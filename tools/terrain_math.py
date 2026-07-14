# -*- coding: utf-8 -*-
"""QGIS-free terrain-derivative math on elevation arrays.

These operate purely on NumPy elevation grids, so they can be regression-tested
against analytic surfaces (a paraboloid has a known, constant curvature) without
a QGIS runtime.  The dialog handles the raster I/O and QGIS layers.
"""

from __future__ import annotations

import numpy as np


def zt_curvature(z, cell):
    """Zevenbergen & Thorne (1987) profile/plan curvature of an elevation grid.

    ``z`` is a 2D array of elevations, ``cell`` the (square) cell size in the
    same horizontal units.  Returns ``(profile, plan)`` arrays.  Neighbours are
    taken with ``np.roll`` so callers must treat the one-cell border as invalid
    (it wraps around).  Where the surface is locally flat (slope ~ 0) both
    curvatures are 0 rather than a divide-by-zero NaN.
    """
    Z2 = np.roll(z, 1, 0)
    Z8 = np.roll(z, -1, 0)
    Z4 = np.roll(z, 1, 1)
    Z6 = np.roll(z, -1, 1)
    Z1 = np.roll(np.roll(z, 1, 0), 1, 1)
    Z3 = np.roll(np.roll(z, 1, 0), -1, 1)
    Z7 = np.roll(np.roll(z, -1, 0), 1, 1)
    Z9 = np.roll(np.roll(z, -1, 0), -1, 1)
    Z5 = z
    L2 = cell * cell
    D = ((Z4 + Z6) / 2.0 - Z5) / L2
    E = ((Z2 + Z8) / 2.0 - Z5) / L2
    F = (-Z1 + Z3 + Z7 - Z9) / (4.0 * L2)
    G = (-Z4 + Z6) / (2.0 * cell)
    H = (Z2 - Z8) / (2.0 * cell)
    denom = G * G + H * H
    small = denom < 1e-12
    ds = np.where(small, 1.0, denom)
    profile = np.where(small, 0.0, 2.0 * (D * G * G + E * H * H + F * G * H) / ds)
    plan = np.where(small, 0.0, -2.0 * (D * H * H + E * G * G - F * G * H) / ds)
    return profile, plan
