"""The inspection sheet as a PDF, to print and fill in at the machine: the same page kernel/report.py's "sheet"
layout makes as a workbook, drawn here.

write(path, data, drawing, parts, footer): landscape Letter. The job across the top (part number, revision, part name,
customer, job number), the check boxes and inspection frequency, Time / Date / Initial over the part columns, then a
table of every balloon (its number in red, description, gage, nominal, lower and upper limit) with five blank part
columns; the table again for each further five parts, and on as many pages as it takes. footer: the shop's own
lines, the first at the bottom left, the second at the bottom right.

Set in Calibri and Cambria where the computer has them (Windows does), else in the PDF's own Helvetica and Times.
"""

import os

from . import balloons, report

PAGE = (792.0, 612.0)
# the columns' edges: number, description, gage, nominal, lower, upper, then the parts
X = [50.5, 74.6, 202.8, 327.8, 379.4, 431.0, 482.6] + [482.6 + 51.6 * i for i in range(1, report.PER + 1)]
TOP, BOTTOM, ROW, HEAD = 54.5, 560.0, 14.5, 14.7
BLUE, RED, BLACK, WHITE = (0.553, 0.706, 0.886), (1, 0, 0), (0, 0, 0), (1, 1, 1)
THICK, THIN = 1.9, 0.9
FONTS = {"sans": ("calibri.ttf", "helv"), "bold": ("calibrib.ttf", "hebo"), "bolditalic": ("calibriz.ttf", "hebi"),
         "serif": ("cambria.ttc", "tiro"), "small": ("segoeui.ttf", "helv")}


def _fonts():
    import pymupdf
    folder = os.path.join(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows", "Fonts")
    out = {}
    for key, (file, base) in FONTS.items():
        try:
            out[key] = pymupdf.Font(fontfile=os.path.join(folder, file))
        except Exception:
            out[key] = pymupdf.Font(base)
    return out


def _number(c, key):
    v = c.get(key)
    if v is None:
        return ""
    if c.get("kind") == "angle":
        return balloons.fmt(v, c.get("places") or 0) + "°"
    return f"{v:.{4 if (c.get('places') or 0) >= 4 else 3}f}"


class _Sheet:
    def __init__(self, doc, fonts):
        import pymupdf
        self.mu, self.doc, self.fonts = pymupdf, doc, fonts
        self.page = self.black = self.white = None
        self.pages = []
        self.used = {}  # a font's name: the characters set in it

    def new_page(self):
        self.flush()
        self.page = self.doc.new_page(width=PAGE[0], height=PAGE[1])
        self.black, self.white = self.mu.TextWriter(self.page.rect, color=BLACK), self.mu.TextWriter(self.page.rect, color=WHITE)
        self.pages.append(self.page)
        self.text("Inspection Report", X[-1] + 23, 32.5, "bold", 18, "right")
        return TOP

    def flush(self):
        if self.page is not None:
            self.black.write_text(self.page)
            self.white.write_text(self.page)

    def text(self, s, x, base, font="serif", size=9.0, align="left", width=None, color=BLACK, underline=False):
        """A line of text with its baseline at `base`: from x, ending at x, or about x. width: made smaller to fit it,
        and cut short if it still doesn't."""
        s = str(s if s is not None else "")
        f = self.fonts[font]
        s = "".join(ch if f.has_glyph(ord(ch)) else "?" for ch in s)
        if not s.strip():
            return
        n = f.text_length(s, size)
        if width and n > width:
            size = max(size * width / n, 5.5)
            n = f.text_length(s, size)
            while n > width and len(s) > 2:
                s = s[:-2].rstrip() + "…"
                n = f.text_length(s, size)
        x0 = x - n if align == "right" else x - n / 2 if align == "center" else x
        self.used.setdefault(f.name, (f, set()))[1].update(s)
        (self.white if color == WHITE else self.black).append((x0, base), s, font=f, fontsize=size)
        if underline:
            self.page.draw_line((x0, base + 1.6), (x0 + n, base + 1.6), color=BLACK, width=0.6)

    def line(self, x0, y0, x1, y1, width=THIN):
        self.page.draw_line((x0, y0), (x1, y1), color=BLACK, width=width)

    def box(self, x0, y0, x1, y1, width=THICK, fill=None):
        self.page.draw_rect(self.mu.Rect(x0, y0, x1, y1), color=BLACK if width else None, fill=fill, width=width or 0)

    # ------------------------------------------------------------------ the job, across the top of the first page
    def job(self, y, info, drawing):
        spans = [("Part Number:", "part", X[0], X[2]), ("Revision:", "rev", X[2], X[3]), ("Part Name:", "name", X[3], X[6]),
                 ("Customer:", "customer", X[6], X[9]), ("Job #:", "job", X[9], X[-1])]
        y1, y2, y3 = y + 15.2, y + 45.0, y + 60.3
        for label, key, a, b in spans:
            self.text(label, a + 2.2, y + 12.0, "bolditalic", 12, width=b - a - 4)
            self.text(info.get(key, ""), (a + b) / 2, y1 + 18.5, "serif", 10, "center", b - a - 6)
            if a > X[0]:
                self.line(a, y, a, y2)
        self.line(X[0], y1, X[-1], y1)
        self.line(X[0], y2, X[-1], y2, THICK)
        # which sheet this is, and how often to inspect
        for label, a in (("FINAL Inspection Sheet", X[0]), ("PROD Inspection Sheet", X[2])):
            self.box(a + 10, y2 + 4.2, a + 17, y2 + 11.2, 0.7)
            self.text(label, a + 23, y2 + 10.6, "small", 8)
        self.text("Inspection Frequency:", X[6] - 2, y2 + 10.8, "serif", 9, "right")
        self.text(info.get("frequency", ""), X[6] + 4, y2 + 10.8, "serif", 9, width=X[-1] - X[6] - 8)
        for a in (X[2], X[3], X[6]):
            self.line(a, y2, a, y3)
        self.line(X[0], y3, X[-1], y3, THICK)
        # the drawing it's from, and who filled each part's column in, when
        self.text(f"Drawing: {drawing}", X[0] + 2, y3 + 10.4, "bold", 9, width=X[5] - X[0] - 6)
        yy = y3
        for label, size, h in (("Time   →", 8, 14.5), ("Date   →", 8, 14.7), ("Initial   →", 11, 15.8)):
            self.text(label, X[6] - 1.8, yy + h - 3.6, "sans", size, "right")
            yy += h
            if label.startswith("Initial"):
                break
            self.line(X[6], yy, X[-1], yy)
        for a in X[5:-1]:
            self.line(a, y3, a, yy)
        return yy

    # ------------------------------------------------------------------ a table: its rows and the part columns
    def table(self, y, rows, initial):
        """Draw a table at y; initial: with a row above it for the inspector's initials. Returns where it ends."""
        top = y
        if initial:
            self.text("Initial   →", X[6] - 1.8, y + 11.2, "sans", 11, "right")
            for a in X[7:-1]:
                self.line(a, y, a, y + 15.0)
            y += 15.0
        head = y
        self.box(X[0], y, X[6], y + HEAD, 0, BLUE)
        self.text("DIMENSION DESCRIPTION", (X[0] + X[2]) / 2, y + 10.8, "bolditalic", 9, "center", underline=True)
        self.text("GAGE", (X[2] + X[3]) / 2, y + 10.8, "bolditalic", 9, "center", underline=True)
        for i, label in enumerate(("Nominal", "Lower Limit", "Upper Limit")):
            self.text(label, (X[3 + i] + X[4 + i]) / 2, y + 10.8, "bolditalic", 9, "center", underline=True)
        for i in range(6, len(X) - 1):
            self.text("Part # ____", (X[i] + X[i + 1]) / 2, y + 10.8, "bolditalic", 9, "center")
        for a in X[2:-1]:
            self.line(a, y, a, y + HEAD)
        y += HEAD
        self.line(X[0], y, X[-1], y)
        if rows:
            self.box(X[0], y, X[1], y + ROW * len(rows), 0, RED)
        for c in rows:
            base = y + ROW - 3.9
            self.text(report._n(c), (X[0] + X[1]) / 2, base - 0.4, "sans", 8, "center", X[1] - X[0] - 2, WHITE)
            self.text(report.describe(c), X[1] + 2, base, "serif", 10, width=X[2] - X[1] - 4)
            self.text(c.get("gage") or "", (X[2] + X[3]) / 2, base, "serif", 9, "center", X[3] - X[2] - 4)
            if c.get("lo") is None and c.get("hi") is None:  # nothing to measure against: what the print says
                self.text(c.get("text") or "", (X[3] + X[6]) / 2, base, "serif", 9, "center", X[6] - X[3] - 4)
                rules = X[1:4] + X[6:-1]
            else:
                for i, key in enumerate(("nominal", "lo", "hi")):
                    self.text(_number(c, key), (X[3 + i] + X[4 + i]) / 2, base, "serif", 9, "center", X[4 + i] - X[3 + i] - 3)
                rules = X[1:-1]
            for a in rules:
                self.line(a, y, a, y + ROW)
            y += ROW
            self.line(X[0], y, X[-1], y)
        self.box(X[0], head, X[-1], y)
        if initial:
            self.box(X[6], top, X[-1], head)
        return y


def _readable(doc, used):
    """Say which character each glyph is, for copying and finding text in the PDF. The embedding names a glyph by the
    last character the font draws with it, so a space comes back as a no-break space and a hyphen as a no-break
    hyphen, and "WM-1001" isn't found. used: {font name: (font, characters set in it)}."""
    import re
    for x in range(1, doc.xref_length()):
        if doc.xref_get_key(x, "Subtype")[1] != "/Type0":
            continue
        name = re.sub(r"#([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), doc.xref_get_key(x, "BaseFont")[1].lstrip("/")).split("+")[-1]
        kind, val = doc.xref_get_key(x, "ToUnicode")
        if name not in used or kind != "xref":
            continue
        font, chars = used[name]
        pairs = sorted({(font.has_glyph(ord(ch)), ord(ch)) for ch in chars if ord(ch) < 0x10000 and font.has_glyph(ord(ch))})
        body = ["/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n/CIDSystemInfo <</Registry(Adobe)/Ordering(UCS)/Supplement 0>> def\n"
                "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"]
        for i in range(0, len(pairs), 100):
            part = pairs[i:i + 100]
            body.append(f"{len(part)} beginbfchar\n" + "".join(f"<{g:04x}> <{u:04x}>\n" for g, u in part) + "endbfchar\n")
        body.append("endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n")
        doc.update_stream(int(val.split()[0]), "".join(body).encode("ascii"))


def write(path, data, drawing, parts=report.PER, footer=""):
    """Write the inspection sheet for an inspection list (see the top of this file). Returns how many pages."""
    import pymupdf
    info, chars = data.get("info") or {}, data["chars"]
    tables = -(-min(max(int(parts or 1), 1), report.MAX_PARTS) // report.PER)
    doc = pymupdf.open()
    sh = _Sheet(doc, _fonts())
    y = sh.new_page()
    job_top = y
    y = sh.job(y, info, drawing)
    first = True
    for t in range(tables):
        rows = list(chars)
        while True:
            initial = not first
            over = (15.0 if initial else 0.0) + HEAD
            fit = int((BOTTOM - y - over) // ROW)
            # a table that would fit a page of its own isn't split over two; a longer one leaves at least three rows
            whole = len(rows) <= int((BOTTOM - TOP - 15.0 - HEAD) // ROW)
            if y > TOP and not (first and t == 0) and (fit < min(3, len(rows)) or (whole and fit < len(rows))):
                y, first = sh.new_page(), False
                continue
            part, rows = rows[:max(fit, 1)], rows[max(fit, 1):]
            end = sh.table(y, part, initial)
            if first:  # the job and the first table are one box
                sh.box(X[0], job_top, X[-1], end)
            first = False
            y = end + 14.2
            if not rows:
                break
            y = sh.new_page()
    sh.flush()
    lines = [ln.strip() for ln in str(footer or "").splitlines() if ln.strip()]
    n = doc.page_count
    for i, page in enumerate(doc, 1):
        w = pymupdf.TextWriter(page.rect, color=BLACK)
        f = sh.fonts["sans"]
        sh.used.setdefault(f.name, (f, set()))[1].update("".join(lines) + f"Page {i} of {n}")
        for k, ln in enumerate(lines[:1] + lines[2:]):
            w.append((33.4, 590.0 - 10.5 * k), ln, font=f, fontsize=9)
        if len(lines) > 1:
            w.append((760.0 - f.text_length(lines[1], 9), 591.0), lines[1], font=f, fontsize=9)
        if n > 1:
            s = f"Page {i} of {n}"
            w.append((PAGE[0] / 2 - f.text_length(s, 9) / 2, 591.0), s, font=f, fontsize=9)
        if lines or n > 1:
            w.write_text(page)
    try:
        doc.subset_fonts()
    except Exception:
        pass  # (the whole fonts stay in: a bigger file, the same page)
    try:
        _readable(doc, sh.used)
    except Exception:
        pass
    doc.set_metadata({"title": f"Inspection Report {info.get('part', '')}".strip(), "creator": "SolidSmurfs"})
    try:
        doc.save(path, garbage=3, deflate=True)
    finally:
        doc.close()
    return n
