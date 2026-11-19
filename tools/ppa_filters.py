# -*- coding: utf-8 -*-
"""QGIS-free Proximal Point Analysis (PPA) planar proximity graph filters.

References:
- Gabriel, K. R., & Sokal, R. R. (1969). A new statistical approach to geographic
  variation analysis. Systematic Zoology, 18(3), 259-278.
- Matula, D. W., & Sokal, R. R. (1980). Properties of Gabriel graphs relevant to
  geographic variation research and the clustering of points in the plane.
  Geographical Analysis, 12(3), 205-222.
- Toussaint, G. T. (1980). The relative neighbourhood graph of a finite planar set.
  Pattern Recognition, 12(4), 261-268.
"""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple


_COLOC_SQ_TOL = 1e-6  # (1 mm)^2 for projected meter coordinates


def _dedupe_edges(n: int, edges: Iterable[Tuple[int, int]]) -> List[Tuple[int, int]]:
    seen = set()
    out: List[Tuple[int, int]] = []
    for raw_a, raw_b in edges:
        a = int(raw_a)
        b = int(raw_b)
        if a == b or not (0 <= a < n and 0 <= b < n):
            continue
        key = (a, b) if a < b else (b, a)
        if key not in seen:
            seen.add(key)
            out.append(key)
    out.sort()
    return out


def ppa_filter_gabriel(
    pts: Sequence[Sequence[float]],
    edges: Iterable[Tuple[int, int]],
    *,
    rel_tol: float = 1e-9,
    coloc_sq_tol: float = _COLOC_SQ_TOL,
) -> List[Tuple[int, int]]:
    """Filter candidate edges to the strict Gabriel graph (closed diametral disk).

    Edge (a, b) is kept iff d^2(c, midpoint(a, b)) > r^2 * (1 + rel_tol) for all
    third points c not co-located with a or b (within sqrt(coloc_sq_tol)).
    Cocircular points on the diameter circle fail strict '>' and reject diagonals.
    """
    n = int(len(pts))
    coords = [(float(p[0]), float(p[1])) for p in pts]
    cand = _dedupe_edges(n, edges)
    kept: List[Tuple[int, int]] = []
    margin = 1.0 + max(0.0, float(rel_tol))
    coloc2 = max(0.0, float(coloc_sq_tol))

    for a, b in cand:
        ax, ay = coords[a]
        bx, by = coords[b]
        midx = 0.5 * (ax + bx)
        midy = 0.5 * (ay + by)
        r2 = (ax - midx) ** 2 + (ay - midy) ** 2

        min_dc2 = math.inf
        for c in range(n):
            if c == a or c == b:
                continue
            cx, cy = coords[c]
            da2 = (cx - ax) ** 2 + (cy - ay) ** 2
            db2 = (cx - bx) ** 2 + (cy - by) ** 2
            if da2 <= coloc2 or db2 <= coloc2:
                continue
            dc2 = (cx - midx) ** 2 + (cy - midy) ** 2
            if dc2 < min_dc2:
                min_dc2 = dc2
        if min_dc2 > r2 * margin:
            kept.append((a, b))
    return kept


def ppa_filter_rng(
    pts: Sequence[Sequence[float]],
    edges: Iterable[Tuple[int, int]],
    *,
    eps: float = 1e-9,
    rel_tol: float = 1e-9,
    coloc_sq_tol: float = _COLOC_SQ_TOL,
) -> List[Tuple[int, int]]:
    """Filter candidate edges to the Relative Neighborhood Graph (empty open lune).

    Edge (a, b) is rejected if any third point c (not co-located with a or b) is
    strictly closer to both endpoints:
    ``max(d^2(a, c), d^2(b, c)) < d^2(a, b) - max(eps, rel_tol * d^2(a, b))``.
    Using a relative tolerance prevents metric-scale equilateral triangles
    (e.g. 5 km sides where ``ulp(d^2) > 1e-9``) from failing rotational invariance.
    """
    n = int(len(pts))
    coords = [(float(p[0]), float(p[1])) for p in pts]
    cand = _dedupe_edges(n, edges)
    kept: List[Tuple[int, int]] = []
    eps_v = max(0.0, float(eps))
    rel_v = max(0.0, float(rel_tol))
    coloc2 = max(0.0, float(coloc_sq_tol))

    for a, b in cand:
        ax, ay = coords[a]
        bx, by = coords[b]
        dij2 = (ax - bx) ** 2 + (ay - by) ** 2
        thresh = dij2 - max(eps_v, rel_v * dij2)
        blocked = False
        for c in range(n):
            if c == a or c == b:
                continue
            cx, cy = coords[c]
            da2 = (cx - ax) ** 2 + (cy - ay) ** 2
            db2 = (cx - bx) ** 2 + (cy - by) ** 2
            if da2 <= coloc2 or db2 <= coloc2:
                continue
            if (da2 if da2 >= db2 else db2) < thresh:
                blocked = True
                break
        if not blocked:
            kept.append((a, b))
    return kept
