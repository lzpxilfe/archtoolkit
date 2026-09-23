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
"""
Map Styling Tool for ArchToolkit
Applies professional cartographic styles to South Korean Digital Topographic Map layers.
"""
import copy
import json
import math
import os
from datetime import datetime

from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QPointF, QUrl
from qgis.PyQt.QtGui import QColor, QPainter, QDesktopServices
from qgis.core import (
    Qgis,
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsLineSymbol,
    QgsFillSymbol,
    QgsRuleBasedRenderer,
    QgsSingleSymbolRenderer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleFillSymbolLayer,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsFeatureRequest,
    QgsSingleBandPseudoColorRenderer,
    QgsRasterShader,
    QgsColorRampShader,
    QgsSingleBandGrayRenderer,
    QgsHillshadeRenderer,
    QgsLayerTreeLayer,
    QgsCoordinateTransform,
    QgsContrastEnhancement,
    QgsPointXY,
    QgsUnitTypes,
)
from .qtcompat import FT_STRING, RBS_ALL, SHADER_DISCRETE
from .utils import (
    is_null_value,
    log_message,
    log_swallowed,
    get_archtoolkit_layer_metadata,
    new_run_id,
    push_message,
    restore_ui_focus,
    set_archtoolkit_layer_metadata,
)
from .help_dialog import show_help_dialog
from . import dialog_memory
from .icons import icon as plugin_icon

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'map_styling_dialog_base.ui'))

# Layer codes and names follow the official NGII (국토지리정보원) code tables:
#   - 국토지리정보원, "전국 연속수치지형도 코드 및 레이어 설명서" Ver 5.1.1
#     (ngii.go.kr file_down.do?sq=58476): p.15 도로중심선 A0023210-A0023217,
#     p.44 건물 B0014110-B0014119, p.119 하천 E0022110/E0022112/E0022113/E0022115;
#   - "수치지도 지형지물 표준코드" attachment on law.go.kr (flDownload.do?flSeq=42285173).
# Both list the same names. Line widths are this tool's cartographic choice.
DEFAULT_CODE_CONFIG = {
    "roads": {
        "name": "Style: 도로",
        "color": "#ff9501",
        "rules": [
            {"code": "A0023211", "width_mm": 1.2, "label": "고속국도"},
            {"code": "A0023212", "width_mm": 1.0, "label": "일반국도"},
            {"code": "A0023213", "width_mm": 0.8, "label": "지방도"},
            {"code": "A0023214", "width_mm": 0.7, "label": "특별시도ㆍ광역시도"},
            {"code": "A0023215", "width_mm": 0.5, "label": "시도"},
            {"code": "A0023216", "width_mm": 0.4, "label": "군도"},
            {"code": "A0023217", "width_mm": 0.3, "label": "면리간도로"},
            {"code": "A0023210", "width_mm": 0.4, "label": "(도로중심선)미분류"},
        ],
    },
    "rivers": {
        "name": "Style: 하천",
        "color": "#1ea1ff",
        "rules": [
            {"code": "E0022110", "width_mm": 1.0, "label": "(하천)미분류"},
            {"code": "E0022115", "width_mm": 0.4, "label": "하천중심선"},
            {"code": "E0022112", "width_mm": 0.7, "label": "세류"},
            {"code": "E0022113", "width_mm": 0.3, "label": "건천"},
        ],
    },
    "buildings": {
        "name": "Style: 건물",
        "codes": [
            "B0014110", "B0014111", "B0014112", "B0014113", "B0014114",
            "B0014115", "B0014116", "B0014117", "B0014118", "B0014119",
        ],
        "labels": {
            "B0014110": "(건물경계)미분류",
            "B0014111": "주택외건물",
            "B0014112": "주택",
            "B0014113": "연립주택",
            "B0014114": "공사중건물",
            "B0014115": "아파트",
            "B0014116": "무벽건물",
            "B0014117": "온실",
            "B0014118": "가건물",
            "B0014119": "집단가옥경계",
        },
        "fill_color": "#ffffff",
        "outline_color": "#666666",
        "outline_width_mm": 0.1,
        "shadow_alpha": 100,
    },
}

# Degenerate building outlines (a part that cannot close into a ring, e.g. a
# two-point wall) are buffered by this many METRES to stay visible - only in a
# CRS whose units convert to metres; never in a geographic CRS.
BUILDING_LINE_BUFFER_M = 0.05

class MapStylingDialog(QtWidgets.QDialog, FORM_CLASS):
    
    def __init__(self, iface, parent=None):
        super(MapStylingDialog, self).__init__(parent)
        # Remember the last-used inputs between sessions (tools/dialog_memory.py).
        dialog_memory.attach(self, "map_styling")
        try:
            self.setWindowIcon(plugin_icon("styling.png"))
        except Exception as _exc:
            log_swallowed("map_styling_dialog.__init__ (icon)", _exc)
        self.setupUi(self)
        self.iface = iface
        self._style_run_id = None
        
        # Setup
        self.populate_layers()
        self.cmbDemLayer.setFilters(Qgis.LayerFilter.RasterLayer)
        self.code_config = self._load_code_config()
        self._sync_code_config_ui()
        
        # Connect signals
        self.btnSelectAll.clicked.connect(lambda: self.set_all_checks(True))
        self.btnDeselectAll.clicked.connect(lambda: self.set_all_checks(False))
        self.btnApply.clicked.connect(self.apply_styling)
        self.btnClose.clicked.connect(self.close)
        if hasattr(self, "btnOpenCodeConfig"):
            self.btnOpenCodeConfig.clicked.connect(self.open_code_config_file)
        if hasattr(self, "btnReloadCodeConfig"):
            self.btnReloadCodeConfig.clicked.connect(self.reload_code_config)
        if hasattr(self, "btnExportPreset"):
            self.btnExportPreset.clicked.connect(self.export_qml_preset)
        self._setup_help_button()

    def _setup_help_button(self):
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
            log_swallowed("map_styling_dialog._setup_help_button", _exc)

    def _on_help(self):
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            html = (
                "<h2>도면 시각화 (Map Styling)</h2>"
                "<p>한국 수치지형도(DXF) 레이어를 분류/집계하고, 도로·하천·건물 등 카토그래피 스타일을 적용합니다.</p>"
                "<h3>코드와 동작</h3>"
                "<ul>"
                "<li>코드 이름은 국토지리정보원 '전국 연속수치지형도 코드 및 레이어 설명서'(Ver 5.1.1)와"
                " '수치지도 지형지물 표준코드'를 따릅니다: 도로중심선 A0023210-A0023217,"
                " 하천 E0022110/E0022112/E0022113/E0022115, 건물 B0014110-B0014119. 선폭은 이 도구의 표현 선택입니다.</li>"
                "<li>원본 레이어는 '원본 레이어 (숨김)' 그룹으로 옮겨 숨깁니다. 스타일 대상 코드가 아닌 피처 수는"
                " 완료 메시지에, 코드별 목록은 로그에 남깁니다.</li>"
                "<li>건물: 선은 부분(part)마다 닫아 면으로 만들고, 면은 그대로 씁니다. 같은 코드의 점(주기/텍스트)은"
                f" 제외합니다. 닫을 수 없는 선은 투영 좌표계에서만 {BUILDING_LINE_BUFFER_M}m 버퍼로 표시하고,"
                " 지리 좌표계에서는 제외합니다.</li>"
                "<li>배경 지형: 음영기복 + 그레이(DEM 최소-최대로 늘인 명암, 곱하기 40%) + 고도 색상(4분위 구간,"
                " 범례에 구간값 표시).</li>"
                "</ul>"
                "<h3>커스터마이즈</h3>"
                "<ul>"
                "<li>DXF 코드 매핑은 <code>tools/map_styling_codes.json</code>에서 수정할 수 있습니다.</li>"
                "<li>QML/프리셋 내보내기로 프로젝트 재사용성을 높일 수 있습니다.</li>"
                "</ul>"
            )
            show_help_dialog(parent=self, title="Map Styling 도움말", html=html, plugin_dir=plugin_dir, tool_id="map_styling")
        except Exception:
            try:
                QtWidgets.QMessageBox.information(self, "도움말", "README.md를 참고하세요.")
            except Exception as _exc:
                log_swallowed("tools/map_styling_dialog.py:155 (_on_help)", _exc)

    def _code_config_path(self):
        return os.path.join(os.path.dirname(__file__), "map_styling_codes.json")

    def _load_code_config(self):
        """Load DXF code/style mapping from JSON (fallback to built-in defaults)."""
        self._code_config_load_error = None
        config = copy.deepcopy(DEFAULT_CODE_CONFIG)
        path = self._code_config_path()

        if not os.path.exists(path):
            self._code_config_load_error = f"매핑 파일이 없습니다: {path}"
            return config

        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except Exception as e:
            self._code_config_load_error = f"매핑 파일을 읽는 중 오류: {e}"
            return config

        if not isinstance(loaded, dict):
            self._code_config_load_error = "매핑 파일 형식이 올바르지 않습니다(JSON object 필요)."
            return config

        for key in ("roads", "rivers", "buildings"):
            if not isinstance(loaded.get(key), dict):
                continue
            cat = loaded[key]
            if key in ("roads", "rivers"):
                if isinstance(cat.get("name"), str):
                    config[key]["name"] = cat["name"]
                if isinstance(cat.get("color"), str):
                    config[key]["color"] = cat["color"]
                if isinstance(cat.get("rules"), list):
                    rules = []
                    for item in cat["rules"]:
                        if not isinstance(item, dict):
                            continue
                        code = item.get("code")
                        width = item.get("width_mm", item.get("width"))
                        label = item.get("label", "")
                        if not (isinstance(code, str) and code.strip()):
                            continue
                        _skip_201 = False
                        try:
                            width_f = float(width)
                        except Exception as _exc:
                            log_swallowed("map_styling_dialog._load_code_config", _exc)
                            log_swallowed("tools/map_styling_dialog.py:203 (_load_code_config)", _exc)
                            _skip_201 = True
                        if _skip_201:
                            continue
                        if not isinstance(label, str):
                            label = str(label)
                        rules.append({"code": code.strip(), "width_mm": width_f, "label": label})
                    config[key]["rules"] = rules
            else:
                if isinstance(cat.get("name"), str):
                    config[key]["name"] = cat["name"]
                if isinstance(cat.get("codes"), list):
                    config[key]["codes"] = [str(c) for c in cat["codes"] if str(c).strip()]
                if isinstance(cat.get("fill_color"), str):
                    config[key]["fill_color"] = cat["fill_color"]
                if isinstance(cat.get("outline_color"), str):
                    config[key]["outline_color"] = cat["outline_color"]
                if isinstance(cat.get("labels"), dict):
                    config[key]["labels"] = {str(k): str(v) for k, v in cat["labels"].items()}
                if cat.get("outline_width_mm") is not None:
                    try:
                        config[key]["outline_width_mm"] = float(cat["outline_width_mm"])
                    except Exception as _exc:
                        log_swallowed("map_styling_dialog._load_code_config", _exc)
                if cat.get("shadow_alpha") is not None:
                    try:
                        config[key]["shadow_alpha"] = int(cat["shadow_alpha"])
                    except Exception as _exc:
                        log_swallowed("map_styling_dialog._load_code_config", _exc)

        return config

    def _sync_code_config_ui(self):
        try:
            if hasattr(self, "lblCodeConfigPath"):
                self.lblCodeConfigPath.setText(self._code_config_path())
        except Exception as _exc:
            log_swallowed("tools/map_styling_dialog.py:236 (_sync_code_config_ui)", _exc)

    def open_code_config_file(self):
        path = self._code_config_path()
        if not os.path.exists(path):
            push_message(self.iface, "정보", f"매핑 파일이 없습니다: {path}", level=1)
            return
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception:
            push_message(self.iface, "오류", "매핑 파일을 여는 중 오류가 발생했습니다.", level=2)

    def reload_code_config(self):
        self.code_config = self._load_code_config()
        self._sync_code_config_ui()
        if getattr(self, "_code_config_load_error", None):
            push_message(self.iface, "경고", f"기본 매핑으로 대체했습니다: {self._code_config_load_error}", level=1)
        else:
            push_message(self.iface, "완료", "DXF 코드 매핑을 다시 불러왔습니다.", level=0)

    def populate_layers(self):
        """Fill the list widget with vector layers from the project"""
        self.lstLayers.clear()
        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if isinstance(layer, QgsVectorLayer):
                item = QtWidgets.QListWidgetItem(layer.name())
                item.setData(Qt.ItemDataRole.UserRole, layer.id())
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.lstLayers.addItem(item)

    def set_all_checks(self, state):
        for i in range(self.lstLayers.count()):
            self.lstLayers.item(i).setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)

    def get_selected_layers(self):
        selected = []
        for i in range(self.lstLayers.count()):
            item = self.lstLayers.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                lid = item.data(Qt.ItemDataRole.UserRole)
                layer = QgsProject.instance().mapLayer(lid)
                if layer:
                    selected.append(layer)
        return selected

    def apply_styling(self):
        source_layers = self.get_selected_layers()
        dem_layer = self.cmbDemLayer.currentLayer()

        # Exclude this tool's own previous outputs from the source set: they are
        # aggregated products, not DXF sources, and (critically) the up-front
        # teardown below deletes them — iterating a deleted layer in
        # aggregate_features would crash the run (e.g. after "Select All").
        try:
            source_layers = [
                sl for sl in source_layers
                if str((get_archtoolkit_layer_metadata(sl) or {}).get("tool_id") or "") != "map_styling"
            ]
        except Exception as _exc:
            log_swallowed("tools/map_styling_dialog.py:297 (apply_styling)", _exc)

        if not source_layers and not (self.chkDemStyling.isChecked() and dem_layer):
            push_message(self.iface, "오류", "시각화를 적용할 레이어를 선택해주세요.", level=2)
            restore_ui_focus(self)
            return


        try:
            self._style_run_id = new_run_id("map_styling")
            results = []
            notes = []
            
            # 1. Raster Background Styling
            if self.chkDemStyling.isChecked() and isinstance(dem_layer, QgsRasterLayer):
                self.style_dem_background(dem_layer)
                results.append("배경 지형")

            # 2. Vector Styling
            if source_layers:
                tasks = []
                roads_cfg = self.code_config.get("roads", {})
                rivers_cfg = self.code_config.get("rivers", {})
                buildings_cfg = self.code_config.get("buildings", {})
                if self.chkRoads.isChecked():
                    tasks.append({
                        'name': roads_cfg.get("name", "Style: 도로"),
                        'codes': [r.get("code") for r in roads_cfg.get("rules", []) if isinstance(r, dict) and r.get("code")],
                        'dest_geom': "line",
                        'style_func': self.style_road_layer,
                    })
                if self.chkRivers.isChecked():
                    tasks.append({
                        'name': rivers_cfg.get("name", "Style: 하천"),
                        'codes': [r.get("code") for r in rivers_cfg.get("rules", []) if isinstance(r, dict) and r.get("code")],
                        'dest_geom': "line",
                        'style_func': self.style_river_layer,
                    })
                if self.chkBuildings.isChecked():
                    tasks.append({
                        'name': buildings_cfg.get("name", "Style: 건물"),
                        'codes': buildings_cfg.get("codes", []) if isinstance(buildings_cfg.get("codes"), list) else [],
                        'dest_geom': "polygon",
                        'style_func': self.style_building_layer,
                    })

                # 2.1 Build the new group under a temporary name FIRST, and only
                # tear down the previous run's group after we know this run
                # actually produced something — otherwise a no-match run would
                # destroy the existing outputs before creating any replacement.
                vector_group_name = "Style: 도면 데이터"
                root = QgsProject.instance().layerTreeRoot()
                tmp_group_name = f"Style: 도면 데이터 (작업중 {self._style_run_id})"
                vec_group = root.insertGroup(0, tmp_group_name)

                created_any = False
                for task in tasks:
                    aggregated_layer = self.aggregate_features(source_layers, task.get('codes', []), task['name'], task.get("dest_geom", "line"))
                    if aggregated_layer:
                        # Add directly to group (layer was added with addMapLayer(False))
                        layer_node = QgsLayerTreeLayer(aggregated_layer)
                        vec_group.insertChildNode(0, layer_node)  # Insert at top

                        # Apply style
                        task['style_func'](aggregated_layer, 'Layer')
                        results.append(task['name'].replace("Style: ", ""))
                        created_any = True
                    if task.get("dest_geom") == "polygon":
                        bs = getattr(self, "_last_building_stats", None) or {}
                        if bs.get("points_skipped"):
                            notes.append(f"건물 코드의 점/주기 피처 {bs['points_skipped']}개는 건물이 아니어서 제외")
                        if bs.get("degenerate_skipped"):
                            notes.append(f"면을 만들 수 없는 건물 선 {bs['degenerate_skipped']}개 제외")

                if created_any:
                    # Now it's safe to retire the previous run's group.
                    old_group = root.findGroup(vector_group_name)
                    if old_group:
                        self._teardown_style_group(old_group, root)
                    try:
                        vec_group.setName(vector_group_name)
                    except Exception as _exc:
                        log_swallowed("tools/map_styling_dialog.py:372 (apply_styling)", _exc)

                    # 3. Move source layers into a hidden sub-group.
                    source_group_name = "원본 레이어 (숨김)"
                    source_sub_group = vec_group.addGroup(source_group_name)

                    for sl in source_layers:
                        sl_node = root.findLayer(sl.id())
                        if sl_node:
                            new_node = QgsLayerTreeLayer(sl)
                            source_sub_group.addChildNode(new_node)
                            parent = sl_node.parent()
                            if parent:
                                parent.removeChildNode(sl_node)

                    source_sub_group.setItemVisibilityChecked(False)

                    # The hidden sources still hold every feature this run did
                    # not style (unmapped codes, unchecked categories, layers
                    # without a code field). Say so instead of letting them
                    # vanish from the map silently.
                    styled_codes = [c for t in tasks for c in (t.get('codes') or [])]
                    unstyled = self._unstyled_feature_counts(source_layers, styled_codes)
                    if unstyled:
                        n_unstyled = sum(unstyled.values())
                        top = sorted(unstyled.items(), key=lambda kv: -kv[1])
                        listing = ", ".join(f"{k or '(빈 코드)'}: {v}" for k, v in top[:20])
                        log_message(
                            f"MapStyling: 스타일되지 않은 원본 피처 {n_unstyled}개 ({len(unstyled)}개 코드) - {listing}",
                            level=Qgis.MessageLevel.Info,
                        )
                        notes.append(
                            f"스타일 대상이 아닌 원본 피처 {n_unstyled}개({len(unstyled)}개 코드)는 "
                            f"'{source_group_name}' 그룹에 숨겨져 있습니다(목록은 로그)"
                        )
                else:
                    # Nothing created: drop the temp group; leave old outputs intact.
                    try:
                        root.removeChildNode(vec_group)
                    except Exception as _exc:
                        log_swallowed("map_styling_dialog.apply_styling", _exc)

            # Final message
            if results:
                msg = f"통합 레이어가 생성되었습니다: {', '.join(results)}"
                if notes:
                    msg += " | " + " | ".join(notes)
                push_message(self.iface, "시각화 완료", msg, level=0, duration=10 if notes else 3)
                self.accept()
            else:
                push_message(self.iface, "정보", "선택한 레이어들에서 해당하는 데이터를 찾을 수 없습니다.", level=1)
                restore_ui_focus(self)
                
        except Exception as e:
            push_message(self.iface, "오류", f"스타일 적용 중 오류: {str(e)}", level=2)
            restore_ui_focus(self)


    def _teardown_style_group(self, group, root):
        """Safely dismantle a previous run's style group:

        1. Source layers hidden inside "원본 레이어 (숨김)" get a fresh node at
           the root (otherwise their ONLY tree node dies with the group and the
           layer vanishes from the panel until QGIS restarts).
        2. Plugin-created layers (tagged tool_id="map_styling") are deregistered
           from the project so they don't accumulate as orphans.
        """
        project = QgsProject.instance()
        try:
            hidden = group.findGroup("원본 레이어 (숨김)")
            if hidden is not None:
                for node in list(hidden.findLayers()):
                    lyr = node.layer()
                    if lyr is not None:
                        root.insertChildNode(0, QgsLayerTreeLayer(lyr))
        except Exception as _exc:
            log_swallowed("map_styling_dialog._teardown_style_group", _exc)
        try:
            for node in list(group.findLayers()):
                lyr = node.layer()
                if lyr is None:
                    continue
                _skip_433 = False
                try:
                    meta = get_archtoolkit_layer_metadata(lyr) or {}
                    if str(meta.get("tool_id") or "") == "map_styling":
                        project.removeMapLayer(lyr.id())
                except Exception as _exc:
                    log_swallowed("map_styling_dialog._teardown_style_group", _exc)
                    log_swallowed("tools/map_styling_dialog.py:437 (_teardown_style_group)", _exc)
                    _skip_433 = True
                if _skip_433:
                    continue
        except Exception as _exc:
            log_swallowed("map_styling_dialog._teardown_style_group", _exc)
        try:
            root.removeChildNode(group)
        except Exception as _exc:
            log_swallowed("map_styling_dialog._teardown_style_group", _exc)

    @staticmethod
    def _dem_min_max(raster_layer):
        """Exact band-1 min/max over all valid cells (NoData excluded)."""
        stats = raster_layer.dataProvider().bandStatistics(1, RBS_ALL)
        mn = float(stats.minimumValue)
        mx = float(stats.maximumValue)
        if not (math.isfinite(mn) and math.isfinite(mx)):
            mn, mx = 0.0, 1.0
        if mx <= mn:
            mx = mn + 1.0
        return mn, mx

    @staticmethod
    def _gray_renderer(provider, dem_min, dem_max):
        """Grey renderer stretched to the DEM's min/max.

        Without a contrast enhancement QGIS writes the raw elevation as the grey
        level, so anything above 255 wraps (a hard black edge at 256 m) and the
        tone follows absolute height instead of the DEM's own range.
        """
        renderer = QgsSingleBandGrayRenderer(provider, 1)
        ce = QgsContrastEnhancement(provider.dataType(1))
        ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.ContrastEnhancementAlgorithm.StretchToMinimumMaximum)
        ce.setMinimumValue(float(dem_min))
        ce.setMaximumValue(float(dem_max))
        renderer.setContrastEnhancement(ce)
        return renderer

    @staticmethod
    def _color_renderer(provider, dem_min, dem_max):
        """Discrete 5-item colour ramp (quartiles); legend labels carry the class values."""
        breaks = [dem_min + (dem_max - dem_min) * f for f in (0.0, 0.25, 0.5, 0.75)] + [dem_max]
        nd = 1 if (dem_max - dem_min) >= 10 else 2

        def _fmt(v):
            return f"{v:.{nd}f}"

        labels = [f"<= {_fmt(breaks[0])}"] + [f"{_fmt(breaks[i - 1])} - {_fmt(breaks[i])}" for i in range(1, 5)]
        colors = ["#ffffcc", "#c2e699", "#78c679", "#31a354", "#006837"]
        shader = QgsRasterShader()
        color_ramp = QgsColorRampShader(breaks[0], breaks[-1])
        color_ramp.setColorRampType(SHADER_DISCRETE)
        color_ramp.setColorRampItemList(
            [QgsColorRampShader.ColorRampItem(v, QColor(c), lbl) for v, c, lbl in zip(breaks, colors, labels)]
        )
        shader.setRasterShaderFunction(color_ramp)
        return QgsSingleBandPseudoColorRenderer(provider, 1, shader), breaks

    def style_dem_background(self, source_raster):
        """Create a 3-layer styled background group from a single DEM"""
        run_id = str(getattr(self, "_style_run_id", "") or "").strip() or new_run_id("map_styling")
        
        group_name = f"Style: 배경 지형 ({source_raster.name()})"
        root = QgsProject.instance().layerTreeRoot()

        # Remove existing group if it exists (deregistering the plugin-created
        # clone layers, so re-runs don't accumulate orphans)
        existing_group = root.findGroup(group_name)
        if existing_group:
            self._teardown_style_group(existing_group, root)
        
        group = root.addGroup(group_name)

        # Full-band statistics (NoData excluded) drive BOTH the grey stretch and
        # the colour classes.
        dem_min, dem_max = self._dem_min_max(source_raster)

        # We want: Color (Top), Gray (Mid), Hillshade (Bottom)
        # Strategy: Add all with addLayer (appends at bottom), then reorder manually.
        # Or: Add in reverse order. Let's add in reverse order so last added is at top.
        
        # 1. Hillshade (should be at bottom, add first)
        hillshade_layer = source_raster.clone()
        hillshade_layer.setName(f"{source_raster.name()}_음영기복")
        hillshade_layer.setRenderer(QgsHillshadeRenderer(hillshade_layer.dataProvider(), 1, 315, 45))
        try:
            set_archtoolkit_layer_metadata(
                hillshade_layer,
                tool_id="map_styling",
                run_id=run_id,
                kind="dem_hillshade",
                units="m",
                params={"source": str(source_raster.name() or "")},
            )
        except Exception as _exc:
            log_swallowed("map_styling_dialog.style_dem_background", _exc)
        QgsProject.instance().addMapLayer(hillshade_layer, False)
        group.addLayer(hillshade_layer) 
        
        # 2. Gray Layer (should be in middle, add second - will be on top of hillshade)
        gray_layer = source_raster.clone()
        gray_layer.setName(f"{source_raster.name()}_그레이")
        gray_layer.setRenderer(self._gray_renderer(gray_layer.dataProvider(), dem_min, dem_max))
        gray_layer.setOpacity(0.4)
        gray_layer.setBlendMode(QPainter.CompositionMode.CompositionMode_Multiply)
        try:
            set_archtoolkit_layer_metadata(
                gray_layer,
                tool_id="map_styling",
                run_id=run_id,
                kind="dem_gray",
                units="m",
                params={
                    "source": str(source_raster.name() or ""),
                    "contrast": "stretch_to_min_max",
                    "stretch_min": float(dem_min),
                    "stretch_max": float(dem_max),
                },
            )
        except Exception as _exc:
            log_swallowed("map_styling_dialog.style_dem_background", _exc)
        QgsProject.instance().addMapLayer(gray_layer, False)
        gray_node = QgsLayerTreeLayer(gray_layer)
        group.insertChildNode(0, gray_node) # Insert at top of group
        
        # 3. Color Layer (should be at top, add last)
        color_layer = source_raster.clone()
        color_layer.setName(f"{source_raster.name()}_고도색상")

        color_renderer, breaks = self._color_renderer(color_layer.dataProvider(), dem_min, dem_max)
        color_layer.setRenderer(color_renderer)
        color_layer.setOpacity(0.7)
        try:
            set_archtoolkit_layer_metadata(
                color_layer,
                tool_id="map_styling",
                run_id=run_id,
                kind="dem_color",
                units="m",
                params={"source": str(source_raster.name() or ""), "class_breaks": [float(v) for v in breaks]},
            )
        except Exception as _exc:
            log_swallowed("map_styling_dialog.style_dem_background", _exc)
        QgsProject.instance().addMapLayer(color_layer, False)
        color_node = QgsLayerTreeLayer(color_layer)
        group.insertChildNode(0, color_node) # Insert at very top of group


    def detect_code_field(self, layer):
        """Identify which field contains the layer codes"""
        possible_names = ['Layer', 'layer', 'RefName', 'LayerName', 'LAYER']
        fields = [f.name() for f in layer.fields()]
        for name in possible_names:
            if name in fields:
                return name
        return None

    @staticmethod
    def _metres_to_layer_units(metres, crs):
        """metres expressed in the CRS's map units; None for geographic/unknown units."""
        try:
            if crs is None or not crs.isValid() or crs.isGeographic():
                return None
            unit = crs.mapUnits()
            if unit == Qgis.DistanceUnit.Unknown:
                return None
            factor = float(QgsUnitTypes.fromUnitToUnitFactor(Qgis.DistanceUnit.Meters, unit))
        except Exception as _exc:
            log_swallowed("map_styling_dialog._metres_to_layer_units", _exc)
            return None
        if not math.isfinite(factor) or factor <= 0:
            return None
        return float(metres) * factor

    @staticmethod
    def _polygonal_parts(geom):
        """Polygon parts of a geometry (a makeValid() result may be a collection)."""
        if geom is None or geom.isNull() or geom.isEmpty():
            return []
        if geom.type() == Qgis.GeometryType.Polygon:
            return [geom]
        out = []
        if geom.isMultipart():
            for part in geom.asGeometryCollection():
                if part.type() == Qgis.GeometryType.Polygon and not part.isEmpty():
                    out.append(part)
        return out

    def _building_polygon(self, geom, crs):
        """Turn one building feature into a (Multi)Polygon, or None.

        - points (DXF text/labels on a building layer) are not buildings: skipped;
        - polygons are kept as they are (invalid ones repaired with makeValid);
        - lines are closed PART BY PART (a multipart outline of two houses is two
          polygons, not one ring zig-zagging between them); a part that cannot
          form a ring is buffered by BUILDING_LINE_BUFFER_M metres, or skipped
          when the CRS has no metre conversion (geographic / unknown units).
        Returns (geometry or None, counters).
        """
        info = {"points_skipped": 0, "degenerate_buffered": 0, "degenerate_skipped": 0, "invalid_repaired": 0}
        if geom is None or geom.isNull() or geom.isEmpty():
            return None, info
        gtype = geom.type()
        if gtype == Qgis.GeometryType.Point:
            info["points_skipped"] = 1
            return None, info
        if gtype == Qgis.GeometryType.Polygon:
            if geom.isGeosValid():
                return QgsGeometry(geom), info
            parts = self._polygonal_parts(geom.makeValid())
            if parts:
                info["invalid_repaired"] = 1
                return QgsGeometry.collectGeometry(parts), info
            info["degenerate_skipped"] = 1
            return None, info
        if gtype != Qgis.GeometryType.Line:
            info["degenerate_skipped"] = 1
            return None, info

        lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
        buf = None
        buf_checked = False
        polys = []
        for line in lines:
            pts = [QgsPointXY(p) for p in line]
            distinct = {(round(p.x(), 9), round(p.y(), 9)) for p in pts}
            part_polys = []
            if len(distinct) >= 3:
                cand = QgsGeometry.fromPolygonXY([pts])
                if cand.isGeosValid() and cand.area() > 0:
                    part_polys = [cand]
                else:
                    part_polys = [pp for pp in self._polygonal_parts(cand.makeValid()) if pp.area() > 0]
                    if part_polys:
                        info["invalid_repaired"] += 1
            if not part_polys:
                if not buf_checked:
                    buf = self._metres_to_layer_units(BUILDING_LINE_BUFFER_M, crs)
                    buf_checked = True
                if buf and len(distinct) >= 2:
                    buffered = QgsGeometry.fromPolylineXY(pts).buffer(buf, 2)
                    if buffered is not None and not buffered.isEmpty():
                        part_polys = [buffered]
                        info["degenerate_buffered"] += 1
                if not part_polys:
                    info["degenerate_skipped"] += 1
            polys.extend(part_polys)
        if not polys:
            return None, info
        return QgsGeometry.collectGeometry(polys), info

    def aggregate_features(self, source_layers, codes, name, dest_geom="line"):
        """Combine matching features from multiple layers into one memory layer"""
        run_id = str(getattr(self, "_style_run_id", "") or "").strip() or new_run_id("map_styling")
        if not codes:
            return None
        is_building = dest_geom == "polygon"
        dest_crs = source_layers[0].crs()

        dest_geom_type = "MultiPolygon" if is_building else "LineString"
        # setCrs rather than "?crs=<authid>": a custom CRS (no authid) would
        # otherwise leave the output without any CRS.
        dest_layer = QgsVectorLayer(dest_geom_type, name, "memory")
        dest_layer.setCrs(dest_crs)
        pr = dest_layer.dataProvider()
        pr.addAttributes([QgsField("Layer", FT_STRING)])
        dest_layer.updateFields()

        all_features = []
        building_stats = {"points_skipped": 0, "degenerate_buffered": 0, "degenerate_skipped": 0, "invalid_repaired": 0}

        for sl in source_layers:
            field_name = self.detect_code_field(sl)
            if not field_name: continue

            # The destination layer uses source_layers[0]'s CRS; any other
            # layer's raw coordinates would land in the wrong place. Reproject.
            layer_ct = None
            try:
                if sl.crs() != dest_crs:
                    layer_ct = QgsCoordinateTransform(
                        sl.crs(), dest_crs, QgsProject.instance()
                    )
            except Exception:
                layer_ct = None

            quoted_codes = ", ".join(["'{}'".format(c) for c in codes])
            query = '"{}" IN ({})'.format(field_name, quoted_codes)
            request = QgsFeatureRequest().setFilterExpression(query)

            for feat in sl.getFeatures(request):
                new_feat = QgsFeature(dest_layer.fields())
                code_val = feat.attribute(field_name)
                new_feat.setAttributes([code_val])

                geom = feat.geometry()
                if layer_ct is not None:
                    _skip_592 = False
                    try:
                        geom = QgsGeometry(geom)
                        geom.transform(layer_ct)
                    except Exception as _exc:
                        log_swallowed("map_styling_dialog.aggregate_features", _exc)
                        log_swallowed("tools/map_styling_dialog.py:595 (aggregate_features)", _exc)
                        _skip_592 = True
                    if _skip_592:
                        continue
                if is_building:
                    poly_geom, info = self._building_polygon(geom, dest_crs)
                    for k, v in info.items():
                        building_stats[k] += v
                    if poly_geom is None:
                        continue
                    new_feat.setGeometry(poly_geom)
                else:
                    new_feat.setGeometry(geom)

                all_features.append(new_feat)

        if is_building:
            self._last_building_stats = dict(building_stats)

        if not all_features:
            return None

        pr.addFeatures(all_features)
        params = {"name": str(name or ""), "dest_geom": str(dest_geom or "")}
        if is_building:
            params.update(building_stats)
            params["degenerate_buffer_m"] = BUILDING_LINE_BUFFER_M
        try:
            set_archtoolkit_layer_metadata(
                dest_layer,
                tool_id="map_styling",
                run_id=run_id,
                kind="styled_vector",
                units="",
                params=params,
            )
        except Exception as _exc:
            log_swallowed("map_styling_dialog.aggregate_features", _exc)
        QgsProject.instance().addMapLayer(dest_layer, False)  # Add to project but NOT to layer tree
        return dest_layer

    def _unstyled_feature_counts(self, source_layers, styled_codes):
        """{code: count} of source features this run did NOT style (they get hidden with the sources)."""
        styled = {str(c) for c in styled_codes}
        counts = {}
        for sl in source_layers:
            field_name = self.detect_code_field(sl)
            try:
                if field_name:
                    req = QgsFeatureRequest().setSubsetOfAttributes([field_name], sl.fields())
                    for ft in sl.getFeatures(req):
                        v = ft.attribute(field_name)
                        code = "" if is_null_value(v) else str(v)
                        if code not in styled:
                            counts[code] = counts.get(code, 0) + 1
                else:
                    key = f"({sl.name()}: 코드 필드 없음)"
                    counts[key] = counts.get(key, 0) + int(sl.featureCount())
            except Exception as _exc:
                log_swallowed("map_styling_dialog._unstyled_feature_counts", _exc)
        return counts

    def style_road_layer(self, layer, field_name):
        cfg = self.code_config.get("roads", {})
        color = QColor(cfg.get("color", "#ff9501"))
        road_rules = cfg.get("rules", [])
        
        # Create invisible root rule (ELSE filter catches nothing)
        root_rule = QgsRuleBasedRenderer.Rule(None)  # No symbol for root
        
        for item in road_rules:
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            width = item.get("width_mm", item.get("width"))
            label = item.get("label", "")
            if not (isinstance(code, str) and code):
                continue
            _skip_665 = False
            try:
                width_f = float(width)
            except Exception as _exc:
                log_swallowed("map_styling_dialog.style_road_layer", _exc)
                log_swallowed("tools/map_styling_dialog.py:667 (style_road_layer)", _exc)
                _skip_665 = True
            if _skip_665:
                continue
            sym = QgsLineSymbol.createSimple({'color': color.name(), 'width': str(width_f)})
            rule = QgsRuleBasedRenderer.Rule(sym, 0, 0, f"\"{field_name}\" = '{code}'", str(label))
            root_rule.appendChild(rule)
            
        layer.setRenderer(QgsRuleBasedRenderer(root_rule))
        layer.triggerRepaint()

    def style_river_layer(self, layer, field_name):
        cfg = self.code_config.get("rivers", {})
        color = QColor(cfg.get("color", "#1ea1ff"))
        river_rules = cfg.get("rules", [])
        
        # Create invisible root rule (ELSE filter catches nothing)
        root_rule = QgsRuleBasedRenderer.Rule(None)  # No symbol for root
        
        for item in river_rules:
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            width = item.get("width_mm", item.get("width"))
            label = item.get("label", "")
            if not (isinstance(code, str) and code):
                continue
            _skip_693 = False
            try:
                width_f = float(width)
            except Exception as _exc:
                log_swallowed("map_styling_dialog.style_river_layer", _exc)
                log_swallowed("tools/map_styling_dialog.py:695 (style_river_layer)", _exc)
                _skip_693 = True
            if _skip_693:
                continue
            sym = QgsLineSymbol.createSimple({'color': color.name(), 'width': str(width_f)})
            rule = QgsRuleBasedRenderer.Rule(sym, 0, 0, f"\"{field_name}\" = '{code}'", str(label))
            root_rule.appendChild(rule)
            
        layer.setRenderer(QgsRuleBasedRenderer(root_rule))
        layer.triggerRepaint()

    def style_building_layer(self, layer, field_name):
        offset_val = self.spinOffset.value()
        cfg = self.code_config.get("buildings", {})
        fill_color = cfg.get("fill_color", "#ffffff")
        outline_color = cfg.get("outline_color", "#666666")
        outline_width = cfg.get("outline_width_mm", 0.1)
        try:
            shadow_alpha = int(cfg.get("shadow_alpha", 100))
        except Exception:
            shadow_alpha = 100
        shadow_alpha = max(0, min(255, shadow_alpha))
        
        if layer.geometryType() == Qgis.GeometryType.Polygon:
            symbol = QgsFillSymbol.createSimple({
                'color': str(fill_color),
                'outline_color': str(outline_color),
                'outline_width': str(outline_width),
            })
            shadow_layer = QgsSimpleFillSymbolLayer()
            shadow_layer.setFillColor(QColor(0, 0, 0, shadow_alpha))
            shadow_layer.setStrokeColor(Qt.GlobalColor.transparent)
            shadow_layer.setOffset(QPointF(offset_val, offset_val))
            shadow_layer.setOffsetUnit(Qgis.RenderUnit.Millimeters)
            symbol.insertSymbolLayer(0, shadow_layer)
        else:
            symbol = QgsLineSymbol.createSimple({'color': '#ffffff', 'width': '0.3'})
            shadow_layer = QgsSimpleLineSymbolLayer()
            shadow_layer.setColor(QColor(0, 0, 0, shadow_alpha))
            shadow_layer.setWidth(0.3)
            shadow_layer.setOffset(offset_val) 
            symbol.insertSymbolLayer(0, shadow_layer)

        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.triggerRepaint()

    @staticmethod
    def _save_named_style(layer, path):
        try:
            # saveNamedStyle returns (message: str, success: bool) — testing
            # res[0] tested the MESSAGE (non-empty exactly on failure).
            res = layer.saveNamedStyle(path)
            if isinstance(res, (tuple, list)) and len(res) >= 2:
                return bool(res[1])
            return bool(res)
        except Exception:
            return False

    def export_qml_preset(self):
        """Export QML styles + current mapping config for reuse."""
        base_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "프리셋 저장 폴더 선택")
        if not base_dir:
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        preset_dir = os.path.join(base_dir, f"ArchToolkit_MapStyling_Preset_{ts}")
        try:
            os.makedirs(preset_dir, exist_ok=False)
        except Exception:
            preset_dir = base_dir

        project_crs = QgsProject.instance().crs()
        exported = []

        def _template(geom_type, layer_name):
            # setCrs keeps a custom project CRS (no authid) instead of dropping it.
            lyr = QgsVectorLayer(geom_type, layer_name, "memory")
            if project_crs.isValid():
                lyr.setCrs(project_crs)
            lyr.dataProvider().addAttributes([QgsField("Layer", FT_STRING)])
            lyr.updateFields()
            return lyr

        # Vector styles (templates)
        try:
            roads_layer = _template("LineString", "roads_style_template")
            self.style_road_layer(roads_layer, "Layer")
            if self._save_named_style(roads_layer, os.path.join(preset_dir, "roads.qml")):
                exported.append("roads.qml")
        except Exception as _exc:
            log_swallowed("map_styling_dialog.export_qml_preset", _exc)

        try:
            rivers_layer = _template("LineString", "rivers_style_template")
            self.style_river_layer(rivers_layer, "Layer")
            if self._save_named_style(rivers_layer, os.path.join(preset_dir, "rivers.qml")):
                exported.append("rivers.qml")
        except Exception as _exc:
            log_swallowed("map_styling_dialog.export_qml_preset", _exc)

        try:
            buildings_layer = _template("MultiPolygon", "buildings_style_template")
            self.style_building_layer(buildings_layer, "Layer")
            if self._save_named_style(buildings_layer, os.path.join(preset_dir, "buildings.qml")):
                exported.append("buildings.qml")
        except Exception as _exc:
            log_swallowed("map_styling_dialog.export_qml_preset", _exc)

        # DEM styles (export only when DEM styling is enabled and a DEM is selected)
        dem_layer = self.cmbDemLayer.currentLayer()
        if self.chkDemStyling.isChecked() and isinstance(dem_layer, QgsRasterLayer):
            try:
                hillshade_layer = dem_layer.clone()
                hillshade_layer.setRenderer(QgsHillshadeRenderer(hillshade_layer.dataProvider(), 1, 315, 45))
                if self._save_named_style(hillshade_layer, os.path.join(preset_dir, "dem_hillshade.qml")):
                    exported.append("dem_hillshade.qml")
            except Exception as _exc:
                log_swallowed("tools/map_styling_dialog.py:807 (export_qml_preset)", _exc)

            try:
                dem_min, dem_max = self._dem_min_max(dem_layer)
            except Exception as _exc:
                log_swallowed("map_styling_dialog.export_qml_preset (stats)", _exc)
                dem_min, dem_max = 0.0, 1.0

            try:
                gray_layer = dem_layer.clone()
                gray_layer.setRenderer(self._gray_renderer(gray_layer.dataProvider(), dem_min, dem_max))
                gray_layer.setOpacity(0.4)
                gray_layer.setBlendMode(QPainter.CompositionMode.CompositionMode_Multiply)
                if self._save_named_style(gray_layer, os.path.join(preset_dir, "dem_gray.qml")):
                    exported.append("dem_gray.qml")
            except Exception as _exc:
                log_swallowed("map_styling_dialog.export_qml_preset", _exc)

            try:
                color_layer = dem_layer.clone()
                color_renderer, _breaks = self._color_renderer(color_layer.dataProvider(), dem_min, dem_max)
                color_layer.setRenderer(color_renderer)
                color_layer.setOpacity(0.7)
                if self._save_named_style(color_layer, os.path.join(preset_dir, "dem_color.qml")):
                    exported.append("dem_color.qml")
            except Exception as _exc:
                log_swallowed("map_styling_dialog.export_qml_preset", _exc)

        # Mapping config snapshot
        try:
            with open(os.path.join(preset_dir, "map_styling_codes.json"), "w", encoding="utf-8") as f:
                json.dump(self.code_config, f, ensure_ascii=False, indent=2)
            exported.append("map_styling_codes.json")
        except Exception as _exc:
            log_swallowed("map_styling_dialog.export_qml_preset", _exc)

        # Minimal manifest
        try:
            manifest = {
                "schema": 1,
                "tool": "ArchToolkit Map Styling",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "exported_files": exported,
                "options": {
                    "roads": bool(self.chkRoads.isChecked()),
                    "rivers": bool(self.chkRivers.isChecked()),
                    "buildings": bool(self.chkBuildings.isChecked()),
                    "dem_styling": bool(self.chkDemStyling.isChecked()),
                    "building_shadow_offset_mm": float(self.spinOffset.value()),
                },
            }
            with open(os.path.join(preset_dir, "preset_manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            exported.append("preset_manifest.json")
        except Exception as _exc:
            log_swallowed("map_styling_dialog.export_qml_preset", _exc)

        push_message(self.iface, "완료", f"프리셋을 저장했습니다: {preset_dir}", level=0)


