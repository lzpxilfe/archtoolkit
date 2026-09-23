"""Correctness pins for 지구화학도 래스터 수치화 (tools/geochem_polygonize_dialog.py).

Each test reproduces a wrong output found in the second review round:
- a re-run deleted the whole "ArchToolkit - GeoChem" group once anything sat
  above it in the layer tree;
- pixels exactly at a legend stop fell into the class below the stop for
  3.1/5.7/7.1/9.4 (float32 vs float64 breaks);
- inpainting filled every off-legend pixel (white background included) and
  averaged the two sides of a line into a class present on neither side;
- the anti-aliased edge of a black line over red read as ~50 %;
- "low range as NoData" dropped the lowest class of a custom legend;
- legend-image import sampled a continuous bar at box centres;
- the high-end snap below t=0.5 lowered values;
- the NoData-polygon option did nothing, transparent pixels triggered the
  legend-mismatch warning, zones outside the export rectangle vanished, and
  the pixel-size box could not hold a geographic pixel size.

The QGIS-free part runs everywhere; the dialog part skips when PyQGIS is not
importable. Run it under QGIS' Python to exercise the dialog end to end.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

from tools import geochem_legend as GL
from tools.geochem_legend import LegendPoint, interp_rgb_to_value, mask_black_lines

QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
    from osgeo import gdal, osr
    from qgis.PyQt import QtWidgets
    from qgis.PyQt.QtGui import QColor, QImage
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

    from processing.core.Processing import Processing
    from tools import geochem_polygonize_dialog as GD
    from tools.qtcompat import FT_INT

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc


FE2O3 = [
    LegendPoint(0.0, (204, 204, 204)),
    LegendPoint(3.1, (0, 38, 115)),
    LegendPoint(3.5, (0, 112, 255)),
    LegendPoint(3.9, (0, 197, 255)),
    LegendPoint(4.5, (0, 255, 0)),
    LegendPoint(5.7, (85, 255, 0)),
    LegendPoint(7.1, (255, 255, 0)),
    LegendPoint(8.5, (255, 170, 0)),
    LegendPoint(9.4, (255, 85, 0)),
    LegendPoint(12.0, (230, 0, 0)),
    LegendPoint(51.0, (115, 12, 12)),
]


def _colour_for(points, values):
    pts = sorted(points, key=lambda p: p.value)
    vals = np.array([p.value for p in pts])
    cols = np.array([p.rgb for p in pts], dtype=float)
    return np.stack([np.interp(values, vals, cols[:, k]) for k in range(3)], 0)


class GeoChemLegendReview2Tests(unittest.TestCase):
    """QGIS-free pins on tools/geochem_legend.py."""

    def test_snap_below_half_raises_values_to_the_maximum(self):
        # Pixels on the last Fe2O3 segment (12 -> 51) at t = 0.35..0.45 with
        # snap t = 0.3 came back as 12.0 or NaN: the snapped (endpoint)
        # distance lost the segment competition to the red stop.
        t = np.array([0.35, 0.4, 0.45, 0.6])
        rgb = np.round(np.array([230.0, 0, 0]) + t[:, None] * np.array([-115.0, 12, 12]))
        out = interp_rgb_to_value(r=rgb[:, 0], g=rgb[:, 1], b=rgb[:, 2], points=FE2O3,
                                  snap_last_t=0.3, max_distance=48.0)
        np.testing.assert_allclose(out, [51.0, 51.0, 51.0, 51.0])

    def test_colour_halo_of_black_line_over_red_is_flagged_but_navy_is_not(self):
        rgb = np.zeros((3, 10, 12), np.uint8)
        rgb[:, :5, :] = np.array([0, 38, 115])[:, None, None]     # navy (3.1), ~0.45 x the blue stop
        rgb[:, 5:, :] = np.array([230, 0, 0])[:, None, None]      # red (12)
        rgb[:, :, 6] = 0                                          # black 1-px line
        rgb[0, 5:, 5] = 115
        rgb[0, 5:, 7] = 115                                       # 50 % anti-alias edge
        rgb[0, 5:, 4] = 172
        rgb[0, 5:, 8] = 172                                       # 25 % edge
        core = mask_black_lines(*rgb)
        halo = GL.mask_colour_halo(*rgb, core=core)
        self.assertTrue(halo[5:, [4, 5, 7, 8]].all())
        self.assertFalse(halo[:5].any(), "legitimate navy next to the line must stay data")
        self.assertFalse(halo[:, [0, 1, 2, 10, 11]].any())

    def test_fill_copies_nearest_value_and_never_averages(self):
        v = np.full((7, 5), 4.5, np.float32)
        v[4:] = 7.1
        v[3] = np.nan                                             # a line between the two classes
        mask = ~np.isfinite(v)
        out, filled = GL.fill_nearest(v, fill_mask=mask, valid=np.isfinite(v), max_dist_px=5, nodata=-9999.0)
        self.assertTrue(filled[3].all())
        self.assertEqual(set(np.unique(out).tolist()), {np.float32(4.5), np.float32(7.1)})

    def test_fill_passes_on_nodata_from_white_background(self):
        v = np.full((5, 9), -9999.0, np.float32)                  # white background (NoData)
        v[:, :2] = 12.0
        mask = np.zeros(v.shape, bool)
        mask[:, 6] = True                                         # a black line deep in the white area
        out, filled = GL.fill_nearest(v, fill_mask=mask, valid=v != -9999.0, max_dist_px=30, nodata=-9999.0)
        self.assertFalse(filled.any())
        self.assertTrue((out[:, 6] == -9999.0).all())

    def test_continuous_bar_is_sampled_at_its_ends(self):
        rows = GL.legend_sample_rows(10, 300, low_at_bottom=True, continuous=True)
        self.assertEqual(rows[0], 299)
        self.assertEqual(rows[-1], 0)
        # Box legends keep the box centres.
        self.assertEqual(GL.legend_sample_rows(10, 300, low_at_bottom=True)[0], 285)

    def test_profile_detection_tells_boxes_from_a_continuous_bar(self):
        vals = [p.value for p in FE2O3[1:]]
        pos = np.linspace(0, 1, 300)
        cont = _colour_for(FE2O3[1:], np.interp(pos * 9, np.arange(10), vals)).T
        boxes = np.array([FE2O3[1 + min(9, int(p * 10))].rgb for p in pos], float)
        self.assertFalse(GL.legend_profile_looks_discrete(cont, 10))
        self.assertTrue(GL.legend_profile_looks_discrete(boxes, 10))

    def test_absent_grey_first_stop_detection(self):
        self.assertTrue(GL.legend_first_stop_is_absent_grey(FE2O3))
        self.assertFalse(GL.legend_first_stop_is_absent_grey(FE2O3[1:]))


class _FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, title, text, level=0, duration=0):
        self.messages.append((str(title), str(text), int(getattr(level, "value", level))))


class _FakeIface:
    def __init__(self, canvas):
        self._bar = _FakeMessageBar()
        self._canvas = canvas

    def messageBar(self):
        return self._bar

    def mainWindow(self):
        if not hasattr(self, "_window"):
            self._window = QtWidgets.QMainWindow()
        return self._window

    def mapCanvas(self):
        return self._canvas


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class GeoChemDialogReview2Tests(unittest.TestCase):
    # 60 x 60 cells of 10 m: x 200000-200600, y 500000-500600 (EPSG:5186).
    GT = (200000.0, 10.0, 0.0, 500600.0, 0.0, -10.0)

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
        if QgsApplication.processingRegistry().algorithmById("gdal:polygonize") is None:
            raise unittest.SkipTest("QGIS GDAL provider is unavailable")
        cls._shim_gdal_polygonize()
        cls.canvas = QgsMapCanvas()
        cls.canvas.resize(400, 300)

    @classmethod
    def _shim_gdal_polygonize(cls):
        """Run QGIS's ``gdal_polygonize.py`` call under THIS interpreter.

        Same trick as tests/test_distance_raster_review.py: the script's
        shebang may name a Python without osgeo. Only PATH is touched, and
        tearDownClass restores it.
        """
        script = "/usr/bin/gdal_polygonize.py"
        cls._saved_path = os.environ.get("PATH", "")
        cls._shim_dir = ""
        if not os.path.exists(script):
            return
        cls._shim_dir = tempfile.mkdtemp(prefix="archtoolkit_geochem_shim_")
        shim = os.path.join(cls._shim_dir, "gdal_polygonize.py")
        with open(shim, "w", encoding="utf-8") as handle:
            handle.write(f"#!/bin/sh\nexec {sys.executable} {script} \"$@\"\n")
        os.chmod(shim, 0o755)
        os.environ["PATH"] = cls._shim_dir + os.pathsep + cls._saved_path

    @classmethod
    def tearDownClass(cls):
        # PATH only; the QgsApplication stays alive (see test_align_export_qgis).
        os.environ["PATH"] = getattr(cls, "_saved_path", os.environ.get("PATH", ""))
        if getattr(cls, "_shim_dir", ""):
            shutil.rmtree(cls._shim_dir, True)

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="archtoolkit_geochem_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        env = mock.patch.dict(os.environ, {"ARCHTOOLKIT_NO_DIALOG_MEMORY": "1"})
        env.start()
        self.addCleanup(env.stop)
        project = QgsProject.instance()
        saved_home = project.presetHomePath()
        project.setPresetHomePath(self.temp_dir)       # persisted rasters land in the temp dir
        self.addCleanup(project.setPresetHomePath, saved_home)
        self.iface = _FakeIface(self.canvas)
        self._layer_ids = []
        self.addCleanup(self._cleanup_project)

    def _cleanup_project(self):
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        group = root.findGroup(GD.PARENT_GROUP_NAME)
        if group is not None:
            ids = [n.layerId() for n in group.findLayers()]
            root.removeChildNode(group)
            project.removeMapLayers([i for i in ids if project.mapLayer(i) is not None])
        for name in ("ArchToolkit - Other tool",):
            g = root.findGroup(name)
            if g is not None:
                root.removeChildNode(g)
        project.removeMapLayers([i for i in self._layer_ids if project.mapLayer(i) is not None])

    def _register(self, layer):
        self.assertTrue(layer.isValid(), layer.name())
        QgsProject.instance().addMapLayer(layer)
        self._layer_ids.append(layer.id())
        return layer

    # -- fixtures --------------------------------------------------------
    def _rgb_raster(self, name, rgb):
        rgb = np.asarray(rgb, dtype=np.uint8)
        path = os.path.join(self.temp_dir, name)
        ds = gdal.GetDriverByName("GTiff").Create(path, rgb.shape[2], rgb.shape[1], rgb.shape[0], gdal.GDT_Byte)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(5186)
        ds.SetProjection(srs.ExportToWkt())
        ds.SetGeoTransform(self.GT)
        for k in range(rgb.shape[0]):
            ds.GetRasterBand(k + 1).WriteArray(rgb[k])
        if rgb.shape[0] == 4:
            ds.GetRasterBand(4).SetColorInterpretation(gdal.GCI_AlphaBand)
        ds = None
        return self._register(QgsRasterLayer(path, name))

    def _polygon_layer(self, name, rects, fields=None):
        layer = QgsVectorLayer("Polygon?crs=EPSG:5186", name, "memory")
        if fields:
            layer.dataProvider().addAttributes([GD.QgsField(n, t) for n, t in fields])
            layer.updateFields()
        feats = []
        for i, (x0, y0, x1, y1) in enumerate(rects):
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(x0, y0), QgsPointXY(x1, y0), QgsPointXY(x1, y1),
                                                      QgsPointXY(x0, y1), QgsPointXY(x0, y0)]]))
            if fields:
                f.setAttributes([i + 1])
            feats.append(f)
        layer.dataProvider().addFeatures(feats)
        return self._register(layer)

    def _aoi(self):
        return self._polygon_layer("aoi", [(200000, 500000, 200600, 500600)])

    def _bands(self, colours, *, line=False):
        rgb = np.zeros((3, 60, 60), np.uint8)
        step = 60 // len(colours)
        for k, col in enumerate(colours):
            for c in range(3):
                rgb[c, k * step:(k + 1) * step, :] = col[c]
        if line:
            rgb[:, 30, :] = 0
            rgb[:, :, 30] = 0
        return rgb

    def _dialog(self, raster, **opts):
        d = GD.GeoChemPolygonizeDialog(self.iface)
        d.cmbRaster.setLayer(raster)
        d.cmbAoi.setLayer(opts.get("aoi") or self._aoi())
        idx = d.cmbPreset.findData(opts.get("preset", "fe2o3"))
        self.assertGreaterEqual(idx, 0)
        d.cmbPreset.setCurrentIndex(idx)
        d.chkSelectedOnly.setChecked(False)
        d.spinPixelSize.setValue(10.0)
        d.spinExtentBuffer.setValue(0.0)
        d.chkMaskAoi.setChecked(True)
        d.chkLowAsNoData.setChecked(opts.get("low", True))
        d.chkFixMax.setChecked(False)
        d.chkSnapMax.setChecked(False)
        d.chkInpaint.setChecked(opts.get("inpaint", False))
        d.chkSaveRasters.setChecked(True)
        d.chkAddRasters.setChecked(True)
        d.chkMakeClassRaster.setChecked(True)
        d.chkMakePolygons.setChecked(opts.get("polygons", False))
        d.chkDissolve.setChecked(True)
        d.chkDropNoData.setChecked(opts.get("drop_nodata", True))
        zones = opts.get("zones")
        d.chkZonalStats.setChecked(zones is not None)
        if zones is not None:
            d.cmbZoneLayer.setLayer(zones)
        d.chkZoneSelectedOnly.setChecked(False)
        d.chkWeightedCenter.setChecked(False)
        self.addCleanup(d._cleanup_tmp)
        return d

    def _run(self, dialog):
        before = set(QgsProject.instance().mapLayers().keys())
        n0 = len(self.iface.messageBar().messages)
        dialog.run()
        new = [lyr for k, lyr in QgsProject.instance().mapLayers().items() if k not in before]
        res = {"msgs": self.iface.messageBar().messages[n0:], "layers": new}
        for lyr in new:
            if isinstance(lyr, QgsRasterLayer):
                ds = gdal.Open(lyr.source().split("|")[0])
                res["value" if "_value_" in lyr.name() else "class"] = ds.GetRasterBand(1).ReadAsArray()
                ds = None
            elif "구간폴리곤" in lyr.name():
                res["poly"] = lyr
            elif "구역통계" in lyr.name():
                res["zonal"] = lyr
        return res

    # -- 1. re-run must not delete the output group ----------------------
    def test_rerun_after_another_group_is_added_keeps_all_results(self):
        raster = self._rgb_raster("red.tif", self._bands([(230, 0, 0)]))
        d = self._dialog(raster)
        first = self._run(d)
        self.assertIn("value", first)
        root = QgsProject.instance().layerTreeRoot()
        root.insertGroup(0, "ArchToolkit - Other tool")      # what every other ArchToolkit tool does
        second = self._run(d)
        self.assertIn("value", second, "second run's layers were removed from the project")
        group = root.findGroup(GD.PARENT_GROUP_NAME)
        self.assertIsNotNone(group)
        names = [n.name() for n in group.findLayers()]
        self.assertEqual(len(names), 4, names)                # value + class from both runs
        self.assertEqual(root.children()[0].name(), GD.PARENT_GROUP_NAME)

    # -- 2. stop colours start their own class ---------------------------
    def test_exact_stop_colours_land_in_the_class_they_start(self):
        for key in ("fe2o3", "cao"):
            pts = list(GD.PRESETS[key].points)
            rgb = np.array([p.rgb for p in pts], np.uint8)
            out = interp_rgb_to_value(r=rgb[:, 0], g=rgb[:, 1], b=rgb[:, 2], points=pts, max_distance=48.0)
            breaks = GL.points_to_breaks(pts)
            cls = GD._classify_to_bins(values=out, breaks=breaks, nodata_class=0, nodata_value=-9999.0)
            expected = [min(i + 1, len(breaks) - 1) for i in range(len(pts))]
            self.assertEqual(cls.tolist(), expected, key)

    def test_navy_band_is_class_3_1_to_3_5_not_the_excluded_grey_class(self):
        raster = self._rgb_raster("bands.tif", self._bands([(0, 38, 115), (0, 255, 0), (255, 255, 0), (230, 0, 0)]))
        res = self._run(self._dialog(raster, low=True))
        self.assertEqual(sorted(np.unique(res["class"]).tolist()), [2, 5, 7, 10])

    # -- 3 / 8e. inpainting fills only linework, by copying --------------
    def test_inpaint_leaves_white_background_nodata_and_fills_lines_by_copy(self):
        rgb = self._bands([(0, 255, 0), (255, 255, 0)], line=True)     # 4.5 | 7.1 split at row 30
        rgb[:, 45:, :] = 255                                           # white background (no data)
        rgb[:, :, 30] = 0                                              # the vertical line runs into it
        raster = self._rgb_raster("lines.tif", rgb)
        res = self._run(self._dialog(raster, inpaint=True))
        v = res["value"]
        self.assertTrue((v[48:, :25] == -9999.0).all(), "white background was filled with invented values")
        self.assertTrue((v[48:, 30] == -9999.0).all(), "a line inside the white area borrowed data values")
        self.assertTrue((v[:40, 30] != -9999.0).all())
        self.assertEqual(set(np.round(v[v != -9999.0].astype(float), 3).tolist()), {4.5, 7.1},
                         "the fill created a value present on neither side of the line")

    # -- 4. anti-aliased edge over red -----------------------------------
    def test_antialiased_line_over_red_is_filled_not_read_as_high_values(self):
        rgb = np.zeros((3, 60, 60), np.uint8)
        rgb[0] = 230
        rgb[:, :, 30] = 0
        rgb[0, :, 29] = 115
        rgb[0, :, 31] = 115
        raster = self._rgb_raster("halo.tif", rgb)
        res = self._run(self._dialog(raster, inpaint=True))
        v = res["value"]
        self.assertAlmostEqual(float(v[v != -9999.0].mean()), 12.0, places=3)
        self.assertTrue((v != -9999.0).all())

    # -- 5. low range as NoData only with a grey first stop --------------
    def test_custom_legend_without_grey_keeps_its_lowest_class(self):
        pts = [LegendPoint(10.0, (0, 0, 255)), LegendPoint(20.0, (0, 255, 0)),
               LegendPoint(30.0, (255, 255, 0)), LegendPoint(40.0, (255, 0, 0))]
        GD.PRESETS["custom_review2"] = GD.GeoChemPreset(key="custom_review2", label="custom", unit="ppm", points=pts)
        self.addCleanup(GD.PRESETS.pop, "custom_review2", None)
        vals = np.linspace(10, 40, 60)
        rgb = np.round(np.repeat(_colour_for(pts, vals)[:, None, :], 60, axis=1))
        raster = self._rgb_raster("custom.tif", rgb)
        d = self._dialog(raster, preset="fe2o3", low=True)
        d.cmbPreset.addItem("custom", "custom_review2")
        d.cmbPreset.setCurrentIndex(d.cmbPreset.count() - 1)
        res = self._run(d)
        row = res["value"][0]
        self.assertTrue((row[vals < 20] != -9999.0).all(), "lowest class of a custom legend was dropped")
        self.assertTrue(any("회색" in m[1] for m in res["msgs"]))
        # A preset whose first stop IS the grey 'absent' colour still drops it.
        grey = self._rgb_raster("grey.tif", self._bands([(204, 204, 204), (0, 38, 115)]))
        v = self._run(self._dialog(grey, low=True))["value"]
        self.assertTrue((v[:30] == -9999.0).all())
        self.assertTrue(np.allclose(v[30:], 3.1))

    # -- 6. legend image, continuous bar ---------------------------------
    def test_continuous_legend_bar_anchors_match_the_stop_colours(self):
        stops = FE2O3[1:]
        vals = [p.value for p in stops]
        img = QImage(40, 300, QImage.Format.Format_RGB32)
        img.fill(QColor(255, 255, 255))
        for y in range(300):
            pos = 1.0 - (y + 0.5) / 300.0
            c = _colour_for(stops, np.array([np.interp(pos * 9, np.arange(10), vals)]))[:, 0]
            for x in range(5, 35):
                img.setPixelColor(x, y, QColor(int(round(c[0])), int(round(c[1])), int(round(c[2]))))
        path = os.path.join(self.temp_dir, "legend.png")
        self.assertTrue(img.save(path, "PNG"))
        answers = iter([("leg", True), ("%", True), (", ".join(f"{v:g}" for v in vals), True)])

        def _get_item(parent, title, label, items, current=0, editable=False, *a, **k):
            return (items[current], True)                       # accept the defaults / the detected form

        d = GD.GeoChemPolygonizeDialog(self.iface)
        before = set(GD.PRESETS)
        with mock.patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(path, "")), \
                mock.patch.object(QtWidgets.QInputDialog, "getText", side_effect=lambda *a, **k: next(answers)), \
                mock.patch.object(QtWidgets.QInputDialog, "getItem", side_effect=_get_item), \
                mock.patch.object(QtWidgets.QInputDialog, "getDouble", return_value=(0.5, True)):
            d._import_preset_from_legend_image()
        new = [k for k in GD.PRESETS if k not in before]
        self.assertEqual(len(new), 1)
        self.addCleanup(GD.PRESETS.pop, new[0], None)
        got = GD.PRESETS[new[0]].points
        err = max(float(np.linalg.norm(np.subtract(p.rgb, q.rgb))) for p, q in zip(got, stops))
        self.assertLess(err, 10.0, [p.rgb for p in got])

    # -- 8a. NoData polygons when the option is off ----------------------
    def test_nodata_polygons_are_kept_when_not_dropped(self):
        rgb = self._bands([(230, 0, 0)])
        rgb[:, :, 30:] = 255                                        # right half off-legend -> NoData
        raster = self._rgb_raster("half.tif", rgb)
        kept = self._run(self._dialog(raster, polygons=True, drop_nodata=False))
        self.assertIn(0, {int(f["class_id"]) for f in kept["poly"].getFeatures()})
        dropped = self._run(self._dialog(raster, polygons=True, drop_nodata=True))
        self.assertNotIn(0, {int(f["class_id"]) for f in dropped["poly"].getFeatures()})

    # -- 8b. transparent pixels are not a legend mismatch ----------------
    def test_transparent_pixels_do_not_trigger_the_legend_mismatch_warning(self):
        rgb = np.zeros((4, 60, 60), np.uint8)
        rgb[0] = 230
        rgb[3] = 255
        rgb[3, :20] = 0
        rgb[:3, :20] = 0                                            # transparent rows, RGB black
        raster = self._rgb_raster("rgba.tif", rgb)
        res = self._run(self._dialog(raster))
        self.assertFalse([m for m in res["msgs"] if "범례와 맞지 않는 색" in m[1]], res["msgs"])
        self.assertTrue((res["value"][:20] == -9999.0).all())

    # -- 8c. zones outside / partly outside the export rectangle ---------
    def test_zones_outside_the_extent_are_reported_not_dropped(self):
        raster = self._rgb_raster("red.tif", self._bands([(230, 0, 0)]))
        zones = self._polygon_layer("zones", [
            (200100, 500100, 200300, 500300),                       # inside
            (200500, 500100, 200700, 500300),                       # half outside
            (201000, 500100, 201200, 500300),                       # fully outside
        ], fields=[("zid", FT_INT)])
        res = self._run(self._dialog(raster, zones=zones))
        zonal = res["zonal"]
        self.assertTrue(zonal.crs().isValid())
        rows = {int(f["zid"]): f for f in zonal.getFeatures()}
        self.assertEqual(sorted(rows), [1, 2, 3])
        self.assertAlmostEqual(float(rows[1]["ext_pct"]), 100.0, places=3)
        self.assertAlmostEqual(float(rows[2]["ext_pct"]), 50.0, places=3)
        self.assertEqual(int(rows[3]["pix_in"]), 0)
        self.assertEqual(str(rows[3]["burn_rule"]), "outside_extent")
        self.assertTrue(any("분석 범위" in m[1] for m in res["msgs"]))

    # -- 8d. geographic pixel sizes fit the spin box ----------------------
    def test_pixel_size_box_holds_a_geographic_pixel_size(self):
        d = GD.GeoChemPolygonizeDialog(self.iface)
        d.spinPixelSize.setValue(0.0001)
        self.assertAlmostEqual(d.spinPixelSize.value(), 0.0001, places=7)


if __name__ == "__main__":
    unittest.main()
