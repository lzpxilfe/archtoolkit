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

# QGIS-free: the resampling decisions align/export makes live in
# tools.raster_semantics precisely so they can be pinned without PyQGIS.
from tools.raster_semantics import (
    CLASS_CODE_MAX_DISTINCT,
    is_categorical_meta,
    is_circular_meta,
    looks_like_class_codes,
)


QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
    from osgeo import gdal, osr
    from qgis.PyQt import QtWidgets
    from qgis.PyQt.QtCore import QObject, QTimer
    from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsRasterLayer

    from processing.core.Processing import Processing
    from tools.align_export_dialog import (
        AlignExportDialog,
        _Cancelled,
        _WarpValidationContract,
        _categorical_output_nodata,
    )
    from tools.raster_grid_contract import Extent, RasterGrid, canonical_gdal_target_grid

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc


class AlignResamplingSemanticsTests(unittest.TestCase):
    """The three-way nearest/bilinear decision, runnable without QGIS."""

    def test_aspect_is_circular_and_never_categorical(self):
        # terrain_analysis tags its aspect raster exactly like this. It is not
        # categorical (degrees are a measurement) but it must not be averaged:
        # 355 and 5 are both north, their mean 180 is south.
        aspect = {"tool_id": "terrain_analysis", "kind": "aspect", "units": "deg"}
        self.assertFalse(is_categorical_meta(aspect))
        self.assertTrue(is_circular_meta(aspect))

    def test_direction_kinds_are_circular(self):
        for kind in ("aspect", "Aspect_8dir", "bearing", "azimuth", "flow_bearing"):
            self.assertTrue(is_circular_meta({"kind": kind}), msg=kind)

    def test_linearised_aspect_derivatives_stay_continuous(self):
        # northness/eastness/TRASP exist so aspect CAN be averaged; they must
        # keep the bilinear path.
        for kind in ("northness", "eastness", "trasp", "slope", "dem", "tri", "distance_water"):
            self.assertFalse(is_circular_meta({"kind": kind, "units": "index"}), msg=kind)

    def test_missing_or_malformed_metadata_is_not_circular(self):
        for meta in (None, {}, {"kind": None}, {"tool_id": "terrain_analysis"}, "aspect", 5):
            self.assertFalse(is_circular_meta(meta), msg=repr(meta))

    def test_integer_raster_with_few_distinct_values_reads_as_class_codes(self):
        # The land-cover shape: Byte codes 1..7, no metadata.
        self.assertTrue(looks_like_class_codes("Byte", [1, 2, 3, 3, 7, 1, 6]))
        self.assertTrue(looks_like_class_codes("Int16", [10, 20, 30]))
        self.assertTrue(looks_like_class_codes("Byte", [4.0, 4.0]))

    def test_measurements_do_not_read_as_class_codes(self):
        # Float bands never; integer bands with many values (a Byte hillshade,
        # a scaled index) or fractional values never.
        self.assertFalse(looks_like_class_codes("Float32", [1, 2, 3]))
        self.assertFalse(looks_like_class_codes("Float64", [1, 2]))
        self.assertFalse(looks_like_class_codes("Byte", range(CLASS_CODE_MAX_DISTINCT + 1)))
        self.assertTrue(looks_like_class_codes("Byte", range(CLASS_CODE_MAX_DISTINCT)))
        self.assertFalse(looks_like_class_codes("Byte", [1, 2.5, 3]))
        self.assertFalse(looks_like_class_codes("Int16", [1, float("nan")]))

    def test_empty_or_unreadable_sample_keeps_the_default(self):
        self.assertFalse(looks_like_class_codes("Byte", []))
        self.assertFalse(looks_like_class_codes("", [1, 2]))
        self.assertFalse(looks_like_class_codes(None, [1, 2]))
        self.assertFalse(looks_like_class_codes("Byte", ["x", 1]))


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

    def _create_raster(self, path, width, height, *, tiled=False, nodata=None,
                       fill=1, valid_rows=None):
        """A Float32 raster filled with ``fill``; ``valid_rows`` top rows get 1."""
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
        band.Fill(fill)
        if valid_rows:
            array = band.ReadAsArray()
            array[:valid_rows, :] = 1
            band.WriteArray(array)
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
                nodata=-9999.0,
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
                nodata=-9999.0,
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
            nodata=-9999.0,
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
            nodata=-9999.0,
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

    # -- coverage -------------------------------------------------------------
    #
    # gdalwarp with an explicit -te/-tr writes the complete target grid even
    # when the source lies entirely outside it. Such a file has the right CRS,
    # grid, band count and NoData and holds no data at all.

    @staticmethod
    def _unit_grid():
        return RasterGrid(
            width=10, height=10, extent=Extent(0.0, 10.0, 0.0, 10.0),
            resolution_x=1.0, resolution_y=1.0,
        )

    def test_output_with_no_valid_pixels_is_rejected(self):
        output = self._path("all_nodata_output.tif")
        self._create_raster(output, 10, 10, nodata=-9999.0, fill=-9999.0)
        with self.assertRaisesRegex(RuntimeError, "유효 픽셀"):
            AlignExportDialog._validate_warp_output(
                QObject(), output, "non-overlapping source", self._contract(self._unit_grid()))

    def test_validation_reports_the_sampled_valid_pixel_share(self):
        half = self._path("half_valid_output.tif")
        self._create_raster(half, 10, 10, nodata=-9999.0, fill=-9999.0, valid_rows=5)
        pct = AlignExportDialog._validate_warp_output(
            QObject(), half, "half covered", self._contract(self._unit_grid()))
        self.assertIsNotNone(pct)
        self.assertAlmostEqual(pct, 50.0, delta=1.0)

        full = self._path("full_valid_output.tif")
        self._create_raster(full, 10, 10, nodata=-9999.0)
        pct = AlignExportDialog._validate_warp_output(
            QObject(), full, "fully covered", self._contract(self._unit_grid()))
        self.assertAlmostEqual(pct, 100.0, delta=0.01)

    # -- circular / source CRS ------------------------------------------------

    def test_nearest_with_float32_keeps_directions_and_continuous_nodata(self):
        # The aspect path: nearest like a class raster (no invented
        # directions) but Float32 with -9999, unlike a class raster which
        # keeps its band type and its own NoData.
        source = self._create_class_raster(
            self._path("aspect_like_source.tif"), nodata=None,
            codes=(0, 90, 180, 270), gdal_type=gdal.GDT_Int16)
        output = self._path("aspect_like_out.tif")
        progress = QtWidgets.QProgressDialog("", "", 0, 1)
        self.addCleanup(progress.close)
        AlignExportDialog._warp(
            QObject(), source, output, 2.0, "0,10,0,10", "EPSG:32652",
            nearest=True, nodata=-9999.0, progress=progress, force_float32=True,
        )
        band = gdal.Open(output).GetRasterBand(1)
        self.assertEqual(band.DataType, gdal.GDT_Float32)
        self.assertAlmostEqual(float(band.GetNoDataValue()), -9999.0, places=6)
        values = set(band.ReadAsArray().ravel().tolist()) - {-9999.0}
        self.assertTrue(values <= {0.0, 90.0, 180.0, 270.0},
                        msg=f"resampling invented directions: {sorted(values)}")

    def test_warp_accepts_the_layers_effective_source_crs(self):
        # A CRS assigned in Layer Properties never reaches the file; the warp
        # is handed it as SOURCE_CRS so gdalwarp does not fall back to the
        # file's own tag. Here both agree, so the output must simply be valid.
        source = self._path("source_crs_source.tif")
        output = self._path("source_crs_out.tif")
        self._create_raster(source, 20, 20)
        progress = QtWidgets.QProgressDialog("", "", 0, 1)
        self.addCleanup(progress.close)
        AlignExportDialog._warp(
            QObject(), source, output, 1.0, "0,10,0,10", "EPSG:32652",
            nearest=False, nodata=-9999.0, progress=progress,
            source_crs=QgsCoordinateReferenceSystem("EPSG:32652"),
        )
        pct = AlignExportDialog._validate_warp_output(
            QObject(), output, "source crs", self._contract(self._unit_grid()))
        self.assertAlmostEqual(pct, 100.0, delta=0.01)

    # -- categorical NoData -------------------------------------------------
    #
    # A class raster exported with no NoData value disables the consumer's own
    # safety net: the nodata mask gets guessed from the array, so nothing can
    # report presence points landing on padding. These tests cover the decision
    # made before the warp, which is where the value is chosen.

    def _create_class_raster(self, path, *, nodata=None, codes=(1, 2, 3),
                             gdal_type=None):
        """A small integer-coded raster, optionally without a NoData value."""
        dataset = gdal.GetDriverByName("GTiff").Create(
            path, 10, 10, 1, gdal_type or gdal.GDT_Int32,
        )
        self.assertIsNotNone(dataset)
        dataset.SetProjection(self._spatial_reference().ExportToWkt())
        dataset.SetGeoTransform((0, 1, 0, 10, 0, -1))
        band = dataset.GetRasterBand(1)
        if nodata is not None:
            band.SetNoDataValue(nodata)
        band.Fill(codes[0])
        array = band.ReadAsArray()
        for index, code in enumerate(codes):
            array[index % array.shape[0], :] = code
        band.WriteArray(array)
        dataset = None
        return path

    def test_categorical_source_nodata_is_reused_not_replaced(self):
        path = self._create_class_raster(self._path("cls_with_nodata.tif"), nodata=0)
        layer = QgsRasterLayer(path, "class with nodata")
        self.assertTrue(layer.isValid())
        value, reason = _categorical_output_nodata(layer)
        self.assertEqual(reason, "source")
        self.assertEqual(value, 0.0)

    def test_categorical_without_nodata_gets_a_sentinel_outside_the_codes(self):
        # The KIGAM shape: integer lithology codes, no NoData declared.
        path = self._create_class_raster(
            self._path("cls_no_nodata.tif"), nodata=None, codes=(1, 2, 3, 47))
        layer = QgsRasterLayer(path, "class without nodata")
        self.assertTrue(layer.isValid())
        value, reason = _categorical_output_nodata(layer)
        self.assertEqual(reason, "sentinel")
        self.assertIsNotNone(value)
        self.assertFalse(1 <= value <= 47,
                         msg=f"sentinel {value} collides with a class code in use")

    def test_warp_stamps_the_chosen_nodata_onto_a_categorical_output(self):
        source = self._create_class_raster(
            self._path("cls_warp_source.tif"), nodata=None, codes=(1, 2, 3))
        output = self._path("cls_warp_out.tif")
        layer = QgsRasterLayer(source, "class warp source")
        value, _reason = _categorical_output_nodata(layer)
        self.assertIsNotNone(value)

        progress = QtWidgets.QProgressDialog("", "", 0, 1)
        self.addCleanup(progress.close)
        AlignExportDialog._warp(
            QObject(),
            source,
            output,
            1.0,
            "0,10,0,10",
            "EPSG:32652",
            nearest=True,
            nodata=value,
            progress=progress,
        )
        written = gdal.Open(output)
        self.assertIsNotNone(written)
        self.assertIsNotNone(
            written.GetRasterBand(1).GetNoDataValue(),
            msg="categorical output must carry an explicit NoData value",
        )
        self.assertAlmostEqual(
            float(written.GetRasterBand(1).GetNoDataValue()), float(value), places=6)
        written = None

    def test_nearest_resampling_keeps_class_codes_integral(self):
        # The corruption this whole path exists to prevent: bilinear on codes
        # 1/2/3 yields 1.5 and 2.5, values that are not classes.
        source = self._create_class_raster(
            self._path("cls_integral_source.tif"), nodata=0, codes=(1, 2, 3))
        output = self._path("cls_integral_out.tif")
        progress = QtWidgets.QProgressDialog("", "", 0, 1)
        self.addCleanup(progress.close)
        AlignExportDialog._warp(
            QObject(), source, output, 2.0, "0,10,0,10", "EPSG:32652",
            nearest=True, nodata=0.0, progress=progress,
        )
        band = gdal.Open(output).GetRasterBand(1)
        array = band.ReadAsArray()
        nodata = band.GetNoDataValue()
        valid = array[array != nodata] if nodata is not None else array.ravel()
        for value in set(valid.ravel().tolist()):
            self.assertEqual(float(value), float(int(value)),
                             msg=f"non-integral class code {value} after resampling")


if __name__ == "__main__":
    unittest.main()
