"""Making a PDF fillable (kernel/pdfform.py and the field edits in kernel/pdfedit.py): the blanks found on a page,
the fields put on them, fields added, changed and removed by hand, and redaction over fields."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pymupdf  # noqa: E402

from solidsmufs.kernel import pdfform  # noqa: E402
from solidsmufs.kernel.pdfdoc import PdfFile  # noqa: E402
from solidsmufs.kernel.pdfedit import PdfEditor  # noqa: E402


def _form(pg):
    """An inspection report with every kind of blank on it."""
    pg.insert_text((72, 80), "Inspection Report", fontsize=16)
    pg.insert_text((72, 120), "Name:", fontsize=11)
    pg.draw_line((110, 122), (300, 122))
    pg.insert_text((320, 120), "Date:", fontsize=11)
    pg.draw_line((350, 122), (460, 122))
    pg.insert_text((72, 160), "Part number: ____________  Rev: _____", fontsize=11)
    pg.draw_rect(pymupdf.Rect(72, 190, 84, 202))
    pg.insert_text((90, 200), "First article", fontsize=11)
    pg.draw_rect(pymupdf.Rect(200, 190, 212, 202))
    pg.insert_text((218, 200), "In process", fontsize=11)
    for r in range(4):  # a table: its headings, and two rows to fill in
        pg.draw_line((72, 240 + 22 * r), (540, 240 + 22 * r))
    for x in (72, 200, 380, 540):
        pg.draw_line((x, 240), (x, 306))
    for x, t in ((76, "Feature"), (204, "Nominal"), (384, "Actual")):
        pg.insert_text((x, 255), t, fontsize=10)
    pg.draw_rect(pymupdf.Rect(72, 340, 540, 420))
    pg.insert_text((76, 352), "Notes", fontsize=10)
    pg.draw_line((72, 500), (260, 500))
    pg.insert_text((72, 512), "Signature", fontsize=9)
    pg.insert_text((72, 560), "This sentence is underlined", fontsize=11)  # not a blank
    pg.draw_line((72, 562), (210, 562))


class Fillable(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ss-form-"))
        self.path = self.dir / "form.pdf"
        d = pymupdf.open()
        _form(d.new_page(width=612, height=792))
        d.new_page(width=612, height=792).insert_text((72, 100), "Nothing to fill in here", fontsize=12)
        d.save(self.path)
        d.close()
        self.pdf = PdfFile(str(self.path))
        self.ed = PdfEditor(self.pdf, self.path)

    def tearDown(self):
        self.pdf.close()

    def fields(self):
        return {f["name"]: f for f in self.ed.run("fields", {})}

    def test_the_blanks_are_found_and_named(self):
        r = self.ed.run("form_auto", {})
        self.assertEqual(r["result"], {"count": 14, "pages": 1})
        self.assertTrue(r["state"]["fields"])
        f = self.fields()
        self.assertEqual(set(f), {"Name", "Date", "Part number", "Rev", "First article", "In process", "Feature", "Nominal",
                                  "Actual", "Feature 2", "Nominal 2", "Actual 2", "Notes", "Signature"})
        self.assertEqual({k for k, v in f.items() if v["kind"] == "checkbox"}, {"First article", "In process"})
        self.assertTrue(f["Notes"]["multiline"])
        self.assertFalse(f["Name"]["multiline"])
        # each sits on its blank: the rule after "Name:", the table's cells under their headings (not on them)
        x, y, w, h = f["Name"]["rect"]
        self.assertAlmostEqual(x, 110, delta=2)
        self.assertAlmostEqual(y + h, 122, delta=2)
        self.assertAlmostEqual(w, 190, delta=3)
        self.assertGreater(f["Feature"]["rect"][1], 261)
        self.assertGreater(f["Notes"]["rect"][1], 352)  # under its caption

    def test_again_adds_nothing_and_undo_takes_them_all_out(self):
        self.ed.run("form_auto", {})
        self.assertEqual(self.ed.run("form_auto", {})["result"]["count"], 0)
        self.ed.run("undo", {})
        self.assertEqual(self.ed.run("fields", {}), [])

    def test_one_page_only(self):
        self.assertEqual(self.ed.run("form_auto", {"pages": [1]})["result"]["count"], 0)
        self.assertEqual(self.ed.run("form_auto", {"pages": [0]})["result"]["count"], 14)

    def test_the_saved_file_fills_in(self):
        self.ed.run("form_auto", {})
        f = self.fields()
        self.ed.run("field_set", {"page": 0, "id": f["Name"]["id"], "value": "B. Pauza"})
        self.ed.run("field_set", {"page": 0, "id": f["First article"]["id"], "value": True})
        out = self.dir / "out.pdf"
        self.ed.run("save", {"path": str(out)})
        d = pymupdf.open(out)
        self.assertTrue(d.is_form_pdf)
        got = {w.field_name: w.field_value for w in d[0].widgets()}
        self.assertEqual(got["Name"], "B. Pauza")
        self.assertNotIn(got["First article"], (False, "Off"))
        self.assertIn(got["In process"], (False, "Off"))
        d.close()

    def test_fields_by_hand(self):
        e = self.ed
        a = e.run("field_add", {"page": 1, "kind": "text", "rect": [100, 200, 150, 18]})["result"]["id"]
        b = e.run("field_add", {"page": 1, "kind": "text", "rect": [100, 240, 150, 18]})["result"]["id"]
        c = e.run("field_add", {"page": 1, "kind": "checkbox", "rect": [100, 280, 12, 12]})["result"]["id"]
        d = e.run("field_add", {"page": 1, "kind": "combo", "rect": [100, 320, 120, 18]})["result"]["id"]
        f = self.fields()
        self.assertEqual(set(f), {"Text", "Text 2", "Check box", "Choice"})
        e.run("field_edit", {"page": 1, "id": a, "name": "Operator", "label": "Who ran it", "required": True,
                             "multiline": True, "fontsize": 9, "rect": [120, 210, 200, 40]})
        e.run("field_edit", {"page": 1, "id": b, "name": "Operator"})  # a name that's taken
        e.run("field_edit", {"page": 1, "id": d, "options": ["Pass", "Fail", " "]})
        f = self.fields()
        op = f["Operator"]
        self.assertEqual((op["label"], op["required"], op["multiline"], op["fontsize"]), ("Who ran it", True, True, 9))
        for got, want in zip(op["rect"], [120, 210, 200, 40]):
            self.assertAlmostEqual(got, want, delta=1)
        self.assertIn("Operator 2", f)
        self.assertEqual(f["Choice"]["options"], ["Pass", "Fail"])
        e.run("field_delete", {"page": 1, "ids": [c]})
        self.assertNotIn("Check box", self.fields())
        e.run("undo", {})
        self.assertIn("Check box", self.fields())
        e.run("field_delete", {})
        self.assertEqual(e.run("fields", {}), [])
        with self.assertRaises(ValueError):
            e.run("field_add", {"page": 1, "kind": "signature", "rect": [0, 0, 50, 20]})

    def test_a_turned_page(self):
        """A landscape sheet stored as a turned portrait page: the blanks are found as the page is shown."""
        d = pymupdf.open()
        pg = d.new_page(width=612, height=792)
        pg.set_rotation(90)
        m = pg.derotation_matrix
        pg.draw_line(pymupdf.Point(100, 300) * m, pymupdf.Point(400, 300) * m)  # a rule across the shown page
        box = pymupdf.Rect(100, 350, 112, 362) * m
        box.normalize()
        pg.draw_rect(box)
        got = sorted((f["kind"], [round(v) for v in f["rect"]]) for f in pdfform.detect(pg))
        d.close()
        self.assertEqual([k for k, _ in got], ["checkbox", "text"])
        self.assertEqual(got[1][1][0], 100)
        self.assertEqual(got[1][1][2], 400)
        self.assertEqual(got[1][1][3], 300)

    def test_a_scanned_form(self):
        """A picture of a form: its rules and boxes are found in the picture."""
        src = pymupdf.open(self.path)
        pix = src[0].get_pixmap(dpi=150)
        src.close()
        d = pymupdf.open()
        pg = d.new_page(width=612, height=792)
        pg.insert_image(pg.rect, pixmap=pix)
        got = pdfform.detect(pg)
        d.close()
        kinds = [f["kind"] for f in got]
        self.assertEqual(kinds.count("checkbox"), 2)
        rules = [f for f in got if f["kind"] == "text" and abs(f["rect"][3] - 122) < 3]
        self.assertEqual(len(rules), 2)  # after Name and Date
        tops = sorted(round(f["rect"][1]) for f in got if f["kind"] == "text")
        self.assertEqual(len([t for t in tops if 262 < t < 290]), 6)  # the table's six cells to fill in
        self.assertFalse([t for t in tops if 238 < t < 250])  # not its headings
        self.assertFalse([f for f in got if abs(f["rect"][3] - 562) < 3])  # nor the underlined sentence

    def test_a_drawing_isnt_taken_for_a_form(self):
        d = pymupdf.open()
        pg = d.new_page(width=612, height=792)
        for i in range(61):  # squared paper: thousands of little boxes
            pg.draw_line((20 + 9 * i, 20), (20 + 9 * i, 560))
            pg.draw_line((20, 20 + 9 * i), (560, 20 + 9 * i))
        self.assertEqual(pdfform.detect(pg), [])
        d.close()


class RedactingFields(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ss-form-"))
        self.path = self.dir / "form.pdf"
        d = pymupdf.open()
        _form(d.new_page(width=612, height=792))
        d.save(self.path)
        d.close()
        self.pdf = PdfFile(str(self.path))
        self.ed = PdfEditor(self.pdf, self.path)
        self.ed.run("form_auto", {})
        self.f = {f["name"]: f for f in self.ed.run("fields", {})}
        self.ed.run("field_set", {"page": 0, "id": self.f["Name"]["id"], "value": "B. Pauza"})

    def tearDown(self):
        self.pdf.close()

    def color_at(self, x, y):
        pix = self.pdf.fz[0].get_pixmap(clip=pymupdf.Rect(x, y, x + 2, y + 2))
        return pix.pixel(0, 0)

    def test_a_marked_field_goes_with_what_was_typed(self):
        e = self.ed
        e.run("annot_add", {"page": 0, "kind": "redact", "rects": [self.f["Name"]["rect"]]})
        e.run("redact_apply", {})
        names = {f["name"] for f in e.run("fields", {})}
        self.assertNotIn("Name", names)
        self.assertIn("Date", names)  # the others stay
        out = self.dir / "out.pdf"
        e.run("save", {"path": str(out)})
        self.assertNotIn(b"Pauza", out.read_bytes())
        x, y, w, h = self.f["Name"]["rect"]
        self.assertEqual(self.color_at(x + w / 2, y + h / 2), (0, 0, 0))

    def test_white_leaves_blank_paper(self):
        e = self.ed
        hit = self.pdf.find("Inspection")[0]["rects"]
        e.run("annot_add", {"page": 0, "kind": "redact", "rects": hit})
        e.run("redact_apply", {"fill": "white"})
        self.assertEqual(self.pdf.find("Inspection"), [])
        x, y, w, h = hit[0]
        self.assertEqual(self.color_at(x + w / 2, y + h / 2), (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
