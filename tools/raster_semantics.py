# -*- coding: utf-8 -*-
"""Whether an ArchToolkit raster holds class codes or measurements.

One rule, two consequences, both silent when it is wrong:

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
CATEGORICAL_UNITS = ("class", "classes", "category", "mask")


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
    return any(hint in kind for hint in CATEGORICAL_KIND_HINTS)


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
    "INTEGER_TYPE_RANGES",
    "choose_nodata_sentinel",
    "is_categorical_meta",
]
