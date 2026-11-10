"""Checks a build from tools/solidsmurfs.spec before it's handed out: the files the app loads at run time are in it (the U3D
decoder, the OCR script), and the frozen app starts, shows its page and opens a real STEP part and a picture in worker processes. Run from the repository root, with gmsh
installed: python tools/check_prebuild.py picture.png"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

DELAY = 90  # seconds the app runs before it takes its picture and quits
NEEDED = ("u3d-rhadobe-mesh.js", "ocr.ps1")  # read from disk when they're used, so a missing one only shows later


def fail(message):
    sys.exit(f"prebuild check failed: {message}")


def locate():
    """(the bundle's folder, its program) in dist/."""
    if sys.platform == "darwin":
        bundle = Path("dist/SolidSmurfs.app")
        return bundle, bundle / "Contents" / "MacOS" / "SolidSmurfs"
    bundle = Path("dist/SolidSmurfs")
    return bundle, bundle / ("SolidSmurfs.exe" if sys.platform == "win32" else "SolidSmurfs")


def make_block(path):
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.occ.addBox(0, 0, 0, 30, 20, 10)
    gmsh.model.occ.synchronize()
    gmsh.write(str(path))
    gmsh.finalize()


def main():
    picture = Path(sys.argv[1]).resolve()
    bundle, program = locate()
    if not program.is_file():
        fail(f"no {program}")
    names = {f.name for f in bundle.rglob("*")}
    missing = [n for n in NEEDED if n not in names]
    if missing:
        fail(f"not in the build: {missing}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        part = tmp / "block.step"
        make_block(part)
        picture_file = tmp / "swatch.png"  # a picture too: Qt's image plugins must be in the build
        from PIL import Image
        Image.new("RGB", (64, 48), (40, 120, 200)).save(picture_file)
        # its own settings and caches, so the log holds this run alone and nothing comes from an earlier one
        env = {**os.environ, "APPDATA": str(tmp), "LOCALAPPDATA": str(tmp)}
        run = subprocess.run([str(program.resolve()), "--snapshot", str(picture), "--snapshot-delay", str(DELAY), str(part), str(picture_file)],
                             env=env, cwd=tmp, timeout=DELAY + 120)
        log = tmp / "SolidSmufs" / "log.txt"
        text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    print(text)
    if run.returncode != 0:
        fail(f"the app exited with {run.returncode}")
    if "Traceback" in text:
        fail("the log has a traceback")
    # a first open reads the exact geometry along with the tessellation, so there's no later "exact geometry ready" line
    for needed in ("[timing] page ready", "block.step tessellation ready (cached=False)", "swatch.png tessellation ready"):
        if needed not in text:
            fail(f"the log never says {needed!r}")
    if not picture.is_file() or picture.stat().st_size == 0:
        fail("no picture")
    print(f"ok: {program}")


if __name__ == "__main__":
    main()
