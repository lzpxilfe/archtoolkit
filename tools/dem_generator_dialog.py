# -*- coding: utf-8 -*-

# ArchToolkit - Archaeology Toolkit for QGIS
# Copyright (C) 2026 balguljang2
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
import math
import os
import uuid
from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QTableWidgetItem, QCheckBox, QWidget, QHBoxLayout, QFileDialog, QListWidgetItem
from qgis.PyQt.QtCore import Qt, QSize
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPoint,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsWkbTypes,
)
import processing
import tempfile
from .utils import (
    is_metric_crs,
    is_null_value,
    log_swallowed,
    new_run_id,
    push_message,
    restore_ui_focus,
    set_archtoolkit_layer_metadata,
)
from .qtcompat import FT_DOUBLE
from .atomic_output import (
    atomic_publish_file,
    atomic_publish_files,
    cleanup_staging_path,
    reserve_staging_path,
)
from .live_log_dialog import ensure_live_log_dialog
from .help_dialog import show_help_dialog
from . import dialog_memory
from .icons import icon as plugin_icon
from .kriging_lite import GEOM_Z_SENTINEL, auto_elevation_field

# Load the UI file
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'dem_generator_dialog_base.ui'))

class DemGeneratorDialog(QtWidgets.QDialog, FORM_CLASS):
    # IDW distance exponent passed explicitly to qgis:idwinterpolation (its
    # own default) so the value recorded in the layer metadata is the one used.
    # That algorithm has no search radius: every input vertex weighs in.
    IDW_POWER = 2.0
    # Smallest pixel size the spin box accepts (0 used to reach the grid
    # snapping as "float division by zero").
    MIN_PIXEL_SIZE = 0.01
    # Grid snapping ignores an extent overshoot below this fraction of a cell
    # (reprojection round-off used to add an all-NoData column/row).
    SNAP_TOLERANCE = 1e-6

    # Map scale to recommended pixel size (meters)
    # Based on contour interval standards from National Geographic Information Institute
    SCALE_PIXEL_MAP = {
        '1:1,000 (등고선 1m)': 1.0,
        '1:2,500 (등고선 2m)': 2.0, 
        '1:5,000 (등고선 5m)': 5.0,
        '1:25,000 (등고선 10m)': 10.0,
        '1:50,000 (등고선 20m)': 20.0,
        'Custom (사용자 지정)': None
    }
    
    # Interpolation methods with academic citations
    INTERPOLATION_METHODS = {
        'TIN - Linear (선형)': {
            'algorithm': 'qgis:tininterpolation',
            'method': 0,
            'desc': '들로네 삼각망(Delaunay 1934) 위의 선형 보간. 등고선 데이터에 적합'
        },
        'TIN - Clough-Tocher (곡면)': {
            'algorithm': 'qgis:tininterpolation',
            'method': 1,
            'desc': '삼각망 기반 곡면 보간. 부드러운 지형 표현 [Clough & Tocher, 1965]'
        },
        'IDW (역거리 가중치)': {
            'algorithm': 'qgis:idwinterpolation',
            'method': None,
            'desc': '포인트 데이터에 적합, 등고선에는 비추천 [Shepard, 1968]'
        },
        'Kriging (Lite, Ordinary)': {
            'algorithm': 'archtoolkit:kriging_lite',
            'method': None,
            # "자동 파라미터" overstated what Lite does: kriging_lite.py:8-11 fits no
            # empirical variogram at all, so the variance band is a relative map and
            # the description has to say so where the method is chosen.
            'desc': ('포인트 기반 Ordinary Kriging(Lite). 휴리스틱 파라미터(경험 베리오그램 미적합) '
                     '+ 예측 DEM + 상대 불확실성(_variance.tif) 출력. '
                     '미터 단위 투영 CRS 필요 [Matheron, 1963; Cressie, 1993]')
        }
    }
    
    # DXF Layer definitions for Korean digital topographic maps (DXF/NGI 표준코드 + 구(숫자) 코드 혼재)
    DXF_LAYER_INFO = {
        # --- 현행 수치지형도(일반적으로 많이 쓰이는 F*** 코드) ---
        # 주요 활용 코드(예시): 등고선 F0017111/F0017114, 표고점 F0027217, 기준점 H0027311/H0027312
        'F0017110': {'name': '등고선(기타/확인필요)', 'desc': '데이터셋에 따라 존재할 수 있는 등고선 코드(확인 필요). 보통 F0017111/F0017114를 주로 사용', 'category': '현행(등고선)', 'default': False},
        'F0017111': {'name': '주곡선', 'desc': '등고선(주곡선). DEM 생성의 기본 입력', 'category': '현행(등고선)', 'default': True},
        'F0017112': {'name': '등고선(보조)', 'desc': '등고선 보조 코드(데이터셋별 상이). 필요 시 선택', 'category': '현행(등고선)', 'default': False},
        'F0017113': {'name': '등고선(보조)', 'desc': '등고선 보조 코드(데이터셋별 상이). 필요 시 선택', 'category': '현행(등고선)', 'default': False},
        'F0017114': {'name': '간곡선', 'desc': '등고선(간곡선/보조). 주곡선 사이를 보완', 'category': '현행(등고선)', 'default': True},
        'F0017115': {'name': '지형선(보조)', 'desc': '지형 굴곡 보조선(데이터셋별 상이). DEM 보간에는 보통 선택적', 'category': '현행(지형)', 'default': False},
        'F0017120': {'name': '등고선 수치', 'desc': '등고선 숫자(텍스트). DEM 보간에는 보통 불필요', 'category': '현행(텍스트)', 'default': False},
        'F0027217': {'name': '표고점', 'desc': '표고점(Spot height). 등고선만으로 부족한 지점 보완(권장)', 'category': '현행(포인트)', 'default': True},
        'H0027311': {'name': '삼각점', 'desc': '삼각점(기준점). 데이터에 존재하면 보간 품질 향상(선택)', 'category': '현행(포인트)', 'default': False},
        'H0027312': {'name': '수준점', 'desc': '수준점(기준점). 데이터에 존재하면 보간 품질 향상(선택)', 'category': '현행(포인트)', 'default': False},
        'E0011111': {'name': '하천중심선', 'desc': '하천 물길 (고도값 없을 수 있음)', 'category': '수계', 'default': False},
        'E0011112': {'name': '하천경계선', 'desc': '강물/지면 경계', 'category': '수계', 'default': False},
        'E0041311': {'name': '호수/저수지', 'desc': '수면 경계', 'category': '수계', 'default': False}
        ,
        # --- 구(2000년대 등) 수치지형도: 숫자 레이어 코드 ---
        # 주로 71XX(등고선), 7217(표고점), 73XX(기준점/수치) 형태로 등장합니다.
        # (예) "Layer" IN ('7111','7114','2121','2122')
        "7111": {
            "name": "주곡선(구)",
            "desc": "구 수치지도(숫자 코드) 주곡선(등고선)",
            "category": "구수치(등고선)",
            "default": False,
        },
        "7114": {
            "name": "계곡선(구)",
            "desc": "구 수치지도(숫자 코드) 계곡선(등고선)",
            "category": "구수치(등고선)",
            "default": False,
        },
        "7217": {
            "name": "표고점(구)",
            "desc": "구 수치지도(숫자 코드) 표고점(Spot height)",
            "category": "구수치(표고점)",
            "default": False,
        },
        "7132": {
            "name": "표고점수치(구)",
            "desc": "구 수치지도(숫자 코드) 표고점 수치(텍스트/표기). DEM 보간에는 보통 불필요",
            "category": "구수치(텍스트)",
            "default": False,
        },
        "2121": {
            "name": "해안선(육지)(구)",
            "desc": "구 수치지도(숫자 코드) 해안선(육지). 해안/수면을 0m 기준으로 쓰고 싶을 때만 선택(주의)",
            "category": "구수치(해안)",
            "default": False,
        },
        "2122": {
            "name": "해안선(섬)(구)",
            "desc": "구 수치지도(숫자 코드) 해안선(섬). 해안/수면 처리를 위해 선택할 수 있음(주의)",
            "category": "구수치(해안)",
            "default": False,
        },
    }

    DXF_LAYER_PRESETS = {
        "modern_f": {
            "label": "현행 수치지형도 (F/H 코드)",
            "era": "modern",
            "codes": ["F0017111", "F0017114", "F0027217"],
            "tooltip": (
                "현행 수치지형도(DXF)에서 많이 쓰는 프리셋입니다.\n"
                "- 등고선(F0017111, F0017114) + 표고점(F0027217)\n"
                "- (선택) 기준점: 삼각점(H0027311), 수준점(H0027312)\n"
                "- DEM 보간에 불필요한 텍스트(등고선 수치 등)는 기본 제외"
            ),
        },
        "legacy_numeric": {
            "label": "구 수치지형도 (숫자 레이어)",
            "era": "legacy",
            "codes": ["7111", "7114", "2121", "2122"],
            "tooltip": (
                "구(2000년대 등) 수치지형도에서 레이어 이름이 숫자로 들어오는 경우가 있습니다.\n"
                "예) \"Layer\" IN ('7111','7114','2121','2122')\n"
                "- 71XX: 등고선(주곡선/계곡선)\n"
                "- (선택) 7217: 표고점(Spot height)\n"
                "- 2121/2122(해안선)은 필요할 때만: 해안/수면을 0m 기준으로 강제할 수 있습니다(주의)"
            ),
        },
    }

    
    def __init__(self, iface, parent=None):
        super(DemGeneratorDialog, self).__init__(parent)
        # Remember the last-used inputs between sessions (tools/dialog_memory.py).
        dialog_memory.attach(self, "dem_generator")
        try:
            self.setWindowIcon(plugin_icon("dem.png"))
        except Exception as _exc:
            log_swallowed("dem_generator_dialog.__init__ (icon)", _exc)
        self.setupUi(self)
        self.iface = iface
        self.loaded_dxf_layers = []
        try:
            self.spinPixelSize.setMinimum(float(self.MIN_PIXEL_SIZE))
        except Exception as _exc:
            log_swallowed("dem_generator_dialog.__init__ (pixel minimum)", _exc)
        self._setup_kriging_controls()
        self._setup_help_button()
        
        # Initialize UI
        self.populate_layers()
        self.populate_scales()
        self.populate_interpolation_methods()
        self.setup_layer_table()
        self.setup_layer_presets()
        self.setup_layer_list()
        
        # Connect signals
        self.cmbScale.currentIndexChanged.connect(self.on_scale_changed)
        self.cmbInterpolation.currentIndexChanged.connect(self.on_interpolation_changed)
        self.btnLoadDxf.clicked.connect(self.load_dxf_file)
        self.btnSelectAll.clicked.connect(self.select_all_layers)
        self.btnDeselectAll.clicked.connect(self.deselect_all_layers)
        self.btnRefreshLayers.clicked.connect(self.populate_layers)
        self.btnRun.clicked.connect(self.run_process)
        self.btnClose.clicked.connect(self.reject)
        
        # Set button icon
        self.btnRun.setIcon(plugin_icon("dem.png"))
        self.btnRun.setIconSize(QSize(32, 32))

    def _setup_help_button(self):
        """Add a Help button without editing the .ui file."""
        try:
            self.btnHelp = QtWidgets.QPushButton("도움말", self)
            self.btnHelp.clicked.connect(self._on_help)

            layout = self.layout()
            if layout is None:
                return

            idx = -1
            try:
                idx = int(layout.indexOf(self.btnClose))
            except Exception:
                idx = -1

            if idx >= 0:
                layout.insertWidget(idx, self.btnHelp)
            else:
                layout.addWidget(self.btnHelp)
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._setup_help_button", _exc)

    def _on_help(self):
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            html = (
                "<h2>DEM 생성 (Generate DEM)</h2>"
                "<p>등고선/표고점(벡터)에서 DEM(GeoTIFF)을 생성합니다.</p>"
                "<h3>보간 방법</h3>"
                "<ul>"
                "<li><b>TIN</b>: 등고선(선) 데이터에 권장</li>"
                "<li><b>IDW</b>: 포인트 데이터에 권장. 거리 지수 2, 검색 반경 없이 모든 점을 씁니다(메타데이터에 기록).</li>"
                "<li><b>Kriging (Lite)</b>: 포인트 + 값 필드(Z) 기반. 예측 DEM과 함께 "
                "<code>_variance.tif</code>도 생성됩니다. (미터 단위 투영 CRS 필요)</li>"
                "</ul>"
                "<h3>입력과 좌표계</h3>"
                "<ul>"
                "<li>체크한 레이어의 점은 점으로, 선·면(등고선 등)은 구조선으로 TIN에 들어갑니다. "
                "등고선 레이어와 표고점 레이어, 여러 DXF 도엽을 함께 선택할 수 있습니다. "
                "Kriging은 선·면의 정점을 표본점으로 씁니다.</li>"
                "<li>모든 입력은 작업 좌표계(좌표계가 있는 첫 번째 체크 레이어)로 변환됩니다. 좌표계가 없는 DXF는 "
                "작업 좌표계와 같은 좌표로 간주합니다.</li>"
                "<li>픽셀 크기는 미터입니다. 작업 좌표계가 지리 좌표계(도)이거나 지도 단위가 미터가 아니면 실행하지 않습니다.</li>"
                "<li>표고는 값 필드(Z) 또는 3D 좌표에서 읽습니다. Z 좌표가 모두 0이면(3D 형식이지만 표고 없음) "
                "평평한 DEM을 만들지 않고 중단하며, 표고가 들어 있을 수 있는 숫자 필드를 알려 줍니다.</li>"
                "</ul>"
                # README.md는 분산 래스터를 '보정된 예측분산이 아님'이라고 명시하는데,
                # 정작 도구 안의 도움말은 그냥 '불확실성'이라고만 적고 있었다. 사용자가
                # 실제로 읽는 곳에 한계를 적는다(수치는 kriging_lite.py:8-11 기준).
                "<h3>Kriging (Lite)의 한계</h3>"
                "<ul>"
                "<li><code>Lite</code>는 <b>경험 베리오그램을 적합하지 않습니다</b>. 모델은 지수형으로 고정, "
                "너깃은 표본분산의 5%, 레인지는 최근린 간격 중앙값의 3배이며, 이방성은 고려하지 않습니다.</li>"
                "<li>따라서 <code>_variance.tif</code>는 보정된 예측분산이 아니라, 표본 밀도를 반영한 "
                "<b>상대 불확실성 지도</b>로 읽어야 합니다. 값의 절대 크기보다 <b>상대적 분포</b>를 보세요.</li>"
                "</ul>"
                "<h3>팁</h3>"
                "<ul>"
                "<li>대상 범위가 넓으면 픽셀 크기를 키우면 더 안정적입니다.</li>"
                "<li>출처/레퍼런스는 <code>REFERENCES.md</code>를 참고하세요.</li>"
                "</ul>"
            )
            show_help_dialog(parent=self, title="DEM 생성 도움말", html=html, plugin_dir=plugin_dir, tool_id="dem_generator")
        except Exception:
            try:
                QtWidgets.QMessageBox.information(self, "도움말", "README.md를 참고하세요.")
            except Exception as _exc:
                log_swallowed("tools/dem_generator_dialog.py:242 (_on_help)", _exc)
    
    def setup_layer_list(self):
        """Setup multi-select layer list with checkboxes"""
        self.listLayers.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.listLayers.itemChanged.connect(self.on_layer_item_changed)
        self._updating_checkboxes = False

    def _setup_kriging_controls(self):
        """Add Kriging-only controls without editing the .ui file (Lite mode)."""
        try:
            layout = getattr(self, "gridLayout", None)
            if layout is None:
                return

            self.lblZField = QtWidgets.QLabel("값 필드(Z):", self)
            self.cmbZField = QtWidgets.QComboBox(self)
            self.cmbZField.setMinimumWidth(220)
            try:
                self.cmbZField.setToolTip(
                    "표고/값(Z)을 읽을 필드를 선택하세요. TIN/IDW/Kriging 모두에 적용됩니다.\n"
                    "- 자동(추천): Z_COORD/Elevation/ELEV/height/표고/고도/z 등 흔한 필드를 자동 탐색\n"
                    "- Z 좌표(3D geometry): 3차원 지오메트리의 Z값 사용 (2D 레이어, Z가 모두 0인 레이어는 오류로 중단)"
                )
            except Exception as _exc:
                log_swallowed("tools/dem_generator_dialog.py:267 (_setup_kriging_controls)", _exc)

            self.lblKrigingNeighbors = QtWidgets.QLabel("Kriging 이웃점 수:", self)
            self.spinKrigingNeighbors = QtWidgets.QSpinBox(self)
            self.spinKrigingNeighbors.setRange(3, 64)
            self.spinKrigingNeighbors.setValue(16)
            try:
                self.spinKrigingNeighbors.setToolTip("셀마다 가장 가까운 N개 점만 사용합니다. (N이 클수록 느리지만 매끈해질 수 있음)")
            except Exception as _exc:
                log_swallowed("tools/dem_generator_dialog.py:276 (_setup_kriging_controls)", _exc)

            # Place below interpolation method rows (existing rows: 0..3)
            layout.addWidget(self.lblZField, 4, 0)
            layout.addWidget(self.cmbZField, 4, 1)
            layout.addWidget(self.lblKrigingNeighbors, 5, 0)
            layout.addWidget(self.spinKrigingNeighbors, 5, 1)

            self.lblKrigingHint = QtWidgets.QLabel(
                "<b>Kriging(Lite) 안내</b><br>"
                "- 포인트 값(표고점 등) 기반 보간입니다. 등고선(선)에는 적합하지 않습니다"
                "(선·면을 넣으면 정점을 표본점으로 씁니다).<br>"
                "- 출력은 DEM과 함께 <code>_variance.tif</code>도 생성됩니다.<br>"
                # This banner sits right next to the method combo, so it is the
                # last thing read before running. It has to carry the same
                # caveat as README.md rather than just the word "불확실성".
                "- <b>Lite</b>는 경험 베리오그램을 적합하지 않습니다(지수형 모델 고정, 너깃=표본분산의 5%, "
                "레인지=최근린 간격 중앙값의 3배, 이방성 미고려).<br>"
                "- 그러므로 <code>_variance.tif</code>는 보정된 예측분산이 아니라 <b>상대 불확실성 지도</b>입니다."
            )
            self.lblKrigingHint.setWordWrap(True)
            try:
                self.lblKrigingHint.setStyleSheet("background:#fff3e0; padding:8px; border-radius:3px;")
            except Exception as _exc:
                log_swallowed("tools/dem_generator_dialog.py:293 (_setup_kriging_controls)", _exc)
            layout.addWidget(self.lblKrigingHint, 6, 0, 1, 2)

            # Fill initial items. The Z-field row applies to every method
            # (TIN/IDW used to guess from a short name list with no way to
            # override it); neighbour count and hint stay Kriging-only.
            self._refresh_kriging_value_fields()
            self.lblKrigingNeighbors.hide()
            self.spinKrigingNeighbors.hide()
            self.lblKrigingHint.hide()
        except Exception as _exc:
            # Never block dialog load due to optional UI widgets.
            log_swallowed("tools/dem_generator_dialog.py:304 (_setup_kriging_controls)", _exc)

    def _is_kriging_selected(self) -> bool:
        try:
            method_name = self.cmbInterpolation.currentText()
            info = self.INTERPOLATION_METHODS.get(method_name, {})
            return str(info.get("algorithm") or "") == "archtoolkit:kriging_lite"
        except Exception:
            return False

    def _refresh_kriging_value_fields(self):
        """Populate the Z/value field dropdown from the checked layers (best-effort).

        Lists the union of numeric fields over every checked layer, so a
        multi-layer run can still name the attribute explicitly (the merge
        keeps field names). Used by TIN/IDW and Kriging alike.
        """
        cmb = getattr(self, "cmbZField", None)
        if cmb is None:
            return

        layers = []
        try:
            layers = self.get_selected_layers()
        except Exception:
            layers = []

        previous = ""
        try:
            previous = str(cmb.currentData() or "")
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._refresh_kriging_value_fields", _exc)

        cmb.blockSignals(True)
        try:
            cmb.clear()
            cmb.addItem("자동(추천)", "")
            cmb.addItem("Z 좌표(3D geometry)", GEOM_Z_SENTINEL)

            seen = set()
            for layer in layers:
                if layer is None or not layer.isValid():
                    continue
                try:
                    for f in layer.fields():
                        try:
                            name = str(f.name())
                            if f.isNumeric() and name not in seen:
                                seen.add(name)
                                cmb.addItem(name, name)
                        except Exception as _exc:
                            log_swallowed("tools/dem_generator_dialog.py:341 (_refresh_kriging_value_fields)", _exc)
                except Exception as _exc:
                    log_swallowed("dem_generator_dialog._refresh_kriging_value_fields", _exc)

            # Keep the user's explicit pick across layer toggles when it still exists.
            if previous:
                idx = cmb.findData(previous)
                if idx >= 0:
                    cmb.setCurrentIndex(idx)
        finally:
            cmb.blockSignals(False)
    
    def on_layer_item_changed(self, item):
        """When one checkbox is toggled, toggle all selected items too"""
        if self._updating_checkboxes:
            return
        
        self._updating_checkboxes = True
        new_state = item.checkState()
        
        # If this item is in selection, apply to all selected
        selected_items = self.listLayers.selectedItems()
        if item in selected_items:
            for sel_item in selected_items:
                sel_item.setCheckState(new_state)
        
        self._updating_checkboxes = False

        try:
            self._refresh_kriging_value_fields()
        except Exception as _exc:
            log_swallowed("tools/dem_generator_dialog.py:367 (on_layer_item_changed)", _exc)
    
    def populate_layers(self):
        """Populate layer list with vector layers (checkboxes)"""
        self.listLayers.clear()
        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if layer.type() == Qgis.LayerType.Vector:
                item = QListWidgetItem(layer.name())
                item.setData(Qt.ItemDataRole.UserRole, layer)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.listLayers.addItem(item)
        
        # Auto-check layers containing 'DEM용' in name
        for i in range(self.listLayers.count()):
            item = self.listLayers.item(i)
            if 'DEM용' in item.text() or '등고선' in item.text().lower():
                item.setCheckState(Qt.CheckState.Checked)

        try:
            self._refresh_kriging_value_fields()
        except Exception as _exc:
            log_swallowed("tools/dem_generator_dialog.py:391 (populate_layers)", _exc)
    
    def setup_layer_table(self):
        """Setup the layer selection table with predefined DXF layers"""
        self.tblLayers.setColumnCount(4)
        self.tblLayers.setHorizontalHeaderLabels(['선택', '코드', '명칭', '설명'])
        self.tblLayers.horizontalHeader().setStretchLastSection(True)
        self.tblLayers.setColumnWidth(0, 52)
        self.tblLayers.setColumnWidth(1, 80)
        self.tblLayers.setColumnWidth(2, 100)
        
        self.layer_checkboxes = {}
        self.layer_row_by_code = {}
        row = 0
        self.tblLayers.setRowCount(len(self.DXF_LAYER_INFO))
        
        for layer_code, info in self.DXF_LAYER_INFO.items():
            checkbox = QCheckBox()
            checkbox.setChecked(info['default'])
            checkbox.setToolTip(f"{info['category']}: {info['desc']}")
            self.layer_checkboxes[layer_code] = checkbox
            
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.addWidget(checkbox)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.setContentsMargins(0, 0, 0, 0)
            self.tblLayers.setCellWidget(row, 0, widget)
            
            code_item = QTableWidgetItem(layer_code)
            code_item.setFlags(code_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tblLayers.setItem(row, 1, code_item)
            
            name_item = QTableWidgetItem(info['name'])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tblLayers.setItem(row, 2, name_item)
            
            desc_item = QTableWidgetItem(info['desc'])
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tblLayers.setItem(row, 3, desc_item)

            self.layer_row_by_code[str(layer_code)] = int(row)
            
            row += 1

    def setup_layer_presets(self):
        """Add compact era/preset selectors without changing the .ui file."""
        try:
            # horizontalLayout is defined in dem_generator_dialog_base.ui (row with SelectAll/Deselect/Load DXF).
            layout = getattr(self, "horizontalLayout", None)
            if layout is None:
                return

            # State: keep selections per era (so switching doesn't feel destructive)
            if not hasattr(self, "_selected_codes_by_era"):
                self._selected_codes_by_era = {"modern": set(), "legacy": set()}
            if not hasattr(self, "_current_dxf_era"):
                self._current_dxf_era = "modern"

            # --- Era selector (구/현행) ---
            self.lblDxfEra = QtWidgets.QLabel("시기", self)
            self.cmbDxfEra = QtWidgets.QComboBox(self)
            self.cmbDxfEra.setMinimumWidth(170)
            self.cmbDxfEra.addItem("현행 수치지형도", "modern")
            self.cmbDxfEra.addItem("구 수치지형도(숫자)", "legacy")
            try:
                self.cmbDxfEra.setItemData(
                    0,
                    "현행 수치지형도는 보통 F***/H*** 같은 표준코드(예: F0017111, F0017114, F0027217)를 사용합니다.",
                    Qt.ItemDataRole.ToolTipRole,
                )
                self.cmbDxfEra.setItemData(
                    1,
                    "구 수치지형도는 레이어가 숫자 코드로 들어오는 경우가 있습니다. (예: 7111, 7114, 2121, 2122)",
                    Qt.ItemDataRole.ToolTipRole,
                )
            except Exception as _exc:
                log_swallowed("dem_generator_dialog.setup_layer_presets", _exc)

            self.lblLayerPreset = QtWidgets.QLabel("프리셋", self)
            self.cmbLayerPreset = QtWidgets.QComboBox(self)
            self.cmbLayerPreset.setMinimumWidth(220)

            # Populate presets based on era
            self._refresh_layer_preset_items()

            def _sync_tip():
                try:
                    self.cmbLayerPreset.setToolTip(
                        str(self.cmbLayerPreset.itemData(self.cmbLayerPreset.currentIndex(), Qt.ItemDataRole.ToolTipRole) or "")
                    )
                except Exception as _exc:
                    log_swallowed("tools/dem_generator_dialog.py:483 (_sync_tip)", _exc)

            self.cmbLayerPreset.currentIndexChanged.connect(self.on_layer_preset_changed)
            self.cmbLayerPreset.currentIndexChanged.connect(_sync_tip)
            _sync_tip()

            def _sync_era_tip():
                try:
                    self.cmbDxfEra.setToolTip(
                        str(self.cmbDxfEra.itemData(self.cmbDxfEra.currentIndex(), Qt.ItemDataRole.ToolTipRole) or "")
                    )
                except Exception as _exc:
                    log_swallowed("tools/dem_generator_dialog.py:495 (_sync_era_tip)", _exc)

            # Set default era before connecting (avoids early signal cascades)
            try:
                if str(self._current_dxf_era) == "legacy":
                    self.cmbDxfEra.setCurrentIndex(1)
                else:
                    self.cmbDxfEra.setCurrentIndex(0)
            except Exception as _exc:
                log_swallowed("tools/dem_generator_dialog.py:504 (setup_layer_presets)", _exc)

            self.cmbDxfEra.currentIndexChanged.connect(self.on_dxf_era_changed)
            self.cmbDxfEra.currentIndexChanged.connect(_sync_era_tip)
            _sync_era_tip()

            # Insert after "선택 해제" (keeps the same row height)
            try:
                idx = int(layout.indexOf(self.btnDeselectAll))
                if idx >= 0:
                    layout.insertWidget(idx + 1, self.lblDxfEra)
                    layout.insertWidget(idx + 2, self.cmbDxfEra)
                    layout.insertWidget(idx + 3, self.lblLayerPreset)
                    layout.insertWidget(idx + 4, self.cmbLayerPreset)
                else:
                    layout.insertWidget(0, self.lblDxfEra)
                    layout.insertWidget(1, self.cmbDxfEra)
                    layout.insertWidget(2, self.lblLayerPreset)
                    layout.insertWidget(3, self.cmbLayerPreset)
            except Exception:
                try:
                    layout.insertWidget(0, self.lblDxfEra)
                    layout.insertWidget(1, self.cmbDxfEra)
                    layout.insertWidget(2, self.lblLayerPreset)
                    layout.insertWidget(3, self.cmbLayerPreset)
                except Exception as _exc:
                    log_swallowed("tools/dem_generator_dialog.py:530 (setup_layer_presets)", _exc)

            # Apply initial filter + remember current selection
            self._apply_dxf_era_filter()
            try:
                self._selected_codes_by_era[str(self._current_dxf_era)] = set(self.get_selected_layer_codes())
            except Exception as _exc:
                log_swallowed("tools/dem_generator_dialog.py:537 (setup_layer_presets)", _exc)
        except Exception as _exc:
            log_swallowed("dem_generator_dialog.setup_layer_presets", _exc)

    def _code_era(self, code: str) -> str:
        code = str(code or "")
        return "legacy" if code.isdigit() else "modern"

    def _is_code_visible(self, code: str) -> bool:
        try:
            row = int((self.layer_row_by_code or {}).get(str(code)))
        except Exception:
            return True
        try:
            return not bool(self.tblLayers.isRowHidden(row))
        except Exception:
            return True

    def _set_visible_checked_codes(self, codes):
        codes = set([str(c) for c in (codes or [])])
        for code, checkbox in (self.layer_checkboxes or {}).items():
            if not self._is_code_visible(code):
                continue
            _skip_561 = False
            try:
                checkbox.setChecked(str(code) in codes)
            except Exception as _exc:
                log_swallowed("tools/dem_generator_dialog.py:563 (_set_visible_checked_codes)", _exc)
                _skip_561 = True
            if _skip_561:
                continue

    def _apply_dxf_era_filter(self):
        era = str(getattr(self, "_current_dxf_era", "modern") or "modern")
        for code, row in (self.layer_row_by_code or {}).items():
            _skip_569 = False
            try:
                show = self._code_era(code) == era
                self.tblLayers.setRowHidden(int(row), not bool(show))
            except Exception as _exc:
                log_swallowed("dem_generator_dialog._apply_dxf_era_filter", _exc)
                log_swallowed("tools/dem_generator_dialog.py:572 (_apply_dxf_era_filter)", _exc)
                _skip_569 = True
            if _skip_569:
                continue

    def _refresh_layer_preset_items(self):
        era = str(getattr(self, "_current_dxf_era", "modern") or "modern")
        try:
            self.cmbLayerPreset.blockSignals(True)
        except Exception as _exc:
            log_swallowed("tools/dem_generator_dialog.py:580 (_refresh_layer_preset_items)", _exc)
        try:
            self.cmbLayerPreset.clear()
            self.cmbLayerPreset.addItem("프리셋 선택…", "")
            for key, item in (self.DXF_LAYER_PRESETS or {}).items():
                if str(item.get("era", "")) != era:
                    continue
                self.cmbLayerPreset.addItem(item.get("label", key), key)
                idx = self.cmbLayerPreset.count() - 1
                tip = item.get("tooltip", "")
                if tip:
                    self.cmbLayerPreset.setItemData(idx, tip, Qt.ItemDataRole.ToolTipRole)
        finally:
            try:
                self.cmbLayerPreset.blockSignals(False)
            except Exception as _exc:
                log_swallowed("tools/dem_generator_dialog.py:596 (_refresh_layer_preset_items)", _exc)

    def on_dxf_era_changed(self):
        new_era = ""
        try:
            new_era = str(self.cmbDxfEra.currentData() or "")
        except Exception:
            new_era = ""
        if new_era not in ("modern", "legacy"):
            return

        # Save current era selections (visible only)
        try:
            self._selected_codes_by_era[str(self._current_dxf_era)] = set(self.get_selected_layer_codes())
        except Exception as _exc:
            log_swallowed("tools/dem_generator_dialog.py:611 (on_dxf_era_changed)", _exc)

        self._current_dxf_era = str(new_era)
        self._apply_dxf_era_filter()
        self._refresh_layer_preset_items()

        # Restore selection for new era, or apply recommended defaults
        codes = set((self._selected_codes_by_era or {}).get(str(new_era)) or [])
        if not codes:
            default_key = "legacy_numeric" if new_era == "legacy" else "modern_f"
            codes = set((self.DXF_LAYER_PRESETS.get(default_key) or {}).get("codes") or [])
        self._set_visible_checked_codes(codes)

    def on_layer_preset_changed(self):
        key = ""
        try:
            key = str(self.cmbLayerPreset.currentData() or "")
        except Exception:
            key = ""

        if not key:
            return

        preset = self.DXF_LAYER_PRESETS.get(key) or {}
        codes = set(preset.get("codes") or [])
        if not codes:
            return

        self._set_visible_checked_codes(codes)
        try:
            self._selected_codes_by_era[str(self._current_dxf_era)] = set(self.get_selected_layer_codes())
        except Exception as _exc:
            log_swallowed("tools/dem_generator_dialog.py:643 (on_layer_preset_changed)", _exc)
    
    def select_all_layers(self):
        for code, checkbox in (self.layer_checkboxes or {}).items():
            if not self._is_code_visible(code):
                continue
            try:
                checkbox.setChecked(True)
            except Exception as _exc:
                log_swallowed("tools/dem_generator_dialog.py:652 (select_all_layers)", _exc)
    
    def deselect_all_layers(self):
        for code, checkbox in (self.layer_checkboxes or {}).items():
            if not self._is_code_visible(code):
                continue
            try:
                checkbox.setChecked(False)
            except Exception as _exc:
                log_swallowed("tools/dem_generator_dialog.py:661 (deselect_all_layers)", _exc)
    
    def get_selected_layer_codes(self):
        """All CHECKED codes, regardless of which era tab is currently shown.

        Filtering by row visibility made the run-time query depend on the tab
        the user happened to be browsing — running while on the "구(old)" tab
        silently dropped every checked modern code and produced an empty DEM.
        """
        selected = []
        for code, checkbox in (self.layer_checkboxes or {}).items():
            _skip_673 = False
            try:
                if checkbox.isChecked():
                    selected.append(str(code))
            except Exception as _exc:
                log_swallowed("tools/dem_generator_dialog.py:676 (get_selected_layer_codes)", _exc)
                _skip_673 = True
            if _skip_673:
                continue
        return selected
    
    def load_dxf_file(self):
        """Load multiple DXF files"""
        dxf_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "DXF 파일 선택 (Ctrl+클릭으로 여러 개 선택)",
            "",
            "DXF Files (*.dxf);;All Files (*)"
        )
        
        if not dxf_paths:
            return
        
        selected_codes = self.get_selected_layer_codes()
        if not selected_codes:
            push_message(self.iface, "오류", "최소 하나의 레이어를 선택해주세요", level=2)
            restore_ui_focus(self)
            return
        
        query = '"Layer" IN (' + ','.join([f"'{code}'" for code in selected_codes]) + ')'
        
        total_features = 0
        loaded_count = 0
        failed = []
        empty = []

        for dxf_path in dxf_paths:
            base = os.path.basename(dxf_path)
            try:
                layer_name = os.path.splitext(base)[0] + "_DEM용"
                layer = QgsVectorLayer(dxf_path + "|layername=entities", layer_name, "ogr")

                if layer.isValid():
                    layer.setSubsetString(query)
                    QgsProject.instance().addMapLayer(layer)
                    self.loaded_dxf_layers.append(layer)
                    n_feat = int(layer.featureCount())
                    total_features += n_feat
                    loaded_count += 1
                    if n_feat <= 0:
                        # Loaded but matched none of the selected codes: visible
                        # now rather than as an empty DEM at run time.
                        empty.append(base)
                else:
                    # An unreadable file (e.g. a .dwg renamed to .dxf) is not an
                    # exception: isValid() is simply False, and this used to fall
                    # through with no message at all.
                    failed.append(base)

            except Exception as _exc:
                log_swallowed("dem_generator_dialog.load_dxf_file", _exc)
                failed.append(base)

        self.populate_layers()

        if failed:
            push_message(
                self.iface,
                "경고" if loaded_count > 0 else "오류",
                f"{loaded_count}개 로드, {len(failed)}개 실패: {', '.join(failed)}",
                level=1 if loaded_count > 0 else 2,
                duration=10,
            )
        if empty:
            push_message(
                self.iface,
                "경고",
                f"선택한 레이어 코드에 해당하는 피처가 0개인 파일: {', '.join(empty)} (레이어 코드 선택을 확인하세요)",
                level=1,
                duration=10,
            )
        if loaded_count > 0:
            push_message(self.iface, "성공", f"{loaded_count}개 DXF 로드 완료: 총 {total_features:,}개 피처", level=0)
    
    def populate_scales(self):
        self.cmbScale.clear()
        for scale in self.SCALE_PIXEL_MAP.keys():
            self.cmbScale.addItem(scale)
        # Default to 1:5,000 (index 2)
        self.cmbScale.setCurrentIndex(2)
        self.on_scale_changed()
    
    def on_scale_changed(self):
        scale = self.cmbScale.currentText()
        recommended = self.SCALE_PIXEL_MAP.get(scale)
        
        if recommended is not None:
            self.spinPixelSize.setValue(recommended)
            self.lblRecommended.setText(f"(권장: {recommended}m)")
        else:
            self.lblRecommended.setText("(직접 입력)")
    
    def populate_interpolation_methods(self):
        self.cmbInterpolation.clear()
        for method_name in self.INTERPOLATION_METHODS.keys():
            self.cmbInterpolation.addItem(method_name)
        self.on_interpolation_changed()
    
    def on_interpolation_changed(self):
        method_name = self.cmbInterpolation.currentText()
        method_info = self.INTERPOLATION_METHODS.get(method_name, {})
        desc = method_info.get('desc', '')
        self.lblInterpDesc.setText(desc)

        show_kriging = str(method_info.get("algorithm") or "") == "archtoolkit:kriging_lite"
        # The Z-field selector is shown for every method: TIN/IDW read the
        # same attribute (or geometry Z) and the user must be able to pick it.
        for w_name in ("lblZField", "cmbZField"):
            w = getattr(self, w_name, None)
            if w is None:
                continue
            try:
                w.setVisible(True)
            except Exception as _exc:
                log_swallowed("tools/dem_generator_dialog.py:760 (on_interpolation_changed)", _exc)
        for w_name in ("lblKrigingNeighbors", "spinKrigingNeighbors", "lblKrigingHint"):
            w = getattr(self, w_name, None)
            if w is None:
                continue
            try:
                w.setVisible(bool(show_kriging))
            except Exception as _exc:
                log_swallowed("tools/dem_generator_dialog.py:760 (on_interpolation_changed)", _exc)

        try:
            self._refresh_kriging_value_fields()
        except Exception as _exc:
            log_swallowed("tools/dem_generator_dialog.py:766 (on_interpolation_changed)", _exc)

    def get_selected_layers(self):
        """Get list of checked layers from the list widget"""
        selected_layers = []
        for i in range(self.listLayers.count()):
            item = self.listLayers.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                layer = item.data(Qt.ItemDataRole.UserRole)
                if layer:
                    selected_layers.append(layer)
        return selected_layers

    def _is_plugin_dxf_layer(self, layer) -> bool:
        """True for a layer this dialog loaded from DXF (tracked, or named *_DEM용).

        The DXF layer-code filter only makes sense for those: a CAD-derived
        shapefile also owns a "Layer" column, and filtering it by the code
        table's defaults dropped its contours (or every feature) silently.
        """
        try:
            if str(layer.name() or "").endswith("_DEM용"):
                return True
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._is_plugin_dxf_layer", _exc)
        try:
            lid = str(layer.id())
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._is_plugin_dxf_layer", _exc)
            return False
        for lyr in list(self.loaded_dxf_layers or []):
            try:
                if str(lyr.id()) == lid:
                    return True
            except Exception as _exc:
                # A DXF layer removed from the project leaves a dead wrapper behind.
                log_swallowed("dem_generator_dialog._is_plugin_dxf_layer", _exc)
        return False

    @staticmethod
    def _field_index(fields, name) -> int:
        """Index of ``name`` in ``fields`` (exact, then case-insensitive) or -1."""
        try:
            return int(fields.lookupField(str(name)))
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._field_index", _exc)
        try:
            return int(fields.indexFromName(str(name)))
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._field_index", _exc)
            return -1

    def _resolve_z_field(self, fields) -> str:
        """Elevation field NAME auto-detected in ``fields``: the same resolver Kriging uses, or ""."""
        try:
            return str(auto_elevation_field(fields) or "")
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._resolve_z_field", _exc)
        return ""

    def _explicit_z_choice(self) -> str:
        """The Z-field combo's pick: a field name, GEOM_Z_SENTINEL, or "" for auto."""
        try:
            v = getattr(self, "cmbZField", None)
            if v is not None:
                return str(v.currentData() or "").strip()
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._explicit_z_choice", _exc)
        return ""

    @staticmethod
    def _layer_has_z(layer) -> bool:
        """True when the layer's geometries carry a Z coordinate.

        QgsInterpolator's ValueZ source rejects every 2D feature, so a 2D
        layer sent down that path yields an all-NoData raster. Trust the WKB
        type first, then sample a few features (some providers report a
        generic type).
        """
        try:
            if QgsWkbTypes.hasZ(layer.wkbType()):
                return True
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._layer_has_z", _exc)
        try:
            seen = 0
            for feat in layer.getFeatures():
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue
                seen += 1
                if geom.constGet().is3D():
                    return True
                if seen >= 20:
                    break
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._layer_has_z", _exc)
        return False

    @staticmethod
    def _snap_extent_to_pixel(extent, pixel_size):
        """Expand ``extent`` so its width/height are whole multiples of ``pixel_size``.

        qgis:tininterpolation / idwinterpolation only take ceil(extent/pixel)
        column and row counts from PIXEL_SIZE and QgsGridFileWriter then
        divides the extent by those counts, so an unsnapped extent yields
        cells smaller than requested and not square (DEMGEN-05). Anchored at
        the top-left corner, like the writer. An overshoot below
        SNAP_TOLERANCE of a cell is treated as round-off, not as one more
        column/row. Returns (rect, ncols, nrows).
        """
        px = float(pixel_size)
        xmin = float(extent.xMinimum())
        ymax = float(extent.yMaximum())
        width = float(extent.width())
        height = float(extent.height())
        # A shortfall of less than SNAP_TOLERANCE of a cell is round-off (e.g. a
        # reprojected corner at x0 + 300.0000000001), not a reason for a column
        # whose centre lies outside every input.
        tol = float(DemGeneratorDialog.SNAP_TOLERANCE)
        ncols = int(max(1, math.ceil(width / px - tol)))
        nrows = int(max(1, math.ceil(height / px - tol)))
        xmax = xmin + ncols * px
        ymin = ymax - nrows * px
        # Guard the algorithm's own ceil() against float drift
        # (e.g. 3*0.1/0.1 == 3.0000000000000004 would add a column).
        for _ in range(8):
            if math.ceil((xmax - xmin) / px) <= ncols:
                break
            xmax = math.nextafter(xmax, xmin)
        for _ in range(8):
            if math.ceil((ymax - ymin) / px) <= nrows:
                break
            ymin = math.nextafter(ymin, ymax)
        return QgsRectangle(xmin, ymin, xmax, ymax), ncols, nrows

    @staticmethod
    def _raster_has_valid_cells(path):
        """False when band 1 of ``path`` holds no valid (non-NoData) cell; None if unknown.

        Scans in strips with GDAL/numpy instead of QgsRasterDataProvider.
        bandStatistics(), which would leave an .aux.xml sidecar beside the
        staged file that the publish rename then orphans.
        """
        ds = None
        try:
            import numpy as np
            from osgeo import gdal  # type: ignore

            ds = gdal.Open(str(path))
            if ds is None:
                return None
            band = ds.GetRasterBand(1)
            if band is None:
                return None
            nodata = band.GetNoDataValue()
            xsize, ysize = int(ds.RasterXSize), int(ds.RasterYSize)
            step = 256
            for yoff in range(0, ysize, step):
                rows = min(step, ysize - yoff)
                arr = band.ReadAsArray(0, yoff, xsize, rows)
                if arr is None:
                    return None
                arr = np.asarray(arr, dtype=float)
                valid = np.isfinite(arr)
                if nodata is not None:
                    valid &= arr != float(nodata)
                if bool(valid.any()):
                    return True
            return False
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._raster_has_valid_cells", _exc)
            return None
        finally:
            ds = None

    @staticmethod
    def _actual_pixel_size(layer):
        """(x, y) cell size the published raster really has, or (None, None)."""
        try:
            if layer is None or not layer.isValid():
                return None, None
            return float(layer.rasterUnitsPerPixelX()), float(layer.rasterUnitsPerPixelY())
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._actual_pixel_size", _exc)
            return None, None

    @staticmethod
    def _pixel_size_note(requested, actual_x, actual_y) -> str:
        """"" when the raster's cells match the requested size, else a short disclosure."""
        try:
            req = float(requested)
            if actual_x is None or actual_y is None or not (req > 0):
                return ""
            tol = req * 1e-6
            if abs(float(actual_x) - req) <= tol and abs(float(actual_y) - req) <= tol:
                return ""
            return f", 실제 셀 크기 {float(actual_x):.4g} x {float(actual_y):.4g} m"
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._pixel_size_note", _exc)
            return ""

    @staticmethod
    def _working_crs(layers):
        """CRS every input is brought into: the first checked layer that HAS one.

        A DXF sheet carries no CRS; taking it as the working CRS used to leave
        the DEM without one even when another checked layer had a valid CRS.
        """
        first = None
        for lyr in layers or []:
            try:
                crs = lyr.crs()
            except Exception as _exc:
                log_swallowed("dem_generator_dialog._working_crs", _exc)
                crs = None
            if crs is None:
                continue
            if first is None:
                first = crs
            if crs.isValid():
                return crs
        return first

    @staticmethod
    def _crs_label(crs) -> str:
        try:
            if crs is None or not crs.isValid():
                return "좌표계 미지정"
            return str(crs.authid() or crs.description() or "사용자 좌표계")
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._crs_label", _exc)
            return "좌표계 미지정"

    def _crs_unit_problem(self, crs) -> str:
        """Korean refusal text when pixel sizes in metres cannot apply to ``crs``, else "".

        The pixel size is typed in metres but the interpolators apply it in map
        units: in EPSG:4326 "5 m" became 5 degrees (a 1x1-cell DEM reported as
        success with pixel_size_m=5). An unknown CRS (a DXF sheet) is not
        refused here: its coordinates cannot be judged.
        """
        try:
            if crs is None or not crs.isValid():
                return ""
            if is_metric_crs(crs):
                return ""
            label = self._crs_label(crs)
            if crs.isGeographic():
                return (f"작업 좌표계({label})가 지리 좌표계(도 단위)입니다. 픽셀 크기(m)가 도(degree)로 적용되므로 "
                        "실행하지 않았습니다. 미터 단위 투영 좌표계로 변환한 레이어를 사용하세요.")
            try:
                unit = QgsUnitTypes.toString(crs.mapUnits())
            except Exception as _exc:
                log_swallowed("dem_generator_dialog._crs_unit_problem", _exc)
                unit = "?"
            return (f"작업 좌표계({label})의 지도 단위가 미터가 아닙니다({unit}). 픽셀 크기(m)를 그대로 적용할 수 없어 "
                    "실행하지 않았습니다. 미터 단위 투영 좌표계로 변환한 레이어를 사용하세요.")
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._crs_unit_problem", _exc)
            return ""

    @staticmethod
    def _set_layer_crs(layer, crs):
        """Give a scratch memory layer ``crs``, or an explicitly UNKNOWN CRS.

        A memory layer created without a CRS defaults to EPSG:4326, which
        would stamp a DXF sheet's TM metres as WGS 84 degrees on the DEM.
        """
        try:
            if crs is not None and crs.isValid():
                layer.setCrs(crs)
            else:
                layer.setCrs(QgsCoordinateReferenceSystem())
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._set_layer_crs", _exc)

    @staticmethod
    def _geometry_kind(geom) -> str:
        """'point' / 'line' / 'polygon' for a single-kind geometry, else ""."""
        try:
            gtype = QgsWkbTypes.geometryType(geom.wkbType())
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._geometry_kind", _exc)
            return ""
        if gtype == Qgis.GeometryType.Point:
            return "point"
        if gtype == Qgis.GeometryType.Line:
            return "line"
        if gtype == Qgis.GeometryType.Polygon:
            return "polygon"
        return ""

    def _feature_parts(self, geom, ct, keep_z):
        """Single-kind parts of ``geom`` as (kind, multi-part QgsGeometry, is_3d).

        Transformed into the working CRS, curves segmentized, M dropped, and Z
        dropped unless the elevation comes from geometry Z. A geometry
        collection (DXF block) is split so each part lands in its own kind.
        """
        g = QgsGeometry(geom)
        if ct is not None:
            g.transform(ct)
        if QgsWkbTypes.isCurvedType(g.wkbType()):
            g = QgsGeometry(g.constGet().segmentize())
        if QgsWkbTypes.flatType(g.wkbType()) == Qgis.WkbType.GeometryCollection:
            pieces = list(g.asGeometryCollection())
        else:
            pieces = [g]
        out = []
        for piece in pieces:
            kind = self._geometry_kind(piece)
            if not kind or piece.isEmpty():
                continue
            ag = piece.constGet().clone()
            is_3d = bool(ag.is3D())
            ag.dropMValue()
            if not keep_z:
                ag.dropZValue()
            part = QgsGeometry(ag)
            part.convertToMultiType()
            out.append((kind, part, is_3d))
        return out

    def _prepare_inputs(self, layers, *, field_name, working_crs, query):
        """Copy every usable feature of ``layers`` into one memory layer per geometry kind.

        Replaces native:mergevectorlayers, which refuses a line layer next to
        a point layer (contours + spot heights, or two DXF sheets whose
        "entities" layers QGIS typed after different first entities). Reading
        the layer objects themselves keeps their subset filter and unsaved
        edits, and every method (TIN/IDW/Kriging) then reads these same
        features. Plugin-loaded DXF layers get the run-time code ``query``
        on an independent handle, as before.
        """
        use_field = bool(field_name)
        suffix = "" if use_field else "Z"
        mem = {}
        for kind, wkb in (("point", "MultiPoint"), ("line", "MultiLineString"), ("polygon", "MultiPolygon")):
            lyr = QgsVectorLayer(wkb + suffix, f"dem_prepared_{kind}", "memory")
            self._set_layer_crs(lyr, working_crs)
            if use_field:
                lyr.dataProvider().addAttributes([QgsField(str(field_name), FT_DOUBLE)])
                lyr.updateFields()
            mem[kind] = lyr

        feats = {kind: [] for kind in mem}
        info = {
            "mem": mem,
            "counts": {kind: 0 for kind in mem},
            "extent": None,
            "skipped_no_value": 0,
            "skipped_2d": 0,
            "skipped_transform": 0,
            "layers_with_field": 0,
            "filter_before": 0,
            "filter_after": 0,
            "filter_applied": False,
            "crs_assumed": [],
            "z_min": None,
            "z_max": None,
            "numeric_ranges": {},
        }
        ranges = info["numeric_ranges"]
        for src in layers or []:
            handle = src
            if query and self._is_plugin_dxf_layer(src):
                try:
                    dxf = QgsVectorLayer(src.source(), src.name(), src.providerType())
                    if dxf.isValid() and dxf.fields().indexFromName("Layer") >= 0:
                        info["filter_before"] += int(dxf.featureCount())
                        dxf.setSubsetString(query)
                        info["filter_after"] += int(dxf.featureCount())
                        info["filter_applied"] = True
                        handle = dxf
                except Exception as _exc:
                    log_swallowed("dem_generator_dialog._prepare_inputs (dxf filter)", _exc)
            fields = handle.fields()
            fidx = -1
            if use_field:
                fidx = self._field_index(fields, field_name)
                if fidx < 0:
                    continue
                info["layers_with_field"] += 1
            numeric = []
            if not use_field:
                numeric = [(i, str(f.name())) for i, f in enumerate(fields) if f.isNumeric()]
            ct = None
            src_crs = handle.crs()
            if working_crs is not None and working_crs.isValid():
                if src_crs.isValid() and src_crs != working_crs:
                    ct = QgsCoordinateTransform(src_crs, working_crs, QgsProject.instance())
                elif not src_crs.isValid():
                    info["crs_assumed"].append(str(src.name()))
            for feat in handle.getFeatures():
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue
                value = None
                if use_field:
                    raw = feat.attribute(fidx)
                    if not is_null_value(raw):
                        try:
                            value = float(raw)
                        except (TypeError, ValueError):
                            value = None
                    if value is None or not math.isfinite(value):
                        info["skipped_no_value"] += 1
                        continue
                parts = []
                try:
                    parts = self._feature_parts(geom, ct, keep_z=not use_field)
                except Exception as _exc:
                    log_swallowed("dem_generator_dialog._prepare_inputs (transform)", _exc)
                    info["skipped_transform"] += 1
                for kind, part, is_3d in parts:
                    if not use_field and not is_3d:
                        # QgsInterpolator's ValueZ source rejects 2D parts; say so.
                        info["skipped_2d"] += 1
                        continue
                    if not use_field:
                        for vtx in part.vertices():
                            z = float(vtx.z())
                            if math.isfinite(z):
                                info["z_min"] = z if info["z_min"] is None else min(info["z_min"], z)
                                info["z_max"] = z if info["z_max"] is None else max(info["z_max"], z)
                    out = QgsFeature(mem[kind].fields())
                    out.setGeometry(part)
                    if use_field:
                        out.setAttributes([value])
                    feats[kind].append(out)
                    bbox = part.boundingBox()
                    if info["extent"] is None:
                        info["extent"] = QgsRectangle(bbox)
                    else:
                        info["extent"].combineExtentWith(bbox)
                if parts and numeric:
                    for i, name in numeric:
                        raw = feat.attribute(i)
                        if is_null_value(raw):
                            continue
                        try:
                            v = float(raw)
                        except (TypeError, ValueError):
                            v = float("nan")
                        if not math.isfinite(v):
                            continue
                        lo_hi = ranges.get(name)
                        ranges[name] = (v, v) if lo_hi is None else (min(lo_hi[0], v), max(lo_hi[1], v))

        for kind, flist in feats.items():
            if flist:
                ok = mem[kind].dataProvider().addFeatures(flist)
                if isinstance(ok, tuple):
                    ok = ok[0]
                if not ok:
                    raise RuntimeError(f"준비 레이어({kind})에 피처를 쓰지 못했습니다.")
                mem[kind].updateExtents()
            info["counts"][kind] = len(flist)
        return info

    @staticmethod
    def _flat_z_problem(info) -> str:
        """Korean refusal text when geometry Z carries no elevation, else "".

        A 3D-typed layer whose Z is 0 everywhere (CAD/ArcGIS export with the
        height in a "Contour" field) used to give a flat 0 m DEM reported as
        success. A constant non-zero Z is refused only when a numeric field
        with varying values could hold the real elevations.
        """
        z_min, z_max = info.get("z_min"), info.get("z_max")
        if z_min is None or z_max is None or z_max != z_min:
            return ""
        candidates = [(name, lo, hi) for name, (lo, hi) in (info.get("numeric_ranges") or {}).items() if hi > lo]
        if z_min != 0.0 and not candidates:
            return ""
        desc = ", ".join(f"{name}({lo:g}-{hi:g})" for name, lo, hi in candidates[:6]) or "없음"
        return (f"Z 좌표가 모두 {z_min:g}입니다(3D 형식이지만 표고가 Z에 없는 자료로 보입니다). "
                f"표고가 들어 있을 수 있는 숫자 필드: {desc}. 값 필드(Z)에서 표고 필드를 직접 선택하세요. "
                "평평한 DEM을 만들지 않고 중단했습니다.")

    @staticmethod
    def _save_prepared(info, working_crs):
        """Write each non-empty prepared kind to a temp file: {kind: (path, layer)}.

        GeoPackage normally; FlatGeobuf when the working CRS is unknown (DXF),
        because GeoPackage stores "no CRS" as "Undefined geographic SRS",
        which QGIS reads as a valid CRS and would stamp on the DEM.
        """
        known = bool(working_crs is not None and working_crs.isValid())
        ext = "gpkg" if known else "fgb"
        out = {}
        for kind in ("point", "line", "polygon"):
            if int(info["counts"].get(kind) or 0) <= 0:
                continue
            path = os.path.join(tempfile.gettempdir(), f"archtoolkit_dem_{kind}_{uuid.uuid4().hex[:8]}.{ext}")
            out[kind] = (path, None)
            res = processing.run("native:savefeatures", {"INPUT": info["mem"][kind], "OUTPUT": path})
            load_src = str(res.get("OUTPUT")) if (isinstance(res, dict) and res.get("OUTPUT")) else path
            lyr = QgsVectorLayer(load_src, f"dem_{kind}", "ogr")
            if not lyr.isValid():
                raise RuntimeError(f"준비 레이어({kind}) 저장에 실패했습니다: {path}")
            out[kind] = (path, lyr)
        return out

    @staticmethod
    def _kriging_samples(info, field_name, working_crs):
        """One point per prepared vertex (points, and line/polygon vertices) for Kriging.

        Returns (layer, n_from_lines). Kriging reads exactly the features the
        TIN/IDW path reads; line and polygon inputs contribute their vertices.
        """
        use_field = bool(field_name)
        lyr = QgsVectorLayer("Point" if use_field else "PointZ", "dem_kriging_samples", "memory")
        DemGeneratorDialog._set_layer_crs(lyr, working_crs)
        if use_field:
            lyr.dataProvider().addAttributes([QgsField(str(field_name), FT_DOUBLE)])
            lyr.updateFields()
        feats = []
        from_lines = 0
        for kind in ("point", "line", "polygon"):
            src = info["mem"][kind]
            if int(info["counts"].get(kind) or 0) <= 0:
                continue
            for feat in src.getFeatures():
                value = feat.attribute(0) if use_field else None
                for vtx in feat.geometry().vertices():
                    f = QgsFeature(lyr.fields())
                    if use_field:
                        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(vtx.x(), vtx.y())))
                        f.setAttributes([value])
                    else:
                        f.setGeometry(QgsGeometry(QgsPoint(vtx.x(), vtx.y(), vtx.z())))
                    feats.append(f)
                    if kind != "point":
                        from_lines += 1
        if feats:
            lyr.dataProvider().addFeatures(feats)
            lyr.updateExtents()
        return lyr, from_lines

    @staticmethod
    def _stray_prj_path(staged) -> str:
        """Where QGIS < 3.38's grid writer drops the .prj for ``staged`` (complete base name + .prj)."""
        return os.path.splitext(str(staged))[0] + ".prj"

    @staticmethod
    def _grid_as_geotiff(staged, output_path, run_id, crs):
        """(staged path, converted-from driver) of a GeoTIFF that carries ``crs``.

        QGIS < 3.38 writes the TIN/IDW grid as Arc/Info ASCII whatever the
        extension and puts the CRS only in a .prj named after the STAGED file,
        which the publish rename left behind: the published ".tif" had no CRS.
        That grid is copied into a real GeoTIFF with the working CRS. Newer
        QGIS writes a GeoTIFF with the CRS already and is returned untouched.
        """
        try:
            from osgeo import gdal  # type: ignore
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._grid_as_geotiff (gdal)", _exc)
            return staged, ""
        wkt = ""
        try:
            if crs is not None and crs.isValid():
                wkt = str(crs.toWkt() or "")
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._grid_as_geotiff (crs)", _exc)
        ds = None
        try:
            ds = gdal.Open(str(staged))
            if ds is None:
                return staged, ""
            driver = str(ds.GetDriver().ShortName or "")
            has_srs = bool(ds.GetProjection())
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._grid_as_geotiff (open)", _exc)
            return staged, ""
        finally:
            ds = None
        if driver == "GTiff":
            if not has_srs and wkt:
                upd = None
                try:
                    upd = gdal.Open(str(staged), gdal.GA_Update)
                    if upd is not None:
                        upd.SetProjection(wkt)
                except Exception as _exc:
                    log_swallowed("dem_generator_dialog._grid_as_geotiff (srs)", _exc)
                finally:
                    upd = None
            return staged, ""
        target = reserve_staging_path(output_path, f"{run_id}-gtiff")
        res = None
        try:
            res = gdal.Translate(
                str(target),
                str(staged),
                format="GTiff",
                # Float32 like QGIS >= 3.38's writer and the Kriging output
                # (the ASCII reader picks Float32 or Float64 by content).
                outputType=gdal.GDT_Float32,
                outputSRS=(wkt if (wkt and not has_srs) else None),
                creationOptions=["TILED=YES", "COMPRESS=LZW"],
            )
        except Exception as _exc:
            log_swallowed("dem_generator_dialog._grid_as_geotiff (translate)", _exc)
            res = None
        if res is None:
            cleanup_staging_path(target)
            return staged, ""
        res = None
        cleanup_staging_path(staged)
        return target, driver

    @staticmethod
    def _grid_meta(pixel_size, actual_x, actual_y, metric):
        """Pixel-size metadata keyed by unit: metres only for a metric working CRS."""
        if metric:
            return {"pixel_size_m": float(pixel_size), "pixel_size_x_m": actual_x, "pixel_size_y_m": actual_y}
        return {
            "pixel_size_map_units": float(pixel_size),
            "pixel_size_x_map_units": actual_x,
            "pixel_size_y_map_units": actual_y,
            "crs_units": "unknown",
        }

    def run_process(self):
        """Run the DEM generation process (Prepare per geometry kind → Filter → Interpolate)"""
        selected_layers = self.get_selected_layers()
        output_path = self.fileOutput.filePath()
        pixel_size = self.spinPixelSize.value()
        run_id = new_run_id("dem")
        
        if not selected_layers:
            push_message(self.iface, "오류", "레이어를 체크해주세요", level=2)
            restore_ui_focus(self)
            return
        if not output_path:
            push_message(self.iface, "오류", "출력 파일 경로를 지정해주세요", level=2)
            restore_ui_focus(self)
            return
        try:
            pixel_ok = math.isfinite(float(pixel_size)) and float(pixel_size) > 0
        except (TypeError, ValueError):
            pixel_ok = False
        if not pixel_ok:
            push_message(self.iface, "오류", "픽셀 크기는 0보다 커야 합니다.", level=2)
            restore_ui_focus(self)
            return

        # Live log window (non-modal) so users can see progress in real time.
        ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)

        method_name = self.cmbInterpolation.currentText()
        method_info = self.INTERPOLATION_METHODS.get(method_name, {})
        algorithm = method_info.get('algorithm', 'qgis:tininterpolation')
        method_param = method_info.get('method')
        
        # Build query for DXF layer filtering
        selected_codes = self.get_selected_layer_codes()

        # No silent auto-excludes: use exactly what the user selected in the table.
        # The code filter is meant for DXF sheets this dialog loaded itself
        # (NGII layer codes in "Layer"); a CAD-derived shapefile owns a "Layer"
        # column too, and filtering it by the table's DEFAULT codes silently
        # dropped its contours (DEMGEN-03). Apply the filter only when every
        # checked layer is a plugin-loaded DXF layer.
        dxf_layer_names = [lyr.name() for lyr in selected_layers if self._is_plugin_dxf_layer(lyr)]
        other_layer_names = [lyr.name() for lyr in selected_layers if not self._is_plugin_dxf_layer(lyr)]
        if selected_codes and dxf_layer_names and not other_layer_names:
            query = '"Layer" IN (' + ','.join([f"'{code}'" for code in selected_codes]) + ')'
        else:
            query = None
            if selected_codes and dxf_layer_names and other_layer_names:
                push_message(
                    self.iface,
                    "안내",
                    "레이어 코드 필터는 DXF 로드 시 적용된 상태를 그대로 쓰고, 일반 레이어("
                    + ", ".join(other_layer_names[:3])
                    + ")가 함께 선택되어 실행 시 재적용하지 않습니다.",
                    level=1,
                    duration=8,
                )
            elif selected_codes and not dxf_layer_names:
                # A DXF opened through the QGIS browser owns a "Layer" column
                # too, but the table is not applied to it; say so instead of
                # letting the ticked codes look active.
                with_layer_field = []
                for lyr in selected_layers:
                    try:
                        if lyr.fields().indexFromName("Layer") >= 0:
                            with_layer_field.append(lyr.name())
                    except Exception as _exc:
                        log_swallowed("dem_generator_dialog.run_process", _exc)
                if with_layer_field:
                    push_message(
                        self.iface,
                        "안내",
                        "레이어 코드 필터는 이 대화상자의 'DXF 불러오기'로 연 레이어에만 적용됩니다. "
                        + ", ".join(with_layer_field[:3])
                        + " 에는 코드 표가 적용되지 않아 모든 피처가 보간에 쓰입니다.",
                        level=1,
                        duration=9,
                    )

        # Decide the elevation source BEFORE merging: native:mergevectorlayers
        # upgrades the output to Z as soon as ONE input has Z and pads the
        # others with Z=0, which the ValueZ path would then interpolate as
        # genuine 0 m elevations (DEMGEN-06). Explicit combo pick first, then
        # the same name list Kriging uses, else geometry Z - which every
        # checked layer must actually carry.
        z_choice = self._explicit_z_choice()
        if z_choice == GEOM_Z_SENTINEL:
            planned_field = ""
        elif z_choice:
            planned_field = z_choice
        else:
            planned_field = ""
            for lyr in selected_layers:
                planned_field = self._resolve_z_field(lyr.fields())
                if planned_field:
                    break
        if not planned_field:
            no_z = [lyr.name() for lyr in selected_layers if not self._layer_has_z(lyr)]
            if no_z:
                push_message(
                    self.iface,
                    "오류",
                    "표고 필드를 찾을 수 없고 3D 좌표도 없습니다: " + ", ".join(no_z)
                    + " (값 필드(Z)를 선택하거나 Z 좌표가 있는 레이어를 사용하세요)",
                    level=2,
                    duration=10,
                )
                restore_ui_focus(self)
                return
        elif len(selected_layers) > 1:
            missing = [lyr.name() for lyr in selected_layers if self._field_index(lyr.fields(), planned_field) < 0]
            if missing:
                push_message(
                    self.iface,
                    "안내",
                    f"'{planned_field}' 필드가 없는 레이어의 피처는 보간에서 제외됩니다: " + ", ".join(missing),
                    level=1,
                    duration=8,
                )

        # Pixel sizes are metres; refuse a working CRS where they are not
        # (TIN/IDW used to publish 5-degree cells as "pixel_size_m 5").
        working_crs = self._working_crs(selected_layers)
        crs_problem = self._crs_unit_problem(working_crs)
        if crs_problem:
            push_message(self.iface, "오류", crs_problem, level=2, duration=12)
            restore_ui_focus(self)
            return
        crs_metric = bool(working_crs is not None and working_crs.isValid() and is_metric_crs(working_crs))
        if str(algorithm or "") == "archtoolkit:kriging_lite" and not crs_metric:
            push_message(
                self.iface,
                "오류",
                f"Kriging(Lite)은 미터 단위 투영 좌표계가 필요합니다({self._crs_label(working_crs)}). "
                "좌표계를 지정한 레이어를 사용하세요.",
                level=2,
                duration=10,
            )
            restore_ui_focus(self)
            return

        push_message(self.iface, "처리 중", f"{len(selected_layers)}개 레이어 준비 중...", level=0)
        self.hide()
        QtWidgets.QApplication.processEvents()

        prepared_files = {}
        try:
            staging_out = None
            stray_prj = None

            # Step 1-3: copy every checked layer's features, per geometry kind,
            # into the working CRS with the elevation source resolved ONCE
            # (planned_field, or geometry Z). TIN/IDW and Kriging all read these.
            field_name = str(planned_field or "")
            if field_name:
                for lyr in selected_layers:
                    idx = self._field_index(lyr.fields(), field_name)
                    if idx >= 0:
                        field_name = str(lyr.fields()[idx].name())
                        break
            prep = self._prepare_inputs(selected_layers, field_name=field_name, working_crs=working_crs, query=query)

            if prep["filter_applied"]:
                before_n, after_n = int(prep["filter_before"]), int(prep["filter_after"])
                if after_n <= 0:
                    push_message(
                        self.iface,
                        "오류",
                        f"레이어 코드 필터로 {before_n:,}개 중 0개만 남았습니다. 레이어 코드 선택(표)을 확인하세요.",
                        level=2,
                        duration=10,
                    )
                    restore_ui_focus(self)
                    return
                if after_n < before_n:
                    push_message(
                        self.iface,
                        "안내",
                        f"레이어 코드 필터로 {before_n:,}개 중 {after_n:,}개 피처만 사용합니다.",
                        level=1,
                        duration=8,
                    )

            if field_name and int(prep["layers_with_field"]) <= 0:
                push_message(self.iface, "오류", f"값 필드 '{field_name}'가 선택한 레이어에 없습니다.", level=2)
                restore_ui_focus(self)
                return

            counts = dict(prep["counts"])
            n_total = int(sum(counts.values()))
            if n_total <= 0 and not field_name and int(prep["skipped_2d"]) > 0:
                # ValueZ on 2D geometry: QgsInterpolator rejects every feature
                # and QgsGridFileWriter writes -9999 into each pixel (DEMGEN-01).
                push_message(
                    self.iface,
                    "오류",
                    "표고 필드를 찾을 수 없고 3D 좌표도 없습니다. 값 필드(Z)를 선택하거나 Z 좌표가 있는 레이어를 사용하세요.",
                    level=2,
                    duration=10,
                )
                restore_ui_focus(self)
                return
            combined_extent = prep["extent"]
            try:
                _ext_w = float(combined_extent.width()) if combined_extent is not None else float("nan")
                _ext_h = float(combined_extent.height()) if combined_extent is not None else float("nan")
            except Exception as _exc:
                log_swallowed("dem_generator_dialog.run_process", _exc)
                _ext_w = _ext_h = float("nan")
            if n_total <= 0 or combined_extent is None or not (math.isfinite(_ext_w) and math.isfinite(_ext_h)):
                # Used to surface as "cannot convert float NaN to integer" from
                # inside the algorithm, naming neither the layer nor the cause.
                push_message(self.iface, "오류", "입력 레이어의 범위를 구할 수 없습니다(피처가 없나요?). 레이어와 코드 필터를 확인하세요.", level=2, duration=10)
                restore_ui_focus(self)
                return

            flat_z = "" if field_name else self._flat_z_problem(prep)
            if flat_z:
                push_message(self.iface, "오류", flat_z, level=2, duration=15)
                restore_ui_focus(self)
                return

            skipped = []
            if int(prep["skipped_no_value"]) > 0:
                skipped.append(f"값 없음(NULL/숫자 아님) {int(prep['skipped_no_value']):,}개")
            if int(prep["skipped_2d"]) > 0:
                skipped.append(f"Z 없는 2D 피처 {int(prep['skipped_2d']):,}개")
            if int(prep["skipped_transform"]) > 0:
                skipped.append(f"좌표 변환 실패 {int(prep['skipped_transform']):,}개")
            if skipped:
                push_message(self.iface, "안내", "보간에서 제외: " + ", ".join(skipped), level=1, duration=8)
            if not (working_crs is not None and working_crs.isValid()):
                push_message(
                    self.iface,
                    "안내",
                    "입력에 좌표계가 없습니다(DXF 등). 픽셀 크기를 좌표 단위 그대로 적용했고, DEM에는 좌표계가 기록되지 않습니다. "
                    "필요하면 결과 레이어에 좌표계를 지정하세요.",
                    level=1,
                    duration=8,
                )
            if prep["crs_assumed"]:
                push_message(
                    self.iface,
                    "안내",
                    "좌표계가 없는 레이어(" + ", ".join(prep["crs_assumed"][:3])
                    + f")는 작업 좌표계({self._crs_label(working_crs)})와 같은 좌표로 간주했습니다.",
                    level=1,
                    duration=8,
                )

            value_source = "attribute" if field_name else "geometry_z"
            value_source_label = field_name if field_name else "Z 좌표(3D geometry)"
            recorded_field = field_name if field_name else GEOM_Z_SENTINEL
            input_counts = {"points": int(counts.get("point") or 0), "lines": int(counts.get("line") or 0),
                            "polygons": int(counts.get("polygon") or 0)}
            z_range = None
            if not field_name and prep["z_min"] is not None:
                z_range = [float(prep["z_min"]), float(prep["z_max"])]

            # Snap once: TIN/IDW and Kriging write the same grid.
            interp_extent, snap_cols, snap_rows = self._snap_extent_to_pixel(combined_extent, pixel_size)
            # Kriging (Lite) path: implemented in pure Python (numpy) + QGIS, no external providers.
            if str(algorithm or "") == "archtoolkit:kriging_lite":
                progress = None
                staging_pred = None
                staging_var = None
                try:
                    from .kriging_lite import ordinary_kriging_lite_to_geotiff

                    # The source resolved ONCE above (DEMGEN-07 follow-up): the
                    # combo's "자동" entry carries "" and kriging_lite used to
                    # re-resolve it on the merged fields, picking another
                    # layer's column than TIN and the exclusion notice named.
                    value_field = field_name if field_name else GEOM_Z_SENTINEL
                    krig_layer, krig_from_lines = self._kriging_samples(prep, field_name, working_crs)
                    if krig_from_lines > 0:
                        push_message(
                            self.iface,
                            "안내",
                            f"Kriging: 선/면 피처의 정점 {krig_from_lines:,}개를 표본점으로 사용합니다 "
                            "(등고선 정점은 간격이 고르지 않아 Kriging에는 권장되지 않습니다).",
                            level=1,
                            duration=8,
                        )

                    neighbors = 16
                    try:
                        n0 = getattr(self, "spinKrigingNeighbors", None)
                        if n0 is not None:
                            neighbors = int(n0.value())
                    except Exception:
                        neighbors = 16

                    base, ext = os.path.splitext(str(output_path))
                    if not ext:
                        ext = ".tif"
                    variance_path = f"{base}_variance{ext}"

                    # Stage both rasters beside their finals so the prediction
                    # and its variance are published together via a pair of
                    # atomic renames; a crash mid-compute or mid-write cannot
                    # truncate a previously-generated DEM at output_path.
                    staging_pred = reserve_staging_path(output_path, run_id)
                    staging_var = reserve_staging_path(variance_path, run_id)

                    progress = QtWidgets.QProgressDialog("Kriging 계산 중…", "취소", 0, 100, self.iface.mainWindow())
                    try:
                        progress.setWindowModality(Qt.WindowModality.WindowModal)
                        progress.setMinimumDuration(0)
                    except Exception as _exc:
                        log_swallowed("tools/dem_generator_dialog.py:928 (run_process)", _exc)
                    progress.show()

                    def progress_cb(pct: int, msg: str):
                        try:
                            progress.setValue(int(pct))
                            progress.setLabelText(str(msg))
                        except Exception as _exc:
                            log_swallowed("dem_generator_dialog.progress_cb", _exc)
                        try:
                            QtWidgets.QApplication.processEvents()
                        except Exception as _exc:
                            log_swallowed("tools/dem_generator_dialog.py:940 (progress_cb)", _exc)

                    def is_cancelled() -> bool:
                        try:
                            return bool(progress.wasCanceled())
                        except Exception:
                            return False

                    push_message(self.iface, "처리 중", f"{method_name} 보간 실행 중...", level=0)
                    info = ordinary_kriging_lite_to_geotiff(
                        layer=krig_layer,
                        value_field=value_field,
                        extent=interp_extent,
                        pixel_size=float(pixel_size),
                        out_path=str(staging_pred),
                        variance_path=str(staging_var),
                        neighbors=int(neighbors),
                        progress_cb=progress_cb,
                        is_cancelled=is_cancelled,
                    )

                    try:
                        progress.setValue(100)
                        progress.close()
                    except Exception as _exc:
                        log_swallowed("tools/dem_generator_dialog.py:965 (run_process)", _exc)

                    # Both rasters finished writing: publish them together.
                    atomic_publish_files([
                        (staging_pred, output_path),
                        (staging_var, variance_path),
                    ])
                    staging_pred = None
                    staging_var = None

                    # DEMGEN-07: record the field kriging_lite actually read
                    # (the "자동" entry carries "") and say it on completion.
                    resolved_field = str((info.get("params") or {}).get("value_field") or value_field or "")
                    value_label = "Z 좌표(3D geometry)" if resolved_field == GEOM_Z_SENTINEL else (resolved_field or "자동")

                    if os.path.exists(output_path):
                        out_layer = self.iface.addRasterLayer(output_path, "생성된 DEM (Kriging)")
                        actual_px_x, actual_px_y = self._actual_pixel_size(out_layer)
                        try:
                            if out_layer is not None:
                                set_archtoolkit_layer_metadata(
                                    out_layer,
                                    tool_id="dem_generate",
                                    run_id=str(run_id),
                                    kind="dem",
                                    units="m",
                                    params={
                                        "pixel_size_m": float(pixel_size),
                                        "pixel_size_x_m": actual_px_x,
                                        "pixel_size_y_m": actual_px_y,
                                        "method": str(method_name or ""),
                                        "algorithm": str(algorithm or ""),
                                        "value_field": resolved_field,
                                        "value_source": value_source,
                                        "working_crs": self._crs_label(working_crs),
                                        "inputs": dict(input_counts),
                                        "kriging_samples_from_line_vertices": int(krig_from_lines),
                                        "kriging": dict(info.get("params") or {}),
                                        "n_points": int(info.get("n_points") or 0),
                                        "grid": {
                                            "ncols": int(info.get("ncols") or 0),
                                            "nrows": int(info.get("nrows") or 0),
                                        },
                                    },
                                )
                        except Exception as _exc:
                            log_swallowed("dem_generator_dialog.run_process", _exc)

                        try:
                            if variance_path and os.path.exists(variance_path):
                                var_layer = self.iface.addRasterLayer(variance_path, "Kriging 분산 (Variance)")
                                if var_layer is not None:
                                    set_archtoolkit_layer_metadata(
                                        var_layer,
                                        tool_id="dem_generate",
                                        run_id=str(run_id),
                                        kind="kriging_variance",
                                        units="m^2",
                                        params={
                                            "pixel_size_m": float(pixel_size),
                                            "pixel_size_x_m": actual_px_x,
                                            "pixel_size_y_m": actual_px_y,
                                            "method": str(method_name or ""),
                                            "algorithm": str(algorithm or ""),
                                            "value_field": resolved_field,
                                            "value_source": value_source,
                                            "working_crs": self._crs_label(working_crs),
                                            "kriging": dict(info.get("params") or {}),
                                        },
                                    )
                        except Exception as _exc:
                            log_swallowed("dem_generator_dialog.run_process", _exc)

                        push_message(self.iface, "완료", f"Kriging 보간 완료! (값 필드: {value_label})", level=0, duration=6)
                        self.accept()
                    else:
                        push_message(self.iface, "오류", "Kriging 출력이 생성되지 않았습니다.", level=2)
                        restore_ui_focus(self)
                    return
                except Exception as e:
                    try:
                        if progress is not None:
                            progress.close()
                    except Exception as _exc:
                        log_swallowed("tools/dem_generator_dialog.py:1033 (run_process)", _exc)
                    push_message(self.iface, "오류", f"Kriging 처리 중 오류: {str(e)}", level=2, duration=10)
                    restore_ui_focus(self)
                    return
                finally:
                    # Remove any staged raster left by a cancel/failure; after a
                    # successful publish these are None and this is a no-op.
                    for _staged in (staging_pred, staging_var):
                        if _staged:
                            cleanup_staging_path(_staged)


            
            # Interpolate into a staged sibling of the final path so a failed or
            # killed run cannot truncate a previously-generated DEM at output_path.
            staging_out = reserve_staging_path(output_path, run_id)
            stray_prj = self._stray_prj_path(staging_out)
            # One interpolation source per geometry kind: points as points,
            # lines and polygon rings as structure lines. Deciding this from
            # the merged layer's type made the DEM depend on the first entity
            # of a DXF sheet (contours were enforced only when it was a line).
            prepared_files = self._save_prepared(prep, working_crs)
            interp_rows = []
            for kind, (_path, prep_layer) in prepared_files.items():
                src_type = 0 if kind == "point" else 1
                if field_name:
                    idx = self._field_index(prep_layer.fields(), field_name)
                    interp_rows.append(f"{prep_layer.source()}::~::0::~::{idx}::~::{src_type}")
                else:
                    interp_rows.append(f"{prep_layer.source()}::~::1::~::0::~::{src_type}")
            interp_data = "::|::".join(interp_rows)
            # Snapped extent (above): PIXEL_SIZE is the cell size actually
            # written (the algorithms only take ceil(extent/pixel) counts from it).
            params = {
                'INTERPOLATION_DATA': interp_data,
                'EXTENT': interp_extent,
                'PIXEL_SIZE': pixel_size,
                'OUTPUT': staging_out
            }
            if method_param is not None:
                params['METHOD'] = method_param
            is_idw = str(algorithm or "") == "qgis:idwinterpolation"
            if is_idw:
                params['DISTANCE_COEFFICIENT'] = float(self.IDW_POWER)

            push_message(
                self.iface,
                "처리 중",
                f"{method_name} 보간 실행 중... (값: {value_source_label}, {snap_cols}x{snap_rows}셀)",
                level=0,
            )
            QtWidgets.QApplication.processEvents()

            # Step 4: Run TIN interpolation
            result = processing.run(algorithm, params)

            # An all-NoData raster (every feature rejected by the interpolator)
            # is a failure, not a DEM: never publish it over a previous result.
            if result and os.path.exists(staging_out) and self._raster_has_valid_cells(staging_out) is False:
                push_message(
                    self.iface,
                    "오류",
                    "보간 결과에 유효한 셀이 없습니다(전부 NoData). 표고 필드/3D 좌표와 레이어 코드 필터를 확인하세요. "
                    "출력 파일은 갱신하지 않았습니다.",
                    level=2,
                    duration=10,
                )
                restore_ui_focus(self)
                return

            # QGIS < 3.38 writes Arc/Info ASCII (no CRS in the file); make the
            # published .tif the GeoTIFF with the working CRS the help promises.
            converted_from = ""
            if result and os.path.exists(staging_out):
                staging_out, converted_from = self._grid_as_geotiff(staging_out, output_path, run_id, working_crs)

            # Publish atomically only once the interpolation produced a file.
            # Success below is bound to THIS publish, not to output_path merely
            # existing (a stale DEM from an earlier run used to be re-loaded
            # and stamped with this run's parameters - DEMGEN-04).
            published = False
            if result and os.path.exists(staging_out):
                atomic_publish_file(staging_out, output_path)
                staging_out = None
                published = True

            # Add result to map
            if published and os.path.exists(output_path):
                out_layer = self.iface.addRasterLayer(output_path, "생성된 DEM")
                actual_px_x, actual_px_y = self._actual_pixel_size(out_layer)
                try:
                    if out_layer is not None:
                        meta = self._grid_meta(pixel_size, actual_px_x, actual_px_y, crs_metric)
                        meta.update({
                            "method": str(method_name or ""),
                            "algorithm": str(algorithm or ""),
                            "value_field": recorded_field,
                            "value_source": value_source,
                            "working_crs": self._crs_label(working_crs),
                            "inputs": dict(input_counts),
                            "interpolation_sources": {"points": "points", "lines": "structure_lines",
                                                      "polygons": "structure_lines"},
                            "grid": {"ncols": int(snap_cols), "nrows": int(snap_rows)},
                        })
                        if z_range is not None:
                            meta["z_range"] = z_range
                        if is_idw:
                            meta["idw"] = {"power": float(self.IDW_POWER), "search": "all_points"}
                        if converted_from:
                            meta["grid_file_converted_from"] = str(converted_from)
                        set_archtoolkit_layer_metadata(
                            out_layer,
                            tool_id="dem_generate",
                            run_id=str(run_id),
                            kind="dem",
                            # Value units (elevation). The grid's own unit is in
                            # params: pixel_size_m only for a metric CRS, else
                            # pixel_size_map_units + crs_units "unknown".
                            units="m",
                            params=meta,
                        )
                except Exception as _exc:
                    log_swallowed("dem_generator_dialog.run_process", _exc)
                px_note = self._pixel_size_note(pixel_size, actual_px_x, actual_px_y)
                if px_note:
                    push_message(
                        self.iface,
                        "안내",
                        f"요청 픽셀 크기 {float(pixel_size):g} m와 실제 셀 크기가 다릅니다{px_note} (레이어 메타데이터에 실제값 기록)",
                        level=1,
                        duration=8,
                    )
                push_message(
                    self.iface,
                    "완료",
                    f"DEM 생성 완료! ({len(selected_layers)}개 레이어 병합, 값: {value_source_label}{px_note})",
                    level=0,
                    duration=6,
                )
                self.accept()
            else:
                if os.path.exists(output_path):
                    push_message(
                        self.iface,
                        "오류",
                        "DEM이 생성되지 않았습니다. 출력 경로에 있는 파일은 이전 실행의 결과입니다.",
                        level=2,
                        duration=10,
                    )
                else:
                    push_message(self.iface, "오류", "DEM이 생성되지 않았습니다.", level=2)
                restore_ui_focus(self)
            
        except Exception as e:
            push_message(self.iface, "오류", f"처리 중 오류: {str(e)}", level=2)
            restore_ui_focus(self)
        finally:
            leftovers = [path for path, _lyr in prepared_files.values() if path and os.path.exists(path)]
            if leftovers:
                from .utils import cleanup_files
                cleanup_files(leftovers)
            # Remove a staged interpolation output left by a failed/aborted run;
            # after a successful publish staging_out is None and this is a no-op.
            if staging_out:
                cleanup_staging_path(staging_out)
            # QGIS < 3.38 drops "<staged name>.prj" beside the staged grid; the
            # publish rename never carried it along.
            if stray_prj:
                cleanup_staging_path(stray_prj)




