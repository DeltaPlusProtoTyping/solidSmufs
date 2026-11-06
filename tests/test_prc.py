"""Tests for reading 3D models out of PDFs (PRC).

    .venv/Scripts/python -m unittest tests.test_prc -v
"""

import struct
import sys
import unittest
import zlib
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidsmufs.formats import prc  # noqa: E402
from solidsmufs.formats.prc.bits import Bits, PrcError  # noqa: E402
from solidsmufs.formats.prc import tess  # noqa: E402

# a real 3D PDF, when this PC has it: McMaster-Carr's 4-40 x 5/8 button head screw
SCREW = Path.home() / "Downloads" / "90910A721_3D_Button Head Screws.pdf"


def bits(text):
    text = text.replace(" ", "")
    text += "0" * (-len(text) % 8)
    return Bits(int(text, 2).to_bytes(len(text) // 8, "big"))


class BitStream(unittest.TestCase):
    def test_unsigned_integers_run_low_byte_first_each_behind_a_flag(self):
        self.assertEqual(bits("0").u(), 0)
        self.assertEqual(bits("1 00110001 1 00000001 0").u(), 305)

    def test_doubles(self):
        self.assertEqual(bits("01").double(), 0.0)  # the code for an exact zero, and no sign follows

    def test_signed_integers_are_sign_then_size(self):
        self.assertEqual(bits("1 101").signed(4), -5)
        self.assertEqual(bits("0 101").signed(4), 5)

    def test_running_out_is_an_error_not_a_crash(self):
        with self.assertRaises(PrcError):
            bits("1").read(64)

    def test_uncompressed_shorts_are_low_byte_first(self):
        b = bits("0 1 00000001 0  00000010 00000001")  # not compressed, one entry, 0x0102
        self.assertEqual(b.huffman(16, True, wide=True), [0x0102])


class Arithmetic(unittest.TestCase):
    def test_length_comes_from_the_square_in_single_precision(self):
        # 1 + 1e-9 is 1 in single precision, so this "length" is exactly 1, which a true root isn't
        self.assertEqual(tess._length((1.0, 3.2e-5, 0.0)), 1.0)
        self.assertAlmostEqual(tess._length((3.0, 4.0, 0.0)), 5.0, 12)

    def test_too_short_has_no_direction(self):
        self.assertIsNone(tess._unit((1e-9, 0.0, 0.0)))
        self.assertIsNone(tess._unit((0.0, 0.0, 0.0)))

    def test_bits_in_a_reference_to_a_normal(self):
        self.assertEqual([tess._reference_bits(n) for n in (0, 1, 2, 3, 4, 5)], [1, 1, 2, 3, 3, 4])

    def test_the_series_match_the_true_functions(self):
        for x in (0.0, 0.2, 0.7, 1.0, 1.5):
            self.assertAlmostEqual(tess._sin(x), np.sin(x), 5)
            self.assertAlmostEqual(tess._cos(x), np.cos(x), 5)

    def test_a_flat_triangle_still_gives_a_frame(self):
        # the triangle behind the edge lies on the edge's line: the fallback axis sets where the corner goes
        p = tess._apex((1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (2.0, 0.0, 0.0), 0, 0, 2, 0.5)
        self.assertAlmostEqual(abs(p[2]), 1.0, 9)


class Traversal(unittest.TestCase):
    def rebuild(self, ints, edges, faces, flags, refs, reverse):
        return tess.rebuild(1.0, (0.0, 0.0, 0.0), ints, edges, faces, np.array(flags, bool), refs, reversed_flags=reverse)

    def test_one_triangle_is_predicted_from_the_origin_then_its_corners(self):
        pts, tris, normals, unread = self.rebuild([1, 2, 3, 4, 0, 0, 0, 5, 0], [0], [0], [0, 0, 0], [], [True])
        self.assertEqual(pts.tolist(), [[1, 2, 3], [5, 2, 3], [3, 7, 3]])
        self.assertEqual(tris.tolist(), [[0, 1, 2]])
        self.assertIsNone(normals)
        self.assertEqual(set(unread.values()), {0})

    def test_unreversed_triangles_run_the_other_way(self):
        _pts, tris, _n, _u = self.rebuild([0, 0, 0, 4, 0, 0, 0, 5, 0], [0], [0], [0, 0, 0], [], [False])
        self.assertEqual(tris.tolist(), [[0, 2, 1]])

    def test_an_empty_stack_starts_again_rather_than_stopping(self):
        ints = [0, 0, 0, 4, 0, 0, 0, 5, 0, 9, 9, 9, 4, 0, 0, 0, 5, 0]
        pts, tris, _n, unread = self.rebuild(ints, [0, 0], [0, 0], [0] * 6, [], [True, True])
        self.assertEqual(len(tris), 2)
        self.assertEqual(len(pts), 6)
        self.assertEqual(unread["points"], 0)

    def test_a_new_start_can_reuse_points(self):
        ints = [0, 0, 0, 4, 0, 0, 0, 5, 0, 0, 0, 1]
        pts, tris, _n, _u = self.rebuild(ints, [0, 0], [0, 0], [0, 0, 0, 1, 1, 0], [0, 1], [True, True])
        self.assertEqual(tris.tolist()[1], [0, 1, 3])
        self.assertEqual(pts[3].tolist(), [2, 0, 1])  # from the midpoint of the two it reused

    def test_the_next_triangle_grows_on_the_left_edge_first(self):
        # status 3: right and left both have neighbours; left is pushed last, so it's next
        ints = [0, 0, 0, 2, 0, 0, 0, 2, 0, 0, 3, 0]
        _pts, tris, _n, _u = self.rebuild(ints, [3, 0], [0, 0], [0, 0, 0, 0], [], [False, False])
        self.assertIn(0, tris[1])  # the left edge runs from the first corner to the new one
        self.assertIn(2, tris[1])
        self.assertNotIn(1, tris[1])

    def test_a_bad_reference_is_an_error(self):
        with self.assertRaises(PrcError):
            self.rebuild([0, 0, 0], [0], [0], [1, 0, 0], [5], [True])


class InThePdf(unittest.TestCase):
    PRC = b"PRC" + b"\0" * 20

    def pdf(self, entry):
        return b"%PDF-1.6\n1 0 obj 5 endobj\n" + entry + b"\ntrailer\n"

    def test_a_raw_stream_with_its_length(self):
        body = self.PRC + b"endstream inside the data"  # the length says it isn't the end
        data = self.pdf(b"11 0 obj\r<</Length %d/Subtype/PRC/Type/3D>>stream\r%s\rendstream\rendobj" % (len(body), body))
        self.assertEqual(prc.streams_in_pdf(data), [body])

    def test_a_compressed_stream_with_its_length_held_elsewhere(self):
        z = zlib.compress(self.PRC)
        data = self.pdf(b"11 0 obj\n<</Filter[/FlateDecode]/Length 7 0 R/Subtype /PRC>>\nstream\r\n%s\nendstream endobj\n7 0 obj %d endobj"
                        % (z, len(z)))
        self.assertEqual(prc.streams_in_pdf(data), [self.PRC])

    def test_anything_else_is_passed_over(self):
        self.assertEqual(prc.streams_in_pdf(self.pdf(b"<</Length 3/Subtype/U3D>>stream\nabc\nendstream")), [])
        self.assertEqual(prc.streams_in_pdf(self.pdf(b"<</Length 3/Subtype/PRC>>stream\nabc\nendstream")), [])

    def test_a_header_that_isnt_prc_says_so(self):
        with self.assertRaises(PrcError):
            prc.read_prc(b"nope")


@unittest.skipUnless(SCREW.is_file(), "the sample 3D PDF isn't on this PC")
class RealScrew(unittest.TestCase):
    """Nothing here can pass by luck: one wrong rule and the bits don't come out even."""

    @classmethod
    def setUpClass(cls):
        cls.file = prc.read_pdf(SCREW)[0]
        cls.piece = cls.file.pieces[0]

    def test_it_is_in_inches(self):
        self.assertEqual(self.file.unit_mm, 25.4)

    def test_every_bit_of_the_mesh_is_used_up(self):
        self.assertEqual(self.piece.unread, {"normal_bits": 0, "angles": 0, "points": 0, "references": 0, "flags": 0})
        self.assertEqual((len(self.piece.points), len(self.piece.triangles)), (14799, 29594))

    def test_it_comes_out_a_closed_consistently_wound_solid(self):
        edges = Counter()
        for a, b, c in self.piece.triangles.tolist():
            edges.update([(a, b), (b, c), (c, a)])
        loose = sum(1 for (u, v), n in edges.items() if edges.get((v, u), 0) != n)
        self.assertLess(loose / len(edges), 0.001)  # those left are triangles the file rounded to nothing
        p, t = self.piece.points, self.piece.triangles
        volume = np.einsum("ij,ij->i", p[t[:, 0]], np.cross(p[t[:, 1]], p[t[:, 2]])).sum() / 6
        self.assertGreater(volume, 0)

    def test_its_size_matches_mcmasters_sheet(self):
        size = np.ptp(self.piece.points, axis=0)
        self.assertAlmostEqual(size[0], 0.213, 3)  # head diameter
        self.assertAlmostEqual(size[2], 0.625 + 0.059, 2)  # length under the head, and the head

    def test_opening_it_gives_real_faces_to_measure(self):
        from solidsmufs.kernel.worker import Session
        s = Session()
        meta = s.open(str(SCREW))["meta"]
        self.assertEqual(meta["format"], "3D PDF (PRC)")
        self.assertEqual(meta["pdf"]["models"], ["PRC"])
        self.assertEqual(Counter(meta["faces"]["type"])["plane"], 4)
        self.assertTrue(meta["bodies"][0]["closed"])
        head = max((p["radius"] for t, p in zip(meta["faces"]["type"], meta["faces"]["params"]) if t == "cylinder"))
        self.assertAlmostEqual(head * 2 / 25.4, 0.213, 3)
        s.pdf.close()


if __name__ == "__main__":
    unittest.main()
