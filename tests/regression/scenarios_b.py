"""Scenario set B: spatial network, DEM generator / kriging, geology rasterize,
geochem polygonize, distance raster, align/export.

Every scenario is tolerant of widgets/methods that exist in only one checkout
(getattr + skip) and returns numeric fingerprints only.
"""
from __future__ import annotations

import csv
import glob
import json
import math
import os
import re
import time

import numpy as np

_RUNID_RE = re.compile(r"_[0-9a-f]{6,}(?=\b|_|$)")

# GDAL python-script algorithms (gdal:proximity, gdal:polygonize) are made to
# run with this interpreter by qgis_env.ensure_gdal_shims(), called by the runner.


# --------------------------------------------------------------------------- helpers
def _norm(name) -> str:
    return _RUNID_RE.sub("_RUNID", str(name))


def _pump(cond, timeout=60.0):
    from qgis.PyQt.QtCore import QCoreApplication
    t0 = time.time()
    while time.time() - t0 < timeout:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    return bool(cond())


def _layer_ids():
    from qgis.core import QgsProject
    return set(QgsProject.instance().mapLayers().keys())


def _new_layers(before):
    from qgis.core import QgsProject
    return [l for lid, l in QgsProject.instance().mapLayers().items() if lid not in before]


def _src_path(layer):
    return str(layer.source()).split("|", 1)[0]


def _fp_layers(ctx, layers) -> dict:
    """Fingerprint a list of project layers keyed by normalised name."""
    out = {}
    for lyr in layers:
        try:
            if lyr.type() == lyr.VectorLayer:
                s = ctx.env.layer_summary(lyr)
                s["name"] = _norm(lyr.name())
                key = "vec:" + s["name"]
            else:
                s = ctx.env.raster_summary(_src_path(lyr))
                s["name"] = _norm(lyr.name())
                key = "ras:" + s["name"]
        except Exception as exc:  # pragma: no cover
            key = "err:" + _norm(lyr.name())
            s = {"error": f"{type(exc).__name__}: {exc}"}
        base, i = key, 2
        while key in out:
            key = f"{base}#{i}"
            i += 1
        out[key] = s
    return out


def _csv_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.reader(f)]


def _write_raster(path, arr, *, gt, dtype, nodata=None, epsg=5186):
    from osgeo import gdal, osr
    arr = np.asarray(arr)
    bands = 1 if arr.ndim == 2 else int(arr.shape[0])
    rows, cols = (arr.shape if arr.ndim == 2 else arr.shape[1:])
    ds = gdal.GetDriverByName("GTiff").Create(path, int(cols), int(rows), bands, dtype)
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    for b in range(bands):
        band = ds.GetRasterBand(b + 1)
        if nodata is not None:
            band.SetNoDataValue(float(nodata))
        band.WriteArray(arr if arr.ndim == 2 else arr[b])
        band.FlushCache()
    ds = None
    return path


def _memory_layer(kind, name, fields, feats, *, crs_epsg=5186):
    """kind: 'Point'|'LineString'|'Polygon'; feats: [(geometry, [attrs])]."""
    from qgis.core import QgsFeature, QgsField, QgsProject, QgsVectorLayer
    lyr = QgsVectorLayer(f"{kind}?crs=EPSG:{crs_epsg}", name, "memory")
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


def _rect_geom(x0, y0, x1, y1):
    from qgis.core import QgsGeometry, QgsPointXY
    return QgsGeometry.fromPolygonXY([[QgsPointXY(x0, y0), QgsPointXY(x1, y0), QgsPointXY(x1, y1), QgsPointXY(x0, y1), QgsPointXY(x0, y0)]])


def _add_raster(path, name):
    from qgis.core import QgsProject, QgsRasterLayer
    lyr = QgsRasterLayer(path, name, "gdal")
    if lyr.isValid():
        QgsProject.instance().addMapLayer(lyr)
    return lyr


def _set_combo_data(combo, data):
    idx = combo.findData(data)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    return idx


def _set_combo_text_contains(combo, needle):
    for i in range(combo.count()):
        if needle in combo.itemText(i):
            combo.setCurrentIndex(i)
            return i
    return -1


def _check_list_by_layer_id(list_widget, wanted_ids):
    """Tick QListWidget items whose UserRole is a layer id (or a layer object)."""
    from qgis.PyQt.QtCore import Qt
    ticked = []
    for i in range(list_widget.count()):
        it = list_widget.item(i)
        data = it.data(Qt.UserRole)
        lid = data.id() if hasattr(data, "id") and callable(getattr(data, "id")) else str(data or "")
        if not (it.flags() & Qt.ItemIsUserCheckable):
            continue
        if lid in wanted_ids:
            it.setCheckState(Qt.Checked)
            ticked.append(lid)
        else:
            it.setCheckState(Qt.Unchecked)
    return ticked


def _six_points():
    return [(200050, 499950), (200150, 499930), (200300, 499800), (200450, 499700), (200520, 499480), (200120, 499500)]


# ------------------------------------------------------------- spatial network (PPA)
def _network_dialog(ctx):
    from tools.spatial_network_dialog import SpatialNetworkDialog
    return SpatialNetworkDialog(ctx.iface)


def _run_ppa(ctx, pts, *, method, k=2, mutual=False, betweenness=True):
    d = _network_dialog(ctx)
    d.cmbSiteLayer.setLayer(pts)
    _set_combo_data(d.cmbNetworkType, "ppa")
    cmb = getattr(d, "cmbPpaGraph", None)
    if cmb is not None:
        _set_combo_data(cmb, method)
    d.spinPpaK.setValue(int(k))
    d.chkPpaMutualOnly.setChecked(bool(mutual))
    for w, v in (("chkCreateNodeMetrics", True), ("chkCloseness", True), ("chkBetweenness", betweenness)):
        wdg = getattr(d, w, None)
        if wdg is not None:
            wdg.setChecked(v)
    sp = getattr(d, "spinPpaMaxDist", None)
    if sp is not None:
        sp.setValue(0.0)
    before = _layer_ids()
    d.run_analysis()
    _pump(lambda: True, 0.2)
    res = _fp_layers(ctx, _new_layers(before))
    res["_has_cmbPpaGraph"] = cmb is not None
    return res


def scenario_network_ppa(ctx):
    from qgis.PyQt.QtCore import QVariant
    out = {}
    pts = ctx.env.make_points("sites6", _six_points(), fields=[("val", QVariant.Int)], attrs=[[i] for i in range(6)])
    out["knn2"] = _run_ppa(ctx, pts, method="knn", k=2, mutual=False)
    out["knn2_mutual"] = _run_ppa(ctx, pts, method="knn", k=2, mutual=True)
    out["delaunay"] = _run_ppa(ctx, pts, method="delaunay")
    # Two sites at exactly the same coordinate (P6 == P3).
    coords = _six_points()
    coords[5] = coords[2]
    dup = ctx.env.make_points("sites6_dup", coords, fields=[("val", QVariant.Int)], attrs=[[i] for i in range(6)])
    out["dup_delaunay"] = _run_ppa(ctx, dup, method="delaunay")
    out["dup_knn2"] = _run_ppa(ctx, dup, method="knn", k=2)
    return out


# ------------------------------------------------------ spatial network (visibility)
def _run_vis(ctx, pts, dem, *, curvature=None, max_dist=450.0, step=5.0):
    d = _network_dialog(ctx)
    d.cmbSiteLayer.setLayer(pts)
    _set_combo_data(d.cmbNetworkType, "visibility")
    d.cmbDemLayer.setLayer(dem)
    d.spinObsHeight.setValue(1.6)
    d.spinTgtHeight.setValue(0.0)
    d.spinCandidateK.setValue(10)
    d.spinMaxDist.setValue(float(max_dist))
    d.spinSampleStep.setValue(float(step))
    d.chkVisAllPairs.setChecked(True)
    d.chkPolyBoundaryVis.setChecked(False)
    for w, v in (("chkCreateNodeMetrics", True), ("chkCloseness", True), ("chkBetweenness", True)):
        wdg = getattr(d, w, None)
        if wdg is not None:
            wdg.setChecked(v)
    rule = getattr(d, "cmbVisEdgeRule", None)
    if rule is not None:
        _set_combo_data(rule, "mutual")
    chk = getattr(d, "chkVisCurvature", None)
    if curvature is not None and chk is not None:
        chk.setChecked(bool(curvature))
    before = _layer_ids()
    d.run_analysis()
    _pump(lambda: True, 0.2)
    res = _fp_layers(ctx, _new_layers(before))
    res["_has_chkVisCurvature"] = chk is not None
    res["_curvature_checked"] = bool(chk.isChecked()) if chk is not None else None
    return res


def scenario_network_visibility(ctx):
    from qgis.PyQt.QtCore import QVariant
    dem_path = ctx.env.make_dem(os.path.join(ctx.tmp, "dem.tif"), kind="ridge")
    dem = _add_raster(dem_path, "dem")
    pts = ctx.env.make_points("sites6", _six_points(), fields=[("val", QVariant.Int)], attrs=[[i] for i in range(6)])
    out = {}
    out["default"] = _run_vis(ctx, pts, dem)              # NEW: curvature on by default
    out["flat"] = _run_vis(ctx, pts, dem, curvature=False)  # NEW: flat; OLD: same as default (no widget)
    out["either_rule_nomax"] = {}
    try:
        d = _network_dialog(ctx)
        d.cmbSiteLayer.setLayer(pts)
        _set_combo_data(d.cmbNetworkType, "visibility")
        d.cmbDemLayer.setLayer(dem)
        d.spinObsHeight.setValue(1.6)
        d.spinTgtHeight.setValue(1.6)
        d.spinMaxDist.setValue(0.0)
        d.spinSampleStep.setValue(0.0)
        d.chkVisAllPairs.setChecked(True)
        rule = getattr(d, "cmbVisEdgeRule", None)
        if rule is not None:
            _set_combo_data(rule, "either")
        before = _layer_ids()
        d.run_analysis()
        out["either_rule_nomax"] = _fp_layers(ctx, _new_layers(before))
    except Exception as exc:
        out["either_rule_nomax"] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


# ---------------------------------------------------------------- DEM generator
def _grid_points(name, field, *, x0=200000.0, y0=500000.0, n=5, spacing=50.0):
    from qgis.PyQt.QtCore import QVariant
    coords, attrs = [], []
    for j in range(n):
        for i in range(n):
            x = x0 + i * spacing
            y = y0 - j * spacing
            coords.append((x, y))
            attrs.append([100.0 + 0.2 * (x - x0) + 0.1 * (y0 - y) + 5.0 * math.sin(i) * math.cos(j)])
    from qgis_env import make_points
    return make_points(name, coords, fields=[(field, QVariant.Double)], attrs=attrs)


def _run_dem(ctx, layer, *, method_needle, out_name, px=10.0, z_choice=None):
    from tools.dem_generator_dialog import DemGeneratorDialog
    d = DemGeneratorDialog(ctx.iface)
    ticked = _check_list_by_layer_id(d.listLayers, {layer.id()})
    _set_combo_text_contains(d.cmbInterpolation, method_needle)
    cmb = getattr(d, "cmbZField", None)
    z_set = None
    if z_choice is not None and cmb is not None:
        z_set = _set_combo_data(cmb, z_choice)
    d.spinPixelSize.setValue(float(px))
    out_path = os.path.join(ctx.tmp, out_name)
    d.fileOutput.setFilePath(out_path)
    before = _layer_ids()
    d.run_process()
    _pump(lambda: os.path.exists(out_path), 30.0)
    res = {"ticked": len(ticked), "method": d.cmbInterpolation.currentText(), "z_combo_idx": z_set,
           "exists": os.path.exists(out_path)}
    if os.path.exists(out_path):
        res["dem"] = ctx.env.raster_summary(out_path)
    base, ext = os.path.splitext(out_path)
    var = f"{base}_variance{ext}"
    if os.path.exists(var):
        res["variance"] = ctx.env.raster_summary(var)
    res["layers_added"] = sorted(_norm(lyr_.name()) for lyr_ in _new_layers(before))
    return res


def scenario_dem_generator(ctx):
    out = {}
    elev = _grid_points("pts_ELEV", "ELEV")            # 2D points, attribute ELEV
    elevation = _grid_points("pts_Elevation", "Elevation")
    out["tin_ELEV_px10"] = _run_dem(ctx, elev, method_needle="TIN - Linear", out_name="tin_elev.tif", px=10)
    out["idw_ELEV_px10"] = _run_dem(ctx, elev, method_needle="IDW", out_name="idw_elev.tif", px=10)
    out["krig_ELEV_px10"] = _run_dem(ctx, elev, method_needle="Kriging", out_name="krig_elev.tif", px=10)
    out["tin_Elevation_px10"] = _run_dem(ctx, elevation, method_needle="TIN - Linear", out_name="tin_elevation.tif", px=10)
    out["tin_Elevation_px6"] = _run_dem(ctx, elevation, method_needle="TIN - Linear", out_name="tin_elevation6.tif", px=6)
    out["idw_Elevation_px10"] = _run_dem(ctx, elevation, method_needle="IDW", out_name="idw_elevation.tif", px=10)
    out["krig_Elevation_px10"] = _run_dem(ctx, elevation, method_needle="Kriging", out_name="krig_elevation.tif", px=10)
    out["krig_Elevation_px10_explicit"] = _run_dem(ctx, elevation, method_needle="Kriging", out_name="krig_elevation_x.tif", px=10, z_choice="Elevation")
    return out


def scenario_kriging_direct(ctx):
    from qgis.PyQt.QtCore import QVariant
    from qgis.core import QgsRectangle
    from osgeo import gdal
    from tools.kriging_lite import ordinary_kriging_lite_to_geotiff
    # 7x7 grid, 30 m spacing, sample points ON 10 m cell centres; one 30 m benchmark.
    coords, attrs = [], []
    bench = (200095.0, 499905.0)
    for j in range(7):
        for i in range(7):
            x = 200005.0 + 30.0 * i
            y = 499995.0 - 30.0 * j
            z = 25.0 + 0.005 * (x - 200005.0) - 0.003 * (499995.0 - y)
            if (x, y) == bench:
                z = 30.0
            coords.append((x, y))
            attrs.append([z])
    lyr = ctx.env.make_points("bench49", coords, fields=[("ELEV", QVariant.Double)], attrs=attrs)
    out_path = os.path.join(ctx.tmp, "krig_direct.tif")
    var_path = os.path.join(ctx.tmp, "krig_direct_var.tif")
    info = ordinary_kriging_lite_to_geotiff(
        layer=lyr, value_field="ELEV", extent=QgsRectangle(200000.0, 499800.0, 200200.0, 500000.0),
        pixel_size=10.0, out_path=out_path, variance_path=var_path, neighbors=16,
    )
    res = {"dem": ctx.env.raster_summary(out_path), "variance": ctx.env.raster_summary(var_path)}
    res["n_points"] = info.get("n_points")
    res["ncols"] = info.get("ncols")
    res["nrows"] = info.get("nrows")
    params = dict(info.get("params") or {})
    res["params_numeric"] = {k: v for k, v in params.items() if isinstance(v, (int, float))}
    res["params_value_field"] = params.get("value_field")
    ds = gdal.Open(out_path)
    arr = ds.GetRasterBand(1).ReadAsArray().astype(float)
    gt = ds.GetGeoTransform()
    col = int((bench[0] - gt[0]) / gt[1])
    row = int((bench[1] - gt[3]) / gt[5])
    res["bench_cell"] = [row, col]
    res["bench_value"] = float(arr[row, col])
    res["bench_neighbours_mean"] = float(np.mean([arr[row - 1, col], arr[row + 1, col], arr[row, col - 1], arr[row, col + 1]]))
    vds = gdal.Open(var_path)
    varr = vds.GetRasterBand(1).ReadAsArray().astype(float)
    res["bench_variance"] = float(varr[row, col])
    res["variance_min"] = float(np.nanmin(varr))
    ds = None
    vds = None
    return res


# ------------------------------------------------------------- geology rasterize
def _geology_layers():
    from qgis.PyQt.QtCore import QVariant
    fields = [("LITHO", QVariant.String), ("LITHOIDX", QVariant.Int), ("LITHONAME", QVariant.String)]
    a = _memory_layer("Polygon", "Litho_sheetA", fields, [
        (_rect_geom(200000, 499700, 200300, 500000), ["Kgr", 5, "Granite"]),
        (_rect_geom(200000, 499400, 200300, 499700), ["Qa", 1, "Alluvium"]),
    ])
    b = _memory_layer("Polygon", "Litho_sheetB", fields, [
        (_rect_geom(200300, 499700, 200600, 499850), ["Jbgr", 12, "Biotite granite"]),
        (_rect_geom(200300, 499400, 200600, 499700), ["Kgr", 5, "Granite"]),
        (_rect_geom(200596, 499400, 200599, 500000), ["Kd", 7, "Dyke"]),   # 3 m sliver: no cell centre
    ])
    return a, b


def _geology_dialog(ctx, layers):
    from tools.geology_zip_dialog import GeologyZipDialog
    d = GeologyZipDialog(ctx.iface)
    d.chkKigamOnly.setChecked(False)
    d.chkLithoOnly.setChecked(False)
    d.refresh_layer_list()
    ticked = _check_list_by_layer_id(d.lstLayers, {lyr_.id() for lyr_ in layers})
    d._refresh_field_choices()
    d.spinPixel.setValue(10.0)
    d.spinNoData.setValue(-9999.0)
    _set_combo_data(d.cmbFormat, "tif")
    return d, ticked


def _fp_geology_output(ctx, tif_path):
    res = {}
    if os.path.exists(tif_path):
        res["raster"] = ctx.env.raster_summary(tif_path)
        from osgeo import gdal
        ds = gdal.Open(tif_path)
        band = ds.GetRasterBand(1)
        arr = band.ReadAsArray()
        nd = band.GetNoDataValue()
        vals, counts = np.unique(arr, return_counts=True)
        res["value_counts"] = {str(int(v)): int(c) for v, c in zip(vals, counts)}
        res["dtype"] = gdal.GetDataTypeName(band.DataType)
        res["nodata_declared"] = nd
        ds = None
    csvp = os.path.splitext(tif_path)[0] + "_mapping.csv"
    if os.path.exists(csvp):
        rows = _csv_rows(csvp)
        res["csv_header"] = rows[0] if rows else []
        res["csv_rows"] = rows[1:]
    return res


def scenario_geology_rasterize(ctx):
    out = {}
    a, b = _geology_layers()

    # 1) merge mode, text code field
    d, ticked = _geology_dialog(ctx, [a, b])
    d.radMerge.setChecked(True)
    idx = d.cmbField.findText("LITHO")
    d.cmbField.setCurrentIndex(idx)
    p1 = os.path.join(ctx.tmp, "geo_litho.tif")
    d.txtOutFile.setText(p1)
    before = _layer_ids()
    d._run_rasterize()
    out["merge_LITHO"] = _fp_geology_output(ctx, p1)
    out["merge_LITHO"]["ticked"] = len(ticked)
    out["merge_LITHO"]["field_idx"] = idx
    out["merge_LITHO"]["layers_added"] = sorted(_norm(lyr_.name()) for lyr_ in _new_layers(before))

    # 2) merge mode, integer code field (labels via LITHONAME)
    d, _ = _geology_dialog(ctx, [a, b])
    d.radMerge.setChecked(True)
    d.cmbField.setCurrentIndex(d.cmbField.findText("LITHOIDX"))
    p2 = os.path.join(ctx.tmp, "geo_idx.tif")
    d.txtOutFile.setText(p2)
    d._run_rasterize()
    out["merge_LITHOIDX"] = _fp_geology_output(ctx, p2)

    # 3) per-layer mode, auto field
    d, _ = _geology_dialog(ctx, [a, b])
    d.radPerLayer.setChecked(True)
    d.cmbField.setCurrentIndex(0)
    pdir = os.path.join(ctx.tmp, "perlayer")
    os.makedirs(pdir, exist_ok=True)
    d.txtOutDir.setText(pdir)
    d._run_rasterize()
    per = {}
    for tif in sorted(glob.glob(os.path.join(pdir, "*.tif"))):
        per[os.path.basename(tif)] = _fp_geology_output(ctx, tif)
    out["per_layer"] = per

    # 4) helpers called directly (signatures differ between checkouts)
    direct = {}
    try:
        d, _ = _geology_dialog(ctx, [a, b])
        res = d._build_numeric_merge_layer([a, b], "LITHO")
        direct["merge_tuple_len"] = len(res)
        merged = res[0]
        direct["merged_summary"] = ctx.env.layer_summary(merged) if merged is not None else None
        direct["mapping"] = {str(k): int(v) for k, v in (res[1] or {}).items()}
        direct["labels"] = {str(k): str(v) for k, v in (res[2] or {}).items()}
        direct["counts"] = {str(k): int(v) for k, v in (res[3] or {}).items()}
        if len(res) > 4:
            direct["drops"] = {str(k): int(v) for k, v in (res[4] or {}).items()}
        shared = getattr(d, "_build_shared_code_mapping", None)
        if shared is not None:
            m, lab, lab_all, conf = shared([a, b], "LITHO")
            direct["shared_mapping_LITHO"] = {str(k): int(v) for k, v in m.items()}
            m2, lab2, lab_all2, conf2 = shared([a, b], "LITHOIDX")
            direct["shared_mapping_LITHOIDX"] = {str(k): int(v) for k, v in m2.items()}
            direct["shared_labels_LITHOIDX"] = {str(k): str(v) for k, v in lab2.items()}
            direct["shared_conflicts_LITHOIDX"] = [[c, list(ls)] for c, ls in conf2]
        else:
            direct["shared_mapping_LITHO"] = "absent"
    except Exception as exc:
        direct["error"] = f"{type(exc).__name__}: {exc}"
    out["direct"] = direct
    return out


# ------------------------------------------------------------- geochem polygonize
def _geochem_rgb(path):
    rows = 60
    cols = 60
    rgb = np.zeros((3, rows, cols), dtype=np.uint8)
    bands = [(0, 38, 115), (0, 255, 0), (255, 255, 0), (230, 0, 0)]
    for k, (r, g, b) in enumerate(bands):
        sl = slice(k * 15, (k + 1) * 15)
        rgb[0, sl, :] = r
        rgb[1, sl, :] = g
        rgb[2, sl, :] = b
    rgb[:, 30, :] = 0     # black horizontal 1-px line
    rgb[:, :, 30] = 0     # black vertical 1-px line
    from osgeo import gdal
    return _write_raster(path, rgb, gt=(200000.0, 10.0, 0.0, 500000.0, 0.0, -10.0), dtype=gdal.GDT_Byte)


def _geochem_dialog(ctx, rgb, aoi, zones, *, inpaint, full):
    from tools.geochem_polygonize_dialog import GeoChemPolygonizeDialog
    d = GeoChemPolygonizeDialog(ctx.iface)
    d.cmbRaster.setLayer(rgb)
    d.cmbAoi.setLayer(aoi)
    _set_combo_data(d.cmbPreset, "fe2o3")
    d.chkSelectedOnly.setChecked(False)
    d.spinPixelSize.setValue(10.0)
    d.spinExtentBuffer.setValue(0.0)
    d.chkMaskAoi.setChecked(True)
    d.chkLowAsNoData.setChecked(False)
    d.chkFixMax.setChecked(False)
    d.chkSnapMax.setChecked(False)
    d.chkInpaint.setChecked(bool(inpaint))
    d.chkSaveRasters.setChecked(True)
    d.chkAddRasters.setChecked(True)
    d.chkMakeClassRaster.setChecked(True)
    d.chkMakePolygons.setChecked(bool(full))
    d.chkDissolve.setChecked(True)
    d.chkDropNoData.setChecked(True)
    d.chkZonalStats.setChecked(bool(full))
    if full:
        d.cmbZoneLayer.setLayer(zones)
    d.chkZoneSelectedOnly.setChecked(False)
    d.chkWeightedCenter.setChecked(bool(full))
    return d


def scenario_geochem_polygonize(ctx):
    from qgis.PyQt.QtCore import QVariant
    rgb_path = _geochem_rgb(os.path.join(ctx.tmp, "fe2o3_rgb.tif"))
    rgb = _add_raster(rgb_path, "fe2o3_wms_clone")
    aoi = ctx.env.make_polygon("aoi", [(200050, 499950), (200550, 499950), (200550, 499450), (200050, 499450)])
    zones = _memory_layer("Polygon", "zones", [("zid", QVariant.Int)], [
        (_rect_geom(200055, 499705, 200295, 499945), [1]),
        (_rect_geom(200305, 499455, 200545, 499695), [2]),
    ])
    out = {}
    for label, inpaint, full in (("full_inpaint", True, True), ("rasters_noinpaint", False, False)):
        try:
            d = _geochem_dialog(ctx, rgb, aoi, zones, inpaint=inpaint, full=full)
            before = _layer_ids()
            d.run()
            _pump(lambda: True, 0.3)
            fp = _fp_layers(ctx, _new_layers(before))
            # Also fingerprint the persisted value/class GeoTIFFs by their file.
            for lyr in _new_layers(before):
                if lyr.type() != lyr.VectorLayer:
                    p = _src_path(lyr)
                    from osgeo import gdal
                    ds = gdal.Open(p)
                    if ds is not None:
                        arr = ds.GetRasterBand(1).ReadAsArray()
                        vals, counts = np.unique(arr, return_counts=True)
                        hist = {str(round(float(v), 3)): int(c) for v, c in zip(vals, counts)}
                        fp["hist:" + _norm(lyr.name())] = hist if len(hist) <= 40 else {"distinct": len(hist)}
                        ds = None
            zonal = [lyr_ for lyr_ in _new_layers(before) if lyr_.type() == lyr_.VectorLayer and "구역통계" in lyr_.name()]
            if zonal:
                rows = []
                for f in zonal[0].getFeatures():
                    rows.append({fld.name(): (round(float(f[fld.name()]), 4) if isinstance(f[fld.name()], (int, float)) else str(f[fld.name()])) for fld in zonal[0].fields()})
                fp["zonal_rows"] = rows
            out[label] = fp
        except Exception as exc:
            out[label] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


# ------------------------------------------------------------- distance raster
def _run_distance(ctx, source, dem, var):
    from tools.distance_raster_dialog import DistanceRasterDialog
    d = DistanceRasterDialog(ctx.iface)
    d.cmbSource.setLayer(source)
    d.cmbRef.setLayer(dem)
    d.chkSelectedOnly.setChecked(False)
    d.txtVariable.setText(var)
    d.spinMaxDistance.setValue(0.0)
    before = _layer_ids()
    d._on_run()
    _pump(lambda: True, 0.3)
    new = _new_layers(before)
    res = _fp_layers(ctx, new)
    res["_added"] = len(new)
    return res


def scenario_distance_raster(ctx):
    from qgis.core import QgsGeometry, QgsPointXY
    from qgis.PyQt.QtCore import QVariant
    dem_path = ctx.env.make_dem(os.path.join(ctx.tmp, "dem.tif"), kind="ridge")
    dem = _add_raster(dem_path, "dem")
    lines = _memory_layer("LineString", "rivers", [("nm", QVariant.String)], [
        (QgsGeometry.fromPolylineXY([QgsPointXY(200050, 499950), QgsPointXY(200550, 499650)]), ["a"]),
        (QgsGeometry.fromPolylineXY([QgsPointXY(200100, 499450), QgsPointXY(200500, 499500)]), ["b"]),
    ])
    strip = _memory_layer("Polygon", "strip5m", [("nm", QVariant.String)], [
        (_rect_geom(200397, 499420, 200402, 499980), ["s"]),   # 5 m wide, misses every 10 m cell centre
    ])
    strip_on = _memory_layer("Polygon", "strip5m_oncentre", [("nm", QVariant.String)], [
        (_rect_geom(200402.5, 499420, 200407.5, 499980), ["s"]),   # 5 m wide, contains centre x=200405
    ])
    from qgis_env import make_points
    pts = make_points("sites6", _six_points())
    out = {}
    out["lines"] = _run_distance(ctx, lines, dem, "river")
    out["strip_offcentre"] = _run_distance(ctx, strip, dem, "strip")
    out["strip_oncentre"] = _run_distance(ctx, strip_on, dem, "strip2")
    out["points"] = _run_distance(ctx, pts, dem, "site")
    return out


# ------------------------------------------------------------- align / export
def scenario_align_export(ctx):
    from osgeo import gdal
    from tools.utils import set_archtoolkit_layer_metadata
    dem_path = ctx.env.make_dem(os.path.join(ctx.tmp, "dem.tif"), kind="ridge")
    dem = _add_raster(dem_path, "dem")
    # Sources on a DIFFERENT grid (15 m, origin shifted by 5 m) so resampling matters.
    n = 40
    gt = (200005.0, 15.0, 0.0, 499995.0, 0.0, -15.0)
    jj, ii = np.mgrid[0:n, 0:n].astype(np.float64)
    slope = (45.0 * np.exp(-((ii - 20) ** 2 + (jj - 20) ** 2) / 200.0)).astype(np.float32)
    aspect = ((ii * 9.0 + jj * 3.0) % 360.0).astype(np.float32)
    classes = (((ii // 8) + (jj // 8)) % 5 + 1).astype(np.uint8)
    p_slope = _write_raster(os.path.join(ctx.tmp, "slope15.tif"), slope, gt=gt, dtype=gdal.GDT_Float32, nodata=-9999.0)
    p_aspect = _write_raster(os.path.join(ctx.tmp, "aspect15.tif"), aspect, gt=gt, dtype=gdal.GDT_Float32, nodata=-9999.0)
    p_cls_meta = _write_raster(os.path.join(ctx.tmp, "class_meta15.tif"), classes, gt=gt, dtype=gdal.GDT_Byte, nodata=0)
    p_cls_nometa = _write_raster(os.path.join(ctx.tmp, "class_nometa15.tif"), classes, gt=gt, dtype=gdal.GDT_Byte, nodata=0)
    l_slope = _add_raster(p_slope, "slope_deg")
    l_aspect = _add_raster(p_aspect, "aspect_deg")
    l_cls = _add_raster(p_cls_meta, "geology_classes")
    l_nometa = _add_raster(p_cls_nometa, "class_nometa")
    set_archtoolkit_layer_metadata(l_slope, tool_id="terrain_analysis", run_id="t1", kind="slope", units="degree", params={})
    set_archtoolkit_layer_metadata(l_aspect, tool_id="terrain_analysis", run_id="t1", kind="aspect", units="degree", params={})
    set_archtoolkit_layer_metadata(l_cls, tool_id="kigam_raster", run_id="g1", kind="geology_class", units="class", params={})

    from tools.align_export_dialog import AlignExportDialog
    d = AlignExportDialog(ctx.iface)
    d.cmbRef.setLayer(dem)
    try:
        d.cmbAoi.setLayer(None)
    except Exception:
        pass
    d.spinPixel.setValue(0.0)
    ticked = _check_list_by_layer_id(d.listLayers, {l_slope.id(), l_aspect.id(), l_cls.id(), l_nometa.id()})
    d.chkAddToProject.setChecked(True)
    export_dir = os.path.join(ctx.tmp, "export")
    d.txtExport.setText(export_dir)
    before = _layer_ids()
    d._on_run()
    _pump(lambda: bool(glob.glob(os.path.join(export_dir, "aligned_stack_*", "aligned_stack_manifest.csv"))), 60.0)
    out = {"ticked": len(ticked)}
    dirs = sorted(glob.glob(os.path.join(export_dir, "aligned_stack_*")))
    out["n_stack_dirs"] = len(dirs)
    if dirs:
        sd = dirs[-1]
        files = {}
        for tif in sorted(glob.glob(os.path.join(sd, "*.tif"))):
            s = ctx.env.raster_summary(tif)
            ds = gdal.Open(tif)
            s["dtype"] = gdal.GetDataTypeName(ds.GetRasterBand(1).DataType)
            arr = ds.GetRasterBand(1).ReadAsArray()
            s["distinct"] = int(len(np.unique(arr)))
            ds = None
            files[os.path.basename(tif)] = s
        out["files"] = files
        man = os.path.join(sd, "aligned_stack_manifest.csv")
        if os.path.exists(man):
            rows = _csv_rows(man)
            out["manifest_header"] = rows[0]
            out["manifest_rows"] = rows[1:]
        cat = os.path.join(sd, "CATEGORICAL_PREDICTORS.txt")
        if os.path.exists(cat):
            out["categorical_txt"] = open(cat, encoding="utf-8").read().strip()
        gj = os.path.join(sd, "aligned_stack_grid.json")
        if os.path.exists(gj):
            g = json.load(open(gj, encoding="utf-8"))
            g.pop("run_id", None)
            g.pop("note", None)
            out["grid"] = g
    out["layers_added"] = _fp_layers(ctx, _new_layers(before))
    return out
