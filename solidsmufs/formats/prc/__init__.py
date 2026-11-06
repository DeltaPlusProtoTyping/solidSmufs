"""Reading 3D models out of PDFs that hold them in PRC (ISO 14739-1), the format of McMaster-Carr's and most CAD
tools' 3D PDFs. What's read is the display tessellation, the triangles the file was made to be shown with.

A PRC file is a small header, then per "file structure" a run of zlib sections (globals, tree, tessellation,
geometry, extra geometry), then the model file section, which holds the units.
"""

import re
import struct
import zlib

import numpy as np

from .bits import Bits, PrcError
from .tess import rebuild

__all__ = ["PrcError", "Piece", "Prc", "read_pdf", "read_prc", "streams_in_pdf"]

TESSELLATION_SECTION = 3  # among a file structure's offsets; 0 is its uncompressed header
TYPE_FILE_TESSELLATION = 305
TYPE_MODEL_FILE = 301
TYPE_TESS_3D, TYPE_TESS_COMPRESSED, TYPE_TESS_WIRE, TYPE_TESS_MARKUP = 172, 173, 175, 176


class Piece:
    """One tessellation: points (n, 3), triangles (m, 3), the face of each triangle, corner normals or None,
    which faces are planar (or None), and the tolerance its points were rounded to."""

    def __init__(self, points, triangles, faces, normals, planar, tolerance, unread):
        self.points, self.triangles, self.faces, self.normals = points, triangles, faces, normals
        self.planar, self.tolerance, self.unread = planar, tolerance, unread


class Prc:
    def __init__(self):
        self.pieces = []
        self.unit_mm = 1.0  # millimetres per file unit
        self.name = ""
        self.warnings = []


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
    structures = []
    for _ in range(count):
        pos += 16 + 4  # its id, a reserved word
        n = struct.unpack_from("<I", data, pos)[0]
        structures.append(struct.unpack_from(f"<{n}I", data, pos + 4))
        pos += 4 + 4 * n
    model_offset = struct.unpack_from("<I", data, pos)[0]
    out = Prc()
    try:
        _read_model_file(_section(data, model_offset), out)
    except (PrcError, struct.error, IndexError) as e:
        out.warnings.append(f"The file's units couldn't be read ({e}); taken as millimetres.")
    for offsets in structures:
        if len(offsets) > TESSELLATION_SECTION:
            _read_tessellations(_section(data, offsets[TESSELLATION_SECTION]), out)
    return out


def _attributes(b):
    """Skip a list of attributes."""
    for _ in range(b.u()):
        b.u()  # its type tag
        _attribute_title(b)
        for _ in range(b.u()):
            _attribute_title(b)
            kind = b.u()
            if kind in (1, 3):
                b.u()
            elif kind == 2:
                b.double()
            elif kind == 4:
                b.string()
            elif kind == 5:
                b.u()
                b.u()


def _attribute_title(b):
    if b.bit():
        b.u()
    else:
        b.string()


def _name(b):
    """An entity's name: blank when it reuses the one before."""
    return "" if b.bit() else b.string()


def _read_model_file(raw, out):
    b = Bits(raw)
    b.u()  # this section alone starts with an extra word
    if b.u() != TYPE_MODEL_FILE:
        raise PrcError("no model file section")
    _attributes(b)
    name = _name(b)
    out.name = "" if name == "unnamed" else name
    b.bit()  # units from the CAD file
    unit = b.double()
    if unit > 0:
        out.unit_mm = unit


def _read_tessellations(raw, out):
    b = Bits(raw)
    if b.u() != TYPE_FILE_TESSELLATION:
        raise PrcError("The tessellation section of the PRC data isn't one.")
    _attributes(b)
    _name(b)
    total = b.u()
    for i in range(total):
        kind = b.u()
        if kind == TYPE_TESS_COMPRESSED:
            piece, more = _compressed(b)
            if len(piece.triangles):
                out.pieces.append(piece)
            if not more:
                if i + 1 < total:
                    out.warnings.append(f"{total - i - 1} more pieces of this model couldn't be read.")
                return
        elif kind == TYPE_TESS_WIRE:
            _skip_wire(b)
        elif kind == TYPE_TESS_MARKUP:
            _skip_markup(b)
        else:  # the uncompressed form (or an unknown one) can't be stepped over yet: what's read so far stands
            out.warnings.append(f"{total - i} pieces of this model are in a form that can't be shown yet.")
            return


def _skip_coordinates(b):
    b.bit()
    for _ in range(b.u()):
        b.double()


def _skip_wire(b):
    _skip_coordinates(b)
    for _ in range(b.u()):
        b.u()
    if b.bit():
        raise PrcError("Coloured wires in the PRC data aren't handled.")


def _skip_markup(b):
    _skip_coordinates(b)
    for _ in range(b.u()):
        b.u()
    for _ in range(b.u()):
        b.string()
    b.string()
    b.read(8)


def _compressed(b):
    """One compressed tessellation: (Piece, whether the next one can be found after it)."""
    b.bit()  # is_calculated
    has_faces = b.bit()
    tolerance = b.double()
    origin = [b.float_bytes() for _ in range(3)]
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
    more = True
    if not b.bit():  # textured: its parameters aren't stepped over
        more = False
    elif b.bit():  # behaviours
        b.huffman(8, False)
    points, triangles, normals, unread = rebuild(tolerance, origin, ints, edges[:count], tri_face, flags, refs,
                                                 reversed_flags, normal_bits, angles, width, planar)
    return Piece(points, triangles, np.array(tri_face, np.int64), normals, planar, tolerance, unread), more
