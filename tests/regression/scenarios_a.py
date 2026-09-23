"""Scenarios A: terrain analysis, viewshed, cost surface, cost network, contours,
terrain profile, map styling.

Every scenario builds its own synthetic DEM (60x60, EPSG:5186, 10 m px) under
ctx.tmp, drives one dialog headlessly and returns numeric fingerprints keyed by
the ArchToolkit `kind` metadata of each output layer (stable across OLD/NEW
even when the display name changed) with the layer name stored alongside.
Widget access is tolerant: anything missing is skipped and recorded in
"skipped_widgets".
"""
from __future__ import annotations

import importlib
import os
import time

DEM_XMIN, DEM_YMAX, DEM_PX, DEM_N = 200000.0, 500000.0, 10.0, 60
DEM_XMAX, DEM_YMIN = DEM_XMIN + DEM_PX * DEM_N, DEM_YMAX - DEM_PX * DEM_N


# --------------------------------------------------------------------------- helpers
def _dem(ctx, name="dem", kind="ridge"):
    from qgis.core import QgsProject, QgsRasterLayer
    path = ctx.env.make_dem(os.path.join(ctx.tmp, f"{name}.tif"), kind=kind)
    lyr = QgsRasterLayer(path, name, "gdal")
    assert lyr.isValid(), "DEM layer invalid"
    QgsProject.instance().addMapLayer(lyr)
    return lyr, path


def _canvas_crs(ctx, authid="EPSG:5186"):
    from qgis.core import QgsCoordinateReferenceSystem
    ctx.iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem(authid))


def _dialog(ctx, module, cls):
    mod = importlib.import_module(f"tools.{module}")
    return getattr(mod, cls)(ctx.iface)


def _pump(cond, timeout_s=60.0, step_ms=50):
    """Process Qt events until cond() is true or the timeout elapses."""
    from qgis.PyQt.QtCore import QCoreApplication, QEventLoop
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        QCoreApplication.processEvents(QEventLoop.AllEvents, step_ms)
        if cond():
            # one extra spin so queued finished() callbacks are delivered
            QCoreApplication.processEvents(QEventLoop.AllEvents, step_ms)
            return True
        time.sleep(step_ms / 1000.0)
    return False


def _set(d, name, value, skipped):
    """Tolerant widget setter: spin/double spin -> setValue, checkbox/radio -> setChecked."""
    w = getattr(d, name, None)
    if w is None:
        skipped.append(name)
        return False
    if isinstance(value, bool):
        w.setChecked(value)
    else:
        w.setValue(value)
    return True


def _set_combo_data(d, name, data, skipped, fallback_index=None):
    w = getattr(d, name, None)
    if w is None:
        skipped.append(name)
        return False
    idx = w.findData(data)
    if idx < 0 and fallback_index is not None:
        idx = fallback_index
    if idx < 0:
        skipped.append(f"{name}:{data}")
        return False
    w.setCurrentIndex(idx)
    return True


def _layer_ids():
    from qgis.core import QgsProject
    return set(QgsProject.instance().mapLayers().keys())


def _fingerprint_new_layers(ctx, before_ids, key_by_kind=True):
    """Fingerprint every layer added since `before_ids`.

    Rasters -> raster_summary(source); vectors -> layer_summary. Keyed by the
    ArchToolkit `kind` metadata when present (falls back to the layer name).
    """
    from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
    try:
        from tools.utils import get_archtoolkit_layer_metadata
    except Exception:  # pragma: no cover
        get_archtoolkit_layer_metadata = lambda _l: {}  # noqa: E731
    out = {}
    names = []
    for lid, lyr in QgsProject.instance().mapLayers().items():
        if lid in before_ids:
            continue
        meta = {}
        try:
            meta = get_archtoolkit_layer_metadata(lyr) or {}
        except Exception:
            meta = {}
        kind = str(meta.get("kind") or "") if key_by_kind else ""
        key = kind or lyr.name()
        base = key
        n = 2
        while key in out:
            key = f"{base}#{n}"
            n += 1
        names.append(lyr.name())
        entry = {"name": lyr.name()}
        if isinstance(lyr, QgsRasterLayer):
            src = lyr.source().split("|", 1)[0]
            entry["raster"] = ctx.env.raster_summary(src)
            try:
                entry["renderer"] = type(lyr.renderer()).__name__
            except Exception:
                pass
        elif isinstance(lyr, QgsVectorLayer):
            entry["vector"] = ctx.env.layer_summary(lyr)
        params = meta.get("params")
        if isinstance(params, dict):
            entry["meta_params"] = {k: v for k, v in sorted(params.items())}
        out[key] = entry
    return out, sorted(names)


# --------------------------------------------------------------------------- terrain analysis
def _terrain_common(ctx, checks, spins, radio="radioTobler"):
    from qgis.PyQt.QtWidgets import QApplication
    dem, _ = _dem(ctx)
    d = _dialog(ctx, "terrain_analysis_dialog", "TerrainAnalysisDialog")
    skipped = []
    d.cmbDemLayer.setLayer(dem)
    for name in ("chkSlope", "chkAspect", "chkTRI", "chkTPI", "chkRoughness",
                 "chkSlopePosition", "chkCurvature", "chkAspectDeriv", "chkAutoSD"):
        _set(d, name, name in checks, skipped)
    for name, val in spins.items():
        _set(d, name, val, skipped)
    r = getattr(d, radio, None)
    if r is not None:
        r.setChecked(True)
    else:
        skipped.append(radio)
    before = _layer_ids()
    d.run_analysis()
    QApplication.processEvents()
    fp, names = _fingerprint_new_layers(ctx, before)
    res = {"layers": fp, "layer_names": names, "n_layers": len(names), "skipped_widgets": skipped}
    try:
        d.close()
    except Exception:
        pass
    return res


def scenario_terrain_basic(ctx):
    """slope (Tobler classes) + aspect + TRI(3x3) + TPI(3x3) + roughness + curvature + aspect derivatives."""
    return _terrain_common(
        ctx,
        checks={"chkSlope", "chkAspect", "chkTRI", "chkTPI", "chkRoughness", "chkCurvature", "chkAspectDeriv"},
        spins={"spinTPIRadius": 1, "spinTPIThreshold": 1.0, "spinTRIRadius": 1, "spinTRIMax": 20},
        radio="radioTobler",
    )


def scenario_terrain_multiscale(ctx):
    """TPI radius 3 + Weiss landform (radius 3, manual thresholds) + TRI radius 2 (RMS path)."""
    return _terrain_common(
        ctx,
        checks={"chkTPI", "chkSlopePosition", "chkTRI"},
        spins={"spinTPIRadius": 3, "spinTPIThreshold": 1.0, "spinSlopeThreshold": 5,
               "spinTPILow": -1.0, "spinTPIHigh": 1.0, "spinTRIRadius": 2, "spinTRIMax": 20},
        radio="radioKorean",
    )


# --------------------------------------------------------------------------- viewshed
def _viewshed_common(ctx, *, max_dist, higuchi, obs_xy=(200150.0, 499700.0)):
    from qgis.PyQt.QtWidgets import QApplication
    _canvas_crs(ctx)
    dem, _ = _dem(ctx)
    obs = ctx.env.make_points("observer", [obs_xy])
    d = _dialog(ctx, "viewshed_dialog", "ViewshedDialog")
    skipped = []
    d.cmbDemLayer.setLayer(dem)
    _set(d, "radioSinglePoint", True, skipped)
    _set(d, "radioFromLayer", True, skipped)
    QApplication.processEvents()
    if getattr(d, "cmbObserverLayer", None) is not None:
        d.cmbObserverLayer.setLayer(obs)
    else:
        skipped.append("cmbObserverLayer")
    _set(d, "spinObserverHeight", 1.6, skipped)
    # Distance first: on_higuchi_toggled pops a modal when max_dist < mid break.
    _set(d, "spinMaxDistance", max_dist, skipped)
    _set(d, "chkCurvature", False, skipped)
    _set(d, "chkRefraction", False, skipped)
    _set(d, "chkAoiStats", False, skipped)
    _set(d, "chkHiguchi", bool(higuchi), skipped)
    QApplication.processEvents()
    extra = {}
    if higuchi:
        # NEW has editable zone breaks; OLD hard-codes 500/2500. Keep the defaults so
        # the run is like-for-like, but record what the dialog actually holds.
        for w in ("spinHiguchiNear", "spinHiguchiMid"):
            sw = getattr(d, w, None)
            extra[w] = float(sw.value()) if sw is not None else "absent"
    before = _layer_ids()
    d.run_analysis()
    _pump(lambda: len(_layer_ids() - before) >= (2 if higuchi else 1), timeout_s=30)
    fp, names = _fingerprint_new_layers(ctx, before)
    res = {"layers": fp, "layer_names": names, "n_layers": len(names),
           "skipped_widgets": skipped, "higuchi_widgets": extra,
           "max_dist": max_dist, "observer": list(obs_xy)}
    try:
        d.close()
    except Exception:
        pass
    return res


def scenario_viewshed_single(ctx):
    """One observer from a point layer, 400 m radius, plain viewshed."""
    return _viewshed_common(ctx, max_dist=400, higuchi=False)


def scenario_viewshed_higuchi(ctx):
    """Observer on the ridge crest near the N edge, 3000 m radius (covers the whole DEM),
    Higuchi zone output + rings; cells along the crest lie > 500 m away so both the near
    and the mid zone are populated."""
    return _viewshed_common(ctx, max_dist=3000, higuchi=True, obs_xy=(200300.0, 499960.0))


# --------------------------------------------------------------------------- cost surface
def _cost_surface_common(ctx, *, model_data, model_fallback_index, extra_spins=None):
    from qgis.core import QgsPointXY
    _canvas_crs(ctx)
    dem, _ = _dem(ctx)
    d = _dialog(ctx, "cost_surface_dialog", "CostSurfaceDialog")
    skipped = []
    d.cmbDemLayer.setLayer(dem)
    _set_combo_data(d, "cmbModel", model_data, skipped, fallback_index=model_fallback_index)
    d._on_model_changed()
    _set(d, "chkCreateCostRaster", True, skipped)
    _set(d, "chkCreateEnergyRaster", False, skipped)
    _set(d, "chkCreatePath", True, skipped)
    _set(d, "chkCreateCorridor", False, skipped)
    _set(d, "chkUseFrictionRaster", False, skipped)
    _set(d, "chkUseFrictionVector", False, skipped)
    _set(d, "chkDiagonal", True, skipped)
    _set(d, "spinBuffer", 0.0, skipped)
    for name, val in (extra_spins or {}).items():
        _set(d, name, val, skipped)
    d.set_start_point(QgsPointXY(200050.0, 499950.0))
    d.set_end_point(QgsPointXY(200550.0, 499450.0))
    captured = {}
    orig_handle = d._handle_task_result

    def _capture(res):
        captured["res"] = res
        return orig_handle(res)

    d._handle_task_result = _capture
    before = _layer_ids()
    d.run_analysis()
    finished = _pump(lambda: not d._task_running, timeout_s=60)
    fp, names = _fingerprint_new_layers(ctx, before)
    res = captured.get("res")
    summary = {}
    if res is not None:
        for f in ("ok", "message", "model_key", "total_cost_s", "lcp_dist_m", "lcp_time_s",
                  "straight_time_s", "straight_dist_m", "cost_min", "cost_max", "cost_mode",
                  "allow_diagonal"):
            v = getattr(res, f, None)
            summary[f] = v if isinstance(v, (int, float, str, bool)) or v is None else str(v)
        if getattr(res, "path_coords", None):
            summary["path_n"] = len(res.path_coords)
            summary["path_sum_x"] = round(sum(p[0] for p in res.path_coords), 3)
            summary["path_sum_y"] = round(sum(p[1] for p in res.path_coords), 3)
        summary["model_params"] = {k: v for k, v in sorted((res.model_params or {}).items())}
    out = {"finished": finished, "task_result": summary, "layers": fp, "layer_names": names,
           "n_layers": len(names), "skipped_widgets": skipped,
           "model_text": d.cmbModel.currentText(), "model_data": d.cmbModel.currentData()}
    conolly = getattr(d, "spinConollyRefSlopeDeg", None)
    if conolly is not None:
        out["conolly_ref_slope_widget"] = float(conolly.value())
    try:
        d.reject()
    except Exception:
        pass
    return out


def scenario_cost_tobler(ctx):
    """Tobler cost surface + least-cost path between two points."""
    from tools import cost_models
    return _cost_surface_common(ctx, model_data=cost_models.MODEL_TOBLER, model_fallback_index=0)


def scenario_cost_conolly(ctx):
    """Relative-slope (Conolly & Lake) surface + LCP; ref slope pinned to 5 deg in both checkouts."""
    from tools import cost_models
    return _cost_surface_common(
        ctx, model_data=cost_models.MODEL_CONOLLY_LAKE, model_fallback_index=3,
        extra_spins={"spinConollyRefSlopeDeg": 5.0, "spinConollyBaseKmh": 5.0},
    )


# --------------------------------------------------------------------------- cost network
def scenario_cost_network_mst(ctx):
    """Three sites, Tobler, MST network."""
    from tools import cost_models
    _canvas_crs(ctx)
    dem, _ = _dem(ctx)
    sites = ctx.env.make_points(
        "sites", [(200050.0, 499950.0), (200550.0, 499450.0), (200500.0, 499950.0)]
    )
    d = _dialog(ctx, "cost_network_dialog", "CostNetworkDialog")
    skipped = []
    d.cmbDemLayer.setLayer(dem)
    d.cmbSiteLayer.setLayer(sites)
    try:
        d._on_site_layer_changed()
    except Exception:
        pass
    _set_combo_data(d, "cmbModel", cost_models.MODEL_TOBLER, skipped, fallback_index=0)
    d._on_model_changed()
    _set_combo_data(d, "cmbNetworkMode", "mst", skipped, fallback_index=0)
    try:
        d._on_mode_changed()
    except Exception:
        pass
    _set_combo_data(d, "cmbNameField", "name", skipped)
    _set(d, "chkSelectedOnly", False, skipped)
    _set(d, "chkDiagonal", True, skipped)
    _set(d, "spinCandidateK", 3, skipped)
    _set(d, "spinPairBuffer", 200.0, skipped)
    _set(d, "chkSnaEnable", False, skipped)
    captured = {}
    orig_handle = d._handle_task_result

    def _capture(res):
        captured["res"] = res
        return orig_handle(res)

    d._handle_task_result = _capture
    before = _layer_ids()
    d.run_analysis()
    finished = _pump(lambda: not d._task_running, timeout_s=60)
    fp, names = _fingerprint_new_layers(ctx, before)
    res = captured.get("res")
    summary = {}
    if res is not None:
        summary["ok"] = bool(getattr(res, "ok", False))
        summary["message"] = str(getattr(res, "message", ""))
        edges = getattr(res, "edges", None) or []
        summary["n_edges"] = len(edges)
        try:
            summary["edge_kinds"] = sorted(str(e.kind) for e in edges)
            summary["edge_time_sym_sum"] = round(sum(float(getattr(e, "time_min_sym", 0) or 0) for e in edges), 4)
            summary["edge_dist_sum"] = round(sum(float(getattr(e, "dist_m", 0) or 0) for e in edges), 4)
        except Exception as exc:
            summary["edge_err"] = str(exc)
        summary["allow_diagonal"] = getattr(res, "allow_diagonal", "absent")
    # Per-edge attribute rows of the network line layer make the diff precise.
    from qgis.core import QgsProject, QgsVectorLayer
    rows = []
    for lid, lyr in QgsProject.instance().mapLayers().items():
        if lid in before or not isinstance(lyr, QgsVectorLayer):
            continue
        if lyr.geometryType() == 1:  # line
            for f in lyr.getFeatures():
                row = {}
                for fld in lyr.fields():
                    v = f[fld.name()]
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        row[fld.name()] = round(float(v), 4)
                    elif isinstance(v, str):
                        row[fld.name()] = v
                rows.append(row)
    rows.sort(key=lambda r: str(sorted(r.items())))
    out = {"finished": finished, "task_result": summary, "layers": fp, "layer_names": names,
           "n_layers": len(names), "edge_rows": rows, "skipped_widgets": skipped,
           "cost_mode": d.cmbCostMode.currentData(), "model_text": d.cmbModel.currentText()}
    try:
        d.reject()
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------- contours
def scenario_contour_5m(ctx):
    from qgis.PyQt.QtWidgets import QApplication
    dem, _ = _dem(ctx)
    d = _dialog(ctx, "contour_extractor_dialog", "ContourExtractorDialog")
    skipped = []
    _set(d, "radioDem", True, skipped)
    d.cmbDemLayer.setLayer(dem)
    _set(d, "spinInterval", 5, skipped)
    before = _layer_ids()
    d.run_process()
    QApplication.processEvents()
    fp, names = _fingerprint_new_layers(ctx, before)
    # Also record per-level counts so a changed contour set is visible.
    from qgis.core import QgsProject, QgsVectorLayer
    levels = {}
    total_len = 0.0
    for lid, lyr in QgsProject.instance().mapLayers().items():
        if lid in before or not isinstance(lyr, QgsVectorLayer):
            continue
        for f in lyr.getFeatures():
            try:
                lv = str(round(float(f["ELEV"]), 3))
            except Exception:
                lv = "?"
            levels[lv] = levels.get(lv, 0) + 1
            total_len += f.geometry().length()
    try:
        d.close()
    except Exception:
        pass
    return {"layers": fp, "layer_names": names, "n_layers": len(names), "levels": levels,
            "total_length": round(total_len, 3), "skipped_widgets": skipped}


# --------------------------------------------------------------------------- terrain profile
def scenario_profile_line(ctx):
    from qgis.core import QgsPointXY
    from qgis.PyQt.QtWidgets import QApplication
    _canvas_crs(ctx)
    dem, _ = _dem(ctx)
    d = _dialog(ctx, "terrain_profile_dialog", "TerrainProfileDialog")
    skipped = []
    d.cmbDemLayer.setLayer(dem)
    _set(d, "spinSamples", 50, skipped)
    _set(d, "chkFixedLength", False, skipped)
    _set(d, "chkSingleLayers", False, skipped)
    _set(d, "chkSegmentStats", True, skipped)
    before = _layer_ids()
    d.points = []
    d.add_point(QgsPointXY(200050.0, 499700.0))
    d.add_point(QgsPointXY(200550.0, 499700.0))  # crosses the ridge W->E
    QApplication.processEvents()
    fp, names = _fingerprint_new_layers(ctx, before)
    data = list(getattr(d, "profile_data", []) or [])
    elev = [float(p["elevation"]) for p in data]
    dist = [float(p["distance"]) for p in data]
    out = {
        "n_samples": len(data),
        "elev_min": round(min(elev), 4) if elev else None,
        "elev_max": round(max(elev), 4) if elev else None,
        "elev_sum": round(sum(elev), 4) if elev else None,
        "dist_last": round(dist[-1], 4) if dist else None,
        "dist_sum": round(sum(dist), 4) if dist else None,
        "first5": [round(v, 3) for v in elev[:5]],
        "last_length_m": getattr(d, "_last_profile_length_m", None),
        "layers": fp, "layer_names": names, "n_layers": len(names), "skipped_widgets": skipped,
    }
    try:
        d.cleanup_and_close()
    except Exception:
        try:
            d.close()
        except Exception:
            pass
    return out


# --------------------------------------------------------------------------- map styling
def scenario_map_styling_dem(ctx):
    from qgis.PyQt.QtWidgets import QApplication
    from qgis.core import QgsProject, QgsRasterLayer
    dem, _ = _dem(ctx)
    d = _dialog(ctx, "map_styling_dialog", "MapStylingDialog")
    skipped = []
    _set(d, "chkDemStyling", True, skipped)
    d.cmbDemLayer.setLayer(dem)
    for w in ("chkRoads", "chkRivers", "chkBuildings"):
        _set(d, w, False, skipped)
    before = _layer_ids()
    d.apply_styling()
    QApplication.processEvents()
    fp, names = _fingerprint_new_layers(ctx, before)
    # Renderer details of the styled clones (the actual "style" this tool applies).
    styles = {}
    for lid, lyr in QgsProject.instance().mapLayers().items():
        if lid in before or not isinstance(lyr, QgsRasterLayer):
            continue
        r = lyr.renderer()
        info = {"renderer": type(r).__name__, "opacity": round(float(lyr.opacity()), 3),
                "blend": int(lyr.blendMode())}
        try:
            if hasattr(r, "shader") and r.shader() is not None:
                fn = r.shader().rasterShaderFunction()
                items = fn.colorRampItemList()
                info["ramp"] = [[round(float(it.value), 4), it.color.name(), it.label] for it in items]
                info["ramp_type"] = int(fn.colorRampType())
            if hasattr(r, "azimuth"):
                info["azimuth"] = float(r.azimuth())
                info["altitude"] = float(r.altitude())
        except Exception as exc:
            info["err"] = str(exc)
        styles[lyr.name()] = info
    groups = [g.name() for g in QgsProject.instance().layerTreeRoot().findGroups()]
    try:
        d.close()
    except Exception:
        pass
    return {"layers": fp, "layer_names": names, "n_layers": len(names), "styles": styles,
            "groups": groups, "skipped_widgets": skipped}


def scenario_viewshed_higuchi_custom(ctx):
    """Higuchi with the NEW editable zone breaks set to 200/400 m (widgets absent in OLD,
    which therefore keeps its hard-coded 500/2500 m; the raster is expected to differ)."""
    from qgis.PyQt.QtWidgets import QApplication
    _canvas_crs(ctx)
    dem, _ = _dem(ctx)
    obs = ctx.env.make_points("observer", [(200300.0, 499960.0)])
    d = _dialog(ctx, "viewshed_dialog", "ViewshedDialog")
    skipped = []
    d.cmbDemLayer.setLayer(dem)
    _set(d, "radioSinglePoint", True, skipped)
    _set(d, "radioFromLayer", True, skipped)
    QApplication.processEvents()
    d.cmbObserverLayer.setLayer(obs)
    _set(d, "spinObserverHeight", 1.6, skipped)
    _set(d, "spinMaxDistance", 3000, skipped)
    _set(d, "chkCurvature", False, skipped)
    _set(d, "chkRefraction", False, skipped)
    _set(d, "chkAoiStats", False, skipped)
    _set(d, "chkHiguchi", True, skipped)
    _set(d, "spinHiguchiNear", 200.0, skipped)
    _set(d, "spinHiguchiMid", 400.0, skipped)
    QApplication.processEvents()
    before = _layer_ids()
    d.run_analysis()
    _pump(lambda: len(_layer_ids() - before) >= 2, timeout_s=30)
    fp, names = _fingerprint_new_layers(ctx, before)
    # class histogram of the Higuchi raster (0/85/170/255)
    hist = {}
    try:
        import numpy as np
        from osgeo import gdal
        for v in fp.values():
            if v.get("name", "").startswith("가시권_히구치"):
                src = None
                from qgis.core import QgsProject
                for lyr in QgsProject.instance().mapLayers().values():
                    if lyr.name() == v["name"]:
                        src = lyr.source().split("|", 1)[0]
                ds = gdal.Open(src)
                arr = ds.GetRasterBand(1).ReadAsArray()
                ds = None
                vals, cnts = np.unique(arr, return_counts=True)
                hist = {str(int(a)): int(c) for a, c in zip(vals, cnts)}
    except Exception as exc:
        hist = {"err": str(exc)}
    try:
        d.close()
    except Exception:
        pass
    return {"layers": fp, "layer_names": names, "n_layers": len(names), "class_hist": hist,
            "skipped_widgets": skipped}


def scenario_terrain_tpi_fallback(ctx):
    """TPI only, radius 30 on the 60x60 DEM: a side of 60 cells is <= 2r, so no cell
    has a full (2r+1)-cell window and the tool must fall back to the 3x3 index with a
    message and report radius 1. (Radius 15 now gets the exact focal TPI.)"""
    return _terrain_common(
        ctx,
        checks={"chkTPI"},
        spins={"spinTPIRadius": 30, "spinTPIThreshold": 1.0},
        radio="radioKorean",
    )
