"""Make the app icon: a Wagner "WM" monogram (W over M, Volkhov Bold) on brushed navy.

Writes web/img/icon.ico (all the sizes Windows asks for) and web/img/icon-256.png.

    .venv\\Scripts\\python tools\\make_icon.py path\\to\\Volkhov-Bold.ttf
"""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QGuiApplication, QImage, QLinearGradient,  # noqa: E402
                           QPainter, QPainterPath, QPen)

IMG = Path(__file__).resolve().parents[1] / "solidsmufs" / "web" / "img"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
NAVY, NAVY_DARK = QColor("#213367"), QColor("#14265a")


def draw(size, family):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    s = size / 256
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 46 * s, 46 * s)
    g = QLinearGradient(QPointF(0, 0), QPointF(0, size))
    g.setColorAt(0, QColor("#2c4486"))
    g.setColorAt(1, NAVY_DARK)
    p.fillPath(tile, g)
    if size >= 32:  # a thin steel rim
        p.setPen(QPen(QColor(200, 210, 225, 120), max(1.0, 3 * s)))
        p.drawPath(tile)
    # W over M, overlapping a little like the company mark
    font = QFont(family)
    font.setBold(True)
    font.setPixelSize(int(round(128 * s)))
    p.setFont(font)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(0, 22 * s, size, 120 * s), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, "W")
    p.drawText(QRectF(0, 112 * s, size, 120 * s), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, "M")
    p.end()
    return img


def png_bytes(img):
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def main(ttf):
    QGuiApplication(sys.argv[:1])
    fid = QFontDatabase.addApplicationFont(ttf)
    family = QFontDatabase.applicationFontFamilies(fid)[0] if fid >= 0 else "Georgia"
    images = [(s, png_bytes(draw(s, family))) for s in SIZES]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for size, data in images:
        dim = 0 if size >= 256 else size
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out += b"".join(d for _, d in images)
    (IMG / "icon.ico").write_bytes(out)
    (IMG / "icon-256.png").write_bytes(images[-1][1])
    print("wrote", IMG / "icon.ico", "and icon-256.png using", family)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "Volkhov-Bold.ttf")
