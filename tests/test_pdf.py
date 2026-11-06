"""Tests for PDF pages.

    .venv/Scripts/python -m unittest tests.test_pdf -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidsmufs.kernel.pdfdoc import PdfFile, models_inside  # noqa: E402


def small_pdf(extra=b""):
    """Two pages of black text, written by hand."""
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R 4 0 R]/Count 2>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 5 0 R/Resources<</Font<</F1 6 0 R>>>>>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 400]/Contents 5 0 R/Resources<</Font<</F1 6 0 R>>>>>>",
            None, b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    text = b"BT /F1 18 Tf 10 40 Td (Button head) Tj ET"
    objs[4] = b"<</Length %d>>stream\n%s\nendstream" % (len(text), text)
    out, offsets = bytearray(b"%PDF-1.5\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, o)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offsets:
        out += b"%010d 00000 n \n" % o
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out) + extra


class Pages(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "t.pdf"
        self.path.write_bytes(small_pdf())
        self.pdf = PdfFile(self.path)
        self.addCleanup(self.pdf.close)

    def test_page_sizes(self):
        self.assertEqual([(p["w"], p["h"]) for p in self.pdf.pages()], [(200, 100), (300, 400)])

    def test_a_tile_is_opaque_white_paper_with_ink_on_it(self):
        px = np.frombuffer(self.pdf.tile(0, 2.0, 0, 0, 400, 200), np.uint8).reshape(200, 400, 4)
        self.assertTrue((px[..., 3] == 255).all())
        self.assertEqual(px[0, 0, :3].tolist(), [255, 255, 255])
        self.assertLess(px[..., 0].min(), 60)

    def test_a_piece_of_the_page_matches_the_whole(self):
        def ink(*spec):
            w, h = spec[-2:]
            ys, xs = np.where(np.frombuffer(self.pdf.tile(0, 2.0, *spec), np.uint8).reshape(h, w, 4)[..., 0] < 128)
            return xs.min() + spec[0], xs.max() + spec[0], ys.min() + spec[1], ys.max() + spec[1]
        whole, part = ink(0, 0, 400, 200), ink(0, 50, 400, 150)  # the same ink, the same place, to the pixel
        self.assertEqual(whole, part)

    def test_a_quarter_turn_swaps_the_sides(self):
        self.assertEqual(len(self.pdf.tile(0, 1.0, 0, 0, 100, 200, 1)), 100 * 200 * 4)

    def test_find_gives_each_place_in_points(self):
        hits = self.pdf.find("HEAD")
        self.assertEqual([h["page"] for h in hits], [0, 1])
        x, y, w, h = hits[0]["rects"][0]
        self.assertTrue(0 < x < 200 and 0 < y < 100 and w > 5 and h > 5)

    def test_select_reads_the_text_between_two_points(self):
        x, y, w, h = self.pdf.find("Button")[0]["rects"][0]
        self.assertIn("Button", self.pdf.select(0, x, y + h / 2, x + w, y + h / 2)["text"])

    def test_no_model_inside(self):
        self.assertEqual(models_inside(self.path), [])

    def test_model_kinds_inside(self):
        self.path.write_bytes(small_pdf(b"\n9 0 obj<</Length 0/Subtype/PRC/Type/3D>>stream\nendstream endobj"))
        self.assertEqual(models_inside(self.path), ["PRC"])

    def test_damaged_files_say_so(self):
        bad = Path(self.dir.name) / "bad.pdf"
        bad.write_bytes(b"not a pdf at all")
        with self.assertRaises(ValueError):
            PdfFile(bad)


if __name__ == "__main__":
    unittest.main()
