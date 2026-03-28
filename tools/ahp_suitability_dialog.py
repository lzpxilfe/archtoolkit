# -*- coding: utf-8 -*-
"""
AHP suitability (multi-criteria) tool for ArchToolkit.

Goal
- Combine existing environmental rasters into a single suitability raster using
  AHP (pairwise comparison) weights.

Design notes
- Best-effort and stable: never crash QGIS due to UI/processing errors.
- Uses GDAL processing (`gdal:rastercalculator`, `gdal:warpreproject`) which is
  available in QGIS by default.
"""

from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

import processing
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsColorRampShader,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
    QgsRasterBandStats,
    QgsRasterLayer,
    QgsRasterShader,
    QgsRectangle,
    QgsSingleBandPseudoColorRenderer,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox

from .config import get_output_group_name
from .live_log_dialog import ensure_live_log_dialog
from .help_dialog import show_help_dialog
from .i18n import apply_language, is_english_ui, tr
from .ui_helpers import create_hint_label, set_plugin_window_icon
from .utils import (
    get_archtoolkit_layer_metadata,
    log_exception,
    new_run_id,
    push_message,
    restore_ui_focus,
    set_archtoolkit_layer_metadata,
)


_RI_TABLE = {
    1: 0.00,
    2: 0.00,
    3: 0.58,
    4: 0.90,
    5: 1.12,
    6: 1.24,
    7: 1.32,
    8: 1.41,
    9: 1.45,
    10: 1.49,
}


_SCALE_OPTIONS: List[Tuple[str, float]] = [
    ("1/9", 1.0 / 9.0),
    ("1/8", 1.0 / 8.0),
    ("1/7", 1.0 / 7.0),
    ("1/6", 1.0 / 6.0),
    ("1/5", 1.0 / 5.0),
    ("1/4", 1.0 / 4.0),
    ("1/3", 1.0 / 3.0),
    ("1/2", 1.0 / 2.0),
    ("1", 1.0),
    ("2", 2.0),
    ("3", 3.0),
    ("4", 4.0),
    ("5", 5.0),
    ("6", 6.0),
    ("7", 7.0),
    ("8", 8.0),
    ("9", 9.0),
]

_GUIDE_IMPORTANCE_OPTIONS: List[Tuple[str, int]] = [
    ("1 | 매우 낮음", 1),
    ("2 | 낮음", 2),
    ("3 | 보통", 3),
    ("4 | 높음", 4),
    ("5 | 매우 높음", 5),
]

_GUIDE_DIFF_TO_SAATY = {
    0: 1.0,
    1: 3.0,
    2: 5.0,
    3: 7.0,
    4: 9.0,
}


def _guide_importance_options() -> List[Tuple[str, int]]:
    if is_english_ui():
        return [
            ("1 | Very low", 1),
            ("2 | Low", 2),
            ("3 | Medium", 3),
            ("4 | High", 4),
            ("5 | Very high", 5),
        ]
    return list(_GUIDE_IMPORTANCE_OPTIONS)


def _fmt_float(v: Any, *, digits: int = 4) -> str:
    try:
        if v is None:
            return "-"
        x = float(v)
        if not math.isfinite(x):
            return "-"
        return f"{x:.{int(digits)}f}"
    except Exception:
        return str(v)


def _aoi_extent_in_crs(aoi_layer: QgsVectorLayer, *, selected_only: bool, dst_crs) -> Optional[QgsRectangle]:
    if aoi_layer is None:
        return None
    try:
        if aoi_layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            return None
    except Exception:
        return None

    geom = None
    feats = aoi_layer.selectedFeatures() if selected_only and aoi_layer.selectedFeatureCount() > 0 else aoi_layer.getFeatures()
    for f in feats:
        try:
            g = f.geometry()
        except Exception:
            continue
        if not g or g.isEmpty():
            continue
        if geom is None:
            geom = g
        else:
            try:
                geom = geom.combine(g)
            except Exception:
                pass

    if geom is None or geom.isEmpty():
        return None

    try:
        if aoi_layer.crs() != dst_crs:
            ct = QgsCoordinateTransform(aoi_layer.crs(), dst_crs, QgsProject.instance())
            g2 = type(geom)(geom)  # copy
            g2.transform(ct)
            geom = g2
    except Exception:
        return None

    try:
        return geom.boundingBox()
    except Exception:
        return None


@dataclass
class _Criterion:
    layer_id: str
    direction: str  # "benefit", "cost", "target", "range", "reclass"
    min_v: Optional[float] = None
    max_v: Optional[float] = None
    weight: Optional[float] = None
    target_v: Optional[float] = None
    prefer_min: Optional[float] = None
    prefer_max: Optional[float] = None
    score_ranges: Optional[List[Dict[str, float]]] = None


def _ahp_weights_from_matrix(mat: "np.ndarray") -> Tuple[List[float], float, float]:
    """Return (weights, lambda_max, CR)."""
    n = int(mat.shape[0])
    if n <= 0:
        return [], float("nan"), float("nan")
    if n == 1:
        return [1.0], 1.0, 0.0
    if np is None:
        return [1.0 / float(n)] * n, float("nan"), float("nan")

    try:
        vals, vecs = np.linalg.eig(mat)
        idx = int(np.argmax(np.real(vals)))
        lam = float(np.real(vals[idx]))
        v = np.real(vecs[:, idx])
        v = np.abs(v)
        if float(np.sum(v)) <= 0:
            w = np.ones((n,), dtype=float) / float(n)
        else:
            w = v / float(np.sum(v))
        w = [float(x) for x in w.tolist()]
    except Exception:
        w = [1.0 / float(n)] * n
        lam = float("nan")

    cr = 0.0
    try:
        if n <= 2:
            cr = 0.0
        else:
            ci = (float(lam) - float(n)) / float(n - 1)
            ri = float(_RI_TABLE.get(n, 0.0))
            cr = float(ci / ri) if ri > 0 else 0.0
    except Exception:
        cr = float("nan")
    return w, float(lam), float(cr)


def _describe_consistency(cr: Optional[float]) -> str:
    try:
        value = float(cr)
    except Exception:
        return tr("가중치 일관성을 아직 판단할 수 없습니다. 기준을 추가하고 쌍대비교를 입력하세요.")

    if not math.isfinite(value):
        return tr("가중치 일관성을 수치로 계산하지 못했습니다. NumPy 또는 입력 상태를 확인하세요.")
    if value <= 0.10:
        return tr("일관성 양호: 현재 쌍대비교는 일반 권장 기준(CR ≤ 0.10) 안에 있습니다.")
    if value <= 0.20:
        return tr("일관성 주의: 몇몇 기준의 상대 중요도를 다시 보면 더 설득력 있는 결과가 됩니다.")
    return tr("일관성 낮음: 현재 비교는 서로 충돌할 가능성이 큽니다. 중요도 판단을 다시 맞춰보세요.")


def _criterion_mode_label(mode: str) -> str:
    key = str(mode or "benefit").strip()
    return {
        "benefit": tr("Benefit(값↑)"),
        "cost": tr("Cost(값↓)"),
        "target": tr("목표값 최적"),
        "range": tr("선호구간 최적"),
        "reclass": tr("구간 점수표"),
    }.get(key, key or tr("Benefit(값↑)"))


def _criterion_setting_summary(crit: _Criterion) -> str:
    mode = str(getattr(crit, "direction", "benefit") or "benefit")
    if mode == "target":
        return f"{tr('목표=')}{_fmt_float(getattr(crit, 'target_v', None), digits=3)}"
    if mode == "range":
        return (
            f"{tr('선호=')}{_fmt_float(getattr(crit, 'prefer_min', None), digits=3)}"
            f" ~ {_fmt_float(getattr(crit, 'prefer_max', None), digits=3)}"
        )
    if mode == "reclass":
        rows = getattr(crit, "score_ranges", None) or []
        return f"{tr('구간')} {len(rows)} {tr('개')}"
    return "-"


def _sanitize_pair_values(
    pairs: Optional[Dict[Tuple[str, str], float]],
    valid_ids: List[str],
) -> Dict[Tuple[str, str], float]:
    valid = {str(item or "") for item in (valid_ids or []) if str(item or "")}
    out: Dict[Tuple[str, str], float] = {}
    for key, value in dict(pairs or {}).items():
        try:
            left = str(key[0] or "").strip()
            right = str(key[1] or "").strip()
            value_f = float(value)
        except Exception:
            continue
        if (not left) or (not right) or left == right:
            continue
        if left not in valid or right not in valid:
            continue
        if value_f <= 0 or (not math.isfinite(value_f)):
            continue
        out[(left, right)] = float(value_f)
    return out


def _weights_from_pair_values(
    row_ids: List[str],
    pairs: Optional[Dict[Tuple[str, str], float]] = None,
) -> Tuple[Dict[str, float], float, float]:
    ids = [str(item or "") for item in (row_ids or []) if str(item or "")]
    n = int(len(ids))
    if n <= 0:
        return {}, float("nan"), float("nan")
    if n == 1:
        return {ids[0]: 1.0}, 1.0, 0.0
    if np is None:
        w = 1.0 / float(n)
        return {row_id: w for row_id in ids}, float("nan"), float("nan")

    mat = np.ones((n, n), dtype=float)
    pairs0 = _sanitize_pair_values(dict(pairs or {}), ids)
    index_map = {row_id: idx for idx, row_id in enumerate(ids)}
    for (left, right), value in pairs0.items():
        try:
            i = int(index_map[left])
            j = int(index_map[right])
            v = float(value)
            if i == j or v <= 0 or (not math.isfinite(v)):
                continue
            mat[i, j] = v
            mat[j, i] = 1.0 / v
        except Exception:
            continue
    weights, lam, cr = _ahp_weights_from_matrix(mat)
    out: Dict[str, float] = {}
    for idx, row_id in enumerate(ids):
        try:
            out[row_id] = float(weights[idx])
        except Exception:
            out[row_id] = 1.0 / float(n)
    return out, float(lam), float(cr)


def _pairwise_from_weight_values(
    row_ids: List[str],
    weights: Optional[Dict[str, float]],
) -> Dict[Tuple[str, str], float]:
    ids = [str(item or "") for item in (row_ids or []) if str(item or "")]
    weight_map = dict(weights or {})
    out: Dict[Tuple[str, str], float] = {}
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            left = ids[i]
            right = ids[j]
            try:
                wl = float(weight_map.get(left))
                wr = float(weight_map.get(right))
                if wl <= 0 or wr <= 0 or (not math.isfinite(wl)) or (not math.isfinite(wr)):
                    raise ValueError
                out[(left, right)] = float(wl / wr)
            except Exception:
                out[(left, right)] = 1.0
    return out


def _compute_hierarchy_summary(
    *,
    criteria_rows: List[Tuple[str, str]],
    criterion_groups: Dict[str, str],
    group_pairs: Optional[Dict[Tuple[str, str], float]] = None,
    local_pairs: Optional[Dict[str, Dict[Tuple[str, str], float]]] = None,
) -> Dict[str, Any]:
    rows = [(str(layer_id or ""), str(label or "")) for layer_id, label in (criteria_rows or []) if str(layer_id or "")]
    assignments: Dict[str, str] = {}
    groups: List[str] = []
    for layer_id, label in rows:
        group_name = str((criterion_groups or {}).get(layer_id) or "").strip()
        if not group_name:
            group_name = str(label or layer_id or "기준").strip() or layer_id
        assignments[layer_id] = group_name
        if group_name not in groups:
            groups.append(group_name)

    group_weights, group_lam, group_cr = _weights_from_pair_values(groups, group_pairs)
    local_pairs0 = dict(local_pairs or {})
    local_weights: Dict[str, Dict[str, float]] = {}
    local_lambda: Dict[str, float] = {}
    local_cr: Dict[str, float] = {}
    global_weights: Dict[str, float] = {}

    for group_name in groups:
        member_rows = [(layer_id, label) for layer_id, label in rows if assignments.get(layer_id) == group_name]
        member_ids = [layer_id for layer_id, _label in member_rows]
        weights0, lam0, cr0 = _weights_from_pair_values(member_ids, local_pairs0.get(group_name))
        local_weights[group_name] = weights0
        local_lambda[group_name] = float(lam0)
        local_cr[group_name] = float(cr0)
        group_weight = float(group_weights.get(group_name, 0.0) or 0.0)
        for layer_id in member_ids:
            local_weight = float(weights0.get(layer_id, 0.0) or 0.0)
            global_weights[layer_id] = float(group_weight * local_weight)

    total = float(sum(global_weights.values())) if global_weights else 0.0
    if total > 0 and math.isfinite(total):
        for layer_id in list(global_weights.keys()):
            try:
                global_weights[layer_id] = float(global_weights[layer_id]) / total
            except Exception:
                global_weights[layer_id] = 0.0

    row_ids = [layer_id for layer_id, _label in rows]
    return {
        "criterion_groups": dict(assignments),
        "group_order": list(groups),
        "group_weights": dict(group_weights),
        "group_lambda_max": float(group_lam),
        "group_consistency_ratio": float(group_cr),
        "local_weights": {group: dict(values) for group, values in local_weights.items()},
        "local_lambda_max": dict(local_lambda),
        "local_consistency_ratio": dict(local_cr),
        "global_weights": dict(global_weights),
        "global_pairwise": _pairwise_from_weight_values(row_ids, global_weights),
    }


class _GuidedWeightingDialog(QtWidgets.QDialog):
    def __init__(self, *, criteria_rows: List[Tuple[str, str]], initial_levels: Dict[str, int], parent=None):
        super().__init__(parent)
        self._criteria_rows = list(criteria_rows or [])
        self._initial_levels = dict(initial_levels or {})
        self._combos: Dict[str, QtWidgets.QComboBox] = {}
        self._setup_ui()

    def _setup_ui(self):
        english = is_english_ui()
        self.setWindowTitle("AHP Guided Weighting" if english else "AHP 질문형 가이드")
        layout = QtWidgets.QVBoxLayout(self)

        intro = QtWidgets.QLabel(
            (
                "Answer how important each criterion is for the final suitability decision on a 1-5 scale,\n"
                "and the plugin will convert it to the Saaty scale (1, 3, 5, 7, 9) to fill the pairwise matrix.\n"
                "The same level means equal importance, a 1-level gap becomes 3, and a 2-level gap becomes 5."
            )
            if english
            else
            (
                "각 기준이 최종 입지 판단에 얼마나 중요한지 1~5단계로 답하면,\n"
                "플러그인이 이를 Saaty 척도(1, 3, 5, 7, 9)로 바꿔 쌍대비교 표를 채웁니다.\n"
                "같은 단계면 같은 중요도, 1단계 차이는 3, 2단계 차이는 5로 처리됩니다."
            )
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#455a64;")
        layout.addWidget(intro)

        table = QtWidgets.QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Criterion", "Importance"] if english else ["기준", "중요도"])
        table.setRowCount(len(self._criteria_rows))
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)

        for row, (layer_id, label) in enumerate(self._criteria_rows):
            item = QtWidgets.QTableWidgetItem(str(label or ("(Unnamed)" if english else "(이름 없음)")))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, 0, item)

            combo = QtWidgets.QComboBox()
            for text, value in _guide_importance_options():
                combo.addItem(text, int(value))
            default_level = int(self._initial_levels.get(layer_id, 3) or 3)
            index = max(0, min(len(_GUIDE_IMPORTANCE_OPTIONS) - 1, default_level - 1))
            combo.setCurrentIndex(index)
            table.setCellWidget(row, 1, combo)
            self._combos[str(layer_id or "")] = combo

        try:
            table.resizeColumnsToContents()
        except Exception:
            pass
        layout.addWidget(table, 1)

        quick_row = QtWidgets.QHBoxLayout()
        btn_mid = QtWidgets.QPushButton("Set all to Medium (3)" if english else "모두 보통(3)")
        btn_mid.clicked.connect(lambda: self._set_all_levels(3))
        btn_high = QtWidgets.QPushButton("Prioritize top rows" if english else "앞쪽 기준 높게")
        btn_high.clicked.connect(self._set_descending_levels)
        quick_row.addWidget(btn_mid)
        quick_row.addWidget(btn_high)
        quick_row.addStretch(1)
        layout.addLayout(quick_row)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.resize(560, 420)
        apply_language(self)

    def _set_all_levels(self, level: int):
        level0 = int(level)
        for combo in self._combos.values():
            try:
                idx = combo.findData(level0)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
            except Exception:
                continue

    def _set_descending_levels(self):
        if not self._criteria_rows:
            return
        total = max(1, len(self._criteria_rows) - 1)
        for row, (layer_id, _label) in enumerate(self._criteria_rows):
            try:
                level = 5 - int(round((row * 4.0) / float(total)))
            except Exception:
                level = 3
            level = max(1, min(5, level))
            combo = self._combos.get(str(layer_id or ""))
            if combo is None:
                continue
            try:
                idx = combo.findData(level)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
            except Exception:
                continue

    def selected_levels(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for layer_id, combo in self._combos.items():
            try:
                out[str(layer_id or "")] = int(combo.currentData() or 3)
            except Exception:
                out[str(layer_id or "")] = 3
        return out


class _CriterionPreferenceDialog(QtWidgets.QDialog):
    def __init__(self, *, layer_name: str, criterion: _Criterion, parent=None):
        super().__init__(parent)
        self._criterion = criterion
        self._layer_name = str(layer_name or "").strip() or "(레이어 없음)"
        self._setup_ui()

    def _setup_ui(self):
        english = is_english_ui()
        self.setWindowTitle("Criterion Preference" if english else "기준 선호 설정")
        layout = QtWidgets.QVBoxLayout(self)

        intro = QtWidgets.QLabel(
            (
                f"<b>{self._layer_name}</b><br>"
                "Choose how this criterion is converted to a 0-1 score. "
                "Benefit/Cost uses monotonic increase or decrease, while target/range gives the highest score to a preferred value or interval."
            )
            if english
            else
            (
                f"<b>{self._layer_name}</b><br>"
                "이 기준을 0~1 점수로 바꾸는 방식을 정합니다. "
                "Benefit/Cost는 단조 증가/감소, 목표값/선호구간은 특정 값 또는 범위를 가장 높게 평가합니다."
            )
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#455a64;")
        layout.addWidget(intro)

        self._form = QtWidgets.QFormLayout()
        self.cmbMode = QtWidgets.QComboBox()
        self.cmbMode.addItem("Benefit(값↑ 좋음)", "benefit")
        self.cmbMode.addItem("Cost(값↓ 좋음)", "cost")
        self.cmbMode.addItem("Target optimum" if english else "목표값 최적", "target")
        self.cmbMode.addItem("Preferred range optimum" if english else "선호구간 최적", "range")
        try:
            idx = self.cmbMode.findData(str(self._criterion.direction or "benefit"))
            if idx >= 0:
                self.cmbMode.setCurrentIndex(idx)
        except Exception:
            pass
        self.cmbMode.currentIndexChanged.connect(self._update_mode_ui)
        self._form.addRow("Scoring mode:" if english else "점수화 방식:", self.cmbMode)

        min_text = _fmt_float(self._criterion.min_v, digits=3)
        max_text = _fmt_float(self._criterion.max_v, digits=3)
        self.lblStats = QtWidgets.QLabel(
            f"Current min/max: {min_text} / {max_text}" if english else f"현재 min/max: {min_text} / {max_text}"
        )
        self.lblStats.setStyleSheet("color:#455a64;")
        self._form.addRow("Reference stats:" if english else "통계 참고:", self.lblStats)

        self.spinTarget = QtWidgets.QDoubleSpinBox()
        self.spinTarget.setDecimals(6)
        self.spinTarget.setRange(-1e12, 1e12)
        self.spinTarget.setValue(float(self._criterion.target_v or 0.0))
        self._form.addRow("Target value:" if english else "목표값:", self.spinTarget)

        self.spinPreferMin = QtWidgets.QDoubleSpinBox()
        self.spinPreferMin.setDecimals(6)
        self.spinPreferMin.setRange(-1e12, 1e12)
        self.spinPreferMin.setValue(float(self._criterion.prefer_min or 0.0))
        self._form.addRow("Preferred min:" if english else "선호 최소:", self.spinPreferMin)

        self.spinPreferMax = QtWidgets.QDoubleSpinBox()
        self.spinPreferMax.setDecimals(6)
        self.spinPreferMax.setRange(-1e12, 1e12)
        self.spinPreferMax.setValue(float(self._criterion.prefer_max or 0.0))
        self._form.addRow("Preferred max:" if english else "선호 최대:", self.spinPreferMax)

        layout.addLayout(self._form)

        self.lblModeHint = QtWidgets.QLabel("")
        self.lblModeHint.setWordWrap(True)
        self.lblModeHint.setStyleSheet("color:#455a64;")
        layout.addWidget(self.lblModeHint)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_mode_ui()
        self.resize(520, 260)
        apply_language(self)

    def _update_mode_ui(self):
        mode = str(self.cmbMode.currentData() or "benefit")
        is_target = mode == "target"
        is_range = mode == "range"
        self.spinTarget.setVisible(is_target)
        self.spinPreferMin.setVisible(is_range)
        self.spinPreferMax.setVisible(is_range)
        try:
            self._form.labelForField(self.spinTarget).setVisible(is_target)
            self._form.labelForField(self.spinPreferMin).setVisible(is_range)
            self._form.labelForField(self.spinPreferMax).setVisible(is_range)
        except Exception:
            pass
        hint = {
            "benefit": "Higher values receive higher scores." if is_english_ui() else "값이 클수록 높은 점수를 부여합니다.",
            "cost": "Lower values receive higher scores." if is_english_ui() else "값이 작을수록 높은 점수를 부여합니다.",
            "target": (
                "Score 1 is assigned at the target value and decreases linearly toward min/max."
                if is_english_ui()
                else "지정한 목표값에서 점수 1을 받고, min/max 쪽으로 갈수록 선형으로 감소합니다."
            ),
            "range": (
                "Values inside the preferred range receive score 1, and values outside decrease linearly toward min/max."
                if is_english_ui()
                else "선호 구간 안에서는 점수 1, 그 밖에서는 min/max 방향으로 선형 감소합니다."
            ),
        }.get(mode, "")
        self.lblModeHint.setText(hint)

    def values(self) -> Dict[str, Any]:
        return {
            "direction": str(self.cmbMode.currentData() or "benefit"),
            "target_v": float(self.spinTarget.value()),
            "prefer_min": float(self.spinPreferMin.value()),
            "prefer_max": float(self.spinPreferMax.value()),
        }


class _CriterionReclassDialog(QtWidgets.QDialog):
    def __init__(self, *, layer_name: str, criterion: _Criterion, parent=None):
        super().__init__(parent)
        self._criterion = criterion
        self._layer_name = str(layer_name or "").strip() or "(레이어 없음)"
        self._spins: List[Tuple[QtWidgets.QDoubleSpinBox, QtWidgets.QDoubleSpinBox, QtWidgets.QDoubleSpinBox]] = []
        self._setup_ui()

    def _setup_ui(self):
        english = is_english_ui()
        self.setWindowTitle("Reclass Score Table" if english else "구간 점수표 설정")
        layout = QtWidgets.QVBoxLayout(self)

        intro = QtWidgets.QLabel(
            (
                f"<b>{self._layer_name}</b><br>"
                "Assign a 0-1 score directly to each interval. "
                "Use this when you need paper-style reclassification such as slope classes, distance bands, or category-code scoring."
            )
            if english
            else
            (
                f"<b>{self._layer_name}</b><br>"
                "각 구간에 0~1 점수를 직접 부여합니다. "
                "경사 구간, 거리 구간, 범주 코드별 점수화처럼 논문식 재분류가 필요할 때 사용합니다."
            )
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#455a64;")
        layout.addWidget(intro)

        stats = QtWidgets.QLabel(
            (
                f"Current min/max: {_fmt_float(self._criterion.min_v, digits=3)} / {_fmt_float(self._criterion.max_v, digits=3)}"
                if english
                else f"현재 min/max: {_fmt_float(self._criterion.min_v, digits=3)} / {_fmt_float(self._criterion.max_v, digits=3)}"
            )
        )
        stats.setStyleSheet("color:#455a64;")
        layout.addWidget(stats)

        self.tbl = QtWidgets.QTableWidget()
        self.tbl.setColumnCount(3)
        self.tbl.setHorizontalHeaderLabels(["Min", "Max", "Score (0-1)"] if english else ["최소", "최대", "점수(0-1)"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.tbl, 1)

        row_btns = QtWidgets.QHBoxLayout()
        self.btnAddRow = QtWidgets.QPushButton("Add row" if english else "행 추가")
        self.btnAddRow.clicked.connect(self._add_row)
        self.btnRemoveRow = QtWidgets.QPushButton("Remove selected" if english else "선택 삭제")
        self.btnRemoveRow.clicked.connect(self._remove_selected_row)
        self.btnOneRange = QtWidgets.QPushButton("Single full-range row" if english else "전체범위 1행")
        self.btnOneRange.clicked.connect(self._populate_single_range)
        self.btnFourRanges = QtWidgets.QPushButton("Quartered example" if english else "4등분 예시")
        self.btnFourRanges.clicked.connect(self._populate_quarters)
        row_btns.addWidget(self.btnAddRow)
        row_btns.addWidget(self.btnRemoveRow)
        row_btns.addWidget(self.btnOneRange)
        row_btns.addWidget(self.btnFourRanges)
        row_btns.addStretch(1)
        layout.addLayout(row_btns)

        self.lblHint = QtWidgets.QLabel(
            (
                "Intervals are saved sorted by minimum value. Overlapping intervals raise an error at run time to prevent silent misbehavior."
                if english
                else "구간은 최소값 기준으로 정렬되어 저장됩니다. 구간이 겹치면 실행 시 오류를 내어 조용한 오작동을 막습니다."
            )
        )
        self.lblHint.setWordWrap(True)
        self.lblHint.setStyleSheet("color:#455a64;")
        layout.addWidget(self.lblHint)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_rows()
        self.resize(560, 420)
        apply_language(self)

    def _new_spin(self, *, minimum: float, maximum: float, decimals: int, value: float) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setDecimals(int(decimals))
        spin.setRange(float(minimum), float(maximum))
        spin.setValue(float(value))
        return spin

    def _add_row(self, values: Optional[Dict[str, float]] = None):
        row = self.tbl.rowCount()
        self.tbl.insertRow(row)
        values = dict(values or {})
        spin_min = self._new_spin(minimum=-1e12, maximum=1e12, decimals=6, value=float(values.get("min", 0.0)))
        spin_max = self._new_spin(minimum=-1e12, maximum=1e12, decimals=6, value=float(values.get("max", 0.0)))
        spin_score = self._new_spin(minimum=0.0, maximum=1.0, decimals=3, value=float(values.get("score", 1.0)))
        self.tbl.setCellWidget(row, 0, spin_min)
        self.tbl.setCellWidget(row, 1, spin_max)
        self.tbl.setCellWidget(row, 2, spin_score)
        self._spins.append((spin_min, spin_max, spin_score))

    def _remove_selected_row(self):
        row = self.tbl.currentRow()
        if row < 0:
            return
        self.tbl.removeRow(row)
        try:
            del self._spins[row]
        except Exception:
            pass

    def _clear_rows(self):
        self.tbl.setRowCount(0)
        self._spins = []

    def _load_rows(self):
        rows = self._criterion.score_ranges or []
        if rows:
            for row in rows:
                self._add_row(row)
            return
        self._populate_single_range()

    def _populate_single_range(self):
        self._clear_rows()
        mn = float(self._criterion.min_v) if self._criterion.min_v is not None else 0.0
        mx = float(self._criterion.max_v) if self._criterion.max_v is not None else mn
        self._add_row({"min": mn, "max": mx, "score": 1.0})

    def _populate_quarters(self):
        self._clear_rows()
        mn = float(self._criterion.min_v) if self._criterion.min_v is not None else 0.0
        mx = float(self._criterion.max_v) if self._criterion.max_v is not None else mn
        if mx < mn:
            mn, mx = mx, mn
        span = float(mx - mn)
        if span <= 0:
            self._add_row({"min": mn, "max": mx, "score": 1.0})
            return
        bounds = [mn, mn + span * 0.25, mn + span * 0.50, mn + span * 0.75, mx]
        scores = [0.25, 0.5, 0.75, 1.0]
        for idx in range(4):
            self._add_row({"min": bounds[idx], "max": bounds[idx + 1], "score": scores[idx]})

    def values(self) -> List[Dict[str, float]]:
        rows: List[Dict[str, float]] = []
        for row in range(self.tbl.rowCount()):
            try:
                spin_min = self.tbl.cellWidget(row, 0)
                spin_max = self.tbl.cellWidget(row, 1)
                spin_score = self.tbl.cellWidget(row, 2)
                min_v = float(spin_min.value())
                max_v = float(spin_max.value())
                score = float(spin_score.value())
            except Exception:
                continue
            if max_v < min_v:
                min_v, max_v = max_v, min_v
            rows.append({"min": min_v, "max": max_v, "score": score})
        rows.sort(key=lambda d: (float(d.get("min", 0.0)), float(d.get("max", 0.0))))
        return rows


class _PairwiseMatrixDialog(QtWidgets.QDialog):
    def __init__(
        self,
        *,
        rows: List[Tuple[str, str]],
        title: str,
        intro: str,
        saved_pairs: Optional[Dict[Tuple[str, str], float]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._rows = [(str(row_id or ""), str(label or "")) for row_id, label in (rows or []) if str(row_id or "")]
        self._pairs = _sanitize_pair_values(saved_pairs, [row_id for row_id, _label in self._rows])
        self._title = str(title or "쌍대비교")
        self._intro = str(intro or "")
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle(self._title)
        english = is_english_ui()
        layout = QtWidgets.QVBoxLayout(self)

        lbl = QtWidgets.QLabel(self._intro)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#455a64;")
        layout.addWidget(lbl)

        self.tbl = QtWidgets.QTableWidget()
        self.tbl.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.tbl, 1)

        row_btn = QtWidgets.QHBoxLayout()
        self.btnReset = QtWidgets.QPushButton("Reset (all 1)" if english else "초기화(모두 1)")
        self.btnReset.clicked.connect(self._on_reset)
        row_btn.addWidget(self.btnReset)
        row_btn.addStretch(1)
        layout.addLayout(row_btn)

        self.lblConsistency = QtWidgets.QLabel("CR: -")
        self.lblConsistency.setWordWrap(True)
        self.lblConsistency.setStyleSheet("color:#455a64;")
        layout.addWidget(self.lblConsistency)

        self.lblPreview = QtWidgets.QLabel("")
        self.lblPreview.setWordWrap(True)
        self.lblPreview.setStyleSheet("color:#455a64;")
        layout.addWidget(self.lblPreview)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._rebuild_table()
        self.resize(760, 460)
        apply_language(self)

    def _rebuild_table(self):
        n = len(self._rows)
        self.tbl.clear()
        self.tbl.setRowCount(n)
        self.tbl.setColumnCount(n)
        headers = []
        for _row_id, label in self._rows:
            text = str(label or ("(Item)" if is_english_ui() else "(항목)"))
            headers.append(text[:18] + ("…" if len(text) > 18 else ""))
        self.tbl.setHorizontalHeaderLabels(headers)
        self.tbl.setVerticalHeaderLabels(headers)

        for i in range(n):
            for j in range(n):
                if i == j:
                    item = QtWidgets.QTableWidgetItem("1")
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                    self.tbl.setItem(i, j, item)
                    continue
                if i < j:
                    cmb = QtWidgets.QComboBox()
                    for label, value in _SCALE_OPTIONS:
                        cmb.addItem(label, float(value))
                    left = self._rows[i][0]
                    right = self._rows[j][0]
                    current_value = float(self._pairs.get((left, right), 1.0))
                    current_index = 8
                    for idx_opt, (_label, value) in enumerate(_SCALE_OPTIONS):
                        try:
                            if abs(float(value) - current_value) <= 1e-9:
                                current_index = idx_opt
                                break
                        except Exception:
                            continue
                    cmb.setCurrentIndex(current_index)

                    def _on_changed(_=None, row=i, col=j, widget=cmb):
                        try:
                            value0 = float(widget.currentData() or 1.0)
                        except Exception:
                            value0 = 1.0
                        left0 = self._rows[int(row)][0]
                        right0 = self._rows[int(col)][0]
                        self._pairs[(left0, right0)] = float(value0)
                        self._set_reciprocal_cell(int(row), int(col), float(value0))
                        self._update_summary()

                    cmb.currentIndexChanged.connect(_on_changed)
                    self.tbl.setCellWidget(i, j, cmb)
                    self._set_reciprocal_cell(i, j, current_value)
                else:
                    item = QtWidgets.QTableWidgetItem("1")
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                    self.tbl.setItem(i, j, item)

        try:
            self.tbl.resizeColumnsToContents()
            self.tbl.resizeRowsToContents()
        except Exception:
            pass
        self._update_summary()

    def _set_reciprocal_cell(self, i: int, j: int, value: float):
        try:
            reciprocal = 1.0 / float(value) if float(value) > 0 else 1.0
        except Exception:
            reciprocal = 1.0
        label = None
        for s_label, s_val in _SCALE_OPTIONS:
            try:
                if abs(float(s_val) - float(reciprocal)) <= 1e-9:
                    label = str(s_label)
                    break
            except Exception:
                continue
        if label is None:
            label = _fmt_float(reciprocal, digits=4)
        item = self.tbl.item(int(j), int(i))
        if item is None:
            item = QtWidgets.QTableWidgetItem(label)
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.tbl.setItem(int(j), int(i), item)
        else:
            item.setText(label)

    def _on_reset(self):
        self._pairs = {}
        self._rebuild_table()

    def _update_summary(self):
        row_ids = [row_id for row_id, _label in self._rows]
        weights, lam, cr = _weights_from_pair_values(row_ids, self._pairs)
        lam_txt = _fmt_float(lam, digits=3) if math.isfinite(float(lam)) else "-"
        cr_txt = _fmt_float(cr, digits=3) if math.isfinite(float(cr)) else "-"
        note = ""
        try:
            if math.isfinite(float(cr)) and float(cr) > 0.10:
                note = " (warning: > 0.10)" if is_english_ui() else " (주의: 0.10 초과)"
        except Exception:
            note = ""
        self.lblConsistency.setText(f"λmax={lam_txt}, CR={cr_txt}{note} | {_describe_consistency(cr)}")
        preview = []
        for row_id, label in self._rows[:6]:
            preview.append(f"{label}={_fmt_float(weights.get(row_id), digits=3)}")
        self.lblPreview.setText(("Weight preview: " if is_english_ui() else "가중치 미리보기: ") + (" / ".join(preview) if preview else "-"))

    def pairs(self) -> Dict[Tuple[str, str], float]:
        return dict(self._pairs)


class _HierarchyConfigDialog(QtWidgets.QDialog):
    def __init__(
        self,
        *,
        criteria_rows: List[Tuple[str, str]],
        config: Optional[Dict[str, Any]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._criteria_rows = [(str(layer_id or ""), str(label or "")) for layer_id, label in (criteria_rows or []) if str(layer_id or "")]
        self._config = dict(config or {})
        self._group_pairs: Dict[Tuple[str, str], float] = {}
        self._local_pairs: Dict[str, Dict[Tuple[str, str], float]] = {}
        self._loading_assignments = False
        self._setup_ui()
        self._load_initial_state()

    def _setup_ui(self):
        english = is_english_ui()
        self.setWindowTitle("Hierarchical AHP" if english else "계층형 AHP 설정")
        layout = QtWidgets.QVBoxLayout(self)

        intro = QtWidgets.QLabel(
            (
                "Group criteria into higher-level themes, then compare the importance of the groups and the subcriteria inside each group separately.\n"
                "Example: slope/elevation/aspect -> 'Terrain', distance to stream/distance to water source -> 'Hydrology'."
            )
            if english
            else
            (
                "기준들을 상위그룹으로 묶은 뒤, 상위그룹 간 중요도와 그룹 내부 하위기준 중요도를 따로 비교합니다.\n"
                "예: 경사/고도/방위 -> '지형', 하천거리/수자원거리 -> '수계'."
            )
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#455a64;")
        layout.addWidget(intro)

        self.tblAssignments = QtWidgets.QTableWidget()
        self.tblAssignments.setColumnCount(2)
        self.tblAssignments.setHorizontalHeaderLabels(["Criterion", "Parent Group"] if english else ["기준", "상위그룹"])
        self.tblAssignments.horizontalHeader().setStretchLastSection(True)
        self.tblAssignments.itemChanged.connect(self._on_assignment_changed)
        layout.addWidget(self.tblAssignments, 1)

        row_btn = QtWidgets.QHBoxLayout()
        self.btnDistinctGroups = QtWidgets.QPushButton("Separate all criteria" if english else "각 기준 독립")
        self.btnDistinctGroups.clicked.connect(self._assign_distinct_groups)
        self.btnSingleGroup = QtWidgets.QPushButton("Put all in one group" if english else "모두 한 그룹")
        self.btnSingleGroup.clicked.connect(self._assign_single_group)
        self.btnRefreshGroups = QtWidgets.QPushButton("Refresh group list" if english else "그룹 목록 갱신")
        self.btnRefreshGroups.clicked.connect(self._sync_state_from_assignments)
        row_btn.addWidget(self.btnDistinctGroups)
        row_btn.addWidget(self.btnSingleGroup)
        row_btn.addWidget(self.btnRefreshGroups)
        row_btn.addStretch(1)
        layout.addLayout(row_btn)

        split = QtWidgets.QHBoxLayout()

        left = QtWidgets.QVBoxLayout()
        self.lstGroups = QtWidgets.QListWidget()
        self.lstGroups.currentRowChanged.connect(lambda *_args: self._update_preview())
        left.addWidget(self.lstGroups, 1)
        split.addLayout(left, 0)

        right = QtWidgets.QVBoxLayout()
        self.btnEditGroupPairs = QtWidgets.QPushButton("Compare parent groups…" if english else "상위그룹 비교…")
        self.btnEditGroupPairs.clicked.connect(self._on_edit_group_pairs)
        self.btnEditLocalPairs = QtWidgets.QPushButton("Compare selected group…" if english else "선택 그룹 비교…")
        self.btnEditLocalPairs.clicked.connect(self._on_edit_local_pairs)
        right.addWidget(self.btnEditGroupPairs)
        right.addWidget(self.btnEditLocalPairs)
        right.addStretch(1)
        split.addLayout(right, 0)

        self.tblPreview = QtWidgets.QTableWidget()
        self.tblPreview.setColumnCount(4)
        self.tblPreview.setHorizontalHeaderLabels(
            ["Criterion", "Parent Group", "Local Weight", "Global Weight"]
            if english
            else ["기준", "상위그룹", "로컬 가중치", "글로벌 가중치"]
        )
        self.tblPreview.horizontalHeader().setStretchLastSection(True)
        split.addWidget(self.tblPreview, 1)

        layout.addLayout(split, 1)

        self.lblSummary = QtWidgets.QLabel("")
        self.lblSummary.setWordWrap(True)
        self.lblSummary.setStyleSheet("color:#455a64;")
        layout.addWidget(self.lblSummary)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.resize(980, 620)
        apply_language(self)

    def _load_initial_state(self):
        assignments = dict(self._config.get("criterion_groups") or {})
        self._loading_assignments = True
        try:
            self.tblAssignments.setRowCount(len(self._criteria_rows))
            for row, (layer_id, label) in enumerate(self._criteria_rows):
                item_label = QtWidgets.QTableWidgetItem(str(label or ("(Criterion)" if is_english_ui() else "(기준)")))
                item_label.setFlags(item_label.flags() & ~Qt.ItemIsEditable)
                self.tblAssignments.setItem(row, 0, item_label)
                group_name = str(assignments.get(layer_id) or "").strip()
                if not group_name:
                    group_name = str(label or layer_id or (f"Group {row + 1}" if is_english_ui() else f"그룹 {row + 1}")).strip()
                self.tblAssignments.setItem(row, 1, QtWidgets.QTableWidgetItem(group_name))
        finally:
            self._loading_assignments = False
        self._group_pairs = _sanitize_pair_values(
            self._config.get("group_pairs"),
            list(dict.fromkeys(group_name for group_name in assignments.values() if str(group_name or "").strip())),
        )
        raw_local_pairs = dict(self._config.get("local_pairs") or {})
        self._local_pairs = {
            str(group or ""): dict(pairs or {})
            for group, pairs in raw_local_pairs.items()
            if str(group or "")
        }
        self._sync_state_from_assignments()

    def _assignment_map(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for row, (layer_id, label) in enumerate(self._criteria_rows):
            item = self.tblAssignments.item(row, 1)
            group_name = str(item.text() if item is not None else "").strip()
            if not group_name:
                group_name = str(label or layer_id or (f"Group {row + 1}" if is_english_ui() else f"그룹 {row + 1}")).strip() or layer_id
            out[layer_id] = group_name
        return out

    def _sync_state_from_assignments(self):
        assignments = self._assignment_map()
        groups: List[str] = []
        for layer_id, _label in self._criteria_rows:
            group_name = str(assignments.get(layer_id) or "").strip()
            if group_name and group_name not in groups:
                groups.append(group_name)

        current_group = None
        try:
            current_item = self.lstGroups.currentItem()
            current_group = str(current_item.text() if current_item is not None else "")
        except Exception:
            current_group = None

        self._group_pairs = _sanitize_pair_values(self._group_pairs, groups)
        new_local: Dict[str, Dict[Tuple[str, str], float]] = {}
        for group_name in groups:
            member_ids = [layer_id for layer_id, _label in self._criteria_rows if assignments.get(layer_id) == group_name]
            new_local[group_name] = _sanitize_pair_values(self._local_pairs.get(group_name), member_ids)
        self._local_pairs = new_local

        self.lstGroups.blockSignals(True)
        try:
            self.lstGroups.clear()
            selected_row = 0 if groups else -1
            for idx, group_name in enumerate(groups):
                self.lstGroups.addItem(group_name)
                if current_group and group_name == current_group:
                    selected_row = idx
            self.lstGroups.setCurrentRow(selected_row)
        finally:
            self.lstGroups.blockSignals(False)
        self._update_preview()

    def _assign_distinct_groups(self):
        self._loading_assignments = True
        try:
            for row, (_layer_id, label) in enumerate(self._criteria_rows):
                item = self.tblAssignments.item(row, 1)
                if item is None:
                    item = QtWidgets.QTableWidgetItem("")
                    self.tblAssignments.setItem(row, 1, item)
                item.setText(str(label or (f"Group {row + 1}" if is_english_ui() else f"그룹 {row + 1}")))
        finally:
            self._loading_assignments = False
        self._sync_state_from_assignments()

    def _assign_single_group(self):
        self._loading_assignments = True
        try:
            for row in range(len(self._criteria_rows)):
                item = self.tblAssignments.item(row, 1)
                if item is None:
                    item = QtWidgets.QTableWidgetItem("")
                    self.tblAssignments.setItem(row, 1, item)
                item.setText("Criteria Group 1" if is_english_ui() else "기준군 1")
        finally:
            self._loading_assignments = False
        self._sync_state_from_assignments()

    def _on_assignment_changed(self, _item=None):
        if self._loading_assignments:
            return
        self._sync_state_from_assignments()

    def _on_edit_group_pairs(self):
        assignments = self._assignment_map()
        groups: List[str] = []
        for layer_id, _label in self._criteria_rows:
            group_name = str(assignments.get(layer_id) or "").strip()
            if group_name and group_name not in groups:
                groups.append(group_name)
        if len(groups) < 2:
            QtWidgets.QMessageBox.information(
                self,
                "Hierarchical AHP" if is_english_ui() else "계층형 AHP",
                "You only need parent-group comparison when there are at least two parent groups."
                if is_english_ui()
                else "상위그룹이 2개 이상일 때만 상위그룹 비교가 필요합니다.",
            )
            return
        dlg = _PairwiseMatrixDialog(
            rows=[(group_name, group_name) for group_name in groups],
            title="Parent-group Pairwise Comparison" if is_english_ui() else "상위그룹 쌍대비교",
            intro=(
                "Compare the importance of the parent groups (for example Terrain, Hydrology, Resources) using the Saaty 1-9 scale."
                if is_english_ui()
                else "상위그룹(예: 지형, 수계, 자원)끼리의 중요도를 Saaty 1~9 척도로 비교합니다."
            ),
            saved_pairs=self._group_pairs,
            parent=self,
        )
        res = dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
        if res != QtWidgets.QDialog.Accepted:
            return
        self._group_pairs = dlg.pairs()
        self._update_preview()

    def _on_edit_local_pairs(self):
        assignments = self._assignment_map()
        current_item = self.lstGroups.currentItem()
        group_name = str(current_item.text() if current_item is not None else "").strip()
        if not group_name:
            QtWidgets.QMessageBox.information(
                self,
                "Hierarchical AHP" if is_english_ui() else "계층형 AHP",
                "Select a group first." if is_english_ui() else "먼저 그룹을 하나 선택하세요.",
            )
            return
        member_rows = [(layer_id, label) for layer_id, label in self._criteria_rows if assignments.get(layer_id) == group_name]
        if len(member_rows) < 2:
            QtWidgets.QMessageBox.information(
                self,
                "Hierarchical AHP" if is_english_ui() else "계층형 AHP",
                "You only need local comparison when the selected group has at least two subcriteria."
                if is_english_ui()
                else "선택 그룹의 하위기준이 2개 이상일 때만 내부 비교가 필요합니다.",
            )
            return
        dlg = _PairwiseMatrixDialog(
            rows=member_rows,
            title=f"{group_name} Local Pairwise Comparison" if is_english_ui() else f"{group_name} 하위기준 쌍대비교",
            intro=(
                "Compare the relative importance of subcriteria inside the same parent group."
                if is_english_ui()
                else "같은 상위그룹 안의 하위기준끼리 상대 중요도를 비교합니다."
            ),
            saved_pairs=self._local_pairs.get(group_name),
            parent=self,
        )
        res = dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
        if res != QtWidgets.QDialog.Accepted:
            return
        self._local_pairs[group_name] = dlg.pairs()
        self._update_preview()

    def _update_preview(self):
        summary = _compute_hierarchy_summary(
            criteria_rows=self._criteria_rows,
            criterion_groups=self._assignment_map(),
            group_pairs=self._group_pairs,
            local_pairs=self._local_pairs,
        )
        global_weights = dict(summary.get("global_weights") or {})
        local_weights = dict(summary.get("local_weights") or {})
        assignments = dict(summary.get("criterion_groups") or {})
        self.tblPreview.setRowCount(0)
        for row, (layer_id, label) in enumerate(self._criteria_rows):
            group_name = str(assignments.get(layer_id) or "")
            local_weight = None
            try:
                local_weight = local_weights.get(group_name, {}).get(layer_id)
            except Exception:
                local_weight = None
            self.tblPreview.insertRow(row)
            self.tblPreview.setItem(row, 0, QtWidgets.QTableWidgetItem(str(label or ("(Criterion)" if is_english_ui() else "(기준)"))))
            self.tblPreview.setItem(row, 1, QtWidgets.QTableWidgetItem(group_name))
            self.tblPreview.setItem(row, 2, QtWidgets.QTableWidgetItem(_fmt_float(local_weight, digits=4)))
            self.tblPreview.setItem(row, 3, QtWidgets.QTableWidgetItem(_fmt_float(global_weights.get(layer_id), digits=4)))
        try:
            self.tblPreview.resizeColumnsToContents()
        except Exception:
            pass

        group_cr = summary.get("group_consistency_ratio")
        parts = [f"{'Parent-group' if is_english_ui() else '상위그룹'} CR={_fmt_float(group_cr, digits=3)}"]
        for group_name in summary.get("group_order") or []:
            try:
                cr0 = summary.get("local_consistency_ratio", {}).get(group_name)
            except Exception:
                cr0 = None
            parts.append(f"{group_name} CR={_fmt_float(cr0, digits=3)}")
        self.lblSummary.setText(" / ".join(parts) if parts else "")

    def accept(self):
        self._sync_state_from_assignments()
        super().accept()

    def config(self) -> Dict[str, Any]:
        summary = _compute_hierarchy_summary(
            criteria_rows=self._criteria_rows,
            criterion_groups=self._assignment_map(),
            group_pairs=self._group_pairs,
            local_pairs=self._local_pairs,
        )
        return {
            "criterion_groups": dict(summary.get("criterion_groups") or {}),
            "group_order": list(summary.get("group_order") or []),
            "group_pairs": dict(self._group_pairs),
            "local_pairs": {
                str(group_name or ""): dict(pairs or {})
                for group_name, pairs in self._local_pairs.items()
                if str(group_name or "")
            },
            "computed": summary,
        }


class _ExpertPairwiseDialog(QtWidgets.QDialog):
    def __init__(
        self,
        *,
        criteria_rows: List[Tuple[str, str]],
        base_pairs: Dict[Tuple[str, str], float],
        experts: Optional[List[Dict[str, Any]]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._criteria_rows = list(criteria_rows or [])
        self._experts: List[Dict[str, Any]] = []
        self._active_expert_index = -1
        raw_experts = list(experts or [])
        if raw_experts:
            for item in raw_experts:
                name = str((item or {}).get("name") or "").strip() or (
                    f"Expert {len(self._experts) + 1}" if is_english_ui() else f"전문가 {len(self._experts) + 1}"
                )
                pairs = dict((item or {}).get("pairs") or {})
                self._experts.append({"name": name, "pairs": pairs})
        if not self._experts:
            self._experts = [{"name": "Expert 1" if is_english_ui() else "전문가 1", "pairs": dict(base_pairs or {})}]
        self._setup_ui()

    def _setup_ui(self):
        english = is_english_ui()
        self.setWindowTitle("Expert Pairwise Aggregation" if english else "전문가 쌍대비교 집계")
        layout = QtWidgets.QVBoxLayout(self)

        intro = QtWidgets.QLabel(
            (
                "Enter pairwise matrices from multiple experts, then combine them into one consensus weight table using the geometric mean."
                if english
                else "여러 전문가의 쌍대비교 표를 입력한 뒤 geometric mean으로 하나의 합의 가중치 표를 만듭니다."
            )
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#455a64;")
        layout.addWidget(intro)

        body = QtWidgets.QHBoxLayout()

        left = QtWidgets.QVBoxLayout()
        self.lstExperts = QtWidgets.QListWidget()
        self.lstExperts.currentRowChanged.connect(self._on_expert_changed)
        left.addWidget(self.lstExperts, 1)
        btns = QtWidgets.QHBoxLayout()
        self.btnAddExpert = QtWidgets.QPushButton("Add expert" if english else "전문가 추가")
        self.btnAddExpert.clicked.connect(self._on_add_expert)
        self.btnRemoveExpert = QtWidgets.QPushButton("Remove selected" if english else "선택 삭제")
        self.btnRemoveExpert.clicked.connect(self._on_remove_expert)
        btns.addWidget(self.btnAddExpert)
        btns.addWidget(self.btnRemoveExpert)
        left.addLayout(btns)
        body.addLayout(left, 0)

        right = QtWidgets.QVBoxLayout()
        self.tblPairs = QtWidgets.QTableWidget()
        self.tblPairs.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        right.addWidget(self.tblPairs, 1)
        self.lblExpertHint = QtWidgets.QLabel(
            "Enter the pairwise matrix for each expert." if english else "각 전문가별로 쌍대비교를 입력하세요."
        )
        self.lblExpertHint.setWordWrap(True)
        self.lblExpertHint.setStyleSheet("color:#455a64;")
        right.addWidget(self.lblExpertHint)
        body.addLayout(right, 1)

        layout.addLayout(body, 1)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._reload_expert_list()
        self.resize(860, 520)
        apply_language(self)

    def _reload_expert_list(self):
        self.lstExperts.blockSignals(True)
        try:
            self.lstExperts.clear()
            for item in self._experts:
                self.lstExperts.addItem(str(item.get("name") or ("Expert" if is_english_ui() else "전문가")))
            row = 0 if self.lstExperts.count() > 0 else -1
            self.lstExperts.setCurrentRow(row)
        finally:
            self.lstExperts.blockSignals(False)
        self._active_expert_index = row
        if row >= 0:
            self._load_expert_table(row)

    def _current_pairs(self) -> Dict[Tuple[str, str], float]:
        row = int(self.lstExperts.currentRow())
        if row < 0 or row >= len(self._experts):
            return {}
        return dict(self._experts[row].get("pairs") or {})

    def _save_current_expert_pairs(self, expert_index: Optional[int] = None):
        row = int(self._active_expert_index if expert_index is None else expert_index)
        if row < 0 or row >= len(self._experts):
            return
        pairs: Dict[Tuple[str, str], float] = {}
        for i in range(len(self._criteria_rows)):
            for j in range(i + 1, len(self._criteria_rows)):
                widget = self.tblPairs.cellWidget(i, j)
                if widget is None:
                    continue
                try:
                    value = float(widget.currentData() or 1.0)
                except Exception:
                    value = 1.0
                left_id = str(self._criteria_rows[i][0] or "")
                right_id = str(self._criteria_rows[j][0] or "")
                if left_id and right_id:
                    pairs[(left_id, right_id)] = value
        self._experts[row]["pairs"] = pairs

    def _load_expert_table(self, expert_index: int):
        if expert_index < 0 or expert_index >= len(self._experts):
            return
        pairs = dict(self._experts[expert_index].get("pairs") or {})
        n = len(self._criteria_rows)
        self.tblPairs.clear()
        self.tblPairs.setRowCount(n)
        self.tblPairs.setColumnCount(n)
        headers = []
        for _layer_id, label in self._criteria_rows:
            text = str(label or ("(Layer)" if is_english_ui() else "(레이어)"))
            headers.append(text[:18] + ("…" if len(text) > 18 else ""))
        self.tblPairs.setHorizontalHeaderLabels(headers)
        self.tblPairs.setVerticalHeaderLabels(headers)

        for i in range(n):
            for j in range(n):
                if i == j:
                    item = QtWidgets.QTableWidgetItem("1")
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                    self.tblPairs.setItem(i, j, item)
                    continue
                if i < j:
                    cmb = QtWidgets.QComboBox()
                    for label, val in _SCALE_OPTIONS:
                        cmb.addItem(label, float(val))
                    left_id = str(self._criteria_rows[i][0] or "")
                    right_id = str(self._criteria_rows[j][0] or "")
                    current_value = float(pairs.get((left_id, right_id), 1.0))
                    current_index = 8
                    for idx_opt, (_label, val) in enumerate(_SCALE_OPTIONS):
                        try:
                            if abs(float(val) - current_value) <= 1e-9:
                                current_index = idx_opt
                                break
                        except Exception:
                            continue
                    cmb.setCurrentIndex(current_index)
                    cmb.currentIndexChanged.connect(lambda *_args, r=i, c=j: self._set_expert_reciprocal_cell(r, c))
                    self.tblPairs.setCellWidget(i, j, cmb)
                    self._set_expert_reciprocal_cell(i, j)
                else:
                    item = QtWidgets.QTableWidgetItem("1")
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                    self.tblPairs.setItem(i, j, item)
        try:
            self.tblPairs.resizeColumnsToContents()
            self.tblPairs.resizeRowsToContents()
        except Exception:
            pass

    def _set_expert_reciprocal_cell(self, i: int, j: int):
        widget = self.tblPairs.cellWidget(int(i), int(j))
        if widget is None:
            return
        try:
            value = float(widget.currentData() or 1.0)
            reciprocal = 1.0 / value if value > 0 else 1.0
        except Exception:
            reciprocal = 1.0
        label = None
        for s_label, s_val in _SCALE_OPTIONS:
            try:
                if abs(float(s_val) - float(reciprocal)) <= 1e-9:
                    label = str(s_label)
                    break
            except Exception:
                continue
        if label is None:
            label = _fmt_float(reciprocal, digits=4)
        item = self.tblPairs.item(int(j), int(i))
        if item is None:
            item = QtWidgets.QTableWidgetItem(label)
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.tblPairs.setItem(int(j), int(i), item)
        else:
            item.setText(label)

    def _on_expert_changed(self, row: int):
        try:
            self._save_current_expert_pairs(self._active_expert_index)
        except Exception:
            pass
        self._active_expert_index = int(row)
        self._load_expert_table(int(row))

    def _on_add_expert(self):
        self._save_current_expert_pairs(self._active_expert_index)
        self._experts.append(
            {
                "name": f"Expert {len(self._experts) + 1}" if is_english_ui() else f"전문가 {len(self._experts) + 1}",
                "pairs": {},
            }
        )
        self._reload_expert_list()
        self._active_expert_index = len(self._experts) - 1
        self.lstExperts.setCurrentRow(self._active_expert_index)
        self._load_expert_table(self._active_expert_index)

    def _on_remove_expert(self):
        if len(self._experts) <= 1:
            return
        row = int(self.lstExperts.currentRow())
        if row < 0 or row >= len(self._experts):
            return
        self._save_current_expert_pairs(self._active_expert_index)
        del self._experts[row]
        self._reload_expert_list()

    def accept(self):
        try:
            self._save_current_expert_pairs()
        except Exception:
            pass
        super().accept()

    def experts(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": str(item.get("name") or ""),
                "pairs": dict(item.get("pairs") or {}),
            }
            for item in self._experts
        ]


class AhpSuitabilityDialog(QtWidgets.QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._criteria: List[_Criterion] = []
        self._pairwise: Dict[Tuple[int, int], float] = {}
        self._last_lambda_max: Optional[float] = None
        self._last_consistency_ratio: Optional[float] = None
        self._weight_input_mode = "manual"
        self._weight_input_note = ""
        self._expert_pairwise_inputs: List[Dict[str, Any]] = []
        self._hierarchy_config: Dict[str, Any] = {}
        self._setup_ui()
        self._rebuild_pairwise_table()
        self._set_weight_input_mode("manual")

    def _setup_ui(self):
        english = is_english_ui()
        self.setWindowTitle("AHP Suitability - ArchToolkit" if english else "AHP 입지적합도 (Suitability) - ArchToolkit")
        set_plugin_window_icon(self, ("AHP.png", "ahp.png", "icon.png"))

        outer_layout = QtWidgets.QVBoxLayout(self)
        self.scrollArea = QtWidgets.QScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        outer_layout.addWidget(self.scrollArea, 1)

        scroll_content = QtWidgets.QWidget(self.scrollArea)
        layout = QtWidgets.QVBoxLayout(scroll_content)
        layout.setSizeConstraint(QtWidgets.QLayout.SetMinAndMaxSize)
        self.scrollArea.setWidget(scroll_content)

        header = QtWidgets.QLabel(
            (
                "<b>AHP Suitability</b><br>"
                "Combine prepared environmental rasters with AHP (pairwise-comparison) weights to create a suitability raster.<br>"
                "<span style='color:#455a64;'>Current formulation: each criterion is normalized to 0-1, "
                "then combined with AHP weights in a weighted sum.</span><br>"
                "<i>Tip: choose an AOI and enable 'Clip to AOI extent' to keep outputs lighter.</i><br>"
                "<span style='color:#455a64;'>Reference: Saaty (1980) The Analytic Hierarchy Process</span>"
            )
            if english
            else
            (
                "<b>AHP 입지적합도</b><br>"
                "만들어진 환경변수(래스터)를 AHP(쌍대비교) 가중치로 통합해 적합도 래스터를 생성합니다.<br>"
                "<span style='color:#455a64;'>현재 구현식: 각 기준을 0–1로 정규화한 뒤, AHP 가중치로 가중합합니다.</span><br>"
                "<i>Tip: AOI를 지정하고 ‘AOI 범위로 자르기’를 켜면 결과가 가벼워집니다.</i><br>"
                "<span style='color:#455a64;'>Reference: Saaty (1980) The Analytic Hierarchy Process</span>"
            )
        )
        header.setWordWrap(True)
        header.setStyleSheet("background:#f1f8e9; padding:10px; border:1px solid #dcedc8; border-radius:4px;")
        layout.addWidget(header)

        grp_in = QtWidgets.QGroupBox("1. Inputs" if english else "1. 입력")
        form = QtWidgets.QFormLayout(grp_in)

        self.cmbAoi = QgsMapLayerComboBox(grp_in)
        try:
            from qgis.core import QgsMapLayerProxyModel

            try:
                poly_filter = QgsMapLayerProxyModel.Filter.PolygonLayer
            except Exception:
                poly_filter = QgsMapLayerProxyModel.PolygonLayer
            self.cmbAoi.setFilters(poly_filter)
        except Exception:
            pass
        form.addRow("AOI (optional):" if english else "AOI(선택):", self.cmbAoi)

        self.chkAoiSelectedOnly = QtWidgets.QCheckBox("Use selected AOI features only" if english else "AOI 선택 피처만 사용")
        form.addRow("", self.chkAoiSelectedOnly)

        self.chkClipToAoiExtent = QtWidgets.QCheckBox("Clip to AOI extent (recommended)" if english else "AOI 범위로 자르기(권장)")
        self.chkClipToAoiExtent.setChecked(True)
        form.addRow("", self.chkClipToAoiExtent)

        self.chkAlignToFirst = QtWidgets.QCheckBox("Align to first criterion layer (resample)" if english else "첫 번째 기준 레이어에 정렬(리샘플)")
        self.chkAlignToFirst.setChecked(True)
        form.addRow("", self.chkAlignToFirst)

        layout.addWidget(grp_in)

        # 2) Criteria selection
        grp_crit = QtWidgets.QGroupBox("2. Criteria Selection" if english else "2. 기준(환경변수) 선택")
        vcrit = QtWidgets.QVBoxLayout(grp_crit)

        row_add = QtWidgets.QHBoxLayout()
        self.cmbRaster = QgsMapLayerComboBox(grp_crit)
        try:
            from qgis.core import QgsMapLayerProxyModel

            try:
                raster_filter = QgsMapLayerProxyModel.Filter.RasterLayer
            except Exception:
                raster_filter = QgsMapLayerProxyModel.RasterLayer
            self.cmbRaster.setFilters(raster_filter)
        except Exception:
            pass
        self.cmbRaster.setAllowEmptyLayer(True)

        self.cmbDirection = QtWidgets.QComboBox()
        self.cmbDirection.addItem("Benefit(값↑ 좋음)", "benefit")
        self.cmbDirection.addItem("Cost(값↓ 좋음)", "cost")
        self.cmbDirection.addItem("Target optimum" if english else "목표값 최적", "target")
        self.cmbDirection.addItem("Preferred range optimum" if english else "선호구간 최적", "range")
        self.cmbDirection.addItem("Reclass score table" if english else "구간 점수표", "reclass")

        self.btnAdd = QtWidgets.QPushButton("Add" if english else "추가")
        self.btnAdd.clicked.connect(self._on_add_criterion)
        self.btnRemove = QtWidgets.QPushButton("Remove selected" if english else "선택 제거")
        self.btnRemove.clicked.connect(self._on_remove_selected_criteria)
        self.btnPreference = QtWidgets.QPushButton("Preference…" if english else "선호 설정…")
        self.btnPreference.clicked.connect(self._on_edit_selected_preference)
        self.btnStats = QtWidgets.QPushButton("Compute stats (min/max)" if english else "통계 계산(min/max)")
        self.btnStats.clicked.connect(self._on_compute_stats)

        row_add.addWidget(QtWidgets.QLabel("Raster:" if english else "래스터:"))
        row_add.addWidget(self.cmbRaster, 1)
        row_add.addWidget(QtWidgets.QLabel("Preference:" if english else "선호:"))
        row_add.addWidget(self.cmbDirection)
        row_add.addWidget(self.btnAdd)
        row_add.addWidget(self.btnRemove)
        row_add.addWidget(self.btnPreference)
        row_add.addWidget(self.btnStats)
        vcrit.addLayout(row_add)

        self.tblCriteria = QtWidgets.QTableWidget()
        self.tblCriteria.setColumnCount(6)
        self.tblCriteria.setHorizontalHeaderLabels(
            ["Layer", "Preference", "Config", "min", "max", "weight"]
            if english
            else ["레이어", "선호", "설정", "min", "max", "weight"]
        )
        self.tblCriteria.horizontalHeader().setStretchLastSection(True)
        self.tblCriteria.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tblCriteria.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tblCriteria.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tblCriteria.setMinimumHeight(120)
        vcrit.addWidget(self.tblCriteria, 1)

        layout.addWidget(grp_crit, 1)

        # 3) Pairwise comparison
        grp_w = QtWidgets.QGroupBox("3. AHP Weights (Pairwise Comparison)" if english else "3. AHP 가중치(쌍대비교)")
        vw = QtWidgets.QVBoxLayout(grp_w)

        hint = QtWidgets.QLabel(
            (
                "The value at (i, j) expresses how much more important criterion i is than criterion j.\n"
                "- 1: equal importance\n"
                "- 3/5/7/9: increasingly more important (use 1/3, 1/5 ... for less important)"
            )
            if english
            else
            (
                "표의 (i, j) 값은 i 기준이 j 기준보다 얼마나 중요한지를 의미합니다.\n"
                "- 1: 동일 중요\n"
                "- 3/5/7/9: 점점 더 중요 (반대로 덜 중요하면 1/3, 1/5 ...)"
            )
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#455a64;")
        vw.addWidget(hint)

        self.lblMethodSummary = QtWidgets.QLabel(
            (
                "Scoring options include Benefit/Cost, target optimum, preferred range optimum, and reclass score tables. "
                "An optional two-level hierarchical AHP with parent groups and subcriteria is also supported. "
                "Final suitability = Σ(normalized value × weight). "
                "This works best for continuous or ordinal rasters; categorical rasters are usually better converted to score rasters first."
            )
            if english
            else
            (
                "계산 방식: Benefit/Cost 외에 목표값 최적, 선호구간 최적, 구간 점수표도 지원하며, "
                "선택적으로 상위그룹-하위기준의 2단계 계층형 AHP도 지원합니다. "
                "최종 적합도 = Σ(정규화값 × 가중치)입니다. "
                "연속형/서열형 래스터에 적합하며, 범주형은 먼저 점수 래스터로 바꿔 사용하는 것을 권장합니다."
            )
        )
        self.lblMethodSummary.setWordWrap(True)
        self.lblMethodSummary.setStyleSheet("color:#455a64;")
        vw.addWidget(self.lblMethodSummary)

        self.lblWorkflowTip = create_hint_label(
            (
                "Start with 3-5 criteria, build the first draft with the guided or hierarchical setup, and fine-tune the pairwise matrix at the end."
                if english
                else "처음에는 3~5개 기준으로 시작해 질문형 가이드나 계층형 설정으로 뼈대를 만든 뒤, 마지막에 쌍대비교 표를 미세조정하면 훨씬 수월합니다."
            ),
            tone="tip",
            parent=grp_w,
        )
        vw.addWidget(self.lblWorkflowTip)

        row_quick = QtWidgets.QHBoxLayout()
        self.btnGuidePairwise = QtWidgets.QPushButton("Guided weighting…" if english else "질문형 가이드…")
        self.btnGuidePairwise.clicked.connect(self._on_open_weight_guide)
        self.btnHierarchy = QtWidgets.QPushButton("Hierarchical setup…" if english else "계층형 설정…")
        self.btnHierarchy.clicked.connect(self._on_open_hierarchy_builder)
        self.btnExpertAggregate = QtWidgets.QPushButton("Aggregate experts…" if english else "전문가 집계…")
        self.btnExpertAggregate.clicked.connect(self._on_open_expert_aggregation)
        self.btnEqualWeights = QtWidgets.QPushButton("Equal weights" if english else "균등 가중치")
        self.btnEqualWeights.clicked.connect(self._on_apply_equal_weights)
        row_quick.addWidget(self.btnGuidePairwise)
        row_quick.addWidget(self.btnHierarchy)
        row_quick.addWidget(self.btnExpertAggregate)
        row_quick.addWidget(self.btnEqualWeights)
        row_quick.addStretch(1)
        vw.addLayout(row_quick)

        self.lblWeightInputMode = QtWidgets.QLabel(
            (
                "Quick start: draft the importance with the guided tool first, then fine-tune the matrix if needed."
                if english
                else "빠른 입력: 질문형 가이드로 중요도를 먼저 만든 뒤, 필요하면 표에서 세부 조정하세요."
            )
        )
        self.lblWeightInputMode.setWordWrap(True)
        self.lblWeightInputMode.setStyleSheet("color:#455a64;")
        vw.addWidget(self.lblWeightInputMode)

        self.tblPairwise = QtWidgets.QTableWidget()
        self.tblPairwise.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tblPairwise.setMinimumHeight(140)
        vw.addWidget(self.tblPairwise, 1)

        row_w = QtWidgets.QHBoxLayout()
        self.btnResetPairwise = QtWidgets.QPushButton("Reset (all 1)" if english else "초기화(모두 1)")
        self.btnResetPairwise.clicked.connect(self._on_reset_pairwise)
        self.lblConsistency = QtWidgets.QLabel("CR: -")
        self.lblConsistency.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        try:
            self.lblConsistency.setToolTip(
                "Consistency ratio (CR). CR ≤ 0.10 is generally recommended (Saaty, 1980)."
                if english
                else "일관성비율(CR). 일반적으로 CR ≤ 0.10 권장 (Saaty, 1980)."
            )
        except Exception:
            pass
        row_w.addWidget(self.btnResetPairwise)
        row_w.addStretch(1)
        row_w.addWidget(self.lblConsistency)
        vw.addLayout(row_w)

        self.lblConsistencyHint = QtWidgets.QLabel(
            (
                "Once you add criteria and adjust importance, consistency guidance will be shown here."
                if english
                else "기준을 추가하고 중요도를 조정하면 여기서 가중치 일관성을 설명해줍니다."
            )
        )
        self.lblConsistencyHint.setWordWrap(True)
        self.lblConsistencyHint.setStyleSheet("color:#455a64;")
        vw.addWidget(self.lblConsistencyHint)

        layout.addWidget(grp_w, 2)

        # 4) Output
        grp_out = QtWidgets.QGroupBox("4. Output" if english else "4. 출력")
        fout = QtWidgets.QFormLayout(grp_out)

        self.txtOut = QtWidgets.QLineEdit()
        self.txtOut.setPlaceholderText("(Leave empty to create a temporary file and add it to the project)" if english else "(비우면 임시 파일로 생성 후 프로젝트에 추가)")
        self.btnBrowse = QtWidgets.QPushButton("Browse…" if english else "찾기…")
        self.btnBrowse.clicked.connect(self._on_browse_out)
        w_out = QtWidgets.QWidget()
        h_out = QtWidgets.QHBoxLayout(w_out)
        h_out.setContentsMargins(0, 0, 0, 0)
        h_out.addWidget(self.txtOut, 1)
        h_out.addWidget(self.btnBrowse)
        fout.addRow("Output GeoTIFF:" if english else "출력 GeoTIFF:", w_out)

        self.chkScale100 = QtWidgets.QCheckBox("Convert to 0-100 scale" if english else "0–100 스케일로 변환")
        self.chkScale100.setChecked(False)
        fout.addRow("", self.chkScale100)

        self.chkAddToProject = QtWidgets.QCheckBox("Add to project when finished" if english else "완료 후 프로젝트에 추가")
        self.chkAddToProject.setChecked(True)
        fout.addRow("", self.chkAddToProject)

        layout.addWidget(grp_out)

        grp_research = QtWidgets.QGroupBox("5. Research Constraints / Validation (Optional)" if english else "5. 연구용 제약/검증(선택)")
        fresearch = QtWidgets.QFormLayout(grp_research)

        self.cmbConstraint = QgsMapLayerComboBox(grp_research)
        try:
            from qgis.core import QgsMapLayerProxyModel

            try:
                mask_filter = QgsMapLayerProxyModel.Filter.RasterLayer | QgsMapLayerProxyModel.Filter.PolygonLayer
            except Exception:
                mask_filter = QgsMapLayerProxyModel.RasterLayer | QgsMapLayerProxyModel.PolygonLayer
            self.cmbConstraint.setFilters(mask_filter)
        except Exception:
            pass
        self.cmbConstraint.setAllowEmptyLayer(True)
        fresearch.addRow("Constraint mask:" if english else "제약 마스크:", self.cmbConstraint)

        self.lblConstraintHint = QtWidgets.QLabel(
            (
                "Polygon masks set areas outside the mask to NoData, while raster masks keep only cells with values greater than 0."
                if english
                else "폴리곤 마스크는 영역 밖을 NoData로, 래스터 마스크는 값이 0보다 큰 셀만 유지합니다."
            )
        )
        self.lblConstraintHint.setWordWrap(True)
        self.lblConstraintHint.setStyleSheet("color:#455a64;")
        fresearch.addRow("", self.lblConstraintHint)

        self.cmbValidation = QgsMapLayerComboBox(grp_research)
        try:
            from qgis.core import QgsMapLayerProxyModel

            try:
                point_filter = QgsMapLayerProxyModel.Filter.PointLayer
            except Exception:
                point_filter = QgsMapLayerProxyModel.PointLayer
            self.cmbValidation.setFilters(point_filter)
        except Exception:
            pass
        self.cmbValidation.setAllowEmptyLayer(True)
        fresearch.addRow("Validation points:" if english else "검증 포인트:", self.cmbValidation)

        self.chkValidationSelectedOnly = QtWidgets.QCheckBox("Use selected validation features only" if english else "검증 레이어 선택 피처만 사용")
        fresearch.addRow("", self.chkValidationSelectedOnly)

        self.lblValidationHint = QtWidgets.QLabel(
            (
                "After running, the tool samples suitability values at known sites and reports mean/median plus 50/70/90% exceedance rates."
                if english
                else "실행 후 known-site suitability 값을 샘플링해 mean/median과 50/70/90% 도달률을 계산합니다."
            )
        )
        self.lblValidationHint.setWordWrap(True)
        self.lblValidationHint.setStyleSheet("color:#455a64;")
        fresearch.addRow("", self.lblValidationHint)

        layout.addWidget(grp_research)
        layout.addStretch(1)

        btn_row = QtWidgets.QHBoxLayout()
        self.btnRun = QtWidgets.QPushButton("Run" if english else "실행")
        self.btnRun.clicked.connect(self._on_run)
        self.btnHelp = QtWidgets.QPushButton("Help" if english else "도움말")
        self.btnHelp.clicked.connect(self._on_help)
        self.btnClose = QtWidgets.QPushButton("Close" if english else "닫기")
        self.btnClose.clicked.connect(self.reject)
        btn_row.addWidget(self.btnRun)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btnHelp)
        btn_row.addWidget(self.btnClose)
        outer_layout.addLayout(btn_row)

        self.resize(920, 720)
        apply_language(self)

    def _on_help(self):
        if is_english_ui():
            html = """
<h3>AHP Suitability Help</h3>
<p>
Combines multiple environmental rasters with AHP (pairwise-comparison) weights to create a single suitability raster.
</p>

<h4>Workflow</h4>
<ol>
  <li>Select an <b>AOI</b> if you want to align extent and resolution.</li>
  <li>Add raster layers to use as <b>criteria</b>, then choose a benefit / cost preference for each one.</li>
  <li>The <b>Question Guide</b> can build a starting pairwise-comparison table from simple 1-5 importance answers.</li>
  <li><b>Hierarchy Settings</b> let you group criteria into parent groups and build a 2-level AHP structure.</li>
  <li><b>Expert Aggregation</b> combines multiple pairwise-comparison tables with a geometric mean.</li>
  <li>Fill in the <b>pairwise-comparison</b> table using the Saaty 1-9 scale.</li>
  <li>Optionally apply a <b>constraint mask</b> to exclude areas from the final suitability output.</li>
  <li>Optionally add <b>validation points</b> to quickly check whether known sites fall in high-suitability zones.</li>
  <li>Review the <b>CR (Consistency Ratio)</b> and run the tool.</li>
  <li>Optionally rescale the output to <b>0-100</b> for mapping or reporting.</li>
</ol>

<h4>Notes</h4>
<ul>
  <li>This tool calculates <b>AHP weights</b> first, then applies a <b>min-max normalization</b> and a weighted sum to the criterion rasters.</li>
  <li>The default workflow is flat AHP + weighted overlay, but a two-level hierarchy can also be used.</li>
  <li>Differences in <b>CRS, resolution, and NoData handling</b> between rasters can distort the result.</li>
  <li>Criteria where lower values are preferable (for example slope or distance) should use <b>Cost</b>.</li>
  <li>If a specific target value or preferred range is most suitable, use <b>Target Value Optimal</b> or <b>Preferred Range Optimal</b>.</li>
  <li>For <b>categorical rasters</b> such as geology or land-cover classes, use the <b>Reclass Score Table</b> to assign 0-1 scores directly.</li>
  <li>The current validation output is a <b>quick validation</b> summary, not a full ROC / AUC or predictive-gain workflow.</li>
  <li>If pairwise comparison feels heavy, start with 3-5 criteria and expand gradually.</li>
</ul>
        """
            title = "AHP Suitability Help"
        else:
            html = """
<h3>AHP 입지분석(적합도) 도움말</h3>
<p>
여러 환경 래스터(기준)를 AHP(쌍대비교) 가중치로 결합해 하나의 적합도 래스터를 만듭니다.
</p>

<h4>작업 흐름</h4>
<ol>
  <li><b>AOI</b>를 선택합니다(선택). 범위/해상도를 통일하고 싶을 때 유용합니다.</li>
  <li><b>기준(criterion)</b>으로 사용할 래스터들을 추가하고, Benefit/Cost 방향을 지정합니다.</li>
  <li><b>질문형 가이드</b>를 쓰면 각 기준의 중요도를 1~5단계로만 답해도 기본 쌍대비교 표를 생성할 수 있습니다.</li>
  <li><b>계층형 설정</b>을 쓰면 기준을 상위그룹으로 묶어 group weight × local weight 형태의 2단계 AHP를 만들 수 있습니다.</li>
  <li><b>전문가 집계</b>를 쓰면 여러 전문가의 쌍대비교를 geometric mean으로 합의 가중치로 묶을 수 있습니다.</li>
  <li><b>쌍대비교</b> 테이블에서 중요도를 입력합니다(사티(Saaty) 1–9 척도).</li>
  <li>(선택) <b>제약 마스크</b>를 넣으면 법적 제외구역·수면·급경사 제한처럼 “분석은 하되 최종 적합도에서 제외할 영역”을 반영할 수 있습니다.</li>
  <li>(선택) <b>검증 포인트</b>를 넣으면 known-site가 높은 적합도 영역에 얼마나 들어오는지 빠르게 점검할 수 있습니다.</li>
  <li><b>CR(일관성비율)</b>을 확인하고(권장 CR ≤ 0.10), 실행합니다.</li>
  <li>(옵션) 결과를 0–100 스케일로 변환해 시각화/보고에 사용합니다.</li>
</ol>

<h4>주의/팁</h4>
<ul>
  <li>이 도구는 <b>AHP로 가중치</b>를 구한 뒤, 각 기준 래스터를 <b>min-max 정규화</b>해서 <b>가중합</b>하는 방식입니다.</li>
  <li>기본은 flat AHP + 가중 오버레이이고, 필요하면 <b>상위그룹-하위기준의 2단계 계층형 AHP</b>를 사용할 수 있습니다.</li>
  <li>기준 래스터의 <b>CRS/해상도/NoData</b>가 다르면 결과가 왜곡될 수 있습니다.</li>
  <li>값이 “낮을수록 유리”한 기준(예: 경사, 거리)은 <b>Cost(값↓)</b>로 지정하세요.</li>
  <li>특정 고도/거리대가 가장 유리하다면 <b>목표값 최적</b> 또는 <b>선호구간 최적</b>으로 재분류할 수 있습니다.</li>
  <li><b>범주형 래스터</b>(예: 지질 코드, 토지피복 클래스)나 수치 구간 점수화가 필요하면 <b>구간 점수표</b>를 사용해 직접 0~1 점수를 지정할 수 있습니다.</li>
  <li>현재 검증 기능은 <b>quick validation</b>입니다. ROC/AUC나 predictive gain 같은 논문형 평가는 아직 별도 구현이 필요합니다.</li>
  <li>쌍대비교가 어려우면 먼저 3~5개 기준으로 시작해 점진적으로 늘리는 것을 권장합니다.</li>
</ul>
        """
            title = "AHP 적합도 도움말"
        try:
            show_help_dialog(parent=self, title=title, html=html)
        except Exception:
            pass

    def _criterion_layer(self, crit: _Criterion) -> Optional[QgsRasterLayer]:
        try:
            lyr = QgsProject.instance().mapLayer(str(crit.layer_id or ""))
            return lyr if isinstance(lyr, QgsRasterLayer) else None
        except Exception:
            return None

    def _selected_criterion_row(self) -> Optional[int]:
        try:
            rows = [idx.row() for idx in self.tblCriteria.selectionModel().selectedRows()]
            if rows:
                row = int(rows[0])
                if 0 <= row < len(self._criteria):
                    return row
        except Exception:
            pass
        try:
            row = int(self.tblCriteria.currentRow())
            if 0 <= row < len(self._criteria):
                return row
        except Exception:
            pass
        return None

    def _criterion_rows(self) -> List[Tuple[str, str]]:
        rows: List[Tuple[str, str]] = []
        for crit in self._criteria:
            layer = self._criterion_layer(crit)
            rows.append((str(crit.layer_id or ""), str(layer.name() if layer is not None else "(레이어 없음)")))
        return rows

    def _sanitize_hierarchy_config(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raw = dict(config if config is not None else self._hierarchy_config or {})
        if not raw:
            return {}

        criteria_rows = self._criterion_rows()
        assignments_raw = dict(raw.get("criterion_groups") or {})
        group_pairs_raw = raw.get("group_pairs")
        local_pairs_raw = dict(raw.get("local_pairs") or {})

        assignments: Dict[str, str] = {}
        for layer_id, label in criteria_rows:
            group_name = str(assignments_raw.get(layer_id) or "").strip()
            if not group_name:
                group_name = str(label or layer_id or "기준").strip() or layer_id
            assignments[layer_id] = group_name

        groups: List[str] = []
        for layer_id, _label in criteria_rows:
            group_name = str(assignments.get(layer_id) or "").strip()
            if group_name and group_name not in groups:
                groups.append(group_name)

        group_pairs = _sanitize_pair_values(group_pairs_raw, groups)
        local_pairs: Dict[str, Dict[Tuple[str, str], float]] = {}
        for group_name in groups:
            member_ids = [layer_id for layer_id, _label in criteria_rows if assignments.get(layer_id) == group_name]
            local_pairs[group_name] = _sanitize_pair_values(local_pairs_raw.get(group_name), member_ids)

        summary = _compute_hierarchy_summary(
            criteria_rows=criteria_rows,
            criterion_groups=assignments,
            group_pairs=group_pairs,
            local_pairs=local_pairs,
        )
        return {
            "criterion_groups": dict(assignments),
            "group_order": list(groups),
            "group_pairs": dict(group_pairs),
            "local_pairs": {group: dict(values) for group, values in local_pairs.items()},
            "computed": summary,
        }

    def _hierarchy_note(self, config: Optional[Dict[str, Any]] = None) -> str:
        config0 = self._sanitize_hierarchy_config(config)
        if not config0:
            return ""
        groups = list(config0.get("group_order") or [])
        preview = " / ".join(groups[:4])
        if len(groups) > 4:
            preview = f"{preview} / ..."
        if preview:
            return f"{len(groups)} parent groups: {preview}" if is_english_ui() else f"{len(groups)}개 상위그룹: {preview}"
        return "Hierarchical AHP" if is_english_ui() else "계층형 AHP"

    def _apply_hierarchy_config(self, config: Optional[Dict[str, Any]], *, note_prefix: str = "") -> bool:
        config0 = self._sanitize_hierarchy_config(config)
        if not config0:
            return False
        summary = dict(config0.get("computed") or {})
        pairwise = dict(summary.get("global_pairwise") or {})
        self._hierarchy_config = config0
        self._rebuild_pairwise_table(saved_pairs=pairwise)
        note = self._hierarchy_note(config0)
        if note_prefix:
            note = f"{str(note_prefix).strip()} {note}".strip()
        self._set_weight_input_mode("hierarchy", note)
        return True

    def _serialized_hierarchy_config(self) -> Optional[Dict[str, Any]]:
        if not str(self._weight_input_mode or "").startswith("hierarchy"):
            return None
        config = self._sanitize_hierarchy_config(self._hierarchy_config)
        if not config:
            return None
        summary = dict(config.get("computed") or {})
        criteria_rows = dict(self._criterion_rows())
        return {
            "criterion_groups": [
                {
                    "layer_id": layer_id,
                    "layer_name": criteria_rows.get(layer_id, ""),
                    "group": group_name,
                }
                for layer_id, group_name in config.get("criterion_groups", {}).items()
            ],
            "group_order": list(config.get("group_order") or []),
            "group_pairwise": [
                {
                    "left_group": str(key[0] or ""),
                    "right_group": str(key[1] or ""),
                    "value": float(value),
                }
                for key, value in sorted(dict(config.get("group_pairs") or {}).items())
            ],
            "local_pairwise": [
                {
                    "group": str(group_name or ""),
                    "pairs": [
                        {
                            "left_layer_id": str(key[0] or ""),
                            "left_layer_name": criteria_rows.get(str(key[0] or ""), ""),
                            "right_layer_id": str(key[1] or ""),
                            "right_layer_name": criteria_rows.get(str(key[1] or ""), ""),
                            "value": float(value),
                        }
                        for key, value in sorted(dict(pairs or {}).items())
                    ],
                }
                for group_name, pairs in dict(config.get("local_pairs") or {}).items()
            ],
            "group_weights": [
                {
                    "group": group_name,
                    "weight": float(summary.get("group_weights", {}).get(group_name)),
                    "local_consistency_ratio": summary.get("local_consistency_ratio", {}).get(group_name),
                }
                for group_name in summary.get("group_order") or []
            ],
            "group_level_consistency_ratio": summary.get("group_consistency_ratio"),
            "global_weights": [
                {
                    "layer_id": layer_id,
                    "layer_name": criteria_rows.get(layer_id, ""),
                    "group": summary.get("criterion_groups", {}).get(layer_id),
                    "weight": float(weight),
                }
                for layer_id, weight in sorted(dict(summary.get("global_weights") or {}).items())
            ],
        }

    def _ensure_criterion_preference_defaults(self, crit: _Criterion) -> None:
        try:
            mn = float(crit.min_v) if crit.min_v is not None else None
            mx = float(crit.max_v) if crit.max_v is not None else None
        except Exception:
            mn, mx = None, None
        if mn is None or mx is None or (not math.isfinite(mn)) or (not math.isfinite(mx)):
            return
        if mx < mn:
            mn, mx = mx, mn
        span = float(mx - mn)
        mode = str(crit.direction or "benefit")
        if mode == "target":
            target_v = crit.target_v
            try:
                target0 = float(target_v) if target_v is not None else None
            except Exception:
                target0 = None
            if target0 is None or (not math.isfinite(target0)) or target0 < mn or target0 > mx:
                crit.target_v = mn + (span / 2.0 if span > 0 else 0.0)
        elif mode == "range":
            pmin = crit.prefer_min
            pmax = crit.prefer_max
            try:
                pmin0 = float(pmin) if pmin is not None else None
                pmax0 = float(pmax) if pmax is not None else None
            except Exception:
                pmin0, pmax0 = None, None
        invalid_range = any(
            (
                pmin0 is None,
                pmax0 is None,
                not math.isfinite(pmin0),
                not math.isfinite(pmax0),
                pmin0 >= pmax0,
                pmin0 < mn,
                pmax0 > mx,
            )
        )
        if invalid_range:
            if span > 0:
                crit.prefer_min = mn + (span * 0.25)
                crit.prefer_max = mn + (span * 0.75)
            else:
                crit.prefer_min = mn
                crit.prefer_max = mx
        elif mode == "reclass":
            rows = crit.score_ranges or []
            if not rows:
                crit.score_ranges = [
                    {
                        "min": float(mn),
                        "max": float(mx),
                        "score": 1.0,
                    }
                ]

    def _on_edit_selected_preference(self):
        row = self._selected_criterion_row()
        if row is None:
            push_message(self.iface, "정보", "선호 설정을 바꿀 기준 레이어를 표에서 하나 선택하세요.", level=1, duration=5)
            return
        crit = self._criteria[row]
        lyr = self._criterion_layer(crit)
        if lyr is not None and (crit.min_v is None or crit.max_v is None):
            mn, mx = self._compute_minmax_for_layer(lyr)
            crit.min_v = mn
            crit.max_v = mx
        self._ensure_criterion_preference_defaults(crit)

        if str(crit.direction or "benefit") == "reclass":
            dlg = _CriterionReclassDialog(
                layer_name=str(lyr.name() if lyr is not None else "(레이어 없음)"),
                criterion=crit,
                parent=self,
            )
            res = dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
            if res != QtWidgets.QDialog.Accepted:
                return
            crit.score_ranges = dlg.values()
            self._refresh_criteria_table()
            return

        dlg = _CriterionPreferenceDialog(
            layer_name=str(lyr.name() if lyr is not None else "(레이어 없음)"),
            criterion=crit,
            parent=self,
        )
        res = dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
        if res != QtWidgets.QDialog.Accepted:
            return

        values = dlg.values()
        crit.direction = str(values.get("direction") or "benefit")
        crit.target_v = float(values.get("target_v")) if values.get("target_v") is not None else None
        crit.prefer_min = float(values.get("prefer_min")) if values.get("prefer_min") is not None else None
        crit.prefer_max = float(values.get("prefer_max")) if values.get("prefer_max") is not None else None
        self._ensure_criterion_preference_defaults(crit)
        self._refresh_criteria_table()

    def _on_add_criterion(self):
        lyr = self.cmbRaster.currentLayer()
        if lyr is None or not isinstance(lyr, QgsRasterLayer):
            push_message(self.iface, "오류", "기준으로 사용할 래스터 레이어를 선택하세요.", level=2, duration=6)
            return

        lid = str(lyr.id() or "")
        if any(c.layer_id == lid for c in self._criteria):
            push_message(self.iface, "정보", "이미 추가된 레이어입니다.", level=1, duration=4)
            return

        direction = str(self.cmbDirection.currentData() or "benefit")
        saved_pairs = self._pairwise_values_by_layer_ids()
        hierarchy_active = str(self._weight_input_mode or "").startswith("hierarchy")
        self._expert_pairwise_inputs = []
        self._criteria.append(_Criterion(layer_id=lid, direction=direction))
        self._refresh_criteria_table()
        if hierarchy_active and self._apply_hierarchy_config(self._hierarchy_config, note_prefix="기준 변경 후 재계산."):
            return
        self._rebuild_pairwise_table(saved_pairs=saved_pairs)

    def _on_remove_selected_criteria(self):
        rows = sorted({idx.row() for idx in self.tblCriteria.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            return
        saved_pairs = self._pairwise_values_by_layer_ids()
        hierarchy_active = str(self._weight_input_mode or "").startswith("hierarchy")
        self._expert_pairwise_inputs = []
        try:
            for r in rows:
                if 0 <= r < len(self._criteria):
                    del self._criteria[r]
        except Exception:
            pass
        self._refresh_criteria_table()
        if hierarchy_active and self._apply_hierarchy_config(self._hierarchy_config, note_prefix="기준 변경 후 재계산."):
            return
        self._rebuild_pairwise_table(saved_pairs=saved_pairs)

    def _refresh_criteria_table(self):
        self.tblCriteria.setRowCount(0)
        for i, crit in enumerate(self._criteria):
            lyr = self._criterion_layer(crit)
            name = str(lyr.name() if lyr is not None else "(레이어 없음)")
            self._ensure_criterion_preference_defaults(crit)

            self.tblCriteria.insertRow(i)

            it = QtWidgets.QTableWidgetItem(name)
            it.setData(Qt.UserRole, str(crit.layer_id))
            self.tblCriteria.setItem(i, 0, it)

            cmb = QtWidgets.QComboBox()
            cmb.addItem("Benefit(값↑)", "benefit")
            cmb.addItem("Cost(값↓)", "cost")
            cmb.addItem("Target optimum" if is_english_ui() else "목표값 최적", "target")
            cmb.addItem("Preferred range optimum" if is_english_ui() else "선호구간 최적", "range")
            cmb.addItem("Reclass score table" if is_english_ui() else "구간 점수표", "reclass")
            try:
                idx = cmb.findData(str(crit.direction or "benefit"))
                if idx >= 0:
                    cmb.setCurrentIndex(idx)
            except Exception:
                pass

            def _on_dir_changed(_=None, row=i, w=cmb):
                try:
                    v = str(w.currentData() or "benefit")
                    if 0 <= int(row) < len(self._criteria):
                        self._criteria[int(row)].direction = v
                        self._ensure_criterion_preference_defaults(self._criteria[int(row)])
                        self._refresh_criteria_table()
                except Exception:
                    pass

            cmb.currentIndexChanged.connect(_on_dir_changed)
            self.tblCriteria.setCellWidget(i, 1, cmb)

            self.tblCriteria.setItem(i, 2, QtWidgets.QTableWidgetItem(_criterion_setting_summary(crit)))
            self.tblCriteria.setItem(i, 3, QtWidgets.QTableWidgetItem(_fmt_float(crit.min_v)))
            self.tblCriteria.setItem(i, 4, QtWidgets.QTableWidgetItem(_fmt_float(crit.max_v)))
            self.tblCriteria.setItem(i, 5, QtWidgets.QTableWidgetItem(_fmt_float(crit.weight, digits=6)))

        try:
            self.tblCriteria.resizeColumnsToContents()
        except Exception:
            pass

        self._update_consistency_and_weights()

    def _pairwise_values_by_layer_ids(self) -> Dict[Tuple[str, str], float]:
        saved: Dict[Tuple[str, str], float] = {}
        for (i, j), value in (self._pairwise or {}).items():
            try:
                left = str(self._criteria[int(i)].layer_id or "")
                right = str(self._criteria[int(j)].layer_id or "")
                if not left or not right or left == right:
                    continue
                saved[(left, right)] = float(value)
            except Exception:
                continue
        return saved

    def _suggest_importance_levels(self) -> Dict[str, int]:
        levels: Dict[str, int] = {}
        if not self._criteria:
            return levels

        weighted = []
        for crit in self._criteria:
            try:
                weight = float(crit.weight)
            except Exception:
                weight = None
            if weight is None or (not math.isfinite(weight)):
                continue
            weighted.append((str(crit.layer_id or ""), float(weight)))

        if not weighted:
            return {str(c.layer_id or ""): 3 for c in self._criteria}

        unique_weights = sorted({weight for _layer_id, weight in weighted})
        if len(unique_weights) == 1:
            return {str(c.layer_id or ""): 3 for c in self._criteria}

        for layer_id, weight in weighted:
            try:
                rank = unique_weights.index(weight)
                level = 1 + int(round((rank * 4.0) / float(len(unique_weights) - 1)))
            except Exception:
                level = 3
            levels[layer_id] = max(1, min(5, level))

        for crit in self._criteria:
            levels.setdefault(str(crit.layer_id or ""), 3)
        return levels

    def _guided_pairs_from_levels(self, levels: Dict[str, int]) -> Dict[Tuple[str, str], float]:
        saved: Dict[Tuple[str, str], float] = {}
        for i in range(len(self._criteria)):
            for j in range(i + 1, len(self._criteria)):
                left = self._criteria[i]
                right = self._criteria[j]
                left_level = int(levels.get(str(left.layer_id or ""), 3) or 3)
                right_level = int(levels.get(str(right.layer_id or ""), 3) or 3)
                diff = min(4, abs(int(left_level) - int(right_level)))
                ratio = float(_GUIDE_DIFF_TO_SAATY.get(diff, 1.0))
                if left_level < right_level:
                    ratio = 1.0 / ratio if ratio > 0 else 1.0
                saved[(str(left.layer_id or ""), str(right.layer_id or ""))] = float(ratio)
        return saved

    def _set_weight_input_mode(self, mode: str, note: str = ""):
        self._weight_input_mode = str(mode or "manual")
        self._weight_input_note = str(note or "").strip()
        text = ""
        if self._weight_input_mode == "guided_levels":
            text = tr("현재 가중치 표는 질문형 가이드(1~5 중요도)에서 생성되었습니다.")
        elif self._weight_input_mode == "guided_levels_manual_edit":
            text = tr("질문형 가이드로 만든 표를 수동으로 미세조정한 상태입니다.")
        elif self._weight_input_mode == "hierarchy":
            text = tr("현재 가중치 표는 상위그룹-하위기준의 2단계 계층형 AHP에서 생성되었습니다.")
        elif self._weight_input_mode == "hierarchy_manual_edit":
            text = tr("계층형 AHP로 만든 표를 수동으로 미세조정한 상태입니다.")
        elif self._weight_input_mode == "expert_geomean":
            text = tr("현재 가중치 표는 여러 전문가의 쌍대비교를 geometric mean으로 집계한 상태입니다.")
        elif self._weight_input_mode == "expert_geomean_manual_edit":
            text = tr("전문가 집계 결과를 수동으로 미세조정한 상태입니다.")
        elif self._weight_input_mode == "equal":
            text = tr("현재 모든 기준을 같은 중요도(1)로 두고 있습니다.")
        else:
            text = tr("현재 쌍대비교 표를 직접 편집하는 수동 입력 상태입니다.")
        if self._weight_input_note:
            text = f"{text} {self._weight_input_note}"
        self.lblWeightInputMode.setText(text)

    def _mark_manual_weight_edit(self):
        if self._weight_input_mode == "guided_levels":
            self._set_weight_input_mode("guided_levels_manual_edit")
        elif self._weight_input_mode == "hierarchy":
            self._set_weight_input_mode("hierarchy_manual_edit", self._hierarchy_note(self._hierarchy_config))
        elif self._weight_input_mode == "expert_geomean":
            self._set_weight_input_mode("expert_geomean_manual_edit")
        elif self._weight_input_mode not in ("guided_levels_manual_edit", "hierarchy_manual_edit", "expert_geomean_manual_edit"):
            self._set_weight_input_mode("manual")

    def _on_open_weight_guide(self):
        if len(self._criteria) < 2:
            push_message(self.iface, "정보", "질문형 가이드는 기준이 2개 이상일 때 사용할 수 있습니다.", level=1, duration=5)
            return

        criteria_rows = []
        for crit in self._criteria:
            layer = self._criterion_layer(crit)
            criteria_rows.append((str(crit.layer_id or ""), str(layer.name() if layer is not None else "(레이어 없음)")))

        dlg = _GuidedWeightingDialog(
            criteria_rows=criteria_rows,
            initial_levels=self._suggest_importance_levels(),
            parent=self,
        )
        res = dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
        if res != QtWidgets.QDialog.Accepted:
            return

        levels = dlg.selected_levels()
        saved_pairs = self._guided_pairs_from_levels(levels)
        self._rebuild_pairwise_table(saved_pairs=saved_pairs)
        level_preview = []
        for layer_id, label in criteria_rows:
            level = int(levels.get(layer_id, 3) or 3)
            level_preview.append(f"{label}={level}")
        self._set_weight_input_mode("guided_levels", " / ".join(level_preview[:6]))

    def _on_open_hierarchy_builder(self):
        if len(self._criteria) < 2:
            push_message(self.iface, "정보", "계층형 AHP는 기준이 2개 이상일 때 사용할 수 있습니다.", level=1, duration=5)
            return

        dlg = _HierarchyConfigDialog(
            criteria_rows=self._criterion_rows(),
            config=self._sanitize_hierarchy_config(self._hierarchy_config),
            parent=self,
        )
        res = dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
        if res != QtWidgets.QDialog.Accepted:
            return
        self._apply_hierarchy_config(dlg.config())

    def _on_open_expert_aggregation(self):
        if len(self._criteria) < 2:
            push_message(self.iface, "정보", "전문가 집계는 기준이 2개 이상일 때 사용할 수 있습니다.", level=1, duration=5)
            return

        criteria_rows = []
        for crit in self._criteria:
            layer = self._criterion_layer(crit)
            criteria_rows.append((str(crit.layer_id or ""), str(layer.name() if layer is not None else "(레이어 없음)")))

        dlg = _ExpertPairwiseDialog(
            criteria_rows=criteria_rows,
            base_pairs=self._pairwise_values_by_layer_ids(),
            experts=self._expert_pairwise_inputs,
            parent=self,
        )
        res = dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
        if res != QtWidgets.QDialog.Accepted:
            return

        experts = dlg.experts()
        aggregated: Dict[Tuple[str, str], float] = {}
        for i in range(len(self._criteria)):
            for j in range(i + 1, len(self._criteria)):
                left = str(self._criteria[i].layer_id or "")
                right = str(self._criteria[j].layer_id or "")
                values = []
                for expert in experts:
                    try:
                        pairs = dict(expert.get("pairs") or {})
                        value = float(pairs.get((left, right), 1.0))
                        if value > 0 and math.isfinite(value):
                            values.append(value)
                    except Exception:
                        continue
                if not values:
                    aggregated[(left, right)] = 1.0
                    continue
                try:
                    geo_mean = math.exp(sum(math.log(v) for v in values) / float(len(values)))
                except Exception:
                    geo_mean = 1.0
                aggregated[(left, right)] = float(geo_mean)

        self._expert_pairwise_inputs = experts
        self._rebuild_pairwise_table(saved_pairs=aggregated)
        self._set_weight_input_mode(
            "expert_geomean",
            f"{len(experts)} experts" if is_english_ui() else f"전문가 {len(experts)}명",
        )

    def _on_apply_equal_weights(self):
        self._rebuild_pairwise_table(saved_pairs={})
        self._set_weight_input_mode("equal")

    def _rebuild_pairwise_table(self, *, saved_pairs: Optional[Dict[Tuple[str, str], float]] = None):
        n = int(len(self._criteria))
        saved = dict(saved_pairs or {})
        self._pairwise = {}
        for i in range(n):
            for j in range(i + 1, n):
                left = str(self._criteria[i].layer_id or "")
                right = str(self._criteria[j].layer_id or "")
                value = saved.get((left, right))
                if value is None:
                    reverse = saved.get((right, left))
                    if reverse is not None:
                        try:
                            reverse_f = float(reverse)
                            value = (1.0 / reverse_f) if reverse_f > 0 else 1.0
                        except Exception:
                            value = 1.0
                try:
                    value_f = float(value) if value is not None else 1.0
                except Exception:
                    value_f = 1.0
                if value_f <= 0 or (not math.isfinite(value_f)):
                    value_f = 1.0
                self._pairwise[(i, j)] = value_f

        self.tblPairwise.clear()
        self.tblPairwise.setRowCount(n)
        self.tblPairwise.setColumnCount(n)

        headers = []
        for c in self._criteria:
            lyr = self._criterion_layer(c)
            name = str(lyr.name() if lyr is not None else ("(Layer)" if is_english_ui() else "(레이어)"))
            headers.append(name[:18] + ("…" if len(name) > 18 else ""))

        self.tblPairwise.setHorizontalHeaderLabels(headers)
        self.tblPairwise.setVerticalHeaderLabels(headers)

        for i in range(n):
            for j in range(n):
                if i == j:
                    item = QtWidgets.QTableWidgetItem("1")
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                    self.tblPairwise.setItem(i, j, item)
                    continue

                if i < j:
                    cmb = QtWidgets.QComboBox()
                    for label, val in _SCALE_OPTIONS:
                        cmb.addItem(label, float(val))
                    current_value = float(self._pairwise.get((i, j), 1.0))
                    current_index = 8
                    for idx_opt, (_label, val) in enumerate(_SCALE_OPTIONS):
                        try:
                            if abs(float(val) - current_value) <= 1e-9:
                                current_index = idx_opt
                                break
                        except Exception:
                            continue
                    cmb.blockSignals(True)
                    cmb.setCurrentIndex(current_index)
                    cmb.blockSignals(False)

                    def _on_changed(_=None, row=i, col=j, w=cmb):
                        try:
                            v = float(w.currentData() or 1.0)
                        except Exception:
                            v = 1.0
                        self._pairwise[(int(row), int(col))] = float(v)
                        self._set_reciprocal_cell(int(row), int(col), float(v))
                        self._mark_manual_weight_edit()
                        self._update_consistency_and_weights()

                    cmb.currentIndexChanged.connect(_on_changed)
                    self.tblPairwise.setCellWidget(i, j, cmb)
                    self._set_reciprocal_cell(i, j, current_value)
                else:
                    item = QtWidgets.QTableWidgetItem("1")
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                    self.tblPairwise.setItem(i, j, item)

        try:
            self.tblPairwise.resizeColumnsToContents()
            self.tblPairwise.resizeRowsToContents()
        except Exception:
            pass
        self._update_consistency_and_weights()

    def _set_reciprocal_cell(self, i: int, j: int, v: float):
        try:
            vv = 1.0 / float(v) if float(v) > 0 else 0.0
        except Exception:
            vv = 1.0

        try:
            label = None
            for s_label, s_val in _SCALE_OPTIONS:
                try:
                    if abs(float(s_val) - float(vv)) <= 1e-9:
                        label = str(s_label)
                        break
                except Exception:
                    continue
            if label is None:
                label = _fmt_float(vv, digits=4)

            item = self.tblPairwise.item(int(j), int(i))
            if item is None:
                item = QtWidgets.QTableWidgetItem(label)
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                self.tblPairwise.setItem(int(j), int(i), item)
            else:
                item.setText(label)
        except Exception:
            pass

    def _on_reset_pairwise(self):
        self._rebuild_pairwise_table()
        self._set_weight_input_mode(
            "manual",
            "Reset all pairwise values to 1." if is_english_ui() else "쌍대비교 값을 모두 1로 초기화했습니다.",
        )

    def _build_pairwise_matrix(self) -> Optional["np.ndarray"]:
        n = int(len(self._criteria))
        if n <= 0 or np is None:
            return None
        mat = np.ones((n, n), dtype=float)
        for (i, j), v in (self._pairwise or {}).items():
            try:
                i0 = int(i)
                j0 = int(j)
                v0 = float(v)
                if i0 == j0:
                    continue
                if v0 <= 0:
                    v0 = 1.0
                mat[i0, j0] = v0
                mat[j0, i0] = 1.0 / v0
            except Exception:
                continue
        return mat

    def _update_consistency_and_weights(self):
        n = int(len(self._criteria))
        if n <= 0:
            self.lblConsistency.setText("CR: -")
            self.lblConsistencyHint.setText(
                "Add criteria to calculate AHP weights and the consistency ratio (CR)."
                if is_english_ui()
                else "기준을 추가하면 AHP 가중치와 일관성(CR)을 계산합니다."
            )
            self._last_lambda_max = None
            self._last_consistency_ratio = None
            return

        mat = self._build_pairwise_matrix()
        if mat is None:
            for c in self._criteria:
                c.weight = 1.0 / float(n)
            self.lblConsistency.setText("CR: - (NumPy unavailable: equal weights)" if is_english_ui() else "CR: - (numpy 없음: 균등 가중치)")
            self.lblConsistencyHint.setText(
                "NumPy is unavailable, so the tool falls back to equal weights instead of the AHP eigenvector solution."
                if is_english_ui()
                else "NumPy를 사용할 수 없어 AHP 고유벡터 대신 균등 가중치로 처리됩니다."
            )
            self._last_lambda_max = None
            self._last_consistency_ratio = None
            self._update_criteria_weight_column()
            return

        w, lam, cr = _ahp_weights_from_matrix(mat)
        self._last_lambda_max = float(lam) if math.isfinite(float(lam)) else None
        self._last_consistency_ratio = float(cr) if math.isfinite(float(cr)) else None
        for i, c in enumerate(self._criteria):
            try:
                c.weight = float(w[i])
            except Exception:
                c.weight = None

        cr_txt = _fmt_float(cr, digits=3) if math.isfinite(float(cr)) else "-"
        lam_txt = _fmt_float(lam, digits=3) if math.isfinite(float(lam)) else "-"
        note = ""
        try:
            if math.isfinite(float(cr)) and float(cr) > 0.10:
                note = " (warning: > 0.10)" if is_english_ui() else " (주의: 0.10 초과)"
        except Exception:
            note = ""
        self.lblConsistency.setText(f"λmax={lam_txt}, CR={cr_txt}{note}")
        self.lblConsistencyHint.setText(_describe_consistency(self._last_consistency_ratio))
        self._update_criteria_weight_column()

    def _update_criteria_weight_column(self):
        try:
            for r, c in enumerate(self._criteria):
                self.tblCriteria.setItem(r, 2, QtWidgets.QTableWidgetItem(_criterion_setting_summary(c)))
                self.tblCriteria.setItem(r, 5, QtWidgets.QTableWidgetItem(_fmt_float(c.weight, digits=6)))
        except Exception:
            pass

    def _extent_for_raster_stats(self, raster: QgsRasterLayer) -> Optional[QgsRectangle]:
        aoi = self.cmbAoi.currentLayer()
        if aoi is None or not isinstance(aoi, QgsVectorLayer):
            return None
        if not self.chkClipToAoiExtent.isChecked():
            return None
        try:
            return _aoi_extent_in_crs(aoi, selected_only=bool(self.chkAoiSelectedOnly.isChecked()), dst_crs=raster.crs())
        except Exception:
            return None

    def _compute_minmax_for_layer(self, raster: QgsRasterLayer) -> Tuple[Optional[float], Optional[float]]:
        if raster is None or not isinstance(raster, QgsRasterLayer):
            return None, None
        try:
            dp = raster.dataProvider()
            extent = self._extent_for_raster_stats(raster)
            stats = dp.bandStatistics(1, QgsRasterBandStats.Min | QgsRasterBandStats.Max, extent or QgsRectangle(), 0)
            mn = float(stats.minimumValue) if stats is not None else None
            mx = float(stats.maximumValue) if stats is not None else None
            if mn is not None and mx is not None and math.isfinite(mn) and math.isfinite(mx):
                return mn, mx
            return None, None
        except Exception:
            return None, None

    def _on_compute_stats(self):
        if not self._criteria:
            return
        for c in self._criteria:
            lyr = self._criterion_layer(c)
            if lyr is None:
                continue
            mn, mx = self._compute_minmax_for_layer(lyr)
            c.min_v = mn
            c.max_v = mx
            self._ensure_criterion_preference_defaults(c)
        self._refresh_criteria_table()
        push_message(self.iface, "AHP", "통계(min/max) 계산 완료", level=0, duration=4)

    def _on_browse_out(self):
        path, _flt = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "AHP 적합도 래스터 저장",
            "ahp_suitability.tif",
            "GeoTIFF (*.tif *.tiff);;All Files (*.*)",
        )
        if not path:
            return
        self.txtOut.setText(str(path))

    def _processing_clip_raster_by_mask(
        self,
        *,
        input_raster,
        mask_layer: QgsVectorLayer,
        out_path: str,
    ) -> str:
        processing.run(
            "gdal:cliprasterbymasklayer",
            {
                "INPUT": input_raster,
                "MASK": mask_layer,
                "NODATA": -9999,
                "DATA_TYPE": 6,  # Float32
                "ALPHA_BAND": False,
                "CROP_TO_CUTLINE": False,
                "KEEP_RESOLUTION": True,
                "OUTPUT": str(out_path),
            },
        )
        return str(out_path)

    def _constraint_summary(self) -> Dict[str, Any]:
        layer = self.cmbConstraint.currentLayer()
        if layer is None:
            return {}
        try:
            layer_type = "raster" if isinstance(layer, QgsRasterLayer) else "vector"
        except Exception:
            layer_type = "layer"
        return {
            "layer_id": str(getattr(layer, "id", lambda: "")() or ""),
            "layer_name": str(getattr(layer, "name", lambda: "")() or ""),
            "layer_type": layer_type,
            "mode": "keep mask > 0" if isinstance(layer, QgsRasterLayer) else "outside nodata",
        }

    def _extract_sample_point(self, feature) -> Optional[QgsPointXY]:
        try:
            geom = feature.geometry()
        except Exception:
            return None
        if geom is None or geom.isEmpty():
            return None
        try:
            if geom.isMultipart():
                pts = geom.asMultiPoint()
                if pts:
                    return QgsPointXY(pts[0])
            pt = geom.asPoint()
            return QgsPointXY(pt)
        except Exception:
            try:
                centroid = geom.centroid()
                if centroid and (not centroid.isEmpty()):
                    return QgsPointXY(centroid.asPoint())
            except Exception:
                return None
        return None

    def _quick_validate_output(self, raster_layer: QgsRasterLayer) -> Dict[str, Any]:
        validation_layer = self.cmbValidation.currentLayer()
        if validation_layer is None or not isinstance(validation_layer, QgsVectorLayer):
            return {}
        try:
            if validation_layer.geometryType() != QgsWkbTypes.PointGeometry:
                return {
                    "layer_id": str(validation_layer.id() or ""),
                    "layer_name": str(validation_layer.name() or ""),
                    "error": "point_geometry_required",
                }
        except Exception:
            return {}
        if raster_layer is None or not isinstance(raster_layer, QgsRasterLayer) or (not raster_layer.isValid()):
            return {}

        try:
            feats = (
                validation_layer.selectedFeatures()
                if self.chkValidationSelectedOnly.isChecked() and validation_layer.selectedFeatureCount() > 0
                else validation_layer.getFeatures()
            )
        except Exception:
            feats = validation_layer.getFeatures()

        ct = None
        try:
            if validation_layer.crs() != raster_layer.crs():
                ct = QgsCoordinateTransform(validation_layer.crs(), raster_layer.crs(), QgsProject.instance())
        except Exception:
            ct = None

        values: List[float] = []
        sampled = 0
        for feat in feats:
            pt = self._extract_sample_point(feat)
            if pt is None:
                continue
            try:
                if ct is not None:
                    pt = ct.transform(pt)
            except Exception:
                continue
            try:
                sampled += 1
                sample = raster_layer.dataProvider().sample(pt, 1)
                if isinstance(sample, tuple):
                    value = sample[0]
                    ok = bool(sample[1]) if len(sample) > 1 else True
                else:
                    value = sample
                    ok = value is not None
                if not ok:
                    continue
                value_f = float(value)
                if math.isfinite(value_f):
                    values.append(value_f)
            except Exception:
                continue

        scale_factor = 100.0 if self.chkScale100.isChecked() else 1.0
        thresholds = (0.50 * scale_factor, 0.70 * scale_factor, 0.90 * scale_factor)
        out: Dict[str, Any] = {
            "layer_id": str(validation_layer.id() or ""),
            "layer_name": str(validation_layer.name() or ""),
            "selected_only": bool(self.chkValidationSelectedOnly.isChecked()),
            "attempted_points": sampled,
            "sample_count": len(values),
            "scale": "0-100" if self.chkScale100.isChecked() else "0-1",
        }
        if not values:
            out["error"] = "no_valid_samples"
            return out

        ordered = sorted(values)
        n = len(ordered)
        mid = n // 2
        median = ordered[mid] if (n % 2) == 1 else (ordered[mid - 1] + ordered[mid]) / 2.0
        out.update(
            {
                "min": ordered[0],
                "max": ordered[-1],
                "mean": sum(ordered) / float(n),
                "median": median,
                "hit_rate_ge_50": sum(1 for v in ordered if v >= thresholds[0]) / float(n),
                "hit_rate_ge_70": sum(1 for v in ordered if v >= thresholds[1]) / float(n),
                "hit_rate_ge_90": sum(1 for v in ordered if v >= thresholds[2]) / float(n),
            }
        )
        return out

    def _validated_score_ranges(self, crit: _Criterion) -> List[Dict[str, float]]:
        rows_in = crit.score_ranges or []
        rows: List[Dict[str, float]] = []
        for row in rows_in:
            try:
                min_v = float(row.get("min"))
                max_v = float(row.get("max"))
                score = float(row.get("score"))
            except Exception:
                continue
            if max_v < min_v:
                min_v, max_v = max_v, min_v
            if not math.isfinite(min_v) or not math.isfinite(max_v) or not math.isfinite(score):
                continue
            score = max(0.0, min(1.0, score))
            rows.append({"min": min_v, "max": max_v, "score": score})
        rows.sort(key=lambda d: (d["min"], d["max"]))
        for idx in range(1, len(rows)):
            prev = rows[idx - 1]
            cur = rows[idx]
            prev_exact = abs(float(prev["max"]) - float(prev["min"])) <= 1e-12
            if cur["min"] < prev["max"] or (prev_exact and abs(float(cur["min"]) - float(prev["max"])) <= 1e-12):
                raise Exception("구간 점수표에 서로 겹치는 구간이 있습니다. 범위를 다시 조정하세요.")
        return rows

    def _criterion_score_formula(self, crit: _Criterion, *, mn: float, mx: float) -> str:
        mode = str(crit.direction or "benefit")
        if mode == "cost":
            return f"({mx} - A) / ({mx} - {mn})"
        if mode == "target":
            target = crit.target_v
            try:
                target0 = float(target) if target is not None else None
            except Exception:
                target0 = None
            if target0 is None or (not math.isfinite(target0)) or target0 <= mn or target0 >= mx:
                target0 = mn + ((mx - mn) / 2.0)
            left_denom = float(target0 - mn)
            right_denom = float(mx - target0)
            if left_denom <= 0 or right_denom <= 0:
                return f"(A - {mn}) / ({mx} - {mn})"
            return (
                f"((A <= {target0}) * ((A - {mn}) / ({target0} - {mn}))) + "
                f"((A > {target0}) * (({mx} - A) / ({mx} - {target0})))"
            )
        if mode == "range":
            try:
                prefer_min = float(crit.prefer_min) if crit.prefer_min is not None else None
                prefer_max = float(crit.prefer_max) if crit.prefer_max is not None else None
            except Exception:
                prefer_min, prefer_max = None, None
        invalid_prefer = any(
            (
                prefer_min is None,
                prefer_max is None,
                not math.isfinite(prefer_min),
                not math.isfinite(prefer_max),
                prefer_min >= prefer_max,
            )
        )
        if invalid_prefer:
            prefer_min = mn + ((mx - mn) * 0.25)
            prefer_max = mn + ((mx - mn) * 0.75)
        if prefer_min <= mn and prefer_max >= mx:
            return "A*0 + 1"
        if prefer_min <= mn:
            if prefer_max >= mx:
                return "A*0 + 1"
            return f"(({mx} - A) / ({mx} - {prefer_max})) * (A > {prefer_max}) + ((A <= {prefer_max}) * 1)"
        if prefer_max >= mx:
            if prefer_min <= mn:
                return "A*0 + 1"
            return f"((A - {mn}) / ({prefer_min} - {mn})) * (A < {prefer_min}) + ((A >= {prefer_min}) * 1)"
        return (
            f"((A < {prefer_min}) * ((A - {mn}) / ({prefer_min} - {mn}))) + "
            f"(((A >= {prefer_min}) * (A <= {prefer_max})) * 1) + "
            f"((A > {prefer_max}) * (({mx} - A) / ({mx} - {prefer_max})))"
        )
        if mode == "reclass":
            rows = self._validated_score_ranges(crit)
            if not rows:
                return "A*0"
            parts: List[str] = []
            for idx, row in enumerate(rows):
                lo = float(row["min"])
                hi = float(row["max"])
                score = float(row["score"])
                if abs(hi - lo) <= 1e-12:
                    parts.append(f"((A == {lo}) * {score})")
                    continue
                is_last = idx == (len(rows) - 1)
                if is_last:
                    parts.append(f"(((A >= {lo}) * (A <= {hi})) * {score})")
                else:
                    parts.append(f"(((A >= {lo}) * (A < {hi})) * {score})")
            return " + ".join(parts) if parts else "A*0"
        return f"(A - {mn}) / ({mx} - {mn})"

    def _processing_warp_to_reference(
        self,
        *,
        input_raster,
        ref_layer: QgsRasterLayer,
        out_path: str,
        extent_str: Optional[str],
        extent_crs_authid: Optional[str],
    ) -> str:
        pixel = None
        try:
            pixel = float(ref_layer.rasterUnitsPerPixelX())
        except Exception:
            pixel = None
        if pixel is None or (not math.isfinite(pixel)) or pixel <= 0:
            pixel = None

        params = {
            "INPUT": input_raster,
            "SOURCE_CRS": None,
            "TARGET_CRS": str(ref_layer.crs().authid() or ""),
            "RESAMPLING": 1,  # bilinear
            "NODATA": None,
            "TARGET_RESOLUTION": pixel,
            "OPTIONS": "",
            "DATA_TYPE": 0,
            "TARGET_EXTENT": extent_str,
            "TARGET_EXTENT_CRS": extent_crs_authid,
            "MULTITHREADING": False,
            "EXTRA": "",
            "OUTPUT": str(out_path),
        }
        processing.run("gdal:warpreproject", params)
        return str(out_path)

    def _processing_raster_calc(
        self,
        *,
        input_a,
        input_b=None,
        formula: str,
        out_path: str,
        rtype: int = 5,  # Float32
    ) -> str:
        params: Dict[str, Any] = {
            "INPUT_A": input_a,
            "BAND_A": 1,
            "FORMULA": str(formula),
            "OUTPUT": str(out_path),
            "RTYPE": int(rtype),
        }
        if input_b:
            params["INPUT_B"] = input_b
            params["BAND_B"] = 1
        processing.run("gdal:rastercalculator", params)
        return str(out_path)

    def _apply_suitability_style(self, layer: QgsRasterLayer):
        if layer is None or not isinstance(layer, QgsRasterLayer) or (not layer.isValid()):
            return
        try:
            shader = QgsRasterShader()
            ramp = QgsColorRampShader()
            ramp.setColorRampType(QgsColorRampShader.Interpolated)
            items = [
                QgsColorRampShader.ColorRampItem(0.0, QColor("#d73027"), "Low"),
                QgsColorRampShader.ColorRampItem(0.5, QColor("#fee08b"), "Mid"),
                QgsColorRampShader.ColorRampItem(1.0, QColor("#1a9850"), "High"),
            ]
            ramp.setColorRampItemList(items)
            shader.setRasterShaderFunction(ramp)
            renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
            layer.setRenderer(renderer)
            layer.triggerRepaint()
        except Exception:
            pass

    def _add_output_to_project(
        self,
        out_path: str,
        *,
        run_id: str,
        cr: Optional[float],
        constraint_info: Optional[Dict[str, Any]] = None,
        validation_summary: Optional[Dict[str, Any]] = None,
    ) -> Optional[QgsRasterLayer]:
        try:
            layer_name = "AHP Suitability"
            try:
                aoi = self.cmbAoi.currentLayer()
                if aoi is not None:
                    layer_name = f"AHP Suitability ({aoi.name()})"
            except Exception:
                pass
            layer = QgsRasterLayer(str(out_path), layer_name)
        except Exception:
            return None

        if layer is None or not layer.isValid():
            return None

        try:
            params = {
                "criteria": [
                    {
                        "layer_id": c.layer_id,
                        "layer_name": (self._criterion_layer(c).name() if self._criterion_layer(c) is not None else ""),
                        "direction": c.direction,
                        "preference_mode": c.direction,
                        "preference_label": _criterion_mode_label(c.direction),
                        "preference_summary": _criterion_setting_summary(c),
                        "min": c.min_v,
                        "max": c.max_v,
                        "target_value": c.target_v,
                        "preferred_min": c.prefer_min,
                        "preferred_max": c.prefer_max,
                        "score_ranges": list(c.score_ranges or []),
                        "weight": c.weight,
                        "archtoolkit_meta": (get_archtoolkit_layer_metadata(self._criterion_layer(c)) if self._criterion_layer(c) is not None else {}),
                    }
                    for c in self._criteria
                ],
                "weight_method": "principal_eigenvector",
                "weight_input_mode": str(self._weight_input_mode or "manual"),
                "weight_input_note": str(self._weight_input_note or ""),
                "suitability_method": "weighted_linear_combination",
                "normalization": {
                    "benefit_formula": "(value - min) / (max - min)",
                    "cost_formula": "(max - value) / (max - min)",
                    "target_formula": "piecewise linear peak at target value",
                    "range_formula": "piecewise linear plateau in preferred range",
                    "reclass_formula": "sum of non-overlapping range conditions * score",
                    "scale_output_0_100": bool(self.chkScale100.isChecked()),
                },
                "pairwise_preferences": [
                    {
                        "left_layer_id": self._criteria[i].layer_id,
                        "left_layer_name": (self._criterion_layer(self._criteria[i]).name() if self._criterion_layer(self._criteria[i]) is not None else ""),
                        "right_layer_id": self._criteria[j].layer_id,
                        "right_layer_name": (self._criterion_layer(self._criteria[j]).name() if self._criterion_layer(self._criteria[j]) is not None else ""),
                        "value": float(v),
                    }
                    for (i, j), v in sorted((self._pairwise or {}).items())
                    if 0 <= int(i) < len(self._criteria) and 0 <= int(j) < len(self._criteria)
                ],
                "lambda_max": self._last_lambda_max,
                "consistency_ratio": self._last_consistency_ratio if self._last_consistency_ratio is not None else cr,
                "clip_to_aoi_extent": bool(self.chkClipToAoiExtent.isChecked()),
                "align_to_first": bool(self.chkAlignToFirst.isChecked()),
                "scale_0_100": bool(self.chkScale100.isChecked()),
            }
            if constraint_info:
                params["constraint_mask"] = dict(constraint_info)
            if validation_summary:
                params["validation_summary"] = dict(validation_summary)
            hierarchy_meta = self._serialized_hierarchy_config()
            if hierarchy_meta:
                params["hierarchy"] = hierarchy_meta
            if str(self._weight_input_mode or "").startswith("expert_geomean") and self._expert_pairwise_inputs:
                params["expert_aggregation"] = {
                    "method": "geometric_mean",
                    "experts": [
                        {
                            "name": str(item.get("name") or ""),
                            "pairs": [
                                {
                                    "left_layer_id": str(k[0] or ""),
                                    "right_layer_id": str(k[1] or ""),
                                    "value": float(v),
                                }
                                for k, v in sorted(dict(item.get("pairs") or {}).items())
                            ],
                        }
                        for item in self._expert_pairwise_inputs
                    ],
                }
            set_archtoolkit_layer_metadata(
                layer,
                tool_id="ahp_suitability",
                run_id=str(run_id),
                kind="suitability",
                units="0-100" if self.chkScale100.isChecked() else "0-1",
                params=params,
            )
        except Exception:
            pass

        project = QgsProject.instance()
        root = project.layerTreeRoot()
        parent_name = get_output_group_name("ahp", "ArchToolkit - AHP")
        parent_group = root.findGroup(parent_name)
        if parent_group is None:
            parent_group = root.insertGroup(0, parent_name)
        try:
            if parent_group.parent() == root:
                idx = root.children().index(parent_group)
                if idx != 0:
                    root.removeChildNode(parent_group)
                    root.insertChildNode(0, parent_group)
        except Exception:
            pass

        try:
            run_group = parent_group.insertGroup(0, f"AHP_{run_id}")
            run_group.setExpanded(False)
        except Exception:
            run_group = parent_group

        try:
            project.addMapLayer(layer, False)
            run_group.insertLayer(0, layer)
        except Exception:
            try:
                project.addMapLayer(layer, True)
            except Exception:
                pass

        self._apply_suitability_style(layer)
        return layer

    def _on_run(self):
        if not self._criteria:
            push_message(self.iface, "오류", "기준(래스터)을 최소 1개 이상 추가하세요.", level=2, duration=6)
            restore_ui_focus(self)
            return

        try:
            ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)
        except Exception:
            pass

        run_id = new_run_id("ahp")
        push_message(self.iface, "AHP", "가중치/통계 계산 중…", level=0, duration=4)

        # 1) Weights
        n = int(len(self._criteria))
        cr = None
        if n == 1:
            self._criteria[0].weight = 1.0
            cr = 0.0
        else:
            mat = self._build_pairwise_matrix()
            if mat is None:
                for c in self._criteria:
                    c.weight = 1.0 / float(n)
                cr = None
            else:
                w, _lam, cr0 = _ahp_weights_from_matrix(mat)
                for i, c in enumerate(self._criteria):
                    try:
                        c.weight = float(w[i])
                    except Exception:
                        c.weight = None
                cr = float(cr0) if math.isfinite(float(cr0)) else None
        self._refresh_criteria_table()

        try:
            if cr is not None and cr > 0.10:
                push_message(self.iface, "주의", f"AHP 일관성비율(CR)이 높습니다: {cr:.3f} (권장 ≤ 0.10)", level=1, duration=8)
        except Exception:
            pass

        # 2) Stats
        for c in self._criteria:
            if c.min_v is not None and c.max_v is not None:
                self._ensure_criterion_preference_defaults(c)
                continue
            lyr = self._criterion_layer(c)
            if lyr is None:
                continue
            mn, mx = self._compute_minmax_for_layer(lyr)
            c.min_v = mn
            c.max_v = mx
            self._ensure_criterion_preference_defaults(c)
        self._refresh_criteria_table()

        # 3) Reference raster
        ref_layer = self._criterion_layer(self._criteria[0])
        if ref_layer is None or not ref_layer.isValid():
            push_message(self.iface, "오류", "첫 번째 기준 레이어를 찾을 수 없습니다.", level=2, duration=7)
            return

        # 4) AOI extent (optional)
        aoi_layer = self.cmbAoi.currentLayer()
        if aoi_layer is not None and isinstance(aoi_layer, QgsVectorLayer):
            try:
                if aoi_layer.geometryType() != QgsWkbTypes.PolygonGeometry:
                    push_message(self.iface, "오류", "AOI는 폴리곤 레이어여야 합니다.", level=2, duration=7)
                    return
            except Exception:
                pass

        extent_str = None
        extent_crs = None
        if self.chkClipToAoiExtent.isChecked() and aoi_layer is not None and isinstance(aoi_layer, QgsVectorLayer):
            try:
                ext = _aoi_extent_in_crs(aoi_layer, selected_only=bool(self.chkAoiSelectedOnly.isChecked()), dst_crs=ref_layer.crs())
                if ext is not None and (not ext.isEmpty()):
                    extent_str = f"{ext.xMinimum()},{ext.xMaximum()},{ext.yMinimum()},{ext.yMaximum()}"
                    extent_crs = str(ref_layer.crs().authid() or "")
            except Exception:
                extent_str = None
                extent_crs = None

        # 5) Output path
        out_path_user = str(self.txtOut.text() or "").strip()
        if out_path_user:
            out_path_user = os.path.abspath(out_path_user)
            if not out_path_user.lower().endswith((".tif", ".tiff")):
                out_path_user = out_path_user + ".tif"
        else:
            out_path_user = os.path.join(tempfile.gettempdir(), f"archtoolkit_ahp_suitability_{run_id}.tif")

        tmp_paths: List[str] = []

        def _tmp(name: str) -> str:
            p = os.path.join(tempfile.gettempdir(), f"archtoolkit_ahp_{name}_{run_id}.tif")
            tmp_paths.append(p)
            return p

        def _safe_rm(path: str):
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

        # 6) Compute suitability
        try:
            push_message(self.iface, "AHP", "래스터 정규화/가중합 계산 중…", level=0, duration=6)

            align = bool(self.chkAlignToFirst.isChecked())
            acc_path = None

            for idx, c in enumerate(self._criteria):
                lyr = self._criterion_layer(c)
                if lyr is None or (not lyr.isValid()):
                    raise Exception("기준 레이어가 유효하지 않습니다.")

                in_path = lyr
                if align:
                    warped = _tmp(f"warp_{idx}")
                    in_path = self._processing_warp_to_reference(
                        input_raster=in_path,
                        ref_layer=ref_layer,
                        out_path=warped,
                        extent_str=extent_str,
                        extent_crs_authid=extent_crs,
                    )

                try:
                    mn = float(c.min_v) if c.min_v is not None else None
                    mx = float(c.max_v) if c.max_v is not None else None
                except Exception:
                    mn, mx = None, None

                if mn is None or mx is None or (not math.isfinite(mn)) or (not math.isfinite(mx)):
                    raise Exception(f"min/max 통계가 없습니다: {lyr.name()}")

                denom = float(mx - mn)
                if (not math.isfinite(denom)) or denom == 0:
                    norm_path = _tmp(f"norm_{idx}")
                    self._processing_raster_calc(input_a=in_path, formula="A*0", out_path=norm_path)
                else:
                    self._ensure_criterion_preference_defaults(c)
                    formula = self._criterion_score_formula(c, mn=mn, mx=mx)
                    norm_path = _tmp(f"norm_{idx}")
                    self._processing_raster_calc(input_a=in_path, formula=formula, out_path=norm_path)

                w0 = float(c.weight) if c.weight is not None else (1.0 / float(n))
                weighted_path = _tmp(f"w_{idx}")
                self._processing_raster_calc(input_a=norm_path, formula=f"A * {w0}", out_path=weighted_path)

                if acc_path is None:
                    acc_path = weighted_path
                else:
                    new_acc = _tmp(f"acc_{idx}")
                    self._processing_raster_calc(input_a=acc_path, input_b=weighted_path, formula="A + B", out_path=new_acc)
                    _safe_rm(acc_path)
                    _safe_rm(weighted_path)
                    acc_path = new_acc

            if acc_path is None:
                raise Exception("가중합 결과를 생성할 수 없습니다.")

            if self.chkScale100.isChecked():
                scaled = _tmp("scaled")
                self._processing_raster_calc(input_a=acc_path, formula="A * 100.0", out_path=scaled)
                _safe_rm(acc_path)
                acc_path = scaled

            constraint_info = self._constraint_summary()
            constraint_layer = self.cmbConstraint.currentLayer()
            if constraint_layer is not None:
                push_message(self.iface, "AHP", "제약 마스크 적용 중…", level=0, duration=4)
                constrained = _tmp("constraint")
                if isinstance(constraint_layer, QgsRasterLayer) and constraint_layer.isValid():
                    constraint_aligned = _tmp("constraint_aligned")
                    mask_path = self._processing_warp_to_reference(
                        input_raster=constraint_layer,
                        ref_layer=ref_layer,
                        out_path=constraint_aligned,
                        extent_str=extent_str,
                        extent_crs_authid=extent_crs,
                    )
                    self._processing_raster_calc(
                        input_a=acc_path,
                        input_b=mask_path,
                        formula="A * (B > 0)",
                        out_path=constrained,
                    )
                    _safe_rm(acc_path)
                    acc_path = constrained
                elif isinstance(constraint_layer, QgsVectorLayer) and constraint_layer.isValid():
                    if constraint_layer.geometryType() != QgsWkbTypes.PolygonGeometry:
                        raise Exception("제약 마스크 벡터는 폴리곤이어야 합니다.")
                    self._processing_clip_raster_by_mask(
                        input_raster=acc_path,
                        mask_layer=constraint_layer,
                        out_path=constrained,
                    )
                    _safe_rm(acc_path)
                    acc_path = constrained
                else:
                    constraint_info = {}

            final_path = out_path_user
            if os.path.abspath(acc_path) != os.path.abspath(final_path):
                try:
                    os.makedirs(os.path.dirname(final_path), exist_ok=True)
                except Exception:
                    pass
                try:
                    if os.path.exists(final_path):
                        os.remove(final_path)
                except Exception:
                    pass
                try:
                    os.replace(acc_path, final_path)
                except Exception:
                    import shutil

                    shutil.copyfile(acc_path, final_path)
            else:
                final_path = acc_path

            validation_summary: Dict[str, Any] = {}
            validation_tmp = QgsRasterLayer(str(final_path), "AHP validation")
            if validation_tmp is not None and validation_tmp.isValid():
                validation_summary = self._quick_validate_output(validation_tmp)

            push_message(self.iface, "AHP", f"완료: {final_path}", level=0, duration=6)

            if validation_summary:
                if validation_summary.get("error") == "point_geometry_required":
                    push_message(self.iface, "AHP 검증", "검증 레이어는 포인트여야 합니다.", level=1, duration=7)
                elif validation_summary.get("error") == "no_valid_samples":
                    push_message(self.iface, "AHP 검증", "검증 포인트에서 적합도 값을 읽지 못했습니다.", level=1, duration=7)
                else:
                    push_message(
                        self.iface,
                        "AHP 검증",
                        (
                            f"{validation_summary.get('sample_count', 0)}개 포인트 샘플링 완료, "
                            f"평균={_fmt_float(validation_summary.get('mean'), digits=3)}, "
                            f"50/70/90% 도달률="
                            f"{_fmt_float(100.0 * float(validation_summary.get('hit_rate_ge_50') or 0.0), digits=1)}/"
                            f"{_fmt_float(100.0 * float(validation_summary.get('hit_rate_ge_70') or 0.0), digits=1)}/"
                            f"{_fmt_float(100.0 * float(validation_summary.get('hit_rate_ge_90') or 0.0), digits=1)}%"
                        ),
                        level=0,
                        duration=8,
                    )

            if self.chkAddToProject.isChecked():
                lyr_out = self._add_output_to_project(
                    final_path,
                    run_id=str(run_id),
                    cr=cr,
                    constraint_info=constraint_info,
                    validation_summary=validation_summary,
                )
                if lyr_out is None:
                    push_message(self.iface, "경고", "결과 레이어를 프로젝트에 추가하지 못했습니다.", level=1, duration=6)

        except Exception as e:
            log_exception("AHP suitability tool error", e)
            push_message(self.iface, "오류", f"AHP 실행 실패: {e}", level=2, duration=10)
            restore_ui_focus(self)
        finally:
            try:
                keep = {os.path.abspath(out_path_user)}
            except Exception:
                keep = set()
            for p in tmp_paths:
                try:
                    ap = os.path.abspath(p)
                    if ap in keep:
                        continue
                    _safe_rm(p)
                except Exception:
                    pass
