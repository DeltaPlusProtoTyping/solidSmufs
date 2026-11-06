"""Reading 3D models out of PDFs that hold them in PRC (ISO 14739-1), the format of McMaster-Carr's and most CAD
tools' 3D PDFs. What's read is the display tessellation, the triangles the file was made to be shown with.

A PRC file is a small header, then per "file structure" a run of zlib sections (globals, tree, tessellation,
geometry, extra geometry), then the model file section, which holds the units and the model's roots.

The reader is our own, written from the format's rules as learned from ISO 14739-1's errata threads, prc-rs (MIT, source
of the table in doubles.py) and studying how nanoPRC (AGPL) reads real files; no nanoPRC code is included.
"""

import re
import struct
import zlib

import numpy as np

from .bits import Bits, PrcError
from .tess import rebuild
from .schema import read_schema
from .tree import attributes, name_of, placements, read_globals, read_tree

__all__ = ["PrcError", "Piece", "Prc", "read_pdf", "read_prc", "streams_in_pdf"]

GLOBALS_SECTION, TREE_SECTION, TESSELLATION_SECTION = 1, 2, 3  # among a file structure's offsets; 0 is its header
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
        self.unit_mm = 1.0  # millimetres per file unit
        self.name = ""
        self.warnings = []
        self.version = 0  # the version of PRC it was written in: some fields came later
        self.placed = None  # [Placed] from the file's tree; None when the tree couldn't be followed
        self.roots = []  # (file structure's id, biased product number, active)
        self.tree_problem = None


# ---------------------------------------------------------------------------------------------- in the PDF
def streams_in_pdf(data):
    """The PRC streams in a PDF's bytes, last version of each first found (in file order)."""
    out = []
    for m in re.finditer(rb"/Subtype\s*/PRC\b", data):
        start = data.rfind(b"obj", 0, m.start())
        at = data.find(b"stream", m.end())
        if start < 0 or at < 0:
            continue
        info = data[start:at]
        body = at + 6
        if data[body:body + 2] == b"\r\n":
            body += 2
        elif data[body:body + 1] in (b"\n", b"\r"):
            body += 1
        length = _stream_length(info, data)
        end = body + length if length is not None and data[body + length:body + length + 12].lstrip()[:9] == b"endstream" \
            else data.find(b"endstream", body)
        if end < 0:
            continue
        raw = data[body:end]
        if b"FlateDecode" in info or b"/Fl" in info:
            try:
                raw = zlib.decompressobj().decompress(raw)
            except zlib.error:
                continue
        if raw[:3] == b"PRC":
            out.append(raw)
    return out


def _stream_length(info, data):
    m = re.search(rb"/Length\s+(\d+)(\s+\d+\s+R)?", info)
    if not m:
        return None
    if not m.group(2):
        return int(m.group(1))
    held = re.search(rb"(?:^|[\r\n\s])" + m.group(1) + rb"\s+\d+\s+obj\s*(\d+)", data)  # /Length n 0 R
    return int(held.group(1)) if held else None


def read_pdf(path):
    """Every PRC model in a PDF, read. Raises PrcError when there's one but nothing can be shown of it."""
    with open(path, "rb") as f:
        data = f.read()
    return [read_prc(s) for s in streams_in_pdf(data)]


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
        out.warnings.append(f"The file's units couldn't be read ({e}); taken as millimetres.")
    for k, offsets in enumerate(structures):
        if len(offsets) > TESSELLATION_SECTION:
            _read_tessellations(_section(data, offsets[TESSELLATION_SECTION]), out, k)
    _place(data, structures, ids, out)
    return out


def _place(data, structures, ids, out):
    """Follow the file's tree to put the pieces where they go. Failing that, they stay where they were modelled."""
    files = []
    try:
        for offsets in structures:
            head = Bits(_section(data, offsets[GLOBALS_SECTION]))
            schema = read_schema(head)  # the fields newer files add, which this file structure's entities carry
            head.schema = schema
            tree = Bits(_section(data, offsets[TREE_SECTION]))
            tree.schema = schema
            parts, products = read_tree(tree, out.version)
            try:
                global_data = read_globals(head, out.version)
            except (PrcError, IndexError, ValueError, OverflowError):
                global_data = None  # its local coordinates and colours go without
            files.append({"parts": parts, "products": products, "globals": global_data})
        pieces = {p.key: p for p in out.pieces}
        out.placed = [Placed(pieces[(f, t)], m, name, color) for f, t, m, name, color in placements(files, ids, out.roots)
                      if (f, t) in pieces]
    except (PrcError, IndexError, ValueError, OverflowError) as e:
        out.placed = None
        out.tree_problem = str(e)


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
    """Vertex colours: the first in full, then a same-as-before bit and a colour only when it differs."""
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
    if b.bit():  # colours at points
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
    if b.bit():  # vertex colours
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
        raise PrcError("Coloured polyfaces in the PRC data aren't handled.")
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
