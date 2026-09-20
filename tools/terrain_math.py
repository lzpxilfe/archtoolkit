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

    Sign convention (stated here because the caller cannot infer it from the
    numbers, and cross-checking against GRASS/SAGA shows the opposite sign):
    these values are the **negation** of the Zevenbergen & Thorne formula as
    printed in the paper and in the ESRI documentation, which puts them in
    agreement with ESRI's *descriptive* wording.

    - profile (종단): 음(-) = 볼록 convex (침식 경향) / 양(+) = 오목 concave (퇴적 경향)
    - plan (횡단):   음(-) = 수렴 convergent (물 모임) / 양(+) = 발산 divergent (능선)

    Same wording as REFERENCES.md "부호 규약" and the layer names the dialog
    writes ("부호규약: 음=볼록" / "부호규약: 음=수렴").
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


def tri_radius(z, radius, *, nodata_mask=None, progress_cb=None, cancel_check=None):
    """Terrain ruggedness over a (2r+1)x(2r+1) window, as an RMS difference.

    ``gdaldem``'s TRI is fixed at 3x3, so on a 5 m DEM it reports ruggedness
    over a 15 m neighbourhood. Landscape-scale questions - and the ruggedness
    variable an archaeological model usually wants - are about a broader
    window, and a 3x3 result is not a coarse version of that, it is a
    different variable.

    Riley et al. (1999) define TRI as ``sqrt(sum((z_c - z_n)^2))`` over the
    eight neighbours. That sum grows with the number of cells in the window, so
    values at different radii are not comparable. This returns the *normalised*
    form - the root-mean-square difference from the centre cell::

        tri_r(c) = sqrt( mean_{n in W(c)} (z_c - z_n)^2 )

    which is Riley's index divided by ``sqrt(N)``; on a full 3x3 window the two
    differ by exactly ``sqrt(8)``. Callers should expose it under its own name
    rather than as "TRI", since the units differ from the 3x3 product.

    ``z`` is a 2D elevation array and ``radius`` a positive cell count.
    ``nodata_mask`` marks cells to exclude (True = NoData); those cells neither
    contribute to a neighbourhood nor receive a value. Cells whose window holds
    no valid neighbour come back as NaN, as do the outermost ``radius`` rows and
    columns, whose windows are not fully inside the grid.

    Cost is O(n * (2r+1)^2): the absolute/squared difference is taken against
    the centre cell, which no summed-area shortcut can decompose. The caller is
    responsible for guarding the array size.

    ``progress_cb(done, total)`` is called after each window offset and
    ``cancel_check()`` is polled at the same point; if it returns True the
    function stops and returns ``None``. A large radius on a large grid runs
    for tens of seconds, and a caller on a GUI thread needs both to keep the
    interface alive and give the user a way out.
    """
    array = np.asarray(z, dtype="float64")
    if array.ndim != 2:
        raise ValueError("tri_radius expects a 2D array")
    radius = int(radius)
    if radius < 1:
        raise ValueError("radius must be at least 1 cell")
    rows, cols = array.shape
    if rows <= 2 * radius or cols <= 2 * radius:
        raise ValueError("array is too small for the requested radius")

    valid = np.ones(array.shape, dtype=bool)
    if nodata_mask is not None:
        valid &= ~np.asarray(nodata_mask, dtype=bool)
    valid &= np.isfinite(array)

    centre = np.where(valid, array, 0.0)
    sq_total = np.zeros(array.shape, dtype="float64")
    counts = np.zeros(array.shape, dtype="int64")

    # Accumulate over every offset in the window except the centre itself.
    # np.roll would wrap the border around the grid, which for a ruggedness
    # statistic invents a cliff at the edges, so the border is trimmed instead.
    total_offsets = (2 * radius + 1) ** 2 - 1
    done = 0
    for row_offset in range(-radius, radius + 1):
        for col_offset in range(-radius, radius + 1):
            if row_offset == 0 and col_offset == 0:
                continue
            shifted = _shift2d(centre, row_offset, col_offset)
            shifted_valid = _shift2d(valid, row_offset, col_offset, fill=False)
            both = valid & shifted_valid
            difference = np.where(both, centre - shifted, 0.0)
            sq_total += difference * difference
            counts += both
            done += 1
            if progress_cb is not None:
                progress_cb(done, total_offsets)
            if cancel_check is not None and cancel_check():
                return None

    with np.errstate(invalid="ignore", divide="ignore"):
        result = np.sqrt(sq_total / np.where(counts > 0, counts, 1))
    result[counts == 0] = np.nan
    result[~valid] = np.nan

    # The rim cannot see a full window, so its value would be computed from a
    # truncated neighbourhood and read as artificially smooth terrain.
    result[:radius, :] = np.nan
    result[-radius:, :] = np.nan
    result[:, :radius] = np.nan
    result[:, -radius:] = np.nan
    return result


def _shift2d(array, row_offset, col_offset, fill=0.0):
    """Shift a 2D array without wrapping, padding the vacated edge with ``fill``."""
    out = np.full(array.shape, fill, dtype=array.dtype)
    rows, cols = array.shape
    src_row = slice(max(0, -row_offset), rows - max(0, row_offset))
    dst_row = slice(max(0, row_offset), rows - max(0, -row_offset))
    src_col = slice(max(0, -col_offset), cols - max(0, col_offset))
    dst_col = slice(max(0, col_offset), cols - max(0, -col_offset))
    out[dst_row, dst_col] = array[src_row, src_col]
    return out
