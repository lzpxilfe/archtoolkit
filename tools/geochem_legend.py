# -*- coding: utf-8 -*-
"""QGIS-free legend inversion for the geochemistry polygonize tool.

The tool recovers quantitative element values from a colour-ramped raster by
projecting each pixel onto the nearest legend segment in RGB space. That
inversion is pure NumPy, so it lives here and can be tested against a known
legend without a QGIS runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np


@dataclass(frozen=True)
class LegendPoint:
    value: float
    rgb: Tuple[int, int, int]


def points_to_breaks(points: Sequence[LegendPoint]) -> List[float]:
    vals = [float(p.value) for p in points]
    vals = sorted(set(vals))
    return vals


def interp_rgb_to_value(
    *,
    r: np.ndarray,
    g: np.ndarray,
    b: np.ndarray,
    points: Sequence[LegendPoint],
    snap_last_t: Optional[float] = None,
) -> np.ndarray:
    """Vectorized mapping: RGB -> scalar value by projecting to the nearest legend polyline segment in RGB space."""
    if r.shape != g.shape or r.shape != b.shape:
        raise ValueError("RGB bands must have the same shape")
    if len(points) < 2:
        raise ValueError("Need at least 2 legend points")

    rr = r.astype(np.float32, copy=False)
    gg = g.astype(np.float32, copy=False)
    bb = b.astype(np.float32, copy=False)

    out = np.full(rr.shape, np.nan, dtype=np.float32)
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
        if snap_last is not None and i == last_seg_idx:
            # Important: apply snap BEFORE distance comparison (affects which segment wins).
            try:
                t[t > np.float32(snap_last)] = np.float32(1.0)
            except Exception:
                pass
        pr = c1r + t * vr
        pg = c1g + t * vg
        pb = c1b + t * vb
        dist_sq = (rr - pr) ** 2 + (gg - pg) ** 2 + (bb - pb) ** 2

        mask = dist_sq < min_dist
        if not np.any(mask):
            continue

        base = np.float32(v1)
        delta = np.float32(v2 - v1)
        out[mask] = base + t[mask].astype(np.float32, copy=False) * delta
        min_dist[mask] = dist_sq[mask].astype(np.float32, copy=False)

    return out


def mask_black_lines(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Detect neutral dark 'linework' (not intense red/brown) and return mask."""
    rr = r.astype(np.int16, copy=False)
    gg = g.astype(np.int16, copy=False)
    bb = b.astype(np.int16, copy=False)
    return (rr < 75) & (gg < 75) & (bb < 75) & (np.abs(rr - gg) < 15) & (np.abs(gg - bb) < 15)
