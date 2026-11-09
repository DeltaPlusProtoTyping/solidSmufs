"""What hovering a print's words shows: sizes in inches, ISO fits (H holes, h shafts), French in English, and how the
words are put back together from a page's letters."""

import unittest

from solidsmufs.kernel import fits, printmarks


def letters(text, x=100.0, y=50.0, size=10.0, adv=6.0):
    """A line of letters as a PDF gives them: (letter, x0, y0, x1, y1), spaces with no box."""
    out = []
    for ch in text:
        out.append((ch, 0, 0, 0, 0) if ch == " " else (ch, x, y, x + adv * 0.8, y + size))
        x += adv
    return out


class DescribeTest(unittest.TestCase):
    def test_fit_limits(self):
        kind, tip = printmarks.describe("Ø25 H7")
        self.assertEqual(kind, "fit")
        self.assertIn("hole", tip)
        self.assertIn("25.000 to 25.021 mm", tip)
        self.assertIn("0.9843 to 0.9851 in", tip)
        kind, tip = printmarks.describe("Ø12 g6")
        self.assertIn("shaft", tip)
        self.assertIn("11.983 to 11.994 mm", tip)

    def test_tolerances_in_inches(self):
        self.assertEqual(printmarks.describe("120 ±0.1"), ("dim", "4.7244 ±0.0039 in\n4.7205 to 4.7283 in"))
        kind, tip = printmarks.describe("45 +0.05/-0.02")
        self.assertTrue(tip.startswith("1.7717 +0.0020 / -0.0008 in"))
        self.assertEqual(printmarks.describe("R0,5"), ("dim", "R0.0197 in"))

    def test_not_sizes(self):
        for text in ("6061", "M6", "SHEET", "0125", "7075"):
            self.assertIsNone(printmarks.describe(text), text)

    def test_ocr_slips(self):
        self.assertEqual(printmarks.describe("Ø25 1-17", ocr=True)[0], "fit")  # H7 read as 1-17
        self.assertIn("check H vs h", printmarks.describe("Ø25 H7", ocr=True)[1])

    def test_fit_table(self):
        lim = fits.limits(30, "h6")
        self.assertEqual((lim["lo_um"], lim["hi_um"]), (-13, 0))


class WordsTest(unittest.TestCase):
    def test_lines_from_the_pdfs_text_order(self):
        brk = [("\n", 0, 0, 0, 0)]
        chars = (letters("Ø25 H7") + brk + letters("NE PAS MESURER SUR LE PLAN", y=80) + brk
                 + letters("ebavurer toutes les aretes vives", y=100) + brk + letters("MATIERE : 6061-T6", y=120))
        lines = printmarks.word_lines(chars)
        self.assertEqual([[w[0] for w in ln] for ln in lines[:2]], [["Ø25", "H7"], ["NE", "PAS", "MESURER", "SUR", "LE", "PLAN"]])
        marks, texts, words = printmarks.text_marks(chars)
        fit = next(m for m in marks if m["kind"] == "fit")
        self.assertEqual(fit["text"], "Ø25 H7")
        self.assertAlmostEqual(fit["x"], 100.0)
        self.assertAlmostEqual(fit["w"], 5 * 6 + 4.8)
        self.assertTrue(any(m["kind"] == "fr" and "DO NOT SCALE" in m["tip"] for m in marks))

    def test_one_letter_per_line_is_rebuilt(self):
        chars = []
        for c in letters("Ø40 H8"):
            if c[0] != " ":
                chars += [c, ("\n", 0, 0, 0, 0)]  # a CAD export: every letter its own line
            else:
                chars += [c]
        lines = printmarks.word_lines(chars)
        self.assertEqual(" ".join(w[0] for w in lines[0]), "Ø40 H8")

    def test_merge_keeps_the_pdfs_own_reading(self):
        have = [{"x": 0, "y": 0, "w": 10, "h": 5, "kind": "fit", "text": "Ø25 H7", "tip": "", "ocr": False}]
        new = [{**have[0], "ocr": True, "x": 2}, {**have[0], "ocr": True, "x": 50}]
        out = printmarks.merge(have, new)
        self.assertEqual([m["x"] for m in out], [0, 50])

    def test_metric_or_not(self):
        self.assertTrue(printmarks.is_metric(["ALL DIMENSIONS IN mm"]))
        self.assertTrue(printmarks.is_metric(["Rayons non cotes R0,5", "MATIERE : 6061"]))
        self.assertFalse(printmarks.is_metric(["DIMENSIONS ARE IN INCHES", "1/4-20 UNC"]))


if __name__ == "__main__":
    unittest.main()
