"""Reading 3D models out of PDFs that hold them in PRC (ISO 14739-1), the format of McMaster-Carr's and most CAD
tools' 3D PDFs. What's read is the display tessellation, the triangles the file was made to be shown with, or when a part
has none, its exact geometry, meshed here (brep.py, brepmesh.py).

A PRC file is a small header, then per "file structure" a run of zlib sections (globals, tree, tessellation,
geometry, extra geometry), then the model file section, which holds the units and the model's roots.

The reader is our own, written from the format's rules as learned from ISO 14739-1's errata threads, prc-rs (MIT, source
of the table in doubles.py) and studying how nanoPRC (AGPL) reads real files; no nanoPRC code is included.
"""

import struct
import zlib

import numpy as np

from ..pdfstreams import model_streams
from . import brep, brepmesh
from .bits import Bits, PrcError
from .tess import rebuild
from .schema import read_schema
from .tree import attributes, name_of, placements, read_globals, read_tree

__all__ = ["PrcError", "Piece", "Prc", "read_pdf", "read_prc", "streams_in_pdf"]

GLOBALS_SECTION, TREE_SECTION, TESSELLATION_SECTION, GEOMETRY_SECTION = 1, 2, 3, 4  # among a file structure's offsets; 0 is its header
CHORD = 1e-3  # how far a mesh may stray from an exact surface, against the size of the body...
CHORD_MODEL = 1e-4  # ...and of everything in its context, so that a model of thousands of tiny bodies stays a sensible size
WELD = 1e-6  # points this close, against the size of the body, are one
TYPE_FILE_TESSELLATION = 305
TYPE_MODEL_FILE = 301
TYPE_TESS_3D, TYPE_TESS_COMPRESSED, TYPE_TESS_FACE, TYPE_TESS_WIRE, TYPE_TESS_MARKUP = 172, 173, 174, 175, 176

# what a face of an uncompressed tessellation holds, in the order it's stored. Each kind of group is one of triangles
# (a count), fans or strips (a count of them, then the indices in each); "one normal" means only the first corner has
# one; "textured" adds texture indices to every corner. Polyfaces are the flags left out here.
TRIANGLES, FANS, STRIPS = 0, 1, 2
_FACE_GROUPS = ((0x2, TRIANGLES, False, False), (0x4, FANS, False, False), (0x8, STRIPS, False, False),
                (0x20, TRIANGLES, True, False), (0x40, FANS, True, False), (0x80, STRIPS, True, False),
                (0x200, TRIANGLES, False, True), (0x400, FANS, False, True), (0x800, STRIPS, False, True),
                (0x2000, TRIANGLES, True, True), (0x4000, FANS, True, True), (0x8000, STRIPS, True, True))
_POLYFACES = 0x1 | 0x10 | 0x100 | 0x1000
_NORMAL_SINGLE = 0x40000000  # a flag carried on a fan's or strip's index count
_WIRE_CLOSING = 0x10000000
_WIRE_SIZE = 0x0FFFFFFF


class Piece:
    """One tessellation: points (n, 3), triangles (m, 3), the face of each triangle, corner normals or None,
    which faces are planar (or None), and the tolerance its points were rounded to."""

    def __init__(self, points, triangles, faces, normals, planar, tolerance, unread):
        self.points, self.triangles, self.faces, self.normals = points, triangles, faces, normals
        self.planar, self.tolerance, self.unread = planar, tolerance, unread
        self.key = None  # (file structure, tessellation number)


class Placed:
    """A piece put in its place in the assembly."""

    def __init__(self, piece, matrix, name, color):
        self.piece, self.matrix, self.name, self.color = piece, matrix, name, color


class Prc:
    def __init__(self):
        self.pieces = []
        self.unit_mm = 1.0  # millimeters per file unit
        self.name = ""
        self.warnings = []
        self.notices = []
        self.thin_limit = 0.0  # triangles lower than this, in file units, can't be trusted to face the way they seem to
        self.version = 0  # the version of PRC it was written in: some fields came later
        self.placed = None  # [Placed] from the file's tree; None when the tree couldn't be followed
        self.roots = []  # (file structure's id, biased product number, active)
        self.tree_problem = None


# ---------------------------------------------------------------------------------------------- in the PDF
def streams_in_pdf(data, password=""):
    """The PRC streams in a PDF's bytes, in file order."""
    return model_streams(data, b"PRC", b"PRC", password)


def read_pdf(path, password=""):
    """Every PRC model in a PDF, read. Raises PrcError when there's one but nothing can be shown of it."""
    with open(path, "rb") as f:
        data = f.read()
    return [read_prc(s) for s in streams_in_pdf(data, password)]


# ---------------------------------------------------------------------------------------------- in the PRC
def _section(data, offset):
    try:
        return zlib.decompressobj().decompress(data[offset:])
    except zlib.error as e:
        raise PrcError(f"A section of the PRC data is damaged ({e}).") from None


def read_prc(data):
    if data[:3] != b"PRC":
        raise PrcError("This isn't PRC data.")
    pos = 3 + 8 + 32  # versions, then the file's and the application's ids
    count = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    structures, ids = [], {}
    for k in range(count):
        ids[struct.unpack_from("<4I", data, pos)] = k
        pos += 16 + 4  # its id, a reserved word
        n = struct.unpack_from("<I", data, pos)[0]
        structures.append(struct.unpack_from(f"<{n}I", data, pos + 4))
        pos += 4 + 4 * n
    model_offset = struct.unpack_from("<I", data, pos)[0]
    out = Prc()
    out.version = struct.unpack_from("<I", data, 7)[0]
    try:
        _read_model_file(_section(data, model_offset), out)
    except (PrcError, struct.error, IndexError) as e:
        out.warnings.append(f"The file's units couldn't be read ({e}); taken as millimeters.")
    for k, offsets in enumerate(structures):
        if len(offsets) > TESSELLATION_SECTION:
            _read_tessellations(_section(data, offsets[TESSELLATION_SECTION]), out, k)
    _place(data, structures, ids, out)
    return out


def _place(data, structures, ids, out):
    """Follow the file's tree to put the pieces where they go. Failing that, they stay where they were modelled."""
    files, schemas = [], []
    try:
        for offsets in structures:
            head = Bits(_section(data, offsets[GLOBALS_SECTION]))
            schema = read_schema(head)  # the fields newer files add, which this file structure's entities carry
            schemas.append(schema)
            head.schema = schema
            tree = Bits(_section(data, offsets[TREE_SECTION]))
            tree.schema = schema
            parts, products = read_tree(tree, out.version)
            try:
                global_data = read_globals(head, out.version)
            except (PrcError, IndexError, ValueError, OverflowError):
                global_data = None  # its local coordinates and colors go without
            files.append({"parts": parts, "products": products, "globals": global_data})
        where = placements(files, ids, out.roots)
        _mesh_exact(data, structures, schemas, {(f, t) for f, t, *_ in where if isinstance(t, tuple)}, out)
        pieces = {p.key: p for p in out.pieces}
        out.placed = [Placed(pieces[(f, t)], m, name, color) for f, t, m, name, color in where if (f, t) in pieces]
    except (PrcError, IndexError, ValueError, OverflowError) as e:
        out.placed = None
        out.tree_problem = str(e)
        if not out.pieces:  # nothing to say where they go, but they can still be seen where they were modelled
            _mesh_exact(data, structures, schemas, None, out)


def _mesh_exact(data, structures, schemas, wanted, out):
    """Pieces from exact bodies: those named in `wanted` as (file structure, ("exact", context, body)), or all of them for None."""
    if wanted is not None and not wanted:
        return
    approximate = skipped = 0
    for k, offsets in enumerate(structures):
        if len(offsets) <= GEOMETRY_SECTION or k >= len(schemas):
            continue
        if wanted is not None and not any(f == k for f, _ in wanted):
            continue
        try:
            b = Bits(_section(data, offsets[GEOMETRY_SECTION]))
            b.schema = schemas[k]
            contexts = brep.read_geometry(b)
        except (PrcError, IndexError, ValueError, OverflowError, struct.error, TypeError, AttributeError) as e:
            out.warnings.append(f"This model's exact geometry couldn't be read ({e}).")
            continue
        for c, context in enumerate(contexts):
            boxes = [brepmesh.bounds(body) if body is not None else None for body in context.bodies]
            known = [x for x in boxes if x is not None]
            overall = float(np.linalg.norm(np.max([x[1] for x in known], axis=0) - np.min([x[0] for x in known], axis=0))) if known else 0.0
            for n, (body, box) in enumerate(zip(context.bodies, boxes)):
                key = (k, ("exact", c, n))
                if body is None or box is None or (wanted is not None and key not in wanted):
                    continue
                size = float(np.linalg.norm(box[1] - box[0]))
                if size <= 0:
                    continue
                points, triangles, faces, normals, planar, counts = brepmesh.mesh_body(body, max(size * CHORD, overall * CHORD_MODEL), size * WELD)
                approximate += counts.approximate
                skipped += counts.skipped
                if len(triangles):
                    piece = Piece(points * context.scale, triangles, faces, normals, planar, size * WELD * context.scale, {})
                    piece.key = key
                    out.pieces.append(piece)
    if approximate:
        out.notices.append(f"{_faces(approximate)} of this model had no surface that could be followed, so shaped from the edges alone.")
    if skipped:
        out.notices.append(f"{_faces(skipped)} of this model couldn't be drawn.")


def _faces(count):
    return "1 face" if count == 1 else f"{count} faces"


def _read_model_file(raw, out):
    b = Bits(raw)
    b.u()  # this section alone starts with an extra word
    if b.u() != TYPE_MODEL_FILE:
        raise PrcError("no model file section")
    attributes(b)
    name = name_of(b)
    out.name = "" if name == "unnamed" else name
    b.bit()  # units from the CAD file
    unit = b.double()
    if unit > 0:
        out.unit_mm = unit
    for _ in range(b.u()):  # the roots of the model: a file structure's id, a product in it, and is it on?
        uid = (b.u(), b.u(), b.u(), b.u())
        index = b.u()
        out.roots.append((uid, index, bool(b.bit())))


def _read_tessellations(raw, out, structure):
    b = Bits(raw)
    if b.u() != TYPE_FILE_TESSELLATION:
        raise PrcError("The tessellation section of the PRC data isn't one.")
    attributes(b)
    name_of(b)
    total = b.u()
    for i in range(total):
        kind = b.u()
        if kind == TYPE_TESS_COMPRESSED:
            piece = _compressed(b, out.version)
            if len(piece.triangles):
                piece.key = (structure, i)
                out.pieces.append(piece)
        elif kind == TYPE_TESS_3D:
            piece = _uncompressed(b, out.version)
            if len(piece.triangles):
                piece.key = (structure, i)
                out.pieces.append(piece)
        elif kind == TYPE_TESS_WIRE:
            _skip_wire(b)
        elif kind == TYPE_TESS_MARKUP:
            _skip_markup(b)
        else:  # an unknown kind can't be stepped over: what's read so far stands
            out.warnings.append(f"{total - i} pieces of this model are in a form that can't be shown yet.")
            return


def _skip_coordinates(b):
    b.bit()
    for _ in range(b.u()):
        b.double()


def _skip_colors(b, points, segments, is_face=False):
    """Vertex colors: the first in full, then a same-as-before bit and a color only when it differs."""
    width = 32 if b.bit() else 24
    count = points
    if not is_face and b.bit():
        count = segments
    if b.bit() or count <= 0:  # "optimised": nothing stored
        return
    b.read(width)
    for _ in range(count - 1):
        if not b.bit():
            b.read(width)


def _skip_wire(b):
    _skip_coordinates(b)
    total = b.u()
    done = elements = points = 0
    while done < total:
        size = b.u()
        n = size & _WIRE_SIZE
        for _ in range(n):
            b.u()
        points += n + (1 if size & _WIRE_CLOSING else 0)
        done += 1 + n
        elements += 1
    if b.bit():
        _skip_colors(b, points, max(points - elements, 0))


def _skip_markup(b):
    _skip_coordinates(b)
    for _ in range(b.u()):
        b.u()
    for _ in range(b.u()):
        b.string()
    b.string()
    b.read(8)


def _skip_texture_parameters(b):
    b.bytes(b.u() * 4)
    b.u()
    for _ in range(b.u()):
        b.read(b.read(5))  # NumberOfBitsThenUnsignedInteger
    b.double()
    b.bytes(b.u() * 4)


def _compressed(b, version):
    """One compressed tessellation."""
    b.bit()  # is_calculated
    has_faces = b.bit()
    tolerance = b.double()
    origin = [b.float_bytes() for _ in range(3)] if version >= 7031 else [0.0, 0.0, 0.0]
    ints = b.integers()
    edges = b.huffman(2, False)
    tri_face = b.indices()
    if tri_face:
        count = len(tri_face)
    else:  # no faces: one per triangle, or three, of which the rest are zero
        count = len(edges) // 3 if len(edges) % 3 == 0 and not any(edges[len(edges) // 3:]) else len(edges)
        tri_face = [0] * count
    face_count = max(tri_face) + 1 if tri_face else 0
    flags = b.flags(b.u())
    n_refs = int(flags.sum())
    refs = b.indices(False, n_refs > 3)
    planar = reversed_flags = normal_bits = angles = None
    width = 0
    if b.bit():  # normals to be worked out by the reader
        reversed_flags = b.flags(len(tri_face))
        b.double()  # crease angle
        b.read(8)
    else:
        width = b.read(8)
        normal_bits = b.flags(b.u())
        angles = b.huffman(width, True, wide=True)
        planar = b.flags(face_count).tolist()
    stated = face_count if has_faces else 1
    if b.bit():  # colors at points
        b.flags(stated)
        b.huffman(8, False)
    if b.bit():  # several line styles on a face
        b.flags(stated)
    b.huffman(16, True, wide=True)  # line styles
    if not b.bit():  # textured
        _skip_texture_parameters(b)
        if not b.bit():
            b.flags(face_count)
    if b.bit():  # behaviours
        b.huffman(8, False)
    points, triangles, normals, unread = rebuild(tolerance, origin, ints, edges[:count], tri_face, flags, refs,
                                                 reversed_flags, normal_bits, angles, width, planar)
    return Piece(points, triangles, np.array(tri_face, np.int64), normals, planar, tolerance, unread)


def _u_list(b):
    return [b.u() for _ in range(b.u())]


def _face_record(b):
    """One face of an uncompressed tessellation: (flags, start in the index array, sizes, texture indices per corner)."""
    if b.u() != TYPE_TESS_FACE:
        raise PrcError("A face in the PRC data isn't one.")
    styles = _u_list(b)
    b.u()  # start of wire data
    _u_list(b)
    flags = b.u()
    start = b.u()
    sizes = _u_list(b)
    textures = b.u()
    if b.bit():  # vertex colors
        _skip_colors(b, _corners_in(flags, sizes), 0, is_face=True)
    if styles:
        b.u()
    return flags, start, sizes, textures


def _groups(flags, sizes):
    """(kind, one normal, textured, primitive sizes) of each group a face holds, in stored order."""
    at = 0
    for flag, kind, one, textured in _FACE_GROUPS:
        if not flags & flag:
            continue
        if at >= len(sizes):
            raise PrcError("A face in the PRC data says less than it should.")
        n = sizes[at]
        at += 1
        if kind == TRIANGLES:
            yield kind, one, textured, n
        else:
            yield kind, one, textured, [v & ~_NORMAL_SINGLE for v in sizes[at:at + n]]
            at += n


def _corners_in(flags, sizes):
    if flags & _POLYFACES:
        raise PrcError("Colored polyfaces in the PRC data aren't handled.")
    return sum(g[3] * 3 if g[0] == TRIANGLES else sum(g[3]) for g in _groups(flags, sizes))


def _uncompressed(b, version):
    """One uncompressed tessellation: points and normals as doubles, then index lists by face."""
    b.bit()  # is_calculated
    coords = [b.double() for _ in range(b.u())]
    b.bit()  # has_faces
    must_calculate = False
    if version >= 7039:
        b.bit()  # has_loops
    if version >= 7047:
        must_calculate = b.bit()
        if must_calculate:
            b.read(8)
            b.double()  # crease angle
    stored = [b.double() for _ in range(b.u())]
    _u_list(b)  # wire indices
    index = _u_list(b)
    records = [_face_record(b) for _ in range(b.u())]
    for _ in range(b.u()):
        b.double()  # texture coordinates

    tris, corner_normals, faces = [], [], []
    has_normals = bool(stored) and not must_calculate
    skipped = 0
    misplaced = 0
    pos = None
    for face, (flags, start, sizes, textures) in enumerate(records):
        if pos is not None and pos != start:
            misplaced += 1
        pos = start
        if flags & _POLYFACES:
            skipped += 1
            pos = None
            continue
        for kind, one, textured, sizes_of in _groups(flags, sizes):
            skip_t = textures if textured else 0
            primitives = [3] * sizes_of if kind == TRIANGLES else sizes_of
            for size in primitives:
                ps, ns = [], []
                for corner in range(size):
                    has_n = not must_calculate and (corner == 0 or not one)
                    if has_n:
                        n = index[pos]
                        pos += 1
                    pos += skip_t
                    ps.append(index[pos] // 3)
                    pos += 1
                    ns.append(n // 3 if has_normals else 0)
                for x, y, z in _triangles_of(kind, size):
                    tris.append((ps[x], ps[y], ps[z]))
                    corner_normals.append((ns[x], ns[y], ns[z]))
                    faces.append(face)
    unread = {"indices": (len(index) - pos if pos is not None else 0), "misplaced": misplaced}
    points = np.array(coords, np.float64).reshape(-1, 3)
    triangles = np.array(tris, np.int64).reshape(-1, 3)
    normals = None
    if has_normals and len(triangles):
        normals = np.array(stored, np.float64).reshape(-1, 3)[np.array(corner_normals, np.int64)]
    if len(triangles) and (triangles.max() >= len(points) or triangles.min() < 0):
        raise PrcError("A PRC triangle refers to a point that doesn't exist.")
    piece = Piece(points, triangles, np.array(faces, np.int64), normals, None, 0.0, unread)
    piece.skipped_polyfaces = skipped
    return piece


def _triangles_of(kind, size):
    """The corner numbers of the triangles in a primitive of `size` corners."""
    if kind == TRIANGLES:
        return ((0, 1, 2),)
    if kind == FANS:
        return [(0, i, i + 1) for i in range(1, size - 1)]
    return [(i, i + 1, i + 2) if i % 2 == 0 else (i + 1, i, i + 2) for i in range(size - 2)]
