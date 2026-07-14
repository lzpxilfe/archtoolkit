# -*- coding: utf-8 -*-
"""QGIS-free movement-cost models for the least-cost surface tool.

Each model maps an edge (horizontal distance + elevation change) to a
traversal cost in seconds or, for Pandolf, joules.  The formulae (Tobler
1993, Naismith 1892, Pandolf et al. 1977, Herzog, Conolly & Lake) are pure
functions of geometry and parameters with no QGIS dependency, so they live
here where they can be regression-tested against published values.
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


def edge_cost(model_key, horiz_m, dz_m, model_params, *, cost_mode="time_s"):
    if horiz_m <= 0:
        return 0.0

    if model_key == MODEL_TOBLER:
        slope = dz_m / horiz_m if horiz_m > 0 else 0.0
        return horiz_m / tobler_speed_mps(
            slope,
            model_params.get("tobler_base_kmh", 6.0),
            model_params.get("tobler_slope_factor", 3.5),
            model_params.get("tobler_slope_offset", 0.05),
            model_params.get("tobler_min_speed_mps", 0.05),
        )
    if model_key == MODEL_NAISMITH:
        return naismith_time_s(
            horiz_m,
            dz_m,
            model_params.get("naismith_horizontal_kmh", 5.0),
            model_params.get("naismith_ascent_m_per_h", 600.0),
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
        W = max(1.0, float(model_params.get("pandolf_body_kg", 70.0)))
        L = max(0.0, float(model_params.get("pandolf_load_kg", 0.0)))
        eta = max(0.1, float(model_params.get("pandolf_terrain_factor", 1.0)))
        V = max(0.05, float(model_params.get("pandolf_speed_mps", 5.0 * 1000.0 / 3600.0)))

        if cost_mode == "time_s":
            return float(horiz_m) / V

        grade_percent = (float(dz_m) / float(horiz_m)) * 100.0
        load_ratio = (L / W) if W > 0 else 0.0
        M = (1.5 * W) + (2.0 * (W + L) * (load_ratio**2)) + (
            eta * (W + L) * (1.5 * V * V + 0.35 * V * grade_percent)
        )
        # The Pandolf equation has no downhill validity: on grades below about
        # -9% the grade term drives M toward (and past) zero, which would make
        # steep descents ~300x cheaper than flat ground and glue "energy-optimal"
        # paths to cliffs. Clamp to the standing metabolic term 1.5·W (a
        # conservative floor: walking downhill still costs at least standing
        # metabolism; a full Santee-style descent correction would need
        # validated coefficients).
        M = max(1.5 * W, float(M))
        return (float(M) * float(horiz_m)) / V

    # Isotropic slope-based models (use absolute slope magnitude)
    slope_abs = abs(float(dz_m)) / float(horiz_m) if horiz_m > 0 else 0.0  # tan(theta)
    min_speed_mps = float(model_params.get("min_speed_mps", 0.05))

    if model_key == MODEL_HERZOG_METABOLIC:
        # Based on the slope_cost implementation in Zoran Čučković's "Movement Analysis" QGIS plugin.
        # We normalize the factor so that slope=0 keeps the base speed.
        den = sum(
            (
                1337.8 * slope_abs**6,
                278.19 * slope_abs**5,
                -517.39 * slope_abs**4,
                -78.199 * slope_abs**3,
                93.419 * slope_abs**2,
                19.825 * slope_abs,
                1.64,
            )
        )
        rel = 1.0 / max(1e-9, float(den))
        rel0 = 1.0 / 1.64
        rel_norm = rel / rel0
        base_mps = max(min_speed_mps, float(model_params.get("herzog_base_kmh", 5.0)) * 1000.0 / 3600.0)
        speed_mps = max(min_speed_mps, base_mps * rel_norm)
        return float(horiz_m) / speed_mps

    if model_key == MODEL_CONOLLY_LAKE:
        # Conolly & Lake: relative slope penalty anchored at a reference slope.
        # We clamp the factor to >=1 so gentle slopes do not become "faster than flat".
        ref_deg = max(0.1, float(model_params.get("conolly_ref_slope_deg", 1.0)))
        ref_tan = math.tan(math.radians(ref_deg))
        factor = max(1.0, slope_abs / max(1e-9, ref_tan))
        base_mps = max(min_speed_mps, float(model_params.get("conolly_base_kmh", 5.0)) * 1000.0 / 3600.0)
        return (float(horiz_m) / base_mps) * factor

    if model_key == MODEL_HERZOG_WHEELED:
        # Optional "hard" slope limit for wheeled traffic (beyond this, effectively impassable).
        max_deg = float(model_params.get("wheeled_max_slope_deg", 45.0))
        max_deg = max(1.0, min(89.0, max_deg))
        slope_deg = math.degrees(math.atan(slope_abs))
        if slope_deg > max_deg + 1e-9:
            # Treat as unreachable instead of producing extreme finite costs (keeps raster ranges readable).
            return math.inf

        critical_deg = max(1.0, float(model_params.get("wheeled_critical_slope_deg", 12.0)))
        critical_percent = math.tan(math.radians(critical_deg)) * 100.0
        slope_percent = slope_abs * 100.0
        speed_factor = 1.0 / (1.0 + (slope_percent / max(1e-9, critical_percent)) ** 2)
        base_mps = max(min_speed_mps, float(model_params.get("wheeled_base_kmh", 4.0)) * 1000.0 / 3600.0)
        speed_mps = max(min_speed_mps, base_mps * speed_factor)
        return float(horiz_m) / speed_mps

    # Fallback
    return naismith_time_s(
        horiz_m,
        dz_m,
        model_params.get("naismith_horizontal_kmh", 5.0),
        model_params.get("naismith_ascent_m_per_h", 600.0),
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
