"""Correctness pins for 거리 래스터 (tools/distance_raster_dialog.py).

Each test reproduces a wrong output or a missing refusal found in review:
- the -maxdist cells gdal_proximity fills with -9999 were never declared as
  NoData, so they read as a distance of -9999 m downstream;
- a reference CRS in feet was accepted and labelled metres;
- a single point or a purely east-west line skipped the overlap check;
- the progress dialog passed a raw int where PyQt6 demands a scoped enum.

The dependency-free CI discovers this module and skips the QGIS part when
PyQGIS is not importable; run it under QGIS' Python to exercise the dialog.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
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

    from processing.core.Processing import Processing
    from tools import distance_raster_dialog
    from tools.distance_raster_dialog import DISTANCE_NODATA, DistanceRasterDialog

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CI
    QGIS_IMPORT_ERROR = exc


_DIALOG_SOURCE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "tools", "distance_raster_dialog.py")


class DistanceRasterSourceTests(unittest.TestCase):
    """Pins that need no QGIS: the dialog source itself."""

    def test_progress_modality_uses_a_scoped_qt_enum(self):
        # PyQt6 raises TypeError for setWindowModality(2); the call sat before
        # the try block and after btnRun.setEnabled(False), so on QGIS 4 every
        # run died with the button left disabled.
        with open(_DIALOG_SOURCE, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIsNone(re.search(r"setWindowModality\(\s*\d", source))
        self.assertIn("setWindowModality(Qt.WindowModality.WindowModal)", source)


class _FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, title, text, level=0, duration=0):
        self.messages.append((str(title), str(text), int(level)))


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


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class DistanceRasterQgisTests(unittest.TestCase):
    # 60 x 60 cells of 10 m: x 200000-200600, y 499400-500000 (EPSG:5186).
    ORIGIN_X = 200000.0
    ORIGIN_Y = 500000.0
    PX = 10.0
    N = 60

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
        if registry.algorithmById("gdal:proximity") is None or registry.algorithmById("gdal:rasterize") is None:
            raise unittest.SkipTest("QGIS GDAL provider is unavailable")
        cls._shim_gdal_proximity()

    @classmethod
    def _shim_gdal_proximity(cls):
        """Make QGIS's ``gdal_proximity.py`` call run under THIS interpreter.

        Same trick as tests/regression/qgis_env.ensure_gdal_shims: on some
        machines /usr/bin/gdal_proximity.py carries a shebang for a Python
        without osgeo bindings, and gdal:proximity then fails identically in
        every run. Only PATH is touched, and tearDownClass restores it.
        """
        script = "/usr/bin/gdal_proximity.py"
        cls._saved_path = os.environ.get("PATH", "")
        if not os.path.exists(script):
            if shutil.which("gdal_proximity.py") is None:
                raise unittest.SkipTest("gdal_proximity.py is not installed")
            return
        cls._shim_dir = tempfile.mkdtemp(prefix="archtoolkit_distance_shim_")
        shim = os.path.join(cls._shim_dir, "gdal_proximity.py")
        with open(shim, "w", encoding="utf-8") as handle:
            handle.write(f"#!/bin/sh\nexec {sys.executable} {script} \"$@\"\n")
        os.chmod(shim, 0o755)
        os.environ["PATH"] = cls._shim_dir + os.pathsep + cls._saved_path

    @classmethod
    def tearDownClass(cls):
        # Restores PATH only. The QgsApplication stays alive: it cannot be
        # re-created in one process after exitQgis(), and any QGIS-gated test
        # discovered later would crash on the dead instance
        # (see tests/test_align_export_qgis.py).
        os.environ["PATH"] = getattr(cls, "_saved_path", os.environ.get("PATH", ""))
        shutil.rmtree(getattr(cls, "_shim_dir", ""), True)

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="archtoolkit_distance_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        # Never let remembered dialog values leak into a scripted run.
        env = mock.patch.dict(os.environ, {"ARCHTOOLKIT_NO_DIALOG_MEMORY": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.iface = _FakeIface()
        self._layer_ids = []
        self._output_files = []
        self.addCleanup(self._drop_layers)

    def _drop_layers(self):
        QgsProject.instance().removeMapLayers(self._layer_ids)
        for path in self._output_files:
            if os.path.exists(path):
                os.remove(path)

    def _register(self, layer):
        self.assertTrue(layer.isValid(), layer.name())
        QgsProject.instance().addMapLayer(layer)
        self._layer_ids.append(layer.id())
        return layer

    # -- fixtures --------------------------------------------------------
    def _write_raster(self, name, epsg, geotransform, size):
        path = os.path.join(self.temp_dir, name)
        dataset = gdal.GetDriverByName("GTiff").Create(path, size, size, 1, gdal.GDT_Float32)
        self.assertIsNotNone(dataset)
        spatial_ref = osr.SpatialReference()
        spatial_ref.ImportFromEPSG(epsg)
        dataset.SetProjection(spatial_ref.ExportToWkt())
        dataset.SetGeoTransform(geotransform)
        band = dataset.GetRasterBand(1)
        band.SetNoDataValue(-9999.0)
        band.Fill(100.0)
        band.FlushCache()
        dataset = None
        return path

    def _reference(self):
        path = self._write_raster("dem.tif", 5186, (self.ORIGIN_X, self.PX, 0.0, self.ORIGIN_Y, 0.0, -self.PX), self.N)
        return self._register(QgsRasterLayer(path, "dem"))

    def _vector(self, kind, name, geometries, crs="EPSG:5186"):
        layer = QgsVectorLayer(f"{kind}?crs={crs}", name, "memory")
        provider = layer.dataProvider()
        features = []
        for geometry in geometries:
            feature = QgsFeature()
            feature.setGeometry(geometry)
            features.append(feature)
        provider.addFeatures(features)
        layer.updateExtents()
        return self._register(layer)

    def _run(self, source, reference, variable, *, max_distance=0.0):
        """Drive the dialog; return (new layers, [(title, text, level)])."""
        self.iface._bar.messages.clear()
        before = set(QgsProject.instance().mapLayers().keys())
        dialog = DistanceRasterDialog(self.iface)
        dialog.cmbSource.setLayer(source)
        dialog.cmbRef.setLayer(reference)
        dialog.chkSelectedOnly.setChecked(False)
        dialog.txtVariable.setText(variable)
        dialog.spinMaxDistance.setValue(max_distance)
        dialog._on_run()
        QtWidgets.QApplication.processEvents()
        dialog.close()
        added = [layer for lid, layer in QgsProject.instance().mapLayers().items() if lid not in before]
        for layer in added:
            self._layer_ids.append(layer.id())
            self._output_files.append(str(layer.source()).split("|", 1)[0])
        return added, list(self.iface._bar.messages)

    @staticmethod
    def _array(layer):
        dataset = gdal.Open(str(layer.source()).split("|", 1)[0])
        band = dataset.GetRasterBand(1)
        array = band.ReadAsArray()
        declared = band.GetNoDataValue()
        dataset = None
        return array, declared

    def _cell_centre(self, col, row):
        return QgsPointXY(self.ORIGIN_X + (col + 0.5) * self.PX, self.ORIGIN_Y - (row + 0.5) * self.PX)

    # -- NoData flag -------------------------------------------------------
    def test_max_distance_cells_are_declared_nodata_and_excluded_from_statistics(self):
        reference = self._reference()
        point = self._vector("Point", "onept", [QgsGeometry.fromPointXY(self._cell_centre(30, 29))])
        added, messages = self._run(point, reference, "md50", max_distance=50.0)
        self.assertEqual(len(added), 1, messages)
        layer = added[0]
        provider = layer.dataProvider()
        self.assertTrue(provider.sourceHasNoDataValue(1))
        self.assertEqual(float(provider.sourceNoDataValue(1)), DISTANCE_NODATA)
        array, declared = self._array(layer)
        self.assertEqual(declared, DISTANCE_NODATA)
        # Cells whose centre lies within 50 m of the target centre: the 81 in a
        # radius-50 disc on a 10 m grid. Everything else is the sentinel.
        self.assertEqual(int((array == DISTANCE_NODATA).sum()), self.N * self.N - 81)
        stats = provider.bandStatistics(1)
        self.assertEqual(int(stats.elementCount), 81)
        self.assertEqual(float(stats.minimumValue), 0.0)
        self.assertAlmostEqual(float(stats.maximumValue), 50.0, places=3)
        self.assertGreaterEqual(float(stats.mean), 0.0)

    def test_unlimited_run_still_declares_nodata(self):
        reference = self._reference()
        point = self._vector("Point", "onept", [QgsGeometry.fromPointXY(self._cell_centre(30, 29))])
        added, messages = self._run(point, reference, "unlimited")
        self.assertEqual(len(added), 1, messages)
        provider = added[0].dataProvider()
        self.assertTrue(provider.sourceHasNoDataValue(1))
        self.assertEqual(float(provider.sourceNoDataValue(1)), DISTANCE_NODATA)
        self.assertEqual(int(provider.bandStatistics(1).elementCount), self.N * self.N)

    def test_output_without_a_single_valid_cell_is_refused(self):
        # A proximity pass that leaves every cell at the sentinel must not be
        # added as a finished predictor. Before the flag was declared this
        # branch could never fire: every cell counted as valid.
        reference = self._reference()
        point = self._vector("Point", "onept", [QgsGeometry.fromPointXY(self._cell_centre(30, 29))])
        real_run = distance_raster_dialog.processing.run

        def all_nodata_run(algorithm, parameters, *args, **kwargs):
            result = real_run(algorithm, parameters, *args, **kwargs)
            if algorithm == "gdal:proximity":
                dataset = gdal.Open(parameters["OUTPUT"], gdal.GA_Update)
                self.assertIsNotNone(dataset, "gdal:proximity produced no output to blank")
                band = dataset.GetRasterBand(1)
                band.Fill(DISTANCE_NODATA)
                band.FlushCache()
                dataset = None
            return result

        with mock.patch.object(distance_raster_dialog.processing, "run", side_effect=all_nodata_run):
            added, messages = self._run(point, reference, "allnd", max_distance=5.0)
        self.assertEqual(added, [], messages)
        errors = [text for title, text, level in messages if level == 2]
        self.assertTrue(any("전부 NoData" in text for text in errors), messages)
        self.assertTrue(any("최대 거리(5 m)" in text for text in errors), messages)
        # The refused raster is scratch and must not linger in the temp folder.
        self.assertEqual(glob.glob(os.path.join(tempfile.gettempdir(), "archt_distance_allnd_*.tif")), [])

    # -- reference CRS units ----------------------------------------------
    def test_reference_in_feet_is_refused(self):
        # EPSG:2229 (NAD83 / California zone 5, US survey feet) is projected,
        # so the geographic check let it through and every value was feet
        # labelled "(거리, m)".
        path = self._write_raster("feet.tif", 2229, (6500000.0, 30.0, 0.0, 1900000.0, 0.0, -30.0), 20)
        reference = self._register(QgsRasterLayer(path, "feet"))
        point = self._vector("Point", "pft", [QgsGeometry.fromPointXY(QgsPointXY(6500315.0, 1899715.0))], crs="EPSG:2229")
        added, messages = self._run(point, reference, "feet")
        self.assertEqual(added, [], messages)
        errors = [text for title, text, level in messages if level == 2]
        self.assertEqual(len(errors), 1, messages)
        self.assertIn("미터가 아닙니다", errors[0])
        self.assertIn("feet", errors[0])
        # The grid label warns before the user even presses run.
        dialog = DistanceRasterDialog(self.iface)
        dialog.cmbRef.setLayer(reference)
        self.assertIn("미터가 아님", dialog.lblGridInfo.text())
        dialog.close()

    def test_reference_in_metres_shows_no_unit_warning(self):
        reference = self._reference()
        dialog = DistanceRasterDialog(self.iface)
        dialog.cmbRef.setLayer(reference)
        self.assertNotIn("[주의]", dialog.lblGridInfo.text())
        dialog.close()

    # -- degenerate extents -------------------------------------------------
    def test_horizontal_line_partly_outside_the_grid_warns(self):
        # A purely east-west line has a zero-height extent; isEmpty() called
        # it empty and the overlap check was skipped, so the dropped eastern
        # half went unmentioned.
        reference = self._reference()
        line = self._vector("LineString", "road", [QgsGeometry.fromPolylineXY([QgsPointXY(200300.0, 499705.0), QgsPointXY(201500.0, 499705.0)])])
        added, messages = self._run(line, reference, "road")
        self.assertEqual(len(added), 1, messages)
        warnings = [text for title, text, level in messages if level == 1]
        self.assertTrue(any("기준 래스터 범위 밖" in text for text in warnings), messages)
        array, _declared = self._array(added[0])
        # Row 29 (y 499700-499710) is burned from column 30 to the east edge.
        self.assertTrue((array[29, 30:] == 0.0).all())
        self.assertFalse((array[29, :30] == 0.0).any())

    def test_single_point_outside_the_grid_reports_no_overlap(self):
        reference = self._reference()
        far = self._vector("Point", "far", [QgsGeometry.fromPointXY(QgsPointXY(300000.0, 600000.0))])
        added, messages = self._run(far, reference, "far")
        self.assertEqual(added, [], messages)
        errors = [text for title, text, level in messages if level == 2]
        self.assertTrue(any("전혀 겹치지 않습니다" in text for text in errors), messages)

    def test_single_point_inside_the_grid_runs_without_a_warning(self):
        reference = self._reference()
        point = self._vector("Point", "onept", [QgsGeometry.fromPointXY(self._cell_centre(5, 5))])
        added, messages = self._run(point, reference, "inside")
        self.assertEqual(len(added), 1, messages)
        self.assertEqual([m for m in messages if m[2] in (1, 2)], [])
        array, _declared = self._array(added[0])
        self.assertEqual(float(array[5, 5]), 0.0)
        self.assertEqual(int((array == 0.0).sum()), 1)


if __name__ == "__main__":
    unittest.main()
