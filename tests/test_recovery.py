"""Autosave (recovery.py): PDF edits not saved, kept as a recovery copy and put back after the app stops."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pymupdf

from solidsmufs import recovery
from solidsmufs.kernel.pdfdoc import PdfFile
from solidsmufs.kernel.pdfedit import PdfEditor


class Recovery(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ss-rec-"))
        env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.dir / "local")})
        env.start()
        self.addCleanup(env.stop)
        self.path = self.dir / "print.pdf"
        d = pymupdf.open()
        d.new_page().insert_text((72, 100), "PART 12345", fontsize=12)
        d.save(self.path)
        d.close()

    def editor(self):
        pdf = PdfFile(str(self.path))
        self.addCleanup(pdf.close)
        return pdf, PdfEditor(pdf, self.path)

    def note(self, ed):
        ed.run("annot_add", {"page": 0, "kind": "note", "at": [100, 100], "contents": "check this"})

    def test_kept_then_put_back(self):
        pdf, ed = self.editor()
        self.assertEqual(ed.run("recover_write", {}), {"kept": False})  # nothing to keep yet
        self.assertIsNone(recovery.find(self.path))
        self.note(ed)
        self.assertEqual(ed.run("recover_write", {}), {"kept": True})
        found = recovery.find(self.path)
        self.assertEqual((found["name"], found["changed"]), ("print.pdf", False))
        self.assertEqual(len(list(pdf.fz[0].annots())), 1)
        # (the app stopped here: the edit was never saved)
        with pymupdf.open(self.path) as d:
            self.assertEqual(list(d[0].annots()), [])
        pdf, ed = self.editor()  # opened again
        r = ed.run("recover_load", {})
        self.assertTrue(r["state"]["dirty"])  # back, not saved
        self.assertEqual([a.info["content"] for a in pdf.fz[0].annots()], ["check this"])
        ed.run("undo", {})  # Undo takes them out again
        self.assertEqual(list(pdf.fz[0].annots()), [])
        ed.run("redo", {})
        ed.run("save", {})  # saved: nothing left to recover
        self.assertIsNone(recovery.find(self.path))
        with pymupdf.open(self.path) as d:
            self.assertEqual(len(list(d[0].annots())), 1)

    def test_undone_back_to_saved_lets_it_go(self):
        _pdf, ed = self.editor()
        self.note(ed)
        ed.run("recover_write", {})
        ed.run("undo", {})
        self.assertEqual(ed.run("recover_write", {}), {"kept": False})
        self.assertIsNone(recovery.find(self.path))

    def test_file_changed_since(self):
        _pdf, ed = self.editor()
        self.note(ed)
        ed.run("recover_write", {})
        later = time.time() + 60
        os.utime(self.path, (later, later))  # saved by someone else meanwhile
        self.assertTrue(recovery.find(self.path)["changed"])
        ed.run("recover_clear", {})
        self.assertIsNone(recovery.find(self.path))

    def test_save_as_lets_the_old_one_go(self):
        _pdf, ed = self.editor()
        self.note(ed)
        ed.run("recover_write", {})
        ed.run("save", {"path": str(self.dir / "copy.pdf")})
        self.assertIsNone(recovery.find(self.path))
        self.assertIsNone(recovery.find(self.dir / "copy.pdf"))


if __name__ == "__main__":
    unittest.main()
