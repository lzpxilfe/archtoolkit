# -*- coding: utf-8 -*-
"""
AOI-centered project summary builder for ArchToolkit AI reporting.

Design goals
- Best-effort and fast: avoid heavy processing providers when possible.
- Only summarize information needed for a narrative report (no raw raster export).
"""

from __future__ import annotations

import math
import os
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

from .config import is_archtoolkit_group_name
from .i18n import is_english_ui, tr
from .utils import get_archtoolkit_layer_metadata, is_metric_crs, log_message, open_gdal_dataset_from_qgis_source


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

_TOOL_ANALYSIS_LABELS = {
    "dem_generate": "DEM 생성",
    "terrain_analysis": "지형 분석",
    "viewshed": "가시권 분석",
    "cost_surface": "비용표면/최소비용경로",
    "cost_network": "최소비용 네트워크",
    "spatial_network": "근접/가시성 네트워크",
    "terrain_profile": "지형 단면",
    "geochem": "지구화학도 수치화",
    "kigam_zip": "KIGAM 지질도 불러오기",
    "kigam_raster": "KIGAM 지질 래스터화",
    "cadastral_overlap": "지적도 중첩",
    "map_styling": "도면 시각화",
    "ahp_suitability": "AHP 입지적합도",
    "slope_aspect_drafting": "경사도/사면방향 도면화",
    "contour_extract": "등고선 추출",
}

_TOOL_KIND_LABELS = {
    ("terrain_analysis", "slope"): "경사도 래스터",
    ("terrain_analysis", "aspect"): "사면방향 래스터",
    ("terrain_analysis", "tri"): "TRI 래스터",
    ("terrain_analysis", "roughness"): "거칠기 래스터",
    ("terrain_analysis", "tpi"): "TPI 래스터",
    ("terrain_analysis", "slope_position"): "사면 위치 분류",
    ("viewshed", "aoi_stats"): "AOI 가시 통계",
    ("viewshed", "union"): "합집합 가시권",
    ("viewshed", "count"): "누적 가시 빈도",
    ("viewshed", "weighted"): "가중 누적 가시권",
    ("viewshed", "observer_points"): "관측점 레이어",
    ("viewshed", "reverse_union"): "역가시권 합집합",
    ("viewshed", "visual_imbalance"): "시각 불균형 지표",
    ("viewshed", "reverse_visual_imbalance_reverse"): "역방향 시각 불균형",
    ("viewshed", "analysis_radius_ring"): "분석 반경 링",
    ("cost_surface", "path"): "최소비용 경로",
    ("cost_surface", "cost_raster"): "누적 비용 래스터",
    ("cost_surface", "energy_raster"): "누적 에너지 래스터",
    ("cost_surface", "corridor"): "비용 회랑",
    ("cost_network", "edges"): "네트워크 간선",
    ("cost_network", "nodes"): "네트워크 노드",
    ("spatial_network", "edges"): "공간 네트워크 간선",
    ("spatial_network", "nodes_metrics"): "노드 지표",
    ("terrain_profile", "profile_single"): "개별 단면",
    ("terrain_profile", "profile_lines"): "단면선 모음",
    ("geochem", "value_raster"): "연속값 래스터",
    ("geochem", "class_raster"): "등급 래스터",
    ("geochem", "zone_polygons"): "구간 폴리곤",
    ("geochem", "zone_centroids"): "구간 중심점",
    ("geochem", "zonal_stats"): "구간 통계",
    ("cadastral_overlap", "overlap"): "중첩 결과",
    ("cadastral_overlap", "overlap_by_aoi"): "AOI별 중첩 결과",
    ("ahp_suitability", "suitability"): "적합도 래스터",
    ("slope_aspect_drafting", "slope_grid"): "인쇄용 경사 래스터",
    ("slope_aspect_drafting", "aspect_arrows"): "사면방향 화살표",
    ("contour_extract", "contours"): "등고선 레이어",
    ("dem_generate", "dem"): "DEM",
    ("dem_generate", "kriging_variance"): "크리깅 분산 래스터",
    ("kigam_zip", "vector"): "불러온 지질 벡터",
    ("kigam_raster", "raster"): "지질 범주형 래스터",
}

_PARAM_LABELS = {
    "points_n": "관측점 수",
    "max_dist_m": "최대 분석거리",
    "classification": "분류 체계",
    "network_mode": "네트워크 모드",
    "cost_mode": "비용 기준",
    "model_label": "이동 모델",
    "distance_m": "거리",
    "samples": "샘플 수",
    "preset_label": "프리셋",
    "field": "값 필드",
    "pixel": "픽셀 크기",
    "split_by_feature": "AOI별 분리",
    "layer_name": "레이어명",
    "title": "지표 제목",
    "raster_name": "원본 래스터",
    "aoi_layer": "AOI 레이어",
}


def _split_qgis_source_path(src: str) -> str:
    try:
        s = str(src or "")
        return (s.split("|", 1)[0] or "").strip()
    except Exception:
        return str(src or "").strip()


def _fmt_number_text(value: Any, *, digits: int = 1) -> str:
    try:
        if value is None:
            return "-"
        x = float(value)
        if not math.isfinite(x):
            return "-"
        return f"{x:,.{int(digits)}f}"
    except Exception:
        return str(value)


def _tool_analysis_label(tool_id: str) -> str:
    key = str(tool_id or "").strip()
    if not key:
        return ""
    return tr(_TOOL_ANALYSIS_LABELS.get(key, key.replace("_", " ").strip()))


def _tool_result_label(tool_id: str, kind: str) -> str:
    key = (str(tool_id or "").strip(), str(kind or "").strip())
    if key in _TOOL_KIND_LABELS:
        return tr(_TOOL_KIND_LABELS[key])
    kind0 = key[1]
    if not kind0:
        return tr("분석 결과")
    return tr(kind0.replace("_", " ").strip())


def _numeric_field_mean(stats: Dict[str, Any], field_name: str) -> Optional[float]:
    try:
        numeric = stats.get("numeric_fields") or {}
        field = numeric.get(field_name) or {}
        value = field.get("mean")
        if value is None:
            return None
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _describe_param_value(key: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    key0 = str(key or "").strip()
    label = _PARAM_LABELS.get(key0, key0.replace("_", " ").strip())
    if not label:
        return None
    try:
        if isinstance(value, bool):
            return f"{tr(label)}: {tr('예' if value else '아니오')}"
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            unit = ""
            if key0.endswith("_m"):
                unit = " m"
            elif key0.endswith("_pct"):
                unit = " %"
            return f"{tr(label)}: {_fmt_number_text(value)}{unit}"
        if isinstance(value, list):
            if key0 == "criteria":
                return tr("기준 수: {count}개", count=len(value))
            preview = ", ".join(str(v) for v in value[:4])
            if preview:
                return f"{tr(label)}: {preview}"
            return None
        text = str(value).strip()
        if not text:
            return None
        return f"{tr(label)}: {text}"
    except Exception:
        return None


def _interpret_archtoolkit_layer(item: Dict[str, Any]) -> Dict[str, Any]:
    meta = item.get("archtoolkit") or {}
    if not isinstance(meta, dict):
        return {}

    tool_id = str(meta.get("tool_id") or "").strip()
    kind = str(meta.get("kind") or "").strip()
    params = meta.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    stats = item.get("stats") or {}
    if not isinstance(stats, dict):
        stats = {}

    analysis = _tool_analysis_label(tool_id)
    result_label = _tool_result_label(tool_id, kind)
    if is_english_ui():
        summary = f"{result_label} from {analysis}." if analysis else f"{result_label}."
    else:
        summary = f"{analysis}의 {result_label}입니다." if analysis else f"{result_label}입니다."

    notes: List[str] = []
    for key in (
        "model_label",
        "network_mode",
        "cost_mode",
        "classification",
        "preset_label",
        "field",
        "pixel",
        "raster_name",
        "aoi_layer",
        "points_n",
        "max_dist_m",
        "distance_m",
        "samples",
        "split_by_feature",
        "title",
    ):
        text = _describe_param_value(key, params.get(key))
        if text:
            notes.append(text)

    if tool_id == "ahp_suitability":
        criteria = params.get("criteria") or []
        if isinstance(criteria, list) and criteria:
            notes.append(tr("기준 수: {count}개", count=len(criteria)))
        cr_value = params.get("consistency_ratio")
        if cr_value is not None:
            notes.append(tr("일관성비율(CR): {value}", value=_fmt_number_text(cr_value, digits=3)))
        method = params.get("suitability_method")
        if method:
            notes.append(tr("합성 방식: {method}", method=str(method).replace('_', ' ')))

    metrics: List[str] = []
    if item.get("type") == "vector":
        features = stats.get("features")
        if features:
            metrics.append(tr("겹치는 피처 {count}개", count=f"{int(features):,}"))
        if "total_length_m" in stats:
            metrics.append(tr("총 길이 {value} m", value=_fmt_number_text(stats.get('total_length_m'))))
        if "total_area_m2" in stats:
            metrics.append(tr("총 면적 {value} ㎡", value=_fmt_number_text(stats.get('total_area_m2'))))
    elif item.get("type") == "raster":
        if stats.get("count"):
            if is_english_ui():
                metrics.append(
                    "Raster value min/mean/max = "
                    f"{_fmt_number_text(stats.get('min'), digits=3)} / "
                    f"{_fmt_number_text(stats.get('mean'), digits=3)} / "
                    f"{_fmt_number_text(stats.get('max'), digits=3)}"
                )
            else:
                metrics.append(
                    "래스터 값 min/mean/max = "
                    f"{_fmt_number_text(stats.get('min'), digits=3)} / "
                    f"{_fmt_number_text(stats.get('mean'), digits=3)} / "
                    f"{_fmt_number_text(stats.get('max'), digits=3)}"
                )
        if "gt_0_5_pct" in stats:
            metrics.append(tr("0.5 초과 비율 {value} %", value=_fmt_number_text(stats.get('gt_0_5_pct'))))

    special_fields = (
        ("vis_pct", "가시비율"),
        ("vis_m2", "가시면적"),
        ("dist_m", "거리"),
        ("time_min", "이동시간"),
        ("energy_kcal", "에너지"),
        ("in_aoi_pct", "AOI 중첩비율"),
        ("distance", "단면 거리"),
        ("min_elev", "최저고도"),
        ("max_elev", "최고고도"),
    )
    for field_name, label in special_fields:
        mean_value = _numeric_field_mean(stats, field_name)
        if mean_value is None:
            continue
        suffix = ""
        if field_name.endswith("_pct"):
            suffix = " %"
        elif field_name.endswith("_m") or field_name in ("distance", "min_elev", "max_elev", "dist_m"):
            suffix = " m"
        elif field_name == "time_min":
            suffix = " min"
        elif field_name == "energy_kcal":
            suffix = " kcal"
        metrics.append(tr("{label} 평균 {value}{suffix}", label=tr(label), value=_fmt_number_text(mean_value), suffix=suffix))

    top_values = stats.get("top_values") or []
    top_field = str(stats.get("top_field") or "").strip()
    if top_field and isinstance(top_values, list) and top_values:
        preview = ", ".join(
            f"{str(d.get('value') or '')}={int(d.get('count') or 0):,}"
            for d in top_values[:3]
            if isinstance(d, dict)
        )
        if preview:
            metrics.append(tr("{field} 상위값: {preview}", field=top_field, preview=preview))

    out = {
        "analysis": analysis,
        "result_label": result_label,
        "summary": summary,
        "notes": notes[:6],
        "key_metrics": metrics[:6],
    }
    if tool_id:
        out["tool_id"] = tool_id
    if kind:
        out["kind"] = kind
    return out


def _summarize_archtoolkit_runs(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for item in items:
        meta = item.get("archtoolkit") or {}
        if not isinstance(meta, dict):
            continue
        run_id = str(meta.get("run_id") or "").strip()
        tool_id = str(meta.get("tool_id") or "").strip()
        if not run_id or not tool_id:
            continue
        interp = item.get("archtoolkit_interpretation") or {}
        bucket = buckets.setdefault(
            run_id,
            {
                "run_id": run_id,
                "tool_id": tool_id,
                "analysis": str(interp.get("analysis") or _tool_analysis_label(tool_id)),
                "layer_names": [],
                "result_labels": [],
                "key_metrics": [],
            },
        )
        name = str(item.get("name") or "").strip()
        if name and name not in bucket["layer_names"]:
            bucket["layer_names"].append(name)
        result_label = str(interp.get("result_label") or "").strip()
        if result_label and result_label not in bucket["result_labels"]:
            bucket["result_labels"].append(result_label)
        for metric in interp.get("key_metrics") or []:
            text = str(metric or "").strip()
            if text and text not in bucket["key_metrics"]:
                bucket["key_metrics"].append(text)

    out = []
    for run_id, bucket in buckets.items():
        analysis = str(bucket.get("analysis") or "").strip()
        results = list(bucket.get("result_labels") or [])
        layer_names = list(bucket.get("layer_names") or [])
        summary = f"{analysis} run group" if is_english_ui() else f"{analysis} 실행 묶음"
        if results:
            summary += f" ({', '.join(results[:3])})"
        out.append(
            {
                "run_id": run_id,
                "tool_id": str(bucket.get("tool_id") or ""),
                "analysis": analysis,
                "layer_count": len(layer_names),
                "layer_names": layer_names,
                "result_labels": results,
                "summary": summary,
                "key_metrics": list(bucket.get("key_metrics") or [])[:6],
            }
        )
    out.sort(key=lambda d: (str(d.get("analysis") or ""), str(d.get("run_id") or "")))
    return out


def _safe_distance_area(crs) -> QgsDistanceArea:
    da = QgsDistanceArea()
    try:
        da.setSourceCrs(crs, QgsProject.instance().transformContext())
    except Exception:
        pass
    try:
        ellps = QgsProject.instance().ellipsoid()
        if ellps:
            da.setEllipsoid(ellps)
    except Exception:
        pass
    return da


def _unary_union_geoms(layer: QgsVectorLayer, *, selected_only: bool) -> Tuple[Optional[QgsGeometry], int]:
    geoms = []
    count = 0
    feats = layer.selectedFeatures() if selected_only and layer.selectedFeatureCount() > 0 else layer.getFeatures()
    for f in feats:
        try:
            g = f.geometry()
        except Exception:
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
    except Exception:
        pass
    try:
        name = str(layer.name() or "")
        if name.startswith("Style:") or name.startswith("AOI_"):
            return True
    except Exception:
        pass
    try:
        src = str(layer.source() or "")
        src_l = src.lower()
        if "archtoolkit_" in src_l or "archt_" in src_l or "archtoolkit" in src_l:
            return True
    except Exception:
        pass
    try:
        # Cost tool tags
        if layer.customProperty("archtoolkit/cost_surface/run_id", None) is not None:
            return True
    except Exception:
        pass
    try:
        # Fall back to configured ArchToolkit output groups when metadata is unavailable.
        root = QgsProject.instance().layerTreeRoot()
        node = root.findLayer(layer.id())
        cur = node.parent() if node is not None else None
        while cur is not None and cur != root:
            try:
                if is_archtoolkit_group_name(str(cur.name() or "")):
                    return True
            except Exception:
                pass
            try:
                cur = cur.parent()
            except Exception:
                break
    except Exception:
        pass
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
    except Exception:
        pass
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
            except Exception:
                pass
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
    except Exception:
        pass
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
) -> Dict[str, Any]:
    out: Dict[str, Any] = {"features": 0}
    if layer is None or geom is None or geom.isEmpty():
        return out

    da = _safe_distance_area(layer.crs())
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

    # Lightweight field-aware summaries (optional)
    field_names = []
    try:
        field_names = [f.name() for f in layer.fields()]
    except Exception:
        field_names = []

    hist = None
    hist_field = None
    for cand in ("class_id", "Layer", "element"):
        if cand in field_names:
            hist_field = cand
            hist = {}
            break

    num_fields = [c for c in _NUMERIC_FIELD_CANDIDATES if c in field_names]
    num_acc: Dict[str, Dict[str, Any]] = {}
    for f in num_fields:
        num_acc[str(f)] = {"sum": 0.0, "min": float("inf"), "max": float("-inf"), "n": 0}

    dist_acc = None
    if geom_type == QgsWkbTypes.PointGeometry and da_origin is not None and origin_point is not None:
        dist_acc = {"sum": 0.0, "min": float("inf"), "max": float("-inf"), "n": 0}

    for feat in layer.getFeatures(req):
        scanned += 1
        if scanned > int(max_features_scan):
            break
        try:
            g = feat.geometry()
        except Exception:
            continue
        if not g or g.isEmpty():
            continue
        try:
            if not g.intersects(geom):
                continue
        except Exception:
            continue

        n += 1
        if geom_type == QgsWkbTypes.LineGeometry:
            try:
                total_len += float(da.measureLength(g.intersection(geom)))
            except Exception:
                pass
        elif geom_type == QgsWkbTypes.PolygonGeometry:
            try:
                total_area += float(da.measureArea(g.intersection(geom)))
            except Exception:
                pass

        if hist is not None and hist_field is not None:
            try:
                v = feat[hist_field]
                k = str(v) if v is not None else "(null)"
                hist[k] = int(hist.get(k, 0)) + 1
            except Exception:
                pass

        for f, acc in num_acc.items():
            try:
                v = feat[f]
                if v is None:
                    continue
                x = float(v)
                if not math.isfinite(x):
                    continue
                acc["sum"] = float(acc["sum"]) + float(x)
                acc["min"] = float(min(float(acc["min"]), float(x)))
                acc["max"] = float(max(float(acc["max"]), float(x)))
                acc["n"] = int(acc["n"]) + 1
            except Exception:
                continue

        if dist_acc is not None:
            try:
                pt = g.centroid().asPoint()
                pt_xy = QgsPointXY(pt)
                if ct_to_origin is not None:
                    pt_xy = ct_to_origin.transform(pt_xy)
                dist = float(da_origin.measureLine(origin_point, pt_xy))
                if math.isfinite(dist):
                    dist_acc["sum"] = float(dist_acc["sum"]) + dist
                    dist_acc["min"] = float(min(float(dist_acc["min"]), dist))
                    dist_acc["max"] = float(max(float(dist_acc["max"]), dist))
                    dist_acc["n"] = int(dist_acc["n"]) + 1
            except Exception:
                pass

    out["features"] = int(n)
    out["scanned"] = int(scanned)
    if geom_type == QgsWkbTypes.LineGeometry:
        out["total_length_m"] = float(total_len)
    if geom_type == QgsWkbTypes.PolygonGeometry:
        out["total_area_m2"] = float(total_area)
    if hist is not None:
        # keep top 20
        items = sorted(hist.items(), key=lambda kv: kv[1], reverse=True)[:20]
        out["top_values"] = [{"value": k, "count": int(v)} for k, v in items]
        out["top_field"] = hist_field

    numeric_out = {}
    for f, acc in num_acc.items():
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
        except Exception:
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
        except Exception:
            pass
    return out


def _raster_stats_in_geom(
    raster_source: str,
    geom: QgsGeometry,
    *,
    max_pixels: int = 4_000_000,  # cap for memory safety
) -> Optional[Dict[str, Any]]:
    if np is None or gdal is None or ogr is None:
        return None
    if not raster_source:
        return None
    if geom is None or geom.isEmpty():
        return None

    ds, _opened_source = open_gdal_dataset_from_qgis_source(str(raster_source))
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

    # Downsample if too big
    step = 1
    try:
        if int(w) * int(h) > int(max_pixels):
            step = int(math.ceil(math.sqrt((w * h) / float(max_pixels))))
            step = max(1, step)
    except Exception:
        step = 1

    try:
        arr = band.ReadAsArray(x0, y0, w, h)
    except Exception:
        ds = None
        return None

    if arr is None:
        ds = None
        return None

    try:
        arr = arr.astype(np.float32, copy=False)
        if step > 1:
            arr = arr[::step, ::step]
    except Exception:
        pass

    # Rasterize polygon mask into the same window
    try:
        win_gt = (
            gt[0] + x0 * gt[1] + y0 * gt[2],
            gt[1] * step,
            gt[2] * step,
            gt[3] + x0 * gt[4] + y0 * gt[5],
            gt[4] * step,
            gt[5] * step,
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

    valid = mask & np.isfinite(arr)
    if nodata is not None:
        try:
            valid &= arr != float(nodata)
        except Exception:
            pass

    if not np.any(valid):
        return None

    vals = arr[valid]
    try:
        out = {
            "count": int(vals.size),
            "min": float(np.nanmin(vals)),
            "max": float(np.nanmax(vals)),
            "mean": float(np.nanmean(vals)),
        }
        # Binary-ish mask hint (e.g., viewshed/corridor): only compute when data looks 0/Max-ish.
        try:
            sample = vals
            if int(sample.size) > 200_000:
                step0 = int(max(1, sample.size // 200_000))
                sample = sample[::step0]
            vmin = float(out.get("min"))
            vmax = float(out.get("max"))
            if math.isfinite(vmin) and math.isfinite(vmax) and vmax > 0 and vmin >= -1e-6 and sample.size > 0:
                near0 = float(np.count_nonzero(np.isclose(sample, 0.0, atol=1e-6)))
                nearMax = float(np.count_nonzero(np.isclose(sample, vmax, atol=1e-6)))
                frac = (near0 + nearMax) / float(sample.size)
                if frac >= 0.98:
                    vis = float(np.count_nonzero(vals > 0.5)) / float(vals.size) * 100.0
                    out["gt_0_5_pct"] = float(vis)
        except Exception:
            pass
        return out
    except Exception:
        return None


def build_aoi_context(
    *,
    aoi_layer: QgsVectorLayer,
    selected_only: bool,
    radius_m: float,
    only_archtoolkit_layers: bool = True,
    exclude_styling_layers: bool = False,
    layer_ids: Optional[List[str]] = None,
    group_path_prefix: Optional[str] = None,
    max_layers: int = 40,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if aoi_layer is None or aoi_layer.geometryType() != QgsWkbTypes.PolygonGeometry:
        return None, "AOI 레이어는 폴리곤이어야 합니다."

    aoi_crs = aoi_layer.crs()
    if not is_metric_crs(aoi_crs):
        return None, "AOI CRS 단위가 미터가 아닙니다. (투영 CRS 사용 권장)"

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
        aoi_area = float(da.measureArea(aoi_geom))
    except Exception:
        aoi_area = None
    try:
        buf_area = float(da.measureArea(buf_geom))
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
    layer_limit = None
    if not layer_ids:
        try:
            layer_limit = max(1, int(max_layers))
        except Exception:
            layer_limit = 40

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
        layers = list(QgsProject.instance().mapLayers().values())
    summaries: List[Dict[str, Any]] = []

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
            except Exception:
                pass
            try:
                if (meta or {}).get("tool_id") == "map_styling":
                    continue
            except Exception:
                pass

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
        except Exception:
            pass

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
            except Exception:
                pass
            try:
                item["provider"] = str(lyr.providerType() or "")
            except Exception:
                pass

            try:
                item["stats"] = _vector_layer_stats_in_geom(
                    lyr,
                    g_layer,
                    origin_point=aoi_centroid_pt,
                    origin_crs=aoi_crs,
                )
            except Exception:
                item["stats"] = {"features": 0}

        elif isinstance(lyr, QgsRasterLayer):
            try:
                item["provider"] = str(lyr.providerType() or "")
            except Exception:
                pass
            src_path = _split_qgis_source_path(lyr.source())
            item["source"] = os.path.basename(src_path) if src_path else ""
            try:
                item["stats"] = _raster_stats_in_geom(str(lyr.source() or ""), g_layer)
            except Exception:
                item["stats"] = None

        if meta:
            try:
                interp = _interpret_archtoolkit_layer(item)
                if interp:
                    item["archtoolkit_interpretation"] = interp
            except Exception:
                pass

        summaries.append(item)
        if layer_limit is not None and len(summaries) >= layer_limit:
            break

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
        "archtoolkit_runs": _summarize_archtoolkit_runs(summaries),
        "options": {
            "selected_only": bool(selected_only),
            "archtoolkit_only": bool(only_archtoolkit_layers),
            "exclude_styling_layers": bool(exclude_styling_layers),
            "layer_scope": "layers" if layer_ids else "group" if group_prefix else "auto",
            "group_path_prefix": group_prefix or None,
            "layer_ids_count": int(len(layer_ids)) if layer_ids else None,
            "max_layers": int(max_layers),
        },
    }

    try:
        log_message(f"AI AOI summary: layers={len(summaries)} (archtoolkit_only={only_archtoolkit_layers})", level=Qgis.Info)
    except Exception:
        pass

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
    except Exception:
        pass

    try:
        out_dir = os.path.dirname(str(numeric_fields_csv_path or ""))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
    except Exception:
        pass

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
            "analysis_label",
            "result_label",
            "interpretation_summary",
            # Common vector stats
            "features",
            "scanned",
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
            "gt_0_5_pct",
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
                interp = lyr.get("archtoolkit_interpretation") or {}
                if not isinstance(interp, dict):
                    interp = {}
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
                    "analysis_label": _as_text(interp.get("analysis")),
                    "result_label": _as_text(interp.get("result_label")),
                    "interpretation_summary": _as_text(interp.get("summary")),
                    # vector stats
                    "features": _as_text(stats.get("features")),
                    "scanned": _as_text(stats.get("scanned")),
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
                    "gt_0_5_pct": _as_text(stats.get("gt_0_5_pct")),
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
