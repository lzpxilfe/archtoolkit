"""Correctness pins for 가시권 분석 (tools/viewshed_dialog.py), review round 2.

Each test reproduces a wrong output, a silent failure or a missing refusal
found in review:
- an observer outside the DEM / on NoData ran silently (no file, no message,
  a stray observer layer) or used the NoData value as eye elevation; in
  multi mode such observers were dropped but still counted;
- LOS sampled at >= 5 m, stepping over thin walls on fine DEMs, and silently
  skipped NoData samples (also at the endpoints);
- AOI statistics used a fixed 0.5 threshold (weighted rasters read 0 %),
  ALL_TOUCHED masks (area inflated) and no analysed-share figure;
- closed perimeters counted their start vertex twice (three times when drawn);
- a repeated run picked up the tool's own observer layer as extra input;
- gdal_viewshed's out-of-range cells and DEM NoData cells were drawn as
  "보이지 않음"; the cumulative mask used cell corners;
- reverse-viewshed metadata stored the internally swapped heights;
- the circular crop expanded outputs far beyond the DEM;
- spinMaxDistance accepted 0 (= unlimited in GDAL);
- LOS "elevation" values were curvature-adjusted;
- memory layers lost CRSs without an authid;
- the analysis radius ring called a non-existent QgsGeometry.boundary().

The dependency-free CI discovers this module and skips it when PyQGIS is not
importable; run it under QGIS' Python to exercise the dialog.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import unittest
from unittest import mock

QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
    import numpy as np
    from osgeo import gdal, osr
    from qgis.PyQt import QtWidgets
    from qgis.PyQt.QtCore import QObject, pyqtSignal
    from qgis.core import (
        QgsApplication,
        QgsCoordinateReferenceSystem,
        QgsFeature,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsRasterLayer,
        QgsVectorLayer,
    )
    from qgis.gui import QgsMapCanvas

    from processing.core.Processing import Processing
    from tools.viewshed_dialog import ViewshedDialog

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc


ORIGIN_X = 200000.0
ORIGIN_Y = 500000.0


if QGIS_AVAILABLE:

    class _Signals(QObject):
        currentLayerChanged = pyqtSignal(object)

    class _FakeMessageBar:
        def __init__(self):
            self.messages = []

        def pushMessage(self, *args, **kwargs):
            self.messages.append(" | ".join(str(a) for a in args[:2]))

        def pushWidget(self, *args, **kwargs):
            self.messages.append("widget")

        def createMessage(self, *args, **kwargs):
            return QtWidgets.QWidget()

        def clearWidgets(self):
            pass

    class _FakeIface:
        """The slice of QgisInterface the viewshed dialog touches."""

        def __init__(self):
            self._bar = _FakeMessageBar()
            self._canvas = QgsMapCanvas()
            self._canvas.resize(800, 600)
            self._sig = _Signals()
            self.currentLayerChanged = self._sig.currentLayerChanged

        def messageBar(self):
            return self._bar

        def mapCanvas(self):
            return self._canvas

        def mainWindow(self):
            if not hasattr(self, "_window"):
                self._window = QtWidgets.QMainWindow()
            return self._window

        def layerTreeView(self):
            return None

        def activeLayer(self):
            return None


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class ViewshedReview2QgisTests(unittest.TestCase):
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
        if QgsApplication.processingRegistry().algorithmById("gdal:viewshed") is None:
            raise unittest.SkipTest("QGIS GDAL provider is unavailable")
        if shutil.which("gdal_viewshed") is None:
            raise unittest.SkipTest("gdal_viewshed is not installed")

    # No tearDownClass: one QgsApplication per process (see
    # tests/test_align_export_qgis.py).

    def setUp(self):
        QgsProject.instance().removeAllMapLayers()
        self.temp_dir = tempfile.mkdtemp(prefix="archtoolkit_viewshed_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        self.iface = _FakeIface()
        self.iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:5186"))
        self._dialogs = []
        self.addCleanup(self._close_dialogs)

    def _close_dialogs(self):
        for d in self._dialogs:
            # cleanup_for_unload() disconnects the project signals; the dialog
            # swallows (and logs) anything already disconnected.
            d.cleanup_for_unload()
            d.hide()
        QgsProject.instance().removeAllMapLayers()

    # ------------------------------------------------------------ fixtures
    def _dem(self, name, z, *, px=10.0, nodata=-9999.0, wkt=None):
        path = os.path.join(self.temp_dir, f"{name}.tif")
        rows, cols = z.shape
        ds = gdal.GetDriverByName("GTiff").Create(path, cols, rows, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((ORIGIN_X, px, 0.0, ORIGIN_Y, 0.0, -px))
        if wkt is None:
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(5186)
            wkt = srs.ExportToWkt()
        ds.SetProjection(wkt)
        band = ds.GetRasterBand(1)
        if nodata is not None:
            band.SetNoDataValue(nodata)
        band.WriteArray(z.astype(np.float32))
        ds = None
        layer = QgsRasterLayer(path, name, "gdal")
        self.assertTrue(layer.isValid())
        QgsProject.instance().addMapLayer(layer)
        return layer, path

    @staticmethod
    def _rough(n=100):
        yy, xx = np.mgrid[0:n, 0:n].astype(float)
        return 100 + 25 * np.sin(xx / 6.0) * np.cos(yy / 7.0) + 0.3 * xx

    def _points(self, name, coords, epsg=5186):
        layer = QgsVectorLayer(f"Point?crs=EPSG:{epsg}", name, "memory")
        feats = []
        for x, y in coords:
            f = QgsFeature()
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            feats.append(f)
        layer.dataProvider().addFeatures(feats)
        QgsProject.instance().addMapLayer(layer)
        return layer

    def _polygon(self, name, geom):
        layer = QgsVectorLayer("Polygon?crs=EPSG:5186", name, "memory")
        f = QgsFeature()
        f.setGeometry(geom)
        layer.dataProvider().addFeatures([f])
        QgsProject.instance().addMapLayer(layer)
        return layer

    def _dialog(self, canvas_crs=None):
        if canvas_crs is not None:
            self.iface.mapCanvas().setDestinationCrs(canvas_crs)
        d = ViewshedDialog(self.iface)
        self._dialogs.append(d)
        return d

    @staticmethod
    def _pump(n=5):
        for _ in range(n):
            QtWidgets.QApplication.processEvents()

    def _setup(self, d, dem, *, mode="single", obs_xy=None, obs_layer=None, obs_h=1.6, tgt_h=None,
               max_dist=300, curvature=False, aoi=None):
        d.cmbDemLayer.setLayer(dem)
        {"single": d.radioSinglePoint, "reverse": d.radioReverseViewshed, "multi": d.radioMultiPoint,
         "line": d.radioLineViewshed, "los": d.radioLineOfSight}[mode].setChecked(True)
        self._pump()
        if obs_layer is not None:
            d.radioFromLayer.setChecked(True)
            self._pump()
            d.cmbObserverLayer.setLayer(obs_layer)
        else:
            d.radioClickMap.setChecked(True)
            self._pump()
            if obs_xy is not None:
                d.observer_point = QgsPointXY(*obs_xy)
        d.spinObserverHeight.setValue(obs_h)
        if tgt_h is not None:
            d.spinTargetHeight.setValue(tgt_h)
        d.spinMaxDistance.setValue(max_dist)
        d.chkCurvature.setChecked(curvature)
        d.chkRefraction.setChecked(False)
        if aoi is not None:
            d.chkAoiStats.setChecked(True)
            d.cmbAoiStatsLayer.setLayer(aoi)
        else:
            d.chkAoiStats.setChecked(False)
        self._pump()

    def _run(self, d):
        before = set(QgsProject.instance().mapLayers())
        self.iface._bar.messages.clear()
        with mock.patch.object(QtWidgets.QMessageBox, "warning",
                               return_value=QtWidgets.QMessageBox.StandardButton.Yes):
            d.run_analysis()
        self._pump(10)
        added = [QgsProject.instance().mapLayer(i) for i in set(QgsProject.instance().mapLayers()) - before]
        return added, list(self.iface._bar.messages)

    @staticmethod
    def _raster(layers, prefix):
        for lyr in layers:
            if isinstance(lyr, QgsRasterLayer) and lyr.name().startswith(prefix):
                return lyr
        return None

    @staticmethod
    def _read(layer):
        ds = gdal.Open(layer.source().split("|", 1)[0])
        band = ds.GetRasterBand(1)
        return band.ReadAsArray().astype(np.float64), ds.GetGeoTransform(), band.GetNoDataValue()

    @staticmethod
    def _to_dem_grid(arr, gt, shape, px=10.0, nodata=-9999.0):
        """Place an output raster on the DEM lattice (NaN elsewhere / NoData)."""
        out = np.full(shape, np.nan)
        ox = int(round((gt[0] - ORIGIN_X) / px))
        oy = int(round((ORIGIN_Y - gt[3]) / px))
        h, w = arr.shape
        r0, c0 = max(0, oy), max(0, ox)
        r1, c1 = min(shape[0], oy + h), min(shape[1], ox + w)
        sub = arr[r0 - oy:r1 - oy, c0 - ox:c1 - ox].astype(float)
        sub[sub == nodata] = np.nan
        out[r0:r1, c0:c1] = sub
        return out

    @staticmethod
    def _params(layer):
        return json.loads(layer.customProperty("archtoolkit/params_json", "{}") or "{}")

    def _feature_attrs(self, layer):
        names = [f.name() for f in layer.fields()]
        return [dict(zip(names, f.attributes())) for f in layer.getFeatures()]

    # ------------------------------------------------------------ 1. off-DEM observers
    def test_single_observer_outside_dem_is_refused_without_stray_layer(self):
        dem, _ = self._dem("flat_out", np.full((60, 60), 50.0))
        d = self._dialog()
        self._setup(d, dem, obs_xy=(ORIGIN_X + 900.0, ORIGIN_Y - 305.0))
        added, msgs = self._run(d)
        self.assertEqual(added, [], msg=f"no layer may be left behind, got {[a.name() for a in added]}")
        self.assertTrue(any("DEM 범위 밖" in m for m in msgs), msg=msgs)
        self.assertTrue(d.isVisible(), "dialog must come back after a refusal")

    def test_single_observer_on_nodata_is_refused(self):
        z = np.full((60, 60), 50.0)
        z[25:35, 25:35] = -9999.0
        dem, _ = self._dem("flat_nd_obs", z)
        d = self._dialog()
        self._setup(d, dem, obs_xy=(ORIGIN_X + 305.0, ORIGIN_Y - 305.0))
        added, msgs = self._run(d)
        self.assertEqual(added, [])
        self.assertTrue(any("NoData" in m for m in msgs), msg=msgs)

    def test_multi_drops_off_dem_observers_and_counts_only_used_ones(self):
        dem, _ = self._dem("rough_multi", self._rough())
        obs = self._points("obs3", [(ORIGIN_X + 305, ORIGIN_Y - 495), (ORIGIN_X + 705, ORIGIN_Y - 695),
                                    (ORIGIN_X + 1050, ORIGIN_Y - 500)])  # last one 50 m east of the DEM
        d = self._dialog()
        self._setup(d, dem, mode="multi", obs_layer=obs, obs_h=2.0)
        d.chkCountOnly.setChecked(True)
        added, msgs = self._run(d)
        ras = self._raster(added, "가시권_누적")
        self.assertIsNotNone(ras, msg=msgs)
        self.assertEqual(ras.name(), "가시권_누적_2개점")
        params = self._params(ras)
        self.assertEqual(params.get("points_n"), 2)
        self.assertEqual(params.get("points_dropped"), 1)
        self.assertTrue(any("1개 관측점 제외" in m for m in msgs), msg=msgs)

    # ------------------------------------------------------------ 2. LOS sampling / NoData
    def _los(self, dem, o, t, *, obs_h=1.6, tgt_h=0.0, curvature=False):
        d = self._dialog()
        self._setup(d, dem, mode="los", obs_h=obs_h, tgt_h=tgt_h, curvature=curvature)
        d.observer_point = QgsPointXY(*o)
        d.target_point = QgsPointXY(*t)
        added, msgs = self._run(d)
        line = [lyr for lyr in added if lyr.name().startswith("가시선_Viscode")]
        payload = d._los_profile_data.get(line[0].id()) if line else None
        for dlg in list(d._los_profile_dialogs.values()):
            dlg.close()
        return d, added, msgs, payload

    def test_los_catches_one_pixel_wall_on_fine_dem(self):
        z = np.zeros((5, 3000))
        z[:, 1500] = 50.0  # 1 m thick, 50 m high wall halfway along a 3 km line
        dem, _ = self._dem("los_wall_1m", z, px=1.0)
        _d, _added, msgs, payload = self._los(dem, (ORIGIN_X + 0.5, ORIGIN_Y - 2.5), (ORIGIN_X + 2999.5, ORIGIN_Y - 2.5))
        self.assertIsNotNone(payload, msg=msgs)
        self.assertIs(payload["is_visible_overall"], False, msg=msgs)
        self.assertAlmostEqual(max(p["elevation"] for p in payload["profile_data"]), 50.0)

    def test_los_endpoint_outside_dem_is_refused(self):
        dem, _ = self._dem("los_out", np.full((60, 60), 50.0))
        _d, added, msgs, payload = self._los(dem, (ORIGIN_X - 400.0, ORIGIN_Y - 305.0), (ORIGIN_X + 505.0, ORIGIN_Y - 305.0))
        self.assertIsNone(payload)
        self.assertEqual(added, [])
        self.assertTrue(any("DEM 범위 밖" in m for m in msgs), msg=msgs)

    def test_los_interior_nodata_is_undetermined(self):
        z = np.full((60, 60), 50.0)
        z[:, 30:33] = -9999.0  # NoData strip across the line
        dem, _ = self._dem("los_nd", z)
        _d, added, msgs, payload = self._los(dem, (ORIGIN_X + 55.0, ORIGIN_Y - 305.0), (ORIGIN_X + 555.0, ORIGIN_Y - 305.0))
        self.assertIsNotNone(payload, msg=msgs)
        self.assertIsNone(payload["is_visible_overall"], msg=msgs)
        self.assertTrue(any("판정 불가" in m for m in msgs), msg=msgs)
        targets = [lyr for lyr in added if lyr.name().startswith("가시선_Targets")]
        self.assertEqual(self._feature_attrs(targets[0])[0]["status"], "판정 불가")

    # ------------------------------------------------------------ 3/4. AOI statistics
    def test_aoi_rule_counts_weighted_cells_below_half(self):
        z = np.full((100, 100), 50.0)
        z[:, 50] = 200.0  # wall: the west AOI is seen only by the west observer
        dem, _ = self._dem("wall_w", z)
        aoi = self._polygon("aoi_w", QgsGeometry.fromWkt(
            "POLYGON((200100 499300, 200400 499300, 200400 499700, 200100 499700, 200100 499300))"))
        d = self._dialog()
        self._setup(d, dem, mode="multi", obs_h=2.0, max_dist=400, aoi=aoi)
        d.chkWeightedCumulative.setChecked(True)
        d.chkNormalizeWeighted.setChecked(False)
        d.observer_points = [QgsPointXY(200255.0, 499505.0), QgsPointXY(200755.0, 499505.0)]
        d.observer_weights = [0.3, 1.0]
        added, msgs = self._run(d)
        stats = [lyr for lyr in added if lyr.name().startswith("AOI_")]
        self.assertTrue(stats, msg=msgs)
        row = self._feature_attrs(stats[0])[0]
        self.assertAlmostEqual(row["vis_pct"], 100.0)
        self.assertIn("value > 0", row["vis_rule"])
        self.assertIn("value > 0", self._params(stats[0]).get("visible_rule", ""))

    def test_aoi_counts_cell_centres_and_reports_analysed_share(self):
        dem, _ = self._dem("flat_aoi", np.full((100, 100), 50.0))
        small = QgsGeometry.fromPointXY(QgsPointXY(200403.0, 499497.0)).buffer(25.0, 64)
        far = QgsGeometry.fromWkt("POLYGON((200505 499000, 200905 499000, 200905 499400, 200505 499400, 200505 499000))")
        aoi = QgsVectorLayer("Polygon?crs=EPSG:5186", "aoi_two", "memory")
        feats = []
        for g in (small, far):
            f = QgsFeature()
            f.setGeometry(g)
            feats.append(f)
        aoi.dataProvider().addFeatures(feats)
        QgsProject.instance().addMapLayer(aoi)
        d = self._dialog()
        self._setup(d, dem, obs_xy=(200505.0, 499495.0), max_dist=300, aoi=aoi)
        added, msgs = self._run(d)
        stats = [lyr for lyr in added if lyr.name().startswith("AOI_")]
        self.assertTrue(stats, msg=msgs)
        rows = sorted(self._feature_attrs(stats[0]), key=lambda r: r["aoi_m2"])
        rr, cc = np.mgrid[0:100, 0:100]
        xs = ORIGIN_X + (cc + 0.5) * 10.0
        ys = ORIGIN_Y - (rr + 0.5) * 10.0
        centre_in = int((np.hypot(xs - 200403.0, ys - 499497.0) <= 25.0).sum())
        self.assertEqual(rows[0]["tot_px"], centre_in)          # 19 cells, not 31 (ALL_TOUCHED)
        self.assertAlmostEqual(rows[0]["tot_m2"], centre_in * 100.0)
        self.assertAlmostEqual(rows[1]["aoi_m2"], 160000.0)
        self.assertLess(rows[1]["anl_pct"], 50.0)                # only part of it lies in the radius
        self.assertGreater(rows[1]["anl_pct"], 0.0)

    # ------------------------------------------------------------ 5/6. perimeters and repeat runs
    def _square(self):
        return [QgsPointXY(200400, 499400), QgsPointXY(200600, 499400),
                QgsPointXY(200600, 499600), QgsPointXY(200400, 499600)]

    def test_closed_perimeter_uses_start_vertex_once(self):
        dem, _ = self._dem("rough_line", self._rough(120))
        d = self._dialog()
        self._setup(d, dem, mode="line", obs_h=2.0)
        d.spinLineInterval.setValue(50)
        d.chkCountOnly.setChecked(True)
        d.set_line_from_tool(self._square(), is_closed=True)
        added, msgs = self._run(d)
        ras = self._raster(added, "가시권_누적")
        self.assertIsNotNone(ras, msg=msgs)
        self.assertEqual(ras.name(), "가시권_누적_16개점")  # 800 m / 50 m, start vertex once

    def test_polygon_layer_ring_uses_start_vertex_once(self):
        dem, _ = self._dem("rough_poly", self._rough(120))
        poly = self._polygon("sqpoly", QgsGeometry.fromWkt(
            "POLYGON((200400 499400, 200600 499400, 200600 499600, 200400 499600, 200400 499400))"))
        d = self._dialog()
        self._setup(d, dem, mode="multi", obs_layer=poly, obs_h=2.0)
        d.spinLineInterval.setValue(50)
        d.chkCountOnly.setChecked(True)
        added, msgs = self._run(d)
        ras = self._raster(added, "가시권_누적")
        self.assertIsNotNone(ras, msg=msgs)
        self.assertEqual(ras.name(), "가시권_누적_16개점")
        obs_layer = [lyr for lyr in added if lyr.name().startswith("누적가시권_관측점")][0]
        pts = [(round(f.geometry().asPoint().x(), 6), round(f.geometry().asPoint().y(), 6)) for f in obs_layer.getFeatures()]
        self.assertEqual(len(pts), len(set(pts)))

    def test_repeated_line_run_is_identical_and_ignores_own_outputs(self):
        dem, _ = self._dem("rough_rep", self._rough(120))
        d = self._dialog()
        self._setup(d, dem, mode="line", obs_h=2.0)
        d.spinLineInterval.setValue(50)
        d.chkCountOnly.setChecked(True)
        names = []
        for _run in range(2):
            d.set_line_from_tool(self._square(), is_closed=True)
            added, msgs = self._run(d)
            ras = self._raster(added, "가시권_누적")
            self.assertIsNotNone(ras, msg=msgs)
            names.append(ras.name())
            self.assertFalse(d.radioFromLayer.isChecked(), "own output layer must not flip the source to a layer")
            self.assertEqual(d.drawn_line_points, [])
        self.assertEqual(names[0], names[1])

    # ------------------------------------------------------------ 7/8/10. radius, NoData, grids
    def test_flat_dem_has_no_false_invisible_ring_and_nodata_stays_nodata(self):
        z = np.full((100, 100), 50.0)
        z[45:55, 60:70] = -9999.0
        dem, _ = self._dem("flat_ring", z)
        d = self._dialog()
        self._setup(d, dem, obs_xy=(200500.0, 499500.0), max_dist=300)  # a cell corner
        added, msgs = self._run(d)
        ras = self._raster(added, "가시권_단일점")
        self.assertIsNotNone(ras, msg=msgs)
        arr, gt, nd = self._read(ras)
        g = self._to_dem_grid(arr, gt, z.shape, nodata=nd)
        self.assertEqual(int((g == 0).sum()), 0, "flat DEM: every analysed cell is visible")
        self.assertTrue(np.isnan(g[45:55, 60:70]).all(), "DEM NoData must stay NoData")
        # Radius exactly as GDAL: cell centre to the centre of the observer's cell.
        rr, cc = np.mgrid[0:100, 0:100]
        dist = np.hypot((cc - 50) * 10.0, (rr - 50) * 10.0)
        expected = (dist <= 300.0) & (z != -9999.0)
        self.assertTrue(np.array_equal(np.isfinite(g), expected))

    def test_radius_mask_does_not_depend_on_gdal_out_of_range_flag(self):
        """GDAL 3.11 (QGIS 3.44 LTR) leaves the first and last rows of its output
        window at 0 instead of the -ov value; the result must still be NoData there."""
        z = np.full((100, 100), 50.0)
        z[45:55, 60:70] = -9999.0
        dem, _ = self._dem("flat_ov311", z)
        d = self._dialog()
        rows = cols = 61
        gt = (ORIGIN_X + 200.0, 10.0, 0.0, ORIGIN_Y - 200.0, 0.0, -10.0)
        yy, xx = np.mgrid[0:rows, 0:cols]
        cx = gt[0] + (xx + 0.5) * 10.0
        cy = gt[3] - (yy + 0.5) * 10.0
        dist = np.hypot(cx - 200505.0, cy - 499495.0)   # centre of the observer's cell
        dem_win = z[20:81, 20:81]
        raw = np.where(dist <= 300.0, 255, 1).astype(np.uint8)
        raw[(dist <= 300.0) & (dem_win == -9999.0)] = 0
        raw[0, dist[0] > 300.0] = 0      # GDAL 3.11: no -ov on the window's edge rows
        raw[-1, dist[-1] > 300.0] = 0
        raw_path = os.path.join(self.temp_dir, "raw_ov311.tif")
        ds = gdal.GetDriverByName("GTiff").Create(raw_path, cols, rows, 1, gdal.GDT_Byte)
        ds.SetGeoTransform(gt)
        ds.GetRasterBand(1).WriteArray(raw)
        ds = None
        out_path = os.path.join(self.temp_dir, "final_ov311.tif")
        d._finalize_viewshed_raster(raw_path, out_path, dem, observer_xy=(200500.0, 499500.0), max_dist=300.0)
        out_ds = gdal.Open(out_path)
        out = out_ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
        out_ds = None
        out[out == -9999.0] = np.nan
        self.assertEqual(int((out == 0).sum()), 0, "no false 'not visible' band on the edge rows")
        expected_valid = (dist <= 300.0) & (dem_win != -9999.0)
        self.assertTrue(np.array_equal(np.isfinite(out), expected_valid))

    def test_cumulative_equals_sum_of_single_viewsheds(self):
        z = self._rough(120)
        dem, _ = self._dem("rough_cum", z)
        obs = [(200405.0, 499405.0), (200612.3, 499587.1), (200333.3, 499777.7)]
        singles = []
        for o in obs:
            d = self._dialog()
            self._setup(d, dem, obs_xy=o, obs_h=2.0, max_dist=350)
            added, msgs = self._run(d)
            ras = self._raster(added, "가시권_단일점")
            self.assertIsNotNone(ras, msg=msgs)
            arr, gt, nd = self._read(ras)
            singles.append(self._to_dem_grid(arr, gt, z.shape, nodata=nd))
        layer = self._points("obs_cum", obs)
        d = self._dialog()
        self._setup(d, dem, mode="multi", obs_layer=layer, obs_h=2.0, max_dist=350)
        d.chkCountOnly.setChecked(True)
        added, msgs = self._run(d)
        ras = self._raster(added, "가시권_누적")
        arr, gt, nd = self._read(ras)
        cum = self._to_dem_grid(arr, gt, z.shape, nodata=nd)
        any_valid = np.any([np.isfinite(s) for s in singles], axis=0)
        self.assertTrue(np.array_equal(np.isfinite(cum), any_valid))
        expected = np.sum([(s == 255).astype(float) for s in singles], axis=0)
        self.assertTrue(np.array_equal(cum[any_valid], expected[any_valid]))

    def test_output_is_never_larger_than_the_dem(self):
        dem, _ = self._dem("small_big_radius", self._rough(60))
        d = self._dialog()
        self._setup(d, dem, obs_xy=(200305.0, 499705.0), max_dist=3000)
        added, msgs = self._run(d)
        ras = self._raster(added, "가시권_단일점")
        self.assertIsNotNone(ras, msg=msgs)
        self.assertLessEqual(ras.width(), 60)
        self.assertLessEqual(ras.height(), 60)

    def test_max_distance_zero_is_not_accepted(self):
        d = self._dialog()
        self.assertGreaterEqual(d.spinMaxDistance.minimum(), 1)

    # ------------------------------------------------------------ 9. reverse metadata
    def test_reverse_metadata_stores_heights_as_entered(self):
        dem, _ = self._dem("rough_rev", self._rough())
        tgt = self._points("tgt", [(200605.0, 499405.0)])
        d = self._dialog()
        self._setup(d, dem, mode="reverse", obs_layer=tgt, obs_h=1.6, tgt_h=10.0, max_dist=300)
        added, msgs = self._run(d)
        ras = self._raster(added, "역방향_가시권")
        self.assertIsNotNone(ras, msg=msgs)
        params = self._params(ras)
        self.assertAlmostEqual(params["observer_height_m"], 1.6)
        self.assertAlmostEqual(params["target_height_m"], 10.0)
        self.assertAlmostEqual(params["gdal_observer_height_m"], 10.0)

    # ------------------------------------------------------------ 12. LOS elevations
    def test_los_reports_dem_elevations_with_curvature(self):
        z = np.zeros((20, 1100))
        z[:, 495:505] = 100.0
        dem, _ = self._dem("ridge_long", z, px=20.0)
        _d, added, msgs, payload = self._los(dem, (200010.0, 499805.0), (221010.0, 499805.0), curvature=True)
        self.assertIsNotNone(payload, msg=msgs)
        self.assertAlmostEqual(payload["profile_data"][-1]["elevation"], 0.0)       # DEM value
        self.assertLess(payload["profile_data"][-1]["elev_calc"], -30.0)            # adjusted, kept apart
        ob = [lyr for lyr in added if lyr.name() == "첫번째_장애물"]
        row = self._feature_attrs(ob[0])[0]
        self.assertAlmostEqual(row["elevation"], 0.0)
        self.assertIn("elev_adj", row)
        self.assertTrue(any("DEM 고도 0.0m" in m for m in msgs), msg=msgs)

    # ------------------------------------------------------------ 13/14. CRS and radius ring
    def test_outputs_keep_a_crs_without_authid(self):
        srs = osr.SpatialReference()
        srs.SetProjCS("custom TM")
        srs.SetGeogCS("GRS80ish", "D_custom", "GRS80", 6378137, 298.257222101)
        srs.SetTM(38.0, 127.0003, 1.0, 200000.0, 600000.0)
        dem, _ = self._dem("custom_crs", self._rough(), wkt=srs.ExportToWkt())
        self.assertEqual(dem.crs().authid(), "")
        d = self._dialog(canvas_crs=dem.crs())
        self._setup(d, dem, obs_xy=(200505.0, 499495.0), max_dist=300)
        d.spinHiguchiNear.setValue(100)
        d.spinHiguchiMid.setValue(200)
        d.chkHiguchi.setChecked(True)
        added, msgs = self._run(d)
        vectors = [lyr for lyr in added if isinstance(lyr, QgsVectorLayer)]
        self.assertTrue(vectors, msg=msgs)
        for lyr in vectors:
            self.assertTrue(lyr.crs().isValid(), msg=lyr.name())

    def test_analysis_radius_ring_is_created(self):
        dem, _ = self._dem("ring_dem", self._rough(60))
        d = self._dialog()
        ring = d.create_analysis_radius_ring(QgsPointXY(200305.0, 499705.0), dem.crs(), 200.0, dem)
        self.assertIsNotNone(ring)
        feats = list(ring.getFeatures())
        self.assertEqual(len(feats), 1)
        self.assertAlmostEqual(feats[0].geometry().length(), 2 * math.pi * 200.0, delta=1.0)
        self.assertTrue(ring.crs().isValid())


if __name__ == "__main__":
    unittest.main()
