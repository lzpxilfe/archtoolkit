"""Correctness pins for 지형 분석 / 경사도·사면방향 도면화 (review round 2).

Each test reproduces a wrong output found in review:
- TPI for a radius of 2+ cells came from a block average + bilinear resample:
  exact only at block centres, 3x the true TPI on average on a paraboloid,
  and the Weiss landform classes built on it disagreed with the stated rule
  on about a quarter of the cells;
- the standalone TPI layer kept the greyed-out manual threshold when 자동 SD
  was on;
- the aspect layer wrote 0 for flats, DEM NoData and the border (0 is due
  north) with no NoData value, so a clipped DEM's collar rendered as "평탄";
- curvature used one mean cell size on non-square pixels;
- the drafting tool deleted every drafting result (old and new) on a run
  after anything was placed above its layer-tree group;
- the drafting "경사도 단계" did not change the zones, and rounding before
  binning put 9.6 deg into the 10-15 class;
- drafting memory layers were built from the CRS authid, so a DEM in a
  custom CRS (no authid) produced CRS-less AOI/zone/arrow layers;
- legend/metadata text: Weiss "Incised Valley"/"Steep Ridge", TRI legend
  breaks printed as "0-0", TPI/TRI/roughness recorded as "index" not metres.

The dependency-free CI discovers this module; the NumPy part runs anywhere
NumPy is installed and the QGIS part skips when PyQGIS is not importable.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

from tools import terrain_math

QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
    from osgeo import gdal, osr
    from qgis.PyQt import QtWidgets
    from qgis.core import (
        QgsApplication,
        QgsFeature,
        QgsField,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsRasterLayer,
        QgsVectorLayer,
    )

    from processing.core.Processing import Processing
    from tools.qtcompat import FT_STRING
    from tools.utils import get_archtoolkit_layer_metadata

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc


def _brute_tpi(z, radius, mask):
    """Reference TPI: centre minus the mean of its valid window neighbours."""
    rows, cols = z.shape
    out = np.full(z.shape, np.nan)
    for i in range(radius, rows - radius):
        for j in range(radius, cols - radius):
            if mask[i, j] or not np.isfinite(z[i, j]):
                continue
            vals = [z[i + a, j + b]
                    for a in range(-radius, radius + 1) for b in range(-radius, radius + 1)
                    if (a or b) and not mask[i + a, j + b] and np.isfinite(z[i + a, j + b])]
            if vals:
                out[i, j] = z[i, j] - float(np.mean(vals))
    return out


class FocalTpiMathTests(unittest.TestCase):
    """terrain_math.focal_tpi / focal_tpi_strips / mark_flat_aspect, NumPy only."""

    def test_matches_a_brute_force_loop_with_nodata_and_nan(self):
        rng = np.random.default_rng(11)
        z = rng.normal(500.0, 25.0, size=(31, 27))
        mask = rng.random(z.shape) < 0.12
        z[5, 7] = np.nan
        for radius in (1, 2, 3, 5):
            got = terrain_math.focal_tpi(z, radius, nodata_mask=mask)
            want = _brute_tpi(z, radius, mask)
            self.assertTrue(np.array_equal(np.isnan(got), np.isnan(want)), msg=f"r={radius}")
            self.assertLess(float(np.nanmax(np.abs(got - want))), 1e-9, msg=f"r={radius}")

    def test_paraboloid_gives_the_closed_form_everywhere(self):
        # z = a(x^2+y^2): the mean of the window WITHOUT its centre is
        # z_c + 2aL^2 r(r+1)/3 * N/(N-1), N=(2r+1)^2 - the same at every cell.
        # The old block-average path gave -0.4 to -1.6 m here at r=2 (mean 3x).
        a, px, n = 0.001, 10.0, 60
        rows, cols = np.mgrid[0:n, 0:n].astype(float)
        z = 500.0 + a * (((cols - 30) * px) ** 2 + ((rows - 30) * px) ** 2)
        for radius in (2, 3, 6):
            side = 2 * radius + 1
            want = -2.0 * a * px * px * radius * (radius + 1) / 3.0 * side * side / (side * side - 1)
            got = terrain_math.focal_tpi(z, radius)[radius:-radius, radius:-radius]
            self.assertLess(float(np.max(np.abs(got - want))), 1e-9, msg=f"r={radius}")
        self.assertAlmostEqual(-2.0 * a * 100 * 2 * 3 / 3.0 * 25 / 24, -0.4166666, places=6)

    def test_border_and_nodata_cells_are_nan(self):
        z = np.full((10, 10), 10.0)
        z[5, 5] = 9999.0
        mask = np.zeros(z.shape, dtype=bool)
        mask[5, 5] = True
        got = terrain_math.focal_tpi(z, 2, nodata_mask=mask)
        self.assertTrue(np.all(np.isnan(got[:2, :])) and np.all(np.isnan(got[-2:, :])))
        self.assertTrue(np.all(np.isnan(got[:, :2])) and np.all(np.isnan(got[:, -2:])))
        self.assertTrue(np.isnan(got[5, 5]))
        # The 9999 NoData value neither leaks into its neighbour's mean nor
        # voids the neighbour: it is left out of both the sum and the count.
        self.assertAlmostEqual(float(got[5, 4]), 0.0, places=9)

    def test_strips_reproduce_the_whole_grid(self):
        rng = np.random.default_rng(5)
        z = rng.normal(100.0, 10.0, size=(43, 17)).astype(np.float32)
        z[10:13, 4:6] = -9999.0
        out = np.full(z.shape, 123.0)

        def _write(first, block):
            out[first:first + block.shape[0], :] = block

        terrain_math.focal_tpi_strips(z.shape[0], z.shape[1], 3, lambda lo, hi: z[lo:hi],
                                      _write, nodata=-9999.0, block_rows=4)
        whole = terrain_math.focal_tpi(z, 3, nodata_mask=(z == -9999.0))
        self.assertTrue(np.array_equal(np.isnan(out), np.isnan(whole)))
        self.assertLess(float(np.nanmax(np.abs(out - whole))), 1e-9)

    def test_radius_one_is_gdaldem_tpi(self):
        try:
            from osgeo import gdal as _gdal
        except ImportError:  # pragma: no cover - GDAL-free CI
            self.skipTest("GDAL unavailable")
        rng = np.random.default_rng(2)
        z = rng.normal(0.0, 5.0, size=(16, 16)).astype(np.float32)
        ds = _gdal.GetDriverByName("MEM").Create("", 16, 16, 1, _gdal.GDT_Float32)
        ds.SetGeoTransform((0, 1, 0, 0, 0, -1))
        ds.GetRasterBand(1).WriteArray(z)
        ref = _gdal.DEMProcessing("/vsimem/tpi_review2.tif", ds, "TPI").ReadAsArray().astype(float)
        _gdal.Unlink("/vsimem/tpi_review2.tif")
        got = terrain_math.focal_tpi(z, 1)
        self.assertLess(float(np.max(np.abs(got[1:-1, 1:-1] - ref[1:-1, 1:-1]))), 1e-5)

    def test_curvature_uses_separate_x_and_y_spacing(self):
        # z = 0.5 k x^2 + 0.05 y on 10 x 5 m pixels; profile = k p^2/(p^2+q^2).
        k, px, py = 0.004, 10.0, 5.0
        rows, cols = np.mgrid[0:31, 0:31].astype(float)
        x = (cols - 15) * px
        y = -(rows - 15) * py
        z = 1000.0 + 0.5 * k * x * x + 0.05 * y
        profile, plan = terrain_math.zt_curvature(z, px, py)
        p, q = k * x[15, 20], 0.05
        self.assertAlmostEqual(float(profile[15, 20]), k * p * p / (p * p + q * q), places=9)
        self.assertAlmostEqual(float(plan[15, 20]), -(k * q * q) / (p * p + q * q), places=9)

    def test_mark_flat_aspect_separates_flat_nodata_and_north(self):
        aspect = np.array([
            [-9999, -9999, -9999, -9999, -9999],
            [-9999, 0.0, -9999, 90.0, -9999],
            [-9999, 180.0, -9999, -9999, -9999],
            [-9999, -9999, -9999, -9999, -9999],
        ], dtype=float)
        valid = np.ones(aspect.shape, dtype=bool)
        valid[2, 4] = False       # DEM NoData: (1,3), (2,3) touch it
        out = terrain_math.mark_flat_aspect(aspect, valid, -9999.0)
        self.assertEqual(out[1, 1], 0.0)                              # due north stays 0
        self.assertEqual(out[1, 2], terrain_math.ASPECT_FLAT_VALUE)   # full window -> flat
        self.assertEqual(out[2, 2], terrain_math.ASPECT_FLAT_VALUE)
        self.assertEqual(out[2, 3], -9999.0)                          # touches NoData
        self.assertEqual(out[0, 2], -9999.0)                          # border


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class _QgisCase(unittest.TestCase):
    ORIGIN_X = 200000.0
    ORIGIN_Y = 500000.0

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ["ARCHTOOLKIT_NO_DIALOG_MEMORY"] = "1"
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
        if QgsApplication.processingRegistry().algorithmById("gdal:slope") is None:
            raise unittest.SkipTest("QGIS GDAL provider is unavailable")
        cls._shim_gdal_calc()

    @classmethod
    def _shim_gdal_calc(cls):
        """Run QGIS's ``gdal_calc.py`` call under THIS interpreter.

        Same trick as tests/test_distance_raster_review.py: /usr/bin/gdal_calc.py
        may carry a shebang for a Python without osgeo. Only PATH is touched,
        and tearDownClass restores it.
        """
        cls._saved_path = os.environ.get("PATH", "")
        cls._shim_dir = None
        script = "/usr/bin/gdal_calc.py"
        if not os.path.exists(script):
            return
        cls._shim_dir = tempfile.mkdtemp(prefix="archtoolkit_terrain_shim_")
        shim = os.path.join(cls._shim_dir, "gdal_calc.py")
        with open(shim, "w", encoding="utf-8") as handle:
            handle.write(f"#!/bin/sh\nexec {sys.executable} {script} \"$@\"\n")
        os.chmod(shim, 0o755)
        os.environ["PATH"] = cls._shim_dir + os.pathsep + cls._saved_path

    @classmethod
    def tearDownClass(cls):
        # PATH only; the QgsApplication stays alive (see
        # tests/test_align_export_qgis.py).
        os.environ["PATH"] = getattr(cls, "_saved_path", os.environ.get("PATH", ""))
        if getattr(cls, "_shim_dir", None):
            shutil.rmtree(cls._shim_dir, True)

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="archtoolkit_terrain_review2_")
        QgsProject.instance().clear()
        self.iface = _FakeIface()

    def tearDown(self):
        QgsProject.instance().clear()
        shutil.rmtree(self.temp_dir, True)

    def _dem(self, name, z, px=10.0, py=None, nodata=-9999.0):
        py = px if py is None else py
        path = os.path.join(self.temp_dir, name)
        ds = gdal.GetDriverByName("GTiff").Create(path, z.shape[1], z.shape[0], 1, gdal.GDT_Float32)
        ds.SetGeoTransform((self.ORIGIN_X, px, 0.0, self.ORIGIN_Y, 0.0, -py))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(5186)
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        if nodata is not None:
            band.SetNoDataValue(nodata)
        band.WriteArray(np.asarray(z, dtype=np.float32))
        ds = None
        layer = QgsRasterLayer(path, name, "gdal")
        self.assertTrue(layer.isValid())
        QgsProject.instance().addMapLayer(layer)
        return layer

    @staticmethod
    def _read(layer):
        ds = gdal.Open(layer.source().split("|")[0])
        band = ds.GetRasterBand(1)
        return band.ReadAsArray().astype(float), band.GetNoDataValue()

    @staticmethod
    def _new_layers(before):
        out = {}
        for lid, lyr in QgsProject.instance().mapLayers().items():
            if lid in before:
                continue
            meta = get_archtoolkit_layer_metadata(lyr) or {}
            out.setdefault(meta.get("kind") or lyr.name(), []).append((lyr, meta))
        return out


class _FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, title, text, level=0, duration=0):
        self.messages.append((str(title), str(text)))


class _FakeIface:
    def __init__(self):
        self._bar = _FakeMessageBar()

    def messageBar(self):
        return self._bar

    def mainWindow(self):
        if not hasattr(self, "_window"):
            self._window = QtWidgets.QMainWindow()
        return self._window

    def mapCanvas(self):
        return None

    def setActiveLayer(self, _layer):
        return True


class TerrainDialogReview2Tests(_QgisCase):

    def _run(self, dem, checks, spins=None, auto_sd=False):
        from tools.terrain_analysis_dialog import TerrainAnalysisDialog
        dialog = TerrainAnalysisDialog(self.iface)
        dialog.cmbDemLayer.setLayer(dem)
        for name in ("chkSlope", "chkAspect", "chkTRI", "chkTPI", "chkRoughness",
                     "chkSlopePosition", "chkCurvature", "chkAspectDeriv"):
            getattr(dialog, name).setChecked(name in checks)
        dialog.chkAutoSD.setChecked(auto_sd)
        for name, value in (spins or {}).items():
            getattr(dialog, name).setValue(value)
        before = set(QgsProject.instance().mapLayers())
        dialog.run_analysis()
        QtWidgets.QApplication.processEvents()
        return self._new_layers(before)

    def test_radius_tpi_is_the_exact_focal_value_on_a_paraboloid(self):
        n, a = 60, 0.001
        rows, cols = np.mgrid[0:n, 0:n].astype(float)
        z = 500.0 + a * (((cols - 30) * 10.0) ** 2 + ((rows - 30) * 10.0) ** 2)
        layers = self._run(self._dem("bowl.tif", z), {"chkTPI"}, {"spinTPIRadius": 2})
        layer, meta = layers["tpi"][0]
        tpi, nodata = self._read(layer)
        inner = tpi[2:-2, 2:-2]
        # float32 output of ~500 m elevations: tolerance 1e-3 m.
        self.assertLess(float(np.max(np.abs(inner - (-0.4 * 25.0 / 24.0)))), 1e-3)
        self.assertTrue(np.all(tpi[:2, :] == nodata))
        self.assertEqual(meta["params"]["tpi_method"], "exact_focal_mean")
        self.assertEqual(meta["params"]["tpi_window"], "5x5")
        self.assertEqual(meta["units"], "m")
        self.assertNotIn("근사", layer.name())

    def test_weiss_classes_follow_the_rule_on_the_exact_tpi(self):
        n = 90
        rows, cols = np.mgrid[0:n, 0:n].astype(float)
        z = 300 + 30 * np.sin(cols / 9.0) * np.cos(rows / 11.0) + 12 * np.sin(cols / 4.3 + rows / 5.1)
        dem = self._dem("wave.tif", z)
        layers = self._run(dem, {"chkSlopePosition"}, {"spinTPIRadius": 3, "spinSlopeThreshold": 5},
                           auto_sd=True)
        classes, class_nd = self._read(layers["slope_position"][0][0])
        exact = terrain_math.focal_tpi(z.astype(np.float32), 3)
        slope_path = os.path.join(self.temp_dir, "slope.tif")
        gdal.DEMProcessing(slope_path, dem.source(), "slope")
        slope = gdal.Open(slope_path).ReadAsArray().astype(float)
        ok = np.isfinite(exact) & (slope != -9999) & (classes != class_nd)
        sd = float(np.std(exact[ok]))
        want = np.zeros(z.shape, dtype=int)
        want[exact < -sd] = 1
        want[(exact >= -sd) & (exact < -sd / 2)] = 2
        want[(exact >= -sd / 2) & (exact <= sd / 2) & (slope <= 5)] = 3
        want[(exact >= -sd / 2) & (exact <= sd / 2) & (slope > 5)] = 4
        want[(exact > sd / 2) & (exact <= sd)] = 5
        want[exact > sd] = 6
        agreement = float(np.mean(want[ok] == classes[ok]))
        # The block-average TPI agreed on ~77% of cells.
        self.assertGreater(agreement, 0.999)

    def test_tpi_layer_uses_the_auto_sd_threshold_it_names(self):
        n = 80
        rows, cols = np.mgrid[0:n, 0:n].astype(float)
        z = 300 + 20 * np.sin(cols / 7.0) * np.cos(rows / 8.0)
        spins = {"spinTPIRadius": 3, "spinTPIThreshold": 1.0}
        layers = self._run(self._dem("autosd.tif", z), {"chkTPI"}, spins, auto_sd=True)
        layer, meta = layers["tpi"][0]
        tpi, nodata = self._read(layer)
        sd = float(np.std(tpi[tpi != nodata]))
        self.assertEqual(meta["params"]["threshold_mode"], "auto_sd")
        self.assertAlmostEqual(meta["params"]["threshold"], sd, places=3)
        self.assertIn(f"±{sd:.2f}", layer.name())
        items = layer.renderer().shader().rasterShaderFunction().colorRampItemList()
        self.assertAlmostEqual(items[0].value, -sd, places=3)

    def test_aspect_keeps_nodata_and_flats_apart_from_north(self):
        n = 40
        rows, cols = np.mgrid[0:n, 0:n].astype(float)
        z = 500 + 3.0 * rows                   # faces due north (aspect 0)
        z[10:20, 10:20] = 530.0                # flat plateau
        z[:, 35:] = -9999.0                    # clipped collar
        layers = self._run(self._dem("aspect.tif", z), {"chkAspect"})
        layer, meta = layers["aspect"][0]
        aspect, nodata = self._read(layer)
        self.assertEqual(nodata, -9999.0)
        self.assertTrue(np.all(aspect[:, 35:] == nodata))
        self.assertTrue(np.all(aspect[0, :] == nodata))
        self.assertTrue(np.all(aspect[12:18, 12:18] == terrain_math.ASPECT_FLAT_VALUE))
        self.assertEqual(aspect[30, 5], 0.0)
        self.assertFalse(meta["params"]["zero_flat"])
        self.assertFalse(meta["params"]["compute_edges"])
        shader = layer.renderer().shader().rasterShaderFunction()

        def label_of(value):
            return [item.label for item in shader.colorRampItemList() if item.value >= value][0]

        self.assertIn("평탄", label_of(terrain_math.ASPECT_FLAT_VALUE))
        self.assertTrue(label_of(0.0).startswith("N |"))
        self.assertTrue(label_of(350.0).startswith("N |"))
        self.assertTrue(label_of(10.0).startswith("N |"))

    def test_curvature_on_non_square_pixels(self):
        k = 0.004
        rows, cols = np.mgrid[0:31, 0:31].astype(float)
        x = (cols - 15) * 10.0
        y = -(rows - 15) * 5.0
        z = 1000 + 0.5 * k * x * x + 0.05 * y
        layers = self._run(self._dem("ns.tif", z, px=10.0, py=5.0), {"chkCurvature"})
        profile, _nd = self._read(layers["curvature_profile"][0][0])
        p, q = k * x[15, 20], 0.05
        # The mean cell size gave 0.00700 here instead of 0.00376.
        self.assertAlmostEqual(float(profile[15, 20]), k * p * p / (p * p + q * q), places=4)

    def test_large_radius_is_exact_and_only_a_too_small_dem_falls_back(self):
        rows, cols = np.mgrid[0:60, 0:60].astype(float)
        z = 100 + 40 * np.exp(-((cols - 30) ** 2) / 200.0) + 0.5 * rows
        dem = self._dem("small.tif", z)
        layers = self._run(dem, {"chkTPI"}, {"spinTPIRadius": 15})
        layer, meta = layers["tpi"][0]
        self.assertEqual(meta["params"]["radius"], 15)
        self.assertEqual(meta["params"]["tpi_window"], "31x31")
        tpi, nodata = self._read(layer)
        self.assertEqual(int(np.sum(tpi != nodata)), 30 * 30)
        layers = self._run(dem, {"chkTPI"}, {"spinTPIRadius": 30})
        layer, meta = layers["tpi"][0]
        self.assertEqual(meta["params"]["radius"], 1)
        self.assertIn("3x3", layer.name())
        self.assertTrue(any("3x3 TPI로 대체" in text for _title, text in self.iface.messageBar().messages))

    def test_labels_and_units(self):
        from tools.terrain_analysis_dialog import TerrainAnalysisDialog
        labels = [c["label"] for c in TerrainAnalysisDialog.SLOPE_POSITION_CLASSES]
        self.assertIn("(Valley)", labels[0])
        self.assertIn("(Ridge)", labels[5])
        self.assertFalse(any("Incised" in t or "Steep" in t for t in labels))
        tri = [c["label"] for c in TerrainAnalysisDialog(self.iface).get_tri_classes(1)]
        self.assertIn("0-0.1", tri[0])
        self.assertIn("0.1-0.25", tri[1])
        self.assertIn("0.25-0.5", tri[2])
        rows, cols = np.mgrid[0:30, 0:30].astype(float)
        layers = self._run(self._dem("units.tif", 100 + 0.3 * cols * 10 + np.sin(rows)),
                           {"chkTPI", "chkTRI", "chkRoughness"}, {"spinTPIRadius": 1, "spinTRIRadius": 1})
        for kind in ("tpi", "tri", "roughness"):
            self.assertEqual(layers[kind][0][1]["units"], "m", msg=kind)


class DraftingReview2Tests(_QgisCase):

    def _aoi(self, name, x0, y0, x1, y1):
        layer = QgsVectorLayer("Polygon?crs=EPSG:5186", name, "memory")
        layer.dataProvider().addAttributes([QgsField("name", FT_STRING)])
        layer.updateFields()
        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(x0, y0), QgsPointXY(x1, y0),
                                                     QgsPointXY(x1, y1), QgsPointXY(x0, y1),
                                                     QgsPointXY(x0, y0)]]))
        layer.dataProvider().addFeatures([feat])
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        return layer

    def _run(self, dem, aoi, step=3, class_step=5):
        from tools.slope_aspect_drafting_dialog import SlopeAspectDraftingDialog
        dialog = SlopeAspectDraftingDialog(self.iface)
        dialog.cmbDemLayer.setLayer(dem)
        dialog.cmbMaskLayer.setLayer(aoi)
        dialog.chkMaskSelectedOnly.setChecked(False)
        dialog.chkSlopeRaster.setChecked(True)
        dialog.chkAspectArrows.setChecked(True)
        dialog.spinStepCells.setValue(step)
        dialog.spinSlopeClassStep.setValue(class_step)
        before = set(QgsProject.instance().mapLayers())
        dialog.run_drafting()
        QtWidgets.QApplication.processEvents()
        return self._new_layers(before), dialog

    @staticmethod
    def _drafting_layer_count():
        return sum(1 for lyr in QgsProject.instance().mapLayers().values()
                   if (get_archtoolkit_layer_metadata(lyr) or {}).get("tool_id") == "slope_aspect_drafting")

    def test_a_later_run_keeps_every_earlier_result(self):
        rows, cols = np.mgrid[0:30, 0:30].astype(float)
        dem = self._dem("grp.tif", 500 + 3.0 * cols + 1.0 * rows)
        x0, y0 = self.ORIGIN_X, self.ORIGIN_Y
        aoi = self._aoi("aoi", x0 + 50, y0 - 250, x0 + 250, y0 - 50)
        self._run(dem, aoi)
        self._run(dem, aoi)
        self.assertEqual(self._drafting_layer_count(), 4)
        # Anything placed above the group (the tool's own "새 폴리곤" layer,
        # another tool's group) used to make the next run delete them all.
        root = QgsProject.instance().layerTreeRoot()
        root.insertGroup(0, "another tool")
        _layers, dialog = self._run(dem, aoi)
        dialog.create_mask_layer()
        self._run(dem, aoi)
        self.assertEqual(self._drafting_layer_count(), 8)
        self.assertEqual(root.children()[0].name(),
                         "ArchToolkit - 도면화(경사도/사면방향) (Slope/Aspect Drafting)")

    def test_outputs_keep_a_crs_that_has_no_authid(self):
        # A custom transverse Mercator: no EPSG code, so "Point?crs=<authid>"
        # built CRS-less memory layers.
        rows, cols = np.mgrid[0:30, 0:30].astype(float)
        z = 500 + 3.0 * cols + 1.0 * rows
        path = os.path.join(self.temp_dir, "custom.tif")
        ds = gdal.GetDriverByName("GTiff").Create(path, 30, 30, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((self.ORIGIN_X, 10.0, 0.0, self.ORIGIN_Y, 0.0, -10.0))
        srs = osr.SpatialReference()
        srs.ImportFromProj4("+proj=tmerc +lat_0=37.7 +lon_0=127.31 +k=0.9991 +x_0=210000 "
                            "+y_0=520000 +ellps=GRS80 +units=m +no_defs")
        ds.SetProjection(srs.ExportToWkt())
        ds.GetRasterBand(1).SetNoDataValue(-9999.0)
        ds.GetRasterBand(1).WriteArray(z.astype(np.float32))
        ds = None
        dem = QgsRasterLayer(path, "custom", "gdal")
        self.assertTrue(dem.crs().isValid())
        self.assertEqual(dem.crs().authid(), "")
        QgsProject.instance().addMapLayer(dem)
        x0, y0 = self.ORIGIN_X, self.ORIGIN_Y
        aoi = QgsVectorLayer("Polygon", "aoi", "memory")
        aoi.setCrs(dem.crs())
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(x0 + 50, y0 - 250), QgsPointXY(x0 + 250, y0 - 250),
                                                     QgsPointXY(x0 + 250, y0 - 50), QgsPointXY(x0 + 50, y0 - 50),
                                                     QgsPointXY(x0 + 50, y0 - 250)]]))
        aoi.dataProvider().addFeatures([feat])
        QgsProject.instance().addMapLayer(aoi)
        layers, dialog = self._run(dem, aoi)
        for kind in ("aspect_arrows", "slope_grid"):
            layer = layers[kind][0][0]
            self.assertTrue(layer.crs().isValid(), msg=kind)
            self.assertEqual(layer.crs(), dem.crs(), msg=kind)
        self.assertGreater(layers["aspect_arrows"][0][0].featureCount(), 0)
        dialog.create_mask_layer()
        new_aoi = [lyr for lyr in QgsProject.instance().mapLayers().values()
                   if lyr.name() == "작업영역_AOI (AOI polygon)"][0]
        self.assertTrue(new_aoi.crs().isValid())
        self.assertEqual(new_aoi.crs(), dem.crs())

    def test_class_step_sets_the_zones_and_bins_before_rounding(self):
        from tools.slope_aspect_drafting_dialog import slope_class_for, slope_class_label
        self.assertEqual(slope_class_for(9.6, 5), 5)
        self.assertEqual(slope_class_label(5, 5), "5-10°")
        self.assertEqual(slope_class_for(9.6, 1), 10)
        self.assertEqual(slope_class_label(10, 1), "10°")
        x0, y0 = self.ORIGIN_X, self.ORIGIN_Y
        rows, cols = np.mgrid[0:60, 0:60].astype(float)
        dem = self._dem("ramp.tif", 100 + 0.0006 * (cols * 10.0) ** 2)
        aoi = self._aoi("aoi", x0, y0 - 600, x0 + 600, y0)
        zones = {}
        for class_step in (1, 5):
            layers, _dialog = self._run(dem, aoi, step=2, class_step=class_step)
            zones[class_step] = layers["slope_grid"][0][0].featureCount()
        self.assertGreater(zones[1], zones[5])
        self.assertEqual(zones[5], len(layers["slope_grid"][0][0].renderer().categories()))
        dem2 = self._dem("p96.tif", 100 + math.tan(math.radians(9.6)) * cols * 10.0)
        layers, _dialog = self._run(dem2, aoi, step=5, class_step=5)
        feature = next(layers["slope_grid"][0][0].getFeatures())
        self.assertEqual(feature["slope_class"], 5)
        self.assertEqual(feature["label"], "5-10°")


if __name__ == "__main__":
    unittest.main()
