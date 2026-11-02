"""Mass properties and bounding boxes.

B-rep documents: OpenCASCADE's exact integrals (volume, centre of mass, inertia about the centre of
mass) per solid, combined with the parallel-axis theorem. Exact bounding boxes come from measuring
the distance between the part and a plane parked just outside it. Mesh documents: the same numbers
from the closed triangle mesh (divergence theorem).

Units in and out: mm, g/cm³ for density, grams, g·mm².
"""

import numpy as np

from .geom import unit


def combine(parts):
    """parts: [(volume mm³, centre (3,), inertia about centre (3, 3) per unit density)] → totals."""
    vol = sum(p[0] for p in parts)
    if vol <= 0:
        return 0.0, np.zeros(3), np.zeros((3, 3))
    com = sum(p[0] * np.asarray(p[1]) for p in parts) / vol
    inertia = np.zeros((3, 3))
    for v, c, i in parts:
        d = np.asarray(c) - com
        inertia += np.asarray(i) + v * (float(d @ d) * np.eye(3) - np.outer(d, d))
    return vol, com, inertia


def report(vol, com, inertia_unit, area, density, solids, exact, notes=()):
    """The numbers the Mass Properties panel shows, densities applied."""
    rho = density * 1e-3  # g/cm³ → g/mm³
    mass = rho * vol
    i_com = inertia_unit * rho
    w, v = np.linalg.eigh(i_com)
    order = np.argsort(w)
    w, v = w[order], v[:, order]
    for k in range(3):  # make each principal axis point mostly along +x / +y / +z for a stable display
        j = int(np.argmax(np.abs(v[:, k])))
        if v[j, k] < 0:
            v[:, k] = -v[:, k]
    i_origin = i_com + mass * (float(com @ com) * np.eye(3) - np.outer(com, com))
    return {
        "density": density, "volume": vol, "mass": mass, "area": area,
        "center": com, "inertia_center": i_com, "inertia_origin": i_origin,
        "principal_moments": w, "principal_axes": v.T,
        "gyration_radii": np.sqrt(np.maximum(w, 0) / mass) if mass > 0 else np.zeros(3),
        "solids": solids, "exact": exact, "notes": list(notes),
    }


# ---------------------------------------------------------------------------------------------- B-rep
def cad_mass(model, bodies, density):
    """Mass properties of the bodies at one density (g/cm³), or with density None at each body's own
    (from its material in the file; 1.0 for bodies without one, as SolidWorks does)."""
    import gmsh

    parts, area, names, notes = [], 0.0, [], []
    rhos = []
    for b in bodies:
        tag = model.body_tag[b]
        f0, fn = model.bodies[b]["faces"]
        area += sum(model.exact_area(f) or 0.0 for f in range(f0, f0 + fn))
        if tag is None:
            notes.append(f"{model.bodies[b]['name']} is surfaces only (no volume)")
            continue
        vol = gmsh.model.occ.getMass(3, tag)
        com = np.asarray(gmsh.model.occ.getCenterOfMass(3, tag), np.float64)
        inertia = np.asarray(gmsh.model.occ.getMatrixOfInertia(3, tag), np.float64).reshape(3, 3)
        if vol < 0:  # an inside-out solid: flip it rather than report negative mass
            vol, inertia = -vol, -inertia
            notes.append(f"{model.bodies[b]['name']} was inside out")
        parts.append((vol, com, inertia))
        names.append(model.bodies[b]["name"])
        rhos.append(float(model.bodies[b].get("density") or 1.0))
    if density is None:
        parts, density = _weighted(parts, rhos)
        if len(set(rhos)) > 1:
            notes.append("Each part weighs with its own material's density; the density shown is the average.")
    vol, com, inertia = combine(parts)
    if not parts:
        notes = ["No solid bodies here, only surfaces (common in IGES files), so there's no volume or mass. "
                 "The surface area is still exact."]
    return report(vol, com, inertia, area, density, names, True, notes)


def _weighted(parts, rhos):
    """(parts scaled to one reference density, that density) for bodies of different densities: each
    body's volume weight and inertia scale by its density over the reference (the mass-weighted mean), so
    combine() gives the true centre of mass and inertia and report() the true total mass."""
    total = sum(v for v, _c, _i in parts)
    if total <= 0:
        return parts, 1.0
    ref = sum(v * r for (v, _c, _i), r in zip(parts, rhos)) / total
    return [(v * r / ref, c, np.asarray(i) * r / ref) for (v, c, i), r in zip(parts, rhos)], ref


def cad_bbox(model, bodies, axes=None):
    """Exact extents along three axes (world XYZ by default): {"min", "max", "size", "axes"}."""
    import gmsh

    axes = np.eye(3) if axes is None else np.asarray(axes, np.float64)
    faces = [f for b in bodies for f in range(model.bodies[b]["faces"][0], sum(model.bodies[b]["faces"]))]
    if not faces:
        return None
    tess = [(f, model.face_triangles(f)[0]) for f in faces]
    tess = [(f, p) for f, p in tess if len(p)]
    allp = np.concatenate([p for _, p in tess])
    size = float(np.linalg.norm(np.ptp(allp, axis=0))) or 1.0
    lo, hi = np.zeros(3), np.zeros(3)
    for k in range(3):
        u = unit(axes[k])
        for side in (1, -1):
            proj = allp @ (u * side)
            best = float(proj.max())
            tol = size * 0.01  # the tessellation is never further than this inside the true surface
            cands = [f for f, p in tess if float((p @ (u * side)).max()) >= best - tol]
            exact = _extreme(gmsh, model, cands, u * side, best + size, size)
            val = exact if exact is not None else best
            if side == 1:
                hi[k] = val
            else:
                lo[k] = -val
    return {"min": lo, "max": hi, "size": hi - lo, "axes": axes, "exact": True}


def _extreme(gmsh, model, faces, u, park, size):
    """max over the faces of p·u: a plane at p·u = park, minus each face's distance to it."""
    plane = _temp_plane(gmsh, u, park, size * 4)
    try:
        best = None
        for f in faces:
            d = gmsh.model.occ.getDistance(2, int(model.face_tag[f]), 2, plane)[0]
            if d >= 0:
                v = park - d
                best = v if best is None else max(best, v)
        return best
    except Exception:
        return None
    finally:
        try:
            gmsh.model.occ.remove([(2, plane)], recursive=True)
        except Exception:
            pass


def _temp_plane(gmsh, u, offset, half):
    """A square face perpendicular to u at distance offset from the origin (not synchronised into
    the model: OpenCASCADE can measure to it straight away)."""
    u = unit(u)
    x = unit(np.cross(u, [0, 0, 1]) if abs(u[2]) < 0.9 else np.cross(u, [1, 0, 0]))
    y = np.cross(u, x)
    c = u * offset
    corners = [c + half * (sx * x + sy * y) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    occ = gmsh.model.occ
    pts = [occ.addPoint(*map(float, p)) for p in corners]
    lines = [occ.addLine(pts[i], pts[(i + 1) % 4]) for i in range(4)]
    loop = occ.addCurveLoop(lines)
    return occ.addPlaneSurface([loop])


# ---------------------------------------------------------------------------------------------- meshes
def mesh_mass(model, bodies, density):
    parts, area, names, notes = [], 0.0, [], []
    for b in bodies:
        f0, fn = model.bodies[b]["faces"]
        tris = [model.face_triangles(f) for f in range(f0, f0 + fn)]
        tri3 = np.concatenate([p[t] for p, t in tris if len(t)]) if tris else np.zeros((0, 3, 3))
        if not len(tri3):
            continue
        a, b_, c = tri3[:, 0], tri3[:, 1], tri3[:, 2]
        area += float(np.linalg.norm(np.cross(b_ - a, c - a), axis=1).sum() / 2)
        vol, com, inertia = _mesh_integrals(tri3)
        if not model.bodies[b].get("closed", True):
            notes.append(f"{model.bodies[b]['name']} isn't closed: volume is approximate")
        if vol < 0:
            vol, inertia = -vol, -inertia
        if vol > 0:
            parts.append((vol, com, inertia))
            names.append(model.bodies[b]["name"])
    vol, com, inertia = combine(parts)
    return report(vol, com, inertia, area, density, names, False, notes)


def _mesh_integrals(tri3):
    """Volume, centroid and inertia about the centroid (unit density) of a closed triangle mesh,
    from signed tetrahedra to the origin."""
    a, b, c = tri3[:, 0], tri3[:, 1], tri3[:, 2]
    det = np.einsum("ij,ij->i", a, np.cross(b, c))  # 6 × signed volume of each tetrahedron
    vol = float(det.sum() / 6)
    if abs(vol) < 1e-300:
        return 0.0, np.zeros(3), np.zeros((3, 3))
    com = ((a + b + c) * det[:, None]).sum(axis=0) / (24 * vol)
    # second moments ∫ x_i x_j dV over each tetrahedron (origin, a, b, c)
    s = a + b + c
    cov = np.zeros((3, 3))
    for i in range(3):
        for j in range(3):
            term = a[:, i] * a[:, j] + b[:, i] * b[:, j] + c[:, i] * c[:, j] + s[:, i] * s[:, j]
            cov[i, j] = float((det * term).sum() / 120)
    cov_c = cov - vol * np.outer(com, com)  # about the centroid
    inertia = np.trace(cov_c) * np.eye(3) - cov_c
    return vol, com, inertia


def mesh_bbox(model, bodies, axes=None):
    axes = np.eye(3) if axes is None else np.asarray(axes, np.float64)
    pts = []
    for b in bodies:
        f0, fn = model.bodies[b]["faces"]
        for f in range(f0, f0 + fn):
            p, _ = model.face_triangles(f)
            if len(p):
                pts.append(p)
    if not pts:
        return None
    allp = np.concatenate(pts) @ axes.T
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    return {"min": lo, "max": hi, "size": hi - lo, "axes": axes, "exact": True}


def oriented_axes(points):
    """A tight box orientation for stock sizing: principal axes of the points, then refined by
    trying rotations about each axis (minimum-volume search)."""
    pts = np.asarray(points, np.float64)
    if len(pts) > 60000:
        pts = pts[np.random.default_rng(0).choice(len(pts), 60000, replace=False)]
    c = pts - pts.mean(axis=0)
    _, vecs = np.linalg.eigh(c.T @ c)
    best_axes = vecs.T[::-1]

    def volume(ax):
        q = c @ ax.T
        return float(np.prod(np.ptp(q, axis=0)))

    best = volume(best_axes)
    for _ in range(2):
        for k in range(3):
            for ang in np.linspace(-np.pi / 4, np.pi / 4, 91):
                axes = _rotate_axes(best_axes, k, ang)
                v = volume(axes)
                if v < best - 1e-12:
                    best, cand = v, axes
                    best_axes = cand
    # order: longest first, right-handed
    q = c @ best_axes.T
    order = np.argsort(-np.ptp(q, axis=0))
    ax = best_axes[order]
    if np.linalg.det(ax) < 0:
        ax[2] = -ax[2]
    return ax


def _rotate_axes(axes, k, ang):
    i, j = [n for n in range(3) if n != k]
    cs, sn = np.cos(ang), np.sin(ang)
    out = axes.copy()
    out[i] = cs * axes[i] + sn * axes[j]
    out[j] = -sn * axes[i] + cs * axes[j]
    return out
