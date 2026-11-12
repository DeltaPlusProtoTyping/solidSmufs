"""DXF drawings (AutoCAD's text exchange format), read into lines, arcs and text in world coordinates.

A DXF file is a list of (group code, value) pairs, split into sections. What's drawn is in ENTITIES,
and in the BLOCKS that entities insert (title blocks, symbols, and each dimension's lines, arrows and
text). Positions of flat entities (circles, arcs, polylines, text) are in their own plane's frame, the
"object coordinate system" set by their extrusion direction; inserted blocks add a move, turn and scale.

The reader follows every insert down to plain geometry and gives back, for each entity, the layer and
color it shows in:
    curves: Conic (circle, arc, ellipse), Poly (straight runs), and splines sampled as Poly
    texts:  Text, placed and lined up, for the viewer to set in a font
Units stay the drawing's own; `unit_mm` says how big one is.

Not drawn (and named in `skipped`): hatching, images, embedded objects, 3D solids (their geometry is
encrypted ACIS), and infinite construction lines. Binary DXF isn't read.
"""

import math
import re
from collections import Counter

import numpy as np


class DxfError(ValueError):
    pass


# $INSUNITS: drawing unit -> millimeters
UNITS_MM = {1: 25.4, 2: 304.8, 3: 1609344.0, 4: 1.0, 5: 10.0, 6: 1000.0, 7: 1e6, 8: 25.4e-6, 9: 0.0254, 10: 914.4,
            11: 1e-7, 12: 1e-6, 13: 1e-3, 14: 100.0, 15: 1e4, 16: 1e5, 17: 1e12, 21: 304.8006096}
UNIT_NAMES = {1: "inches", 2: "feet", 3: "miles", 4: "millimeters", 5: "centimeters", 6: "meters", 7: "kilometers",
              8: "microinches", 9: "mils", 10: "yards", 11: "ångströms", 12: "nanometres", 13: "microns", 14: "decimetres",
              15: "decametres", 16: "hectometres", 17: "gigametres", 21: "US survey feet"}

MAX_DEPTH = 24  # blocks inside blocks: deeper than this is a loop or a broken file


# ---------------------------------------------------------------------------------------------- colors
def _aci_table():
    """AutoCAD's 256 indexed colors as (r, g, b) in 0..1. 10-249 run through 24 hues, each in five
    shades, full and half strength; 250-255 are grays."""
    t = [(0.0, 0.0, 0.0)] * 256
    base = {1: (1, 0, 0), 2: (1, 1, 0), 3: (0, 1, 0), 4: (0, 1, 1), 5: (0, 0, 1), 6: (1, 0, 1), 7: (1, 1, 1),
            8: (65 / 255, 65 / 255, 65 / 255), 9: (128 / 255, 128 / 255, 128 / 255)}
    for i, c in base.items():
        t[i] = tuple(float(x) for x in c)
    shades = (1.0, 0.8, 0.6, 0.5, 0.3)
    for i in range(10, 250):
        hue = (i // 10 - 1) * 15.0
        k = i % 10
        value, sat = shades[k // 2], (1.0 if k % 2 == 0 else 0.5)
        h = hue / 60.0
        x = 1 - abs(h % 2 - 1)
        r, g, b = [(1, x, 0), (x, 1, 0), (0, 1, x), (0, x, 1), (x, 0, 1), (1, 0, x)][int(h) % 6]
        t[i] = tuple(value * (1 - sat + sat * c) for c in (r, g, b))
    for i, v in zip(range(250, 256), (51, 80, 105, 130, 190, 255)):
        t[i] = (v / 255,) * 3
    return t


ACI = _aci_table()


def aci(index):
    """An indexed color as (r, g, b), or None for 7 (white on black, black on white: the drawing's ink)."""
    index = abs(int(index))
    if index == 7 or not 1 <= index <= 255:
        return None
    return ACI[index]


def true_color(value):
    v = int(value) & 0xFFFFFF
    return ((v >> 16) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255)


# ---------------------------------------------------------------------------------------------- reading pairs
BINARY_SENTINEL = b"AutoCAD Binary DXF"


def _pairs(data):
    """[(code, value string)] from the file's text."""
    if data.startswith(BINARY_SENTINEL):
        raise DxfError("This is a binary DXF, which SolidSmurfs can't read yet. Save it from your CAD program as an ASCII DXF.")
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    lines = text.splitlines()
    out = []
    n = len(lines) - 1
    i = 0
    while i < n:
        code = lines[i].strip()
        if not code:  # a stray blank line between pairs
            i += 1
            continue
        try:
            c = int(code)
        except ValueError:
            raise DxfError(f"This doesn't look like a DXF file (line {i + 1} should be a group code, not {code[:20]!r}).") from None
        out.append((c, lines[i + 1]))
        i += 2
    if not out:
        raise DxfError("This DXF file is empty.")
    return out


class Ent:
    """One entity (or table entry): its type and its (code, value) pairs, in order."""

    __slots__ = ("type", "tags", "children")

    def __init__(self, typ, tags):
        self.type = typ
        cut = len(tags)
        for k, (c, _v) in enumerate(tags):  # extended data and embedded objects aren't the entity's own
            if c >= 1000 or c == 101:
                cut = k
                break
        self.tags = tags[:cut]
        self.children = []

    def get(self, code, default=None):
        for c, v in self.tags:
            if c == code:
                return v
        return default

    def text(self, code, default=""):
        v = self.get(code)
        return default if v is None else v

    def num(self, code, default=0.0):
        v = self.get(code)
        if v is None:
            return default
        try:
            f = float(v)
        except ValueError:
            return default
        return f if math.isfinite(f) else default

    def int(self, code, default=0):
        v = self.get(code)
        if v is None:
            return default
        try:
            return int(float(v))
        except ValueError:
            return default

    def point(self, code, default=(0.0, 0.0, 0.0)):
        if self.get(code) is None:
            return np.array(default, np.float64)
        return np.array([self.num(code), self.num(code + 10), self.num(code + 20)], np.float64)

    def has(self, code):
        return any(c == code for c, _ in self.tags)


def _records(pairs):
    """Split a section's pairs into (type, tags) records at each code 0."""
    out, typ, tags = [], None, []
    for c, v in pairs:
        if c == 0:
            if typ is not None:
                out.append((typ, tags))
            typ, tags = v.strip(), []
        elif typ is not None:
            tags.append((c, v))
    if typ is not None:
        out.append((typ, tags))
    return out


def _entities(records):
    """Entities from records, with each POLYLINE's vertices and each INSERT's attributes as its children."""
    out, i = [], 0
    while i < len(records):
        e = Ent(*records[i])
        i += 1
        if e.type in ("POLYLINE", "INSERT") and (e.type == "POLYLINE" or e.int(66) == 1):
            while i < len(records) and records[i][0] in ("VERTEX", "ATTRIB", "SEQEND"):
                if records[i][0] == "SEQEND":
                    i += 1
                    break
                e.children.append(Ent(*records[i]))
                i += 1
        out.append(e)
    return out


# ---------------------------------------------------------------------------------------------- geometry
def ocs(normal):
    """The 4x4 matrix from an entity's own plane frame to world coordinates (AutoCAD's arbitrary axis rule)."""
    n = np.asarray(normal, np.float64)
    length = float(np.linalg.norm(n))
    m = np.eye(4)
    if length < 1e-12 or (abs(n[0]) < 1e-12 and abs(n[1]) < 1e-12 and n[2] > 0):
        return m
    n = n / length
    ax = np.cross([0.0, 1.0, 0.0], n) if abs(n[0]) < 1 / 64 and abs(n[1]) < 1 / 64 else np.cross([0.0, 0.0, 1.0], n)
    ax /= np.linalg.norm(ax)
    ay = np.cross(n, ax)
    m[:3, 0], m[:3, 1], m[:3, 2] = ax, ay, n
    return m


def _extrusion(e):
    return ocs(e.point(210, (0.0, 0.0, 1.0)))


def _move(p):
    m = np.eye(4)
    m[:3, 3] = p
    return m


def _apply(m, pts):
    pts = np.atleast_2d(np.asarray(pts, np.float64))
    return pts @ m[:3, :3].T + m[:3, 3]


class Conic:
    """A circle, arc or ellipse: center + u·cos t + v·sin t for t from t0 to t1 (radians). Any
    move, turn or scale keeps it one, which is why inserts can't spoil it."""

    def __init__(self, center, u, v, t0, t1):
        self.center, self.u, self.v = (np.asarray(x, np.float64) for x in (center, u, v))
        self.t0, self.t1 = float(t0), float(t1)

    def moved(self, m):
        return Conic(_apply(m, self.center)[0], m[:3, :3] @ self.u, m[:3, :3] @ self.v, self.t0, self.t1)

    @property
    def closed(self):
        return self.t1 - self.t0 >= 2 * math.pi - 1e-9

    def round(self):
        """(radius, normal) when it's a true circle (or arc of one), else None."""
        lu, lv = float(np.linalg.norm(self.u)), float(np.linalg.norm(self.v))
        if lu < 1e-12 or abs(lu - lv) > 1e-9 * max(lu, 1.0) or abs(float(self.u @ self.v)) > 1e-9 * lu * lv:
            return None
        n = np.cross(self.u, self.v)
        return lu, n / np.linalg.norm(n)

    def at(self, t):
        t = np.asarray(t, np.float64)
        return self.center + np.outer(np.cos(t), self.u) + np.outer(np.sin(t), self.v)


class Poly:
    """Straight runs through points; `kind` says what to call each piece ("line" pieces each become an edge)."""

    def __init__(self, points, kind="line"):
        self.points = np.asarray(points, np.float64).reshape(-1, 3)
        self.kind = kind

    def moved(self, m):
        return Poly(_apply(m, self.points), self.kind)


class Text:
    """Text placed in the world. `origin` is the point it lines up on; `xdir` and `ydir` are unit
    directions along and up its lines; `height` is the capital-letter height, and `width` how much wider
    than normal its letters are. `halign` left/center/right and `valign` baseline/bottom/middle/top
    say how it sits on `origin`. `wrap` is a width to wrap lines at (0: don't), `fit` a width to stretch
    the text to (0: don't). For several lines, `spacing` is the line pitch as a multiple of 5/3 the height."""

    __slots__ = ("lines", "origin", "xdir", "ydir", "height", "width", "halign", "valign", "wrap", "fit", "spacing", "mtext")

    def __init__(self, lines, origin, xdir, ydir, height, width=1.0, halign="left", valign="baseline", wrap=0.0, fit=0.0,
                 spacing=1.0, mtext=False):
        self.lines, self.origin, self.xdir, self.ydir = lines, origin, xdir, ydir
        self.height, self.width, self.halign, self.valign = height, width, halign, valign
        self.wrap, self.fit, self.spacing, self.mtext = wrap, fit, spacing, mtext


def _text_frame(m, origin, angle, height, width):
    """A Text's world placement from a position, angle (radians) and size in a frame `m`: (origin, xdir,
    ydir, height, width factor, length scale along the line)."""
    lin = m[:3, :3]
    x = lin @ np.array([math.cos(angle), math.sin(angle), 0.0])
    y = lin @ np.array([-math.sin(angle), math.cos(angle), 0.0])
    lx, ly = float(np.linalg.norm(x)), float(np.linalg.norm(y))
    if lx < 1e-15 or ly < 1e-15:
        return None
    o = _apply(m, origin)[0]
    return o, x / lx, y / ly, height * ly, width * lx / ly, lx


# ---------------------------------------------------------------------------------------------- splines
def _spline_points(e):
    """Points along a SPLINE (control points through de Boor, or a smooth run through its fit points)."""
    degree = max(1, e.int(71, 3))
    knots, weights, ctrl, fit = [], [], [], []
    cur = None
    for c, v in e.tags:
        try:
            f = float(v)
        except ValueError:
            continue
        if c == 40:
            knots.append(f)
        elif c == 41:
            weights.append(f)
        elif c == 10:
            cur = [f, 0.0, 0.0]
            ctrl.append(cur)
        elif c == 20 and ctrl:
            ctrl[-1][1] = f
        elif c == 30 and ctrl:
            ctrl[-1][2] = f
        elif c == 11:
            fit.append([f, 0.0, 0.0])
        elif c == 21 and fit:
            fit[-1][1] = f
        elif c == 31 and fit:
            fit[-1][2] = f
    ctrl = np.asarray(ctrl, np.float64).reshape(-1, 3)
    if len(ctrl) >= 2:
        n = len(ctrl)
        degree = min(degree, n - 1)
        if len(knots) != n + degree + 1:  # missing or wrong: clamped and even
            inner = np.linspace(0, 1, n - degree + 1)
            knots = [0.0] * degree + list(inner) + [1.0] * degree
        u = np.asarray(knots, np.float64)
        w = np.asarray(weights, np.float64) if len(weights) == n else np.ones(n)
        lo, hi = u[degree], u[n]
        if not hi > lo:
            return ctrl
        samples = np.linspace(lo, hi, min(4000, max(32, n * 12)))
        return np.array([_de_boor(t, degree, u, ctrl, w) for t in samples])
    fit = np.asarray(fit, np.float64).reshape(-1, 3)
    if len(fit) >= 2:
        return _through(fit, bool(e.int(70) & 1))
    return None


def _de_boor(t, p, u, ctrl, w):
    n = len(ctrl)
    k = int(np.searchsorted(u, t, side="right") - 1)
    k = min(max(k, p), n - 1)
    d = [np.append(ctrl[j] * w[j], w[j]) for j in range(k - p, k + 1)]
    for r in range(1, p + 1):
        for j in range(p, r - 1, -1):
            i = j + k - p
            den = u[i + p - r + 1] - u[i]
            a = 0.0 if den == 0 else (t - u[i]) / den
            d[j] = (1 - a) * d[j - 1] + a * d[j]
    h = d[p]
    return h[:3] / h[3] if h[3] != 0 else h[:3]


def _through(pts, closed, steps=8):
    """A smooth (Catmull-Rom) run through points."""
    if len(pts) < 3:
        return pts
    p = np.vstack([pts[-1:] if closed else pts[:1] * 2 - pts[1:2], pts, pts[:1] if closed else pts[-1:] * 2 - pts[-2:-1]])
    if closed:
        p = np.vstack([p, pts[1:2]])
    t = np.linspace(0, 1, steps + 1)[:-1, None]
    out = []
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        out.append(0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(p[len(p) - 2:len(p) - 1])
    return np.vstack(out)


# ---------------------------------------------------------------------------------------------- text strings
_SPECIAL = {"c": "\u00d8", "d": "\u00b0", "p": "\u00b1", "%": "%"}


def plain_text(s):
    """A TEXT string as it shows: %%c → Ø, %%d → °, %%p → ±, %%nnn → that character, \\U+hhhh → that
    character; underline and overline switches dropped."""
    s = re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), s)

    def special(m):
        code = m.group(1).lower()
        if code.isdigit():
            return chr(int(code))
        return _SPECIAL.get(code, "")

    return re.sub(r"%%(\d{3}|[cdpuoCDPUO%])", special, s)


def mtext_lines(s):
    """An MTEXT string's lines, with its formatting codes (fonts, colors, heights, …) taken out."""
    s = re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r"\\M\+[0-9A-Fa-f]{5}", "", s)
    out, i, n = [], 0, len(s)
    buf = []
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n:
            nx = s[i + 1]
            if nx == "P":
                out.append("".join(buf))
                buf = []
                i += 2
            elif nx in "\\{}":
                buf.append(nx)
                i += 2
            elif nx == "~":
                buf.append("\u00a0")
                i += 2
            elif nx == "S":  # stacked text a^b, a/b, a#b → a/b
                end = s.find(";", i)
                end = n if end < 0 else end
                part = s[i + 2:end]
                buf.append(re.sub(r"[\^#]", "/", part).replace("/ ", "/").strip())
                i = end + 1
            elif nx in "LlOoKkNX":  # underline, overline, strike, column break: no text
                i += 2
            elif nx in "ACcFfHhQqTtWwp":  # codes with a value up to ';'
                end = s.find(";", i)
                i = n if end < 0 else end + 1
            else:
                buf.append(nx)
                i += 2
        elif ch in "{}":
            i += 1
        else:
            buf.append(ch)
            i += 1
    out.append("".join(buf))
    return [plain_text(line) for line in out]


# ---------------------------------------------------------------------------------------------- the drawing
class Layer:
    def __init__(self, name, color=None, on=True, frozen=False):
        self.name, self.color, self.on, self.frozen = name, color, on, frozen


class Drawing:
    def __init__(self):
        self.layers = {}  # upper-case name -> Layer, in the file's order
        self.curves = []  # (layer key, color or None, Conic | Poly)
        self.texts = []  # (layer key, color or None, Text)
        self.unit_mm = 1.0
        self.units = None  # "inches", ... or None when the drawing doesn't say
        self.version = None
        self.space = "model"  # or "paper" when only paper space has anything in it
        self.skipped = Counter()  # entity type -> count not drawn
        self.warnings = []

    def layer(self, name):
        key = (name or "0").upper()
        if key not in self.layers:
            self.layers[key] = Layer(name or "0")
        return key


class _Reader:
    def __init__(self, drawing, blocks):
        self.d, self.blocks = drawing, blocks
        self.inserting = []

    # what an entity draws with: its layer (layer 0 in a block takes the insert's) and color
    def _layer(self, e, outer_layer):
        name = e.text(8, "0").strip() or "0"
        if name == "0" and outer_layer is not None:
            return outer_layer
        return self.d.layer(name)

    def _color(self, e, layer, outer_color):
        tc = e.get(420)
        if tc is not None:
            try:
                return true_color(int(tc))
            except ValueError:
                pass
        c = e.int(62, 256)
        if c == 0:  # BYBLOCK
            return outer_color
        if c == 256 or c < 0:  # BYLAYER
            return self.d.layers[layer].color
        return aci(c)

    def walk(self, ents, m, outer_layer=None, outer_color=None, depth=0):
        for e in ents:
            if e.int(60) == 1:  # invisible
                continue
            try:
                layer = self._layer(e, outer_layer)
                if outer_layer is not None and self.d.layers[outer_layer].frozen:
                    layer = outer_layer  # everything in an insert on a frozen layer goes with it
                color = self._color(e, layer, outer_color)
                self._one(e, m, layer, color, depth)
            except (ValueError, IndexError, ZeroDivisionError, OverflowError, np.linalg.LinAlgError):
                self.d.skipped[e.type + " (unreadable)"] += 1

    def _curve(self, layer, color, c):
        self.d.curves.append((layer, color, c))

    def _one(self, e, m, layer, color, depth):
        t = e.type
        if t == "LINE":
            self._curve(layer, color, Poly(_apply(m, [e.point(10), e.point(11)])))
        elif t in ("CIRCLE", "ARC"):
            r = e.num(40)
            if r <= 0:
                return
            if t == "CIRCLE":
                t0, t1 = 0.0, 2 * math.pi
            else:
                t0 = math.radians(e.num(50))
                t1 = math.radians(e.num(51, 360.0))
                while t1 <= t0:
                    t1 += 2 * math.pi
            self._curve(layer, color, Conic(e.point(10), [r, 0, 0], [0, r, 0], t0, t1).moved(m @ _extrusion(e)))
        elif t == "ELLIPSE":
            n = e.point(210, (0.0, 0.0, 1.0))
            n = n / (np.linalg.norm(n) or 1.0)
            major = e.point(11)
            ratio = e.num(40, 1.0)
            t0, t1 = e.num(41, 0.0), e.num(42, 2 * math.pi)
            while t1 <= t0:
                t1 += 2 * math.pi
            if t1 - t0 > 2 * math.pi + 1e-9:
                t1 = t0 + 2 * math.pi
            self._curve(layer, color, Conic(e.point(10), major, ratio * np.cross(n, major), t0, t1).moved(m))
        elif t == "LWPOLYLINE":
            self._lwpolyline(e, m @ _extrusion(e), layer, color)
        elif t == "POLYLINE":
            self._polyline(e, m, layer, color)
        elif t == "SPLINE":
            pts = _spline_points(e)
            if pts is not None and len(pts) >= 2:
                self._curve(layer, color, Poly(_apply(m, pts), "spline"))
        elif t in ("SOLID", "TRACE"):
            a, b, c, d = (e.point(k) for k in (10, 11, 12, 13))
            ring = [a, b, d, c, a] if np.linalg.norm(d - c) > 1e-12 else [a, b, c, a]
            self._edges_of(_apply(m @ _extrusion(e), ring), layer, color)
        elif t == "3DFACE":
            pts = [e.point(k) for k in (10, 11, 12, 13)]
            hidden = e.int(70)
            for k in range(4):
                if not hidden & (1 << k) and np.linalg.norm(pts[k] - pts[(k + 1) % 4]) > 1e-12:
                    self._curve(layer, color, Poly(_apply(m, [pts[k], pts[(k + 1) % 4]])))
        elif t == "LEADER":
            pts = [[float(v), 0.0, 0.0] for c, v in e.tags if c == 10]
            ys = [float(v) for c, v in e.tags if c == 20]
            zs = [float(v) for c, v in e.tags if c == 30]
            for k, p in enumerate(pts):
                p[1] = ys[k] if k < len(ys) else 0.0
                p[2] = zs[k] if k < len(zs) else 0.0
            if len(pts) >= 2:
                self._edges_of(_apply(m, pts), layer, color)
        elif t in ("TEXT", "ATTRIB"):
            if t == "ATTRIB" and e.int(70) & 1:  # an invisible attribute
                return
            self._text(e, m, layer, color, t == "ATTRIB")
        elif t == "MTEXT":
            self._mtext(e, m, layer, color)
        elif t == "INSERT":
            self._insert(e, m, layer, color, depth)
        elif t == "DIMENSION":
            name = e.text(2).strip()
            block = self.blocks.get(name.upper())
            if block is None:
                self.d.skipped["DIMENSION (no picture in the file)"] += 1
                return
            frame = m @ _extrusion(e) @ _move(e.point(12))
            self._block(block, frame, layer, color, depth)
        elif t in ("POINT", "ATTDEF", "VIEWPORT", "WIPEOUT", "SEQEND", "ENDBLK", "BLOCK"):
            pass  # points mark positions only; ATTDEF shows in the block editor; viewports are paper space windows
        elif t == "HATCH":
            self.d.skipped["hatching"] += 1
        elif t in ("IMAGE", "OLE2FRAME", "OLEFRAME"):
            self.d.skipped["images and embedded objects"] += 1
        elif t in ("3DSOLID", "REGION", "BODY", "SURFACE", "EXTRUDEDSURFACE", "LOFTEDSURFACE", "REVOLVEDSURFACE", "SWEPTSURFACE",
                   "PLANESURFACE", "MESH"):
            self.d.skipped["3D solids and surfaces"] += 1
        elif t in ("XLINE", "RAY"):
            self.d.skipped["construction lines"] += 1
        else:
            self.d.skipped[t.lower()] += 1

    def _edges_of(self, pts, layer, color):
        for k in range(len(pts) - 1):
            if np.linalg.norm(pts[k + 1] - pts[k]) > 0:
                self._curve(layer, color, Poly(pts[k:k + 2]))

    def _bulge_run(self, verts, closed, m, layer, color):
        """Straight segments and arcs between polyline vertices [(x, y, z, bulge)] in frame m."""
        count = len(verts)
        for k in range(count if closed else count - 1):
            x0, y0, z0, bulge = verts[k]
            x1, y1, z1, _ = verts[(k + 1) % count]
            p0, p1 = np.array([x0, y0, z0]), np.array([x1, y1, z1])
            chord = float(np.hypot(x1 - x0, y1 - y0))
            if chord <= 1e-15:
                continue
            if abs(bulge) < 1e-12:
                self._curve(layer, color, Poly(_apply(m, [p0, p1])))
                continue
            # bulge = tan(sweep / 4), + anticlockwise; the center sits off the chord's middle, to its left
            # for an anticlockwise arc under half a circle (the formula's sign covers the other cases)
            sweep = 4 * math.atan(bulge)
            r = chord / (2 * math.sin(abs(sweep) / 2))
            d = (p1 - p0) / chord
            left = np.array([-d[1], d[0], 0.0])
            center = (p0 + p1) / 2 + left * chord * (1 - bulge * bulge) / (4 * bulge)
            if bulge > 0:
                a0 = math.atan2(p0[1] - center[1], p0[0] - center[0])
            else:  # clockwise: the same arc, run anticlockwise from the far end
                a0 = math.atan2(p1[1] - center[1], p1[0] - center[0])
            conic = Conic([center[0], center[1], z0], [r, 0, 0], [0, r, 0], a0, a0 + abs(sweep))
            self._curve(layer, color, conic.moved(m))

    def _lwpolyline(self, e, m, layer, color):
        z = e.num(38)
        verts = []
        for c, v in e.tags:
            if c == 10:
                verts.append([float(v), 0.0, z, 0.0])
            elif c == 20 and verts:
                verts[-1][1] = float(v)
            elif c == 42 and verts:
                verts[-1][3] = float(v)
        if len(verts) >= 2:
            self._bulge_run(verts, bool(e.int(70) & 1), m, layer, color)

    def _polyline(self, e, m, layer, color):
        flags = e.int(70)
        verts = [v for v in e.children if v.type == "VERTEX"]
        if flags & 64:  # polyface mesh: the corner vertices, then faces naming them
            corners = [v.point(10) for v in verts if v.int(70) & 64]
            seen = set()
            for f in (v for v in verts if v.int(70) & 128 and not v.int(70) & 64):
                idx = [f.int(k) for k in (71, 72, 73, 74) if f.has(k) and f.int(k) != 0]
                for k in range(len(idx)):
                    a, b = idx[k], idx[(k + 1) % len(idx)]
                    if a < 0:  # a negative number hides the edge that starts there
                        continue
                    a, b = abs(a) - 1, abs(b) - 1
                    key = (min(a, b), max(a, b))
                    if key in seen or not (0 <= a < len(corners) and 0 <= b < len(corners)):
                        continue
                    seen.add(key)
                    self._curve(layer, color, Poly(_apply(m, [corners[a], corners[b]])))
            return
        if flags & 16:  # polygon mesh: a grid of m × n points
            rows, cols = max(e.int(71), 1), max(e.int(72), 1)
            pts = np.array([v.point(10) for v in verts][: rows * cols])
            if len(pts) != rows * cols:
                return
            grid = _apply(m, pts).reshape(rows, cols, 3)
            for r in range(rows):
                self._edges_of(np.vstack([grid[r], grid[r, :1]]) if flags & 32 else grid[r], layer, color)
            for c in range(cols):
                self._edges_of(np.vstack([grid[:, c], grid[:1, c]]) if flags & 1 else grid[:, c], layer, color)
            return
        # a fitted spline polyline lists its frame points too: draw what the curve went through
        if flags & 4:
            verts = [v for v in verts if not v.int(70) & 16]
        if flags & 8:  # 3D polyline: world points, straight runs
            pts = _apply(m, [v.point(10) for v in verts])
            if flags & 1 and len(pts) > 2:
                pts = np.vstack([pts, pts[:1]])
            self._edges_of(pts, layer, color)
            return
        z = e.point(10)[2]  # a 2D polyline's elevation
        run = [[*v.point(10)[:2], z, v.num(42)] for v in verts]
        if len(run) >= 2:
            self._bulge_run(run, bool(flags & 1), m @ _extrusion(e), layer, color)

    def _text(self, e, m, layer, color, attrib):
        raw = e.text(1)
        if not raw.strip():
            return
        frame = m @ _extrusion(e)
        h = e.num(40, 1.0)
        width = e.num(41, 1.0) or 1.0
        angle = math.radians(e.num(50))
        halign = e.int(72)
        valign = e.int(74 if attrib else 73)
        first, second = e.point(10), e.point(11) if e.has(11) else None
        fit = 0.0
        if halign in (3, 5) and second is not None and np.linalg.norm(second - first) > 1e-12:  # aligned / fit: between two points
            angle = math.atan2(second[1] - first[1], second[0] - first[0])
            fit = float(np.linalg.norm((second - first)[:2]))
            at, ha, va = (first + second) / 2, "center", "baseline"
        else:
            at = second if (halign or valign) and second is not None else first
            ha = {0: "left", 1: "center", 2: "right", 4: "center"}.get(halign, "left")
            va = "middle" if halign == 4 else {0: "baseline", 1: "bottom", 2: "middle", 3: "top"}.get(valign, "baseline")
        placed = _text_frame(frame, at, angle, h, width)
        if placed is None:
            return
        o, xd, yd, hh, ww, along = placed
        mirror = e.int(71)
        if mirror & 2:
            xd = -xd
        if mirror & 4:
            yd = -yd
        self.d.texts.append((layer, color, Text([plain_text(raw)], o, xd, yd, hh, ww, ha, va, fit=fit * along)))

    def _mtext(self, e, m, layer, color):
        raw = "".join(v for c, v in e.tags if c == 3) + e.text(1)
        if not raw.strip():
            return
        n = e.point(210, (0.0, 0.0, 1.0))
        frame = ocs(n)
        h = e.num(40, 1.0)
        if e.has(11):  # its x direction, in world coordinates: into its own plane's frame for the angle
            xw = e.point(11)
            local = np.linalg.inv(frame[:3, :3]) @ xw
            angle = math.atan2(local[1], local[0])
        else:
            angle = math.radians(e.num(50))
        at = np.linalg.inv(frame) @ np.append(e.point(10), 1.0)  # its position is in world coordinates
        placed = _text_frame(m @ frame, at[:3], angle, h, 1.0)
        if placed is None:
            return
        o, xd, yd, hh, ww, along = placed
        attach = e.int(71, 1)
        ha = ("left", "center", "right")[(attach - 1) % 3] if 1 <= attach <= 9 else "left"
        va = ("top", "middle", "bottom")[(attach - 1) // 3] if 1 <= attach <= 9 else "top"
        self.d.texts.append((layer, color, Text(mtext_lines(raw), o, xd, yd, hh, ww, ha, va, wrap=e.num(41) * along,
                                                spacing=e.num(44, 1.0) or 1.0, mtext=True)))

    def _insert(self, e, m, layer, color, depth):
        name = e.text(2).strip()
        block = self.blocks.get(name.upper())
        if block is not None:
            sx, sy, sz = e.num(41, 1.0), e.num(42, 1.0), e.num(43, 1.0)
            rot = math.radians(e.num(50))
            cols, rows = max(e.int(70, 1), 1), max(e.int(71, 1), 1)
            dx, dy = e.num(44), e.num(45)
            if cols * rows > 10000:
                cols, rows = min(cols, 100), min(rows, 100)
                self.d.warnings.append(f"Block {name} is set out in a very large grid; only the first 100 × 100 are drawn.")
            turn = np.eye(4)
            turn[:2, :2] = [[math.cos(rot), -math.sin(rot)], [math.sin(rot), math.cos(rot)]]
            scale = np.diag([sx, sy, sz, 1.0])
            base = m @ _extrusion(e) @ _move(e.point(10)) @ turn
            for r in range(rows):
                for c in range(cols):
                    self._block(block, base @ _move([c * dx, r * dy, 0.0]) @ scale, layer, color, depth)
        elif name:
            self.d.skipped["missing blocks"] += 1
        # its attributes are placed already, in the insert's own surroundings; BYBLOCK ones take its color
        self.walk([a for a in e.children if a.type == "ATTRIB"], m, None, color, depth)

    def _block(self, block, m, layer, color, depth):
        name, base, ents, xref = block
        if xref:
            self.d.skipped["external references (xrefs)"] += 1
            return
        if depth >= MAX_DEPTH or name in self.inserting:
            self.d.skipped["blocks that insert themselves"] += 1
            return
        self.inserting.append(name)
        try:
            self.walk(ents, m @ _move(-base), layer, color, depth + 1)
        finally:
            self.inserting.pop()


def read_dxf(data):
    """A Drawing from a DXF file's bytes."""
    pairs = _pairs(data)
    sections, i = {}, 0
    while i < len(pairs):
        if pairs[i] == (0, "SECTION") or (pairs[i][0] == 0 and pairs[i][1].strip() == "SECTION"):
            name = pairs[i + 1][1].strip().upper() if i + 1 < len(pairs) and pairs[i + 1][0] == 2 else ""
            j = i + 2
            while j < len(pairs) and not (pairs[j][0] == 0 and pairs[j][1].strip() in ("ENDSEC", "EOF")):
                j += 1
            sections[name] = pairs[i + 2:j]
            i = j + 1
        else:
            i += 1
    if "ENTITIES" not in sections and "BLOCKS" not in sections:
        raise DxfError("This DXF file has no drawing in it (no ENTITIES section).")
    d = Drawing()

    # header: units and version
    header = {}
    hp = sections.get("HEADER", [])
    name = None
    for c, v in hp:
        if c == 9:
            name = v.strip().upper()
            header[name] = []
        elif name is not None:
            header[name].append((c, v))
    d.version = (header.get("$ACADVER") or [(1, None)])[0][1]
    d.version = d.version.strip() if d.version else None

    def header_int(name):
        try:
            return int(float(header[name][0][1]))
        except (KeyError, IndexError, ValueError):
            return None

    insunits, measurement = header_int("$INSUNITS"), header_int("$MEASUREMENT")
    if insunits in UNITS_MM:
        d.unit_mm, d.units = UNITS_MM[insunits], UNIT_NAMES[insunits]
    elif measurement in (0, 1):
        d.unit_mm, d.units = (25.4, "inches") if measurement == 0 else (1.0, "millimeters")
    else:
        d.unit_mm, d.units = 25.4, None

    # layers
    for typ, tags in _records(sections.get("TABLES", [])):
        if typ != "LAYER":
            continue
        e = Ent(typ, tags)
        name = e.text(2, "0").strip() or "0"
        c = e.int(62, 7)
        tc = e.get(420)
        try:
            color = true_color(int(tc)) if tc is not None else aci(c)
        except ValueError:
            color = aci(c)
        d.layers[name.upper()] = Layer(name, color, on=c >= 0, frozen=bool(e.int(70) & 1))

    # blocks: name -> (name, base point, entities, is an xref)
    blocks, current, inside = {}, None, []
    for typ, tags in _records(sections.get("BLOCKS", [])):
        if typ == "BLOCK":
            current = Ent(typ, tags)
            inside = []
        elif typ == "ENDBLK":
            if current is not None:
                name = current.text(2).strip()
                blocks[name.upper()] = (name.upper(), current.point(10), _entities(inside), bool(current.int(70) & 12))
            current = None
        elif current is not None:
            inside.append((typ, tags))

    ents = _entities(_records(sections.get("ENTITIES", [])))
    model = [e for e in ents if e.int(67) != 1]
    drawn = [e for e in model if e.type not in ("VIEWPORT",)]
    if not drawn:  # nothing in model space: show the paper (a layout) instead
        paper = [e for e in ents if e.int(67) == 1 and e.type != "VIEWPORT"]
        if not paper:
            block = blocks.get("*PAPER_SPACE")
            paper = [e for e in block[2] if e.type != "VIEWPORT"] if block else []
        if paper:
            drawn, d.space = paper, "paper"
    _Reader(d, blocks).walk(drawn, np.eye(4))
    if not d.curves and not d.texts:
        what = ", ".join(f"{n} {k}" for k, n in d.skipped.most_common(4))
        raise DxfError("This DXF has nothing SolidSmurfs can draw" + (f" (it holds {what})." if what else "."))
    return d
