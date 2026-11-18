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
from typing import Any, Dict, List, Optional, Sequence, Tuple
from .swallow_log import log_swallowed

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
        _skip_142 = False
        try:
            v0 = float(v)
        except Exception as _exc:
            log_swallowed("tools/ahp_core.py:144 (matrix_from_pairs)", _exc)
            _skip_142 = True
        if _skip_142:
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

    The flat table can only express ratios on the Saaty scale [1/9, 9], but a
    hierarchy easily produces global weight ratios beyond it (two levels of 9:1
    multiply out to 81:1).  Those ratios are clamped, which means the flat seed
    is only an *approximation* of the hierarchy whenever clamping happened --
    re-deriving weights from the seeded table will not reproduce these numbers.
    `global_weights` stays authoritative.  So the clamping is reported rather
    than applied silently:

    - `global_pairwise_clamped` (bool): True if any ratio had to be clamped.
    - `global_pairwise_clamped_pairs` (list of (id_i, id_j) tuples): the keys of
      `global_pairwise` that were clamped, in `global_pairwise` order.
    - `global_pairwise_clamped_count` (int): length of that list, so a caller
      that only needs a count does not have to compute one.

    A ratio can also be unusable rather than merely out of scale: a criterion
    left out of every group has global weight 0, so its ratio is 0, infinite or
    0/0.  Those pairs fall back to 1.0 ("equally important"), which is just as
    approximate as a clamp, and are reported under sibling keys so a caller can
    tell the two causes apart:

    - `global_pairwise_substituted` (bool): True if any ratio was replaced
      because a global weight was zero or non-finite.
    - `global_pairwise_substituted_pairs` (list of (id_i, id_j) tuples): those
      keys of `global_pairwise`, in `global_pairwise` order.
    - `global_pairwise_substituted_count` (int): length of that list.

    The two lists never overlap: a substituted ratio is exactly 1.0, which is
    on the Saaty scale and therefore never clamped.
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
    global_pairwise_clamped_pairs: List[Tuple[str, str]] = []
    global_pairwise_substituted_pairs: List[Tuple[str, str]] = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            wa = float(global_weights.get(a, 0.0))
            wb = float(global_weights.get(b, 0.0))
            ratio = (wa / wb) if wb > 0 else float("nan")
            if not math.isfinite(ratio) or ratio <= 0:
                # A criterion that was never assigned to a group keeps global
                # weight 0, so its ratio against another criterion is 0, or
                # infinite, or 0/0 -- none of which the flat table can express.
                # Falling back to 1.0 says "equally important", which is the
                # maximally wrong answer when one side carries all the weight,
                # so this substitution is reported like the Saaty clamp instead
                # of being applied in silence.
                ratio = 1.0
                global_pairwise_substituted_pairs.append((a, b))
            scaled = max(1.0 / 9.0, min(9.0, ratio))
            # Only count a clamp that really moved the ratio: the eigenvector
            # solve returns an exact 9:1 hierarchy as 9.000000000000002, and
            # warning the user about that float noise would be a false alarm.
            if not math.isclose(scaled, ratio, rel_tol=1e-9):
                global_pairwise_clamped_pairs.append((a, b))
            global_pairwise[(a, b)] = scaled

    return {
        "group_order": list(groups),
        "group_weights": group_weights,
        "group_consistency_ratio": group_cr,
        "local_weights": local_weights,
        "local_consistency_ratio": local_cr,
        "criterion_groups": dict(criterion_groups or {}),
        "global_weights": global_weights,
        "global_pairwise": global_pairwise,
        "global_pairwise_clamped": bool(global_pairwise_clamped_pairs),
        "global_pairwise_clamped_pairs": list(global_pairwise_clamped_pairs),
        "global_pairwise_clamped_count": len(global_pairwise_clamped_pairs),
        "global_pairwise_substituted": bool(global_pairwise_substituted_pairs),
        "global_pairwise_substituted_pairs": list(global_pairwise_substituted_pairs),
        "global_pairwise_substituted_count": len(global_pairwise_substituted_pairs),
    }


def clamp01(expr):
    """Wrap a gdal_calc/numpy expression so its result stays within [0, 1].

    gdal_calc evaluates formulas in the numpy namespace, so minimum/maximum are
    available.  Clamping keeps scores in [0, 1] even when pixels fall outside
    the [mn, mx] stats range.
    """
    return f"minimum(maximum(({expr}), 0.0), 1.0)"


def validated_score_ranges(score_ranges):
    """Clean, clamp, sort, and overlap-check a reclass score table.

    Non-numeric or non-finite rows are dropped, scores clamped to [0, 1], and
    min/max swapped if reversed.  Raises on overlapping intervals and on gaps
    wider than one unit between consecutive rows.

    A gap wider than one unit means class codes between the rows are simply
    absent from the table, and those cells then score exactly 0.0 -
    indistinguishable from the worst listed interval in the weighted sum.
    Adjacent integer codes ([1,1] then [2,4]) stay valid: for the class-code
    rasters reclass exists for, they cover the domain with no missing code.
    """
    rows_in = score_ranges or []
    rows = []
    for row in rows_in:
        _skip_250 = False
        try:
            min_v = float(row.get("min"))
            max_v = float(row.get("max"))
            score = float(row.get("score"))
        except Exception as _exc:
            log_swallowed("tools/ahp_core.py:254 (validated_score_ranges)", _exc)
            _skip_250 = True
        if _skip_250:
            continue
        if max_v < min_v:
            min_v, max_v = max_v, min_v
        if not math.isfinite(min_v) or not math.isfinite(max_v) or not math.isfinite(score):
            continue
        score = max(0.0, min(1.0, score))
        rows.append({"min": min_v, "max": max_v, "score": score})
    rows.sort(key=lambda d: (d["min"], d["max"]))
    for idx in range(1, len(rows)):
        prev = rows[idx - 1]
        cur = rows[idx]
        prev_exact = abs(float(prev["max"]) - float(prev["min"])) <= 1e-12
        if cur["min"] < prev["max"] or (prev_exact and abs(float(cur["min"]) - float(prev["max"])) <= 1e-12):
            raise Exception(
                "\uad6c\uac04 \uc810\uc218\ud45c\uc5d0 \uc11c\ub85c \uacb9\uce58\ub294 \uad6c\uac04\uc774 \uc788\uc2b5\ub2c8\ub2e4. "
                "\ubc94\uc704\ub97c \ub2e4\uc2dc \uc870\uc815\ud558\uc138\uc694."
            )
        if float(cur["min"]) - float(prev["max"]) > 1.0 + 1e-12:
            raise Exception(
                f"\uad6c\uac04 \uc810\uc218\ud45c\uc5d0 \ube48 \uad6c\uac04\uc774 \uc788\uc2b5\ub2c8\ub2e4"
                f"({float(prev['max']):g} \uc55e \u2192 {float(cur['min']):g} \ub4a4). "
                "\uac08 \uc548\uc758 \ud074\ub798\uc2a4 \ucf54\ub4dc\ub294 0\uc810\uc73c\ub85c \uacc4\uc0b0\ub418\ubbc0\ub85c, "
                "\uad6c\uac04\uc744 \uc11c\ub85c \ub9de\ub2db\uac8c \uc870\uc815\ud558\uac70\ub098 0\uc810 \uad6c\uac04\uc744 \uba85\uc2dc\ud558\uc138\uc694."
            )
    return rows


def score_formula(*, direction, mn, mx, target_v=None, prefer_min=None, prefer_max=None, score_ranges=None):
    """Build the gdal_calc expression mapping a criterion raster (band ``A``) to
    a 0-1 suitability score, per the criterion's preference mode.

    - benefit: linear ramp, larger is better
    - cost: linear ramp, smaller is better
    - target: 1 at the target value, ramping to 0 toward mn/mx (degrading to a
      pure ramp when the target sits on a boundary)
    - range: 1 inside [prefer_min, prefer_max], ramping to 0 outside
    - reclass: piecewise scores from a validated interval table. Values outside
      the table (below the first min / above the last max) score exactly 0.0 -
      worse than any listed interval - so add an explicit row when that is not
      the intent.
    """
    mode = str(direction or "benefit")
    if mode == "cost":
        return clamp01(f"({mx} - A) / ({mx} - {mn})")
    if mode == "target":
        try:
            target0 = float(target_v) if target_v is not None else None
        except Exception:
            target0 = None
        if target0 is None or (not math.isfinite(target0)) or target0 < mn or target0 > mx:
            target0 = mn + ((mx - mn) / 2.0)
        if target0 <= mn:
            return clamp01(f"({mx} - A) / ({mx} - {mn})")
        if target0 >= mx:
            return clamp01(f"(A - {mn}) / ({mx} - {mn})")
        return clamp01(
            f"((A <= {target0}) * ((A - {mn}) / ({target0} - {mn}))) + "
            f"((A > {target0}) * (({mx} - A) / ({mx} - {target0})))"
        )
    if mode == "range":
        try:
            prefer_min0 = float(prefer_min) if prefer_min is not None else None
            prefer_max0 = float(prefer_max) if prefer_max is not None else None
        except Exception:
            prefer_min0, prefer_max0 = None, None
        invalid_prefer = (
            prefer_min0 is None
            or prefer_max0 is None
            or not math.isfinite(prefer_min0)
            or not math.isfinite(prefer_max0)
            or prefer_min0 >= prefer_max0
        )
        if invalid_prefer:
            prefer_min0 = mn + ((mx - mn) * 0.25)
            prefer_max0 = mn + ((mx - mn) * 0.75)
        if prefer_min0 <= mn and prefer_max0 >= mx:
            return "A*0 + 1"
        if prefer_min0 <= mn:
            return clamp01(
                f"(({mx} - A) / ({mx} - {prefer_max0})) * (A > {prefer_max0}) + ((A <= {prefer_max0}) * 1)"
            )
        if prefer_max0 >= mx:
            return clamp01(
                f"((A - {mn}) / ({prefer_min0} - {mn})) * (A < {prefer_min0}) + ((A >= {prefer_min0}) * 1)"
            )
        return clamp01(
            f"((A < {prefer_min0}) * ((A - {mn}) / ({prefer_min0} - {mn}))) + "
            f"(((A >= {prefer_min0}) * (A <= {prefer_max0})) * 1) + "
            f"((A > {prefer_max0}) * (({mx} - A) / ({mx} - {prefer_max0})))"
        )
    if mode == "reclass":
        rows = validated_score_ranges(score_ranges)
        if not rows:
            return "A*0"
        parts = []
        for idx, row in enumerate(rows):
            lo = float(row["min"])
            hi = float(row["max"])
            score = float(row["score"])
            if abs(hi - lo) <= 1e-12:
                parts.append(f"((A == {lo}) * {score})")
                continue
            # Half-open [lo, hi) only when the next interval starts exactly at hi
            # (so a shared boundary belongs to one row). A row followed by a gap
            # - integer class tables like [1,2],[3,4] - keeps its closed upper
            # bound; with "<" class 2 silently scored 0.0.
            abuts_next = idx + 1 < len(rows) and float(rows[idx + 1]["min"]) <= hi + 1e-12
            if abuts_next:
                parts.append(f"(((A >= {lo}) * (A < {hi})) * {score})")
            else:
                parts.append(f"(((A >= {lo}) * (A <= {hi})) * {score})")
        return " + ".join(parts) if parts else "A*0"
    return clamp01(f"(A - {mn}) / ({mx} - {mn})")


def _strict_rank_order(weights: Sequence[float], *, tol: float = 1e-12) -> List[int]:
    return sorted(range(len(weights)), key=lambda i: (-round(float(weights[i]) / max(tol, 1e-15)), i))


def _has_rank_swap(base_w: Sequence[float], pert_w: Sequence[float], *, tie_tol: float = 1e-9) -> bool:
    n = len(base_w)
    for a in range(n):
        for b in range(a + 1, n):
            diff_base = float(base_w[a]) - float(base_w[b])
            if abs(diff_base) <= tie_tol:
                continue
            diff_pert = float(pert_w[a]) - float(pert_w[b])
            if (diff_base > 0.0 and diff_pert < -tie_tol) or (diff_base < 0.0 and diff_pert > tie_tol):
                return True
    return False


def oat_weight_sensitivity(
    weights: Sequence[float],
    *,
    delta: float = 0.10,
) -> List[Dict[str, Any]]:
    """One-at-a-Time (OAT) multiplicative criterion weight sensitivity (Chen et al. 2010).

    Perturbs each criterion weight by ``(1 +/- delta)`` and rescales remaining
    weights proportionally so ``sum(w) == 1.0`` is conserved.
    """
    raw = [max(0.0, float(x)) for x in (weights or [])]
    n = len(raw)
    if n == 0:
        return []
    total = sum(raw)
    base = [x / total for x in raw] if total > 0.0 else [1.0 / float(n)] * n
    d = max(0.0, min(0.95, float(delta)))

    def _rescale(idx: int, new_wi: float) -> List[float]:
        wi = max(0.0, min(1.0, float(new_wi)))
        rem_target = max(0.0, 1.0 - wi)
        rem_base = sum(base[j] for j in range(n) if j != idx)
        out = [0.0] * n
        out[idx] = wi
        if rem_base > 0.0:
            scale = rem_target / rem_base
            for j in range(n):
                if j != idx:
                    out[j] = base[j] * scale
        elif n > 1:
            each = rem_target / float(n - 1)
            for j in range(n):
                if j != idx:
                    out[j] = each
        return out

    results: List[Dict[str, Any]] = []
    for i in range(n):
        plus_w = _rescale(i, base[i] * (1.0 + d))
        minus_w = _rescale(i, base[i] * (1.0 - d))
        shifts = [
            abs(cand[j] - base[j])
            for cand in (plus_w, minus_w)
            for j in range(n)
            if j != i
        ]
        max_other = max(shifts) if shifts else 0.0
        rank_changed = _has_rank_swap(base, plus_w) or _has_rank_swap(base, minus_w)
        results.append(
            {
                "index": int(i),
                "base_weight": float(base[i]),
                "delta": float(d),
                "plus_weights": [float(x) for x in plus_w],
                "minus_weights": [float(x) for x in minus_w],
                "max_other_shift": float(max_other),
                "rank_changed": bool(rank_changed),
            }
        )
    return results


def format_ahp_methodology_report(
    *,
    criteria: Sequence[str],
    weights: Sequence[float],
    matrix: Any = None,
    cr: Optional[float] = None,
    ci: Optional[float] = None,
    ri: Optional[float] = None,
    lambda_max: Optional[float] = None,
    weights_source: str = "pairwise_matrix",
    hierarchy: Optional[Dict[str, Any]] = None,
    sensitivity: Optional[List[Dict[str, Any]]] = None,
    notes: Optional[Sequence[str]] = None,
) -> str:
    """Format a reproducible Markdown methodology and sensitivity report for AHP."""
    names = [str(c) for c in (criteria or [])]
    w_list = [float(w) for w in (weights or [])]
    sens = sensitivity if sensitivity is not None else (oat_weight_sensitivity(w_list, delta=0.10) if len(w_list) >= 2 else [])
    sens_by_idx = {int(row["index"]): row for row in sens if isinstance(row, dict) and "index" in row}

    lines = [
        "# AHP 다기준 적합도 분석 방법론 보고서",
        "",
        f"- 가중치 산출 경로 (`weights_source`): `{weights_source}`",
        f"- 기준 수 (`n`): {len(names)}",
        "",
        "## 1. 기준 가중치 및 OAT ±10% 민감도 분석",
        "",
        "| # | 기준 (Criterion) | 가중치 | 비율 (%) | OAT -10% 본인 가중치 | OAT +10% 본인 가중치 | 최대 타 기준 변동폭 | 순위 역전 |",
        "|---:|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for i, name in enumerate(names):
        wi = w_list[i] if i < len(w_list) else 0.0
        row = sens_by_idx.get(i)
        if row:
            w_min = float(row["minus_weights"][i])
            w_max = float(row["plus_weights"][i])
            max_sh = float(row["max_other_shift"])
            swapped = "예 (주의)" if row.get("rank_changed") else "안정"
            lines.append(
                f"| {i + 1} | {name} | {wi:.4f} | {100.0 * wi:.2f}% | "
                f"{100.0 * w_min:.2f}% | {100.0 * w_max:.2f}% | {100.0 * max_sh:.2f}%p | {swapped} |"
            )
        else:
            lines.append(f"| {i + 1} | {name} | {wi:.4f} | {100.0 * wi:.2f}% | - | - | - | - |")

    lines.extend(["", "## 2. 일관성 검증 (Saaty 1980; Alonso & Lamata 2006)", ""])
    lam_txt = f"{float(lambda_max):.6f}" if lambda_max is not None and math.isfinite(float(lambda_max)) else "N/A"
    ci_txt = f"{float(ci):.6f}" if ci is not None and math.isfinite(float(ci)) else "N/A"
    ri_txt = f"{float(ri):.4f}" if ri is not None and math.isfinite(float(ri)) else "N/A"
    cr_txt = f"{float(cr):.4f}" if cr is not None and math.isfinite(float(cr)) else "N/A"
    lines.extend(
        [
            f"- 최대 고유값 (lambda_max): `{lam_txt}`",
            f"- 일관성지수 (CI = (lambda_max - n)/(n - 1)): `{ci_txt}`",
            f"- 무작위지수 (RI): `{ri_txt}`",
            f"- 일관성비율 (CR = CI / RI): `{cr_txt}` (권장 ≤ 0.10)",
        ]
    )

    if hierarchy:
        lines.extend(["", "## 3. 계층형 AHP 요약", ""])
        cr_g = hierarchy.get("consistency_ratio_group")
        cr_l = hierarchy.get("consistency_ratio_local_max")
        if cr_g is not None:
            lines.append(f"- 그룹 간 CR: `{float(cr_g):.4f}`")
        if cr_l is not None:
            lines.append(f"- 그룹 내 최대 CR: `{float(cr_l):.4f}`")

    if matrix is not None and np is not None:
        mat = np.asarray(matrix, dtype=float)
        if mat.ndim == 2 and mat.shape == (len(names), len(names)) and len(names) > 0:
            lines.extend(["", "## 쌍대비교 행렬", ""])
            header = "| 기준 | " + " | ".join(names) + " |"
            sep = "|---|" + "|".join(["---:"] * len(names)) + "|"
            lines.append(header)
            lines.append(sep)
            for i, nm in enumerate(names):
                cells = " | ".join(f"{float(mat[i, j]):.4g}" for j in range(len(names)))
                lines.append(f"| {nm} | {cells} |")

    lines.extend(
        [
            "",
            "## 참고문헌 및 주의사항",
            "- Saaty, T. L. (1980). *The Analytic Hierarchy Process*. McGraw-Hill.",
            "- Alonso, J. A., & Lamata, M. T. (2006). *IJUFKS* 14(4), 445-459.",
            "- Chen, Y., Yu, J., & Khan, S. (2010). Spatial sensitivity analysis of multi-criteria weights in GIS-based land suitability evaluation. *Environmental Modelling & Software*, 25(12), 1582-1591.",
            "- AHP 가중치는 전문가 판단에 근거한 규범적 모형이며(Verhagen & Whitley 2012), 통계적 빈도/회귀 적합도가 아닙니다.",
        ]
    )
    if notes:
        for note in notes:
            lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)
