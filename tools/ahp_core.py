# -*- coding: utf-8 -*-
"""QGIS-free core of the AHP (Analytic Hierarchy Process) weighting.

The pairwise-comparison algebra — building a reciprocal matrix, deriving the
priority vector from the principal eigenvector, and Saaty's consistency ratio —
has no QGIS dependency, so it lives here where it can be regression-tested in a
plain Python environment (the same separation ``kriging_lite`` and
``atomic_output`` use).  The dialog imports these functions and keeps all UI and
raster work to itself.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy ships with QGIS
    np = None


# Saaty random consistency index, extended to n=15 (Saaty 1980; Alonso &
# Lamata 2006 for n>10). CR is undefined beyond the table — callers must not
# silently report 0.0 for larger matrices.
RI_TABLE = {
    1: 0.00,
    2: 0.00,
    3: 0.58,
    4: 0.90,
    5: 1.12,
    6: 1.24,
    7: 1.32,
    8: 1.41,
    9: 1.45,
    10: 1.49,
    11: 1.51,
    12: 1.54,
    13: 1.56,
    14: 1.57,
    15: 1.58,
}


def ahp_weights_from_matrix(mat: "np.ndarray") -> Tuple[List[float], float, float]:
    """Return (weights, lambda_max, CR)."""
    n = int(mat.shape[0])
    if n <= 0:
        return [], float("nan"), float("nan")
    if n == 1:
        return [1.0], 1.0, 0.0
    if np is None:
        return [1.0 / float(n)] * n, float("nan"), float("nan")

    try:
        vals, vecs = np.linalg.eig(mat)
        idx = int(np.argmax(np.real(vals)))
        lam = float(np.real(vals[idx]))
        v = np.real(vecs[:, idx])
        v = np.abs(v)
        if float(np.sum(v)) <= 0:
            w = np.ones((n,), dtype=float) / float(n)
        else:
            w = v / float(np.sum(v))
        w = [float(x) for x in w.tolist()]
    except Exception:
        w = [1.0 / float(n)] * n
        lam = float("nan")

    cr = 0.0
    try:
        if n <= 2:
            cr = 0.0
        else:
            ci = (float(lam) - float(n)) / float(n - 1)
            ri = RI_TABLE.get(n)
            # Beyond the RI table CR is undefined; NaN (rendered as "-") is
            # honest, whereas 0.0 would falsely certify consistency.
            cr = float(ci / float(ri)) if (ri is not None and float(ri) > 0) else float("nan")
    except Exception:
        cr = float("nan")
    return w, float(lam), float(cr)


def sanitize_pair_values(pairs_raw: Any, keys: List[str]) -> Dict[Tuple[str, str], float]:
    """Normalize pairwise comparison values to {(a, b): ratio} with a before b in `keys` order.

    Accepts either a dict keyed by (a, b) tuples/lists, or a list of dicts like
    {"left_group"/"left_layer_id": ..., "right_group"/"right_layer_id": ..., "value": ...}
    (the serialized JSON form). Pairs referencing unknown keys are dropped and
    values are clamped to the Saaty scale [1/9, 9]. Missing pairs default to 1.
    """
    order = {str(k): i for i, k in enumerate(keys or [])}
    out: Dict[Tuple[str, str], float] = {}

    def _put(a: Any, b: Any, v: Any) -> None:
        a0 = str(a or "").strip()
        b0 = str(b or "").strip()
        if a0 not in order or b0 not in order or a0 == b0:
            return
        try:
            v0 = float(v)
        except Exception:
            return
        if not math.isfinite(v0) or v0 <= 0:
            return
        if order[a0] > order[b0]:
            a0, b0 = b0, a0
            v0 = 1.0 / v0
        v0 = max(1.0 / 9.0, min(9.0, v0))
        out[(a0, b0)] = float(v0)

    if isinstance(pairs_raw, dict):
        for key, value in pairs_raw.items():
            if isinstance(key, (tuple, list)) and len(key) == 2:
                _put(key[0], key[1], value)
    elif isinstance(pairs_raw, (list, tuple)):
        for item in pairs_raw:
            if not isinstance(item, dict):
                continue
            left = item.get("left_group", item.get("left_layer_id"))
            right = item.get("right_group", item.get("right_layer_id"))
            _put(left, right, item.get("value"))

    for i, a in enumerate(keys or []):
        for b in list(keys or [])[i + 1:]:
            out.setdefault((str(a), str(b)), 1.0)
    return out


def matrix_from_pairs(keys: List[str], pairs: Dict[Tuple[str, str], float]) -> Optional["np.ndarray"]:
    n = int(len(keys or []))
    if n <= 0 or np is None:
        return None
    mat = np.ones((n, n), dtype=float)
    index = {str(k): i for i, k in enumerate(keys)}
    for (a, b), v in (pairs or {}).items():
        ia = index.get(str(a))
        ib = index.get(str(b))
        if ia is None or ib is None or ia == ib:
            continue
        try:
            v0 = float(v)
        except Exception:
            continue
        if not math.isfinite(v0) or v0 <= 0:
            continue
        mat[ia, ib] = v0
        mat[ib, ia] = 1.0 / v0
    return mat


def compute_hierarchy_summary(
    *,
    criteria_rows: List[Tuple[str, str]],
    criterion_groups: Dict[str, str],
    group_pairs: Dict[Tuple[str, str], float],
    local_pairs: Dict[str, Dict[Tuple[str, str], float]],
) -> Dict[str, Any]:
    """Compute hierarchical AHP weights (group level x local level).

    Returns group weights, per-group local weights/CR, global per-criterion
    weights (group weight x local weight) and a synthesized `global_pairwise`
    dict {(id_i, id_j): w_i / w_j} that can seed the flat pairwise table.
    """
    ids = [str(layer_id) for layer_id, _label in (criteria_rows or [])]
    groups: List[str] = []
    for layer_id in ids:
        g = str(criterion_groups.get(layer_id) or "").strip()
        if g and g not in groups:
            groups.append(g)

    group_weights: Dict[str, float] = {}
    group_cr: Optional[float] = None
    mat_g = matrix_from_pairs(groups, group_pairs or {})
    if mat_g is not None:
        w_g, _lam, cr0 = ahp_weights_from_matrix(mat_g)
        group_weights = {g: float(w) for g, w in zip(groups, w_g)}
        group_cr = float(cr0) if math.isfinite(float(cr0)) else None
    elif groups:
        group_weights = {g: 1.0 / float(len(groups)) for g in groups}

    local_weights: Dict[str, Dict[str, float]] = {}
    local_cr: Dict[str, Optional[float]] = {}
    for g in groups:
        member_ids = [layer_id for layer_id in ids if str(criterion_groups.get(layer_id) or "") == g]
        if not member_ids:
            continue
        mat_l = matrix_from_pairs(member_ids, (local_pairs or {}).get(g) or {})
        if mat_l is not None:
            w_l, _lam_l, cr_l = ahp_weights_from_matrix(mat_l)
            local_weights[g] = {m: float(w) for m, w in zip(member_ids, w_l)}
            local_cr[g] = float(cr_l) if math.isfinite(float(cr_l)) else None
        else:
            local_weights[g] = {m: 1.0 / float(len(member_ids)) for m in member_ids}
            local_cr[g] = None

    global_weights: Dict[str, float] = {}
    for layer_id in ids:
        g = str(criterion_groups.get(layer_id) or "").strip()
        gw = float(group_weights.get(g, 0.0))
        lw = float(local_weights.get(g, {}).get(layer_id, 0.0))
        global_weights[layer_id] = gw * lw

    total = sum(global_weights.values())
    if total > 0:
        global_weights = {k: v / total for k, v in global_weights.items()}

    global_pairwise: Dict[Tuple[str, str], float] = {}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            wa = float(global_weights.get(a, 0.0))
            wb = float(global_weights.get(b, 0.0))
            ratio = (wa / wb) if wb > 0 else 1.0
            if not math.isfinite(ratio) or ratio <= 0:
                ratio = 1.0
            global_pairwise[(a, b)] = max(1.0 / 9.0, min(9.0, ratio))

    return {
        "group_order": list(groups),
        "group_weights": group_weights,
        "group_consistency_ratio": group_cr,
        "local_weights": local_weights,
        "local_consistency_ratio": local_cr,
        "criterion_groups": dict(criterion_groups or {}),
        "global_weights": global_weights,
        "global_pairwise": global_pairwise,
    }
