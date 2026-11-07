"""Opening the encrypted streams of a PDF, per the standard security handler of ISO 32000-1 and -2 (revisions 2 to 6: RC4,
AES-128 and AES-256). PDFium draws the pages, but the 3D models have to be fetched from the file's bytes ourselves.
A PDF can be encrypted and still open with no password at all, which is common for CAD exports with restricted printing.
"""

import hashlib
import re
import struct

import numpy as np

_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


# ---------------------------------------------------------------------------------------------- ciphers
def rc4(key, data):
    s = list(range(256))
    j = 0
    size = len(key)
    for i in range(256):
        j = (j + s[i] + key[i % size]) & 255
        s[i], s[j] = s[j], s[i]
    out = bytearray(len(data))
    i = j = 0
    for n, byte in enumerate(data):
        i = (i + 1) & 255
        a = s[i]
        j = (j + a) & 255
        b = s[j]
        s[i], s[j] = b, a
        out[n] = byte ^ s[(a + b) & 255]
    return bytes(out)


def _tables():
    sbox = [0] * 256
    p = q = 1
    while True:  # walk the multiplicative group: q stays the inverse of p
        p = p ^ ((p << 1) & 255) ^ (0x1B if p & 0x80 else 0)
        q ^= (q << 1) & 255
        q ^= (q << 2) & 255
        q ^= (q << 4) & 255
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) & 255 ^ ((q << 2) | (q >> 6)) & 255 ^ ((q << 3) | (q >> 5)) & 255 ^ ((q << 4) | (q >> 4)) & 255
        sbox[p] = x ^ 0x63
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox


_SBOX = _tables()
_INV = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV[_v] = _i


def _times(a, b):
    out = 0
    while b:
        if b & 1:
            out ^= a
        a = ((a << 1) & 255) ^ (0x1B if a & 0x80 else 0)
        b >>= 1
    return out


_M2, _M3 = [_times(i, 2) for i in range(256)], [_times(i, 3) for i in range(256)]
_NP_INV = np.array(_INV, np.uint8)
_NP_9 = np.array([_times(i, 9) for i in range(256)], np.uint8)
_NP_11 = np.array([_times(i, 11) for i in range(256)], np.uint8)
_NP_13 = np.array([_times(i, 13) for i in range(256)], np.uint8)
_NP_14 = np.array([_times(i, 14) for i in range(256)], np.uint8)
_INV_SHIFT = np.array([0, 13, 10, 7, 4, 1, 14, 11, 8, 5, 2, 15, 12, 9, 6, 3])
_SHIFT = (0, 5, 10, 15, 4, 9, 14, 3, 8, 13, 2, 7, 12, 1, 6, 11)


def _round_keys(key):
    """The expanded key, a list of 16-byte round keys."""
    nk = len(key) // 4
    rounds = nk + 6
    words = [list(key[i * 4:i * 4 + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (rounds + 1)):
        w = list(words[i - 1])
        if i % nk == 0:
            w = [_SBOX[w[1]] ^ rcon, _SBOX[w[2]], _SBOX[w[3]], _SBOX[w[0]]]
            rcon = _M2[rcon]
        elif nk > 6 and i % nk == 4:
            w = [_SBOX[b] for b in w]
        words.append([a ^ b for a, b in zip(w, words[i - nk])])
    return [sum(words[i:i + 4], []) for i in range(0, len(words), 4)]


def aes_cbc_encrypt(key, iv, data):
    """Whole blocks, one after another: the password hash of revision 6 needs this, on short runs of data."""
    keys = _round_keys(key)
    out = bytearray()
    prev = list(iv)
    s, m2, m3 = _SBOX, _M2, _M3
    for at in range(0, len(data), 16):
        st = [data[at + i] ^ prev[i] ^ keys[0][i] for i in range(16)]
        for rk in keys[1:-1]:
            t = [s[st[j]] for j in _SHIFT]
            st = [0] * 16
            for c in (0, 4, 8, 12):
                a, b, d, e = t[c], t[c + 1], t[c + 2], t[c + 3]
                st[c] = m2[a] ^ m3[b] ^ d ^ e ^ rk[c]
                st[c + 1] = a ^ m2[b] ^ m3[d] ^ e ^ rk[c + 1]
                st[c + 2] = a ^ b ^ m2[d] ^ m3[e] ^ rk[c + 2]
                st[c + 3] = m3[a] ^ b ^ d ^ m2[e] ^ rk[c + 3]
        last = keys[-1]
        prev = [s[st[j]] ^ last[n] for n, j in enumerate(_SHIFT)]
        out += bytes(prev)
    return bytes(out)


def aes_cbc_decrypt(key, iv, data):
    """Whole blocks. Every block can be undone on its own, so it goes through all at once: a model is megabytes long."""
    size = len(data) // 16 * 16
    if not size:
        return b""
    keys = [np.array(k, np.uint8) for k in _round_keys(key)]
    blocks = np.frombuffer(data, np.uint8, size).reshape(-1, 16)
    st = blocks ^ keys[-1]
    for rk in reversed(keys[1:-1]):
        st = _NP_INV[st[:, _INV_SHIFT]] ^ rk
        a, b, c, d = st[:, 0::4], st[:, 1::4], st[:, 2::4], st[:, 3::4]
        st = np.stack([_NP_14[a] ^ _NP_11[b] ^ _NP_13[c] ^ _NP_9[d], _NP_9[a] ^ _NP_14[b] ^ _NP_11[c] ^ _NP_13[d],
                       _NP_13[a] ^ _NP_9[b] ^ _NP_14[c] ^ _NP_11[d], _NP_11[a] ^ _NP_13[b] ^ _NP_9[c] ^ _NP_14[d]], axis=2).reshape(-1, 16)
    st = _NP_INV[st[:, _INV_SHIFT]] ^ keys[0]
    before = np.vstack([np.frombuffer(iv, np.uint8)[None], blocks[:-1]])
    return (st ^ before).tobytes()


def _unpad(data):
    if data and 1 <= data[-1] <= 16:
        return data[:-data[-1]]
    return data


# ---------------------------------------------------------------------------------------------- the encryption dictionary
def _string(info, name):
    """A string's bytes from a dictionary: <hex> or (literal), both legal for these fields."""
    m = re.search(rb"/" + name + rb"\s*(<|\()", info)
    if not m:
        return None
    at = m.end()
    if m.group(1) == b"<":
        end = info.find(b">", at)
        text = re.sub(rb"\s", b"", info[at:end])
        return bytes.fromhex((text + (b"0" if len(text) % 2 else b"")).decode("ascii"))
    out, depth = bytearray(), 1
    escapes = {110: 10, 114: 13, 116: 9, 98: 8, 102: 12}
    while at < len(info):
        c = info[at]
        at += 1
        if c == 92:  # backslash
            c = info[at]
            at += 1
            if 48 <= c <= 55:
                code = c - 48
                for _ in range(2):
                    if 48 <= info[at] <= 55:
                        code = code * 8 + info[at] - 48
                        at += 1
                out.append(code & 255)
            elif c in escapes:
                out.append(escapes[c])
            elif c == 13:
                if info[at] == 10:
                    at += 1
            elif c != 10:
                out.append(c)
            continue
        if c == 40:
            depth += 1
        elif c == 41:
            depth -= 1
            if not depth:
                break
        out.append(c)
    return bytes(out)


def _number(info, name, default=None):
    m = re.search(rb"/" + name + rb"\s+(-?\d+)", info)
    return int(m.group(1)) if m else default


def _object(data, number, generation):
    at = None
    for m in re.finditer(rb"(?:^|[\s>])" + str(number).encode() + rb"\s+" + str(generation).encode() + rb"\s+obj\b", data):
        at = m.end()  # the last version of an object wins
    if at is None:
        return None
    end = data.find(b"endobj", at)
    return data[at:end if end >= 0 else None]


def _dictionary(data):
    """The encryption dictionary and the file's first ID, or None for a PDF that isn't encrypted."""
    refs = list(re.finditer(rb"/Encrypt\s+(\d+)\s+(\d+)\s+R", data))
    if refs:
        info = _object(data, int(refs[-1].group(1)), int(refs[-1].group(2)))
        skip = (int(refs[-1].group(1)), int(refs[-1].group(2)))
    else:
        direct = list(re.finditer(rb"/Encrypt\s*<<", data))
        if not direct:
            return None
        info, skip = data[direct[-1].end():direct[-1].end() + 4096], None
    if info is None:
        return None
    ids = list(re.finditer(rb"/ID\s*\[\s*(<[^>]*>|\()", data))
    first = b""
    if ids:
        first = _string(b"/ID " + data[ids[-1].start(1):ids[-1].start(1) + 512], b"ID") or b""
    return info, first, skip


def _method(info):
    """How streams are ciphered: "RC4", "AES" or "NONE"."""
    version = _number(info, b"V", 0)
    if version < 4:
        return "RC4"
    m = re.search(rb"/StmF\s*/(\w+)", info)
    name = m.group(1) if m else b"Identity"
    if name == b"Identity":
        return "NONE"
    filt = re.search(rb"/" + name + rb"\s*<<(.*?)>>", info, re.S)
    how = re.search(rb"/CFM\s*/(\w+)", filt.group(1)) if filt else None
    kind = how.group(1) if how else b"None"
    return {b"V2": "RC4", b"AESV2": "AES", b"AESV3": "AES"}.get(kind, "NONE")


# ---------------------------------------------------------------------------------------------- the file key
def _padded(password):
    return (password + _PAD)[:32]


def _legacy_key(password, info, first_id):
    """Revisions 2 to 4: the key from the user's password."""
    revision = _number(info, b"R", 2)
    size = _number(info, b"Length", 40) // 8 if revision > 2 else 5
    if not 5 <= size <= 16:
        size = 16 if revision > 3 else 5
    if _number(info, b"V", 0) >= 4:
        size = 16
    md = hashlib.md5(_padded(password) + _string(info, b"O")[:32] + struct.pack("<I", _number(info, b"P", 0) & 0xFFFFFFFF) + first_id)
    if revision >= 4 and re.search(rb"/EncryptMetadata\s+false", info):
        md.update(b"\xff\xff\xff\xff")
    key = md.digest()
    if revision >= 3:
        for _ in range(50):
            key = hashlib.md5(key[:size]).digest()
    return key[:size]


def _legacy_user_matches(key, info, first_id):
    revision = _number(info, b"R", 2)
    stored = _string(info, b"U") or b""
    if revision == 2:
        return rc4(key, _PAD) == stored[:32]
    out = rc4(key, hashlib.md5(_PAD + first_id).digest())
    for i in range(1, 20):
        out = rc4(bytes(b ^ i for b in key), out)
    return out[:16] == stored[:16]


def _legacy_user_password(owner, info):
    """Revisions 2 to 4: the owner's password unlocks the user's, which is stored ciphered by it."""
    revision = _number(info, b"R", 2)
    size = _number(info, b"Length", 40) // 8 if revision > 2 else 5
    if _number(info, b"V", 0) >= 4:
        size = 16
    digest = hashlib.md5(_padded(owner)).digest()
    if revision >= 3:
        for _ in range(50):
            digest = hashlib.md5(digest).digest()
    key = digest[:size]
    stored = _string(info, b"O")[:32]
    if revision == 2:
        return rc4(key, stored)
    for i in range(19, -1, -1):
        stored = rc4(bytes(b ^ i for b in key), stored)
    return stored


def _hash_r6(password, salt, extra=b""):
    """The password hash of ISO 32000-2, algorithm 2.B."""
    key = hashlib.sha256(password + salt + extra).digest()
    n = 0
    while True:
        run = (password + key + extra) * 64
        cipher = aes_cbc_encrypt(key[:16], key[16:32], run)
        kind = sum(cipher[:16]) % 3
        key = (hashlib.sha256, hashlib.sha384, hashlib.sha512)[kind](cipher).digest()
        n += 1
        if n >= 64 and cipher[-1] <= n - 32:
            return key[:32]


def _key_r5(password, info):
    """Revisions 5 and 6: the file key is stored ciphered by a hash of the password, or None if the password is wrong."""
    revision = _number(info, b"R", 5)
    password = password[:127]
    u, o = _string(info, b"U") or b"", _string(info, b"O") or b""
    ue, oe = _string(info, b"UE") or b"", _string(info, b"OE") or b""
    if revision >= 6:
        hashed = _hash_r6
    else:
        def hashed(pw, salt, extra=b""):
            return hashlib.sha256(pw + salt + extra).digest()
    if hashed(password, u[32:40]) == u[:32]:
        return aes_cbc_decrypt(hashed(password, u[40:48]), bytes(16), ue[:32])
    extra = u[:48]
    if hashed(password, o[32:40], extra) == o[:32]:
        return aes_cbc_decrypt(hashed(password, o[40:48], extra), bytes(16), oe[:32])
    return None


class Decryptor:
    """Undoes the encryption of a stream, given the object it's in."""

    def __init__(self, key, method, version):
        self.key, self.method, self.version = key, method, version

    def stream(self, number, generation, data):
        if self.method == "NONE":
            return data
        if self.version >= 5:
            return _unpad(aes_cbc_decrypt(self.key, data[:16], data[16:]))
        material = self.key + struct.pack("<I", number)[:3] + struct.pack("<H", generation)[:2]
        if self.method == "AES":
            material += b"sAlT"
        key = hashlib.md5(material).digest()[:min(len(self.key) + 5, 16)]
        if self.method == "AES":
            return _unpad(aes_cbc_decrypt(key, data[:16], data[16:]))
        return rc4(key, data)


def decryptor(data, password=""):
    """What opens this PDF's streams, or None when they aren't encrypted or the password doesn't open them."""
    found = _dictionary(data)
    if found is None:
        return None
    info, first_id, _skip = found
    if b"/Standard" not in info:
        return None
    method, version = _method(info), _number(info, b"V", 0)
    raw = password.encode("utf-8") if version >= 5 else password.encode("latin-1", "replace")
    if version >= 5:
        key = _key_r5(raw, info)
        return Decryptor(key, method, version) if key else None
    key = _legacy_key(raw, info, first_id)
    if not _legacy_user_matches(key, info, first_id):
        key = _legacy_key(_legacy_user_password(raw, info), info, first_id)
        if not _legacy_user_matches(key, info, first_id):
            return None
    return Decryptor(key, method, version)
