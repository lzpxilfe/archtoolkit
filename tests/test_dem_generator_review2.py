"""Correctness pins for DEM 생성 (tools/dem_generator_dialog.py), review round 2.

Each test reproduces a wrong output, a crash or a missing refusal found in
review:
- a contour (line) layer checked together with a spot-height (point) layer,
  or two DXF sheets whose "entities" layers QGIS typed after different first
  entities, died in native:mergevectorlayers ("same geometry type");
- structure lines vs points was decided from the merged layer's type, so the
  same DXF content in another entity order gave another DEM;
- a geographic working CRS was accepted and 5-degree cells published as
  pixel_size_m = 5;
- 3D contours whose Z is 0 (elevation in a "Contour" field) gave a flat 0 m
  DEM reported as success;
- "자동" resolved to different columns for TIN and Kriging;
- Kriging read the file instead of the layer's unsaved edits;
- pixel size 0 reached the grid snapping ("float division by zero") and
  reprojection round-off added an all-NoData column;
- on QGIS < 3.38 the TIN/IDW ".tif" was Arc/Info ASCII without a CRS and a
  staged .prj was left behind; IDW's power was not recorded.

The dependency-free CI discovers this module and skips it when PyQGIS is not
importable; run it under QGIS' Python to exercise the dialog.
"""

from __future__ import annotations

import glob
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
    from osgeo import gdal, ogr, osr
    from qgis.PyQt import QtWidgets
    from qgis.PyQt.QtCore import Qt
    from qgis.core import (
        Qgis,
        QgsApplication,
        QgsFeature,
        QgsField,
        QgsGeometry,
        QgsLineString,
        QgsPoint,
        QgsPointXY,
        QgsProject,
        QgsRasterLayer,
        QgsRectangle,
        QgsVectorLayer,
    )

    from processing.core.Processing import Processing
    from tools import dem_generator_dialog
    from tools.dem_generator_dialog import DemGeneratorDialog
    from tools.qtcompat import FT_DOUBLE

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc


X0, Y0 = 200000.0, 500000.0


def _plane(x, y):
    """Terrain used by the DXF sheets: z = 100 + 0.05 dx + 0.02 dy (metres)."""
    return 100.0 + 0.05 * (x - X0) + 0.02 * (Y0 - y)


class _FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, title, text, level=0, duration=0):
        self.messages.append((str(title), str(text), level))


class _FakeIface:
    """The slice of QgisInterface the dialog touches."""

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

    def addRasterLayer(self, path, name=None, provider="gdal"):
        lyr = QgsRasterLayer(path, name or os.path.basename(path), provider)
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
        return lyr


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class DemGeneratorReview2Tests(unittest.TestCase):

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
        if registry.algorithmById("qgis:tininterpolation") is None or registry.algorithmById("native:savefeatures") is None:
            raise unittest.SkipTest("QGIS interpolation algorithms are unavailable")
        # No tearDownClass: a QgsApplication cannot be re-created in the same
        # process after exitQgis() (see tests/test_align_export_qgis.py).

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="archtoolkit_dem_review2_")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        env = mock.patch.dict(os.environ, {"ARCHTOOLKIT_NO_DIALOG_MEMORY": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.iface = _FakeIface()
        self._before_ids = set(QgsProject.instance().mapLayers().keys())
        self.addCleanup(self._drop_layers)

    def _drop_layers(self):
        project = QgsProject.instance()
        for lid in set(project.mapLayers().keys()) - self._before_ids:
            project.removeMapLayer(lid)

    # ------------------------------------------------------------ helpers
    def _layer(self, geom_uri, name, fields, feats, crs="EPSG:5186"):
        lyr = QgsVectorLayer(f"{geom_uri}?crs={crs}", name, "memory")
        self.assertTrue(lyr.crs().isValid())
        pr = lyr.dataProvider()
        pr.addAttributes([QgsField(n, t) for n, t in fields])
        lyr.updateFields()
        out = []
        for geom, attrs in feats:
            f = QgsFeature(lyr.fields())
            f.setGeometry(geom)
            f.setAttributes(list(attrs))
            out.append(f)
        pr.addFeatures(out)
        lyr.updateExtents()
        QgsProject.instance().addMapLayer(lyr)
        return lyr

    def _dialog(self):
        return DemGeneratorDialog(self.iface)

    def _run(self, layers, method, name, *, px=10.0, z_choice=None, dialog=None):
        d = dialog or self._dialog()
        wanted = {lyr.id() for lyr in layers}
        for i in range(d.listLayers.count()):
            it = d.listLayers.item(i)
            lyr = it.data(Qt.ItemDataRole.UserRole)
            checked = lyr is not None and lyr.id() in wanted
            it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        for i in range(d.cmbInterpolation.count()):
            if method in d.cmbInterpolation.itemText(i):
                d.cmbInterpolation.setCurrentIndex(i)
                break
        if z_choice is not None:
            idx = d.cmbZField.findData(z_choice)
            self.assertGreaterEqual(idx, 0, z_choice)
            d.cmbZField.setCurrentIndex(idx)
        d.spinPixelSize.setValue(float(px))
        out = os.path.join(self.temp_dir, name)
        d.fileOutput.setFilePath(out)
        n0 = len(self.iface._bar.messages)
        before = set(QgsProject.instance().mapLayers().keys())
        d.run_process()
        msgs = self.iface._bar.messages[n0:]
        added = [QgsProject.instance().mapLayer(k) for k in set(QgsProject.instance().mapLayers().keys()) - before]
        meta = {}
        for lyr in added:
            raw = lyr.customProperty("archtoolkit/params_json")
            if raw:
                meta[lyr.name()] = {"units": lyr.customProperty("archtoolkit/units"), "params": json.loads(raw)}
        return out, msgs, meta

    @staticmethod
    def _read(path):
        ds = gdal.Open(path)
        band = ds.GetRasterBand(1)
        arr = band.ReadAsArray().astype(float)
        nodata = band.GetNoDataValue()
        gt = ds.GetGeoTransform()
        wkt = ds.GetProjection()
        driver = ds.GetDriver().ShortName
        ds = None
        valid = np.isfinite(arr)
        if nodata is not None:
            valid &= arr != nodata
        return arr, valid, gt, wkt, driver

    @staticmethod
    def _centres(gt, shape):
        rows, cols = np.mgrid[0:shape[0], 0:shape[1]]
        return gt[0] + (cols + 0.5) * gt[1], gt[3] + (rows + 0.5) * gt[5]

    def _write_dxf(self, name, *, points_first, y_top=Y0):
        """DXF "entities" sheet: 3D contours of _plane (F0017111) + 3D spot heights (F0027217)."""
        path = os.path.join(self.temp_dir, name)
        ds = ogr.GetDriverByName("DXF").CreateDataSource(path)
        lyr = ds.CreateLayer("entities", geom_type=ogr.wkbUnknown)
        defn = lyr.GetLayerDefn()

        def add(code, geom):
            feat = ogr.Feature(defn)
            feat.SetField("Layer", code)
            feat.SetGeometry(geom)
            lyr.CreateFeature(feat)

        def spots():
            for dx, dy in [(0, 0), (400, 0), (0, 400), (400, 400), (200, 200), (123, 311)]:
                x, y = X0 + dx, y_top - dy
                g = ogr.Geometry(ogr.wkbPoint25D)
                g.AddPoint(x, y, _plane(x, y))
                add("F0027217", g)

        if points_first:
            spots()
        for zc in range(90, 140, 2):
            pts = []
            for i in range(41):
                x = X0 + i * 10.0
                y = Y0 - (zc - 100.0 - 0.05 * (x - X0)) / 0.02
                if y_top - 400 <= y <= y_top:
                    pts.append((x, y, float(zc)))
            if len(pts) >= 2:
                g = ogr.Geometry(ogr.wkbLineString25D)
                for p in pts:
                    g.AddPoint(*p)
                add("F0017111", g)
        if not points_first:
            spots()
        ds = None
        return path

    def _write_hill_dxf(self, name, *, points_first):
        """Same irregular hill (coarse contour polygons + summit) in two entity orders."""
        path = os.path.join(self.temp_dir, name)
        cx, cy = X0 + 200.0, Y0 - 200.0
        ds = ogr.GetDriverByName("DXF").CreateDataSource(path)
        lyr = ds.CreateLayer("entities", geom_type=ogr.wkbUnknown)
        defn = lyr.GetLayerDefn()

        def summit():
            g = ogr.Geometry(ogr.wkbPoint25D)
            g.AddPoint(cx + 7, cy + 3, 158.0)
            f = ogr.Feature(defn)
            f.SetField("Layer", "F0027217")
            f.SetGeometry(g)
            lyr.CreateFeature(f)

        if points_first:
            summit()
        for k, zc in enumerate(range(100, 160, 10)):
            radius = 190 - 30 * k
            g = ogr.Geometry(ogr.wkbLineString25D)
            for i in range(13):
                a = 2 * math.pi * i / 12 + 0.3 * k
                g.AddPoint(cx + radius * math.cos(a) * (1 + 0.4 * math.cos(2 * a)), cy + radius * math.sin(a), float(zc))
            f = ogr.Feature(defn)
            f.SetField("Layer", "F0017111")
            f.SetGeometry(g)
            lyr.CreateFeature(f)
        if not points_first:
            summit()
        ds = None
        return path

    def _load_dxf(self, dialog, paths):
        with mock.patch.object(dem_generator_dialog.QFileDialog, "getOpenFileNames", return_value=(list(paths), "")):
            dialog.load_dxf_file()
        names = {os.path.splitext(os.path.basename(p))[0] + "_DEM용" for p in paths}
        found = {lyr.name(): lyr for lyr in QgsProject.instance().mapLayers().values() if lyr.name() in names}
        self.assertEqual(len(found), len(paths))
        return found

    def _contours_and_spot(self):
        lines = []
        for k, zc in enumerate([100.0, 110.0, 120.0, 130.0]):
            h = 200 - 45 * k
            ring = [QgsPoint(X0 + 250 + dx * h, Y0 - 250 + dy * h) for dx, dy in [(-1, 1), (1, 1), (1, -1), (-1, -1), (-1, 1)]]
            lines.append((QgsGeometry(QgsLineString(ring)), [zc]))
        cont = self._layer("LineString", "contours_ELEV", [("ELEV", FT_DOUBLE)], lines)
        spot = self._layer("Point", "spot_ELEV", [("ELEV", FT_DOUBLE)],
                           [(QgsGeometry.fromPointXY(QgsPointXY(X0 + 250, Y0 - 250)), [147.0])])
        return cont, spot

    @staticmethod
    def _errors(msgs):
        return [text for _title, text, level in msgs if level == Qgis.MessageLevel.Critical]

    # ------------------------------------------------------------ tests
    def test_contours_and_spot_heights_in_separate_layers_run_for_every_method(self):
        cont, spot = self._contours_and_spot()
        for method in ("TIN - Linear", "IDW", "Kriging"):
            out, msgs, meta = self._run([cont, spot], method, f"mixed_{method[:3]}.tif")
            self.assertTrue(os.path.exists(out), (method, msgs))
            self.assertEqual(self._errors(msgs), [], method)
            arr, valid, *_ = self._read(out)
            # The 147 m summit exists only in the point layer; contours stop at 130 m.
            self.assertGreater(float(arr[valid].max()), 140.0, method)

    def test_dxf_sheets_with_different_first_entities_interpolate_together(self):
        d = self._dialog()
        found = self._load_dxf(d, [
            self._write_dxf("sheet_lines_first.dxf", points_first=False, y_top=Y0),
            self._write_dxf("sheet_points_first.dxf", points_first=True, y_top=Y0 - 400.0),
        ])
        for method in ("TIN - Linear", "IDW"):
            out, msgs, _meta = self._run(list(found.values()), method, f"sheets_{method[:3]}.tif")
            self.assertTrue(os.path.exists(out), (method, msgs))
            arr, valid, gt, _wkt, _drv = self._read(out)
            self.assertEqual(arr.shape, (80, 40))
            if method.startswith("TIN"):
                x, y = self._centres(gt, arr.shape)
                err = np.abs(arr - _plane(x, y))[valid]
                self.assertLess(float(err.max()), 1e-3)

    def test_dxf_entity_order_does_not_change_the_dem(self):
        d = self._dialog()
        found = self._load_dxf(d, [
            self._write_hill_dxf("hill_lines_first.dxf", points_first=False),
            self._write_hill_dxf("hill_points_first.dxf", points_first=True),
        ])
        out_a, msgs_a, _ = self._run([found["hill_lines_first_DEM용"]], "TIN - Linear", "hill_a.tif", px=5.0)
        out_b, msgs_b, _ = self._run([found["hill_points_first_DEM용"]], "TIN - Linear", "hill_b.tif", px=5.0)
        a, va, *_ = self._read(out_a)
        b, vb, *_ = self._read(out_b)
        self.assertEqual(a.shape, b.shape)
        both = va & vb
        self.assertGreater(int(both.sum()), 1000)
        # Before: 3.57 m apart, 794 cells > 0.5 m (contours enforced only when
        # the sheet's first entity was a line).
        self.assertLess(float(np.abs(a - b)[both].max()), 1e-6)

    def test_geographic_working_crs_is_refused(self):
        feats = [(QgsGeometry.fromPointXY(QgsPointXY(127.0 + i * 0.002, 37.0 + j * 0.002)), [100.0 + i + j])
                 for i in range(6) for j in range(6)]
        geo = self._layer("Point", "geo_pts", [("ELEV", FT_DOUBLE)], feats, crs="EPSG:4326")
        for method in ("TIN - Linear", "IDW"):
            out, msgs, _meta = self._run([geo], method, f"geo_{method[:3]}.tif", px=5.0)
            self.assertFalse(os.path.exists(out), method)
            self.assertTrue(any("지리 좌표계" in t for t in self._errors(msgs)), msgs)

    def test_all_zero_geometry_z_is_refused_and_names_the_candidate_fields(self):
        feats = []
        for k, zc in enumerate([100.0, 110.0, 120.0, 130.0]):
            h = 200 - 45 * k
            ring = [QgsPoint(X0 + 250 + dx * h, Y0 - 250 + dy * h, 0.0) for dx, dy in [(-1, 1), (1, 1), (1, -1), (-1, -1), (-1, 1)]]
            feats.append((QgsGeometry(QgsLineString(ring)), [zc, float(k + 1)]))
        lyr = self._layer("LineStringZ", "contour_arcgis", [("Contour", FT_DOUBLE), ("Id", FT_DOUBLE)], feats)
        out, msgs, _meta = self._run([lyr], "TIN - Linear", "zero_z.tif")
        self.assertFalse(os.path.exists(out))
        errors = self._errors(msgs)
        self.assertTrue(any("Contour" in t and "Z 좌표가 모두 0" in t for t in errors), msgs)
        # The explicit pick still works and gives the real surface.
        out, msgs, meta = self._run([lyr], "TIN - Linear", "contour_field.tif", z_choice="Contour")
        arr, valid, *_ = self._read(out)
        self.assertGreater(float(arr[valid].min()), 100.0)
        params = list(meta.values())[0]["params"]
        self.assertEqual(params.get("value_field"), "Contour")
        self.assertEqual(params.get("value_source"), "attribute")

    def test_auto_field_is_the_same_for_tin_and_kriging(self):
        rng = np.random.default_rng(4)
        pa = [(X0 + rng.uniform(0, 300), Y0 - rng.uniform(0, 300)) for _ in range(40)]
        pb = [(X0 + rng.uniform(0, 300), Y0 - rng.uniform(0, 300)) for _ in range(40)]
        la = self._layer("Point", "A_ELEV", [("ELEV", FT_DOUBLE)], [(QgsGeometry.fromPointXY(QgsPointXY(*p)), [100.0]) for p in pa])
        lb = self._layer("Point", "B_Elevation", [("Elevation", FT_DOUBLE)],
                         [(QgsGeometry.fromPointXY(QgsPointXY(*p)), [200.0]) for p in pb])
        means = {}
        for method in ("TIN - Linear", "Kriging"):
            out, msgs, _meta = self._run([la, lb], method, f"auto_{method[:3]}.tif")
            self.assertTrue(any("B_Elevation" in t and "제외" in t for _t, t, _l in msgs), msgs)
            arr, valid, *_ = self._read(out)
            means[method] = float(arr[valid].mean())
        # The notice says B is excluded; before, Kriging then used ONLY B (200).
        self.assertAlmostEqual(means["TIN - Linear"], 100.0, places=3)
        self.assertAlmostEqual(means["Kriging"], 100.0, places=3)

    def test_kriging_reads_unsaved_edits_like_tin(self):
        path = os.path.join(self.temp_dir, "edits.shp")
        ds = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(path)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(5186)
        olyr = ds.CreateLayer("edits", srs, ogr.wkbPoint)
        olyr.CreateField(ogr.FieldDefn("ELEV", ogr.OFTReal))
        rng = np.random.default_rng(1)
        for _ in range(60):
            f = ogr.Feature(olyr.GetLayerDefn())
            g = ogr.Geometry(ogr.wkbPoint)
            g.AddPoint_2D(X0 + rng.uniform(0, 300), Y0 - rng.uniform(0, 300))
            f.SetGeometry(g)
            f.SetField("ELEV", 50.0 + rng.uniform(0, 10))
            olyr.CreateFeature(f)
        ds = None
        lyr = QgsVectorLayer(path, "edits", "ogr")
        self.assertTrue(lyr.isValid())
        QgsProject.instance().addMapLayer(lyr)
        lyr.startEditing()
        self.addCleanup(lyr.rollBack)
        idx = lyr.fields().indexFromName("ELEV")
        for feat in lyr.getFeatures():
            lyr.changeAttributeValue(feat.id(), idx, 0.0)
        for method in ("TIN - Linear", "Kriging"):
            out, msgs, _meta = self._run([lyr], method, f"edits_{method[:3]}.tif")
            arr, valid, *_ = self._read(out)
            # Before: Kriging read the file (mean ~55) while TIN used the edits.
            self.assertAlmostEqual(float(arr[valid].mean()), 0.0, places=4, msg=method)

    def test_zero_pixel_size_is_refused(self):
        lyr = self._layer("Point", "px0", [("ELEV", FT_DOUBLE)],
                          [(QgsGeometry.fromPointXY(QgsPointXY(X0 + 50 * i, Y0 - 50 * j)), [100.0 + i + j]) for i in range(4) for j in range(4)])
        d = self._dialog()
        self.assertGreater(d.spinPixelSize.minimum(), 0.0)
        with mock.patch.object(d.spinPixelSize, "value", return_value=0.0):
            d.spinPixelSize.setValue = lambda *_a: None
            out, msgs, _meta = self._run([lyr], "TIN - Linear", "px0.tif", dialog=d)
        self.assertFalse(os.path.exists(out))
        errors = self._errors(msgs)
        self.assertTrue(any("픽셀 크기" in t for t in errors), msgs)
        self.assertFalse(any("division" in t for t in errors), msgs)

    def test_grid_snapping_ignores_round_off(self):
        # A 5186 -> 5179 -> 5186 round trip leaves x0 + 300.0000000001.
        _rect, ncols, nrows = DemGeneratorDialog._snap_extent_to_pixel(QgsRectangle(X0, Y0 - 300.0, X0 + 300.0000000001, Y0), 10.0)
        self.assertEqual((ncols, nrows), (30, 30))
        _rect, ncols, nrows = DemGeneratorDialog._snap_extent_to_pixel(QgsRectangle(X0, Y0 - 200.0, X0 + 301.0, Y0), 10.0)
        self.assertEqual((ncols, nrows), (31, 20))

    def test_published_dem_is_geotiff_with_crs_and_idw_settings_are_recorded(self):
        rng = np.random.default_rng(2)
        pts = [(X0, Y0), (X0 + 300, Y0), (X0, Y0 - 300), (X0 + 300, Y0 - 300)]
        pts += [(X0 + rng.uniform(0, 300), Y0 - rng.uniform(0, 300)) for _ in range(40)]
        lyr = self._layer("Point", "plane_pts", [("ELEV", FT_DOUBLE)],
                          [(QgsGeometry.fromPointXY(QgsPointXY(x, y)), [_plane(x, y)]) for x, y in pts])
        for method in ("TIN - Linear", "IDW"):
            out, msgs, meta = self._run([lyr], method, f"crs_{method[:3]}.tif")
            arr, valid, gt, wkt, driver = self._read(out)
            self.assertEqual(driver, "GTiff", method)
            srs = osr.SpatialReference(wkt=wkt)
            srs.AutoIdentifyEPSG()
            self.assertEqual(srs.GetAuthorityCode(None), "5186", method)
            params = list(meta.values())[0]["params"]
            self.assertEqual(params.get("pixel_size_m"), 10.0)
            self.assertEqual(params.get("value_source"), "attribute")
            if method == "IDW":
                self.assertEqual(params.get("idw"), {"power": 2.0, "search": "all_points"})
            else:
                x, y = self._centres(gt, arr.shape)
                self.assertLess(float(np.abs(arr - _plane(x, y))[valid].max()), 1e-3)
        leftovers = glob.glob(os.path.join(self.temp_dir, ".*archtoolkit-staged*"))
        self.assertEqual(leftovers, [])

    def test_dxf_without_crs_stays_without_crs_and_is_not_labelled_metres(self):
        d = self._dialog()
        found = self._load_dxf(d, [self._write_dxf("nocrs.dxf", points_first=False)])
        out, msgs, meta = self._run(list(found.values()), "TIN - Linear", "nocrs.tif")
        _arr, _valid, _gt, wkt, _driver = self._read(out)
        # A scratch memory layer defaults to EPSG:4326; TM metres must not be
        # published as WGS 84 degrees.
        self.assertEqual(wkt, "")
        entry = list(meta.values())[0]
        self.assertNotIn("pixel_size_m", entry["params"])
        self.assertEqual(entry["params"].get("pixel_size_map_units"), 10.0)
        self.assertEqual(entry["params"].get("crs_units"), "unknown")


if __name__ == "__main__":
    unittest.main()
