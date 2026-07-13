# -*- coding: utf-8 -*-
"""Dependency-free GDAL completion tracking.

QGIS forwards GDAL stderr through a single diagnostic channel, so the text of
a diagnostic is not a stable severity signal.  This module instead accepts an
exact, caller-supplied localized completion marker and evaluates event order.
It deliberately makes no decisions from English diagnostic text.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Lock


class GdalOutcomeReason(str, Enum):
    """Stable machine-readable reasons returned by ``decide``."""

    SUCCESS = "success"
    INVALID_SUCCESS_MARKER = "invalid_success_marker"
    FATAL_DIAGNOSTIC = "fatal_diagnostic"
    SUCCESS_MARKER_MISSING = "success_marker_missing"
    DIAGNOSTIC_AFTER_SUCCESS = "diagnostic_after_success"


@dataclass(frozen=True)
class GdalDiagnostic:
    """One diagnostic forwarded by the processing feedback channel."""

    message: str
    fatal: bool


@dataclass(frozen=True)
class GdalOutcomeDecision:
    """Immutable result of evaluating the recorded GDAL events."""

    succeeded: bool
    reason: GdalOutcomeReason
    detail: str
    diagnostics: tuple[GdalDiagnostic, ...]


class GdalOutcomeTracker:
    """Track GDAL diagnostics and an exact localized completion marker.

    Non-fatal diagnostics are accepted only when the exact marker is observed
    afterwards.  Fatal diagnostics always block success.  Missing markers and
    diagnostics recorded after the last marker also fail closed.
    """

    def __init__(self, success_marker: str):
        self._success_marker = success_marker
        self._marker_is_valid = (
            isinstance(success_marker, str) and bool(success_marker.strip())
        )
        self._diagnostics: list[tuple[int, GdalDiagnostic]] = []
        self._last_success_sequence: int | None = None
        self._sequence = 0
        self._lock = Lock()

    def record_diagnostic(self, message: str, *, fatal: bool = False) -> None:
        """Record a diagnostic without interpreting its localized text."""
        diagnostic = GdalDiagnostic(message=str(message), fatal=bool(fatal))
        with self._lock:
            self._sequence += 1
            self._diagnostics.append((self._sequence, diagnostic))

    def record_info(self, message: str) -> bool:
        """Record an exact completion marker and return whether it matched."""
        with self._lock:
            self._sequence += 1
            matched = self._marker_is_valid and message == self._success_marker
            if matched:
                self._last_success_sequence = self._sequence
            return matched

    def decide(self) -> GdalOutcomeDecision:
        """Return a fail-closed snapshot of the current outcome."""
        with self._lock:
            diagnostics_with_sequence = tuple(self._diagnostics)
            success_sequence = self._last_success_sequence
            marker_is_valid = self._marker_is_valid

        diagnostics = tuple(item[1] for item in diagnostics_with_sequence)
        fatal_diagnostics = tuple(item for item in diagnostics if item.fatal)

        if not marker_is_valid:
            return GdalOutcomeDecision(
                succeeded=False,
                reason=GdalOutcomeReason.INVALID_SUCCESS_MARKER,
                detail="A non-empty localized GDAL success marker is required.",
                diagnostics=diagnostics,
            )

        if fatal_diagnostics:
            return GdalOutcomeDecision(
                succeeded=False,
                reason=GdalOutcomeReason.FATAL_DIAGNOSTIC,
                detail=(
                    "A fatal GDAL diagnostic was reported: "
                    f"{fatal_diagnostics[-1].message}"
                ),
                diagnostics=diagnostics,
            )

        if success_sequence is None:
            detail = "The localized GDAL success marker was not observed."
            if diagnostics:
                detail += f" Last diagnostic: {diagnostics[-1].message}"
            return GdalOutcomeDecision(
                succeeded=False,
                reason=GdalOutcomeReason.SUCCESS_MARKER_MISSING,
                detail=detail,
                diagnostics=diagnostics,
            )

        late_diagnostics = tuple(
            diagnostic
            for sequence, diagnostic in diagnostics_with_sequence
            if sequence > success_sequence
        )
        if late_diagnostics:
            return GdalOutcomeDecision(
                succeeded=False,
                reason=GdalOutcomeReason.DIAGNOSTIC_AFTER_SUCCESS,
                detail=(
                    "A GDAL diagnostic was reported after the last success "
                    f"marker: {late_diagnostics[-1].message}"
                ),
                diagnostics=diagnostics,
            )

        return GdalOutcomeDecision(
            succeeded=True,
            reason=GdalOutcomeReason.SUCCESS,
            detail=(
                "The localized GDAL success marker followed all non-fatal "
                "diagnostics."
            ),
            diagnostics=diagnostics,
        )
