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
Terrain Analysis Dialog for ArchToolkit
Slope, Aspect, TRI, TPI, Roughness, Slope Position with archaeological classifications
User-configurable parameters for TPI radius, TPI thresholds, and Slope Position
"""
import os
import tempfile
import uuid

try:
    import numpy as np
except Exception:  # pragma: no cover - QGIS ships NumPy; guard anyway
    np = None
try:
    from osgeo import gdal
except Exception:  # pragma: no cover
    gdal = None

from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsProject, QgsRasterLayer, QgsMapLayerProxyModel,
    QgsRasterShader, QgsColorRampShader, QgsSingleBandPseudoColorRenderer
)
import processing
from .utils import (
    cleanup_files, log_message, push_message, restore_ui_focus, set_archtoolkit_layer_metadata,
)
from .live_log_dialog import ensure_live_log_dialog
from .help_dialog import show_help_dialog

# This tool uses QGIS built-in GDAL processing algorithms. The curvature
# analysis additionally uses NumPy + GDAL (both ship with QGIS - no extra
# install), per DEVELOPMENT.md.

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'terrain_analysis_dialog_base.ui'))


class TerrainAnalysisDialog(QtWidgets.QDialog, FORM_CLASS):
    
    # Slope classifications
    SLOPE_CLASSIFICATIONS = {
        'korean': {
            'name': '한국표준',
            'classes': [
                {'max': 15, 'label': '완경사지 | 0~15° | 주거지 최적', 'color': '#1a5f1a'},
                {'max': 20, 'label': '경사지 | 15~20° | 계단식 경작', 'color': '#7ec87e'},
                {'max': 25, 'label': '급경사지 | 20~25° | 산지 산림', 'color': '#ffff00'},
                {'max': 30, 'label': '험준지 | 25~30° | 접근 곤란', 'color': '#ffa500'},
                {'max': 90, 'label': '절험지 | 30°+ | 절벽/암벽', 'color': '#ff0000'},
            ]
        },
        'tobler': {
            'name': 'Tobler 1993',
            'classes': [
                {'max': 6, 'label': '1등급 | 0~6° | 일반 보행', 'color': '#1a5f1a'},
                {'max': 12, 'label': '2등급 | 6~12° | 속도 감소', 'color': '#7ec87e'},
                {'max': 18, 'label': '3등급 | 12~18° | 이동 지체', 'color': '#ffff00'},
                {'max': 25, 'label': '4등급 | 18~25° | 한계', 'color': '#ffa500'},
                {'max': 90, 'label': '5등급 | 25°+ | 불가', 'color': '#ff0000'},
            ]
        },
        'minetti': {
            'name': 'Minetti 1995',
            'classes': [
                {'max': 3, 'label': '1등급 | 0~3° | 일상', 'color': '#20b2aa'},
                {'max': 9, 'label': '2등급 | 3~9° | 노동', 'color': '#ffff00'},
                {'max': 15, 'label': '3등급 | 9~15° | 고강도', 'color': '#ffa500'},
                {'max': 25, 'label': '4등급 | 15~25° | 임계', 'color': '#ff0000'},
                {'max': 90, 'label': '5등급 | 25°+ | 금지', 'color': '#800080'},
            ]
        },
        'llobera': {
            'name': 'Llobera 2007',
            'classes': [
                {'max': 2, 'label': '1등급 | 0~2° | 평탄', 'color': '#d3d3d3'},
                {'max': 6, 'label': '2등급 | 2~6° | 인지', 'color': '#add8e6'},
                {'max': 12, 'label': '3등급 | 6~12° | 언덕', 'color': '#00ffff'},
                {'max': 20, 'label': '4등급 | 12~20° | 장벽', 'color': '#800080'},
                {'max': 90, 'label': '5등급 | 20°+ | 수직', 'color': '#000000'},
            ]
        }
    }
    
    # Aspect 8-direction with flat area
    ASPECT_CLASSES = [
        {'max': 0, 'label': '평탄 | 0° | 평지/수면', 'color': '#808080'},
        {'max': 45, 'label': 'N-NE | 0~45° | 북~북동', 'color': '#ff0000'},
        {'max': 90, 'label': 'NE-E | 45~90° | 북동~동', 'color': '#ff7f00'},
        {'max': 135, 'label': 'E-SE | 90~135° | 동~남동', 'color': '#ffff00'},
        {'max': 180, 'label': 'SE-S | 135~180° | 남동~남', 'color': '#7fff00'},
        {'max': 225, 'label': 'S-SW | 180~225° | 남~남서', 'color': '#00ffff'},
        {'max': 270, 'label': 'SW-W | 225~270° | 남서~서', 'color': '#007fff'},
        {'max': 315, 'label': 'W-NW | 270~315° | 서~북서', 'color': '#0000ff'},
        {'max': 360, 'label': 'NW-N | 315~360° | 북서~북', 'color': '#7f00ff'},
    ]
    
    # Weiss (2001) 6-class Slope Position Classification.
    # Labels follow Weiss's own class names: classes 2/5 are Lower/Upper Slope
    # (no flatness test applies to them) — calling them "valley floor"/"upland
    # flat" previously invited wrong archaeological readings.
    SLOPE_POSITION_CLASSES = [
        {'max': 1, 'label': '1 | 깊은 곡저 (Incised Valley)', 'color': '#08306b'},
        {'max': 2, 'label': '2 | 하부 사면 (Lower Slope)', 'color': '#2171b5'},
        {'max': 3, 'label': '3 | 평지/단구 (Flat or Terrace)', 'color': '#f7f7f7'},
        {'max': 4, 'label': '4 | 중간 사면 (Mid Slope)', 'color': '#fee391'},
        {'max': 5, 'label': '5 | 상부 사면 (Upper Slope)', 'color': '#ec7014'},
        {'max': 6, 'label': '6 | 급경사 능선 (Steep Ridge)', 'color': '#8c2d04'},
    ]

    # Roughness - Wilson (2000) - Greens to Purple.
    # The last break is inf: QGIS Discrete shaders render values above the last
    # entry as TRANSPARENT, so a finite 500 cap made extreme cells invisible
    # while the legend claimed "15m+".
    ROUGHNESS_CLASSES = [
        {'max': 1, 'label': '평탄 | 0~1m', 'color': '#d9f0d3'},
        {'max': 3, 'label': '미세거침 | 1~3m', 'color': '#a6dba0'},
        {'max': 6, 'label': '중간거침 | 3~6m', 'color': '#5aae61'},
        {'max': 15, 'label': '험준 | 6~15m', 'color': '#c2a5cf'},
        {'max': float('inf'), 'label': '극도험준 | 15m+', 'color': '#762a83'},
    ]
    
    def __init__(self, iface, parent=None):
        super(TerrainAnalysisDialog, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface
        
        self.cmbDemLayer.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.btnRun.clicked.connect(self.run_analysis)
        self.btnClose.clicked.connect(self.reject)
        
        # Advanced settings toggle - EXPANDED by default (user request)
        self.widgetAdvanced.setVisible(True)
        self.btnAdvanced.setText("⚙ 고급 설정 ▲")
        self.btnAdvanced.clicked.connect(self.toggle_advanced)
        
        # Auto-SD checkbox connection and initial state
        if hasattr(self, 'chkAutoSD'):
            self.chkAutoSD.stateChanged.connect(self.on_auto_sd_changed)
            # Apply initial state - disable inputs if auto-SD is checked
            self._apply_auto_sd_state(self.chkAutoSD.isChecked())

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
        except Exception:
            pass

    def _on_help(self):
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            html = (
                "<h2>지형 분석 (Terrain Analysis)</h2>"
                "<p>DEM에서 지형 지표를 계산하고(경사/사면방향/TRI/TPI/Roughness/Slope Position/곡률) "
                "분류·스타일을 적용합니다.</p>"
                "<h3>곡률 (Zevenbergen &amp; Thorne 1987)</h3>"
                "<ul>"
                "<li><b>종단(profile)</b>: 경사 방향 곡률. <b>음(−)=볼록</b>(경사 가속→침식 경향), "
                "<b>양(+)=오목</b>(감속→퇴적 경향).</li>"
                "<li><b>횡단(plan)</b>: 등고선 방향 곡률. <b>음(−)=수렴</b>(곡저·물 모임), "
                "<b>양(+)=발산</b>(능선·분산).</li>"
                "<li>실행 후 <b>해석 요약</b>(볼록/평탄/오목·수렴/평탄/발산 면적 %)을 로그와 메시지바에 표시합니다.</li>"
                "</ul>"
                "<h3>사면 파생 (모델용)</h3>"
                "<ul>"
                "<li><b>북향성</b>=cos(aspect), <b>동향성</b>=sin(aspect): 원형인 사면방향을 모델에 바로 쓰는 연속값으로.</li>"
                "<li><b>TRASP</b>(Roberts &amp; Cooper 1989): 0=북동(서늘/습) ~ 1=남서(따뜻/건조) 일사 프록시.</li>"
                "<li>실행 후 TRASP/북향 우세 등 <b>해석 요약</b>을 표시합니다.</li>"
                "</ul>"
                "<h3>출력</h3>"
                "<ul>"
                "<li>선택한 지표별 래스터 레이어</li>"
                "<li>(옵션) 분류/색상표 적용</li>"
                "</ul>"
                "<h3>팁</h3>"
                "<ul>"
                "<li>DEM이 너무 거칠면(해상도 낮음) TPI/TRI가 과도하게 튈 수 있습니다.</li>"
                "<li>TPI 자동 SD 모드는 입력 DEM 통계에 따라 임계값을 자동으로 잡습니다.</li>"
                "<li>학술 출처는 <code>REFERENCES.md</code>를 참고하세요.</li>"
                "</ul>"
            )
            show_help_dialog(parent=self, title="지형 분석 도움말", html=html, plugin_dir=plugin_dir)
        except Exception:
            try:
                QtWidgets.QMessageBox.information(self, "도움말", "README.md를 참고하세요.")
            except Exception:
                pass
    
    def on_auto_sd_changed(self, state):
        """Enable/disable manual TPI threshold inputs based on auto-SD checkbox"""
        # Use isChecked() for reliable check - stateChanged sends int (0, 1, or 2)
        auto_mode = self.chkAutoSD.isChecked()
        self._apply_auto_sd_state(auto_mode)
    
    def _apply_auto_sd_state(self, auto_mode):
        """Apply the auto-SD state to disable/enable relevant spinboxes"""
        self.spinTPILow.setEnabled(not auto_mode)
        self.spinTPIHigh.setEnabled(not auto_mode)
        self.spinTPIThreshold.setEnabled(not auto_mode)
    
    def toggle_advanced(self):
        """Toggle visibility of advanced settings"""
        is_visible = self.widgetAdvanced.isVisible()
        self.widgetAdvanced.setVisible(not is_visible)
        if is_visible:
            self.btnAdvanced.setText("⚙ 고급 설정 ▼")
        else:
            self.btnAdvanced.setText("⚙ 고급 설정 ▲")
    
    def get_selected_classification(self):
        if self.radioKorean.isChecked():
            return 'korean'
        elif self.radioTobler.isChecked():
            return 'tobler'
        elif self.radioMinetti.isChecked():
            return 'minetti'
        else:
            return 'llobera'
    
    def get_tpi_classes(self, threshold):
        """Generate TPI classification classes based on user threshold.

        Last break is inf: Discrete shaders render values past the final entry
        as transparent, so a finite cap would hide extreme ridges."""
        return [
            {'max': -threshold, 'label': f'골짜기 | <-{threshold:.2f}', 'color': '#2166ac'},
            {'max': threshold, 'label': f'평지 | -{threshold:.2f}~+{threshold:.2f}', 'color': '#f7f7f7'},
            {'max': float('inf'), 'label': f'능선 | >+{threshold:.2f}', 'color': '#8b4513'},
        ]
    
    def get_tri_classes(self, max_rugged):
        """Generate TRI classification classes based on user-defined max ruggedness threshold
        
        Parameters:
        - max_rugged: The threshold above which terrain is classified as 'rugged' (V)
          Lower values = more sensitive to subtle terrain variations
          Higher values = only extreme ruggedness is classified as 'rugged'
        """
        # Proportionally distribute the 5 classes based on max_rugged
        t1 = max_rugged * 0.1   # ~10% = flat
        t2 = max_rugged * 0.25  # ~25% = nearly flat  
        t3 = max_rugged * 0.5   # ~50% = slightly rugged
        t4 = max_rugged         # 100% = moderately rugged
        return [
            {'max': t1, 'label': f'I | 0~{t1:.0f} | 평탄', 'color': '#2166ac'},
            {'max': t2, 'label': f'II | {t1:.0f}~{t2:.0f} | 거의평탄', 'color': '#67a9cf'},
            {'max': t3, 'label': f'III | {t2:.0f}~{t3:.0f} | 약간거침', 'color': '#f7f7f7'},
            {'max': t4, 'label': f'IV | {t3:.0f}~{t4:.0f} | 중간', 'color': '#ef8a62'},
            {'max': float('inf'), 'label': f'V | {t4:.0f}+ | 험준', 'color': '#b2182b'},
        ]
    
    def apply_style(self, layer, classes, max_val):
        """Apply discrete color classification"""
        color_ramp = QgsColorRampShader()
        color_ramp.setColorRampType(QgsColorRampShader.Discrete)
        
        items = []
        for cls in classes:
            item = QgsColorRampShader.ColorRampItem(
                cls['max'], QColor(cls['color']), cls['label']
            )
            items.append(item)
        
        color_ramp.setColorRampItemList(items)
        
        shader = QgsRasterShader()
        shader.setRasterShaderFunction(color_ramp)
        
        renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
        renderer.setClassificationMin(0)
        renderer.setClassificationMax(max_val)
        
        layer.setRenderer(renderer)
        layer.triggerRepaint()
    
    def run_analysis(self):
        dem_layer = self.cmbDemLayer.currentLayer()
        if not dem_layer:
            push_message(self.iface, "오류", "DEM 래스터를 선택해주세요", level=2)
            restore_ui_focus(self)
            return
        
        has_any = any([self.chkSlope.isChecked(), self.chkAspect.isChecked(),
                       self.chkTRI.isChecked(), self.chkTPI.isChecked(),
                       self.chkRoughness.isChecked(), self.chkSlopePosition.isChecked(),
                       (hasattr(self, "chkCurvature") and self.chkCurvature.isChecked()),
                       (hasattr(self, "chkAspectDeriv") and self.chkAspectDeriv.isChecked())])
        if not has_any:
            push_message(self.iface, "오류", "분석 유형을 선택해주세요", level=2)
            restore_ui_focus(self)
            return

        # gdal:slope/aspect run with SCALE=1 and the curvature kernel takes cell
        # size from the geotransform: on a geographic (degree) DEM every output
        # would be silently, plausibly wrong (slope ~89.9° everywhere).
        try:
            if dem_layer.crs().isGeographic():
                push_message(
                    self.iface,
                    "오류",
                    "DEM이 지리좌표계(위경도)입니다. 미터 단위 투영 좌표계로 재투영 후 사용하세요. "
                    "(위경도 DEM에서는 경사/곡률 값이 전부 왜곡됩니다)",
                    level=2,
                    duration=9,
                )
                restore_ui_focus(self)
                return
        except Exception:
            pass

        # Live log window (non-modal) so users can see progress in real time.
        ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)
        
        push_message(self.iface, "처리 중", "지형 분석 실행 중...", level=0)
        self.hide()
        QtWidgets.QApplication.processEvents()
        
        success = False
        try:
            dem_source = dem_layer.source()
            results = []
            run_id = uuid.uuid4().hex[:8]
            
            # Get user parameters
            tpi_radius = self.spinTPIRadius.value()
            tpi_threshold = self.spinTPIThreshold.value()
            slope_threshold = self.spinSlopeThreshold.value()
            tpi_low = self.spinTPILow.value()
            tpi_high = self.spinTPIHigh.value()
            tri_max = self.spinTRIMax.value()
            
            # Slope
            if self.chkSlope.isChecked():
                output = os.path.join(tempfile.gettempdir(), f'archtoolkit_slope_{run_id}.tif')
                processing.run("gdal:slope", {
                    'INPUT': dem_source, 'BAND': 1, 'SCALE': 1, 'AS_PERCENT': False, 'OUTPUT': output
                })
                cls_key = self.get_selected_classification()
                cls_info = self.SLOPE_CLASSIFICATIONS[cls_key]
                layer = QgsRasterLayer(output, f"경사도_{cls_info['name']}")
                if layer.isValid():
                    try:
                        set_archtoolkit_layer_metadata(
                            layer,
                            tool_id="terrain_analysis",
                            run_id=str(run_id),
                            kind="slope",
                            units="deg",
                            params={"classification": str(cls_key)},
                        )
                    except Exception:
                        pass
                    QgsProject.instance().addMapLayer(layer)
                    self.apply_style(layer, cls_info['classes'], 90)
                    results.append("경사도")
            
            # Aspect
            if self.chkAspect.isChecked():
                output = os.path.join(tempfile.gettempdir(), f'archtoolkit_aspect_{run_id}.tif')
                processing.run("gdal:aspect", {
                    'INPUT': dem_source, 'BAND': 1, 'TRIG_ANGLE': False, 'ZERO_FLAT': True, 'OUTPUT': output
                })
                layer = QgsRasterLayer(output, "사면방향_8방위")
                if layer.isValid():
                    try:
                        set_archtoolkit_layer_metadata(
                            layer,
                            tool_id="terrain_analysis",
                            run_id=str(run_id),
                            kind="aspect",
                            units="deg",
                        )
                    except Exception:
                        pass
                    QgsProject.instance().addMapLayer(layer)
                    self.apply_style(layer, self.ASPECT_CLASSES, 360)
                    results.append("사면방향")
            
            # TRI with user-defined classification threshold
            if self.chkTRI.isChecked():
                output = os.path.join(tempfile.gettempdir(), f'archtoolkit_tri_{run_id}.tif')
                processing.run("gdal:triterrainruggednessindex", {
                    'INPUT': dem_source, 'BAND': 1, 'OUTPUT': output
                })
                tri_classes = self.get_tri_classes(tri_max)
                layer_name = f"TRI Riley 1999 (험준기준:{tri_max})"
                layer = QgsRasterLayer(output, layer_name)
                if layer.isValid():
                    try:
                        set_archtoolkit_layer_metadata(
                            layer,
                            tool_id="terrain_analysis",
                            run_id=str(run_id),
                            kind="tri",
                            units="index",
                            params={"tri_max": float(tri_max)},
                        )
                    except Exception:
                        pass
                    QgsProject.instance().addMapLayer(layer)
                    self.apply_style(layer, tri_classes, tri_max * 2.5)
                    results.append("TRI")
            
            # TPI with user parameters (radius and threshold)
            if self.chkTPI.isChecked():
                self.run_tpi_analysis(dem_layer, dem_source, tpi_radius, tpi_threshold, results, run_id)
            
            # Roughness
            if self.chkRoughness.isChecked():
                output = os.path.join(tempfile.gettempdir(), f'archtoolkit_roughness_{run_id}.tif')
                processing.run("gdal:roughness", {
                    'INPUT': dem_source, 'BAND': 1, 'OUTPUT': output
                })
                layer = QgsRasterLayer(output, "Roughness Wilson 2000")
                if layer.isValid():
                    try:
                        set_archtoolkit_layer_metadata(
                            layer,
                            tool_id="terrain_analysis",
                            run_id=str(run_id),
                            kind="roughness",
                            units="index",
                        )
                    except Exception:
                        pass
                    QgsProject.instance().addMapLayer(layer)
                    self.apply_style(layer, self.ROUGHNESS_CLASSES, 20)
                    results.append("Roughness")
            
            # Slope Position - Weiss (2001) 6-class with user thresholds
            if self.chkSlopePosition.isChecked():
                self.run_slope_position_analysis(dem_source, slope_threshold, tpi_low, tpi_high, results, run_id)

            # Curvature - Zevenbergen & Thorne (1987): profile + plan + interpretation
            if hasattr(self, "chkCurvature") and self.chkCurvature.isChecked():
                self.run_curvature_analysis(dem_layer, dem_source, results, run_id)

            # Aspect derivatives - northness/eastness/TRASP (model-ready aspect)
            if hasattr(self, "chkAspectDeriv") and self.chkAspectDeriv.isChecked():
                self.run_aspect_derivatives(dem_layer, dem_source, results, run_id)

            if results:
                push_message(self.iface, "완료", f"분석 완료: {', '.join(results)}", level=0)
                success = True
                self.accept()
            else:
                push_message(self.iface, "오류", "분석 결과가 없습니다.", level=2)
                restore_ui_focus(self)
                
        except Exception as e:
            push_message(self.iface, "오류", f"처리 중 오류: {str(e)}", level=2)
            restore_ui_focus(self)
        finally:
            if not success:
                restore_ui_focus(self)
    
    def run_tpi_analysis(self, dem_layer, dem_source, radius, threshold, results, run_id):
        """Run TPI analysis with user-specified radius and classification threshold
        
        TPI = Elevation - Mean of Neighborhood
        
        Uses GDAL only - for radius > 1, uses resampling trick to approximate larger windows.
        
        Parameters:
        - radius: Number of cells for neighborhood window (larger = broader terrain features)
        - threshold: Classification boundary for valley/flat/ridge (smaller = more sensitive)
        """
        downsampled = None
        mean_approx = None
        try:
            output = os.path.join(tempfile.gettempdir(), f'archtoolkit_tpi_{run_id}.tif')
            
            # Calculate window size (must be odd number: 3, 5, 7, ...)
            window_size = radius * 2 + 1 if radius > 1 else 3
            
            if radius <= 1:
                # Use standard GDAL TPI for radius=1 (3x3 window)
                processing.run("gdal:tpitopographicpositionindex", {
                    'INPUT': dem_source, 'BAND': 1, 'OUTPUT': output
                })
            else:
                # Pure GDAL approach for custom radius:
                
                # Get original resolution
                pixel_size_x = dem_layer.rasterUnitsPerPixelX()
                pixel_size_y = dem_layer.rasterUnitsPerPixelY()
                new_res = max(pixel_size_x, pixel_size_y) * radius
                
                # Step 1: Downsample (average resampling = approximate focal mean)
                downsampled = os.path.join(tempfile.gettempdir(), f'archtoolkit_tpi_down_{run_id}.tif')
                processing.run("gdal:warpreproject", {
                    'INPUT': dem_source,
                    'SOURCE_CRS': None,
                    'TARGET_CRS': None,
                    'RESAMPLING': 5,  # Average
                    'NODATA': None,
                    'TARGET_RESOLUTION': new_res,
                    'OPTIONS': '',
                    'DATA_TYPE': 6,  # Float32: keep the focal mean fractional (Int16 DEMs truncate)
                    'TARGET_EXTENT': None,
                    'TARGET_EXTENT_CRS': None,
                    'MULTITHREADING': False,
                    'EXTRA': '',
                    'OUTPUT': downsampled
                })
                
                # Step 2: Resample back to original resolution (neighborhood mean approximation)
                mean_approx = os.path.join(tempfile.gettempdir(), f'archtoolkit_tpi_mean_{run_id}.tif')
                extent = dem_layer.extent()
                extent_str = f"{extent.xMinimum()},{extent.xMaximum()},{extent.yMinimum()},{extent.yMaximum()}"
                
                processing.run("gdal:warpreproject", {
                    'INPUT': downsampled,
                    'SOURCE_CRS': None,
                    'TARGET_CRS': None,
                    'RESAMPLING': 1,  # Bilinear
                    'NODATA': None,
                    'TARGET_RESOLUTION': pixel_size_x,
                    'OPTIONS': '',
                    'DATA_TYPE': 6,  # Float32
                    'TARGET_EXTENT': extent_str,
                    'TARGET_EXTENT_CRS': dem_layer.crs().authid(),
                    'MULTITHREADING': False,
                    'EXTRA': '',
                    'OUTPUT': mean_approx
                })

                # Step 3: Calculate TPI = DEM - Mean.
                # NO_DATA makes gdal_calc propagate DEM NoData into the output
                # instead of computing (-9999)-(-9999)=0 and classifying the
                # collar outside a clipped DEM as "flat terrain".
                if os.path.exists(mean_approx):
                    processing.run("gdal:rastercalculator", {
                        'INPUT_A': dem_source, 'BAND_A': 1,
                        'INPUT_B': mean_approx, 'BAND_B': 1,
                        'FORMULA': 'A - B',
                        'NO_DATA': -9999.0,
                        'OUTPUT': output,
                        'RTYPE': 5  # Float32
                    })
                else:
                    # Fallback to standard GDAL TPI
                    processing.run("gdal:tpitopographicpositionindex", {
                        'INPUT': dem_source, 'BAND': 1, 'OUTPUT': output
                    })
                    window_size = 3
            
            # Apply classification with user threshold
            tpi_classes = self.get_tpi_classes(threshold)
            if radius > 1:
                # Honest label: the custom radius is a block-average + bilinear
                # approximation at scale ~radius cells, not a true (2r+1)² focal mean.
                layer_name = f"TPI (근사 반경≈{radius}셀, 임계값:±{threshold:.2f})"
            else:
                layer_name = f"TPI (창:{window_size}x{window_size}, 임계값:±{threshold:.2f})"
            layer = QgsRasterLayer(output, layer_name)
            
            if layer.isValid():
                try:
                    set_archtoolkit_layer_metadata(
                        layer,
                        tool_id="terrain_analysis",
                        run_id=str(run_id),
                        kind="tpi",
                        units="index",
                        params={"radius": int(radius), "threshold": float(threshold)},
                    )
                except Exception:
                    pass
                QgsProject.instance().addMapLayer(layer)
                self.apply_style(layer, tpi_classes, 10)
                results.append("TPI")
            
        except Exception as e:
            self.iface.messageBar().pushMessage("경고", f"TPI 분석 오류: {str(e)}", level=1)
        finally:
            cleanup_files([downsampled, mean_approx])
    
    def run_slope_position_analysis(self, dem_source, slope_thresh, tpi_low, tpi_high, results, run_id):
        """Run Weiss (2001) 6-class Landform Classification using GDAL with user thresholds
        
        Parameters:
        - slope_thresh: Degree threshold for flat vs sloped areas (e.g., 5°)
        - tpi_low: TPI threshold for valley classification (e.g., -1.0)
        - tpi_high: TPI threshold for ridge classification (e.g., 1.0)
        
        Classification Logic:
        1. 깊은 곡저 (Incised Valley): TPI < tpi_low
        2. 곡저/하상 (Valley Floor): tpi_low <= TPI < tpi_low/2
        3. 평지/단구 (Flat or Terrace): |TPI| <= |tpi_low/2| and Slope <= slope_thresh
        4. 중간 사면 (Mid Slope): |TPI| <= |tpi_high/2| and Slope > slope_thresh
        5. 능선 평탄부 (Upland Flat): tpi_high/2 < TPI <= tpi_high
        6. 급경사 능선 (Steep Ridge): TPI > tpi_high
        """
        # Assigned inside try; predefine so the finally-cleanup never hits
        # an unbound name (which would mask the original error).
        tpi_path = None
        slope_path = None
        try:
            # 1. Generate TPI
            tpi_path = os.path.join(tempfile.gettempdir(), f'archtoolkit_tpi_temp_{run_id}.tif')
            processing.run("gdal:tpitopographicpositionindex", {
                'INPUT': dem_source, 'BAND': 1, 'OUTPUT': tpi_path
            })
            
            # 2. Generate Slope
            slope_path = os.path.join(tempfile.gettempdir(), f'archtoolkit_slope_temp_{run_id}.tif')
            processing.run("gdal:slope", {
                'INPUT': dem_source, 'BAND': 1, 'SCALE': 1, 'AS_PERCENT': False, 'OUTPUT': slope_path
            })
            
            # 3. Check if files exist
            if not os.path.exists(tpi_path) or not os.path.exists(slope_path):
                self.iface.messageBar().pushMessage("경고", "TPI/Slope 생성 실패", level=1)
                return
            
            # 3.5 AUTO-SD CALCULATION (Weiss 2001 standard approach)
            # Calculate TPI statistics to use 1 SD as threshold
            use_auto_sd = hasattr(self, 'chkAutoSD') and self.chkAutoSD.isChecked()
            if use_auto_sd:
                tpi_layer = QgsRasterLayer(tpi_path, "TPI_temp")
                if tpi_layer.isValid():
                    provider = tpi_layer.dataProvider()
                    stats = provider.bandStatistics(1)
                    tpi_sd = stats.stdDev
                    tpi_mean = stats.mean
                    # Weiss (2001): use 1 SD as threshold
                    tpi_low = -tpi_sd
                    tpi_high = tpi_sd
                    self.iface.messageBar().pushMessage(
                        "자동 SD", 
                        f"TPI 통계: 평균={tpi_mean:.2f}, 표준편차={tpi_sd:.2f} → 임계값 ±{tpi_sd:.2f} 적용",
                        level=0
                    )
            
            # 4. Use gdal_calc.py for classification with thresholds
            output_path = os.path.join(tempfile.gettempdir(), f'archtoolkit_landform_{run_id}.tif')
            
            # Calculate intermediate thresholds (Weiss 2001: 0.5 SD boundaries)
            tpi_mid_low = tpi_low / 2   # -0.5 SD
            tpi_mid_high = tpi_high / 2  # +0.5 SD
            
            # Classification: 1=Valley, 2=Lower, 3=Flat, 4=Mid, 5=Upper, 6=Ridge
            # Using user-defined thresholds
            calc_expr = (
                f"(A<{tpi_low})*1 + "
                f"((A>={tpi_low})*(A<{tpi_mid_low}))*2 + "
                f"((A>={tpi_mid_low})*(A<={tpi_mid_high})*(B<={slope_thresh}))*3 + "
                f"((A>={tpi_mid_low})*(A<={tpi_mid_high})*(B>{slope_thresh}))*4 + "
                f"((A>{tpi_mid_high})*(A<={tpi_high}))*5 + "
                f"(A>{tpi_high})*6"
            )

            # Mask NoData: TPI/Slope NoData cells (e.g. edge -9999) otherwise satisfy
            # A<tpi_low and get miscoloured as class 1 (valley). Zero them out and
            # mark 0 as NoData (transparent) after the layer is created.
            nd_a = nd_b = None
            if gdal is not None:
                try:
                    _da = gdal.Open(tpi_path, gdal.GA_ReadOnly)
                    nd_a = _da.GetRasterBand(1).GetNoDataValue() if _da else None
                    _da = None
                    _db = gdal.Open(slope_path, gdal.GA_ReadOnly)
                    nd_b = _db.GetRasterBand(1).GetNoDataValue() if _db else None
                    _db = None
                except Exception:
                    nd_a = nd_b = None
            mask_expr = ""
            if nd_a is not None:
                mask_expr += f"*(A!={nd_a})"
            if nd_b is not None:
                mask_expr += f"*(B!={nd_b})"
            if mask_expr:
                calc_expr = f"({calc_expr}){mask_expr}"

            result = processing.run("gdal:rastercalculator", {
                'INPUT_A': tpi_path, 'BAND_A': 1,
                'INPUT_B': slope_path, 'BAND_B': 1,
                'FORMULA': calc_expr,
                'OUTPUT': output_path,
                'RTYPE': 1  # Int16
            })
            
            if result and os.path.exists(output_path):
                layer_name = f"지형분류 (경사:{slope_thresh}°, TPI:{tpi_low:.1f}~{tpi_high:.1f})"
                layer = QgsRasterLayer(output_path, layer_name)
                if layer.isValid():
                    try:
                        set_archtoolkit_layer_metadata(
                            layer,
                            tool_id="terrain_analysis",
                            run_id=str(run_id),
                            kind="slope_position",
                            units="class",
                            params={
                                "slope_thresh_deg": float(slope_thresh),
                                "tpi_low": float(tpi_low),
                                "tpi_high": float(tpi_high),
                            },
                        )
                    except Exception:
                        pass
                    # Class 0 = masked NoData -> transparent
                    try:
                        layer.dataProvider().setNoDataValue(1, 0)
                    except Exception:
                        pass
                    QgsProject.instance().addMapLayer(layer)
                    self.apply_style(layer, self.SLOPE_POSITION_CLASSES, 6)
                    results.append("지형분류")
                else:
                    self.iface.messageBar().pushMessage("경고", "지형분류 레이어 생성 실패", level=1)
            else:
                self.iface.messageBar().pushMessage("경고", "지형분류 래스터 생성 실패", level=1)
                
        except Exception as e:
            self.iface.messageBar().pushMessage("경고", f"지형분류 분석 오류: {str(e)}", level=1)
        finally:
            cleanup_files([tpi_path, slope_path])

    def run_curvature_analysis(self, dem_layer, dem_source, results, run_id):
        """Profile & plan curvature (Zevenbergen & Thorne 1987) + interpretation.

        Sign convention (numerically verified against synthetic surfaces):
        - profile: (-) 볼록 convex, 경사 가속 → 침식 경향 / (+) 오목 concave, 감속 → 퇴적 경향
        - plan:    (-) 수렴 convergent, 곡저·물 모임 / (+) 발산 divergent, 능선·분산

        This produces not just rasters but an interpretation summary (area % of
        convex/flat/concave and convergent/flat/divergent) so the result reads
        as an analysis, not a bare covariate.
        """
        if np is None or gdal is None:
            push_message(self.iface, "경고", "곡률 분석에는 NumPy/GDAL이 필요합니다(QGIS 기본 포함).", level=1)
            return
        try:
            src = str(dem_source or "").split("|", 1)[0].strip()
            ds = gdal.Open(src, gdal.GA_ReadOnly)
            if ds is None:
                push_message(self.iface, "경고", "DEM을 GDAL로 열 수 없습니다(곡률).", level=1)
                return
            band = ds.GetRasterBand(1)
            # Memory guard: the kernel keeps ~18 full-size arrays alive; at
            # float32 that's ~72 B/px, so cap the pixel count instead of letting
            # a merged LiDAR DEM freeze QGIS. 120M px ≈ 9 GB peak.
            npx = int(ds.RasterXSize) * int(ds.RasterYSize)
            if npx > 120_000_000:
                push_message(
                    self.iface,
                    "경고",
                    f"DEM이 너무 큽니다({npx:,} 픽셀). 곡률 분석은 1.2억 픽셀 이하로 클립/리샘플 후 실행하세요.",
                    level=1,
                    duration=9,
                )
                ds = None
                return
            z = band.ReadAsArray().astype("float32")
            gt = ds.GetGeoTransform()
            proj = ds.GetProjection()
            nodata = band.GetNoDataValue()
            ds = None
            if z is None or z.ndim != 2:
                push_message(self.iface, "경고", "DEM 배열을 읽을 수 없습니다(곡률).", level=1)
                return

            cell = (abs(float(gt[1])) + abs(float(gt[5]))) / 2.0
            if cell <= 0:
                push_message(self.iface, "경고", "DEM 픽셀 크기를 확인할 수 없습니다(곡률).", level=1)
                return

            valid = np.isfinite(z)
            if nodata is not None:
                valid &= (z != nodata)

            # Curvature is invariant to an additive constant. Subtracting the
            # mean valid elevation drops working magnitudes from ~1000 m (a
            # Korean LiDAR base) to relief scale, avoiding float32 catastrophic
            # cancellation in the second-difference terms (verified: cuts
            # sign-flips/large errors on sub-meter micro-relief) while keeping
            # the float32 memory budget.
            try:
                if np.any(valid):
                    z0 = float(np.mean(z[valid]))
                    if np.isfinite(z0):
                        z = z - np.float32(z0)
            except Exception:
                pass

            profile, plan = self._zt_curvature(z, cell)

            # NoData where any 3x3 neighbour is invalid, plus the 1-px border.
            inv = ~valid
            inv_any = (
                inv
                | np.roll(inv, 1, 0) | np.roll(inv, -1, 0)
                | np.roll(inv, 1, 1) | np.roll(inv, -1, 1)
                | np.roll(np.roll(inv, 1, 0), 1, 1) | np.roll(np.roll(inv, 1, 0), -1, 1)
                | np.roll(np.roll(inv, -1, 0), 1, 1) | np.roll(np.roll(inv, -1, 0), -1, 1)
            )
            border = np.zeros(z.shape, dtype=bool)
            border[0, :] = border[-1, :] = border[:, 0] = border[:, -1] = True
            out_mask = inv_any | border
            nd = -9999.0
            for arr in (profile, plan):
                arr[out_mask] = nd

            good = ~out_mask
            prof_path = os.path.join(tempfile.gettempdir(), f'archtoolkit_curv_profile_{run_id}.tif')
            plan_path = os.path.join(tempfile.gettempdir(), f'archtoolkit_curv_plan_{run_id}.tif')
            self._write_geotiff(prof_path, profile.astype("float32"), gt, proj, nd)
            self._write_geotiff(plan_path, plan.astype("float32"), gt, proj, nd)

            for path, name, kind, arr, neg_lab, pos_lab in (
                (prof_path, "곡률-종단 profile (Zevenbergen & Thorne 1987)", "curvature_profile",
                 profile, "볼록 convex (침식)", "오목 concave (퇴적)"),
                (plan_path, "곡률-횡단 plan (Zevenbergen & Thorne 1987)", "curvature_plan",
                 plan, "수렴 convergent (물모임)", "발산 divergent (능선)"),
            ):
                layer = QgsRasterLayer(path, name)
                if not layer.isValid():
                    continue
                try:
                    set_archtoolkit_layer_metadata(
                        layer, tool_id="terrain_analysis", run_id=str(run_id),
                        kind=kind, units="1/m",
                        params={"method": "Zevenbergen & Thorne 1987", "cell_size": float(cell)},
                    )
                except Exception:
                    pass
                QgsProject.instance().addMapLayer(layer)
                self._apply_diverging_style(layer, arr[good], neg_lab, pos_lab)

            self._log_curvature_summary(profile[good], plan[good])
            results.append("곡률")
        except Exception as e:
            push_message(self.iface, "경고", f"곡률 분석 오류: {str(e)}", level=1)

    def _zt_curvature(self, z, cell):
        """Zevenbergen & Thorne (1987) profile/plan curvature. See run_curvature_analysis
        for the (verified) sign convention."""
        Z2 = np.roll(z, 1, 0)
        Z8 = np.roll(z, -1, 0)
        Z4 = np.roll(z, 1, 1)
        Z6 = np.roll(z, -1, 1)
        Z1 = np.roll(np.roll(z, 1, 0), 1, 1)
        Z3 = np.roll(np.roll(z, 1, 0), -1, 1)
        Z7 = np.roll(np.roll(z, -1, 0), 1, 1)
        Z9 = np.roll(np.roll(z, -1, 0), -1, 1)
        Z5 = z
        L2 = cell * cell
        D = ((Z4 + Z6) / 2.0 - Z5) / L2
        E = ((Z2 + Z8) / 2.0 - Z5) / L2
        F = (-Z1 + Z3 + Z7 - Z9) / (4.0 * L2)
        G = (-Z4 + Z6) / (2.0 * cell)
        H = (Z2 - Z8) / (2.0 * cell)
        denom = G * G + H * H
        small = denom < 1e-12
        ds = np.where(small, 1.0, denom)
        profile = np.where(small, 0.0, 2.0 * (D * G * G + E * H * H + F * G * H) / ds)
        plan = np.where(small, 0.0, -2.0 * (D * H * H + E * G * G - F * G * H) / ds)
        return profile, plan

    def _write_geotiff(self, out_path, arr, gt, proj, nodata):
        driver = gdal.GetDriverByName("GTiff")
        rows, cols = arr.shape
        ds = driver.Create(out_path, cols, rows, 1, gdal.GDT_Float32, ["COMPRESS=LZW"])
        ds.SetGeoTransform(gt)
        if proj:
            ds.SetProjection(proj)
        b = ds.GetRasterBand(1)
        b.SetNoDataValue(float(nodata))
        b.WriteArray(arr)
        b.FlushCache()
        ds = None

    def _apply_diverging_style(self, layer, valid_values, neg_label, pos_label):
        """Blue-white-red diverging ramp, symmetric about 0 (2/98 percentile range).

        neg_label / pos_label describe what negative / positive values mean for
        THIS raster (profile and plan have different meanings for the same sign).
        """
        try:
            if valid_values.size:
                absmax = float(np.nanpercentile(np.abs(valid_values), 98))
            else:
                absmax = 1.0
            if not np.isfinite(absmax) or absmax <= 0:
                absmax = 1.0
            ramp = QgsColorRampShader()
            ramp.setColorRampType(QgsColorRampShader.Interpolated)
            ramp.setColorRampItemList([
                QgsColorRampShader.ColorRampItem(-absmax, QColor('#2166ac'), f"{-absmax:.4f} ({neg_label})"),
                QgsColorRampShader.ColorRampItem(0.0, QColor('#f7f7f7'), "0 (평탄)"),
                QgsColorRampShader.ColorRampItem(absmax, QColor('#b2182b'), f"{absmax:.4f} ({pos_label})"),
            ])
            shader = QgsRasterShader()
            shader.setRasterShaderFunction(ramp)
            renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
            renderer.setClassificationMin(-absmax)
            renderer.setClassificationMax(absmax)
            layer.setRenderer(renderer)
            layer.triggerRepaint()
        except Exception:
            pass

    def _log_curvature_summary(self, profile_valid, plan_valid):
        """Emit an interpretation (area % per curvature class) to the live log + message bar."""
        try:
            if profile_valid.size == 0:
                return
            eps_p = max(1e-9, 0.1 * float(np.std(profile_valid)))
            eps_c = max(1e-9, 0.1 * float(np.std(plan_valid)))
            convex = float(np.mean(profile_valid < -eps_p) * 100.0)
            concave = float(np.mean(profile_valid > eps_p) * 100.0)
            flat_p = max(0.0, 100.0 - convex - concave)
            diverg = float(np.mean(plan_valid > eps_c) * 100.0)
            converg = float(np.mean(plan_valid < -eps_c) * 100.0)
            flat_c = max(0.0, 100.0 - diverg - converg)
            msg = (
                f"곡률 해석 — 종단: 볼록(침식) {convex:.1f}% / 평탄 {flat_p:.1f}% / 오목(퇴적) {concave:.1f}% | "
                f"횡단: 수렴(물모임) {converg:.1f}% / 평탄 {flat_c:.1f}% / 발산(능선) {diverg:.1f}%"
            )
            log_message(msg)
            push_message(self.iface, "곡률 해석", msg, level=0, duration=12)
        except Exception:
            pass

    def run_aspect_derivatives(self, dem_layer, dem_source, results, run_id):
        """Model-ready aspect transforms: northness, eastness, TRASP + interpretation.

        Raw aspect is circular (0-360 deg) and unusable in most models. These
        continuous transforms fix that and carry ecological meaning:
        - northness = cos(aspect)  (+1 북향 ~ -1 남향)
        - eastness  = sin(aspect)  (+1 동향 ~ -1 서향)
        - TRASP (Roberts & Cooper 1989) = (1 - cos(aspect-30 deg))/2
          0 = 북동(서늘/습), 1 = 남서(따뜻/건조); flat = 0.5 (neutral)
        Flat cells: northness/eastness = 0.
        """
        if np is None or gdal is None:
            push_message(self.iface, "경고", "사면 파생에는 NumPy/GDAL이 필요합니다(QGIS 기본 포함).", level=1)
            return
        aspect_path = None
        try:
            src = str(dem_source or "").split("|", 1)[0].strip()
            aspect_path = os.path.join(tempfile.gettempdir(), f'archtoolkit_aspderiv_asp_{run_id}.tif')
            processing.run("gdal:aspect", {
                'INPUT': src, 'BAND': 1, 'TRIG_ANGLE': False, 'ZERO_FLAT': False,
                'COMPUTE_EDGES': True, 'ZEVENBERGEN': False, 'OUTPUT': aspect_path,
            })
            ads = gdal.Open(aspect_path, gdal.GA_ReadOnly)
            if ads is None:
                push_message(self.iface, "경고", "사면방향 계산 실패(사면 파생).", level=1)
                return
            aband = ads.GetRasterBand(1)
            npx = int(ads.RasterXSize) * int(ads.RasterYSize)
            if npx > 120_000_000:
                push_message(
                    self.iface,
                    "경고",
                    f"DEM이 너무 큽니다({npx:,} 픽셀). 사면 파생은 1.2억 픽셀 이하로 클립/리샘플 후 실행하세요.",
                    level=1,
                    duration=9,
                )
                ads = None
                return
            aspect = aband.ReadAsArray().astype("float32")
            gt = ads.GetGeoTransform()
            proj = ads.GetProjection()
            a_nd = aband.GetNoDataValue()
            ads = None

            # gdaldem aspect (ZERO_FLAT=False) writes the same sentinel for
            # true flats AND for DEM NoData. Read the source DEM's validity so
            # NoData stays NoData instead of being fabricated as "neutral".
            dem_valid = None
            try:
                dds = gdal.Open(src, gdal.GA_ReadOnly)
                if dds is not None:
                    dband = dds.GetRasterBand(1)
                    d_nd = dband.GetNoDataValue()
                    zarr = dband.ReadAsArray()
                    if zarr is not None and zarr.shape == aspect.shape:
                        dem_valid = np.isfinite(zarr)
                        if d_nd is not None:
                            dem_valid &= (zarr != d_nd)
                    del zarr
                    dds = None
            except Exception:
                dem_valid = None

            undefined_aspect = (aspect < 0)
            if a_nd is not None:
                undefined_aspect |= (aspect == a_nd)
            if dem_valid is not None:
                invalid = ~dem_valid                    # DEM NoData → output NoData
                flat = undefined_aspect & dem_valid     # true flats → neutral value
            else:
                invalid = np.zeros(aspect.shape, dtype=bool)
                flat = undefined_aspect
            defined = ~(undefined_aspect | invalid)
            nd = -9999.0
            rad = np.radians(aspect)

            def _make(fn, flat_value):
                arr = np.full(aspect.shape, nd, dtype="float32")
                arr[defined] = fn(rad[defined]).astype("float32") if callable(fn) else fn[defined].astype("float32")
                arr[flat] = flat_value
                return arr

            north = _make(np.cos, 0.0)
            east = _make(np.sin, 0.0)
            trasp = np.full(aspect.shape, nd, dtype="float32")
            trasp[defined] = ((1.0 - np.cos(np.radians(aspect[defined] - 30.0))) / 2.0).astype("float32")
            trasp[flat] = 0.5

            specs = [
                ("northness", "북향성 northness = cos(aspect)", north, "diverging",
                 "남향 south (-1)", "북향 north (+1)"),
                ("eastness", "동향성 eastness = sin(aspect)", east, "diverging",
                 "서향 west (-1)", "동향 east (+1)"),
                ("trasp", "TRASP 일사프록시 (Roberts & Cooper 1989)", trasp, "sequential",
                 "서늘/습 (0)", "따뜻/건조 (1)"),
            ]
            for key, name, arr, style, neg_lab, pos_lab in specs:
                path = os.path.join(tempfile.gettempdir(), f'archtoolkit_aspderiv_{key}_{run_id}.tif')
                self._write_geotiff(path, arr, gt, proj, nd)
                layer = QgsRasterLayer(path, name)
                if not layer.isValid():
                    continue
                try:
                    set_archtoolkit_layer_metadata(
                        layer, tool_id="terrain_analysis", run_id=str(run_id),
                        kind=key, units="index",
                        params={"source": "aspect", "flat_handling": "north/east=0, TRASP=0.5"},
                    )
                except Exception:
                    pass
                QgsProject.instance().addMapLayer(layer)
                valid_vals = arr[arr != nd]
                if style == "diverging":
                    self._apply_diverging_style(layer, valid_vals, neg_lab, pos_lab)
                else:
                    self._apply_sequential_style(layer, 0.0, 1.0, neg_lab, pos_lab)

            self._log_aspect_summary(north, east, trasp, nd)
            results.append("사면파생")
        except Exception as e:
            push_message(self.iface, "경고", f"사면 파생 오류: {str(e)}", level=1)
        finally:
            cleanup_files([aspect_path])

    def _apply_sequential_style(self, layer, vmin, vmax, min_label, max_label):
        """Cool-to-warm sequential ramp for 0..1 style indices (e.g., TRASP)."""
        try:
            ramp = QgsColorRampShader()
            ramp.setColorRampType(QgsColorRampShader.Interpolated)
            mid = (vmin + vmax) / 2.0
            ramp.setColorRampItemList([
                QgsColorRampShader.ColorRampItem(vmin, QColor('#2c7bb6'), f"{vmin:.2f} ({min_label})"),
                QgsColorRampShader.ColorRampItem(mid, QColor('#ffffbf'), f"{mid:.2f}"),
                QgsColorRampShader.ColorRampItem(vmax, QColor('#d7191c'), f"{vmax:.2f} ({max_label})"),
            ])
            shader = QgsRasterShader()
            shader.setRasterShaderFunction(ramp)
            renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
            renderer.setClassificationMin(vmin)
            renderer.setClassificationMax(vmax)
            layer.setRenderer(renderer)
            layer.triggerRepaint()
        except Exception:
            pass

    def _log_aspect_summary(self, north, east, trasp, nd):
        try:
            tv = trasp[trasp != nd]
            nv = north[north != nd]
            if tv.size == 0:
                return
            warm = float(np.mean(tv > 0.6) * 100.0)
            cool = float(np.mean(tv < 0.4) * 100.0)
            neutral = max(0.0, 100.0 - warm - cool)
            north_pct = float(np.mean(nv > 0.3) * 100.0)
            south_pct = float(np.mean(nv < -0.3) * 100.0)
            msg = (
                f"사면 파생 해석 — TRASP: 따뜻/건조 {warm:.1f}% / 중간 {neutral:.1f}% / 서늘/습 {cool:.1f}% | "
                f"북향 우세 {north_pct:.1f}% · 남향 우세 {south_pct:.1f}% (평균 TRASP {float(np.mean(tv)):.2f})"
            )
            log_message(msg)
            push_message(self.iface, "사면 파생 해석", msg, level=0, duration=12)
        except Exception:
            pass
