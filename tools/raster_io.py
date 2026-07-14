# -*- coding: utf-8 -*-
"""GDAL raster-writing helpers with no QGIS dependency.

Keeping the file rules here (create, write, delete-on-failure) free of QGIS
imports lets them be regression-tested in a plain Python environment, the same
separation ``atomic_output`` uses for its staging rules.  GDAL itself is
imported lazily inside the function so importing this module never requires
``osgeo`` to be present.
"""

from __future__ import annotations

import os


def write_single_band_geotiff(
    out_path,
    array,
    *,
    geotransform,
    projection=None,
    nodata=None,
    gdal_type=None,
    options=("TILED=YES", "COMPRESS=LZW"),
):
    """Write a single-band GeoTIFF, deleting the partial file if the write fails.

    Long-running tools write unique-named temp rasters; a write that dies
    partway (disk full, a killed process) would otherwise leave a truncated
    ``.tif`` that no layer references and nothing tracks for cleanup.  This
    helper removes that partial file on any error and re-raises so the caller
    still reports the failure.

    Returns ``True`` on success and ``False`` only when the GTiff driver could
    not create the dataset, so callers that previously branched on
    ``driver.Create(...) is None`` keep that exact behaviour.
    """
    from osgeo import gdal

    shape = getattr(array, "shape", None)
    if not shape or len(shape) != 2:
        raise ValueError("write_single_band_geotiff expects a 2D array")
    rows, cols = int(shape[0]), int(shape[1])

    driver = gdal.GetDriverByName("GTiff")
    if driver is None:
        return False
    if gdal_type is None:
        gdal_type = gdal.GDT_Float32

    out_ds = driver.Create(str(out_path), cols, rows, 1, gdal_type, list(options))
    if out_ds is None:
        return False

    ok = False
    try:
        out_ds.SetGeoTransform(geotransform)
        if projection:
            out_ds.SetProjection(projection)
        band = out_ds.GetRasterBand(1)
        if nodata is not None:
            band.SetNoDataValue(float(nodata))
        band.WriteArray(array)
        band.FlushCache()
        out_ds.FlushCache()
        ok = True
    finally:
        # Close the dataset before any delete (required on Windows), then drop
        # a truncated file left by a failed write.
        out_ds = None
        if not ok and os.path.exists(str(out_path)):
            try:
                os.remove(str(out_path))
            except OSError:
                pass
    return True
