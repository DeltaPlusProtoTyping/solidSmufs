"""Geometric tolerances on a print (kernel/gdt.py): reading a feature control frame three ways, what it says on
hover, and the difficulty scores (a first guess: the numbers here move when the tables are tuned)."""

import unittest

from solidsmufs.kernel import gdt, printmarks


def got(text, ocr=False):
    g = gdt.read(text, ocr)
    return g and (g["kind"], g["dia"], g["tol"], g["mmc"], g["datums"])


class Reading(unittest.TestCase):
    def test_the_symbols_themselves(self):
        self.assertEqual(got("⌖ Ø.005 Ⓜ A B C"), ("position", True, ".005", "M", ["A", "B", "C"]))
        self.assertEqual(got("⌖ | Ø.005 Ⓜ | A | B | C"), ("position", True, ".005", "M", ["A", "B", "C"]))
        self.assertEqual(got("⏥ .002"), ("flatness", False, ".002", None, []))
        self.assertEqual(got("⊥ 0,05 A"), ("perpendicularity", False, "0,05", None, ["A"]))
        self.assertEqual(got("⌓ .020 A B-C"), ("profile of a surface", False, ".020", None, ["A", "B-C"]))

    def test_a_gdt_fonts_letters(self):
        self.assertEqual(got("j n.010m A B"), ("position", True, ".010", "M", ["A", "B"]))
        self.assertEqual(got("jn.005mABC"), ("position", True, ".005", "M", ["A", "B", "C"]))
        self.assertEqual(got("c .002"), ("flatness", False, ".002", None, []))
        self.assertEqual(got("t .001 A"), ("total runout", False, ".001", None, ["A"]))

    def test_ocr_without_the_symbol(self):
        self.assertEqual(got("Ø.005 0 A B c", True), ("position", True, ".005", None, ["A", "B", "C"]))  # C read as c
        self.assertEqual(gdt.read("Ø.005 0 A B c", True)["mods"], ["?"])  # a circled letter read as 0: which one, the picture says
        self.assertEqual(got("$ 00.005 (M) A B C", True), ("position", True, "0.005", "M", ["A", "B", "C"]))  # Ø0.005 read as 00.005
        self.assertEqual(got("$ 0.005 (M) A B C", True), ("geometric tolerance", False, "0.005", "M", ["A", "B", "C"]))  # no Ø in it
        self.assertEqual(got("4 .005 A B C", True), ("geometric tolerance", False, ".005", None, ["A", "B", "C"]))
        self.assertIn("almost always position", gdt.tip(gdt.read("Ø.005 0 A B c", True)))

    def test_words(self):
        self.assertEqual(got("TRUE POSITION .010"), ("position", False, ".010", None, []))
        self.assertEqual(got("TP Ø0.1 mm")[:3], ("position", True, "0.1"))

    def test_what_isnt_one(self):
        for text, ocr in (("a 0.5", False), ("2X Ø.250", False), ("R.030", False), (".25 A", True), ("b 0.5 mm", False),
                          (".010 a b", True), ("NOTE 3 .010 TO DATUM A", True), ("4X Ø.250 THRU", True)):
            self.assertIsNone(gdt.read(text, ocr), text)


class Scoring(unittest.TestCase):
    def test_inch_or_mm_by_the_leading_zero(self):
        self.assertAlmostEqual(gdt.tol_mm(".005"), 0.127)
        self.assertAlmostEqual(gdt.tol_mm("0,05"), 0.05)
        self.assertAlmostEqual(gdt.tol_mm("0.1"), 0.1)
        self.assertAlmostEqual(gdt.tol_mm("0.1", unit="in"), 2.54)

    def test_tighter_is_harder_and_stays_in_range(self):
        hold = [gdt.scores("position", gdt.tol_mm(t))[0] for t in (".0002", ".0005", ".001", ".002", ".005", ".010", ".020", ".060", ".250")]
        self.assertEqual(hold, sorted(hold, reverse=True))
        self.assertEqual((hold[0], hold[-1]), (10, 1))
        self.assertEqual(gdt.scores("position", 0.127), (3, 2))  # .005 in: routine for a good shop
        self.assertEqual(gdt.scores("position", 0.0127), (8, 7))  # .0005 in: hard
        self.assertEqual(gdt.scores("position", 0.127, "M"), (2, 1))  # bonus tolerance, and a gauge can check it
        self.assertGreater(gdt.scores("cylindricity", 0.127), gdt.scores("flatness", 0.127))

    def test_the_tip(self):
        tip = gdt.tip(gdt.read("⌖ Ø.005 Ⓜ A B C"))
        self.assertIn("True position", tip)
        self.assertIn("Ø0.0050 in (0.127 mm)", tip)  # written the inch way, so inches first
        self.assertIn("Datums A, B, C", tip)
        self.assertTrue(tip.endswith("Machining 2/10 · Measuring 1/10"))  # the two scores last
        self.assertLess(max(len(line) for line in tip.splitlines()), 90)  # short lines, read at a glance


class OnAPage(unittest.TestCase):
    def test_a_line_of_words(self):
        line = [("⌖", 10, 10, 20, 20), ("Ø.005", 24, 10, 60, 20), ("Ⓜ", 62, 10, 72, 20), ("A", 80, 10, 88, 20), ("B", 96, 10, 104, 20)]
        marks, _ = printmarks.lines_marks([line], False)
        frame = [m for m in marks if m["kind"] == "gdt"]
        self.assertEqual([(m["x"], m["w"]) for m in frame], [(10, 94)])

    def test_ocr_cells_are_read_across(self):
        """OCR gives a frame's cells as lines of their own: they're one frame."""
        cells = [[("Ø.005", 24, 10, 60, 20), ("0", 62, 10, 72, 20)], [("A", 80, 10, 88, 20)], [("B", 96, 10, 104, 20)],
                 [("FAR", 400, 10, 430, 20)], [("BELOW", 24, 60, 70, 70)]]
        marks, _ = printmarks.lines_marks(cells, True)
        frame = [m for m in marks if m["kind"] == "gdt"]
        self.assertEqual([m["text"] for m in frame], ["Ø.005 0 A B"])


class EveryCallout(unittest.TestCase):
    def test_modifiers_and_datum_modifiers(self):
        g = gdt.read("⌖ Ø0.002 Ⓢ A Ⓢ")
        self.assertEqual((g["kind"], g["tol"], g["mods"], g["datums"], g["dmods"]), ("position", "0.002", ["S"], ["A"], ["S"]))
        self.assertAlmostEqual(gdt.tol_mm("0.002"), 0.0508)  # inches, leading zero or not: nobody asks for two microns
        tip = gdt.tip(g)
        self.assertIn("Regardless of feature size", tip)
        self.assertIn("Datum A Ⓢ", tip)
        g = gdt.read("⌖ Ø.010 Ⓜ Ⓟ .500 A B Ⓜ C")
        self.assertEqual((g["mods"], g["mmc"], g["datums"], g["dmods"]), (["M", "P"], "M", ["A", "B", "C"], [None, "M", None]))
        self.assertIn("Projected tolerance zone", gdt.tip(g))
        g = gdt.read("j n.010m A Bm")  # the same in a GD&T font's letters
        self.assertEqual((g["mods"], g["dmods"]), (["M"], [None, "M"]))
        self.assertEqual(gdt.read("⌓ .020 Ⓤ .005 A")["mods"], ["U"])
        self.assertTrue(gdt.read("⌖ SØ.010 A")["sphere"])

    def test_what_ocr_makes_of_circled_letters(self):
        g = gdt.read("Ø0.002@ A@", True)  # Windows OCR's reading of: position | Ø0.002 Ⓢ | A Ⓢ
        self.assertEqual((g["kind"], g["dia"], g["tol"], g["mods"], g["datums"], g["dmods"], g["guess"]),
                         ("position", True, "0.002", ["?"], ["A"], ["?"], True))
        self.assertEqual(gdt.read("ØO.002@ A@", True)["tol"], "0.002")
        self.assertIn("not read: check the print", gdt.tip(g))
        self.assertEqual(gdt.scores("position", 0.0508), gdt.scores("position", 0.0508, None))  # no bonus guessed at

    def test_hole_callouts(self):
        self.assertIn("Counterbore", gdt.hole_tip("⌴ Ø.500"))
        self.assertIn("12.700 mm", gdt.hole_tip("⌴ Ø.500"))
        self.assertIn("82° is the cone's included angle", gdt.hole_tip("⌵ Ø.380 X 82°"))
        self.assertIn("Depth", gdt.hole_tip("↧ .250"))
        self.assertIn("Counterbore", gdt.hole_tip("v n.500"))
        self.assertIsNone(gdt.hole_tip("x 2"))


class FromThePicture(unittest.TestCase):
    """kernel/gdtsee.py: the symbol and the circled letters, from the pixels (no OCR in these)."""

    @staticmethod
    def frame(symbol, tol="Ø.005", after="A", dpi=300):
        import numpy as np
        import pymupdf
        font = "C:/Windows/Fonts/seguisym.ttf"
        doc = pymupdf.open()
        pg = doc.new_page(width=300, height=90)
        x, boxes = 30, {}
        for text, w, sym in ((symbol, 30, True), (tol, 70, False), (after, 40, False)):
            pg.draw_rect(pymupdf.Rect(x, 30, x + w, 54), color=(0, 0, 0), width=1)
            kw = {"fontname": "ss", "fontfile": font} if sym or any(ord(c) > 0x2000 for c in text) else {}
            pg.insert_text((x + 6, 48), text, fontsize=14, **kw)
            boxes[text] = [v * dpi / 72 for v in (x + 6, 37, x + w - 6, 49)]  # about where OCR would box the word
            x += w
        pix = pg.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)[:, :pix.width].copy()
        for text, (x0, y0, x1, y1) in boxes.items():  # tight around the word's ink, as OCR boxes it
            x0, x1, y0, y1 = int(x0), int(x1), int(y0) - 8, int(y1) + 12
            ys, xs = np.nonzero(img[y0:y1, x0:x1] < 128)
            boxes[text] = [x0 + xs.min(), y0 + ys.min(), x0 + xs.max() + 1, y0 + ys.max() + 1]
        return img, boxes

    @unittest.skipUnless(__import__("os").path.exists("C:/Windows/Fonts/seguisym.ttf"), "needs Segoe UI Symbol to draw the symbols")
    def test_symbols_are_named_and_letters_arent(self):
        from solidsmufs.kernel import gdtsee
        named = 0
        for sign, kind in (("⌖", "position"), ("⏥", "flatness"), ("⊥", "perpendicularity"), ("∥", "parallelism"), ("◎", "concentricity"),
                           ("⌓", "profile of a surface"), ("○", "circularity"), ("⌰", "total runout")):
            img, boxes = self.frame(sign)
            hit = gdtsee.symbol(img, boxes["Ø.005"])
            self.assertIn(hit and hit[0], (kind, None), sign)  # never the wrong one
            named += bool(hit)
        self.assertGreaterEqual(named, 6)
        for letter in ("d", "X", "R", "12"):
            img, boxes = self.frame(letter)
            self.assertIsNone(gdtsee.symbol(img, boxes["Ø.005"]), letter)
        img, boxes = self.frame("⌖")
        self.assertIsNone(gdtsee.symbol(img, [v + 400 for v in boxes["Ø.005"]]))  # no frame there

    @unittest.skipUnless(__import__("os").path.exists("C:/Windows/Fonts/seguisym.ttf"), "needs Segoe UI Symbol to draw the symbols")
    def test_circled_letters(self):
        from solidsmufs.kernel import gdtsee
        read = {}
        for sign, letter in (("Ⓜ", "M"), ("Ⓛ", "L"), ("Ⓢ", "S")):
            img, boxes = self.frame("⌖", tol=f".005 {sign}")
            read[letter] = gdtsee.circled(img, boxes[f".005 {sign}"])
            self.assertIn(read[letter], (letter, None), sign)  # never the wrong one
        self.assertGreaterEqual(sum(v is not None for v in read.values()), 2)
        img, boxes = self.frame("⌖", tol=".0052")
        self.assertIsNone(gdtsee.circled(img, boxes[".0052"]))  # a plain digit is no circled letter


class Units(unittest.TestCase):
    def test_what_the_print_says(self):
        for text, unit in (("UNLESS OTHERWISE SPECIFIED DIMENSIONS ARE IN INCHES", "in"), ("UNITS: MM", "mm"), ("DIMENSIONS IN INCH [MM]", "in"),
                           ("ALL DIMENSIONS IN MILLIMETERS", "mm"), ("1/4-20 UNC 2B", "in"), ("ISO 2768-mK", "mm"),
                           ("INTERPRET PER ASME Y14.5", None), ("PART NAME BRACKET", None)):
            self.assertEqual(printmarks.units([text]), unit, text)

    def test_tips_follow_the_prints_units(self):
        g = gdt.read("⌖ Ø0.25 A B")  # written the metric way
        self.assertIn("Ø0.250 mm (0.0098 in)", gdt.tip(g))  # nothing says: by how it's written, and said so
        self.assertIn("Units weren't found", gdt.tip(g))
        inch = gdt.tip(g, metric=False)  # the print's notes say inches
        self.assertIn("Ø0.2500 in (6.350 mm)", inch)
        self.assertNotIn("Units weren't found", inch)
        self.assertNotEqual(gdt.card(g)["machining"], gdt.card(g, metric=False)["machining"])  # and scored as such
        line = [("⌖", 10, 10, 20, 20), ("Ø0.25", 24, 10, 60, 20), ("A", 80, 10, 88, 20)]
        marks, _ = printmarks.lines_marks([line], False)
        frame = [m for m in printmarks.with_units(marks, "in") if m["kind"] == "gdt"][0]
        self.assertIn("0.2500 in", frame["tip"])
        self.assertNotIn("g", frame)


class TappedHoles(unittest.TestCase):
    """Position on a tapped hole is very hard, to machine and to measure: the frame under a thread callout says so."""

    def test_thread_callouts(self):
        for text, yes in (("4X 1/4-20 UNC-2B", True), ("#10-32 UNF", True), ("M6x1.0 - 6H", True), (".250-20 UNC", True), ("TAP DRILL", True),
                          ("2X Ø.250 THRU", False), ("0.002 S A S", False), ("6061-T6", False), ("REV 1-2", False)):
            self.assertEqual(bool(gdt.THREAD.search(text)), yes, text)

    def test_a_frame_under_a_thread_callout(self):
        frame = [("⌖", 10, 14, 20, 24), ("Ø.014", 24, 14, 60, 24), ("Ⓜ", 62, 14, 72, 24), ("A", 80, 14, 88, 24), ("B", 96, 14, 104, 24)]
        thread = [("4X", 10, 0, 20, 9), ("1/4-20", 24, 0, 60, 9), ("UNC-2B", 64, 0, 100, 9)]
        plain = [("4X", 10, 0, 20, 9), ("Ø.257", 24, 0, 60, 9), ("THRU", 64, 0, 100, 9)]
        far = [(w[0], w[1] + 600, w[2] + 300, w[3] + 600, w[4] + 300) for w in thread]

        def card(*lines):
            marks, _ = printmarks.lines_marks(list(lines), False)
            return [m for m in printmarks.with_units(marks, "in") if m["kind"] == "gdt"][0]["card"]
        on_thread, on_hole, elsewhere = card(thread, frame), card(plain, frame), card(far, frame)
        self.assertIn("Tapped hole: very hard", on_thread["notes"][0])
        self.assertGreaterEqual(min(on_thread["machining"], on_thread["measuring"]), 8)
        self.assertLess(on_hole["machining"], 5)  # the same frame on a plain hole
        self.assertEqual((elsewhere["machining"], elsewhere["notes"]), (on_hole["machining"], on_hole["notes"]))  # a thread far away isn't its


class FromACadPdfsText(unittest.TestCase):
    """A CAD system's PDF holds a frame's numbers and letters as text and draws its symbol, Ø and circles as lines."""

    def test_reading_the_letters(self):
        g = gdt.read_layer("0.005 P .270 M A B M")  # position | Ø0.005 Ⓟ .270 Ⓜ | A | B Ⓜ
        self.assertEqual((g["tol"], g["mods"], g["extra"], g["datums"], g["dmods"], g["guess"]),
                         ("0.005", ["P", "M"], {"P": ".270"}, ["A", "B"], [None, "M"], True))
        g = gdt.read_layer("0.0005 M A B M")
        self.assertEqual((g["mods"], g["mmc"], g["datums"], g["dmods"]), (["M"], "M", ["A", "B"], [None, "M"]))
        self.assertEqual(gdt.read_layer("0.002 S A S")["dmods"], ["S"])
        for words in ("0.005 B MAJOR DIAMETER", "4X Ø.250", ".002 MAX", "WEIGHT: 0.004 LBS."):
            self.assertIsNone(gdt.read_layer(words), words)
        self.assertEqual(gdt.read("// 0.005 A")["kind"], "parallelism")  # the one symbol such PDFs do spell out

    def test_nothing_shows_until_the_picture_confirms_a_frame(self):
        line = [("0.0005", 24, 10, 60, 20), ("M", 62, 10, 72, 20), ("A", 80, 10, 88, 20), ("B", 96, 10, 104, 20), ("M", 106, 10, 116, 20)]
        marks, _ = printmarks.lines_marks([line], False)
        self.assertEqual([m["kind"] for m in marks if m["kind"].startswith("gdt")], [gdt.PENDING])
        self.assertEqual([m for m in printmarks.with_units(marks, "in") if m["kind"].startswith("gdt")], [])

    @unittest.skipUnless(__import__("os").path.exists("C:/Windows/Fonts/seguisym.ttf"), "needs Segoe UI Symbol to draw the symbols")
    def test_the_picture_names_it_and_sees_the_diameter(self):
        from solidsmufs.kernel import gdtsee
        img, boxes = FromThePicture.frame("⌖", tol="Ø 0.0005", after="A")
        k = 72 / 300
        x0, y0, x1, y1 = boxes["Ø 0.0005"]
        number = ("0.0005", (x0 + (x1 - x0) * 0.32) * k, y0 * k, x1 * k, y1 * k)  # the text has the number, not the Ø before it
        line = [number, ("M", number[3] + 4, number[2], number[3] + 12, number[4]), ("A", number[3] + 30, number[2], number[3] + 38, number[4])]
        marks, _ = printmarks.lines_marks([line], False)
        out = [m for m in gdtsee.confirm(marks, img, k) if m["kind"] == "gdt"]
        self.assertEqual(len(out), 1)
        g = out[0]["g"]
        self.assertEqual((g["kind"], g["dia"], g["mods"], g["datums"]), ("position", True, ["M"], ["A"]))
        card = printmarks.with_units(out, "in")[0]["card"]
        self.assertEqual(card["head"], "⌖ Position | Ø0.0005 Ⓜ | A")
        self.assertEqual((card["machining"], card["measuring"]), (7, 6))
        nowhere = [(w[0], w[1] + 300, w[2] + 200, w[3] + 300, w[4] + 200) for w in line]  # the same words with no frame drawn
        marks, _ = printmarks.lines_marks([nowhere], False)
        self.assertEqual([m for m in gdtsee.confirm(marks, img, k) if m["kind"].startswith("gdt")], [])

    def test_ocrs_reading_of_the_symbol_names_an_unnamed_frame(self):
        g = gdt.read_layer("0.005 B")
        have = {"x": 100, "y": 50, "w": 60, "h": 12, "kind": "gdt", "text": "0.005 B", "tip": "", "ocr": False, "g": g}
        ocr = gdt.mark([("//", 86, 50, 96, 62), ("0.005", 104, 50, 130, 62), ("B", 140, 50, 148, 62)], "// 0.005 B", "", True, gdt.read("// 0.005 B", True))
        out = printmarks.merge([have], [ocr], [])
        self.assertEqual([(m["ocr"], m["g"]["kind"], m["g"]["guess"]) for m in out], [(False, "parallelism", False)])


class WholePart(unittest.TestCase):
    """The part's overall difficulty: its callouts' points, totalled (a first guess, as the scores are)."""

    def test_no_callouts_no_score(self):
        self.assertIsNone(gdt.part([]))

    def test_routine_callouts_dont_make_a_hard_part(self):
        easy = [gdt.read("⌖ Ø.020 Ⓜ A B")] * 30
        p = gdt.part(easy, metric=False)
        self.assertEqual((p["count"], p["points"]), (30, 0))
        self.assertLessEqual(p["score"], 2)

    def test_more_and_harder_callouts_raise_it(self):
        one = gdt.part([gdt.read("⌖ Ø.002 A B")], metric=False)
        four = gdt.part([gdt.read("⌖ Ø.002 A B")] * 4, metric=False)
        tight = gdt.part([gdt.read("⌖ Ø.0005 A B")] * 4, metric=False)
        self.assertLess(one["score"], four["score"])
        self.assertLess(four["score"], tight["score"])
        self.assertLessEqual(tight["score"], 10)
        self.assertEqual(four["items"][0]["points"], one["points"])

    def test_one_very_hard_callout_is_a_hard_part(self):
        p = gdt.part([gdt.read("⌖ Ø.0002 A B")], metric=False)
        self.assertGreaterEqual(p["score"], 8)

    def test_tapped_holes_count_extra(self):
        plain, tapped = gdt.read("⌖ Ø.005 A B"), {**gdt.read("⌖ Ø.005 A B"), "by_thread": True}
        a, b = gdt.part([plain], metric=False), gdt.part([tapped], metric=False)
        self.assertEqual((b["items"][0]["mult"], b["items"][0]["machining"]), (1.5, 8))
        self.assertGreater(b["points"], 3 * a["points"])
        self.assertIn("(tapped)", b["items"][0]["head"])

    def test_from_a_pages_marks(self):
        line = [("⌖", 10, 10, 20, 20), ("Ø.001", 24, 10, 60, 20), ("A", 80, 10, 88, 20)]
        marks, _ = printmarks.lines_marks([line], False)
        p = printmarks.part_difficulty(marks, "in")
        self.assertEqual((p["count"], p["items"][0]["machining"]), (1, 7))


class WithThePdfsOwnText(unittest.TestCase):
    def test_a_frame_from_the_picture_stays_over_the_pdfs_text(self):
        """A CAD system's PDF has a frame's numbers as text and draws its symbol as lines: the text gives a size to
        show in inches, the picture gives the frame, and both stay."""
        size = {"x": 100, "y": 50, "w": 30, "h": 10, "kind": "dim", "text": "0.002", "tip": "", "ocr": False}
        words = [(100, 50, 130, 60), (140, 50, 150, 60)]
        frame = {"x": 80, "y": 48, "w": 75, "h": 14, "kind": "gdt", "text": "Ø0.002@ A@", "tip": "", "ocr": True}
        dim = {"x": 100, "y": 50, "w": 30, "h": 10, "kind": "dim", "text": "0.002", "tip": "", "ocr": True}
        out = printmarks.merge([size], [frame, dict(frame), dim], words)
        self.assertEqual([(m["kind"], m["ocr"]) for m in out], [("dim", False), ("gdt", True)])  # one frame; OCR's size isn't wanted


if __name__ == "__main__":
    unittest.main()
