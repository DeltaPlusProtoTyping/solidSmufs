"""The measure tool: what to report for a selection of faces, edges, vertices and picked points,
SolidWorks-style (distance, centre distance, normal distance, angle, dX/dY/dZ, radius, area, …).

Distances between B-rep entities come from OpenCASCADE (exact); everything else from the
analytic data the loader worked out (plane normals, axes, circle centres). For mesh documents the
same questions are answered from the triangles.

Results are in mm and degrees; the browser formats them in the user's units. Each result row:
{"label", "value", "kind": "length" | "area" | "angle" | "number" | "point" | "text", "primary"?}
and graphics for the view: {"type": "line" | "point" | "axis", ...}.
"""

import math

import numpy as np

from .geom import angle_deg, line_line, point_line, unit

PARALLEL_DEG = 1e-4  # angles closer than this to 0/180 count as parallel


class Entity:
    """One selected thing. kind: face / edge / vertex / point; index into the model's arrays."""

    def __init__(self, model, sel):
        self.m = model
        self.kind = sel["kind"]
        self.index = int(sel.get("index", -1))
        self.pick = np.asarray(sel["point"], np.float64) if sel.get("point") is not None else None
        self.type, self.params = None, None
        if self.kind == "face":
            self.type, self.params = model.face_type[self.index], model.face_params[self.index]
        elif self.kind == "edge":
            self.type, self.params = model.edge_type[self.index], model.edge_params[self.index]

    @property
    def label(self):
        names = {"face": "Face", "edge": "Edge", "vertex": "Vertex", "point": "Point"}
        return f"{names[self.kind]} {self.index + 1}" if self.kind != "point" else "Point"

    # what kind of geometric thing it is, for the pairwise rules
    def point(self):
        if self.kind == "vertex":
            return np.asarray(self.m.vertices[self.index], np.float64)
        if self.kind == "point":
            return self.pick
        return None

    def centre(self):
        """A circle / arc / sphere centre, else None."""
        p = self.params or {}
        if self.type in ("circle", "ellipse", "sphere") and p.get("center") is not None:
            return np.asarray(p["center"], np.float64)
        return None

    def axis(self):
        """(point, direction) of a cylinder / cone / torus axis, or a circle's axis, else None."""
        p = self.params or {}
        if self.type in ("cylinder", "cone", "torus") and p.get("axis") is not None:
            return np.asarray(p["center"], np.float64), unit(p["axis"])
        if self.type in ("circle", "ellipse") and p.get("normal") is not None:
            return np.asarray(p["center"], np.float64), unit(p["normal"])
        return None

    def plane(self):
        """(point, unit normal) of a planar face, else None."""
        if self.type == "plane" and self.params:
            return np.asarray(self.params["origin"], np.float64), unit(self.params["normal"])
        return None

    def line(self):
        """(point, unit direction) of a straight edge, else None."""
        if self.type == "line" and self.params:
            return np.asarray(self.params["start"], np.float64), unit(self.params["dir"])
        return None

    def radius(self):
        p = self.params or {}
        return p.get("radius")


# ---------------------------------------------------------------------------------------------- one entity
def single(e, extra):
    rows, gfx = [], []
    m = e.m
    if e.kind in ("vertex", "point"):
        p = e.point()
        rows += [{"label": "X", "value": p[0], "kind": "length", "signed": True},
                 {"label": "Y", "value": p[1], "kind": "length", "signed": True},
                 {"label": "Z", "value": p[2], "kind": "length", "signed": True}]
        gfx.append({"type": "point", "p": p})
        return rows, gfx
    if e.kind == "edge":
        p = e.params or {}
        length = m.edge_length[e.index]
        if e.type == "circle" and p:
            closed = p.get("closed")
            rows.append({"label": "Diameter" if closed else "Radius", "value": 2 * p["radius"] if closed else p["radius"],
                         "kind": "length", "primary": True})
            rows.append({"label": "Radius" if closed else "Diameter", "value": p["radius"] if closed else 2 * p["radius"],
                         "kind": "length"})
            if not closed:
                rows.append({"label": "Arc length", "value": length, "kind": "length"})
                rows.append({"label": "Arc angle", "value": p["angle"], "kind": "angle"})
            else:
                rows.append({"label": "Circumference", "value": length, "kind": "length"})
            rows.append({"label": "Center", "value": p["center"], "kind": "point"})
            gfx.append({"type": "point", "p": p["center"], "style": "center"})
        elif e.type == "ellipse" and p:
            rows += [{"label": "Major radius", "value": p["major_radius"], "kind": "length", "primary": True},
                     {"label": "Minor radius", "value": p["minor_radius"], "kind": "length"},
                     {"label": "Length", "value": length, "kind": "length"},
                     {"label": "Center", "value": p["center"], "kind": "point"}]
        else:
            rows.append({"label": "Length", "value": length, "kind": "length", "primary": True})
            if e.type == "line" and p:
                d = np.asarray(p["end"]) - np.asarray(p["start"])
                rows += [{"label": "dX", "value": abs(d[0]), "kind": "length"},
                         {"label": "dY", "value": abs(d[1]), "kind": "length"},
                         {"label": "dZ", "value": abs(d[2]), "kind": "length"}]
        rows.append({"label": "Type", "value": _type_name(e.type), "kind": "text"})
        return rows, gfx
    # face
    p = e.params or {}
    area = face_area(m, e.index)
    rows.append({"label": "Area", "value": area, "kind": "area", "primary": e.type not in ("cylinder", "sphere")})
    per = face_perimeter(m, e.index)
    if per is not None:
        rows.append({"label": "Perimeter", "value": per, "kind": "length"})
    if e.type == "cylinder" and p:
        rows.insert(0, {"label": "Diameter", "value": 2 * p["radius"], "kind": "length", "primary": True})
        rows.insert(1, {"label": "Radius", "value": p["radius"], "kind": "length"})
        rows.append({"label": "Axis direction", "value": p["axis"], "kind": "vector"})
        gfx.append({"type": "axis", "p": p["center"], "d": p["axis"], "len": _face_extent(m, e.index)})
    elif e.type == "sphere" and p:
        rows.insert(0, {"label": "Diameter", "value": 2 * p["radius"], "kind": "length", "primary": True})
        rows.insert(1, {"label": "Radius", "value": p["radius"], "kind": "length"})
        rows.append({"label": "Center", "value": p["center"], "kind": "point"})
        gfx.append({"type": "point", "p": p["center"], "style": "center"})
    elif e.type == "cone" and p:
        rows.append({"label": "Cone angle", "value": 2 * p["half_angle"], "kind": "angle"})
        rows.append({"label": "Half angle", "value": p["half_angle"], "kind": "angle"})
        rows.append({"label": "Diameter (large)", "value": 2 * p["radius_max"], "kind": "length"})
        rows.append({"label": "Diameter (small)", "value": 2 * p["radius_min"], "kind": "length"})
        gfx.append({"type": "axis", "p": p["center"], "d": p["axis"], "len": _face_extent(m, e.index)})
    elif e.type == "torus" and p:
        rows.append({"label": "Major radius", "value": p["major_radius"], "kind": "length"})
        rows.append({"label": "Minor radius", "value": p["minor_radius"], "kind": "length"})
    elif e.type == "plane" and p:
        rows.append({"label": "Normal", "value": p["normal"], "kind": "vector"})
    centroid = face_centroid(m, e.index)
    if centroid is not None:
        rows.append({"label": "Centroid", "value": centroid, "kind": "point"})
    rows.append({"label": "Type", "value": _type_name(e.type), "kind": "text"})
    return rows, gfx


def face_centroid(m, f):
    if hasattr(m, "exact_centroid"):
        c = m.exact_centroid(f)
        if c is not None:
            return c
    pts, tri = m.face_triangles(f)
    if not len(tri):
        return None
    a, b, c = pts[tri[:, 0]], pts[tri[:, 1]], pts[tri[:, 2]]
    w = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    return ((a + b + c) / 3 * w[:, None]).sum(axis=0) / w.sum() if w.sum() > 0 else None


def _type_name(t):
    return {"plane": "Plane", "cylinder": "Cylinder", "cone": "Cone", "sphere": "Sphere", "torus": "Torus",
            "bspline": "Spline surface", "bezier": "Bezier surface", "revolution": "Surface of revolution",
            "line": "Line", "circle": "Circle / arc", "ellipse": "Ellipse", "mesh": "Mesh region",
            "polyline": "Polyline", "curve": "Curve", "surface": "Surface", "conic": "Conic"}.get(t, (t or "?").title())


def face_area(m, f):
    if hasattr(m, "exact_area"):
        a = m.exact_area(f)
        if a is not None:
            return a
    pts, tri = m.face_triangles(f)
    if not len(tri):
        return 0.0
    return float(np.linalg.norm(np.cross(pts[tri[:, 1]] - pts[tri[:, 0]], pts[tri[:, 2]] - pts[tri[:, 0]]), axis=1).sum() / 2)


def face_perimeter(m, f):
    edges = [e for e, fs in enumerate(m.edge_faces) if f in fs and not m.edge_seam[e]]
    if not edges:
        return None
    return float(sum(m.edge_length[e] for e in edges))


def _face_extent(m, f):
    pts, _ = m.face_triangles(f)
    return float(np.linalg.norm(np.ptp(pts, axis=0))) if len(pts) else 1.0


# ---------------------------------------------------------------------------------------------- two entities
def pair(a, b, opts, exact_distance):
    """Rows and graphics for two entities. exact_distance(a, b) → (d, p1, p2) or None."""
    rows, gfx = [], []
    arc_mode = opts.get("arc", "center")  # how circles / arcs are measured: center | min | max

    pa, pb = a.point(), b.point()
    ca, cb = a.centre(), b.centre()
    # SolidWorks measures circles and arcs centre to centre unless told otherwise
    use_centre_a = ca is not None and a.kind == "edge" and arc_mode == "center"
    use_centre_b = cb is not None and b.kind == "edge" and arc_mode == "center"

    # 1. the main distance
    main = None
    if pa is not None and pb is not None:
        main = ("Distance", pa, pb)
    elif (use_centre_a or pa is not None) and (use_centre_b or pb is not None) and (use_centre_a or use_centre_b):
        main = ("Center distance", ca if use_centre_a else pa, cb if use_centre_b else pb)
    if main is None:
        res = exact_distance(a, b)
        if res is not None:
            d, p1, p2 = res
            main = ("Distance", p1, p2)
    if main is not None and arc_mode == "max" and (a.type == "circle" or b.type == "circle"):
        main = _max_distance(a, b) or main
    if main is not None:
        label, p1, p2 = main
        d = float(np.linalg.norm(p2 - p1))
        rows.append({"label": label if arc_mode != "max" or label != "Distance" else "Max distance", "value": d,
                     "kind": "length", "primary": True})
        delta = p2 - p1
        rows += [{"label": "dX", "value": abs(delta[0]), "kind": "length", "axis": "x"},
                 {"label": "dY", "value": abs(delta[1]), "kind": "length", "axis": "y"},
                 {"label": "dZ", "value": abs(delta[2]), "kind": "length", "axis": "z"}]
        gfx.append({"type": "line", "p1": p1, "p2": p2, "value": d, "xyz": True})

    # 2. centre distance for round things (when the main distance wasn't already that)
    if main is None or main[0] != "Center distance":
        cd = _centre_distance(a, b)
        if cd is not None:
            d, p1, p2 = cd
            rows.append({"label": "Center distance", "value": d, "kind": "length"})
            gfx.append({"type": "line", "p1": p1, "p2": p2, "value": d, "style": "center"})

    # 3. normal distance / angle between flat and straight things
    na, nb = _direction(a), _direction(b)
    if na is not None and nb is not None:
        ang = angle_deg(na[1], nb[1])
        kinds = (na[0], nb[0])
        if kinds == ("normal", "normal"):  # two planes: angle between them
            shown = ang
            if ang < PARALLEL_DEG or ang > 180 - PARALLEL_DEG:
                pl_a, pl_b = a.plane(), b.plane()
                nd = abs(float((pl_b[0] - pl_a[0]) @ pl_a[1]))
                rows.append({"label": "Normal distance", "value": nd, "kind": "length",
                             "primary": main is None})
                rows.append({"label": "Angle", "value": "0.00° (parallel)", "kind": "text"})
                foot = pl_b[0] - pl_a[1] * float((pl_b[0] - pl_a[0]) @ pl_a[1])
                gfx.append({"type": "line", "p1": foot, "p2": pl_b[0], "value": nd, "style": "normal"})
            else:
                rows.append({"label": "Angle", "value": shown, "kind": "angle", "primary": main is None})
        elif "normal" in kinds:  # a plane and a line / axis
            rows.append({"label": "Angle", "value": abs(90 - ang), "kind": "angle"})
            if abs(90 - ang) < PARALLEL_DEG:
                plane_e, other = (a, b) if kinds[0] == "normal" else (b, a)
                pl = plane_e.plane()
                q = _anchor(other)
                if q is not None:
                    nd = abs(float((q - pl[0]) @ pl[1]))
                    rows.append({"label": "Normal distance", "value": nd, "kind": "length"})
        else:  # lines and axes
            acute = min(ang, 180 - ang)
            rows.append({"label": "Angle", "value": acute, "kind": "angle"})
            if acute < PARALLEL_DEG:
                qa, qb = _anchor(a), _anchor(b)
                if qa is not None and qb is not None:
                    foot = point_line(qb, qa, na[1])
                    rows.append({"label": "Perpendicular distance", "value": float(np.linalg.norm(qb - foot)),
                                 "kind": "length"})
    # 4. a point and a plane: normal distance
    for p, e in ((pa, b), (pb, a)):
        if p is not None and e.plane() is not None:
            o, n = e.plane()
            rows.append({"label": "Normal distance", "value": abs(float((p - o) @ n)), "kind": "length"})
    return rows, gfx


def _direction(e):
    if e.plane() is not None:
        return "normal", e.plane()[1]
    if e.line() is not None:
        return "line", e.line()[1]
    ax = e.axis()
    if ax is not None and e.type in ("cylinder", "cone"):
        return "line", ax[1]
    return None


def _anchor(e):
    """A point the entity's line / axis / plane passes through."""
    if e.plane() is not None:
        return e.plane()[0]
    if e.line() is not None:
        return e.line()[0]
    ax = e.axis()
    return ax[0] if ax is not None else None


def _centre_distance(a, b):
    """Centre-to-centre / axis-to-axis / centre-to-plane distance when either side is round."""
    ra = a.centre() is not None or (a.axis() is not None and a.type in ("cylinder", "cone"))
    rb = b.centre() is not None or (b.axis() is not None and b.type in ("cylinder", "cone"))
    if not (ra or rb):
        return None

    def as_geom(e):
        if e.centre() is not None:
            return "p", e.centre(), None
        if e.type in ("cylinder", "cone") and e.axis() is not None:
            return "l", *e.axis()
        if e.point() is not None:
            return "p", e.point(), None
        if e.plane() is not None:
            return "pl", *e.plane()
        if e.line() is not None:
            return "l", *e.line()
        return None

    ga, gb = as_geom(a), as_geom(b)
    if ga is None or gb is None:
        return None
    (ka, xa, da), (kb, xb, db) = ga, gb
    if ka == "p" and kb == "p":
        p1, p2 = xa, xb
    elif ka == "p" and kb == "l":
        p1, p2 = xa, point_line(xa, xb, db)
    elif ka == "l" and kb == "p":
        p1, p2 = point_line(xb, xa, da), xb
    elif ka == "l" and kb == "l":
        p1, p2 = line_line(xa, da, xb, db)
    elif ka == "p" and kb == "pl":
        p1, p2 = xa, xa - db * float((xa - xb) @ db)
    elif ka == "pl" and kb == "p":
        p1, p2 = xb - da * float((xb - xa) @ da), xb
    elif ka == "l" and kb == "pl" and abs(float(da @ db)) < 1e-9:
        p1, p2 = xa, xa - db * float((xa - xb) @ db)
    elif ka == "pl" and kb == "l" and abs(float(db @ da)) < 1e-9:
        p1, p2 = xb - da * float((xb - xa) @ da), xb
    else:
        return None
    return float(np.linalg.norm(p2 - p1)), p1, p2


def _max_distance(a, b):
    """Largest distance between two circles / a circle and a point, sampled finely."""
    def samples(e):
        if e.type == "circle" and e.params:
            p = e.params
            n = unit(p["normal"])
            x = unit(np.asarray(p["start"]) - p["center"]) if not p.get("closed") else unit(np.cross(n, [1, 0, 0]) if abs(n[0]) < 0.9 else np.cross(n, [0, 1, 0]))
            y = np.cross(n, x)
            span = math.radians(p["angle"])
            t = np.linspace(0, span, 721)
            return p["center"] + p["radius"] * (np.outer(np.cos(t), x) + np.outer(np.sin(t), y))
        if e.point() is not None:
            return e.point()[None, :]
        return None

    sa, sb = samples(a), samples(b)
    if sa is None or sb is None:
        return None
    d = np.linalg.norm(sa[:, None, :] - sb[None, :, :], axis=2)
    i, j = np.unravel_index(int(d.argmax()), d.shape)
    return "Max distance", sa[i], sb[j]


# ---------------------------------------------------------------------------------------------- many entities
def many(ents):
    rows = []
    edges = [e for e in ents if e.kind == "edge"]
    faces = [e for e in ents if e.kind == "face"]
    if edges:
        rows.append({"label": "Total length", "value": float(sum(e.m.edge_length[e.index] for e in edges)),
                     "kind": "length", "primary": not faces})
    if faces:
        rows.append({"label": "Total area", "value": float(sum(face_area(e.m, e.index) for e in faces)),
                     "kind": "area", "primary": True})
    pts = [e.point() for e in ents if e.point() is not None]
    if len(pts) >= 2:
        path = float(sum(np.linalg.norm(np.asarray(pts[i + 1]) - pts[i]) for i in range(len(pts) - 1)))
        rows.append({"label": "Path length (points)", "value": path, "kind": "length"})
    rows.append({"label": "Items", "value": len(ents), "kind": "number"})
    return rows, []


def measure(model, selection, opts, exact_distance):
    ents = [Entity(model, s) for s in selection]
    if not ents:
        return {"rows": [], "graphics": []}
    if len(ents) == 1:
        rows, gfx = single(ents[0], opts)
    elif len(ents) == 2:
        rows, gfx = pair(ents[0], ents[1], opts, exact_distance)
        if not rows:
            rows = [{"label": "Distance", "value": None, "kind": "text"}]
    else:
        rows, gfx = many(ents)
    return {"rows": rows, "graphics": gfx, "labels": [e.label for e in ents]}
