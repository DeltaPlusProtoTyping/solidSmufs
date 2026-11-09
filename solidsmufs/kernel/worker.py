"""The worker process behind one open document.

It owns that document's geometry (a gmsh/OpenCASCADE model, or a mesh) and answers requests sent
over a multiprocessing pipe: (request id, command, keyword args) in; (request id, "progress" |
"ok" | "error", payload) out.
"""

import copy
import hashlib
import json
import os
import pickle
import shutil
import tempfile
import time
import traceback
from pathlib import Path

import numpy as np

from . import looks, massprops, measure
from .geom import unit
from .formats import (ALL_FORMATS, ARCHIVE_FORMATS, ASSEMBLY_FORMATS, CAD_FORMATS, DRAWING_FORMATS, IMAGE_FORMATS,  # noqa: F401
                      MESH_FORMATS, PARASOLID_FORMATS, PDF_FORMATS, PICTURE_FORMATS, PRC_FORMATS, TOOLPATH_FORMATS, U3D_FORMATS)
from .model import jsonable


def prc_placed(piece):
    """A piece just where it was modelled."""
    from ..formats.prc import Placed
    return Placed(piece, np.eye(4), "", None)


def _placed_piece(one, unit_mm, default_name):
    """(name, points in mm, triangles, faces, corner normals, planar flags, colour) of a piece in its place."""
    p, m = one.piece, one.matrix
    points = (p.points @ m[:3, :3].T + m[:3, 3]) * unit_mm
    triangles, normals = p.triangles, p.normals
    turned = m[:3, :3]
    det = float(np.linalg.det(turned))
    if normals is not None and not np.allclose(turned, np.eye(3)):
        if abs(det) > 1e-12:  # normals turn by the inverse transpose, which keeps them square to a scaled surface
            normals = unit_rows_3(normals @ np.linalg.inv(turned))
    if det < 0:  # mirrored: the same triangles now wind the other way
        triangles = triangles[:, [0, 2, 1]]
        if normals is not None:
            normals = normals[:, [0, 2, 1]]
    color = list(one.color) if one.color is not None else None
    to_mm = np.diag([unit_mm, unit_mm, unit_mm, 1.0]) @ m
    return (one.name or default_name, points, triangles, p.faces, normals, p.planar, color, (id(p), to_mm))


def unit_rows_3(n):
    """Corner normals (m, 3, 3) made unit length."""
    length = np.linalg.norm(n, axis=2, keepdims=True)
    length[length == 0] = 1.0
    return n / length


class Session:
    def __init__(self):
        self.model = None
        self.exact = False  # is the exact OpenCASCADE model loaded (not just a cached tessellation)?
        self.path = self.quality = None
        self.config = None  # SolidWorks part configuration shown (its Config-<n> id); None: the file's first
        self.orient = None  # 3x3 rotation the part is turned by (Align Part); None: as modelled
        self.post = None  # work to do after the answer has gone out (writing the cache)
        self.pdf = None  # the PDF behind a .pdf document
        self.password = ""  # what opened it, kept here only for as long as it's open

    # ------------------------------------------------------------------ PDF
    def _open_pdf(self, path, progress):
        from .model import Model
        from .pdfdoc import PdfFile, models_inside
        progress("Reading the PDF", 0.3)
        if self.pdf is not None:
            self.pdf.close()
        self.pdf = PdfFile(path, self.password)
        models, problem = models_inside(path), None
        private = bool(self.password)  # its model isn't to sit unprotected in the cache
        self.model = None
        if models:
            hit = None if private else _mesh_cache_read(path, "pdf", None, self.orient)
            if hit is not None:  # worked out on an earlier opening: only the pages are new
                progress("Opening from cache", 0.5)
                self.model, meta, blob = hit
                self.exact = True
                meta["pdf"] = {"pages": self.pdf.pages(), "title": self.pdf.title(), "models": models, "problem": None}
                meta["stats"]["cached"] = True
                return meta, blob
            progress("Reading the 3D model", 0.5)
            try:
                self.model = self._pdf_model(path)
            except ValueError as e:  # the pages can still be shown (PrcError is a ValueError)
                problem = str(e)
        if self.model is None:
            self.model = Model(Path(path).name, path, "PDF")
            self.model.kind = "pdf"
        elif self.orient is not None:
            _turn_mesh(self.model, self.orient)
        self.exact = True
        meta, blob = self.model.payload()
        meta["pdf"] = {"pages": self.pdf.pages(), "title": self.pdf.title(), "models": models, "problem": problem}
        meta["orient"] = None if self.orient is None else self.orient.tolist()
        meta = jsonable(meta)
        if self.model.kind == "mesh" and not private:
            model, orient = self.model, self.orient
            self.post = lambda: _mesh_cache_write(path, "pdf", model, meta, blob, None, orient)
        return meta, blob

    def _open_picture(self, path, progress):
        """A picture, or the preview picture inside a drawing, shown as pages by the PDF page view."""
        from .model import Model
        from .pictures import open_picture
        progress("Reading the picture", 0.3)
        if self.pdf is not None:
            self.pdf.close()
        ext = Path(path).suffix.lower()
        self.pdf, what = open_picture(path, ext)
        self.model = Model(Path(path).name, path, what)
        self.model.kind = "pdf"
        self.model.info["Picture"] = self.pdf.size_text()
        if ext == ".dwg":
            self.model.notices.append("This is the DWG's preview picture. To see its lines and measure them, "
                                      "install the free ODA File Converter, then open it again.")
        elif ext not in IMAGE_FORMATS:
            self.model.notices.append("This is the preview picture saved in the file, as it looked when it was last saved.")
        self.exact = True
        meta, blob = self.model.payload()
        meta["pdf"] = {"pages": self.pdf.pages(), "title": self.pdf.title(), "models": [], "problem": None, "picture": True}
        return jsonable(meta), blob

    def _shown_as_pages(self, path):
        """Is this file shown by the page view (a PDF, a picture, or a preview picture)?"""
        ext = Path(path).suffix.lower()
        if ext == ".dwg":
            from .pictures import dwg_converter
            return dwg_converter() is None
        return ext in PDF_FORMATS or ext in PICTURE_FORMATS

    def _open_pages(self, path, progress):
        if Path(path).suffix.lower() in PDF_FORMATS:
            return self._open_pdf(path, progress)
        return self._open_picture(path, progress)

    def _pdf_model(self, path):
        """The mesh model from the 3D models in a PDF, in mm."""
        from ..formats import prc, u3d
        prcs, u3ds = prc.read_pdf(path, self.password), u3d.read_pdf(path, self.password)
        kinds = " + ".join(k for k, found in (("PRC", prcs), ("U3D", u3ds)) if found) or "no readable model"
        return self._prc_model(path, prcs + u3ds, f"3D PDF ({kinds})")

    def _prc_model(self, path, files, fmt):
        """A mesh model from read PRC or U3D files. Each piece goes where the file's tree puts it, as many times as it does."""
        from . import meshio
        stem, pieces, warnings, notices, tolerance, lost = Path(path).stem, [], [], [], 0.0, False
        for f in files:
            warnings += f.warnings
            notices += [n for n in f.notices if n not in notices]
            placed = f.placed
            if not placed:  # the tree couldn't be followed, or names none of them: each where it was modelled
                lost = lost or len(f.pieces) > 1
                placed = [prc_placed(p) for p in f.pieces]
            for one in placed:
                pieces.append(_placed_piece(one, f.unit_mm, f.name or stem))
                tolerance = max(tolerance, one.piece.tolerance * f.unit_mm)
        if not pieces:
            raise ValueError(" ".join(warnings) or "This 3D model holds no surfaces to show. (It may be lines alone, such as a plot.)")
        if len(pieces) == 1:
            pieces[0] = (stem, *pieces[0][1:])
        # three axes, each rounded to the nearest tolerance: half of it, on the diagonal
        slack = tolerance * 0.87
        m = meshio.from_faces(path, Path(path).name, fmt, pieces, slack=slack)
        if slack:
            m.info["Accuracy"] = f"\u00b1{slack:.3f} mm (the file's rounding)"
        m.warnings += warnings
        m.notices += notices
        thin = max((f.thin_limit * f.unit_mm for f in files), default=0.0)
        if thin:
            m.stats["thin_limit_mm"] = thin
        if lost:
            m.notices.append("This model's pieces couldn't be put in their assembly positions: each is shown where it was modelled.")
        return m

    def pdf_tile(self, **kw):
        return self.pdf.tile(**kw)

    def pdf_select(self, **kw):
        return self.pdf.select(**kw)

    def pdf_find(self, query):
        return self.pdf.find(query)

    # ------------------------------------------------------------------ loading
    def open(self, path, quality="normal", progress=lambda *a: None, config=None, orient=None, password=None):
        """First look at a file: a cached tessellation when there is one (instant), else a full load.
        {"meta", "blob", "exact"}; when exact is False, ensure_exact() loads the real geometry."""
        self.path, self.quality, self.config, self.orient = path, quality, config, _rotation(orient)
        if password is not None:
            self.password = password
        if self._shown_as_pages(path):
            meta, blob = self._open_pages(path, progress)
            return {"meta": meta, "blob": blob, "exact": True}
        hit = _mesh_cache_read(path, quality, config, self.orient)
        if hit is not None:
            progress("Opening from cache", 0.5)
            self.model, meta, blob = hit
            self.exact = self.model.kind != "brep"
            meta["stats"]["cached"] = True
            meta["orient"] = None if self.orient is None else self.orient.tolist()
            if self.orient is not None:
                meta["notices"] = [*[n for n in meta.get("notices", []) if n != TURNED_NOTICE], TURNED_NOTICE]
            return {"meta": meta, "blob": blob, "exact": self.exact}
        meta, blob = self.load(path, quality, progress)
        return {"meta": meta, "blob": blob, "exact": True}

    def ensure_exact(self, path=None, quality=None, progress=lambda *a: None):
        """Load the exact geometry behind a cached tessellation (no new tessellation needed)."""
        path, quality = path or self.path, quality or self.quality
        if self.exact or self.model is None or self.model.kind != "brep":
            self.exact = True
            return {"changed": False}
        from . import cad
        ext = Path(path).suffix.lower()
        try:
            if ext in PARASOLID_FORMATS:
                step, _info, cleanup = self._parasolid_step(path, ext, progress, self.config)
                try:
                    gmsh = cad.import_only(path, source=step)
                finally:
                    cleanup()
            elif ext in ASSEMBLY_FORMATS:
                gmsh, _asm = self._assembly_import(path, progress)
            else:
                gmsh = cad.import_only(path, sew=CAD_FORMATS.get(ext) == "IGES")
            if self.orient is not None:
                cad.turn(gmsh, self.orient)
            m = self.model
            faces = {t for _, t in gmsh.model.getEntities(2)}
            curves = {t for _, t in gmsh.model.getEntities(1)}
            points = {t for _, t in gmsh.model.getEntities(0)}
            same = (len(faces) == len(m.face_tag) and set(map(int, m.face_tag)) <= faces
                    and set(map(int, m.edge_tag)) <= curves and set(map(int, m.vert_tag)) <= points)
        except Exception:
            same = False
        if same:
            self._wire_exact()
            self.exact = True
            return {"changed": False}
        meta, blob = self.load(path, quality, progress)  # the cache didn't match: start over
        return {"changed": True, "meta": meta, "blob": blob}

    def load(self, path, quality="normal", progress=lambda *a: None, config="keep", orient="keep"):
        if config != "keep":
            self.config = config
        if orient != "keep":
            self.orient = _rotation(orient)
        ext = Path(path).suffix.lower()
        name = Path(path).name
        if self._shown_as_pages(path):
            self.path, self.quality = path, quality
            return self._open_pages(path, progress)
        if ext not in ALL_FORMATS or ext in ARCHIVE_FORMATS:
            raise ValueError(f"Can't open {ext or 'this kind of'} files.")
        self.path, self.quality = path, quality
        t0 = time.perf_counter()
        if ext in PRC_FORMATS or ext in U3D_FORMATS:
            from ..formats import prc, u3d
            progress("Reading the model", 0.3)
            data = Path(path).read_bytes()
            self.model = self._prc_model(path, [prc.read_prc(data) if ext in PRC_FORMATS else u3d.read_u3d(data)], ALL_FORMATS[ext])
            if self.orient is not None:
                _turn_mesh(self.model, self.orient)
        elif ext in CAD_FORMATS:
            from . import cad
            self.model = cad.load(path, name, CAD_FORMATS[ext], quality, progress, sew=CAD_FORMATS[ext] == "IGES",
                                  orient=self.orient)
        elif ext in PARASOLID_FORMATS:
            self.model = self._load_parasolid(path, name, ext, quality, progress)
        elif ext in ASSEMBLY_FORMATS:
            self.model = self._load_assembly(path, name, quality, progress)
        elif ext in DRAWING_FORMATS:
            from . import drawing
            from ..formats.dxf import DxfError
            try:
                if ext == ".dwg":
                    self.model = _load_dwg(path, name, progress)
                else:
                    self.model = drawing.load(path, name, progress)
            except DxfError as e:
                raise ValueError(str(e)) from None
            self.orient = None  # a flat drawing isn't turned by Align Part
        elif ext in TOOLPATH_FORMATS:
            from . import toolpath
            self.model = toolpath.load(path, name, progress)
            self.orient = None  # a program's moves are where the machine makes them
        else:
            from . import meshio
            self.model = meshio.load(path, name, MESH_FORMATS[ext], progress)
            if self.orient is not None:
                _turn_mesh(self.model, self.orient)
        self._wire_exact()
        self.exact = True
        self.model.stats["load_s"] = round(time.perf_counter() - t0, 3)
        progress("Sending to the view", 0.95)
        meta, blob = self.model.payload()
        meta["orient"] = None if self.orient is None else self.orient.tolist()  # turned by Align Part
        if self.orient is not None:
            meta["notices"] = [*[n for n in meta.get("notices", []) if n != TURNED_NOTICE], TURNED_NOTICE]
        meta = jsonable(meta)
        if self.model.kind == "brep" or ext in PRC_FORMATS or ext in U3D_FORMATS:
            model, config, orient = self.model, self.config, self.orient
            self.post = lambda: _mesh_cache_write(path, quality, model, meta, blob, config, orient)
        return meta, blob

    def _parasolid_step(self, path, ext, progress, config=None):
        """(STEP path, translator info, cleanup) for a SolidWorks / Parasolid file (configuration `config`
        of a SolidWorks part, else its first), translating once and keeping the STEP in the cache."""
        try:
            from ..formats import parasolid
        except ImportError:
            raise ValueError("The SolidWorks / Parasolid reader isn't installed.") from None
        progress("Reading " + PARASOLID_FORMATS[ext], 0.05)
        cached = _cache_paths(path, config)
        if cached and cached[0].is_file() and cached[1].is_file():
            try:
                return cached[0], json.loads(cached[1].read_text(encoding="utf-8")), lambda: None
            except (OSError, ValueError):
                pass
        work = Path(tempfile.mkdtemp(prefix="solidsmufs-"))
        step = work / "model.step"
        try:
            info = parasolid.to_step(str(path), str(step), config)
        except parasolid.UnsupportedFile as e:
            shutil.rmtree(work, ignore_errors=True)
            raise ValueError(str(e)) from None
        if cached:  # translated once; next time straight to OpenCASCADE
            try:
                shutil.copyfile(step, cached[0])
                cached[1].write_text(json.dumps(info), encoding="utf-8")
            except OSError:
                pass
        return step, info, lambda: shutil.rmtree(work, ignore_errors=True)

    def _load_parasolid(self, path, name, ext, quality, progress):
        from . import cad
        step, info, cleanup = self._parasolid_step(path, ext, progress, self.config)
        try:
            m = cad.load(path, name, info.get("format") or PARASOLID_FORMATS[ext], quality, progress, source=step,
                         orient=self.orient)
        finally:
            cleanup()
        if info.get("app"):
            m.info["Created by"] = info["app"]
        m.warnings += list(info.get("warnings") or [])
        m.configs, m.config = info.get("configurations") or [], info.get("config")
        m.hole_wizard = list(info.get("hole_wizard") or [])  # SolidWorks Hole Wizard types, e.g. "M10x1.5 Tapped Hole"
        if m.hole_wizard:
            from collections import Counter
            m.info["Hole Wizard"] = ", ".join(f"{n}× {t}" if n > 1 else t for t, n in Counter(m.hole_wizard).items())
        looks.apply(m, info)
        _set_material(m)
        return m

    def _assembly_import(self, path, progress):
        """(gmsh, Assembly): read a SolidWorks assembly, translate each part configuration it uses once
        (through the STEP cache) and place every instance. Parts that can't be read join asm.missing."""
        from ..formats import parasolid, sldasm
        from . import cad
        progress("Reading the assembly", 0.03)
        try:
            asm = sldasm.read(path)
        except parasolid.UnsupportedFile as e:
            raise ValueError(str(e)) from None
        groups = {}  # (part file, configuration) -> [(matrix, instance names)], in file order
        for p in asm.placements:
            groups.setdefault((str(p.file), p.config), []).append((p.matrix, p.path))
        parts, cleanups = [], []
        try:
            for i, ((file, config), instances) in enumerate(groups.items()):
                progress(f"Reading part {i + 1} of {len(groups)}", 0.05 + 0.3 * i / max(len(groups), 1))
                try:
                    step, info, cleanup = self._parasolid_step(file, ".sldprt", lambda *a: None, config)
                    asm.infos[(file, config)] = info
                except ValueError as e:
                    asm.missing += [("/".join(names), Path(file).name, str(e)) for _m, names in instances]
                    continue
                cleanups.append(cleanup)
                parts.append((step, instances))
            if not parts:
                raise ValueError("None of this assembly's parts could be shown. " + _missing_text(asm.missing))
            failed = []
            gmsh = cad.import_assembly(parts, asm.name, failed)
            for index, why in failed:
                step, instances = parts[index]
                file = next(f for (f, _c), insts in groups.items() if insts is instances)
                asm.missing += [("/".join(names), Path(file).name, why) for _m, names in instances]
            if len(failed) == len(parts):
                raise ValueError("None of this assembly's parts could be shown. " + _missing_text(asm.missing))
            return gmsh, asm
        finally:
            for cleanup in cleanups:
                cleanup()

    def _load_assembly(self, path, name, quality, progress):
        from . import cad
        found = {}
        m = cad.load(path, name, ASSEMBLY_FORMATS[".sldasm"], quality, progress, orient=self.orient,
                     importer=lambda: found.setdefault("gmsh", self._assembly_import(path, progress))[0])
        asm = found["gmsh"][1]
        m.info["Components"] = str(len(asm.placements))
        part_of = {"/".join(p.path): (str(p.file), p.config) for p in asm.placements}
        instances = {}  # (instance path, part) -> its body indices, in order
        for bi, b in enumerate(m.bodies):
            inst = "/".join(n.replace("::", "-") for n in b.get("path") or [] if "::" in n)
            if inst in part_of:
                instances.setdefault((inst, part_of[inst]), []).append(bi)
        hidden = {"/".join(p.path) for p in asm.placements if p.hidden}
        for (inst, part), bodies in instances.items():
            if part in asm.infos:
                looks.apply(m, asm.infos[part], bodies)
            if inst in hidden:  # hidden in SolidWorks: loaded, but starts hidden (show it from the tree)
                for bi in bodies:
                    m.bodies[bi]["hidden"] = True
        if asm.suppressed:
            m.info["Suppressed"] = f"{len(asm.suppressed)} component{'s' if len(asm.suppressed) != 1 else ''} (not shown or counted)"
        _set_material(m)
        if asm.missing:
            m.warnings.append(_missing_text(asm.missing))
            m.notices.append(_missing_text(asm.missing))
        return m

    def reload(self, path, quality="normal", progress=lambda *a: None, config="keep", orient="keep"):
        return self.load(path, quality, progress, config, orient)

    def facing(self, refs):
        """For Align Part's arrows: [{"dir": the way each pick faces (or None), "at": its middle}]; the
        first also gets "length", the part's length direction square to it (the Bounding Box fit)."""
        m, out = self.model, []
        for r in refs:
            i = int(r.get("index", -1))
            pts = m.face_triangles(i)[0] if r.get("kind") == "face" else m.edge_points(i) if r.get("kind") == "edge" else np.zeros((0, 3))
            out.append({"dir": _facing(m, r), "at": pts.mean(axis=0) if len(pts) else None})
        if out and out[0]["dir"] is not None:
            d1 = out[0]["dir"]
            allp = np.concatenate([np.asarray(m.positions, np.float64), np.asarray(m.vertices, np.float64)])
            ln = np.asarray(massprops.reference_axes(allp, [d1])[0], np.float64)
            out[0]["length"] = unit(ln - d1 * float(ln @ d1))
        return jsonable(out)

    def align(self, refs, targets):
        """The rotation (3x3, on top of the current one) that turns the picked faces / edges to face the
        given directions: refs[0] to targets[0] exactly, refs[1] (optional) as near targets[1] as it can
        go. With one pick the part also turns about it so its length runs along targets[1], the way the
        Bounding Box fits. Returns {"orient": 3x3 total, "turn": 3x3 this step}; reload with orient to
        turn the part (turn's rows are where the new X / Y / Z point on the part as it is now)."""
        m = self.model
        if not refs:
            raise ValueError("Pick a flat face, a round face or a straight edge to align to.")
        t1 = unit(np.asarray(targets[0], np.float64))
        t2 = np.asarray(targets[1], np.float64) if len(targets) > 1 else (np.eye(3)[0] if abs(t1[0]) < 0.9 else np.eye(3)[2])
        t2 = unit(t2 - t1 * float(t2 @ t1))
        d1 = _facing(m, refs[0])
        if d1 is None:
            raise ValueError("The first pick has no direction: use a flat face, a round face or a straight edge.")
        if len(refs) > 1:
            d2 = _facing(m, refs[1])
            if d2 is None:
                raise ValueError("The second pick has no direction: use a flat face, a round face or a straight edge.")
            d2 = d2 - d1 * float(d2 @ d1)
            if np.linalg.norm(d2) < 1e-6:
                raise ValueError("The second pick lines up with the first; pick one that points another way.")
        else:  # the part's length, square to the first pick, pointing the way nearer the target
            pts = np.concatenate([np.asarray(m.positions, np.float64), np.asarray(m.vertices, np.float64)])
            d2 = np.asarray(massprops.reference_axes(pts, [d1])[0], np.float64)
            d2 = d2 - d1 * float(d2 @ d1)
            if float(d2 @ t2) < 0:
                d2 = -d2
        d2 = unit(d2)
        frame_now = np.stack([d1, d2, np.cross(d1, d2)], axis=1)
        frame_then = np.stack([t1, t2, np.cross(t1, t2)], axis=1)
        cur = self.orient if self.orient is not None else np.eye(3)
        turn = frame_then @ frame_now.T
        return jsonable({"orient": turn @ cur, "turn": turn})

    def _wire_exact(self):
        """Give the model an exact face-area lookup when OpenCASCADE is behind it."""
        m = self.model
        if m.kind != "brep":
            return
        import gmsh

        def exact_area(f):
            if f not in m.area_cache:
                try:
                    m.area_cache[f] = gmsh.model.occ.getMass(2, int(m.face_tag[f]))
                except Exception:
                    m.area_cache[f] = None
            return m.area_cache[f]

        def exact_centroid(f):
            try:
                return np.asarray(gmsh.model.occ.getCenterOfMass(2, int(m.face_tag[f])), np.float64)
            except Exception:
                return None

        def exact_curvature(kind, i, pts):
            """Curvatures at points on a face ((tightest, gentlest) per point) or an edge (per point)."""
            flat = np.asarray(pts, np.float64).ravel().tolist()
            if kind == "face":
                tag = int(m.face_tag[i])
                k1, k2, _d1, _d2 = gmsh.model.getPrincipalCurvatures(tag, gmsh.model.getParametrization(2, tag, flat))
                k1, k2 = np.abs(np.asarray(k1, np.float64)), np.abs(np.asarray(k2, np.float64))
                return np.maximum(k1, k2), np.minimum(k1, k2)
            tag = int(m.edge_tag[i])
            return np.abs(np.asarray(gmsh.model.getCurvature(1, tag, gmsh.model.getParametrization(1, tag, flat)), np.float64))

        m.exact_area = exact_area
        m.exact_centroid = exact_centroid
        m.exact_curvature = exact_curvature

    # ------------------------------------------------------------------ tools
    def measure(self, selection, options=None):
        m = self.model
        sel = [dict(s) for s in selection]
        if m.kind == "brep":
            import gmsh
            for s in sel:  # picked points sit on the tessellation: put them on the true surface
                if s["kind"] == "point" and s.get("face") is not None:
                    try:
                        p, _ = gmsh.model.getClosestPoint(2, int(m.face_tag[int(s["face"])]), list(map(float, s["point"])))
                        s["point"] = list(map(float, p[:3]))
                    except Exception:
                        pass
        res = measure.measure(m, sel, options or {}, self._exact_distance)
        return jsonable(res)

    def _exact_distance(self, a, b):
        m = self.model
        if m.kind != "brep":
            return _mesh_distance(m, a, b)
        import gmsh
        occ = gmsh.model.occ
        temps = []

        def ref(e):
            if e.kind == "face":
                return 2, int(m.face_tag[e.index])
            if e.kind == "edge":
                return 1, int(m.edge_tag[e.index])
            if e.kind == "vertex":
                return 0, int(m.vert_tag[e.index])
            t = occ.addPoint(*map(float, e.point()))
            temps.append(t)
            return 0, t

        try:
            (d1, t1), (d2, t2) = ref(a), ref(b)
            d, x1, y1, z1, x2, y2, z2 = occ.getDistance(d1, t1, d2, t2)
            if d < 0:
                return None
            return d, np.array([x1, y1, z1]), np.array([x2, y2, z2])
        except Exception:
            return _mesh_distance(m, a, b)
        finally:
            if temps:
                try:
                    occ.remove([(0, t) for t in temps])
                except Exception:
                    pass

    def massprops(self, bodies=None, density=1.0):
        """density None: each body's own (from its material in the file)."""
        m = self.model
        bodies = list(range(len(m.bodies))) if bodies is None else [int(b) for b in bodies]
        if m.kind == "brep":
            res = massprops.cad_mass(m, bodies, None if density is None else float(density))
        else:
            res = massprops.mesh_mass(m, bodies, 1.0 if density is None else float(density))
        return jsonable(res)

    def bbox(self, bodies=None, mode="world", refs=None):
        """Exact box around the bodies: along world XYZ, best fit ("oriented"), or "reference": aligned to
        picked faces / edges (refs: [{"kind", "index"}]; the first sets the height direction)."""
        m = self.model
        bodies = list(range(len(m.bodies))) if bodies is None else [int(b) for b in bodies]
        axes = None
        if mode in ("oriented", "reference"):
            pts = [m.face_triangles(f)[0] for b in bodies
                   for f in range(m.bodies[b]["faces"][0], sum(m.bodies[b]["faces"]))]
            pts = [p for p in pts if len(p)]
            dirs = [d for d in (_direction(m, r) for r in refs or []) if d is not None]
            if mode == "reference" and not dirs:
                raise ValueError("Pick a flat or round face (or a straight edge) to line the box up with.")
            if pts:
                pts = np.concatenate(pts)
                axes = massprops.reference_axes(pts, dirs) if mode == "reference" else _best_fit_axes(m, bodies, pts)
        if m.kind == "brep":
            res = massprops.cad_bbox(m, bodies, axes)
        else:
            res = massprops.mesh_bbox(m, bodies, axes)
        if res is not None:
            res["mode"] = mode
        return jsonable(res)

    def save_step(self, out):
        from . import export
        return export.save_step(self, out)

    def section_props(self, faces):
        """Area properties of flat faces: area, centroid and second moments of area (mm, mm², mm⁴)."""
        m = self.model
        faces = [int(f) for f in faces]
        parts = []
        normal = None
        for f in faces:
            p = m.face_params[f] or {}
            if normal is None and p.get("normal") is not None:
                normal = np.asarray(p["normal"], np.float64)
            if m.kind == "brep" and self.exact:
                import gmsh
                tag = int(m.face_tag[f])
                a = gmsh.model.occ.getMass(2, tag)
                c = np.asarray(gmsh.model.occ.getCenterOfMass(2, tag), np.float64)
                i = np.asarray(gmsh.model.occ.getMatrixOfInertia(2, tag), np.float64).reshape(3, 3)
            else:
                a, c, i = _area_integrals(*m.face_triangles(f))
            parts.append((a, c, i))
        area, centroid, inertia = massprops.combine(parts)
        if normal is None:
            normal = np.array([0.0, 0.0, 1.0])
        n = normal / np.linalg.norm(normal)
        x = np.cross(n, [1, 0, 0]) if abs(n[0]) < 0.9 else np.cross(n, [0, 1, 0])
        x /= np.linalg.norm(x)
        y = np.cross(n, x)
        basis = np.stack([x, y])
        w = np.linalg.eigvalsh(basis @ inertia @ basis.T)
        return jsonable({"area": area, "centroid": centroid, "inertia": inertia, "polar": float(n @ inertia @ n),
                         "principal": np.sort(w), "normal": n})

    def holes(self):
        """Round holes: cylindrical faces whose material wraps around them, grouped by axis and
        radius into hole features, then by diameter. Depth is the length along the axis; a hole
        with no bottom face (flat or drill point) counts as through. Holes with a modelled thread
        carry its size; the rest say what their diameter most likely is (tap drill, clearance, drill)."""
        from . import threads
        from .geom import unit
        m = self.model
        feats = []
        for f, t in enumerate(m.face_type):
            p = m.face_params[f]
            if t != "cylinder" or not p:
                continue
            pts, tri = m.face_triangles(f)
            if not len(tri):
                continue
            v0 = m.face_vstart[f]
            nrm = np.asarray(m.normals[v0:v0 + m.face_vcount[f]], np.float64)
            c, a = np.asarray(p["center"], np.float64), unit(p["axis"])
            if a[np.argmax(np.abs(a))] < 0:
                a = -a
            rel = pts - c
            radial = rel - np.outer(rel @ a, a)
            if float(np.einsum("ij,ij->i", radial, nrm).mean()) >= 0:  # normals point away from the axis: a boss
                continue
            x = unit(np.cross(a, [1, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1, 0]))
            ang = np.degrees(np.arctan2(radial @ np.cross(a, x), radial @ x)) % 360
            feats.append({"face": f, "r": float(p["radius"]), "c": c, "a": a, "bins": set((ang // 5).astype(int).tolist()),
                          "t": (float((rel @ a).min()), float((rel @ a).max()))})
        # coaxial faces of one radius are one hole (SolidWorks splits a hole into two half faces)
        holes = []
        for ft in feats:
            for hole in holes:
                d = ft["c"] - hole["c"]
                off = np.linalg.norm(d - (d @ hole["a"]) * hole["a"])
                if abs(ft["r"] - hole["r"]) < 1e-4 and abs(abs(ft["a"] @ hole["a"]) - 1) < 1e-6 and off < 1e-4:
                    s = float(d @ hole["a"])
                    hole["faces"].append(ft["face"])
                    hole["bins"] |= ft["bins"]
                    hole["t"] = (min(hole["t"][0], ft["t"][0] + s), max(hole["t"][1], ft["t"][1] + s))
                    break
            else:
                holes.append({"r": ft["r"], "c": ft["c"], "a": ft["a"], "faces": [ft["face"]], "bins": set(ft["bins"]), "t": ft["t"]})
        result, threaded = [], set()

        def thread_of(faces):
            for f in faces:
                try:
                    th = threads.modelled(m, f)
                except Exception:
                    th = None
                if th and th["internal"] is not False and th["callout"]:
                    return th
            return None

        for hole in holes:
            th = thread_of(hole["faces"])
            if len(hole["bins"]) < 64 and not th:  # less than ~320°: a slot end, fillet or partial bore, not a hole
                continue
            if th and threaded & set(th["faces"]):
                continue  # another strip of a thread already counted
            if th:
                threaded |= set(th["faces"])
                hole = {**hole, "faces": sorted(set(hole["faces"]) | set(th["faces"])), "r": th["thread"]["major"] / 2}
            result.append({"diameter": 2 * hole["r"], "depth": th["length"] if th else hole["t"][1] - hole["t"][0],
                           "through": not self._hole_has_bottom(hole), "faces": hole["faces"], "thread": th and th["callout"]})
        # threads modelled with no plain cylinder in them
        for f, t in enumerate(m.face_type):
            if t in threads.FREEFORM and f not in threaded:
                th = thread_of([f])
                if th and not threaded & set(th["faces"]):
                    threaded |= set(th["faces"])
                    hole = {"faces": th["faces"], "r": th["thread"]["major"] / 2, "a": th["axis"]}
                    result.append({"diameter": th["thread"]["major"], "depth": th["length"], "through": not self._hole_has_bottom(hole),
                                   "faces": th["faces"], "thread": th["callout"]})
        groups = {}
        for r in result:
            g = groups.setdefault((r["thread"], round(r["diameter"], 3)), {"diameter": r["diameter"], "count": 0, "depths": [], "through": True,
                                                                         "faces": [], "thread": r["thread"]})
            g["count"] += 1
            g["depths"].append(r["depth"])
            g["through"] = g["through"] and r["through"]
            g["faces"] += r["faces"]
        out = []
        for g in sorted(groups.values(), key=lambda g: g["diameter"]):
            hw = None if g["thread"] else threads.hole_wizard_thread(m, g["diameter"])  # a plain hole the Hole Wizard taps
            likely = ([f"{g['thread']} tapped (modelled thread)"] if g["thread"]
                      else [f"{hw['callout']} tapped (Hole Wizard)"] if hw else threads.likely(g["diameter"]))
            out.append({"diameter": g["diameter"], "count": g["count"], "depth_min": min(g["depths"]), "depth_max": max(g["depths"]),
                        "through": g["through"], "faces": g["faces"], "thread": g["thread"] or (hw and hw["callout"]), "likely": likely})
        return jsonable({"groups": out, "holes": len(result)})

    def _hole_has_bottom(self, hole):
        """Is the hole closed at one end by a face across it (flat bottom or a drill point)?"""
        from .measure import face_area
        m = self.model
        faces = set(hole["faces"])
        for fs in m.edge_faces:
            if not faces & set(fs):
                continue
            for g in fs:
                if g in faces:
                    continue
                t, p = m.face_type[g], m.face_params[g] or {}
                if t == "cone" and p.get("axis") is not None and abs(abs(float(np.dot(p["axis"], hole["a"]))) - 1) < 1e-6 \
                        and p.get("radius_max", 0) <= hole["r"] * 1.001:
                    return True
                if t == "plane" and p.get("normal") is not None and abs(abs(float(np.dot(p["normal"], hole["a"]))) - 1) < 1e-6:
                    if face_area(m, g) <= np.pi * hole["r"] ** 2 * 1.02:
                        return True
        return False


def _best_fit_axes(m, bodies, pts):
    """The smallest box we can find: the rotation search, and boxes standing on each of the biggest flat
    faces and on its own axes (machined parts nearly always fit tightest square to a flat face)."""
    cands = [massprops.oriented_axes(pts)]
    faces = [f for b in bodies for f in range(m.bodies[b]["faces"][0], sum(m.bodies[b]["faces"]))
             if m.face_type[f] == "plane" and (m.face_params[f] or {}).get("normal") is not None]
    faces.sort(key=lambda f: -(m.exact_area(f) or 0.0) if hasattr(m, "exact_area") else -m.face_tcount[f])
    normals = []
    for f in faces:
        n = np.asarray(m.face_params[f]["normal"], np.float64)
        if all(abs(float(n @ k)) < 0.9999 for k in normals):
            normals.append(n)
        if len(normals) == 5:
            break
    for d in [*normals, *cands[0]]:
        cands.append(massprops.reference_axes(pts, [d]))
    vol = lambda ax: float(np.prod(np.ptp(pts @ np.asarray(ax).T, axis=0)))
    best = min(cands, key=vol)
    order = np.argsort(-np.ptp(pts @ best.T, axis=0))  # longest first, right-handed, as before
    best = best[order]
    if np.linalg.det(best) < 0:
        best[2] = -best[2]
    return best


def _direction(m, ent):
    """The direction a picked entity lines a box up with: a flat face's normal, a round face's axis, a
    straight edge's direction or a circle's axis. None when it has none (a spline face, a vertex)."""
    kind, i = ent.get("kind"), int(ent.get("index", -1))
    if kind == "face" and 0 <= i < len(m.face_type):
        p = m.face_params[i] or {}
        d = p.get("normal") if m.face_type[i] == "plane" else p.get("axis")
    elif kind == "edge" and 0 <= i < len(m.edge_type):
        p = m.edge_params[i] or {}
        d = p.get("dir") if m.edge_type[i] == "line" else p.get("normal") if m.edge_type[i] == "circle" else None
    else:
        d = None
    return None if d is None else np.asarray(d, np.float64)


TURNED_NOTICE = "Shown in the orientation you set with Align Part (Tools > Align Part > Reset to go back)."


def _rotation(orient):
    """A 3x3 rotation from a request (None, or the identity, means as modelled)."""
    if orient is None:
        return None
    r = np.asarray(orient, np.float64).reshape(3, 3)
    u, _s, vt = np.linalg.svd(r)  # the nearest true rotation, so rounding in transit can't skew the part
    r = u @ vt
    if np.linalg.det(r) < 0:
        raise ValueError("That orientation would mirror the part.")
    return None if np.abs(r - np.eye(3)).max() < 1e-12 else r


def _facing(m, ent):
    """The way a pick faces: a flat face's outward normal (from its triangles), a round face's axis, an
    edge's direction, or a direction given outright ({"dir": [x, y, z]}); None when it has none."""
    if ent.get("dir") is not None:
        return unit(np.asarray(ent["dir"], np.float64))
    d = _direction(m, ent)
    if d is None:
        return None
    d = unit(d)
    if ent.get("kind") == "face" and m.face_type[int(ent["index"])] == "plane":
        pts, tri = m.face_triangles(int(ent["index"]))
        if len(tri):
            n = np.cross(pts[tri[:, 1]] - pts[tri[:, 0]], pts[tri[:, 2]] - pts[tri[:, 0]]).sum(axis=0)
            if float(n @ d) < 0:
                d = -d
    return d


def _turn_mesh(m, rot):
    """Turn a mesh model (no exact geometry behind it) by a rotation about the origin."""
    r = np.asarray(rot, np.float64)
    m.positions = (np.asarray(m.positions, np.float64) @ r.T).astype(m.positions.dtype)
    m.normals = (np.asarray(m.normals, np.float64) @ r.T).astype(m.normals.dtype)
    if len(m.segments):
        m.segments = (np.asarray(m.segments, np.float64) @ r.T).astype(m.segments.dtype)
    m.vertices = np.asarray(m.vertices, np.float64) @ r.T
    for params in (m.face_params, m.edge_params):
        for p in params:
            for k, v in list((p or {}).items()):
                if k in ("center", "origin", "start", "end", "apex", "axis", "normal", "dir") and v is not None and np.size(v) == 3:
                    p[k] = r @ np.asarray(v, np.float64)


def _set_material(m):
    """The model's material for the tree and Mass Properties: the one its bodies share, or "Mixed"
    (each body then weighs with its own density). None when the file names no materials."""
    named = {(b.get("material"), b.get("density")) for b in m.bodies if b.get("material")}
    if not named:
        return
    if len(named) == 1 and all(b.get("material") for b in m.bodies):
        name, density = next(iter(named))
        m.material = {"name": name, "density": density}
        m.info["Material"] = f"{name} ({density:g} g/cm³)" if density else name
    else:
        m.material = {"name": "As modeled (part materials)", "density": None, "perBody": True}
        m.info["Material"] = ", ".join(sorted({n for n, _ in named})[:6])


def _missing_text(missing):
    """One plain sentence about the components an assembly couldn't show."""
    if not missing:
        return ""
    names = sorted({f"{file} ({why})" for _inst, file, why in missing})
    shown = "; ".join(names[:6]) + (f"; and {len(names) - 6} more" if len(names) > 6 else "")
    n = len(missing)
    return f"{n} component{'s' if n != 1 else ''} couldn't be shown: {shown}."


def _cache_paths(path, config=None):
    """(STEP, info) cache files for a translated SolidWorks / Parasolid file (one per configuration),
    keyed by the file's path, size and time and by the translator's code, or None when there's nowhere
    to put them."""
    try:
        from .. import settings
        from ..formats import parasolid

        st = Path(path).stat()
        code = Path(parasolid.__file__).parent
        stamp = max(f.stat().st_mtime_ns for f in code.glob("*.py"))
        key = f"{Path(path).resolve()}|{st.st_size}|{st.st_mtime_ns}|{stamp}".lower()
        if config is not None:
            key += f"|config {config}"
        folder = Path(os.environ.get("LOCALAPPDATA") or settings.folder()) / "SolidSmufs" / "cache"
        folder.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha1(key.encode()).hexdigest()[:24]
        _prune(folder)
        return folder / f"{h}.step", folder / f"{h}.json"
    except Exception:
        return None


def _code_stamp():
    here = Path(__file__).resolve().parents[1]
    files = [*(here / "kernel").glob("*.py"), *(here / "formats").glob("*.py"),
             *(here / "formats" / "parasolid").glob("*.py"), *(here / "formats" / "prc").glob("*.py"),
             *(here / "formats" / "u3d").glob("*.py")]
    return max((f.stat().st_mtime_ns for f in files), default=0)


def _dependency_stamp(path):
    """An assembly's look depends on its part files too: their sizes and times, for the cache key."""
    if Path(path).suffix.lower() not in ASSEMBLY_FORMATS:
        return ""
    from ..formats import sldasm
    stamps = []
    for f in sldasm.dependencies(path):
        try:
            st = f.stat()
            stamps.append(f"{f.resolve()}:{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            stamps.append(f"{f}:missing")
    return "|" + "|".join(stamps)


def _mesh_cache_file(path, quality, config=None, orient=None):
    try:
        import gmsh
        from .. import settings

        st = Path(path).stat()
        key = (f"mesh|{Path(path).resolve()}|{st.st_size}|{st.st_mtime_ns}|{quality}|{_code_stamp()}|"
               f"{gmsh.__version__}{_dependency_stamp(path)}|config {config}"
               + ("" if orient is None else "|turn " + ",".join(f"{x:.9f}" for x in np.ravel(orient)))).lower()
        folder = Path(os.environ.get("LOCALAPPDATA") or settings.folder()) / "SolidSmufs" / "cache"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / (hashlib.sha1(key.encode()).hexdigest()[:24] + ".mesh.pkl")
    except Exception:
        return None


def _mesh_cache_read(path, quality, config=None, orient=None):
    """(model, meta, blob) from an earlier opening of this exact file at this quality, or None."""
    f = _mesh_cache_file(path, quality, config, orient)
    if f is None or not f.is_file():
        return None
    try:
        with open(f, "rb") as fh:
            d = pickle.load(fh)
        os.utime(f)  # recently used: keep it longest
        return d["model"], d["meta"], d["blob"]
    except Exception:
        f.unlink(missing_ok=True)
        return None


def _mesh_cache_write(path, quality, model, meta, blob, config=None, orient=None):
    f = _mesh_cache_file(path, quality, config, orient)
    if f is None:
        return
    clone = copy.copy(model)
    for k in ("exact_area", "exact_centroid"):
        clone.__dict__.pop(k, None)
    try:
        tmp = f.with_suffix(".tmp")
        with open(tmp, "wb") as fh:
            pickle.dump({"model": clone, "meta": meta, "blob": blob}, fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, f)
        _prune(f.parent, keep_mb=1500)
    except Exception:
        pass


def _area_integrals(pts, tri):
    """Area, centroid and inertia about the centroid (per unit area density) of triangles."""
    if not len(tri):
        return 0.0, np.zeros(3), np.zeros((3, 3))
    a, b, c = pts[tri[:, 0]], pts[tri[:, 1]], pts[tri[:, 2]]
    ar = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
    area = float(ar.sum())
    if area <= 0:
        return 0.0, np.zeros(3), np.zeros((3, 3))
    s = a + b + c
    centroid = (s / 3 * ar[:, None]).sum(axis=0) / area
    cov = np.zeros((3, 3))
    for i in range(3):
        for j in range(3):
            cov[i, j] = float((ar / 12 * (a[:, i] * a[:, j] + b[:, i] * b[:, j] + c[:, i] * c[:, j] + s[:, i] * s[:, j])).sum())
    cov -= area * np.outer(centroid, centroid)
    return area, centroid, np.trace(cov) * np.eye(3) - cov


def _prune(folder, keep_mb=600):
    """Keep the cache under keep_mb, oldest files out first."""
    files = sorted(folder.glob("*"), key=lambda f: f.stat().st_mtime)
    total = sum(f.stat().st_size for f in files)
    while files and total > keep_mb * 1e6:
        f = files.pop(0)
        total -= f.stat().st_size
        f.unlink(missing_ok=True)


def _mesh_distance(m, a, b):
    """Closest points between two entities using their triangles / polylines / points."""
    def cloud(e):
        if e.point() is not None:
            return e.point()[None, :], None
        if e.kind == "edge":
            return m.edge_points(e.index), None
        p, t = m.face_triangles(e.index)
        return p, t

    pa, ta = cloud(a)
    pb, tb = cloud(b)
    if pa is None or pb is None or not len(pa) or not len(pb):
        return None
    best = (np.inf, None, None)
    # point sets against each other (chunked)
    for i in range(0, len(pa), 2048):
        chunk = pa[i:i + 2048]
        d = np.linalg.norm(chunk[:, None, :] - pb[None, :, :], axis=2) if len(pb) * len(chunk) < 4e7 else None
        if d is None:
            break
        j = np.unravel_index(int(d.argmin()), d.shape)
        if d[j] < best[0]:
            best = (float(d[j]), chunk[j[0]], pb[j[1]])
    # a single point against a face: exact to the triangles
    for p_set, t, other in ((pa, ta, pb), (pb, tb, pa)):
        if t is not None and len(other) == 1:
            q = _closest_on_triangles(other[0], p_set, t)
            d = float(np.linalg.norm(q - other[0]))
            if d < best[0]:
                best = (d, other[0], q) if other is pa else (d, q, other[0])
    if best[1] is None:
        return None
    return best


def _closest_on_triangles(p, pts, tri):
    """Closest point to p on a set of triangles: the foot on each triangle's plane when it lands
    inside the triangle, else the nearest point on its three sides."""
    a, b, c = pts[tri[:, 0]], pts[tri[:, 1]], pts[tri[:, 2]]
    n = np.cross(b - a, c - a)
    nn = np.einsum("ij,ij->i", n, n)
    nn[nn == 0] = 1e-300
    q = p - n * (np.einsum("ij,ij->i", p - a, n) / nn)[:, None]
    inside = np.ones(len(a), bool)
    for s, e in ((a, b), (b, c), (c, a)):
        inside &= np.einsum("ij,ij->i", np.cross(e - s, q - s), n) >= 0
    best = np.where(inside, np.linalg.norm(q - p, axis=1), np.inf)
    out = q.copy()
    for s, e in ((a, b), (b, c), (c, a)):
        se = e - s
        t = np.clip(np.einsum("ij,ij->i", p - s, se) / np.maximum(np.einsum("ij,ij->i", se, se), 1e-300), 0, 1)
        cand = s + se * t[:, None]
        d = np.linalg.norm(cand - p, axis=1)
        closer = d < best
        best[closer] = d[closer]
        out[closer] = cand[closer]
    return out[int(best.argmin())]


def _load_dwg(path, name, progress):
    """A DWG drawing, turned into DXF by the ODA File Converter (in a folder of its own, as it converts folders)
    and read as one."""
    import subprocess
    from . import drawing
    from .pictures import dwg_converter
    exe = dwg_converter()
    progress("Converting the DWG", 0.1)
    with tempfile.TemporaryDirectory(prefix="solidsmufs-dwg-") as tmp:
        src, out = Path(tmp) / "in", Path(tmp) / "out"
        src.mkdir()
        out.mkdir()
        shutil.copyfile(path, src / "drawing.dwg")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.run([str(exe), str(src), str(out), "ACAD2018", "DXF", "0", "1", "*.DWG"],
                           creationflags=flags, timeout=300, capture_output=True)
        except subprocess.TimeoutExpired:
            raise ValueError("The ODA File Converter took too long with this DWG.") from None
        dxf = out / "drawing.dxf"
        if not dxf.is_file():
            raise ValueError("The ODA File Converter couldn't convert this DWG (it may be damaged).")
        m = drawing.load(dxf, name, progress, fmt="DWG")
    m.path = path
    m.info.pop("DXF version", None)  # that's what it was converted to; the DWG's own version is in its first bytes
    version = Path(path).read_bytes()[:6].decode("ascii", "replace")
    info = {"DWG version": f"AutoCAD {drawing.VERSIONS.get(version, version)}"}
    m.info = {**info, **m.info}
    return m


EXACT_CMDS = ("measure", "massprops", "bbox", "section_props", "holes")
SOLID_CMDS = ("massprops", "bbox", "section_props", "holes", "align", "facing", "save_step")  # need faces: not for a 2D drawing


def main(conn):
    """Process entry point: serve requests until told to quit or the pipe closes."""
    try:  # every open needs these; a worker started ahead of time has them loaded before it's asked
        import gmsh  # noqa: F401
        from . import cad  # noqa: F401
    except ImportError:
        pass
    s = Session()
    while True:
        try:
            rid, cmd, kw = conn.recv()
        except (EOFError, OSError):
            break
        if cmd == "quit":
            break

        def progress(stage, frac, rid=rid):
            conn.send((rid, "progress", {"stage": stage, "fraction": frac}))

        try:
            fn = getattr(s, cmd)
            if cmd in ("open", "load", "reload", "ensure_exact"):
                result = fn(progress=progress, **kw)
            else:
                if s.model is None:
                    raise ValueError("Nothing is loaded.")
                if s.model.kind == "pdf" and not cmd.startswith("pdf_"):
                    raise ValueError("This has no 3D model to work on.")
                if s.model.kind == "drawing" and cmd in SOLID_CMDS:
                    raise ValueError("That works on 3D parts. A drawing or a toolpath is just lines, with no solid to work on.")
                if cmd in EXACT_CMDS and not s.exact:
                    s.ensure_exact(progress=progress)
                result = fn(**kw)
            conn.send((rid, "ok", result))
        except Exception as e:
            friendly = isinstance(e, (ValueError, FileNotFoundError, PermissionError))
            conn.send((rid, "error", {"message": str(e) if friendly else f"{type(e).__name__}: {e}",
                                      "trace": traceback.format_exc()}))
        if s.post is not None:
            post, s.post = s.post, None
            try:
                post()
            except Exception:
                pass
