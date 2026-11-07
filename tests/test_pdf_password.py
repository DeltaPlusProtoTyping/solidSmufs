"""Protected PDFs. Each test file is ciphered here and handed to PDFium, an independent reader: if it opens and finds the
page's text, the keys and ciphers agree with what real PDFs use. The model stream is then fetched by our own code."""

import hashlib
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from solidsmufs.formats import pdfcrypt, pdfstreams  # noqa: E402
from solidsmufs.kernel import formats  # noqa: E402
from solidsmufs.kernel.pdfdoc import PdfFile  # noqa: E402

MODEL = b"U3D\0pretend this is a model"
PAGE = b"BT /F1 24 Tf 72 700 Td (HELLO SMURFS) Tj ET"
ID = bytes(range(16))
OWNER = "owner-pw"


def hexa(b):
    return b"<" + b.hex().encode() + b">"


def pad(data):
    n = 16 - len(data) % 16
    return data + bytes([n]) * n


def legacy(password, owner, revision, bits, flags=-44):
    """The /O and /U of revisions 2 to 4, and the key: the standard's algorithms 2 to 5, written out on their own here."""
    size = bits // 8
    d = hashlib.md5(pdfcrypt._padded(owner.encode())).digest()
    if revision >= 3:
        for _ in range(50):
            d = hashlib.md5(d).digest()
    o = pdfcrypt.rc4(d[:size], pdfcrypt._padded(password.encode()))
    if revision >= 3:
        for i in range(1, 20):
            o = pdfcrypt.rc4(bytes(b ^ i for b in d[:size]), o)
    k = hashlib.md5(pdfcrypt._padded(password.encode()) + o + struct.pack("<i", flags) + ID).digest()
    if revision >= 3:
        for _ in range(50):
            k = hashlib.md5(k[:size]).digest()
    key = k[:size]
    if revision == 2:
        u = pdfcrypt.rc4(key, pdfcrypt._PAD)
    else:
        u = pdfcrypt.rc4(key, hashlib.md5(pdfcrypt._PAD + ID).digest())
        for i in range(1, 20):
            u = pdfcrypt.rc4(bytes(b ^ i for b in key), u)
        u += bytes(16)
    return o, u, key


def build(kind, password):
    """A one-page PDF with a text page and a U3D stream, encrypted one way."""
    if kind in ("rc4-40", "rc4-128", "aes-128"):
        revision, bits = {"rc4-40": (2, 40), "rc4-128": (3, 128), "aes-128": (4, 128)}[kind]
        o, u, key = legacy(password, OWNER, revision, bits)
        if kind == "aes-128":
            head = b"/V 4/R 4/Length 128/CF<</StdCF<</CFM/AESV2/Length 16/AuthEvent/DocOpen>>>>/StmF/StdCF/StrF/StdCF"
        elif kind == "rc4-128":
            head = b"/V 2/R 3/Length 128"
        else:
            head = b"/V 1/R 2/Length 40"
        extra = b""

        def cipher(n, data):
            material = key + struct.pack("<I", n)[:3] + b"\0\0" + (b"sAlT" if kind == "aes-128" else b"")
            k = hashlib.md5(material).digest()[:min(len(key) + 5, 16)]
            if kind == "aes-128":
                iv = bytes(range(32, 48))
                return iv + pdfcrypt.aes_cbc_encrypt(k, iv, pad(data))
            return pdfcrypt.rc4(k, data)
    else:  # AES-256, revision 6
        key = bytes(range(100, 132))
        pw, own = password.encode(), OWNER.encode()
        vs, ks = b"valsalt1", b"keysalt1"
        u = pdfcrypt._hash_r6(pw, vs) + vs + ks
        ue = pdfcrypt.aes_cbc_encrypt(pdfcrypt._hash_r6(pw, ks), bytes(16), key)
        ovs, oks = b"valsalt2", b"keysalt2"
        o = pdfcrypt._hash_r6(own, ovs, u) + ovs + oks
        oe = pdfcrypt.aes_cbc_encrypt(pdfcrypt._hash_r6(own, oks, u), bytes(16), key)
        perms = pdfcrypt.aes_cbc_encrypt(key, bytes(16), struct.pack("<i", -44) + b"\xff\xff\xff\xffTadb" + b"abcd")
        head = (b"/V 5/R 6/Length 256/CF<</StdCF<</CFM/AESV3/Length 32/AuthEvent/DocOpen>>>>/StmF/StdCF/StrF/StdCF"
                b"/OE" + hexa(oe) + b"/UE" + hexa(ue) + b"/Perms" + hexa(perms))
        extra = b""

        def cipher(n, data):
            iv = bytes(range(32, 48))
            return iv + pdfcrypt.aes_cbc_encrypt(key, iv, pad(data))

    objs = {
        1: b"<</Type/Catalog/Pages 2 0 R>>",
        2: b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        3: b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>>>>>>>",
    }
    page, model = cipher(4, PAGE), cipher(5, MODEL)
    objs[4] = b"<</Length %d>>stream\n%s\nendstream" % (len(page), page)
    objs[5] = b"<</Type/3D/Subtype/U3D/Length %d>>stream\n%s\nendstream" % (len(model), model)
    objs[6] = b"<</Filter/Standard" + head + b"/O" + hexa(o) + b"/U" + hexa(u) + b"/P -44" + extra + b">>"
    out, offsets = b"%PDF-1.7\n", {}
    for n in sorted(objs):
        offsets[n] = len(out)
        out += b"%d 0 obj\n" % n + objs[n] + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 7\n0000000000 65535 f \n" + b"".join(b"%010d 00000 n \n" % offsets[n] for n in sorted(objs))
    out += b"trailer<</Size 7/Root 1 0 R/Encrypt 6 0 R/ID[" + hexa(ID) + hexa(ID) + b"]>>\nstartxref\n%d\n%%%%EOF\n" % xref
    return out


KINDS = ("rc4-40", "rc4-128", "aes-128", "aes-256")


class Ciphers(unittest.TestCase):
    def test_aes_known_answers(self):
        """The standard's own examples (FIPS 197, appendix C)."""
        plain = bytes.fromhex("00112233445566778899aabbccddeeff")
        for size, answer in ((16, "69c4e0d86a7b0430d8cdb78070b4c55a"), (32, "8ea2b7ca516745bfeafc49904b496089")):
            key = bytes(range(size))
            self.assertEqual(pdfcrypt.aes_cbc_encrypt(key, bytes(16), plain).hex(), answer)
            self.assertEqual(pdfcrypt.aes_cbc_decrypt(key, bytes(16), bytes.fromhex(answer)), plain)

    def test_rc4_known_answer(self):
        self.assertEqual(pdfcrypt.rc4(b"Key", b"Plaintext").hex(), "bbf316e8d940af0ad3")

    def test_cbc_chains_blocks(self):
        key, iv = bytes(range(16)), bytes(range(16, 32))
        data = bytes(range(64))
        self.assertEqual(pdfcrypt.aes_cbc_decrypt(key, iv, pdfcrypt.aes_cbc_encrypt(key, iv, data)), data)

    def test_literal_strings_with_escapes(self):
        self.assertEqual(pdfcrypt._string(rb"/O (a\(b\)\n\101\\c(d))", b"O"), b"a(b)\nA\\c(d)")


class Protected(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def file(self, kind, password):
        p = Path(self.dir.name) / f"{kind}.pdf"
        p.write_bytes(build(kind, password))
        return p

    def opened(self, path, password):
        doc = PdfFile(str(path), password)
        self.addCleanup(doc.close)
        return doc

    def test_pdfium_agrees_the_file_is_properly_ciphered(self):
        for kind in KINDS:
            with self.subTest(kind):
                doc = self.opened(self.file(kind, "secret"), "secret")
                self.assertTrue(doc.find("HELLO SMURFS"), "the page's text wasn't found")

    def test_no_password_and_a_wrong_one_say_different_things(self):
        for kind in KINDS:
            with self.subTest(kind):
                p = self.file(kind, "secret")
                with self.assertRaisesRegex(ValueError, formats.PASSWORD_NEEDED):
                    PdfFile(str(p))
                with self.assertRaisesRegex(ValueError, formats.PASSWORD_WRONG):
                    PdfFile(str(p), "nope")

    def test_the_model_comes_out_with_the_password(self):
        for kind in KINDS:
            with self.subTest(kind):
                data = self.file(kind, "secret").read_bytes()
                self.assertEqual(pdfstreams.model_streams(data, b"U3D", b"U3D\0", "secret"), [MODEL])

    def test_the_owners_password_opens_it_too(self):
        for kind in KINDS:
            with self.subTest(kind):
                data = self.file(kind, "secret").read_bytes()
                self.assertEqual(pdfstreams.model_streams(data, b"U3D", b"U3D\0", OWNER), [MODEL])

    def test_no_model_comes_out_with_the_wrong_password(self):
        for kind in KINDS:
            with self.subTest(kind):
                data = self.file(kind, "secret").read_bytes()
                self.assertEqual(pdfstreams.model_streams(data, b"U3D", b"U3D\0", "nope"), [])

    def test_encrypted_but_needing_no_password_just_opens(self):
        """Common for CAD exports: restricted, not secret."""
        for kind in KINDS:
            with self.subTest(kind):
                p = self.file(kind, "")
                self.assertTrue(self.opened(p, "").find("HELLO SMURFS"))
                self.assertEqual(pdfstreams.model_streams(p.read_bytes(), b"U3D", b"U3D\0"), [MODEL])


if __name__ == "__main__":
    unittest.main()
