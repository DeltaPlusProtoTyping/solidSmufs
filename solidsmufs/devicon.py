"""The icon of SolidSmurfs run from its scripts (not the built app): the usual cube with the version in a box at the bottom
right, the way SolidWorks puts its year on its icon, so this copy can be told from an installed one on the taskbar and
desktop.

    python -m solidsmufs.devicon [out.ico]     (writes the icon file the desktop shortcut uses; see ico_path)
"""

import os
import struct
import sys
from pathlib import Path

from . import __version__

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SOURCE = Path(__file__).resolve().parent / "web" / "img" / "solidsmurfs.ico"


def ico_path():
    """Where the badged icon file is kept: beside the app's other per-user files."""
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "SolidSmufs" / "SolidSmurfs-scripts.ico"


def label(version=__version__, size=256):
    """V and the version; the number alone on the taskbar's small sizes, where the V would only make it smaller."""
    return f"V{version}" if size >= 40 else version


def badged(size, text):
    """The icon at one size with text in a white box at the bottom right. Too small to read below 24 pixels, where an
    amber corner marks it instead."""
    from PySide6.QtCore import QRectF, QSize, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QImage, QPainter, QPainterPath, QPen

    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawPixmap(0, 0, QIcon(str(SOURCE)).pixmap(QSize(size, size)))
    navy = QColor("#14265a")  # (the tile's own navy)
    if size < 24:
        corner = QPainterPath()
        corner.moveTo(size, size * 0.45)
        corner.lineTo(size, size)
        corner.lineTo(size * 0.45, size)
        corner.closeSubpath()
        p.fillPath(corner, QColor("#f5a623"))
        p.end()
        return img
    font = QFont("Segoe UI")
    font.setBold(True)
    pad = max(1.0, size * 0.04)
    most_w, most_h = size * 0.92 - 2 * pad, size * 0.30 - 2 * pad
    px = max(6, int(most_h))
    while px > 6:
        font.setPixelSize(px)
        if QFontMetricsF(font).horizontalAdvance(text) <= most_w:
            break
        px -= 1
    font.setPixelSize(px)
    m = QFontMetricsF(font)
    w, h = m.horizontalAdvance(text) + 2 * pad, m.capHeight() + 2.6 * pad
    box = QRectF(size - w - size * 0.02, size - h - size * 0.02, w, h)
    edge = max(1.0, size / 64)
    p.setPen(QPen(navy, edge))
    p.setBrush(QColor("white"))
    p.drawRoundedRect(box.adjusted(edge / 2, edge / 2, -edge / 2, -edge / 2), h * 0.18, h * 0.18)
    p.setFont(font)
    p.setPen(navy)
    p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return img


def icon(version=__version__):
    """A QIcon with the badge at every size Windows asks for (a QGuiApplication must exist)."""
    from PySide6.QtGui import QIcon, QPixmap

    out = QIcon()
    for s in SIZES:
        out.addPixmap(QPixmap.fromImage(badged(s, label(version, s))))
    return out


def ico_bytes(version=__version__):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    images = []
    for s in SIZES:
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        badged(s, label(version, s)).save(buf, "PNG")
        images.append((s, bytes(data)))
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for s, data in images:
        dim = 0 if s >= 256 else s
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return out + b"".join(d for _, d in images)


def write_ico(path=None, version=__version__):
    """Writes the badged icon file if it's missing or shows another version; returns its path."""
    path = Path(path or ico_path())
    stamp = path.with_suffix(".version")
    if path.is_file() and stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == version:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ico_bytes(version))
    stamp.write_text(version, encoding="utf-8")
    return path


if __name__ == "__main__":
    if sys.platform != "win32":  # (Windows draws with its own fonts and shows no window; offscreen has no fonts there)
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication(sys.argv[:1])
    print(write_ico(sys.argv[1] if len(sys.argv) > 1 else None))
