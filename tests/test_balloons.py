"""Ballooning a print: reading its characteristics (kernel/balloons.py), keeping them and their balloons in the PDF
(kernel/balloonops.py), and the inspection report (kernel/xlsx.py)."""

import os
import tempfile
import unittest
import xml.dom.minidom
import zipfile

from solidsmufs.kernel import balloons


def one(text, unit="in"):
    items = balloons.parse(text, unit)
    assert len(items) == 1, (text, items)
    return items[0]


def line(text, x, y, w=None, h=9.0, vert=False):
    w = w or 5.0 * len(text)
    return {"text": text, "box": [x, y, x + (h if vert else w), y + (w if vert else h)], "vert": vert}


class Parse(unittest.TestCase):
    def test_tolerances_beside_the_size(self):
        it = one("1.250 ±.005")
        self.assertEqual((it["kind"], it["nominal"], it["plus"], it["minus"], it["places"], it["tol"]), ("dim", 1.25, 0.005, 0.005, 3, "print"))
        it = one("Ø.250 +.005/-.000")
        self.assertEqual((it["nominal"], it["plus"], it["minus"], it["text"]), (0.25, 0.005, 0.0, "Ø.250 +.005/-.000"))
        it = one(".2500-.2505")
        self.assertEqual((it["lo"], it["hi"], it["nominal"]), (0.25, 0.2505, None))
        self.assertEqual(one("R.125 MAX")["hi"], 0.125)
        self.assertEqual(one(".010 MIN")["lo"], 0.01)

    def test_counts(self):
        it = one("4X Ø.201 THRU")
        self.assertEqual((it["count"], it["text"], it["nominal"]), (4, "4X Ø.201", 0.201))
        self.assertEqual(one("Ø.136 THRU 3 PLACES")["count"], 3)

    def test_threads_finishes_angles_chamfers(self):
        self.assertEqual([(i["kind"], i["text"]) for i in balloons.parse("2X .500-13 UNC-2B", "in")], [("thread", "2X .500-13 UNC-2B")])
        self.assertEqual(one("1/4-20 UNC-2B THRU")["kind"], "thread")
        self.assertEqual(one("#10-32 UNF-2B")["kind"], "thread")
        self.assertEqual(one("M6X1.0-6H", "mm")["kind"], "thread")
        self.assertEqual(one("125 RMS")["kind"], "finish")
        it = one("45° ±1°")
        self.assertEqual((it["kind"], it["nominal"], it["plus"]), ("angle", 45.0, 1.0))
        self.assertEqual(one(".030 X 45°")["kind"], "chamfer")

    def test_a_hole_callout_is_one_characteristic_per_size(self):
        self.assertEqual([i["text"] for i in balloons.parse("⌴Ø.375 ↧.250", "in")], ["⌴Ø.375", "↧.250"])

    def test_what_isnt_inspected_or_isnt_a_size(self):
        for text in ["(1.500)", "2.000 REF", "1.000 BSC", "SCALE 1:2", "12/05/2023", "6061-T6 PER AMS 4027",
                     "BREAK ALL SHARP EDGES .005-.015", "DWG NO. 12345-001 REV B", "25"]:
            self.assertEqual(balloons.parse(text, "in"), [], text)

    def test_whole_numbers_are_sizes_on_a_metric_print_only(self):
        self.assertEqual(balloons.parse("25", "in"), [])
        self.assertEqual(one("25", "mm")["nominal"], 25.0)
        self.assertEqual(one("Ø25", "in")["nominal"], 25.0)

    def test_title_block_tolerances(self):
        self.assertEqual(balloons.defaults(["UNLESS OTHERWISE SPECIFIED", ".XX ± .01", ".XXX ±.005", "X.XXXX = ±.0005", "ANGLES ± 0.5°"]),
                         {"2": 0.01, "3": 0.005, "4": 0.0005, "angle": 0.5})
        self.assertEqual(balloons.defaults(["TWO PLACE DECIMAL ±.010", "THREE PLACE DECIMAL +/-.005"]), {"2": 0.01, "3": 0.005})
        self.assertEqual(balloons.defaults(["NO TOLERANCES HERE"]), {})


class Read(unittest.TestCase):
    def test_title_block_tolerance_by_decimals(self):
        items = balloons.read([line("3.750", 100, 100), line("1.25", 300, 100), line("30°", 500, 100)], tols={"2": 0.01, "3": 0.005, "angle": 1.0})
        self.assertEqual([(i["lo"], i["hi"], i["tol"]) for i in items], [(3.745, 3.755, "default"), (1.24, 1.26, "default"), (29.0, 31.0, "default")])

    def test_stacked_tolerance(self):
        items = balloons.read([line("2.500", 100, 100, 26), line("+.005", 130, 96, 16, 6), line("-.000", 130, 104, 16, 6)], tols={})
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual((it["plus"], it["minus"], it["lo"], it["hi"], it["text"]), (0.005, 0.0, 2.5, 2.505, "2.500 +.005/-.000"))
        self.assertGreater(it["box"][2], 40)  # the callout's box takes in its tolerance

    def test_stacked_tolerance_on_a_size_that_reads_up_the_page(self):
        items = balloons.read([line("2.500", 100, 300, 26, vert=True), line("+.005", 96, 280, 16, 6, vert=True),
                               line("-.002", 104, 280, 16, 6, vert=True)], tols={})
        self.assertEqual([(i["plus"], i["minus"]) for i in items], [(0.005, 0.002)])

    def test_stacked_limits(self):
        items = balloons.read([line(".4995", 100, 100, 22), line(".4990", 100, 110, 22)], tols={"4": 0.0005})
        self.assertEqual([(i["lo"], i["hi"], i["text"], i["tol"]) for i in items], [(0.499, 0.4995, ".4995 / .4990", "print")])

    def test_frames_notes_and_the_title_block(self):
        lines = [line("1. BREAK ALL SHARP EDGES .005-.015 UNLESS NOTED.", 60, 80), line("2. ANODIZE PER MIL-A-8625 TYPE II,", 60, 92),
                 line("COLOR BLACK.", 72, 104), line("5.000 ±.005", 400, 200), line(".002", 300, 300, 14),
                 *[line(t, 900, 640 + 11 * i) for i, t in enumerate(["UNLESS OTHERWISE SPECIFIED", "TOLERANCES: .XXX ±.005", "MATERIAL: 6061-T6",
                                                                    "SCALE 1:1  SHEET 1 OF 1", "DWG NO. 77", "WEIGHT 1.25"])]]
        frames = [{"box": [280, 296, 80, 16], "text": "⌖ Position | Ø.002 | A B"}]
        items = balloons.read(lines, frames, "in", None, (1224.0, 792.0))
        self.assertEqual([(i["kind"], i["text"]) for i in items], [
            ("dim", "5.000 ±.005"), ("gdt", "⌖ Position | Ø.002 | A B"),
            ("note", "1. BREAK ALL SHARP EDGES .005-.015 UNLESS NOTED."), ("note", "2. ANODIZE PER MIL-A-8625 TYPE II, COLOR BLACK.")])
        self.assertEqual(len(balloons.read(lines, frames, "in", None, (1224.0, 792.0), notes=False)), 2)

    def test_balloons_keep_clear_of_text_and_each_other(self):
        lines = [line("1.250", 100, 100, 26), line("2.500", 60, 100, 26), line("3.750", 100, 114, 26)]
        items = balloons.read(lines, tols={})
        r = balloons.radius(items)
        spots = balloons.place(items, [tuple(ln["box"]) for ln in lines], (612.0, 792.0), r)
        boxes = [(x - r, y - r, x + r, y + r) for x, y in spots]
        for i, b in enumerate(boxes):
            for o in [tuple(ln["box"]) for ln in lines] + boxes[:i]:
                self.assertFalse(b[0] < o[2] and o[0] < b[2] and b[1] < o[3] and o[1] < b[3], (b, o))


def _print(path, rotate=0):
    import pymupdf
    doc = pymupdf.open()
    pg = doc.new_page(width=1224, height=792)
    for (x, y), text, size in [((420, 185), "5.000 ±.005", 9), ((710, 330), "2.500", 9), ((742, 326), "+.005", 6), ((742, 334), "-.000", 6),
                               ((250, 280), "2X Ø.375 +.002/-.000 THRU", 9), ((560, 270), "1/4-20 UNC-2B THRU", 9), ((600, 470), "(3.000)", 9),
                               ((300, 500), "3.750", 9), ((60, 94), "1. BREAK ALL SHARP EDGES .005-.015 UNLESS NOTED.", 9),
                               ((870, 640), "UNLESS OTHERWISE SPECIFIED", 8), ((870, 651), "DIMENSIONS ARE IN INCHES", 8), ((870, 662), "TOLERANCES:", 8),
                               ((870, 673), ".XXX ±.005", 8), ((870, 684), "MATERIAL: 6061-T6", 8), ((870, 695), "SCALE 1:1  SHEET 1 OF 1", 8),
                               ((870, 706), "DWG NO. 12345-001 REV B", 8), ((870, 717), "WEIGHT 1.25", 8)]:
        pg.insert_text((x, y), text, fontsize=size, fontname="helv")
    if rotate:
        pg.set_rotation(rotate)
    doc.save(path)
    doc.close()


class InThePdf(unittest.TestCase):
    def setUp(self):
        from solidsmufs.kernel.pdfdoc import PdfFile
        from solidsmufs.kernel.pdfedit import PdfEditor
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "print.pdf")
        _print(self.path)
        self.pdf = PdfFile(self.path)
        self.ed = PdfEditor(self.pdf, self.path)

    def tearDown(self):
        self.pdf.close()
        self.dir.cleanup()

    def auto(self):
        return self.ed.run("balloon_auto", {"extra": {"unit": "in", "pages": {}}})["result"]

    def test_detect_balloons_the_print(self):
        import pymupdf
        res = self.auto()
        self.assertEqual([(c["n"], c["kind"], c["text"]) for c in res["chars"]], [
            (1, "dim", "5.000 ±.005"), (2, "dim", "2X Ø.375 +.002/-.000"), (3, "thread", "1/4-20 UNC-2B"), (4, "dim", "2.500 +.005/-.000"),
            (5, "dim", "3.750"), (6, "note", "1. BREAK ALL SHARP EDGES .005-.015 UNLESS NOTED.")])
        self.assertEqual(res["tols"], {"3": 0.005})
        self.assertEqual([res["chars"][4][k] for k in ("lo", "hi", "tol")], [3.745, 3.755, "default"])
        marks = [a for a in self.pdf.fz[0].annots() if a.info["subject"] == "Balloon"]
        self.assertEqual(len(marks), 6)
        self.assertEqual(self.ed.run("annots", {}), [])  # they aren't comments to the editor
        # a balloon's number is drawn in its circle
        ap = int(self.pdf.fz.xref_get_key(marks[0].xref, "AP/N")[1].split()[0])
        self.assertIn(b"Tj", self.pdf.fz.xref_stream(ap))
        self.assertTrue(self.ed.state()["dirty"])
        self.ed.run("undo", {})
        self.assertEqual(self.ed.run("balloons", {})["chars"], [])
        self.assertEqual(len(list(self.pdf.fz[0].annots(types=[pymupdf.PDF_ANNOT_CIRCLE]))), 0)

    def test_changes(self):
        res = self.auto()
        first = res["chars"][0]
        res = self.ed.run("balloon_move", {"id": first["id"], "at": [500.0, 150.0]})["result"]
        self.assertEqual(res["chars"][0]["at"], [500.0, 150.0])
        res = self.ed.run("balloon_edit", {"id": 5, "plus": 0.002, "minus": 0.001})["result"]
        self.assertEqual([res["chars"][4][k] for k in ("lo", "hi", "tol")], [3.749, 3.752, "print"])
        res = self.ed.run("balloon_edit", {"id": 3, "n": 1})["result"]
        self.assertEqual([(c["id"], c["n"]) for c in res["chars"][:3]], [(3, 1), (1, 2), (2, 3)])
        res = self.ed.run("balloon_delete", {"ids": [1]})["result"]
        self.assertEqual([c["n"] for c in res["chars"]], [1, 3, 4, 5, 6])
        res = self.ed.run("balloon_renumber", {})["result"]
        self.assertEqual([c["n"] for c in res["chars"]], [1, 2, 3, 4, 5])
        res = self.ed.run("balloon_tols", {"tols": {"3": 0.01}})["result"]
        self.assertEqual([c["tol"] for c in res["chars"] if c["id"] == 5], ["print"])  # its own tolerance stays
        self.ed.run("balloon_edit", {"id": 5, "plus": None, "minus": None})
        res = self.ed.run("balloons", {})
        self.assertEqual([(c["lo"], c["hi"], c["tol"]) for c in res["chars"] if c["id"] == 5], [(3.74, 3.76, "default")])

    def test_add_by_hand(self):
        self.auto()
        res = self.ed.run("balloon_add", {"page": 0, "rect": [590, 455, 60, 22]})["result"]  # a reference size, asked for
        new = [c for c in res["chars"] if c["id"] in res["ids"]]
        self.assertEqual([(c["n"], c["kind"], c["nominal"]) for c in new], [(7, "dim", 3.0)])
        res = self.ed.run("balloon_add", {"page": 0, "rect": [800, 300, 0, 0]})["result"]
        new = [c for c in res["chars"] if c["id"] in res["ids"]]
        self.assertEqual([(c["n"], c["kind"], c["text"], c["at"]) for c in new], [(8, "other", "", [800.0, 300.0])])

    def test_saved_with_the_pdf_and_follows_its_pages(self):
        from solidsmufs.kernel.pdfdoc import PdfFile
        from solidsmufs.kernel.pdfedit import PdfEditor
        self.auto()
        self.ed.run("pages_blank", {"at": 0})  # the print is now the second page
        out = os.path.join(self.dir.name, "ballooned.pdf")
        self.ed.run("save", {"path": out})
        pdf = PdfFile(out)
        try:
            res = PdfEditor(pdf, out).run("balloons", {})
            self.assertEqual(len(res["chars"]), 6)
            self.assertEqual({c["page"] for c in res["chars"]}, {1})
            self.assertEqual(res["tols"], {"3": 0.005})
        finally:
            pdf.close()

    def test_report(self):
        self.auto()
        out = os.path.join(self.dir.name, "report.xlsx")
        self.assertEqual(self.ed.run("balloon_report", {"path": out})["count"], 6)
        with zipfile.ZipFile(out) as z:
            for name in z.namelist():
                xml.dom.minidom.parseString(z.read(name))
            sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
            form = z.read("xl/worksheets/sheet2.xml").decode("utf-8")
        self.assertIn("5.000 ±.005", sheet)
        self.assertIn("<v>4.995</v>", sheet)
        self.assertIn("Title block", sheet)
        self.assertIn("8. Requirement", form)
        self.assertIn("3.750  (3.745 to 3.755)", form)

    def test_a_turned_page(self):
        path = os.path.join(self.dir.name, "turned.pdf")
        _print(path, rotate=90)
        from solidsmufs.kernel.pdfdoc import PdfFile
        from solidsmufs.kernel.pdfedit import PdfEditor
        pdf = PdfFile(path)
        try:
            res = PdfEditor(pdf, path).run("balloon_auto", {"extra": {"unit": "in", "pages": {}}})["result"]
            # (its text runs down the page now: the sizes are read all the same, a note isn't)
            self.assertEqual(sorted(c["text"] for c in res["chars"]), ["1/4-20 UNC-2B", "2.500 +.005/-.000", "2X Ø.375 +.002/-.000", "3.750", "5.000 ±.005"])
            w, h = pdf.fz[0].rect.width, pdf.fz[0].rect.height  # as shown: 792 x 1224
            for c in res["chars"]:
                self.assertTrue(0 < c["at"][0] < w and 0 < c["at"][1] < h, c["at"])
                self.assertTrue(abs(c["at"][0] - (c["box"][0] + c["box"][2] / 2)) < 200 and abs(c["at"][1] - (c["box"][1] + c["box"][3] / 2)) < 200)
        finally:
            pdf.close()


if __name__ == "__main__":
    unittest.main()
