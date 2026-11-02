"""Open sample files through the same path the app uses and print what came out.

    .venv\\Scripts\\python tests\\smoke.py [file ...]

With no arguments it tries the sample parts that come with this PC's software (PartMaker, gmsh)
plus whatever STEP / SolidWorks / STL files are in Downloads.
"""

import glob
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidsmufs.kernel.worker import ALL_FORMATS, Session  # noqa: E402


def samples():
    home = Path.home()
    pats = [str(home / "Downloads" / f"*{e}") for e in (".step", ".stp", ".sldprt", ".igs", ".stl", ".x_t")]
    pats.append(r"C:\Users\Public\Documents\Autodesk\PartMaker\pm-common\solids\*")
    sw = r"C:\Users\Public\Documents\SOLIDWORKS\SOLIDWORKS 2025\samples"
    pats += [sw + r"\learn\U-Joint\UJoint.SLDASM", sw + r"\introsw\bolt-assembly.sldasm"]  # assemblies
    out = []
    for p in pats:
        out += [f for f in glob.glob(p) if Path(f).suffix.lower() in ALL_FORMATS]
    return sorted(set(out))


def main(files):
    ok = bad = 0
    for f in files:
        s = Session()
        t = time.perf_counter()
        try:
            meta, _ = s.load(f, "normal")
            mp = s.massprops(None, 1.0)
            st = meta["stats"]
            print(f"OK   {time.perf_counter() - t:6.2f}s  {meta['format'][:26]:26}  bodies {st['bodies']:3}  faces {st['faces']:5}  "
                  f"volume {mp['volume']:14.3f} mm³  {os.path.basename(f)}")
            ok += 1
        except Exception as e:
            print(f"FAIL {time.perf_counter() - t:6.2f}s  {os.path.basename(f)}: {e}")
            bad += 1
    print(f"\n{ok} opened, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or samples()))
