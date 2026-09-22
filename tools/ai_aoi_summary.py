# -*- coding: utf-8 -*-
"""
AOI-centered project summary builder for ArchToolkit AI reporting.

Design goals
- Best-effort and fast: avoid heavy processing providers when possible.
- Only summarize information needed for a narrative report (no raw raster export).
"""

from __future__ import annotations

import heapq
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:
    from osgeo import gdal, ogr
except Exception:  # pragma: no cover
    gdal = None
    ogr = None

from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsFeatureRequest,
    QgsGeometry,
    QgsMapLayer,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)
from .qtcompat import FT_INT, FT_UINT, FT_LONGLONG, FT_ULONGLONG, FT_DOUBLE, FT_STRING

from .utils import is_null_value, log_swallowed, get_archtoolkit_layer_metadata, is_metric_crs, log_message
from .utils import split_qgis_source_path


_NUMERIC_FIELD_CANDIDATES = (
    # Generic stats-like fields
    "value",
    "val",
    "min",
    "max",
    "mean",
    "avg",
    # Viewshed AOI stats (common)
    "vis_pct",
    "vis_m2",
    "tot_m2",
    "feat_n",
    # Terrain profile (line attributes)
    "distance",
    "min_elev",
    "max_elev",
    # Cost/LCP outputs
    "dist_m",
    "time_min",
    "energy_kcal",
    # GeoChem polygonize outputs
    "val_min",
    "val_max",
    "v_min",
    "v_max",
    # Cadastral overlap outputs
    "parcel_m2",
    "in_aoi_m2",
    "in_aoi_pct",
)

# Field names that are numeric but carry no analytical meaning: ids/keys,
# sequence counters and graph component indices - their mean/min/max would read
# as pseudo-analytics in the report and the Gemini prompt. This generic rule is
# applied to EVERY layer, so it must not swallow legitimate short columns: a
# geochemistry table's boron column "B", a "rank" score or a "no" count are
# data, not ids. Tool-specific junk columns live in _TOOL_ID_FIELD_RES instead.
_ID_FIELD_RE = re.compile(
    r"^(fid|gid|id|oid|objectid|osm_id|uid|uuid|idx|index|seq|pnu"
    r"|component|번호|일련번호|.*_id|.*_fid|.*_no|.*_idx)$",
    re.IGNORECASE,
)

# Per-tool exclusions keyed by the layer's archtoolkit tool_id: terrain profile
# writes per-feature RGB colour columns and a row counter, cadastral overlap
# carries the 19-digit Korean PNU, trench suggestion a rank/row counter. They
# are skipped only when the layer metadata says it came from that tool.
_TOOL_ID_FIELD_RES = {
    "terrain_profile": re.compile(r"^(r|g|b|no)$", re.IGNORECASE),
    "cadastral_overlap": re.compile(r"^(pnu)$", re.IGNORECASE),
    "trench_suggestion": re.compile(r"^(rank|no)$", re.IGNORECASE),
}

# Hints that a string field is a category worth histogramming (EN + KO).
_CATEGORICAL_HINTS = (
    "class", "type", "category", "code", "grade", "kind", "group", "zone", "use",
    "지목", "분류", "종류", "구분", "유형", "코드", "명칭", "등급", "용도", "구역", "구조",
)

_NUMERIC_QVARIANTS = (
    FT_INT,
    FT_UINT,
    FT_LONGLONG,
    FT_ULONGLONG,
    FT_DOUBLE,
)


def _classify_fields(layer, *, max_numeric: int = 12, tool_id: str = ""):
    """Auto-select fields by their actual type instead of a name whitelist.

    Returns (numeric_field_names, categorical_field_name, numeric_dropped).
    Numeric fields are real numeric columns (excluding id/key-like names, plus
    the tool-specific junk columns for the ArchToolkit `tool_id` given); the
    categorical field is the best string column for a value histogram (Korean
    category fields included), preferring name hints and legacy tool outputs.
    `numeric_dropped` is how many numeric columns the `max_numeric` cap cut, so
    the report can say "외 N개 생략" instead of implying the column was absent.
    """
    numeric: List[str] = []
    categorical: Optional[str] = None
    tool_re = _TOOL_ID_FIELD_RES.get(str(tool_id or "").strip().lower())
    try:
        fields = list(layer.fields())
    except Exception:
        fields = []

    string_candidates: List[str] = []
    for f in fields:
        _skip_122 = False
        try:
            name = str(f.name() or "")
            ftype = f.type()
        except Exception as _exc:
            log_swallowed("tools/ai_aoi_summary.py:125 (_classify_fields)", _exc)
            _skip_122 = True
        if _skip_122:
            continue
        if not name:
            continue
        if ftype in _NUMERIC_QVARIANTS:
            if _ID_FIELD_RE.match(name):
                continue
            if tool_re is not None and tool_re.match(name):
                continue
            numeric.append(name)
        elif ftype == FT_STRING:
            string_candidates.append(name)

    # Order numeric fields: semantically-known (whitelist) first, then the rest.
    known = [c for c in _NUMERIC_FIELD_CANDIDATES if c in numeric]
    rest = [c for c in numeric if c not in known]
    numeric_ordered = (known + rest)[: int(max_numeric)]
    numeric_dropped = max(0, len(numeric) - len(numeric_ordered))

    # Categorical: legacy tool fields first, then a hinted string field.
    for legacy in ("class_id", "Layer", "element"):
        if legacy in string_candidates:
            categorical = legacy
            break
    if categorical is None:
        for name in string_candidates:
            low = name.lower()
            if any(h in low or h in name for h in _CATEGORICAL_HINTS):
                categorical = name
                break

    return numeric_ordered, categorical, numeric_dropped


_COMPASS_8_KO = ("북", "북동", "동", "남동", "남", "남서", "서", "북서")


def _compass8_ko(bearing_deg) -> str:
    """8-point Korean compass label for a compass bearing (deg, 0=north, CW)."""
    try:
        b = float(bearing_deg) % 360.0
    except Exception:
        return ""
    idx = int((b + 22.5) // 45.0) % 8
    return _COMPASS_8_KO[idx]


_split_qgis_source_path = split_qgis_source_path


def _is_geographic_crs(crs) -> bool:
    """True when `crs` is measured in degrees (planar measures would be degrees)."""
    try:
        return bool(crs is not None and crs.isValid() and crs.isGeographic())
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._is_geographic_crs", _exc)
        return False


def _will_use_ellipsoid(da: QgsDistanceArea) -> bool:
    """True when `da` is actually configured to measure on an ellipsoid.

    Guarded with hasattr/try because willUseEllipsoid() is not exposed by every
    QGIS build. When we cannot tell, assume the measurement is sound: this check
    exists to reject a bad number, never to withhold a correct one.
    """
    try:
        if not hasattr(da, "willUseEllipsoid"):
            return True
        return bool(da.willUseEllipsoid())
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._will_use_ellipsoid", _exc)
        return True


def _measures_in_degrees(da: QgsDistanceArea, crs) -> bool:
    """True when this measurer would hand back degrees rather than metres.

    measureArea()/measureLine() do not raise on a geographic CRS with no
    ellipsoid in effect - they succeed and return SQUARE DEGREES / DEGREES. Every
    caller in this module writes the result into a key named ``*_m2`` or ``*_m``,
    and those values go into the report *and* into the prompt handed to the LLM,
    so a degree-valued figure has to be withheld rather than presented as a
    measurement.
    """
    if da is None:
        return False
    return _is_geographic_crs(crs) and not _will_use_ellipsoid(da)


def _safe_distance_area(crs) -> QgsDistanceArea:
    da = QgsDistanceArea()
    try:
        da.setSourceCrs(crs, QgsProject.instance().transformContext())
    except Exception as _exc:
        log_swallowed("tools/ai_aoi_summary.py:176 (_safe_distance_area)", _exc)
    try:
        ellps = str(QgsProject.instance().ellipsoid() or "").strip()
        # QGIS returns the literal string "NONE" - not "" - when the project has
        # no ellipsoid set, and "NONE" is truthy, so the previous `if ellps:`
        # test applied it and willUseEllipsoid() stayed False. Substitute a real
        # ellipsoid on a geographic CRS so an ellipsoidal measurement is genuinely
        # performed; a projected CRS keeps honouring whatever the project is
        # configured with. Same remedy as cadastral_overlap_dialog._distance_area
        # and geochem_polygonize_dialog.
        if _is_geographic_crs(crs) and ((not ellps) or ellps.upper() == "NONE"):
            ellps = "WGS84"
            log_message(
                "AI 요약: 프로젝트 타원체가 설정되지 않아(NONE) 지리좌표계 레이어의 "
                "면적/거리 계산에 WGS84 타원체를 대신 사용합니다.",
                level=Qgis.MessageLevel.Warning,
            )
        if ellps:
            da.setEllipsoid(ellps)
    except Exception as _exc:
        log_swallowed("tools/ai_aoi_summary.py:182 (_safe_distance_area)", _exc)
    # Warn once here rather than once per feature: if the substitution did not
    # take (unknown ellipsoid name, older build), every measurement from this
    # measurer is withheld by _measures_in_degrees() at the call sites.
    if _measures_in_degrees(da, crs):
        log_message(
            "AI 요약: 타원체 기준 측정을 설정하지 못해 지리좌표계 레이어의 면적/거리를 "
            "생략합니다(제곱도를 ㎡로 적지 않기 위함).",
            level=Qgis.MessageLevel.Warning,
        )
    return da


def _to_m2(da: QgsDistanceArea, area: float) -> float:
    """Convert a measureArea() result to square metres.

    QgsDistanceArea reports in its own areaUnits(): square metres when an
    ellipsoid is in effect, otherwise the source CRS units squared. Routing every
    value through convertAreaMeasurement() is what makes a ``*_m2`` key mean
    square metres on a feet- or kilometre-based projection as well (same as
    cadastral_overlap_dialog._area_m2). On failure the raw figure is kept, which
    is the pre-conversion behaviour and exact for a metre CRS.
    """
    try:
        return float(da.convertAreaMeasurement(float(area), Qgis.AreaUnit.SquareMeters))
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._to_m2", _exc)
        return float(area)


def _to_m(da: QgsDistanceArea, length: float) -> float:
    """Convert a measureLength()/measureLine() result to metres (see _to_m2)."""
    try:
        return float(da.convertLengthMeasurement(float(length), Qgis.DistanceUnit.Meters))
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._to_m", _exc)
        return float(length)


def _area_m2(da: QgsDistanceArea, geom, crs) -> Optional[float]:
    """Ellipsoidal area in square metres, or None when it would not be metres."""
    if geom is None:
        return None
    try:
        if geom.isEmpty():
            return None
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._area_m2", _exc)
        return None
    if _measures_in_degrees(da, crs):
        return None
    try:
        return _to_m2(da, float(da.measureArea(geom)))
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._area_m2", _exc)
        return None


def _length_m(da: QgsDistanceArea, geom, crs) -> Optional[float]:
    """Ellipsoidal length in metres, or None when it would not be metres."""
    if geom is None:
        return None
    try:
        if geom.isEmpty():
            return None
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._length_m", _exc)
        return None
    if _measures_in_degrees(da, crs):
        return None
    try:
        return _to_m(da, float(da.measureLength(geom)))
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._length_m", _exc)
        return None


def _line_m(da: QgsDistanceArea, p1, p2, crs) -> Optional[float]:
    """Ellipsoidal point-to-point distance in metres, or None when it would not be."""
    if da is None or p1 is None or p2 is None:
        return None
    if _measures_in_degrees(da, crs):
        return None
    try:
        return _to_m(da, float(da.measureLine(p1, p2)))
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._line_m", _exc)
        return None


def _unary_union_geoms(layer: QgsVectorLayer, *, selected_only: bool) -> Tuple[Optional[QgsGeometry], int]:
    geoms = []
    count = 0
    feats = layer.selectedFeatures() if selected_only and layer.selectedFeatureCount() > 0 else layer.getFeatures()
    for f in feats:
        _skip_192 = False
        try:
            g = f.geometry()
        except Exception as _exc:
            log_swallowed("ai_aoi_summary._unary_union_geoms", _exc)
            log_swallowed("tools/ai_aoi_summary.py:194 (_unary_union_geoms)", _exc)
            _skip_192 = True
        if _skip_192:
            continue
        if not g or g.isEmpty():
            continue
        geoms.append(QgsGeometry(g))
        count += 1
    if not geoms:
        return None, 0
    if len(geoms) == 1:
        return geoms[0], count
    try:
        return QgsGeometry.unaryUnion(geoms), count
    except Exception:
        # Fallback: iterative combine
        try:
            out = geoms[0]
            for g in geoms[1:]:
                out = out.combine(g)
            return out, count
        except Exception:
            return None, count


def is_archtoolkit_layer(layer: QgsMapLayer) -> bool:
    """Heuristic: identify layers created by ArchToolkit tools."""
    if layer is None:
        return False
    try:
        meta = get_archtoolkit_layer_metadata(layer)
        if meta and (meta.get("tool_id") or meta.get("run_id")):
            return True
    except Exception as _exc:
        log_swallowed("tools/ai_aoi_summary.py:226 (is_archtoolkit_layer)", _exc)
    try:
        name = str(layer.name() or "")
        if name.startswith("Style:") or name.startswith("AOI_"):
            return True
    except Exception as _exc:
        log_swallowed("tools/ai_aoi_summary.py:232 (is_archtoolkit_layer)", _exc)
    try:
        src = str(layer.source() or "")
        src_l = src.lower()
        if "archtoolkit_" in src_l or "archt_" in src_l or "archtoolkit" in src_l:
            return True
    except Exception as _exc:
        log_swallowed("tools/ai_aoi_summary.py:239 (is_archtoolkit_layer)", _exc)
    try:
        # Cost tool tags
        if layer.customProperty("archtoolkit/cost_surface/run_id", None) is not None:
            return True
    except Exception as _exc:
        log_swallowed("tools/ai_aoi_summary.py:245 (is_archtoolkit_layer)", _exc)
    try:
        # Many tools place outputs under an "ArchToolkit - ..." layer tree group.
        root = QgsProject.instance().layerTreeRoot()
        node = root.findLayer(layer.id())
        cur = node.parent() if node is not None else None
        while cur is not None and cur != root:
            try:
                if str(cur.name() or "").startswith("ArchToolkit -"):
                    return True
            except Exception as _exc:
                log_swallowed("tools/ai_aoi_summary.py:256 (is_archtoolkit_layer)", _exc)
            try:
                cur = cur.parent()
            except Exception:
                break
    except Exception as _exc:
        log_swallowed("ai_aoi_summary.is_archtoolkit_layer", _exc)
    return False


def _layer_archtoolkit_meta(layer: QgsMapLayer) -> Dict[str, Any]:
    """Return ArchToolkit metadata dict for this layer (best-effort)."""
    if layer is None:
        return {}
    try:
        meta = get_archtoolkit_layer_metadata(layer) or {}
        if meta:
            return meta
    except Exception:
        meta = {}

    # Backward-compat: older builds tagged cost surface layers under a different key.
    try:
        rid = layer.customProperty("archtoolkit/cost_surface/run_id", None)
        if rid:
            out = {"tool_id": "cost_surface", "run_id": str(rid)}
            k = layer.customProperty("archtoolkit/cost_surface/kind", None)
            if k:
                out["kind"] = str(k)
            return out
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._layer_archtoolkit_meta", _exc)
    return {}


def _layer_group_path(layer_id: str) -> str:
    """Return a best-effort layer tree path 'Group/Sub/Layer'."""
    try:
        root = QgsProject.instance().layerTreeRoot()
        node = root.findLayer(layer_id)
        if node is None:
            return ""
        parts = []
        cur = node
        while cur is not None:
            try:
                if cur.name():
                    parts.append(cur.name())
            except Exception as _exc:
                log_swallowed("tools/ai_aoi_summary.py:305 (_layer_group_path)", _exc)
            cur = cur.parent()
            if cur == root:
                break
        parts.reverse()
        return "/".join(parts)
    except Exception:
        return ""


def _transform_geom(geom: QgsGeometry, src_crs, dst_crs) -> Optional[QgsGeometry]:
    if geom is None or geom.isEmpty():
        return None
    try:
        if src_crs == dst_crs:
            return QgsGeometry(geom)
    except Exception as _exc:
        log_swallowed("tools/ai_aoi_summary.py:322 (_transform_geom)", _exc)
    try:
        tr = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
    except Exception:
        return None
    out = QgsGeometry(geom)
    try:
        out.transform(tr)
    except Exception:
        return None
    if out.isEmpty():
        return None
    return out


def _vector_layer_stats_in_geom(
    layer: QgsVectorLayer,
    geom: QgsGeometry,
    *,
    max_features_scan: int = 20000,
    origin_point: Optional[QgsPointXY] = None,
    origin_crs=None,
    tool_id: str = "",
) -> Dict[str, Any]:
    out: Dict[str, Any] = {"features": 0}
    if layer is None or geom is None or geom.isEmpty():
        return out

    layer_crs = layer.crs()
    da = _safe_distance_area(layer_crs)
    # Withhold the *_m / *_m2 totals outright when they would be degrees: writing
    # 0.0 into `total_length_m` reads as "no line features inside the AOI", which
    # is a different wrong answer, and the figure is also sent to the LLM.
    metric_totals = not _measures_in_degrees(da, layer_crs)
    da_origin = _safe_distance_area(origin_crs) if origin_point is not None and origin_crs is not None else None
    ct_to_origin = None
    if da_origin is not None:
        try:
            if layer.crs() != origin_crs:
                ct_to_origin = QgsCoordinateTransform(layer.crs(), origin_crs, QgsProject.instance())
        except Exception:
            ct_to_origin = None

    bbox: QgsRectangle = geom.boundingBox()
    req = QgsFeatureRequest().setFilterRect(bbox)

    geom_type = layer.geometryType()
    total_len = 0.0
    total_area = 0.0
    n = 0
    scanned = 0

    # Auto-select fields by actual type (numeric stats + one categorical column),
    # including Korean category fields - not just a fixed English name whitelist.
    num_fields, hist_field, num_dropped = _classify_fields(layer, tool_id=tool_id)
    hist = {} if hist_field else None

    num_acc: Dict[str, Dict[str, Any]] = {}
    # Unconvertible (non-null) values are counted per field and reported once
    # after the scan. Logging each one ran a file append per feature per field
    # - 200k features x a text column named like a number was 200k appends on
    # the GUI thread and a flooded UI log queue.
    convert_failures: Dict[str, int] = {}
    for f in num_fields:
        num_acc[str(f)] = {"sum": 0.0, "min": float("inf"), "max": float("-inf"), "n": 0}

    dist_acc = None
    if geom_type == Qgis.GeometryType.Point and da_origin is not None and origin_point is not None:
        dist_acc = {"sum": 0.0, "min": float("inf"), "max": float("-inf"), "n": 0}

    scan_cap = int(max_features_scan)
    truncated = False
    for feat in layer.getFeatures(req):
        # Test the cap BEFORE counting so `scanned` reports the number actually
        # examined (it used to read cap+1 when the cap fired).
        if scanned >= scan_cap:
            truncated = True
            break
        scanned += 1
        _skip_391 = False
        try:
            g = feat.geometry()
        except Exception as _exc:
            log_swallowed("ai_aoi_summary._vector_layer_stats_in_geom", _exc)
            log_swallowed("tools/ai_aoi_summary.py:393 (_vector_layer_stats_in_geom)", _exc)
            _skip_391 = True
        if _skip_391:
            continue
        if not g or g.isEmpty():
            continue
        _skip_398 = False
        try:
            if not g.intersects(geom):
                continue
        except Exception as _exc:
            log_swallowed("ai_aoi_summary._vector_layer_stats_in_geom", _exc)
            log_swallowed("tools/ai_aoi_summary.py:401 (_vector_layer_stats_in_geom)", _exc)
            _skip_398 = True
        if _skip_398:
            continue

        n += 1
        if geom_type == Qgis.GeometryType.Line:
            try:
                _len = _length_m(da, g.intersection(geom), layer_crs)
                if _len is not None:
                    total_len += _len
            except Exception as _exc:
                log_swallowed("ai_aoi_summary._vector_layer_stats_in_geom", _exc)
        elif geom_type == Qgis.GeometryType.Polygon:
            try:
                _area = _area_m2(da, g.intersection(geom), layer_crs)
                if _area is not None:
                    total_area += _area
            except Exception as _exc:
                log_swallowed("ai_aoi_summary._vector_layer_stats_in_geom", _exc)

        if hist is not None and hist_field is not None:
            try:
                v = feat[hist_field]
                k = "(null)" if is_null_value(v) else str(v)
                hist[k] = int(hist.get(k, 0)) + 1
            except Exception as _exc:
                log_swallowed("ai_aoi_summary._vector_layer_stats_in_geom", _exc)

        for f, acc in num_acc.items():
            _skip_426 = False
            try:
                v = feat[f]
                # PyQGIS hands back NULL (not None) for a null attribute, and
                # float(NULL) raises - which was being logged once per null
                # cell of every scanned feature. Nulls are data, not failures.
                if is_null_value(v):
                    continue
                x = float(v)
                if not math.isfinite(x):
                    continue
                acc["sum"] = float(acc["sum"]) + float(x)
                acc["min"] = float(min(float(acc["min"]), float(x)))
                acc["max"] = float(max(float(acc["max"]), float(x)))
                acc["n"] = int(acc["n"]) + 1
            except Exception as _exc:
                convert_failures[str(f)] = convert_failures.get(str(f), 0) + 1
                log_swallowed("tools/ai_aoi_summary.py:440 (_vector_layer_stats_in_geom)", _exc)
                _skip_426 = True
            if _skip_426:
                continue

        if dist_acc is not None:
            try:
                pt = g.centroid().asPoint()
                pt_xy = QgsPointXY(pt)
                if ct_to_origin is not None:
                    pt_xy = ct_to_origin.transform(pt_xy)
                dist = _line_m(da_origin, origin_point, pt_xy, origin_crs)
                if dist is not None and math.isfinite(dist):
                    dist_acc["sum"] = float(dist_acc["sum"]) + dist
                    dist_acc["min"] = float(min(float(dist_acc["min"]), dist))
                    dist_acc["max"] = float(max(float(dist_acc["max"]), dist))
                    dist_acc["n"] = int(dist_acc["n"]) + 1
            except Exception as _exc:
                log_swallowed("ai_aoi_summary._vector_layer_stats_in_geom", _exc)

    out["features"] = int(n)
    out["scanned"] = int(scanned)
    out["scan_cap"] = int(scan_cap)
    # Written explicitly (not only when true) so a reader of context.json/CSV
    # can tell "complete" from "flag never written".
    out["truncated"] = bool(truncated)
    out["numeric_fields_truncated"] = int(num_dropped)
    if truncated:
        # Everything below is a partial figure over the first `scan_cap`
        # features in provider order. Name the cap and, when the provider can
        # answer cheaply, the layer's full feature count as the denominator.
        try:
            fc = int(layer.featureCount())
            if fc >= 0:
                out["layer_feature_count"] = fc
        except Exception as _exc:
            log_swallowed("ai_aoi_summary._vector_layer_stats_in_geom", _exc)
        try:
            log_message(
                f"AI 요약: 레이어 '{layer.name()}' 피처 스캔 한도({scan_cap:,}개)에 도달했습니다. "
                "피처 수/총 길이/총 면적/필드 통계는 부분값입니다.",
                level=Qgis.MessageLevel.Warning,
            )
        except Exception as _exc:
            log_swallowed("ai_aoi_summary._vector_layer_stats_in_geom", _exc)
    if geom_type == Qgis.GeometryType.Line and metric_totals:
        out["total_length_m"] = float(total_len)
    if geom_type == Qgis.GeometryType.Polygon and metric_totals:
        out["total_area_m2"] = float(total_area)
    if hist is not None:
        # keep top 20
        items = sorted(hist.items(), key=lambda kv: kv[1], reverse=True)[:20]
        out["top_values"] = [{"value": k, "count": int(v)} for k, v in items]
        out["top_field"] = hist_field

    numeric_out = {}
    for field_name, count in convert_failures.items():
        log_swallowed(
            "ai_aoi_summary._vector_layer_stats_in_geom",
            ValueError(f"field '{field_name}': {count} value(s) not numeric; skipped"),
        )
    for f, acc in num_acc.items():
        _skip_478 = False
        try:
            n0 = int(acc.get("n") or 0)
            if n0 <= 0:
                continue
            s0 = float(acc.get("sum") or 0.0)
            numeric_out[f] = {
                "n": n0,
                "min": float(acc.get("min")),
                "max": float(acc.get("max")),
                "mean": float(s0 / float(n0)),
            }
        except Exception as _exc:
            log_swallowed("ai_aoi_summary._vector_layer_stats_in_geom", _exc)
            log_swallowed("tools/ai_aoi_summary.py:489 (_vector_layer_stats_in_geom)", _exc)
            _skip_478 = True
        if _skip_478:
            continue
    if numeric_out:
        out["numeric_fields"] = numeric_out

    if dist_acc is not None:
        try:
            dn = int(dist_acc.get("n") or 0)
            if dn > 0:
                ds = float(dist_acc.get("sum") or 0.0)
                out["dist_to_aoi_centroid_m"] = {
                    "n": dn,
                    "min": float(dist_acc.get("min")),
                    "max": float(dist_acc.get("max")),
                    "mean": float(ds / float(dn)),
                }
        except Exception as _exc:
            log_swallowed("ai_aoi_summary._vector_layer_stats_in_geom", _exc)
    return out


def _pick_reference_name_field(layer: QgsVectorLayer, preferred: str = "") -> str:
    if layer is None or not isinstance(layer, QgsVectorLayer):
        return ""
    pref = str(preferred or "").strip()
    try:
        if pref and layer.fields().indexFromName(pref) >= 0:
            return pref
    except Exception as _exc:
        log_swallowed("tools/ai_aoi_summary.py:518 (_pick_reference_name_field)", _exc)

    try:
        fields = [f.name() for f in layer.fields()]
    except Exception:
        fields = []
    if not fields:
        return ""

    want = (
        "name",
        "site_name",
        "title",
        "label",
        "유적명",
        "명칭",
        "문화재명",
        "대상명",
        "지명",
    )
    lower_map = {str(n).lower(): str(n) for n in fields}
    for cand in want:
        key = str(cand).lower()
        if key in lower_map:
            return lower_map[key]

    try:
        for f in layer.fields():
            if int(f.type()) == int(FT_STRING):
                return str(f.name() or "")
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._pick_reference_name_field", _exc)
    return ""


def _feature_ref_name(feature, *, name_field: str) -> str:
    if feature is None:
        return ""
    try:
        if name_field:
            v = feature[name_field]
            if v is not None:
                s = str(v).strip()
                if s:
                    return s
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._feature_ref_name", _exc)
    try:
        return f"FID {int(feature.id())}"
    except Exception:
        return "feature"


def _extract_representative_point(geom: QgsGeometry) -> Optional[QgsPointXY]:
    if geom is None or geom.isEmpty():
        return None
    try:
        if geom.type() == Qgis.GeometryType.Point:
            if geom.isMultipart():
                pts = geom.asMultiPoint()
                if pts:
                    return QgsPointXY(pts[0])
            else:
                return QgsPointXY(geom.asPoint())
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._extract_representative_point", _exc)

    try:
        p = geom.pointOnSurface()
        if p is not None and (not p.isEmpty()):
            return QgsPointXY(p.asPoint())
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._extract_representative_point", _exc)
    try:
        c = geom.centroid()
        if c is not None and (not c.isEmpty()):
            return QgsPointXY(c.asPoint())
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._extract_representative_point", _exc)
    return None


def _reference_sites_summary(
    *,
    layer: QgsVectorLayer,
    aoi_geom: QgsGeometry,
    buffer_geom: QgsGeometry,
    aoi_centroid_pt: Optional[QgsPointXY],
    aoi_crs,
    selected_only: bool,
    preferred_name_field: str = "",
    max_features: int = 120,
) -> Optional[Dict[str, Any]]:
    if layer is None or not isinstance(layer, QgsVectorLayer):
        return None
    if aoi_geom is None or aoi_geom.isEmpty() or buffer_geom is None or buffer_geom.isEmpty():
        return None

    try:
        g_aoi_on_layer = _transform_geom(aoi_geom, aoi_crs, layer.crs())
        g_buf_on_layer = _transform_geom(buffer_geom, aoi_crs, layer.crs())
    except Exception:
        g_aoi_on_layer = None
        g_buf_on_layer = None
    if g_aoi_on_layer is None or g_aoi_on_layer.isEmpty() or g_buf_on_layer is None or g_buf_on_layer.isEmpty():
        return None

    # Small bbox pre-filter in source CRS.
    try:
        req = QgsFeatureRequest().setFilterRect(g_buf_on_layer.boundingBox())
    except Exception:
        req = QgsFeatureRequest()

    selected_count = 0
    try:
        if selected_only:
            selected_count = int(layer.selectedFeatureCount())
            if selected_count > 0:
                features = layer.selectedFeatures()
            else:
                # Respect "selected only": empty selection means empty result.
                features = []
        else:
            features = layer.getFeatures(req)
    except Exception:
        try:
            features = layer.getFeatures(req) if not selected_only else []
        except Exception:
            features = []

    max_items = int(max(1, min(int(max_features), 2000)))
    max_scan = int(max(max_items * 20, 500))

    name_field = _pick_reference_name_field(layer, preferred=preferred_name_field)
    da = _safe_distance_area(aoi_crs)

    scanned = 0
    classified = 0
    scan_truncated = False
    counts = {
        "inside_or_overlap_aoi": 0,
        "inside_buffer_only": 0,
        "outside_buffer": 0,
        "inside_aoi": 0,
        "crosses_aoi_boundary": 0,
        "crosses_buffer_boundary": 0,
    }

    # Two passes. Pass 1 walks every feature up to max_scan and computes only
    # the cheap discriminators (relation class, distance to AOI/buffer) and
    # tallies `counts` over ALL of them; it keeps the nearest max_items in a
    # bounded max-heap keyed on distance so memory stays O(max_items). Pass 2
    # computes the expensive per-item fields (bearing, area/length splits) for
    # those nearest items only. Previously the loop stopped at max_items in
    # provider (FID) order and sorted afterwards, so the "nearest site" and the
    # classification counts came from an arbitrary subset of the sites in range.
    heap: List[Tuple[float, int, Dict[str, Any]]] = []

    for ft in features:
        if scanned >= max_scan:
            scan_truncated = True
            break
        scanned += 1

        _skip_672 = False
        try:
            g0 = ft.geometry()
        except Exception as _exc:
            log_swallowed("ai_aoi_summary._reference_sites_summary", _exc)
            log_swallowed("tools/ai_aoi_summary.py:674 (_reference_sites_summary)", _exc)
            _skip_672 = True
        if _skip_672:
            continue
        if g0 is None or g0.isEmpty():
            continue

        if not selected_only:
            try:
                if not g0.intersects(g_buf_on_layer):
                    # When not using explicit selection, keep the scan focused around AOI.
                    continue
            except Exception as _exc:
                log_swallowed("ai_aoi_summary._reference_sites_summary", _exc)

        g = _transform_geom(g0, layer.crs(), aoi_crs)
        if g is None or g.isEmpty():
            continue

        try:
            intersects_aoi = bool(g.intersects(aoi_geom))
        except Exception:
            intersects_aoi = False
        try:
            within_aoi = bool(g.within(aoi_geom))
        except Exception:
            within_aoi = False
        try:
            intersects_buf = bool(g.intersects(buffer_geom))
        except Exception:
            intersects_buf = False
        try:
            within_buf = bool(g.within(buffer_geom))
        except Exception:
            within_buf = False

        crosses_aoi_boundary = bool(intersects_aoi and (not within_aoi))
        crosses_buffer_boundary = bool(intersects_buf and (not within_buf))

        if within_aoi:
            relation = "inside_aoi"
            counts["inside_aoi"] += 1
            counts["inside_or_overlap_aoi"] += 1
        elif intersects_aoi:
            relation = "crosses_aoi_boundary"
            counts["crosses_aoi_boundary"] += 1
            counts["inside_or_overlap_aoi"] += 1
        elif within_buf:
            relation = "inside_buffer_only"
            counts["inside_buffer_only"] += 1
        elif intersects_buf:
            relation = "crosses_buffer_boundary"
            counts["crosses_buffer_boundary"] += 1
        else:
            relation = "outside_buffer"
            counts["outside_buffer"] += 1
        classified += 1

        try:
            dist_to_aoi = 0.0 if intersects_aoi else float(g.distance(aoi_geom))
            if not math.isfinite(dist_to_aoi):
                dist_to_aoi = None
        except Exception:
            dist_to_aoi = None
        try:
            dist_to_buffer = 0.0 if intersects_buf else float(g.distance(buffer_geom))
            if not math.isfinite(dist_to_buffer):
                dist_to_buffer = None
        except Exception:
            dist_to_buffer = None

        rec: Dict[str, Any] = {
            "ft": ft,
            "g": g,
            "relation": relation,
            "intersects_aoi": intersects_aoi,
            "within_aoi": within_aoi,
            "intersects_buf": intersects_buf,
            "within_buf": within_buf,
            "crosses_aoi_boundary": crosses_aoi_boundary,
            "crosses_buffer_boundary": crosses_buffer_boundary,
            "dist_to_aoi": dist_to_aoi,
            "dist_to_buffer": dist_to_buffer,
        }
        # Negated distance -> max-heap; the unique sequence number breaks ties
        # so the dict is never compared. heappushpop evicts the farthest.
        sort_key = float(dist_to_aoi) if dist_to_aoi is not None else float("inf")
        entry = (-sort_key, -classified, rec)
        if len(heap) < max_items:
            heapq.heappush(heap, entry)
        else:
            heapq.heappushpop(heap, entry)

    if scan_truncated:
        try:
            log_message(
                f"AI 요약: 추가 유적 레이어 '{layer.name()}' 스캔 한도({max_scan:,}개)에 도달했습니다. "
                "분류 집계와 '가장 가까운 유적'은 스캔된 범위 내의 값입니다.",
                level=Qgis.MessageLevel.Warning,
            )
        except Exception as _exc:
            log_swallowed("ai_aoi_summary._reference_sites_summary", _exc)

    nearest = [entry[2] for entry in heap]
    for rec in nearest:
        rec["name"] = _feature_ref_name(rec["ft"], name_field=name_field)
    try:
        nearest.sort(
            key=lambda r: (
                float(r["dist_to_aoi"]) if r.get("dist_to_aoi") is not None else float("inf"),
                str(r.get("name") or ""),
            )
        )
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._reference_sites_summary", _exc)

    items: List[Dict[str, Any]] = []
    for rec in nearest:
        ft = rec["ft"]
        g = rec["g"]
        intersects_aoi = bool(rec["intersects_aoi"])
        within_aoi = bool(rec["within_aoi"])
        intersects_buf = bool(rec["intersects_buf"])
        within_buf = bool(rec["within_buf"])

        dist_to_centroid = None
        bearing_from_aoi_deg = None
        compass_from_aoi = None
        if aoi_centroid_pt is not None:
            try:
                rp = _extract_representative_point(g)
                if rp is not None:
                    d0 = _line_m(da, aoi_centroid_pt, rp, aoi_crs)
                    if d0 is not None and math.isfinite(d0):
                        dist_to_centroid = d0
                    # Compass bearing AOI-centroid -> site (both in projected AOI CRS).
                    dx = float(rp.x()) - float(aoi_centroid_pt.x())
                    dy = float(rp.y()) - float(aoi_centroid_pt.y())
                    if abs(dx) > 1e-9 or abs(dy) > 1e-9:
                        b = math.degrees(math.atan2(dx, dy)) % 360.0
                        bearing_from_aoi_deg = float(b)
                        compass_from_aoi = _compass8_ko(b)
            except Exception:
                dist_to_centroid = None

        feature_area_m2 = None
        overlap_aoi_area_m2 = None
        overlap_buffer_area_m2 = None
        outside_aoi_area_m2 = None
        outside_buffer_area_m2 = None
        inside_aoi_area_pct = None
        outside_aoi_area_pct = None
        inside_buffer_area_pct = None
        outside_buffer_area_pct = None

        feature_length_m = None
        overlap_aoi_length_m = None
        overlap_buffer_length_m = None
        outside_aoi_length_m = None
        outside_buffer_length_m = None
        inside_aoi_length_pct = None
        outside_aoi_length_pct = None
        inside_buffer_length_pct = None
        outside_buffer_length_pct = None
        try:
            gt = int(g.type())
        except Exception:
            gt = -1
        if gt == int(Qgis.GeometryType.Polygon):
            try:
                feature_area_m2 = _area_m2(da, g, aoi_crs)
            except Exception:
                feature_area_m2 = None
            try:
                inter = g.intersection(aoi_geom)
                if inter is not None and (not inter.isEmpty()):
                    overlap_aoi_area_m2 = _area_m2(da, inter, aoi_crs)
            except Exception:
                overlap_aoi_area_m2 = None
            try:
                interb = g.intersection(buffer_geom)
                if interb is not None and (not interb.isEmpty()):
                    overlap_buffer_area_m2 = _area_m2(da, interb, aoi_crs)
            except Exception:
                overlap_buffer_area_m2 = None

            try:
                if feature_area_m2 is not None and feature_area_m2 > 0:
                    in_aoi = float(overlap_aoi_area_m2 or 0.0)
                    in_buf = float(overlap_buffer_area_m2 or 0.0)
                    outside_aoi_area_m2 = max(0.0, float(feature_area_m2) - in_aoi)
                    outside_buffer_area_m2 = max(0.0, float(feature_area_m2) - in_buf)
                    inside_aoi_area_pct = max(0.0, min(100.0, (in_aoi / float(feature_area_m2)) * 100.0))
                    outside_aoi_area_pct = max(0.0, min(100.0, (outside_aoi_area_m2 / float(feature_area_m2)) * 100.0))
                    inside_buffer_area_pct = max(0.0, min(100.0, (in_buf / float(feature_area_m2)) * 100.0))
                    outside_buffer_area_pct = max(0.0, min(100.0, (outside_buffer_area_m2 / float(feature_area_m2)) * 100.0))
            except Exception as _exc:
                log_swallowed("ai_aoi_summary._reference_sites_summary", _exc)
        elif gt == int(Qgis.GeometryType.Line):
            try:
                feature_length_m = _length_m(da, g, aoi_crs)
            except Exception:
                feature_length_m = None
            try:
                inter = g.intersection(aoi_geom)
                if inter is not None and (not inter.isEmpty()):
                    overlap_aoi_length_m = _length_m(da, inter, aoi_crs)
            except Exception:
                overlap_aoi_length_m = None
            try:
                interb = g.intersection(buffer_geom)
                if interb is not None and (not interb.isEmpty()):
                    overlap_buffer_length_m = _length_m(da, interb, aoi_crs)
            except Exception:
                overlap_buffer_length_m = None

            try:
                if feature_length_m is not None and feature_length_m > 0:
                    in_aoi_l = float(overlap_aoi_length_m or 0.0)
                    in_buf_l = float(overlap_buffer_length_m or 0.0)
                    outside_aoi_length_m = max(0.0, float(feature_length_m) - in_aoi_l)
                    outside_buffer_length_m = max(0.0, float(feature_length_m) - in_buf_l)
                    inside_aoi_length_pct = max(0.0, min(100.0, (in_aoi_l / float(feature_length_m)) * 100.0))
                    outside_aoi_length_pct = max(0.0, min(100.0, (outside_aoi_length_m / float(feature_length_m)) * 100.0))
                    inside_buffer_length_pct = max(0.0, min(100.0, (in_buf_l / float(feature_length_m)) * 100.0))
                    outside_buffer_length_pct = max(0.0, min(100.0, (outside_buffer_length_m / float(feature_length_m)) * 100.0))
            except Exception as _exc:
                log_swallowed("ai_aoi_summary._reference_sites_summary", _exc)

        item = {
            "fid": int(ft.id()) if hasattr(ft, "id") else None,
            "name": str(rec.get("name") or ""),
            "relation": str(rec["relation"]),
            "crosses_aoi_boundary": bool(rec["crosses_aoi_boundary"]),
            "crosses_buffer_boundary": bool(rec["crosses_buffer_boundary"]),
            "inside_or_overlap_aoi": bool(intersects_aoi or within_aoi),
            "inside_or_overlap_buffer": bool(intersects_buf or within_buf),
            "distance_to_aoi_m": rec["dist_to_aoi"],
            "distance_to_buffer_m": rec["dist_to_buffer"],
            "distance_to_aoi_centroid_m": dist_to_centroid,
            "bearing_from_aoi_deg": bearing_from_aoi_deg,
            "compass_from_aoi": compass_from_aoi,
        }
        try:
            item["wkb"] = QgsWkbTypes.displayString(layer.wkbType())
        except Exception as _exc:
            log_swallowed("tools/ai_aoi_summary.py:863 (_reference_sites_summary)", _exc)
        if overlap_aoi_area_m2 is not None:
            item["overlap_aoi_area_m2"] = overlap_aoi_area_m2
        if overlap_buffer_area_m2 is not None:
            item["overlap_buffer_area_m2"] = overlap_buffer_area_m2
        if feature_area_m2 is not None:
            item["feature_area_m2"] = feature_area_m2
        if outside_aoi_area_m2 is not None:
            item["outside_aoi_area_m2"] = outside_aoi_area_m2
        if outside_buffer_area_m2 is not None:
            item["outside_buffer_area_m2"] = outside_buffer_area_m2
        if inside_aoi_area_pct is not None:
            item["inside_aoi_area_pct"] = inside_aoi_area_pct
        if outside_aoi_area_pct is not None:
            item["outside_aoi_area_pct"] = outside_aoi_area_pct
        if inside_buffer_area_pct is not None:
            item["inside_buffer_area_pct"] = inside_buffer_area_pct
        if outside_buffer_area_pct is not None:
            item["outside_buffer_area_pct"] = outside_buffer_area_pct
        if overlap_aoi_length_m is not None:
            item["overlap_aoi_length_m"] = overlap_aoi_length_m
        if overlap_buffer_length_m is not None:
            item["overlap_buffer_length_m"] = overlap_buffer_length_m
        if feature_length_m is not None:
            item["feature_length_m"] = feature_length_m
        if outside_aoi_length_m is not None:
            item["outside_aoi_length_m"] = outside_aoi_length_m
        if outside_buffer_length_m is not None:
            item["outside_buffer_length_m"] = outside_buffer_length_m
        if inside_aoi_length_pct is not None:
            item["inside_aoi_length_pct"] = inside_aoi_length_pct
        if outside_aoi_length_pct is not None:
            item["outside_aoi_length_pct"] = outside_aoi_length_pct
        if inside_buffer_length_pct is not None:
            item["inside_buffer_length_pct"] = inside_buffer_length_pct
        if outside_buffer_length_pct is not None:
            item["outside_buffer_length_pct"] = outside_buffer_length_pct

        items.append(item)

    kept = len(items)

    return {
        "layer_id": str(layer.id() or ""),
        "layer_name": str(layer.name() or ""),
        "selected_only": bool(selected_only),
        "selected_feature_count": int(selected_count),
        "name_field": str(name_field or ""),
        "feature_count": int(kept),
        # Sites the relation classes/counts were tallied over (all scanned in
        # range), as opposed to feature_count = items detailed below.
        "classified_count": int(classified),
        "scanned": int(scanned),
        "scan_cap": int(max_scan),
        # scan_truncated: the scan itself stopped at scan_cap, so counts and the
        # nearest site are relative to the scanned subset. truncated: only the
        # item list is cut (counts remain complete over everything scanned).
        "scan_truncated": bool(scan_truncated),
        "counts": counts,
        "items": items,
        "max_features": int(max_items),
        "truncated": bool(classified > kept),
    }


def _raster_stats_in_geom(
    raster_path: str,
    geom: QgsGeometry,
    *,
    max_pixels: int = 4_000_000,  # cap for memory safety
) -> Optional[Dict[str, Any]]:
    if np is None or gdal is None or ogr is None:
        return None
    if not raster_path or not os.path.exists(str(raster_path)):
        return None
    if geom is None or geom.isEmpty():
        return None

    ds = gdal.Open(str(raster_path), gdal.GA_ReadOnly)
    if ds is None:
        return None
    band = ds.GetRasterBand(1)
    if band is None:
        ds = None
        return None

    gt = ds.GetGeoTransform()
    proj = ds.GetProjection() or ""
    nodata = band.GetNoDataValue()

    try:
        inv_gt = gdal.InvGeoTransform(gt)
        if isinstance(inv_gt, tuple) and len(inv_gt) == 2:
            ok, inv_gt = inv_gt
            if not ok:
                ds = None
                return None
    except Exception:
        ds = None
        return None

    bbox = geom.boundingBox()
    try:
        px0, py0 = gdal.ApplyGeoTransform(inv_gt, float(bbox.xMinimum()), float(bbox.yMaximum()))
        px1, py1 = gdal.ApplyGeoTransform(inv_gt, float(bbox.xMaximum()), float(bbox.yMinimum()))
    except Exception:
        ds = None
        return None

    x0 = int(math.floor(min(px0, px1)))
    x1 = int(math.ceil(max(px0, px1)))
    y0 = int(math.floor(min(py0, py1)))
    y1 = int(math.ceil(max(py0, py1)))

    x0 = max(0, min(ds.RasterXSize - 1, x0))
    y0 = max(0, min(ds.RasterYSize - 1, y0))
    x1 = max(0, min(ds.RasterXSize, x1))
    y1 = max(0, min(ds.RasterYSize, y1))

    w = int(max(1, x1 - x0))
    h = int(max(1, y1 - y0))
    if w <= 0 or h <= 0:
        ds = None
        return None

    # Downsample DURING the read via buf_xsize/buf_ysize so GDAL never allocates
    # the full native-resolution window. A large AOI over a high-res DEM could be
    # tens of millions of pixels (hundreds of MB to GBs) if read at full size.
    bw, bh = int(w), int(h)
    try:
        if int(w) * int(h) > int(max_pixels):
            scale = math.sqrt((float(w) * float(h)) / float(max_pixels))
            if scale > 1.0:
                bw = max(1, int(math.floor(float(w) / scale)))
                bh = max(1, int(math.floor(float(h) / scale)))
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._raster_stats_in_geom", _exc)
        bw, bh = int(w), int(h)

    try:
        arr = band.ReadAsArray(x0, y0, w, h, buf_xsize=bw, buf_ysize=bh)
    except Exception:
        ds = None
        return None

    if arr is None:
        ds = None
        return None

    try:
        arr = arr.astype(np.float32, copy=False)
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._raster_stats_in_geom", _exc)

    # Rasterize polygon mask into the same (possibly downsampled) window. The
    # pixel size scales by w/read_width so the mask aligns with the read buffer.
    try:
        rw = int(arr.shape[1]) if arr.ndim >= 2 else int(bw)
        rh = int(arr.shape[0]) if arr.ndim >= 2 else int(bh)
        sx = float(w) / float(rw) if rw > 0 else 1.0
        sy = float(h) / float(rh) if rh > 0 else 1.0
        win_gt = (
            gt[0] + x0 * gt[1] + y0 * gt[2],
            gt[1] * sx,
            gt[2] * sy,
            gt[3] + x0 * gt[4] + y0 * gt[5],
            gt[4] * sx,
            gt[5] * sy,
        )

        rdrv = gdal.GetDriverByName("MEM")
        mds = rdrv.Create("", int(arr.shape[1]), int(arr.shape[0]), 1, gdal.GDT_Byte)
        if mds is None:
            ds = None
            return None
        mds.SetGeoTransform(win_gt)
        mds.SetProjection(str(proj))
        mband = mds.GetRasterBand(1)
        mband.Fill(0)
        mband.SetNoDataValue(0)

        ogr_geom = ogr.CreateGeometryFromWkb(bytes(geom.asWkb()))
        vdrv = ogr.GetDriverByName("Memory")
        vds = vdrv.CreateDataSource("")
        vlyr = vds.CreateLayer("mask", None, ogr.wkbUnknown)
        feat_defn = vlyr.GetLayerDefn()
        feat = ogr.Feature(feat_defn)
        feat.SetGeometry(ogr_geom)
        vlyr.CreateFeature(feat)

        gdal.RasterizeLayer(mds, [1], vlyr, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
        mask = mband.ReadAsArray()
        if mask is None:
            ds = None
            return None
        mask = mask != 0
    except Exception:
        ds = None
        return None

    ds = None

    # Record whether the read was decimated (GDAL nearest-neighbour via the
    # smaller buffer): every (step x step) block then contributes one sample,
    # so `count` is a sample count and min/max are sample extrema, biased inward.
    window_px = int(w) * int(h)
    try:
        read_px = int(arr.shape[0]) * int(arr.shape[1]) if arr.ndim >= 2 else int(arr.size)
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._raster_stats_in_geom", _exc)
        read_px = int(bw) * int(bh)
    sampled = bool(read_px > 0 and read_px < window_px)
    sample_step = 1.0
    if sampled:
        try:
            sample_step = float(round(math.sqrt(float(window_px) / float(read_px)), 3))
        except Exception as _exc:
            log_swallowed("ai_aoi_summary._raster_stats_in_geom", _exc)
            sample_step = 1.0

    valid = mask & np.isfinite(arr)
    if nodata is not None:
        try:
            valid &= arr != float(nodata)
        except Exception as _exc:
            log_swallowed("ai_aoi_summary._raster_stats_in_geom", _exc)

    if not np.any(valid):
        return None

    vals = arr[valid]
    try:
        out = {
            "count": int(vals.size),
            "min": float(np.nanmin(vals)),
            "max": float(np.nanmax(vals)),
            "mean": float(np.nanmean(vals)),
            "sampled": bool(sampled),
            "sample_step": float(sample_step),
            "window_px": int(window_px),
        }
        # Binary mask hint (e.g. viewshed/corridor): only when the sample holds
        # EXACTLY two distinct valid values. The old ">= 98 % of cells are 0 or
        # max" gate also admitted three-class rasters (the viewshed asymmetry
        # coding 0/1/2) and zero-padded continuous rasters.
        try:
            sample = vals
            if int(sample.size) > 200_000:
                step0 = int(max(1, sample.size // 200_000))
                sample = sample[::step0]
            vmin = float(out.get("min"))
            vmax = float(out.get("max"))
            if math.isfinite(vmin) and math.isfinite(vmax) and vmax > 0 and vmin >= -1e-6 and sample.size > 0:
                uniq = np.unique(sample)
                if int(uniq.size) == 2:
                    lo = float(uniq[0])
                    hi = float(uniq[1])
                    # Threshold relative to the detected values (their midpoint,
                    # i.e. vmax/2 for a 0/high mask) rather than an absolute 0.5:
                    # a weighted viewshed coded {0, 0.35} used to report 0 %.
                    thr = (lo + hi) / 2.0
                    pct = float(np.count_nonzero(vals > thr)) / float(vals.size) * 100.0
                    out["high_value_pct"] = float(pct)
                    out["high_value"] = float(hi)
                    out["low_value"] = float(lo)
                    out["high_value_threshold"] = float(thr)
                    # Legacy key kept for readers of older context.json/CSV (same
                    # number; the keys above describe what it now measures).
                    out["gt_0_5_pct"] = float(pct)
        except Exception as _exc:
            log_swallowed("ai_aoi_summary._raster_stats_in_geom", _exc)
        return out
    except Exception:
        return None


def _project_layers_in_tree_order() -> List[QgsMapLayer]:
    """Project layers in layer-tree (panel) order, then any not in the tree.

    mapLayers() iterates in layer-id key order, which is alphabetical by
    generated id and unrelated to the panel, so which layers survived the
    max_layers cap was arbitrary. Tree order is what the user sees.
    """
    ordered: List[QgsMapLayer] = []
    seen = set()
    try:
        root = QgsProject.instance().layerTreeRoot()
        for node in root.findLayers():
            try:
                lyr = node.layer()
            except Exception as _exc:
                log_swallowed("ai_aoi_summary._project_layers_in_tree_order", _exc)
                lyr = None
            if lyr is None or lyr.id() in seen:
                continue
            ordered.append(lyr)
            seen.add(lyr.id())
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._project_layers_in_tree_order", _exc)
    try:
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr is None or lyr.id() in seen:
                continue
            ordered.append(lyr)
            seen.add(lyr.id())
    except Exception as _exc:
        log_swallowed("ai_aoi_summary._project_layers_in_tree_order", _exc)
    return ordered


def build_aoi_context(
    *,
    aoi_layer: QgsVectorLayer,
    selected_only: bool,
    radius_m: float,
    only_archtoolkit_layers: bool = True,
    exclude_styling_layers: bool = False,
    layer_ids: Optional[List[str]] = None,
    group_path_prefix: Optional[str] = None,
    reference_layer: Optional[QgsVectorLayer] = None,
    reference_selected_only: bool = False,
    reference_name_field: str = "",
    reference_max_features: int = 120,
    max_layers: int = 40,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if aoi_layer is None or aoi_layer.geometryType() != Qgis.GeometryType.Polygon:
        return None, "AOI 레이어는 폴리곤이어야 합니다."

    aoi_crs = aoi_layer.crs()
    if not is_metric_crs(aoi_crs):
        return None, "AOI CRS 단위가 미터가 아닙니다. (투영 CRS 사용 권장)"

    # "Selected features only" with an empty selection falls back to the whole
    # layer (as _unary_union_geoms always did) - but the fallback is now recorded
    # so the report header cannot claim "선택 피처만 사용" for a run that used
    # every feature, and the log says so at warning level.
    selected_only_requested = bool(selected_only)
    selection_note: Optional[str] = None
    if selected_only:
        try:
            sel_n = int(aoi_layer.selectedFeatureCount())
        except Exception as _exc:
            log_swallowed("ai_aoi_summary.build_aoi_context", _exc)
            sel_n = 0
        if sel_n <= 0:
            selected_only = False
            selection_note = "선택 피처 없음: 전체 피처 사용"
            try:
                log_message(
                    "AI 요약: '선택된 피처만 사용'이 켜져 있으나 AOI 레이어에 선택된 피처가 없어 "
                    "전체 피처를 사용합니다. AOI 면적/버퍼/모든 통계가 레이어 전체 기준입니다.",
                    level=Qgis.MessageLevel.Warning,
                )
            except Exception as _exc:
                log_swallowed("ai_aoi_summary.build_aoi_context", _exc)

    aoi_geom, feat_n = _unary_union_geoms(aoi_layer, selected_only=selected_only)
    if aoi_geom is None or aoi_geom.isEmpty():
        return None, "AOI 지오메트리를 만들 수 없습니다."

    r = float(radius_m)
    if not math.isfinite(r) or r <= 0:
        return None, "반경(m)은 0보다 커야 합니다."

    try:
        buf_geom = aoi_geom.buffer(r, 24)
    except Exception:
        buf_geom = None
    if buf_geom is None or buf_geom.isEmpty():
        return None, "AOI 버퍼를 만들 수 없습니다."

    da = _safe_distance_area(aoi_crs)
    try:
        aoi_area = _area_m2(da, aoi_geom, aoi_crs)
    except Exception:
        aoi_area = None
    try:
        buf_area = _area_m2(da, buf_geom, aoi_crs)
    except Exception:
        buf_area = None

    aoi_centroid_pt = None
    try:
        c = aoi_geom.centroid()
        if c and (not c.isEmpty()):
            aoi_centroid_pt = QgsPointXY(c.asPoint())
    except Exception:
        aoi_centroid_pt = None

    group_prefix = str(group_path_prefix or "").strip().strip("/")
    if layer_ids:
        map_layers = QgsProject.instance().mapLayers()
        ordered = []
        seen = set()
        for lid in layer_ids:
            lid0 = str(lid or "").strip()
            if not lid0:
                continue
            lyr = map_layers.get(lid0)
            if lyr is None:
                continue
            if lyr.id() in seen:
                continue
            ordered.append(lyr)
            seen.add(lyr.id())
        layers = ordered
    else:
        layers = _project_layers_in_tree_order()
    summaries: List[Dict[str, Any]] = []

    # In the explicit 'layers' scope the user picked every layer by hand, so
    # the cap honours the full selection (raised to its size and logged) rather
    # than silently cutting an arbitrary tail of it.
    effective_max_layers = int(max_layers)
    if layer_ids and len(layers) > effective_max_layers:
        effective_max_layers = int(len(layers))
        try:
            log_message(
                f"AI 요약: 대상 레이어 {len(layers)}개가 레이어 한도({int(max_layers)}개)를 넘어 한도를 "
                f"{effective_max_layers}개로 올렸습니다.",
                level=Qgis.MessageLevel.Info,
            )
        except Exception as _exc:
            log_swallowed("ai_aoi_summary.build_aoi_context", _exc)
    layers_candidates = 0
    layers_truncated = False

    for lyr in layers:
        if lyr is None or lyr.id() == aoi_layer.id():
            continue

        group_path = None
        if group_prefix:
            try:
                group_path = str(_layer_group_path(lyr.id()) or "")
            except Exception:
                group_path = ""
            if group_path != group_prefix and (not group_path.startswith(group_prefix + "/")):
                continue

        meta = _layer_archtoolkit_meta(lyr)

        if exclude_styling_layers:
            try:
                if str(lyr.name() or "").startswith("Style:"):
                    continue
            except Exception as _exc:
                log_swallowed("tools/ai_aoi_summary.py:1203 (build_aoi_context)", _exc)
            try:
                if (meta or {}).get("tool_id") == "map_styling":
                    continue
            except Exception as _exc:
                log_swallowed("tools/ai_aoi_summary.py:1208 (build_aoi_context)", _exc)

        if only_archtoolkit_layers and (not meta) and (not is_archtoolkit_layer(lyr)):
            continue

        # Transform buffer geometry to layer CRS to do intersection tests.
        try:
            g_layer = _transform_geom(buf_geom, aoi_crs, lyr.crs())
        except Exception:
            g_layer = None
        if g_layer is None or g_layer.isEmpty():
            continue

        try:
            if not lyr.extent().intersects(g_layer.boundingBox()):
                continue
        except Exception as _exc:
            log_swallowed("ai_aoi_summary.build_aoi_context", _exc)

        # Past the cap: keep counting candidates (so the context can say how
        # many were skipped) but do not compute their stats.
        layers_candidates += 1
        if len(summaries) >= effective_max_layers:
            layers_truncated = True
            continue

        item: Dict[str, Any] = {
            "id": lyr.id(),
            "name": lyr.name(),
            "type": "raster" if isinstance(lyr, QgsRasterLayer) else "vector" if isinstance(lyr, QgsVectorLayer) else "other",
            "crs": getattr(lyr.crs(), "authid", lambda: "")() if hasattr(lyr, "crs") else "",
            "group_path": group_path if group_path is not None else _layer_group_path(lyr.id()),
        }
        if meta:
            item["archtoolkit"] = meta

        if isinstance(lyr, QgsVectorLayer):
            item["geometry_type"] = int(lyr.geometryType())
            try:
                item["wkb"] = QgsWkbTypes.displayString(lyr.wkbType())
            except Exception as _exc:
                log_swallowed("tools/ai_aoi_summary.py:1242 (build_aoi_context)", _exc)
            try:
                item["provider"] = str(lyr.providerType() or "")
            except Exception as _exc:
                log_swallowed("tools/ai_aoi_summary.py:1246 (build_aoi_context)", _exc)

            try:
                item["stats"] = _vector_layer_stats_in_geom(
                    lyr,
                    g_layer,
                    origin_point=aoi_centroid_pt,
                    origin_crs=aoi_crs,
                    tool_id=str((meta or {}).get("tool_id") or ""),
                )
            except Exception:
                item["stats"] = {"features": 0}

        elif isinstance(lyr, QgsRasterLayer):
            try:
                item["provider"] = str(lyr.providerType() or "")
            except Exception as _exc:
                log_swallowed("tools/ai_aoi_summary.py:1262 (build_aoi_context)", _exc)
            src_path = _split_qgis_source_path(lyr.source())
            item["source"] = os.path.basename(src_path) if src_path else ""
            if src_path and os.path.exists(src_path):
                try:
                    item["stats"] = _raster_stats_in_geom(src_path, g_layer)
                except Exception:
                    item["stats"] = None
            else:
                item["stats"] = None

        summaries.append(item)

    if layers_truncated:
        try:
            log_message(
                f"AI 요약: 레이어 한도({effective_max_layers}개)에 도달해 후보 {layers_candidates}개 중 "
                f"{len(summaries)}개만 요약했습니다.",
                level=Qgis.MessageLevel.Warning,
            )
        except Exception as _exc:
            log_swallowed("ai_aoi_summary.build_aoi_context", _exc)

    reference_sites = None
    if reference_layer is not None and isinstance(reference_layer, QgsVectorLayer):
        try:
            reference_sites = _reference_sites_summary(
                layer=reference_layer,
                aoi_geom=aoi_geom,
                buffer_geom=buf_geom,
                aoi_centroid_pt=aoi_centroid_pt,
                aoi_crs=aoi_crs,
                selected_only=bool(reference_selected_only),
                preferred_name_field=str(reference_name_field or ""),
                max_features=int(reference_max_features),
            )
        except Exception:
            reference_sites = None

    ctx: Dict[str, Any] = {
        "aoi": {
            "layer_name": aoi_layer.name(),
            "feature_count": int(feat_n),
            "crs": aoi_crs.authid(),
            "area_m2": aoi_area,
        },
        "radius_m": float(r),
        "buffer_area_m2": buf_area,
        "layers": summaries,
        "layers_truncated": bool(layers_truncated),
        "layers_candidates": int(layers_candidates),
        "options": {
            # Effective mode (False when the empty-selection fallback was taken).
            "selected_only": bool(selected_only),
            "selected_only_requested": bool(selected_only_requested),
            "selection_note": selection_note,
            "archtoolkit_only": bool(only_archtoolkit_layers),
            "exclude_styling_layers": bool(exclude_styling_layers),
            "layer_scope": "layers" if layer_ids else "group" if group_prefix else "auto",
            "group_path_prefix": group_prefix or None,
            "layer_ids_count": int(len(layer_ids)) if layer_ids else None,
            "reference_sites_enabled": bool(reference_sites is not None),
            "reference_selected_only": bool(reference_selected_only),
            "reference_name_field": str(reference_name_field or ""),
            "reference_max_features": int(reference_max_features),
            "max_layers": int(effective_max_layers),
            "max_layers_requested": int(max_layers),
        },
    }
    if reference_sites is not None:
        ctx["reference_sites"] = reference_sites

    try:
        log_message(f"AI AOI summary: layers={len(summaries)} (archtoolkit_only={only_archtoolkit_layers})", level=Qgis.MessageLevel.Info)
    except Exception as _exc:
        log_swallowed("tools/ai_aoi_summary.py:1323 (build_aoi_context)", _exc)

    return ctx, None


def export_aoi_context_csv(
    ctx: Dict[str, Any],
    *,
    layers_csv_path: str,
    numeric_fields_csv_path: str,
) -> Optional[str]:
    """Export aoi context stats to CSV files (best-effort).

    This is designed to work without any AI provider so users can bundle
    standard stats into a report folder.
    Returns an error message on failure, else None.
    """
    if not ctx:
        return "context is empty"

    try:
        import csv
        import json
    except Exception as e:  # pragma: no cover
        return str(e)

    try:
        layers = ctx.get("layers") or []
    except Exception:
        layers = []

    try:
        out_dir = os.path.dirname(str(layers_csv_path or ""))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
    except Exception as _exc:
        log_swallowed("ai_aoi_summary.export_aoi_context_csv", _exc)

    try:
        out_dir = os.path.dirname(str(numeric_fields_csv_path or ""))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
    except Exception as _exc:
        log_swallowed("ai_aoi_summary.export_aoi_context_csv", _exc)

    def _as_text(v: Any) -> str:
        try:
            if v is None:
                return ""
            if isinstance(v, (dict, list)):
                return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            return str(v)
        except Exception:
            return ""

    # 1) Layer summary CSV (one row per layer)
    try:
        fieldnames = [
            "layer_id",
            "layer_name",
            "layer_type",
            "group_path",
            "crs",
            "provider",
            "wkb",
            "source",
            # ArchToolkit metadata
            "tool_id",
            "run_id",
            "kind",
            "units",
            "created_at",
            # Common vector stats
            "features",
            "scanned",
            "scan_cap",
            "truncated",
            "layer_feature_count",
            "numeric_fields_truncated",
            "total_length_m",
            "total_area_m2",
            "top_field",
            "top_values_preview",
            "dist_to_aoi_centroid_mean_m",
            "dist_to_aoi_centroid_min_m",
            "dist_to_aoi_centroid_max_m",
            "dist_to_aoi_centroid_n",
            # Common raster stats
            "pixel_count",
            "raster_min",
            "raster_mean",
            "raster_max",
            "raster_sampled",
            "raster_sample_step",
            "raster_window_px",
            "gt_0_5_pct",
            "high_value_pct",
            "high_value_threshold",
            # Context-level layer cap (repeated per row so the file is self-describing)
            "layers_truncated",
            "layers_candidates",
            # Raw JSON
            "stats_json",
        ]
        with open(str(layers_csv_path), "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for lyr in layers:
                if not isinstance(lyr, dict):
                    continue
                meta = lyr.get("archtoolkit") or {}
                if not isinstance(meta, dict):
                    meta = {}
                stats = lyr.get("stats") or {}
                if not isinstance(stats, dict):
                    stats = {}

                top_preview = ""
                try:
                    tv = stats.get("top_values") or []
                    if isinstance(tv, list) and tv:
                        top_preview = ";".join([f"{d.get('value')}={d.get('count')}" for d in tv[:10] if isinstance(d, dict)])
                except Exception:
                    top_preview = ""

                dist = stats.get("dist_to_aoi_centroid_m") or {}
                if not isinstance(dist, dict):
                    dist = {}

                row = {
                    "layer_id": _as_text(lyr.get("id")),
                    "layer_name": _as_text(lyr.get("name")),
                    "layer_type": _as_text(lyr.get("type")),
                    "group_path": _as_text(lyr.get("group_path")),
                    "crs": _as_text(lyr.get("crs")),
                    "provider": _as_text(lyr.get("provider")),
                    "wkb": _as_text(lyr.get("wkb")),
                    "source": _as_text(lyr.get("source")),
                    # metadata
                    "tool_id": _as_text(meta.get("tool_id")),
                    "run_id": _as_text(meta.get("run_id")),
                    "kind": _as_text(meta.get("kind")),
                    "units": _as_text(meta.get("units")),
                    "created_at": _as_text(meta.get("created_at")),
                    # vector stats
                    "features": _as_text(stats.get("features")),
                    "scanned": _as_text(stats.get("scanned")),
                    "scan_cap": _as_text(stats.get("scan_cap")),
                    "truncated": _as_text(stats.get("truncated")),
                    "layer_feature_count": _as_text(stats.get("layer_feature_count")),
                    "numeric_fields_truncated": _as_text(stats.get("numeric_fields_truncated")),
                    "total_length_m": _as_text(stats.get("total_length_m")),
                    "total_area_m2": _as_text(stats.get("total_area_m2")),
                    "top_field": _as_text(stats.get("top_field")),
                    "top_values_preview": _as_text(top_preview),
                    "dist_to_aoi_centroid_mean_m": _as_text(dist.get("mean")),
                    "dist_to_aoi_centroid_min_m": _as_text(dist.get("min")),
                    "dist_to_aoi_centroid_max_m": _as_text(dist.get("max")),
                    "dist_to_aoi_centroid_n": _as_text(dist.get("n")),
                    # raster stats
                    "pixel_count": _as_text(stats.get("count")),
                    "raster_min": _as_text(stats.get("min")),
                    "raster_mean": _as_text(stats.get("mean")),
                    "raster_max": _as_text(stats.get("max")),
                    "raster_sampled": _as_text(stats.get("sampled")),
                    "raster_sample_step": _as_text(stats.get("sample_step")),
                    "raster_window_px": _as_text(stats.get("window_px")),
                    "gt_0_5_pct": _as_text(stats.get("gt_0_5_pct")),
                    "high_value_pct": _as_text(stats.get("high_value_pct")),
                    "high_value_threshold": _as_text(stats.get("high_value_threshold")),
                    # context-level
                    "layers_truncated": _as_text(ctx.get("layers_truncated")),
                    "layers_candidates": _as_text(ctx.get("layers_candidates")),
                    # raw
                    "stats_json": _as_text(lyr.get("stats")),
                }
                w.writerow(row)
    except Exception as e:
        return str(e)

    # 2) Numeric fields CSV (long format, one row per layer-field)
    try:
        fieldnames = [
            "layer_id",
            "layer_name",
            "group_path",
            "layer_type",
            "tool_id",
            "run_id",
            "kind",
            "units",
            "field",
            "n",
            "min",
            "mean",
            "max",
        ]
        with open(str(numeric_fields_csv_path), "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for lyr in layers:
                if not isinstance(lyr, dict):
                    continue
                stats = lyr.get("stats") or {}
                if not isinstance(stats, dict):
                    continue
                num = stats.get("numeric_fields") or {}
                if not isinstance(num, dict) or not num:
                    continue

                meta = lyr.get("archtoolkit") or {}
                if not isinstance(meta, dict):
                    meta = {}

                for fname, d in num.items():
                    if not isinstance(d, dict):
                        continue
                    w.writerow(
                        {
                            "layer_id": _as_text(lyr.get("id")),
                            "layer_name": _as_text(lyr.get("name")),
                            "group_path": _as_text(lyr.get("group_path")),
                            "layer_type": _as_text(lyr.get("type")),
                            "tool_id": _as_text(meta.get("tool_id")),
                            "run_id": _as_text(meta.get("run_id")),
                            "kind": _as_text(meta.get("kind")),
                            "units": _as_text(meta.get("units")),
                            "field": _as_text(fname),
                            "n": _as_text(d.get("n")),
                            "min": _as_text(d.get("min")),
                            "mean": _as_text(d.get("mean")),
                            "max": _as_text(d.get("max")),
                        }
                    )
    except Exception as e:
        return str(e)

    return None
