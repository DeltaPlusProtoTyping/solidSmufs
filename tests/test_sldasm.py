"""Tests for the SolidWorks assembly reader (solidsmufs/formats/sldasm.py) and for opening assemblies.

    .venv\\Scripts\\python -m unittest tests.test_sldasm -v

The format checks use small hand-made byte strings. The assembly checks use the U-Joint sample that
SolidWorks installs (skipped on a PC without it); the end-to-end check proves each part is placed where
the assembly says by comparing its volume and centre of mass with the part opened on its own.
"""

import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidsmufs.formats import sldasm  # noqa: E402

UJOINT = Path(r"C:\Users\Public\Documents\SOLIDWORKS\SOLIDWORKS 2025\samples\learn\U-Joint\UJoint.SLDASM")
STAMP = bytes.fromhex("6a70cb010a4b53aa")  # the timestamp that starts every record (2010 here)
START = STAMP + bytes.fromhex("02000000000001")
VOLUME_TOLERANCE_MM3 = 1e-3
CENTER_TOLERANCE_MM = 1e-3


def mfc(text):
    """An MFC CString as SolidWorks stores it: FF FE FF, a length byte, UTF-16 characters."""
    return b"\xff\xfe\xff" + bytes([len(text)]) + text.encode("utf-16-le")


def record(name, config, rotation=None, translation_m=(0.0, 0.0, 0.0), scale=1.0):
    """One component record: name, marker, flag + placement doubles, then its configuration name."""
    if rotation is None:
        body = b"\x00" + struct.pack("<4d", *translation_m, scale)
    else:
        body = b"\x01" + struct.pack("<13d", *np.asarray(rotation, float).ravel(), *translation_m, scale)
    return mfc(name) + START + sldasm.RECORD_NEWER + body + mfc(config)


class RecordFormat(unittest.TestCase):
    def test_reads_mfc_strings_with_their_exact_text(self):
        data = b"junk" + mfc("bracket-1") + b"\x01\x02" + mfc("Default")
        self.assertEqual([s[2] for s in sldasm._mfc_strings(data)], ["bracket-1", "Default"])

    def test_translation_only_record_places_part_in_millimetres(self):
        (name, config, matrix), = sldasm._records(record("bolt-1", "Default", None, (0.01, -0.02, 0.5)))
        self.assertEqual((name, config), ("bolt-1", "Default"))
        np.testing.assert_allclose(matrix[:3, :3], np.eye(3))
        np.testing.assert_allclose(matrix[:3, 3], [10.0, -20.0, 500.0])

    def test_rotation_record_is_applied_transposed(self):
        quarter_turn_about_z = [[0, 1, 0], [-1, 0, 0], [0, 0, 1]]  # as stored
        (_, _, matrix), = sldasm._records(record("pin-2", "SHORT", quarter_turn_about_z, (0, 0, 0)))
        np.testing.assert_allclose(matrix[:3, :3] @ [1, 0, 0], [0, 1, 0], atol=1e-12)

    def test_configuration_name_is_the_string_after_the_record(self):
        data = record("pin-1", "LONG") + record("pin-2", "SHORT")
        self.assertEqual([(n, c) for n, c, _ in sldasm._records(data)], [("pin-1", "LONG"), ("pin-2", "SHORT")])

    def test_reads_the_older_record_encoding(self):
        older = mfc("table-1") + START + b"\x00" + struct.pack("<4d", 1.3208, 0.3, 0.07, 1.0)
        (name, _, matrix), = sldasm._records(older + mfc("Default"))
        self.assertEqual(name, "table-1")
        np.testing.assert_allclose(matrix[:3, 3], [1320.8, 300.0, 70.0])

    def test_reads_records_with_an_id_after_the_timestamp(self):
        with_id = mfc("holder-1") + STAMP + bytes.fromhex("0200e493040001") + sldasm.RECORD_NEWER
        (name, _, matrix), = sldasm._records(with_id + b"\x00" + struct.pack("<4d", 0.032, 0, 0.1, 1.0) + mfc("Default"))
        self.assertEqual(name, "holder-1")
        np.testing.assert_allclose(matrix[:3, 3], [32.0, 0.0, 100.0])

    def test_lights_do_not_borrow_the_last_component_name(self):
        light = b"\x00" * 1000 + START + b"\x00" + struct.pack("<4d", 0, 0, 0, 1.0) + mfc("Ambient")
        names = [n for n, _, _ in sldasm._records(record("crank-knob-1", "Default") + light)]
        self.assertEqual(names, ["crank-knob-1"])

    def test_rejects_records_that_are_not_rigid_placements(self):
        skewed = [[2, 0, 0], [0, 1, 0], [0, 0, 1]]
        self.assertEqual(sldasm._records(record("odd-1", "Default", skewed)), [])
        self.assertEqual(sldasm._records(record("scaled-1", "Default", None, scale=2.0)), [])


class ModelMatching(unittest.TestCase):
    MODELS = [sldasm._Model("pin", "LONG", 0, r"C:\x\pin.SLDPRT"), sldasm._Model("pin", "SHORT", 1, r"C:\x\pin.SLDPRT"),
              sldasm._Model("crank-arm", "Default", 28, r"C:\x\crank-arm.SLDPRT")]

    def test_picks_the_configuration_a_component_uses(self):
        self.assertEqual(sldasm._match(self.MODELS, "pin-3", "SHORT").config_id, 1)
        self.assertEqual(sldasm._match(self.MODELS, "pin-1", "LONG").config_id, 0)

    def test_keeps_dashes_that_are_part_of_the_name(self):
        self.assertEqual(sldasm._match(self.MODELS, "crank-arm-1", "Default").config_id, 28)

    def test_ignores_records_that_are_not_components(self):
        self.assertIsNone(sldasm._match(self.MODELS, "Directional-1", ""))


class FileSearch(unittest.TestCase):
    def test_finds_a_part_at_the_same_relative_place_after_the_folder_moved(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "parts").mkdir()
            part = Path(tmp) / "parts" / "arm.sldprt"
            part.write_bytes(b"x")
            found = sldasm._resolve(r"F:\old\job\parts\arm.sldprt", r"F:\old\job\top.sldasm", Path(tmp) / "top.sldasm")
            self.assertEqual(found, part)

    def test_returns_none_when_the_part_is_nowhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(sldasm._resolve(r"F:\old\gone.sldprt", None, Path(tmp) / "top.sldasm"))


@unittest.skipUnless(UJOINT.is_file(), "SolidWorks 2025 sample files are not installed")
class UJointAssembly(unittest.TestCase):
    def test_lists_every_part_including_the_sub_assembly(self):
        asm = sldasm.read(UJOINT)
        self.assertEqual(len(asm.placements), 10)
        self.assertEqual(asm.missing, [])
        self.assertIn(["crank sub-1", "crank-arm-1"], [p.path for p in asm.placements])

    def test_long_and_short_pins_use_their_own_configurations(self):
        configs = {"/".join(p.path): p.config for p in sldasm.read(UJOINT).placements}
        self.assertEqual((configs["pin-1"], configs["pin-2"], configs["pin-3"]), (0, 1, 1))

    def test_reports_parts_that_are_not_next_to_a_copied_assembly(self):
        with tempfile.TemporaryDirectory() as tmp:
            alone = Path(tmp) / UJOINT.name
            shutil.copyfile(UJOINT, alone)
            asm = sldasm.read(alone)
        self.assertEqual(asm.placements, [])
        self.assertEqual({why for _i, _f, why in asm.missing}, {"file not found"})

    def test_every_part_sits_where_the_assembly_places_it(self):
        from solidsmufs.kernel.worker import Session

        whole = Session()
        whole.load(str(UJOINT), "normal")
        placements = sldasm.read(UJOINT).placements
        self.assertEqual(len(whole.model.bodies), len(placements))
        # bodies come out grouped by part file; find each instance's body by its tree path
        body_of = {"/".join(n.replace("::", "-") for n in b["path"] if "::" in n): i
                   for i, b in enumerate(whole.model.bodies)}
        self.assertEqual(sorted(body_of), sorted("/".join(p.path) for p in placements))
        # gmsh holds one model per process: measure the assembly before opening parts on their own
        placed_all = {name: whole.massprops([i], 1.0) for name, i in body_of.items()}
        alone = {}
        for p in placements:
            key = (str(p.file), p.config)
            if key not in alone:
                part = Session()
                step, _info, cleanup = part._parasolid_step(str(p.file), ".sldprt", lambda *a: None, p.config)
                try:
                    from solidsmufs.kernel import cad
                    part.model = cad.load(str(p.file), p.file.name, "part", source=step)
                    part._wire_exact()
                finally:
                    cleanup()
                alone[key] = part.massprops(None, 1.0)
            placed = placed_all["/".join(p.path)]
            with self.subTest(part="/".join(p.path)):
                self.assertAlmostEqual(placed["volume"], alone[key]["volume"], delta=VOLUME_TOLERANCE_MM3)
                expected = p.matrix[:3, :3] @ np.asarray(alone[key]["center"]) + p.matrix[:3, 3]
                np.testing.assert_allclose(placed["center"], expected, atol=CENTER_TOLERANCE_MM)


if __name__ == "__main__":
    unittest.main()
