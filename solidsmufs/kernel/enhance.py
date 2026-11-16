"""Cleaning up a scanned print (PDF > Pages > Enhance scan): the paper made white, the ink solid, specks taken off,
lines broken by a pixel joined, the page straightened, and Windows OCR's reading laid under it as hidden text, to
search, select and balloon.

What's on the page is only ever cleaned, never retyped: a figure OCR misreads (.005 for .006, a Ø for a 0) would be a
wrong requirement that looks right. A smudge right over a figure stays, for whoever reads it to judge.

All of it is numpy on the page rendered in gray: no image library to install."""

import math

import numpy as np

DPI = 300  # enough for a figure's point to keep its shape
MOST = 36_000_000  # pixels a page is cleaned at, at most: a big sheet gets fewer dots per inch
SPECKS = {0: 0, 1: 3, 2: 5}  # despeckle: off, light, strong: the widest speck taken (pixels at 300 dpi)


def scanned(pg):
    """Is the page a scan: a picture over most of it, or pictures (one, or strips) with little else on the page, as when
    a scan is printed to PDF inside the paper's margins? A print exported from CAD is lines and text, already sharp: a
    page with much of either isn't one, whatever pictures it also has."""
    import pymupdf
    page = pymupdf.Rect(pg.rect) * pg.derotation_matrix
    page.normalize()
    area = max(page.get_area(), 1.0)
    covered = sum((pymupdf.Rect(info["bbox"]) & page).get_area() for info in pg.get_image_info())
    if covered >= 0.5 * area:
        return True
    if covered < 0.05 * area:
        return False
    lines = sum(len(d["items"]) for d in pg.get_drawings())
    shown = [t for t in pg.get_texttrace() if t["type"] != 3 and any(chr(c[0]).strip() for c in t["chars"])]  # (not hidden OCR)
    return lines < 40 and sum(len(t["chars"]) for t in shown) < 40


def dpi_for(width, height, dpi=DPI):
    """The dots per inch a page of this size (points) is cleaned at: DPI, or fewer for a sheet too big for it."""
    px = (width / 72 * dpi) * (height / 72 * dpi)
    return dpi if px <= MOST else max(100, int(dpi * math.sqrt(MOST / px)))


def gray(pix):
    """A gray pymupdf Pixmap as a numpy array (rows, columns)."""
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.stride)[:, :pix.w].copy()


# ------------------------------------------------------------------------------------------------ the paper and ink
def _grow(a, n=1):
    """The largest of each value's neighbors, n deep (a small array: the paper's brightness block by block)."""
    for _ in range(n):
        p = np.pad(a, 1, mode="edge")
        a = np.maximum.reduce([p[i:i + a.shape[0], j:j + a.shape[1]] for i in range(3) for j in range(3)])
    return a


def paper(g, dpi):
    """The paper's own brightness under each pixel: what it would be with nothing printed on it, from the bright end of
    each block of the page. Shadows, yellowing and a gray copier background are in it; the ink isn't."""
    b = max(8, int(dpi / 6))  # (a sixth of an inch: wider than a stroke, narrower than a shadow's edge)
    h, w = g.shape
    H, W = -(-h // b), -(-w // b)
    pad = np.pad(g, ((0, H * b - h), (0, W * b - w)), mode="edge")
    blocks = pad.reshape(H, b, W, b).swapaxes(1, 2).reshape(H, W, b * b)
    k = int(0.9 * (b * b - 1))
    bright = np.partition(blocks, k, axis=2)[:, :, k].astype(np.float32)
    bright = _grow(bright)  # (a block all ink, like a filled area, takes its neighbors' paper)
    return np.repeat(np.repeat(bright, b, axis=0), b, axis=1)[:h, :w]


def ink(g, dpi):
    """Which pixels are ink: each against the paper under it, so a shadowed corner reads like the middle, and a light
    smudge or a gray background goes to paper."""
    level = np.clip(g.astype(np.float32) / np.maximum(paper(g, dpi), 1.0), 0.0, 1.0)
    # a stroke's edge is halfway between its own darkness and the paper's: cut any lighter and a blurred scan's
    # strokes go fat and the holes in its 8s, 6s and 0s fill in
    dark = level[level < 0.85]
    if dark.size < 0.0005 * level.size:
        return level < 0.6
    core = float(np.percentile(dark, 20))
    t = min(max((core + 1.0) / 2.0, 0.5), 0.75)
    return level < t


# ------------------------------------------------------------------------------------------------ straightening
def skew(mask, dpi):
    """How far the page's lines run off level, in degrees (positive: down to the right, as the page is shown), from the
    angle that lines the ink up into the sharpest rows. 0 when it's level within a tenth of a degree."""
    f = max(1, int(round(mask.shape[1] / 1600)))
    ys, xs = np.nonzero(mask[::f, ::f])
    if len(ys) < 500:
        return 0.0
    if len(ys) > 300_000:
        pick = np.random.default_rng(0).choice(len(ys), 300_000, replace=False)
        ys, xs = ys[pick], xs[pick]
    ys, xs = ys.astype(np.float64), xs.astype(np.float64)

    def score(a):
        yy = ys - xs * math.tan(math.radians(a))
        hist = np.bincount((yy - yy.min()).astype(np.int64))
        return float((hist.astype(np.float64) ** 2).sum())

    best = max(np.arange(-4.0, 4.01, 0.1), key=score)
    best = max(np.arange(best - 0.1, best + 0.101, 0.01), key=score)
    return round(float(best), 2) if abs(best) >= 0.1 else 0.0


def turn(mask, angle):
    """The ink turned to take `angle` (see skew) back out, about the page's middle; what turns in from off the page is
    paper."""
    if not angle:
        return mask
    h, w = mask.shape
    a = math.radians(angle)
    cos, sin = math.cos(a), math.sin(a)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    out = np.zeros_like(mask)
    xo = np.arange(w, dtype=np.float32) - cx
    step = 512
    for y0 in range(0, h, step):
        yo = np.arange(y0, min(y0 + step, h), dtype=np.float32)[:, None] - cy
        sx = np.rint(cx + xo[None, :] * cos - yo * sin).astype(np.int64)
        sy = np.rint(cy + xo[None, :] * sin + yo * cos).astype(np.int64)
        ok = (sx >= 0) & (sx < w) & (sy >= 0) & (sy < h)
        rows = np.zeros(sx.shape, dtype=bool)
        rows[ok] = mask[sy[ok], sx[ok]]
        out[y0:y0 + rows.shape[0]] = rows
    return out


# ------------------------------------------------------------------------------------------------ mending
def bridge(mask):
    """A pixel between two of ink, above and below or left and right, made ink: a faint line broken by the scan
    joined, a hollow in a stroke filled. Nothing grows fatter."""
    p = np.pad(mask, 1)
    return mask | (p[:-2, 1:-1] & p[2:, 1:-1]) | (p[1:-1, :-2] & p[1:-1, 2:])


def _box_sums(a, n):
    """The sum over every n x n window of a (by its top-left corner)."""
    s = np.zeros((a.shape[0] + 1, a.shape[1] + 1), dtype=np.int32)
    s[1:, 1:] = a.astype(np.int32).cumsum(0, dtype=np.int32).cumsum(1, dtype=np.int32)
    return s[n:, n:] - s[:-n, n:] - s[n:, :-n] + s[:-n, :-n]


def despeckle(mask, size, clear=None):
    """Specks taken off: ink no wider or taller than `size` pixels with paper round it, unless there's a line or a
    letter within `clear` pixels (by default three times its size and 6 more: a sixtieth of an inch at 300 dpi for the
    light setting). A decimal point is as small as a speck in small print, but there's always a figure that close to
    it, even in a typewriter font: it stays. Specks near only other specks go together."""
    if size < 1:
        return mask
    m = 3 * size + 6 if clear is None else int(clear)
    h, w = mask.shape
    if h < size + 2 or w < size + 2:
        return mask
    inner = _box_sums(mask, size)[1:-1, 1:-1]  # windows from (1, 1)
    outer = _box_sums(mask, size + 2)  # the same windows with a pixel's ring round them, from (0, 0)
    small = (inner > 0) & (inner == outer)
    marks = np.zeros((h, w), dtype=bool)
    marks[1:1 + small.shape[0], 1:1 + small.shape[1]] = small
    tiny = mask & (_box_sums(np.pad(marks, ((size - 1, 0), (size - 1, 0))), size) > 0)  # the small marks' ink
    solid = mask & ~tiny  # lines and letters
    near = _box_sums(np.pad(solid, m), 2 * m + 1) > 0  # within m of them
    return mask & ~(tiny & ~near)


# ------------------------------------------------------------------------------------------------ all of it
def clean(g, dpi, specks=1, straighten=True):
    """A gray page (numpy, 0 ink to 255 paper) cleaned: (the page as black on white, the angle it was turned by)."""
    m = ink(g, dpi)
    angle = skew(m, dpi) if straighten else 0.0
    m = turn(m, angle)
    m = bridge(m)
    m = despeckle(m, max(1, round(SPECKS.get(int(specks), 0) * dpi / 300)) if specks else 0)
    return np.where(m, 0, 255).astype(np.uint8), angle


def png(a, dpi=None):
    """A gray numpy picture as PNG bytes."""
    import pymupdf
    a = np.ascontiguousarray(a, dtype=np.uint8)
    pix = pymupdf.Pixmap(pymupdf.csGRAY, a.shape[1], a.shape[0], a.tobytes(), False)
    if dpi:
        pix.set_dpi(int(dpi), int(dpi))
    return pix.tobytes("png")


def qimage(a):
    """A gray numpy picture as a QImage (for Windows OCR)."""
    from PySide6.QtGui import QImage
    a = np.ascontiguousarray(a, dtype=np.uint8)
    return QImage(a.data, a.shape[1], a.shape[0], a.shape[1], QImage.Format.Format_Grayscale8).copy()
