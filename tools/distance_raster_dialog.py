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
거리 래스터 (Distance to Features).

Why this tool exists
- Distance to water is in almost every published archaeological predictive
  model, and distance to known sites, roads or resources is close behind.
  ArchToolkit produced every terrain derivative and none of these, so a user
  assembling predictors had to leave the plugin for the one variable most
  models lean on hardest.
- The output is a predictor, so it is built to be one: it lands on a chosen
  reference grid rather than inventing its own extent, it carries an explicit
  NoData, and the user names the variable up front - because that name becomes
  the column in the model's training table and the label in its importance
  ranking.

Design
- QGIS built-ins only (gdal:rasterize + gdal:proximity), per DEVELOPMENT.md.
- The reference raster defines CRS, extent and pixel size, so the result is
  already aligned with the rest of a predictor stack and needs no resampling.
- Distances are in the reference CRS's map units, which is why a geographic
  CRS is refused: degrees are not a distance an archaeologist can use.
"""

from __future__ import annotations

import os
import tempfile

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsProject,
    QgsRasterBandStats,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox

import processing

from .help_dialog import show_help_dialog
from .live_log_dialog import ensure_live_log_dialog
from .predictor_naming import distance_variable_key, sanitize_key
from .utils import (
    log_swallowed,
    cleanup_files,
    log_exception,
    log_message,
    new_run_id,
    push_message,
    restore_ui_focus,
    set_archtoolkit_layer_metadata,
)

PARENT_GROUP_NAME = "ArchToolkit - 거리 래스터 (Distance)"
DISTANCE_NODATA = -9999.0


class DistanceRasterDialog(QtWidgets.QDialog):
    """Euclidean distance from every cell to the nearest feature of a layer."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._setup_ui()

    # -- UI ------------------------------------------------------------------
    def _setup_ui(self):
        self.setWindowTitle("거리 래스터 (Distance to Features)")
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            for name in ("cost_icon.png", "terrain_icon.png", "icon.png"):
                path = os.path.join(plugin_dir, name)
                if os.path.exists(path):
                    self.setWindowIcon(QIcon(path))
                    break
        except Exception as _exc:
            log_swallowed("distance_raster_dialog._setup_ui", _exc)

        layout = QtWidgets.QVBoxLayout(self)
        header = QtWidgets.QLabel(
            "<b>거리 래스터</b><br>"
            "선택한 레이어의 가장 가까운 피처까지의 <b>직선거리</b>를 격자로 계산합니다. "
            "하천까지 거리, 기존 유적까지 거리, 도로까지 거리처럼 예측모델에서 가장 널리 쓰이는 변수입니다.<br>"
            "<span style='color:#455a64;'>기준 래스터의 격자(CRS·범위·픽셀크기)에 맞춰 출력하므로 "
            "다른 예측변수와 바로 같은 스택에 넣을 수 있습니다.</span>"
        )
        header.setWordWrap(True)
        header.setStyleSheet(
            "background:#e8f4fd; padding:10px; border:1px solid #bcdff5; border-radius:4px;"
        )
        layout.addWidget(header)

        grp_src = QtWidgets.QGroupBox("1. 거리를 잴 대상")
        form_src = QtWidgets.QFormLayout(grp_src)
        self.cmbSource = QgsMapLayerComboBox(grp_src)
        try:
            from qgis.core import QgsMapLayerProxyModel
            self.cmbSource.setFilters(
                QgsMapLayerProxyModel.PointLayer
                | QgsMapLayerProxyModel.LineLayer
                | QgsMapLayerProxyModel.PolygonLayer
            )
        except Exception as _exc:
            log_swallowed("distance_raster_dialog._setup_ui", _exc)
        self.cmbSource.layerChanged.connect(self._on_source_changed)
        form_src.addRow("대상 레이어:", self.cmbSource)
        self.chkSelectedOnly = QtWidgets.QCheckBox("선택한 피처만 사용")
        form_src.addRow("", self.chkSelectedOnly)
        layout.addWidget(grp_src)

        grp_grid = QtWidgets.QGroupBox("2. 기준 격자")
        form_grid = QtWidgets.QFormLayout(grp_grid)
        self.cmbRef = QgsMapLayerComboBox(grp_grid)
        try:
            from qgis.core import QgsMapLayerProxyModel
            self.cmbRef.setFilters(QgsMapLayerProxyModel.RasterLayer)
        except Exception as _exc:
            log_swallowed("tools/distance_raster_dialog.py:136 (_setup_ui)", _exc)
        form_grid.addRow("기준 래스터:", self.cmbRef)
        self.lblGridInfo = QtWidgets.QLabel("")
        self.lblGridInfo.setStyleSheet("color:#455a64; font-size:9pt;")
        self.cmbRef.layerChanged.connect(self._on_ref_changed)
        form_grid.addRow("", self.lblGridInfo)
        self.spinMaxDistance = QtWidgets.QDoubleSpinBox()
        self.spinMaxDistance.setRange(0.0, 1e9)
        self.spinMaxDistance.setDecimals(1)
        self.spinMaxDistance.setValue(0.0)
        self.spinMaxDistance.setSpecialValueText("(제한 없음)")
        self.spinMaxDistance.setSuffix(" m")
        self.spinMaxDistance.setToolTip(
            "이 거리를 넘는 셀은 NoData가 됩니다. 0이면 전체 격자를 계산합니다.\n"
            "모델 입력으로 쓸 때는 보통 제한 없이 두는 편이 낫습니다 — NoData 셀은 학습에서 빠집니다."
        )
        form_grid.addRow("최대 거리(선택):", self.spinMaxDistance)
        layout.addWidget(grp_grid)

        grp_out = QtWidgets.QGroupBox("3. 변수 이름")
        form_out = QtWidgets.QFormLayout(grp_out)
        self.txtVariable = QtWidgets.QLineEdit()
        self.txtVariable.setPlaceholderText("water, river, road, site …")
        self.txtVariable.textChanged.connect(self._on_variable_changed)
        form_out.addRow("변수 이름:", self.txtVariable)
        self.lblVariableHint = QtWidgets.QLabel("")
        self.lblVariableHint.setWordWrap(True)
        self.lblVariableHint.setStyleSheet("color:#455a64; font-size:9pt;")
        form_out.addRow("", self.lblVariableHint)
        layout.addWidget(grp_out)

        btn_row = QtWidgets.QHBoxLayout()
        self.btnRun = QtWidgets.QPushButton("거리 계산")
        self.btnRun.clicked.connect(self._on_run)
        self.btnHelp = QtWidgets.QPushButton("도움말")
        self.btnHelp.clicked.connect(self._on_help)
        self.btnClose = QtWidgets.QPushButton("닫기")
        self.btnClose.clicked.connect(self.reject)
        btn_row.addWidget(self.btnRun)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btnHelp)
        btn_row.addWidget(self.btnClose)
        layout.addLayout(btn_row)
        self.resize(560, 470)

        self._on_ref_changed(self.cmbRef.currentLayer())
        self._on_source_changed(self.cmbSource.currentLayer())

    def _on_source_changed(self, layer):
        # Suggest a variable name from the layer, but only when the user has
        # not typed one - never overwrite their choice.
        if layer is None or self.txtVariable.text().strip():
            return
        suggestion = sanitize_key(layer.name())
        if suggestion:
            self.txtVariable.setText(suggestion.lower()[:24])

    def _on_ref_changed(self, layer):
        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            self.lblGridInfo.setText("")
            return
        try:
            crs = layer.crs()
            px_x = abs(float(layer.rasterUnitsPerPixelX()))
            px_y = abs(float(layer.rasterUnitsPerPixelY()))
            text = (f"{crs.authid() or crs.description()} · {layer.width()}x{layer.height()} 셀 "
                    f"· 픽셀 {px_x:g}")
            if not self._is_square_pixel(px_x, px_y):
                text += (f" x {px_y:g}  [주의] 비정사각 픽셀 — 거리 계산 불가, "
                         "정사각 픽셀로 리샘플링하세요")
            if crs.isValid() and crs.isGeographic():
                text += "  [주의] 지리좌표계(도) — 투영 CRS를 쓰세요"
            self.lblGridInfo.setText(text)
        except Exception as _exc:
            log_swallowed("distance_raster_dialog._on_ref_changed", _exc)
            self.lblGridInfo.setText("")

    def _on_variable_changed(self, text):
        name = str(text or "").strip()
        if not name:
            self.lblVariableHint.setText(
                "비워 두면 대상 레이어 이름에서 자동으로 만듭니다."
            )
            return
        key = self._variable_key(name)
        if key is None:
            self.lblVariableHint.setText(
                "<span style='color:#c62828;'>영문/숫자/밑줄만 쓸 수 있습니다. "
                "예측모델 도구가 한글을 지우기 때문에 한글 이름은 쓸 수 없습니다.</span>"
            )
        else:
            self.lblVariableHint.setText(f"출력 변수명: <b>{key}</b>")

    @staticmethod
    def _variable_key(name: str):
        """`distance_<name>`, or None when the name cannot be used downstream.

        The rule lives in predictor_naming so CI can test it without QGIS; see
        that module for why a Korean name arrives empty rather than
        transliterated.
        """
        return distance_variable_key(name)

    # -- run -----------------------------------------------------------------
    def _on_run(self):
        source = self.cmbSource.currentLayer()
        if not isinstance(source, QgsVectorLayer) or not source.isValid():
            push_message(self.iface, "오류", "대상 벡터 레이어를 선택하세요.", level=2, duration=6)
            return
        ref = self.cmbRef.currentLayer()
        if not isinstance(ref, QgsRasterLayer) or not ref.isValid():
            push_message(self.iface, "오류", "기준 래스터를 선택하세요.", level=2, duration=6)
            return

        ref_crs = ref.crs()
        if not ref_crs.isValid():
            push_message(
                self.iface, "오류",
                "기준 래스터에 CRS가 없습니다. 거리를 계산할 수 없습니다.",
                level=2, duration=8,
            )
            return
        if ref_crs.isGeographic():
            push_message(
                self.iface, "오류",
                "기준 래스터가 지리좌표계(도)입니다. 거리 단위가 미터가 되도록 "
                "투영 CRS(예: EPSG:5179) 래스터를 기준으로 쓰세요.",
                level=2, duration=10,
            )
            return

        name_text = self.txtVariable.text().strip() or source.name()
        key = self._variable_key(name_text)
        if key is None:
            push_message(
                self.iface, "오류",
                "변수 이름을 영문/숫자/밑줄로 지정하세요 (예: water, road, site).",
                level=2, duration=8,
            )
            return

        use_selected = self.chkSelectedOnly.isChecked()
        if use_selected and source.selectedFeatureCount() == 0:
            push_message(
                self.iface, "오류",
                "'선택한 피처만'이 켜져 있지만 선택된 피처가 없습니다.",
                level=2, duration=7,
            )
            return
        if not use_selected and source.featureCount() == 0:
            push_message(self.iface, "오류", "대상 레이어가 비어 있습니다.", level=2, duration=6)
            return

        try:
            px_x = abs(float(ref.rasterUnitsPerPixelX()))
            px_y = abs(float(ref.rasterUnitsPerPixelY()))
        except Exception as _exc:
            log_swallowed("distance_raster_dialog._on_run", _exc)
            px_x = px_y = 0.0
        if px_x <= 0 or px_y <= 0:
            push_message(self.iface, "오류", "기준 래스터 픽셀 크기를 확인할 수 없습니다.",
                         level=2, duration=6)
            return
        # gdal_proximity measures sqrt(dx^2 + dy^2) in pixel-index space and
        # multiplies by the X pixel size alone (alg/gdalproximity.cpp), so on a
        # 10 m x 20 m grid every north-south distance comes out at half its
        # true value while the layer still says metres. GDAL's own "Pixels not
        # square" note is a CPLError warning that never reaches the message
        # bar, so the refusal has to happen here - the same rule align/export
        # applies to its reference grid.
        if not self._is_square_pixel(px_x, px_y):
            log_message(
                f"거리 래스터: 비정사각 픽셀 기준 래스터 거부 ({ref.name()}: "
                f"{px_x:g} x {px_y:g}).",
                level=Qgis.Warning,
            )
            push_message(
                self.iface, "오류",
                f"비정사각 픽셀 기준 래스터({px_x:g} x {px_y:g})는 거리 계산에서 지원하지 않습니다. "
                "GDAL proximity가 두 축 모두에 X 픽셀 크기를 적용해 남북 방향 거리가 틀어집니다. "
                "기준 래스터를 정사각 픽셀로 리샘플링한 뒤 다시 실행하세요.",
                level=2, duration=12,
            )
            return

        run_id = new_run_id("dist")
        try:
            ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)
        except Exception as _exc:
            log_swallowed("tools/distance_raster_dialog.py:298 (_on_run)", _exc)

        temp_files = []
        self.btnRun.setEnabled(False)
        progress = QtWidgets.QProgressDialog("거리 계산 중…", None, 0, 3, self)
        progress.setWindowModality(2)  # Qt.WindowModal
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        QtWidgets.QApplication.processEvents()

        try:
            # 1. Selection and CRS are settled before rasterizing: gdal_rasterize
            #    burns coordinates as they are, so a layer in a different CRS
            #    would silently land in the wrong place on the grid.
            prepared = source
            if use_selected:
                progress.setLabelText("선택 피처 추출 중…")
                QtWidgets.QApplication.processEvents()
                selected_path = os.path.join(
                    tempfile.gettempdir(), f"archt_dist_sel_{run_id}.gpkg")
                temp_files.append(selected_path)
                prepared = processing.run("native:saveselectedfeatures", {
                    "INPUT": source, "OUTPUT": selected_path,
                })["OUTPUT"]

            source_crs = source.crs()
            if source_crs.isValid() and source_crs != ref_crs:
                progress.setLabelText("좌표계 변환 중…")
                QtWidgets.QApplication.processEvents()
                reprojected_path = os.path.join(
                    tempfile.gettempdir(), f"archt_dist_proj_{run_id}.gpkg")
                temp_files.append(reprojected_path)
                prepared = processing.run("native:reprojectlayer", {
                    "INPUT": prepared,
                    "TARGET_CRS": QgsCoordinateReferenceSystem(ref_crs),
                    "OUTPUT": reprojected_path,
                })["OUTPUT"]
                log_message(
                    f"거리 래스터: 대상 레이어를 {source_crs.authid()} → "
                    f"{ref_crs.authid()} 로 변환했습니다."
                )
            elif not source_crs.isValid():
                push_message(
                    self.iface, "오류",
                    "대상 레이어에 CRS가 없습니다. CRS를 지정한 뒤 다시 실행하세요.",
                    level=2, duration=8,
                )
                return

            # 2. Burn the features onto the reference grid.
            progress.setValue(1)
            progress.setLabelText("대상을 격자에 굽는 중…")
            QtWidgets.QApplication.processEvents()
            extent = ref.extent()

            # gdal:rasterize burns only what falls inside EXTENT. A river whose
            # main channel runs just past the DEM edge would be dropped without
            # a word, and every "distance to water" would then point at some
            # minor tributary instead - or, with nothing inside at all, the
            # output would be all NoData and still report success. Check the
            # overlap before burning so the user hears about it.
            prepared_extent = self._layer_extent(prepared)
            if prepared_extent is not None and not prepared_extent.isEmpty():
                if not prepared_extent.intersects(extent):
                    raise RuntimeError(
                        "대상 레이어가 기준 래스터 범위와 전혀 겹치지 않습니다. "
                        "거리를 잴 피처가 격자 안에 없습니다."
                    )
                if not extent.contains(prepared_extent):
                    log_message(
                        f"거리 래스터: 대상 레이어 일부가 기준 래스터 범위 밖에 있습니다. "
                        f"범위 밖 피처는 거리 계산에서 제외됩니다 ({key}).",
                        level=Qgis.Warning,
                    )
                    push_message(
                        self.iface, "주의",
                        "대상 레이어 일부가 기준 래스터 범위 밖에 있어 그 피처들은 제외됩니다. "
                        "가장 가까운 피처가 범위 밖이면 거리가 과대평가됩니다.",
                        level=1, duration=10,
                    )
            extent_str = (f"{extent.xMinimum()},{extent.xMaximum()},"
                          f"{extent.yMinimum()},{extent.yMaximum()}"
                          f" [{ref_crs.authid()}]")
            burned = os.path.join(tempfile.gettempdir(), f"archt_dist_burn_{run_id}.tif")
            temp_files.append(burned)
            # GDAL's default burns a polygon only where a pixel CENTRE falls
            # inside it, so a 5 m channel polygon on a 30 m grid burns almost
            # nothing and every "distance to water" then points at the nearest
            # wide reach instead. A presence mask feeding a distance transform
            # wants every touched cell (-at); points are unaffected by -at and
            # always land in the cell that contains them.
            burn_rule = self._burn_rule(source)
            processing.run("gdal:rasterize", {
                "INPUT": prepared,
                "BURN": 1,
                "UNITS": 1,          # georeferenced units
                "WIDTH": px_x,
                "HEIGHT": px_y,
                "EXTENT": extent_str,
                "NODATA": 0,
                "DATA_TYPE": 0,      # Byte: this is a presence mask, not a measurement
                "INIT": 0,
                "ALL_TOUCH": burn_rule == "all_touched",
                "OUTPUT": burned,
            })
            if not os.path.exists(burned):
                raise RuntimeError("대상 레이어를 격자에 굽지 못했습니다.")

            # A mask with no target cell makes gdal:proximity write NoData into
            # every cell and still return a valid file, so "file exists" is not
            # enough: count what actually burned before spending the proximity
            # pass on it.
            target_cells = None
            burned_summary = self._band_summary(burned)
            if burned_summary is not None:
                _valid, value_sum, max_value = burned_summary
                target_cells = int(round(value_sum))
                if target_cells <= 0 and max_value >= 1:
                    # Contradictory statistics; something burned, count unknown.
                    target_cells = None
                elif target_cells <= 0:
                    log_message(
                        f"거리 래스터: 대상 레이어 '{source.name()}'가 기준 격자 어느 셀에도 "
                        f"구워지지 않아 중단합니다 ({key}, 기준 {ref.name()}).",
                        level=Qgis.Warning,
                    )
                    push_message(
                        self.iface, "오류",
                        f"대상 레이어 '{source.name()}'의 피처가 기준 격자({px_x:g} m 셀)의 어느 셀에도 "
                        "구워지지 않았습니다. 거리 래스터를 만들지 않았습니다. "
                        "기준 래스터 범위와 대상 레이어의 지오메트리를 확인하세요.",
                        level=2, duration=12,
                    )
                    return
                log_message(
                    f"거리 래스터: 대상 셀 {target_cells}개 ({burn_rule}, {key}).")
            else:
                log_message(
                    f"거리 래스터: 구운 셀 수를 확인하지 못했습니다 ({key}). 계속 진행합니다.",
                    level=Qgis.Warning,
                )

            # 3. Distance from every cell to the nearest burned cell.
            progress.setValue(2)
            progress.setLabelText("거리 계산 중…")
            QtWidgets.QApplication.processEvents()
            max_distance = float(self.spinMaxDistance.value())
            output = os.path.join(tempfile.gettempdir(), f"archt_{key}_{run_id}.tif")
            proximity_params = {
                "INPUT": burned,
                "BAND": 1,
                "VALUES": "1",
                "UNITS": 0,          # georeferenced distances, i.e. map units
                "MAX_DISTANCE": max_distance,
                "NODATA": DISTANCE_NODATA,
                "REPLACE": 0,
                "OPTIONS": "",
                "EXTRA": "",
                "DATA_TYPE": 5,      # Float32
                "OUTPUT": output,
            }
            processing.run("gdal:proximity", proximity_params)
            if not os.path.exists(output):
                raise RuntimeError("거리 래스터가 생성되지 않았습니다.")

            # Same rule on the way out: a layer that is 100% NoData would be
            # added, stamped with units="m" and reported as done, and then
            # silently drop every training point from a predictor stack.
            output_summary = self._band_summary(output)
            if output_summary is not None:
                valid_cells, _sum, max_value = output_summary
                if valid_cells <= 0 and not (max_value >= 0):
                    temp_files.append(output)
                    hint = ""
                    if max_distance > 0:
                        hint = (f" 최대 거리({max_distance:g} m)를 늘리거나 제한을 없애세요.")
                    log_message(
                        f"거리 래스터: 결과가 전부 NoData여서 레이어를 추가하지 않습니다 "
                        f"({key}, 기준 {ref.name()}).",
                        level=Qgis.Warning,
                    )
                    push_message(
                        self.iface, "오류",
                        f"거리 래스터 '{key}'에 유효한 셀이 없습니다(전부 NoData). "
                        f"레이어를 추가하지 않았습니다.{hint}",
                        level=2, duration=12,
                    )
                    return
            else:
                log_message(
                    f"거리 래스터: 결과의 유효 셀 수를 확인하지 못했습니다 ({key}).",
                    level=Qgis.Warning,
                )

            progress.setValue(3)
            layer = QgsRasterLayer(output, f"{key} (거리, m)")
            if not layer.isValid():
                raise RuntimeError("거리 래스터를 레이어로 열 수 없습니다.")

            set_archtoolkit_layer_metadata(
                layer,
                tool_id="distance_raster",
                run_id=run_id,
                kind=key,
                units="m",
                params={
                    "source_layer": source.name(),
                    "selected_only": bool(use_selected),
                    "max_distance_m": max_distance or None,
                    "reference_raster": ref.name(),
                    "reference_crs": ref_crs.authid(),
                    "pixel_size_m": px_x,
                    "burn_rule": burn_rule,
                    "target_cells": target_cells,
                },
            )
            self._add_to_group(layer, run_id)

            push_message(
                self.iface, "거리 래스터",
                f"완료: 변수 '{key}' 생성 (기준 {ref.name()})",
                level=0, duration=8,
            )
            log_message(f"Distance raster done: {key} (run {run_id})")
        except Exception as e:
            log_exception("Distance raster failed", e)
            push_message(self.iface, "오류", f"거리 계산에 실패했습니다: {e}",
                         level=2, duration=10)
        finally:
            self.btnRun.setEnabled(True)
            try:
                progress.close()
            except Exception as _exc:
                log_swallowed("tools/distance_raster_dialog.py:458 (_on_run)", _exc)
            # The burned mask and any reprojection are scratch; the distance
            # raster itself is referenced by the new layer and must survive.
            cleanup_files(temp_files)
            restore_ui_focus(self)

    @staticmethod
    def _is_square_pixel(px_x, px_y, rel_tol=1e-6):
        """True when the two pixel sizes agree within a relative tolerance."""
        try:
            px_x, px_y = abs(float(px_x)), abs(float(px_y))
        except Exception as _exc:
            log_swallowed("distance_raster_dialog._is_square_pixel", _exc)
            return False
        if px_x <= 0 or px_y <= 0:
            return False
        return abs(px_x - px_y) <= rel_tol * max(px_x, px_y)

    @staticmethod
    def _burn_rule(layer) -> str:
        """'cell_centre' for point sources, 'all_touched' for lines and polygons.

        Recorded in the layer metadata so a reader of the predictor can tell
        how the target was put on the grid. When the geometry type cannot be
        read the line/polygon rule is used: GDAL ignores -at for points, so
        the wider rule is never wrong, only the label would be.
        """
        try:
            if layer.geometryType() == QgsWkbTypes.PointGeometry:
                return "cell_centre"
        except Exception as _exc:
            log_swallowed("distance_raster_dialog._burn_rule", _exc)
        return "all_touched"

    @staticmethod
    def _band_summary(path):
        """(valid_cells, value_sum, max_value) of band 1, or None when unknown.

        Full scan (sampleSize 0): a sampled pass could miss the handful of
        cells a small site layer burns, and refusing on a sampling artefact
        would be worse than the silence this replaces. For the 0/1 mask the
        sum is the burned-cell count whether or not the NoData flag took;
        for the distance raster elementCount is the number of non-NoData
        cells. None means the statistics could not be read, and the caller
        proceeds with a logged warning rather than aborting a working run.
        """
        try:
            probe = QgsRasterLayer(str(path), "archt_dist_stats_probe", "gdal")
            if not probe.isValid():
                return None
            stats = probe.dataProvider().bandStatistics(
                1, QgsRasterBandStats.All, QgsRectangle(), 0)
            return (int(stats.elementCount), float(stats.sum), float(stats.maximumValue))
        except Exception as _exc:
            log_swallowed("distance_raster_dialog._band_summary", _exc)
        return None

    @staticmethod
    def _layer_extent(obj):
        """Extent of a layer object or of a vector path, or None."""
        try:
            if isinstance(obj, QgsVectorLayer):
                return obj.extent()
            layer = QgsVectorLayer(str(obj), "archt_dist_extent_probe", "ogr")
            if layer.isValid():
                return layer.extent()
        except Exception as _exc:
            log_swallowed("distance_raster_dialog._layer_extent", _exc)
        return None

    def _add_to_group(self, layer, run_id):
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        parent = root.findGroup(PARENT_GROUP_NAME)
        if parent is None:
            parent = root.insertGroup(0, PARENT_GROUP_NAME)
        project.addMapLayer(layer, False)
        parent.insertLayer(0, layer)

    def _on_help(self):
        html = (
            "<h3>거리 래스터 (Distance to Features)</h3>"
            "<p>각 셀에서 가장 가까운 피처까지의 <b>직선거리</b>를 계산합니다. "
            "고고학 예측모델에서 가장 널리 쓰이는 변수 계열입니다 — 하천까지 거리, "
            "기존 유적까지 거리, 도로·자원까지 거리.</p>"
            "<h4>사용</h4>"
            "<ol>"
            "<li><b>대상 레이어</b>: 거리를 잴 대상(하천선, 유적점, 도로선 등). "
            "점은 점이 놓인 셀에, 선·면은 <b>닿는 모든 셀</b>에 굽습니다(all-touched). "
            "기준 셀보다 훨씬 가는 하천·도로 폴리곤도 셀 단위로만 표현되므로 "
            "거리의 해상도는 기준 픽셀 크기를 넘지 못합니다.</li>"
            "<li><b>기준 래스터</b>: 출력 격자를 정합니다. 다른 예측변수와 같은 래스터를 "
            "고르면 정렬 작업 없이 바로 같은 스택에 들어갑니다.</li>"
            "<li><b>변수 이름</b>: 영문으로 짧게 (water, road, site). "
            "출력 변수명은 <code>distance_&lt;이름&gt;</code>이 됩니다.</li>"
            "</ol>"
            "<h4>왜 영문 이름인가</h4>"
            "<p>예측모델 도구는 파일 이름에서 변수 이름을 만들면서 한글을 "
            "<b>음차하지 않고 지웁니다</b>. 한글 이름을 쓰면 보고서에 "
            "<code>predictor_2</code> 같은 이름으로 나옵니다. 그래서 여기서 미리 막습니다.</p>"
            "<h4>주의</h4>"
            "<ul>"
            "<li>기준 래스터가 <b>투영 CRS</b>여야 거리 단위가 미터가 됩니다. "
            "지리좌표계(도)는 거부합니다.</li>"
            "<li>대상 레이어 CRS가 다르면 자동으로 변환한 뒤 계산합니다.</li>"
            "<li>기준 래스터 픽셀은 <b>정사각</b>이어야 합니다. 비정사각 픽셀은 GDAL이 "
            "X 픽셀 크기로만 거리를 환산해 남북 거리가 틀어지므로 거부합니다.</li>"
            "<li>대상이 격자 어느 셀에도 구워지지 않거나 결과가 전부 NoData이면 "
            "레이어를 추가하지 않고 오류를 표시합니다.</li>"
            "<li><b>최대 거리</b>를 두면 그보다 먼 셀은 NoData가 되고, 모델 학습에서 "
            "그 셀들이 빠집니다. 보통은 제한 없이 두세요.</li>"
            "</ul>"
            "<p style='color:#455a64'>QGIS 기본 구성(GDAL)만 사용합니다.</p>"
        )
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            show_help_dialog(parent=self, title="거리 래스터 도움말", html=html,
                             plugin_dir=plugin_dir)
        except Exception as _exc:
            log_swallowed("tools/distance_raster_dialog.py:520 (_on_help)", _exc)
