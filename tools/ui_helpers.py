# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from typing import Iterable, Optional

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtGui import QIcon

_HINT_PALETTE = {
    "info": ("#e3f2fd", "#bbdefb", "#1e3a5f"),
    "tip": ("#f1f8e9", "#dcedc8", "#355724"),
    "warn": ("#fff3e0", "#ffe0b2", "#8a4b00"),
}


def plugin_base_dir() -> str:
    return os.path.dirname(os.path.dirname(__file__))


def find_plugin_resource(candidates: Iterable[str]) -> str:
    base_dir = plugin_base_dir()
    for candidate in tuple(candidates or ()):
        try:
            relative_path = str(candidate or "").strip()
        except Exception:
            relative_path = ""
        if not relative_path:
            continue
        full_path = os.path.join(base_dir, relative_path)
        if os.path.exists(full_path):
            return full_path
    return ""


def set_plugin_window_icon(widget, candidates: Iterable[str]) -> str:
    if widget is None:
        return ""
    icon_path = find_plugin_resource(candidates)
    if not icon_path:
        return ""
    try:
        widget.setWindowIcon(QIcon(icon_path))
    except Exception:
        return ""
    return icon_path


def insert_help_button(
    *,
    dialog,
    callback,
    close_button=None,
    layout=None,
    text: str = "도움말",
) -> Optional[QtWidgets.QPushButton]:
    if dialog is None or callback is None:
        return None
    try:
        button = QtWidgets.QPushButton(str(text or "도움말"), dialog)
        button.clicked.connect(callback)
    except Exception:
        return None

    target_layout = layout
    if target_layout is None:
        try:
            target_layout = dialog.layout()
        except Exception:
            target_layout = None
    if target_layout is None:
        return button

    try:
        if close_button is not None:
            idx = int(target_layout.indexOf(close_button))
            if idx >= 0:
                target_layout.insertWidget(idx, button)
                return button
    except Exception:
        pass

    try:
        target_layout.addWidget(button)
    except Exception:
        return None
    return button


def apply_hint_label_style(label, *, tone: str = "info") -> None:
    if label is None:
        return
    bg, border, color = _HINT_PALETTE.get(str(tone or "info"), _HINT_PALETTE["info"])
    label.setStyleSheet(
        f"background:{bg}; border:1px solid {border}; color:{color}; "
        "padding:8px; border-radius:4px;"
    )


def create_hint_label(text: str, *, tone: str = "info", parent=None) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(str(text or ""), parent)
    label.setWordWrap(True)
    apply_hint_label_style(label, tone=tone)
    return label
