"""QGIS integration tests for the align/export review fixes.

Covered here, each pinned by driving the real dialog (``_on_run``) headlessly:

* an AOI clip is widened to whole reference cells, so every output cell
  coincides with a reference cell and the reference DEM round-trips exactly;
* NoData that exists only on the project layer (Layer Properties, or a tool's
  ``setNoDataValue`` on the open layer) reaches gdalwarp as ``-srcnodata``
  instead of being blended as data;
* a source with no CRS in the file and none on the layer is refused;
* a float-typed class raster with no NoData gets -9999 rather than 0-padding.

The dependency-free CI discovers this module but skips it when PyQGIS or the
QGIS ``processing`` plugin is unavailable.  Run it with QGIS' Python:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=/usr/share/qgis/python/plugins \\
        python3 -m unittest tests.test_align_export_review -v
"""

from __future__ import annotations

import csv
import glob
import json
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("ARCHTOOLKIT_NO_DIALOG_MEMORY", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
    import numpy as np
    from osgeo import gdal, osr
    from qgis.PyQt import QtWidgets
    from qgis.PyQt.QtCore import QCoreApplication, Qt
    from qgis.core import (
        QgsApplication,
        QgsFeature,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsRasterLayer,
        QgsRasterRange,
        QgsVectorLayer,
    )

    from processing.core.Processing import Processing
    from tools.align_export_dialog import (
        AlignExportDialog,
        _categorical_output_nodata,
        _effective_source_nodata,
        _srcnodata_argument,
        snap_extent_outward_to_lattice,
    )
    from tools.raster_grid_contract import Extent, GridContractError
    from tools.utils import set_archtoolkit_layer_metadata

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc


class _FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, *args, **kwargs):
        self.messages.append(tuple(str(a) for a in args))


class _FakeIface:
    """Just enough of QgisInterface for AlignExportDialog."""

    def __init__(self):
        self._bar = _FakeMessageBar()
        self._window = QtWidgets.QMainWindow()

    def messageBar(self):
        return self._bar

    def mainWindow(self):
        return self._window

    def mapCanvas(self):
        return None


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class AlignExportReviewTests(unittest.TestCase):
    REF_ORIGIN = (200000.0, 500000.0)
    REF_PX = 10.0
    # A second, coarser grid whose origin is off the reference lattice.
    GT15 = (200005.0, 15.0, 0.0, 499995.0, 0.0, -15.0)

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

    # No tearDownClass: one QgsApplication per process (see test_align_export_qgis).

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="archtoolkit_align_review_")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        self.addCleanup(QgsProject.instance().removeAllMapLayers)
        self.iface = _FakeIface()

    # -- fixtures -------------------------------------------------------------

    def _path(self, name):
        return os.path.join(self.temp_dir, name)

    @staticmethod
    def _wkt(epsg=5186):
        spatial_ref = osr.SpatialReference()
        spatial_ref.ImportFromEPSG(epsg)
        return spatial_ref.ExportToWkt()

    def _write_raster(self, path, array, geotransform, *, nodata=None, gdal_type=None, wkt=None):
        array = np.asarray(array)
        rows, cols = array.shape
        dataset = gdal.GetDriverByName("GTiff").Create(
            path, int(cols), int(rows), 1, gdal_type or gdal.GDT_Float32)
        self.assertIsNotNone(dataset)
        dataset.SetGeoTransform(geotransform)
        if wkt is None:
            wkt = self._wkt()
        if wkt:
            dataset.SetProjection(wkt)
        band = dataset.GetRasterBand(1)
        if nodata is not None:
            band.SetNoDataValue(float(nodata))
        band.WriteArray(array)
        band.FlushCache()
        dataset = None
        return path

    def _reference_dem(self):
        """A 60x60, 10 m ridge DEM on the reference lattice, with many distinct values."""
        rows, cols = np.mgrid[0:60, 0:60].astype(np.float64)
        z = 100.0 + 40.0 * np.exp(-((cols - 30.0) ** 2) / (2 * 10.0 ** 2)) + 0.5 * rows
        path = self._write_raster(
            self._path("dem.tif"), z.astype(np.float32),
            (self.REF_ORIGIN[0], self.REF_PX, 0.0, self.REF_ORIGIN[1], 0.0, -self.REF_PX),
            nodata=-9999.0)
        return path, z.astype(np.float32)

    def _add_raster(self, path, name, meta=None):
        layer = QgsRasterLayer(path, name, "gdal")
        self.assertTrue(layer.isValid(), path)
        QgsProject.instance().addMapLayer(layer)
        if meta:
            set_archtoolkit_layer_metadata(layer, run_id="review", **meta)
        return layer

    def _add_polygon(self, name, ring, epsg=5186):
        layer = QgsVectorLayer(f"Polygon?crs=EPSG:{epsg}", name, "memory")
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in ring]]))
        layer.dataProvider().addFeatures([feature])
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        return layer

    def _run(self, reference, layers, *, aoi=None, px=0.0):
        """Drive the dialog; return the published stack (or None) and the messages."""
        export_dir = self._path("export")
        os.makedirs(export_dir, exist_ok=True)
        dialog = AlignExportDialog(self.iface)
        self.addCleanup(dialog.close)
        dialog.cmbRef.setLayer(reference)
        dialog.cmbAoi.setLayer(aoi)
        dialog.spinPixel.setValue(px)
        wanted = {layer.id() for layer in layers}
        for index in range(dialog.listLayers.count()):
            item = dialog.listLayers.item(index)
            if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                continue
            checked = str(item.data(Qt.ItemDataRole.UserRole)) in wanted
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        dialog.chkAddToProject.setChecked(False)
        dialog.txtExport.setText(export_dir)
        dialog._on_run()
        QCoreApplication.processEvents()
        result = {
            "messages": [" | ".join(m) for m in self.iface.messageBar().messages],
            "leftovers": sorted(os.listdir(export_dir)),
            "stack_dir": None,
        }
        stacks = sorted(glob.glob(os.path.join(export_dir, "aligned_stack_*")))
        if stacks:
            stack_dir = stacks[-1]
            result["stack_dir"] = stack_dir
            with open(os.path.join(stack_dir, "aligned_stack_manifest.csv"), encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
            result["manifest"] = {row[0]: dict(zip(rows[0], row)) for row in rows[1:]}
            with open(os.path.join(stack_dir, "aligned_stack_grid.json"), encoding="utf-8") as f:
                result["grid"] = json.load(f)
        return result

    @staticmethod
    def _read(path):
        dataset = gdal.Open(path)
        band = dataset.GetRasterBand(1)
        out = {
            "gt": dataset.GetGeoTransform(),
            "size": (dataset.RasterXSize, dataset.RasterYSize),
            "nodata": band.GetNoDataValue(),
            "dtype": gdal.GetDataTypeName(band.DataType),
            "array": band.ReadAsArray(),
        }
        dataset = None
        return out

    # -- fix 1: AOI on the reference lattice ----------------------------------

    def test_aoi_extent_is_widened_to_whole_reference_cells(self):
        snapped = snap_extent_outward_to_lattice(
            Extent(200123.4, 200456.7, 499456.7, 499876.5), 200000.0, 500000.0, 10.0)
        self.assertEqual(
            (snapped.xmin, snapped.xmax, snapped.ymin, snapped.ymax),
            (200120.0, 200460.0, 499450.0, 499880.0))
        # A pixel-size override still anchors on the reference's upper-left corner.
        snapped = snap_extent_outward_to_lattice(
            Extent(200123.4, 200456.7, 499456.7, 499876.5), 200000.0, 500000.0, 25.0)
        self.assertEqual(
            (snapped.xmin, snapped.xmax, snapped.ymin, snapped.ymax),
            (200100.0, 200475.0, 499450.0, 499900.0))
        # Float noise left by a CRS transform must not add a row or column.
        snapped = snap_extent_outward_to_lattice(
            Extent(200100.00000000003, 200400.00000000003, 499500.000000001, 499800.000000001),
            200000.0, 500000.0, 10.0)
        self.assertEqual(
            (snapped.xmin, snapped.xmax, snapped.ymin, snapped.ymax),
            (200100.0, 200400.0, 499500.0, 499800.0))
        # An AOI thinner than a cell still yields one whole cell.
        snapped = snap_extent_outward_to_lattice(Extent(200101.0, 200102.0, 499901.0, 499902.0), 200000.0, 500000.0, 10.0)
        self.assertEqual(
            (snapped.xmin, snapped.xmax, snapped.ymin, snapped.ymax),
            (200100.0, 200110.0, 499900.0, 499910.0))
        with self.assertRaises(GridContractError):
            snap_extent_outward_to_lattice(Extent(0.0, 1.0, 0.0, 1.0), 0.0, 0.0, 0.0)

    def test_aoi_run_keeps_reference_cells_and_round_trips_the_dem(self):
        dem_path, dem_values = self._reference_dem()
        dem = self._add_raster(dem_path, "dem", {"tool_id": "terrain_analysis", "kind": "dem", "units": "m"})
        slope = self._add_raster(
            self._write_raster(self._path("slope15.tif"), np.full((40, 40), 12.5, np.float32), self.GT15, nodata=-9999.0),
            "slope", {"tool_id": "terrain_analysis", "kind": "slope", "units": "deg"})
        aoi = self._add_polygon("aoi", [
            (200123.4, 499456.7), (200456.7, 499456.7), (200456.7, 499876.5), (200123.4, 499876.5), (200123.4, 499456.7)])

        result = self._run(dem, [dem, slope], aoi=aoi)
        self.assertIsNotNone(result["stack_dir"], result["messages"])

        written = self._read(os.path.join(result["stack_dir"], "dem.tif"))
        origin_x, origin_y = written["gt"][0], written["gt"][3]
        self.assertAlmostEqual((origin_x - self.REF_ORIGIN[0]) % self.REF_PX, 0.0, places=6)
        self.assertAlmostEqual((self.REF_ORIGIN[1] - origin_y) % self.REF_PX, 0.0, places=6)
        self.assertEqual((origin_x, origin_y), (200120.0, 499880.0))
        self.assertEqual(written["size"], (34, 43))
        # Every output cell is a reference cell, so the DEM comes back untouched.
        col0, row0 = 12, 12
        self.assertTrue(np.array_equal(written["array"], dem_values[row0:row0 + 43, col0:col0 + 34]),
                        msg="reference DEM was resampled under an AOI clip")
        self.assertEqual(written["array"].shape, (43, 34))

        grid = result["grid"]
        self.assertEqual(grid["requested_extent"], {"xmin": 200120.0, "xmax": 200460.0, "ymin": 499450.0, "ymax": 499880.0})
        self.assertEqual(grid["actual_extent"], grid["requested_extent"])
        self.assertEqual(grid["aoi_extent"], {"xmin": 200123.4, "xmax": 200456.7, "ymin": 499456.7, "ymax": 499876.5})
        self.assertEqual(result["manifest"]["dem"]["valid_pct"], "100.0")

    # -- fix 2: layer-only NoData ---------------------------------------------

    def _holed_layer(self, name):
        """Float32 raster, no file NoData, with a -32768 hole."""
        values = np.full((40, 40), 50.0, np.float32)
        values[15:25, 15:25] = -32768.0
        path = self._write_raster(self._path(f"{name}.tif"), values, self.GT15, nodata=None)
        return self._add_raster(path, name, {"tool_id": "terrain_analysis", "kind": "dem", "units": "m"})

    def _assert_hole_is_nodata(self, result, variable):
        self.assertIsNotNone(result["stack_dir"], result["messages"])
        written = self._read(os.path.join(result["stack_dir"], f"{variable}.tif"))
        values = set(np.unique(written["array"]).tolist())
        self.assertTrue(values <= {50.0, -9999.0}, msg=f"NoData was blended into data: {sorted(values)[:6]}")
        hole_cells = int((written["array"] == -9999.0).sum())
        # A 150 m x 150 m hole on the 10 m grid is 225 cells; bilinear masking
        # may widen it by a ring but never shrinks it.
        self.assertGreaterEqual(hole_cells, 225)
        row = result["manifest"][variable]
        self.assertEqual(row["nodata"], "-9999.0")
        self.assertLess(float(row["valid_pct"]), 100.0)
        self.assertAlmostEqual(float(row["valid_pct"]), 100.0 * (3600 - hole_cells) / 3600.0, delta=1.0)

    def test_user_nodata_from_layer_properties_is_masked_not_blended(self):
        dem_path, _ = self._reference_dem()
        dem = self._add_raster(dem_path, "dem", {"tool_id": "terrain_analysis", "kind": "dem", "units": "m"})
        holed = self._holed_layer("holed")
        holed.dataProvider().setUserNoDataValue(1, [QgsRasterRange(-32768.0, -32768.0)])
        self.assertFalse(holed.dataProvider().sourceHasNoDataValue(1))
        self._assert_hole_is_nodata(self._run(dem, [holed]), "dem")

    def test_provider_set_nodata_on_the_open_layer_is_masked_not_blended(self):
        # The way the plugin's own tools mark NoData on a layer they just
        # created; this QGIS does not write it back to the file.
        dem_path, _ = self._reference_dem()
        dem = self._add_raster(dem_path, "dem", {"tool_id": "terrain_analysis", "kind": "dem", "units": "m"})
        holed = self._holed_layer("holed")
        self.assertTrue(holed.dataProvider().setNoDataValue(1, -32768.0))
        reopened = QgsRasterLayer(holed.source(), "reopened", "gdal")
        self.assertFalse(reopened.dataProvider().sourceHasNoDataValue(1), "fixture: NoData reached the file")
        self._assert_hole_is_nodata(self._run(dem, [holed]), "dem")

    def test_file_nodata_needs_no_explicit_srcnodata(self):
        # An explicit -srcnodata switches on unified multi-band masking, so it
        # must only be sent for a value the file lacks.
        path = self._write_raster(self._path("tagged.tif"), np.full((40, 40), 1.0, np.float32), self.GT15, nodata=-9999.0)
        layer = self._add_raster(path, "tagged")
        self.assertIsNone(_effective_source_nodata(layer, path))
        layer.dataProvider().setUserNoDataValue(1, [QgsRasterRange(7.0, 7.0)])
        with self.assertRaisesRegex(RuntimeError, "여러 개"):
            _effective_source_nodata(layer, path)
        self.assertEqual(_srcnodata_argument(None), "")
        self.assertEqual(_srcnodata_argument((-32768.0,)), "-srcnodata -32768.0")
        self.assertEqual(_srcnodata_argument((-1.0, -2.0)), '-srcnodata "-1.0 -2.0"')

    def test_user_nodata_range_is_refused_before_anything_is_published(self):
        dem_path, _ = self._reference_dem()
        dem = self._add_raster(dem_path, "dem", {"tool_id": "terrain_analysis", "kind": "dem", "units": "m"})
        holed = self._holed_layer("holed")
        holed.dataProvider().setUserNoDataValue(1, [QgsRasterRange(-32768.0, -32000.0)])
        result = self._run(dem, [holed])
        self.assertIsNone(result["stack_dir"])
        self.assertEqual(result["leftovers"], [], "staging directory was left behind")
        self.assertTrue(any("범위" in m and "holed" in m for m in result["messages"]), result["messages"])

    # -- fix 3: CRS-less source ------------------------------------------------

    def test_source_without_any_crs_is_refused(self):
        dem_path, _ = self._reference_dem()
        dem = self._add_raster(dem_path, "dem", {"tool_id": "terrain_analysis", "kind": "dem", "units": "m"})
        bare = self._add_raster(
            self._write_raster(self._path("nocrs.tif"), np.full((40, 40), 3.0, np.float32), self.GT15, nodata=-9999.0, wkt=""),
            "bare_raster", {"tool_id": "terrain_analysis", "kind": "tri", "units": "index"})
        self.assertFalse(bare.crs().isValid())
        result = self._run(dem, [dem, bare])
        self.assertIsNone(result["stack_dir"])
        self.assertEqual(result["leftovers"], [])
        self.assertTrue(any("좌표계" in m and "bare_raster" in m for m in result["messages"]), result["messages"])

    # -- fix 4: float class raster without NoData -----------------------------

    def _float_class_layer(self):
        codes = np.where(np.arange(400).reshape(20, 20) % 2 == 0, 0.0, 3.0).astype(np.float32)
        path = self._write_raster(
            self._path("float_class.tif"), codes, (200100.0, 15.0, 0.0, 499900.0, 0.0, -15.0), nodata=None)
        layer = self._add_raster(path, "float_class", {"tool_id": "kigam_raster", "kind": "geology_class", "units": "class"})
        return layer, codes

    def test_float_class_raster_without_nodata_gets_minus_9999(self):
        layer, codes = self._float_class_layer()
        value, reason = _categorical_output_nodata(layer)
        self.assertEqual((value, reason), (-9999.0, "sentinel"))

        dem_path, _ = self._reference_dem()
        dem = self._add_raster(dem_path, "dem", {"tool_id": "terrain_analysis", "kind": "dem", "units": "m"})
        result = self._run(dem, [layer])
        self.assertIsNotNone(result["stack_dir"], result["messages"])
        written = self._read(os.path.join(result["stack_dir"], "geology_class.tif"))
        self.assertEqual(written["dtype"], "Float32")
        self.assertEqual(written["nodata"], -9999.0)
        self.assertEqual(set(np.unique(written["array"]).tolist()), {-9999.0, 0.0, 3.0})
        # Padding is NoData now, so class 0 keeps exactly its own cells. The
        # 300 m x 300 m source covers 900 cells of the 10 m grid. Its codes
        # alternate 0/3 in 15 m columns; the 10 m cell centres at 5, 15, 25 m of
        # each 30 m period pick source columns 0, 1, 1, so a third is class 0.
        # Before the fix all 2700 padding cells also read as class 0.
        self.assertEqual(int((written["array"] != -9999.0).sum()), 900)
        self.assertEqual(int((written["array"] == 0.0).sum()), 300)
        self.assertEqual(result["manifest"]["geology_class"]["nodata"], "-9999.0")
        self.assertEqual(result["manifest"]["geology_class"]["categorical"], "yes")


if __name__ == "__main__":
    unittest.main()
