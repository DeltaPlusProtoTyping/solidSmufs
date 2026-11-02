"""Read the nodes of a Parasolid transmit (text or binary) into a Model.

A transmit is a short preamble, then nodes until one of type 1:
    <type> [<layout>] [<count>] <index> <field>...
<layout> comes only at a type's first node, and only in files whose schema key has three parts
(SCH_<modeller>_<schema>_<base>, Parasolid 15+): 255 means "as in the base schema"; otherwise it's the
new field count, followed for a base type by edits of the base's fields until 'Z' (C copy one, D drop
one, I/A add a new field described inline) and for a new type by its name, description and fields.
<count> comes only for variable-length types: the length of their last field.

Text (.x_t, "T" preamble): numbers end with a space; chars, logicals (T/F), '?' (a null double, or a
whole null vector) and the characters of length-prefixed strings don't. Line breaks are only wrapping:
they fall anywhere, even inside numbers, and are dropped. Binary (.x_b and SolidWorks, "PS" preamble):
big-endian; pointers and node indexes are written one higher than in text (null is 1) and take two
shorts past 32767. Indexes here are the text ones: 0 is null.
"""

import struct

from . import UnsupportedFile
from .schema import Field, NodeType, base_schema

NULL_F = -31415800000000.0  # the binary "unset" double ('?' in text)
_D = struct.Struct(">d")
_D3 = struct.Struct(">3d")
_I = struct.Struct(">i")
_H = struct.Struct(">h")


class Node:
    __slots__ = ("idx", "type", "f")

    def __init__(self, idx, type_, f):
        self.idx, self.type, self.f = idx, type_, f

    def __getitem__(self, k):
        return self.f[k]

    def get(self, k, default=None):
        return self.f.get(k, default)

    def __repr__(self):
        return f"<{self.type} #{self.idx}>"


class Model:
    """The nodes of one transmit, by index; ``m[idx]`` is None for a null (0) or missing index."""

    def __init__(self, nodes, version, schema_key, kind):
        self.nodes, self.version, self.schema_key, self.kind = nodes, version, schema_key, kind

    def __getitem__(self, idx):
        return self.nodes.get(idx) if idx else None

    def of_type(self, *names):
        return [n for n in self.nodes.values() if n.type in names]


# ------------------------------------------------------------------ text
class _Text:
    binary = False

    def __init__(self, s, i=0):
        self.s, self.i = s, i

    def _tok(self):
        s, i = self.s, self.i
        while s[i] == " ":
            i += 1
        j = s.find(" ", i)
        if j < 0:
            j = len(s)
        self.i = j + 1
        return s[i:j]

    def int(self):
        return int(self._tok())

    short = byte = ptr = int

    def float(self):
        s, i = self.s, self.i
        while s[i] == " ":
            i += 1
        if s[i] == "?":
            self.i = i + 1
            return None
        j = s.find(" ", i)
        if j < 0:
            j = len(s)
        self.i = j + 1
        return float(s[i:j])

    def vector(self, k):
        s, i = self.s, self.i
        while s[i] == " ":
            i += 1
        if s[i] == "?":  # the whole vector is null
            self.i = i + 1
            return None
        self.i = i
        fl = self.float
        return tuple(fl() for _ in range(k))

    def vector3(self):
        return self.vector(3)

    def vector2(self):
        return self.vector(2)

    def char(self):
        c = self.s[self.i]
        self.i += 1
        return c

    def logical(self):
        c = self.s[self.i]
        self.i += 1
        if c == "T":
            return True
        if c == "F":
            return False
        raise ValueError(f"logical {c!r} at {self.i}")

    def string(self):
        n = self.int()
        st = self.s[self.i:self.i + n]
        self.i += n
        return st

    def var_flag(self):
        return self.logical()


# ------------------------------------------------------------------ binary
class _Binary:
    binary = True

    def __init__(self, d, i=0):
        self.d, self.i = d, i

    def int(self):
        v = _I.unpack_from(self.d, self.i)[0]
        self.i += 4
        return v

    def short(self):
        v = _H.unpack_from(self.d, self.i)[0]
        self.i += 2
        return v

    def byte(self):
        v = self.d[self.i]
        self.i += 1
        return v

    def ptr(self):
        d, i = self.d, self.i
        v = (d[i] << 8) | d[i + 1]
        if v < 0x8000:
            self.i = i + 2
            return v - 1
        hi = _H.unpack_from(d, i + 2)[0]
        self.i = i + 4
        return ((hi << 15) | (~(v - 0x10000) & 0x7FFF)) - 1

    def float(self):
        v = _D.unpack_from(self.d, self.i)[0]
        self.i += 8
        return None if v == NULL_F else v

    def vector(self, k):
        v = struct.unpack_from(f">{k}d", self.d, self.i)
        self.i += 8 * k
        return None if v[0] == NULL_F else v

    def vector3(self):
        v = _D3.unpack_from(self.d, self.i)
        self.i += 24
        return None if v[0] == NULL_F else v

    def vector2(self):
        return self.vector(2)

    def char(self):
        v = chr(self.d[self.i])
        self.i += 1
        return v

    def logical(self):
        v = self.d[self.i]
        self.i += 1
        return bool(v)

    def string(self):
        n = self.d[self.i]
        st = self.d[self.i + 1:self.i + 1 + n].decode("latin-1")
        self.i += 1 + n
        return st

    def string32(self):
        n = self.int()
        st = self.d[self.i:self.i + n].decode("latin-1")
        self.i += n
        return st

    def var_flag(self):
        return bool(self.byte())


# ------------------------------------------------------------------ fields
def _reader(src, code):
    """A function reading one value of a field type from src."""
    if code == "p":
        return src.ptr
    if code == "d":
        return src.int
    if code in ("n", "w"):
        return src.short
    if code == "u":
        return src.byte
    if code == "c":
        return src.char
    if code == "l":
        return src.logical
    if code == "f":
        return src.float
    if code in ("v", "h"):
        return src.vector3
    if code == "i":
        return src.vector2
    if code == "b":
        return lambda: src.vector(6)
    raise UnsupportedFile(f"Unknown Parasolid field type {code!r}.")


def _field_desc(src):
    """A field described inline (schema edits and new node types)."""
    name = src.string()
    ptr = src.short()
    n = src.short()
    code = "p" if ptr else src.string()
    if src.binary:  # written as n + 1
        n -= 1
    if n == 1:  # followed by a variable-length flag
        return Field(name, code, 1, src.var_flag())
    return Field(name, code, max(n, 1), False)


def _layout(src, base, typ, edits):
    if not edits:
        if typ not in base:
            raise UnsupportedFile(f"Unknown Parasolid node type {typ}.")
        return base[typ]
    fc = src.byte() if src.binary else src.int()
    if typ in base and fc == 255:
        return base[typ]
    if typ in base:
        bf, out, j = base[typ].fields, [], 0
        while True:
            op = src.char()
            if op == "Z":
                break
            if op == "C":
                out.append(bf[j])
                j += 1
            elif op == "D":
                j += 1
            elif op in ("I", "A"):
                out.append(_field_desc(src))
            else:
                raise ValueError(f"schema edit {op!r}")
        return NodeType(typ, base[typ].name, out)
    name = src.string()
    src.string()  # description
    return NodeType(typ, name, [_field_desc(src) for _ in range(fc)])


def _compile(src, nt):
    return nt.name, nt.var, [(f.name, _reader(src, f.code), f.n, f.var) for f in nt.fields]


def read_transmit(data):
    """Model of a transmit: bytes starting 'PS' (binary) or str/bytes starting 'T' (text, header removed)."""
    if isinstance(data, (bytes, bytearray)) and data[:2] == b"PS":
        src = _Binary(data, 2)
        version = src.string32()
        key = src.string32()
    else:
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("latin-1")
        s = data.replace("\r", "").replace("\n", "")
        if not s.startswith("T"):
            raise UnsupportedFile("This isn't a Parasolid transmit file.")
        src = _Text(s, 1)
        version = src.string()
        key = src.string()
    parts = key.strip().split("_")
    if len(parts) < 3 or parts[0].upper() != "SCH":
        raise UnsupportedFile(f"Unrecognised Parasolid schema {key!r}.")
    edits = len(parts) >= 4
    base = base_schema(parts[-1] if edits else parts[2])
    if edits:
        src.short()  # number of node types in the writer's schema
    if src.int():  # user field size
        raise UnsupportedFile("Parasolid files with user fields aren't supported.")
    kind = "deltas" if "(deltas)" in version else "partition" if "(partition)" in version else ""
    layouts, nodes = {}, {}
    rd_type, rd_count, rd_idx = src.short, src.int, src.ptr
    try:
        while True:
            typ = rd_type()
            if typ == 1:
                break
            lay = layouts.get(typ)
            if lay is None:
                lay = layouts[typ] = _compile(src, _layout(src, base, typ, edits))
            name, var, fields = lay
            count = rd_count() if var else 0
            idx = rd_idx()
            vals = {}
            for fname, rd, n, fvar in fields:
                if fvar:
                    vals[fname] = [rd() for _ in range(count)]
                elif n == 1:
                    vals[fname] = rd()
                else:
                    vals[fname] = [rd() for _ in range(n)]
            nodes[idx] = Node(idx, name, vals)
    except (IndexError, ValueError, struct.error) as e:
        if not nodes:
            raise UnsupportedFile("The Parasolid data couldn't be read.") from e
        raise UnsupportedFile(f"The Parasolid data is damaged or in an unknown variant ({e}).") from e
    return Model(nodes, version, key, kind)
