# -*- coding: utf-8 -*-
"""
Trench suggestion tool (MVP) for ArchToolkit.
"""

from __future__ import annotations

import math
import os
import re
import tempfile
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsMapLayerProxyModel,
    QgsMarkerSymbol,
    QgsPointXY,
    QgsProject,
    QgsProviderRegistry,
    QgsRaster,
    QgsRasterBandStats,
    QgsRasterLayer,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsSpatialIndex,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox

import processing

from .help_dialog import show_help_dialog
from . import dialog_memory
from .icons import icon as plugin_icon
from .live_log_dialog import ensure_live_log_dialog
from .utils import (
    is_null_value,
    log_swallowed,
    cleanup_files,
    get_archtoolkit_layer_metadata,
    is_metric_crs,
    log_exception,
    log_message,
    new_run_id,
    push_message,
    restore_ui_focus,
    set_archtoolkit_layer_metadata,
)

# Korean grave/tomb terms. Bare "묘" (1 char) is deliberately excluded: it is a
# frequent substring of unrelated words (묘목=seedling, 묘사=description,
# 교묘=cunning) and would produce false "grave" hits. Only specific 2+ char
# compounds are matched. English terms are matched on word boundaries so
# "grave" does not fire on "gravel".
_GRAVE_KW_KO = (
    "무덤",
    "분묘",
    "묘지",
    "묘역",
    "봉분",
    "고분군",
    "고분",
    "왕릉",
    "능묘",
    "가족묘",
    "공동묘",
    # Burial-type names that Korean excavation/survey data uses as feature and
    # legend labels (a dolmen row reads "OO리 지석묘군", never "무덤").
    # 패총 (shell midden) is deliberately NOT here.
    "지석묘",
    "고인돌",
    "석실묘",
    "석곽묘",
    "석실분",
    "석곽분",
    "토광묘",
    "옹관묘",
    "목관묘",
    "목곽묘",
    "분구묘",
    "주구묘",
    "봉토분",
    "적석총",
)
_GRAVE_KW_EN = (
    "tomb",
    "grave",
    "burial",
    "cemetery",
    "tumulus",
    "barrow",
    "dolmen",
    "cist",
)
# English plurals the `s?` suffix in the matcher does not produce.
_GRAVE_KW_EN_IRREGULAR = (
    "cemeteries",
    "tumuli",
)
# Korean compounds that contain a grave term as a substring but are NOT graves.
# They are removed from the text before any Korean rule runs.
_GRAVE_KO_FALSE = (
    "고분자",  # polymer / macromolecule
    # Guards for the 총/릉 suffix rules below.
    "총계",  # total (count)
    "총합",  # sum
    "총량",  # total amount
    "총면적",  # total area
    "패총",  # shell midden - a site, not a grave
    "권총",  # pistol
    "소총",  # rifle
    "엽총",  # shotgun
    "기관총",  # machine gun
    "구릉",  # hill
    "강릉",  # Gangneung (city)
    "능선",  # ridge
    "릉선",  # ridge (variant spelling)
)
# Suffix rules: a Hangul syllable followed by 총 (mounded tomb: 천마총, 고총,
# 황남대총) or 릉 (royal tomb: 선릉, 정릉) at the END of a word. Requiring a
# Hangul syllable before and none after keeps 선릉역 (station), 구릉지 (hilly
# land) and a bare "총 3건" (total 3) from firing.
_GRAVE_SUFFIX_RES = (
    re.compile(r"(?<=[가-힣])총(?![가-힣])"),
    re.compile(r"(?<=[가-힣])릉(?![가-힣])"),
)

# Legend codes such as A0010000 / B00100011. Lookarounds instead of `\b`: Python
# treats Hangul syllables as word characters, so `\b` never fired between 묘지
# and A0010000 when a legend cell glued the code to its label.
_CODE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z][0-9]{7,8})(?![A-Za-z0-9])")

# hidden/ legend workbook extensions. Modern NGII legend files ship as .xlsx.
_LEGEND_WORKBOOK_EXTS = (".xls", ".xlsx", ".xlsm")
# Legacy QgsDataProvider.subLayers() field separator.
_SUBLAYER_SEP = "!!::!!"


def _text_has_grave_keyword(text: str) -> bool:
    """Word-aware grave-term test for mixed Korean/English legend text.

    Korean has no reliable word boundaries, so we match specific multi-char
    compounds as substrings while stripping out known false-positive words
    first. English terms use regex word boundaries.
    """
    if not text:
        return False
    s = str(text)
    scrubbed = s
    for bad in _GRAVE_KO_FALSE:
        scrubbed = scrubbed.replace(bad, "")
    for kw in _GRAVE_KW_KO:
        if kw in scrubbed:
            return True
    for rx in _GRAVE_SUFFIX_RES:
        if rx.search(scrubbed):
            return True
    low = s.lower()
    for kw in _GRAVE_KW_EN:
        # `s?` covers plurals ("tombs", "graves"); irregular plurals have their own stems.
        if re.search(r"\b" + re.escape(kw) + r"s?\b", low):
            return True
    for kw in _GRAVE_KW_EN_IRREGULAR:
        if re.search(r"\b" + re.escape(kw) + r"\b", low):
            return True
    return False


def _grave_search_terms() -> List[str]:
    """Every term the grave matcher looks for, in matcher order.

    Reported when avoidance matched nothing, so the user can tell a genuine
    absence of graves from a vocabulary gap.
    """
    terms: List[str] = list(_GRAVE_KW_KO)
    terms.extend(["~총", "~릉"])
    terms.extend(_GRAVE_KW_EN)
    terms.extend(_GRAVE_KW_EN_IRREGULAR)
    return terms


_GRAVE_SEARCH_TERM_COUNT = len(_grave_search_terms())


def _is_legend_workbook_name(name: str) -> bool:
    return str(name or "").lower().endswith(_LEGEND_WORKBOOK_EXTS)


def _sublayer_name(entry: str) -> str:
    """Sheet name from a legacy QgsDataProvider.subLayers() entry.

    The entry is "index!!::!!name!!::!!featureCount!!::!!geometryType[!!::!!geomColumn]",
    so the name is field 1 of an UNLIMITED split. A maxsplit=1 split kept
    "Sheet1!!::!!12!!::!!None" as the name and no sheet ever loaded.
    """
    parts = str(entry or "").split(_SUBLAYER_SEP)
    if len(parts) > 1:
        return parts[1].strip()
    return parts[0].strip()


def _meters_to_crs_units(meters: float, crs, *, ref_y: float = 0.0) -> float:
    """Metres -> units of ``crs`` for growing a feature-request rectangle.

    Geographic CRS: divide by the cos(lat)-scaled metres-per-degree so the
    rectangle over-grows east/west rather than missing features (the same
    rule _build_reference_index applies). Anything else is taken as metres.
    """
    m = max(0.0, float(meters or 0.0))
    try:
        if crs is not None and crs.isGeographic():
            lat = abs(float(ref_y or 0.0))
            cos_lat = max(0.2, math.cos(math.radians(min(85.0, lat))))
            return m / (111320.0 * cos_lat)
    except Exception as _exc:
        log_swallowed("trench_suggestion_dialog._meters_to_crs_units", _exc)
    return m


def _grave_fetch_margin_m(grave_buffer_m: float, trench_length_m: float) -> float:
    """How far outside the AOI bbox grave features must be fetched (metres).

    A candidate only has to satisfy inside_ratio >= the user's minimum, so a
    trench centred inside the AOI can protrude up to half its length past
    the edge; the buffer and 5 m of slack come on top.
    """
    return float(grave_buffer_m or 0.0) + float(trench_length_m or 0.0) * 0.5 + 5.0


def _min_true_distance(ids: Iterable[int], geom_by_id: Dict[int, QgsGeometry], ptg: QgsGeometry, px: float, py: float) -> Optional[float]:
    """Smallest true geometry distance from (px, py) to the features in ``ids``.

    Features are visited in ascending bounding-box distance and the loop stops
    once a box is farther than the best true distance found, which is safe
    because box distance never exceeds true distance. A negative distance
    (QgsGeometry.distance() signals failure that way) is ignored.
    """
    cands: List[Tuple[float, QgsGeometry]] = []
    for fid in ids:
        g = geom_by_id.get(int(fid))
        if g is None:
            continue
        bd = 0.0  # unknown box distance -> never pruned
        try:
            bb = g.boundingBox()
            dx = max(float(bb.xMinimum()) - px, 0.0, px - float(bb.xMaximum()))
            dy = max(float(bb.yMinimum()) - py, 0.0, py - float(bb.yMaximum()))
            bd = math.hypot(dx, dy)
        except Exception as _exc:
            log_swallowed("trench_suggestion_dialog._min_true_distance", _exc)
        cands.append((bd, g))
    cands.sort(key=lambda t: t[0])
    dmin: Optional[float] = None
    for bd, g in cands:
        if dmin is not None and bd >= dmin:
            break
        d: Optional[float] = None
        try:
            d = float(g.distance(ptg))
        except Exception as _exc:
            log_swallowed("trench_suggestion_dialog._min_true_distance", _exc)
        if d is None or (not math.isfinite(d)) or d < 0.0:
            continue
        if dmin is None or d < dmin:
            dmin = d
    return dmin


def _safe_float(v, default=None):
    """Convert to float, returning ``default`` for null, NaN or unconvertible.

    Called per candidate cell in the placement loop, where NoData samples are
    routine - so a null is handled before conversion and never logged. Only a
    non-null value that still fails to convert is worth a [swallowed] line.
    """
    if is_null_value(v):
        return default
    try:
        f = float(v)
        if math.isfinite(f):
            return f
    except Exception as _exc:
        log_swallowed("trench_suggestion_dialog._safe_float", _exc)
    return default


def _unary_union_geom(layer: QgsVectorLayer, *, selected_only: bool) -> Tuple[Optional[QgsGeometry], int, bool]:
    """Union of the layer's (selected) features.

    Returns ``(geometry, feature_count, selection_used)``. When ``selected_only``
    is requested but nothing is selected, every feature is used and
    ``selection_used`` is False so the caller can say so instead of silently
    widening the AOI. ``feature_count`` counts features that contributed a
    non-empty geometry.
    """
    if layer is None or not isinstance(layer, QgsVectorLayer):
        return None, 0, False
    geoms: List[QgsGeometry] = []
    n = 0
    selection_used = False
    try:
        if selected_only and layer.selectedFeatureCount() > 0:
            feats = layer.selectedFeatures()
            selection_used = True
        else:
            feats = layer.getFeatures()
    except Exception as _exc:
        log_swallowed("trench_suggestion_dialog._unary_union_geom", _exc)
        feats = []
    for ft in feats:
        _skip_144 = False
        try:
            g = ft.geometry()
            if g is not None and (not g.isEmpty()):
                geoms.append(g)
                n += 1
        except Exception as _exc:
            log_swallowed("trench_suggestion_dialog._unary_union_geom", _exc)
            log_swallowed("tools/trench_suggestion_dialog.py:148 (_unary_union_geom)", _exc)
            _skip_144 = True
        if _skip_144:
            continue
    if not geoms:
        return None, 0, selection_used
    try:
        return (geoms[0], n, selection_used) if len(geoms) == 1 else (QgsGeometry.unaryUnion(geoms), n, selection_used)
    except Exception as _exc:
        log_swallowed("trench_suggestion_dialog._unary_union_geom", _exc)
        try:
            out = geoms[0]
            for g in geoms[1:]:
                out = out.combine(g)
            return out, n, selection_used
        except Exception as _exc2:
            log_swallowed("trench_suggestion_dialog._unary_union_geom", _exc2)
            return None, 0, selection_used


def _transform_geom(geom: QgsGeometry, src_crs, dst_crs) -> Optional[QgsGeometry]:
    if geom is None or geom.isEmpty():
        return None
    if src_crs == dst_crs:
        return QgsGeometry(geom)
    try:
        g = QgsGeometry(geom)
        g.transform(QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance()))
        return g
    except Exception:
        return None


def _transform_point(pt: QgsPointXY, src_crs, dst_crs) -> Optional[QgsPointXY]:
    if pt is None:
        return None
    if src_crs == dst_crs:
        return QgsPointXY(pt)
    try:
        return QgsPointXY(QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance()).transform(pt))
    except Exception:
        return None


def _bearing_to_unit_vec(bearing_deg: float) -> Tuple[float, float]:
    th = math.radians(90.0 - float(bearing_deg))
    return math.cos(th), math.sin(th)


def _rect_geom_from_center(center: QgsPointXY, *, length_m: float, width_m: float, bearing_deg: float) -> Optional[QgsGeometry]:
    hl = max(0.01, float(length_m)) * 0.5
    hw = max(0.01, float(width_m)) * 0.5
    ux, uy = _bearing_to_unit_vec(bearing_deg)
    vx, vy = -uy, ux
    cx = float(center.x())
    cy = float(center.y())
    p1 = QgsPointXY(cx + ux * hl + vx * hw, cy + uy * hl + vy * hw)
    p2 = QgsPointXY(cx + ux * hl - vx * hw, cy + uy * hl - vy * hw)
    p3 = QgsPointXY(cx - ux * hl - vx * hw, cy - uy * hl - vy * hw)
    p4 = QgsPointXY(cx - ux * hl + vx * hw, cy - uy * hl + vy * hw)
    try:
        return QgsGeometry.fromPolygonXY([[p1, p2, p3, p4, p1]])
    except Exception:
        return None


class TrenchSuggestionDialog(QtWidgets.QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        # Remember the last-used inputs between sessions (tools/dialog_memory.py).
        dialog_memory.attach(self, "trench_suggestion")
        self.iface = iface
        self._grave_codes_cache: Optional[Set[str]] = None
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("트렌치 후보 제안 (Trench Suggestion) - ArchToolkit")
        try:
            self.setWindowIcon(plugin_icon("trench.png", "terrain.png"))
        except Exception as _exc:
            log_swallowed("trench_suggestion_dialog._setup_ui", _exc)

        self.setMinimumWidth(680)
        layout = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel(
            "<b>트렌치 후보 제안 (보조 도구)</b><br>"
            "AOI 내부에서 지형·AHP·주변 유적 맥락을 기준으로 트렌치 배치 후보를 자동 제안합니다.<br>"
            "<b>주의:</b> 본 결과는 조사 설계 보조용 가설이며, 매장문화재 존재를 보장하지 않습니다."
        )
        header.setWordWrap(True)
        header.setStyleSheet("background:#e8f5e9; padding:10px; border:1px solid #c8e6c9; border-radius:4px;")
        layout.addWidget(header)

        grp_in = QtWidgets.QGroupBox("1. 기본 입력")
        form_in = QtWidgets.QFormLayout(grp_in)
        self.cmbAoi = QgsMapLayerComboBox(grp_in)
        try:
            poly_filter = QgsMapLayerProxyModel.Filter.PolygonLayer
        except Exception:
            poly_filter = QgsMapLayerProxyModel.PolygonLayer
        self.cmbAoi.setFilters(poly_filter)
        form_in.addRow("AOI 폴리곤:", self.cmbAoi)

        self.chkAoiSelectedOnly = QtWidgets.QCheckBox("AOI 선택 피처만 사용")
        self.chkAoiSelectedOnly.setChecked(True)
        form_in.addRow("", self.chkAoiSelectedOnly)

        self.cmbDem = QgsMapLayerComboBox(grp_in)
        try:
            ras_filter = QgsMapLayerProxyModel.Filter.RasterLayer
        except Exception:
            ras_filter = QgsMapLayerProxyModel.RasterLayer
        self.cmbDem.setFilters(ras_filter)
        form_in.addRow("DEM:", self.cmbDem)

        self.cmbAhp = QgsMapLayerComboBox(grp_in)
        self.cmbAhp.setFilters(ras_filter)
        # Optional input: default to "no layer" so the AHP raster is only used
        # when the user explicitly picks it (otherwise the DEM would be auto-selected).
        try:
            self.cmbAhp.setAllowEmptyLayer(True)
            self.cmbAhp.setCurrentIndex(0)
        except Exception as _exc:
            log_swallowed("tools/trench_suggestion_dialog.py:274 (_setup_ui)", _exc)
        form_in.addRow("AHP 적합도 래스터(선택):", self.cmbAhp)
        layout.addWidget(grp_in)

        grp_tr = QtWidgets.QGroupBox("2. 트렌치 설정")
        grid_tr = QtWidgets.QGridLayout(grp_tr)

        self.spinWidth = QtWidgets.QDoubleSpinBox()
        self.spinWidth.setRange(0.5, 100.0)
        self.spinWidth.setDecimals(1)
        self.spinWidth.setValue(2.0)
        self.spinWidth.setSuffix(" m")

        self.spinLength = QtWidgets.QDoubleSpinBox()
        self.spinLength.setRange(2.0, 500.0)
        self.spinLength.setDecimals(1)
        self.spinLength.setValue(20.0)
        self.spinLength.setSuffix(" m")

        self.spinCount = QtWidgets.QSpinBox()
        self.spinCount.setRange(1, 300)
        self.spinCount.setValue(12)

        self.spinGrid = QtWidgets.QDoubleSpinBox()
        self.spinGrid.setRange(1.0, 200.0)
        self.spinGrid.setDecimals(1)
        self.spinGrid.setValue(10.0)
        self.spinGrid.setSuffix(" m")

        self.spinMinSpacing = QtWidgets.QDoubleSpinBox()
        self.spinMinSpacing.setRange(0.0, 500.0)
        self.spinMinSpacing.setDecimals(1)
        self.spinMinSpacing.setValue(6.0)
        self.spinMinSpacing.setSuffix(" m")
        self.spinMinSpacing.setToolTip(
            "선택된 트렌치 사이의 최소 '가장자리 간격'(edge-to-edge)입니다. "
            "트렌치 길이가 길수록 실제 중심 간 거리는 자동으로 더 벌어집니다."
        )

        self.spinInsidePct = QtWidgets.QDoubleSpinBox()
        self.spinInsidePct.setRange(10.0, 100.0)
        self.spinInsidePct.setDecimals(0)
        self.spinInsidePct.setValue(95.0)
        self.spinInsidePct.setSuffix(" %")

        self.cmbOrientation = QtWidgets.QComboBox()
        self.cmbOrientation.addItem("등고선 직교 (기본)", "orthogonal")
        self.cmbOrientation.addItem("등고선 평행", "parallel")

        grid_tr.addWidget(QtWidgets.QLabel("폭:"), 0, 0)
        grid_tr.addWidget(self.spinWidth, 0, 1)
        grid_tr.addWidget(QtWidgets.QLabel("길이:"), 0, 2)
        grid_tr.addWidget(self.spinLength, 0, 3)
        grid_tr.addWidget(QtWidgets.QLabel("제안 개수:"), 1, 0)
        grid_tr.addWidget(self.spinCount, 1, 1)
        grid_tr.addWidget(QtWidgets.QLabel("후보 격자 간격:"), 1, 2)
        grid_tr.addWidget(self.spinGrid, 1, 3)
        grid_tr.addWidget(QtWidgets.QLabel("최소 간격:"), 2, 0)
        grid_tr.addWidget(self.spinMinSpacing, 2, 1)
        grid_tr.addWidget(QtWidgets.QLabel("AOI 내부 포함비율 최소:"), 2, 2)
        grid_tr.addWidget(self.spinInsidePct, 2, 3)
        grid_tr.addWidget(QtWidgets.QLabel("방향 모드:"), 3, 0)
        grid_tr.addWidget(self.cmbOrientation, 3, 1, 1, 3)
        layout.addWidget(grp_tr)

        grp_ctx = QtWidgets.QGroupBox("3. 맥락/회피 설정")
        form_ctx = QtWidgets.QFormLayout(grp_ctx)
        self.cmbRefSites = QgsMapLayerComboBox(grp_ctx)
        try:
            vec_filter = QgsMapLayerProxyModel.Filter.VectorLayer
        except Exception:
            vec_filter = QgsMapLayerProxyModel.VectorLayer
        self.cmbRefSites.setFilters(vec_filter)
        try:
            self.cmbRefSites.setAllowEmptyLayer(True)
            self.cmbRefSites.setCurrentIndex(0)
        except Exception as _exc:
            log_swallowed("tools/trench_suggestion_dialog.py:351 (_setup_ui)", _exc)
        form_ctx.addRow("주변 유적 레이어(선택):", self.cmbRefSites)

        self.spinRefRadius = QtWidgets.QDoubleSpinBox()
        self.spinRefRadius.setRange(50.0, 10_000.0)
        self.spinRefRadius.setDecimals(0)
        self.spinRefRadius.setValue(1000.0)
        self.spinRefRadius.setSuffix(" m")
        form_ctx.addRow("유적 근접 점수 반경:", self.spinRefRadius)

        self.chkAvoidGrave = QtWidgets.QCheckBox("무덤/분묘 회피 적용")
        self.chkAvoidGrave.setChecked(True)
        form_ctx.addRow("", self.chkAvoidGrave)

        self.cmbTopo = QgsMapLayerComboBox(grp_ctx)
        self.cmbTopo.setFilters(vec_filter)
        try:
            self.cmbTopo.setAllowEmptyLayer(True)
            self.cmbTopo.setCurrentIndex(0)
        except Exception as _exc:
            log_swallowed("tools/trench_suggestion_dialog.py:371 (_setup_ui)", _exc)
        self.cmbTopo.layerChanged.connect(self._on_topo_layer_changed)
        form_ctx.addRow("수치지형도 벡터(선택):", self.cmbTopo)

        self.cmbTopoCodeField = QtWidgets.QComboBox()
        form_ctx.addRow("코드 필드:", self.cmbTopoCodeField)

        self.spinGraveBuffer = QtWidgets.QDoubleSpinBox()
        self.spinGraveBuffer.setRange(0.0, 100.0)
        self.spinGraveBuffer.setDecimals(1)
        self.spinGraveBuffer.setValue(3.0)
        self.spinGraveBuffer.setSuffix(" m")
        form_ctx.addRow("무덤 회피 버퍼:", self.spinGraveBuffer)

        self.lblLegendStatus = QtWidgets.QLabel("hidden XLS: 미확인")
        self.lblLegendStatus.setStyleSheet("color:#455a64;")
        form_ctx.addRow("범례 코드 상태:", self.lblLegendStatus)
        layout.addWidget(grp_ctx)

        grp_score = QtWidgets.QGroupBox("4. 점수 가중치")
        grid_sc = QtWidgets.QGridLayout(grp_score)
        self.spinWAhp = QtWidgets.QDoubleSpinBox()
        self.spinWAhp.setRange(0.0, 5.0)
        self.spinWAhp.setDecimals(2)
        self.spinWAhp.setValue(0.55)
        self.spinWRef = QtWidgets.QDoubleSpinBox()
        self.spinWRef.setRange(0.0, 5.0)
        self.spinWRef.setDecimals(2)
        self.spinWRef.setValue(0.25)
        self.spinWSlope = QtWidgets.QDoubleSpinBox()
        self.spinWSlope.setRange(0.0, 5.0)
        self.spinWSlope.setDecimals(2)
        self.spinWSlope.setValue(0.20)
        self.spinSlopeMax = QtWidgets.QDoubleSpinBox()
        self.spinSlopeMax.setRange(1.0, 90.0)
        self.spinSlopeMax.setDecimals(1)
        self.spinSlopeMax.setValue(30.0)
        self.spinSlopeMax.setSuffix(" deg")
        self.spinMaxEval = QtWidgets.QSpinBox()
        self.spinMaxEval.setRange(100, 50_000)
        self.spinMaxEval.setValue(8000)
        grid_sc.addWidget(QtWidgets.QLabel("AHP 가중치:"), 0, 0)
        grid_sc.addWidget(self.spinWAhp, 0, 1)
        grid_sc.addWidget(QtWidgets.QLabel("유적근접 가중치:"), 0, 2)
        grid_sc.addWidget(self.spinWRef, 0, 3)
        grid_sc.addWidget(QtWidgets.QLabel("경사 가중치:"), 1, 0)
        grid_sc.addWidget(self.spinWSlope, 1, 1)
        grid_sc.addWidget(QtWidgets.QLabel("최대 허용 경사:"), 1, 2)
        grid_sc.addWidget(self.spinSlopeMax, 1, 3)
        grid_sc.addWidget(QtWidgets.QLabel("최대 후보 평가 수:"), 2, 0)
        grid_sc.addWidget(self.spinMaxEval, 2, 1)
        layout.addWidget(grp_score)

        self.lblBusy = QtWidgets.QLabel("")
        self.lblBusy.setStyleSheet("color:#455a64;")
        layout.addWidget(self.lblBusy)

        row_btn = QtWidgets.QHBoxLayout()
        row_btn.addStretch(1)
        self.btnHelp = QtWidgets.QPushButton("도움말")
        self.btnRun = QtWidgets.QPushButton("후보 생성")
        self.btnClose = QtWidgets.QPushButton("닫기")
        row_btn.addWidget(self.btnHelp)
        row_btn.addWidget(self.btnRun)
        row_btn.addWidget(self.btnClose)
        layout.addLayout(row_btn)

        self.btnHelp.clicked.connect(self._on_help)
        self.btnRun.clicked.connect(self._run)
        self.btnClose.clicked.connect(self.reject)
        self._on_topo_layer_changed()
        self._update_legend_status()

    def _on_help(self):
        html = (
            "<h3>트렌치 후보 제안 도구</h3>"
            "<p>AOI 내부 후보점에 대해 지형 방향(등고선 직교/평행), AHP 적합도, 주변 유적 근접성을 종합해 트렌치 후보를 제안합니다.</p>"
            "<ul>"
            "<li><b>방향 기본값</b>: 등고선 직교</li>"
            "<li><b>평행 옵션</b>: 선형 유구/가마 등 사례 대응</li>"
            "<li><b>무덤 회피</b>: 수치지형도 속성과 hidden 범례(XLS/XLSX) 기반 코드·키워드 회피 "
            f"(검색어 {_GRAVE_SEARCH_TERM_COUNT}종: 무덤·분묘·고분·지석묘·석실묘·토광묘·옹관묘 등, "
            "총/릉 접미 규칙, tomb/grave/dolmen 등)</li>"
            "</ul>"
            "<p><b>주의:</b> 본 결과는 조사 보조용 가설이며, 유구 존재를 보장하지 않습니다. 최종 판단은 현장 조사자의 책임입니다.</p>"
        )
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            show_help_dialog(parent=self, title="트렌치 후보 제안 도움말", html=html, plugin_dir=plugin_dir, tool_id="trench_suggestion")
        except Exception:
            QtWidgets.QMessageBox.information(self, "도움말", "README를 참고하세요.")

    def _set_busy(self, message: str = ""):
        try:
            self.lblBusy.setText(str(message or ""))
            QtWidgets.QApplication.processEvents()
        except Exception as _exc:
            log_swallowed("tools/trench_suggestion_dialog.py:466 (_set_busy)", _exc)

    def _on_topo_layer_changed(self):
        self.cmbTopoCodeField.clear()
        self.cmbTopoCodeField.addItem("(자동 탐지)", "")
        lyr = self.cmbTopo.currentLayer()
        if lyr is None or not isinstance(lyr, QgsVectorLayer):
            return
        try:
            for f in lyr.fields():
                n = str(f.name() or "")
                self.cmbTopoCodeField.addItem(n, n)
        except Exception as _exc:
            log_swallowed("tools/trench_suggestion_dialog.py:479 (_on_topo_layer_changed)", _exc)

    def _hidden_xls_path(self) -> str:
        plugin_dir = os.path.dirname(os.path.dirname(__file__))
        hidden_dir = os.path.join(plugin_dir, "hidden")
        if not os.path.isdir(hidden_dir):
            return ""
        try:
            names = [x for x in os.listdir(hidden_dir) if _is_legend_workbook_name(x)]
        except Exception as _exc:
            log_swallowed("trench_suggestion_dialog._hidden_xls_path", _exc)
            names = []
        if not names:
            return ""
        names.sort()
        return os.path.join(hidden_dir, names[0])

    def _iter_rows_from_xls_pandas(self, xls_path: str) -> Iterable[List[str]]:
        try:
            import pandas as pd  # type: ignore
        except Exception:
            return []
        rows: List[List[str]] = []
        try:
            sheets = pd.read_excel(xls_path, sheet_name=None, dtype=str, engine=None)
        except Exception:
            return []
        for _sheet_name, df in (sheets or {}).items():
            _skip_507 = False
            try:
                for _idx, row in df.fillna("").iterrows():
                    vals = [str(v).strip() for v in row.tolist() if str(v).strip()]
                    if vals:
                        rows.append(vals)
            except Exception as _exc:
                log_swallowed("tools/trench_suggestion_dialog.py:512 (_iter_rows_from_xls_pandas)", _exc)
                _skip_507 = True
            if _skip_507:
                continue
        return rows

    def _legend_sublayers(self, xls_path: str) -> List[QgsVectorLayer]:
        """Every sheet of the legend workbook as a valid vector layer.

        Prefers QgsProviderRegistry.querySublayers() (QGIS >= 3.22), whose
        details carry a ready-made per-sheet URI. Falls back to the legacy
        subLayers() strings parsed by _sublayer_name(), and finally to the
        workbook opened as a single layer.
        """
        layers: List[QgsVectorLayer] = []
        try:
            registry = QgsProviderRegistry.instance()
            query = getattr(registry, "querySublayers", None)
            if callable(query):
                for detail in query(xls_path) or []:
                    uri = ""
                    name = ""
                    provider = "ogr"
                    try:
                        uri = str(detail.uri() or "")
                        name = str(detail.name() or "")
                        provider = str(detail.providerKey() or "ogr")
                    except Exception as _exc:
                        log_swallowed("trench_suggestion_dialog._legend_sublayers", _exc)
                    if not uri:
                        continue
                    lyr = QgsVectorLayer(uri, f"legend_{name or len(layers)}", provider)
                    if lyr.isValid():
                        layers.append(lyr)
        except Exception as _exc:
            log_swallowed("trench_suggestion_dialog._legend_sublayers", _exc)
        if layers:
            return layers

        base = QgsVectorLayer(xls_path, "legend_xls", "ogr")
        if not base.isValid():
            return layers
        try:
            subs = base.dataProvider().subLayers() or []
        except Exception as _exc:
            log_swallowed("trench_suggestion_dialog._legend_sublayers", _exc)
            subs = []
        for entry in subs:
            name = _sublayer_name(entry)
            if not name:
                continue
            lyr = QgsVectorLayer(f"{xls_path}|layername={name}", f"legend_{name}", "ogr")
            if lyr.isValid():
                layers.append(lyr)
        if not layers:
            layers.append(base)
        return layers

    def _iter_rows_from_xls_qgis(self, xls_path: str) -> Iterable[List[str]]:
        out: List[List[str]] = []
        layers = self._legend_sublayers(xls_path)
        if not layers:
            return out

        for lyr in layers:
            try:
                f_names = [str(f.name() or "") for f in lyr.fields()]
            except Exception:
                f_names = []
            for ft in lyr.getFeatures():
                vals: List[str] = []
                for fn in f_names:
                    try:
                        v = ft[fn]
                        s = str(v).strip() if v is not None else ""
                    except Exception:
                        s = ""
                    if s:
                        vals.append(s)
                if vals:
                    out.append(vals)
        return out

    def _extract_grave_codes(self, rows: Iterable[Sequence[str]]) -> Set[str]:
        codes: Set[str] = set()
        for row in rows:
            vals = [str(v).strip() for v in row if str(v).strip()]
            if not vals:
                continue
            row_txt = " ".join(vals)
            if not _text_has_grave_keyword(row_txt):
                continue
            for v in vals:
                for m in _CODE_RE.findall(str(v).upper()):
                    codes.add(str(m).upper())
        return codes

    def _load_grave_codes_from_hidden(self) -> Set[str]:
        if self._grave_codes_cache is not None:
            return set(self._grave_codes_cache)
        xls_path = self._hidden_xls_path()
        if not xls_path:
            self._grave_codes_cache = set()
            return set()

        codes: Set[str] = set()
        rows = self._iter_rows_from_xls_pandas(xls_path)
        if rows:
            codes = self._extract_grave_codes(rows)
        if not codes:
            rows2 = self._iter_rows_from_xls_qgis(xls_path)
            if rows2:
                codes = self._extract_grave_codes(rows2)

        self._grave_codes_cache = set(codes)
        return set(codes)

    def _update_legend_status(self):
        path = self._hidden_xls_path()
        if not path:
            self.lblLegendStatus.setText("hidden XLS 없음 (키워드 회피만 사용)")
            return
        codes = self._load_grave_codes_from_hidden()
        if codes:
            self.lblLegendStatus.setText(f"hidden XLS 로드됨 (무덤 코드 {len(codes)}개)")
        else:
            self.lblLegendStatus.setText("hidden XLS 인식 실패/코드 없음 (키워드 회피만 사용)")

    def _sample_raster_value(self, raster: QgsRasterLayer, pt: QgsPointXY, src_crs) -> Optional[float]:
        if raster is None or not isinstance(raster, QgsRasterLayer) or (not raster.isValid()):
            return None
        p = _transform_point(pt, src_crs, raster.crs())
        if p is None:
            return None
        try:
            res = raster.dataProvider().identify(p, QgsRaster.IdentifyFormatValue)
            if not res.isValid():
                return None
            vals = res.results() or {}
            if not vals:
                return None
            v = vals.get(1)
            if v is None:
                try:
                    v = list(vals.values())[0]
                except Exception:
                    v = None
            return _safe_float(v, default=None)
        except Exception:
            return None

    def _pick_code_field(self, lyr: QgsVectorLayer) -> str:
        sel = str(self.cmbTopoCodeField.currentData() or "").strip()
        if sel:
            try:
                if lyr.fields().indexFromName(sel) >= 0:
                    return sel
            except Exception as _exc:
                log_swallowed("tools/trench_suggestion_dialog.py:635 (_pick_code_field)", _exc)
        cands = (
            "code",
            "CODE",
            "dxf_code",
            "DXF_CODE",
            "표준코드",
            "지형지물코드",
            "class_id",
            "Class_id",
            "Layer",
            "layer",
            "element",
        )
        try:
            names = [str(f.name() or "") for f in lyr.fields()]
        except Exception:
            names = []
        lower_map = {n.lower(): n for n in names}
        for c in cands:
            if c.lower() in lower_map:
                return lower_map[c.lower()]
        return ""

    def _feature_has_grave_hint(self, ft: QgsFeature, *, code_field: str, grave_codes: Set[str]) -> bool:
        code = ""
        if code_field:
            try:
                v = ft[code_field]
                code = str(v).strip().upper() if v is not None else ""
            except Exception:
                code = ""
        if code and (code in grave_codes):
            return True
        txts: List[str] = []
        try:
            for v in ft.attributes():
                if v is None:
                    continue
                s = str(v).strip()
                if s:
                    txts.append(s)
        except Exception as _exc:
            log_swallowed("trench_suggestion_dialog._feature_has_grave_hint", _exc)
        if not txts:
            return False
        return _text_has_grave_keyword(" ".join(txts))

    def _build_reference_index(self, layer: Optional[QgsVectorLayer], *, aoi_geom: QgsGeometry, aoi_crs, radius_m: float = 0.0):
        idx = QgsSpatialIndex()
        geom_by_id: Dict[int, QgsGeometry] = {}
        if layer is None or not isinstance(layer, QgsVectorLayer):
            return idx, geom_by_id
        req = QgsFeatureRequest()
        try:
            g_on_layer = _transform_geom(aoi_geom, aoi_crs, layer.crs())
            if g_on_layer is not None and (not g_on_layer.isEmpty()):
                bb = g_on_layer.boundingBox()
                # Grow the filter by the proximity radius so sites within the
                # radius but outside the AOI bbox still feed ref_score (radius
                # can be up to 10 km — much larger than the AOI).
                grow = float(radius_m or 0.0)
                try:
                    if grow > 0 and layer.crs().isGeographic():
                        # meters -> degrees. Longitude degrees shrink by cos(lat),
                        # so divide by the SMALLER (cos-scaled) meters-per-degree
                        # to OVER-grow rather than miss features east/west.
                        lat = abs(float(bb.center().y()))
                        cos_lat = max(0.2, math.cos(math.radians(min(85.0, lat))))
                        grow = grow / (111320.0 * cos_lat)
                except Exception:
                    grow = float(radius_m or 0.0) / 111320.0
                if grow > 0:
                    bb.grow(grow)
                req.setFilterRect(bb)
        except Exception as _exc:
            log_swallowed("trench_suggestion_dialog._build_reference_index", _exc)
        for ft in layer.getFeatures(req):
            _skip_714 = False
            try:
                g0 = ft.geometry()
            except Exception as _exc:
                log_swallowed("trench_suggestion_dialog._build_reference_index", _exc)
                log_swallowed("tools/trench_suggestion_dialog.py:716 (_build_reference_index)", _exc)
                _skip_714 = True
            if _skip_714:
                continue
            if g0 is None or g0.isEmpty():
                continue
            g = _transform_geom(g0, layer.crs(), aoi_crs)
            if g is None or g.isEmpty():
                continue
            f2 = QgsFeature()
            f2.setId(int(ft.id()))
            f2.setGeometry(g)
            _skip_727 = False
            try:
                idx.addFeature(f2)
                geom_by_id[int(ft.id())] = g
            except Exception as _exc:
                log_swallowed("trench_suggestion_dialog._build_reference_index", _exc)
                log_swallowed("tools/trench_suggestion_dialog.py:730 (_build_reference_index)", _exc)
                _skip_727 = True
            if _skip_727:
                continue
        return idx, geom_by_id

    def _nearest_reference_distance(
        self,
        idx: QgsSpatialIndex,
        geom_by_id: Dict[int, QgsGeometry],
        pt: QgsPointXY,
        *,
        radius_m: float = 0.0,
    ) -> Optional[float]:
        """True distance from ``pt`` to the nearest reference feature (ref_dist_m).

        QgsSpatialIndex.nearestNeighbor ranks by bounding box, so a fixed k=8
        could drop a small site that is genuinely closer than eight large
        polygons whose boxes all contain the point. Every feature whose box
        touches the square of half-width ``radius_m`` around the point is
        measured instead (the reference set is already pre-filtered to the
        AOI bbox + radius, so this is cheap), which makes the value exact
        whenever a site lies within the radius. Beyond the radius, where
        ref_score is 0 anyway, a k=32 nearest-neighbour query is the fallback
        and the value is a best effort.
        """
        if not geom_by_id:
            return None
        ptg = QgsGeometry.fromPointXY(pt)
        px = float(pt.x())
        py = float(pt.y())
        r = max(0.0, float(radius_m or 0.0))
        ids: List[int] = []
        if r > 0.0:
            try:
                ids = list(idx.intersects(QgsRectangle(px - r, py - r, px + r, py + r)) or [])
            except Exception as _exc:
                log_swallowed("trench_suggestion_dialog._nearest_reference_distance", _exc)
                ids = []
        dmin = _min_true_distance(ids, geom_by_id, ptg, px, py)
        if dmin is None or dmin > r:
            try:
                more = list(idx.nearestNeighbor(pt, 32) or [])
            except Exception as _exc:
                log_swallowed("trench_suggestion_dialog._nearest_reference_distance", _exc)
                more = list(geom_by_id.keys())[:32]
            d2 = _min_true_distance(more, geom_by_id, ptg, px, py)
            if d2 is not None and (dmin is None or d2 < dmin):
                dmin = d2
        return dmin

    def _build_grave_avoid_union(
        self,
        *,
        topo_layer: Optional[QgsVectorLayer],
        aoi_geom: QgsGeometry,
        aoi_crs,
        grave_buffer_m: float,
        use_avoid: bool,
        trench_length_m: float = 0.0,
    ) -> Tuple[Optional[QgsGeometry], int]:
        """Return (avoidance_union, matched_feature_count).

        The count is reported to the user so an "avoidance enabled but 0 features
        matched" outcome is stated honestly instead of implying graves were dodged.
        ``trench_length_m`` widens the fetch rectangle so graves a protruding
        trench could reach are loaded (see _grave_fetch_margin_m).
        """
        if (not use_avoid) or topo_layer is None or (not isinstance(topo_layer, QgsVectorLayer)):
            return None, 0
        grave_codes = self._load_grave_codes_from_hidden()
        code_field = self._pick_code_field(topo_layer)
        req = QgsFeatureRequest()
        try:
            g_on_topo = _transform_geom(aoi_geom, aoi_crs, topo_layer.crs())
            if g_on_topo is not None and (not g_on_topo.isEmpty()):
                bb = g_on_topo.boundingBox()
                # The old margin (buffer + 3 m) came from the buffer alone; a 500 m
                # trench at inside_ratio 0.95 reaches 25 m past the AOI edge and
                # graves there were never fetched, counted or avoided.
                margin_m = _grave_fetch_margin_m(grave_buffer_m, trench_length_m)
                bb.grow(max(1e-9, _meters_to_crs_units(margin_m, topo_layer.crs(), ref_y=bb.center().y())))
                req.setFilterRect(bb)
        except Exception as _exc:
            log_swallowed("trench_suggestion_dialog._build_grave_avoid_union", _exc)

        geoms: List[QgsGeometry] = []
        for ft in topo_layer.getFeatures(req):
            if not self._feature_has_grave_hint(ft, code_field=code_field, grave_codes=grave_codes):
                continue
            _skip_789 = False
            try:
                g0 = ft.geometry()
            except Exception as _exc:
                log_swallowed("trench_suggestion_dialog._build_grave_avoid_union", _exc)
                log_swallowed("tools/trench_suggestion_dialog.py:791 (_build_grave_avoid_union)", _exc)
                _skip_789 = True
            if _skip_789:
                continue
            if g0 is None or g0.isEmpty():
                continue
            g = _transform_geom(g0, topo_layer.crs(), aoi_crs)
            if g is None or g.isEmpty():
                continue
            try:
                if float(grave_buffer_m) > 0:
                    gb = g.buffer(float(grave_buffer_m), 8)
                    # buffer() returns a NULL geometry on GEOS failure instead of
                    # raising; appending it poisons the union below.
                    if gb is not None and not gb.isNull() and not gb.isEmpty():
                        g = gb
                    else:
                        log_message("무덤 회피: 버퍼 실패 피처는 원 지오메트리로 대체합니다.", level=Qgis.Warning)
            except Exception as _exc:
                log_swallowed("trench_suggestion_dialog._build_grave_avoid_union", _exc)
            if g is None or g.isNull() or g.isEmpty():
                continue
            geoms.append(g)

        count = len(geoms)
        if not geoms:
            return None, 0
        try:
            union = geoms[0] if count == 1 else QgsGeometry.unaryUnion(geoms)
        except Exception:
            try:
                union = geoms[0]
                for g in geoms[1:]:
                    union = union.combine(g)
            except Exception:
                union = None
        # unaryUnion() reports a GEOS failure as a null geometry, not an
        # exception, and intersects() against a null is always False - so the
        # avoidance silently did nothing while the UI counted N graves avoided.
        if union is None or union.isNull() or union.isEmpty():
            log_message("무덤 회피: 회피 마스크(union) 생성 실패 — 이번 실행에는 회피가 적용되지 않습니다.", level=Qgis.Warning)
            return None, 0
        return union, count

    def _dem_pixel_size(self, dem_layer: QgsRasterLayer) -> float:
        try:
            px = float(dem_layer.rasterUnitsPerPixelX())
            if math.isfinite(px) and px > 0:
                return px
        except Exception as _exc:
            log_swallowed("trench_suggestion_dialog._dem_pixel_size", _exc)
        return 1.0

    def _default_bearing_from_aoi(self, aoi_geom: QgsGeometry) -> float:
        """Long-axis bearing of the AOI (deg, [0,180)) as a flat-terrain fallback.

        On flat ground aspect is meaningless, so trenches align to the AOI's
        principal axis, which gives the best areal coverage.
        """
        try:
            res = aoi_geom.orientedMinimumBoundingBox()
            # QGIS returns (geometry, area, angle, width, height). Per the QGIS
            # implementation (QgsGeometryUtilsBase::lineAngle = -atan2+π/2, i.e.
            # a compass bearing clockwise from NORTH), `angle` is already the
            # bearing of the box's LONG side, and width <= height is guaranteed
            # (the C++ swaps dimensions and adds 90° when needed).
            if res is not None and len(res) >= 5:
                angle = float(res[2])
                width = float(res[3])
                height = float(res[4])
                if width <= height:
                    bearing = angle % 180.0
                else:
                    # Defensive: shouldn't occur with current QGIS, but if the
                    # convention ever flips, the long side is 90° off `angle`.
                    bearing = (angle + 90.0) % 180.0
                if math.isfinite(bearing):
                    return bearing
        except Exception as _exc:
            log_swallowed("trench_suggestion_dialog._default_bearing_from_aoi", _exc)
        return 0.0

    def _footprint_downslope_bearing(
        self,
        *,
        aspect_layer: QgsRasterLayer,
        slope_layer: QgsRasterLayer,
        pt: QgsPointXY,
        src_crs,
        radius_m: float,
    ) -> Tuple[Optional[float], float, Optional[float]]:
        """Slope-weighted circular mean of aspect over the trench footprint.

        Also returns the MAXIMUM slope seen over the same rosette, so the
        slope limit can be applied to the whole footprint rather than the
        single centre cell a 500 m trench was previously judged by.

        A single-cell aspect sample is noisy; averaging aspect across the footprint
        (weighted by slope, so near-flat cells barely contribute) yields a stable
        downslope direction. Returns (downslope_bearing_deg or None, coherence R in
        [0,1]). None bearing / low R signals flat/incoherent terrain -> use fallback.
        """
        r = max(1.0, float(radius_m))
        # Rosette: centre + one ring of 8 points at the footprint radius. Enough to
        # average out single-cell aspect noise without an expensive sample count.
        offsets: List[Tuple[float, float]] = [(0.0, 0.0)]
        for k in range(8):
            a = math.radians(45.0 * k)
            offsets.append((r * math.cos(a), r * math.sin(a)))

        sum_e = 0.0
        sum_n = 0.0
        w_total = 0.0
        slope_max_seen: Optional[float] = None
        cx = float(pt.x())
        cy = float(pt.y())
        for dx, dy in offsets:
            sp = QgsPointXY(cx + dx, cy + dy)
            asp = self._sample_raster_value(aspect_layer, sp, src_crs)
            slp = self._sample_raster_value(slope_layer, sp, src_crs)
            if slp is not None and 0.0 <= float(slp) <= 90.0:
                slope_max_seen = float(slp) if slope_max_seen is None else max(slope_max_seen, float(slp))
            if asp is None or slp is None:
                continue
            if asp < 0.0 or asp > 360.0 or slp < 0.0 or slp > 90.0:
                continue
            w = max(0.0, float(slp))
            if w <= 0.0:
                continue
            ar = math.radians(float(asp))
            # Aspect: degrees clockwise from north. East=sin, North=cos.
            sum_e += w * math.sin(ar)
            sum_n += w * math.cos(ar)
            w_total += w

        if w_total <= 0.0:
            return None, 0.0, slope_max_seen
        mag = math.hypot(sum_e, sum_n)
        coherence = mag / w_total if w_total > 0 else 0.0
        if mag <= 1e-9:
            return None, float(coherence), slope_max_seen
        bearing = math.degrees(math.atan2(sum_e, sum_n)) % 360.0
        return float(bearing), float(coherence), slope_max_seen

    def _clip_dem_to_aoi(
        self,
        *,
        dem_layer: QgsRasterLayer,
        aoi_geom: QgsGeometry,
        aoi_crs,
        buffer_m: float,
        out_path: str,
    ) -> Optional[str]:
        """Clip the DEM to the AOI bounding box + buffer so slope/aspect are
        computed on a small window (faster, fewer edge artifacts). Returns the
        clipped path, or None on failure (caller falls back to the full DEM)."""
        try:
            g = _transform_geom(aoi_geom, aoi_crs, dem_layer.crs())
            if g is None or g.isEmpty():
                return None
            bb = g.boundingBox()
            # buffer_m is meters; convert to DEM CRS units (degrees for a
            # geographic DEM) so the margin isn't 111 km per "meter".
            grow_units = max(1.0, float(buffer_m))
            try:
                if dem_layer.crs().isGeographic():
                    grow_units = float(buffer_m) / 111320.0
            except Exception as _exc:
                log_swallowed("trench_suggestion_dialog._clip_dem_to_aoi", _exc)
            bb.grow(max(1e-9, grow_units))
            # Intersect with the DEM extent to avoid requesting data outside coverage.
            dem_ext = dem_layer.extent()
            xmin = max(bb.xMinimum(), dem_ext.xMinimum())
            ymin = max(bb.yMinimum(), dem_ext.yMinimum())
            xmax = min(bb.xMaximum(), dem_ext.xMaximum())
            ymax = min(bb.yMaximum(), dem_ext.yMaximum())
            if not (xmax > xmin and ymax > ymin):
                return None
            crs_authid = str(dem_layer.crs().authid() or "")
            projwin = f"{xmin},{xmax},{ymin},{ymax}"
            if crs_authid:
                projwin = f"{projwin} [{crs_authid}]"
            processing.run(
                "gdal:cliprasterbyextent",
                {
                    "INPUT": dem_layer.source(),
                    "PROJWIN": projwin,
                    "OVERCRS": False,
                    "NODATA": None,
                    "OPTIONS": "",
                    "DATA_TYPE": 0,
                    "OUTPUT": out_path,
                },
            )
            if os.path.exists(out_path):
                probe = QgsRasterLayer(out_path, "clip_probe")
                if probe.isValid():
                    return out_path
        except Exception:
            return None
        return None

    def _aoi_extent_in_raster_crs(self, aoi_geom: QgsGeometry, *, aoi_crs, raster: QgsRasterLayer):
        if raster is None or not isinstance(raster, QgsRasterLayer):
            return None
        try:
            g = _transform_geom(aoi_geom, aoi_crs, raster.crs())
            if g is None or g.isEmpty():
                return None
            return g.boundingBox()
        except Exception:
            return None

    def _run(self):
        ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)
        self._set_busy("입력 검증 중…")

        aoi_layer = self.cmbAoi.currentLayer()
        if aoi_layer is None or not isinstance(aoi_layer, QgsVectorLayer):
            push_message(self.iface, "오류", "AOI 폴리곤 레이어를 선택하세요.", level=2, duration=7)
            restore_ui_focus(self)
            return
        if aoi_layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            push_message(self.iface, "오류", "AOI는 폴리곤이어야 합니다.", level=2, duration=7)
            restore_ui_focus(self)
            return
        if not is_metric_crs(aoi_layer.crs()):
            push_message(self.iface, "오류", "AOI CRS는 미터 단위 투영 좌표계를 사용하세요.", level=2, duration=8)
            restore_ui_focus(self)
            return

        aoi_selected_only = bool(self.chkAoiSelectedOnly.isChecked())
        aoi_geom, aoi_n, aoi_selection_used = _unary_union_geom(aoi_layer, selected_only=aoi_selected_only)
        if aoi_geom is None or aoi_geom.isEmpty():
            push_message(self.iface, "오류", "AOI 지오메트리를 만들 수 없습니다.", level=2, duration=7)
            return
        if aoi_selected_only and not aoi_selection_used:
            # The checkbox is on by default; a forgotten selection must not
            # silently turn one survey polygon into the whole layer.
            push_message(
                self.iface,
                "경고",
                f"AOI 레이어에 선택된 피처가 없어 전체 {aoi_n}개 피처를 AOI로 사용합니다.",
                level=1,
                duration=8,
            )
            log_message(f"TrenchSuggestion: AOI selected-only requested but no selection; using all {aoi_n} features", level=Qgis.Warning)

        dem_layer = self.cmbDem.currentLayer()
        if dem_layer is None or not isinstance(dem_layer, QgsRasterLayer):
            push_message(self.iface, "오류", "DEM 래스터를 선택하세요.", level=2, duration=7)
            return
        # gdal:slope runs with SCALE=1: a geographic (degree) DEM would yield
        # ~90° slopes everywhere and every candidate would fail the slope filter
        # with a misleading "조건 완화" message. Reject it up front instead.
        try:
            if dem_layer.crs().isGeographic():
                push_message(
                    self.iface,
                    "오류",
                    "DEM이 지리좌표계(위경도)입니다. 미터 단위 투영 좌표계로 재투영한 DEM을 사용하세요.",
                    level=2,
                    duration=9,
                )
                return
        except Exception as _exc:
            log_swallowed("trench_suggestion_dialog._run", _exc)

        ahp_layer = self.cmbAhp.currentLayer()
        if ahp_layer is not None and (not isinstance(ahp_layer, QgsRasterLayer)):
            ahp_layer = None

        ref_layer = self.cmbRefSites.currentLayer()
        if ref_layer is not None and (not isinstance(ref_layer, QgsVectorLayer)):
            ref_layer = None
        topo_layer = self.cmbTopo.currentLayer()
        if topo_layer is not None and (not isinstance(topo_layer, QgsVectorLayer)):
            topo_layer = None

        trench_width = float(self.spinWidth.value())
        trench_length = float(self.spinLength.value())
        want_n = int(self.spinCount.value())
        grid_step = float(self.spinGrid.value())
        min_spacing = float(self.spinMinSpacing.value())
        inside_min_ratio = max(0.1, min(1.0, float(self.spinInsidePct.value()) / 100.0))
        orient_mode = str(self.cmbOrientation.currentData() or "orthogonal")
        use_avoid = bool(self.chkAvoidGrave.isChecked())
        grave_buffer_m = float(self.spinGraveBuffer.value())
        ref_radius_m = float(self.spinRefRadius.value())
        slope_max = float(self.spinSlopeMax.value())
        max_eval = int(self.spinMaxEval.value())

        w_ahp = float(self.spinWAhp.value())
        w_ref = float(self.spinWRef.value())
        w_slope = float(self.spinWSlope.value())
        w_sum = w_ahp + w_ref + w_slope
        if w_sum <= 0:
            push_message(self.iface, "오류", "가중치 합이 0보다 커야 합니다.", level=2, duration=7)
            return

        run_id = new_run_id("trench_suggestion")
        tmp_clip = os.path.join(tempfile.gettempdir(), f"archtoolkit_trench_demclip_{run_id}.tif")
        tmp_aspect = os.path.join(tempfile.gettempdir(), f"archtoolkit_trench_aspect_{run_id}.tif")
        tmp_slope = os.path.join(tempfile.gettempdir(), f"archtoolkit_trench_slope_{run_id}.tif")
        temp_files = [tmp_clip, tmp_aspect, tmp_slope]

        try:
            # Clip the DEM to AOI + margin so slope/aspect run on a small window.
            # Margin covers the footprint-aspect rosette plus a couple of cells for
            # edge continuity. Falls back to the full DEM if clipping fails.
            pixel = self._dem_pixel_size(dem_layer)
            # >= trench_length also covers a trench protruding past the AOI: its
            # centre is inside the AOI, so no footprint sample (rosette radius
            # max(length/2, 2 px)) can lie farther out than length/2 + 2 px.
            clip_buffer = max(float(trench_length), float(grid_step)) + 4.0 * float(pixel)
            self._set_busy("DEM를 AOI 범위로 클립 중…")
            dem_src = self._clip_dem_to_aoi(
                dem_layer=dem_layer,
                aoi_geom=aoi_geom,
                aoi_crs=aoi_layer.crs(),
                buffer_m=clip_buffer,
                out_path=tmp_clip,
            )
            if not dem_src:
                dem_src = dem_layer.source()

            self._set_busy("DEM 파생 레이어(경사/사면방향) 계산 중…")
            processing.run(
                "gdal:aspect",
                {
                    "INPUT": dem_src,
                    "BAND": 1,
                    "TRIG_ANGLE": False,
                    "ZERO_FLAT": True,
                    "COMPUTE_EDGES": True,
                    "ZEVENBERGEN": False,
                    "OUTPUT": tmp_aspect,
                },
            )
            processing.run(
                "gdal:slope",
                {
                    "INPUT": dem_src,
                    "BAND": 1,
                    "SCALE": 1,
                    "AS_PERCENT": False,
                    "COMPUTE_EDGES": True,
                    "ZEVENBERGEN": False,
                    "OUTPUT": tmp_slope,
                },
            )
            aspect_layer = QgsRasterLayer(tmp_aspect, f"tmp_aspect_{run_id}")
            slope_layer = QgsRasterLayer(tmp_slope, f"tmp_slope_{run_id}")
            if (not aspect_layer.isValid()) or (not slope_layer.isValid()):
                raise Exception("aspect/slope raster build failed")

            self._set_busy("주변 유적 인덱스/무덤 회피 마스크 준비 중…")
            ref_idx, ref_geoms = self._build_reference_index(
                ref_layer, aoi_geom=aoi_geom, aoi_crs=aoi_layer.crs(), radius_m=ref_radius_m
            )
            grave_union, grave_count = self._build_grave_avoid_union(
                topo_layer=topo_layer,
                aoi_geom=aoi_geom,
                aoi_crs=aoi_layer.crs(),
                grave_buffer_m=grave_buffer_m,
                use_avoid=use_avoid,
                trench_length_m=trench_length,
            )
            # Honest reporting of what avoidance actually did.
            if use_avoid:
                if topo_layer is None:
                    log_message("무덤 회피: 수치지형도 레이어 미지정 → 회피 미적용", level=Qgis.Warning)
                elif grave_count <= 0:
                    log_message(
                        "무덤 회피: 조건에 맞는 무덤/분묘 피처 0건 → 회피 대상 없음(제외된 후보 없음). "
                        f"검색어 {_GRAVE_SEARCH_TERM_COUNT}종 기준: " + ", ".join(_grave_search_terms()),
                        level=Qgis.Info,
                    )
                else:
                    log_message(f"무덤 회피: 무덤/분묘 피처 {grave_count}건을 회피 대상으로 반영", level=Qgis.Info)

            ahp_min = None
            ahp_max = None
            if ahp_layer is not None and isinstance(ahp_layer, QgsRasterLayer) and ahp_layer.isValid():
                try:
                    ext = self._aoi_extent_in_raster_crs(aoi_geom, aoi_crs=aoi_layer.crs(), raster=ahp_layer)
                    stats = ahp_layer.dataProvider().bandStatistics(
                        1,
                        QgsRasterBandStats.Min | QgsRasterBandStats.Max,
                        ext if ext is not None else ahp_layer.extent(),
                        0,
                    )
                    ahp_min = _safe_float(getattr(stats, "minimumValue", None), default=None)
                    ahp_max = _safe_float(getattr(stats, "maximumValue", None), default=None)
                    if ahp_min is not None and ahp_max is not None and (ahp_max - ahp_min) <= 1e-12:
                        ahp_min = None
                        ahp_max = None
                except Exception:
                    ahp_min = None
                    ahp_max = None

            # Effective weights: drop the weight of any input that was not supplied
            # so it stops acting as a constant offset (previously an absent AHP/ref
            # layer still contributed a flat 0.5 * weight to every candidate).
            ahp_available = bool(
                ahp_layer is not None and isinstance(ahp_layer, QgsRasterLayer) and ahp_layer.isValid()
            )
            # The AHP tool tags its output with units "0-100" when scaled.
            ahp_units_0_100 = False
            if ahp_available:
                try:
                    meta = get_archtoolkit_layer_metadata(ahp_layer) or {}
                    ahp_units_0_100 = str(meta.get("units") or "") == "0-100"
                except Exception:
                    ahp_units_0_100 = False
            ref_available = bool(ref_geoms)
            we_ahp = w_ahp if ahp_available else 0.0
            we_ref = w_ref if ref_available else 0.0
            we_slope = w_slope
            if (we_ahp + we_ref + we_slope) <= 0:
                we_slope = 1.0
            excluded = []
            if not ahp_available and w_ahp > 0:
                excluded.append("AHP")
            if not ref_available and w_ref > 0:
                excluded.append("유적근접")
            if excluded:
                log_message(
                    "입력 미지정으로 가중치에서 제외 후 재정규화: " + ", ".join(excluded),
                    level=Qgis.Info,
                )

            default_bearing = self._default_bearing_from_aoi(aoi_geom)
            flat_slope_thresh = 1.0  # deg; below this, aspect direction is meaningless
            foot_radius = max(float(trench_length) * 0.5, float(pixel) * 2.0)

            # Coarsen the candidate grid so the AOI *interior* fits within the eval
            # budget. This replaces the old scan that stopped after max_eval cells of
            # the bounding box - which silently truncated coverage to one corner.
            bbox = aoi_geom.boundingBox()
            bb_w = max(1e-6, float(bbox.width()))
            bb_h = max(1e-6, float(bbox.height()))
            try:
                aoi_area = float(aoi_geom.area())
            except Exception:
                aoi_area = bb_w * bb_h
            frac = min(1.0, max(1e-3, aoi_area / max(1e-9, bb_w * bb_h)))

            def _grid_counts(step):
                nx = int(bb_w / step) + 1
                ny = int(bb_h / step) + 1
                bpts = nx * ny
                return bpts * frac, bpts

            orig_step = grid_step
            interior_est, bbox_points = _grid_counts(grid_step)
            if interior_est > max_eval:
                grid_step = grid_step * math.sqrt(interior_est / float(max_eval))
                interior_est, bbox_points = _grid_counts(grid_step)
            BBOX_CEIL = 600_000
            if bbox_points > BBOX_CEIL:
                grid_step = grid_step * math.sqrt(bbox_points / float(BBOX_CEIL))
                interior_est, bbox_points = _grid_counts(grid_step)
            if grid_step > orig_step * 1.001:
                log_message(
                    f"AOI가 넓어 후보 격자를 {orig_step:.1f}m→{grid_step:.1f}m로 확대하여 "
                    "AOI 전체를 잘림 없이 커버합니다.",
                    level=Qgis.Info,
                )
            hard_cap = int(max(bbox_points * 2, max_eval * 4))

            x0 = float(bbox.xMinimum()) + grid_step * 0.5
            y0 = float(bbox.yMinimum()) + grid_step * 0.5
            xmax = float(bbox.xMaximum())
            ymax = float(bbox.yMaximum())

            candidates = []
            scanned = 0
            kept = 0
            iters = 0
            truncated = False

            # Prepared geometry engine: containment over hundreds of thousands
            # of grid points is ~10-100x faster than QgsGeometry.contains, and
            # the loop stays responsive via periodic processEvents.
            aoi_engine = None
            try:
                aoi_engine = QgsGeometry.createGeometryEngine(aoi_geom.constGet())
                aoi_engine.prepareGeometry()
            except Exception:
                aoi_engine = None

            def _pt_in_aoi(pt_geom0):
                if aoi_engine is not None:
                    try:
                        return bool(aoi_engine.contains(pt_geom0.constGet()))
                    except Exception as _exc:
                        log_swallowed("tools/trench_suggestion_dialog.py:1248 (_pt_in_aoi)", _exc)
                return bool(aoi_geom.contains(pt_geom0))

            x = x0
            while x <= xmax:
                if truncated:
                    break
                y = y0
                while y <= ymax:
                    iters += 1
                    if iters > hard_cap:
                        truncated = True
                        break
                    if iters % 5000 == 0:
                        self._set_busy(f"후보 스캔 중… ({kept}개 확보)")
                    pt = QgsPointXY(x, y)
                    pt_geom = QgsGeometry.fromPointXY(pt)
                    if not _pt_in_aoi(pt_geom):
                        y += grid_step
                        continue

                    scanned += 1
                    slope = self._sample_raster_value(slope_layer, pt, aoi_layer.crs())
                    if slope is None or slope < 0.0 or slope > 90.0:
                        y += grid_step
                        continue
                    if slope > slope_max:
                        y += grid_step
                        continue

                    # Stable orientation from footprint-averaged aspect, with a
                    # flat-terrain fallback to the AOI long axis.
                    asp_bear, coherence, foot_slope_max = self._footprint_downslope_bearing(
                        aspect_layer=aspect_layer,
                        slope_layer=slope_layer,
                        pt=pt,
                        src_crs=aoi_layer.crs(),
                        radius_m=foot_radius,
                    )
                    # The limit applies to the whole footprint, not just the centre
                    # cell: a long trench can cross ground far steeper than its middle.
                    if foot_slope_max is not None and foot_slope_max > slope_max:
                        y += grid_step
                        continue
                    is_flat = (asp_bear is None) or (coherence < 0.25) or (slope < flat_slope_thresh)
                    if is_flat:
                        bearing = float(default_bearing) % 180.0
                    elif orient_mode == "parallel":
                        bearing = (float(asp_bear) + 90.0) % 180.0
                    else:
                        bearing = float(asp_bear) % 180.0

                    trench_geom = _rect_geom_from_center(
                        pt, length_m=trench_length, width_m=trench_width, bearing_deg=bearing
                    )
                    if trench_geom is None or trench_geom.isEmpty():
                        y += grid_step
                        continue

                    try:
                        g_in = trench_geom.intersection(aoi_geom)
                        a_in = max(0.0, float(g_in.area())) if g_in is not None and (not g_in.isEmpty()) else 0.0
                        a_all = max(1e-9, float(trench_geom.area()))
                        inside_ratio = a_in / a_all
                    except Exception:
                        inside_ratio = 0.0
                    if inside_ratio < inside_min_ratio:
                        y += grid_step
                        continue

                    if grave_union is not None:
                        try:
                            if trench_geom.intersects(grave_union):
                                y += grid_step
                                continue
                        except Exception as _exc:
                            log_swallowed("trench_suggestion_dialog._run", _exc)

                    ahp_val = self._sample_raster_value(ahp_layer, pt, aoi_layer.crs()) if ahp_available else None
                    if ahp_val is not None and ahp_min is not None and ahp_max is not None and ahp_max > ahp_min:
                        ahp_score = max(0.0, min(1.0, (ahp_val - ahp_min) / (ahp_max - ahp_min)))
                    elif ahp_val is not None:
                        # Stats fallback (constant raster / stats failure): honour
                        # the AHP tool's own 0-100 output option before clamping,
                        # else every cell of a 0-100 raster clamps to 1.0.
                        v0 = float(ahp_val) / 100.0 if ahp_units_0_100 else float(ahp_val)
                        ahp_score = max(0.0, min(1.0, v0))
                    else:
                        ahp_score = 0.0

                    if ref_available:
                        ref_dist = self._nearest_reference_distance(ref_idx, ref_geoms, pt, radius_m=ref_radius_m)
                        ref_score = 0.0 if ref_dist is None else max(
                            0.0, min(1.0, 1.0 - (float(ref_dist) / max(1.0, ref_radius_m)))
                        )
                    else:
                        ref_dist = None
                        ref_score = 0.0

                    slope_score = max(0.0, min(1.0, 1.0 - (float(slope) / max(1.0, slope_max))))

                    # Per-cell renormalization: skip the AHP term where this cell is
                    # NoData so a valid cell is never penalized by a missing value.
                    cw_ahp = we_ahp if ahp_val is not None else 0.0
                    cw_ref = we_ref
                    cw_slope = we_slope
                    cw_sum = cw_ahp + cw_ref + cw_slope
                    if cw_sum <= 0:
                        cw_slope = 1.0
                        cw_sum = 1.0
                    total = (cw_ahp * ahp_score + cw_ref * ref_score + cw_slope * slope_score) / cw_sum

                    candidates.append(
                        {
                            "point": pt,
                            "geom": trench_geom,
                            "bearing_deg": float(bearing),
                            "mode": ("flat" if is_flat else orient_mode),
                            "inside_ratio": float(inside_ratio),
                            "slope_deg": float(slope),
                            "slope_max_deg": foot_slope_max,
                            "ahp_val": ahp_val,
                            "ahp_score": float(ahp_score),
                            "ref_dist_m": ref_dist,
                            "ref_score": float(ref_score),
                            "score": float(total),
                        }
                    )
                    kept += 1
                    y += grid_step
                x += grid_step

            if truncated:
                log_message(
                    f"안전 상한({hard_cap} 반복)에 도달하여 스캔을 종료했습니다. "
                    "격자 간격을 넓히거나 AOI를 줄이면 전체를 커버할 수 있습니다.",
                    level=Qgis.Warning,
                )

            if not candidates:
                push_message(
                    self.iface,
                    "정보",
                    "조건을 만족하는 트렌치 후보가 없습니다. 간격/경사/내부비율 조건을 완화해보세요.",
                    level=1,
                    duration=8,
                )
                return

            self._set_busy("커버리지 우선 후보 선별 중…")
            # Coverage-first selection: partition the AOI into ~want_n cells and pick
            # in round-robin (best per cell each pass) so trenches spread across the
            # AOI instead of clustering in the single highest-scoring corner.
            cov_cell = max(float(grid_step), math.sqrt(max(1.0, aoi_area) / max(1, want_n)))
            buckets: Dict[Tuple[int, int], List[dict]] = {}
            for cand in candidates:
                p = cand.get("point")
                key = (int((float(p.x()) - x0) // cov_cell), int((float(p.y()) - y0) // cov_cell))
                buckets.setdefault(key, []).append(cand)
            for b in buckets.values():
                b.sort(key=lambda d: float(d.get("score", 0.0)), reverse=True)
            bucket_order = sorted(buckets.values(), key=lambda b: float(b[0].get("score", 0.0)), reverse=True)

            selected: List[dict] = []
            selected_geoms: List[QgsGeometry] = []

            def _conflicts(g: QgsGeometry) -> bool:
                for sg in selected_geoms:
                    _skip_1411 = False
                    try:
                        if g.intersects(sg):
                            return True
                        if min_spacing > 0 and float(g.distance(sg)) < min_spacing:
                            return True
                    except Exception as _exc:
                        log_swallowed("trench_suggestion_dialog._conflicts", _exc)
                        log_swallowed("tools/trench_suggestion_dialog.py:1416 (_conflicts)", _exc)
                        _skip_1411 = True
                    if _skip_1411:
                        continue
                return False

            ptrs = [0] * len(bucket_order)
            progress = True
            while len(selected) < want_n and progress:
                progress = False
                for bi, b in enumerate(bucket_order):
                    if len(selected) >= want_n:
                        break
                    j = ptrs[bi]
                    while j < len(b):
                        cand = b[j]
                        g = cand.get("geom")
                        j += 1
                        if g is None or _conflicts(g):
                            continue
                        selected.append(cand)
                        selected_geoms.append(g)
                        progress = True
                        break
                    ptrs[bi] = j

            if not selected:
                push_message(self.iface, "정보", "중복/간격 필터 후 남은 후보가 없습니다.", level=1, duration=6)
                return

            self._set_busy("결과 레이어 생성 중…")
            crs_authid = aoi_layer.crs().authid()
            trench_layer = QgsVectorLayer(f"Polygon?crs={crs_authid}", f"Trench_Suggestions_{run_id}", "memory")
            center_layer = QgsVectorLayer(f"Point?crs={crs_authid}", f"Trench_Centers_{run_id}", "memory")

            t_pr = trench_layer.dataProvider()
            c_pr = center_layer.dataProvider()
            fields = [
                QgsField("rank", QVariant.Int),
                QgsField("pick_order", QVariant.Int),
                QgsField("score", QVariant.Double),
                QgsField("mode", QVariant.String),
                QgsField("bearing_deg", QVariant.Double),
                QgsField("inside_pct", QVariant.Double),
                QgsField("slope_deg", QVariant.Double),
                QgsField("slope_max_deg", QVariant.Double),
                QgsField("ahp_val", QVariant.Double),
                QgsField("ahp_score", QVariant.Double),
                QgsField("ref_dist_m", QVariant.Double),
                QgsField("ref_score", QVariant.Double),
            ]
            t_pr.addAttributes(fields)
            c_pr.addAttributes(fields)
            trench_layer.updateFields()
            center_layer.updateFields()

            trench_feats: List[QgsFeature] = []
            center_feats: List[QgsFeature] = []
            # `rank` follows score (1 = best) so sorting by rank and by score agree;
            # `pick_order` is the coverage round-robin sequence the trenches were
            # chosen in, which is not a score order.
            score_rank: Dict[int, int] = {}
            for r0, d0 in enumerate(sorted(selected, key=lambda d: float(d.get("score") or 0.0), reverse=True), start=1):
                score_rank[id(d0)] = int(r0)
            for i, d in enumerate(selected, start=1):
                vals = [
                    int(score_rank.get(id(d), i)),
                    int(i),
                    float(d.get("score") or 0.0),
                    str(d.get("mode") or ""),
                    float(d.get("bearing_deg") or 0.0),
                    float(d.get("inside_ratio") or 0.0) * 100.0,
                    float(d.get("slope_deg") or 0.0),
                    _safe_float(d.get("slope_max_deg"), default=None),
                    _safe_float(d.get("ahp_val"), default=None),
                    float(d.get("ahp_score") or 0.0),
                    _safe_float(d.get("ref_dist_m"), default=None),
                    float(d.get("ref_score") or 0.0),
                ]

                f_poly = QgsFeature(trench_layer.fields())
                f_poly.setGeometry(d.get("geom"))
                for idx0, v in enumerate(vals):
                    f_poly[idx0] = v
                trench_feats.append(f_poly)

                f_pt = QgsFeature(center_layer.fields())
                f_pt.setGeometry(QgsGeometry.fromPointXY(d.get("point")))
                for idx0, v in enumerate(vals):
                    f_pt[idx0] = v
                center_feats.append(f_pt)

            t_pr.addFeatures(trench_feats)
            c_pr.addFeatures(center_feats)
            trench_layer.updateExtents()
            center_layer.updateExtents()
            try:
                t_sym = QgsFillSymbol.createSimple(
                    {"color": "255,99,71,40", "outline_color": "200,30,0,220", "outline_width": "0.6"}
                )
                trench_layer.setRenderer(QgsSingleSymbolRenderer(t_sym))
            except Exception as _exc:
                log_swallowed("tools/trench_suggestion_dialog.py:1506 (_run)", _exc)
            try:
                c_sym = QgsMarkerSymbol.createSimple({"name": "circle", "size": "2.0", "color": "40,120,220,220"})
                center_layer.setRenderer(QgsSingleSymbolRenderer(c_sym))
            except Exception as _exc:
                log_swallowed("tools/trench_suggestion_dialog.py:1511 (_run)", _exc)

            set_archtoolkit_layer_metadata(
                trench_layer,
                tool_id="trench_suggestion",
                run_id=run_id,
                kind="trench_polygon",
                units="m",
                params={
                    "width_m": trench_width,
                    "length_m": trench_length,
                    "count_requested": want_n,
                    "count_selected": len(selected),
                    "grid_step_m": grid_step,
                    "grid_step_requested_m": orig_step,
                    "min_spacing_m": min_spacing,
                    "min_spacing_semantics": "edge_to_edge",
                    "inside_min_ratio": inside_min_ratio,
                    "orientation_mode": orient_mode,
                    "grave_avoid": bool(use_avoid),
                    "grave_matched_features": int(grave_count),
                    "grave_buffer_m": grave_buffer_m,
                    "grave_fetch_margin_m": float(_grave_fetch_margin_m(grave_buffer_m, trench_length)),
                    "grave_keyword_terms": int(_GRAVE_SEARCH_TERM_COUNT),
                    "ref_radius_m": ref_radius_m,
                    # Exact whenever a site lies within ref_radius_m; beyond that a
                    # k=32 bbox-ranked nearest-neighbour best effort (score is 0 there).
                    "ref_dist_method": "exact_within_ref_radius_else_k32_bbox_nn",
                    "max_slope_deg": slope_max,
                    "slope_test": "footprint_max_and_centre",
                    "selection_strategy": "coverage_round_robin",
                    "coverage_cell_m": float(cov_cell),
                    "rank_field": "score_desc",
                    "pick_order_field": "coverage_round_robin",
                    # ahp_score is a min-max stretch over the AOI bounding box, not the
                    # polygon and not the raster's own scale - recorded so a reader can
                    # tell why the same raster scores differently in another AOI.
                    "ahp_norm": {"method": "minmax", "extent": "aoi_bbox", "min": ahp_min, "max": ahp_max},
                    "weights_requested": {"ahp": w_ahp, "ref": w_ref, "slope": w_slope},
                    "weights_effective": {"ahp": we_ahp, "ref": we_ref, "slope": we_slope},
                    "ahp_used": bool(ahp_available),
                    "ref_used": bool(ref_available),
                    "aoi_features": int(aoi_n),
                    "aoi_selected_only_requested": bool(aoi_selected_only),
                    "aoi_selection_used": bool(aoi_selection_used),
                    "candidates_scanned": int(scanned),
                    "candidates_kept": int(kept),
                    "scan_truncated": bool(truncated),
                    "hidden_xls_loaded": bool(len(self._load_grave_codes_from_hidden()) > 0),
                },
            )
            set_archtoolkit_layer_metadata(
                center_layer,
                tool_id="trench_suggestion",
                run_id=run_id,
                kind="trench_center",
                units="m",
                params={"paired_polygon_layer": trench_layer.name()},
            )

            root = QgsProject.instance().layerTreeRoot()
            parent_name = "ArchToolkit - Trench Suggestion"
            grp = root.findGroup(parent_name)
            if grp is None:
                grp = root.insertGroup(0, parent_name)
            run_grp = grp.insertGroup(0, f"TrenchSuggestion_{run_id}")
            QgsProject.instance().addMapLayer(trench_layer, False)
            QgsProject.instance().addMapLayer(center_layer, False)
            run_grp.insertLayer(0, trench_layer)
            run_grp.insertLayer(1, center_layer)

            if use_avoid:
                if topo_layer is None:
                    avoid_note = " (무덤 회피: 지형도 미지정으로 미적용)"
                elif grave_count <= 0:
                    avoid_note = f" (무덤 회피: 대상 0건 - 검색어 {_GRAVE_SEARCH_TERM_COUNT}종 기준)"
                else:
                    avoid_note = f" (무덤 회피: {grave_count}건 반영)"
            else:
                avoid_note = ""
            shortfall = ""
            if len(selected) < want_n:
                shortfall = f" 요청 {want_n}개 중 {len(selected)}개만 조건을 만족했습니다."
            push_message(
                self.iface,
                "완료",
                (
                    f"트렌치 후보 {len(selected)}개를 생성했습니다.{shortfall}{avoid_note} "
                    "선별은 AOI 전체에 분산하는 커버리지 우선 방식이며 rank=점수순, pick_order=선별순입니다. "
                    "결과는 조사 보조용 제안이며, 최종 판단은 현장 조사자가 수행해야 합니다."
                ),
                level=0,
                duration=8,
            )
            log_message(
                f"TrenchSuggestion done: selected={len(selected)} scanned={scanned} kept={kept} "
                f"grave_matched={grave_count} truncated={truncated} run_id={run_id}",
                level=Qgis.Info,
            )
            self.accept()
        except Exception as e:
            log_exception("Trench suggestion error", e)
            push_message(self.iface, "오류", f"트렌치 후보 생성 실패: {e}", level=2, duration=10)
            restore_ui_focus(self)
        finally:
            cleanup_files(temp_files)
            self._set_busy("")
