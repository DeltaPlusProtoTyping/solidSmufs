"""STEP / IGES / BREP through gmsh's OpenCASCADE kernel.

Reads the file, has OpenCASCADE tessellate it (gmsh's "STL" representation: BRepMesh, the same
mesher CAD programs use for display), and keeps the exact model loaded so the measure tool can ask
it for true distances, areas and mass properties. SolidWorks / Parasolid parts come here too, as a
STEP written by formats.parasolid.
"""

import math
import re
import time

import numpy as np

from .geom import circumcircle, unit, unit_rows, vertex_normals
from .model import Model

# (relative linear deflection, angular deflection in radians) for OpenCASCADE's mesher
QUALITY = {"coarse": (0.004, 0.6), "normal": (0.0012, 0.35), "fine": (0.0004, 0.2)}

SURFACE_TYPES = {"Plane": "plane", "Cylinder": "cylinder", "Cone": "cone", "Sphere": "sphere", "Torus": "torus",
                 "BSpline surface": "bspline", "Nurb": "bspline", "Bezier surface": "bezier",
                 "Surface of Revolution": "revolution", "Ruled surface": "ruled"}
CURVE_TYPES = {"Line": "line", "Circle": "circle", "Ellipse": "ellipse", "BSpline": "bspline", "Bezier": "bezier",
               "Parabola": "conic", "Hyperbola": "conic", "Conic": "conic"}

_started = False


def gmsh_ready():
    """gmsh, initialised once per worker; cleared for each new file."""
    global _started
    import gmsh

    if not _started:
        gmsh.initialize(["-noenv"], readConfigFiles=False)
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.Verbosity", 1)
        _started = True
    else:
        gmsh.clear()
    return gmsh


class CadModel(Model):
    kind = "brep"

    def __init__(self, name, path, fmt):
        super().__init__(name, path, fmt)
        self.face_tag = np.zeros(0, np.int64)
        self.edge_tag = np.zeros(0, np.int64)
        self.vert_tag = np.zeros(0, np.int64)
        self.body_tag = []  # gmsh volume tag per body (None for a group of loose faces)
        self.area_cache = {}


def load(path, name, fmt, quality="normal", progress=lambda *a: None, source=None, sew=False, importer=None,
         orient=None):
    """Read path (or `source`, an already translated STEP; or whatever `importer()` puts in gmsh, for
    assemblies) into a CadModel, turned by the 3x3 rotation `orient` when one is given (Align Part)."""
    t0 = time.perf_counter()
    progress("Reading " + fmt, 0.05)
    gmsh = importer() if importer else import_only(path, source, sew)
    if orient is not None:
        turn(gmsh, orient)
    t1 = time.perf_counter()

    progress("Tessellating", 0.4)
    lin, ang = QUALITY.get(quality, QUALITY["normal"])
    gmsh.option.setNumber("Mesh.StlLinearDeflection", lin)
    gmsh.option.setNumber("Mesh.StlLinearDeflectionRelative", 1)
    gmsh.option.setNumber("Mesh.StlAngularDeflection", ang)
    gmsh.model.mesh.importStl()
    t2 = time.perf_counter()

    progress("Building the model", 0.7)
    m = CadModel(name, path, fmt)
    _extract(gmsh, m)
    t3 = time.perf_counter()
    m.stats.update(read_s=round(t1 - t0, 3), tessellate_s=round(t2 - t1, 3), build_s=round(t3 - t2, 3),
                   quality=quality)
    return m


def import_only(path, source=None, sew=False):
    """Read the file into gmsh / OpenCASCADE (no tessellation). Same options every time, so the
    entity numbering matches a cached tessellation of the same file."""
    gmsh = gmsh_ready()
    gmsh.option.setNumber("Geometry.OCCImportLabels", 1)
    gmsh.option.setNumber("Geometry.OCCParallel", 1)
    try:
        gmsh.model.occ.importShapes(str(source or path))
        gmsh.model.occ.synchronize()
    except Exception as e:
        raise ValueError(_gmsh_error(e)) from None
    if not gmsh.model.getEntities(2):
        raise ValueError("No surfaces or solids found in this file.")
    if sew and not gmsh.model.getEntities(3):
        _try_sew(gmsh)
    return gmsh


def import_assembly(parts, top, failed=None):
    """Place parts into one gmsh / OpenCASCADE model: `parts` is [(STEP path, [(4x4 matrix in mm,
    instance names such as ["crank sub-1", "crank-arm-1"])])]. Each STEP is read once and copied for its
    other instances. A part OpenCASCADE can't read is skipped and added to `failed` as (index in parts,
    message), so one bad part doesn't stop the assembly. Same order every time, so the numbering matches
    a cached tessellation."""
    gmsh = gmsh_ready()
    gmsh.option.setNumber("Geometry.OCCImportLabels", 1)
    gmsh.option.setNumber("Geometry.OCCParallel", 1)
    occ = gmsh.model.occ
    placed = []  # (entities of one instance, names for them, template looks)
    for index, (step, instances) in enumerate(parts):
        before = set(occ.getEntities())
        reading = True  # gmsh keeps its last error text, so say which step failed rather than echo it
        try:
            ents = occ.importShapes(str(step))
            reading = False
            occ.synchronize()
            top_dim = max((d for d, _ in ents), default=0)
            ents = [(d, t) for d, t in ents if d == top_dim]
            looks = [_looks(gmsh, d, t) for d, t in ents]  # moving a shape drops its imported colors and names
            copies = [ents] + [occ.copy(ents) for _ in instances[1:]]
            for dimtags, (matrix, _names) in zip(copies, instances):
                _move(occ, dimtags, np.asarray(matrix, np.float64))
            occ.synchronize()  # per part, so a shape OpenCASCADE can't bind is traced to its part
        except Exception as e:
            if failed is None:
                raise ValueError(_gmsh_error(e)) from None
            detail = _gmsh_error(e)
            echo = any(detail in why for _i, why in failed)  # gmsh's sticky last error, not this part's
            failed.append((index, "OpenCASCADE could not read it" if reading
                           else "OpenCASCADE could not repair its shape" + ("" if echo else f": {detail}")))
            _remove_new(occ, before)
            continue
        placed += [(dimtags, _instance_names(top, names, looks), looks)
                   for dimtags, (_m, names) in zip(copies, instances)]
    for dimtags, names, looks in placed:
        for (d, t), name, (_, color, face_colors) in zip(dimtags, names, looks):
            gmsh.model.setEntityName(d, t, name)
            if color:
                gmsh.model.setColor([(d, t)], *color)
            faces = _faces_of(gmsh, d, t)
            for f, c in zip(faces, face_colors):
                if c:
                    gmsh.model.setColor([(2, f)], *c)
    if not gmsh.model.getEntities(2):
        raise ValueError("No surfaces or solids found in this assembly.")
    return gmsh


def turn(gmsh, rot):
    """Turn the whole model by the 3x3 rotation `rot` about the origin, exactly (see _move), keeping the
    names and colours the file gave it (moving a shape drops them). Entity numbers don't change."""
    occ = gmsh.model.occ
    vols = gmsh.model.getEntities(3)
    in_vol = {abs(t) for _d, t in gmsh.model.getBoundary(vols, combined=False, oriented=False)} if vols else set()
    tops = vols + [(2, t) for _d, t in gmsh.model.getEntities(2) if t not in in_vol]
    looks = [_looks(gmsh, d, t) for d, t in tops]
    m = np.eye(4)
    m[:3, :3] = np.asarray(rot, np.float64)
    _move(occ, tops, m)
    occ.synchronize()
    for (d, t), (name, color, face_colors) in zip(tops, looks):
        if name:
            gmsh.model.setEntityName(d, t, name)
        if color:
            gmsh.model.setColor([(d, t)], *color)
        for f, col in zip(_faces_of(gmsh, d, t), face_colors):
            if col:
                gmsh.model.setColor([(2, f)], *col)


def _remove_new(occ, before):
    """Take out what a failed part left in the model, so the parts after it still bind."""
    new = [e for e in occ.getEntities() if e not in before]
    try:
        if new:
            occ.remove(new, recursive=True)
        occ.synchronize()
    except Exception:  # nothing more to clean; the next part's synchronize reports anything lasting
        pass


def _move(occ, dimtags, matrix):
    """Apply a rigid 4x4 placement exactly: a rotation about the origin, then a translation.
    Not occ.affineTransform: that general transform turns every surface into an approximating spline,
    so cylinders stop being cylinders (hole sizes, measuring) and volumes drift by about 1%."""
    rot, t = matrix[:3, :3], matrix[:3, 3]
    axis, angle = _axis_angle(rot)
    if angle > 1e-12:
        occ.rotate(dimtags, 0.0, 0.0, 0.0, *axis, angle)
    if np.abs(t).max() > 0:
        occ.translate(dimtags, *map(float, t))


def _axis_angle(rot):
    """(unit axis, angle in radians) of a rotation matrix."""
    angle = float(np.arccos(np.clip((np.trace(rot) - 1) / 2, -1.0, 1.0)))
    if angle < 1e-12:
        return (0.0, 0.0, 1.0), 0.0
    if np.pi - angle > 1e-6:
        axis = np.array([rot[2, 1] - rot[1, 2], rot[0, 2] - rot[2, 0], rot[1, 0] - rot[0, 1]])
    else:  # a half turn: the skew part vanishes; the axis is the column of R + I with the most length
        sym = rot + np.eye(3)
        axis = sym[:, int(np.argmax(np.linalg.norm(sym, axis=0)))]
    return tuple(float(x) for x in axis / np.linalg.norm(axis)), angle


def _faces_of(gmsh, dim, tag):
    if dim == 2:
        return [tag]
    return [abs(f) for _, f in gmsh.model.getBoundary([(dim, tag)], combined=False, oriented=False, recursive=False)]


def _looks(gmsh, dim, tag):
    """(name, RGBA, [face RGBA]) of an imported entity; RGBA None when it has no color of its own."""
    def rgba(d, t):
        c = gmsh.model.getColor(d, t)
        return None if c[3] == 0 else tuple(int(x) for x in c)
    return gmsh.model.getEntityName(dim, tag), rgba(dim, tag), [rgba(2, f) for f in _faces_of(gmsh, dim, tag)]


def _instance_names(top, names, looks):
    """Entity names in the STEP-assembly style the tree understands: "UJoint/crank sub::1/crank sub/
    crank-arm::1/crank-arm" shows as crank-arm<1> inside crank sub<1>, the way SolidWorks labels them.
    A part with several bodies adds each body's own name."""
    parts = [top]
    for n in names:
        m = re.match(r"^(.*)-(\d+)$", n)
        parts += [f"{m.group(1)}::{m.group(2)}", m.group(1)] if m else [n]
    base = "/".join(p.replace("/", "-") for p in parts)
    if len(looks) == 1:
        return [base]
    return [f"{base}/{(_body_path(name) or [f'Body {i + 1}'])[-1]}" for i, (name, _, _) in enumerate(looks)]


def _gmsh_error(e):
    msg = str(e) or "OpenCASCADE could not read this file."
    if "Unknown OpenCASCADE" in msg or "Could not read" in msg:
        return "OpenCASCADE could not read this file (it may be damaged or not really this format)."
    return msg


def _try_sew(gmsh):
    """Loose trimmed surfaces (typical IGES) → sewn shells / solids, so mass properties work."""
    try:
        box = gmsh.model.getBoundingBox(-1, -1)
        size = max(float(np.linalg.norm(np.subtract(box[3:], box[:3]))), 1e-6)
        gmsh.model.occ.healShapes(tolerance=min(max(size * 1e-5, 1e-6), 0.01), fixDegenerated=False,
                                  fixSmallEdges=False, fixSmallFaces=False, sewFaces=True, makeSolids=True)
        gmsh.model.occ.synchronize()
    except Exception:
        pass


# ---------------------------------------------------------------------------------------------- build
def _color(gmsh, dim, tag):
    r, g, b, a = gmsh.model.getColor(dim, tag)
    return None if a == 0 else [r / 255, g / 255, b / 255]


def _body_path(name):
    """'Shapes/as1/L-BRACKET-ASSEMBLY::1/l-bracket-assembly/BOLT/bolt' → readable path parts."""
    parts = [p.strip() for p in (name or "").split("/") if p.strip()]
    if parts and parts[0] == "Shapes":
        parts = parts[1:]
    out = []
    for p in parts:
        if p.startswith("=>") or p.upper() in ("SOLID", "SHELL", "COMPOUND", "FACE"):
            continue
        p = p.replace(" & & 256", "").strip()
        if out and out[-1].lower() == p.lower():
            continue
        out.append(p)
    return out


def _body_name(path):
    """The part's name for the tree: 'NUT::1' then 'nut' reads 'nut<1>', the way SolidWorks shows instances."""
    if not path:
        return None
    name = path[-1]
    if len(path) > 1:
        inst = re.match(r"^(.*)::(\d+)$", path[-2])
        if inst and inst.group(1).lower() == name.lower():
            return f"{name}<{inst.group(2)}>"
    return name


class _NodeTable:
    """Mesh node tags → coordinates, for many lookups at once."""

    def __init__(self, tags, coord):
        tags = np.asarray(tags, np.int64)
        self.order = np.argsort(tags, kind="stable")
        self.sorted = tags[self.order]
        self.coord = np.asarray(coord, np.float64).reshape(-1, 3)

    def __call__(self, tags):
        i = np.clip(np.searchsorted(self.sorted, tags), 0, len(self.sorted) - 1)
        return self.coord[self.order[i]]


def _extract(gmsh, m):
    vols = [t for _, t in gmsh.model.getEntities(3)]
    all_faces = [t for _, t in gmsh.model.getEntities(2)]
    owner = {}
    groups = []
    for v in vols:
        fs = []
        for _, f in gmsh.model.getBoundary([(3, v)], combined=False, oriented=False, recursive=False):
            f = abs(f)
            if f not in owner:
                owner[f] = len(groups)
                fs.append(f)
        groups.append(("solid", v, fs))
    loose = [f for f in all_faces if f not in owner]
    if loose:
        for f in loose:
            owner[f] = len(groups)
        groups.append(("sheet", None, loose))

    # every mesh node once; faces and edges look their nodes up here (far fewer gmsh calls)
    ntags, coord, _ = gmsh.model.mesh.getNodes(-1, -1, includeBoundary=False, returnParametricCoord=False)
    nodes = _NodeTable(ntags, coord)

    # bodies and faces
    pos, nrm, idx = [], [], []
    face_tags, edge_faces = [], {}
    vcount = tcount = 0
    used_names = {}
    for bi, (kind, v, fs) in enumerate(groups):
        if v is not None:
            path = _body_path(gmsh.model.getEntityName(3, v))
            name = _body_name(path) or f"Body {bi + 1}"
            color = _color(gmsh, 3, v)
        else:
            path, name, color = [], "Surface body", None
        key = (tuple(path[:-1]), name)  # names only need to differ within the same sub-assembly
        n = used_names.get(key, 0)
        used_names[key] = n + 1
        if n:
            name = f"{name} ({n + 1})"
        start = len(face_tags)
        for f in fs:
            fi = len(face_tags)
            pts, tri = _face_mesh(gmsh, f, nodes)
            typ = SURFACE_TYPES.get(gmsh.model.getType(2, f), "surface")
            params = _surface_params(gmsh, f, typ, pts)
            if params is None and typ in FITTABLE and len(tri):
                fit = _fitted_cylinder(gmsh, f, pts, tri)
                if fit is not None:  # a bore or boss stored as a spline / swept surface: measure it as the cylinder it is
                    typ, params = "cylinder", fit
                else:
                    fit = _fitted_cone(pts, tri)
                    if fit is not None:  # likewise a drafted bore or boss: a cone
                        typ, params = "cone", fit
            normals = _face_normals(typ, params, pts, tri) if len(tri) else pts
            for c in set(int(c) for c in gmsh.model.getAdjacencies(2, f)[1]):  # a seam is listed twice
                edge_faces.setdefault(c, []).append(fi)
            m.face_type.append(typ)
            m.face_color.append(_color(gmsh, 2, f))
            m.face_params.append(params)
            m.face_body.append(bi)
            m.face_vstart.append(vcount)
            m.face_vcount.append(len(pts))
            m.face_tstart.append(tcount)
            m.face_tcount.append(len(tri))
            pos.append(pts)
            nrm.append(normals)
            idx.append(tri + vcount)
            vcount += len(pts)
            tcount += len(tri)
            face_tags.append(f)
        m.bodies.append({"name": name, "path": path, "kind": kind, "color": color, "faces": [start, len(fs)]})
        m.body_tag.append(v)
    m.face_tag = np.array(face_tags, np.int64)
    m.positions = np.concatenate(pos).astype(np.float32) if pos else m.positions
    m.normals = np.concatenate(nrm).astype(np.float32) if nrm else m.normals
    m.indices = np.concatenate(idx).astype(np.uint32) if idx else m.indices

    # edges
    segs, edge_tags = [], []
    scount = 0
    for _, c in gmsh.model.getEntities(1):
        s = _edge_mesh(gmsh, c, nodes)
        if not len(s):
            continue
        fidx = edge_faces.get(int(c), [])
        typ = CURVE_TYPES.get(gmsh.model.getType(1, c), "curve")
        try:
            length = gmsh.model.occ.getMass(1, c)
        except Exception:
            length = float(np.linalg.norm(s[:, 1] - s[:, 0], axis=1).sum())
        seam = len(fidx) == 1 and groups[owner[face_tags[fidx[0]]]][0] == "solid"
        m.edge_type.append(typ)
        m.edge_params.append(_curve_params(gmsh, c, typ, length, s))
        m.edge_length.append(length)
        m.edge_faces.append(fidx)
        m.edge_seam.append(bool(seam))
        m.edge_sstart.append(scount)
        m.edge_scount.append(len(s))
        segs.append(s)
        scount += len(s)
        edge_tags.append(c)
    m.edge_tag = np.array(edge_tags, np.int64)
    m.segments = np.concatenate(segs).astype(np.float32) if segs else m.segments

    # vertices
    vt, vp = [], []
    for _, p in gmsh.model.getEntities(0):
        try:
            vp.append(np.asarray(gmsh.model.getValue(0, p, []), np.float64)[:3])
            vt.append(p)
        except Exception:
            pass
    m.vert_tag = np.array(vt, np.int64)
    m.vertices = np.array(vp, np.float64).reshape(-1, 3)


def _face_mesh(gmsh, f, nodes):
    """(points, triangles) of one face's tessellation, compacted to the points it uses."""
    _, tri_tags = gmsh.model.mesh.getElementsByType(2, f)
    if not len(tri_tags):
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    used, inv = np.unique(np.asarray(tri_tags, np.int64), return_inverse=True)
    return nodes(used), inv.reshape(-1, 3).astype(np.int64)


def _face_normals(typ, params, pts, tri):
    """Normals at the face's points: worked out from the surface where it's a known shape (so curved
    faces shade smoothly), otherwise averaged from the triangles; oriented like the triangles."""
    avg = vertex_normals(pts, tri)
    if typ == "plane":
        a, b, c = pts[tri[:, 0]], pts[tri[:, 1]], pts[tri[:, 2]]
        n = unit(np.cross(b - a, c - a).sum(axis=0))
        return np.repeat(n[None, :], len(pts), axis=0)
    n = _analytic_normals(typ, params, pts)
    if n is None:
        return avg
    ok = np.linalg.norm(n, axis=1) > 0.5
    if float(np.einsum("ij,ij->i", n[ok], avg[ok]).sum()) < 0:
        n = -n
    good = ok & (np.einsum("ij,ij->i", n, avg) > 0.3)
    n[~good] = avg[~good]
    return n


def _analytic_normals(typ, pr, pts):
    if not pr:
        return None
    if typ == "cylinder":
        a, d = pr["axis"], pts - pr["center"]
        return unit_rows(d - np.outer(d @ a, a))
    if typ == "sphere":
        return unit_rows(pts - pr["center"])
    if typ == "cone" and pr.get("apex") is not None:
        a, half = pr["axis"], math.radians(pr["half_angle"])
        d = pts - pr["apex"]
        radial = unit_rows(d - np.outer(d @ a, a))
        return unit_rows(radial * math.cos(half) - a[None, :] * math.sin(half))
    if typ == "torus":
        a, c = pr["axis"], pr["center"]
        d = pts - c
        radial = unit_rows(d - np.outer(d @ a, a))
        return unit_rows(pts - (c + radial * pr["major_radius"]))
    return None


def _edge_mesh(gmsh, c, nodes):
    """The edge's polyline as (k, 2, 3) segments, in order along the edge."""
    _, seg_tags = gmsh.model.mesh.getElementsByType(1, c)
    if not len(seg_tags):
        return np.zeros((0, 2, 3))
    s = nodes(np.asarray(seg_tags, np.int64)).reshape(-1, 2, 3)
    keep = np.linalg.norm(s[:, 1] - s[:, 0], axis=1) > 0
    return s[keep]


# ---------------------------------------------------------------------------------------------- analytic data
def _vals(gmsh, dim, tag, pars):
    """Points at several parameter values in one call."""
    flat = [float(x) for p in pars for x in p]
    return np.asarray(gmsh.model.getValue(dim, tag, flat), np.float64).reshape(-1, 3)


FITTABLE = {"bspline", "bezier", "revolution", "ruled", "surface"}


def _fitted_cylinder(gmsh, f, pts, tri):
    """Cylinder params for a face that is a cylinder in all but name, or None. Points sampled on the
    true surface must sit at one radius from one axis to within 0.1% (and 5 microns); the axis is the direction
    every surface normal is square to. Nearly flat faces (normals all alike) don't count."""
    try:
        lo, hi = (np.asarray(b, np.float64) for b in gmsh.model.getParametrizationBounds(2, f))
        uv = [(lo[0] + (hi[0] - lo[0]) * i / 8, lo[1] + (hi[1] - lo[1]) * j / 8) for i in range(9) for j in range(9)]
        q = _vals(gmsh, 2, f, uv)
    except Exception:
        q = np.asarray(pts, np.float64)
    if len(q) < 12:
        return None
    nrm = vertex_normals(pts, tri)
    ev, vec = np.linalg.eigh(nrm.T @ nrm / max(len(nrm), 1))
    if ev[0] > 2e-3 * ev.sum() or ev[1] < 0.02 * ev.sum():  # normals not all square to one axis / all alike
        return None
    axis = unit(vec[:, 0])
    x = unit(np.cross(axis, [1, 0, 0]) if abs(axis[0]) < 0.9 else np.cross(axis, [0, 1, 0]))
    y = np.cross(axis, x)
    p2 = np.c_[q @ x, q @ y]
    a = np.c_[2 * p2, np.ones(len(p2))]
    (cx, cy, _), *_ = np.linalg.lstsq(a, (p2 ** 2).sum(1), rcond=None)
    r = np.linalg.norm(p2 - [cx, cy], axis=1)
    rad = float(r.mean())
    size = float(np.linalg.norm(np.ptp(q, axis=0)))
    # spline copies of a cylinder are off by a micron or two; a real non-cylinder by far more
    if not (0 < rad < 5 * max(size, 1e-9)) or float(np.abs(r - rad).max()) > min(1e-3 * rad, 0.005):
        return None
    c = cx * x + cy * y + axis * float((q @ axis).mean())  # the axis point level with the face's middle
    return {"center": c, "axis": axis, "radius": rad, "fitted": True}


def _fitted_cone(pts, tri):
    """Cone params (as _surface_params gives them) for a face that is a cone in all but name, typically
    a drafted bore or boss, or None. Every normal of a cone leans the same way off its axis and passes
    through it: the axis is the direction the normals all make one angle with, its position the point
    their lines meet at, and the radius must then grow in a straight line along it (to 0.1%)."""
    pts = np.asarray(pts, np.float64)
    if len(pts) < 12:
        return None
    nrm = vertex_normals(pts, tri)
    cov = np.cov((nrm - nrm.mean(axis=0)).T)
    ev, vec = np.linalg.eigh(cov)
    if ev[0] > 2e-4 * ev.sum() or ev[1] < 0.02 * ev.sum():
        return None
    a = unit(vec[:, 0])
    x = unit(np.cross(a, [1, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1, 0]))
    y = np.cross(a, x)
    p2, n2 = np.c_[pts @ x, pts @ y], np.c_[nrm @ x, nrm @ y]
    n2 = n2 / np.maximum(np.linalg.norm(n2, axis=1), 1e-12)[:, None]
    m = np.eye(2)[None] - n2[:, :, None] * n2[:, None, :]  # each normal line's "distance to it" projector
    try:
        cxy = np.linalg.solve(m.sum(axis=0), np.einsum("nij,nj->i", m, p2))
    except np.linalg.LinAlgError:
        return None
    z = pts @ a
    if np.ptp(z) < 1e-9:
        return None
    for _ in range(6):  # refine: radius straight along the axis, centre where every point fits that radius
        r = np.linalg.norm(p2 - cxy, axis=1)
        k, b = np.polyfit(z, r, 1)
        lhs = np.c_[2 * p2, np.ones(len(p2))]
        sol, *_ = np.linalg.lstsq(lhs, (p2 ** 2).sum(1) - (k * z + b) ** 2, rcond=None)
        cxy = sol[:2]
    r = np.linalg.norm(p2 - cxy, axis=1)
    k, b = np.polyfit(z, r, 1)
    if float(np.abs(r - (k * z + b)).max()) > 1e-3 * float(r.mean()) or abs(k) < math.tan(math.radians(0.05)):
        return None
    if k < 0:  # point the axis away from the apex
        a, z, k, b = -a, -z, -k, b
    base = cxy[0] * x + cxy[1] * y  # the axis where it crosses the plane through the origin (z = 0 along a)
    if float(base @ a) != 0:
        base = base - a * float(base @ a)
    z0, z1 = float(z.min()), float(z.max())
    return {"center": base + a * z0, "axis": a, "half_angle": math.degrees(math.atan(k)), "apex": base + a * (-b / k),
            "radius_min": float(k * z0 + b), "radius_max": float(k * z1 + b), "fitted": True}


def _surface_params(gmsh, f, typ, pts):
    """What the measure tool shows for a face: plane normal, cylinder axis and radius, … (mm)."""
    if typ not in ("plane", "cylinder", "cone", "sphere", "torus"):
        return None
    try:
        lo, hi = (np.asarray(b, np.float64) for b in gmsh.model.getParametrizationBounds(2, f))
        um, vm = (lo + hi) / 2
        pi = math.pi
        centroid = pts.mean(axis=0) if len(pts) else None
        if typ == "plane":
            n = unit(gmsh.model.getNormal(f, [um, vm]))
            origin = centroid if centroid is not None else _vals(gmsh, 2, f, [(um, vm)])[0]
            return {"origin": origin, "normal": n}
        if typ == "cylinder":
            p0, p1, p2 = _vals(gmsh, 2, f, [(um, vm), (um + pi, vm), (um + pi / 2, vm)])
            c, r = (p0 + p1) / 2, float(np.linalg.norm(p0 - p1)) / 2
            if abs(float(np.linalg.norm(p2 - c)) - r) > 1e-6 * max(r, 1):
                return None
            axis = unit(np.asarray(gmsh.model.getDerivative(2, f, [um, vm]), np.float64)[3:6])
            if centroid is not None:  # put the axis point level with the face's middle
                c = c + axis * float((centroid - c) @ axis)
            return {"center": c, "axis": axis, "radius": r}
        if typ == "cone":
            va, vb = vm, vm + max((hi[1] - lo[1]) * 0.25, 1e-3)
            q = _vals(gmsh, 2, f, [(um, va), (um + pi, va), (um, vb), (um + pi, vb),
                                   (um, lo[1]), (um + pi, lo[1]), (um, hi[1]), (um + pi, hi[1])])
            ca, cb = (q[0] + q[1]) / 2, (q[2] + q[3]) / 2
            ra, rb = float(np.linalg.norm(q[0] - ca)), float(np.linalg.norm(q[2] - cb))
            h = float(np.linalg.norm(cb - ca))
            if h < 1e-12:
                return None
            axis = unit(cb - ca) * (1 if rb >= ra else -1)  # pointing away from the apex
            half = math.atan2(abs(rb - ra), h)
            apex = ca - axis * (ra / math.tan(half)) if half > 1e-9 else None
            r_lo = float(np.linalg.norm(q[4] - (q[4] + q[5]) / 2))
            r_hi = float(np.linalg.norm(q[6] - (q[6] + q[7]) / 2))
            return {"center": ca, "axis": axis, "half_angle": math.degrees(half), "apex": apex,
                    "radius_min": min(r_lo, r_hi), "radius_max": max(r_lo, r_hi)}
        if typ == "sphere":
            pa, pb, pc = _vals(gmsh, 2, f, [(um, vm), (um + pi, -vm), (um + 1.0, vm * 0.5)])
            c, r = (pa + pb) / 2, float(np.linalg.norm(pa - pb)) / 2
            if abs(float(np.linalg.norm(pc - c)) - r) > 1e-6 * max(r, 1):
                return None
            return {"center": c, "radius": r}
        if typ == "torus":
            q = _vals(gmsh, 2, f, [(um, vm), (um, vm + pi), (um + pi, vm), (um + pi, vm + pi),
                                   (um + pi / 2, vm), (um + pi / 2, vm + pi)])
            t1, t2, t3 = (q[0] + q[1]) / 2, (q[2] + q[3]) / 2, (q[4] + q[5]) / 2
            c = (t1 + t2) / 2
            return {"center": c, "axis": unit(np.cross(t1 - c, t3 - c)), "major_radius": float(np.linalg.norm(t1 - c)),
                    "minor_radius": float(np.linalg.norm(q[0] - q[1])) / 2}
    except Exception:
        return None
    return None


def _curve_params(gmsh, c, typ, length, segs):
    """Line ends, circle centre / radius / normal, … The edge's polyline points lie exactly on the
    curve (OpenCASCADE puts them there), so lines and circles are read straight off them."""
    try:
        pts = np.concatenate([segs[:, 0], segs[-1:, 1]])
        a, b = pts[0], pts[-1]
        scale = max(float(np.linalg.norm(np.ptp(pts, axis=0))), 1e-9)
        closed = float(np.linalg.norm(a - b)) < 1e-7 * scale or (len(pts) > 3 and float(np.linalg.norm(a - b)) < 1e-9)
        if typ == "line":
            return {"start": a, "end": b, "dir": unit(b - a)}
        if typ == "circle":
            k = len(pts) - 1
            if closed and k >= 3:
                fit = circumcircle(pts[0], pts[k // 3], pts[(2 * k) // 3])
            elif not closed and k >= 2:
                fit = circumcircle(a, pts[k // 2], b)
            else:  # too few points on the polyline: ask the curve
                (t0,), (t1,) = (np.asarray(x, np.float64) for x in gmsh.model.getParametrizationBounds(1, c))
                q = _vals(gmsh, 1, c, [(t0,), ((t0 + t1) / 2,), (t1,)] if not closed else
                          [(t0,), (t0 + (t1 - t0) / 3,), (t0 + 2 * (t1 - t0) / 3,)])
                fit = circumcircle(*q)
            if fit is None:
                return None
            centre, r, n = fit
            return {"center": centre, "radius": r, "normal": n, "closed": closed,
                    "angle": 360.0 if closed else math.degrees(length / r) if r > 0 else 0.0,
                    "start": a, "end": b}
        if typ == "ellipse":
            (t0,), _ = (np.asarray(x, np.float64) for x in gmsh.model.getParametrizationBounds(1, c))
            q = _vals(gmsh, 1, c, [(t,) for t in np.linspace(t0, t0 + 2 * math.pi, 73)[:-1]])
            centre = q.mean(axis=0)
            d = np.linalg.norm(q - centre, axis=1)
            i, j = int(d.argmax()), int(d.argmin())
            return {"center": centre, "major_radius": float(d[i]), "minor_radius": float(d[j]),
                    "normal": unit(np.cross(q[i] - centre, q[j] - centre)), "major_dir": unit(q[i] - centre),
                    "closed": closed, "start": a, "end": b}
        return {"start": a, "end": b, "closed": closed}
    except Exception:
        return None
