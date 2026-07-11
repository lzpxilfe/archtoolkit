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
from qgis.PyQt.QtGui import QColor, QIcon
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

from .live_log_dialog import ensure_live_log_dialog
from .help_dialog import show_help_dialog
from .i18n import is_english_ui
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


def _split_qgis_source_path(src: str) -> str:
    try:
        s = str(src or "")
        return (s.split("|", 1)[0] or "").strip()
    except Exception:
        return str(src or "").strip()


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
    direction: str  # "benefit", "cost", "target", "range" or "reclass"
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


def _sanitize_pair_values(pairs_raw: Any, keys: List[str]) -> Dict[Tuple[str, str], float]:
    """Normalize pairwise comparison values to {(a, b): ratio} with a before b in `keys` order.

    Accepts either a dict keyed by (a, b) tuples/lists, or a list of dicts like
    {"left_group"/"left_layer_id": ..., "right_group"/"right_layer_id": ..., "value": ...}
    (the serialized JSON form). Pairs referencing unknown keys are dropped and
    values are clamped to the Saaty scale [1/9, 9]. Missing pairs default to 1.
    """
    order = {str(k): i for i, k in enumerate(keys or [])}
    out: Dict[Tuple[str, str], float] = {}

    def _put(a: Any, b: Any, v: Any) -> None:
        a0 = str(a or "").strip()
        b0 = str(b or "").strip()
        if a0 not in order or b0 not in order or a0 == b0:
            return
        try:
            v0 = float(v)
        except Exception:
            return
        if not math.isfinite(v0) or v0 <= 0:
            return
        if order[a0] > order[b0]:
            a0, b0 = b0, a0
            v0 = 1.0 / v0
        v0 = max(1.0 / 9.0, min(9.0, v0))
        out[(a0, b0)] = float(v0)

    if isinstance(pairs_raw, dict):
        for key, value in pairs_raw.items():
            if isinstance(key, (tuple, list)) and len(key) == 2:
                _put(key[0], key[1], value)
    elif isinstance(pairs_raw, (list, tuple)):
        for item in pairs_raw:
            if not isinstance(item, dict):
                continue
            left = item.get("left_group", item.get("left_layer_id"))
            right = item.get("right_group", item.get("right_layer_id"))
            _put(left, right, item.get("value"))

    for i, a in enumerate(keys or []):
        for b in list(keys or [])[i + 1:]:
            out.setdefault((str(a), str(b)), 1.0)
    return out


def _matrix_from_pairs(keys: List[str], pairs: Dict[Tuple[str, str], float]) -> Optional["np.ndarray"]:
    n = int(len(keys or []))
    if n <= 0 or np is None:
        return None
    mat = np.ones((n, n), dtype=float)
    index = {str(k): i for i, k in enumerate(keys)}
    for (a, b), v in (pairs or {}).items():
        ia = index.get(str(a))
        ib = index.get(str(b))
        if ia is None or ib is None or ia == ib:
            continue
        try:
            v0 = float(v)
        except Exception:
            continue
        if not math.isfinite(v0) or v0 <= 0:
            continue
        mat[ia, ib] = v0
        mat[ib, ia] = 1.0 / v0
    return mat


def _compute_hierarchy_summary(
    *,
    criteria_rows: List[Tuple[str, str]],
    criterion_groups: Dict[str, str],
    group_pairs: Dict[Tuple[str, str], float],
    local_pairs: Dict[str, Dict[Tuple[str, str], float]],
) -> Dict[str, Any]:
    """Compute hierarchical AHP weights (group level x local level).

    Returns group weights, per-group local weights/CR, global per-criterion
    weights (group weight x local weight) and a synthesized `global_pairwise`
    dict {(id_i, id_j): w_i / w_j} that can seed the flat pairwise table.
    """
    ids = [str(layer_id) for layer_id, _label in (criteria_rows or [])]
    groups: List[str] = []
    for layer_id in ids:
        g = str(criterion_groups.get(layer_id) or "").strip()
        if g and g not in groups:
            groups.append(g)

    group_weights: Dict[str, float] = {}
    group_cr: Optional[float] = None
    mat_g = _matrix_from_pairs(groups, group_pairs or {})
    if mat_g is not None:
        w_g, _lam, cr0 = _ahp_weights_from_matrix(mat_g)
        group_weights = {g: float(w) for g, w in zip(groups, w_g)}
        group_cr = float(cr0) if math.isfinite(float(cr0)) else None
    elif groups:
        group_weights = {g: 1.0 / float(len(groups)) for g in groups}

    local_weights: Dict[str, Dict[str, float]] = {}
    local_cr: Dict[str, Optional[float]] = {}
    for g in groups:
        member_ids = [layer_id for layer_id in ids if str(criterion_groups.get(layer_id) or "") == g]
        if not member_ids:
            continue
        mat_l = _matrix_from_pairs(member_ids, (local_pairs or {}).get(g) or {})
        if mat_l is not None:
            w_l, _lam_l, cr_l = _ahp_weights_from_matrix(mat_l)
            local_weights[g] = {m: float(w) for m, w in zip(member_ids, w_l)}
            local_cr[g] = float(cr_l) if math.isfinite(float(cr_l)) else None
        else:
            local_weights[g] = {m: 1.0 / float(len(member_ids)) for m in member_ids}
            local_cr[g] = None

    global_weights: Dict[str, float] = {}
    for layer_id in ids:
        g = str(criterion_groups.get(layer_id) or "").strip()
        gw = float(group_weights.get(g, 0.0))
        lw = float(local_weights.get(g, {}).get(layer_id, 0.0))
        global_weights[layer_id] = gw * lw

    total = sum(global_weights.values())
    if total > 0:
        global_weights = {k: v / total for k, v in global_weights.items()}

    global_pairwise: Dict[Tuple[str, str], float] = {}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            wa = float(global_weights.get(a, 0.0))
            wb = float(global_weights.get(b, 0.0))
            ratio = (wa / wb) if wb > 0 else 1.0
            if not math.isfinite(ratio) or ratio <= 0:
                ratio = 1.0
            global_pairwise[(a, b)] = max(1.0 / 9.0, min(9.0, ratio))

    return {
        "group_order": list(groups),
        "group_weights": group_weights,
        "group_consistency_ratio": group_cr,
        "local_weights": local_weights,
        "local_consistency_ratio": local_cr,
        "criterion_groups": dict(criterion_groups or {}),
        "global_weights": global_weights,
        "global_pairwise": global_pairwise,
    }


class _CriterionPreferenceDialog(QtWidgets.QDialog):
    """Per-criterion scoring preference editor (benefit/cost/target/range/reclass)."""

    _MODES = [
        ("Benefit(값↑ 좋음)", "benefit"),
        ("Cost(값↓ 좋음)", "cost"),
        ("Target(특정 값 선호)", "target"),
        ("Range(구간 선호)", "range"),
        ("Reclass(구간 점수표)", "reclass"),
    ]

    def __init__(self, *, layer_name: str, criterion: _Criterion, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"선호 설정 - {layer_name}")

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        self.cmbMode = QtWidgets.QComboBox(self)
        for label, value in self._MODES:
            self.cmbMode.addItem(label, value)
        idx = self.cmbMode.findData(str(criterion.direction or "benefit"))
        if idx >= 0:
            self.cmbMode.setCurrentIndex(idx)
        form.addRow("점수 방식:", self.cmbMode)

        def _spin(value: Optional[float]) -> QtWidgets.QDoubleSpinBox:
            sp = QtWidgets.QDoubleSpinBox(self)
            sp.setRange(-1e12, 1e12)
            sp.setDecimals(6)
            try:
                if value is not None and math.isfinite(float(value)):
                    sp.setValue(float(value))
            except Exception:
                pass
            return sp

        self.spinTarget = _spin(criterion.target_v)
        form.addRow("Target 값:", self.spinTarget)
        self.spinPreferMin = _spin(criterion.prefer_min)
        form.addRow("선호 구간 최소:", self.spinPreferMin)
        self.spinPreferMax = _spin(criterion.prefer_max)
        form.addRow("선호 구간 최대:", self.spinPreferMax)

        hint = QtWidgets.QLabel(
            "Target: 값이 목표에 가까울수록 1점, 멀수록 0점.\n"
            "Range: 선호 구간 안은 1점, 밖은 경계에서 멀수록 0점.\n"
            "Reclass: 확인 후 구간 점수표 편집 창이 열립니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#455a64;")

        layout.addLayout(form)
        layout.addWidget(hint)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, parent=self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.cmbMode.currentIndexChanged.connect(self._sync_enabled)
        self._sync_enabled()

    def _sync_enabled(self, _=None):
        mode = str(self.cmbMode.currentData() or "benefit")
        self.spinTarget.setEnabled(mode == "target")
        self.spinPreferMin.setEnabled(mode == "range")
        self.spinPreferMax.setEnabled(mode == "range")

    def values(self) -> Dict[str, Any]:
        mode = str(self.cmbMode.currentData() or "benefit")
        out: Dict[str, Any] = {"direction": mode, "target_v": None, "prefer_min": None, "prefer_max": None}
        if mode == "target":
            out["target_v"] = float(self.spinTarget.value())
        elif mode == "range":
            out["prefer_min"] = float(self.spinPreferMin.value())
            out["prefer_max"] = float(self.spinPreferMax.value())
        return out


class _CriterionReclassDialog(QtWidgets.QDialog):
    """Interval -> score (0-1) table editor for "reclass" criteria."""

    def __init__(self, *, layer_name: str, criterion: _Criterion, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"구간 점수표 - {layer_name}")
        self.resize(420, 360)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("각 구간 [min, max]에 부여할 점수(0~1)를 입력하세요. 구간은 겹치면 안 됩니다."))

        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["min", "max", "score(0~1)"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        rows = list(criterion.score_ranges or [])
        if not rows:
            mn = criterion.min_v if criterion.min_v is not None else 0.0
            mx = criterion.max_v if criterion.max_v is not None else 1.0
            rows = [{"min": float(mn), "max": float(mx), "score": 1.0}]
        for row in rows:
            self._append_row(row.get("min"), row.get("max"), row.get("score"))

        btn_row = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton("행 추가", self)
        btn_add.clicked.connect(lambda: self._append_row(None, None, None))
        btn_del = QtWidgets.QPushButton("선택 행 삭제", self)
        btn_del.clicked.connect(self._remove_selected_rows)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, parent=self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _append_row(self, mn, mx, score):
        r = int(self.table.rowCount())
        self.table.insertRow(r)
        for col, value in enumerate((mn, mx, score)):
            text = "" if value is None else str(value)
            self.table.setItem(r, col, QtWidgets.QTableWidgetItem(text))

    def _remove_selected_rows(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            row = int(self.table.currentRow())
            rows = [row] if row >= 0 else []
        for r in rows:
            if 0 <= r < self.table.rowCount():
                self.table.removeRow(r)

    def values(self) -> List[Dict[str, float]]:
        out: List[Dict[str, float]] = []
        for r in range(int(self.table.rowCount())):
            try:
                mn = float(self.table.item(r, 0).text())
                mx = float(self.table.item(r, 1).text())
                score = float(self.table.item(r, 2).text())
            except Exception:
                continue
            if not (math.isfinite(mn) and math.isfinite(mx) and math.isfinite(score)):
                continue
            if mx < mn:
                mn, mx = mx, mn
            out.append({"min": mn, "max": mx, "score": max(0.0, min(1.0, score))})
        return out


class AhpSuitabilityDialog(QtWidgets.QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._criteria: List[_Criterion] = []
        self._pairwise: Dict[Tuple[int, int], float] = {}
        self._hierarchy_config: Dict[str, Any] = {}
        self._weight_input_mode: str = "flat"
        self._weight_input_note: str = ""
        self._setup_ui()
        self._rebuild_pairwise_table()

    def _set_weight_input_mode(self, mode: str, note: str = "") -> None:
        """Track how weights were provided ("flat" pairwise table or "hierarchy")."""
        self._weight_input_mode = str(mode or "flat")
        self._weight_input_note = str(note or "")
        try:
            if self._weight_input_note:
                self.lblConsistency.setToolTip(self._weight_input_note)
        except Exception:
            pass

    def _setup_ui(self):
        self.setWindowTitle("AHP 입지적합도 (Suitability) - ArchToolkit")
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            for icon_name in ("AHP.png", "ahp.png", "icon.png"):
                icon_path = os.path.join(plugin_dir, icon_name)
                if os.path.exists(icon_path):
                    self.setWindowIcon(QIcon(icon_path))
                    break
        except Exception:
            pass

        layout = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel(
            "<b>AHP 입지적합도</b><br>"
            "만들어진 환경변수(래스터)를 AHP(쌍대비교) 가중치로 통합해 적합도 래스터를 생성합니다.<br>"
            "<i>Tip: AOI를 지정하고 ‘AOI 범위로 자르기’를 켜면 결과가 가벼워집니다.</i><br>"
            "<span style='color:#455a64;'>Reference: Saaty (1980) The Analytic Hierarchy Process</span>"
        )
        header.setWordWrap(True)
        header.setStyleSheet("background:#f1f8e9; padding:10px; border:1px solid #dcedc8; border-radius:4px;")
        layout.addWidget(header)

        grp_in = QtWidgets.QGroupBox("1. 입력")
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
        form.addRow("AOI(선택):", self.cmbAoi)

        self.chkAoiSelectedOnly = QtWidgets.QCheckBox("AOI 선택 피처만 사용")
        form.addRow("", self.chkAoiSelectedOnly)

        self.chkClipToAoiExtent = QtWidgets.QCheckBox("AOI 범위로 자르기(권장)")
        self.chkClipToAoiExtent.setChecked(True)
        form.addRow("", self.chkClipToAoiExtent)

        self.chkAlignToFirst = QtWidgets.QCheckBox("첫 번째 기준 레이어에 정렬(리샘플)")
        self.chkAlignToFirst.setChecked(True)
        form.addRow("", self.chkAlignToFirst)

        layout.addWidget(grp_in)

        # 2) Criteria selection
        grp_crit = QtWidgets.QGroupBox("2. 기준(환경변수) 선택")
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

        self.btnAdd = QtWidgets.QPushButton("추가")
        self.btnAdd.clicked.connect(self._on_add_criterion)
        self.btnRemove = QtWidgets.QPushButton("선택 제거")
        self.btnRemove.clicked.connect(self._on_remove_selected_criteria)
        self.btnStats = QtWidgets.QPushButton("통계 계산(min/max)")
        self.btnStats.clicked.connect(self._on_compute_stats)

        row_add.addWidget(QtWidgets.QLabel("래스터:"))
        row_add.addWidget(self.cmbRaster, 1)
        row_add.addWidget(QtWidgets.QLabel("방향:"))
        row_add.addWidget(self.cmbDirection)
        row_add.addWidget(self.btnAdd)
        row_add.addWidget(self.btnRemove)
        row_add.addWidget(self.btnStats)
        vcrit.addLayout(row_add)

        self.tblCriteria = QtWidgets.QTableWidget()
        self.tblCriteria.setColumnCount(5)
        self.tblCriteria.setHorizontalHeaderLabels(["레이어", "방향", "min", "max", "weight"])
        self.tblCriteria.horizontalHeader().setStretchLastSection(True)
        self.tblCriteria.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tblCriteria.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tblCriteria.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        vcrit.addWidget(self.tblCriteria, 1)

        layout.addWidget(grp_crit, 1)

        # 3) Pairwise comparison
        grp_w = QtWidgets.QGroupBox("3. AHP 가중치(쌍대비교)")
        vw = QtWidgets.QVBoxLayout(grp_w)

        hint = QtWidgets.QLabel(
            "표의 (i, j) 값은 i 기준이 j 기준보다 얼마나 중요한지를 의미합니다.\n"
            "- 1: 동일 중요\n"
            "- 3/5/7/9: 점점 더 중요 (반대로 덜 중요하면 1/3, 1/5 ...)"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#455a64;")
        vw.addWidget(hint)

        self.tblPairwise = QtWidgets.QTableWidget()
        self.tblPairwise.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        vw.addWidget(self.tblPairwise, 1)

        row_w = QtWidgets.QHBoxLayout()
        self.btnResetPairwise = QtWidgets.QPushButton("초기화(모두 1)")
        self.btnResetPairwise.clicked.connect(self._on_reset_pairwise)
        self.lblConsistency = QtWidgets.QLabel("CR: -")
        self.lblConsistency.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        try:
            self.lblConsistency.setToolTip("일관성비율(CR). 일반적으로 CR ≤ 0.10 권장 (Saaty, 1980).")
        except Exception:
            pass
        row_w.addWidget(self.btnResetPairwise)
        row_w.addStretch(1)
        row_w.addWidget(self.lblConsistency)
        vw.addLayout(row_w)

        layout.addWidget(grp_w, 2)

        # 4) Output
        grp_out = QtWidgets.QGroupBox("4. 출력")
        fout = QtWidgets.QFormLayout(grp_out)

        self.txtOut = QtWidgets.QLineEdit()
        self.txtOut.setPlaceholderText("(비우면 임시 파일로 생성 후 프로젝트에 추가)")
        self.btnBrowse = QtWidgets.QPushButton("찾기…")
        self.btnBrowse.clicked.connect(self._on_browse_out)
        w_out = QtWidgets.QWidget()
        h_out = QtWidgets.QHBoxLayout(w_out)
        h_out.setContentsMargins(0, 0, 0, 0)
        h_out.addWidget(self.txtOut, 1)
        h_out.addWidget(self.btnBrowse)
        fout.addRow("출력 GeoTIFF:", w_out)

        self.chkScale100 = QtWidgets.QCheckBox("0–100 스케일로 변환")
        self.chkScale100.setChecked(False)
        fout.addRow("", self.chkScale100)

        self.chkAddToProject = QtWidgets.QCheckBox("완료 후 프로젝트에 추가")
        self.chkAddToProject.setChecked(True)
        fout.addRow("", self.chkAddToProject)

        layout.addWidget(grp_out)

        btn_row = QtWidgets.QHBoxLayout()
        self.btnRun = QtWidgets.QPushButton("실행")
        self.btnRun.clicked.connect(self._on_run)
        self.btnHelp = QtWidgets.QPushButton("도움말")
        self.btnHelp.clicked.connect(self._on_help)
        self.btnClose = QtWidgets.QPushButton("닫기")
        self.btnClose.clicked.connect(self.reject)
        btn_row.addWidget(self.btnRun)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btnHelp)
        btn_row.addWidget(self.btnClose)
        layout.addLayout(btn_row)

        self.resize(920, 720)

    def _on_help(self):
        html = """
<h3>AHP 입지분석(적합도) 도움말</h3>
<p>
여러 환경 래스터(기준)를 AHP(쌍대비교) 가중치로 결합해 하나의 적합도 래스터를 만듭니다.
</p>

<h4>작업 흐름</h4>
<ol>
  <li><b>AOI</b>를 선택합니다(선택). 범위/해상도를 통일하고 싶을 때 유용합니다.</li>
  <li><b>기준(criterion)</b>으로 사용할 래스터들을 추가하고, Benefit/Cost 방향을 지정합니다.</li>
  <li><b>쌍대비교</b> 테이블에서 중요도를 입력합니다(사티(Saaty) 1–9 척도).</li>
  <li><b>CR(일관성비율)</b>을 확인하고(권장 CR ≤ 0.10), 실행합니다.</li>
  <li>(옵션) 결과를 0–100 스케일로 변환해 시각화/보고에 사용합니다.</li>
</ol>

<h4>주의/팁</h4>
<ul>
  <li>기준 래스터의 <b>CRS/해상도/NoData</b>가 다르면 결과가 왜곡될 수 있습니다.</li>
  <li>값이 “낮을수록 유리”한 기준(예: 경사, 거리)은 <b>Cost(값↓)</b>로 지정하세요.</li>
  <li>쌍대비교가 어려우면 먼저 3~5개 기준으로 시작해 점진적으로 늘리는 것을 권장합니다.</li>
</ul>
"""
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            show_help_dialog(parent=self, title="AHP 적합도 도움말", html=html, plugin_dir=plugin_dir)
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
            # `or` short-circuits so isfinite() never sees None.
            invalid_range = (
                pmin0 is None
                or pmax0 is None
                or not math.isfinite(pmin0)
                or not math.isfinite(pmax0)
                or pmin0 >= pmax0
                or pmin0 < mn
                or pmax0 > mx
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
        self._criteria.append(_Criterion(layer_id=lid, direction=direction))
        self._refresh_criteria_table()
        self._rebuild_pairwise_table()

    def _on_remove_selected_criteria(self):
        rows = sorted({idx.row() for idx in self.tblCriteria.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            return
        try:
            for r in rows:
                if 0 <= r < len(self._criteria):
                    del self._criteria[r]
        except Exception:
            pass
        self._refresh_criteria_table()
        self._rebuild_pairwise_table()

    def _refresh_criteria_table(self):
        self.tblCriteria.setRowCount(0)
        for i, crit in enumerate(self._criteria):
            lyr = self._criterion_layer(crit)
            name = str(lyr.name() if lyr is not None else "(레이어 없음)")

            self.tblCriteria.insertRow(i)

            it = QtWidgets.QTableWidgetItem(name)
            it.setData(Qt.UserRole, str(crit.layer_id))
            self.tblCriteria.setItem(i, 0, it)

            cmb = QtWidgets.QComboBox()
            cmb.addItem("Benefit(값↑)", "benefit")
            cmb.addItem("Cost(값↓)", "cost")
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
                except Exception:
                    pass

            cmb.currentIndexChanged.connect(_on_dir_changed)
            self.tblCriteria.setCellWidget(i, 1, cmb)

            self.tblCriteria.setItem(i, 2, QtWidgets.QTableWidgetItem(_fmt_float(crit.min_v)))
            self.tblCriteria.setItem(i, 3, QtWidgets.QTableWidgetItem(_fmt_float(crit.max_v)))
            self.tblCriteria.setItem(i, 4, QtWidgets.QTableWidgetItem(_fmt_float(crit.weight, digits=6)))

        try:
            self.tblCriteria.resizeColumnsToContents()
        except Exception:
            pass

        self._update_consistency_and_weights()

    def _rebuild_pairwise_table(self, saved_pairs: Optional[Dict[Tuple[str, str], float]] = None):
        n = int(len(self._criteria))
        self._pairwise = {(i, j): 1.0 for i in range(n) for j in range(i + 1, n)}

        # Optionally seed values from a {(layer_id_a, layer_id_b): ratio} dict
        # (e.g. the global pairwise synthesized from a hierarchical AHP config).
        if saved_pairs:
            id_to_idx = {str(c.layer_id): i for i, c in enumerate(self._criteria)}
            for key, value in dict(saved_pairs).items():
                if not (isinstance(key, (tuple, list)) and len(key) == 2):
                    continue
                ia = id_to_idx.get(str(key[0]))
                ib = id_to_idx.get(str(key[1]))
                if ia is None or ib is None or ia == ib:
                    continue
                try:
                    v = float(value)
                except Exception:
                    continue
                if not math.isfinite(v) or v <= 0:
                    continue
                if ia > ib:
                    ia, ib = ib, ia
                    v = 1.0 / v
                self._pairwise[(ia, ib)] = float(v)

        self.tblPairwise.clear()
        self.tblPairwise.setRowCount(n)
        self.tblPairwise.setColumnCount(n)

        headers = []
        for c in self._criteria:
            lyr = self._criterion_layer(c)
            name = str(lyr.name() if lyr is not None else "(레이어)")
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
                    # Select the scale option nearest to the (possibly seeded) value.
                    try:
                        v_saved = float(self._pairwise.get((i, j), 1.0))
                        best_k, best_d = 8, None
                        for k in range(cmb.count()):
                            d = abs(float(cmb.itemData(k)) - v_saved)
                            if best_d is None or d < best_d:
                                best_k, best_d = k, d
                        cmb.setCurrentIndex(int(best_k))
                        self._pairwise[(i, j)] = float(cmb.currentData() or 1.0)
                    except Exception:
                        cmb.setCurrentIndex(8)  # "1"

                    def _on_changed(_=None, row=i, col=j, w=cmb):
                        try:
                            v = float(w.currentData() or 1.0)
                        except Exception:
                            v = 1.0
                        self._pairwise[(int(row), int(col))] = float(v)
                        self._set_reciprocal_cell(int(row), int(col), float(v))
                        self._update_consistency_and_weights()

                    cmb.currentIndexChanged.connect(_on_changed)
                    self.tblPairwise.setCellWidget(i, j, cmb)
                else:
                    item = QtWidgets.QTableWidgetItem("1")
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                    self.tblPairwise.setItem(i, j, item)

        # Reciprocal cells are plain items created above; sync them to the
        # (possibly seeded) upper-triangle values once the grid exists.
        for (pi, pj), pv in dict(self._pairwise).items():
            try:
                if abs(float(pv) - 1.0) > 1e-12:
                    self._set_reciprocal_cell(int(pi), int(pj), float(pv))
            except Exception:
                continue

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
            return

        mat = self._build_pairwise_matrix()
        if mat is None:
            for c in self._criteria:
                c.weight = 1.0 / float(n)
            self.lblConsistency.setText("CR: - (numpy 없음: 균등 가중치)")
            self._update_criteria_weight_column()
            return

        w, lam, cr = _ahp_weights_from_matrix(mat)
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
                note = " (주의: 0.10 초과)"
        except Exception:
            note = ""
        self.lblConsistency.setText(f"λmax={lam_txt}, CR={cr_txt}{note}")
        self._update_criteria_weight_column()

    def _update_criteria_weight_column(self):
        try:
            for r, c in enumerate(self._criteria):
                self.tblCriteria.setItem(r, 4, QtWidgets.QTableWidgetItem(_fmt_float(c.weight, digits=6)))
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
        # The constraint-layer picker is not part of the current UI yet.
        combo = getattr(self, "cmbConstraint", None)
        layer = combo.currentLayer() if combo is not None else None
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
        # The validation-layer picker is not part of the current UI yet.
        combo = getattr(self, "cmbValidation", None)
        validation_layer = combo.currentLayer() if combo is not None else None
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
                if bool(getattr(self, "chkValidationSelectedOnly", None) and self.chkValidationSelectedOnly.isChecked())
                and validation_layer.selectedFeatureCount() > 0
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
            "selected_only": bool(getattr(self, "chkValidationSelectedOnly", None) and self.chkValidationSelectedOnly.isChecked()),
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
            # `or` short-circuits so isfinite() never sees None.
            invalid_prefer = (
                prefer_min is None
                or prefer_max is None
                or not math.isfinite(prefer_min)
                or not math.isfinite(prefer_max)
                or prefer_min >= prefer_max
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
        input_path: str,
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
            "INPUT": str(input_path),
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
        input_a: str,
        input_b: Optional[str] = None,
        formula: str,
        out_path: str,
        rtype: int = 5,  # Float32
    ) -> str:
        params: Dict[str, Any] = {
            "INPUT_A": str(input_a),
            "BAND_A": 1,
            "FORMULA": str(formula),
            "OUTPUT": str(out_path),
            "RTYPE": int(rtype),
        }
        if input_b:
            params["INPUT_B"] = str(input_b)
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

    def _add_output_to_project(self, out_path: str, *, run_id: str, cr: Optional[float]) -> Optional[QgsRasterLayer]:
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
                        "min": c.min_v,
                        "max": c.max_v,
                        "weight": c.weight,
                        "archtoolkit_meta": (get_archtoolkit_layer_metadata(self._criterion_layer(c)) if self._criterion_layer(c) is not None else {}),
                    }
                    for c in self._criteria
                ],
                "consistency_ratio": cr,
                "clip_to_aoi_extent": bool(self.chkClipToAoiExtent.isChecked()),
                "align_to_first": bool(self.chkAlignToFirst.isChecked()),
                "scale_0_100": bool(self.chkScale100.isChecked()),
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
        parent_name = "ArchToolkit - AHP"
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
                continue
            lyr = self._criterion_layer(c)
            if lyr is None:
                continue
            mn, mx = self._compute_minmax_for_layer(lyr)
            c.min_v = mn
            c.max_v = mx
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

                src0 = _split_qgis_source_path(lyr.source())
                if not src0:
                    raise Exception("래스터 소스 경로를 읽을 수 없습니다.")

                in_path = src0
                if align:
                    warped = _tmp(f"warp_{idx}")
                    in_path = self._processing_warp_to_reference(
                        input_path=in_path,
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
                    if str(c.direction or "benefit") == "cost":
                        formula = f"({mx} - A) / ({mx} - {mn})"
                    else:
                        formula = f"(A - {mn}) / ({mx} - {mn})"
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

            push_message(self.iface, "AHP", f"완료: {final_path}", level=0, duration=6)

            if self.chkAddToProject.isChecked():
                lyr_out = self._add_output_to_project(final_path, run_id=str(run_id), cr=cr)
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
