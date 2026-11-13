"""Editing PDFs (kernel/pdfedit.py): comments, pages, forms, the pages' own text and pictures, redaction, undo and
saving. Every edit is checked by reading the result back, mostly from a saved file opened afresh."""

import base64
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pymupdf  # noqa: E402

from solidsmufs.kernel.pdfdoc import PdfFile  # noqa: E402
from solidsmufs.kernel.pdfedit import PdfEditor  # noqa: E402


def _png(w=40, h=20, rgb=(200, 30, 30)):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), 0)
    pix.set_rect(pix.irect, rgb)
    return "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode()


def _make(path, pages=3, rotate_second=False, form=False):
    d = pymupdf.open()
    for i in range(pages):
        pg = d.new_page(width=612, height=792)
        pg.insert_text((72, 100), f"Page {i + 1} quick brown fox", fontsize=14)
        pg.insert_text((72, 140), "SECRET 555-1234 here", fontsize=12)
        pg.insert_text((72, 180), "Line below stays", fontsize=12)
    if rotate_second and pages > 1:
        d[1].set_rotation(90)
    if form:
        pg = d[0]
        w = pymupdf.Widget()
        w.field_type, w.field_name, w.rect = pymupdf.PDF_WIDGET_TYPE_TEXT, "Name", pymupdf.Rect(72, 300, 300, 320)
        pg.add_widget(w)
        c = pymupdf.Widget()
        c.field_type, c.field_name, c.rect = pymupdf.PDF_WIDGET_TYPE_CHECKBOX, "Agree", pymupdf.Rect(72, 340, 86, 354)
        pg.add_widget(c)
    d.save(path)
    d.close()


class Editing(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ss-edit-"))
        self.path = self.dir / "doc.pdf"
        _make(self.path, rotate_second=True, form=True)
        self.pdf = PdfFile(str(self.path))
        self.ed = PdfEditor(self.pdf, self.path)

    def tearDown(self):
        self.pdf.close()

    def reopen(self, path=None):
        self.ed.run("save", {"path": str(path) if path else None})
        return pymupdf.open(path or self.path)

    def ink_at(self, page, x, y, w=4, h=4):
        """How dark the page is around (x, y) as shown, drawn at 2 pixels per point."""
        s = 2
        raw = self.pdf.tile(page, s, int(x * s), int(y * s), int(w * s), int(h * s))
        px = np.frombuffer(raw, np.uint8).reshape(int(h * s), int(w * s), 4)
        return 255 - px[..., :3].mean()

    # ------------------------------------------------------------------ comments
    def test_every_kind_of_comment(self):
        e = self.ed
        e.run("annot_add", {"page": 0, "kind": "highlight", "rects": [[72, 86, 200, 18]], "contents": "check"})
        e.run("annot_add", {"page": 0, "kind": "underline", "rects": [[72, 130, 100, 14]]})
        e.run("annot_add", {"page": 0, "kind": "strikeout", "rects": [[72, 170, 100, 14]]})
        e.run("annot_add", {"page": 0, "kind": "note", "at": [400, 100], "contents": "a sticky note"})
        e.run("annot_add", {"page": 0, "kind": "text", "rect": [300, 400, 200, 40], "text": "Typed words", "fontsize": 14,
                            "textColor": "#0000ff"})
        e.run("annot_add", {"page": 0, "kind": "rect", "rect": [100, 500, 80, 50], "color": "#ff0000"})
        e.run("annot_add", {"page": 0, "kind": "ellipse", "rect": [200, 500, 80, 50]})
        e.run("annot_add", {"page": 0, "kind": "cloud", "rect": [300, 500, 80, 50]})
        e.run("annot_add", {"page": 0, "kind": "arrow", "points": [[100, 600], [200, 650]]})
        e.run("annot_add", {"page": 0, "kind": "ink", "points": [[[400, 600], [420, 620], [440, 600]]]})
        e.run("annot_add", {"page": 0, "kind": "stamp", "rect": [400, 680, 150, 50], "stamp": "Approved"})
        e.run("annot_add", {"page": 0, "kind": "stamp", "rect": [100, 700, 80, 40], "image": _png()})
        kinds = sorted(a["kind"] for a in e.run("annots", {}))
        self.assertEqual(kinds, sorted(["highlight", "underline", "strikeout", "note", "text", "rect", "ellipse", "rect",
                                        "line", "ink", "stamp", "stamp"]))
        listed = {a["kind"]: a for a in e.run("annots", {"page": 0})}
        self.assertEqual(listed["highlight"]["contents"], "check")
        self.assertTrue(listed["line"]["arrow"])
        self.assertEqual(listed["text"]["fontsize"], 14)
        self.assertEqual(listed["text"]["textColor"], "#0000ff")
        clouds = [a for a in e.run("annots", {"page": 0}) if a["clouds"]]
        self.assertEqual(len(clouds), 1)
        # they're drawn on the page, and survive saving: Acrobat reads the same annotations
        self.assertGreater(self.ink_at(0, 100, 500, 4, 50), 10)  # the rectangle's left side
        d = self.reopen()
        self.assertEqual(len(list(d[0].annots())), 12)
        self.assertFalse(self.ed.state()["dirty"])

    def test_turned_page_puts_comments_where_shown(self):
        """Page 2 is turned a quarter by its /Rotate: a box drawn on it as shown lands there, and lists back the same."""
        e = self.ed
        self.assertEqual(self.pdf.pages()[1]["w"], 792)
        r = e.run("annot_add", {"page": 1, "kind": "rect", "rect": [500, 100, 120, 60], "width": 4})["result"]
        self.assertEqual([round(v) for v in r["rect"]], [500, 100, 120, 60])
        self.assertGreater(self.ink_at(1, 499, 120, 3, 3), 50)  # the left side, where it was drawn
        self.assertLess(self.ink_at(1, 560, 130, 3, 3), 5)  # inside it, paper

    def test_move_resize_restyle_and_delete(self):
        e = self.ed
        a = e.run("annot_add", {"page": 0, "kind": "rect", "rect": [100, 400, 50, 50], "width": 2})["result"]
        b = e.run("annot_set", {"page": 0, "id": a["id"], "rect": [300, 450, 100, 30], "color": "#00ff00", "width": 3,
                                "contents": "moved"})["result"]
        self.assertEqual([round(v) for v in b["rect"]], [300, 450, 100, 30])
        self.assertEqual((b["color"], b["width"], b["contents"]), ("#00ff00", 3, "moved"))
        ink = e.run("annot_add", {"page": 0, "kind": "ink", "points": [[[100, 600], [150, 650]]]})["result"]
        moved = e.run("annot_set", {"page": 0, "id": ink["id"], "rect": [300, 600, ink["rect"][2], ink["rect"][3]]})["result"]
        self.assertAlmostEqual(moved["points"][0][0][0], 300 + (100 - ink["rect"][0]), delta=1)
        e.run("annot_reply", {"page": 0, "id": b["id"], "contents": "agreed"})
        self.assertEqual([x["replyTo"] for x in e.run("annots", {"page": 0}) if x["contents"] == "agreed"], [b["id"]])
        e.run("annot_delete", {"page": 0, "ids": [b["id"]]})  # its reply goes too
        self.assertEqual([x["kind"] for x in e.run("annots", {"page": 0})], ["ink"])

    def test_moving_again_and_again_keeps_the_size(self):
        e = self.ed
        a = e.run("annot_add", {"page": 1, "kind": "cloud", "rect": [100, 100, 80, 40], "width": 3})["result"]
        for k in range(5):
            r = a["rect"]
            a = e.run("annot_set", {"page": 1, "id": a["id"], "rect": [r[0] + 10, r[1], r[2], r[3]]})["result"]
        self.assertEqual([round(v) for v in a["rect"]], [150, 100, 80, 40])

    def test_copy_a_comment(self):
        e = self.ed
        made = {}
        for kind, args in (("rect", {"rect": [100, 400, 80, 40], "width": 3}), ("line", {"points": [[100, 500], [200, 540]]}),
                           ("ink", {"points": [[[100, 600], [150, 650]]]}), ("note", {"at": [400, 400], "contents": "n"}),
                           ("text", {"rect": [300, 500, 120, 30], "text": "words"}), ("highlight", {"rects": [[72, 86, 100, 18]]})):
            made[kind] = e.run("annot_add", {"page": 0, "kind": kind, **args})["result"]
        for kind, a in made.items():
            c = e.run("annot_clone", {"page": 0, "id": a["id"]})["result"]
            self.assertEqual((c["kind"], c["contents"]), (kind, a["contents"]), kind)
            self.assertEqual([round(v) for v in c["rect"]], [round(a["rect"][0]) + 12, round(a["rect"][1]) + 12,
                                                             round(a["rect"][2]), round(a["rect"][3])], kind)
        other = e.run("annot_clone", {"page": 0, "id": made["rect"]["id"], "to": 2})["result"]
        self.assertEqual((other["page"], len(list(self.pdf.fz[2].annots()))), (2, 1))
        stamp = e.run("annot_add", {"page": 0, "kind": "stamp", "rect": [400, 680, 150, 50], "stamp": "Draft"})["result"]
        with self.assertRaises(ValueError):
            e.run("annot_clone", {"page": 0, "id": stamp["id"]})
        self.assertTrue(e.run("annot_image", {"page": 0, "id": stamp["id"]}).startswith("data:image/png;base64,"))

    def test_a_lines_ends_and_text_that_grows(self):
        e = self.ed
        line = e.run("annot_add", {"page": 0, "kind": "arrow", "points": [[100, 500], [200, 540]], "color": "#0000ff"})["result"]
        moved = e.run("annot_set", {"page": 0, "id": line["id"], "points": [[100, 500], [300, 450]]})["result"]
        self.assertEqual(([[round(v) for v in q] for q in moved["points"]], moved["arrow"], moved["color"]),
                         ([[100, 500], [300, 450]], True, "#0000ff"))
        box = e.run("annot_add", {"page": 0, "kind": "text", "rect": [300, 500, 120, 20], "text": "short", "fontsize": 12})["result"]
        self.assertEqual(round(box["rect"][3]), 20)  # what was asked for holds it
        grown = e.run("annot_set", {"page": 0, "id": box["id"], "text": "\n".join(["one", "two", "three", "four"])})["result"]
        self.assertGreater(grown["rect"][3], 4 * 12)  # tall enough for four lines now
        self.assertEqual(round(grown["rect"][2]), 120)
        typed = e.run("annot_add", {"page": 0, "kind": "text", "rect": [72, 600, 0, 0], "fit": True, "text": "Typed on", "fontsize": 12})["result"]
        self.assertTrue(40 < typed["rect"][2] < 70 and 14 < typed["rect"][3] < 24)  # just around its words

    # ------------------------------------------------------------------ pages
    def test_organize_pages(self):
        e = self.ed
        r = e.run("pages_rotate", {"pages": [0], "by": 90})
        self.assertEqual(r["pages"][0]["w"], 792)
        e.run("pages_order", {"order": [2, 0, 1]})
        self.assertIn("Page 3", self.pdf.fz[0].get_text())
        e.run("pages_move", {"pages": [0], "to": 3})  # page 3 back to the end
        self.assertIn("Page 3", self.pdf.fz[2].get_text())
        e.run("pages_duplicate", {"pages": [1]})
        self.assertEqual(self.pdf.fz.page_count, 4)
        e.run("pages_delete", {"pages": [2]})
        e.run("pages_blank", {"at": 0})
        self.assertEqual((self.pdf.fz.page_count, self.pdf.fz[0].get_text().strip()), (4, ""))
        with self.assertRaises(ValueError):
            e.run("pages_delete", {"pages": [0, 1, 2, 3]})
        other = self.dir / "other.pdf"
        _make(other, pages=2)
        png = self.dir / "pic.png"
        png.write_bytes(base64.b64decode(_png().split(",")[1]))
        r = e.run("pages_insert_file", {"at": 4, "paths": [str(other), str(png)]})
        self.assertEqual((r["result"]["added"], len(r["pages"])), (3, 7))
        out = self.dir / "two.pdf"
        e.run("pages_extract", {"pages": [1, 2], "path": str(out)})
        self.assertEqual(pymupdf.open(out).page_count, 2)
        paths = e.run("split", {"every": 3})["paths"]
        self.assertEqual([pymupdf.open(p).page_count for p in paths], [3, 3, 1])
        self.assertTrue(paths[0].endswith("doc (pages 1-3).pdf"))

    def test_crop(self):
        e = self.ed
        r = e.run("pages_crop", {"pages": [0, 2], "rect": [50, 60, 400, 300]})
        self.assertEqual((r["pages"][0]["w"], r["pages"][0]["h"]), (400, 300))
        self.assertEqual((r["pages"][2]["w"], r["pages"][2]["h"]), (400, 300))
        self.assertIn("quick brown", self.pdf.fz[0].get_text())  # the text at (72, 100) is still in view
        e.run("pages_uncrop", {"pages": [0]})
        self.assertEqual(self.pdf.pages()[0]["w"], 612)

    # ------------------------------------------------------------------ forms and signing
    def test_fill_and_flatten(self):
        e = self.ed
        fields = {f["name"]: f for f in e.run("fields", {"page": 0})}
        self.assertEqual((fields["Name"]["kind"], fields["Agree"]["kind"]), ("text", "checkbox"))
        e.run("field_set", {"page": 0, "id": fields["Name"]["id"], "value": "Pat Doe"})
        e.run("field_set", {"page": 0, "id": fields["Agree"]["id"], "value": True})
        d = self.reopen()
        values = {w.field_name: w.field_value for w in d[0].widgets()}
        self.assertEqual(values["Name"], "Pat Doe")
        self.assertNotEqual(values["Agree"], "Off")
        e.run("annot_add", {"page": 0, "kind": "stamp", "rect": [300, 700, 120, 40], "image": _png(120, 40)})
        e.run("flatten", {})
        self.assertEqual(list(self.pdf.fz[0].widgets()), [])
        self.assertEqual(list(self.pdf.fz[0].annots()), [])
        self.assertIn("Pat Doe", self.pdf.fz[0].get_text())
        self.assertGreater(self.ink_at(0, 340, 710, 20, 10), 50)  # the signature is part of the page now

    # ------------------------------------------------------------------ the pages' own text and pictures
    def test_edit_a_line_of_text(self):
        e = self.ed
        line = e.run("text_at", {"page": 0, "at": [100, 136]})
        self.assertEqual(line["text"], "SECRET 555-1234 here")
        self.assertEqual(line["size"], 12)
        e.run("text_replace", {"page": 0, "rect": line["rect"], "text": "PUBLIC words", "size": line["size"],
                               "color": line["color"]})
        text = self.pdf.fz[0].get_text()
        self.assertNotIn("SECRET", text)
        self.assertIn("PUBLIC words", text)
        self.assertIn("quick brown fox", text)  # the lines above and below stay
        self.assertIn("Line below stays", text)
        self.assertEqual(self.pdf.find("PUBLIC")[0]["page"], 0)  # and finding sees the change
        self.assertIsNone(e.run("text_at", {"page": 0, "at": [500, 700]}))

    def test_add_text_on_a_turned_page(self):
        e = self.ed
        e.run("text_add", {"page": 1, "at": [100, 500], "text": "Across the page", "size": 20})
        hit = self.pdf.find("Across the page")[0]["rects"][0]
        self.assertGreater(hit[2], hit[3] * 3)  # reads across the page as shown, not up it
        self.assertAlmostEqual(hit[0], 100, delta=3)

    def test_pictures(self):
        e = self.ed
        e.run("image_add", {"page": 0, "rect": [300, 500, 100, 50], "image": _png()})
        pics = e.run("images", {"page": 0})
        self.assertEqual(len(pics), 1)
        self.assertGreater(self.ink_at(0, 340, 520), 50)
        e.run("image_set", {"page": 0, "id": pics[0]["id"], "rect": [100, 600, 100, 50]})
        self.assertLess(self.ink_at(0, 340, 520), 5)
        self.assertGreater(self.ink_at(0, 140, 620), 50)
        moved = e.run("images", {"page": 0})
        e.run("image_delete", {"page": 0, "id": moved[0]["id"]})
        self.assertLess(self.ink_at(0, 140, 620), 5)

    def test_picture_on_a_turned_page_stays_upright(self):
        e = self.ed
        wide = _png(80, 20)
        e.run("image_add", {"page": 1, "rect": [300, 300, 160, 40], "image": wide})
        pic = e.run("images", {"page": 1})[0]
        self.assertGreater(pic["rect"][2], pic["rect"][3] * 3)  # as wide as asked, as shown
        self.assertGreater(self.ink_at(1, 440, 315), 50)
        self.assertLess(self.ink_at(1, 310, 360), 5)

    def test_redaction_removes_the_words(self):
        e = self.ed
        hits = self.pdf.find("555-1234")
        e.run("annot_add", {"page": 0, "kind": "redact", "rects": hits[0]["rects"]})
        self.assertIn("555-1234", self.pdf.fz[0].get_text())  # only marked so far
        e.run("redact_apply", {})
        d = self.reopen()
        self.assertNotIn("555-1234", d[0].get_text())
        self.assertIn("SECRET", d[0].get_text())
        self.assertGreater(self.ink_at(0, hits[0]["rects"][0][0] + 5, hits[0]["rects"][0][1] + 3), 200)  # a black box

    def test_strike_through_leaves_the_words(self):
        e = self.ed
        word = self.pdf.find("SECRET")[0]["rects"]
        gone = self.pdf.find("555-1234")[0]["rects"]
        e.run("annot_add", {"page": 0, "kind": "strike", "rects": word})
        marks = e.run("annots", {})
        self.assertEqual([(a["kind"], a["subject"]) for a in marks], [("strikeout", "Strike through")])
        e.run("annot_add", {"page": 0, "kind": "redact", "rects": gone})
        e.run("redact_apply", {})
        d = self.reopen()
        self.assertIn("SECRET", d[0].get_text())  # struck, still there and readable
        self.assertNotIn("555-1234", d[0].get_text())
        self.assertEqual(list(d[0].annots()), [])
        x, y, w, h = word[0]
        lines = [p for p in d[0].get_drawings() if any(it[0] == "l" for it in p["items"])]
        self.assertTrue(any(abs(p["rect"].y0 - (y + h / 2)) < 2 and p["rect"].x0 <= x + 1 and p["rect"].x1 >= x + w - 1 for p in lines))
        self.assertEqual(e.run("annots", {}), [])

    def test_strike_through_on_its_own(self):
        e = self.ed
        e.run("annot_add", {"page": 0, "kind": "strike", "rects": self.pdf.find("SECRET")[0]["rects"]})
        self.assertEqual(e.run("redact_apply", {})["result"]["struck"], 1)
        self.assertIn("SECRET", self.reopen()[0].get_text())
        with self.assertRaises(ValueError):
            e.run("redact_apply", {})

    # ------------------------------------------------------------------ undo and saving
    def test_undo_redo_and_save_as(self):
        e = self.ed
        self.assertFalse(e.state()["dirty"])
        e.run("annot_add", {"page": 0, "kind": "rect", "rect": [100, 400, 50, 50]})
        e.run("pages_delete", {"pages": [2]})
        self.assertTrue(e.state()["dirty"])
        r = e.run("undo", {})
        self.assertEqual(len(r["pages"]), 3)
        e.run("undo", {})
        self.assertFalse(e.state()["dirty"])  # back where it was saved
        self.assertEqual(len(list(self.pdf.fz[0].annots())), 0)
        e.run("redo", {})
        self.assertEqual(len(list(self.pdf.fz[0].annots())), 1)
        other = self.dir / "copy.pdf"
        d = self.reopen(other)
        self.assertEqual(len(list(d[0].annots())), 1)
        self.assertEqual(e.state()["path"], str(other))
        self.assertTrue(e.state()["redo"])

    def test_password_pdf_keeps_its_password(self):
        locked = self.dir / "locked.pdf"
        d = pymupdf.open(self.path)
        d.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="own")
        pdf = PdfFile(str(locked), "pw")
        ed = PdfEditor(pdf, locked)
        ed.run("annot_add", {"page": 0, "kind": "note", "at": [300, 300], "contents": "x"})
        ed.run("save", {})
        pdf.close()
        again = pymupdf.open(locked)
        self.assertTrue(again.needs_pass)
        self.assertTrue(again.authenticate("pw"))


if __name__ == "__main__":
    unittest.main()
