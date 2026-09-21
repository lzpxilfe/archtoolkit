# -*- coding: utf-8 -*-
"""Remember a dialog's last-used inputs between sessions.

Every tool dialog re-asked every parameter each time it opened; a user running
the same analysis over several map sheets typed the same values again and
again. :func:`restore` and :func:`save` persist the ordinary input widgets of a
dialog under ``ArchToolkit/dialogs/<key>/<objectName>`` in QgsSettings.

What is remembered: QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox (by data
when it has any, else by text), QLineEdit, and QgsMapLayerComboBox (by layer
NAME, restored only when a layer of that name is in the project). Widgets
without an objectName, and widgets listed in ``skip``, are ignored. Restoring
never raises: a stale or invalid stored value is simply skipped, so a dialog
that fails to restore still opens with its defaults.
"""
from __future__ import annotations

import os
import re
from typing import Iterable

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QTimer
from qgis.core import QgsProject, QgsSettings

from .swallow_log import log_swallowed

try:
    from qgis.gui import QgsMapLayerComboBox
except Exception:  # pragma: no cover - headless import paths
    QgsMapLayerComboBox = None  # type: ignore

_PREFIX = "ArchToolkit/dialogs"
# Set by test harnesses so remembered values never leak into a scripted run.
_DISABLE_ENV = "ARCHTOOLKIT_NO_DIALOG_MEMORY"
# Line edits that hold paths or secrets are never remembered: an output path
# restored blindly overwrites the previous result, and a key must not sit in
# plain settings under a generic name.
_SENSITIVE_LINEEDIT_RE = re.compile(r"(out|path|file|dir|folder|key|token|secret|api|password)", re.IGNORECASE)


def _widgets(dialog: QtWidgets.QWidget, skip: Iterable[str]) -> list:
    skip_set = set(str(s) for s in (skip or ()))
    out = []
    for w in dialog.findChildren(QtWidgets.QWidget):
        name = str(w.objectName() or "")
        if not name or name.startswith("qt_") or name in skip_set:
            continue
        if isinstance(w, QtWidgets.QLineEdit) and _SENSITIVE_LINEEDIT_RE.search(name):
            continue
        out.append((name, w))
    return out


def save(dialog: QtWidgets.QWidget, key: str, *, skip: Iterable[str] = ()) -> int:
    """Persist the dialog's input widgets; returns how many values were written."""
    n = 0
    try:
        settings = QgsSettings()
    except Exception as exc:
        log_swallowed("dialog_memory.save", exc)
        return 0
    base = f"{_PREFIX}/{key}"
    for name, w in _widgets(dialog, skip):
        try:
            if QgsMapLayerComboBox is not None and isinstance(w, QgsMapLayerComboBox):
                lyr = w.currentLayer()
                if lyr is not None:
                    settings.setValue(f"{base}/{name}/layer_name", str(lyr.name()))
                    n += 1
            elif isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                settings.setValue(f"{base}/{name}/value", w.value())
                n += 1
            elif isinstance(w, QtWidgets.QCheckBox):
                settings.setValue(f"{base}/{name}/checked", bool(w.isChecked()))
                n += 1
            elif isinstance(w, QtWidgets.QComboBox):
                data = w.currentData()
                if data is not None and not isinstance(data, (list, dict)):
                    settings.setValue(f"{base}/{name}/data", data)
                else:
                    settings.setValue(f"{base}/{name}/text", str(w.currentText()))
                n += 1
            elif isinstance(w, QtWidgets.QLineEdit):
                settings.setValue(f"{base}/{name}/text", str(w.text()))
                n += 1
        except Exception as exc:
            log_swallowed("dialog_memory.save", exc)
    return n


def restore(dialog: QtWidgets.QWidget, key: str, *, skip: Iterable[str] = ()) -> int:
    """Apply remembered values to the dialog's widgets; returns how many were applied."""
    n = 0
    try:
        settings = QgsSettings()
    except Exception as exc:
        log_swallowed("dialog_memory.restore", exc)
        return 0
    base = f"{_PREFIX}/{key}"
    project = QgsProject.instance()
    for name, w in _widgets(dialog, skip):
        try:
            if QgsMapLayerComboBox is not None and isinstance(w, QgsMapLayerComboBox):
                wanted = settings.value(f"{base}/{name}/layer_name", None)
                if wanted:
                    matches = project.mapLayersByName(str(wanted))
                    if matches:
                        w.setLayer(matches[0])
                        n += 1
            elif isinstance(w, QtWidgets.QSpinBox):
                v = settings.value(f"{base}/{name}/value", None)
                if v is not None:
                    w.setValue(int(float(v)))
                    n += 1
            elif isinstance(w, QtWidgets.QDoubleSpinBox):
                v = settings.value(f"{base}/{name}/value", None)
                if v is not None:
                    w.setValue(float(v))
                    n += 1
            elif isinstance(w, QtWidgets.QCheckBox):
                v = settings.value(f"{base}/{name}/checked", None)
                if v is not None:
                    w.setChecked(str(v).lower() in ("true", "1", "yes"))
                    n += 1
            elif isinstance(w, QtWidgets.QComboBox):
                data = settings.value(f"{base}/{name}/data", None)
                if data is not None:
                    idx = w.findData(data)
                    if idx < 0:
                        # QSettings may hand numbers back as strings
                        for i in range(w.count()):
                            if str(w.itemData(i)) == str(data):
                                idx = i
                                break
                    if idx >= 0:
                        w.setCurrentIndex(idx)
                        n += 1
                else:
                    text = settings.value(f"{base}/{name}/text", None)
                    if text is not None:
                        idx = w.findText(str(text))
                        if idx >= 0:
                            w.setCurrentIndex(idx)
                            n += 1
            elif isinstance(w, QtWidgets.QLineEdit):
                text = settings.value(f"{base}/{name}/text", None)
                if text is not None and not w.text():
                    w.setText(str(text))
                    n += 1
        except Exception as exc:
            log_swallowed("dialog_memory.restore", exc)
    return n


def attach(dialog: QtWidgets.QDialog, key: str, *, skip: Iterable[str] = ()) -> None:
    """Restore once the dialog is up, and save when it closes.

    Called right after ``super().__init__`` in a dialog constructor: the
    restore is deferred with a zero-delay timer so it runs after the whole
    constructor has built and populated its widgets, and the save hangs on
    QDialog.finished so accept, reject and the window close button all
    persist what the user last entered. A no-op when the environment sets
    ARCHTOOLKIT_NO_DIALOG_MEMORY (scripted runs).
    """
    if os.environ.get(_DISABLE_ENV):
        return
    try:
        QTimer.singleShot(0, lambda: restore(dialog, key, skip=skip))
    except Exception as exc:
        log_swallowed("dialog_memory.attach", exc)
    try:
        dialog.finished.connect(lambda _result: save(dialog, key, skip=skip))
    except Exception as exc:
        log_swallowed("dialog_memory.attach", exc)


def forget(key: str) -> None:
    """Drop everything remembered for one dialog key."""
    try:
        QgsSettings().remove(f"{_PREFIX}/{key}")
    except Exception as exc:
        log_swallowed("dialog_memory.forget", exc)


__all__ = ["attach", "save", "restore", "forget"]
