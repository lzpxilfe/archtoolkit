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
- Categorical outputs (by ArchToolkit metadata kind/units/tool_id) resample
  with nearest neighbour; so do circular outputs (aspect and other directions
  in degrees, whose linear average points the wrong way). Continuous outputs
  use bilinear. A raster with no ArchToolkit metadata is of unknown meaning:
  it defaults to bilinear and is marked "unknown" in the manifest, unless a
  pixel sample reads as integer class codes, in which case it gets nearest.
- The common grid is CRS + extent + pixel size. NoData is decided per raster
  (continuous: -9999; categorical: the source's own value or a sentinel) and
  recorded in the manifest's ``nodata`` column.
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
)
from .qtcompat import RBS_ALL, RBS_MIN, RBS_MAX
from qgis.gui import QgsMapLayerComboBox

from .aoi_extent import resolve_aoi_extent
from .atomic_output import cleanup_staging_dir, create_staging_dir, publish_staging_dir
from .gdal_outcome import GdalOutcomeTracker
from .help_dialog import show_help_dialog
from . import dialog_memory
from .icons import icon as plugin_icon
from .live_log_dialog import ensure_live_log_dialog
from .predictor_naming import assign_variable_keys
from .raster_grid_contract import (
    Extent,
    GridContractError,
    GridMismatchError,
    RasterGrid,
    canonical_gdal_target_grid,
    validate_grid,
)
from .raster_semantics import (
    CLASS_CODE_MAX_DISTINCT,
    CLASS_CODE_TYPES,
    choose_nodata_sentinel,
    is_circular_meta,
    looks_like_class_codes,
)
from .utils import (
    log_swallowed,
    get_archtoolkit_layer_metadata,
    is_categorical_raster_meta,
    log_exception,
    log_message,
    new_run_id,
    push_message,
    restore_ui_focus,
    set_archtoolkit_layer_metadata,
    split_qgis_source_path,
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


def _band_type_name(provider, band: int) -> str:
    """GDAL type name for a band, or "" when it cannot be determined."""
    try:
        data_type = provider.dataType(band)
    except Exception:
        return ""
    for holder in (getattr(Qgis, "DataType", None), Qgis):
        if holder is None:
            continue
        for name in ("Byte", "Int8", "UInt16", "Int16", "UInt32", "Int32",
                     "Float32", "Float64"):
            member = getattr(holder, name, None)
            if member is not None and member == data_type:
                return name
    return ""


def _categorical_output_nodata(layer: QgsRasterLayer):
    """Decide the NoData value a categorical output should carry.

    Class rasters used to be warped with ``NODATA=None``, so a source with no
    NoData produced an export with none either. That is not a cosmetic gap:
    with no NoData the consumer guesses the mask from the array, the warp's own
    padding reads as a real class code, and the checks that would have caught
    it (high-nodata warning, presence-on-nodata) cannot fire.

    Preference order: reuse the source's own value when every band agrees -
    that keeps the file describing itself the way its producer meant - then a
    sentinel outside the observed code range. Returns ``(value, reason)`` where
    a ``None`` value means no safe choice was found and the caller should warn
    rather than invent one.
    """
    provider = layer.dataProvider()
    if provider is None:
        raise RuntimeError(f"입력 래스터 데이터 공급자를 열 수 없습니다: {layer.name()}")
    band_count = int(layer.bandCount())

    source_values = []
    for band in range(1, band_count + 1):
        try:
            if provider.sourceHasNoDataValue(band):
                source_values.append(float(provider.sourceNoDataValue(band)))
            else:
                source_values.append(None)
        except Exception:
            source_values.append(None)

    if source_values and all(v is not None for v in source_values):
        first = source_values[0]
        if all(_nodata_equal(v, first) for v in source_values):
            return first, "source"
        # Bands disagree. Forcing one value onto the others would change what
        # the other bands mean, so leave it alone and let the caller say so.
        return None, "bands_disagree"

    if band_count != 1:
        # The sentinel is chosen from band 1's value range; stamping it across
        # the other bands could land inside their data. Every categorical
        # raster this plugin produces is single-band, so refuse rather than
        # guess for the case that should not arise.
        return None, "multiband"

    type_name = _band_type_name(provider, 1)
    try:
        # A full statistics pass, but only for a class raster that declared no
        # NoData - rare, and the alternative is shipping a file whose nodata
        # nothing downstream can verify.
        log_message(
            f"범주형 NoData 결정을 위해 값 범위를 확인합니다: {layer.name()}",
            level=Qgis.MessageLevel.Info,
        )
        stats = provider.bandStatistics(1, RBS_MIN | RBS_MAX)
        data_min, data_max = float(stats.minimumValue), float(stats.maximumValue)
    except Exception:
        return None, "no_statistics"

    sentinel = choose_nodata_sentinel(type_name, data_min, data_max)
    if sentinel is None:
        return None, "no_safe_value"
    return float(sentinel), "sentinel"


def _source_nodata_per_band(layer: QgsRasterLayer):
    """Each band's own source NoData, or None where it has none."""
    provider = layer.dataProvider()
    if provider is None:
        raise RuntimeError(f"입력 래스터 데이터 공급자를 열 수 없습니다: {layer.name()}")
    values = []
    for band in range(1, int(layer.bandCount()) + 1):
        try:
            values.append(float(provider.sourceNoDataValue(band))
                          if provider.sourceHasNoDataValue(band) else None)
        except Exception:
            values.append(None)
    return tuple(values)


def _expected_nodata_values(layer: QgsRasterLayer, nodata):
    """What each output band's NoData must be, given the value passed to warp.

    ``nodata=None`` means the warp was left to inherit, so the expectation is
    the source's own per-band values - not None for every band. Collapsing
    that to None would reject a perfectly good multi-band output whose bands
    declare different NoData values.
    """
    band_count = max(1, int(layer.bandCount()))
    if nodata is None:
        return _source_nodata_per_band(layer)
    return tuple([nodata] * band_count)


def _band_valid_count(provider, band: int) -> Optional[int]:
    """Number of non-NoData cells in a band from full-resolution statistics, or None."""
    try:
        stats = provider.bandStatistics(int(band), RBS_ALL, QgsRectangle(), 0)
        return int(stats.elementCount)
    except Exception as exc:
        log_swallowed("align_export_dialog._band_valid_count", exc)
        return None


def _valid_fraction(block) -> Optional[float]:
    """Share of cells in a raster block that are not NoData, or None if unreadable.

    The block is the decimated sample the validator already reads, so this
    costs nothing extra. A block with no NoData declared counts as fully
    valid - there is nothing to mask in that case.
    """
    try:
        rows, cols = int(block.height()), int(block.width())
        total = rows * cols
        if total <= 0:
            return None
        valid = 0
        for row in range(rows):
            for col in range(cols):
                if not block.isNoData(row, col):
                    valid += 1
        return valid / float(total)
    except Exception as exc:
        log_swallowed("align_export_dialog._valid_fraction", exc)
        return None


def _sample_looks_like_class_codes(layer: QgsRasterLayer) -> bool:
    """Pixel-sample heuristic for a raster that carries no ArchToolkit metadata.

    Decision rule lives in :func:`tools.raster_semantics.looks_like_class_codes`
    (unit-tested); this only feeds it the band type and a decimated sample of
    the valid cells. Anything unreadable resolves to False, i.e. the
    continuous default, so a failure here can only leave behaviour unchanged.
    """
    try:
        provider = layer.dataProvider()
        if provider is None or int(layer.bandCount()) != 1:
            return False
        type_name = _band_type_name(provider, 1)
        if type_name not in CLASS_CODE_TYPES:
            return False
        block = provider.block(
            1, layer.extent(), min(64, int(layer.width())), min(64, int(layer.height())))
        if block is None or not block.isValid():
            return False
        values = (
            block.value(row, col)
            for row in range(int(block.height()))
            for col in range(int(block.width()))
            if not block.isNoData(row, col)
        )
        return looks_like_class_codes(type_name, values)
    except Exception as exc:
        log_swallowed("align_export_dialog._sample_looks_like_class_codes", exc)
        return False


def _crs_label(crs) -> str:
    try:
        if crs is None or not crs.isValid():
            return ""
        return str(crs.authid() or crs.description() or "")
    except Exception as exc:
        log_swallowed("align_export_dialog._crs_label", exc)
        return ""


def _ensure_supported_reference_grid(layer: QgsRasterLayer, px: float, *, pixel_override: bool) -> None:
    provider = layer.dataProvider()
    if provider is None:
        raise RuntimeError("기준 래스터 데이터 공급자를 열 수 없습니다.")

    try:
        origin = provider.transformCoordinates(
            QgsPoint(0, 0),
            QgsRasterDataProvider.TransformType.TransformImageToLayer,
        )
        x_step = provider.transformCoordinates(
            QgsPoint(1, 0),
            QgsRasterDataProvider.TransformType.TransformImageToLayer,
        )
        y_step = provider.transformCoordinates(
            QgsPoint(0, 1),
            QgsRasterDataProvider.TransformType.TransformImageToLayer,
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
    tool_id: str = ""
    nodata: Optional[float] = None
    nodata_reason: str = ""
    # Direction in degrees (aspect): nearest only, see raster_semantics.
    circular: bool = False
    # False for a raster this plugin did not produce. Its meaning is unknown,
    # which the manifest must say instead of asserting "continuous".
    has_metadata: bool = True
    # Set by the pixel-sample heuristic for a no-metadata raster.
    nearest_by_sample: bool = False
    source_crs: str = ""
    valid_pct: Optional[float] = None

    @property
    def nearest(self) -> bool:
        return bool(self.categorical or self.circular or self.nearest_by_sample)

    @property
    def categorical_label(self) -> str:
        """Manifest ``categorical`` column: yes / no / unknown / unknown(nearest)."""
        if self.categorical:
            return "yes"
        if not self.has_metadata:
            return "unknown(nearest)" if self.nearest_by_sample else "unknown"
        return "no"

    @property
    def resampling_label(self) -> str:
        """Manifest ``resampling`` column; the reason is appended when it is not the default one."""
        if self.categorical:
            return "nearest"
        if self.circular:
            return "nearest(circular)"
        if self.nearest_by_sample:
            return "nearest(heuristic)"
        return "bilinear"

    @property
    def semantics_note(self) -> str:
        """Short Korean tag for the log line that maps variable name to layer."""
        if self.categorical:
            return "  [범주형: 최근접]"
        if self.circular:
            return "  [방향(원형): 최근접]"
        if not self.has_metadata:
            return "  [메타데이터 없음: 연속형으로 처리]"
        return ""


@dataclass(frozen=True)
class _WarpValidationContract:
    crs: object
    grid: RasterGrid
    band_count: int
    nodata_values: tuple
    categorical: bool


class AlignExportDialog(QtWidgets.QDialog):
    """Align selected analysis-result rasters to a common grid; export a stack."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        # Remember the last-used inputs between sessions (tools/dialog_memory.py).
        dialog_memory.attach(self, "align_export")
        self.iface = iface
        self._setup_ui()
        self._populate_layers()

    # -- UI ------------------------------------------------------------------
    def _setup_ui(self):
        self.setWindowTitle("분석 결과 정렬/내보내기 (Align & Export Stack)")
        try:
            self.setWindowIcon(plugin_icon("align_export.xpm", "terrain.png"))
        except Exception as _exc:
            log_swallowed("align_export_dialog._setup_ui", _exc)

        layout = QtWidgets.QVBoxLayout(self)
        header = QtWidgets.QLabel(
            "<b>분석 결과 정렬/내보내기</b><br>"
            "이미 만든 분석 결과 래스터들을 <b>하나의 기준 격자</b>(CRS·범위·픽셀크기)로 맞춰 "
            "정렬하고, 예측모델용 스택+manifest로 내보냅니다. "
            "NoData는 래스터별로 정해지며 manifest의 <code>nodata</code> 열에 기록됩니다.<br>"
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
        except Exception as _exc:
            log_swallowed("tools/align_export_dialog.py:396 (_setup_ui)", _exc)
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
        self.listLayers.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
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
            if raster:
                combo.setFilters(Qgis.LayerFilter.RasterLayer)
            else:
                combo.setFilters(Qgis.LayerFilter.PolygonLayer)
        except Exception as _exc:
            log_swallowed("align_export_dialog._set_filter", _exc)

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
            tool_id = str(meta.get("tool_id") or "")
            # 도면 시각화 outputs are render clones of a DEM the user already
            # has - hillshade, grey and colour views of the same elevation.
            # Auto-checking them exported three byte-identical predictors and
            # handed the model three copies of one variable.
            is_render_clone = tool_id == "map_styling"
            auto_check = is_arch and not is_render_clone
            label = lyr.name() + (f"   [{tool_id}/{kind}]" if is_arch else "")
            if is_render_clone:
                label += "  (도면용 사본 — 예측변수 아님)"
            elif is_categorical_raster_meta(meta):
                label += "  (범주형)"
            elif is_circular_meta(meta):
                label += "  (방향, 최근접)"
            elif not is_arch:
                # Not produced by this plugin, so nothing says whether it is a
                # measurement or class codes. Say so where the user checks it.
                label += "  (메타데이터 없음: 연속형으로 처리)"
            item = QtWidgets.QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if auto_check else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, lyr.id())
            item.setData(Qt.ItemDataRole.UserRole + 1, bool(auto_check))
            self.listLayers.addItem(item)
        if self.listLayers.count() == 0:
            item = QtWidgets.QListWidgetItem("(프로젝트에 래스터 레이어가 없습니다)")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.listLayers.addItem(item)

    def _check_all(self, state: bool):
        for i in range(self.listLayers.count()):
            it = self.listLayers.item(i)
            if it.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                it.setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)

    def _check_arch_only(self):
        for i in range(self.listLayers.count()):
            it = self.listLayers.item(i)
            if it.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                is_arch = bool(it.data(Qt.ItemDataRole.UserRole + 1))
                it.setCheckState(Qt.CheckState.Checked if is_arch else Qt.CheckState.Unchecked)

    def _on_browse(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "내보내기 폴더 선택")
        if d:
            self.txtExport.setText(d)

    # -- run -----------------------------------------------------------------
    def _selected_items(self) -> List[_Item]:
        out: List[_Item] = []
        project = QgsProject.instance()
        for i in range(self.listLayers.count()):
            it = self.listLayers.item(i)
            if not (it.flags() & Qt.ItemFlag.ItemIsUserCheckable) or it.checkState() != Qt.CheckState.Checked:
                continue
            lid = str(it.data(Qt.ItemDataRole.UserRole) or "")
            lyr = project.mapLayer(lid)
            if not isinstance(lyr, QgsRasterLayer) or not lyr.isValid():
                continue
            meta = get_archtoolkit_layer_metadata(lyr) or {}
            kind = str(meta.get("kind") or "")
            units = str(meta.get("units") or "")
            tool_id = str(meta.get("tool_id") or "")
            # Categorical → nearest resampling (bilinear would blend class codes
            # into meaningless fractional values). Shared helper keeps this in
            # lockstep with the covariate report's exclusion rule.
            categorical = is_categorical_raster_meta(meta)
            # Aspect and other directions in degrees are circular: bilinear
            # averages 355 and 5 to 180. Nearest only, like categorical.
            circular = (not categorical) and is_circular_meta(meta)
            has_metadata = bool(tool_id or kind)
            out.append(_Item(lid, lyr.name(), "", kind, units, categorical, tool_id,
                             circular=circular, has_metadata=has_metadata))

        # The exported base name becomes the model's variable name downstream,
        # and consumers reduce it to ASCII - which deletes Hangul rather than
        # transcribing it, turning 경사도.tif into "predictor". Derive the key
        # from the English `kind` each tool already records, in the order shown
        # in this dialog so the numbering is reproducible.
        for item, key in zip(out, assign_variable_keys(
            [{"kind": i.kind, "name": i.name, "tool_id": i.tool_id} for i in out]
        )):
            item.key = key
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
        # Belt and braces for assign_variable_keys' case-folded uniqueness:
        # keys are filenames, and on Windows/macOS slope.tif and Slope.tif are
        # the same file, which gdalwarp -overwrite would silently replace.
        folded = [item.key.casefold() for item in items]
        if len(set(folded)) != len(folded):
            clashes = sorted({item.key for item in items if folded.count(item.key.casefold()) > 1})
            push_message(
                self.iface, "오류",
                "변수명이 대소문자만 다른 래스터가 있어 같은 파일로 덮어쓰게 됩니다: "
                + ", ".join(clashes) + " (레이어 이름을 바꾸거나 하나를 해제하세요)",
                level=2, duration=12,
            )
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
            aoi_result = resolve_aoi_extent(
                aoi, selected_only=self.chkAoiSelected.isChecked(), dst_crs=ref.crs())
            if aoi_result.ok:
                requested_extent = _qgs_rectangle_to_extent(aoi_result.extent)
                if aoi_result.skipped:
                    push_message(self.iface, "주의", aoi_result.message(), level=1, duration=8)
            elif aoi_result.requested_but_failed:
                # Falling back to the full reference extent here would hand the
                # user an unclipped stack while they believe it was clipped.
                push_message(
                    self.iface, "오류",
                    f"AOI를 사용할 수 없습니다: {aoi_result.message()}",
                    level=2, duration=10,
                )
                return
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
        except Exception as _exc:
            log_swallowed("tools/align_export_dialog.py:636 (_on_run)", _exc)

        # The variable name is what the user will see in a model report, and it
        # is no longer the layer name, so show the mapping before the run
        # rather than leaving them to infer it from the manifest afterwards.
        for item in items:
            log_message(
                f"변수명 '{item.key}' ← {item.name}" + item.semantics_note,
                level=Qgis.MessageLevel.Info,
            )

        # A source that does not overlap the target grid still warps "successfully"
        # into a file that is entirely NoData. Say so before the run starts; the
        # output validation below refuses such a file when it happens anyway.
        outside = self._sources_outside_target(items, ref_crs, target_grid)
        if outside:
            names = ", ".join(outside)
            log_message(
                f"기준 격자와 겹치지 않는 입력 래스터: {names} (정렬 결과가 전부 NoData가 됩니다)",
                level=Qgis.MessageLevel.Warning,
            )
            push_message(
                self.iface, "주의",
                f"기준 격자와 겹치지 않는 입력 래스터가 있습니다: {names}",
                level=1, duration=12,
            )

        try:
            staging_dir = create_staging_dir(export_dir, run_id, purpose="align")
        except Exception as e:
            log_exception("Align staging directory error", e)
            push_message(self.iface, "오류", f"임시 출력 폴더를 만들 수 없습니다: {e}", level=2, duration=8)
            restore_ui_focus(self)
            return

        progress = QtWidgets.QProgressDialog("래스터 정렬 중…", "취소", 0, len(items), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
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
                src = split_qgis_source_path(src_layer.source())
                if not src:
                    raise RuntimeError(f"입력 경로를 확인할 수 없습니다: {item.name}")
                if not item.has_metadata:
                    # No metadata means no semantic claim can be made. Default
                    # to the continuous path but say so, and switch to nearest
                    # only when the pixels themselves read as class codes.
                    item.nearest_by_sample = _sample_looks_like_class_codes(src_layer)
                    if item.nearest_by_sample:
                        log_message(
                            f"메타데이터 없는 래스터가 정수형이고 표본의 서로 다른 값이 "
                            f"{CLASS_CODE_MAX_DISTINCT}개 이하라 클래스 코드로 보고 최근접으로 "
                            f"재배열합니다 (manifest categorical=unknown(nearest)): {item.name}",
                            level=Qgis.MessageLevel.Warning,
                        )
                    else:
                        log_message(
                            f"메타데이터 없는 래스터를 연속형으로 처리합니다 (이중선형, manifest "
                            f"categorical=unknown). 실제로 범주형이면 결과가 잘못됩니다: {item.name}",
                            level=Qgis.MessageLevel.Warning,
                        )
                src_crs = src_layer.crs()
                item.source_crs = _crs_label(src_crs)
                try:
                    # A CRS assigned in Layer Properties lives only in the
                    # project. The warp is told to use it; record the case
                    # where that differs from what the file says.
                    provider = src_layer.dataProvider()
                    file_crs = provider.crs() if provider is not None else None
                    if file_crs is not None and file_crs.isValid() and src_crs.isValid() and file_crs != src_crs:
                        log_message(
                            f"레이어 CRS가 파일 CRS와 다릅니다 ({item.name}): 레이어 "
                            f"{_crs_label(src_crs)} / 파일 {_crs_label(file_crs)}. "
                            "레이어에 지정된 CRS를 원본 CRS로 사용합니다.",
                            level=Qgis.MessageLevel.Warning,
                        )
                except Exception as exc:
                    log_swallowed("align_export_dialog._on_run", exc)
                if item.categorical:
                    item.nodata, item.nodata_reason = _categorical_output_nodata(src_layer)
                    if item.nodata is None:
                        # Say it out loud rather than shipping a class raster
                        # whose NoData nothing downstream can check.
                        log_message(
                            f"범주형 래스터 NoData를 정할 수 없습니다 ({item.name}, "
                            f"사유: {item.nodata_reason}). NoData 없이 내보냅니다.",
                            level=Qgis.MessageLevel.Warning,
                        )
                else:
                    item.nodata, item.nodata_reason = CONTINUOUS_NODATA, "continuous"
                expected = _WarpValidationContract(
                    crs=ref_crs,
                    grid=target_grid,
                    band_count=int(src_layer.bandCount()),
                    nodata_values=_expected_nodata_values(src_layer, item.nodata),
                    categorical=item.categorical,
                )
                out_path = os.path.join(staging_dir, f"{item.key}.tif")
                self._warp(
                    src,
                    out_path,
                    px,
                    extent_str,
                    ref_crs,
                    nearest=item.nearest,
                    nodata=item.nodata,
                    progress=progress,
                    # Only a true categorical raster keeps its band type. A
                    # circular or heuristic-nearest raster still carries the
                    # continuous -9999 NoData, which needs Float32.
                    force_float32=not item.categorical,
                    source_crs=src_crs,
                )
                QtWidgets.QApplication.processEvents()
                if progress.wasCanceled():
                    raise _Cancelled()
                if not os.path.isfile(out_path):
                    raise RuntimeError(f"정렬 출력이 생성되지 않았습니다: {item.name}")
                item.valid_pct = self._validate_warp_output(out_path, item.name, expected)
                outputs.append({
                    "key": item.key, "path": out_path, "source": item.name,
                    "kind": item.kind, "units": item.units,
                    "categorical": bool(item.categorical),
                    "categorical_label": item.categorical_label,
                    "nodata": item.nodata,
                    "resampling": item.resampling_label,
                    "source_crs": item.source_crs,
                    "valid_pct": item.valid_pct,
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
            log_message(f"Align & export cancelled (run {run_id})", level=Qgis.MessageLevel.Warning)
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
            except Exception as _exc:
                log_swallowed("tools/align_export_dialog.py:756 (_on_run)", _exc)

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
            "note": (
                "continuous_nodata applies only to manifest rows whose categorical "
                "column is 'no' (or 'unknown'/'unknown(nearest)'). NoData is per "
                "raster, not part of the common grid: categorical rows carry their "
                "own value, or none, in the manifest's nodata column."
            ),
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
            except Exception as _exc:
                log_swallowed("tools/align_export_dialog.py:802 (_on_run)", _exc)
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
        log_level = Qgis.MessageLevel.Warning if layer_add_error is not None else Qgis.MessageLevel.Info
        log_message(f"Align & export done: {len(outputs)} rasters (run {run_id})", level=log_level)
        restore_ui_focus(self)

    def _warp(self, src, out, px, extent_str, ref_crs, *, nearest: bool, nodata, progress,
              force_float32: Optional[bool] = None, source_crs=None):
        if progress.wasCanceled():
            raise _Cancelled()
        if force_float32 is None:
            force_float32 = not nearest
        # Categorical layers keep their input type (often Byte) so the class
        # codes stay integral, and carry an explicit NoData chosen by
        # _categorical_output_nodata — either the source's own value or a
        # sentinel outside the code range. Continuous layers are forced to
        # Float32 so the -9999 NoData is always representable — with DATA_TYPE=0
        # a continuous Byte product (e.g. 0-255 hillshade) would have -9999
        # clamped, turning valid value 0 into NoData.
        # SOURCE_CRS is the layer's effective CRS, which may be one the user
        # assigned in Layer Properties and which never reaches the file. With
        # None, gdalwarp reads the file's own tag and that override is lost.
        # The algorithm emits -s_srs only for a valid CRS, so None stays a
        # no-op for callers that have nothing better.
        params = {
            "INPUT": src,
            "SOURCE_CRS": source_crs,
            "TARGET_CRS": ref_crs,
            "RESAMPLING": 0 if nearest else 1,  # 0=nearest, 1=bilinear
            "NODATA": nodata,
            "TARGET_RESOLUTION": px,
            "OPTIONS": "",
            "DATA_TYPE": 6 if force_float32 else 0,  # 0: keep type / 6: Float32
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
            loop.exec()
        finally:
            try:
                progress.canceled.disconnect(_cancel_active_warp)
            except Exception as _exc:
                log_swallowed("tools/align_export_dialog.py:883 (_warp)", _exc)

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
                level=Qgis.MessageLevel.Warning,
            )
        result_path = str(state["results"].get("OUTPUT") or "")
        if result_path and os.path.realpath(result_path) != os.path.realpath(out):
            raise RuntimeError(f"GDAL 출력 경로가 요청과 다릅니다: {result_path}")
        return out

    def _validate_warp_output(self, path, source_name, expected) -> Optional[float]:
        """Check the output against ``expected``; return its sampled valid-pixel percentage.

        The percentage comes from the decimated block read for the pixel
        check, so it is an estimate. None means it could not be read. Zero
        raises: gdalwarp with an explicit extent produces a complete grid even
        when the source lies entirely outside it, and that file passes every
        container check while holding no data at all.
        """
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
        valid_pct: Optional[float] = None
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
            fraction = _valid_fraction(block)
            if fraction is None:
                log_message(
                    f"정렬 결과의 유효 픽셀 비율을 읽지 못했습니다: {source_name} band {band}",
                    level=Qgis.MessageLevel.Warning,
                )
                continue
            if fraction <= 0.0:
                # A 64x64 nearest-decimated sample can step over a small valid
                # patch on a large grid; confirm with full-band statistics
                # before calling the predictor empty.
                full_valid = _band_valid_count(provider, band)
                if full_valid is None or full_valid <= 0:
                    raise RuntimeError(
                        f"정렬 결과에 유효 픽셀이 없습니다 (입력이 기준 격자와 겹치지 않는지 확인하세요): "
                        f"{source_name} band {band}"
                    )
                total_px = float(layer.width()) * float(layer.height())
                fraction = (float(full_valid) / total_px) if total_px > 0 else 0.0
                log_message(
                    f"정렬 결과 표본에는 유효 픽셀이 없었지만 전체 통계로 {full_valid:,}개를 확인했습니다: "
                    f"{source_name} band {band}",
                    level=Qgis.MessageLevel.Warning,
                )
            band_pct = 100.0 * fraction
            valid_pct = band_pct if valid_pct is None else min(valid_pct, band_pct)
        if valid_pct is not None and valid_pct < 100.0:
            log_message(
                f"정렬 결과 유효 픽셀(표본) {valid_pct:.1f}%: {source_name}",
                level=Qgis.MessageLevel.Warning if valid_pct < 50.0 else Qgis.MessageLevel.Info,
            )
        return valid_pct

    def _sources_outside_target(self, items, ref_crs, target_grid) -> List[str]:
        """Names of the inputs whose extent, in the reference CRS, misses the target grid."""
        outside: List[str] = []
        try:
            target = QgsRectangle(
                target_grid.extent.xmin, target_grid.extent.ymin,
                target_grid.extent.xmax, target_grid.extent.ymax,
            )
        except Exception as exc:
            log_swallowed("align_export_dialog._sources_outside_target", exc)
            return outside
        project = QgsProject.instance()
        for item in items:
            try:
                layer = project.mapLayer(item.layer_id)
                if layer is None:
                    continue
                extent = layer.extent()
                src_crs = layer.crs()
                if src_crs.isValid() and ref_crs.isValid() and src_crs != ref_crs:
                    extent = QgsCoordinateTransform(src_crs, ref_crs, project).transformBoundingBox(extent)
                if extent.isEmpty() or not extent.intersects(target):
                    outside.append(item.name)
            except Exception as exc:
                # A failed transform is not proof of non-overlap; the output
                # validation still refuses an all-NoData result.
                log_swallowed("align_export_dialog._sources_outside_target", exc)
        return outside

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
            # categorical: yes / no / unknown / unknown(nearest). "unknown" is a
            # raster this plugin did not produce; nothing says what it holds.
            # nodata is per raster (not a grid property). source_crs is the
            # CRS the warp read the input in. valid_pct is the sampled share
            # of non-NoData cells, so a partly covered predictor is visible.
            w.writerow(["variable", "file", "source_layer", "kind", "units",
                        "categorical", "nodata", "resampling", "source_crs", "valid_pct"])
            for o in outputs:
                valid_pct = o.get("valid_pct")
                w.writerow([o["key"], os.path.basename(o["path"]), o["source"],
                            o["kind"], o["units"],
                            o.get("categorical_label") or ("yes" if o.get("categorical") else "no"),
                            "" if o.get("nodata") is None else o["nodata"],
                            o["resampling"],
                            o.get("source_crs", ""),
                            "" if valid_pct is None else round(float(valid_pct), 1)])

        # Which rasters are categorical is the one thing file conventions
        # cannot carry, and a modelling tool that wants it as a typed list
        # otherwise makes the user retype names by hand. Write the exact string
        # to paste, next to the stack it describes. This states what the export
        # already knows; it is not a format for anyone to depend on.
        categorical_keys = [o["key"] for o in outputs if o.get("categorical")]
        with open(os.path.join(export_dir, "CATEGORICAL_PREDICTORS.txt"),
                  "w", encoding="utf-8") as cf:
            cf.write(",".join(categorical_keys))
            cf.write("\n")

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
                        "resampling": o["resampling"],
                        "categorical": o.get("categorical_label", ""),
                        "source_crs": o.get("source_crs", "")},
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
            "<p>이미 실행한 분석 결과 래스터들을 <b>하나의 기준 격자</b>(CRS·범위·픽셀크기)로 맞춰 "
            "정렬하고, 예측모델용 스택으로 내보냅니다. 이 도구는 <b>변수를 새로 만들지 않습니다</b> — "
            "당신의 분석을 모델 입력으로 정리하는 하위 유틸리티입니다.</p>"
            "<h4>사용</h4>"
            "<ol>"
            "<li><b>기준 래스터</b>를 고릅니다(그 격자에 모두 맞춰집니다). 필요하면 픽셀 크기/AOI로 조정.</li>"
            "<li><b>정렬할 래스터</b>를 체크합니다. ArchToolkit 분석 결과는 자동 체크됩니다.</li>"
            "<li><b>내보내기 폴더</b>를 지정합니다. 결과는 실행별 "
            "<code>aligned_stack_&lt;run_id&gt;</code> 폴더에 GeoTIFF와 manifest로 함께 게시됩니다.</li>"
            "</ol>"
            "<h4>NoData</h4>"
            "<p>NoData는 기준 격자의 일부가 <b>아니라 래스터별</b>로 정해집니다. 연속형은 -9999, "
            "범주형은 원본의 값 또는 코드 범위 밖의 값을 쓰며, 안전한 값이 없으면 NoData 없이 내보내고 "
            "로그에 사유를 남깁니다. 실제 값은 manifest의 <code>nodata</code> 열을 보세요.</p>"
            "<h4>리샘플</h4>"
            "<p>래스터의 의미에 따라 세 갈래로 나뉘며 manifest의 <code>categorical</code>·"
            "<code>resampling</code> 열에 기록됩니다.</p>"
            "<ul>"
            "<li><b>범주형</b>(지질/등급/마스크 등, 메타데이터 <code>kind</code>·<code>units</code>·"
            "<code>tool_id</code> 기준): 최근접(nearest). 이중선형은 클래스 코드를 섞어 존재하지 않는 값을 만듭니다.</li>"
            "<li><b>방향(원형) 값</b>(사면방향 등 도 단위 방위): 최근접. 355도와 5도의 평균 180도는 정반대 방향이므로 "
            "이중선형을 쓸 수 없습니다. 평균할 수 있는 형태가 필요하면 지형 분석의 북향성/동향성/TRASP를 쓰세요.</li>"
            "<li><b>연속형</b>(경사·고도·거리 등): 이중선형(bilinear).</li>"
            "</ul>"
            "<p><b>ArchToolkit 메타데이터가 없는 래스터</b>(직접 불러온 파일 등)는 의미를 알 수 없으므로 "
            "연속형으로 처리(이중선형)하고 <code>categorical</code> 열에 <code>unknown</code>으로 기록합니다. "
            f"다만 정수형(Byte/Int16 등)이고 표본에서 서로 다른 값이 {CLASS_CODE_MAX_DISTINCT}개 이하이면 "
            "클래스 코드로 보고 최근접으로 재배열하며 <code>unknown(nearest)</code>로 기록합니다. "
            "그런 래스터가 실제로 범주형인지 여부는 "
            "직접 확인하세요. 잘못 처리되면 결과가 조용히 틀립니다.</p>"
            "<h4>검증</h4>"
            "<p>결과마다 CRS·격자·band 수·NoData를 확인하고, 표본의 유효 픽셀 비율을 <code>valid_pct</code> 열에 "
            "기록합니다. 유효 픽셀이 하나도 없으면(입력이 기준 격자와 겹치지 않을 때) 실행을 중단합니다. "
            "입력의 CRS는 <code>source_crs</code> 열에 기록되며, 레이어 속성에서 지정한 CRS가 파일의 CRS보다 우선합니다.</p>"
            "<p style='color:#455a64'>QGIS 기본 구성(GDAL)만 사용합니다.</p>"
        )
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            show_help_dialog(parent=self, title="정렬/내보내기 도움말", html=html, plugin_dir=plugin_dir, tool_id="align_export")
        except Exception as _exc:
            log_swallowed("tools/align_export_dialog.py:1057 (_on_help)", _exc)
