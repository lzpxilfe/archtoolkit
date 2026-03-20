# -*- coding: utf-8 -*-
"""
AI AOI Report tool for ArchToolkit.

Summarizes the situation within a radius around an AOI polygon by scanning
project layers (preferably ArchToolkit outputs) and generates a Korean narrative
report. Supports a free/local mode and optional Gemini API mode.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import List, Optional, Set

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QSettings, Qt

from qgis.core import QgsLayerTreeGroup, QgsMapLayerProxyModel, QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.gui import QgsMapLayerComboBox  # noqa: F401 (needed for custom widget)

from . import ai_aoi_summary
from . import ai_gemini
from . import ai_local_summarizer
from .help_dialog import show_help_dialog
from .i18n import is_english_ui, tr
from .live_log_dialog import ensure_live_log_dialog
from .ui_helpers import apply_hint_label_style, create_hint_label, set_plugin_window_icon
from .utils import log_message, push_message, restore_ui_focus


_SETTINGS_PREFIX = "ArchToolkit/ai/report"
_PROJECT_CACHE_INVALIDATION_SIGNALS = ("layersAdded", "layersRemoved", "cleared")
_LAYER_CACHE_INVALIDATION_SIGNALS = (
    "selectionChanged",
    "attributeValueChanged",
    "featureAdded",
    "featureDeleted",
    "updatedFields",
    "dataChanged",
    "styleChanged",
    "nameChanged",
    "layerModified",
)


class _LayerMultiSelectDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent=None,
        *,
        aoi_layer_id: str,
        preselected_ids: Optional[List[str]] = None,
    ):
        super().__init__(parent)
        self._aoi_layer_id = str(aoi_layer_id or "")
        self._preselected = set(str(x) for x in (preselected_ids or []) if str(x or "").strip())

        self.setWindowTitle("Select Target Layers - AI AOI Report" if is_english_ui() else "대상 레이어 선택 - AI 조사요약")
        self._setup_ui()
        self._populate()
        self._apply_filter("")

    def _setup_ui(self):
        english = is_english_ui()
        self.setMinimumSize(760, 620)
        layout = QtWidgets.QVBoxLayout(self)

        hint = QtWidgets.QLabel(
            (
                "Select the layers to summarize within the AOI radius.\n"
                "- Only vector and raster layers are listed.\n"
                "- The AOI layer itself is excluded automatically."
            )
            if english
            else
            (
                "AOI 반경 내에서 요약할 레이어를 선택하세요.\n"
                "- 벡터/래스터 레이어만 표시됩니다.\n"
                "- AOI 레이어는 자동으로 제외됩니다."
            )
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#455a64;")
        layout.addWidget(hint)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Filter:" if english else "필터:"))
        self.txtFilter = QtWidgets.QLineEdit()
        self.txtFilter.setPlaceholderText("Search by layer/group name…" if english else "레이어/그룹 이름으로 검색…")
        self.txtFilter.textChanged.connect(self._apply_filter)
        row.addWidget(self.txtFilter, 1)
        layout.addLayout(row)

        self.listLayers = QtWidgets.QListWidget()
        self.listLayers.setAlternatingRowColors(True)
        self.listLayers.itemChanged.connect(lambda *_args: self._update_selection_summary())
        layout.addWidget(self.listLayers, 1)

        self.lblSelectionSummary = QtWidgets.QLabel("Checking candidate layers..." if english else "후보 레이어를 확인하는 중입니다.")
        self.lblSelectionSummary.setWordWrap(True)
        self.lblSelectionSummary.setStyleSheet("color:#455a64;")
        layout.addWidget(self.lblSelectionSummary)

        quick = QtWidgets.QHBoxLayout()
        self.btnCheckVisible = QtWidgets.QPushButton("Select all visible" if english else "보이는 것 전체 선택")
        self.btnCheckVisible.clicked.connect(lambda: self._set_all_checked(True, visible_only=True))
        self.btnUncheckVisible = QtWidgets.QPushButton("Clear all visible" if english else "보이는 것 전체 해제")
        self.btnUncheckVisible.clicked.connect(lambda: self._set_all_checked(False, visible_only=True))
        quick.addWidget(self.btnCheckVisible)
        quick.addWidget(self.btnUncheckVisible)
        quick.addStretch(1)
        layout.addLayout(quick)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self):
        self.listLayers.clear()
        layers = list(QgsProject.instance().mapLayers().values())
        for lyr in layers:
            if lyr is None:
                continue
            if lyr.id() == self._aoi_layer_id:
                continue
            if not isinstance(lyr, (QgsVectorLayer, QgsRasterLayer)):
                continue

            group_path = ""
            try:
                group_path = str(ai_aoi_summary._layer_group_path(lyr.id()) or "")
            except Exception:
                group_path = ""

            kind = "V" if isinstance(lyr, QgsVectorLayer) else "R"
            text = f"[{kind}] {lyr.name()}"
            if group_path:
                text = f"{group_path} / {text}"

            item = QtWidgets.QListWidgetItem(text)
            item.setData(Qt.UserRole, lyr.id())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if lyr.id() in self._preselected else Qt.Unchecked)
            self.listLayers.addItem(item)
        self._update_selection_summary()

    def _apply_filter(self, text: str):
        q = str(text or "").strip().lower()
        for i in range(self.listLayers.count()):
            item = self.listLayers.item(i)
            if not q:
                item.setHidden(False)
                continue
            item.setHidden(q not in str(item.text() or "").lower())
        self._update_selection_summary()

    def _set_all_checked(self, checked: bool, *, visible_only: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.listLayers.count()):
            item = self.listLayers.item(i)
            if visible_only and item.isHidden():
                continue
            item.setCheckState(state)
        self._update_selection_summary()

    def _update_selection_summary(self):
        english = is_english_ui()
        total = int(self.listLayers.count())
        visible = 0
        checked = 0
        names: List[str] = []
        for i in range(total):
            item = self.listLayers.item(i)
            if item is None:
                continue
            if not item.isHidden():
                visible += 1
            if item.checkState() != Qt.Checked:
                continue
            checked += 1
            if len(names) < 20:
                text = str(item.text() or "").strip()
                if text:
                    names.append(text)
        if english:
            text = f"{visible} currently visible layers out of {total} candidates"
            if checked > 0:
                text += f" / {checked} selected"
            else:
                text += " / none selected yet"
        else:
            text = f"후보 {total}개 중 현재 보이는 레이어 {visible}개"
            if checked > 0:
                text += f" / 선택 {checked}개"
            else:
                text += " / 아직 선택 없음"
        self.lblSelectionSummary.setText(text)
        self.lblSelectionSummary.setToolTip("\n".join(names))

    def selected_layer_ids(self) -> List[str]:
        ids: List[str] = []
        for i in range(self.listLayers.count()):
            item = self.listLayers.item(i)
            if item.checkState() != Qt.Checked:
                continue
            lid = str(item.data(Qt.UserRole) or "").strip()
            if lid and lid not in ids:
                ids.append(lid)
        return ids


class AiAoiReportDialog(QtWidgets.QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._selected_layer_ids: List[str] = []
        self._last_ctx: Optional[dict] = None
        self._last_ctx_key = None
        self._ctx_revision = 0
        self._observed_layer_ids: Set[str] = set()
        self._last_verified_models: List[str] = []
        self._last_models_verified_at: str = ""
        self._last_report_text: str = ""
        self._last_report_ctx_key = None
        self._last_provider: str = ""
        self._last_model: str = ""
        self._last_generated_at: str = ""
        self._setup_ui()
        self._connect_cache_invalidation_signals()
        self._update_provider_ui()
        self._refresh_key_status()
        self._refresh_group_list()
        self._update_layer_scope_ui()

    def _invalidate_ctx_cache(self, *_args) -> None:
        self._last_ctx = None
        self._last_ctx_key = None
        self._ctx_revision += 1

    def _connect_cache_invalidation_signals(self) -> None:
        project = QgsProject.instance()
        for signal_name in _PROJECT_CACHE_INVALIDATION_SIGNALS:
            signal = getattr(project, signal_name, None)
            if signal is None:
                continue
            try:
                signal.connect(self._on_project_layers_changed)
            except Exception:
                pass
        self._refresh_layer_observers()

    def _disconnect_cache_invalidation_signals(self) -> None:
        project = QgsProject.instance()
        for signal_name in _PROJECT_CACHE_INVALIDATION_SIGNALS:
            signal = getattr(project, signal_name, None)
            if signal is None:
                continue
            try:
                signal.disconnect(self._on_project_layers_changed)
            except Exception:
                pass
        for layer_id in list(self._observed_layer_ids):
            layer = project.mapLayer(layer_id)
            if layer is None:
                continue
            self._disconnect_layer_signals(layer)
        self._observed_layer_ids.clear()

    def _connect_layer_signals(self, layer) -> None:
        if layer is None:
            return
        for signal_name in _LAYER_CACHE_INVALIDATION_SIGNALS:
            signal = getattr(layer, signal_name, None)
            if signal is None:
                continue
            try:
                signal.connect(self._on_observed_layer_changed)
            except Exception:
                pass

    def _disconnect_layer_signals(self, layer) -> None:
        if layer is None:
            return
        for signal_name in _LAYER_CACHE_INVALIDATION_SIGNALS:
            signal = getattr(layer, signal_name, None)
            if signal is None:
                continue
            try:
                signal.disconnect(self._on_observed_layer_changed)
            except Exception:
                pass

    def _refresh_layer_observers(self) -> None:
        project = QgsProject.instance()
        for layer_id in list(self._observed_layer_ids):
            layer = project.mapLayer(layer_id)
            if layer is not None:
                self._disconnect_layer_signals(layer)
        self._observed_layer_ids.clear()

        for layer in project.mapLayers().values():
            self._connect_layer_signals(layer)
            try:
                self._observed_layer_ids.add(str(layer.id() or ""))
            except Exception:
                continue

    def _on_observed_layer_changed(self, *_args) -> None:
        self._invalidate_ctx_cache()

    def _on_project_layers_changed(self, *_args) -> None:
        self._refresh_layer_observers()
        self._invalidate_ctx_cache()
        try:
            self._refresh_group_list()
        except Exception:
            pass
        try:
            self._update_selected_layers_label()
        except Exception:
            pass
        try:
            self._refresh_scope_summary()
        except Exception:
            pass

    def done(self, result: int) -> None:
        self._disconnect_cache_invalidation_signals()
        super().done(result)

    def _settings_get(self, key: str, default=None):
        try:
            return QSettings().value(f"{_SETTINGS_PREFIX}/{key}", default)
        except Exception:
            return default

    def _settings_set(self, key: str, value) -> None:
        try:
            QSettings().setValue(f"{_SETTINGS_PREFIX}/{key}", value)
        except Exception:
            pass

    def _update_model_field_hint(self) -> None:
        default_model = ai_gemini.get_default_model_name()
        english = is_english_ui()
        self.txtModel.setPlaceholderText(f"{'e.g.' if english else '예'}: {default_model}")

        known_models = list(self._last_verified_models or ai_gemini.get_known_models())
        verified_at = str(self._last_models_verified_at or ai_gemini.get_known_models_verified_at() or "").strip()
        is_stale = ai_gemini.is_known_models_catalog_stale(verified_at)
        if known_models:
            tip = "Recently verified official Gemini model IDs" if english else "최근 확인된 공식 Gemini 모델 ID"
            if is_stale:
                tip = "Saved/built-in Gemini model IDs" if english else "저장된/내장 Gemini 모델 ID"
            if verified_at:
                tip += f" ({'verified on' if english else '확인일'} {verified_at})"
            if is_stale:
                tip += (
                    "\nThis catalog is old enough that re-verifying is safer."
                    if english
                    else "\n이 목록은 확인일이 오래되어 다시 검증하는 편이 안전합니다."
                )
            tip += ":\n- " + "\n- ".join(known_models)
            self.txtModel.setToolTip(tip)

            try:
                completer = QtWidgets.QCompleter(known_models, self)
                completer.setCaseSensitivity(Qt.CaseInsensitive)
                if hasattr(completer, "setFilterMode"):
                    completer.setFilterMode(Qt.MatchContains)
                self.txtModel.setCompleter(completer)
            except Exception:
                pass
            return

        self.txtModel.setToolTip("")

    def _refresh_model_status(self) -> None:
        if self._get_provider() != "gemini":
            self.lblModelStatus.setText(
                "Gemini model settings are not used in local summary mode."
                if is_english_ui()
                else "현재는 로컬 요약 모드라 Gemini 모델 설정을 사용하지 않습니다."
            )
            self.lblModelStatus.setStyleSheet("color:#455a64;")
            return

        verified_models = list(self._last_verified_models or ai_gemini.get_known_models())
        verified_at = str(self._last_models_verified_at or ai_gemini.get_known_models_verified_at() or "").strip()
        level, message = ai_gemini.describe_model_status(
            str(self.txtModel.text() or "").strip(),
            verified_models=verified_models,
            verified_at=verified_at,
        )
        color = "#455a64"
        if level == "ok":
            color = "#2e7d32"
        elif level == "warning":
            color = "#ef6c00"
        self.lblModelStatus.setText(message)
        self.lblModelStatus.setStyleSheet(f"color:{color};")

    def _get_provider(self) -> str:
        try:
            v = self.cmbProvider.currentData()
            return str(v or "").strip() or "local"
        except Exception:
            return "local"

    def _get_layer_scope(self) -> str:
        try:
            v = self.cmbLayerScope.currentData()
            return str(v or "").strip() or "auto"
        except Exception:
            return "auto"

    def _get_target_group_path(self) -> str:
        try:
            v = self.cmbTargetGroup.currentData()
            return str(v or "").strip()
        except Exception:
            return ""

    def _setup_ui(self):
        english = is_english_ui()
        self.setWindowTitle("AI AOI Report - ArchToolkit" if english else "AI 조사요약 (AOI Report) - ArchToolkit")
        set_plugin_window_icon(self, ("AI.png", "ai.png", "icon.png"))
        self.resize(920, 760)

        layout = QtWidgets.QVBoxLayout(self)

        self.scrollArea = QtWidgets.QScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        layout.addWidget(self.scrollArea, 1)

        self.scrollContent = QtWidgets.QWidget(self.scrollArea)
        self.scrollArea.setWidget(self.scrollContent)
        content_layout = QtWidgets.QVBoxLayout(self.scrollContent)
        content_layout.setContentsMargins(0, 0, 0, 0)

        header = QtWidgets.QLabel(
            (
                "<b>AI AOI Report</b><br>"
                "Summarizes project layers within a radius around the Area of Interest (AOI), especially ArchToolkit outputs,<br>"
                "and turns them into report-style notes.<br>"
                "<i>Modes: Free (local summary) or Gemini (API)</i><br>"
                "<i>Note: AI/generated summaries are for reference only and must be reviewed by the user.</i>"
            )
            if english
            else
            (
                "<b>AI 조사요약</b><br>"
                "조사지역(AOI) 반경 내의 프로젝트 레이어(특히 ArchToolkit 결과)를 요약하고,<br>"
                "보고서/업무 메모 형태의 문장으로 정리합니다.<br>"
                "<i>모드: 무료(로컬 요약) 또는 Gemini(API)</i><br>"
                "<i>주의: AI/요약 결과는 참고용이며, 반드시 사용자가 검토해야 합니다.</i>"
            )
        )
        header.setWordWrap(True)
        header.setStyleSheet("background:#e3f2fd; padding:10px; border:1px solid #bbdefb; border-radius:4px;")
        content_layout.addWidget(header)

        help_row = QtWidgets.QHBoxLayout()
        help_row.addStretch(1)
        self.btnHelp = QtWidgets.QPushButton("Help" if english else "도움말")
        self.btnHelp.clicked.connect(self._on_help)
        help_row.addWidget(self.btnHelp)
        content_layout.addLayout(help_row)

        grp_in = QtWidgets.QGroupBox("1. Inputs" if english else "1. 입력")
        form = QtWidgets.QFormLayout(grp_in)

        self.cmbAoi = QgsMapLayerComboBox(grp_in)
        # QGIS API compatibility: Filter may be scoped or unscoped depending on build.
        try:
            poly_filter = QgsMapLayerProxyModel.Filter.PolygonLayer
        except Exception:
            poly_filter = QgsMapLayerProxyModel.PolygonLayer
        self.cmbAoi.setFilters(poly_filter)
        form.addRow("AOI polygon:" if english else "조사지역 폴리곤(AOI):", self.cmbAoi)

        self.chkSelectedOnly = QtWidgets.QCheckBox("Use selected features only" if english else "선택된 피처만 사용")
        form.addRow("", self.chkSelectedOnly)

        self.spinRadius = QtWidgets.QDoubleSpinBox(grp_in)
        self.spinRadius.setDecimals(0)
        self.spinRadius.setRange(1.0, 1_000_000.0)
        self.spinRadius.setValue(1000.0)
        self.spinRadius.setSingleStep(100.0)
        self.spinRadius.setSuffix(" m")
        form.addRow("Radius:" if english else "반경:", self.spinRadius)

        self.chkOnlyArchToolkit = QtWidgets.QCheckBox("Summarize ArchToolkit result layers only (recommended)" if english else "ArchToolkit 결과 레이어만 요약(권장)")
        self.chkOnlyArchToolkit.setChecked(True)
        form.addRow("", self.chkOnlyArchToolkit)

        self.chkExcludeStyling = QtWidgets.QCheckBox(
            "Exclude map/style (cartography) result layers (recommended)"
            if english
            else "도면/Style(카토그래피) 결과 레이어 제외(권장)"
        )
        self.chkExcludeStyling.setChecked(True)
        form.addRow("", self.chkExcludeStyling)

        self.cmbLayerScope = QtWidgets.QComboBox()
        self.cmbLayerScope.addItem("Auto (scan with current options)", "auto")
        self.cmbLayerScope.addItem("Choose group (layer group)", "group")
        self.cmbLayerScope.addItem("Choose layers directly", "layers")
        saved_scope = str(self._settings_get("layer_scope", "auto") or "").strip() or "auto"
        try:
            idx = self.cmbLayerScope.findData(saved_scope)
            if idx >= 0:
                self.cmbLayerScope.setCurrentIndex(idx)
        except Exception:
            pass
        self.cmbLayerScope.currentIndexChanged.connect(self._on_layer_scope_changed)
        form.addRow("Target scope:" if english else "대상 레이어:", self.cmbLayerScope)

        self.cmbTargetGroup = QtWidgets.QComboBox()
        self.cmbTargetGroup.currentIndexChanged.connect(self._on_target_group_changed)
        self.btnRefreshGroups = QtWidgets.QPushButton("Refresh" if english else "새로고침")
        self.btnRefreshGroups.clicked.connect(self._refresh_group_list)
        w_group = QtWidgets.QWidget()
        row_group = QtWidgets.QHBoxLayout(w_group)
        row_group.setContentsMargins(0, 0, 0, 0)
        row_group.addWidget(self.cmbTargetGroup, 1)
        row_group.addWidget(self.btnRefreshGroups)
        form.addRow("Target group:" if english else "대상 그룹:", w_group)

        self.btnSelectLayers = QtWidgets.QPushButton("Select layers…" if english else "레이어 선택…")
        self.btnSelectLayers.clicked.connect(self._on_select_layers)
        self.btnClearLayers = QtWidgets.QPushButton("Clear" if english else "초기화")
        self.btnClearLayers.clicked.connect(self._on_clear_layers)
        self.lblSelectedLayers = QtWidgets.QLabel("None selected" if english else "선택 없음")
        self.lblSelectedLayers.setStyleSheet("color:#455a64;")

        w_layers = QtWidgets.QWidget()
        row_layers = QtWidgets.QHBoxLayout(w_layers)
        row_layers.setContentsMargins(0, 0, 0, 0)
        row_layers.addWidget(self.btnSelectLayers)
        row_layers.addWidget(self.btnClearLayers)
        row_layers.addWidget(self.lblSelectedLayers, 1)
        form.addRow("Target layers:" if english else "대상 레이어:", w_layers)

        content_layout.addWidget(grp_in)

        self.lblScopeSummary = create_hint_label(
            "Checking the current scan scope..." if english else "현재 스캔 범위를 확인하는 중입니다.",
            tone="tip",
            parent=self.scrollContent,
        )
        content_layout.addWidget(self.lblScopeSummary)

        grp_ai = QtWidgets.QGroupBox("2. AI Settings" if english else "2. AI 설정")
        grid = QtWidgets.QGridLayout(grp_ai)

        self.cmbProvider = QtWidgets.QComboBox()
        self.cmbProvider.addItem("Free (local summary)", "local")
        self.cmbProvider.addItem("Gemini(API)", "gemini")
        saved_provider = str(self._settings_get("provider", "local") or "").strip() or "local"
        try:
            idx = self.cmbProvider.findData(saved_provider)
            if idx >= 0:
                self.cmbProvider.setCurrentIndex(idx)
        except Exception:
            pass
        self.cmbProvider.currentIndexChanged.connect(self._on_provider_changed)

        self.lblKeyStatus = QtWidgets.QLabel("(Checking key status...)" if english else "(키 상태: 확인 중)")
        self.lblKeyStatus.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

        self.btnSetKey = QtWidgets.QPushButton("Set/change API key…" if english else "API 키 설정/변경…")
        self.btnSetKey.clicked.connect(self._on_set_key)

        self.txtModel = QtWidgets.QLineEdit()
        self.txtModel.setText(ai_gemini.get_configured_model())
        self.txtModel.textChanged.connect(self._refresh_model_status)
        self._update_model_field_hint()

        self.btnSaveModel = QtWidgets.QPushButton("Save model" if english else "모델 저장")
        self.btnSaveModel.clicked.connect(self._on_save_model)
        self.btnRefreshModels = QtWidgets.QPushButton("Check models" if english else "모델 확인")
        self.btnRefreshModels.clicked.connect(self._on_refresh_models_safe)

        self.lblModelStatus = QtWidgets.QLabel("")
        self.lblModelStatus.setWordWrap(True)

        w_model_actions = QtWidgets.QWidget()
        row_model_actions = QtWidgets.QHBoxLayout(w_model_actions)
        row_model_actions.setContentsMargins(0, 0, 0, 0)
        row_model_actions.addWidget(self.btnSaveModel)
        row_model_actions.addWidget(self.btnRefreshModels)

        grid.addWidget(QtWidgets.QLabel("Mode:" if english else "모드:"), 0, 0)
        grid.addWidget(self.cmbProvider, 0, 1, 1, 2)
        grid.addWidget(QtWidgets.QLabel("Key:" if english else "키:"), 1, 0)
        grid.addWidget(self.lblKeyStatus, 1, 1)
        grid.addWidget(self.btnSetKey, 1, 2)
        grid.addWidget(QtWidgets.QLabel("Model:" if english else "모델:"), 2, 0)
        grid.addWidget(self.txtModel, 2, 1)
        grid.addWidget(w_model_actions, 2, 2)
        grid.addWidget(self.lblModelStatus, 3, 0, 1, 3)

        self.lblLocalHint = QtWidgets.QLabel(
            "Free (local summary) mode writes project statistics into sentences without any external API call or data transfer."
            if english
            else "무료(로컬 요약) 모드는 외부 API 호출/전송 없이, 프로젝트 통계를 문장으로 정리합니다."
        )
        self.lblLocalHint.setWordWrap(True)
        self.lblLocalHint.setStyleSheet("color:#455a64;")
        grid.addWidget(self.lblLocalHint, 4, 0, 1, 3)

        self.lblAuthHint = QtWidgets.QLabel(ai_gemini.explain_auth_manager_once())
        self.lblAuthHint.setWordWrap(True)
        self.lblAuthHint.setStyleSheet("color:#455a64;")
        grid.addWidget(self.lblAuthHint, 5, 0, 1, 3)

        self.lblModelGuide = create_hint_label(
            (
                "If you use Gemini, refresh the currently available models first with 'Check models'. "
                "Free (local summary) runs immediately without any external transfer."
            )
            if english
            else
            (
                "Gemini를 쓸 때는 먼저 '모델 확인'으로 현재 사용 가능한 모델을 갱신하세요. "
                "무료(로컬 요약) 모드는 외부 전송 없이 바로 실행됩니다."
            ),
            tone="info",
            parent=grp_ai,
        )
        grid.addWidget(self.lblModelGuide, 6, 0, 1, 3)

        content_layout.addWidget(grp_ai)

        self.lblTransmissionHint = create_hint_label("", tone="tip", parent=self.scrollContent)
        content_layout.addWidget(self.lblTransmissionHint)
        self._refresh_model_status()

        grp_out = QtWidgets.QGroupBox("3. Output" if english else "3. 결과")
        v = QtWidgets.QVBoxLayout(grp_out)
        self.txtOutput = QtWidgets.QTextEdit()
        self.txtOutput.setReadOnly(True)
        self.txtOutput.setPlaceholderText("The AI report will appear here." if english else "여기에 AI 보고서가 생성됩니다.")
        self.txtOutput.setMinimumHeight(240)
        v.addWidget(self.txtOutput)

        btn_row = QtWidgets.QHBoxLayout()
        self.btnGenerate = QtWidgets.QPushButton("Generate AI summary" if english else "AI 요약 생성")
        self.btnGenerate.clicked.connect(self._on_generate)
        self.btnBundle = QtWidgets.QPushButton("Save bundle…" if english else "번들 저장…")
        self.btnBundle.clicked.connect(self._on_export_bundle)
        self.btnExportCsv = QtWidgets.QPushButton("Export stats CSV…" if english else "통계 CSV…")
        self.btnExportCsv.clicked.connect(self._on_export_stats_csv)
        self.btnExport = QtWidgets.QPushButton("Save…" if english else "저장…")
        self.btnExport.clicked.connect(self._on_export)
        self.btnClose = QtWidgets.QPushButton("Close" if english else "닫기")
        self.btnClose.clicked.connect(self.reject)

        btn_row.addWidget(self.btnGenerate)
        btn_row.addWidget(self.btnBundle)
        btn_row.addWidget(self.btnExportCsv)
        btn_row.addWidget(self.btnExport)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btnClose)
        v.addLayout(btn_row)

        content_layout.addWidget(grp_out)
        content_layout.addStretch(1)

        try:
            self.cmbAoi.layerChanged.connect(self._refresh_scope_summary)
        except Exception:
            pass
        self.spinRadius.valueChanged.connect(self._refresh_scope_summary)
        self.chkSelectedOnly.toggled.connect(self._refresh_scope_summary)
        self.chkOnlyArchToolkit.toggled.connect(self._refresh_scope_summary)
        self.chkExcludeStyling.toggled.connect(self._refresh_scope_summary)
        self.cmbProvider.currentIndexChanged.connect(self._refresh_transmission_hint)
        self.txtModel.textChanged.connect(self._refresh_transmission_hint)
        self._refresh_scope_summary()
        self._refresh_transmission_hint()

    def _collect_group_paths(self) -> List[str]:
        root = QgsProject.instance().layerTreeRoot()
        paths: List[str] = []

        def walk(group: QgsLayerTreeGroup, prefix: str):
            for child in group.children():
                if not isinstance(child, QgsLayerTreeGroup):
                    continue
                name = str(child.name() or "").strip()
                if not name:
                    continue
                p = f"{prefix}/{name}" if prefix else name
                paths.append(p)
                walk(child, p)

        try:
            walk(root, "")
        except Exception:
            return []

        return paths

    def _refresh_group_list(self):
        keep = self._get_target_group_path() or str(self._settings_get("target_group_path", "") or "").strip()
        paths = self._collect_group_paths()

        self.cmbTargetGroup.blockSignals(True)
        try:
            self.cmbTargetGroup.clear()
            self.cmbTargetGroup.addItem("(Select group)" if is_english_ui() else "(그룹 선택)", "")
            for p in paths:
                self.cmbTargetGroup.addItem(p, p)
            if keep:
                idx = self.cmbTargetGroup.findData(keep)
                if idx >= 0:
                    self.cmbTargetGroup.setCurrentIndex(idx)
        finally:
            self.cmbTargetGroup.blockSignals(False)
        self._refresh_scope_summary()

    def _selected_layers_snapshot(self):
        ids: List[str] = []
        names: List[str] = []
        for lid in self._selected_layer_ids:
            lyr = QgsProject.instance().mapLayer(lid)
            if lyr is None:
                continue
            ids.append(lid)
            try:
                names.append(str(lyr.name() or ""))
            except Exception:
                pass
        self._selected_layer_ids = ids
        return ids, names

    def _update_selected_layers_label(self):
        ids, names = self._selected_layers_snapshot()
        english = is_english_ui()

        if not ids:
            self.lblSelectedLayers.setText("None selected" if english else "선택 없음")
            self.lblSelectedLayers.setToolTip("")
            return
        if len(names) <= 2:
            summary = ", ".join([name for name in names if name])
        else:
            summary = f"{names[0]}, {names[1]} plus {len(names) - 2} more" if english else f"{names[0]}, {names[1]} 외 {len(names) - 2}개"
        if summary:
            self.lblSelectedLayers.setText(f"{len(ids)} selected: {summary}" if english else f"{len(ids)}개 선택됨: {summary}")
        else:
            self.lblSelectedLayers.setText(f"{len(ids)} selected" if english else f"{len(ids)}개 선택됨")
        preview = "\n".join([n for n in names if n][:30])
        self.lblSelectedLayers.setToolTip(preview)

    def _refresh_scope_summary(self, *_args):
        english = is_english_ui()
        try:
            aoi_layer = self.cmbAoi.currentLayer()
        except Exception:
            aoi_layer = None

        aoi_name = ""
        if isinstance(aoi_layer, QgsVectorLayer):
            try:
                aoi_name = str(aoi_layer.name() or "").strip()
            except Exception:
                aoi_name = ""

        selected_only = bool(self.chkSelectedOnly.isChecked())
        try:
            radius_text = f"{int(round(float(self.spinRadius.value()))):,} m"
        except Exception:
            radius_text = f"{self.spinRadius.value()} m"

        if english:
            lines = [
                f"<b>Current Scan Scope</b>: AOI={aoi_name or 'Not selected'} / radius={radius_text} / "
                f"{'Use selected features only' if selected_only else 'Use the full AOI'}"
            ]
        else:
            lines = [
                f"<b>현재 스캔 범위</b>: AOI={aoi_name or '미선택'} / 반경={radius_text} / "
                f"{'선택 피처만 사용' if selected_only else 'AOI 전체 사용'}"
            ]

        scope = self._get_layer_scope()
        if scope == "group":
            group_path = self._get_target_group_path()
            if english:
                lines.append(
                    "Only the selected group will be scanned: "
                    + (group_path or "<span style='color:#8a4b00;'>No group has been selected yet.</span>")
                )
            else:
                lines.append(
                    "선택 그룹만 스캔합니다: "
                    + (group_path or "<span style='color:#8a4b00;'>아직 그룹을 고르지 않았습니다.</span>")
                )
        elif scope == "layers":
            ids, names = self._selected_layers_snapshot()
            if ids:
                preview = ", ".join([name for name in names[:3] if name])
                extra = ""
                if len(names) > 3:
                    extra = f" plus {len(names) - 3} more" if english else f" 외 {len(names) - 3}개"
                if english:
                    lines.append(f"Only the {len(ids)} manually selected layers will be scanned: {preview}{extra}")
                else:
                    lines.append(f"직접 선택한 {len(ids)}개 레이어만 스캔합니다: {preview}{extra}")
            else:
                lines.append(
                    "<span style='color:#8a4b00;'>Layer-selection mode is active, but no layers have been selected yet.</span>"
                    if english
                    else "<span style='color:#8a4b00;'>레이어 직접 선택 모드입니다. 아직 선택된 레이어가 없습니다.</span>"
                )
        else:
            auto_filters: List[str] = []
            if english:
                auto_filters.append("ArchToolkit results only" if self.chkOnlyArchToolkit.isChecked() else "Include general layers")
                auto_filters.append("Exclude styling / cartographic layers" if self.chkExcludeStyling.isChecked() else "Include styling / cartographic layers")
                lines.append("Automatic scan mode: " + ", ".join(auto_filters))
            else:
                auto_filters.append("ArchToolkit 결과만" if self.chkOnlyArchToolkit.isChecked() else "일반 레이어도 포함")
                auto_filters.append("도면/Style 제외" if self.chkExcludeStyling.isChecked() else "도면/Style도 포함")
                lines.append("자동 스캔 모드입니다: " + ", ".join(auto_filters))

        self.lblScopeSummary.setText("<br>".join(lines))

    def _update_layer_scope_ui(self):
        scope = self._get_layer_scope()
        is_auto = scope == "auto"
        is_group = scope == "group"
        is_layers = scope == "layers"

        try:
            self.chkOnlyArchToolkit.setEnabled(is_auto)
        except Exception:
            pass

        try:
            self.cmbTargetGroup.setEnabled(is_group)
            self.btnRefreshGroups.setEnabled(is_group)
        except Exception:
            pass

        try:
            self.btnSelectLayers.setEnabled(is_layers)
            self.btnClearLayers.setEnabled(is_layers)
        except Exception:
            pass

        self._update_selected_layers_label()
        self._refresh_scope_summary()

    def _on_layer_scope_changed(self):
        scope = self._get_layer_scope()
        self._settings_set("layer_scope", scope)
        self._update_layer_scope_ui()

    def _on_target_group_changed(self):
        self._settings_set("target_group_path", self._get_target_group_path())
        self._refresh_scope_summary()

    def _on_select_layers(self):
        aoi_layer = self.cmbAoi.currentLayer()
        aoi_id = ""
        try:
            aoi_id = str(getattr(aoi_layer, "id", lambda: "")() or "")
        except Exception:
            aoi_id = ""

        dlg = _LayerMultiSelectDialog(self, aoi_layer_id=aoi_id, preselected_ids=self._selected_layer_ids)
        res = dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
        if res != QtWidgets.QDialog.Accepted:
            return
        self._selected_layer_ids = dlg.selected_layer_ids()
        self._update_selected_layers_label()
        self._refresh_scope_summary()

    def _on_clear_layers(self):
        self._selected_layer_ids = []
        self._update_selected_layers_label()
        self._refresh_scope_summary()

    def _on_provider_changed(self):
        provider = self._get_provider()
        self._settings_set("provider", provider)
        self._update_provider_ui()
        self._refresh_key_status()

    def _update_provider_ui(self):
        provider = self._get_provider()
        is_gemini = provider == "gemini"

        try:
            self.btnSetKey.setEnabled(is_gemini)
            self.txtModel.setEnabled(is_gemini)
            self.btnSaveModel.setEnabled(is_gemini)
            self.btnRefreshModels.setEnabled(is_gemini)
        except Exception:
            pass

        try:
            self.lblAuthHint.setVisible(is_gemini)
            self.lblLocalHint.setVisible(not is_gemini)
        except Exception:
            pass
        self._refresh_model_status()
        self._refresh_transmission_hint()

    def _refresh_transmission_hint(self, *_args):
        provider = self._get_provider()
        english = is_english_ui()
        if provider != "gemini":
            self.lblTransmissionHint.setText(
                "<b>No external transmission</b>: the Free (Local Summary) mode turns AOI and layer statistics into prose entirely on this computer."
                if english
                else "<b>외부 전송 없음</b>: 무료(로컬 요약) 모드는 AOI/레이어 통계를 이 컴퓨터 안에서만 문장으로 정리합니다."
            )
            apply_hint_label_style(self.lblTransmissionHint, tone="tip")
            return

        model_name = ai_gemini.normalize_model_name(str(self.txtModel.text() or "").strip())
        if not model_name:
            model_name = ai_gemini.get_configured_model() or ai_gemini.get_default_model_name()
        self.lblTransmissionHint.setText(
            (
                "<b>Sent to Gemini</b>: the AOI name, radius, layer names, summary statistics, "
                f"and ArchToolkit metadata are sent to <b>{model_name}</b> in JSON form. "
                "This does not upload full raw geometries or full raster pixel arrays."
            )
            if english
            else
            (
                "<b>Gemini 전송 범위</b>: AOI 이름, 반경, 레이어 이름, 통계 요약, "
                f"ArchToolkit 메타데이터가 JSON 형태로 <b>{model_name}</b>에 전달됩니다. "
                "원본 지오메트리나 래스터 전체 픽셀을 통째로 업로드하는 방식은 아닙니다."
            )
        )
        apply_hint_label_style(self.lblTransmissionHint, tone="warn")

    def _refresh_key_status(self):
        if self._get_provider() != "gemini":
            self.lblKeyStatus.setText("Not needed (local summary)" if is_english_ui() else "불필요 (로컬 요약)")
            self.lblKeyStatus.setStyleSheet("color:#455a64; font-weight:bold;")
            return

        key = ai_gemini.get_api_key()
        if key:
            self.lblKeyStatus.setText("Configured (AuthManager)" if is_english_ui() else "설정됨 (AuthManager)")
            self.lblKeyStatus.setStyleSheet("color:#2e7d32; font-weight:bold;")
        else:
            self.lblKeyStatus.setText("Not configured" if is_english_ui() else "미설정")
            self.lblKeyStatus.setStyleSheet("color:#c62828; font-weight:bold;")

    def _on_set_key(self):
        english = is_english_ui()
        if self._get_provider() != "gemini":
            push_message(
                self.iface,
                "Info" if english else "정보",
                "No API key is needed in the current mode."
                if english
                else "현재 모드에서는 API 키가 필요하지 않습니다.",
                level=1,
                duration=4,
            )
            return
        try:
            ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)
        except Exception:
            pass
        ai_gemini.configure_api_key(self, iface=self.iface)
        self._refresh_key_status()

    def _on_save_model(self):
        english = is_english_ui()
        if self._get_provider() != "gemini":
            push_message(
                self.iface,
                "Info" if english else "정보",
                "No model setting is needed in the current mode."
                if english
                else "현재 모드에서는 모델 설정이 필요하지 않습니다.",
                level=1,
                duration=4,
            )
            return
        raw_model = str(self.txtModel.text() or "").strip()
        model = ai_gemini.normalize_model_name(raw_model)
        if not model:
            push_message(
                self.iface,
                "Error" if english else "오류",
                "Enter a model name." if english else "모델 이름을 입력하세요.",
                level=2,
                duration=5,
            )
            return
        if model != raw_model:
            self.txtModel.setText(model)
        ai_gemini.set_configured_model(model)
        if model != raw_model:
            push_message(
                self.iface,
                "Done" if english else "완료",
                (
                    f"Saved after replacing the legacy model ID with the latest one: {raw_model} -> {model}"
                    if english
                    else f"구형 모델 ID를 최신 ID로 바꿔 저장했습니다: {raw_model} -> {model}"
                ),
                level=0,
                duration=5,
            )
        else:
            push_message(
                self.iface,
                "Done" if english else "완료",
                f"Saved model: {model}" if english else f"모델을 저장했습니다: {model}",
                level=0,
                duration=4,
            )
        self._refresh_model_status()

    def _on_refresh_models(self):
        self._on_refresh_models_safe()

    def _on_refresh_models_safe(self):
        english = is_english_ui()
        if self._get_provider() != "gemini":
            push_message(
                self.iface,
                "Info" if english else "정보",
                "Model checking is only available in Gemini mode."
                if english
                else "Gemini 모드에서만 모델 확인을 사용할 수 있습니다.",
                level=1,
                duration=4,
            )
            return

        api_key = ai_gemini.get_api_key()
        if not api_key:
            self._on_set_key()
            api_key = ai_gemini.get_api_key()
            if not api_key:
                return

        push_message(
            self.iface,
            "Gemini",
            "Checking available official model IDs..."
            if english
            else "사용 가능한 공식 모델 ID를 확인 중…",
            level=0,
            duration=4,
        )
        models, err = ai_gemini.list_available_models(api_key=str(api_key), timeout_ms=20000)
        if err or not models:
            push_message(
                self.iface,
                "Error" if english else "오류",
                err or ("Could not verify Gemini model IDs." if english else "Gemini 모델 ID를 확인할 수 없습니다."),
                level=2,
                duration=8,
            )
            return

        normalized_models = []
        for model in models:
            model_name = ai_gemini.normalize_model_name(model)
            if model_name and model_name not in normalized_models:
                normalized_models.append(model_name)

        self._last_verified_models = normalized_models
        self._last_models_verified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._update_model_field_hint()

        current_model = ai_gemini.normalize_model_name(str(self.txtModel.text() or "").strip())
        if not current_model:
            self.txtModel.setText(normalized_models[0])
            current_model = normalized_models[0]
        elif current_model != str(self.txtModel.text() or "").strip():
            self.txtModel.setText(current_model)

        level = 0
        if is_english_ui():
            detail = f"Verified {len(normalized_models)} Gemini models"
            if current_model and current_model not in normalized_models:
                level = 1
                detail += f" / current model not verified: {current_model}"
        else:
            detail = f"Gemini 모델 {len(normalized_models)}개 확인"
            if current_model and current_model not in normalized_models:
                level = 1
                detail += f" / 현재 입력 모델 미확인: {current_model}"
        push_message(self.iface, "Gemini", detail, level=level, duration=6)
        self._refresh_model_status()
        self._refresh_transmission_hint()

    def _build_prompt(self, ctx: dict) -> str:
        ctx_json = json.dumps(ctx, ensure_ascii=False, indent=2)
        radius_m = ctx.get("radius_m")
        aoi = ctx.get("aoi", {}) or {}
        aoi_name = aoi.get("layer_name", "")

        if is_english_ui():
            return (
                "You are a GIS analysis assistant supporting archaeology and cultural heritage research.\n"
                "The JSON below summarizes layers within the Area of Interest (AOI) radius in a QGIS project.\n"
                "\n"
                "Important: each layer may include `archtoolkit` metadata.\n"
                "- If `archtoolkit_interpretation` exists, treat it as the plugin's first-pass explanation of the layer.\n"
                "- `archtoolkit_runs` groups outputs from the same `run_id` into a single tool execution.\n"
                "- Prefer `archtoolkit.tool_id/kind/units/run_id` when interpreting the meaning of each layer.\n"
                "- When metadata exists, do not guess the meaning from the layer name alone.\n"
                "- Layers with the same `run_id` may be described together.\n"
                "\n"
                "Request:\n"
                "1) Write in English, in a report / field-note style.\n"
                "2) Do not exaggerate or speculate. If a number is missing, mark it as an estimate or reference.\n"
                "3) Use sections:\n"
                "   - Overview (AOI / radius)\n"
                "   - Layer / analysis summary (by layer)\n"
                "   - Key observations (include quantitative values when available)\n"
                "   - Limits / notes (CRS, resolution, NoData, AI limitations)\n"
                "   - Suggested next steps\n"
                "4) Keep layer names as close to the originals as possible.\n"
                "\n"
                f"Target: AOI={aoi_name}, radius={radius_m} m\n"
                "\n"
                "JSON:\n"
                f"{ctx_json}\n"
            )

        return (
            "당신은 한국의 고고학/문화유산 연구자를 돕는 GIS 분석 보조자입니다.\n"
            "아래 JSON은 QGIS 프로젝트에서 ‘조사지역(AOI) 반경’ 내의 레이어들을 요약한 것입니다.\n"
            "\n"
            "중요: 각 레이어 항목에 `archtoolkit` 메타데이터가 포함될 수 있습니다.\n"
            "- `archtoolkit_interpretation`이 있으면, 이는 플러그인이 도구 의미를 1차 해석한 값입니다.\n"
            "- `archtoolkit_runs`는 같은 `run_id` 결과를 실행 단위로 묶은 요약입니다.\n"
            "- 가능하면 `archtoolkit.tool_id/kind/units/run_id`를 우선 사용해 레이어 의미를 해석하세요.\n"
            "- 메타데이터가 있는 경우, 레이어 이름만 보고 임의로 의미를 추측하지 마세요.\n"
            "- 동일 `run_id`는 같은 도구 실행(run)에서 나온 결과이므로 묶어서 설명해도 됩니다.\n"
            "\n"
            "요청:\n"
            "1) 한국어로, 보고서/업무 메모 형태로 정리해 주세요.\n"
            "2) 과장/추측 금지: 수치가 없으면 단정하지 말고 '추정/참고'로 표시.\n"
            "3) 결과는 섹션으로 구분:\n"
            "   - 개요(조사지역/반경)\n"
            "   - 사용된 레이어/분석 요약(레이어별)\n"
            "   - 핵심 관찰(정량값이 있으면 포함)\n"
            "   - 한계/주의(좌표계/해상도/NoData/AI 한계)\n"
            "   - 다음 단계 제안\n"
            "4) 결과에 포함된 레이어 이름은 가능한 그대로 유지.\n"
            "\n"
            f"대상: AOI={aoi_name}, 반경={radius_m} m\n"
            "\n"
            "JSON:\n"
            f"{ctx_json}\n"
        )

    def _sanitize_filename(self, name: str, *, fallback: str = "aoi_report") -> str:
        s = str(name or "").strip()
        if not s:
            return fallback
        for ch in '<>:"/\\|?*':
            s = s.replace(ch, "_")
        s = s.replace("\r", " ").replace("\n", " ").strip().strip(".")
        s = " ".join(s.split())
        return (s or fallback)[:80]

    def _make_ctx_key(
        self,
        *,
        aoi_layer,
        selected_only: bool,
        radius_m: float,
        only_arch: bool,
        exclude_styling: bool,
        scope: str,
        target_group: str,
        layer_ids,
        max_layers: int,
    ):
        try:
            aoi_id = str(aoi_layer.id() or "")
        except Exception:
            aoi_id = ""
        try:
            r0 = int(round(float(radius_m)))
        except Exception:
            r0 = radius_m
        try:
            lids = tuple([str(x or "").strip() for x in (layer_ids or []) if str(x or "").strip()])
        except Exception:
            lids = ()
        return (
            aoi_id,
            bool(selected_only),
            r0,
            bool(only_arch),
            bool(exclude_styling),
            str(scope or ""),
            str(target_group or ""),
            lids,
            int(max_layers),
            int(self._ctx_revision),
        )

    def _get_or_build_ctx(self, *, max_layers: int = 40, prompt_select_layers: bool = True):
        aoi_layer = self.cmbAoi.currentLayer()
        if aoi_layer is None or not isinstance(aoi_layer, QgsVectorLayer):
            return None, "Select an AOI polygon layer." if is_english_ui() else "조사지역(AOI) 폴리곤 레이어를 선택하세요."

        radius_m = float(self.spinRadius.value())
        selected_only = bool(self.chkSelectedOnly.isChecked())
        only_arch = bool(self.chkOnlyArchToolkit.isChecked())
        exclude_styling = bool(self.chkExcludeStyling.isChecked())

        scope = self._get_layer_scope()
        target_group = ""
        layer_ids = None
        if scope == "group":
            target_group = self._get_target_group_path()
            if not target_group:
                return None, "Select a target group." if is_english_ui() else "대상 그룹을 선택하세요."
            only_arch = False
        elif scope == "layers":
            if not self._selected_layer_ids and prompt_select_layers:
                self._on_select_layers()
            if not self._selected_layer_ids:
                return None, "Select target layers." if is_english_ui() else "대상 레이어를 선택하세요."
            layer_ids = list(self._selected_layer_ids)
            only_arch = False

        key = self._make_ctx_key(
            aoi_layer=aoi_layer,
            selected_only=selected_only,
            radius_m=radius_m,
            only_arch=only_arch,
            exclude_styling=exclude_styling,
            scope=scope,
            target_group=target_group,
            layer_ids=layer_ids,
            max_layers=max_layers,
        )
        if self._last_ctx is not None and self._last_ctx_key == key:
            return self._last_ctx, None

        ctx, err = ai_aoi_summary.build_aoi_context(
            aoi_layer=aoi_layer,
            selected_only=selected_only,
            radius_m=radius_m,
            only_archtoolkit_layers=only_arch,
            exclude_styling_layers=exclude_styling,
            layer_ids=layer_ids,
            group_path_prefix=target_group or None,
            max_layers=int(max_layers),
        )
        if err:
            return None, err
        if ctx:
            self._last_ctx = ctx
            self._last_ctx_key = key
        return ctx, None

    def _on_generate(self):
        english = is_english_ui()
        aoi_layer = self.cmbAoi.currentLayer()
        if aoi_layer is None or not isinstance(aoi_layer, QgsVectorLayer):
            push_message(
                self.iface,
                "Error" if english else "오류",
                "Select an AOI polygon layer." if english else "조사지역(AOI) 폴리곤 레이어를 선택하세요.",
                level=2,
                duration=6,
            )
            restore_ui_focus(self)
            return

        provider = self._get_provider()
        is_gemini = provider == "gemini"

        api_key = None
        model = None
        if is_gemini:
            api_key = ai_gemini.get_api_key()
            if not api_key:
                push_message(
                    self.iface,
                    "Info" if english else "정보",
                    "A Gemini API key is required. Please configure it first."
                    if english
                    else "Gemini API 키가 필요합니다. 먼저 설정하세요.",
                    level=1,
                    duration=6,
                )
                self._on_set_key()
                api_key = ai_gemini.get_api_key()
                if not api_key:
                    return

            raw_model = str(self.txtModel.text() or "").strip() or ai_gemini.get_configured_model()
            model = ai_gemini.normalize_model_name(raw_model)
            if model != raw_model:
                self.txtModel.setText(model)
                push_message(
                    self.iface,
                    "Info" if english else "정보",
                    (
                        f"Using the latest model ID instead of the legacy one: {raw_model} -> {model}"
                        if english
                        else f"구형 모델 ID를 최신 ID로 바꿔 사용합니다: {raw_model} -> {model}"
                    ),
                    level=1,
                    duration=6,
                )

        try:
            ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)
        except Exception:
            pass

        push_message(
            self.iface,
            "AI Summary" if english else "AI 요약",
            "Building a summary of layers around the AOI..."
            if english
            else "AOI 주변 레이어 요약 생성 중…",
            level=0,
            duration=4,
        )
        ctx, err = self._get_or_build_ctx(max_layers=40, prompt_select_layers=True)
        if err or not ctx:
            push_message(
                self.iface,
                "Error" if english else "오류",
                err or ("Could not build the AOI summary context." if english else "AOI 요약 컨텍스트를 만들 수 없습니다."),
                level=2,
                duration=8,
            )
            return

        try:
            self._last_provider = str(provider or "")
        except Exception:
            self._last_provider = ""
        try:
            self._last_model = str(model or "")
        except Exception:
            self._last_model = ""
        try:
            self._last_generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            self._last_generated_at = ""

        if not is_gemini:
            try:
                text = ai_local_summarizer.generate_report(ctx)
            except Exception as e:
                push_message(
                    self.iface,
                    "Error" if english else "오류",
                    f"{'Local summary generation failed' if english else '로컬 요약 생성 실패'}: {e}",
                    level=2,
                    duration=8,
                )
                return

            self.txtOutput.setPlainText(text or "")
            self._last_report_text = str(text or "")
            self._last_report_ctx_key = self._last_ctx_key
            push_message(
                self.iface,
                "AI Summary" if english else "AI 요약",
                "Done (local summary)" if english else "완료 (로컬)",
                level=0,
                duration=4,
            )
            return

        prompt = self._build_prompt(ctx)

        push_message(
            self.iface,
            "AI Summary" if english else "AI 요약",
            "Calling Gemini... (sending only data summaries and layer names)"
            if english
            else "Gemini 호출 중…(데이터 요약/레이어명만 전송)",
            level=0,
            duration=5,
        )
        self.setEnabled(False)
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            text, api_err = ai_gemini.generate_text(
                api_key=str(api_key or ""),
                model=str(model or ""),
                prompt=prompt,
                temperature=0.2,
                max_output_tokens=1400,
                timeout_ms=45000,
            )
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.setEnabled(True)

        if api_err:
            log_message(f"Gemini error: {api_err}", level=2)
            push_message(
                self.iface,
                "Error" if english else "오류",
                f"{'Gemini call failed' if english else 'Gemini 호출 실패'}: {api_err}",
                level=2,
                duration=10,
            )
            # Fallback to local report so user still gets something usable.
            try:
                fallback = ai_local_summarizer.generate_report(ctx)
                if fallback:
                    self.txtOutput.setPlainText(
                        (
                            tr("※ Gemini 호출 실패로 로컬 요약으로 대체했습니다.\n\n")
                            if not english
                            else "Note: Gemini failed, so the result was replaced with a local summary.\n\n"
                        )
                        + str(fallback)
                    )
                    self._last_report_text = str(fallback or "")
                    self._last_report_ctx_key = self._last_ctx_key
                    push_message(
                        self.iface,
                        "AI Summary" if english else "AI 요약",
                        "Replaced with local summary" if english else "로컬 요약으로 대체 완료",
                        level=1,
                        duration=6,
                    )
            except Exception:
                pass
            return

        self.txtOutput.setPlainText(text or "")
        self._last_report_text = str(text or "")
        self._last_report_ctx_key = self._last_ctx_key
        push_message(self.iface, "AI Summary" if is_english_ui() else "AI 요약", "Done" if is_english_ui() else "완료", level=0, duration=4)

    def _on_help(self):
        if is_english_ui():
            html = (
                "<b>Why was this feature added?</b><br>"
                "When analysis results such as viewshed, cost, network, terrain indices, GeoChem, and cadastral overlap are scattered across many layers, "
                "they become difficult to reuse in field notes and reports. AI AOI Report gathers results within the AOI radius and turns them into "
                "<b>summary / report prose</b> more quickly.<br><br>"
                "<b>How should I use it?</b><br>"
                "1) Run the analyses you need so result layers exist first.<br>"
                "2) Choose the AOI and radius (m).<br>"
                "3) Choose a mode: <b>Free (Local)</b> summarizes without external transmission, "
                "while <b>Gemini</b> creates more natural report text (API key required).<br>"
                "4) <b>Always review</b> the generated text before saving or editing it.<br><br>"
                "<b>What this tool reads</b><br>"
                "- It scans layers in the current QGIS project that intersect the AOI buffer.<br>"
                "- Vector layers: feature count, and when possible total length / area and top field values.<br>"
                "- Raster layers: simple statistics such as min / mean / max when available.<br><br>"
                "<b>What leaves your computer in Gemini mode</b><br>"
                "- The AOI name, radius, selected layer names, summary statistics, and ArchToolkit metadata are sent as JSON.<br>"
                "- It does not upload full raw geometries or full raster pixel arrays.<br><br>"
                "<b>Can AI explain every analysis?</b><br>"
                "In principle, if a result exists as a layer (raster or vector), it can be included in the summary. "
                "The current workflow summarizes layer-based statistics, and "
                "<b>when ArchToolkit metadata (tool_id / kind / run_id, etc.) exists, it is used first to interpret layer meaning</b>. "
                "Even so, the final interpretation still needs user review.<br><br>"
                "<b>Tips</b><br>"
                "- Use the AOI in a <b>projected CRS (meters)</b> when possible.<br>"
                "- Check the <b>Current Scan Scope</b> banner under the input section to confirm what will actually be read.<br>"
                "- If target layers are too many or too mixed, narrow the scope with <b>Target Group / Target Layers</b> for better results.<br>"
                "- <b>Statistics CSV</b> saves standard AOI-neighborhood statistics without AI.<br>"
                "- <b>Save Bundle</b> writes report.md + context.json + CSV + canvas.png + params.json into one folder.<br>"
                "- If layer names or attributes contain sensitive information, be careful when using Gemini mode because they may be transmitted.<br>"
                "- Styling / cartographic layers often interfere with interpretation, so excluding them by default is recommended."
            )
            title = "AI AOI Report Help"
            fallback = "See the AI AOI Report section in README."
        else:
            html = (
                "<b>왜 이 기능을 넣었나요?</b><br>"
                "분석 결과(가시권/비용/네트워크/지형지수/GeoChem/지적중첩 등)가 여러 레이어로 흩어지면, "
                "현장 기록·보고서에 쓰기 어렵습니다. AI 조사요약은 AOI 반경 내 결과를 모아 "
                "<b>요약/보고서 문장</b>으로 빠르게 정리하려고 만들었습니다.<br><br>"
                "<b>어떻게 쓰면 좋나요?</b><br>"
                "1) 먼저 원하는 분석을 실행해 결과 레이어를 만든 다음<br>"
                "2) AOI와 반경(m)을 고르고<br>"
                "3) 모드를 선택합니다: <b>무료(로컬)</b>은 외부 전송 없이 요약, <b>Gemini</b>는 더 자연어 보고서 생성(키 필요).<br>"
                "4) 생성된 문장을 <b>반드시 검토</b>한 뒤 저장/편집하세요.<br><br>"
                "<b>이 도구가 ‘읽는 것’</b><br>"
                "- 현재 QGIS 프로젝트의 레이어 중 AOI 버퍼와 겹치는 레이어를 스캔합니다.<br>"
                "- 벡터: 피처 수, (가능하면) 길이/면적 합, 일부 필드 분포(상위 값).<br>"
                "- 래스터: min/mean/max 등 단순 통계(가능하면).<br><br>"
                "<b>Gemini 모드에서 외부로 나가는 것</b><br>"
                "- AOI 이름, 반경, 선택된 레이어 이름, 통계 요약, ArchToolkit 메타데이터가 JSON으로 전송됩니다.<br>"
                "- 원본 지오메트리 전체나 래스터 픽셀 전체를 그대로 업로드하는 구조는 아닙니다.<br><br>"
                "<b>모든 분석을 AI가 답변할 수 있나요?</b><br>"
                "원칙적으로 ‘결과가 레이어(래스터/벡터)로 존재’하면 요약에 포함될 수 있습니다. "
                "지금은 레이어 기반 통계를 모아 문장화하는 구조이지만, "
                "<b>ArchToolkit 메타데이터(tool_id/kind/run_id 등)가 있으면 도구 의미를 더 우선적으로 해석</b>합니다. "
                "그래도 최종 해석은 사용자가 검토해야 합니다.<br><br>"
                "<b>팁</b><br>"
                "- AOI는 가능하면 <b>투영 CRS(미터)</b>에서 사용하세요.<br>"
                "- 입력 섹션 아래의 <b>현재 스캔 범위</b> 안내 배너에서 실제로 어떤 범위를 읽을지 먼저 확인하세요.<br>"
                "- 대상 레이어가 너무 많거나 섞여 있으면, <b>대상 그룹/대상 레이어</b>를 지정해 범위를 좁히면 더 정확합니다.<br>"
                "- <b>통계 CSV</b>는 AI 없이 AOI 주변 표준 통계를 CSV로 저장합니다.<br>"
                "- <b>번들 저장</b>은 report.md + context.json + CSV + canvas.png + params.json을 한 폴더로 저장합니다.<br>"
                "- 레이어 이름/속성에 민감정보가 있으면 Gemini 모드 사용 시 전송될 수 있으니 주의하세요.<br>"
                "- 도면/Style 결과는 해석에 방해가 될 수 있어 기본적으로 제외(체크)하는 것을 권장합니다."
            )
            title = "AI 조사요약 도움말"
            fallback = "README의 AI 조사요약 섹션을 참고하세요."
        try:
            show_help_dialog(parent=self, title=title, html=html)
        except Exception:
            # Fallback plain text
            QtWidgets.QMessageBox.information(self, title, fallback)

    def _on_export(self):
        txt = self.txtOutput.toPlainText()
        if not (txt or "").strip():
            push_message(self.iface, "정보", "저장할 내용이 없습니다.", level=1, duration=4)
            return
        path, _flt = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "보고서 저장",
            "aoi_report.md",
            "Markdown (*.md);;Text (*.txt);;All Files (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(txt)
            push_message(self.iface, "완료", f"저장했습니다: {path}", level=0, duration=5)
        except Exception as e:
            push_message(self.iface, "오류", f"저장 실패: {e}", level=2, duration=6)

    def _on_export_stats_csv(self):
        ctx, err = self._get_or_build_ctx(max_layers=40, prompt_select_layers=True)
        if err or not ctx:
            push_message(self.iface, "오류", err or "AOI 요약 컨텍스트를 만들 수 없습니다.", level=2, duration=8)
            return

        aoi = ctx.get("aoi") or {}
        aoi_name = str(aoi.get("layer_name") or "").strip()
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_aoi = self._sanitize_filename(aoi_name, fallback="AOI")
        default_name = f"aoi_layers_summary_{safe_aoi}_{ts}.csv"

        layers_path, _flt = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "통계 CSV 저장 (layers_summary)",
            default_name,
            "CSV (*.csv);;All Files (*.*)",
        )
        if not layers_path:
            return

        root, ext = os.path.splitext(str(layers_path))
        if not ext:
            layers_path = root + ".csv"
        numeric_path = root + "_numeric_fields.csv"

        err2 = ai_aoi_summary.export_aoi_context_csv(
            ctx,
            layers_csv_path=str(layers_path),
            numeric_fields_csv_path=str(numeric_path),
        )
        if err2:
            push_message(self.iface, "오류", f"CSV 저장 실패: {err2}", level=2, duration=8)
            return
        push_message(self.iface, "완료", f"CSV 저장 완료: {layers_path}, {numeric_path}", level=0, duration=6)

    def _save_canvas_snapshot(self, path: str) -> Optional[str]:
        try:
            if self.iface is None:
                return "iface is None"
            canvas = self.iface.mapCanvas()
            if canvas is None:
                return "mapCanvas is None"

            # Preferred (QGIS API)
            try:
                if hasattr(canvas, "saveAsImage"):
                    canvas.saveAsImage(str(path))
                    if os.path.exists(str(path)):
                        return None
            except Exception:
                pass

            # Fallback (Qt)
            try:
                pm = canvas.grab()
                if pm is not None and (not pm.isNull()):
                    ok = pm.save(str(path))
                    if ok and os.path.exists(str(path)):
                        return None
            except Exception:
                pass
            return "snapshot failed"
        except Exception as e:
            return str(e)

    def _on_export_bundle(self):
        ctx, err = self._get_or_build_ctx(max_layers=40, prompt_select_layers=True)
        if err or not ctx:
            push_message(self.iface, "오류", err or "AOI 요약 컨텍스트를 만들 수 없습니다.", level=2, duration=8)
            return

        base_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "번들 저장 폴더 선택", "")
        if not base_dir:
            return

        aoi = ctx.get("aoi") or {}
        aoi_name = str(aoi.get("layer_name") or "").strip()
        safe_aoi = self._sanitize_filename(aoi_name, fallback="AOI")
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        folder_base = f"ArchToolkit_AOI_Report_{safe_aoi}_{ts}"

        bundle_dir = os.path.join(str(base_dir), folder_base)
        try:
            i = 1
            while os.path.exists(bundle_dir):
                bundle_dir = os.path.join(str(base_dir), f"{folder_base}_{i}")
                i += 1
            os.makedirs(bundle_dir, exist_ok=True)
        except Exception as e:
            push_message(self.iface, "오류", f"폴더 생성 실패: {e}", level=2, duration=8)
            return

        current_report_key = self._last_ctx_key
        report_matches_ctx = self._last_report_ctx_key == current_report_key

        # Report text: use current UI/cached text only when it matches the current context.
        report_text = ""
        report_source = "regenerated_local"
        if report_matches_ctx:
            try:
                report_text = str(self.txtOutput.toPlainText() or "")
            except Exception:
                report_text = ""
            if report_text.strip():
                report_source = "current_output"
            else:
                report_text = str(self._last_report_text or "")
                if report_text.strip():
                    report_source = "cached_output"
        if not report_text.strip():
            try:
                report_text = str(ai_local_summarizer.generate_report(ctx) or "")
                if report_text.strip():
                    self._last_report_text = report_text
                    self._last_report_ctx_key = current_report_key
                    self._last_provider = "local"
                    self._last_model = ""
            except Exception:
                report_text = ""

        warnings: List[str] = []

        try:
            with open(os.path.join(bundle_dir, "report.md"), "w", encoding="utf-8") as f:
                f.write(report_text)
        except Exception as e:
            warnings.append(f"report.md 저장 실패: {e}")

        try:
            with open(os.path.join(bundle_dir, "context.json"), "w", encoding="utf-8") as f:
                f.write(json.dumps(ctx, ensure_ascii=False, indent=2))
        except Exception as e:
            warnings.append(f"context.json 저장 실패: {e}")

        try:
            params = {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "provider": str((self._last_provider if report_source != "regenerated_local" else "local") or self._get_provider() or ""),
                "gemini_model": str(self._last_model or "") if report_source != "regenerated_local" else "",
                "report_source": report_source,
                "aoi_layer_name": aoi_name,
                "radius_m": ctx.get("radius_m"),
                "options": ctx.get("options") or {},
                "layers_count": int(len(ctx.get("layers") or [])),
                "qgis_project_path": str(QgsProject.instance().fileName() or ""),
            }
            with open(os.path.join(bundle_dir, "params.json"), "w", encoding="utf-8") as f:
                f.write(json.dumps(params, ensure_ascii=False, indent=2))
        except Exception as e:
            warnings.append(f"params.json 저장 실패: {e}")

        try:
            layers_csv_path = os.path.join(bundle_dir, "layers_summary.csv")
            numeric_csv_path = os.path.join(bundle_dir, "numeric_fields.csv")
            err2 = ai_aoi_summary.export_aoi_context_csv(
                ctx,
                layers_csv_path=str(layers_csv_path),
                numeric_fields_csv_path=str(numeric_csv_path),
            )
            if err2:
                warnings.append(f"CSV 저장 실패: {err2}")
        except Exception as e:
            warnings.append(f"CSV 저장 실패: {e}")

        try:
            snap_err = self._save_canvas_snapshot(os.path.join(bundle_dir, "canvas.png"))
            if snap_err:
                warnings.append(f"canvas.png 저장 실패: {snap_err}")
        except Exception as e:
            warnings.append(f"canvas.png 저장 실패: {e}")

        if warnings:
            push_message(self.iface, "번들 저장", f"완료(경고 {len(warnings)}개): {bundle_dir}", level=1, duration=10)
            try:
                for w in warnings[:8]:
                    log_message(f"[bundle] {w}")
            except Exception:
                pass
            return

        push_message(self.iface, "번들 저장", f"완료: {bundle_dir}", level=0, duration=8)
