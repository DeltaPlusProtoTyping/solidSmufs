"""Setting up the ODA File Converter (which turns DWG into DXF) for this Windows user, with no admin: its installer
is fetched from the Open Design Alliance, checked to be signed by them, and unpacked (msiexec /a, an "administrative
image", which installs nothing) into SolidSmurfs' own folder, where kernel/pictures.dwg_converter() finds it.
Only ever run when the user asks for it."""

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

INSTALLER = "ODAFileConverter_QT6_vc16_amd64dll.msi"
URL = f"https://www.opendesign.com/guestfiles/get?filename={INSTALLER}"
SIGNER = "OPEN DESIGN ALLIANCE"
SIZE_MB = 32  # about: said before the download, so the user knows what they're agreeing to


def folder():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "SolidSmufs" / "ODAFileConverter"


def available():
    """Can it be set up here? (The converter this fetches is the Windows one.)"""
    return sys.platform == "win32"


def _signer(path):
    """Who signed a file, if Windows says the signature is good; else None."""
    ps = ("$s = Get-AuthenticodeSignature -LiteralPath $env:SS_FILE; "
          "if ($s.Status -eq 'Valid') { $s.SignerCertificate.Subject }")
    run = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True,
                         env={**os.environ, "SS_FILE": str(path)}, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return run.stdout.strip() or None


def setup():
    """Fetch, check and unpack the converter. Its program's path, or ValueError saying what went wrong."""
    if not available():
        raise ValueError("Setting up DWG drawings works on Windows only.")
    exe = folder() / "ODAFileConverter.exe"
    if exe.is_file():
        return exe
    with tempfile.TemporaryDirectory(prefix="solidsmufs-oda-") as tmp:
        msi = Path(tmp) / INSTALLER
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (SolidSmurfs)"})
            with urllib.request.urlopen(req, timeout=60) as r, open(msi, "wb") as out:
                shutil.copyfileobj(r, out, 1 << 20)
        except OSError as e:
            raise ValueError(f"The ODA File Converter couldn't be downloaded: {e}") from None
        if msi.read_bytes()[:8] != bytes.fromhex("d0cf11e0a1b11ae1"):  # an installer is an OLE file
            raise ValueError("The Open Design Alliance site didn't send the converter's installer (it may have changed).")
        who = _signer(msi) or ""
        if SIGNER not in who.upper():
            raise ValueError("The downloaded converter isn't signed by the Open Design Alliance, so it wasn't used.")
        target = folder()
        shutil.rmtree(target, ignore_errors=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        run = subprocess.run(["msiexec", "/a", str(msi), "/qn", f"TARGETDIR={target}"], timeout=600,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if run.returncode != 0 or not exe.is_file():
            raise ValueError(f"The converter couldn't be unpacked (msiexec said {run.returncode}).")
    if SIGNER not in (_signer(exe) or "").upper():
        shutil.rmtree(folder(), ignore_errors=True)
        raise ValueError("The unpacked converter isn't signed by the Open Design Alliance, so it was removed.")
    return exe
