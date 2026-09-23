"""Correctness pins for 근접/가시성 네트워크 (tools/spatial_network_dialog.py), review round 2.

Each test reproduces a wrong output found in review:
- LOS read the DEM by nearest cell anywhere inside a cell (up to slope x
  pixel/2 too high on a slope) and tested the endpoints' own cells, so with the
  default target height 0 most truly intervisible pairs on inclined ground
  came out "not visible";
- step 0 meant max(pixel, 5 m), stepping over thin ridges on 1-2 m DEMs;
- polygon boundary sampling called QgsGeometry.boundary() (does not exist),
  swallowed the AttributeError and silently used one point per polygon;
- output memory layers were built from crs.authid() and lost a custom CRS;
- the Gabriel filter kept sites lying ON the diametral circle (grids);
- 2 sites / collinear sites aborted Delaunay/Gabriel/RNG, and co-located
  sites were not joined to each other;
- NULL names became the text "NULL"; k-NN metadata recorded a max distance
  that was never applied; k-NN ties depended on numpy's unstable sort.

The dependency-free CI discovers this module and skips it when PyQGIS is not
importable; run it under QGIS' Python to exercise the dialog.
"""

from __future__ import annotations

import itertools
import json
import math
import os
import random
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
    from qgis.core import (
        QgsApplication,
        QgsCoordinateReferenceSystem,
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
    from tools.spatial_network_dialog import SpatialNetworkDialog

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc


XMIN = 200000.0
YMAX = 500000.0
EARTH_R = 6371000.0


class _FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, title, text, level=0, duration=0):
        self.messages.append((str(title), str(text), int(level)))


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


def _set_combo(combo, data):
    for i in range(combo.count()):
        if combo.itemData(i) == data:
            combo.setCurrentIndex(i)
            return
    raise AssertionError(f"combo item {data!r} not found")


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS unavailable: {QGIS_IMPORT_ERROR}")
class SpatialNetworkReview2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
        registry = QgsApplication.processingRegistry()
        if registry.algorithmById("native:delaunaytriangulation") is None and \
                registry.algorithmById("qgis:delaunaytriangulation") is None:
            raise unittest.SkipTest("Delaunay triangulation algorithm unavailable")

    # No tearDownClass: the QgsApplication lives for the whole test process
    # (see tests/test_align_export_qgis.py).

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="archtoolkit_spatialnet_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        env = mock.patch.dict(os.environ, {"ARCHTOOLKIT_NO_DIALOG_MEMORY": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.iface = _FakeIface()
        self._layer_ids = []
        self.addCleanup(self._drop_layers)

    def _drop_layers(self):
        project = QgsProject.instance()
        project.removeMapLayers([lid for lid in self._layer_ids if project.mapLayer(lid) is not None])

    # -- fixtures --------------------------------------------------------
    def _register(self, layer):
        self.assertTrue(layer.isValid(), layer.name())
        QgsProject.instance().addMapLayer(layer)
        self._layer_ids.append(layer.id())
        return layer

    def _dem(self, name, z, px):
        path = os.path.join(self.temp_dir, name)
        ds = gdal.GetDriverByName("GTiff").Create(path, z.shape[1], z.shape[0], 1, gdal.GDT_Float64)
        ds.SetGeoTransform((XMIN, px, 0.0, YMAX, 0.0, -px))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(5186)
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(-9999.0)
        band.WriteArray(z)
        band.FlushCache()
        ds = None
        return self._register(QgsRasterLayer(path, name))

    def _points(self, coords, *, names=None, crs=None):
        layer = QgsVectorLayer("Point?crs=EPSG:5186" if crs is None else "Point", "sites", "memory")
        if crs is not None:
            layer.setCrs(crs)
        provider = layer.dataProvider()
        provider.addAttributes([QgsField("nm", FT_STRING)])
        layer.updateFields()
        feats = []
        for i, (x, y) in enumerate(coords):
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(x), float(y))))
            f.setAttributes([names[i] if names is not None else f"S{i}"])
            feats.append(f)
        provider.addFeatures(feats)
        layer.updateExtents()
        return self._register(layer)

    def _new_layers(self, before):
        out = [lyr for lid, lyr in QgsProject.instance().mapLayers().items() if lid not in before]
        self._layer_ids.extend(lyr.id() for lyr in out)
        return out

    def _run_ppa(self, layer, method, *, k=2, mutual=False, max_dist=0.0, name_field=""):
        dlg = SpatialNetworkDialog(self.iface)
        dlg.cmbSiteLayer.setLayer(layer)
        _set_combo(dlg.cmbNetworkType, "ppa")
        _set_combo(dlg.cmbPpaGraph, method)
        dlg.spinPpaK.setValue(int(k))
        dlg.chkPpaMutualOnly.setChecked(bool(mutual))
        dlg.spinPpaMaxDist.setValue(float(max_dist))
        dlg.chkCreateNodeMetrics.setChecked(True)
        if name_field:
            _set_combo(dlg.cmbNameField, name_field)
        before = set(QgsProject.instance().mapLayers().keys())
        dlg.run_analysis()
        layers = self._new_layers(before)
        edges = [lyr for lyr in layers if lyr.geometryType() == 1]
        nodes = [lyr for lyr in layers if lyr.geometryType() == 0]
        return (edges[0] if edges else None), (nodes[0] if nodes else None)

    def _run_vis(self, layer, dem, *, obs=1.6, tgt=0.0, step=0.0, curvature=True, boundary=False):
        dlg = SpatialNetworkDialog(self.iface)
        dlg.cmbSiteLayer.setLayer(layer)
        _set_combo(dlg.cmbNetworkType, "visibility")
        dlg.cmbDemLayer.setLayer(dem)
        dlg.spinObsHeight.setValue(obs)
        dlg.spinTgtHeight.setValue(tgt)
        dlg.spinMaxDist.setValue(0.0)
        dlg.spinSampleStep.setValue(step)
        dlg.chkVisAllPairs.setChecked(True)
        dlg.chkPolyBoundaryVis.setChecked(bool(boundary))
        dlg.spinPolyBoundaryStep.setValue(50)
        dlg.spinPolyMaxBoundaryPts.setValue(30)
        dlg.chkVisCurvature.setChecked(bool(curvature))
        dlg.chkCreateNodeMetrics.setChecked(True)
        before = set(QgsProject.instance().mapLayers().keys())
        dlg.run_analysis()
        layers = self._new_layers(before)
        edges = [lyr for lyr in layers if lyr.geometryType() == 1]
        self.assertEqual(len(edges), 1, [lyr.name() for lyr in layers])
        return edges[0]

    @staticmethod
    def _rows(layer):
        names = layer.fields().names()
        return [dict(zip(names, f.attributes())) for f in layer.getFeatures()]

    @classmethod
    def _edge_set(cls, layer):
        out = set()
        for r in cls._rows(layer):
            a, b = int(r["from_id"]) - 1, int(r["to_id"]) - 1
            out.add((min(a, b), max(a, b)))
        return out

    @staticmethod
    def _params(layer):
        return json.loads(layer.customProperty("archtoolkit/params_json") or "{}")

    # -- visibility ------------------------------------------------------
    def test_inclined_plane_is_fully_intervisible_with_default_heights(self):
        # On a plane every sight line between eye heights >= 0 clears the
        # ground (curvature only adds clearance). The old nearest-cell reading
        # returned 2 mutual pairs of 45 here (default obs 1.6 m, tgt 0 m).
        px, slope, n = 5.0, 0.10, 300
        phi = math.radians(30.0)
        xc = (np.arange(n) + 0.5) * px
        yc = -(np.arange(n) + 0.5) * px
        gx, gy = np.meshgrid(xc, yc)
        z = 600.0 + slope * (gx * math.cos(phi) + gy * math.sin(phi))
        dem = self._dem("plane.tif", z, px)
        rng = random.Random(3)
        sites = [(XMIN + rng.uniform(100, 1400), YMAX - rng.uniform(100, 1400)) for _ in range(10)]
        edges = self._run_vis(self._points(sites), dem)
        statuses = [r["status"] for r in self._rows(edges)]
        self.assertEqual(len(statuses), 45)
        self.assertEqual(statuses.count("상호 보임"), 45, statuses)
        params = self._params(edges)
        self.assertEqual(params.get("dem_sampling"), "bilinear")
        self.assertTrue(params.get("los_endpoint_cells_skipped"))

    def test_cone_summit_and_flank_see_each_other(self):
        # Straight-flanked cone on a 30 m DEM: the summit cell used to hide
        # the summit from the flank and vice versa (gdal_viewshed: visible).
        px, n = 30.0, 81
        yy, xx = np.mgrid[0:n, 0:n]
        c = n // 2
        z = 100.0 + np.maximum(0.0, 300.0 - 0.2 * np.hypot((xx - c) * px, (yy - c) * px))
        dem = self._dem("cone.tif", z, px)
        xs, ys = XMIN + (c + 0.5) * px, YMAX - (c + 0.5) * px
        pts = self._points([(xs, ys), (xs - 1200.0, ys)])
        for tgt in (0.0, 1.6):
            row = self._rows(self._run_vis(pts, dem, tgt=tgt))[0]
            self.assertEqual((row["vis_ab"], row["vis_ba"]), (1, 1), f"tgt={tgt}: {row['status']}")

    def test_wall_threshold_matches_curvature_formula(self):
        # 10 km pair, 20 m towers, one-cell wall 3 km from A, flat ground.
        # Blocked iff H > 20 - cc*d1*(D-d1)/(2R) (cc = 0.87), or H > 20 flat.
        # The observer sits off the cell centre so the wall is not hit by a
        # regular sample centre; the cell-centre crossing must still see it.
        px = 10.0
        ax, bx, y = XMIN + 58.3, XMIN + 10058.3, YMAX - 25.0
        d1 = (XMIN + 3055.0) - ax
        total = bx - ax
        h_curv = 20.0 - 0.87 * d1 * (total - d1) / (2.0 * EARTH_R)
        pts = self._points([(ax, y), (bx, y)])
        for height in (h_curv - 0.05, h_curv + 0.05, 19.95, 20.05):
            z = np.full((5, 1020), 100.0)
            z[:, 305] = 100.0 + height
            dem = self._dem(f"wall_{height:.3f}.tif", z, px)
            for curvature in (True, False):
                edges = self._run_vis(pts, dem, obs=20.0, tgt=20.0, curvature=curvature)
                row = self._rows(edges)[0]
                blocked = height > (h_curv if curvature else 20.0)
                self.assertEqual(row["vis_ab"], 0 if blocked else 1, f"H={height:.3f} curvature={curvature}")
        self.assertEqual(self._params(edges).get("dem_sampling"), "bilinear")

    def test_step_zero_means_pixel_size(self):
        # 1 m DEM: step 0 used to become 5 m and step over a 1 m thick wall.
        z = np.full((5, 1100), 100.0)
        z[:, 301] = 200.0
        dem = self._dem("wall1m.tif", z, 1.0)
        pts = self._points([(XMIN + 0.5, YMAX - 2.5), (XMIN + 1000.5, YMAX - 2.5)])
        edges = self._run_vis(pts, dem, obs=1.6, tgt=1.6, step=0.0)
        self.assertEqual(self._rows(edges)[0]["status"], "상호 안보임")
        self.assertAlmostEqual(self._params(edges)["sample_step_m_base"], 1.0)

    def test_polygon_boundary_ratio_is_computed(self):
        # A: 100 x 900 m rectangle; a 100 m wall covers the northern part of
        # the sight lines to the small polygon B. 19 of A's 30 boundary
        # samples see B's representative point; the old code used only A's
        # representative point (ratio 1.0).
        z = np.full((100, 1000), 100.0)
        z[:70, 600] = 200.0
        dem = self._dem("pb_wall.tif", z, 10.0)
        poly = QgsVectorLayer("Polygon?crs=EPSG:5186", "polys", "memory")

        def rect(x0, x1, y0, y1):
            f = QgsFeature()
            f.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(XMIN + x0, YMAX - y0), QgsPointXY(XMIN + x1, YMAX - y0),
                                                      QgsPointXY(XMIN + x1, YMAX - y1), QgsPointXY(XMIN + x0, YMAX - y1)]]))
            return f

        poly.dataProvider().addFeatures([rect(1000, 1100, 50, 950), rect(8990, 9010, 890, 910)])
        self._register(poly)
        edges = self._run_vis(poly, dem, obs=1.6, tgt=1.6, curvature=False, boundary=True)
        row = self._rows(edges)[0]
        self.assertAlmostEqual(row["vis_ratio_ab"], 19.0 / 30.0, places=4)
        params = self._params(edges)
        self.assertTrue(params["poly_boundary"])
        self.assertEqual(params["poly_boundary_samples_max"], 30)
        self.assertEqual(params["poly_boundary_fallback_nodes"], 0)

    # -- PPA -------------------------------------------------------------
    def test_output_layers_keep_a_crs_without_authid(self):
        crs = QgsCoordinateReferenceSystem.fromProj(
            "+proj=tmerc +lat_0=38 +lon_0=127.123 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs")
        self.assertTrue(crs.isValid())
        self.assertEqual(crs.authid(), "")
        rng = random.Random(1)
        pts = self._points([(XMIN + rng.uniform(0, 2000), YMAX + rng.uniform(0, 2000)) for _ in range(6)], crs=crs)
        edges, nodes = self._run_ppa(pts, "delaunay")
        for layer in (edges, nodes):
            self.assertTrue(layer.crs().isValid(), layer.name())
            self.assertEqual(layer.crs(), crs)

    def test_gabriel_on_a_grid_is_strict(self):
        # 4 x 4 grid: every cell's corners are cocircular. The strict Gabriel
        # graph is the 24 grid edges; the old filter kept 9 diagonals.
        coords = [(XMIN + 100 * i, YMAX + 100 * j) for j in range(4) for i in range(4)]
        edges, _nodes = self._run_ppa(self._points(coords), "gabriel")
        got = self._edge_set(edges)
        truth = set()
        for a, b in itertools.combinations(range(16), 2):
            dab = (coords[a][0] - coords[b][0]) ** 2 + (coords[a][1] - coords[b][1]) ** 2
            if all((coords[a][0] - coords[c][0]) ** 2 + (coords[a][1] - coords[c][1]) ** 2
                   + (coords[b][0] - coords[c][0]) ** 2 + (coords[b][1] - coords[c][1]) ** 2 > dab
                   for c in range(16) if c not in (a, b)):
                truth.add((a, b))
        self.assertEqual(len(truth), 24)
        self.assertEqual(got, truth)

    def test_collinear_and_two_sites_give_the_path(self):
        line = [(XMIN, YMAX), (XMIN + 100, YMAX), (XMIN + 250, YMAX), (XMIN + 400, YMAX), (XMIN + 520, YMAX)]
        path = {(0, 1), (1, 2), (2, 3), (3, 4)}
        pts = self._points([line[i] for i in (3, 0, 4, 1, 2)])  # feature order != line order
        order = [3, 0, 4, 1, 2]
        expect = {tuple(sorted((order.index(a), order.index(b)))) for a, b in path}
        for method in ("delaunay", "gabriel", "rng"):
            self.iface.messageBar().messages.clear()
            edges, _nodes = self._run_ppa(pts, method)
            self.assertIsNotNone(edges, method)
            self.assertEqual(self._edge_set(edges), expect, method)
            self.assertEqual(self._params(edges)["degenerate"], "collinear")
            self.assertFalse([m for m in self.iface.messageBar().messages if m[2] >= 2], method)
        two = self._points([(XMIN, YMAX), (XMIN + 300, YMAX + 40)])
        for method in ("delaunay", "gabriel", "rng"):
            edges, _nodes = self._run_ppa(two, method)
            self.assertIsNotNone(edges, method)
            self.assertEqual(self._edge_set(edges), {(0, 1)}, method)

    def test_colocated_sites_are_joined(self):
        coords = [(XMIN, YMAX), (XMIN + 100, YMAX), (XMIN + 50, YMAX + 80), (XMIN + 50, YMAX + 80),
                  (XMIN + 160, YMAX + 90), (XMIN - 60, YMAX + 70)]
        pts = self._points(coords)
        for method in ("delaunay", "gabriel", "rng"):
            edges, _nodes = self._run_ppa(pts, method)
            self.assertIn((2, 3), self._edge_set(edges), method)

    def test_null_name_falls_back_to_fid(self):
        pts = self._points([(XMIN, YMAX), (XMIN + 100, YMAX), (XMIN + 40, YMAX + 90)], names=["A", None, "C"])
        _edges, nodes = self._run_ppa(pts, "knn", k=1, name_field="nm")
        names = {r["fid"]: r["name"] for r in self._rows(nodes)}
        self.assertEqual(names, {"1": "A", "2": "2", "3": "C"})

    def test_max_dist_recorded_only_when_applied(self):
        rng = random.Random(2)
        pts = self._points([(XMIN + rng.uniform(0, 1000), YMAX + rng.uniform(0, 1000)) for _ in range(8)])
        knn, _n = self._run_ppa(pts, "knn", k=2, max_dist=100.0)
        self.assertIsNone(self._params(knn)["max_dist_m"])
        dela, _n = self._run_ppa(pts, "delaunay", max_dist=0.0)
        self.assertIsNone(self._params(dela)["max_dist_m"])
        dela_lim, _n = self._run_ppa(pts, "delaunay", max_dist=400.0)
        self.assertEqual(self._params(dela_lim)["max_dist_m"], 400.0)
        thr, _n = self._run_ppa(pts, "threshold", max_dist=300.0)
        self.assertEqual(self._params(thr)["max_dist_m"], 300.0)

    def test_knn_ties_break_by_feature_id(self):
        coords = [(XMIN + 100 * i, YMAX + 100 * j) for j in range(4) for i in range(4)]
        edges, _nodes = self._run_ppa(self._points(coords), "knn", k=2)
        truth = set()
        for i in range(16):
            ranked = sorted(((coords[i][0] - coords[j][0]) ** 2 + (coords[i][1] - coords[j][1]) ** 2, j)
                            for j in range(16) if j != i)
            for _d, j in ranked[:2]:
                truth.add((min(i, j), max(i, j)))
        self.assertEqual(self._edge_set(edges), truth)


if __name__ == "__main__":
    unittest.main()
