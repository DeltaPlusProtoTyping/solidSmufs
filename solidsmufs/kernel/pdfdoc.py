"""PDF pages, drawn by MuPDF (PyMuPDF), with their text read by PDFium through QtPdf. It runs in the document's worker, so a damaged file only takes its
own document down, and pages come back as raw pixels: nothing is spent encoding images for a local window.
"""

import math
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


def quad_along(r, u):
    """A box as a quad the way text along `u` reads in it (u: which way a line runs, y down the page; taken to the
    nearest of across, up, back or down): [upper left, upper right, lower left, lower right] of the words, which is
    how a PDF's underline, strike-out or highlight knows where their baseline is."""
    import pymupdf
    ux, uy = (1 if u[0] >= 0 else -1, 0) if abs(u[0]) >= abs(u[1]) else (0, 1 if u[1] >= 0 else -1)
    vx, vy = uy, -ux  # up from the baseline
    corners = [(r.x0, r.y0), (r.x1, r.y0), (r.x0, r.y1), (r.x1, r.y1)]
    along, up = [x * ux + y * uy for x, y in corners], [x * vx + y * vy for x, y in corners]
    a0, a1, b0, b1 = min(along), max(along), min(up), max(up)

    def at(a, b):
        return pymupdf.Point(a * ux + b * vx, a * uy + b * vy)
    return pymupdf.Quad(at(a0, b1), at(a1, b1), at(a0, b0), at(a1, b0))


def reading_quad(pg, r, spans=()):
    """A box on a page (the page's own points) as a quad the way the words in it read: along the text it covers most
    (spans: the page's, each with its line's "dir"). Over no text: along its longer side as shown, left to right or
    bottom to top."""
    import pymupdf
    r = pymupdf.Rect(r)
    r.normalize()
    best, most = None, 0.0
    for s in spans:
        b = pymupdf.Rect(s["bbox"])
        area = (b & r).get_area() if b.intersects(r) else 0.0
        if area > most:
            best, most = s, area
    if best is not None:
        return quad_along(r, best["dir"])
    shown = pymupdf.Rect(r) * pg.rotation_matrix
    shown.normalize()
    turn = pg.derotation_matrix
    u = pymupdf.Point((1, 0) if shown.width >= shown.height else (0, -1)) * turn - pymupdf.Point(0, 0) * turn
    return quad_along(r, (u.x, u.y))


class PdfFile:
    """A PDF open for showing and editing. MuPDF (PyMuPDF) holds the document and draws its pages, so edits show
    at once; QtPdf (PDFium) reads its text for selecting, finding and the hover marks, from a copy brought up to
    date after an edit that changes what's on the pages."""

    def __init__(self, path, password=None):
        _qt()
        import pymupdf
        data = Path(path).read_bytes()  # from memory, so the file isn't held: it can be replaced or saved over while it's on screen
        try:
            self.fz = pymupdf.open(stream=data, filetype="pdf")
        except Exception:
            raise ValueError("This PDF can't be read (it may be damaged).") from None
        if self.fz.needs_pass and not (password and self.fz.authenticate(password)):
            raise ValueError(PASSWORD_WRONG if password else PASSWORD_NEEDED)
        if self.fz.page_count < 1:
            raise ValueError("This PDF can't be read (it may be damaged).")
        self.password = password
        self.raw = data  # the file as it was read: what a save can add to the end of (a signed PDF's signature stays good)
        self._qt_doc = None
        self._load_qt(data)
        self.text = {}
        self._dirs = {}  # page -> [(a line of text's box, which way it reads)]

    def _load_qt(self, data):
        from PySide6.QtCore import QBuffer, QByteArray, QCoreApplication, QIODevice
        from PySide6.QtPdf import QPdfDocument
        if self._qt_doc is not None:
            self._qt_doc.close()
        doc = QPdfDocument()
        if self.password:
            doc.setPassword(self.password)
        self._data = QByteArray(data)
        self._buffer = QBuffer(self._data)
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        doc.load(self._buffer)
        for _ in range(2000):
            if doc.status() not in (QPdfDocument.Status.Null, QPdfDocument.Status.Loading):
                break
            QCoreApplication.processEvents()
            time.sleep(0.002)
        err = doc.error()
        if err == QPdfDocument.Error.IncorrectPassword:
            raise ValueError(PASSWORD_WRONG if self.password else PASSWORD_NEEDED)
        if err != QPdfDocument.Error.None_ or doc.pageCount() < 1:
            raise ValueError("This PDF can't be read (it may be damaged).")
        self._qt_doc = doc
        self._qt_stale = False

    @property
    def doc(self):
        """QtPdf's copy, for text: read again from MuPDF's when an edit has changed the pages."""
        if self._qt_stale:
            import pymupdf
            self._load_qt(self.fz.tobytes(encryption=pymupdf.PDF_ENCRYPT_KEEP))
        return self._qt_doc

    def changed(self):
        """The pages' text or order changed: QtPdf's copy and the text read from it are out of date."""
        self._qt_stale = True
        self.text = {}
        self._dirs = {}

    def close(self):
        if self._qt_doc is not None:
            self._qt_doc.close()
        self.fz.close()

    def pages(self):
        """[{"w", "h" in points, "label"}]: as shown, turned by the page's own /Rotate"""
        out = []
        for i, pg in enumerate(self.fz):
            r = pg.rect
            out.append({"w": round(r.width, 3), "h": round(r.height, 3), "label": pg.get_label() or str(i + 1)})
        return out

    def title(self):
        return (self.fz.metadata or {}).get("title") or ""

    def tile(self, page, scale, x, y, w, h, turns=0):
        """RGBA pixels of a piece of a page drawn at `scale` pixels per point, turned by `turns` quarter turns:
        (x, y) is the piece's corner on the whole drawn page."""
        import pymupdf
        pg = self.fz[page]
        r = pg.rect
        W, H = max(round(r.width * scale), 1), max(round(r.height * scale), 1)  # the page unturned
        # drawn unturned and turned here. Turn 1 is a quarter turn clockwise: the turned page's (x, y) is the page's
        # (y, H - x), as pdfview.js maps it back
        turns %= 4
        cx, cy, cw, ch = {0: (x, y, w, h), 1: (y, H - x - w, h, w), 2: (W - x - w, H - y - h, w, h),
                          3: (W - y - h, x, h, w)}[turns]
        sx, sy = W / r.width, H / r.height  # exactly W x H pixels for the whole page
        clip = pymupdf.Rect(cx / sx, cy / sy, (cx + cw) / sx, (cy + ch) / sy)  # as shown: MuPDF turns by /Rotate itself
        try:
            pix = pg.get_pixmap(matrix=pymupdf.Matrix(sx, sy), clip=clip, alpha=False)
        except Exception as e:
            raise ValueError(f"That page couldn't be drawn: {e}") from None
        raw = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride // pix.n, pix.n)[:, :pix.width, :3]
        # MuPDF rounds the clip outwards to whole pixels: the piece starts (ox, oy) into what it drew
        ox, oy = cx - pix.x, cy - pix.y
        piece = np.full((ch, cw, 4), 255, np.uint8)
        src = raw[max(oy, 0):max(oy, 0) + ch, max(ox, 0):max(ox, 0) + cw]
        piece[:src.shape[0], :src.shape[1], :3] = src
        return np.ascontiguousarray(np.rot90(piece, -turns)[:h, :w]).tobytes()

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

    def _line_dirs(self, page):
        if page not in self._dirs:
            import pymupdf
            self._dirs[page] = [{"bbox": pymupdf.Rect(ln["bbox"]), "dir": ln["dir"]}
                                for b in self.fz[page].get_text("dict", flags=0)["blocks"] for ln in b.get("lines", [])]
        return self._dirs[page]

    def select(self, page, ax, ay, bx, by):
        """The text between two points on a page, a whole word at a time, in reading order: {"text", "rects", "quads"}
        (points from the page's top left, as shown). rects: each line's box. quads: the same lines as [upper left,
        upper right, lower left, lower right] the way their words read (up the page for a drawing's turned
        dimensions), for marks that need to know: underline, strike-out, squiggly. By MuPDF: PDFium's hit test misses
        whole lines of some PDFs."""
        import pymupdf
        pg = self.fz[page]
        words = pg.get_text("words")  # (x0, y0, x1, y1, word, block, line, n) in reading order, unturned points
        if not words:
            return {"text": "", "rects": [], "quads": []}
        m = pg.derotation_matrix
        boxes = [pymupdf.Rect(w[:4]) for w in words]

        def nearest(p, start):
            """The word under p. Else, where the drag starts: the nearest on its line, a couple of words' width
            away at most, or the nearest within 12 points (a press on blank paper far from any words selects
            nothing). Where it ends: the nearest on its line however far along (past a line's end is its end), or
            else on the line nearest above or below (dragged off under the last line, the selection stays)."""
            best = level = None
            off = []
            for i, r in enumerate(boxes):
                if r.contains(p):
                    return i
                dx, dy = max(r.x0 - p.x, 0, p.x - r.x1), max(r.y0 - p.y, 0, p.y - r.y1)
                if dy == 0 and (level is None or dx < level[0]):
                    level = (dx, i)
                d = math.hypot(dx, dy)
                if d < 12 and (best is None or d < best[0]):
                    best = (d, i)
                off.append((dy, dx, i))
            if level is not None and (not start or level[0] <= max(24.0, 3 * boxes[level[1]].height)):
                return level[1]
            if best is not None:
                return best[1]
            if start:
                return None
            least = min(o[0] for o in off)
            return min((o for o in off if o[0] <= least + 1.5), key=lambda o: o[1])[2]
        ia = nearest(pymupdf.Point(ax, ay) * m, True)
        ib = None if ia is None else nearest(pymupdf.Point(bx, by) * m, False)
        if ia is None or ib is None:
            return {"text": "", "rects": [], "quads": []}
        i0, i1 = min(ia, ib), max(ia, ib)
        text, lines, last = [], {}, None
        for w, r in zip(words[i0:i1 + 1], boxes[i0:i1 + 1]):
            key = (w[5], w[6])
            if last is not None:
                text.append(" " if key == last else "\n")
            text.append(w[4])
            lines[key] = lines[key] | r if key in lines else pymupdf.Rect(r)
            last = key
        rects, quads = [], []
        turn = pg.rotation_matrix
        for r in lines.values():
            q = r * turn
            q.normalize()
            rects.append([round(q.x0, 2), round(q.y0, 2), round(q.width, 2), round(q.height, 2)])
            quad = reading_quad(pg, r, self._line_dirs(page))
            quads.append([[round(c.x, 2), round(c.y, 2)] for c in (p * turn for p in (quad.ul, quad.ur, quad.ll, quad.lr))])
        return {"text": "".join(text), "rects": rects, "quads": quads}

    def find(self, query, limit=1000):
        """Every place `query` appears, ignoring case: [{"page", "rects"}]."""
        q = query.lower()
        out = []
        if not q:
            return out
        for page in range(self.doc.pageCount()):
            text = self.page_text(page).lower()
            at = text.find(q)
            k = None
            while at >= 0 and len(out) < limit:
                rects = self._rects(self.doc.getSelectionAtIndex(page, at, len(q)))
                if k is None:
                    # PDFium gives places in the page's plain points; a page with a /UserUnit (very large sheets) is
                    # shown that many times bigger, as MuPDF sizes it
                    pg = self.fz[page]
                    plain = self.doc.pagePointSize(page).width()
                    k = pg.rect.width / plain if plain > 0 else 1.0
                    k = k if abs(k - 1) > 0.01 else 1.0
                if k != 1.0:
                    rects = [[round(v * k, 2) for v in r] for r in rects]
                out.append({"page": page, "rects": rects})
                at = text.find(q, at + len(q))
        return out
