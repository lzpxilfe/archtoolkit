# -*- coding: utf-8 -*-
import json
import os
import queue
import tempfile
import traceback
import uuid
from datetime import datetime

from qgis.core import (
    QgsCoordinateTransform,
    QgsMessageLog,
    QgsProject,
    Qgis,
)

from .raster_semantics import is_categorical_meta

_UI_LOG_QUEUE_MAX = 5000
_ui_log_queue = queue.Queue(maxsize=_UI_LOG_QUEUE_MAX)
_ui_log_timer = None
_ui_log_listeners = set()

def transform_point(point, src_crs, dest_crs):
    """Transform point from source CRS to destination CRS (best-effort).

    This helper is used in multiple tools. Coordinate transform errors should not
    crash the plugin UI; in that case we return the original point and log a
    warning.
    """
    if point is None:
        return None
    try:
        if src_crs == dest_crs:
            return point
        transform = QgsCoordinateTransform(src_crs, dest_crs, QgsProject.instance())
        return transform.transform(point)
    except Exception as e:
        try:
            log_message(f"CRS transform failed (fallback to original point): {e}", level=Qgis.MessageLevel.Warning)
        except Exception as _exc:
            log_swallowed("tools/utils.py:42 (transform_point)", _exc)
        return point

def is_null_value(value) -> bool:
    """True for Python None and for PyQGIS's NULL QVariant.

    A null attribute comes back from a feature as ``qgis.core.NULL``, which is
    not ``None`` - ``float(NULL)`` raises. Checking only ``is None`` before a
    conversion therefore raised, and was logged, once per null cell of every
    scanned feature. Nulls are expected data, not failures.
    """
    if value is None:
        return True
    try:
        if hasattr(value, "isNull") and value.isNull():
            return True
    except Exception as _exc:
        log_swallowed("tools/utils.py:59 (is_null_value)", _exc)
    try:
        from qgis.core import NULL
        return value == NULL
    except Exception:
        return False


def split_qgis_source_path(source) -> str:
    """Strip QGIS URI options (``|layername=...``, ``|layerid=...``) for GDAL/OGR.

    Four modules carried their own copy of this. They agreed, but four copies
    of a rule is how the categorical-metadata bug happened: one drifts and
    nobody notices. This is the only implementation now.
    """
    try:
        text = str(source or "").strip()
    except Exception:
        return ""
    if not text:
        return ""
    return (text.split("|", 1)[0] or "").strip()


def cleanup_files(file_paths):
    """Safely remove a list of file paths"""
    for path in file_paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception as _exc:
                log_swallowed("tools/utils.py:90 (cleanup_files)", _exc)

def _log_file_path():
    """Return a writable log file path (best-effort)."""
    try:
        from qgis.core import QgsApplication

        base = QgsApplication.qgisSettingsDirPath() or ""
    except Exception:
        base = ""

    if not base:
        base = tempfile.gettempdir()

    log_dir = os.path.join(base, "ArchToolkit", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        log_dir = tempfile.gettempdir()

    return os.path.join(log_dir, "archtoolkit.log")


def get_log_path():
    """Public helper to retrieve the current log file path."""
    return _log_file_path()


def _write_log_line(level_name: str, message: str):
    """Append a timestamped line to the plugin log file (best-effort, thread-safe enough)."""
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level_name}] {message}\n"
        with open(_log_file_path(), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        return


def _is_main_thread():
    """Best-effort check to avoid calling Qt/QGIS UI APIs from worker threads."""
    try:
        from qgis.PyQt.QtCore import QCoreApplication, QThread

        app = QCoreApplication.instance()
        if app is None:
            return True
        return QThread.currentThread() == app.thread()
    except Exception:
        return True


def _queue_ui_log(message: str, level=Qgis.MessageLevel.Info):
    """Queue a message to be flushed to QgsMessageLog on the main thread."""
    try:
        _ui_log_queue.put_nowait((str(message), level))
    except Exception:
        # full or unavailable -> drop
        return


def _flush_ui_log_queue(max_items: int = 200):
    """Flush queued log messages into the QGIS Log Messages panel (main thread only)."""
    if not _is_main_thread():
        return
    try:
        n = 0
        while n < max_items:
            try:
                msg, level = _ui_log_queue.get_nowait()
            except Exception:
                break
            try:
                QgsMessageLog.logMessage(str(msg), "ArchToolkit", level)
            except Exception as _exc:
                log_swallowed("tools/utils.py:165 (_flush_ui_log_queue)", _exc)

            # Also forward to any in-plugin live log UIs.
            try:
                listeners = list(_ui_log_listeners)
            except Exception:
                listeners = []
            for cb in listeners:
                try:
                    cb(str(msg), level)
                except Exception as _exc:
                    log_swallowed("tools/utils.py:176 (_flush_ui_log_queue)", _exc)
            n += 1
    except Exception as _exc:
        log_swallowed("tools/utils.py:179 (_flush_ui_log_queue)", _exc)


def start_ui_log_pump(interval_ms: int = 200):
    """Start a small timer to flush worker-thread log messages into QGIS' Log Messages panel."""
    if not _is_main_thread():
        return

    global _ui_log_timer
    try:
        if _ui_log_timer is not None and _ui_log_timer.isActive():
            return
    except Exception:
        _ui_log_timer = None

    try:
        from qgis.PyQt.QtCore import QCoreApplication, QTimer

        app = QCoreApplication.instance()
        _ui_log_timer = QTimer(app)
        _ui_log_timer.setInterval(max(50, int(interval_ms)))
        _ui_log_timer.timeout.connect(_flush_ui_log_queue)
        _ui_log_timer.start()
    except Exception:
        _ui_log_timer = None


def stop_ui_log_pump():
    """Stop the UI log pump timer (called on plugin unload)."""
    global _ui_log_timer
    try:
        if _ui_log_timer is not None:
            try:
                _ui_log_timer.stop()
            except Exception as _exc:
                log_swallowed("tools/utils.py:214 (stop_ui_log_pump)", _exc)
            try:
                _ui_log_timer.deleteLater()
            except Exception as _exc:
                log_swallowed("tools/utils.py:218 (stop_ui_log_pump)", _exc)
    finally:
        _ui_log_timer = None


def add_ui_log_listener(callback):
    """Register a main-thread callback (msg: str, level: Qgis) for real-time log UIs."""
    try:
        _ui_log_listeners.add(callback)
    except Exception as _exc:
        log_swallowed("tools/utils.py:228 (add_ui_log_listener)", _exc)


def remove_ui_log_listener(callback):
    """Unregister a previously-registered UI log callback."""
    try:
        _ui_log_listeners.discard(callback)
    except Exception as _exc:
        log_swallowed("tools/utils.py:236 (remove_ui_log_listener)", _exc)


def ensure_log_panel_visible(iface, show_hint: bool = True):
    """Deprecated: kept for backward compatibility.

    We no longer auto-open the QGIS 'Log Messages' panel (too intrusive). This now
    only ensures the worker-thread log pump is running.
    """
    try:
        start_ui_log_pump()
    except Exception as _exc:
        log_swallowed("tools/utils.py:248 (ensure_log_panel_visible)", _exc)


def log_message(message, level=Qgis.MessageLevel.Info):
    """Log to file + QGIS Message Log (file is always attempted; QGIS log only on main thread)."""
    try:
        level_name = "INFO"
        if level == Qgis.MessageLevel.Warning:
            level_name = "WARN"
        elif level == Qgis.MessageLevel.Critical:
            level_name = "ERROR"
        _write_log_line(level_name, str(message))
    except Exception as _exc:
        log_swallowed("tools/utils.py:261 (log_message)", _exc)

    # QgsMessageLog may not be safe off the main thread on some setups.
    if not _is_main_thread():
        _queue_ui_log(message, level=level)
        return

    try:
        # Ensure the pump is running so worker-thread logs appear too.
        start_ui_log_pump()
        QgsMessageLog.logMessage(str(message), "ArchToolkit", level)

        # Forward to in-plugin live log UIs.
        try:
            listeners = list(_ui_log_listeners)
        except Exception:
            listeners = []
        for cb in listeners:
            try:
                cb(str(message), level)
            except Exception as _exc:
                log_swallowed("tools/utils.py:282 (log_message)", _exc)
    except Exception as _exc:
        # Never crash due to logging
        log_swallowed("tools/utils.py:284 (log_message)", _exc)


def log_swallowed(context: str, exc: Exception = None) -> None:
    """Record an exception a handler is about to swallow on purpose.

    The plugin guards a great deal of optional work with ``except Exception``
    and continues, which is the right call for a tooltip that failed to set
    and the wrong call for a statistic that failed to compute - and until now
    the two looked identical: nothing was written anywhere. A wrong number
    could reach a report with no trace of the failure that produced it.

    This does not change what the handler does. It logs at Info under a fixed
    ``[swallowed]`` prefix so a normal run is not flooded with warnings, while
    anyone chasing a wrong result can filter the log for that prefix and see
    every place a computation quietly gave up.
    """
    try:
        _write_log_line("SWALLOWED", f"[swallowed] {context}: {exc!r}")
        _queue_ui_log(f"[swallowed] {context}: {exc}", Qgis.MessageLevel.Info)
    except Exception:
        return


def log_exception(context: str, exc: Exception = None, level=Qgis.MessageLevel.Critical):
    """Log a stack trace to file + (main thread only) QGIS log."""
    try:
        msg = f"{context}: {exc}" if exc is not None else str(context)
        if exc is not None and getattr(exc, "__traceback__", None) is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        else:
            tb = traceback.format_exc()
        log_message(msg, level=level)
        if tb and "Traceback" in tb:
            log_message(tb, level=level)
    except Exception as _exc:
        log_swallowed("tools/utils.py:321 (log_exception)", _exc)

def is_metric_crs(crs):
    """Return True if CRS map units are meters (recommended for distance-based tools)."""
    try:
        return (not crs.isGeographic()) and crs.mapUnits() == Qgis.DistanceUnit.Meters
    except Exception:
        return False

def move_group_to_top(root, group):
    if group.parent() != root or root.children().index(group) == 0:
        return group
    clone = group.clone()
    root.insertChildNode(0, clone)
    root.removeChildNode(group)
    return clone


def restore_ui_focus(dialog):
    """Ensure the dialog is visible and has focus"""
    if dialog is None:
        return
    try:
        dialog.show()
    except Exception as _exc:
        log_swallowed("tools/utils.py:346 (restore_ui_focus)", _exc)
    try:
        dialog.raise_()
    except Exception as _exc:
        log_swallowed("tools/utils.py:350 (restore_ui_focus)", _exc)
    try:
        dialog.activateWindow()
    except Exception as _exc:
        log_swallowed("tools/utils.py:354 (restore_ui_focus)", _exc)

def _message_level(level):
    """Map the tools' 0/1/2/3 message levels (or an enum) to Qgis.MessageLevel."""
    if isinstance(level, Qgis.MessageLevel):
        return level
    return {
        1: Qgis.MessageLevel.Warning,
        2: Qgis.MessageLevel.Critical,
        3: Qgis.MessageLevel.Success,
    }.get(level, Qgis.MessageLevel.Info)


def push_message(iface, title, text, level=0, duration=3):
    """Helper to push message to QGIS message bar"""
    try:
        lvl = Qgis.MessageLevel.Info
        if level == 1:
            lvl = Qgis.MessageLevel.Warning
        elif level == 2:
            lvl = Qgis.MessageLevel.Critical
        log_message(f"{title}: {text}", level=lvl)
    except Exception as _exc:
        log_swallowed("tools/utils.py:366 (push_message)", _exc)
    try:
        if iface is None:
            return
        mb = iface.messageBar()
        if mb is None:
            return
        # Pass the enum, not the int: QGIS 4 declares Qgis.MessageLevel as an
        # IntEnum and accepts ints, but the enum is correct on every binding.
        mb.pushMessage(title, text, level=_message_level(level), duration=duration)
    except Exception:
        # Never crash due to message bar errors
        try:
            log_message(f"(messageBar failed) {title}: {text}", level=Qgis.MessageLevel.Warning)
        except Exception as _exc:
            log_swallowed("tools/utils.py:379 (push_message)", _exc)


def new_run_id(prefix: str = "run") -> str:
    """Generate a short run id for grouping outputs.

    This is intended for tagging layers created by ArchToolkit tools so AI/reporting
    can reliably group related outputs even if layer names change.
    """
    p = str(prefix or "run").strip().replace(" ", "_")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    rnd = uuid.uuid4().hex[:6]
    return f"{p}-{ts}-{rnd}"


def set_archtoolkit_layer_metadata(
    layer,
    *,
    tool_id: str,
    run_id: str,
    kind: str = "",
    units: str = "",
    params: dict = None,
) -> None:
    """Attach stable metadata to a QGIS layer (best-effort).

    Stored as layer custom properties so it persists in the project and can be
    read by AI 조사요약 / 리포트 번들 내보내기.
    """
    if layer is None:
        return
    tool_id0 = str(tool_id or "").strip()
    run_id0 = str(run_id or "").strip()
    if not tool_id0 or not run_id0:
        return

    try:
        layer.setCustomProperty("archtoolkit/tool_id", tool_id0)
        layer.setCustomProperty("archtoolkit/run_id", run_id0)
        if kind:
            layer.setCustomProperty("archtoolkit/kind", str(kind or "").strip())
        if units:
            layer.setCustomProperty("archtoolkit/units", str(units or "").strip())
        layer.setCustomProperty("archtoolkit/created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        if params:
            try:
                layer.setCustomProperty(
                    "archtoolkit/params_json",
                    json.dumps(params, ensure_ascii=False, separators=(",", ":")),
                )
            except Exception as _exc:
                log_swallowed("tools/utils.py:430 (set_archtoolkit_layer_metadata)", _exc)
    except Exception as _exc:
        # Never crash due to metadata tagging.
        log_swallowed("tools/utils.py:432 (set_archtoolkit_layer_metadata)", _exc)


def get_archtoolkit_layer_metadata(layer) -> dict:
    """Read ArchToolkit metadata from a layer (best-effort)."""
    if layer is None:
        return {}
    try:
        tool_id = str(layer.customProperty("archtoolkit/tool_id", "") or "").strip()
        run_id = str(layer.customProperty("archtoolkit/run_id", "") or "").strip()
        if not tool_id and not run_id:
            return {}
        out = {"tool_id": tool_id, "run_id": run_id}

        kind = str(layer.customProperty("archtoolkit/kind", "") or "").strip()
        units = str(layer.customProperty("archtoolkit/units", "") or "").strip()
        created_at = str(layer.customProperty("archtoolkit/created_at", "") or "").strip()
        params_json = str(layer.customProperty("archtoolkit/params_json", "") or "").strip()

        if kind:
            out["kind"] = kind
        if units:
            out["units"] = units
        if created_at:
            out["created_at"] = created_at
        if params_json:
            try:
                out["params"] = json.loads(params_json)
            except Exception:
                # keep raw if not valid json
                out["params_json"] = params_json
        return out
    except Exception:
        return {}


def is_categorical_raster_meta(meta: dict) -> bool:
    """True when the ArchToolkit layer metadata describes a categorical raster.

    Thin re-export: the rule itself lives in the QGIS-free
    :mod:`tools.raster_semantics` so CI can pin it to the metadata the tools
    actually write (``tests/test_categorical_meta.py``). Callers keep importing
    it from here.
    """
    return is_categorical_meta(meta)
