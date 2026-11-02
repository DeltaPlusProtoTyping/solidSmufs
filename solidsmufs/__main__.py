"""python -m solidsmufs [file] [--browser | --no-open] [--port N]"""

import multiprocessing
import sys


def _hand_to_running_window(argv):
    """When a WMC Viewer window is already open, give it the files straight through its pipe and
    stop: this skips loading Qt, so a right-click on another part opens its tab at once."""
    if sys.platform != "win32" or any(a.startswith("--") for a in argv):
        return False
    import getpass
    import json
    from pathlib import Path

    from solidsmufs.kernel.formats import ALL_FORMATS

    files = [str(Path(a).resolve()) for a in argv if Path(a).suffix.lower() in ALL_FORMATS]
    try:
        # the name app.py gives its QLocalServer, which Qt puts under \\.\pipe\ on Windows
        with open(rf"\\.\pipe\SolidSmufs-{getpass.getuser()}", "wb", buffering=0) as pipe:
            pipe.write(json.dumps(files).encode())
        return True
    except OSError:  # no window yet (or it's busy): the normal start sorts it out
        return False


def main():
    multiprocessing.freeze_support()
    if _hand_to_running_window(sys.argv[1:]):
        return
    from solidsmufs.app import run

    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
