"""QGIS integration tests for the correlation / VIF report (covariate_report_dialog).

Known-answer checks drive the real dialog on synthetic rasters whose Pearson
matrix and VIFs are computed independently with NumPy, plus the review fixes:
the AOI polygon (not its bounding box) limits the sample, the grid never has
more points than the first raster has cells, a cancelled scan yields no report,
and VIF 5/10 are reference lines rather than removal advice.

The dependency-free CI discovers this module but skips it when PyQGIS/GDAL are
unavailable. Run with QGIS' Python, e.g.
    QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m unittest tests.test_covariate_report_review -v
"""

from __future__ import annotations

import csv
import inspect
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
    from qgis.core import (
        QgsApplication,
        QgsFeature,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsRasterLayer,
        QgsVectorLayer,
    )

    from tools import covariate_report_dialog as covmod
    from tools.covariate_report_dialog import CovariateReportDialog

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc

XMIN, YMAX, PX, N = 200000.0, 500000.0, 10.0, 80  # 80 x 80 cells of 10 m, EPSG:5186


class _Bar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, title, text, *args, **kwargs):
        self.messages.append((title, text))


class _Iface:
    def __init__(self):
        self.bar = _Bar()

    def messageBar(self):
        return self.bar


def _truth(cols):
    """Pearson matrix and VIF_j = 1/(1-R_j^2) from OLS (with intercept) of x_j on the others."""
    m = np.column_stack(cols).astype(np.float64)
    corr = np.corrcoef(m, rowvar=False)
    n, k = m.shape
    vifs = []
    for i in range(k):
        y = m[:, i]
        x = np.column_stack([np.ones(n)] + [m[:, j] for j in range(k) if j != i])
        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
        r2 = 1.0 - np.sum((y - x @ beta) ** 2) / np.sum((y - y.mean()) ** 2)
        vifs.append(1.0 / (1.0 - r2))
    return corr, vifs


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL/NumPy unavailable: {QGIS_IMPORT_ERROR}")
class CovariateReportQgisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QgsApplication.instance() is None:
            prefix = os.environ.get("QGIS_PREFIX_PATH", "").strip()
            if prefix:
                QgsApplication.setPrefixPath(prefix, True)
            cls.app = QgsApplication([], True)
            cls.app.initQgis()
        else:
            cls.app = QgsApplication.instance()
        # No tearDownClass / exitQgis: one QgsApplication lives for the whole
        # test process (see tests/test_align_export_qgis.py).
        rng = np.random.default_rng(12345)
        cls.x1 = rng.normal(0.0, 1.0, (N, N))
        cls.x2 = 2.0 * cls.x1 + rng.normal(0.0, 1.0, (N, N))
        cls.x3 = rng.normal(5.0, 2.0, (N, N))

    def setUp(self):
        env = mock.patch.dict(os.environ, {"ARCHTOOLKIT_NO_DIALOG_MEMORY": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.tmp = tempfile.mkdtemp(prefix="archtoolkit_covariate_test_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(QgsProject.instance().removeAllMapLayers)
        QgsProject.instance().removeAllMapLayers()
        self.iface = _Iface()

    # ------------------------------------------------------------ helpers
    def _raster(self, name, arr, nodata=-9999.0):
        path = os.path.join(self.tmp, f"{name}.tif")
        ds = gdal.GetDriverByName("GTiff").Create(path, arr.shape[1], arr.shape[0], 1, gdal.GDT_Float32)
        ds.SetGeoTransform((XMIN, PX, 0.0, YMAX, 0.0, -PX))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(5186)
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(nodata)
        band.WriteArray(arr.astype(np.float32))
        band.FlushCache()
        ds = None
        layer = QgsRasterLayer(path, name, "gdal")
        self.assertTrue(layer.isValid(), path)
        QgsProject.instance().addMapLayer(layer)
        return layer

    def _stack(self):
        return [self._raster("x1", self.x1), self._raster("x2", self.x2), self._raster("x3", self.x3)]

    def _polygons(self, name, rings):
        layer = QgsVectorLayer("Polygon?crs=EPSG:5186", name, "memory")
        feats = []
        for ring in rings:
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in ring]]))
            feats.append(f)
        layer.dataProvider().addFeatures(feats)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        return layer

    def _run(self, target, aoi=None, selected_only=False):
        d = CovariateReportDialog(self.iface)
        self.addCleanup(d.deleteLater)
        d._check_all(True)
        d.spinSamples.setValue(target)
        d.cmbAoi.setLayer(aoi)
        d.chkAoiSelected.setChecked(selected_only)
        captured = {}

        def _capture(html, names, corr, vifs, n):
            captured.update(html=html, names=list(names), corr=corr, vifs=list(vifs), n=int(n))
        d._show_report = _capture
        d._on_run()
        return d, captured

    def _csv(self, dialog, captured):
        path = os.path.join(self.tmp, "report.csv")
        with mock.patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(path, "CSV (*.csv)")):
            dialog._save_csv(captured["names"], captured["corr"], captured["vifs"])
        with open(path, encoding="utf-8-sig") as f:
            return list(csv.reader(f))

    @staticmethod
    def _f32(a):
        return a.astype(np.float32).astype(np.float64).ravel()

    # ------------------------------------------------------------ tests
    def test_known_answer_corr_and_vif_exact(self):
        self._stack()
        _d, cap = self._run(N * N)  # the scan hits every cell centre once
        self.assertEqual(cap["n"], N * N)
        corr, vifs = _truth([self._f32(self.x1), self._f32(self.x2), self._f32(self.x3)])
        np.testing.assert_allclose(cap["corr"], corr, atol=1e-9)
        np.testing.assert_allclose(cap["vifs"], vifs, rtol=1e-9)
        self.assertGreater(cap["vifs"][0], 5.0)  # x2 = 2*x1 + noise: r ~ 0.9, VIF ~ 5.1
        self.assertLess(cap["vifs"][2], 1.01)

    def test_oversampling_is_capped_at_one_point_per_cell(self):
        self._stack()
        _d, census = self._run(N * N)
        d, cap = self._run(200000)
        self.assertEqual(cap["n"], N * N)
        np.testing.assert_allclose(cap["corr"], census["corr"], atol=1e-12)
        self.assertIn("요청 200,000점 &gt; 셀 6,400개, 전수 6,400점", cap["html"])
        rows = self._csv(d, cap)
        self.assertIn(["# 요청 200,000점 > 셀 6,400개, 전수 6,400점"], rows)

    def test_polygon_aoi_restricts_samples_to_polygon_not_bbox(self):
        self._stack()
        # A thin band along the diagonal: its bounding box is the whole raster,
        # the polygon itself about 2.5 % of it.
        ring = [(XMIN, YMAX - N * PX), (XMIN + N * PX, YMAX), (XMIN + N * PX, YMAX - 20.0),
                (XMIN + 20.0, YMAX - N * PX), (XMIN, YMAX - N * PX)]
        aoi = self._polygons("AOI_diag", [ring])
        geom = QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in ring]])
        inside = np.zeros((N, N), dtype=bool)
        for r in range(N):
            for c in range(N):
                inside[r, c] = geom.contains(QgsPointXY(XMIN + (c + 0.5) * PX, YMAX - (r + 0.5) * PX))
        d, cap = self._run(N * N, aoi=aoi)
        self.assertTrue(cap, self.iface.bar.messages)
        self.assertEqual(cap["n"], int(inside.sum()))
        self.assertLess(cap["n"], 0.04 * N * N)
        m = inside.ravel()
        corr, _vifs = _truth([self._f32(self.x1)[m], self._f32(self.x2)[m], self._f32(self.x3)[m]])
        np.testing.assert_allclose(cap["corr"], corr, atol=1e-9)
        self.assertIn("AOI: AOI_diag", cap["html"])
        self.assertIn("폴리곤 내부 표본", cap["html"])
        rows = self._csv(d, cap)
        self.assertTrue(any(r and r[0].startswith("# AOI: AOI_diag") for r in rows), rows[:8])
        self.assertTrue(any(r and r[0].startswith("# 범위: X ") for r in rows), rows[:8])

    def test_selected_only_aoi_uses_selected_polygon(self):
        self._stack()
        big = [(XMIN, YMAX - 800.0), (XMIN + 400.0, YMAX - 800.0), (XMIN + 400.0, YMAX - 400.0), (XMIN, YMAX - 400.0), (XMIN, YMAX - 800.0)]
        small = [(XMIN + 700.0, YMAX - 100.0), (XMIN + 800.0, YMAX - 100.0), (XMIN + 800.0, YMAX), (XMIN + 700.0, YMAX), (XMIN + 700.0, YMAX - 100.0)]
        aoi = self._polygons("AOI_two", [big, small])
        _d, both = self._run(N * N, aoi=aoi)
        self.assertEqual(both["n"], 40 * 40 + 10 * 10)  # union of both polygons, not their bbox (6400)
        ids = [f.id() for f in aoi.getFeatures()]
        aoi.selectByIds([ids[1]])
        _d, sel = self._run(N * N, aoi=aoi, selected_only=True)
        self.assertEqual(sel["n"], 10 * 10)
        self.assertIn("(선택 피처만)", sel["html"])

    def test_no_aoi_is_stated(self):
        self._stack()
        d, cap = self._run(N * N)
        self.assertIn("AOI 없음", cap["html"])
        self.assertIn(["# AOI 없음 — 공통 범위 전체"], self._csv(d, cap))

    def test_header_reports_valid_versus_scanned(self):
        x1 = self.x1.copy()
        x1[10:30, 10:50] = -9999.0  # 800 NoData cells
        self._raster("x1nd", x1)
        self._raster("x2", self.x2)
        _d, cap = self._run(N * N)
        self.assertEqual(cap["n"], N * N - 800)
        self.assertIn("격자 점 6,400점 중 모든 변수가 유효한 표본 5,600점", cap["html"])

    def test_cancel_yields_no_report(self):
        self._stack()
        calls = {"n": 0}

        def _cancel_after_first_row(_self):
            calls["n"] += 1
            return calls["n"] > 1
        with mock.patch.object(QtWidgets.QProgressDialog, "wasCanceled", _cancel_after_first_row):
            _d, cap = self._run(N * N)
        self.assertEqual(cap, {}, "a cancelled scan must not produce a report")
        self.assertTrue(any(title == "취소됨" for title, _text in self.iface.bar.messages), self.iface.bar.messages)
        # The patch is gone: a normal run works again.
        _d, cap = self._run(N * N)
        self.assertEqual(cap["n"], N * N)

    def test_thresholds_are_reference_lines_not_removal_advice(self):
        self.assertNotIn("제거 권장", inspect.getsource(covmod))
        names = ["a", "b", "c"]
        corr = np.array([[1.0, 0.95, 0.1], [0.95, 1.0, 0.1], [0.1, 0.1, 1.0]])
        html = CovariateReportDialog._build_report_html(None, names, corr, [12.0, 6.0, 1.0], 100)
        self.assertNotIn("제거 권장", html)
        self.assertIn("높음(≥10) — 참고선", html)
        self.assertIn("주의(≥5) — 참고선", html)
        self.assertIn("O'Brien 2007", html)
        for colour in ("#b2182b", "#ef8a62", "#1a9850"):
            self.assertIn(colour, html)

    def test_duplicate_names_get_suffix_and_long_names_are_not_cut_to_ten(self):
        self._raster("경사도_2024_v1_final_long", self.x1)
        self._raster("slope", self.x2)
        self._raster("slope", self.x3)
        d, cap = self._run(N * N)
        self.assertEqual(cap["names"], ["경사도_2024_v1_final_long", "slope", "slope (2)"])
        self.assertIn("title='경사도_2024_v1_final_long'", cap["html"])
        self.assertIn("<th align='left'>경사도_2024_v1_final_long</th>", cap["html"])
        rows = self._csv(d, cap)
        self.assertIn(["", "경사도_2024_v1_final_long", "slope", "slope (2)"], rows)
        self.assertIn(["variable", "vif"], rows)
        vif_names = [r[0] for r in rows[rows.index(["variable", "vif"]) + 1:][:3]]
        self.assertEqual(vif_names, ["경사도_2024_v1_final_long", "slope", "slope (2)"])

    def test_categorical_inputs_are_named_in_report_and_csv(self):
        geol = self._raster("geology_class", np.random.default_rng(7).integers(1, 6, (N, N)).astype(np.float64), nodata=0.0)
        geol.setCustomProperty("archtoolkit/tool_id", "geology")
        geol.setCustomProperty("archtoolkit/kind", "class")
        geol.setCustomProperty("archtoolkit/units", "class")
        self._raster("x1", self.x1)
        d, cap = self._run(N * N)  # '모두 선택' includes the class raster
        note = "범주형 래스터 포함, 클래스 코드로 계산됨: geology_class"
        self.assertIn(note, cap["html"])
        self.assertIn([f"# {note}"], self._csv(d, cap))

    def test_unique_names_helper(self):
        self.assertEqual(covmod._unique_names(["a", "b", "a", "a"]), ["a", "b", "a (2)", "a (3)"])


if __name__ == "__main__":
    unittest.main()
