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
from dataclasses import dataclass
from functools import partial
from importlib import import_module
import os.path

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QActionGroup, QMenu, QToolButton, QMessageBox

from .tools.i18n import apply_language, get_ui_language, install_runtime_i18n_hooks, set_ui_language, tr
from .tools.utils import log_exception, start_ui_log_pump, stop_ui_log_pump


@dataclass(frozen=True)
class ToolSpec:
    key: str
    action_attr: str
    text: str
    icon_candidates: tuple
    menu_group: str
    dialog_module: str
    dialog_class: str
    log_label: str
    persistent_attr: str = None
    modal: bool = True
    error_operation: str = "여는"


def _translate_error_operation(operation: str) -> str:
    if get_ui_language() == "en":
        return {
            "여는": "opening",
            "실행": "running",
        }.get(operation, tr(operation))
    return operation


TOOL_SPECS = (
    ToolSpec(
        key="dem",
        action_attr="dem_action",
        text=u"DEM 생성 (Generate DEM)",
        icon_candidates=("dem_icon.png",),
        menu_group="terrain_data",
        dialog_module="dem_generator_dialog",
        dialog_class="DemGeneratorDialog",
        log_label="DEM tool",
    ),
    ToolSpec(
        key="contour",
        action_attr="contour_action",
        text=u"등고선 추출 (Extract Contours)",
        icon_candidates=("contour_icon.png",),
        menu_group="terrain_data",
        dialog_module="contour_extractor_dialog",
        dialog_class="ContourExtractorDialog",
        log_label="Contour tool",
    ),
    ToolSpec(
        key="cad_overlap",
        action_attr="cad_overlap_action",
        text=u"지적도 중첩 면적표 (Cadastral Overlap)",
        icon_candidates=("jijuk.png", "jijuk.jpg", "jijuk.jpeg", "style_icon.png"),
        menu_group="terrain_data",
        dialog_module="cadastral_overlap_dialog",
        dialog_class="CadastralOverlapDialog",
        log_label="Cadastral overlap tool",
    ),
    ToolSpec(
        key="terrain",
        action_attr="terrain_action",
        text=u"지형 분석 (Terrain Analysis)",
        icon_candidates=("terrain_icon.png",),
        menu_group="analysis",
        dialog_module="terrain_analysis_dialog",
        dialog_class="TerrainAnalysisDialog",
        log_label="Terrain tool",
    ),
    ToolSpec(
        key="ahp",
        action_attr="ahp_action",
        text=u"AHP 입지적합도 (AHP Suitability)",
        icon_candidates=("AHP.png", "ahp.png", "terrain_icon.png"),
        menu_group="analysis",
        dialog_module="ahp_suitability_dialog",
        dialog_class="AhpSuitabilityDialog",
        log_label="AHP tool",
    ),
    ToolSpec(
        key="geochem",
        action_attr="geochem_action",
        text=u"지구화학도 래스터 수치화 (GeoChem WMS → Raster)",
        icon_candidates=("tools/geochem.png", "geochem.png", "terrain_icon.png"),
        menu_group="analysis",
        dialog_module="geochem_polygonize_dialog",
        dialog_class="GeoChemPolygonizeDialog",
        log_label="GeoChem tool",
    ),
    ToolSpec(
        key="geology_zip",
        action_attr="geology_zip_action",
        text=u"지질도 도엽 ZIP 불러오기/래스터 변환 (KIGAM)",
        icon_candidates=("tools/geochem.png", "geochem.png", "terrain_icon.png"),
        menu_group="analysis",
        dialog_module="geology_zip_dialog",
        dialog_class="GeologyZipDialog",
        log_label="KIGAM geology tool",
    ),
    ToolSpec(
        key="profile",
        action_attr="profile_action",
        text=u"지형 단면 (Terrain Profile)",
        icon_candidates=("profile_icon.png",),
        menu_group="analysis",
        dialog_module="terrain_profile_dialog",
        dialog_class="TerrainProfileDialog",
        log_label="Terrain profile tool",
        persistent_attr="profile_dlg",
        modal=False,
    ),
    ToolSpec(
        key="viewshed",
        action_attr="viewshed_action",
        text=u"가시권 분석 (Viewshed Analysis)",
        icon_candidates=("viewshed_icon.png",),
        menu_group="analysis",
        dialog_module="viewshed_dialog",
        dialog_class="ViewshedDialog",
        log_label="Viewshed tool",
        persistent_attr="viewshed_dlg",
    ),
    ToolSpec(
        key="cost",
        action_attr="cost_action",
        text=u"비용표면/최소비용경로 (Cost Surface / LCP)",
        icon_candidates=("cost_icon.png",),
        menu_group="analysis",
        dialog_module="cost_surface_dialog",
        dialog_class="CostSurfaceDialog",
        log_label="Cost surface tool",
        persistent_attr="cost_dlg",
    ),
    ToolSpec(
        key="network",
        action_attr="network_action",
        text=u"최소비용 네트워크 (Least-cost Network)",
        icon_candidates=("network_icon.png", "network_icon.jpg", "network_icon.jpeg", "cost_icon.png"),
        menu_group="analysis",
        dialog_module="cost_network_dialog",
        dialog_class="CostNetworkDialog",
        log_label="Least-cost network tool",
        error_operation="실행",
    ),
    ToolSpec(
        key="spatial_network",
        action_attr="spatial_network_action",
        text=u"근접/가시성 네트워크 (PPA / Visibility)",
        icon_candidates=(
            "spatial_network.png",
            "spatial_network.jpg",
            "spatial_network.jpeg",
            "network_visibility.png",
            "network_visibility.jpg",
            "network_visibility.jpeg",
            "network_icon.png",
            "network_icon.jpg",
            "network_icon.jpeg",
            "cost_icon.png",
        ),
        menu_group="analysis",
        dialog_module="spatial_network_dialog",
        dialog_class="SpatialNetworkDialog",
        log_label="Spatial network tool",
        error_operation="실행",
    ),
    ToolSpec(
        key="style",
        action_attr="style_action",
        text=u"도면 시각화 (Map Styling)",
        icon_candidates=("style_icon.png",),
        menu_group="styling",
        dialog_module="map_styling_dialog",
        dialog_class="MapStylingDialog",
        log_label="Map styling tool",
    ),
    ToolSpec(
        key="drafting",
        action_attr="drafting_action",
        text=u"경사도/사면방향 도면화 (Slope/Aspect Drafting)",
        icon_candidates=("slope_aspect.png", "style_icon.png"),
        menu_group="styling",
        dialog_module="slope_aspect_drafting_dialog",
        dialog_class="SlopeAspectDraftingDialog",
        log_label="Slope/aspect drafting tool",
    ),
    ToolSpec(
        key="ai_report",
        action_attr="ai_report_action",
        text=u"AI 조사요약 (AOI Report)",
        icon_candidates=("AI.png", "ai.png", "icon.png", "terrain_icon.png", "style_icon.png"),
        menu_group="ai",
        dialog_module="ai_report_dialog",
        dialog_class="AiAoiReportDialog",
        log_label="AI AOI report tool",
    ),
)


class ArchToolkit:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu_actions = []
        self.tool_actions = {}
        self.menu_name = u'Archaeology Toolkit'
        self.toolbar = None
        self.main_action = None
        self.tool_button = None
        self.tool_menu = None
        self.language_menu = None
        self.language_action_group = None
        self.language_ko_action = None
        self.language_en_action = None
        self.viewshed_dlg = None  # Persistent reference for marker cleanup
        self.cost_dlg = None  # Persistent reference for temp/preview cleanup
        self.profile_dlg = None  # Persistent reference for multi-profile selection/view
        self.geochem_dlg = None  # Optional: keep reference if we later add temp cleanup
        self.geology_zip_dlg = None
        self._tool_specs_by_key = {spec.key: spec for spec in TOOL_SPECS}

    def _find_first_existing_path(self, relative_paths):
        for relative_path in relative_paths:
            candidate = os.path.join(self.plugin_dir, relative_path)
            if os.path.exists(candidate):
                return candidate
        return None

    def _resolve_icon(self, icon_candidates):
        icon_path = self._find_first_existing_path(icon_candidates)
        return QIcon(icon_path) if icon_path else QIcon()

    def _create_tool_action(self, spec):
        action = QAction(self._resolve_icon(spec.icon_candidates), tr(spec.text), self.iface.mainWindow())
        try:
            action.setProperty("_archtoolkit_i18n_source_text", spec.text)
        except Exception:
            pass
        action.triggered.connect(partial(self._execute_tool, spec.key))
        return action

    def _build_language_menu(self):
        if self.language_menu is not None:
            apply_language(self.language_menu)
            self._sync_language_actions()
            return self.language_menu

        menu = QMenu(self.iface.mainWindow())
        menu.setTitle("언어 (Language)")

        self.language_action_group = QActionGroup(menu)
        self.language_action_group.setExclusive(True)

        self.language_ko_action = QAction("한국어", menu)
        self.language_ko_action.setCheckable(True)
        self.language_ko_action.triggered.connect(partial(self._change_ui_language, "ko"))
        self.language_action_group.addAction(self.language_ko_action)

        self.language_en_action = QAction("영어 (English)", menu)
        self.language_en_action.setCheckable(True)
        self.language_en_action.triggered.connect(partial(self._change_ui_language, "en"))
        self.language_action_group.addAction(self.language_en_action)

        menu.addAction(self.language_ko_action)
        menu.addAction(self.language_en_action)
        self.language_menu = menu
        self._sync_language_actions()
        apply_language(menu)
        return menu

    def _build_tool_menu(self):
        menu = QMenu(self.iface.mainWindow())
        if hasattr(menu, "setSeparatorsCollapsible"):
            menu.setSeparatorsCollapsible(False)

        previous_group = None
        for spec in TOOL_SPECS:
            if previous_group is not None and spec.menu_group != previous_group:
                menu.addSeparator()
            menu.addAction(self.tool_actions[spec.key])
            previous_group = spec.menu_group
        menu.addSeparator()
        menu.addMenu(self.language_menu or self._build_language_menu())
        apply_language(menu)
        return menu

    def _sync_language_actions(self):
        lang = get_ui_language()
        if self.language_ko_action is not None:
            self.language_ko_action.setChecked(lang == "ko")
        if self.language_en_action is not None:
            self.language_en_action.setChecked(lang == "en")

    def _refresh_ui_language(self):
        for spec in TOOL_SPECS:
            action = self.tool_actions.get(spec.key)
            if action is not None:
                try:
                    action.setText(tr(spec.text))
                except Exception:
                    pass

        if self.language_menu is not None:
            try:
                self.language_menu.setTitle(tr("언어 (Language)"))
            except Exception:
                pass
            apply_language(self.language_menu)

        self._sync_language_actions()

        if self.tool_menu is not None:
            apply_language(self.tool_menu)
        if self.main_action is not None:
            apply_language(self.main_action)

        for attr_name in {spec.persistent_attr for spec in TOOL_SPECS if spec.persistent_attr}:
            dialog = getattr(self, attr_name, None)
            if dialog is not None:
                apply_language(dialog)

    def _change_ui_language(self, code, _checked=False):
        lang = set_ui_language(code)
        self._refresh_ui_language()
        if lang == "en":
            notice = "영어 UI가 적용되었습니다. 이미 열려 있던 창은 일부 다시 열어야 완전히 반영될 수 있습니다."
        else:
            notice = "한국어 UI가 적용되었습니다."
        try:
            self.iface.messageBar().pushMessage(tr("언어 (Language)"), tr(notice), level=0, duration=5)
        except Exception:
            pass

    def _load_dialog_class(self, spec):
        package_name = __package__ or __name__.rpartition(".")[0]
        module = import_module(f".tools.{spec.dialog_module}", package_name)
        return getattr(module, spec.dialog_class)

    def _get_dialog_instance(self, spec, dialog_class):
        if not spec.persistent_attr:
            return dialog_class(self.iface)

        dialog = getattr(self, spec.persistent_attr)
        if dialog is None:
            dialog = dialog_class(self.iface)
            setattr(self, spec.persistent_attr, dialog)
        return dialog

    def _show_dialog(self, dialog, *, modal):
        apply_language(dialog)
        if modal:
            dialog.exec_()
            return

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _execute_tool(self, spec_key, _checked=False):
        spec = self._tool_specs_by_key[spec_key]
        try:
            dialog_class = self._load_dialog_class(spec)
            dialog = self._get_dialog_instance(spec, dialog_class)
            self._show_dialog(dialog, modal=spec.modal)
        except Exception as e:
            log_exception(f"{spec.log_label} error", e)
            QMessageBox.critical(
                self.iface.mainWindow(),
                tr("오류"),
                tr(
                    "도구를 {operation} 중 오류가 발생했습니다: {error}",
                    operation=_translate_error_operation(spec.error_operation),
                    error=str(e),
                ),
            )

    def _cleanup_dialog(self, attr_name):
        dialog = getattr(self, attr_name, None)
        if dialog is None:
            return

        try:
            if hasattr(dialog, "cleanup_for_unload"):
                dialog.cleanup_for_unload()
        except Exception:
            pass
        try:
            dialog.close()
        except Exception:
            pass
        try:
            dialog.deleteLater()
        except Exception:
            pass
        setattr(self, attr_name, None)

    def initGui(self):
        try:
            # Enable real-time logs in the QGIS "Log Messages" panel.
            try:
                start_ui_log_pump()
            except Exception:
                pass
            try:
                install_runtime_i18n_hooks()
            except Exception:
                pass

            self.actions = []
            self.menu_actions = []
            self.tool_actions = {}

            # 1. Create actions from a shared tool registry so menu order,
            # grouping, icon fallbacks, and launcher behavior stay in sync.
            for spec in TOOL_SPECS:
                action = self._create_tool_action(spec)
                setattr(self, spec.action_attr, action)
                self.tool_actions[spec.key] = action
                self.menu_actions.append(action)

            self._build_language_menu()

            # 2. Add to Plugin Menu
            for action in self.menu_actions:
                self.iface.addPluginToMenu(self.menu_name, action)
            if self.language_menu is not None:
                self.iface.addPluginToMenu(self.menu_name, self.language_menu.menuAction())
                self.menu_actions.append(self.language_menu.menuAction())

            # 3. Create Dedicated Toolbar for Visibility
            self.toolbar = self.iface.addToolBar(u"ArchToolkit")
            self.toolbar.setObjectName("ArchToolkit")

            # 4. Create Unified Toolkit Button
            self.main_action = QAction(self._resolve_icon(("icon.png",)), u"ArchToolkit", self.iface.mainWindow())

            # Create dropdown menu using the same group metadata as the plugin menu.
            self.tool_menu = self._build_tool_menu()

            self.main_action.setMenu(self.tool_menu)

            # Add QToolButton to toolbar for instant popup support
            self.tool_button = QToolButton()
            self.tool_button.setDefaultAction(self.main_action)
            self.tool_button.setMenu(self.tool_menu)
            self.tool_button.setPopupMode(QToolButton.InstantPopup)

            self.toolbar.addWidget(self.tool_button)

            # Keep references for cleanup
            self.actions = list(self.menu_actions) + [self.main_action]
            self._refresh_ui_language()
        except Exception as e:
            log_exception("ArchToolkit initGui error", e)
            QMessageBox.critical(
                self.iface.mainWindow(),
                tr("ArchToolkit 로드 오류"),
                tr("플러그인을 초기화하는 중 오류가 발생했습니다: {error}", error=str(e)),
            )

    def unload(self):
        # Remove from menu
        for action in self.menu_actions:
            try:
                self.iface.removePluginMenu(self.menu_name, action)
            except Exception:
                pass

        try:
            stop_ui_log_pump()
        except Exception:
            pass

        # Close persistent dialogs and disconnect long-lived signals (prevents stale callbacks after reload)
        for attr_name in {spec.persistent_attr for spec in TOOL_SPECS if spec.persistent_attr}:
            self._cleanup_dialog(attr_name)

        # Remove toolbar cleanly from mainWindow
        if self.toolbar:
            try:
                self.iface.mainWindow().removeToolBar(self.toolbar)
            except Exception:
                pass
            try:
                self.toolbar.deleteLater()
            except Exception:
                pass
            self.toolbar = None

        self.tool_button = None
        self.tool_menu = None
        self.language_menu = None
        self.language_action_group = None
        self.language_ko_action = None
        self.language_en_action = None
        self.main_action = None
        self.menu_actions = []
        self.tool_actions = {}
        self.actions = []

    def run_dem_tool(self):
        self._execute_tool("dem")

    def run_contour_tool(self):
        self._execute_tool("contour")

    def run_cadastral_overlap_tool(self):
        self._execute_tool("cad_overlap")

    def run_terrain_tool(self):
        self._execute_tool("terrain")

    def run_ahp_tool(self):
        self._execute_tool("ahp")

    def run_profile_tool(self):
        self._execute_tool("profile")

    def run_geochem_tool(self):
        self._execute_tool("geochem")

    def run_geology_zip_tool(self):
        self._execute_tool("geology_zip")

    def run_ai_report_tool(self):
        self._execute_tool("ai_report")

    def run_styling_tool(self):
        self._execute_tool("style")

    def run_drafting_tool(self):
        self._execute_tool("drafting")

    def run_cost_tool(self):
        self._execute_tool("cost")

    def run_network_tool(self):
        self._execute_tool("network")

    def run_spatial_network_tool(self):
        self._execute_tool("spatial_network")

    def run_viewshed_tool(self):
        self._execute_tool("viewshed")
