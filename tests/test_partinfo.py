"""A part's quoting numbers with no window (solidsmufs/partinfo.py, --part): weight, surface area, size and holes."""

import json
import math
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from solidsmufs import partinfo  # noqa: E402

AREA = 2 * (30 * 20 + 30 * 10 + 20 * 10) - 2 * math.pi * 9 + 2 * math.pi * 3 * 10  # the block less the hole's ends, plus its wall
VOLUME = 30 * 20 * 10 - math.pi * 9 * 10


def _block(path):
    """A 30 × 20 × 10 mm block with a 6 mm hole through it (made in the app's own gmsh, which stays running for the
    other tests)."""
    from solidsmufs.kernel.cad import gmsh_ready
    gmsh = gmsh_ready()
    b = gmsh.model.occ.addBox(0, 0, 0, 30, 20, 10)
    c = gmsh.model.occ.addCylinder(15, 10, -1, 0, 0, 12, 3)
    gmsh.model.occ.cut([(3, b)], [(3, c)])
    gmsh.model.occ.synchronize()
    gmsh.write(str(path))
    gmsh.clear()


class PartInfoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.part = Path(cls.tmp.name) / "block.step"
        _block(cls.part)
        cls.env = {k: os.environ.get(k) for k in ("APPDATA", "LOCALAPPDATA")}
        os.environ["APPDATA"] = os.environ["LOCALAPPDATA"] = cls.tmp.name  # (its own mesh cache)

    @classmethod
    def tearDownClass(cls):
        for k, v in cls.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cls.tmp.cleanup()

    def test_numbers_from_a_listed_material(self):
        r = partinfo.read(self.part, material="6061-t6 ALUMINUM")
        self.assertEqual(r["format"], 1)
        self.assertEqual((r["kind"], r["exact"], r["bodies"]), ("cad", True, 1))
        self.assertEqual(r["material"], {"name": "6061-T6 Aluminum", "density": 2.7, "from": "list"})
        self.assertAlmostEqual(r["area"]["mm2"], AREA, places=2)
        self.assertAlmostEqual(r["area"]["in2"], AREA / 25.4 ** 2, places=4)
        self.assertAlmostEqual(r["volume"]["mm3"], VOLUME, places=2)
        self.assertAlmostEqual(r["weight"]["g"], VOLUME * 2.7e-3, places=3)
        self.assertAlmostEqual(r["weight"]["lb"], VOLUME * 2.7e-3 / 453.59237, places=5)
        self.assertEqual(r["size"]["mm"], [30.0, 20.0, 10.0])
        self.assertEqual(r["envelope"]["mm"], [30.0, 20.0, 10.0])
        self.assertEqual(r["holes"]["count"], 1)
        hole = r["holes"]["groups"][0]
        self.assertAlmostEqual(hole["diameter"]["mm"], 6.0, places=3)
        self.assertTrue(hole["through"])

    def test_density_and_no_material(self):
        r = partinfo.read(self.part, density=7.85)
        self.assertEqual(r["material"]["from"], "density")
        self.assertAlmostEqual(r["weight"]["g"], VOLUME * 7.85e-3, places=3)
        r = partinfo.read(self.part)  # the file names no material: no weight, the rest still there
        self.assertIsNone(r["material"])
        self.assertIsNone(r["weight"])
        self.assertAlmostEqual(r["area"]["mm2"], AREA, places=2)

    def test_errors_come_back_as_json(self):
        out = Path(self.tmp.name) / "out.json"
        self.assertEqual(partinfo.main(["--part", str(self.part), "--material", "Unobtainium", "--out", str(out)]), 2)
        self.assertIn("Unobtainium", json.loads(out.read_text(encoding="utf-8"))["error"])
        self.assertEqual(partinfo.main(["--part", str(Path(self.tmp.name) / "print.pdf"), "--out", str(out)]), 2)
        self.assertEqual(partinfo.main(["--part", str(self.part), "--out", str(out)]), 0)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["holes"]["count"], 1)

    def test_material_list_is_the_windows_one(self):
        known = partinfo.materials()
        self.assertEqual(known["304 Stainless"], 8.0)
        self.assertGreater(len(known), 40)


if __name__ == "__main__":
    unittest.main()
