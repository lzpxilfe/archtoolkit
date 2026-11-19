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
from .swallow_log import log_swallowed


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

    A failed real write raises nothing from ``WriteArray``/``FlushCache`` (both
    are void calls) - GDAL only records it in its error state - so the write is
    verified twice before being called a success: the GDAL error state is
    checked after the flush, and the closed file is re-opened to confirm GDAL
    sees one complete raster of the written shape.

    Returns ``True`` on success and ``False`` only when the GTiff driver could
    not create the dataset, so callers that previously branched on
    ``driver.Create(...) is None`` keep that exact behaviour.  Any other
    failure raises after the partial file has been removed.
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
    band = None
    try:
        gdal.ErrorReset()
        out_ds.SetGeoTransform(geotransform)
        if projection:
            out_ds.SetProjection(projection)
        band = out_ds.GetRasterBand(1)
        if band is None:
            raise RuntimeError(f"GDAL band 1 missing while writing {out_path}")
        if nodata is not None:
            band.SetNoDataValue(float(nodata))
        err_rc = band.WriteArray(array)
        if err_rc not in (None, 0):
            raise RuntimeError(
                f"GDAL WriteArray returned error code {err_rc} ({gdal.GetLastErrorMsg()}) while writing {out_path}"
            )
        band.FlushCache()
        out_ds.FlushCache()
        # Release the band BEFORE the dataset: in GDAL's Python bindings a band
        # holds a reference to its parent dataset, so ``out_ds = None`` alone
        # keeps the file open on Windows (blocking os.remove on failure and
        # deferring TIFF directory finalization until function exit).
        band = None
        out_ds = None
        # Check GDAL error state AFTER close (closing flushes compressed tiles
        # and writes the TIFF IFD, which is where disk-full errors surface).
        if gdal.GetLastErrorType() >= gdal.CE_Failure:
            raise RuntimeError(
                f"GDAL write failed ({gdal.GetLastErrorMsg()}) while writing {out_path}"
            )
        if not _closed_file_is_complete(out_path, rows, cols):
            raise RuntimeError(f"GeoTIFF verification failed (truncated write?): {out_path}")
        ok = True
    finally:
        # Release band first, then dataset (required on Windows), then drop
        # a truncated file left by a failed write.
        band = None
        out_ds = None
        if not ok and os.path.exists(str(out_path)):
            try:
                os.remove(str(out_path))
            except OSError as _exc:
                log_swallowed("tools/raster_io.py (write_single_band_geotiff)", _exc)
    return True


def _closed_file_is_complete(out_path, rows, cols) -> bool:
    """True when the closed ``out_path`` re-opens as a complete rows x cols raster.

    Catches the truncation a void ``FlushCache()`` cannot report: GDAL writes
    the TIFF directory at close, so a cut-off write leaves a file that either
    fails to open or reports the wrong raster shape.
    """
    from osgeo import gdal

    try:
        ds = gdal.Open(str(out_path))
    except Exception as _exc:
        log_swallowed("tools/raster_io.py (_closed_file_is_complete)", _exc)
        return False
    if ds is None:
        return False
    try:
        return bool(ds.RasterCount == 1 and ds.RasterYSize == rows and ds.RasterXSize == cols)
    finally:
        ds = None


def inv_geotransform(gt):
    """Invert a GDAL geotransform across GDAL's two return conventions.

    Older GDAL returns ``(success, inverse)``; newer builds return the inverse
    tuple directly or ``None``. Three modules each carried a copy of this
    branch; this is the one implementation.
    """
    from osgeo import gdal

    inv = gdal.InvGeoTransform(gt)
    if isinstance(inv, (list, tuple)) and len(inv) == 2:
        ok, inv_gt = inv
        if not ok:
            raise Exception("geotransform inverse failed")
        return inv_gt
    if isinstance(inv, (list, tuple)) and len(inv) == 6:
        return inv
    raise Exception("geotransform inverse failed")
