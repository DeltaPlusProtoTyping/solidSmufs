"""Saving PDFs other programs check: signed, certified, PDF/A, XFA; and one another program changed meanwhile.

    .venv\\Scripts\\python -m unittest tests.test_pdfsave -v
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf  # noqa: E402

from solidsmufs.kernel.pdfdoc import PdfFile  # noqa: E402
from solidsmufs.kernel.pdfedit import PdfEditor  # noqa: E402

PDFA = """<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF
xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about=""
xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/" pdfaid:part="2" pdfaid:conformance="B"/></rdf:RDF></x:xmpmeta><?xpacket end="w"?>"""


def _make(path, signed=False, certified=None, pdfa=False, objstms=False):
    doc = pymupdf.open()
    for i in range(2):
        pg = doc.new_page(width=612, height=792)
        pg.insert_text((72, 100), f"Page {i + 1}: 4X Ø.250 ±.002", fontsize=12)
    if signed or certified:  # a signature's dictionary (its bytes aren't really signed: what's checked is that they stay)
        sig = doc.get_new_xref()
        doc.update_object(sig, "<</Type/Sig/Filter/Adobe.PPKLite/SubFilter/adbe.pkcs7.detached/ByteRange[0 10 20 30]"
                               "/Contents<0000>/Name(Pat Smith)"
                               + (f"/Reference[<</TransformMethod/DocMDP/TransformParams<</P {certified}/V/1.2>>>>]" if certified else "")
                               + ">>")
        field = doc.get_new_xref()
        doc.update_object(field, f"<</FT/Sig/T(Signature1)/V {sig} 0 R>>")
        doc.xref_set_key(doc.pdf_catalog(), "AcroForm", f"<</Fields[{field} 0 R]/SigFlags 3>>")
        if certified:
            doc.xref_set_key(doc.pdf_catalog(), "Perms", f"<</DocMDP {sig} 0 R>>")
    if pdfa:
        doc.set_xml_metadata(PDFA)
    doc.save(path, use_objstms=1 if objstms else 0, garbage=1)
    doc.close()


class Saving(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ss-pdfsave-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        os.environ["LOCALAPPDATA"] = str(self.dir / "app")  # (recovery copies stay out of the real one)

    def open(self, name="print.pdf", **make):
        path = self.dir / name
        _make(path, **make)
        pdf = PdfFile(str(path))
        self.addCleanup(pdf.close)
        return path, PdfEditor(pdf, path)

    @staticmethod
    def note(ed):
        ed.run("annot_add", {"page": 0, "kind": "text", "rect": [300, 300, 20, 20], "text": "check this"})

    def test_plain_pdf_saves_as_before(self):
        path, ed = self.open()
        self.note(ed)
        r = ed.run("save", {})
        self.assertNotIn("ask", r["result"])
        self.assertFalse(r["result"]["appended"])

    def test_comments_on_a_signed_pdf_go_on_the_end(self):
        for objstms in (False, True):
            with self.subTest(objstms=objstms):
                path, ed = self.open(f"signed{int(objstms)}.pdf", signed=True, objstms=objstms)
                before = path.read_bytes()
                self.assertEqual(ed.guards["signed"], ["Pat Smith"])
                self.note(ed)
                ed.run("undo", {})
                ed.run("redo", {})
                r = ed.run("save", {})
                self.assertTrue(r["result"]["appended"])
                after = path.read_bytes()
                self.assertEqual(after[:len(before)], before)  # what was signed is byte for byte the same
                d = pymupdf.open(path)
                self.assertFalse(d.is_repaired)
                self.assertEqual(len(list(d[0].annots())), 1)
                d.close()
                PdfFile(str(path)).close()  # (PDFium reads it too)
                self.note(ed)  # and again, onto the end of that
                self.assertTrue(ed.run("save", {})["result"]["appended"])
                self.assertEqual(path.read_bytes()[:len(after)], after)

    def test_undo_across_a_save_loses_nothing(self):
        path, ed = self.open("undo.pdf", signed=True, objstms=True)
        self.note(ed)
        ed.run("save", {})
        ed.run("undo", {})  # (the document as before that save: its numbering doesn't know the save's)
        self.note(ed)
        self.note(ed)
        r = ed.run("save", {})
        if "ask" in r["result"]:
            r = ed.run("save", {"guardsOk": True})
        d = pymupdf.open(path)
        self.assertEqual(len(list(d[0].annots())), len(list(ed.fz[0].annots())))
        d.close()

    def test_editing_the_pages_of_a_signed_pdf_asks_first(self):
        path, ed = self.open(signed=True)
        before = path.read_bytes()
        ed.run("pages_rotate", {"pages": [0], "by": 90})
        r = ed.run("save", {})
        self.assertEqual(r["result"]["ask"]["kind"], "guarded")
        self.assertIn("Pat Smith", r["result"]["ask"]["text"])
        self.assertEqual(path.read_bytes(), before)  # nothing written
        r = ed.run("save", {"guardsOk": True})
        self.assertFalse(r["result"]["appended"])
        d = pymupdf.open(path)
        self.assertEqual(d[0].rotation, 90)
        d.close()
        ed.run("pages_rotate", {"pages": [0], "by": 90})
        self.assertNotIn("ask", ed.run("save", {})["result"])  # (said once)

    def test_certified_for_no_changes_asks_even_for_comments(self):
        path, ed = self.open(certified=1)
        self.assertEqual(ed.guards["certified"], 1)
        self.note(ed)
        r = ed.run("save", {})
        self.assertEqual(r["result"]["ask"]["kind"], "guarded")
        self.assertIn("no changes", r["result"]["ask"]["text"])

    def test_certified_for_comments_takes_them_on_the_end(self):
        path, ed = self.open(certified=3)
        self.note(ed)
        self.assertTrue(ed.run("save", {})["result"]["appended"])

    def test_pdfa(self):
        path, ed = self.open(pdfa=True)
        self.assertEqual(ed.guards["pdfa"], "PDF/A-2b")
        self.note(ed)
        self.assertTrue(ed.run("save", {})["result"]["appended"])
        d = pymupdf.open(path)
        self.assertIn("pdfaid", d.get_xml_metadata())
        d.close()
        ed.run("text_add", {"page": 0, "at": [100, 300], "text": "NEW"})
        r = ed.run("save", {})
        self.assertIn("PDF/A-2b", r["result"]["ask"]["text"])

    def test_changed_by_another_program_asks_first(self):
        path, ed = self.open()
        self.note(ed)
        time.sleep(0.05)
        other = pymupdf.open(path)
        other[0].insert_text((72, 200), "SAVED ELSEWHERE", fontsize=12)
        other.save(str(path) + ".x")
        other.close()
        os.replace(str(path) + ".x", path)
        st = os.stat(path)
        os.utime(path, (st.st_atime, st.st_mtime + 5))
        theirs = path.read_bytes()
        r = ed.run("save", {})
        self.assertEqual(r["result"]["ask"]["kind"], "changed")
        self.assertEqual(path.read_bytes(), theirs)
        self.assertNotIn("ask", ed.run("save", {"changedOk": True})["result"])
        self.assertNotIn("ask", (self.note(ed), ed.run("save", {}))[1]["result"])  # (its own save is no change by another)

    def test_save_as_a_copy_keeps_the_signature_too(self):
        path, ed = self.open(signed=True)
        before = path.read_bytes()
        self.note(ed)
        copy = self.dir / "copy.pdf"
        r = ed.run("save", {"path": str(copy)})
        self.assertTrue(r["result"]["appended"])
        self.assertEqual(copy.read_bytes()[:len(before)], before)
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
