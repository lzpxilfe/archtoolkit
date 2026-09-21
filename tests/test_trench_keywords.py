"""Grave-keyword, legend-code and reference-distance helpers of the trench tool.

tools.trench_suggestion_dialog imports PyQGIS at module level, so this test
installs throw-away stand-ins for the qgis/processing modules just long enough
to import it, then restores sys.modules so the QGIS-optional tests elsewhere
still see a genuine ImportError. Everything exercised here is pure Python.
"""

from __future__ import annotations

import importlib
import math
import sys
import types
import unittest

_STUB_MODULES = (
    "qgis",
    "qgis.PyQt",
    "qgis.PyQt.QtWidgets",
    "qgis.PyQt.QtCore",
    "qgis.PyQt.QtGui",
    "qgis.core",
    "qgis.gui",
    "processing",
)


class _StubMeta(type):
    def __getattr__(cls, name):
        return _stub_class(name)


def _stub_class(name):
    return _StubMeta(name, (object,), {"__init__": lambda self, *a, **k: None})


def _stub_module(name):
    mod = types.ModuleType(name)
    mod.__getattr__ = lambda attr: _stub_class(attr)
    mod.__path__ = []
    return mod


def _import_dialog_module():
    saved = dict(sys.modules)
    try:
        for name in _STUB_MODULES:
            sys.modules[name] = _stub_module(name)
        sys.modules.pop("tools.trench_suggestion_dialog", None)
        return importlib.import_module("tools.trench_suggestion_dialog")
    finally:
        for name in list(sys.modules):
            if name not in saved:
                del sys.modules[name]
        sys.modules.update(saved)


try:
    tsd = _import_dialog_module()
    IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment dependent
    tsd = None
    IMPORT_ERROR = exc


_NEW_KO_STEMS = (
    "지석묘", "고인돌", "석실묘", "석곽묘", "석실분", "석곽분", "토광묘",
    "옹관묘", "목관묘", "목곽묘", "분구묘", "주구묘", "봉토분", "적석총",
)


@unittest.skipIf(tsd is None, f"trench dialog not importable: {IMPORT_ERROR}")
class GraveKeywordTests(unittest.TestCase):
    def test_burial_type_stems_match(self):
        for stem in _NEW_KO_STEMS:
            self.assertTrue(tsd._text_has_grave_keyword(stem), stem)
            self.assertIn(stem, tsd._GRAVE_KW_KO)
        for label in ("OO리 지석묘군", "OO 석실묘 3호", "OO 토광묘", "횡혈식석실분", "옹관묘 A0010000"):
            self.assertTrue(tsd._text_has_grave_keyword(label), label)

    def test_generic_terms_still_match(self):
        for text in ("무덤", "분묘", "묘지", "묘역", "봉분", "고분군", "고분", "왕릉", "능묘", "가족묘", "공동묘"):
            self.assertTrue(tsd._text_has_grave_keyword(text), text)

    def test_suffix_rules_for_chong_and_reung(self):
        for text in ("천마총", "고총", "황남대총", "선릉", "정릉 A0010000", "태릉 3호"):
            self.assertTrue(tsd._text_has_grave_keyword(text), text)
        for text in ("선릉역", "구릉", "구릉지", "총계", "총합", "총량", "총면적 12", "능선", "릉선", "총 3건", "3총"):
            self.assertFalse(tsd._text_has_grave_keyword(text), text)

    def test_known_false_positives_stay_negative(self):
        for text in ("묘목", "묘사", "교묘", "고분자", "패총", "OO리 패총", "권총", "강릉", "강릉시", "gravel", "cistern", "", None):
            self.assertFalse(tsd._text_has_grave_keyword(text), repr(text))

    def test_english_terms(self):
        for text in ("tumulus", "Tumuli", "barrow", "barrows", "dolmen", "cist", "cists", "cemeteries", "Tomb", "graves"):
            self.assertTrue(tsd._text_has_grave_keyword(text), text)

    def test_search_term_count_matches_list(self):
        terms = tsd._grave_search_terms()
        self.assertEqual(tsd._GRAVE_SEARCH_TERM_COUNT, len(terms))
        self.assertGreaterEqual(len(terms), 30)
        for stem in _NEW_KO_STEMS + ("무덤", "tomb", "dolmen", "cemeteries"):
            self.assertIn(stem, terms)


@unittest.skipIf(tsd is None, f"trench dialog not importable: {IMPORT_ERROR}")
class LegendCodeRegexTests(unittest.TestCase):
    def test_code_adjacent_to_hangul_is_found(self):
        cases = {
            "묘지A0010000": ["A0010000"],
            "묘지(A0010000)": ["A0010000"],
            "분묘 A0010000": ["A0010000"],
            "A0010000": ["A0010000"],
            "A0010000묘지": ["A0010000"],
            "XA0010000": [],
            "A001000": [],
            "B00100011": ["B00100011"],
        }
        for text, expected in cases.items():
            self.assertEqual(tsd._CODE_RE.findall(text), expected, text)

    def test_extract_grave_codes_from_glued_cells(self):
        rows = [["묘지A0010000"], ["분묘", "B0010001"], ["도로", "C0010000"], ["구릉 D0010000"]]
        codes = tsd.TrenchSuggestionDialog._extract_grave_codes(None, rows)
        self.assertEqual(codes, {"A0010000", "B0010001"})


@unittest.skipIf(tsd is None, f"trench dialog not importable: {IMPORT_ERROR}")
class LegendWorkbookTests(unittest.TestCase):
    def test_sublayer_name_is_second_field_of_unlimited_split(self):
        self.assertEqual(tsd._sublayer_name("0!!::!!Sheet1!!::!!12!!::!!None"), "Sheet1")
        self.assertEqual(tsd._sublayer_name("1!!::!!범례!!::!!842!!::!!None!!::!!"), "범례")
        self.assertEqual(tsd._sublayer_name("Sheet1"), "Sheet1")
        self.assertEqual(tsd._sublayer_name(""), "")
        self.assertEqual(tsd._sublayer_name(None), "")

    def test_modern_workbook_extensions_are_accepted(self):
        for name in ("legend.xls", "LEGEND.XLSX", "legend.xlsm"):
            self.assertTrue(tsd._is_legend_workbook_name(name), name)
        for name in ("legend.csv", "legend.xls.bak", "", None):
            self.assertFalse(tsd._is_legend_workbook_name(name), repr(name))


class _Crs:
    def __init__(self, geographic):
        self._geo = geographic

    def isGeographic(self):
        return self._geo


@unittest.skipIf(tsd is None, f"trench dialog not importable: {IMPORT_ERROR}")
class GraveFetchMarginTests(unittest.TestCase):
    def test_margin_covers_half_trench_length(self):
        # 500 m trench at inside_ratio 0.95 protrudes 25 m; the old 6 m margin missed it.
        self.assertEqual(tsd._grave_fetch_margin_m(3.0, 500.0), 258.0)
        self.assertEqual(tsd._grave_fetch_margin_m(3.0, 20.0), 18.0)
        self.assertGreater(tsd._grave_fetch_margin_m(3.0, 20.0), 6.0)
        self.assertEqual(tsd._grave_fetch_margin_m(0.0, 0.0), 5.0)

    def test_meters_to_crs_units(self):
        self.assertEqual(tsd._meters_to_crs_units(100.0, _Crs(False)), 100.0)
        self.assertEqual(tsd._meters_to_crs_units(100.0, None), 100.0)
        deg = tsd._meters_to_crs_units(100.0, _Crs(True), ref_y=37.5)
        self.assertAlmostEqual(deg, 100.0 / (111320.0 * math.cos(math.radians(37.5))), places=12)
        self.assertGreater(deg, 100.0 / 111320.0)


class _Box:
    def __init__(self, xmin, ymin, xmax, ymax):
        self._v = (xmin, ymin, xmax, ymax)

    def xMinimum(self):
        return self._v[0]

    def yMinimum(self):
        return self._v[1]

    def xMaximum(self):
        return self._v[2]

    def yMaximum(self):
        return self._v[3]


class _Geom:
    """Stand-in reference geometry: a bounding box and a fixed true distance."""

    def __init__(self, box, true_dist):
        self._box = box
        self._d = true_dist
        self.measured = 0

    def boundingBox(self):
        return self._box

    def distance(self, _ptg):
        self.measured += 1
        return self._d


class _Pt:
    def __init__(self, x, y):
        self._x = x
        self._y = y

    def x(self):
        return self._x

    def y(self):
        return self._y


class _Index:
    def __init__(self, rect_ids, knn_ids):
        self.rect_ids = list(rect_ids)
        self.knn_ids = list(knn_ids)
        self.knn_calls = []

    def intersects(self, _rect):
        return list(self.rect_ids)

    def nearestNeighbor(self, _pt, k):
        self.knn_calls.append(k)
        return list(self.knn_ids[:k])


def _crowded_reference_set():
    """Nine hillside polygons whose boxes contain the point (true distance
    700-900 m) plus one small site 50 m away, as in the audit scenario."""
    geoms = {}
    for i in range(9):
        geoms[i] = _Geom(_Box(-5000, -5000, 5000, 5000), 700.0 + 25.0 * i)
    geoms[9] = _Geom(_Box(50, -1, 60, 1), 50.0)
    return geoms


@unittest.skipIf(tsd is None, f"trench dialog not importable: {IMPORT_ERROR}")
class NearestReferenceDistanceTests(unittest.TestCase):
    def test_min_true_distance_is_exact_and_prunes_by_box(self):
        geoms = _crowded_reference_set()
        far = _Geom(_Box(2000, 2000, 2100, 2100), 2800.0)
        geoms[10] = far
        ptg = object()
        d = tsd._min_true_distance(list(geoms.keys()), geoms, ptg, 0.0, 0.0)
        self.assertEqual(d, 50.0)
        # Its box is 2828 m away, farther than the 50 m already found: never measured.
        self.assertEqual(far.measured, 0)

    def test_min_true_distance_ignores_negative_and_missing(self):
        geoms = {1: _Geom(_Box(0, 0, 1, 1), -1.0), 2: _Geom(_Box(0, 0, 1, 1), 12.0)}
        self.assertEqual(tsd._min_true_distance([1, 2, 99], geoms, object(), 0.0, 0.0), 12.0)
        self.assertIsNone(tsd._min_true_distance([1], geoms, object(), 0.0, 0.0))
        self.assertIsNone(tsd._min_true_distance([], geoms, object(), 0.0, 0.0))

    def test_rectangle_query_finds_the_small_site_the_8nn_missed(self):
        geoms = _crowded_reference_set()
        # A bbox-ranked k-NN puts the nine zero-box-distance polygons first.
        idx = _Index(rect_ids=range(10), knn_ids=list(range(9)) + [9])
        fn = tsd.TrenchSuggestionDialog._nearest_reference_distance
        d = fn(None, idx, geoms, _Pt(0.0, 0.0), radius_m=1000.0)
        self.assertEqual(d, 50.0)
        self.assertEqual(idx.knn_calls, [])

    def test_falls_back_to_k32_when_nothing_is_within_radius(self):
        geoms = {1: _Geom(_Box(3000, 3000, 3100, 3100), 4200.0), 2: _Geom(_Box(2500, 0, 2600, 10), 2500.0)}
        idx = _Index(rect_ids=[], knn_ids=[1, 2])
        fn = tsd.TrenchSuggestionDialog._nearest_reference_distance
        d = fn(None, idx, geoms, _Pt(0.0, 0.0), radius_m=1000.0)
        self.assertEqual(d, 2500.0)
        self.assertEqual(idx.knn_calls, [32])

    def test_beyond_radius_merges_rectangle_and_knn_results(self):
        # The rectangle only caught a huge polygon whose true edge is 1500 m
        # away; the k-NN pass finds a 1200 m point the rectangle missed.
        geoms = {1: _Geom(_Box(-9000, -9000, 9000, 9000), 1500.0), 2: _Geom(_Box(1200, 0, 1201, 1), 1200.0)}
        idx = _Index(rect_ids=[1], knn_ids=[1, 2])
        fn = tsd.TrenchSuggestionDialog._nearest_reference_distance
        d = fn(None, idx, geoms, _Pt(0.0, 0.0), radius_m=1000.0)
        self.assertEqual(d, 1200.0)
        self.assertEqual(idx.knn_calls, [32])

    def test_empty_reference_set_is_none(self):
        fn = tsd.TrenchSuggestionDialog._nearest_reference_distance
        self.assertIsNone(fn(None, _Index([], []), {}, _Pt(0.0, 0.0), radius_m=1000.0))


class StubHygieneTests(unittest.TestCase):
    def test_stub_modules_did_not_leak(self):
        for name in _STUB_MODULES:
            mod = sys.modules.get(name)
            self.assertFalse(isinstance(mod, types.ModuleType) and hasattr(mod, "__getattr__") and not getattr(mod, "__file__", None), name)


if __name__ == "__main__":
    unittest.main()
