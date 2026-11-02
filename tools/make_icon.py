"""Make the app icon from web/img/icon.svg (the SolidSmurfs cube: blue, an S on each side face, on Wagner
navy).

Writes web/img/icon.ico (all the sizes Windows asks for) and web/img/icon-256.png.

    .venv\\Scripts\\python tools\\make_icon.py
"""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

IMG = Path(__file__).resolve().parents[1] / "solidsmufs" / "web" / "img"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def draw(renderer, size):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return img


def png_bytes(img):
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def main():
    QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(IMG / "icon.svg"))
    images = [(s, png_bytes(draw(renderer, s))) for s in SIZES]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for size, data in images:
        dim = 0 if size >= 256 else size
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out += b"".join(d for _, d in images)
    (IMG / "icon.ico").write_bytes(out)
    (IMG / "icon-256.png").write_bytes(images[-1][1])
    print("wrote", IMG / "icon.ico", "and icon-256.png")


if __name__ == "__main__":
    main()
