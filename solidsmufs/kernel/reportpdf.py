"""The inspection sheet as a PDF, to print and fill in at the machine: the same page kernel/report.py's "sheet"
layout makes as a workbook, drawn here.

write(path, data, drawing, parts, footer): landscape Letter. The job across the top (part number, revision, part name,
customer, job number), the check boxes and inspection frequency, Time / Date / Initial over the part columns, then a
table of every balloon (its number in red, description, gage, nominal, lower and upper limit) with five blank part
columns; the table again for each further five parts, and on as many pages as it takes. What the parts measured is
written in under each part (a result outside its limits in red), the other part columns left to fill in. footer: the
shop's own lines, the first at the bottom left, the second at the bottom right.
printing ({"header", "issues", "photos", "logo", "pictures", "who"}): a line across the top of every page saying what
it's of (part, revision, sheet id, status: on unless header is False), and along the very bottom when it was printed,
by whom and with what; the shop's logo at the top left (logo: a picture's bytes); the production issues not hidden
(issues: True) on a page of their own; and the photos (photos: "small", three across, "medium", two, or "large", one
to a page; pictures: {photo id: its bytes}) with what's drawn on them, each saying what it's of.

Set in Calibri and Cambria where the computer has them (Windows does), else in the PDF's own Helvetica and Times.
"""

import datetime
import os

from .. import __version__
from . import balloons, report

PAGE = (792.0, 612.0)
# the columns' edges: number, description, gage, nominal, lower, upper, then the parts
X = [50.5, 74.6, 202.8, 327.8, 379.4, 431.0, 482.6] + [482.6 + 51.6 * i for i in range(1, report.PER + 1)]
TOP, BOTTOM, ROW, HEAD = 54.5, 560.0, 14.5, 14.7
BLUE, RED, BLACK, WHITE, FAIL = (0.553, 0.706, 0.886), (1, 0, 0), (0, 0, 0), (1, 1, 1), (0.8, 0, 0)
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
        self.page = self.black = self.white = self.red = None
        self.pages = []
        self.used = {}  # a font's name: the characters set in it

    def new_page(self):
        self.flush()
        self.page = self.doc.new_page(width=PAGE[0], height=PAGE[1])
        self.black, self.white = self.mu.TextWriter(self.page.rect, color=BLACK), self.mu.TextWriter(self.page.rect, color=WHITE)
        self.red = self.mu.TextWriter(self.page.rect, color=FAIL)
        self.pages.append(self.page)
        self.text("Inspection Report", X[-1] + 23, 32.5, "bold", 18, "right")
        return TOP

    def flush(self):
        if self.page is not None:
            for writer in (self.black, self.white, self.red):
                writer.write_text(self.page)

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
        (self.white if color == WHITE else self.red if color == FAIL else self.black).append((x0, base), s, font=f, fontsize=size)
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
        self.text(report.drawing_line(info, drawing), X[0] + 2, y3 + 10.4, "bold", 9, width=X[5] - X[0] - 6)
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
    def table(self, y, rows, initial, data=None, at=0):
        """Draw a table at y; initial: with a row above it for the inspector's initials. data: the list, for what the
        parts measured, this table's first part column being part number `at`. Returns where it ends."""
        data = data or {}
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
            self.text(report._part(data, at + i - 6, "Part # ____"), (X[i] + X[i + 1]) / 2, y + 10.8, "bolditalic", 9, "center", X[i + 1] - X[i] - 3)
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
            for i in range(6, len(X) - 1):  # what each part measured: outside its limits, in red
                value = report._measured(data, c, at + i - 6)[0]
                if value != "":
                    said = ((data.get("results") or {}).get(c.get("key") or str(c.get("id"))) or {}).get(str(data["samples"][at + i - 6]["id"]), "")
                    self.text(said, (X[i] + X[i + 1]) / 2, base, "serif", 9, "center", X[i + 1] - X[i] - 3,
                              FAIL if balloons.judge(c, said) is False else BLACK)
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


STATUS = {"draft": "Draft", "released": "Released", "superseded": "Superseded"}
ISSUE_COLS = [("#", 50.5, 80.0), ("Balloon", 80.0, 125.0), ("Title", 125.0, 300.0), ("Tags", 300.0, 420.0),
              ("Status", 420.0, 545.0), ("Job", 545.0, 595.0), ("Notes", 595.0, 740.6)]


def _issue_status(i):
    if i.get("status") == "resolved":
        return "Resolved: moved to troubleshooting" if i.get("route") == "troubleshooting" else "Resolved: machinist fix"
    return "Fixed, ready for lead" if i.get("status") == "fixed" else "Open"


def _issues(sh, data):
    """The production issues not hidden, on pages of their own."""
    issues = [i for i in data.get("issues") or [] if not i.get("hidden")]
    if not issues:
        return
    labels = {c["id"]: balloons.label(c) for c in data["chars"]}
    y = sh.new_page()
    sh.text("Production Issues", X[0], y + 12, "bold", 14)
    y += 22
    head = y
    sh.box(X[0], y, X[-1], y + HEAD, 0, BLUE)
    for label, a, b in ISSUE_COLS:
        sh.text(label, (a + b) / 2, y + 10.8, "bolditalic", 9, "center", b - a - 4)
    y += HEAD
    for i in issues:
        if y + ROW > BOTTOM:
            sh.box(X[0], head, X[-1], y)
            y = head = sh.new_page()
        cells = [f"#{i['n']}", labels.get(i.get("char"), i.get("label") or ""), i.get("title") or "", ", ".join(i.get("tags") or []),
                 _issue_status(i), i.get("job") or "", (i.get("notes") or "").replace("\n", "  ")]
        for (label, a, b), s in zip(ISSUE_COLS, cells):
            sh.text(s, a + 2, y + ROW - 3.9, "serif", 9, width=b - a - 4)
        for _, a, _b in ISSUE_COLS[1:]:
            sh.line(a, y, a, y + ROW)
        y += ROW
        sh.line(X[0], y, X[-1], y)
    sh.box(X[0], head, X[-1], y)


def _marks(page, rect, p):
    """What's drawn on a photo, drawn over it where it's placed (rect), in the photo's own pixels scaled."""
    import math
    import pymupdf
    k = rect.width / p["w"]
    pt = lambda q: pymupdf.Point(rect.x0 + q[0] * k, rect.y0 + q[1] * k)  # noqa: E731
    for m in p.get("marks") or []:
        c = m.get("c", "#e02020").lstrip("#")
        color = tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)) if len(c) == 6 else (1, 0, 0)
        w = max(m.get("w", 4) * k, 0.5)
        s = page.new_shape()
        if m["t"] == "pen" and len(m.get("pts") or []) > 1:
            s.draw_polyline([pt(q) for q in m["pts"]])
        elif m["t"] in ("line", "arrow"):
            a, b = pt(m["a"]), pt(m["b"])
            s.draw_line(a, b)
            if m["t"] == "arrow":
                ang, L = math.atan2(b.y - a.y, b.x - a.x), max(m.get("w", 4) * 4, 18) * k
                for d in (0.45, -0.45):
                    s.draw_line(b, pymupdf.Point(b.x - L * math.cos(ang + d), b.y - L * math.sin(ang + d)))
        elif m["t"] == "oval":
            s.draw_oval(pymupdf.Rect(pt(m["a"]), pt(m["b"])).normalize())
        elif m["t"] == "rect":
            s.draw_rect(pymupdf.Rect(pt(m["a"]), pt(m["b"])).normalize())
        elif m["t"] == "text":
            size = max((m.get("size") or 48) * k, 4)
            page.insert_text(pt(m["at"]), m.get("s", ""), fontsize=size, color=color, fontname="hebo",
                             render_mode=2, border_width=0.04 if color != (1, 1, 1) else 0.08)
            continue
        s.finish(color=color, width=w, lineCap=1, lineJoin=1)
        s.commit()


def _photos(sh, data, size, pictures):
    """The photos with what's drawn on them, each saying what it's of: small three across, medium two, large one."""
    import pymupdf
    photos = [p for p in data.get("photos") or [] if p["id"] in pictures]
    chars = {c["id"]: c for c in data["chars"]}
    issues = {i["id"]: i for i in data.get("issues") or [] if not i.get("hidden")}
    photos = [p for p in photos if (p["on"] == "char" and p["of"] in chars) or (p["on"] == "issue" and p["of"] in issues)]
    if not photos:
        return
    across = {"small": 3, "medium": 2, "large": 1}[size]
    gap, cap = 12.0, 14.0
    width = (X[-1] - X[0] - gap * (across - 1)) / across
    tall = (BOTTOM - TOP - 22 - cap) if across == 1 else width * 0.75
    y = sh.new_page()
    sh.text("Photos", X[0], y + 12, "bold", 14)
    y += 22
    col = 0
    for p in photos:
        if col == 0 and y + tall + cap > BOTTOM:
            y = sh.new_page()
        x = X[0] + col * (width + gap)
        k = min(width / p["w"], tall / p["h"])
        r = pymupdf.Rect(x, y, x + p["w"] * k, y + p["h"] * k)
        sh.page.insert_image(r, stream=pictures[p["id"]])
        _marks(sh.page, r, p)
        if p["on"] == "char":
            c = chars[p["of"]]
            say = f"Balloon {balloons.label(c)}: {c.get('text') or ''}"
        else:
            i = issues[p["of"]]
            say = f"Issue #{i['n']}: {i.get('title') or ''}"
        sh.text(say, x, y + tall + 10, "sans", 9, width=width)
        col += 1
        if col == across:
            col, y = 0, y + tall + cap + gap


def write(path, data, drawing, parts=report.PER, footer="", printing=None):
    """Write the inspection sheet for an inspection list (see the top of this file). Returns how many pages."""
    import pymupdf
    o = printing or {}
    info, chars = data.get("info") or {}, report.expanded(data["chars"])
    tables = -(-min(max(int(parts or 1), len(data.get("samples") or []), 1), report.MAX_PARTS) // report.PER)
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
            end = sh.table(y, part, initial, data, t * report.PER)
            if first:  # the job and the first table are one box
                sh.box(X[0], job_top, X[-1], end)
            first = False
            y = end + 14.2
            if not rows:
                break
            y = sh.new_page()
    if o.get("issues"):
        _issues(sh, data)
    if o.get("photos") in ("small", "medium", "large") and o.get("pictures"):
        _photos(sh, data, o["photos"], o["pictures"])
    sh.flush()
    # the logo, at the top left of the first page
    logo_right = X[0]
    if o.get("logo"):
        try:
            pix = pymupdf.Pixmap(o["logo"])
            k = min(150 / pix.width, 36 / pix.height)
            r = pymupdf.Rect(X[0], 12, X[0] + pix.width * k, 12 + pix.height * k)
            doc[0].insert_image(r, stream=o["logo"])
            logo_right = r.x1 + 10
        except Exception:
            pass
    # what each page is of, along its top; when it was printed, by whom, with what, along the very bottom
    head = ""
    if o.get("header", True):
        bits = [f"Part {info['part']}" if info.get("part") else "", f"Rev {info['rev']}" if info.get("rev") else "",
                f"Job {info['job']}" if info.get("job") else "", data.get("sid") or "", STATUS.get(data.get("status") or "draft", "")]
        head = "  ·  ".join(b for b in bits if b)
    printed = f"Printed {datetime.datetime.now().strftime('%b %d, %Y %I:%M %p')}{(' by ' + o['who']) if o.get('who') else ''} · SolidSmurfs {__version__}" if o.get("header", True) else ""
    lines = [ln.strip() for ln in str(footer or "").splitlines() if ln.strip()]
    n = doc.page_count
    for i, page in enumerate(doc, 1):
        w = pymupdf.TextWriter(page.rect, color=BLACK)
        f = sh.fonts["sans"]
        sh.used.setdefault(f.name, (f, set()))[1].update("".join(lines) + f"Page {i} of {n}" + head + printed)
        if head:
            w.append((logo_right if i == 1 else X[0], 24.0 if i > 1 or logo_right == X[0] else 34.0), head, font=f, fontsize=8)
        if printed:
            w.append((PAGE[0] / 2 - f.text_length(printed, 6.5) / 2, 597.5), printed, font=f, fontsize=6.5)
        for k, ln in enumerate(lines[:1] + lines[2:]):
            w.append((33.4, 590.0 - 10.5 * k), ln, font=f, fontsize=9)
        if len(lines) > 1:
            w.append((760.0 - f.text_length(lines[1], 9), 591.0), lines[1], font=f, fontsize=9)
        if n > 1:
            s = f"Page {i} of {n}"
            w.append((PAGE[0] / 2 - f.text_length(s, 9) / 2, 591.0), s, font=f, fontsize=9)
        if lines or n > 1 or head or printed:
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
