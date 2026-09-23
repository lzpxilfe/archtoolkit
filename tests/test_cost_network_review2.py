"""QGIS integration tests for the least-cost network review (round 2) fixes.

Like tests/test_align_export_qgis.py this module is discovered by the
dependency-free CI and skips (never fails) when PyQGIS or GDAL are
unavailable. Run it with QGIS' Python to drive the real dialog and QgsTask:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=/usr/share/qgis/python/plugins \
        python3 -m unittest tests.test_cost_network_review2 -v

Covered:
- two sites in one DEM cell keep a real, drawn edge (2 vertices, straight-line
  cost at the model's flat-ground speed) and closeness/betweenness see it;
  the reported edge count equals the line-layer feature count;
- a DEM CRS without an authid is kept on both output layers;
- the symmetrisation combo is visible in k-NN mode and its method is recorded
  in the metadata and the time_sym alias;
- a k-NN k above the candidate k raises the candidate k (complete graph for
  6 sites, k-NN k=5, candidate k=2) and both values are recorded;
- All mode records that SNA ran on the union of MST, k-NN and hub edges;
- a NULL name falls back to the feature id;
- a MultiPoint feature with several points is refused with a message.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("ARCHTOOLKIT_NO_DIALOG_MEMORY", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_REGRESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "regression")

QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
    import numpy as np
    from osgeo import gdal, osr
    from qgis.PyQt.QtCore import QCoreApplication, QEventLoop
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
    from qgis.gui import QgsMapCanvas

    from tools import cost_network_dialog as cnd
    from tools.qtcompat import FT_STRING
    from tools.utils import get_archtoolkit_layer_metadata

    if _REGRESSION_DIR not in sys.path:
        sys.path.insert(0, _REGRESSION_DIR)
    import qgis_env  # noqa: E402  (tests/regression/qgis_env.py: FakeIface)

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc


XMIN, YMAX, PX = 200000.0, 500000.0, 10.0
# Tobler on flat ground: 6 km/h * exp(-3.5 * 0.05), in m/s.
TOBLER_FLAT_MPS = 6.0 * math.exp(-3.5 * 0.05) / 3.6


def _cell_centre(col, row):
    return (XMIN + PX * col + PX / 2.0, YMAX - PX * row - PX / 2.0)


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class CostNetworkReview2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._owns_app = QgsApplication.instance() is None
        if cls._owns_app:
            prefix = os.environ.get("QGIS_PREFIX_PATH", "").strip()
            if not prefix and os.path.isdir("/usr/share/qgis"):
                prefix = "/usr"
            if prefix:
                QgsApplication.setPrefixPath(prefix, True)
            cls.app = QgsApplication([], True)
            cls.app.initQgis()
        else:
            cls.app = QgsApplication.instance()
        cls.canvas = QgsMapCanvas()
        cls.iface = qgis_env.FakeIface(cls.canvas)

    # No tearDownClass: a QgsApplication cannot be re-created in the same
    # process once exitQgis() has run (see tests/test_align_export_qgis.py).

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="archtoolkit_costnet_review2_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(QgsProject.instance().removeAllMapLayers)

    # ------------------------------------------------------------ fixtures
    def _dem(self, name, *, n=60, srs=None, rise_per_col=0.0):
        path = os.path.join(self.tmp, f"{name}.tif")
        ds = gdal.GetDriverByName("GTiff").Create(path, n, n, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((XMIN, PX, 0.0, YMAX, 0.0, -PX))
        if srs is None:
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(5186)
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(-9999.0)
        z = 100.0 + rise_per_col * np.mgrid[0:n, 0:n][1].astype(np.float64)
        band.WriteArray(z.astype(np.float32))
        band.FlushCache()
        ds = None
        lyr = QgsRasterLayer(path, name, "gdal")
        self.assertTrue(lyr.isValid())
        QgsProject.instance().addMapLayer(lyr)
        return lyr

    def _points(self, name, coords, *, names=None, crs=None, geom="Point"):
        lyr = QgsVectorLayer(f"{geom}?crs=EPSG:5186", name, "memory")
        if crs is not None:
            lyr.setCrs(crs)
        lyr.dataProvider().addAttributes([QgsField("name", FT_STRING)])
        lyr.updateFields()
        feats = []
        for i, c in enumerate(coords):
            f = QgsFeature(lyr.fields())
            if isinstance(c, str):
                f.setGeometry(QgsGeometry.fromWkt(c))
            else:
                f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*c)))
            f.setAttributes([names[i] if names else f"P{i}"])
            feats.append(f)
        lyr.dataProvider().addFeatures(feats)
        lyr.updateExtents()
        QgsProject.instance().addMapLayer(lyr)
        return lyr

    @staticmethod
    def _set_data(combo, data):
        idx = combo.findData(data)
        assert idx >= 0, (combo.objectName(), data)
        combo.setCurrentIndex(idx)

    def _run(self, dem, sites, *, mode="mst", cand_k=10, knn_k=3, buffer=300.0, sym="avg",
             sna=True, hub_field="", hub_values=""):
        d = cnd.CostNetworkDialog(self.iface)
        self.addCleanup(d.deleteLater)
        d.cmbDemLayer.setLayer(dem)
        d.cmbSiteLayer.setLayer(sites)
        d._on_site_layer_changed()
        self._set_data(d.cmbModel, cnd.MODEL_TOBLER)
        d._on_model_changed()
        self._set_data(d.cmbNetworkMode, mode)
        d._on_mode_changed()
        self._set_data(d.cmbNameField, "name")
        if hub_field:
            self._set_data(d.cmbHubField, hub_field)
        d.txtHubValues.setText(hub_values)
        d.chkSelectedOnly.setChecked(False)
        d.chkDiagonal.setChecked(True)
        d.spinCandidateK.setValue(cand_k)
        d.spinKnnK.setValue(knn_k)
        d.spinPairBuffer.setValue(buffer)
        self._set_data(d.cmbSymmetrize, sym)
        d.chkSnaEnable.setChecked(sna)
        d.chkSnaCloseness.setChecked(sna)
        d.chkSnaBetweenness.setChecked(sna)
        before = set(QgsProject.instance().mapLayers().keys())
        self.iface._bar.messages.clear()
        d.run_analysis()
        t0 = time.time()
        while d._task_running and time.time() - t0 < 120:
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
            time.sleep(0.02)
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        self.assertFalse(d._task_running, "task did not finish")
        edges = nodes = None
        for lid, lyr in QgsProject.instance().mapLayers().items():
            if lid in before or not isinstance(lyr, QgsVectorLayer):
                continue
            meta = get_archtoolkit_layer_metadata(lyr) or {}
            if meta.get("kind") == "edges":
                edges = lyr
            elif meta.get("kind") == "nodes":
                nodes = lyr
        msgs = [" | ".join(str(a) for a in m[0][:2]) for m in self.iface._bar.messages]
        return d, edges, nodes, msgs

    @staticmethod
    def _rows(lyr):
        return [{f.name(): ft[f.name()] for f in lyr.fields()} | {"_geom": ft.geometry()} for ft in lyr.getFeatures()]

    # ------------------------------------------------------------ tests
    def test_same_cell_sites_keep_a_drawn_edge_and_count_in_sna(self):
        dem = self._dem("flat")
        # P0 and P1 are 2.83 m apart inside ONE 10 m cell.
        coords = [(200105.0, 499895.0), (200107.0, 499897.0), (200405.0, 499895.0), (200255.0, 499605.0)]
        sites = self._points("coloc", coords)
        _d, edges, nodes, msgs = self._run(dem, sites, mode="mst", cand_k=3)
        self.assertIsNotNone(edges)
        # Reported count == drawn count, every line has >= 2 vertices.
        self.assertIn("간선 3개", msgs[-1])
        self.assertEqual(edges.featureCount(), 3)
        for r in self._rows(edges):
            self.assertGreaterEqual(len(r["_geom"].asPolyline()), 2)
        pair = [r for r in self._rows(edges) if {r["from_nm"], r["to_nm"]} == {"P0", "P1"}]
        self.assertEqual(len(pair), 1)
        expected_min = math.hypot(2.0, 2.0) / TOBLER_FLAT_MPS / 60.0
        self.assertAlmostEqual(pair[0]["time_sym"], expected_min, places=6)
        self.assertAlmostEqual(pair[0]["dist_m"], math.hypot(2.0, 2.0), places=6)
        by_name = {r["name"]: r for r in self._rows(nodes)}
        # P0 bridges all 3 pairs of the star; P1 is reachable (closeness > 0).
        self.assertAlmostEqual(by_name["P0"]["betweenness"], 3.0, places=9)
        self.assertGreater(by_name["P1"]["closeness"], 0.3)
        self.assertEqual(get_archtoolkit_layer_metadata(edges)["params"]["same_cell_pairs"], 1)

    def test_identical_sites_get_half_a_cell(self):
        dem = self._dem("flat_dup")
        coords = [(200105.0, 499895.0), (200105.0, 499895.0), (200405.0, 499895.0)]
        sites = self._points("dup", coords)
        _d, edges, _nodes, _msgs = self._run(dem, sites, mode="knn", cand_k=2, knn_k=1)
        pair = [r for r in self._rows(edges) if {r["from_nm"], r["to_nm"]} == {"P0", "P1"}]
        self.assertEqual(len(pair), 1)
        self.assertAlmostEqual(pair[0]["time_ab"], (PX / 2.0) / TOBLER_FLAT_MPS / 60.0, places=6)
        self.assertEqual(edges.featureCount(), 2)

    def test_dem_crs_without_authid_is_kept(self):
        srs = osr.SpatialReference()
        srs.ImportFromProj4(
            "+proj=tmerc +lat_0=38 +lon_0=127.0028902777778 +k=1 +x_0=200000 +y_0=500000 "
            "+ellps=bessel +towgs84=-115.8,474.99,674.11,1.16,-2.31,-1.63,6.43 +units=m +no_defs"
        )
        dem = self._dem("custom", srs=srs)
        self.assertEqual(dem.crs().authid(), "")
        sites = self._points("cs", [(200055.0, 499945.0), (200505.0, 499945.0), (200305.0, 499555.0)], crs=dem.crs())
        _d, edges, nodes, _msgs = self._run(dem, sites, mode="mst", cand_k=2)
        for lyr in (edges, nodes):
            self.assertTrue(lyr.crs().isValid())
            self.assertEqual(lyr.crs(), dem.crs())

    def test_symmetrisation_is_visible_and_recorded_in_knn(self):
        dem = self._dem("slope_sym", rise_per_col=2.0)  # 20% eastward slope: A->B != B->A
        coords = [_cell_centre(5, 5), _cell_centre(40, 10), _cell_centre(20, 45)]
        sites = self._points("sym", coords)
        d, edges, _nodes, _msgs = self._run(dem, sites, mode="knn", cand_k=2, knn_k=2, sym="min")
        self.assertTrue(d.cmbSymmetrize.isVisibleTo(d))
        params = get_archtoolkit_layer_metadata(edges)["params"]
        self.assertEqual(params["symmetrization"], "min(A->B, B->A)")
        alias = edges.attributeAlias(edges.fields().indexFromName("time_sym"))
        self.assertIn("편도 최소", alias)
        for r in self._rows(edges):
            self.assertGreater(abs(r["time_ab"] - r["time_ba"]), 0.1)
            self.assertAlmostEqual(r["time_sym"], min(r["time_ab"], r["time_ba"]), places=9)

    def test_knn_k_above_candidate_k_raises_candidate_k(self):
        dem = self._dem("flat_knn", n=100)
        cells = [(10, 10), (40, 15), (25, 50), (80, 30), (70, 80), (15, 85)]
        sites = self._points("knn", [_cell_centre(c, r) for c, r in cells])
        _d, edges, _nodes, msgs = self._run(dem, sites, mode="knn", cand_k=2, knn_k=5, sna=False)
        self.assertEqual(edges.featureCount(), 15)  # k=5 on 6 sites = complete graph
        params = get_archtoolkit_layer_metadata(edges)["params"]
        self.assertEqual(params["candidate_k"], 5)
        self.assertEqual(params["candidate_k_requested"], 2)
        self.assertEqual(params["knn_k"], 5)
        self.assertIn("k-NN k=5", msgs[-1])

    def test_all_mode_records_union_graph_for_sna(self):
        dem = self._dem("flat_all", n=100)
        cells = [(10, 10), (40, 15), (25, 50), (80, 30), (70, 80), (15, 85)]
        sites = self._points("all", [_cell_centre(c, r) for c, r in cells])
        _d, _edges, nodes, msgs = self._run(dem, sites, mode="all", cand_k=5, knn_k=2)
        params = get_archtoolkit_layer_metadata(nodes)["params"]
        self.assertEqual(params["sna_graph"], "union of mst, knn and hub edges")
        self.assertIn("합집합", msgs[-1])
        self.assertIn("합집합", nodes.attributeAlias(nodes.fields().indexFromName("degree")))

    def test_null_name_falls_back_to_feature_id(self):
        dem = self._dem("flat_null")
        coords = [(200055.0, 499945.0), (200505.0, 499945.0), (200305.0, 499555.0)]
        sites = self._points("nulls", coords, names=["S0", None, "S2"])
        _d, _edges, nodes, _msgs = self._run(dem, sites, mode="mst", cand_k=2, sna=False)
        rows = {r["fid"]: r["name"] for r in self._rows(nodes)}
        self.assertEqual(rows["2"], "2")
        self.assertNotIn("NULL", rows.values())

    def test_multipoint_with_several_points_is_refused(self):
        dem = self._dem("flat_mp")
        a, b, c = (200105.0, 499895.0), (200405.0, 499845.0), (200305.0, 499555.0)
        wkts = [f"MultiPoint(({a[0]} {a[1]}),({c[0]} {c[1]}))", f"MultiPoint(({b[0]} {b[1]}))",
                f"MultiPoint(({c[0]} {c[1]}))"]
        sites = self._points("mp", wkts, geom="MultiPoint")
        d, edges, nodes, msgs = self._run(dem, sites, mode="mst", cand_k=2, sna=False)
        self.assertIsNone(edges)
        self.assertIsNone(nodes)
        self.assertTrue(any("멀티포인트" in m for m in msgs), msgs)
        # Single-part MultiPoint features still work.
        ok_sites = self._points("mp1", wkts[1:], geom="MultiPoint")
        _d, edges, _nodes, _msgs = self._run(dem, ok_sites, mode="mst", cand_k=2, sna=False)
        self.assertEqual(edges.featureCount(), 1)


if __name__ == "__main__":
    unittest.main()
