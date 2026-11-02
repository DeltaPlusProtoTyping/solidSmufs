"""Tests for measuring, mass properties and bounding boxes on a part whose answers are known exactly.

    .venv\\Scripts\\python -m unittest tests.test_measure -v

The part is a 40 x 20 x 10 mm block with a through hole of 8 mm diameter at (10, 10) and one of 6 mm at
(30, 10), built in OpenCASCADE and saved as STEP, then opened the way the viewer opens any file.
"""

import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidsmufs.kernel import measure  # noqa: E402

L, W, H = 40.0, 20.0, 10.0
HOLES = [((10.0, 10.0), 8.0), ((30.0, 10.0), 6.0)]  # (centre x, y), diameter
TOL = 1e-6


def _make_block(path):
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("block")
    occ = gmsh.model.occ
    box = occ.addBox(0, 0, 0, L, W, H)
    cyls = [(3, occ.addCylinder(x, y, -1, 0, 0, H + 2, d / 2)) for (x, y), d in HOLES]
    occ.cut([(3, box)], cyls)
    occ.synchronize()
    gmsh.write(str(path))
    gmsh.finalize()


class BlockWithHoles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from solidsmufs.kernel.worker import Session

        cls.dir = Path(tempfile.mkdtemp(prefix="solidsmufs-test-"))
        step = cls.dir / "block.step"
        _make_block(step)
        cls.s = Session()
        cls.s.load(str(step), "normal")
        cls.m = cls.s.model

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    # ---- finding entities by what they are
    def plane(self, normal, at):
        """The flat face with this normal (up to sign) whose centroid lies at `at` along it."""
        n = np.asarray(normal, float)
        for f, t in enumerate(self.m.face_type):
            p = self.m.face_params[f] or {}
            if t == "plane" and abs(abs(np.dot(p["normal"], n)) - 1) < 1e-9:
                if abs(np.dot(measure.face_centroid(self.m, f), n) - at) < 1e-6:
                    return {"kind": "face", "index": f}
        self.fail(f"no flat face with normal {normal} at {at}")

    def hole(self, dia):
        for f, t in enumerate(self.m.face_type):
            if t == "cylinder" and abs(2 * self.m.face_params[f]["radius"] - dia) < 1e-6:
                return {"kind": "face", "index": f}
        self.fail(f"no {dia} mm hole")

    def circle(self, dia):
        for e, t in enumerate(self.m.edge_type):
            p = self.m.edge_params[e] or {}
            if t == "circle" and abs(2 * p.get("radius", 0) - dia) < 1e-6:
                return {"kind": "edge", "index": e}
        self.fail(f"no {dia} mm circle")

    def vertex(self, xyz):
        d = np.linalg.norm(self.m.vertices - np.asarray(xyz, float), axis=1)
        return {"kind": "vertex", "index": int(np.argmin(d))}

    def rows(self, *ents):
        return {r["label"]: r["value"] for r in self.s.measure(list(ents))["rows"]}

    # ---- one item
    def test_hole_diameter(self):
        self.assertAlmostEqual(self.rows(self.hole(8))["Diameter"], 8.0, delta=TOL)
        self.assertAlmostEqual(self.rows(self.hole(6))["Radius"], 3.0, delta=TOL)

    def test_circular_edge_diameter_and_circumference(self):
        r = self.rows(self.circle(8))
        self.assertAlmostEqual(r["Diameter"], 8.0, delta=TOL)
        self.assertAlmostEqual(r["Circumference"], math.pi * 8, delta=1e-4)

    def test_face_area_is_exact(self):
        top = self.rows(self.plane((0, 0, 1), H))
        expected = L * W - sum(math.pi * (d / 2) ** 2 for _c, d in HOLES)
        self.assertAlmostEqual(top["Area"], expected, delta=1e-6)

    def test_vertex_position(self):
        r = self.rows(self.vertex((L, W, H)))
        self.assertEqual((r["X"], r["Y"], r["Z"]), (L, W, H))

    # ---- two items
    def test_distance_between_opposite_faces(self):
        r = self.rows(self.plane((1, 0, 0), 0), self.plane((1, 0, 0), L))
        self.assertAlmostEqual(r["Normal distance"], L, delta=TOL)
        self.assertAlmostEqual(r["Distance"], L, delta=TOL)
        self.assertIn("parallel", str(r["Angle"]))

    def test_angle_between_adjacent_faces(self):
        r = self.rows(self.plane((1, 0, 0), 0), self.plane((0, 0, 1), H))
        self.assertAlmostEqual(r["Angle"], 90.0, delta=1e-9)

    def test_hole_centre_distance(self):
        r = self.rows(self.hole(8), self.hole(6))
        self.assertAlmostEqual(r["Center distance"], 20.0, delta=TOL)

    def test_circle_edges_measure_centre_to_centre(self):
        r = self.rows(self.circle(8), self.circle(6))
        self.assertAlmostEqual(r["Center distance"], 20.0, delta=TOL)

    def test_corner_to_corner_distance_and_deltas(self):
        r = self.rows(self.vertex((0, 0, 0)), self.vertex((L, W, H)))
        self.assertAlmostEqual(r["Distance"], math.sqrt(L * L + W * W + H * H), delta=TOL)
        self.assertEqual((r["dX"], r["dY"], r["dZ"]), (L, W, H))

    # ---- mass properties and size
    def test_volume_and_centre_of_mass(self):
        res = self.s.massprops(None, 1.0)
        vols = [math.pi * (d / 2) ** 2 * H for _c, d in HOLES]
        volume = L * W * H - sum(vols)
        cx = (L * W * H * L / 2 - sum(v * c[0] for v, (c, _d) in zip(vols, HOLES))) / volume
        self.assertAlmostEqual(res["volume"], volume, delta=1e-4)
        self.assertAlmostEqual(res["mass"], volume * 1e-3, delta=1e-6)  # g at 1 g/cm³
        np.testing.assert_allclose(res["center"], [cx, W / 2, H / 2], atol=1e-6)

    def test_bounding_box_is_the_block(self):
        world = self.s.bbox(None, "world")
        np.testing.assert_allclose(world["size"], [L, W, H], atol=1e-6)
        best = self.s.bbox(None, "oriented")
        np.testing.assert_allclose(sorted(best["size"], reverse=True), [L, W, H], atol=1e-6)


if __name__ == "__main__":
    unittest.main()
