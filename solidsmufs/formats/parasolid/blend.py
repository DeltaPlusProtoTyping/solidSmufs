"""Parasolid rolling-ball blends (BLENDED_EDGE surfaces), approximated as B-spline surfaces.

A BLENDED_EDGE is the surface swept by a ball rolling between two support surfaces: its spine (the ball
centre's path) is a curve, or an INTERSECTION of the supports' offsets; range[] holds the signed offsets
from the supports (|range| is the ball radius). The blend is, at each spine point C, the short circular arc
from C's foot point on support 0 to its foot point on support 1.

STEP has no such surface, so the part of it a face uses is sampled on a grid of (spine parameter t, arc
fraction b) and interpolated by a bicubic B-spline within FIT_TOL. Parasolid's own (u, v) parameters for
blends aren't known here, so SP-curves on blends aren't used (edges take their other side's curve).
"""

import numpy as np

from . import nurbs as N
from .geom import GeomError

FIT_TOL = 1e-6  # m


def foot(S, Q, uv0=None):
    """(nearest points on surface S, unit normals there, their parameters) for each row of Q."""
    if isinstance(S, Blend):
        uv, P = S.closest(Q)
        return P, S.normal_at(P), uv
    uv, P = S.closest(Q, uv0)
    return P, S.normal(uv[:, 0], uv[:, 1]), uv


def on_intersection(A, B, x, iters=10):
    """The points x moved onto the intersection of surfaces A and B (Newton steps: each one the nearest
    point of the line where the two tangent planes meet)."""
    uva = uvb = None
    for _ in range(iters):
        pa, na, uva = foot(A, x, uva)
        pb, nb, uvb = foot(B, x, uvb)
        c = np.einsum("ij,ij->i", na, nb)
        ra = -np.einsum("ij,ij->i", na, x - pa)
        rb = -np.einsum("ij,ij->i", nb, x - pb)
        det = 1 - c * c
        ok = det > 1e-10
        alpha = np.where(ok, (ra - c * rb) / np.where(ok, det, 1), 0.5 * ra)
        beta = np.where(ok, (rb - c * ra) / np.where(ok, det, 1), 0.5 * rb)
        step = alpha[:, None] * na + beta[:, None] * nb
        x = x + step
        if float(np.max(np.linalg.norm(step, axis=1))) < 1e-12:
            break
    return x


class Spine:
    """t -> ball centre. From an exact curve, or from an intersection: its chart, densified and moved onto
    the two surfaces once, then interpolated by a C2 spline (t in [0, 1])."""

    def __init__(self, curve=None, chart_pts=None, surfaces=None):
        self.curve, self.surfaces = curve, surfaces
        self.period = None
        self.P = None
        if curve is not None:
            self.lo, self.hi = curve.domain() if curve.domain() else (-1.0, 1.0)
            self.period = curve.period
            return
        P = np.asarray(chart_pts, float)
        keep = [0]
        for i in range(1, len(P)):
            if float(np.linalg.norm(P[i] - P[keep[-1]])) > 1e-9:
                keep.append(i)
        P = P[keep]
        if len(P) < 2:
            raise GeomError("blend spine chart too short")
        self.closed = float(np.linalg.norm(P[0] - P[-1])) < 1e-8
        self._chart = P
        self.lo, self.hi = 0.0, 1.0
        if self.closed:
            self.period = 1.0

    def _build(self):
        deg, U, S = N.interp_points(self._chart)
        knots = np.unique(U)
        ts = np.unique(np.concatenate([np.linspace(a, b, 3)[:-1] for a, b in zip(knots, knots[1:])] + [[1.0]]))
        X = N.eval_curve(deg, U, S, ts)
        if not self.closed and self.surfaces:
            # faces can reach a little past the chart: carry on along the end tangents, then onto the surfaces
            L = float(np.sum(np.linalg.norm(np.diff(X, axis=0), axis=1)))
            ext = max(0.25 * L, 1e-4)
            t0 = X[0] - X[1]
            t1 = X[-1] - X[-2]
            t0 /= max(float(np.linalg.norm(t0)), 1e-300)
            t1 /= max(float(np.linalg.norm(t1)), 1e-300)
            k = 4
            head = np.array([X[0] + t0 * ext * j / k for j in range(k, 0, -1)])
            tail = np.array([X[-1] + t1 * ext * j / k for j in range(1, k + 1)])
            X = np.vstack([head, X, tail])
        if self.surfaces:
            X = on_intersection(*self.surfaces, X)
            if not self.closed:  # keep the extension only where it really reached both surfaces
                A, B = self.surfaces
                ends = np.r_[0:4, len(X) - 4:len(X)]
                Xe = X[ends]
                ok = ((np.linalg.norm(foot(A, Xe)[0] - Xe, axis=1) < 1e-8)
                      & (np.linalg.norm(foot(B, Xe)[0] - Xe, axis=1) < 1e-8))
                good = np.ones(len(X), bool)
                good[ends] = ok
                lo = 0
                while lo < 4 and not good[lo:4].all():
                    lo += 1
                hi = len(X)
                while hi > len(X) - 4 and not good[len(X) - 4:hi].all():
                    hi -= 1
                X = X[lo:hi]
        if self.closed:
            X[-1] = X[0]
        keep = [0]
        for i in range(1, len(X)):
            if float(np.linalg.norm(X[i] - X[keep[-1]])) > 1e-10:
                keep.append(i)
        self.deg, self.U, self.P = N.interp_points(X[keep])

    def eval(self, ts):
        ts = np.atleast_1d(np.asarray(ts, float))
        if self.curve is not None:
            return self.curve.eval(ts)
        if self.P is None:
            self._build()
        if self.period:
            ts = self.lo + np.mod(ts - self.lo, self.period)
        return N.eval_curve(self.deg, self.U, self.P, ts)

    _approx = eval

    def project(self, Q):
        """Spine parameters of the points nearest each row of Q."""
        from .geom import project_many
        Q = np.atleast_2d(Q)
        if self.curve is not None and self.curve.domain() is None:  # a line
            return np.array([self.curve.project(q) for q in Q])
        if self.curve is None and self.P is None:
            self._build()
        n = 257 if self.curve is not None else max(257, 2 * len(self.P) + 1)
        return project_many(self.eval, Q, self.lo, self.hi, n=n, period=self.period)


class Blend:
    """A rolling-ball blend: supports s0, s1, spine, ball radius r."""
    exact = False

    def __init__(self, s0, s1, spine, r):
        # r = 0: a blend down to its spine (an edge another blend rolls along: blend type 'E')
        self.s0, self.s1, self.spine, self.r = s0, s1, spine, abs(float(r))

    def section(self, ts):
        """Spine points C, the arc's start direction e0, its in-plane normal w, its angle and radius."""
        if self.r <= 0:
            raise GeomError("face on a blend of zero radius")
        ts = np.atleast_1d(np.asarray(ts, float))
        cache = self.__dict__.setdefault("_sec", {})
        miss = [t for t in ts.tolist() if t not in cache]
        if miss:
            for t, row in zip(miss, zip(*self._section(np.array(miss)))):
                cache[t] = row
        rows = [cache[t] for t in ts.tolist()]
        return tuple(np.array([r[i] for r in rows]) for i in range(5))

    def _section(self, ts):
        C = self.spine.eval(ts)
        _, F0 = self.s0.closest(C)
        _, F1 = self.s1.closest(C)
        d0, d1 = F0 - C, F1 - C
        l0, l1 = np.linalg.norm(d0, axis=1), np.linalg.norm(d1, axis=1)
        if float(np.min(l0)) < 1e-12 or float(np.min(l1)) < 1e-12:
            raise GeomError("blend touching its spine")
        e0, e1 = d0 / l0[:, None], d1 / l1[:, None]
        cth = np.clip(np.einsum("ij,ij->i", e0, e1), -1.0, 1.0)
        th = np.arccos(cth)
        sth = np.sin(th)
        w = (e1 - cth[:, None] * e0) / np.where(sth > 1e-12, sth, 1.0)[:, None]
        return C, e0, w, th, (l0 + l1) / 2

    def grid(self, ts, bs):
        C, e0, w, th, r = self.section(ts)
        bs = np.asarray(bs, float)
        ang = th[:, None] * bs[None, :]
        return (C[:, None, :] + r[:, None, None] * (np.cos(ang)[..., None] * e0[:, None, :]
                                                     + np.sin(ang)[..., None] * w[:, None, :]))

    def params(self, Q):
        """(t, b) of points on (or near) the blend."""
        Q = np.atleast_2d(Q)
        ts = self.spine.project(Q)
        C, e0, w, th, _r = self.section(ts)
        d = Q - C
        phi = np.arctan2(np.einsum("ij,ij->i", d, w), np.einsum("ij,ij->i", d, e0))
        return ts, phi / np.where(th > 1e-12, th, 1.0)

    def closest(self, Q, uv0=None):
        """Nearest points on the ball tube (for blends that support other blends)."""
        Q = np.atleast_2d(Q)
        ts = self.spine.project(Q)
        C = self.spine.eval(ts)
        if self.r <= 0:
            return np.column_stack([ts, np.zeros(len(ts))]), C
        d = Q - C
        ln = np.maximum(np.linalg.norm(d, axis=1), 1e-300)
        return np.column_stack([ts, np.zeros(len(ts))]), C + self.r * d / ln[:, None]

    def normal_at(self, Q):
        """Unit normals pointing away from the ball centre at points near the blend."""
        Q = np.atleast_2d(Q)
        C = self.spine.eval(self.spine.project(Q))
        d = Q - C
        return d / np.maximum(np.linalg.norm(d, axis=1), 1e-300)[:, None]

    def fit(self, samples, tol=FIT_TOL):
        """(du, dv, U, V, P) of a bicubic B-spline covering the blend around sample points of a face's boundary,
        parametrised by (t along the spine, b across)."""
        ts, bs = self.params(samples)
        sp = self.spine
        if sp.period:
            L = sp.period
            tt = np.sort(np.mod(ts - sp.lo, L))
            gaps = np.diff(np.concatenate([tt, [tt[0] + L]]))
            k = int(np.argmax(gaps))
            if gaps[k] < 0.05 * L:  # all the way round
                t0, t1 = sp.lo, sp.lo + L
            else:
                t0 = sp.lo + tt[(k + 1) % len(tt)]
                t1 = t0 + (L - gaps[k])
                m = 0.03 * (t1 - t0) + 1e-9
                t0, t1 = t0 - m, t1 + m
        else:
            t0, t1 = float(ts.min()), float(ts.max())
            m = 0.03 * (t1 - t0) + 1e-9
            t0, t1 = max(t0 - m, sp.lo), min(t1 + m, sp.hi)
        b0, b1 = float(bs.min()), float(bs.max())
        mb = 0.03 * (b1 - b0) + 1e-6
        b0, b1 = b0 - mb, b1 + mb
        if t1 - t0 <= 1e-12:
            raise GeomError("degenerate blend face")
        r = N.fit_surface_grid(self.grid, t0, t1, b0, b1, tol, max_n=49)
        if r is None:
            raise GeomError("blend surface fit failed")
        return r


def make_blend(factory, node):
    """A Blend from a BLENDED_EDGE node."""
    m = factory.m
    f = node.f
    if f["blend_type"] not in ("R", "E"):
        raise GeomError(f"blend type {f['blend_type']!r}")
    s0, s1 = (factory.surface(i) for i in f["surface"])
    rr = [x for x in (f["range"] or []) if x is not None]
    if not rr:
        raise GeomError("blend without a radius")
    r = max(abs(x) for x in rr)
    sp = m[f["spine"]]
    if sp is None:
        raise GeomError("blend without a spine")
    if sp.type == "INTERSECTION":
        ch = m[sp["chart"]]
        pts = [h for h in (ch["hvec"] if ch else []) if h is not None]
        surfs = tuple(factory.surface(i) for i in sp["surface"])
        spine = Spine(chart_pts=pts, surfaces=surfs)
    else:
        spine = Spine(curve=factory.curve(f["spine"]))
    b = Blend(s0, s1, spine, r)
    b.kind = f["blend_type"]
    return b

