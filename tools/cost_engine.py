# -*- coding: utf-8 -*-
"""QGIS-free grid pathfinding kernels for least-cost surfaces and networks.

Moving :func:`neighbors`, :func:`astar_path`, :func:`dijkstra_full` and
:func:`reconstruct_path` out of the PyQGIS dialog keeps the Dijkstra/A*
accumulation, reverse-graph relaxation, midpoint friction averaging and NoData
handling directly testable without QGIS.
"""

from __future__ import annotations

import heapq
import math
from typing import Callable, List, Optional, Tuple

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


def neighbors(allow_diagonal: bool, dx: float, dy: float) -> List[Tuple[int, int, float]]:
    """Return the ``(d_row, d_col, step_length)`` moves available from one cell.

    Known limitation, disclosed rather than fixed: this is an 8-neighbour (or,
    with ``allow_diagonal=False``, 4-neighbour) grid walk, so every path is
    quantised to 45-degree (or 90-degree) increments.
    """
    moves = [(-1, 0, float(dy)), (1, 0, float(dy)), (0, -1, float(dx)), (0, 1, float(dx))]
    if allow_diagonal:
        dxy = math.hypot(dx, dy)
        moves.extend([(-1, -1, dxy), (-1, 1, dxy), (1, -1, dxy), (1, 1, dxy)])
    return moves


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
    moves = neighbors(allow_diagonal, dx, dy)

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

        z0 = float(dem[r, c])
        for dr, dc, horiz in moves:
            nr = r + dr
            nc = c + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue
            if nodata_mask[nr, nc]:
                continue
            dz = float(dem[nr, nc]) - z0
            w = _edge_cost(model_key, horiz, dz, model_params, cost_mode=cost_mode)
            if (not math.isfinite(w)) or w < 0.0:
                continue
            if friction is not None:
                _skip_friction = False
                try:
                    f0 = float(friction[r, c])
                    f1 = float(friction[nr, nc])
                except Exception as _exc:
                    log_swallowed("cost_engine.astar_path", _exc)
                    _skip_friction = True
                if _skip_friction or not (math.isfinite(f0) and math.isfinite(f1) and f0 > 0.0 and f1 > 0.0):
                    continue
                w *= 0.5 * (f0 + f1)
                if (not math.isfinite(w)) or w < 0.0:
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
    moves = neighbors(allow_diagonal, dx, dy)
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

        z0 = float(dem[r, c])
        for dr, dc, horiz in moves:
            nr = r + dr
            nc = c + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue
            if nodata_mask[nr, nc]:
                continue

            dz = float(dem[nr, nc]) - z0
            edge_dz = -dz if reverse else dz
            w = _edge_cost(model_key, horiz, edge_dz, model_params, cost_mode=cost_mode)
            if (not math.isfinite(w)) or w < 0.0:
                continue
            if friction is not None:
                _skip_friction = False
                try:
                    f0 = float(friction[r, c])
                    f1 = float(friction[nr, nc])
                except Exception as _exc:
                    log_swallowed("cost_engine.dijkstra_full", _exc)
                    _skip_friction = True
                if _skip_friction or not (math.isfinite(f0) and math.isfinite(f1) and f0 > 0.0 and f1 > 0.0):
                    continue
                w *= 0.5 * (f0 + f1)
                if (not math.isfinite(w)) or w < 0.0:
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
_astar_path = astar_path
_dijkstra_full = dijkstra_full
_reconstruct_path = reconstruct_path

__all__ = [
    "neighbors",
    "astar_path",
    "dijkstra_full",
    "reconstruct_path",
    "_neighbors",
    "_astar_path",
    "_dijkstra_full",
    "_reconstruct_path",
]
