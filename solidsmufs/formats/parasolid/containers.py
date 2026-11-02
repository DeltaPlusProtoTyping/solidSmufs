"""Find the Parasolid transmits inside SolidWorks parts and Parasolid files.

* SolidWorks 2015+ (.sldprt): a chain of chunks, each a stream name (its bytes rotated left by a key from
  the file header) and a raw-deflate payload. The part's B-rep is a Parasolid partition transmit in
  ``Contents/Config-<n>-Partition`` (or, for some parts, the bodies in ``Config-<n>-FeatureBodies/LocalBodies``;
  ``Contents/Config-<n>-Body`` in SolidWorks 2001 and earlier):
  a 16-byte marker, then zlib data in pieces, each after an 8-byte [size][compressed size].
* SolidWorks before 2015 (.sldprt, an OLE compound file, magic D0 CF 11 E0): the same streams. Each is a
  run of sections, [u32 size][section]: from about SolidWorks 2006 a section is the marker + zlib pieces as
  above; earlier ones are PKWARE DCL "implode" data (1 byte literal coding, 1 byte dictionary size, ...).
  The partition is the section whose transmit says "(partition)"; "(deltas)" is the undo history.
* Parasolid .x_t / .xmt_txt and .x_b / .xmt_bin: a text header of '**' lines up to **END_OF_HEADER, then
  the transmit (text starts "T", binary "PS").
"""

import os
import re
import struct
import zlib

from . import UnsupportedFile

GEO_MAGIC = bytes.fromhex("231dd571da8148a2a85898b21b89ef99")
CHUNK_MARK = b"\x14\x00\x06\x00\x08\x00"
OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


class Source:
    """What a file holds: its transmits (bytes or text) with where each came from."""

    def __init__(self, fmt, app=None):
        self.format, self.app = fmt, app
        self.transmits = []  # (stream name, data)
        self.header = {}


def open_source(path):
    with open(path, "rb") as fh:
        d = fh.read()
    if len(d) < 32:
        raise UnsupportedFile("The file is empty or too short to be a part.")
    ext = os.path.splitext(path)[1].lower()
    if d[:8] == OLE_MAGIC:
        return _ole_sldprt(path)
    if d[:2] == b"**" or d[:3] in (b"T51", b"PS\x00") or ext in (".x_t", ".xmt_txt", ".x_b", ".xmt_bin"):
        return _parasolid(d)
    if ext == ".sldprt" or d.find(CHUNK_MARK, 0, 4096) >= 0:
        return _sldprt_2015(d)
    raise UnsupportedFile("This doesn't look like a SolidWorks part or a Parasolid file.")


# ------------------------------------------------------------------ Parasolid files
def _parasolid(d):
    header = {}
    if d[:2] == b"**":
        i = d.find(b"**END_OF_HEADER")
        if i < 0:
            raise UnsupportedFile("The Parasolid header has no end.")
        text = d[:i].decode("latin-1").replace("\r", "").replace("\n", "")
        for m in re.finditer(r"([A-Z_0-9]+)=([^;]*);", text):
            header.setdefault(m.group(1), m.group(2).strip())
        j = d.find(b"\n", i)
        body = d[j + 1:] if j >= 0 else b""
    else:
        body = d
    k = 0
    while k < len(body) and body[k] in b"\r\n \t":
        k += 1
    body = body[k:]
    if body[:2] == b"PS":
        kind = "binary"
    elif body[:1] == b"T":
        kind = "text"
    else:
        raise UnsupportedFile("This Parasolid file's data is in a format that isn't supported "
                              "(only text and neutral binary are).")
    src = Source(f"Parasolid {kind}", header.get("APPL") or None)
    src.header = header
    src.transmits.append(("", body))
    return src


def parasolid_version(transmit_version, header=None):
    """'V17.1' from 'TRANSMIT FILE created by modeller version 1701283' (or the header's FRU)."""
    m = re.search(r"version\s+(\d{6,})", transmit_version or "")
    if m:
        v = m.group(1)
        return f"V{int(v[:-5])}.{int(v[-5:-3])}"
    m = re.search(r"Version\s+(\d+(?:\.\d+)?)", (header or {}).get("FRU", ""))
    return f"V{m.group(1)}" if m else None


# ------------------------------------------------------------------ SolidWorks 2015+
def chunk_streams(d, keep=lambda name: True):
    """{stream name: data} of a SolidWorks 2015+ file (parts and assemblies alike), for names `keep` accepts."""
    key = d[7] & 7
    rot = bytes(((b << key) | (b >> (8 - key))) & 0xFF for b in range(256))
    streams, i = {}, 0
    while True:
        m = d.find(CHUNK_MARK, i)
        if m < 0:
            return streams
        si, i = m - 4, m + 1
        if si < 0 or si + 0x1E > len(d):
            continue
        f1, csz, _usz, nsz = struct.unpack_from("<4I", d, si + 0x0E)
        if f1 < 65536 or not 0 < nsz <= 512 or si + 0x1E + nsz + csz > len(d):
            continue
        name = d[si + 0x1E: si + 0x1E + nsz].translate(rot)
        if any(b < 0x20 or b >= 0x80 for b in name):
            continue
        name = name.decode("ascii")
        if keep(name) and name not in streams:
            try:
                streams[name] = zlib.decompressobj(-15).decompress(d[si + 0x1E + nsz: si + 0x1E + nsz + csz])
            except zlib.error:  # a damaged chunk: the file's other streams are still worth having
                pass
        i = si + 0x1E + nsz + csz


def sw_streams(path, keep=lambda name: True):
    """{stream name: data} of any SolidWorks file: 2015+ chunks, or an older OLE compound file (raw streams)."""
    with open(path, "rb") as fh:
        d = fh.read()
    if d[:8] != OLE_MAGIC:
        return chunk_streams(d, keep)
    try:
        import olefile
    except ImportError:  # pragma: no cover
        raise UnsupportedFile("Reading SolidWorks files from before 2015 needs the olefile package.") from None
    try:
        ole = olefile.OleFileIO(path)
    except OSError as e:
        raise UnsupportedFile("This SolidWorks file is damaged (its compound file can't be opened).") from e
    with ole:
        names = ["/".join(e) for e in ole.listdir(streams=True, storages=False)]
        return {n: ole.openstream(n).read() for n in names if keep(n)}


def _sldprt_2015(d):
    streams = chunk_streams(d, _wanted)
    src = Source("SolidWorks part (2015+)")
    for name in sorted(streams, key=_stream_order):
        for t in _zlib_transmits(streams[name]):
            src.transmits.append((name, t))
    if not streams:
        raise UnsupportedFile("No 3D model data was found in this SolidWorks file.")
    return src


def _wanted(name):
    # -Body: SolidWorks 2001 and earlier; Ghost partitions hold reference geometry
    return name.endswith(("-Partition", "-Body", "/LocalBodies")) and "Ghost" not in name


def _stream_order(name):
    m = re.search(r"Config-(\d+)", name)
    return (0 if name.endswith(("-Partition", "-Body")) else 1, int(m.group(1)) if m else 0, name)


def _zlib_transmits(data):
    """The marked zlib transmits of a stream, each from its pieces."""
    out, i = [], 0
    while True:
        j = data.find(GEO_MAGIC, i)
        if j < 0:
            return out
        i = j + 1
        try:
            z = zlib.decompressobj()
            parts, rest = [z.decompress(data[j + 24:])], z.unused_data
            while len(rest) > 10 and rest[8:9] == b"\x78":  # [size][compressed size] + zlib, 4 KiB at a time
                z = zlib.decompressobj()
                parts.append(z.decompress(rest[8:]))
                rest = z.unused_data
        except zlib.error:
            continue
        t = b"".join(parts)
        if t[:2] == b"PS":
            out.append(t)


# ------------------------------------------------------------------ SolidWorks before 2015 (OLE)
def _ole_sldprt(path):
    try:
        import olefile
    except ImportError:  # pragma: no cover
        raise UnsupportedFile("Reading SolidWorks files from before 2015 needs the olefile package.") from None
    src = Source("SolidWorks part (pre-2015)")
    try:
        ole = olefile.OleFileIO(path)
    except OSError as e:
        raise UnsupportedFile("This SolidWorks file is damaged (its compound file can't be opened).") from e
    with ole:
        names = ["/".join(e) for e in ole.listdir(streams=True, storages=False)]
        for name in sorted((n for n in names if _wanted(n)), key=_stream_order):
            data = ole.openstream(name).read()
            for t in _ole_transmits(data):
                src.transmits.append((name, t))
    if not src.transmits:
        raise UnsupportedFile("No 3D model data was found in this SolidWorks file.")
    return src


def _ole_transmits(data):
    if GEO_MAGIC in data[:64]:
        return _zlib_transmits(data)
    out, p = [], 0
    while p + 6 < len(data):
        n = struct.unpack_from("<I", data, p)[0]
        if n <= 2 or p + 4 + n > len(data):
            break
        try:
            t = blast(data, p + 4, p + 4 + n)
        except ValueError:
            break
        if t[:2] == b"PS":
            out.append(t)
        p += 4 + n
    return out


# ------------------------------------------------------------------ PKWARE DCL "implode" (after zlib's blast.c)
_LITLEN = (11, 124, 8, 7, 28, 7, 188, 13, 76, 4, 10, 8, 12, 10, 12, 10, 8, 23, 8, 9, 7, 6, 7, 8, 7, 6, 55, 8,
           23, 24, 12, 11, 7, 9, 11, 12, 6, 7, 22, 5, 7, 24, 6, 11, 9, 6, 7, 22, 7, 11, 38, 7, 9, 8, 25, 11, 8,
           11, 9, 12, 8, 12, 5, 38, 5, 38, 5, 11, 7, 5, 6, 21, 6, 10, 53, 8, 7, 24, 10, 27, 44, 253, 253, 253,
           252, 252, 252, 13, 12, 45, 12, 45, 12, 61, 12, 45, 44, 173)
_LENLEN = (2, 35, 36, 53, 38, 23)
_DISTLEN = (2, 20, 53, 230, 247, 151, 248)
_BASE = (3, 2, 4, 5, 6, 7, 8, 9, 10, 12, 16, 24, 40, 72, 136, 264)
_EXTRA = (0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8)
_TABLES = []


def _huffman_table(rep):
    """(lookup table indexed by the next maxlen bits, LSB first: symbol << 4 | length, maxlen)."""
    lengths = []
    for b in rep:
        lengths += [b & 15] * ((b >> 4) + 1)
    maxlen = max(lengths)
    table = [0] * (1 << maxlen)
    code = 0
    for ln in range(1, maxlen + 1):
        for sym, sl in enumerate(lengths):
            if sl != ln:
                continue
            # the code's bits arrive most significant first, inverted
            v = 0
            for j in range(ln):
                v |= (((code >> (ln - 1 - j)) & 1) ^ 1) << j
            for hi in range(1 << (maxlen - ln)):
                table[v | (hi << ln)] = (sym << 4) | ln
            code += 1
        code <<= 1
    return table, maxlen


def blast(d, start=0, end=None):
    """Decompress PKWARE DCL data d[start:end]."""
    if not _TABLES:
        _TABLES.extend((_huffman_table(_LITLEN), _huffman_table(_LENLEN), _huffman_table(_DISTLEN)))
    (lit_t, lit_n), (len_t, len_n), (dist_t, dist_n) = _TABLES
    end = len(d) if end is None else end
    src = bytes(d[start:end]) + b"\x00" * 4
    if len(src) < 7:
        raise ValueError("too short")
    coded, dict_bits = src[0], src[1]
    if coded > 1 or not 4 <= dict_bits <= 6:
        raise ValueError("not DCL data")
    out = bytearray()
    bb, bc, i, n = 0, 0, 2, len(src)
    lit_m, len_m, dist_m = (1 << lit_n) - 1, (1 << len_n) - 1, (1 << dist_n) - 1
    while True:
        if bc < 24:
            while bc < 32 and i < n:
                bb |= src[i] << bc
                i += 1
                bc += 8
            if bc < 16:
                raise ValueError("ran out of data")
        flag = bb & 1
        bb >>= 1
        bc -= 1
        if flag:
            e = len_t[bb & len_m]
            sym, ln = e >> 4, e & 15
            bb >>= ln
            bc -= ln
            x = _EXTRA[sym]
            length = _BASE[sym] + (bb & ((1 << x) - 1))
            bb >>= x
            bc -= x
            if length == 519:
                break
            if bc < 16:
                while bc < 32 and i < n:
                    bb |= src[i] << bc
                    i += 1
                    bc += 8
            e = dist_t[bb & dist_m]
            dsym, ln = e >> 4, e & 15
            bb >>= ln
            bc -= ln
            s = 2 if length == 2 else dict_bits
            dist = (dsym << s) + (bb & ((1 << s) - 1)) + 1
            bb >>= s
            bc -= s
            st = len(out) - dist
            if st < 0:
                raise ValueError("distance too far back")
            if dist >= length:
                out += out[st:st + length]
            else:
                for k in range(length):
                    out.append(out[st + k])
        elif coded:
            e = lit_t[bb & lit_m]
            out.append(e >> 4)
            ln = e & 15
            bb >>= ln
            bc -= ln
        else:
            out.append(bb & 0xFF)
            bb >>= 8
            bc -= 8
    return bytes(out)
