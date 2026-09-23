"""QGIS integration tests for the terrain-profile and map-styling review fixes.

Like tests/test_align_export_qgis.py this module is discovered by the
dependency-free CI and skips (never fails) when PyQGIS/GDAL are unavailable.
Run it with QGIS' Python to exercise the real dialogs:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=/usr/share/qgis/python/plugins \
        python3 -m unittest tests.test_profile_styling_review2 -v

Terrain profile:
- the profile group is moved to the top, not deleted (its layer node survives);
- lines drawn after a canvas CRS change are stored in the library layer's CRS
  and reopen with the same samples;
- the chart draws the raw samples by default (a 2 m ditch stays 2 m), states
  the vertical exaggeration and the curve method, and its tick labels are dark;
- NoData gaps break the chart line and are excluded from ascent/slope;
- reopening a profile whose DEM is gone asks instead of silently sampling
  another DEM;
- the AOI inside-length is the exact geometric intersection;
- zooming keeps the distance under the cursor and never runs past the data;
- messages report N intervals = N+1 points.
Map styling:
- the grey DEM layer is stretched to the DEM min/max (no wrap at 256 m);
- road/river labels and building codes follow the NGII code tables;
- building polygons: polygons untouched (also in EPSG:4326), multipart lines
  closed part by part, label points skipped;
- the colour legend carries the class values;
- a CRS without authid survives into the aggregated layer.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("ARCHTOOLKIT_NO_DIALOG_MEMORY", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_REGRESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "regression")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
    import numpy as np
    from osgeo import gdal, osr
    from qgis.PyQt.QtCore import QEvent, QPoint, QPointF, Qt
    from qgis.PyQt.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
    from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox
    from qgis.core import (
        QgsApplication,
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsFeature,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsRasterLayer,
        QgsRectangle,
        QgsVectorLayer,
    )
    from qgis.gui import QgsMapCanvas

    from tools import terrain_profile_dialog as tpd
    from tools.map_styling_dialog import DEFAULT_CODE_CONFIG, MapStylingDialog
    from tools.utils import get_archtoolkit_layer_metadata
    from tools.terrain_profile_dialog import (
        PROFILE_GROUP_NAME,
        PROFILE_LAYER_NAME,
        PROFILE_SINGLE_SUBGROUP_NAME,
        ProfileChartWidget,
        TerrainProfileDialog,
    )

    if _REGRESSION_DIR not in sys.path:
        sys.path.insert(0, _REGRESSION_DIR)
    import qgis_env  # noqa: E402  (tests/regression/qgis_env.py: FakeIface)

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc


XMIN, YMAX = 200000.0, 500000.0


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class _QgisCase(unittest.TestCase):
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
        cls.canvas.resize(800, 600)
        cls.iface = qgis_env.FakeIface(cls.canvas)

    # No tearDownClass: a QgsApplication cannot be re-created in the same
    # process once exitQgis() has run (see tests/test_align_export_qgis.py).

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="archtoolkit_profile_styling_")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        self.addCleanup(self._clear_project)
        self._clear_project()
        self.iface._bar.messages.clear()
        self._set_canvas("EPSG:5186")

    @staticmethod
    def _clear_project():
        QgsProject.instance().removeAllMapLayers()
        QgsProject.instance().layerTreeRoot().removeAllChildren()

    def _set_canvas(self, authid):
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem(authid))

    def _dem(self, name, z, *, px=10.0, nodata=-9999.0):
        path = os.path.join(self.temp_dir, name)
        nrows, ncols = z.shape
        ds = gdal.GetDriverByName("GTiff").Create(path, ncols, nrows, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((XMIN, px, 0.0, YMAX, 0.0, -px))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(5186)
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(nodata)
        band.WriteArray(z.astype(np.float32))
        band.FlushCache()
        ds = None
        lyr = QgsRasterLayer(path, name, "gdal")
        self.assertTrue(lyr.isValid(), path)
        QgsProject.instance().addMapLayer(lyr)
        return lyr

    def _messages(self):
        return [" ".join(str(a) for a in args) for args, _kw in self.iface._bar.messages]

    def _mem(self, geom_type, crs, rows, name, field="Layer"):
        lyr = QgsVectorLayer(f"{geom_type}?field={field}:string", name, "memory")
        lyr.setCrs(crs)
        feats = []
        for code, wkt in rows:
            f = QgsFeature(lyr.fields())
            f.setGeometry(QgsGeometry.fromWkt(wkt))
            f.setAttributes([code])
            feats.append(f)
        lyr.dataProvider().addFeatures(feats)
        lyr.updateExtents()
        QgsProject.instance().addMapLayer(lyr)
        return lyr


class TerrainProfileReviewTests(_QgisCase):
    def _dialog(self):
        d = TerrainProfileDialog(self.iface)
        self.addCleanup(d.close)
        d.chkSingleLayers.setChecked(False)
        return d

    def _run(self, d, dem, p0, p1, n):
        d.cmbDemLayer.setLayer(dem)
        d.spinSamples.setValue(n)
        d.points = []
        d.add_point(QgsPointXY(*p0))
        d.add_point(QgsPointXY(*p1))
        return list(d.profile_data)

    def _ramp_dem(self, name="ramp.tif"):
        yy, xx = np.mgrid[0:60, 0:60].astype(np.float64)
        return self._dem(name, 100 + 0.5 * xx)

    def test_existing_profile_group_is_moved_not_deleted(self):
        root = QgsProject.instance().layerTreeRoot()
        grp = root.addGroup(PROFILE_GROUP_NAME)
        grp.addGroup(PROFILE_SINGLE_SUBGROUP_NAME)
        root.insertGroup(0, "someone else's group")
        dem = self._ramp_dem()
        d = self._dialog()
        self._run(d, dem, (200050.0, 499700.0), (200550.0, 499700.0), 50)
        lines = QgsProject.instance().mapLayersByName(PROFILE_LAYER_NAME)
        self.assertEqual(len(lines), 1)
        node = root.findLayer(lines[0].id())
        self.assertIsNotNone(node, "profile line layer lost its layer-tree node")
        self.assertEqual(node.parent().name(), PROFILE_GROUP_NAME)
        self.assertEqual(root.children()[0].name(), PROFILE_GROUP_NAME)
        self.assertIsNotNone(root.findGroup(PROFILE_GROUP_NAME).findGroup(PROFILE_SINGLE_SUBGROUP_NAME))

    def test_library_layer_survives_canvas_crs_change(self):
        dem = self._ramp_dem()
        d = self._dialog()
        # Endpoints off the 10 m cell edges, so a 1e-9 round trip through
        # EPSG:4326 cannot flip a sample into the neighbouring cell.
        p0, p1 = QgsPointXY(200053.0, 499703.0), QgsPointXY(200553.0, 499703.0)
        first = self._run(d, dem, (p0.x(), p0.y()), (p1.x(), p1.y()), 50)
        self._set_canvas("EPSG:4326")
        ct = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:5186"), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()
        )
        q0, q1 = ct.transform(p0), ct.transform(p1)
        second = self._run(d, dem, (q0.x(), q0.y()), (q1.x(), q1.y()), 50)
        self.assertEqual(len(second), 51)
        lyr = QgsProject.instance().mapLayersByName(PROFILE_LAYER_NAME)[0]
        self.assertEqual(lyr.crs().authid(), "EPSG:5186")
        f2 = [f for f in lyr.getFeatures() if f["no"] == 2][0]
        start = f2.geometry().asPolyline()[0]
        self.assertAlmostEqual(start.x(), 200053.0, places=2)
        self.assertAlmostEqual(start.y(), 499703.0, places=2)
        d.profile_data = []
        d._open_profile_from_feature(lyr, f2)
        self.assertEqual(len(d.profile_data), 51)
        for a, b in zip(first, d.profile_data):
            self.assertAlmostEqual(a["elevation"], b["elevation"], places=6)
            self.assertAlmostEqual(a["distance"], b["distance"], places=3)

    def _ditch_dialog(self):
        z = np.full((220, 220), 50.0)
        z[:, 100:102] = 48.0   # 10 m wide, 2 m deep ditch
        z[:, 150:152] = 52.0   # 10 m wide, 2 m high bank
        dem = self._dem("ditch.tif", z, px=5.0)
        d = self._dialog()
        self._run(d, dem, (200002.5, 499500.0), (201002.5, 499500.0), 200)   # 5 m spacing
        return d

    def test_chart_draws_raw_samples_and_states_vertical_exaggeration(self):
        d = self._ditch_dialog()
        curve = [p["elevation"] for p in d.chart.smooth_data]
        self.assertAlmostEqual(min(curve), 48.0, places=6)
        self.assertAlmostEqual(max(curve), 52.0, places=6)
        png = os.path.join(self.temp_dir, "ditch.png")
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(png, "PNG Files (*.png)")):
            d.export_image()
        # 1200x800 image: 1110 px over 1000 m horizontally, 730 px over the
        # padded 4.8 m elevation range vertically -> 137.0x.
        expected_ve = (730.0 / 4.8) / (1110.0 / 1000.0)
        self.assertAlmostEqual(d.chart.export_vertical_exaggeration, expected_ve, places=3)
        self.assertIn(f"수직 과장 {expected_ve:.1f}배", d.chart.export_annotation_lines)
        self.assertIn("곡선: 원시 샘플", d.chart.export_annotation_lines)
        img = QImage(png)
        dark = 0
        for x in range(0, 56):
            for y in range(25, 790):
                c = QColor(img.pixel(x, y))
                if max(c.red(), c.green(), c.blue()) < 150:
                    dark += 1
        self.assertGreater(dark, 50, "y-axis tick labels are not readable (no dark pixels)")
        # Opt-in smoothing is stated with its window.
        d.chkSmoothChart.setChecked(True)
        curve = [p["elevation"] for p in d.chart.smooth_data]
        self.assertAlmostEqual(min(curve), 50.0 - 4.0 / 7.0, places=6)
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(png, "PNG Files (*.png)")):
            d.export_image()
        self.assertIn("곡선: ±3점 이동평균 (약 30m 창)", d.chart.export_annotation_lines)
        self.assertIn("±3점 이동평균", d.lblStats.text())

    def test_nodata_gap_breaks_line_and_is_excluded_from_ascent(self):
        yy, xx = np.mgrid[0:60, 0:60].astype(np.float64)
        z = 100 + 0.5 * xx
        z[:, 20:25] = -9999.0
        dem = self._dem("gap.tif", z)
        d = self._dialog()
        data = self._run(d, dem, (199900.0, 499705.0), (200400.0, 499705.0), 50)
        self.assertEqual(len(data), 36)
        self.assertEqual(sum(1 for p in data if p.get("gap_before")), 1)
        runs = tpd._profile_runs(d.chart.smooth_data)
        self.assertEqual(len(runs), 2)
        csv_path = os.path.join(self.temp_dir, "gap.csv")
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(csv_path, "CSV Files (*.csv)")):
            d.export_csv()
        with open(csv_path, encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        summary = {r[0]: r[1] for r in rows if len(r) == 2}
        # 290 -> 350 m spans the NoData block: its 3 m jump is not "ascent".
        self.assertAlmostEqual(float(summary["total_ascent_m"]), 17.0, places=6)
        self.assertEqual(summary["nodata_gaps"], "1")
        self.assertAlmostEqual(float(summary["nodata_gap_length_m"]), 60.0, places=3)
        hdr = [i for i, r in enumerate(rows) if r and r[0] == "Distance(m)"][0]
        self.assertEqual(rows[hdr][-1], "GapBefore")
        gap_rows = [r for r in rows[hdr + 1:hdr + 1 + len(data)] if r[-1] == "1"]
        self.assertEqual(len(gap_rows), 1)
        self.assertEqual(gap_rows[0][2], "")   # no slope across the gap
        self.assertIn("누적상승: 17.0m", d.lblStats.text())

    def test_reopen_with_missing_dem_asks_instead_of_switching_silently(self):
        yy, xx = np.mgrid[0:60, 0:60].astype(np.float64)
        dem_a = self._dem("demA.tif", 100 + 0.5 * xx)
        dem_b = self._dem("demB.tif", 900 - 0.5 * xx)
        d = self._dialog()
        self._run(d, dem_a, (200050.0, 499700.0), (200550.0, 499700.0), 50)
        QgsProject.instance().removeMapLayer(dem_a.id())
        d.cmbDemLayer.setLayer(dem_b)
        lyr = QgsProject.instance().mapLayersByName(PROFILE_LAYER_NAME)[0]
        feat = next(lyr.getFeatures())
        d.profile_data = []
        self.iface._bar.messages.clear()
        with mock.patch.object(tpd.QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as q:
            d._open_profile_from_feature(lyr, feat)
        self.assertEqual(q.call_count, 1)
        self.assertEqual(d.profile_data, [], "sampled another DEM without asking")
        self.assertTrue(any("원래 DEM" in m for m in self._messages()))
        with mock.patch.object(tpd.QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            d._open_profile_from_feature(lyr, feat)
        self.assertEqual(len(d.profile_data), 51)
        self.assertGreater(min(p["elevation"] for p in d.profile_data), 800.0)

    def test_aoi_inside_length_is_exact_intersection(self):
        dem = self._ramp_dem()
        aoi = self._mem(
            "Polygon", QgsCoordinateReferenceSystem("EPSG:5186"),
            [("aoi", "POLYGON((200155 499600, 200245 499600, 200245 499800, 200155 499800, 200155 499600))")], "aoi",
        )
        d = self._dialog()
        d.cmbAoiLayer.setLayer(aoi)
        self._run(d, dem, (200050.0, 499700.0), (200550.0, 499700.0), 50)   # 10 m spacing
        self.assertAlmostEqual(d._last_aoi_inside_m, 90.0, places=4)
        self.assertEqual(len(d.chart.highlight_ranges), 1)
        a, b = d.chart.highlight_ranges[0]
        self.assertAlmostEqual(a, 105.0, places=4)
        self.assertAlmostEqual(b, 195.0, places=4)

    def test_sample_count_messages_report_points(self):
        dem = self._ramp_dem()
        d = self._dialog()
        self._run(d, dem, (200050.0, 499700.0), (200550.0, 499700.0), 50)
        msgs = self._messages()
        self.assertTrue(any("50개 구간(51개 지점)" in m for m in msgs), msgs)
        self.assertTrue(any("51/51개 지점" in m for m in msgs), msgs)


class ProfileChartZoomTests(_QgisCase):
    def _wheel(self, w, x, dy):
        w.wheelEvent(QWheelEvent(
            QPointF(x, 100), QPointF(x, 100), QPoint(0, 0), QPoint(0, dy),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
        ))

    def _drag(self, w, x0, x1):
        for t, x in ((QEvent.Type.MouseButtonPress, x0), (QEvent.Type.MouseMove, x1), (QEvent.Type.MouseButtonRelease, x1)):
            btns = Qt.MouseButton.NoButton if t == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
            ev = QMouseEvent(t, QPointF(x, 100), QPointF(x, 100), Qt.MouseButton.LeftButton, btns, Qt.KeyboardModifier.NoModifier)
            {QEvent.Type.MouseButtonPress: w.mousePressEvent,
             QEvent.Type.MouseMove: w.mouseMoveEvent,
             QEvent.Type.MouseButtonRelease: w.mouseReleaseEvent}[t](ev)

    def test_zoom_is_centred_on_cursor_and_clamped(self):
        w = ProfileChartWidget()
        w.resize(690, 300)   # plot area 600 px wide
        w.set_data([{"distance": float(i * 10), "elevation": 100.0 + i, "x": 0.0, "y": 0.0} for i in range(101)])
        self._wheel(w, 360, 120)   # cursor at the middle (500 m)
        visible = 1000.0 / w.zoom_level
        self.assertAlmostEqual(w.pan_offset + 0.5 * visible, 500.0, places=6)
        for _ in range(7):
            self._wheel(w, 360, 120)
        for _ in range(5):
            self._drag(w, 600, 60)
        self.assertAlmostEqual(w.pan_offset + 1000.0 / w.zoom_level, 1000.0, places=6)
        for _ in range(5):
            self._wheel(w, 660, -120)
            self.assertLessEqual(w.pan_offset + 1000.0 / w.zoom_level, 1000.0 + 1e-9)
            self.assertGreaterEqual(w.pan_offset, 0.0)


class MapStylingReviewTests(_QgisCase):
    def _dialog(self):
        d = MapStylingDialog(self.iface)
        self.addCleanup(d.close)
        return d

    def _select(self, d, layers):
        ids = {lyr.id() for lyr in layers}
        for i in range(d.lstLayers.count()):
            it = d.lstLayers.item(i)
            it.setCheckState(Qt.CheckState.Checked if it.data(Qt.ItemDataRole.UserRole) in ids else Qt.CheckState.Unchecked)

    def _styled(self, name):
        found = [lyr for lyr in QgsProject.instance().mapLayers().values() if lyr.name() == name]
        self.assertEqual(len(found), 1, name)
        return found[0]

    def _dem_styled(self, z):
        dem = self._dem("hills.tif", z)
        d = self._dialog()
        d.set_all_checks(False)
        d.chkDemStyling.setChecked(True)
        d.cmbDemLayer.setLayer(dem)
        d.apply_styling()
        return dem

    def test_grey_layer_is_stretched_to_dem_min_max(self):
        yy, xx = np.mgrid[0:60, 0:60].astype(np.float64)
        z = 150 + 3.0 * xx   # 150 - 327 m: crosses 256 m
        self._dem_styled(z)
        gray = self._styled("hills.tif_그레이")
        ce = gray.renderer().contrastEnhancement()
        self.assertIsNotNone(ce)
        self.assertAlmostEqual(ce.minimumValue(), 150.0, places=4)
        self.assertAlmostEqual(ce.maximumValue(), 327.0, places=4)
        blk = gray.renderer().block(1, QgsRectangle(XMIN, YMAX - 600, XMIN + 600, YMAX), 60, 60)
        levels = [QColor.fromRgba(blk.color(30, c)).red() for c in range(60)]
        self.assertEqual(levels, sorted(levels), "grey level must rise monotonically with elevation (no wrap)")
        params = (get_archtoolkit_layer_metadata(gray) or {}).get("params") or {}
        self.assertEqual(params.get("contrast"), "stretch_to_min_max")

    def test_colour_legend_carries_class_values(self):
        yy, xx = np.mgrid[0:60, 0:60].astype(np.float64)
        self._dem_styled(150 + 3.0 * xx)
        color = self._styled("hills.tif_고도색상")
        # The legend shows the colour-ramp item labels.
        labels = [it.label for it in color.renderer().shader().rasterShaderFunction().colorRampItemList()]
        self.assertEqual(labels, ["<= 150.0", "150.0 - 194.2", "194.2 - 238.5", "238.5 - 282.8", "282.8 - 327.0"])

    def test_ngii_code_labels_and_all_building_codes(self):
        roads = {r["code"]: r["label"] for r in DEFAULT_CODE_CONFIG["roads"]["rules"]}
        self.assertEqual(roads["A0023214"], "특별시도ㆍ광역시도")
        self.assertEqual(roads["A0023215"], "시도")
        self.assertEqual(roads["A0023216"], "군도")
        self.assertEqual(roads["A0023217"], "면리간도로")
        rivers = {r["code"]: r["label"] for r in DEFAULT_CODE_CONFIG["rivers"]["rules"]}
        self.assertEqual(rivers["E0022112"], "세류")
        self.assertEqual(rivers["E0022113"], "건천")
        self.assertEqual(rivers["E0022115"], "하천중심선")
        self.assertEqual(DEFAULT_CODE_CONFIG["buildings"]["codes"], [f"B00141{i}" for i in range(10, 20)])
        # The shipped JSON (what the dialog actually loads) says the same.
        with open(os.path.join(_ROOT, "tools", "map_styling_codes.json"), encoding="utf-8") as f:
            shipped = json.load(f)
        for key in ("roads", "rivers"):
            self.assertEqual(shipped[key]["rules"], DEFAULT_CODE_CONFIG[key]["rules"])
        self.assertEqual(shipped["buildings"]["codes"], DEFAULT_CODE_CONFIG["buildings"]["codes"])
        # A greenhouse (B0014117) is styled, not hidden with the source layer.
        src = self._mem(
            "LineString", QgsCoordinateReferenceSystem("EPSG:5186"),
            [("B0014117", "LINESTRING(200100 499500,200120 499500,200120 499520,200100 499520,200100 499500)"),
             ("A0023215", "LINESTRING(200100 499900, 200500 499900)"),
             ("F0017111", "LINESTRING(200100 499800, 200500 499800)")], "dxf",
        )
        d = self._dialog()
        self._select(d, [src])
        d.chkDemStyling.setChecked(False)
        d.apply_styling()
        bld = self._styled("Style: 건물")
        self.assertEqual([f["Layer"] for f in bld.getFeatures()], ["B0014117"])
        road = self._styled("Style: 도로")
        labels = {c.filterExpression(): c.label() for c in road.renderer().rootRule().children()}
        self.assertEqual(labels["\"Layer\" = 'A0023215'"], "시도")
        # The contour line is not styled: the hidden source still holds it, and the message says so.
        self.assertTrue(any("스타일 대상이 아닌 원본 피처 1개" in m for m in self._messages()), self._messages())

    def test_building_polygons_geographic_multipart_and_points(self):
        c5186 = QgsCoordinateReferenceSystem("EPSG:5186")
        c4326 = QgsCoordinateReferenceSystem("EPSG:4326")
        poly = QgsGeometry.fromWkt("POLYGON((200300 499500,200320 499500,200320 499520,200300 499520,200300 499500))")
        poly.transform(QgsCoordinateTransform(c5186, c4326, QgsProject.instance()))
        geo = self._mem("Polygon", c4326, [("B0014112", poly.asWkt(12))], "bld_4326")
        d = self._dialog()
        self._select(d, [geo])
        d.chkDemStyling.setChecked(False)
        d.apply_styling()
        out = next(self._styled("Style: 건물").getFeatures()).geometry()
        out.transform(QgsCoordinateTransform(c4326, c5186, QgsProject.instance()))
        self.assertAlmostEqual(out.area(), 400.0, delta=0.5)

        self._clear_project()
        multi = self._mem(
            "MultiLineString", c5186,
            [("B0014110", "MULTILINESTRING((200100 499500,200120 499500,200120 499520,200100 499520,200100 499500),"
                          "(200150 499500,200170 499500,200170 499520,200150 499520,200150 499500))")],
            "bld_multi",
        )
        pts = self._mem("Point", c5186, [("B0014110", "POINT(200110 499510)")], "bld_labels")
        d = self._dialog()
        self._select(d, [multi, pts])
        d.chkDemStyling.setChecked(False)
        d.apply_styling()
        feats = list(self._styled("Style: 건물").getFeatures())
        self.assertEqual(len(feats), 1, "the label point must not become a building")
        g = feats[0].geometry()
        self.assertTrue(g.isGeosValid())
        self.assertAlmostEqual(g.area(), 800.0, places=6)
        self.assertEqual(len(g.asMultiPolygon()), 2)
        self.assertTrue(any("점/주기 피처 1개" in m for m in self._messages()), self._messages())

    def test_custom_crs_without_authid_is_kept(self):
        custom = QgsCoordinateReferenceSystem.fromProj(
            # A user-defined TM (odd origin/false easting) that matches no EPSG code.
            "+proj=tmerc +lat_0=37.5 +lon_0=127.123 +k=0.9999 +x_0=123456 +y_0=654321 "
            "+ellps=bessel +towgs84=-115.8,474.99,674.11,1.16,-2.31,-1.63,6.43 +units=m +no_defs"
        )
        self.assertTrue(custom.isValid())
        self.assertEqual(custom.authid(), "")
        src = self._mem("LineString", custom, [("A0023211", "LINESTRING(200100 499900, 200500 499900)")], "bessel_dxf")
        d = self._dialog()
        self._select(d, [src])
        d.chkDemStyling.setChecked(False)
        d.apply_styling()
        road = self._styled("Style: 도로")
        self.assertTrue(road.crs().isValid())
        self.assertEqual(road.crs(), custom)


if __name__ == "__main__":
    unittest.main()
