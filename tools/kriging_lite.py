# -*- coding: utf-8 -*-
"""
Kriging (Lite) implementation for ArchToolkit.

- Goal: provide an Ordinary Kriging workflow without external providers
  (SAGA/GRASS) and without extra Python dependencies beyond numpy.
- Scope: "Lite" = HEURISTIC variogram parameters + local neighborhood kriging.
  No empirical variogram is fitted: the model is fixed to exponential, the
  nugget is 5% of sample variance, and the range is 3x the median
  nearest-neighbour spacing. No anisotropy. The variance raster is therefore
  assumption-driven — treat it as a relative (not calibrated) uncertainty map.
- Exactness: the kriging system uses C(0) = partial_sill + nugget on BOTH the
  matrix diagonal and the right-hand side, so a grid node that coincides with
  a sample reproduces that sample (weights = unit vector, variance 0), as
  Ordinary Kriging is defined (Matheron 1963; Cressie 1993). Earlier versions
  left the nugget out of the right-hand side, which turned the solver into a
  measurement-error filter: a 30.00 m benchmark came back as 25.05 m at its
  own location and the variance never reached zero anywhere.
- Provenance: the returned ``params["value_field"]`` names the attribute the
  surface was built from, or ``"__geom_z__"`` for geometry Z, so callers can
  record and display the actual source rather than the "" an auto pick carries.

This is intentionally conservative and best-effort:
- Uses nearest N points per grid cell (fast enough for moderate grids).
- Writes prediction + variance GeoTIFF via GDAL Python bindings (usually present
  in QGIS' Python environment). If unavailable, the caller should fail
  gracefully.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .kriging_math import (
    build_ok_system,
    diagnose_kriging_assumptions,
    exponential_cov,
    fit_variogram_wls,
    invert_ok_system,
    loocv_ordinary_kriging,
    solve_ok,
)

from qgis.core import (
    Qgis,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
    QgsSpatialIndex,
    QgsVectorLayer,
)

from .utils import log_swallowed, is_metric_crs, log_message
from .raster_io import write_single_band_geotiff


# Sentinel (from the DEM generator UI) meaning "use the geometry's Z
# coordinate", not an attribute field name.
GEOM_Z_SENTINEL = "__geom_z__"

# Field names that hold elevation in the datasets this plugin meets (NGII
# exports, CAD conversions, survey packages, QGIS "Extract Z" output). Shared
# with the DEM generator dialog so TIN/IDW and Kriging agree on what counts as
# an elevation column; matched exactly first, then case-insensitively.
ELEVATION_FIELD_CANDIDATES = (
    "Z_COORD",
    "z_coord",
    "Elevation",
    "ELEVATION",
    "elev",
    "ELEV",
    "height",
    "HEIGHT",
    "표고",
    "고도",
    "z",
    "Z",
    "z_first",
)

# Distances at or below this (map units) count as "the grid node IS the sample".
_EXACT_TOL = 1e-9


@dataclass(frozen=True)
class KrigingParams:
    """Variogram parameters for the exponential model used below.

    ``range`` is the exponential *scale* parameter: ``C(h) = partial_sill *
    exp(-h / range)``. The practical distance at which correlation drops to
    ~5% is ``3 * range`` - which is what most kriging packages report as
    "range", so transcribing these values into another tool without
    multiplying by 3 smooths about 3x less than intended.
    """

    model: str
    nugget: float
    partial_sill: float
    range: float


def _as_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return None
        return out
    except Exception:
        return None


def auto_elevation_field(fields) -> Optional[str]:
    """Elevation field name in a QgsFields, by NAME only, or None.

    Exact spelling first over the whole candidate list, then one
    case-insensitive pass (QgsFields.lookupField) returning the real
    spelling. Shared by the Kriging path and the DEM dialog's TIN/IDW path so
    "auto" resolves to the same column everywhere.
    """
    if fields is None:
        return None
    try:
        for name in ELEVATION_FIELD_CANDIDATES:
            idx = fields.indexFromName(name)
            if idx >= 0:
                return name
        lookup = getattr(fields, "lookupField", None)
        if lookup is not None:
            for name in ELEVATION_FIELD_CANDIDATES:
                idx = int(lookup(name))
                if idx >= 0:
                    return str(fields[idx].name())
    except Exception as _exc:
        log_swallowed("tools/kriging_lite.py (auto_elevation_field)", _exc)
    return None


def _auto_value_field(layer: QgsVectorLayer) -> Optional[str]:
    """Pick a likely elevation field by NAME only.

    Deliberately does NOT fall back to "first numeric field": that silently
    kriged id/serial columns (a DEM of feature IDs). When no elevation-named
    field exists the caller falls back to geometry Z, and 2D layers without one
    fail loudly instead of interpolating garbage.
    """
    if layer is None:
        return None
    try:
        return auto_elevation_field(layer.fields())
    except Exception as _exc:
        log_swallowed("tools/kriging_lite.py:89 (_auto_value_field)", _exc)
    return None


def resolve_value_field(layer: QgsVectorLayer, value_field: Optional[str]) -> str:
    """Name the source the run reads elevations from.

    Returns the attribute name (explicit, or auto-detected by name) or
    :data:`GEOM_Z_SENTINEL` when the geometry's Z coordinate is used. This is
    the single decision :func:`_collect_point_samples` acts on, exposed so the
    caller can record and show it (the "자동" combo entry carries "").
    """
    name = str(value_field or "").strip()
    if name == GEOM_Z_SENTINEL:
        return GEOM_Z_SENTINEL
    if name:
        return name
    auto = _auto_value_field(layer)
    return str(auto) if auto else GEOM_Z_SENTINEL


def _collect_point_samples(
    layer: QgsVectorLayer,
    *,
    value_field: Optional[str],
    dedup_round: int = 6,
) -> Tuple[List[Tuple[float, float]], List[float], QgsSpatialIndex]:
    """Return unique point samples and a spatial index (IDs are 0..n-1)."""
    if layer is None or not layer.isValid():
        raise ValueError("Invalid layer")

    if layer.geometryType() != Qgis.GeometryType.Point:
        raise ValueError("Kriging requires a point layer")

    # GEOM_Z_SENTINEL (from the DEM generator UI) means "use the geometry's Z
    # coordinate", not an attribute field name.
    resolved = resolve_value_field(layer, value_field)
    use_geom_z = (resolved == GEOM_Z_SENTINEL)
    field_name = "" if use_geom_z else resolved

    sums: Dict[Tuple[float, float], float] = {}
    counts: Dict[Tuple[float, float], int] = {}
    coords: Dict[Tuple[float, float], Tuple[float, float]] = {}

    # Gather samples (deduplicate by rounded XY). Iterating vertices() handles
    # both Point and MultiPoint layers (asPoint() raised on multipoints, which
    # silently skipped every feature and ended in "Not enough valid points").
    use_field = bool((not use_geom_z) and field_name)
    for feat in layer.getFeatures():
        try:
            geom = feat.geometry()
        except Exception:
            geom = None
        if geom is None or geom.isEmpty():
            continue

        field_z = None
        if use_field:
            try:
                field_z = _as_float(feat[field_name])
            except Exception:
                field_z = None

        try:
            vertices = list(geom.vertices())
        except Exception:
            vertices = []

        for vtx in vertices:
            x = _as_float(vtx.x())
            y = _as_float(vtx.y())
            if x is None or y is None:
                continue

            if use_field:
                # An explicitly (or auto-)selected field is the single source
                # of truth: rows with NULL/invalid values are SKIPPED, never
                # silently mixed with geometry Z (possibly different units).
                z = field_z
            else:
                # Geometry Z (3D points): vertices are QgsPoint carrying Z
                # (NaN when the layer is 2D — rejected by _as_float).
                z = _as_float(vtx.z())
            if z is None or z != z:
                continue

            key = (round(x, dedup_round), round(y, dedup_round))
            coords[key] = (x, y)
            sums[key] = float(sums.get(key, 0.0)) + float(z)
            counts[key] = int(counts.get(key, 0)) + 1

    points_xy: List[Tuple[float, float]] = []
    values: List[float] = []
    index = QgsSpatialIndex()

    for i, (key, sum_z) in enumerate(sums.items()):
        x, y = coords[key]
        z = float(sum_z) / max(1, int(counts.get(key, 1)))

        points_xy.append((float(x), float(y)))
        values.append(float(z))

        f = QgsFeature()
        f.setId(int(i))
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(x), float(y))))
        index.addFeature(f)

    if len(points_xy) < 3:
        raise ValueError("Not enough valid points (need >= 3)")

    return points_xy, values, index


def _median_nearest_neighbor_distance(
    points_xy: Sequence[Tuple[float, float]],
    index: QgsSpatialIndex,
) -> Optional[float]:
    """Estimate typical spacing via median NN distance (best-effort)."""
    try:
        import numpy as np
    except Exception:
        return None

    dists = []
    for x, y in points_xy:
        try:
            ids = index.nearestNeighbor(QgsPointXY(float(x), float(y)), 2)
        except Exception:
            ids = []
        if not ids or len(ids) < 2:
            continue

        # The nearest is usually itself; take the second.
        j = int(ids[1])
        if j < 0 or j >= len(points_xy):
            continue
        x2, y2 = points_xy[j]
        dx = float(x2) - float(x)
        dy = float(y2) - float(y)
        d = math.hypot(dx, dy)
        if d > 0:
            dists.append(d)

    if not dists:
        return None
    try:
        return float(np.median(np.array(dists, dtype=float)))
    except Exception:
        return None


def auto_params(
    *,
    points_xy: Sequence[Tuple[float, float]],
    values: Sequence[float],
    extent: QgsRectangle,
    index: QgsSpatialIndex,
) -> KrigingParams:
    """Heuristic "good-enough" parameters for Lite mode."""
    try:
        import numpy as np
    except Exception as e:
        raise RuntimeError(f"numpy is required for Kriging Lite ({e})")

    v = np.array(list(values), dtype=float)
    if v.size < 3:
        raise ValueError("Not enough values")

    # Sample variance (ddof=1). If it collapses (all equal), keep a tiny sill.
    var = float(np.var(v, ddof=1)) if v.size >= 2 else 0.0
    if not (var > 0):
        var = 1e-6

    nn = _median_nearest_neighbor_distance(points_xy, index)
    if nn is None or not (nn > 0):
        # Fallback: approximate spacing from area/points
        try:
            area = float(max(0.0, extent.width() * extent.height()))
            nn = math.sqrt(area / max(1, len(points_xy)))
        except Exception:
            nn = 0.0
    if not (nn > 0):
        nn = 1.0

    # Exponential model tends to be stable for "Lite" defaults.
    # Range is set to a few typical spacings so correlation decays reasonably.
    rng = float(max(1e-6, nn * 3.0))

    nugget = float(max(0.0, var * 0.05))
    partial_sill = float(max(1e-6, var - nugget))

    return KrigingParams(model="exponential", nugget=nugget, partial_sill=partial_sill, range=rng)


def _cov_exponential(dist, *, partial_sill: float, rng: float):
    # C(h) = partial_sill * exp(-h / range)
    try:
        return exponential_cov(dist, partial_sill=partial_sill, rng=rng)
    except Exception:
        raise RuntimeError("numpy is required")


def _write_geotiff(
    *,
    out_path: str,
    array_2d,
    extent: QgsRectangle,
    pixel_size: float,
    crs_wkt: str,
    nodata: float,
) -> None:
    """Write a single-band Float32 GeoTIFF with GDAL write verification."""
    try:
        import numpy as np
    except Exception as e:
        raise RuntimeError(f"numpy is required to write raster ({e})")

    try:
        from osgeo import gdal  # type: ignore
    except Exception as e:
        raise RuntimeError(f"GDAL Python bindings not available: {e}")

    arr = np.asarray(array_2d, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError("Expected 2D array")

    height, width = int(arr.shape[0]), int(arr.shape[1])
    if width <= 0 or height <= 0:
        raise ValueError("Invalid raster shape")

    xmin = float(extent.xMinimum())
    ymax = float(extent.yMaximum())
    px = float(pixel_size)
    if not write_single_band_geotiff(
        str(out_path),
        arr,
        geotransform=(xmin, px, 0.0, ymax, 0.0, -px),
        projection=str(crs_wkt or ""),
        nodata=float(nodata),
        gdal_type=gdal.GDT_Float32,
        options=("TILED=YES", "COMPRESS=LZW"),
    ):
        raise RuntimeError(f"Kriging GeoTIFF 파일을 생성할 수 없습니다: {out_path}")


def ordinary_kriging_lite_to_geotiff(
    *,
    layer: QgsVectorLayer,
    value_field: Optional[str],
    extent: QgsRectangle,
    pixel_size: float,
    out_path: str,
    variance_path: Optional[str] = None,
    neighbors: int = 16,
    max_cells: int = 250_000,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    fit_variogram: bool = False,
    compute_loocv: bool = True,
) -> Dict[str, object]:
    """Run Ordinary Kriging and write GeoTIFF(s).

    Returns a dict with keys:
    - out_path, variance_path
    - params (KrigingParams as dict, plus "neighbors", "value_field", and "variogram_source")
    - loocv (leave-one-out cross-validation dict when compute_loocv=True, else None)
    - ncols, nrows, n_points
    """
    if layer is None or not layer.isValid():
        raise ValueError("Invalid layer")

    if not is_metric_crs(layer.crs()):
        raise ValueError("Layer CRS must be projected in meters for Kriging")

    px = float(pixel_size)
    if not (px > 0):
        raise ValueError("Invalid pixel size")

    # Prepare samples + index. Resolve the value source once, up front, so the
    # log and the returned params say which column the surface came from.
    resolved_field = resolve_value_field(layer, value_field)
    log_message(f"[kriging] value source: {resolved_field}")
    points_xy, values, index = _collect_point_samples(layer, value_field=resolved_field)

    # Compute grid size (ceil so we fully cover extent)
    width = float(extent.width())
    height = float(extent.height())
    ncols = int(max(1, math.ceil(width / px)))
    nrows = int(max(1, math.ceil(height / px)))
    ncells = int(ncols * nrows)

    if ncells > int(max_cells):
        area = float(max(0.0, width * height))
        rec_px = math.sqrt(area / float(max_cells)) if area > 0 else px
        raise ValueError(
            f"Grid too large for Kriging Lite: {ncols}x{nrows}={ncells:,} cells. "
            f"Increase pixel size (≈ {rec_px:.2f}m+) or reduce extent."
        )

    try:
        import numpy as np
    except Exception as e:
        raise RuntimeError(f"numpy is required for Kriging Lite ({e})")

    pts = np.array(points_xy, dtype=float)
    zs = np.array(values, dtype=float)

    variogram_source = "heuristic_lite"
    if fit_variogram:
        fit = fit_variogram_wls(pts, zs)
        if fit.get("fitted"):
            params = KrigingParams(
                model=str(fit["model"]),
                nugget=float(fit["nugget"]),
                partial_sill=float(fit["partial_sill"]),
                range=float(fit["range"]),
            )
            variogram_source = "empirical_wls"
            log_message(
                f"[kriging] fitted WLS variogram: model={params.model}, nugget={params.nugget:.6g}, "
                f"partial_sill={params.partial_sill:.6g}, range={params.range:.6g}, "
                f"wls_loss={float(fit.get('wls_loss', 0.0)):.6g}"
            )
        else:
            params = auto_params(points_xy=points_xy, values=values, extent=extent, index=index)
            variogram_source = str(fit.get("variogram_source") or "heuristic_fallback")
            log_message(
                f"[kriging] WLS variogram fallback ({fit.get('reason')}): "
                f"model={params.model}, nugget={params.nugget:.6g}, "
                f"partial_sill={params.partial_sill:.6g}, range={params.range:.6g}"
            )
    else:
        params = auto_params(points_xy=points_xy, values=values, extent=extent, index=index)
        log_message(
            f"[kriging] auto params: model={params.model}, nugget={params.nugget:.6g}, "
            f"partial_sill={params.partial_sill:.6g}, range={params.range:.6g}"
        )

    neighbor_n = int(max(3, min(int(neighbors), len(points_xy))))
    nodata = -9999.0

    pred = np.full((nrows, ncols), nodata, dtype=np.float32)
    varr = np.full((nrows, ncols), nodata, dtype=np.float32)

    # Cache inverse matrices by neighbor id tuple (local neighborhoods repeat a lot on grids).
    inv_cache: Dict[Tuple[int, ...], Optional[np.ndarray]] = {}
    inv_cache_max = 5000

    def get_inv(nei_ids: Sequence[int]) -> Optional[np.ndarray]:
        """Inverse of the augmented kriging system, or None when it stays singular.

        None (cached as such, so a broken neighborhood is not rebuilt per
        cell) makes the caller leave that cell at NoData instead of letting a
        single unusable neighborhood abort the whole raster mid-run.
        """
        key = tuple(int(i) for i in nei_ids)
        if key in inv_cache:
            return inv_cache[key]

        coords = pts[list(key), :]
        A = build_ok_system(
            coords,
            partial_sill=params.partial_sill,
            rng=params.range,
            nugget=params.nugget,
            model=params.model,
        )
        inv = invert_ok_system(A, partial_sill=params.partial_sill, nugget=params.nugget)

        if len(inv_cache) >= inv_cache_max:
            inv_cache.clear()
        inv_cache[key] = inv
        return inv

    xmin = float(extent.xMinimum())
    ymax = float(extent.yMaximum())

    for r in range(nrows):
        if is_cancelled and is_cancelled():
            raise RuntimeError("Cancelled")

        y = ymax - (float(r) + 0.5) * px
        for c in range(ncols):
            x = xmin + (float(c) + 0.5) * px

            try:
                nei_ids = index.nearestNeighbor(QgsPointXY(x, y), neighbor_n)
            except Exception:
                nei_ids = []
            if not nei_ids or len(nei_ids) < 3:
                continue

            key = [int(i) for i in nei_ids if 0 <= int(i) < len(points_xy)]
            if len(key) < 3:
                continue

            inv = get_inv(key)
            if inv is None:
                # This neighborhood stays singular even after regularization:
                # leave the cell at NoData rather than abort the run.
                continue
            coords = pts[key, :]
            dz = zs[key]
            zhat, vv = solve_ok(
                inv,
                coords,
                dz,
                (float(x), float(y)),
                partial_sill=params.partial_sill,
                rng=params.range,
                nugget=params.nugget,
                model=params.model,
                exact_tol=max(_EXACT_TOL, 1e-6 * px),
            )
            if (not math.isfinite(zhat)) or (not math.isfinite(vv)):
                continue
            pred[r, c] = float(zhat)
            varr[r, c] = float(vv)

        if progress_cb:
            try:
                pct = int((r + 1) * 100 / max(1, nrows))
                progress_cb(pct, f"Kriging 계산 중… ({r + 1}/{nrows})")
            except Exception as _exc:
                log_swallowed("kriging_lite.ordinary_kriging_lite_to_geotiff", _exc)

    crs_wkt = ""
    try:
        crs_wkt = layer.crs().toWkt()
    except Exception:
        crs_wkt = ""

    _write_geotiff(out_path=out_path, array_2d=pred, extent=extent, pixel_size=px, crs_wkt=crs_wkt, nodata=nodata)
    if variance_path:
        _write_geotiff(
            out_path=variance_path,
            array_2d=varr,
            extent=extent,
            pixel_size=px,
            crs_wkt=crs_wkt,
            nodata=nodata,
        )

    loocv: Optional[Dict[str, object]] = None
    if compute_loocv:
        try:
            loocv = loocv_ordinary_kriging(
                pts,
                zs,
                model=params.model,
                nugget=params.nugget,
                partial_sill=params.partial_sill,
                rng=params.range,
                neighbors=neighbor_n,
            )
            if int(loocv.get("n_evaluated") or 0) > 0:
                msdr_val = loocv.get("msdr")
                msdr_txt = f", MSDR={float(msdr_val):.3f}" if msdr_val is not None else ""
                log_message(
                    f"[kriging] LOOCV (n={loocv['n_evaluated']}): "
                    f"RMSE={float(loocv['rmse']):.4f}m, MAE={float(loocv['mae']):.4f}m"
                    f"{msdr_txt}"
                )
        except Exception as _exc:
            log_swallowed("kriging_lite.loocv", _exc)
            loocv = None

    assumptions: Optional[Dict[str, object]] = None
    try:
        assumptions = diagnose_kriging_assumptions(pts, zs)
        for _warn in (assumptions.get("warnings") or []):
            log_message(f"[kriging] 가정 점검 경고: {_warn}", level=Qgis.MessageLevel.Warning)
    except Exception as _exc:
        log_swallowed("kriging_lite.diagnose_kriging_assumptions", _exc)
        assumptions = None

    return {
        "out_path": out_path,
        "variance_path": variance_path,
        "params": {
            "model": params.model,
            "nugget": params.nugget,
            "partial_sill": params.partial_sill,
            "range": params.range,
            "neighbors": neighbor_n,
            "value_field": resolved_field,
            "variogram_source": variogram_source,
            "assumptions": assumptions,
        },
        "loocv": loocv,
        "assumptions": assumptions,
        "ncols": ncols,
        "nrows": nrows,
        "n_points": len(points_xy),
    }
