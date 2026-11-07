"""Turning exact surfaces into triangles, for the formats that store only those: B-spline evaluation, and meshing a surface
inside its trim loops. Meshing happens flat in the surface's parameter space, stretched so a parameter step comes out about
the same length on the surface: the loops are clipped into triangles, then edges inside are split until they follow the
surface. It's all plain loops with limits, so a badly behaved face can't hang it, as one could a mesher called from here.
"""

import math

import numpy as np


# ---------------------------------------------------------------------------------------------- B-splines
def expand_knots(values, multiplicities):
    return np.repeat(np.asarray(values, float), np.asarray(multiplicities, int))


def basis(knots, degree, t):
    """For each parameter: its knot span, and the degree + 1 basis functions that aren't zero there (the standard triangle
    of divided differences, run over all parameters at once)."""
    knots = np.asarray(knots, float)
    t = np.asarray(t, float).ravel()
    count = len(knots) - degree - 1
    low, high = knots[degree], knots[count]
    t = np.clip(t, low, high)
    span = np.clip(np.searchsorted(knots, t, side="right") - 1, degree, count - 1)
    n = np.zeros((len(t), degree + 1))
    n[:, 0] = 1.0
    left, right = np.zeros((len(t), degree + 1)), np.zeros((len(t), degree + 1))
    for j in range(1, degree + 1):
        left[:, j] = t - knots[span + 1 - j]
        right[:, j] = knots[span + j] - t
        saved = np.zeros(len(t))
        for r in range(j):
            size = right[:, r + 1] + left[:, j - r]
            part = np.divide(n[:, r], size, out=np.zeros(len(t)), where=size != 0)
            n[:, r] = saved + right[:, r + 1] * part
            saved = left[:, j - r] * part
        n[:, j] = saved
    return span, n


def curve_points(knots, degree, control, t, weights=None):
    """Points of a B-spline curve: control (n, k), for any dimension k."""
    control = np.asarray(control, float)
    span, n = basis(knots, degree, t)
    index = span[:, None] - degree + np.arange(degree + 1)
    if weights is None:
        return (n[..., None] * control[index]).sum(axis=1)
    w = np.asarray(weights, float)[index] * n
    return (w[..., None] * control[index]).sum(axis=1) / w.sum(axis=1, keepdims=True)


def surface_points(knots_u, degree_u, knots_v, degree_v, control, u, v, weights=None):
    """Points of a B-spline surface at matching (u, v): control (nu, nv, 3), weights (nu, nv) or None."""
    control = np.asarray(control, float)
    su, nu = basis(knots_u, degree_u, u)
    sv, nv = basis(knots_v, degree_v, v)
    iu = su[:, None] - degree_u + np.arange(degree_u + 1)
    iv = sv[:, None] - degree_v + np.arange(degree_v + 1)
    # (points, degree_u + 1, degree_v + 1)
    cu, cv = iu[:, :, None], iv[:, None, :]
    w = nu[:, :, None] * nv[:, None, :]
    if weights is None:
        return (w[..., None] * control[cu, cv]).sum(axis=(1, 2))
    w = w * np.asarray(weights, float)[cu, cv]
    return (w[..., None] * control[cu, cv]).sum(axis=(1, 2)) / w.sum(axis=(1, 2))[:, None]


# ---------------------------------------------------------------------------------------------- how finely
def _steps(lengths_over_cells, chord_error, tolerance, limit):
    """Cells needed along one direction so the worst chord stays inside the tolerance: error falls with the square of the step."""
    if chord_error <= tolerance or chord_error == 0:
        return 1
    return int(min(limit, max(2, math.ceil(math.sqrt(chord_error / tolerance) * lengths_over_cells))))


def resolution(surface, box, tolerance, limit=96):
    """How many cells this surface needs across its parameter box (u0, u1, v0, v1), from how far it strays from straight
    lines on a probing grid. Returns (cells u, cells v, length along u, length along v)."""
    u0, u1, v0, v1 = box
    probes = 9
    us, vs = np.linspace(u0, u1, probes), np.linspace(v0, v1, probes)
    uu, vv = np.meshgrid(us, vs, indexing="ij")
    p = surface(uu.ravel(), vv.ravel()).reshape(probes, probes, 3)
    along_u = np.linalg.norm(np.diff(p, axis=0), axis=2)
    along_v = np.linalg.norm(np.diff(p, axis=1), axis=2)
    # the middle of each probe step against the midpoint of its ends
    du = (u1 - u0) / (probes - 1) / 2
    dv = (v1 - v0) / (probes - 1) / 2
    mid_u = surface((uu[:-1] + du).ravel(), vv[:-1].ravel()).reshape(probes - 1, probes, 3)
    mid_v = surface(uu[:, :-1].ravel(), (vv[:, :-1] + dv).ravel()).reshape(probes, probes - 1, 3)
    sag_u = float(np.linalg.norm(mid_u - (p[:-1] + p[1:]) / 2, axis=2).max())
    sag_v = float(np.linalg.norm(mid_v - (p[:, :-1] + p[:, 1:]) / 2, axis=2).max())
    return (_steps(probes - 1, sag_u, tolerance, limit), _steps(probes - 1, sag_v, tolerance, limit),
            float(along_u.sum(axis=0).max()), float(along_v.sum(axis=1).max()))


# ---------------------------------------------------------------------------------------------- meshing
def _clean_loop(loop):
    """A loop's points without repeats, and without closing back onto its start."""
    loop = np.asarray(loop, float)
    if len(loop) < 3:
        return None
    span = float(np.ptp(loop, axis=0).max())
    if span == 0:
        return None
    keep = np.linalg.norm(np.diff(loop, axis=0, append=loop[:1]), axis=1) > span * 1e-9
    loop = loop[keep]
    return loop if len(loop) >= 3 else None


def signed_area(loop):
    x, y = loop[:, 0], loop[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def box_loop(u0, u1, v0, v1, per_side=8):
    """The whole of a parameter box as a loop, for a face that isn't trimmed."""
    side = np.linspace(0.0, 1.0, per_side, endpoint=False)
    return np.vstack([np.column_stack([u0 + (u1 - u0) * side, np.full(per_side, v0)]),
                      np.column_stack([np.full(per_side, u1), v0 + (v1 - v0) * side]),
                      np.column_stack([u1 - (u1 - u0) * side, np.full(per_side, v1)]),
                      np.column_stack([np.full(per_side, u0), v1 - (v1 - v0) * side])])


def _cross2(a, b, c):
    return (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])


def _ear_clip(points, ring):
    """Triangles of one simple polygon, given as indices running counter-clockwise. It always finishes: if bad data leaves no
    proper ear, the most convex corner goes anyway, and the caller's area check finds what that did. Only a corner that turns
    the wrong way can lie inside an ear, so only those are tested against."""
    count = len(ring)
    if count < 3:
        return []
    xs, ys = points[ring, 0].tolist(), points[ring, 1].tolist()
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    flat = span * span * 1e-12  # less than this is a straight run, not a corner
    before = [(k - 1) % count for k in range(count)]
    after = [(k + 1) % count for k in range(count)]

    def turn(k):
        a, c = before[k], after[k]
        return (xs[k] - xs[a]) * (ys[c] - ys[a]) - (ys[k] - ys[a]) * (xs[c] - xs[a])

    reflex = {k for k in range(count) if turn(k) <= flat}
    triangles = []

    def remove(k):
        nonlocal count
        a, c = before[k], after[k]
        after[a], before[c] = c, a
        reflex.discard(k)
        count -= 1
        for j in (a, c):
            if turn(j) <= flat:
                reflex.add(j)
            else:
                reflex.discard(j)

    at, misses = 0, 0
    while count > 3:
        if at not in reflex:
            a, c = before[at], after[at]
            ax, ay, bx, by, cx, cy = xs[a], ys[a], xs[at], ys[at], xs[c], ys[c]
            low_x, high_x = min(ax, bx, cx), max(ax, bx, cx)
            low_y, high_y = min(ay, by, cy), max(ay, by, cy)
            clear = True
            for r in reflex:
                x, y = xs[r], ys[r]
                if x < low_x or x > high_x or y < low_y or y > high_y or r == a or r == c:
                    continue
                if (x == ax and y == ay) or (x == bx and y == by) or (x == cx and y == cy):
                    continue  # the two sides of a bridge between loops
                if ((bx - ax) * (y - ay) - (by - ay) * (x - ax) >= 0 and (cx - bx) * (y - by) - (cy - by) * (x - bx) >= 0
                        and (ax - cx) * (y - cy) - (ay - cy) * (x - cx) >= 0):
                    clear = False
                    break
            if clear:
                triangles.append((ring[a], ring[at], ring[c]))
                remove(at)
                at = after[c]  # on from here, so triangles don't all fan from one corner
                misses = 0
                continue
        at = after[at]
        misses += 1
        if misses > count:
            best, best_turn = at, -math.inf
            k = at
            for _ in range(count):
                t = turn(k)
                if t > best_turn:
                    best, best_turn = k, t
                k = after[k]
            if best_turn > 0:
                triangles.append((ring[before[best]], ring[best], ring[after[best]]))
            at = after[best]
            remove(best)
            misses = 0
    if count == 3:
        a, c = before[at], after[at]
        if turn(at) > 0:
            triangles.append((ring[a], ring[at], ring[c]))
    return triangles


def _crosses(p, q, a, b):
    """Does segment p-q properly cross any of the segments a[i]-b[i]?"""
    d1, d2 = _cross2(a, b, p), _cross2(a, b, q)
    d3, d4 = _cross2(p, q, a), _cross2(p, q, b)
    return bool((((d1 > 0) & (d2 < 0) | (d1 < 0) & (d2 > 0)) & ((d3 > 0) & (d4 < 0) | (d3 < 0) & (d4 > 0))).any())


def _bridge(points, outer, holes):
    """Holes joined to the outer ring by a cut each, nearest first from the right: one ring to clip."""
    ring = list(outer)
    order = sorted(holes, key=lambda h: -float(points[h, 0].max()))
    for done, hole in enumerate(order):
        from_here = int(np.argmax(points[hole, 0]))
        p = points[hole[from_here]]
        current = np.array(ring)
        rest = [h for h in order[done:]]
        a = np.vstack([points[current]] + [points[h] for h in rest])
        b = np.vstack([np.roll(points[current], -1, axis=0)] + [np.roll(points[h], -1, axis=0) for h in rest])
        distance = np.linalg.norm(points[current] - p, axis=1)
        pick = None
        for k in np.argsort(distance)[:64]:
            if not _crosses(p, points[current[k]], a, b):
                pick = int(k)
                break
        if pick is None:
            pick = int(distance.argmin())
        turned = list(hole[from_here:]) + list(hole[:from_here])
        ring = ring[:pick + 1] + turned + [hole[from_here], ring[pick]] + ring[pick + 1:]
    return ring


def triangulate(loops):
    """Triangles filling the biggest loop, less the others, with no points but the loops' own and running counter-clockwise.
    Returns (points (n, 2), triangles (m, 3)), or nothing to show if the loops are empty."""
    clean = [c for c in map(_clean_loop, loops) if c is not None]
    if not clean:
        return np.zeros((0, 2)), np.zeros((0, 3), np.int64)
    clean.sort(key=lambda c: -abs(signed_area(c)))
    points = np.vstack(clean)
    rings, at = [], 0
    for k, c in enumerate(clean):
        ring = list(range(at, at + len(c)))
        at += len(c)
        area = signed_area(c)
        if (k == 0) != (area > 0):  # the outer one counter-clockwise, holes the other way
            ring.reverse()
        rings.append(ring)
    ring = _bridge(points, rings[0], [np.array(r) for r in rings[1:]]) if len(rings) > 1 else rings[0]
    triangles = np.array(_ear_clip(points, ring), np.int64).reshape(-1, 3)
    return points, _delaunay(points, triangles)


def _in_circle(a, b, c, d):
    """Is d inside the circle through a, b, c, which run counter-clockwise?"""
    ax, ay = a[0] - d[0], a[1] - d[1]
    bx, by = b[0] - d[0], b[1] - d[1]
    cx, cy = c[0] - d[0], c[1] - d[1]
    return ((ax * ax + ay * ay) * (bx * cy - cx * by) - (bx * bx + by * by) * (ax * cy - cx * ay)
            + (cx * cx + cy * cy) * (ax * by - bx * ay)) > 1e-14 * (ax * ax + ay * ay + bx * bx + by * by + cx * cx + cy * cy) ** 2


def _delaunay(points, triangles):
    """Edges flipped until no triangle's circle holds its neighbour's far corner, which does away with the long thin triangles
    ear clipping leaves. Edges with one triangle (the loops) never move, and the area covered doesn't change."""
    tris = [list(t) for t in triangles.tolist()]
    edges = {}
    for i, t in enumerate(tris):
        for k in range(3):
            edges[(t[k], t[(k + 1) % 3])] = i
    stack = [key for key in edges if key[0] < key[1] and (key[1], key[0]) in edges]
    budget = 40 * len(tris) + 100
    while stack and budget:
        budget -= 1
        a, b = stack.pop()
        i, j = edges.get((a, b)), edges.get((b, a))
        if i is None or j is None:
            continue
        t, u = tris[i], tris[j]
        c = t[(t.index(a) + 2) % 3]  # the triangle a, b, c
        d = u[(u.index(b) + 2) % 3]  # the triangle b, a, d
        if c == d:
            continue
        pa, pb, pc, pd = points[a], points[b], points[c], points[d]
        if not _in_circle(pa, pb, pc, pd):
            continue
        # only a corner-free quadrilateral can flip
        if not (_cross2(pa, pd, pc) > 0 and _cross2(pb, pc, pd) > 0):
            continue
        if (c, d) in edges or (d, c) in edges:
            continue
        del edges[(a, b)], edges[(b, a)]
        tris[i], tris[j] = [a, d, c], [b, c, d]
        for x, y, owner in ((a, d, i), (d, c, i), (c, a, i), (b, c, j), (c, d, j), (d, b, j)):
            edges[(x, y)] = owner
        for x, y in ((a, d), (d, b), (b, c), (c, a)):
            if (y, x) in edges:
                stack.append((min(x, y), max(x, y)))
    return np.array(tris, np.int64).reshape(-1, 3)


def refine(uv, xyz, triangles, surface, tolerance, limit=20000):
    """Split the edges inside a mesh that stray from the surface by more than twice the tolerance (the surface's normals smooth
    what's left). Edges on the boundary stay as they are, so that the face next door still meets this one. Returns (uv, xyz,
    triangles)."""
    triangles = np.asarray(triangles, np.int64)
    if not len(triangles):
        return uv, xyz, triangles
    size = len(uv) + 1
    # an edge used by one triangle is on the boundary. Copies of a point (either side of a seam) are told apart by index
    keys = np.vstack([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
    keys = np.sort(keys, axis=1)
    _unique, counts = np.unique(keys[:, 0] * size + keys[:, 1], return_counts=True)
    boundary = set(_unique[counts == 1].tolist())
    fixed = len(uv)
    for _round in range(10):
        if len(triangles) * 2 > limit:
            break
        size = max(size, len(uv) + 1)
        e = np.vstack([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
        low, high = e.min(axis=1), e.max(axis=1)
        wide = low.astype(np.int64) * (1 << 31) + high
        key, where = np.unique(wide, return_inverse=True)
        pairs = np.column_stack([key // (1 << 31), key % (1 << 31)])
        inner = np.array([not (a < fixed and b < fixed and a * (fixed + 1) + b in boundary) for a, b in pairs.tolist()], bool)
        mid_uv = (uv[pairs[:, 0]] + uv[pairs[:, 1]]) / 2
        mid = np.zeros((len(pairs), 3))
        mid[inner] = surface(mid_uv[inner, 0], mid_uv[inner, 1])
        stray = np.linalg.norm(mid - (xyz[pairs[:, 0]] + xyz[pairs[:, 1]]) / 2, axis=1)
        split = inner & (stray > tolerance * 2)
        if not split.any():
            break
        new_index = np.full(len(pairs), -1, np.int64)
        new_index[split] = len(uv) + np.arange(int(split.sum()))
        uv = np.vstack([uv, mid_uv[split]])
        xyz = np.vstack([xyz, mid[split]])
        count = len(triangles)
        marks = new_index[where.ravel()].reshape(3, count).T  # new point on each side: 0-1, 1-2, 2-0
        triangles = _subdivide(triangles, marks)
    return uv, xyz, triangles


def _subdivide(t, m):
    """Each triangle cut along the sides marked with a new point."""
    has = m >= 0
    out = [t[~has.any(axis=1)]]
    three = has.all(axis=1)
    if three.any():
        a, b, c, x, y, z = t[three, 0], t[three, 1], t[three, 2], m[three, 0], m[three, 1], m[three, 2]
        out += [np.column_stack(r) for r in ((a, x, z), (x, b, y), (z, y, c), (x, y, z))]
    for k in range(3):  # one or two sides: turned so the first marked side comes first
        p, q, r = k, (k + 1) % 3, (k + 2) % 3
        one = has[:, p] & ~has[:, q] & ~has[:, r]
        if one.any():
            a, b, c, x = t[one, p], t[one, q], t[one, r], m[one, p]
            out += [np.column_stack((a, x, c)), np.column_stack((x, b, c))]
        two = has[:, p] & has[:, q] & ~has[:, r]
        if two.any():
            a, b, c, x, y = t[two, p], t[two, q], t[two, r], m[two, p], m[two, q]
            out += [np.column_stack((a, x, c)), np.column_stack((x, b, y)), np.column_stack((x, y, c))]
    return np.vstack(out)


def mesh_surface_uv(surface, loops, tolerance, flat=False):
    """A surface meshed inside its trim loops. `surface(u, v)` gives points (n, 3), loops are arrays of (u, v). The result faces
    the way the parameters run, u cross v. Returns (uv (n, 2), points (n, 3), triangles (m, 3)), empty if nothing can be made."""
    loops = [np.asarray(c, float) for c in loops if len(c) >= 3]
    if not loops:
        return np.zeros((0, 2)), np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    every = np.vstack(loops)
    low, high = every.min(axis=0), every.max(axis=0)
    if high[0] <= low[0] or high[1] <= low[1]:
        return np.zeros((0, 2)), np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    # triangles are chosen as they'd look on the surface, a step in u and in v coming out about the same length
    stretch = np.array([1.0, 1.0])
    if not flat:
        _cu, _cv, size_u, size_v = resolution(surface, (low[0], high[0], low[1], high[1]), tolerance)
        biggest = max(size_u, size_v, 1e-300)
        stretch = np.array([max(size_u, biggest * 1e-3) / (high[0] - low[0]), max(size_v, biggest * 1e-3) / (high[1] - low[1])])
    else:
        stretch = stretch / max(high[0] - low[0], high[1] - low[1])
    flat_points, triangles = triangulate([(c - low) * stretch for c in loops])
    if not len(triangles):
        return np.zeros((0, 2)), np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    uv = flat_points / stretch + low
    xyz = surface(uv[:, 0], uv[:, 1])
    if not flat:
        uv, xyz, triangles = refine(uv, xyz, triangles, surface, tolerance)
    return uv, xyz, triangles


def mesh_surface(surface, loops, tolerance, flat=False):
    """As mesh_surface_uv, without the parameters."""
    _uv, xyz, triangles = mesh_surface_uv(surface, loops, tolerance, flat)
    return xyz, triangles
