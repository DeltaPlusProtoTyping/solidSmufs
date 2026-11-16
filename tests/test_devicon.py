"""The icon of SolidSmurfs run from its scripts (solidsmufs/devicon.py): the usual cube with the version in a box at the
bottom right, written as an .ico for the desktop shortcut and redrawn when the version changes."""

import os
import struct
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QGuiApplication, QIcon, QImage  # noqa: E402

from solidsmufs import __version__, devicon  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])


def _plain(size):
    return QIcon(str(devicon.SOURCE)).pixmap(size, size).toImage().convertToFormat(QImage.Format.Format_ARGB32)


def _changed(a, b, x0, y0, x1, y1):
    """How many pixels differ between two images in a box (by more than redrawing the icon rounds them)."""
    def far(p, q):
        return any(abs(((p >> s) & 255) - ((q >> s) & 255)) > 8 for s in (0, 8, 16, 24))
    return sum(far(a.pixel(x, y), b.pixel(x, y)) for x in range(x0, x1) for y in range(y0, y1))


class DevIconTest(unittest.TestCase):
    def test_label(self):
        self.assertEqual(devicon.label("0.1.5"), "V0.1.5")
        self.assertEqual(devicon.label("0.1.5", 48), "V0.1.5")
        self.assertEqual(devicon.label("0.1.5", 32), "0.1.5")  # (the taskbar's sizes: the number alone, larger)
        self.assertEqual(devicon.label(), f"V{__version__}")

    def test_badge_at_the_bottom_right_only(self):
        for size in (16, 32, 256):
            badged = devicon.badged(size, devicon.label(size=size)).convertToFormat(QImage.Format.Format_ARGB32)
            plain = _plain(size)
            h = size // 2
            self.assertGreater(_changed(badged, plain, h, h, size, size), size * size // 40, size)
            self.assertEqual(_changed(badged, plain, 0, 0, size, h // 2), 0, size)  # the top of the cube as it was

    def test_ico_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = devicon.write_ico(Path(tmp) / "icon.ico", "9.9.9")
            data = path.read_bytes()
            reserved, kind, count = struct.unpack_from("<HHH", data)
            self.assertEqual((reserved, kind, count), (0, 1, len(devicon.SIZES)))
            dims = [struct.unpack_from("<B", data, 6 + 16 * i)[0] or 256 for i in range(count)]
            self.assertEqual(dims, list(devicon.SIZES))
            for i in range(count):  # each size a PNG inside the file
                length, offset = struct.unpack_from("<II", data, 6 + 16 * i + 8)
                self.assertEqual(data[offset:offset + 8], b"\x89PNG\r\n\x1a\n")
                self.assertLessEqual(offset + length, len(data))

            # kept while the version is the same, redrawn when it changes
            before = path.stat().st_mtime_ns
            os.utime(path, ns=(before - 10**9, before - 10**9))
            devicon.write_ico(path, "9.9.9")
            self.assertEqual(path.stat().st_mtime_ns, before - 10**9)
            devicon.write_ico(path, "9.9.10")
            self.assertNotEqual(path.stat().st_mtime_ns, before - 10**9)
            self.assertEqual(path.with_suffix(".version").read_text(encoding="utf-8"), "9.9.10")

    def test_qicon_has_every_size(self):
        sizes = sorted(s.width() for s in devicon.icon("1.2.3").availableSizes())
        self.assertEqual(sizes, list(devicon.SIZES))


if __name__ == "__main__":
    unittest.main()
