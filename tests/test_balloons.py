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
        for text in ["SCALE 1:2", "12/05/2023", "6061-T6 PER AMS 4027", "BREAK ALL SHARP EDGES .005-.015", "DWG NO. 12345-001 REV B", "25",
                     "(REF)", "STOCK", "(2 PLACES)"]:
            self.assertEqual(balloons.parse(text, "in"), [], text)

    def test_reference_and_basic_sizes(self):
        for text, nominal, tol in [("(1.500)", 1.5, "ref"), ("2.000 REF", 2.0, "ref"), ("0.625 (REF)", .625, "ref"), ("Ø.625 STOCK", .625, "ref"),
                                   ("2X (Ø.250)", .25, "ref"), ("1.000 BSC", 1.0, "basic"), ("1.000 BASIC", 1.0, "basic")]:
            it = one(text)
            self.assertEqual((it["text"], it["nominal"], it["tol"], it["plus"], it["lo"]), (text, nominal, tol, None, None), text)
        self.assertEqual(one("2X (Ø.250)")["count"], 2)
        self.assertEqual(balloons.limits(one("(1.500)"), {"3": .005})["lo"], None)  # the title block's tolerance isn't theirs
        # REF, BSC or STOCK under a size, or after it, is said of that size
        lines = [line("Ø.625", 100, 100, 26), line("STOCK", 100, 111, 26), line("2.375 ±.040", 300, 100, 55), line("1.000", 100, 300, 26),
                 line("BSC", 132, 300, 16), line("3.250", 300, 300, 26)]
        got = {i["text"]: i["tol"] for i in balloons.read(lines, tols={"3": .005})}
        self.assertEqual(got, {"Ø.625 STOCK": "ref", "2.375 ±.040": "print", "1.000 BSC": "basic", "3.250": "default"})
        # a size in a box of its own is basic: one that only has lines running past it isn't
        ln = line("1.500", 200, 200, 26)
        x0, y0, x1, y1 = ln["box"]
        box = [(x0 - 3, y0 - 1, x1 + 3, y0 - 1), (x0 - 3, y1 + 1, x1 + 3, y1 + 1), (x0 - 3, y0 - 1, x0 - 3, y1 + 1), (x1 + 3, y0 - 1, x1 + 3, y1 + 1)]
        self.assertEqual(balloons.read([ln], tols={"3": .005}, segs=box)[0]["tol"], "basic")
        past = [(x0 - 40, y1 + 1, x1 + 40, y1 + 1), (x0 - 40, y0 - 1, x1 + 40, y0 - 1), (x0 - 3, y0 - 30, x0 - 3, y1 + 30), (x1 + 3, y0 - 30, x1 + 3, y1 + 30)]
        self.assertEqual(balloons.read([ln], tols={"3": .005}, segs=past)[0]["tol"], "default")

    def test_flag_notes(self):
        notes = [line("1. BREAK ALL SHARP EDGES .005-.015 UNLESS NOTED.", 40, 40, 250), line("2. ANODIZE PER MIL-A-8625 TYPE II.", 40, 52, 180)]
        flag, boxed, bare = line("2", 300, 300, 5), line("25", 400, 300, 10), line("4", 500, 300, 5)
        tri = (295, 292, 311, 312, 3)  # a triangle round the 2
        box = (396, 297, 414, 312, 4)  # a box round the 25: a basic size, not a flag
        far = (480, 280, 560, 330, 3)  # a big triangle (part of the drawing) round the 4
        items = balloons.read(notes + [flag, boxed, bare], tols={}, unit="mm", shapes=[tri, box, far])
        got = [(i["kind"], i["text"], i.get("flag")) for i in items if i.get("flag") or i["kind"] == "dim"]
        self.assertIn(("note", "Flag note 2: ANODIZE PER MIL-A-8625 TYPE II.", 2), got)
        self.assertIn(("dim", "25", None), got)  # (a metric whole number, boxed)
        self.assertEqual(len([g for g in got if g[2]]), 1)
        flagged = next(i for i in items if i.get("flag"))
        self.assertEqual(flagged["box"], [295, 292, 16, 20])
        self.assertNotIn("2", [i["text"] for i in items if i["kind"] == "dim"])  # its number isn't a size
        self.assertEqual([i.get("flag") for i in balloons.read(notes + [flag], tols={}, shapes=[tri], want={"flags": False})], [None, None])
        # a flag whose note isn't on the page: its number all the same
        self.assertEqual(balloons.read([line("7", 300, 300, 5)], tols={}, shapes=[tri])[0]["text"], "Flag note 7")

    def test_what_to_balloon(self):
        lines = [line("5.000 ±.005", 100, 100, 55), line("(3.000)", 100, 200, 36), line("1.000 BSC", 100, 300, 45), line("2.250", 100, 400, 26),
                 line("63 RMS", 300, 100, 30), line("1/4-20 UNC-2B", 300, 200, 65)]
        texts = lambda **want: sorted(i["text"] for i in balloons.read(lines, tols={"3": .005}, want=want))  # noqa: E731
        every = ["(3.000)", "1.000 BSC", "1/4-20 UNC-2B", "2.250", "5.000 ±.005", "63 RMS"]
        self.assertEqual(texts(), every)
        self.assertEqual(texts(ref=False), [t for t in every if t != "(3.000)"])
        self.assertEqual(texts(basic=False), [t for t in every if t != "1.000 BSC"])
        self.assertEqual(texts(general=False), [t for t in every if t != "2.250"])
        self.assertEqual(texts(finish=False), [t for t in every if t != "63 RMS"])

    def test_one_callouts_characteristics_go_together(self):
        lines = [line("Ø.470 ±.010 THRU", 100, 100, 80), line("↧.250 ±.010", 100, 110, 55), line("2.375 ±.040", 400, 100, 55), line("⌴Ø.375 ↧.250", 400, 300, 60)]
        items = balloons.read(lines, tols={})
        group = {i["text"]: i["group"] for i in items}
        self.assertEqual(group["Ø.470 ±.010"], group["↧.250 ±.010"])  # stacked: one callout
        self.assertEqual(group["⌴Ø.375"], group["↧.250"])  # on one line
        self.assertEqual(len(set(group.values())), 3)

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

    def auto(self, **more):
        # (the print's one reference size is left out, but for the tests that are about it)
        return self.ed.run("balloon_auto", {"extra": {"unit": "in", "pages": {}}, "want": {"ref": False}, **more})["result"]

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
        self.assertEqual(self.ed.run("balloon_report", {"path": out, "layout": "list"})["count"], 6)
        with zipfile.ZipFile(out) as z:
            for name in z.namelist():
                xml.dom.minidom.parseString(z.read(name))
            sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
            form = z.read("xl/worksheets/sheet4.xml").decode("utf-8")
        self.assertIn("5.000 ±.005", sheet)
        self.assertIn("<v>4.995</v>", sheet)
        self.assertIn("Title block", sheet)
        self.assertIn("8. Requirement", form)
        self.assertIn("3.750  (3.745 to 3.755)", form)

    def test_report_results_and_details(self):
        from solidsmufs.kernel import report, xlsx
        self.auto()
        res = self.ed.run("balloon_info", {"info": {"part": "WM-1001", "rev": "B", "parts": 3, "nonsense": "x"}})["result"]
        self.assertEqual(res["info"], {"part": "WM-1001", "rev": "B", "parts": 3})
        self.assertIn(["part", "Part number"], res["fields"])
        out = os.path.join(self.dir.name, "report.xlsx")
        self.assertEqual(self.ed.run("balloon_report", {"path": out, "layout": "list"})["parts"], 3)  # (as the details say)
        with zipfile.ZipFile(out) as z:
            for name in z.namelist():
                xml.dom.minidom.parseString(z.read(name))
            sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
            form = z.read("xl/worksheets/sheet5.xml").decode("utf-8")
            book = z.read("xl/workbook.xml").decode("utf-8")
        for want in ("WM-1001", "Part 1", "Part 3", "Pass / Fail", "conditionalFormatting", 'orientation="landscape"'):
            self.assertIn(want, sheet)
        self.assertNotIn("Part 4", sheet)
        self.assertIn("WM-1001", form)
        self.assertIn("_xlnm.Print_Titles", book)
        # the details stay through a new Detect, and undo takes them back
        self.assertEqual(self.auto()["info"]["part"], "WM-1001")
        # a row's Pass / Fail: from the cells its limits are in, over every part's result
        data = {"chars": [{"n": 1, "page": 0, "kind": "dim", "text": "5.000 ±.005", "count": 1, "nominal": 5.0, "plus": .005, "minus": .005,
                           "lo": 4.995, "hi": 5.005, "places": 3, "tol": "print"},
                          {"n": 2, "page": 0, "kind": "note", "text": "DEBURR", "count": 1, "places": 0}], "unit": "in", "tols": {}}
        sheet, where = report.inspection(data, "p.pdf", 2)
        r = where["first"]
        row = sheet["rows"][r - 1]
        head = [c[0] for c in sheet["rows"][r - 2]]
        self.assertEqual(head[11:14], ["Part 1", "Part 2", "Pass / Fail"])
        # (Pass only once both parts are in; until then how many are)
        done = lambda q: f'IF(COUNTA(L{q}:M{q})<2,COUNTA(L{q}:M{q})&" of 2","Pass")'  # noqa: E731
        self.assertEqual(row[13][0]["f"], f'IF(COUNTA(L{r}:M{r})=0,"",IF(COUNTIF(L{r}:M{r},"Fail")+COUNTIF(L{r}:M{r},"<"&I{r})+COUNTIF(L{r}:M{r},">"&J{r})>0,"Fail",{done(r)}))')
        self.assertEqual(sheet["rows"][r][13][0]["f"], f'IF(COUNTA(L{r + 1}:M{r + 1})=0,"",IF(COUNTIF(L{r + 1}:M{r + 1},"Fail")>0,"Fail",{done(r + 1)}))')
        # another layout: fewer columns, the limits written into the formula
        short = {"name": "Short", "columns": ["n", "text", "results", "status"]}
        sheet, where = report.inspection(data, "p.pdf", 1, short)
        self.assertEqual([c[0] for c in sheet["rows"][where["first"] - 2]], ["Balloon", "Requirement", "Result", "Pass / Fail"])
        self.assertIn('"<"&4.995', sheet["rows"][where["first"] - 1][3][0]["f"])
        xlsx.write(out, report.build(data, "p.pdf", 1, short))

    def test_balloons_keep_off_the_linework(self):
        ln = line("1.250", 200, 300, 26)
        items = balloons.read([ln], tols={})
        r = balloons.radius(items)
        (x, y), = balloons.place(items, [tuple(ln["box"])], (612.0, 792.0), r)
        self.assertLess(x, 200)  # with nothing in the way: at its left, close by
        self.assertLess(200 - x - r, 0.5 * r + 2)
        # an extension line down its left side and a dimension line under it: somewhere clear of both
        segs = [(200 - r - 3, 250, 200 - r - 3, 350), (150, ln["box"][3] + 3, 300, ln["box"][3] + 3)]
        (x, y), = balloons.place(items, [tuple(ln["box"])], (612.0, 792.0), r, segs)
        for s in segs:
            self.assertGreaterEqual(balloons._seg_dist(x, y, *s), r)
        self.assertGreaterEqual(balloons._box_dist(x, y, tuple(ln["box"])), r)
        # and not on a picture when there's room beside it
        (x, y), = balloons.place(items, [tuple(ln["box"])], (612.0, 792.0), r, (), [(100, 280, 199, 330)])
        self.assertFalse(100 < x < 199 and 280 < y < 330)

    def test_detect_again_does_not_read_the_balloons(self):
        first = self.auto()
        pg = self.ed.fz[0]
        before = (len(self.ed._balloon_lines(pg)), len(self.ed._balloon_marks(pg)[0]))
        self.ed.run("balloon_clear", {})
        self.assertEqual((len(self.ed._balloon_lines(self.ed.fz[0])), len(self.ed._balloon_marks(self.ed.fz[0])[0])), before)
        self.auto()
        again = self.auto()
        self.assertEqual([(c["text"], c["at"]) for c in again["chars"]], [(c["text"], c["at"]) for c in first["chars"]])

    def test_the_border_grid_is_left_out(self):
        W, H = 842.0, 595.0
        ln = lambda t, x, y: {"text": t, "box": [x, y, x + 6 * len(t), y + 9], "vert": False}  # noqa: E731
        grid = [ln(str(i + 1), 70 + 100 * i, y) for i in range(8) for y in (8, 578)]
        grid += [ln("ABCDEF"[i], x, 60 + 95 * i) for i in range(6) for x in (10, 826)]
        sizes = [ln("4", 530, 100), ln("23", 320, 160), ln("7", 360, 195), ln("72.42", 520, 250), ln("63.3 ±.1", 520, 232)]
        self.assertEqual(len(balloons.zones(grid + sizes, (W, H))), len(grid))
        got = balloons.read(grid + sizes, unit="mm", size=(W, H))
        self.assertEqual(sorted(it["text"] for it in got), ["23", "4", "63.3 ±.1", "7", "72.42"])
        # two lone numbers near an edge are not a grid
        self.assertEqual(balloons.zones([ln("4", 300, 8), ln("7", 500, 8)] + sizes, (W, H)), set())

    def test_zones_and_types(self):
        W, H = 842.0, 595.0
        ln = lambda t, x, y: {"text": t, "box": [x, y, x + 6 * len(t), y + 9], "vert": False}  # noqa: E731
        lines = [ln(str(i + 1), 70 + 100 * i, y) for i in range(8) for y in (8, 578)]
        lines += [ln("ABCDEF"[i], x, 60 + 95 * i) for i in range(6) for x in (10, 826)]
        g = balloons.grid(lines, (W, H))
        self.assertEqual([t for _, t in g["cols"]], [str(i) for i in range(1, 9)])
        self.assertEqual([t for _, t in g["rows"]], list("ABCDEF"))
        self.assertEqual(balloons.zone_at(g, 480, 160), "B5")
        self.assertEqual(balloons.zone_at(g, 75, 560), "F1")
        self.assertEqual(balloons.zone_at(balloons.grid([], (W, H)), 75, 560), "")
        kinds = [("dim", "Ø.470 ±.010", "Diameter"), ("dim", "2X R.125 MAX", "Radius"), ("dim", "2.375 ±.040", "Linear"), ("angle", "30°", "Angular"),
                 ("chamfer", ".025 X 45°", "Chamfer"), ("thread", "1/4-20 UNC-2B", "Thread"), ("finish", "63 RMS", "Surface Finish"),
                 ("gdt", "⌖ Position | Ø.002 | A B", "Position"), ("note", "1. DEBURR", "Note")]
        for kind, text, want in kinds:
            self.assertEqual(balloons.type_of({"kind": kind, "text": text}), want)

    def test_one_tolerance_for_every_size(self):
        tols = balloons.defaults(["Material: C11000", "Tolerances: +-.5mm unless noted", "Scale 2:1"])
        self.assertEqual(tols, {k: .5 for k in "01234"})
        it = balloons.limits(one("72.42", "mm"), tols)
        self.assertEqual((it["lo"], it["hi"], it["tol"]), (71.92, 72.92, "default"))
        tols = balloons.defaults(["TOLERANCES: ±.010", ".XXX ±.005"])
        self.assertEqual((tols["3"], tols["2"]), (.005, .01))
        self.assertEqual(balloons.defaults(["TOLERANCES:", ".XX ±.01", ".XXX ±.005"]), {"2": .01, "3": .005})

    def test_a_size_told_in_a_sentence(self):
        self.assertTrue(balloons.is_prose('Hole is .470" +/-.010'))
        self.assertTrue(balloons.is_prose('Length is 2.375" +/-.040'))
        self.assertEqual(balloons.parse('Hole is .470" +/-.010', "in"), [])
        self.assertFalse(balloons.is_prose("Ø.470 ±.010 THRU"))
        self.assertFalse(balloons.is_prose(".025 x 45° CHAMFER"))
        it = one('.470" +/-.010')  # an inch mark doesn't part a size from its tolerance
        self.assertEqual((it["nominal"], it["plus"], it["minus"]), (.47, .01, .01))

    def test_the_sheet_as_a_pdf(self):
        import pymupdf
        from solidsmufs.kernel import reportpdf
        res = self.auto()
        c = next(c for c in res["chars"] if c["text"] == "5.000 ±.005")
        self.ed.run("balloon_edit", {"id": c["id"], "desc": "Overall Length", "gage": "Calipers"})
        self.ed.run("balloon_info", {"info": {"part": "WM-1001", "name": "BRACKET", "job": "J-77", "frequency": "1 in 5", "parts": 15}})
        out = os.path.join(self.dir.name, "WM-1001 inspection report.xlsx")
        done = self.ed.run("balloon_report", {"path": out, "footer": "Limits are absolute\nFM-1 Inspection Report"})
        self.assertEqual(done["pdf"], out[:-5] + ".pdf")  # the workbook's name, beside it
        doc = pymupdf.open(done["pdf"])
        try:
            self.assertEqual((doc.page_count, done["pages"]), (1, 1))
            pg = doc[0]
            self.assertEqual((pg.rect.width, pg.rect.height), (792.0, 612.0))
            text = pg.get_text()
            for want in ("Inspection Report", "Part Number:", "WM-1001", "BRACKET", "J-77", "1 in 5", "Overall Length", "Calipers", "5.000", "4.995", "5.005",
                         "1/4-20 UNC-2B", "FINAL Inspection Sheet", "Limits are absolute", "FM-1 Inspection Report"):
                self.assertIn(want, text)
            self.assertEqual((text.count("DIMENSION DESCRIPTION"), text.count("Part # ____"), text.count("Initial")), (3, 15, 3))
            fills = {tuple(round(v, 2) for v in p["fill"]) for p in pg.get_drawings() if p.get("fill")}
            self.assertTrue({(1.0, 0.0, 0.0), (0.55, 0.71, 0.89)} <= fills)  # the numbers' red, the headings' blue
            words = {w[4]: w for w in pg.get_text("words")}
            self.assertLess(words["Limits"][0], 100)  # the footer's first line at the left, its second at the right
            self.assertGreater(words["FM-1"][0], 500)
        finally:
            doc.close()
        # a long list runs on to further pages, each table with its heading
        data = {"chars": [{"n": i, "page": 0, "kind": "dim", "text": f"{i}.000", "count": 1, "nominal": float(i), "lo": i - .005, "hi": i + .005, "places": 3}
                          for i in range(1, 61)], "unit": "in", "tols": {}, "info": {}}
        many = os.path.join(self.dir.name, "many.pdf")
        n = reportpdf.write(many, data, "p.pdf", 10)
        doc = pymupdf.open(many)
        try:
            self.assertEqual(doc.page_count, n)
            self.assertGreater(n, 2)
            text = "".join(p.get_text() for p in doc)
            self.assertEqual(text.count("60.005"), 2)  # every row, once for each table of five parts
            self.assertIn(f"Page {n} of {n}", text)
            for p in doc:
                self.assertTrue(all(w[3] < 600 for w in p.get_text("words")))
        finally:
            doc.close()
        with self.assertRaises(ValueError):  # never over the print itself
            self.ed.run("balloon_report", {"path": os.path.splitext(self.ed.path)[0] + ".xlsx"})

    def test_reviewed_notes_and_where(self):
        res = self.auto()
        a, b = res["chars"][0], res["chars"][1]
        self.assertEqual((a["where"], a["type"], a["reviewed"], a["note"]), ("S1", "Linear", None, None))  # (this print has no zones)
        res = self.ed.run("balloon_edit", {"id": a["id"], "reviewed": True, "note": "check with the fixture"})["result"]
        got = next(c for c in res["chars"] if c["id"] == a["id"])
        self.assertEqual((got["reviewed"], got["note"]), (True, "check with the fixture"))
        res = self.ed.run("balloon_reviewed", {"ids": [c["id"] for c in res["chars"]]})["result"]
        self.assertTrue(all(c["reviewed"] for c in res["chars"]))
        res = self.ed.run("balloon_reviewed", {"ids": [b["id"]], "on": False})["result"]
        self.assertEqual([c["id"] for c in res["chars"] if not c["reviewed"]], [b["id"]])
        self.ed.run("undo", {})
        self.assertTrue(all(c["reviewed"] for c in self.ed.run("balloons", {})["chars"]))
        # under the same number, a sub-balloon is in its callout's zone
        self.ed._insp_write({**self.ed._insp(), "chars": [{**c, "zone": "B5"} for c in self.ed._insp()["chars"]]})
        res = self.ed.run("balloon_sub", {"id": a["id"]})["result"]
        self.assertEqual({c["where"] for c in res["chars"]}, {"S1-B5"})

    def test_flag_notes_in_the_pdf(self):
        import pymupdf
        pg = self.ed.fz[0]
        shape = pg.new_shape()
        shape.draw_polyline([(600, 600), (620, 600), (610, 584), (600, 600)])
        shape.finish(color=(0, 0, 0), width=0.7, closePath=True)
        shape.commit()
        pg.insert_text((607.5, 597), "1", fontsize=8, fontname="helv")
        self.assertIn((600.0, 584.0, 620.0, 600.0, 3), [tuple(round(v, 1) for v in s[:4]) + (s[4],) for s in self.ed._balloon_shapes(pg)])
        res = self.auto()
        flag = [c for c in res["chars"] if c["text"].startswith("Flag note 1")]
        self.assertEqual(len(flag), 1)
        self.assertEqual(flag[0]["text"], "Flag note 1: BREAK ALL SHARP EDGES .005-.015 UNLESS NOTED.")

    def test_carried_over_to_a_new_revision(self):
        import pymupdf
        from solidsmufs.kernel.pdfdoc import PdfFile
        from solidsmufs.kernel.pdfedit import PdfEditor
        # the last revision, ballooned and worked on
        res = self.auto()
        num = {c["text"]: c["label"] for c in res["chars"]}
        five = next(c for c in res["chars"] if c["text"] == "5.000 ±.005")
        self.ed.run("balloon_edit", {"id": five["id"], "desc": "Overall Length", "gage": "Calipers", "reviewed": True})
        self.ed.run("balloon_info", {"info": {"part": "WM-1001", "customer": "ACME"}})
        old = os.path.join(self.dir.name, "rev-a.pdf")
        self.ed.run("save", {"path": old})
        # the next revision: 2.500's tolerance opened up, 3.750 gone, a 4.250 added, 5.000 moved a little
        new = os.path.join(self.dir.name, "rev-b.pdf")
        doc = pymupdf.open()
        pg = doc.new_page(width=1224, height=792)
        for (x, y), text, size in [((428, 188), "5.000 ±.005", 9), ((710, 330), "2.500", 9), ((742, 326), "+.010", 6), ((742, 334), "-.000", 6),
                                   ((250, 280), "2X Ø.375 +.002/-.000 THRU", 9), ((560, 270), "1/4-20 UNC-2B THRU", 9), ((600, 470), "(3.000)", 9),
                                   ((900, 300), "4.250 ±.010", 9), ((60, 94), "1. BREAK ALL SHARP EDGES .005-.015 UNLESS NOTED.", 9),
                                   ((870, 640), "UNLESS OTHERWISE SPECIFIED", 8), ((870, 651), "DIMENSIONS ARE IN INCHES", 8), ((870, 662), "TOLERANCES:", 8),
                                   ((870, 673), ".XXX ±.005", 8), ((870, 684), "MATERIAL: 6061-T6", 8), ((870, 695), "SCALE 1:1  SHEET 1 OF 1", 8),
                                   ((870, 706), "DWG NO. 12345-001 REV C", 8), ((870, 717), "WEIGHT 1.25", 8)]:
            pg.insert_text((x, y), text, fontsize=size, fontname="helv")
        doc.save(new)
        doc.close()
        pdf = PdfFile(new)
        try:
            ed = PdfEditor(pdf, new)
            res = ed.run("balloon_carry", {"path": old, "extra": {"unit": "in", "pages": {}}, "want": {"ref": False}})["result"]
            got = res["carried"]
            self.assertEqual((got["from"], got["kept"]), ("rev-a.pdf", 4))
            self.assertEqual(got["changed"], [{"n": num["2.500 +.005/-.000"], "was": "2.500 +.005/-.000", "now": "2.500 +.010/-.000"}])
            top = max(int(n.split(".")[0]) for n in num.values())
            self.assertEqual(got["added"], [{"n": str(top + 1), "now": "4.250 ±.010"}])
            self.assertEqual(got["removed"], [{"n": num["3.750"], "was": "3.750"}])
            mine = {c["text"]: c for c in res["chars"]}
            self.assertEqual((mine["5.000 ±.005"]["label"], mine["5.000 ±.005"]["desc"], mine["5.000 ±.005"]["gage"], mine["5.000 ±.005"]["reviewed"]),
                             (num["5.000 ±.005"], "Overall Length", "Calipers", True))
            self.assertEqual((mine["2.500 +.010/-.000"]["reviewed"], mine["2.500 +.010/-.000"]["note"]), (None, "Was 2.500 +.005/-.000 on the last revision"))
            self.assertEqual((mine["4.250 ±.010"]["note"], mine["4.250 ±.010"]["lo"]), ("New on this revision", 4.24))
            self.assertEqual(res["info"]["part"], "WM-1001")
            labels = [c["label"] for c in res["chars"]]
            self.assertEqual(len(labels), len(set(labels)))
            self.assertNotIn(num["3.750"], labels)  # (a gap where the one that's gone was)
            ed.run("undo", {})  # one step
            self.assertEqual(ed.run("balloons", {})["chars"], [])
            with self.assertRaises(ValueError):
                ed.run("balloon_carry", {"path": new, "extra": {"unit": "in", "pages": {}}})  # (itself)
            with self.assertRaises(ValueError):
                ed.run("balloon_carry", {"path": self.ed.path if False else os.path.join(self.dir.name, "nothing.pdf"), "extra": {}})
        finally:
            pdf.close()

    def test_auto_balloon_choices(self):
        res = self.auto(want={})
        ref = next(c for c in res["chars"] if c["text"] == "(3.000)")
        self.assertEqual((len(res["chars"]), ref["tol"], ref["nominal"], ref["lo"], ref["hi"]), (7, "ref", 3.0, None, None))
        # an ordinary size again, with the title block's tolerance; then basic, which keeps its type through a new nominal
        res = self.ed.run("balloon_edit", {"id": ref["id"], "tol": "auto"})["result"]
        got = next(c for c in res["chars"] if c["id"] == ref["id"])
        self.assertEqual((got["tol"], got["lo"], got["hi"]), ("default", 2.995, 3.005))
        self.ed.run("balloon_edit", {"id": ref["id"], "tol": "basic"})
        res = self.ed.run("balloon_edit", {"id": ref["id"], "nominal": 3.1, "places": 3})["result"]
        got = next(c for c in res["chars"] if c["id"] == ref["id"])
        self.assertEqual((got["tol"], got["nominal"], got["lo"], got["hi"]), ("basic", 3.1, None, None))
        # without the sizes the title block tolerances, the finishes or the notes
        res = self.auto(want={"general": False, "ref": False}, notes=False)
        self.assertEqual(sorted(c["text"] for c in res["chars"]), ["1/4-20 UNC-2B", "2.500 +.005/-.000", "2X Ø.375 +.002/-.000", "5.000 ±.005"])
        # one callout's characteristics under one number
        res = self.auto(split=True)
        self.assertEqual(len({c["n"] for c in res["chars"]}), len({(c["n"], c["sub"]) for c in res["chars"] if not c["sub"]}) + len({c["n"] for c in res["chars"] if c["sub"]}))
        self.assertTrue(all((c["sub"] is None) == (sum(x["n"] == c["n"] for x in res["chars"]) == 1) for c in res["chars"]))

    def test_auto_balloon_a_page_at_a_time(self):
        self.ed.run("pages_insert_file", {"at": 1, "paths": [self.ed.path]})  # a second sheet, the same as the first
        first = self.auto(pages=[0])
        self.assertEqual(({c["page"] for c in first["chars"]}, len(first["chars"])), ({0}, 6))
        self.ed.run("balloon_move", {"id": first["chars"][0]["id"], "at": [700.0, 700.0]})
        keep = {c["id"]: (c["text"], c["at"]) for c in self.ed.run("balloons", {})["chars"]}
        # the second sheet read on its own: the first one's balloons stay as they are, and the numbers run on
        res = self.auto(pages=[1])
        self.assertEqual({c["id"]: (c["text"], c["at"]) for c in res["chars"] if c["page"] == 0}, keep)
        self.assertEqual([(c["page"], c["n"]) for c in res["chars"]], [(0, n) for n in range(1, 7)] + [(1, n) for n in range(7, 13)])
        # the first sheet read again: its balloons are new ones, still numbered ahead of the second's
        res = self.auto(pages=[0])
        self.assertNotIn([700.0, 700.0], [c["at"] for c in res["chars"]])
        self.assertEqual([(c["page"], c["n"]) for c in res["chars"]], [(0, n) for n in range(1, 7)] + [(1, n) for n in range(7, 13)])
        self.assertEqual(len([a for pg in self.ed.fz for a in pg.annots() if a.info.get("subject") == "Balloon"]), 12)
        # nothing to read on a page that isn't there
        self.assertEqual(self.auto(pages=[5])["found"], 0)

    def test_the_list_stays_through_the_pages_being_rearranged(self):
        self.ed.run("pages_blank", {"at": 1})
        self.auto()
        self.ed.run("pages_order", {"order": [1, 0]})
        res = self.ed.run("balloons", {})
        self.assertEqual((len(res["chars"]), {c["page"] for c in res["chars"]}, res["tols"]), (6, {1}, {"3": 0.005}))
        self.ed.run("balloon_renumber", {})  # (and its balloons can still be drawn: their font is still there)
        self.assertEqual(len([a for a in self.ed.fz[1].annots() if a.info.get("subject") == "Balloon"]), 6)

    def test_multiply_reset_and_detach(self):
        import pymupdf
        from solidsmufs.kernel import report
        res = self.auto()
        two = next(c for c in res["chars"] if c["text"] == "2X Ø.375 +.002/-.000")
        self.assertEqual((two["count"], two["mult"]), (2, None))
        res = self.ed.run("balloon_multiply", {})["result"]  # every one that applies in more than one place
        self.assertEqual((res["did"], res["rows"]), (1, 2))
        self.assertEqual([c["mult"] for c in res["chars"]], [c["id"] == two["id"] or None for c in res["chars"]])
        self.assertEqual(self.ed.run("balloon_multiply", {})["result"]["did"], 0)
        self.assertEqual(len([a for a in self.ed.fz[0].annots() if a.info.get("subject") == "Balloon"]), 6)  # still its one balloon
        # the report has a row for each place, the requirement said of one
        page = report.sheet(self.ed._insp(), "p.pdf", 5)
        r = next(i for i, row in enumerate(page["rows"]) if row[0] and row[0][0] == "DIMENSION DESCRIPTION")
        got = [(row[0][0], row[1][0], row[3][0]) for row in page["rows"][r + 1:r + 8]]
        self.assertEqual(got[1:3], [("2.1", "Diameter", .375), ("2.2", "Diameter", .375)])
        self.assertEqual(len(got), 7)
        form = report.form3(self.ed._insp(), "p.pdf")
        self.assertEqual([row[0][0] for row in form["rows"][6:9]], [1, "2.1", "2.2"])
        self.assertIn("Ø.375 +.002/-.000  (0.375 to 0.377)", [row[3][0] for row in form["rows"][6:] if len(row) > 3])
        out = os.path.join(self.dir.name, "mult.xlsx")
        self.ed.run("balloon_report", {"path": out})
        doc = pymupdf.open(out[:-5] + ".pdf")
        try:
            self.assertIn("2.2", doc[0].get_text().split())
        finally:
            doc.close()
        # one place only: nothing to multiply any more
        res = self.ed.run("balloon_edit", {"id": two["id"], "count": 1})["result"]
        self.assertEqual(next(c for c in res["chars"] if c["id"] == two["id"])["mult"], None)
        self.ed.run("undo", {})
        # back to its one row
        res = self.ed.run("balloon_multiply", {"ids": [two["id"]], "on": False})["result"]
        self.assertEqual((res["did"], [c["mult"] for c in res["chars"]]), (1, [None] * 6))
        # detached: each place an entry of its own, with its balloon, clear of the callout's text and of each other
        self.ed.run("balloon_edit", {"id": two["id"], "count": 4, "desc": "Mounting Hole", "gage": "Gage Pin"})
        self.ed.run("balloon_multiply", {"ids": [two["id"]]})
        res = self.ed.run("balloon_detach", {})["result"]
        self.assertEqual(res["made"], 3)
        mine = [c for c in res["chars"] if c["n"] == two["n"]]
        self.assertEqual([(c["label"], c["text"], c["count"], c["mult"], c["desc"], c["lo"], c["hi"]) for c in mine],
                         [(f"2.{k}", "Ø.375 +.002/-.000", 1, None, "Mounting Hole", .375, .377) for k in range(1, 5)])
        self.assertEqual([c["label"] for c in res["chars"]], ["1", "2.1", "2.2", "2.3", "2.4", "3", "4", "5", "6"])
        spots = [(c["at"], c["r"]) for c in mine]
        for i, (a, r) in enumerate(spots):
            for b, _ in spots[i + 1:]:
                self.assertGreaterEqual(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** .5, 2 * r)
        self.assertEqual(len([a for a in self.ed.fz[0].annots() if a.info.get("subject") == "Balloon"]), 9)
        self.assertEqual(self.ed.run("balloon_detach", {})["result"]["made"], 0)
        self.ed.run("undo", {})
        self.assertEqual(len(self.ed.run("balloons", {})["chars"]), 6)

    def test_results_as_kept_and_judged(self):
        for typed, kept in [("2.3751", "2.3751"), (" 2,375 ", "2.375"), ("+.005", ".005"), ("p", "Pass"), ("OK", "Pass"), ("accept", "Pass"), ("f", "Fail"),
                            ("NG", "Fail"), ("reject", "Fail"), ("n/a", "n/a"), ("", ""), (None, "")]:
            self.assertEqual(balloons.result(typed), kept, typed)
        c = {"lo": 4.995, "hi": 5.005}
        self.assertEqual([balloons.judge(c, v) for v in ("5.000", "4.995", "5.005", "5.0051", "4.99", "Pass", "Fail", "n/a", "", None)],
                         [True, True, True, False, False, True, False, None, None, None])
        self.assertEqual([balloons.judge({"lo": None, "hi": .125}, v) for v in (".100", ".126")], [True, False])
        self.assertEqual(balloons.judge({"lo": None, "hi": None}, "1.5"), None)  # nothing to hold it against
        self.assertEqual(balloons.row_keys({"id": 7, "count": 3}), ["7"])
        self.assertEqual(balloons.row_keys({"id": 7, "count": 3, "mult": True}), ["7.1", "7.2", "7.3"])

    def test_parts_and_their_results(self):
        res = self.auto()
        five = next(c for c in res["chars"] if c["text"] == "5.000 ±.005")
        two = next(c for c in res["chars"] if c["text"] == "2X Ø.375 +.002/-.000")
        self.assertEqual((res["samples"], res["results"]), ([], {}))
        a = self.ed.run("balloon_part_add", {})["result"]["part"]
        res = self.ed.run("balloon_part_add", {"name": "S/N 0042"})["result"]
        b = res["part"]
        self.assertEqual(res["samples"], [{"id": a, "name": "1"}, {"id": b, "name": "S/N 0042"}])
        self.ed.run("balloon_result", {"key": str(five["id"]), "part": a, "value": "5.002"})
        self.ed.run("balloon_result", {"key": str(five["id"]), "part": b, "value": "5,009"})
        res = self.ed.run("balloon_result", {"key": str(two["id"]), "part": a, "value": "ok"})["result"]
        self.assertEqual(res["results"], {str(five["id"]): {str(a): "5.002", str(b): "5.009"}, str(two["id"]): {str(a): "Pass"}})
        with self.assertRaises(ValueError):
            self.ed.run("balloon_result", {"key": "999", "part": a, "value": "1"})
        with self.assertRaises(ValueError):
            self.ed.run("balloon_result", {"key": f"{two['id']}.2", "part": a, "value": "1"})  # (it isn't multiplied)
        # multiplied: what it measured is its first place's; each place has its own; detached, they go with their balloons
        self.ed.run("balloon_multiply", {"ids": [two["id"]]})
        res = self.ed.run("balloon_result", {"key": f"{two['id']}.2", "part": a, "value": ".376"})["result"]
        self.assertEqual({k: v for k, v in res["results"].items() if k.startswith(str(two["id"]))}, {f"{two['id']}.1": {str(a): "Pass"}, f"{two['id']}.2": {str(a): ".376"}})
        res = self.ed.run("balloon_detach", {})["result"]
        made = next(c for c in res["chars"] if c["label"] == f"{two['n']}.2")
        self.assertEqual((res["results"][str(two["id"])], res["results"][str(made["id"])]), ({str(a): "Pass"}, {str(a): ".376"}))
        # saved with the PDF
        out = os.path.join(self.dir.name, "measured.pdf")
        self.ed.run("save", {"path": out})
        from solidsmufs.kernel.pdfdoc import PdfFile
        from solidsmufs.kernel.pdfedit import PdfEditor
        pdf = PdfFile(out)
        try:
            again = PdfEditor(pdf, out).run("balloons", {})
            self.assertEqual((again["samples"], again["results"]), (res["samples"], res["results"]))
        finally:
            pdf.close()
        # a result taken out; a balloon deleted, or a part, and theirs go too; undo brings them back
        res = self.ed.run("balloon_result", {"key": str(five["id"]), "part": b, "value": ""})["result"]
        self.assertEqual(res["results"][str(five["id"])], {str(a): "5.002"})
        res = self.ed.run("balloon_delete", {"ids": [made["id"]]})["result"]
        self.assertNotIn(str(made["id"]), res["results"])
        res = self.ed.run("balloon_part_delete", {"id": a})["result"]
        self.assertEqual((res["samples"], res["results"]), ([{"id": b, "name": "S/N 0042"}], {}))
        self.ed.run("undo", {})
        res = self.ed.run("balloons", {})
        self.assertEqual(res["results"][str(five["id"])], {str(a): "5.002"})
        self.assertEqual(self.ed.run("balloon_part_edit", {"id": b, "name": "S/N 0043"})["result"]["samples"][1]["name"], "S/N 0043")
        # reading the print again: the parts stay, what they measured against the old balloons doesn't
        res = self.auto()
        self.assertEqual((len(res["samples"]), res["results"]), (2, {}))
        self.ed.run("undo", {})
        res = self.ed.run("balloon_results_clear", {})["result"]
        self.assertEqual((res["samples"], res["results"]), ([], {}))

    def test_results_in_the_reports(self):
        import pymupdf
        from solidsmufs.kernel import report
        res = self.auto()
        five = next(c for c in res["chars"] if c["text"] == "5.000 ±.005")
        thread = next(c for c in res["chars"] if c["kind"] == "thread")
        a = self.ed.run("balloon_part_add", {"name": "S/N 0042"})["result"]["part"]
        b = self.ed.run("balloon_part_add", {})["result"]["part"]
        for key, part, value in [(five["id"], a, "5.002"), (five["id"], b, "5.0090"), (thread["id"], a, "ok")]:
            self.ed.run("balloon_result", {"key": str(key), "part": part, "value": value})
        self.ed.run("balloon_info", {"info": {"part": "WM-1001", "lot": "S/N 0042", "fai": "FAI-7", "dwg": "D-1001", "dwgrev": "C", "po": "PO 5512",
                                              "org": "Acme Machine", "supplier": "V123", "inspector": "B. P.", "parts": 1}})
        data = self.ed._insp()
        # the sheet to fill in: the parts by name, what they measured under them, the rest still blank
        page = report.sheet(data, "p.pdf", 1)
        r = next(i for i, row in enumerate(page["rows"]) if row[0] and row[0][0] == "DIMENSION DESCRIPTION")
        self.assertEqual([c[0] for c in page["rows"][r][6:9]], ["Part # S/N 0042", "Part # 2", "Part # ____"])
        row = next(row for row in page["rows"][r + 1:] if row[0][0] == five["n"])
        self.assertEqual(row[6:9], [(5.002, "c3"), (5.009, "c4"), ("", "center")])
        self.assertEqual(next(row for row in page["rows"][r + 1:] if row[0][0] == thread["n"])[6], ("Pass", "center"))
        self.assertIn("Drawing: D-1001 Rev C", [row[0][0] for row in page["rows"] if row and row[0]])
        # six parts measured: a second table for the sixth, whatever the report was asked to make room for
        for _ in range(4):
            self.ed.run("balloon_part_add", {})
        self.assertEqual(sum(row[0][0] == "DIMENSION DESCRIPTION" for row in report.sheet(self.ed._insp(), "p.pdf", 1)["rows"] if row and row[0]), 2)
        self.ed.run("undo", {}); self.ed.run("undo", {}); self.ed.run("undo", {}); self.ed.run("undo", {})  # noqa: E702
        # the first article workbook: results under their parts, Pass / Fail worked out, Forms 1, 2 and 3
        out = os.path.join(self.dir.name, "fai.xlsx")
        done = self.ed.run("balloon_report", {"path": out, "layout": "list"})
        with zipfile.ZipFile(out) as z:
            for name in z.namelist():
                xml.dom.minidom.parseString(z.read(name))
            book = z.read("xl/workbook.xml").decode("utf-8")
            sheets = [z.read(f"xl/worksheets/sheet{i}.xml").decode("utf-8") for i in range(1, 6)]
        for name in ("Inspection", "Statistics", "AS9102 Form 1", "AS9102 Form 2", "AS9102 Form 3"):  # (two parts: their spread)
            self.assertIn(f'name="{name}"', book)
        for want in ("Part # S/N 0042", "Part # 2", "<v>5.002</v>", "<v>5.009</v>", "Pass"):
            self.assertIn(want, sheets[0])
        for want in ("1. Part Number", "WM-1001", "S/N 0042", "FAI-7", "6. Drawing Number", "D-1001", "10. Organization Name", "Acme Machine", "V123", "PO 5512",
                     "19. Signature", "B. P."):
            self.assertIn(want, sheets[2])
        for want in ("5. Material or Process Name", "10. Certificate of Conformance Number", "11. Functional Test Procedure Number", "13. Comments", "WM-1001"):
            self.assertIn(want, sheets[3])
        for want in ("9. Results", "12. Prepared By", "B. P."):
            self.assertIn(want, sheets[4])
        # and the PDF beside it: the results on the page, the one outside its limits in red
        doc = pymupdf.open(done["pdf"])
        try:
            text = doc[0].get_text()
            for want in ("Part # S/N 0042", "5.002", "5.0090", "Pass", "Drawing: D-1001 Rev C"):
                self.assertIn(want, text)
            red = [s["text"] for b in doc[0].get_text("dict")["blocks"] for ln in b.get("lines", []) for s in ln["spans"] if s["color"] == 0xCC0000]
            self.assertEqual(red, ["5.0090"])
        finally:
            doc.close()

    def test_results_imported_from_an_export(self):
        res = self.auto()
        five = next(c for c in res["chars"] if c["text"] == "5.000 ±.005")
        two = next(c for c in res["chars"] if c["text"] == "2X Ø.375 +.002/-.000")
        thread = next(c for c in res["chars"] if c["kind"] == "thread")
        self.ed.run("balloon_multiply", {"ids": [two["id"]]})
        # a CMM's report: a row for each dimension, the measured value beside its nominal and tolerances
        cmm = os.path.join(self.dir.name, "cmm.csv")
        with open(cmm, "w", encoding="utf-8") as f:
            f.write(f"Part,WM-1001\nDIM,Nominal,+Tol,-Tol,Measured,Dev\nDIM {five['n']},5.000,.005,.005,5.0021,.0021\nDIM {two['n']}.2,.375,.002,0,.3764,.0014\nDIM 99,1,1,1,1,0\n")
        pre = self.ed.run("balloon_import", {"path": cmm, "preview": True})
        self.assertEqual((pre["count"], pre["guess"]["head"], pre["guess"]["key"], pre["guess"]["values"]), (5, 1, 0, [4]))
        res = self.ed.run("balloon_import", {"path": cmm, "head": 1, "key": 0, "values": [4]})["result"]
        self.assertEqual((res["imported"], res["parts"], res["unmatched"]), (2, 1, ["99"]))
        pid = str(res["samples"][0]["id"])
        self.assertEqual(res["samples"][0]["name"], "Measured")
        self.assertEqual((res["results"][str(five["id"])][pid], res["results"][f"{two['id']}.2"][pid]), ("5.0021", ".3764"))
        # a gage's spreadsheet: a column for each part, Pass and Fail for what isn't measured
        from solidsmufs.kernel import xlsx
        book = os.path.join(self.dir.name, "gage.xlsx")
        xlsx.write(book, [{"name": "Data", "rows": [["Balloon", "S/N 1", "S/N 2"], [five["n"], 5.003, 4.994], [thread["n"], "OK", "NG"]]}])
        pre = self.ed.run("balloon_import", {"path": book, "preview": True})
        self.assertEqual((pre["guess"]["head"], pre["guess"]["key"], pre["guess"]["values"]), (0, 0, [1, 2]))
        res = self.ed.run("balloon_import", {"path": book, "head": 0, "key": 0, "values": [1, 2]})["result"]
        names = {s["name"]: str(s["id"]) for s in res["samples"]}
        self.assertEqual(set(names), {"Measured", "S/N 1", "S/N 2"})
        self.assertEqual(res["results"][str(thread["id"])], {names["S/N 1"]: "Pass", names["S/N 2"]: "Fail"})
        self.assertEqual(res["results"][str(five["id"])][names["S/N 2"]], "4.994")
        # a row for each measurement, the part in a column; imported again into parts already there by name
        log = os.path.join(self.dir.name, "log.txt")
        with open(log, "w", encoding="utf-8") as f:
            f.write(f"Serial\tChar\tActual\nS/N 1\t{five['n']}\t5,001\nS/N 3\t{five['n']}\t5,004\nS/N 3\t{thread['n']}\tP\n")
        pre = self.ed.run("balloon_import", {"path": log, "preview": True})
        self.assertEqual((pre["guess"]["key"], pre["guess"]["part"], pre["guess"]["values"]), (1, 0, [2]))
        res = self.ed.run("balloon_import", {"path": log, "head": 0, "key": 1, "values": [2], "part": 0})["result"]
        names = {s["name"]: str(s["id"]) for s in res["samples"]}
        self.assertEqual(len(res["samples"]), 4)
        self.assertEqual((res["results"][str(five["id"])][names["S/N 1"]], res["results"][str(five["id"])][names["S/N 3"]]), ("5.001", "5.004"))
        # undone as one
        self.ed.run("undo", {})
        self.assertEqual(len(self.ed.run("balloons", {})["samples"]), 3)
        # the CMM's one column into a part already there, whatever the column is called
        res = self.ed.run("balloon_import", {"path": cmm, "head": 1, "key": 0, "values": [4], "into": int(names["S/N 2"])})["result"]
        self.assertEqual((len(res["samples"]), res["results"][str(five["id"])][names["S/N 2"]]), (3, "5.0021"))
        with self.assertRaises(ValueError):
            self.ed.run("balloon_import", {"path": log, "head": 0, "key": 2, "values": [1]})  # (no balloon numbers there)

    def test_statistics(self):
        c = {"lo": 4.995, "hi": 5.005}
        self.assertIsNone(balloons.stats(c, ["5.001", "Pass", ""]))  # (fewer than two numbers)
        s = balloons.stats(c, ["5.001", "5.003", "4.999", "Pass"])
        self.assertEqual((s["n"], round(s["mean"], 6), round(s["range"], 6), round(s["sd"], 6)), (3, 5.001, .004, .002))
        self.assertAlmostEqual(s["cp"], .01 / (6 * .002))
        self.assertAlmostEqual(s["cpk"], .004 / (3 * .002))
        one = balloons.stats({"lo": None, "hi": .125}, [".100", ".110"])
        self.assertIsNone(one["cp"])
        self.assertAlmostEqual(one["cpk"], (.125 - .105) / (3 * one["sd"]))
        self.assertIsNone(balloons.stats(c, ["5", "5"])["cpk"])  # (no spread at all)
        # the first article workbook works it out from the measurements on its Inspection sheet
        from solidsmufs.kernel import report
        res = self.auto()
        five = next(x for x in res["chars"] if x["text"] == "5.000 ±.005")
        a = self.ed.run("balloon_part_add", {})["result"]["part"]
        b = self.ed.run("balloon_part_add", {})["result"]["part"]
        self.ed.run("balloon_result", {"key": str(five["id"]), "part": a, "value": "5.001"})
        self.ed.run("balloon_result", {"key": str(five["id"]), "part": b, "value": "5.003"})
        sheets = report.build(self.ed._insp(), "p.pdf", 2, "list")
        self.assertEqual([s["name"] for s in sheets], ["Inspection", "Statistics", "AS9102 Form 1", "AS9102 Form 2", "AS9102 Form 3"])
        row = next(r for r in sheets[1]["rows"] if r and r[0][0] == five["n"])
        at = next(i for i, r in enumerate(sheets[0]["rows"], 1) if r and r[0] and r[0][0] == five["n"])  # (its row on the Inspection sheet)
        self.assertEqual(row[5][0]["f"].split(",", 1)[1], f"AVERAGE('Inspection'!$L${at}:$M${at}),\"\")")
        self.assertIn("MIN((", row[11][0]["f"])
        self.assertEqual([s["name"] for s in report.build(self.ed._insp(), "p.pdf", 1, "list")][:2], ["Inspection", "Statistics"])  # (two parts measured)

    def test_renumber_orders(self):
        res = self.auto()
        at = {c["text"]: c["at"] for c in res["chars"]}
        order = lambda r: [c["text"] for c in sorted(r["chars"], key=lambda c: (c["n"], c["sub"] or 0))]  # noqa: E731
        listed = order(res)
        rows = order(self.ed.run("balloon_renumber", {"order": "rows"})["result"])
        # across a row at a time: each balloon is below the one before by less than a row, or starts a lower row
        ys = [at[t][1] for t in rows]
        self.assertTrue(all(b >= a - 45 for a, b in zip(ys, ys[1:])), (rows, ys))
        cols = order(self.ed.run("balloon_renumber", {"order": "columns"})["result"])
        xs = [at[t][0] for t in cols]
        self.assertTrue(all(b >= a - 45 for a, b in zip(xs, xs[1:])), (cols, xs))
        clock = order(self.ed.run("balloon_renumber", {"order": "clockwise"})["result"])
        cx, cy = sum(at[t][0] for t in clock) / len(clock), sum(at[t][1] for t in clock) / len(clock)
        import math
        angles = [(math.atan2(at[t][0] - cx, cy - at[t][1]) + 2 * math.pi) % (2 * math.pi) for t in clock]
        self.assertEqual(angles, sorted(angles))
        self.assertEqual(sorted(clock), sorted(listed))
        # the numbers stay 1 to n, the PDF's balloons say them
        res = self.ed.run("balloons", {})
        self.assertEqual(sorted(c["n"] for c in res["chars"]), list(range(1, len(res["chars"]) + 1)))
        with self.assertRaises(ValueError):
            self.ed.run("balloon_renumber", {"order": "sideways"})

    def test_the_requirement_follows_an_edit(self):
        res = self.auto()
        five = next(c for c in res["chars"] if c["text"] == "5.000 ±.005")
        two = next(c for c in res["chars"] if c["text"] == "2X Ø.375 +.002/-.000")
        general = next(c for c in res["chars"] if c["text"] == "3.750")
        got = lambda r, c: next(x for x in r["chars"] if x["id"] == c["id"])  # noqa: E731
        r = self.ed.run("balloon_edit", {"id": five["id"], "plus": .01, "minus": .01})["result"]
        self.assertEqual((got(r, five)["text"], got(r, five)["lo"]), ("5.000 ±.010", 4.99))
        r = self.ed.run("balloon_edit", {"id": two["id"], "count": 4})["result"]
        self.assertEqual(got(r, two)["text"], "4X Ø.375 +.002/-.000")
        r = self.ed.run("balloon_edit", {"id": general["id"], "nominal": 3.8, "places": 3})["result"]  # (still the title block's tolerance)
        self.assertEqual((got(r, general)["text"], got(r, general)["tol"], got(r, general)["hi"]), ("3.800", "default", 3.805))
        r = self.ed.run("balloon_edit", {"id": general["id"], "plus": .002, "minus": .002})["result"]
        self.assertEqual(got(r, general)["text"], "3.800 ±.002")
        r = self.ed.run("balloon_edit", {"id": five["id"], "plus": .02, "text": "5.000 +.020 -.010 (as I want it)"})["result"]
        self.assertEqual(got(r, five)["text"], "5.000 +.020 -.010 (as I want it)")  # (what's typed stands)
        balloon = next(a for a in self.ed.fz[0].annots() if a.info.get("id") == f"ssb-{two['id']}")
        self.assertIn("4X Ø.375", balloon.info["content"])

    def test_views_and_balloons_follow_their_pages(self):
        import pymupdf
        self.ed.run("pages_blank", {"at": 1})  # page 0 the print, page 1 blank
        self.auto()
        w = self.ed.fz[0].rect.width
        v = self.ed.run("balloon_view_add", {"page": 0, "rect": [0, 0, w / 2, 792], "name": "Front"})["result"]["view"]
        first = self.ed.fz[0]
        hidden = [a for a in first.annots() if a.info.get("subject") == "Balloon view"]
        self.assertEqual(len(hidden), 1)
        self.assertTrue(hidden[0].flags & pymupdf.PDF_ANNOT_IS_HIDDEN)
        self.assertEqual(self.ed.run("annots", {}), [])  # (no comment to the editor)
        n = len(self.ed.run("balloons", {})["chars"])
        marks = lambda i: [a.info.get("subject") for a in self.ed.fz[i].annots()]  # noqa: E731
        # moved: the view and the balloons go with their page
        self.ed.run("pages_order", {"order": [1, 0]})
        res = self.ed.run("balloons", {})
        self.assertEqual(([x["page"] for x in res["views"]], {c["page"] for c in res["chars"]}), ([1], {1}))
        # copied: one list still, and the copy has no balloons or view of its own
        self.ed.run("pages_duplicate", {"pages": [1]})
        res = self.ed.run("balloons", {})
        self.assertEqual((len(res["chars"]), [x["page"] for x in res["views"]], {c["page"] for c in res["chars"]}), (n, [1], {1}))
        self.assertEqual((marks(2).count("Balloon"), marks(2).count("Balloon view")), (0, 0))
        # another print's pages brought in: none of its balloons come with them
        other = os.path.join(self.dir.name, "other.pdf")
        self.ed.run("save", {"path": other})
        self.ed.run("pages_insert_file", {"at": 0, "paths": [other]})
        res = self.ed.run("balloons", {})
        self.assertEqual((len(res["chars"]), [x["page"] for x in res["views"]], {c["page"] for c in res["chars"]}), (n, [4], {4}))
        self.assertEqual(sum(marks(i).count("Balloon") + marks(i).count("Balloon view") for i in range(3)), 0)
        # its page deleted: the view goes with it
        res = self.ed.run("pages_delete", {"pages": [4]})
        res = self.ed.run("balloons", {})
        self.assertEqual((res["views"], res["chars"]), ([], []))
        self.ed.run("undo", {})
        res = self.ed.run("balloons", {})
        self.assertEqual(([x["id"] for x in res["views"]], len(res["chars"])), ([v], n))

    def test_flatten_keeps_the_balloons(self):
        self.auto()
        w = self.ed.fz[0].rect.width
        self.ed.run("balloon_view_add", {"page": 0, "rect": [0, 0, w / 2, 792]})
        self.ed.run("annot_add", {"page": 0, "kind": "text", "rect": [1080, 40, 20, 20], "text": "a note to bake in"})
        before = self.ed.run("balloons", {})
        self.ed.run("flatten", {})
        after = self.ed.run("balloons", {})
        self.assertEqual(([c["label"] for c in after["chars"]], len(after["views"])), ([c["label"] for c in before["chars"]], 1))
        subjects = [a.info.get("subject") for a in self.ed.fz[0].annots()]
        self.assertEqual((subjects.count("Balloon"), subjects.count("Balloon view"), len(subjects)), (len(before["chars"]), 1, len(before["chars"]) + 1))
        # the balloons' numbers aren't the print's own text now, so reading it again finds the same, no more
        again = self.auto()
        self.assertEqual(sorted(c["text"] for c in again["chars"]), sorted(c["text"] for c in before["chars"]))

    def test_views(self):
        res = self.auto()
        w = self.ed.fz[0].rect.width
        # a view round the left half of the sheet, starting at 10; one round the right half
        left = self.ed.run("balloon_view_add", {"page": 0, "rect": [0, 0, w / 2, 792]})["result"]
        right = self.ed.run("balloon_view_add", {"page": 0, "rect": [w / 2, 0, w / 2, 792], "name": "Section B-B"})["result"]
        a, b = left["view"], right["view"]
        self.assertEqual([(v["name"], v["color"]) for v in right["views"]], [("View 1", "#1f77b4"), ("Section B-B", "#e67e22")])
        mine = lambda r, v: [c for c in r["chars"] if c["view"] == v]  # noqa: E731
        self.assertEqual(len(mine(right, a)) + len(mine(right, b)), len(right["chars"]))
        self.assertTrue(mine(right, a) and mine(right, b))
        self.assertTrue(all(c["color"] == "#e67e22" for c in mine(right, b)))
        # its balloons are drawn in its color in the PDF
        c = mine(right, b)[0]
        annot = next(x for x in self.ed.fz[0].annots() if x.info.get("id") == f"ssb-{c['id']}")
        self.assertEqual(tuple(round(v, 2) for v in annot.colors["stroke"]), (round(0xe6 / 255, 2), round(0x7e / 255, 2), round(0x22 / 255, 2)))
        # renumbered view by view: the right one first now, the left one from 10
        self.ed.run("balloon_view_edit", {"id": b, "move": -1})
        res = self.ed.run("balloon_view_edit", {"id": a, "start": 10, "color": "#123456", "name": "Front"})["result"]
        self.assertEqual([(v["name"], v["color"], v["start"]) for v in res["views"]], [("Section B-B", "#e67e22", None), ("Front", "#123456", 10)])
        res = self.ed.run("balloon_renumber", {"order": "rows"})["result"]
        nb, na = sorted(c["n"] for c in mine(res, b)), sorted(c["n"] for c in mine(res, a))
        self.assertEqual(nb, list(range(1, len(nb) + 1)))
        self.assertEqual(na, list(range(10, 10 + len(na))))
        # Auto Balloon keeps the views and numbers by them; saved with the PDF; a view deleted, its balloons are red again
        res = self.auto()
        self.assertEqual(len(res["views"]), 2)
        self.assertEqual(min(c["n"] for c in mine(res, a)), 10)
        res = self.ed.run("balloon_view_delete", {"id": a})["result"]
        self.assertEqual(([v["id"] for v in res["views"]], {c["color"] for c in res["chars"] if c["view"] is None}), ([b], {None}))
        with self.assertRaises(ValueError):
            self.ed.run("balloon_view_add", {"page": 0, "rect": [10, 10, 2, 2]})

    def test_sampling(self):
        self.assertEqual(balloons.sample(5), [1, 2, 3, 4, 5])
        self.assertEqual(balloons.sample(25, "ends"), [1, 25])
        self.assertEqual(balloons.sample(25, "thirds"), [1, 13, 25])
        self.assertEqual(balloons.sample(25, "one_in", 5), [1, 6, 11, 16, 21, 25])
        self.assertEqual(balloons.sample(25, "one_in", 5, last=False), [1, 6, 11, 16, 21])
        self.assertEqual(balloons.sample(20, "percent", 10), [1, 20])
        self.assertEqual(balloons.sample(3, "percent", 10), [1])
        self.assertEqual(balloons.sample(1, "ends"), [1])
        for bad in [(0,), (5, "one_in", 0), (5, "percent", 150), (5, "sideways")]:
            with self.assertRaises(ValueError):
                balloons.sample(*bad)
        self.assertEqual(balloons.frequency(25, "one_in", 5), "1 in 5, and the last (lot of 25)")
        self.auto()
        res = self.ed.run("balloon_sample", {"lot": 25, "how": "one_in", "n": 5})["result"]
        self.assertEqual(([s["name"] for s in res["samples"]], res["added"]), (["#1", "#6", "#11", "#16", "#21", "#25"], 6))
        self.assertEqual((res["info"]["frequency"], res["info"]["parts"]), ("1 in 5, and the last (lot of 25)", 6))
        self.assertEqual(self.ed.run("balloon_sample", {"lot": 25, "how": "ends"})["result"]["added"], 0)  # (#1 and #25 are there)
        with self.assertRaises(ValueError):
            self.ed.run("balloon_sample", {"lot": 500, "how": "every"})

    def test_the_requirement_follows_its_numbers(self):
        def edit(text, **o):
            c = {"kind": "dim", "text": text, "count": 1, **balloons.parse(text, "in")[0]}
            c.pop("span", None)
            c.update(o)
            if any(k in o for k in ("plus", "minus")) and "lo" not in o:
                c.update(lo=None, hi=None, tol="print")
            balloons.limits(c, {})
            return balloons.restate(c, text)
        self.assertEqual(edit("5.000 ±.005", plus=.010, minus=.010), "5.000 ±.010")
        self.assertEqual(edit("2X Ø.375 +.002/-.000", plus=.003), "2X Ø.375 +.003/-.000")
        self.assertEqual(edit("2.500 +.005/-.000", minus=.002), "2.500 +.005/-.002")
        self.assertEqual(edit("Ø.470 ±.010 THRU", nominal=.475, places=3), "Ø.475 ±.010 THRU")
        self.assertEqual(edit(".2500-.2505", lo=.2495, hi=.2505, plus=None, minus=None), ".2495-.2505")
        self.assertEqual(edit("R.125 MAX", hi=.130, nominal=.130), "R.130 MAX")
        self.assertEqual(edit("63.3 ±0.1", nominal=63.4, places=1), "63.4 ±0.1")
        c = {"kind": "angle", "text": "30°", "nominal": 30.0, "places": 0, "plus": 1.0, "minus": 1.0, "tol": "print", "lo": 29.0, "hi": 31.0}
        self.assertEqual(balloons.restate(c, "30°"), "30° ±1°")
        for kind, text in [("thread", "1/4-20 UNC-2B"), ("note", "1. DEBURR")]:
            self.assertEqual(balloons.restate({"kind": kind, "text": text, "nominal": 1.0}, text), text)
        self.assertEqual(balloons.restate({"kind": "dim", "text": "(3.000)", "nominal": 3.1, "tol": "ref"}, "(3.000)"), "(3.000)")
        self.assertEqual(balloons.recount("Ø.375 ±.005", 4), "4X Ø.375 ±.005")
        self.assertEqual(balloons.recount("4X Ø.375 ±.005", 1), "Ø.375 ±.005")
        self.assertEqual(balloons.recount(".030 X 45°", 2), "2X .030 X 45°")

    def test_a_requirement_said_of_one(self):
        self.assertEqual(balloons.single("4X Ø.250 ±.005"), "Ø.250 ±.005")
        self.assertEqual(balloons.single("2X (Ø.250)"), "(Ø.250)")
        self.assertEqual(balloons.single(".030 X 45°"), ".030 X 45°")
        self.assertEqual(balloons.single("2 X 45°"), "2 X 45°")
        self.assertEqual(balloons.single("1/4-20 UNC-2B"), "1/4-20 UNC-2B")

    def test_sub_numbers(self):
        from solidsmufs.kernel import report
        res = self.auto()
        labels = lambda r: [c["label"] for c in r["chars"]]  # noqa: E731
        self.assertEqual(labels(res), ["1", "2", "3", "4", "5", "6"])
        ids = [c["id"] for c in res["chars"]]
        # 3 goes under 2, then 4 (now 3) too, ahead of it
        res = self.ed.run("balloon_edit", {"id": ids[2], "n": "2.2"})["result"]
        self.assertEqual(labels(res), ["1", "2.1", "2.2", "3", "4", "5"])
        res = self.ed.run("balloon_edit", {"id": ids[3], "n": "2.2"})["result"]
        self.assertEqual([(c["id"], c["label"]) for c in res["chars"]][1:4], [(ids[1], "2.1"), (ids[3], "2.2"), (ids[2], "2.3")])
        # another under 2, by the button: empty, beside the last of them
        res = self.ed.run("balloon_sub", {"id": ids[1]})["result"]
        new = next(c for c in res["chars"] if c["id"] == res["ids"][0])
        self.assertEqual((new["label"], new["text"], new["page"]), ("2.4", "", 0))
        self.assertEqual(labels(res), ["1", "2.1", "2.2", "2.3", "2.4", "3", "4"])
        annots = [a.info["content"].split(":")[0] for a in self.ed.fz[0].annots() if a.info.get("subject") == "Balloon"]
        self.assertEqual(sorted(annots), sorted(labels(res)))
        # a plain number takes one out again; with one left under a number, its sub-number goes
        res = self.ed.run("balloon_edit", {"id": ids[3], "n": 1})["result"]
        self.assertEqual(labels(res), ["1", "2", "3.1", "3.2", "3.3", "4", "5"])
        self.ed.run("balloon_delete", {"ids": [ids[2], new["id"]]})
        res = self.ed.run("balloon_renumber", {})["result"]
        self.assertEqual(labels(res), ["1", "2", "3", "4", "5"])
        with self.assertRaises(ValueError):
            self.ed.run("balloon_edit", {"id": ids[0], "n": "two"})
        # on a lone balloon, the first under a number
        res = self.ed.run("balloon_sub", {"id": ids[0]})["result"]
        self.assertEqual(labels(res)[:3], ["1", "2.1", "2.2"])
        # in the report, and through a save
        page = report.sheet(self.ed._insp(), "p.pdf", 5)
        self.assertIn("2.1", [row[0][0] for row in page["rows"] if row and row[0]])
        out = os.path.join(self.dir.name, "subs.pdf")
        self.ed.run("save", {"path": out})
        from solidsmufs.kernel.pdfdoc import PdfFile
        from solidsmufs.kernel.pdfedit import PdfEditor
        pdf = PdfFile(out)
        try:
            self.assertEqual(labels(PdfEditor(pdf, out).run("balloons", {}))[:3], ["1", "2.1", "2.2"])
        finally:
            pdf.close()

    def test_report_as_the_sheet_to_fill_in(self):
        from solidsmufs.kernel import report
        res = self.auto()
        c = next(c for c in res["chars"] if c["text"] == "5.000 ±.005")
        self.ed.run("balloon_edit", {"id": c["id"], "desc": "Overall Length", "gage": "Calipers"})
        self.ed.run("balloon_info", {"info": {"part": "WM-1001", "job": "J-77", "frequency": "1 in 5", "parts": 12}})
        out = os.path.join(self.dir.name, "sheet.xlsx")
        self.ed.run("balloon_report", {"path": out, "footer": "FM-1 Inspection Report\n\nLimits are absolute"})
        with zipfile.ZipFile(out) as z:
            self.assertEqual(sum(n.startswith("xl/worksheets/") for n in z.namelist()), 1)
            for name in z.namelist():
                xml.dom.minidom.parseString(z.read(name))
            page = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        for want in ("WM-1001", "J-77", "1 in 5", "Overall Length", "Calipers", "FM-1 Inspection Report", "Limits are absolute", "mergeCell", "<v>4.995</v>"):
            self.assertIn(want, page)
        self.assertEqual(page.count("DIMENSION DESCRIPTION"), 3)  # 12 parts: three tables of five
        self.assertEqual(page.count("Part # ____"), 15)
        data = {"chars": [{"n": 1, "page": 0, "kind": "dim", "text": "2X Ø.375 +.002/-.000", "count": 2, "nominal": .375, "lo": .375, "hi": .377, "places": 3},
                          {"n": 2, "page": 0, "kind": "dim", "text": "0.625 (REF)", "count": 1, "nominal": .625, "lo": None, "hi": None, "places": 3},
                          {"n": 3, "page": 0, "kind": "thread", "text": "1/4-20 UNC-2B", "count": 1, "places": 0}], "unit": "in", "tols": {}}
        page = report.sheet(data, "p.pdf", 5)
        r = next(i for i, row in enumerate(page["rows"]) if row[0] and row[0][0] == "DIMENSION DESCRIPTION")
        a, b, c = page["rows"][r + 1:r + 4]
        self.assertEqual([a[0][0], a[1][0], a[3], a[4], a[5]], [1, "2X Diameter", (.375, "num3"), (.375, "num3"), (.377, "num3")])
        self.assertEqual([b[1][0], b[3][0]], ["Dimension", "0.625 (REF)"])  # no limits: as the print says, across the three
        self.assertIn(f"D{r + 3}:F{r + 3}", page["merge"])
        self.assertEqual([c[1][0], c[3][0]], [balloons.KIND_LABEL["thread"], "1/4-20 UNC-2B"])
        self.assertEqual(page["color"][0]["range"], f"G{r + 2}:K{r + 4}")

    def test_a_turned_page(self):
        path = os.path.join(self.dir.name, "turned.pdf")
        _print(path, rotate=90)
        from solidsmufs.kernel.pdfdoc import PdfFile
        from solidsmufs.kernel.pdfedit import PdfEditor
        pdf = PdfFile(path)
        try:
            res = PdfEditor(pdf, path).run("balloon_auto", {"extra": {"unit": "in", "pages": {}}})["result"]
            # (its text runs down the page now: the sizes are read all the same, a note isn't)
            self.assertEqual(sorted(c["text"] for c in res["chars"]), ["(3.000)", "1/4-20 UNC-2B", "2.500 +.005/-.000", "2X Ø.375 +.002/-.000", "3.750", "5.000 ±.005"])
            w, h = pdf.fz[0].rect.width, pdf.fz[0].rect.height  # as shown: 792 x 1224
            for c in res["chars"]:
                self.assertTrue(0 < c["at"][0] < w and 0 < c["at"][1] < h, c["at"])
                self.assertTrue(abs(c["at"][0] - (c["box"][0] + c["box"][2] / 2)) < 200 and abs(c["at"][1] - (c["box"][1] + c["box"][3] / 2)) < 200)
        finally:
            pdf.close()


if __name__ == "__main__":
    unittest.main()
