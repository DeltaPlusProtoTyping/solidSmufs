"""A DXF drawing as a model the viewer can show: no faces, just edges (each line, arc, circle, ellipse and
spline its own edge, so the measure tool can pick them) and text. Each layer is a body, so it can be
shown and hidden from the tree. Everything is in millimetres."""

import math
from pathlib import Path

import numpy as np

from ..formats import dxf
from .geom import unit
from .model import Model

INK = [0.05, 0.05, 0.06]  # AutoCAD colour 7: black on a light background (the viewer swaps it on a dark one)

VERSIONS = {"AC1009": "R11/R12", "AC1012": "R13", "AC1014": "R14", "AC1015": "2000", "AC1018": "2004", "AC1021": "2007",
            "AC1024": "2010", "AC1027": "2013", "AC1032": "2018"}

MAX_STEP = math.radians(3.0)  # arcs are drawn in steps no bigger than this, however big they are


def _bounds(curves):
    """(min, max) corners of a drawing's curves, ellipses taken whole (a quick, safe overestimate)."""
    pts = []
    for _layer, _color, c in curves:
        if isinstance(c, dxf.Conic):
            reach = np.abs(c.u) + np.abs(c.v)
            pts += [c.center - reach, c.center + reach]
        else:
            pts.append(c.points.min(axis=0))
            pts.append(c.points.max(axis=0))
    if not pts:
        return None
    pts = np.array(pts)
    return pts.min(axis=0), pts.max(axis=0)


def _conic_points(c, tol):
    r = max(float(np.linalg.norm(c.u)), float(np.linalg.norm(c.v)))
    sweep = c.t1 - c.t0
    step = MAX_STEP
    if r > tol:
        step = min(step, 2 * math.acos(max(-1.0, 1 - tol / r)))
    n = int(min(max(math.ceil(sweep / step), 4 if c.closed else 1), 4000))
    return c.at(np.linspace(c.t0, c.t1, n + 1))


def load(path, name, progress=lambda *a: None, fmt="DXF"):
    progress("Reading the drawing", 0.2)
    d = dxf.read_dxf(Path(path).read_bytes())
    s = d.unit_mm
    m = Model(name, path, fmt)
    m.kind = "drawing"

    # layers with something on them become bodies, in the layer table's order
    used = {layer for layer, _c, _x in d.curves} | {layer for layer, _c, _x in d.texts}
    body_of = {}
    for key, layer in d.layers.items():
        if key in used:
            body_of[key] = len(m.bodies)
            m.bodies.append({"name": layer.name, "path": [layer.name], "kind": "layer", "color": layer.color or INK,
                             "faces": (0, 0), "hidden": not layer.on or layer.frozen})

    progress("Laying out the lines", 0.5)
    box = _bounds(d.curves)
    size = float(np.linalg.norm(box[1] - box[0])) if box is not None else 1.0
    tol = max(size, 1e-9) * 2e-5  # how far an arc's straight steps may stray from it, in drawing units

    segs, colors, bodies, types, params, lengths, ends = [], [], [], [], [], [], []

    def edge(pts, typ, prm, color, layer):
        pts = np.asarray(pts, np.float64) * s
        if len(pts) < 2:
            return
        steps = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        if not steps.sum() > 0:
            return
        segs.append(np.stack([pts[:-1], pts[1:]], axis=1))
        lengths.append(float(steps.sum()))
        types.append(typ)
        params.append(prm)
        colors.append(color)
        bodies.append(body_of[layer])
        if not (prm or {}).get("closed"):
            ends.extend([pts[0], pts[-1]])

    for layer, color, c in d.curves:
        if isinstance(c, dxf.Conic):
            pts = _conic_points(c, tol)
            rnd = c.round()
            start, end = pts[0] * s, pts[-1] * s
            if rnd is not None:
                r, n = rnd
                prm = {"center": c.center * s, "radius": r * s, "normal": n, "closed": c.closed,
                       "angle": math.degrees(c.t1 - c.t0), "start": start, "end": end}
                edge(pts, "circle", prm, color, layer)
            else:
                lu, lv = float(np.linalg.norm(c.u)), float(np.linalg.norm(c.v))
                major, minor = (c.u, c.v) if lu >= lv else (c.v, c.u)
                prm = {"center": c.center * s, "major_radius": max(lu, lv) * s, "minor_radius": min(lu, lv) * s,
                       "normal": unit(np.cross(c.u, c.v)), "major_dir": unit(major), "closed": c.closed, "start": start, "end": end}
                edge(pts, "ellipse", prm, color, layer)
        elif c.kind == "spline":
            closed = float(np.linalg.norm(c.points[0] - c.points[-1])) <= tol
            edge(c.points, "spline", {"start": c.points[0] * s, "end": c.points[-1] * s, "closed": closed}, color, layer)
        else:
            for k in range(len(c.points) - 1):
                a, b = c.points[k] * s, c.points[k + 1] * s
                if float(np.linalg.norm(b - a)) > 0:
                    edge(c.points[k:k + 2], "line", {"start": a, "end": b, "dir": unit(b - a)}, color, layer)

    m.segments = np.concatenate(segs).astype(np.float32) if segs else np.zeros((0, 2, 3), np.float32)
    counts = [len(x) for x in segs]
    m.edge_sstart = list(np.concatenate([[0], np.cumsum(counts)[:-1]]).astype(int)) if counts else []
    m.edge_scount = counts
    m.edge_type, m.edge_params, m.edge_length = types, params, lengths
    m.edge_faces = [[] for _ in types]
    m.edge_seam = [False] * len(types)
    m.edge_color = colors
    m.edge_body = bodies
    if ends:  # line and arc ends, once each, to pick and measure from
        pts = np.array(ends)
        key = np.round(pts / max(tol * s, 1e-9)).astype(np.int64)
        _u, first = np.unique(key, axis=0, return_index=True)
        m.vertices = pts[np.sort(first)]

    m.texts = []
    for layer, color, t in d.texts:
        if t.height <= 0 or not any(line.strip() for line in t.lines):
            continue
        m.texts.append({"body": body_of[layer], "color": color, "lines": t.lines, "origin": t.origin * s, "x": t.xdir, "y": t.ydir,
                        "height": t.height * s, "width": t.width, "halign": t.halign, "valign": t.valign,
                        "wrap": t.wrap * s, "fit": t.fit * s, "spacing": t.spacing, "mtext": t.mtext})
    m.drawing = True

    # what the document panel and the notices say
    if d.version:
        m.info["DXF version"] = f"AutoCAD {VERSIONS.get(d.version, d.version)}"
    m.info["Units"] = d.units or "not given (shown as inches)"
    m.info["Layers"] = str(len(m.bodies))
    if d.texts:
        m.info["Text items"] = str(len(m.texts))
    if d.units is None:
        m.notices.append("This drawing doesn't say what units it's in, so it's shown in inches. "
                         "If it was drawn in millimetres, its sizes read 25.4 times too big.")
    if d.space == "paper":
        m.notices.append("This drawing has nothing in model space, so its paper layout is shown.")
    if d.skipped:
        what = "; ".join(f"{name} ({n})" for name, n in d.skipped.most_common())
        m.notices.append(f"Some things in this drawing aren't shown: {what}.")
    m.warnings += d.warnings
    m.stats["drawing"] = True
    return m
