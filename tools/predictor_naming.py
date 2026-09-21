# -*- coding: utf-8 -*-
"""Predictor variable names that survive a downstream modelling toolchain.

Why this module exists
----------------------
The exported raster's base name becomes the *variable name* in a predictive
model's training table, in every importance ranking and in every response
curve.  Consumers written against a scientific-Python stack routinely reduce
that base name to ASCII.  ArchModelBench, the companion this export targets,
does exactly that (``arch_model_bench_core/utils.py``)::

    def safe_name(value):
        name = re.sub(r"[^A-Za-z0-9_]+", "_", Path(value).stem).strip("_")
        return name or "predictor"

Hangul is not in ``[A-Za-z0-9_]``, so a Korean display name is not transcribed
there - it is *deleted*.  ``경사도.tif`` arrives as ``predictor`` and
``사면방향.tif`` as ``predictor_2``, with the numbering decided by the order the
consumer happens to walk the folder.  Two failures follow: nobody can read the
report, and a model feature bound to ``predictor_2`` by name alone can end up
scoring a different raster than it was trained on.

So the export must emit names that are already ASCII and already unique -
names that pass through ``safe_name`` unchanged.  :func:`is_round_trip_stable`
states that contract and :func:`assign_variable_keys` guarantees it.

The good name is already in hand: every ArchToolkit result carries a ``kind``
in its layer metadata (``slope``, ``trasp``, ``curvature_profile``,
``geology_class``), which is short, English and stable across UI languages.
The Korean display name is not discarded - it is recorded in the manifest's
``source_layer`` column, which is where a human looks.

No QGIS or GDAL imports here, so the rules are unit-testable in a plain Python
environment (see DEVELOPMENT.md and ``tests/test_predictor_naming.py``).
"""

from __future__ import annotations

import re

# Mirrors the consumer's own sanitiser. Kept as a literal copy rather than an
# import: predictor_preparation.md rules out a Python import in either
# direction, so this is a restatement of a documented contract, not a
# dependency. tests/test_predictor_naming.py pins the two to each other.
_NON_ASCII_WORD = re.compile(r"[^A-Za-z0-9_]+")

_VALID_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# A key that is only digits (``7``) or starts with one (``3000m``) is a legal
# identifier for the consumer but useless as a column header, and in a CSV it
# is liable to be read back as a number. Fall back to a prefixed form.
_LEADING_DIGIT = re.compile(r"^[0-9]")

FALLBACK_STEM = "layer"


def consumer_safe_name(value: str) -> str:
    """Reproduce the downstream ASCII reduction applied to a file base name.

    ``value`` is a base name, not a path - callers strip the extension first.
    Mirrors ArchModelBench's ``safe_name`` so :func:`is_round_trip_stable` can
    assert the export is a fixed point of it.
    """
    name = _NON_ASCII_WORD.sub("_", str(value or "")).strip("_")
    return name or "predictor"


def is_round_trip_stable(key: str) -> bool:
    """True when the consumer would leave ``key`` exactly as it is.

    This is the whole contract of this module: an exported file named
    ``f"{key}.tif"`` must produce the variable ``key`` downstream, so that the
    name in the manifest, the name typed into ``CATEGORICAL_PREDICTORS`` and
    the name printed in the report are all the same string.
    """
    key = str(key or "")
    return bool(key) and consumer_safe_name(key) == key


def sanitize_key(value: str) -> str:
    """Reduce one candidate to an ASCII key, or return "" if nothing survives.

    Returning "" rather than a placeholder keeps the decision with
    :func:`derive_variable_key`, which knows what to fall back to and can say
    so in the manifest.
    """
    cleaned = _NON_ASCII_WORD.sub("_", str(value or "")).strip("_")
    # Collapse the runs of underscores that punctuation in a display name
    # leaves behind. The substitution above already folds each *contiguous* run
    # of non-word characters into a single "_", so the shipped
    # "TRI (Riley et al. 1999 지수, 사용자 정의 5등급, 험준기준:5)" reduces cleanly to
    # "TRI_Riley_et_al_1999_5_5" on its own. This pass is for the case that
    # substitution cannot handle: a *literal* "_" in the name sitting next to
    # stripped text, as in "TRI_험준기준_5" -> "TRI___5" -> "TRI_5".
    cleaned = re.sub(r"_{2,}", "_", cleaned).strip("_")
    if not cleaned:
        return ""
    if _LEADING_DIGIT.match(cleaned):
        cleaned = f"v_{cleaned}"
    return cleaned if _VALID_KEY.match(cleaned) else ""


def derive_variable_key(kind: str = "", name: str = "", tool_id: str = "") -> str:
    """Pick the best ASCII key for one raster, before de-duplication.

    Preference order, each step used only when the previous one yields nothing:

    1. ``kind`` - the metadata token the producing tool already wrote. This is
       the case that matters: it is English, short and independent of the UI
       language, so a Korean project and an English one export the same names.
    2. ``tool_id`` + the display name, for a raster this plugin did not make
       but whose name still has usable ASCII in it.
    3. ``tool_id`` alone.

    Returns "" when every candidate reduces to nothing, which happens for a
    wholly Korean display name on a non-ArchToolkit layer.
    :func:`assign_variable_keys` turns that into a numbered fallback.
    """
    for candidate in (kind, name, tool_id):
        key = sanitize_key(candidate)
        if key:
            return key
    return ""


def assign_variable_keys(items):
    """Assign a unique, round-trip-stable key to each item, in list order.

    ``items`` is a sequence of mappings with optional ``kind``, ``name`` and
    ``tool_id`` entries. Returns a list of keys parallel to ``items``.

    De-duplication is by position in the given list, never by sorting names or
    paths. That matters: the consumer disambiguates collisions by the order it
    walks a folder, so two Korean names that both reduce to ``predictor`` get a
    numbering that changes when an unrelated file is added. Deciding it here,
    from the order the user sees in the dialog, makes the mapping reproducible
    and lets the manifest record it.
    """
    # ``taken`` holds case-folded keys. A key becomes a filename, and on NTFS
    # and default APFS/HFS+ - the two desktops QGIS mostly runs on - slope.tif
    # and Slope.tif are one file; the warp runs with -overwrite, so the second
    # raster would silently replace the first. The returned key keeps its
    # original case so the manifest still shows what the user named.
    taken: set = set()
    keys = []
    for index, item in enumerate(items or []):
        get = item.get if hasattr(item, "get") else (lambda k, d="": getattr(item, k, d))
        base = derive_variable_key(
            kind=str(get("kind", "") or ""),
            name=str(get("name", "") or ""),
            tool_id=str(get("tool_id", "") or ""),
        )
        if not base:
            # Nothing usable survived. A positional name is honest - it points
            # at the manifest row rather than pretending to describe the layer.
            base = f"{FALLBACK_STEM}_{index + 1:02d}"
        # Uniqueness is checked against every FINAL key handed out, not just
        # the bases. Counting bases alone let ("slope", "slope", "slope_2")
        # produce slope, slope_2, slope_2 - two rasters written to one file,
        # one predictor silently lost.
        key = base
        suffix = 2
        while key.casefold() in taken:
            key = f"{base}_{suffix}"
            suffix += 1
        # The suffix cannot break the contract (it is ASCII), but assert it
        # rather than trust it: everything downstream depends on this holding.
        if not is_round_trip_stable(key):  # pragma: no cover - defensive
            key = f"{FALLBACK_STEM}_{index + 1:02d}"
            while key.casefold() in taken:
                index += 1
                key = f"{FALLBACK_STEM}_{index + 1:02d}"
        taken.add(key.casefold())
        keys.append(key)
    return keys


def distance_variable_key(name, prefix="distance"):
    """``distance_<name>``, or None when ``name`` cannot survive downstream.

    A distance raster is named by the user, not by a tool's metadata, so the
    check has to happen while they can still fix it. Returning None lets the
    dialog say "use letters and digits" at the point of entry, instead of the
    user discovering in a model report that their column is called
    ``predictor_2``.
    """
    cleaned = sanitize_key(str(name or "").strip())
    if not cleaned:
        return None
    key = f"{prefix}_{cleaned}".lower()
    return key if is_round_trip_stable(key) else None


__all__ = [
    "FALLBACK_STEM",
    "assign_variable_keys",
    "consumer_safe_name",
    "derive_variable_key",
    "distance_variable_key",
    "is_round_trip_stable",
    "sanitize_key",
]
