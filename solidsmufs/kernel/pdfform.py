"""Finding the blanks on a page that isn't a form yet, so they can be made into fields to fill in: boxes and table
cells with nothing in them (or only their caption), small squares to tick, rules to write on, and runs of
underscores in the text. From the page's own lines and words; a scanned page's lines are found in its picture.

Everything here is in the page's points as shown (turned by its /Rotate), from its top left."""

import re

import numpy as np

MIN_LINE = 28.0  # the shortest rule taken for a blank to write on, in points
TOL = 2.0  # how far apart two lines' ends can be and still meet
CHECK = (5.0, 22.0)  # a square this big on a side is a box to tick
TALL = 34.0  # a blank this high takes several lines of writing
MAX_LINES = 6000  # more lines than this on a page is a drawing, not a form: its lines are left alone
MAX_BOXES = 1200  # and more boxes than this is squared paper or a drawing's hatching
_BLANK = re.compile(r"_{3,}|\.{8,}")
_BOXES = "☐□❏❑▢"


def _merge(segs):
    """Lines along the same row that touch or overlap, as one: [(row, from, to)]."""
    out = []
    for y, a, b in sorted(segs, key=lambda s: (round(s[0]), s[1])):
        if out and abs(out[-1][0] - y) <= 1.0 and a <= out[-1][2] + 1.5:
            out[-1] = (out[-1][0], out[-1][1], max(out[-1][2], b))
        else:
            out.append((y, a, b))
    return out


def _vector_lines(pg):
    """The page's straight lines across and down, from what's drawn on it: ([(y, x0, x1)], [(x, y0, y1)])."""
    import pymupdf
    rot = pg.rotation_matrix
    hs, vs = [], []

    def seg(a, b):
        if abs(a.y - b.y) <= 1.0 and abs(a.x - b.x) >= 4:
            hs.append(((a.y + b.y) / 2, min(a.x, b.x), max(a.x, b.x)))
        elif abs(a.x - b.x) <= 1.0 and abs(a.y - b.y) >= 4:
            vs.append(((a.x + b.x) / 2, min(a.y, b.y), max(a.y, b.y)))

    def box(r):
        r = pymupdf.Rect(r) * rot
        r.normalize()
        if r.height <= 2.5 and r.width >= 4:  # a thin bar is a rule
            hs.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
        elif r.width <= 2.5 and r.height >= 4:
            vs.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
        elif r.width >= 4 and r.height >= 4:
            hs.extend([(r.y0, r.x0, r.x1), (r.y1, r.x0, r.x1)])
            vs.extend([(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)])

    try:
        drawings = pg.get_drawings()
    except Exception:
        drawings = []
    for d in drawings:
        for it in d.get("items", ()):
            if it[0] == "l":
                seg(it[1] * rot, it[2] * rot)
            elif it[0] == "re":
                box(it[1])
            elif it[0] == "qu":
                box(it[1].rect)
    return hs, vs


def _runs(dark, least, k):
    """Long runs of dark along the rows of a picture, runs on neighbouring rows taken together as one line:
    [(row, from, to)] in points (k points to a pixel). A band more than a few rows thick is a block, not a line."""
    d = np.diff(np.pad(dark, ((0, 0), (1, 1))).astype(np.int8), axis=1)
    starts, ends = np.argwhere(d == 1), np.argwhere(d == -1)
    keep = (ends[:, 1] - starts[:, 1]) >= least
    rows, x0, x1 = starts[keep, 0], starts[keep, 1], ends[keep, 1]
    if len(rows) > 20000:
        return []
    groups = []  # [first row, last row, x0, x1]
    live = []
    for r, a, b in zip(rows.tolist(), x0.tolist(), x1.tolist()):
        live = [g for g in live if r - g[1] <= 1]
        for g in live:
            if abs(g[2] - a) <= 4 and abs(g[3] - b) <= 4:
                g[1] = r
                g[2], g[3] = min(g[2], a), max(g[3], b)
                break
        else:
            g = [r, r, a, b]
            live.append(g)
            groups.append(g)
    return [((g[0] + g[1] + 1) / 2 * k, g[2] * k, g[3] * k) for g in groups if g[1] - g[0] < 7]


def _picture_lines(pg, dpi=100):
    """The same from the page's picture, for a scan: (lines across, lines down, inked(x0, y0, x1, y1): how much
    of that part of the page is dark, 0 to 1)."""
    import pymupdf
    pix = pg.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    dark = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)[:, :pix.width] < 128
    k = 72.0 / dpi

    def closed(a):  # a pixel or two missing from a scanned line doesn't break it
        b = a.copy()
        b[:, 1:] |= a[:, :-1]
        b[:, 2:] |= a[:, :-2]
        return b
    hs = _runs(closed(dark), int(7 / k), k)
    vs = _runs(closed(np.ascontiguousarray(dark.T)), int(7 / k), k)

    def inked(x0, y0, x1, y1):
        part = dark[max(int(y0 / k), 0):int(y1 / k) + 1, max(int(x0 / k), 0):int(x1 / k) + 1]
        return float(part.mean()) if part.size else 0.0
    return hs, vs, inked


def _boxes(hs, vs):
    """The smallest closed boxes the lines make (a table's cells, drawn rectangles): [(x0, y0, x1, y1)]."""
    if not hs or not vs:
        return []
    H, V = np.array(hs), np.array(vs)
    found = set()
    for y, x0, x1 in hs:
        m = (V[:, 0] >= x0 - TOL) & (V[:, 0] <= x1 + TOL) & (V[:, 1] <= y + TOL) & (V[:, 2] >= y + 4)
        if m.sum() < 2:
            continue
        down = sorted((float(x), float(b)) for x, _, b in V[m])
        sides = []  # the lines going down from this one, by where: (x, how far down)
        for x, b in down:
            if sides and x - sides[-1][0] <= TOL:
                sides[-1] = (sides[-1][0], max(sides[-1][1], b))
            else:
                sides.append((x, b))
        for (xl, bl), (xr, br) in zip(sides, sides[1:]):
            if xr - xl < 4:
                continue
            under = (H[:, 0] > y + 4) & (H[:, 0] <= min(bl, br) + TOL) & (H[:, 1] <= xl + TOL) & (H[:, 2] >= xr - TOL)
            if under.any():
                found.add((round(xl, 1), round(y, 1), round(xr, 1), round(float(H[under, 0].min()), 1)))
        if len(found) > MAX_BOXES:
            return []
    out = sorted(found)
    inside = lambda a, b: a != b and a[0] >= b[0] - TOL and a[1] >= b[1] - TOL and a[2] <= b[2] + TOL and a[3] <= b[3] + TOL
    return [b for b in out if not any(inside(a, b) for a in out)]


def _words(pg):
    """The page's words as (x0, y0, x1, y1, word), with the blanks typed into the text taken out of them:
    (words, blanks [(x0, y0, x1, y1)], boxes to tick typed as a character [(x0, y0, x1, y1)])."""
    import pymupdf
    rot = pg.rotation_matrix
    words, blanks, ticks = [], [], []
    for w in pg.get_text("words"):
        r = pymupdf.Rect(w[:4]) * rot
        r.normalize()
        t = w[4]
        if t and t[0] in _BOXES and len(t) == 1:
            s = min(r.width, r.height)
            ticks.append((r.x0, r.y1 - s, r.x0 + s, r.y1))
            continue
        runs = list(_BLANK.finditer(t))
        if not runs:
            words.append((r.x0, r.y0, r.x1, r.y1, t))
            continue
        per = r.width / max(len(t), 1)
        for m in runs:
            blanks.append((r.x0 + m.start() * per, r.y0, r.x0 + m.end() * per, r.y1))
        rest = t[:runs[0].start()]
        if rest.strip("_. "):  # "Name:____": the caption stays a word
            words.append((r.x0, r.y0, r.x0 + len(rest) * per, r.y1, rest))
    return words, blanks, ticks


def _clean(words):
    t = " ".join(w[4] for w in words)
    t = re.sub(r"\s+", " ", t).strip(" :._-()[]*#")
    return t[:40].strip()


def _caption(r, words, tick=False):
    """What a blank is for, from the words beside it: the ones before it on its row (after it, for a box to
    tick), else the ones just above, else the ones just below."""
    x0, y0, x1, y1 = r
    row = [w for w in words if y0 - 3 <= (w[1] + w[3]) / 2 <= y1 + 3]

    def before():
        got, edge = [], x0
        for w in sorted((w for w in row if w[2] <= x0 + 2), key=lambda w: -w[2]):
            if edge - w[2] > (150 if not got else 12) or len(got) >= 6:
                break
            got.insert(0, w)
            edge = w[0]
        return got

    def after():
        got, edge = [], x1
        for w in sorted((w for w in row if w[0] >= x1 - 2), key=lambda w: w[0]):
            if w[0] - edge > (20 if not got else 12) or len(got) >= 6:
                break
            got.append(w)
            edge = w[2]
        return got

    def beside(above):
        near = [w for w in words if w[2] > x0 and w[0] < x1 and
                (0 <= y0 + 2 - w[3] < 16 if above else 0 <= w[1] - (y1 - 2) < 14)]
        if not near:
            return []
        line = max(w[3] for w in near) if above else min(w[1] for w in near)
        return sorted((w for w in near if abs((w[3] if above else w[1]) - line) < 4), key=lambda w: w[0])[:6]
    for got in ((after(), before()) if tick else (before(), beside(True), beside(False))):
        name = _clean(got)
        if name:
            return name
    return ""


def detect(pg):
    """The blanks on a page: [{"kind": "text" | "checkbox", "rect": (x0, y0, x1, y1), "name", "multiline"}], down
    the page and then across. Names are the captions found beside them ("" when there's none)."""
    W, Hh = pg.rect.width, pg.rect.height
    words, blanks, ticks = _words(pg)
    hs, vs = _vector_lines(pg)
    inked = None  # on a scan there are no words to go by: a blank is one with next to no ink in it
    if not hs and not vs and not words:
        try:
            if pg.get_images():
                hs, vs, inked = _picture_lines(pg)
        except Exception:
            hs, vs = [], []
    hs, vs = _merge(hs), [(x, a, b) for x, a, b in _merge(vs)]
    if len(hs) + len(vs) > MAX_LINES:
        hs, vs = [], []
    out = []

    def add(kind, r, name=None, multiline=False):
        x0, y0, x1, y1 = r
        if x1 - x0 < 4 or y1 - y0 < 4:
            return
        area = (x1 - x0) * (y1 - y0)
        for o in out:
            a = o["rect"]
            ix, iy = min(x1, a[2]) - max(x0, a[0]), min(y1, a[3]) - max(y0, a[1])
            if ix > 0 and iy > 0 and ix * iy > 0.3 * min(area, (a[2] - a[0]) * (a[3] - a[1])):
                return
        out.append({"kind": kind, "rect": (x0, y0, x1, y1), "multiline": multiline,
                    "name": name if name is not None else _caption(r, words, kind == "checkbox")})

    # boxes: a small square is ticked, an empty one is written in, and one with only its caption in it is
    # written in beside or under the caption
    boxes = [b for b in _boxes(hs, vs) if (b[2] - b[0]) * (b[3] - b[1]) <= 0.5 * W * Hh]
    held = {b: [t for t in words if b[0] < (t[0] + t[2]) / 2 < b[2] and b[1] < (t[1] + t[3]) / 2 < b[3]] for b in boxes}
    column = lambda a, b: abs(a[0] - b[0]) <= TOL and abs(a[2] - b[2]) <= TOL

    def heading(b):
        """The words in the nearest captioned cell above an empty one in the same column: a table's heading."""
        above = [a for a in boxes if column(a, b) and a[3] <= b[1] + TOL and held[a]]
        return _clean(held[max(above, key=lambda a: a[3])]) if above else None

    for x0, y0, x1, y1 in boxes:
        w, h = x1 - x0, y1 - y0
        inside = held[(x0, y0, x1, y1)]
        if CHECK[0] <= w <= CHECK[1] and CHECK[0] <= h <= CHECK[1] and abs(w - h) <= 0.35 * max(w, h):
            if inked and (min(w, h) < 7.5 or inked(x0 + 2, y0 + 2, x1 - 2, y1 - 2) > 0.02):
                continue  # on a scan: a letter's bowl, or a box already ticked
            if not inside:
                add("checkbox", (x0 + 0.5, y0 + 0.5, x1 - 0.5, y1 - 0.5))
            continue
        if w < 24 or h < 9:
            continue
        if not inside:
            if inked and inked(x0 + 2.5, y0 + 2.5, x1 - 2.5, y1 - 2.5) > 0.004:
                continue  # a scanned cell with something written or printed in it
            add("text", (x0 + 1.5, y0 + 1.5, x1 - 1.5, y1 - 1.5), name=heading((x0, y0, x1, y1)), multiline=h >= TALL)
            continue
        if w < 60:
            continue
        if any(column(a, (x0, y0, x1, y1)) and abs(a[1] - y1) <= TOL and not held[a] for a in boxes):
            continue  # a table's heading, over the cells to fill in
        wx0, wy0 = min(t[0] for t in inside), min(t[1] for t in inside)
        wx1, wy1 = max(t[2] for t in inside), max(t[3] for t in inside)
        high = float(np.median([t[3] - t[1] for t in inside]))
        text = " ".join(t[4] for t in sorted(inside, key=lambda t: (round(t[1]), t[0])))
        under = y1 - wy1 >= max(11, 1.1 * high) and wy1 - y0 < 0.45 * h
        beside = wy1 - wy0 < 1.6 * high and wx0 - x0 < 0.3 * w and x1 - wx1 >= 40 and \
            (text.rstrip().endswith(":") or x1 - wx1 >= 0.55 * w)
        if under and (h >= TALL or not beside):  # a caption in the corner of a big box: write under it
            add("text", (x0 + 1.5, wy1 + 1, x1 - 1.5, y1 - 1.5), name=_clean(inside), multiline=y1 - wy1 >= TALL)
        elif beside:
            add("text", (wx1 + 4, y0 + 1.5, x1 - 1.5, y1 - 1.5), name=_clean(inside))

    for r in ticks:
        add("checkbox", r)
    for x0, y0, x1, y1 in blanks:
        if x1 - x0 >= 15:
            add("text", (x0, y0 - 1, x1, y1 + 1))

    # rules to write on: lines across that nothing going down meets, with room above them
    V = np.array(vs) if vs else np.zeros((0, 3))
    for y, x0, x1 in hs:
        if x1 - x0 < MIN_LINE or x1 - x0 > 0.9 * W:
            continue
        if len(V) and ((V[:, 0] >= x0 - TOL) & (V[:, 0] <= x1 + TOL) & (V[:, 1] <= y + TOL) & (V[:, 2] >= y - TOL)).any():
            continue
        over = [t for t in words if t[2] > x0 and t[0] < x1]
        sitting = [t for t in over if t[3] > y - 8 and t[1] < y]
        if sitting:  # a caption written on the line's start: the blank is the rest of it
            last = max(t[2] for t in sitting)
            if x1 - last < MIN_LINE:
                continue
            x0 = last + 3
            over = [t for t in over if t[2] > x0]
        gaps = [y - t[3] for t in over if t[3] <= y - 8]
        gaps += [y - yy for yy, a, b in hs if yy < y - 3 and b > x0 and a < x1]
        h = min(min(gaps, default=99) - 1, 16)
        if h < 7:
            continue
        if inked and inked(x0, y - h, x1, y - 2.5) > 0.01:
            continue  # scanned words standing on the line: underlined, not a blank
        add("text", (x0, y - h, x1, y - 0.5))

    out.sort(key=lambda o: (round(o["rect"][1] / 6), o["rect"][0]))
    return out
