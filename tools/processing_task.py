# -*- coding: utf-8 -*-
"""Run a Processing algorithm through the QGIS task manager and wait for it.

``processing.run()`` blocks the calling GUI thread for the whole algorithm, so
every tool that used it froze QGIS for the duration. Routing through
``QgsProcessingAlgRunnerTask`` keeps the event loop live - the dialog repaints,
a progress dialog's Cancel actually works, and a hung task is detected instead
of freezing QGIS forever. Extracted from ``align_export_dialog._warp`` so all
tools share one implementation (and one watchdog).
"""
from __future__ import annotations

import time
from typing import List, Optional

from qgis.PyQt.QtCore import QCoreApplication, QEventLoop, QTimer
from qgis.core import (
    QgsApplication,
    QgsMapLayer,
    QgsProcessing,
    QgsProcessingAlgRunnerTask,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsTask,
)

from .utils import log_swallowed

# A task that emits no feedback at all for this long is hung (dead subprocess /
# starved task), not slow: healthy algorithms report progress regularly.
STALL_TIMEOUT_S = 180.0
_WATCHDOG_POLL_MS = 5000

# Keep references to timed-out tasks/contexts/feedback until the C++ task
# manager signals completion/termination so Python GC never frees them mid-run.
_PENDING_TASKS: dict = {}


def _is_memory_param_value(val) -> bool:
    if isinstance(val, QgsMapLayer):
        try:
            if str(val.providerType() or "").lower() == "memory":
                return True
        except Exception:
            return True
        try:
            if hasattr(val, "isEditable") and val.isEditable():
                return True
        except Exception as _exc:
            log_swallowed("tools/processing_task.py (_is_memory_param_value)", _exc)
        return False
    if isinstance(val, (list, tuple)):
        return any(_is_memory_param_value(item) for item in val)
    if isinstance(val, str):
        s = val.strip().lower()
        temp_out = str(getattr(QgsProcessing, "TEMPORARY_OUTPUT", "TEMPORARY_OUTPUT")).strip().lower()
        if s.startswith("memory:") or (temp_out and s == temp_out):
            return True
    return False


def _uses_memory_layers(params: dict) -> bool:
    if not isinstance(params, dict):
        return False
    return any(_is_memory_param_value(v) for v in params.values())


def _take_temporary_result_layers(results: dict, context: QgsProcessingContext) -> dict:
    """Resolve temporaryLayerStore IDs to owned QgsMapLayer objects before context drops."""
    if not isinstance(results, dict) or context is None:
        return dict(results or {})
    out = dict(results)
    try:
        store = context.temporaryLayerStore()
    except Exception:
        return out
    if store is None:
        return out
    for key, val in list(out.items()):
        if isinstance(val, str) and val:
            try:
                if store.mapLayer(val) is not None:
                    taken = context.takeResultLayer(val)
                    if taken is not None:
                        out[key] = taken
            except Exception as _exc:
                log_swallowed("tools/processing_task.py (_take_temporary_result_layers)", _exc)
    return out


class ProcessingCancelled(Exception):
    """The user cancelled a task-run Processing algorithm."""


class ProcessingTaskError(RuntimeError):
    """A task-run Processing algorithm failed or never completed."""

    def __init__(self, alg_id: str, message: str, *, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.alg_id = str(alg_id)
        self.errors = list(errors or ())


class ActivityFeedback(QgsProcessingFeedback):
    """Processing feedback that timestamps every callback and keeps the errors.

    The watchdog uses the timestamps to tell a slow-but-alive task from a hung
    one; subclasses may override the same callbacks for their own bookkeeping
    (see align_export's GDAL outcome tracker).
    """

    def __init__(self):
        super().__init__()
        self.last_activity = time.monotonic()
        self.errors: List[str] = []

    def _touch(self):
        self.last_activity = time.monotonic()

    def setProgress(self, progress):
        self._touch()
        super().setProgress(progress)

    def reportError(self, error, fatalError=False):
        self._touch()
        self.errors.append(str(error))
        super().reportError(error, fatalError)

    def pushInfo(self, info):
        self._touch()
        super().pushInfo(info)


def _run_alg_inline(
    alg_id: str,
    params: dict,
    *,
    context: QgsProcessingContext,
    fb: QgsProcessingFeedback,
    progress=None,
) -> dict:
    """Run ``alg_id`` on the main thread when memory layers are involved.

    QGIS memory vector layers carry main-thread QObject affinity, and
    ``QgsProcessingAlgRunnerTask`` returns ``context.temporaryLayerStore()`` IDs
    rather than owned layer objects. Running inline via ``processing.run`` with
    periodic ``processEvents`` and taking ownership via
    ``context.takeResultLayer`` keeps memory-layer algorithms safe and valid.
    """
    import processing  # lazy import inside QGIS session

    last_pump = [0.0]

    def _pump(_value=None):
        now = time.monotonic()
        if now - last_pump[0] >= 0.05:
            last_pump[0] = now
            try:
                QCoreApplication.processEvents()
            except Exception as _exc:
                log_swallowed("tools/processing_task.py (_pump)", _exc)

    def _cancel():
        try:
            fb.cancel()
        except Exception as _exc:
            log_swallowed("tools/processing_task.py (_cancel inline)", _exc)

    fb.progressChanged.connect(_pump)
    if progress is not None:
        progress.canceled.connect(_cancel)
    try:
        results = processing.run(str(alg_id), params, context=context, feedback=fb)
    except Exception as exc:
        if progress is not None and progress.wasCanceled() or fb.isCanceled():
            raise ProcessingCancelled(f"{alg_id} 작업이 취소되었습니다.") from exc
        raise ProcessingTaskError(
            alg_id,
            f"처리 작업({alg_id})이(가) 정상적으로 완료되지 않았습니다: {exc}",
            errors=list(getattr(fb, "errors", []) or []),
        ) from exc
    finally:
        try:
            fb.progressChanged.disconnect(_pump)
        except Exception as _exc:
            log_swallowed("tools/processing_task.py (_pump disconnect)", _exc)
        if progress is not None:
            try:
                progress.canceled.disconnect(_cancel)
            except Exception as _exc:
                log_swallowed("tools/processing_task.py (_cancel inline disconnect)", _exc)

    cancelled = False
    try:
        cancelled = bool(progress is not None and progress.wasCanceled()) or bool(fb.isCanceled())
    except Exception as _exc:
        log_swallowed("tools/processing_task.py (inline cancel check)", _exc)
    if cancelled:
        raise ProcessingCancelled(f"{alg_id} 작업이 취소되었습니다.")

    return _take_temporary_result_layers(results, context)


def run_alg_blocking(
    alg_id: str,
    params: dict,
    *,
    owner=None,
    feedback: Optional[QgsProcessingFeedback] = None,
    progress=None,
    timeout_s: float = STALL_TIMEOUT_S,
) -> dict:
    """Run ``alg_id`` via the task manager; return its results.

    Blocks the caller (the GUI event loop keeps running inside the wait), so
    the interface stays responsive while the algorithm works. ``owner`` is the
    dialog driving the run: its ``_run_progress`` (when it has one) supplies
    the progress/cancel UI, so every tool wires Cancel the same way;
    ``progress`` overrides it. Cancelling the progress dialog aborts the task
    and raises :class:`ProcessingCancelled`. Raises :class:`ProcessingTaskError`
    on failure or when the task goes silent for ``timeout_s`` seconds (hung
    subprocess / starved task).
    """
    if progress is None and owner is not None:
        progress = getattr(owner, "_run_progress", None)
    algorithm = QgsApplication.processingRegistry().algorithmById(str(alg_id))
    if algorithm is None:
        raise ProcessingTaskError(alg_id, f"QGIS 처리 알고리즘({alg_id})을 찾을 수 없습니다.")

    fb = feedback if feedback is not None else ActivityFeedback()
    context = QgsProcessingContext()
    context.setProject(QgsProject.instance())

    if _uses_memory_layers(params):
        return _run_alg_inline(alg_id, params, context=context, fb=fb, progress=progress)

    task = QgsProcessingAlgRunnerTask(algorithm, params, context, fb)
    task_key = id(task)
    _PENDING_TASKS[task_key] = (task, context, fb)
    loop = QEventLoop()
    state = {"finished": False, "successful": False, "results": {}, "stalled": False}

    def _finished(successful, results):
        _PENDING_TASKS.pop(task_key, None)
        if state["stalled"]:
            return
        state["finished"] = True
        state["successful"] = bool(successful)
        state["results"] = _take_temporary_result_layers(dict(results or {}), context)
        loop.quit()

    def _cancel():
        try:
            fb.cancel()
        except Exception as _exc:
            log_swallowed("tools/processing_task.py (_cancel)", _exc)
        try:
            task.cancel()
        except Exception as _exc:
            log_swallowed("tools/processing_task.py (_cancel)", _exc)

    watchdog = QTimer()
    watchdog.setInterval(_WATCHDOG_POLL_MS)

    def _check_stall():
        if state["finished"]:
            watchdog.stop()
            return
        idle_s = time.monotonic() - getattr(fb, "last_activity", time.monotonic())
        if idle_s > timeout_s:
            state["stalled"] = True
            watchdog.stop()
            _cancel()
            loop.quit()

    watchdog.timeout.connect(_check_stall)
    task.executed.connect(_finished)
    if progress is not None:
        progress.canceled.connect(_cancel)
    try:
        if not QgsApplication.taskManager().addTask(task):
            _PENDING_TASKS.pop(task_key, None)
            raise ProcessingTaskError(
                alg_id, f"처리 작업({alg_id})을 QGIS 작업 관리자에 등록하지 못했습니다."
            )
        watchdog.start()
        loop.exec()
    finally:
        watchdog.stop()
        try:
            watchdog.timeout.disconnect(_check_stall)
        except Exception as _exc:
            log_swallowed("tools/processing_task.py (watchdog)", _exc)
        if state["finished"]:
            try:
                task.executed.disconnect(_finished)
            except Exception as _exc:
                log_swallowed("tools/processing_task.py (executed)", _exc)
            _PENDING_TASKS.pop(task_key, None)
        if progress is not None:
            try:
                progress.canceled.disconnect(_cancel)
            except Exception as _exc:
                log_swallowed("tools/processing_task.py (progress)", _exc)

    errors = list(getattr(fb, "errors", []) or [])
    tail = " | ".join(errors[-3:])
    if state["stalled"]:
        raise ProcessingTaskError(
            alg_id,
            f"{alg_id} 작업이 {int(timeout_s)}초 동안 진행 신호가 없어 중단했습니다. "
            "입력 크기를 줄이거나 디스크/네트워크 상태를 확인한 뒤 다시 실행하세요.",
            errors=errors,
        )
    cancelled = False
    try:
        cancelled = bool(progress is not None and progress.wasCanceled()) or bool(fb.isCanceled())
    except Exception as _exc:
        log_swallowed("tools/processing_task.py (cancelled check)", _exc)
    if cancelled:
        raise ProcessingCancelled(f"{alg_id} 작업이 취소되었습니다.")
    if not state["finished"] or not state["successful"]:
        suffix = f": {tail[:1200]}" if tail else ""
        raise ProcessingTaskError(
            alg_id, f"처리 작업({alg_id})이(가) 정상적으로 완료되지 않았습니다{suffix}", errors=errors
        )
    return state["results"]


def run_task_blocking(
    task: QgsTask,
    *,
    owner=None,
    progress=None,
    timeout_s: Optional[float] = STALL_TIMEOUT_S,
) -> None:
    """Wait for a ``QgsTask`` through the task manager; raise on failure/cancel.

    Same contract as :func:`run_alg_blocking`, for tools that run their own
    compute in a worker instead of a Processing algorithm. The task should call
    ``setProgress`` regularly: the stall watchdog uses those calls to tell a
    slow task from a hung one (pass ``timeout_s=None`` for a task that never
    reports progress). Cancelling ``progress`` cancels the task and raises
    :class:`ProcessingCancelled`; a failed/terminated task raises
    :class:`ProcessingTaskError`.
    """
    if progress is None and owner is not None:
        progress = getattr(owner, "_run_progress", None)
    task_key = id(task)
    _PENDING_TASKS[task_key] = task
    loop = QEventLoop()
    state = {"done": False, "ok": False, "stalled": False, "touch": time.monotonic()}

    def _cleanup_refs():
        _PENDING_TASKS.pop(task_key, None)

    def _completed():
        _cleanup_refs()
        if state["stalled"]:
            return
        state["done"] = True
        state["ok"] = True
        loop.quit()

    def _terminated():
        _cleanup_refs()
        if state["stalled"]:
            return
        state["done"] = True
        state["ok"] = False
        loop.quit()

    def _touched(_value):
        state["touch"] = time.monotonic()

    def _cancel():
        try:
            task.cancel()
        except Exception as _exc:
            log_swallowed("tools/processing_task.py (_cancel task)", _exc)

    watchdog = QTimer()
    watchdog.setInterval(_WATCHDOG_POLL_MS)

    def _check_stall():
        if state["done"]:
            watchdog.stop()
            return
        if timeout_s is not None and (time.monotonic() - state["touch"]) > timeout_s:
            state["stalled"] = True
            watchdog.stop()
            _cancel()
            loop.quit()

    watchdog.timeout.connect(_check_stall)
    task.taskCompleted.connect(_completed)
    task.taskTerminated.connect(_terminated)
    task.progressChanged.connect(_touched)
    if progress is not None:
        progress.canceled.connect(_cancel)
    try:
        if not QgsApplication.taskManager().addTask(task):
            _cleanup_refs()
            raise ProcessingTaskError(
                str(task.description() or "task"), "작업을 QGIS 작업 관리자에 등록하지 못했습니다."
            )
        watchdog.start()
        loop.exec()
    finally:
        watchdog.stop()
        try:
            watchdog.timeout.disconnect(_check_stall)
        except Exception as _exc:
            log_swallowed("tools/processing_task.py (watchdog)", _exc)
        try:
            task.progressChanged.disconnect(_touched)
        except Exception as _exc:
            log_swallowed("tools/processing_task.py (progressChanged)", _exc)
        if progress is not None:
            try:
                progress.canceled.disconnect(_cancel)
            except Exception as _exc:
                log_swallowed("tools/processing_task.py (progress)", _exc)
        if state["done"]:
            try:
                task.taskCompleted.disconnect(_completed)
            except Exception as _exc:
                log_swallowed("tools/processing_task.py (taskCompleted)", _exc)
            try:
                task.taskTerminated.disconnect(_terminated)
            except Exception as _exc:
                log_swallowed("tools/processing_task.py (taskTerminated)", _exc)
            _cleanup_refs()

    label = str(task.description() or "작업")
    if state["stalled"]:
        raise ProcessingTaskError(
            label,
            f"{label}이(가) {int(timeout_s)}초 동안 진행 신호가 없어 중단했습니다.",
        )
    cancelled = False
    try:
        cancelled = bool(progress is not None and progress.wasCanceled())
    except Exception as _exc:
        log_swallowed("tools/processing_task.py (cancelled check)", _exc)
    if cancelled:
        raise ProcessingCancelled(f"{label}이(가) 취소되었습니다.")
    if not (state["done"] and state["ok"]):
        inner = getattr(task, "error", None)
        if inner is not None:
            raise inner
        raise ProcessingTaskError(label, f"{label}이(가) 정상적으로 완료되지 않았습니다.")


class ComputeTask(QgsTask):
    """Run a plain callable on a worker thread.

    The callable receives a ``set_progress(percent)`` callback and must not
    touch QGIS API (numpy/GDAL/geometry only). Its exception is captured and
    re-raised unchanged on the caller's thread by :func:`run_task_blocking`,
    so existing error messages and handlers survive the move off the GUI
    thread.
    """

    def __init__(self, description, fn):
        super().__init__(description, QgsTask.Flag.CanCancel)
        self._fn = fn
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self._fn(self.setProgress)
            return True
        except Exception as exc:
            self.error = exc
            return False


def run_compute_blocking(
    fn,
    *,
    label: str,
    owner=None,
    progress=None,
    timeout_s: Optional[float] = STALL_TIMEOUT_S,
):
    """Run ``fn(set_progress)`` on a worker thread; return its result.

    Convenience over :class:`ComputeTask` + :func:`run_task_blocking` for the
    numpy/GDAL array paths that used to freeze QGIS inline. ``fn`` should call
    ``set_progress`` between phases so the stall watchdog can tell a slow run
    from a hung one.
    """
    task = ComputeTask(str(label), fn)
    run_task_blocking(task, owner=owner, progress=progress, timeout_s=timeout_s)
    return task.result
