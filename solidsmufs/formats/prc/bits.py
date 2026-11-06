"""PRC's bit stream and the array encodings built on it (ISO 14739-1). Bits run most significant first."""

import struct

import numpy as np

from .doubles import table

_CODES = None


class PrcError(ValueError):
    pass


class Bits:
    def __init__(self, data):
        # one ASCII '0' / '1' per bit: slicing that and int(..., 2) is far quicker than shifting in Python
        self.s = (np.unpackbits(np.frombuffer(data, np.uint8)) + 48).tobytes()
        self.i = 0

    def bit(self):
        try:
            v = self.s[self.i] == 49
        except IndexError:
            raise PrcError("The PRC data ended early.") from None
        self.i += 1
        return v

    def read(self, n):
        """n bits, first bit highest."""
        if not n:
            return 0
        j = self.i + n
        if j > len(self.s):
            raise PrcError("The PRC data ended early.")
        v = int(self.s[self.i:j], 2)
        self.i = j
        return v

    def bytes(self, n):
        return self.read(n * 8).to_bytes(n, "big") if n else b""

    def u(self):
        """UnsignedInteger: bytes, lowest first, each behind a 'one more' bit."""
        v, shift = 0, 0
        while self.bit():
            v |= self.read(8) << shift
            shift += 8
        return v

    def string(self):
        if not self.bit():
            return ""
        return self.bytes(self.u()).split(b"\0")[0].decode("utf-8", "replace")

    def double(self):
        global _CODES
        if _CODES is None:
            _CODES = table()
        code, entry = 0, None
        for n in range(1, 23):
            code = code * 2 + self.bit()
            entry = _CODES.get((n, code))
            if entry:
                break
        if not entry:
            raise PrcError("A number in the PRC data isn't in the known codes.")
        whole, hi, lo = entry
        if whole and n == 2 and code == 1:  # exactly zero: no sign follows
            return 0.0
        v = bytearray(struct.pack("<II", lo, hi))
        if self.bit():
            v[7] |= 0x80
        if whole or not self.bit():
            return struct.unpack("<d", v)[0]
        v[6] |= self.read(4)
        last, cur = 0, 5
        while cur >= last:
            if self.bit():
                v[cur] = self.read(8)
            else:
                offset = self.read(3)
                if offset == 0:  # all the rest repeat the byte before
                    v[last:cur + 1] = bytes([v[cur + 1]]) * (cur + 1 - last)
                    break
                if offset == 6:  # all but the last repeat it; the last is stored
                    v[1:cur + 1] = bytes([v[cur + 1]]) * cur
                    v[0] = self.read(8)
                    break
                if cur + offset >= 8:
                    raise PrcError("A number in the PRC data is damaged.")
                v[cur] = v[cur + offset]
            cur -= 1
        return struct.unpack("<d", v)[0]

    def float_bytes(self):
        return struct.unpack("<f", self.bytes(4))[0]

    def signed(self, n):
        """IntegerWithVariableBitNumber: a sign bit, then n - 1 bits of size."""
        if n <= 0:
            raise PrcError("A compressed integer has no width.")
        negative = self.bit()
        v = self.read(n - 1)
        return -v if negative else v

    def flags(self, n):
        """n single-bit values."""
        j = self.i + n
        if j > len(self.s):
            raise PrcError("The PRC data ended early.")
        out = np.frombuffer(self.s, np.uint8, n, self.i) == 49
        self.i = j
        return out

    # ------------------------------------------------------------------ arrays
    def huffman(self, width, sign_extend, has_flag=True, compressed=True, wide=False):
        """CharacterArray / ShortArray: numbers of `width` bits, stored raw or Huffman coded."""
        if has_flag:
            compressed = self.bit()
        if not compressed:
            n = self.u()
            if wide:  # low byte first
                return [self._as_signed(self.read(8) | self.read(8) << 8, 16) for _ in range(n)]
            return [self._as_signed(self.read(8), 8) for _ in range(n)]
        words = self.u()
        if not words:
            return []
        raw = self.bytes(words * 4)
        used = self.u()
        if used > 32:
            raise PrcError("A compressed array in the PRC data is damaged.")
        return _huffman_decode(raw, width, sign_extend)

    @staticmethod
    def _as_signed(v, size):
        return v - (1 << size) if v >= 1 << (size - 1) else v

    def integers(self):
        """CompressedIntegerArray: each integer's width, then the integers."""
        return [self.signed(n) for n in self.huffman(6, True)]

    def indices(self, has_flag=True, compressed=True):
        """CompressedIndiceArray: changes of width, then differences from the index before."""
        changes = self.huffman(6, True, has_flag, compressed)
        out, width, value = [], 0, 0
        for k, c in enumerate(changes):
            width += c
            d = self.signed(width)
            value = d if k == 0 else value + d
            out.append(value)
        return out


def _huffman_decode(raw, width, sign_extend):
    """The Huffman stream's own bits run lowest first within each byte, so codes read as stored but numbers
    come out reversed: a table of (symbol, code length, code) and the symbols."""
    s = (np.unpackbits(np.frombuffer(raw, np.uint8), bitorder="little") + 48).tobytes()
    pos = 0

    def num(n):
        nonlocal pos
        j = pos + n
        if j > len(s):
            raise PrcError("A compressed array in the PRC data ended early.")
        v = int(s[pos:j][::-1], 2) if n else 0
        pos = j
        return v

    leaves = num(width + 1)
    if not leaves:
        return []
    longest = num(8)
    if not 0 < longest <= 32:
        raise PrcError("A compressed array in the PRC data is damaged.")
    left, right, symbol = [-1], [-1], [None]  # the tree, as arrays
    for _ in range(leaves):
        sym = num(width)
        if sign_extend and sym >= 1 << (width - 1):
            sym -= 1 << width
        length = num(longest)
        code = num(length)
        node = 0
        for k in range(length - 1, -1, -1):  # the code's highest bit is read first
            arm = right if (code >> k) & 1 else left
            if arm[node] < 0:
                arm[node] = len(left)
                left.append(-1)
                right.append(-1)
                symbol.append(None)
            node = arm[node]
        symbol[node] = sym
    count = num(32)
    out, node, end = [], 0, len(s)
    append = out.append
    while len(out) < count:
        if left[node] < 0 and right[node] < 0:  # a leaf (also a tree of one symbol, which takes no bits)
            append(symbol[node])
            node = 0
            continue
        if pos >= end:
            raise PrcError("A compressed array in the PRC data ended early.")
        node = right[node] if s[pos] == 49 else left[node]
        pos += 1
        if node < 0:
            raise PrcError("A compressed array in the PRC data has a code it doesn't define.")
    return out
