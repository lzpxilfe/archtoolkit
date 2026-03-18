# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


_DEFAULT_CONFIG = {
    "plugin": {
        "output_groups": {
            "ahp": "ArchToolkit - AHP",
            "cadastral": "ArchToolkit - Cadastral",
            "cost_network": "ArchToolkit - 최소비용 네트워크 (Least-cost Network)",
            "cost_surface": "ArchToolkit - 비용표면/최소비용경로 (Cost Surface / LCP)",
            "geochem": "ArchToolkit - GeoChem",
            "geology": "ArchToolkit - Geology",
            "spatial_network": "ArchToolkit - Networks (PPA/Visibility)",
            "slope_aspect_drafting": "ArchToolkit - 도면화(경사도/사면방향) (Slope/Aspect Drafting)",
            "terrain_profile": "ArchToolkit - Terrain Profile",
            "viewshed_los": "ArchToolkit - 가시선",
        },
        "output_group_prefixes": ["ArchToolkit -"],
        "ui": {
            "help_dialog": {
                "min_width": 760,
                "min_height": 560,
                "search_placeholder": "도움말 검색...",
                "hint_text": "이 도움말은 검색하고 복사할 수 있습니다. 입력 전에 한 번 훑어보면 실수를 줄일 수 있어요.",
            }
        },
    },
    "ai": {
        "gemini": {
            "default_model": "gemini-3.1-pro-preview",
            "known_models_verified_at": "2026-03-15",
            "known_models_stale_after_days": 14,
            "known_models": [
                "gemini-3.1-pro-preview",
                "gemini-3-flash-preview",
                "gemini-3.1-flash-lite-preview",
                "gemini-2.5-pro",
                "gemini-2.5-flash",
            ],
        }
    },
    "contour_extractor": {
        "dxf_filter_field_candidates": ["Layer", "LAYER", "layer"],
        "code_presets": [
            {"code": "F0017110", "label": "주곡선", "default_checked": True},
            {"code": "F0017111", "label": "계곡선", "default_checked": True},
            {"code": "F0017112", "label": "간곡선", "default_checked": True},
            {"code": "F0017113", "label": "조곡선", "default_checked": False},
        ],
    },
    "geology_zip": {
        "extract_root_name": "ArchToolkit_KIGAM_Extract",
        "extract_cleanup_days": 14,
        "provider_encoding": "cp949",
        "candidate_encodings": ["CP949", "EUC-KR", None, "UTF-8"],
        "encoding_preference": {
            "CP949": 4,
            "EUC-KR": 3,
            "default": 2,
            "UTF-8": 1,
        },
        "qml_write_encoding": "UTF-8",
        "ui": {
            "font_size_min": 5,
            "font_size_max": 50,
            "font_size_default": 10,
            "pixel_size_min": 0.1,
            "pixel_size_max": 10000.0,
            "pixel_size_default": 10.0,
            "nodata_min": -9999999.0,
            "nodata_max": 9999999.0,
            "nodata_decimals": 2,
            "nodata_default": -9999.0,
        },
        "symbology": {
            "point_marker_size": 6.0,
            "polygon_fill_width": 10.0,
            "symbol_priority_fields": [
                "LITHOIDX",
                "TYPE",
                "ASGN_CODE",
                "SIGN",
                "CODE",
                "AGEIDX",
            ],
            "label_field_candidates": ["LITHOIDX", "LITHONAME"],
            "frame_layer_keywords": ["frame"],
            "reference_hide_keywords": ["frame", "crosssection", "crosssectionline"],
            "litho_layer_keyword": "litho",
        },
        "raster": {
            "field_priority": [
                "LITHOIDX",
                "AGEIDX",
                "LITHONAME",
                "TYPE",
                "ASGN_CODE",
                "SIGN",
                "CODE",
            ],
            "name_field_candidates": ["LITHONAME", "AGENAME", "NAME", "KOR_NAME", "ENG_NAME"],
        },
    },
}

_CONFIG_CACHE = None


def _config_path() -> Path:
    return Path(__file__).resolve().with_name("plugin_config.json")


def _deep_merge(base: Any, override: Any) -> Any:
    if not isinstance(base, dict) or not isinstance(override, dict):
        return copy.deepcopy(override)

    out = copy.deepcopy(base)
    for key, value in override.items():
        if key in out:
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_plugin_config(*, force_reload: bool = False) -> dict:
    global _CONFIG_CACHE

    if _CONFIG_CACHE is not None and not force_reload:
        return copy.deepcopy(_CONFIG_CACHE)

    cfg = copy.deepcopy(_DEFAULT_CONFIG)
    path = _config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg = _deep_merge(cfg, raw)
    except Exception:
        pass

    _CONFIG_CACHE = cfg
    return copy.deepcopy(cfg)


def get_plugin_config_value(*keys, default=None):
    cur: Any = load_plugin_config()
    for key in keys:
        if not isinstance(cur, dict):
            return copy.deepcopy(default)
        if key not in cur:
            return copy.deepcopy(default)
        cur = cur[key]
    return copy.deepcopy(cur)


def get_output_group_name(group_key: str, default: str = "") -> str:
    value = get_plugin_config_value("plugin", "output_groups", str(group_key or ""), default=default)
    out = str(value or "").strip()
    return out or str(default or "").strip()


def get_output_group_names() -> dict[str, str]:
    values = get_plugin_config_value("plugin", "output_groups", default={})
    out: dict[str, str] = {}
    if not isinstance(values, dict):
        return out
    for key, value in values.items():
        key0 = str(key or "").strip()
        value0 = str(value or "").strip()
        if key0 and value0:
            out[key0] = value0
    return out


def get_output_group_prefixes() -> list[str]:
    values = get_plugin_config_value("plugin", "output_group_prefixes", default=[])
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def is_archtoolkit_group_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    if text in set(get_output_group_names().values()):
        return True
    return any(text.startswith(prefix) for prefix in get_output_group_prefixes())


def get_contour_code_presets() -> list[dict[str, Any]]:
    values = get_plugin_config_value("contour_extractor", "code_presets", default=[])
    raw = values if isinstance(values, list) else []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        label = str(item.get("label") or code).strip() or code
        if not code:
            continue
        out.append(
            {
                "code": code,
                "label": label,
                "default_checked": bool(item.get("default_checked", True)),
            }
        )
    return out


def get_contour_filter_field_candidates() -> list[str]:
    values = get_plugin_config_value("contour_extractor", "dxf_filter_field_candidates", default=[])
    raw = values if isinstance(values, list) else []
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out
