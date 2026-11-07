"""The bit stream inside a U3D block (ECMA-363 clause 10 and annex A): everything in a block, compressed or not, is one
arithmetic-coded stream. A "plain" byte is a symbol from a flat context of 256, which leaves the coder as it found it,
so until the first really compressed value the stream is the block's bytes as they lie. A block starts afresh: its
adaptive contexts don't carry over to the next block.
"""

from bisect import bisect_right
from itertools import accumulate

import numpy as np

STATIC_LIMIT = 0x3FFF  # a range this wide or wider isn't compressed: it's written as a plain value
MAX_ADAPTIVE_SYMBOL = 0xFFFF  # larger symbols are never counted, so they always come through the escape
ELEPHANT = 0x1FFF  # an adaptive count this high is halved, to keep room and to follow changing statistics
_READ_COUNT = (4, 3, 2, 2, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0)
_FAST_MASK = (0xFFFF, 0x7FFF, 0x3FFF, 0x1FFF, 0x0FFF)
_REVERSED = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))


class U3dError(ValueError):
    """The U3D data can't be read."""


class _Adaptive:
    """How often each symbol has come up. Symbol 0 is the escape, and starts out having been seen once."""
    __slots__ = ("symbols", "counts", "total")

    def __init__(self):
        self.symbols, self.counts, self.total = [0], [1], 1

    def add(self, symbol):
        if symbol >= MAX_ADAPTIVE_SYMBOL:
            return
        if self.total >= ELEPHANT:
            self.counts = [c >> 1 for c in self.counts]
            self.counts[0] += 1
            self.total = sum(self.counts)
        at = bisect_right(self.symbols, symbol) - 1
        if self.symbols[at] == symbol:
            self.counts[at] += 1
        else:
            self.symbols.insert(at + 1, symbol)
            self.counts.insert(at + 1, 1)
        self.total += 1


class Stream:
    def __init__(self, data, plain=False):
        """`plain`: a file written in "no compression mode", where compressed fields hold plain values."""
        self.raw = data
        self.bits = data.translate(_REVERSED) + bytes(8)  # first bit read is each byte's lowest: now each byte's highest
        self.pos = 0
        self.low, self.high, self.underflow = 0, 0xFFFF, 0
        self.plain = plain
        self.contexts = {}

    # ---------------------------------------------------------------- the coder
    def _code(self):
        """The next 16 bits as the coder sees them: skipping any bits held back by an underflow, which aren't read yet."""
        b, p = self.bits, self.pos
        i = p >> 3
        first = (b[i] >> (7 - (p & 7))) & 1
        p += 1 + self.underflow
        i = p >> 3
        return first << 15 | ((b[i] << 16 | b[i + 1] << 8 | b[i + 2]) >> (9 - (p & 7))) & 0x7FFF

    def _narrow(self, cum, freq, total):
        """Take a symbol out of the coder's range, and count how many bits that settles."""
        size = self.high + 1 - self.low
        high = self.low - 1 + size * (cum + freq) // total
        low = self.low + size * cum // total
        n = _READ_COUNT[((low >> 12) ^ (high >> 12)) & 0xF]
        low = (low & _FAST_MASK[n]) << n
        high = (high & _FAST_MASK[n]) << n | ((1 << n) - 1)
        while not (low ^ high) & 0x8000:
            low = (low & 0x7FFF) << 1
            high = (high & 0x7FFF) << 1 | 1
            n += 1
        keep_low, keep_high = low & 0x8000, high & 0x8000
        if n:
            n += self.underflow
            self.underflow = 0
        while low & 0x4000 and not high & 0x4000:
            low = (low & 0x3FFF) << 1
            high = (high & 0x3FFF) << 1 | 1
            self.underflow += 1
        self.low, self.high = low | keep_low, high | keep_high
        self.pos += n

    def _static(self, total):
        """A symbol from a flat context of `total`: 1 to total."""
        code = self._code()
        if code < self.low or code > self.high:
            raise U3dError("The U3D data is damaged.")
        at = (total * (1 + code - self.low) - 1) // (self.high + 1 - self.low)
        self._narrow(at, 1, total)
        return at + 1

    def _adaptive(self, name):
        hist = self.contexts.get(name)
        if hist is None:
            hist = self.contexts[name] = _Adaptive()
        code = self._code()
        if code < self.low or code > self.high:
            raise U3dError("The U3D data is damaged.")
        total = hist.total
        at = (total * (1 + code - self.low) - 1) // (self.high + 1 - self.low)
        counts = hist.counts
        running = list(accumulate(counts))
        i = bisect_right(running, at)
        symbol = hist.symbols[i]
        self._narrow(running[i - 1] if i else 0, counts[i], total)
        hist.add(symbol)
        return symbol

    # ---------------------------------------------------------------- plain values
    def u8(self):
        if self.low == 0 and self.high == 0xFFFF and not self.underflow:  # the coder has nothing held: just a byte
            p = self.pos
            i = p >> 3
            value = ((self.bits[i] << 8 | self.bits[i + 1]) >> (8 - (p & 7))) & 0xFF
            self.pos = p + 8
            return _REVERSED[value]
        return _REVERSED[self._static(256) - 1]

    def u16(self):
        return self.u8() | self.u8() << 8

    def u32(self):
        return self.u16() | self.u16() << 16

    def f32(self):
        return float(np.frombuffer(self.u32().to_bytes(4, "little"), "<f4")[0])

    def f64(self):
        return float(np.frombuffer((self.u32() | self.u32() << 32).to_bytes(8, "little"), "<f8")[0])

    def string(self):
        size = self.u16()
        return bytes(self.u8() for _ in range(size)).decode("utf-8", "replace")

    def floats(self, count):
        """`count` F32 values as an array: at the speed of the file's bytes where the coder has nothing held."""
        if self.low == 0 and self.high == 0xFFFF and not self.underflow and not self.pos & 7:
            at, size = self.pos >> 3, count * 4
            if at + size > len(self.raw):
                raise U3dError("The U3D data is cut short.")
            self.pos += size * 8
            return np.frombuffer(self.raw, "<f4", count, at).astype(float)
        return np.array([self.f32() for _ in range(count)], float)

    # ---------------------------------------------------------------- compressed values
    def cu32(self, name):
        if self.plain:
            return self.u32()
        symbol = self._adaptive(name)
        if symbol:
            return symbol - 1
        value = self.u32()
        self.contexts[name].add(value + 1)
        return value

    def cu16(self, name):
        if self.plain:
            return self.u16()
        symbol = self._adaptive(name)
        if symbol:
            return symbol - 1
        value = self.u16()
        self.contexts[name].add(value + 1)
        return value

    def cu8(self, name):
        if self.plain:
            return self.u8()
        symbol = self._adaptive(name)
        if symbol:
            return symbol - 1
        value = self.u8()
        self.contexts[name].add(value + 1)
        return value

    def ranged(self, size, empty="cZero"):
        """A U32 known to be less than `size`. `empty` is the context of the special case of a range of nothing."""
        if self.plain:
            return self.u32()
        if size == 0:
            return self.cu32(empty)
        if size >= STATIC_LIMIT:
            return self.u32()
        return self._static(size) - 1

    def left_bytes(self):
        """Bytes of the block not reached. The coder's last symbols settle up to a few bytes before its end."""
        return len(self.raw) - ((self.pos + self.underflow + 7) >> 3)
