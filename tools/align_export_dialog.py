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
분석 결과 정렬/내보내기 (Align & Export Analysis Stack).

Philosophy
- ArchToolkit is first a set of *meaningful analyses* (terrain, curvature,
  viewshed, geochem, geology, AHP, ...). This tool does NOT invent variables;
  it takes the analysis-result rasters you already produced and aligns them to
  ONE common reference grid, then exports a model-ready stack + manifest.
- That keeps the analyses as the point, and predictive-model input as a tidy
  by-product.

Design
- QGIS built-ins only (gdal:warpreproject + QGIS layer API), per DEVELOPMENT.md.
- Reference grid is taken from a chosen raster layer (its CRS / extent / pixel
  size), with optional AOI clip and pixel-size override.
- Categorical outputs (by ArchToolkit metadata kind) resample with nearest
  neighbour; continuous outputs use bilinear.
- Runs each GDAL warp through QGIS' task manager so the progress dialog stays
  responsive and cancellation reaches the active subprocess.
"""

from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass
from typing import List, Optional

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QEventLoop, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateTransform,
    QgsProcessingAlgRunnerTask,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsPoint,
    QgsRasterDataProvider,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox

from .atomic_output import cleanup_staging_dir, create_staging_dir, publish_staging_dir
from .gdal_outcome import GdalOutcomeTracker
from .help_dialog import show_help_dialog
from .live_log_dialog import ensure_live_log_dialog
from .raster_grid_contract import (
    Extent,
    GridContractError,
    GridMismatchError,
    RasterGrid,
    canonical_gdal_target_grid,
    validate_grid,
)
from .utils import (
    get_archtoolkit_layer_metadata,
    is_categorical_raster_meta,
    log_exception,
    log_message,
    new_run_id,
    push_message,
    restore_ui_focus,
    set_archtoolkit_layer_metadata,
)

PARENT_GROUP_NAME = "ArchToolkit - 정렬 스택 (Aligned Stack)"
CONTINUOUS_NODATA = -9999.0


class _Cancelled(Exception):
    pass


class _GdalOutcomeFeedback(QgsProcessingFeedback):
    """Preserve GDAL diagnostics and the provider's localized exit-0 marker."""

    def __init__(self, success_marker):
        super().__init__()
        self.outcome = GdalOutcomeTracker(success_marker)

    def reportError(self, error, fatalError=False):
        self.outcome.record_diagnostic(str(error), fatal=bool(fatalError))
        super().reportError(error, fatalError)

    def pushInfo(self, info):
        self.outcome.record_info(str(info))
        super().pushInfo(info)


def _translated_gdal_success_marker() -> str:
    """Return QGIS GDAL provider's localized exit-0 marker, or fail closed."""
    try:
        from processing.algs.gdal.GdalUtils import GdalUtils

        marker = str(GdalUtils.tr("Process completed successfully"))
    except Exception as exc:
        raise RuntimeError(
            "QGIS GDAL 공급자의 정상 종료 표식을 확인할 수 없습니다."
        ) from exc
    if not marker.strip():
        raise RuntimeError("QGIS GDAL 공급자의 정상 종료 표식이 비어 있습니다.")
    return marker


def _qgs_rectangle_to_extent(rect: QgsRectangle) -> Extent:
    return Extent(
        rect.xMinimum(),
        rect.xMaximum(),
        rect.yMinimum(),
        rect.yMaximum(),
    )


def _raster_grid_from_layer(layer: QgsRasterLayer) -> RasterGrid:
    return RasterGrid(
        width=int(layer.width()),
        height=int(layer.height()),
        extent=_qgs_rectangle_to_extent(layer.extent()),
        resolution_x=abs(float(layer.rasterUnitsPerPixelX())),
        resolution_y=abs(float(layer.rasterUnitsPerPixelY())),
    )


def _nodata_equal(actual, expected) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    try:
        actual_float = float(actual)
        expected_float = float(expected)
    except (TypeError, ValueError):
        return False
    if math.isnan(actual_float) or math.isnan(expected_float):
        return math.isnan(actual_float) and math.isnan(expected_float)
    return math.isclose(actual_float, expected_float, rel_tol=0.0, abs_tol=1e-9)


def _source_nodata_values(layer: QgsRasterLayer, *, categorical: bool):
    provider = layer.dataProvider()
    if provider is None:
        raise RuntimeError(f"입력 래스터 데이터 공급자를 열 수 없습니다: {layer.name()}")
    values = []
    for band in range(1, int(layer.bandCount()) + 1):
        if categorical:
            try:
                has_nodata = bool(provider.sourceHasNoDataValue(band))
            except Exception:
                has_nodata = False
            if has_nodata:
                try:
                    values.append(float(provider.sourceNoDataValue(band)))
                except Exception:
                    values.append(None)
            else:
                values.append(None)
        else:
            values.append(CONTINUOUS_NODATA)
    return tuple(values)


def _ensure_supported_reference_grid(layer: QgsRasterLayer, px: float, *, pixel_override: bool) -> None:
    provider = layer.dataProvider()
    if provider is None:
        raise RuntimeError("기준 래스터 데이터 공급자를 열 수 없습니다.")

    try:
        origin = provider.transformCoordinates(
            QgsPoint(0, 0),
            QgsRasterDataProvider.TransformImageToLayer,
        )
        x_step = provider.transformCoordinates(
            QgsPoint(1, 0),
            QgsRasterDataProvider.TransformImageToLayer,
        )
        y_step = provider.transformCoordinates(
            QgsPoint(0, 1),
            QgsRasterDataProvider.TransformImageToLayer,
        )
    except Exception as exc:
        raise RuntimeError("기준 래스터의 격자 변환을 확인할 수 없습니다.") from exc

    tolerance = max(1e-9, abs(px) * 1e-9)
    coordinates = (
        float(origin.x()), float(origin.y()),
        float(x_step.x()), float(x_step.y()),
        float(y_step.x()), float(y_step.y()),
    )
    if not all(math.isfinite(value) for value in coordinates):
        raise RuntimeError("기준 래스터의 격자 변환 값이 유효하지 않습니다.")
    if (
        abs(float(x_step.y()) - float(origin.y())) > tolerance
        or abs(float(y_step.x()) - float(origin.x())) > tolerance
    ):
        raise RuntimeError(
            "회전되거나 기울어진 기준 래스터는 현재 정렬/내보내기에서 지원하지 않습니다."
        )

    if not pixel_override:
        try:
            px_y = abs(float(layer.rasterUnitsPerPixelY()))
        except Exception:
            px_y = 0.0
        if px_y <= 0.0 or not math.isclose(px, px_y, rel_tol=0.0, abs_tol=tolerance):
            raise RuntimeError(
                "비정사각 픽셀 기준 래스터는 현재 정렬/내보내기에서 지원하지 않습니다. "
                "명시적인 픽셀 크기를 지정하거나 정사각 격자 기준 래스터를 사용하세요."
            )


@dataclass
class _Item:
    layer_id: str
    name: str
    key: str
    kind: str
    units: str
    categorical: bool


@dataclass(frozen=True)
class _WarpValidationContract:
    crs: object
    grid: RasterGrid
    band_count: int
    nodata_values: tuple
    categorical: bool


def _safe_key(name: str, used: set) -> str:
    base = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(name or "layer")).strip("_")
    base = base or "layer"
    key = base
    i = 2
    while key in used:
        key = f"{base}_{i}"
        i += 1
    used.add(key)
    return key


def _aoi_extent_in_crs(aoi_layer, *, selected_only: bool, dst_crs) -> Optional[QgsRectangle]:
    if aoi_layer is None:
        return None
    try:
        if aoi_layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            return None
    except Exception:
        return None
    geom = None
    try:
        use_sel = selected_only and aoi_layer.selectedFeatureCount() > 0
        feats = aoi_layer.selectedFeatures() if use_sel else aoi_layer.getFeatures()
    except Exception:
        feats = aoi_layer.getFeatures()
    for f in feats:
        try:
            g = f.geometry()
        except Exception:
            continue
        if not g or g.isEmpty():
            continue
        geom = g if geom is None else geom.combine(g)
    if geom is None or geom.isEmpty():
        return None
    try:
        if aoi_layer.crs() != dst_crs:
            ct = QgsCoordinateTransform(aoi_layer.crs(), dst_crs, QgsProject.instance())
            g2 = type(geom)(geom)
            g2.transform(ct)
            geom = g2
        return geom.boundingBox()
    except Exception:
        return None


class AlignExportDialog(QtWidgets.QDialog):
    """Align selected analysis-result rasters to a common grid; export a stack."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._setup_ui()
        self._populate_layers()

    # -- UI ------------------------------------------------------------------
    def _setup_ui(self):
        self.setWindowTitle("분석 결과 정렬/내보내기 (Align & Export Stack)")
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            for name in ("align_export_icon.xpm", "terrain_icon.png", "icon.png"):
                p = os.path.join(plugin_dir, name)
                if os.path.exists(p):
                    self.setWindowIcon(QIcon(p))
                    break
        except Exception:
            pass

        layout = QtWidgets.QVBoxLayout(self)
        header = QtWidgets.QLabel(
            "<b>분석 결과 정렬/내보내기</b><br>"
            "이미 만든 분석 결과 래스터들을 <b>하나의 기준 격자</b>(CRS·범위·픽셀크기·NoData)로 맞춰 "
            "정렬하고, 예측모델용 스택+manifest로 내보냅니다.<br>"
            "<span style='color:#455a64;'>이 도구는 변수를 새로 만들지 않습니다 — 당신의 분석 결과를 모델 입력으로 정리합니다.</span>"
        )
        header.setWordWrap(True)
        header.setStyleSheet("background:#f1f8e9; padding:10px; border:1px solid #dcedc8; border-radius:4px;")
        layout.addWidget(header)

        grp_ref = QtWidgets.QGroupBox("1. 기준 격자")
        form = QtWidgets.QFormLayout(grp_ref)
        self.cmbRef = QgsMapLayerComboBox(grp_ref)
        self._set_filter(self.cmbRef, raster=True)
        form.addRow("기준 래스터:", self.cmbRef)
        self.spinPixel = QtWidgets.QDoubleSpinBox()
        self.spinPixel.setRange(0.0, 100000.0)
        self.spinPixel.setDecimals(3)
        self.spinPixel.setValue(0.0)
        self.spinPixel.setSpecialValueText("(기준 래스터 해상도)")
        form.addRow("픽셀 크기(선택):", self.spinPixel)
        self.cmbAoi = QgsMapLayerComboBox(grp_ref)
        self._set_filter(self.cmbAoi, raster=False)
        try:
            self.cmbAoi.setAllowEmptyLayer(True)
        except Exception:
            pass
        form.addRow("AOI 자르기(선택):", self.cmbAoi)
        self.chkAoiSelected = QtWidgets.QCheckBox("AOI 선택 피처만 사용")
        form.addRow("", self.chkAoiSelected)
        layout.addWidget(grp_ref)

        grp_list = QtWidgets.QGroupBox("2. 정렬할 래스터 선택")
        vl = QtWidgets.QVBoxLayout(grp_list)
        hint = QtWidgets.QLabel("ArchToolkit 분석 결과는 자동으로 체크됩니다. 필요에 맞게 조정하세요.")
        hint.setStyleSheet("color:#455a64;")
        vl.addWidget(hint)
        self.listLayers = QtWidgets.QListWidget()
        self.listLayers.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        vl.addWidget(self.listLayers, 1)
        row = QtWidgets.QHBoxLayout()
        self.btnAll = QtWidgets.QPushButton("모두 선택")
        self.btnNone = QtWidgets.QPushButton("모두 해제")
        self.btnArch = QtWidgets.QPushButton("ArchToolkit 결과만")
        self.btnAll.clicked.connect(lambda: self._check_all(True))
        self.btnNone.clicked.connect(lambda: self._check_all(False))
        self.btnArch.clicked.connect(self._check_arch_only)
        row.addWidget(self.btnAll)
        row.addWidget(self.btnNone)
        row.addWidget(self.btnArch)
        row.addStretch(1)
        vl.addLayout(row)
        layout.addWidget(grp_list, 1)

        grp_out = QtWidgets.QGroupBox("3. 출력")
        fout = QtWidgets.QFormLayout(grp_out)
        self.chkAddToProject = QtWidgets.QCheckBox("정렬 결과를 프로젝트에 추가")
        self.chkAddToProject.setChecked(True)
        fout.addRow("", self.chkAddToProject)
        rr = QtWidgets.QHBoxLayout()
        self.txtExport = QtWidgets.QLineEdit()
        self.txtExport.setPlaceholderText("GeoTIFF 스택과 manifest를 저장할 폴더(필수)")
        self.btnBrowse = QtWidgets.QPushButton("찾기…")
        self.btnBrowse.clicked.connect(self._on_browse)
        rr.addWidget(self.txtExport, 1)
        rr.addWidget(self.btnBrowse)
        w = QtWidgets.QWidget()
        w.setLayout(rr)
        fout.addRow("내보내기 폴더:", w)
        layout.addWidget(grp_out)

        btn_row = QtWidgets.QHBoxLayout()
        self.btnRun = QtWidgets.QPushButton("정렬/내보내기")
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
        self.resize(660, 640)

    def _set_filter(self, combo, *, raster: bool):
        try:
            from qgis.core import QgsMapLayerProxyModel
            if raster:
                try:
                    combo.setFilters(QgsMapLayerProxyModel.Filter.RasterLayer)
                except Exception:
                    combo.setFilters(QgsMapLayerProxyModel.RasterLayer)
            else:
                try:
                    combo.setFilters(QgsMapLayerProxyModel.Filter.PolygonLayer)
                except Exception:
                    combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        except Exception:
            pass

    def _populate_layers(self):
        self.listLayers.clear()
        try:
            layers = list(QgsProject.instance().mapLayers().values())
        except Exception:
            layers = []
        for lyr in layers:
            if not isinstance(lyr, QgsRasterLayer) or not lyr.isValid():
                continue
            meta = get_archtoolkit_layer_metadata(lyr) or {}
            is_arch = bool(meta.get("tool_id") or meta.get("kind"))
            kind = str(meta.get("kind") or "")
            label = lyr.name() + (f"   [{meta.get('tool_id')}/{kind}]" if is_arch else "")
            item = QtWidgets.QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if is_arch else Qt.Unchecked)
            item.setData(Qt.UserRole, lyr.id())
            item.setData(Qt.UserRole + 1, bool(is_arch))
            self.listLayers.addItem(item)
        if self.listLayers.count() == 0:
            item = QtWidgets.QListWidgetItem("(프로젝트에 래스터 레이어가 없습니다)")
            item.setFlags(Qt.NoItemFlags)
            self.listLayers.addItem(item)

    def _check_all(self, state: bool):
        for i in range(self.listLayers.count()):
            it = self.listLayers.item(i)
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(Qt.Checked if state else Qt.Unchecked)

    def _check_arch_only(self):
        for i in range(self.listLayers.count()):
            it = self.listLayers.item(i)
            if it.flags() & Qt.ItemIsUserCheckable:
                is_arch = bool(it.data(Qt.UserRole + 1))
                it.setCheckState(Qt.Checked if is_arch else Qt.Unchecked)

    def _on_browse(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "내보내기 폴더 선택")
        if d:
            self.txtExport.setText(d)

    # -- run -----------------------------------------------------------------
    def _selected_items(self) -> List[_Item]:
        out: List[_Item] = []
        used: set = set()
        project = QgsProject.instance()
        for i in range(self.listLayers.count()):
            it = self.listLayers.item(i)
            if not (it.flags() & Qt.ItemIsUserCheckable) or it.checkState() != Qt.Checked:
                continue
            lid = str(it.data(Qt.UserRole) or "")
            lyr = project.mapLayer(lid)
            if not isinstance(lyr, QgsRasterLayer) or not lyr.isValid():
                continue
            meta = get_archtoolkit_layer_metadata(lyr) or {}
            kind = str(meta.get("kind") or "")
            units = str(meta.get("units") or "")
            # Categorical → nearest resampling (bilinear would blend class codes
            # into meaningless fractional values). Shared helper keeps this in
            # lockstep with the covariate report's exclusion rule.
            categorical = is_categorical_raster_meta(meta)
            out.append(_Item(lid, lyr.name(), _safe_key(lyr.name(), used), kind, units, categorical))
        return out

    def _on_run(self):
        ref = self.cmbRef.currentLayer()
        if ref is None or not isinstance(ref, QgsRasterLayer) or not ref.isValid():
            push_message(self.iface, "오류", "기준 래스터를 선택하세요.", level=2, duration=6)
            return
        items = self._selected_items()
        if not items:
            push_message(self.iface, "오류", "정렬할 래스터를 하나 이상 선택하세요.", level=2, duration=6)
            return

        export_dir = str(self.txtExport.text() or "").strip()
        if not export_dir:
            push_message(
                self.iface,
                "오류",
                "완성된 결과를 보관할 내보내기 폴더를 지정하세요.",
                level=2,
                duration=7,
            )
            return
        try:
            os.makedirs(export_dir, exist_ok=True)
        except Exception as e:
            push_message(self.iface, "오류", f"내보내기 폴더를 만들 수 없습니다: {e}", level=2, duration=7)
            return

        px = float(self.spinPixel.value())
        pixel_override = px > 0.0
        if px <= 0:
            try:
                px = float(ref.rasterUnitsPerPixelX())
            except Exception:
                px = 0.0
        if px <= 0:
            push_message(self.iface, "오류", "기준 픽셀 크기를 확인할 수 없습니다.", level=2, duration=6)
            return

        try:
            _ensure_supported_reference_grid(ref, px, pixel_override=pixel_override)
        except Exception as e:
            push_message(self.iface, "오류", str(e), level=2, duration=8)
            return

        ref_crs = ref.crs()
        requested_extent = None
        aoi = self.cmbAoi.currentLayer()
        if isinstance(aoi, QgsVectorLayer):
            ext = _aoi_extent_in_crs(aoi, selected_only=self.chkAoiSelected.isChecked(), dst_crs=ref.crs())
            if ext is not None and not ext.isEmpty():
                requested_extent = _qgs_rectangle_to_extent(ext)
        if requested_extent is None:
            e = ref.extent()
            requested_extent = _qgs_rectangle_to_extent(e)
        try:
            target_grid = canonical_gdal_target_grid(requested_extent, px, px)
        except GridContractError as e:
            push_message(self.iface, "오류", f"목표 격자를 계산할 수 없습니다: {e}", level=2, duration=8)
            return
        extent_str = (
            f"{requested_extent.xmin},{requested_extent.xmax},"
            f"{requested_extent.ymin},{requested_extent.ymax}"
        )

        run_id = new_run_id("align")
        try:
            ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)
        except Exception:
            pass

        try:
            staging_dir = create_staging_dir(export_dir, run_id, purpose="align")
        except Exception as e:
            log_exception("Align staging directory error", e)
            push_message(self.iface, "오류", f"임시 출력 폴더를 만들 수 없습니다: {e}", level=2, duration=8)
            restore_ui_focus(self)
            return

        progress = QtWidgets.QProgressDialog("래스터 정렬 중…", "취소", 0, len(items), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        QtWidgets.QApplication.processEvents()

        outputs: List[dict] = []
        self.btnRun.setEnabled(False)
        try:
            for idx, item in enumerate(items):
                QtWidgets.QApplication.processEvents()
                if progress.wasCanceled():
                    raise _Cancelled()
                progress.setLabelText(f"정렬 중: {item.name} ({idx + 1}/{len(items)})")
                progress.setValue(idx)
                QtWidgets.QApplication.processEvents()
                if progress.wasCanceled():
                    raise _Cancelled()
                src_layer = QgsProject.instance().mapLayer(item.layer_id)
                if src_layer is None:
                    raise RuntimeError(f"입력 레이어를 찾을 수 없습니다: {item.name}")
                src = str(src_layer.source() or "").split("|", 1)[0].strip()
                if not src:
                    raise RuntimeError(f"입력 경로를 확인할 수 없습니다: {item.name}")
                expected = _WarpValidationContract(
                    crs=ref_crs,
                    grid=target_grid,
                    band_count=int(src_layer.bandCount()),
                    nodata_values=_source_nodata_values(src_layer, categorical=item.categorical),
                    categorical=item.categorical,
                )
                out_path = os.path.join(staging_dir, f"{item.key}.tif")
                self._warp(
                    src,
                    out_path,
                    px,
                    extent_str,
                    ref_crs,
                    nearest=item.categorical,
                    progress=progress,
                )
                QtWidgets.QApplication.processEvents()
                if progress.wasCanceled():
                    raise _Cancelled()
                if not os.path.isfile(out_path):
                    raise RuntimeError(f"정렬 출력이 생성되지 않았습니다: {item.name}")
                self._validate_warp_output(out_path, item.name, expected)
                outputs.append({
                    "key": item.key, "path": out_path, "source": item.name,
                    "kind": item.kind, "units": item.units,
                    "resampling": "nearest" if item.categorical else "bilinear",
                })
                progress.setValue(idx + 1)
            if len(outputs) != len(items):
                raise RuntimeError(f"정렬 결과 수가 입력과 다릅니다: {len(outputs)}/{len(items)}")
        except _Cancelled:
            try:
                cleanup_staging_dir(staging_dir)
            except Exception as cleanup_error:
                log_exception("Align cancellation cleanup error", cleanup_error)
            push_message(
                self.iface,
                "정렬/내보내기",
                "취소됨: 부분 결과를 게시하거나 프로젝트에 추가하지 않았습니다.",
                level=1,
                duration=8,
            )
            log_message(f"Align & export cancelled (run {run_id})", level=Qgis.Warning)
            restore_ui_focus(self)
            return
        except Exception as e:
            try:
                cleanup_staging_dir(staging_dir)
            except Exception as cleanup_error:
                log_exception("Align failure cleanup error", cleanup_error)
            log_exception("Align & export failed", e)
            push_message(self.iface, "오류", f"정렬/내보내기에 실패했습니다: {e}", level=2, duration=10)
            restore_ui_focus(self)
            return
        finally:
            self.btnRun.setEnabled(True)
            try:
                progress.close()
            except Exception:
                pass

        grid = {
            "crs": str(ref.crs().authid() or ""),
            "crs_wkt": "" if ref.crs().authid() else str(ref.crs().toWkt() or ""),
            "pixel_size": px,
            "pixel_size_x": target_grid.resolution_x,
            "pixel_size_y": target_grid.resolution_y,
            "width": target_grid.width,
            "height": target_grid.height,
            "requested_extent": {
                "xmin": requested_extent.xmin,
                "xmax": requested_extent.xmax,
                "ymin": requested_extent.ymin,
                "ymax": requested_extent.ymax,
            },
            "actual_extent": {
                "xmin": target_grid.extent.xmin,
                "xmax": target_grid.extent.xmax,
                "ymin": target_grid.extent.ymin,
                "ymax": target_grid.extent.ymax,
            },
            "extent": (
                f"{target_grid.extent.xmin},{target_grid.extent.xmax},"
                f"{target_grid.extent.ymin},{target_grid.extent.ymax}"
            ),
            "continuous_nodata": CONTINUOUS_NODATA,
            "run_id": run_id,
        }
        try:
            self._write_manifest(
                staging_dir,
                outputs,
                grid=grid,
            )
            final_dir = publish_staging_dir(
                staging_dir,
                export_dir,
                f"aligned_stack_{run_id}",
            )
            for output in outputs:
                output["path"] = os.path.join(final_dir, os.path.basename(output["path"]))
        except Exception as e:
            try:
                cleanup_staging_dir(staging_dir)
            except Exception:
                pass
            log_exception("Align output publication error", e)
            push_message(self.iface, "오류", f"완성된 결과를 게시하지 못했습니다: {e}", level=2, duration=10)
            restore_ui_focus(self)
            return

        layer_add_error = None
        if self.chkAddToProject.isChecked():
            try:
                self._add_layers(outputs, run_id)
            except Exception as e:
                log_exception("Add aligned layers error", e)
                layer_add_error = e

        msg = f"완료: {len(outputs)}개 정렬"
        msg += f" → {final_dir}"
        if layer_add_error is not None:
            msg += " (파일은 완성됐지만 프로젝트 추가에 실패했습니다)"
        level = 1 if layer_add_error is not None else 0
        push_message(self.iface, "정렬/내보내기", msg, level=level, duration=10)
        log_level = Qgis.Warning if layer_add_error is not None else Qgis.Info
        log_message(f"Align & export done: {len(outputs)} rasters (run {run_id})", level=log_level)
        restore_ui_focus(self)

    def _warp(self, src, out, px, extent_str, ref_crs, *, nearest: bool, progress):
        if progress.wasCanceled():
            raise _Cancelled()
        # Categorical layers keep their input type (often Byte) and inherit the
        # source NoData (nearest resampling preserves codes). Continuous layers
        # are forced to Float32 so the -9999 NoData is always representable —
        # with DATA_TYPE=0 a continuous Byte product (e.g. 0-255 hillshade)
        # would have -9999 clamped, turning valid value 0 into NoData.
        params = {
            "INPUT": src,
            "SOURCE_CRS": None,
            "TARGET_CRS": ref_crs,
            "RESAMPLING": 0 if nearest else 1,  # 0=nearest, 1=bilinear
            "NODATA": None if nearest else CONTINUOUS_NODATA,
            "TARGET_RESOLUTION": px,
            "OPTIONS": "",
            "DATA_TYPE": 0 if nearest else 6,  # categorical: keep type / continuous: Float32
            "TARGET_EXTENT": extent_str,
            "TARGET_EXTENT_CRS": ref_crs,
            "MULTITHREADING": False,
            "EXTRA": "",
            "OUTPUT": out,
        }
        algorithm = QgsApplication.processingRegistry().algorithmById("gdal:warpreproject")
        if algorithm is None:
            raise RuntimeError("QGIS GDAL 정렬 알고리즘(gdal:warpreproject)을 찾을 수 없습니다.")

        context = QgsProcessingContext()
        context.setProject(QgsProject.instance())
        feedback = _GdalOutcomeFeedback(_translated_gdal_success_marker())
        task = QgsProcessingAlgRunnerTask(algorithm, params, context, feedback)
        loop = QEventLoop(self)
        state = {"finished": False, "successful": False, "results": {}}

        def _finished(successful, results):
            state["finished"] = True
            state["successful"] = bool(successful)
            state["results"] = dict(results or {})
            loop.quit()

        def _cancel_active_warp():
            feedback.cancel()
            task.cancel()

        task.executed.connect(_finished)
        progress.canceled.connect(_cancel_active_warp)
        try:
            task_id = QgsApplication.taskManager().addTask(task)
            if not task_id:
                raise RuntimeError("GDAL 정렬 작업을 QGIS 작업 관리자에 등록하지 못했습니다.")
            loop.exec_()
        finally:
            try:
                progress.canceled.disconnect(_cancel_active_warp)
            except Exception:
                pass

        if progress.wasCanceled() or feedback.isCanceled() or task.algorithmCanceled():
            raise _Cancelled()
        if not state["finished"] or not state["successful"]:
            diagnostics = feedback.outcome.decide().diagnostics
            details = " | ".join(item.message for item in diagnostics[-3:])
            suffix = f": {details[:1200]}" if details else ""
            raise RuntimeError(f"GDAL 정렬 작업이 정상적으로 완료되지 않았습니다{suffix}")
        outcome = feedback.outcome.decide()
        if not outcome.succeeded:
            details = " | ".join(item.message for item in outcome.diagnostics[-3:])
            details = details or outcome.detail
            raise RuntimeError(f"GDAL 정렬 종료 상태를 확인하지 못했습니다: {details[:1200]}")
        if outcome.diagnostics:
            details = " | ".join(item.message for item in outcome.diagnostics[-3:])
            log_message(
                f"GDAL alignment completed with non-fatal diagnostics: {details[:1200]}",
                level=Qgis.Warning,
            )
        result_path = str(state["results"].get("OUTPUT") or "")
        if result_path and os.path.realpath(result_path) != os.path.realpath(out):
            raise RuntimeError(f"GDAL 출력 경로가 요청과 다릅니다: {result_path}")
        return out

    def _validate_warp_output(self, path, source_name, expected):
        layer = QgsRasterLayer(path, "ArchToolkit alignment validation")
        if not layer.isValid():
            raise RuntimeError(f"정렬 결과를 열 수 없습니다: {source_name}")
        if layer.bandCount() < 1 or layer.width() < 1 or layer.height() < 1:
            raise RuntimeError(f"정렬 결과 격자가 비어 있습니다: {source_name}")

        actual_crs = layer.crs()
        if expected.crs and actual_crs and actual_crs != expected.crs:
            actual_label = str(actual_crs.authid() or actual_crs.description() or "")
            expected_label = str(expected.crs.authid() or expected.crs.description() or "")
            raise RuntimeError(
                f"정렬 결과 CRS가 기준과 다릅니다: {source_name} ({actual_label} != {expected_label})"
            )

        try:
            actual_grid = _raster_grid_from_layer(layer)
            validate_grid(actual_grid, expected.grid)
        except GridMismatchError as e:
            raise RuntimeError(
                f"정렬 결과 격자가 기준과 다릅니다: {source_name} ({', '.join(e.fields)})"
            ) from e
        except GridContractError as e:
            raise RuntimeError(f"정렬 결과 격자를 확인할 수 없습니다: {source_name} ({e})") from e

        actual_band_count = int(layer.bandCount())
        if actual_band_count != expected.band_count:
            raise RuntimeError(
                f"정렬 결과 band 수가 입력과 다릅니다: {source_name} "
                f"({actual_band_count} != {expected.band_count})"
            )

        provider = layer.dataProvider()
        if provider is None:
            raise RuntimeError(f"정렬 결과 데이터 공급자를 열 수 없습니다: {source_name}")

        if len(expected.nodata_values) != actual_band_count:
            raise RuntimeError(f"정렬 결과 NoData 계약이 band 수와 맞지 않습니다: {source_name}")
        for band in range(1, actual_band_count + 1):
            expected_nodata = expected.nodata_values[band - 1]
            try:
                has_nodata = bool(provider.sourceHasNoDataValue(band))
                actual_nodata = float(provider.sourceNoDataValue(band)) if has_nodata else None
            except Exception:
                has_nodata = False
                actual_nodata = None
            if not _nodata_equal(actual_nodata, expected_nodata):
                expected_label = "없음" if expected_nodata is None else expected_nodata
                actual_label = "없음" if actual_nodata is None else actual_nodata
                raise RuntimeError(
                    f"정렬 결과 NoData가 기준과 다릅니다: {source_name} "
                    f"band {band} ({actual_label} != {expected_label})"
                )

            sample_width = min(64, layer.width())
            sample_height = min(64, layer.height())
            block = provider.block(band, layer.extent(), sample_width, sample_height)
            if block is None or not block.isValid():
                raise RuntimeError(f"정렬 결과 픽셀을 읽을 수 없습니다: {source_name} band {band}")

    def _write_manifest(self, export_dir, outputs, grid=None):
        # Reference grid → its own JSON sidecar so the CSV's first row is the
        # real column header (a bare `pandas.read_csv` / csv.DictReader used
        # to mis-parse a leading `# reference_grid` comment row as the header).
        if grid:
            with open(os.path.join(export_dir, "aligned_stack_grid.json"), "w", encoding="utf-8") as gf:
                json.dump(dict(grid), gf, ensure_ascii=False, indent=2)

        path = os.path.join(export_dir, "aligned_stack_manifest.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["variable", "file", "source_layer", "kind", "units", "resampling"])
            for o in outputs:
                w.writerow([o["key"], os.path.basename(o["path"]), o["source"],
                            o["kind"], o["units"], o["resampling"]])

    def _add_layers(self, outputs, run_id):
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        layers = []
        for o in outputs:
            lyr = QgsRasterLayer(o["path"], f"{o['source']} (정렬)")
            if not lyr.isValid():
                raise RuntimeError(f"정렬 결과 레이어를 열 수 없습니다: {o['path']}")
            set_archtoolkit_layer_metadata(
                lyr, tool_id="align_export", run_id=run_id,
                kind=o["kind"] or "aligned", units=o["units"],
                params={"variable": o["key"], "source_layer": o["source"],
                        "resampling": o["resampling"]},
            )
            layers.append(lyr)

        parent = root.findGroup(PARENT_GROUP_NAME)
        parent_created = parent is None
        if parent is None:
            parent = root.insertGroup(0, PARENT_GROUP_NAME)
        group = parent.insertGroup(0, f"정렬_{run_id}")
        group.setExpanded(False)
        added_ids = []
        try:
            for lyr in layers:
                project.addMapLayer(lyr, False)
                added_ids.append(lyr.id())
                group.insertLayer(0, lyr)
        except Exception:
            for layer_id in added_ids:
                project.removeMapLayer(layer_id)
            parent.removeChildNode(group)
            if parent_created:
                root.removeChildNode(parent)
            raise

    def _on_help(self):
        html = (
            "<h3>분석 결과 정렬/내보내기</h3>"
            "<p>이미 실행한 분석 결과 래스터들을 <b>하나의 기준 격자</b>(CRS·범위·픽셀크기·NoData)로 맞춰 "
            "정렬하고, 예측모델용 스택으로 내보냅니다. 이 도구는 <b>변수를 새로 만들지 않습니다</b> — "
            "당신의 분석을 모델 입력으로 정리하는 하위 유틸리티입니다.</p>"
            "<h4>사용</h4>"
            "<ol>"
            "<li><b>기준 래스터</b>를 고릅니다(그 격자에 모두 맞춰집니다). 필요하면 픽셀 크기/AOI로 조정.</li>"
            "<li><b>정렬할 래스터</b>를 체크합니다. ArchToolkit 분석 결과는 자동 체크됩니다.</li>"
            "<li><b>내보내기 폴더</b>를 지정합니다. 결과는 실행별 "
            "<code>aligned_stack_&lt;run_id&gt;</code> 폴더에 GeoTIFF와 manifest로 함께 게시됩니다.</li>"
            "</ol>"
            "<h4>리샘플</h4>"
            "<p>범주형 결과(지질/등급 등, 메타데이터 <code>kind</code> 기준)는 최근접(nearest), "
            "연속형은 이중선형(bilinear)으로 재배열합니다.</p>"
            "<p style='color:#455a64'>QGIS 기본 구성(GDAL)만 사용합니다.</p>"
        )
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            show_help_dialog(parent=self, title="정렬/내보내기 도움말", html=html, plugin_dir=plugin_dir)
        except Exception:
            pass
