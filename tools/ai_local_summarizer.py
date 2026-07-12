# -*- coding: utf-8 -*-
"""
Free/local AOI report generator for ArchToolkit.

This module intentionally makes no external API calls.
It turns the AOI context (from ai_aoi_summary.build_aoi_context) into a
Korean, report-like narrative.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def _fmt_int(v: Any) -> str:
    try:
        if v is None:
            return "-"
        return f"{int(v):,}"
    except Exception:
        return str(v)


def _fmt_float(v: Any, *, digits: int = 2) -> str:
    try:
        if v is None:
            return "-"
        x = float(v)
        if not math.isfinite(x):
            return "-"
        return f"{x:,.{int(digits)}f}"
    except Exception:
        return str(v)


def _first_nonempty(items: List[str]) -> Optional[str]:
    for s in items:
        if isinstance(s, str) and s.strip():
            return s.strip()
    return None


def _layer_stats_lines(layer: Dict[str, Any]) -> List[str]:
    t = str(layer.get("type") or "")
    stats = layer.get("stats")
    if not stats:
        return ["- 통계: (없음/계산 실패)"]

    lines: List[str] = []

    if t == "vector":
        n = stats.get("features")
        scanned = stats.get("scanned")
        lines.append(f"- 피처: { _fmt_int(n) } (스캔 { _fmt_int(scanned) })")

        if "total_length_m" in stats:
            lines.append(f"- 총 길이: { _fmt_float(stats.get('total_length_m'), digits=1) } m")
        if "total_area_m2" in stats:
            lines.append(f"- 총 면적: { _fmt_float(stats.get('total_area_m2'), digits=1) } ㎡")

        top_field = stats.get("top_field")
        top_vals = stats.get("top_values") or []
        if top_field and top_vals:
            preview = ", ".join([f"{d.get('value')}={_fmt_int(d.get('count'))}" for d in top_vals[:6]])
            if preview:
                lines.append(f"- 상위 값({top_field}): {preview}")

        num = stats.get("numeric_fields") or {}
        if isinstance(num, dict) and num:
            preferred = [
                # Viewshed AOI stats
                "vis_pct",
                "vis_m2",
                "tot_m2",
                # Cost/LCP
                "dist_m",
                "time_min",
                "energy_kcal",
                # Terrain profile
                "distance",
                "min_elev",
                "max_elev",
                # GeoChem
                "val_min",
                "val_max",
                "v_min",
                "v_max",
                # Cadastral
                "in_aoi_pct",
                "in_aoi_m2",
                "parcel_m2",
            ]
            show_fields = [f for f in preferred if f in num]
            if not show_fields:
                show_fields = list(num.keys())
            for f in show_fields[:8]:
                d = num.get(f) or {}
                lines.append(
                    f"- {f}: mean={_fmt_float(d.get('mean'), digits=2)} (min={_fmt_float(d.get('min'), digits=2)}, max={_fmt_float(d.get('max'), digits=2)}, n={_fmt_int(d.get('n'))})"
                )

        dist = stats.get("dist_to_aoi_centroid_m")
        if isinstance(dist, dict) and dist.get("n"):
            lines.append(
                f"- AOI 중심까지 거리: mean={_fmt_float(dist.get('mean'), digits=1)} m (min={_fmt_float(dist.get('min'), digits=1)}, max={_fmt_float(dist.get('max'), digits=1)}, n={_fmt_int(dist.get('n'))})"
            )

    elif t == "raster":
        lines.append(f"- 픽셀(표본) 수: {_fmt_int(stats.get('count'))}")
        lines.append(
            f"- min/mean/max: { _fmt_float(stats.get('min'), digits=3) } / { _fmt_float(stats.get('mean'), digits=3) } / { _fmt_float(stats.get('max'), digits=3) }"
        )
        if "gt_0_5_pct" in stats:
            lines.append(f"- (힌트) 마스크/가시(>0.5) 비율: { _fmt_float(stats.get('gt_0_5_pct'), digits=1) } %")
    else:
        lines.append("- 통계: (지원되지 않는 레이어 타입)")

    return lines


def _reference_sites_lines(ctx: Dict[str, Any]) -> List[str]:
    ref = ctx.get("reference_sites") or {}
    if not isinstance(ref, dict) or not ref:
        return ["- (추가 유적 관계 분석 미사용)"]

    layer_name = str(ref.get("layer_name") or "").strip()
    feature_count = int(ref.get("feature_count") or 0)
    scanned = int(ref.get("scanned") or 0)
    name_field = str(ref.get("name_field") or "").strip()
    counts = ref.get("counts") or {}
    if not isinstance(counts, dict):
        counts = {}
    items = ref.get("items") or []
    if not isinstance(items, list):
        items = []

    out: List[str] = []
    out.append(f"- 레이어: `{layer_name or '(이름 없음)'}`")
    out.append(f"- 유적 수: {_fmt_int(feature_count)} (스캔 {_fmt_int(scanned)})")
    if name_field:
        out.append(f"- 이름 필드: `{name_field}`")
    out.append(
        "- 분류: AOI 내부/중첩="
        f"{_fmt_int(counts.get('inside_or_overlap_aoi'))}, "
        "AOI 내부="
        f"{_fmt_int(counts.get('inside_aoi'))}, "
        "AOI 경계걸침="
        f"{_fmt_int(counts.get('crosses_aoi_boundary'))}, "
        "AOI 버퍼 내(외부)="
        f"{_fmt_int(counts.get('inside_buffer_only'))}, "
        "버퍼 경계걸침="
        f"{_fmt_int(counts.get('crosses_buffer_boundary'))}, "
        "버퍼 밖="
        f"{_fmt_int(counts.get('outside_buffer'))}"
    )

    if not items:
        out.append("- (관계 계산된 유적이 없습니다)")
        return out

    out.append("- 주요 유적 관계(가까운 순):")
    for d in items[:20]:
        if not isinstance(d, dict):
            continue
        name = str(d.get("name") or "").strip() or "(이름 없음)"
        rel = str(d.get("relation") or "").strip()
        rel_ko = {
            "inside_or_overlap_aoi": "AOI 내부/중첩",
            "inside_aoi": "AOI 내부",
            "crosses_aoi_boundary": "AOI 경계 걸침(내/외부 혼합)",
            "inside_buffer_only": "AOI 버퍼 내(외부)",
            "crosses_buffer_boundary": "AOI 버퍼 경계 걸침",
            "outside_buffer": "AOI 버퍼 밖",
        }.get(rel, rel or "-")
        dist = _fmt_float(d.get("distance_to_aoi_m"), digits=1)
        dc = _fmt_float(d.get("distance_to_aoi_centroid_m"), digits=1)
        comp = str(d.get("compass_from_aoi") or "").strip()
        comp_txt = f", 방위={comp}" if comp else ""
        extra = []
        if "overlap_aoi_area_m2" in d:
            extra.append(f"AOI중첩면적={_fmt_float(d.get('overlap_aoi_area_m2'), digits=1)}㎡")
        if "overlap_aoi_length_m" in d:
            extra.append(f"AOI중첩길이={_fmt_float(d.get('overlap_aoi_length_m'), digits=1)}m")
        if "feature_area_m2" in d:
            extra.append(
                "AOI내부="
                f"{_fmt_float(d.get('overlap_aoi_area_m2'), digits=1)}㎡"
                f"({ _fmt_float(d.get('inside_aoi_area_pct'), digits=1) }%)"
            )
            extra.append(
                "AOI외부="
                f"{_fmt_float(d.get('outside_aoi_area_m2'), digits=1)}㎡"
                f"({ _fmt_float(d.get('outside_aoi_area_pct'), digits=1) }%)"
            )
        if "feature_length_m" in d:
            extra.append(
                "AOI내부길이="
                f"{_fmt_float(d.get('overlap_aoi_length_m'), digits=1)}m"
                f"({ _fmt_float(d.get('inside_aoi_length_pct'), digits=1) }%)"
            )
            extra.append(
                "AOI외부길이="
                f"{_fmt_float(d.get('outside_aoi_length_m'), digits=1)}m"
                f"({ _fmt_float(d.get('outside_aoi_length_pct'), digits=1) }%)"
            )
        suffix = f" / {', '.join(extra)}" if extra else ""
        out.append(f"  - {name}: {rel_ko}{comp_txt}, AOI경계거리={dist}m, AOI중심거리={dc}m{suffix}")

    if bool(ref.get("truncated")):
        out.append("- (표시 개수 제한으로 일부 유적은 생략됨)")
    return out


def _distance_phrase(dist_m: Any) -> str:
    try:
        d = float(dist_m)
    except Exception:
        return ""
    if not math.isfinite(d):
        return ""
    if d <= 0.5:
        return "AOI에 접함"
    if d < 1000:
        return f"약 {d:,.0f} m"
    return f"약 {d/1000.0:,.1f} km"


_RELATION_KO = {
    "inside_aoi": "AOI 내부",
    "crosses_aoi_boundary": "AOI 경계 걸침",
    "inside_buffer_only": "버퍼 내부",
    "crosses_buffer_boundary": "버퍼 경계 걸침",
    "outside_buffer": "버퍼 밖",
}


def _narrative_lines(ctx: Dict[str, Any]) -> List[str]:
    """Rule-based Korean prose using direction/distance/relation - a readable
    executive summary, not a bullet dump."""
    aoi = ctx.get("aoi") or {}
    layers = ctx.get("layers") or []
    aoi_name = str(aoi.get("layer_name") or "").strip() or "(이름 없음)"
    aoi_area = aoi.get("area_m2")
    radius_m = ctx.get("radius_m")

    n_vec = sum(1 for lyr in layers if str(lyr.get("type") or "") == "vector")
    n_ras = sum(1 for lyr in layers if str(lyr.get("type") or "") == "raster")
    total_feats = 0
    for lyr in layers:
        try:
            total_feats += int(((lyr.get("stats") or {}).get("features")) or 0)
        except Exception:
            pass

    lines: List[str] = []
    area_txt = _fmt_float(aoi_area, digits=0)
    rad_txt = _fmt_float(radius_m, digits=0)
    s1 = (
        f"이번 요약은 조사지역 `{aoi_name}`"
        + (f"(면적 약 {area_txt} ㎡)" if area_txt != "-" else "")
        + f"을(를) 중심으로 반경 {rad_txt} m 범위를 대상으로 합니다. "
        + f"해당 범위와 겹치는 레이어는 총 {_fmt_int(len(layers))}개"
        + f"(벡터 {n_vec}, 래스터 {n_ras})이며, "
        + f"벡터 피처는 대략 {_fmt_int(total_feats)}개가 확인됩니다."
    )
    lines.append(s1)

    # Reference-site relations with direction and distance.
    ref = ctx.get("reference_sites") or {}
    if isinstance(ref, dict) and ref:
        counts = ref.get("counts") or {}
        items = [d for d in (ref.get("items") or []) if isinstance(d, dict)]
        feature_count = int(ref.get("feature_count") or 0)
        inside = int(counts.get("inside_or_overlap_aoi") or 0)
        buf_only = int(counts.get("inside_buffer_only") or 0)

        s2 = (
            f"주변 유적 레이어에서 관계가 계산된 유적은 총 {_fmt_int(feature_count)}개로, "
            f"이 중 AOI 내부/중첩 {_fmt_int(inside)}개, 버퍼 내부(외곽) {_fmt_int(buf_only)}개입니다."
        )
        lines.append(s2)

        # Nearest site: name, distance, direction.
        ranked = sorted(
            items,
            key=lambda d: (
                float(d.get("distance_to_aoi_m")) if d.get("distance_to_aoi_m") is not None else float("inf")
            ),
        )
        if ranked:
            nearest = ranked[0]
            nm = str(nearest.get("name") or "").strip() or "(이름 없음)"
            dphrase = _distance_phrase(nearest.get("distance_to_aoi_m"))
            comp = str(nearest.get("compass_from_aoi") or "").strip()
            rel = _RELATION_KO.get(str(nearest.get("relation") or ""), "")
            bits = [f"가장 가까운 유적은 `{nm}`"]
            if comp:
                bits.append(f"AOI 중심 기준 {comp}쪽")
            if dphrase == "AOI에 접함":
                bits.append("AOI 경계에 접함")
            elif dphrase:
                bits.append(f"AOI 경계에서 {dphrase} 거리")
            if rel:
                bits.append(f"관계: {rel}")
            lines.append(", ".join(bits) + "에 위치합니다.")

            # Direction distribution among buffered sites.
            dir_tally: Dict[str, int] = {}
            for d in ranked:
                c = str(d.get("compass_from_aoi") or "").strip()
                if not c:
                    continue
                if str(d.get("relation") or "") == "outside_buffer":
                    continue
                dir_tally[c] = dir_tally.get(c, 0) + 1
            if dir_tally:
                top_dirs = sorted(dir_tally.items(), key=lambda kv: kv[1], reverse=True)[:2]
                dirs_txt = "·".join([f"{k}({v})" for k, v in top_dirs])
                lines.append(f"반경 내 유적은 주로 {dirs_txt} 방향에 분포합니다.")
    else:
        lines.append("추가 유적(관계 분석) 레이어는 사용되지 않았습니다.")

    return lines


def generate_report(ctx: Dict[str, Any]) -> str:
    aoi = ctx.get("aoi") or {}
    layers = ctx.get("layers") or []
    options = ctx.get("options") or {}

    aoi_name = str(aoi.get("layer_name") or "").strip()
    aoi_crs = str(aoi.get("crs") or "").strip()
    feat_n = aoi.get("feature_count")
    aoi_area = aoi.get("area_m2")

    radius_m = ctx.get("radius_m")
    buf_area = ctx.get("buffer_area_m2")

    selected_only = bool(options.get("selected_only")) if "selected_only" in options else None
    arch_only = bool(options.get("archtoolkit_only")) if "archtoolkit_only" in options else None

    mode_note = _first_nonempty(
        [
            "ArchToolkit 결과 중심 요약" if arch_only else None,
            "프로젝트 전체 요약" if arch_only is False else None,
        ]
    )
    sel_note = _first_nonempty(
        [
            "선택 피처만 사용" if selected_only else None,
            "레이어 전체 피처 사용" if selected_only is False else None,
        ]
    )

    header_notes = " / ".join([s for s in [mode_note, sel_note] if s])
    if header_notes:
        header_notes = f"({header_notes})"

    out: List[str] = []
    out.append("# AI 조사요약 (무료/로컬)")
    out.append("")

    # 0) Auto narrative (rule-based prose: direction / distance / relation)
    out.append("## 요약 서술(자동 생성)")
    try:
        for s in _narrative_lines(ctx):
            if s and s.strip():
                out.append(s.strip())
                out.append("")
    except Exception:
        out.append("(자동 서술 생성 실패 — 아래 세부 통계를 참고하세요.)")
        out.append("")

    # 1) Overview
    out.append("## 1) 개요")
    out.append(f"- AOI: `{aoi_name or '(이름 없음)'}`")
    out.append(f"- AOI 피처 수: {_fmt_int(feat_n)}")
    out.append(f"- AOI CRS: `{aoi_crs or '-'}`")
    out.append(f"- AOI 면적: {_fmt_float(aoi_area, digits=1)} ㎡")
    out.append(f"- 반경: {_fmt_float(radius_m, digits=0)} m")
    out.append(f"- 버퍼 면적(반경 내): {_fmt_float(buf_area, digits=1)} ㎡")
    out.append(f"- 요약 레이어 수: {_fmt_int(len(layers))} {header_notes}".rstrip())
    if isinstance(options.get("max_layers"), (int, float)) and len(layers) >= int(options.get("max_layers") or 0):
        out.append("- 참고: 레이어 수가 많아 일부만 요약되었을 수 있습니다.")
    out.append("")

    # 2) Layer summaries
    out.append("## 2) 레이어/분석 요약")
    if not layers:
        out.append("- (요약할 레이어가 없습니다)")
    else:
        for lyr in layers:
            name = str(lyr.get("name") or "").strip() or "(이름 없음)"
            ltype = str(lyr.get("type") or "")
            group_path = str(lyr.get("group_path") or "").strip()
            wkb = str(lyr.get("wkb") or "").strip()
            arch = lyr.get("archtoolkit") or {}
            tool_id = str((arch.get("tool_id") if isinstance(arch, dict) else "") or "").strip()
            run_id = str((arch.get("run_id") if isinstance(arch, dict) else "") or "").strip()
            kind = str((arch.get("kind") if isinstance(arch, dict) else "") or "").strip()
            units = str((arch.get("units") if isinstance(arch, dict) else "") or "").strip()
            created_at = str((arch.get("created_at") if isinstance(arch, dict) else "") or "").strip()

            meta_bits = []
            if ltype:
                meta_bits.append(ltype)
            if wkb:
                meta_bits.append(wkb)
            if group_path:
                meta_bits.append(group_path)
            meta = " | ".join(meta_bits)
            out.append(f"### - {name}")
            if meta:
                out.append(f"- 분류: {meta}")
            if tool_id or run_id:
                meta2 = []
                if tool_id:
                    meta2.append(f"tool_id={tool_id}")
                if kind:
                    meta2.append(f"kind={kind}")
                if units:
                    meta2.append(f"units={units}")
                if run_id:
                    meta2.append(f"run_id={run_id}")
                if created_at:
                    meta2.append(f"created_at={created_at}")
                out.append(f"- ArchToolkit 메타: {', '.join(meta2)}")
            out.extend(_layer_stats_lines(lyr))
            out.append("")

    # 3) Optional reference-site relation
    out.append("## 3) 추가 유적 관계")
    out.extend(_reference_sites_lines(ctx))
    out.append("")

    # 4) Key observations (heuristic)
    out.append("## 4) 핵심 관찰(로컬 자동 요약)")
    observations: List[str] = []
    try:
        # Find the biggest vector layer by feature count
        vec = []
        for lyr in layers:
            if str(lyr.get("type") or "") != "vector":
                continue
            stats = lyr.get("stats") or {}
            vec.append((int(stats.get("features") or 0), str(lyr.get("name") or "")))
        vec.sort(reverse=True)
        if vec and vec[0][0] > 0:
            observations.append(f"- 주변에서 가장 많은 피처가 겹치는 레이어: `{vec[0][1]}` ({_fmt_int(vec[0][0])}개)")
    except Exception:
        pass

    try:
        ras_vis = []
        for lyr in layers:
            if str(lyr.get("type") or "") != "raster":
                continue
            stats = lyr.get("stats") or {}
            if "gt_0_5_pct" in stats:
                ras_vis.append((float(stats.get("gt_0_5_pct") or 0.0), str(lyr.get("name") or "")))
        ras_vis.sort(reverse=True)
        if ras_vis:
            observations.append(
                f"- (힌트) 0.5 초과 비율이 높은 래스터: `{ras_vis[0][1]}` ({_fmt_float(ras_vis[0][0], digits=1)}%)"
            )
    except Exception:
        pass

    if not observations:
        observations.append("- (특이사항 자동 추출 없음) 위 레이어별 통계를 참고해 해석하세요.")

    out.extend(observations)
    out.append("")

    # 5) Limits
    out.append("## 5) 한계/주의")
    out.append("- 이 보고서는 **외부 AI를 호출하지 않는 로컬 요약**입니다(문장 품질/해석은 제한적).")
    out.append("- 통계는 AOI 버퍼와의 교차/표본 기반이며, 레이어 품질(좌표계/해상도/NoData)에 따라 달라질 수 있습니다.")
    out.append("- 레이어가 많거나(레이어 cap), 피처가 매우 많으면(스캔 cap) 일부만 반영되었을 수 있습니다.")
    out.append("")

    # 6) Next steps
    out.append("## 6) 다음 단계 제안")
    out.append("- 필요하면 `AI 모드: Gemini(API)`로 전환해 더 자연어 중심의 보고서 문장을 생성합니다.")
    out.append("- 해석에 중요한 레이어는 이름/그룹을 정리하고(민감정보 제거) 다시 요약을 생성합니다.")
    out.append("- 최종 보고서에는 원자료/방법/좌표계/해상도 등을 함께 기록하세요.")
    out.append("")

    return "\n".join(out).strip() + "\n"
