# -*- coding: utf-8 -*-
"""QGIS-free movement-cost models for the least-cost surface tool.

Each model maps an edge (horizontal distance + elevation change) to a
traversal cost in seconds or, for Pandolf, joules.  They are pure functions
of geometry and parameters with no QGIS dependency, so they live here where
the published ones can be regression-tested against their published values.

Published formulae implemented here:
  - Tobler (1993) hiking function
  - Naismith (1892) rule
  - Pandolf et al. (1977) load-carriage energy equation
  - Herzog slope-cost model: the metabolic branch is a 6th-order
    polynomial, the wheeled branch a critical-slope form (critical slope
    as a PERCENT grade, default 12 %); both follow Cuckovic's Movement
    Analysis implementation

NOT a published formula:
  - MODEL_CONOLLY_LAKE is a PLUGIN-DEFINED relative-slope penalty, written
    for this plugin and informed by the discussion of relative slope cost in
    Conolly & Lake (2006).  Conolly & Lake do not publish this equation.  Its
    magnitude is set entirely by ``conolly_ref_slope_deg`` (the penalty
    scales inversely with that reference), so the reference slope must be
    reported alongside any result produced with this model.  See the branch
    comment in :func:`edge_cost` for the calibration note.

Pandolf caveat: Pandolf is an ENERGY model.  Its ``cost_mode="time_s"``
output is isotropic ``distance / speed`` with NO slope response whatsoever,
so a Pandolf time surface degenerates to straight-line distance and its
least-cost path is the shortest path.  Only the energy mode reacts to grade.
Use Tobler or Naismith when a slope-responsive TIME surface is wanted.
"""

from __future__ import annotations

import math


MODEL_TOBLER = "tobler_time"
MODEL_NAISMITH = "naismith_time"
MODEL_HERZOG_METABOLIC = "herzog_metabolic_time"
MODEL_CONOLLY_LAKE = "conolly_lake_time"
MODEL_HERZOG_WHEELED = "herzog_wheeled_time"
MODEL_PANDOLF = "pandolf_energy"


def tobler_speed_mps(slope, base_speed_kmh, slope_factor, slope_offset, min_speed_mps):
    # Tobler (1993): W = a * exp(-b * abs(slope + c))  [km/h]
    speed_kmh = float(base_speed_kmh) * math.exp(
        -float(slope_factor) * abs(float(slope) + float(slope_offset))
    )
    return max(float(min_speed_mps), speed_kmh * 1000.0 / 3600.0)


def naismith_time_s(horizontal_m, dz_m, horizontal_kmh, ascent_m_per_h):
    # Classic Naismith (1892): time = distance / speed + ascent / ascent_rate
    horizontal_kmh = max(0.0001, float(horizontal_kmh))
    ascent_m_per_h = max(0.0001, float(ascent_m_per_h))
    time_h = (float(horizontal_m) / (horizontal_kmh * 1000.0)) + (
        max(0.0, float(dz_m)) / ascent_m_per_h
    )
    return time_h * 3600.0


WHEELED_CRITICAL_SLOPE_PCT_DEFAULT = 12.0


def wheeled_critical_slope_percent(model_params):
    """Critical slope of the Herzog wheeled-vehicle function, in PERCENT grade.

    Herzog (2013) and the formula in Cuckovic's Movement Analysis code
    (``1 / (1 + (s*100 / critical_slope)**2)``, s = tan) both take the critical
    slope as a percent grade, default 12 %: at that grade the cost is twice the
    flat cost. This plugin used to read the number as DEGREES (12 deg = 21.3 %),
    which made carts about half as slope-averse as the cited model.

    ``wheeled_critical_slope_pct`` is the parameter. The legacy key
    ``wheeled_critical_slope_deg`` is still honoured for callers that have not
    moved yet: it is converted with tan(), so such a caller keeps its old
    numbers until it switches to the percent key.
    """
    params = model_params or {}
    pct = params.get("wheeled_critical_slope_pct")
    if pct is None and params.get("wheeled_critical_slope_deg") is not None:
        deg = max(1.0, min(89.0, float(params.get("wheeled_critical_slope_deg"))))
        pct = math.tan(math.radians(deg)) * 100.0
    if pct is None:
        pct = WHEELED_CRITICAL_SLOPE_PCT_DEFAULT
    return max(0.1, float(pct))


PEDESTRIAN_MAX_SLOPE_DEG_DEFAULT = 70.0


def _pedestrian_cliff_exceeded(horiz_m: float, dz_m: float, model_params: dict) -> bool:
    """Return True if slope exceeds the walkable pedestrian cliff barrier.

    Without a cliff barrier and/or 3D vertical penalty, models clamped to a
    ``0.05 m/s`` floor charge the same flat 200 s per 10 m horizontal cell
    whether ``dz`` is 15 m or a 500 m sheer vertical cliff.
    """
    raw = (model_params or {}).get("max_walkable_slope_deg", PEDESTRIAN_MAX_SLOPE_DEG_DEFAULT)
    if raw is None:
        return False
    try:
        max_deg = float(raw)
    except (TypeError, ValueError):
        return False
    if (not math.isfinite(max_deg)) or max_deg >= 90.0:
        return False
    max_deg = max(1.0, max_deg)
    slope_deg = math.degrees(math.atan2(abs(float(dz_m)), float(horiz_m)))
    return slope_deg > max_deg + 1e-9


def edge_cost(model_key, horiz_m, dz_m, model_params, *, cost_mode="time_s"):
    if horiz_m <= 0:
        return 0.0
    params = model_params or {}

    if model_key == MODEL_TOBLER:
        if _pedestrian_cliff_exceeded(horiz_m, dz_m, params):
            return math.inf
        slope = dz_m / horiz_m if horiz_m > 0 else 0.0
        min_v = float(params.get("tobler_min_speed_mps", 0.05))
        raw_kmh = float(params.get("tobler_base_kmh", 6.0)) * math.exp(
            -float(params.get("tobler_slope_factor", 3.5))
            * abs(float(slope) + float(params.get("tobler_slope_offset", 0.05)))
        )
        raw_mps = raw_kmh * 1000.0 / 3600.0
        if raw_mps < min_v:
            # Beyond the speed floor, charge 3D surface length so taller cliffs
            # always cost strictly more than lower slopes instead of saturating.
            return math.hypot(float(horiz_m), float(dz_m)) / max(1e-6, min_v)
        return float(horiz_m) / raw_mps
    if model_key == MODEL_NAISMITH:
        if _pedestrian_cliff_exceeded(horiz_m, dz_m, params):
            return math.inf
        return naismith_time_s(
            horiz_m,
            dz_m,
            params.get("naismith_horizontal_kmh", 5.0),
            params.get("naismith_ascent_m_per_h", 600.0),
        )

    if model_key == MODEL_PANDOLF:
        # Pandolf et al. (1977) load carriage equation (energy-based).
        #
        # M(W) = 1.5W + 2.0(W+L)(L/W)^2 + η(W+L)(1.5V^2 + 0.35VG)
        # where:
        #   W: body weight (kg)
        #   L: load weight (kg)
        #   V: speed (m/s)
        #   G: grade (%)  (signed)
        #   η: terrain factor (dimensionless)
        #
        # Edge energy (J) = M * (distance / V)
        # Edge time (s)   = distance / V
        #
        # WARNING - Pandolf is an ENERGY model; its TIME output ignores slope.
        W = max(1.0, float(params.get("pandolf_body_kg", 70.0)))
        L = max(0.0, float(params.get("pandolf_load_kg", 0.0)))
        eta = max(0.1, float(params.get("pandolf_terrain_factor", 1.0)))
        V = max(0.05, float(params.get("pandolf_speed_mps", 5.0 * 1000.0 / 3600.0)))

        if cost_mode == "time_s":
            # Isotropic by design: distance / constant speed.
            return float(horiz_m) / V

        if _pedestrian_cliff_exceeded(horiz_m, dz_m, params):
            return math.inf

        grade_percent = (float(dz_m) / float(horiz_m)) * 100.0
        load_ratio = (L / W) if W > 0 else 0.0
        standing_loaded_w = (1.5 * W) + (2.0 * (W + L) * (load_ratio**2))
        M = standing_loaded_w + (
            eta * (W + L) * (1.5 * V * V + 0.35 * V * grade_percent)
        )
        # Pandolf (1977) was calibrated for level and uphill walking only.
        # Floor at the LOADED standing metabolic rate (1.5*W + 2.0*(W+L)*(L/W)^2),
        # never merely 1.5*W, so descending with a pack never costs less than
        # standing still holding that same pack.
        M = max(standing_loaded_w, float(M))
        dist_m = math.hypot(float(horiz_m), float(dz_m)) if bool(params.get("pandolf_3d_distance", False)) else float(horiz_m)
        return (float(M) * dist_m) / V

    min_speed_mps = float(params.get("min_speed_mps", 0.05))

    if model_key == MODEL_HERZOG_METABOLIC:
        if _pedestrian_cliff_exceeded(horiz_m, dz_m, params):
            return math.inf
        # Signed-slope 6th-degree metabolic cost polynomial (Herzog 2013 fit to Minetti et al. 2002):
        #   C(s) [J / (kg * m)] = 1337.8 s^6 + 278.19 s^5 - 517.39 s^4 - 78.199 s^3
        #                         + 93.419 s^2 + 19.825 s + 1.64
        # In energy mode ("energy_j"), return true metabolic energy in Joules:
        #   E(J) = W_kg * C(s) * horiz_m
        # (no artificial speed conversion or 13.35 km/h downhill sprint artifact).
        slope_s = float(dz_m) / float(horiz_m) if horiz_m > 0 else 0.0
        den = (
            1337.8 * slope_s**6
            + 278.19 * slope_s**5
            - 517.39 * slope_s**4
            - 78.199 * slope_s**3
            + 93.419 * slope_s**2
            + 19.825 * slope_s
            + 1.64
        )
        den_safe = max(1e-9, float(den))
        if cost_mode == "energy_j":
            body_kg = max(1.0, float(params.get("herzog_body_kg", 70.0)))
            return body_kg * den_safe * float(horiz_m)

        # Legacy relative-time proxy (when callers explicitly request cost_mode="time_s").
        rel = 1.0 / den_safe
        rel0 = 1.0 / 1.64
        rel_norm = rel / rel0
        base_mps = max(min_speed_mps, float(params.get("herzog_base_kmh", 5.0)) * 1000.0 / 3600.0)
        raw_speed = base_mps * rel_norm
        if raw_speed < min_speed_mps:
            return math.hypot(float(horiz_m), float(dz_m)) / max(1e-6, min_speed_mps)
        return float(horiz_m) / raw_speed

    # Isotropic slope-based models (use absolute slope magnitude)
    slope_abs = abs(float(dz_m)) / float(horiz_m) if horiz_m > 0 else 0.0  # tan(theta)

    if model_key == MODEL_CONOLLY_LAKE:
        if _pedestrian_cliff_exceeded(horiz_m, dz_m, params):
            return math.inf
        ref_deg = max(0.1, float(params.get("conolly_ref_slope_deg", 5.0)))
        ref_tan = math.tan(math.radians(ref_deg))
        factor = max(1.0, slope_abs / max(1e-9, ref_tan))
        base_mps = max(min_speed_mps, float(params.get("conolly_base_kmh", 5.0)) * 1000.0 / 3600.0)
        return (float(horiz_m) / base_mps) * factor

    if model_key == MODEL_HERZOG_WHEELED:
        # Optional "hard" slope limit for wheeled traffic (beyond this, effectively impassable).
        max_deg = float(params.get("wheeled_max_slope_deg", 45.0))
        max_deg = max(1.0, min(89.0, max_deg))
        slope_deg = math.degrees(math.atan(slope_abs))
        if slope_deg > max_deg + 1e-9:
            return math.inf

        critical_percent = wheeled_critical_slope_percent(params)
        slope_percent = slope_abs * 100.0
        speed_factor = 1.0 / (1.0 + (slope_percent / max(1e-9, critical_percent)) ** 2)
        base_mps = max(min_speed_mps, float(params.get("wheeled_base_kmh", 4.0)) * 1000.0 / 3600.0)
        speed_mps = max(min_speed_mps, base_mps * speed_factor)
        return float(horiz_m) / speed_mps

    # Fallback
    return naismith_time_s(
        horiz_m,
        dz_m,
        params.get("naismith_horizontal_kmh", 5.0),
        params.get("naismith_ascent_m_per_h", 600.0),
    )


def isochrone_levels_minutes(max_minutes):
    """Generate isochrone levels (minutes) with coarse spacing as time increases.

    - Up to 60 min: every 15 min
    - 60~180 min: every 30 min
    - 180+ min: every 60 min
    """
    try:
        max_minutes = float(max_minutes)
    except Exception:
        return []
    if not math.isfinite(max_minutes) or max_minutes <= 0:
        return []

    levels = []

    for v in (15, 30, 45, 60):
        if v <= max_minutes + 1e-6:
            levels.append(float(v))

    v = 90
    while v <= 180 and v <= max_minutes + 1e-6:
        levels.append(float(v))
        v += 30

    v = 240
    # Safety cap to avoid producing an excessive number of contours on huge rasters.
    max_levels = 60
    while v <= max_minutes + 1e-6 and len(levels) < max_levels:
        levels.append(float(v))
        v += 60

    # Ensure sorted unique values
    uniq = []
    for t in sorted(set(levels)):
        if t > 0:
            uniq.append(t)
    return uniq


def isoenergy_levels_kcal(max_kcal):
    """Generate iso-energy levels (kcal) with coarser spacing as energy increases."""
    try:
        max_kcal = float(max_kcal)
    except Exception:
        return []
    if not math.isfinite(max_kcal) or max_kcal <= 0:
        return []

    levels = []

    # Up to 600 kcal: 50-kcal steps
    step = 50.0
    v = step
    while v <= min(600.0, max_kcal + 1e-6):
        levels.append(float(v))
        v += step

    # 600~2000 kcal: 200-kcal steps
    v = 800.0
    while v <= min(2000.0, max_kcal + 1e-6):
        levels.append(float(v))
        v += 200.0

    # 2000+ kcal: 500-kcal steps (cap count)
    v = 2500.0
    max_levels = 80
    while v <= max_kcal + 1e-6 and len(levels) < max_levels:
        levels.append(float(v))
        v += 500.0

    uniq = []
    for t in sorted(set(levels)):
        if t > 0:
            uniq.append(t)
    return uniq
