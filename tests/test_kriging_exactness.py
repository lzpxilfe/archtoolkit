"""Ordinary Kriging (Lite) is exact at its samples (DEMGEN-02) and reports its
value source (DEMGEN-07).

``tools.kriging_lite`` imports ``qgis.core`` (and ``osgeo.gdal`` when it
writes), so this module installs minimal stand-ins for both, imports the real
module against them, and restores ``sys.modules`` afterwards. Only numpy is
needed; the test is skipped without it.

The scenario is the one from the audit: 49 spot heights on a 10 m grid, all
0.00 m except a 30.00 m benchmark at (30, 30), kriged onto a 5 m grid whose
cell centres land exactly on the samples. Before the fix the benchmark cell
came back as 25.05 m with a variance of 1.69 m^2; Ordinary Kriging as defined
(Matheron 1963; Cressie 1993) must return 30.00 m with variance 0.
"""

from __future__ import annotations

import importlib
import math
import os
import sys
import tempfile
import types
import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover - dependency-free CI lane
    np = None


# ---------------------------------------------------------------------------
# qgis.core stand-ins (only what kriging_lite / utils touch at import + run)
# ---------------------------------------------------------------------------
class _PointXY:
    def __init__(self, x, y, z=float("nan")):
        self._x, self._y, self._z = float(x), float(y), float(z)

    def x(self):
        return self._x

    def y(self):
        return self._y

    def z(self):
        return self._z


class _Geometry:
    def __init__(self, pt):
        self._pt = pt

    @staticmethod
    def fromPointXY(pt):
        return _Geometry(pt)

    def isEmpty(self):
        return False

    def vertices(self):
        return [self._pt]

    def asPoint(self):
        return self._pt


class _Feature:
    def __init__(self, fid=-1, attrs=None):
        self._id = int(fid)
        self._geom = None
        self._attrs = dict(attrs or {})

    def setId(self, fid):
        self._id = int(fid)

    def id(self):
        return self._id

    def setGeometry(self, geom):
        self._geom = geom

    def geometry(self):
        return self._geom

    def __getitem__(self, name):
        return self._attrs[name]


class _SpatialIndex:
    """Brute-force stand-in for QgsSpatialIndex.nearestNeighbor."""

    def __init__(self):
        self._pts = {}

    def addFeature(self, feat):
        p = feat.geometry().asPoint()
        self._pts[feat.id()] = (p.x(), p.y())

    def nearestNeighbor(self, pt, n):
        order = sorted(
            self._pts.items(),
            key=lambda kv: math.hypot(kv[1][0] - pt.x(), kv[1][1] - pt.y()),
        )
        return [fid for fid, _ in order[:n]]


class _Rectangle:
    def __init__(self, xmin, ymin, xmax, ymax):
        self._b = (float(xmin), float(ymin), float(xmax), float(ymax))

    def xMinimum(self):
        return self._b[0]

    def yMinimum(self):
        return self._b[1]

    def xMaximum(self):
        return self._b[2]

    def yMaximum(self):
        return self._b[3]

    def width(self):
        return self._b[2] - self._b[0]

    def height(self):
        return self._b[3] - self._b[1]


class _Field:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _Fields:
    def __init__(self, names):
        self._names = list(names)

    def indexFromName(self, name):
        return self._names.index(name) if name in self._names else -1

    def lookupField(self, name):
        idx = self.indexFromName(name)
        if idx >= 0:
            return idx
        low = [n.lower() for n in self._names]
        return low.index(name.lower()) if name.lower() in low else -1

    def __getitem__(self, i):
        return _Field(self._names[i])


class _Crs:
    def isGeographic(self):
        return False

    def mapUnits(self):
        return 0  # == QgsUnitTypes.DistanceMeters in the stub

    def toWkt(self):
        return ""


class _Layer:
    def __init__(self, samples, field_names):
        # samples: [(x, y, {field: value}), ...]
        self._samples = list(samples)
        self._field_names = list(field_names)

    def isValid(self):
        return True

    def geometryType(self):
        return 0  # QgsWkbTypes.PointGeometry in the stub

    def fields(self):
        return _Fields(self._field_names)

    def crs(self):
        return _Crs()

    def getFeatures(self):
        for i, (x, y, attrs) in enumerate(self._samples):
            f = _Feature(i, attrs)
            f.setGeometry(_Geometry(_PointXY(x, y)))
            yield f


# ---------------------------------------------------------------------------
# osgeo.gdal stand-in that captures the written arrays instead of files
# ---------------------------------------------------------------------------
class _Band:
    def __init__(self, sink):
        self._sink = sink

    def SetNoDataValue(self, v):
        self._sink["nodata"] = float(v)

    def WriteArray(self, arr):
        self._sink["array"] = np.array(arr, dtype=float)

    def FlushCache(self):
        return None


class _Dataset:
    def __init__(self, sink):
        self._sink = sink

    def SetGeoTransform(self, gt):
        self._sink["geotransform"] = tuple(gt)

    def SetProjection(self, wkt):
        self._sink["projection"] = wkt

    def GetRasterBand(self, _i):
        return _Band(self._sink)

    def FlushCache(self):
        return None


class _Driver:
    def __init__(self):
        self.written = {}

    def Create(self, path, width, height, bands, dtype, options=None):
        sink = {"size": (int(width), int(height))}
        self.written[str(path)] = sink
        return _Dataset(sink)


def _build_stubs(driver):
    core = types.ModuleType("qgis.core")

    class Qgis:
        Info, Warning, Critical = 0, 1, 2

    class QgsMessageLog:
        @staticmethod
        def logMessage(*_a, **_k):
            return None

    class QgsProject:
        @staticmethod
        def instance():
            return None

    class QgsUnitTypes:
        DistanceMeters = 0

    class QgsWkbTypes:
        PointGeometry = 0

    core.Qgis = Qgis
    core.QgsMessageLog = QgsMessageLog
    core.QgsProject = QgsProject
    core.QgsUnitTypes = QgsUnitTypes
    core.QgsCoordinateTransform = type("QgsCoordinateTransform", (), {})
    core.QgsFeature = _Feature
    core.QgsGeometry = _Geometry
    core.QgsPointXY = _PointXY
    core.QgsRectangle = _Rectangle
    core.QgsSpatialIndex = _SpatialIndex
    core.QgsVectorLayer = _Layer
    core.QgsWkbTypes = QgsWkbTypes

    qgis = types.ModuleType("qgis")
    qgis.__path__ = []
    qgis.core = core

    gdal = types.ModuleType("osgeo.gdal")
    gdal.GDT_Float32 = 6
    gdal.GetDriverByName = lambda _name: driver
    osgeo = types.ModuleType("osgeo")
    osgeo.__path__ = []
    osgeo.gdal = gdal
    return {"qgis": qgis, "qgis.core": core, "osgeo": osgeo, "osgeo.gdal": gdal}


_STUB_KEYS = ("qgis", "qgis.core", "osgeo", "osgeo.gdal")
_PLUGIN_KEYS = ("tools.kriging_lite", "tools.utils")


@unittest.skipIf(np is None, "numpy unavailable")
class KrigingExactnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = _Driver()
        cls._saved = {k: sys.modules.get(k) for k in _STUB_KEYS + _PLUGIN_KEYS}
        for key in _PLUGIN_KEYS:
            sys.modules.pop(key, None)
        sys.modules.update(_build_stubs(cls.driver))
        importlib.invalidate_caches()
        cls.kl = importlib.import_module("tools.kriging_lite")

    @classmethod
    def tearDownClass(cls):
        for key in _STUB_KEYS + _PLUGIN_KEYS:
            saved = cls._saved.get(key)
            if saved is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = saved

    # -- fixtures -----------------------------------------------------------
    @staticmethod
    def _benchmark_layer(field="Elevation"):
        samples = []
        for x in range(0, 61, 10):
            for y in range(0, 61, 10):
                z = 30.0 if (x, y) == (30, 30) else 0.0
                samples.append((float(x), float(y), {field: z}))
        return _Layer(samples, [field, "id"]), samples

    def _run(self, layer, value_field, tag):
        tmp = tempfile.mkdtemp(prefix="archtoolkit_krig_")
        out = os.path.join(tmp, f"{tag}.tif")
        var = os.path.join(tmp, f"{tag}_variance.tif")
        info = self.kl.ordinary_kriging_lite_to_geotiff(
            layer=layer,
            value_field=value_field,
            extent=_Rectangle(-2.5, -2.5, 62.5, 62.5),
            pixel_size=5.0,
            out_path=out,
            variance_path=var,
            neighbors=16,
        )
        pred = self.driver.written[out]["array"]
        varr = self.driver.written[var]["array"]
        return info, pred, varr

    # -- tests --------------------------------------------------------------
    def test_benchmark_is_reproduced_with_zero_variance(self):
        layer, _ = self._benchmark_layer()
        info, pred, varr = self._run(layer, "Elevation", "bench")
        self.assertEqual((info["nrows"], info["ncols"]), (13, 13))
        # Cell centres: x = -2.5 + (c + 0.5) * 5 -> (30, 30) is (row 6, col 6).
        self.assertAlmostEqual(float(pred[6, 6]), 30.0, places=5)
        self.assertAlmostEqual(float(varr[6, 6]), 0.0, places=6)

    def test_every_sample_location_is_exact(self):
        layer, samples = self._benchmark_layer()
        _, pred, varr = self._run(layer, "Elevation", "all")
        for x, y, attrs in samples:
            c = int(round((x + 2.5) / 5.0 - 0.5))
            r = int(round((62.5 - y) / 5.0 - 0.5))
            self.assertAlmostEqual(float(pred[r, c]), attrs["Elevation"], places=5, msg=f"({x},{y})")
            self.assertAlmostEqual(float(varr[r, c]), 0.0, places=6, msg=f"({x},{y})")

    def test_between_samples_variance_is_positive(self):
        layer, _ = self._benchmark_layer()
        _, pred, varr = self._run(layer, "Elevation", "mid")
        # (5, 55): midway between four 0 m samples, none coincident, so the
        # prediction is an estimate and its variance must be strictly positive.
        # (No bound check on pred: OK weights may be negative - the screening
        # effect - so a value slightly outside the data range is legitimate.)
        self.assertGreater(float(varr[1, 1]), 0.0)
        self.assertTrue(bool(np.isfinite(pred).all()))
        self.assertTrue(bool((varr >= 0).all()))

    def test_resolved_value_field_is_reported(self):
        layer, _ = self._benchmark_layer("HEIGHT")
        info, _, _ = self._run(layer, None, "auto")
        self.assertEqual(info["params"]["value_field"], "HEIGHT")

        explicit, _, _ = self._run(layer, "HEIGHT", "explicit")
        self.assertEqual(explicit["params"]["value_field"], "HEIGHT")

    def test_resolution_is_case_insensitive_and_honours_geom_sentinel(self):
        layer = _Layer([], ["Height", "id"])
        self.assertEqual(self.kl.resolve_value_field(layer, None), "Height")
        self.assertEqual(self.kl.resolve_value_field(layer, "__geom_z__"), self.kl.GEOM_Z_SENTINEL)
        self.assertEqual(self.kl.resolve_value_field(_Layer([], ["id"]), ""), self.kl.GEOM_Z_SENTINEL)


if __name__ == "__main__":
    unittest.main()
