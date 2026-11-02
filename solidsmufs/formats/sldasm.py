"""SolidWorks assemblies (.sldasm): which part files, in which configuration, placed where.

An assembly holds no geometry of its own; it names its component files and places each one:

* ``swXmlContents/COMPINSTANCETREE`` (XML): every referenced file (``swFile``: id, saved path) and every
  model used (``swModel``: name, configuration name and id, file id). A configuration id is the ``n`` of
  the part's ``Contents/Config-<n>-Partition`` stream, so it picks the right shape of a multi-config part.
* ``Contents/Config-<n>`` (an MFC archive, one per assembly configuration): one record per top-level
  component: its name (``bracket-1``) as an MFC string, an 8-byte timestamp, ``02 00``, four bytes, ``01``
  (then ``00 00 00 01`` in files from newer versions), then a flag. Flag 1: a 3x3
  rotation, a translation (metres) and a scale, as doubles; flag 0: only the translation and scale. The
  first string after the record is the component's configuration name.

Sub-assemblies are read the same way from their own files. The layout was worked out from the SolidWorks
2025 sample assemblies; every record is checked (rotation orthonormal, scale 1) and others are skipped.
"""

import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .parasolid import UnsupportedFile
from .parasolid.containers import sw_streams

NS = "{http://www.solidworks.com/sw2003/schema}"
# A record starts with a Windows timestamp (high half first: its top byte is 01 and the next C0-DF for
# years 2000-2030), then 02 00, four bytes (zero in most files), 01, and in files from newer versions
# 00 00 00 01; then the placement flag.
RECORD_START = re.compile(rb"..[\xc0-\xdf]\x01.{4}\x02\x00.{4}\x01", re.S)
RECORD_NEWER = bytes.fromhex("00000001")
MFC_STRING = b"\xff\xfe\xff"
MAX_NAME_GAP = 320  # a record starts 120-260 bytes after its component's name (sample files); lights etc. sit far away
MAX_DEPTH = 16  # sub-assemblies inside sub-assemblies; deeper means a loop in the file references
SEARCH_LIMIT = 20000  # files looked at when hunting for a moved part under the assembly's folder
M_TO_MM = 1000.0  # placements are stored in metres; the parts' STEP files are in millimetres


@dataclass
class Placement:
    """One part shown in the assembly."""

    file: Path
    config: int | None  # the part's configuration id (its Config-<n>-Partition), None for its default
    matrix: np.ndarray  # 4x4, millimetres, part coordinates -> assembly coordinates
    path: list  # instance names from the top: ["crank sub-1", "crank-arm-1"]
    hidden: bool = False  # hidden in the assembly's saved display state (shown greyed in the tree)


@dataclass
class Assembly:
    name: str
    placements: list = field(default_factory=list)
    missing: list = field(default_factory=list)  # (instance path text, file name, why)
    files: list = field(default_factory=list)  # every file read (for the cache key)
    infos: dict = field(default_factory=dict)  # (part file, configuration) -> its translation info (looks)
    suppressed: list = field(default_factory=list)  # instance path texts left out (suppressed in SolidWorks)


@dataclass
class _Model:
    name: str
    config_name: str
    config_id: int | None
    saved_path: str


def read(path):
    """The assembly at `path`, flattened to placed parts. Raises UnsupportedFile when it can't be read."""
    path = Path(path)
    asm = Assembly(path.stem)
    _expand(path, None, np.eye(4), [], asm, [], _Finder(), False)
    if not asm.placements and not asm.missing:
        raise UnsupportedFile("No components were found in this assembly.")
    return asm


def dependencies(path):
    """Every file the assembly's geometry comes from (itself, sub-assemblies, parts), for cache keys."""
    try:
        return read(path).files
    except (UnsupportedFile, OSError, ValueError):
        return [Path(path)]


# ---------------------------------------------------------------------------------------------- walk
def _expand(path, config_id, parent, prefix, asm, stack, finder, hidden):
    if len(stack) >= MAX_DEPTH or path.resolve() in stack:
        asm.missing.append(("/".join(prefix), path.name, "the assembly refers to itself"))
        return
    asm.files.append(path)
    streams = sw_streams(str(path), keep=lambda n: n == "swXmlContents/COMPINSTANCETREE"
                         or re.fullmatch(r"Contents/Config-\d+", n) is not None)
    models, saved_self, active = _models(streams.get("swXmlContents/COMPINSTANCETREE"))
    data = _config_stream(streams, config_id if config_id is not None else active)
    if data is None:
        raise UnsupportedFile(f"{path.name}: no component list was found (an unsupported assembly format?).")
    states = _states(streams.get("swXmlContents/COMPINSTANCETREE"), config_id if config_id is not None else active)
    for name, cfg_name, matrix in _records(data):
        model = _match(models, name, cfg_name)
        inst = prefix + [name]
        if model is None:
            continue  # records of the same type that aren't parts (lights such as "Directional-1")
        state = states.get(name, {})
        if state.get("suppressed"):  # still has a placement record, but SolidWorks doesn't show or count it
            asm.suppressed.append("/".join(inst))
            continue
        hide = hidden or bool(state.get("hidden"))
        file_name = Path(model.saved_path.replace("\\", "/")).name
        if "^" in name:
            asm.missing.append(("/".join(inst), file_name, "a virtual part stored inside the assembly"))
            continue
        found = _resolve(model.saved_path, saved_self, path, finder)
        if found is None:
            asm.missing.append(("/".join(inst), file_name, "file not found"))
            continue
        world = parent @ matrix
        ext = found.suffix.lower()
        if ext == ".sldasm":
            _expand(found, model.config_id, world, inst, asm, stack + [path.resolve()], finder, hide)
        elif ext == ".sldprt":
            asm.placements.append(Placement(found, model.config_id, world, inst, hide))
            if found not in asm.files:
                asm.files.append(found)
        else:
            asm.missing.append(("/".join(inst), file_name, f"{ext or 'this kind of'} files can't be read"))


def _models(xml):
    """([_Model], the assembly's own saved path, its active configuration id) from COMPINSTANCETREE."""
    if not xml:
        return [], None, None
    try:
        root = ET.fromstring(xml.decode("utf-8", "replace"))
    except ET.ParseError:
        return [], None, None
    files = {f.get("id"): f for f in root.iter(NS + "swFile")}
    first = next(iter(files.values()), None)
    saved_self = first.get("swPath") if first is not None and first.get("swDocType") == "ASSEMBLY" else None
    models = []
    for m in root.iter(NS + "swModel"):
        f = files.get(m.get("swFileRef"))
        if f is None or not m.get("swName"):
            continue
        cid = m.get("swConfigurationId")
        models.append(_Model(m.get("swName"), m.get("swConfigurationName") or "",
                             int(cid) if cid and cid.lstrip("-").isdigit() else None, f.get("swPath") or ""))
    active = None
    for c in root.iter(NS + "swConfiguration"):
        if c.get("swMostRecentConfiguration") == "YES" and (c.get("swID") or "").isdigit():
            active = int(c.get("swID"))
    return models, saved_self, active


def _states(xml, config_id):
    """{component instance name ("pin-2"): {"suppressed": bool, "hidden": bool}} for the assembly's own
    components in configuration `config_id`, from COMPINSTANCETREE: the swConfiguration's swModelRef is the
    assembly itself in that configuration, and its swReference children carry swSuppressed / swHidden
    (hidden as in the display state it was saved in). References added since a configuration was last
    rebuilt carry neither and count as shown."""
    if not xml:
        return {}
    try:
        root = ET.fromstring(xml.decode("utf-8", "replace"))
    except ET.ParseError:
        return {}
    configs = list(root.iter(NS + "swConfiguration"))
    cfg = next((c for c in configs if config_id is not None and c.get("swID") == str(config_id)), None)
    if cfg is None:  # (not `or`: an element without children is falsy)
        cfg = next((c for c in configs if c.get("swMostRecentConfiguration") == "YES"), configs[0] if configs else None)
    models = {m.get("id"): m for m in root.iter(NS + "swModel")}
    top = models.get(cfg.get("swModelRef")) if cfg is not None else None
    if top is None:
        return {}
    return {f"{r.get('swName')}-{r.get('swReferenceNumber')}": {"suppressed": r.get("swSuppressed") == "YES",
                                                                 "hidden": r.get("swHidden") == "YES"}
            for r in top.findall(NS + "swReference")}


def _config_stream(streams, config_id):
    if config_id is not None and f"Contents/Config-{config_id}" in streams:
        return streams[f"Contents/Config-{config_id}"]
    ids = sorted(int(n.rsplit("-", 1)[1]) for n in streams if n.startswith("Contents/Config-"))
    return streams[f"Contents/Config-{ids[0]}"] if ids else None


def _match(models, instance, cfg_name):
    """The model a component record uses: same name (without the "-1" instance number), and the same
    configuration when the part is used in several."""
    base = re.sub(r"-\d+$", "", instance).strip().lower()
    hits = [m for m in models if m.name.strip().lower() == base]
    if not hits:
        return None
    return next((m for m in hits if m.config_name == cfg_name), hits[0])


# ---------------------------------------------------------------------------------------------- records
def _records(data):
    """[(component name, configuration name, 4x4 placement in mm)] from a Contents/Config-<n> stream."""
    strings = _mfc_strings(data)
    out, used = [], set()
    for hit in RECORD_START.finditer(data):
        names = [s for s in strings if s[1] <= hit.start() and re.fullmatch(r".+-\d+", s[2])]
        # the name must be this record's own: just before it, and not claimed by an earlier record
        # (lights and other entities share the record layout and would borrow the last component's name)
        if not names or hit.start() - names[-1][1] > MAX_NAME_GAP or names[-1][0] in used:
            continue
        o = hit.end()
        # the newer encoding first: its first byte (00) would otherwise read as a "translation only" flag
        matrix, end = _placement(data, o + len(RECORD_NEWER)) if data[o:o + 4] == RECORD_NEWER else (None, o)
        if matrix is None:
            matrix, end = _placement(data, o)
        if matrix is None:
            continue
        used.add(names[-1][0])
        after = next((s for s in strings if s[0] >= end), None)
        out.append((names[-1][2].strip(), after[2] if after else "", matrix))
    return out


def _placement(data, o):
    """(4x4 matrix in mm, end offset) of the placement after a record marker, or (None, o)."""
    if o >= len(data):
        return None, o
    flag = data[o]
    if flag == 1 and o + 1 + 13 * 8 <= len(data):
        v = struct.unpack_from("<13d", data, o + 1)
        rot, t, scale, end = np.array(v[:9]).reshape(3, 3), v[9:12], v[12], o + 1 + 13 * 8
    elif flag == 0 and o + 1 + 4 * 8 <= len(data):
        v = struct.unpack_from("<4d", data, o + 1)
        rot, t, scale, end = np.eye(3), v[:3], v[3], o + 1 + 4 * 8
    else:
        return None, o
    orthonormal = np.abs(rot @ rot.T - np.eye(3)).max() < 1e-6
    if not orthonormal or abs(np.linalg.det(rot) - 1) > 1e-6 or abs(scale - 1) > 1e-9 or max(map(abs, t)) > 1e4:
        return None, o
    m = np.eye(4)
    m[:3, :3] = rot.T  # stored as rows of the transposed rotation (checked against SolidWorks' own previews)
    m[:3, 3] = np.array(t) * M_TO_MM
    return m, end


def _mfc_strings(data):
    """[(start, end, text)] for every MFC CString in the data: FF FE FF, a length (u8, or FF + u16, or
    FFFF + u32), then that many UTF-16 characters."""
    out, i = [], 0
    while (i := data.find(MFC_STRING, i)) >= 0:
        p = i + 3
        n = data[p] if p < len(data) else 0
        p += 1
        if n == 0xFF:
            n = struct.unpack_from("<H", data, p)[0] if p + 2 <= len(data) else 0
            p += 2
            if n == 0xFFFF:
                n = struct.unpack_from("<I", data, p)[0] if p + 4 <= len(data) else 0
                p += 4
        if 0 < n < 4096 and p + 2 * n <= len(data):
            out.append((i, p + 2 * n, data[p:p + 2 * n].decode("utf-16-le", "replace")))
            i = p + 2 * n
        else:
            i += 3
    return out


# ---------------------------------------------------------------------------------------------- files
class _Finder:
    """Files under a folder by lower-case name, listed once per read (a folder of 50 missing parts
    would otherwise be walked 50 times)."""

    def __init__(self):
        self._index = {}

    def find(self, folder, name):
        if folder not in self._index:
            files = {}
            for i, c in enumerate(folder.rglob("*")):
                if i > SEARCH_LIMIT:
                    break
                files.setdefault(c.name.lower(), c)
            self._index[folder] = files
        hit = self._index[folder].get(name.lower())
        return hit if hit is not None and hit.is_file() else None


def _resolve(saved, saved_assembly, assembly, finder=None):
    """Find a component file the way SolidWorks does: where it was saved, next to the assembly, at the
    same place relative to the assembly as when saved, then anywhere under the assembly's folder."""
    saved = saved.replace("\\", "/")
    name = Path(saved).name
    folder = assembly.parent
    candidates = [Path(saved), folder / name]
    if saved_assembly:
        old = Path(saved_assembly.replace("\\", "/")).parent.as_posix().lower()
        if saved.lower().startswith(old + "/"):
            candidates.append(folder / saved[len(old) + 1:])
    for c in candidates:
        try:
            if c.is_file():
                return c
        except OSError:  # a saved path on a drive this PC doesn't have
            pass
    return (finder or _Finder()).find(folder, name)
