# PyInstaller recipe for the prebuilt app: pyinstaller --noconfirm tools/solidsmurfs.spec
# Leaves dist/SolidSmurfs (Windows, Linux) or dist/SolidSmurfs.app (macOS). See .github/workflows/prebuilds.yml.
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
PKG = ROOT / "solidsmufs"
ICONS = PKG / "web" / "img"
# Everything in the package goes in, the U3D decoder in formats/u3d/vendor too (it has no license: see its README.md).

hidden, datas = [], []
for f in sorted(PKG.rglob("*")):
    if not f.is_file() or "__pycache__" in f.parts:
        continue
    if f.suffix == ".py":
        parts = f.relative_to(ROOT).with_suffix("").parts
        hidden.append(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    else:
        datas.append((str(f), str(f.parent.relative_to(ROOT))))

# gmsh.py looks for its library beside itself, and the wheel puts it in the environment's lib folder
gmsh_lib = {"win32": "gmsh-*.dll", "darwin": "libgmsh*.dylib"}.get(sys.platform, "libgmsh.so*")
binaries = [(str(f), ".") for f in Path(sys.prefix).glob(f"[Ll]ib*/{gmsh_lib}")]
if not binaries:
    raise SystemExit(f"no {gmsh_lib} under {sys.prefix}")

a = Analysis(
    [str(ROOT / "solidsmurfs.pyw")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    # as source files, not in the archive: the caches stamp themselves with the .py files, and gmsh finds its library by __file__
    module_collection_mode={"solidsmufs": "py", "gmsh": "py"},
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SolidSmurfs",
    console=False,
    upx=False,
    icon=str(ICONS / "solidsmurfs.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="SolidSmurfs", upx=False)
if sys.platform == "darwin":
    # no document types: the app never claims a file type, so double-clicks stay with whatever owns them
    app = BUNDLE(
        coll,
        name="SolidSmurfs.app",
        icon=str(ICONS / "icon-256.png"),
        bundle_identifier="com.wagnermachine.solidsmurfs",
        info_plist={"NSHighResolutionCapable": True},
    )
