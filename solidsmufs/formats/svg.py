"""SVG drawings, read into a drawing of lines, arcs and text in millimetres (Y up, as in a CAD drawing).

Understood: path (every command: M L H V C S Q T A Z), rect (rounded too), circle, ellipse, line, polyline, polygon,
text / tspan, g, a, use / symbol, and transforms on all of them. Each top-level group (an Inkscape or Illustrator
layer) is a layer. Strokes give the colour, else fills; shapes with neither are drawn in the drawing's ink.
Gradients, patterns, clipping, masks, filters and embedded pictures aren't drawn.

Sizes: a width / height in real units (mm, cm, in, pt) with a viewBox sets the scale; otherwise a user unit is a
CSS pixel, 1/96 inch.
"""

import math
import re
import xml.etree.ElementTree as ET
from collections import Counter

import numpy as np

from .dxf import Conic, Drawing, Layer, Poly, Text

UNIT_MM = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72, "pc": 25.4 / 6, "px": 25.4 / 96, "": 25.4 / 96}
NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
SKIP = {"defs", "clipPath", "mask", "marker", "pattern", "linearGradient", "radialGradient", "style", "script", "title",
        "desc", "metadata", "symbol", "filter", "foreignObject", "namedview", "font", "font-face"}
NAMED = {"black": (0, 0, 0), "white": (1, 1, 1), "red": (1, 0, 0), "green": (0, 0.5, 0), "lime": (0, 1, 0), "blue": (0, 0, 1),
         "yellow": (1, 1, 0), "cyan": (0, 1, 1), "aqua": (0, 1, 1), "magenta": (1, 0, 1), "fuchsia": (1, 0, 1),
         "gray": (0.5, 0.5, 0.5), "grey": (0.5, 0.5, 0.5), "silver": (0.75, 0.75, 0.75), "maroon": (0.5, 0, 0),
         "olive": (0.5, 0.5, 0), "purple": (0.5, 0, 0.5), "teal": (0, 0.5, 0.5), "navy": (0, 0, 0.5), "orange": (1, 0.65, 0)}
CURVE_STEPS = 24


class SvgError(ValueError):
    pass


def _tag(el):
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def _length(text, default=0.0):
    m = re.match(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([a-z%]*)", text or "")
    if not m:
        return default, ""
    return float(m.group(1)), m.group(2)


def _num(text, default=0.0):
    return _length(text, default)[0]


def _color(text):
    """(r, g, b) in 0..1 for a CSS colour; None for none / unreadable; 'ink' for black (the drawing's ink)."""
    if not text:
        return None
    t = text.strip().lower()
    if t in ("none", "transparent") or t.startswith("url("):
        return None
    if t.startswith("#"):
        h = t[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h[:3])
        try:
            rgb = tuple(int(h[k:k + 2], 16) / 255 for k in (0, 2, 4))
        except ValueError:
            return None
    elif t.startswith("rgb"):
        vals = NUM.findall(t)[:3]
        if len(vals) < 3:
            return None
        rgb = tuple(min(max(float(v) / (100 if "%" in t else 255), 0.0), 1.0) for v in vals)
    elif t in NAMED:
        rgb = NAMED[t]
    else:
        return None
    return "ink" if max(rgb) < 0.08 else tuple(float(x) for x in rgb)


def _style(el, inherited):
    """The presentation properties that matter here, from attributes and style="", over the inherited ones."""
    s = dict(inherited)
    for k in ("stroke", "fill", "display", "visibility", "font-size"):
        if el.get(k) is not None:
            s[k] = el.get(k)
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            k = k.strip()
            if k in ("stroke", "fill", "display", "visibility", "font-size"):
                s[k] = v.strip()
    return s


def _transform(text):
    m = np.eye(3)
    for name, args in re.findall(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)", text or ""):
        a = [float(v) for v in NUM.findall(args)]
        t = np.eye(3)
        if name == "matrix" and len(a) == 6:
            t = np.array([[a[0], a[2], a[4]], [a[1], a[3], a[5]], [0, 0, 1]])
        elif name == "translate" and a:
            t[0, 2], t[1, 2] = a[0], a[1] if len(a) > 1 else 0.0
        elif name == "scale" and a:
            t[0, 0], t[1, 1] = a[0], a[1] if len(a) > 1 else a[0]
        elif name == "rotate" and a:
            c, s = math.cos(math.radians(a[0])), math.sin(math.radians(a[0]))
            r = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
            if len(a) >= 3:
                r = np.array([[1, 0, a[1]], [0, 1, a[2]], [0, 0, 1]]) @ r @ np.array([[1, 0, -a[1]], [0, 1, -a[2]], [0, 0, 1]])
            t = r
        elif name == "skewX" and a:
            t[0, 1] = math.tan(math.radians(a[0]))
        elif name == "skewY" and a:
            t[1, 0] = math.tan(math.radians(a[0]))
        m = m @ t
    return m


def _arc_center(p0, p1, rx, ry, phi, large, sweep):
    """SVG's endpoint arc as (centre, rx, ry, start angle, sweep angle) in its own (unrotated) frame; None: a line."""
    rx, ry = abs(rx), abs(ry)
    if rx < 1e-12 or ry < 1e-12 or np.allclose(p0, p1):
        return None
    c, s = math.cos(phi), math.sin(phi)
    dx, dy = (p0 - p1) / 2
    x1, y1 = c * dx + s * dy, -s * dx + c * dy
    lam = (x1 / rx) ** 2 + (y1 / ry) ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    k = math.sqrt(max(num / den, 0.0)) if den else 0.0
    if large == sweep:
        k = -k
    cx1, cy1 = k * rx * y1 / ry, -k * ry * x1 / rx
    center = np.array([c * cx1 - s * cy1, s * cx1 + c * cy1]) + (p0 + p1) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    t0 = ang(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = ang((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    return center, rx, ry, t0, dt


class _Reader:
    def __init__(self, root):
        self.d = Drawing()
        self.d.unit_mm = 1.0
        self.ids = {el.get("id"): el for el in root.iter() if el.get("id")}
        self.skipped = Counter()
        self.depth = 0

    # -------------------------------------------------------------- output
    def _conic(self, m, center, rx, ry, phi, t0, dt, layer, color):
        """An ellipse arc in user space put through `m` (affine, so it stays one)."""
        c, s = math.cos(phi), math.sin(phi)
        u = np.array([rx * c, rx * s])
        v = np.array([-ry * s, ry * c])
        lin = m[:2, :2]
        cw = m @ np.array([center[0], center[1], 1.0])
        uu, vv = lin @ u, lin @ v
        if dt < 0:  # keep the parameter rising: run it the other way with v flipped
            vv, t0, dt = -vv, -t0, -dt
        self.d.curves.append((layer, color, Conic([cw[0], cw[1], 0], [uu[0], uu[1], 0], [vv[0], vv[1], 0], t0, t0 + dt)))

    def _poly(self, m, pts, layer, color, kind="line"):
        if len(pts) < 2:
            return
        p = np.asarray(pts, float)
        w = (m @ np.c_[p, np.ones(len(p))].T).T
        self.d.curves.append((layer, color, Poly(np.c_[w[:, :2], np.zeros(len(w))], kind)))

    # -------------------------------------------------------------- elements
    def walk(self, el, m, style, layer):
        tag = _tag(el)
        if tag in SKIP or self.depth > 40:
            return
        style = _style(el, style)
        if style.get("display") == "none" or style.get("visibility") in ("hidden", "collapse"):
            return
        m = m @ _transform(el.get("transform"))
        stroke, fill = _color(style.get("stroke")), _color(style.get("fill", "black"))
        paint = stroke if stroke is not None else fill
        color = None if paint in (None, "ink") else paint  # None: the layer's colour (the drawing's ink)
        if tag in ("svg", "g", "a", "switch"):
            if tag == "svg" and self.depth:  # a nested svg: its own position
                m = m @ _transform(f"translate({_num(el.get('x'))},{_num(el.get('y'))})")
            self.depth += 1
            for child in el:
                self.walk(child, m, style, layer)
            self.depth -= 1
        elif tag == "use":
            ref = (el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or "").lstrip("#")
            target = self.ids.get(ref)
            if target is not None and self.depth < 40:
                m = m @ _transform(f"translate({_num(el.get('x'))},{_num(el.get('y'))})")
                self.depth += 1
                if _tag(target) == "symbol":
                    for child in target:
                        self.walk(child, m, style, layer)
                else:
                    self.walk(target, m, style, layer)
                self.depth -= 1
        elif tag == "path":
            self.path(el.get("d") or "", m, layer, color)
        elif tag == "rect":
            x, y, w, h = (_num(el.get(k)) for k in ("x", "y", "width", "height"))
            rx, ry = el.get("rx"), el.get("ry")
            rx = _num(rx if rx is not None else ry)
            ry = _num(ry if ry is not None else el.get("rx"))
            rx, ry = min(rx, w / 2), min(ry, h / 2)
            if w <= 0 or h <= 0:
                return
            if rx > 0 and ry > 0:
                self.path(f"M{x + rx},{y} H{x + w - rx} A{rx},{ry} 0 0 1 {x + w},{y + ry} V{y + h - ry} A{rx},{ry} 0 0 1 {x + w - rx},{y + h} "
                          f"H{x + rx} A{rx},{ry} 0 0 1 {x},{y + h - ry} V{y + ry} A{rx},{ry} 0 0 1 {x + rx},{y} Z", m, layer, color)
            else:
                self._poly(m, [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)], layer, color)
        elif tag in ("circle", "ellipse"):
            cx, cy = _num(el.get("cx")), _num(el.get("cy"))
            rx = _num(el.get("r")) if tag == "circle" else _num(el.get("rx"))
            ry = _num(el.get("r")) if tag == "circle" else _num(el.get("ry"))
            if rx > 0 and ry > 0:
                self._conic(m, (cx, cy), rx, ry, 0.0, 0.0, 2 * math.pi, layer, color)
        elif tag == "line":
            self._poly(m, [(_num(el.get("x1")), _num(el.get("y1"))), (_num(el.get("x2")), _num(el.get("y2")))], layer, color)
        elif tag in ("polyline", "polygon"):
            v = [float(x) for x in NUM.findall(el.get("points") or "")]
            pts = [(v[k], v[k + 1]) for k in range(0, len(v) - 1, 2)]
            if tag == "polygon" and pts:
                pts.append(pts[0])
            self._poly(m, pts, layer, color)
        elif tag == "text":
            self.text(el, m, style, layer, color)
        elif tag in ("image",):
            self.skipped["embedded pictures"] += 1

    def text(self, el, m, style, layer, color):
        size = _num(style.get("font-size"), 16.0) or 16.0
        x, y = _num(el.get("x")), _num(el.get("y"))
        runs = [(el.text or "", x, y)]
        for t in el:
            if _tag(t) == "tspan":
                runs.append((t.text or "", _num(t.get("x"), x) if t.get("x") else None, _num(t.get("y"), y) if t.get("y") else None))
            if t.tail:
                runs.append((t.tail, None, None))
        lines, origin = [], None
        for s, rx, ry in runs:
            s = " ".join(s.split())
            if not s:
                continue
            if origin is None:
                origin = (rx if rx is not None else x, ry if ry is not None else y)
            if ry is not None and lines and (rx, ry) != origin:
                lines.append(s)
            elif lines:
                lines[-1] += " " + s
            else:
                lines.append(s)
        if not lines:
            return
        lin = m[:2, :2]
        o = m @ np.array([origin[0], origin[1], 1.0])
        xd, yd = lin @ np.array([1.0, 0.0]), lin @ np.array([0.0, -1.0])  # up the letters: -y in SVG
        lx, ly = float(np.hypot(*xd)), float(np.hypot(*yd))
        if lx < 1e-12 or ly < 1e-12:
            return
        height = size * 0.7 * ly  # the capital-letter height of a font this size
        anchor = {"middle": "center", "end": "right"}.get(el.get("text-anchor") or "", "left")
        self.d.texts.append((layer, color, Text(lines, np.array([o[0], o[1], 0.0]), np.array([xd[0] / lx, xd[1] / lx, 0]),
                                                np.array([yd[0] / ly, yd[1] / ly, 0]), height, width=lx / ly, halign=anchor)))

    def path(self, d, m, layer, color):
        toks = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d)
        i, cmd = 0, None
        cur, start = np.zeros(2), np.zeros(2)
        last_c = None  # the last control point, for S and T
        run = []

        def flush():
            nonlocal run
            if len(run) >= 2:
                self._poly(m, run, layer, color)
            run = []

        def nums(k):
            nonlocal i
            out = []
            for _ in range(k):
                if i >= len(toks) or toks[i].isalpha():
                    return None
                out.append(float(toks[i]))
                i += 1
            return out

        def flags_num():  # an arc's flags may be written run together ("0 01")
            nonlocal i
            if i >= len(toks) or toks[i].isalpha():
                return None
            t = toks[i]
            if len(t) > 1 and t[0] in "01" and not t.startswith(("0.", "1.")):
                toks[i] = t[1:]
                return float(t[0])
            i += 1
            return float(t)

        while i < len(toks):
            if toks[i].isalpha():
                cmd = toks[i]
                i += 1
                if cmd in "Zz":
                    if run:
                        run.append(tuple(start))
                    flush()
                    cur = start.copy()
                    last_c = None
                    continue
            if cmd is None:
                i += 1
                continue
            rel = cmd.islower()
            base = cur if rel else np.zeros(2)
            c = cmd.upper()
            if c == "M":
                v = nums(2)
                if v is None:
                    break
                flush()
                cur = base + v
                start = cur.copy()
                run = [tuple(cur)]
                cmd = "l" if rel else "L"  # more pairs after a move are lines
                last_c = None
            elif c in "LHV":
                if c == "L":
                    v = nums(2)
                    if v is None:
                        break
                    cur = base + v
                elif c == "H":
                    v = nums(1)
                    if v is None:
                        break
                    cur = np.array([(cur[0] if rel else 0) + v[0], cur[1]])
                else:
                    v = nums(1)
                    if v is None:
                        break
                    cur = np.array([cur[0], (cur[1] if rel else 0) + v[0]])
                if not run:
                    run = [tuple(start)]
                run.append(tuple(cur))
                last_c = None
            elif c in "CSQT":
                if c == "C":
                    v = nums(6)
                    if v is None:
                        break
                    c1, c2, p = base + v[0:2], base + v[2:4], base + v[4:6]
                elif c == "S":
                    v = nums(4)
                    if v is None:
                        break
                    c1 = 2 * cur - last_c[0] if last_c is not None and last_c[1] == "c" else cur.copy()
                    c2, p = base + v[0:2], base + v[2:4]
                elif c == "Q":
                    v = nums(4)
                    if v is None:
                        break
                    q, p = base + v[0:2], base + v[2:4]
                    c1, c2 = cur + 2 / 3 * (q - cur), p + 2 / 3 * (q - p)
                else:  # T
                    v = nums(2)
                    if v is None:
                        break
                    q = 2 * cur - last_c[0] if last_c is not None and last_c[1] == "q" else cur.copy()
                    p = base + v
                    c1, c2 = cur + 2 / 3 * (q - cur), p + 2 / 3 * (q - p)
                t = np.linspace(0, 1, CURVE_STEPS + 1)[:, None]
                pts = (1 - t) ** 3 * cur + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t ** 2 * c2 + t ** 3 * p
                flush()  # the straight run so far, then the curve as one piece
                self._poly(m, pts, layer, color, "spline")
                run = [tuple(p)]
                last_c = (q, "q") if c in "QT" else (c2, "c")
                cur = p
            elif c == "A":
                v = nums(3)
                if v is None:
                    break
                large, sweep = flags_num(), flags_num()
                pv = nums(2)
                if large is None or sweep is None or pv is None:
                    break
                p = base + pv
                arc = _arc_center(cur, p, v[0], v[1], math.radians(v[2]), bool(large), bool(sweep))
                if arc is None:
                    if not run:
                        run = [tuple(cur)]
                    run.append(tuple(p))
                else:
                    flush()
                    center, rx, ry, t0, dt = arc
                    self._conic(m, center, rx, ry, math.radians(v[2]), t0, dt, layer, color)
                    run = [tuple(p)]
                cur = p
                last_c = None
            else:
                i += 1
        flush()


def read_svg(data):
    """A Drawing (in mm, Y up) from the bytes of an SVG file."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise SvgError(f"This SVG can't be read: {e}") from None
    if _tag(root) != "svg":
        raise SvgError("This isn't an SVG drawing.")
    vb = [float(v) for v in NUM.findall(root.get("viewBox") or "")]
    (w, wu), (h, hu) = _length(root.get("width")), _length(root.get("height"))
    units = None
    if len(vb) == 4 and vb[2] > 0 and vb[3] > 0:
        if w and wu in UNIT_MM and wu not in ("", "px"):
            scale = w * UNIT_MM[wu] / vb[2]
            units = {"mm": "millimetres", "cm": "centimetres", "in": "inches", "pt": "points", "pc": "picas"}[wu]
        elif w:
            scale = w * UNIT_MM.get(wu, UNIT_MM["px"]) / vb[2]
        else:
            scale = UNIT_MM["px"]
        top = vb[1] + vb[3]
        m = np.array([[scale, 0, -vb[0] * scale], [0, -scale, top * scale], [0, 0, 1]])
    else:
        scale = UNIT_MM.get(wu, UNIT_MM["px"])
        if wu in ("mm", "cm", "in", "pt", "pc"):
            units = {"mm": "millimetres", "cm": "centimetres", "in": "inches", "pt": "points", "pc": "picas"}[wu]
        m = np.array([[scale, 0, 0], [0, -scale, (h or 0) * UNIT_MM.get(hu, UNIT_MM["px"])], [0, 0, 1]])

    r = _Reader(root)
    # top-level groups are layers (Inkscape marks them; Illustrator names them by id)
    ink_label = "{http://www.inkscape.org/namespaces/inkscape}label"
    groups = [el for el in root if _tag(el) == "g"]
    loose = [el for el in root if _tag(el) not in ("g",) and _tag(el) not in SKIP]
    base_style = _style(root, {})
    if groups and not any(_tag(el) in ("path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "use")
                          for el in loose):
        for k, g in enumerate(groups):
            name = g.get(ink_label) or g.get("id") or f"Group {k + 1}"
            key = f"{k}:{name}".upper()
            r.d.layers[key] = Layer(name)
            r.walk(g, m, base_style, key)
    else:
        r.d.layers["DRAWING"] = Layer("Drawing")
        for el in root:
            r.walk(el, m, base_style, "DRAWING")
    r.d.units = units or "pixels (1/96 inch each)"
    r.d.skipped.update(r.skipped)
    if not r.d.curves and not r.d.texts:
        raise SvgError("This SVG has no lines, shapes or text in it to draw.")
    return r.d
