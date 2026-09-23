from __future__ import annotations

import ast
import os
import unittest

from tools.raster_semantics import choose_nodata_sentinel, is_categorical_meta

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")


def _literal_metadata_calls():
    """Every set_archtoolkit_layer_metadata call whose tool_id/kind/units are literals.

    The KIGAM bug lived because nothing connected the categorical rule to the
    metadata the producing tools actually write: the rule tested for a tool_id
    of "geology" while the tool wrote "kigam_raster". Scanning the real call
    sites is what closes that gap - a new tool, or a changed kind, shows up
    here rather than silently falling into the continuous branch.

    Call sites that pass a variable (``kind=kind``) cannot be resolved
    statically and are returned separately so the test can assert they are
    still a known, bounded set.
    """
    resolved = []
    dynamic = []
    for entry in sorted(os.listdir(TOOLS_DIR)):
        if not entry.endswith(".py"):
            continue
        path = os.path.join(TOOLS_DIR, entry)
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source, filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name != "set_archtoolkit_layer_metadata":
                continue
            fields = {}
            has_dynamic = False
            for kw in node.keywords:
                if kw.arg not in ("tool_id", "kind", "units"):
                    continue
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    fields[kw.arg] = kw.value.value
                else:
                    has_dynamic = True
            record = (entry, node.lineno, fields.get("tool_id", ""),
                      fields.get("kind", ""), fields.get("units", ""))
            (dynamic if has_dynamic else resolved).append(record)
    return resolved, dynamic


# Every literal (tool_id, kind, units) the plugin writes, and whether that
# raster holds nominal class codes. Vector outputs are listed too - they never
# reach align/export, but pinning them keeps the table a complete census of the
# call sites, so a new one cannot be added without a decision being recorded.
EXPECTED = {
    # --- rasters: nominal class codes -------------------------------------
    ("kigam_raster", "geology_class", "class"): True,        # 1:50,000 lithology
    ("terrain_analysis", "slope_position", "class"): True,   # Weiss (2001) 6-class
    ("viewshed", "visual_imbalance", "class"): True,         # 동일/전방만/역방향만
    ("viewshed", "reverse_union", "mask"): True,             # binary union mask
    ("viewshed", "reverse_visual_imbalance_reverse", "mask"): True,
    ("kigam_zip", "vector", ""): True,                       # geology vectors
    # --- rasters: measurements --------------------------------------------
    ("terrain_analysis", "slope", "deg"): False,
    ("terrain_analysis", "aspect", "deg"): False,
    ("terrain_analysis", "tri", "m"): False,
    ("terrain_analysis", "tri_radius", "m"): False,
    ("terrain_analysis", "tpi", "m"): False,
    ("terrain_analysis", "roughness", "m"): False,
    ("dem_generate", "dem", "m"): False,
    ("dem_generate", "kriging_variance", "m^2"): False,
    ("slope_aspect_drafting", "slope_grid", "deg"): False,
    ("map_styling", "dem_hillshade", "m"): False,
    ("map_styling", "dem_gray", "m"): False,
    ("map_styling", "dem_color", "m"): False,
    # --- vector outputs (never reach align/export; pinned for completeness) -
    ("cadastral_overlap", "overlap", "m2/%"): False,
    ("cadastral_overlap", "overlap_by_aoi", "m2/%"): False,
    ("contour_extract", "contours", "m"): False,
    ("cost_network", "edges", "m/min/kcal"): False,
    ("cost_network", "nodes", ""): False,
    ("spatial_network", "edges", "m"): False,
    ("spatial_network", "nodes_metrics", ""): False,
    ("terrain_profile", "profile_single", "m"): False,
    ("terrain_profile", "profile_lines", "m"): False,
    ("trench_suggestion", "trench_polygon", "m"): False,
    ("trench_suggestion", "trench_center", "m"): False,
    ("slope_aspect_drafting", "aspect_arrows", "deg"): False,
    ("map_styling", "styled_vector", ""): False,
    ("viewshed", "analysis_radius_ring", "m"): False,
    ("viewshed", "aoi_stats", "m2/%"): False,
    ("viewshed", "observer_points", ""): False,
}

# Call sites that choose kind/units at runtime, so the AST census cannot read
# them. Their real values are pinned here by hand.
RUNTIME_EXPECTED = {
    ("geochem", "class_raster", "class"): True,
    ("geochem", "value_raster", "ppm"): False,
    ("ahp_suitability", "suitability", ""): False,
    ("terrain_analysis", "curvature_profile", "1/m"): False,
    ("terrain_analysis", "curvature_plan", "1/m"): False,
    ("terrain_analysis", "northness", "index"): False,
    ("terrain_analysis", "eastness", "index"): False,
    ("terrain_analysis", "trasp", "index"): False,
    ("viewshed", "viewshed_single", "mask"): True,
    ("viewshed", "higuchi", "mask"): True,
    ("viewshed", "reverse_single", "mask"): True,
    ("viewshed", "union", "mask"): True,               # binary across observers
    ("viewshed", "cumulative", "count"): False,        # a count surface
    ("viewshed", "count", "count"): False,
    ("viewshed", "weighted_percent", "percent"): False,
    ("viewshed", "weighted_cumulative", "weight"): False,
    ("distance_raster", "distance_water", "m"): False,
    ("distance_raster", "distance_site", "m"): False,
    ("cost_surface", "cost_time", "min"): False,
    ("cost_surface", "cost_energy", "kcal"): False,
}


class KnownMetadataTests(unittest.TestCase):
    def test_every_expected_triple_classifies_as_recorded(self):
        combined = dict(EXPECTED)
        combined.update(RUNTIME_EXPECTED)
        for (tool_id, kind, units), expected in combined.items():
            meta = {"tool_id": tool_id, "kind": kind, "units": units}
            self.assertEqual(
                is_categorical_meta(meta), expected,
                msg=f"{tool_id}/{kind}/{units!r} should be "
                    f"{'categorical' if expected else 'continuous'}",
            )

    def test_kigam_geology_raster_is_categorical(self):
        """The regression this module exists for.

        Before the fix the KIGAM raster was tagged kind="raster" with no units
        and the rule tested `"geology" in tool_id` against "kigam_raster", so
        it took the continuous branch: bilinear resampling and a Float32 cast
        applied to nominal lithology codes.
        """
        self.assertTrue(is_categorical_meta(
            {"tool_id": "kigam_raster", "kind": "geology_class", "units": "class"}))
        # The old tagging must still be caught, for projects saved before the
        # fix whose layers carry the old custom properties.
        self.assertTrue(is_categorical_meta(
            {"tool_id": "kigam_raster", "kind": "raster", "units": ""}))

    def test_binary_masks_are_categorical(self):
        self.assertTrue(is_categorical_meta(
            {"tool_id": "viewshed", "kind": "viewshed_single", "units": "mask"}))

    def test_counts_stay_continuous(self):
        # A cumulative viewshed is a count surface, not a mask; averaging it is
        # meaningful, so it must NOT take the nearest-neighbour branch.
        self.assertFalse(is_categorical_meta(
            {"tool_id": "viewshed", "kind": "cumulative", "units": "count"}))

    def test_union_and_count_modes_are_told_apart(self):
        # Both came out of the same branch tagged "mask/count", which matched
        # neither rule, so the binary union was resampled bilinearly.
        self.assertTrue(is_categorical_meta(
            {"tool_id": "viewshed", "kind": "union", "units": "mask"}))
        self.assertFalse(is_categorical_meta(
            {"tool_id": "viewshed", "kind": "count", "units": "count"}))

    def test_missing_or_malformed_metadata_is_not_categorical(self):
        for meta in (None, {}, {"kind": None}, {"tool_id": 5}, "not-a-dict"):
            self.assertFalse(is_categorical_meta(meta), msg=repr(meta))


class NodataSentinelTests(unittest.TestCase):
    """A categorical export with no NoData disables the consumer's own checks.

    The value has to sit outside the codes in use: stamping one that is in use
    deletes that class silently, which is worse than having no NoData at all.
    """

    def test_picks_a_value_just_outside_the_code_range(self):
        self.assertEqual(choose_nodata_sentinel("Byte", 0, 14), 15)
        self.assertEqual(choose_nodata_sentinel("Int16", -5, 30), -6)

    def test_kigam_lithology_case(self):
        # Int32 codes 1..47 - the shape the KIGAM rasteriser produces.
        sentinel = choose_nodata_sentinel("Int32", 1, 47)
        self.assertIsNotNone(sentinel)
        self.assertFalse(1 <= sentinel <= 47)

    def test_never_returns_a_value_inside_the_data(self):
        for type_name, low, high in (("Byte", 0, 14), ("Byte", 3, 200),
                                     ("Int16", -300, 300), ("Int32", 1, 47),
                                     ("UInt16", 0, 4), ("Int8", -128, 126)):
            sentinel = choose_nodata_sentinel(type_name, low, high)
            if sentinel is not None:
                self.assertFalse(low <= sentinel <= high,
                                 msg=f"{type_name} {low}-{high} -> {sentinel}")

    def test_returns_none_when_the_data_spans_the_whole_type(self):
        # Refusing is correct: any value would delete a class in use.
        self.assertIsNone(choose_nodata_sentinel("Byte", 0, 255))
        self.assertIsNone(choose_nodata_sentinel("UInt16", 0, 65535))

    def test_returns_none_for_float_and_unknown_types(self):
        self.assertIsNone(choose_nodata_sentinel("Float32", 0, 10))
        self.assertIsNone(choose_nodata_sentinel("Float64", 0, 10))
        self.assertIsNone(choose_nodata_sentinel("", 0, 10))
        self.assertIsNone(choose_nodata_sentinel(None, 0, 10))

    def test_returns_none_on_unusable_statistics(self):
        self.assertIsNone(choose_nodata_sentinel("Byte", float("nan"), 10))
        self.assertIsNone(choose_nodata_sentinel("Byte", float("inf"), 10))
        self.assertIsNone(choose_nodata_sentinel("Byte", 10, 0))   # min > max
        self.assertIsNone(choose_nodata_sentinel("Byte", None, 10))

    def test_sentinel_is_representable_in_the_band_type(self):
        for type_name, (type_min, type_max) in (
            ("Byte", (0, 255)), ("Int16", (-32768, 32767)), ("Int32", (-2147483648, 2147483647)),
        ):
            sentinel = choose_nodata_sentinel(type_name, 5, 9)
            self.assertIsNotNone(sentinel)
            self.assertTrue(type_min <= sentinel <= type_max)


class CallSiteCensusTests(unittest.TestCase):
    """Guards against a producer being added without a categorical decision."""

    def test_every_literal_call_site_is_in_the_expected_table(self):
        resolved, _ = _literal_metadata_calls()
        self.assertTrue(resolved, "found no literal metadata call sites - scan broke")
        unknown = sorted({
            (tool_id, kind, units)
            for _file, _line, tool_id, kind, units in resolved
            if (tool_id, kind, units) not in EXPECTED
        })
        self.assertEqual(
            unknown, [],
            msg="New or changed layer metadata found. Add each triple to "
                "EXPECTED with an explicit True/False so a categorical raster "
                "cannot reach align/export as a measurement:\n  "
                + "\n  ".join(map(repr, unknown)),
        )

    def test_dynamic_call_sites_stay_a_known_set(self):
        # These pass kind=<variable>; the census cannot resolve them, so they
        # are pinned by count. A new one means a tool now chooses its kind at
        # runtime and needs its own coverage.
        _resolved, dynamic = _literal_metadata_calls()
        files = sorted({entry for entry, _line, _t, _k, _u in dynamic})
        self.assertEqual(
            files,
            ["ahp_suitability_dialog.py", "align_export_dialog.py", "cost_surface_dialog.py",
             "distance_raster_dialog.py", "geochem_polygonize_dialog.py",
             "terrain_analysis_dialog.py", "viewshed_dialog.py"],
            msg=f"dynamic metadata call sites changed: {dynamic}",
        )


if __name__ == "__main__":
    unittest.main()
