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


def _is_effectively_constant(col: "np.ndarray") -> bool:
    """True when column variance is zero within float64 relative rounding."""
    if col.size < 2:
        return True
    mean = float(np.mean(col))
    if not math.isfinite(mean):
        return True
    centered = col - mean
    ss = float(np.sum(centered * centered))
    if not math.isfinite(ss):
        return True
    scale = max(1.0, abs(mean))
    # Relative threshold rejects constant shifted arrays such as 512345.67
    # whose float64 cancellation noise otherwise produces fake r = -1.0.
    return ss <= (1e-12 * scale) ** 2 * float(col.size)


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

    means = np.mean(X, axis=0, keepdims=True)
    Xc = X - means
    ss = np.sum(Xc * Xc, axis=0)
    scales = np.maximum(1.0, np.abs(means.ravel()))
    non_const = ss > ((1e-12 * scales) ** 2) * float(n)
    cov_num = np.einsum("ij,ik->jk", Xc, Xc)
    denom = np.sqrt(np.outer(ss, ss))
    corr = np.full((k, k), np.nan, dtype=float)
    valid = (denom > 0.0) & np.outer(non_const, non_const)
    corr[valid] = np.clip(cov_num[valid] / denom[valid], -1.0, 1.0)
    for j in range(k):
        if non_const[j]:
            corr[j, j] = 1.0
    return corr


def compute_vif(
    matrix,
    *,
    min_extra_obs: int = 0,
    constant_value: float = math.inf,
) -> List[float]:
    """Variance Inflation Factor per column: VIF_j = 1 / (1 - R_j^2) from OLS with intercept.

    Columns are z-standardized prior to OLS regression so mixed-scale
    covariates (e.g. curvature ~1e-3 alongside flow accumulation ~1e8) do not
    trigger ``lstsq`` singular-value truncation and mask true collinearity.
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
        return [float(constant_value)] if _is_effectively_constant(X[:, 0]) else [1.0]

    # Pre-standardize all non-constant columns to zero mean and unit L2 norm.
    is_const = [_is_effectively_constant(X[:, j]) for j in range(k)]
    Z_std = np.zeros_like(X, dtype=float)
    for j in range(k):
        if not is_const[j]:
            col = X[:, j] - float(np.mean(X[:, j]))
            norm = float(np.linalg.norm(col))
            if norm > 0.0 and math.isfinite(norm):
                Z_std[:, j] = col / norm
            else:
                is_const[j] = True

    vifs: List[float] = []
    for j in range(k):
        if is_const[j]:
            vifs.append(float(constant_value))
            continue
        other_idx = [m for m in range(k) if m != j and not is_const[m]]
        if not other_idx:
            vifs.append(1.0)
            continue
        y = Z_std[:, j]
        # Columns are already centered, so intercept is identically 0 and SST = 1.0.
        X_other = Z_std[:, other_idx]
        beta, *_ = np.linalg.lstsq(X_other, y, rcond=None)
        y_hat = X_other @ beta
        if not np.all(np.isfinite(y_hat)):
            vifs.append(math.nan)
            continue
        resid = y - y_hat
        sse = float(np.sum(resid * resid))
        r2 = max(0.0, min(1.0, 1.0 - sse))
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
    # Regression of x on (1, cos(theta), sin(theta)) uses 3 parameters; at n == 3
    # residual degrees of freedom is 0 so R^2 is identically 1.0 even for noise.
    if n_valid < 4:
        return {
            "r2": math.nan,
            "r": math.nan,
            "r2_adj": math.nan,
            "p_value": math.nan,
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
            "r2_adj": math.nan,
            "p_value": math.nan,
            "n_valid": n_valid,
            "n_flat_excluded": n_flat_excluded,
        }

    if math.isnan(r_xc) or math.isnan(r_xs) or math.isnan(r_cs) or (1.0 - r_cs * r_cs) <= 1e-12:
        cands = [v * v for v in (r_xc, r_xs) if math.isfinite(v)]
        r2 = max(0.0, min(1.0, max(cands))) if cands else math.nan
    else:
        num = (r_xc * r_xc) + (r_xs * r_xs) - 2.0 * r_xc * r_xs * r_cs
        den = 1.0 - r_cs * r_cs
        r2 = max(0.0, min(1.0, float(num / den)))

    r = math.sqrt(r2) if math.isfinite(r2) else math.nan
    # Adjusted R^2 and exact F(2, n-3) survival p-value = (1 - R^2)^((n-3)/2).
    if math.isfinite(r2):
        r2_adj = 1.0 - (1.0 - r2) * float(n_valid - 1) / float(n_valid - 3)
        p_val = float(max(0.0, 1.0 - r2) ** (0.5 * float(n_valid - 3)))
    else:
        r2_adj = math.nan
        p_val = math.nan
    return {
        "r2": float(r2) if math.isfinite(r2) else math.nan,
        "r": float(r) if math.isfinite(r) else math.nan,
        "r2_adj": float(r2_adj) if math.isfinite(r2_adj) else math.nan,
        "p_value": float(p_val) if math.isfinite(p_val) else math.nan,
        "n_valid": n_valid,
        "n_flat_excluded": n_flat_excluded,
    }
