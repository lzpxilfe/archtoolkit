# -*- coding: utf-8 -*-
"""QGIS-free statistical helpers for Covariate Report (VIF, Pearson, Spearman, Circular-Linear R^2).

References:
- O'Brien, R. M. (2007). A caution regarding rules of thumb for variance inflation
  factors. Quality & Quantity, 41(5), 673-690.
- Spearman, C. (1904). The proof and measurement of association between two things.
  American Journal of Psychology, 15(1), 72-101.
- Mardia, K. V. (1976). Linear-circular correlation coefficients and rhythmometry.
  Biometrika, 63(2), 403-405.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None  # type: ignore


def _require_numpy():
    if np is None:
        raise RuntimeError("numpy is required for covariate_stats")
    return np


def compute_pearson_matrix(matrix) -> "np.ndarray":
    """Compute column-wise Pearson correlation matrix via centered cross-products."""
    _require_numpy()
    X = np.asarray(matrix, dtype=float)
    if X.ndim != 2:
        raise ValueError("matrix must be 2-dimensional")
    n, k = X.shape
    if k == 0:
        return np.empty((0, 0), dtype=float)
    if n < 2:
        return np.full((k, k), np.nan, dtype=float)

    Xc = X - np.mean(X, axis=0, keepdims=True)
    ss = np.sum(Xc * Xc, axis=0)
    cov_num = np.einsum("ij,ik->jk", Xc, Xc)
    denom = np.sqrt(np.outer(ss, ss))
    corr = np.full((k, k), np.nan, dtype=float)
    valid = denom > 0.0
    corr[valid] = np.clip(cov_num[valid] / denom[valid], -1.0, 1.0)
    for j in range(k):
        if ss[j] > 0.0:
            corr[j, j] = 1.0
    return corr


def compute_vif(
    matrix,
    *,
    min_extra_obs: int = 0,
    constant_value: float = math.inf,
) -> List[float]:
    """Variance Inflation Factor per column: VIF_j = 1 / (1 - R_j^2) from OLS with intercept.

    When ``min_extra_obs > 0`` (e.g. ``3`` -> require ``n > k + 2``), underdetermined
    sample matrices return ``nan`` instead of saturated collinearity numbers.
    """
    _require_numpy()
    X = np.asarray(matrix, dtype=float)
    if X.ndim != 2:
        raise ValueError("matrix must be 2-dimensional")
    n, k = X.shape
    if k == 0:
        return []
    if int(min_extra_obs) > 0 and (k < 2 or n < k + int(min_extra_obs)):
        return [math.nan] * k
    if k == 1:
        sst0 = float(np.sum((X[:, 0] - np.mean(X[:, 0])) ** 2)) if n > 1 else 0.0
        return [1.0] if sst0 > 1e-18 else [float(constant_value)]

    ones = np.ones(n, dtype=float)
    vifs: List[float] = []
    for j in range(k):
        y = X[:, j]
        if float(np.std(y)) < 1e-12:
            vifs.append(float(constant_value))
            continue
        sst = float(np.sum((y - np.mean(y)) ** 2))
        if sst <= 1e-18:
            vifs.append(float(constant_value))
            continue
        X_other = np.delete(X, j, axis=1)
        Z = np.column_stack([ones, X_other])
        beta, *_ = np.linalg.lstsq(Z, y, rcond=None)
        y_hat = np.sum(Z * beta[None, :], axis=1)
        if not np.all(np.isfinite(y_hat)):
            vifs.append(math.nan)
            continue
        resid = y - y_hat
        sse = float(np.sum(resid * resid))
        r2 = max(0.0, min(1.0, 1.0 - sse / sst))
        if (1.0 - r2) <= 1e-12:
            vifs.append(math.inf)
        else:
            vifs.append(float(1.0 / (1.0 - r2)))
    return vifs


def rankdata_average(vec) -> "np.ndarray":
    """Assign 1-based average ranks with tie averaging (no scipy dependency)."""
    _require_numpy()
    a = np.asarray(vec, dtype=float).ravel()
    n = int(a.size)
    if n == 0:
        return np.empty(0, dtype=float)
    order = np.argsort(a, kind="mergesort")
    s = a[order]
    ranks = np.empty(n, dtype=float)
    i = 0
    while i < n:
        j = i + 1
        while j < n and s[j] == s[i]:
            j += 1
        avg_rank = 0.5 * (float(i + 1) + float(j))
        for p in range(i, j):
            ranks[order[p]] = avg_rank
        i = j
    return ranks


def compute_spearman_matrix(matrix) -> "np.ndarray":
    """Compute column-wise Spearman rank correlation matrix using average-tie ranks."""
    _require_numpy()
    X = np.asarray(matrix, dtype=float)
    if X.ndim != 2:
        raise ValueError("matrix must be 2-dimensional")
    n, k = X.shape
    if k == 0:
        return np.empty((0, 0), dtype=float)
    ranked = np.empty_like(X, dtype=float)
    for j in range(k):
        ranked[:, j] = rankdata_average(X[:, j])
    return compute_pearson_matrix(ranked)


def _pair_pearson(a: "np.ndarray", b: "np.ndarray") -> float:
    ac = a - np.mean(a)
    bc = b - np.mean(b)
    sa = float(np.sum(ac * ac))
    sb = float(np.sum(bc * bc))
    if sa <= 1e-18 or sb <= 1e-18:
        return math.nan
    return max(-1.0, min(1.0, float(np.sum(ac * bc)) / math.sqrt(sa * sb)))


def circular_linear_r2(
    angles_deg,
    linear_vals,
    *,
    flat_value: float = -1.0,
) -> Dict[str, Any]:
    """Compute Mardia (1976) circular-linear squared correlation R^2 in [0, 1].

    Excludes NaN/Inf pairs and flat-aspect sentinel values (`angles < 0` or `== flat_value`).
    """
    _require_numpy()
    ang = np.asarray(angles_deg, dtype=float).ravel()
    lin = np.asarray(linear_vals, dtype=float).ravel()
    if ang.size != lin.size:
        raise ValueError("angles_deg and linear_vals must have equal length")

    finite_mask = np.isfinite(ang) & np.isfinite(lin)
    flat_mask = finite_mask & ((ang < 0.0) | np.isclose(ang, float(flat_value), atol=1e-9))
    valid_mask = finite_mask & (~flat_mask)

    n_valid = int(np.count_nonzero(valid_mask))
    n_flat_excluded = int(np.count_nonzero(flat_mask))
    if n_valid < 3:
        return {
            "r2": math.nan,
            "r": math.nan,
            "n_valid": n_valid,
            "n_flat_excluded": n_flat_excluded,
        }

    theta = np.deg2rad(ang[valid_mask])
    x = lin[valid_mask]
    c = np.cos(theta)
    s = np.sin(theta)

    r_xc = _pair_pearson(x, c)
    r_xs = _pair_pearson(x, s)
    r_cs = _pair_pearson(c, s)

    if math.isnan(r_xc) and math.isnan(r_xs):
        return {
            "r2": math.nan,
            "r": math.nan,
            "n_valid": n_valid,
            "n_flat_excluded": n_flat_excluded,
        }

    if math.isnan(r_xc) or math.isnan(r_xs) or math.isnan(r_cs) or (1.0 - r_cs * r_cs) <= 1e-12:
        # Degenerate circular component (e.g. collinear sin/cos along two opposite angles):
        # fall back to the non-degenerate univariate correlation.
        cands = [v * v for v in (r_xc, r_xs) if math.isfinite(v)]
        r2 = max(0.0, min(1.0, max(cands))) if cands else math.nan
    else:
        num = (r_xc * r_xc) + (r_xs * r_xs) - 2.0 * r_xc * r_xs * r_cs
        den = 1.0 - r_cs * r_cs
        r2 = max(0.0, min(1.0, float(num / den)))

    r = math.sqrt(r2) if math.isfinite(r2) else math.nan
    return {
        "r2": float(r2) if math.isfinite(r2) else math.nan,
        "r": float(r) if math.isfinite(r) else math.nan,
        "n_valid": n_valid,
        "n_flat_excluded": n_flat_excluded,
    }
