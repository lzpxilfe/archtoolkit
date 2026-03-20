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
    QgsUnitTypes,
    Qgis,
)

from .i18n import tr

_UI_LOG_QUEUE_MAX = 5000
_ui_log_queue = queue.Queue(maxsize=_UI_LOG_QUEUE_MAX)
_ui_log_timer = None
_ui_log_listeners = set()


def transform_point(point, src_crs, dest_crs, *, strict=False):
    """Transform point from source CRS to destination CRS (best-effort).

    This helper is used in multiple tools. Coordinate transform errors should not
    crash the plugin UI. By default we return the original point on failure to
    preserve legacy behavior; callers can opt into `strict=True` when a failed
    transform should stop downstream analysis instead of silently continuing with
    a wrong coordinate.
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
            log_message(f"CRS transform failed (fallback to original point): {e}", level=Qgis.Warning)
        except Exception:
            pass
        if strict:
            return None
        return point


def split_qgis_source_path(source: str) -> str:
    """Strip common QGIS URI options (e.g. `|layername=...`) from a source string."""
    try:
        s = str(source or "").strip()
    except Exception:
        return ""
    if not s:
        return ""
    return (s.split("|", 1)[0] or "").strip()


def qgis_raster_source_to_gdal(source: str) -> str:
    """Best-effort conversion from a QGIS raster source URI to a GDAL-openable source."""
    try:
        s = str(source or "").strip()
    except Exception:
        return ""
    if not s:
        return ""

    # Already a GDAL-style dataset string.
    upper = s.upper()
    if upper.startswith(("GPKG:", "NETCDF:", "HDF4:", "HDF5:", "WMS:", "WCS:", "WMTS:", "PG:")):
        return s

    dataset_path = split_qgis_source_path(s)
    if not dataset_path:
        return ""

    layer_name = ""
    try:
        for part in s.split("|")[1:]:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            if str(key or "").strip().lower() == "layername":
                layer_name = str(value or "").strip()
                break
    except Exception:
        layer_name = ""

    if layer_name and dataset_path.lower().endswith(".gpkg"):
        return f"GPKG:{dataset_path}:{layer_name}"

    return dataset_path


def open_gdal_dataset_from_qgis_source(source: str, *, access=None):
    """Open a raster dataset from a QGIS source string, returning `(dataset, opened_source)`."""
    try:
        from osgeo import gdal
    except Exception as e:
        try:
            log_message(f"GDAL import failed while opening raster source: {e}", level=Qgis.Warning)
        except Exception:
            pass
        return None, ""

    if access is None:
        try:
            access = gdal.GA_ReadOnly
        except Exception:
            access = 0

    source0 = ""
    try:
        source0 = str(source or "").strip()
    except Exception:
        source0 = ""

    candidates = []
    normalized = qgis_raster_source_to_gdal(source0)
    if normalized:
        candidates.append(normalized)
    if source0 and source0 not in candidates:
        candidates.append(source0)

    for candidate in candidates:
        try:
            ds = gdal.Open(candidate, access)
        except Exception:
            ds = None
        if ds is not None:
            return ds, candidate

    return None, (normalized or source0)


def cleanup_files(file_paths):
    """Safely remove a list of file paths"""
    for path in file_paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


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
        pass


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


def _queue_ui_log(message: str, level=Qgis.Info):
    """Queue a message to be flushed to QgsMessageLog on the main thread."""
    try:
        _ui_log_queue.put_nowait((str(message), level))
    except Exception:
        # full or unavailable -> drop
        pass


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
            except Exception:
                pass

            # Also forward to any in-plugin live log UIs.
            try:
                listeners = list(_ui_log_listeners)
            except Exception:
                listeners = []
            for cb in listeners:
                try:
                    cb(str(msg), level)
                except Exception:
                    pass
            n += 1
    except Exception:
        pass


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
            except Exception:
                pass
            try:
                _ui_log_timer.deleteLater()
            except Exception:
                pass
    finally:
        _ui_log_timer = None


def add_ui_log_listener(callback):
    """Register a main-thread callback (msg: str, level: Qgis) for real-time log UIs."""
    try:
        _ui_log_listeners.add(callback)
    except Exception:
        pass


def remove_ui_log_listener(callback):
    """Unregister a previously-registered UI log callback."""
    try:
        _ui_log_listeners.discard(callback)
    except Exception:
        pass


def ensure_log_panel_visible(iface, show_hint: bool = True):
    """Deprecated: kept for backward compatibility.

    We no longer auto-open the QGIS 'Log Messages' panel (too intrusive). This now
    only ensures the worker-thread log pump is running.
    """
    try:
        start_ui_log_pump()
    except Exception:
        pass


def log_message(message, level=Qgis.Info):
    """Log to file + QGIS Message Log (file is always attempted; QGIS log only on main thread)."""
    try:
        level_name = "INFO"
        if level == Qgis.Warning:
            level_name = "WARN"
        elif level == Qgis.Critical:
            level_name = "ERROR"
        _write_log_line(level_name, str(message))
    except Exception:
        pass

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
            except Exception:
                pass
    except Exception:
        # Never crash due to logging
        pass


def log_exception(context: str, exc: Exception = None, level=Qgis.Critical):
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
    except Exception:
        pass


def is_metric_crs(crs):
    """Return True if CRS map units are meters (recommended for distance-based tools)."""
    try:
        return (not crs.isGeographic()) and crs.mapUnits() == QgsUnitTypes.DistanceMeters
    except Exception:
        return False


def restore_ui_focus(dialog):
    """Ensure the dialog is visible and has focus"""
    if dialog is None:
        return
    try:
        dialog.show()
    except Exception:
        pass
    try:
        dialog.raise_()
    except Exception:
        pass
    try:
        dialog.activateWindow()
    except Exception:
        pass


def push_message(iface, title, text, level=0, duration=3):
    """Helper to push message to QGIS message bar"""
    title_text = tr(title)
    body_text = tr(text)
    try:
        lvl = Qgis.Info
        if level == 1:
            lvl = Qgis.Warning
        elif level == 2:
            lvl = Qgis.Critical
        log_message(f"{title_text}: {body_text}", level=lvl)
    except Exception:
        pass
    try:
        if iface is None:
            return
        mb = iface.messageBar()
        if mb is None:
            return
        mb.pushMessage(title_text, body_text, level=level, duration=duration)
    except Exception:
        # Never crash due to message bar errors
        try:
            log_message(f"(messageBar failed) {title_text}: {body_text}", level=Qgis.Warning)
        except Exception:
            pass


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
            except Exception:
                pass
    except Exception:
        # Never crash due to metadata tagging.
        pass


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
