# -*- coding: utf-8 -*-

import os

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QDateTime, QPoint, Qt, QEvent
from qgis.PyQt.QtGui import QFontDatabase
from qgis.core import Qgis

from .utils import log_swallowed, add_ui_log_listener, get_log_path, remove_ui_log_listener, start_ui_log_pump

_live_log_dialog = None


def _level_name(level) -> str:
    try:
        if level == Qgis.Warning:
            return "WARN"
        if level == Qgis.Critical:
            return "ERROR"
        if level == Qgis.Success:
            return "OK"
    except Exception as _exc:
        log_swallowed("live_log_dialog._level_name", _exc)
    return "INFO"


def _read_metadata() -> dict:
    """Read metadata.txt (best-effort) to populate header links/version."""
    try:
        plugin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        path = os.path.join(plugin_root, "metadata.txt")
        if not os.path.exists(path):
            return {}

        out = {}
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or line.startswith("["):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k and v and k not in out:
                    out[k] = v
        return out
    except Exception:
        return {}


class ArchToolkitLiveLogDialog(QtWidgets.QDialog):
    """Lightweight, non-modal live log window for long-running tools."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ArchToolkit 작업 로그")
        try:
            self.setWindowFlag(Qt.Tool, True)
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:62 (__init__)", _exc)
        try:
            self.setModal(False)
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:66 (__init__)", _exc)

        self._owner = None

        self._txt = QtWidgets.QPlainTextEdit(self)
        self._txt.setReadOnly(True)
        self._txt.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        try:
            self._txt.document().setMaximumBlockCount(5000)
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:76 (__init__)", _exc)
        try:
            fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
            if fixed_font is not None:
                self._txt.setFont(fixed_font)
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:82 (__init__)", _exc)

        btn_clear = QtWidgets.QPushButton("비우기", self)
        btn_close = QtWidgets.QPushButton("닫기", self)
        btn_clear.clicked.connect(self.clear)
        btn_close.clicked.connect(self.close)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(btn_clear)
        btn_row.addWidget(btn_close)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self._txt, 1)
        layout.addLayout(btn_row)
        self.setLayout(layout)

        self._listener = self._on_log
        add_ui_log_listener(self._listener)
        try:
            self.destroyed.connect(lambda *_: remove_ui_log_listener(self._listener))
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:104 (__init__)", _exc)

        try:
            self.resize(520, 360)
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:109 (__init__)", _exc)

        # Initial header (helps users know where to report errors / license).
        try:
            self.write_header()
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:115 (__init__)", _exc)

    def clear(self):
        try:
            self._txt.clear()
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:121 (clear)", _exc)
        try:
            self.write_header()
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:125 (clear)", _exc)

    def write_header(self):
        meta = _read_metadata()
        tracker = meta.get("tracker", "")
        author = meta.get("author", "balguljang2")
        license_name = meta.get("license", "GPL v3")

        lines = []
        title = "ArchToolkit 작업 로그"
        lines.append(title)
        lines.append("- 진행상황/오류가 여기에 실시간으로 기록됩니다.")
        if tracker:
            lines.append(f"- 오류/제안 제보: {tracker}")
        else:
            lines.append("- 오류/제안 제보: GitHub Issues (repo tracker)")
        try:
            lines.append(f"- 로그 파일: {get_log_path()}")
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:144 (write_header)", _exc)
        lines.append(f"- Copyright (C) 2026 {author}  ·  License: {license_name}")
        lines.append("- 참고문헌/모델 출처: REFERENCES.md")
        lines.append("-" * 60)
        for ln in lines:
            try:
                self._txt.appendPlainText(str(ln))
            except Exception as _exc:
                log_swallowed("tools/live_log_dialog.py:152 (write_header)", _exc)

    def _on_log(self, message: str, level):
        try:
            ts = QDateTime.currentDateTime().toString("HH:mm:ss")
            lvl = _level_name(level)
            self._txt.appendPlainText(f"[{ts}] [{lvl}] {message}")
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:160 (_on_log)", _exc)

    def _reposition_near_owner(self):
        try:
            owner = self._owner
            if owner is not None:
                g = owner.frameGeometry()
                w = int(self.width() or 520)
                h = int(self.height() or 360)

                # Avoid positioning far off-screen (best-effort).
                screen = None
                try:
                    center = g.center()
                    # Use the screen where the owner window is located (multi-monitor safe).
                    for s in QtWidgets.QApplication.screens() or []:
                        _skip_177 = False
                        try:
                            if s.availableGeometry().contains(center):
                                screen = s
                                break
                        except Exception as _exc:
                            log_swallowed("tools/live_log_dialog.py:181 (_reposition_near_owner)", _exc)
                            _skip_177 = True
                        if _skip_177:
                            continue
                except Exception:
                    screen = None

                if screen is None:
                    try:
                        screen = QtWidgets.QApplication.primaryScreen()
                    except Exception:
                        screen = None

                if screen is not None:
                    avail = screen.availableGeometry()
                    x_right = int(g.right() + 12)
                    x_left = int(g.left() - 12 - w)

                    # Prefer right side; fallback to left side if it doesn't fit.
                    if x_right + w <= avail.right():
                        x = x_right
                    else:
                        x = x_left

                    y = int(g.top())
                    x = max(avail.left(), min(avail.right() - w, x))
                    y = max(avail.top(), min(avail.bottom() - h, y))
                else:
                    x = int(g.right() + 12)
                    y = int(g.top())

                self.move(QPoint(x, y))
        except Exception as _exc:
            log_swallowed("live_log_dialog._reposition_near_owner", _exc)

    def attach_owner(self, owner=None):
        if owner is self._owner:
            return

        # Detach previous owner tracking.
        try:
            if self._owner is not None:
                try:
                    self._owner.removeEventFilter(self)
                except Exception as _exc:
                    log_swallowed("tools/live_log_dialog.py:223 (attach_owner)", _exc)
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:225 (attach_owner)", _exc)

        self._owner = owner
        if owner is None:
            return

        try:
            owner.installEventFilter(self)
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:234 (attach_owner)", _exc)

        # Position immediately if we're already visible.
        if self.isVisible():
            self._reposition_near_owner()

    def eventFilter(self, obj, event):  # noqa: N802 (Qt naming)
        try:
            if obj is self._owner and event is not None:
                et = int(event.type())
                if et in (QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.WindowStateChange):
                    if self.isVisible():
                        self._reposition_near_owner()
        except Exception as _exc:
            log_swallowed("live_log_dialog.eventFilter", _exc)
        return super().eventFilter(obj, event)

    def show_near(self, owner=None):
        """Show window near the owner dialog (sticky), best-effort."""
        try:
            self.attach_owner(owner)
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:256 (show_near)", _exc)

        self._reposition_near_owner()

        try:
            self.show()
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:263 (show_near)", _exc)
        try:
            self.raise_()
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:267 (show_near)", _exc)


def ensure_live_log_dialog(iface=None, *, owner=None, show: bool = True, clear: bool = False):
    """Return a singleton live log dialog; optionally show it next to `owner`."""
    global _live_log_dialog

    try:
        start_ui_log_pump()
    except Exception as _exc:
        log_swallowed("tools/live_log_dialog.py:277 (ensure_live_log_dialog)", _exc)

    parent = None
    try:
        if iface is not None and hasattr(iface, "mainWindow"):
            parent = iface.mainWindow()
    except Exception:
        parent = None

    if _live_log_dialog is None:
        _live_log_dialog = ArchToolkitLiveLogDialog(parent=parent)
    else:
        # Re-parent if needed (best-effort).
        try:
            if parent is not None and _live_log_dialog.parent() is None:
                _live_log_dialog.setParent(parent)
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:294 (ensure_live_log_dialog)", _exc)

    if clear:
        try:
            _live_log_dialog.clear()
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:300 (ensure_live_log_dialog)", _exc)

    if show:
        try:
            _live_log_dialog.show_near(owner)
        except Exception as _exc:
            log_swallowed("tools/live_log_dialog.py:306 (ensure_live_log_dialog)", _exc)

    return _live_log_dialog
