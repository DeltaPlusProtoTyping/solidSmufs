"""Adobe's private U3D mesh ("RHAdobeMeshResource", Right Hemisphere's compression, Acrobat 8.1 and later), read as
Adobe describes it in "U3D Supported Elements" (Acrobat SDK 8.1): chapter 2 for the layout, appendix A for the two
byte-coded integer schemes. The block isn't arithmetic-coded like the rest of U3D: it's plain little-endian bytes.

That document leaves things out and in places contradicts itself. Where it does, the comments say which reading is
taken; each was settled by trying it on data whose right answer was known, not by guessing.
"""

import math
import struct
from collections import namedtuple

import numpy as np

from .stream import U3dError

NAME = "RHAdobeMeshResource"
GUID = (0x96A804A6, 0x3FB9, 0x43C5, bytes((0xB2, 0xDF, 0x2A, 0x31, 0xB5, 0x56, 0x93, 0x40)))

MOST = 1 << 24  # no count in a mesh may be more than this: with nothing else to hold it to, a count could ask for anything
ROOM = 1 << 30  # nor may its arrays hold more numbers than this between them: a few bytes can stand for a great many
_U32 = 0xFFFFFFFF
_BLOCK = 1 << 16  # byte-coded integers are gathered this many at a time
_COUNTS = ("triangles", "points", "normals", "diffuse colours", "specular colours", "texture coordinates")
_EXTENDED = (0, 1, 2, 3, 4, 0xFF, 0xFF00, 0xFF0000, 0xFF000000, 0x00FFFFFF, 0xFFFFFFFF)  # UIC1's one-byte constants
_CUT = "Adobe's mesh format: the data is cut short."
_BIG = "Adobe's mesh format: the mesh is too big to hold."
_DAMAGED = "Adobe's mesh format: the data is damaged."

# dims: what the block says of each layer's texture coordinates, two bits a layer (always at least one entry)
Material = namedtuple("Material", "diffuse specular layers shading dims")


class Mesh:
    """All that a block holds. Each `..._faces` array is rows of three, a corner each, into the array it's named for.
    `triangles`, `normal_faces` and each layer of `texcoord_faces` have a row for every face. `diffuse_faces` and
    `specular_faces` only have rows for the faces whose material has such colours, in the order of the faces.
    """

    def __init__(self):
        self.name = ""
        self.materials = []  # Material, in the order `ids` counts them
        self.points = self.normals = np.zeros((0, 3), np.float32)
        self.diffuse = self.specular = self.texcoords = np.zeros((0, 4), np.float32)  # RGBA; texcoords always have 4 parts
        self.ids = np.zeros(0, np.uint32)  # material of each face
        self.triangles = self.normal_faces = self.diffuse_faces = self.specular_faces = np.zeros((0, 3), np.uint32)
        self.texcoord_faces = []  # one array per texture layer
        self.skeleton = False  # a skeleton follows the mesh: it isn't read
        self.used = 0  # bytes of the block the mesh took


def available():
    return True


class _Reader:
    def __init__(self, data):
        self.data, self.pos, self.room = bytes(data), 0, ROOM

    def take(self, size):
        at = self.pos
        if size < 0 or at + size > len(self.data):
            raise U3dError(_CUT)
        self.pos = at + size
        return self.data[at:at + size]

    def u8(self):
        if self.pos >= len(self.data):
            raise U3dError(_CUT)
        self.pos += 1
        return self.data[self.pos - 1]

    def uint(self, width):
        return int.from_bytes(self.take(width), "little")

    def spend(self, count):
        """Before making `count` numbers: an array of the one value over and over costs the file next to nothing."""
        self.room -= count
        if self.room < 0:
            raise U3dError(_BIG)

    # ---------------------------------------------------------------- floats
    def floats(self, count, parts):
        """`count` rows of `parts` numbers. The document's types 0, 2 and 3; there is no type 1."""
        kind = self.u8()
        self.spend(count * parts)
        if kind == 0:  # as they are, but a part at a time: every x, then every y...
            return np.ascontiguousarray(np.frombuffer(self.take(4 * count * parts), "<f4").reshape(parts, count).T)
        if kind == 2:  # each part as whole steps between its least and its most
            out = np.empty((count, parts), np.float32)
            for k in range(parts):
                low, high = struct.unpack("<ff", self.take(8))
                if low == high:  # then that's all there is of this part: no step count, no integers
                    out[:, k] = low
                    continue
                steps = self.uint(4)
                values = self.ints(count)
                with np.errstate(all="ignore"):  # no steps at all gives infinities, as written
                    # the size of one step is worked out first: the last bit of the answer hangs on the order
                    out[:, k] = low + values * (np.float64(high - low) / steps)
            return out
        if kind == 3:  # unit normals as two angles. The document lists two arrays; it's one: every alpha, then every theta
            steps = self.uint(4)
            values = self.ints(2 * count)
            with np.errstate(all="ignore"):
                step = np.float64(2 * math.pi) / steps  # likewise worked out first
                alpha, theta = values[:count] * step, values[count:] * step
                sine = np.sin(theta)
                return np.column_stack((sine * np.cos(alpha), sine * np.sin(alpha), np.cos(theta))).astype(np.float32)
        raise U3dError(f"Adobe's mesh format: number type {kind} isn't one this knows.")

    # ---------------------------------------------------------------- integers
    def ints(self, count):
        """`count` U32 values, in whichever of the document's encodings the first byte names."""
        first = self.u8()
        kind = first & 63
        self.spend(count)
        if kind == 0:  # all zero: the one byte is all there is
            return np.zeros(count, np.uint32)
        if kind == 1:  # all the same
            return np.full(count, self.uint(4), np.uint32)
        size = self.uint((first >> 6) + 1)  # how many bytes the encoded values take: where the next thing starts
        start, end = self.pos, self.pos + size
        if end > len(self.data):
            raise U3dError(_CUT)
        if kind in (8, 9):  # the document only says "as in U3D", not which contexts or what is coded
            raise U3dError(f"Adobe's mesh format: integer encoding {kind} (arithmetic coding) isn't supported.")
        if kind == 2:  # half a byte each, the low half first
            raw = np.frombuffer(self._fixed((count + 1) // 2), np.uint8)
            out = np.empty(2 * len(raw), np.uint32)
            out[0::2], out[1::2] = raw & 15, raw >> 4
            out = out[:count]
        elif kind in (3, 4, 6):
            wide = 4 if kind == 6 else kind - 2
            out = np.frombuffer(self._fixed(count * wide), ("", "u1", "<u2", "", "<u4")[wide]).astype(np.uint32)
        elif kind == 5:
            raw = np.frombuffer(self._fixed(count * 3), np.uint8).reshape(-1, 3).astype(np.uint32)
            out = raw[:, 0] | raw[:, 1] << 8 | raw[:, 2] << 16
        elif kind == 7:
            out = self._rh39(count, end)
        elif kind == 10:
            out = self._uic1(count, end)
        else:
            raise U3dError(f"Adobe's mesh format: integer encoding {kind} isn't one this knows.")
        self.pos = end
        return out

    def _fixed(self, size):
        """The bytes of a fixed-width array. It's the count that says how many: a size too small doesn't shorten it."""
        if self.pos + size > len(self.data):
            raise U3dError(_CUT)
        return self.data[self.pos:self.pos + size]

    def _rh39(self, count, end):
        """Appendix A.1: runs of up to 4112 values, each headed by what kind of run it is and how long."""
        data, at, size = self.data, self.pos, len(self.data)
        chunks, values, offset, left = [], [], 0, count
        while left:
            if at >= end:  # the size is only looked at between runs
                raise U3dError(_CUT)
            head = data[at]
            at += 1
            kind, n = head >> 4 & 7, (head & 15) + 1
            if head & 0x80:  # a long run: a second byte of length
                if at >= size:
                    raise U3dError(_CUT)
                n = 17 + ((head & 15) << 8) + data[at]
                at += 1
            if kind == 7:  # not values: the number the next runs add to. It has 4 bytes at most, whatever length is given
                wide = min(n, 4)
                if at + wide > size:
                    raise U3dError(_CUT)
                offset = int.from_bytes(data[at:at + wide], "little")
                at += wide
                continue
            if n > left:
                raise U3dError(_DAMAGED)
            wide = (4 * n, (n + 1) // 2, n, 2 * n, 2 * n, 0, n)[kind]
            if at + wide > size:
                raise U3dError(_CUT)
            raw = data[at:at + wide]
            at += wide
            if kind == 6:  # U8 each
                values.extend(raw)
            elif kind == 5:  # the offset itself, over and over
                values.extend([offset] * n)
            elif kind == 2:  # offset + U8
                values.extend([(offset + v) & _U32 for v in raw])
            elif kind == 1:  # offset + half a byte, the low half first
                halves = [(offset + h) & _U32 for v in raw for h in (v & 15, v >> 4)]
                values.extend(halves if len(halves) == n else halves[:n])
            elif kind == 4:  # U16 each
                values.extend(struct.unpack(f"<{n}H", raw))
            elif kind == 3:  # offset + U16
                values.extend([(offset + v) & _U32 for v in struct.unpack(f"<{n}H", raw)])
            else:  # U32 each
                values.extend(struct.unpack(f"<{n}I", raw))
            left -= n
            if len(values) >= _BLOCK:
                chunks.append(np.array(values, np.uint32))
                values = []
        chunks.append(np.array(values, np.uint32))
        return np.concatenate(chunks)

    def _uic1(self, count, end):
        """Appendix A.2: a byte is a command in its low half and a number in its high half (the document's table has
        the halves the wrong way round; its code and its worked example have them right). Commands make a value from
        the one before, from one of the last 32 values, from one of the last 32 differences, or from the value three
        places back, which in a list of triangles is the same corner of the triangle before.
        """
        data, at, size = self.data, self.pos, len(self.data)
        back = [-k & 31 for k in range(32)]  # back[(here - k) & 31] is the value k places back. They start as 0, 1, 2...
        steps = [0] * 32  # differences likewise
        here = there = 0
        value = one = two = three = 0  # the last value, and the three before the one being made
        again = -1  # a value still owed by the command before: how far back it is
        chunks, values, n = [], [], 0
        while n < count:
            stop = min(count, n + _BLOCK)
            while n < stop:
                before = value
                if again >= 0:
                    value, again = back[(here - again) & 31], -1
                else:
                    if at >= end:  # as in RH39, the size is only looked at between commands
                        raise U3dError(_CUT)
                    command = data[at]
                    at += 1
                    arg, command = command >> 4, command & 15
                    if command == 0:  # one of the last 16 values
                        value = back[(here - arg) & 31]
                    elif command == 1:  # a little up or down: odd numbers are up (the document's table says otherwise)
                        value += (arg >> 1) + 1 if arg & 1 else -(arg >> 1) - 1
                    elif command == 3:
                        value = three + arg + 1
                    elif command == 4:
                        value = three - arg - 1
                    elif command == 5:  # one of the 16 values before those
                        value = back[(here - arg - 16) & 31]
                    elif command == 6:  # the same step as one of the last 16
                        value += steps[(there - arg) & 31]
                    elif command == 7:
                        value = three + arg + 17
                    elif command == 8:
                        value = three - arg - 17
                    elif 9 <= command <= 11:  # a byte more: further up, further down, or a value of 12 bits
                        if at >= size:
                            raise U3dError(_CUT)
                        arg += data[at] << 4
                        at += 1
                        value = value + arg + 3 if command == 9 else value - arg - 3 if command == 10 else arg
                    elif command == 12:  # a value of 20 bits
                        if at + 2 > size:
                            raise U3dError(_CUT)
                        value = arg + (data[at] << 4) + (data[at + 1] << 12)
                        at += 2
                    elif command == 13:  # two of the last four values: this one, and the one after
                        value, again = back[(here - (arg >> 2)) & 31], arg & 3
                    elif command == 14 or (command == 15 and arg == 13):  # the last value again, 3 to 18 times or 37 and up
                        if command == 14:
                            run = arg + 3
                        else:
                            if at + 2 > size:
                                raise U3dError(_CUT)
                            run = 37 + data[at] + (data[at + 1] << 8)
                            at += 2
                        run = min(run, count - n)
                        if run < 32:
                            for _ in range(run):
                                here = (here + 1) & 31
                                back[here] = value
                        else:
                            back = [value] * 32
                        if run >= 3:
                            one = two = three = value
                        else:
                            for _ in range(run):
                                three, two, one = two, one, value
                        if run < 256:
                            values.extend([value] * run)
                        else:
                            chunks += [np.array(values, np.uint32), np.full(run, value, np.uint32)]
                            values = []
                        n += run
                        continue
                    elif command == 15 and arg < 11:
                        value = _EXTENDED[arg]
                    elif command == 15 and arg < 13:  # a value of 24 or 32 bits
                        wide = arg - 8
                        if at + wide > size:
                            raise U3dError(_CUT)
                        value = int.from_bytes(data[at:at + wide], "little")
                        at += wide
                    else:  # command 2, and two of the extended ones, mean nothing
                        raise U3dError(_DAMAGED)
                    value &= _U32
                here = (here + 1) & 31
                back[here] = value
                if value != before and -0x7FFFFFFF < value - before < 0x7FFFFFFF:  # a step too big isn't kept
                    there = (there + 1) & 31
                    steps[there] = value - before
                three, two, one = two, one, value
                values.append(value)
                n += 1
            chunks.append(np.array(values, np.uint32))
            values = []
        return np.concatenate(chunks) if chunks else np.zeros(0, np.uint32)

    # ---------------------------------------------------------------- the block
    def material(self):
        flag = self.u8()
        layers = self.uint((flag >> 4 & 3) + 1)
        shading = self.uint((flag >> 2 & 3) + 1)
        dims = bytes((flag & 3,))
        if layers > 1:  # the first layer's is in the flag; the rest follow, four layers to a byte, low bits first
            raw = np.frombuffer(self.take((layers + 2) // 4), np.uint8)
            dims += (raw[:, None] >> np.array((0, 2, 4, 6), np.uint8) & 3).astype(np.uint8).tobytes()[:layers - 1]
        return Material(bool(flag & 0x40), bool(flag & 0x80), layers, shading, dims)

    def mesh(self):
        out = Mesh()
        out.name = self.take(self.uint(2)).decode("utf-8", "replace")
        flags = self.u8()
        if flags & 15:
            raise U3dError(f"Adobe's mesh format: version {flags & 15} of it isn't one this reads.")
        if flags & 16:  # a table of sub-chunks would follow: the document doesn't say what the mesh looks like then
            raise U3dError("Adobe's mesh format: a mesh in sub-chunks isn't supported.")
        out.skeleton = bool(flags & 32)
        # with no count there's still one material written (the document's text says none: its own example has one)
        count = self.uint((0, 1, 2, 4)[flags >> 6]) if flags >> 6 else 1
        if count * 3 > len(self.data) - self.pos:
            raise U3dError(_CUT)
        out.materials = [self.material() for _ in range(count)]

        flags = self.u8()  # which counts are written (the rest are 0), and in how many bytes each
        counts = [self.uint((flags >> 6) + 1) if flags >> k & 1 else 0 for k in range(6)]
        for n, what in zip(counts, _COUNTS):
            if n > MOST:
                raise U3dError(f"Adobe's mesh format: it can't have {n} {what}.")
        faces, points, normals, diffuse, specular, texcoords = counts
        out.points = self.floats(points, 3)  # the points' number type is there even when there are no points
        if normals:
            out.normals = self.floats(normals, 3)
        if diffuse:
            out.diffuse = self.floats(diffuse, 4)
        if specular:
            out.specular = self.floats(specular, 4)
        if texcoords:
            out.texcoords = self.floats(texcoords, 4)  # four parts each, however many of them a layer uses

        # the material of each face isn't written when there's nothing to tell apart
        out.ids = self.ints(faces) if count > 1 else np.zeros(faces, np.uint32)
        out.triangles = self.ints(3 * faces).reshape(-1, 3)
        if normals:
            out.normal_faces = self.ints(3 * faces).reshape(-1, 3)
        # colours: only the faces whose material has them. It's the materials that say so, not the counts above,
        # and when no face has them there's nothing written at all
        known = out.ids[out.ids < count]
        for k, name in ((0, "diffuse_faces"), (1, "specular_faces")):
            coloured = int(np.count_nonzero(np.array([m[k] for m in out.materials], bool)[known])) if count else 0
            if coloured:
                setattr(out, name, self.ints(3 * coloured).reshape(-1, 3))
        if texcoords:  # every face has a row in every layer, as many layers as the material with the most
            for _ in range(max((m.layers for m in out.materials), default=0)):
                out.texcoord_faces.append(self.ints(3 * faces).reshape(-1, 3))
        out.used = self.pos  # a skeleton, if any, comes after this
        return out


def read(body):
    """The whole of a block, as a Mesh."""
    try:
        return _Reader(body).mesh()
    except MemoryError:
        raise U3dError(_BIG) from None


def decode(body):
    """(name, points (n, 3), triangles (m, 3), material of each triangle, materials as (diffuse, specular, layers))."""
    mesh = read(body)
    if len(mesh.triangles) and int(mesh.triangles.max()) >= len(mesh.points):
        raise U3dError("Adobe's mesh format: a triangle uses a point that isn't there.")
    materials = [(m.diffuse, m.specular, m.layers) for m in mesh.materials]
    with np.errstate(invalid="ignore"):  # a point that isn't a number is handed on as it is, without a warning
        points = mesh.points.astype(float)
    return mesh.name, points, mesh.triangles.astype(np.int64), mesh.ids.astype(np.int64), materials
