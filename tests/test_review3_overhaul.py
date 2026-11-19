"""Comprehensive regression suite for the Stage 1-6 ArchToolkit overhaul.

Covers real behavioral fixes across all 6 stages under PyQGIS + GDAL:
- Stage 1-3: processing_task inline materialization of ``"memory:"``,
  normalized RMS ``tri_radius``, flat aspect ``-1.0`` vs border NoData ``-9999``,
  NGII ``F0017112`` defaults + DXF subset filter, Kriging numerical-instability
  variance NoData guard, and viewshed visual-imbalance symmetry.
- Stage 4: Herzog metabolic signed-slope asymmetry + admissible A* downhill path,
  CostNetwork ``_simplify_turn_points`` / ``site->hub`` direction / ``betw_norm``,
  SpatialNetwork ``_los_visible`` undeclared NoData / ``_ppa_filter_rng``
  co-located witnesses / ``betweenness_centrality_*`` edge dedup, and
  DistanceRaster reference NoData masking + explicit pixel dimensions.
- Stage 5: AHP gapped vs abutting ``reclass`` interval boundaries, Trench
  Korean ridge false-positive exclusions, Covariate Report auto-selection &
  small-sample VIF guard.
- Stage 6: Geology cross-sheet ``LITHOIDX`` conflict disambiguation, GeoChem
  halo stop protection, MapStyling open 3-vertex wall buffering, Cadastral
  overlap pct clamping, AI integer class auto-detection / undeclared NoData /
  metric distance / synchronized bundle export.
"""

from __future__ import annotations

import csv
import json
import math
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("ARCHTOOLKIT_NO_DIALOG_MEMORY", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_REGRESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "regression")

QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
    import numpy as np
    from osgeo import gdal, osr
    from qgis.PyQt.QtCore import Qt
    from qgis.core import (
        NULL,
        QgsApplication,
        QgsCoordinateReferenceSystem,
        QgsFeature,
        QgsField,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsRasterLayer,
        QgsRectangle,
        QgsVectorLayer,
    )
    from qgis.gui import QgsMapCanvas
    from processing.core.Processing import Processing

    from tools import ahp_core, ai_aoi_summary, cost_models, cost_network_dialog as cnd
    from tools import covariate_report_dialog as crd
    from tools import geochem_legend as GL, network_metrics as nm
    from tools.ai_report_dialog import AiAoiReportDialog
    from tools.cadastral_overlap_dialog import CadastralOverlapDialog
    from tools.contour_extractor_dialog import ContourExtractorDialog
    from tools.cost_surface_dialog import _astar_path
    from tools.covariate_report_dialog import CovariateReportDialog
    from tools.dem_generator_dialog import DemGeneratorDialog
    from tools.distance_raster_dialog import DISTANCE_NODATA, DistanceRasterDialog
    from tools.geology_zip_dialog import GeologyZipDialog
    from tools.kriging_lite import ordinary_kriging_lite_to_geotiff
    from tools.map_styling_dialog import MapStylingDialog
    from tools.processing_task import run_alg_blocking
    from tools.qtcompat import FT_DOUBLE, FT_INT, FT_STRING
    from tools.spatial_network_dialog import SpatialNetworkDialog
    from tools.terrain_analysis_dialog import TerrainAnalysisDialog
    from tools.terrain_math import ASPECT_FLAT_VALUE, mark_flat_aspect, tri_radius
    from tools.trench_suggestion_dialog import _text_has_grave_keyword
    from tools.utils import get_archtoolkit_layer_metadata, set_archtoolkit_layer_metadata
    from tools.viewshed_dialog import ViewshedDialog

    if _REGRESSION_DIR not in sys.path:
        sys.path.insert(0, _REGRESSION_DIR)
    import qgis_env  # noqa: E402

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - dependency-free CI
    QGIS_IMPORT_ERROR = exc


def _write_gtiff(path: str, arr: "np.ndarray", *, origin=(200000.0, 500000.0), px=10.0, nodata=None, epsg=5186, dtype=None):
    rows, cols = int(arr.shape[0]), int(arr.shape[1])
    if dtype is None:
        dtype = gdal.GDT_Int32 if np.issubdtype(arr.dtype, np.integer) else gdal.GDT_Float32
    ds = gdal.GetDriverByName("GTiff").Create(path, cols, rows, 1, dtype)
    ds.SetGeoTransform((float(origin[0]), float(px), 0.0, float(origin[1]), 0.0, -float(px)))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(int(epsg))
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(float(nodata))
    band.WriteArray(arr)
    band.FlushCache()
    ds = None
    return path


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class Review3OverhaulTests(unittest.TestCase):
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
        cls.canvas = QgsMapCanvas()
        cls.iface = qgis_env.FakeIface(cls.canvas)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="archtoolkit_r3_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(QgsProject.instance().removeAllMapLayers)
        self.iface._bar.messages.clear()

    def _mem(self, geom_type: str, name: str, fields, rows, *, epsg: int = 5186) -> QgsVectorLayer:
        lyr = QgsVectorLayer(f"{geom_type}?crs=EPSG:{int(epsg)}", name, "memory")
        pr = lyr.dataProvider()
        pr.addAttributes([QgsField(fn, ft) for fn, ft in fields])
        lyr.updateFields()
        feats = []
        for g, attrs in rows:
            f = QgsFeature(lyr.fields())
            f.setGeometry(g if isinstance(g, QgsGeometry) else QgsGeometry.fromWkt(g))
            f.setAttributes(list(attrs))
            feats.append(f)
        pr.addFeatures(feats)
        lyr.updateExtents()
        return lyr

    # --- Stage 1-3 --------------------------------------------------------
    def test_run_alg_blocking_materializes_memory_output(self):
        pt = self._mem("Point", "pts", [("id", FT_INT)], [("POINT(200100 499900)", [1])])
        res = run_alg_blocking("native:buffer", {"INPUT": pt, "DISTANCE": 15.0, "OUTPUT": "memory:"})
        out = res.get("OUTPUT")
        self.assertIsInstance(out, QgsVectorLayer)
        self.assertTrue(out.isValid())
        self.assertEqual(out.featureCount(), 1)
        poly = next(out.getFeatures()).geometry()
        self.assertAlmostEqual(poly.area(), math.pi * 15.0 * 15.0, delta=30.0)

    def test_tri_radius_normalized_rms_and_aspect_flat_vs_nodata(self):
        # 7x7 linear slope ramp: z = 100 + 2 * col => 6 neighbours differ by +-2, 2 equal
        cols = np.arange(7, dtype=np.float64)[None, :]
        z = np.repeat(100.0 + 2.0 * cols, 7, axis=0)
        tri = tri_radius(z, 1)
        # Centre cell RMS difference: sqrt((4*6 + 0*2)/8) = sqrt(3)
        self.assertAlmostEqual(float(tri[3, 3]), math.sqrt(3.0), places=6)
        self.assertTrue(np.isnan(tri[0, 3]) and np.isnan(tri[3, 0]))

        # mark_flat_aspect: interior flat cell gets ASPECT_FLAT_VALUE (-1.0), border stays -9999.0
        dem_valid = np.ones((5, 5), dtype=bool)
        raw_aspect = np.full((5, 5), -9999.0, dtype=np.float64)
        marked = mark_flat_aspect(raw_aspect, dem_valid, -9999.0)
        self.assertEqual(float(marked[2, 2]), ASPECT_FLAT_VALUE)
        self.assertEqual(float(marked[0, 2]), -9999.0)

    def test_ngii_f0017112_defaults_and_dxf_layer_filter(self):
        self.assertTrue(DemGeneratorDialog.DXF_LAYER_INFO["F0017112"]["default"])
        self.assertIn("F0017112", DemGeneratorDialog.DXF_LAYER_PRESETS["modern_f"]["codes"])

        dxf = self._mem(
            "LineString",
            "dxf_src",
            [("Layer", FT_STRING)],
            [
                ("LINESTRING(200000 499900, 200050 499900)", ["F0017111"]),
                ("LINESTRING(200000 499910, 200050 499910)", ["F0017112"]),
                ("LINESTRING(200000 499920, 200050 499920)", ["A0023211"]),
            ],
        )
        QgsProject.instance().addMapLayer(dxf)
        dlg = ContourExtractorDialog(self.iface)
        self.addCleanup(dlg.close)
        codes = dlg.get_selected_contour_codes()
        self.assertIn("F0017111", codes)
        self.assertIn("F0017112", codes)
        for i in range(dlg.listDxfLayers.count()):
            item = dlg.listDxfLayers.item(i)
            item.setSelected(item.data(0x0100) == dxf.id())
        dlg.extract_from_dxf()
        self.assertEqual(dxf.featureCount(), 2)
        dlg.reset_filters()
        self.assertEqual(dxf.featureCount(), 3)

    def test_kriging_ill_conditioned_variance_stays_nonnegative_or_nodata(self):
        # Include two near-collocated samples (1 mm apart) with different elevations
        pts = self._mem(
            "Point",
            "krig_pts",
            [("z", FT_DOUBLE)],
            [
                ("POINT(200015 499985)", [10.0]),
                ("POINT(200015.001 499985)", [90.0]),
                ("POINT(200055 499985)", [30.0]),
                ("POINT(200015 499945)", [50.0]),
                ("POINT(200055 499945)", [70.0]),
                ("POINT(200035 499965)", [45.0]),
            ],
        )
        out_p = os.path.join(self.tmp, "k_pred.tif")
        var_p = os.path.join(self.tmp, "k_var.tif")
        ordinary_kriging_lite_to_geotiff(
            layer=pts,
            value_field="z",
            extent=QgsRectangle(200000, 499930, 200070, 500000),
            pixel_size=10.0,
            out_path=out_p,
            variance_path=var_p,
            neighbors=6,
        )
        ds = gdal.Open(var_p)
        var = ds.GetRasterBand(1).ReadAsArray()
        nd = ds.GetRasterBand(1).GetNoDataValue()
        ds = None
        valid = var[var != nd]
        self.assertTrue(np.all(valid >= 0.0), f"Negative kriging variance found: {valid.min()}")

    def test_viewshed_visual_imbalance_raster_coding_and_symmetric_terrain(self):
        fwd = _write_gtiff(os.path.join(self.tmp, "fwd.tif"), np.array([[1, 1, 0, -9999]], dtype=np.int16), nodata=-9999, dtype=gdal.GDT_Int16)
        rev = _write_gtiff(os.path.join(self.tmp, "rev.tif"), np.array([[1, 0, 1, 1]], dtype=np.int16), nodata=-9999, dtype=gdal.GDT_Int16)
        out = os.path.join(self.tmp, "imb.tif")
        dlg = ViewshedDialog(self.iface)
        self.addCleanup(dlg.close)
        dlg._create_visual_imbalance_raster(fwd, rev, out, nodata_value=-9999)
        ds = gdal.Open(out)
        arr = ds.GetRasterBand(1).ReadAsArray()
        ds = None
        self.assertEqual(arr[0].tolist(), [0, 1, 2, -9999])

    # --- Stage 4 ----------------------------------------------------------
    def test_herzog_signed_slope_unclamped_and_astar_admissible(self):
        spec = {}
        # Downhill minimum near -10% vs flat vs moderate downhill vs cliff (-60%)
        c_opt = cost_models.edge_cost(cost_models.MODEL_HERZOG_METABOLIC, 10.0, -1.0, spec, cost_mode="energy_j")
        c_flat = cost_models.edge_cost(cost_models.MODEL_HERZOG_METABOLIC, 10.0, 0.0, spec, cost_mode="energy_j")
        c_up = cost_models.edge_cost(cost_models.MODEL_HERZOG_METABOLIC, 10.0, +1.0, spec, cost_mode="energy_j")
        c_45 = cost_models.edge_cost(cost_models.MODEL_HERZOG_METABOLIC, 10.0, -4.5, spec, cost_mode="energy_j")
        c_60 = cost_models.edge_cost(cost_models.MODEL_HERZOG_METABOLIC, 10.0, -6.0, spec, cost_mode="energy_j")
        self.assertLess(c_opt, c_flat)
        self.assertLess(c_flat, c_up)
        self.assertGreater(c_60, c_45)

        # Downhill ramp where Herzog speed exceeds flat speed -> A* must match optimal path
        dem = np.repeat((500.0 - 1.0 * np.arange(8, dtype=np.float64))[None, :], 5, axis=0)
        nodata = np.zeros_like(dem, dtype=bool)
        coords, cost = _astar_path(
            dem, nodata, (2, 0), (2, 7), 10.0, 10.0, True,
            cost_models.MODEL_HERZOG_METABOLIC, spec, cost_mode="energy_j",
        )
        self.assertIsNotNone(coords)
        expected_step = cost_models.edge_cost(cost_models.MODEL_HERZOG_METABOLIC, 10.0, -1.0, spec, cost_mode="energy_j")
        self.assertAlmostEqual(cost, 7.0 * expected_step, places=4)

    def test_cost_network_simplify_hub_direction_and_betw_norm(self):
        # Exact collinearity under arbitrary rotation
        self.assertEqual(cnd._simplify_turn_points([(0.0, 0.0), (3.0, 4.0), (6.0, 8.0), (9.0, 12.0)]), [(0.0, 0.0), (9.0, 12.0)])
        self.assertEqual(cnd._simplify_turn_points([(0.0, 0.0), (3.0, 4.0), (6.0, 0.0)]), [(0.0, 0.0), (3.0, 4.0), (6.0, 0.0)])

        # Sloped DEM: sites 1 & 2 uphill -> hub 0 downhill => asymmetric time_min_ab != time_min_ba
        cols = np.mgrid[0:10, 0:10][1].astype(np.float32)
        dem_path = _write_gtiff(os.path.join(self.tmp, "sloped.tif"), 100.0 + 3.0 * cols)
        nodes = [
            cnd.NetworkNode("0", "Hub0", 200015.0, 499955.0, is_hub=True),
            cnd.NetworkNode("1", "Site1", 200075.0, 499955.0, is_hub=False),
            cnd.NetworkNode("2", "Site2", 200075.0, 499925.0, is_hub=False),
        ]
        worker = cnd.CostNetworkWorker(
            dem_source=dem_path,
            dem_authid="EPSG:5186",
            nodes=nodes,
            allow_diagonal=True,
            pair_buffer_m=100.0,
            candidate_k=3,
            network_mode=cnd.NETWORK_HUB,
            knn_k=2,
            hub_connect_mst=False,
            sym_method=cnd.SYMMETRY_AVG,
            model_key=cost_models.MODEL_TOBLER,
            model_params={},
            model_label="Tobler",
            cost_mode=cnd.COST_TIME,
            on_done=None,
        )
        res = worker._run_impl()
        self.assertTrue(res.ok, res.message)
        hub_edges = [e for e in res.edges if e.kind == "hub_link"]
        self.assertEqual(len(hub_edges), 2)
        for e in hub_edges:
            # Must be oriented site -> hub (not min/max node id)
            self.assertEqual(e.b, 0)
            self.assertGreater(e.a, 0)
            self.assertAlmostEqual(e.coords[0][0], nodes[e.a].x, delta=5.1)
            self.assertAlmostEqual(e.coords[-1][0], nodes[0].x, delta=5.1)

        # Normalized betweenness check via dialog handler
        dlg = cnd.CostNetworkDialog(self.iface)
        self.addCleanup(dlg.close)
        dlg.chkSnaEnable.setChecked(True)
        dlg.chkSnaBetweenness.setChecked(True)
        dlg._handle_task_result(res)
        pts_lyr = next(l for l in QgsProject.instance().mapLayers().values() if isinstance(l, QgsVectorLayer) and l.geometryType() == 0)
        by_fid = {f["fid"]: f for f in pts_lyr.getFeatures()}
        # Star of 3 nodes around hub 0: betw(hub) = 1.0, betw_pairs = (3-1)(3-2)/2 = 1.0 => betw_norm = 1.0
        self.assertAlmostEqual(float(by_fid["0"]["betweenness"]), 1.0, places=6)
        self.assertAlmostEqual(float(by_fid["0"]["betw_norm"]), 1.0, places=6)
        self.assertAlmostEqual(float(by_fid["1"]["betw_norm"]), 0.0, places=6)

    def test_spatial_network_los_nodata_rng_colocated_and_dedup_centrality(self):
        # Undeclared -9999 interior cell must fail LOS (return None = sample failure)
        arr = np.full((6, 6), 100.0, dtype=np.float32)
        arr[2, 2] = -9999.0
        dem_path = _write_gtiff(os.path.join(self.tmp, "undec_nd.tif"), arr, nodata=None)
        dem = QgsRasterLayer(dem_path, "undec_nd", "gdal")
        self.assertTrue(dem.isValid())
        dlg = SpatialNetworkDialog(self.iface)
        self.addCleanup(dlg.close)
        vis = dlg._los_visible(
            dem_layer=dem,
            ax=200005.0, ay=499975.0,
            bx=200055.0, by=499975.0,
            obs_height=2.0, tgt_height=2.0, sample_step_m=5.0,
        )
        self.assertIsNone(vis)

        # Co-located witness points (< 1e-3 m) must not falsely prune valid edges
        coords = np.array([[0.0, 0.0], [1e-4, 0.0], [100.0, 0.0]], dtype=np.float64)
        kept = dlg._ppa_filter_rng(cand_edges={(0, 2)}, coords=coords)
        self.assertIn((0, 2), kept)

        # Repeated parallel undirected edge in adj must still yield clean Brandes centrality
        adj_dup = [
            [(1, 1.0), (1, 1.0)],
            [(0, 1.0), (0, 1.0), (2, 1.0)],
            [(1, 1.0)],
        ]
        bw = nm.betweenness_centrality_weighted(n=3, adj=adj_dup)
        bu = nm.betweenness_centrality_unweighted(n=3, adj=[[1, 1], [0, 0, 2], [1]])
        self.assertAlmostEqual(bw[1], 1.0, places=6)
        self.assertAlmostEqual(bu[1], 1.0, places=6)

    def test_distance_raster_applies_reference_nodata_and_exact_dimensions(self):
        ref_arr = np.full((25, 30), 100.0, dtype=np.float32)
        ref_arr[:5, :5] = -9999.0
        ref_path = _write_gtiff(os.path.join(self.tmp, "ref_nd.tif"), ref_arr, nodata=-9999.0)
        ref_lyr = QgsRasterLayer(ref_path, "ref_nd", "gdal")
        QgsProject.instance().addMapLayer(ref_lyr)

        tgt = self._mem("Point", "water_pt", [("id", FT_INT)], [("POINT(200155 499855)", [1])])
        QgsProject.instance().addMapLayer(tgt)

        dlg = DistanceRasterDialog(self.iface)
        self.addCleanup(dlg.close)
        dlg.cmbRef.setLayer(ref_lyr)
        dlg.cmbSource.setLayer(tgt)
        dlg.chkSelectedOnly.setChecked(False)
        dlg.spinMaxDistance.setValue(0.0)
        dlg.txtVariable.setText("water_r3")
        dlg._on_run()

        out_lyrs = [
            l for l in QgsProject.instance().mapLayers().values()
            if isinstance(l, QgsRasterLayer) and l.id() != ref_lyr.id()
        ]
        self.assertEqual(len(out_lyrs), 1)
        out_tif = out_lyrs[0].source().split("|", 1)[0]
        out_id = out_lyrs[0].id()

        def _cleanup_out(p=out_tif, lid=out_id):
            if QgsProject.instance().mapLayer(lid) is not None:
                QgsProject.instance().removeMapLayer(lid)
            if os.path.exists(p):
                os.remove(p)

        self.addCleanup(_cleanup_out)
        ds = gdal.Open(out_tif)
        self.assertEqual((ds.RasterXSize, ds.RasterYSize), (30, 25))
        dist = ds.GetRasterBand(1).ReadAsArray()
        ds = None
        # Reference NoData cells in [:5, :5] must remain DISTANCE_NODATA
        self.assertTrue(np.all(dist[:5, :5] == DISTANCE_NODATA))
        self.assertGreaterEqual(float(dist[15, 15]), 0.0)

    # --- Stage 5 ----------------------------------------------------------
    def test_ahp_reclass_gapped_vs_abutting_upper_bounds(self):
        expr_gap = ahp_core.score_formula(
            direction="reclass", mn=0.0, mx=10.0,
            score_ranges=[{"min": 1.0, "max": 2.0, "score": 0.4}, {"min": 3.0, "max": 4.0, "score": 0.8}],
        )
        expr_abut = ahp_core.score_formula(
            direction="reclass", mn=0.0, mx=10.0,
            score_ranges=[{"min": 1.0, "max": 2.0, "score": 0.4}, {"min": 2.0, "max": 3.0, "score": 0.8}],
        )
        for val, exp_gap, exp_abut in ((2.0, 0.4, 0.8), (3.0, 0.8, 0.8), (2.5, 0.0, 0.8)):
            self.assertAlmostEqual(float(eval(expr_gap, {"__builtins__": {}}, {"A": val})), exp_gap, places=6)
            self.assertAlmostEqual(float(eval(expr_abut, {"__builtins__": {}}, {"A": val})), exp_abut, places=6)

    def test_trench_ridge_exclusion_and_covariate_unchecked_defaults(self):
        for ridge in ("남릉", "북릉", "동릉", "서릉", "주릉", "지릉", "산릉", "사면릉", "정상릉", "세장릉", "능지", "구릉지", "능선"):
            self.assertFalse(_text_has_grave_keyword(f"조사구 {ridge} 사면"), ridge)
        for tomb in ("무녕왕릉", "선릉", "천마총", "공동묘지"):
            self.assertTrue(_text_has_grave_keyword(tomb), tomb)

        # CovariateReportDialog skips map_styling & circular layers on auto-check + warns on circular/small sample
        hs_p = _write_gtiff(os.path.join(self.tmp, "hs.tif"), np.full((10, 10), 120.0, np.float32))
        asp_p = _write_gtiff(os.path.join(self.tmp, "asp.tif"), np.full((10, 10), 45.0, np.float32))
        slp_p = _write_gtiff(os.path.join(self.tmp, "slp.tif"), np.full((10, 10), 12.0, np.float32))
        hs = QgsRasterLayer(hs_p, "Hillshade", "gdal")
        asp = QgsRasterLayer(asp_p, "Aspect", "gdal")
        slp = QgsRasterLayer(slp_p, "Slope", "gdal")
        set_archtoolkit_layer_metadata(hs, tool_id="map_styling", run_id="r1", kind="dem_hillshade", units="m")
        set_archtoolkit_layer_metadata(asp, tool_id="terrain_analysis", run_id="r1", kind="aspect", units="deg")
        set_archtoolkit_layer_metadata(slp, tool_id="terrain_analysis", run_id="r1", kind="slope", units="deg")
        QgsProject.instance().addMapLayers([hs, asp, slp])

        dlg = CovariateReportDialog(self.iface)
        self.addCleanup(dlg.close)
        checked = {lyr.id() for lyr in dlg._selected_layers()}
        self.assertNotIn(hs.id(), checked)
        self.assertNotIn(asp.id(), checked)
        self.assertIn(slp.id(), checked)

        # VIF with too few samples (n <= k + 2) must return NaNs instead of collinearity estimates
        X_small = np.array([[1.0, 2.0], [2.0, 4.0], [3.0, 6.0], [4.0, 8.0]], dtype=np.float64)
        vifs = crd._compute_vif(X_small)
        self.assertEqual(len(vifs), 2)
        self.assertTrue(all(math.isnan(float(v)) for v in vifs))

    # --- Stage 6 ----------------------------------------------------------
    def test_geology_conflicting_lithoidx_disambiguated_in_merge_and_per_layer(self):
        fields = [("LITHO", FT_STRING), ("LITHOIDX", FT_INT), ("LITHONAME", FT_STRING)]
        rA = QgsGeometry.fromWkt("POLYGON((200000 499900, 200100 499900, 200100 500000, 200000 500000, 200000 499900))")
        rB1 = QgsGeometry.fromWkt("POLYGON((200100 499900, 200200 499900, 200200 500000, 200100 500000, 200100 499900))")
        rB2 = QgsGeometry.fromWkt("POLYGON((200200 499900, 200300 499900, 200300 500000, 200200 500000, 200200 499900))")
        lyr_a = self._mem("Polygon", "SheetA", fields, [(rA, ["Kgr", 5, "Granite"])])
        lyr_b = self._mem("Polygon", "SheetB", fields, [(rB1, ["B", 5, "Basalt"]), (rB2, ["Qa", 1, "Alluvium"])])
        QgsProject.instance().addMapLayers([lyr_a, lyr_b])

        dlg = GeologyZipDialog(self.iface)
        self.addCleanup(dlg.close)
        dlg.chkKigamOnly.setChecked(False)
        dlg.chkLithoOnly.setChecked(False)
        dlg.refresh_layer_list()
        for i in range(dlg.lstLayers.count()):
            dlg.lstLayers.item(i).setCheckState(Qt.CheckState.Checked)
        dlg._refresh_field_choices()

        smap, slab, lall, conf = dlg._build_shared_code_mapping([lyr_a, lyr_b], "LITHOIDX", numeric=True)
        self.assertEqual(conf, [("5", ["Granite", "Basalt"])])
        self.assertNotEqual(smap["5::Granite"], smap["5::Basalt"])
        self.assertNotIn(smap["5::Granite"], (1, 5))
        self.assertNotIn(smap["5::Basalt"], (1, 5))
        self.assertEqual(smap["1"], 1)

        # Merge mode run
        merge_tif = os.path.join(self.tmp, "merged_geo.tif")
        dlg.cmbField.setCurrentIndex(dlg.cmbField.findText("LITHOIDX"))
        dlg.radMerge.setChecked(True)
        dlg.txtOutFile.setText(merge_tif)
        dlg.spinPixel.setValue(10.0)
        dlg.cmbFormat.setCurrentIndex(dlg.cmbFormat.findData("tif"))
        dlg._run_rasterize()

        ds = gdal.Open(merge_tif)
        self.assertIsNotNone(ds)
        arr = ds.GetRasterBand(1).ReadAsArray()
        ds = None
        uniq_vals = set(int(v) for v in np.unique(arr))
        self.assertIn(smap["5::Granite"], uniq_vals)
        self.assertIn(smap["5::Basalt"], uniq_vals)
        self.assertIn(1, uniq_vals)
        self.assertTrue(any("지질도 코드 충돌" in str(m) for m in self.iface._bar.messages))

        with open(os.path.splitext(merge_tif)[0] + "_mapping.csv", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        by_code = {r["code"]: r for r in rows}
        self.assertEqual(by_code["5::Granite"]["labels_all"], "Granite|Basalt")
        self.assertEqual(by_code["5::Basalt"]["label"], "Basalt")

        merged_r = next(l for l in QgsProject.instance().mapLayers().values() if isinstance(l, QgsRasterLayer))
        meta_params = json.loads(merged_r.customProperty("archtoolkit/params_json") or "{}")
        self.assertEqual(meta_params.get("code_conflicts"), 1)

        # Per-layer mode also warns and disambiguates across sheets
        QgsProject.instance().removeAllMapLayers()
        lyr_a2 = self._mem("Polygon", "SheetA2", fields, [(rA, ["Kgr", 5, "Granite"])])
        lyr_b2 = self._mem("Polygon", "SheetB2", fields, [(rB1, ["B", 5, "Basalt"]), (rB2, ["Qa", 1, "Alluvium"])])
        QgsProject.instance().addMapLayers([lyr_a2, lyr_b2])
        per_dir = os.path.join(self.tmp, "per_layer")
        os.makedirs(per_dir)
        self.iface._bar.messages.clear()
        dlg2 = GeologyZipDialog(self.iface)
        self.addCleanup(dlg2.close)
        dlg2.chkKigamOnly.setChecked(False)
        dlg2.chkLithoOnly.setChecked(False)
        dlg2.refresh_layer_list()
        for i in range(dlg2.lstLayers.count()):
            dlg2.lstLayers.item(i).setCheckState(Qt.CheckState.Checked)
        dlg2._refresh_field_choices()
        dlg2.cmbField.setCurrentIndex(dlg2.cmbField.findText("LITHOIDX"))
        dlg2.radPerLayer.setChecked(True)
        dlg2.txtOutDir.setText(per_dir)
        dlg2.spinPixel.setValue(10.0)
        dlg2.cmbFormat.setCurrentIndex(dlg2.cmbFormat.findData("tif"))
        dlg2._run_rasterize()
        self.assertTrue(any("지질도 코드 충돌" in str(m) for m in self.iface._bar.messages))

    def test_geochem_halo_preserves_legend_stops_and_flags_blur(self):
        # Black line across rows 0..9, col 4; dark legend stops adjacent on col 3 & 5;
        # half-black blurred edge (115, 0, 0) next to red (230, 0, 0) in rows 5..9
        rgb = np.zeros((3, 10, 10), dtype=np.uint8)
        rgb[:, :5, :] = np.array([115, 12, 12])[:, None, None]  # exact Fe2O3 stop 10
        rgb[:, :5, :3] = np.array([0, 38, 115])[:, None, None]  # navy stop
        rgb[:, 5:, :] = np.array([230, 0, 0])[:, None, None]
        rgb[:, :, 4] = 0  # black 1-px line
        rgb[:, 5:, 3] = np.array([115, 0, 0])[:, None]
        rgb[:, 5:, 5] = np.array([115, 0, 0])[:, None]

        core = GL.mask_black_lines(*rgb)
        palette = [(0, 38, 115), (0, 255, 0), (255, 255, 0), (230, 0, 0), (115, 12, 12)]
        halo = GL.mask_colour_halo(*rgb, core=core, palette=palette)
        self.assertFalse(halo[:5, [3, 5]].any(), "Valid stop (115, 12, 12) adjacent to black line was masked as halo")
        self.assertTrue(halo[5:, [3, 5]].all(), "Half-black anti-aliased edge must still be masked as halo")

    def test_map_styling_open_3v_wall_and_cadastral_pct_clamp(self):
        c5186 = QgsCoordinateReferenceSystem("EPSG:5186")
        open_wall = QgsGeometry.fromWkt("LINESTRING(200100 499500, 200110 499500, 200110 499510)")
        geom_wall, info_wall = MapStylingDialog._building_polygon(open_wall, c5186)
        self.assertIsNotNone(geom_wall)
        self.assertEqual(info_wall["degenerate_buffered"], 1)
        # Buffered wall (width=0.6 m x 20 m length) << hallucinated 50 m^2 triangle
        self.assertLess(geom_wall.area(), 25.0)

        closed_box = QgsGeometry.fromWkt("LINESTRING(200100 499500, 200110 499500, 200110 499510, 200100 499510, 200100 499500)")
        geom_box, info_box = MapStylingDialog._building_polygon(closed_box, c5186)
        self.assertEqual(info_box["degenerate_buffered"], 0)
        self.assertAlmostEqual(geom_box.area(), 100.0, places=6)

        # Cadastral overlap pct clamps <= 100.0 even under ellipsoidal/planar ratio jitter
        aoi = self._mem("Polygon", "aoi_cad", [("id", FT_INT)], [("POLYGON((200000 499800, 200200 499800, 200200 500000, 200000 500000, 200000 499800))", [1])])
        cad = self._mem("Polygon", "parcels", [("pnu", FT_STRING)], [("POLYGON((200050 499850, 200150 499850, 200150 499950, 200050 499950, 200050 499850))", ["11110-1"])])
        QgsProject.instance().addMapLayers([aoi, cad])
        cdlg = CadastralOverlapDialog(self.iface)
        self.addCleanup(cdlg.close)
        cdlg.cmbSurvey.setLayer(aoi)
        cdlg.chkSurveySelected.setChecked(False)
        cdlg.cmbCadastral.setLayer(cad)
        cdlg.chkCadastralSelected.setChecked(False)
        cdlg.run()
        out_l = next(l for l in QgsProject.instance().mapLayers().values() if isinstance(l, QgsVectorLayer) and "지적" in l.name())
        for f in out_l.getFeatures():
            self.assertLessEqual(float(f["in_aoi_pct"]), 100.0)

    def test_ai_summary_integer_categorical_metric_dist_and_bundle_sync(self):
        # 1) Int32 un-metadated class raster auto-promotes, Float32 stays continuous, undeclared -9999 masked
        cls_arr = np.full((30, 30), 2, dtype=np.int32)
        cls_arr[:10, :] = 1
        flt_arr = cls_arr.astype(np.float32)
        flt_arr[0, 0] = -9999.0  # undeclared NoData sentinel
        cls_tif = _write_gtiff(os.path.join(self.tmp, "int_cls.tif"), cls_arr, dtype=gdal.GDT_Int32)
        flt_tif = _write_gtiff(os.path.join(self.tmp, "flt_cont.tif"), flt_arr, nodata=None, dtype=gdal.GDT_Float32)

        aoi_geom = QgsGeometry.fromWkt("POLYGON((200000 499700, 200300 499700, 200300 500000, 200000 500000, 200000 499700))")
        st_cls = ai_aoi_summary._raster_stats_in_geom(cls_tif, aoi_geom, categorical=False)
        st_flt = ai_aoi_summary._raster_stats_in_geom(flt_tif, aoi_geom, categorical=False)
        self.assertTrue(st_cls["categorical"])
        self.assertTrue(st_cls["auto_categorical"])
        self.assertNotIn("mean", st_cls)
        self.assertNotIn("categorical", st_flt)
        self.assertGreater(float(st_flt["min"]), 0.0)  # -9999 excluded

        # 2) _reference_sites_summary with geographic EPSG:4326 AOI -> distance_to_aoi_m must be metric (~m, not degrees)
        aoi4326 = self._mem("Polygon", "aoi4326", [("id", FT_INT)], [("POLYGON((127.0 37.0, 127.01 37.0, 127.01 37.01, 127.0 37.01, 127.0 37.0))", [1])], epsg=4326)
        site4326 = self._mem("Point", "site4326", [("name", FT_STRING)], [("POINT(127.02 37.005)", ["S1"])], epsg=4326)
        g_aoi4 = next(aoi4326.getFeatures()).geometry()
        ref4326 = ai_aoi_summary._reference_sites_summary(
            layer=site4326,
            aoi_geom=g_aoi4,
            buffer_geom=g_aoi4.buffer(0.05, 8),
            aoi_centroid_pt=QgsPointXY(127.005, 37.005),
            aoi_crs=aoi4326.crs(),
            selected_only=False,
            preferred_name_field="name",
        )
        dist_m = float(ref4326["items"][0]["distance_to_aoi_m"])
        self.assertGreater(dist_m, 500.0)

        # 3) _on_export_bundle regenerates report.md if AOI/context changed after Generate
        aoi_a = self._mem("Polygon", "AOI_First", [("id", FT_INT)], [("POLYGON((200000 499700, 200300 499700, 200300 500000, 200000 500000, 200000 499700))", [1])])
        aoi_b = self._mem("Polygon", "AOI_Second", [("id", FT_INT)], [("POLYGON((200000 499700, 200300 499700, 200300 500000, 200000 500000, 200000 499700))", [1])])
        QgsProject.instance().addMapLayers([aoi_a, aoi_b])
        dlg = AiAoiReportDialog(self.iface)
        self.addCleanup(dlg.close)
        dlg.cmbAoi.setLayer(aoi_a)
        dlg.cmbProvider.setCurrentIndex(dlg.cmbProvider.findData("local"))
        dlg.cmbLayerScope.setCurrentIndex(dlg.cmbLayerScope.findData("auto"))
        dlg.spinRadius.setValue(500.0)
        dlg._on_generate()
        self.assertIn("AOI_First", dlg.txtOutput.toPlainText())

        # Change AOI without re-clicking Generate, then export bundle
        dlg.cmbAoi.setLayer(aoi_b)
        b_root = os.path.join(self.tmp, "bundles")
        os.makedirs(b_root)
        from unittest import mock
        with mock.patch("tools.ai_report_dialog.QtWidgets.QFileDialog.getExistingDirectory", return_value=b_root):
            dlg._on_export_bundle()
        folders = os.listdir(b_root)
        self.assertEqual(len(folders), 1)
        bdir = os.path.join(b_root, folders[0])
        with open(os.path.join(bdir, "report.md"), encoding="utf-8") as fh:
            rep = fh.read()
        self.assertIn("AOI_Second", rep)
        self.assertNotIn("AOI_First", rep.splitlines()[0] + "\n" + rep.splitlines()[1])


if __name__ == "__main__":
    unittest.main()
