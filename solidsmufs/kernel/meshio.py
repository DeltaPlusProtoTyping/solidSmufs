"""Triangle-mesh formats (STL, OBJ, PLY, OFF, 3MF, glTF/GLB) and turning a raw mesh into something
the measure tool can work with: each object becomes a body, its triangles are split into faces
along sharp creases (so you can pick a flat face or a hole wall the way you would on a solid),
creases become edges (holes come out as true circles when they fit one), and corners become
vertices.

Meshes carry no units; they're taken as millimetres (3MF and glTF say theirs and are converted).
"""

import json
import math
import re
import struct
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from .geom import unit, unit_rows, vertex_normals
from .model import Model

MESH_EXTS = (".stl", ".obj", ".ply", ".off", ".3mf", ".glb", ".gltf")
CREASE_DEG = 28.0


class MeshModel(Model):
    kind = "mesh"


# ---------------------------------------------------------------------------------------------- readers
def read(path):
    """[(name, points (n, 3), triangles (m, 3), colour or None)], units label."""
    ext = Path(path).suffix.lower()
    data = Path(path).read_bytes()
    if ext == ".stl":
        return _stl(data, Path(path).stem), "mm"
    if ext == ".obj":
        return _obj(data, Path(path)), "mm"
    if ext == ".ply":
        return _ply(data, Path(path).stem), "mm"
    if ext == ".off":
        return _off(data, Path(path).stem), "mm"
    if ext == ".3mf":
        return _3mf(path)
    if ext in (".glb", ".gltf"):
        return _gltf(data, Path(path)), "m→mm"
    raise ValueError(f"Can't read {ext} files.")


def _stl(data, name):
    n = int.from_bytes(data[80:84], "little") if len(data) >= 84 else 0
    if len(data) == 84 + n * 50 and n:
        rec = np.frombuffer(data, np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n, offset=84)
        tri3 = rec["v"].astype(np.float64)
        color = None
        if data[:80].find(b"COLOR=") >= 0:  # Materialise / VisCAM header colour
            i = data.find(b"COLOR=")
            color = [data[i + 6] / 255, data[i + 7] / 255, data[i + 8] / 255]
        return [(name, tri3.reshape(-1, 3), np.arange(len(tri3) * 3).reshape(-1, 3), color)]
    text = data.decode("latin-1")
    out = []
    for m in re.finditer(r"solid\s*([^\n\r]*)(.*?)endsolid", text, re.S | re.I):
        vals = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", m.group(2), re.I)
        if vals:
            pts = np.array(vals, np.float64)
            out.append((m.group(1).strip() or name, pts, np.arange(len(pts)).reshape(-1, 3), None))
    if not out:
        vals = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text, re.I)
        if not vals:
            raise ValueError("No triangles in this STL.")
        pts = np.array(vals, np.float64)
        out.append((name, pts, np.arange(len(pts)).reshape(-1, 3), None))
    return out


def _obj(data, path):
    verts, groups, colors = [], {}, {}
    mtl = {}
    cur, cur_mtl = path.stem, None
    for raw in data.decode("latin-1").splitlines():
        line = raw.strip()
        if not line or line[0] == "#":
            continue
        parts = line.split()
        tag = parts[0]
        if tag == "v" and len(parts) >= 4:
            verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif tag == "f" and len(parts) >= 4:
            idx = []
            for p in parts[1:]:
                k = int(p.split("/")[0])
                idx.append(k - 1 if k > 0 else len(verts) + k)
            g = groups.setdefault(cur, [])
            for i in range(1, len(idx) - 1):  # fan-triangulate polygons
                g.append((idx[0], idx[i], idx[i + 1]))
            if cur_mtl and cur not in colors and cur_mtl in mtl:
                colors[cur] = mtl[cur_mtl]
        elif tag in ("o", "g") and len(parts) > 1:
            cur = " ".join(parts[1:])
        elif tag == "usemtl" and len(parts) > 1:
            cur_mtl = parts[1]
        elif tag == "mtllib" and len(parts) > 1:
            mtl.update(_read_mtl(path.parent / " ".join(parts[1:])))
    pts = np.array(verts, np.float64).reshape(-1, 3)
    out = []
    for name, tris in groups.items():
        if tris:
            out.append((name, pts, np.array(tris, np.int64), colors.get(name)))
    if not out:
        raise ValueError("No faces in this OBJ.")
    return out


def _read_mtl(p):
    out, cur = {}, None
    try:
        for line in Path(p).read_text(errors="replace").splitlines():
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "newmtl" and len(parts) > 1:
                cur = parts[1]
            elif parts[0] == "Kd" and cur and len(parts) >= 4:
                out[cur] = [float(parts[1]), float(parts[2]), float(parts[3])]
    except OSError:
        pass
    return out


def _ply(data, name):
    end = data.find(b"end_header")
    if not data.startswith(b"ply") or end < 0:
        raise ValueError("Not a PLY file.")
    header = data[:end].decode("latin-1").splitlines()
    body = data[data.index(b"\n", end) + 1:]
    fmt = "ascii"
    elements, cur = [], None
    for line in header:
        p = line.split()
        if not p:
            continue
        if p[0] == "format":
            fmt = p[1]
        elif p[0] == "element":
            cur = {"name": p[1], "count": int(p[2]), "props": []}
            elements.append(cur)
        elif p[0] == "property" and cur is not None:
            if p[1] == "list":
                cur["props"].append((p[4], "list", p[2], p[3]))
            else:
                cur["props"].append((p[2], p[1]))
    types = {"char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1", "short": "i2", "int16": "i2",
             "ushort": "u2", "uint16": "u2", "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
             "float": "f4", "float32": "f4", "double": "f8", "float64": "f8"}
    verts, faces, colors = None, [], None
    if fmt == "ascii":
        tokens = body.decode("latin-1").split()
        pos = 0
        for el in elements:
            if el["name"] == "vertex":
                n, k = el["count"], len(el["props"])
                arr = np.array(tokens[pos:pos + n * k], np.float64).reshape(n, k)
                pos += n * k
                names = [p[0] for p in el["props"]]
                verts = arr[:, [names.index("x"), names.index("y"), names.index("z")]]
                if "red" in names:
                    colors = arr[:, [names.index("red"), names.index("green"), names.index("blue")]].mean(axis=0) / 255
            elif el["name"] == "face":
                for _ in range(el["count"]):
                    cnt = int(tokens[pos])
                    idx = [int(t) for t in tokens[pos + 1:pos + 1 + cnt]]
                    pos += 1 + cnt
                    for i in range(1, cnt - 1):
                        faces.append((idx[0], idx[i], idx[i + 1]))
                    pos += len(el["props"]) - 1  # other face properties (rare)
            else:
                pos += el["count"] * len(el["props"])
    else:
        end_c = "<" if "little" in fmt else ">"
        off = 0
        for el in elements:
            if all(p[1] != "list" for p in el["props"]):
                dt = np.dtype([(p[0], end_c + types[p[1]]) for p in el["props"]])
                arr = np.frombuffer(body, dt, count=el["count"], offset=off)
                off += dt.itemsize * el["count"]
                if el["name"] == "vertex":
                    verts = np.stack([arr["x"], arr["y"], arr["z"]], axis=1).astype(np.float64)
                    if "red" in dt.names:
                        colors = np.stack([arr["red"], arr["green"], arr["blue"]], axis=1).mean(axis=0) / 255
            else:
                for _ in range(el["count"]):
                    for p in el["props"]:
                        if p[1] == "list":
                            ct = np.dtype(end_c + types[p[2]])
                            it = np.dtype(end_c + types[p[3]])
                            cnt = int(np.frombuffer(body, ct, 1, off)[0])
                            off += ct.itemsize
                            idx = np.frombuffer(body, it, cnt, off).astype(np.int64)
                            off += it.itemsize * cnt
                            if el["name"] == "face" and p[0] in ("vertex_indices", "vertex_index"):
                                for i in range(1, cnt - 1):
                                    faces.append((idx[0], idx[i], idx[i + 1]))
                        else:
                            off += np.dtype(types[p[1]]).itemsize
    if verts is None or not faces:
        raise ValueError("No triangles in this PLY.")
    col = [float(c) for c in colors] if colors is not None else None
    return [(name, verts, np.array(faces, np.int64), col)]


def _off(data, name):
    tokens = [t for line in data.decode("latin-1").splitlines() for t in line.split("#")[0].split()]
    if not tokens or not tokens[0].endswith("OFF"):
        raise ValueError("Not an OFF file.")
    nv, nf = int(tokens[1]), int(tokens[2])
    pos = 4
    verts = np.array(tokens[pos:pos + nv * 3], np.float64).reshape(nv, 3)
    pos += nv * 3
    faces = []
    for _ in range(nf):
        cnt = int(tokens[pos])
        idx = [int(t) for t in tokens[pos + 1:pos + 1 + cnt]]
        pos += 1 + cnt
        for i in range(1, cnt - 1):
            faces.append((idx[0], idx[i], idx[i + 1]))
    return [(name, verts, np.array(faces, np.int64), None)]


_3MF_UNITS = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8, "meter": 1000.0}


def _3mf(path):
    with zipfile.ZipFile(path) as z:
        name = next((n for n in z.namelist() if n.lower().endswith(".model") and "3d/" in n.lower()), None)
        if name is None:
            raise ValueError("No 3D model inside this 3MF.")
        root = ET.fromstring(z.read(name))
    ns = {"m": root.tag[1:root.tag.index("}")]} if root.tag.startswith("{") else {"m": ""}
    q = (lambda t: f"m:{t}") if ns["m"] else (lambda t: t)
    scale = _3MF_UNITS.get(root.get("unit", "millimeter"), 1.0)
    colors = {}
    for bm in root.iter(f"{{{ns['m']}}}basematerials" if ns["m"] else "basematerials"):
        cols = []
        for b in bm:
            c = b.get("displaycolor", "#B0B0B0").lstrip("#")
            cols.append([int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)])
        colors[bm.get("id")] = cols
    objects = {}
    for obj in root.find(q("resources"), ns).findall(q("object"), ns):
        mesh = obj.find(q("mesh"), ns)
        col = None
        if obj.get("pid") in colors:
            col = colors[obj.get("pid")][int(obj.get("pindex", 0))]
        if mesh is not None:
            v = np.array([[float(e.get("x")), float(e.get("y")), float(e.get("z"))]
                          for e in mesh.find(q("vertices"), ns)], np.float64)
            t = np.array([[int(e.get("v1")), int(e.get("v2")), int(e.get("v3"))]
                          for e in mesh.find(q("triangles"), ns)], np.int64)
            objects[obj.get("id")] = ("mesh", obj.get("name") or f"Object {obj.get('id')}", v, t, col)
        else:
            comps = obj.find(q("components"), ns)
            refs = [(c.get("objectid"), _3mf_matrix(c.get("transform"))) for c in comps] if comps is not None else []
            objects[obj.get("id")] = ("comp", obj.get("name") or f"Object {obj.get('id')}", refs, None, col)

    def expand(oid, mat, depth=0):
        kind, nm, a, b, col = objects[oid]
        if kind == "mesh":
            return [(nm, (np.c_[a, np.ones(len(a))] @ mat.T)[:, :3], b, col)]
        out = []
        if depth < 16:
            for ref, m2 in a:
                out += expand(ref, mat @ m2, depth + 1)
        return out

    out = []
    build = root.find(q("build"), ns)
    items = build.findall(q("item"), ns) if build is not None else []
    for it in items or [type("I", (), {"get": lambda s, k, d=None: {"objectid": k2}.get(k, d)})() for k2 in objects]:
        oid = it.get("objectid")
        if oid in objects:
            out += expand(oid, _3mf_matrix(it.get("transform")))
    out = [(n, p * scale, t, c) for n, p, t, c in out]
    if not out:
        raise ValueError("No meshes in this 3MF.")
    return out, "mm"


def _3mf_matrix(s):
    m = np.eye(4)
    if s:
        v = [float(x) for x in s.split()]
        if len(v) == 12:
            m[:3, :3] = np.array(v[:9]).reshape(3, 3).T
            m[:3, 3] = v[9:12]
    return m


def _gltf(data, path):
    if data[:4] == b"glTF":
        off, doc, binchunk = 12, None, b""
        while off + 8 <= len(data):
            ln, typ = struct.unpack_from("<II", data, off)
            chunk = data[off + 8:off + 8 + ln]
            if typ == 0x4E4F534A:
                doc = json.loads(chunk)
            elif typ == 0x004E4942:
                binchunk = chunk
            off += 8 + ln
    else:
        doc, binchunk = json.loads(data), b""
    buffers = []
    for b in doc.get("buffers", []):
        uri = b.get("uri")
        if uri is None:
            buffers.append(binchunk)
        elif uri.startswith("data:"):
            import base64
            buffers.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            buffers.append((path.parent / uri).read_bytes())
    comp = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}
    ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

    def accessor(i):
        a = doc["accessors"][i]
        bv = doc["bufferViews"][a["bufferView"]]
        dt = np.dtype("<" + comp[a["componentType"]])
        n, k = a["count"], ncomp[a["type"]]
        start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride", 0)
        buf = buffers[bv["buffer"]]
        if stride and stride != dt.itemsize * k:
            rows = [np.frombuffer(buf, dt, k, start + r * stride) for r in range(n)]
            return np.array(rows)
        return np.frombuffer(buf, dt, n * k, start).reshape(n, k) if k > 1 else np.frombuffer(buf, dt, n, start)

    def node_matrix(nd):
        if "matrix" in nd:
            return np.array(nd["matrix"], np.float64).reshape(4, 4).T
        m = np.eye(4)
        if "scale" in nd:
            m = np.diag([*nd["scale"], 1.0]) @ m
        if "rotation" in nd:
            x, y, z, w = nd["rotation"]
            r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            rm = np.eye(4)
            rm[:3, :3] = r
            m = rm @ m
        if "translation" in nd:
            t = np.eye(4)
            t[:3, 3] = nd["translation"]
            m = t @ m
        return m

    out = []

    def visit(ni, parent):
        nd = doc["nodes"][ni]
        mat = parent @ node_matrix(nd)
        if "mesh" in nd:
            mesh = doc["meshes"][nd["mesh"]]
            for k, prim in enumerate(mesh["primitives"]):
                if prim.get("mode", 4) != 4 or "POSITION" not in prim["attributes"]:
                    continue
                p = accessor(prim["attributes"]["POSITION"]).astype(np.float64)
                p = (np.c_[p, np.ones(len(p))] @ mat.T)[:, :3] * 1000.0  # glTF is in metres
                t = accessor(prim["indices"]).astype(np.int64).reshape(-1, 3) if "indices" in prim else \
                    np.arange(len(p)).reshape(-1, 3)
                col = None
                if "material" in prim:
                    f = doc["materials"][prim["material"]].get("pbrMetallicRoughness", {}).get("baseColorFactor")
                    col = [float(c) for c in f[:3]] if f else None
                nm = nd.get("name") or mesh.get("name") or f"Mesh {nd['mesh'] + 1}"
                out.append((nm if len(mesh["primitives"]) == 1 else f"{nm} ({k + 1})", p, t, col))
        for c in nd.get("children", []):
            visit(c, mat)

    scene = doc.get("scenes", [{}])[doc.get("scene", 0)] if doc.get("scenes") else {"nodes": list(range(len(doc.get("nodes", []))))}
    for ni in scene.get("nodes", []):
        visit(ni, np.eye(4))
    if not out:
        raise ValueError("No triangle meshes in this glTF.")
    return out


# ---------------------------------------------------------------------------------------------- mesh → model
def load(path, name, fmt, progress=lambda *a: None):
    progress("Reading " + fmt, 0.1)
    objects, units = read(path)
    m = MeshModel(name, path, fmt)
    if units != "mm":
        m.info["Units"] = "metres in the file, shown in mm" if units == "m→mm" else units
    else:
        m.info["Units"] = "none in the file (taken as mm)" if fmt in ("STL", "OBJ", "PLY", "OFF") else "mm"
    progress("Finding faces and edges", 0.4)
    pos, nrm, idx, segs, corners = [], [], [], [], []
    vcount = tcount = scount = 0
    for oi, (oname, pts, tris, color) in enumerate(objects):
        tris = tris[(tris >= 0).all(axis=1) & (tris < len(pts)).all(axis=1)]
        if not len(tris):
            continue
        face0 = len(m.face_type)
        regions, welded, wpts, sharp_pairs, closed = _segment(pts, tris)
        for rid in range(regions.max() + 1):
            sel = np.nonzero(regions == rid)[0]
            rt = welded[sel]
            used, inv = np.unique(rt, return_inverse=True)
            p = wpts[used]
            t = inv.reshape(-1, 3)
            n = vertex_normals(p, t)
            typ, params = _classify(p, t)
            m.face_type.append(typ)
            m.face_params.append(params)
            m.face_color.append(None)
            m.face_body.append(len(m.bodies))
            m.face_vstart.append(vcount)
            m.face_vcount.append(len(p))
            m.face_tstart.append(tcount)
            m.face_tcount.append(len(t))
            pos.append(p)
            nrm.append(n)
            idx.append(t + vcount)
            vcount += len(p)
            tcount += len(t)
        # edges: creases and open boundaries, one edge per pair of faces they separate
        for (ra, rb), es in sharp_pairs.items():
            for chain in _chains(es):
                s = wpts[np.stack([chain[:-1], chain[1:]], axis=1)]
                length = float(np.linalg.norm(s[:, 1] - s[:, 0], axis=1).sum())
                typ, params = _edge_classify(wpts[chain])
                m.edge_type.append(typ)
                m.edge_params.append(params)
                m.edge_length.append(length)
                m.edge_faces.append([face0 + ra] + ([face0 + rb] if rb >= 0 else []))
                m.edge_seam.append(False)
                m.edge_sstart.append(scount)
                m.edge_scount.append(len(s))
                segs.append(s)
                scount += len(s)
                corners += [chain[0], chain[-1]] if chain[0] != chain[-1] else []
        m.bodies.append({"name": oname, "path": [], "kind": "mesh", "color": color,
                         "faces": [face0, len(m.face_type) - face0], "closed": bool(closed)})
        if corners:
            uniq, cnt = np.unique(np.array(corners), return_counts=True)
            m.vertices = np.concatenate([m.vertices, wpts[uniq[cnt >= 2]]])
        corners = []
    if not pos:
        raise ValueError("No triangles in this file.")
    m.positions = np.concatenate(pos).astype(np.float32)
    m.normals = np.concatenate(nrm).astype(np.float32)
    m.indices = np.concatenate(idx).astype(np.uint32)
    m.segments = np.concatenate(segs).astype(np.float32) if segs else m.segments
    return m


def from_faces(path, name, fmt, pieces, slack=0.0):
    """A model from meshes that come with their own faces (a 3D PDF): pieces are (name, points (n, 3) in mm,
    triangles (m, 3), face per triangle, corner normals (m, 3, 3) or None, planar flag per face or None, colour or None,
    source or None). `slack` is how far, in mm, the file's rounding may have moved a point: fits must allow for it.
    Instances of one part say so with the same source, (its id, its 4 x 4 matrix to mm), so it's only worked out once:
    an assembly may hold thousands of the same screw."""
    m = MeshModel(name, path, fmt)
    pos, nrm, idx, segs = [], [], [], []
    vcount = tcount = scount = 0
    known = {}  # a part's id: what's worked out for its first instance
    for pname, pts, tris, faces, normals, planar, color, source in pieces:
        face0 = len(m.face_type)
        # how a part's later instance relates to its first: only a rigid move lets the findings carry over
        work = move = None
        if source and source[0] in known:
            move = _rigid_between(known[source[0]][1], source[1])
            if move is not None:
                work = known[source[0]][0]
        if work is None:
            work = _work_out_faces(pts, tris, faces, planar, slack)
            if source and source[0] not in known:
                known[source[0]] = (work, source[1])
        for sel, used, t, typ, params in work["faces"]:
            p = pts[used]
            if normals is None:
                n = vertex_normals(p, t)
            else:  # what's stored, averaged where a vertex has several in the one face
                n = np.zeros_like(p)
                np.add.at(n, t.reshape(-1), normals[sel].reshape(-1, 3))
                n = unit_rows(n)
            if typ == "planar":  # the file says so; its normal is the stored one
                typ, params = "plane", {"origin": p.mean(axis=0), "normal": unit(n.mean(axis=0))}
            elif move is not None:
                params = _moved(params, move)
            m.face_type.append(typ)
            m.face_params.append(params)
            m.face_color.append(None)
            m.face_body.append(len(m.bodies))
            m.face_vstart.append(vcount)
            m.face_vcount.append(len(p))
            m.face_tstart.append(tcount)
            m.face_tcount.append(len(t))
            pos.append(p)
            nrm.append(n)
            idx.append(t + vcount)
            vcount += len(p)
            tcount += len(t)
        for ra, rb, chain, typ, params in work["edges"]:
            s = pts[np.stack([chain[:-1], chain[1:]], axis=1)]
            m.edge_type.append(typ)
            m.edge_params.append(_moved(params, move) if move is not None else params)
            m.edge_length.append(float(np.linalg.norm(s[:, 1] - s[:, 0], axis=1).sum()))
            m.edge_faces.append([face0 + ra] + ([face0 + rb] if rb >= 0 else []))
            m.edge_seam.append(False)
            m.edge_sstart.append(scount)
            m.edge_scount.append(len(s))
            segs.append(s)
            scount += len(s)
        m.bodies.append({"name": pname, "path": [], "kind": "mesh", "color": color,
                         "faces": [face0, len(work["faces"])], "closed": work["closed"]})
        if len(work["corners"]):
            m.vertices = np.concatenate([m.vertices, pts[work["corners"]]])
    if not pos:
        raise ValueError("No triangles in this file.")
    m.positions = np.concatenate(pos).astype(np.float32)
    m.normals = np.concatenate(nrm).astype(np.float32)
    m.indices = np.concatenate(idx).astype(np.uint32)
    m.segments = np.concatenate(segs).astype(np.float32) if segs else m.segments
    return m


def _work_out_faces(pts, tris, faces, planar, slack):
    """Which triangles make each face and what it is, and where the edges run: all independent of where the part sits."""
    order = np.argsort(faces, kind="stable")
    ids, starts = np.unique(faces[order], return_index=True)
    out = {"faces": [], "edges": [], "corners": np.zeros(0, np.int64), "closed": True}
    for fi, (fid, first) in enumerate(zip(ids, starts)):
        last = starts[fi + 1] if fi + 1 < len(starts) else len(order)
        sel = order[first:last]
        used, inv = np.unique(tris[sel], return_inverse=True)
        t = inv.reshape(-1, 3)
        if planar is not None and planar[int(fid)]:
            typ, params = "planar", None
        else:
            typ, params = _classify(pts[used], t, slack)
        out["faces"].append((sel, used, t, typ, params))
    region = np.searchsorted(ids, faces)
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    of = np.tile(np.arange(len(tris)), 3)
    k = np.sort(e, axis=1)
    keep = k[:, 0] != k[:, 1]
    k, of = k[keep], of[keep]
    by_edge = {}
    for key, tri in zip(map(tuple, k.tolist()), of.tolist()):
        by_edge.setdefault(key, []).append(int(region[tri]))
    pairs = {}
    for key, regs in by_edge.items():
        here = sorted(set(regs))
        if len(here) == 1 and len(regs) == 1:
            pairs.setdefault((here[0], -1), []).append(key)
        elif len(here) > 1:
            pairs.setdefault((here[0], here[1]), []).append(key)
    ends = []
    for (ra, rb), es in pairs.items():
        out["closed"] = out["closed"] and rb >= 0
        for chain in _chains(es):
            typ, params = _edge_classify(pts[chain], slack)
            out["edges"].append((ra, rb, chain, typ, params))
            if chain[0] != chain[-1]:
                ends += [chain[0], chain[-1]]
    if ends:
        uniq, cnt = np.unique(np.array(ends), return_counts=True)
        out["corners"] = uniq[cnt >= 2]
    return out


def _rigid_between(first, second):
    """The move from one placement to another, if it's only a turn and a slide (no mirror or scale); else None."""
    try:
        move = np.asarray(second) @ np.linalg.inv(np.asarray(first))
    except np.linalg.LinAlgError:
        return None
    r = move[:3, :3]
    if not np.allclose(r @ r.T, np.eye(3), atol=1e-6) or np.linalg.det(r) < 0:
        return None
    return move


_PARAM_POINTS = ("origin", "center", "start", "end")
_PARAM_VECTORS = ("normal", "axis", "dir")


def _moved(params, move):
    """A fitted plane, cylinder, line or circle after a rigid move."""
    if params is None:
        return None
    out = dict(params)
    for key in _PARAM_POINTS:
        if key in out:
            out[key] = move[:3, :3] @ np.asarray(out[key]) + move[:3, 3]
    for key in _PARAM_VECTORS:
        if key in out:
            out[key] = move[:3, :3] @ np.asarray(out[key])
    return out


def _thin_triangles(a, b, c, slack):
    """Which triangles are so thin that rounding their points by `slack` could swing their normal any way at all. Where
    that's most of a mesh it says more about the rounding than the triangles: then none are singled out."""
    if slack <= 0:
        return np.zeros(len(a), bool)
    twice_area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    longest = np.max([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)], axis=0)
    thin = twice_area < 2 * slack * longest
    return thin if thin.mean() < 0.5 else np.zeros(len(a), bool)


def _trusted_normals(normals, thin, t1, t2):
    """Normals to judge creases by. A thin triangle's own may be tipped by rounding, but it still says which side the
    triangle is nearer: it takes the normal of the neighbour closest to it, so it never spans a crease itself. Only thin
    neighbours yet: it waits for them. A patch of nothing but thin triangles has to go by its own."""
    out = normals.copy()
    across = {}
    for x, y in zip(t1.tolist(), t2.tolist()):
        if thin[x]:
            across.setdefault(x, []).append(y)
        if thin[y]:
            across.setdefault(y, []).append(x)
    waiting = np.nonzero(thin)[0].tolist()
    settled = ~thin
    while waiting:
        reached = {}
        for t in waiting:
            sides = [other for other in across.get(t, ()) if settled[other]]
            if sides:
                reached[t] = out[max(sides, key=lambda other: float(normals[t] @ out[other]))]
        if not reached:
            reached[waiting[0]] = out[waiting[0]]
        for t, normal in reached.items():
            out[t] = normal
            settled[t] = True
        waiting = [t for t in waiting if t not in reached]
    return out


def _segment(pts, tris, slack=0.0):
    """Split triangles into smooth regions. Returns (region per triangle, welded triangles,
    welded points, {(region a, region b or -1): [edges as welded point pairs]}, closed?).
    `slack` is how far the file's rounding may have moved a point: a triangle too thin to trust doesn't make a crease."""
    scale = float(np.ptp(pts, axis=0).max()) or 1.0
    key = np.round(pts / (scale * 1e-7)).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    wpts = pts[first]
    welded = inv.reshape(-1)[tris]
    ok = (welded[:, 0] != welded[:, 1]) & (welded[:, 1] != welded[:, 2]) & (welded[:, 0] != welded[:, 2])
    welded = welded[ok]
    a, b, c = wpts[welded[:, 0]], wpts[welded[:, 1]], wpts[welded[:, 2]]
    fn = unit_rows(np.cross(b - a, c - a))
    nt = len(welded)
    e = np.concatenate([welded[:, [0, 1]], welded[:, [1, 2]], welded[:, [2, 0]]])
    tri_of = np.tile(np.arange(nt), 3)
    k = np.sort(e, axis=1)
    order = np.lexsort((k[:, 1], k[:, 0]))
    k, tri_of = k[order], tri_of[order]
    same = np.all(k[1:] == k[:-1], axis=1)
    pair_i = np.nonzero(same)[0]
    # an edge shared by exactly two triangles: smooth if their normals are close
    multi = np.zeros(len(k), bool)
    multi[pair_i] = True
    multi[pair_i + 1] = True
    t1, t2 = tri_of[pair_i], tri_of[pair_i + 1]
    thin = _thin_triangles(a, b, c, slack)
    if thin.any():
        fn = _trusted_normals(fn, thin, t1, t2)
    smooth = np.einsum("ij,ij->i", fn[t1], fn[t2]) > math.cos(math.radians(CREASE_DEG))
    parent = np.arange(nt)
    u, v = t1[smooth], t2[smooth]
    for _ in range(64):  # union-find, a whole layer at a time
        ru, rv = parent[u], parent[v]
        lo, hi = np.minimum(ru, rv), np.maximum(ru, rv)
        changed = lo != hi
        if not changed.any():
            break
        np.minimum.at(parent, hi[changed], lo[changed])
        for _ in range(32):
            nxt = parent[parent]
            if np.array_equal(nxt, parent):
                break
            parent = nxt
    while True:
        nxt = parent[parent]
        if np.array_equal(nxt, parent):
            break
        parent = nxt
    _, regions = np.unique(parent, return_inverse=True)
    sharp_pairs = {}
    hard = pair_i[~smooth]
    for i in hard:
        ra, rb = int(regions[tri_of[i]]), int(regions[tri_of[i + 1]])
        if ra != rb:
            sharp_pairs.setdefault((min(ra, rb), max(ra, rb)), []).append(tuple(k[i]))
    single = ~multi
    for i in np.nonzero(single)[0]:
        sharp_pairs.setdefault((int(regions[tri_of[i]]), -1), []).append(tuple(k[i]))
    closed = not single.any()
    return regions, welded, wpts, sharp_pairs, closed


def _chains(edges):
    """Link edge segments (point pairs) into polylines (lists of point ids)."""
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    seen = set()
    out = []
    starts = [p for p, n in adj.items() if len(n) != 2] + list(adj)
    for s in starts:
        for nb in adj[s]:
            if (s, nb) in seen:
                continue
            chain = [s, nb]
            seen.add((s, nb))
            seen.add((nb, s))
            while len(adj[chain[-1]]) == 2:
                p, q = chain[-2], chain[-1]
                nx = adj[q][0] if adj[q][0] != p else adj[q][1]
                if (q, nx) in seen:
                    break
                seen.add((q, nx))
                seen.add((nx, q))
                chain.append(nx)
            out.append(np.array(chain, np.int64))
    return out


def _classify(p, t, slack=0.0):
    """Is this region flat? Report it as a plane (with its normal) if so. Points may be `slack` off true."""
    if len(p) < 3:
        return "mesh", None
    c = p.mean(axis=0)
    _, s, vt = np.linalg.svd(p - c, full_matrices=False)
    n = vt[2]
    dev = np.abs((p - c) @ n).max()
    size = float(np.linalg.norm(np.ptp(p, axis=0))) or 1.0
    if dev <= max(1e-4 * size, 1e-6, slack):
        a, b, cc = p[t[:, 0]], p[t[:, 1]], p[t[:, 2]]
        if float(np.cross(b - a, cc - a).sum(axis=0) @ n) < 0:
            n = -n
        return "plane", {"origin": c, "normal": unit(n)}
    cyl = _fit_cylinder(p, size, slack)
    if cyl is not None:
        return "cylinder", cyl
    return "mesh", None


def _fit_cylinder(p, size, slack=0.0):
    """A cylinder through the points, if they make one: axis from the point spread's least-curved
    direction, circle fit across it."""
    if len(p) < 8:
        return None
    c = p.mean(axis=0)
    _, _, vt = np.linalg.svd(p - c, full_matrices=False)
    for axis in vt:
        x = unit(np.cross(axis, [1, 0, 0]) if abs(axis[0]) < 0.9 else np.cross(axis, [0, 1, 0]))
        y = np.cross(axis, x)
        q = np.stack([(p - c) @ x, (p - c) @ y], axis=1)
        fit = _fit_circle_2d(q)
        if fit is None:
            continue
        (cx, cy), r, err = fit
        if r > 0 and err < max(2e-3 * r, 1e-5 * size, slack) and r < size * 10:
            centre = c + cx * x + cy * y
            return {"center": centre, "axis": unit(axis), "radius": float(r)}
    return None


def _fit_circle_2d(q):
    a = np.c_[2 * q, np.ones(len(q))]
    rhs = (q ** 2).sum(axis=1)
    try:
        sol, *_ = np.linalg.lstsq(a, rhs, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy, k = sol
    r2 = k + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    err = float(np.abs(np.linalg.norm(q - [cx, cy], axis=1) - r).max())
    return (cx, cy), r, err


def _edge_classify(pts, slack=0.0):
    """A crease polyline: a straight line, a circle / arc (fitted), or just a polyline."""
    a, b = pts[0], pts[-1]
    size = float(np.linalg.norm(np.ptp(pts, axis=0))) or 1.0
    closed = len(pts) > 3 and float(np.linalg.norm(a - b)) < 1e-9 * size
    d = b - a
    if not closed and float(np.linalg.norm(d)) > 0:
        off = np.linalg.norm(np.cross(pts - a, unit(d)), axis=1).max()
        if off < max(1e-5 * size, slack):
            return "line", {"start": a, "end": b, "dir": unit(d)}
    if len(pts) >= 6:
        c = pts.mean(axis=0)
        _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
        n = vt[2]
        if np.abs((pts - c) @ n).max() < max(2e-3 * size, slack):
            x = vt[0]
            y = np.cross(n, x)
            fit = _fit_circle_2d(np.stack([(pts - c) @ x, (pts - c) @ y], axis=1))
            if fit is not None:
                (cx, cy), r, err = fit
                if err < max(2e-3 * r, 1e-6 * size, slack):
                    centre = c + cx * x + cy * y
                    seg = np.linalg.norm(pts[1:] - pts[:-1], axis=1).sum()
                    ang = 360.0 if closed else math.degrees(seg / r)
                    return "circle", {"center": centre, "radius": float(r), "normal": unit(n), "closed": closed,
                                      "angle": ang, "start": a, "end": b}
    return "polyline", {"start": a, "end": b, "closed": closed}
