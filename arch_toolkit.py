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
from qgis.PyQt.QtGui import QAction
from qgis.PyQt.QtWidgets import QMenu, QToolButton, QMessageBox

from .tools.utils import log_exception, log_swallowed, start_ui_log_pump, stop_ui_log_pump
from .tools.icons import MAIN_ICON, icon
import os.path

class ArchToolkit:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu_name = u'Archaeology Toolkit'
        self.toolbar = None
        self.main_action = None
        self.viewshed_dlg = None  # Persistent reference for marker cleanup
        self.cost_dlg = None  # Persistent reference for temp/preview cleanup
        self.profile_dlg = None  # Persistent reference for multi-profile selection/view
        self.geochem_dlg = None  # Optional: keep reference if we later add temp cleanup
        self.geology_zip_dlg = None

    def initGui(self):
        try:
            # Enable real-time logs in the QGIS "Log Messages" panel.
            try:
                start_ui_log_pump()
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:43 (initGui)", _exc)

            # 1. Create Actions for all tools (icons: tools/icons.py -> icons/)
            mw = self.iface.mainWindow()

            self.dem_action = QAction(icon("dem.png"), u"DEM 생성 (Generate DEM)", mw)
            self.dem_action.triggered.connect(self.run_dem_tool)

            self.contour_action = QAction(icon("contour.png"), u"등고선 추출 (Extract Contours)", mw)
            self.contour_action.triggered.connect(self.run_contour_tool)

            self.cad_overlap_action = QAction(icon("cadastral.png"), u"지적도 중첩 면적표 (Cadastral Overlap)", mw)
            self.cad_overlap_action.triggered.connect(self.run_cadastral_overlap_tool)

            self.terrain_action = QAction(icon("terrain.png"), u"지형 분석 (Terrain Analysis)", mw)
            self.terrain_action.triggered.connect(self.run_terrain_tool)

            self.align_export_action = QAction(icon("align_export.xpm"), u"분석 결과 정렬/내보내기 (Align & Export Stack)", mw)
            self.align_export_action.triggered.connect(self.run_align_export_tool)

            self.cov_report_action = QAction(icon("covariate.png", "terrain.png"), u"변수 상관/VIF 리포트 (Correlation & VIF)", mw)
            self.cov_report_action.triggered.connect(self.run_cov_report_tool)

            # Distance to features: the most widely used predictor family in
            # archaeological modelling.
            self.distance_action = QAction(icon("cost.png"), u"거리 래스터 (Distance to Features)", mw)
            self.distance_action.triggered.connect(self.run_distance_raster_tool)

            self.ahp_action = QAction(icon("ahp.png"), u"AHP 입지적합도 (AHP Suitability)", mw)
            self.ahp_action.triggered.connect(self.run_ahp_tool)

            self.geochem_action = QAction(icon("geochem.png"), u"지구화학도 래스터 수치화 (GeoChem WMS → Raster)", mw)
            self.geochem_action.triggered.connect(self.run_geochem_tool)

            self.geology_zip_action = QAction(icon("geochem.png"), u"지질도 도엽 ZIP 불러오기/래스터 변환 (KIGAM)", mw)
            self.geology_zip_action.triggered.connect(self.run_geology_zip_tool)

            self.ai_report_action = QAction(icon("ai_report.png"), u"AI 조사요약 (AOI Report)", mw)
            self.ai_report_action.triggered.connect(self.run_ai_report_tool)

            self.profile_action = QAction(icon("profile.png"), u"지형 단면 (Terrain Profile)", mw)
            self.profile_action.triggered.connect(self.run_profile_tool)

            self.cost_action = QAction(icon("cost.png"), u"비용표면/최소비용경로 (Cost Surface / LCP)", mw)
            self.cost_action.triggered.connect(self.run_cost_tool)

            self.network_action = QAction(icon("network.png", "cost.png"), u"최소비용 네트워크 (Least-cost Network)", mw)
            self.network_action.triggered.connect(self.run_network_tool)

            self.spatial_network_action = QAction(
                icon("spatial_network.png", "network.png"), u"근접/가시성 네트워크 (PPA / Visibility)", mw
            )
            self.spatial_network_action.triggered.connect(self.run_spatial_network_tool)

            self.style_action = QAction(icon("styling.png"), u"도면 시각화 (Map Styling)", mw)
            self.style_action.triggered.connect(self.run_styling_tool)

            self.drafting_action = QAction(icon("slope_aspect.png", "styling.png"), u"경사도/사면방향 도면화 (Slope/Aspect Drafting)", mw)
            self.drafting_action.triggered.connect(self.run_drafting_tool)

            # icons/trench.png is drawn by scripts/make_tool_icons.py; the plugin icon is the fallback.
            self.trench_action = QAction(icon("trench.png", "archtoolkit.png"), u"트렌치 후보 제안 (Trench Suggestion)", mw)
            self.trench_action.triggered.connect(self.run_trench_tool)

            self.viewshed_action = QAction(icon("viewshed.png"), u"가시권 분석 (Viewshed Analysis)", mw)
            self.viewshed_action.triggered.connect(self.run_viewshed_tool)

            # Track actions BEFORE any menu/toolbar registration: if a later
            # step throws, unload() can still remove what was already added
            # (previously self.actions stayed empty and menu entries dangled).
            self.actions = [
                self.dem_action, self.contour_action, self.cad_overlap_action,
                self.terrain_action, self.distance_action, self.align_export_action,
                self.cov_report_action, self.ahp_action,
                self.geochem_action, self.geology_zip_action,
                self.profile_action, self.cost_action, self.network_action,
                self.spatial_network_action, self.style_action, self.drafting_action,
                self.trench_action, self.viewshed_action,
                self.ai_report_action,
            ]

            # 2. Add to Plugin Menu
            self.iface.addPluginToMenu(self.menu_name, self.dem_action)
            self.iface.addPluginToMenu(self.menu_name, self.contour_action)
            self.iface.addPluginToMenu(self.menu_name, self.cad_overlap_action)
            self.iface.addPluginToMenu(self.menu_name, self.terrain_action)
            self.iface.addPluginToMenu(self.menu_name, self.align_export_action)
            self.iface.addPluginToMenu(self.menu_name, self.distance_action)
            self.iface.addPluginToMenu(self.menu_name, self.cov_report_action)
            self.iface.addPluginToMenu(self.menu_name, self.ahp_action)
            self.iface.addPluginToMenu(self.menu_name, self.geochem_action)
            self.iface.addPluginToMenu(self.menu_name, self.geology_zip_action)
            self.iface.addPluginToMenu(self.menu_name, self.profile_action)
            self.iface.addPluginToMenu(self.menu_name, self.cost_action)
            self.iface.addPluginToMenu(self.menu_name, self.network_action)
            self.iface.addPluginToMenu(self.menu_name, self.spatial_network_action)
            self.iface.addPluginToMenu(self.menu_name, self.style_action)
            self.iface.addPluginToMenu(self.menu_name, self.drafting_action)
            self.iface.addPluginToMenu(self.menu_name, self.viewshed_action)
            # AI/assistant tools should sit at the bottom.
            self.iface.addPluginToMenu(self.menu_name, self.trench_action)
            self.iface.addPluginToMenu(self.menu_name, self.ai_report_action)

            # 3. Create Dedicated Toolbar for Visibility
            self.toolbar = self.iface.addToolBar(u"ArchToolkit")
            self.toolbar.setObjectName("ArchToolkit")

            # 4. Create Unified Toolkit Button
            main_icon = icon(MAIN_ICON)
            self.main_action = QAction(main_icon, u"ArchToolkit", self.iface.mainWindow())
            
            # Create Dropdown Menu
            self.tool_menu = QMenu(self.iface.mainWindow())
            # Title header so the dropdown clearly reads "ArchToolkit" at the top
            # (a disabled action renders as a non-clickable heading on all styles).
            self.menu_title_action = self.tool_menu.addAction(main_icon, u"ArchToolkit")
            self.menu_title_action.setEnabled(False)
            try:
                title_font = self.menu_title_action.font()
                title_font.setBold(True)
                self.menu_title_action.setFont(title_font)
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:299 (initGui)", _exc)
            self.tool_menu.addSeparator()
            self.tool_menu.addAction(self.dem_action)
            self.tool_menu.addAction(self.contour_action)
            self.tool_menu.addAction(self.cad_overlap_action)
            self.tool_menu.addSeparator()
            self.tool_menu.addAction(self.terrain_action)
            self.tool_menu.addAction(self.align_export_action)
            self.tool_menu.addAction(self.distance_action)
            self.tool_menu.addAction(self.cov_report_action)
            self.tool_menu.addAction(self.ahp_action)
            self.tool_menu.addAction(self.geochem_action)
            self.tool_menu.addAction(self.geology_zip_action)
            self.tool_menu.addAction(self.profile_action)
            self.tool_menu.addAction(self.viewshed_action)
            self.tool_menu.addAction(self.cost_action)
            self.tool_menu.addAction(self.network_action)
            self.tool_menu.addAction(self.spatial_network_action)
            self.tool_menu.addSeparator()
            self.tool_menu.addAction(self.style_action)
            self.tool_menu.addAction(self.drafting_action)
            self.tool_menu.addSeparator()
            self.tool_menu.addAction(self.trench_action)
            self.tool_menu.addAction(self.ai_report_action)
             
            self.main_action.setMenu(self.tool_menu)
            
            # Add QToolButton to toolbar for instant popup support
            tool_button = QToolButton()
            tool_button.setDefaultAction(self.main_action)
            tool_button.setMenu(self.tool_menu)
            tool_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            
            self.toolbar.addWidget(tool_button)
            
            # main_action joins the cleanup list last (tool actions were
            # already tracked before menu registration above).
            self.actions.append(self.main_action)
        except Exception as e:
            log_exception("ArchToolkit initGui error", e)
            QMessageBox.critical(self.iface.mainWindow(), "ArchToolkit 로드 오류", f"플러그인을 초기화하는 중 오류가 발생했습니다: {str(e)}")

    def unload(self):
        # Remove from menu
        for action in self.actions:
            try:
                self.iface.removePluginMenu(self.menu_name, action)
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:347 (unload)", _exc)

        try:
            stop_ui_log_pump()
        except Exception as _exc:
            log_swallowed("arch_toolkit.py:352 (unload)", _exc)

        # Close persistent dialogs and disconnect long-lived signals (prevents stale callbacks after reload)
        if self.viewshed_dlg is not None:
            try:
                if hasattr(self.viewshed_dlg, "cleanup_for_unload"):
                    self.viewshed_dlg.cleanup_for_unload()
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:360 (unload)", _exc)
            try:
                self.viewshed_dlg.close()
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:364 (unload)", _exc)
            try:
                self.viewshed_dlg.deleteLater()
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:368 (unload)", _exc)
            self.viewshed_dlg = None

        if self.cost_dlg is not None:
            try:
                if hasattr(self.cost_dlg, "cleanup_for_unload"):
                    self.cost_dlg.cleanup_for_unload()
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:376 (unload)", _exc)
            try:
                self.cost_dlg.close()
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:380 (unload)", _exc)
            try:
                self.cost_dlg.deleteLater()
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:384 (unload)", _exc)
            self.cost_dlg = None

        if self.profile_dlg is not None:
            try:
                if hasattr(self.profile_dlg, "cleanup_for_unload"):
                    self.profile_dlg.cleanup_for_unload()
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:392 (unload)", _exc)
            try:
                self.profile_dlg.close()
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:396 (unload)", _exc)
            try:
                self.profile_dlg.deleteLater()
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:400 (unload)", _exc)
            self.profile_dlg = None
             
        # Remove toolbar cleanly from mainWindow
        if self.toolbar:
            try:
                self.iface.mainWindow().removeToolBar(self.toolbar)
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:408 (unload)", _exc)
            try:
                self.toolbar.deleteLater()
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:412 (unload)", _exc)
            self.toolbar = None

        # The dropdown menu, its title action and every QAction are parented to
        # mainWindow(), so they survive unload unless explicitly deleted — each
        # reload otherwise accumulates a QMenu + ~20 QActions whose signal
        # connections keep the stale plugin instance (and modules) alive.
        try:
            if getattr(self, "tool_menu", None) is not None:
                self.tool_menu.deleteLater()
                self.tool_menu = None
        except Exception as _exc:
            log_swallowed("arch_toolkit.py:424 (unload)", _exc)
        try:
            if getattr(self, "menu_title_action", None) is not None:
                self.menu_title_action.deleteLater()
                self.menu_title_action = None
        except Exception as _exc:
            log_swallowed("arch_toolkit.py:430 (unload)", _exc)
        for action in list(self.actions or []):
            try:
                action.deleteLater()
            except Exception as _exc:
                log_swallowed("arch_toolkit.py:435 (unload)", _exc)
        self.actions = []

    def run_dem_tool(self):
        try:
            from .tools.dem_generator_dialog import DemGeneratorDialog
            dlg = DemGeneratorDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("DEM tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_contour_tool(self):
        try:
            from .tools.contour_extractor_dialog import ContourExtractorDialog
            dlg = ContourExtractorDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("Contour tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_cadastral_overlap_tool(self):
        try:
            from .tools.cadastral_overlap_dialog import CadastralOverlapDialog

            dlg = CadastralOverlapDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("Cadastral overlap tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_terrain_tool(self):
        try:
            from .tools.terrain_analysis_dialog import TerrainAnalysisDialog
            dlg = TerrainAnalysisDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("Terrain tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_ahp_tool(self):
        try:
            from .tools.ahp_suitability_dialog import AhpSuitabilityDialog

            dlg = AhpSuitabilityDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("AHP tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_align_export_tool(self):
        try:
            from .tools.align_export_dialog import AlignExportDialog

            dlg = AlignExportDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("Align & export tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_cov_report_tool(self):
        try:
            from .tools.covariate_report_dialog import CovariateReportDialog

            dlg = CovariateReportDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("Covariate report tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_distance_raster_tool(self):
        try:
            from .tools.distance_raster_dialog import DistanceRasterDialog

            dlg = DistanceRasterDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("Distance raster tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_profile_tool(self):
        try:
            from .tools.terrain_profile_dialog import TerrainProfileDialog
            if self.profile_dlg is None:
                self.profile_dlg = TerrainProfileDialog(self.iface)
            # Non-modal: lets users click/choose saved profile lines on the map.
            self.profile_dlg.show()
            self.profile_dlg.raise_()
            self.profile_dlg.activateWindow()
        except Exception as e:
            log_exception("Terrain profile tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_geochem_tool(self):
        try:
            from .tools.geochem_polygonize_dialog import GeoChemPolygonizeDialog

            dlg = GeoChemPolygonizeDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("GeoChem tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_geology_zip_tool(self):
        try:
            from .tools.geology_zip_dialog import GeologyZipDialog

            dlg = GeologyZipDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("KIGAM geology tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_ai_report_tool(self):
        try:
            from .tools.ai_report_dialog import AiAoiReportDialog

            dlg = AiAoiReportDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("AI AOI report tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_styling_tool(self):
        try:
            from .tools.map_styling_dialog import MapStylingDialog
            dlg = MapStylingDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("Map styling tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_drafting_tool(self):
        try:
            from .tools.slope_aspect_drafting_dialog import SlopeAspectDraftingDialog
            dlg = SlopeAspectDraftingDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("Slope/aspect drafting tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_trench_tool(self):
        try:
            from .tools.trench_suggestion_dialog import TrenchSuggestionDialog
            dlg = TrenchSuggestionDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("Trench suggestion tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구 실행 중 오류가 발생했습니다: {str(e)}")

    def run_cost_tool(self):
        try:
            if self.cost_dlg is None:
                from .tools.cost_surface_dialog import CostSurfaceDialog
                self.cost_dlg = CostSurfaceDialog(self.iface)
            self.cost_dlg.exec()
        except Exception as e:
            log_exception("Cost surface tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")

    def run_network_tool(self):
        try:
            from .tools.cost_network_dialog import CostNetworkDialog
            dlg = CostNetworkDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("Least-cost network tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구 실행 중 오류가 발생했습니다: {str(e)}")

    def run_spatial_network_tool(self):
        try:
            from .tools.spatial_network_dialog import SpatialNetworkDialog
            dlg = SpatialNetworkDialog(self.iface)
            dlg.exec()
        except Exception as e:
            log_exception("Spatial network tool error", e)
            QMessageBox.critical(
                self.iface.mainWindow(),
                "오류",
                f"도구 실행 중 오류가 발생했습니다: {str(e)}",
            )

    def run_viewshed_tool(self):
        try:
            # Maintain persistent dialog instance so layersRemoved signal persists
            if self.viewshed_dlg is None:
                from .tools.viewshed_dialog import ViewshedDialog
                self.viewshed_dlg = ViewshedDialog(self.iface)
            
            # Show the dialog. exec_() is modal and blocks until closed.
            # In a future version we might switch to .show() for non-modal interaction.
            self.viewshed_dlg.exec()
        except Exception as e:
            log_exception("Viewshed tool error", e)
            QMessageBox.critical(self.iface.mainWindow(), "오류", f"도구를 여는 중 오류가 발생했습니다: {str(e)}")
