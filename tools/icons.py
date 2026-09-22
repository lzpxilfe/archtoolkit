# -*- coding: utf-8 -*-
"""Locate the plugin's icons.

Icons live in ``<plugin>/icons/`` as 256 px PNGs (one XPM). Older layouts kept
them at the plugin root or under ``tools/``, so those folders are searched too,
which keeps a half-updated install working. A miss falls back to the toolkit
icon, and to an empty QIcon only when nothing at all is found, so a missing
file can never raise during ``initGui``.
"""
from __future__ import annotations

import os
from typing import Optional

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SEARCH_DIRS = (
    os.path.join(_PLUGIN_DIR, "icons"),
    _PLUGIN_DIR,
    os.path.join(_PLUGIN_DIR, "tools"),
)
MAIN_ICON = "archtoolkit.png"


def icon_path(*names: str, default: Optional[str] = MAIN_ICON) -> str:
    """First existing icon file among ``names`` (then ``default``), or ""."""
    candidates = [str(n) for n in names if n]
    if default:
        candidates.append(str(default))
    for name in candidates:
        for folder in _SEARCH_DIRS:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return path
    return ""


def icon(*names: str, default: Optional[str] = MAIN_ICON):
    """QIcon for the first existing icon among ``names``; an empty QIcon if none."""
    from qgis.PyQt.QtGui import QIcon

    path = icon_path(*names, default=default)
    return QIcon(path) if path else QIcon()


__all__ = ["MAIN_ICON", "icon", "icon_path"]
