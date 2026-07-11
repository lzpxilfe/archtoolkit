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
DEM 파생 변수 일괄 생성기 (Batch DEM Covariate Generator).

Goal
- Produce a stack of geomorphometric covariates from a single DEM, all snapped
  to ONE common reference grid (identical CRS / extent / pixel size / NoData) so
  they can be fed directly into predictive models (e.g. MaxEnt) without further
  alignment.

Design
- QGIS built-ins only (gdal:* processing + NumPy, which ships with QGIS). No
  GRASS/SAGA/WhiteboxTools dependency, per DEVELOPMENT.md.
- All derivatives are computed FROM the aligned elevation raster, so every
  output shares the reference grid natively.
- Runs synchronously on the GUI thread with a cancelable progress dialog (the
  same proven pattern the other processing-based tools use); processing.run is
  not called from a background thread.

References
- Aspect -> northness/eastness: standard circular transform (sin/cos).
- TRASP (heat/insolation proxy): Roberts, D.W. & Cooper, S.V. (1989).
- TRI: Riley et al. (1999). TPI: Weiss (2001). Roughness: GDAL DEM utilities.
"""

from __future__ import annotations

import csv
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import numpy as np
except Exception:  # pragma: no cover - QGIS ships NumPy; guard anyway
    np = None

from osgeo import gdal

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
    log_exception,
    log_message,
    new_run_id,
    push_message,
    restore_ui_focus,
    set_archtoolkit_layer_metadata,
)

PARENT_GROUP_NAME = "ArchToolkit - DEM 변수 (Covariates)"
_MAX_CELLS = 60_000_000  # guard: refuse absurdly large reference grids


class _Cancelled(Exception):
    """Raised internally when the user cancels the progress dialog."""


@dataclass
class _CovInfo:
    key: str
    path: str
    kind: str
    units: str
    label: str
    description: str


@dataclass
class _Result:
    ok: bool = False
    message: str = ""
    covariates: List[_CovInfo] = field(default_factory=list)
    export_dir: str = ""
    run_id: str = ""


def _aoi_extent_in_crs(aoi_layer, *, selected_only: bool, dst_crs) -> Optional[QgsRectangle]:
    """Union extent of AOI features, transformed to dst_crs (best-effort)."""
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


class DemCovariatesBuilder:
    """Builds the aligned covariate stack (synchronous, GUI thread).

    Pass optional callbacks:
    - progress_cb(percent:int, message:str)
    - should_cancel() -> bool
    """

    def __init__(
        self,
        *,
        dem_source: str,
        pixel_size: float,
        extent_str: Optional[str],
        extent_crs: Optional[str],
        options: Dict[str, Any],
        tpi_radii: List[int],
        export_dir: str,
        run_id: str,
        progress_cb=None,
        should_cancel=None,
    ):
        self.dem_source = dem_source
        self.pixel_size = float(pixel_size)
        self.extent_str = extent_str
        self.extent_crs = extent_crs
        self.options = dict(options or {})
        self.tpi_radii = list(tpi_radii or [])
        self.export_dir = str(export_dir or "")
        self.run_id = str(run_id)
        self._progress_cb = progress_cb
        self._should_cancel = should_cancel
        self._tmp: List[str] = []

    # -- progress / cancel ---------------------------------------------------
    def _progress(self, pct: int, msg: str) -> None:
        if self._should_cancel and self._should_cancel():
            raise _Cancelled()
        if self._progress_cb:
            try:
                self._progress_cb(int(pct), str(msg))
            except Exception:
                pass

    # -- path helpers --------------------------------------------------------
    def _tmp_path(self, name: str) -> str:
        p = os.path.join(tempfile.gettempdir(), f"archtoolkit_covtmp_{self.run_id}_{name}.tif")
        self._tmp.append(p)
        return p

    def _out_path(self, key: str) -> str:
        """Final path for a kept covariate: export_dir if set, else a temp file."""
        if self.export_dir:
            return os.path.join(self.export_dir, f"{key}.tif")
        return os.path.join(tempfile.gettempdir(), f"archtoolkit_cov_{self.run_id}_{key}.tif")

    def _cleanup_tmp(self) -> None:
        for p in self._tmp:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    def _warp(self, src: str, out: str, resampling: int) -> str:
        processing.run("gdal:warpreproject", {
            "INPUT": src,
            "SOURCE_CRS": None,
            "TARGET_CRS": self.extent_crs,
            "RESAMPLING": int(resampling),
            "NODATA": -9999,
            "TARGET_RESOLUTION": self.pixel_size,
            "OPTIONS": "",
            "DATA_TYPE": 6,  # Float32
            "TARGET_EXTENT": self.extent_str,
            "TARGET_EXTENT_CRS": self.extent_crs,
            "MULTITHREADING": False,
            "EXTRA": "",
            "OUTPUT": out,
        })
        return out

    # -- main build ----------------------------------------------------------
    def build(self) -> _Result:
        if np is None:
            return _Result(ok=False, message="NumPy를 사용할 수 없습니다.", run_id=self.run_id)
        try:
            return self._build_impl()
        except _Cancelled:
            return _Result(ok=False, message="취소되었습니다.", run_id=self.run_id)
        except Exception as e:
            log_exception("DEM covariates build error", e)
            return _Result(ok=False, message=str(e), run_id=self.run_id)
        finally:
            self._cleanup_tmp()

    def _build_impl(self) -> _Result:
        opt = self.options
        covs: List[_CovInfo] = []

        # 1) Aligned elevation = the reference grid every derivative inherits.
        self._progress(5, "기준 격자(정렬 DEM) 생성 중…")
        elev = self._out_path("elevation") if opt.get("elevation") else self._tmp_path("elev_ref")
        self._warp(self.dem_source, elev, 1)  # bilinear
        if not os.path.exists(elev):
            return _Result(ok=False, message="기준 격자(정렬 DEM) 생성에 실패했습니다.", run_id=self.run_id)

        ref_ds = gdal.Open(elev, gdal.GA_ReadOnly)
        if ref_ds is None:
            return _Result(ok=False, message="정렬 DEM을 열 수 없습니다.", run_id=self.run_id)
        cells = int(ref_ds.RasterXSize) * int(ref_ds.RasterYSize)
        ref_gt = ref_ds.GetGeoTransform()
        ref_proj = ref_ds.GetProjection()
        ref_ds = None
        if cells > _MAX_CELLS:
            return _Result(
                ok=False,
                message=f"기준 격자가 너무 큽니다(약 {cells:,} cells). 픽셀 크기를 키우거나 AOI로 자르세요.",
                run_id=self.run_id,
            )
        if opt.get("elevation"):
            covs.append(_CovInfo("elevation", elev, "elevation", "m",
                                 "표고 (정렬 DEM)", "Reference-grid elevation."))

        # 2) slope (needed by slope output and by the aspect transforms' flat mask)
        need_slope = opt.get("slope")
        slope_path = self._out_path("slope") if opt.get("slope") else self._tmp_path("slope")
        if need_slope:
            self._progress(20, "경사도 계산 중…")
            processing.run("gdal:slope", {
                "INPUT": elev, "BAND": 1, "SCALE": 1.0, "AS_PERCENT": False,
                "COMPUTE_EDGES": True, "ZEVENBERGEN": False, "OUTPUT": slope_path,
            })
            covs.append(_CovInfo("slope", slope_path, "slope", "degree",
                                 "경사도 (도)", "Slope in degrees (Horn)."))

        # 3) aspect + circular transforms
        need_aspect = opt.get("aspect") or opt.get("northness") or opt.get("eastness") or opt.get("trasp")
        aspect_path = self._out_path("aspect") if opt.get("aspect") else self._tmp_path("aspect")
        if need_aspect:
            self._progress(35, "사면방향 계산 중…")
            processing.run("gdal:aspect", {
                "INPUT": elev, "BAND": 1, "TRIG_ANGLE": False, "ZERO_FLAT": False,
                "COMPUTE_EDGES": True, "ZEVENBERGEN": False, "OUTPUT": aspect_path,
            })
            if opt.get("aspect"):
                covs.append(_CovInfo("aspect", aspect_path, "aspect", "degree",
                                     "사면 방향 (도)", "Aspect 0-360 deg (flat = NoData)."))

        if opt.get("northness") or opt.get("eastness") or opt.get("trasp"):
            self._progress(45, "북향성/동향성/TRASP 계산 중…")
            covs.extend(self._circular_transforms(elev, aspect_path, ref_gt, ref_proj, opt))

        # 4) TRI / roughness
        if opt.get("tri"):
            self._progress(60, "TRI(험준도) 계산 중…")
            tri_path = self._out_path("tri")
            processing.run("gdal:triterrainruggednessindex", {"INPUT": elev, "BAND": 1, "OUTPUT": tri_path})
            covs.append(_CovInfo("tri", tri_path, "tri", "m",
                                 "지형 험준도 TRI (Riley 1999)", "Terrain Ruggedness Index."))
        if opt.get("roughness"):
            self._progress(68, "거칠기 계산 중…")
            r_path = self._out_path("roughness")
            processing.run("gdal:roughness", {"INPUT": elev, "BAND": 1, "OUTPUT": r_path})
            covs.append(_CovInfo("roughness", r_path, "roughness", "m",
                                 "거칠기 Roughness", "Largest elevation difference in 3x3."))

        # 5) multi-scale TPI (Weiss 2001)
        if opt.get("tpi"):
            n = max(1, len(self.tpi_radii))
            for i, radius in enumerate(self.tpi_radii):
                self._progress(72 + int(22 * i / n), f"TPI(반경 {radius}) 계산 중…")
                info = self._tpi_at_radius(elev, int(radius))
                if info is not None:
                    covs.append(info)

        if not covs:
            return _Result(ok=False, message="생성할 변수를 하나 이상 선택하세요.", run_id=self.run_id)

        if self.export_dir:
            self._progress(96, "manifest 저장 중…")
            self._write_manifest(covs)

        self._progress(100, "완료")
        return _Result(ok=True, message=f"{len(covs)}개 변수 생성", covariates=covs,
                       export_dir=self.export_dir, run_id=self.run_id)

    def _circular_transforms(self, elev, aspect_path, ref_gt, ref_proj, opt) -> List[_CovInfo]:
        out: List[_CovInfo] = []
        try:
            a_ds = gdal.Open(aspect_path, gdal.GA_ReadOnly)
            e_ds = gdal.Open(elev, gdal.GA_ReadOnly)
            if a_ds is None or e_ds is None:
                return out
            a_band = a_ds.GetRasterBand(1)
            e_band = e_ds.GetRasterBand(1)
            aspect = a_band.ReadAsArray().astype("float64")
            elevation = e_band.ReadAsArray().astype("float64")
            a_nd = a_band.GetNoDataValue()
            e_nd = e_band.GetNoDataValue()
            a_ds = None
            e_ds = None

            valid = np.isfinite(elevation)
            if e_nd is not None:
                valid &= (elevation != e_nd)
            flat = np.zeros(aspect.shape, dtype=bool)
            if a_nd is not None:
                flat = (aspect == a_nd)
            flat |= (aspect < 0)  # GDAL emits a negative NoData for flat cells
            defined = valid & (~flat)
            rad = np.radians(aspect)

            def _emit(key, arr, flat_value, kind, units, label, desc):
                out_arr = np.full(aspect.shape, -9999.0, dtype="float32")
                out_arr[defined] = arr[defined].astype("float32")
                out_arr[valid & flat] = flat_value
                path = self._out_path(key)
                self._write_like(path, out_arr, ref_gt, ref_proj, -9999.0)
                out.append(_CovInfo(key, path, kind, units, label, desc))

            if opt.get("northness"):
                _emit("northness", np.cos(rad), 0.0, "northness", "index (-1..1)",
                      "북향성 northness = cos(aspect)", "Cosine of aspect; +1 = north-facing.")
            if opt.get("eastness"):
                _emit("eastness", np.sin(rad), 0.0, "eastness", "index (-1..1)",
                      "동향성 eastness = sin(aspect)", "Sine of aspect; +1 = east-facing.")
            if opt.get("trasp"):
                # TRASP (Roberts & Cooper 1989): (1 - cos(asp-30deg))/2; 0=NNE cool, 1=SSW warm.
                trasp = (1.0 - np.cos(np.radians(aspect - 30.0))) / 2.0
                _emit("trasp", trasp, 0.5, "trasp", "index (0..1)",
                      "일사/열부하 프록시 TRASP (Roberts & Cooper 1989)",
                      "Solar-radiation aspect index; flat = 0.5 (neutral).")
        except Exception as e:
            log_exception("Circular transform error", e)
        return out

    def _tpi_at_radius(self, elev: str, radius: int) -> Optional[_CovInfo]:
        try:
            if radius <= 1:
                out = self._out_path("tpi_r1")
                processing.run("gdal:tpitopographicpositionindex", {"INPUT": elev, "BAND": 1, "OUTPUT": out})
                window = 3
            else:
                ds = gdal.Open(elev, gdal.GA_ReadOnly)
                gt = ds.GetGeoTransform()
                px = abs(float(gt[1]))
                ds = None
                coarse = self._tmp_path(f"tpi_down_{radius}")
                processing.run("gdal:warpreproject", {
                    "INPUT": elev, "SOURCE_CRS": None, "TARGET_CRS": self.extent_crs,
                    "RESAMPLING": 5, "NODATA": -9999, "TARGET_RESOLUTION": px * radius,
                    "OPTIONS": "", "DATA_TYPE": 6, "TARGET_EXTENT": self.extent_str,
                    "TARGET_EXTENT_CRS": self.extent_crs, "MULTITHREADING": False,
                    "EXTRA": "", "OUTPUT": coarse,
                })
                mean_approx = self._tmp_path(f"tpi_mean_{radius}")
                self._warp(coarse, mean_approx, 1)  # back to reference grid (bilinear)
                out = self._out_path(f"tpi_r{radius}")
                processing.run("gdal:rastercalculator", {
                    "INPUT_A": elev, "BAND_A": 1, "INPUT_B": mean_approx, "BAND_B": 1,
                    "FORMULA": "A - B", "OUTPUT": out, "RTYPE": 5,
                })
                window = radius * 2 + 1
            return _CovInfo(f"tpi_r{radius}", out, "tpi", "index",
                            f"TPI 반경 {radius} (창 {window}x{window}, Weiss 2001)",
                            "Topographic Position Index = elevation - neighborhood mean.")
        except Exception as e:
            log_exception(f"TPI radius {radius} error", e)
            return None

    def _write_like(self, out_path: str, arr, gt, proj, nodata: float) -> None:
        driver = gdal.GetDriverByName("GTiff")
        rows, cols = arr.shape
        ds = driver.Create(out_path, cols, rows, 1, gdal.GDT_Float32, ["COMPRESS=LZW"])
        ds.SetGeoTransform(gt)
        if proj:
            ds.SetProjection(proj)
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(float(nodata))
        band.WriteArray(arr)
        band.FlushCache()
        ds = None

    def _write_manifest(self, covs: List[_CovInfo]) -> None:
        try:
            path = os.path.join(self.export_dir, "covariates_manifest.csv")
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["variable", "file", "kind", "units", "label", "description"])
                for c in covs:
                    w.writerow([c.key, os.path.basename(c.path), c.kind, c.units, c.label, c.description])
        except Exception as e:
            log_exception("Manifest write error", e)


class DemCovariatesDialog(QtWidgets.QDialog):
    """One-click aligned covariate stack from a DEM (for predictive modelling)."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("DEM 파생 변수 일괄 생성 (Batch DEM Covariates)")
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
            "<b>DEM 파생 변수 일괄 생성기</b><br>"
            "DEM 하나에서 예측모델용 파생변수(covariate)를 <b>동일 기준 격자</b>에 맞춰 한 번에 생성합니다.<br>"
            "<span style='color:#455a64;'>모든 결과는 같은 CRS·범위·픽셀크기·NoData로 정렬되어 MaxEnt 등에 바로 투입할 수 있습니다.</span>"
        )
        header.setWordWrap(True)
        header.setStyleSheet("background:#f1f8e9; padding:10px; border:1px solid #dcedc8; border-radius:4px;")
        layout.addWidget(header)

        grp_in = QtWidgets.QGroupBox("1. 입력")
        form = QtWidgets.QFormLayout(grp_in)
        self.cmbDem = QgsMapLayerComboBox(grp_in)
        self._set_filter(self.cmbDem, raster=True)
        form.addRow("DEM:", self.cmbDem)

        self.cmbAoi = QgsMapLayerComboBox(grp_in)
        self._set_filter(self.cmbAoi, raster=False)
        try:
            self.cmbAoi.setAllowEmptyLayer(True)
        except Exception:
            pass
        form.addRow("AOI(선택):", self.cmbAoi)

        self.chkAoiSelected = QtWidgets.QCheckBox("AOI 선택 피처만 사용")
        form.addRow("", self.chkAoiSelected)
        self.chkClip = QtWidgets.QCheckBox("AOI 범위로 자르기(권장)")
        self.chkClip.setChecked(True)
        form.addRow("", self.chkClip)

        self.spinPixel = QtWidgets.QDoubleSpinBox()
        self.spinPixel.setRange(0.0, 100000.0)
        self.spinPixel.setDecimals(3)
        self.spinPixel.setValue(0.0)
        self.spinPixel.setSpecialValueText("(DEM 원본 해상도)")
        form.addRow("출력 픽셀 크기:", self.spinPixel)
        layout.addWidget(grp_in)

        grp_var = QtWidgets.QGroupBox("2. 생성할 변수")
        vgrid = QtWidgets.QGridLayout(grp_var)
        self.checks: Dict[str, QtWidgets.QCheckBox] = {}
        var_defs = [
            ("elevation", "표고 (정렬 DEM)", True),
            ("slope", "경사도 (도)", True),
            ("aspect", "사면방향 (도, 원자료)", False),
            ("northness", "북향성 cos(aspect)", True),
            ("eastness", "동향성 sin(aspect)", True),
            ("trasp", "TRASP 일사/열부하 프록시", True),
            ("tri", "TRI 험준도 (Riley 1999)", True),
            ("roughness", "거칠기 Roughness", True),
            ("tpi", "TPI 다중스케일 (Weiss 2001)", True),
        ]
        for i, (key, label, default) in enumerate(var_defs):
            cb = QtWidgets.QCheckBox(label)
            cb.setChecked(default)
            self.checks[key] = cb
            vgrid.addWidget(cb, i // 2, i % 2)

        tpi_row = QtWidgets.QHBoxLayout()
        tpi_row.addWidget(QtWidgets.QLabel("TPI 반경(셀, 쉼표):"))
        self.txtTpiRadii = QtWidgets.QLineEdit("2,5,10")
        self.txtTpiRadii.setToolTip("여러 스케일의 TPI를 만듭니다. 예: 2,5,10")
        tpi_row.addWidget(self.txtTpiRadii, 1)
        vgrid.addLayout(tpi_row, (len(var_defs) + 1) // 2, 0, 1, 2)
        layout.addWidget(grp_var)

        grp_out = QtWidgets.QGroupBox("3. 출력")
        fout = QtWidgets.QFormLayout(grp_out)
        self.chkAddToProject = QtWidgets.QCheckBox("완료 후 프로젝트에 추가")
        self.chkAddToProject.setChecked(True)
        fout.addRow("", self.chkAddToProject)

        row = QtWidgets.QHBoxLayout()
        self.txtExport = QtWidgets.QLineEdit()
        self.txtExport.setPlaceholderText("(비우면 임시 폴더에 생성; 지정하면 GeoTIFF 스택+manifest 저장)")
        self.btnBrowse = QtWidgets.QPushButton("찾기…")
        self.btnBrowse.clicked.connect(self._on_browse)
        row.addWidget(self.txtExport, 1)
        row.addWidget(self.btnBrowse)
        w = QtWidgets.QWidget()
        w.setLayout(row)
        fout.addRow("내보내기 폴더:", w)
        layout.addWidget(grp_out)

        btn_row = QtWidgets.QHBoxLayout()
        self.btnRun = QtWidgets.QPushButton("생성")
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

        self.resize(640, 660)

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

    def _on_browse(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "내보내기 폴더 선택")
        if d:
            self.txtExport.setText(d)

    def _parse_radii(self) -> List[int]:
        out: List[int] = []
        for tok in str(self.txtTpiRadii.text() or "").replace(" ", "").split(","):
            if not tok:
                continue
            try:
                v = int(float(tok))
                if v >= 1 and v not in out:
                    out.append(v)
            except Exception:
                continue
        return out or [5]

    def _raster_source(self, layer) -> str:
        try:
            return (str(layer.source() or "").split("|", 1)[0]).strip()
        except Exception:
            return ""

    def _on_run(self):
        dem = self.cmbDem.currentLayer()
        if dem is None or not isinstance(dem, QgsRasterLayer) or not dem.isValid():
            push_message(self.iface, "오류", "유효한 DEM 래스터를 선택하세요.", level=2, duration=6)
            return
        opt = {k: bool(cb.isChecked()) for k, cb in self.checks.items()}
        if not any(opt.values()):
            push_message(self.iface, "오류", "생성할 변수를 하나 이상 선택하세요.", level=2, duration=6)
            return

        export_dir = str(self.txtExport.text() or "").strip()
        if export_dir:
            try:
                os.makedirs(export_dir, exist_ok=True)
            except Exception as e:
                push_message(self.iface, "오류", f"내보내기 폴더를 만들 수 없습니다: {e}", level=2, duration=7)
                return

        dem_source = self._raster_source(dem)
        if not dem_source:
            push_message(self.iface, "오류", "DEM 파일 경로를 읽을 수 없습니다.", level=2, duration=6)
            return

        px = float(self.spinPixel.value())
        if px <= 0:
            try:
                px = float(dem.rasterUnitsPerPixelX())
            except Exception:
                px = 0.0
        if px <= 0:
            push_message(self.iface, "오류", "출력 픽셀 크기를 확인할 수 없습니다.", level=2, duration=6)
            return

        extent_crs = dem.crs().authid()
        extent_str = None
        aoi = self.cmbAoi.currentLayer()
        if self.chkClip.isChecked() and isinstance(aoi, QgsVectorLayer):
            ext = _aoi_extent_in_crs(aoi, selected_only=self.chkAoiSelected.isChecked(), dst_crs=dem.crs())
            if ext is not None and not ext.isEmpty():
                extent_str = f"{ext.xMinimum()},{ext.xMaximum()},{ext.yMinimum()},{ext.yMaximum()}"

        run_id = new_run_id("cov")
        try:
            ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)
        except Exception:
            pass

        progress = QtWidgets.QProgressDialog("DEM 파생 변수 생성 중…", "취소", 0, 100, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        QtWidgets.QApplication.processEvents()

        def _progress_cb(pct, msg):
            progress.setValue(int(pct))
            progress.setLabelText(str(msg))
            QtWidgets.QApplication.processEvents()

        builder = DemCovariatesBuilder(
            dem_source=dem_source,
            pixel_size=px,
            extent_str=extent_str,
            extent_crs=extent_crs,
            options=opt,
            tpi_radii=self._parse_radii() if opt.get("tpi") else [],
            export_dir=export_dir,
            run_id=run_id,
            progress_cb=_progress_cb,
            should_cancel=progress.wasCanceled,
        )

        self.btnRun.setEnabled(False)
        try:
            res = builder.build()
        finally:
            self.btnRun.setEnabled(True)
            try:
                progress.close()
            except Exception:
                pass

        if not res or not res.ok:
            push_message(self.iface, "오류", (res.message if res else "실패"), level=2, duration=9)
            restore_ui_focus(self)
            return

        if self.chkAddToProject.isChecked():
            try:
                self._add_layers(res)
            except Exception as e:
                log_exception("Add covariate layers error", e)

        msg = f"완료: {len(res.covariates)}개 변수"
        if res.export_dir:
            msg += f" → {res.export_dir}"
        push_message(self.iface, "DEM 변수", msg, level=0, duration=8)
        log_message(f"DEM covariates done: {len(res.covariates)} vars (run {res.run_id})", level=Qgis.Info)
        restore_ui_focus(self)

    def _add_layers(self, res: _Result):
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        parent = root.findGroup(PARENT_GROUP_NAME) or root.insertGroup(0, PARENT_GROUP_NAME)
        group = parent.insertGroup(0, f"변수_{res.run_id}")
        group.setExpanded(False)
        for c in res.covariates:
            try:
                lyr = QgsRasterLayer(c.path, c.label)
                if not lyr.isValid():
                    continue
                set_archtoolkit_layer_metadata(
                    lyr, tool_id="dem_covariates", run_id=res.run_id,
                    kind=c.kind, units=c.units,
                    params={"variable": c.key, "description": c.description},
                )
                project.addMapLayer(lyr, False)
                group.insertLayer(0, lyr)
            except Exception:
                continue

    def _on_help(self):
        html = (
            "<h3>DEM 파생 변수 일괄 생성기</h3>"
            "<p>DEM 하나에서 예측모델(MaxEnt 등)용 파생변수를 <b>동일 기준 격자</b>(CRS·범위·픽셀크기·NoData)로 "
            "한 번에 생성합니다. 모든 변수가 정렬되어 있어 별도 리샘플 없이 모델 입력으로 쓸 수 있습니다.</p>"
            "<h4>변수</h4>"
            "<ul>"
            "<li><b>표고/경사도</b>: 기본 지형.</li>"
            "<li><b>북향성/동향성</b>: cos/sin(aspect). 원형인 raw aspect 대신 모델에 바로 쓸 수 있는 형태.</li>"
            "<li><b>TRASP</b>: 일사/열부하 프록시(Roberts &amp; Cooper 1989). 0=북동(서늘/습), 1=남서(따뜻/건조).</li>"
            "<li><b>TRI/거칠기</b>: 지형 험준도(Riley 1999) / 국소 기복.</li>"
            "<li><b>TPI 다중스케일</b>: 여러 반경의 지형위치지수(Weiss 2001) — 능선/사면/곡저 맥락.</li>"
            "</ul>"
            "<h4>내보내기</h4>"
            "<p>폴더를 지정하면 각 변수를 <code>&lt;변수&gt;.tif</code>로 저장하고 "
            "<code>covariates_manifest.csv</code>(변수 목록/설명)를 함께 만듭니다.</p>"
            "<p style='color:#455a64'>QGIS 기본 구성(GDAL/NumPy)만 사용합니다.</p>"
        )
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            show_help_dialog(parent=self, title="DEM 변수 생성 도움말", html=html, plugin_dir=plugin_dir)
        except Exception:
            pass
