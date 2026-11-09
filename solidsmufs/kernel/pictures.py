"""Pictures shown as pages: image files (each page of a multi-page TIFF its own page), and the preview pictures
stored inside SolidWorks drawings, eDrawings files and DWG drawings. They're shown by the PDF page view, so
this answers the same calls as pdfdoc.PdfFile: pages(), title(), tile(), select() and find().

Pictures are decoded by Qt (PNG, JPEG, BMP, GIF, TIFF, WebP, TGA) in the document's worker."""

import io
import os
import struct
import zipfile
from pathlib import Path

import numpy as np

from .pdfdoc import _qt

POINTS_PER_PX = 72 / 96  # a picture's pixel is a screen pixel at 100% (the page view shows 96/72 px per point)


class PictureError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------- previews
def sw_preview(path):
    """The PNG (else the BMP) a SolidWorks file keeps of how it looks when last saved."""
    from ..formats.parasolid.containers import sw_streams
    try:
        streams = sw_streams(path, lambda n: n in ("PreviewPNG", "Preview"))
    except Exception:
        streams = {}
    if streams.get("PreviewPNG", b"")[:4] == b"\x89PNG":
        return streams["PreviewPNG"]
    if "Preview" in streams:
        return _dib_to_bmp(streams["Preview"])
    raise PictureError("This SolidWorks drawing has no preview picture in it, so there's nothing to show. "
                       "(Its sheets themselves can only be drawn by SolidWorks.)")


def edrawings_preview(path):
    """eDrawings files from 2008 on hold a zip archive with a preview.jpg; earlier ones (HOOPS stream files
    alone) hold no picture at all."""
    data = Path(path).read_bytes()
    at = data.find(b"PK\x03\x04")
    if at >= 0:
        try:
            with zipfile.ZipFile(io.BytesIO(data[at:])) as z:
                for name in z.namelist():
                    if name.lower().startswith("preview.") and name.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                        return z.read(name)
        except zipfile.BadZipFile:
            pass
    raise PictureError("This eDrawings file has no preview picture in it (files saved before eDrawings 2008 "
                       "don't), and its 3D model can't be read yet.")


def dwg_preview(path):
    """The thumbnail AutoCAD keeps at the front of a DWG (R13 and later): a PNG, else a BMP."""
    data = Path(path).read_bytes()
    if len(data) < 0x20 or not data.startswith(b"AC10"):
        raise PictureError("This doesn't look like a DWG drawing.")
    start = struct.unpack_from("<I", data, 0x0D)[0]
    # the image section opens with a sentinel, its size, and a count of entries: (code, start, size) each
    if start and start + 21 < len(data):
        count = data[start + 20]
        p = start + 21
        found = {}
        for _ in range(min(count, 8)):
            if p + 9 > len(data):
                break
            code, at, size = data[p], *struct.unpack_from("<II", data, p + 1)
            found[code] = (at, size)
            p += 9
        for code in (6, 2):  # 6: PNG; 2: BMP (a DIB with no file header)
            if code in found:
                at, size = found[code]
                blob = data[at:at + size]
                if code == 6 and blob[:4] == b"\x89PNG":
                    return blob
                if code == 2 and len(blob) > 40:
                    return _dib_to_bmp(blob)
    raise PictureError("This DWG has no preview picture in it.")


def _dib_to_bmp(dib):
    """A Windows DIB (a BMP without its 14-byte file header) made into a BMP file."""
    if dib[:2] == b"BM":
        return dib
    head, bits, used = struct.unpack_from("<I", dib, 0)[0], struct.unpack_from("<H", dib, 14)[0], struct.unpack_from("<I", dib, 32)[0]
    palette = (used or (1 << bits if bits <= 8 else 0)) * 4
    return b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, 14 + head + palette) + dib


# ---------------------------------------------------------------------------------------------- the pages
class Picture:
    def __init__(self, path, data=None, title=""):
        """`data`: the picture's bytes when it comes from inside another file (a small preview, smoothed when it's
        shown bigger); else the file itself is read (shown pixel for pixel close up)."""
        _qt()
        self.smooth = data is not None
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QImageReader
        self._title = title
        self._bytes = QByteArray(data if data is not None else Path(path).read_bytes())
        buf = QBuffer(self._bytes)
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buf)
        reader.setAutoTransform(True)  # a phone photo the right way up
        reader.setAllocationLimit(2048)  # MB: big scans are fine, a damaged size isn't
        fmt = bytes(reader.format()).decode()
        if not fmt:
            raise PictureError("This picture can't be read (it may be damaged, or in a kind Qt doesn't know).")
        pages = reader.imageCount() if fmt == "tiff" else 1  # a GIF's later images are animation, not pages
        self.images = []
        for i in range(max(pages, 1)):
            if i and not reader.jumpToImage(i):
                break
            img = reader.read()
            if img.isNull():
                if not self.images:
                    raise PictureError(f"This picture can't be read: {reader.errorString()}.")
                break
            self.images.append(self._prepare(img))
        buf.close()
        self.levels = [None] * len(self.images)
        self.format = {"jpg": "JPEG", "tif": "TIFF"}.get(fmt, fmt.upper())

    @staticmethod
    def _prepare(img):
        from PySide6.QtGui import QImage
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    def close(self):
        self.images = []

    def pages(self):
        return [{"w": round(im.width() * POINTS_PER_PX, 3), "h": round(im.height() * POINTS_PER_PX, 3), "label": str(i + 1)}
                for i, im in enumerate(self.images)]

    def title(self):
        return self._title

    def size_text(self):
        im = self.images[0]
        text = f"{im.width()} × {im.height()} pixels"
        return text + (f", {len(self.images)} pages" if len(self.images) > 1 else "")

    def _level(self, page, k):
        """The picture halved enough times for drawing it `k` times its size: (image, how much smaller it is)."""
        if self.levels[page] is None:
            from PySide6.QtCore import Qt
            chain, im = [self.images[page]], self.images[page]
            while min(im.width(), im.height()) > 256:
                im = im.scaled(max(im.width() // 2, 1), max(im.height() // 2, 1), Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                chain.append(im)
            self.levels[page] = chain
        chain, n = self.levels[page], 0
        while n + 1 < len(chain) and k * (2 ** (n + 1)) <= 1.0:
            n += 1
        return chain[n], 2 ** n

    def tile(self, page, scale, x, y, w, h, turns=0):
        """RGBA pixels of a piece of a page drawn at `scale` pixels per point, turned by `turns` quarter turns
        clockwise: (x, y) is the piece's corner on the whole drawn page. As pdfdoc.PdfFile.tile."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QPainter, QTransform
        if not 0 <= page < len(self.images):
            raise ValueError("No such page.")
        full = self.images[page]
        k = scale * POINTS_PER_PX  # drawn pixels per picture pixel
        src, shrink = self._level(page, k)
        kk = k * shrink
        wu, hu = full.width() * k, full.height() * k  # the whole drawn picture, before turning
        out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(Qt.GlobalColor.white)  # on white paper, like a PDF page
        t = QTransform()
        t.translate(-x, -y)
        turns %= 4
        if turns == 1:
            t.translate(hu, 0)
        elif turns == 2:
            t.translate(wu, hu)
        elif turns == 3:
            t.translate(0, wu)
        t.rotate(90 * turns)
        t.scale(kk, kk)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.smooth or kk < 2.0)  # close up: crisp pixels, as they are
        p.setTransform(t)
        p.drawImage(0, 0, src)
        p.end()
        raw = np.frombuffer(out.constBits(), np.uint8, out.sizeInBytes()).reshape(h, out.bytesPerLine() // 4, 4)
        px = raw[:, :w, [2, 1, 0, 3]].copy()  # Qt keeps BGRA in memory
        px[..., 3] = 255
        return px.tobytes()

    # a picture has no text to pick or find
    def page_text(self, page):
        return ""

    def select(self, page, ax, ay, bx, by):
        return {"text": "", "rects": []}

    def find(self, query, limit=1000):
        return []


def open_picture(path, ext):
    """(Picture, what the file is) for an image file or a file whose preview picture is shown."""
    from .formats import EDRAWINGS_FORMATS, IMAGE_FORMATS, SW_DRAWING_FORMATS
    name = Path(path).name
    if ext in IMAGE_FORMATS:
        pic = Picture(path, title=name)
        return pic, f"{pic.format} picture"
    if ext in SW_DRAWING_FORMATS:
        return Picture(path, sw_preview(path), name), "SolidWorks drawing (its preview picture)"
    if ext in EDRAWINGS_FORMATS:
        return Picture(path, edrawings_preview(path), name), "eDrawings file (its preview picture)"
    if ext == ".dwg":
        return Picture(path, dwg_preview(path), name), "DWG drawing (its preview picture)"
    raise PictureError(f"Can't show {ext} files.")


def dwg_converter():
    """The ODA File Converter, if it's here: it turns DWG into DXF. It's looked for unpacked in SolidSmurfs' own
    folder (no admin needed: msiexec /a the installer with TARGETDIR there), then installed in Program Files."""
    own = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "SolidSmufs" / "ODAFileConverter" / "ODAFileConverter.exe"
    if own.is_file():
        return own
    roots = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
    for root in roots:
        base = Path(root) / "ODA"
        if base.is_dir():
            for exe in sorted(base.glob("ODAFileConverter*/ODAFileConverter.exe"), reverse=True):
                return exe
    return None
