"""The measure tool: what to report for a selection of faces, edges, vertices and picked points,
SolidWorks-style (distance, center distance, normal distance, angle, dX/dY/dZ, radius, area, …).

Distances between B-rep entities come from OpenCASCADE (exact); everything else from the
analytic data the loader worked out (plane normals, axes, circle centers). For mesh documents the
same questions are answered from the triangles.

Results are in mm and degrees; the browser formats them in the user's units. Each result row:
{"label", "value", "kind": "length" | "area" | "angle" | "number" | "point" | "text", "primary"?}
and graphics for the view: {"type": "line" | "point" | "axis", ...}.
"""

import numpy as np

from . import threads
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

    def center(self):
        """A circle / arc / sphere center, or a round flat face's (a disk or ring), else None."""
        p = self.params or {}
        if self.type in ("circle", "ellipse", "sphere") and p.get("center") is not None:
            return np.asarray(p["center"], np.float64)
        ring = self.ring()
        return ring[0] if ring else None

    def axis(self):
        """(point, direction) of a cylinder / cone / torus axis, or a circle's or ring's axis, else None."""
        p = self.params or {}
        if self.type in ("cylinder", "cone", "torus") and p.get("axis") is not None:
            return np.asarray(p["center"], np.float64), unit(p["axis"])
        if self.type in ("circle", "ellipse") and p.get("normal") is not None:
            return np.asarray(p["center"], np.float64), unit(p["normal"])
        ring = self.ring()
        return (ring[0], ring[1]) if ring else None

    def ring(self):
        """(center, normal, radius) of a flat face whose edge is mostly circles round one center (a disk, or
        a ring such as a bore's rim, where the radius is the inner circle's; small notches don't matter),
        else None."""
        if self.kind != "face" or self.type != "plane":
            return None
        cache = self.m.__dict__.setdefault("_rings", {})
        if self.index not in cache:
            m, found = self.m, None
            edges = [e for e, fs in enumerate(m.edge_faces) if self.index in fs and not m.edge_seam[e]]
            circles = [e for e in edges if m.edge_type[e] == "circle" and m.edge_params[e]]
            if circles:
                big = max(circles, key=lambda e: m.edge_params[e]["radius"])
                c0 = np.asarray(m.edge_params[big]["center"], np.float64)
                tol = 1e-4 * max(m.edge_params[big]["radius"], 1)
                ring = [e for e in circles if np.linalg.norm(np.asarray(m.edge_params[e]["center"], np.float64) - c0) < tol]
                if sum(m.edge_length[e] for e in ring) >= 0.75 * sum(m.edge_length[e] for e in edges):
                    found = (c0, unit(self.params["normal"]), float(min(m.edge_params[e]["radius"] for e in ring)))
            cache[self.index] = found
        return cache[self.index]

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
        if self.type == "cone":
            return p.get("radius_max")
        ring = self.ring()
        return ring[2] if ring else p.get("radius")

    def radius_at(self, q):
        """The radius level with point q along the axis: a cone's grows from its apex (within the face's
        own range); everything else has one radius."""
        p = self.params or {}
        if self.type == "cone" and p.get("apex") is not None and p.get("half_angle"):
            r = float((np.asarray(q, np.float64) - p["apex"]) @ unit(p["axis"])) * np.tan(np.radians(p["half_angle"]))
            return float(np.clip(r, p.get("radius_min", r), p.get("radius_max", r)))
        return self.radius()

    def round(self):
        """A radius the measure tool can measure to its center or either tangent: a circle / arc edge, a
        cylindrical or conical face, or a flat disk or ring."""
        if not self.radius():
            return False
        if self.type == "circle":
            return self.center() is not None
        if self.type in ("cylinder", "cone"):
            return self.axis() is not None
        return self.ring() is not None


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
        _radius_rows(e, rows, gfx)
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
    _thread_rows(e, rows, gfx)
    if not any(r["label"] == "Thread" for r in rows):
        _radius_rows(e, rows, gfx)
    return rows, gfx


def _radius_rows(e, rows, gfx):
    """The radius of a smooth bend that has no radius of its own in the file: a spline, swept or offset
    face or edge, from the exact curvature (a fillet's spline is one radius all along; otherwise the
    radius at the picked spot and the range), a torus's tube (a fillet round a bend) or a cone at the
    picked height. Flat and straight things, and anything with no exact geometry, add nothing."""
    p = e.params or {}
    if e.kind == "face" and e.type == "torus" and p.get("minor_radius"):
        _lead_radius(rows, gfx, e, "Radius", float(p["minor_radius"]))
        return
    if e.kind == "face" and e.type == "cone":
        if e.pick is not None:
            _lead_radius(rows, gfx, e, "Radius here", float(e.radius_at(e.pick)))
        return
    bends = e.kind == "face" and e.type in ("bspline", "bezier", "surface", "revolution", "ruled") or \
        e.kind == "edge" and e.type not in (None, "line", "circle")
    if not bends or not hasattr(e.m, "exact_curvature"):
        return
    pts = e.m.face_triangles(e.index)[0] if e.kind == "face" else e.m.edge_points(e.index)
    if not len(pts):
        return
    size = float(np.linalg.norm(np.ptp(pts, axis=0))) or 1.0
    pts = pts[np.linspace(0, len(pts) - 1, min(len(pts), 80)).astype(int)]
    try:
        k = e.m.exact_curvature(e.kind, e.index, pts)
        other = None
        if e.kind == "face":
            k, other = k
        here = None
        if e.pick is not None:
            kp = e.m.exact_curvature(e.kind, e.index, e.pick[None, :])
            here = float(kp[0][0] if e.kind == "face" else kp[0])
    except Exception:  # a curvature gmsh can't work out must never stop the measurement
        return
    k = k[np.isfinite(k)]
    if not len(k):
        return
    FLAT = 1 / (1000 * size)  # gentler than this is straight, for this size of thing
    lo, hi = float(np.percentile(k, 2)), float(np.percentile(k, 98))  # the very ends can be noisy
    if hi < FLAT:
        return
    if hi - lo <= 0.01 * hi:  # one radius all along
        _lead_radius(rows, gfx, e, "Radius", 1 / float(np.median(k)))
    else:
        extra = [{"label": "Smallest radius", "value": 1 / hi, "kind": "length"}]
        if lo >= FLAT:
            extra.append({"label": "Largest radius", "value": 1 / lo, "kind": "length"})
        rows[0:0] = extra
        if here is not None and here >= FLAT:
            _lead_radius(rows, gfx, e, "Radius here", 1 / here)
        else:
            rows[0]["primary"] = True
            for r in rows[1:]:
                r["primary"] = False
    if other is not None:  # curved both ways: its gentler bend, unless it's a ball
        o = float(np.median(other[np.isfinite(other)]))
        if o >= 10 * FLAT and o < 0.99 * float(np.median(k)):
            rows.insert(1, {"label": "Other-way radius", "value": 1 / o, "kind": "length"})


def _lead_radius(rows, gfx, e, label, r):
    """Put a radius at the top of the rows, as the main answer, with its value on the part."""
    for row in rows:
        row["primary"] = False
    rows.insert(0, {"label": label, "value": r, "kind": "length", "primary": True})
    at = e.pick
    if at is None:
        pts = e.m.face_triangles(e.index)[0] if e.kind == "face" else e.m.edge_points(e.index)
        at = pts[int(np.argmin(np.linalg.norm(pts - pts.mean(axis=0), axis=1)))] if len(pts) else None
    if at is not None:
        gfx.append({"type": "radius", "p": at, "value": r})


def _thread_rows(e, rows, gfx):
    """Thread size for a round or helical face: a modelled thread's callout at the top, or for a plain
    hole what its diameter most likely is (tap drill, clearance, drill size). Rows marked "status" also
    show in the status bar."""
    if e.type not in threads.FREEFORM and e.type not in ("cylinder", "cone"):
        return
    try:
        th = threads.identify(e.m, e.index)
    except Exception:  # a thread guess must never stop the measurement
        th = None
    if not th:
        return
    if th["modelled"]:
        std = th["thread"]
        for r in rows:
            r["primary"] = False
        where = "tapped hole" if th["internal"] else "external" if th["internal"] is False else ""
        top = [{"label": "Thread", "value": f"{th['callout']} {where}".strip() if std else f"Non-standard ({th['pitch']:.3f} mm pitch)",
                "kind": "text", "primary": True, "status": True}]
        if std:
            top.append({"label": "Pitch", "value": threads.describe(std), "kind": "text", "status": True})
            if th["internal"] is not False:
                top.append({"label": "Tap drill", "value": std["tap_name"], "kind": "text"})
            top.append({"label": "Major diameter", "value": std["major"], "kind": "length"})
        if th["hand"] == "left":
            top.append({"label": "Hand", "value": "Left-hand", "kind": "text", "status": True})
        top += [{"label": "Thread length", "value": th["length"], "kind": "length"},
                {"label": "Modelled major", "value": th["major"], "kind": "length"},
                {"label": "Modelled minor", "value": th["minor"], "kind": "length"}]
        rows[:0] = top
        gfx.append({"type": "note", "p": th["center"], "text": top[0]["value"]})
        return
    if th.get("hole_wizard"):
        std = th["thread"]
        rows.insert(0, {"label": "Thread", "value": f"{std['callout']} tapped hole (Hole Wizard)", "kind": "text",
                        "primary": True, "status": True})
        for r in rows[1:]:
            r["primary"] = False
        at = next((i + 1 for i, r in enumerate(rows) if r["label"] == "Radius"), 1)
        rows[at:at] = [{"label": "Pitch", "value": threads.describe(std), "kind": "text", "status": True},
                       {"label": "Tap drill", "value": std["tap_name"], "kind": "text"}]
        gfx.append({"type": "note", "p": e.m.face_params[e.index]["center"], "text": f"{std['callout']} tapped"})
        return
    if th.get("taper"):
        rows.insert(0, {"label": "Thread", "value": th["callout"], "kind": "text", "primary": True, "status": True})
        gfx.append({"type": "note", "p": e.m.face_params[e.index]["center"], "text": th["callout"]})
        return
    likely = th.get("likely") or []
    at = next((i + 1 for i, r in enumerate(rows) if r["label"] == "Radius"), 1)
    extra = [{"label": "Likely", "value": likely[0], "kind": "text", "status": True}] if likely else []
    extra += [{"label": "Could be", "value": x, "kind": "text"} for x in likely[1:3]]
    rows[at:at] = extra


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
    pa, pb = a.point(), b.point()
    modes = arc_modes((a, b), opts)

    # 1. the main distance
    main = _arc_distance(a, b, modes) if any(modes) else None
    if main is None and pa is not None and pb is not None:
        main = ("Distance", pa, pb)
    if main is None:
        res = exact_distance(a, b)
        if res is not None:
            d, p1, p2 = res
            main = ("Distance", p1, p2)
    if main is not None:
        label, p1, p2 = main
        d = float(np.linalg.norm(p2 - p1))
        rows.append({"label": label, "value": d, "kind": "length", "primary": True})
        delta = p2 - p1
        rows += [{"label": "dX", "value": abs(delta[0]), "kind": "length", "axis": "x"},
                 {"label": "dY", "value": abs(delta[1]), "kind": "length", "axis": "y"},
                 {"label": "dZ", "value": abs(delta[2]), "kind": "length", "axis": "z"}]
        gfx.append({"type": "line", "p1": p1, "p2": p2, "value": d, "xyz": True})

    # 2. center distance for round things (when the main distance wasn't already that)
    if main is None or main[0] != "Center distance":
        cd = _center_distance(a, b)
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


def arc_modes(ents, opts):
    """Where each round item is measured from: "center" (centerline), "min" (close tangent) or "max"
    (far tangent); None for items that aren't round. opts["arcs"] picks per item; otherwise
    opts["arc"] applies, except that round faces start at the close tangent, the way SolidWorks
    measures faces, while arcs start at the center. A flat disk or ring (a bore's rim) only counts as
    round next to another round item; against a corner or a flat face it measures as the face it is."""
    picked = list(opts.get("arcs") or [])
    default = opts.get("arc", "center")
    other_round = [e.round() and e.ring() is None for e in ents]
    out = []
    for i, e in enumerate(ents):
        if not e.round() or (e.ring() is not None and not any(r for j, r in enumerate(other_round) if j != i)):
            out.append(None)
            continue
        mode = picked[i] if i < len(picked) else None
        if mode not in ("center", "min", "max"):
            mode = "min" if e.kind == "face" and default == "center" else default
        out.append(mode)
    return out


def _as_geom(e):
    """The entity as a point ("p"), line ("l") or plane ("pl") for center measurements, else None."""
    if e.center() is not None:
        return "p", e.center(), None
    if e.type in ("cylinder", "cone") and e.axis() is not None:
        return "l", *e.axis()
    if e.point() is not None:
        return "p", e.point(), None
    if e.plane() is not None:
        return "pl", *e.plane()
    if e.line() is not None:
        return "l", *e.line()
    return None


def _closest(ga, gb):
    """Closest points between two of _as_geom's points / lines / planes, or None (a plane and a line
    or plane that crosses it)."""
    (ka, xa, da), (kb, xb, db) = ga, gb
    if ka == "p" and kb == "p":
        return xa, xb
    if ka == "p" and kb == "l":
        return xa, point_line(xa, xb, db)
    if ka == "l" and kb == "p":
        return point_line(xb, xa, da), xb
    if ka == "l" and kb == "l":
        return line_line(xa, da, xb, db)
    if ka == "p" and kb == "pl":
        return xa, xa - db * float((xa - xb) @ db)
    if ka == "pl" and kb == "p":
        return xb - da * float((xb - xa) @ da), xb
    if ka == "l" and kb == "pl" and abs(float(da @ db)) < 1e-9:
        return xa, xa - db * float((xa - xb) @ db)
    if ka == "pl" and kb == "l" and abs(float(db @ da)) < 1e-9:
        return xb - da * float((xb - xa) @ da), xb
    return None


def _foot(g, q):
    """The point of geometry g nearest to q."""
    k, x, d = g
    if k == "p":
        return x
    if k == "l":
        return point_line(q, x, d)
    return q - d * float((q - x) @ d)


def _center_distance(a, b):
    """Center-to-center / axis-to-axis / center-to-plane distance when either side is round."""
    ra = a.center() is not None or (a.axis() is not None and a.type in ("cylinder", "cone"))
    rb = b.center() is not None or (b.axis() is not None and b.type in ("cylinder", "cone"))
    if not (ra or rb):
        return None
    ga, gb = _as_geom(a), _as_geom(b)
    if ga is None or gb is None:
        return None
    res = _closest(ga, gb)
    if res is None:
        return None
    p1, p2 = res
    return float(np.linalg.norm(p2 - p1)), p1, p2


def _arc_distance(a, b, modes):
    """The distance with each round item measured from its centerline, close tangent or far tangent.
    Starts from the center / axis measurement, then slides each tangent end out by the radius, across
    the circle's plane or the hole's axis, towards (close) or away from (far) the other end. For two
    holes side by side that's the center distance minus or plus each radius."""
    ga, gb = _as_geom(a), _as_geom(b)
    if ga is None or gb is None:
        return None
    res = _closest(ga, gb)
    if res is None:
        return None
    centers, ends = list(res), list(res)
    geoms, ents = (ga, gb), (a, b)
    for _ in range(4 if any(m in ("min", "max") for m in modes) else 0):  # skewed circles take a few rounds
        for i in (0, 1):
            if modes[i] not in ("min", "max"):
                continue
            e, j = ents[i], 1 - i
            n = e.axis()[1]
            v = ends[j] - centers[i]
            v = v - n * float(v @ n)
            if np.linalg.norm(v) > 1e-12:
                ends[i] = centers[i] + (1 if modes[i] == "min" else -1) * e.radius_at(centers[i]) * unit(v)
            if modes[j] is None or (modes[j] == "center" and geoms[j][0] == "l"):
                ends[j] = _foot(geoms[j], ends[i])  # the other side's nearest point to the new end
    label = "Center distance" if all(m in (None, "center") for m in modes) else "Distance"
    return label, ends[0], ends[1]


# ---------------------------------------------------------------------------------------------- many entities
def from_radius(ents, opts, exact_distance):
    """A hole or arc and two or more other items: the distance from the radius (its close tangent,
    centerline or far tangent) to each of the others, and with two others how far off center it
    sits between them. None when nothing in the selection is round."""
    modes = arc_modes(ents, opts)
    hub = next((i for i, mo in enumerate(modes) if mo), None)
    if hub is None:
        return None
    rows, gfx, dists = [], [], []
    for j, e in enumerate(ents):
        if j == hub:
            continue
        main = _arc_distance(ents[hub], e, [modes[hub], modes[j]])
        if main is None:
            res = exact_distance(ents[hub], e)
            main = res and ("Distance", res[1], res[2])
        if main is None:
            rows.append({"label": f"To {e.label}", "value": "—", "kind": "text"})
            continue
        _, p1, p2 = main
        d = float(np.linalg.norm(p2 - p1))
        dists.append(d)
        rows.append({"label": f"To {e.label}", "value": d, "kind": "length", "primary": True})
        gfx.append({"type": "line", "p1": p1, "p2": p2, "value": d})
    if len(dists) == 2 and len(ents) == 3:
        rows.append({"label": "Difference", "value": abs(dists[0] - dists[1]), "kind": "length"})
        rows.append({"label": "Off center", "value": abs(dists[0] - dists[1]) / 2, "kind": "length"})
    return rows, gfx


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
        return {"rows": rows, "graphics": gfx, "labels": [e.label for e in ents]}
    if len(ents) == 2:
        rows, gfx = pair(ents[0], ents[1], opts, exact_distance)
        if not rows:
            rows = [{"label": "Distance", "value": None, "kind": "text"}]
        return {"rows": rows, "graphics": gfx, "labels": [e.label for e in ents], "arcs": arc_modes(ents, opts)}
    res = from_radius(ents, opts, exact_distance)
    if res is not None:
        rows, gfx = res
        return {"rows": rows, "graphics": gfx, "labels": [e.label for e in ents], "arcs": arc_modes(ents, opts)}
    rows, gfx = many(ents)
    return {"rows": rows, "graphics": gfx, "labels": [e.label for e in ents]}
