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
from qgis.PyQt import QtCore, QtWidgets
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis,
    QgsProject,
    QgsRasterLayer,
    QgsRasterShader,
    QgsColorRampShader,
    QgsSingleBandPseudoColorRenderer,
)
from .qtcompat import SHADER_INTERPOLATED, SHADER_DISCRETE
import processing
from .utils import (
    log_swallowed,
    cleanup_files, log_message, push_message, restore_ui_focus, set_archtoolkit_layer_metadata,
)
from .raster_io import write_single_band_geotiff
from .terrain_math import (
    ASPECT_FLAT_VALUE, focal_tpi_strips, mark_flat_aspect, tri_radius, zt_curvature,
)
from . import cost_budget
from .live_log_dialog import ensure_live_log_dialog
from .help_dialog import show_help_dialog
from . import dialog_memory
from .icons import icon as plugin_icon

# This tool uses QGIS built-in GDAL processing algorithms. The curvature
# analysis additionally uses NumPy + GDAL (both ship with QGIS - no extra
# install), per DEVELOPMENT.md.

# Peak working set of terrain_math.tri_radius per input pixel: the float64
# grid, the centre/shifted/difference arrays, the squared-sum and count
# accumulators and both validity masks. Measured with tracemalloc; rounded up.
TRI_RADIUS_BYTES_PER_PIXEL = 80

# Exact radius TPI is computed in horizontal strips (terrain_math.focal_tpi_strips)
# so a large DEM never has to fit in memory at once. Rows per strip are chosen
# so one strip's float64 working arrays stay near this many bytes.
TPI_STRIP_TARGET_BYTES = 256 * 1024 ** 2
TPI_NODATA = -9999.0
ASPECT_NODATA = -9999.0


def _fmt_break(value):
    """A class break for a legend: up to 2 decimals, no trailing zeros."""
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


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
            'name': '보행속도구분(플러그인)',
            'classes': [
                {'max': 6, 'label': '1등급 | 0~6° | 일반 보행', 'color': '#1a5f1a'},
                {'max': 12, 'label': '2등급 | 6~12° | 속도 감소', 'color': '#7ec87e'},
                {'max': 18, 'label': '3등급 | 12~18° | 이동 지체', 'color': '#ffff00'},
                {'max': 25, 'label': '4등급 | 18~25° | 한계', 'color': '#ffa500'},
                {'max': 90, 'label': '5등급 | 25°+ | 불가', 'color': '#ff0000'},
            ]
        },
        'minetti': {
            'name': '에너지구분(플러그인)',
            'classes': [
                {'max': 3, 'label': '1등급 | 0~3° | 일상', 'color': '#20b2aa'},
                {'max': 9, 'label': '2등급 | 3~9° | 노동', 'color': '#ffff00'},
                {'max': 15, 'label': '3등급 | 9~15° | 고강도', 'color': '#ffa500'},
                {'max': 25, 'label': '4등급 | 15~25° | 임계', 'color': '#ff0000'},
                {'max': 90, 'label': '5등급 | 25°+ | 금지', 'color': '#800080'},
            ]
        },
        'llobera': {
            'name': '인지구분(플러그인)',
            'classes': [
                {'max': 2, 'label': '1등급 | 0~2° | 평탄', 'color': '#d3d3d3'},
                {'max': 6, 'label': '2등급 | 2~6° | 인지', 'color': '#add8e6'},
                {'max': 12, 'label': '3등급 | 6~12° | 언덕', 'color': '#00ffff'},
                {'max': 20, 'label': '4등급 | 12~20° | 장벽', 'color': '#800080'},
                {'max': 90, 'label': '5등급 | 20°+ | 수직', 'color': '#000000'},
            ]
        }
    }
    
    # Aspect: 8 compass directions CENTRED on N, NE, E, ... (N = 337.5-22.5),
    # which is what the checkbox tooltip promises ("8방위(N, NE, E, ...)").
    # The old 0-45 / 45-90 sectors had no N class at all: a slope facing 350
    # and one facing 10 degrees fell into different classes. N needs two
    # entries (0-22.5 and 337.5-360) because the Discrete shader is linear.
    # Flat cells carry ASPECT_FLAT_VALUE (-1), outside 0-360, so they no longer
    # share the value 0 with due north; DEM NoData stays NoData (-9999).
    ASPECT_CLASSES = [
        {'max': ASPECT_FLAT_VALUE, 'label': '평탄 | 경사 0° (값 -1) | 방향 없음', 'color': '#808080'},
        {'max': 22.5, 'label': 'N | 0-22.5° | 북', 'color': '#ff0000'},
        {'max': 67.5, 'label': 'NE | 22.5-67.5° | 북동', 'color': '#ff7f00'},
        {'max': 112.5, 'label': 'E | 67.5-112.5° | 동', 'color': '#ffff00'},
        {'max': 157.5, 'label': 'SE | 112.5-157.5° | 남동', 'color': '#7fff00'},
        {'max': 202.5, 'label': 'S | 157.5-202.5° | 남', 'color': '#00ffff'},
        {'max': 247.5, 'label': 'SW | 202.5-247.5° | 남서', 'color': '#007fff'},
        {'max': 292.5, 'label': 'W | 247.5-292.5° | 서', 'color': '#0000ff'},
        {'max': 337.5, 'label': 'NW | 292.5-337.5° | 북서', 'color': '#7f00ff'},
        {'max': 360, 'label': 'N | 337.5-360° | 북', 'color': '#ff0000'},
    ]

    # Weiss (2001) 6-class Slope Position Classification.
    # Labels follow Weiss's own class names: classes 2/5 are Lower/Upper Slope
    # (no flatness test applies to them) — calling them "valley floor"/"upland
    # flat" previously invited wrong archaeological readings. Classes 1/6 are
    # Weiss's Valley/Ridge: no incision or steepness test is applied, so the
    # former "Incised Valley"/"Steep Ridge" names claimed a rule that is not run.
    SLOPE_POSITION_CLASSES = [
        {'max': 1, 'label': '1 | 곡저 (Valley)', 'color': '#08306b'},
        {'max': 2, 'label': '2 | 하부 사면 (Lower Slope)', 'color': '#2171b5'},
        {'max': 3, 'label': '3 | 평지/단구 (Flat or Terrace)', 'color': '#f7f7f7'},
        {'max': 4, 'label': '4 | 중간 사면 (Mid Slope)', 'color': '#fee391'},
        {'max': 5, 'label': '5 | 상부 사면 (Upper Slope)', 'color': '#ec7014'},
        {'max': 6, 'label': '6 | 능선 (Ridge)', 'color': '#8c2d04'},
    ]

    # Roughness - gdaldem's roughness, i.e. Wilson et al. (2007) - Greens
    # to Purple. The 0-1 / 1-3 / 3-6 / 6-15 / 15m+ breaks below are THIS
    # PLUGIN's display convention for Korean terrain, NOT classes published
    # by Wilson et al.; the metadata records them as plugin_defined_5class.
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
        # Remember the last-used inputs between sessions (tools/dialog_memory.py).
        dialog_memory.attach(self, "terrain_analysis")
        try:
            self.setWindowIcon(plugin_icon("terrain.png"))
        except Exception as _exc:
            log_swallowed("terrain_analysis_dialog.__init__ (icon)", _exc)
        self.setupUi(self)
        self.iface = iface
        
        self.cmbDemLayer.setFilters(Qgis.LayerFilter.RasterLayer)
        self.btnRun.clicked.connect(self.run_analysis)
        self.btnClose.clicked.connect(self.reject)
        
        # Advanced settings toggle - EXPANDED by default (user request)
        self.widgetAdvanced.setVisible(True)
        self.btnAdvanced.setText("고급 설정 ▲")
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
        except Exception as _exc:
            log_swallowed("terrain_analysis_dialog._setup_help_button", _exc)

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
                "<li><b>부호 규약 주의</b>: 본 플러그인은 <b>음(−)=볼록/수렴</b> 규약을 씁니다. "
                "Z&amp;T·ESRI에 인쇄된 공식과 GRASS <code>r.slope.aspect</code>·SAGA는 "
                "<b>반대 부호</b>(볼록=양)이므로 교차 검증 시 값의 부호가 뒤집혀 보입니다.</li>"
                "<li>실행 후 <b>해석 요약</b>(볼록/평탄/오목·수렴/평탄/발산 면적 %)을 로그와 메시지바에 표시합니다.</li>"
                "</ul>"
                "<h3>사면 파생 (모델용)</h3>"
                "<ul>"
                "<li><b>북향성</b>=cos(aspect), <b>동향성</b>=sin(aspect): 원형인 사면방향을 모델에 바로 쓰는 연속값으로.</li>"
                "<li><b>TRASP</b>(Roberts &amp; Cooper 1989): 0=북동(서늘/습) ~ 1=남서(따뜻/건조) 일사 프록시.</li>"
                "<li>실행 후 TRASP/북향 우세 등 <b>해석 요약</b>을 표시합니다.</li>"
                "</ul>"
                "<h3>TPI (Weiss 2001)</h3>"
                "<ul>"
                "<li>반경 1셀은 GDAL 3x3 TPI, 반경 2셀 이상은 <b>(2r+1)x(2r+1) 창의 정확한 초점평균</b>으로 "
                "계산합니다(중심 셀 제외, 3x3과 같은 정의). DEM NoData는 합과 개수에서 모두 빠지며, "
                "DEM 가장자리 r셀은 창이 격자를 벗어나므로 NoData입니다.</li>"
                "<li>DEM 한 변이 2r셀 이하라 온전한 창이 하나도 없으면 3x3 TPI로 대체하고 알립니다.</li>"
                "<li>자동 SD가 켜져 있으면 TPI 레이어와 지형분류 모두 TPI의 1 표준편차를 임계값으로 쓰며, "
                "레이어 이름에 실제 적용값이 표시됩니다.</li>"
                "</ul>"
                "<h3>출력</h3>"
                "<ul>"
                "<li>선택한 지표별 래스터 레이어</li>"
                "<li>(옵션) 분류/색상표 적용</li>"
                "<li>사면방향: 8방위(N=337.5-22.5°, NE, E, ... 중심 구간). 평탄 셀(경사 0)은 -1, "
                "DEM NoData와 가장자리 1셀은 NoData입니다(0은 정북).</li>"
                "</ul>"
                "<h3>팁</h3>"
                "<ul>"
                "<li>DEM이 너무 거칠면(해상도 낮음) TPI/TRI가 과도하게 튈 수 있습니다.</li>"
                "<li>TPI 자동 SD 모드는 입력 DEM 통계에 따라 임계값을 자동으로 잡습니다.</li>"
                "<li>학술 출처는 <code>REFERENCES.md</code>를 참고하세요.</li>"
                "</ul>"
            )
            show_help_dialog(parent=self, title="지형 분석 도움말", html=html, plugin_dir=plugin_dir, tool_id="terrain_analysis")
        except Exception:
            try:
                QtWidgets.QMessageBox.information(self, "도움말", "README.md를 참고하세요.")
            except Exception as _exc:
                log_swallowed("tools/terrain_analysis_dialog.py:231 (_on_help)", _exc)
    
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
            self.btnAdvanced.setText("고급 설정 ▼")
        else:
            self.btnAdvanced.setText("고급 설정 ▲")
    
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

        These 5 classes are NOT Riley, DeGloria & Elliot's (1999)
        classification. Riley publishes SEVEN classes on an absolute metre
        scale (0-80 level, 81-116 nearly level, 117-161 slightly rugged,
        162-239 intermediately rugged, 240-497 moderately rugged, 498-958
        highly rugged, 959-4367 extremely rugged). The breaks below are
        scaled to the user's own max_rugged instead, so only the INDEX is
        Riley's - the classification is this plugin's own.
        
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
        # Up to two decimals, trailing zeros dropped: '.0f' printed a threshold
        # of 1-3 as '0-0', '0-0', '0-1' (0.1/0.25/0.5 all rounded to 0).
        f1, f2, f3, f4 = (_fmt_break(t) for t in (t1, t2, t3, t4))
        return [
            {'max': t1, 'label': f'I | 0-{f1} | 평탄', 'color': '#2166ac'},
            {'max': t2, 'label': f'II | {f1}-{f2} | 거의평탄', 'color': '#67a9cf'},
            {'max': t3, 'label': f'III | {f2}-{f3} | 약간거침', 'color': '#f7f7f7'},
            {'max': t4, 'label': f'IV | {f3}-{f4} | 중간', 'color': '#ef8a62'},
            {'max': float('inf'), 'label': f'V | {f4}+ | 험준', 'color': '#b2182b'},
        ]
    
    def apply_style(self, layer, classes, max_val):
        """Apply discrete color classification"""
        color_ramp = QgsColorRampShader()
        color_ramp.setColorRampType(SHADER_DISCRETE)
        
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
        except Exception as _exc:
            log_swallowed("terrain_analysis_dialog.run_analysis", _exc)

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
            tri_radius_cells = int(self.spinTRIRadius.value())
            
            # Slope
            if self.chkSlope.isChecked():
                output = os.path.join(tempfile.gettempdir(), f'archtoolkit_slope_{run_id}.tif')
                # SCALE=1 (the toolbox default) assumes z units == horizontal
                # units; the geographic-CRS guard above is what keeps that true.
                # COMPUTE_EDGES is left at the toolbox default (False), so the
                # 1-px border stays NoData instead of a half-window estimate.
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
                    except Exception as _exc:
                        log_swallowed("terrain_analysis_dialog.run_analysis", _exc)
                    QgsProject.instance().addMapLayer(layer)
                    self.apply_style(layer, cls_info['classes'], 90)
                    results.append("경사도")
            
            # Aspect
            if self.chkAspect.isChecked():
                output = os.path.join(tempfile.gettempdir(), f'archtoolkit_aspect_{run_id}.tif')
                raw_aspect = os.path.join(tempfile.gettempdir(), f'archtoolkit_aspect_raw_{run_id}.tif')
                # ZERO_FLAT stays False: gdaldem's -zero_for_flat writes 0 for
                # flats (0 is also due north) AND for the border and every
                # NoData cell, and drops the band's NoData value, so a clipped
                # DEM's collar rendered as a "flat" class. Flats come back as
                # NoData here and are re-marked with ASPECT_FLAT_VALUE (-1) by
                # _write_flat_marked_aspect; DEM NoData stays NoData.
                # COMPUTE_EDGES stays False so the 1-px border is NoData instead
                # of a half-window guess. Both are recorded in the metadata.
                processing.run("gdal:aspect", {
                    'INPUT': dem_source, 'BAND': 1, 'TRIG_ANGLE': False, 'ZERO_FLAT': False,
                    'COMPUTE_EDGES': False, 'ZEVENBERGEN': False, 'OUTPUT': raw_aspect,
                })
                flat_marked = self._write_flat_marked_aspect(dem_source, raw_aspect, output)
                if flat_marked:
                    cleanup_files([raw_aspect])
                else:
                    output = raw_aspect
                layer = QgsRasterLayer(
                    output,
                    "사면방향_8방위 (평탄=-1)" if flat_marked else "사면방향_8방위 (평탄=NoData)",
                )
                if layer.isValid():
                    try:
                        set_archtoolkit_layer_metadata(
                            layer,
                            tool_id="terrain_analysis",
                            run_id=str(run_id),
                            kind="aspect",
                            units="deg",
                            params={
                                "zero_flat": False,
                                "compute_edges": False,
                                "flat_value": (float(ASPECT_FLAT_VALUE) if flat_marked else None),
                                "nodata": float(ASPECT_NODATA),
                                "classes": "8 directions centred on N (337.5-22.5), NE, E, SE, S, SW, W, NW",
                            },
                        )
                    except Exception as _exc:
                        log_swallowed("terrain_analysis_dialog.run_analysis", _exc)
                    QgsProject.instance().addMapLayer(layer)
                    self.apply_style(layer, self.ASPECT_CLASSES, 360)
                    results.append("사면방향")
            
            # TRI with user-defined classification threshold
            if self.chkTRI.isChecked():
                # gdaldem's TRI is fixed at 3x3 - on a 5 m DEM that is a 15 m
                # neighbourhood. A broader window is a different variable, not
                # a coarser one, so radius > 1 takes its own path and its own
                # variable name rather than quietly relabelling the 3x3.
                if tri_radius_cells > 1:
                    self.run_tri_radius_analysis(
                        dem_layer, dem_source, tri_radius_cells, tri_max, results, run_id
                    )
                else:
                    output = os.path.join(tempfile.gettempdir(), f'archtoolkit_tri_{run_id}.tif')
                    processing.run("gdal:triterrainruggednessindex", {
                        'INPUT': dem_source, 'BAND': 1, 'OUTPUT': output
                    })
                    tri_classes = self.get_tri_classes(tri_max)
                    # The INDEX is Riley's (gdaldem -alg Riley, its default);
                    # the 5 display classes are ours, scaled to tri_max. Riley's
                    # own classification is a different 7-class absolute scheme,
                    # so the name keeps index and classification apart.
                    layer_name = f"TRI (Riley et al. 1999 지수, 사용자 정의 5등급, 험준기준:{tri_max})"
                    layer = QgsRasterLayer(output, layer_name)
                    if layer.isValid():
                        try:
                            set_archtoolkit_layer_metadata(
                                layer,
                                tool_id="terrain_analysis",
                                run_id=str(run_id),
                                kind="tri",
                                units="m",
                                params={
                                    "tri_max": float(tri_max),
                                    "radius": 1,
                                    "classification": "user_scaled_5class",
                                    "classification_note": (
                                        "5 display classes scaled to tri_max; Riley et al. "
                                        "(1999) publish a different 7-class absolute (metre) "
                                        "classification"
                                    ),
                                },
                            )
                        except Exception as _exc:
                            log_swallowed("terrain_analysis_dialog.run_analysis", _exc)
                        QgsProject.instance().addMapLayer(layer)
                        self.apply_style(layer, tri_classes, tri_max * 2.5)
                        results.append("TRI")
            
            # TPI with user parameters (radius and threshold)
            if self.chkTPI.isChecked():
                self.run_tpi_analysis(dem_layer, dem_source, tpi_radius, tpi_threshold, results, run_id)
            
            # Roughness
            if self.chkRoughness.isChecked():
                output = os.path.join(tempfile.gettempdir(), f'archtoolkit_roughness_{run_id}.tif')
                # gdaldem's roughness is Wilson, O'Connell, Brown, Guinan &
                # Grehan (2007), Marine Geodesy 30(1-2), 3-35 - NOT Wilson &
                # Gallant (2000), a different work by a different author.
                processing.run("gdal:roughness", {
                    'INPUT': dem_source, 'BAND': 1, 'OUTPUT': output
                })
                layer = QgsRasterLayer(output, "Roughness (Wilson et al. 2007)")
                if layer.isValid():
                    try:
                        set_archtoolkit_layer_metadata(
                            layer,
                            tool_id="terrain_analysis",
                            run_id=str(run_id),
                            kind="roughness",
                            units="m",
                            params={
                                "classification": "plugin_defined_5class",
                                "classification_note": (
                                    "0-1 / 1-3 / 3-6 / 6-15 / 15+ m breaks are this plugin's "
                                    "display convention, not classes published by Wilson et al."
                                ),
                            },
                        )
                    except Exception as _exc:
                        log_swallowed("terrain_analysis_dialog.run_analysis", _exc)
                    QgsProject.instance().addMapLayer(layer)
                    self.apply_style(layer, self.ROUGHNESS_CLASSES, 20)
                    results.append("Roughness")
            
            # Slope Position - Weiss (2001) 6-class with user thresholds
            if self.chkSlopePosition.isChecked():
                self.run_slope_position_analysis(
                    dem_layer, dem_source, tpi_radius, slope_threshold,
                    tpi_low, tpi_high, results, run_id,
                )

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
    
    def _compute_tpi_raster(self, dem_layer, dem_source, radius, run_id, tag, scratch):
        """TPI at a user-chosen radius. Returns (path, scratch_files, effective_radius).

        gdal:tpitopographicpositionindex is fixed at 3x3. Weiss's landform
        classification is defined on a *broad-scale* TPI, so at 5 m cells a 3x3
        window classifies micro-relief rather than landform - which is why this
        is shared rather than duplicated: the standalone TPI output honoured the
        dialog's radius while the landform classification quietly did not.

        For radius > 1 the (2r+1)x(2r+1) focal mean is computed EXACTLY
        (terrain_math.focal_tpi: cumulative-sum window sums, centre excluded as
        in gdaldem's 3x3 TPI, DEM NoData left out of both sum and count, the
        outer r rows/columns NoData). It replaced a block-average + bilinear
        resample that was exact only at block centres and averaged 3x the true
        TPI on curved terrain. The DEM is processed in row strips, so memory is
        bounded by the strip, not the DEM.
        ``effective_radius`` is 1 when the exact window cannot fit the DEM (a
        side of 2r cells or fewer, so no cell has a full window) and the 3x3
        result was used instead, so the caller never claims a radius it did not
        get.

        ``scratch`` is the CALLER's list: intermediate files are appended to it
        as they are created, so if a later processing step raises, the caller's
        ``finally`` still sees and removes them. Returning the list only on
        success orphaned a temp GeoTIFF on every failed run.
        """
        output = os.path.join(tempfile.gettempdir(), f'archtoolkit_tpi_{tag}_{run_id}.tif')

        def _fallback_3x3():
            processing.run("gdal:tpitopographicpositionindex", {
                'INPUT': dem_source, 'BAND': 1, 'OUTPUT': output
            })
            return output, scratch, 1

        if radius <= 1:
            return _fallback_3x3()

        if np is None or gdal is None:
            push_message(self.iface, "알림", "NumPy/GDAL을 쓸 수 없어 3x3 TPI로 대체했습니다.",
                         level=0, duration=8)
            return _fallback_3x3()

        src = str(dem_source or "").split("|", 1)[0].strip()
        ds = gdal.Open(src, gdal.GA_ReadOnly)
        if ds is None:
            push_message(self.iface, "알림", "DEM을 GDAL로 열 수 없어 3x3 TPI로 대체했습니다.",
                         level=0, duration=8)
            return _fallback_3x3()
        rows, cols = int(ds.RasterYSize), int(ds.RasterXSize)
        # Still needed: with a side of 2r cells or fewer no cell has a full
        # (2r+1)-cell window, so the exact result would be all NoData.
        if rows <= 2 * int(radius) or cols <= 2 * int(radius):
            ds = None
            push_message(
                self.iface,
                "알림",
                f"DEM({cols}x{rows}셀)이 반경 {int(radius)}셀({2 * int(radius) + 1}셀 창)보다 작아 "
                f"3x3 TPI로 대체했습니다.",
                level=0,
                duration=8,
            )
            return _fallback_3x3()

        band = ds.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        gt = ds.GetGeoTransform()
        proj = ds.GetProjection()
        driver = gdal.GetDriverByName("GTiff")
        out_ds = driver.Create(output, cols, rows, 1, gdal.GDT_Float32, ["TILED=YES", "COMPRESS=LZW"])
        if out_ds is None:
            ds = None
            raise RuntimeError("TPI 출력 파일을 만들 수 없습니다.")
        ok = False
        try:
            out_ds.SetGeoTransform(gt)
            if proj:
                out_ds.SetProjection(proj)
            out_band = out_ds.GetRasterBand(1)
            out_band.SetNoDataValue(TPI_NODATA)

            def _read(first, stop):
                return band.ReadAsArray(0, int(first), cols, int(stop - first))

            def _write(first, block):
                out = np.where(np.isfinite(block), block, TPI_NODATA).astype("float32")
                out_band.WriteArray(out, 0, int(first))

            def _progress(_done, _total):
                QtWidgets.QApplication.processEvents()

            block_rows = max(64, int(TPI_STRIP_TARGET_BYTES // max(1, cols * 64)))
            log_message(
                f"TPI 반경 {int(radius)}셀: {2 * int(radius) + 1}x{2 * int(radius) + 1} 창 정확 초점평균"
                f" ({cols}x{rows}셀, {block_rows}행 단위)"
            )
            focal_tpi_strips(rows, cols, int(radius), _read, _write, nodata=nodata,
                             block_rows=block_rows, progress_cb=_progress)
            out_band.FlushCache()
            out_ds.FlushCache()
            ok = True
        finally:
            out_ds = None
            ds = None
            if not ok and os.path.exists(output):
                cleanup_files([output])
        return output, scratch, int(radius)

    @staticmethod
    def _tpi_window_meta(radius):
        """Metadata describing the TPI neighbourhood actually used."""
        radius = int(radius)
        if radius <= 1:
            return {
                "tpi_window": "3x3",
                "tpi_method": "gdaldem_tpi_3x3",
                "tpi_window_note": "exact 3x3 focal index (gdaldem); centre excluded",
            }
        side = 2 * radius + 1
        return {
            "tpi_window": f"{side}x{side}",
            "tpi_method": "exact_focal_mean",
            "tpi_window_note": (
                f"z minus the exact mean of the {side}x{side} window, centre cell excluded "
                "(same definition as the 3x3 gdaldem TPI); DEM NoData excluded from sum and "
                "count; outer radius rows/columns NoData"
            ),
        }

    def _tpi_auto_sd(self, tpi_path):
        """(mean, sd) of a TPI raster over its valid cells, or None."""
        try:
            tpi_layer = QgsRasterLayer(tpi_path, "TPI_temp")
            if not tpi_layer.isValid():
                return None
            stats = tpi_layer.dataProvider().bandStatistics(1)
            return float(stats.mean), float(stats.stdDev)
        except Exception as _exc:
            log_swallowed("terrain_analysis_dialog._tpi_auto_sd", _exc)
            return None

    def run_tpi_analysis(self, dem_layer, dem_source, radius, threshold, results, run_id):
        """Topographic Position Index at the radius the user chose.

        Parameters:
        - radius: neighbourhood window radius in cells (larger = broader features)
        - threshold: classification boundary for valley/flat/ridge
        """
        scratch = []
        try:
            output, _scratch, radius = self._compute_tpi_raster(
                dem_layer, dem_source, radius, run_id, "single", scratch)

            # The threshold actually applied: with 자동 SD on (the default) the
            # manual spinbox is disabled, so the layer must be classified with
            # 1 SD of THIS TPI raster - it used to keep the greyed-out value.
            threshold_mode = "manual"
            use_auto_sd = hasattr(self, 'chkAutoSD') and self.chkAutoSD.isChecked()
            if use_auto_sd:
                sd_stats = self._tpi_auto_sd(output)
                if sd_stats is not None and np is not None and np.isfinite(sd_stats[1]) and sd_stats[1] > 0:
                    threshold = float(sd_stats[1])
                    threshold_mode = "auto_sd"
                else:
                    push_message(
                        self.iface, "알림",
                        f"TPI 표준편차를 구할 수 없어 수동 임계값 ±{threshold:.2f}를 사용했습니다.",
                        level=1, duration=8,
                    )
            threshold_label = (f"±{threshold:.2f} (자동 1 SD)" if threshold_mode == "auto_sd"
                               else f"±{threshold:.2f}")
            tpi_classes = self.get_tpi_classes(threshold)
            if radius > 1:
                side = 2 * int(radius) + 1
                layer_name = f"TPI (반경 {radius}셀, {side}x{side} 창, 임계값:{threshold_label})"
            else:
                # radius 1 (or a radius that fell back) is gdaldem's fixed 3x3.
                layer_name = f"TPI (창:3x3, 임계값:{threshold_label})"
            layer = QgsRasterLayer(output, layer_name)

            if layer.isValid():
                try:
                    params = {
                        "radius": int(radius),
                        "threshold": float(threshold),
                        "threshold_mode": threshold_mode,
                    }
                    # The layer name advertises a radius, so the metadata has to
                    # state the window and method actually used - the same
                    # disclosure the landform layer carries.
                    params.update(self._tpi_window_meta(radius))
                    set_archtoolkit_layer_metadata(
                        layer,
                        tool_id="terrain_analysis",
                        run_id=str(run_id),
                        kind="tpi",
                        units="m",
                        params=params,
                    )
                except Exception as _exc:
                    log_swallowed("terrain_analysis_dialog.run_tpi_analysis", _exc)
                QgsProject.instance().addMapLayer(layer)
                self.apply_style(layer, tpi_classes, 10)
                results.append("TPI")
            
        except Exception as e:
            self.iface.messageBar().pushMessage("경고", f"TPI 분석 오류: {str(e)}", level=1)
        finally:
            cleanup_files(scratch)
    
    def run_slope_position_analysis(self, dem_layer, dem_source, tpi_radius, slope_thresh,
                                    tpi_low, tpi_high, results, run_id):
        """Run Weiss (2001) 6-class Landform Classification using GDAL with user thresholds
        
        Parameters:
        - tpi_radius: TPI neighbourhood radius in cells. Weiss defines the
          classification on a BROAD-scale TPI; this used to be hard-wired to
          gdaldem's 3x3 while the dialog's own radius control was ignored, so
          at 5 m cells it classified 15 m micro-relief as landform.
        - slope_thresh: Degree threshold for flat vs sloped areas (e.g., 5°)
        - tpi_low: TPI threshold for valley classification (e.g., -1.0)
        - tpi_high: TPI threshold for ridge classification (e.g., 1.0)
        
        Classification Logic:
        1. 곡저 (Valley): TPI < tpi_low
        2. 하부 사면 (Lower Slope): tpi_low <= TPI < tpi_low/2
        3. 평지/단구 (Flat or Terrace): |TPI| <= |tpi_low/2| and Slope <= slope_thresh
        4. 중간 사면 (Mid Slope): |TPI| <= |tpi_high/2| and Slope > slope_thresh
        5. 상부 사면 (Upper Slope): tpi_high/2 < TPI <= tpi_high
        6. 능선 (Ridge): TPI > tpi_high
        """
        # Assigned inside try; predefine so the finally-cleanup never hits
        # an unbound name (which would mask the original error).
        tpi_path = None
        slope_path = None
        tpi_scratch = []
        try:
            # 1. TPI at the radius the user asked for, not a fixed 3x3.
            tpi_path, _scratch, tpi_radius = self._compute_tpi_raster(
                dem_source=dem_source, dem_layer=dem_layer, radius=tpi_radius,
                run_id=run_id, tag="landform", scratch=tpi_scratch)
            
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
            threshold_mode = "manual"
            if use_auto_sd:
                sd_stats = self._tpi_auto_sd(tpi_path)
                if sd_stats is not None:
                    tpi_mean, tpi_sd = sd_stats
                    threshold_mode = "auto_sd"
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
                radius_label = ("3x3" if tpi_radius <= 1 else
                                f"반경 {tpi_radius}셀 {2 * int(tpi_radius) + 1}x{2 * int(tpi_radius) + 1} 창")
                layer_name = (f"지형분류 (TPI {radius_label}, 경사:{slope_thresh}°, "
                              f"TPI:{tpi_low:.1f}-{tpi_high:.1f})")
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
                                "tpi_radius_cells": int(tpi_radius),
                                # State the real window and method, not only the radius.
                                **self._tpi_window_meta(tpi_radius),
                                "threshold_mode": threshold_mode,
                                "slope_thresh_deg": float(slope_thresh),
                                "tpi_low": float(tpi_low),
                                "tpi_high": float(tpi_high),
                            },
                        )
                    except Exception as _exc:
                        log_swallowed("terrain_analysis_dialog.run_slope_position_analysis", _exc)
                    # Class 0 = masked NoData -> transparent
                    try:
                        layer.dataProvider().setNoDataValue(1, 0)
                    except Exception as _exc:
                        log_swallowed("terrain_analysis_dialog.run_slope_position_analysis", _exc)
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
            cleanup_files([tpi_path, slope_path] + list(tpi_scratch))

    def run_tri_radius_analysis(self, dem_layer, dem_source, radius, tri_max, results, run_id):
        """Ruggedness over a (2r+1)x(2r+1) window, for landscape-scale questions.

        gdaldem's TRI is fixed at 3x3. On a 5 m DEM that is a 15 m
        neighbourhood, which describes micro-relief; a model asking about
        ruggedness at, say, 65 m needs a genuinely wider window. The result is
        the RMS elevation difference from the centre cell - Riley's index
        normalised by sqrt(N) - so values stay comparable across radii. It is
        published as its own variable (`tri_radius`) because its units differ
        from the 3x3 product and silently swapping them would make two runs
        look comparable when they are not.
        """
        try:
            ds = gdal.Open(dem_source, gdal.GA_ReadOnly)
            if ds is None:
                push_message(self.iface, "경고", "DEM을 열 수 없습니다(TRI 반경).", level=1)
                return
            band = ds.GetRasterBand(1)

            # Cost is O(n * (2r+1)^2) - there is no summed-area shortcut for a
            # difference taken against the centre cell - so guard on the
            # product, not the pixel count alone. 2e9 cell-visits is a few tens
            # of seconds; beyond that the dialog would look hung.
            npx = int(ds.RasterXSize) * int(ds.RasterYSize)
            window_cells = (2 * int(radius) + 1) ** 2
            if npx * window_cells > 2_000_000_000:
                suggested = max(1, int((2_000_000_000 / max(1, npx)) ** 0.5 - 1) // 2)
                push_message(
                    self.iface,
                    "경고",
                    f"DEM {npx:,} 픽셀에 반경 {radius}셀은 너무 큽니다. "
                    f"반경을 {suggested}셀 이하로 줄이거나 DEM을 클립하세요.",
                    level=1,
                    duration=10,
                )
                ds = None
                return
            # Time is not the only bound. tri_radius holds the float64 grid
            # plus shifted/difference/accumulator temporaries - measured at
            # ~67 B/px - all on the GUI thread, so a DEM the time guard admits
            # (small radius, huge grid) can still want gigabytes. Check it
            # against what the machine reports, the way the cost surface does.
            bytes_needed = npx * TRI_RADIUS_BYTES_PER_PIXEL
            available = cost_budget.available_memory_bytes()
            allowed = (available if available is not None
                       else cost_budget.ASSUMED_AVAILABLE_BYTES) * cost_budget.MEMORY_SAFETY_FRACTION
            if bytes_needed > allowed:
                push_message(
                    self.iface,
                    "경고",
                    f"DEM {npx:,} 픽셀의 TRI 반경 계산에 약 {bytes_needed / 1024 ** 3:.1f}GB가 "
                    f"필요한데 가용 메모리가 부족합니다"
                    + (f" (가용 약 {available / 1024 ** 3:.1f}GB)." if available else ".")
                    + " DEM을 클립하거나 리샘플하세요.",
                    level=1,
                    duration=10,
                )
                ds = None
                return

            z = band.ReadAsArray()
            gt = ds.GetGeoTransform()
            proj = ds.GetProjection()
            nodata = band.GetNoDataValue()
            ds = None
            if z is None or z.ndim != 2:
                push_message(self.iface, "경고", "DEM 배열을 읽을 수 없습니다(TRI 반경).", level=1)
                return
            if z.shape[0] <= 2 * radius or z.shape[1] <= 2 * radius:
                push_message(
                    self.iface, "경고",
                    f"DEM이 반경 {radius}셀 창보다 작습니다(TRI 반경).", level=1,
                )
                return

            z = z.astype("float64")
            nodata_mask = None
            if nodata is not None:
                nodata_mask = (z == nodata)

            cell = (abs(float(gt[1])) + abs(float(gt[5]))) / 2.0
            log_message(
                f"TRI 반경 계산: {npx:,}픽셀 x {window_cells}셀 창 (반경 {radius}셀"
                + (f" ≈ {radius * cell:.0f}m)" if cell > 0 else ")")
            )

            # Runs on the GUI thread for up to tens of seconds, so keep the
            # interface alive and give the user a way out. The dialog would
            # otherwise sit unresponsive until the OS calls QGIS "not
            # responding".
            progress = QtWidgets.QProgressDialog(
                f"TRI 반경 {radius}셀 계산 중…", "취소", 0, window_cells - 1, self)
            progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(500)

            def _progress(done, total):
                progress.setValue(done)
                QtWidgets.QApplication.processEvents()

            try:
                result = tri_radius(
                    z, int(radius), nodata_mask=nodata_mask,
                    progress_cb=_progress, cancel_check=progress.wasCanceled,
                )
            finally:
                progress.close()
            if result is None:
                push_message(self.iface, "TRI 반경", "취소됨: 결과를 만들지 않았습니다.",
                             level=1, duration=6)
                return

            nd = -9999.0
            out = np.where(np.isfinite(result), result, nd).astype("float32")
            path = os.path.join(
                tempfile.gettempdir(), f'archtoolkit_tri_r{int(radius)}_{run_id}.tif'
            )
            self._write_geotiff(path, out, gt, proj, nd)

            distance_label = f"≈{radius * cell:.0f}m" if cell > 0 else f"{radius}셀"
            layer = QgsRasterLayer(path, f"TRI 반경 {radius}셀 ({distance_label}, RMS 고도차)")
            if not layer.isValid():
                push_message(self.iface, "경고", "TRI 반경 결과를 열 수 없습니다.", level=1)
                return
            try:
                set_archtoolkit_layer_metadata(
                    layer,
                    tool_id="terrain_analysis",
                    run_id=str(run_id),
                    kind="tri_radius",
                    units="m",
                    params={
                        "radius_cells": int(radius),
                        "radius_m": float(radius * cell) if cell > 0 else None,
                        "statistic": "rms_elevation_difference_from_centre",
                        "note": "Riley (1999) normalised by sqrt(N); not comparable to the 3x3 TRI",
                    },
                )
            except Exception as _exc:
                log_swallowed("terrain_analysis_dialog.run_tri_radius_analysis", _exc)
            QgsProject.instance().addMapLayer(layer)
            valid_vals = result[np.isfinite(result)]
            if valid_vals.size:
                self._apply_sequential_style(
                    layer, float(np.nanpercentile(valid_vals, 2)),
                    float(np.nanpercentile(valid_vals, 98)),
                    "평탄 smooth", "험준 rugged",
                )
            results.append(f"TRI(반경 {radius}셀)")
        except Exception as e:
            push_message(self.iface, "경고", f"TRI 반경 분석 오류: {str(e)}", level=1)

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
            # Read, then check, then cast: ReadAsArray() returns None on a failed
            # read, so casting first turned that into an AttributeError and left
            # the None branch below unreachable.
            z = band.ReadAsArray()
            gt = ds.GetGeoTransform()
            proj = ds.GetProjection()
            nodata = band.GetNoDataValue()
            ds = None
            if z is None or z.ndim != 2:
                push_message(self.iface, "경고", "DEM 배열을 읽을 수 없습니다(곡률).", level=1)
                return
            z = z.astype("float32")

            # Separate x/y spacing: one mean size scaled the second
            # derivatives wrongly on non-square pixels (10 x 5 m: ~1.9x).
            cell_x = abs(float(gt[1]))
            cell_y = abs(float(gt[5]))
            if cell_x <= 0 or cell_y <= 0:
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
            except Exception as _exc:
                log_swallowed("terrain_analysis_dialog.run_curvature_analysis", _exc)

            profile, plan = self._zt_curvature(z, cell_x, cell_y)

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
                # The sign convention belongs in the name: users cross-checking
                # against GRASS/SAGA (convex = positive) otherwise see every value
                # inverted with nothing on the layer to explain it.
                (prof_path, "곡률-종단 profile (Z&T 1987, 부호규약: 음=볼록)", "curvature_profile",
                 profile, "볼록 convex (침식 경향)", "오목 concave (퇴적 경향)"),
                (plan_path, "곡률-횡단 plan (Z&T 1987, 부호규약: 음=수렴)", "curvature_plan",
                 plan, "수렴 convergent (물모임)", "발산 divergent (능선)"),
            ):
                layer = QgsRasterLayer(path, name)
                if not layer.isValid():
                    continue
                try:
                    set_archtoolkit_layer_metadata(
                        layer, tool_id="terrain_analysis", run_id=str(run_id),
                        kind=kind, units="1/m",
                        params={
                            "method": "Zevenbergen & Thorne 1987",
                            "cell_size": float(cell_x),
                            "cell_size_y": float(cell_y),
                            "sign_convention": (
                                "negative = convex (profile) / convergent (plan); this is the "
                                "NEGATION of the Z&T formula as printed by ESRI and most "
                                "textbooks, and GRASS r.slope.aspect / SAGA use the opposite sign"
                            ),
                        },
                    )
                except Exception as _exc:
                    log_swallowed("terrain_analysis_dialog.run_curvature_analysis", _exc)
                QgsProject.instance().addMapLayer(layer)
                self._apply_diverging_style(layer, arr[good], neg_lab, pos_lab)

            self._log_curvature_summary(profile[good], plan[good])
            results.append("곡률")
        except Exception as e:
            push_message(self.iface, "경고", f"곡률 분석 오류: {str(e)}", level=1)

    def _zt_curvature(self, z, cell, cell_y=None):
        """Zevenbergen & Thorne (1987) profile/plan curvature. See run_curvature_analysis
        for the (verified) sign convention. ``cell_y`` defaults to ``cell``."""
        return zt_curvature(z, cell, cell_y)

    def _write_flat_marked_aspect(self, dem_source, raw_path, out_path):
        """Write the aspect raster with flats as ASPECT_FLAT_VALUE and NoData flagged.

        ``raw_path`` is gdaldem aspect run without -zero_for_flat, where flats
        and uncomputable cells share the NoData value. A cell whose whole 3x3
        DEM window is valid can only be NoData there because it is flat
        (terrain_math.mark_flat_aspect). Returns False - and the caller keeps
        the raw raster, flats left as NoData - when the arrays cannot be read
        or the DEM is beyond the same 1.2e8-pixel cap as the other array paths.
        """
        if np is None or gdal is None:
            return False
        try:
            ads = gdal.Open(raw_path, gdal.GA_ReadOnly)
            if ads is None:
                return False
            npx = int(ads.RasterXSize) * int(ads.RasterYSize)
            if npx > 120_000_000:
                log_message(
                    f"사면방향: DEM이 커서({npx:,} 픽셀) 평탄 셀을 따로 표시하지 않고 NoData로 둡니다."
                )
                ads = None
                return False
            aband = ads.GetRasterBand(1)
            aspect = aband.ReadAsArray()
            a_nd = aband.GetNoDataValue()
            gt = ads.GetGeoTransform()
            proj = ads.GetProjection()
            ads = None
            src = str(dem_source or "").split("|", 1)[0].strip()
            dds = gdal.Open(src, gdal.GA_ReadOnly)
            if dds is None or aspect is None:
                return False
            dband = dds.GetRasterBand(1)
            zarr = dband.ReadAsArray()
            d_nd = dband.GetNoDataValue()
            dds = None
            if zarr is None or zarr.shape != aspect.shape:
                return False
            dem_valid = np.isfinite(zarr)
            if d_nd is not None:
                dem_valid &= (zarr != d_nd)
            del zarr
            marked = mark_flat_aspect(aspect, dem_valid, a_nd, out_nodata=ASPECT_NODATA)
            self._write_geotiff(out_path, marked.astype("float32"), gt, proj, ASPECT_NODATA)
            return os.path.exists(out_path)
        except Exception as _exc:
            log_swallowed("terrain_analysis_dialog._write_flat_marked_aspect", _exc)
            return False

    def _write_geotiff(self, out_path, arr, gt, proj, nodata):
        write_single_band_geotiff(
            out_path,
            arr,
            geotransform=gt,
            projection=proj,
            nodata=nodata,
            gdal_type=gdal.GDT_Float32,
            options=("COMPRESS=LZW",),
        )

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
            ramp.setColorRampType(SHADER_INTERPOLATED)
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
        except Exception as _exc:
            log_swallowed("terrain_analysis_dialog._apply_diverging_style", _exc)

    def _log_curvature_summary(self, profile_valid, plan_valid):
        """Emit an interpretation (area % per curvature class) to the live log + message bar.

        The 평탄 band is |curvature| < 0.1 * std of THIS DEM, so the percentages
        are relative to each DEM's own variability and are not comparable between
        areas. The message therefore carries the rule and the actual eps values,
        and names erosion/deposition as tendencies rather than determinations.
        """
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
                f"곡률 해석 — 종단: 볼록(침식 경향) {convex:.1f}% / 평탄 {flat_p:.1f}% / "
                f"오목(퇴적 경향) {concave:.1f}% | "
                f"횡단: 수렴(물모임) {converg:.1f}% / 평탄 {flat_c:.1f}% / 발산(능선) {diverg:.1f}% | "
                f"'평탄' 기준: 해당 DEM 자체 표준편차의 0.1배(0.1σ) — 종단 ±{eps_p:.4g}, 횡단 ±{eps_c:.4g} "
                f"(DEM마다 달라지므로 지역 간 % 직접 비교는 불가)"
            )
            log_message(msg)
            push_message(self.iface, "곡률 해석", msg, level=0, duration=12)
        except Exception as _exc:
            log_swallowed("terrain_analysis_dialog._log_curvature_summary", _exc)

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
            # COMPUTE_EDGES=True overrides the QGIS toolbox default (False): with
            # the default the 1-px border returns as 'undefined aspect', and the
            # flat/NoData split below would read it as a true flat and fabricate
            # neutral 0 / 0.5 values all around the DEM. ZERO_FLAT stays at the
            # toolbox default (False) because flats must stay distinguishable to
            # get the neutral value, not 0 deg (= due north).
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
            # Read, then check, then cast: ReadAsArray() returns None on a failed
            # read, so casting first turned that into an AttributeError instead of
            # the user-facing message below.
            aspect = aband.ReadAsArray()
            gt = ads.GetGeoTransform()
            proj = ads.GetProjection()
            a_nd = aband.GetNoDataValue()
            ads = None
            if aspect is None or aspect.ndim != 2:
                push_message(self.iface, "경고", "사면방향 래스터 배열을 읽을 수 없습니다(사면 파생).", level=1)
                return
            aspect = aspect.astype("float32")

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
                        params={
                            "source": "aspect",
                            "flat_handling": "north/east=0, TRASP=0.5",
                            "compute_edges": True,
                            "zero_flat": False,
                        },
                    )
                except Exception as _exc:
                    log_swallowed("tools/terrain_analysis_dialog.py:1238 (run_aspect_derivatives)", _exc)
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
            ramp.setColorRampType(SHADER_INTERPOLATED)
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
        except Exception as _exc:
            log_swallowed("terrain_analysis_dialog._apply_sequential_style", _exc)

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
        except Exception as _exc:
            log_swallowed("terrain_analysis_dialog._log_aspect_summary", _exc)
