"""PRC's exact geometry section (ISO 14739-1): bodies of faces, loops and edges on real curves and surfaces, plain or in the
compressed form CAD writers favour. Reading only: curves and surfaces can give their points, and meshing is brepmesh.py's.

Field orders come from prc-rs's schema (MIT) and ISO 14739-1's errata threads, and each was checked by walking every section
of 257 sample files to its end. What a stored number means was checked against those files' vertices where they let it be.
Iso faces in compressed bodies store no surface at all, just their boundary, so they are rebuilt from it (see `rebuilt`).
"""

import math

import numpy as np

from ..surfaces import curve_points, expand_knots, surface_points
from .bits import PrcError
from .schema import extend
from .tree import _transform_3d, _user_data, _vector, attributes, name_of

TYPE_GEOMETRY = 306
TOPO_CONTEXT, TOPO_MULTIPLE_VERTEX, TOPO_UNIQUE_VERTEX, TOPO_WIRE_EDGE, TOPO_EDGE, TOPO_COEDGE = 141, 143, 144, 145, 146, 147
TOPO_LOOP, TOPO_FACE, TOPO_SHELL, TOPO_CONNEX, TOPO_BODY = 148, 149, 150, 151, 152
TOPO_WIRE_BODY, TOPO_BREP, TOPO_WIRE_COMPRESSED, TOPO_BREP_COMPRESSED = 153, 154, 155, 156
CRV_BLEND02, CRV_NURBS, CRV_CIRCLE, CRV_COMPOSITE, CRV_ON_SURFACE, CRV_ELLIPSE, CRV_EQUATION, CRV_HELIX = 12, 13, 14, 15, 16, 17, 18, 19
CRV_HYPERBOLA, CRV_INTERSECTION, CRV_LINE, CRV_OFFSET, CRV_PARABOLA, CRV_POLYLINE, CRV_TRANSFORM = 20, 21, 22, 23, 24, 25, 26
SURF_BLEND01, SURF_BLEND02, SURF_BLEND03, SURF_NURBS, SURF_CONE, SURF_CYLINDER, SURF_CYLINDRICAL = 77, 78, 79, 80, 81, 82, 83
SURF_OFFSET, SURF_PIPE, SURF_PLANE, SURF_RULED, SURF_SPHERE, SURF_REVOLUTION, SURF_EXTRUSION = 84, 85, 86, 87, 88, 89, 90
SURF_FROM_CURVES, SURF_TORUS, SURF_TRANSFORM = 91, 92, 93
MATH_POLYNOM, MATH_TRIG, MATH_FRACTION, MATH_ARCTAN_COS, MATH_COMBINATION, MATH_LINEAR, MATH_NONLINEAR = 902, 903, 904, 905, 906, 911, 912
TAU = 2 * math.pi
MAX_NEST = 256


def _apply(matrix, points):
    return points if matrix is None else points @ matrix[:3, :3].T + matrix[:3, 3]


# ---------------------------------------------------------------------------------------------- curves
class Curve:
    """Points at parameters, over t0..t1. `straight` lets the mesher take just the ends."""
    t0, t1 = 0.0, 1.0
    straight = False

    def at(self, t):
        raise NotImplementedError


class Param(Curve):
    """A curve with a transformation and a parameterisation: the point at t is the shape's at a * t + b."""

    def __init__(self, matrix, t0, t1, a, b):
        self.matrix, self.t0, self.t1, self.a, self.b = matrix, t0, t1, a, b

    def local(self, s):
        raise NotImplementedError

    def at(self, t):
        return _apply(self.matrix, self.local(self.a * np.asarray(t, float) + self.b))


class Line(Param):
    straight = True

    def local(self, s):
        return np.column_stack([s, np.zeros_like(s), np.zeros_like(s)])


class Ellipse(Param):
    def __init__(self, matrix, t0, t1, a, b, rx, ry):
        super().__init__(matrix, t0, t1, a, b)
        self.rx, self.ry = rx, ry

    def local(self, s):
        return np.column_stack([self.rx * np.cos(s), self.ry * np.sin(s), np.zeros_like(s)])


class Hyperbola(Ellipse):
    def local(self, s):
        return np.column_stack([self.rx * np.cosh(s), self.ry * np.sinh(s), np.zeros_like(s)])


class Parabola(Param):
    def __init__(self, matrix, t0, t1, a, b, focal):
        super().__init__(matrix, t0, t1, a, b)
        self.focal = focal

    def local(self, s):
        return np.column_stack([s * s / (4 * self.focal), s, np.zeros_like(s)])


class Polyline(Param):
    def __init__(self, matrix, t0, t1, a, b, points):
        super().__init__(matrix, t0, t1, a, b)
        self.points = np.asarray(points, float).reshape(-1, 3)

    def local(self, s):
        p = self.points
        s = np.clip(s, 0, len(p) - 1)
        k = np.minimum(s.astype(int), max(len(p) - 2, 0))
        f = (s - k)[:, None]
        return p[k] * (1 - f) + p[np.minimum(k + 1, len(p) - 1)] * f


class ThroughPoints(Curve):
    """Curves the file defines implicitly (the crossing of two surfaces): what it does store is points along them."""

    def __init__(self, points):
        self.points = np.asarray(points, float).reshape(-1, 3)

    def at(self, t):
        p = self.points
        s = np.clip(np.asarray(t, float), 0.0, 1.0) * (len(p) - 1)
        k = np.minimum(s.astype(int), max(len(p) - 2, 0))
        f = (s - k)[:, None]
        return p[k] * (1 - f) + p[np.minimum(k + 1, len(p) - 1)] * f


class Nurbs(Curve):
    def __init__(self, degree, control, knots, weights):
        self.degree, self.control, self.knots, self.weights = degree, control, knots, weights
        self.t0, self.t1 = float(knots[degree]), float(knots[len(control)])

    def at(self, t):
        return curve_points(self.knots, self.degree, self.control, t, self.weights)


class Composite(Param):
    """Sub-curves one after another, each given an equal share of the parameter."""

    def __init__(self, matrix, t0, t1, a, b, parts):
        super().__init__(matrix, t0, t1, a, b)
        self.parts = parts

    def local(self, s):
        span = (self.t1 - self.t0) or 1.0
        f = np.clip((np.asarray(s) - self.t0) / span, 0.0, 1.0) * len(self.parts)
        k = np.minimum(f.astype(int), len(self.parts) - 1)
        out = np.zeros((len(f), 3))
        for i, (curve, forward) in enumerate(self.parts):
            here = k == i
            if here.any():
                w = f[here] - i
                out[here] = curve.at(curve.t0 + (curve.t1 - curve.t0) * (w if forward else 1 - w))
        return out

    def at(self, t):
        return _apply(self.matrix, self.local(np.asarray(t, float)))


class OnSurface(Param):
    def __init__(self, matrix, t0, t1, a, b, uv, surface):
        super().__init__(matrix, t0, t1, a, b)
        self.uv, self.surface = uv, surface

    def local(self, s):
        q = self.uv.at(self.uv.t0 + (self.uv.t1 - self.uv.t0) * (s - self.t0) / ((self.t1 - self.t0) or 1.0))
        return self.surface.at(q[:, 0], q[:, 1])


class Offset(Param):
    def __init__(self, matrix, t0, t1, a, b, base, normal, distance):
        super().__init__(matrix, t0, t1, a, b)
        self.base, self.normal, self.distance = base, np.array(normal, float), distance

    def local(self, s):
        h = (self.base.t1 - self.base.t0) * 1e-5 or 1e-5
        p = self.base.at(s)
        tangent = self.base.at(s + h) - self.base.at(s - h)
        side = np.cross(self.normal, tangent)
        size = np.linalg.norm(side, axis=1, keepdims=True)
        size[size == 0] = 1.0
        return p + self.distance * side / size


# compressed curves: ends are always known
class Segment(Curve):
    straight = True

    def __init__(self, start, end):
        self.start, self.end = np.asarray(start, float), np.asarray(end, float)

    def at(self, t):
        t = np.asarray(t, float)[:, None]
        return self.start * (1 - t) + self.end * t


class Arc(Curve):
    """start turned about center and axis by up to `sweep`."""

    def __init__(self, start, center, axis, sweep):
        self.start, self.center, self.sweep = np.asarray(start, float), np.asarray(center, float), sweep
        size = np.linalg.norm(axis)
        self.axis = np.asarray(axis, float) / (size or 1.0)
        self.end = self.at(np.array([1.0]))[0]

    def at(self, t):
        a = np.asarray(t, float) * self.sweep
        r = self.start - self.center
        return self.center + np.outer(np.cos(a), r) + np.outer(np.sin(a), np.cross(self.axis, r))


def _arc_through(start, middle, end):
    """The circle through three points, or a line if they're in a row."""
    a, b, c = (np.asarray(p, float) for p in (start, middle, end))
    ab, ac = b - a, c - a
    normal = np.cross(ab, ac)
    area = float(normal @ normal)
    if area < 1e-30:
        return Segment(a, c)
    center = a + np.cross(ab @ ab * ac - ac @ ac * ab, normal) / (2 * area)
    r0, r1, r2 = a - center, b - center, c - center
    first = math.atan2(float(np.cross(r0, r1) @ normal) / math.sqrt(area), float(r0 @ r1))
    sweep = math.atan2(float(np.cross(r0, r2) @ normal) / math.sqrt(area), float(r0 @ r2))
    if first < 0:
        first += TAU
    if sweep < first:
        sweep += TAU
    return Arc(a, center, normal, sweep)


def _arc_about(start, end, center, big):
    a, b, c = (np.asarray(p, float) for p in (start, end, center))
    r0, r1 = a - c, b - c
    normal = np.cross(r0, r1)
    if float(normal @ normal) < 1e-30:  # half a circle has no plane to go by: a line stands in for it if nothing else does
        return Segment(a, b)
    sweep = math.atan2(float(np.linalg.norm(normal)), float(r0 @ r1))
    if big:
        normal, sweep = -normal, TAU - sweep
    arc = Arc(a, c, normal, sweep)
    arc.end = b
    return arc


class Hermite(Curve):
    """Cubic pieces through points, the tangents being their handles (each piece's control points are P, P + t, Q - t', Q)."""

    def __init__(self, points, handles):
        self.points, self.handles = np.asarray(points, float), np.asarray(handles, float)
        self.start, self.end = self.points[0], self.points[-1]

    def at(self, t):
        count = len(self.points) - 1
        s = np.clip(np.asarray(t, float), 0.0, 1.0) * count
        k = np.minimum(s.astype(int), count - 1)
        f = (s - k)[:, None]
        p, q, a, b = self.points[k], self.points[k + 1], self.handles[k], self.handles[k + 1]
        g = 1 - f
        return g * g * g * p + 3 * g * g * f * (p + a) + 3 * g * f * f * (q - b) + f * f * f * q


class Chain(Curve):
    """Curves joined in order, for a compressed composite: each equal share."""

    def __init__(self, parts):
        self.parts = parts
        self.start, self.end = parts[0].start, parts[-1].end

    def at(self, t):
        f = np.clip(np.asarray(t, float), 0.0, 1.0) * len(self.parts)
        k = np.minimum(f.astype(int), len(self.parts) - 1)
        out = np.zeros((len(f), 3))
        for i, part in enumerate(self.parts):
            here = k == i
            if here.any():
                out[here] = part.at(f[here] - i)
        return out


class IsoShift(Curve):
    """A side of a patch on a known surface: the side across from it, moved along the surface's parameters to start at `start`."""

    def __init__(self, surface, curve, start, end):
        self.surface, self.curve, self.start, self.end = surface, curve, np.asarray(start, float), np.asarray(end, float)
        self.anchor = surface.invert(self.start[None, :])

    def at(self, t):
        t = np.asarray(t, float)
        u, v, _pole = self.surface.invert(self.curve.at(np.concatenate([[0.0], t])))
        p, q = self.surface.period
        u = np.unwrap(u, period=p) if p else u
        v = np.unwrap(v, period=q) if q else v
        return self.surface.at(u[1:] - u[0] + self.anchor[0][0], v[1:] - v[0] + self.anchor[1][0])


class Deduced(Curve):
    """An iso face's trim that isn't stored: worked out once the face is read, and maybe named by faces after it."""
    start = end = None
    source = None

    def at(self, t):
        return self.source.at(t)

    def become(self, source):
        self.source, self.start, self.end = source, source.start, source.end
        self.straight = getattr(source, "straight", False)


class Similar(Curve):
    """A curve moved, turned the least way and scaled so its ends land on two given points: the side of a patch opposite it,
    all the kinds of iso surface having the same family of curve across them."""

    def __init__(self, curve, start, end):
        self.curve, self.start, self.end = curve, np.asarray(start, float), np.asarray(end, float)
        self.straight = getattr(curve, "straight", False)
        a, b = curve.start, curve.end
        was, now = b - a, self.end - self.start
        size_was, size_now = float(np.linalg.norm(was)), float(np.linalg.norm(now))
        self.scale = size_now / size_was if size_was > 0 else 1.0
        self.turn = _least_turn(was / size_was, now / size_now) if size_was > 0 and size_now > 0 else np.eye(3)
        self.origin = a

    def at(self, t):
        return (self.curve.at(t) - self.origin) @ self.turn.T * self.scale + self.start


def _least_turn(a, b):
    """The rotation taking unit a to unit b that moves everything else least."""
    v = np.cross(a, b)
    c = float(a @ b)
    if c < -1 + 1e-9:
        return np.eye(3)  # the far way round has no one answer
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k / (1 + c)


# ---------------------------------------------------------------------------------------------- surfaces
class Surface:
    """Points at (u, v), the parameters as stored. `period` is how far each runs before it repeats, or 0; `flip` says when
    u cross v points opposite the surface's own normal."""
    flip = False
    period = (0.0, 0.0)
    domain = None  # (umin, vmin, umax, vmax)
    planar = False

    def at(self, u, v):
        raise NotImplementedError

    def invert(self, points):
        """(u, v, pole) of points on the surface, or None if it has no direct way. `pole`: where u means nothing."""
        return None


class Analytic(Surface):
    """Plane, cylinder, cone, sphere or torus in its own frame, with the parameterisation they share."""

    def __init__(self, matrix, swap, domain, ua, va, ub, vb):
        self.matrix = np.eye(4) if matrix is None else matrix
        self.swap, self.domain, self.ua, self.va, self.ub, self.vb = swap, domain, ua or 1.0, va or 1.0, ub, vb
        self.inverse = np.linalg.inv(self.matrix) if abs(np.linalg.det(self.matrix)) > 1e-300 else None
        periods = self.canonical_period
        self.period = (periods[1] / abs(self.ua), periods[0] / abs(self.va)) if swap else (periods[0] / abs(self.ua), periods[1] / abs(self.va))
        self.flip = bool(swap) ^ (self.ua * self.va < 0) ^ (np.linalg.det(self.matrix[:3, :3]) < 0)

    canonical_period = (0.0, 0.0)

    def local(self, a, b):
        raise NotImplementedError

    def angles(self, q):
        """(a, b, pole) of points in the local frame."""
        raise NotImplementedError

    def at(self, u, v):
        big_u, big_v = self.ua * np.asarray(u, float) + self.ub, self.va * np.asarray(v, float) + self.vb
        a, b = (big_v, big_u) if self.swap else (big_u, big_v)
        return _apply(self.matrix, self.local(a.ravel(), b.ravel()))

    def invert(self, points):
        if self.inverse is None:
            return None
        a, b, pole = self.angles(_apply(self.inverse, np.asarray(points, float)))
        big_u, big_v = (b, a) if self.swap else (a, b)
        return (big_u - self.ub) / self.ua, (big_v - self.vb) / self.va, pole


class Plane(Analytic):
    planar = True

    def local(self, a, b):
        return np.column_stack([a, b, np.zeros_like(a)])

    def angles(self, q):
        return q[:, 0], q[:, 1], np.zeros(len(q), bool)


class Cylinder(Analytic):
    canonical_period = (TAU, 0.0)

    def __init__(self, matrix, swap, domain, ua, va, ub, vb, radius):
        self.radius = radius
        super().__init__(matrix, swap, domain, ua, va, ub, vb)

    def local(self, a, b):
        return np.column_stack([self.radius * np.cos(a), self.radius * np.sin(a), b])

    def angles(self, q):
        return np.arctan2(q[:, 1], q[:, 0]), q[:, 2], np.zeros(len(q), bool)


class Cone(Analytic):
    canonical_period = (TAU, 0.0)

    def __init__(self, matrix, swap, domain, ua, va, ub, vb, radius, slope):
        self.radius, self.slope = radius, slope
        super().__init__(matrix, swap, domain, ua, va, ub, vb)

    def local(self, a, b):
        r = self.radius + b * self.slope
        return np.column_stack([r * np.cos(a), r * np.sin(a), b])

    def angles(self, q):
        b = q[:, 2]
        r = self.radius + b * self.slope
        sign = np.where(r < 0, -1.0, 1.0)  # past the apex the radius is negative: the point is across the axis
        size = np.hypot(q[:, 0], q[:, 1])
        return np.arctan2(q[:, 1] * sign, q[:, 0] * sign), b, size < 1e-9 * max(abs(self.radius), float(np.abs(b).max()), 1e-30)


class Sphere(Analytic):
    canonical_period = (TAU, 0.0)

    def __init__(self, matrix, swap, domain, ua, va, ub, vb, radius):
        self.radius = radius
        super().__init__(matrix, swap, domain, ua, va, ub, vb)

    def local(self, a, b):
        r = self.radius
        return np.column_stack([r * np.cos(b) * np.cos(a), r * np.cos(b) * np.sin(a), r * np.sin(b)])

    def angles(self, q):
        size = np.hypot(q[:, 0], q[:, 1])
        return np.arctan2(q[:, 1], q[:, 0]), np.arctan2(q[:, 2], size), size < 1e-6 * abs(self.radius)


class Torus(Analytic):
    canonical_period = (TAU, TAU)

    def __init__(self, matrix, swap, domain, ua, va, ub, vb, major, minor):
        self.major, self.minor = major, minor
        super().__init__(matrix, swap, domain, ua, va, ub, vb)

    def local(self, a, b):
        r = self.major + self.minor * np.cos(b)
        return np.column_stack([r * np.cos(a), r * np.sin(a), self.minor * np.sin(b)])

    def angles(self, q):
        a = np.arctan2(q[:, 1], q[:, 0])
        return a, np.arctan2(q[:, 2], np.hypot(q[:, 0], q[:, 1]) - self.major), np.zeros(len(q), bool)


class Swept(Analytic):
    """A surface that has no way back from a point to its parameters: the mesher searches for them."""

    def invert(self, points):
        return None


class Extrusion(Swept):
    def __init__(self, matrix, swap, domain, ua, va, ub, vb, sweep, base):
        self.sweep, self.base = np.array(sweep, float), base
        super().__init__(matrix, swap, domain, ua, va, ub, vb)

    def local(self, a, b):
        return self.base.at(a) + np.outer(b, self.sweep)


class Revolution(Swept):
    canonical_period = (TAU, 0.0)

    def __init__(self, matrix, swap, domain, ua, va, ub, vb, origin, x, y, base):
        self.origin, self.base = np.array(origin, float), base
        z = np.cross(x, y)
        self.axis = z / (np.linalg.norm(z) or 1.0)
        super().__init__(matrix, swap, domain, ua, va, ub, vb)

    def local(self, a, b):
        d = self.base.at(b) - self.origin
        along = (d @ self.axis)[:, None] * self.axis
        out = d - along
        return self.origin + along + out * np.cos(a)[:, None] + np.cross(self.axis, out) * np.sin(a)[:, None]


class Ruled(Swept):
    def __init__(self, matrix, swap, domain, ua, va, ub, vb, first, second):
        self.first, self.second = first, second
        super().__init__(matrix, swap, domain, ua, va, ub, vb)

    def local(self, a, b):
        f = b[:, None]
        return self.first.at(a) * (1 - f) + self.second.at(a) * f


class FromCurves(Swept):
    def __init__(self, matrix, swap, domain, ua, va, ub, vb, origin, first, second):
        self.origin, self.first, self.second = np.array(origin, float), first, second
        super().__init__(matrix, swap, domain, ua, va, ub, vb)

    def local(self, a, b):
        return self.first.at(a) + self.second.at(b) - self.origin


class OffsetSurface(Swept):
    def __init__(self, matrix, swap, domain, ua, va, ub, vb, base, distance):
        self.base, self.distance = base, distance
        super().__init__(matrix, swap, domain, ua, va, ub, vb)

    def local(self, a, b):
        d = self.base.domain
        hu, hv = (abs(d[2] - d[0]) or 1.0) * 1e-5, (abs(d[3] - d[1]) or 1.0) * 1e-5
        n = np.cross(self.base.at(a + hu, b) - self.base.at(a - hu, b), self.base.at(a, b + hv) - self.base.at(a, b - hv))
        size = np.linalg.norm(n, axis=1, keepdims=True)
        size[size == 0] = 1.0
        return self.base.at(a, b) + self.distance * n / size


class Unevaluated(Surface):
    """Stored, but with no known formula (the rolling-ball blends): faces on it are built from their edges."""

    def at(self, u, v):
        raise PrcError("This surface has no formula.")


class NurbsSurface(Surface):
    def __init__(self, degree_u, degree_v, control, knots_u, knots_v, weights):
        self.degree_u, self.degree_v, self.control, self.knots_u, self.knots_v = degree_u, degree_v, control, knots_u, knots_v
        self.weights = weights
        nu, nv = control.shape[:2]
        self.domain = (float(knots_u[degree_u]), float(knots_v[degree_v]), float(knots_u[nu]), float(knots_v[nv]))
        a, b, c, d = self.domain
        size = max(float(np.ptp(control.reshape(-1, 3), axis=0).max()), 1e-30)
        self.period = (c - a if np.abs(control[0] - control[-1]).max() < size * 1e-7 else 0.0,
                       d - b if np.abs(control[:, 0] - control[:, -1]).max() < size * 1e-7 else 0.0)

    def at(self, u, v):
        u, v = np.asarray(u, float).ravel(), np.asarray(v, float).ravel()
        a, b, c, d = self.domain
        if self.period[0]:
            u = a + np.mod(u - a, c - a + 1e-300 + 0.0) if (u.min() < a or u.max() > c) else u
        if self.period[1]:
            v = b + np.mod(v - b, d - b + 1e-300 + 0.0) if (v.min() < b or v.max() > d) else v
        return surface_points(self.knots_u, self.degree_u, self.knots_v, self.degree_v, self.control, u, v, self.weights)


# ---------------------------------------------------------------------------------------------- topology
class Edge:
    __slots__ = ("curve", "interval", "start", "end", "polyline")

    def __init__(self):
        self.curve = self.interval = self.start = self.end = self.polyline = None


class CoEdge:
    __slots__ = ("edge", "uv", "forward")


class Loop:
    __slots__ = ("direction", "coedges")


class Face:
    __slots__ = ("surface", "domain", "outer", "loops")


class Shell:
    __slots__ = ("closed", "faces")


class Connex:
    __slots__ = ("shells",)


class Brep:
    """A body: its shells, each [(face, orientation)] where orientation 0 turns the face over, 1 keeps it, 2 doesn't say."""

    def __init__(self, shells, points):
        self.shells, self.points = shells, points


class AnaFace:
    """A compressed face on a surface named by its axes alone, with its trim as loops of 3D curves. `make` builds the surface
    once points on it are known, since sizes aren't stored."""
    __slots__ = ("make", "keep", "loops", "extra")

    def __init__(self, make, keep, loops, extra=None):
        self.make, self.keep, self.loops, self.extra = make, keep, loops, extra


class PatchFace:
    """A compressed iso face: four sides, the surface being what they span."""
    __slots__ = ("kind", "keep", "sides")

    def __init__(self, kind, keep, sides):
        self.kind, self.keep, self.sides = kind, keep, sides


class WholeFace:
    """A compressed face that's a whole NURBS or other surface, untrimmed."""
    __slots__ = ("surface", "keep")

    def __init__(self, surface, keep):
        self.surface, self.keep = surface, keep


class Context:
    def __init__(self):
        self.scale = 1.0
        self.tolerance = 0.0
        self.bodies = []


# ---------------------------------------------------------------------------------------------- reading: plain parts
def _bits_then(b):
    return b.read(b.read(5))


def _base_topology(b):
    if b.bit():
        attributes(b)
        name_of(b)
        b.u()


def _content_geometry(b):
    """What a curve or surface starts with."""
    if b.bit():
        attributes(b)
        name_of(b)
        b.u()
    b.u()  # how it may be extended


def _domain(b):
    return b.double(), b.double(), b.double(), b.double()


class _Tables:
    """A context's numbered entities. An entity takes its number before its fields are read; references count from 1 and may
    name something in an earlier body."""

    def __init__(self):
        self.topology, self.curves, self.surfaces = [], [], []
        self.points = []
        self.loose = False  # inside a compressed body, surfaces name the body's other faces, which aren't in these tables


def _pick(table, ref, what, loose=False):
    if not 0 < ref <= len(table):
        if loose:
            return None
        raise PrcError(f"A reference to a {what} in the PRC geometry goes nowhere ({ref} of {len(table)}).")
    return table[ref - 1]


def _ptr_topology(b, t):
    if b.bit():
        return _pick(t.topology, b.u(), "topological entity", t.loose)
    tag = b.u()
    if tag == 0:
        return None
    if tag == TOPO_UNIQUE_VERTEX:
        slot = len(t.topology)
        t.topology.append(None)
        _base_topology(b)
        p = np.array(_vector(b))
        if b.bit():
            b.double()
        t.points.append(p)
        t.topology[slot] = p
        return p
    if tag == TOPO_MULTIPLE_VERTEX:
        slot = len(t.topology)
        t.topology.append(None)
        _base_topology(b)
        p = None
        for _ in range(b.u()):
            q = np.array(_vector(b))
            p = q if p is None else p
        if p is not None:
            t.points.append(p)
        t.topology[slot] = p
        return p
    if tag in (TOPO_EDGE, TOPO_WIRE_EDGE):
        e = Edge()
        t.topology.append(e)
        _base_topology(b)
        e.curve = _ptr_curve(b, t)
        if b.bit():
            e.interval = (b.double(), b.double())
        if tag == TOPO_EDGE:
            e.start, e.end = _ptr_topology(b, t), _ptr_topology(b, t)
            if b.bit():
                b.double()
        return e
    if tag == TOPO_COEDGE:
        c = CoEdge()
        t.topology.append(c)
        _base_topology(b)
        c.edge = _ptr_topology(b, t)
        c.uv = _ptr_curve(b, t)
        c.forward = b.read(8) != 0
        b.read(8)
        return c
    if tag == TOPO_LOOP:
        loop = Loop()
        t.topology.append(loop)
        _base_topology(b)
        loop.direction = b.read(8)
        loop.coedges = []
        for _ in range(b.u()):
            c = _ptr_topology(b, t)
            b.u()  # its neighbour's place
            if c is not None:
                loop.coedges.append(c)
        return loop
    if tag == TOPO_FACE:
        f = Face()
        t.topology.append(f)
        _base_topology(b)
        f.surface = _ptr_surface(b, t)
        f.domain = _domain(b) if b.bit() else None
        if b.bit():
            b.double()
        n = b.u()
        f.outer = b.i32()
        f.loops = [x for x in (_ptr_topology(b, t) for _ in range(n)) if x is not None]
        return f
    if tag == TOPO_SHELL:
        s = Shell()
        t.topology.append(s)
        _base_topology(b)
        s.closed = b.bit()
        s.faces = []
        for _ in range(b.u()):
            f = _ptr_topology(b, t)
            how = b.read(8)
            if f is not None:
                s.faces.append((f, how))
        return s
    if tag == TOPO_CONNEX:
        c = Connex()
        t.topology.append(c)
        _base_topology(b)
        c.shells = [x for x in (_ptr_topology(b, t) for _ in range(b.u())) if x is not None]
        return c
    raise PrcError(f"An unknown topological entity in the PRC geometry ({tag}).")


def _matrix_3d_with_bit(b):
    return _transform_3d(b) if b.bit() else None


def _matrix_2d_with_bit(b):
    if not b.bit():
        return None
    how, m = b.read(8), np.eye(4)
    if how & 1:
        m[:2, 3] = b.double(), b.double()
    if how & 32:
        m[:2, 0] = b.double(), b.double()
        m[:2, 1] = b.double(), b.double()
    elif how & 2:
        x, y = b.double(), b.double()
        m[:2, 0] = x, y
        m[:2, 1] = (y, -x) if how & 4 else (-y, x)
    if how & 16:
        m[:3, :3] = m[:3, :3] @ np.diag([b.double(), b.double(), 1.0])
    if how & 8:
        m[:2, :2] *= b.double()
    if how & 64:
        b.double(), b.double(), b.double()
    return m


def _ptr_curve(b, t):
    if b.bit():
        return _pick(t.curves, b.u(), "curve", t.loose)
    tag = b.u()
    slot = len(t.curves)
    t.curves.append(None)
    if tag == 0:
        return None
    t.curves[slot] = curve = _curve_body(b, t, tag)
    return curve


def _curve_body(b, t, tag):
    _content_geometry(b)
    is_3d = b.bit()
    if tag == CRV_NURBS:
        return _nurbs_curve(b, is_3d)
    matrix = _matrix_3d_with_bit(b) if is_3d else _matrix_2d_with_bit(b)
    t0, t1, a, c = b.double(), b.double(), b.double(), b.double()
    if tag == CRV_LINE:
        return Line(matrix, t0, t1, a, c)
    if tag == CRV_CIRCLE:
        r = b.double()
        return Ellipse(matrix, t0, t1, a, c, r, r)
    if tag == CRV_ELLIPSE:
        return Ellipse(matrix, t0, t1, a, c, b.double(), b.double())
    if tag == CRV_POLYLINE:
        n = b.u()
        pts = [_vector(b) if is_3d else (b.double(), b.double(), 0.0) for _ in range(n)]
        return Polyline(matrix, t0, t1, a, c, pts)
    if tag == CRV_COMPOSITE:
        parts = []
        for _ in range(b.u()):
            sub = _ptr_curve(b, t)
            forward = b.bit()
            if sub is not None:
                parts.append((sub, forward))
        b.bit()
        return Composite(matrix, t0, t1, a, c, parts) if parts else None
    if tag == CRV_INTERSECTION:
        _ptr_surface(b, t), _ptr_surface(b, t)
        b.bit(), b.bit(), b.bit()
        pts = []
        for _ in range(b.u()):
            pts.append(_vector(b))
            for _ in range(4):
                b.double()
            _vector(b)
            b.double(), b.double()
            b.read(8)
        first = _vector(b)
        b.u()
        last = _vector(b)
        b.u()
        b.double(), b.double()
        b.bit()
        return ThroughPoints([first, *pts, last]) if pts else ThroughPoints([first, last])
    if tag == CRV_BLEND02:
        _ptr_surface(b, t)
        b.i32()
        pts = [_vector(b) for _ in range(b.u())]
        b.double(), b.double()
        _ptr_surface(b, t)
        b.bit(), b.bit(), b.bit()
        b.double(), b.double()
        first = _vector(b)
        b.u()
        last = _vector(b)
        b.u()
        return ThroughPoints([first, *pts, last])
    if tag == CRV_HYPERBOLA:
        x, y = b.double(), b.double()
        b.read(8)
        return Hyperbola(matrix, t0, t1, a, c, x, y)
    if tag == CRV_PARABOLA:
        focal = b.double()
        b.read(8)
        return Parabola(matrix, t0, t1, a, c, focal)
    if tag == CRV_ON_SURFACE:
        b.double()
        uv = _ptr_curve(b, t)
        surface = _ptr_surface(b, t)
        _domain(b)
        return OnSurface(matrix, t0, t1, a, c, uv, surface) if uv is not None and surface is not None and not isinstance(surface, Unevaluated) else None
    if tag == CRV_OFFSET:
        base = _ptr_curve(b, t)
        normal = _vector(b)
        distance = b.double()
        return Offset(matrix, t0, t1, a, c, base, normal, distance) if base is not None else None
    if tag == CRV_EQUATION:
        b.double(), b.double()
        _math_1d(b), _math_1d(b)
        if is_3d:
            _math_1d(b)
        return None  # edges on it are drawn straight between their vertices
    if tag == CRV_TRANSFORM:
        _ptr_curve(b, t)
        _math_3d(b)
        return None
    if tag == CRV_HELIX:
        kind = b.read(8)
        b.bit()
        _vector(b)
        for _ in range(8 if kind == 0 else 10):
            b.double()
        if kind != 0:
            _math_1d(b), _math_1d(b), _math_1d(b)
        return None
    raise PrcError(f"An unknown curve in the PRC geometry ({tag}).")


def _control(values, count, width, rational):
    """Euclidean control points and their weights: rational ones are stored multiplied through."""
    raw = np.array(values, float).reshape(count, width)
    if not rational:
        return raw, None
    w = raw[:, -1].copy()
    safe = np.where(w == 0, 1.0, w)
    return raw[:, :-1] / safe[:, None], w


def _nurbs_curve(b, is_3d):
    rational = b.bit()
    degree = b.u()
    count = b.u() + 1
    knots = b.u() + 1
    width = (3 if is_3d else 2) + (1 if rational else 0)
    raw = [b.double() for _ in range(count * width)]
    k = np.array([b.double() for _ in range(knots)], float)
    b.u(), b.u()
    control, weights = _control(raw, count, width, rational)
    if not is_3d:
        control = np.column_stack([control, np.zeros(count)])
    if knots == count + degree - 1:  # written without its outer pair
        k = np.concatenate([k[:1], k, k[-1:]])
    if len(k) != count + degree + 1 or count <= degree:
        return None
    return Nurbs(degree, control, k, weights)


def _ptr_surface(b, t):
    if b.bit():
        return _pick(t.surfaces, b.u(), "surface", t.loose)
    tag = b.u()
    slot = len(t.surfaces)
    t.surfaces.append(None)
    if tag == 0:
        return None
    t.surfaces[slot] = surface = _surface_body(b, t, tag)
    return surface


def _surface_body(b, t, tag):
    _content_geometry(b)
    if tag == SURF_NURBS:
        return _nurbs_surface(b)
    if tag == SURF_PLANE:
        matrix = _transform_3d(b)
        domain = _domain(b)
        return Plane(matrix, False, domain, b.double(), b.double(), b.double(), b.double())
    matrix = _matrix_3d_with_bit(b)
    swap = b.bit()
    domain = _domain(b)
    p = (matrix, swap, domain, b.double(), b.double(), b.double(), b.double())
    if tag == SURF_CYLINDER:
        return Cylinder(*p, b.double())
    if tag == SURF_CONE:
        r, angle = b.double(), b.double()
        return Cone(*p, r, math.tan(angle))
    if tag == SURF_SPHERE:
        return Sphere(*p, b.double())
    if tag == SURF_TORUS:
        return Torus(*p, b.double(), b.double())
    if tag == SURF_EXTRUSION:
        sweep = _vector(b)
        base = _ptr_curve(b, t)
        return Extrusion(*p, sweep, base) if base is not None else Unevaluated()
    if tag == SURF_REVOLUTION:
        b.double()
        origin, x, y = _vector(b), _vector(b), _vector(b)
        base = _ptr_curve(b, t)
        return Revolution(*p, origin, x, y, base) if base is not None else Unevaluated()
    if tag == SURF_RULED:
        first, second = _ptr_curve(b, t), _ptr_curve(b, t)
        return Ruled(*p, first, second) if first is not None and second is not None else Unevaluated()
    if tag == SURF_FROM_CURVES:
        origin = _vector(b)
        first, second = _ptr_curve(b, t), _ptr_curve(b, t)
        return FromCurves(*p, origin, first, second) if first is not None and second is not None else Unevaluated()
    if tag == SURF_OFFSET:
        base = _ptr_surface(b, t)
        distance = b.double()
        return OffsetSurface(*p, base, distance) if base is not None and base.domain is not None and not isinstance(base, Unevaluated) else Unevaluated()
    if tag == SURF_CYLINDRICAL:
        _ptr_surface(b, t)
        b.double()
        return Unevaluated()
    if tag == SURF_PIPE:
        _ptr_curve(b, t), _ptr_curve(b, t)
        b.double()
        return Unevaluated()
    if tag == SURF_TRANSFORM:
        _ptr_surface(b, t)
        _math_3d(b)
        return Unevaluated()
    if tag == SURF_BLEND01:
        _ptr_curve(b, t), _ptr_curve(b, t), _ptr_curve(b, t)
        return Unevaluated()
    if tag == SURF_BLEND02:
        _ptr_surface(b, t), _ptr_curve(b, t), _ptr_surface(b, t), _ptr_curve(b, t), _ptr_curve(b, t)
        b.bit(), b.bit(), b.bit()
        b.double(), b.double()
        _ptr_surface(b, t), _ptr_surface(b, t)
        b.read(8)
        return Unevaluated()
    if tag == SURF_BLEND03:
        n = b.u()
        for _ in range(n):
            b.double()
        for _ in range(n):
            b.i32()
        for _ in range(3 * n):
            _vector(b)
        for _ in range(n):
            b.double()
        for _ in range(3 * n):
            _vector(b)
        for _ in range(n):
            b.double()
        for _ in range(3 * n):
            _vector(b)
        for _ in range(n):
            b.double()
        b.double(), b.double(), b.double()
        for _ in range(6):
            b.i32()
        b.read(24)
        for _ in range(b.u()):
            b.double()
        return Unevaluated()
    raise PrcError(f"An unknown surface in the PRC geometry ({tag}).")


def _math_1d(b):
    tag = b.u()
    if tag == 0:
        return
    if tag == MATH_POLYNOM:
        for _ in range(b.u()):
            b.double()
    elif tag == MATH_TRIG:
        for _ in range(4):
            b.double()
    elif tag == MATH_FRACTION:
        _math_1d(b), _math_1d(b)
    elif tag == MATH_ARCTAN_COS:
        for _ in range(5):
            b.double()
    elif tag == MATH_COMBINATION:
        for _ in range(b.u()):
            b.double()
            _math_1d(b)
    else:
        raise PrcError(f"An unknown function in the PRC geometry ({tag}).")


def _math_3d(b):
    tag = b.u()
    if tag == 0:
        return
    if tag == MATH_LINEAR:
        for _ in range(12):
            b.double()
    elif tag == MATH_NONLINEAR:
        _math_3d(b), _math_3d(b)
        b.double(), b.double()
        b.i32(), b.i32(), b.i32()
    else:
        raise PrcError(f"An unknown function in the PRC geometry ({tag}).")


def _nurbs_surface(b):
    rational = b.bit()
    du, dv = b.u(), b.u()
    nu, nv = b.u() + 1, b.u() + 1
    ku, kv = b.u() + 1, b.u() + 1
    width = 4 if rational else 3
    raw = [b.double() for _ in range(nu * nv * width)]
    knots_u = np.array([b.double() for _ in range(ku)], float)
    knots_v = np.array([b.double() for _ in range(kv)], float)
    b.u(), b.u()
    control, weights = _control(raw, nu * nv, width, rational)
    if ku == nu + du - 1:
        knots_u = np.concatenate([knots_u[:1], knots_u, knots_u[-1:]])
    if kv == nv + dv - 1:
        knots_v = np.concatenate([knots_v[:1], knots_v, knots_v[-1:]])
    if len(knots_u) != nu + du + 1 or len(knots_v) != nv + dv + 1 or nu <= du or nv <= dv:
        return Unevaluated()
    return NurbsSurface(du, dv, control.reshape(nu, nv, 3), knots_u, knots_v, None if weights is None else weights.reshape(nu, nv))


# ---------------------------------------------------------------------------------------------- reading: compressed bodies
ISO_PLANE, ISO_CYLINDER, ISO_TORUS, ISO_SPHERE, ISO_CONE, ISO_NURBS = 2, 3, 4, 5, 6, 7
ANA_PLANE, ANA_CYLINDER, ANA_TORUS, ANA_SPHERE, ANA_CONE, ANA_NURBS, ANA_GENERIC = 8, 9, 10, 11, 12, 13, 14
NEW_LOOP, END_LOOP = 0, 1
C_LINE, C_CIRCLE, C_HERMITE, C_ELLIPSE, C_COMPOSITE = 0, 1, 2, 12, 13


class _Compressed:
    """One compressed body. Vertices and curves are numbered as they're stored: those in iso faces from 0, the rest after the
    count declared for those. (With none declared, it comes to the same thing.)"""

    def __init__(self, b, tolerance, bits, vertices, edges, wire=False):
        self.b, self.tolerance, self.bits = b, tolerance, bits
        self.declared_vertices, self.declared_edges = vertices, edges
        self.iso_vertex, self.iso_curve, self.ana_vertex, self.ana_curve = 0, 0, vertices, edges
        self.vertices, self.curves = {}, {}
        self.in_iso = self.in_iso_nurbs = False
        self.wire = wire
        self.points = []
        self.tables = _Tables()  # a whole surface inside a compressed body numbers its own entities
        self.tables.loose = True

    def number_vertex(self):
        if self.in_iso and self.declared_vertices:
            n = self.iso_vertex
            self.iso_vertex += 1
        else:
            n = self.ana_vertex
            self.ana_vertex += 1
        return n

    def number_curve(self):
        if self.in_iso and self.declared_edges:
            n = self.iso_curve
            self.iso_curve += 1
        else:
            n = self.ana_curve
            self.ana_curve += 1
        return n

    def named_curve(self, n):
        c = self.curves.get(n)
        if c is None:
            raise PrcError(f"A compressed PRC face names a curve that isn't there ({n}).")
        return c

    def point(self):
        b = self.b
        n = b.read(6)
        if 1 <= n <= 30:
            step = self.tolerance / 100
            return np.array([b.signed(n) * step, b.signed(n) * step, b.signed(n) * step])
        if n in (31, 32):
            return np.array(_vector(b))
        if b.u() != TOPO_UNIQUE_VERTEX:
            raise PrcError("A compressed point in the PRC geometry isn't one.")
        _base_topology(b)
        p = np.array(_vector(b))
        if b.bit():
            b.double()
        return p

    def vertex(self):
        b = self.b
        if b.bit():
            number = self.number_vertex()
            p = self.point()
            self.vertices[number] = p
            self.points.append(p)
            return p
        n = b.read(self.bits)
        if n not in self.vertices:
            raise PrcError(f"A compressed PRC curve names a vertex that isn't there ({n}).")
        return self.vertices[n]

    def ends(self):
        if self.wire:
            return self.point(), self.point()
        return self.vertex(), self.vertex()

    def entity_type(self):
        """(is it a curve, its code)."""
        b = self.b
        if b.bit():
            code = b.read(2)
            if code == 3:
                code = 12 + b.read(2)
            return True, code
        return False, b.read(4)

    def curve_body(self, code):
        if code == C_LINE:
            start, end = self.ends()
            return Segment(start, end)
        if code == C_CIRCLE:
            return self.circle()
        if code == C_HERMITE:
            return self.hermite()
        if code == C_COMPOSITE:
            return self.composite()
        raise PrcError(f"A compressed curve in the PRC geometry can't be read ({code}).")

    def curve_or_ref(self):
        """A stored curve, or a named one."""
        b = self.b
        if b.bit():
            number = self.number_curve()
            is_curve, code = self.entity_type()
            if not is_curve:
                raise PrcError("A compressed PRC face holds something else where a curve goes.")
            curve = self.curve_body(code)
            self.curves[number] = curve
            return curve
        return self.named_curve(b.read(self.bits))

    def circle(self):
        b = self.b
        if b.bit():
            full = b.bit()
            start, end = self.ends()
            if full:
                center = self.point()
                normal = self.point()
                return Arc(start, center, normal, TAU)
            return _arc_through(start, self.point(), end)
        start, end = self.ends()
        center = self.point()
        return _arc_about(start, end, center, b.bit())

    def hermite(self):
        b = self.b
        start, end = self.ends()
        n = b.read(b.read(4))
        step = self.tolerance / 2
        width = b.read(6)
        points = [start]
        for _ in range(max(n - 2, 0)):
            d = np.array(_vector(b)) if width > 30 else np.array([b.signed(width) * step, b.signed(width) * step, b.signed(width) * step])
            points.append(points[-1] + d)
        points.append(end)
        width = b.read(6)
        handles = [np.array(_vector(b)) if width > 30 else np.array([b.signed(width) * step, b.signed(width) * step, b.signed(width) * step])
                   for _ in range(n)]
        if len(points) != len(handles):
            handles = (handles + [np.zeros(3)] * len(points))[:len(points)]
        return Hermite(points, handles)

    def composite(self):
        b = self.b
        self.ends()
        b.u()
        b.bit()
        parts = [self.curve_or_ref() for _ in range(b.u())]
        return Chain(parts)

    def face(self):
        is_curve, code = self.entity_type()
        if is_curve:
            raise PrcError("A compressed PRC shell holds a curve where a face goes.")
        if code in (ISO_PLANE, ISO_CYLINDER, ISO_TORUS, ISO_SPHERE, ISO_CONE):
            return self.iso_face(code)
        if code == ISO_NURBS:
            return self.iso_nurbs()
        return self.ana_face(code)

    def iso_face(self, code):
        b = self.b
        if code == ISO_PLANE:
            self.normal()
        elif code == ISO_TORUS:
            b.bit()
        self.in_iso = True
        keep = b.bit()
        b.bit()  # the loop's way round against the surface's
        first = self.curve_or_ref()
        second = self.curve_or_ref()
        third_deduced = b.bit()
        third = self.deduced() if third_deduced else self.named_curve(b.read(self.bits))
        fourth_deduced = b.bit()
        fourth = self.deduced() if fourth_deduced else self.named_curve(b.read(self.bits))
        corner = self.vertex() if third_deduced and fourth_deduced else None
        self.in_iso = False
        _settle_sides(first, second, third, fourth, third_deduced, fourth_deduced, corner)
        return PatchFace(code, keep, (first, second, third, fourth))

    def deduced(self):
        curve = Deduced()
        self.curves[self.number_curve()] = curve
        return curve

    def normal(self):
        b = self.b
        x, y = b.double(), b.double()
        z = math.sqrt(max(0.0, 1 - x * x - y * y))
        return np.array([x, y, z if b.bit() else -z])

    def iso_nurbs(self):
        b = self.b
        self.in_iso = True
        keep = b.bit()
        b.bit()
        b.bit(), b.bit(), b.bit()
        surface = self.nurbs()
        self.points.append(surface.control.reshape(-1, 3))
        trims = [self.iso_trim(surface) for _ in range(4)]
        have = [t[1] is not None for t in trims]  # stored here, not named
        vertex = [None] * 4
        for k, (a, c) in ((3, (0, 3)), (0, (0, 1)), (1, (1, 2)), (2, (2, 3))):
            if not trims[a][0] and not trims[c][0]:
                vertex[k] = self.vertex()
        self.in_iso = False
        _settle_iso_trims(surface, trims, vertex)
        return WholeFace(surface, keep)

    def iso_trim(self, surface):
        """(is it named, what it is to become or None if named): numbers are taken here, the ends known after."""
        b = self.b
        if b.bit():
            return True, None, self.named_curve(b.read(self.bits))
        if b.bit():  # the surface's own edge
            c = Deduced()
            self.curves[self.number_curve()] = c
            return False, ("edge",), c
        if b.bit():
            c = Deduced()
            self.curves[self.number_curve()] = c
            if b.bit():
                if b.bit():
                    return False, ("full", self.point(), self.point()), c
                return False, ("middle", self.point()), c
            return False, ("about", self.point(), b.bit()), c
        c = Deduced()
        self.curves[self.number_curve()] = c
        return False, ("line",), c

    def ana_face(self, code):
        b = self.b
        if code == ANA_PLANE:
            normal = self.normal()
        keep = b.bit()
        loops = None
        extra = None
        lines_only = False
        if b.bit():
            loops, lines_only = self.loops()
        if code == ANA_TORUS and loops and lines_only:
            extra = self.point()
        if code == ANA_PLANE:
            return AnaFace(lambda points: _make_plane(normal, points), keep, loops)
        if code == ANA_CYLINDER:
            point, direction = self.point(), self.point()
            return AnaFace(lambda points: _make_cylinder(point, direction, points), keep, loops)
        if code == ANA_TORUS:
            center, x, y = self.point(), self.point(), np.array(_vector(b))
            return AnaFace(lambda points: _make_torus(center, x, y), keep, loops, extra)
        if code == ANA_SPHERE:
            center = self.point()
            return AnaFace(lambda points: _make_sphere(center, points), keep, loops)
        if code == ANA_CONE:
            axis_point, apex = self.point(), self.point()
            return AnaFace(lambda points: _make_cone(axis_point, apex, points), keep, loops)
        if code == ANA_NURBS:
            surface = self.nurbs()
            if loops is None:  # a trimmed one may be a huge sheet with a little kept: only its loops say how big the body is
                self.points.append(surface.control.reshape(-1, 3))
                return WholeFace(surface, keep)
            return AnaFace(lambda points: surface, keep, loops)
        if code == ANA_GENERIC:
            tag = b.u()
            slot = len(self.tables.surfaces)
            self.tables.surfaces.append(None)
            surface = _surface_body(b, self.tables, tag) if tag else Unevaluated()
            self.tables.surfaces[slot] = surface
            return AnaFace(lambda points: surface, keep, loops)
        raise PrcError(f"A compressed face in the PRC geometry can't be read ({code}).")

    def loops(self):
        """The trim loops: a loop's way round, then curves until a marker ends it."""
        b = self.b
        out, lines_only = [], True
        while True:
            b.bit()  # its way round against the surface's
            curves = []
            while True:
                if not b.bit():
                    curves.append(self.named_curve(b.read(self.bits)))
                    lines_only = False
                    continue
                is_curve, code = self.entity_type()
                if not is_curve:
                    marker = code
                    break
                number = self.number_curve()
                curve = self.curve_body(code)
                self.curves[number] = curve
                curves.append(curve)
                if code != C_LINE:
                    lines_only = False
            if len(curves) != 1:
                lines_only = False
            out.append(curves)
            if marker == END_LOOP:
                return out, lines_only
            if marker != NEW_LOOP:
                raise PrcError(f"A compressed PRC face's loops aren't as expected ({marker}).")

    def nurbs(self):
        b = self.b
        du, dv = b.read(5), b.read(5)
        mult_u = self._multiplicities(du)
        mult_v = self._multiplicities(dv)
        b.bit(), b.bit()
        iso_bits, rest_bits = b.read(20) + 1, b.read(20) + 1
        nu, nv = sum(mult_u) - du - 1, sum(mult_v) - dv - 1
        if nu < 1 or nv < 1 or nu * nv > 4000000:
            raise PrcError("A compressed PRC surface says it's an impossible size.")
        step = self.tolerance / 5
        P = np.zeros((nu, nv, 3))
        P[0, 0] = _vector(b)
        for j in range(1, nv):
            P[0, j] = P[0, j - 1] + (b.signed(iso_bits) * step, b.signed(iso_bits) * step, b.signed(iso_bits) * step)
        for i in range(1, nu):
            P[i, 0] = P[i - 1, 0] + (b.signed(iso_bits) * step, b.signed(iso_bits) * step, b.signed(iso_bits) * step)
        for i in range(1, nu):
            for j in range(1, nv):
                kind = b.read(2)
                corner = P[i - 1, j - 1]
                U, V = P[i, j - 1] - corner, P[i - 1, j] - corner
                here = corner + U + V
                if kind == 3:
                    here = here + (b.signed(rest_bits) * step, b.signed(rest_bits) * step, b.signed(rest_bits) * step)
                elif kind:
                    normal = _unit(np.cross(U, V))
                    if kind == 1:
                        here = here + b.signed(rest_bits) * step * normal
                    else:
                        along = _unit(U)
                        x, y = b.signed(rest_bits) * step, b.signed(rest_bits) * step
                        here = here + x * along + y * np.cross(normal, along)
                P[i, j] = here
        knots_u, knots_v = self._knots(mult_u), self._knots(mult_v)
        weights = None
        if b.bit():
            width = b.read(6)
            if width:
                if width <= 30:
                    size = b.double()
                    weights = np.array([b.signed(width + 1) * size for _ in range(nu * nv)])
                else:
                    weights = np.array([b.double() for _ in range(nu * nv)])
                weights = weights.reshape(nu, nv)
        return NurbsSurface(du, dv, P, knots_u, knots_v, weights)

    def _multiplicities(self, degree):
        b = self.b
        width = math.ceil(math.log2(degree + 2)) if degree else 2
        out = []
        for _ in range(b.read(16)):
            out.append((out[-1] if out else 1) if b.bit() else b.read(width))
        return out

    def _knots(self, multiplicities):
        """The distinct knots: evenly over 0 to 1, or from stored spans with the last implied. Pseudo-uniform keeps its ends."""
        b = self.b
        count = len(multiplicities)
        values = np.linspace(0.0, 1.0, count) if count > 1 else np.zeros(count)
        if not b.bit():
            unknown = b.bit()
            pseudo = False if unknown else b.bit()
            width = b.read(6)
            stored = 2 if pseudo else max(count - 2, 0)
            read = [b.double() if width > 30 else b.signed(width + 1) / 2.0 ** (width - 1) for _ in range(stored)]
            if not pseudo and count >= 2:
                spans = np.array(read, float)
                inner = np.cumsum(spans)
                if not len(inner) or (inner[-1] < 1.0 and np.all(spans > 0)):
                    values = np.concatenate([[0.0], inner, [1.0]])
        return expand_knots(values, multiplicities)


def _unit(v):
    size = float(np.linalg.norm(v))
    return v / size if size > 0 else v


def _frame(origin, z, near_x=None):
    """A right-handed frame about an axis."""
    z = _unit(np.asarray(z, float))
    x = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    if near_x is not None:
        x = np.asarray(near_x, float)
    x = _unit(x - (x @ z) * z)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, np.cross(z, x), z, origin
    return m


def _make_plane(normal, points):
    return Plane(_frame(np.mean(points, axis=0), normal), False, None, 1.0, 1.0, 0.0, 0.0)


def _make_cylinder(point, direction, points):
    m = _frame(point, direction)
    rel = np.asarray(points) - m[:3, 3]
    radius = float(np.mean(np.linalg.norm(rel - np.outer(rel @ m[:3, 2], m[:3, 2]), axis=1)))
    return Cylinder(m, False, None, 1.0, 1.0, 0.0, 0.0, radius)


def _make_cone(axis_point, apex, points):
    direction = _unit(apex - axis_point)
    m = _frame(apex, direction)
    rel = np.asarray(points) - apex
    h = rel @ direction
    rho = np.linalg.norm(rel - np.outer(h, direction), axis=1)
    use = np.abs(h) > 1e-9 * max(float(np.abs(h).max()), 1e-30)
    slope = float(np.median(rho[use] / h[use])) if use.any() else 0.0
    return Cone(m, False, None, 1.0, 1.0, 0.0, 0.0, 0.0, slope)


def _make_sphere(center, points):
    rel = np.asarray(points) - center
    radius = float(np.mean(np.linalg.norm(rel, axis=1)))
    # the poles out of the way of the edges: the axis the way they spread least. A band then lies round the equator, and a cap
    # round a pole, which is closed to
    axis = np.linalg.svd(rel - rel.mean(axis=0), full_matrices=False)[2][-1]
    return Sphere(_frame(center, axis), False, None, 1.0, 1.0, 0.0, 0.0, radius)


def _make_torus(center, x, y):
    major, minor = float(np.linalg.norm(x)), float(np.linalg.norm(y))
    m = np.eye(4)
    m[:3, 0], m[:3, 2], m[:3, 3] = _unit(x), _unit(np.cross(x, y)), center
    m[:3, 1] = np.cross(m[:3, 2], m[:3, 0])
    return Torus(m, False, None, 1.0, 1.0, 0.0, 0.0, major, minor)


def _common_end(a, b):
    """Which end of each of two curves meet: (a's other end, the meeting point, b's other end)."""
    best = None
    for p, op in ((a.start, a.end), (a.end, a.start)):
        for q, oq in ((b.start, b.end), (b.end, b.start)):
            d = float(np.abs(p - q).max())
            if best is None or d < best[0]:
                best = (d, op, p, oq)
    return best[1], best[2], best[3]


class Reversed(Curve):
    def __init__(self, curve):
        self.curve, self.start, self.end = curve, curve.end, curve.start
        self.straight = getattr(curve, "straight", False)

    def at(self, t):
        return self.curve.at(1.0 - np.asarray(t, float))


def forward(curve, start):
    """The curve, running away from whichever end is at `start`."""
    if float(np.abs(curve.end - start).max()) < float(np.abs(curve.start - start).max()):
        return Reversed(curve)
    return curve


def _settle_sides(first, second, third, fourth, third_deduced, fourth_deduced, corner):
    """What an iso face's unstored sides are: p0 -first- p1 -second- p2 -third- p3 -fourth- p0, each deduced side being a copy
    of the side across from it, set on its corners."""
    p0, p1, p2 = _common_end(first, second)
    if third_deduced and fourth_deduced:
        p3 = corner
    elif third_deduced:
        known = fourth
        p3 = known.end if float(np.abs(known.start - p0).max()) < float(np.abs(known.end - p0).max()) else known.start
    elif fourth_deduced:
        known = third
        p3 = known.end if float(np.abs(known.start - p2).max()) < float(np.abs(known.end - p2).max()) else known.start
    else:
        return
    if third_deduced:
        third.become(Similar(forward(first, p0), p3, p2))
    if fourth_deduced:
        fourth.become(Similar(forward(second, p2), p3, p0))


def _settle_iso_trims(surface, trims, vertex):
    """An iso NURBS face is its whole surface, so its trims matter only to faces naming them later."""
    corners = surface.control[[0, 0, -1, -1], [0, -1, -1, 0]]
    ends = list(vertex)

    def known_from(k):
        a, c = trims[k], trims[(k + 1) % 4]  # vertex k joins trim k and trim k + 1
        for trim in (a, c):
            curve = trim[2]
            if trim[0] and curve.start is not None:
                d = [float(np.abs(corners - e).max(axis=1).min()) for e in (curve.start, curve.end)]
                return curve.start if d[0] <= d[1] else curve.end
        return None

    for k in range(4):
        if ends[k] is None:
            ends[k] = known_from(k)
    for k, (named, how, curve) in enumerate(trims):
        if named:
            continue
        a, b = ends[(k + 3) % 4], ends[k]
        if a is None or b is None:
            a, b = corners[k], corners[(k + 1) % 4]
        kind = how[0]
        if kind == "full":
            curve.become(Arc(a, how[1], how[2], TAU))
        elif kind == "middle":
            curve.become(_arc_through(a, how[1], b))
        elif kind == "about":
            curve.become(_arc_about(a, b, how[1], how[2]))
        else:
            curve.become(Segment(a, b))


# ---------------------------------------------------------------------------------------------- reading: the section
def read_geometry(b):
    """The contexts of a file structure's geometry section. A body that can't be read ends its context's reading, since
    nothing says where the next one starts: those before it stand, and a note of what went wrong goes on the context."""
    if b.u() != TYPE_GEOMETRY:
        raise PrcError("The geometry section of the PRC data isn't one.")
    attributes(b)
    name_of(b)
    return [_context(b) for _ in range(b.u())]


def _context(b):
    if b.u() != TOPO_CONTEXT:
        raise PrcError("A topological context in the PRC geometry isn't one.")
    attributes(b)
    name_of(b)
    out = Context()
    b.read(8)
    b.double()
    out.tolerance = b.double()
    if b.bit():
        b.double()
    if b.bit():
        scale = b.double()
        out.scale = scale if scale else 1.0
    count = b.u()
    tables = _Tables()
    out.bodies = [_body(b, tables) for _ in range(count)]
    extend(b, TOPO_CONTEXT)
    return out


def _body(b, tables, depth=0):
    if depth > MAX_NEST:
        raise PrcError("The PRC bodies nest too deep.")
    tag = b.u()
    if tag == 0:
        return None
    if tag == TOPO_BODY:
        return _body(b, tables, depth + 1)
    if tag == TOPO_WIRE_BODY:
        _base_topology(b)
        b.read(8)
        _ptr_topology(b, tables)
        return None
    if tag == TOPO_BREP:
        return _plain_body(b, tables)
    if tag == TOPO_BREP_COMPRESSED:
        return _compressed_body(b)
    if tag == TOPO_WIRE_COMPRESSED:
        return _compressed_wire(b)
    raise PrcError(f"An unknown body in the PRC geometry ({tag}).")


def _plain_body(b, t):
    t.points = []
    _base_topology(b)
    behaviour = b.read(8)
    shells = []
    for _ in range(b.u()):
        connex = _ptr_topology(b, t)
        if connex is not None:
            shells += [(s.closed, s.faces) for s in connex.shells]
    if behaviour & 3:
        for _ in range(6):
            b.double()
    return Brep(shells, t.points)


def _compressed_body(b):
    _base_topology(b)
    b.read(8)
    tolerance = b.double()
    width = _bits_then(b)
    vertices, edges = b.read(width), b.read(width)
    c = _Compressed(b, tolerance, width, vertices, edges)
    if b.bit():
        shells = [_compressed_shell(b, c)]
    else:
        shells = [_compressed_shell(b, c) for _ in range(_bits_then(b)) for _ in range(_bits_then(b))]
    for closed, faces in shells:
        for _ in faces:
            _base_topology(b)
    return Brep(shells, c.points)


def _compressed_shell(b, c):
    count = 1 if b.bit() else _bits_then(b)
    faces = [c.face() for _ in range(count)]
    b.flags(count)  # which of them are iso faces, which are stored first
    return False, [(f, 1 if f.keep else 0) for f in faces]


def _compressed_wire(b):
    """Lines alone, with nothing to mesh. Writers differ on one bit before the curve: the files seen all have it."""
    _base_topology(b)
    b.read(8)
    tolerance = b.double()
    at = b.i
    try:
        b.bit()
        _wire_curve(b, tolerance)
    except PrcError:
        b.i = at
        _wire_curve(b, tolerance)
    return None


def _wire_curve(b, tolerance):
    c = _Compressed(b, tolerance, 0, 0, 0, wire=True)
    is_curve, code = c.entity_type()
    if not is_curve:
        raise PrcError("A compressed PRC wire isn't a curve.")
    c.curve_body(code)
