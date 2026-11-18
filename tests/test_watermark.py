"""Edit > Remove watermark (kernel/watermark.py, PdfEditor's watermark_* edits): tagged watermarks (Acrobat's and
Word's), watermark layers and comments, and large tilted words repeated on the pages."""

import tempfile
import unittest
from pathlib import Path

import pymupdf

from solidsmufs.kernel import watermark
from solidsmufs.kernel.pdfdoc import PdfFile
from solidsmufs.kernel.pdfedit import PdfEditor


def _stamp_source():
    src = pymupdf.open()
    pg = src.new_page(width=400, height=100)
    pg.insert_text((10, 70), "CONFIDENTIAL", fontsize=48, color=(0.8, 0.8, 0.8))
    pg.draw_rect(pymupdf.Rect(5, 5, 395, 95), color=(0.8, 0.8, 0.8), width=3)  # (outlines too: the whole block goes)
    return src


def _wrap_last(doc, pg, before, after=b"EMC"):
    """Wraps the page's last drawing (what show_pdf_page just added) in marked content."""
    xrefs = pg.get_contents()
    x = xrefs[-1]
    data = doc.xref_stream(x)
    i = data.rfind(b"q")
    doc.update_stream(x, data[:i] + before + b"\n" + data[i:] + b"\n" + after + b"\n")


def _make(path, pages=3):
    d = pymupdf.open()
    src = _stamp_source()
    for i in range(pages):
        pg = d.new_page(width=612, height=792)
        pg.insert_text((72, 100), f"Page {i + 1} part 12345-001", fontsize=12)
        pg.insert_text((72, 140), "BREAK ALL SHARP EDGES", fontsize=12)
        pg.draw_line((72, 600), (540, 600), width=1)
        # Acrobat's way: a form drawn inside /Artifact <</Subtype /Watermark>>
        pg.show_pdf_page(pymupdf.Rect(100, 300, 500, 400), src, 0)
        _wrap_last(d, pg, b"/Artifact <</Subtype /Watermark /Type /Pagination >>BDC")
    d.save(path)
    d.close()


class Tagged(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ss-wm-"))
        self.path = self.dir / "doc.pdf"

    def open(self):
        self.pdf = PdfFile(str(self.path))
        self.ed = PdfEditor(self.pdf, self.path)
        self.addCleanup(self.pdf.close)

    def test_acrobat_watermark(self):
        _make(self.path)
        self.open()
        self.assertIn("CONFIDENTIAL", self.pdf.fz[0].get_text())
        found = self.ed.run("watermark_find", {})
        self.assertEqual([(i["kind"], i["pages"]) for i in found["items"]], [("tagged", [0, 1, 2])])
        self.assertEqual(found["page"], 0)
        self.assertTrue(found["before"].startswith("data:image/png") and found["after"] != found["before"])
        self.assertIn("CONFIDENTIAL", self.pdf.fz[0].get_text())  # (finding changes nothing)
        res = self.ed.run("watermark_remove", {})["result"]
        self.assertEqual(res["pages"], 3)
        for pg in self.pdf.fz:
            text = pg.get_text()
            self.assertNotIn("CONFIDENTIAL", text)
            self.assertIn("BREAK ALL SHARP EDGES", text)
            self.assertEqual(len([d for d in pg.get_drawings() if d["rect"].width > 300 and d["rect"].height > 50]), 0)  # its box too
            self.assertEqual(len(pg.get_drawings()), 1)  # the page's own line stays
        self.ed.run("undo", {})
        self.assertIn("CONFIDENTIAL", self.pdf.fz[2].get_text())
        # saved and opened again: still gone
        self.ed.run("watermark_remove", {})
        out = self.dir / "clean.pdf"
        self.ed.run("save", {"path": str(out)})
        with pymupdf.open(out) as d:
            self.assertNotIn("CONFIDENTIAL", "".join(p.get_text() for p in d))

    def test_layer_and_comment(self):
        d = pymupdf.open()
        pg = d.new_page()
        pg.insert_text((72, 100), "Keep me", fontsize=12)
        ocg = d.add_ocg("Watermark", on=True)
        pg.insert_text((100, 400), "SAMPLE", fontsize=60, oc=ocg)
        # a watermark comment, as some programs add one
        a = pg.add_rect_annot(pymupdf.Rect(50, 500, 200, 550))
        d.xref_set_key(a.xref, "Subtype", "/Watermark")
        d.save(self.path)
        d.close()
        self.open()
        found = self.ed.run("watermark_find", {})
        self.assertEqual(sorted(i["kind"] for i in found["items"]), ["annot", "tagged"])
        self.ed.run("watermark_remove", {})
        pg = self.pdf.fz[0]
        self.assertNotIn("SAMPLE", pg.get_text())
        self.assertIn("Keep me", pg.get_text())
        kind, val = self.pdf.fz.xref_get_key(pg.xref, "Annots")
        self.assertNotIn(str(a.xref), val if kind != "xref" else self.pdf.fz.xref_object(int(val.split()[0])))

    def test_repeated_tilted_words(self):
        d = pymupdf.open()
        for i in range(3):
            pg = d.new_page(width=612, height=792)
            pg.insert_text((72, 100), f"Sheet {i + 1}", fontsize=12)
            pg.insert_text((72, 700), "NOTES: DEBURR", fontsize=12)
            # DRAFT at 45 degrees, in light gray
            pg.insert_text((150, 550), "DRAFT", fontsize=90, color=(0.85, 0.85, 0.85), morph=(pymupdf.Point(150, 550), pymupdf.Matrix(45)))
            if i == 2:  # a note written right through it on the last page: it can't be taken out there without the note
                pg.insert_text((250, 420), "SEE DETAIL B", fontsize=12)
        d.save(self.path)
        d.close()
        self.open()
        words = watermark.words(self.pdf.fz)
        self.assertEqual([w["text"] for w in words.values()], ["DRAFT"])
        found = self.ed.run("watermark_find", {})
        self.assertEqual([(i["kind"], i["pages"]) for i in found["items"]], [("text", [0, 1, 2])])
        res = self.ed.run("watermark_remove", {})["result"]
        texts = [pg.get_text() for pg in self.pdf.fz]
        self.assertNotIn("DRAFT", texts[0])
        self.assertNotIn("DRAFT", texts[1])
        self.assertIn("NOTES: DEBURR", texts[0])
        self.assertIn("SEE DETAIL B", texts[2])
        self.assertIn("DRAFT", texts[2])  # (left where the note runs through it)
        self.assertEqual(res["kept"], [2])

    def test_a_plain_print_has_none(self):
        d = pymupdf.open()
        for i in range(2):
            pg = d.new_page()
            pg.insert_text((72, 100), "TITLE BLOCK  DWG 12345", fontsize=10)
            pg.insert_text((72, 140), "Ø.375 THRU", fontsize=12, morph=(pymupdf.Point(72, 140), pymupdf.Matrix(30)))  # a tilted callout, small
        d.save(self.path)
        d.close()
        self.open()
        self.assertEqual(self.ed.run("watermark_find", {})["items"], [])
        with self.assertRaises(ValueError):
            self.ed.run("watermark_remove", {})


class Stream(unittest.TestCase):
    def test_cut_keeps_everything_else(self):
        data = (b"q 1 0 0 1 0 0 cm BT /F1 12 Tf (keep \\) EMC) Tj ET Q\n"
                b"/Artifact <</Subtype /Watermark>> BDC q 0.5 g BT /F1 60 Tf (DRAFT) Tj ET Q EMC\n"
                b"/Span <</ActualText (x)>> BDC BT (also kept) Tj ET EMC")
        new, n = watermark.cut(None, data, "")
        self.assertEqual(n, 1)
        self.assertNotIn(b"DRAFT", new)
        self.assertIn(b"(keep \\) EMC) Tj", new)
        self.assertIn(b"(also kept)", new)
        # unbalanced q/Q inside: left as it is
        new, n = watermark.cut(None, b"/Artifact <</Subtype /Watermark>> BDC q (x) Tj EMC Q", "")
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
