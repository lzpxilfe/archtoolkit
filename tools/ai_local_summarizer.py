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

from .i18n import is_english_ui, tr


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
    english = is_english_ui()
    t = str(layer.get("type") or "")
    stats = layer.get("stats")
    if not stats:
        return ["- Stats: (none / failed to compute)" if english else "- 통계: (없음/계산 실패)"]

    lines: List[str] = []

    if t == "vector":
        n = stats.get("features")
        scanned = stats.get("scanned")
        lines.append(
            f"- Features: {_fmt_int(n)} (scanned {_fmt_int(scanned)})"
            if english
            else f"- 피처: {_fmt_int(n)} (스캔 {_fmt_int(scanned)})"
        )

        if "total_length_m" in stats:
            lines.append(
                f"- Total length: {_fmt_float(stats.get('total_length_m'), digits=1)} m"
                if english
                else f"- 총 길이: {_fmt_float(stats.get('total_length_m'), digits=1)} m"
            )
        if "total_area_m2" in stats:
            lines.append(
                f"- Total area: {_fmt_float(stats.get('total_area_m2'), digits=1)} m²"
                if english
                else f"- 총 면적: {_fmt_float(stats.get('total_area_m2'), digits=1)} ㎡"
            )

        top_field = stats.get("top_field")
        top_vals = stats.get("top_values") or []
        if top_field and top_vals:
            preview = ", ".join([f"{d.get('value')}={_fmt_int(d.get('count'))}" for d in top_vals[:6]])
            if preview:
                lines.append(
                    f"- Top values ({top_field}): {preview}"
                    if english
                    else f"- 상위 값({top_field}): {preview}"
                )

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
                    f"- {f}: mean={_fmt_float(d.get('mean'), digits=2)} "
                    f"(min={_fmt_float(d.get('min'), digits=2)}, "
                    f"max={_fmt_float(d.get('max'), digits=2)}, "
                    f"n={_fmt_int(d.get('n'))})"
                )

        dist = stats.get("dist_to_aoi_centroid_m")
        if isinstance(dist, dict) and dist.get("n"):
            lines.append(
                (
                    f"- Distance to AOI centroid: mean={_fmt_float(dist.get('mean'), digits=1)} m "
                    f"(min={_fmt_float(dist.get('min'), digits=1)}, "
                    f"max={_fmt_float(dist.get('max'), digits=1)}, "
                    f"n={_fmt_int(dist.get('n'))})"
                    if english
                    else f"- AOI 중심까지 거리: mean={_fmt_float(dist.get('mean'), digits=1)} m "
                    f"(min={_fmt_float(dist.get('min'), digits=1)}, "
                    f"max={_fmt_float(dist.get('max'), digits=1)}, "
                    f"n={_fmt_int(dist.get('n'))})"
                )
            )

    elif t == "raster":
        lines.append(f"- Pixels (samples): {_fmt_int(stats.get('count'))}" if english else f"- 픽셀(표본) 수: {_fmt_int(stats.get('count'))}")
        lines.append(
            f"- min/mean/max: {_fmt_float(stats.get('min'), digits=3)} / {_fmt_float(stats.get('mean'), digits=3)} / {_fmt_float(stats.get('max'), digits=3)}"
        )
        if "gt_0_5_pct" in stats:
            lines.append(
                f"- Hint: mask/visible ratio (>0.5): {_fmt_float(stats.get('gt_0_5_pct'), digits=1)} %"
                if english
                else f"- (힌트) 마스크/가시(>0.5) 비율: {_fmt_float(stats.get('gt_0_5_pct'), digits=1)} %"
            )
    else:
        lines.append("- Stats: (unsupported layer type)" if english else "- 통계: (지원되지 않는 레이어 타입)")

    return lines


def _layer_interpretation_lines(layer: Dict[str, Any]) -> List[str]:
    english = is_english_ui()
    interp = layer.get("archtoolkit_interpretation") or {}
    if not isinstance(interp, dict) or not interp:
        return []

    lines: List[str] = []
    summary = str(interp.get("summary") or "").strip()
    if summary:
        lines.append(f"- Interpretation: {summary}" if english else f"- 해석: {summary}")

    notes = [str(x).strip() for x in (interp.get("notes") or []) if str(x).strip()]
    if notes:
        lines.append(f"- Settings / context: {'; '.join(notes[:4])}" if english else f"- 설정/맥락: {'; '.join(notes[:4])}")

    metrics = [str(x).strip() for x in (interp.get("key_metrics") or []) if str(x).strip()]
    if metrics:
        lines.append(f"- Key metrics: {'; '.join(metrics[:4])}" if english else f"- 핵심 지표: {'; '.join(metrics[:4])}")

    return lines


def generate_report(ctx: Dict[str, Any]) -> str:
    english = is_english_ui()
    aoi = ctx.get("aoi") or {}
    layers = ctx.get("layers") or []
    runs = ctx.get("archtoolkit_runs") or []
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
            "Focused on ArchToolkit result layers" if english and arch_only else "ArchToolkit 결과 중심 요약" if arch_only else None,
            "Whole-project summary" if english and arch_only is False else "프로젝트 전체 요약" if arch_only is False else None,
        ]
    )
    sel_note = _first_nonempty(
        [
            "Using selected features only" if english and selected_only else "선택 피처만 사용" if selected_only else None,
            "Using all layer features" if english and selected_only is False else "레이어 전체 피처 사용" if selected_only is False else None,
        ]
    )

    header_notes = " / ".join([s for s in [mode_note, sel_note] if s])
    if header_notes:
        header_notes = f"({header_notes})"

    out: List[str] = []
    out.append("# AI AOI Report (Free / Local)" if english else "# AI 조사요약 (무료/로컬)")
    out.append("")

    # 1) Overview
    out.append("## 1) Overview" if english else "## 1) 개요")
    out.append(f"- AOI: `{aoi_name or ('(Unnamed)' if english else '(이름 없음)')}`")
    out.append(f"- AOI feature count: {_fmt_int(feat_n)}" if english else f"- AOI 피처 수: {_fmt_int(feat_n)}")
    out.append(f"- AOI CRS: `{aoi_crs or '-'}`")
    out.append(f"- AOI area: {_fmt_float(aoi_area, digits=1)} m²" if english else f"- AOI 면적: {_fmt_float(aoi_area, digits=1)} ㎡")
    out.append(f"- Radius: {_fmt_float(radius_m, digits=0)} m" if english else f"- 반경: {_fmt_float(radius_m, digits=0)} m")
    out.append(f"- Buffer area (within radius): {_fmt_float(buf_area, digits=1)} m²" if english else f"- 버퍼 면적(반경 내): {_fmt_float(buf_area, digits=1)} ㎡")
    out.append(
        (f"- Summarized layers: {_fmt_int(len(layers))} {header_notes}".rstrip())
        if english
        else f"- 요약 레이어 수: {_fmt_int(len(layers))} {header_notes}".rstrip()
    )
    if runs:
        out.append(f"- ArchToolkit run groups: {_fmt_int(len(runs))}" if english else f"- ArchToolkit 실행 묶음: {_fmt_int(len(runs))}")
    if isinstance(options.get("max_layers"), (int, float)) and len(layers) >= int(options.get("max_layers") or 0):
        out.append("- Note: only part of the layers may have been summarized because there were too many." if english else "- 참고: 레이어 수가 많아 일부만 요약되었을 수 있습니다.")
    out.append("")

    # 1.5) Run summaries
    out.append("## 1-1) ArchToolkit Run Groups" if english else "## 1-1) ArchToolkit 실행 묶음")
    if not runs:
        out.append("- (none)" if english else "- (해당 없음)")
    else:
        for run in runs[:10]:
            summary = str(run.get("summary") or "").strip() or ("ArchToolkit run group" if english else "ArchToolkit 실행 묶음")
            layer_names = [str(x).strip() for x in (run.get("layer_names") or []) if str(x).strip()]
            metrics = [str(x).strip() for x in (run.get("key_metrics") or []) if str(x).strip()]
            out.append(f"- {summary}: {len(layer_names)} layers" if english else f"- {summary}: 레이어 {len(layer_names)}개")
            if layer_names:
                out.append(f"  - Included layers: {', '.join(layer_names[:4])}" if english else f"  - 포함 레이어: {', '.join(layer_names[:4])}")
            if metrics:
                out.append(f"  - Representative metrics: {'; '.join(metrics[:3])}" if english else f"  - 대표 지표: {'; '.join(metrics[:3])}")
    out.append("")

    # 2) Layer summaries
    out.append("## 2) Layer / Analysis Summary" if english else "## 2) 레이어/분석 요약")
    if not layers:
        out.append("- (No layers to summarize)" if english else "- (요약할 레이어가 없습니다)")
    else:
        for lyr in layers:
            name = str(lyr.get("name") or "").strip() or ("(Unnamed)" if english else "(이름 없음)")
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
                out.append(f"- Category: {meta}" if english else f"- 분류: {meta}")
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
                out.append(f"- ArchToolkit metadata: {', '.join(meta2)}" if english else f"- ArchToolkit 메타: {', '.join(meta2)}")
            out.extend(_layer_interpretation_lines(lyr))
            out.extend(_layer_stats_lines(lyr))
            out.append("")

    # 3) Key observations (heuristic)
    out.append("## 3) Key Observations (Local Auto Summary)" if english else "## 3) 핵심 관찰(로컬 자동 요약)")
    observations: List[str] = []
    try:
        for run in runs[:6]:
            summary = str(run.get("summary") or "").strip()
            if not summary:
                continue
            metrics = [str(x).strip() for x in (run.get("key_metrics") or []) if str(x).strip()]
            if metrics:
                observations.append(f"- {summary}: {'; '.join(metrics[:2])}")
            else:
                observations.append(f"- {summary}")
    except Exception:
        pass

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
            observations.append(
                f"- Layer with the most overlapping features nearby: `{vec[0][1]}` ({_fmt_int(vec[0][0])})"
                if english
                else f"- 주변에서 가장 많은 피처가 겹치는 레이어: `{vec[0][1]}` ({_fmt_int(vec[0][0])}개)"
            )
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
                f"- Hint: raster with the highest ratio over 0.5: `{ras_vis[0][1]}` ({_fmt_float(ras_vis[0][0], digits=1)}%)"
                if english
                else f"- (힌트) 0.5 초과 비율이 높은 래스터: `{ras_vis[0][1]}` ({_fmt_float(ras_vis[0][0], digits=1)}%)"
            )
    except Exception:
        pass

    if not observations:
        observations.append(
            "- (No notable patterns were auto-extracted) Please interpret the layer-level statistics above."
            if english
            else "- (특이사항 자동 추출 없음) 위 레이어별 통계를 참고해 해석하세요."
        )

    out.extend(observations)
    out.append("")

    # 4) Limits
    out.append("## 4) Limits / Notes" if english else "## 4) 한계/주의")
    out.append(
        "- This report is a **local summary with no external AI call**; sentence quality and interpretation are therefore limited."
        if english
        else "- 이 보고서는 **외부 AI를 호출하지 않는 로컬 요약**입니다(문장 품질/해석은 제한적)."
    )
    out.append(
        "- Statistics are based on AOI-buffer intersections or samples and may vary with layer quality (CRS/resolution/NoData)."
        if english
        else "- 통계는 AOI 버퍼와의 교차/표본 기반이며, 레이어 품질(좌표계/해상도/NoData)에 따라 달라질 수 있습니다."
    )
    out.append(
        "- If there are many layers (layer cap) or too many features (scan cap), only part of the data may be reflected."
        if english
        else "- 레이어가 많거나(레이어 cap), 피처가 매우 많으면(스캔 cap) 일부만 반영되었을 수 있습니다."
    )
    out.append("")

    # 5) Next steps
    out.append("## 5) Suggested Next Steps" if english else "## 5) 다음 단계 제안")
    out.append(
        "- If needed, switch to `AI mode: Gemini (API)` to generate a more natural-language report."
        if english
        else "- 필요하면 `AI 모드: Gemini(API)`로 전환해 더 자연어 중심의 보고서 문장을 생성합니다."
    )
    out.append(
        "- For layers that matter most to interpretation, clean up names/groups and regenerate the summary after removing sensitive information."
        if english
        else "- 해석에 중요한 레이어는 이름/그룹을 정리하고(민감정보 제거) 다시 요약을 생성합니다."
    )
    out.append(
        "- In the final report, record the raw data, method, CRS, resolution, and similar metadata together."
        if english
        else "- 최종 보고서에는 원자료/방법/좌표계/해상도 등을 함께 기록하세요."
    )
    out.append("")

    return tr("\n".join(out).strip() + "\n")
