"""B-spline math on numpy arrays: evaluation, knot insertion, clamping / trimming, and fitting.

Control points are rows; rational ones are homogeneous (x·w, y·w, z·w, w). Knot vectors are full
(every knot repeated by its multiplicity) and may be unclamped (Parasolid's periodic splines are).
"""

import numpy as np


def full_knots(knots, mults):
    return np.repeat(np.asarray(knots, float), np.asarray(mults, int))


def compress_knots(U, tol=0.0):
    """(distinct knots, multiplicities) of a full knot vector."""
    ks, ms = [], []
    for u in U:
        if ks and abs(u - ks[-1]) <= tol:
            ms[-1] += 1
        else:
            ks.append(float(u))
            ms.append(1)
    return ks, ms


def basis_funs(deg, U, ts):
    """(first index (k,), values (k, deg + 1)): the basis functions that can be non-zero at each t,
    N_first .. N_first+deg (t clamped into the domain)."""
    U = np.asarray(U, float)
    t = np.atleast_1d(np.asarray(ts, float))
    n = len(U) - deg - 1
    t = np.minimum(np.maximum(t, U[deg]), U[n])
    span = np.searchsorted(U, t, side="right") - 1
    span = np.minimum(np.maximum(span, deg), n - 1)
    m = len(t)
    N = np.zeros((m, deg + 1))
    N[:, 0] = 1.0
    left = np.zeros((m, deg + 1))
    right = np.zeros((m, deg + 1))
    for j in range(1, deg + 1):
        left[:, j] = t - U[span + 1 - j]
        right[:, j] = U[span + j] - t
        saved = np.zeros(m)
        for r in range(j):
            den = right[:, r + 1] + left[:, j - r]
            temp = np.divide(N[:, r], den, out=np.zeros(m), where=den != 0)
            N[:, r] = saved + right[:, r + 1] * temp
            saved = left[:, j - r] * temp
        N[:, j] = saved
    return span - deg, N


def basis_matrix(deg, U, ts):
    """(len(ts), n) matrix of the basis functions N_i,deg at ts (clamped into the domain)."""
    U = np.asarray(U, float)
    t = np.atleast_1d(np.asarray(ts, float))
    n = len(U) - deg - 1
    t = np.clip(t, U[deg], U[n])
    span = np.clip(np.searchsorted(U, t, side="right") - 1, deg, n - 1)
    m = len(t)
    N = np.zeros((m, deg + 1))
    N[:, 0] = 1.0
    left = np.zeros((m, deg + 1))
    right = np.zeros((m, deg + 1))
    for j in range(1, deg + 1):
        left[:, j] = t - U[span + 1 - j]
        right[:, j] = U[span + j] - t
        saved = np.zeros(m)
        for r in range(j):
            den = right[:, r + 1] + left[:, j - r]
            temp = np.divide(N[:, r], den, out=np.zeros(m), where=den != 0)
            N[:, r] = saved + right[:, r + 1] * temp
            saved = left[:, j - r] * temp
        N[:, j] = saved
    M = np.zeros((m, n))
    cols = span[:, None] - deg + np.arange(deg + 1)[None, :]
    M[np.arange(m)[:, None], cols] = N
    return M


def eval_curve(deg, U, P, ts, rational=False):
    i0, Nb = basis_funs(deg, U, ts)
    idx = i0[:, None] + np.arange(deg + 1)[None, :]
    pts = np.einsum("ki,kid->kd", Nb, np.asarray(P)[idx])
    return pts[:, :-1] / pts[:, -1:] if rational else pts


def eval_surface(du, dv, U, V, P, us, vs, rational=False):
    """Points at the pairs (us[k], vs[k]); P has shape (nu, nv, dim)."""
    iu, Nu = basis_funs(du, U, us)
    iv, Nv = basis_funs(dv, V, vs)
    a = iu[:, None] + np.arange(du + 1)[None, :]
    b = iv[:, None] + np.arange(dv + 1)[None, :]
    blk = np.asarray(P)[a[:, :, None], b[:, None, :]]  # (k, du+1, dv+1, dim)
    pts = np.einsum("ki,kj,kijd->kd", Nu, Nv, blk)
    return pts[:, :-1] / pts[:, -1:] if rational else pts


# ------------------------------------------------------------------ knot insertion, clamping, trimming
def insert_knot(deg, U, P, t, r=1):
    """(U, P) with t inserted r more times (up to multiplicity deg). P: (n, dim)."""
    U = np.asarray(U, float)
    P = np.asarray(P, float)
    n = len(P) - 1
    s = int(np.sum(np.abs(U - t) <= 1e-14 * max(1.0, abs(t))))
    r = min(r, deg - s)
    if r <= 0:
        return U, P
    k = int(np.searchsorted(U, t, side="right") - 1)
    # the span t starts: up to n + s, so a knot already at the domain's end (an unclamped, periodic
    # spline's U[n + 1]) is raised there rather than in the span before it
    k = min(max(k, deg), n + s)
    Q = np.zeros((n + 1 + r, P.shape[1]))
    Q[:k - deg + 1] = P[:k - deg + 1]
    Q[k - s + r:] = P[k - s:]
    R = P[k - deg:k - s + 1].copy()
    L = k - deg
    for j in range(1, r + 1):
        L = k - deg + j
        for i in range(deg - j - s + 1):
            den = U[i + k + 1] - U[L + i]
            alpha = (t - U[L + i]) / den if den else 0.0
            R[i] = alpha * R[i + 1] + (1.0 - alpha) * R[i]
        Q[L] = R[0]
        Q[k + r - j - s] = R[deg - j - s]
    for i in range(L + 1, k - s):
        Q[i] = R[i - L]
    U2 = np.concatenate([U[:k + 1], np.full(r, t), U[k + 1:]])
    return U2, Q


def segment(deg, U, P, a=None, b=None):
    """The clamped B-spline equal to the curve on [a, b] (default: its whole domain)."""
    U = np.asarray(U, float)
    n = len(P) - 1
    lo, hi = U[deg], U[n + 1]
    a = lo if a is None else min(max(a, lo), hi)
    b = hi if b is None else min(max(b, lo), hi)
    if b < a:
        a, b = b, a
    U2, P2 = insert_knot(deg, U, P, a, deg)
    U2, P2 = insert_knot(deg, U2, P2, b, deg)
    ia = int(np.searchsorted(U2, a, side="right")) - 1  # last index of a's run
    ib = int(np.searchsorted(U2, b, side="left"))  # first index of b's run
    i0, i1 = ia - deg, ib - 1
    if i0 < 0 or i1 > len(P2) - 1 or i1 - i0 < deg:
        return np.concatenate([[a] * (deg + 1), [b] * (deg + 1)]), P2[max(i0, 0):max(i0, 0) + deg + 1]
    knots = np.concatenate([[a] * (deg + 1), U2[ia + 1:ib], [b] * (deg + 1)])
    return knots, P2[i0:i1 + 1]


def surface_clamp(du, dv, U, V, P):
    """(U, V, P) clamped at the domain ends in both directions (P: (nu, nv, dim))."""
    nu, nv, dim = P.shape
    if not _clamped(du, U):
        rows = [segment(du, U, P[:, j, :]) for j in range(nv)]
        U = rows[0][0]
        P = np.stack([r[1] for r in rows], axis=1)
    if not _clamped(dv, V):
        cols = [segment(dv, V, P[i]) for i in range(P.shape[0])]
        V = cols[0][0]
        P = np.stack([c[1] for c in cols], axis=0)
    return U, V, P


def _clamped(deg, U):
    U = np.asarray(U)
    return bool(np.all(U[:deg + 1] == U[0]) and np.all(U[-deg - 1:] == U[-1]))


def iso_curve(du, dv, U, V, P, which, value):
    """The (homogeneous) control points and knots of the surface's iso-curve u=value ('u') or v=value ('v')."""
    if which == "u":  # fixed u: a curve in v
        N = basis_matrix(du, U, [value])[0]
        return dv, V, np.einsum("i,ijd->jd", N, P)
    N = basis_matrix(dv, V, [value])[0]
    return du, U, np.einsum("j,ijd->id", N, P)


# ------------------------------------------------------------------ fitting
def interp_cubic(params, pts, deg=3):
    """A non-rational B-spline of degree deg through pts at params (increasing): (knots, control points)."""
    t = np.asarray(params, float)
    Q = np.asarray(pts, float)
    m = len(t)
    deg = min(deg, m - 1)
    if deg < 1:
        raise ValueError("need two points")
    U = np.concatenate([[t[0]] * (deg + 1),
                        [np.mean(t[j:j + deg]) for j in range(1, m - deg)],
                        [t[-1]] * (deg + 1)])
    A = basis_matrix(deg, U, t)
    A[-1, :] = 0.0
    A[-1, -1] = 1.0
    A[0, :] = 0.0
    A[0, 0] = 1.0
    P = np.linalg.solve(A, Q)
    return deg, U, P


def hermite_bspline(ts, P, D):
    """The C1 cubic B-spline (double interior knots) with points P and tangents D at parameters ts."""
    h = np.diff(ts)[:, None]
    B1 = P[:-1] + D[:-1] * h / 3
    B2 = P[1:] - D[1:] * h / 3
    poles = [P[0]]
    for i in range(len(h)):
        poles += [B1[i], B2[i]]
    poles.append(P[-1])
    knots = np.concatenate([[ts[0]] * 4, np.repeat(ts[1:-1], 2), [ts[-1]] * 4])
    return 3, knots, np.array(poles)


def interp_points(pts):
    """A C2 cubic spline through pts (chord-length parameters on [0, 1], Bessel end tangents), as a
    B-spline: (3, knots, poles). Tridiagonal solve, linear time."""
    P = np.asarray(pts, float)
    n = len(P) - 1
    if n < 1:
        raise ValueError("need two points")
    t = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    if t[-1] <= 0:
        raise ValueError("coincident points")
    t /= t[-1]
    h = np.diff(t)
    if n == 1:
        D = np.vstack([P[1] - P[0], P[1] - P[0]]) / h[0]
        return hermite_bspline(t, P, D)
    s = np.diff(P, axis=0) / h[:, None]  # chord slopes
    D = np.zeros_like(P)
    # Bessel ends: the parabola through the first (last) three points
    D[0] = s[0] + (s[0] - s[1]) * h[0] / (h[0] + h[1])
    D[-1] = s[-1] + (s[-1] - s[-2]) * h[-1] / (h[-1] + h[-2])
    if n >= 2:
        m = n - 1  # unknowns D[1..n-1]
        a = h[1:].copy()  # sub-diagonal coefficient of D[i-1] (row i): h_i
        b = 2 * (h[:-1] + h[1:])
        c = h[:-1].copy()  # super-diagonal: h_{i-1}
        r = 3 * (h[1:, None] * s[:-1] + h[:-1, None] * s[1:])
        r[0] -= a[0] * D[0]
        r[-1] -= c[-1] * D[-1]
        # Thomas algorithm
        cp = np.zeros(m)
        rp = np.zeros((m, P.shape[1]))
        cp[0] = c[0] / b[0]
        rp[0] = r[0] / b[0]
        for i in range(1, m):
            den = b[i] - a[i] * cp[i - 1]
            cp[i] = c[i] / den
            rp[i] = (r[i] - a[i] * rp[i - 1]) / den
        x = np.zeros((m, P.shape[1]))
        x[-1] = rp[-1]
        for i in range(m - 2, -1, -1):
            x[i] = rp[i] - cp[i] * x[i + 1]
        D[1:-1] = x
    return hermite_bspline(t, P, D)


def fit_curve(f, t0, t1, tol, breaks=(), max_spans=3000):
    """A cubic B-spline through f(ts) -> (k, 3) from t0 to t1 (either way round), within tol.

    Piecewise cubic Hermite: points and (numerical) tangents of f at samples, split where the error at a
    span's middle exceeds tol; C1 joints, C0 where f has a corner. Purely local: no linear systems.
    Returns (3, knots, poles, max error) or None if it can't get within tol."""
    lo, hi = min(t0, t1), max(t0, t1)
    if hi - lo <= 0:
        return None
    base = sorted({lo, hi, *[b for b in breaks if lo < b < hi]})
    ts = np.unique(np.concatenate([np.linspace(a, b, 3)[:-1] for a, b in zip(base, base[1:])] + [[hi]]))
    eps = 1e-7 * (hi - lo)
    for _ in range(40):
        P = f(ts)
        n = len(ts)
        tl = np.maximum(ts - eps, lo)
        tr = np.minimum(ts + eps, hi)
        Pl, Pr = f(tl), f(tr)
        with np.errstate(invalid="ignore", divide="ignore"):
            Dl = (P - Pl) / np.where(ts - tl > 0, ts - tl, 1)[:, None]
            Dr = (Pr - P) / np.where(tr - ts > 0, tr - ts, 1)[:, None]
        Dl[0], Dr[-1] = Dr[0], Dl[-1]
        Dc = np.where(((ts > lo) & (ts < hi))[:, None], (Pr - Pl) / np.maximum(tr - tl, 1e-300)[:, None], Dr)
        Dc[-1] = Dl[-1]
        # a corner where the one-sided tangents disagree
        scale = np.maximum(np.linalg.norm(Dc, axis=1), 1e-300)
        corner = np.linalg.norm(Dl - Dr, axis=1) > 1e-3 * scale
        corner[0] = corner[-1] = False
        Da = np.where(corner[:, None], Dr, Dc)  # leaving each sample
        Db = np.where(corner[:, None], Dl, Dc)  # arriving at it
        h = np.diff(ts)[:, None]
        B1 = P[:-1] + Da[:-1] * h / 3
        B2 = P[1:] - Db[1:] * h / 3
        mids = (ts[:-1] + ts[1:]) / 2
        bez = (P[:-1] + 3 * B1 + 3 * B2 + P[1:]) / 8
        err = np.linalg.norm(bez - f(mids), axis=1)
        bad = err > tol
        if not bad.any():
            break
        if n + int(bad.sum()) > max_spans:
            return None
        ts = np.sort(np.concatenate([ts, mids[bad]]))
    else:
        return None
    # B-spline: knots doubled at smooth joints (C1), tripled at corners (C0)
    knots = [ts[0]] * 4
    poles = [P[0], B1[0], B2[0]]
    for i in range(1, n - 1):
        if corner[i]:
            knots += [ts[i]] * 3
            poles += [P[i], B1[i], B2[i]]
        else:
            knots += [ts[i]] * 2
            poles += [B1[i], B2[i]]
    knots += [ts[-1]] * 4
    poles.append(P[-1])
    U, Q = np.array(knots), np.array(poles)
    if t1 < t0:  # run the other way
        U = (lo + hi) - U[::-1]
        Q = Q[::-1]
    return 3, U, Q, float(err.max())


def fit_surface_grid(f_grid, u0, u1, v0, v1, tol, max_n=65):
    """Bicubic B-spline interpolating f_grid(us, vs) -> (nu, nv, 3) on a box, refined until the error at the
    grid's cell centres is within tol. Returns (du, dv, U, V, P (nu, nv, 3), max error) or None."""
    nu, nv = 5, 5
    while True:
        us, vs = np.linspace(u0, u1, nu), np.linspace(v0, v1, nv)
        G = f_grid(us, vs)
        try:
            dv, V, R = interp_cubic(vs, G.transpose(1, 0, 2).reshape(nv, -1))  # every row at once
            R = R.reshape(-1, nu, 3).transpose(1, 0, 2)  # (nu, n poles in v, 3)
            du, U, P = interp_cubic(us, R.reshape(nu, -1))
            P = P.reshape(-1, R.shape[1], 3)
        except (ValueError, np.linalg.LinAlgError):
            return None
        um, vm = (us[:-1] + us[1:]) / 2, (vs[:-1] + vs[1:]) / 2
        T = f_grid(um, vm)
        uu, vv = np.repeat(um, len(vm)), np.tile(vm, len(um))
        e = np.linalg.norm(eval_surface(du, dv, U, V, P, uu, vv) - T.reshape(-1, 3), axis=1).reshape(len(um), len(vm))
        err = float(e.max())
        if err <= tol:
            return du, dv, U, V, P, err
        # refine the direction(s) the error comes from
        grow_u = nu < max_n
        grow_v = nv < max_n
        if not grow_u and not grow_v:
            return du, dv, U, V, P, err
        if grow_u and grow_v:
            # cheap test: error along u-midlines only (v at grid values) tells if u needs points
            Tu = f_grid(um, vs)
            uu2, vv2 = np.repeat(um, nv), np.tile(vs, len(um))
            e_u = float(np.linalg.norm(eval_surface(du, dv, U, V, P, uu2, vv2) - Tu.reshape(-1, 3), axis=1).max())
            grow_u = e_u > tol * 0.5
            grow_v = err > tol and (not grow_u or e_u < err * 0.9)
            if not grow_u and not grow_v:
                grow_u = grow_v = True
        if grow_u:
            nu = min(max_n, nu * 2 - 1)
        if grow_v:
            nv = min(max_n, nv * 2 - 1)
