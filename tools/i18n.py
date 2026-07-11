# -*- coding: utf-8 -*-
"""Config + UI language helpers for ArchToolkit.

This module provides the small config/i18n API used across the tool dialogs:

- ``get_plugin_config_value(*keys, default=None)``: read a nested value from an
  optional user config file (``<plugin_dir>/config.json``). Missing file/keys
  fall back to ``default`` so the plugin always works out of the box.
- ``get_output_group_name(tool_key, default)``: resolve the layer-tree group
  name a tool files its outputs under (user-overridable via config.json).
- ``is_english_ui()`` / ``set_ui_language(lang)``: selectable Korean/English UI.
  Language is stored in QSettings (``ArchToolkit/ui/language``: "ko", "en" or
  "auto"); "auto" follows the QGIS locale.
- ``tr(text)``: translate a known Korean UI string to English when the English
  UI is active; unknown strings pass through unchanged (never crashes).

Everything here is best-effort: any failure falls back to defaults instead of
raising, because these helpers run at import time in several dialogs.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

_CONFIG_CACHE: Optional[dict] = None
_CONFIG_LOADED = False


def _plugin_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_config() -> dict:
    """Load <plugin_dir>/config.json once (optional user overrides)."""
    global _CONFIG_CACHE, _CONFIG_LOADED
    if _CONFIG_LOADED:
        return _CONFIG_CACHE or {}
    _CONFIG_LOADED = True
    _CONFIG_CACHE = {}
    try:
        path = os.path.join(_plugin_dir(), "config.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _CONFIG_CACHE = data
    except Exception:
        _CONFIG_CACHE = {}
    return _CONFIG_CACHE


def reload_plugin_config() -> None:
    """Drop the config cache so the next lookup re-reads config.json."""
    global _CONFIG_CACHE, _CONFIG_LOADED
    _CONFIG_CACHE = None
    _CONFIG_LOADED = False


def get_plugin_config_value(*keys: str, default: Any = None) -> Any:
    """Return a nested config value, e.g. ``get_plugin_config_value("geology_zip", "extract_root_name", default=...)``.

    Falls back to ``default`` when config.json is absent or the path is missing.
    """
    try:
        node: Any = _load_config()
        for key in keys:
            if not isinstance(node, dict):
                return default
            if key not in node:
                return default
            node = node[key]
        return node if node is not None else default
    except Exception:
        return default


def get_output_group_name(tool_key: str, default: str) -> str:
    """Layer-tree group name for a tool's outputs (user-overridable)."""
    try:
        value = get_plugin_config_value("output_groups", str(tool_key or ""), default=None)
        text = str(value or "").strip()
        return text or str(default or "")
    except Exception:
        return str(default or "")


_LANGUAGE_SETTINGS_KEY = "ArchToolkit/ui/language"


def get_ui_language() -> str:
    """Return the configured UI language: "ko", "en" or "auto"."""
    try:
        from qgis.PyQt.QtCore import QSettings

        value = str(QSettings().value(_LANGUAGE_SETTINGS_KEY, "") or "").strip().lower()
        if value in ("ko", "en", "auto"):
            return value
    except Exception:
        pass
    cfg = str(get_plugin_config_value("ui", "language", default="") or "").strip().lower()
    if cfg in ("ko", "en", "auto"):
        return cfg
    return "auto"


def set_ui_language(lang: str) -> None:
    """Persist the UI language ("ko", "en" or "auto")."""
    value = str(lang or "").strip().lower()
    if value not in ("ko", "en", "auto"):
        value = "auto"
    try:
        from qgis.PyQt.QtCore import QSettings

        QSettings().setValue(_LANGUAGE_SETTINGS_KEY, value)
    except Exception:
        pass


def _qgis_locale_is_english() -> bool:
    try:
        from qgis.PyQt.QtCore import QSettings

        override = QSettings().value("locale/overrideFlag", False)
        if override in (True, "true", "True", 1, "1"):
            locale = str(QSettings().value("locale/userLocale", "") or "")
        else:
            from qgis.PyQt.QtCore import QLocale

            locale = str(QLocale.system().name() or "")
        return locale.strip().lower().startswith("en")
    except Exception:
        return False


def is_english_ui() -> bool:
    """True when tool dialogs should show English labels/messages."""
    lang = get_ui_language()
    if lang == "en":
        return True
    if lang == "ko":
        return False
    return _qgis_locale_is_english()


# Korean -> English strings for the few UI texts routed through tr().
# Unknown strings pass through unchanged, so missing entries are harmless.
_TRANSLATIONS = {
    "다음": "Next",
    "이전": "Previous",
    "지우기": "Clear",
    "복사": "Copy",
    "닫기": "Close",
    "도움말": "Help",
    "도움말 검색...": "Search help...",
    "이 도움말은 검색하고 복사할 수 있습니다.": "You can search and copy this help text.",
    "※ Gemini 호출 실패로 로컬 요약으로 대체했습니다.\n\n": (
        "Note: Gemini failed, so the result was replaced with a local summary.\n\n"
    ),
}


def tr(text: str) -> str:
    """Translate a known Korean UI string when the English UI is active."""
    try:
        s = str(text or "")
        if not s:
            return s
        if not is_english_ui():
            return s
        return _TRANSLATIONS.get(s, s)
    except Exception:
        return text
