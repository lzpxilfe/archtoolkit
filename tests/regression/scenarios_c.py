"""Scenario set C: AHP suitability, trench suggestion, cadastral overlap,
covariate report and the AI-report *local* path (no Gemini).

Every scenario returns a JSON-serialisable dict of fingerprints.  Volatile
values (layer ids, run ids, timestamps) are scrubbed so OLD/NEW diffs only
show real behavioural changes.
"""
from __future__ import annotations

import csv
import inspect
import math
import os
import random
import re
import time

# gdal_calc.py etc. are re-exec'd with this interpreter by qgis_env.ensure_gdal_shims()
# (called by run_scenarios.py), so no PATH handling is needed here.

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_VOLATILE_KEYS = {
    "id", "layer_id", "run_id", "created_at", "fid", "left_layer_id", "right_layer_id",
    "layer_ids", "paired_polygon_layer", "hidden_xls_loaded",
}
_RUN_ID_RE = re.compile(r"_[0-9a-f]{6,}(_[0-9]+)?$|_[0-9]{8}_[0-9]{6}.*$")


def _scrub(obj):
    """Drop volatile keys recursively and coerce non-JSON values to str."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            ks = str(k)
            if ks in _VOLATILE_KEYS:
                continue
            out[ks] = _scrub(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_scrub(v) for v in obj]
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return str(obj)
        return round(obj, 6)
    if isinstance(obj, (int, str, bool)) or obj is None:
        return obj
    return str(obj)


def _scrub_name(name: str) -> str:
    return _RUN_ID_RE.sub("_<id>", str(name or ""))


def _layer_fp(env, layer):
    d = env.layer_summary(layer)
    if "name" in d:
        d["name"] = _scrub_name(d["name"])
    return d


def _meta(layer):
    try:
        from tools.utils import get_archtoolkit_layer_metadata
        m = get_archtoolkit_layer_metadata(layer) or {}
    except Exception as exc:  # pragma: no cover
        return {"meta_error": str(exc)}
    return _scrub(m)


def _pump(seconds: float = 0.5):
    from qgis.PyQt.QtCore import QCoreApplication
    t0 = time.time()
    while time.time() - t0 < seconds:
        QCoreApplication.processEvents()
        time.sleep(0.02)


def _project_layers():
    from qgis.core import QgsProject
    return list(QgsProject.instance().mapLayers().values())


def _find_layers(prefix: str):
    return [lyr_ for lyr_ in _project_layers() if str(lyr_.name() or "").startswith(prefix)]


def _write_raster(path, arr, *, xmin=200000.0, ymax=500000.0, px=10.0, crs_epsg=5186, nodata=-9999.0):
    import numpy as np
    from osgeo import gdal, osr
    nrows, ncols = arr.shape
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, ncols, nrows, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((xmin, px, 0.0, ymax, 0.0, -px))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(crs_epsg)
    ds.SetProjection(srs.ExportToWkt())
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(nodata)
    b.WriteArray(np.asarray(arr, dtype=np.float32))
    b.FlushCache()
    ds = None
    return path


def _make_criteria_rasters(ctx):
    """DEM (ridge), a slope-like raster, a distance-like raster; all 60x60 aligned."""
    import numpy as np
    dem = ctx.env.make_dem(os.path.join(ctx.tmp, "dem.tif"), kind="ridge")
    yy, xx = np.mgrid[0:60, 0:60].astype(np.float64)
    # slope-like: steep flanks of the ridge, 0..~35 deg
    slope = 35.0 * np.abs(np.sin((xx - 30.0) / 10.0)) * np.exp(-((xx - 30.0) ** 2) / 600.0) + 0.2 * yy
    dist = np.hypot((xx - 10.0) * 10.0, (yy - 50.0) * 10.0)  # metres from a "water" point
    slope_p = _write_raster(os.path.join(ctx.tmp, "slope.tif"), slope)
    dist_p = _write_raster(os.path.join(ctx.tmp, "dist.tif"), dist)
    return dem, slope_p, dist_p


def _aoi_ring():
    # 300 m x 300 m inside the 600 m x 600 m DEM (200000..200600, 499400..500000)
    return [(200150, 499250 + 300), (200450, 499250 + 300), (200450, 499250 + 600), (200150, 499250 + 600), (200150, 499250 + 300)]
    # -> x 200150..200450, y 499550..499850


def _make_polygons(name, rings, *, fields=None, attrs=None, crs_epsg=5186):
    from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer
    lyr = QgsVectorLayer(f"Polygon?crs=EPSG:{crs_epsg}", name, "memory")
    pr = lyr.dataProvider()
    pr.addAttributes([QgsField(n, t) for n, t in (fields or [])])
    lyr.updateFields()
    feats = []
    for i, ring in enumerate(rings):
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(float(x), float(y)) for x, y in ring]]))
        if attrs:
            f.setAttributes(list(attrs[i]))
        feats.append(f)
    pr.addFeatures(feats)
    lyr.updateExtents()
    QgsProject.instance().addMapLayer(lyr)
    return lyr


def _square(x0, y0, w, h):
    return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h), (x0, y0)]


# ---------------------------------------------------------------------------
# AHP suitability
# ---------------------------------------------------------------------------

def _ahp_setup(ctx):
    from tools.ahp_suitability_dialog import AhpSuitabilityDialog
    dem_p, slope_p, dist_p = _make_criteria_rasters(ctx)
    dem = ctx.iface.addRasterLayer(dem_p, "DEM")
    slope = ctx.iface.addRasterLayer(slope_p, "Slope")
    dist = ctx.iface.addRasterLayer(dist_p, "DistWater")
    d = AhpSuitabilityDialog(ctx.iface)
    for lyr, direction in ((dem, "benefit"), (slope, "cost"), (dist, "cost")):
        d.cmbRaster.setLayer(lyr)
        k = d.cmbDirection.findData(direction)
        if k >= 0:
            d.cmbDirection.setCurrentIndex(k)
        d._on_add_criterion()
    try:
        d.cmbAoi.setLayer(None)
    except Exception:
        pass
    d.chkAddToProject.setChecked(True)
    d.chkAlignToFirst.setChecked(True)
    d.chkScale100.setChecked(False)
    return d, (dem, slope, dist)


def _ahp_set_pair(d, i, j, value):
    cmb = d.tblPairwise.cellWidget(i, j)
    k = cmb.findData(float(value))
    if k < 0:
        raise RuntimeError(f"scale value {value} not found")
    cmb.setCurrentIndex(k)


_W_RE = re.compile(r"\*\s*([0-9.eE+-]+)\s*$")


def _ahp_capture_formulas(d):
    """Wrap the raster-calc helper so the weight actually multiplied into each
    criterion raster is recorded (formula ends with '* <weight>')."""
    formulas = []
    orig = d._processing_raster_calc

    def _cap(**kw):
        formulas.append(str(kw.get("formula")))
        return orig(**kw)

    d._processing_raster_calc = _cap
    return formulas


def _ahp_fingerprint(ctx, d, out_path, formulas=None):
    res = {}
    if formulas is not None:
        ws = []
        for f in formulas:
            m = _W_RE.search(f)
            if m and "A + B" not in f and "100.0" not in f:
                ws.append(round(float(m.group(1)), 6))
        res["raster_calc_weights_used"] = ws
        res["raster_calc_n"] = len(formulas)
    hv = getattr(d, "_hierarchy_global_weight_vector", None)
    res["hierarchy_global_weight_vector"] = ([round(float(x), 6) for x in hv()] if callable(hv) and hv() is not None else None) if callable(hv) else "<absent>"
    res["n_criteria"] = len(d._criteria)
    res["pairwise"] = {f"{i},{j}": round(float(v), 6) for (i, j), v in sorted(d._pairwise.items())}
    res["criteria_weights"] = [round(float(c.weight), 6) if c.weight is not None else None for c in d._criteria]
    res["criteria_minmax"] = [[_scrub(c.min_v), _scrub(c.max_v)] for c in d._criteria]
    res["consistency_label"] = str(d.lblConsistency.text())
    res["weight_input_mode"] = str(getattr(d, "_weight_input_mode", "<absent>"))
    res["raster"] = ctx.env.raster_summary(out_path) if os.path.exists(out_path) else {"error": "no output"}
    outs = _find_layers("AHP Suitability")
    res["output_layers"] = len(outs)
    if outs:
        m = _meta(outs[0])
        params = m.get("params") or {}
        res["meta_kind"] = m.get("kind")
        res["meta_units"] = m.get("units")
        res["params_keys"] = sorted(params.keys())
        res["params_weights"] = [c.get("weight") for c in (params.get("criteria") or [])]
        res["params_directions"] = [c.get("direction") for c in (params.get("criteria") or [])]
        res["params_cr"] = params.get("consistency_ratio")
        res["params_weight_input_mode"] = params.get("weight_input_mode", "<absent>")
        res["params_weights_source"] = params.get("weights_source", "<absent>")
        res["params_clamped"] = params.get("global_pairwise_clamped", "<absent>")
        res["params_clamped_count"] = params.get("global_pairwise_clamped_count", "<absent>")
        hier = params.get("hierarchy")
        if hier:
            res["hierarchy"] = {
                "group_order": hier.get("group_order"),
                "group_weights": hier.get("group_weights"),
                "global_weights": [(g.get("layer_name"), g.get("group"), g.get("weight")) for g in (hier.get("global_weights") or [])],
                "group_pairwise": hier.get("group_pairwise"),
                "clamped": hier.get("global_pairwise_clamped", "<absent>"),
                "clamped_count": hier.get("global_pairwise_clamped_count", "<absent>"),
                "clamped_pairs": hier.get("global_pairwise_clamped_pairs", "<absent>"),
                "note_nonempty": bool(hier.get("global_pairwise_note")),
            }
    return res


def scenario_ahp_flat(ctx):
    d, _layers = _ahp_setup(ctx)
    _ahp_set_pair(d, 0, 1, 3.0)
    _ahp_set_pair(d, 0, 2, 5.0)
    _ahp_set_pair(d, 1, 2, 2.0)
    out = os.path.join(ctx.tmp, "ahp_flat.tif")
    d.txtOut.setText(out)
    formulas = _ahp_capture_formulas(d)
    d._on_run()
    _pump(0.3)
    return _ahp_fingerprint(ctx, d, out, formulas=formulas)


def scenario_ahp_hierarchy(ctx):
    d, _layers = _ahp_setup(ctx)
    ids = [c.layer_id for c in d._criteria]
    # 2 groups: terrain={DEM}, access={Slope, DistWater}. terrain:access = 9,
    # Slope:DistWater = 1/9  -> global weights 0.9 / 0.01 / 0.09, so the flat
    # seed ratios DEM/Slope=90 and DEM/DistWater=10 exceed the Saaty scale.
    config = {
        "criterion_groups": {ids[0]: "terrain", ids[1]: "access", ids[2]: "access"},
        "group_pairs": {("terrain", "access"): 9.0},
        "local_pairs": {"access": {(ids[1], ids[2]): 1.0 / 9.0}},
    }
    res = {}
    if not hasattr(d, "_apply_hierarchy_config"):
        res["apply_hierarchy"] = "method missing"
    else:
        res["apply_hierarchy"] = bool(d._apply_hierarchy_config(config))
    try:
        san = d._sanitize_hierarchy_config(config)
        comp = san.get("computed") or {}
        res["computed_global_weights"] = {str(_layers_name(ctx, k)): round(float(v), 6) for k, v in (comp.get("global_weights") or {}).items()}
        res["computed_global_pairwise"] = sorted(round(float(v), 6) for v in (comp.get("global_pairwise") or {}).values())
        res["computed_clamped"] = comp.get("global_pairwise_clamped", "<absent>")
        res["computed_clamped_count"] = comp.get("global_pairwise_clamped_count", "<absent>")
    except Exception as exc:
        res["sanitize_error"] = f"{type(exc).__name__}: {exc}"
    res["weight_mode_note_nonempty"] = bool(getattr(d, "_weight_input_note", ""))
    out = os.path.join(ctx.tmp, "ahp_hier.tif")
    d.txtOut.setText(out)
    formulas = _ahp_capture_formulas(d)
    d._on_run()
    _pump(0.3)
    res.update(_ahp_fingerprint(ctx, d, out, formulas=formulas))
    return res


def _layers_name(ctx, layer_id):
    from qgis.core import QgsProject
    lyr = QgsProject.instance().mapLayer(str(layer_id))
    return lyr.name() if lyr is not None else "?"


# ---------------------------------------------------------------------------
# Trench suggestion
# ---------------------------------------------------------------------------

_GRAVE_STRINGS = [
    "무덤",
    "고분군 A0010000",
    "고분자 화합물",
    "묘목장",
    "천마총",
    "총 3건",
    "구릉지",
    "선릉역",
    "패총",
    "지석묘군",
    "gravel road",
    "Tomb of the King",
    "cemeteries",
    "dolmen field",
    "tumuli",
]


def scenario_trench_grave_keywords(ctx):
    from tools import trench_suggestion_dialog as mod
    fn = getattr(mod, "_text_has_grave_keyword", None)
    if fn is None:
        return {"error": "_text_has_grave_keyword missing"}
    out = {s: bool(fn(s)) for s in _GRAVE_STRINGS}
    out["_true_count"] = sum(1 for v in out.values() if v is True)
    terms = getattr(mod, "_grave_search_terms", None)
    out["_search_term_count"] = len(terms()) if callable(terms) else "<absent>"
    return out


def scenario_trench_suggestion(ctx):
    from tools.trench_suggestion_dialog import TrenchSuggestionDialog
    dem_p = ctx.env.make_dem(os.path.join(ctx.tmp, "dem.tif"), kind="ridge")
    dem = ctx.iface.addRasterLayer(dem_p, "DEM")
    aoi = ctx.env.make_polygon("AOI", _aoi_ring())
    d = TrenchSuggestionDialog(ctx.iface)
    d.cmbAoi.setLayer(aoi)
    d.chkAoiSelectedOnly.setChecked(False)
    d.cmbDem.setLayer(dem)
    for cmb in ("cmbAhp", "cmbRefSites", "cmbTopo"):
        try:
            getattr(d, cmb).setLayer(None)
        except Exception:
            pass
    d.spinCount.setValue(6)
    d.spinGrid.setValue(20.0)
    d._run()
    _pump(0.3)
    res = {}
    polys = _find_layers("Trench_Suggestions_")
    cents = _find_layers("Trench_Centers_")
    res["n_poly_layers"] = len(polys)
    res["n_center_layers"] = len(cents)
    if polys:
        p = polys[0]
        res["poly"] = _layer_fp(ctx.env, p)
        rows = []
        for f in p.getFeatures():
            rows.append((int(f["rank"]), round(float(f["score"]), 6), round(float(f["slope_deg"]), 4), round(float(f["bearing_deg"]), 3)))
        rows.sort()
        res["rank_score_pairs"] = rows
        scores_by_rank = [r[1] for r in rows]
        res["rank_is_score_order"] = scores_by_rank == sorted(scores_by_rank, reverse=True)
        m = _meta(p)
        params = m.get("params") or {}
        res["meta_kind"] = m.get("kind")
        res["params"] = params
    if cents:
        res["center"] = _layer_fp(ctx.env, cents[0])
        res["center_meta_kind"] = _meta(cents[0]).get("kind")
    return res


# ---------------------------------------------------------------------------
# Cadastral overlap
# ---------------------------------------------------------------------------

def scenario_cadastral_overlap(ctx):
    from qgis.PyQt.QtCore import QVariant
    from tools.cadastral_overlap_dialog import CadastralOverlapDialog
    parcels = _make_polygons(
        "Parcels",
        [
            _square(200100, 499700, 100, 100),
            _square(200200, 499700, 100, 100),
            _square(200100, 499600, 100, 100),
            _square(200300, 499600, 100, 100),
        ],
        fields=[("PNU", QVariant.String), ("JIBUN", QVariant.String), ("AREA_REG", QVariant.Double)],
        attrs=[
            ["4111010100100010000", "1", 10000.0],
            ["4111010100100020000", "2", 10000.0],
            ["4111010100100030000", "3", 10000.0],
            ["4111010100100040000", "4", 10000.0],
        ],
    )
    # AOI overlaps parcel 1 (50 x 80 = 4000 m2) and parcel 2 (80 x 80 = 6400 m2)
    aoi = ctx.env.make_polygon("SurveyArea", _square(200150, 499720, 130, 130))
    d = CadastralOverlapDialog(ctx.iface)
    d.cmbCadastral.setLayer(parcels)
    d.cmbSurvey.setLayer(aoi)
    d.chkCadastralSelected.setChecked(False)
    d.chkSurveySelected.setChecked(False)
    d.chkSplitBySurveyFeature.setChecked(False)
    d.run()
    _pump(0.3)
    outs = _find_layers("지적중첩_")
    res = {"n_output_layers": len(outs)}
    if outs:
        o = outs[0]
        res["layer"] = _layer_fp(ctx.env, o)
        rows = []
        for f in o.getFeatures():
            rows.append((str(f["PNU"]), round(float(f["parcel_m2"]), 3), round(float(f["in_aoi_m2"]), 3), round(float(f["in_aoi_pct"]), 4)))
        res["rows"] = sorted(rows)
        res["meta"] = _meta(o)
        try:
            res["aliases"] = [o.attributeAlias(i) for i in range(o.fields().count())]
        except Exception:
            pass
    return res


# ---------------------------------------------------------------------------
# Covariate report
# ---------------------------------------------------------------------------

def scenario_covariate_report(ctx):
    from qgis.PyQt import QtWidgets
    from qgis.PyQt.QtCore import QVariant
    from tools.covariate_report_dialog import CovariateReportDialog
    dem_p, slope_p, _dist_p = _make_criteria_rasters(ctx)
    ctx.iface.addRasterLayer(dem_p, "DEM")
    ctx.iface.addRasterLayer(slope_p, "Slope")
    pts = [(200050 + 70 * i, 499450 + 60 * i) for i in range(8)]
    ctx.env.make_points("Sites", pts, fields=[("value", QVariant.Double)], attrs=[[float(i)] for i in range(8)])
    d = CovariateReportDialog(ctx.iface)
    d._check_all(True)
    d.spinSamples.setValue(2000)
    captured = {}

    def _fake_show(html, names, corr, vifs, n_samples):
        captured.update({"html": html, "names": list(names), "corr": corr, "vifs": list(vifs), "n": int(n_samples)})

    d._show_report = _fake_show
    csv_path = os.path.join(ctx.tmp, "covariate_report.csv")
    orig = QtWidgets.QFileDialog.getSaveFileName
    QtWidgets.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (csv_path, "CSV (*.csv)"))
    try:
        d._on_run()
        _pump(0.2)
        if captured:
            d._save_csv(captured["names"], captured["corr"], captured["vifs"])
    finally:
        QtWidgets.QFileDialog.getSaveFileName = orig
    res = {"selected": len(d._selected_layers()), "captured": bool(captured)}
    if captured:
        corr = captured["corr"]
        res["names"] = captured["names"]
        res["n_samples"] = captured["n"]
        res["corr"] = [[round(float(corr[i, j]), 6) for j in range(len(captured["names"]))] for i in range(len(captured["names"]))]
        res["vifs"] = [(round(float(v), 6) if math.isfinite(float(v)) else str(v)) for v in captured["vifs"]]
        res["html_len"] = len(captured["html"])
    if os.path.exists(csv_path):
        with open(csv_path, encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        res["csv_rows"] = rows
    else:
        res["csv_rows"] = "missing"
    return res


# ---------------------------------------------------------------------------
# AI report - local path only (build_aoi_context -> generate_report -> csv)
# ---------------------------------------------------------------------------

def scenario_ai_report_local(ctx):
    from qgis.PyQt.QtCore import QVariant
    from tools import ai_aoi_summary
    from tools import ai_local_summarizer

    dem_p, slope_p, _ = _make_criteria_rasters(ctx)
    ctx.iface.addRasterLayer(dem_p, "DEM")
    ctx.iface.addRasterLayer(slope_p, "Slope")
    aoi = ctx.env.make_polygon("AOI", _aoi_ring())  # x 200150..200450, y 499550..499850

    # 200 points: 197 scattered around (outside the AOI) + 3 inside.
    rng = random.Random(42)
    coords = []
    while len(coords) < 197:
        x = 198500 + rng.random() * 3600.0
        y = 498000 + rng.random() * 3600.0
        if 200150 - 5 <= x <= 200450 + 5 and 499550 - 5 <= y <= 499850 + 5:
            continue
        coords.append((round(x, 2), round(y, 2)))
    coords += [(200200.0, 499600.0), (200300.0, 499700.0), (200420.0, 499830.0)]
    attrs = []
    for i, (x, y) in enumerate(coords):
        attrs.append([int(i % 7), 4111010100100000000 + i, round(math.hypot(x - 200300, y - 499700), 2), "선사" if i % 3 == 0 else ("삼국" if i % 3 == 1 else "고려")])
    sites = ctx.env.make_points(
        "Sites",
        coords,
        fields=[("B", QVariant.Int), ("PNU", QVariant.LongLong), ("value", QVariant.Double), ("period_type", QVariant.String)],
        attrs=attrs,
    )
    _make_polygons(
        "Zones",
        [
            _square(200100, 499500, 200, 200),   # overlaps AOI
            _square(200400, 499800, 150, 150),   # touches AOI corner
            _square(201500, 501000, 100, 100),   # far away (outside buffer)
        ],
        fields=[("지목", QVariant.String), ("grade", QVariant.Int)],
        attrs=[["전", 1], ["임야", 2], ["대", 3]],
    )

    sig = inspect.signature(ai_aoi_summary.build_aoi_context)
    kwargs = dict(
        aoi_layer=aoi,
        selected_only=False,
        radius_m=500.0,
        only_archtoolkit_layers=False,
        reference_layer=sites,
        reference_name_field="name",
        reference_max_features=10,
    )
    kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
    res = {"build_kwargs": sorted(kwargs.keys()), "build_sig_params": sorted(sig.parameters.keys())}
    ctx_dict, err = ai_aoi_summary.build_aoi_context(**kwargs)
    res["build_error"] = err
    if not ctx_dict:
        return res

    res["aoi"] = _scrub(ctx_dict.get("aoi"))
    res["buffer_area_m2"] = _scrub(ctx_dict.get("buffer_area_m2"))
    res["options"] = _scrub(ctx_dict.get("options"))
    res["n_layers"] = len(ctx_dict.get("layers") or [])
    layers_fp = {}
    for item in ctx_dict.get("layers") or []:
        stats = item.get("stats") or {}
        entry = {"type": item.get("type")}
        if item.get("type") == "vector":
            entry.update({
                "features": stats.get("features"),
                "scanned": stats.get("scanned"),
                "truncated": stats.get("truncated", "<absent>"),
                "numeric_field_names": sorted((stats.get("numeric_fields") or {}).keys()) if isinstance(stats.get("numeric_fields"), dict) else stats.get("numeric_fields"),
                "numeric_fields": _scrub(stats.get("numeric_fields")),
                "numeric_fields_truncated": stats.get("numeric_fields_truncated", "<absent>"),
                "top_field": stats.get("top_field"),
                "top_values": _scrub(stats.get("top_values")),
                "total_area_m2": _scrub(stats.get("total_area_m2")),
                "dist_keys": sorted(k for k in stats.keys() if "dist" in k),
                "dist_vals": _scrub({k: v for k, v in stats.items() if "dist" in k}),
            })
        else:
            entry.update(_scrub({k: v for k, v in stats.items() if k in ("count", "min", "max", "mean", "std", "gt_0_5_pct", "high_value_pct", "sampled", "window_px")}))
            entry["stats_keys"] = sorted(stats.keys())
        layers_fp[str(item.get("name"))] = entry
    res["layers"] = layers_fp

    ref = ctx_dict.get("reference_sites") or {}
    items = ref.get("items") or []
    dists = [it.get("distance_to_aoi_m") for it in items if it.get("distance_to_aoi_m") is not None]
    cdists = [it.get("distance_to_aoi_centroid_m") for it in items if it.get("distance_to_aoi_centroid_m") is not None]
    res["reference"] = {
        "feature_count": ref.get("feature_count"),
        "classified_count": ref.get("classified_count", "<absent>"),
        "scanned": ref.get("scanned"),
        "scan_truncated": ref.get("scan_truncated", "<absent>"),
        "truncated": ref.get("truncated"),
        "counts": _scrub(ref.get("counts")),
        "n_items": len(items),
        "nearest_to_aoi_m": round(min(dists), 3) if dists else None,
        "nearest_to_centroid_m": round(min(cdists), 3) if cdists else None,
        "first_item": _scrub({k: v for k, v in (items[0] if items else {}).items() if k in ("name", "relation", "distance_to_aoi_m", "distance_to_aoi_centroid_m")}),
        "item_relations": sorted(str(it.get("relation")) for it in items),
    }

    text = str(ai_local_summarizer.generate_report(ctx_dict) or "")
    lines = [ln for ln in text.splitlines()]
    res["report_line_count"] = len(lines)
    res["report_char_count"] = len(text)
    res["report_lines"] = lines[:120]

    layers_csv = os.path.join(ctx.tmp, "aoi_layers.csv")
    fields_csv = os.path.join(ctx.tmp, "aoi_numeric_fields.csv")
    err2 = ai_aoi_summary.export_aoi_context_csv(ctx_dict, layers_csv_path=layers_csv, numeric_fields_csv_path=fields_csv)
    res["csv_error"] = err2
    for label, path in (("layers_csv", layers_csv), ("fields_csv", fields_csv)):
        if not os.path.exists(path):
            res[label] = "missing"
            continue
        with open(path, encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        hdr = rows[0] if rows else []
        drop = {i for i, h in enumerate(hdr) if h in ("layer_id", "created_at", "run_id")}
        res[label] = {
            "headers": hdr,
            "n_rows": max(0, len(rows) - 1),
            "rows": [[c for i, c in enumerate(r) if i not in drop] for r in rows[1:]],
        }
    return res
