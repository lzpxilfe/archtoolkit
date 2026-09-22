"""Headless QGIS bootstrap + fake iface + synthetic data for before/after smoke runs.

Usage (from a repo root, with /usr/bin/python3 = QGIS python):
    import sys; sys.path.insert(0, HARNESS_DIR); import qgis_env
    app, iface = qgis_env.boot(repo_root)
"""
from __future__ import annotations

import os
import sys
import math
import stat
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false;qt.qpa.*=false")

_APP = None

# GDAL python utilities QGIS shells out to (gdal_calc.py, gdal_proximity.py, ...).
_GDAL_SCRIPTS = ("gdal_calc.py", "gdal_proximity.py", "gdal_polygonize.py", "gdal_sieve.py",
                 "gdal_fillnodata.py", "gdal_merge.py", "gdal_edit.py", "gdal2xyz.py", "gdal_retile.py")


def ensure_gdal_shims() -> str:
    """Make QGIS's GDAL script calls use THIS interpreter.

    On some machines /usr/bin/gdal_calc.py carries a shebang for a Python that
    has no osgeo bindings, so gdal:rastercalculator / gdal:proximity fail
    identically in every checkout. Wrappers that re-exec the scripts with
    sys.executable are written to a temp dir and prepended to PATH. Harmless
    where the scripts already work. Returns the shim directory.
    """
    shim = os.path.join(tempfile.gettempdir(), "archtoolkit_gdal_shim")
    os.makedirs(shim, exist_ok=True)
    for name in _GDAL_SCRIPTS:
        target = f"/usr/bin/{name}"
        if not os.path.exists(target):
            continue
        path = os.path.join(shim, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"#!/bin/sh\nexec {sys.executable} {target} \"$@\"\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.environ["PATH"] = shim + os.pathsep + os.environ.get("PATH", "")
    return shim


class _FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, *args, **kwargs):
        self.messages.append((args, kwargs))

    def pushWidget(self, *args, **kwargs):
        self.messages.append((args, kwargs))

    def createMessage(self, *args, **kwargs):
        from qgis.PyQt import QtWidgets
        return QtWidgets.QWidget()

    def clearWidgets(self):
        pass


class FakeIface:
    """Just enough of QgisInterface for the ArchToolkit dialogs."""

    def __init__(self, canvas):
        self._canvas = canvas
        self._bar = _FakeMessageBar()
        self._active = None
        from qgis.PyQt.QtCore import QObject, pyqtSignal

        class _Sig(QObject):
            currentLayerChanged = pyqtSignal(object)

        self._sig = _Sig()
        self.currentLayerChanged = self._sig.currentLayerChanged

    def messageBar(self):
        return self._bar

    def mapCanvas(self):
        return self._canvas

    def mainWindow(self):
        from qgis.PyQt import QtWidgets
        if not hasattr(self, "_mw"):
            self._mw = QtWidgets.QMainWindow()
        return self._mw

    # Menu / toolbar registration used by ArchToolkit.initGui and unload.
    def addPluginToMenu(self, name, action):
        self.menus = getattr(self, "menus", {})
        self.menus.setdefault(name, []).append(action)

    def removePluginMenu(self, name, action):
        try:
            self.menus.get(name, []).remove(action)
        except (AttributeError, ValueError):
            pass

    def addToolBar(self, name):
        from qgis.PyQt import QtWidgets
        tb = QtWidgets.QToolBar(name, self.mainWindow())
        self.mainWindow().addToolBar(tb)
        return tb

    def addToolBarIcon(self, action):
        self.toolbar_actions = getattr(self, "toolbar_actions", [])
        self.toolbar_actions.append(action)

    def removeToolBarIcon(self, action):
        try:
            self.toolbar_actions.remove(action)
        except (AttributeError, ValueError):
            pass

    def layerTreeView(self):
        return None

    def activeLayer(self):
        return self._active

    def setActiveLayer(self, layer):
        self._active = layer
        return True

    def addRasterLayer(self, path, name=None, provider="gdal"):
        from qgis.core import QgsProject, QgsRasterLayer
        lyr = QgsRasterLayer(path, name or os.path.basename(path), provider)
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
        return lyr

    def addVectorLayer(self, path, name=None, provider="ogr"):
        from qgis.core import QgsProject, QgsVectorLayer
        lyr = QgsVectorLayer(path, name or os.path.basename(path), provider)
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
        return lyr

    def pushed(self):
        return list(self._bar.messages)


def boot(repo_root: str):
    """Start QgsApplication (once), init Processing, import the plugin package."""
    global _APP
    from qgis.core import QgsApplication
    from qgis.gui import QgsMapCanvas
    if _APP is None:
        QgsApplication.setPrefixPath("/usr", True)
        _APP = QgsApplication([], False)
        _APP.initQgis()
        sys.path.insert(0, "/usr/share/qgis/python/plugins")
        from processing.core.Processing import Processing
        Processing.initialize()
        # The plugin is a package named after its directory; import it as `tools`
        # relative to the repo root (tests do the same).
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
    canvas = QgsMapCanvas()
    canvas.resize(800, 600)
    iface = FakeIface(canvas)
    return _APP, iface


def make_dem(path: str, *, xmin=200000.0, ymax=500000.0, px=10.0, ncols=60, nrows=60, crs_epsg=5186, kind="ridge"):
    """Write a small synthetic DEM GeoTIFF; returns the path."""
    import numpy as np
    from osgeo import gdal, osr
    yy, xx = np.mgrid[0:nrows, 0:ncols].astype(np.float64)
    cx = ncols / 2.0
    if kind == "ridge":
        z = 100.0 + 40.0 * np.exp(-((xx - cx) ** 2) / (2 * (ncols / 6.0) ** 2)) + 0.5 * yy
    elif kind == "plane":
        z = 100.0 + 0.3 * xx + 0.1 * yy
    else:
        z = 100.0 + 25.0 * np.sin(xx / 6.0) * np.cos(yy / 7.0)
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, ncols, nrows, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((xmin, px, 0.0, ymax, 0.0, -px))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(crs_epsg)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    band.WriteArray(z.astype(np.float32))
    band.FlushCache()
    ds = None
    return path


def make_points(name: str, coords, *, crs_epsg=5186, fields=None, attrs=None):
    """Memory point layer. fields: [(name, QVariant.Type)], attrs: list of lists."""
    from qgis.PyQt.QtCore import QVariant
    from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer
    lyr = QgsVectorLayer(f"Point?crs=EPSG:{crs_epsg}", name, "memory")
    pr = lyr.dataProvider()
    flds = [QgsField("name", QVariant.String)] + [QgsField(n, t) for n, t in (fields or [])]
    pr.addAttributes(flds)
    lyr.updateFields()
    feats = []
    for i, (x, y) in enumerate(coords):
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(x), float(y))))
        row = [f"P{i + 1}"] + (list(attrs[i]) if attrs else [])
        f.setAttributes(row)
        feats.append(f)
    pr.addFeatures(feats)
    lyr.updateExtents()
    QgsProject.instance().addMapLayer(lyr)
    return lyr


def make_polygon(name: str, ring, *, crs_epsg=5186, fields=None, attrs=None):
    from qgis.PyQt.QtCore import QVariant
    from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer
    lyr = QgsVectorLayer(f"Polygon?crs=EPSG:{crs_epsg}", name, "memory")
    pr = lyr.dataProvider()
    flds = [QgsField("name", QVariant.String)] + [QgsField(n, t) for n, t in (fields or [])]
    pr.addAttributes(flds)
    lyr.updateFields()
    f = QgsFeature(lyr.fields())
    f.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(float(x), float(y)) for x, y in ring]]))
    f.setAttributes([name] + (list(attrs) if attrs else []))
    pr.addFeatures([f])
    lyr.updateExtents()
    QgsProject.instance().addMapLayer(lyr)
    return lyr


def raster_summary(path: str) -> dict:
    """Stable numeric fingerprint of a raster for before/after diffs."""
    import numpy as np
    from osgeo import gdal
    ds = gdal.Open(path)
    if ds is None:
        return {"error": "cannot open"}
    out = {"size": [ds.RasterXSize, ds.RasterYSize], "bands": ds.RasterCount, "gt": [round(v, 6) for v in ds.GetGeoTransform()]}
    b = ds.GetRasterBand(1)
    nd = b.GetNoDataValue()
    arr = b.ReadAsArray().astype(np.float64)
    m = np.isfinite(arr)
    if nd is not None:
        m &= arr != nd
    vals = arr[m]
    out.update({
        "nodata": nd,
        "valid": int(vals.size),
        "min": (float(vals.min()) if vals.size else None),
        "max": (float(vals.max()) if vals.size else None),
        "mean": (float(vals.mean()) if vals.size else None),
        "sum": (float(vals.sum()) if vals.size else None),
    })
    ds = None
    return out


def layer_summary(layer) -> dict:
    """Fingerprint of a vector layer: count, fields, and per-numeric-field sums."""
    if layer is None:
        return {"error": "none"}
    out = {"name": layer.name(), "count": int(layer.featureCount()), "fields": [f.name() for f in layer.fields()]}
    sums = {}
    for f in layer.featureCount() and layer.getFeatures() or []:
        for fld in layer.fields():
            v = f[fld.name()]
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v is not None:
                try:
                    if math.isfinite(float(v)):
                        sums[fld.name()] = round(sums.get(fld.name(), 0.0) + float(v), 6)
                except Exception:
                    pass
    out["sums"] = sums
    return out
