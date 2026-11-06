"""PRC's schema extensions: a small program a file can declare per entity type, stepping over fields added in versions
newer than the reader knows. A reader says which version it reads as (the ISO standard's 10001 here), and the blocks
marked newer than that run; each reads and discards its fields, so the entity's end is found.
"""

from .bits import PrcError

READER_VERSION = 10001

BOOLEAN, DOUBLE, CHARACTER, UNSIGNED, INTEGER, STRING, PARENT, VECTOR_2D, VECTOR_3D, EXTENT_1D, EXTENT_2D, EXTENT_3D = range(12)
PTR_TYPE, PTR_SURFACE, PTR_CURVE, FOR, SIMPLE_FOR, IF, ELSE, BLOCK_START, BLOCK_VERSION, BLOCK_END = range(12, 22)
DECLARE, SET, DECLARE_AND_SET, VALUE, CONSTANT, VALUE_FOR, CURVE_IS_3D = range(22, 29)
MULT, DIV, ADD, SUB, LT, LE, GT, GE, EQ, NEQ, IGNORE1, IGNORE2 = range(29, 41)
_ARITHMETIC = {MULT: lambda a, b: a * b, DIV: lambda a, b: a / b, ADD: lambda a, b: a + b, SUB: lambda a, b: a - b}
_COMPARE = {LT: lambda a, b: a < b, LE: lambda a, b: a <= b, GT: lambda a, b: a > b, GE: lambda a, b: a >= b,
            EQ: lambda a, b: a == b, NEQ: lambda a, b: a != b}
_DEPTH = 256


def read_schema(b):
    """{entity type: its program}, from the start of a file structure's globals."""
    out = {}
    for _ in range(b.u()):
        tag = b.u()
        out[tag] = [b.u() for _ in range(b.u())]
    return out


class _Run:
    def __init__(self, bits, schema, codes):
        self.b, self.schema, self.c = bits, schema, codes
        self.value = None  # what the last instruction gave
        self.names = {}
        self.parent = None
        self.loop = None

    def _token(self, i):
        if not 0 <= i < len(self.c):
            raise PrcError("A PRC schema ran past its end.")
        return self.c[i]

    def skip(self, i, depth=0):
        """Past one instruction, without running it."""
        if depth > _DEPTH:
            raise PrcError("A PRC schema nests too deep.")
        t = self._token(i)
        if t in (BLOCK_START, BLOCK_VERSION):
            i += 1 if t == BLOCK_START else 2
            while self._token(i) != BLOCK_END:
                i = self.skip(i, depth + 1)
            return i + 1
        if t in (BOOLEAN, DOUBLE, CHARACTER, UNSIGNED, INTEGER, STRING, VECTOR_2D, VECTOR_3D, EXTENT_1D, EXTENT_2D, EXTENT_3D,
                 PTR_SURFACE, PTR_CURVE, VALUE_FOR, CURVE_IS_3D, IGNORE1, IGNORE2):
            return i + 1
        if t in (PTR_TYPE, PARENT, CONSTANT, VALUE, DECLARE):
            return i + 2
        if t == IF:
            i = self.skip(self.skip(i + 1, depth + 1), depth + 1)
            if i < len(self.c) and self.c[i] == ELSE:
                i = self.skip(i + 1, depth + 1)
            return i
        if t in (DECLARE_AND_SET, SET):
            return self.skip(i + 2, depth + 1)
        if t == SIMPLE_FOR:
            return self.skip(i + 1, depth + 1)
        if t == FOR or t in _ARITHMETIC or t in _COMPARE:
            return self.skip(self.skip(i + 1, depth + 1), depth + 1)
        raise PrcError(f"An unknown instruction in a PRC schema ({t}).")

    def step(self, i, depth=0):
        """Run one instruction; where the next one is."""
        if depth > _DEPTH:
            raise PrcError("A PRC schema nests too deep.")
        b, t = self.b, self._token(i)
        d = depth + 1
        if t == BOOLEAN:
            self.value = bool(b.bit())
        elif t == DOUBLE:
            self.value = b.double()
        elif t == CHARACTER:
            self.value = b.read(8)
        elif t == UNSIGNED:
            self.value = b.u()
        elif t == INTEGER:
            self.value = b.i32()
        elif t == STRING:
            b.string()
            self.value = None
        elif t == VECTOR_2D or t == EXTENT_1D:
            b.double(), b.double()
        elif t == VECTOR_3D:
            b.double(), b.double(), b.double()
        elif t == EXTENT_2D:
            for _ in range(4):
                b.double()
        elif t == EXTENT_3D:
            for _ in range(6):
                b.double()
        elif t in (PTR_SURFACE, PTR_CURVE, CURVE_IS_3D):
            pass  # geometry behind pointers: never seen in the tree, and nothing here reads it
        elif t == PTR_TYPE:
            return i + 2
        elif t == PARENT:
            self.parent = self._token(i + 1)
            return i + 2
        elif t in (FOR, SIMPLE_FOR):
            if t == FOR:
                i = self.step(i + 1, d)
                count = int(self.value)
            else:
                count = b.u()
                i += 1
            start = i
            if count == 0:
                return self.skip(start, d)
            for k in range(count):
                self.loop = k
                i = self.step(start, d)
            return i
        elif t == IF:
            i = self.step(i + 1, d)
            if self.value:
                i = self.step(i, d)
                if i < len(self.c) and self.c[i] == ELSE:
                    i = self.skip(i + 1, d)
            else:
                i = self.skip(i, d)
                if i < len(self.c) and self.c[i] == ELSE:
                    i = self.step(i + 1, d)
            return i
        elif t == BLOCK_START:
            i += 1
            while self._token(i) != BLOCK_END:
                i = self.step(i, d)
            return i + 1
        elif t == BLOCK_VERSION:
            if READER_VERSION < self._token(i + 1):
                i += 2
                while self._token(i) != BLOCK_END:
                    i = self.step(i, d)
                return i + 1
            return self.skip(i, d)
        elif t == DECLARE:
            self.names[self._token(i + 1)] = 0
            return i + 2
        elif t in (SET, DECLARE_AND_SET):
            key = self._token(i + 1)
            i = self.step(i + 2, d)
            self.names[key] = self.value
            return i
        elif t == VALUE:
            key = self._token(i + 1)
            if key not in self.names:
                raise PrcError("A PRC schema uses a value it didn't declare.")
            self.value = self.names[key]
            return i + 2
        elif t == CONSTANT:
            self.value = self._token(i + 1)
            return i + 2
        elif t == VALUE_FOR:
            self.value = self.loop
        elif t in _ARITHMETIC or t in _COMPARE:
            i = self.step(i + 1, d)
            left = self.value
            i = self.step(i, d)
            self.value = (_ARITHMETIC.get(t) or _COMPARE[t])(left, self.value)
            return i
        elif t in (IGNORE1, IGNORE2):
            return i + 2
        else:
            raise PrcError(f"An unknown instruction in a PRC schema ({t}).")
        return i + 1


def extend(b, tag, depth=0):
    """Step over the fields a file's schema adds to this entity type, if it adds any."""
    schema = getattr(b, "schema", None)
    if not schema or tag not in schema:
        return
    if depth > 16:
        raise PrcError("A PRC schema's parents nest too deep.")
    codes = schema[tag]
    run = _Run(b, schema, codes)
    i = 0
    while i < len(codes):
        i = run.step(i)
    if run.parent is not None and run.parent != tag:
        extend(b, run.parent, depth + 1)
