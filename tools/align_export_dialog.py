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
- Runs synchronously with a cancelable progress dialog (no processing.run off
  the GUI thread).
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from typing import List, Optional

import processing
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox

from .help_dialog import show_help_dialog
from .live_log_dialog import ensure_live_log_dialog
from .utils import (
    get_archtoolkit_layer_metadata,
    log_exception,
    log_message,
    new_run_id,
    push_message,
    restore_ui_focus,
    set_archtoolkit_layer_metadata,
)

PARENT_GROUP_NAME = "ArchToolkit - 정렬 스택 (Aligned Stack)"
_CATEGORICAL_HINTS = ("class", "category", "litho", "age", "geolog", "categor")


class _Cancelled(Exception):
    pass


@dataclass
class _Item:
    layer_id: str
    name: str
    key: str
    kind: str
    units: str
    categorical: bool


@dataclass
class _Result:
    ok: bool = False
    message: str = ""
    outputs: List[dict] = field(default_factory=list)
    export_dir: str = ""
    run_id: str = ""


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
            for name in ("terrain_icon.png", "icon.png"):
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
        self.txtExport.setPlaceholderText("(비우면 임시 폴더; 지정하면 GeoTIFF 스택+manifest 저장)")
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
            tool_id = str(meta.get("tool_id") or "")
            # Categorical detection must catch the toolkit's real outputs, not
            # just kind-name hints: slope-position tags units="class", the
            # KIGAM geology raster tags tool_id="geology_zip"/kind="raster",
            # geochem tags kind="class_raster". Bilinear on class codes would
            # blend them into meaningless fractional values.
            categorical = (
                any(h in kind.lower() for h in _CATEGORICAL_HINTS)
                or units.lower() in ("class", "classes", "category")
                or "geology" in tool_id.lower()
                or "slope_position" in kind.lower()
            )
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
        if export_dir:
            try:
                os.makedirs(export_dir, exist_ok=True)
            except Exception as e:
                push_message(self.iface, "오류", f"내보내기 폴더를 만들 수 없습니다: {e}", level=2, duration=7)
                return

        px = float(self.spinPixel.value())
        if px <= 0:
            try:
                px = float(ref.rasterUnitsPerPixelX())
            except Exception:
                px = 0.0
        if px <= 0:
            push_message(self.iface, "오류", "기준 픽셀 크기를 확인할 수 없습니다.", level=2, duration=6)
            return

        ref_crs = ref.crs().authid()
        extent_str = None
        aoi = self.cmbAoi.currentLayer()
        if isinstance(aoi, QgsVectorLayer):
            ext = _aoi_extent_in_crs(aoi, selected_only=self.chkAoiSelected.isChecked(), dst_crs=ref.crs())
            if ext is not None and not ext.isEmpty():
                extent_str = f"{ext.xMinimum()},{ext.xMaximum()},{ext.yMinimum()},{ext.yMaximum()}"
        if extent_str is None:
            e = ref.extent()
            extent_str = f"{e.xMinimum()},{e.xMaximum()},{e.yMinimum()},{e.yMaximum()}"

        run_id = new_run_id("align")
        try:
            ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)
        except Exception:
            pass

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
                if progress.wasCanceled():
                    break
                progress.setLabelText(f"정렬 중: {item.name} ({idx + 1}/{len(items)})")
                progress.setValue(idx)
                QtWidgets.QApplication.processEvents()
                src_layer = QgsProject.instance().mapLayer(item.layer_id)
                if src_layer is None:
                    continue
                src = str(src_layer.source() or "").split("|", 1)[0].strip()
                out_path = (os.path.join(export_dir, f"{item.key}.tif") if export_dir
                            else os.path.join(_tmpdir(), f"archtoolkit_align_{run_id}_{item.key}.tif"))
                try:
                    self._warp(src, out_path, px, extent_str, ref_crs, nearest=item.categorical)
                    outputs.append({
                        "key": item.key, "path": out_path, "source": item.name,
                        "kind": item.kind, "units": item.units,
                        "resampling": "nearest" if item.categorical else "bilinear",
                    })
                except Exception as e:
                    log_exception(f"Align failed for {item.name}", e)
            progress.setValue(len(items))
        finally:
            self.btnRun.setEnabled(True)
            try:
                progress.close()
            except Exception:
                pass

        if not outputs:
            push_message(self.iface, "오류", "정렬된 결과가 없습니다.", level=2, duration=8)
            restore_ui_focus(self)
            return

        if export_dir:
            self._write_manifest(
                export_dir,
                outputs,
                grid={
                    "crs": str(ref.crs().authid() or ""),
                    "pixel_size": px,
                    "extent": extent_str,
                    "continuous_nodata": -9999,
                    "run_id": run_id,
                },
            )
        if self.chkAddToProject.isChecked():
            try:
                self._add_layers(outputs, run_id)
            except Exception as e:
                log_exception("Add aligned layers error", e)

        msg = f"완료: {len(outputs)}개 정렬"
        if export_dir:
            msg += f" → {export_dir}"
        push_message(self.iface, "정렬/내보내기", msg, level=0, duration=8)
        log_message(f"Align & export done: {len(outputs)} rasters (run {run_id})", level=Qgis.Info)
        restore_ui_focus(self)

    def _warp(self, src, out, px, extent_str, ref_crs, *, nearest: bool):
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
            "NODATA": None if nearest else -9999,
            "TARGET_RESOLUTION": px,
            "OPTIONS": "",
            "DATA_TYPE": 0 if nearest else 6,  # categorical: keep type / continuous: Float32
            "TARGET_EXTENT": extent_str,
            "TARGET_EXTENT_CRS": ref_crs,
            "MULTITHREADING": False,
            "EXTRA": "",
            "OUTPUT": out,
        }
        processing.run("gdal:warpreproject", params)
        return out

    def _write_manifest(self, export_dir, outputs, grid=None):
        try:
            path = os.path.join(export_dir, "aligned_stack_manifest.csv")
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                # Grid definition first — the facts a downstream modeler needs
                # to verify alignment (CRS / pixel size / extent / NoData).
                if grid:
                    w.writerow(["# reference_grid"])
                    for k in ("crs", "pixel_size", "extent", "continuous_nodata", "run_id"):
                        w.writerow([f"# {k}", grid.get(k, "")])
                w.writerow(["variable", "file", "source_layer", "kind", "units", "resampling"])
                for o in outputs:
                    w.writerow([o["key"], os.path.basename(o["path"]), o["source"],
                                o["kind"], o["units"], o["resampling"]])
        except Exception as e:
            log_exception("Align manifest write error", e)

    def _add_layers(self, outputs, run_id):
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        parent = root.findGroup(PARENT_GROUP_NAME) or root.insertGroup(0, PARENT_GROUP_NAME)
        group = parent.insertGroup(0, f"정렬_{run_id}")
        group.setExpanded(False)
        for o in outputs:
            try:
                lyr = QgsRasterLayer(o["path"], f"{o['source']} (정렬)")
                if not lyr.isValid():
                    continue
                set_archtoolkit_layer_metadata(
                    lyr, tool_id="align_export", run_id=run_id,
                    kind=o["kind"] or "aligned", units=o["units"],
                    params={"variable": o["key"], "source_layer": o["source"],
                            "resampling": o["resampling"]},
                )
                project.addMapLayer(lyr, False)
                group.insertLayer(0, lyr)
            except Exception:
                continue

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
            "<li>필요하면 <b>내보내기 폴더</b>를 지정합니다(→ <code>&lt;변수&gt;.tif</code> + "
            "<code>aligned_stack_manifest.csv</code>).</li>"
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


def _tmpdir() -> str:
    import tempfile
    return tempfile.gettempdir()
