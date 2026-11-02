"""SolidWorks parts and Parasolid transmit files → STEP AP214 (millimetres), without any CAD software.

Reads ``.sldprt`` (2015+ chunked files and the older OLE compound files), ``.x_t`` / ``.xmt_txt``
(Parasolid text) and ``.x_b`` / ``.xmt_bin`` (Parasolid binary), and writes the solid bodies' B-rep with
exact geometry wherever possible (analytic and B-spline surfaces, lines, circles, ellipses and B-spline
edges); the rest is approximated and reported in the result's warnings.

Importing this package is cheap: the readers load on the first call to :func:`to_step`.
"""

SUPPORTED_EXTS = (".sldprt", ".x_t", ".xmt_txt", ".x_b", ".xmt_bin")


class UnsupportedFile(Exception):
    """No geometry could be produced; the message is short and meant for the user."""


def to_step(src_path: str, out_path: str, config: int | None = None) -> dict:
    """Write src's solid bodies as STEP to out_path (a SolidWorks part's configuration `config`, the id
    in its Config-<n> streams, when given and present; otherwise its first). Returns
    {"bodies": int, "faces": int, "format": str, "app": str | None, "warnings": [str],
     "edges_exact": int, "edges_approx": int, "edges_polyline": int}
    ("format" e.g. "SolidWorks part (2015+)", "SolidWorks part (pre-2015)", "Parasolid text (V17.1)";
    "app" is APPL= from the Parasolid header when there is one; the edge counts say how many edges were
    written exactly, as fitted B-splines and as polylines). Raises UnsupportedFile when no geometry can be
    produced."""
    from .convert import convert

    return convert(src_path, out_path, config)


__all__ = ["SUPPORTED_EXTS", "UnsupportedFile", "to_step"]
