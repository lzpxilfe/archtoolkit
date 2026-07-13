"""QGIS integration tests for align/export cancellation and GDAL failures.

The regular dependency-free CI discovers this module but skips it when PyQGIS
and GDAL are unavailable.  Run it with QGIS' Python environment and the GDAL
provider initialized to exercise the real subprocess/task path.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest


QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
    from osgeo import gdal, osr
    from qgis.PyQt import QtWidgets
    from qgis.PyQt.QtCore import QObject, QTimer
    from qgis.core import QgsApplication, QgsRasterLayer

    from processing.core.Processing import Processing
    from tools.align_export_dialog import (
        AlignExportDialog,
        _Cancelled,
        _WarpValidationContract,
    )
    from tools.raster_grid_contract import Extent, RasterGrid, canonical_gdal_target_grid

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class AlignExportQgisIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._owns_app = QgsApplication.instance() is None
        if cls._owns_app:
            prefix = os.environ.get("QGIS_PREFIX_PATH", "").strip()
            if prefix:
                QgsApplication.setPrefixPath(prefix, True)
            cls.app = QgsApplication([], True)
            cls.app.initQgis()
        else:
            cls.app = QgsApplication.instance()
        Processing.initialize()
        if QgsApplication.processingRegistry().algorithmById("gdal:warpreproject") is None:
            raise unittest.SkipTest("QGIS GDAL provider is unavailable")

    @classmethod
    def tearDownClass(cls):
        if cls._owns_app:
            cls.app.exitQgis()

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="archtoolkit_align_qgis_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)

    def _path(self, name):
        return os.path.join(self.temp_dir, name)

    @staticmethod
    def _spatial_reference():
        spatial_ref = osr.SpatialReference()
        spatial_ref.ImportFromEPSG(32652)
        return spatial_ref

    def _create_raster(self, path, width, height, *, tiled=False, nodata=None):
        options = ["TILED=YES"] if tiled else []
        dataset = gdal.GetDriverByName("GTiff").Create(
            path,
            width,
            height,
            1,
            gdal.GDT_Float32,
            options=options,
        )
        self.assertIsNotNone(dataset)
        dataset.SetProjection(self._spatial_reference().ExportToWkt())
        dataset.SetGeoTransform((0, 1, 0, height, 0, -1))
        band = dataset.GetRasterBand(1)
        if nodata is not None:
            band.SetNoDataValue(nodata)
        band.Fill(1)
        dataset = None

    def _contract(self, grid, *, nodata=-9999.0):
        crs = QgsRasterLayer(self._path("contract_crs_source.tif"), "missing").crs()
        if not crs.isValid():
            source = self._path("contract_crs_source.tif")
            self._create_raster(source, 1, 1)
            crs = QgsRasterLayer(source, "contract crs").crs()
        return _WarpValidationContract(
            crs=crs,
            grid=grid,
            band_count=1,
            nodata_values=(nodata,),
            categorical=False,
        )

    @staticmethod
    def _progress_dialog():
        progress = QtWidgets.QProgressDialog("working", "cancel", 0, 1)
        progress.setMinimumDuration(0)
        progress.show()
        QtWidgets.QApplication.processEvents()
        return progress

    def test_gui_cancel_stops_active_gdal_task_and_raises_cancelled(self):
        source = self._path("cancel_source.tif")
        output = self._path("cancel_output.tif")
        # A small source upsampled to 100M cells keeps gdalwarp active long
        # enough for the GUI timer to click the real progress cancel button.
        self._create_raster(source, 100, 100)
        progress = self._progress_dialog()
        self.addCleanup(progress.close)
        cancel_button = progress.findChild(QtWidgets.QPushButton)
        self.assertIsNotNone(cancel_button)

        timer_fired = []

        def click_cancel_button():
            timer_fired.append(time.monotonic())
            cancel_button.click()

        QTimer.singleShot(100, click_cancel_button)
        started = time.monotonic()
        with self.assertRaises(_Cancelled):
            AlignExportDialog._warp(
                QObject(),
                source,
                output,
                0.01,
                "0,100,0,100",
                "EPSG:32652",
                nearest=False,
                progress=progress,
            )
        elapsed = time.monotonic() - started

        self.assertTrue(timer_fired)
        self.assertTrue(progress.wasCanceled())
        # A completed output is about 400 MB and opens as a valid raster.  The
        # canceled task must return promptly with no complete publishable file.
        if os.path.exists(output):
            self.assertFalse(QgsRasterLayer(output, "canceled output").isValid())
            self.assertLess(os.path.getsize(output), 400_000_000)
        self.assertLess(elapsed, 2.0)

    def test_provider_report_error_blocks_partial_warp_output(self):
        source = self._path("truncated_source.tif")
        output = self._path("partial_output.tif")
        self._create_raster(source, 2000, 2000, tiled=True)
        original_size = os.path.getsize(source)
        self.assertGreater(original_size, 2_000_000)
        os.truncate(source, original_size - 2_000_000)
        # The provider accepts the header; failure occurs only during tile read.
        self.assertTrue(QgsRasterLayer(source, "truncated source").isValid())

        progress = self._progress_dialog()
        self.addCleanup(progress.close)
        with self.assertRaisesRegex(RuntimeError, "GDAL 정렬"):
            AlignExportDialog._warp(
                QObject(),
                source,
                output,
                1.0,
                "0,2000,0,2000",
                "EPSG:32652",
                nearest=False,
                progress=progress,
            )

    def test_nonmultiple_extent_validates_against_canonical_gdal_grid(self):
        source = self._path("nonmultiple_source.tif")
        output = self._path("nonmultiple_output.tif")
        self._create_raster(source, 20, 20)
        progress = self._progress_dialog()
        self.addCleanup(progress.close)

        AlignExportDialog._warp(
            QObject(),
            source,
            output,
            1.7,
            "0.2,10.45,-1.3,6.9",
            QgsRasterLayer(source, "source crs").crs(),
            nearest=False,
            progress=progress,
        )
        expected_grid = canonical_gdal_target_grid(
            Extent(0.2, 10.45, -1.3, 6.9),
            1.7,
            1.7,
        )

        AlignExportDialog._validate_warp_output(
            QObject(),
            output,
            "nonmultiple source",
            self._contract(expected_grid),
        )

    def test_one_pixel_origin_shift_is_rejected_by_output_validation(self):
        source = self._path("origin_source.tif")
        output = self._path("origin_output.tif")
        self._create_raster(source, 20, 20)
        progress = self._progress_dialog()
        self.addCleanup(progress.close)

        AlignExportDialog._warp(
            QObject(),
            source,
            output,
            1.0,
            "0,10,0,10",
            "EPSG:32652",
            nearest=False,
            progress=progress,
        )
        shifted_grid = RasterGrid(
            width=10,
            height=10,
            extent=Extent(1.0, 11.0, 0.0, 10.0),
            resolution_x=1.0,
            resolution_y=1.0,
        )

        with self.assertRaisesRegex(RuntimeError, "격자가 기준과 다릅니다"):
            AlignExportDialog._validate_warp_output(
                QObject(),
                output,
                "origin source",
                self._contract(shifted_grid),
            )


if __name__ == "__main__":
    unittest.main()
