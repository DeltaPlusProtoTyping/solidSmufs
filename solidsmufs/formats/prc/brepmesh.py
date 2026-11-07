"""Triangles for PRC's exact bodies. Edges are sampled once each, so the faces either side of one meet point for point. A face
on a known surface is trimmed in that surface's parameters: its edges are carried back to (u, v), the angles untwisted, and a
closed surface cut along a seam. A face with no known surface, and any that can't be trimmed, is built from its edges alone
and counted as drawn approximately.
"""

import math

import numpy as np

from .. import surfaces as sf
from . import brep as br

MAX_ANGLE = math.radians(15.0)  # the most a curve may turn in one straight step
PROBES = 32
MAX_STEPS = 256
GRID_SEARCH = 41


# ---------------------------------------------------------------------------------------------- curves to points
def _steps_for(points, tolerance):
    """How many straight steps a curve needs, from a run of points evenly along it."""
    d = np.diff(points, axis=0)
    lengths = np.linalg.norm(d, axis=1)
    if lengths.sum() == 0:
        return 1
    sag = np.linalg.norm(points[1:-1] - (points[:-2] + points[2:]) / 2, axis=1).max() if len(points) > 2 else 0.0
    use = (lengths[:-1] > 0) & (lengths[1:] > 0)
    if use.any():
        cos = (d[:-1][use] * d[1:][use]).sum(axis=1) / (lengths[:-1][use] * lengths[1:][use])
        turning = float(np.arccos(np.clip(cos, -1.0, 1.0)).sum())
    else:
        turning = 0.0
    if turning < 1e-6:
        return 1
    # a chord's error goes with the square of its length; the sag seen is over two probe steps
    by_sag = (len(points) - 1) * math.sqrt(sag / tolerance) / 2 if sag > 0 else 1
    return int(min(MAX_STEPS, max(1, math.ceil(max(by_sag, turning / MAX_ANGLE)))))


def sample_curve(curve, t0, t1, tolerance):
    if getattr(curve, "straight", False):
        return curve.at(np.array([t0, t1], float))
    n = _steps_for(curve.at(np.linspace(t0, t1, PROBES + 1)), tolerance)
    return curve.at(np.linspace(t0, t1, n + 1))


def _edge_points(edge, tolerance):
    """An edge's points from its start to its end, sampled the once."""
    if edge.polyline is not None:
        return edge.polyline
    curve, start, end = edge.curve, edge.start, edge.end
    if not isinstance(start, np.ndarray):
        start = None
    if not isinstance(end, np.ndarray):
        end = None
    if curve is None:
        points = np.array([start, end]) if start is not None and end is not None else np.zeros((0, 3))
    elif isinstance(curve, br.ThroughPoints):
        points = _between(curve.points, start, end)
    else:
        t0, t1 = edge.interval or (curve.t0, curve.t1)
        points = sample_curve(curve, t0, t1, tolerance)
        if start is not None and end is not None and len(points) > 1:
            if np.linalg.norm(points[0] - start) + np.linalg.norm(points[-1] - end) > np.linalg.norm(points[-1] - start) + np.linalg.norm(points[0] - end):
                points = points[::-1].copy()
    if len(points) >= 2 and start is not None and end is not None:  # vertices are what the neighbours share
        points = points.copy()
        points[0], points[-1] = start, end
    edge.polyline = points
    return points


def _between(points, start, end):
    """A stored run of points on a curve, from the one nearest `start` to the one nearest `end`, ending on those."""
    if start is None or end is None:
        return points
    i = int(np.linalg.norm(points - start, axis=1).argmin())
    j = int(np.linalg.norm(points - end, axis=1).argmin())
    middle = points[i:j + 1] if i <= j else points[j:i + 1][::-1]
    return np.vstack([start, middle[1:-1], end]) if len(middle) > 2 else np.array([start, end])


def _join(parts):
    """Runs of points into one closed loop, each turned whichever way meets the last. None if there's nothing to it."""
    parts = [p for p in parts if len(p) >= 2]
    if not parts:
        return None
    if len(parts) > 1:  # the first run's way round follows from the second's
        a, b = parts[0], parts[1]
        here = min(np.abs(a[-1] - b[0]).max(), np.abs(a[-1] - b[-1]).max())
        there = min(np.abs(a[0] - b[0]).max(), np.abs(a[0] - b[-1]).max())
        if there < here:
            parts[0] = a[::-1]
    out = [parts[0]]
    for p in parts[1:]:
        end = out[-1][-1]
        out.append(p[1:] if np.abs(end - p[0]).max() <= np.abs(end - p[-1]).max() else p[::-1][1:])
    points = np.vstack(out)
    size = float(np.ptp(points, axis=0).max())
    if len(points) > 3 and np.abs(points[0] - points[-1]).max() <= size * 1e-6:
        points = points[:-1]
    return points


def _sided_polyline(curve, tolerance, cache):
    key = id(curve)
    points = cache.get(key)
    if points is None:
        points = cache[key] = sample_curve(curve, curve.t0, curve.t1, tolerance)
    return points


# ---------------------------------------------------------------------------------------------- back to (u, v)
def _search(surface, points, box, state):
    """Parameters of points on a surface with no formula back: the nearest of a grid, then Newton's steps."""
    u0, v0, u1, v1 = box
    key = (id(surface), box)
    grid = state.get(key)
    across_u, across_v = GRID_SEARCH, GRID_SEARCH
    if isinstance(surface, br.NurbsSurface):  # a finely detailed surface, like a thread, needs looking at as finely
        across_u = min(257, max(GRID_SEARCH, 4 * (len(np.unique(surface.knots_u)) - 1) + 1))
        across_v = min(257, max(GRID_SEARCH, 4 * (len(np.unique(surface.knots_v)) - 1) + 1))
    if grid is None:
        us, vs = np.meshgrid(np.linspace(u0, u1, across_u), np.linspace(v0, v1, across_v), indexing="ij")
        grid = state[key] = (us.ravel(), vs.ravel(), surface.at(us.ravel(), vs.ravel()))
    us, vs, xyz = grid
    near = np.array([np.einsum("ij,ij->i", xyz - p, xyz - p).argmin() for p in points])
    u, v = us[near].copy(), vs[near].copy()
    # a small trim on a huge sheet falls between the grid's points: look again, closer, around where they landed
    step_u, step_v = (u1 - u0) / (across_u - 1), (v1 - v0) / (across_v - 1)
    a0, a1 = max(u.min() - step_u, u0), min(u.max() + step_u, u1)
    b0, b1 = max(v.min() - step_v, v0), min(v.max() + step_v, v1)
    if a1 - a0 < (u1 - u0) * 0.5 or b1 - b0 < (v1 - v0) * 0.5:
        fine_u, fine_v = np.meshgrid(np.linspace(a0, a1, GRID_SEARCH), np.linspace(b0, b1, GRID_SEARCH), indexing="ij")
        fine_u, fine_v = fine_u.ravel(), fine_v.ravel()
        fine = surface.at(fine_u, fine_v)
        near = np.array([np.einsum("ij,ij->i", fine - p, fine - p).argmin() for p in points])
        u, v = fine_u[near], fine_v[near]
        step_u, step_v = (a1 - a0) / (GRID_SEARCH - 1), (b1 - b0) / (GRID_SEARCH - 1)
    hu, hv = min(step_u, (u1 - u0) * 1e-3) * 1e-2 or 1e-5, min(step_v, (v1 - v0) * 1e-3) * 1e-2 or 1e-5
    for _ in range(8):
        p = surface.at(u, v)
        su = (surface.at(np.minimum(u + hu, u1), v) - surface.at(np.maximum(u - hu, u0), v)) / (np.minimum(u + hu, u1) - np.maximum(u - hu, u0))[:, None]
        sv = (surface.at(u, np.minimum(v + hv, v1)) - surface.at(u, np.maximum(v - hv, v0))) / (np.minimum(v + hv, v1) - np.maximum(v - hv, v0))[:, None]
        r = points - p
        a, b, c = (su * su).sum(axis=1), (su * sv).sum(axis=1), (sv * sv).sum(axis=1)
        f, g = (su * r).sum(axis=1), (sv * r).sum(axis=1)
        det = a * c - b * b
        ok = np.abs(det) > 1e-30
        du, dv = np.zeros(len(u)), np.zeros(len(v))
        du[ok] = (c[ok] * f[ok] - b[ok] * g[ok]) / det[ok]
        dv[ok] = (a[ok] * g[ok] - b[ok] * f[ok]) / det[ok]
        u, v = np.clip(u + du, u0, u1), np.clip(v + dv, v0, v1)
    return u, v, np.zeros(len(u), bool)


def _parameters(surface, points, box, state):
    found = surface.invert(points)
    if found is None:
        if box is None:
            raise ValueError("a surface with no bounds can't be searched")
        found = _search(surface, points, box, state)
    return found


def _settle_poles(u, v, pole):
    """At a pole u means nothing: it takes the u of the way in, then the way out."""
    if not pole.any():
        return u, v
    n, nu, nv = len(u), [], []
    for i in range(n):
        if not pole[i]:
            nu.append(u[i])
            nv.append(v[i])
            continue
        before, after = (i - 1) % n, (i + 1) % n
        if not pole[before]:
            nu.append(u[before])
            nv.append(v[i])
        if not pole[after]:
            nu.append(u[after])
            nv.append(v[i])
    return np.array(nu), np.array(nv)


def _unwrap(values, period):
    """Untwisted along the loop. Returns (values, whole turns made getting back to the start)."""
    if not period:
        return values, 0
    closed = np.unwrap(np.append(values, values[0]), period=period)
    return closed[:-1], int(round((closed[-1] - closed[0]) / period))


def _pole_values(surface, axis_stored):
    """Where a closed surface's other parameter ends in a point: a cone's apex, a sphere's poles. Stored values, along the
    parameter that isn't wrapping (0: u, 1: v)."""
    if isinstance(surface, br.Cone) and surface.slope:
        canonical = [-surface.radius / surface.slope]
    elif isinstance(surface, br.Sphere):
        canonical = [-math.pi / 2, math.pi / 2]
    else:
        return []
    if axis_stored == 1:
        return [(c - surface.vb) / surface.va for c in canonical]
    return [(c - surface.ub) / surface.ua for c in canonical]


def _seam_cut(loop, seam, period):
    """A loop that goes once round with its first column rising, cut at `seam`: its run from seam to seam + period."""
    # enough copies of it, end to end, to cover the seam and one whole turn past it
    first = math.floor((seam - float(loop[:, 0].max())) / period) - 1
    last = math.ceil((seam + period - float(loop[:, 0].min())) / period) + 1
    rows = np.vstack([np.column_stack([loop[:, 0] + k * period, loop[:, 1]]) for k in range(first, last + 1)])
    u = rows[:, 0]
    start = int(np.argmax(u >= seam))
    if u[start] < seam or start == 0:
        raise ValueError("a loop doesn't reach its seam")
    tail = u[start:]
    stop = int(np.argmax(tail >= seam + period)) + start
    if u[stop] < seam + period:
        raise ValueError("a loop doesn't get round")

    def at(i, value):
        a, b = rows[i - 1], rows[i]
        f = (value - a[0]) / (b[0] - a[0]) if b[0] != a[0] else 0.0
        return np.array([value, a[1] + (b[1] - a[1]) * f])

    return np.vstack([at(start, seam), rows[start:stop], at(stop, seam + period)])


def _strip_loops(wrapping, plain, period, closes, seam_steps):
    """Loops on a closed surface as ordinary polygons, the first parameter being the closed one: `wrapping` go round, as
    (points, whole turns), `plain` don't. Two wrapping loops bound a band, one and an end (a pole, an edge of the domain) likewise."""
    # a seam clear of everything that doesn't go round, or anywhere if nothing's in the way
    rising = [w if turns > 0 else w[::-1] for w, turns in wrapping]
    seam = float(rising[0][0, 0])
    if plain:
        spans = sorted((float(p[:, 0].min()) % period, float(np.ptp(p[:, 0]))) for p in plain)
        best, seam = -1.0, seam
        for k, (start, width) in enumerate(spans):
            end = start + width
            following = spans[(k + 1) % len(spans)][0] + (period if k == len(spans) - 1 else 0.0)
            if following - end > best:
                best, seam = following - end, end + (following - end) / 2
    cuts = [_seam_cut(w, seam, period) for w in rising]
    cuts.sort(key=lambda c: float(c[:, 1].mean()))
    def along(u, v0, v1):  # the seam's inside points, the same on both its copies so that they weld: it's an edge like any other
        inner = np.linspace(v0, v1, seam_steps + 1)[1:-1]
        return np.column_stack([np.full(len(inner), u), inner])

    if len(cuts) >= 2:
        low, high = cuts[0], cuts[-1]
        outer = np.vstack([low, along(seam + period, low[-1, 1], high[-1, 1]), high[::-1], along(seam, high[0, 1], low[0, 1])])
    else:
        c = cuts[0]
        end = closes(c)
        outer = np.vstack([c, along(seam + period, c[-1, 1], end), [[seam + period, end], [seam, end]], along(seam, end, c[0, 1])])
    holes = [np.column_stack([p[:, 0] - period * math.floor((float(p[:, 0].mean()) - seam) / period), p[:, 1]]) for p in plain]
    return [outer] + holes


def _uv_loops(surface, loops3d, box, tolerance, state, ways=None):
    """Each 3D loop in the surface's parameters as polygons to mesh. An edge that isn't on the surface means the surface isn't
    to be trusted for this face: better built from its edges."""
    period = surface.period
    made = []
    for points in loops3d:
        u, v, pole = _parameters(surface, points, box, state)
        if not surface.planar and float(np.linalg.norm(surface.at(u, v) - points, axis=1).max()) > tolerance * 25:
            raise ValueError("its edges aren't on its surface")
        u, v = _settle_poles(u, v, pole)
        u, turns_u = _unwrap(u, period[0])
        v, turns_v = _unwrap(v, period[1])
        made.append((np.column_stack([u, v]), turns_u, turns_v, ways[len(made)] if ways and len(made) < len(ways) else None))
    round_u = [m for m in made if m[1]]
    round_v = [m for m in made if m[2]]
    if not round_u and not round_v:
        return _into_window([m[0] for m in made], period)
    if round_u and round_v:  # both ways round on a torus: the two kinds cross, so go with the one that has a pair
        round_v = [] if len(round_u) >= len(round_v) else round_v
        round_u = [] if round_v else round_u
    axis = 0 if round_u else 1
    chosen = round_u or round_v
    swap = (lambda c: c) if axis == 0 else (lambda c: c[:, ::-1])
    wrapping = [(swap(m[0]), m[1] if axis == 0 else m[2]) for m in chosen]
    plain = [swap(m[0]) for m in made if not (m[1] if axis == 0 else m[2])]

    def closes(cut):
        mean = float(cut[:, 1].mean())
        poles = _pole_values(surface, 1 - axis)
        if not poles and box is not None:
            poles = [box[1 - axis], box[3 - axis]]
        if not poles:
            raise ValueError("a single loop on a closed surface with no end to close against")
        way = chosen[0][3]
        if way in (0, 1) and len(poles) == 2:  # a face lies to the left of a loop running its surface's way: that picks the end
            turns = chosen[0][1] if axis == 0 else chosen[0][2]
            up = (turns > 0) == (way == 1)
            if surface.flip:
                up = not up
            if axis == 1:
                up = not up
            return max(poles) if up else min(poles)
        if isinstance(surface, br.Sphere) and len(poles) == 2 and abs(mean - sum(poles) / 2) < 0.05 * abs(poles[1] - poles[0]):
            return _hemisphere(surface, poles, axis, state)
        return min(poles, key=lambda p: abs(p - mean))

    # along a cylinder or cone the seam is straight; on anything else a chord would crease the surface
    seam_steps = 1 if isinstance(surface, (br.Cylinder, br.Cone)) else 16
    return [swap(p) for p in _strip_loops(wrapping, plain, period[axis], closes, seam_steps)]


def _hemisphere(surface, poles, axis, state):
    """Which pole a sphere's face closes to, when all it stores is a great circle (a compressed face has no edge directions to
    tell by). A dome bulges away from the body; a second face on the same sphere takes the other side."""
    key = ("sphere", *np.round(surface.matrix[:3, 3] / (abs(surface.radius) or 1.0), 6).tolist(), round(surface.radius, 9))
    taken = state.get(key)
    if taken is not None:
        return poles[1] if taken == poles[0] else poles[0]
    middle = state.get("middle")

    def far(p):
        u, v = (np.array([0.0]), np.array([p])) if axis == 0 else (np.array([p]), np.array([0.0]))
        return float(np.linalg.norm(surface.at(u, v)[0] - middle)) if middle is not None else 0.0

    pick = max(poles, key=far)
    state[key] = pick
    return pick


def _into_window(loops, period):
    """Loops that don't go round, each shifted by whole turns to sit with the biggest."""
    if len(loops) < 2 or not (period[0] or period[1]):
        return loops
    big = max(loops, key=lambda c: abs(sf.signed_area(c)))
    middle = (big.min(axis=0) + big.max(axis=0)) / 2
    out = []
    for c in loops:
        c = c.copy()
        for k in (0, 1):
            if period[k]:
                c[:, k] += period[k] * round((middle[k] - float(c[:, k].mean())) / period[k])
        out.append(c)
    return out


# ---------------------------------------------------------------------------------------------- whole grids
def _grid_triangles(nu, nv):
    a = (np.arange(nu)[:, None] * (nv + 1) + np.arange(nv)).ravel()
    b = a + nv + 1
    return np.vstack([np.column_stack([a, b, b + 1]), np.column_stack([a, b + 1, a + 1])])


def surface_normals(surface, uv, box=None):
    """u cross v at each point, by differences that stay on the surface. Zero where it has none, as at a pole."""
    u, v = uv[:, 0], uv[:, 1]
    box = box or surface.domain
    lo, hi = uv.min(axis=0), uv.max(axis=0)
    if box is not None and _finite(box):  # a closed surface may run past its box: the differences needn't stop at it then
        lo = np.array([min(lo[0], box[0]), min(lo[1], box[1])])
        hi = np.array([max(hi[0], box[2]), max(hi[1], box[3])])
    hu, hv = max(hi[0] - lo[0], 1e-12) * 1e-5, max(hi[1] - lo[1], 1e-12) * 1e-5
    u_up, u_down = np.minimum(u + hu, hi[0]), np.maximum(u - hu, lo[0])
    v_up, v_down = np.minimum(v + hv, hi[1]), np.maximum(v - hv, lo[1])
    n = np.cross((surface.at(u_up, v) - surface.at(u_down, v)), (surface.at(u, v_up) - surface.at(u, v_down)))
    length = np.linalg.norm(n, axis=1, keepdims=True)
    length[length == 0] = 1.0
    return n / length


def mesh_whole(surface, tolerance, box=None):
    """A surface over all of its parameter box, on a grid. (points, triangles, normals)."""
    u0, v0, u1, v1 = box or surface.domain
    cells_u, cells_v, _, _ = sf.resolution(surface.at, (u0, u1, v0, v1), tolerance)
    if isinstance(surface, br.NurbsSurface):  # enough for each span of its knots at least to be seen
        cells_u = max(cells_u, min(32, len(np.unique(surface.knots_u)) - 1))
        cells_v = max(cells_v, min(32, len(np.unique(surface.knots_v)) - 1))
    us, vs = np.meshgrid(np.linspace(u0, u1, cells_u + 1), np.linspace(v0, v1, cells_v + 1), indexing="ij")
    uv = np.column_stack([us.ravel(), vs.ravel()])
    return surface.at(uv[:, 0], uv[:, 1]), _grid_triangles(cells_u, cells_v), surface_normals(surface, uv, (u0, v0, u1, v1))


class _Side:
    """A run of points, as a curve running 0 to 1 by its length."""

    def __init__(self, points):
        self.points = points
        d = np.linalg.norm(np.diff(points, axis=0), axis=1)
        total = d.sum()
        self.along = np.concatenate([[0.0], np.cumsum(d) / total]) if total > 0 else np.linspace(0, 1, len(points))

    def at(self, t):
        return np.column_stack([np.interp(t, self.along, self.points[:, k]) for k in range(3)])


def mesh_patch(sides, flat_cells=None):
    """The surface four sides span, each running on from the last (a Coons patch: exact for a plane and a cylinder, and close
    on anything curved both ways when the patch is small). Sides are runs of points."""
    s0, s1, s2, s3 = (_Side(p) for p in sides)
    nu = max(len(sides[0]), len(sides[2])) - 1
    nv = max(len(sides[1]), len(sides[3])) - 1
    u, v = np.linspace(0.0, 1.0, nu + 1), np.linspace(0.0, 1.0, nv + 1)
    bottom, top = s0.at(u), s2.at(1.0 - u)
    right, left = s1.at(v), s3.at(1.0 - v)
    p00, p10, p01, p11 = bottom[0], bottom[-1], top[0], top[-1]
    uu, vv = u[:, None, None], v[None, :, None]
    points = ((1 - vv) * bottom[:, None, :] + vv * top[:, None, :] + (1 - uu) * left[None, :, :] + uu * right[None, :, :]
              - ((1 - uu) * (1 - vv) * p00 + uu * (1 - vv) * p10 + (1 - uu) * vv * p01 + uu * vv * p11))
    return points.reshape(-1, 3), _grid_triangles(nu, nv)


def _split_sides(loop_parts):
    """Four sides from a loop's runs of points, if it has three or four; otherwise None."""
    joined = []
    for p in loop_parts:
        if len(p) < 2:
            continue
        if joined:
            end = joined[-1][-1]
            joined.append(p if np.abs(end - p[0]).max() <= np.abs(end - p[-1]).max() else p[::-1])
        else:
            joined.append(p)
    if len(joined) == 3:
        joined.append(np.array([joined[0][0], joined[0][0]]))
    if len(joined) != 4:
        return None
    return joined


def mesh_from_edges(loops3d, parts):
    """A face with no surface to go by, from its edges alone: a patch when one loop has four sides, or the loops laid flat on
    the plane that fits them best, otherwise."""
    if len(parts) == 1:
        sides = _split_sides(parts[0])
        if sides is not None:
            return mesh_patch(sides)
    every = np.vstack(loops3d)
    center = every.mean(axis=0)
    _, _, axes = np.linalg.svd(every - center, full_matrices=False)
    flat = [(p - center) @ axes[:2].T for p in loops3d]
    points, triangles = sf.triangulate(flat)
    if _covers(flat, points, triangles):
        return center + points @ axes[:2], triangles
    if len(loops3d) == 1:  # it folds too much to lay flat: a fan from its middle still closes the gap
        ring = loops3d[0]
        n = len(ring)
        return np.vstack([ring, ring.mean(axis=0)]), np.column_stack([np.full(n, n), np.arange(n), (np.arange(n) + 1) % n])
    raise ValueError("its edges don't lie flat enough to fill")


# ---------------------------------------------------------------------------------------------- one face
def _covers(polygons, points, triangles):
    """Do the triangles fill what the polygons enclose? Meshing that went wrong shows as the wrong area."""
    if not len(triangles):
        return False
    areas = sorted((abs(sf.signed_area(p)) for p in polygons), reverse=True)
    want = areas[0] - sum(areas[1:])
    a, b = points[triangles[:, 1]] - points[triangles[:, 0]], points[triangles[:, 2]] - points[triangles[:, 0]]
    got = 0.5 * float(np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]).sum())
    return want > 0 and abs(got - want) <= 0.03 * want


def _mesh_on_surface(surface, loops3d, tolerance, box, state, ways=None):
    polygons = _uv_loops(surface, loops3d, box, tolerance, state, ways)
    uv, points, triangles = sf.mesh_surface_uv(surface.at, polygons, tolerance, flat=surface.planar)
    fixed = len(np.vstack(polygons))
    if not _covers(polygons, uv[:fixed], triangles[(triangles < fixed).all(axis=1)]) and not _covers(polygons, uv, triangles):
        raise ValueError("its trim loops don't fill")
    return points, triangles, surface_normals(surface, uv, box)


_NOTHING = (np.zeros((0, 3)), np.zeros((0, 3), np.int64), None)


class Counts:
    def __init__(self):
        self.approximate = self.skipped = 0


def _finite(box):
    return box is not None and all(math.isfinite(x) and abs(x) < 12000.0 for x in box) and box[2] > box[0] and box[3] > box[1]


def _face_box(face, surface):
    for box in (face.domain, surface.domain):
        if _finite(box):
            return box
    return None


def _plain_face(face, tolerance, state, counts):
    """(points, triangles, normals or None, is it planar)."""
    surface = face.surface
    if surface is None:
        surface = br.Unevaluated()
    box = _face_box(face, surface)
    parts, ways = [], []
    for loop in face.loops:
        if isinstance(loop, br.Loop):
            runs = []
            for coedge in loop.coedges:
                if isinstance(coedge, br.CoEdge) and isinstance(coedge.edge, br.Edge):
                    p = _edge_points(coedge.edge, tolerance)
                    runs.append(p if coedge.forward else p[::-1])
            parts.append(runs)
            ways.append(loop.direction)
    joined = [_join(r) for r in parts]
    ways = [w for w, x in zip(ways, joined) if x is not None and len(x) >= 3]
    loops3d = [x for x in joined if x is not None and len(x) >= 3]
    planar = isinstance(surface, br.Plane)
    return (*_surface_or_edges(surface, loops3d, parts, box, tolerance, state, counts, ways), planar)


def _stays_near(points, loops3d):
    """A face reaches little beyond its edges: a dome by its radius at most. Far past them, something went wrong on the way."""
    every = np.vstack(loops3d)
    low, high = every.min(axis=0), every.max(axis=0)
    reach = float(np.linalg.norm(high - low))
    return bool(np.all(points >= low - reach) and np.all(points <= high + reach))


def _surface_or_edges(surface, loops3d, parts, box, tolerance, state, counts, ways=None):
    if not loops3d:  # nothing to trim it by: the whole of what it has
        if not isinstance(surface, br.Unevaluated) and _finite(box):
            return mesh_whole(surface, tolerance, box)
        counts.skipped += 1
        return _NOTHING
    if not isinstance(surface, br.Unevaluated):
        try:
            done = _mesh_on_surface(surface, loops3d, tolerance, box, state, ways)
            if len(done[1]) and _stays_near(done[0], loops3d):
                return done
        except (ValueError, IndexError, ZeroDivisionError, np.linalg.LinAlgError):  # an awkward face mustn't stop the rest
            pass
    try:
        points, triangles = mesh_from_edges(loops3d, parts)
    except (ValueError, IndexError, ZeroDivisionError, np.linalg.LinAlgError):
        counts.skipped += 1
        return _NOTHING
    counts.approximate += 1
    return points, triangles, None


def _compressed_face(face, tolerance, state, counts, cache):
    if isinstance(face, br.WholeFace):
        surface = face.surface
        if isinstance(surface, br.Unevaluated):
            counts.skipped += 1
            return _NOTHING + (False,)
        return mesh_whole(surface, tolerance) + (False,)
    if isinstance(face, br.PatchFace):
        sides = [_sided_polyline(c, tolerance, cache) for c in face.sides]
        if face.kind == br.ISO_TORUS:  # a Coons patch strays on a torus swept far: its arcs say what the torus really is
            surface = torus_of(face.sides)
            if surface is not None:
                for k, side in enumerate(face.sides):  # what's deduced comes from the surface, not from a copy that may bulge wrongly
                    if isinstance(side, br.Deduced) and isinstance(side.source, br.Similar):
                        side.become(br.IsoShift(surface, side.source.curve, side.source.start, side.source.end))
                        cache.pop(id(side), None)
                        sides[k] = _sided_polyline(side, tolerance, cache)
                loop = _join(list(sides))
                if loop is not None and len(loop) >= 3:
                    try:
                        done = _mesh_on_surface(surface, [loop], tolerance, None, state)
                        if len(done[1]) and _stays_near(done[0], [loop]):
                            return (*done, False)
                    except (ValueError, IndexError, ZeroDivisionError, np.linalg.LinAlgError):
                        pass
        p0, _p1, _p2 = br._common_end(face.sides[0], face.sides[1])
        ordered, at = [], p0
        for curve, run in zip(face.sides, sides):
            if np.abs(run[0] - at).max() > np.abs(run[-1] - at).max():
                run = run[::-1]
            ordered.append(run)
            at = run[-1]
        points, triangles = mesh_patch(ordered)
        return points, triangles, None, face.kind == br.ISO_PLANE
    if not face.loops:
        counts.skipped += 1  # a whole surface whose size was never stored
        return _NOTHING + (False,)
    parts = [[_sided_polyline(c, tolerance, cache) for c in loop] for loop in face.loops]
    loops3d = [x for x in (_join(list(r)) for r in parts) if x is not None and len(x) >= 3]
    if not loops3d:
        counts.skipped += 1
        return _NOTHING + (False,)
    surface = face.make(np.vstack(loops3d))
    box = _face_box_of(surface)
    return (*_surface_or_edges(surface, loops3d, parts, box, tolerance, state, counts), isinstance(surface, br.Plane))


def _arc_data(curve):
    """(centre, unit axis, radius) of a curve that's a circular arc, however it was come by, or None."""
    if isinstance(curve, br.Deduced):
        return _arc_data(curve.source) if curve.source is not None else None
    if isinstance(curve, br.Reversed):
        return _arc_data(curve.curve)
    if isinstance(curve, br.Similar):
        inner = _arc_data(curve.curve)
        if inner is None:
            return None
        center = (inner[0] - curve.origin) @ curve.turn.T * curve.scale + curve.start
        return center, inner[1] @ curve.turn.T, inner[2] * curve.scale
    if isinstance(curve, br.Arc):
        return curve.center, curve.axis, float(np.linalg.norm(curve.start - curve.center))
    return None


def torus_of(sides):
    """The torus four sides lie on, from a pair of arcs at right angles: one round its axis, the other round its tube. None if
    the sides don't say, or don't all fit it."""
    arcs = [a for a in map(_arc_data, sides) if a is not None]
    every = np.vstack([np.array([s.start, s.end]) for s in sides])
    size = float(np.ptp(every, axis=0).max()) or 1.0
    best = None
    for big in arcs:
        for tube in arcs:
            if big is tube or abs(float(big[1] @ tube[1])) > 1e-3:
                continue
            # the tube's circle lies in a plane holding the torus's axis
            if abs(float(tube[1] @ (big[0] - tube[0]))) > 1e-3 * size:
                continue
            axis = big[1]
            center = big[0] + float((tube[0] - big[0]) @ axis) * axis
            out = tube[0] - center
            major = float(np.linalg.norm(out))
            if major <= 0:
                continue
            x = out
            y = np.cross(axis, out / major) * tube[2]
            surface = br._make_torus(center, x, y)
            a, b, _pole = surface.invert(every)
            error = float(np.linalg.norm(surface.at(a, b) - every, axis=1).max())
            if best is None or error < best[0]:
                best = (error, surface)
    return best[1] if best is not None and best[0] <= 2e-3 * size else None


def _corner_normals(points, triangles, normals):
    """Normals at each triangle's corners: the surface's where it has one, the mesh's own otherwise."""
    a, b, c = points[triangles[:, 0]], points[triangles[:, 1]], points[triangles[:, 2]]
    own = np.cross(b - a, c - a)
    if normals is None:
        summed = np.zeros_like(points)
        for k in range(3):
            np.add.at(summed, triangles[:, k], own)
        length = np.linalg.norm(summed, axis=1, keepdims=True)
        length[length == 0] = 1.0
        normals = summed / length
    corners = normals[triangles]
    missing = np.linalg.norm(corners, axis=2) < 0.5
    if missing.any():
        length = np.linalg.norm(own, axis=1, keepdims=True)
        length[length == 0] = 1.0
        flat = own / length
        corners[missing] = np.repeat(flat[:, None, :], 3, axis=1)[missing]
    return corners


def _face_box_of(surface):
    return surface.domain if _finite(surface.domain) else None


# ---------------------------------------------------------------------------------------------- a whole body
def bounds(body):
    """Corners of what a body holds, or None: its vertices, points along its edges (a whole circle has only one vertex, so
    those alone can be far too small), and for faces with no edges, their surfaces."""
    every = [np.atleast_2d(p) for p in body.points]
    along = np.linspace(0.0, 1.0, 9)

    def add(curve, t0=None, t1=None):
        if curve is None:
            return
        try:
            first, last = (curve.t0, curve.t1) if t0 is None else (t0, t1)
            every.append(curve.at(first + (last - first) * along))
        except (ValueError, IndexError, TypeError, AttributeError, ZeroDivisionError):
            pass

    for _closed, faces in body.shells:
        for face, _how in faces:
            if isinstance(face, br.Face):
                if not face.loops and face.surface is not None and not isinstance(face.surface, br.Unevaluated):
                    box = _face_box(face, face.surface)
                    if box is not None:
                        us, vs = np.meshgrid(np.linspace(box[0], box[2], 5), np.linspace(box[1], box[3], 5))
                        every.append(face.surface.at(us.ravel(), vs.ravel()))
                for loop in face.loops:
                    for coedge in loop.coedges if isinstance(loop, br.Loop) else ():
                        edge = coedge.edge if isinstance(coedge, br.CoEdge) else None
                        if isinstance(edge, br.Edge) and not isinstance(edge.curve, br.ThroughPoints):
                            add(edge.curve, *(edge.interval or (None, None)))
            elif isinstance(face, br.AnaFace):
                for loop in face.loops or ():
                    for curve in loop:
                        add(curve)
            elif isinstance(face, br.PatchFace):
                for curve in face.sides:
                    add(curve)
    if not every:
        return None
    every = np.vstack(every)
    return every.min(axis=0), every.max(axis=0)


def mesh_body(body, tolerance, weld):
    """(points, triangles, face per triangle, corner normals, planar flag per face, Counts), in the body's own units."""
    out_points, out_triangles, out_faces, out_normals, planar = [], [], [], [], []
    counts = Counts()
    state, cache = {}, {}
    box = bounds(body)
    reach = 0.0
    if box is not None:
        state["middle"] = (box[0] + box[1]) / 2
        reach = float(np.linalg.norm(box[1] - box[0]))
    total = 0
    for closed, faces in body.shells:
        for face, how in faces:
            try:
                if isinstance(face, br.Face):
                    points, triangles, normals, flat = _plain_face(face, tolerance, state, counts)
                    turned = (face.surface is not None and face.surface.flip) ^ (how == 0)
                elif isinstance(face, (br.AnaFace, br.PatchFace, br.WholeFace)):
                    points, triangles, normals, flat = _compressed_face(face, tolerance, state, counts, cache)
                    turned = not face.keep
                else:
                    continue
            except (ValueError, IndexError, TypeError, AttributeError, ZeroDivisionError, np.linalg.LinAlgError):
                counts.skipped += 1  # one face that can't be made sense of mustn't cost the rest of the model
                continue
            if not len(triangles):
                continue
            if box is not None and (np.any(points < box[0] - reach) or np.any(points > box[1] + reach)):
                counts.skipped += 1  # far outside everything the body says it holds
                continue
            number = len(planar)
            planar.append(bool(flat))
            corners = _corner_normals(points, triangles, normals)
            if turned:
                triangles = triangles[:, [0, 2, 1]]
                corners = -corners[:, [0, 2, 1]]
            out_points.append(points)
            out_normals.append(corners)
            out_triangles.append(triangles + total)
            out_faces.append(np.full(len(triangles), number, np.int64))
            total += len(points)
    if not out_points:
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64), np.zeros(0, np.int64), None, [], counts
    points, triangles = _welded(np.vstack(out_points), np.vstack(out_triangles), weld)
    faces = np.concatenate(out_faces)
    keep = (triangles[:, 0] != triangles[:, 1]) & (triangles[:, 1] != triangles[:, 2]) & (triangles[:, 0] != triangles[:, 2])
    return points, triangles[keep], faces[keep], np.vstack(out_normals)[keep], planar, counts


def _welded(points, triangles, weld):
    """Points within `weld` of each other as one, so that faces share their edges."""
    keys = np.round(points / weld).astype(np.int64)
    _, first, back = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    return points[first], back.ravel()[triangles]
