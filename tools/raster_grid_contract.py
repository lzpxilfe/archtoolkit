# -*- coding: utf-8 -*-
"""Dependency-free numeric contracts for north-up raster grids.

The helpers in this module intentionally avoid QGIS and GDAL imports.  A UI or
provider adapter can capture its raster metadata into :class:`RasterGrid`, then
compare the observed output against a canonical target grid before publishing
files.

When both a target extent and target resolution are supplied, the GDAL warp
path used by ArchToolkit rounds each cell count using ``floor(ratio + 0.5)``.
The upper-left anchor is retained: x grows from ``xmin`` and y grows downward
from ``ymax``.  Consequently the canonical ``xmax`` and ``ymin`` can differ
from the originally requested extent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple


class GridContractError(ValueError):
    """Raised when a grid contract or its tolerances are not usable."""


class GridMismatchError(GridContractError):
    """Raised when an observed raster grid does not match its contract."""

    def __init__(self, fields: Tuple[str, ...]):
        self.fields = tuple(fields)
        super().__init__(f"Raster grid mismatch: {', '.join(self.fields)}")


def _finite_float(value: float, label: str) -> float:
    if isinstance(value, bool):
        raise GridContractError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GridContractError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise GridContractError(f"{label} must be a finite number")
    return number


@dataclass(frozen=True)
class Extent:
    """Axis-aligned extent ordered as xmin, xmax, ymin, ymax."""

    xmin: float
    xmax: float
    ymin: float
    ymax: float

    def __post_init__(self) -> None:
        for field_name in ("xmin", "xmax", "ymin", "ymax"):
            value = _finite_float(getattr(self, field_name), f"extent.{field_name}")
            object.__setattr__(self, field_name, value)
        if self.xmax <= self.xmin:
            raise GridContractError("extent.xmax must be greater than extent.xmin")
        if self.ymax <= self.ymin:
            raise GridContractError("extent.ymax must be greater than extent.ymin")

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin


@dataclass(frozen=True)
class RasterGrid:
    """Observable dimensions, extent, and x/y resolution of a raster."""

    width: int
    height: int
    extent: Extent
    resolution_x: float
    resolution_y: float

    def __post_init__(self) -> None:
        for field_name in ("width", "height"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise GridContractError(f"{field_name} must be a positive integer")
        if not isinstance(self.extent, Extent):
            raise GridContractError("extent must be an Extent")
        for field_name in ("resolution_x", "resolution_y"):
            value = _finite_float(getattr(self, field_name), field_name)
            if value <= 0.0:
                raise GridContractError(f"{field_name} must be greater than zero")
            object.__setattr__(self, field_name, value)


@dataclass(frozen=True)
class GridTolerances:
    """Absolute tolerances for extent coordinates and pixel resolutions."""

    extent_absolute: float
    resolution_absolute: float

    def __post_init__(self) -> None:
        for field_name in ("extent_absolute", "resolution_absolute"):
            value = _finite_float(getattr(self, field_name), field_name)
            if value < 0.0:
                raise GridContractError(f"{field_name} must not be negative")
            object.__setattr__(self, field_name, value)


def _rounded_cell_count(span: float, resolution: float) -> int:
    ratio = span / resolution
    if not math.isfinite(ratio):
        raise GridContractError("extent-to-resolution ratio must be finite")
    return max(1, math.floor(ratio + 0.5))


def canonical_gdal_target_grid(
    requested_extent: Extent,
    resolution_x: float,
    resolution_y: Optional[float] = None,
) -> RasterGrid:
    """Return the north-up grid produced by GDAL-style half-up sizing.

    ``xmin`` and ``ymax`` remain anchored.  The opposite edges are derived
    from the rounded cell counts, so they need not equal the requested
    ``xmax`` and ``ymin``.  Supplying only ``resolution_x`` requests square
    cells; otherwise x and y resolutions are handled independently.
    """
    if not isinstance(requested_extent, Extent):
        raise GridContractError("requested_extent must be an Extent")
    x_resolution = _finite_float(resolution_x, "resolution_x")
    y_resolution = x_resolution if resolution_y is None else _finite_float(
        resolution_y, "resolution_y"
    )
    if x_resolution <= 0.0:
        raise GridContractError("resolution_x must be greater than zero")
    if y_resolution <= 0.0:
        raise GridContractError("resolution_y must be greater than zero")

    width = _rounded_cell_count(requested_extent.width, x_resolution)
    height = _rounded_cell_count(requested_extent.height, y_resolution)
    canonical_extent = Extent(
        xmin=requested_extent.xmin,
        xmax=requested_extent.xmin + width * x_resolution,
        ymin=requested_extent.ymax - height * y_resolution,
        ymax=requested_extent.ymax,
    )
    return RasterGrid(
        width=width,
        height=height,
        extent=canonical_extent,
        resolution_x=x_resolution,
        resolution_y=y_resolution,
    )


def suggested_grid_tolerances(expected: RasterGrid) -> GridTolerances:
    """Derive conservative absolute tolerances from an expected grid."""
    if not isinstance(expected, RasterGrid):
        raise GridContractError("expected must be a RasterGrid")
    max_resolution = max(expected.resolution_x, expected.resolution_y)
    coordinate_scale = max(
        1.0,
        abs(expected.extent.xmin),
        abs(expected.extent.xmax),
        abs(expected.extent.ymin),
        abs(expected.extent.ymax),
    )
    tolerances = GridTolerances(
        extent_absolute=max(
            64.0 * math.ulp(coordinate_scale),
            1e-9 * max_resolution,
        ),
        resolution_absolute=max(
            64.0 * math.ulp(max_resolution),
            1e-9 * max_resolution,
        ),
    )
    _require_distinguishing_tolerances(expected, tolerances)
    return tolerances


def _require_distinguishing_tolerances(
    expected: RasterGrid,
    tolerances: GridTolerances,
) -> None:
    cell_limit = 0.01 * min(expected.resolution_x, expected.resolution_y)
    if tolerances.extent_absolute >= cell_limit:
        raise GridContractError(
            "extent_absolute must be less than 1% of the smallest cell size"
        )
    if tolerances.resolution_absolute >= cell_limit:
        raise GridContractError(
            "resolution_absolute must be less than 1% of the smallest cell size"
        )


def grid_mismatches(
    actual: RasterGrid,
    expected: RasterGrid,
    *,
    tolerances: Optional[GridTolerances] = None,
) -> Tuple[str, ...]:
    """Return deterministic field names which differ from the contract."""
    if not isinstance(actual, RasterGrid):
        raise GridContractError("actual must be a RasterGrid")
    if not isinstance(expected, RasterGrid):
        raise GridContractError("expected must be a RasterGrid")
    checked_tolerances = tolerances or suggested_grid_tolerances(expected)
    if not isinstance(checked_tolerances, GridTolerances):
        raise GridContractError("tolerances must be GridTolerances")
    _require_distinguishing_tolerances(expected, checked_tolerances)

    mismatches = []
    if actual.width != expected.width:
        mismatches.append("width")
    if actual.height != expected.height:
        mismatches.append("height")

    for field_name in ("xmin", "xmax", "ymin", "ymax"):
        if not math.isclose(
            getattr(actual.extent, field_name),
            getattr(expected.extent, field_name),
            rel_tol=0.0,
            abs_tol=checked_tolerances.extent_absolute,
        ):
            mismatches.append(field_name)
    for field_name in ("resolution_x", "resolution_y"):
        if not math.isclose(
            getattr(actual, field_name),
            getattr(expected, field_name),
            rel_tol=0.0,
            abs_tol=checked_tolerances.resolution_absolute,
        ):
            mismatches.append(field_name)
    return tuple(mismatches)


def validate_grid(
    actual: RasterGrid,
    expected: RasterGrid,
    *,
    tolerances: Optional[GridTolerances] = None,
) -> None:
    """Raise :class:`GridMismatchError` unless ``actual`` matches the contract."""
    mismatches = grid_mismatches(actual, expected, tolerances=tolerances)
    if mismatches:
        raise GridMismatchError(mismatches)


__all__ = [
    "Extent",
    "GridContractError",
    "GridMismatchError",
    "GridTolerances",
    "RasterGrid",
    "canonical_gdal_target_grid",
    "grid_mismatches",
    "suggested_grid_tolerances",
    "validate_grid",
]
