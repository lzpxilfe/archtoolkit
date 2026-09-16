# -*- coding: utf-8 -*-
"""How large an accumulated-cost run this machine can actually take.

The cost surface is a Dijkstra accumulation written in Python with ``heapq``,
one pop and eight edge relaxations per cell. That shape fixes the scaling, and
the old guard - a flat ``cell_count > 4_000_000`` refusal - answered it with a
constant that said nothing about the machine it was running on. A 5 m DEM over
a county is tens of millions of cells, so the constant was the only thing
standing between the user and the analysis, on a laptop that might well have
had room for it.

Measured on the real loop (random elevations, which is the worst case for heap
churn - a real DEM is smoother and pushes fewer decrease-key entries):

    cells        time      peak RSS
      160,000    1.27 s      38 MB    (240 B/cell)
      490,000    4.54 s      82 MB    (168 B/cell)
    1,000,000   10.16 s     128 MB    (128 B/cell)

Per-cell cost falls as fixed overhead amortizes, so the constants below take
the large-grid figure and add headroom. The important consequence: **memory is
the binding constraint, not time**. Forty million cells is about seven minutes
- long, but a thing a person may reasonably choose to wait for - while the same
run wants roughly six gigabytes, which is what will actually fail.

So the budget is derived from memory the machine reports as available, and when
a run does not fit, the honest answer is not "too big" but "too big at this
pixel size" - :func:`suggested_pixel_size` computes the one that would fit,
because for a genuinely large region the fix is a coarser grid, not a bigger
cap.

No QGIS imports, so the arithmetic is testable in a plain Python environment
(DEVELOPMENT.md).
"""

from __future__ import annotations

import math
import os

# Measured at 1,000,000 cells (128 B/cell, 10.2 us/cell), rounded up for
# headroom: real DEMs vary, and a friction raster adds another float32 plane.
PER_CELL_BYTES = 160
PER_CELL_SECONDS = 1.05e-5

# Fraction of reported-available memory a single analysis may claim. QGIS, the
# project's other layers and the OS all need room; taking half leaves the
# session usable rather than winning the allocation and freezing the desktop.
MEMORY_SAFETY_FRACTION = 0.5

# Used only when the platform will not report its memory. Deliberately modest:
# under-promising costs the user a confirmation prompt, over-promising costs
# them the session.
ASSUMED_AVAILABLE_BYTES = 2 * 1024 ** 3

# Below this, never interrupt - the run is seconds and a prompt would be noise.
ALWAYS_ALLOW_CELLS = 4_000_000

# Runs longer than this get a heads-up with the estimate, even when memory is
# ample, so nobody starts a ten-minute job believing it is a ten-second one.
WARN_SECONDS = 60.0

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_REFUSE = "refuse"


class CostBudgetError(ValueError):
    """Raised when an extent or budget is not usable."""


def available_memory_bytes():
    """Memory the OS reports as available, or None when it will not say.

    Returning None rather than a guess keeps the distinction visible: the
    caller can say "assuming 2 GB" instead of stating a limit as if measured.
    """
    # Linux: MemAvailable accounts for reclaimable cache, which SC_AVPHYS_PAGES
    # does not, and is the number that predicts whether an allocation succeeds.
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass

    # Windows.
    try:
        import ctypes

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullAvailPhys)
    except Exception:
        pass

    # POSIX fallback (macOS and Linux without /proc).
    try:
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_AVPHYS_PAGES"))
    except Exception:
        pass
    return None


def estimate_bytes(cells) -> int:
    return int(max(0, int(cells)) * PER_CELL_BYTES)


def estimate_seconds(cells) -> float:
    return float(max(0, int(cells)) * PER_CELL_SECONDS)


def cell_budget(available_bytes=None) -> int:
    """How many cells fit in the share of memory an analysis may claim."""
    if available_bytes is None:
        available_bytes = ASSUMED_AVAILABLE_BYTES
    usable = float(available_bytes) * MEMORY_SAFETY_FRACTION
    if not math.isfinite(usable) or usable <= 0:
        return 0
    return int(usable // PER_CELL_BYTES)


def suggested_pixel_size(current_pixel_size, cells, budget_cells):
    """The pixel size at which ``cells`` would fit in ``budget_cells``.

    Cell count scales with the inverse square of pixel size, so the factor is
    ``sqrt(cells / budget)``. Rounded up to something a person would type: for
    a genuinely large region this is the real answer, and it should read as a
    recommendation rather than as a raw float.
    """
    try:
        current = float(current_pixel_size)
        cells = int(cells)
        budget = int(budget_cells)
    except (TypeError, ValueError):
        return None
    if current <= 0 or not math.isfinite(current) or cells <= 0 or budget <= 0:
        return None
    if cells <= budget:
        return None
    factor = math.sqrt(cells / float(budget))
    target = current * factor
    # Round up to 1 / 2 / 5 x 10^n so the suggestion is a round number and is
    # never slightly under the size that actually fits.
    exponent = math.floor(math.log10(target))
    base = 10.0 ** exponent
    for step in (1.0, 2.0, 5.0, 10.0):
        candidate = step * base
        if candidate >= target:
            return candidate
    return target


class BudgetVerdict:
    """What to do about a requested analysis extent."""

    def __init__(self, level, cells, bytes_needed, seconds, budget_cells,
                 available_bytes, memory_known, suggested_pixel=None):
        self.level = level
        self.cells = int(cells)
        self.bytes_needed = int(bytes_needed)
        self.seconds = float(seconds)
        self.budget_cells = int(budget_cells)
        self.available_bytes = available_bytes
        self.memory_known = bool(memory_known)
        self.suggested_pixel = suggested_pixel

    @property
    def gigabytes(self) -> float:
        return self.bytes_needed / (1024.0 ** 3)

    @property
    def minutes(self) -> float:
        return self.seconds / 60.0

    def __repr__(self):  # pragma: no cover - debugging aid
        return (f"BudgetVerdict({self.level}, cells={self.cells}, "
                f"{self.gigabytes:.1f}GB, {self.minutes:.1f}min)")


def assess(cells, *, available_bytes=None, memory_known=None,
           current_pixel_size=None, confirmed=False) -> BudgetVerdict:
    """Decide whether a run of ``cells`` cells may proceed.

    Three outcomes rather than the old yes/no:

    * ``ok`` - small enough that asking would be noise.
    * ``warn`` - it fits, but it is long or large enough that the user should
      see the estimate first. ``confirmed=True`` turns this into ``ok``; that
      is the user's decision to make, not the plugin's.
    * ``refuse`` - it does not fit in the memory share, and no confirmation
      changes that, because the failure mode is the session dying rather than
      the wait being long.
    """
    cells = int(cells)
    if cells < 0:
        raise CostBudgetError("cells must not be negative")
    if memory_known is None:
        memory_known = available_bytes is not None
    budget = cell_budget(available_bytes)
    bytes_needed = estimate_bytes(cells)
    seconds = estimate_seconds(cells)

    if cells > budget:
        return BudgetVerdict(
            LEVEL_REFUSE, cells, bytes_needed, seconds, budget, available_bytes,
            memory_known,
            suggested_pixel=suggested_pixel_size(current_pixel_size, cells, budget),
        )

    if cells <= ALWAYS_ALLOW_CELLS or confirmed or seconds < WARN_SECONDS:
        level = LEVEL_OK
    else:
        level = LEVEL_WARN
    return BudgetVerdict(level, cells, bytes_needed, seconds, budget,
                         available_bytes, memory_known)


# A batch of accumulations (the least-cost network runs one per directed pair)
# is bounded by total time, not by any single window. Two hours is generous -
# the point is that a run which would take a working day is a mistake the user
# wants told about, not a thing to discover tomorrow.
MAX_BATCH_SECONDS = 2 * 3600


def assess_batch(cells_per_run, runs, *, available_bytes=None, memory_known=None,
                 current_pixel_size=None) -> BudgetVerdict:
    """Assess a batch of accumulations that run one after another.

    Memory is per run - only one window is held at a time - so the memory
    ceiling is the same as for a single accumulation. Time is cumulative, and
    that is the difference that matters: a window which is fine on its own can
    be hours of work once it is repeated for every candidate pair. Raising the
    per-window limit without this would turn an immediate refusal into an
    overnight run.

    The returned verdict's ``seconds`` is the batch total.
    """
    cells_per_run = int(cells_per_run)
    runs = max(1, int(runs))
    if cells_per_run < 0:
        raise CostBudgetError("cells must not be negative")

    verdict = assess(
        cells_per_run,
        available_bytes=available_bytes,
        memory_known=memory_known,
        current_pixel_size=current_pixel_size,
        confirmed=True,   # per-run time is not the question here
    )
    total_seconds = estimate_seconds(cells_per_run) * runs
    verdict.seconds = total_seconds

    if verdict.level == LEVEL_REFUSE:
        return verdict
    if total_seconds > MAX_BATCH_SECONDS:
        verdict.level = LEVEL_REFUSE
        if verdict.suggested_pixel is None and current_pixel_size:
            # Not a memory problem, so size the suggestion by time instead.
            affordable = int(MAX_BATCH_SECONDS / (PER_CELL_SECONDS * runs))
            verdict.suggested_pixel = suggested_pixel_size(
                current_pixel_size, cells_per_run, max(1, affordable))
    elif total_seconds >= WARN_SECONDS:
        verdict.level = LEVEL_WARN
    return verdict


def assess_windows(cells_per_window, *, available_bytes=None, memory_known=None,
                   current_pixel_size=None) -> BudgetVerdict:
    """Assess a batch whose windows differ in size, once, before any run.

    :func:`assess_batch` multiplies one window by the run count, which is only
    right when every window is the same size. A least-cost network's windows
    are not: most pairs are near neighbours with small windows and a few are
    far apart. Extrapolating the largest window across all pairs refused runs
    that were fine, and doing it inside the loop refused them after earlier
    pairs had already been computed and thrown away.

    Memory is bounded by the largest window (one is held at a time); time is
    the sum. Both are known from geotransform arithmetic before the first
    accumulation starts, so the decision belongs there.
    """
    sizes = [max(0, int(c)) for c in (cells_per_window or [])]
    if not sizes:
        return assess(0, available_bytes=available_bytes, memory_known=memory_known,
                      current_pixel_size=current_pixel_size, confirmed=True)
    largest = max(sizes)
    verdict = assess(
        largest,
        available_bytes=available_bytes,
        memory_known=memory_known,
        current_pixel_size=current_pixel_size,
        confirmed=True,
    )
    total_seconds = sum(estimate_seconds(c) for c in sizes)
    verdict.seconds = total_seconds
    if verdict.level == LEVEL_REFUSE:
        return verdict
    if total_seconds > MAX_BATCH_SECONDS:
        verdict.level = LEVEL_REFUSE
        if verdict.suggested_pixel is None and current_pixel_size:
            # Time-bound, so size the suggestion so the SUM fits: every
            # window shrinks by the same factor, so scale the total.
            total_cells = sum(sizes)
            affordable = int(MAX_BATCH_SECONDS / PER_CELL_SECONDS)
            verdict.suggested_pixel = suggested_pixel_size(
                current_pixel_size, total_cells, max(1, affordable))
    elif total_seconds >= WARN_SECONDS:
        verdict.level = LEVEL_WARN
    return verdict


def assess_current_machine(cells, *, current_pixel_size=None, confirmed=False):
    """:func:`assess` against this machine's reported available memory."""
    available = available_memory_bytes()
    return assess(
        cells,
        available_bytes=available if available is not None else ASSUMED_AVAILABLE_BYTES,
        memory_known=available is not None,
        current_pixel_size=current_pixel_size,
        confirmed=confirmed,
    )


__all__ = [
    "ALWAYS_ALLOW_CELLS",
    "MAX_BATCH_SECONDS",
    "assess_batch",
    "assess_windows",
    "ASSUMED_AVAILABLE_BYTES",
    "BudgetVerdict",
    "CostBudgetError",
    "LEVEL_OK",
    "LEVEL_REFUSE",
    "LEVEL_WARN",
    "MEMORY_SAFETY_FRACTION",
    "PER_CELL_BYTES",
    "PER_CELL_SECONDS",
    "WARN_SECONDS",
    "assess",
    "assess_current_machine",
    "available_memory_bytes",
    "cell_budget",
    "estimate_bytes",
    "estimate_seconds",
    "suggested_pixel_size",
]
