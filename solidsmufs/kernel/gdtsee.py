"""Looking at a scanned print's picture for what OCR can't read in a feature control frame: the geometric symbol in
its first cell, and which letter is in a circle (Ⓜ Ⓛ Ⓢ ...), which OCR gives as "@".

No training and no downloads: each symbol is a few lines and arcs, drawn here as points, and the ink found in the
cell is matched to them by shape (how far, on average, each one's points are from the other's). A symbol is only
looked for inside a drawn frame (lines above and below, and a wall between it and the tolerance), and only named
when one shape fits clearly better than the rest; otherwise the frame stays a guess, as gdt.py words it.
"""

import math
import re

import numpy as np

from . import gdt

FIT = 0.085  # the most a shape may be off (of the symbol's size) to be named
CLEAR = 1.25  # and how much worse the next best must be
LETTER_FIT, LETTER_CLEAR = 0.11, 1.12


# ---------------------------------------------------------------------------------------------- the shapes
def _line(a, b, n=24):
    t = np.linspace(0, 1, n)[:, None]
    return np.array(a) * (1 - t) + np.array(b) * t


def _poly(pts, close=False):
    pts = list(pts) + ([pts[0]] if close else [])
    return np.vstack([_line(pts[i], pts[i + 1], 14) for i in range(len(pts) - 1)])


def _arc(cx, cy, r, a0=0, a1=360, n=48):
    a = np.radians(np.linspace(a0, a1, n))
    return np.stack([cx + r * np.cos(a), cy + r * np.sin(a)], axis=1)


def _arrow(a, b):
    a, b = np.array(a, float), np.array(b, float)
    d = (b - a) / np.linalg.norm(b - a)
    n = np.array([-d[1], d[0]])
    return np.vstack([_line(a, b), _poly([b - 0.45 * d + 0.2 * n, b, b - 0.45 * d - 0.2 * n], close=True)])


def _unit(pts):
    """Points scaled so their longer side is 1, centerd on the shorter."""
    pts = np.asarray(pts, float)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    span = max(hi[0] - lo[0], hi[1] - lo[1], 1e-9)
    return (pts - lo) / span + (1 - (hi - lo) / span) / 2


def _flat(slant, tall):
    return _poly([(slant, 0), (2 + slant, 0), (2, tall), (0, tall)], close=True)


# each symbol as it's usually drawn, some in a few proportions (CAD systems and fonts differ): [(kind, points)]
SHAPES = [(k, _unit(v)) for k, v in [  # y runs down the page
    ("position", np.vstack([_arc(0, 0, 1), _line((-1.5, 0), (1.5, 0)), _line((0, -1.5), (0, 1.5))])),
    ("position", np.vstack([_arc(0, 0, 1), _line((-1.25, 0), (1.25, 0)), _line((0, -1.25), (0, 1.25))])),
    *[("flatness", _flat(sl, t)) for sl in (0.35, 0.6, 0.9) for t in (0.6, 0.85, 1.1)],
    ("straightness", _line((0, 0), (2, 0))),
    ("circularity", _arc(0, 0, 1)),
    ("cylindricity", np.vstack([_arc(0, 0, 1), _line((-1.9, 1), (-0.9, -1)), _line((0.9, 1), (1.9, -1))])),
    ("cylindricity", np.vstack([_arc(0, 0, 1), _line((-1.6, 1), (-0.9, -1)), _line((0.9, 1), (1.6, -1))])),
    # (some draw a small circle between two long leaning lines)
    *[("cylindricity", np.vstack([_arc(0, 0, r), _line((-r - lean / 2, 1), (-r + lean / 2, -1)), _line((r - lean / 2, 1), (r + lean / 2, -1))]))
      for r in (0.4, 0.5, 0.65, 0.8) for lean in (0.5, 0.8, 1.1)],
    ("perpendicularity", np.vstack([_line((-1, 1), (1, 1)), _line((0, 1), (0, -1))])),
    ("perpendicularity", np.vstack([_line((-1, 1), (1, 1)), _line((0, 1), (0, -0.6))])),
    *[("parallelism", np.vstack([_line((0, 1), (dx, -1)), _line((gap, 1), (gap + dx, -1))])) for dx in (0.35, 0.6, 1.0) for gap in (0.45, 0.6, 0.9)],
    *[("angularity", np.vstack([_line((0, 1), (2, 1)), _line((0, 1), (x, y))])) for x, y in ((1.7, -0.2), (1.4, -0.4), (1.9, 0.1))],
    ("profile of a line", _arc(0, 0, 1, 180, 360)),
    ("profile of a surface", np.vstack([_arc(0, 0, 1, 180, 360), _line((-1, 0), (1, 0))])),
    ("concentricity", np.vstack([_arc(0, 0, 1), _arc(0, 0, 0.5)])),
    ("concentricity", np.vstack([_arc(0, 0, 1), _arc(0, 0, 0.62)])),
    *[("symmetry", np.vstack([_line((-1, 0), (1, 0)), _line((-s, -g), (s, -g)), _line((-s, g), (s, g))])) for s in (0.55, 0.75) for g in (0.4, 0.6)],
    ("circular runout", _arrow((0, 1), (1, -1))),
    ("circular runout", _arrow((0, 1), (1.4, -1))),
    ("total runout", np.vstack([_arrow((0, 1), (0.8, -1)), _arrow((0.9, 1), (1.7, -1)), _line((0, 1), (0.9, 1))])),
]]
LETTERS = {k: _unit(v) for k, v in {
    "M": _poly([(-0.4, 0.45), (-0.4, -0.45), (0, 0.2), (0.4, -0.45), (0.4, 0.45)]),
    "L": _poly([(-0.3, -0.45), (-0.3, 0.45), (0.35, 0.45)]),
    "S": _poly([(0.3, -0.3), (0.15, -0.45), (-0.15, -0.45), (-0.3, -0.3), (-0.3, -0.12), (-0.15, 0), (0.15, 0), (0.3, 0.12),
                (0.3, 0.3), (0.15, 0.45), (-0.15, 0.45), (-0.3, 0.3)]),
    "P": _poly([(-0.3, 0.45), (-0.3, -0.45), (0.15, -0.45), (0.3, -0.33), (0.3, -0.1), (0.15, 0), (-0.3, 0)]),
    "F": np.vstack([_poly([(-0.3, 0.45), (-0.3, -0.45), (0.3, -0.45)]), _line((-0.3, 0), (0.2, 0))]),
    "T": np.vstack([_line((-0.35, -0.45), (0.35, -0.45)), _line((0, -0.45), (0, 0.45))]),
    "U": _poly([(-0.3, -0.45), (-0.3, 0.25), (-0.15, 0.45), (0.15, 0.45), (0.3, 0.25), (0.3, -0.45)]),
}.items()}


def _apart(a, b):
    """How far apart two point sets are: the mean distance from each one's points to the other's nearest."""
    d = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(axis=2))
    return (d.min(axis=1).mean() + d.min(axis=0).mean()) / 2


def _thin(pts, most=500):
    return pts if len(pts) <= most else pts[np.linspace(0, len(pts) - 1, most).astype(int)]


def best_shape(ink_points, shapes, fit, clear):
    """The shape these ink points (x, y) are, or None when none fits clearly: (name, how far off)."""
    if len(ink_points) < 6:
        return None
    pts = _thin(_unit(ink_points))
    best = {}  # each kind's best fit, of the ways it's drawn
    for k, shape in (shapes.items() if isinstance(shapes, dict) else shapes):
        d = _apart(pts, shape)
        if d < best.get(k, 9):
            best[k] = d
    ranked = sorted((d, k) for k, d in best.items())
    (d0, k0), (d1, _) = ranked[0], ranked[1]
    return (k0, d0) if d0 <= fit and d1 >= d0 * clear else None


# ---------------------------------------------------------------------------------------------- the picture
def gray(qimage):
    """A QImage as a 2D uint8 array (0 black)."""
    from PySide6.QtGui import QImage
    g = qimage.convertToFormat(QImage.Format.Format_Grayscale8)
    a = np.frombuffer(g.constBits(), np.uint8, g.sizeInBytes()).reshape(g.height(), g.bytesPerLine())
    return a[:, :g.width()].copy()


def _ink(a):
    if not a.size:
        return np.zeros(a.shape, bool)
    lo, hi = int(a.min()), int(a.max())
    if hi - lo < 60:
        return np.zeros(a.shape, bool)
    return a < (lo + hi) / 2


def symbol_cell(img, box):
    """The ink in the frame cell left of a tolerance: box is the tolerance's (x0, y0, x1, y1) in pixels. (points,
    the cell's left edge in pixels) or None when there's no drawn frame there."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    h = y1 - y0
    H, W = img.shape
    if h < 8 or x0 < 6:
        return None
    X0, Y0, Y1 = max(0, int(x0 - 7 * h)), max(0, int(y0 - 1.9 * h)), min(H, int(y1 + 1.9 * h))
    ink = _ink(img[Y0:Y1, X0:x0])
    if not ink.any():
        return None
    w = ink.shape[1]
    # the frame's top and bottom lines: rows that are ink nearly all the way across the right half
    # (just left of the tolerance: a word's box may be as tall as the frame, when a circled letter is in it, and the
    # frame's first cell is no wider than the frame is tall)
    full = ink[:, max(0, w - max(12, int(0.8 * h))):].mean(axis=1) > 0.8
    above = [r for r in np.flatnonzero(full) if r < y0 - Y0]
    below = [r for r in np.flatnonzero(full) if r > y1 - Y0]
    if not above or not below:
        return None
    top, bottom = max(above), min(below)
    if bottom - top < h or bottom - top > 4.6 * h:
        return None
    band = ink[top + 1:bottom]
    walls = np.flatnonzero(band.mean(axis=0) > 0.85)
    if not len(walls):
        return None
    right = walls.max()  # the wall between the symbol and the tolerance
    if w - right > 3.0 * h:  # (a drawn Ø may stand between the wall and the number)
        return None
    left = [c for c in walls if c < right - 0.5 * (bottom - top)]
    if not left:
        return None
    left = max(left)
    if right - left > 2.6 * (bottom - top):
        return None
    pad = max(2, (bottom - top) // 12)
    cell = band[pad:-pad or None, left + 1 + pad:right - pad]
    ys, xs = np.nonzero(cell)
    if len(xs) < 6:
        return None
    return np.stack([xs, ys], axis=1).astype(float), X0 + left, X0 + right


def symbol(img, box):
    """(the geometric tolerance drawn in the cell left of the tolerance at `box`, the cell's left edge), or None."""
    found = symbol_cell(img, box)
    if not found:
        return None
    hit = best_shape(found[0], SHAPES, FIT, CLEAR)
    return (hit[0], found[1]) if hit else None


def circled(img, box):
    """The letter in the circle at the right end of a word's box (x0, y0, x1, y1) in pixels: "M", "L", "S", ... or
    None when it isn't clear."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    h = y1 - y0
    H, W = img.shape
    if h < 10:
        return None
    Y0, Y1, X1 = max(0, y0 - 2), min(H, y1 + 2), min(W, x1 + h // 8)  # the word's own rows: the frame's lines are outside them
    X0 = max(0, int(x1 - 1.5 * h))
    ink = _ink(img[Y0:Y1, X0:X1])
    ink[ink.mean(axis=1) > 0.8] = False  # (and any that aren't)
    ink[:, ink.mean(axis=0) > 0.9] = False  # a cell's wall
    cols = ink.any(axis=0)
    if not cols.any():
        return None
    # the last blob of ink: back from the right end to the first gap
    end = int(np.flatnonzero(cols).max())
    start = end
    while start > 0 and cols[start - 1]:
        start -= 1
    blob = ink[:, start:end + 1]
    ys, xs = np.nonzero(blob)
    if len(xs) < 20:
        return None
    pts = _unit(np.stack([xs, ys], axis=1).astype(float))
    r = np.hypot(pts[:, 0] - 0.5, pts[:, 1] - 0.5)
    if (r > 0.4).mean() < 0.25 or abs((xs.max() - xs.min()) - (ys.max() - ys.min())) > 0.3 * (ys.max() - ys.min() + 1):
        return None  # no ring around it: not a circled letter
    inner = pts[r < 0.33]
    hit = best_shape(inner, LETTERS, LETTER_FIT, LETTER_CLEAR)
    return hit[0] if hit else None


# ---------------------------------------------------------------------------------------------- on a page
_BARE = re.compile(r"^[Ø⌀∅øΦφ@QO0]?\s?[0O]?[.,]\d{2,4}[@®©]?$")
_CIRCLE_END = re.compile(r"[@®©]$")
_ALONE = re.compile(r"^(?:[@®©0OMS]|\([MLSPFTU]\))$")


def has_dia(img, box, wall):
    """Is a Ø drawn between the symbol cell's wall (pixel column `wall`) and the tolerance at box? A CAD PDF's text
    has the number but draws the Ø."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    h = y1 - y0
    if x0 - wall < 0.45 * h:
        return False
    ink = _ink(img[y0:y1, wall + 3:max(wall + 3, x0 - 1)])
    return bool(ink.size) and ink.any(axis=0).sum() >= 0.3 * h


def confirm(marks, img, k):
    """The frames found in a PDF's own text without their symbol (gdt.PENDING marks, from gdt.read_layer): each is
    kept if the picture shows a drawn frame with a symbol cell left of its tolerance, with the symbol named when
    it's clear and the Ø seen when it's drawn; the rest are dropped. A new list."""
    out = []
    for m in marks:
        if m.get("kind") != gdt.PENDING:
            out.append(m)
            continue
        g, run = m["g"], m["_run"]
        w = run[0]
        if (w[3] - w[1]) < 0.8 * (w[4] - w[2]):
            continue  # turned text: not looked for
        box = [v / k for v in w[1:5]]
        cell = symbol_cell(img, box)
        if not cell:
            continue
        g = dict(g)
        named = best_shape(cell[0], SHAPES, FIT, CLEAR)
        if named:
            g["kind"], g["guess"], g["seen"] = named[0], False, True
        if not g["dia"] and has_dia(img, box, cell[2]):
            g["dia"] = True
        x1 = m["x"] + m["w"]
        x = min(m["x"], cell[1] * k)
        out.append({**{key: v for key, v in m.items() if key != "_run"}, "kind": "gdt", "g": g, "tip": gdt.tip(g), "x": x, "w": x1 - x})
    return out


def refine(marks, words, img, k):
    """With the page's picture: name the symbol of the frames OCR found (marks from gdt.scan, changed in place), read
    their circled letters, and find the frames that are a symbol and a tolerance alone (flatness, say), which the
    words don't give away. `words`: every level word (text, x0, y0, x1, y1) in points; k: points per pixel."""
    def px(w):
        return [v / k for v in w[1:5]]

    def level(w):
        return (w[3] - w[1]) >= 0.8 * (w[4] - w[2])

    taken = []
    for m in marks:
        g, run = m.get("g"), m.get("_run")
        if not g or not run or not m.get("ocr"):
            continue
        taken.append((m["x"], m["y"], m["x"] + m["w"], m["y"] + m["h"]))
        if not g["guess"]:
            continue
        ti = next((i for i, w in enumerate(run) if re.search(r"\d", w[0])), None)
        if ti is None or not level(run[ti]):
            continue
        _letters(g, run, ti, img, px)
        hit = symbol(img, px(run[ti]))
        if hit:
            g["kind"], g["guess"], g["seen"] = hit[0], False, True
            x1 = m["x"] + m["w"]
            m["x"] = min(m["x"], hit[1] * k)
            m["w"] = x1 - m["x"]
        m["tip"] = gdt.tip(g)
    # the frames the words alone don't give away (a symbol and a tolerance, with one datum or none): a tolerance
    # with a symbol drawn in a cell to its left is one, along with whatever datums follow it on its row
    for row in gdt.rows(words):
        for i, w in enumerate(row):
            if not _BARE.match(w[0]) or not level(w) or any(w[1] < b[2] and b[0] < w[3] and w[2] < b[3] and b[1] < w[4] for b in taken):
                continue
            cell = symbol_cell(img, px(w))
            if not cell:
                continue  # no drawn frame with something in its first cell
            named = best_shape(cell[0], SHAPES, FIT, CLEAR)
            hit = (named[0] if named else None, cell[1])
            for n in range(min(8, len(row) - i), 0, -1):
                run = row[i:i + n]
                text = " ".join(x[0] for x in run)
                g = gdt.read(text, True, loose=True)
                if g:
                    break
            else:
                continue
            if hit[0]:
                g["kind"], g["guess"], g["seen"] = hit[0], False, True
            else:  # in a frame, but its symbol isn't clear: said so
                g["kind"], g["guess"] = "geometric tolerance", True
            _letters(g, run, 0, img, px)
            m = gdt.mark(run, text, gdt.tip(g), True, g)
            m["w"] += m["x"] - hit[1] * k
            m["x"] = hit[1] * k
            marks.append(m)
            taken.append((m["x"], m["y"], m["x"] + m["w"], m["y"] + m["h"]))


def _letters(g, run, ti, img, px):
    """The circled letters OCR gave as "@": read from the picture, into the frame's and its datums' modifiers."""
    datum = -1
    for i, w in enumerate(run):
        text = w[0]
        if i < ti:
            continue
        alone = i > ti and _ALONE.match(text)
        if i > ti and not alone:
            datum += len(re.findall(r"[A-Za-z](?:\s*-\s*[A-Za-z])?", re.sub(r"\([MLS]\)", "", text))) or 0
        if not (_CIRCLE_END.search(text) or (alone and text[0] != "(")):
            continue
        letter = circled(img, px(w))
        if not letter:
            continue
        if i == ti or (alone and datum < 0):
            if "?" in g["mods"]:
                g["mods"][g["mods"].index("?")] = letter
            elif alone and g["mods"]:
                g["mods"][0] = letter  # OCR's own reading of it (M, S) gives way to the shape
            g["mmc"] = next((x for x in g["mods"] if x in ("M", "L")), None)
        elif 0 <= datum < len(g["dmods"]) and g["dmods"][datum] == "?":
            g["dmods"][datum] = letter
