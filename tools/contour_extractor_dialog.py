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
import os
import tempfile
import uuid
from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsVectorLayer, QgsMapLayerProxyModel
import processing
from .config import get_contour_code_presets, get_contour_filter_field_candidates
from .utils import push_message, set_archtoolkit_layer_metadata
from .live_log_dialog import ensure_live_log_dialog
from .help_dialog import show_help_dialog
from .ui_helpers import create_hint_label, insert_help_button, set_plugin_window_icon

# Load the UI file
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'contour_extractor_dialog_base.ui'))


class ContourExtractorDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, iface, parent=None):
        super(ContourExtractorDialog, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface
        self._contour_checkboxes = [self.chkContour1, self.chkContour2, self.chkContour3, self.chkContour4]
        self._contour_presets = list(get_contour_code_presets())
        self._contour_field_candidates = list(get_contour_filter_field_candidates() or ["Layer"])
        
        # Store original filters for undo
        self.original_filters = {}

        set_plugin_window_icon(self, ("contour_icon.png", "icon.png"))
        self._apply_contour_presets()
        self._inject_mode_hints()
        
        # Setup layer filters for DEM mode
        self.cmbDemLayer.setFilters(QgsMapLayerProxyModel.RasterLayer)
        
        # Connect signals
        self.radioDxf.toggled.connect(self.on_mode_changed)
        self.btnRun.clicked.connect(self.run_process)
        self.btnClose.clicked.connect(self.reject)
        self.btnRefreshLayers.clicked.connect(self.refresh_layer_list)
        self.btnResetFilter.clicked.connect(self.reset_filters)
        
        # Initial state
        self.on_mode_changed()
        self.refresh_layer_list()
        self._setup_help_button()

    def _setup_help_button(self):
        try:
            self.btnHelp = insert_help_button(
                dialog=self,
                callback=self._on_help,
                close_button=self.btnClose,
                text="도움말",
            )
        except Exception:
            pass

    def _apply_contour_presets(self):
        presets = list(self._contour_presets or [])
        for idx, checkbox in enumerate(self._contour_checkboxes):
            if idx < len(presets):
                preset = presets[idx]
                checkbox.setVisible(True)
                checkbox.setText(str(preset.get("label") or preset.get("code") or "등고선"))
                checkbox.setChecked(bool(preset.get("default_checked", True)))
                checkbox.setProperty("contour_code", str(preset.get("code") or ""))
                checkbox.setToolTip(f"DXF 코드: {str(preset.get('code') or '')}")
            else:
                checkbox.setVisible(False)
                checkbox.setChecked(False)
                checkbox.setProperty("contour_code", "")

    def _inject_mode_hints(self):
        try:
            dxf_layout = self.groupDxf.layout()
            if dxf_layout is not None:
                dxf_hint = create_hint_label(
                    "DXF 모드에서는 `Layer/LAYER/layer` 필드를 자동으로 찾아 체크한 등고선 유형만 필터링합니다.",
                    tone="info",
                    parent=self.groupDxf,
                )
                if hasattr(dxf_layout, "insertWidget"):
                    dxf_layout.insertWidget(0, dxf_hint)
                else:
                    dxf_layout.addWidget(dxf_hint)
        except Exception:
            pass
        try:
            dem_layout = self.groupDem.layout()
            if dem_layout is not None:
                dem_hint = create_hint_label(
                    "DEM 모드에서는 간격(m)만 정하면 새 등고선 레이어를 만들어 프로젝트에 바로 추가합니다.",
                    tone="tip",
                    parent=self.groupDem,
                )
                if hasattr(dem_layout, "insertWidget"):
                    dem_layout.insertWidget(0, dem_hint)
                else:
                    dem_layout.addWidget(dem_hint)
        except Exception:
            pass

    def _on_help(self):
        try:
            html = (
                "<h2>등고선 추출 (Extract Contours)</h2>"
                "<p>DXF 레이어에서 등고선(코드)만 필터링하거나, DEM 래스터에서 등고선을 생성합니다.</p>"
                "<h3>모드</h3>"
                "<ul>"
                "<li><b>DXF 필터</b>: 선택한 DXF 레이어에 subsetString 필터를 적용합니다. "
                "필드명은 <code>Layer/LAYER/layer</code>를 자동으로 찾아보고, 필요하면 <b>필터 초기화</b>로 되돌릴 수 있습니다.</li>"
                "<li><b>DEM에서 생성</b>: GDAL <code>gdal:contour</code>로 등고선 벡터를 생성합니다.</li>"
                "</ul>"
                "<h3>팁</h3>"
                "<ul>"
                "<li>체크박스 라벨과 DXF 코드는 설정 파일에서 바꿀 수 있어, 기관별 코드 체계에도 맞추기 쉽습니다.</li>"
                "<li>DEM 모드의 등고선 간격은 DEM의 높이 단위(보통 m)를 기준으로 합니다.</li>"
                "<li>출처/레퍼런스는 <code>REFERENCES.md</code>를 참고하세요.</li>"
                "</ul>"
            )
            show_help_dialog(parent=self, title="등고선 추출 도움말", html=html)
        except Exception:
            try:
                QtWidgets.QMessageBox.information(self, "도움말", "README.md를 참고하세요.")
            except Exception:
                pass
    
    def refresh_layer_list(self):
        """Populate the vector layer list"""
        self.listDxfLayers.clear()
        
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                item = QtWidgets.QListWidgetItem(layer.name())
                item.setData(Qt.UserRole, layer.id())
                self.listDxfLayers.addItem(item)
    
    def on_mode_changed(self):
        """Toggle visibility of mode panels"""
        is_dxf = self.radioDxf.isChecked()
        self.groupDxf.setEnabled(is_dxf)
        self.groupDem.setEnabled(not is_dxf)
    
    def get_selected_contour_codes(self):
        """Get list of selected contour codes"""
        codes = []
        for checkbox in self._contour_checkboxes:
            try:
                if checkbox.isVisible() and checkbox.isChecked():
                    code = str(checkbox.property("contour_code") or "").strip()
                    if code:
                        codes.append(code)
            except Exception:
                continue
        return codes

    def _find_filter_field_name(self, layer: QgsVectorLayer):
        try:
            field_names = {str(field.name() or "").strip().lower(): str(field.name() or "").strip() for field in layer.fields()}
        except Exception:
            field_names = {}
        for candidate in self._contour_field_candidates:
            key = str(candidate or "").strip().lower()
            if key and key in field_names:
                return field_names[key]
        return None
    
    def get_selected_layers(self):
        """Get list of selected vector layers"""
        layers = []
        for item in self.listDxfLayers.selectedItems():
            layer_id = item.data(Qt.UserRole)
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer:
                layers.append(layer)
        return layers
    
    def run_process(self):
        """Run the contour extraction process"""
        # Live log window (non-modal) so users can see progress in real time.
        ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)
        if self.radioDxf.isChecked():
            self.extract_from_dxf()
        else:
            self.extract_from_dem()
    
    def extract_from_dxf(self):
        """Extract contours by filtering DXF layers (supports multiple layers)"""
        layers = self.get_selected_layers()
        if not layers:
            push_message(self.iface, "오류", "벡터 레이어를 선택해주세요", level=2)
            return
        
        codes = self.get_selected_contour_codes()
        if not codes:
            push_message(self.iface, "오류", "추출할 등고선 유형을 선택해주세요", level=2)
            return
        
        try:
            filtered_count = 0
            skipped_layers = []
            for layer in layers:
                field_name = self._find_filter_field_name(layer)
                if not field_name:
                    skipped_layers.append(layer.name())
                    continue

                query = f'"{field_name}" IN (' + ",".join([f"'{c}'" for c in codes]) + ")"

                # Store original filter for undo
                if layer.id() not in self.original_filters:
                    self.original_filters[layer.id()] = layer.subsetString()
                
                # Apply filter
                layer.setSubsetString(query)
                filtered_count += 1

            if filtered_count <= 0:
                field_preview = ", ".join(self._contour_field_candidates)
                push_message(
                    self.iface,
                    "오류",
                    f"선택한 레이어에서 등고선 코드 필드({field_preview})를 찾지 못했습니다.",
                    level=2,
                )
                return
            
            push_message(
                self.iface, "완료", 
                f"{filtered_count}개 레이어에 등고선 필터 적용 완료 ({len(codes)}개 유형)", 
                level=0
            )
            if skipped_layers:
                skipped_preview = ", ".join(skipped_layers[:3])
                if len(skipped_layers) > 3:
                    skipped_preview += " ..."
                push_message(
                    self.iface,
                    "안내",
                    f"코드 필드를 찾지 못해 건너뜬 레이어: {skipped_preview}",
                    level=1,
                )
            self.accept()
            
        except Exception as e:
            self.iface.messageBar().pushMessage("오류", f"처리 중 오류: {str(e)}", level=2)
    
    def reset_filters(self):
        """Reset filters on selected layers (undo)"""
        layers = self.get_selected_layers()
        if not layers:
            # If no selection, reset all stored filters
            reset_count = 0
            for layer_id, original_filter in self.original_filters.items():
                layer = QgsProject.instance().mapLayer(layer_id)
                if layer:
                    layer.setSubsetString(original_filter)
                    reset_count += 1
            self.original_filters.clear()
            self.iface.messageBar().pushMessage("완료", f"{reset_count}개 레이어 필터 초기화 완료", level=0)
        else:
            # Reset only selected layers
            reset_count = 0
            for layer in layers:
                if layer.id() in self.original_filters:
                    layer.setSubsetString(self.original_filters[layer.id()])
                    del self.original_filters[layer.id()]
                else:
                    layer.setSubsetString("")
                reset_count += 1
            self.iface.messageBar().pushMessage("완료", f"{reset_count}개 레이어 필터 초기화 완료", level=0)
    
    def extract_from_dem(self):
        """Generate contours from DEM raster"""
        
        layer = self.cmbDemLayer.currentLayer()
        if not layer:
            self.iface.messageBar().pushMessage("오류", "DEM 래스터를 선택해주세요", level=2)
            return
        
        interval = self.spinInterval.value()
        
        try:
            self.iface.messageBar().pushMessage("처리 중", "등고선 생성 중...", level=0)
            self.hide()
            QtWidgets.QApplication.processEvents()
            
            # Use temp file instead of memory layer
            run_id = uuid.uuid4().hex[:8]
            temp_output = os.path.join(tempfile.gettempdir(), f'archtoolkit_contour_{interval}m_{run_id}.gpkg')
            
            # Run GDAL contour
            result = processing.run("gdal:contour", {
                'INPUT': layer.source(),
                'BAND': 1,
                'INTERVAL': interval,
                'FIELD_NAME': 'ELEV',
                'CREATE_3D': False,
                'IGNORE_NODATA': True,
                'NODATA': None,
                'OUTPUT': temp_output
            })
            
            # Add result to map
            if result and os.path.exists(temp_output):
                output_layer = QgsVectorLayer(temp_output, f"등고선_{interval}m", "ogr")
                if output_layer.isValid():
                    try:
                        set_archtoolkit_layer_metadata(
                            output_layer,
                            tool_id="contour_extract",
                            run_id=str(run_id),
                            kind="contours",
                            units="m",
                            params={"interval_m": float(interval)},
                        )
                    except Exception:
                        pass
                    QgsProject.instance().addMapLayer(output_layer)
                    self.iface.messageBar().pushMessage("완료", f"등고선 생성 완료 (간격: {interval}m)", level=0)
                    self.accept()
                else:
                    self.iface.messageBar().pushMessage("오류", "등고선 레이어를 로드할 수 없습니다.", level=2)
                    self.show()
            else:
                self.iface.messageBar().pushMessage("오류", "등고선 생성에 실패했습니다.", level=2)
                self.show()
            
        except Exception as e:
            self.iface.messageBar().pushMessage("오류", f"처리 중 오류: {str(e)}", level=2)
            self.show()
