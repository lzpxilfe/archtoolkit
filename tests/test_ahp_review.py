"""QGIS integration tests for the AHP suitability review fixes.

Runs the real dialog end to end (GDAL warp + raster calculator) on small
synthetic rasters whose answer is known, and pins the fixes from the review:
constant criteria, clamped target/range values, the 0-100 colour ramp, the
hierarchy's own consistency ratios, stale statistics, an AOI outside the
raster, reproducible metadata, the AOI layer-name suffix and the reference
pixel lattice.  Skipped (not failed) without PyQGIS/GDAL/Processing.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
    import numpy as np
    from osgeo import gdal, osr
    from qgis.core import (
        QgsApplication,
        QgsFeature,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsVectorLayer,
    )
    from qgis.gui import QgsMapCanvas

    from processing.core.Processing import Processing
    from tools.ahp_suitability_dialog import AhpSuitabilityDialog, _SCALE_OPTIONS, _nearest_scale_index
    from tools.utils import get_archtoolkit_layer_metadata

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc


_X0 = 200000.0
_Y0 = 500000.0
_PX = 10.0


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class AhpReviewQgisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_memory_env = os.environ.get("ARCHTOOLKIT_NO_DIALOG_MEMORY")
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
        registry = QgsApplication.processingRegistry()
        for alg in ("gdal:warpreproject", "gdal:rastercalculator", "gdal:cliprasterbyextent"):
            if registry.algorithmById(alg) is None:
                raise unittest.SkipTest(f"QGIS GDAL provider is unavailable ({alg})")
        # gdal:rastercalculator shells out to gdal_calc.py, whose shebang may
        # name a Python without GDAL bindings; the regression harness writes
        # wrappers that re-exec it with this interpreter.
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "regression"))
        try:
            import qgis_env
        finally:
            sys.path.pop(0)
        qgis_env.ensure_gdal_shims()
        cls.canvas = QgsMapCanvas()
        cls.iface = qgis_env.FakeIface(cls.canvas)

    # No exitQgis(): a QgsApplication cannot be re-created in the same process
    # (see tests/test_align_export_qgis.py).
    @classmethod
    def tearDownClass(cls):
        if cls._old_memory_env is None:
            os.environ.pop("ARCHTOOLKIT_NO_DIALOG_MEMORY", None)
        else:
            os.environ["ARCHTOOLKIT_NO_DIALOG_MEMORY"] = cls._old_memory_env

    def setUp(self):
        QgsProject.instance().removeAllMapLayers()
        self.iface._bar.messages.clear()
        self.tmp = tempfile.mkdtemp(prefix="archtoolkit_ahp_review_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(QgsProject.instance().removeAllMapLayers)

    # ------------------------------------------------------------ helpers
    def _raster(self, name, arr, *, nodata=-9999.0):
        path = os.path.join(self.tmp, f"{name}.tif")
        nrows, ncols = arr.shape
        ds = gdal.GetDriverByName("GTiff").Create(path, ncols, nrows, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((_X0, _PX, 0.0, _Y0, 0.0, -_PX))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(5186)
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(nodata)
        band.WriteArray(np.asarray(arr, dtype=np.float32))
        band.FlushCache()
        ds = None
        layer = self.iface.addRasterLayer(path, name)
        self.assertTrue(layer.isValid())
        return layer

    @staticmethod
    def _aoi(name, xmin, ymin, xmax, ymax):
        layer = QgsVectorLayer("Polygon?crs=EPSG:5186", name, "memory")
        feat = QgsFeature()
        ring = [QgsPointXY(xmin, ymin), QgsPointXY(xmax, ymin), QgsPointXY(xmax, ymax), QgsPointXY(xmin, ymax), QgsPointXY(xmin, ymin)]
        feat.setGeometry(QgsGeometry.fromPolygonXY([ring]))
        layer.dataProvider().addFeatures([feat])
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        return layer

    def _dialog(self, criteria, *, aoi=None, clip=True, scale100=False):
        d = AhpSuitabilityDialog(self.iface)
        self.addCleanup(d.deleteLater)
        for layer, direction in criteria:
            d.cmbRaster.setLayer(layer)
            d.cmbDirection.setCurrentIndex(d.cmbDirection.findData(direction))
            d._on_add_criterion()
        d.cmbAoi.setLayer(aoi)
        d.chkClipToAoiExtent.setChecked(clip)
        d.chkAlignToFirst.setChecked(True)
        d.chkScale100.setChecked(scale100)
        d.chkAddToProject.setChecked(True)
        captured = {}
        original = d._add_output_to_project

        def _capture(*args, **kwargs):
            captured["layer"] = original(*args, **kwargs)
            return captured["layer"]

        d._add_output_to_project = _capture
        d._captured = captured
        return d

    @staticmethod
    def _pair(d, i, j, value):
        cmb = d.tblPairwise.cellWidget(i, j)
        k = cmb.findData(float(value))
        if k < 0:
            raise AssertionError(f"scale value {value} not offered")
        cmb.setCurrentIndex(k)

    def _run(self, d, name="out"):
        self.iface._bar.messages.clear()
        out = os.path.join(self.tmp, f"{name}.tif")
        d.txtOut.setText(out)
        d._on_run()
        return out

    def _messages(self):
        return [" | ".join(str(a) for a in args[:2]) for args, _kw in self.iface.pushed()]

    @staticmethod
    def _read(path):
        ds = gdal.Open(path)
        band = ds.GetRasterBand(1)
        arr = band.ReadAsArray().astype(np.float64)
        nodata = band.GetNoDataValue()
        gt = ds.GetGeoTransform()
        ds = None
        return arr, nodata, gt

    def _params(self, d):
        layer = d._captured.get("layer")
        self.assertIsNotNone(layer, f"no output layer; messages: {self._messages()}")
        return get_archtoolkit_layer_metadata(layer).get("params") or {}

    @staticmethod
    def _eig_weights(mat):
        vals, vecs = np.linalg.eig(np.asarray(mat, dtype=float))
        k = int(np.argmax(vals.real))
        v = np.abs(vecs[:, k].real)
        return v / v.sum(), float(vals[k].real)

    @staticmethod
    def _grid(n=20):
        yy, xx = np.mgrid[0:n, 0:n].astype(np.float64)
        return yy, xx

    # ------------------------------------------------------------ known answer
    def test_known_answer_weights_scores_nodata_and_metadata(self):
        yy, xx = self._grid()
        c1 = xx.copy()
        c2 = yy.copy()
        c3 = xx + yy
        c1[5, 5] = -9999.0
        c2[7, 8] = -9999.0
        l1, l2, l3 = self._raster("C1", c1), self._raster("C2", c2), self._raster("C3", c3)
        d = self._dialog([(l1, "benefit"), (l2, "cost"), (l3, "benefit")])
        self._pair(d, 0, 1, 3.0)
        self._pair(d, 0, 2, 5.0)
        self._pair(d, 1, 2, 2.0)
        w, lam = self._eig_weights([[1, 3, 5], [1 / 3, 1, 2], [1 / 5, 1 / 2, 1]])
        out = self._run(d)

        for got, exp in zip([c.weight for c in d._criteria], w):
            self.assertAlmostEqual(got, exp, places=6)
        arr, nodata, _gt = self._read(out)
        expected = w[0] * c1 / 19.0 + w[1] * (19.0 - c2) / 19.0 + w[2] * c3 / 38.0
        valid = (c1 != -9999.0) & (c2 != -9999.0)
        np.testing.assert_allclose(arr[valid], expected[valid], atol=1e-6)
        self.assertEqual(arr[5, 5], nodata)
        self.assertEqual(arr[7, 8], nodata)

        params = self._params(d)
        self.assertAlmostEqual(params["consistency_ratio"], ((lam - 3.0) / 2.0) / 0.58, places=6)
        self.assertEqual(params["weights_source"], "pairwise_matrix")
        # Fix 7: the flat judgements travel with the layer.
        values = sorted(round(p["value"], 6) for p in params["pairwise"])
        self.assertEqual(values, [2.0, 3.0, 5.0])

    # ------------------------------------------------------------ fix 1
    def test_constant_benefit_criterion_scores_half_and_is_reported(self):
        yy, xx = self._grid()
        l1 = self._raster("Ramp", xx)
        l2 = self._raster("Flat", np.full(xx.shape, 7.0))
        d = self._dialog([(l1, "benefit"), (l2, "benefit")])
        arr, _nd, _gt = self._read(self._run(d))
        np.testing.assert_allclose(arr, 0.5 * xx / 19.0 + 0.5 * 0.5, atol=1e-6)
        self.assertTrue(any("'Flat'" in m and "0.5" in m for m in self._messages()), self._messages())
        const = self._params(d)["constant_criteria"]
        self.assertEqual([(c["layer_name"], c["score"]) for c in const], [("Flat", 0.5)])

    def test_constant_reclass_range_and_target_use_their_mode(self):
        yy, xx = self._grid()
        l1 = self._raster("Ramp", xx)
        cases = [
            ("reclass", {"score_ranges": [{"min": 7.0, "max": 7.0, "score": 1.0}]}, 1.0),
            ("range", {"prefer_min": 5.0, "prefer_max": 10.0}, 1.0),
            ("range", {"prefer_min": 8.0, "prefer_max": 10.0}, 0.0),
            ("target", {"target_v": 7.0}, 1.0),
        ]
        for mode, attrs, score in cases:
            with self.subTest(mode=mode, attrs=attrs):
                l2 = self._raster(f"Flat_{mode}_{score}", np.full(xx.shape, 7.0))
                d = self._dialog([(l1, "benefit"), (l2, "benefit")])
                d._criteria[1].direction = mode
                for key, value in attrs.items():
                    setattr(d._criteria[1], key, value)
                arr, _nd, _gt = self._read(self._run(d, f"out_{mode}_{score}"))
                np.testing.assert_allclose(arr, 0.5 * xx / 19.0 + 0.5 * score, atol=1e-6)

    # ------------------------------------------------------------ fix 2
    def test_out_of_range_preferences_are_clamped_and_reported(self):
        yy, xx = self._grid()
        l1 = self._raster("Slope", xx)
        d = self._dialog([(l1, "benefit")])
        d._compute_all_stats(force=True)
        crit = d._criteria[0]
        crit.direction = "range"
        crit.prefer_min, crit.prefer_max = 5.0, 25.0
        notes = d._ensure_criterion_preference_defaults(crit)
        self.assertEqual((crit.prefer_min, crit.prefer_max), (5.0, 19.0))
        self.assertTrue(notes and "5.0000-25.0000" in notes[0] and "5.0000-19.0000" in notes[0], notes)
        crit.prefer_min, crit.prefer_max = 30.0, 40.0  # entirely outside: default interval
        notes = d._ensure_criterion_preference_defaults(crit)
        self.assertEqual((crit.prefer_min, crit.prefer_max), (4.75, 14.25))
        self.assertTrue(notes, "defaulting a user interval must be reported")
        crit.prefer_min, crit.prefer_max = 6.0, 12.0  # inside: untouched, silent
        self.assertEqual(d._ensure_criterion_preference_defaults(crit), [])
        self.assertEqual((crit.prefer_min, crit.prefer_max), (6.0, 12.0))

    def test_target_above_the_data_becomes_a_benefit_ramp(self):
        yy, xx = self._grid()
        l1 = self._raster("Slope", xx)
        d = self._dialog([(l1, "benefit")])
        d._criteria[0].direction = "target"
        d._criteria[0].target_v = 25.0
        arr, _nd, _gt = self._read(self._run(d))
        self.assertEqual(d._criteria[0].target_v, 19.0)
        # Clamped to the maximum: "higher is better", not the old midpoint tent.
        np.testing.assert_allclose(arr, xx / 19.0, atol=1e-6)
        self.assertTrue(any("'Slope'" in m and "25.0000 -> 19.0000" in m for m in self._messages()), self._messages())
        crit_meta = self._params(d)["criteria"][0]
        self.assertEqual((crit_meta["direction"], crit_meta["target_v"]), ("target", 19.0))

    # ------------------------------------------------------------ fix 3
    def test_colour_ramp_follows_the_0_100_scale(self):
        yy, xx = self._grid()
        d = self._dialog([(self._raster("C1", xx), "benefit")], scale100=True)
        arr, _nd, _gt = self._read(self._run(d))
        self.assertAlmostEqual(float(arr.max()), 100.0, places=4)
        shader = d._captured["layer"].renderer().shader().rasterShaderFunction()
        self.assertEqual([it.value for it in shader.colorRampItemList()], [0.0, 50.0, 100.0])
        self.assertNotEqual(shader.shade(10.0)[1:4], shader.shade(100.0)[1:4])

    # ------------------------------------------------------------ fix 4
    def test_hierarchy_reports_its_own_consistency_ratios(self):
        yy, xx = self._grid(10)
        layers = [self._raster(f"K{i}", xx + i * yy) for i in range(4)]
        d = self._dialog([(lyr, "benefit") for lyr in layers])
        ids = [c.layer_id for c in d._criteria]
        cfg = {
            "criterion_groups": {ids[0]: "G1", ids[1]: "G1", ids[2]: "G2", ids[3]: "G2"},
            "group_pairs": {("G1", "G2"): 5.0},
            "local_pairs": {"G1": {(ids[0], ids[1]): 3.0}, "G2": {(ids[2], ids[3]): 0.5}},
        }
        self.assertTrue(d._apply_hierarchy_config(cfg))
        # The snapped flat seed is not perfectly consistent...
        _w, seed_lam = self._eig_weights(d._build_pairwise_matrix())
        self.assertGreater(seed_lam - 4.0, 1e-3)
        # ...but the user's judgements are, and that is what is shown and stored.
        self.assertIn("CR(그룹 간)=0.000", d.lblConsistency.text())
        self.assertIn("CR(그룹 내 최대)=0.000", d.lblConsistency.text())
        self._run(d)
        self.assertFalse(any("CR" in m and "높습니다" in m for m in self._messages()), self._messages())
        params = self._params(d)
        self.assertIsNone(params["consistency_ratio"])
        self.assertAlmostEqual(params["consistency_ratio_group"], 0.0, places=9)
        self.assertAlmostEqual(params["consistency_ratio_local_max"], 0.0, places=9)
        for got, exp in zip([c.weight for c in d._criteria], [0.625, 0.625 / 3.0, 0.5 / 9.0, 1.0 / 9.0]):
            self.assertAlmostEqual(got, exp, places=6)

    def test_inconsistent_group_judgements_are_warned_by_group_cr(self):
        yy, xx = self._grid(10)
        layers = [self._raster(f"K{i}", xx + i * yy) for i in range(3)]
        d = self._dialog([(lyr, "benefit") for lyr in layers])
        ids = [c.layer_id for c in d._criteria]
        cfg = {
            "criterion_groups": {ids[0]: "A", ids[1]: "B", ids[2]: "C"},
            "group_pairs": {("A", "B"): 9.0, ("B", "C"): 9.0, ("A", "C"): 1.0 / 9.0},
            "local_pairs": {},
        }
        self.assertTrue(d._apply_hierarchy_config(cfg))
        self._run(d)
        self.assertTrue(any("그룹 간 CR" in m for m in self._messages()), self._messages())
        self.assertGreater(self._params(d)["consistency_ratio_group"], 0.10)

    def test_seed_snapping_is_reciprocal(self):
        for ratio in (1.4, 1.6, 2.4, 2.6, 4.4, 8.6, 12.0):
            with self.subTest(ratio=ratio):
                up = _SCALE_OPTIONS[_nearest_scale_index(ratio)][1]
                down = _SCALE_OPTIONS[_nearest_scale_index(1.0 / ratio)][1]
                self.assertAlmostEqual(up * down, 1.0, places=12)

    # ------------------------------------------------------------ fix 5
    def test_statistics_from_another_aoi_setting_are_recomputed(self):
        yy, xx = self._grid(60)
        l1 = self._raster("C1", xx)
        aoi = self._aoi("AOI", _X0 + 100, _Y0 - 300, _X0 + 300, _Y0 - 100)
        d = self._dialog([(l1, "benefit")])
        d._on_compute_stats()
        self.assertEqual((d._criteria[0].min_v, d._criteria[0].max_v), (0.0, 59.0))
        d.cmbAoi.setLayer(aoi)
        arr, _nd, _gt = self._read(self._run(d))
        self.assertEqual((d._criteria[0].min_v, d._criteria[0].max_v), (10.0, 29.0))
        self.assertAlmostEqual(float(arr.min()), 0.0, places=6)
        self.assertAlmostEqual(float(arr.max()), 1.0, places=6)
        self.assertTrue(any("다시 계산" in m and "C1" in m for m in self._messages()), self._messages())

    # ------------------------------------------------------------ fix 6
    def test_aoi_outside_the_raster_stops_with_an_error(self):
        yy, xx = self._grid()
        l1 = self._raster("C1", xx)
        far = self._aoi("Far", _X0 + 100000, _Y0 + 100000, _X0 + 100100, _Y0 + 100100)
        d = self._dialog([(l1, "benefit")], aoi=far)
        d._on_compute_stats()
        self.assertIsNone(d._criteria[0].min_v)
        self.assertTrue(any("AOI가 래스터와 겹치지 않습니다" in m for m in self._messages()), self._messages())
        out = self._run(d)
        self.assertFalse(os.path.exists(out))
        self.assertTrue(any("AOI가 래스터와 겹치지 않습니다" in m for m in self._messages()), self._messages())

    # ------------------------------------------------------------ fix 7 (modes) / fix 8
    def test_metadata_keeps_mode_parameters_and_aoi_name_only_when_clipped(self):
        yy, xx = self._grid()
        l1 = self._raster("C1", xx)
        l2 = self._raster("Geo", (xx // 5) + 1)
        aoi = self._aoi("MyAOI", _X0 + 50, _Y0 - 150, _X0 + 150, _Y0 - 50)
        table = [{"min": 1.0, "max": 1.0, "score": 0.2}, {"min": 2.0, "max": 4.0, "score": 1.0}]
        d = self._dialog([(l1, "benefit"), (l2, "benefit")], aoi=aoi, clip=False)
        d._criteria[0].direction = "range"
        d._criteria[0].prefer_min, d._criteria[0].prefer_max = 5.0, 10.0
        d._criteria[1].direction = "reclass"
        d._criteria[1].score_ranges = table
        self._run(d)
        self.assertEqual(d._captured["layer"].name(), "AHP Suitability")
        params = self._params(d)
        self.assertFalse(params["aoi_applied"])
        c0, c1 = params["criteria"]
        self.assertEqual((c0["direction"], c0["prefer_min"], c0["prefer_max"]), ("range", 5.0, 10.0))
        self.assertEqual((c1["direction"], c1["score_ranges"]), ("reclass", table))

        d.chkClipToAoiExtent.setChecked(True)
        self._run(d, "out_clipped")
        self.assertEqual(d._captured["layer"].name(), "AHP Suitability (MyAOI)")
        self.assertTrue(self._params(d)["aoi_applied"])

    # ------------------------------------------------------------ fix 9
    def test_off_lattice_aoi_keeps_the_reference_pixel_grid(self):
        yy, xx = self._grid(60)
        l1 = self._raster("C1", xx)
        aoi = self._aoi("Offset", _X0 + 103, _Y0 - 297, _X0 + 303, _Y0 - 97)
        d = self._dialog([(l1, "benefit")], aoi=aoi)
        arr, _nd, gt = self._read(self._run(d))
        col0 = (gt[0] - _X0) / _PX
        row0 = (_Y0 - gt[3]) / _PX
        self.assertAlmostEqual(col0, round(col0), places=6)
        self.assertAlmostEqual(row0, round(row0), places=6)
        self.assertEqual((gt[1], gt[5]), (_PX, -_PX))
        # The AOI bounding box is covered (snapped outward, never inward).
        self.assertLessEqual(gt[0], _X0 + 103)
        self.assertGreaterEqual(gt[3], _Y0 - 97)
        # No sub-pixel resampling: every cell is the reference value itself.
        mn, mx = d._criteria[0].min_v, d._criteria[0].max_v
        cols = int(round(col0)) + np.arange(arr.shape[1])
        expected = np.clip((cols[None, :] - mn) / (mx - mn), 0.0, 1.0) * np.ones((arr.shape[0], 1))
        np.testing.assert_allclose(arr, expected, atol=1e-6)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
