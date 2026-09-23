# -*- coding: utf-8 -*-
"""QGIS-free legend inversion for the geochemistry polygonize tool.

The tool recovers quantitative element values from a colour-ramped raster by
projecting each pixel onto the nearest legend segment in RGB space. That
inversion is pure NumPy, so it lives here and can be tested against a known
legend without a QGIS runtime.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from .swallow_log import log_swallowed


@dataclass(frozen=True)
class LegendPoint:
    value: float
    rgb: Tuple[int, int, int]


def points_to_breaks(points: Sequence[LegendPoint]) -> List[float]:
    vals = [float(p.value) for p in points]
    vals = sorted(set(vals))
    return vals


RGB_MATCH_TOLERANCE = 48.0
"""Euclidean RGB distance beyond which a pixel is not a legend colour.

Without a tolerance every pixel is forced onto the nearest segment, and the
dark corner of RGB space is nearest the maroon end of most presets - so black
linework, its anti-alias halo and label text came back as top-percentile
anomalies. 48 is generous (about 19% of one channel): it rejects neutral
darks and off-legend colours while keeping JPEG-noisy ramp colours.
"""


def interp_rgb_to_value(
    *,
    r: np.ndarray,
    g: np.ndarray,
    b: np.ndarray,
    points: Sequence[LegendPoint],
    snap_last_t: Optional[float] = None,
    max_distance: Optional[float] = None,
    return_residual: bool = False,
):
    """Vectorized mapping: RGB -> scalar value by projecting to the nearest legend polyline segment in RGB space.

    ``max_distance``: pixels whose nearest-segment RGB distance exceeds it are
    returned as NaN instead of being forced onto the ramp. ``return_residual``
    also returns that per-pixel distance so the caller can report or write it.
    Both default off, so existing callers see the old behaviour.
    """
    if r.shape != g.shape or r.shape != b.shape:
        raise ValueError("RGB bands must have the same shape")
    if len(points) < 2:
        raise ValueError("Need at least 2 legend points")

    rr = r.astype(np.float32, copy=False)
    gg = g.astype(np.float32, copy=False)
    bb = b.astype(np.float32, copy=False)

    out = np.full(rr.shape, np.nan, dtype=np.float32)
    # Distance of each pixel to the winning segment, always measured to the
    # UNSNAPPED projection. snap_last_t only changes the VALUE read off the
    # last segment; it must neither decide which segment wins nor count as
    # colour mismatch. Competing on the snapped distance made a pixel at
    # t in (snap_t, 0.5) lose to the previous segment's end (value 12 instead
    # of 51 for Fe2O3), or exceed the tolerance and become NoData.
    min_dist = np.full(rr.shape, np.float32(np.inf), dtype=np.float32)

    pts = list(points)
    last_seg_idx = len(pts) - 2
    snap_last = None
    if snap_last_t is not None:
        try:
            snap_last = float(snap_last_t)
        except Exception:
            snap_last = None
    if snap_last is not None and not (0.0 <= snap_last <= 1.0):
        snap_last = None

    for i in range(len(pts) - 1):
        v1 = float(pts[i].value)
        v2 = float(pts[i + 1].value)
        c1 = pts[i].rgb
        c2 = pts[i + 1].rgb

        c1r = np.float32(c1[0])
        c1g = np.float32(c1[1])
        c1b = np.float32(c1[2])
        vr = np.float32(c2[0] - c1[0])
        vg = np.float32(c2[1] - c1[1])
        vb = np.float32(c2[2] - c1[2])
        v_len_sq = np.float32(vr * vr + vg * vg + vb * vb)
        if v_len_sq <= 0:
            continue

        t = ((rr - c1r) * vr + (gg - c1g) * vg + (bb - c1b) * vb) / v_len_sq
        np.clip(t, np.float32(0.0), np.float32(1.0), out=t)
        pr = c1r + t * vr
        pg = c1g + t * vg
        pb = c1b + t * vb
        dist_sq = (rr - pr) ** 2 + (gg - pg) ** 2 + (bb - pb) ** 2

        mask = dist_sq < min_dist
        if not np.any(mask):
            continue

        t_val = t
        if snap_last is not None and i == last_seg_idx:
            # Value rule only: t above the snap threshold reads as the top value.
            try:
                t_val = np.where(t > np.float32(snap_last), np.float32(1.0), t)
            except Exception as _exc:
                log_swallowed("tools/geochem_legend.py (interp_rgb_to_value snap)", _exc)
                t_val = t

        base = np.float32(v1)
        delta = np.float32(v2 - v1)
        out[mask] = base + t_val[mask].astype(np.float32, copy=False) * delta
        min_dist[mask] = dist_sq[mask].astype(np.float32, copy=False)

    residual = np.sqrt(min_dist)
    if max_distance is not None:
        try:
            tol = float(max_distance)
            if tol >= 0.0:
                out[residual > np.float32(tol)] = np.nan
        except Exception as _exc:
            log_swallowed("tools/geochem_legend.py (interp_rgb_to_value tolerance)", _exc)
    if return_residual:
        return out, residual
    return out


def mask_black_lines(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Detect neutral dark 'linework' (not intense red/brown) and return mask.

    Two tests, OR-ed: the original strict one, plus a low-saturation dark test
    that also catches the anti-alias halo around a black line (e.g. 85,80,78),
    which the strict per-channel <75 bound missed. The saturation term keeps
    dark but coloured ramp pixels (10,60,10; the maroon legend maximum) out.
    """
    rr = r.astype(np.int16, copy=False)
    gg = g.astype(np.int16, copy=False)
    bb = b.astype(np.int16, copy=False)
    strict = (rr < 75) & (gg < 75) & (bb < 75) & (np.abs(rr - gg) < 15) & (np.abs(gg - bb) < 15)
    mx = np.maximum(np.maximum(rr, gg), bb)
    mn = np.minimum(np.minimum(rr, gg), bb)
    halo = (mx < 90) & ((mx - mn) < 30)
    return strict | halo


def _neighbour_shift(a: np.ndarray, dy: int, dx: int, fill) -> np.ndarray:
    """``out[y, x] = a[y + dy, x + dx]``; cells whose neighbour is off the grid get ``fill``."""
    out = np.full(a.shape, fill, dtype=a.dtype)
    h, w = a.shape
    ys0, ys1 = max(0, -dy), h - max(0, dy)
    xs0, xs1 = max(0, -dx), w - max(0, dx)
    if ys1 > ys0 and xs1 > xs0:
        out[ys0:ys1, xs0:xs1] = a[ys0 + dy:ys1 + dy, xs0 + dx:xs1 + dx]
    return out


# 4-neighbours first, then diagonals: the order in which a filled pixel looks
# for a source, so the nearest (not the diagonal) neighbour wins a tie.
_NEIGHBOURS = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))


def _dilate8(mask: np.ndarray) -> np.ndarray:
    grown = mask.copy()
    for dy, dx in _NEIGHBOURS:
        grown |= _neighbour_shift(mask, dy, dx, False)
    return grown


def grow_mask(mask: np.ndarray, steps: int) -> np.ndarray:
    """``mask`` grown by ``steps`` 8-neighbour pixels."""
    grown = np.asarray(mask, dtype=bool).copy()
    for _step in range(max(0, int(steps))):
        grown = _dilate8(grown)
    return grown


def mask_colour_halo(
    r: np.ndarray,
    g: np.ndarray,
    b: np.ndarray,
    *,
    core: np.ndarray,
    rings: int = 2,
    max_rgb_distance: float = 16.0,
    min_alpha: float = 0.08,
    max_alpha: float = 0.92,
) -> np.ndarray:
    """Anti-aliased edge pixels of dark linework drawn over a colour.

    A black line over a red (12 %) area leaves an edge of (115, 0, 0): black
    blended 50 % with red. That colour lies on the legend ramp (it is close
    to the maroon maximum), so neither the RGB tolerance nor the neutral
    ``mask_black_lines`` test rejects it and it read as ~50 %. A pixel is
    such an edge when it lies within ``rings`` pixels (8-neighbour steps) of
    the neutral dark ``core`` and its colour is ``alpha * N`` for the colour
    ``N`` of one of its own neighbours outside the line (``min_alpha <=
    alpha <= max_alpha``, RGB distance to that blend line at most
    ``max_rgb_distance``). Testing against the NEIGHBOUR's colour, not any
    legend colour, keeps legitimately dark legend areas (navy is 0.45 x the
    blue stop) from being flagged next to a line. Returns the edge mask only
    (``core`` excluded). Without a neutral dark core nearby nothing is
    flagged: a darkened colour on its own is indistinguishable from data.
    """
    core = np.asarray(core, dtype=bool)
    region = core.copy()
    if not np.any(core) or rings <= 0:
        return np.zeros(core.shape, dtype=bool)
    h, w = core.shape
    chans = (np.asarray(r), np.asarray(g), np.asarray(b))
    tol_sq = float(max_rgb_distance) ** 2
    for _ring in range(int(rings)):
        cand = _dilate8(region) & ~region
        ys, xs = np.nonzero(cand)
        if ys.size == 0:
            break
        # Gather only the candidate pixels and their neighbours: a full-size
        # float RGB stack of a 12 Mpx export would cost ~300 MB.
        px = np.stack([c[ys, xs] for c in chans], axis=-1).astype(np.float64)
        pp = np.einsum("ij,ij->i", px, px)
        is_blend = np.zeros(ys.size, dtype=bool)
        for dy, dx in _NEIGHBOURS:
            ny = ys + dy
            nx = xs + dx
            inside = (ny >= 0) & (ny < h) & (nx >= 0) & (nx < w)
            nyc = np.clip(ny, 0, h - 1)
            nxc = np.clip(nx, 0, w - 1)
            n_ok = inside & ~region[nyc, nxc]
            nb = np.stack([c[nyc, nxc] for c in chans], axis=-1).astype(np.float64)
            nn = np.einsum("ij,ij->i", nb, nb)
            pn = np.einsum("ij,ij->i", px, nb)
            a = np.where(nn > 1.0, pn / np.maximum(nn, 1.0), -1.0)
            d_sq = pp - 2.0 * a * pn + a * a * nn
            is_blend |= n_ok & (nn > 1.0) & (a >= min_alpha) & (a <= max_alpha) & (d_sq <= tol_sq)
        if not np.any(is_blend):
            break
        region[ys[is_blend], xs[is_blend]] = True
    return region & ~core


def fill_nearest(
    values: np.ndarray,
    *,
    fill_mask: np.ndarray,
    valid: np.ndarray,
    max_dist_px: int,
    nodata: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Give each ``fill_mask`` pixel the value of its nearest pixel outside the mask.

    The fill grows one pixel (8-neighbour) per step for at most
    ``max_dist_px`` steps and COPIES a neighbour's value, so it never makes a
    value (or class) that is not already on the map. The GDAL inverse-
    distance fill it replaces averaged the two sides of a line: a black line
    between a 4.5 % and a 7.1 % area became a 5.8 % strip, a sliver of a
    class that exists on neither side.

    Every pixel outside ``fill_mask`` is a source. ``valid`` ones pass on
    their value; when ``nodata`` is given, the others pass on NoData, so a
    line drawn across white background or a transparent area stays NoData
    instead of borrowing a value from data further away. Pixels outside
    ``fill_mask`` are never changed. Returns ``(filled_values, filled_mask)``
    where ``filled_mask`` marks the pixels that received a VALID value.
    """
    fill_mask = np.asarray(fill_mask, dtype=bool)
    valid = np.asarray(valid, dtype=bool)
    out = np.array(values, copy=True)
    if nodata is not None:
        have = ~fill_mask
        src_valid = valid & ~fill_mask
        out[~fill_mask & ~valid] = nodata
    else:
        have = valid & ~fill_mask
        src_valid = have.copy()
    todo = fill_mask.copy()
    for _step in range(max(1, int(max_dist_px))):
        if not np.any(todo):
            break
        newly = np.zeros(out.shape, dtype=bool)
        new_vals = np.zeros(out.shape, dtype=out.dtype)
        new_valid = np.zeros(out.shape, dtype=bool)
        for dy, dx in _NEIGHBOURS:
            src_have = _neighbour_shift(have, dy, dx, False)
            take = todo & ~newly & src_have
            if np.any(take):
                new_vals[take] = _neighbour_shift(out, dy, dx, 0)[take]
                new_valid[take] = _neighbour_shift(src_valid, dy, dx, False)[take]
                newly |= take
        if not np.any(newly):
            break
        out[newly] = new_vals[newly]
        have |= newly
        src_valid |= newly & new_valid
        todo &= ~newly
    filled = fill_mask & src_valid
    return out, filled


def legend_first_stop_is_absent_grey(points: Sequence[LegendPoint]) -> bool:
    """True when the legend's lowest stop is a neutral grey 'absent data' colour.

    The shipped presets start with (204, 204, 204) at value 0 (자료 없음), so
    the interval up to the second stop is background, not data. A custom
    legend usually starts at its first real class; treating that interval as
    NoData threw the whole lowest class away. Neutral means channel spread
    <= 16 and light means mean >= 96 (a dark neutral is linework, not a
    legend entry).
    """
    pts = sorted(points, key=lambda p: float(p.value))
    if len(pts) < 2:
        return False
    rgb = [int(c) for c in pts[0].rgb]
    return (max(rgb) - min(rgb)) <= 16 and (sum(rgb) / 3.0) >= 96.0


def break_tolerance(value: float) -> float:
    """Tolerance for "a pixel exactly at a legend stop" in float32 values.

    Values are float32; a stop such as 3.1 is stored as 3.0999999, which is
    below the float64 break 3.1, so exact stop colours used to fall into the
    class BELOW the stop for 3.1/5.7/7.1/9.4 but above it for 3.5/4.5/8.5/12.
    Four float32 ULPs of the stop is far below the colour quantisation (the
    finest Fe2O3 step is ~0.003 %) and puts every stop in the class it starts.
    """
    try:
        return 4.0 * float(np.spacing(np.float32(abs(float(value)))))
    except Exception as _exc:
        log_swallowed("tools/geochem_legend.py (break_tolerance)", _exc)
        return 0.0


# ---------------------------------------------------------------------------
# Legend CSV import (value,r,g,b), QGIS-free so it can be unit tested.
# ---------------------------------------------------------------------------

class LegendCsvError(ValueError):
    """A legend CSV was read but must be rejected rather than repaired.

    ``code`` is one of ``"range"`` (a channel outside 0-255 after any 0-1
    scaling), ``"too_few"`` (fewer than two usable points) or
    ``"same_colour"`` (fewer than two distinct colours). ``rows`` lists the
    offending 1-based line numbers where that applies. ``str(err)`` is the
    Korean message the dialog shows.
    """

    def __init__(self, code: str, message: str, rows: Optional[Sequence[int]] = None):
        super().__init__(message)
        self.code = str(code)
        self.rows = [int(r) for r in (rows or [])]


@dataclass
class LegendCsvResult:
    points: List[LegendPoint]
    skipped_rows: List[int] = field(default_factory=list)
    scaled_from_unit: bool = False
    notes: List[str] = field(default_factory=list)


def _fmt_rows(rows: Sequence[int]) -> str:
    rows = sorted(set(int(r) for r in rows))
    if len(rows) > 12:
        return ", ".join(str(r) for r in rows[:12]) + f" 외 {len(rows) - 12}행"
    return ", ".join(str(r) for r in rows)


def parse_legend_csv_rows(rows: Iterable[Sequence[str]]) -> LegendCsvResult:
    """Parse ``value,r,g,b`` rows (header optional) into legend points.

    Rules, in order:
    - blank rows, ``#`` comments and a ``value``/``val`` header are ignored;
      a single cell holding ``v,r,g,b`` (spreadsheet paste) is split;
    - rows with fewer than four cells or a non-numeric cell are skipped and
      reported in ``skipped_rows`` (1-based line numbers);
    - if every channel is <= 1.0 and at least one is fractional, the file is
      taken to use the 0-1 convention (matplotlib, R, QGIS ramp exports) and
      all channels are scaled by 255. ``int(float(x))`` used to truncate such
      a file to an all-black legend, which then sent every map pixel to the
      legend maximum;
    - a channel outside 0-255 after that scaling rejects the whole file
      (``LegendCsvError`` code ``range``) instead of being clamped;
    - values are de-duplicated (last wins) and sorted;
    - fewer than two points (``too_few``) or fewer than two distinct colours
      (``same_colour``) reject the file.
    """
    parsed: List[Tuple[int, float, float, float, float]] = []
    skipped: List[int] = []
    for lineno, row in enumerate(rows, start=1):
        if not row:
            continue
        cells = [str(x if x is not None else "").strip() for x in row]
        if len(cells) == 1:
            txt = cells[0]
            if not txt or txt.startswith("#"):
                continue
            # Allow "value,r,g,b" in a single cell (copied from spreadsheets)
            cells = [x.strip() for x in txt.split(",")]
        cells = [x for x in cells if x]
        if not cells:
            continue
        if cells[0].startswith("#"):
            continue
        if cells[0].lower() in ("value", "val"):
            continue
        if len(cells) < 4:
            skipped.append(lineno)
            continue
        try:
            nums = tuple(float(c) for c in cells[:4])
        except Exception as _exc:
            log_swallowed("tools/geochem_legend.py (parse_legend_csv_rows)", _exc)
            nums = None
        if nums is None:
            skipped.append(lineno)
            continue
        v, r, g, b = nums
        if not all(np.isfinite(x) for x in (v, r, g, b)):
            skipped.append(lineno)
            continue
        parsed.append((lineno, v, r, g, b))

    notes: List[str] = []
    scaled = False
    if parsed:
        chans = [c for _ln, _v, r, g, b in parsed for c in (r, g, b)]
        if all(0.0 <= c <= 1.0 for c in chans) and any(0.0 < c < 1.0 for c in chans):
            scaled = True
            parsed = [(ln, v, r * 255.0, g * 255.0, b * 255.0) for ln, v, r, g, b in parsed]
            notes.append("RGB 채널이 모두 0~1 범위라 255배로 환산했습니다.")

    bad_rows = [ln for ln, _v, r, g, b in parsed if not all(-0.5 <= c <= 255.5 for c in (r, g, b))]
    if bad_rows:
        raise LegendCsvError(
            "range",
            "RGB 채널이 0~255 범위를 벗어난 행이 있어 CSV를 거부합니다(열 순서는 value,r,g,b): "
            + _fmt_rows(bad_rows),
            rows=bad_rows,
        )

    dedup: Dict[float, LegendPoint] = {}
    for _ln, v, r, g, b in parsed:
        rgb = (
            max(0, min(255, int(round(r)))),
            max(0, min(255, int(round(g)))),
            max(0, min(255, int(round(b)))),
        )
        dedup[float(v)] = LegendPoint(float(v), rgb)
    points = sorted(dedup.values(), key=lambda p: float(p.value))

    if len(points) < 2:
        raise LegendCsvError(
            "too_few",
            "CSV에는 value,r,g,b 형태의 포인트가 2개 이상 필요합니다."
            + (f" (건너뛴 행: {_fmt_rows(skipped)})" if skipped else ""),
            rows=skipped,
        )
    if len({p.rgb for p in points}) < 2:
        raise LegendCsvError(
            "same_colour",
            "CSV의 색이 모두 같아 범례로 쓸 수 없습니다(서로 다른 색이 2개 이상 필요). 열 순서가 value,r,g,b인지 확인하세요.",
        )
    if skipped:
        notes.append(f"{len(skipped)}행을 건너뛰었습니다(행: {_fmt_rows(skipped)}).")
    return LegendCsvResult(points=points, skipped_rows=skipped, scaled_from_unit=scaled, notes=notes)


def legend_points_from_csv(csv_path: str) -> LegendCsvResult:
    """Load legend points from a CSV file with columns value,r,g,b (header optional)."""
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        return parse_legend_csv_rows(csv.reader(f))


# ---------------------------------------------------------------------------
# Legend image sampling geometry and sanity checks (QGIS-free).
# ---------------------------------------------------------------------------

def legend_sample_rows(n_points: int, height: int, low_at_bottom: bool = True, continuous: bool = False) -> List[int]:
    """Image rows at which to sample ``n_points`` legend anchors on a vertical bar.

    Discrete legend (one box per value, ``continuous=False``): each anchor is
    sampled at the centre of its box, row ``(i + 0.5) / n * h``. The old rule
    (rows 0 and h-1 for the extremes) read the margin or frame of the graphic.

    Continuous colour bar (``continuous=True``): the values sit at the two
    ends of the bar and evenly between them, so anchor ``i`` is at
    ``i / (n - 1)`` of the (cropped) bar, rows ``0 .. h-1``. Box centres on a
    continuous bar shifted every anchor inwards: the end colours were off by
    ~69 RGB and a map value of 30 % came back as 46.6 %. Frames or margins at
    the ends are caught by ``sampled_legend_problem`` and rejected.

    ``low_at_bottom`` orders the rows so that ``rows[0]`` is the lowest value
    (nearest the bottom of the image). Rows are clamped to ``0..height-1``.
    """
    n = max(1, int(n_points))
    h = max(1, int(height))
    rows: List[int] = []
    for i in range(n):
        if continuous and n > 1:
            frac = float(i) / float(n - 1)
            if low_at_bottom:
                frac = 1.0 - frac
            y = int(round(frac * float(h - 1)))
        else:
            frac = (float(i) + 0.5) / float(n)
            if low_at_bottom:
                frac = 1.0 - frac
            y = int(math.floor(frac * float(h)))
        rows.append(max(0, min(h - 1, y)))
    return rows


def legend_profile_looks_discrete(colours: Sequence[Sequence[float]], n_points: int, tol: float = 12.0) -> bool:
    """Guess whether a sampled legend column is boxes (True) or a continuous bar.

    ``colours`` is the RGB of every row along the sample column. Rows are
    grouped into runs that stay within ``tol`` RGB of the run's first row
    (tolerant of JPEG noise). A box legend is made of runs about ``h / n``
    rows long; a continuous bar changes colour every few rows. The guess is
    "boxes" when the row-weighted median run is at least half a box.
    """
    c = np.asarray(colours, dtype=np.float64).reshape(-1, 3)
    h = int(c.shape[0])
    if h < 2:
        return True
    runs: List[int] = []
    start = 0
    for y in range(1, h + 1):
        if y == h or float(np.linalg.norm(c[y] - c[start])) > float(tol):
            runs.append(y - start)
            start = y
    lens = np.repeat(np.asarray(runs, dtype=np.float64), runs)
    return float(np.median(lens)) >= 0.5 * float(h) / float(max(1, int(n_points)))


def sampled_legend_problem(points: Sequence[LegendPoint], alphas: Optional[Sequence[int]] = None) -> Optional[str]:
    """Return a problem code for colours sampled from a legend image, or None.

    Codes: ``endpoint_transparent`` (an extreme sample has alpha < 128),
    ``endpoint_white`` / ``endpoint_black`` (an extreme sample is pure white
    or pure black, i.e. background or frame), ``all_identical`` (every
    consecutive pair of samples is the same colour, so the sampled column is
    not on the colour bar).
    """
    pts = list(points)
    if len(pts) < 2:
        return "all_identical"
    ends = [0, len(pts) - 1]
    if alphas is not None:
        try:
            al = list(alphas)
            if len(al) == len(pts) and any(int(al[i]) < 128 for i in ends):
                return "endpoint_transparent"
        except Exception as _exc:
            log_swallowed("tools/geochem_legend.py (sampled_legend_problem)", _exc)
    for i in ends:
        rgb = tuple(int(c) for c in pts[i].rgb)
        if all(c >= 250 for c in rgb):
            return "endpoint_white"
        if all(c <= 5 for c in rgb):
            return "endpoint_black"
    if all(tuple(pts[i].rgb) == tuple(pts[i + 1].rgb) for i in range(len(pts) - 1)):
        return "all_identical"
    return None
