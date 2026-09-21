# -*- coding: utf-8 -*-

# ArchToolkit - Archaeology Toolkit for QGIS
# Copyright (C) 2026 balguljang2
# License: GPL v3
"""
Spatial / Visibility Network Tool

- PPA (Proximal Point Analysis): Euclidean k-NN graph ("spatial proximity" only).
- Visibility Network: DEM-based Line of Sight graph (A <-> B if mutually visible).

This tool is intentionally separated from the Least-cost Network tool to keep
the UI simple and avoid mixing "cost" and "proximity/visibility" concepts.
"""

import heapq
import math
import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import processing

from qgis.PyQt import QtWidgets, uic
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor, QIcon, QTextOption
from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsMapLayerProxyModel,
    QgsPalLayerSettings,
    QgsPointXY,
    QgsProject,
    QgsRendererCategory,
    QgsRendererRange,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsGraduatedSymbolRenderer,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox  # noqa: F401 (needed for .ui custom widget loading)

from .utils import (
    log_swallowed,
    is_metric_crs,
    log_message,
    push_message,
    restore_ui_focus,
    move_group_to_top,
    set_archtoolkit_layer_metadata,
)
from .live_log_dialog import ensure_live_log_dialog
from .help_dialog import show_help_dialog
from . import dialog_memory
from .i18n import is_english_ui
from .network_metrics import (
    betweenness_centrality_unweighted,
    closeness_centrality_unweighted,
)


FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "spatial_network_dialog_base.ui")
)


NETWORK_PPA = "ppa"
NETWORK_VISIBILITY = "visibility"

PPA_KNN = "knn"
PPA_THRESHOLD = "threshold"
PPA_DELAUNAY = "delaunay"
PPA_GABRIEL = "gabriel"
PPA_RNG = "rng"

VIS_RULE_MUTUAL = "mutual"
VIS_RULE_EITHER = "either"

# LOS earth-curvature / atmospheric-refraction drop: cc * d^2 / (2R), the same
# formula and constants as viewshed_dialog (and gdal_viewshed -cc).
# cc = 1 - refraction coefficient (default k = 0.13 -> cc = 0.87), cc = 0 = flat.
LOS_EARTH_RADIUS_M = 6371000.0
LOS_DEFAULT_REFRACTION_K = 0.13
LOS_SAMPLE_CAP = 5000
LOS_SAMPLE_MIN = 80


@dataclass(frozen=True)
class _Node:
    fid: str
    name: str
    x: float
    y: float
    samples: Tuple[Tuple[float, float], ...]
    is_polygon: bool


class SpatialNetworkDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        # Remember the last-used inputs between sessions (tools/dialog_memory.py).
        dialog_memory.attach(self, "spatial_network")
        self.setupUi(self)
        self.iface = iface
        self.canvas = iface.mapCanvas()

        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            icon_candidates = [
                "spatial_network.png",
                "spatial_network.jpg",
                "spatial_network.jpeg",
                "network_icon.png",
                "network_icon.jpg",
                "network_icon.jpeg",
                "cost_icon.png",
            ]
            for icon_name in icon_candidates:
                icon_path = os.path.join(plugin_dir, icon_name)
                if os.path.exists(icon_path):
                    self.setWindowIcon(QIcon(icon_path))
                    break
        except Exception as _exc:
            log_swallowed("spatial_network_dialog.__init__", _exc)

        # Layer filters
        self.cmbSiteLayer.setFilters(QgsMapLayerProxyModel.VectorLayer)
        self.cmbDemLayer.setFilters(QgsMapLayerProxyModel.RasterLayer)

        # Polygon representative point mode
        self.cmbPolyPointMode.clear()
        self.cmbPolyPointMode.addItem("Point on surface (권장)", "surface")
        self.cmbPolyPointMode.addItem("Centroid", "centroid")

        # Name field
        self.cmbNameField.clear()
        self.cmbNameField.addItem("(FID 사용)", "")

        # Network type
        self.cmbNetworkType.clear()
        self.cmbNetworkType.addItem("근접성 네트워크 (PPA)", NETWORK_PPA)
        self.cmbNetworkType.addItem("가시성 네트워크 (Visibility / LOS)", NETWORK_VISIBILITY)

        # Extra widgets (created dynamically to avoid .ui editing regressions)
        self._ensure_extra_widgets()
        self._setup_help_button()

        # PPA graph selector
        try:
            self.cmbPpaGraph.clear()
            self.cmbPpaGraph.addItem("k-NN (직선거리)", PPA_KNN)
            self.cmbPpaGraph.addItem("Distance threshold (반경)", PPA_THRESHOLD)
            self.cmbPpaGraph.addItem("Delaunay (삼각망)", PPA_DELAUNAY)
            self.cmbPpaGraph.addItem("Gabriel graph", PPA_GABRIEL)
            self.cmbPpaGraph.addItem("RNG (Relative neighbor graph)", PPA_RNG)
        except Exception as _exc:
            log_swallowed("spatial_network_dialog.__init__", _exc)

        # Visibility edge rule (for node metrics/components)
        try:
            self.cmbVisEdgeRule.clear()
            self.cmbVisEdgeRule.addItem("상호 보임만 (Mutual)", VIS_RULE_MUTUAL)
            self.cmbVisEdgeRule.addItem("단방향 포함 (Either direction)", VIS_RULE_EITHER)
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:164 (__init__)", _exc)

        self._setup_tooltips()

        # Signals
        self.cmbNetworkType.currentIndexChanged.connect(self._on_mode_changed)
        self.cmbSiteLayer.layerChanged.connect(self._on_site_layer_changed)
        try:
            self.cmbPpaGraph.currentIndexChanged.connect(self._update_ppa_controls)
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:174 (__init__)", _exc)
        try:
            self.chkVisAllPairs.toggled.connect(self._update_visibility_controls)
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:178 (__init__)", _exc)
        try:
            self.chkPolyBoundaryVis.toggled.connect(self._update_visibility_controls)
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:182 (__init__)", _exc)
        self.btnRun.clicked.connect(self.run_analysis)
        self.btnClose.clicked.connect(self.reject)

        self._on_site_layer_changed(self.cmbSiteLayer.currentLayer())
        self._on_mode_changed()

    def _setup_help_button(self):
        try:
            self.btnHelp = QtWidgets.QPushButton("도움말", self)
            self.btnHelp.setToolTip("도구 사용법/주의사항을 봅니다.")
            self.btnHelp.clicked.connect(self._on_help)
            if hasattr(self, "horizontalLayout_Buttons"):
                try:
                    idx = int(self.horizontalLayout_Buttons.indexOf(self.btnClose))
                    if idx >= 0:
                        self.horizontalLayout_Buttons.insertWidget(idx, self.btnHelp)
                    else:
                        self.horizontalLayout_Buttons.addWidget(self.btnHelp)
                except Exception:
                    try:
                        self.horizontalLayout_Buttons.addWidget(self.btnHelp)
                    except Exception as _exc:
                        log_swallowed("tools/spatial_network_dialog.py:205 (_setup_help_button)", _exc)
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._setup_help_button", _exc)

    def _on_help(self):
        html = """
<h3>근접/가시권 네트워크(Spatial / Visibility Network) 도움말</h3>
<p>
유적(노드) 레이어를 입력으로 받아, (1) 근접성 네트워크(PPA) 또는 (2) DEM 기반 가시성(LOS) 네트워크를 생성합니다.
</p>

<h4>모드</h4>
<ul>
  <li><b>PPA</b>: 직선거리 기반 k-NN/반경/삼각망(Delaunay) 등으로 간선을 생성합니다.</li>
  <li><b>Visibility(LOS)</b>: DEM을 샘플링하여 두 노드가 서로 보이는지 판정해 간선을 생성합니다.</li>
</ul>

<h4>입력/출력</h4>
<ul>
  <li><b>입력</b>: 유적 레이어(포인트/폴리곤), (LOS 모드일 때) DEM</li>
  <li><b>출력</b>: 네트워크 간선(라인) 레이어 + (옵션) 노드 지표(중심성/컴포넌트) 레이어</li>
</ul>

<h4>주의/팁</h4>
<ul>
  <li>LOS는 후보쌍 수가 급증할 수 있습니다. <b>후보 k</b>·<b>최대거리</b>로 제한하는 것을 권장합니다.</li>
  <li>폴리곤 유적은 대표점을 사용합니다(표면상 점/중심점). 필요하면 경계 샘플링 옵션을 켜세요.</li>
  <li>LOS 판정에는 지구 곡률·대기 굴절 보정이 기본 적용됩니다(굴절 계수 0.13, 가시권 분석 도구와 같은 식).
      평면 시선으로 판정하려면 <b>지구 곡률 보정</b> 체크를 해제하세요. 설정값은 결과 레이어 메타데이터에 기록됩니다.</li>
  <li>더 자세한 해석은 버튼행의 <b>해석 가이드</b>를 참고하세요.</li>
</ul>
"""
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            show_help_dialog(parent=self, title="Spatial / Visibility Network 도움말", html=html, plugin_dir=plugin_dir, tool_id="spatial_network")
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:239 (_on_help)", _exc)

    def _setup_tooltips(self):
        # Keep the main UI compact; provide detailed explanations via tooltips.
        tooltip_ppa = (
            "PPA(Proximal Point Analysis)\n"
            "- 지형(DEM) 비용을 쓰지 않고, 유클리드 거리(직선거리)로 최근접 k개를 연결합니다.\n"
            "- k가 작을수록(예: 3~5) 현실적인 '이웃망' 형태가 되며, k가 크면 간선이 급격히 늘어납니다.\n"
            "- 본 도구는 SciPy(KDTree) 같은 외부 의존성 없이 동작합니다.\n\n"
            "Ref (REFERENCES.md 구분: (B) 직접 구현, (C) 해석/배경 참고):\n"
            "- (B) 구현: 유클리드 k-NN / 반경 / Delaunay-Gabriel-RNG 근접 그래프.\n"
            "- (C) Terrell (1977) Human Biogeography in the Solomon Islands.\n"
            "- (C) Brughmans & Peeples (2017) Trends in archaeological network research.\n"
            "- (C) Amati, Shafie & Brandes (2018) Reconstructing Archaeological Networks with Structural Holes."
        )

        tooltip_vis = (
            "가시성 네트워크(Visibility / LOS)\n"
            "- DEM 기반 Line of Sight(가시선)으로 두 유적 사이에 지형이 시선을 가리는지 샘플링하여 판정합니다.\n"
            "- 결과 레이어는 '보임/안보임'을 색상으로 구분하고, 거리(km)는 속성(dist_km)으로 저장됩니다.\n"
            "- 계산량이 커질 수 있으므로 '후보 k'와 '최대거리'로 후보 쌍을 줄이는 것을 권장합니다.\n"
            "- 관측/대상 높이는 지표면(DEM) 위 추가 높이(m)입니다.\n"
            "- 곡률·굴절 보정: 기본 적용, 계수 0.13 (가시권 분석 도구와 같은 식 cc*d^2/(2R), cc = 1 - 계수).\n"
            "  장거리 쌍에서는 보정 여부에 따라 판정이 달라질 수 있습니다(25 km에서 약 10 m). 끄려면 '지구 곡률 보정' 해제.\n\n"
            "Ref (REFERENCES.md 구분: (B) 직접 구현, (C) 해석/배경 참고):\n"
            "- (B) 구현: DEM 등간격 샘플링 LOS + 곡률·굴절 보정 + 네트워크 지표(degree/component/centrality).\n"
            "- (C) Van Dyke et al. (2016) Intervisibility in the Chacoan world (viewsheds + viewnets).\n"
            "- (C) Gillings & Wheatley (2001) unresolved issues in archaeological visibility analysis.\n"
            "- (C) 참고: Turner et al. (2001) 격자 기반 VGA(visibility graph analysis); 이 도구는 유적 간 상호가시성 네트워크이며\n"
            "  VGA 지표(visual integration 등)는 계산하지 않습니다."
        )

        # Per-item tooltips (combobox dropdown)
        try:
            self.cmbNetworkType.setItemData(0, tooltip_ppa, Qt.ToolTipRole)
            self.cmbNetworkType.setItemData(1, tooltip_vis, Qt.ToolTipRole)
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:271 (_setup_tooltips)", _exc)

        # Show the currently selected item's tooltip even when the dropdown is closed.
        def _sync_network_type_tooltip():
            try:
                tip = self.cmbNetworkType.itemData(self.cmbNetworkType.currentIndex(), Qt.ToolTipRole) or ""
                self.cmbNetworkType.setToolTip(str(tip))
            except Exception as _exc:
                log_swallowed("tools/spatial_network_dialog.py:279 (_sync_network_type_tooltip)", _exc)

        try:
            self.cmbNetworkType.currentIndexChanged.connect(_sync_network_type_tooltip)
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:284 (_setup_tooltips)", _exc)
        _sync_network_type_tooltip()

        try:
            self.spinPpaK.setToolTip("각 유적(노드)에서 연결할 최근접 이웃 수 k입니다. (권장 3~5)")
            self.chkPpaMutualOnly.setToolTip(
                "상호 최근접(Mutual)일 때만 간선을 남깁니다.\n"
                "예) A의 최근접에 B가 포함되고, B의 최근접에도 A가 포함될 때만 연결."
            )
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:294 (_setup_tooltips)", _exc)

        try:
            self.cmbPpaGraph.setToolTip(
                "PPA 간선(그래프) 생성 규칙입니다.\n"
                "- k-NN: 각 노드에서 가까운 k개 연결\n"
                "- Threshold: 반경 내 모든 쌍 연결\n"
                "- Delaunay/Gabriel/RNG: 스파게티(과도한 간선)를 줄이는 대표적인 근접 그래프"
            )
            self.spinPpaMaxDist.setToolTip(
                "PPA 최대 거리(m) 필터입니다. 0이면 제한 없음.\n"
                "Threshold 그래프에서는 필수 파라미터(0이면 오류)입니다."
            )
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:308 (_setup_tooltips)", _exc)

        try:
            # Per-item tooltip (shown on hover in the dropdown)
            ppa_tips = {
                PPA_KNN: (
                    "k-NN (유클리드 거리)\n"
                    "- 각 노드에서 직선거리로 가까운 k개를 연결합니다.\n"
                    "- k가 커지면 간선이 급증하므로(스파게티) 보통 3~5 권장.\n\n"
                    "Ref:\n"
                    "- Terrell (1977) Human Biogeography in the Solomon Islands.\n"
                    "- Brughmans & Peeples (2017) Trends in archaeological network research."
                ),
                PPA_THRESHOLD: (
                    "Distance threshold (반경)\n"
                    "- 지정 반경 안의 모든 쌍을 연결합니다.\n"
                    "- Max dist(m)가 필수입니다(0이면 의미 없음).\n\n"
                    "Tip:\n"
                    "- 반경이 커지면 간선이 매우 많아질 수 있습니다."
                ),
                PPA_DELAUNAY: (
                    "Delaunay (삼각망)\n"
                    "- 점 집합의 Delaunay 삼각분할 간선만 남깁니다.\n"
                    "- '공간적 이웃'을 과도하게 연결하지 않으면서 전역 구조를 보기에 좋습니다.\n\n"
                    "Ref:\n"
                    "- Delaunay (1934) Sur la sphère vide.\n"
                    "- Okabe, Boots & Sugihara (1992) Spatial Tessellations."
                ),
                PPA_GABRIEL: (
                    "Gabriel graph\n"
                    "- Delaunay 간선 중 '원(지름 AB) 내부에 다른 점이 없을 때'만 남깁니다.\n"
                    "- Delaunay보다 더 희소(sparser)한 근접 그래프입니다.\n\n"
                    "Ref:\n"
                    "- Gabriel & Sokal (1969) A new statistical approach to geographic variation analysis."
                ),
                PPA_RNG: (
                    "RNG (Relative Neighborhood Graph)\n"
                    "- 간선 AB에 대해, A와 B에 동시에 더 가까운 점이 있으면 AB를 제거합니다.\n"
                    "- 매우 희소한 근접 그래프(스파게티 감소)에 유리합니다.\n\n"
                    "Ref:\n"
                    "- Toussaint (1980) The relative neighborhood graph of a finite planar set."
                ),
            }
            for idx in range(int(self.cmbPpaGraph.count())):
                key = str(self.cmbPpaGraph.itemData(idx) or "")
                tip = ppa_tips.get(key, "")
                if tip:
                    self.cmbPpaGraph.setItemData(idx, tip, Qt.ToolTipRole)

            def _sync_ppa_graph_tooltip():
                try:
                    tip = self.cmbPpaGraph.itemData(self.cmbPpaGraph.currentIndex(), Qt.ToolTipRole) or ""
                    self.cmbPpaGraph.setToolTip(str(tip))
                except Exception as _exc:
                    log_swallowed("tools/spatial_network_dialog.py:362 (_sync_ppa_graph_tooltip)", _exc)

            try:
                self.cmbPpaGraph.currentIndexChanged.connect(_sync_ppa_graph_tooltip)
            except Exception as _exc:
                log_swallowed("tools/spatial_network_dialog.py:367 (_setup_tooltips)", _exc)
            _sync_ppa_graph_tooltip()
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._setup_tooltips", _exc)

        try:
            vis_rule_tips = {
                VIS_RULE_MUTUAL: (
                    "Mutual(상호 보임)만 연결\n"
                    "- A↔B 양방향 모두 보일 때만 간선으로 간주합니다.\n"
                    "- '확실한 통신/감시' 관계만 남기고 싶을 때 권장."
                ),
                VIS_RULE_EITHER: (
                    "Either(단방향 포함)\n"
                    "- A→B 또는 B→A 중 하나라도 보이면 간선으로 간주합니다.\n"
                    "- 지형/높이 차로 단방향이 생길 수 있는 상황에서 탐색적으로 유용."
                ),
            }
            for idx in range(int(self.cmbVisEdgeRule.count())):
                key = str(self.cmbVisEdgeRule.itemData(idx) or "")
                tip = vis_rule_tips.get(key, "")
                if tip:
                    self.cmbVisEdgeRule.setItemData(idx, tip, Qt.ToolTipRole)

            def _sync_vis_rule_tooltip():
                try:
                    tip = self.cmbVisEdgeRule.itemData(self.cmbVisEdgeRule.currentIndex(), Qt.ToolTipRole) or ""
                    self.cmbVisEdgeRule.setToolTip(str(tip))
                except Exception as _exc:
                    log_swallowed("tools/spatial_network_dialog.py:396 (_sync_vis_rule_tooltip)", _exc)

            try:
                self.cmbVisEdgeRule.currentIndexChanged.connect(_sync_vis_rule_tooltip)
            except Exception as _exc:
                log_swallowed("tools/spatial_network_dialog.py:401 (_setup_tooltips)", _exc)
            _sync_vis_rule_tooltip()
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._setup_tooltips", _exc)

        try:
            self.chkCreateNodeMetrics.setToolTip(
                "노드(유적)별 네트워크 지표를 계산한 점 레이어를 추가합니다.\n"
                "기본: degree(연결 수), component(연결된 덩어리)."
            )
            self.chkCloseness.setToolTip("Closeness centrality(근접 중심성)를 계산합니다. 노드가 많으면 느릴 수 있습니다.")
            self.chkBetweenness.setToolTip(
                "Betweenness centrality(매개 중심성)를 계산합니다. 노드가 많으면 매우 느릴 수 있습니다.\n"
                "betweenness는 원시 쌍 개수, betw_norm은 (n-1)(n-2)/2로 나눈 정규화값입니다."
            )
            self.cmbVisEdgeRule.setToolTip(
                "가시성 네트워크에서 '연결'로 간주할 규칙입니다.\n"
                "- Mutual: A↔B 모두 보일 때만 연결\n"
                "- Either: A→B 또는 B→A 중 하나라도 보이면 연결"
            )
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:419 (_setup_tooltips)", _exc)

        try:
            self.btnInterpretGuide.setToolTip(
                "현재 선택한 네트워크(PPA/가시성) 결과를 어떻게 읽어야 하는지\n"
                "해석 가이드를 작은 창으로 표시합니다."
            )
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:427 (_setup_tooltips)", _exc)

    def _ensure_extra_widgets(self):
        """Create optional widgets at runtime (keeps .ui stable and avoids regressions)."""
        # --- PPA graph controls ---
        try:
            if not hasattr(self, "cmbPpaGraph"):
                self.lblPpaGraph = QtWidgets.QLabel("Graph", self.groupPpa)
                self.lblPpaGraph.setObjectName("lblPpaGraph")
                self.cmbPpaGraph = QtWidgets.QComboBox(self.groupPpa)
                self.cmbPpaGraph.setObjectName("cmbPpaGraph")

                self.lblPpaMaxDist = QtWidgets.QLabel("Max dist (m)", self.groupPpa)
                self.lblPpaMaxDist.setObjectName("lblPpaMaxDist")
                self.spinPpaMaxDist = QtWidgets.QDoubleSpinBox(self.groupPpa)
                self.spinPpaMaxDist.setObjectName("spinPpaMaxDist")
                self.spinPpaMaxDist.setDecimals(0)
                self.spinPpaMaxDist.setMinimum(0.0)
                self.spinPpaMaxDist.setMaximum(100000000.0)
                self.spinPpaMaxDist.setValue(0.0)
                self.spinPpaMaxDist.setSuffix(" m")

                try:
                    row = int(self.gridLayout_Ppa.rowCount())
                except Exception:
                    row = 2
                self.gridLayout_Ppa.addWidget(self.lblPpaGraph, row, 0)
                self.gridLayout_Ppa.addWidget(self.cmbPpaGraph, row, 1)
                self.gridLayout_Ppa.addWidget(self.lblPpaMaxDist, row + 1, 0)
                self.gridLayout_Ppa.addWidget(self.spinPpaMaxDist, row + 1, 1)
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._ensure_extra_widgets", _exc)

        # --- SNA metrics group ---
        try:
            if not hasattr(self, "groupSna"):
                self.groupSna = QtWidgets.QGroupBox("4. SNA 지표", self)
                self.groupSna.setObjectName("groupSna")
                grid = QtWidgets.QGridLayout(self.groupSna)
                grid.setObjectName("gridLayout_Sna")

                self.chkCreateNodeMetrics = QtWidgets.QCheckBox("노드 지표 레이어(점) 생성", self.groupSna)
                self.chkCreateNodeMetrics.setObjectName("chkCreateNodeMetrics")
                self.chkCreateNodeMetrics.setChecked(True)

                self.chkCloseness = QtWidgets.QCheckBox("Closeness 계산", self.groupSna)
                self.chkCloseness.setObjectName("chkCloseness")
                self.chkCloseness.setChecked(False)

                self.chkBetweenness = QtWidgets.QCheckBox("Betweenness 계산", self.groupSna)
                self.chkBetweenness.setObjectName("chkBetweenness")
                self.chkBetweenness.setChecked(False)

                self.lblVisEdgeRule = QtWidgets.QLabel("LOS 연결 규칙", self.groupSna)
                self.lblVisEdgeRule.setObjectName("lblVisEdgeRule")
                self.cmbVisEdgeRule = QtWidgets.QComboBox(self.groupSna)
                self.cmbVisEdgeRule.setObjectName("cmbVisEdgeRule")

                grid.addWidget(self.chkCreateNodeMetrics, 0, 0, 1, 4)
                grid.addWidget(self.chkCloseness, 1, 0, 1, 2)
                grid.addWidget(self.chkBetweenness, 1, 2, 1, 2)
                grid.addWidget(self.lblVisEdgeRule, 2, 0, 1, 1)
                grid.addWidget(self.cmbVisEdgeRule, 2, 1, 1, 3)

                # Insert above the button row.
                try:
                    idx = max(0, int(self.verticalLayout.count()) - 1)
                    self.verticalLayout.insertWidget(idx, self.groupSna)
                except Exception:
                    try:
                        self.verticalLayout.addWidget(self.groupSna)
                    except Exception as _exc:
                        log_swallowed("tools/spatial_network_dialog.py:499 (_ensure_extra_widgets)", _exc)
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._ensure_extra_widgets", _exc)

        # --- Visibility: earth curvature / refraction (same physics as viewshed_dialog) ---
        try:
            if not hasattr(self, "chkVisCurvature"):
                self.chkVisCurvature = QtWidgets.QCheckBox("지구 곡률 보정", self.groupVisibility)
                self.chkVisCurvature.setObjectName("chkVisCurvature")
                self.chkVisCurvature.setChecked(True)

                self.lblVisRefraction = QtWidgets.QLabel("굴절 계수", self.groupVisibility)
                self.lblVisRefraction.setObjectName("lblVisRefraction")
                self.spinVisRefraction = QtWidgets.QDoubleSpinBox(self.groupVisibility)
                self.spinVisRefraction.setObjectName("spinVisRefraction")
                self.spinVisRefraction.setDecimals(2)
                self.spinVisRefraction.setMinimum(0.0)
                self.spinVisRefraction.setMaximum(1.0)
                self.spinVisRefraction.setSingleStep(0.01)
                self.spinVisRefraction.setValue(LOS_DEFAULT_REFRACTION_K)

                try:
                    row = int(self.gridLayout_Vis.rowCount())
                except Exception as _exc:
                    log_swallowed("spatial_network_dialog._ensure_extra_widgets", _exc)
                    row = 7
                self.gridLayout_Vis.addWidget(self.chkVisCurvature, row, 0, 1, 2)
                self.gridLayout_Vis.addWidget(self.lblVisRefraction, row, 2)
                self.gridLayout_Vis.addWidget(self.spinVisRefraction, row, 3)

                try:
                    self.chkVisCurvature.toggled.connect(self._update_visibility_controls)
                except Exception as _exc:
                    log_swallowed("spatial_network_dialog._ensure_extra_widgets", _exc)
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._ensure_extra_widgets", _exc)

        # --- Interpretation guide button (kept in the button row to avoid increasing dialog height) ---
        try:
            if not hasattr(self, "btnInterpretGuide"):
                self.btnInterpretGuide = QtWidgets.QPushButton("해석 가이드", self)
                self.btnInterpretGuide.setObjectName("btnInterpretGuide")
                try:
                    from qgis.core import QgsApplication

                    self.btnInterpretGuide.setIcon(QgsApplication.getThemeIcon("/mActionHelpContents.svg"))
                except Exception as _exc:
                    log_swallowed("tools/spatial_network_dialog.py:513 (_ensure_extra_widgets)", _exc)

                # Insert just before "실행" so the main buttons stay at the right.
                try:
                    idx = int(self.horizontalLayout_Buttons.indexOf(self.btnRun))
                    if idx >= 0:
                        self.horizontalLayout_Buttons.insertWidget(idx, self.btnInterpretGuide)
                    else:
                        self.horizontalLayout_Buttons.addWidget(self.btnInterpretGuide)
                except Exception:
                    try:
                        self.horizontalLayout_Buttons.addWidget(self.btnInterpretGuide)
                    except Exception as _exc:
                        log_swallowed("tools/spatial_network_dialog.py:526 (_ensure_extra_widgets)", _exc)

                try:
                    self.btnInterpretGuide.clicked.connect(self._show_interpretation_guide)
                except Exception as _exc:
                    log_swallowed("tools/spatial_network_dialog.py:531 (_ensure_extra_widgets)", _exc)
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._ensure_extra_widgets", _exc)

    def _update_ppa_controls(self):
        """Enable/disable PPA controls depending on the selected graph rule."""
        method = PPA_KNN
        try:
            method = str(self.cmbPpaGraph.currentData() or PPA_KNN)
        except Exception:
            method = PPA_KNN

        use_knn = method == PPA_KNN
        use_thresh = method == PPA_THRESHOLD

        try:
            self.spinPpaK.setEnabled(use_knn)
            self.lblPpaK.setEnabled(use_knn)
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:550 (_update_ppa_controls)", _exc)
        try:
            self.chkPpaMutualOnly.setEnabled(use_knn)
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:554 (_update_ppa_controls)", _exc)

        try:
            self.spinPpaMaxDist.setEnabled((not use_knn))
            self.lblPpaMaxDist.setEnabled((not use_knn))
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:560 (_update_ppa_controls)", _exc)

        # If threshold mode is selected, make it visually clear that max distance is required.
        try:
            if use_thresh:
                self.spinPpaMaxDist.setStyleSheet("font-weight: bold;")
            else:
                self.spinPpaMaxDist.setStyleSheet("")
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:569 (_update_ppa_controls)", _exc)

        try:
            self.cmbPolyPointMode.setToolTip(
                "폴리곤을 노드(점)로 변환할 때 대표점을 선택합니다.\n"
                "- Point on surface: 폴리곤 내부 보장(권장)\n"
                "- Centroid: 중심점(폴리곤이 오목하면 밖으로 나갈 수 있음)"
            )
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:578 (_update_ppa_controls)", _exc)

        try:
            self.spinObsHeight.setToolTip("관측자 높이(m): DEM 지표면 위 추가 높이.")
            self.spinTgtHeight.setToolTip("대상 높이(m): DEM 지표면 위 추가 높이.")
            self.spinCandidateK.setToolTip(
                "각 노드에서 LOS 후보로 검사할 최근접 이웃 수입니다.\n"
                "값이 커질수록 정확도는 올라가지만 계산 시간이 증가합니다."
            )
            self.spinMaxDist.setToolTip(
                "최대 검사 거리(m). 0이면 제한 없음.\n"
                "거리 제한을 두면 계산량이 크게 줄어듭니다."
            )
            self.spinSampleStep.setToolTip(
                "LOS 샘플링 간격(m). 작을수록 정확하지만 느립니다.\n"
                "0 또는 너무 작으면 DEM 픽셀 크기를 기준으로 자동 보정됩니다."
            )
            self.chkVisAllPairs.setToolTip(
                "체크하면 후보 k 제한을 무시하고 (최대 거리 내) 모든 쌍을 LOS로 검사합니다.\n"
                "노드가 많으면 시간이 오래 걸릴 수 있습니다."
            )
            self.chkPolyBoundaryVis.setToolTip(
                "입력 레이어가 폴리곤일 때, 관측 폴리곤의 경계 샘플점 여러 곳에서 상대 유적의 대표점 1개가 보이는지 검사합니다.\n"
                "vis_ratio_ab = A의 경계 샘플 중 B의 대표점이 보이는 비율(0-1). B가 얼마나 보이는가가 아닙니다.\n"
                "vis_ab는 샘플 1개라도 보이면 1입니다. (느릴 수 있음)"
            )
            self.spinPolyBoundaryStep.setToolTip("폴리곤 경계에서 샘플 점을 뽑는 간격(m)입니다.")
            self.spinPolyMaxBoundaryPts.setToolTip("폴리곤 1개당 경계 샘플 점의 최대 개수(속도 제한)입니다.")
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:606 (_update_ppa_controls)", _exc)

        try:
            self.chkVisCurvature.setToolTip(
                "지구 곡률 보정(기본 켬): 관측점에서 수평거리 d인 샘플 지형고도(대상점 포함)에서 cc*d^2/(2R)을 뺍니다.\n"
                "R = 6,371,000 m, cc = 1 - 굴절 계수. 가시권 분석 도구 / gdal_viewshed -cc 와 같은 식입니다.\n"
                "끄면 평면 시선(cc = 0)으로 판정하며, 장거리 쌍에서 '보임'이 늘어날 수 있습니다(25 km에서 약 10 m 차이)."
            )
            self.spinVisRefraction.setToolTip(
                "대기 굴절 계수 k (기본 0.13, 표준 대기). cc = 1 - k 로 곡률 보정량을 줄입니다.\n"
                "0이면 순수 곡률만 적용, 1이면 보정 없음과 같습니다. '지구 곡률 보정'을 켠 경우에만 쓰입니다."
            )
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._update_ppa_controls", _exc)

    def _interpretation_guide_html(self) -> str:
        mode = None
        try:
            mode = str(self.cmbNetworkType.currentData() or "")
        except Exception:
            mode = ""

        if is_english_ui():
            ppa = """
            <h3>Proximity Network (PPA)</h3>
            <p><b>What does it show?</b><br>
            It links sites using <b>straight-line (Euclidean) distance</b> only, without terrain cost.
            It is useful for quickly checking neighborhood-style interaction hypotheses.</p>

            <p><b>How should the outputs be read?</b><br>
            <ul>
              <li><b>Edge layer</b>: neighborhood connections between sites. <code>dist_km</code> stores straight-line distance.</li>
              <li><b>Node layer (SNA)</b>: <code>degree</code>, <code>component</code>, and <code>comp_size</code> summarize local and network structure.</li>
            </ul></p>

            <p><b>How can I reduce spaghetti-like edges?</b><br>
            <ul>
              <li><b>Mutual k-NN</b>: keeps only reciprocal neighbors.</li>
              <li><b>Gabriel / RNG</b>: keeps only more essential proximity edges derived from Delaunay.</li>
              <li><b>Max dist (m)</b>: removes unrealistically long links.</li>
            </ul></p>
            """

            vis = """
            <h3>Visibility Network (LOS)</h3>
            <p><b>What does it show?</b><br>
            It samples the DEM with line-of-sight tests to ask whether site A and site B can see each other.
            It fits questions about watch, signaling, defense, or communication systems.</p>

            <p><b>How should the outputs be read?</b><br>
            <ul>
              <li><b>Edge layer</b>: the <code>status</code> field distinguishes mutually visible, one-way visible, mutually hidden, and failed samples.</li>
              <li><b>Directionality</b>: <code>vis_ab</code> and <code>vis_ba</code> store A->B and B->A separately.</li>
              <li><b>Polygon input</b>: with boundary sampling, <code>vis_ratio_ab</code> is the share of A's boundary samples
                  from which B's representative point is visible (not how much of B is visible);
                  <code>vis_ab</code> is 1 if any sample sees it.</li>
              <li><b>Failed samples</b>: pairs that could not be tested (DEM NoData) get <code>status</code> = failed;
                  the node layer's <code>fail_deg</code> counts them, so degree 0 can mean untested rather than hidden.</li>
              <li><b>Curvature / refraction</b>: applied by default (refraction coefficient 0.13; the same drop
                  cc*d^2/(2R) as the viewshed tool). Uncheck <b>earth curvature</b> for a flat sight line.
                  The setting, heights, step and distance limits are stored in the layer metadata (params_json).</li>
            </ul></p>

            <p><b>How can I reduce runtime?</b><br>
            <ul>
              <li><b>Candidate k</b>: tests only nearby candidates for each node.</li>
              <li><b>All pairs in range</b>: use only for small datasets when exhaustive checking matters.</li>
              <li><b>Max dist (m)</b>: skips distant pairs entirely.</li>
            </ul></p>
            """

            sna = """
            <h3>SNA Metrics (Point Layer)</h3>
            <p><b>Why use them?</b><br>
            They help identify hubs, strategic intermediaries, isolation, and network fragmentation numerically.</p>
            <ul>
              <li><code>degree</code>: number of links.</li>
              <li><code>component</code> / <code>comp_size</code>: disconnected sub-networks and their sizes.</li>
              <li><code>closeness</code>: how near a node is to the rest of the network
                  (Wasserman&ndash;Faust corrected: scores are scaled by the share of the
                  network the node can reach, so isolated pairs no longer score highest).</li>
              <li><code>betweenness</code>: how strongly a node acts as a bridge between others. Raw Brandes pair counts
                  (undirected, halved), not normalised; use <code>betw_norm</code> (= betweenness / ((n-1)(n-2)/2)) to compare
                  with NetworkX/Gephi defaults or across networks of different size.</li>
            </ul>
            """

            refs = """
            <h3>References (summary)</h3>
            <ul>
              <li>Proximity graphs: Delaunay (1934), Gabriel &amp; Sokal (1969), Toussaint (1980)</li>
              <li>Archaeological network review: Brughmans &amp; Peeples (2017)</li>
              <li>Intervisibility networks (context): Gillings &amp; Wheatley (2001), Van Dyke et al. (2016)</li>
              <li>(C) Background only: Turner et al. (2001) grid-based VGA. This tool builds a site-to-site
                  intervisibility network; it does not compute VGA measures (visual integration etc.).</li>
            </ul>
            """

            body = vis + sna + ppa if mode == NETWORK_VISIBILITY else ppa + sna + vis
            return "".join(
                (
                    "<html><head><meta charset='utf-8'></head><body style='font-family:Sans-Serif;'>",
                    "<h2>Network Interpretation Guide</h2>",
                    "<p style='color:#444'>Tip: hover over each option to see a short explanation and reference note.</p>",
                    body,
                    refs,
                    "</body></html>",
                )
            )

        # Keep it practical: how to read the output layers/fields and when to use each option.
        ppa = """
        <h3>근접성 네트워크 (PPA)</h3>
        <p><b>무엇을 보는가?</b><br>
        지형(DEM)을 무시하고 <b>직선거리(유클리드)</b>로 “이웃” 관계를 연결합니다.
        평원/도서 지역처럼 지형 영향이 약한 환경이나, <b>‘이웃 공동체’</b> 가설을 빠르게 점검할 때 유용합니다.</p>

        <p><b>결과를 어떻게 읽나?</b><br>
        <ul>
          <li><b>Edge 레이어</b>: 유적 간 “이웃” 연결. <code>dist_km</code>는 직선거리(km).</li>
          <li><b>Nodes 레이어(SNA)</b>: <code>degree</code>(연결 수), <code>component</code>(연결 덩어리), <code>comp_size</code>(덩어리 크기).</li>
        </ul></p>

        <p><b>스파게티(선 과다) 줄이는 팁</b><br>
        <ul>
          <li><b>Mutual k‑NN</b>: 서로의 k 안에 들어갈 때만 연결(더 보수적).</li>
          <li><b>Gabriel/RNG</b>: Delaunay에서 더 “필요한” 간선만 남겨 희소화.</li>
          <li><b>Max dist(m)</b>: 너무 먼 간선은 제거(현실적 상호작용 범위 반영).</li>
        </ul></p>
        """

        vis = """
        <h3>가시성 네트워크 (Visibility / LOS)</h3>
        <p><b>무엇을 보는가?</b><br>
        DEM 기반 Line of Sight(가시선)으로 유적 A↔B 사이에 지형이 시선을 가리는지 샘플링해 연결합니다.
        방어·봉수·감시/통신 체계처럼 <b>‘보이는가’</b>가 핵심인 질문에 적합합니다.</p>

        <p><b>결과를 어떻게 읽나?</b><br>
        <ul>
          <li><b>Edge 레이어(LOS)</b>: <code>status</code>로 “상호 보임/단방향 보임/상호 안보임/샘플 실패”를 구분합니다.</li>
          <li><b>방향성</b>: <code>vis_ab</code>, <code>vis_ba</code> (0/1)로 A→B, B→A를 따로 기록합니다.</li>
          <li><b>폴리곤 입력</b>: 경계 샘플링을 켜면 <code>vis_ratio_ab</code>(0-1)는 “A의 경계 샘플 중 B의 대표점이 보이는 비율”입니다
              (B가 얼마나 보이는가가 아님). <code>vis_ab</code>는 샘플 1개라도 보이면 1입니다.</li>
          <li><b>샘플 실패</b>: DEM NoData 등으로 검사하지 못한 쌍은 <code>status</code>=“샘플 실패”이며,
              노드 레이어의 <code>fail_deg</code>가 그 개수입니다. degree 0은 “안 보임”이 아니라 “검사 불가”일 수 있습니다.</li>
          <li><b>곡률·굴절 보정</b>: 기본 적용, 계수 0.13 (가시권 분석 도구와 같은 식 cc·d²/(2R)).
              <b>지구 곡률 보정</b>을 끄면 평면 시선으로 판정합니다. 보정 설정·높이·샘플 간격·거리 제한은
              결과 레이어 메타데이터(params_json)에 기록됩니다.</li>
        </ul></p>

        <p><b>연산량 줄이는 팁</b><br>
        <ul>
          <li><b>후보 k</b>: 각 노드에서 가까운 후보만 검사(빠름).</li>
          <li><b>반경 내 모든 쌍</b>: 작은 데이터에만 권장(정확하지만 느림).</li>
          <li><b>Max dist(m)</b>: 먼 쌍은 애초에 검사하지 않음.</li>
        </ul></p>
        """

        sna = """
        <h3>SNA 지표(점 레이어)</h3>
        <p><b>왜 필요한가?</b><br>
        “선 몇 개”로 끝나지 않고, <b>중심지/요충지/고립</b>이 어디인지 수치로 드러내기 위함입니다.</p>
        <ul>
          <li><code>degree</code>: 연결 수(많을수록 ‘허브’ 후보).</li>
          <li><code>component</code>/<code>comp_size</code>: 네트워크가 몇 덩어리로 끊기는지, 각 덩어리의 크기.</li>
          <li><code>closeness</code>: 전체에 ‘가까운’ 정도. Wasserman–Faust 보정 적용:
              도달 가능한 노드 비율(r/(n−1))을 곱해, 고립된 소규모 컴포넌트가
              만점을 받는 왜곡을 제거했습니다. (노드가 많으면 느릴 수 있음)</li>
          <li><code>betweenness</code>: 다른 노드 사이를 ‘중개’하는 정도(매우 느릴 수 있어 큰 데이터는 자동 스킵될 수 있음).
              값은 정규화하지 않은 Brandes 원시 최단경로 쌍 개수(무방향 x0.5)입니다. NetworkX/Gephi 기본값과 비교하거나
              크기가 다른 네트워크끼리 비교하려면 <code>betw_norm</code>(= betweenness / ((n-1)(n-2)/2)) 필드를 쓰세요.</li>
        </ul>
        """

        refs = """
        <h3>참고(요약)</h3>
        <ul>
          <li>근접 그래프: Delaunay(1934), Gabriel &amp; Sokal(1969), Toussaint(1980)</li>
          <li>고고학 네트워크 리뷰: Brughmans &amp; Peeples(2017)</li>
          <li>상호가시성 네트워크(해석 맥락): Gillings &amp; Wheatley(2001), Van Dyke et al.(2016)</li>
          <li>(C) 참고: Turner et al.(2001) 격자 기반 VGA; 이 도구는 유적 간 상호가시성 네트워크이며 VGA 지표는 계산하지 않습니다.</li>
        </ul>
        """

        body = ""
        if mode == NETWORK_VISIBILITY:
            body = vis + sna + ppa
        else:
            body = ppa + sna + vis

        return "".join(
            (
                "<html><head><meta charset='utf-8'></head><body style='font-family:Sans-Serif;'>",
                "<h2>네트워크 해석 가이드</h2>",
                "<p style='color:#444'>Tip: 각 옵션 위에 마우스를 올리면 짧은 설명/참고문헌을 바로 볼 수 있어요.</p>",
                body,
                refs,
                "</body></html>",
            )
        )

    def _show_interpretation_guide(self):
        try:
            # Reuse if already open (prevents multiple floating dialogs).
            if getattr(self, "_interpretGuideDialog", None) is not None:
                try:
                    if self._interpretGuideDialog.isVisible():
                        self._interpretGuideBrowser.setHtml(self._interpretation_guide_html())
                        self._interpretGuideDialog.raise_()
                        self._interpretGuideDialog.activateWindow()
                        return
                except Exception as _exc:
                    log_swallowed("tools/spatial_network_dialog.py:785 (_show_interpretation_guide)", _exc)

            dlg = QtWidgets.QDialog(self)
            dlg.setAttribute(Qt.WA_DeleteOnClose, True)
            dlg.setWindowTitle("해석 가이드 (Network Interpretation)")
            dlg.resize(560, 520)

            layout = QtWidgets.QVBoxLayout(dlg)
            browser = QtWidgets.QTextBrowser(dlg)
            browser.setOpenExternalLinks(True)
            browser.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
            browser.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
            browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            browser.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            browser.setHtml(self._interpretation_guide_html())
            layout.addWidget(browser)

            row = QtWidgets.QHBoxLayout()
            btn_copy = QtWidgets.QPushButton("복사", dlg)
            btn_close = QtWidgets.QPushButton("닫기", dlg)
            row.addStretch(1)
            row.addWidget(btn_copy)
            row.addWidget(btn_close)
            layout.addLayout(row)

            def _copy():
                try:
                    QtWidgets.QApplication.clipboard().setText(browser.toPlainText())
                except Exception as _exc:
                    log_swallowed("tools/spatial_network_dialog.py:814 (_copy)", _exc)

            btn_copy.clicked.connect(_copy)
            btn_close.clicked.connect(dlg.close)

            # Keep python refs for stability (avoid GC on modeless dialogs).
            self._interpretGuideDialog = dlg
            self._interpretGuideBrowser = browser

            def _clear_refs():
                try:
                    self._interpretGuideDialog = None
                    self._interpretGuideBrowser = None
                except Exception as _exc:
                    log_swallowed("tools/spatial_network_dialog.py:828 (_clear_refs)", _exc)

            try:
                dlg.destroyed.connect(lambda _=None: _clear_refs())
            except Exception as _exc:
                log_swallowed("tools/spatial_network_dialog.py:833 (_show_interpretation_guide)", _exc)

            dlg.show()
        except Exception as e:
            log_message(f"InterpretGuide: failed to open guide dialog: {e}", level=Qgis.Warning)

    def _on_mode_changed(self):
        mode = self.cmbNetworkType.currentData()
        is_ppa = mode == NETWORK_PPA
        is_vis = mode == NETWORK_VISIBILITY

        try:
            self.groupPpa.setVisible(is_ppa)
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:847 (_on_mode_changed)", _exc)
        try:
            self.groupVisibility.setVisible(is_vis)
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:851 (_on_mode_changed)", _exc)
        try:
            # Visibility edge rule is only meaningful for LOS.
            self.lblVisEdgeRule.setEnabled(is_vis)
            self.cmbVisEdgeRule.setEnabled(is_vis)
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:857 (_on_mode_changed)", _exc)

        try:
            self._update_ppa_controls()
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:862 (_on_mode_changed)", _exc)
        self._update_visibility_controls()

    def _update_visibility_controls(self):
        """Show/hide/enable advanced visibility options based on mode + input geometry."""
        mode = None
        try:
            mode = self.cmbNetworkType.currentData()
        except Exception:
            mode = None

        is_vis = mode == NETWORK_VISIBILITY
        site_layer = None
        try:
            site_layer = self.cmbSiteLayer.currentLayer()
        except Exception:
            site_layer = None

        is_polygon_layer = False
        try:
            if site_layer and site_layer.isValid():
                is_polygon_layer = site_layer.geometryType() == QgsWkbTypes.PolygonGeometry
        except Exception:
            is_polygon_layer = False

        # Candidate-k is irrelevant when all-pairs is enabled.
        all_pairs = False
        try:
            all_pairs = bool(self.chkVisAllPairs.isChecked())
        except Exception:
            all_pairs = False

        try:
            self.spinCandidateK.setEnabled(is_vis and (not all_pairs))
            self.lblCandidateK.setEnabled(is_vis and (not all_pairs))
        except Exception as _exc:
            log_swallowed("tools/spatial_network_dialog.py:898 (_update_visibility_controls)", _exc)

        show_poly = bool(is_vis and is_polygon_layer)
        poly_enabled = False
        try:
            poly_enabled = bool(self.chkPolyBoundaryVis.isChecked())
        except Exception:
            poly_enabled = False

        for w in ("chkPolyBoundaryVis",):
            try:
                getattr(self, w).setVisible(show_poly)
            except Exception as _exc:
                log_swallowed("tools/spatial_network_dialog.py:911 (_update_visibility_controls)", _exc)

        for w in ("lblPolyBoundaryStep", "spinPolyBoundaryStep", "lblPolyMaxPts", "spinPolyMaxBoundaryPts"):
            try:
                getattr(self, w).setVisible(show_poly and poly_enabled)
            except Exception as _exc:
                log_swallowed("tools/spatial_network_dialog.py:917 (_update_visibility_controls)", _exc)

        # The refraction coefficient only matters while curvature is applied.
        try:
            curv_on = bool(self.chkVisCurvature.isChecked())
            self.spinVisRefraction.setEnabled(curv_on)
            self.lblVisRefraction.setEnabled(curv_on)
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._update_visibility_controls", _exc)

    def _on_site_layer_changed(self, layer):
        # Populate name fields (string-ish fields only)
        try:
            self.cmbNameField.blockSignals(True)
            self.cmbNameField.clear()
            self.cmbNameField.addItem("(FID 사용)", "")

            if layer and layer.isValid():
                for f in layer.fields():
                    _skip_929 = False
                    try:
                        if f.type() in (QVariant.String, QVariant.Int, QVariant.LongLong):
                            self.cmbNameField.addItem(f.name(), f.name())
                    except Exception as _exc:
                        log_swallowed("tools/spatial_network_dialog.py:932 (_on_site_layer_changed)", _exc)
                        _skip_929 = True
                    if _skip_929:
                        continue
        finally:
            try:
                self.cmbNameField.blockSignals(False)
            except Exception as _exc:
                log_swallowed("tools/spatial_network_dialog.py:937 (_on_site_layer_changed)", _exc)

        self._update_visibility_controls()

    def _collect_nodes(
        self,
        *,
        layer,
        name_field: str,
        poly_mode: str,
        use_selected_only: bool,
        target_crs,
        collect_polygon_boundary: bool = False,
        boundary_step_m: float = 50.0,
        boundary_max_points: int = 30,
    ) -> List[_Node]:
        feats = []
        try:
            if use_selected_only:
                feats = layer.selectedFeatures()
            else:
                feats = list(layer.getFeatures())
        except Exception:
            feats = layer.selectedFeatures() if use_selected_only else []

        nodes: List[_Node] = []
        skipped = 0

        ct = None
        try:
            if layer.crs() != target_crs:
                ct = QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance())
        except Exception:
            ct = None

        for ft in feats:
            try:
                geom = ft.geometry()
                if geom is None or geom.isEmpty():
                    skipped += 1
                    continue

                is_polygon = geom.type() == QgsWkbTypes.PolygonGeometry

                # Work in target CRS (meters expected for distance-based tools)
                geom_t = geom
                if ct is not None:
                    try:
                        geom_t = QgsGeometry(geom)
                        geom_t.transform(ct)
                    except Exception:
                        geom_t = geom

                pt_t = None
                if geom_t.type() == QgsWkbTypes.PointGeometry:
                    if geom_t.isMultipart():
                        mp = geom_t.asMultiPoint()
                        if mp:
                            pt_t = QgsPointXY(mp[0])
                    else:
                        pt_t = QgsPointXY(geom_t.asPoint())
                elif geom_t.type() == QgsWkbTypes.PolygonGeometry:
                    gpt = geom_t.pointOnSurface() if poly_mode == "surface" else geom_t.centroid()
                    if gpt is not None and (not gpt.isEmpty()):
                        pt_t = QgsPointXY(gpt.asPoint())
                else:
                    skipped += 1
                    continue

                if pt_t is None:
                    skipped += 1
                    continue

                fid = str(ft.id())

                name = fid
                if name_field:
                    try:
                        v = ft[name_field]
                        if v is not None and str(v).strip() != "":
                            name = str(v)
                    except Exception as _exc:
                        log_swallowed("tools/spatial_network_dialog.py:1019 (_collect_nodes)", _exc)

                samples: Tuple[Tuple[float, float], ...] = ((float(pt_t.x()), float(pt_t.y())),)
                if is_polygon and collect_polygon_boundary:
                    try:
                        step = float(boundary_step_m or 0.0)
                    except Exception:
                        step = 50.0
                    try:
                        mx = int(boundary_max_points or 0)
                    except Exception:
                        mx = 30
                    pts = self._sample_polygon_boundary_points(geom_t, step_m=step, max_points=mx)
                    if pts:
                        samples = pts

                nodes.append(
                    _Node(
                        fid=fid,
                        name=name,
                        x=float(pt_t.x()),
                        y=float(pt_t.y()),
                        samples=samples,
                        is_polygon=bool(is_polygon),
                    )
                )
            except Exception:
                skipped += 1

        if skipped:
            log_message(f"SpatialNetwork: skipped {skipped} feature(s) (empty/unsupported geometry)", level=Qgis.Warning)
        return nodes

    def _sample_polygon_boundary_points(
        self,
        geom_t: QgsGeometry,
        *,
        step_m: float,
        max_points: int,
    ) -> Tuple[Tuple[float, float], ...]:
        """Sample points along polygon boundary in *target CRS units* (meters expected)."""
        try:
            boundary = geom_t.boundary()
        except Exception:
            boundary = None

        if boundary is None or boundary.isEmpty():
            return ()

        try:
            length = float(boundary.length() or 0.0)
        except Exception:
            length = 0.0

        if length <= 0:
            return ()

        try:
            step = float(step_m or 0.0)
        except Exception:
            step = 0.0
        if step <= 0:
            step = 50.0

        try:
            mx = int(max_points or 0)
        except Exception:
            mx = 0
        if mx > 0:
            # Enforce a cap by increasing the step when needed.
            step = max(step, length / float(mx))

        try:
            num = int(length / step) + 1
        except Exception:
            num = 1
        num = max(1, num)

        pts: List[Tuple[float, float]] = []
        for i in range(num + 1):
            d = min(length, float(i) * step)
            try:
                p = boundary.interpolate(d)
            except Exception:
                p = None
            if p is None or p.isEmpty():
                continue
            _skip_1107 = False
            try:
                pt = p.asPoint()
                pts.append((float(pt.x()), float(pt.y())))
            except Exception as _exc:
                log_swallowed("spatial_network_dialog._sample_polygon_boundary_points", _exc)
                log_swallowed("tools/spatial_network_dialog.py:1110 (_sample_polygon_boundary_points)", _exc)
                _skip_1107 = True
            if _skip_1107:
                continue

        # Deduplicate (rounded to reduce near-duplicates from interpolation).
        uniq: List[Tuple[float, float]] = []
        seen: Set[Tuple[int, int]] = set()
        for x, y in pts:
            k = (int(round(x * 1000.0)), int(round(y * 1000.0)))
            if k in seen:
                continue
            seen.add(k)
            uniq.append((x, y))

        return tuple(uniq)

    def _ensure_metric(self, crs, title: str) -> bool:
        if is_metric_crs(crs):
            # Web Mercator passes the metre check, but its scale factor is
            # 1/cos(lat): every planar distance in this tool is ~26% long at
            # 37.5N, and so is every distance threshold. Warn, do not block.
            try:
                authid = str(crs.authid() or "").upper()
                desc = str(crs.description() or "").lower()
                if authid in ("EPSG:3857", "EPSG:900913", "EPSG:3785") or "pseudo-mercator" in desc or "web mercator" in desc:
                    push_message(
                        self.iface, title,
                        "Web Mercator(EPSG:3857)는 미터 단위지만 한국 위도에서 거리가 약 26% 과대합니다. "
                        "거리·임계값이 중요하면 EPSG:5186 등 한국 투영좌표계로 재투영하세요.",
                        level=1, duration=10,
                    )
                    log_message("CRS가 Web Mercator입니다: 거리와 임계값이 위도에 따라 과대(37.5N에서 약 1.26배).", level=Qgis.Warning)
            except Exception as _exc:
                log_swallowed("spatial_network_dialog._ensure_metric", _exc)
            return True
        push_message(
            self.iface,
            title,
            "CRS 단위가 미터가 아닙니다. (권장: 투영좌표계/미터) 레이어를 재투영 후 다시 시도해주세요.",
            level=2,
            duration=8,
        )
        return False

    def run_analysis(self):
        mode = self.cmbNetworkType.currentData()

        site_layer = self.cmbSiteLayer.currentLayer()
        if site_layer is None or (not site_layer.isValid()):
            push_message(self.iface, "네트워크", "입력 유적(벡터) 레이어를 선택해주세요.", level=2)
            restore_ui_focus(self)
            return

        use_selected = bool(self.chkSelectedOnly.isChecked())
        if use_selected and site_layer.selectedFeatureCount() < 2:
            push_message(self.iface, "네트워크", "선택 피처가 2개 이상 필요합니다.", level=2)
            restore_ui_focus(self)
            return

        # Live log window (non-modal) so users can see progress in real time.
        ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)

        name_field = str(self.cmbNameField.currentData() or "")
        poly_mode = str(self.cmbPolyPointMode.currentData() or "surface")

        if mode == NETWORK_PPA:
            if not self._ensure_metric(site_layer.crs(), "PPA"):
                restore_ui_focus(self)
                return

            nodes = self._collect_nodes(
                layer=site_layer,
                name_field=name_field,
                poly_mode=poly_mode,
                use_selected_only=use_selected,
                target_crs=site_layer.crs(),
            )
            if len(nodes) < 2:
                push_message(self.iface, "PPA", "유효한 노드가 2개 이상 필요합니다.", level=2)
                restore_ui_focus(self)
                return

            k = int(self.spinPpaK.value())
            mutual = bool(self.chkPpaMutualOnly.isChecked())
            method = str(getattr(self, "cmbPpaGraph", None).currentData() if hasattr(self, "cmbPpaGraph") else PPA_KNN)
            try:
                max_dist_m = float(self.spinPpaMaxDist.value()) if hasattr(self, "spinPpaMaxDist") else 0.0
            except Exception:
                max_dist_m = 0.0

            make_nodes = bool(getattr(self, "chkCreateNodeMetrics", None) and self.chkCreateNodeMetrics.isChecked())
            do_close = bool(getattr(self, "chkCloseness", None) and self.chkCloseness.isChecked())
            do_betw = bool(getattr(self, "chkBetweenness", None) and self.chkBetweenness.isChecked())

            self._run_ppa(
                nodes,
                method=method,
                k=k,
                mutual_only=mutual,
                max_dist_m=max_dist_m,
                create_node_metrics=make_nodes,
                compute_closeness=do_close,
                compute_betweenness=do_betw,
            )
            return

        # Visibility network
        dem_layer = self.cmbDemLayer.currentLayer()
        if dem_layer is None or (not dem_layer.isValid()):
            push_message(self.iface, "가시성 네트워크", "DEM(래스터) 레이어를 선택해주세요.", level=2)
            restore_ui_focus(self)
            return
        if not self._ensure_metric(dem_layer.crs(), "가시성 네트워크"):
            restore_ui_focus(self)
            return

        poly_boundary = False
        boundary_step = 50.0
        boundary_max_pts = 30
        try:
            poly_boundary = bool(self.chkPolyBoundaryVis.isChecked())
        except Exception:
            poly_boundary = False
        try:
            boundary_step = float(self.spinPolyBoundaryStep.value())
        except Exception:
            boundary_step = 50.0
        try:
            boundary_max_pts = int(self.spinPolyMaxBoundaryPts.value())
        except Exception:
            boundary_max_pts = 30

        nodes = self._collect_nodes(
            layer=site_layer,
            name_field=name_field,
            poly_mode=poly_mode,
            use_selected_only=use_selected,
            target_crs=dem_layer.crs(),
            collect_polygon_boundary=poly_boundary,
            boundary_step_m=boundary_step,
            boundary_max_points=boundary_max_pts,
        )
        if len(nodes) < 2:
            push_message(self.iface, "가시성 네트워크", "유효한 노드가 2개 이상 필요합니다.", level=2)
            restore_ui_focus(self)
            return

        obs_h = float(self.spinObsHeight.value())
        tgt_h = float(self.spinTgtHeight.value())
        cand_k = int(self.spinCandidateK.value())
        max_dist = float(self.spinMaxDist.value())
        step_m = float(self.spinSampleStep.value())

        # Curvature/refraction controls are created at runtime; default to the
        # viewshed tool's behaviour (curvature on, k = 0.13) if they are missing.
        curvature_on = True
        refraction_k = LOS_DEFAULT_REFRACTION_K
        try:
            curvature_on = bool(self.chkVisCurvature.isChecked())
        except Exception as _exc:
            log_swallowed("spatial_network_dialog.run_analysis", _exc)
            curvature_on = True
        try:
            refraction_k = float(self.spinVisRefraction.value())
        except Exception as _exc:
            log_swallowed("spatial_network_dialog.run_analysis", _exc)
            refraction_k = LOS_DEFAULT_REFRACTION_K

        make_nodes = bool(getattr(self, "chkCreateNodeMetrics", None) and self.chkCreateNodeMetrics.isChecked())
        do_close = bool(getattr(self, "chkCloseness", None) and self.chkCloseness.isChecked())
        do_betw = bool(getattr(self, "chkBetweenness", None) and self.chkBetweenness.isChecked())
        vis_rule = str(
            getattr(self, "cmbVisEdgeRule", None).currentData()
            if hasattr(self, "cmbVisEdgeRule")
            else VIS_RULE_MUTUAL
        )

        self._run_visibility_network(
            dem_layer=dem_layer,
            nodes=nodes,
            obs_height=obs_h,
            tgt_height=tgt_h,
            candidate_k=cand_k,
            max_dist=max_dist,
            sample_step_m=step_m,
            use_poly_boundary_ratio=poly_boundary,
            create_node_metrics=make_nodes,
            compute_closeness=do_close,
            compute_betweenness=do_betw,
            vis_edge_rule=vis_rule,
            curvature=curvature_on,
            refraction_coeff=refraction_k,
            poly_boundary_step_m=boundary_step,
            poly_boundary_max_points=boundary_max_pts,
        )

    def _run_ppa(
        self,
        nodes: List[_Node],
        *,
        method: str,
        k: int,
        mutual_only: bool,
        max_dist_m: float,
        create_node_metrics: bool,
        compute_closeness: bool,
        compute_betweenness: bool,
    ):
        n = int(len(nodes))
        if n < 2:
            return

        method = str(method or PPA_KNN)
        max_dist_m = float(max_dist_m or 0.0)
        if max_dist_m < 0:
            max_dist_m = 0.0

        coords = np.array([(float(nd.x), float(nd.y)) for nd in nodes], dtype=np.float64)

        if method == PPA_THRESHOLD and max_dist_m <= 0.0:
            push_message(self.iface, "PPA", "Threshold 그래프는 '최대 거리(m)'가 필요합니다. (0보다 크게)", level=2)
            restore_ui_focus(self)
            return

        # --- Build edges ---
        edges: Set[Tuple[int, int]] = set()

        if method == PPA_KNN:
            k_eff = max(1, min(int(k), max(1, n - 1)))
            log_message(f"PPA: k-NN building (n={n}, k={k_eff}, mutual={bool(mutual_only)})", level=Qgis.Info)

            neigh: List[Set[int]] = [set() for _ in range(n)]
            for i in range(n):
                d2 = (coords[:, 0] - coords[i, 0]) ** 2 + (coords[:, 1] - coords[i, 1]) ** 2
                d2[i] = np.inf
                nn = np.argsort(d2)[:k_eff]
                for j in nn:
                    neigh[i].add(int(j))

            for i in range(n):
                for j in neigh[i]:
                    a, b = (i, j) if i < j else (j, i)
                    if mutual_only:
                        if i in neigh[j]:
                            edges.add((a, b))
                    else:
                        edges.add((a, b))

            layer_name = f"PPA_kNN_{k_eff}" + ("_mutual" if mutual_only else "")

        elif method == PPA_THRESHOLD:
            r2 = float(max_dist_m) ** 2
            log_message(f"PPA: threshold building (n={n}, max_dist_m={max_dist_m})", level=Qgis.Info)
            for i in range(n - 1):
                dx = coords[i + 1 :, 0] - coords[i, 0]
                dy = coords[i + 1 :, 1] - coords[i, 1]
                d2 = dx * dx + dy * dy
                js = np.where(d2 <= r2)[0]
                for j_off in js:
                    j = int(i + 1 + int(j_off))
                    edges.add((i, j))
            layer_name = f"PPA_threshold_{int(round(max_dist_m))}m"

        else:
            crs_authid = (
                self.cmbSiteLayer.currentLayer().crs().authid()
                if self.cmbSiteLayer.currentLayer()
                else QgsProject.instance().crs().authid()
            )
            cand = self._ppa_delaunay_edges(nodes=nodes, crs_authid=crs_authid)
            if not cand:
                push_message(self.iface, "PPA", "Delaunay 기반 간선을 만들 수 없습니다. (점이 너무 적거나 중복일 수 있음)", level=2)
                restore_ui_focus(self)
                return

            if method == PPA_GABRIEL:
                edges = self._ppa_filter_gabriel(cand_edges=cand, coords=coords)
                layer_name = "PPA_gabriel"
            elif method == PPA_RNG:
                edges = self._ppa_filter_rng(cand_edges=cand, coords=coords)
                layer_name = "PPA_rng"
            else:
                edges = set(cand)
                layer_name = "PPA_delaunay"

            if max_dist_m > 0.0:
                edges = self._filter_edges_max_dist(edges=edges, coords=coords, max_dist_m=max_dist_m)
                layer_name = f"{layer_name}_max{int(round(max_dist_m))}m"

        # --- Output layers ---
        crs_authid = (
            self.cmbSiteLayer.currentLayer().crs().authid()
            if self.cmbSiteLayer.currentLayer()
            else QgsProject.instance().crs().authid()
        )

        push_message(self.iface, "PPA", f"근접성 네트워크 생성 중... (노드 {n}, 간선 {len(edges)})", level=0, duration=4)
        QtWidgets.QApplication.processEvents()

        # Run parameters recorded on both output layers (reproducibility).
        ppa_params: Dict[str, Any] = {
            "network": "ppa",
            "method": str(method),
            "k": (int(k) if method == PPA_KNN else None),
            "mutual_only": (bool(mutual_only) if method == PPA_KNN else None),
            "max_dist_m": float(max_dist_m),
            "n_nodes": int(n),
            "n_edges": int(len(edges)),
        }

        edge_layer, run_group, run_id = self._add_edge_layer(
            nodes=nodes,
            edges=sorted(edges),
            layer_name=layer_name,
            color=QColor(80, 80, 80, 220),
            add_dist=True,
            crs_authid=crs_authid,
            extra_params=ppa_params,
        )

        # Node metrics (SNA) layer
        if create_node_metrics:
            self._add_node_metrics_layer(
                nodes=nodes,
                edges=set(edges),
                crs_authid=crs_authid,
                run_group=run_group,
                run_id=run_id,
                title="PPA_Nodes",
                compute_closeness=compute_closeness,
                compute_betweenness=compute_betweenness,
                extra_params=ppa_params,
            )

        # Summary
        deg = self._degrees(n, edges)
        comps, comp_sizes = self._components(n, edges)
        msg = f"완료: 노드 {n} / 간선 {len(edges)}  " f"(평균 degree {float(sum(deg)) / max(1, n):.2f}, components {len(comp_sizes)})"
        log_message(f"PPA: {msg}  [method={method}]", level=Qgis.Info)
        push_message(self.iface, "PPA", msg, level=0, duration=7)
        self.accept()

    def _degrees(self, n: int, edges: Set[Tuple[int, int]]) -> List[int]:
        deg = [0] * int(n)
        for a, b in edges:
            _skip_1407 = False
            try:
                deg[int(a)] += 1
                deg[int(b)] += 1
            except Exception as _exc:
                log_swallowed("spatial_network_dialog._degrees", _exc)
                log_swallowed("tools/spatial_network_dialog.py:1410 (_degrees)", _exc)
                _skip_1407 = True
            if _skip_1407:
                continue
        return deg

    def _components(self, n: int, edges: Set[Tuple[int, int]]) -> Tuple[List[int], Dict[int, int]]:
        parent = list(range(int(n)))
        rank = [0] * int(n)

        def find(x: int) -> int:
            x = int(x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int):
            ra = find(a)
            rb = find(b)
            if ra == rb:
                return
            if rank[ra] < rank[rb]:
                parent[ra] = rb
            elif rank[ra] > rank[rb]:
                parent[rb] = ra
            else:
                parent[rb] = ra
                rank[ra] += 1

        for a, b in edges:
            _skip_1440 = False
            try:
                union(int(a), int(b))
            except Exception as _exc:
                log_swallowed("spatial_network_dialog._components", _exc)
                log_swallowed("tools/spatial_network_dialog.py:1442 (_components)", _exc)
                _skip_1440 = True
            if _skip_1440:
                continue

        roots = [find(i) for i in range(int(n))]
        # Compact component IDs (0..k-1)
        remap: Dict[int, int] = {}
        comp_id: List[int] = [0] * int(n)
        for i, r in enumerate(roots):
            if r not in remap:
                remap[r] = len(remap)
            comp_id[i] = remap[r]

        comp_sizes: Dict[int, int] = {}
        for cid in comp_id:
            comp_sizes[int(cid)] = comp_sizes.get(int(cid), 0) + 1

        return comp_id, comp_sizes

    def _filter_edges_max_dist(
        self, *, edges: Set[Tuple[int, int]], coords: np.ndarray, max_dist_m: float
    ) -> Set[Tuple[int, int]]:
        if not edges:
            return set()
        r2 = float(max_dist_m) ** 2
        out: Set[Tuple[int, int]] = set()
        for a, b in edges:
            _skip_1469 = False
            try:
                dx = float(coords[a, 0] - coords[b, 0])
                dy = float(coords[a, 1] - coords[b, 1])
                if (dx * dx + dy * dy) <= r2:
                    out.add((int(a), int(b)))
            except Exception as _exc:
                log_swallowed("spatial_network_dialog._filter_edges_max_dist", _exc)
                log_swallowed("tools/spatial_network_dialog.py:1474 (_filter_edges_max_dist)", _exc)
                _skip_1469 = True
            if _skip_1469:
                continue
        return out

    def _ppa_delaunay_edges(self, *, nodes: List[_Node], crs_authid: str) -> Set[Tuple[int, int]]:
        """Return candidate edges from a Delaunay triangulation (best-effort, uses QGIS Processing)."""
        n = int(len(nodes))
        if n < 3:
            return set()

        try:
            pt_layer = QgsVectorLayer(f"Point?crs={crs_authid}", "PPA_points_tmp", "memory")
            pr = pt_layer.dataProvider()
            pr.addAttributes([QgsField("idx", QVariant.Int)])
            pt_layer.updateFields()

            feats = []
            for i, nd in enumerate(nodes):
                f = QgsFeature(pt_layer.fields())
                f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(nd.x), float(nd.y))))
                f["idx"] = int(i)
                feats.append(f)
            pr.addFeatures(feats)
            pt_layer.updateExtents()
        except Exception as e:
            log_message(f"PPA: failed to build temp point layer for Delaunay: {e}", level=Qgis.Warning)
            return set()

        tri_layer = None
        last_err = None
        for alg_id in ("qgis:delaunaytriangulation", "native:delaunaytriangulation"):
            try:
                res = processing.run(alg_id, {"INPUT": pt_layer, "OUTPUT": "memory:"})
                out = res.get("OUTPUT")
                if isinstance(out, QgsVectorLayer):
                    tri_layer = out
                elif isinstance(out, str) and out:
                    tri_layer = QgsVectorLayer(out, "Delaunay", "ogr")
                if tri_layer is not None and tri_layer.isValid():
                    break
            except Exception as e:
                last_err = e
                tri_layer = None

        if tri_layer is None or (not tri_layer.isValid()):
            log_message(f"PPA: Delaunay algorithm not available/failed: {last_err}", level=Qgis.Warning)
            return set()

        # Map vertex coordinates back to node indices (rounded)
        # Several sites can share one coordinate (a duplicated row, or two
        # records of one complex). The triangulation sees one vertex, so keep
        # every node index per key and let co-located nodes share the edges
        # instead of publishing the extra ones as isolated.
        lookup: Dict[Tuple[int, int], List[int]] = {}
        for i, nd in enumerate(nodes):
            key = (int(round(float(nd.x) * 1000.0)), int(round(float(nd.y) * 1000.0)))
            lookup.setdefault(key, []).append(int(i))
        dup_groups = [ids for ids in lookup.values() if len(ids) > 1]
        if dup_groups:
            n_dup = int(sum(len(ids) - 1 for ids in dup_groups))
            log_message(
                f"PPA: {n_dup} node(s) share a coordinate (within 1 mm) at {len(dup_groups)} location(s); "
                "co-located nodes share the same Delaunay/Gabriel/RNG edges.",
                level=Qgis.Warning,
            )
            try:
                push_message(
                    self.iface,
                    "경고",
                    f"좌표가 같은 노드 {n_dup}개({len(dup_groups)}개 지점): 겹친 노드끼리 같은 이웃 간선을 공유합니다(고립 아님).",
                    level=1,
                    duration=8,
                )
            except Exception as _exc:
                log_swallowed("spatial_network_dialog._ppa_delaunay_edges", _exc)

        coords = np.array([(float(nd.x), float(nd.y)) for nd in nodes], dtype=np.float64)

        def _idxs_for_xy(x: float, y: float) -> List[int]:
            key = (int(round(float(x) * 1000.0)), int(round(float(y) * 1000.0)))
            if key in lookup:
                return list(lookup[key])
            # Fallback: nearest
            try:
                d2 = (coords[:, 0] - float(x)) ** 2 + (coords[:, 1] - float(y)) ** 2
                j = int(np.argmin(d2))
                if float(d2[j]) <= 1e-6:
                    jkey = (int(round(float(coords[j, 0]) * 1000.0)), int(round(float(coords[j, 1]) * 1000.0)))
                    return list(lookup.get(jkey, [j]))
            except Exception as _exc:
                log_swallowed("spatial_network_dialog._ppa_delaunay_edges", _exc)
                return []
            return []

        edges: Set[Tuple[int, int]] = set()
        for ft in tri_layer.getFeatures():
            _skip_1547 = False
            try:
                geom = ft.geometry()
                if geom is None or geom.isEmpty():
                    continue
                polys = geom.asPolygon()
                if not polys:
                    mp = geom.asMultiPolygon()
                    if mp and mp[0]:
                        polys = mp[0]
                if not polys or not polys[0]:
                    continue
                ring = polys[0]
                if len(ring) >= 2 and ring[0] == ring[-1]:
                    ring = ring[:-1]

                groups: List[List[int]] = []
                seen_groups: Set[Tuple[int, ...]] = set()
                for p in ring:
                    g_ids = _idxs_for_xy(p.x(), p.y())
                    if not g_ids:
                        continue
                    gk = tuple(g_ids)
                    if gk in seen_groups:
                        continue
                    seen_groups.add(gk)
                    groups.append(g_ids)
                if len(groups) < 3:
                    continue
                ga, gb, gc = groups[0], groups[1], groups[2]
                for gu, gv in ((ga, gb), (gb, gc), (gc, ga)):
                    for u in gu:
                        for v in gv:
                            uu, vv = (u, v) if u < v else (v, u)
                            if uu != vv:
                                edges.add((uu, vv))
            except Exception as _exc:
                log_swallowed("spatial_network_dialog._ppa_delaunay_edges", _exc)
                log_swallowed("tools/spatial_network_dialog.py:1575 (_ppa_delaunay_edges)", _exc)
                _skip_1547 = True
            if _skip_1547:
                continue

        return edges

    def _ppa_filter_gabriel(self, *, cand_edges: Set[Tuple[int, int]], coords: np.ndarray) -> Set[Tuple[int, int]]:
        """Gabriel graph filter (usually applied on Delaunay candidate edges)."""
        out: Set[Tuple[int, int]] = set()
        eps = 1e-9
        for a, b in cand_edges:
            a = int(a)
            b = int(b)
            if a == b:
                continue
            midx = 0.5 * (coords[a, 0] + coords[b, 0])
            midy = 0.5 * (coords[a, 1] + coords[b, 1])
            r2 = ((coords[a, 0] - midx) ** 2) + ((coords[a, 1] - midy) ** 2)  # (d/2)^2

            d2 = (coords[:, 0] - midx) ** 2 + (coords[:, 1] - midy) ** 2
            d2[a] = np.inf
            d2[b] = np.inf
            if float(np.min(d2)) >= float(r2) - eps:
                out.add((a, b) if a < b else (b, a))
        return out

    def _ppa_filter_rng(self, *, cand_edges: Set[Tuple[int, int]], coords: np.ndarray) -> Set[Tuple[int, int]]:
        """Relative Neighborhood Graph (RNG) filter (usually applied on Delaunay candidate edges)."""
        out: Set[Tuple[int, int]] = set()
        eps = 1e-9
        for a, b in cand_edges:
            a = int(a)
            b = int(b)
            if a == b:
                continue
            dx = float(coords[a, 0] - coords[b, 0])
            dy = float(coords[a, 1] - coords[b, 1])
            dij2 = dx * dx + dy * dy

            d2a = (coords[:, 0] - coords[a, 0]) ** 2 + (coords[:, 1] - coords[a, 1]) ** 2
            d2b = (coords[:, 0] - coords[b, 0]) ** 2 + (coords[:, 1] - coords[b, 1]) ** 2
            d2a[a] = np.inf
            d2a[b] = np.inf
            d2b[a] = np.inf
            d2b[b] = np.inf

            if not bool(np.any(np.maximum(d2a, d2b) < (float(dij2) - eps))):
                out.add((a, b) if a < b else (b, a))
        return out

    def _add_node_metrics_layer(
        self,
        *,
        nodes: List[_Node],
        edges: Set[Tuple[int, int]],
        crs_authid: str,
        run_group,
        run_id: str,
        title: str,
        compute_closeness: bool,
        compute_betweenness: bool,
        extra_node_fields: Optional[List[QgsField]] = None,
        extra_values_by_node: Optional[Dict[int, Dict[str, Any]]] = None,
        extra_params: Optional[Dict[str, Any]] = None,
    ):
        n = int(len(nodes))
        if n <= 0:
            return

        deg = self._degrees(n, edges)
        comp_id, comp_sizes = self._components(n, edges)

        # Build adjacency
        adj: List[List[int]] = [[] for _ in range(n)]
        for a, b in edges:
            a = int(a)
            b = int(b)
            if a == b:
                continue
            adj[a].append(b)
            adj[b].append(a)

        # Advanced SNA metrics can be expensive; guard for large graphs.
        if n > 500 and (compute_closeness or compute_betweenness):
            log_message(
                f"SNA: advanced metrics skipped (n={n} too large). Use smaller selection or disable advanced metrics.",
                level=Qgis.Warning,
            )
            # The user explicitly checked these boxes — tell them visibly, not
            # just in the message log, that the fields will be missing.
            try:
                push_message(
                    self.iface,
                    "경고",
                    f"노드가 많아(n={n}>500) Closeness/Betweenness 계산을 건너뛰었습니다. 결과에 해당 필드가 없습니다.",
                    level=1,
                    duration=8,
                )
            except Exception as _exc:
                log_swallowed("spatial_network_dialog._add_node_metrics_layer", _exc)
            compute_closeness = False
            compute_betweenness = False

        closeness = None
        if compute_closeness:
            closeness = self._closeness_centrality(n=n, adj=adj)

        betweenness = None
        if compute_betweenness:
            betweenness = self._betweenness_centrality(n=n, adj=adj)

        layer = QgsVectorLayer(f"Point?crs={crs_authid}", title, "memory")
        pr = layer.dataProvider()
        fields = [
            QgsField("fid", QVariant.String),
            QgsField("name", QVariant.String),
            QgsField("degree", QVariant.Int),
            QgsField("component", QVariant.Int),
            QgsField("comp_size", QVariant.Int),
        ]
        if compute_closeness:
            fields.append(QgsField("closeness", QVariant.Double))
        if compute_betweenness:
            fields.append(QgsField("betweenness", QVariant.Double))
            fields.append(QgsField("betw_norm", QVariant.Double))
        if extra_node_fields:
            fields.extend(extra_node_fields)
        pr.addAttributes(fields)
        layer.updateFields()

        # Raw Brandes pair counts scaled by the number of unordered pairs that
        # exclude i, so networks of different size and NetworkX/Gephi defaults
        # become comparable.
        betw_pairs = (float(n - 1) * float(n - 2)) / 2.0 if n > 2 else 0.0
        feats = []
        for i, nd in enumerate(nodes):
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(nd.x), float(nd.y))))
            f["fid"] = str(nd.fid)
            f["name"] = str(nd.name)
            f["degree"] = int(deg[i])
            f["component"] = int(comp_id[i])
            f["comp_size"] = int(comp_sizes.get(int(comp_id[i]), 1))
            if compute_closeness and closeness is not None:
                try:
                    f["closeness"] = float(closeness[i])
                except Exception:
                    f["closeness"] = 0.0
            if compute_betweenness and betweenness is not None:
                try:
                    f["betweenness"] = float(betweenness[i])
                    f["betw_norm"] = (float(betweenness[i]) / betw_pairs) if betw_pairs > 0 else 0.0
                except Exception:
                    f["betweenness"] = 0.0
                    f["betw_norm"] = 0.0
            if extra_values_by_node and i in extra_values_by_node:
                for k, v in (extra_values_by_node.get(i) or {}).items():
                    try:
                        f[str(k)] = v
                    except Exception as _exc:
                        log_swallowed("tools/spatial_network_dialog.py:1726 (_add_node_metrics_layer)", _exc)
            feats.append(f)

        pr.addFeatures(feats)
        layer.updateExtents()

        # Styling: degree-based graduated colors (simple, readable)
        try:
            vmax = int(max(deg) if deg else 0)
            vmin = int(min(deg) if deg else 0)
            if vmax <= 0:
                sym = QgsMarkerSymbol.createSimple({"name": "circle", "color": "255,0,0,200", "size": "3"})
                layer.setRenderer(QgsSingleSymbolRenderer(sym))
            elif vmax == vmin:
                # Every node has the same degree (regular graph, e.g. K4 from a
                # mutual 3-NN on four sites). A 5-class ramp with step >= 1 would
                # end in an inverted "v+4 - v" class; one exact-value category
                # keeps the exported legend honest.
                sym = QgsMarkerSymbol.createSimple({"name": "circle", "color": "255,120,60,220", "size": "4"})
                cat = QgsRendererCategory(int(vmax), sym, f"{int(vmax)} (모든 노드 동일)")
                layer.setRenderer(QgsCategorizedSymbolRenderer("degree", [cat]))
            else:
                # Never more classes than integer degree values in the span, so
                # every class stays inside [vmin, vmax] and hi >= lo.
                span = float(vmax) - float(vmin)
                classes = int(max(1, min(5, int(round(span)))))
                step = span / float(classes)
                ranges: List[QgsRendererRange] = []
                for i in range(classes):
                    lo = float(vmin) + float(i) * step
                    hi = float(vmax) if i == classes - 1 else (float(vmin) + float(i + 1) * step)
                    hi = max(float(hi), float(lo))
                    t = 0.0 if classes <= 1 else float(i) / float(classes - 1)
                    r = int(255)
                    g = int(round(240.0 * (1.0 - t)))
                    b = int(round(120.0 * (1.0 - t)))
                    col = QColor(r, g, b, 220)
                    sym = QgsMarkerSymbol.createSimple(
                        {"name": "circle", "color": f"{col.red()},{col.green()},{col.blue()},{col.alpha()}", "size": f"{3.0 + 2.0 * t:.1f}"}
                    )
                    label = f"{int(round(lo))}–{int(round(hi))}"
                    ranges.append(QgsRendererRange(lo, hi, sym, label))
                renderer = QgsGraduatedSymbolRenderer("degree", ranges)
                layer.setRenderer(renderer)
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._add_node_metrics_layer", _exc)

        # Labels (name)
        try:
            pal = QgsPalLayerSettings()
            pal.enabled = True
            pal.fieldName = "name"
            fmt = QgsTextFormat()
            fmt.setSize(8)
            fmt.setColor(QColor(40, 40, 40))
            buf = QgsTextBufferSettings()
            buf.setEnabled(True)
            buf.setSize(1.0)
            buf.setColor(QColor(255, 255, 255))
            fmt.setBuffer(buf)
            pal.setFormat(fmt)
            layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
            layer.setLabelsEnabled(True)
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._add_node_metrics_layer", _exc)

        project = QgsProject.instance()
        try:
            node_params: Dict[str, Any] = dict(extra_params or {})
            node_params.update(
                {
                    "title": str(title or ""),
                    "n_nodes": int(n),
                    "n_edges": int(len(edges)),
                    "closeness": bool(compute_closeness),
                    "betweenness": bool(compute_betweenness),
                }
            )
            set_archtoolkit_layer_metadata(
                layer,
                tool_id="spatial_network",
                run_id=str(run_id),
                kind="nodes_metrics",
                units="",
                params=node_params,
            )
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._add_node_metrics_layer", _exc)
        project.addMapLayer(layer, False)
        try:
            run_group.addLayer(layer)
        except Exception:
            project.addMapLayer(layer)

    def _closeness_centrality(self, *, n: int, adj: List[List[int]]) -> List[float]:
        return closeness_centrality_unweighted(n=n, adj=adj)

    def _betweenness_centrality(self, *, n: int, adj: List[List[int]]) -> List[float]:
        return betweenness_centrality_unweighted(n=n, adj=adj)

    def _los_visible(
        self,
        *,
        dem_layer,
        provider=None,
        ax: float,
        ay: float,
        bx: float,
        by: float,
        obs_height: float,
        tgt_height: float,
        sample_step_m: float,
        curvature_cc: float = 0.87,
    ) -> Optional[bool]:
        """DEM line-of-sight test from (ax, ay) to (bx, by).

        curvature_cc: earth-curvature/refraction coefficient, as gdal_viewshed
        -cc: every sampled terrain height (target included) is lowered by
        cc * d^2 / (2R) with d the horizontal distance from the observer.
        Default 0.87 = 1 - 0.13 (standard refraction); 0 = flat sight line.
        """
        dx = bx - ax
        dy = by - ay
        total_dist = math.hypot(dx, dy)
        if total_dist <= 0:
            return True

        px = abs(float(dem_layer.rasterUnitsPerPixelX() or 0.0))
        py = abs(float(dem_layer.rasterUnitsPerPixelY() or 0.0))
        pix = min([v for v in (px, py) if v > 0] or [5.0])
        step = float(sample_step_m or 0.0)
        if step <= 0:
            step = max(pix, 5.0)
        else:
            step = max(pix, step)

        # Network use-case: keep sampling reasonable - but say so when the
        # ceiling coarsens a long sight line past the requested step.
        num_samples = int(total_dist / step) if step > 0 else 200
        num_samples = max(LOS_SAMPLE_MIN, min(num_samples, LOS_SAMPLE_CAP))
        eff_step = (total_dist / num_samples) if num_samples > 0 else step
        # Remembered per run so the output layers can record the step actually used.
        self._los_step_base_m = float(step)
        self._los_eff_step_max_m = max(float(getattr(self, "_los_eff_step_max_m", 0.0) or 0.0), float(eff_step))
        if eff_step > step * 1.05 and not getattr(self, "_los_step_warned", False):
            self._los_step_warned = True
            log_message(
                f"가시선 샘플 간격: 요청 {step:.1f} m, 장거리 상한(5000점)으로 실제 {eff_step:.1f} m 적용 "
                f"(총거리 {total_dist:.0f} m). 이보다 긴 쌍은 모두 이 상한의 영향을 받습니다.",
                level=Qgis.Warning,
            )

        if provider is None:
            provider = dem_layer.dataProvider()

        # Endpoints
        obs_elev0, ok0 = provider.sample(QgsPointXY(ax, ay), 1)
        tgt_elev0, ok1 = provider.sample(QgsPointXY(bx, by), 1)
        if not ok0 or not ok1:
            return None
        try:
            obs_elev = float(obs_elev0) + float(obs_height)
            tgt_elev = float(tgt_elev0) + float(tgt_height)
        except Exception:
            return None
        # A Float32 DEM carrying NaN but declaring no NoData makes sample()
        # return (nan, True). NaN compares False to everything, so a NaN
        # endpoint made every pair "visible" and a NaN hole read as clear
        # ground. Treat both as a sample failure, like viewshed_dialog does.
        if not (math.isfinite(obs_elev) and math.isfinite(tgt_elev)):
            return None

        # Earth curvature + refraction (viewshed_dialog / gdal_viewshed -cc):
        # apparent drop cc*d^2/(2R) grows with distance from the observer. The
        # target is a sample at d = total_dist, so it drops too and the sight
        # line bends with it; intermediate terrain drops by the smaller
        # cc*(frac*D)^2/(2R), which is what removes the flat-earth over-clearance
        # of up to D^2/(8R) (about 10 m at 25 km with k = 0.13).
        try:
            cc = float(curvature_cc)
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._los_visible", _exc)
            cc = 0.0
        if not math.isfinite(cc) or cc < 0.0:
            cc = 0.0
        cc = min(1.0, cc)
        two_r = 2.0 * LOS_EARTH_RADIUS_M
        if cc > 0.0:
            tgt_elev -= cc * (total_dist * total_dist) / two_r

        for i in range(1, num_samples):
            frac = i / num_samples
            x = ax + frac * dx
            y = ay + frac * dy
            elev, ok = provider.sample(QgsPointXY(x, y), 1)
            if not ok:
                return None
            try:
                z = float(elev)
            except Exception:
                return None
            if not math.isfinite(z):
                return None
            if cc > 0.0:
                d_sample = frac * total_dist
                z -= cc * (d_sample * d_sample) / two_r

            sight = obs_elev + frac * (tgt_elev - obs_elev)
            if z > sight:
                return False
        return True

    def _run_visibility_network(
        self,
        *,
        dem_layer,
        nodes: List[_Node],
        obs_height: float,
        tgt_height: float,
        candidate_k: int,
        max_dist: float,
        sample_step_m: float,
        use_poly_boundary_ratio: bool = False,
        create_node_metrics: bool = True,
        compute_closeness: bool = False,
        compute_betweenness: bool = False,
        vis_edge_rule: str = VIS_RULE_MUTUAL,
        curvature: bool = True,
        refraction_coeff: float = LOS_DEFAULT_REFRACTION_K,
        poly_boundary_step_m: float = 0.0,
        poly_boundary_max_points: int = 0,
    ):
        # once-per-run notice for the LOS sample ceiling (see _los_visible)
        self._los_step_warned = False
        self._los_step_base_m = 0.0
        self._los_eff_step_max_m = 0.0
        n = len(nodes)
        if n < 2:
            return

        # Curvature/refraction coefficient, mirroring viewshed_dialog._calculate_gdal_viewshed_cc:
        # off -> 0 (flat), on -> 1 - k clamped to [0, 1].
        cc = 0.0
        try:
            if bool(curvature):
                cc = max(0.0, min(1.0, 1.0 - float(refraction_coeff)))
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._run_visibility_network", _exc)
            cc = 1.0 - LOS_DEFAULT_REFRACTION_K
        candidate_k_requested = int(candidate_k)

        all_pairs = False
        try:
            all_pairs = bool(self.chkVisAllPairs.isChecked())
        except Exception:
            all_pairs = False

        if candidate_k <= 0:
            candidate_k = 1
        candidate_k = min(int(candidate_k), max(1, n - 1))

        max_dist = float(max_dist or 0.0)
        if max_dist < 0:
            max_dist = 0.0
        max_dist_sq = (max_dist ** 2) if max_dist > 0 else 0.0

        if all_pairs:
            # Count pairs for progress.
            total_pairs = 0
            for i in range(n):
                xi, yi = nodes[i].x, nodes[i].y
                for j in range(i + 1, n):
                    if max_dist_sq > 0:
                        xj, yj = nodes[j].x, nodes[j].y
                        dsq = (xi - xj) ** 2 + (yi - yj) ** 2
                        if dsq > max_dist_sq:
                            continue
                    total_pairs += 1

            # Large all-pairs runs can be slow; ask for confirmation.
            try:
                est_los = None
                if use_poly_boundary_ratio:
                    avg_samples = sum(len(nd.samples) for nd in nodes) / float(max(1, n))
                    est_los = int(total_pairs * avg_samples * 2)  # A->B + B->A

                if total_pairs >= 5000 or (est_los is not None and est_los >= 200000):
                    extra = ""
                    if est_los is not None:
                        extra = f"\n(추정 LOS 호출: 약 {est_los:,}회)"
                    res = QtWidgets.QMessageBox.warning(
                        self,
                        "경고",
                        f"반경 내 검사 쌍이 많습니다: {total_pairs:,}쌍{extra}\n계속 진행할까요?",
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                        QtWidgets.QMessageBox.No,
                    )
                    if res != QtWidgets.QMessageBox.Yes:
                        restore_ui_focus(self)
                        return
            except Exception as _exc:
                log_swallowed("spatial_network_dialog._run_visibility_network", _exc)

            progress = QtWidgets.QProgressDialog(
                f"가시성 네트워크(LOS) 계산 중... (쌍 {total_pairs}개 검사)",
                "취소",
                0,
                max(1, total_pairs),
                self,
            )
        else:
            progress = QtWidgets.QProgressDialog(
                "가시성 네트워크(LOS) 계산 중...", "취소", 0, n, self
            )
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        QtWidgets.QApplication.processEvents()

        edges: Set[Tuple[int, int]] = set()
        status_by_edge: Dict[Tuple[int, int], str] = {}
        ratio_by_edge: Dict[Tuple[int, int], float] = {}
        extra_by_edge: Dict[Tuple[int, int], Dict[str, Any]] = {}
        tested_pairs = 0
        failed_pairs = 0
        provider = dem_layer.dataProvider()

        def _ratio_for_samples(
            obs_samples: Tuple[Tuple[float, float], ...],
            tx: float,
            ty: float,
            *,
            obs_h: float,
            tgt_h: float,
        ) -> Optional[float]:
            visible = 0
            valid = 0
            for ox, oy in obs_samples:
                vis = self._los_visible(
                    dem_layer=dem_layer,
                    provider=provider,
                    ax=float(ox),
                    ay=float(oy),
                    bx=float(tx),
                    by=float(ty),
                    obs_height=obs_h,
                    tgt_height=tgt_h,
                    sample_step_m=sample_step_m,
                    curvature_cc=cc,
                )
                if vis is None:
                    continue
                valid += 1
                if vis:
                    visible += 1
            if valid <= 0:
                return None
            return float(visible) / float(valid)

        def _status_from_vis(vis: Optional[bool]) -> str:
            if vis is None:
                return "샘플 실패"
            return "보임" if bool(vis) else "안보임"

        def _eval_pair(a: int, b: int) -> Tuple[str, float, Dict[str, Any]]:
            """Evaluate visibility for pair (a<b), returning (edge_status, ratio_mean, extras)."""
            a = int(a)
            b = int(b)
            vis_ab = None
            vis_ba = None
            r_ab = None
            r_ba = None

            if use_poly_boundary_ratio:
                r_ab = _ratio_for_samples(
                    nodes[a].samples,
                    nodes[b].x,
                    nodes[b].y,
                    obs_h=obs_height,
                    tgt_h=tgt_height,
                )
                r_ba = _ratio_for_samples(
                    nodes[b].samples,
                    nodes[a].x,
                    nodes[a].y,
                    obs_h=obs_height,
                    tgt_h=tgt_height,
                )
                # Convert ratio -> visible bool (any visible sample)
                vis_ab = None if r_ab is None else bool(float(r_ab) > 0.0)
                vis_ba = None if r_ba is None else bool(float(r_ba) > 0.0)
            else:
                vis_ab = self._los_visible(
                    dem_layer=dem_layer,
                    provider=provider,
                    ax=nodes[a].x,
                    ay=nodes[a].y,
                    bx=nodes[b].x,
                    by=nodes[b].y,
                    obs_height=obs_height,
                    tgt_height=tgt_height,
                    sample_step_m=sample_step_m,
                    curvature_cc=cc,
                )
                if abs(float(obs_height) - float(tgt_height)) <= 1e-9:
                    vis_ba = vis_ab
                else:
                    vis_ba = self._los_visible(
                        dem_layer=dem_layer,
                        provider=provider,
                        ax=nodes[b].x,
                        ay=nodes[b].y,
                        bx=nodes[a].x,
                        by=nodes[a].y,
                        obs_height=obs_height,
                        tgt_height=tgt_height,
                        sample_step_m=sample_step_m,
                        curvature_cc=cc,
                    )
                # Point nodes: ratio is 0/1 when valid
                r_ab = None if vis_ab is None else (1.0 if bool(vis_ab) else 0.0)
                r_ba = None if vis_ba is None else (1.0 if bool(vis_ba) else 0.0)

            status_ab = _status_from_vis(vis_ab)
            status_ba = _status_from_vis(vis_ba)

            # Aggregate ratio
            vals = [v for v in (r_ab, r_ba) if v is not None]
            ratio_mean = float(sum(vals) / float(len(vals))) if vals else 0.0

            # Aggregate status for styling
            if status_ab == "샘플 실패" or status_ba == "샘플 실패":
                edge_status = "샘플 실패"
            else:
                vab = bool(vis_ab)
                vba = bool(vis_ba)
                if vab and vba:
                    edge_status = "상호 보임"
                elif vab or vba:
                    edge_status = "단방향 보임"
                else:
                    edge_status = "상호 안보임"

            extras = {
                "status_ab": status_ab,
                "status_ba": status_ba,
                "vis_ab": int(bool(vis_ab)) if vis_ab is not None else 0,
                "vis_ba": int(bool(vis_ba)) if vis_ba is not None else 0,
                "vis_ratio_ab": float(r_ab) if r_ab is not None else 0.0,
                "vis_ratio_ba": float(r_ba) if r_ba is not None else 0.0,
                "vis_ratio": float(ratio_mean),
                "mutual": int(1 if (edge_status == "상호 보임") else 0),
            }
            return edge_status, float(ratio_mean), extras

        if all_pairs:
            for i in range(n):
                if progress.wasCanceled():
                    push_message(self.iface, "가시성 네트워크", "취소되었습니다.", level=1, duration=4)
                    restore_ui_focus(self)
                    return

                xi, yi = nodes[i].x, nodes[i].y
                for j in range(i + 1, n):
                    if max_dist_sq > 0:
                        xj, yj = nodes[j].x, nodes[j].y
                        dsq = (xi - xj) ** 2 + (yi - yj) ** 2
                        if dsq > max_dist_sq:
                            continue

                    tested_pairs += 1
                    edge_status, ratio_mean, extras = _eval_pair(i, j)
                    if edge_status == "샘플 실패":
                        failed_pairs += 1

                    edges.add((i, j))
                    status_by_edge[(i, j)] = edge_status
                    ratio_by_edge[(i, j)] = ratio_mean
                    extra_by_edge[(i, j)] = extras

                    if tested_pairs % 20 == 0:
                        progress.setValue(min(progress.maximum(), tested_pairs))
                        QtWidgets.QApplication.processEvents()

            progress.setValue(progress.maximum())
        else:
            tested: Set[Tuple[int, int]] = set()
            for i in range(n):
                if progress.wasCanceled():
                    push_message(self.iface, "가시성 네트워크", "취소되었습니다.", level=1, duration=4)
                    restore_ui_focus(self)
                    return

                # Candidate neighbors by Euclidean distance (in DEM CRS units, meters expected)
                xi, yi = nodes[i].x, nodes[i].y
                dists = []
                for j in range(n):
                    if i == j:
                        continue
                    xj, yj = nodes[j].x, nodes[j].y
                    dsq = (xi - xj) ** 2 + (yi - yj) ** 2
                    if max_dist_sq > 0 and dsq > max_dist_sq:
                        continue
                    dists.append((dsq, j))

                for _dsq, j in heapq.nsmallest(candidate_k, dists, key=lambda t: t[0]):
                    a, b = (i, j) if i < j else (j, i)
                    if a == b:
                        continue
                    if (a, b) in tested:
                        continue
                    tested.add((a, b))
                    tested_pairs += 1
                    edge_status, ratio_mean, extras = _eval_pair(a, b)
                    if edge_status == "샘플 실패":
                        failed_pairs += 1

                    edges.add((a, b))
                    status_by_edge[(a, b)] = edge_status
                    ratio_by_edge[(a, b)] = ratio_mean
                    extra_by_edge[(a, b)] = extras

                progress.setValue(i + 1)
                QtWidgets.QApplication.processEvents()

        extra_fields = [
            QgsField("status_ab", QVariant.String),
            QgsField("status_ba", QVariant.String),
            QgsField("vis_ab", QVariant.Int),
            QgsField("vis_ba", QVariant.Int),
            QgsField("vis_ratio_ab", QVariant.Double),
            QgsField("vis_ratio_ba", QVariant.Double),
            QgsField("mutual", QVariant.Int),
        ]

        # Layer names carry the result-determining settings (as the PPA branch
        # does with k/mutual/max), so three runs with different observer
        # heights no longer produce three identical "Visibility_LOS" layers.
        def _fmt_m(v: float) -> str:
            try:
                return f"{float(v):g}"
            except Exception as _exc:
                log_swallowed("spatial_network_dialog._run_visibility_network", _exc)
                return str(v)

        name_suffix = f"_obs{_fmt_m(obs_height)}m"
        if abs(float(tgt_height) - float(obs_height)) > 1e-9:
            name_suffix += f"_tgt{_fmt_m(tgt_height)}m"
        if max_dist > 0:
            name_suffix += f"_max{int(round(max_dist))}m"
        if cc <= 0.0:
            name_suffix += "_flat"
        edge_layer_name = f"Visibility_LOS{name_suffix}"
        node_layer_name = f"LOS_Nodes{name_suffix}"

        # Every value that determines the result, recorded on both output
        # layers (params_json) so a saved run can be told apart and reproduced.
        dem_name = ""
        try:
            dem_name = str(dem_layer.name() or "")
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._run_visibility_network", _exc)
        run_params: Dict[str, Any] = {
            "network": "visibility_los",
            "n_nodes": int(n),
            "dem_layer": dem_name,
            "dem_crs": str(dem_layer.crs().authid()),
            "obs_height_m": float(obs_height),
            "tgt_height_m": float(tgt_height),
            "sample_step_m_requested": float(sample_step_m),
            "sample_step_m_base": float(getattr(self, "_los_step_base_m", 0.0) or 0.0),
            "sample_step_m_effective_max": float(getattr(self, "_los_eff_step_max_m", 0.0) or 0.0),
            "sample_step_capped": bool(getattr(self, "_los_step_warned", False)),
            "samples_per_line_min": int(LOS_SAMPLE_MIN),
            "samples_per_line_cap": int(LOS_SAMPLE_CAP),
            "max_dist_m": float(max_dist),
            "all_pairs": bool(all_pairs),
            "candidate_k": (None if all_pairs else int(candidate_k)),
            "candidate_k_requested": (None if all_pairs else int(candidate_k_requested)),
            "vis_edge_rule": str(vis_edge_rule or VIS_RULE_MUTUAL),
            "poly_boundary": bool(use_poly_boundary_ratio),
            "poly_boundary_step_m": (float(poly_boundary_step_m) if use_poly_boundary_ratio else None),
            "poly_boundary_max_points": (int(poly_boundary_max_points) if use_poly_boundary_ratio else None),
            "curvature": bool(cc > 0.0),
            "refraction_coeff": (float(refraction_coeff) if cc > 0.0 else None),
            "curvature_cc": float(cc),
            "earth_radius_m": float(LOS_EARTH_RADIUS_M),
            "tested_pairs": int(tested_pairs),
            "failed_pairs": int(failed_pairs),
        }

        edge_layer, run_group, run_id = self._add_edge_layer(
            nodes=nodes,
            edges=sorted(edges),
            layer_name=edge_layer_name,
            color=QColor(0, 160, 80, 220),
            add_dist=True,
            crs_authid=dem_layer.crs().authid(),
            status_by_edge=status_by_edge,
            ratio_by_edge=ratio_by_edge,
            extra_fields=extra_fields,
            extra_values_by_edge=extra_by_edge,
            label_distance=bool(tested_pairs <= 300),
            extra_params=run_params,
        )

        # Pairs whose sight line could not be evaluated (DEM NoData, sampling
        # failure) must not read as "not visible": count them per node so a
        # degree of 0 can be told apart from "never tested".
        fail_deg = [0] * int(n)
        for (fa, fb), st in status_by_edge.items():
            if st == "샘플 실패":
                try:
                    fail_deg[int(fa)] += 1
                    fail_deg[int(fb)] += 1
                except Exception as _exc:
                    log_swallowed("spatial_network_dialog._run_visibility_network", _exc)
        n_fail_nodes = int(sum(1 for c in fail_deg if c > 0))

        # Node metrics layer (SNA)
        if create_node_metrics:
            edges_for_metrics: Set[Tuple[int, int]] = set()
            out_deg = [0] * int(n)
            in_deg = [0] * int(n)
            for (a, b), ex in extra_by_edge.items():
                _skip_2188 = False
                try:
                    va = int(ex.get("vis_ab", 0))
                    vb = int(ex.get("vis_ba", 0))
                    out_deg[int(a)] += va
                    in_deg[int(b)] += va
                    out_deg[int(b)] += vb
                    in_deg[int(a)] += vb

                    if str(vis_edge_rule or VIS_RULE_MUTUAL) == VIS_RULE_EITHER:
                        if va or vb:
                            edges_for_metrics.add((int(a), int(b)))
                    else:
                        if va and vb:
                            edges_for_metrics.add((int(a), int(b)))
                except Exception as _exc:
                    log_swallowed("spatial_network_dialog._run_visibility_network", _exc)
                    log_swallowed("tools/spatial_network_dialog.py:2202 (_run_visibility_network)", _exc)
                    _skip_2188 = True
                if _skip_2188:
                    continue

            extra_node_fields = [
                QgsField("out_deg", QVariant.Int),
                QgsField("in_deg", QVariant.Int),
                QgsField("vis_total", QVariant.Int),
                QgsField("fail_deg", QVariant.Int),
            ]
            extra_values_by_node: Dict[int, Dict[str, Any]] = {}
            for i0 in range(int(n)):
                extra_values_by_node[int(i0)] = {
                    "out_deg": int(out_deg[i0]),
                    "in_deg": int(in_deg[i0]),
                    "vis_total": int(out_deg[i0] + in_deg[i0]),
                    "fail_deg": int(fail_deg[i0]),
                }

            self._add_node_metrics_layer(
                nodes=nodes,
                edges=edges_for_metrics,
                crs_authid=dem_layer.crs().authid(),
                run_group=run_group,
                run_id=run_id,
                title=node_layer_name,
                compute_closeness=compute_closeness,
                compute_betweenness=compute_betweenness,
                extra_node_fields=extra_node_fields,
                extra_values_by_node=extra_values_by_node,
                extra_params=run_params,
            )

        mutual_edges = sum(1 for v in status_by_edge.values() if v == "상호 보임")
        oneway_edges = sum(1 for v in status_by_edge.values() if v == "단방향 보임")
        hidden_edges = sum(1 for v in status_by_edge.values() if v == "상호 안보임")
        fail_edges = sum(1 for v in status_by_edge.values() if v == "샘플 실패")

        msg = (
            f"완료: 검사쌍 {tested_pairs}개 (상호보임 {mutual_edges}, 단방향 {oneway_edges}, "
            f"상호안보임 {hidden_edges}, 실패 {fail_edges})"
        )
        if use_poly_boundary_ratio:
            msg += "  [vis_ratio]"
        if fail_edges > 0:
            msg += (
                f"  미검사 쌍 {fail_edges}개(노드 {n_fail_nodes}개): 해당 노드의 degree 0은 '안 보임'이 아니라 "
                "'검사 불가'일 수 있습니다(fail_deg 필드)."
            )
        log_message(
            f"VisibilityNetwork: {msg} (all_pairs={all_pairs}, max_dist={max_dist}, poly_ratio={use_poly_boundary_ratio}, "
            f"rule={vis_edge_rule}, obs={obs_height}, tgt={tgt_height}, curvature_cc={cc:.2f}, "
            f"step_eff_max={float(getattr(self, '_los_eff_step_max_m', 0.0) or 0.0):.1f}m)",
            level=Qgis.Info,
        )
        push_message(self.iface, "가시성 네트워크", msg, level=(1 if fail_edges > 0 else 0), duration=(12 if fail_edges > 0 else 8))
        self.accept()

    def _add_edge_layer(
        self,
        *,
        nodes: List[_Node],
        edges: List[Tuple[int, int]],
        layer_name: str,
        color: QColor,
        add_dist: bool,
        crs_authid: str,
        status_by_edge: Optional[Dict[Tuple[int, int], str]] = None,
        ratio_by_edge: Optional[Dict[Tuple[int, int], float]] = None,
        extra_fields: Optional[List[QgsField]] = None,
        extra_values_by_edge: Optional[Dict[Tuple[int, int], Dict[str, Any]]] = None,
        label_distance: bool = False,
        extra_params: Optional[Dict[str, Any]] = None,
    ):
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        parent_name = "ArchToolkit - Networks (PPA/Visibility)"
        parent_group = root.findGroup(parent_name)
        if parent_group is None:
            parent_group = root.insertGroup(0, parent_name)
        parent_group = move_group_to_top(root, parent_group)

        run_id = uuid.uuid4().hex[:6]
        run_group = parent_group.insertGroup(0, f"{layer_name}_{run_id}")
        run_group.setExpanded(False)

        layer = QgsVectorLayer(
            f"LineString?crs={crs_authid}",
            layer_name,
            "memory",
        )
        pr = layer.dataProvider()
        fields = [
            QgsField("from_id", QVariant.String),
            QgsField("to_id", QVariant.String),
            QgsField("from_nm", QVariant.String),
            QgsField("to_nm", QVariant.String),
        ]
        if status_by_edge is not None:
            fields.append(QgsField("status", QVariant.String))
        if ratio_by_edge is not None:
            fields.append(QgsField("vis_ratio", QVariant.Double))
        if add_dist:
            fields.append(QgsField("dist_m", QVariant.Double))
            fields.append(QgsField("dist_km", QVariant.Double))
        if extra_fields:
            fields.extend(extra_fields)
        pr.addAttributes(fields)
        layer.updateFields()

        feats = []
        for a, b in edges:
            na = nodes[a]
            nb = nodes[b]
            geom = QgsGeometry.fromPolylineXY([QgsPointXY(na.x, na.y), QgsPointXY(nb.x, nb.y)])
            f = QgsFeature(layer.fields())
            f.setGeometry(geom)
            f["from_id"] = na.fid
            f["to_id"] = nb.fid
            f["from_nm"] = na.name
            f["to_nm"] = nb.name
            if add_dist:
                dist_m = float(math.hypot(nb.x - na.x, nb.y - na.y))
                f["dist_m"] = dist_m
                f["dist_km"] = dist_m / 1000.0
            if status_by_edge is not None:
                f["status"] = str(status_by_edge.get((a, b), ""))
            if ratio_by_edge is not None:
                try:
                    f["vis_ratio"] = float(ratio_by_edge.get((a, b), 0.0))
                except Exception:
                    f["vis_ratio"] = 0.0
            if extra_values_by_edge is not None and (a, b) in extra_values_by_edge:
                for k, v in (extra_values_by_edge.get((a, b)) or {}).items():
                    try:
                        f[str(k)] = v
                    except Exception as _exc:
                        log_swallowed("tools/spatial_network_dialog.py:2327 (_add_edge_layer)", _exc)
            feats.append(f)
        pr.addFeatures(feats)
        layer.updateExtents()

        # Styling
        if status_by_edge is not None:
            categories: List[QgsRendererCategory] = []

            def _mk_sym(col: QColor, *, dashed: bool = False, dotted: bool = False) -> QgsLineSymbol:
                sym = QgsLineSymbol.createSimple(
                    {
                        "color": f"{col.red()},{col.green()},{col.blue()},{col.alpha()}",
                        "width": "0.7",
                    }
                )
                if dashed or dotted:
                    try:
                        ls = "dash" if dashed else "dot"
                        sym.symbolLayer(0).setPenStyle(Qt.DashLine if ls == "dash" else Qt.DotLine)
                    except Exception as _exc:
                        log_swallowed("tools/spatial_network_dialog.py:2348 (_mk_sym)", _exc)
                return sym

            # Backward compatible labels (older builds used "보임/안보임").
            categories.append(QgsRendererCategory("상호 보임", _mk_sym(QColor(0, 180, 0, 230)), "상호 보임"))
            categories.append(QgsRendererCategory("보임", _mk_sym(QColor(0, 180, 0, 230)), "보임"))
            categories.append(QgsRendererCategory("단방향 보임", _mk_sym(QColor(240, 140, 0, 220), dashed=True), "단방향 보임"))
            categories.append(QgsRendererCategory("상호 안보임", _mk_sym(QColor(220, 0, 0, 190), dashed=True), "상호 안보임"))
            categories.append(QgsRendererCategory("안보임", _mk_sym(QColor(220, 0, 0, 190), dashed=True), "안보임"))
            categories.append(QgsRendererCategory("샘플 실패", _mk_sym(QColor(120, 120, 120, 180), dotted=True), "샘플 실패"))

            renderer = QgsCategorizedSymbolRenderer("status", categories)
            layer.setRenderer(renderer)
        else:
            sym = QgsLineSymbol.createSimple(
                {"color": f"{color.red()},{color.green()},{color.blue()},{color.alpha()}", "width": "0.7"}
            )
            layer.setRenderer(QgsSingleSymbolRenderer(sym))

        # Labels: enable only when requested (or small graphs)
        try:
            pal = QgsPalLayerSettings()
            if label_distance and add_dist:
                pal.enabled = True
                pal.isExpression = True
                pal.fieldName = 'round("dist_km", 2) || \' km\''

                fmt = QgsTextFormat()
                fmt.setSize(8)
                fmt.setColor(QColor(40, 40, 40))
                buf = QgsTextBufferSettings()
                buf.setEnabled(True)
                buf.setSize(1.0)
                buf.setColor(QColor(255, 255, 255))
                fmt.setBuffer(buf)
                pal.setFormat(fmt)

                layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
                layer.setLabelsEnabled(True)
            else:
                pal.enabled = False
                layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._add_edge_layer", _exc)

        try:
            edge_params: Dict[str, Any] = dict(extra_params or {})
            edge_params.update(
                {
                    "layer_name": str(layer_name or ""),
                    "add_dist": bool(add_dist),
                    "has_status": bool(status_by_edge is not None),
                    "has_ratio": bool(ratio_by_edge is not None),
                }
            )
            set_archtoolkit_layer_metadata(
                layer,
                tool_id="spatial_network",
                run_id=str(run_id),
                kind="edges",
                units="m",
                params=edge_params,
            )
        except Exception as _exc:
            log_swallowed("spatial_network_dialog._add_edge_layer", _exc)
        project.addMapLayer(layer, False)
        run_group.addLayer(layer)

        return layer, run_group, run_id
