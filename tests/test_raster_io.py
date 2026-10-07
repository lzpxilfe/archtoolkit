from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

from tools.raster_io import write_single_band_geotiff


class _FakeArray:
    def __init__(self, shape):
        self.shape = shape


class _FakeBand:
    def __init__(self, fail_write=False, silent_write=False, gdal_state=None):
        self._fail_write = fail_write
        self._silent_write = silent_write
        self._gdal_state = gdal_state
        self.nodata = "unset"
        self.wrote = False

    def SetNoDataValue(self, value):
        self.nodata = value

    def WriteArray(self, array):
        if self._fail_write:
            raise RuntimeError("disk full")
        if self._silent_write and self._gdal_state is not None:
            # Real GDAL reports a failed write (disk full, quota) only through
            # its error state - WriteArray/FlushCache raise nothing.
            self._gdal_state.update({"err_type": 3, "err_msg": "No space left on device"})
            return
        self.wrote = True

    def FlushCache(self):
        pass


class _FakeDataset:
    def __init__(self, path, fail_write=False, fail_flush=False, silent_write=False, gdal_state=None):
        self.path = path
        self._band = _FakeBand(
            fail_write=fail_write, silent_write=silent_write, gdal_state=gdal_state
        )
        self._fail_flush = fail_flush
        self.geotransform = None
        self.projection = "unset"

    def SetGeoTransform(self, gt):
        self.geotransform = gt

    def SetProjection(self, proj):
        self.projection = proj

    def GetRasterBand(self, index):
        return self._band

    def FlushCache(self):
        if self._fail_flush:
            raise RuntimeError("flush failed")


class _FakeReopenedDataset:
    """What gdal.Open returns for a file the fake driver claims to have written."""

    def __init__(self, rows, cols):
        self.RasterCount = 1
        self.RasterYSize = rows
        self.RasterXSize = cols


class _FakeDriver:
    def __init__(self, create_returns_none=False, fail_write=False, fail_flush=False, silent_write=False):
        self._none = create_returns_none
        self._fail_write = fail_write
        self._fail_flush = fail_flush
        self._silent_write = silent_write
        self._gdal_state = None
        self.last = None
        self.written = {}  # path -> (rows, cols) of every Create

    def bind_gdal_state(self, state):
        self._gdal_state = state

    def Create(self, path, cols, rows, bands, gdal_type, options):
        if self._none:
            return None
        # Mirror GDAL: the destination file appears on disk as soon as the
        # dataset is created, before any array is written.
        with open(path, "wb") as handle:
            handle.write(b"partial")
        self.written[path] = (rows, cols)
        self.last = _FakeDataset(
            path,
            fail_write=self._fail_write,
            fail_flush=self._fail_flush,
            silent_write=self._silent_write,
            gdal_state=self._gdal_state,
        )
        return self.last


def _build_fake_osgeo(driver, *, driver_is_none=False):
    gdal = types.ModuleType("osgeo.gdal")
    gdal.GDT_Float32 = 6
    gdal.GDT_Byte = 1
    gdal.CE_Failure = 3
    gdal.GetDriverByName = lambda name: (None if driver_is_none else driver)

    state = {"err_type": 0, "err_msg": "", "open_mode": "ok"}
    if driver is not None and hasattr(driver, "bind_gdal_state"):
        driver.bind_gdal_state(state)

    def error_reset():
        state["err_type"] = 0
        state["err_msg"] = ""

    def open_file(path):
        # "ok": the written raster re-opens complete; "truncated": the file is
        # cut off before GDAL could write its directory; "wrong_shape": close
        # left a raster of a different shape than requested.
        if state["open_mode"] == "truncated":
            return None
        if driver is None:
            return None
        dims = driver.written.get(path)
        if dims is None:
            return None
        if state["open_mode"] == "wrong_shape":
            return _FakeReopenedDataset(dims[0] + 1, dims[1])
        return _FakeReopenedDataset(*dims)

    gdal.ErrorReset = error_reset
    gdal.GetLastErrorType = lambda: state["err_type"]
    gdal.GetLastErrorMsg = lambda: state["err_msg"]
    gdal.Open = open_file
    # Test hook: simulate a file truncated before GDAL wrote its directory.
    gdal._set_open_mode = lambda mode: state.update({"open_mode": mode})
    osgeo = types.ModuleType("osgeo")
    osgeo.gdal = gdal
    return osgeo, gdal


class WriteSingleBandGeotiffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self._saved = {k: sys.modules.get(k) for k in ("osgeo", "osgeo.gdal")}

    def _use(self, osgeo, gdal):
        sys.modules["osgeo"] = osgeo
        sys.modules["osgeo.gdal"] = gdal

        def restore():
            for key, value in self._saved.items():
                if value is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = value

        self.addCleanup(restore)

    def test_success_writes_file_and_returns_true(self):
        driver = _FakeDriver()
        self._use(*_build_fake_osgeo(driver))
        out = self.root / "ok.tif"

        result = write_single_band_geotiff(
            str(out),
            _FakeArray((3, 4)),
            geotransform=(0, 1, 0, 0, 0, -1),
            projection="WKT",
            nodata=-9999.0,
        )

        self.assertTrue(result)
        self.assertTrue(out.exists())
        self.assertTrue(driver.last._band.wrote)
        self.assertEqual(driver.last._band.nodata, -9999.0)
        self.assertEqual(driver.last.projection, "WKT")

    def test_write_failure_deletes_partial_and_reraises(self):
        driver = _FakeDriver(fail_write=True)
        self._use(*_build_fake_osgeo(driver))
        out = self.root / "partial.tif"

        with self.assertRaises(RuntimeError):
            write_single_band_geotiff(
                str(out),
                _FakeArray((3, 4)),
                geotransform=(0, 1, 0, 0, 0, -1),
            )

        # The truncated file the driver created must not survive the failure.
        self.assertFalse(out.exists())

    def test_flush_failure_also_deletes_partial(self):
        driver = _FakeDriver(fail_flush=True)
        self._use(*_build_fake_osgeo(driver))
        out = self.root / "flush.tif"

        with self.assertRaises(RuntimeError):
            write_single_band_geotiff(
                str(out),
                _FakeArray((2, 2)),
                geotransform=(0, 1, 0, 0, 0, -1),
            )

        self.assertFalse(out.exists())

    def test_silent_gdal_error_deletes_partial_and_reraises(self):
        # A failed real write raises nothing - GDAL only records the error in
        # its error state. The write must not be published as success.
        driver = _FakeDriver(silent_write=True)
        osgeo, gdal = _build_fake_osgeo(driver)
        self._use(osgeo, gdal)
        out = self.root / "silent.tif"

        with self.assertRaises(RuntimeError):
            write_single_band_geotiff(
                str(out),
                _FakeArray((3, 4)),
                geotransform=(0, 1, 0, 0, 0, -1),
            )

        self.assertFalse(out.exists())

    def test_truncated_close_deletes_partial_and_reraises(self):
        driver = _FakeDriver()
        osgeo, gdal = _build_fake_osgeo(driver)
        self._use(osgeo, gdal)
        out = self.root / "truncated.tif"
        # The file is cut off before GDAL wrote its directory: it cannot be
        # re-opened after close.
        gdal._set_open_mode("truncated")

        with self.assertRaises(RuntimeError):
            write_single_band_geotiff(
                str(out),
                _FakeArray((3, 4)),
                geotransform=(0, 1, 0, 0, 0, -1),
            )

        self.assertFalse(out.exists())

    def test_wrong_shape_reopen_deletes_partial_and_reraises(self):
        driver = _FakeDriver()
        osgeo, gdal = _build_fake_osgeo(driver)
        self._use(osgeo, gdal)
        out = self.root / "shape.tif"
        gdal._set_open_mode("wrong_shape")

        with self.assertRaises(RuntimeError):
            write_single_band_geotiff(
                str(out),
                _FakeArray((3, 4)),
                geotransform=(0, 1, 0, 0, 0, -1),
            )

        self.assertFalse(out.exists())

    def test_create_returning_none_returns_false(self):
        driver = _FakeDriver(create_returns_none=True)
        self._use(*_build_fake_osgeo(driver))
        out = self.root / "none.tif"

        self.assertFalse(
            write_single_band_geotiff(
                str(out),
                _FakeArray((2, 2)),
                geotransform=(0, 1, 0, 0, 0, -1),
            )
        )
        self.assertFalse(out.exists())

    def test_missing_driver_returns_false(self):
        self._use(*_build_fake_osgeo(None, driver_is_none=True))
        out = self.root / "nodriver.tif"

        self.assertFalse(
            write_single_band_geotiff(
                str(out),
                _FakeArray((2, 2)),
                geotransform=(0, 1, 0, 0, 0, -1),
            )
        )

    def test_non_2d_array_raises(self):
        driver = _FakeDriver()
        self._use(*_build_fake_osgeo(driver))

        with self.assertRaisesRegex(ValueError, "2D array"):
            write_single_band_geotiff(
                str(self.root / "x.tif"),
                _FakeArray((5,)),
                geotransform=(0, 1, 0, 0, 0, -1),
            )

    def test_none_projection_and_nodata_are_skipped(self):
        driver = _FakeDriver()
        self._use(*_build_fake_osgeo(driver))
        out = self.root / "skip.tif"

        write_single_band_geotiff(
            str(out),
            _FakeArray((2, 2)),
            geotransform=(0, 1, 0, 0, 0, -1),
            projection=None,
            nodata=None,
        )

        self.assertEqual(driver.last.projection, "unset")
        self.assertEqual(driver.last._band.nodata, "unset")


if __name__ == "__main__":
    unittest.main()
