# -*- coding: utf-8 -*-
"""QGIS-free counterpart of :func:`tools.utils.log_swallowed`.

Pure analysis modules (``atomic_output``, ``raster_io``, ``ahp_core``, ...)
must stay importable in a plain Python environment where ``qgis.core`` is
unavailable, so they cannot import the plugin logger.  This module gives them
the same contract: an exception a handler swallows on purpose leaves a
``[swallowed]`` record on the ``archtoolkit`` logging channel, matching the
line utils.log_swallowed writes to the plugin log file.  A NullHandler keeps
stderr silent unless the embedding application configures logging itself.

Deliberately raises nothing: logging here must never replace the exception it
is reporting.
"""
import logging

_logger = logging.getLogger("archtoolkit")
_logger.addHandler(logging.NullHandler())


def log_swallowed(context: str, exc: Exception = None) -> None:
    """Record an exception a handler is about to swallow on purpose (QGIS-free).

    Severity is Info, matching utils.log_swallowed: the point of the record is
    traceability (filter for ``[swallowed]`` when chasing a wrong result), not
    alarm, and a normal run must not be flooded with warnings.
    """
    _logger.info("[swallowed] %s: %r", context, exc)
