"""QGIS integration tests for the trench-suggestion review fixes.

Like tests/test_align_export_qgis.py this module is discovered by the
dependency-free CI and skips (never fails) when PyQGIS, GDAL or processing are
unavailable. Run it with QGIS' Python to exercise the real dialog:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=/usr/share/qgis/python/plugins \
        python3 -m unittest tests.test_trench_review -v

Covered:
- the slope limit and ``slope_max_deg`` come from every slope cell under the
  real L x W rectangle (a 57 deg band inside the footprint rejects the
  candidate; a wall 10 m beside a 2 m wide trench does not; on a coarse DEM
  the field never exceeds the footprint's own cells);
- a candidate whose AHP value is NoData is excluded and counted;
- candidates outside the DEM are counted and named in the message;
- a reference layer with no site in range is named as such.
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
    from qgis.PyQt.QtCore import QCoreApplication
    from qgis.core import (
        QgsApplication,
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
    from tools.qtcompat import FT_STRING
    from tools.trench_suggestion_dialog import TrenchSuggestionDialog
    from tools.utils import get_archtoolkit_layer_metadata, is_null_value

    if _REGRESSION_DIR not in sys.path:
        sys.path.insert(0, _REGRESSION_DIR)
    import qgis_env  # noqa: E402  (tests/regression/qgis_env.py: FakeIface, make_dem)

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class TrenchReviewQgisTests(unittest.TestCase):
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
        Processing.initialize()
        if QgsApplication.processingRegistry().algorithmById("gdal:slope") is None:
            raise unittest.SkipTest("QGIS GDAL provider is unavailable")
        cls.canvas = QgsMapCanvas()
        cls.iface = qgis_env.FakeIface(cls.canvas)

    # No tearDownClass: a QgsApplication cannot be re-created in the same
    # process once exitQgis() has run (see tests/test_align_export_qgis.py).

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="archtoolkit_trench_review_")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        # Cleanups run last-in first-out: layers go before their directory does.
        self.addCleanup(QgsProject.instance().removeAllMapLayers)
        QgsProject.instance().removeAllMapLayers()
        self.iface._bar.messages.clear()

    # ---- helpers -----------------------------------------------------------

    def _path(self, name):
        return os.path.join(self.temp_dir, name)

    def _write_raster(self, name, arr, *, xmin=200000.0, ymax=500000.0, px=1.0, epsg=5186, nodata=-9999.0):
        path = self._path(name)
        nrows, ncols = arr.shape
        ds = gdal.GetDriverByName("GTiff").Create(path, ncols, nrows, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((xmin, px, 0.0, ymax, 0.0, -px))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(epsg)
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(nodata)
        band.WriteArray(arr.astype(np.float32))
        band.FlushCache()
        ds = None
        return path

    def _raster_layer(self, path, name):
        lyr = QgsRasterLayer(path, name, "gdal")
        self.assertTrue(lyr.isValid(), path)
        QgsProject.instance().addMapLayer(lyr)
        return lyr

    def _rect_layer(self, name, x0, y0, x1, y1):
        lyr = QgsVectorLayer("Polygon?crs=EPSG:5186", name, "memory")
        pr = lyr.dataProvider()
        pr.addAttributes([QgsField("name", FT_STRING)])
        lyr.updateFields()
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromRect(QgsRectangle(x0, y0, x1, y1)))
        f.setAttributes([name])
        pr.addFeatures([f])
        lyr.updateExtents()
        QgsProject.instance().addMapLayer(lyr)
        return lyr

    def _point_layer(self, name, coords):
        lyr = QgsVectorLayer("Point?crs=EPSG:5186", name, "memory")
        pr = lyr.dataProvider()
        feats = []
        for x, y in coords:
            f = QgsFeature()
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(x), float(y))))
            feats.append(f)
        pr.addFeatures(feats)
        lyr.updateExtents()
        QgsProject.instance().addMapLayer(lyr)
        return lyr

    def _run(self, aoi, dem, *, ahp=None, ref=None, count=12, grid=10.0, length=20.0, width=2.0,
             spacing=6.0, slope_max=30.0, ref_radius=1000.0, inside_pct=95.0):
        self.iface._bar.messages.clear()
        d = TrenchSuggestionDialog(self.iface)
        d.cmbAoi.setLayer(aoi)
        d.chkAoiSelectedOnly.setChecked(False)
        d.cmbDem.setLayer(dem)
        d.cmbAhp.setLayer(ahp)
        d.cmbRefSites.setLayer(ref)
        d.cmbTopo.setLayer(None)
        d.spinWidth.setValue(width)
        d.spinLength.setValue(length)
        d.spinCount.setValue(count)
        d.spinGrid.setValue(grid)
        d.spinMinSpacing.setValue(spacing)
        d.spinInsidePct.setValue(inside_pct)
        d.spinSlopeMax.setValue(slope_max)
        d.spinRefRadius.setValue(ref_radius)
        before = set(QgsProject.instance().mapLayers().keys())
        d._run()
        t0 = time.time()
        while time.time() - t0 < 0.2:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        polys = [lyr for lid, lyr in QgsProject.instance().mapLayers().items()
                 if lid not in before and str(lyr.name()).startswith("Trench_Suggestions_")]
        msgs = [" | ".join(str(a) for a in args[:2]) for args, _kw in self.iface.pushed()]
        return (polys[0] if polys else None), msgs

    @staticmethod
    def _rows(layer):
        out = []
        for f in layer.getFeatures():
            row = {fld.name(): f[fld.name()] for fld in layer.fields()}
            row["geom"] = f.geometry()
            out.append(row)
        return out

    @staticmethod
    def _meta(layer):
        return (get_archtoolkit_layer_metadata(layer) or {}).get("params") or {}

    def _independent_slope(self, dem_path):
        """gdaldem slope (Horn, compute_edges, scale 1) exactly as the tool runs it."""
        out = self._path("slope_independent.tif")
        gdal.DEMProcessing(out, dem_path, "slope", computeEdges=True, scale=1.0, slopeFormat="degree")
        ds = gdal.Open(out)
        gt = ds.GetGeoTransform()
        arr = ds.GetRasterBand(1).ReadAsArray().astype(float)
        nd = ds.GetRasterBand(1).GetNoDataValue()
        ds = None
        return arr, gt, nd

    @staticmethod
    def _centre_cells_max(pt, arr, gt):
        """Max over every cell whose closed extent contains ``pt`` (1-4 cells)."""
        fx = (pt.x() - gt[0]) / gt[1]
        fy = (gt[3] - pt.y()) / -gt[5]
        cols = {int(math.floor(fx))}
        rows = {int(math.floor(fy))}
        if abs(fx - round(fx)) < 1e-6:
            cols.update((int(round(fx)) - 1, int(round(fx))))
        if abs(fy - round(fy)) < 1e-6:
            rows.update((int(round(fy)) - 1, int(round(fy))))
        return max(float(arr[r, c]) for r in rows for c in cols)

    @staticmethod
    def _footprint_max(geom, arr, gt, nd):
        """(max over cells whose CENTRE is in geom or None, max over all-touched cells)."""
        bb = geom.boundingBox()
        px = gt[1]
        py = -gt[5]
        c0 = max(0, int((bb.xMinimum() - gt[0]) / px) - 1)
        c1 = min(arr.shape[1] - 1, int((bb.xMaximum() - gt[0]) / px) + 1)
        r0 = max(0, int((gt[3] - bb.yMaximum()) / py) - 1)
        r1 = min(arr.shape[0] - 1, int((gt[3] - bb.yMinimum()) / py) + 1)
        engine = QgsGeometry.createGeometryEngine(geom.constGet())
        engine.prepareGeometry()
        mx_centre = None
        mx_touch = None
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                v = float(arr[r, c])
                if nd is not None and v == nd:
                    continue
                cx = gt[0] + (c + 0.5) * px
                cy = gt[3] - (r + 0.5) * py
                ptg = QgsGeometry.fromPointXY(QgsPointXY(cx, cy))  # keep alive for constGet()
                cell = QgsGeometry.fromRect(QgsRectangle(cx - px / 2, cy - py / 2, cx + px / 2, cy + py / 2))
                if engine.contains(ptg.constGet()):
                    mx_centre = v if mx_centre is None else max(mx_centre, v)
                if engine.intersects(cell.constGet()):
                    mx_touch = v if mx_touch is None else max(mx_touch, v)
        return mx_centre, mx_touch

    # ---- fix 1: footprint slope over the real rectangle -----------------------

    def test_steep_band_inside_footprint_is_rejected(self):
        # 1 m DEM: 2.9 deg plane rising east (E-W trenches) plus a 4 m step over
        # x 200148-200150, i.e. 57 deg cells that a 20 m trench centred 5-7 m away
        # crosses although none of its nine rosette samples land on them.
        yy, xx = np.mgrid[0:200, 0:300].astype(float)
        xm = 200000.0 + (xx + 0.5)
        z = 100.0 + 0.05 * (xm - 200000.0) + 4.0 * np.clip((xm - 200148.0) / 2.0, 0.0, 1.0)
        dem_path = self._write_raster("dem_band.tif", z)
        dem = self._raster_layer(dem_path, "DEM")
        aoi = self._rect_layer("AOI", 200050, 499850, 200250, 499970)
        poly, msgs = self._run(aoi, dem, count=200, grid=10.0, spacing=1.0, slope_max=30.0)
        self.assertIsNotNone(poly, msgs)
        rows = self._rows(poly)
        self.assertGreater(len(rows), 20)
        band = QgsGeometry.fromRect(QgsRectangle(200148, 499800, 200150, 500000))
        crossing = [r for r in rows if r["geom"].intersects(band)]
        self.assertEqual(crossing, [], "trenches crossing the 57 deg band were accepted")
        self.assertTrue(all(float(r["slope_max_deg"]) <= 30.0 for r in rows))
        meta = self._meta(poly)
        self.assertEqual(meta.get("slope_test"), "footprint_cells_max")
        self.assertEqual(meta.get("skipped_no_dem"), 0)
        # The field is the footprint's own cells: equal to an independent cell-centre max.
        arr, gt, nd = self._independent_slope(dem_path)
        for r in rows:
            mx_centre, mx_touch = self._footprint_max(r["geom"], arr, gt, nd)
            self.assertIsNotNone(mx_centre)
            expect = max(mx_centre, self._centre_cells_max(r["geom"].centroid().asPoint(), arr, gt))
            self.assertAlmostEqual(float(r["slope_max_deg"]), expect, delta=0.05)
            self.assertLessEqual(float(r["slope_max_deg"]), mx_touch + 0.05)

    def test_wall_beside_narrow_trench_is_not_a_footprint_slope(self):
        # Flat DEM with a 3 m wall over y 499972-499975. AOI 100 x 30 (E-W long
        # axis -> flat-mode E-W 20 x 2 m trenches), grid 10 -> centre rows 499955 /
        # 499965 / 499975. The old test sampled a circle of radius L/2 = 10 m, so
        # the 499965 row (2 m wide footprints, all flat) was rejected because a
        # sample 7-10 m north hit the wall: 3 of 30 trenches, blamed on the terrain.
        yy, xx = np.mgrid[0:100, 0:200].astype(float)
        ym = 500000.0 - (yy + 0.5)
        z = 100.0 + 3.0 * ((ym > 499972.0) & (ym < 499975.0))
        dem = self._raster_layer(self._write_raster("dem_wall.tif", z), "DEM")
        aoi = self._rect_layer("AOI", 200000, 499950, 200100, 499980)
        poly, msgs = self._run(aoi, dem, count=30, grid=10.0, length=20.0, width=2.0, spacing=2.0, slope_max=30.0)
        self.assertIsNotNone(poly, msgs)
        meta = self._meta(poly)
        # Per row, x 200015-200085 pass the 95 % inside ratio (8 candidates); the
        # two flat rows keep all of theirs, the row on the wall keeps none.
        self.assertEqual(int(meta["candidates_kept"]), 16)
        self.assertEqual(int(meta["skipped_no_dem"]), 0)
        rows = self._rows(poly)
        ys = sorted(set(round(r["geom"].centroid().asPoint().y()) for r in rows))
        self.assertEqual(ys, [499955, 499965])
        self.assertTrue(all(float(r["slope_max_deg"]) == 0.0 for r in rows))

    def test_coarse_dem_field_matches_footprint_cells(self):
        # 10 m DEM, 20 x 2 m trenches: the old circle of radius 2 px = 20 m
        # reported terrain up to 20 m from the trench. The field must now equal
        # the max over the footprint's own cell centres (or the centre cell).
        dem_path = qgis_env.make_dem(self._path("ridge10.tif"), kind="ridge")
        dem = self._raster_layer(dem_path, "DEM10")
        aoi = self._rect_layer("AOI", 200150, 499550, 200450, 499850)
        poly, msgs = self._run(aoi, dem, count=40, grid=20.0, spacing=1.0, slope_max=90.0)
        self.assertIsNotNone(poly, msgs)
        rows = self._rows(poly)
        self.assertEqual(len(rows), 40)
        arr, gt, nd = self._independent_slope(dem_path)
        for r in rows:
            mx_centre, mx_touch = self._footprint_max(r["geom"], arr, gt, nd)
            field = float(r["slope_max_deg"])
            self.assertLessEqual(field, mx_touch + 0.05)
            self.assertGreaterEqual(field, float(r["slope_deg"]) - 1e-6)
            # Candidate centres of this grid sit on DEM cell corners, so the
            # "cell under the centre" is every cell sharing that corner.
            expect = self._centre_cells_max(r["geom"].centroid().asPoint(), arr, gt)
            if mx_centre is not None:
                expect = max(expect, mx_centre)
            self.assertAlmostEqual(field, expect, delta=0.05)

    # ---- fix 2: AHP NoData candidates are excluded and counted -----------------

    def test_ahp_nodata_candidates_are_excluded_and_counted(self):
        flat = np.full((300, 300), 100.0)
        dem = self._raster_layer(self._write_raster("flat.tif", flat), "FLAT")
        yy, xx = np.mgrid[0:300, 0:300].astype(float)
        ahp = xx / 300.0 * 100.0  # low west, high east
        ahp[:, 130:170] = -9999.0  # NoData strip x 200130-200170
        ahp_l = self._raster_layer(self._write_raster("ahp_nodata.tif", ahp), "AHP")
        aoi = self._rect_layer("AOI", 200020, 499900, 200280, 499940)
        poly, msgs = self._run(aoi, dem, ahp=ahp_l, count=60, grid=10.0, spacing=1.0, slope_max=90.0)
        self.assertIsNotNone(poly, msgs)
        rows = self._rows(poly)
        self.assertTrue(all(not is_null_value(r["ahp_val"]) for r in rows), "a NoData-AHP trench was output")
        meta = self._meta(poly)
        # 4 grid columns (200135-200165) x 4 rows (499905-499935) fall in the strip.
        self.assertEqual(meta.get("skipped_ahp_nodata"), 16)
        self.assertIn("AHP 값 없음(NoData/범위 밖)으로 제외된 후보 16개", msgs[-1])
        # One formula for every candidate, so rank is comparable.
        we = meta["weights_effective"]
        norm = meta["ahp_norm"]
        for key, val in (("ahp", 0.55), ("ref", 0.0), ("slope", 0.2)):
            self.assertAlmostEqual(float(we[key]), val, places=9)
        for r in rows:
            a = max(0.0, min(1.0, (float(r["ahp_val"]) - norm["min"]) / (norm["max"] - norm["min"])))
            expect = (0.55 * a + 0.2 * (1.0 - float(r["slope_deg"]) / 90.0)) / 0.75
            self.assertAlmostEqual(float(r["score"]), expect, places=6)

    # ---- fix 3: candidates without DEM are counted ---------------------------

    def test_candidates_without_dem_are_counted(self):
        flat = np.full((300, 300), 100.0)  # x 200000-200300
        dem = self._raster_layer(self._write_raster("flat_small.tif", flat), "FLAT")
        aoi = self._rect_layer("AOI", 200200, 499900, 200400, 499940)  # half of it east of the DEM
        poly, msgs = self._run(aoi, dem, count=20, grid=10.0, spacing=1.0)
        self.assertIsNotNone(poly, msgs)
        meta = self._meta(poly)
        # Centres x 200205-200395 by 10 m, 4 rows. Columns 200305-200395 (10) have
        # no DEM under the centre; the 200295 column's E-W 20 m footprint runs past
        # the DEM edge at 200300. (11 columns x 4 rows) = 44, previously silent.
        self.assertEqual(int(meta["candidates_scanned"]), 80)
        self.assertEqual(int(meta.get("skipped_no_dem")), 44)
        self.assertIn("DEM 밖/결손으로 제외된 후보 44개", msgs[-1])
        for r in self._rows(poly):
            self.assertLessEqual(r["geom"].boundingBox().xMaximum(), 200300.0 + 1e-6)

    def test_footprint_over_nodata_hole_is_rejected(self):
        z = np.full((300, 300), 100.0)
        z[40:60, 120:125] = -9999.0  # hole x 200120-200125, y 499940-499960
        dem = self._raster_layer(self._write_raster("flat_hole.tif", z), "FLAT")
        aoi = self._rect_layer("AOI", 200020, 499900, 200220, 499990)
        poly, msgs = self._run(aoi, dem, count=40, grid=10.0, spacing=1.0)
        self.assertIsNotNone(poly, msgs)
        hole = QgsGeometry.fromRect(QgsRectangle(200120, 499940, 200125, 499960))
        # Overlap by area: a trench whose edge merely touches the hole (x 200125)
        # has no footprint cell in it. Before the fix a 200105-200125 trench,
        # 10 m2 of it over NoData, was output with slope_max_deg 0.0.
        over = [r for r in self._rows(poly) if r["geom"].intersection(hole).area() > 1e-6]
        self.assertEqual(over, [])
        self.assertGreater(int(self._meta(poly).get("skipped_no_dem")), 0)

    # ---- fix 4: reference layer with nothing in range is named ----------------

    def test_reference_layer_with_no_site_in_range_is_named(self):
        flat = np.full((300, 300), 100.0)
        dem = self._raster_layer(self._write_raster("flat_ref.tif", flat), "FLAT")
        aoi = self._rect_layer("AOI", 200050, 499850, 200250, 499970)
        far = self._point_layer("Far", [(150000, 450000)])
        poly, msgs = self._run(aoi, dem, ref=far, count=4, ref_radius=100.0)
        self.assertIsNotNone(poly, msgs)
        meta = self._meta(poly)
        self.assertTrue(meta.get("ref_layer_given"))
        self.assertFalse(meta.get("ref_used"))
        self.assertIn("반경 내 참조 유적 없음", msgs[-1])
        self.assertTrue(all(is_null_value(r["ref_dist_m"]) for r in self._rows(poly)))
        self.assertTrue(math.isclose(meta["weights_effective"]["ref"], 0.0))


if __name__ == "__main__":
    unittest.main()
