# -*- coding: utf-8 -*-
"""Whether an ArchToolkit raster holds class codes or measurements.

One rule (plus a circular-direction rule and a no-metadata heuristic, both
below), two consequences, both silent when it is wrong:

* align/export resamples a categorical raster with nearest neighbour. Bilinear
  on nominal codes blends lithology 5 and lithology 12 into 8.5 - a value that
  is not a class, stored in a file that still claims to be one.
* the correlation/VIF report excludes categorical rasters. Pearson's r over
  arbitrary integer codes is a number with no meaning.

Neither failure raises, so the rule is the only thing standing between a class
raster and a corrupted predictor. It used to key partly off a ``tool_id`` no
tool ever wrote, which is why the KIGAM lithology raster - the single most
important categorical predictor this plugin makes - was treated as continuous
for its whole life. Nothing tied the rule to what the producing tools actually
tag, so nothing noticed.

Kept free of QGIS imports so ``tests/test_categorical_meta.py`` can pin it to
the real metadata in a plain Python environment (DEVELOPMENT.md).
"""

from __future__ import annotations

import math

# Bare "age" is deliberately excluded: it substring-matches unrelated kinds
# (drainage/average/image). Specific multi-char hints only.
CATEGORICAL_KIND_HINTS = (
    "class", "category", "categor", "litho", "geolog", "slope_position",
)

# Tool ids whose raster outputs are nominal whatever kind they carry. "geology"
# alone used to be the whole test and matched nothing - the KIGAM tools
# register as "kigam_raster"/"kigam_zip".
CATEGORICAL_TOOL_HINTS = ("geology", "kigam")

# Units that mean "nominal" on their own. "mask" is a binary visible/not-visible
# grid: interpolating it yields fractions that are neither class nor count.
# "bitmask" encodes observer subsets as bit flags (2^i): averaging bit flags is
# numerically meaningless.
CATEGORICAL_UNITS = ("class", "classes", "category", "mask", "bitmask")


# Units that unambiguously denote continuous physical measurements.
# Checked so a distance raster whose kind contains a categorical substring
# (e.g. "distance_geology", "distance_class1_road") is not misclassified as
# nominal class codes.
CONTINUOUS_UNITS = (
    "m", "deg", "1/m", "s", "min", "kcal", "j", "j/kg", "m^2", "m2",
    "ppm", "%", "percent", "count", "weight", "index",
)


def is_categorical_meta(meta) -> bool:
    """True when the layer metadata describes a raster of nominal class codes."""
    try:
        kind = str((meta or {}).get("kind") or "").lower()
        units = str((meta or {}).get("units") or "").lower()
        tool_id = str((meta or {}).get("tool_id") or "").lower()
    except Exception:
        return False
    if units in CATEGORICAL_UNITS:
        return True
    if any(hint in tool_id for hint in CATEGORICAL_TOOL_HINTS):
        return True
    if kind.startswith("distance_") or tool_id == "distance_raster":
        return False
    if units in CONTINUOUS_UNITS:
        return False
    return any(hint in kind for hint in CATEGORICAL_KIND_HINTS)


# Kinds that hold a direction in degrees. A direction is circular: 355 and 5
# are ten degrees apart, and their linear average (180) points the opposite
# way, so bilinear resampling manufactures directions no source cell had.
# Only nearest neighbour leaves them alone. terrain_analysis writes flat cells
# as -1 (outside 0-360) and NoData as -9999; averaging across a direction
# boundary is still wrong.
# "northness", "eastness" and "trasp" are deliberately absent: those are the
# linearised forms terrain_analysis emits precisely so they can be averaged.
CIRCULAR_KIND_HINTS = ("aspect", "bearing", "azimuth")


def is_circular_meta(meta) -> bool:
    """True when the layer metadata describes a raster of directions (degrees).

    Checked after :func:`is_categorical_meta` by callers: a raster that is
    both (an 8-sector aspect *class* raster) is categorical first, and both
    answers lead to nearest-neighbour resampling anyway.
    """
    if not hasattr(meta, "get"):
        return False
    kind = str(meta.get("kind") or "").lower()
    return any(hint in kind for hint in CIRCULAR_KIND_HINTS)


# Band types a raster of class codes is normally stored in. Float types are
# absent: codes stored as float are already outside the convention, and a
# float raster with few distinct values is far more often a rescaled
# measurement than a class map.
# Int32/UInt32 included: the plugin's own geology rasterizer writes lithology
# codes as Int32, and a GeoTIFF opened in a fresh project has no metadata.
CLASS_CODE_TYPES = ("Byte", "Int8", "Int16", "UInt16", "Int32", "UInt32")

# Distinct values a sample may hold and still read as class codes. Korea's
# detailed Ministry of Environment land-cover map has 41 classes and KIGAM
# 1:50,000 geology sheets commonly have 30-55 units; a Byte continuous
# measurement (hillshade, scaled index) still exceeds 64 in any real sample.
CLASS_CODE_MAX_DISTINCT = 64


def looks_like_class_codes(type_name, values) -> bool:
    """Heuristic for a raster that carries no ArchToolkit metadata.

    Absence of metadata is not evidence of continuity, but nothing in the
    file says which it is either. This is the cheapest signal that can be
    read from the pixels: an integer band type AND at most
    :data:`CLASS_CODE_MAX_DISTINCT` distinct, integral values in ``values``
    (a decimated sample of the valid cells). True means "resample with
    nearest neighbour and say why"; False keeps the caller's default.

    A false positive costs little (nearest on a measurement drops the
    interpolation smoothing); a false negative is the bilinear-on-codes
    corruption this exists to avoid. The threshold is therefore generous.
    """
    if str(type_name or "") not in CLASS_CODE_TYPES:
        return False
    distinct = set()
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(number) or number != math.floor(number):
            return False
        distinct.add(number)
        if len(distinct) > CLASS_CODE_MAX_DISTINCT:
            return False
    return bool(distinct)


# Inclusive value ranges of the GDAL band types a categorical raster is written
# with. Float types are absent on purpose: a class raster stored as float is
# already outside the contract this helper protects, and -9999 is available
# there anyway.
INTEGER_TYPE_RANGES = {
    "Byte": (0, 255),
    "Int8": (-128, 127),
    "UInt16": (0, 65535),
    "Int16": (-32768, 32767),
    "UInt32": (0, 4294967295),
    "Int32": (-2147483648, 2147483647),
}


# Sentinels that can never be a real elevation/depth but keep appearing in DEMs
# whose metadata declares no NoData value.
UNDECLARED_NODATA_SENTINELS = (-9999.0, -9999.9, -32768.0, -2147483648.0)
_UNDECLARED_NODATA_MAGNITUDE = 1e30


def nodata_equals(values, nodata):
    """Precision-safe elementwise equality test between ``values`` and ``nodata``.

    GDAL's ``GetNoDataValue()`` always returns a 64-bit Python float, whereas
    rasters are commonly Float32 or Int32/UInt32. Comparing a Float32 array
    against a float64 sentinel in NumPy 1.x (or after casting to float64) fails
    for non-binary-exact values like ``-9999.9`` or ``-3.402823e+38`` because
    ``float(np.float32(-9999.9)) == -9999.900390625 != -9999.9``. Likewise
    casting Int32/UInt32 to Float32 corrupts ``-2147483647`` / ``4294967295``.

    Comparing in the array's native dtype avoids both failure modes cleanly.
    """
    import numpy as np

    v = np.asarray(values)
    if nodata is None:
        return np.zeros(v.shape, dtype=bool)
    try:
        nd_f = float(nodata)
    except (TypeError, ValueError):
        return np.zeros(v.shape, dtype=bool)
    if math.isnan(nd_f):
        return np.isnan(v) if np.issubdtype(v.dtype, np.floating) else np.zeros(v.shape, dtype=bool)

    if np.issubdtype(v.dtype, np.integer):
        if not math.isfinite(nd_f) or nd_f != math.floor(nd_f):
            return np.zeros(v.shape, dtype=bool)
        info = np.iinfo(v.dtype)
        nd_i = int(nd_f)
        if nd_i < info.min or nd_i > info.max:
            return np.zeros(v.shape, dtype=bool)
        return v == v.dtype.type(nd_i)

    if np.issubdtype(v.dtype, np.floating):
        with np.errstate(over="ignore", invalid="ignore"):
            nd_native = v.dtype.type(nd_f)
        if not np.isfinite(nd_native):
            return np.zeros(v.shape, dtype=bool)
        eq = v == nd_native
        # If a caller already upcast a Float32 raster to Float64 before calling
        # us, a Float32 sentinel like -3.402823e+38 or -9999.9 lives in float64
        # as float(np.float32(nd_f)). Catch that representation for well-known
        # extreme/sentinel magnitudes without loosening equality for ordinary
        # measurement values.
        if v.dtype == np.float64 and (
            abs(nd_f) >= _UNDECLARED_NODATA_MAGNITUDE
            or any(math.isclose(nd_f, s, rel_tol=0.0, abs_tol=1e-9) for s in UNDECLARED_NODATA_SENTINELS)
        ):
            with np.errstate(over="ignore", invalid="ignore"):
                nd32_as64 = float(np.float32(nd_f))
            if math.isfinite(nd32_as64):
                eq = eq | (v == nd32_as64)
        return eq

    return v == nodata


def undeclared_nodata_mask(values, declared_nodata):
    """Build the NoData mask of a band, guessing undeclared sentinels.

    Returns ``(mask, guessed_count)``.  Cells equal to the declared NoData value
    and non-finite cells are always NoData.  When the metadata declares NO
    NoData value, cells that match a common sentinel (-9999, -9999.9, -32768,
    the Float32 extremes, ...) are treated as NoData as well and counted in
    ``guessed_count``.
    """
    import numpy as np

    v = np.asarray(values)
    mask = ~np.isfinite(v) if np.issubdtype(v.dtype, np.floating) else np.zeros(v.shape, dtype=bool)
    if declared_nodata is not None:
        mask |= nodata_equals(v, declared_nodata)
        return mask, 0
    guessed = np.zeros(v.shape, dtype=bool)
    for sentinel in UNDECLARED_NODATA_SENTINELS:
        guessed |= nodata_equals(v, sentinel)
    if np.issubdtype(v.dtype, np.floating):
        guessed |= v <= v.dtype.type(-_UNDECLARED_NODATA_MAGNITUDE)
        guessed |= v >= v.dtype.type(_UNDECLARED_NODATA_MAGNITUDE)
    count = int(np.count_nonzero(guessed))
    mask |= guessed
    return mask, count


def choose_nodata_sentinel(type_name, data_min, data_max):
    """Pick a NoData value for a class raster that has none, or None if unsafe.

    A categorical raster exported without a NoData value is worse than it
    sounds: downstream the nodata mask is guessed from the array, so the checks
    that would have caught bad cells (a high-nodata warning, presence points
    landing off the data) cannot fire at all, and padding introduced by the
    warp reads as a real class code.

    The value must sit OUTSIDE the observed data range - stamping a code that
    is in use would silently delete that class, which is a worse failure than
    having no NoData. Candidates are tried in order of least surprise: just
    below the data, just above it, then the type's own extremes. ``None`` means
    no safe value exists (the data already spans the whole type), and the
    caller should leave NoData unset and say so rather than guess.

    ``type_name`` is a GDAL band type name; unknown or floating-point types
    return ``None`` so the caller keeps its existing behaviour.
    """
    bounds = INTEGER_TYPE_RANGES.get(str(type_name or ""))
    if bounds is None:
        return None
    type_min, type_max = bounds
    try:
        raw_min = float(data_min)
        raw_max = float(data_max)
    except (TypeError, ValueError):
        return None
    # Finiteness first: floor(inf) raises OverflowError, and an all-NoData band
    # reports NaN statistics, so both reach here in practice.
    if not (math.isfinite(raw_min) and math.isfinite(raw_max)):
        return None
    low = int(math.floor(raw_min))
    high = int(math.ceil(raw_max))
    if low > high:
        return None

    for candidate in (low - 1, high + 1, type_min, type_max):
        if type_min <= candidate <= type_max and not (low <= candidate <= high):
            return candidate
    return None


__all__ = [
    "CATEGORICAL_KIND_HINTS",
    "CATEGORICAL_TOOL_HINTS",
    "CATEGORICAL_UNITS",
    "CIRCULAR_KIND_HINTS",
    "CLASS_CODE_MAX_DISTINCT",
    "CLASS_CODE_TYPES",
    "CONTINUOUS_UNITS",
    "INTEGER_TYPE_RANGES",
    "UNDECLARED_NODATA_SENTINELS",
    "choose_nodata_sentinel",
    "is_categorical_meta",
    "is_circular_meta",
    "looks_like_class_codes",
    "nodata_equals",
    "undeclared_nodata_mask",
]
