"""PRC exact geometry: curves, surfaces and faces whose answers are known. Samples of real files are used when
SOLIDSMURFS_PRC_SAMPLES names a folder of .prc files; their licences don't let them live in the project."""

import math
import os
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from solidsmufs.formats import prc  # noqa: E402
from solidsmufs.formats.prc import brep as br, brepmesh as bm  # noqa: E402

SAMPLES = os.environ.get("SOLIDSMURFS_PRC_SAMPLES", "")
T = np.linspace(0.0, 1.0, 33)


def area_of(points, triangles):
    a, b, c = points[triangles[:, 0]], points[triangles[:, 1]], points[triangles[:, 2]]
    return float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2)


def circle(center, radius, axis=(0, 0, 1)):
    axis = np.array(axis, float)
    side = np.cross(axis, (1.0, 0, 0)) if abs(axis[0]) < 0.9 else np.cross(axis, (0, 1.0, 0))
    side = side / np.linalg.norm(side)
    return br.Arc(np.array(center, float) + side * radius, center, axis, br.TAU)


def body_of(*faces):
    points = []
    for f in faces:
        for loop in (f.loops or []) if isinstance(f, br.AnaFace) else []:
            for curve in loop:
                points.append(curve.at(T))
    return br.Brep([(False, [(f, 1) for f in faces])], points)


class Arcs(unittest.TestCase):
    def test_the_circle_through_three_points(self):
        a = br._arc_through((1, 0, 0), (0, 1, 0), (-1, 0, 0))
        p = a.at(T)
        np.testing.assert_allclose(np.linalg.norm(p, axis=1), 1.0)
        np.testing.assert_allclose(p[0], (1, 0, 0), atol=1e-12)
        np.testing.assert_allclose(p[16], (0, 1, 0), atol=1e-12)
        np.testing.assert_allclose(p[-1], (-1, 0, 0), atol=1e-12)

    def test_it_goes_by_the_middle_point_even_the_long_way(self):
        a = br._arc_through((1, 0, 0), (-1, 0, 0), (0, 1, 0))  # three quarters of the way round, by (-1, 0)
        self.assertAlmostEqual(a.sweep, 1.5 * math.pi)
        np.testing.assert_allclose(a.at(np.array([1.0]))[0], (0, 1, 0), atol=1e-12)

    def test_off_center_it_finds_the_true_center(self):
        a = br._arc_through((6, 3, 2), (5, 4, 2), (4, 3, 2))
        np.testing.assert_allclose(a.center, (5, 3, 2), atol=1e-12)

    def test_three_in_a_row_are_a_line(self):
        self.assertIsInstance(br._arc_through((0, 0, 0), (1, 0, 0), (2, 0, 0)), br.Segment)

    def test_short_and_long_about_a_center(self):
        short = br._arc_about((1, 0, 0), (0, 1, 0), (0, 0, 0), False)
        long = br._arc_about((1, 0, 0), (0, 1, 0), (0, 0, 0), True)
        self.assertAlmostEqual(short.sweep, math.pi / 2)
        self.assertAlmostEqual(long.sweep, 1.5 * math.pi)
        np.testing.assert_allclose(long.at(np.array([1.0]))[0], (0, 1, 0), atol=1e-12)
        np.testing.assert_allclose(long.at(np.array([0.5]))[0][:2], np.array((-1, -1)) / math.sqrt(2), atol=1e-12)

    def test_a_hermite_curve_runs_through_its_points(self):
        h = br.Hermite([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(1 / 3, 0, 0)] * 3)
        np.testing.assert_allclose(h.at(np.array([0.0, 0.25, 0.5, 1.0]))[:, 0], [0, 0.5, 1, 2])


class Surfaces(unittest.TestCase):
    def check_round_trip(self, s, u, v):
        back_u, back_v, _pole = s.invert(s.at(u, v))
        np.testing.assert_allclose(s.at(back_u, back_v), s.at(u, v), atol=1e-9)

    def test_each_kind_finds_its_way_back(self):
        m = br._frame((1, 2, 3), (1, 1, 0))
        u, v = np.array([0.3, 1.2, 2.5]), np.array([0.2, 0.5, 0.9])
        for s in (br.Plane(m, False, None, 1, 1, 0, 0), br.Cylinder(m, False, None, 1, 1, 0, 0, 2.0), br.Cone(m, False, None, 1, 1, 0, 0, 1.0, 0.5),
                  br.Sphere(m, False, None, 1, 1, 0, 0, 2.0), br.Torus(m, False, None, 1, 1, 0, 0, 5.0, 1.0),
                  br.Cylinder(m, True, None, 2.0, 3.0, 0.5, 0.25, 2.0)):
            self.check_round_trip(s, u, v)

    def test_a_cone_with_a_negative_radius_is_the_same_cone(self):
        s = br.Cone(None, False, None, 1, 1, 0, 0, -30.0, 0.1)
        p = s.at(np.array([0.7]), np.array([-12.5]))
        np.testing.assert_allclose(np.hypot(p[0, 0], p[0, 1]), 31.25)
        self.check_round_trip(s, np.array([0.7, 2.0]), np.array([-12.5, 4.0]))

    def test_a_swapped_surface_faces_the_other_way(self):
        self.assertFalse(br.Cylinder(None, False, None, 1, 1, 0, 0, 1.0).flip)
        self.assertTrue(br.Cylinder(None, True, None, 1, 1, 0, 0, 1.0).flip)

    def test_a_closed_nurbs_says_so_and_wraps(self):
        w, n = math.sqrt(0.5), 9
        ring = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0)]
        control = np.array([[[x, y, z] for x, y in ring] for z in (0.0, 1.0)], float)
        weights = np.array([[1, w, 1, w, 1, w, 1, w, 1]] * 2, float)
        s = br.NurbsSurface(1, 2, control, np.array([0, 0, 1, 1.0]), np.array([0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4.0]), weights)
        self.assertEqual(s.period, (0.0, 4.0))
        np.testing.assert_allclose(s.at(np.array([0.5]), np.array([5.0])), s.at(np.array([0.5]), np.array([1.0])))
        self.assertEqual(n, control.shape[1])


class Faces(unittest.TestCase):
    def mesh(self, *faces, tolerance=1e-3):
        return bm.mesh_body(body_of(*faces), tolerance, 1e-7)

    def test_a_plate_with_a_hole(self):
        square = [br.Segment((0, 0, 0), (10, 0, 0)), br.Segment((10, 0, 0), (10, 10, 0)), br.Segment((10, 10, 0), (0, 10, 0)), br.Segment((0, 10, 0), (0, 0, 0))]
        hole = circle((5, 5, 0), 2.0)
        points, tris, _f, _n, planar, counts = self.mesh(br.AnaFace(lambda p: br._make_plane(np.array((0, 0, 1.0)), p), True, [square, [hole]]))
        self.assertEqual(planar, [True])
        self.assertEqual(counts.approximate, 0)
        self.assertAlmostEqual(area_of(points, tris), 100 - math.pi * 4, delta=0.05)

    def test_a_band_round_a_whole_cylinder(self):
        loops = [[circle((0, 0, 0), 2.0)], [circle((0, 0, 5), 2.0)]]
        face = br.AnaFace(lambda p: br._make_cylinder(np.zeros(3), np.array((0, 0, 1.0)), p), True, loops)
        points, tris, _f, normals, _p, counts = self.mesh(face)
        self.assertEqual(counts.approximate, 0)
        self.assertAlmostEqual(area_of(points, tris), 2 * math.pi * 2 * 5, delta=0.3)
        np.testing.assert_allclose(np.hypot(points[:, 0], points[:, 1]), 2.0, atol=1e-6)
        # the surface's own normals, pointing square out from the axis
        np.testing.assert_allclose(np.abs(normals[:, :, 2]), 0.0, atol=1e-6)

    def test_a_cone_closes_at_its_apex(self):
        apex = np.array((0, 0, 4.0))
        face = br.AnaFace(lambda p: br._make_cone(np.zeros(3), apex, p), True, [[circle((0, 0, 0), 3.0)]])
        points, tris, _f, _n, _p, counts = self.mesh(face)
        self.assertEqual(counts.approximate, 0)
        self.assertAlmostEqual(area_of(points, tris), math.pi * 3 * 5, delta=0.3)
        self.assertAlmostEqual(float(points[:, 2].max()), 4.0, places=6)

    def test_two_faces_on_one_great_circle_are_both_halves_of_the_sphere(self):
        center = np.zeros(3)
        faces = [br.AnaFace(lambda p: br._make_sphere(center, p), True, [[circle(center, 2.0)]]) for _ in range(2)]
        points, tris, _f, _n, _p, _c = self.mesh(*faces)
        self.assertAlmostEqual(float(points[:, 2].min()), -2.0, places=6)
        self.assertAlmostEqual(float(points[:, 2].max()), 2.0, places=6)
        self.assertAlmostEqual(area_of(points, tris), 4 * math.pi * 4, delta=0.5)

    def test_a_patch_on_a_cylinder_is_exact(self):
        arc = br._arc_about((2, 0, 0), (0, 2, 0), (0, 0, 0), False)
        line = br.Segment((0, 2, 0), (0, 2, 5))
        third, fourth = br.Deduced(), br.Deduced()
        br._settle_sides(arc, line, third, fourth, True, True, np.array((2.0, 0, 5)))
        face = br.PatchFace(br.ISO_CYLINDER, True, (arc, line, third, fourth))
        points, tris, _f, _n, planar, _c = self.mesh(face)
        self.assertEqual(planar, [False])
        np.testing.assert_allclose(np.hypot(points[:, 0], points[:, 1]), 2.0, atol=1e-6)
        self.assertAlmostEqual(area_of(points, tris), math.pi / 2 * 2 * 5, delta=0.1)

    def test_a_torus_patch_finds_its_torus_even_with_a_side_deduced_the_wrong_way(self):
        # half way round a torus of radii 5 and 1, a quarter of its tube
        big = br._arc_about((5, 0, 0), (-5, 0, 0), (0, 0, 0), False)
        big = br.Arc((5, 0, 0), (0, 0, 0), (0, 0, 1), math.pi)
        tube = br.Arc((-5, 0, 0), (-5 - 1, 0, 0), (0, 1, 0), math.pi / 2)
        tube_end = tube.at(np.array([1.0]))[0]
        third, fourth = br.Deduced(), br.Deduced()
        corner = np.array((-tube_end[0], 0, tube_end[2]))
        br._settle_sides(big, tube, third, fourth, True, True, corner)
        face = br.PatchFace(br.ISO_TORUS, True, (big, tube, third, fourth))
        points, _t, _f, _n, _p, counts = self.mesh(face)
        self.assertEqual(counts.approximate, 0)
        surface = bm.torus_of(face.sides)
        self.assertIsNotNone(surface)
        self.assertAlmostEqual(surface.major, 6.0, places=6)
        self.assertAlmostEqual(surface.minor, 1.0, places=6)
        ring = np.hypot(points[:, 0], points[:, 1]) - 6.0
        np.testing.assert_allclose(np.hypot(ring, points[:, 2]), 1.0, atol=1e-6)

    def test_a_whole_nurbs_is_a_grid_over_its_domain(self):
        c = np.array([[[x, y, 0.0] for y in (0, 1, 2)] for x in (0, 1, 2)])
        s = br.NurbsSurface(2, 2, c, np.array([0, 0, 0, 1, 1, 1.0]), np.array([0, 0, 0, 1, 1, 1.0]), None)
        points, tris, _f, _n, _p, _c = bm.mesh_body(br.Brep([(False, [(br.WholeFace(s, True), 1)])], [c.reshape(-1, 3)]), 1e-3, 1e-7)
        self.assertAlmostEqual(area_of(points, tris), 4.0, places=9)

    def test_a_face_that_makes_no_sense_costs_only_itself(self):
        good = br.AnaFace(lambda p: br._make_plane(np.array((0, 0, 1.0)), p), True,
                          [[br.Segment((0, 0, 0), (1, 0, 0)), br.Segment((1, 0, 0), (0, 1, 0)), br.Segment((0, 1, 0), (0, 0, 0))]])

        def broken(_points):
            raise TypeError("no")
        bad = br.AnaFace(broken, True, [[circle((0, 0, 0), 1.0)]])
        points, tris, _f, _n, planar, counts = self.mesh(bad, good)
        self.assertEqual(counts.skipped, 1)
        self.assertEqual(len(planar), 1)
        self.assertAlmostEqual(area_of(points, tris), 0.5)

    def test_a_trimmed_sheet_counts_only_what_it_keeps(self):
        huge = np.array([[[x, y, 0.0] for y in (-1e4, 1e4)] for x in (-1e4, 1e4)])
        sheet = br.NurbsSurface(1, 1, huge, np.array([0, 0, 1, 1.0]), np.array([0, 0, 1, 1.0]), None)
        loop = [br.Segment((0, 0, 0), (1, 0, 0)), br.Segment((1, 0, 0), (1, 1, 0)), br.Segment((1, 1, 0), (0, 1, 0)), br.Segment((0, 1, 0), (0, 0, 0))]
        points, tris, _f, _n, _p, counts = self.mesh(br.AnaFace(lambda p: sheet, True, [loop]), tolerance=1e-3)
        self.assertEqual(counts.approximate, 0)
        self.assertAlmostEqual(area_of(points, tris), 1.0, places=5)
        self.assertLess(float(np.abs(points).max()), 1.01)


@unittest.skipUnless(SAMPLES, "SOLIDSMURFS_PRC_SAMPLES isn't set")
class RealFiles(unittest.TestCase):
    def read(self, name):
        return prc.read_prc((Path(SAMPLES) / f"{name}.prc").read_bytes())

    def test_files_with_no_triangles_now_show(self):
        for name, faces in (("Engineering-Data-Release_LandingGear.stream-8995", 1000), ("mower_carb.stream-23", 1000),
                            ("Bracket-with-PMI.attachment-Bracket_Shock_PMI_data.stream-12", 90), ("c1-102580", 150)):
            r = self.read(name)
            self.assertTrue(r.placed, name)
            self.assertGreater(sum(len(p.planar) for p in r.pieces), faces, name)
            for p in r.pieces:
                self.assertTrue(np.isfinite(p.points).all(), name)

    def test_a_file_with_triangles_keeps_them(self):
        r = self.read("TDP_Creo_Tetra4D_6_2017.stream-10")
        self.assertTrue(all(isinstance(p.key[1], int) for p in r.pieces))

    def test_a_context_scale_is_applied(self):
        r = self.read("mower_carb.stream-23")  # in meters in its body, millimeters at its scale of 1000
        self.assertGreater(max(float(np.ptp(p.points, axis=0).max()) for p in r.pieces), 1.0)


if __name__ == "__main__":
    unittest.main()
