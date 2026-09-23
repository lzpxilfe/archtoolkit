# -*- coding: utf-8 -*-
"""QGIS-free terrain-derivative math on elevation arrays.

These operate purely on NumPy elevation grids, so they can be regression-tested
against analytic surfaces (a paraboloid has a known, constant curvature) without
a QGIS runtime.  The dialog handles the raster I/O and QGIS layers.
"""

from __future__ import annotations

import numpy as np


def zt_curvature(z, cell, cell_y=None):
    """Zevenbergen & Thorne (1987) profile/plan curvature of an elevation grid.

    ``z`` is a 2D array of elevations, ``cell`` the cell width (x) in the same
    horizontal units and ``cell_y`` the cell height; it defaults to ``cell``
    (square pixels).  On non-square pixels the x and y differences need their
    own spacing: using one mean size for both axes scaled the second
    derivatives wrongly (a 10 x 5 m grid reported ~1.9x the true curvature).
    Returns ``(profile, plan)`` arrays.  Neighbours are
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
    lx = float(cell)
    ly = lx if cell_y is None else float(cell_y)
    D = ((Z4 + Z6) / 2.0 - Z5) / (lx * lx)
    E = ((Z2 + Z8) / 2.0 - Z5) / (ly * ly)
    F = (-Z1 + Z3 + Z7 - Z9) / (4.0 * lx * ly)
    G = (-Z4 + Z6) / (2.0 * lx)
    H = (Z2 - Z8) / (2.0 * ly)
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


def focal_tpi(z, radius, *, nodata_mask=None):
    """Topographic Position Index over an exact (2r+1)x(2r+1) focal window.

    ``tpi(c) = z_c - mean{ z_n : n in W(c), n != c, n valid }``

    The centre cell is excluded from the mean, exactly as gdaldem's 3x3 TPI
    (the radius-1 path of the dialog) excludes it, so radius 1 here equals
    ``gdaldem TPI`` and every radius shares one definition (Weiss 2001: the
    cell's elevation minus the mean elevation of its neighbourhood).

    This replaces a block-average + bilinear-resample approximation that was
    exact only at block centres: on a paraboloid it averaged 3x the true TPI
    with a (2r+1)-cell periodic artefact.  The window sums come from cumulative
    sums (a separable summed-area table), so the cost is O(n) for any radius.

    ``nodata_mask`` marks cells to exclude (True = NoData); NaN/inf are always
    excluded.  NoData cells are left out of both the sum and the count, so a
    cell next to a hole or a clipped collar is averaged over its valid
    neighbours only, and receives NaN itself only when it is NoData or has no
    valid neighbour.  The outermost ``radius`` rows and columns are NaN: their
    window leaves the grid, and a one-sided window on a slope would read as a
    false ridge or valley along the DEM border (same rule as ``tri_radius``
    and gdaldem without -compute_edges).
    """
    array = np.asarray(z, dtype="float64")
    if array.ndim != 2:
        raise ValueError("focal_tpi expects a 2D array")
    radius = int(radius)
    if radius < 1:
        raise ValueError("radius must be at least 1 cell")
    rows, cols = array.shape
    if rows <= 2 * radius or cols <= 2 * radius:
        raise ValueError("array is too small for the requested radius")

    valid = np.isfinite(array)
    if nodata_mask is not None:
        valid &= ~np.asarray(nodata_mask, dtype=bool)

    # TPI is invariant to an additive constant; working relative to the mean
    # keeps the cumulative sums at relief scale (no cancellation on a 1000 m
    # base).
    ref = float(array[valid].mean()) if np.any(valid) else 0.0
    values = np.where(valid, array - ref, 0.0)
    counts = valid.astype("float64")

    window = 2 * radius + 1

    def _box_sum(a):
        # Sum over every full (2r+1)x(2r+1) window; result is (rows-2r, cols-2r)
        # and element [i, j] belongs to the centre cell [i+r, j+r].
        c = np.cumsum(a, axis=0)
        c = np.concatenate([np.zeros((1, a.shape[1])), c], axis=0)
        s = c[window:, :] - c[:-window, :]
        c = np.cumsum(s, axis=1)
        c = np.concatenate([np.zeros((s.shape[0], 1)), c], axis=1)
        return c[:, window:] - c[:, :-window]

    inner = (slice(radius, rows - radius), slice(radius, cols - radius))
    sums = _box_sum(values) - values[inner]
    n = _box_sum(counts) - counts[inner]
    # Counts are sums of 0/1 and exact in float64; round away any residue.
    n = np.rint(n)

    result = np.full(array.shape, np.nan, dtype="float64")
    with np.errstate(invalid="ignore", divide="ignore"):
        result[inner] = values[inner] - sums / np.where(n > 0, n, 1.0)
    inner_result = result[inner]
    inner_result[n <= 0] = np.nan
    result[~valid] = np.nan
    return result


def focal_tpi_strips(rows, cols, radius, read_rows, write_rows, *, nodata=None,
                     block_rows=512, progress_cb=None):
    """Run :func:`focal_tpi` over horizontal strips so memory stays bounded.

    ``read_rows(first, stop)`` returns rows ``first..stop-1`` (all columns) of
    the elevation grid; ``write_rows(first, block)`` receives the finished TPI
    rows starting at ``first`` (float64, NaN where there is no value).  Each
    strip is read with a ``radius``-row halo above and below, so the output is
    identical to running :func:`focal_tpi` on the whole grid (the halo rows are
    discarded; only the true grid border stays NaN).  ``nodata`` is compared
    against the raw values before any cast.  ``progress_cb(done_rows, rows)``
    is called after each strip.
    """
    rows = int(rows)
    cols = int(cols)
    radius = int(radius)
    block_rows = max(1, int(block_rows))
    if rows <= 2 * radius or cols <= 2 * radius:
        raise ValueError("grid is too small for the requested radius")
    for first in range(0, rows, block_rows):
        stop = min(rows, first + block_rows)
        lo = max(0, first - radius)
        hi = min(rows, stop + radius)
        if hi - lo <= 2 * radius:
            # Only border rows remain in this strip: no full window fits.
            block = np.full((stop - first, cols), np.nan, dtype="float64")
        else:
            raw = np.asarray(read_rows(lo, hi))
            mask = None
            if nodata is not None:
                mask = raw == nodata
            tpi = focal_tpi(raw, radius, nodata_mask=mask)
            block = tpi[first - lo:stop - lo, :]
        write_rows(first, block)
        if progress_cb is not None:
            progress_cb(stop, rows)


# Value written for flat cells (no downslope direction) in the aspect raster.
# It must sit outside 0-360 so it cannot be read as a direction: gdaldem's
# -zero_for_flat writes 0, which is also due north, and on an integer DEM the
# due-north cells outnumbered the true flats about ten to one.
ASPECT_FLAT_VALUE = -1.0


def mark_flat_aspect(aspect, dem_valid, aspect_nodata, *, flat_value=ASPECT_FLAT_VALUE,
                     out_nodata=-9999.0):
    """Tell gdaldem's flat cells apart from NoData in an aspect grid.

    gdaldem aspect (without -zero_for_flat and without -compute_edges) writes
    its NoData value both for flat cells and for cells it could not compute:
    the one-cell border and every cell whose 3x3 window touches DEM NoData.
    A cell whose full 3x3 window is valid DEM and which still came back as
    NoData is therefore flat. Those get ``flat_value``; the rest of the NoData
    cells get ``out_nodata``; real directions are returned unchanged.
    """
    a = np.asarray(aspect, dtype="float64")
    valid = np.asarray(dem_valid, dtype=bool)
    if a.shape != valid.shape or a.ndim != 2:
        raise ValueError("aspect and dem_valid must be 2D arrays of one shape")
    missing = ~np.isfinite(a)
    if aspect_nodata is not None:
        missing |= a == aspect_nodata
    computable = np.zeros(a.shape, dtype=bool)
    rows, cols = a.shape
    if rows >= 3 and cols >= 3:
        full = np.ones((rows - 2, cols - 2), dtype=bool)
        for dr in (0, 1, 2):
            for dc in (0, 1, 2):
                full &= valid[dr:dr + rows - 2, dc:dc + cols - 2]
        computable[1:-1, 1:-1] = full
    out = np.where(missing, out_nodata, a)
    out[missing & computable] = flat_value
    return out


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
