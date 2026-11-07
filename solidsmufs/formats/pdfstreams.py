"""Fetching 3D model streams out of a PDF's bytes. The PDF standard keeps stream dictionaries out of compressed object
streams, so they can be found in plain sight even in an encrypted file: only the stream's own bytes are ciphered.
"""

import re
import zlib

from .pdfcrypt import decryptor


def _stream_length(info, data):
    m = re.search(rb"/Length\s+(\d+)(\s+\d+\s+R)?", info)
    if not m:
        return None
    if not m.group(2):
        return int(m.group(1))
    held = re.search(rb"(?:^|[\r\n\s])" + m.group(1) + rb"\s+\d+\s+obj\s*(\d+)", data)  # /Length n 0 R
    return int(held.group(1)) if held else None


def model_streams(data, subtype, magic, password=""):
    """The streams of /Subtype `subtype` starting with `magic`, in file order, undone of any encryption."""
    opener = decryptor(data, password)
    out = []
    for m in re.finditer(rb"/Subtype\s*/" + subtype + rb"\b", data):
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
        if opener is not None:
            label = re.search(rb"(\d+)\s+(\d+)\s*$", data[max(0, start - 24):start])
            if label is None:
                continue
            raw = opener.stream(int(label.group(1)), int(label.group(2)), raw)
        if b"FlateDecode" in info or b"/Fl" in info:
            try:
                raw = zlib.decompressobj().decompress(raw)
            except zlib.error:
                continue
        if raw[:len(magic)] == magic:
            out.append(raw)
    return out
