# -*- coding: utf-8 -*-
"""QGIS-free mathematical core for Ordinary Kriging, empirical variogram fitting, and LOOCV.

Grounded in:
- Matheron, G. (1963). Principles of geostatistics. Economic Geology, 58(8), 1246-1266.
- Cressie, N. (1985). Fitting variogram models by weighted least squares.
  Mathematical Geology, 17(5), 563-586.
- Cressie, N. (1993). Statistics for Spatial Data (Rev. ed.). Wiley.
- Webster, R., & Oliver, M. A. (2007). Geostatistics for Environmental Scientists (2nd ed.).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import numpy as np
except Exception:  # pragma: no cover - optional runtime guard
    np = None  # type: ignore


SUPPORTED_VARIOGRAM_MODELS = ("exponential", "spherical", "gaussian")


def _require_numpy():
    if np is None:
        raise RuntimeError("numpy is required for kriging_math")
    return np


def _normalize_model(model: str) -> str:
    m = str(model or "exponential").strip().lower()
    if m not in SUPPORTED_VARIOGRAM_MODELS:
        raise ValueError(f"Unsupported variogram model: {model!r}")
    return m


def _unit_variogram_shape(dist, *, model: str, rng: float):
    """Dimensionless unit-sill variogram shape phi(h; rng) in [0, 1]."""
    mod = _normalize_model(model)
    r = max(1e-12, float(rng))
    h = np.asarray(dist, dtype=float)
    pos = h > 0.0
    if mod == "exponential":
        out = np.zeros_like(h, dtype=float)
        out[pos] = 1.0 - np.exp(-h[pos] / r)
        return out
    if mod == "spherical":
        out = np.zeros_like(h, dtype=float)
        u = h[pos] / r
        inner = u < 1.0
        vals = np.ones_like(u, dtype=float)
        vals[inner] = 1.5 * u[inner] - 0.5 * (u[inner] ** 3)
        out[pos] = vals
        return out
    # gaussian
    out = np.zeros_like(h, dtype=float)
    out[pos] = 1.0 - np.exp(-((h[pos] / r) ** 2))
    return out


def semivariogram_value(
    dist,
    *,
    model: str = "exponential",
    nugget: float = 0.0,
    partial_sill: float = 1.0,
    rng: float = 1.0,
):
    """Evaluate isotropic semivariogram gamma(h) with gamma(0) = 0."""
    _require_numpy()
    h = np.asarray(dist, dtype=float)
    c0 = max(0.0, float(nugget))
    c1 = max(0.0, float(partial_sill))
    phi = _unit_variogram_shape(h, model=model, rng=rng)
    gamma = np.zeros_like(h, dtype=float)
    pos = h > 0.0
    gamma[pos] = c0 + c1 * phi[pos]
    return float(gamma) if np.ndim(dist) == 0 else gamma


def covariance_value(
    dist,
    *,
    model: str = "exponential",
    nugget: float = 0.0,
    partial_sill: float = 1.0,
    rng: float = 1.0,
    zero_tol: float = 0.0,
):
    """Evaluate stationary covariance C(h) = C(0) - gamma(h), with C(0) = nugget + partial_sill."""
    _require_numpy()
    h = np.asarray(dist, dtype=float)
    c0 = max(0.0, float(nugget))
    c1 = max(0.0, float(partial_sill))
    phi = _unit_variogram_shape(h, model=model, rng=rng)
    cov = c1 * (1.0 - phi)
    zero_mask = h <= max(0.0, float(zero_tol))
    cov = np.where(zero_mask, c0 + c1, cov)
    return float(cov) if np.ndim(dist) == 0 else cov


def exponential_cov(dist, *, partial_sill: float, rng: float):
    """Evaluate C(h) = partial_sill * exp(-h / range) matching kriging_lite convention."""
    _require_numpy()
    rng0 = float(max(1e-12, rng))
    return float(partial_sill) * np.exp(-np.asarray(dist, dtype=float) / rng0)


def build_ok_system(
    coords,
    *,
    partial_sill: float,
    rng: float,
    nugget: float = 0.0,
    model: str = "exponential",
):
    """Construct the (n+1) x (n+1) Ordinary Kriging saddle-point matrix A."""
    _require_numpy()
    pts = np.asarray(coords, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError("coords must have shape (n, 2)")
    n = int(pts.shape[0])
    dx = pts[:, 0][:, None] - pts[:, 0][None, :]
    dy = pts[:, 1][:, None] - pts[:, 1][None, :]
    dist = np.sqrt(dx * dx + dy * dy)
    # Off-diagonal collocated observations (i != j, h == 0) reflect independent
    # measurement errors with covariance lim_{h->0+} C(h) = partial_sill (Cressie 1993),
    # while only the diagonal i == j carries total sill C(0) = partial_sill + nugget.
    c0 = max(0.0, float(nugget))
    c1 = max(0.0, float(partial_sill))
    phi = _unit_variogram_shape(dist, model=model, rng=rng)
    C = c1 * (1.0 - phi)
    np.fill_diagonal(C, float(c1 + c0))

    A = np.empty((n + 1, n + 1), dtype=float)
    A[:n, :n] = C
    A[:n, n] = 1.0
    A[n, :n] = 1.0
    A[n, n] = 0.0
    return A


def invert_ok_system(
    A,
    *,
    partial_sill: float = 1.0,
    nugget: float = 0.0,
    cond_limit: float = 1e10,
):
    """Invert an Ordinary Kriging saddle-point matrix with exact diagonal equilibration.

    Unscaled ``[C 1; 1^T 0]`` has ``cond(A) ~ sill^2`` (``relief^4``), which
    falsely exceeds ``cond_limit`` on mountainous DEMs (e.g. 1,500 m relief)
    even when the covariance block ``C`` is well-conditioned. Similarity
    scaling ``S A S`` with ``S = diag(1/sqrt(s), ..., 1/sqrt(s), sqrt(s))``
    equilibrates the block to ``[C/s 1; 1^T 0]`` and recovers ``A^-1 = S A_tilde^-1 S``
    exactly.
    """
    _require_numpy()
    mat = np.asarray(A, dtype=float)
    n = int(mat.shape[0]) - 1
    if n <= 0:
        return None
    diag_scale = float(np.max(np.abs(np.diag(mat[:n, :n])))) if n > 0 else 0.0
    sill = float(max(0.0, partial_sill) + max(0.0, nugget))
    scale = max(sill, diag_scale, 1e-12)
    inv_sqrt = 1.0 / math.sqrt(scale)
    sqrt_s = math.sqrt(scale)
    s_vec = np.empty(n + 1, dtype=float)
    s_vec[:n] = inv_sqrt
    s_vec[n] = sqrt_s

    def _try_invert(raw_mat, limit: float):
        scaled = (s_vec[:, None] * raw_mat) * s_vec[None, :]
        cond = float(np.linalg.cond(scaled))
        if math.isfinite(cond) and cond <= float(limit):
            cand_scaled = np.linalg.inv(scaled)
            cand = (s_vec[:, None] * cand_scaled) * s_vec[None, :]
            if np.isfinite(cand).all():
                return cand
        return None

    try:
        cand = _try_invert(mat, float(cond_limit))
        if cand is not None:
            return cand
    except np.linalg.LinAlgError:
        cand = None

    eps = float(max(1e-8 * max(scale, 1e-12), 1e-10))
    mat_reg = mat.copy()
    mat_reg[:n, :n] += np.eye(n, dtype=float) * eps
    try:
        return _try_invert(mat_reg, 1e12)
    except np.linalg.LinAlgError:
        return None


def solve_ok(
    inv,
    coords,
    values,
    target_xy: Tuple[float, float],
    *,
    partial_sill: float,
    rng: float,
    nugget: float = 0.0,
    model: str = "exponential",
    exact_tol: float = 1e-9,
    roundoff_tol: Optional[float] = None,
    include_nugget_at_zero: Optional[bool] = None,
) -> Tuple[float, float]:
    """Solve Ordinary Kriging prediction and variance at one target location.

    When ``target_xy`` coincides with a single unique sample point (and
    ``include_nugget_at_zero`` is not False), ``C(0) = c0 + c1`` is used so
    Ordinary Kriging acts as an exact interpolator at isolated observations.
    When multiple collocated observations coincide with ``target_xy`` (or in
    LOOCV where the held-out observation has an independent nugget error),
    the nugget is excluded from the target covariance vector ``cvec``
    (Cressie 1993, Section 3.2.1), keeping the kriging variance strictly
    positive instead of turning negative/NaN.
    """
    _require_numpy()
    pts = np.asarray(coords, dtype=float)
    vals = np.asarray(values, dtype=float)
    n = int(pts.shape[0])
    x, y = float(target_xy[0]), float(target_xy[1])
    dx0 = pts[:, 0] - x
    dy0 = pts[:, 1] - y
    dist0 = np.sqrt(dx0 * dx0 + dy0 * dy0)

    c0 = max(0.0, float(nugget))
    c1 = max(0.0, float(partial_sill))
    total_sill = c0 + c1
    tol_exact = max(0.0, float(exact_tol))
    n_exact = int(np.count_nonzero(dist0 <= tol_exact))

    if include_nugget_at_zero is None:
        use_nugget_at_zero = (n_exact == 1)
    else:
        use_nugget_at_zero = bool(include_nugget_at_zero) and (n_exact <= 1)

    if use_nugget_at_zero:
        cvec = covariance_value(
            dist0,
            model=model,
            nugget=c0,
            partial_sill=c1,
            rng=rng,
            zero_tol=tol_exact,
        )
    else:
        # Target covariance with independent measurement error (no nugget jump at h=0).
        phi = _unit_variogram_shape(dist0, model=model, rng=rng)
        cvec = c1 * (1.0 - phi)

    rhs = np.empty(n + 1, dtype=float)
    rhs[:n] = cvec
    rhs[n] = 1.0
    sol = inv @ rhs
    w = sol[:n]
    mu = float(sol[n])

    tol = 1e-5 * max(total_sill, 1.0) if roundoff_tol is None else abs(float(roundoff_tol))
    zhat = float(np.dot(w, vals))
    vv = float(total_sill - float(np.dot(w, cvec)) - mu)
    if (not math.isfinite(zhat)) or (not math.isfinite(vv)) or vv < -tol:
        return math.nan, math.nan
    if vv < 0.0:
        vv = 0.0
    return zhat, vv


def empirical_semivariogram(
    coords,
    values,
    *,
    n_lags: int = 12,
    max_lag: Optional[float] = None,
    min_pairs: int = 5,
    max_samples: int = 1500,
) -> Dict[str, Any]:
    """Compute Matheron (1963) classical omnidirectional empirical semivariogram."""
    _require_numpy()
    pts = np.asarray(coords, dtype=float)
    vals = np.asarray(values, dtype=float)
    n = int(pts.shape[0])
    if n < 4 or vals.shape[0] != n or int(n_lags) < 2:
        return {
            "lag_centers": [],
            "semivariance": [],
            "pair_counts": [],
            "max_lag": 0.0,
            "n_pairs_used": 0,
        }

    # Deterministic stride keeps memory O(1500^2) on very dense point clouds.
    if n > int(max_samples):
        idx = np.linspace(0, n - 1, int(max_samples), dtype=int)
        pts = pts[idx]
        vals = vals[idx]
        n = int(pts.shape[0])

    i_idx, j_idx = np.triu_indices(n, k=1)
    dx = pts[i_idx, 0] - pts[j_idx, 0]
    dy = pts[i_idx, 1] - pts[j_idx, 1]
    h = np.sqrt(dx * dx + dy * dy)
    dz = vals[i_idx] - vals[j_idx]
    sq_half = 0.5 * (dz * dz)

    pos_mask = h > 0.0
    h = h[pos_mask]
    sq_half = sq_half[pos_mask]
    if h.size == 0:
        return {
            "lag_centers": [],
            "semivariance": [],
            "pair_counts": [],
            "max_lag": 0.0,
            "n_pairs_used": 0,
        }

    h_max_all = float(np.max(h))
    lag_limit = float(max_lag) if (max_lag is not None and float(max_lag) > 0.0) else 0.5 * h_max_all
    if lag_limit <= 0.0:
        lag_limit = h_max_all

    in_range = (h > 0.0) & (h <= lag_limit)
    h_sel = h[in_range]
    g_sel = sq_half[in_range]
    if h_sel.size == 0:
        return {
            "lag_centers": [],
            "semivariance": [],
            "pair_counts": [],
            "max_lag": lag_limit,
            "n_pairs_used": 0,
        }

    edges = np.linspace(0.0, lag_limit, int(n_lags) + 1)
    bin_idx = np.searchsorted(edges, h_sel, side="left") - 1
    bin_idx = np.clip(bin_idx, 0, int(n_lags) - 1)

    lag_centers: List[float] = []
    semivariances: List[float] = []
    counts: List[int] = []
    total_used = 0

    for k in range(int(n_lags)):
        m = bin_idx == k
        cnt = int(np.count_nonzero(m))
        if cnt < int(min_pairs):
            continue
        lag_centers.append(float(np.mean(h_sel[m])))
        semivariances.append(float(np.mean(g_sel[m])))
        counts.append(cnt)
        total_used += cnt

    return {
        "lag_centers": lag_centers,
        "semivariance": semivariances,
        "pair_counts": counts,
        "max_lag": float(lag_limit),
        "n_pairs_used": int(total_used),
    }


def _solve_2var_nnls_wls(phi, gamma_hat, weights):
    """Exact 2-variable non-negative weighted least squares for c0 >= 0, c1 >= 0."""
    # Evaluate all 4 active-set candidates: (unconstrained, c0=0, c1=0, (0,0)).
    w = weights
    y = gamma_hat
    x0 = np.ones_like(phi, dtype=float)
    x1 = phi

    candidates: List[Tuple[float, float]] = [(0.0, 0.0)]
    sw0 = float(np.sum(w * x0))
    if sw0 > 0.0:
        c0_only = max(0.0, float(np.sum(w * y) / sw0))
        candidates.append((c0_only, 0.0))

    sw1 = float(np.sum(w * x1 * x1))
    if sw1 > 0.0:
        c1_only = max(0.0, float(np.sum(w * x1 * y) / sw1))
        candidates.append((0.0, c1_only))

    a00 = sw0
    a01 = float(np.sum(w * x1))
    a11 = sw1
    b0 = float(np.sum(w * y))
    b1 = float(np.sum(w * x1 * y))
    det = a00 * a11 - a01 * a01
    if det > 1e-18 * max(1.0, abs(a00 * a11)):
        c0_u = (a11 * b0 - a01 * b1) / det
        c1_u = (-a01 * b0 + a00 * b1) / det
        if c0_u >= 0.0 and c1_u >= 0.0:
            candidates.append((float(c0_u), float(c1_u)))

    best_loss = math.inf
    best_pair = (0.0, 0.0)
    for c0, c1 in candidates:
        pred = c0 + c1 * phi
        diff = y - pred
        loss = float(np.sum(w * diff * diff))
        if loss < best_loss:
            best_loss = loss
            best_pair = (float(c0), float(c1))
    return best_pair[0], best_pair[1]


def _cressie_loss(gamma_hat, gamma_pred, counts, floor_var: float) -> float:
    denom = np.maximum(gamma_pred, floor_var)
    diff = gamma_hat - gamma_pred
    return float(np.sum(counts * (diff * diff) / (denom * denom)))


def fit_variogram_wls(
    coords,
    values,
    *,
    models: Sequence[str] = SUPPORTED_VARIOGRAM_MODELS,
    n_lags: int = 12,
    min_pairs: int = 5,
    max_lag: Optional[float] = None,
) -> Dict[str, Any]:
    """Fit parametric variogram via Cressie (1985) WLS with model selection."""
    _require_numpy()
    pts = np.asarray(coords, dtype=float)
    vals = np.asarray(values, dtype=float)
    sample_var = float(np.var(vals)) if vals.size > 1 else 0.0
    if not math.isfinite(sample_var) or sample_var <= 1e-15:
        return {
            "fitted": False,
            "reason": "degenerate_variance",
            "variogram_source": "heuristic_fallback",
        }

    emp = empirical_semivariogram(pts, vals, n_lags=n_lags, max_lag=max_lag, min_pairs=min_pairs)
    h = np.asarray(emp["lag_centers"], dtype=float)
    g_hat = np.asarray(emp["semivariance"], dtype=float)
    cnts = np.asarray(emp["pair_counts"], dtype=float)
    if h.size < 3:
        return {
            "fitted": False,
            "reason": "insufficient_variogram_bins",
            "variogram_source": "heuristic_fallback",
            "empirical": emp,
        }

    floor_var = max(1e-12, 1e-6 * sample_var)
    h_min = float(np.min(h))
    h_max = max(float(np.max(h)), h_min * 1.5)
    r_low = max(1e-6, 0.1 * h_min)
    r_high = max(r_low * 10.0, 2.5 * h_max)
    coarse_ranges = np.geomspace(r_low, r_high, 40)

    def _refine_cressie_direct(phi, c0_init: float, c1_init: float) -> Tuple[float, float, float]:
        """Directly minimize Cressie (1985) WLS loss over c0 >= 0, c1 >= 0.

        IRLS ignores the derivative of the 1/gamma(h)^2 denominator and
        systematically biases the fitted sill downward (up to ~9%). Starting
        from the IRLS point, adaptive coordinate + multiplicative search on
        the true objective guarantees <= IRLS loss and unbiased sills.
        """
        best_c0 = max(0.0, float(c0_init))
        best_c1 = max(0.0, float(c1_init))
        best_loss = _cressie_loss(g_hat, best_c0 + best_c1 * phi, cnts, floor_var)
        # First optimize overall scale factor s > 0 (since loss(s*c0, s*c1) is
        # often strictly lower at a slightly larger sill than IRLS returns).
        for step_scale in (0.25, 0.10, 0.04, 0.015, 0.005, 0.0015):
            improved = True
            iters = 0
            while improved and iters < 12:
                improved = False
                iters += 1
                # Joint scale move
                for mult in (1.0 + step_scale, max(0.0, 1.0 - step_scale)):
                    cand_c0 = best_c0 * mult
                    cand_c1 = best_c1 * mult
                    cand_loss = _cressie_loss(g_hat, cand_c0 + cand_c1 * phi, cnts, floor_var)
                    if cand_loss < best_loss - 1e-12:
                        best_c0, best_c1, best_loss = cand_c0, cand_c1, cand_loss
                        improved = True
                # Individual c0, c1 moves
                dc0 = max(best_c0, sample_var * 0.05) * step_scale
                for cand_c0 in (best_c0 + dc0, max(0.0, best_c0 - dc0)):
                    cand_loss = _cressie_loss(g_hat, cand_c0 + best_c1 * phi, cnts, floor_var)
                    if cand_loss < best_loss - 1e-12:
                        best_c0, best_loss = cand_c0, cand_loss
                        improved = True
                dc1 = max(best_c1, sample_var * 0.05) * step_scale
                for cand_c1 in (best_c1 + dc1, max(0.0, best_c1 - dc1)):
                    cand_loss = _cressie_loss(g_hat, best_c0 + cand_c1 * phi, cnts, floor_var)
                    if cand_loss < best_loss - 1e-12:
                        best_c1, best_loss = cand_c1, cand_loss
                        improved = True
        return best_loss, best_c0, best_c1

    def fit_at_range(mod: str, rng_val: float, *, refine: bool = False) -> Tuple[float, float, float]:
        phi = _unit_variogram_shape(h, model=mod, rng=rng_val)
        w = cnts / (np.maximum(g_hat, floor_var) ** 2)
        c0, c1 = _solve_2var_nnls_wls(phi, g_hat, w)
        for _ in range(3):
            g_pred = c0 + c1 * phi
            w = cnts / (np.maximum(g_pred, floor_var) ** 2)
            c0, c1 = _solve_2var_nnls_wls(phi, g_hat, w)
        if refine:
            return _refine_cressie_direct(phi, c0, c1)
        g_pred = c0 + c1 * phi
        loss = _cressie_loss(g_hat, g_pred, cnts, floor_var)
        return loss, c0, c1

    best: Optional[Dict[str, Any]] = None
    for raw_mod in models:
        mod = _normalize_model(raw_mod)
        best_r = float(coarse_ranges[0])
        best_tuple = (math.inf, 0.0, sample_var)
        for r_cand in coarse_ranges:
            res = fit_at_range(mod, float(r_cand), refine=False)
            if res[0] < best_tuple[0]:
                best_tuple = res
                best_r = float(r_cand)

        # Local multiplicative refinement around coarse optimum with direct
        # minimization of the true Cressie (1985) objective.
        lo = max(1e-6, best_r * 0.55)
        hi = best_r * 1.65
        best_tuple = fit_at_range(mod, best_r, refine=True)
        for r_cand in np.geomspace(lo, hi, 20):
            res = fit_at_range(mod, float(r_cand), refine=True)
            if res[0] < best_tuple[0]:
                best_tuple = res
                best_r = float(r_cand)

        loss, c0, c1 = best_tuple
        if c0 + c1 <= 0.0:
            continue
        if best is None or loss < best["wls_loss"]:
            best = {
                "fitted": True,
                "model": mod,
                "nugget": float(c0),
                "partial_sill": float(c1),
                "range": float(best_r),
                "wls_loss": float(loss),
                "variogram_source": "empirical_wls",
                "empirical": emp,
            }

    if best is None:
        return {
            "fitted": False,
            "reason": "no_valid_sill",
            "variogram_source": "heuristic_fallback",
            "empirical": emp,
        }
    return best


def loocv_ordinary_kriging(
    coords,
    values,
    *,
    model: str = "exponential",
    nugget: float = 0.0,
    partial_sill: float = 1.0,
    rng: float = 1.0,
    neighbors: int = 16,
    max_eval: int = 400,
) -> Dict[str, Any]:
    """Compute Leave-One-Out Cross-Validation diagnostics (RMSE, MAE, ME, MSDR)."""
    _require_numpy()
    pts = np.asarray(coords, dtype=float)
    vals = np.asarray(values, dtype=float)
    n = int(pts.shape[0])
    if n < 4 or vals.shape[0] != n:
        return {
            "n_evaluated": 0,
            "rmse": None,
            "mae": None,
            "me": None,
            "msdr": None,
        }

    k_nei = min(max(3, int(neighbors)), n - 1)
    if n <= int(max_eval):
        eval_indices = np.arange(n, dtype=int)
    else:
        eval_indices = np.linspace(0, n - 1, int(max_eval), dtype=int)

    errors: List[float] = []
    std_sq_errors: List[float] = []

    for i in eval_indices:
        dx = pts[:, 0] - pts[i, 0]
        dy = pts[:, 1] - pts[i, 1]
        d2 = dx * dx + dy * dy
        d2[i] = math.inf
        nei_idx = np.argpartition(d2, k_nei)[:k_nei]
        A = build_ok_system(
            pts[nei_idx],
            partial_sill=partial_sill,
            rng=rng,
            nugget=nugget,
            model=model,
        )
        inv = invert_ok_system(A, partial_sill=partial_sill, nugget=nugget)
        if inv is None:
            continue
        zhat, vv = solve_ok(
            inv,
            pts[nei_idx],
            vals[nei_idx],
            (float(pts[i, 0]), float(pts[i, 1])),
            partial_sill=partial_sill,
            rng=rng,
            nugget=nugget,
            model=model,
            # The held-out observation has an independent measurement error
            # (nugget), so even if a collocated neighbor sits at distance 0,
            # its cross-covariance is partial_sill (not partial_sill + nugget),
            # yielding true LOOCV variance 2*nugget > 0 instead of 0.0.
            include_nugget_at_zero=False,
        )
        if not (math.isfinite(zhat) and math.isfinite(vv)):
            continue
        err = float(zhat - vals[i])
        errors.append(err)
        if vv > 1e-12:
            std_sq_errors.append((err * err) / float(vv))

    if not errors:
        return {
            "n_evaluated": 0,
            "rmse": None,
            "mae": None,
            "me": None,
            "msdr": None,
        }

    err_arr = np.asarray(errors, dtype=float)
    return {
        "n_evaluated": int(err_arr.size),
        "rmse": float(np.sqrt(np.mean(err_arr * err_arr))),
        "mae": float(np.mean(np.abs(err_arr))),
        "me": float(np.mean(err_arr)),
        "msdr": float(np.mean(std_sq_errors)) if std_sq_errors else None,
    }
