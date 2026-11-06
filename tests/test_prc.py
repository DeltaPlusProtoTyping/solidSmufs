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
from solidsmufs.formats.prc import schema as prc_schema, tess, tree  # noqa: E402
from solidsmufs.kernel import meshio  # noqa: E402
from solidsmufs.kernel.worker import _placed_piece  # noqa: E402

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


def move(x=0.0, y=0.0, z=0.0):
    m = np.eye(4)
    m[:3, 3] = x, y, z
    return m


def product(**kw):
    return {"name": "", "style": 0, "part": 0, "prototype": 0, "prototype_file": None, "external": 0, "external_file": None,
            "children": [], "location": None, **kw}


def part(tess_number, style=0):
    return {"name": "", "style": style, "items": [tree.Item("", 0, 0, tess_number)]}


class Placing(unittest.TestCase):
    def at(self, files, by_id=None, roots=()):
        return [(f, n, m[:3, 3].tolist()) for f, n, m, _name, _c in tree.placements(files, by_id or {}, roots)]

    def test_locations_add_up_from_the_root_down(self):
        files = [{"parts": [part(1)], "globals": None, "products": [
            product(part=1, location=move(x=1)), product(children=[0], location=move(y=2))]}]
        self.assertEqual(self.at(files), [(0, 0, [1, 2, 0])])

    def test_one_part_placed_twice_comes_out_twice(self):
        files = [{"parts": [part(1)], "globals": None, "products": [
            product(part=1, location=move(x=1)), product(part=1, location=move(x=5)), product(children=[0, 1])]}]
        self.assertEqual(self.at(files), [(0, 0, [1, 0, 0]), (0, 0, [5, 0, 0])])

    def test_a_prototype_is_looked_through_keeping_its_location(self):
        files = [{"parts": [part(1)], "globals": None, "products": [
            product(part=1, location=move(z=1)), product(prototype=1, location=move(z=3))]}]
        self.assertEqual(self.at(files), [(0, 0, [0, 0, 4])])

    def test_a_prototype_can_be_in_another_file_structure(self):
        uid = (1, 2, 3, 4)
        files = [{"parts": [part(7)], "products": [product(part=1)], "globals": None},
                 {"parts": [], "products": [product(prototype=1, prototype_file=uid)], "globals": None}]
        self.assertEqual(self.at(files, {uid: 0}), [(0, 6, [0, 0, 0])])

    def test_every_active_root_counts(self):
        a, b = (1, 1, 1, 1), (2, 2, 2, 2)
        files = [{"parts": [part(1)], "products": [product(part=1)], "globals": None},
                 {"parts": [part(2)], "products": [product(part=1)], "globals": None}]
        self.assertEqual(self.at(files, {a: 0, b: 1}, [(a, 1, True), (b, 1, True)]), [(0, 0, [0, 0, 0]), (1, 1, [0, 0, 0])])
        self.assertEqual(self.at(files, {a: 0, b: 1}, [(a, 1, False), (b, 1, True)]), [(1, 1, [0, 0, 0])])

    def test_an_assembly_that_loops_is_an_error_not_a_hang(self):
        files = [{"parts": [], "globals": None, "products": [product(children=[0])]}]
        with self.assertRaises(PrcError):
            self.at(files)

    def test_colours_come_from_styles_through_materials_and_textures(self):
        data = {"colors": [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], "styles": [(False, 1), (True, 1), (True, 2)],
                "materials": [(False, 4), (True, 1)], "coords": []}
        self.assertEqual(tree.style_color(data, 1), (1.0, 0.0, 0.0))  # a plain colour; indices count components
        self.assertEqual(tree.style_color(data, 2), (0.0, 1.0, 0.0))  # a material's diffuse
        self.assertEqual(tree.style_color(data, 3), (0.0, 1.0, 0.0))  # a texture over that material
        self.assertIsNone(tree.style_color(data, 0))
        self.assertIsNone(tree.style_color(None, 1))


class SchemaPrograms(unittest.TestCase):
    def run_it(self, tokens, text):
        b = bits(text)
        b.schema = {99: tokens}
        prc_schema.extend(b, 99)
        return b.i

    def test_a_block_for_a_newer_version_is_read(self):
        tokens = [prc_schema.BLOCK_VERSION, 15000, prc_schema.BOOLEAN, prc_schema.BLOCK_END]
        self.assertEqual(self.run_it(tokens, "1"), 1)

    def test_a_block_for_a_version_we_know_is_passed_over(self):
        tokens = [prc_schema.BLOCK_VERSION, 8000, prc_schema.BOOLEAN, prc_schema.BLOCK_END]
        self.assertEqual(self.run_it(tokens, "1"), 0)

    def test_conditions_and_loops(self):
        ifs = [prc_schema.IF, prc_schema.EQ, prc_schema.CONSTANT, 1, prc_schema.BOOLEAN, prc_schema.CHARACTER,
               prc_schema.ELSE, prc_schema.BOOLEAN]
        self.assertEqual(self.run_it(ifs, "1 00000000"), 9)
        self.assertEqual(self.run_it(ifs, "0 1"), 2)
        loop = [prc_schema.SIMPLE_FOR, prc_schema.BOOLEAN]
        self.assertEqual(self.run_it(loop, "1 00000011 0 111"), 13)

    def test_no_schema_reads_nothing(self):
        b = bits("1")
        prc_schema.extend(b, 99)
        self.assertEqual(b.i, 0)

    def test_a_program_running_off_its_end_is_an_error(self):
        with self.assertRaises(PrcError):
            self.run_it([prc_schema.BLOCK_START, prc_schema.BOOLEAN], "1")


class Uncompressed(unittest.TestCase):
    def test_fans_and_strips_become_triangles(self):
        self.assertEqual(prc._triangles_of(prc.FANS, 4), [(0, 1, 2), (0, 2, 3)])
        self.assertEqual(prc._triangles_of(prc.STRIPS, 4), [(0, 1, 2), (2, 1, 3)])
        self.assertEqual(prc._triangles_of(prc.TRIANGLES, 3), ((0, 1, 2),))

    def test_a_face_counts_its_corners_for_its_colours(self):
        # 2 triangles, then 2 fans of 3 and 4 (one carrying the flag that isn't part of its size)
        self.assertEqual(prc._corners_in(0x2 | 0x4, [2, 2, 3, 4 | prc._NORMAL_SINGLE]), 13)

    def test_group_sizes_that_run_short_say_so(self):
        with self.assertRaises(PrcError):
            prc._corners_in(0x2 | 0x4, [2])


class InstancesOfAPart(unittest.TestCase):
    SQUARE = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
    TRIS = np.array([[0, 1, 2], [0, 2, 3]])

    def piece(self, matrix, source=1, planar=(True,)):
        pts = self.SQUARE @ matrix[:3, :3].T + matrix[:3, 3]
        return ("p", pts, self.TRIS, np.zeros(2, np.int64), None, list(planar), None, (source, matrix))

    def test_later_instances_match_working_them_out_afresh(self):
        turn = move(x=10)
        turn[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        shared = meshio.from_faces("x", "x", "t", [self.piece(np.eye(4)), self.piece(turn)])
        alone = meshio.from_faces("x", "x", "t", [self.piece(turn, source=2)])
        self.assertEqual(shared.edge_type[len(alone.edge_type):], alone.edge_type)
        for a, b in zip(shared.edge_params[len(alone.edge_params):], alone.edge_params):
            for k in ("start", "end"):
                np.testing.assert_allclose(a[k], b[k], atol=1e-9)
        np.testing.assert_allclose(shared.positions[4:], alone.positions, atol=1e-5)

    def test_a_mirrored_or_scaled_instance_is_worked_out_afresh(self):
        mirror = np.diag([-1.0, 1.0, 1.0, 1.0])
        m = meshio.from_faces("x", "x", "t", [self.piece(np.eye(4)), self.piece(mirror)])
        self.assertEqual(len(m.bodies), 2)
        self.assertIsNone(meshio._rigid_between(np.eye(4), mirror))
        self.assertIsNone(meshio._rigid_between(np.eye(4), np.diag([2.0, 2.0, 2.0, 1.0])))
        self.assertIsNotNone(meshio._rigid_between(np.eye(4), move(x=3)))

    def test_a_mirrored_part_keeps_facing_outward(self):
        piece = prc.Piece(self.SQUARE, self.TRIS, np.zeros(2, np.int64), None, None, 0.0, {})
        _n, pts, tris, *_rest = _placed_piece(prc.Placed(piece, np.diag([-1.0, 1.0, 1.0, 1.0]), "", None), 1.0, "d")
        a, b, c = pts[tris[0]]
        self.assertGreater(np.cross(b - a, c - a)[2], 0)  # as the unmirrored square faces

    def test_units_scale_the_placed_points(self):
        piece = prc.Piece(self.SQUARE, self.TRIS, np.zeros(2, np.int64), None, None, 0.0, {})
        _n, pts, *_rest = _placed_piece(prc.Placed(piece, move(x=1), "", None), 25.4, "d")
        np.testing.assert_allclose(pts[0], [25.4, 0, 0])


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
        self.assertIsNone(self.file.tree_problem)
        self.assertEqual(len(self.file.placed), 1)
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
