"""The loaded document as the viewer sees it: bodies → faces → edges → vertices, with triangles and
polylines to draw, plus what the measure tool needs to know about each entity.

Faces are stored body by body, each face with its own run of vertices (so normals can be smooth
inside a face and sharp between faces) and its own run of triangles. Edges are runs of line
segments. Everything is in millimetres.
"""

import json

import numpy as np


class Model:
    kind = "brep"  # "brep" (exact CAD geometry behind it) or "mesh" (triangles only)

    def __init__(self, name, path, fmt):
        self.name, self.path, self.format = name, path, fmt
        self.units = "mm"
        self.warnings = []
        self.notices = []  # things the user should be told when the file opens (missing assembly parts)
        self.material = None  # {"name", "density" g/cm³ or None, "perBody"} when the file names materials
        self.info = {}  # extra lines for the document panel: {"Application": "SolidWorks 2024", ...}
        self.bodies = []  # dicts: name, path, kind, color, faces=(start, count)
        # faces
        self.face_type, self.face_color, self.face_params = [], [], []
        self.face_body = []
        self.face_vstart, self.face_vcount, self.face_tstart, self.face_tcount = [], [], [], []
        self.positions = np.zeros((0, 3), np.float32)
        self.normals = np.zeros((0, 3), np.float32)
        self.indices = np.zeros((0, 3), np.uint32)
        # edges
        self.edge_type, self.edge_params, self.edge_length = [], [], []
        self.edge_faces, self.edge_seam = [], []
        self.edge_sstart, self.edge_scount = [], []
        self.segments = np.zeros((0, 2, 3), np.float32)
        # vertices
        self.vertices = np.zeros((0, 3), np.float64)
        self.stats = {}

    # ------------------------------------------------------------------ geometry helpers
    def face_triangles(self, f):
        """(points (n, 3), triangles (m, 3)) of one face, in its own vertex numbering."""
        v0, vn = self.face_vstart[f], self.face_vcount[f]
        t0, tn = self.face_tstart[f], self.face_tcount[f]
        return self.positions[v0:v0 + vn].astype(np.float64), self.indices[t0:t0 + tn].astype(np.int64) - v0

    def edge_points(self, e):
        s0, sn = self.edge_sstart[e], self.edge_scount[e]
        return self.segments[s0:s0 + sn].reshape(-1, 3).astype(np.float64)

    def bbox(self):
        pts = [p for p in (self.positions, self.segments.reshape(-1, 3), self.vertices) if len(p)]
        if not pts:
            return [0, 0, 0, 0, 0, 0]
        allp = np.concatenate([np.asarray(p, np.float64) for p in pts])
        return [*map(float, allp.min(axis=0)), *map(float, allp.max(axis=0))]

    # ------------------------------------------------------------------ to the browser
    def payload(self):
        """(meta dict, binary blob). The blob holds the big arrays back to back (4-byte aligned);
        meta["buffers"] says where each one starts."""
        arrays = {
            "positions": np.ascontiguousarray(self.positions, np.float32),
            "normals": np.ascontiguousarray(self.normals, np.float32),
            "indices": np.ascontiguousarray(self.indices, np.uint32),
            "segments": np.ascontiguousarray(self.segments, np.float32),
            "vertices": np.ascontiguousarray(self.vertices, np.float32),
        }
        layout, parts, offset = {}, [], 0
        for key, arr in arrays.items():
            raw = arr.tobytes()
            layout[key] = {"offset": offset, "length": arr.size, "dtype": str(arr.dtype)}
            parts.append(raw)
            offset += len(raw)
            pad = (-offset) % 4
            if pad:
                parts.append(b"\0" * pad)
                offset += pad
        tri_count = len(self.indices)
        meta = {
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "format": self.format,
            "units": self.units,
            "bbox": self.bbox(),
            "info": self.info,
            "warnings": self.warnings,
            "notices": getattr(self, "notices", []),  # models cached before notices existed have none
            "material": getattr(self, "material", None),
            "configs": getattr(self, "configs", []),  # SolidWorks part configurations [{"id", "name"}]
            "config": getattr(self, "config", None),
            "stats": {**self.stats, "triangles": int(tri_count), "faces": len(self.face_type),
                      "edges": len(self.edge_type), "vertices": int(len(self.vertices)), "bodies": len(self.bodies)},
            "bodies": self.bodies,
            "faces": {
                "type": self.face_type,
                "body": [int(b) for b in self.face_body],
                "color": self.face_color,
                "params": self.face_params,
                "vstart": [int(x) for x in self.face_vstart],
                "vcount": [int(x) for x in self.face_vcount],
                "tstart": [int(x) for x in self.face_tstart],
                "tcount": [int(x) for x in self.face_tcount],
            },
            "edges": {
                "type": self.edge_type,
                "params": self.edge_params,
                "length": [round(float(x), 9) for x in self.edge_length],
                "faces": self.edge_faces,
                "seam": self.edge_seam,
                "sstart": [int(x) for x in self.edge_sstart],
                "scount": [int(x) for x in self.edge_scount],
            },
            "buffers": layout,
        }
        return meta, b"".join(parts)


def jsonable(x):
    """numpy scalars / arrays → plain Python, rounded so the JSON stays small."""
    if isinstance(x, dict):
        return {k: jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return jsonable(x.tolist())
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return round(v, 10) if np.isfinite(v) else None
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


def dumps(meta):
    return json.dumps(jsonable(meta), separators=(",", ":"))
