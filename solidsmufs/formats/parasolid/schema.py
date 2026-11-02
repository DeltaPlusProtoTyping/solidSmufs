"""Parasolid schemas: the node types of a transmit file and the fields each one carries.

A schema file (``sch_<n>.s_t`` with SolidWorks, ``sch_<n>.sch_txt`` with Autodesk's ATF) lists every node
type as ``<id> <NAME>; <description>; <transmitted> <n fields> <variable>`` followed by one line per field,
``<name>; <type code>; <transmitted> <pointer class> <n>``. Only transmitted fields are in a transmit file.
``n`` is 0 for a single value, 1 for the variable-length field that ends a variable node, and the length of
a fixed array otherwise.

Type codes: d int, n/w short, u unsigned byte, c char, l logical, p pointer, f double, i interval (2 doubles),
v vector (3), h chart point (3), b box (6).

Files name their schema as ``SCH_<modeller>_<schema>`` or, from Parasolid 15 on, ``SCH_<modeller>_<schema>_<base>``;
the latter carry their differences from ``<base>`` inline (see ``nodes.py``). Almost every file uses base 13006,
which is embedded (``schema_13006.py``); any other is looked up in the CAD installs on this PC.
"""

import glob
import os

from . import UnsupportedFile


class Field:
    __slots__ = ("name", "code", "n", "var")

    def __init__(self, name, code, n=1, var=False):
        self.name, self.code, self.n, self.var = name, code, n, var

    def __repr__(self):
        return f"{self.name}:{self.code}{'*' if self.var else (self.n if self.n > 1 else '')}"


class NodeType:
    __slots__ = ("tid", "name", "fields", "var")

    def __init__(self, tid, name, fields):
        self.tid, self.name, self.fields = tid, name, fields
        self.var = any(f.var for f in fields)


# fields a schema file marks as transmitted that files don't carry (none known)
NOT_SENT = set()


def parse_schema_text(text):
    """{type id: NodeType} from the text of a schema file (transmitted fields only)."""
    lines = text.replace("\r", "").split("\n")
    try:
        k = next(i for i, ln in enumerate(lines) if ln.startswith(": SCHEMA FILE")) + 2
    except StopIteration:
        raise ValueError("not a Parasolid schema file") from None
    types = {}
    while k < len(lines):
        parts = lines[k].split(";")
        k += 1
        head = parts[0].split(None, 1)
        if len(parts) < 3 or len(head) < 2 or not head[0].isdigit():
            continue
        tid, name = int(head[0]), head[1].strip()
        _trans, nf, _var = map(int, parts[2].split()[:3])
        fields = []
        for _ in range(nf):
            fp = lines[k].split(";")
            k += 1
            sent, _ptr, n = map(int, fp[2].split()[:3])
            fname = fp[0].strip()
            if sent and (name, fname) not in NOT_SENT:
                fields.append(Field(fname, fp[1].strip(), n if n > 1 else 1, n == 1))
        types[tid] = NodeType(tid, name, fields)
    return types


def encode_table(types):
    """The compact text form used by the embedded table: 'NAME field:code field:code* field:codeN ...'."""
    out = {}
    for tid, t in sorted(types.items()):
        fs = " ".join(f"{f.name}:{f.code}{'*' if f.var else (f.n if f.n > 1 else '')}" for f in t.fields)
        out[tid] = f"{t.name} {fs}".rstrip()
    return out


def decode_table(table):
    types = {}
    for tid, line in table.items():
        name, *fs = line.split(" ")
        fields = []
        for f in fs:
            fname, spec = f.split(":")
            code, rest = spec[0], spec[1:]
            fields.append(Field(fname, code, int(rest) if rest.isdigit() else 1, rest == "*"))
        types[tid] = NodeType(tid, name, fields)
    return types


# where CAD software keeps Parasolid's schema files ({n}: the schema number)
SEARCH = (
    r"{env}\sch_{n}.s_t",
    r"{env}\sch_{n}.sch_txt",
    r"C:\Program Files\SOLIDWORKS Corp*\SOLIDWORKS*\data\pschema\sch_{n}.s_t",
    r"C:\Program Files\Common Files\SOLIDWORKS Shared\*\pschema\sch_{n}.s_t",
    r"C:\Program Files\Autodesk\*\ATF\schema\sch_{n}.sch_txt",
    r"C:\Program Files\Autodesk\*\*\schema\sch_{n}.sch_txt",
    r"C:\Program Files\Siemens\*\*\sch_{n}.sch_txt",
)
_CACHE = {}


def base_schema(n):
    """{type id: NodeType} of schema number n (a string such as '13006')."""
    n = str(n)
    if n in _CACHE:
        return _CACHE[n]
    if n == "13006":
        from .schema_13006 import TYPES
        types = decode_table(TYPES)
    else:
        env = os.environ.get("P_SCHEMA", "")
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas")
        pats = [os.path.join(here, f"sch_{n}.s_t"), os.path.join(here, f"sch_{n}.sch_txt")]
        pats += [p.format(n=n, env=env) for p in SEARCH if env or "{env}" not in p]
        found = None
        for p in pats:
            hits = sorted(glob.glob(p))
            if hits:
                found = hits[-1]
                break
        if found is None:
            raise UnsupportedFile(f"This file uses Parasolid schema {n}, which isn't on this PC "
                                  "(it comes with SolidWorks or Autodesk CAM software).")
        with open(found, encoding="latin-1") as fh:
            types = parse_schema_text(fh.read())
    _CACHE[n] = types
    return types
