"""Editing a PDF, as Acrobat does: comments and markups, organizing pages, filling forms and signing, editing the
pages' own text and pictures, and redacting. MuPDF (PyMuPDF) does the work on the document a PdfFile holds.

Every place and size comes in and goes out in the page's points as shown: from its top left, turned by the page's
own /Rotate (as pdfview.js and QtPdf use them). PDF annotations keep the page's unturned points; `_in` and `_out`
convert. Undo keeps whole-document snapshots, which work for every kind of edit (MuPDF's own journal refuses some,
such as inserting pages).
"""

import base64
import datetime
import getpass
import math
import os
import re
import tempfile
from pathlib import Path

from .balloonops import SUBJECT as BALLOON, VIEW as BALLOON_VIEW, BalloonOps

UNDO_BYTES = 400_000_000  # the most the snapshots for undo hold before the oldest go
HIGHLIGHT = (1.0, 0.85, 0.1)
RED = (0.86, 0.1, 0.1)

# annotation kinds as the window calls them, and as PDF does
KINDS = {"Text": "note", "FreeText": "text", "Highlight": "highlight", "Underline": "underline",
         "StrikeOut": "strikeout", "Squiggly": "squiggly", "Square": "rect", "Circle": "ellipse", "Line": "line",
         "Ink": "ink", "Polygon": "polygon", "PolyLine": "polyline", "Stamp": "stamp", "Redact": "redact",
         "Caret": "caret", "FileAttachment": "file", "Link": "link", "Widget": "field", "Popup": "popup"}
STAMPS = ["Approved", "NotApproved", "Draft", "Final", "ForComment", "Confidential", "Experimental", "AsIs",
          "Expired", "Departmental", "ForPublicRelease", "NotForPublicRelease", "Sold", "TopSecret"]
# the 14 standard fonts by look: (serif?, bold, italic) -> MuPDF's short name
BASE14 = {(False, False, False): "helv", (False, True, False): "hebo", (False, False, True): "heit",
          (False, True, True): "hebi", (True, False, False): "tiro", (True, True, False): "tibo",
          (True, False, True): "tiit", (True, True, True): "tibi"}
MONO = {(False, False): "cour", (True, False): "cobo", (False, True): "coit", (True, True): "cobi"}


def author():
    try:
        return getpass.getuser()
    except Exception:
        return ""


def _now():
    return datetime.datetime.now().astimezone().strftime("D:%Y%m%d%H%M%S%z").replace("+", "+").replace("-", "-")


def _color(c, default=None):
    """A color from the window ("#rrggbb", [r, g, b] 0..1, or None)."""
    if c is None or c == "":
        return default
    if isinstance(c, str):
        c = c.lstrip("#")
        return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return tuple(float(x) for x in c[:3])


def _hex(c):
    if not c:
        return None
    return "#" + "".join(f"{max(0, min(255, round(x * 255))):02x}" for x in c[:3])


STRIKE = "Strike through"  # the subject of a strike-through mark from the Redact tools


def _is_strike(a):
    return a.type[1] == "StrikeOut" and a.info.get("subject") == STRIKE


class PdfEditor(BalloonOps):
    def __init__(self, pdf, path):
        self.pdf = pdf
        self.path = str(path)
        self.undo, self.redo = [], []  # [(snapshot bytes, its generation)]
        self.gen = self.saved_gen = 0
        self.next_gen = 1

    @property
    def fz(self):
        return self.pdf.fz

    # ================================================================== the edit record
    def state(self):
        return {"dirty": self.gen != self.saved_gen, "undo": bool(self.undo), "redo": bool(self.redo),
                "path": self.path, "fields": self._has_fields()}

    def _has_fields(self):
        try:
            return bool(self.fz.is_form_pdf)
        except Exception:
            return False

    def _snapshot(self):
        self.undo.append((self._bytes(), self.gen))
        self.redo.clear()
        while len(self.undo) > 1 and sum(len(b) for b, _ in self.undo) > UNDO_BYTES:
            self.undo.pop(0)
        self.gen, self.next_gen = self.next_gen, self.next_gen + 1

    def _bytes(self):
        import pymupdf
        return self.fz.tobytes(encryption=pymupdf.PDF_ENCRYPT_KEEP)  # (a first write without it drops the password)

    def _restore(self, data):
        import pymupdf
        old = self.pdf.fz
        self.pdf.fz = pymupdf.open(stream=data, filetype="pdf")
        if self.pdf.fz.needs_pass:
            self.pdf.fz.authenticate(self.pdf.password or "")
        old.close()
        self.pdf.changed()

    def op_undo(self):
        if not self.undo:
            raise ValueError("There's nothing to undo.")
        data, gen = self.undo.pop()
        self.redo.append((self._bytes(), self.gen))
        self._restore(data)
        self.gen = gen
        return self._answer(None, structure=True)

    def op_redo(self):
        if not self.redo:
            raise ValueError("There's nothing to redo.")
        data, gen = self.redo.pop()
        self.undo.append((self._bytes(), self.gen))
        self._restore(data)
        self.gen = gen
        return self._answer(None, structure=True)

    def _answer(self, changed, structure=False, text=False, result=None):
        """What an edit sends back: the pages, which of them to draw again (None: all), and the record."""
        if structure or text:
            self.pdf.changed()
        out = {"pages": self.pdf.pages(), "changed": changed, "structure": structure, "text": bool(text or structure),
               "state": self.state()}
        if result is not None:
            out["result"] = result
        return out

    def run(self, op, args):
        """One edit or question from the window: {"op": name, ...}."""
        fn = getattr(self, f"op_{op}", None)
        if fn is None:
            raise ValueError(f"Unknown PDF edit: {op}")
        self._balloon_guard(op, args)
        return fn(**args)

    # ================================================================== coordinates
    def _page(self, page):
        if not 0 <= int(page) < self.fz.page_count:
            raise ValueError("That page isn't in the document any more.")
        return self.fz[int(page)]

    @staticmethod
    def _in(pg, r):
        """A rectangle [x, y, w, h] as shown, to the page's own points."""
        import pymupdf
        x, y, w, h = r
        return pymupdf.Rect(x, y, x + w, y + h) * pg.derotation_matrix

    @staticmethod
    def _pt(pg, p):
        import pymupdf
        return pymupdf.Point(p[0], p[1]) * pg.derotation_matrix

    @staticmethod
    def _out(pg, r):
        """The page's own rectangle to [x, y, w, h] as shown."""
        import pymupdf
        q = pymupdf.Rect(r) * pg.rotation_matrix
        q.normalize()
        return [round(q.x0, 2), round(q.y0, 2), round(q.width, 2), round(q.height, 2)]

    @staticmethod
    def _pt_out(pg, p):
        import pymupdf
        q = pymupdf.Point(p) * pg.rotation_matrix
        return [round(q.x, 2), round(q.y, 2)]

    # ================================================================== comments and markups
    def _annot_info(self, pg, a):
        kind = KINDS.get(a.type[1], a.type[1].lower())
        info, colors, border = a.info, a.colors or {}, a.border or {}
        out = {"id": a.xref, "kind": kind, "rect": self._out(pg, a.rect), "contents": info.get("content", ""),
               "author": info.get("title", ""), "subject": info.get("subject", ""),
               "date": info.get("modDate") or info.get("creationDate") or "",
               "color": _hex(colors.get("stroke")), "fill": _hex(colors.get("fill")),
               "width": border.get("width", -1), "opacity": a.opacity if a.opacity is not None and a.opacity >= 0 else 1,
               "clouds": border.get("clouds", -1) > 0, "replyTo": a.irt_xref or None}
        if kind == "line":
            ends = a.line_ends or (0, 0)
            out["arrow"] = bool(ends[1])
            v = a.vertices or []
            out["points"] = [self._pt_out(pg, p) for p in v]
        elif kind in ("ink",):
            out["points"] = [[self._pt_out(pg, p) for p in stroke] for stroke in (a.vertices or [])]
        elif kind in ("polygon", "polyline"):
            out["points"] = [self._pt_out(pg, p) for p in (a.vertices or [])]
        if kind == "text":
            out["fontsize"] = self._freetext_size(a)
            out["textColor"] = self._freetext_color(a)
        return out

    @staticmethod
    def _freetext_size(a):
        try:
            da = a.get_parent().parent.xref_get_key(a.xref, "DA")[1]
            m = re.search(r"([\d.]+)\s+Tf", da)
            return float(m.group(1)) if m else 11
        except Exception:
            return 11

    @staticmethod
    def _freetext_color(a):
        try:
            da = a.get_parent().parent.xref_get_key(a.xref, "DA")[1]
            m = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", da)
            return _hex([float(x) for x in m.groups()]) if m else "#000000"
        except Exception:
            return "#000000"

    def op_annots(self, page=None):
        """Every comment and markup: on one page, or the whole document. [{"page", "id", "kind", "rect", ...}]"""
        out = []
        pages = range(self.fz.page_count) if page is None else [int(page)]
        for i in pages:
            pg = self.fz[i]
            for a in pg.annots():
                kind = KINDS.get(a.type[1], "")
                if kind in ("popup", "link", "field", "") or a.info.get("subject") in (BALLOON, BALLOON_VIEW):
                    continue  # (a balloon, or a view's mark, is the inspection list's: kernel/balloonops.py)
                out.append({"page": i, **self._annot_info(pg, a)})
        return out

    def _find_annot(self, pg, xref):
        for a in pg.annots():
            if a.xref == int(xref):
                return a
        raise ValueError("That comment isn't there any more.")

    def _finish(self, pg, a, o):
        """Common properties on a new annotation, then its look."""
        a.set_info(title=o.get("author") or author(), content=o.get("contents", a.info.get("content", "")),
                   subject=o.get("subject", a.info.get("subject", "")))
        if o.get("opacity") is not None:
            a.set_opacity(float(o["opacity"]))
        a.update()
        return a

    def op_annot_add(self, page, kind, **o):
        """A new comment or markup. Rectangles, points and paths as shown; colors as "#rrggbb"."""
        import pymupdf
        self._snapshot()
        pg = self._page(page)
        color = _color(o.get("color"))
        fill = _color(o.get("fill"))
        width = float(o.get("width", 1.5))
        rot = pg.rotation
        if kind == "strike":  # a single line through the words, which stay readable: Apply makes it part of the page
            kind = "strikeout"
            color = color or (0, 0, 0)
            o["subject"] = STRIKE
        if kind in ("highlight", "underline", "strikeout", "squiggly"):
            quads = [self._in(pg, r).quad for r in o["rects"]]
            if not quads:
                raise ValueError("Select some text to mark first.")
            add = {"highlight": pg.add_highlight_annot, "underline": pg.add_underline_annot,
                   "strikeout": pg.add_strikeout_annot, "squiggly": pg.add_squiggly_annot}[kind]
            a = add(quads=quads)
            a.set_colors(stroke=color or (HIGHLIGHT if kind == "highlight" else RED))
            if o.get("contents") is None:
                o["contents"] = o.get("text", "")
        elif kind == "note":
            a = pg.add_text_annot(self._pt(pg, o["at"]), o.get("contents", ""), icon=o.get("icon", "Comment"))
            a.set_colors(stroke=color or HIGHLIGHT)
        elif kind == "text":
            r = self._in(pg, o["rect"])
            if o.get("fit"):  # sized to its words once they're in
                r = self._in(pg, [o["rect"][0], o["rect"][1], 40, 20])
            # (MuPDF draws a text box's border only for rich text, which it then loses on any change: none here)
            a = pg.add_freetext_annot(r, o.get("text", ""), fontsize=float(o.get("fontsize", 12)), fontname="Helv",
                                      text_color=_color(o.get("textColor"), (0, 0, 0)), fill_color=fill, rotate=rot,
                                      align=int(o.get("align", 0)))
            o.setdefault("contents", o.get("text", ""))
            o.setdefault("subject", "Text Box" if fill else "Typewriter")
        elif kind in ("rect", "ellipse", "cloud"):
            r = self._in(pg, o["rect"])
            a = (pg.add_circle_annot if kind == "ellipse" else pg.add_rect_annot)(r)
            a.set_colors(stroke=color or RED, fill=fill)
            a.set_border(width=width, clouds=1 if kind == "cloud" else 0)
            if kind == "cloud":
                o.setdefault("subject", "Cloud")
        elif kind in ("line", "arrow"):
            a = pg.add_line_annot(self._pt(pg, o["points"][0]), self._pt(pg, o["points"][1]))
            a.set_colors(stroke=color or RED)
            a.set_border(width=width)
            if kind == "arrow":
                a.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, pymupdf.PDF_ANNOT_LE_OPEN_ARROW)
                o.setdefault("subject", "Arrow")
        elif kind == "ink":
            strokes = [[self._pt(pg, p) for p in s] for s in o["points"] if len(s) > 1]
            if not strokes:
                raise ValueError("Draw a line to add it.")
            a = pg.add_ink_annot([[tuple(p) for p in s] for s in strokes])
            a.set_colors(stroke=color or RED)
            a.set_border(width=width)
        elif kind == "polygon":
            a = pg.add_polygon_annot([tuple(self._pt(pg, p)) for p in o["points"]])
            a.set_colors(stroke=color or RED, fill=fill)
            a.set_border(width=width, clouds=1 if o.get("clouds") else 0)
        elif kind == "stamp":
            r = self._in(pg, o["rect"])
            if o.get("image"):  # a signature, initials or a picture of a stamp: PNG as a data URL
                a = pg.add_stamp_annot(r, stamp=base64.b64decode(o["image"].split(",", 1)[-1]))
            else:
                import pymupdf as m
                name = o.get("stamp", "Approved")
                a = pg.add_stamp_annot(r, stamp=getattr(m, f"STAMP_{name}", 0))
            if rot:
                a.set_rotation(rot)
            o.setdefault("subject", o.get("stamp", "Stamp"))
            o.setdefault("contents", "")  # not MuPDF's "Image Stamp"
        elif kind == "redact":
            for r in o["rects"]:
                a = pg.add_redact_annot(self._in(pg, r), fill=(0, 0, 0), cross_out=True)
                a.set_info(title=author(), subject="Redact")
                a.update()
            return self._answer([int(page)], result={"id": a.xref})
        else:
            raise ValueError(f"Unknown kind of comment: {kind}")
        self._finish(pg, a, o)
        if kind in ("rect", "ellipse", "cloud"):
            self._place(a, r)
        if kind == "text":
            self._grow_text(pg, a, fit=bool(o.get("fit")))
        if o.get("replyTo"):
            a.set_irt_xref(int(o["replyTo"]))
        return self._answer([int(page)], result=self._annot_info(pg, a))

    def op_annot_reply(self, page, id, contents):
        """A reply to a comment: a note of its own, hidden, pointing at the comment it answers."""
        self._snapshot()
        pg = self._page(page)
        parent = self._find_annot(pg, id)
        a = pg.add_text_annot(parent.rect.tl, contents, icon="Comment")
        a.set_irt_xref(parent.xref)
        a.set_flags(a.flags | 2)  # hidden: only the comments list shows a reply
        a.set_info(title=author(), content=contents, subject="Reply")
        a.update()
        return self._answer([], result=self._annot_info(pg, a))

    def op_annot_set(self, page, id, **o):
        """Change a comment: its place and size ("rect", as shown), colors, width, opacity, words."""
        import pymupdf
        self._snapshot()
        pg = self._page(page)
        a = self._find_annot(pg, id)
        kind = KINDS.get(a.type[1], "")
        boxed = kind in ("rect", "ellipse")  # its outside kept where it is (or put where asked) as its border changes
        target = a.rect
        if "points" in o and kind == "line":  # a line's two ends, as shown
            a = self._remake(pg, a, a.rect, a.rect, pts=[tuple(self._pt(pg, q)) for q in o["points"][:2]])
        if "rect" in o:
            new = self._in(pg, o["rect"])
            old = a.rect
            if kind in ("ink", "line", "polygon", "polyline") or a.type[1] in ("Highlight", "Underline", "StrikeOut", "Squiggly"):
                a = self._remake(pg, a, old, new)
            elif boxed:
                target = new
            else:
                a.set_rect(new)
        if "color" in o or "fill" in o:
            c = a.colors or {}
            stroke = _color(o["color"]) if "color" in o else c.get("stroke")
            fill = _color(o["fill"]) if "fill" in o else c.get("fill")
            if kind == "text":  # a text box: its background (the words' color is textColor)
                a.update(fill_color=fill)
            elif a.type[1] in ("Highlight", "Underline", "StrikeOut", "Squiggly", "Text", "Ink", "Line", "PolyLine"):
                a.set_colors(stroke=stroke)
            else:
                a.set_colors(stroke=stroke, fill=fill)
        if "width" in o:
            b = a.border or {}
            a.set_border(width=float(o["width"]), clouds=b.get("clouds", -1))
        if "clouds" in o:
            a.set_border(width=(a.border or {}).get("width", 1.5), clouds=1 if o["clouds"] else 0)
        if "opacity" in o:
            a.set_opacity(float(o["opacity"]))
        if "contents" in o or "text" in o:
            words = o.get("text", o.get("contents"))
            a.set_info(content=words)
        if "arrow" in o and kind == "line":
            end = pymupdf.PDF_ANNOT_LE_OPEN_ARROW if o["arrow"] else pymupdf.PDF_ANNOT_LE_NONE
            a.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, end)
        upd = {}
        if kind == "text":
            if "fontsize" in o:
                upd["fontsize"] = float(o["fontsize"])
            if "textColor" in o:
                upd["text_color"] = _color(o["textColor"])
        a.set_info(modDate=_now())
        a.update(**upd)
        if boxed:
            self._place(a, target)
        if kind == "text" and ({"text", "contents", "fontsize", "rect"} & set(o)):
            self._grow_text(pg, a)
        return self._answer([int(page)], result=self._annot_info(pg, a))

    def _grow_text(self, pg, a, fit=False):
        """A text box made tall enough for its words (never shorter: only grown), so typing more never hides any.
        With `fit`, sized to the words exactly (text typed straight onto the page has no box to keep)."""
        import pymupdf
        size = self._freetext_size(a)
        x, y, w, h = self._out(pg, a.rect)
        words = (a.info.get("content") or "").split("\n")
        longest = max((pymupdf.get_text_length(ln, "helv", size) for ln in words), default=0)
        if fit:
            w = longest + 6
        rows = sum(max(1, math.ceil(pymupdf.get_text_length(ln, "helv", size) / max(w - 5, 1))) for ln in words)
        need = rows * size * 1.22 + 5
        if fit or need > h + 0.5:
            a.set_rect(self._in(pg, [x, y, w, need if fit else max(h, need)]))
            a.update()

    @staticmethod
    def _place(a, want):
        """Put a box-shaped annotation exactly on `want` (page points), border and all. MuPDF takes the rectangle it's
        given as the inside of the border and adds the border's /RD around it, so that's taken off first (setting
        a.rect back as it reads would grow the box by its border each time it's moved)."""
        import pymupdf
        want = pymupdf.Rect(want)
        a.update()  # the border's /RD for its width now
        doc = a.get_parent().parent
        kind, val = doc.xref_get_key(a.xref, "RD")
        rd = [float(v) for v in val.strip("[]").split()] if kind == "array" else [0, 0, 0, 0]
        inner = pymupdf.Rect(want.x0 + rd[0], want.y0 + rd[3], want.x1 - rd[2], want.y1 - rd[1])
        if inner.width < 1 or inner.height < 1:
            inner = pymupdf.Rect(want)
        a.set_rect(inner)

    def _remake(self, pg, a, old, new, pts=None, keep=False):
        """An annotation drawn from points, moved and stretched from `old` to `new` (page points): made again, on
        `pg` (a line with its ends at `pts`). With `keep` the first one stays: a copy."""
        sx = new.width / old.width if old.width else 1
        sy = new.height / old.height if old.height else 1

        def move(p):
            return ((p[0] - old.x0) * sx + new.x0, (p[1] - old.y0) * sy + new.y0)
        t = a.type[1]
        colors, border, info, opacity, ends = a.colors or {}, a.border or {}, a.info, a.opacity, a.line_ends
        irt = a.irt_xref
        v = a.vertices or []
        if t == "Ink":
            b = pg.add_ink_annot([[move(p) for p in s] for s in v])
        elif t == "Line":
            b = pg.add_line_annot(*(pts or (move(v[0]), move(v[1]))))
            if ends:
                b.set_line_ends(*ends)
        elif t in ("Polygon", "PolyLine"):
            b = (pg.add_polygon_annot if t == "Polygon" else pg.add_polyline_annot)([move(p) for p in v])
        else:  # text markups: their quads
            pts = [move(p) for p in v]
            import pymupdf
            quads = [pymupdf.Quad(pts[i:i + 4]) for i in range(0, len(pts) - 3, 4)]
            add = {"Highlight": pg.add_highlight_annot, "Underline": pg.add_underline_annot,
                   "StrikeOut": pg.add_strikeout_annot, "Squiggly": pg.add_squiggly_annot}[t]
            b = add(quads=quads)
        b.set_colors(stroke=colors.get("stroke"), fill=colors.get("fill"))
        if border.get("width", -1) >= 0:
            b.set_border(width=border["width"], clouds=border.get("clouds", -1))
        b.set_info(info)
        if opacity is not None and opacity >= 0:
            b.set_opacity(opacity)
        b.update()
        if keep:
            return b
        if irt:
            b.set_irt_xref(irt)
        # replies that pointed at the old one now point at the new one
        for r in pg.annots():
            if r.irt_xref == a.xref:
                r.set_irt_xref(b.xref)
        pg.delete_annot(a)
        return b

    def op_annot_clone(self, page, id, to=None, dx=12, dy=12):
        """A copy of a comment, on page `to` (or its own), shifted (dx, dy) as shown: for paste and duplicate."""
        import pymupdf
        src = self._page(page)
        a = self._find_annot(src, id)
        t = a.type[1]
        if t not in ("Ink", "Line", "Polygon", "PolyLine", "Highlight", "Underline", "StrikeOut", "Squiggly", "Square",
                     "Circle", "FreeText", "Text"):
            raise ValueError("That kind of comment can't be copied: place a new one instead.")
        self._snapshot()
        to = int(page if to is None else to)
        pg = self._page(to)
        d = self._pt(pg, [dx, dy]) - self._pt(pg, [0, 0])
        old = pymupdf.Rect(a.rect)
        new = old + (d.x, d.y, d.x, d.y)
        new += (min(0, pg.rect.width - new.x1) if pg.rotation == 0 else 0, 0) * 2  # (kept on an unturned page)
        colors, border, info, opacity = a.colors or {}, a.border or {}, dict(a.info), a.opacity
        if t in ("Square", "Circle"):
            b = (pg.add_circle_annot if t == "Circle" else pg.add_rect_annot)(new)
            b.set_colors(stroke=colors.get("stroke"), fill=colors.get("fill"))
            b.set_border(width=max(border.get("width", 1), 0), clouds=border.get("clouds", -1))
        elif t == "FreeText":
            b = pg.add_freetext_annot(new, info.get("content", ""), fontsize=self._freetext_size(a), fontname="Helv",
                                      text_color=_color(self._freetext_color(a)), fill_color=colors.get("fill"),
                                      rotate=pg.rotation)
        elif t == "Text":
            b = pg.add_text_annot(new.tl, info.get("content", ""), icon="Comment")
            b.set_colors(stroke=colors.get("stroke"))
        else:
            b = self._remake(pg, a, old, new, keep=True)
        info.pop("id", None)
        b.set_info(content=info.get("content", ""), title=author(), subject=info.get("subject", ""))
        if opacity is not None and 0 <= opacity < 1:
            b.set_opacity(opacity)
        b.update()
        if t in ("Square", "Circle"):
            self._place(b, new)
        return self._answer([to], result={"page": to, **self._annot_info(pg, b)})

    def op_annot_image(self, page, id):
        """A picture of one comment as it's drawn (a PNG data URL), to carry along while it's dragged; None where
        the page is turned (the picture would be too)."""
        import pymupdf
        pg = self._page(page)
        a = self._find_annot(pg, id)
        r = a.rect
        if pg.rotation or r.is_empty:
            return None
        k = min(3.0, 1400 / max(r.width, r.height, 1))
        pix = a.get_pixmap(matrix=pymupdf.Matrix(k, k), alpha=True)
        return "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode()

    def op_annot_delete(self, page, ids):
        self._snapshot()
        pg = self._page(page)
        ids = {int(i) for i in (ids if isinstance(ids, list) else [ids])}
        doomed = {a.xref for a in pg.annots() if a.xref in ids or (a.irt_xref and a.irt_xref in ids)}  # replies go too
        for xref in doomed:
            # found again each time: MuPDF deletes a comment's replies and popup along with it
            a = next((x for x in pg.annots() if x.xref == xref), None)
            if a is not None:
                pg.delete_annot(a)
        return self._answer([int(page)])

    def op_state(self):
        return self.state()

    def op_stamps(self):
        return STAMPS

    # ================================================================== pages
    def _pages_list(self, pages):
        n = self.fz.page_count
        out = sorted({int(p) for p in pages if 0 <= int(p) < n})
        if not out:
            raise ValueError("Pick some pages first.")
        return out

    def op_pages_rotate(self, pages, by=90):
        self._snapshot()
        for i in self._pages_list(pages):
            pg = self.fz[i]
            pg.set_rotation((pg.rotation + int(by)) % 360)
        return self._answer(None, structure=True)

    def op_pages_delete(self, pages):
        pages = self._pages_list(pages)
        if len(pages) >= self.fz.page_count:
            raise ValueError("A PDF needs at least one page: those are all of them.")
        self._snapshot()
        self.fz.delete_pages(pages)
        return self._answer(None, structure=True)

    def op_pages_order(self, order):
        """Put the pages in this order (a list of the current page numbers, each once)."""
        order = [int(i) for i in order]
        if sorted(order) != list(range(self.fz.page_count)):
            raise ValueError("That order doesn't name every page once.")
        if order == list(range(self.fz.page_count)):
            return self._answer([])
        self._snapshot()
        self._select(order)
        return self._answer(None, structure=True)

    def op_pages_move(self, pages, to):
        """Move the pages to before page `to` (in the current numbering; the page count puts them last)."""
        pages = self._pages_list(pages)
        rest = [i for i in range(self.fz.page_count) if i not in pages]
        at = sum(1 for i in rest if i < int(to))
        return self.op_pages_order(rest[:at] + pages + rest[at:])

    def op_pages_duplicate(self, pages):
        """A copy of each page right after it: a page of its own, its comments its own (a page put in twice by
        select() would be one page shown twice, and a comment changed on either changed on both)."""
        pages = self._pages_list(pages)
        self._snapshot()
        for i in sorted(set(pages), reverse=True):
            self.fz.fullcopy_page(i, i + 1 if i + 1 < self.fz.page_count else -1)  # (-1: after the last)
        self._balloon_tidy()  # (the copies' balloons aren't in the list: they go)
        return self._answer(None, structure=True)

    def op_pages_blank(self, at, w=None, h=None):
        """A blank page before page `at`, the size of the page it follows (or Letter)."""
        at = max(0, min(int(at), self.fz.page_count))
        ref = self.fz[min(at, self.fz.page_count - 1)].rect
        self._snapshot()
        self.fz.new_page(at, width=float(w or ref.width or 612), height=float(h or ref.height or 792))
        return self._answer(None, structure=True)

    def _open_other(self, path, password=None):
        """Another file as a PDF to take pages from: a PDF, or a picture made into a page."""
        import pymupdf
        try:
            src = pymupdf.open(path)
        except Exception as e:
            raise ValueError(f"{Path(path).name} can't be read: {e}") from None
        if src.needs_pass and not (password and src.authenticate(password)):
            raise ValueError(f"{Path(path).name} needs its password: open it on its own first.")
        if not src.is_pdf:
            data = src.convert_to_pdf()
            src.close()
            src = pymupdf.open(stream=data, filetype="pdf")
        return src

    def op_pages_insert_file(self, at, paths):
        """Every page of other files (PDFs or pictures) before page `at`: merging, as Acrobat's Combine Files."""
        at = max(0, min(int(at), self.fz.page_count))
        paths = paths if isinstance(paths, list) else [paths]
        srcs = [self._open_other(p) for p in paths]
        self._snapshot()
        added = 0
        for src in srcs:
            self.fz.insert_pdf(src, start_at=at + added)
            added += src.page_count
            src.close()
        self._balloon_tidy(range(at, at + added))  # (another print's balloons aren't this one's)
        return self._answer(None, structure=True, result={"added": added})

    def op_pages_replace(self, pages, path):
        """Swap pages for those of another file, one for one from its first."""
        pages = self._pages_list(pages)
        src = self._open_other(path)
        n = min(len(pages), src.page_count)
        self._snapshot()
        for k in range(n):
            i = pages[k]
            self.fz.insert_pdf(src, from_page=k, to_page=k, start_at=i)
            self.fz.delete_page(i + 1)
        src.close()
        self._balloon_tidy(pages[:n])
        return self._answer(None, structure=True, result={"replaced": n})

    def _write_pages(self, pages, path):
        import pymupdf
        out = pymupdf.open()
        for i in pages:
            out.insert_pdf(self.fz, from_page=i, to_page=i)
        self._save_doc(out, path, encrypt=False)
        out.close()

    def op_pages_extract(self, pages, path, delete=False):
        """The pages into a new PDF at `path` (and out of this one, with `delete`)."""
        pages = self._pages_list(pages)
        self._write_pages(pages, path)
        if delete:
            return self.op_pages_delete(pages) | {"result": {"path": str(path)}}
        return self._answer([], result={"path": str(path)})

    def op_split(self, every=None, ranges=None, folder=None, stem=None):
        """Split into several PDFs next to this one (or in `folder`): every n pages, or the ranges [[first, last], ...]
        (1-based). Their paths."""
        n = self.fz.page_count
        if ranges:
            groups = [list(range(max(1, a) - 1, min(n, b))) for a, b in ranges]
        else:
            k = max(1, int(every or 1))
            groups = [list(range(i, min(n, i + k))) for i in range(0, n, k)]
        groups = [g for g in groups if g]
        if len(groups) < 1:
            raise ValueError("Those ranges hold no pages.")
        folder = Path(folder or Path(self.path).parent)
        stem = stem or Path(self.path).stem
        paths = []
        for g in groups:
            name = f"{stem} (page {g[0] + 1}).pdf" if len(g) == 1 else f"{stem} (pages {g[0] + 1}-{g[-1] + 1}).pdf"
            p = folder / name
            self._write_pages(g, p)
            paths.append(str(p))
        return {"paths": paths}

    def op_pages_crop(self, pages, rect):
        """Crop the pages to `rect` (as shown on the first of them); crop boxes are the page's visible part."""
        import pymupdf
        pages = self._pages_list(pages)
        self._snapshot()
        first = self.fz[pages[0]]
        want = self._in(first, rect)
        for i in pages:
            pg = self.fz[i]
            box = pymupdf.Rect(want) + (pg.cropbox.x0, pg.cropbox.y0, pg.cropbox.x0, pg.cropbox.y0)
            box &= pg.mediabox
            if box.is_empty or box.width < 9 or box.height < 9:
                raise ValueError("That crop leaves too little of the page.")
            pg.set_cropbox(box)
        return self._answer(None, structure=True)

    def op_pages_uncrop(self, pages):
        self._snapshot()
        for i in self._pages_list(pages):
            pg = self.fz[i]
            pg.set_cropbox(pg.mediabox)
        return self._answer(None, structure=True)

    # ================================================================== forms
    def op_fields(self, page=None):
        """Form fields to fill in: on one page, or every page. [{"page", "id", "name", "kind", "rect", "value", ...}]"""
        if page is None:
            return [f for i in range(self.fz.page_count) for f in self.op_fields(i)]
        pg = self._page(page)
        out = []
        for w in pg.widgets() or []:
            kind = {2: "checkbox", 5: "radio", 7: "text", 3: "combo", 4: "list", 6: "signature",
                    1: "button"}.get(w.field_type, "other")
            ff = w.field_flags or 0
            out.append({"page": int(page), "id": w.xref, "name": w.field_name, "label": w.field_label or w.field_name, "kind": kind,
                        "rect": self._out(pg, w.rect), "value": w.field_value, "options": w.choice_values or [],
                        "readonly": bool(ff & 1), "required": bool(ff & 2), "multiline": bool(ff & 4096),
                        "on": w.on_state() if kind in ("checkbox", "radio") else None,
                        "maxlen": w.text_maxlen or 0, "fontsize": w.text_fontsize or 0})
        return out

    def op_field_set(self, page, id, value):
        self._snapshot()
        pg = self._page(page)
        for w in pg.widgets() or []:
            if w.xref != int(id):
                continue
            if w.field_flags & 1:
                raise ValueError("That field can't be changed: it's read-only.")
            if w.field_type in (2, 5):  # a check box or radio button: on or off
                w.field_value = w.on_state() if value in (True, "true", "on", 1) or value == w.on_state() else "Off"
            else:
                w.field_value = str(value)
            w.update()
            # every page may show the same field (and a radio group's other buttons change)
            return self._answer(None, result={"value": w.field_value})
        raise ValueError("That field isn't there any more.")

    # ------------------------------------------------------------------ making a form: fields added, changed, removed
    def _field_names(self):
        return {w.field_name for pg in self.fz for w in (pg.widgets() or []) if w.field_name}

    @staticmethod
    def _unique(name, used):
        """A field name nothing else has (two fields with one name share what's typed into them)."""
        name = (name or "").strip() or "Field"
        if name not in used:
            used.add(name)
            return name
        n = 2
        while f"{name} {n}" in used:
            n += 1
        used.add(f"{name} {n}")
        return f"{name} {n}"

    def _add_field(self, pg, kind, rect, name, used, multiline=False, border=False, options=None, fontsize=None, label=None):
        """A new field on a page (rect: the page's own points). On a blank the page already draws, the field has
        no border of its own; on bare paper it gets one, so it can be seen on a printed copy."""
        import pymupdf
        w = pymupdf.Widget()
        default = {"checkbox": "Check box", "combo": "Choice"}.get(kind, "Text")
        w.field_name = self._unique(name or default, used)
        if label:
            w.field_label = label
        w.rect = pymupdf.Rect(rect)
        if border:
            w.border_color, w.border_width = (0.35, 0.35, 0.35), 0.75
            if kind == "checkbox":
                w.fill_color = (1, 1, 1)
        if kind == "checkbox":
            w.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
            w.field_value = False
        elif kind == "combo":
            w.field_type = pymupdf.PDF_WIDGET_TYPE_COMBOBOX
            w.choice_values = [str(o) for o in (options or ["Option 1", "Option 2"])]
            w.text_fontsize = float(fontsize or 0)
        else:
            w.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
            w.field_value = ""
            if multiline:
                w.field_flags = pymupdf.PDF_TX_FIELD_IS_MULTILINE
            # 0 is "fit the words to the field": right for one line, too big for a box of several
            w.text_fontsize = float(fontsize if fontsize is not None else (10 if multiline else 0))
        return pg.add_widget(w)

    def op_form_auto(self, pages=None):
        """Make the document fillable: find the blanks on these pages (every page when None) and put a field on
        each: kernel/pdfform.py. Blanks that already have a field are left. One step to undo."""
        import pymupdf
        from . import pdfform
        todo = range(self.fz.page_count) if pages is None else self._pages_list(pages)
        found = []
        for i in todo:
            pg = self.fz[i]
            have = [pymupdf.Rect(w.rect) * pg.rotation_matrix for w in (pg.widgets() or [])]
            for f in pdfform.detect(pg):
                r = pymupdf.Rect(f["rect"])
                if any((r & h).get_area() > 0.3 * min(r.get_area(), abs(h.get_area())) for h in have if r.intersects(h)):
                    continue
                found.append((i, f, r))
        if not found:
            return self._answer([], result={"count": 0, "pages": 0})
        self._snapshot()
        used = self._field_names()
        for i, f, r in found:
            pg = self.fz[i]
            q = r * pg.derotation_matrix
            q.normalize()
            self._add_field(pg, f["kind"], q, f["name"], used, multiline=f["multiline"])
        return self._answer(sorted({i for i, _, _ in found}),
                            result={"count": len(found), "pages": len({i for i, _, _ in found})})

    def op_field_add(self, page, kind, rect, name=None, multiline=False, options=None):
        if kind not in ("text", "checkbox", "combo"):
            raise ValueError("That kind of field can't be added.")
        self._snapshot()
        pg = self._page(page)
        q = self._in(pg, rect)
        q.normalize()
        w = self._add_field(pg, kind, q, name, self._field_names(), multiline=bool(multiline), border=True, options=options)
        return self._answer([int(page)], result={"id": w.xref})

    def op_field_edit(self, page, id, **o):
        """Change a field itself (not what's filled in): name, label (its tip), rect, required, readonly,
        multiline, options, fontsize, maxlen."""
        pg = self._page(page)
        for w in pg.widgets() or []:
            if w.xref != int(id):
                continue
            self._snapshot()
            if o.get("name") and o["name"].strip() != w.field_name:
                w.field_name = self._unique(o["name"], self._field_names())
            if "label" in o:
                w.field_label = (o["label"] or "").strip() or None
            if o.get("rect"):
                q = self._in(pg, o["rect"])
                q.normalize()
                w.rect = q
            flags = w.field_flags or 0
            for key, bit in (("readonly", 1), ("required", 2), ("multiline", 4096)):
                if key in o and (key != "multiline" or w.field_type == 7):
                    flags = flags | bit if o[key] else flags & ~bit
            w.field_flags = flags
            if "options" in o and w.field_type in (3, 4):
                w.choice_values = [str(x) for x in o["options"] if str(x).strip()] or ["Option 1"]
            if "fontsize" in o and w.field_type != 2:
                w.text_fontsize = float(o["fontsize"] or 0)
            if "maxlen" in o and w.field_type == 7:
                w.text_maxlen = int(o["maxlen"] or 0)
            w.update()
            return self._answer([int(page)])
        raise ValueError("That field isn't there any more.")

    def op_field_delete(self, page=None, ids=None):
        """Take fields out: these on a page, or every field in the document (page None)."""
        self._snapshot()
        changed = set()
        for i in (range(self.fz.page_count) if page is None else [int(page)]):
            pg = self._page(i)
            want = None if page is None or ids is None else {int(x) for x in ids}
            for w in list(pg.widgets() or []):
                if want is None or w.xref in want:
                    pg.delete_widget(w)
                    changed.add(i)
        return self._answer(sorted(changed))

    def op_flatten(self, annots=True, fields=True):
        """Make comments and filled-in fields part of the pages, so nobody can change them. Balloons stay balloons:
        made part of the pages they'd be read as the print's own text, and drawn again over themselves."""
        self._snapshot()
        keep = self._insp() if annots else None
        if keep and (keep["chars"] or keep["views"]):
            self._balloon_strip()
        self.fz.bake(annots=bool(annots), widgets=bool(fields))
        if keep and (keep["chars"] or keep["views"]):
            self._balloon_sync(keep, range(self.fz.page_count))
        return self._answer(None, text=True)

    # ================================================================== the pages' own text and pictures
    def op_text_at(self, page, at):
        """The line of text under a point: its words, place, font, size and color, to edit."""
        import pymupdf
        pg = self._page(page)
        p = self._pt(pg, at)
        best = None
        for b in pg.get_text("dict", flags=0)["blocks"]:
            for line in b.get("lines", []):
                r = pymupdf.Rect(line["bbox"])
                if not r.contains(p) and best is not None:
                    continue
                d = 0 if r.contains(p) else min(abs(p.y - r.y0), abs(p.y - r.y1)) + max(r.x0 - p.x, 0, p.x - r.x1)
                if d < 6 and (best is None or d < best[0]):
                    best = (d, line)
        if best is None:
            return None
        line = best[1]
        spans = [s for s in line["spans"] if s["text"].strip()] or line["spans"]
        s = max(spans, key=lambda s: len(s["text"]))
        font = s["font"]
        flags = s["flags"]
        bold = bool(flags & 16) or "bold" in font.lower() or "black" in font.lower()
        italic = bool(flags & 2) or "italic" in font.lower() or "oblique" in font.lower()
        serif = bool(flags & 4) and "sans" not in font.lower()
        mono = bool(flags & 8)
        return {"rect": self._out(pg, line["bbox"]), "text": "".join(x["text"] for x in line["spans"]),
                "font": font.split("+", 1)[-1], "size": round(s["size"], 2), "color": f"#{s['color']:06x}",
                "bold": bold, "italic": italic, "serif": serif, "mono": mono,
                "origin": self._pt_out(pg, line["spans"][0]["origin"]), "dir": list(line["dir"])}

    def _fontname(self, o):
        if o.get("mono"):
            return MONO[(bool(o.get("bold")), bool(o.get("italic")))]
        return BASE14[(bool(o.get("serif")), bool(o.get("bold")), bool(o.get("italic")))]

    def _write_text(self, pg, origin, text, o, angle):
        """Words into the page itself, the first line's baseline starting at `origin` (page points)."""
        import pymupdf
        size = float(o.get("size", 11))
        fontname = self._fontname(o)
        color = _color(o.get("color"), (0, 0, 0))
        lines = str(text).split("\n")
        # insert_text turns by multiples of 90 degrees, counter-clockwise: lines run along `angle`
        rotate = int(round(angle / 90.0)) * 90 % 360
        pg.insert_text(pymupdf.Point(origin), lines, fontsize=size, fontname=fontname, color=color, rotate=rotate,
                       lineheight=1.2)

    def op_text_replace(self, page, rect, text, **o):
        """Change a line of the page's own text: the old words are taken out of the page (as a redaction does, so
        they're really gone), and the new ones set in their place in the nearest standard font."""
        import pymupdf
        self._snapshot()
        pg = self._page(page)
        r = self._in(pg, rect)
        old = self._lines_in(pg, r)
        origin = pymupdf.Point(old["origin"]) if old else pymupdf.Point(r.x0, r.y1 - (r.height * 0.2))
        dirv = old["dir"] if old else (1, 0)
        # an unturned page's text runs along dir; insert_text measures its turn counter-clockwise, with y down
        angle = math.degrees(math.atan2(-dirv[1], dirv[0]))
        # only the words: a box a little inside the line's, so the lines above and below stay
        inner = pymupdf.Rect(r)
        if abs(dirv[0]) >= abs(dirv[1]):
            inner.y0 += r.height * 0.25
            inner.y1 -= r.height * 0.25
        else:
            inner.x0 += r.width * 0.25
            inner.x1 -= r.width * 0.25
        pg.add_redact_annot(inner)
        pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                            text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        if str(text).strip():
            self._write_text(pg, origin, text, o, angle)
        return self._answer([int(page)], text=True)

    def _lines_in(self, pg, r):
        import pymupdf
        for b in pg.get_text("dict", flags=0)["blocks"]:
            for line in b.get("lines", []):
                if pymupdf.Rect(line["bbox"]).intersects(r) and line["spans"]:
                    return {"origin": line["spans"][0]["origin"], "dir": line["dir"]}
        return None

    def op_text_add(self, page, at, text, **o):
        """New words in the page itself (not a comment), reading across the page as shown, from `at`'s baseline."""
        self._snapshot()
        pg = self._page(page)
        # reading across the page as shown: against the page's own turn
        self._write_text(pg, self._pt(pg, at), text, o, pg.rotation)
        return self._answer([int(page)], text=True)

    def op_words(self, page):
        """Where a page's words are, as shown: [[x, y, w, h], ...] (for the Select tool's I-beam and text drag)."""
        pg = self._page(page)
        return [self._out(pg, w[:4]) for w in pg.get_text("words")]

    def op_images(self, page):
        """The pictures on a page: [{"id": xref, "rect"}]. Inline pictures (no xref) can't be edited."""
        pg = self._page(page)
        out = []
        for info in pg.get_image_info(xrefs=True):
            if not info.get("xref") or (info["width"] <= 1 and info["height"] <= 1):
                continue  # inline, or one taken out (MuPDF leaves an empty dot in its place)
            out.append({"id": info["xref"], "rect": self._out(pg, info["bbox"]), "w": info["width"], "h": info["height"]})
        return out

    def _image_pixmap(self, xref):
        import pymupdf
        pix = pymupdf.Pixmap(self.fz, xref)
        smask = self.fz.xref_get_key(xref, "SMask")
        if smask[0] == "xref":
            try:
                mask = pymupdf.Pixmap(self.fz, int(smask[1].split()[0]))
                pix = pymupdf.Pixmap(pix, mask)
            except Exception:
                pass
        if pix.colorspace and pix.colorspace.n not in (1, 3):
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        return pix

    def op_image_set(self, page, id, rect=None, image=None):
        """Move or resize a picture on the page (`rect` as shown), or swap it for another (`image`: a data URL)."""
        import pymupdf
        pg = self._page(page)
        xref = int(id)
        now = [i for i in pg.get_image_info(xrefs=True) if i.get("xref") == xref]
        if not now:
            raise ValueError("That picture isn't there any more.")
        self._snapshot()
        target = self._in(pg, rect) if rect else pymupdf.Rect(now[0]["bbox"])
        pix = None if image else self._image_pixmap(xref)
        pg.delete_image(xref)
        if image:
            pg.insert_image(target, stream=base64.b64decode(image.split(",", 1)[-1]), keep_proportion=False,
                            rotate=pg.rotation and (360 - pg.rotation) % 360)
        else:
            pg.insert_image(target, pixmap=pix, keep_proportion=False,
                            rotate=pg.rotation and (360 - pg.rotation) % 360)
        return self._answer([int(page)], text=True)

    def op_image_delete(self, page, id):
        self._snapshot()
        pg = self._page(page)
        pg.delete_image(int(id))
        return self._answer([int(page)], text=True)

    def op_image_add(self, page, rect, image):
        self._snapshot()
        pg = self._page(page)
        pg.insert_image(self._in(pg, rect), stream=base64.b64decode(image.split(",", 1)[-1]),
                        rotate=pg.rotation and (360 - pg.rotation) % 360)
        return self._answer([int(page)], text=True)

    # ================================================================== redacting
    def op_redact_apply(self, fill="black"):
        """Take everything under the redaction marks out of the pages for good: words, the parts of pictures,
        and drawing they cover, and form fields the marks touch (with what's filled into them). The marks become
        black boxes, or white ones (fill "white": blank paper, for a print that shouldn't show what was hidden).
        Strike-through marks become lines drawn into the page, the words under them left as they are."""
        import pymupdf
        strikes = [i for i in range(self.fz.page_count) if any(_is_strike(a) for a in self.fz[i].annots())]
        pages = [i for i in range(self.fz.page_count) if any(a.type[1] == "Redact" for a in self.fz[i].annots())]
        if not pages and not strikes:
            raise ValueError("Mark something to redact or strike through first.")
        self._snapshot()
        for i in strikes:
            pg = self.fz[i]
            marks = [a for a in pg.annots() if _is_strike(a)]
            lines = []
            for a in marks:
                v = [pymupdf.Point(p) for p in (a.vertices or [])]
                stroke = (a.colors or {}).get("stroke") or (0, 0, 0)
                for k in range(0, len(v) - 3, 4):  # each quad: upper left, upper right, lower left, lower right
                    ul, ur, ll, lr = v[k:k + 4]
                    lines.append(((ul + ll) / 2, (ur + lr) / 2, max(0.5, abs(ll - ul) * 0.07), stroke))
            for a in marks:
                pg.delete_annot(a)
            for a, b, width, stroke in lines:
                pg.draw_line(a, b, color=stroke, width=width, lineCap=0)
        color = (1, 1, 1) if fill == "white" else (0, 0, 0)
        for i in pages:
            pg = self.fz[i]
            marks = [pymupdf.Rect(a.rect) for a in pg.annots() if a.type[1] == "Redact"]
            for a in [a for a in pg.annots() if a.type[1] == "Redact"]:
                pg.delete_annot(a)
            for r in marks:
                pg.add_redact_annot(r, fill=color, cross_out=False)
            for w in list(pg.widgets() or []):  # a field isn't part of the page: it goes whole
                if any((pymupdf.Rect(w.rect) & r).get_area() > 0.5 for r in marks if r.intersects(w.rect)):
                    pg.delete_widget(w)
            self.fz[i].apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                                        graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                                        text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        return self._answer(None, text=True, result={"pages": len(set(pages) | set(strikes)), "struck": len(strikes)})

    def op_scrub(self):
        """Remove hidden information: the document's details, attached files, scripts, hidden text and comments."""
        self._snapshot()
        self.fz.scrub(metadata=True, xml_metadata=True, attached_files=True, embedded_files=True, javascript=True,
                      hidden_text=True, redactions=True, remove_links=False, reset_fields=False, reset_responses=True,
                      thumbnails=True, clean_pages=True)
        return self._answer(None, text=True)

    # ================================================================== saving
    def _save_doc(self, doc, path, encrypt=True):
        """Write `doc` to `path` safely: to a file beside it first, then swapped in, so a failure leaves the old one."""
        import pymupdf
        path = Path(path)
        fd, tmp = tempfile.mkstemp(prefix=".~", suffix=".pdf", dir=str(path.parent))
        os.close(fd)
        try:
            doc.save(tmp, garbage=1, deflate=True,
                     encryption=pymupdf.PDF_ENCRYPT_KEEP if encrypt else pymupdf.PDF_ENCRYPT_NONE)
            os.replace(tmp, path)
        except PermissionError:
            raise ValueError(f"{path.name} can't be written: it's open in another program, or the folder is read-only.") from None
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def op_save(self, path=None):
        """Save the edits: to the file it came from, or (Save As) to `path`, which it then is."""
        target = Path(path or self.path)
        self._save_doc(self.fz, target)
        self.path = str(target)
        self.saved_gen = self.gen
        data = self._insp()
        if data["chars"] or data.get("issues"):  # (searched across jobs: kernel/inspindex.py)
            from . import inspindex
            inspindex.record(self.path, data)
        return self._answer([], result={"path": self.path})
