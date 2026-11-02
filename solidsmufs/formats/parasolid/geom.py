"""Parasolid curves and surfaces: evaluation (in metres) and STEP output.

Parametrisations (checked against vertex positions in real files):
    PLANE     p + u·x + v·y                         CYLINDER  p + r(cos u·x + sin u·y) + v·a
    CONE      p + (r + v·s/c)(cos u·x + sin u·y) + v·a   (s, c: sin / cos of the half angle)
    SPHERE    c + r(cos v(cos u·x + sin u·y) + sin v·a)
    TORUS     c + (R + r cos v)(cos u·x + sin u·y) + r sin v·a
    SWEPT     section(u) + v·sweep                  SPUN      profile(u) turned by v about (base, axis)
    CIRCLE    c + r(cos t·x + sin t·y)              LINE      p + t·d
with y = axis × x. A surface's natural normal is ∂u × ∂v; a geometry node's sense '-' reverses it.
Rational B-spline vertices are stored homogeneous (x·w, y·w, z·w, w).
"""

import math

import numpy as np

from . import nurbs as N

TWO_PI = 2.0 * math.pi


class GeomError(Exception):
    """This geometry can't be built (missing data or an unsupported kind)."""


def _v(x):
    if x is None:
        raise GeomError("missing vector")
    return np.asarray(x, float)


def _unit(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    if n == 0:
        raise GeomError("zero vector")
    return v / n


def _frame(axis, xref):
    a = _unit(axis)
    x = np.asarray(xref, float) if xref is not None else np.cross(a, (1, 0, 0) if abs(a[0]) < 0.9 else (0, 1, 0))
    x = x - np.dot(x, a) * a
    if np.linalg.norm(x) < 1e-12:
        x = np.cross(a, (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0))
    x = _unit(x)
    return a, x, np.cross(a, x)


def project_many(ev, Q, lo, hi, n=257, period=None, iters=10):
    """Parameters t in [lo, hi] of the points of the curve ev(ts) -> (k, m) nearest each row of Q (k, m):
    the best of n samples, then Newton steps on (ev(t) - q)·ev'(t) = 0, all rows at once."""
    Q = np.atleast_2d(np.asarray(Q, float))
    ts = np.linspace(lo, hi, n)
    T = ev(ts)
    d = (Q * Q).sum(axis=1)[:, None] - 2 * Q @ T.T + (T * T).sum(axis=1)[None, :]
    t = ts[np.argmin(d, axis=1)]
    k = len(t)
    h = 1e-6 * (hi - lo)
    lim = 2.0 * (hi - lo) / (n - 1)
    for _ in range(iters):
        E = ev(np.concatenate([t, t + h, t - h]))
        P, Pp, Pm = E[:k], E[k:2 * k], E[2 * k:]
        d1 = (Pp - Pm) / (2 * h)
        d2 = (Pp - 2 * P + Pm) / (h * h)
        r = P - Q
        g = np.einsum("ij,ij->i", r, d1)
        gp = np.einsum("ij,ij->i", d1, d1) + np.einsum("ij,ij->i", r, d2)
        gp = np.where(gp > 1e-300, gp, np.maximum(np.einsum("ij,ij->i", d1, d1), 1e-300))
        step = np.clip(-g / gp, -lim, lim)
        t = t + step
        if period is None:
            t = np.clip(t, lo, hi)
        if float(np.max(np.abs(step), initial=0)) < 1e-14 * max(1.0, hi - lo):
            break
    return t


def _nearest(ev, q, ts):
    """Parameter of the point of the curve ev(ts) nearest q: the best of the samples ts, then zoomed in."""
    ts = np.asarray(ts, float)
    e = ev(ts) - q
    d = np.einsum("ij,ij->i", e, e)
    i = int(np.argmin(d))
    a, b = ts[max(i - 1, 0)], ts[min(i + 1, len(ts) - 1)]
    for _ in range(7):
        ts = np.linspace(a, b, 17)
        e = ev(ts) - q
        d = np.einsum("ij,ij->i", e, e)
        i = int(np.argmin(d))
        a, b = ts[max(i - 1, 0)], ts[min(i + 1, 16)]
    return float(ts[i])


# ================================================================== curves
class Curve:
    exact = True  # STEP can say it exactly
    period = None  # for closed periodic curves (circles, ellipses)

    def eval(self, ts):
        raise NotImplementedError

    def domain(self):
        return None

    def breaks(self):
        return ()

    def project(self, q):
        """Parameter of the point of the curve nearest q."""
        lo, hi = self.domain()
        n = max(65, 8 * (len(self.breaks()) + 1) + 1)
        return float(project_many(self.eval, np.asarray(q, float)[None], lo, hi, n=n, period=self.period)[0])

    def point(self, t):
        return self.eval(np.array([t], float))[0]


class Line(Curve):
    def __init__(self, p, d):
        self.p, self.d = _v(p), _unit(d)

    def eval(self, ts):
        ts = np.asarray(ts, float)
        return self.p + ts[:, None] * self.d

    def project(self, q):
        return float(np.dot(q - self.p, self.d))

    def step(self, w):
        return w.line(self.p, self.d)


class Circle(Curve):
    period = TWO_PI

    def __init__(self, c, n, x, r):
        self.c, self.r = _v(c), float(r)
        self.n, self.x, self.y = _frame(n, x)

    def eval(self, ts):
        ts = np.asarray(ts, float)
        return self.c + self.r * (np.cos(ts)[:, None] * self.x + np.sin(ts)[:, None] * self.y)

    def project(self, q):
        d = q - self.c
        return math.atan2(float(np.dot(d, self.y)), float(np.dot(d, self.x)))

    def domain(self):
        return (0.0, TWO_PI)

    def step(self, w):
        return w.circle(self.c, self.n, self.x, self.r)


class Ellipse(Curve):
    period = TWO_PI

    def __init__(self, c, n, x, r1, r2):
        self.c, self.r1, self.r2 = _v(c), float(r1), float(r2)
        self.n, self.x, self.y = _frame(n, x)

    def eval(self, ts):
        ts = np.asarray(ts, float)
        return self.c + np.cos(ts)[:, None] * self.r1 * self.x + np.sin(ts)[:, None] * self.r2 * self.y

    def project(self, q):
        d = q - self.c
        t0 = math.atan2(float(np.dot(d, self.y)) / self.r2, float(np.dot(d, self.x)) / self.r1)
        return _nearest(self.eval, q, np.linspace(t0 - 0.3, t0 + 0.3, 13))

    def domain(self):
        return (0.0, TWO_PI)

    def step(self, w):
        if self.r1 >= self.r2:
            return w.ellipse(self.c, self.n, self.x, self.r1, self.r2)
        # STEP readers want the major axis first: the same ellipse from a frame turned by 90 degrees about
        # the same normal (its parameter is then t - pi/2: the direction is unchanged)
        return w.ellipse(self.c, self.n, self.y, self.r2, self.r1)


class BSpline(Curve):
    """A NURBS curve; dim 3 (space) or 2 (an SP-curve's parameter-space curve)."""

    def __init__(self, deg, U, P, rational, dim):
        self.deg, self.U, self.P, self.rational, self.dim = deg, np.asarray(U, float), np.asarray(P, float), rational, dim
        if len(self.U) != len(self.P) + deg + 1:
            raise GeomError("inconsistent B-spline")

    def eval(self, ts):
        return N.eval_curve(self.deg, self.U, self.P, ts, self.rational)

    def domain(self):
        return (float(self.U[self.deg]), float(self.U[len(self.P)]))

    def breaks(self):
        lo, hi = self.domain()
        return sorted({float(u) for u in self.U if lo < u < hi})

    def segment(self, a, b):
        U, P = N.segment(self.deg, self.U, self.P, a, b)
        return BSpline(self.deg, U, P, self.rational, self.dim)

    def step(self, w, a=None, b=None):
        c = self if (a is None and self._is_clamped()) else self.segment(a, b)
        return w.bspline_curve(c.deg, c.U, c.P, c.rational)

    def _is_clamped(self):
        return N._clamped(self.deg, self.U)


class SPCurve(Curve):
    """A curve given by a 2D B-spline in a surface's parameter space."""
    exact = False

    def __init__(self, surface, pcurve):
        self.surface, self.pc = surface, pcurve

    def eval(self, ts):
        uv = self.pc.eval(ts)
        return self.surface.eval(uv[:, 0], uv[:, 1])

    def domain(self):
        return self.pc.domain()

    def breaks(self):
        return self.pc.breaks()

    def exact_piece(self, t0, t1):
        """(curve, t0', t1') giving the same points exactly, when STEP can say it, else None."""
        S, pc = self.surface, self.pc
        P = pc.P[:, :2] / pc.P[:, 2:3] if pc.rational else pc.P[:, :2]
        if isinstance(S, Plane):  # an affine image of the 2D spline
            if pc.rational:
                w = pc.P[:, 2]
                Q = np.column_stack([S.p * w[:, None] + P[:, :1] * w[:, None] * S.x + P[:, 1:2] * w[:, None] * S.y, w])
            else:
                Q = S.p + P[:, :1] * S.x + P[:, 1:2] * S.y
            return BSpline(pc.deg, pc.U, Q, pc.rational, 3), t0, t1
        span = np.ptp(P, axis=0)
        scale = max(1.0, float(np.max(np.abs(P))))
        for k, which in ((1, "v"), (0, "u")):  # constant v: the curve runs in u, and vice versa
            if span[k] <= 1e-11 * scale:
                c = float(np.mean(P[:, k]))
                iso = S.iso("u" if which == "u" else "v", c)
                if iso is None:
                    return None
                a, b = pc.point(t0)[1 - k], pc.point(t1)[1 - k]
                if not _monotone(pc, t0, t1, 1 - k):
                    return None
                return iso, a, b
        return None


def _monotone(pc, t0, t1, k):
    v = pc.eval(np.linspace(t0, t1, 33))[:, k]
    d = np.diff(v)
    return bool(np.all(d >= -1e-14) or np.all(d <= 1e-14))


class ChartCurve(Curve):
    """An intersection curve, known by points along it (Parasolid's chart)."""
    exact = False

    def __init__(self, pts, surfaces=()):
        self.pts = np.asarray(pts, float)
        if len(self.pts) < 2:
            raise GeomError("intersection chart too short")
        seg = np.linalg.norm(np.diff(self.pts, axis=0), axis=1)
        keep = np.concatenate([[True], seg > 1e-12])
        self.pts = self.pts[keep]
        seg = seg[seg > 1e-12]
        self.s = np.concatenate([[0.0], np.cumsum(seg)])
        if len(self.pts) < 2:
            raise GeomError("intersection chart too short")
        self.surfaces = surfaces

    def domain(self):
        return (0.0, float(self.s[-1]))

    def eval(self, ts):  # along the chart polyline (by arc length)
        ts = np.clip(np.asarray(ts, float), 0.0, self.s[-1])
        return np.column_stack([np.interp(ts, self.s, self.pts[:, k]) for k in range(3)])

    def project(self, q):
        a, b = self.pts[:-1], self.pts[1:]
        ab = b - a
        L2 = np.einsum("ij,ij->i", ab, ab)
        t = np.clip(np.einsum("ij,ij->i", q - a, ab) / np.where(L2 > 0, L2, 1), 0, 1)
        d = np.linalg.norm(a + t[:, None] * ab - q, axis=1)
        i = int(np.argmin(d))
        return float(self.s[i] + t[i] * (self.s[i + 1] - self.s[i]))

    def points_between(self, s0, s1):
        """The chart points strictly between arc lengths s0 and s1, in that order."""
        lo, hi = min(s0, s1), max(s0, s1)
        tol = 1e-9 + 1e-6 * (hi - lo)
        sel = (self.s > lo + tol) & (self.s < hi - tol)
        pts, ss = self.pts[sel], self.s[sel]
        if s1 < s0:
            pts, ss = pts[::-1], ss[::-1]
        return pts, ss


# ================================================================== surfaces
class Surface:
    exact = True

    def eval(self, us, vs):
        raise NotImplementedError

    def iso(self, which, c):
        """The exact curve of constant u (which='u') or v, parametrised by the other parameter."""
        return None

    def normal(self, us, vs, h=1e-6):
        """Unit natural normals (du x dv); at a degenerate point (a pole), the limit from close by."""
        us, vs = np.asarray(us, float), np.asarray(vs, float)
        du = (self.eval(us + h, vs) - self.eval(us - h, vs)) / (2 * h)
        dv = (self.eval(us, vs + h) - self.eval(us, vs - h)) / (2 * h)
        n = np.cross(du, dv)
        ln = np.linalg.norm(n, axis=1)
        luv = np.linalg.norm(du, axis=1) * np.linalg.norm(dv, axis=1)
        bad = (ln <= 1e-9 * luv) | (luv <= 1e-300)
        if bad.any():
            acc = np.zeros((int(bad.sum()), 3))
            for su, sv in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                uu, vv = us[bad] + su * 1e-4, vs[bad] + sv * 1e-4
                d1 = self.eval(uu + h, vv) - self.eval(uu - h, vv)
                d2 = self.eval(uu, vv + h) - self.eval(uu, vv - h)
                c = np.cross(d1, d2)
                acc += c / np.maximum(np.linalg.norm(c, axis=1), 1e-300)[:, None]
            n[bad] = acc
            ln = np.linalg.norm(n, axis=1)
        return n / np.maximum(ln, 1e-300)[:, None]

    def uv_box(self):
        """A parameter box to search for closest points (numeric surfaces)."""
        return None

    def closest(self, Q, uv0=None):
        """(uv (k, 2), points (k, 3)): the points of the surface nearest each row of Q (Gauss-Newton)."""
        Q = np.atleast_2d(np.asarray(Q, float))
        if uv0 is None:
            uv0 = self._grid_guess(Q)
        uv = np.array(uv0, float, copy=True)
        box = self.uv_box()
        h = 1e-7
        stop = 1e-10 * (max(box[1] - box[0], box[3] - box[2]) if box is not None else 1.0)
        k = len(Q)
        for _ in range(25):
            u, v = uv[:, 0], uv[:, 1]
            E = self.eval(np.concatenate([u, u + h, u - h, u, u]), np.concatenate([v, v, v, v + h, v - h]))
            P = E[:k]
            Pu = (E[k:2 * k] - E[2 * k:3 * k]) / (2 * h)
            Pv = (E[3 * k:4 * k] - E[4 * k:]) / (2 * h)
            r = P - Q
            a11 = np.einsum("ij,ij->i", Pu, Pu)
            a12 = np.einsum("ij,ij->i", Pu, Pv)
            a22 = np.einsum("ij,ij->i", Pv, Pv)
            b1 = -np.einsum("ij,ij->i", Pu, r)
            b2 = -np.einsum("ij,ij->i", Pv, r)
            det = a11 * a22 - a12 * a12
            det = np.where(np.abs(det) > 1e-300, det, 1e-300)
            du = (b1 * a22 - b2 * a12) / det
            dv = (a11 * b2 - a12 * b1) / det
            if box is not None:  # no jumps further than a tenth of the search box at once
                su, sv = 0.1 * (box[1] - box[0]), 0.1 * (box[3] - box[2])
                du, dv = np.clip(du, -su, su), np.clip(dv, -sv, sv)
            old_uv = uv.copy()
            uv[:, 0] += du
            uv[:, 1] += dv
            if box is not None:  # nearest points beyond the edge of the parameter box stay on the edge
                uv[:, 0] = np.clip(uv[:, 0], box[0], box[1])
                uv[:, 1] = np.clip(uv[:, 1], box[2], box[3])
            if float(np.max(np.abs(uv - old_uv), initial=0)) < stop:
                break
        return uv, self.eval(uv[:, 0], uv[:, 1])

    def _grid_guess(self, Q, n=24):
        g = getattr(self, "_guess_grid", None)
        if g is None:
            box = self.uv_box()
            if box is None:
                raise GeomError("no parameter box to search")
            us, vs = np.linspace(box[0], box[1], n), np.linspace(box[2], box[3], n)
            uu, vv = np.repeat(us, n), np.tile(vs, n)
            g = self._guess_grid = (uu, vv, self.eval(uu, vv))
        uu, vv, G = g
        d = (Q * Q).sum(axis=1)[:, None] - 2 * Q @ G.T + (G * G).sum(axis=1)[None, :]
        i = np.argmin(d, axis=1)
        return np.column_stack([uu[i], vv[i]])


class Plane(Surface):
    def __init__(self, p, n, x):
        self.p = _v(p)
        self.n, self.x, self.y = _frame(n, x)

    def eval(self, us, vs):
        us, vs = np.asarray(us, float), np.asarray(vs, float)
        return self.p + us[:, None] * self.x + vs[:, None] * self.y

    def iso(self, which, c):
        if which == "u":
            return Line(self.p + c * self.x, self.y)
        return Line(self.p + c * self.y, self.x)

    def closest(self, Q, uv0=None):
        d = np.atleast_2d(Q) - self.p
        u, v = d @ self.x, d @ self.y
        return np.column_stack([u, v]), self.eval(u, v)

    def step(self, w):
        return w.add(f"PLANE('',{w.axis2(self.p, self.n, self.x)})"), False


class Cylinder(Surface):
    def __init__(self, p, a, r, x):
        self.p, self.r = _v(p), float(r)
        self.a, self.x, self.y = _frame(a, x)

    def eval(self, us, vs):
        us, vs = np.asarray(us, float), np.asarray(vs, float)
        return (self.p + self.r * (np.cos(us)[:, None] * self.x + np.sin(us)[:, None] * self.y)
                + vs[:, None] * self.a)

    def closest(self, Q, uv0=None):
        d = np.atleast_2d(Q) - self.p
        v = d @ self.a
        rv = d - v[:, None] * self.a
        u = np.arctan2(rv @ self.y, rv @ self.x)
        if self.r < 0:
            u = u + math.pi
        return np.column_stack([u, v]), self.eval(u, v)

    def iso(self, which, c):
        if which == "v":
            return Circle(self.p + c * self.a, self.a, self.x, self.r)
        return Line(self.p + self.r * (math.cos(c) * self.x + math.sin(c) * self.y), self.a)

    def step(self, w):
        # the natural normal r·(cos u·x + sin u·y) points away from the axis whatever r's sign: as STEP's
        return w.add(f"CYLINDRICAL_SURFACE('',{w.axis2(self.p, self.a, self.x)},{w.length(abs(self.r))})"), False


class Cone(Surface):
    def __init__(self, p, a, r, s, c, x):
        self.p, self.r, self.s, self.c = _v(p), float(r), float(s), float(c)
        self.a, self.x, self.y = _frame(a, x)

    def eval(self, us, vs):
        us, vs = np.asarray(us, float), np.asarray(vs, float)
        rad = self.r + vs * (self.s / self.c)
        return (self.p + rad[:, None] * (np.cos(us)[:, None] * self.x + np.sin(us)[:, None] * self.y)
                + vs[:, None] * self.a)

    def closest(self, Q, uv0=None):
        d = np.atleast_2d(Q) - self.p
        h = d @ self.a
        rv = d - h[:, None] * self.a
        rho = np.linalg.norm(rv, axis=1)
        u = np.arctan2(rv @ self.y, rv @ self.x)
        k = self.s / self.c
        v = (h + (rho - self.r) * k) / (1 + k * k)
        return np.column_stack([u, v]), self.eval(u, v)

    def iso(self, which, c):
        if which == "v":
            rad = self.r + c * self.s / self.c
            if rad < 1e-12:  # the apex, or the other nappe
                return None
            return Circle(self.p + c * self.a, self.a, self.x, rad)
        d = (self.s / self.c) * (math.cos(c) * self.x + math.sin(c) * self.y) + self.a
        o = self.p + self.r * (math.cos(c) * self.x + math.sin(c) * self.y)
        L = float(np.linalg.norm(d))
        return _ScaledLine(o, d / L, L)

    def step(self, w):
        s, c, a = self.s, self.c, self.a
        half = math.atan2(abs(s), abs(c))
        # natural normal (r + v·s/c)·(radial - (s/c)·a): away from the axis, as STEP's
        if abs(s) < 1e-14:  # a cylinder really
            return w.add(f"CYLINDRICAL_SURFACE('',{w.axis2(self.p, a, self.x)},{w.length(abs(self.r))})"), False
        if s * c < 0:  # the radius grows against the axis
            a = -a
        if self.r < 0:
            raise GeomError("cone with negative radius")
        return w.add(f"CONICAL_SURFACE('',{w.axis2(self.p, a, self.x)},{w.length(self.r)},{_n(half)})"), False


class _ScaledLine(Line):
    """p + t·L·d: a line whose parameter runs L times faster (cone generators)."""

    def __init__(self, p, d, L):
        super().__init__(p, d)
        self.L = L

    def eval(self, ts):
        return super().eval(np.asarray(ts, float) * self.L)

    def project(self, q):
        return super().project(q) / self.L


class Sphere(Surface):
    def __init__(self, c, r, a, x):
        self.c, self.r = _v(c), float(r)
        self.a, self.x, self.y = _frame(a, x)

    def eval(self, us, vs):
        us, vs = np.asarray(us, float), np.asarray(vs, float)
        cv = np.cos(vs)[:, None]
        return self.c + self.r * (cv * (np.cos(us)[:, None] * self.x + np.sin(us)[:, None] * self.y)
                                  + np.sin(vs)[:, None] * self.a)

    def closest(self, Q, uv0=None):
        d = np.atleast_2d(Q) - self.c
        if self.r < 0:
            d = -d
        u = np.arctan2(d @ self.y, d @ self.x)
        v = np.arctan2(d @ self.a, np.linalg.norm(d - (d @ self.a)[:, None] * self.a, axis=1))
        return np.column_stack([u, v]), self.eval(u, v)

    def iso(self, which, c):
        if which == "v":
            rad = self.r * math.cos(c)
            if rad < 1e-12:
                return None
            return Circle(self.c + self.r * math.sin(c) * self.a, self.a, self.x, rad)
        d = math.cos(c) * self.x + math.sin(c) * self.y
        return Circle(self.c, np.cross(d, self.a), d, self.r)

    def step(self, w):
        return w.add(f"SPHERICAL_SURFACE('',{w.axis2(self.c, self.a, self.x)},{w.length(abs(self.r))})"), self.r < 0


class Torus(Surface):
    def __init__(self, c, a, R, r, x):
        self.c, self.R, self.r = _v(c), float(R), float(r)
        self.a, self.x, self.y = _frame(a, x)

    def eval(self, us, vs):
        us, vs = np.asarray(us, float), np.asarray(vs, float)
        rad = self.R + self.r * np.cos(vs)
        return (self.c + rad[:, None] * (np.cos(us)[:, None] * self.x + np.sin(us)[:, None] * self.y)
                + (self.r * np.sin(vs))[:, None] * self.a)

    def closest(self, Q, uv0=None):
        Q = np.atleast_2d(Q)
        d = Q - self.c
        h = d @ self.a
        rv = d - h[:, None] * self.a
        u0 = np.arctan2(rv @ self.y, rv @ self.x)
        best_uv, best_d = None, None
        for u in (u0, u0 + math.pi):  # both tube circles of the meridian plane (spindle tori use both)
            eu = np.cos(u)[:, None] * self.x + np.sin(u)[:, None] * self.y
            q = d - self.R * eu  # from the tube centre
            v = np.arctan2(q @ self.a, np.einsum("ij,ij->i", q, eu))
            if self.r < 0:
                v = v + math.pi
            dist = np.linalg.norm(self.eval(u, v) - Q, axis=1)
            if best_uv is None:
                best_uv, best_d = np.column_stack([u, v]), dist
            else:
                take = dist < best_d
                best_uv[take] = np.column_stack([u, v])[take]
                best_d = np.where(take, dist, best_d)
        return best_uv, self.eval(best_uv[:, 0], best_uv[:, 1])

    def iso(self, which, c):
        if which == "v":
            rad = self.R + self.r * math.cos(c)
            if rad < 1e-12:
                return None
            return Circle(self.c + self.r * math.sin(c) * self.a, self.a, self.x, rad)
        d = math.cos(c) * self.x + math.sin(c) * self.y
        return Circle(self.c + self.R * d, np.cross(d, self.a), d, abs(self.r))

    def step(self, w):
        if self.r <= 0 or self.R == 0:
            raise GeomError("degenerate torus")
        # a negative major radius is the same surface as |R| at (u + pi, pi - v): the normal flips
        return (w.add(f"TOROIDAL_SURFACE('',{w.axis2(self.c, self.a, self.x)},{w.length(abs(self.R))},"
                      f"{w.length(self.r)})"), self.R < 0)


class BSurface(Surface):
    def __init__(self, du, dv, U, V, P, rational):
        self.du, self.dv, self.rational = du, dv, rational
        self.U, self.V, self.P = np.asarray(U, float), np.asarray(V, float), np.asarray(P, float)
        nu, nv = self.P.shape[:2]
        if len(self.U) != nu + du + 1 or len(self.V) != nv + dv + 1:
            raise GeomError("inconsistent B-spline surface")

    def eval(self, us, vs):
        return N.eval_surface(self.du, self.dv, self.U, self.V, self.P, us, vs, self.rational)

    def domain(self):
        nu, nv = self.P.shape[:2]
        return (self.U[self.du], self.U[nu], self.V[self.dv], self.V[nv])

    def uv_box(self):
        return self.domain()

    def iso(self, which, c):
        deg, K, Q = N.iso_curve(self.du, self.dv, self.U, self.V, self.P, which, c)
        return BSpline(deg, K, Q, self.rational, 3)

    def step(self, w):
        U, V, P = N.surface_clamp(self.du, self.dv, self.U, self.V, self.P)
        return w.bspline_surface(self.du, self.dv, U, V, P, self.rational), False


class Swept(Surface):
    """section(u) + v·sweep."""

    def __init__(self, section, sweep):
        self.sec, self.d = section, _v(sweep)
        if np.linalg.norm(self.d) == 0:
            raise GeomError("zero sweep")

    def eval(self, us, vs):
        return self.sec.eval(us) + np.asarray(vs, float)[:, None] * self.d

    def closest(self, Q, uv0=None):
        Q = np.atleast_2d(np.asarray(Q, float))
        dom = self.sec.domain()
        if dom is None:
            raise GeomError("swept surface without a bounded section")
        dn = _unit(self.d)

        def flat(ts):  # the section seen along the sweep
            c = self.sec.eval(ts)
            return c - (c @ dn)[:, None] * dn

        u = project_many(flat, Q - (Q @ dn)[:, None] * dn, dom[0], dom[1], period=self.sec.period)
        v = np.einsum("ij,j->i", Q - self.sec.eval(u), self.d) / float(self.d @ self.d)
        return np.column_stack([u, v]), self.eval(u, v)

    def _grid_guess(self, Q, n=24):
        dom = self.sec.domain()
        if dom is None:
            raise GeomError("swept surface without a bounded section")
        us = np.linspace(dom[0], dom[1], 4 * n)
        S = self.sec.eval(us)
        dd = float(np.dot(self.d, self.d))
        best = []
        for q in Q:  # the section point whose sweep line passes nearest q
            v = (q - S) @ self.d / dd
            e = q - S - v[:, None] * self.d
            i = int(np.argmin(np.einsum("ij,ij->i", e, e)))
            best.append((us[i], v[i]))
        return np.array(best)

    def iso(self, which, c):
        if which == "u":
            return _ScaledLine(self.sec.point(c), _unit(self.d), float(np.linalg.norm(self.d)))
        return moved(self.sec, t=c * self.d) or _Shifted(self.sec, c * self.d)

    def step(self, w):
        if not getattr(self.sec, "exact", False) or not hasattr(self.sec, "step"):
            raise GeomError("swept surface with an inexact section")
        vec = w.add(f"VECTOR('',{w.direction(self.d)},{w.length(float(np.linalg.norm(self.d)))})")
        return w.add(f"SURFACE_OF_LINEAR_EXTRUSION('',{self.sec.step(w)},{vec})"), False


class _Shifted(Curve):
    def __init__(self, c, off):
        self.c, self.off = c, np.asarray(off, float)
        self.exact = getattr(c, "exact", False)

    def eval(self, ts):
        return self.c.eval(ts) + self.off

    def domain(self):
        return self.c.domain()

    def project(self, q):
        return self.c.project(q - self.off)


def moved(c, R=None, t=None, about=None):
    """The curve c turned by the rotation matrix R about the point `about`, then shifted by t (exact)."""
    R = np.eye(3) if R is None else np.asarray(R, float)
    t = np.zeros(3) if t is None else np.asarray(t, float)
    o = np.zeros(3) if about is None else np.asarray(about, float)

    def pt(p):
        return R @ (np.asarray(p, float) - o) + o + t

    if isinstance(c, _ScaledLine):
        return _ScaledLine(pt(c.p), R @ c.d, c.L)
    if isinstance(c, Line):
        return Line(pt(c.p), R @ c.d)
    if isinstance(c, Circle):
        return Circle(pt(c.c), R @ c.n, R @ c.x, c.r)
    if isinstance(c, Ellipse):
        return Ellipse(pt(c.c), R @ c.n, R @ c.x, c.r1, c.r2)
    if isinstance(c, BSpline) and c.dim == 3:
        P = c.P.copy()
        if c.rational:
            wts = P[:, 3:4]
            xyz = P[:, :3] / wts
            P[:, :3] = (np.array([pt(q) for q in xyz])) * wts
        else:
            P = np.array([pt(q) for q in P[:, :3]])
        return BSpline(c.deg, c.U, P, c.rational, 3)
    return None


def _rot_matrix(axis, ang):
    a = _unit(axis)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * (K @ K)


def _rotate(pts, base, axis, ang):
    """pts (k, 3) turned by angles ang (k,) about the line (base, axis)."""
    q = pts - base
    c, s = np.cos(ang)[:, None], np.sin(ang)[:, None]
    return base + q * c + np.cross(axis, q) * s + axis * (q @ axis)[:, None] * (1 - c)


class Spun(Surface):
    """profile(u) turned by v about the axis."""

    def __init__(self, profile, base, axis):
        self.prof, self.base, self.axis = profile, _v(base), _unit(axis)

    def eval(self, us, vs):
        return _rotate(self.prof.eval(us), self.base, self.axis, np.asarray(vs, float))

    def closest(self, Q, uv0=None):
        Q = np.atleast_2d(np.asarray(Q, float))
        dom = self.prof.domain()
        if dom is None:
            raise GeomError("spun surface without a bounded profile")
        ax, b = self.axis, self.base

        def rh(pts):
            d = pts - b
            hh = d @ ax
            return np.column_stack([np.linalg.norm(d - hh[:, None] * ax, axis=1), hh])

        u = project_many(lambda ts: rh(self.prof.eval(ts)), rh(Q), dom[0], dom[1], period=self.prof.period)
        P0 = self.prof.eval(u) - b
        r0 = P0 - (P0 @ ax)[:, None] * ax
        dq = Q - b
        rq = dq - (dq @ ax)[:, None] * ax
        e1 = r0 / np.maximum(np.linalg.norm(r0, axis=1), 1e-300)[:, None]
        e2 = np.cross(ax, e1)
        v = np.arctan2(np.einsum("ij,ij->i", rq, e2), np.einsum("ij,ij->i", rq, e1))
        return np.column_stack([u, v]), self.eval(u, v)

    def _grid_guess(self, Q, n=24):
        dom = self.prof.domain()
        if dom is None:
            raise GeomError("spun surface without a bounded profile")
        us = np.linspace(dom[0], dom[1], 4 * n)
        Pr = self.prof.eval(us) - self.base
        hp = Pr @ self.axis
        ref = Pr - hp[:, None] * self.axis
        rp = np.linalg.norm(ref, axis=1)
        out = []
        for q in Q:  # the profile point at q's height and distance from the axis; then the turn angle
            d = q - self.base
            hq = float(d @ self.axis)
            rq = d - hq * self.axis
            i = int(np.argmin((hp - hq) ** 2 + (rp - np.linalg.norm(rq)) ** 2))
            a = ref[i] / max(float(np.linalg.norm(ref[i])), 1e-300)
            b = np.cross(self.axis, a)
            out.append((us[i], math.atan2(float(rq @ b), float(rq @ a))))
        return np.array(out)

    def iso(self, which, c):
        if which == "u":  # a circle through profile(c)
            p = self.prof.point(c)
            q = p - self.base
            h = float(np.dot(q, self.axis))
            rv = q - h * self.axis
            r = float(np.linalg.norm(rv))
            if r < 1e-12:
                return None
            return Circle(self.base + h * self.axis, self.axis, rv, r)
        return moved(self.prof, _rot_matrix(self.axis, c), about=self.base)  # the profile, turned

    def step(self, w):
        if not getattr(self.prof, "exact", False) or not hasattr(self.prof, "step"):
            raise GeomError("spun surface with an inexact profile")
        # STEP's revolution runs (angle, profile), Parasolid's (profile, angle): the normals are opposite
        return w.add(f"SURFACE_OF_REVOLUTION('',{self.prof.step(w)},{w.axis1(self.base, self.axis)})"), True


class Offset(Surface):
    """basis + d·(unit natural normal of the basis, with the basis' own sense)."""

    def __init__(self, basis, d, basis_sense):
        self.basis, self.d, self.bs = basis, float(d), basis_sense

    def eval(self, us, vs):
        return self.basis.eval(us, vs) + (self.d * self.bs) * self.basis.normal(us, vs)

    def uv_box(self):
        return self.basis.uv_box()

    def normal(self, us, vs, h=1e-6):
        return self.basis.normal(us, vs, h)  # parallel surfaces share their normals

    def closest(self, Q, uv0=None):
        uv, _ = self.basis.closest(Q, uv0)
        us, vs = uv[:, 0], uv[:, 1]
        return uv, self.basis.eval(us, vs) + (self.d * self.bs) * self.basis.normal(us, vs)

    def step(self, w):
        ref, flip = self.basis.step(w)
        # STEP offsets along the STEP basis' natural normal
        dist = self.d * self.bs * (-1.0 if flip else 1.0)
        return w.add(f"OFFSET_SURFACE('',{ref},{w.length(dist)},.F.)"), flip


def _n(x):
    from .step import num
    return num(x)


# ================================================================== from nodes
class Factory:
    """Curves and surfaces of a Model's geometry nodes (cached by node index)."""

    def __init__(self, model):
        self.m = model
        self._c, self._s = {}, {}

    def nurbs_curve(self, idx):
        n = self.m[idx]
        if n is None or n.type != "NURBS_CURVE":
            raise GeomError("missing NURBS curve")
        dim = n["vertex_dim"]
        rat = bool(n["rational"])
        verts = np.asarray(self.m[n["bspline_vertices"]]["vertices"], float).reshape(-1, dim)
        U = N.full_knots(self.m[n["knots"]]["knots"], self.m[n["knot_mult"]]["mult"])
        return BSpline(n["degree"], U, verts, rat, dim - (1 if rat else 0))

    def curve(self, idx):
        if idx in self._c:
            return self._c[idx]
        n = self.m[idx]
        if n is None:
            raise GeomError("missing curve")
        t = n.type
        f = n.f
        if t == "LINE":
            c = Line(f["pvec"], f["direction"])
        elif t == "CIRCLE":
            c = Circle(f["centre"], f["normal"], f["x_axis"], f["radius"])
        elif t == "ELLIPSE":
            c = Ellipse(f["centre"], f["normal"], f["x_axis"], f["major_radius"], f["minor_radius"])
        elif t == "B_CURVE":
            c = self.nurbs_curve(f["nurbs"])
        elif t == "SP_CURVE":
            bc = self.m[f["b_curve"]]
            if bc is None or bc.type != "B_CURVE":
                raise GeomError("SP-curve without its B-curve")
            S = self.surface(f["surface"])
            if not hasattr(S, "iso"):  # blends: Parasolid's parameters for them aren't known
                raise GeomError("curves on blend surfaces")
            c = SPCurve(S, self.nurbs_curve(bc["nurbs"]))
        elif t == "INTERSECTION":
            ch = self.m[f["chart"]]
            if ch is None:
                raise GeomError("intersection without a chart")
            pts = [h for h in ch["hvec"] if h is not None]
            c = ChartCurve(pts)
        elif t == "TRIMMED_CURVE":
            c = self.curve(f["basis_curve"])
        else:
            raise GeomError(f"{t.lower().replace('_', ' ')} curves")
        self._c[idx] = c
        return c

    def surface(self, idx):
        if idx in self._s:
            if self._s[idx] is None:
                raise GeomError("cyclic surface definition")
            return self._s[idx]
        n = self.m[idx]
        if n is None:
            raise GeomError("missing surface")
        t, f = n.type, n.f
        if t == "PLANE":
            s = Plane(f["pvec"], f["normal"], f["x_axis"])
        elif t == "CYLINDER":
            s = Cylinder(f["pvec"], f["axis"], f["radius"], f["x_axis"])
        elif t == "CONE":
            s = Cone(f["pvec"], f["axis"], f["radius"], f["sin_half_angle"], f["cos_half_angle"], f["x_axis"])
        elif t == "SPHERE":
            s = Sphere(f["centre"], f["radius"], f["axis"], f["x_axis"])
        elif t == "TORUS":
            s = Torus(f["centre"], f["axis"], f["major_radius"], f["minor_radius"], f["x_axis"])
        elif t == "B_SURFACE":
            s = self._bsurface(f["nurbs"])
        elif t == "SWEPT_SURF":
            s = Swept(self.curve(f["section"]), f["sweep"])
        elif t == "SPUN_SURF":
            s = Spun(self.curve(f["profile"]), f["base"], f["axis"])
        elif t == "OFFSET_SURF":
            b = self.m[f["surface"]]
            s = Offset(self.surface(f["surface"]), f["offset"], 1.0 if (b is None or b["sense"] == "+") else -1.0)
        elif t == "BLENDED_EDGE":
            from .blend import make_blend
            self._s[idx] = None  # guard against cycles
            try:
                s = make_blend(self, n)
            except BaseException:
                del self._s[idx]
                raise
        else:
            raise GeomError(f"{t.lower().replace('_', ' ')} surfaces")
        self._s[idx] = s
        return s

    def _bsurface(self, idx):
        n = self.m[idx]
        if n is None or n.type != "NURBS_SURF":
            raise GeomError("missing NURBS surface")
        dim = n["vertex_dim"]
        nu, nv = n["n_u_vertices"], n["n_v_vertices"]
        P = np.asarray(self.m[n["bspline_vertices"]]["vertices"], float).reshape(nu, nv, dim)
        U = N.full_knots(self.m[n["u_knots"]]["knots"], self.m[n["u_knot_mult"]]["mult"])
        V = N.full_knots(self.m[n["v_knots"]]["knots"], self.m[n["v_knot_mult"]]["mult"])
        return BSurface(n["u_degree"], n["v_degree"], U, V, P, bool(n["rational"]))
