# -*- coding: utf-8 -*-
"""QGIS-free grid pathfinding kernels for least-cost surfaces and networks.

Moving :func:`neighbors`, :func:`step_edge_cost`, :func:`astar_path`,
:func:`dijkstra_full` and :func:`reconstruct_path` out of the PyQGIS dialog
keeps the Dijkstra/A* accumulation, reverse-graph relaxation, midpoint friction
averaging, 16-neighbour knight's-move anti-tunneling and NoData handling
directly testable without QGIS.

Grid elongation bounds (Huber & Church 1985; Goodchild 1977; Douglas 1994):
- 4-neighbour (orthogonal): up to ~41.42% over Euclidean geodesic.
- 8-neighbour (queen):      up to ~8.24% over Euclidean geodesic.
- 16-neighbour (knight):    up to ~2.75% over Euclidean geodesic.
"""

from __future__ import annotations

import heapq
import math
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .cost_models import (
    MODEL_CONOLLY_LAKE,
    MODEL_HERZOG_METABOLIC,
    MODEL_HERZOG_WHEELED,
    MODEL_NAISMITH,
    MODEL_PANDOLF,
    MODEL_TOBLER,
    edge_cost as _edge_cost,
)
from .swallow_log import log_swallowed

# Exact worst-case flat-plane grid elongation percentages over [0, 45 deg].
MAX_ELONGATION_PCT = {
    4: 41.42,
    8: 8.24,
    16: 2.75,
}


def grid_connectivity_info(allow_diagonal: bool, allow_knight: bool = False) -> Dict[str, object]:
    """Return structured connectivity metadata for a pathfinding run."""
    if not allow_diagonal:
        n_dir = 4
        label = "4-neighbour grid (90-degree quantised, cost overestimated by up to ~41.4%)"
    elif allow_knight:
        n_dir = 16
        label = "16-neighbour knight's-move grid (Huber & Church 1985, cost overestimated by up to ~2.75%)"
    else:
        n_dir = 8
        label = "8-neighbour grid (45-degree quantised, cost overestimated by up to ~8.2%)"
    return {
        "n_directions": n_dir,
        "allow_diagonal": bool(allow_diagonal),
        "allow_knight": bool(allow_diagonal and allow_knight),
        "max_grid_elongation_pct": float(MAX_ELONGATION_PCT[n_dir]),
        "connectivity": label,
    }


def neighbors(
    allow_diagonal: bool,
    dx: float,
    dy: float,
    allow_knight: bool = False,
) -> List[Tuple[int, int, float]]:
    """Return the ``(d_row, d_col, step_length)`` moves available from one cell.

    Supports 4-neighbour (``allow_diagonal=False``), 8-neighbour (default when
    ``allow_diagonal=True``), and 16-neighbour knight's-move connectivity
    (``allow_diagonal=True, allow_knight=True``, reducing maximum grid
    elongation from ~8.24% to ~2.75%; Huber & Church 1985).
    """
    moves = [(-1, 0, float(dy)), (1, 0, float(dy)), (0, -1, float(dx)), (0, 1, float(dx))]
    if allow_diagonal:
        dxy = math.hypot(dx, dy)
        moves.extend([(-1, -1, dxy), (-1, 1, dxy), (1, -1, dxy), (1, 1, dxy)])
        if allow_knight:
            d2r = math.hypot(dx, 2.0 * dy)
            d2c = math.hypot(2.0 * dx, dy)
            moves.extend([
                (-2, -1, d2r), (-2, 1, d2r), (2, -1, d2r), (2, 1, d2r),
                (-1, -2, d2c), (1, -2, d2c), (-1, 2, d2c), (1, 2, d2c),
            ])
    return moves


def _knight_intermediates(r: int, c: int, dr: int, dc: int) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Return the two intermediate grid cells crossed by a knight's move.

    A segment from ``(r, c)`` to ``(r+2, c+1)`` traverses ``(r, c)`` [0, 0.25],
    ``m1 = (r+1, c)`` [0.25, 0.5], ``m2 = (r+1, c+1)`` [0.5, 0.75], and
    ``(r+2, c+1)`` [0.75, 1.0]. Returning ``(m1, m2)`` in forward traversal
    order keeps forward and reverse edge costs exact transposes.
    """
    if abs(dr) == 2:
        sr = 1 if dr > 0 else -1
        return (r + sr, c), (r + sr, c + dc)
    sc = 1 if dc > 0 else -1
    return (r, c + sc), (r + dr, c + sc)


def step_edge_cost(
    dem,
    nodata_mask,
    friction,
    r: int,
    c: int,
    nr: int,
    nc: int,
    horiz: float,
    model_key: str,
    model_params: dict,
    cost_mode: str = "time_s",
    reverse: bool = False,
) -> Optional[float]:
    """Compute a single grid step cost from ``(r, c)`` to ``(nr, nc)``.

    Returns ``None`` if the step is blocked by NoData, non-finite/non-positive
    friction, steep cliff cutoff, or 1-pixel barrier tunneling.

    For 16-neighbour knight's moves (``|dr|+|dc| == 3``), the step is split
    into two equal half-segments through the midpoint elevation of the two
    traversed intermediate cells ``(m1, m2)``, with exact quarter-segment
    friction weighting (``0.5*(f0+fm1)`` on the first half and
    ``0.5*(fm2+f1)`` on the second half). This prevents tunneling across
    1-pixel cliffs, NoData walls, or high-friction rivers while remaining
    exact on planar slopes and strictly transpose-symmetric under ``reverse``.
    """
    dr = nr - r
    dc = nc - c
    z0 = float(dem[r, c])
    z1 = float(dem[nr, nc])

    # 16-neighbour knight's move: |dr| + |dc| == 3
    if (abs(dr) + abs(dc)) == 3:
        (m1r, m1c), (m2r, m2c) = _knight_intermediates(r, c, dr, dc)
        if nodata_mask is not None and (nodata_mask[m1r, m1c] or nodata_mask[m2r, m2c]):
            return None
        zm1 = float(dem[m1r, m1c])
        zm2 = float(dem[m2r, m2c])
        if (not math.isfinite(zm1)) or (not math.isfinite(zm2)):
            return None
        z_mid = 0.5 * (zm1 + zm2)
        half_h = 0.5 * float(horiz)
        if reverse:
            # Reversed edge: (nr, nc) -> m2 -> m1 -> (r, c)
            dz_first = z_mid - z1
            dz_second = z0 - z_mid
        else:
            # Forward edge: (r, c) -> m1 -> m2 -> (nr, nc)
            dz_first = z_mid - z0
            dz_second = z1 - z_mid
        w_first = _edge_cost(model_key, half_h, dz_first, model_params, cost_mode=cost_mode)
        w_second = _edge_cost(model_key, half_h, dz_second, model_params, cost_mode=cost_mode)
        if (not math.isfinite(w_first)) or w_first < 0.0 or (not math.isfinite(w_second)) or w_second < 0.0:
            return None
        if friction is not None:
            try:
                f0 = float(friction[r, c])
                f1 = float(friction[nr, nc])
                fm1 = float(friction[m1r, m1c])
                fm2 = float(friction[m2r, m2c])
            except Exception as _exc:
                log_swallowed("cost_engine.step_edge_cost.knight_friction", _exc)
                return None
            if not (
                math.isfinite(f0) and f0 > 0.0
                and math.isfinite(f1) and f1 > 0.0
                and math.isfinite(fm1) and fm1 > 0.0
                and math.isfinite(fm2) and fm2 > 0.0
            ):
                return None
            f_start_half = 0.5 * (f0 + fm1)
            f_end_half = 0.5 * (fm2 + f1)
            if reverse:
                w = w_first * f_end_half + w_second * f_start_half
            else:
                w = w_first * f_start_half + w_second * f_end_half
        else:
            w = w_first + w_second
        if (not math.isfinite(w)) or w < 0.0:
            return None
        return float(w)

    # 4- or 8-neighbour move: prevent 1-pixel diagonal NoData barrier tunneling.
    if dr != 0 and dc != 0 and nodata_mask is not None and nodata_mask[nr, c] and nodata_mask[r, nc]:
        return None

    dz = z1 - z0
    edge_dz = -dz if reverse else dz
    w = _edge_cost(model_key, horiz, edge_dz, model_params, cost_mode=cost_mode)
    if (not math.isfinite(w)) or w < 0.0:
        return None
    if friction is not None:
        try:
            f0 = float(friction[r, c])
            f1 = float(friction[nr, nc])
        except Exception as _exc:
            log_swallowed("cost_engine.step_edge_cost.friction", _exc)
            return None
        if not (math.isfinite(f0) and math.isfinite(f1) and f0 > 0.0 and f1 > 0.0):
            return None
        f_mult = 0.5 * (f0 + f1)
        if dr != 0 and dc != 0:
            fa = float(friction[nr, c])
            fb = float(friction[r, nc])
            fa_ok = math.isfinite(fa) and fa > 0.0
            fb_ok = math.isfinite(fb) and fb > 0.0
            if (not fa_ok) and (not fb_ok):
                return None
            if fa_ok and fb_ok:
                f_mult = max(f_mult, min(fa, fb))
        w *= f_mult
        if (not math.isfinite(w)) or w < 0.0:
            return None
    return float(w)


def _admissible_vmax_mps(model_key: str, model_params: dict) -> Optional[float]:
    """Return an upper bound on traversal speed (m/s) for an admissible A*
    time heuristic, or ``None`` if the heuristic must stay disabled (0).
    """
    params = model_params or {}
    min_speed_mps = max(1e-6, float(params.get("min_speed_mps", 0.05)))
    if model_key == MODEL_TOBLER:
        if float(params.get("tobler_slope_factor", 3.5)) < 0.0:
            return None
        t_min = max(1e-6, float(params.get("tobler_min_speed_mps", 0.05)))
        return max(t_min, float(params.get("tobler_base_kmh", 6.0)) * 1000.0 / 3600.0)
    if model_key == MODEL_NAISMITH:
        return max(1e-6, float(params.get("naismith_horizontal_kmh", 5.0)) * 1000.0 / 3600.0)
    if model_key == MODEL_HERZOG_METABOLIC:
        # Peak speed factor is 1.64 / min(den) ~ 2.67024 near -10.55% downhill.
        base_mps = max(min_speed_mps, float(params.get("herzog_base_kmh", 5.0)) * 1000.0 / 3600.0)
        return max(min_speed_mps, base_mps * 2.671)
    if model_key == MODEL_CONOLLY_LAKE:
        return max(min_speed_mps, float(params.get("conolly_base_kmh", 5.0)) * 1000.0 / 3600.0)
    if model_key == MODEL_HERZOG_WHEELED:
        return max(min_speed_mps, float(params.get("wheeled_base_kmh", 4.0)) * 1000.0 / 3600.0)
    if model_key == MODEL_PANDOLF:
        return max(0.05, float(params.get("pandolf_speed_mps", 5.0 * 1000.0 / 3600.0)))
    return max(min_speed_mps, float(params.get("naismith_horizontal_kmh", 5.0)) * 1000.0 / 3600.0)


def astar_path(
    dem,
    nodata_mask,
    start_rc: Tuple[int, int],
    end_rc: Tuple[int, int],
    dx: float,
    dy: float,
    allow_diagonal: bool,
    model_key: str,
    model_params: dict,
    cost_mode: str = "time_s",
    cancel_check: Optional[Callable[[], bool]] = None,
    friction=None,
    friction_min: Optional[float] = None,
    allow_knight: bool = False,
):
    """Run A* between ``start_rc`` and ``end_rc`` on ``dem``.

    Returns ``(prev, total_cost)`` where ``total_cost`` is ``None`` if
    cancelled or unreachable.
    """
    rows, cols = dem.shape
    sr, sc = start_rc
    er, ec = end_rc
    start_idx = sr * cols + sc
    end_idx = er * cols + ec

    gscore = np.full(rows * cols, np.inf, dtype=np.float64)
    prev = np.full(rows * cols, -1, dtype=np.int32)
    gscore[start_idx] = 0.0

    vmax = _admissible_vmax_mps(model_key, model_params or {}) if cost_mode == "time_s" else None
    if vmax is None:
        # Keep heuristic admissible (0) for energy or unrestricted parameter regimes.
        def hfun(_r: int, _c: int) -> float:
            return 0.0
    else:
        fmin = 1.0
        if friction_min is None:
            if friction is not None:
                try:
                    valid_f = friction[np.isfinite(friction) & (friction > 0)]
                    fmin = max(0.0, float(np.nanmin(valid_f))) if valid_f.size else 1.0
                except Exception as _exc:
                    log_swallowed("cost_engine.astar_path.fmin", _exc)
                    fmin = 1.0
        else:
            try:
                fmin = max(0.0, float(friction_min))
            except Exception as _exc:
                log_swallowed("cost_engine.astar_path.friction_min", _exc)
                fmin = 1.0

        def hfun(r: int, c: int) -> float:
            return (math.hypot((ec - c) * dx, (er - r) * dy) / vmax) * fmin

    heap = [(hfun(sr, sc), 0.0, start_idx)]
    moves = neighbors(allow_diagonal, dx, dy, allow_knight=allow_knight)

    while heap:
        if cancel_check and cancel_check():
            return None, None
        _f, g, idx = heapq.heappop(heap)
        if g != gscore[idx]:
            continue
        if idx == end_idx:
            return prev, float(g)

        r = idx // cols
        c = idx % cols
        if nodata_mask[r, c]:
            continue

        for dr, dc, horiz in moves:
            nr = r + dr
            nc = c + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue
            if nodata_mask[nr, nc]:
                continue
            w = step_edge_cost(
                dem,
                nodata_mask,
                friction,
                r,
                c,
                nr,
                nc,
                horiz,
                model_key,
                model_params,
                cost_mode=cost_mode,
                reverse=False,
            )
            if w is None:
                continue

            nidx = nr * cols + nc
            ng = g + w
            if ng < gscore[nidx]:
                gscore[nidx] = ng
                prev[nidx] = idx
                heapq.heappush(heap, (ng + hfun(nr, nc), ng, nidx))

    return prev, None


def dijkstra_full(
    dem,
    nodata_mask,
    start_rc: Tuple[int, int],
    dx: float,
    dy: float,
    allow_diagonal: bool,
    model_key: str,
    model_params: dict,
    cost_mode: str = "time_s",
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    friction=None,
    reverse: bool = False,
    allow_knight: bool = False,
):
    """Single-source shortest costs over the DEM grid.

    ``reverse=False``: ``dist[x] = cost(start_rc -> x)``.
    ``reverse=True``:  ``dist[x] = cost(x -> start_rc)``, computed on the reversed
    graph by negating the elevation delta in the (anisotropic) edge cost.
    """
    rows, cols = dem.shape
    sr, sc = start_rc
    start_idx = sr * cols + sc

    dist = np.full(rows * cols, np.inf, dtype=np.float64)
    prev = np.full(rows * cols, -1, dtype=np.int32)
    dist[start_idx] = 0.0

    heap = [(0.0, start_idx)]
    moves = neighbors(allow_diagonal, dx, dy, allow_knight=allow_knight)
    total = rows * cols
    popped = 0

    while heap:
        if cancel_check and cancel_check():
            return None, None
        d, idx = heapq.heappop(heap)
        if d != dist[idx]:
            continue

        popped += 1
        if progress_cb and popped % 5000 == 0:
            progress_cb(min(99.0, 100.0 * popped / max(1, total)))

        r = idx // cols
        c = idx % cols
        if nodata_mask[r, c]:
            continue

        for dr, dc, horiz in moves:
            nr = r + dr
            nc = c + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue
            if nodata_mask[nr, nc]:
                continue
            w = step_edge_cost(
                dem,
                nodata_mask,
                friction,
                r,
                c,
                nr,
                nc,
                horiz,
                model_key,
                model_params,
                cost_mode=cost_mode,
                reverse=reverse,
            )
            if w is None:
                continue
            nidx = nr * cols + nc
            nd = d + w
            if nd < dist[nidx]:
                dist[nidx] = nd
                prev[nidx] = idx
                heapq.heappush(heap, (nd, nidx))

    if progress_cb:
        progress_cb(100.0)
    return dist, prev


def reconstruct_path(prev, start_rc: Tuple[int, int], end_rc: Tuple[int, int], cols: int, rows: int) -> List[int]:
    """Reconstruct linear cell indices from ``start_rc`` to ``end_rc``."""
    start_idx = start_rc[0] * cols + start_rc[1]
    end_idx = end_rc[0] * cols + end_rc[1]
    if start_idx == end_idx:
        return [start_idx]
    if prev[end_idx] == -1:
        return []

    path = []
    cur = end_idx
    max_steps = rows * cols + 1
    steps = 0
    while cur != -1 and steps < max_steps:
        path.append(cur)
        if cur == start_idx:
            break
        cur = int(prev[cur])
        steps += 1
    if not path or path[-1] != start_idx:
        return []
    path.reverse()
    return path


_neighbors = neighbors
_step_edge_cost = step_edge_cost
_astar_path = astar_path
_dijkstra_full = dijkstra_full
_reconstruct_path = reconstruct_path


__all__ = [
    "MAX_ELONGATION_PCT",
    "grid_connectivity_info",
    "neighbors",
    "step_edge_cost",
    "astar_path",
    "dijkstra_full",
    "reconstruct_path",
    "_neighbors",
    "_step_edge_cost",
    "_astar_path",
    "_dijkstra_full",
    "_reconstruct_path",
]
