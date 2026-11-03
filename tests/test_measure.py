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


def _make_block(path, turn=None):
    """Write the block as STEP, optionally turned (turn = [(axis, degrees), ...] about the origin). Built in
    a process of its own so its gmsh session can't disturb the viewer's."""
    import multiprocessing as mp

    p = mp.get_context("spawn").Process(target=_build_block, args=(str(path), turn))
    p.start()
    p.join(120)
    if p.exitcode != 0 or not Path(path).is_file():
        raise RuntimeError("could not build the test block")


def _build_block(path, turn):
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("block")
    occ = gmsh.model.occ
    box = occ.addBox(0, 0, 0, L, W, H)
    cyls = [(3, occ.addCylinder(x, y, -1, 0, 0, H + 2, d / 2)) for (x, y), d in HOLES]
    out, _ = occ.cut([(3, box)], cyls)
    for axis, deg in turn or []:
        occ.rotate(out, 0, 0, 0, *axis, math.radians(deg))
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

    def arcs(self, a, b, modes):
        res = self.s.measure([a, b], {"arcs": modes})
        return {r["label"]: r["value"] for r in res["rows"]}, res["arcs"]

    def test_hole_to_hole_close_center_and_far_tangents(self):
        # centres 20 apart, radii 4 and 3
        for a, b in ((self.hole(8), self.hole(6)), (self.circle(8), self.circle(6))):
            for modes, expected in ((["min", "min"], 13.0), (["center", "center"], 20.0), (["max", "max"], 27.0),
                                    (["min", "max"], 19.0), (["center", "max"], 23.0), (["max", "min"], 21.0)):
                r, used = self.arcs(a, b, modes)
                self.assertEqual(used, modes)
                label = "Center distance" if modes == ["center", "center"] else "Distance"
                self.assertAlmostEqual(r[label], expected, delta=TOL, msg=f"{a['kind']} {modes}")

    def test_hole_to_side_face_tangents(self):
        side = self.plane((1, 0, 0), 0)  # x = 0, hole centre at x = 10, radius 4
        for mode, expected in (("min", 6.0), ("center", 10.0), ("max", 14.0)):
            r, used = self.arcs(self.hole(8), side, [mode, None])
            self.assertEqual(used, [mode, None])
            self.assertAlmostEqual(r["Distance" if mode != "center" else "Center distance"], expected, delta=TOL)

    def test_point_to_arc_tangents(self):
        spot = {"kind": "point", "point": [0.0, 10.0, H]}  # on the top edge, level with the 8 mm hole, 10 mm away
        for mode, expected in (("min", 6.0), ("center", 10.0), ("max", 14.0)):
            r, _ = self.arcs(spot, self.circle(8), [None, mode])
            self.assertAlmostEqual(r["Distance" if mode != "center" else "Center distance"], expected, delta=TOL)

    def test_hole_centred_between_two_faces(self):
        # the 8 mm hole sits at x = 10 on a 40 mm block: 10 from one end, 30 from the other
        left, right, front, back = (self.plane((1, 0, 0), 0), self.plane((1, 0, 0), L),
                                    self.plane((0, 1, 0), 0), self.plane((0, 1, 0), W))
        for mode, near, far in (("center", 10.0, 30.0), ("min", 6.0, 26.0), ("max", 14.0, 34.0)):
            res = self.s.measure([self.hole(8), left, right], {"arcs": [mode, None, None]})
            vals = [r["value"] for r in res["rows"] if r["label"].startswith("To ")]
            np.testing.assert_allclose(vals, [near, far], atol=TOL)
            self.assertEqual(res["arcs"], [mode, None, None])
            r = {x["label"]: x["value"] for x in res["rows"]}
            self.assertAlmostEqual(r["Off center"], 10.0, delta=TOL)
        r = {x["label"]: x["value"] for x in self.s.measure([front, self.circle(8), back], {"arcs": [None, "center", None]})["rows"]}
        self.assertAlmostEqual(r["Off center"], 0.0, delta=TOL)  # centred across the 20 mm width

    def test_three_flat_faces_still_total(self):
        r = self.rows(self.plane((1, 0, 0), 0), self.plane((1, 0, 0), L), self.plane((0, 0, 1), H))
        self.assertIn("Total area", r)

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


class BoxAlignedToPickedFaces(unittest.TestCase):
    """The block turned 30° about Z and tipped 20° about X, so no box along X / Y / Z fits it."""

    @classmethod
    def setUpClass(cls):
        from solidsmufs.kernel.worker import Session

        cls.dir = Path(tempfile.mkdtemp(prefix="solidsmufs-test-"))
        step = cls.dir / "turned.step"
        cls.turn = [((0, 0, 1), 30.0), ((1, 0, 0), 20.0)]
        _make_block(step, cls.turn)
        cls.s = Session()
        cls.s.load(str(step), "normal")
        cls.m = cls.s.model

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def turned(self, v):
        """Where a direction of the unturned block points now."""
        v = np.asarray(v, float)
        for axis, deg in self.turn:
            a, t = np.asarray(axis, float), math.radians(deg)
            v = v * math.cos(t) + np.cross(a, v) * math.sin(t) + a * (a @ v) * (1 - math.cos(t))
        return v

    def face_along(self, n):
        n = self.turned(n)
        for f, t in enumerate(self.m.face_type):
            if t == "plane" and abs(abs(np.dot(self.m.face_params[f]["normal"], n)) - 1) < 1e-6:
                return {"kind": "face", "index": f}
        self.fail("no such face")

    def test_world_box_is_bigger_than_the_block(self):
        size = self.s.bbox(None, "world")["size"]
        self.assertGreater(float(np.prod(size)), L * W * H * 1.2)

    def test_one_face_sets_the_height_and_fits_the_rest(self):
        res = self.s.bbox(None, "reference", [self.face_along((0, 0, 1))])
        np.testing.assert_allclose(res["size"], [L, W, H], atol=1e-6)
        self.assertAlmostEqual(abs(float(np.dot(res["axes"][2], self.turned((0, 0, 1))))), 1.0, places=9)

    def test_second_face_sets_the_length_direction(self):
        res = self.s.bbox(None, "reference", [self.face_along((0, 0, 1)), self.face_along((0, 1, 0))])
        np.testing.assert_allclose(res["size"], [W, L, H], atol=1e-6)  # length now runs along the 20 mm side

    def test_a_hole_sets_the_height_along_its_axis(self):
        hole = next(f for f, t in enumerate(self.m.face_type) if t == "cylinder")
        res = self.s.bbox(None, "reference", [{"kind": "face", "index": hole}])
        np.testing.assert_allclose(res["size"], [L, W, H], atol=1e-6)

    def test_asks_for_a_usable_face(self):
        with self.assertRaises(ValueError):
            self.s.bbox(None, "reference", [])


class AlignPart(unittest.TestCase):
    """Turning the block so picked faces face chosen views: the geometry itself turns, exactly."""

    @classmethod
    def setUpClass(cls):
        from solidsmufs.kernel.worker import Session

        cls.dir = Path(tempfile.mkdtemp(prefix="solidsmufs-test-"))
        cls.step = str(cls.dir / "block.step")
        _make_block(cls.step)
        cls.s = Session()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.s.load(self.step, "normal", orient=None)

    def face_along(self, n):
        m = self.s.model
        return next({"kind": "face", "index": f} for f, t in enumerate(m.face_type)
                    if t == "plane" and abs(abs(np.dot(m.face_params[f]["normal"], n)) - 1) < 1e-9)

    def turned(self, refs, targets):
        r = self.s.align(refs, targets)
        self.s.load(self.step, "normal", orient=r["orient"])
        return np.asarray(self.s.bbox(None, "world")["size"])

    def test_one_face_up_and_length_left_to_right(self):
        size = self.turned([self.face_along((1, 0, 0))], [[0, 1, 0]])  # an end face to Top
        np.testing.assert_allclose(size, [W, L, H], atol=1e-6)

    def test_two_faces_set_the_whole_orientation(self):
        size = self.turned([self.face_along((0, 0, 1)), self.face_along((1, 0, 0))], [[0, 0, 1], [0, 1, 0]])
        np.testing.assert_allclose(size, [W, L, H], atol=1e-6)  # top stays facing front, the end now up

    def test_turning_keeps_the_geometry_exact(self):
        self.turned([self.face_along((0, 1, 0))], [[1, 0, 0]])
        m = self.s.model
        dias = sorted(2 * m.face_params[f]["radius"] for f, t in enumerate(m.face_type) if t == "cylinder")
        np.testing.assert_allclose(dias, [6.0, 8.0], atol=1e-9)
        vol = L * W * H - sum(math.pi * (d / 2) ** 2 * H for _c, d in HOLES)
        self.assertAlmostEqual(self.s.massprops(None, 1.0)["volume"], vol, delta=1e-4)

    def test_reset(self):
        self.turned([self.face_along((1, 0, 0))], [[0, 1, 0]])
        self.s.load(self.step, "normal", orient=None)
        np.testing.assert_allclose(self.s.bbox(None, "world")["size"], [L, W, H], atol=1e-6)


if __name__ == "__main__":
    unittest.main()
