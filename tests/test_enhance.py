"""Cleaning up a scanned print (kernel/enhance.py, and Pages > Enhance scan in kernel/pdfedit.py): the paper made white,
the ink solid, specks off with decimal points kept, the page straightened, and nothing on the page retyped."""

import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pymupdf  # noqa: E402

from solidsmufs.kernel import enhance  # noqa: E402

TEXTS = ["2.500 ±.005", "Ø.375 +.002/-.000 THRU", ".436", "BREAK ALL SHARP EDGES .005-.015"]


def _clean_print(dpi=200):
    """The print drawn clean, as ink (True) at `dpi`."""
    d = pymupdf.open()
    pg = d.new_page(width=792, height=612)
    pg.draw_rect(pymupdf.Rect(30, 30, 762, 582), width=1.5)
    for i, t in enumerate(TEXTS):
        pg.insert_text((120, 120 + 60 * i), t, fontsize=14)
    pg.draw_circle((550, 350), 60, width=1.0)
    return enhance.gray(pg.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)) < 128


def _bad_scan(angle=1.5, specks=2000, dpi=200):
    """That print scanned badly: turned, on a shadowed gray background, with specks."""
    m = enhance.turn(_clean_print(dpi), -angle)
    h, w = m.shape
    rng = np.random.default_rng(1)
    yy, xx = np.mgrid[0:h, 0:w]
    bg = 235 - 60 * (xx / w) ** 3 - 30 * (yy / h)
    img = np.where(m, 70 + rng.integers(0, 40, (h, w)), bg + rng.normal(0, 6, (h, w)))
    for _ in range(specks):
        y, x = rng.integers(2, h - 3), rng.integers(2, w - 3)
        img[y:y + 2, x:x + 2] = 40
    return np.clip(img, 0, 255).astype(np.uint8)


def _near(m, n=2):
    for _ in range(n):
        p = np.pad(m, 1)
        m = m | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
    return m


class Cleaning(unittest.TestCase):
    def test_paper_goes_white_and_shadows_go(self):
        g = _bad_scan(angle=0, specks=0)
        m = enhance.ink(g, 200)
        truth = _clean_print()
        self.assertLess((m & ~_near(truth)).sum(), 0.001 * m.size)  # the shadowed corner isn't ink
        self.assertLess((truth & ~_near(m)).sum(), 0.001 * truth.sum())  # and every line is

    def test_the_page_is_straightened(self):
        for angle in (1.5, -2.2, 0.6):
            m = enhance.turn(_clean_print(), -angle)
            self.assertAlmostEqual(enhance.skew(m, 200), angle, delta=0.05)
        self.assertEqual(enhance.skew(_clean_print(), 200), 0.0)
        level = enhance.turn(enhance.turn(_clean_print(), -1.5), 1.5)
        self.assertEqual(enhance.skew(level, 200), 0.0)

    def test_a_pixel_gap_in_a_line_is_joined(self):
        m = np.zeros((20, 40), bool)
        m[10, 5:35] = True
        m[10, 20] = False
        self.assertTrue(enhance.bridge(m)[10, 5:35].all())
        self.assertEqual(int(enhance.bridge(m).sum()), 30)  # nothing grew fatter

    def test_specks_go_and_decimal_points_stay(self):
        for font in ("helv", "cour", "tiro"):
            for size in (6, 8, 12):
                d = pymupdf.open()
                pg = d.new_page(width=300, height=60)
                pg.insert_text((10, 30), ".005 .436 1.2 (.5) 0.001 A.", fontsize=size, fontname=font)
                m = enhance.gray(pg.get_pixmap(dpi=300, colorspace=pymupdf.csGRAY)) < 128
                for strength in (1, 2):
                    kept = enhance.despeckle(m, enhance.SPECKS[strength])
                    self.assertEqual(int((m & ~kept).sum()), 0, (font, size, strength))
        open_paper = np.zeros((200, 200), bool)
        for y, x in [(20, 20), (60, 150), (120, 40), (170, 170), (170, 176)]:  # (the last two close: they go together)
            open_paper[y:y + 2, x:x + 2] = True
        self.assertFalse(enhance.despeckle(open_paper, 3).any())
        blot = np.zeros((60, 60), bool)
        blot[20:28, 20:28] = True  # bigger than a speck: it stays, for whoever reads it to judge
        self.assertTrue((enhance.despeckle(blot, 5) == blot).all())

    def test_the_whole_clean_up(self):
        out, angle = enhance.clean(_bad_scan(), 200, specks=1)
        self.assertAlmostEqual(angle, 1.5, delta=0.05)
        m = out == 0
        truth = _clean_print()
        self.assertLess((truth & ~_near(m)).sum(), 0.001 * truth.sum())
        self.assertEqual(set(np.unique(out)), {0, 255})  # black on white


class EnhanceScan(unittest.TestCase):
    def setUp(self):
        from solidsmufs.kernel.pdfdoc import PdfFile
        from solidsmufs.kernel.pdfedit import PdfEditor
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "scan.pdf"
        d = pymupdf.open()
        p = d.new_page(width=792, height=612)  # a scan
        p.insert_image(p.rect, stream=enhance.png(_bad_scan(), 200))
        p.add_text_annot((60, 60), "a comment stays")
        v = d.new_page(width=792, height=612)  # a print from CAD
        v.insert_text((100, 100), "2.500 ±.005", fontsize=12)
        d.save(self.path)
        d.close()
        self.pdf = PdfFile(str(self.path))
        self.ed = PdfEditor(self.pdf, self.path)

    def tearDown(self):
        self.pdf.close()
        self.dir.cleanup()

    def test_preview_changes_nothing(self):
        r = self.ed.run("enhance_preview", {"page": 0})
        self.assertTrue(r["scan"])
        self.assertAlmostEqual(r["angle"], 1.5, delta=0.1)
        self.assertTrue(r["before"].startswith("data:image/png;base64,") and r["after"].startswith("data:image/png;base64,"))
        self.assertEqual(self.ed.run("enhance_preview", {"page": 1}), {"scan": False})
        self.assertFalse(self.ed.state()["dirty"])

    def test_scanned_pages_are_cleaned_and_others_left(self):
        before = self.pdf.fz[1].get_text()
        r = self.ed.run("enhance", {"text": False})["result"]
        self.assertEqual((r["enhanced"], r["skipped"]), ([0], [1]))
        self.assertAlmostEqual(r["angles"][0], 1.5, delta=0.05)
        pg = self.pdf.fz[0]
        self.assertEqual(len(pg.get_images()), 1)  # the cleaned picture in place of the scan
        self.assertEqual([a.info["content"] for a in pg.annots()], ["a comment stays"])
        self.assertEqual(self.pdf.fz[1].get_text(), before)
        out = enhance.gray(pg.get_pixmap(dpi=100, colorspace=pymupdf.csGRAY, annots=False))
        self.assertGreater((out > 250).mean(), 0.95)  # white paper
        self.ed.run("undo", {})
        self.assertEqual(len(self.pdf.fz[0].get_images()), 1)
        with self.assertRaises(ValueError):  # a print from CAD only: nothing to clean
            self.ed.run("enhance", {"pages": [1]})

    def test_a_scan_printed_inside_margins_in_strips(self):
        # (Microsoft Print to PDF puts a scanned picture inside an inch of margin, cut into strips)
        path = Path(self.dir.name) / "printed.pdf"
        img = _bad_scan()
        d = pymupdf.open()
        p = d.new_page(width=612, height=792)
        h = img.shape[0] // 3
        for k in range(3):
            p.insert_image(pymupdf.Rect(72, 72 + 117 * k, 540, 72 + 117 * (k + 1)), stream=enhance.png(img[k * h:(k + 1) * h], 200))
        d.save(path)
        d.close()
        d = pymupdf.open(path)
        self.assertTrue(enhance.scanned(d[0]))
        self.assertFalse(enhance.scanned(self.pdf.fz[1]))  # a print from CAD with a logo is no scan
        logo = self.pdf.fz[1]
        for i in range(100):  # (a real print from CAD is hundreds of lines)
            logo.draw_line((50, 100 + 4 * i), (380, 100 + 4 * i))
        logo.insert_image(pymupdf.Rect(400, 400, 600, 600), stream=enhance.png(_bad_scan(angle=0, specks=0)[:300, :300]))
        self.assertFalse(enhance.scanned(logo))

    def test_turned_page_stays_turned(self):
        self.pdf.fz[0].set_rotation(90)
        self.ed.run("enhance", {"pages": [0], "text": False})
        pg = self.pdf.fz[0]
        self.assertEqual(pg.rotation, 90)
        self.assertEqual((round(pg.rect.width), round(pg.rect.height)), (612, 792))

    @unittest.skipUnless(__import__("sys").platform == "win32", "Windows OCR")
    def test_hidden_text_is_searchable_and_unseen(self):
        from solidsmufs.kernel import printmarks
        if not printmarks.ocr_available():
            self.skipTest("no Windows OCR")
        r = self.ed.run("enhance", {"pages": [0]})["result"]
        self.assertTrue(r["read"])
        self.assertGreater(r["lines"], 0)
        pg = self.pdf.fz[0]
        hit = pg.search_for(".436")
        self.assertTrue(hit)
        self.assertLess(abs(hit[0].y1 - 240), 8)  # under where it's printed (its baseline at 240, straightened)
        trace = pg.get_texttrace()
        self.assertTrue(trace and all(t["type"] == 3 for t in trace))  # invisible: drawn with render mode 3


if __name__ == "__main__":
    unittest.main()
