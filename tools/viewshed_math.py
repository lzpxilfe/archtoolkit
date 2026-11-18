# -*- coding: utf-8 -*-
"""QGIS-free helpers for GDAL viewshed curvature/refraction and Higuchi zone breaks.

References:
- GDAL gdal_viewshed documentation (`-cc` curvature/refraction coefficient:
  0 when curvature disabled, 1 - k when enabled with terrestrial refraction k).
- Higuchi, T. (1975). The visual and spatial structure of landscapes.
"""

from __future__ import annotations

from typing import Optional, Tuple


def calculate_gdal_viewshed_cc(curvature: bool, refraction: bool, refraction_coeff: float) -> float:
    """Compute GDAL viewshed `-cc` parameter combining Earth curvature and refraction."""
    use_curvature = bool(curvature)
    use_refraction = bool(refraction)
    # Refraction is a correction applied together with curvature.
    if use_refraction and not use_curvature:
        use_curvature = True
    if not use_curvature:
        return 0.0
    if use_refraction:
        cc = 1.0 - float(refraction_coeff)
        return float(max(0.0, min(1.0, cc)))
    return 1.0


def order_higuchi_pair(near: float, mid: float) -> Tuple[float, float]:
    """Enforce strictly ascending `near < mid` Higuchi distance breaks (metres)."""
    near_v = float(near)
    mid_v = float(mid)
    if near_v > mid_v:
        near_v, mid_v = mid_v, near_v
    if near_v >= mid_v:
        mid_v = near_v + 1.0
    return (near_v, mid_v)


def resolve_higuchi_thresholds(
    near_m: Optional[float] = None,
    mid_m: Optional[float] = None,
    *,
    default_near: float = 150.0,
    default_mid: float = 1000.0,
) -> Tuple[float, float]:
    """Resolve optional Higuchi thresholds against defaults and enforce ordering."""
    n_val = float(default_near) if near_m is None else float(near_m)
    m_val = float(default_mid) if mid_m is None else float(mid_m)
    return order_higuchi_pair(n_val, m_val)


def format_higuchi_distance(value_m) -> str:
    """Format a Higuchi distance threshold for legends and reports."""
    try:
        val = float(value_m)
    except (TypeError, ValueError):
        return str(value_m)
    if val >= 1000.0:
        return "{0:g}km".format(val / 1000.0)
    return "{0:g}m".format(val)
