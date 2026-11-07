"""PDF pages, drawn by PDFium through QtPdf. It runs in the document's worker, so a damaged file only takes its
own document down, and pages come back as raw pixels: nothing is spent encoding images for a local window.
"""

import os
import re
import time
from pathlib import Path

import numpy as np

from .formats import PASSWORD_NEEDED, PASSWORD_WRONG

_qt_app = None


def _qt():
    global _qt_app
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication
    if _qt_app is None:
        _qt_app = QCoreApplication.instance() or QCoreApplication([])


def models_inside(path):
    """The kinds of 3D model embedded in a PDF: a list such as ["PRC"]. The model streams always sit in plain
    sight in the file, since PDF doesn't allow them inside compressed object streams."""
    data = Path(path).read_bytes()
    found = re.findall(rb"/Subtype\s*/(PRC|U3D)\b", data)
    return sorted({k.decode() for k in found})


class PdfFile:
    def __init__(self, path, password=None):
        _qt()
        from PySide6.QtCore import QBuffer, QByteArray, QCoreApplication, QIODevice
        from PySide6.QtPdf import QPdfDocument
        self.doc = QPdfDocument()
        if password:
            self.doc.setPassword(password)
        # from memory, so the file isn't held: it can be replaced or saved over while it's on screen
        self._data = QByteArray(Path(path).read_bytes())
        self._buffer = QBuffer(self._data)
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.doc.load(self._buffer)
        for _ in range(2000):
            if self.doc.status() not in (QPdfDocument.Status.Null, QPdfDocument.Status.Loading):
                break
            QCoreApplication.processEvents()
            time.sleep(0.002)
        err = self.doc.error()
        if err == QPdfDocument.Error.IncorrectPassword:
            raise ValueError(PASSWORD_WRONG if password else PASSWORD_NEEDED)
        if err != QPdfDocument.Error.None_ or self.doc.pageCount() < 1:
            raise ValueError("This PDF can't be read (it may be damaged).")
        self.text = {}

    def close(self):
        self.doc.close()

    def pages(self):
        """[{"w", "h" in points, "label"}]"""
        out = []
        for i in range(self.doc.pageCount()):
            s = self.doc.pagePointSize(i)
            out.append({"w": round(s.width(), 3), "h": round(s.height(), 3), "label": self.doc.pageLabel(i) or str(i + 1)})
        return out

    def title(self):
        from PySide6.QtPdf import QPdfDocument
        return self.doc.metaData(QPdfDocument.MetaDataField.Title) or ""

    def tile(self, page, scale, x, y, w, h, turns=0):
        """RGBA pixels of a piece of a page drawn at `scale` pixels per point, turned by `turns` quarter turns:
        (x, y) is the piece's corner on the whole drawn page."""
        from PySide6.QtCore import QRect, QSize
        from PySide6.QtPdf import QPdfDocumentRenderOptions
        s = self.doc.pagePointSize(page)
        pw, ph = (s.height(), s.width()) if turns % 2 else (s.width(), s.height())
        o = QPdfDocumentRenderOptions()
        o.setRotation(QPdfDocumentRenderOptions.Rotation(turns % 4))
        o.setScaledSize(QSize(max(round(pw * scale), 1), max(round(ph * scale), 1)))
        o.setScaledClipRect(QRect(x, y, w, h))
        img = self.doc.render(page, QSize(w, h), o)
        if img.isNull():
            raise ValueError("That page couldn't be drawn.")
        raw = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes()).reshape(img.height(), img.bytesPerLine() // 4, 4)
        px = raw[:h, :w, [2, 1, 0, 3]].astype(np.uint16)  # Qt keeps BGRA in memory
        # on white paper: PDFium leaves bare paper transparent, and what's under a tile mustn't show through
        a = px[..., 3:]
        px[..., :3] = (px[..., :3] * a + 255 * (255 - a) + 127) // 255
        px[..., 3] = 255
        return px.astype(np.uint8).tobytes()

    def page_text(self, page):
        if page not in self.text:
            self.text[page] = self.doc.getAllText(page).text()
        return self.text[page]

    @staticmethod
    def _rects(sel):
        out = []
        for poly in sel.bounds():
            r = poly.boundingRect()
            out.append([round(r.x(), 2), round(r.y(), 2), round(r.width(), 2), round(r.height(), 2)])
        return out

    def select(self, page, ax, ay, bx, by):
        """The text between two points on a page: {"text", "rects"} (points from the page's top left)."""
        from PySide6.QtCore import QPointF
        sel = self.doc.getSelection(page, QPointF(ax, ay), QPointF(bx, by))
        return {"text": sel.text(), "rects": self._rects(sel)}

    def find(self, query, limit=1000):
        """Every place `query` appears, ignoring case: [{"page", "rects"}]."""
        q = query.lower()
        out = []
        if not q:
            return out
        for page in range(self.doc.pageCount()):
            text = self.page_text(page).lower()
            at = text.find(q)
            while at >= 0 and len(out) < limit:
                out.append({"page": page, "rects": self._rects(self.doc.getSelectionAtIndex(page, at, len(q)))})
                at = text.find(q, at + len(q))
        return out
