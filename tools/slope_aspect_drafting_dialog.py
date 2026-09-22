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
Slope/Aspect Drafting (Cartographic) Tool

This tool is intentionally separated from "Terrain Analysis".
It generates print-ready layers for a user-defined AOI polygon.

Inputs:
- DEM raster
- AOI polygon (clip/mask)

Outputs (optional):
- Slope raster (red ramp, 0°→90°)
- Aspect arrow points (rotated by azimuth)
"""

import math
import os
import tempfile
import uuid

from osgeo import gdal

from qgis.PyQt import QtWidgets, uic
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsGradientColorRamp,
    QgsGeometry,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsPointXY,
    QgsProject,
    QgsProperty,
    QgsRendererCategory,
    QgsStyle,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from .qtcompat import FT_INT, FT_DOUBLE, FT_STRING, SYMBOL_PROPERTY_ANGLE

import processing

from .utils import log_swallowed, cleanup_files, push_message, restore_ui_focus, set_archtoolkit_layer_metadata
from .live_log_dialog import ensure_live_log_dialog
from .help_dialog import show_help_dialog
from . import dialog_memory
from .icons import icon as plugin_icon


FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "slope_aspect_drafting_dialog_base.ui")
)


class SlopeAspectDraftingDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        # Remember the last-used inputs between sessions (tools/dialog_memory.py).
        dialog_memory.attach(self, "slope_aspect_drafting")
        try:
            self.setWindowIcon(plugin_icon("slope_aspect.png"))
        except Exception as _exc:
            log_swallowed("slope_aspect_drafting_dialog.__init__ (icon)", _exc)
        self.setupUi(self)
        self.iface = iface

        self.cmbDemLayer.setFilters(Qgis.LayerFilter.RasterLayer)
        self.cmbMaskLayer.setFilters(Qgis.LayerFilter.VectorLayer)

        self.btnCreateMask.clicked.connect(self.create_mask_layer)
        self.btnRun.clicked.connect(self.run_drafting)
        self.btnClose.clicked.connect(self.reject)
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
            log_swallowed("slope_aspect_drafting_dialog._setup_help_button", _exc)

    def _on_help(self):
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            html = (
                "<h2>경사도/사면방향 도면화 (Slope/Aspect Drafting)</h2>"
                "<p>AOI(작업영역)를 기준으로 인쇄용 경사 래스터와 사면방향(방위각) 화살표 레이어를 생성합니다.</p>"
                "<h3>입력</h3>"
                "<ul>"
                "<li>DEM 래스터</li>"
                "<li>AOI 폴리곤(없으면 ‘작업영역(AOI) 폴리곤 생성’으로 생성)</li>"
                "</ul>"
                "<h3>팁</h3>"
                "<ul>"
                "<li>AOI 범위를 너무 크게 잡으면 출력이 무거워질 수 있습니다.</li>"
                "</ul>"
            )
            show_help_dialog(parent=self, title="도면화(경사/사면방향) 도움말", html=html, plugin_dir=plugin_dir, tool_id="slope_aspect_drafting")
        except Exception:
            try:
                QtWidgets.QMessageBox.information(self, "도움말", "README.md를 참고하세요.")
            except Exception as _exc:
                log_swallowed("tools/slope_aspect_drafting_dialog.py:134 (_on_help)", _exc)

    def create_mask_layer(self):
        dem_layer = self.cmbDemLayer.currentLayer()
        crs_authid = (
            dem_layer.crs().authid()
            if dem_layer is not None
            else QgsProject.instance().crs().authid()
        )

        layer = QgsVectorLayer(
            f"MultiPolygon?crs={crs_authid}", "작업영역_AOI (AOI polygon)", "memory"
        )
        pr = layer.dataProvider()
        pr.addAttributes([QgsField("name", FT_STRING)])
        layer.updateFields()
        QgsProject.instance().addMapLayer(layer)

        try:
            self.cmbMaskLayer.setLayer(layer)
        except Exception as _exc:
            log_swallowed("tools/slope_aspect_drafting_dialog.py:155 (create_mask_layer)", _exc)
        try:
            layer.startEditing()
            self.iface.setActiveLayer(layer)
        except Exception as _exc:
            log_swallowed("tools/slope_aspect_drafting_dialog.py:160 (create_mask_layer)", _exc)

        push_message(
            self.iface,
            "작업영역(AOI)",
            "새 폴리곤 레이어를 생성했습니다. 편집 모드에서 폴리곤(1개 이상)을 그린 후 실행해주세요.",
            level=0,
            duration=6,
        )

    def run_drafting(self):
        dem_layer = self.cmbDemLayer.currentLayer()
        if dem_layer is None:
            push_message(self.iface, "오류", "입력 DEM(래스터)을 선택해주세요.", level=2)
            restore_ui_focus(self)
            return

        mask_layer = self.cmbMaskLayer.currentLayer()
        if mask_layer is None:
            push_message(
                self.iface,
                "오류",
                "작업영역(AOI) 폴리곤 레이어를 선택하거나 '새 폴리곤'을 눌러 생성해주세요.",
                level=2,
            )
            restore_ui_focus(self)
            return
        if mask_layer.geometryType() != Qgis.GeometryType.Polygon:
            push_message(self.iface, "오류", "작업영역은 폴리곤 레이어여야 합니다.", level=2)
            restore_ui_focus(self)
            return

        use_selected_only = bool(self.chkMaskSelectedOnly.isChecked())
        if use_selected_only and mask_layer.selectedFeatureCount() == 0:
            push_message(
                self.iface,
                "오류",
                "선택된 폴리곤이 없습니다. '선택된 피처만 사용'을 해제하거나 폴리곤을 선택해주세요.",
                level=2,
            )
            restore_ui_focus(self)
            return
        if (not use_selected_only) and mask_layer.featureCount() == 0:
            push_message(
                self.iface,
                "오류",
                "작업영역 폴리곤이 없습니다. 폴리곤을 그리거나 다른 폴리곤 레이어를 선택해주세요.",
                level=2,
            )
            restore_ui_focus(self)
            return

        mask_source = (
            self._selected_polygons_as_mask_layer(mask_layer)
            if use_selected_only
            else mask_layer
        )

        want_slope = bool(self.chkSlopeRaster.isChecked())
        want_aspect = bool(self.chkAspectArrows.isChecked())
        if not (want_slope or want_aspect):
            push_message(self.iface, "오류", "생성할 결과(경사도/사면방향)를 선택해주세요.", level=2)
            restore_ui_focus(self)
            return

        # gdal:slope/aspect read the cell size straight from the geotransform and
        # SCALE=1 (gdaldem's default) is only correct when the horizontal and the
        # vertical units are both metres. On a geographic (degree) DEM every value
        # would be silently, plausibly wrong (slope ~89.9° everywhere) - and this
        # tool prints those numbers as value labels on a finished drawing.
        try:
            if dem_layer.crs().isGeographic():
                push_message(
                    self.iface,
                    "오류",
                    "DEM이 지리좌표계(위경도)입니다. 미터 단위 투영 좌표계로 재투영 후 사용하세요. "
                    "(위경도 DEM에서는 경사도 래스터와 도면 라벨 값이 전부 왜곡됩니다)",
                    level=2,
                    duration=9,
                )
                restore_ui_focus(self)
                return
        except Exception as _exc:
            log_swallowed("slope_aspect_drafting_dialog.run_drafting", _exc)

        # Live log window (non-modal) so users can see progress in real time.
        ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)

        step_cells = max(1, int(self.spinStepCells.value()))
        flat_thresh = max(0.0, float(self.spinFlatSlopeDeg.value()))
        arrow_size_mm = max(0.1, float(self.spinArrowSizeMm.value()))
        label_size_pt = max(4.0, float(self.spinLabelSizePt.value()))
        slope_class_step = 5
        try:
            slope_class_step = max(1, int(self.spinSlopeClassStep.value()))
        except Exception:
            slope_class_step = 5

        push_message(self.iface, "처리 중", "경사도/사면방향 도면화 생성 중...", level=0)
        self.hide()
        QtWidgets.QApplication.processEvents()

        run_id = uuid.uuid4().hex[:6]
        dem_source = dem_layer.source()

        slope_full_tif = os.path.join(
            tempfile.gettempdir(), f"archtoolkit_slope_full_{run_id}.tif"
        )
        slope_clip_tif = os.path.join(
            tempfile.gettempdir(), f"archtoolkit_slope_aoi_{run_id}.tif"
        )
        aspect_full_tif = os.path.join(
            tempfile.gettempdir(), f"archtoolkit_aspect_full_{run_id}.tif"
        )
        aspect_clip_tif = os.path.join(
            tempfile.gettempdir(), f"archtoolkit_aspect_aoi_{run_id}.tif"
        )

        intermediate_files = []
        success = False
        try:
            # Slope is required for both slope raster and aspect filtering.
            # SCALE=1 is gdaldem's default and is only correct when the
            # horizontal and the vertical units are both metres - the
            # geographic-CRS guard above is what keeps that true.
            # COMPUTE_EDGES stays at the toolbox default (False), so the 1-px
            # border comes back as the -9999 NoData sentinel instead of a
            # half-window guess. Both samplers below have to reject that value
            # explicitly (slope <= -9000 / slope <= flat_thresh_deg) because
            # -9999 is finite and isfinite() alone would let it through.
            # Both choices are recorded in the layer metadata below.
            processing.run(
                "gdal:slope",
                {
                    "INPUT": dem_source,
                    "BAND": 1,
                    "SCALE": 1,
                    "AS_PERCENT": False,
                    "OUTPUT": slope_full_tif,
                },
            )
            intermediate_files.append(slope_full_tif)
            self._clip_raster_by_mask(slope_full_tif, mask_source, slope_clip_tif)
            intermediate_files.append(slope_clip_tif)

            # Prepare layer tree group
            project = QgsProject.instance()
            root = project.layerTreeRoot()
            parent_name = "ArchToolkit - 도면화(경사도/사면방향) (Slope/Aspect Drafting)"
            parent_group = root.findGroup(parent_name)
            if parent_group is None:
                parent_group = root.insertGroup(0, parent_name)
            group_name = f"도면화_{dem_layer.name()}_{run_id}"
            run_group = parent_group.insertGroup(0, group_name)
            run_group.setExpanded(False)

            if want_slope:
                out_grid = self._build_slope_grid_layer(
                    slope_tif=slope_clip_tif,
                    dem_authid=dem_layer.crs().authid(),
                    step_cells=step_cells,
                    label_size_pt=label_size_pt,
                    slope_class_step=slope_class_step,
                )
                try:
                    set_archtoolkit_layer_metadata(
                        out_grid,
                        tool_id="slope_aspect_drafting",
                        run_id=str(run_id),
                        kind="slope_grid",
                        units="deg",
                        params={
                            "step_cells": int(step_cells),
                            "label_size_pt": float(label_size_pt),
                            "slope_class_step": int(slope_class_step),
                            "scale": 1,
                            "compute_edges": False,
                        },
                    )
                except Exception as _exc:
                    log_swallowed("slope_aspect_drafting_dialog.run_drafting", _exc)
                project.addMapLayer(out_grid, False)
                run_group.insertLayer(0, out_grid)

            if want_aspect:
                # ZERO_FLAT=True overrides the QGIS toolbox default (False):
                # with the default gdaldem writes -9999 for flat cells, which is
                # finite and would quantize to a bogus 81 deg (= E) arrow if the
                # user left the flat threshold at 0. Writing flats as 0 keeps
                # them harmless; they are dropped by the slope <= flat_thresh_deg
                # test in _build_aspect_arrow_layer either way.
                # COMPUTE_EDGES stays at the toolbox default (False) - the same
                # as the gdal:slope call above - so the 1-px border is NoData in
                # BOTH rasters and the arrow sampler drops it through that same
                # slope test. Enabling it on only one of the two would ring the
                # drawing with arrows whose direction is a half-window guess.
                # Both choices are recorded in the layer metadata below.
                processing.run(
                    "gdal:aspect",
                    {
                        "INPUT": dem_source,
                        "BAND": 1,
                        "TRIG_ANGLE": False,
                        "ZERO_FLAT": True,
                        "OUTPUT": aspect_full_tif,
                    },
                )
                intermediate_files.append(aspect_full_tif)
                self._clip_raster_by_mask(aspect_full_tif, mask_source, aspect_clip_tif)
                intermediate_files.append(aspect_clip_tif)

                out_pts = self._build_aspect_arrow_layer(
                    slope_tif=slope_clip_tif,
                    aspect_tif=aspect_clip_tif,
                    dem_authid=dem_layer.crs().authid(),
                    step_cells=step_cells,
                    flat_thresh_deg=flat_thresh,
                    arrow_size_mm=arrow_size_mm,
                )
                try:
                    set_archtoolkit_layer_metadata(
                        out_pts,
                        tool_id="slope_aspect_drafting",
                        run_id=str(run_id),
                        kind="aspect_arrows",
                        units="deg",
                        params={
                            "step_cells": int(step_cells),
                            "flat_thresh_deg": float(flat_thresh),
                            "arrow_size_mm": float(arrow_size_mm),
                            "zero_flat": True,
                            "compute_edges": False,
                        },
                    )
                except Exception as _exc:
                    log_swallowed("slope_aspect_drafting_dialog.run_drafting", _exc)
                project.addMapLayer(out_pts, False)
                run_group.insertLayer(0, out_pts)

            try:
                # Keep results visible even when rasters are added later.
                if parent_group.parent() == root:
                    idx = root.children().index(parent_group)
                    if idx != 0:
                        root.removeChildNode(parent_group)
                        root.insertChildNode(0, parent_group)
            except Exception as _exc:
                log_swallowed("slope_aspect_drafting_dialog.run_drafting", _exc)

            push_message(self.iface, "완료", "도면화 결과가 생성되었습니다.", level=0)
            success = True
            self.accept()

        except Exception as e:
            push_message(self.iface, "오류", f"도면화 실패: {str(e)}", level=2, duration=7)
            restore_ui_focus(self)
        finally:
            try:
                cleanup_files(intermediate_files)
            except Exception as _exc:
                log_swallowed("slope_aspect_drafting_dialog.run_drafting", _exc)
            if not success:
                restore_ui_focus(self)

    def _build_slope_grid_layer(
        self,
        slope_tif: str,
        dem_authid: str,
        step_cells: int,
        label_size_pt: float,
        slope_class_step: int,
    ) -> QgsVectorLayer:
        ds = gdal.Open(slope_tif, gdal.GA_ReadOnly)
        if ds is None:
            raise RuntimeError("경사도 래스터를 열 수 없습니다.")

        band = ds.GetRasterBand(1)
        gt = ds.GetGeoTransform()
        xsize = int(ds.RasterXSize)
        ysize = int(ds.RasterYSize)

        nx = (xsize + step_cells - 1) // step_cells
        ny = (ysize + step_cells - 1) // step_cells
        approx = int(nx * ny)
        max_cells = 200_000
        if approx > max_cells:
            ds = None
            raise RuntimeError(
                f"생성될 경사도 격자(폴리곤)가 너무 많습니다: 약 {approx:,}개 (최대 {max_cells:,}개). "
                "표시 간격(셀)을 늘려주세요."
            )

        layer = QgsVectorLayer(
            f"Polygon?crs={dem_authid}", "경사도_격자 (Slope grid)", "memory"
        )
        pr = layer.dataProvider()
        pr.addAttributes(
            [
                QgsField("slope_class", FT_INT),
                QgsField("slope_deg", FT_INT),
                QgsField("slope", FT_DOUBLE),
            ]
        )
        layer.updateFields()

        def corner_xy(col: int, row: int):
            x = gt[0] + col * gt[1] + row * gt[2]
            y = gt[3] + col * gt[4] + row * gt[5]
            return x, y

        feats = []
        # Read in strips whose height is a multiple of step_cells so grid
        # blocks stay aligned to the global grid; otherwise blocks starting
        # near a strip boundary overlap blocks of the next strip.
        chunk_rows = max(step_cells, (256 // step_cells) * step_cells if step_cells <= 256 else step_cells)
        for row0 in range(0, ysize, chunk_rows):
            rows_to_read = min(chunk_rows, ysize - row0)
            arr = band.ReadAsArray(0, row0, xsize, rows_to_read)
            if arr is None:
                continue

            for dr in range(0, rows_to_read, step_cells):
                row = row0 + dr
                row2 = min(row + step_cells, row0 + rows_to_read)
                if row2 <= row:
                    continue
                for col in range(0, xsize, step_cells):
                    col2 = min(col + step_cells, xsize)
                    if col2 <= col:
                        continue
                    _skip_446 = False
                    try:
                        sample_r = dr + ((row2 - row) // 2)
                        sample_c = col + ((col2 - col) // 2)
                        slope = float(arr[sample_r, sample_c])
                    except Exception as _exc:
                        log_swallowed("slope_aspect_drafting_dialog._build_slope_grid_layer", _exc)
                        log_swallowed("tools/slope_aspect_drafting_dialog.py:450 (_build_slope_grid_layer)", _exc)
                        _skip_446 = True
                    if _skip_446:
                        continue
                    if not math.isfinite(slope):
                        continue
                    if slope <= -9000:
                        continue

                    slope_deg = int(round(slope))
                    if slope_deg < 0:
                        slope_deg = 0
                    if slope_deg > 90:
                        slope_deg = 90
                    cls_step = max(1, int(slope_class_step))
                    slope_class = int((slope_deg // cls_step) * cls_step)
                    if slope_class < 0:
                        slope_class = 0
                    if slope_class > 90:
                        slope_class = 90

                    x1, y1 = corner_xy(col, row)
                    x2, y2 = corner_xy(col2, row)
                    x3, y3 = corner_xy(col2, row2)
                    x4, y4 = corner_xy(col, row2)

                    ring = [
                        QgsPointXY(x1, y1),
                        QgsPointXY(x2, y2),
                        QgsPointXY(x3, y3),
                        QgsPointXY(x4, y4),
                        QgsPointXY(x1, y1),
                    ]
                    geom = QgsGeometry.fromPolygonXY([ring])
                    if geom.isEmpty():
                        continue

                    f = QgsFeature(layer.fields())
                    f.setGeometry(geom)
                    f["slope_class"] = slope_class
                    f["slope_deg"] = slope_deg
                    f["slope"] = slope
                    feats.append(f)

                if len(feats) >= 2000:
                    pr.addFeatures(feats)
                    feats = []

        if feats:
            pr.addFeatures(feats)
        layer.updateExtents()

        out_layer = layer
        try:
            # Merge adjacent cells with the same 1-degree value to reduce label clutter.
            dissolve_params = {
                "INPUT": layer,
                "FIELD": ["slope_deg"],
                "OUTPUT": "memory:",
            }
            try:
                dissolve_params["SEPARATE_DISJOINT"] = True
            except Exception as _exc:
                log_swallowed("tools/slope_aspect_drafting_dialog.py:511 (_build_slope_grid_layer)", _exc)
            out_layer = processing.run("native:dissolve", dissolve_params)["OUTPUT"]
            try:
                out_layer = processing.run(
                    "native:multiparttosingleparts",
                    {"INPUT": out_layer, "OUTPUT": "memory:"},
                )["OUTPUT"]
            except Exception as _exc:
                log_swallowed("slope_aspect_drafting_dialog._build_slope_grid_layer", _exc)

            if hasattr(out_layer, "setName"):
                out_layer.setName("경사도_구역(1°) (Slope zones)")
        except Exception:
            out_layer = layer

        try:
            self._apply_slope_grid_style(
                out_layer,
                label_size_pt=label_size_pt,
                slope_class_step=slope_class_step,
            )
        except Exception as _exc:
            log_swallowed("tools/slope_aspect_drafting_dialog.py:533 (_build_slope_grid_layer)", _exc)

        ds = None
        return out_layer

    def _selected_polygons_as_mask_layer(self, layer: QgsVectorLayer) -> QgsVectorLayer:
        """Create a temporary memory polygon layer from selected features."""
        tmp = QgsVectorLayer(
            f"MultiPolygon?crs={layer.crs().authid()}", "tmp_mask_selected", "memory"
        )
        pr = tmp.dataProvider()
        feats = []
        for ft in layer.selectedFeatures():
            if ft.geometry() is None or ft.geometry().isEmpty():
                continue
            f = QgsFeature(tmp.fields())
            f.setGeometry(ft.geometry())
            feats.append(f)
        pr.addFeatures(feats)
        tmp.updateExtents()
        return tmp

    def _clip_raster_by_mask(self, in_raster: str, mask_layer, out_raster: str):
        """Clip raster to AOI polygon. Output is kept (not auto-deleted)."""
        processing.run(
            "gdal:cliprasterbymasklayer",
            {
                "INPUT": in_raster,
                "MASK": mask_layer,
                "NODATA": -9999,
                "DATA_TYPE": 6,  # Float32
                "ALPHA_BAND": False,
                "CROP_TO_CUTLINE": True,
                "KEEP_RESOLUTION": True,
                "OUTPUT": out_raster,
            },
        )

    def _apply_slope_grid_style(
        self, layer: QgsVectorLayer, label_size_pt: float, slope_class_step: int
    ):
        """Style slope grid polygons + labels (Reds, step classes)."""
        try:
            deg_idx = layer.fields().indexFromName("slope_deg")
            if deg_idx < 0:
                return

            cls_idx = layer.fields().indexFromName("slope_class")
            if cls_idx < 0:
                layer.dataProvider().addAttributes([QgsField("slope_class", FT_INT)])
                layer.updateFields()
                cls_idx = layer.fields().indexFromName("slope_class")

            ramp = None
            try:
                ramp = QgsStyle.defaultStyle().colorRamp("Reds")
            except Exception:
                ramp = None
            if ramp is None:
                ramp = QgsGradientColorRamp(QColor(255, 245, 240), QColor(103, 0, 13))

            cls_step = max(1, int(slope_class_step))

            # Populate a plain text label field to avoid expression compatibility issues.
            label_idx = layer.fields().indexFromName("label")
            if label_idx < 0:
                layer.dataProvider().addAttributes([QgsField("label", FT_STRING)])
                layer.updateFields()
                label_idx = layer.fields().indexFromName("label")

            changes = {}
            for ft in layer.getFeatures():
                _skip_606 = False
                try:
                    slope_deg = int(ft["slope_deg"])
                except Exception as _exc:
                    log_swallowed("slope_aspect_drafting_dialog._apply_slope_grid_style", _exc)
                    log_swallowed("tools/slope_aspect_drafting_dialog.py:608 (_apply_slope_grid_style)", _exc)
                    _skip_606 = True
                if _skip_606:
                    continue
                if slope_deg < 0:
                    slope_deg = 0
                if slope_deg > 90:
                    slope_deg = 90
                slope_class = int((slope_deg // cls_step) * cls_step)
                if slope_class < 0:
                    slope_class = 0
                if slope_class > 90:
                    slope_class = 90

                changes[ft.id()] = {label_idx: f"{slope_deg}°", cls_idx: slope_class}
            if changes:
                try:
                    layer.dataProvider().changeAttributeValues(changes)
                except Exception as _exc:
                    log_swallowed("slope_aspect_drafting_dialog._apply_slope_grid_style", _exc)

            vals = []
            try:
                vals = sorted(
                    int(v)
                    for v in layer.uniqueValues(cls_idx)
                    if v is not None and str(v) != ""
                )
            except Exception:
                vals = []
            if not vals:
                return

            cats = []
            for v in vals:
                v0 = int(v)
                v1 = min(int(v0 + cls_step), 90)
                if v0 >= 90:
                    label = "90°"
                else:
                    label = f"{v0}~{v1}°"

                pos = min(max(v0 / 90.0, 0.0), 1.0)
                c = ramp.color(pos)
                if c is None:
                    c = QColor(255, 0, 0)
                c.setAlpha(180)

                sym = QgsFillSymbol.createSimple(
                    {
                        "color": f"{c.red()},{c.green()},{c.blue()},{c.alpha()}",
                        "outline_color": "0,0,0,40",
                        "outline_width": "0.1",
                    }
                )
                cats.append(QgsRendererCategory(v0, sym, label))

            layer.setRenderer(QgsCategorizedSymbolRenderer("slope_class", cats))

            pal = QgsPalLayerSettings()
            pal.fieldName = "label"
            try:
                pal.isExpression = False
            except Exception as _exc:
                log_swallowed("tools/slope_aspect_drafting_dialog.py:670 (_apply_slope_grid_style)", _exc)
            try:
                pal.displayAll = True
                pal.allowOverlap = True
            except Exception as _exc:
                log_swallowed("tools/slope_aspect_drafting_dialog.py:675 (_apply_slope_grid_style)", _exc)
            try:
                pal.placement = Qgis.LabelPlacement.OverPoint
                pal.centroidInside = True
            except Exception as _exc:
                log_swallowed("slope_aspect_drafting_dialog._apply_slope_grid_style", _exc)
            fmt = QgsTextFormat()
            fmt.setSize(float(label_size_pt))
            fmt.setColor(QColor(20, 20, 20))
            buf = QgsTextBufferSettings()
            buf.setEnabled(True)
            buf.setColor(QColor(255, 255, 255, 230))
            buf.setSize(1.0)
            fmt.setBuffer(buf)
            pal.setFormat(fmt)
            layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
            layer.setLabelsEnabled(True)
            layer.triggerRepaint()
        except Exception as _exc:
            log_swallowed("slope_aspect_drafting_dialog._apply_slope_grid_style", _exc)

    def _build_aspect_arrow_layer(
        self,
        slope_tif: str,
        aspect_tif: str,
        dem_authid: str,
        step_cells: int,
        flat_thresh_deg: float,
        arrow_size_mm: float,
    ) -> QgsVectorLayer:
        ds_slope = gdal.Open(slope_tif, gdal.GA_ReadOnly)
        ds_aspect = gdal.Open(aspect_tif, gdal.GA_ReadOnly)
        if ds_slope is None or ds_aspect is None:
            raise RuntimeError("래스터를 열 수 없습니다.")

        band_slope = ds_slope.GetRasterBand(1)
        band_aspect = ds_aspect.GetRasterBand(1)
        gt = ds_slope.GetGeoTransform()
        xsize = int(ds_slope.RasterXSize)
        ysize = int(ds_slope.RasterYSize)

        nx = (xsize + step_cells - 1) // step_cells
        ny = (ysize + step_cells - 1) // step_cells
        approx = int(nx * ny)
        max_points = 300_000
        if approx > max_points:
            raise RuntimeError(
                f"생성될 화살표 점이 너무 많습니다: 약 {approx:,}개 (최대 {max_points:,}개). "
                "표시 간격(셀)을 늘려주세요."
            )

        layer = QgsVectorLayer(
            f"Point?crs={dem_authid}", "사면방향_화살표 (Aspect arrows)", "memory"
        )
        pr = layer.dataProvider()
        pr.addAttributes(
            [
                QgsField("aspect_deg", FT_INT),
                QgsField("aspect_45", FT_INT),
                QgsField("dir8", FT_STRING),
                QgsField("slope", FT_DOUBLE),
            ]
        )
        layer.updateFields()

        feats = []
        # Align the strip height to step_cells so the global sampling grid
        # (row0 + dr, step step_cells) is continuous across strip boundaries —
        # a fixed 256 not divisible by step_cells produced an uneven extra row
        # of arrows at every boundary.
        chunk_rows = max(int(step_cells), (256 // int(step_cells)) * int(step_cells)) if step_cells else 256
        for row0 in range(0, ysize, chunk_rows):
            rows_to_read = min(chunk_rows, ysize - row0)
            slope_arr = band_slope.ReadAsArray(0, row0, xsize, rows_to_read)
            aspect_arr = band_aspect.ReadAsArray(0, row0, xsize, rows_to_read)
            if slope_arr is None or aspect_arr is None:
                continue

            for dr in range(0, rows_to_read, step_cells):
                row = row0 + dr
                for col in range(0, xsize, step_cells):
                    _skip_757 = False
                    try:
                        slope = float(slope_arr[dr, col])
                        aspect = float(aspect_arr[dr, col])
                    except Exception as _exc:
                        log_swallowed("slope_aspect_drafting_dialog._build_aspect_arrow_layer", _exc)
                        log_swallowed("tools/slope_aspect_drafting_dialog.py:760 (_build_aspect_arrow_layer)", _exc)
                        _skip_757 = True
                    if _skip_757:
                        continue
                    if not math.isfinite(slope) or not math.isfinite(aspect):
                        continue
                    if slope <= float(flat_thresh_deg):
                        continue

                    aspect_deg = int(round(aspect)) % 360
                    bin_idx = int(((aspect_deg + 22.5) // 45) % 8)
                    aspect_45 = int(bin_idx * 45)
                    dir8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][bin_idx]

                    x = gt[0] + (col + 0.5) * gt[1] + (row + 0.5) * gt[2]
                    y = gt[3] + (col + 0.5) * gt[4] + (row + 0.5) * gt[5]

                    f = QgsFeature(layer.fields())
                    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
                    f["aspect_deg"] = aspect_deg
                    f["aspect_45"] = aspect_45
                    f["dir8"] = dir8
                    f["slope"] = slope
                    feats.append(f)

                if len(feats) >= 5000:
                    pr.addFeatures(feats)
                    feats = []

        if feats:
            pr.addFeatures(feats)
        layer.updateExtents()

        # Symbol: arrow marker rotated by quantized 45° aspect, colored by 8 directions.
        base_sym = QgsMarkerSymbol.createSimple(
            {
                "name": "arrow",
                "color": "0,0,0,200",
                "outline_color": "0,0,0,220",
                "outline_width": "0.1",
                "size": str(float(arrow_size_mm)),
            }
        )
        try:
            sl = base_sym.symbolLayer(0)
            if sl is not None:
                sl.setDataDefinedProperty(
                    SYMBOL_PROPERTY_ANGLE, QgsProperty.fromField("aspect_45")
                )
        except Exception as _exc:
            log_swallowed("tools/slope_aspect_drafting_dialog.py:808 (_build_aspect_arrow_layer)", _exc)

        colors = {
            "N": "228,26,28,200",
            "NE": "255,127,0,200",
            "E": "255,255,51,200",
            "SE": "77,175,74,200",
            "S": "0,191,255,200",
            "SW": "55,126,184,200",
            "W": "152,78,163,200",
            "NW": "247,129,191,200",
        }
        cats = []
        for key in ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]:
            sym = base_sym.clone()
            try:
                sym.setColor(QColor(*[int(x) for x in colors[key].split(",")]))
            except Exception as _exc:
                log_swallowed("slope_aspect_drafting_dialog._build_aspect_arrow_layer", _exc)
            cats.append(QgsRendererCategory(key, sym, key))

        layer.setRenderer(QgsCategorizedSymbolRenderer("dir8", cats))
        layer.setLabelsEnabled(False)
        layer.triggerRepaint()

        ds_slope = None
        ds_aspect = None
        return layer
