"""Correctness pins for 지질도 도엽 ZIP (tools/geology_zip_dialog.py) and
지적도 중첩 면적표 (tools/cadastral_overlap_dialog.py), review round 2.

Each test reproduces a wrong output found in review:

Cadastral
- a second run crashed on a dead layer-tree wrapper once the output group was
  no longer the top node, and took the earlier results out of the tree;
- a parcel that overlaps the survey area and also touches it along an edge
  intersects as a GeometryCollection; the polygon layer rejected it and the
  memory provider dropped every later row, while the message counted them;
- a previous result used as input kept its old parcel_m2/in_aoi_m2 values;
- a CRS without an authid produced an output layer with no CRS;
- split mode summed overlapping survey features twice in its headline total.

Geology
- NULL (a QVariant, not None) codes became a class named "NULL", numeric NULLs
  were counted as "숫자 아님", and NULL labels were written as "NULL";
- a sheet without a CRS was merged with its raw coordinates, and the load-time
  warning about it raised AttributeError (no iface on the processor);
- cp949 was forced over a UTF-8 .cpg, and cp949 member names in the ZIP were
  extracted as cp437 mojibake;
- per-layer mode reported codes of OTHER sheets as "narrower than one cell";
- a same-named ZIP deleted the extracted files of a loaded sheet;
- a NoData value equal to a class code erased that class;
- reloading the same ZIP added a duplicate group.

The dependency-free CI discovers this module and skips it when PyQGIS is not
importable; run it under QGIS' Python to exercise the dialogs.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
    from osgeo import gdal, ogr, osr
    from qgis.PyQt import QtWidgets
    from qgis.PyQt.QtCore import Qt
    from qgis.core import (
        NULL,
        QgsApplication,
        QgsCoordinateReferenceSystem,
        QgsFeature,
        QgsField,
        QgsGeometry,
        QgsLayerTreeGroup,
        QgsPointXY,
        QgsProject,
        QgsRasterLayer,
        QgsVectorLayer,
    )

    from processing.core.Processing import Processing
    from tools.qtcompat import FT_INT, FT_STRING
    from tools.cadastral_overlap_dialog import CadastralOverlapDialog
    from tools.geology_zip_dialog import GeologyZipDialog, KigamZipProcessor

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc
    FT_INT = FT_STRING = None  # referenced by class attributes below


class _FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, title, text, level=0, duration=0):
        self.messages.append((str(title), str(text), int(level)))


class _FakeIface:
    """The slice of QgisInterface the two dialogs touch."""

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

    def texts(self):
        return [f"{t} | {m}" for t, m, _lvl in self._bar.messages]


def _rect(x0, y0, x1, y1):
    return QgsGeometry.fromPolygonXY([[QgsPointXY(x0, y0), QgsPointXY(x1, y0), QgsPointXY(x1, y1),
                                       QgsPointXY(x0, y1), QgsPointXY(x0, y0)]])


def _poly_wkt(x0, y0, x1, y1):
    return f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))"


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class _QgisCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        if QgsApplication.instance() is None:
            prefix = os.environ.get("QGIS_PREFIX_PATH", "").strip()
            if prefix:
                QgsApplication.setPrefixPath(prefix, True)
            cls.app = QgsApplication([], True)
            cls.app.initQgis()
        else:
            cls.app = QgsApplication.instance()
        # Never exitQgis(): a QgsApplication cannot be re-created in one process
        # (see tests/test_align_export_qgis.py).
        Processing.initialize()
        if QgsApplication.processingRegistry().algorithmById("gdal:rasterize") is None:
            raise unittest.SkipTest("QGIS GDAL provider is unavailable")

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="archtoolkit_geo_cad_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        env = mock.patch.dict(os.environ, {"ARCHTOOLKIT_NO_DIALOG_MEMORY": "1"})
        env.start()
        self.addCleanup(env.stop)
        QgsProject.instance().clear()
        self.addCleanup(QgsProject.instance().clear)
        self.iface = _FakeIface()

    def _memory(self, kind, name, fields, feats, crs="EPSG:5186", legend=True):
        uri = f"{kind}?crs={crs}" if crs else kind
        layer = QgsVectorLayer(uri, name, "memory")
        if crs is None:
            layer.setCrs(QgsCoordinateReferenceSystem())
        layer.dataProvider().addAttributes([QgsField(n, t) for n, t in fields])
        layer.updateFields()
        out = []
        for geom, attrs in feats:
            f = QgsFeature(layer.fields())
            f.setGeometry(geom)
            f.setAttributes(list(attrs))
            out.append(f)
        layer.dataProvider().addFeatures(out)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer, legend)
        return layer


class CadastralOverlapReview2Tests(_QgisCase):
    F = [("PNU", FT_STRING)]

    def _run(self, cad, aoi, *, split=False):
        before = set(QgsProject.instance().mapLayers().keys())
        self.iface._bar.messages.clear()
        dlg = CadastralOverlapDialog(self.iface)
        dlg.cmbCadastral.setLayer(cad)
        dlg.cmbSurvey.setLayer(aoi)
        dlg.chkCadastralSelected.setChecked(False)
        dlg.chkSurveySelected.setChecked(False)
        dlg.chkSplitBySurveyFeature.setChecked(split)
        dlg.run()
        new = [lyr for lid, lyr in QgsProject.instance().mapLayers().items() if lid not in before]
        return new, self.iface.texts()

    @staticmethod
    def _rows(layer):
        return sorted((str(f["PNU"]), round(f["parcel_m2"], 3), round(f["in_aoi_m2"], 3), round(f["in_aoi_pct"], 3))
                      for f in layer.getFeatures())

    def test_second_run_after_a_layer_was_added_keeps_both_results(self):
        cad = self._memory("Polygon", "cad", self.F, [(_rect(200000, 500000, 200100, 500100), ["P1"])])
        aoi = self._memory("Polygon", "aoi", [("id", FT_STRING)], [(_rect(200050, 500000, 200150, 500100), ["a"])])
        first, _ = self._run(cad, aoi)
        self.assertEqual(len(first), 1)
        # Any layer loaded afterwards lands above the output group.
        self._memory("Polygon", "loaded_later", self.F, [])
        second, msgs = self._run(cad, aoi)  # raised RuntimeError on a deleted group wrapper
        self.assertEqual(len(second), 1, msgs)
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup("ArchToolkit - Cadastral")
        self.assertIsNotNone(group)
        self.assertIs(root.children()[0], group)
        in_tree = {node.layerId() for node in group.findLayers()}
        self.assertEqual(in_tree, {first[0].id(), second[0].id()})

    def test_parcel_touching_a_second_zone_keeps_every_row(self):
        # Zone B is snapped to P1's east edge: P1 ∩ AOI = Polygon(zone A) + LineString.
        cad = self._memory("Polygon", "parcels", self.F, [
            (_rect(200000, 500000, 200100, 500100), ["P1"]),
            (_rect(200100, 500000, 200200, 500100), ["P2"]),
        ])
        aoi = self._memory("Polygon", "survey", [("id", FT_STRING)], [
            (_rect(200020, 500000, 200060, 500100), ["A"]),
            (_rect(200100, 500000, 200150, 500100), ["B"]),
        ])
        new, msgs = self._run(cad, aoi)
        self.assertEqual(len(new), 1, msgs)
        self.assertEqual(self._rows(new[0]), [("P1", 10000.0, 4000.0, 40.0), ("P2", 10000.0, 5000.0, 50.0)])
        self.assertTrue(any("2개 필지" in m and "9,000.00" in m for m in msgs), msgs)

    def test_previous_result_as_input_gets_the_new_values(self):
        cad = self._memory("Polygon", "cad", self.F + [("OWNER", FT_STRING)], [
            (_rect(200000, 500000, 200100, 500100), ["P1", "kim"]),
            (_rect(200100, 500000, 200200, 500100), ["P2", "lee"]),
        ])
        aoi = self._memory("Polygon", "aoi", [("id", FT_STRING)], [(_rect(200050, 500000, 200150, 500100), ["a"])])
        first, _ = self._run(cad, aoi)
        # Kept out of the layer tree so this test does not also hit the group-move bug.
        small = self._memory("Polygon", "aoi_small", [("id", FT_STRING)], [(_rect(200050, 500000, 200075, 500100), ["b"])],
                             legend=False)
        second, msgs = self._run(first[0], small)
        out = second[0]
        self.assertEqual(out.fields().names(), ["PNU", "OWNER", "parcel_m2", "in_aoi_m2", "in_aoi_pct"])
        rows = [f.attributes() for f in out.getFeatures()]
        # The input piece of P1 is the 5000 m2 clip; the new AOI covers half of it.
        self.assertEqual(rows, [["P1", "kim", 5000.0, 2500.0, 50.0]], msgs)

    def test_crs_without_authid_is_kept_on_the_output(self):
        custom = QgsCoordinateReferenceSystem.fromProj(
            "+proj=tmerc +lat_0=38 +lon_0=127.0028902777778 +k=1 +x_0=200000 +y_0=512345 "
            "+ellps=bessel +towgs84=-115.8,474.99,674.11,1.16,-2.31,-1.63,6.43 +units=m +no_defs")
        self.assertTrue(custom.isValid())
        self.assertEqual(custom.authid(), "")
        cad = self._memory("Polygon", "cad", self.F, [(_rect(200000, 500000, 200100, 500100), ["C1"])], crs=None)
        cad.setCrs(custom)
        aoi = self._memory("Polygon", "aoi", [("id", FT_STRING)], [(_rect(200050, 500000, 200150, 500100), ["a"])], crs=None)
        aoi.setCrs(custom)
        new, msgs = self._run(cad, aoi)
        self.assertEqual(len(new), 1, msgs)
        self.assertTrue(new[0].crs().isValid())
        self.assertEqual(new[0].crs(), custom)
        self.assertEqual(self._rows(new[0]), [("C1", 10000.0, 5000.0, 50.0)])

    def test_split_mode_total_counts_overlapping_zones_once(self):
        cad = self._memory("Polygon", "cad", self.F, [
            (_rect(200000, 500000, 200100, 500100), ["P1"]),
            (_rect(200100, 500000, 200200, 500100), ["P2"]),
        ])
        aoi = self._memory("Polygon", "aoi", [("id", FT_STRING)], [
            (_rect(200050, 500000, 200150, 500100), ["a"]),
            (_rect(200080, 500000, 200180, 500100), ["b"]),
        ])
        new, msgs = self._run(cad, aoi, split=True)
        self.assertEqual(len(new), 2, msgs)
        done = [m for m in msgs if m.startswith("지적도 중첩 면적표")]
        self.assertEqual(len(done), 1, msgs)
        # Union of the zones covers 5000 + 8000 m2; the per-zone sum is 20000.
        self.assertIn("포함면적 합 13,000.00 ㎡", done[0])
        self.assertIn("조사지역별 합계 20,000.00 ㎡", done[0])


class GeologyZipReview2Tests(_QgisCase):
    LITHO_FIELDS = [("LITHO", FT_STRING), ("LITHOIDX", FT_INT), ("LITHONAME", FT_STRING)]

    def setUp(self):
        super().setUp()
        self.extract_root = os.path.join(self.temp_dir, "extract")
        patcher = mock.patch.object(KigamZipProcessor, "default_extract_root",
                                    staticmethod(lambda: self.extract_root))
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- fixtures --------------------------------------------------------
    def _write_shp(self, path, epsg, fields, feats, *, encoding="CP949", keep_cpg=False, prj=True):
        """Shapefile whose DBF text is really in `encoding` (QGIS switches OGR
        recoding off process-wide, so SHAPE_ENCODING is set while writing)."""
        old = gdal.GetConfigOption("SHAPE_ENCODING")
        gdal.SetConfigOption("SHAPE_ENCODING", encoding)
        try:
            drv = ogr.GetDriverByName("ESRI Shapefile")
            ds = drv.CreateDataSource(path)
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(epsg)
            layer = ds.CreateLayer(os.path.splitext(os.path.basename(path))[0], srs, ogr.wkbPolygon,
                                   options=[f"ENCODING={encoding}"])
            for name, ftype, width in fields:
                fd = ogr.FieldDefn(name, ftype)
                if width:
                    fd.SetWidth(width)
                layer.CreateField(fd)
            for wkt, attrs in feats:
                feat = ogr.Feature(layer.GetLayerDefn())
                feat.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
                for (name, _t, _w), value in zip(fields, attrs):
                    if value is None:
                        feat.SetFieldNull(name)
                    else:
                        feat.SetField(name, value)
                layer.CreateFeature(feat)
            ds = None
        finally:
            gdal.SetConfigOption("SHAPE_ENCODING", old)
        base = os.path.splitext(path)[0]
        if not keep_cpg and os.path.exists(base + ".cpg"):
            os.remove(base + ".cpg")
        if not prj and os.path.exists(base + ".prj"):
            os.remove(base + ".prj")

    def _zip(self, zip_path, sheet_dir, feats, *, epsg=5186, encoding="CP949", keep_cpg=False, prj=True):
        src = tempfile.mkdtemp(dir=self.temp_dir)
        folder = os.path.join(src, sheet_dir)
        os.makedirs(folder)
        fields = [("LITHOIDX", ogr.OFTInteger, 0), ("LITHO", ogr.OFTString, 20), ("LITHONAME", ogr.OFTString, 60)]
        self._write_shp(os.path.join(folder, "Litho.shp"), epsg, fields, feats,
                        encoding=encoding, keep_cpg=keep_cpg, prj=prj)
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(src):
                for name in files:
                    full = os.path.join(root, name)
                    zf.write(full, os.path.relpath(full, src))
        return zip_path

    SHEET = [
        (_poly_wkt(200000, 499700, 200300, 500000), [5, "Kgr", "흑운모 화강암"]),
        (_poly_wkt(200000, 499400, 200300, 499700), [1, "Qa", "충적층"]),
    ]

    def _load(self, dlg, zip_path):
        dlg.txtZip.setText(zip_path)
        dlg._load_zip()

    def _litho_layers(self):
        return [lyr for lyr in QgsProject.instance().mapLayers().values()
                if isinstance(lyr, QgsVectorLayer) and lyr.name() == "Litho"]

    def _geology_dialog(self, layers, *, nodata=-9999.0):
        dlg = GeologyZipDialog(self.iface)
        dlg.chkKigamOnly.setChecked(False)
        dlg.chkLithoOnly.setChecked(False)
        dlg.refresh_layer_list()
        ids = {lyr.id() for lyr in layers}
        for i in range(dlg.lstLayers.count()):
            item = dlg.lstLayers.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in ids
                               else Qt.CheckState.Unchecked)
        dlg._refresh_field_choices()
        dlg.spinPixel.setValue(10.0)
        dlg.spinNoData.setValue(nodata)
        dlg.cmbFormat.setCurrentIndex(dlg.cmbFormat.findData("tif"))
        return dlg

    def _merge(self, layers, field, name, *, nodata=-9999.0):
        dlg = self._geology_dialog(layers, nodata=nodata)
        dlg.radMerge.setChecked(True)
        dlg.cmbField.setCurrentIndex(dlg.cmbField.findText(field))
        path = os.path.join(self.temp_dir, name)
        dlg.txtOutFile.setText(path)
        self.iface._bar.messages.clear()
        dlg._run_rasterize()
        return path

    @staticmethod
    def _csv(path):
        with open(os.path.splitext(path)[0] + "_mapping.csv", encoding="utf-8-sig") as fh:
            return list(csv.reader(fh))

    @staticmethod
    def _values(path):
        ds = gdal.Open(path)
        band = ds.GetRasterBand(1)
        arr = band.ReadAsArray()
        nd = band.GetNoDataValue()
        ds = None
        values = {}
        for v in arr.ravel().tolist():
            values[int(v)] = values.get(int(v), 0) + 1
        return values, nd

    # -- NULL codes and labels ---------------------------------------------
    def test_null_and_blank_text_codes_are_excluded_not_a_class(self):
        layer = self._memory("Polygon", "Litho_null", self.LITHO_FIELDS, [
            (_rect(200000, 499700, 200300, 500000), ["Kgr", 5, "Granite"]),
            (_rect(200000, 499400, 200300, 499700), [NULL, NULL, NULL]),
            (_rect(200300, 499400, 200600, 499700), ["  ", 7, "Dyke"]),
        ])
        path = self._merge([layer], "LITHO", "null_litho.tif")
        codes = [row[0] for row in self._csv(path)[1:]]
        self.assertEqual(codes, ["Kgr"])  # was ["Kgr", "NULL"], the NULL polygon burned as class 2
        values, nd = self._values(path)
        self.assertEqual(values.get(1), 900)
        self.assertEqual(sorted(k for k in values if k != int(nd)), [1])
        self.assertTrue(any("값 없음(NULL/공백) 2" in m for m in self.iface.texts()), self.iface.texts())

    def test_numeric_null_is_counted_as_null_and_null_labels_stay_blank(self):
        layer = self._memory("Polygon", "Litho_nullidx", self.LITHO_FIELDS, [
            (_rect(200000, 499700, 200300, 500000), ["Kgr", 5, NULL]),
            (_rect(200000, 499400, 200300, 499700), ["Qa", NULL, "Alluvium"]),
        ])
        dlg = self._geology_dialog([layer])
        _m, labels, labels_all, _c = dlg._build_shared_code_mapping([layer], "LITHOIDX", numeric=True)
        self.assertNotEqual(labels.get("5", ""), "NULL")
        self.assertNotIn("NULL", labels_all.get("5", []))
        _lyr, _mapping, labels2, _counts, drops = dlg._build_numeric_merge_layer([layer], "LITHOIDX", numeric=True)
        self.assertEqual(drops["null_value"], 1)
        self.assertEqual(drops["non_numeric"], 0)
        self.assertNotEqual(labels2.get("5", ""), "NULL")

    # -- sheets without a CRS -----------------------------------------------
    def test_merge_refuses_a_sheet_without_crs(self):
        a = self._memory("Polygon", "Litho_A", self.LITHO_FIELDS, [(_rect(200000, 499700, 200300, 500000), ["Kgr", 5, "G"])])
        b = self._memory("Polygon", "Litho_B", self.LITHO_FIELDS, [(_rect(200300, 399700, 200600, 400000), ["Qa", 1, "A"])], crs=None)
        self.assertFalse(b.crs().isValid())
        path = self._merge([a, b], "LITHOIDX", "nocrs.tif")
        self.assertFalse(os.path.exists(path), "a CRS-less sheet was merged with raw coordinates")
        self.assertTrue(any("좌표계" in m and "Litho_B" in m for m in self.iface.texts()), self.iface.texts())
        dlg = self._geology_dialog([a, b])
        merged, _m, _l, _c, drops = dlg._build_numeric_merge_layer([a, b], "LITHOIDX", numeric=True)
        self.assertEqual(drops.get("layer_crs_missing"), 1)
        self.assertEqual(merged.featureCount(), 1)

    def test_load_warns_in_the_message_bar_about_a_sheet_without_prj(self):
        zp = self._zip(os.path.join(self.temp_dir, "zips", "GF09_noprj.zip"), "GF09", self.SHEET, prj=False)
        dlg = GeologyZipDialog(self.iface)
        self._load(dlg, zp)
        self.assertTrue(any(m.startswith("지질도 좌표계") and "Litho.shp" in m for m in self.iface.texts()),
                        self.iface.texts())

    # -- encodings ------------------------------------------------------------
    def test_attribute_encoding_follows_cpg_or_the_dbf_bytes(self):
        utf8 = self._zip(os.path.join(self.temp_dir, "zips", "GF11_utf8.zip"), "GF11", self.SHEET,
                         encoding="UTF-8", keep_cpg=True)
        cp949 = self._zip(os.path.join(self.temp_dir, "zips", "GF12_cp949.zip"), "GF12", self.SHEET, encoding="CP949")
        # Fixture sanity: the second DBF really is cp949 and has no .cpg.
        with zipfile.ZipFile(cp949) as zf:
            names = zf.namelist()
            self.assertFalse(any(n.lower().endswith(".cpg") for n in names))
            dbf = zf.read([n for n in names if n.endswith(".dbf")][0])
        self.assertIn("흑운모 화강암".encode("cp949"), dbf)
        dlg = GeologyZipDialog(self.iface)
        self._load(dlg, utf8)
        self._load(dlg, cp949)
        layers = self._litho_layers()
        self.assertEqual(len(layers), 2)
        for layer in layers:
            names = sorted(str(f["LITHONAME"]) for f in layer.getFeatures())
            self.assertEqual(names, ["충적층", "흑운모 화강암"], layer.source())

    def test_cp949_member_names_are_decoded(self):
        zp = self._zip(os.path.join(self.temp_dir, "zips", "GF13.zip"), "GF13_XXXX", self.SHEET)
        with open(zp, "rb") as fh:
            data = fh.read()
        # Re-spell the folder in cp949 bytes without the UTF-8 flag, as Korean
        # Windows zippers do ("가나" is 4 bytes in cp949, like "XXXX").
        data = data.replace(b"GF13_XXXX", b"GF13_" + "가나".encode("cp949"))
        with open(zp, "wb") as fh:
            fh.write(data)
        dlg = GeologyZipDialog(self.iface)
        self._load(dlg, zp)
        layers = self._litho_layers()
        self.assertEqual(len(layers), 1)
        self.assertIn(os.sep + "GF13_가나" + os.sep, layers[0].source())

    # -- per-layer unburned codes -------------------------------------------------
    def test_per_layer_mode_only_reports_codes_of_that_sheet(self):
        a = self._memory("Polygon", "Litho_A", self.LITHO_FIELDS, [
            (_rect(200000, 499700, 200300, 500000), ["Kgr", 5, "Granite"]),
            (_rect(200000, 499400, 200300, 499700), ["Qa", 1, "Alluvium"]),
        ])
        b = self._memory("Polygon", "Litho_B", self.LITHO_FIELDS, [
            (_rect(200300, 499700, 200600, 500000), ["Jbgr", 12, "Biotite granite"]),
            (_rect(200300, 499400, 200600, 499700), ["Kgr", 5, "Granite"]),
        ])
        dlg = self._geology_dialog([a, b])
        dlg.radPerLayer.setChecked(True)
        dlg.cmbField.setCurrentIndex(dlg.cmbField.findText("LITHOIDX"))
        out_dir = os.path.join(self.temp_dir, "per_layer")
        os.makedirs(out_dir)
        dlg.txtOutDir.setText(out_dir)
        self.iface._bar.messages.clear()
        dlg._run_rasterize()
        texts = self.iface.texts()
        # Every polygon is 30 x 30 cells: nothing is narrower than a cell.
        self.assertFalse(any(m.startswith("래스터에 없는 코드") for m in texts), texts)
        rasters = [lyr for lyr in QgsProject.instance().mapLayers().values() if isinstance(lyr, QgsRasterLayer)]
        self.assertEqual(len(rasters), 2)
        for raster in rasters:
            params = json.loads(raster.customProperty("archtoolkit/params_json") or "{}")
            self.assertEqual(params.get("unburned_codes"), 0, raster.name())

    # -- extraction folders and reloads ------------------------------------------
    def test_same_named_zip_keeps_the_loaded_sheet_files(self):
        first = self._zip(os.path.join(self.temp_dir, "ed2019", "GF10.zip"), "GF10_old", self.SHEET)
        second = self._zip(os.path.join(self.temp_dir, "ed2023", "GF10.zip"), "GF10_new", self.SHEET[:1])
        dlg = GeologyZipDialog(self.iface)
        self._load(dlg, first)
        old = self._litho_layers()[0]
        old_src = old.source().split("|")[0]
        self._load(dlg, second)
        self.assertTrue(os.path.exists(old_src), "loading a same-named ZIP deleted a loaded sheet's files")
        old.reload()
        self.assertEqual(old.featureCount(), 2)
        self.assertEqual(len(self._litho_layers()), 2)

    def test_reloading_the_same_zip_replaces_its_group(self):
        zp = self._zip(os.path.join(self.temp_dir, "zips", "GF14.zip"), "GF14", self.SHEET)
        dlg = GeologyZipDialog(self.iface)
        self._load(dlg, zp)
        self._load(dlg, zp)
        parent = QgsProject.instance().layerTreeRoot().findGroup("ArchToolkit - Geology")
        groups = [c.name() for c in parent.children() if isinstance(c, QgsLayerTreeGroup)]
        self.assertEqual(groups, ["KIGAM_GF14"])
        self.assertEqual(len(self._litho_layers()), 1)
        self.assertTrue(any("교체" in m for m in self.iface.texts()), self.iface.texts())

    # -- NoData --------------------------------------------------------------------
    def test_nodata_equal_to_a_code_moves_off_the_codes(self):
        layer = self._memory("Polygon", "Litho_nd", self.LITHO_FIELDS, [
            (_rect(200000, 499700, 200300, 500000), ["Kgr", 5, "Granite"]),
            (_rect(200000, 499400, 200300, 499700), ["Qa", 1, "Alluvium"]),
        ])
        path = self._merge([layer], "LITHOIDX", "nd1.tif", nodata=1.0)
        values, nd = self._values(path)
        self.assertNotIn(int(nd), (1, 5))
        self.assertEqual(values.get(1), 900)  # was 0: the Alluvium class had become NoData
        self.assertEqual(values.get(5), 900)
        self.assertTrue(any(m.startswith("NoData 값 변경") for m in self.iface.texts()), self.iface.texts())


if __name__ == "__main__":
    unittest.main()
