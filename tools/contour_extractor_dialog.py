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
from qgis.core import QgsProject, QgsVectorLayer, Qgis
from .utils import (
    cleanup_files,
    log_swallowed,
    push_message,
    set_archtoolkit_layer_metadata,
    stamp_layer_temp_outputs,
)
from .live_log_dialog import ensure_live_log_dialog
from .help_dialog import show_help_dialog
from .processing_task import ProcessingCancelled, run_alg_blocking
from . import dialog_memory
from .icons import icon as plugin_icon

# Load the UI file
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'contour_extractor_dialog_base.ui'))


class ContourExtractorDialog(QtWidgets.QDialog, FORM_CLASS):
    # NGII Digital Topographic Map Standard Contour Codes (현행 8자리 + 구 4자리)
    CONTOUR_CODES = {
        'F0017111': '주곡선',
        'F0017112': '계곡선',
        'F0017113': '간곡선',
        'F0017114': '조곡선',
        'F0017110': '등고선(미분류)',
        '7111': '주곡선(구)',
        '7112': '계곡선(구)',
        '7113': '간곡선(구)',
        '7114': '조곡선(구)',
    }
    
    def __init__(self, iface, parent=None):
        super(ContourExtractorDialog, self).__init__(parent)
        # Remember the last-used inputs between sessions (tools/dialog_memory.py).
        dialog_memory.attach(self, "contour_extractor")
        try:
            self.setWindowIcon(plugin_icon("contour.png"))
        except Exception as _exc:
            log_swallowed("contour_extractor_dialog.__init__ (icon)", _exc)
        self.setupUi(self)
        self.iface = iface
        
        # Store original filters for undo
        self.original_filters = {}
        
        # Setup layer filters for DEM mode
        self.cmbDemLayer.setFilters(Qgis.LayerFilter.RasterLayer)
        
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
            log_swallowed("contour_extractor_dialog._setup_help_button", _exc)

    def _on_help(self):
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            html = (
                "<h2>등고선 추출 (Extract Contours)</h2>"
                "<p>DXF 레이어에서 등고선(코드)만 필터링하거나, DEM 래스터에서 등고선을 생성합니다.</p>"
                "<h3>모드</h3>"
                "<ul>"
                "<li><b>DXF 필터</b>: 선택한 DXF 레이어에 subsetString 필터를 적용합니다. 필요하면 <b>필터 초기화</b>로 되돌릴 수 있습니다.</li>"
                "<li><b>DEM에서 생성</b>: GDAL <code>gdal:contour</code>로 등고선 벡터를 생성합니다.</li>"
                "</ul>"
                "<h3>팁</h3>"
                "<ul>"
                "<li>DEM 모드의 등고선 간격은 DEM의 높이 단위(보통 m)를 기준으로 합니다.</li>"
                "<li>출처/레퍼런스는 <code>REFERENCES.md</code>를 참고하세요.</li>"
                "</ul>"
            )
            show_help_dialog(parent=self, title="등고선 추출 도움말", html=html, plugin_dir=plugin_dir, tool_id="contour_extractor")
        except Exception:
            try:
                QtWidgets.QMessageBox.information(self, "도움말", "README.md를 참고하세요.")
            except Exception as _exc:
                log_swallowed("tools/contour_extractor_dialog.py:108 (_on_help)", _exc)
    
    def refresh_layer_list(self):
        """Populate the vector layer list"""
        self.listDxfLayers.clear()
        
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                item = QtWidgets.QListWidgetItem(layer.name())
                item.setData(Qt.ItemDataRole.UserRole, layer.id())
                self.listDxfLayers.addItem(item)
    
    def on_mode_changed(self):
        """Toggle visibility of mode panels"""
        is_dxf = self.radioDxf.isChecked()
        self.groupDxf.setEnabled(is_dxf)
        self.groupDem.setEnabled(not is_dxf)
    
    def get_selected_contour_codes(self):
        """Get list of selected contour codes (NGII modern 8-char + legacy 4-digit)."""
        codes = []
        if self.chkContour1.isChecked():
            codes.extend(['F0017111', '7111', 'F0017110', '7110'])
        if self.chkContour2.isChecked():
            codes.extend(['F0017112', '7112'])
        if self.chkContour3.isChecked():
            codes.extend(['F0017113', '7113'])
        if self.chkContour4.isChecked():
            codes.extend(['F0017114', '7114'])
        return codes
    
    def get_selected_layers(self):
        """Get list of selected vector layers"""
        layers = []
        for item in self.listDxfLayers.selectedItems():
            layer_id = item.data(Qt.ItemDataRole.UserRole)
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
            # Build query
            query = '"Layer" IN (' + ','.join([f"'{c}'" for c in codes]) + ')'
            
            filtered_count = 0
            failed_names = []
            empty_names = []
            for layer in layers:
                # Store original filter for undo. Persist it on the LAYER
                # (custom property), not this dialog instance — the dialog is
                # recreated per open and accept()s right after, so an
                # instance-only map made 필터 초기화 a guaranteed no-op.
                prop_key = "archtoolkit/contour_orig_filter"
                had_orig = layer.customProperty(prop_key, None) is not None
                if not had_orig:
                    layer.setCustomProperty(prop_key, layer.subsetString())
                orig_sub = layer.customProperty(prop_key, "")
                self.original_filters.setdefault(layer.id(), orig_sub)

                # setSubsetString returns False when the provider rejects the
                # query (e.g. the layer has no "Layer" field) — count honestly.
                if layer.setSubsetString(query):
                    if int(layer.featureCount()) > 0:
                        filtered_count += 1
                    else:
                        empty_names.append(str(layer.name()))
                        try:
                            layer.setSubsetString(orig_sub or "")
                            if not had_orig:
                                layer.removeCustomProperty(prop_key)
                                self.original_filters.pop(layer.id(), None)
                        except Exception as _exc:
                            log_swallowed("tools/contour_extractor_dialog.py (empty filter restore)", _exc)
                else:
                    failed_names.append(str(layer.name()))
                    # Restore whatever was there before and forget the entry.
                    try:
                        layer.setSubsetString(orig_sub or "")
                        if not had_orig:
                            layer.removeCustomProperty(prop_key)
                            self.original_filters.pop(layer.id(), None)
                    except Exception as _exc:
                        log_swallowed("tools/contour_extractor_dialog.py:198 (extract_from_dxf)", _exc)

            parts = []
            if filtered_count > 0:
                parts.append(f"{filtered_count}개 레이어에 등고선 필터 적용 완료")
            else:
                parts.append("선택한 등고선 코드에 해당하는 객체가 없습니다.")
            if empty_names:
                parts.append(f"일치 객체 0개(원상 복구): {', '.join(empty_names[:3])}")
            if failed_names:
                parts.append(f'적용 실패 {len(failed_names)}개: {", ".join(failed_names[:3])} ("Layer" 필드 확인 필요)')
            msg = " / ".join(parts)
            push_message(self.iface, "완료" if filtered_count else "경고", msg, level=0 if filtered_count else 1)
            if filtered_count > 0:
                self.accept()
            
        except Exception as e:
            self.iface.messageBar().pushMessage("오류", f"처리 중 오류: {str(e)}", level=2)
    
    def reset_filters(self):
        """Reset filters on selected layers (undo). Reads the original filter
        from the layer's custom property so it works even after the dialog was
        closed and reopened (a fresh instance)."""
        prop_key = "archtoolkit/contour_orig_filter"
        layers = self.get_selected_layers()
        if not layers:
            # No selection: reset every layer this tool tagged (project-wide).
            reset_count = 0
            for layer in QgsProject.instance().mapLayers().values():
                _skip_221 = False
                try:
                    orig = layer.customProperty(prop_key, None)
                    if orig is not None:
                        layer.setSubsetString(orig or "")
                        layer.removeCustomProperty(prop_key)
                        self.original_filters.pop(layer.id(), None)
                        reset_count += 1
                except Exception as _exc:
                    log_swallowed("contour_extractor_dialog.reset_filters", _exc)
                    log_swallowed("tools/contour_extractor_dialog.py:228 (reset_filters)", _exc)
                    _skip_221 = True
                if _skip_221:
                    continue
            self.iface.messageBar().pushMessage("완료", f"{reset_count}개 레이어 필터 초기화 완료", level=0)
        else:
            # Reset only selected layers — but never blank out a filter this
            # tool didn't set (the user may have their own subset applied).
            reset_count = 0
            skipped = 0
            for layer in layers:
                orig = layer.customProperty(prop_key, None)
                if orig is not None:
                    layer.setSubsetString(orig or "")
                    layer.removeCustomProperty(prop_key)
                    self.original_filters.pop(layer.id(), None)
                    reset_count += 1
                else:
                    skipped += 1
            msg = f"{reset_count}개 레이어 필터 초기화 완료"
            if skipped:
                msg += f" (이 도구가 설정하지 않은 {skipped}개 레이어는 건드리지 않음)"
            self.iface.messageBar().pushMessage("완료", msg, level=0)
    
    def extract_from_dem(self):
        """Generate contours from DEM raster"""
        
        layer = self.cmbDemLayer.currentLayer()
        if not layer:
            self.iface.messageBar().pushMessage("오류", "DEM 래스터를 선택해주세요", level=2)
            return
        
        interval = self.spinInterval.value()
        temp_output = None

        try:
            self.iface.messageBar().pushMessage("처리 중", "등고선 생성 중...", level=0)
            self.hide()
            QtWidgets.QApplication.processEvents()

            # Use temp file instead of memory layer
            run_id = uuid.uuid4().hex[:8]
            temp_output = os.path.join(tempfile.gettempdir(), f'archtoolkit_contour_{interval}m_{run_id}.gpkg')
            
            # Run GDAL contour - through the task manager so the GUI stays
            # live and Cancel aborts (processing.run froze QGIS on fine DEMs).
            # IGNORE_NODATA maps to gdal_contour's -inodata flag, which means
            # "ignore the nodata DESIGNATION and treat every value as valid" —
            # True would draw garbage contour rings around -9999/-32768 fill.
            self._run_progress = QtWidgets.QProgressDialog("등고선 추출 중…", "취소", 0, 0, self)
            self._run_progress.setWindowModality(Qt.WindowModality.WindowModal)
            self._run_progress.setAutoClose(False)
            self._run_progress.show()
            try:
                result = run_alg_blocking("gdal:contour", {
                    'INPUT': layer.source(),
                    'BAND': 1,
                    'INTERVAL': interval,
                    'FIELD_NAME': 'ELEV',
                    'CREATE_3D': False,
                    'IGNORE_NODATA': False,
                    'NODATA': None,
                    'OUTPUT': temp_output
                }, owner=self)
            finally:
                try:
                    self._run_progress.close()
                except Exception as _exc:
                    log_swallowed("contour_extractor_dialog.extract_from_dem (progress)", _exc)
                self._run_progress = None
            
            # Add result to map
            if result and os.path.exists(temp_output):
                output_layer = QgsVectorLayer(temp_output, f"등고선_{interval}m", "ogr")
                if output_layer.isValid():
                    if int(output_layer.featureCount()) <= 0:
                        output_layer = None
                        cleanup_files([temp_output])
                        self.iface.messageBar().pushMessage(
                            "경고", "생성된 등고선이 없습니다 (고도 범위와 등고선 간격을 확인하세요).", level=1
                        )
                        self.show()
                        return
                    try:
                        set_archtoolkit_layer_metadata(
                            output_layer,
                            tool_id="contour_extract",
                            run_id=str(run_id),
                            kind="contours",
                            units="m",
                            params={"interval_m": float(interval)},
                        )
                    except Exception as _exc:
                        log_swallowed("contour_extractor_dialog.extract_from_dem", _exc)
                    stamp_layer_temp_outputs(output_layer, [temp_output])
                    QgsProject.instance().addMapLayer(output_layer)
                    self.iface.messageBar().pushMessage("완료", f"등고선 생성 완료 (간격: {interval}m)", level=0)
                    self.accept()
                else:
                    cleanup_files([temp_output])
                    self.iface.messageBar().pushMessage("오류", "등고선 레이어를 로드할 수 없습니다.", level=2)
                    self.show()
            else:
                cleanup_files([temp_output])
                self.iface.messageBar().pushMessage("오류", "등고선 생성에 실패했습니다.", level=2)
                self.show()

        except ProcessingCancelled:
            cleanup_files([temp_output])
            self.iface.messageBar().pushMessage("취소", "등고선 추출이 취소되었습니다.", level=1)
            self.show()
        except Exception as e:
            cleanup_files([temp_output])
            self.iface.messageBar().pushMessage("오류", f"처리 중 오류: {str(e)}", level=2)
            self.show()
