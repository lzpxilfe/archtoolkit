from __future__ import annotations

import re
import unittest
from pathlib import Path

from tools.predictor_naming import (
    assign_variable_keys,
    consumer_safe_name,
    derive_variable_key,
    distance_variable_key,
    is_round_trip_stable,
    sanitize_key,
)


def _archmodelbench_safe_name(value: str) -> str:
    """Verbatim copy of the consumer's sanitiser.

    Transcribed from ArchModelBench ``arch_model_bench_core/utils.py``. The
    point of copying it here is that the tests below pin our mirror to the
    real thing; if the consumer ever changes this, these tests are where the
    divergence should be noticed and the contract renegotiated.
    """
    name = re.sub(r"[^A-Za-z0-9_]+", "_", Path(value).stem).strip("_")
    return name or "predictor"


def _archmodelbench_unique_names(paths):
    counts: dict = {}
    names = []
    for path in paths:
        base = _archmodelbench_safe_name(str(path))
        counts[base] = counts.get(base, 0) + 1
        names.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return names


class ConsumerMirrorTests(unittest.TestCase):
    """Our mirror must agree with the transcribed consumer implementation."""

    def test_mirror_matches_on_representative_names(self):
        # These are *base names*, i.e. what the consumer sees after Path().stem.
        # The shipped TRI layer contributes the key it exports as rather than its
        # display name: that display name contains a dot ("et al."), which
        # Path().stem would cut - see test_dotted_display_name_exports_cleanly.
        for value in (
            "slope",
            "경사도",
            "경사도_국토지리정보원_7등급",
            "TRI_Riley_et_al_1999_5_5",
            "curvature_profile",
            "",
            "___",
            "3000m",
        ):
            self.assertEqual(
                consumer_safe_name(value),
                _archmodelbench_safe_name(value),
                msg=f"mirror diverged for {value!r}",
            )

    def test_hangul_is_deleted_not_transcribed(self):
        # The premise of this whole module. If this ever stops being true the
        # naming workaround can be simplified.
        self.assertEqual(_archmodelbench_safe_name("경사도"), "predictor")
        self.assertEqual(_archmodelbench_safe_name("사면방향_8방위 (평탄=0)"), "8_0")


class RoundTripStabilityTests(unittest.TestCase):
    def test_kind_tokens_are_already_stable(self):
        # Every kind ArchToolkit writes must pass through untouched, or the
        # export gains a rename the manifest would not describe.
        for kind in (
            "slope", "aspect", "tri", "tpi", "roughness", "slope_position",
            "curvature_profile", "curvature_plan", "northness", "eastness",
            "trasp", "suitability", "geology_class", "class_raster",
            "value_raster", "viewshed_single", "cumulative", "dem",
        ):
            self.assertTrue(is_round_trip_stable(kind), msg=kind)

    def test_rejects_names_the_consumer_would_rewrite(self):
        for bad in ("경사도", "곡률-종단", "slope grid", "slope.1", "", "_slope"):
            self.assertFalse(is_round_trip_stable(bad), msg=bad)


class SanitizeKeyTests(unittest.TestCase):
    def test_collapses_punctuation_runs(self):
        # The shipped TRI layer name: every run of punctuation/Hangul folds to a
        # single "_" already, so this pins the key the exporter actually writes.
        self.assertEqual(
            sanitize_key("TRI (Riley et al. 1999 지수, 사용자 정의 5등급, 험준기준:5)"),
            "TRI_Riley_et_al_1999_5_5",
        )
        # The case that genuinely needs the collapse pass: a literal "_" in the
        # name next to stripped Hangul yields "TRI___5" before it is collapsed.
        self.assertEqual(sanitize_key("TRI_험준기준_5"), "TRI_5")

    def test_dotted_display_name_exports_cleanly(self):
        # The shipped TRI name contains "et al.", and the consumer runs
        # Path(value).stem *before* sanitising - fed that display name raw it
        # would cut everything after the dot and yield "TRI_Riley_et_al". The
        # export never hands over a display name, only the key, so this walks
        # the path the exporter really takes and requires the consumer to leave
        # the result alone. Same guard for the aspect layer's "(평탄=0)".
        for name, expected in (
            ("TRI (Riley et al. 1999 지수, 사용자 정의 5등급, 험준기준:5)", "TRI_Riley_et_al_1999_5_5"),
            ("사면방향_8방위 (평탄=0)", "v_8_0"),
            ("곡률-종단 profile (Z&T 1987, 부호규약: 음=볼록)", "profile_Z_T_1987"),
        ):
            key = sanitize_key(name)
            self.assertEqual(key, expected, msg=name)
            self.assertEqual(_archmodelbench_safe_name(f"{key}.tif"), key, msg=name)

    def test_returns_empty_when_nothing_ascii_survives(self):
        self.assertEqual(sanitize_key("경사도"), "")
        self.assertEqual(sanitize_key("사면방향"), "")
        self.assertEqual(sanitize_key(""), "")

    def test_prefixes_leading_digit(self):
        # "가시권_단일점_3000m" would otherwise reduce to "3000m", which reads
        # as a number in a CSV header.
        self.assertEqual(sanitize_key("가시권_단일점_3000m"), "v_3000m")
        self.assertEqual(sanitize_key("7등급"), "v_7")

    def test_sanitized_output_is_always_round_trip_stable(self):
        for value in ("TRI (Riley et al. 1999 지수, 사용자 정의 5등급, 험준기준:5)",
                      "사면방향_8방위 (평탄=0)", "가시권_단일점_3000m",
                      "북향성 northness = cos(aspect)", "비용표면 (Tobler, 시간)"):
            key = sanitize_key(value)
            if key:
                self.assertTrue(is_round_trip_stable(key), msg=f"{value!r} -> {key!r}")


class DeriveVariableKeyTests(unittest.TestCase):
    def test_kind_wins_over_korean_display_name(self):
        self.assertEqual(
            derive_variable_key(kind="slope", name="경사도_국토지리정보원_7등급"),
            "slope",
        )

    def test_falls_back_to_display_name_when_kind_absent(self):
        self.assertEqual(derive_variable_key(kind="", name="landcover_2023"), "landcover_2023")

    def test_falls_back_to_tool_id_when_name_is_korean(self):
        self.assertEqual(derive_variable_key(kind="", name="경사도", tool_id="terrain_analysis"),
                         "terrain_analysis")

    def test_returns_empty_when_everything_is_korean(self):
        self.assertEqual(derive_variable_key(kind="", name="경사도", tool_id=""), "")


class AssignVariableKeysTests(unittest.TestCase):
    def test_the_failing_real_world_stack_becomes_readable(self):
        # The exact layers a Korean ArchToolkit session produces. Before this
        # module these exported as Korean filenames and arrived downstream as
        # '7', '8_0', 'KIGAM', 'predictor', 'predictor_2'.
        items = [
            {"kind": "slope", "name": "경사도_국토지리정보원_7등급", "tool_id": "terrain_analysis"},
            {"kind": "aspect", "name": "사면방향_8방위 (평탄=0)", "tool_id": "terrain_analysis"},
            {"kind": "tri", "name": "TRI (Riley et al. 1999 지수, 사용자 정의 5등급, 험준기준:5)",
             "tool_id": "terrain_analysis"},
            {"kind": "curvature_profile", "name": "곡률-종단 profile (Z&T 1987, 부호규약: 음=볼록)",
             "tool_id": "terrain_analysis"},
            {"kind": "trasp", "name": "TRASP 일사프록시 (Roberts & Cooper 1989)",
             "tool_id": "terrain_analysis"},
            {"kind": "geology_class", "name": "지질도 래스터 (KIGAM)", "tool_id": "kigam_raster"},
            {"kind": "suitability", "name": "적합도 (AHP)", "tool_id": "ahp_suitability"},
        ]
        self.assertEqual(
            assign_variable_keys(items),
            ["slope", "aspect", "tri", "curvature_profile", "trasp",
             "geology_class", "suitability"],
        )

    def test_keys_survive_the_consumer_unchanged(self):
        items = [
            {"kind": "slope", "name": "경사도"},
            {"kind": "geology_class", "name": "지질도"},
            {"kind": "", "name": "고도"},
            {"kind": "", "name": "표고"},
        ]
        keys = assign_variable_keys(items)
        # This is the end-to-end assertion: run the exported filenames through
        # the consumer's own pipeline and require the names to come back
        # identical, with no collisions introduced.
        exported = [f"{k}.tif" for k in keys]
        self.assertEqual(_archmodelbench_unique_names(exported), keys)

    def test_duplicate_kinds_are_numbered_in_list_order(self):
        items = [
            {"kind": "viewshed_single", "name": "가시권_A"},
            {"kind": "viewshed_single", "name": "가시권_B"},
            {"kind": "viewshed_single", "name": "가시권_C"},
        ]
        self.assertEqual(
            assign_variable_keys(items),
            ["viewshed_single", "viewshed_single_2", "viewshed_single_3"],
        )

    def test_numbering_is_positional_not_name_sorted(self):
        # The consumer numbers collisions by the order it walks the folder,
        # which for Korean names is Unicode codepoint order and shifts when an
        # unrelated file appears. Ours must follow the dialog's list order.
        forward = assign_variable_keys([{"kind": "slope", "name": "힣"},
                                        {"kind": "slope", "name": "가"}])
        self.assertEqual(forward, ["slope", "slope_2"])

    def test_unusable_names_get_positional_fallbacks_not_collisions(self):
        items = [{"kind": "", "name": "경사도"}, {"kind": "", "name": "사면방향"},
                 {"kind": "", "name": "고도"}]
        keys = assign_variable_keys(items)
        self.assertEqual(keys, ["layer_01", "layer_02", "layer_03"])
        self.assertEqual(len(set(keys)), 3)
        for key in keys:
            self.assertTrue(is_round_trip_stable(key))

    def test_suffix_never_collides_with_another_items_base(self):
        # Found in review: counting bases alone gave slope, slope_2, slope_2.
        # Two rasters then warp to the same {key}.tif and one is lost.
        keys = assign_variable_keys([
            {"kind": "slope", "name": "a"},
            {"kind": "slope", "name": "b"},
            {"kind": "slope_2", "name": "c"},
        ])
        self.assertEqual(len(set(keys)), 3, msg=f"collision in {keys}")
        keys = assign_variable_keys([
            {"kind": "viewshed_single", "name": "a"},
            {"kind": "viewshed_single", "name": "b"},
            {"kind": "viewshed_single_2", "name": "c"},
            {"kind": "viewshed_single", "name": "d"},
        ])
        self.assertEqual(len(set(keys)), 4, msg=f"collision in {keys}")
        # And the exported filenames must still survive the consumer as a set.
        self.assertEqual(len(set(_archmodelbench_unique_names([f"{k}.tif" for k in keys]))), 4)

    def test_keys_differing_only_by_case_are_made_distinct(self):
        # Keys become filenames, and NTFS / default APFS are case-insensitive:
        # slope.tif and Slope.tif are one file there, and gdalwarp -overwrite
        # replaces the first predictor with the second without a word. The
        # natural pairing is an ArchToolkit product next to the user's own
        # layer of the same name.
        for items in (
            [{"kind": "slope", "name": "경사도", "tool_id": "terrain_analysis"},
             {"kind": "", "name": "Slope"}],
            [{"kind": "dem", "name": "DEM_생성", "tool_id": "dem_generate"},
             {"kind": "", "name": "DEM"}],
            [{"kind": "", "name": "TRI"}, {"kind": "tri", "name": "x"},
             {"kind": "", "name": "Tri"}],
        ):
            keys = assign_variable_keys(items)
            folded = [k.casefold() for k in keys]
            self.assertEqual(len(set(folded)), len(items), msg=f"case collision in {keys}")
            for key in keys:
                self.assertTrue(is_round_trip_stable(key), msg=key)
        # The first occurrence keeps its case; only the later one is suffixed.
        self.assertEqual(
            assign_variable_keys([{"kind": "slope", "name": "a"}, {"kind": "", "name": "Slope"}]),
            ["slope", "Slope_2"],
        )

    def test_fallback_and_derived_keys_never_collide(self):
        items = [{"kind": "layer_01", "name": "x"}, {"kind": "", "name": "경사도"}]
        keys = assign_variable_keys(items)
        self.assertEqual(len(set(keys)), 2, msg=f"collision in {keys}")

    def test_empty_input(self):
        self.assertEqual(assign_variable_keys([]), [])
        self.assertEqual(assign_variable_keys(None), [])


class DistanceVariableKeyTests(unittest.TestCase):
    """Distance rasters are named by the user, so the name is checked on entry."""

    def test_builds_a_prefixed_key(self):
        self.assertEqual(distance_variable_key("water"), "distance_water")
        self.assertEqual(distance_variable_key("Road"), "distance_road")
        self.assertEqual(distance_variable_key(" site "), "distance_site")

    def test_rejects_a_name_with_no_ascii(self):
        # This is the whole point of asking up front: the consumer would turn
        # "distance_하천" into "distance" and collide with the next one.
        self.assertIsNone(distance_variable_key("하천"))
        self.assertIsNone(distance_variable_key(""))
        self.assertIsNone(distance_variable_key(None))

    def test_mixed_names_keep_their_ascii_part(self):
        self.assertEqual(distance_variable_key("하천 river"), "distance_river")

    def test_result_survives_the_consumer(self):
        for name in ("water", "River 2023", "iron-ore", "하천 river", "site_5179"):
            key = distance_variable_key(name)
            if key is not None:
                self.assertTrue(is_round_trip_stable(key), msg=f"{name!r} -> {key!r}")
                self.assertEqual(_archmodelbench_safe_name(f"{key}.tif"), key)

    def test_distinct_sources_give_distinct_keys(self):
        keys = {distance_variable_key(n) for n in ("water", "road", "site")}
        self.assertEqual(len(keys), 3)


if __name__ == "__main__":
    unittest.main()
