"""Tests for colours, finishes and materials (kernel/looks.py, formats/parasolid/appearance.py) and for
mass properties with a density per body.

    .venv\\Scripts\\python -m unittest tests.test_looks -v

The sample-part checks use files SolidWorks installs (skipped on a PC without them).
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidsmufs.formats.parasolid import appearance  # noqa: E402
from solidsmufs.kernel import looks, massprops  # noqa: E402

SAMPLES = Path(r"C:\Users\Public\Documents\SOLIDWORKS\SOLIDWORKS 2025\samples")
BRACKET = SAMPLES / "learn" / "U-Joint" / "bracket.sldprt"
BLADE = SAMPLES / "learn" / "Carving Knife" / "Components" / "Left Blade.SLDPRT"
PIN_304 = SAMPLES / "tutorial" / "assemblyvisualize" / "drive shaft pin.sldprt"


class Finishes(unittest.TestCase):
    def test_reads_the_finish_from_solidworks_appearance_names(self):
        cases = {"chromium plate": "Polished metal", "satin finish stainless steel": "Satin metal",
                 "carbon steel": "Rough metal", "matte rubber": "Matte rubber", "glossy rubber": "Glossy rubber",
                 "blue polished abs plastic": "High gloss plastic", "black low gloss plastic": "Low gloss plastic",
                 "polycarbonate": "Clear plastic", "polished ash 2d": "Wood", "metallic cool grey": "Metallic paint"}
        for name, finish in cases.items():
            with self.subTest(name=name):
                self.assertEqual(looks.finish_of_appearance(name), finish)

    def test_ignores_appearances_that_say_nothing_about_the_surface(self):
        for name in ("pw-mt11000", "asphalt 2d", "color"):
            self.assertIsNone(looks.finish_of_appearance(name))

    def test_material_sets_the_finish_when_there_is_no_appearance(self):
        self.assertEqual(looks.finish_of_material("AISI 304"), "Satin metal")
        self.assertEqual(looks.finish_of_material("Plain Carbon Steel"), "Rough metal")
        self.assertEqual(looks.finish_of_material("Brass"), "Polished metal")
        self.assertEqual(looks.finish_of_material("Rubber"), "Matte rubber")
        self.assertIsNone(looks.finish_of_material("Unobtanium"))

    def test_each_body_wears_the_appearance_that_matches_its_colour(self):
        apps = ["carbon steel", "black low gloss plastic", "light grey high gloss plastic"]
        self.assertEqual(looks.pick_appearance((0.05, 0.05, 0.05), apps), "black low gloss plastic")
        self.assertEqual(looks.pick_appearance((0.68, 0.7, 0.72), apps), "carbon steel")

    def test_metal_with_solidworks_default_colour_shows_in_metal_colour(self):
        lk = looks.look(looks.SOLIDWORKS_DEFAULT, [], "Brass")
        self.assertEqual(lk["finish"], "Polished metal")
        self.assertEqual(lk["tint"], list(looks.METAL_TINTS["brass"]))

    def test_a_chosen_colour_is_kept(self):
        self.assertNotIn("tint", looks.look((1.0, 0.0, 0.0), ["chromium plate"], None))


class Densities(unittest.TestCase):
    def test_keeps_the_stored_density(self):
        self.assertEqual(appearance.density_for("AISI 304", 8000.0), 8000.0)
        self.assertEqual(appearance.density_for("Rubber", 1000.0), 1000.0)

    def test_replaces_the_unset_value_with_the_material_family(self):
        self.assertEqual(appearance.density_for("Chrome Stainless Steel", 1000.0), 8000.0)
        self.assertEqual(appearance.density_for("6061 Alloy", None), 2700.0)


class PerBodyMass(unittest.TestCase):
    def test_bodies_of_different_densities_give_the_true_mass_and_centre(self):
        # two unit cubes 10 mm apart: steel (7.85) at x=0 and aluminium (2.7) at x=10
        cube = np.eye(3) / 6.0  # inertia of a unit cube about its centre, per unit density
        parts = [(1.0, np.array([0.0, 0, 0]), cube), (1.0, np.array([10.0, 0, 0]), cube)]
        scaled, ref = massprops._weighted(parts, [7.85, 2.7])
        vol, com, _inertia = massprops.combine(scaled)
        self.assertAlmostEqual(ref * vol, 7.85 + 2.7)  # report() computes mass as density × volume
        self.assertAlmostEqual(com[0], 10.0 * 2.7 / (7.85 + 2.7))


@unittest.skipUnless(BRACKET.is_file(), "SolidWorks 2025 sample files are not installed")
class SamplePartLooks(unittest.TestCase):
    def test_reads_body_colours_from_the_part(self):
        from solidsmufs.formats.parasolid.containers import open_source
        from solidsmufs.formats.parasolid.nodes import read_transmit

        model = read_transmit(open_source(str(BRACKET)).transmits[0][1])
        (rgb,) = appearance.colours(model)[0].values()
        np.testing.assert_allclose(rgb, (0.125, 0.737, 0.941), atol=1e-3)  # the blue bracket

    def test_reads_material_density_and_appearance(self):
        pin = appearance.solidworks(str(PIN_304))
        self.assertEqual((pin["material"], pin["density"]), ("AISI 304", 8000.0))
        blade = appearance.solidworks(str(BLADE))
        self.assertEqual((blade["material"], blade["appearances"]), ("Chrome Stainless Steel", ["chromium plate"]))

    def test_part_opens_with_its_colour_finish_and_material(self):
        from solidsmufs.kernel.worker import Session

        s = Session()
        s.load(str(BLADE), "normal")
        body = s.model.bodies[0]
        self.assertEqual(body["finish"]["finish"], "Polished metal")
        self.assertEqual(s.model.material["name"], "Chrome Stainless Steel")
        self.assertIsNotNone(body["color"])


if __name__ == "__main__":
    unittest.main()
