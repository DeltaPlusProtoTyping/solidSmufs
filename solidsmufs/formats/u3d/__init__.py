"""Reading 3D models in U3D (ECMA-363), the older format of 3D PDFs. The reader is our own, written from the standard,
and from Intel's U3D sample software (Apache-2.0) where the standard leaves a rule out or has it backwards: how a new
face's third point is listed and how a face's stay-or-move is predicted. None of that software's code is included.

A U3D file is a run of blocks, some inside "modifier chains": nodes that place things, mesh resources they refer to,
then shaders and materials. A mesh is "progressive": it may hold a base mesh, then resolution updates that each split
a point in two, moving some of the triangles around it onto the new point and adding others. Every update has to be
followed in order, since each is written in terms of the mesh as it stood.
"""

import struct

import numpy as np

from ..pdfstreams import model_streams
from ..prc import Piece, Placed
from . import freeform, rhadobe
from .stream import Stream, U3dError

__all__ = ["U3dError", "U3d", "read_u3d", "read_pdf", "streams_in_pdf"]

CHAIN = 0xFFFFFF14
GROUP_NODE, MODEL_NODE = 0xFFFFFF21, 0xFFFFFF22
MESH_DECLARATION, POINT_SET, LINE_SET = 0xFFFFFF31, 0xFFFFFF36, 0xFFFFFF37
BASE_MESH, PROGRESSIVE_MESH = 0xFFFFFF3B, 0xFFFFFF3C
SHADING_MODIFIER, SHADER, MATERIAL = 0xFFFFFF45, 0xFFFFFF53, 0xFFFFFF54
NEW_OBJECT_TYPE = 0xFFFFFF16
FIRST_NEW_OBJECT, LAST_NEW_OBJECT = 0x00000100, 0x00FFFFFF

PROFILE_NO_COMPRESSION, PROFILE_UNITS = 4, 8
EXCLUDE_NORMALS = 1
MOVE = 1
LEFT = 1  # a new face's winding: split, new, third; otherwise new, split, third
LOCAL_THIRD = 1
CHANGE, NEW_INDEX, LOCAL_INDEX = 1, 1, 2  # a moved corner's "keep or change", then the kind of index that follows
# the contexts of a stay-or-move flag, by what's predicted for the face
NO_PREDICTION, MOVE_BY_THIRD, STAY_BY_THIRD, MOVE_BY_NEIGHBOUR, STAY_BY_NEIGHBOUR = range(5)


class Mesh:
    """A mesh resource as it's being rebuilt."""

    def __init__(self, name):
        self.name = name
        self.exclude_normals = False
        self.shadings = []  # (uses diffuse colors, uses specular colors, texture layers)
        self.position_quant = 1.0
        self.points = []  # (x, y, z)
        self.faces = []  # [a, b, c]
        self.shading = []  # shading of each face
        self.at = []  # the faces at each point
        self.declared = (0, 0)  # the faces and points it says it reaches
        self.updates = 0
        self.leftover = 0
        self.damaged = False


class Node:
    def __init__(self, name, parents, resource=None, visible=True):
        self.name, self.parents, self.resource, self.visible = name, parents, resource, visible


class U3d:
    def __init__(self):
        self.pieces = []
        self.placed = []
        self.unit_mm = 1.0
        self.has_units = False
        self.name = ""
        self.warnings = []
        self.notices = []  # what has to be seen right away, not just noted
        self.thin_limit = 0.0  # triangles lower than this, in file units, can't be trusted to face the way they seem to
        self.meshes = {}
        self.forms = {}  # free-form objects, by name
        self.form_blocks = {}  # the block types the file gave them: type: "declaration" or "continuation"
        self.vendor_kinds = {}  # other block types the file declares: type: the object's name
        self.nodes = {}
        self.resource_shaders = {}
        self.shaders = {}  # name: material name
        self.materials = {}  # name: (r, g, b) diffuse
        self.skipped = {}  # what's in the file that isn't triangles, by kind: how many
        self.damaged = 0  # meshes that could only be read part of the way
        self.adobe = 0  # meshes in Adobe's own format (rhadobe.py)


# ---------------------------------------------------------------------------------------------- in the PDF
def streams_in_pdf(data, password=""):
    """The U3D streams in a PDF's bytes, in file order."""
    return model_streams(data, b"U3D", b"U3D\0", password)


def read_pdf(path, password=""):
    with open(path, "rb") as f:
        data = f.read()
    return [read_u3d(s) for s in streams_in_pdf(data, password)]


# ---------------------------------------------------------------------------------------------- the blocks
def _blocks(data, start, end):
    """(type, where its data starts, its size), keeping to the 4-byte steps the file is laid out in."""
    i = start
    while i + 12 <= end:
        kind, size, meta = struct.unpack_from("<III", data, i)
        body = i + 12
        if body + size > end:
            raise U3dError("The U3D data is cut short.")
        yield kind, body, size
        i = (body + size + 3) & ~3
        i = (i + meta + 3) & ~3


def read_u3d(data):
    if data[:4] != b"U3D\0":
        raise U3dError("This isn't U3D data.")
    out = U3d()
    profile = struct.unpack_from("<I", data, 16)[0]
    plain = bool(profile & PROFILE_NO_COMPRESSION)
    if profile & PROFILE_UNITS:
        out.unit_mm = struct.unpack_from("<d", data, 36)[0] * 1000.0
        out.has_units = True
    _read_blocks(out, data, _after_header(data), len(data), plain)
    _build(out)
    return out


def _after_header(data):
    _kind, size, meta = struct.unpack_from("<III", data, 0)
    i = (12 + size + 3) & ~3
    return (i + meta + 3) & ~3


def _read_blocks(out, data, start, end, plain):
    for kind, body, size in _blocks(data, start, end):
        if kind == CHAIN:
            _read_chain(out, data, body, body + size, plain)
        else:
            _read_block(out, kind, data[body:body + size], plain)


def _read_chain(out, data, start, end, plain):
    size = struct.unpack_from("<H", data, start)[0]
    i = start + 2 + size + 4
    attributes = struct.unpack_from("<I", data, i)[0]
    i += 4
    if attributes & 1:
        i += 16
    if attributes & 2:
        i += 24
    i = (i + 3) & ~3
    i += 4  # how many there are: the chain's size says it too
    _read_blocks(out, data, i, end, plain)


def _read_block(out, kind, body, plain):
    if kind == GROUP_NODE or kind == MODEL_NODE:
        s = Stream(body, plain)
        name = s.string()
        parents = []
        for _ in range(s.u32()):
            parent = s.string()
            parents.append((parent, s.floats(16).reshape(4, 4).T))
        if kind == GROUP_NODE:
            out.nodes[name] = Node(name, parents)
        else:
            resource = s.string()
            out.nodes[name] = Node(name, parents, resource, s.u32() != 0)
    elif kind == SHADING_MODIFIER:
        s = Stream(body, plain)
        name = s.string()
        s.u32()  # its place in the chain
        attributes = s.u32()
        lists = [[s.string() for _ in range(s.u32())] for _ in range(s.u32())]
        if attributes & 1:  # for meshes, not lines or points
            out.resource_shaders[name] = lists
    elif kind == SHADER:
        s = Stream(body, plain)
        name = s.string()
        s.u32(), s.f32(), s.u32(), s.u32(), s.u32(), s.u32(), s.u32()
        out.shaders[name] = s.string()
    elif kind == MATERIAL:
        s = Stream(body, plain)
        name = s.string()
        attributes = s.u32()
        s.floats(3)
        diffuse = s.floats(3)
        if attributes & 2:
            out.materials[name] = tuple(float(c) for c in np.clip(diffuse, 0.0, 1.0))
    elif kind == MESH_DECLARATION:
        mesh = _read_declaration(Stream(body, plain))
        out.meshes[mesh.name] = mesh
    elif kind == BASE_MESH:
        _continue(out, _read_base, Stream(body, plain))
    elif kind == PROGRESSIVE_MESH:
        _continue(out, _read_progressive, Stream(body, plain))
    elif kind == POINT_SET:
        out.skipped["point sets"] = out.skipped.get("point sets", 0) + 1
    elif kind == LINE_SET:
        out.skipped["line sets"] = out.skipped.get("line sets", 0) + 1
    elif kind == NEW_OBJECT_TYPE:
        _read_object_type(out, Stream(body, plain))
    elif out.form_blocks.get(kind) == "declaration":
        form = freeform.read_declaration(Stream(body, plain))
        out.forms[form.name] = form
    elif out.form_blocks.get(kind) == "adobe":
        _read_adobe(out, body)
    elif out.form_blocks.get(kind) == "continuation":
        try:
            freeform.read_continuation(out.forms, Stream(body, plain))
        except IndexError:
            raise U3dError("The U3D data is damaged: a free-form block ends too soon.") from None
    elif FIRST_NEW_OBJECT <= kind <= LAST_NEW_OBJECT:
        out.skipped["objects in a vendor's own format"] = out.skipped.get("objects in a vendor's own format", 0) + 1


def _read_adobe(out, body):
    """A mesh in Adobe's own format: whole in one block, with no levels of detail. A damaged one is noted and skipped."""
    try:
        name, points, triangles, ids, materials = rhadobe.decode(body)
    except U3dError as e:
        out.warnings.append(str(e))
        kind = "meshes in Adobe's own format that couldn't be read"
        out.skipped[kind] = out.skipped.get(kind, 0) + 1
        return
    mesh = Mesh(name)
    mesh.shadings = materials or [(False, False, 0)]
    mesh.points, mesh.faces = points, triangles
    mesh.shading = ids if len(ids) == len(triangles) else np.zeros(len(triangles), np.int64)
    mesh.declared = (len(triangles), len(points))
    out.meshes[name] = mesh
    out.adobe += 1


def _read_object_type(out, s):
    """A new kind of block the file brings in. The standard's own free-form surfaces come in this way, and vendors' formats."""
    name = s.string()
    s.u32()  # the kind of modifier it is
    guid = (s.u32(), s.u16(), s.u16(), bytes(s.u8() for _ in range(8)))
    declaration = s.u32()
    continuations = [s.u32() for _ in range(s.u32())]
    if (guid == rhadobe.GUID or name == rhadobe.NAME) and rhadobe.available():
        for kind in (declaration, *continuations):
            out.form_blocks[kind] = "adobe"
    elif guid == freeform.GUID or name == "Free-Form Object":
        out.form_blocks[declaration] = "declaration"
        for kind in continuations:
            out.form_blocks[kind] = "continuation"
    else:
        for kind in (declaration, *continuations):
            out.vendor_kinds[kind] = name


def _continue(out, read, s):
    """A mesh's data. Each update is complete before it's applied, so a damaged block leaves the mesh coarser, not wrong."""
    mesh = _mesh_of(out, s)
    try:
        read(mesh, s)
    except (U3dError, IndexError):
        if not mesh.damaged:
            mesh.damaged = True
            out.damaged += 1


def _read_declaration(s):
    mesh = Mesh(s.string())
    s.u32()  # its place in the chain
    mesh.exclude_normals = bool(s.u32() & EXCLUDE_NORMALS)
    mesh.declared = (s.u32(), s.u32())
    s.u32(), s.u32(), s.u32(), s.u32()  # how many normals, colors and texture coordinates
    for _ in range(s.u32()):
        attributes = s.u32()
        layers = s.u32()
        for _ in range(layers):
            s.u32()
        s.u32()
        mesh.shadings.append((bool(attributes & 1), bool(attributes & 2), layers))
    s.u32(), s.u32()  # the resolutions it runs between
    s.u32(), s.u32(), s.u32()  # quality factors
    mesh.position_quant = s.f32()
    return mesh


def _mesh_of(out, s):
    name = s.string()
    s.u32()  # its place in the chain
    mesh = out.meshes.get(name)
    if mesh is None:
        raise U3dError(f"The U3D data continues a mesh it hasn't declared ({name}).")
    return mesh


def _shading_of(mesh, shading):
    if shading >= len(mesh.shadings):
        raise U3dError("The U3D data is damaged: a face uses a shading the mesh doesn't have.")
    return mesh.shadings[shading]


def _read_base(mesh, s):
    face_count, points, normals, diffuse, specular, texture = (s.u32() for _ in range(6))
    mesh.points = [tuple(p) for p in s.floats(points * 3).reshape(-1, 3).tolist()]
    mesh.at = [[] for _ in range(points)]
    s.floats(normals * 3), s.floats(diffuse * 4), s.floats(specular * 4), s.floats(texture * 4)
    faces, shadings = mesh.faces, mesh.shading
    with_normals = not mesh.exclude_normals
    for f in range(face_count):
        shading = s.cu32("cShading")
        uses_diffuse, uses_specular, layers = _shading_of(mesh, shading)
        corner = []
        for _ in range(3):
            p = s.ranged(points)
            if p >= points:
                raise U3dError("The U3D data is damaged: a face uses a point that isn't there.")
            corner.append(p)
            if with_normals:
                s.ranged(normals)
            if uses_diffuse:
                s.ranged(diffuse)
            if uses_specular:
                s.ranged(specular)
            for _ in range(layers):
                s.ranged(texture)
        faces.append(corner)
        shadings.append(shading)
        for p in corner:
            mesh.at[p].append(f)
    mesh.leftover = max(mesh.leftover, s.left_bytes())


def _new_values(s, count_context, sign_context, contexts):
    for _ in range(s.cu16(count_context)):
        s.cu8(sign_context)
        for c in contexts:
            s.cu32(c)


def _change(s, keep_change, change_type, index_new, index_local, index_global):
    """A moved corner's color or texture coordinate: which isn't needed for the shape, but has to be read past."""
    if s.cu8(keep_change) == CHANGE:
        kind = s.cu8(change_type)
        s.cu32(index_new if kind == NEW_INDEX else index_local if kind == LOCAL_INDEX else index_global)


def _duplicates(s, flag, index_type, index_local, index_global):
    """The color or texture index at each of a new face's corners, unless it's flagged as the last one again."""
    flags = s.cu8(flag)
    for bit in (1, 2, 4):
        if not flags & bit:
            s.cu32(index_local if s.cu8(index_type) == LOCAL_INDEX else index_global)


def _predict(corners, split, left_thirds, right_thirds, moved, stayed):
    """Which way a face at the split point will likely go. A new face runs along an edge from the split point, so a
    face sharing that edge is on one side of it or the other: whether it's the side that moves shows in which way round
    it holds the edge, and in the new face's winding. A face no new face touches goes the way one sharing a corner went."""
    a, b, c = corners
    after, before = (b, c) if a == split else (c, a) if b == split else (a, b)
    if after in right_thirds:
        return MOVE_BY_THIRD
    if before in right_thirds:
        return STAY_BY_THIRD
    if after in left_thirds:
        return STAY_BY_THIRD
    if before in left_thirds:
        return MOVE_BY_THIRD
    if a in moved or b in moved or c in moved:
        return MOVE_BY_NEIGHBOUR
    if a in stayed or b in stayed or c in stayed:
        return STAY_BY_NEIGHBOUR
    return NO_PREDICTION


def _read_progressive(mesh, s):
    start, end = s.u32(), s.u32()
    points, faces, shadings, at = mesh.points, mesh.faces, mesh.shading, mesh.at
    quant = mesh.position_quant
    with_normals = not mesh.exclude_normals
    if start != len(points):
        raise U3dError("The U3D data's resolution updates aren't in order.")
    for _ in range(start, end):
        count = len(points)
        split = s.ranged(count)
        if count and split >= count:
            raise U3dError("The U3D data is damaged: an update splits a point that isn't there.")
        _new_values(s, "cDiffuseCount", "cDiffuseColorSign", ("cColorDiffR", "cColorDiffG", "cColorDiffB", "cColorDiffA"))
        _new_values(s, "cSpecularCount", "cSpecularColorSign", ("cColorDiffR", "cColorDiffG", "cColorDiffB", "cColorDiffA"))
        _new_values(s, "cTexCoordCount", "cTexCoordSign", ("cTexCDiffU", "cTexCDiffV", "cTexCDiffS", "cTexCDiffT"))
        around = sorted(at[split], reverse=True) if count else []
        near = {p for f in around for p in faces[f]}
        near.discard(split)
        added, left_thirds, right_thirds = [], set(), set()
        for _ in range(s.cu32("cFaceCnt")):
            shading = s.cu32("cShading")
            _shading_of(mesh, shading)
            left = s.cu8("cFaceOrnt") == LEFT
            if s.cu8("cThrdPosType") == LOCAL_THIRD:
                local = s.cu32("cLocal3rdPos")
                if local >= len(near):
                    raise U3dError("The U3D data is damaged: a new face uses a neighbour that isn't there.")
                third = sorted(near, reverse=True)[local]
            else:
                third = s.ranged(count)
                if third >= max(count, 1):
                    raise U3dError("The U3D data is damaged: a new face uses a point that isn't there.")
                near.add(third)  # there for the next new face to refer to
            (left_thirds if left else right_thirds).add(third)
            added.append((shading, left, third))

        moving, moved, stayed = [], set(), set()
        for f in around:
            corners = faces[f]
            if s.cu8(f"cStayMove{_predict(corners, split, left_thirds, right_thirds, moved, stayed)}") == MOVE:
                moving.append(f)
                moved.update(corners)
                moved.discard(split)
            else:
                stayed.update(corners)
                stayed.discard(split)

        for f in moving:
            uses_diffuse, uses_specular, layers = mesh.shadings[shadings[f]]
            if uses_diffuse:
                _change(s, "cDiffuseKeepChange", "cDiffuseChangeType", "cDiffuseChangeIndexNew", "cDiffuseChangeIndexLocal", "cDiffuseChangeIndexGlobal")
            if uses_specular:
                _change(s, "cSpecularKeepChange", "cSpecularChangeType", "cSpecularChangeIndexNew", "cSpecularChangeIndexLocal", "cSpecularChangeIndexGlobal")
            for _ in range(layers):
                _change(s, "cTCKeepChange", "cTCChangeType", "cTCChangeIndexNew", "cTCChangeIndexLocal", "cTCChangeIndexGlobal")

        for shading, _left, _third in added:
            uses_diffuse, uses_specular, layers = mesh.shadings[shading]
            if uses_diffuse:
                _duplicates(s, "cColorDup", "cColorIndexType", "cColorIndexLocal", "cColorIndexGlobal")
            if uses_specular:
                _duplicates(s, "cColorDup", "cColorIndexType", "cColorIndexLocal", "cColorIndexGlobal")
            for _ in range(layers):
                _duplicates(s, "cTexCDup", "cTexCIndexType", "cTextureIndexLocal", "cTextureIndexGlobal")

        signs = s.cu8("cPosDiffSign")
        dx, dy, dz = s.cu32("cPosDiffX"), s.cu32("cPosDiffY"), s.cu32("cPosDiffZ")
        x, y, z = points[split] if count else (0.0, 0.0, 0.0)
        new = count
        points.append((x + (-dx if signs & 1 else dx) * quant, y + (-dy if signs & 2 else dy) * quant,
                       z + (-dz if signs & 4 else dz) * quant))
        at.append([])
        for f in moving:
            corner = faces[f]
            corner[corner.index(split)] = new
            at[split].remove(f)
            at[new].append(f)
        for shading, left, third in added:
            f = len(faces)
            faces.append([split, new, third] if left else [new, split, third])
            shadings.append(shading)
            at[split].append(f)
            at[new].append(f)
            if third != split and third != new:
                at[third].append(f)

        if with_normals:
            around_new = sorted({p for f in at[new] for p in faces[f]}, reverse=True)
            for p in around_new:
                for _ in range(s.cu32("cNormlCnt")):
                    s.cu8("cDiffNormalSign")
                    s.cu32("cDiffNormalX"), s.cu32("cDiffNormalY"), s.cu32("cDiffNormalZ")
                for _ in at[p]:
                    s.cu32("cNormlIdx")
        mesh.updates += 1
    mesh.leftover = max(mesh.leftover, s.left_bytes())


# ---------------------------------------------------------------------------------------------- the scene
def _piece(mesh, shading=None):
    """A mesh, or the part of it with one shading, as a piece: its faces are its smooth regions, since U3D has no faces."""
    from ...kernel.meshio import _segment
    triangles = np.array(mesh.faces, np.int64).reshape(-1, 3)
    if shading is not None:
        triangles = triangles[np.array(mesh.shading) == shading]
    points = np.array(mesh.points, float).reshape(-1, 3)
    if not len(triangles) or not len(points):
        return None
    # an update's point is its split point plus rounded steps, so it can be off by about a step
    rounding = mesh.position_quant if mesh.updates else 0.0
    regions, welded, joined, _edges, _closed = _segment(points, triangles, rounding)
    if not len(welded):
        return None
    return Piece(joined, welded, regions, None, None, rounding, {})


def _form_piece(form, shading):
    from ...kernel.meshio import _segment
    points, triangles, faces = freeform.tessellate(form, shading)
    if not len(triangles):
        return None
    # each trimmed face of the file is a face here too, joined where they meet: so edges run where the model's do
    _regions, welded, joined, _edges, _closed = _segment(points, triangles)
    if len(welded) != len(triangles):
        keep = np.linalg.norm(np.cross(points[triangles[:, 1]] - points[triangles[:, 0]], points[triangles[:, 2]] - points[triangles[:, 0]]), axis=1) > 0
        return Piece(points, triangles[keep], faces[keep], None, None, 0.0, {})
    return Piece(joined, welded, faces, None, None, 0.0, {})


def _worlds(out, name, seen=()):
    """Every place a node ends up: a node may have several parents, and each of them several places."""
    node = out.nodes.get(name)
    if node is None:  # the world itself, or something the file doesn't define (which falls back to the world)
        return [np.eye(4)]
    if name in seen:
        raise U3dError("The U3D data's node tree loops.")
    places = []
    for parent, matrix in node.parents:
        places += [world @ matrix for world in _worlds(out, parent, (*seen, name))]
    return places


def _color(out, lists, shading):
    if not lists or shading >= len(lists) or not lists[shading]:
        return None
    return out.materials.get(out.shaders.get(lists[shading][0]))


def _place_form(out, node, form, cache):
    lists = out.resource_shaders.get(node.name) or out.resource_shaders.get(node.resource)
    shadings = sorted({c.shading for c in form.surfaces})
    split = shadings if len({_color(out, lists, k) for k in shadings}) > 1 else [None]
    for k in split:
        key = ("form", form.name, k)
        if key not in cache:
            cache[key] = _form_piece(form, k)
            if cache[key] is not None:
                out.pieces.append(cache[key])
        if cache[key] is None:
            continue
        color = _color(out, lists, shadings[0] if k is None and shadings else k)
        for world in _worlds(out, node.name):
            out.placed.append(Placed(cache[key], world, node.name, color))


def _build(out):
    cache = {}

    def piece_of(mesh, shading):
        key = (mesh.name, shading)
        if key not in cache:
            cache[key] = _piece(mesh, shading)
            if cache[key] is not None:
                out.pieces.append(cache[key])
        return cache[key]

    used = set()
    for node in out.nodes.values():
        form = out.forms.get(node.resource) if node.resource is not None else None
        if form is not None:
            used.add(form.name)
            if node.visible:
                _place_form(out, node, form, cache)
            continue
        mesh = out.meshes.get(node.resource) if node.resource is not None else None
        if mesh is None:
            continue
        used.add(mesh.name)
        if not node.visible:
            continue
        lists = out.resource_shaders.get(node.name) or out.resource_shaders.get(node.resource)
        shadings = sorted(set(np.asarray(mesh.shading).tolist()))
        colors = {_color(out, lists, k) for k in shadings}
        split = shadings if len(colors) > 1 else [None]  # a piece has one color
        for k in split:
            piece = piece_of(mesh, k)
            if piece is None:
                continue
            color = _color(out, lists, shadings[0] if k is None and shadings else k)
            for world in _worlds(out, node.name):
                out.placed.append(Placed(piece, world, node.name, color))
    if not used:  # meshes no node shows: better shown where they were modelled than not at all
        for mesh in out.meshes.values():
            piece = piece_of(mesh, None)
            if piece is not None:
                out.placed.append(Placed(piece, np.eye(4), mesh.name, None))
        for form in out.forms.values():
            _place_form(out, Node(form.name, [("", np.eye(4))], form.name), form, cache)

    out.thin_limit = max((2 * m.position_quant for m in out.meshes.values() if m.updates), default=0.0)
    if not out.has_units:
        out.notices.append("This U3D model doesn't say what units it's in. Each unit is taken as 1 mm, so its shape is right but "
                           "its sizes may be off by a scale: don't measure from it without checking one known size.")
    short = sum(1 for m in out.meshes.values() if not m.damaged and (len(m.faces), len(m.points)) != m.declared)
    if out.damaged or short:
        out.warnings.append(f"{out.damaged + short} of this model's meshes couldn't be read to the end, and are shown in less detail.")
    for kind, count in out.skipped.items():
        out.warnings.append(f"This U3D model also holds {count} {kind}, which aren't shown.")
