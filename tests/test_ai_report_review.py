"""Known-answer and regression tests for the AI 조사요약 (AOI report) tool.

A synthetic project with hand-computable answers (AOI 300 x 300 m in
EPSG:5186, radius 500 m) pins the statistics the local path reports: AOI and
buffer area, point counts and distances, clipped line length and polygon area,
raster NoData handling, reference-site relations. It also covers the review
fixes: stale context cache, NULL site names, "inside" vs "touching" wording,
compass tally over every classified site, explicit layer picks, invalid
geometries, categorical rasters and the AOI + buffer scope label.

The regular dependency-free CI discovers this module and skips the QGIS tests;
run it with QGIS' Python (see DEVELOPMENT.md). The Gemini request test replaces
QgsNetworkAccessManager with an in-process fake, so nothing leaves the machine.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
    import numpy as np
    from osgeo import gdal, osr
    import qgis.core as qgis_core
    from qgis.PyQt.QtCore import QByteArray, QObject, QSettings, QTimer, pyqtSignal
    from qgis.PyQt.QtNetwork import QNetworkReply
    from qgis.core import (
        NULL,
        QgsApplication,
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsFeature,
        QgsField,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsProviderRegistry,
        QgsRasterLayer,
        QgsRectangle,
        QgsVectorLayer,
    )

    from tools.qtcompat import FT_DOUBLE, FT_STRING
    from tools import ai_aoi_summary, ai_gemini, ai_local_summarizer
    from tools.ai_report_dialog import AiAoiReportDialog

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc


# AOI square and radius shared by every test.
AX0, AY0, AX1, AY1 = 200150.0, 499550.0, 200450.0, 499850.0
CX, CY = 200300.0, 499700.0
RADIUS = 500.0
# QgsGeometry.buffer(r, 24): 24 segments per quarter -> an inscribed 96-gon.
BUFFER_AREA = 90000.0 + 4 * 300.0 * RADIUS + 0.5 * 96 * RADIUS * RADIUS * math.sin(2 * math.pi / 96)
# 10 m raster grid covering the buffer; the buffer bbox is exactly 130 x 130 cells.
GRID_GT = (199000.0, 10.0, 0.0, 501000.0, 0.0, -10.0)
GRID_N = 260

# (x, y), name, value, site_type. The first seven lie inside the buffer.
POINTS = [
    ((200300.0, 499700.0), "c0", 10.0, "A"),       # AOI centroid
    ((200200.0, 499600.0), None, 20.0, "B"),       # inside AOI, NULL name, SW
    ((200440.0, 499840.0), "c2", None, "A"),       # inside AOI, NULL value, NE
    ((200300.0, 499950.0), "n100", 40.0, "C"),     # 100 m north of the AOI
    ((200700.0, 499700.0), "e250", 50.0, None),    # 250 m east
    ((199750.0, 499700.0), "w400", 60.0, "A"),     # 400 m west
    ((200300.0, 499051.0), "s499", 70.0, "B"),     # 499 m south
    ((200300.0, 499049.0), "s501", 80.0, "C"),     # 501 m south: outside
    ((201450.0, 499700.0), "e1000", 90.0, "A"),    # outside
    ((200850.0, 500250.0), "ne566", 100.0, "B"),   # 565.7 m from the corner: outside
]


def _sq(x0, y0, x1, y1):
    ring = [QgsPointXY(x0, y0), QgsPointXY(x1, y0), QgsPointXY(x1, y1), QgsPointXY(x0, y1), QgsPointXY(x0, y0)]
    return QgsGeometry.fromPolygonXY([ring])


def _line(x0, y0, x1, y1):
    return QgsGeometry.fromPolylineXY([QgsPointXY(x0, y0), QgsPointXY(x1, y1)])


def _pt(x, y):
    return QgsGeometry.fromPointXY(QgsPointXY(x, y))


def _mem_layer(kind, name, crs, fields, rows, *, add=True):
    lyr = QgsVectorLayer(f"{kind}?crs={crs}", name, "memory")
    pr = lyr.dataProvider()
    pr.addAttributes([QgsField(n, t) for n, t in fields])
    lyr.updateFields()
    feats = []
    for geom, attrs in rows:
        f = QgsFeature(lyr.fields())
        f.setGeometry(geom)
        f.setAttributes([NULL if a is None else a for a in attrs])
        feats.append(f)
    pr.addFeatures(feats)
    lyr.updateExtents()
    if add:
        QgsProject.instance().addMapLayer(lyr)
    return lyr


def _points_layer(name="Pts"):
    rows = [(_pt(*xy), [nm, v, t]) for xy, nm, v, t in POINTS]
    return _mem_layer("Point", name, "EPSG:5186", [("name", FT_STRING), ("value", FT_DOUBLE), ("site_type", FT_STRING)], rows)


def _aoi_layer():
    return _mem_layer("Polygon", "AOI", "EPSG:5186", [("name", FT_STRING)], [(_sq(AX0, AY0, AX1, AY1), ["aoi"])])


def _write_tif(path, arr, *, nodata=None, gt=GRID_GT, epsg=5186):
    ds = gdal.GetDriverByName("GTiff").Create(path, arr.shape[1], arr.shape[0], 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(nodata)
    band.WriteArray(arr)
    band.FlushCache()
    ds = None
    return path


def _add_raster(path, name, meta=None):
    lyr = QgsRasterLayer(path, name, "gdal")
    if meta:
        for k, v in meta.items():
            lyr.setCustomProperty(f"archtoolkit/{k}", v)
    QgsProject.instance().addMapLayer(lyr)
    return lyr


def _buffer_geom():
    return _sq(AX0, AY0, AX1, AY1).buffer(RADIUS, 24)


def _touched_cells(classify=None):
    """Independent ALL_TOUCHED count: every 10 m cell of the buffer bbox that
    intersects the buffer. With `classify(col, row)` returns {class: count}."""
    buf = _buffer_geom()
    out = {}
    total = 0
    for i in range(130):
        for j in range(130):
            x0 = 199650.0 + i * 10.0
            y0 = 499050.0 + j * 10.0
            if not QgsGeometry.fromRect(QgsRectangle(x0, y0, x0 + 10.0, y0 + 10.0)).intersects(buf):
                continue
            total += 1
            if classify is not None:
                col = int(round((x0 - GRID_GT[0]) / 10.0))
                row = int(round((GRID_GT[3] - (y0 + 10.0)) / 10.0))
                k = classify(col, row)
                out[k] = out.get(k, 0) + 1
    return out if classify is not None else total


def _build(**kw):
    args = dict(
        aoi_layer=kw.pop("aoi"),
        selected_only=False,
        radius_m=RADIUS,
        only_archtoolkit_layers=False,
    )
    args.update(kw)
    ctx, err = ai_aoi_summary.build_aoi_context(**args)
    if err:
        raise AssertionError(err)
    return ctx


def _by_name(ctx):
    return {lyr["name"]: lyr for lyr in ctx["layers"]}


class AiReportSourceSpellingTests(unittest.TestCase):
    """QGIS-free: the network enums must be written in the PyQt6-safe form."""

    def test_gemini_uses_scoped_network_enums(self):
        with open(os.path.join(ROOT, "tools", "ai_gemini.py"), encoding="utf-8") as f:
            src = f.read()
        code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
        self.assertIn("QNetworkRequest.KnownHeaders.ContentTypeHeader", code)
        self.assertIsNone(re.search(r"QNetworkRequest\.ContentTypeHeader", code))
        # PyQt6's NetworkError is a plain Enum: every member is truthy.
        self.assertIsNone(re.search(r"if\s+reply\.error\(\)\s*:", code))
        self.assertIn("reply.error() != QNetworkReply.NetworkError.NoError", code)


class _QgisTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("ARCHTOOLKIT_NO_DIALOG_MEMORY", "1")
        cls._owns_app = QgsApplication.instance() is None
        if cls._owns_app:
            prefix = os.environ.get("QGIS_PREFIX_PATH", "").strip()
            if prefix:
                QgsApplication.setPrefixPath(prefix, True)
            cls.app = QgsApplication([], True)
            cls.app.initQgis()
        else:
            cls.app = QgsApplication.instance()
        providers = set(QgsProviderRegistry.instance().providerList())
        if not {"gdal", "memory"} <= providers:
            raise unittest.SkipTest(f"QGIS providers unavailable: {sorted(providers)}")

    # No tearDownClass: a QgsApplication cannot be re-created in the same
    # process once exitQgis() has run (see test_align_export_qgis).

    def setUp(self):
        QgsProject.instance().removeAllMapLayers()
        self.tmp = tempfile.mkdtemp(prefix="archtoolkit_ai_report_test_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(QgsProject.instance().removeAllMapLayers)

    def _path(self, name):
        return os.path.join(self.tmp, name)


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class AiReportKnownAnswerTests(_QgisTestBase):

    def test_aoi_and_buffer_area(self):
        ctx = _build(aoi=_aoi_layer())
        self.assertAlmostEqual(ctx["aoi"]["area_m2"], 90000.0, places=3)
        self.assertAlmostEqual(ctx["buffer_area_m2"], BUFFER_AREA, delta=0.01)
        self.assertEqual(ctx["stats_scope"], "aoi_plus_radius_buffer")

    def test_points_counts_distances_and_null_numeric(self):
        aoi = _aoi_layer()
        _points_layer()
        st = _by_name(_build(aoi=aoi))["Pts"]["stats"]
        self.assertEqual(st["features"], 7)
        cd = [math.hypot(xy[0] - CX, xy[1] - CY) for xy, *_ in POINTS[:7]]
        d = st["dist_to_aoi_centroid_m"]
        self.assertEqual(d["n"], 7)
        self.assertAlmostEqual(d["min"], min(cd), places=6)
        self.assertAlmostEqual(d["max"], max(cd), places=6)
        self.assertAlmostEqual(d["mean"], sum(cd) / 7.0, places=6)
        vals = [v for _, _, v, _ in POINTS[:7] if v is not None]
        num = st["numeric_fields"]["value"]
        self.assertEqual(num["n"], len(vals))  # NULL is not a zero
        self.assertAlmostEqual(num["mean"], sum(vals) / len(vals), places=9)
        self.assertEqual(st["top_field"], "site_type")
        self.assertEqual({d["value"]: d["count"] for d in st["top_values"]}, {"A": 3, "B": 2, "C": 1, "(null)": 1})

    def test_lines_and_polygons_are_clipped_to_the_buffer(self):
        aoi = _aoi_layer()
        _mem_layer("LineString", "Roads", "EPSG:5186", [("name", FT_STRING)], [
            (_line(198300, 499700, 202300, 499700), ["h"]),
            (_line(200300, 497700, 200300, 501700), ["v"]),
            (_line(198000, 510000, 202000, 510000), ["far"]),
        ])
        _mem_layer("Polygon", "Parcels", "EPSG:5186", [("name", FT_STRING)], [
            (_sq(200400, 499800, 200600, 500000), ["whole"]),   # 40,000 inside
            (_sq(200850, 499600, 201050, 499800), ["half"]),    # 20,000 inside
            (_sq(205000, 505000, 205200, 505200), ["far"]),
        ])
        tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:5186"), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())

        def geo(g):
            g2 = QgsGeometry(g)
            g2.transform(tr)
            return g2
        _mem_layer("Polygon", "Parcels4326", "EPSG:4326", [("name", FT_STRING)], [
            (geo(_sq(200400, 499800, 200600, 500000)), ["whole"]),
            (geo(_sq(200850, 499600, 201050, 499800)), ["half"]),
        ])
        _mem_layer("LineString", "Roads4326", "EPSG:4326", [("name", FT_STRING)], [(geo(_line(198300, 499700, 202300, 499700)), ["h"])])
        L = _by_name(_build(aoi=aoi))
        self.assertEqual(L["Roads"]["stats"]["features"], 2)
        self.assertAlmostEqual(L["Roads"]["stats"]["total_length_m"], 2600.0, places=3)
        self.assertEqual(L["Parcels"]["stats"]["features"], 2)
        self.assertAlmostEqual(L["Parcels"]["stats"]["total_area_m2"], 60000.0, places=2)
        # Geographic layers are measured in metres (ellipsoid), not degrees.
        self.assertAlmostEqual(L["Parcels4326"]["stats"]["total_area_m2"], 60000.0, delta=5.0)
        self.assertAlmostEqual(L["Roads4326"]["stats"]["total_length_m"], 1300.0, delta=0.1)

    def test_raster_statistics_exclude_nodata_and_use_the_buffer(self):
        aoi = _aoi_layer()
        const = np.full((GRID_N, GRID_N), 7.0, np.float32)
        const[120:140, 120:140] = -9999.0          # 400 NoData cells inside the AOI
        _add_raster(_write_tif(self._path("const.tif"), const, nodata=-9999.0), "Const")
        mask = np.zeros((GRID_N, GRID_N), np.float32)
        mask[115:145, 115:145] = 10.0              # exactly the AOI: 900 cells
        _add_raster(_write_tif(self._path("mask.tif"), mask), "Mask")
        L = _by_name(_build(aoi=aoi))
        touched = _touched_cells()
        st = L["Const"]["stats"]
        self.assertEqual(st["count"], touched - 400)
        self.assertEqual((st["min"], st["mean"], st["max"]), (7.0, 7.0, 7.0))
        ms = L["Mask"]["stats"]
        self.assertEqual(ms["count"], touched)
        self.assertAlmostEqual(ms["mean"], 9000.0 / touched, places=5)
        self.assertAlmostEqual(ms["high_value_pct"], 900.0 / touched * 100.0, places=6)

    def test_reference_site_relations_and_distances(self):
        aoi = _aoi_layer()
        pts = _points_layer()
        ref = _build(aoi=aoi, reference_layer=pts, reference_name_field="name")["reference_sites"]
        self.assertEqual(ref["classified_count"], 7)
        self.assertEqual(ref["counts"]["inside_aoi"], 3)
        self.assertEqual(ref["counts"]["inside_buffer_only"], 4)
        items = {it["name"]: it for it in ref["items"]}
        self.assertEqual(sorted(round(it["distance_to_aoi_m"], 6) for it in ref["items"]), [0, 0, 0, 100, 250, 400, 499])
        self.assertAlmostEqual(items["w400"]["distance_to_aoi_centroid_m"], 550.0, places=6)
        self.assertEqual([items[n]["compass_from_aoi"] for n in ("n100", "e250", "w400", "s499")], ["북", "동", "서", "남"])

    def test_null_site_name_falls_back_to_fid(self):
        aoi = _aoi_layer()
        pts = _points_layer()
        ctx = _build(aoi=aoi, reference_layer=pts, reference_name_field="name")
        names = [it["name"] for it in ctx["reference_sites"]["items"]]
        self.assertNotIn("NULL", names)
        fid = [f.id() for f in pts.getFeatures() if f.geometry().asPoint() == QgsPointXY(200200.0, 499600.0)][0]
        self.assertIn(f"FID {fid}", names)
        self.assertNotIn("`NULL`", ai_local_summarizer.generate_report(ctx))

    def test_nearest_interior_site_is_described_as_inside(self):
        aoi = _aoi_layer()
        pts = _points_layer()
        ctx = _build(aoi=aoi, reference_layer=pts, reference_name_field="name")
        nearest = [ln for ln in ai_local_summarizer._narrative_lines(ctx) if "가장 가까운 유적" in ln][0]
        self.assertIn("AOI 내부", nearest)
        self.assertNotIn("접함", nearest)
        # A site outside the AOI keeps its boundary distance.
        only_n = _mem_layer("Point", "OnlyN", "EPSG:5186", [("name", FT_STRING)], [(_pt(200300, 499950), ["n100"])])
        ctx2 = _build(aoi=aoi, reference_layer=only_n, reference_name_field="name")
        nearest2 = [ln for ln in ai_local_summarizer._narrative_lines(ctx2) if "가장 가까운 유적" in ln][0]
        self.assertIn("AOI 경계에서 약 100 m 거리", nearest2)

    def test_direction_tally_covers_every_classified_site(self):
        aoi = _aoi_layer()
        pts = _points_layer()
        # Display cap 3: the three AOI sites fill the item list.
        ctx = _build(aoi=aoi, reference_layer=pts, reference_name_field="name", reference_max_features=3)
        ref = ctx["reference_sites"]
        self.assertEqual(len(ref["items"]), 3)
        self.assertEqual(ref["direction_counts"]["buffer"], {"북": 1, "동": 1, "서": 1, "남": 1})
        self.assertEqual(ref["direction_counts"]["aoi"], {"남서": 1, "북동": 1})
        lines = ai_local_summarizer._narrative_lines(ctx)
        ring = [ln for ln in lines if ln.startswith("AOI 밖 반경(버퍼) 내 유적은")]
        self.assertEqual(len(ring), 1)
        self.assertNotIn("남서", ring[0])  # AOI sites are not the ring distribution
        self.assertTrue(any(ln.startswith("AOI 내부/중첩 유적은") for ln in lines))

    def test_invalid_polygon_is_repaired_before_measuring(self):
        aoi = _aoi_layer()
        bow = QgsGeometry.fromPolygonXY([[QgsPointXY(200000, 499400), QgsPointXY(200100, 499500), QgsPointXY(200100, 499400),
                                          QgsPointXY(200000, 499500), QgsPointXY(200000, 499400)]])
        self.assertFalse(bow.isGeosValid())
        _mem_layer("Polygon", "Bow", "EPSG:5186", [("name", FT_STRING)], [(bow, ["bow"]), (_sq(200500, 499500, 200600, 499600), ["sq"])])
        st = _by_name(_build(aoi=aoi))["Bow"]["stats"]
        self.assertEqual(st["features"], 2)
        # makeValid() -> two 2,500 m2 triangles, plus the 10,000 m2 square.
        self.assertAlmostEqual(st["total_area_m2"], 15000.0, places=3)
        self.assertEqual(st["invalid_geometries"], 0)
        self.assertEqual(st.get("repaired_geometries"), 1)

    def test_unrepairable_geometry_is_counted_not_hidden(self):
        aoi = _aoi_layer()
        bow = QgsGeometry.fromPolygonXY([[QgsPointXY(200000, 499400), QgsPointXY(200100, 499500), QgsPointXY(200100, 499400),
                                          QgsPointXY(200000, 499500), QgsPointXY(200000, 499400)]])
        _mem_layer("Polygon", "Bow", "EPSG:5186", [("name", FT_STRING)], [(bow, ["bow"]), (_sq(200500, 499500, 200600, 499600), ["sq"])])
        real = ai_aoi_summary._repaired_geometry

        def never_repairs(g):
            return (g, True) if not g.isGeosValid() else real(g)
        with mock.patch.object(ai_aoi_summary, "_repaired_geometry", never_repairs):
            ctx = _build(aoi=aoi)
        st = _by_name(ctx)["Bow"]["stats"]
        self.assertEqual(st["features"], 2)
        self.assertEqual(st["invalid_geometries"], 1)
        self.assertAlmostEqual(st["total_area_m2"], 10000.0, places=3)
        self.assertIn("지오메트리 오류 1개", ai_local_summarizer.generate_report(ctx))
        layers_csv, numeric_csv = self._path("l.csv"), self._path("n.csv")
        self.assertIsNone(ai_aoi_summary.export_aoi_context_csv(ctx, layers_csv_path=layers_csv, numeric_fields_csv_path=numeric_csv))
        with open(layers_csv, encoding="utf-8") as f:
            row = [r for r in csv.DictReader(f) if r["layer_name"] == "Bow"][0]
        self.assertEqual(row["invalid_geometries"], "1")

    def test_categorical_raster_gets_a_class_histogram(self):
        aoi = _aoi_layer()
        arr = np.zeros((GRID_N, GRID_N), np.float32)
        arr[:, :130] = 1
        arr[:, 130:] = 3
        arr[100:160, :] = 2
        _add_raster(_write_tif(self._path("cls.tif"), arr), "Classes", {"tool_id": "test_tool", "kind": "class", "units": "class"})
        _add_raster(_write_tif(self._path("cont.tif"), arr), "Continuous")  # same cells, no metadata

        def klass(col, row):
            return 2 if 100 <= row < 160 else (1 if col < 130 else 3)
        expected = _touched_cells(klass)
        ctx = _build(aoi=aoi)
        L = _by_name(ctx)
        st = L["Classes"]["stats"]
        self.assertTrue(st["categorical"])
        for k in ("min", "mean", "max"):
            self.assertNotIn(k, st)
        self.assertEqual(st["class_count"], 3)
        self.assertEqual({d["value"]: d["count"] for d in st["classes"]}, expected)
        self.assertEqual(st["count"], sum(expected.values()))
        self.assertIn("mean", L["Continuous"]["stats"])  # no metadata: unchanged
        report = ai_local_summarizer.generate_report(ctx)
        section = report.split("### - Classes", 1)[1].split("###", 1)[0]
        self.assertIn("범주형 래스터: 클래스 3개", section)
        self.assertNotIn("min/mean/max:", section)
        layers_csv, numeric_csv = self._path("l.csv"), self._path("n.csv")
        self.assertIsNone(ai_aoi_summary.export_aoi_context_csv(ctx, layers_csv_path=layers_csv, numeric_fields_csv_path=numeric_csv))
        with open(layers_csv, encoding="utf-8") as f:
            row = [r for r in csv.DictReader(f) if r["layer_name"] == "Classes"][0]
        self.assertEqual((row["raster_categorical"], row["raster_class_count"], row["raster_mean"]), ("True", "3", ""))

    def test_explicit_layer_picks_win_and_skips_are_named(self):
        aoi = _aoi_layer()
        pts = _points_layer()
        style = _mem_layer("Point", "Style: 도면", "EPSG:5186", [("name", FT_STRING)], [(_pt(200300, 499700), ["s"])])
        far = _mem_layer("Point", "FarPts", "EPSG:5186", [("name", FT_STRING)], [(_pt(250000, 550000), ["f"])])
        ctx = _build(aoi=aoi, only_archtoolkit_layers=True, exclude_styling_layers=True, layer_ids=[pts.id(), style.id(), far.id()])
        self.assertEqual(sorted(_by_name(ctx)), ["Pts", "Style: 도면"])
        self.assertEqual(ctx["skipped_selected_layers"], [{"id": far.id(), "name": "FarPts", "reason": "out_of_range"}])
        report = ai_local_summarizer.generate_report(ctx)
        self.assertIn("선택 레이어 중 범위 밖이라 제외: FarPts", report)
        self.assertIn("선택 레이어 요약", report)
        self.assertNotIn("프로젝트 전체 요약", report)
        # Auto scope still honours the exclusions.
        ctx_auto = _build(aoi=aoi, exclude_styling_layers=True)
        self.assertNotIn("Style: 도면", _by_name(ctx_auto))

    def test_buffer_scope_is_labelled_in_report_and_csv(self):
        aoi = _aoi_layer()
        _points_layer()
        ctx = _build(aoi=aoi)
        report = ai_local_summarizer.generate_report(ctx)
        self.assertIn("AOI 폴리곤이 아니라 AOI + 반경 500 m 버퍼 범위 기준", report)
        self.assertIn("## 2) 레이어/분석 요약 (AOI + 반경 버퍼 기준)", report)
        layers_csv, numeric_csv = self._path("l.csv"), self._path("n.csv")
        self.assertIsNone(ai_aoi_summary.export_aoi_context_csv(ctx, layers_csv_path=layers_csv, numeric_fields_csv_path=numeric_csv))
        for path in (layers_csv, numeric_csv):
            with open(path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertTrue(rows, path)
            self.assertEqual({(r["stats_scope"], r["buffer_radius_m"]) for r in rows}, {("aoi_plus_radius_buffer", "500.0")})


class _FakeIface:
    class _Bar:
        def __init__(self):
            self.messages = []

        def pushMessage(self, title, text, level=0, duration=0):
            self.messages.append((title, text))

    def __init__(self):
        self._bar = self._Bar()

    def messageBar(self):
        return self._bar

    def mapCanvas(self):
        return None


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class AiReportDialogTests(_QgisTestBase):
    """Context cache invalidation, prompt wording and the (faked) Gemini call."""

    _GROUP = "ArchToolkit/ai"

    def setUp(self):
        # The dialog persists its options under ArchToolkit/ai; keep the user's
        # values and start from auto scope / local provider (a saved
        # "layers" scope would open the modal layer picker). Registered before
        # the base cleanups so it runs LAST: removing the layers makes the
        # still-open dialog's reference combo write its options again.
        s = QSettings()
        s.beginGroup(self._GROUP)
        saved = {k: s.value(k) for k in s.allKeys()}
        s.endGroup()
        self.addCleanup(self._restore_settings, saved)
        super().setUp()
        s.setValue(f"{self._GROUP}/report/layer_scope", "auto")
        s.setValue(f"{self._GROUP}/report/provider", "local")
        s.setValue(f"{self._GROUP}/report/reference_enabled", "0")
        self.aoi = _aoi_layer()
        self.pts = _points_layer()
        self.dlg = AiAoiReportDialog(_FakeIface())
        self.addCleanup(self.dlg.done, 0)
        self.dlg.cmbAoi.setLayer(self.aoi)
        self.dlg.spinRadius.setValue(RADIUS)
        self.dlg.chkOnlyArchToolkit.setChecked(False)

    def _restore_settings(self, saved):
        s = QSettings()
        s.remove(self._GROUP)
        for k, v in saved.items():
            s.setValue(f"{self._GROUP}/{k}", v)
        s.sync()

    def _ctx(self):
        ctx, err = self.dlg._get_or_build_ctx(prompt_select_layers=False)
        self.assertIsNone(err)
        return ctx

    def _pts_features(self, ctx):
        return _by_name(ctx)["Pts"]["stats"]["features"]

    def test_cache_is_reused_when_nothing_changed(self):
        first = self._ctx()
        self.assertIs(self._ctx(), first)
        self.dlg.chkForceRecompute.setChecked(True)
        self.assertIsNot(self._ctx(), first)

    def test_cache_invalidated_when_feature_count_changes(self):
        self.assertEqual(self._pts_features(self._ctx()), 7)
        # Provider-level add: no edit session, no commit signal - only the
        # per-layer feature count in the signature can notice it.
        f = QgsFeature(self.pts.fields())
        f.setGeometry(_pt(200310, 499710))
        f.setAttributes(["new", 5.0, "A"])
        self.pts.dataProvider().addFeatures([f])
        self.assertEqual(self._pts_features(self._ctx()), 8)

    def test_cache_invalidated_by_committed_attribute_edit(self):
        ctx = self._ctx()
        mean_before = _by_name(ctx)["Pts"]["stats"]["numeric_fields"]["value"]["mean"]
        fid = [f.id() for f in self.pts.getFeatures() if f["name"] == "c0"][0]
        self.pts.startEditing()
        self.pts.changeAttributeValue(fid, self.pts.fields().indexFromName("value"), 610.0)
        self.assertTrue(self.pts.commitChanges())
        self.assertIsNone(self.dlg._last_ctx)  # afterCommitChanges dropped it
        mean_after = _by_name(self._ctx())["Pts"]["stats"]["numeric_fields"]["value"]["mean"]
        self.assertAlmostEqual(mean_after - mean_before, 600.0 / 6.0, places=9)

    def test_cache_invalidated_when_layer_added_and_signals_released_on_close(self):
        self._ctx()
        _mem_layer("Point", "Later", "EPSG:5186", [("name", FT_STRING)], [(_pt(200300, 499700), ["x"])])
        self.assertIsNone(self.dlg._last_ctx)
        self.assertIn("Later", _by_name(self._ctx()))
        self.dlg.done(0)
        self.assertFalse(self.dlg._project_signals_connected)
        self.assertEqual(self.dlg._watched_layers, {})

    def test_prompt_states_buffer_scope_and_categorical_caveat(self):
        arr = np.ones((GRID_N, GRID_N), np.float32)
        arr[:, 130:] = 2
        _add_raster(_write_tif(self._path("cls.tif"), arr), "Litho", {"tool_id": "geology", "kind": "lithology", "units": "class"})
        prompt = self.dlg._build_prompt(self._ctx())
        self.assertIn("AOI 폴리곤이 아니라 AOI + 반경 500.0 m 버퍼", prompt)
        self.assertIn("범주형(클래스 코드)", prompt)
        self.assertIn("Litho(클래스 2개)", prompt)

    def test_gemini_request_and_reply_status_with_fake_network(self):
        calls = []

        class FakeReply(QObject):
            finished = pyqtSignal()

            def __init__(self, body, err):
                super().__init__()
                self._body, self._err = body, err
                QTimer.singleShot(0, self.finished.emit)

            def error(self):
                return self._err

            def errorString(self):
                return "fake error"

            def readAll(self):
                return QByteArray(self._body)

            def abort(self):
                return None

        script = []

        class FakeNam:
            @classmethod
            def instance(cls):
                return cls()

            def post(self, req, data):
                calls.append((req.url().toString(), bytes(req.rawHeader(b"x-goog-api-key")), json.loads(bytes(data).decode("utf-8"))))
                return FakeReply(*script.pop(0))

        ok_body = json.dumps({"candidates": [{"content": {"parts": [{"text": "보고서"}]}, "finishReason": "STOP"}]}).encode()
        with mock.patch.object(qgis_core, "QgsNetworkAccessManager", FakeNam):
            script.append((ok_body, QNetworkReply.NetworkError.NoError))
            text, err = ai_gemini.generate_text(api_key="FAKE", model="gemini-2.5-flash", prompt="p")
            self.assertEqual((text, err), ("보고서", None))
            script.append((b'{"error":{"code":404}}', QNetworkReply.NetworkError.ContentNotFoundError))
            text, err = ai_gemini.generate_text(api_key="FAKE", model="gemini-2.5-flash", prompt="p")
            self.assertIsNone(text)
            self.assertIn("fake error", err)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("FAKE", calls[0][0])  # key travels in the header only
        self.assertEqual(calls[0][1], b"FAKE")


if __name__ == "__main__":
    unittest.main()
