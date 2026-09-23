"""Regression tests for the second review of the cost surface / LCP tool.

Each test pins one confirmed finding:

* Herzog wheeled critical slope read as PERCENT grade (Herzog 2013 and the
  formula in Cuckovic's code), not degrees.
* The .ui: percent spin for the critical slope, corridor tooltip cost(cell->end).
* Closing the dialog during a run left Run/Pick/Clear/Close disabled for good.
* A DEM CRS without an authid silently dropped the LCP, start/end and milestone
  layers.
* The friction vector ignored the layer filter and failed for memory layers.
* Milestones, the profile dialog and Pandolf path times ignored friction.
* Output metadata lacked the model parameters.
* The straight-line comparison was NULL for a point in an edge pixel's outer half.

The QGIS parts skip (not fail) when PyQGIS/GDAL are not importable.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from tools.cost_models import MODEL_HERZOG_WHEELED, edge_cost

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import numpy as np
    from osgeo import gdal, ogr, osr
    from qgis.PyQt.QtCore import QCoreApplication, QEventLoop
    from qgis.core import (
        QgsApplication,
        QgsFeature,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsRasterLayer,
        QgsVectorLayer,
    )
    from qgis.gui import QgsMapCanvas

    from tools import cost_models as cm
    from tools import cost_surface_dialog as csd

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - dependency-free CI
    QGIS_IMPORT_ERROR = exc


class WheeledCriticalSlopeIsPercentTests(unittest.TestCase):
    """QGIS-free: tools.cost_models only."""

    @staticmethod
    def _ratio(grade, params):
        flat = edge_cost(MODEL_HERZOG_WHEELED, 10.0, 0.0, params)
        return edge_cost(MODEL_HERZOG_WHEELED, 10.0, 10.0 * grade, params) / flat

    def test_cost_doubles_at_the_critical_percent_grade(self):
        base = {"wheeled_base_kmh": 4.0, "wheeled_max_slope_deg": 45.0, "min_speed_mps": 0.05}
        # Default: 12 % grade costs 2x flat (Herzog: 1 + (s%/12)^2). The old
        # degree reading gave 1.32x (12 deg = 21.3 %).
        self.assertAlmostEqual(self._ratio(0.12, dict(base)), 2.0, places=9)
        self.assertAlmostEqual(self._ratio(0.20, dict(base)), 1.0 + (20.0 / 12.0) ** 2, places=9)
        # Explicit percent parameter.
        p = dict(base, wheeled_critical_slope_pct=8.0)
        self.assertAlmostEqual(self._ratio(0.08, p), 2.0, places=9)
        # A caller still passing the legacy degree key keeps its old numbers.
        legacy = dict(base, wheeled_critical_slope_deg=12.0)
        pct = math.tan(math.radians(12.0)) * 100.0
        self.assertAlmostEqual(self._ratio(0.12, legacy), 1.0 + (12.0 / pct) ** 2, places=9)


class CostSurfaceUiTextTests(unittest.TestCase):
    """QGIS-free: parse the .ui."""

    def setUp(self):
        self.tree = ET.parse(os.path.join(ROOT, "tools", "cost_surface_dialog_base.ui"))

    def _widget(self, name):
        for w in self.tree.iter("widget"):
            if w.get("name") == name:
                return w
        return None

    @staticmethod
    def _prop(widget, name):
        for p in widget.findall("property"):
            if p.get("name") == name and len(p):
                return list(p)[0].text
        return None

    def test_critical_slope_spin_is_percent_and_corridor_tooltip_matches_code(self):
        self.assertIsNone(self._widget("spinWheeledCriticalSlopeDeg"))
        spin = self._widget("spinWheeledCriticalSlopePct")
        self.assertIsNotNone(spin)
        self.assertEqual((self._prop(spin, "suffix") or "").strip(), "%")
        self.assertAlmostEqual(float(self._prop(spin, "value")), 12.0)
        self.assertIn("%", self._prop(self._widget("lblWheeledCriticalSlope"), "text"))
        tip = self._prop(self._widget("chkCreateCorridor"), "toolTip")
        self.assertIn("cost(cell→end)", tip)
        self.assertNotIn("cost(end→cell)", tip)


def _pump(cond, timeout_s=60.0):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        if cond():
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
            return True
        time.sleep(0.02)
    return False


class _Bar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, *args, **kwargs):
        self.messages.append(" | ".join(str(a) for a in args))

    def pushWidget(self, *args, **kwargs):
        self.messages.append("widget")

    def createMessage(self, *args, **kwargs):
        from qgis.PyQt import QtWidgets
        return QtWidgets.QWidget()

    def clearWidgets(self):
        pass


class _Iface:
    def __init__(self, canvas):
        self._canvas = canvas
        self._bar = _Bar()

    def messageBar(self):
        return self._bar

    def mapCanvas(self):
        return self._canvas

    def mainWindow(self):
        from qgis.PyQt import QtWidgets
        if not hasattr(self, "_mw"):
            self._mw = QtWidgets.QMainWindow()
        return self._mw


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class CostSurfaceReview2QgisTests(unittest.TestCase):
    XMIN, YMAX, PX = 200000.0, 500000.0, 10.0

    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance()
        if cls.app is None:
            prefix = os.environ.get("QGIS_PREFIX_PATH", "").strip()
            if prefix:
                QgsApplication.setPrefixPath(prefix, True)
            cls.app = QgsApplication([], True)
            cls.app.initQgis()
        cls.canvas = QgsMapCanvas()
        cls.canvas.resize(400, 300)
        cls.iface = _Iface(cls.canvas)

    # No tearDownClass: one QgsApplication for the whole test process.

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="archtoolkit_cost_review2_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.iface._bar.messages = []
        # Never restore the tester's remembered dialog values into these runs.
        env = mock.patch.dict(os.environ, {"ARCHTOOLKIT_NO_DIALOG_MEMORY": "1"})
        env.start()
        self.addCleanup(env.stop)
        p = mock.patch.object(csd.CostSurfaceDialog, "_confirm_analysis_size", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self._before_ids = set(QgsProject.instance().mapLayers().keys())
        self.addCleanup(self._remove_layers)

    def _remove_layers(self):
        prj = QgsProject.instance()
        ids = [lid for lid in list(prj.mapLayers().keys()) if lid not in self._before_ids]
        if ids:
            prj.removeMapLayers(ids)

    # -- data -------------------------------------------------------------
    def _cell_xy(self, r, c):
        return (self.XMIN + (c + 0.5) * self.PX, self.YMAX - (r + 0.5) * self.PX)

    def _raster(self, name, arr, *, epsg=5186, wkt=None, nodata=-9999.0):
        path = os.path.join(self.tmp, name)
        rows, cols = arr.shape
        ds = gdal.GetDriverByName("GTiff").Create(path, cols, rows, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((self.XMIN, self.PX, 0.0, self.YMAX, 0.0, -self.PX))
        if wkt is None:
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(epsg)
            wkt = srs.ExportToWkt()
        ds.SetProjection(wkt)
        b = ds.GetRasterBand(1)
        if nodata is not None:
            b.SetNoDataValue(nodata)
        b.WriteArray(arr.astype(np.float32))
        b.FlushCache()
        ds = None
        return path

    def _layer(self, path, name):
        lyr = QgsRasterLayer(path, name, "gdal")
        self.assertTrue(lyr.isValid())
        QgsProject.instance().addMapLayer(lyr)
        return lyr

    # -- driving the dialog ------------------------------------------------
    def _dialog(self, dem_layer, start, end, *, model=None, path=True, cost=True):
        self.canvas.setDestinationCrs(dem_layer.crs())
        d = csd.CostSurfaceDialog(self.iface)
        self.addCleanup(d.deleteLater)
        d.cmbDemLayer.setLayer(dem_layer)
        d.cmbModel.setCurrentIndex(d.cmbModel.findData(model or cm.MODEL_TOBLER))
        d._on_model_changed()
        d.chkCreateCostRaster.setChecked(cost)
        d.chkCreatePath.setChecked(path)
        d.chkCreateCorridor.setChecked(False)
        d.chkDiagonal.setChecked(True)
        d.spinBuffer.setValue(0.0)
        d.chkUseFrictionRaster.setChecked(False)
        d.chkUseFrictionVector.setChecked(False)
        d.set_start_point(QgsPointXY(*start))
        if end is not None:
            d.set_end_point(QgsPointXY(*end))
        return d

    def _run(self, d):
        captured = {}
        orig = d._handle_task_result

        def cap(res):
            captured["res"] = res
            return orig(res)

        d._handle_task_result = cap
        before = set(QgsProject.instance().mapLayers().keys())
        d.run_analysis()
        self.assertTrue(_pump(lambda: "res" in captured, 120), "task did not finish")
        new = [lyr for lid, lyr in QgsProject.instance().mapLayers().items() if lid not in before]
        kinds = {}
        for lyr in new:
            kinds[lyr.customProperty("archtoolkit/cost_surface/kind", lyr.name())] = lyr
        return captured["res"], kinds

    # -- tests ---------------------------------------------------------------
    def test_closing_dialog_mid_run_keeps_it_usable_and_reports_cancel(self):
        dem = self._layer(self._raster("big.tif", np.full((900, 900), 100.0)), "big")
        d = self._dialog(dem, self._cell_xy(5, 5), self._cell_xy(890, 890))
        d.show()
        d.run_analysis()
        self.assertTrue(d._task_running)
        _pump(lambda: False, 1.0)
        d.close()  # user closes the (reused) dialog mid-run
        cancelled = _pump(lambda: any("취소" in m for m in self.iface._bar.messages if "닫아" not in m), 30)
        d.show()  # the plugin reopens the same instance
        self.assertTrue(cancelled, self.iface._bar.messages)
        for name in ("btnRun", "btnPickPoints", "btnClearPoints", "btnClose"):
            self.assertTrue(getattr(d, name).isEnabled(), name)
        self.assertEqual(d._closing_tasks, [])

    def test_dem_crs_without_authid_still_gets_path_points_and_milestones(self):
        srs = osr.SpatialReference()
        srs.ImportFromProj4(
            "+proj=tmerc +lat_0=38 +lon_0=127.0028902777778 +k=1 +x_0=200000 +y_0=500000 "
            "+ellps=bessel +towgs84=-115.8,474.99,674.11,1.16,-2.31,-1.63,6.43 +units=m +no_defs"
        )
        yy, xx = np.mgrid[0:60, 0:60].astype(np.float64)
        z = 100 + 20 * np.sin(xx / 9) * np.cos(yy / 11)
        dem = self._layer(self._raster("custom.tif", z, wkt=srs.ExportToWkt()), "custom")
        self.assertEqual(dem.crs().authid(), "")
        self.assertTrue(dem.crs().isValid())
        d = self._dialog(dem, self._cell_xy(5, 5), self._cell_xy(55, 50))
        res, kinds = self._run(d)
        self.assertTrue(res.ok, res.message)
        for kind in ("path_compare", "start_end_points", "milestones"):
            self.assertIn(kind, kinds)
            lyr = kinds[kind]
            self.assertTrue(lyr.crs().isValid(), kind)
            self.assertEqual(lyr.crs(), dem.crs(), kind)
            self.assertGreater(lyr.featureCount(), 0, kind)

    def test_friction_vector_honours_filter_and_memory_layers(self):
        dem = self._layer(self._raster("flat.tif", np.full((60, 60), 100.0)), "flat")
        gp = os.path.join(self.tmp, "zones.gpkg")
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(gp)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(5186)
        ol = ds.CreateLayer("zones", srs, ogr.wkbPolygon)
        ol.CreateField(ogr.FieldDefn("kind", ogr.OFTString))
        for kind, wkt in (
            ("swamp", "POLYGON((200000 499700,200600 499700,200600 499750,200000 499750,200000 499700))"),
            ("road", "POLYGON((200000 499000,200100 499000,200100 499100,200000 499100,200000 499000))"),
        ):
            f = ogr.Feature(ol.GetLayerDefn())
            f.SetField("kind", kind)
            f.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
            ol.CreateFeature(f)
        ds = None
        start, end = self._cell_xy(5, 30), self._cell_xy(55, 30)  # crosses the swamp rows
        v = 6.0 * math.exp(-3.5 * 0.05) / 3.6
        free_s = 500.0 / v
        swamp_s = 700.0 / v  # 50 steps; the 6 steps in/at the swamp average to 26 instead of 6

        filtered = QgsVectorLayer(f"{gp}|layername=zones", "road_only", "ogr")
        filtered.setSubsetString("\"kind\" = 'road'")
        self.assertEqual(filtered.featureCount(), 1)
        QgsProject.instance().addMapLayer(filtered)
        d = self._dialog(dem, start, end)
        d.chkUseFrictionVector.setChecked(True)
        d.cmbFrictionVector.setLayer(filtered)
        d.spinFrictionVectorMult.setValue(5.0)
        res, _k = self._run(d)
        self.assertTrue(res.ok, res.message)
        self.assertAlmostEqual(res.total_cost_s, free_s, places=3)

        mem = QgsVectorLayer("Polygon?crs=EPSG:5186", "scratch", "memory")
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((200000 499700,200600 499700,200600 499750,200000 499750,200000 499700))"))
        mem.dataProvider().addFeatures([feat])
        QgsProject.instance().addMapLayer(mem)
        d2 = self._dialog(dem, start, end)
        d2.chkUseFrictionVector.setChecked(True)
        d2.cmbFrictionVector.setLayer(mem)
        d2.spinFrictionVectorMult.setValue(5.0)
        res2, kinds2 = self._run(d2)
        self.assertTrue(res2.ok, res2.message)
        self.assertAlmostEqual(res2.total_cost_s, swamp_s, places=3)
        meta = json.loads(kinds2["cost_raster"].customProperty("archtoolkit/params_json", "{}"))
        self.assertEqual(meta["friction_vector"]["layer"], "scratch")
        self.assertEqual(meta["friction_vector"]["multiplier"], 5.0)

    def test_milestones_profile_and_pandolf_times_include_friction(self):
        dem = self._layer(self._raster("flat80.tif", np.full((80, 80), 100.0)), "flat80")
        fr = self._layer(self._raster("fric3.tif", np.full((80, 80), 3.0), nodata=None), "fric3")
        start, end = self._cell_xy(40, 2), self._cell_xy(40, 77)
        d = self._dialog(dem, start, end)
        d.chkUseFrictionRaster.setChecked(True)
        d.cmbFrictionRaster.setLayer(fr)
        d.spinFrictionRasterScale.setValue(1.0)
        res, kinds = self._run(d)
        self.assertTrue(res.ok, res.message)
        ds = gdal.Open(res.cost_raster_path)
        cost = ds.GetRasterBand(1).ReadAsArray()
        ds = None
        ms = list(kinds["milestones"].getFeatures())
        self.assertEqual(len(ms), 1)
        self.assertAlmostEqual(ms[0]["dist_m"], 500.0, places=6)
        self.assertAlmostEqual(ms[0]["time_min"], float(cost[40, 52]), places=4)  # 17.87 min, was 5.96
        lcp = [f for f in kinds["path_compare"].getFeatures() if f["kind"] == "lcp"][0]
        payload = d._profile_payloads[kinds["path_compare"].id()]
        self.assertAlmostEqual(payload["lcp_profile"][-1][4] / 60.0, lcp["time_min"], places=6)
        self.assertAlmostEqual(payload["straight_profile"][-1][4], res.straight_time_s, places=6)
        self.assertAlmostEqual(lcp["time_min"], 750.0 / (6.0 * math.exp(-0.175) / 3.6) * 3.0 / 60.0, places=6)

        d2 = self._dialog(dem, start, end, model=cm.MODEL_PANDOLF)
        d2.chkUseFrictionRaster.setChecked(True)
        d2.cmbFrictionRaster.setLayer(fr)
        d2.spinFrictionRasterScale.setValue(1.0)
        res2, kinds2 = self._run(d2)
        self.assertTrue(res2.ok, res2.message)
        ds = gdal.Open(res2.cost_raster_path)
        t_end = float(ds.GetRasterBand(1).ReadAsArray()[40, 77])
        ds = None
        self.assertAlmostEqual(t_end, 27.0, places=4)
        self.assertAlmostEqual(res2.lcp_time_s / 60.0, t_end, places=4)  # was 9.0 (distance / V)
        self.assertAlmostEqual(res2.straight_time_s / 60.0, t_end, places=4)

    def test_metadata_records_the_model_parameters(self):
        yy, xx = np.mgrid[0:40, 0:40].astype(np.float64)
        dem = self._layer(self._raster("plane.tif", 100 + 0.3 * xx + 0.1 * yy), "plane")
        d = self._dialog(dem, self._cell_xy(5, 5), self._cell_xy(35, 30), model=cm.MODEL_CONOLLY_LAKE)
        d.spinConollyRefSlopeDeg.setValue(7.5)
        res, kinds = self._run(d)
        meta = json.loads(kinds["cost_raster"].customProperty("archtoolkit/params_json", "{}"))
        self.assertEqual(meta["model_params"]["conolly_ref_slope_deg"], 7.5)
        self.assertIn("conolly_base_kmh", meta["model_params"])
        self.assertTrue(meta["allow_diagonal"])
        self.assertIn("connectivity", meta)

        d2 = self._dialog(dem, self._cell_xy(5, 5), self._cell_xy(35, 30), model=cm.MODEL_HERZOG_WHEELED)
        res2, kinds2 = self._run(d2)
        meta2 = json.loads(kinds2["path_compare"].customProperty("archtoolkit/params_json", "{}"))
        self.assertEqual(meta2["model_params"]["wheeled_critical_slope_pct"], 12.0)

    def test_straight_line_near_dem_edge_is_not_null(self):
        path = self._raster("flat40.tif", np.full((40, 40), 100.0))
        w = csd.CostSurfaceWorker(
            dem_source=path, dem_authid="EPSG:5186",
            start_xy=(self.XMIN + 2.0, self.YMAX - 202.0), end_xy=(self.XMIN + 302.0, self.YMAX - 202.0),
            buffer_m=0.0, allow_diagonal=True, model_key=cm.MODEL_TOBLER,
            model_params={"tobler_base_kmh": 6.0, "tobler_slope_factor": 3.5, "tobler_slope_offset": 0.05},
            model_label="t", create_cost_raster=False, create_energy_raster=False, create_path=True,
            on_done=None,
        )
        res = w._run_impl()
        self.assertTrue(res.ok, res.message)
        self.assertIsNotNone(res.straight_time_s)
        v = 6.0 * math.exp(-3.5 * 0.05) / 3.6
        self.assertAlmostEqual(res.straight_time_s, 300.0 / v, places=6)

    def test_old_degree_setting_is_migrated_once(self):
        class _S(dict):
            def value(self, k, default=None):
                return self.get(k, default)

            def setValue(self, k, v):
                self[k] = v

            def remove(self, group):
                for k in [k for k in self if k == group or k.startswith(group + "/")]:
                    del self[k]

        base = "ArchToolkit/dialogs/cost_surface"
        s = _S({f"{base}/spinWheeledCriticalSlopeDeg/value": "12"})
        self.assertEqual(csd._migrate_wheeled_critical_slope_setting(s), 12.0)  # untouched default -> 12 %
        self.assertEqual(s[f"{base}/spinWheeledCriticalSlopePct/value"], 12.0)
        self.assertNotIn(f"{base}/spinWheeledCriticalSlopeDeg/value", s)
        self.assertIsNone(csd._migrate_wheeled_critical_slope_setting(s))  # once

        s2 = _S({f"{base}/spinWheeledCriticalSlopeDeg/value": 8.0})
        pct = csd._migrate_wheeled_critical_slope_setting(s2)
        self.assertAlmostEqual(pct, math.tan(math.radians(8.0)) * 100.0, places=9)  # same cart, now in %
        s3 = _S({f"{base}/spinWheeledCriticalSlopeDeg/value": 8.0, f"{base}/spinWheeledCriticalSlopePct/value": 10.0})
        csd._migrate_wheeled_critical_slope_setting(s3)
        self.assertEqual(s3[f"{base}/spinWheeledCriticalSlopePct/value"], 10.0)  # never overwrites


if __name__ == "__main__":
    sys.exit(unittest.main())
