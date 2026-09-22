# -*- coding: utf-8 -*-
#
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
지구화학도(WMS 등) RGB 래스터를 범례 기반으로 수치화하고, 구간별 폴리곤으로 변환합니다.

중요: WMS는 원자료 수치가 아니라 "렌더링된 이미지"이므로, 이 도구는 범례(색-값)를 이용한 역추정입니다.
따라서 안티앨리어싱/경계선/투명도 등으로 인한 오차가 있을 수 있습니다.

프리셋: Fe2O3(사용자 제공 범례 포인트 기반) + Pb/Cu/Zn/Sr/Ba/CaO(백분위 구간값은 범례에서 읽었고,
색상 팔레트는 Fe2O3와 같다고 가정함 - 실제 팔레트가 다르면 색 매칭 허용오차(RGB_MATCH_TOLERANCE)에 걸려
NoData로 제외되고 경고가 뜸).
"""

import math
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from osgeo import gdal, ogr, osr

import processing
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtGui import QColor, QImage
from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsRendererCategory,
    QgsVectorLayer,
)
from .qtcompat import FT_INT, FT_DOUBLE, FT_STRING, SHADER_INTERPOLATED
from qgis.gui import QgsMapLayerComboBox

from .utils import (
    log_swallowed,
    log_exception,
    log_message,
    push_message,
    restore_ui_focus,
    set_archtoolkit_layer_metadata,
)
from .raster_io import write_single_band_geotiff
from .atomic_output import (
    atomic_publish_file,
    cleanup_staging_path,
    reserve_staging_path,
)
from .live_log_dialog import ensure_live_log_dialog
from .help_dialog import show_help_dialog
from . import dialog_memory
from .icons import icon as plugin_icon
from .i18n import get_output_group_name
from .geochem_legend import (
    LegendCsvError,
    LegendPoint,
    RGB_MATCH_TOLERANCE as _RGB_MATCH_TOLERANCE,
    interp_rgb_to_value as _interp_rgb_to_value,
    legend_points_from_csv as _legend_points_from_csv,
    legend_sample_rows as _legend_sample_rows,
    mask_black_lines as _mask_black_lines,
    points_to_breaks as _points_to_breaks,
    sampled_legend_problem as _sampled_legend_problem,
)
from .raster_io import inv_geotransform


PARENT_GROUP_NAME = get_output_group_name("geochem", "ArchToolkit - GeoChem")


@dataclass(frozen=True)
class GeoChemPreset:
    key: str
    label: str
    unit: str
    points: Sequence[LegendPoint]


FE2O3_POINTS: List[LegendPoint] = [
    LegendPoint(0.0, (204, 204, 204)),
    LegendPoint(3.1, (0, 38, 115)),
    LegendPoint(3.5, (0, 112, 255)),
    LegendPoint(3.9, (0, 197, 255)),
    LegendPoint(4.5, (0, 255, 0)),
    LegendPoint(5.7, (85, 255, 0)),
    LegendPoint(7.1, (255, 255, 0)),
    LegendPoint(8.5, (255, 170, 0)),
    LegendPoint(9.4, (255, 85, 0)),
    LegendPoint(12.0, (230, 0, 0)),
    LegendPoint(51.0, (115, 12, 12)),
]

PB_POINTS: List[LegendPoint] = [
    # Legend from percentile ramp (ppm): 5=18, 10=20, 15=21, 25=24, 50=28, 75=32, 90=36, 95=41, 99=57, 100=1363
    # We reuse the same base palette as other GeoChem layers (blue->red) to match the WMS styling.
    LegendPoint(0.0, (204, 204, 204)),  # Absent data
    LegendPoint(18.0, (0, 38, 115)),  # 5%
    LegendPoint(20.0, (0, 112, 255)),  # 10%
    LegendPoint(21.0, (0, 197, 255)),  # 15%
    LegendPoint(24.0, (0, 255, 0)),  # 25%
    LegendPoint(28.0, (85, 255, 0)),  # 50%
    LegendPoint(32.0, (255, 255, 0)),  # 75%
    LegendPoint(36.0, (255, 170, 0)),  # 90%
    LegendPoint(41.0, (255, 85, 0)),  # 95%
    LegendPoint(57.0, (230, 0, 0)),  # 99%
    LegendPoint(1363.0, (115, 12, 12)),  # 100%
]

CU_POINTS: List[LegendPoint] = [
    # Legend from percentile ramp (ppm): 5=10, 10=12, 15=14, 25=17, 50=23, 75=33, 90=45, 95=58, 99=104, 100=2104
    LegendPoint(0.0, (204, 204, 204)),  # Absent data
    LegendPoint(10.0, (0, 38, 115)),  # 5%
    LegendPoint(12.0, (0, 112, 255)),  # 10%
    LegendPoint(14.0, (0, 197, 255)),  # 15%
    LegendPoint(17.0, (0, 255, 0)),  # 25%
    LegendPoint(23.0, (85, 255, 0)),  # 50%
    LegendPoint(33.0, (255, 255, 0)),  # 75%
    LegendPoint(45.0, (255, 170, 0)),  # 90%
    LegendPoint(58.0, (255, 85, 0)),  # 95%
    LegendPoint(104.0, (230, 0, 0)),  # 99%
    LegendPoint(2104.0, (115, 12, 12)),  # 100%
]

ZN_POINTS: List[LegendPoint] = [
    # Legend from percentile ramp (ppm): 5=45, 10=57, 15=66, 25=79, 50=107, 75=149, 90=212, 95=272, 99=542, 100=21100
    LegendPoint(0.0, (204, 204, 204)),  # Absent data
    LegendPoint(45.0, (0, 38, 115)),  # 5%
    LegendPoint(57.0, (0, 112, 255)),  # 10%
    LegendPoint(66.0, (0, 197, 255)),  # 15%
    LegendPoint(79.0, (0, 255, 0)),  # 25%
    LegendPoint(107.0, (85, 255, 0)),  # 50%
    LegendPoint(149.0, (255, 255, 0)),  # 75%
    LegendPoint(212.0, (255, 170, 0)),  # 90%
    LegendPoint(272.0, (255, 85, 0)),  # 95%
    LegendPoint(542.0, (230, 0, 0)),  # 99%
    LegendPoint(21100.0, (115, 12, 12)),  # 100%
]

SR_POINTS: List[LegendPoint] = [
    # Legend from percentile ramp (ppm): 5=57, 10=72, 15=83, 25=99, 50=135, 75=192, 90=275, 95=342, 99=496, 100=3645
    LegendPoint(0.0, (204, 204, 204)),  # Absent data
    LegendPoint(57.0, (0, 38, 115)),  # 5%
    LegendPoint(72.0, (0, 112, 255)),  # 10%
    LegendPoint(83.0, (0, 197, 255)),  # 15%
    LegendPoint(99.0, (0, 255, 0)),  # 25%
    LegendPoint(135.0, (85, 255, 0)),  # 50%
    LegendPoint(192.0, (255, 255, 0)),  # 75%
    LegendPoint(275.0, (255, 170, 0)),  # 90%
    LegendPoint(342.0, (255, 85, 0)),  # 95%
    LegendPoint(496.0, (230, 0, 0)),  # 99%
    LegendPoint(3645.0, (115, 12, 12)),  # 100%
]

BA_POINTS: List[LegendPoint] = [
    # Legend from percentile ramp (ppm): 5=734, 10=853, 15=935, 25=1050, 50=1268, 75=1507, 90=1752, 95=1920, 99=2362, 100=15840
    LegendPoint(0.0, (204, 204, 204)),  # Absent data
    LegendPoint(734.0, (0, 38, 115)),  # 5%
    LegendPoint(853.0, (0, 112, 255)),  # 10%
    LegendPoint(935.0, (0, 197, 255)),  # 15%
    LegendPoint(1050.0, (0, 255, 0)),  # 25%
    LegendPoint(1268.0, (85, 255, 0)),  # 50%
    LegendPoint(1507.0, (255, 255, 0)),  # 75%
    LegendPoint(1752.0, (255, 170, 0)),  # 90%
    LegendPoint(1920.0, (255, 85, 0)),  # 95%
    LegendPoint(2362.0, (230, 0, 0)),  # 99%
    LegendPoint(15840.0, (115, 12, 12)),  # 100%
]

CAO_POINTS: List[LegendPoint] = [
    # Legend from percentile ramp (%): 5=0.40, 10=0.50, 15=0.58, 25=0.73, 50=1.18, 75=1.90, 90=2.99, 95=4.05, 99=9.03, 100=53.07
    LegendPoint(0.0, (204, 204, 204)),  # Absent data
    LegendPoint(0.40, (0, 38, 115)),  # 5%
    LegendPoint(0.50, (0, 112, 255)),  # 10%
    LegendPoint(0.58, (0, 197, 255)),  # 15%
    LegendPoint(0.73, (0, 255, 0)),  # 25%
    LegendPoint(1.18, (85, 255, 0)),  # 50%
    LegendPoint(1.90, (255, 255, 0)),  # 75%
    LegendPoint(2.99, (255, 170, 0)),  # 90%
    LegendPoint(4.05, (255, 85, 0)),  # 95%
    LegendPoint(9.03, (230, 0, 0)),  # 99%
    LegendPoint(53.07, (115, 12, 12)),  # 100%
]

PRESETS: Dict[str, GeoChemPreset] = {
    "fe2o3": GeoChemPreset(key="fe2o3", label="Fe2O3 (산화철)", unit="%", points=FE2O3_POINTS),
    "pb": GeoChemPreset(key="pb", label="Pb (납)", unit="ppm", points=PB_POINTS),
    "cu": GeoChemPreset(key="cu", label="Cu (구리)", unit="ppm", points=CU_POINTS),
    "zn": GeoChemPreset(key="zn", label="Zn (아연)", unit="ppm", points=ZN_POINTS),
    "sr": GeoChemPreset(key="sr", label="Sr (스트론튬)", unit="ppm", points=SR_POINTS),
    "ba": GeoChemPreset(key="ba", label="Ba (바륨)", unit="ppm", points=BA_POINTS),
    "cao": GeoChemPreset(key="cao", label="CaO (칼슘)", unit="%", points=CAO_POINTS),
}


def _safe_custom_preset_key(label: str) -> str:
    txt = (label or "").strip().lower()
    txt = re.sub(r"[^a-z0-9]+", "_", txt).strip("_")
    if not txt:
        txt = "preset"
    return f"custom_{txt}_{uuid.uuid4().hex[:6]}"


_inv_geotransform = inv_geotransform


def _window_geotransform(gt, xoff: int, yoff: int):
    """Compute a sub-window geotransform for an affine geotransform."""
    return (
        float(gt[0] + xoff * gt[1] + yoff * gt[2]),
        float(gt[1]),
        float(gt[2]),
        float(gt[3] + xoff * gt[4] + yoff * gt[5]),
        float(gt[4]),
        float(gt[5]),
    )


def _gdal_rasterize_wkt_mask(
    *,
    geom_wkt: str,
    xsize: int,
    ysize: int,
    geotransform,
    projection_wkt: str,
    all_touched: bool = True,
) -> Optional[np.ndarray]:
    """Rasterize a polygon WKT into a boolean mask (True inside).

    ``all_touched=True`` burns every pixel the polygon so much as clips (the
    right thing for the AOI clip mask, where over-inclusion is harmless).
    ``all_touched=False`` is GDAL's default pixel-centre rule, the one QGIS
    zonal statistics uses; zone polygons must use it, otherwise pix_in and
    every derived area are computed over a zone dilated by up to one pixel
    on every side (a 10 m test pit in 30 m pixels came back as 3600 m2).
    """
    if not geom_wkt:
        return None
    try:
        geom = ogr.CreateGeometryFromWkt(str(geom_wkt))
    except Exception:
        geom = None
    if geom is None:
        return None

    drv = gdal.GetDriverByName("MEM")
    ds = drv.Create("", int(xsize), int(ysize), 1, gdal.GDT_Byte)
    ds.SetGeoTransform(geotransform)
    ds.SetProjection(projection_wkt)
    band = ds.GetRasterBand(1)
    band.Fill(0)
    # gdal.RasterizeGeometries does NOT exist in the GDAL Python bindings —
    # burn the geometry through an in-memory OGR layer + gdal.RasterizeLayer
    # (the only Create-driver rasterize API available), otherwise the whole
    # AOI mask was a silent no-op and zonal stats came back empty.
    try:
        vdrv = ogr.GetDriverByName("Memory")
        vds = vdrv.CreateDataSource("mask")
        try:
            srs = osr.SpatialReference()
            srs.ImportFromWkt(str(projection_wkt))
        except Exception:
            srs = None
        vlyr = vds.CreateLayer("mask", srs, ogr.wkbUnknown)
        feat = ogr.Feature(vlyr.GetLayerDefn())
        feat.SetGeometry(geom)
        vlyr.CreateFeature(feat)
        rast_opts = ["ALL_TOUCHED=TRUE"] if all_touched else []
        gdal.RasterizeLayer(ds, [1], vlyr, burn_values=[1], options=rast_opts)
        vds = None
    except Exception:
        ds = None
        return None
    arr = band.ReadAsArray()
    ds = None
    try:
        return arr.astype(np.uint8, copy=False) > 0
    except Exception:
        return None


def _gdal_fill_nodata_nearestish(*, arr: np.ndarray, nodata: float, max_search_dist_px: int) -> np.ndarray:
    """Fill nodata/NaN using GDAL FillNodata (fast, no scipy).

    Note: This is not a perfect 'nearest' in Euclidean sense, but with smoothingIterations=0 it preserves edges well.
    """
    a = arr.astype(np.float32, copy=True)
    a[~np.isfinite(a)] = float(nodata)

    ysize, xsize = a.shape
    drv = gdal.GetDriverByName("MEM")
    ds = drv.Create("", int(xsize), int(ysize), 1, gdal.GDT_Float32)
    band = ds.GetRasterBand(1)
    band.WriteArray(a)
    band.SetNoDataValue(float(nodata))
    try:
        gdal.FillNodata(
            targetBand=band,
            maskBand=None,
            maxSearchDist=int(max(1, max_search_dist_px)),
            smoothingIterations=0,
        )
    except Exception as _exc:
        log_swallowed("geochem_polygonize_dialog._gdal_fill_nodata_nearestish", _exc)
    filled = band.ReadAsArray().astype(np.float32, copy=False)
    ds = None
    return filled


def _classify_to_bins(
    *,
    values: np.ndarray,
    breaks: Sequence[float],
    nodata_class: int = 0,
    nodata_value: Optional[float] = None,
) -> np.ndarray:
    br = [float(x) for x in breaks]
    if len(br) < 2:
        raise ValueError("Need at least 2 breaks")

    v = values.astype(np.float32, copy=False)
    cls = np.full(v.shape, int(nodata_class), dtype=np.int16)

    valid = np.isfinite(v)
    if nodata_value is not None:
        try:
            valid &= v != np.float32(float(nodata_value))
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._classify_to_bins", _exc)

    if not np.any(valid):
        return cls

    vmin = float(br[0])
    vmax = float(br[-1])
    vv = np.clip(v, vmin, vmax)

    bins = br[1:-1]  # internal thresholds
    idx = np.digitize(vv, bins=bins, right=False).astype(np.int16, copy=False)  # 0..n-1
    cls[valid] = idx[valid] + 1  # 1..n_intervals
    return cls


def _interval_label(v0: float, v1: float, unit: str) -> str:
    if unit:
        return f"{v0:g}-{v1:g}{unit}"
    return f"{v0:g}-{v1:g}"


def _rgb_for_value(*, points: Sequence[LegendPoint], value: float) -> Tuple[int, int, int]:
    """Interpolate an RGB color for a scalar value using legend points (value-space interpolation)."""
    pts = sorted(points, key=lambda p: float(p.value))
    if not pts:
        return (204, 204, 204)
    v = float(value)

    if v <= float(pts[0].value):
        return pts[0].rgb
    if v >= float(pts[-1].value):
        return pts[-1].rgb

    for i in range(len(pts) - 1):
        v0 = float(pts[i].value)
        v1 = float(pts[i + 1].value)
        if v0 <= v <= v1:
            if v1 <= v0:
                return pts[i + 1].rgb
            t = (v - v0) / (v1 - v0)
            c0 = pts[i].rgb
            c1 = pts[i + 1].rgb
            r = int(round(float(c0[0]) + t * (float(c1[0]) - float(c0[0]))))
            g = int(round(float(c0[1]) + t * (float(c1[1]) - float(c0[1]))))
            b = int(round(float(c0[2]) + t * (float(c1[2]) - float(c0[2]))))
            return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))

    return pts[-1].rgb


def _parse_float_list(text: str) -> List[float]:
    vals: List[float] = []
    for part in (text or "").replace(";", ",").split(","):
        t = part.strip()
        if not t:
            continue
        _skip_436 = False
        try:
            vals.append(float(t))
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._parse_float_list", _exc)
            log_swallowed("tools/geochem_polygonize_dialog.py:438 (_parse_float_list)", _exc)
            _skip_436 = True
        if _skip_436:
            continue
    return vals


def _sample_qimage_rgb(image: QImage, x: int, y: int, radius: int = 1) -> Tuple[int, int, int]:
    if image is None or image.isNull():
        return (204, 204, 204)
    w = int(image.width() or 0)
    h = int(image.height() or 0)
    if w <= 0 or h <= 0:
        return (204, 204, 204)

    x = max(0, min(w - 1, int(x)))
    y = max(0, min(h - 1, int(y)))
    r0 = max(0, x - int(radius))
    r1 = min(w - 1, x + int(radius))
    c0 = max(0, y - int(radius))
    c1 = min(h - 1, y + int(radius))

    rs = 0
    gs = 0
    bs = 0
    n = 0
    for yy in range(c0, c1 + 1):
        for xx in range(r0, r1 + 1):
            _skip_465 = False
            try:
                col = QColor(image.pixel(xx, yy))
                rs += int(col.red())
                gs += int(col.green())
                bs += int(col.blue())
                n += 1
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._sample_qimage_rgb", _exc)
                log_swallowed("tools/geochem_polygonize_dialog.py:471 (_sample_qimage_rgb)", _exc)
                _skip_465 = True
            if _skip_465:
                continue
    if n <= 0:
        return (204, 204, 204)
    return (int(round(rs / n)), int(round(gs / n)), int(round(bs / n)))


def _sample_qimage_alpha(image: QImage, x: int, y: int) -> int:
    """Alpha (0-255) of one pixel; 255 when the image has no alpha or on error.

    ``_sample_qimage_rgb`` goes through QColor(QRgb), which drops alpha, so a
    transparent legend margin read as opaque black. The importer needs the
    alpha separately to recognise that it sampled the margin.
    """
    try:
        if image is None or image.isNull():
            return 255
        w = int(image.width() or 0)
        h = int(image.height() or 0)
        if w <= 0 or h <= 0:
            return 255
        if not image.hasAlphaChannel():
            return 255
        xx = max(0, min(w - 1, int(x)))
        yy = max(0, min(h - 1, int(y)))
        return int(image.pixelColor(xx, yy).alpha())
    except Exception as _exc:
        log_swallowed("geochem_polygonize_dialog._sample_qimage_alpha", _exc)
        return 255


_LEGEND_SAMPLE_PROBLEMS: Dict[str, str] = {
    "endpoint_transparent": "범례 샘플의 끝 색이 투명합니다(색상바 밖 여백을 샘플링함).",
    "endpoint_white": "범례 샘플의 끝 색이 흰색입니다(여백/배경을 샘플링함).",
    "endpoint_black": "범례 샘플의 끝 색이 검정입니다(테두리/배경을 샘플링함).",
    "all_identical": "샘플링한 색이 모두 같습니다(샘플 x 위치가 색상바 위가 아닙니다).",
}


class GeoChemPolygonizeDialog(QtWidgets.QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        # Remember the last-used inputs between sessions (tools/dialog_memory.py).
        dialog_memory.attach(self, "geochem")
        self.iface = iface
        self.setWindowTitle("지구화학도 래스터 수치화 (GeoChem WMS → Raster) - ArchToolkit")

        try:
            self.setWindowIcon(plugin_icon("geochem.png"))
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog.__init__", _exc)

        self._tmp_dir = None

        layout = QtWidgets.QVBoxLayout(self)

        desc = QtWidgets.QLabel(
            "<b>지구화학도 래스터 수치화</b><br>"
            "WMS 등 RGB 래스터(이미지)를 범례 기반으로 <b>값 래스터</b>로 복원하고,<br>"
            "원하면 <b>구간(class) 래스터 / 폴리곤</b>까지 생성합니다. (원자료 수치가 아닌 ‘역추정’입니다.)"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("background:#f0f0f0; padding:6px; border-radius:4px;")
        desc.setToolTip(
            "워크플로우:\n"
            "1) RGB 지구화학도(WMS/래스터)를 조사지역 경계(사각형)로 잘라 GeoTIFF로 저장\n"
            "2) RGB → 값(%) 래스터로 변환(범례 기반)\n"
            "3) (옵션) 값 → 구간(class) 래스터 생성\n"
            "4) (옵션) 구간 폴리곤 생성 + dissolve\n"
            "5) (옵션) 중심점(포인트) 생성\n\n"
            "팁:\n"
            "- 검은 경계선/텍스트가 지저분하면 '검은 경계선 제거(보간)'을 켜보세요.\n"
            "- 픽셀 크기를 작게 할수록 디테일은 좋아지지만 느려질 수 있습니다."
        )
        layout.addWidget(desc)

        grp_in = QtWidgets.QGroupBox("1. 입력")
        grid = QtWidgets.QGridLayout(grp_in)

        self.cmbRaster = QgsMapLayerComboBox(grp_in)
        self.cmbRaster.setFilters(Qgis.LayerFilter.RasterLayer)
        self.cmbAoi = QgsMapLayerComboBox(grp_in)
        self.cmbAoi.setFilters(Qgis.LayerFilter.VectorLayer)

        grid.addWidget(QtWidgets.QLabel("RGB 래스터(WMS)"), 0, 0)
        grid.addWidget(self.cmbRaster, 0, 1, 1, 2)
        grid.addWidget(QtWidgets.QLabel("조사지역 폴리곤"), 1, 0)
        grid.addWidget(self.cmbAoi, 1, 1, 1, 2)

        self.chkSelectedOnly = QtWidgets.QCheckBox("조사지역 선택 피처만 사용")
        self.chkSelectedOnly.setChecked(False)
        grid.addWidget(self.chkSelectedOnly, 2, 0, 1, 3)

        layout.addWidget(grp_in)

        grp_preset = QtWidgets.QGroupBox("2. 원소/범례 프리셋")
        h = QtWidgets.QHBoxLayout(grp_preset)
        self.cmbPreset = QtWidgets.QComboBox(grp_preset)
        for k, p in PRESETS.items():
            self.cmbPreset.addItem(p.label, k)
        self.txtUnit = QtWidgets.QLineEdit(grp_preset)
        self.txtUnit.setText(PRESETS["fe2o3"].unit)
        self.txtUnit.setMaximumWidth(80)
        self.txtUnit.setToolTip("구간 라벨 표시용 단위(예: %, wt%).")

        self.btnPresetImport = QtWidgets.QToolButton(grp_preset)
        self.btnPresetImport.setText("불러오기")
        self.btnPresetImport.setToolTip("사용자 범례 프리셋을 추가합니다(CSV/이미지 샘플링).")
        self.btnPresetImport.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        try:
            menu = QtWidgets.QMenu(self.btnPresetImport)
            act_csv = menu.addAction("CSV로 프리셋 불러오기…")
            act_csv.triggered.connect(self._import_preset_from_csv)
            act_img = menu.addAction("범례 이미지에서 샘플링…")
            act_img.triggered.connect(self._import_preset_from_legend_image)
            self.btnPresetImport.setMenu(menu)
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:563 (__init__)", _exc)
        h.addWidget(QtWidgets.QLabel("프리셋"))
        h.addWidget(self.cmbPreset, 1)
        h.addWidget(QtWidgets.QLabel("단위"))
        h.addWidget(self.txtUnit)
        h.addWidget(self.btnPresetImport)
        layout.addWidget(grp_preset)

        grp_clip = QtWidgets.QGroupBox("3. 처리/보정 옵션")
        grid2 = QtWidgets.QGridLayout(grp_clip)
        self.spinPixelSize = QtWidgets.QDoubleSpinBox(grp_clip)
        self.spinPixelSize.setDecimals(2)
        self.spinPixelSize.setMinimum(0.0)
        self.spinPixelSize.setMaximum(1000000.0)
        self.spinPixelSize.setSingleStep(1.0)
        self.spinPixelSize.setValue(0.0)
        self.spinPixelSize.setToolTip(
            "0이면 현재 지도 해상도(캔버스 mapUnitsPerPixel)를 사용합니다.\n"
            "프로젝트 CRS와 래스터 CRS가 다르면 조사지역 위치에서 래스터 CRS 단위로 환산합니다."
        )

        self.spinExtentBuffer = QtWidgets.QDoubleSpinBox(grp_clip)
        self.spinExtentBuffer.setDecimals(0)
        self.spinExtentBuffer.setMinimum(0.0)
        self.spinExtentBuffer.setMaximum(10000000.0)
        self.spinExtentBuffer.setSingleStep(100.0)
        self.spinExtentBuffer.setValue(0.0)
        self.spinExtentBuffer.setToolTip("조사지역 경계(사각형)의 바깥쪽으로 버퍼(m)를 줍니다. 0이면 버퍼 없음.")

        self.chkMaskAoi = QtWidgets.QCheckBox("AOI 마스크 적용(폴리곤 내부만)")
        self.chkMaskAoi.setChecked(True)
        self.chkMaskAoi.setToolTip("조사지역 폴리곤 내부만 유효값으로 두고 바깥은 NoData로 처리합니다. (분석/중심점 계산에 권장)")

        self.chkLowAsNoData = QtWidgets.QCheckBox("0~최소값(회색) 구간을 NoData로 취급")
        self.chkLowAsNoData.setChecked(True)
        self.chkLowAsNoData.setToolTip(
            "범례의 최저값(보통 회색)은 실제 데이터가 아닌 배경/무자료로 보고 NoData(-9999)로 처리합니다.\n"
            "예: Fe2O3 프리셋은 0~3.1 구간을 NoData로 취급"
        )

        self.chkFixMax = QtWidgets.QCheckBox("최댓값을 범례 최댓값으로 보정")
        self.chkFixMax.setChecked(False)
        self.chkFixMax.setToolTip("색상 매칭 결과의 최댓값이 범례 최댓값보다 낮게 나오면, 전체를 비례 스케일합니다.")

        self.chkSnapMax = QtWidgets.QCheckBox("고농도 스냅(최댓값)")
        self.chkSnapMax.setChecked(False)
        self.chkSnapMax.setToolTip("마지막 구간(예: 12~51)에서 일정 이상이면 최댓값으로 강제합니다. (로컬 보정)")
        self.spinSnapT = QtWidgets.QDoubleSpinBox(grp_clip)
        self.spinSnapT.setDecimals(2)
        self.spinSnapT.setMinimum(0.0)
        self.spinSnapT.setMaximum(1.0)
        self.spinSnapT.setSingleStep(0.05)
        self.spinSnapT.setValue(0.7)
        self.spinSnapT.setToolTip("마지막 구간에서 t(0~1)가 이 값보다 크면 최댓값으로 스냅합니다.")

        self.chkInpaint = QtWidgets.QCheckBox("검은 경계선 제거(보간)")
        self.chkInpaint.setChecked(True)
        self.chkInpaint.setToolTip("무채색 계열의 어두운 경계선을 NoData로 보고 주변 값으로 메웁니다.")
        self.spinFillDist = QtWidgets.QSpinBox(grp_clip)
        self.spinFillDist.setMinimum(1)
        self.spinFillDist.setMaximum(500)
        self.spinFillDist.setValue(30)
        self.spinFillDist.setToolTip("보간 시 검색 거리(픽셀). 클수록 잘 메우지만 느릴 수 있습니다.")

        grid2.addWidget(QtWidgets.QLabel("픽셀 크기(지도 단위/px)"), 0, 0)
        grid2.addWidget(self.spinPixelSize, 0, 1)
        grid2.addWidget(QtWidgets.QLabel("조사지역 경계(사각형) 버퍼(m)"), 0, 2)
        grid2.addWidget(self.spinExtentBuffer, 0, 3)

        grid2.addWidget(self.chkMaskAoi, 1, 0, 1, 2)
        grid2.addWidget(self.chkFixMax, 1, 2, 1, 2)

        grid2.addWidget(self.chkInpaint, 2, 0, 1, 2)
        grid2.addWidget(QtWidgets.QLabel("보간 거리(px)"), 2, 2)
        grid2.addWidget(self.spinFillDist, 2, 3)

        grid2.addWidget(self.chkSnapMax, 3, 0, 1, 2)
        grid2.addWidget(QtWidgets.QLabel("스냅 t(0~1)"), 3, 2)
        grid2.addWidget(self.spinSnapT, 3, 3)

        grid2.addWidget(self.chkLowAsNoData, 4, 0, 1, 4)

        layout.addWidget(grp_clip)

        grp_out = QtWidgets.QGroupBox("4. 출력 옵션")
        grid3 = QtWidgets.QGridLayout(grp_out)

        self.chkSaveRasters = QtWidgets.QCheckBox("값 래스터 저장(영구)")
        self.chkSaveRasters.setChecked(True)
        self.chkSaveRasters.setToolTip(
            "값(value) 래스터를 프로젝트 홈(없으면 QGIS 프로필) 하위에 저장합니다.\n"
            "※ '구간(class) 래스터 생성'을 켠 경우, class 래스터도 함께 저장됩니다."
        )

        self.chkAddRasters = QtWidgets.QCheckBox("프로젝트에 래스터 레이어로 추가")
        self.chkAddRasters.setChecked(True)
        self.chkAddRasters.setToolTip(
            "저장된 래스터 레이어를 ArchToolkit - GeoChem 그룹에 함께 추가합니다.\n"
            "- value: 항상 추가\n"
            "- class: '구간(class) 래스터 생성'을 켠 경우에만 추가"
        )

        self.chkMakeClassRaster = QtWidgets.QCheckBox("구간(class) 래스터 생성(옵션)")
        self.chkMakeClassRaster.setChecked(False)
        self.chkMakeClassRaster.setToolTip(
            "연속값(value)을 범례 구간대로 정수 class(1..N)로 재분류한 래스터를 만듭니다.\n"
            "다음이 필요할 때만 켜세요:\n"
            "- 구간형(범주형) 지도가 필요할 때\n"
            "- '폴리곤 생성(구간별)'을 사용할 때(내부적으로 class가 필요함)\n\n"
            "대부분의 분석(MaxEnt/통계/가중 중심점)은 value 래스터만으로 충분합니다.\n"
            "단, value는 WMS 색상에서 역추정한 추정값이므로 안티앨리어싱·경계선·구간표에 따른 오차를 감안하세요."
        )

        self.chkMakePolygons = QtWidgets.QCheckBox("폴리곤 생성(구간별)")
        self.chkMakePolygons.setChecked(False)
        self.chkMakePolygons.setToolTip(
            "구간(class) 래스터를 폴리곤으로 변환합니다(요약/도면/편집/오버레이용).\n"
            "예: '구간별 면적'을 벡터로 보고 싶거나, 다른 레이어와 교차/편집이 필요할 때."
        )

        self.chkDissolve = QtWidgets.QCheckBox("구간별로 합치기(dissolve)")
        self.chkDissolve.setChecked(True)
        self.chkDissolve.setEnabled(False)
        self.chkDissolve.setToolTip("같은 구간(class)끼리 하나의 멀티폴리곤으로 합칩니다(도면/분석이 단순해짐).")

        self.chkDropNoData = QtWidgets.QCheckBox("NoData(투명) 폴리곤 제외")
        self.chkDropNoData.setChecked(True)
        self.chkDropNoData.setEnabled(False)
        self.chkDropNoData.setToolTip("class_id=0(투명/NoData) 폴리곤을 결과에서 제외합니다.")

        grid3.addWidget(self.chkSaveRasters, 0, 0)
        grid3.addWidget(self.chkAddRasters, 0, 1)
        grid3.addWidget(self.chkMakeClassRaster, 1, 0, 1, 2)
        grid3.addWidget(self.chkMakePolygons, 2, 0)
        grid3.addWidget(self.chkDissolve, 2, 1)
        grid3.addWidget(self.chkDropNoData, 3, 0, 1, 2)

        self.lblOutHelp = QtWidgets.QLabel(
            "TIP: value 래스터는 WMS 렌더링 색상을 범례(색-값)로 역추정한 추정값입니다(원자료 아님).\n"
            "- 프리셋 범례는 백분위 구간표라서 값은 구간 경계 사이의 선형 보간이며, 최상위 구간 색은 구간 상한값(예: Pb 1363 ppm)으로 기록됩니다.\n"
            "- 범례 색과 먼 픽셀(경계선·글자 등)은 NoData로 제외되고, 제외 비율이 5% 이상이면 경고합니다.\n"
            "- class 래스터/폴리곤은 ‘구간별(범주형) 결과’가 필요할 때만 켜세요."
        )
        self.lblOutHelp.setWordWrap(True)
        self.lblOutHelp.setStyleSheet("color: #555;")
        grid3.addWidget(self.lblOutHelp, 4, 0, 1, 2)
        layout.addWidget(grp_out)

        grp_zonal = QtWidgets.QGroupBox("5. 구역 통계(Zonal stats)")
        grid_z = QtWidgets.QGridLayout(grp_zonal)

        self.chkZonalStats = QtWidgets.QCheckBox("구역 통계 레이어 생성(폴리곤별 평균/구간면적)")
        self.chkZonalStats.setChecked(False)
        self.chkZonalStats.setToolTip(
            "선택한 구역(행정구역/유적폴리곤 등)마다 value/class 래스터를 집계합니다.\n"
            "- value: 평균/표준편차/최솟값/최댓값\n"
            "- class: 구간별 픽셀수/면적/비율\n"
            "- 픽셀 집계 기준: 픽셀 중심이 구역 안에 있는 픽셀만 셉니다(QGIS 구역 통계와 같은 규칙).\n"
            "  픽셀보다 작은 구역은 닿은 픽셀로 대체하며 burn_rule 필드에 all_touched로 표시됩니다.\n"
            "- zone_area: 구역 폴리곤 자체의 면적(타원체 m2). c*_area 합과 비교해 픽셀화 오차를 확인하세요.\n"
            "- fill_pct: 검은 경계선 제거로 보간된(측정값이 아닌) 픽셀의 비율\n\n"
            "※ 많은 피처/큰 해상도에서는 시간이 오래 걸릴 수 있습니다."
        )

        self.cmbZoneLayer = QgsMapLayerComboBox(grp_zonal)
        try:
            self.cmbZoneLayer.setFilters(Qgis.LayerFilter.PolygonLayer)
        except Exception:
            self.cmbZoneLayer.setFilters(Qgis.LayerFilter.VectorLayer)

        self.chkZoneSelectedOnly = QtWidgets.QCheckBox("구역 레이어 선택 피처만 사용")
        self.chkZoneSelectedOnly.setChecked(False)
        self.chkZoneSelectedOnly.setToolTip(
            "구역 레이어에서 '선택된 피처'만 통계 대상으로 씁니다.\n"
            "선택이 없으면 전체 피처를 사용하고 경고를 표시합니다."
        )

        grid_z.addWidget(self.chkZonalStats, 0, 0, 1, 2)
        grid_z.addWidget(QtWidgets.QLabel("구역(폴리곤) 레이어"), 1, 0)
        grid_z.addWidget(self.cmbZoneLayer, 1, 1)
        grid_z.addWidget(self.chkZoneSelectedOnly, 2, 0, 1, 2)

        layout.addWidget(grp_zonal)

        grp_center = QtWidgets.QGroupBox("6. 중심점(포인트)")
        grid4 = QtWidgets.QGridLayout(grp_center)
        self.chkWeightedCenter = QtWidgets.QCheckBox("중심점 생성")
        self.chkWeightedCenter.setChecked(False)
        self.chkWeightedCenter.setToolTip("값 래스터에서 중심점을 계산해 포인트 레이어로 추가합니다.")

        self.cmbCenterMethod = QtWidgets.QComboBox(grp_center)
        self.cmbCenterMethod.addItem("가중 평균 중심(질량중심)", "weighted_mean")
        self.cmbCenterMethod.addItem("무가중 평균 중심(선택 픽셀 중심)", "mean")
        self.cmbCenterMethod.addItem("최대값 픽셀(peak)", "peak")
        self.cmbCenterMethod.setToolTip(
            "중심점 산정 방식입니다.\n"
            "- 가중 평균: 값이 클수록 중심이 더 끌립니다.\n"
            "- 무가중 평균: 선택된 영역의 기하학적 중심(픽셀 평균)입니다.\n"
            "- peak: 선택된 픽셀 중 값이 가장 큰 위치입니다."
        )

        self.cmbWeightRule = QtWidgets.QComboBox(grp_center)
        self.cmbWeightRule.addItem("값 그대로 (w = max(value, 0))", "value")
        self.cmbWeightRule.addItem("값 거듭제곱 (w = max(value, 0)^p)", "power")
        self.cmbWeightRule.addItem("임계값 이상만 (w = value, value>=t)", "threshold")
        self.cmbWeightRule.addItem("임계값 이상만 (w = 1, value>=t)", "binary")
        self.cmbWeightRule.addItem("상위 %만 (w = value, top X%)", "top_pct")

        self.spinWeightPower = QtWidgets.QSpinBox(grp_center)
        self.spinWeightPower.setMinimum(1)
        self.spinWeightPower.setMaximum(8)
        self.spinWeightPower.setValue(2)
        self.spinWeightPower.setToolTip("거듭제곱 지수 p (w = max(value, 0)^p; 음수 값은 가중치 0)")

        self.spinWeightThreshold = QtWidgets.QDoubleSpinBox(grp_center)
        self.spinWeightThreshold.setDecimals(2)
        self.spinWeightThreshold.setMinimum(0.0)
        self.spinWeightThreshold.setMaximum(1_000_000.0)
        self.spinWeightThreshold.setValue(12.0)
        self.spinWeightThreshold.setToolTip("임계값 t (value>=t만 사용)")

        self.spinWeightTopPct = QtWidgets.QDoubleSpinBox(grp_center)
        self.spinWeightTopPct.setDecimals(1)
        self.spinWeightTopPct.setMinimum(0.1)
        self.spinWeightTopPct.setMaximum(100.0)
        self.spinWeightTopPct.setSingleStep(1.0)
        self.spinWeightTopPct.setValue(10.0)
        self.spinWeightTopPct.setToolTip("상위 X%만 사용 (예: 10이면 상위 10%)")

        grid4.addWidget(self.chkWeightedCenter, 0, 0, 1, 2)
        grid4.addWidget(QtWidgets.QLabel("중심점 방식"), 1, 0)
        grid4.addWidget(self.cmbCenterMethod, 1, 1)
        grid4.addWidget(QtWidgets.QLabel("가중치 규칙"), 2, 0)
        grid4.addWidget(self.cmbWeightRule, 2, 1)
        grid4.addWidget(QtWidgets.QLabel("p"), 3, 0)
        grid4.addWidget(self.spinWeightPower, 3, 1)
        grid4.addWidget(QtWidgets.QLabel("t"), 4, 0)
        grid4.addWidget(self.spinWeightThreshold, 4, 1)
        grid4.addWidget(QtWidgets.QLabel("X(%)"), 5, 0)
        grid4.addWidget(self.spinWeightTopPct, 5, 1)
        layout.addWidget(grp_center)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        self.btnRun = QtWidgets.QPushButton("실행")
        self.btnHelp = QtWidgets.QPushButton("도움말")
        self.btnClose = QtWidgets.QPushButton("닫기")
        btn_row.addWidget(self.btnRun)
        btn_row.addWidget(self.btnHelp)
        btn_row.addWidget(self.btnClose)
        layout.addLayout(btn_row)

        self.btnClose.clicked.connect(self.reject)
        self.btnRun.clicked.connect(self.run)
        self.btnHelp.clicked.connect(self._on_help)
        self.cmbPreset.currentIndexChanged.connect(self._on_preset_changed)
        self.chkMakePolygons.stateChanged.connect(self._update_polygon_ui)
        self.chkAddRasters.stateChanged.connect(self._on_add_rasters_changed)
        self.chkZonalStats.stateChanged.connect(self._update_zonal_ui)
        self.chkWeightedCenter.stateChanged.connect(self._update_weight_ui)
        self.cmbWeightRule.currentIndexChanged.connect(self._update_weight_ui)
        self.cmbCenterMethod.currentIndexChanged.connect(self._update_weight_ui)

        self._update_polygon_ui()
        self._update_zonal_ui()
        self._update_weight_ui()

        # Tooltips: keep the dialog short, show detailed guidance on hover.
        try:
            self.cmbRaster.setToolTip(
                "RGB 지구화학도 래스터/WMS 레이어를 선택하세요.\n"
                "- 보통 3밴드(R,G,B)입니다.\n"
                "- DEM 같은 단일밴드 래스터는 대상이 아닙니다."
            )
            self.cmbAoi.setToolTip(
                "조사지역(폴리곤) 레이어를 선택하세요.\n"
                "- 선택 피처만 사용할 수도 있습니다.\n"
                "- 실제로는 폴리곤 클립이 아니라 '경계 사각형(extent)'으로 잘라냅니다."
            )
            self.chkSelectedOnly.setToolTip(
                "조사지역 레이어에서 '선택된 피처'만 사용해 경계(extent)를 계산합니다.\n"
                "선택이 없으면 전체 피처를 사용하고 경고를 표시합니다."
            )
            self.cmbPreset.setToolTip(
                "원소/범례 프리셋을 선택합니다. 제공: Fe2O3, Pb, Cu, Zn, Sr, Ba, CaO.\n"
                "- Fe2O3: 사용자가 제공한 범례 포인트(색-값) 기반.\n"
                "- 나머지 6종: 백분위 구간값은 범례에서 읽었고, 색상 팔레트는 Fe2O3와 같은 파랑-빨강 팔레트로 '가정'했습니다.\n"
                "  실제 WMS 팔레트가 다르면 색 매칭에 실패한 픽셀이 NoData로 제외되고 경고가 뜹니다.\n"
                "  확실하게 하려면 '범례 가져오기'로 해당 도면의 범례를 직접 등록하세요."
            )
            self.txtUnit.setToolTip(
                "표시용 단위입니다.\n"
                "결과 폴리곤의 라벨(예: 3.1-3.5%)에 붙습니다."
            )
            self.spinPixelSize.setToolTip(
                "내보낼 래스터의 픽셀 크기(래스터 CRS 단위/px)입니다.\n"
                "- 0이면 현재 지도 해상도(mapUnitsPerPixel)를 사용합니다.\n"
                "  프로젝트 CRS와 래스터 CRS가 다르면 조사지역 위치에서 래스터 CRS 단위로 환산하고,\n"
                "  환산에 실패하면 '조사지역 긴 변/1024'를 쓰며 경고를 표시합니다.\n"
                "- 총 픽셀 수가 1,200만을 넘으면 픽셀을 자동으로 키우고 경고를 표시합니다.\n"
                "- 실제 사용한 픽셀 크기는 로그와 결과 래스터 메타데이터(pixel_size)에 기록됩니다.\n"
                "- 값이 작을수록 디테일↑, 처리시간/파일크기↑\n"
                "- WMS 색을 보존하려고 최근접(Nearest)으로 리샘플링합니다."
            )
            self.spinExtentBuffer.setToolTip(
                "조사지역 폴리곤을 감싸는 '경계 사각형(extent)'에 버퍼(m)를 추가합니다.\n"
                "0이면 버퍼 없음."
            )
            self.chkDissolve.setToolTip(
                "같은 구간(class)끼리 하나의 폴리곤으로 합칩니다.\n"
                "끄면 폴리곤 조각이 매우 많아질 수 있습니다."
            )
            self.chkFixMax.setToolTip(
                "클립 안에서 매칭된 최댓값이 범례 최댓값(예: 51%)보다 작으면 모든 값에\n"
                "(범례 최댓값 / 클립 최댓값)을 곱해 클립의 최댓값이 범례 최댓값이 되도록 늘립니다.\n"
                "※ 주의: 클립에 실제로 고농도 구간이 없다면 이 옵션은 없는 고농도 값을 만들어 냅니다.\n"
                "  WMS가 보이는 범위에 맞춰 색을 다시 스트레치했다는 것을 알 때만 켜세요.\n"
                "- 최댓값은 조사지역 마스크를 적용한 뒤(마스크를 켠 경우 조사지역 안 픽셀에서만) 구합니다.\n"
                "- 적용 여부/클립 최댓값/배율은 로그와 결과 래스터 메타데이터(fix_max)에 기록됩니다."
            )
            self.chkSnapMax.setToolTip(
                "마지막 구간(예: 12~51)에서 고농도 영역이 잘 안 잡힐 때 사용하는 로컬 보정입니다.\n"
                "- t는 마지막 구간의 색상 선분 위 위치(0~1)입니다.\n"
                "- t가 스냅값보다 크면 최댓값(예: 51)으로 강제합니다.\n"
                "※ 과하면 고농도 영역이 과대평가될 수 있습니다."
            )
            self.spinSnapT.setToolTip(
                "고농도 스냅 임계값입니다.\n"
                "- 0.7이면 마지막 구간 상위 30%를 최댓값으로 스냅합니다.\n"
                "- 값이 작을수록 더 많은 픽셀이 최댓값으로 들어갑니다."
            )
            self.chkInpaint.setToolTip(
                "무채색(검정/짙은 회색) 경계선을 NoData로 만든 뒤 주변 값으로 메웁니다.\n"
                "지괴 경계선/텍스트 등 '검은 선'이 결과를 깨뜨릴 때 켜세요.\n"
                "너무 과하면 경계 부근이 부드러워질 수 있습니다.\n"
                "※ 메운 픽셀은 측정값이 아닌 보간값이지만 이후 통계(구간 면적/구역 평균 등)에 그대로 포함됩니다.\n"
                "  메운 픽셀 수/비율은 로그와 결과 래스터 메타데이터(inpaint_fill_pct)에,\n"
                "  구역별 비율은 구역 통계의 fill_pct 필드에 기록됩니다."
            )
            self.spinFillDist.setToolTip(
                "보간 최대 검색 거리(px)입니다.\n"
                "- 경계선이 두껍거나 지저분할수록 값을 키워보세요.\n"
                "- 값이 클수록 더 멀리까지 메우지만 느려질 수 있습니다."
            )
            self.btnRun.setToolTip("실행합니다. (중간 산출물은 창을 닫을 때 정리됩니다)")
            self.btnClose.setToolTip("닫기")
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:884 (__init__)", _exc)

        self.resize(700, 650)

    def _on_help(self):
        html = """
<h3>GeoChem (지구화학도) 도움말</h3>
<p>
이 도구는 RGB 지구화학도(WMS/래스터)에서 <b>범례 색상→값</b>을 역추정하여
value/class 래스터와 폴리곤을 생성합니다.
</p>

<h4>입력/출력</h4>
<ul>
  <li><b>입력</b>: RGB 지구화학도 레이어, 조사지역(AOI) 폴리곤</li>
  <li><b>출력</b>: value 래스터(추정값), class 래스터(구간), (옵션) 구간 폴리곤/라벨</li>
  <li>(옵션) 중심점/가중중심, (옵션) Zonal 통계(행정구역/유적 폴리곤 등)</li>
</ul>

<h4>정확도/주의</h4>
<ul>
  <li>원자료가 아닌 “렌더링 이미지” 기반이라 텍스트/경계선/안티앨리어싱/압축에 의해 오차가 생길 수 있습니다.</li>
  <li>클립은 폴리곤 자체가 아니라 <b>경계 사각형(extent)</b> 기준입니다.</li>
  <li>가능하면 범례 이미지와 동일한 스타일(색상램프)로 보이는 WMS를 사용하세요.</li>
</ul>

<h4>팁</h4>
<ul>
  <li><b>Inpaint</b>: 검정 경계선/문자 때문에 값이 깨지면 켜고 <b>Fill distance</b>를 조절하세요.</li>
  <li><b>고농도 스냅</b>: 마지막 구간이 잘 안 잡힐 때 사용하되, 과하면 고농도 영역이 과대평가될 수 있습니다.</li>
  <li><b>프리셋 확장</b>: CSV(value,r,g,b)로 프리셋을 가져오면 다른 원소도 쉽게 추가할 수 있습니다.</li>
</ul>
"""
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            show_help_dialog(parent=self, title="GeoChem 도움말", html=html, plugin_dir=plugin_dir, tool_id="geochem")
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:921 (_on_help)", _exc)

    def _on_preset_changed(self):
        try:
            key = str(self.cmbPreset.currentData() or "")
            p = PRESETS.get(key)
            if p:
                self.txtUnit.setText(p.unit or "")
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:930 (_on_preset_changed)", _exc)

    def _import_preset_from_csv(self):
        try:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "CSV 프리셋 불러오기",
                "",
                "CSV Files (*.csv);;All Files (*.*)",
            )
        except Exception:
            path = ""
        if not path:
            return

        try:
            csv_result = _legend_points_from_csv(path)
        except LegendCsvError as e:
            # Out-of-range, mis-columned or single-colour files are rejected
            # outright: clamping them used to yield an all-black legend that
            # sent every map pixel to the legend maximum.
            push_message(self.iface, "오류", str(e), level=2, duration=10)
            return
        except Exception as e:
            push_message(self.iface, "오류", f"CSV를 읽을 수 없습니다: {e}", level=2, duration=7)
            return
        points = list(csv_result.points)
        for note in csv_result.notes:
            log_message(f"GeoChem: CSV 프리셋 {os.path.basename(path)}: {note}", level=Qgis.MessageLevel.Info)
        if csv_result.scaled_from_unit:
            push_message(self.iface, "프리셋", "CSV의 RGB가 0~1 범위라 255배로 환산했습니다.", level=1, duration=7)
        if csv_result.skipped_rows:
            rows_txt = ", ".join(str(r) for r in csv_result.skipped_rows[:12])
            push_message(
                self.iface,
                "프리셋",
                f"CSV에서 {len(csv_result.skipped_rows)}행을 건너뛰었습니다(행: {rows_txt}).",
                level=1,
                duration=9,
            )

        base_label = os.path.splitext(os.path.basename(path))[0]
        try:
            label, ok = QtWidgets.QInputDialog.getText(self, "프리셋 이름", "프리셋 표시 이름", text=base_label)
        except Exception:
            label, ok = (base_label, True)
        label = (label or "").strip()
        if not ok or not label:
            return

        try:
            unit, ok2 = QtWidgets.QInputDialog.getText(self, "단위", "표시용 단위(예: ppm, %, wt%). 비워도 됩니다.", text="")
        except Exception:
            unit, ok2 = ("", True)
        if not ok2:
            return
        unit = (unit or "").strip()

        key = _safe_custom_preset_key(label)
        preset = GeoChemPreset(key=key, label=label, unit=unit, points=points)
        PRESETS[key] = preset
        try:
            self.cmbPreset.addItem(preset.label, preset.key)
            self.cmbPreset.setCurrentIndex(self.cmbPreset.count() - 1)
            self.txtUnit.setText(preset.unit or "")
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:979 (_import_preset_from_csv)", _exc)
        try:
            push_message(self.iface, "프리셋", f"사용자 프리셋을 추가했습니다: {preset.label}", level=0, duration=5)
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:983 (_import_preset_from_csv)", _exc)

    def _import_preset_from_legend_image(self):
        try:
            img_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "범례 이미지 선택",
                "",
                "Image Files (*.png *.jpg *.jpeg *.bmp);;All Files (*.*)",
            )
        except Exception:
            img_path = ""
        if not img_path:
            return

        base_label = os.path.splitext(os.path.basename(img_path))[0]
        try:
            label, ok = QtWidgets.QInputDialog.getText(self, "프리셋 이름", "프리셋 표시 이름", text=base_label)
        except Exception:
            label, ok = (base_label, True)
        label = (label or "").strip()
        if not ok or not label:
            return

        try:
            unit, ok2 = QtWidgets.QInputDialog.getText(self, "단위", "표시용 단위(예: ppm, %, wt%). 비워도 됩니다.", text="")
        except Exception:
            unit, ok2 = ("", True)
        if not ok2:
            return
        unit = (unit or "").strip()

        try:
            values_txt, ok3 = QtWidgets.QInputDialog.getText(
                self,
                "값 목록",
                "값 목록(쉼표로 구분, 예: 0, 3.1, 3.5, 3.9, ...)\n"
                "※ 이미지의 색상바가 위/아래로 변하는 '연속 범례'라고 가정합니다.",
                text="",
            )
        except Exception:
            values_txt, ok3 = ("", False)
        if not ok3:
            return
        vals = _parse_float_list(values_txt)
        vals = sorted(set([float(v) for v in vals]))
        if len(vals) < 2:
            push_message(self.iface, "오류", "값 목록은 2개 이상이어야 합니다.", level=2, duration=7)
            return

        try:
            direction, ok4 = QtWidgets.QInputDialog.getItem(
                self,
                "샘플링 방향",
                "범례 이미지에서 낮은 값(최소값)이 위치한 곳",
                ["낮은 값이 아래(권장)", "낮은 값이 위"],
                0,
                False,
            )
        except Exception:
            direction, ok4 = ("낮은 값이 아래(권장)", True)
        if not ok4:
            return
        low_at_bottom = str(direction).startswith("낮은 값이 아래")

        try:
            x_ratio, ok5 = QtWidgets.QInputDialog.getDouble(
                self,
                "샘플링 X 위치",
                "색상바 샘플 x 비율 (0~1, 0.5=가운데)",
                0.5,
                0.0,
                1.0,
                2,
            )
        except Exception:
            x_ratio, ok5 = (0.5, True)
        if not ok5:
            return

        img = QImage(str(img_path))
        if img.isNull():
            push_message(self.iface, "오류", "이미지를 열 수 없습니다.", level=2, duration=7)
            return
        w = int(img.width() or 0)
        h = int(img.height() or 0)
        if w <= 1 or h <= 1:
            push_message(self.iface, "오류", "이미지 크기가 올바르지 않습니다.", level=2, duration=7)
            return

        x = int(round(float(x_ratio) * float(w - 1)))
        n = len(vals)
        # Sample each anchor at the centre of its band (row (i+0.5)/n*h), never
        # at row 0 / h-1: those are the margin or frame of any real legend
        # graphic, and reading them made white (or the border colour) the
        # legend minimum and maximum.
        rows = _legend_sample_rows(n, h, low_at_bottom=low_at_bottom)
        points: List[LegendPoint] = []
        alphas: List[int] = []
        for v, y in zip(vals, rows):
            rgb = _sample_qimage_rgb(img, x, y, radius=1)
            alphas.append(_sample_qimage_alpha(img, x, y))
            points.append(LegendPoint(float(v), rgb))
        try:
            log_message(
                f"GeoChem: legend image {w}x{h} sampled at x={x} rows={rows} -> "
                + ", ".join(f"{p.value:g}:{p.rgb}" for p in points),
                level=Qgis.MessageLevel.Info,
            )
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._import_preset_from_legend_image", _exc)

        if len(points) < 2:
            push_message(self.iface, "오류", "범례 포인트를 만들 수 없습니다.", level=2, duration=7)
            return
        problem = _sampled_legend_problem(points, alphas)
        if problem:
            push_message(
                self.iface,
                "오류",
                _LEGEND_SAMPLE_PROBLEMS.get(problem, "범례 샘플이 올바르지 않습니다.")
                + " 이미지를 색상바만 남기고 잘라 다시 시도하세요.",
                level=2,
                duration=10,
            )
            return

        key = _safe_custom_preset_key(label)
        preset = GeoChemPreset(key=key, label=label, unit=unit, points=points)
        PRESETS[key] = preset
        try:
            self.cmbPreset.addItem(preset.label, preset.key)
            self.cmbPreset.setCurrentIndex(self.cmbPreset.count() - 1)
            self.txtUnit.setText(preset.unit or "")
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:1100 (_import_preset_from_legend_image)", _exc)
        try:
            push_message(self.iface, "프리셋", f"범례 이미지에서 프리셋을 추가했습니다: {preset.label}", level=0, duration=5)
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:1104 (_import_preset_from_legend_image)", _exc)

    def _on_add_rasters_changed(self):
        try:
            if self.chkAddRasters.isChecked():
                self.chkSaveRasters.setChecked(True)
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:1111 (_on_add_rasters_changed)", _exc)

    def _update_polygon_ui(self):
        try:
            enabled = bool(self.chkMakePolygons.isChecked())
            self.chkDissolve.setEnabled(enabled)
            self.chkDropNoData.setEnabled(enabled)
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:1119 (_update_polygon_ui)", _exc)

    def _update_zonal_ui(self):
        try:
            enabled = bool(getattr(self, "chkZonalStats", None) and self.chkZonalStats.isChecked())
            if getattr(self, "cmbZoneLayer", None):
                self.cmbZoneLayer.setEnabled(enabled)
            if getattr(self, "chkZoneSelectedOnly", None):
                self.chkZoneSelectedOnly.setEnabled(enabled)
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:1129 (_update_zonal_ui)", _exc)

    def _update_weight_ui(self):
        try:
            enabled = bool(self.chkWeightedCenter.isChecked())
            self.cmbCenterMethod.setEnabled(enabled)
            self.cmbWeightRule.setEnabled(enabled)
            rule = str(self.cmbWeightRule.currentData() or "")
            self.spinWeightPower.setEnabled(enabled and rule == "power")
            self.spinWeightThreshold.setEnabled(enabled and rule in ("threshold", "binary"))
            self.spinWeightTopPct.setEnabled(enabled and rule == "top_pct")
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._update_weight_ui", _exc)

    def _tmp_dir_in_use(self, tmp_dir: str) -> bool:
        """Return True if any current project layer source points into tmp_dir."""
        if not tmp_dir:
            return False

        try:
            tmp_abs = os.path.abspath(tmp_dir)
        except Exception:
            tmp_abs = str(tmp_dir)

        try:
            tmp_norm = os.path.normcase(tmp_abs).replace("\\", "/")
            if not tmp_norm.endswith("/"):
                tmp_norm += "/"
        except Exception:
            tmp_norm = str(tmp_abs).replace("\\", "/")
            if tmp_norm and not tmp_norm.endswith("/"):
                tmp_norm += "/"

        try:
            project = QgsProject.instance()
            layers = list(project.mapLayers().values())
        except Exception:
            return False

        for layer in layers:
            _skip_1170 = False
            try:
                src = str(layer.source() or "")
            except Exception as _exc:
                log_swallowed("tools/geochem_polygonize_dialog.py:1172 (_tmp_dir_in_use)", _exc)
                _skip_1170 = True
            if _skip_1170:
                continue
            if not src:
                continue

            # Some providers use complex URIs; substring matching is the most robust check.
            try:
                src_norm = os.path.normcase(src).replace("\\", "/")
                if tmp_norm and tmp_norm in src_norm:
                    return True
            except Exception as _exc:
                log_swallowed("tools/geochem_polygonize_dialog.py:1182 (_tmp_dir_in_use)", _exc)

            # Typical "path|layername=..." sources.
            _skip_1186 = False
            try:
                path = (src.split("|", 1)[0] or "").strip()
                if not path:
                    continue
                path_norm = os.path.normcase(os.path.abspath(path)).replace("\\", "/")
                if tmp_norm and path_norm.startswith(tmp_norm):
                    return True
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._tmp_dir_in_use", _exc)
                log_swallowed("tools/geochem_polygonize_dialog.py:1193 (_tmp_dir_in_use)", _exc)
                _skip_1186 = True
            if _skip_1186:
                continue

        return False

    def _cleanup_tmp(self):
        tmp_dir = self._tmp_dir
        if not tmp_dir or not os.path.isdir(tmp_dir):
            self._tmp_dir = None
            return

        try:
            if self._tmp_dir_in_use(tmp_dir):
                log_message(f"GeoChem: tmp dir still in use, skip cleanup: {tmp_dir}", level=Qgis.MessageLevel.Warning)
                return
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:1209 (_cleanup_tmp)", _exc)

        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._cleanup_tmp", _exc)
        self._tmp_dir = None

    def reject(self):
        self._cleanup_tmp()
        super().reject()

    def closeEvent(self, event):
        self._cleanup_tmp()
        event.accept()

    def run(self):
        try:
            ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:1229 (run)", _exc)

        raster = self.cmbRaster.currentLayer()
        aoi = self.cmbAoi.currentLayer()
        if raster is None or not isinstance(raster, QgsRasterLayer):
            push_message(self.iface, "오류", "RGB 래스터(WMS) 레이어를 선택해주세요.", level=2, duration=7)
            restore_ui_focus(self)
            return
        if aoi is None or not isinstance(aoi, QgsVectorLayer):
            push_message(self.iface, "오류", "조사지역 폴리곤 레이어를 선택해주세요.", level=2, duration=7)
            restore_ui_focus(self)
            return
        if aoi.geometryType() != Qgis.GeometryType.Polygon:
            push_message(self.iface, "오류", "조사지역은 폴리곤 레이어여야 합니다.", level=2, duration=7)
            restore_ui_focus(self)
            return

        key = str(self.cmbPreset.currentData() or "")
        preset = PRESETS.get(key)
        if preset is None:
            push_message(self.iface, "오류", "범례 프리셋이 올바르지 않습니다.", level=2, duration=7)
            restore_ui_focus(self)
            return

        unit = (self.txtUnit.text() or "").strip()
        do_mask_aoi = bool(getattr(self, "chkMaskAoi", None) and self.chkMaskAoi.isChecked())
        do_low_as_nodata = bool(getattr(self, "chkLowAsNoData", None) and self.chkLowAsNoData.isChecked())
        do_make_polygons = bool(getattr(self, "chkMakePolygons", None) and self.chkMakePolygons.isChecked())
        do_make_class_raster = bool(getattr(self, "chkMakeClassRaster", None) and self.chkMakeClassRaster.isChecked())
        do_dissolve = bool(self.chkDissolve.isChecked()) and do_make_polygons
        do_fix_max = bool(self.chkFixMax.isChecked())
        do_snap_max = bool(getattr(self, "chkSnapMax", None) and self.chkSnapMax.isChecked())
        snap_t = float(getattr(self, "spinSnapT", None).value()) if getattr(self, "spinSnapT", None) else 0.0
        do_inpaint = bool(self.chkInpaint.isChecked())
        fill_dist = int(self.spinFillDist.value())
        do_drop_nodata = bool(getattr(self, "chkDropNoData", None) and self.chkDropNoData.isChecked()) and do_make_polygons
        do_save_rasters = bool(getattr(self, "chkSaveRasters", None) and self.chkSaveRasters.isChecked())
        do_add_rasters = bool(getattr(self, "chkAddRasters", None) and self.chkAddRasters.isChecked())
        do_zonal_stats = bool(getattr(self, "chkZonalStats", None) and self.chkZonalStats.isChecked())
        zone_layer = self.cmbZoneLayer.currentLayer() if do_zonal_stats and getattr(self, "cmbZoneLayer", None) else None
        zone_selected_only = bool(getattr(self, "chkZoneSelectedOnly", None) and self.chkZoneSelectedOnly.isChecked())
        do_weight_center = bool(getattr(self, "chkWeightedCenter", None) and self.chkWeightedCenter.isChecked())
        center_method = (
            str(getattr(self, "cmbCenterMethod", None).currentData() or "weighted_mean")
            if getattr(self, "cmbCenterMethod", None)
            else "weighted_mean"
        )
        weight_rule = str(getattr(self, "cmbWeightRule", None).currentData() or "value") if getattr(self, "cmbWeightRule", None) else "value"
        weight_power = int(getattr(self, "spinWeightPower", None).value()) if getattr(self, "spinWeightPower", None) else 2
        weight_threshold = float(getattr(self, "spinWeightThreshold", None).value()) if getattr(self, "spinWeightThreshold", None) else 0.0
        weight_top_pct = float(getattr(self, "spinWeightTopPct", None).value()) if getattr(self, "spinWeightTopPct", None) else 10.0
        if do_add_rasters:
            do_save_rasters = True

        if do_zonal_stats:
            if zone_layer is None or not isinstance(zone_layer, QgsVectorLayer):
                push_message(self.iface, "오류", "구역 통계용 폴리곤 레이어를 선택해주세요.", level=2, duration=7)
                restore_ui_focus(self)
                return
            if zone_layer.geometryType() != Qgis.GeometryType.Polygon:
                push_message(self.iface, "오류", "구역 통계 레이어는 폴리곤 레이어여야 합니다.", level=2, duration=7)
                restore_ui_focus(self)
                return

        # Survey area extent (bounding rectangle), optionally buffered.
        aoi_selected_only = bool(self.chkSelectedOnly.isChecked())
        aoi_selection_used = False
        try:
            if aoi_selected_only and aoi.selectedFeatureCount() > 0:
                feats = list(aoi.selectedFeatures())
                aoi_selection_used = True
            else:
                feats = list(aoi.getFeatures())
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog.run", _exc)
            feats = []
        if aoi_selected_only and not aoi_selection_used and feats:
            # The tooltip promises this fallback; say it out loud so a forgotten
            # selection cannot silently widen the study area.
            push_message(
                self.iface,
                "경고",
                f"조사지역 레이어에 선택된 피처가 없어 전체 {len(feats)}개 피처로 경계를 계산합니다.",
                level=1,
                duration=7,
            )
            log_message(f"GeoChem: AOI selected-only requested but no selection; using all {len(feats)} features", level=Qgis.MessageLevel.Warning)
        if not feats:
            push_message(self.iface, "오류", "조사지역 피처가 없습니다. (선택 또는 레이어 내용 확인)", level=2, duration=7)
            restore_ui_focus(self)
            return

        aoi_geom = None
        for ft in feats:
            g = ft.geometry()
            if g is None or g.isEmpty():
                continue
            aoi_geom = g if aoi_geom is None else aoi_geom.combine(g)
        if aoi_geom is None or aoi_geom.isEmpty():
            push_message(self.iface, "오류", "조사지역 지오메트리를 만들 수 없습니다.", level=2, duration=7)
            restore_ui_focus(self)
            return

        extent_aoi = aoi_geom.boundingBox()
        buf = float(self.spinExtentBuffer.value() or 0.0)
        if buf > 0:
            # The spinbox is meters, but grow() works in the AOI layer's CRS
            # units — on a geographic AOI a "500 m" buffer would become 500
            # DEGREES (a world-spanning export). Convert meters → degrees.
            grow_units = buf
            try:
                if aoi.crs().isGeographic():
                    grow_units = buf / 111320.0
            except Exception as _exc:
                log_swallowed("tools/geochem_polygonize_dialog.py:1325 (run)", _exc)
            extent_aoi.grow(grow_units)

        # Keep a canvas-compatible extent for zooming (destination CRS).
        extent_canvas = QgsRectangle(extent_aoi)
        extent_canvas_ok = True
        try:
            dest_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            if dest_crs and aoi.crs() != dest_crs:
                ct_canvas = QgsCoordinateTransform(aoi.crs(), dest_crs, QgsProject.instance())
                extent_canvas = ct_canvas.transformBoundingBox(extent_canvas)
        except Exception as _exc:
            extent_canvas_ok = False
            log_swallowed("tools/geochem_polygonize_dialog.py:1336 (run)", _exc)

        # Transform survey-area extent to raster CRS for export.
        extent_export = QgsRectangle(extent_aoi)
        aoi_geom_raster = QgsGeometry(aoi_geom)
        try:
            if aoi.crs() != raster.crs():
                ct = QgsCoordinateTransform(aoi.crs(), raster.crs(), QgsProject.instance())
                extent_export = ct.transformBoundingBox(extent_export)
                # QgsGeometry.transform reports failure via its RETURN CODE
                # (0=success), not an exception. A failed reprojection left the
                # AOI in the wrong CRS and the mask then blanked the whole
                # output to NoData. Disable masking instead.
                try:
                    rc = aoi_geom_raster.transform(ct)
                    if rc != 0:
                        log_message(
                            f"GeoChem: AOI reprojection failed (code {rc}) — AOI 마스킹을 건너뜁니다.",
                            level=Qgis.MessageLevel.Warning,
                        )
                        aoi_geom_raster = None
                except Exception:
                    aoi_geom_raster = None
        except Exception as e:
            # Transform failed outright: do NOT restore the untransformed AOI
            # (it would mask in the wrong CRS and blank the output). Skip masking.
            log_message(f"GeoChem: extent transform failed: {e} — AOI 마스킹을 건너뜁니다.", level=Qgis.MessageLevel.Warning)
            aoi_geom_raster = None

        if extent_export.isEmpty() or extent_export.width() <= 0 or extent_export.height() <= 0:
            push_message(self.iface, "오류", "조사지역 경계(사각형)가 비어있습니다.", level=2, duration=7)
            restore_ui_focus(self)
            return

        # Choose pixel size: 0 = use current canvas resolution.
        px_input = float(self.spinPixelSize.value() or 0.0)
        px = px_input
        px_source = "user"
        if px <= 0:
            px = 0.0
            px_source = ""
            try:
                # mapUnitsPerPixel is in destination CRS units. Use it directly
                # when the raster CRS matches; otherwise convert it into the
                # raster CRS at the AOI. The old silent fallback to extent/1024
                # gave ~9x fewer samples for the usual EPSG:5186 project /
                # EPSG:3857 WMS pairing, and different class areas after a
                # project CRS switch, while the tooltip promised the canvas.
                canvas = self.iface.mapCanvas()
                dest_crs = canvas.mapSettings().destinationCrs()
                if dest_crs and dest_crs == raster.crs():
                    px = float(canvas.mapUnitsPerPixel())
                    px_source = "canvas"
                elif dest_crs and dest_crs.isValid() and raster.crs().isValid():
                    centre = extent_canvas.center() if extent_canvas_ok else canvas.extent().center()
                    px = self._canvas_pixel_size_in_raster_crs(
                        dest_crs=dest_crs, raster_crs=raster.crs(), centre_dest=centre
                    )
                    if px > 0:
                        px_source = "reprojected_canvas"
                        log_message(
                            f"GeoChem: canvas {float(canvas.mapUnitsPerPixel()):g} ({dest_crs.authid()} units/px) "
                            f"-> {px:g} ({raster.crs().authid()} units/px) at the AOI",
                            level=Qgis.MessageLevel.Info,
                        )
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog.run (pixel size)", _exc)
                px = 0.0
        if not (px > 0) or not math.isfinite(px):
            px = max(extent_export.width(), extent_export.height()) / 1024.0
            px_source = "fallback_1024"
            push_message(
                self.iface,
                "경고",
                f"캔버스 해상도를 래스터 CRS로 환산하지 못해 픽셀 크기 {px:g}(조사지역 긴 변/1024)을 사용합니다. "
                "해상도를 고정하려면 픽셀 크기를 직접 입력하세요.",
                level=1,
                duration=9,
            )
        px = max(px, 1e-9)
        px_requested = px

        width = max(1, int(math.ceil(extent_export.width() / px)))
        height = max(1, int(math.ceil(extent_export.height() / px)))

        # Guardrail: prevent accidental huge rasters (memory explosion during numpy processing).
        MAX_PIXELS = 12_000_000
        total_px = int(width) * int(height)
        if total_px > MAX_PIXELS:
            if px_input > 0:
                push_message(
                    self.iface,
                    "오류",
                    f"요청 해상도가 너무 큽니다: {width}x{height} ({total_px:,} px). 픽셀 크기를 키우거나 조사지역 범위를 줄여주세요.",
                    level=2,
                    duration=10,
                )
                restore_ui_focus(self)
                return

            scale = math.sqrt(float(total_px) / float(MAX_PIXELS))
            px *= max(scale, 1.0)
            width = max(1, int(math.ceil(extent_export.width() / px)))
            height = max(1, int(math.ceil(extent_export.height() / px)))
            total_px = int(width) * int(height)
            px_source = "capped"
            log_message(
                f"GeoChem: auto-adjusted px to {px:g} to cap size => {width}x{height} ({total_px:,} px)",
                level=Qgis.MessageLevel.Warning,
            )
            push_message(
                self.iface,
                "경고",
                f"픽셀 수 상한({MAX_PIXELS:,})에 걸려 픽셀 크기를 {px_requested:g}에서 {px:g}(으)로 키웠습니다"
                f" ({width}x{height}). 구간 면적/구역 통계는 이 해상도 기준입니다.",
                level=1,
                duration=9,
            )

        log_message(
            f"GeoChem: export extent {extent_export.toString()} px={px:g} ({px_source}) => {width}x{height}",
            level=Qgis.MessageLevel.Info,
        )
        # Recorded in the value/class raster metadata (params_json) so a saved
        # GeoTIFF can be traced back to the resolution and corrections used.
        self._last_geochem_run_params = {
            "pixel_size": float(px),
            "pixel_size_source": str(px_source),
            "raster_size_px": f"{int(width)}x{int(height)}",
        }
        if px_source == "capped":
            self._last_geochem_run_params["pixel_size_requested"] = float(px_requested)
        self._last_geochem_zonal_meta = {}

        self._cleanup_tmp()
        self._tmp_dir = tempfile.mkdtemp(prefix="ArchToolkit_GeoChem_")
        run_id = uuid.uuid4().hex[:6]
        rgb_path = os.path.join(self._tmp_dir, f"wms_rgb_{run_id}.tif")
        val_path = os.path.join(self._tmp_dir, f"{preset.key}_value_{run_id}.tif")
        cls_path = os.path.join(self._tmp_dir, f"{preset.key}_class_{run_id}.tif")
        log_message(f"GeoChem: tmp={self._tmp_dir}", level=Qgis.MessageLevel.Info)
        log_message(f"GeoChem: out rgb={rgb_path}", level=Qgis.MessageLevel.Info)
        log_message(f"GeoChem: out val={val_path}", level=Qgis.MessageLevel.Info)
        log_message(f"GeoChem: out cls={cls_path}", level=Qgis.MessageLevel.Info)

        try:
            # 1) Export WMS RGB to GeoTIFF within survey-area extent (rectangular).
            ok = self._export_raster_to_geotiff(
                raster=raster, out_path=rgb_path, extent=extent_export, width=width, height=height
            )
            if not ok:
                push_message(self.iface, "오류", "WMS 래스터를 GeoTIFF로 저장하지 못했습니다.", level=2, duration=9)
                restore_ui_focus(self)
                return

            # 2) RGB -> value raster
            log_message("GeoChem: reading exported RGB…", level=Qgis.MessageLevel.Info)
            ds = gdal.Open(rgb_path)
            if ds is None:
                raise RuntimeError("Cannot open exported RGB GeoTIFF")
            band_count = int(ds.RasterCount or 0)
            if band_count < 3:
                raise RuntimeError("RGB 래스터는 최소 3밴드(R,G,B)가 필요합니다.")
            gt = None
            proj_wkt = ""
            try:
                gt = ds.GetGeoTransform()
                proj_wkt = str(ds.GetProjection() or "")
            except Exception:
                gt = None
                proj_wkt = ""
            r = ds.GetRasterBand(1).ReadAsArray()
            g = ds.GetRasterBand(2).ReadAsArray()
            b = ds.GetRasterBand(3).ReadAsArray()
            a = None
            if band_count >= 4:
                try:
                    a = ds.GetRasterBand(4).ReadAsArray()
                except Exception:
                    a = None
            try:
                log_message(
                    f"GeoChem: exported bands={band_count} shape={getattr(r, 'shape', None)} dtype={getattr(r, 'dtype', None)}",
                    level=Qgis.MessageLevel.Info,
                )
            except Exception as _exc:
                log_swallowed("tools/geochem_polygonize_dialog.py:1469 (run)", _exc)

            log_message("GeoChem: RGB -> value mapping…", level=Qgis.MessageLevel.Info)
            if do_snap_max:
                log_message(f"GeoChem: high-end snap enabled (last segment t>{snap_t:g} -> max)", level=Qgis.MessageLevel.Info)
            out, residual = _interp_rgb_to_value(
                r=r,
                g=g,
                b=b,
                points=preset.points,
                snap_last_t=snap_t if do_snap_max else None,
                max_distance=_RGB_MATCH_TOLERANCE,
                return_residual=True,
            )
            nodata_val = np.float32(-9999.0)
            # Off-legend colours (black lines, label text, anything not on the
            # ramp) used to be forced onto the nearest segment - and the dark
            # corner of RGB space is nearest the maximum of most presets. They
            # are NoData now; with inpainting on they get filled like the
            # linework mask, otherwise they stay NoData. The count is reported
            # so a map full of rejected pixels does not pass silently.
            try:
                rejected = ~np.isfinite(out)
                n_rej = int(np.count_nonzero(rejected))
                if n_rej:
                    out = out.astype(np.float32, copy=False)
                    out[rejected] = nodata_val
                    pct_rej = n_rej / max(1, int(out.size)) * 100.0
                    log_message(
                        f"GeoChem: {n_rej:,}/{int(out.size):,} 픽셀({pct_rej:.2f}%)이 범례 색에서 RGB 거리 "
                        f"{_RGB_MATCH_TOLERANCE:g} 이상 떨어져 NoData 처리 (검정 선·문자·범례 밖 색)",
                        level=Qgis.MessageLevel.Warning if pct_rej >= 5.0 else Qgis.MessageLevel.Info,
                    )
                    if pct_rej >= 5.0:
                        push_message(
                            self.iface, "GeoChem",
                            f"범례와 맞지 않는 색 {pct_rej:.1f}%를 NoData 처리했습니다. 범례 프리셋이 이 WMS와 맞는지 확인하세요.",
                            level=1, duration=9,
                        )
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog.run (legend tolerance)", _exc)

            # Transparent pixels (if alpha band exists) -> NoData
            transparent = None
            if a is not None:
                try:
                    transparent = a.astype(np.int16, copy=False) <= 0
                    out = out.astype(np.float32, copy=False)
                    out[transparent] = nodata_val
                    try:
                        total = int(transparent.size)
                        tr = int(np.count_nonzero(transparent))
                        log_message(
                            f"GeoChem: alpha transparent {tr:,}/{total:,} ({(tr / total * 100.0):.2f}%)",
                            level=Qgis.MessageLevel.Info,
                        )
                    except Exception as _exc:
                        log_swallowed("geochem_polygonize_dialog.run", _exc)
                except Exception:
                    transparent = None

            low_nodata_mask = None
            if do_low_as_nodata:
                try:
                    br = _points_to_breaks(preset.points)
                    min_valid = float(br[1]) if len(br) >= 2 else None
                    if min_valid is not None:
                        low_nodata_mask = np.isfinite(out) & (out != nodata_val) & (out < np.float32(min_valid))
                        n_low = int(np.count_nonzero(low_nodata_mask))
                        out = out.astype(np.float32, copy=False)
                        out[low_nodata_mask] = nodata_val
                        log_message(
                            f"GeoChem: treat <{min_valid:g} as nodata {n_low:,} px (legend low-end)",
                            level=Qgis.MessageLevel.Info,
                        )
                except Exception:
                    low_nodata_mask = None

            try:
                total = int(out.size)
                nd = int(np.count_nonzero(out == nodata_val))
                log_message(
                    f"GeoChem: nodata pixels {nd:,}/{total:,} ({(nd / total * 100.0):.2f}%)",
                    level=Qgis.MessageLevel.Info,
                )
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog.run", _exc)

            # Optional black line masking + fill. The fill mask is kept: the
            # filled pixels are invented (nearest-neighbour IDW), yet they are
            # counted as data by every statistic downstream, so their share is
            # reported per run (metadata) and per zone (fill_pct).
            fill_mask = None
            if do_inpaint:
                log_message("GeoChem: masking dark linework…", level=Qgis.MessageLevel.Info)
                try:
                    mask = _mask_black_lines(r, g, b)
                    if transparent is not None:
                        mask &= ~transparent
                    try:
                        m = int(np.count_nonzero(mask))
                        t = int(mask.size)
                        log_message(
                            f"GeoChem: linework mask {m:,}/{t:,} ({(m / t * 100.0):.2f}%)",
                            level=Qgis.MessageLevel.Info,
                        )
                    except Exception as _exc:
                        log_swallowed("geochem_polygonize_dialog.run", _exc)
                    out = out.astype(np.float32, copy=False)
                    out[mask] = np.nan
                except Exception as _exc:
                    log_swallowed("geochem_polygonize_dialog.run", _exc)
                pre_nodata = None
                try:
                    pre_nodata = (~np.isfinite(out)) | (out == nodata_val)
                except Exception as _exc:
                    log_swallowed("geochem_polygonize_dialog.run (fill mask)", _exc)
                log_message("GeoChem: filling masked pixels…", level=Qgis.MessageLevel.Info)
                out = _gdal_fill_nodata_nearestish(arr=out, nodata=float(nodata_val), max_search_dist_px=fill_dist)
                if transparent is not None:
                    try:
                        out = out.astype(np.float32, copy=False)
                        out[transparent] = nodata_val
                    except Exception as _exc:
                        log_swallowed("geochem_polygonize_dialog.run", _exc)
                if low_nodata_mask is not None:
                    try:
                        out = out.astype(np.float32, copy=False)
                        out[low_nodata_mask] = nodata_val
                    except Exception as _exc:
                        log_swallowed("geochem_polygonize_dialog.run", _exc)
                if pre_nodata is not None:
                    try:
                        fill_mask = pre_nodata & np.isfinite(out) & (out != nodata_val)
                    except Exception as _exc:
                        log_swallowed("geochem_polygonize_dialog.run (fill mask)", _exc)
                        fill_mask = None
                try:
                    total = int(out.size)
                    nd = int(np.count_nonzero(out == nodata_val))
                    log_message(
                        f"GeoChem: nodata pixels after fill {nd:,}/{total:,} ({(nd / total * 100.0):.2f}%)",
                        level=Qgis.MessageLevel.Info,
                    )
                except Exception as _exc:
                    log_swallowed("geochem_polygonize_dialog.run", _exc)

            # Optional AOI mask: keep only pixels inside the AOI polygon (outside -> NoData).
            if do_mask_aoi:
                try:
                    if gt is not None and aoi_geom_raster is not None and not aoi_geom_raster.isEmpty():
                        mask_aoi = _gdal_rasterize_wkt_mask(
                            geom_wkt=aoi_geom_raster.asWkt(),
                            xsize=int(ds.RasterXSize),
                            ysize=int(ds.RasterYSize),
                            geotransform=gt,
                            projection_wkt=proj_wkt,
                        )
                    else:
                        mask_aoi = None
                    if mask_aoi is not None:
                        out = out.astype(np.float32, copy=False)
                        out[~mask_aoi] = nodata_val
                        try:
                            total = int(mask_aoi.size)
                            inside = int(np.count_nonzero(mask_aoi))
                            log_message(
                                f"GeoChem: AOI mask inside {inside:,}/{total:,} ({(inside / total * 100.0):.2f}%)",
                                level=Qgis.MessageLevel.Info,
                            )
                        except Exception as _exc:
                            log_swallowed("geochem_polygonize_dialog.run", _exc)
                        try:
                            total2 = int(out.size)
                            nd2 = int(np.count_nonzero(out == nodata_val))
                            log_message(
                                f"GeoChem: nodata pixels after AOI mask {nd2:,}/{total2:,} ({(nd2 / total2 * 100.0):.2f}%)",
                                level=Qgis.MessageLevel.Info,
                            )
                        except Exception as _exc:
                            log_swallowed("geochem_polygonize_dialog.run", _exc)
                except Exception as _exc:
                    log_swallowed("geochem_polygonize_dialog.run", _exc)

            # Inpaint accounting, after the AOI mask so only counted pixels are
            # in the percentage. Filled pixels are not measurements.
            inpaint_meta = {"inpaint": bool(do_inpaint), "inpaint_distance_px": int(fill_dist)}
            if do_inpaint:
                try:
                    if fill_mask is not None:
                        fill_mask &= np.isfinite(out) & (out != nodata_val)
                        n_fill = int(np.count_nonzero(fill_mask))
                        n_valid = int(np.count_nonzero(np.isfinite(out) & (out != nodata_val)))
                        pct_fill = (n_fill / n_valid * 100.0) if n_valid > 0 else 0.0
                        inpaint_meta["inpaint_fill_px"] = n_fill
                        inpaint_meta["inpaint_fill_pct"] = round(pct_fill, 3)
                        log_message(
                            f"GeoChem: inpaint filled {n_fill:,}/{n_valid:,} valid px ({pct_fill:.2f}%) - "
                            "이 픽셀은 측정값이 아니라 주변 보간값이며 이후 통계에 그대로 포함됩니다",
                            level=Qgis.MessageLevel.Warning if pct_fill >= 5.0 else Qgis.MessageLevel.Info,
                        )
                    else:
                        log_message("GeoChem: inpaint fill mask unavailable; filled share not recorded", level=Qgis.MessageLevel.Warning)
                except Exception as _exc:
                    log_swallowed("geochem_polygonize_dialog.run (inpaint accounting)", _exc)
            self._last_geochem_run_params.update(inpaint_meta)

            # Optional max correction: stretch every value so the clip's maximum
            # becomes the legend maximum. Computed AFTER the AOI mask so pixels
            # the user excluded (corners of the bounding rectangle) cannot drive
            # the factor, and recorded in the layer metadata (fix_max), because
            # when the clip genuinely lacks high values this invents them.
            fix_max_meta = {"applied": False}
            if do_fix_max:
                try:
                    br = _points_to_breaks(preset.points)
                    target_max = float(br[-1])
                    fix_max_meta["target_max"] = target_max
                    out = out.astype(np.float32, copy=False)
                    valid = np.isfinite(out) & (out != nodata_val) & (out >= 0)
                    if np.any(valid):
                        cur_max = float(np.nanmax(out[valid]))
                        fix_max_meta["cur_max"] = cur_max
                        if 0 < cur_max < target_max:
                            factor = target_max / cur_max
                            fix_max_meta["applied"] = True
                            fix_max_meta["factor"] = round(factor, 6)
                            log_message(
                                f"GeoChem: max correction {cur_max:g} -> {target_max:g} (x{factor:.3f}) - "
                                "클립 최댓값을 범례 최댓값으로 늘림 (모든 값에 적용)",
                                level=Qgis.MessageLevel.Warning,
                            )
                            push_message(
                                self.iface,
                                "GeoChem",
                                f"최댓값 보정 적용: 모든 값에 x{factor:.2f} (클립 최댓값 {cur_max:g} -> 범례 최댓값 {target_max:g}). "
                                "클립에 고농도 구간이 원래 없다면 결과가 실제보다 큽니다.",
                                level=1,
                                duration=9,
                            )
                            out[valid] = (out[valid] / cur_max) * target_max
                        else:
                            log_message(f"GeoChem: max correction not needed (cur_max={cur_max:g}, legend max={target_max:g})", level=Qgis.MessageLevel.Info)
                except Exception as _exc:
                    log_swallowed("geochem_polygonize_dialog.run", _exc)
            self._last_geochem_run_params["fix_max"] = fix_max_meta

            # Ensure explicit nodata
            out = out.astype(np.float32, copy=False)
            out[~np.isfinite(out)] = nodata_val

            # Write value raster
            log_message("GeoChem: writing value raster…", level=Qgis.MessageLevel.Info)
            self._write_single_band_geotiff(ds, out_path=val_path, data=out, nodata=float(nodata_val))

            try:
                valid = np.isfinite(out) & (out != nodata_val)
                if np.any(valid):
                    vmin = float(np.nanmin(out[valid]))
                    vmax = float(np.nanmax(out[valid]))
                    p99 = float(np.nanpercentile(out[valid], 99.0))
                    log_message(f"GeoChem: value stats min={vmin:g} max={vmax:g} p99={p99:g}", level=Qgis.MessageLevel.Info)
                else:
                    log_message("GeoChem: value stats (no valid pixels)", level=Qgis.MessageLevel.Warning)
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog.run", _exc)

            zone_stats_layer = None
            need_class = bool(do_make_polygons or do_make_class_raster or do_zonal_stats)
            if need_class:
                # 3) Class raster (optional output, required internally for polygonize)
                breaks = _points_to_breaks(preset.points)
                log_message(f"GeoChem: classify to {len(breaks) - 1} bins…", level=Qgis.MessageLevel.Info)
                cls = _classify_to_bins(values=out, breaks=breaks, nodata_class=0, nodata_value=float(nodata_val))
                try:
                    flat = cls.ravel()
                    counts = np.bincount(flat.astype(np.int64, copy=False), minlength=len(breaks))
                    parts = [f"class0={int(counts[0]):,}"]
                    for i in range(1, len(breaks)):
                        v0 = float(breaks[i - 1])
                        v1 = float(breaks[i])
                        parts.append(f"class{i}({v0:g}-{v1:g})={int(counts[i]):,}")
                    log_message("GeoChem: class counts " + " | ".join(parts), level=Qgis.MessageLevel.Info)

                    # Store counts so we can write per-class pixel stats into the polygon layer.
                    pix_counts = {}
                    try:
                        for i in range(len(breaks)):  # 0..n_classes
                            pix_counts[int(i)] = int(counts[i]) if i < len(counts) else 0
                    except Exception:
                        pix_counts = {}
                    self._last_geochem_pix_counts = pix_counts
                except Exception as _exc:
                    self._last_geochem_pix_counts = {}
                    log_swallowed("tools/geochem_polygonize_dialog.py:1670 (run)", _exc)

                # Per-class mean value (useful as a representative numeric attribute on dissolved polygons).
                try:
                    valid_mean = (cls > 0) & np.isfinite(out) & (out != nodata_val)
                    if np.any(valid_mean):
                        flat_cls = cls[valid_mean].astype(np.int64, copy=False)
                        flat_out = out[valid_mean].astype(np.float64, copy=False)
                        sums = np.bincount(flat_cls, weights=flat_out, minlength=len(breaks))
                        sums2 = np.bincount(flat_cls, weights=flat_out * flat_out, minlength=len(breaks))
                        cnts = np.bincount(flat_cls, minlength=len(breaks))
                        means = {}
                        stds = {}
                        for i in range(1, len(breaks)):
                            if i < len(cnts) and cnts[i] > 0:
                                mu = float(sums[i] / cnts[i])
                                means[int(i)] = mu
                                try:
                                    var = float(sums2[i] / cnts[i]) - (mu * mu)
                                    if var < 0 and var > -1e-12:
                                        var = 0.0
                                    stds[int(i)] = float(math.sqrt(var)) if var > 0 else 0.0
                                except Exception:
                                    stds[int(i)] = 0.0
                        self._last_geochem_class_mean = means
                        self._last_geochem_class_std = stds
                        try:
                            last_cid = len(breaks) - 1
                            if int(last_cid) in means:
                                log_message(f"GeoChem: class{last_cid} mean={means[int(last_cid)]:g}", level=Qgis.MessageLevel.Info)
                        except Exception as _exc:
                            log_swallowed("geochem_polygonize_dialog.run", _exc)
                    else:
                        self._last_geochem_class_mean = {}
                        self._last_geochem_class_std = {}
                except Exception:
                    self._last_geochem_class_mean = {}
                    self._last_geochem_class_std = {}

                self._write_single_band_geotiff(
                    ds,
                    out_path=cls_path,
                    data=cls.astype(np.int16, copy=False),
                    nodata=0,
                    gdal_type=gdal.GDT_Int16,
                )

                if do_zonal_stats:
                    try:
                        zone_stats_layer = self._make_zonal_stats_layer(
                            zone_layer=zone_layer,
                            zone_selected_only=zone_selected_only,
                            values=out,
                            classes=cls,
                            breaks=breaks,
                            nodata_value=float(nodata_val),
                            geotransform=gt,
                            projection_wkt=proj_wkt,
                            raster_crs=raster.crs(),
                            preset=preset,
                            unit=unit,
                            run_id=run_id,
                            fill_mask=fill_mask if do_inpaint else None,
                            inpaint_on=do_inpaint,
                        )
                    except Exception as e:
                        log_message(f"GeoChem: zonal stats failed: {e}", level=Qgis.MessageLevel.Warning)
            else:
                self._last_geochem_pix_counts = {}
                self._last_geochem_class_mean = {}
                self._last_geochem_class_std = {}
            ds = None

            persist_val_path = None
            persist_cls_path = None
            if do_save_rasters:
                try:
                    persist_val_path, persist_cls_path = self._persist_geochem_rasters(
                        preset=preset,
                        run_id=run_id,
                        val_path=val_path,
                        cls_path=cls_path if do_make_class_raster else None,
                    )
                    log_message(
                        f"GeoChem: saved rasters val={persist_val_path} cls={persist_cls_path}",
                        level=Qgis.MessageLevel.Info,
                    )
                except Exception as e:
                    log_message(f"GeoChem: failed to save rasters: {e}", level=Qgis.MessageLevel.Warning)
                    persist_val_path = None
                    persist_cls_path = None

            center_layer = None
            if do_weight_center:
                try:
                    if not do_mask_aoi:
                        log_message(
                            "GeoChem: AOI 마스크가 꺼져 있어 가중 중심점이 경계 사각형(extent) 기준으로 계산됩니다.",
                            level=Qgis.MessageLevel.Warning,
                        )
                except Exception as _exc:
                    log_swallowed("tools/geochem_polygonize_dialog.py:1770 (run)", _exc)
                try:
                    center_layer = self._make_weighted_center_layer(
                        values=out,
                        nodata_value=float(nodata_val),
                        geotransform=gt,
                        src_crs=raster.crs(),
                        dest_crs=self.iface.mapCanvas().mapSettings().destinationCrs(),
                        preset=preset,
                        unit=unit,
                        run_id=run_id,
                        center_method=center_method,
                        weight_rule=weight_rule,
                        weight_power=weight_power,
                        weight_threshold=weight_threshold,
                        weight_top_pct=weight_top_pct,
                    )
                except Exception as e:
                    log_message(f"GeoChem: center failed: {e}", level=Qgis.MessageLevel.Warning)
                    center_layer = None

            poly: Optional[QgsVectorLayer] = None
            if do_make_polygons:
                # 4) Polygonize -> dissolve
                log_message("GeoChem: polygonize…", level=Qgis.MessageLevel.Info)
                poly_path = os.path.join(self._tmp_dir, f"{preset.key}_poly_{run_id}.gpkg")
                try:
                    if os.path.exists(poly_path):
                        os.remove(poly_path)
                except Exception as _exc:
                    log_swallowed("geochem_polygonize_dialog.run", _exc)

                poly_out = processing.run(
                    "gdal:polygonize",
                    {
                        "INPUT": cls_path,
                        "BAND": 1,
                        "FIELD": "class_id",
                        "EIGHT_CONNECTEDNESS": True,
                        "OUTPUT": poly_path,
                    },
                ).get("OUTPUT")

                log_message(f"GeoChem: polygonize OUTPUT type={type(poly_out).__name__} value={poly_out}", level=Qgis.MessageLevel.Info)

                if isinstance(poly_out, QgsVectorLayer):
                    poly = poly_out
                else:
                    out_str = str(poly_out) if poly_out is not None else ""
                    out_path = (out_str.split("|", 1)[0] or "").strip()
                    if out_path:
                        poly_path = out_path

                    try:
                        exists = os.path.exists(poly_path)
                        size = os.path.getsize(poly_path) if exists else 0
                        log_message(f"GeoChem: polygonize file exists={exists} size={size}", level=Qgis.MessageLevel.Info)
                    except Exception as _exc:
                        log_swallowed("tools/geochem_polygonize_dialog.py:1828 (run)", _exc)

                    # Try to discover the layer name from the GeoPackage and load it reliably.
                    layer_name = None
                    try:
                        vds = gdal.OpenEx(poly_path, gdal.OF_VECTOR)
                        if vds is not None:
                            names = []
                            try:
                                n = int(vds.GetLayerCount() or 0)
                            except Exception:
                                n = 0
                            for i in range(n):
                                _skip_1842 = False
                                try:
                                    lyr = vds.GetLayerByIndex(i)
                                    if lyr is not None:
                                        names.append(str(lyr.GetName()))
                                except Exception as _exc:
                                    log_swallowed("tools/geochem_polygonize_dialog.py:1846 (run)", _exc)
                                    _skip_1842 = True
                                if _skip_1842:
                                    continue
                            vds = None
                            log_message(f"GeoChem: gpkg layers={names}", level=Qgis.MessageLevel.Info)
                            if names:
                                layer_name = names[0]
                    except Exception as _exc:
                        log_swallowed("geochem_polygonize_dialog.run", _exc)

                    uri_candidates = []
                    if layer_name:
                        uri_candidates.append(f"{poly_path}|layername={layer_name}")
                    uri_candidates.append(poly_path)

                    for uri in uri_candidates:
                        _skip_1861 = False
                        try:
                            cand = QgsVectorLayer(uri, f"{preset.label} polygons", "ogr")
                            if cand.isValid():
                                poly = cand
                                break
                        except Exception as _exc:
                            log_swallowed("geochem_polygonize_dialog.run", _exc)
                            log_swallowed("tools/geochem_polygonize_dialog.py:1866 (run)", _exc)
                            _skip_1861 = True
                        if _skip_1861:
                            continue

                if poly is None or not isinstance(poly, QgsVectorLayer) or not poly.isValid():
                    raise RuntimeError("Polygonize failed (no valid vector layer output)")

                # Drop nodata (class_id == 0)
                if do_drop_nodata:
                    try:
                        poly = processing.run(
                            "native:extractbyexpression",
                            {"INPUT": poly, "EXPRESSION": "\"class_id\" > 0", "OUTPUT": "memory:"},
                        )["OUTPUT"]
                    except Exception as _exc:
                        log_swallowed("geochem_polygonize_dialog.run", _exc)

                if do_dissolve:
                    log_message("GeoChem: dissolve by class…", level=Qgis.MessageLevel.Info)
                    poly = processing.run(
                        "native:dissolve",
                        {"INPUT": poly, "FIELD": ["class_id"], "OUTPUT": "memory:"},
                    )["OUTPUT"]

                # Add descriptive fields
                self._decorate_polygons(layer=poly, preset=preset, unit=unit)

            # Add to project (rasters / polygon / point)
            self._add_to_project(
                layer=poly,
                center_layer=center_layer,
                zone_stats_layer=zone_stats_layer,
                preset=preset,
                unit=unit,
                run_id=run_id,
                extent=extent_canvas,
                value_raster_path=persist_val_path if do_add_rasters else None,
                class_raster_path=persist_cls_path if do_add_rasters else None,
            )
            push_message(self.iface, "지구화학도 래스터 수치화", "완료", level=0, duration=7)
        except Exception as e:
            log_exception("GeoChem error", e)
            try:
                log_message(f"GeoChem: kept temp folder for debug: {self._tmp_dir}", level=Qgis.MessageLevel.Warning)
            except Exception as _exc:
                log_swallowed("tools/geochem_polygonize_dialog.py:1910 (run)", _exc)
            push_message(self.iface, "오류", f"처리 실패: {e}", level=2, duration=10)
        finally:
            restore_ui_focus(self)

    def _canvas_pixel_size_in_raster_crs(self, *, dest_crs, raster_crs, centre_dest) -> float:
        """Current canvas pixel size expressed in the raster CRS, measured at ``centre_dest``.

        Transforms a segment one canvas width long (and one canvas height
        long) through ``centre_dest`` (a QgsPointXY in the project CRS) into
        the raster CRS and returns the geometric mean of the two per-pixel
        lengths, which preserves the pixel count. Returns 0.0 when it cannot
        be derived; the caller then falls back and says so.
        """
        try:
            canvas = self.iface.mapCanvas()
            mupp = float(canvas.mapUnitsPerPixel())
            if not (mupp > 0) or not math.isfinite(mupp):
                return 0.0
            w_px = max(1, int(canvas.width() or 0))
            h_px = max(1, int(canvas.height() or 0))
            cx = float(centre_dest.x())
            cy = float(centre_dest.y())
            ct = QgsCoordinateTransform(dest_crs, raster_crs, QgsProject.instance())
            half_w = mupp * w_px / 2.0
            half_h = mupp * h_px / 2.0
            p_l = ct.transform(QgsPointXY(cx - half_w, cy))
            p_r = ct.transform(QgsPointXY(cx + half_w, cy))
            p_b = ct.transform(QgsPointXY(cx, cy - half_h))
            p_t = ct.transform(QgsPointXY(cx, cy + half_h))
            dx = math.hypot(p_r.x() - p_l.x(), p_r.y() - p_l.y()) / float(w_px)
            dy = math.hypot(p_t.x() - p_b.x(), p_t.y() - p_b.y()) / float(h_px)
            if dx > 0 and dy > 0 and math.isfinite(dx) and math.isfinite(dy):
                return float(math.sqrt(dx * dy))
            return 0.0
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._canvas_pixel_size_in_raster_crs", _exc)
            return 0.0

    def _export_raster_to_geotiff(self, *, raster: QgsRasterLayer, out_path: str, extent: QgsRectangle, width: int, height: int) -> bool:
        """Export the raster (including WMS) to a GeoTIFF.

        1) Try QGIS raster writer (fast, works for many providers).
        2) Fallback to Processing GDAL warp (more robust for some WMS providers).
        """
        try:
            from qgis.core import QgsRasterFileWriter, QgsRasterPipe
        except Exception:
            return False

        try:
            provider = raster.dataProvider()
            pipe = QgsRasterPipe()
            if not pipe.set(provider.clone()):
                # Fallback: some providers may not support clone() cleanly.
                if not pipe.set(provider):
                    raise RuntimeError("pipe.set(provider) failed")
            writer = QgsRasterFileWriter(out_path)
            writer.setOutputFormat("GTiff")
            writer.setCreateOptions(["COMPRESS=LZW", "TILED=YES"])
            ctx = QgsProject.instance().transformContext()
            res = writer.writeRaster(pipe, int(width), int(height), extent, raster.crs(), ctx)
            if res != 0:
                log_message(f"GeoChem: writeRaster returned {res}", level=Qgis.MessageLevel.Warning)
                raise RuntimeError(f"writeRaster failed ({res})")
            if os.path.exists(out_path):
                return True
        except Exception as e:
            log_message(f"GeoChem: QGIS export failed, trying GDAL warp… ({e})", level=Qgis.MessageLevel.Warning)

        # Fallback: GDAL warp through Processing (more provider-compatible)
        try:
            extent_str = f"{extent.xMinimum()},{extent.xMaximum()},{extent.yMinimum()},{extent.yMaximum()}"
            # Match the requested width/height via target resolution in layer CRS units.
            px = max(extent.width() / max(1, int(width)), extent.height() / max(1, int(height)))
            px = float(px) if px > 0 else None
            processing.run(
                "gdal:warpreproject",
                {
                    "INPUT": raster,
                    "SOURCE_CRS": None,
                    "TARGET_CRS": None,
                    "RESAMPLING": 0,  # Nearest (preserve legend colors)
                    "NODATA": None,
                    "TARGET_RESOLUTION": px,
                    "OPTIONS": "COMPRESS=LZW|TILED=YES",
                    "DATA_TYPE": 0,
                    "TARGET_EXTENT": extent_str,
                    "TARGET_EXTENT_CRS": raster.crs().authid() if raster.crs() else None,
                    "MULTITHREADING": False,
                    "EXTRA": "",
                    "OUTPUT": out_path,
                },
            )
            if os.path.exists(out_path):
                return True
            log_message("GeoChem: GDAL warp completed but output missing", level=Qgis.MessageLevel.Warning)
            return False
        except Exception as e:
            log_message(f"GeoChem: GDAL warp export failed: {e}", level=Qgis.MessageLevel.Warning)
            return False

    def _write_single_band_geotiff(
        self,
        src_ds,
        *,
        out_path: str,
        data: np.ndarray,
        nodata: float,
        gdal_type=gdal.GDT_Float32,
    ):
        write_single_band_geotiff(
            out_path,
            data,
            geotransform=src_ds.GetGeoTransform(),
            projection=src_ds.GetProjection(),
            nodata=nodata,
            gdal_type=gdal_type,
            options=("COMPRESS=LZW", "TILED=YES"),
        )

    def _persist_geochem_rasters(
        self,
        *,
        preset: GeoChemPreset,
        run_id: str,
        val_path: str,
        cls_path: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        """Persist generated rasters so they remain usable after the dialog closes."""
        out_dir = ""
        try:
            base = (QgsProject.instance().homePath() or "").strip()
            if base:
                out_dir = os.path.join(base, "ArchToolkit_outputs", "geochem")
            else:
                from qgis.core import QgsApplication

                out_dir = os.path.join(QgsApplication.qgisSettingsDirPath(), "ArchToolkit", "outputs", "geochem")
        except Exception:
            out_dir = ""

        if not out_dir:
            try:
                from qgis.PyQt.QtCore import QStandardPaths

                out_dir = os.path.join(
                    QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation),
                    "ArchToolkit_outputs",
                    "geochem",
                )
            except Exception:
                out_dir = os.path.join(os.path.expanduser("~"), "ArchToolkit_outputs", "geochem")

        os.makedirs(out_dir, exist_ok=True)

        # Copy each raster into a staged sibling of its final path, then publish
        # it with an atomic rename, so a crash mid-copy cannot leave a truncated
        # GeoTIFF at the permanent output path. The value raster is required; the
        # class raster stays best-effort, preserving the prior behaviour.
        val_dst = os.path.join(out_dir, os.path.basename(val_path))
        val_staging = reserve_staging_path(val_dst, "geochem")
        try:
            shutil.copy2(val_path, val_staging)
            atomic_publish_file(val_staging, val_dst)
        finally:
            cleanup_staging_path(val_staging)

        cls_dst = None
        if cls_path:
            try:
                if os.path.exists(cls_path):
                    cls_dst = os.path.join(out_dir, os.path.basename(cls_path))
                    cls_staging = reserve_staging_path(cls_dst, "geochem")
                    try:
                        shutil.copy2(cls_path, cls_staging)
                        atomic_publish_file(cls_staging, cls_dst)
                    finally:
                        cleanup_staging_path(cls_staging)
            except Exception:
                cls_dst = None
        return val_dst, cls_dst

    def _make_weighted_center_layer(
        self,
        *,
        values: np.ndarray,
        nodata_value: float,
        geotransform,
        src_crs,
        dest_crs,
        preset: GeoChemPreset,
        unit: str,
        run_id: str,
        center_method: str,
        weight_rule: str,
        weight_power: int,
        weight_threshold: float,
        weight_top_pct: float,
    ) -> Optional[QgsVectorLayer]:
        """Compute a center point from a value raster and return a point memory layer (or None)."""
        if geotransform is None:
            return None

        gt = list(geotransform) if geotransform is not None else None
        if not gt or len(gt) != 6:
            return None

        v = values.astype(np.float32, copy=False)
        valid = np.isfinite(v)
        try:
            valid &= v != np.float32(float(nodata_value))
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._make_weighted_center_layer", _exc)
        if not np.any(valid):
            log_message("GeoChem: center skipped (no valid pixels)", level=Qgis.MessageLevel.Warning)
            return None

        method = (center_method or "weighted_mean").strip()
        if method not in ("weighted_mean", "mean", "peak"):
            method = "weighted_mean"

        rule = (weight_rule or "value").strip()
        thr_used = None
        sel = np.zeros(v.shape, dtype=bool)

        # Build weight array (float64) with zeros outside selection.
        w = np.zeros(v.shape, dtype=np.float64)
        try:
            if rule == "power":
                p = max(1, int(weight_power))
                sel = valid
                vv = np.maximum(v[sel].astype(np.float64, copy=False), 0.0)
                w[sel] = np.power(vv, float(p))
                param = float(p)
            elif rule == "threshold":
                t = float(weight_threshold)
                sel = valid & (v >= np.float32(t))
                w[sel] = v[sel].astype(np.float64, copy=False)
                param = float(t)
            elif rule == "binary":
                t = float(weight_threshold)
                sel = valid & (v >= np.float32(t))
                w[sel] = 1.0
                param = float(t)
            elif rule == "top_pct":
                pct = float(weight_top_pct)
                pct = min(max(pct, 0.1), 100.0)
                vv = v[valid].astype(np.float64, copy=False)
                thr = float(np.nanpercentile(vv, 100.0 - pct))
                thr_used = thr
                sel = valid & (v >= np.float32(thr))
                w[sel] = v[sel].astype(np.float64, copy=False)
                param = float(pct)
            else:
                sel = valid
                vv = np.maximum(v[sel].astype(np.float64, copy=False), 0.0)
                w[sel] = vv
                param = float(1.0)
        except Exception:
            log_message("GeoChem: center skipped (weight computation failed)", level=Qgis.MessageLevel.Warning)
            return None

        if not np.any(sel):
            log_message("GeoChem: center skipped (no pixels after selection)", level=Qgis.MessageLevel.Warning)
            return None
        if rule in ("value", "power"):
            # Label says w = max(value, 0): say how many pixels that clamp touched.
            try:
                n_neg = int(np.count_nonzero(sel & (v < np.float32(0.0))))
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._make_weighted_center_layer", _exc)
                n_neg = 0
            if n_neg > 0:
                log_message(
                    f"GeoChem: center rule={rule}: {n_neg:,} negative-valued pixels weighted 0 (w = max(value, 0)); pix_n still counts them",
                    level=Qgis.MessageLevel.Warning,
                )

        sum_w = float(np.sum(w))
        pix_n = 0
        try:
            pix_n = int(np.count_nonzero(sel))
        except Exception:
            pix_n = 0

        mean_row = None
        mean_col = None
        peak_val = None

        if method == "peak":
            try:
                vv = np.where(sel, v, np.float32(-np.inf))
                idx = int(np.argmax(vv))
                ncol = int(v.shape[1])
                mean_row = float(idx // ncol)
                mean_col = float(idx % ncol)
                peak_val = float(vv[int(mean_row), int(mean_col)])
            except Exception:
                log_message("GeoChem: center skipped (peak computation failed)", level=Qgis.MessageLevel.Warning)
                return None
        else:
            if method == "weighted_mean":
                if not math.isfinite(sum_w) or sum_w <= 0:
                    log_message("GeoChem: center skipped (sum_w <= 0)", level=Qgis.MessageLevel.Warning)
                    return None
                denom = float(sum_w)
                try:
                    row_sums = np.sum(w, axis=1, dtype=np.float64)
                    col_sums = np.sum(w, axis=0, dtype=np.float64)
                except Exception:
                    log_message("GeoChem: center skipped (centroid accumulation failed)", level=Qgis.MessageLevel.Warning)
                    return None
            else:
                denom = float(pix_n)
                if not math.isfinite(denom) or denom <= 0:
                    log_message("GeoChem: center skipped (pix_n <= 0)", level=Qgis.MessageLevel.Warning)
                    return None
                try:
                    row_sums = np.sum(sel, axis=1, dtype=np.float64)
                    col_sums = np.sum(sel, axis=0, dtype=np.float64)
                except Exception:
                    log_message("GeoChem: center skipped (centroid accumulation failed)", level=Qgis.MessageLevel.Warning)
                    return None

            try:
                rows = np.arange(v.shape[0], dtype=np.float64)
                cols = np.arange(v.shape[1], dtype=np.float64)
                mean_row = float(np.dot(row_sums, rows) / denom)
                mean_col = float(np.dot(col_sums, cols) / denom)
            except Exception:
                log_message("GeoChem: center skipped (centroid accumulation failed)", level=Qgis.MessageLevel.Warning)
                return None

        if mean_row is None or mean_col is None:
            return None

        # Convert pixel-space centroid to map coordinates (affine geotransform).
        x = float(gt[0] + (mean_col + 0.5) * gt[1] + (mean_row + 0.5) * gt[2])
        y = float(gt[3] + (mean_col + 0.5) * gt[4] + (mean_row + 0.5) * gt[5])

        # Transform to destination CRS for display.
        pt = QgsPointXY(x, y)
        try:
            if dest_crs and src_crs and dest_crs != src_crs:
                ct = QgsCoordinateTransform(src_crs, dest_crs, QgsProject.instance())
                pt = QgsPointXY(ct.transform(pt))
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._make_weighted_center_layer", _exc)

        # Create output point layer
        crs = dest_crs if dest_crs else src_crs
        uri = "Point?crs=EPSG:4326"
        try:
            auth = (crs.authid() or "").strip() if crs else ""
            if auth:
                uri = f"Point?crs={auth}"
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:2222 (_make_weighted_center_layer)", _exc)

        layer = QgsVectorLayer(uri, f"{preset.key}_중심점_{run_id}", "memory")
        if not layer.isValid():
            return None
        try:
            if crs:
                layer.setCrs(crs)
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:2231 (_make_weighted_center_layer)", _exc)

        pr = layer.dataProvider()
        pr.addAttributes(
            [
                QgsField("element", FT_STRING),
                QgsField("unit", FT_STRING),
                QgsField("c_method", FT_STRING),
                QgsField("w_rule", FT_STRING),
                QgsField("w_param", FT_DOUBLE),
                QgsField("w_thr", FT_DOUBLE),
                QgsField("w_sum", FT_DOUBLE),
                QgsField("pix_n", FT_INT),
            ]
        )
        layer.updateFields()

        ft = QgsFeature(layer.fields())
        ft.setGeometry(QgsGeometry.fromPointXY(pt))
        ft["element"] = preset.label
        ft["unit"] = unit
        ft["c_method"] = method
        ft["w_rule"] = rule
        ft["w_param"] = float(param)
        try:
            ft["w_thr"] = float(thr_used) if thr_used is not None else None
        except Exception:
            ft["w_thr"] = None
        ft["w_sum"] = float(sum_w)
        ft["pix_n"] = int(pix_n)
        pr.addFeatures([ft])
        layer.updateExtents()

        try:
            from qgis.core import QgsMarkerSymbol, QgsSingleSymbolRenderer

            sym = QgsMarkerSymbol.createSimple({"name": "circle", "color": "230,0,0,255", "size": "4"})
            layer.setRenderer(QgsSingleSymbolRenderer(sym))
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:2270 (_make_weighted_center_layer)", _exc)

        try:
            extra = ""
            if peak_val is not None:
                extra = f" peak={peak_val:g}"
            log_message(
                f"GeoChem: center method={method} rule={rule} param={param:g} sum_w={sum_w:g} pix_n={pix_n:,}{extra}",
                level=Qgis.MessageLevel.Info,
            )
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._make_weighted_center_layer", _exc)

        return layer

    def _make_zonal_stats_layer(
        self,
        *,
        zone_layer: QgsVectorLayer,
        zone_selected_only: bool,
        values: np.ndarray,
        classes: np.ndarray,
        breaks: Sequence[float],
        nodata_value: float,
        geotransform,
        projection_wkt: str,
        raster_crs,
        preset: GeoChemPreset,
        unit: str,
        run_id: str,
        fill_mask: Optional[np.ndarray] = None,
        inpaint_on: bool = False,
    ) -> Optional[QgsVectorLayer]:
        """Aggregate value/class rasters per zone polygon and return a new polygon memory layer.

        Pixels are counted by the pixel-centre rule (as QGIS zonal statistics
        does); a zone too small to contain any pixel centre falls back to the
        touched pixels and says so in ``burn_rule``. ``zone_area`` carries the
        polygon's own (ellipsoidal) area so the pixel-derived ``c*_area`` can
        be checked against it. ``fill_mask`` marks inpainted (invented) pixels;
        their share of the zone's valid pixels is written to ``fill_pct``.
        """
        if zone_layer is None or (not isinstance(zone_layer, QgsVectorLayer)):
            return None
        if zone_layer.geometryType() != Qgis.GeometryType.Polygon:
            return None
        if geotransform is None:
            return None

        try:
            inv_gt = _inv_geotransform(geotransform)
        except Exception:
            return None

        full_ysize, full_xsize = values.shape
        if full_xsize <= 0 or full_ysize <= 0:
            return None

        try:
            px_area = abs(float(geotransform[1]) * float(geotransform[5]) - float(geotransform[2]) * float(geotransform[4]))
        except Exception:
            px_area = 0.0
        if not math.isfinite(px_area) or px_area < 0:
            px_area = 0.0
        # px_area and every c*_area below are in the RASTER CRS units squared.
        # A WMS is often served in EPSG:4326, in which case these are square
        # degrees and must not be read as an area. Name the unit in a field and
        # warn once rather than let a square-degree number sit in an area column.
        try:
            rcrs = raster_crs
            if rcrs is not None and rcrs.isValid() and rcrs.isGeographic():
                px_area_unit = "deg2"
                log_message(
                    "GeoChem zonal: 래스터 CRS가 위경도라 px_area/c*_area는 제곱도(deg²)입니다. 면적으로 읽지 마세요.",
                    level=Qgis.MessageLevel.Warning,
                )
            elif rcrs is not None and rcrs.isValid():
                # Projected: label with the CRS authid so the unit is traceable
                # (a Korean belt is metres; a feet-based CRS is not).
                px_area_unit = f"{rcrs.authid() or 'projected'} units^2"
            else:
                px_area_unit = "unknown"
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._make_zonal_stats_layer (area unit)", _exc)
            px_area_unit = "unknown"

        # Output layer (same CRS as zone layer)
        crs = zone_layer.crs()
        uri = "Polygon?crs=EPSG:4326"
        try:
            auth = (crs.authid() or "").strip() if crs else ""
            if auth:
                uri = f"Polygon?crs={auth}"
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:2333 (_make_zonal_stats_layer)", _exc)

        out_layer = QgsVectorLayer(uri, f"{preset.key}_zonal_{run_id}", "memory")
        if not out_layer.isValid():
            return None
        try:
            if crs:
                out_layer.setCrs(crs)
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:2342 (_make_zonal_stats_layer)", _exc)

        pr = out_layer.dataProvider()
        try:
            orig_fields = list(zone_layer.fields())
        except Exception:
            orig_fields = []

        extra_fields: List[QgsField] = [
            QgsField("element", FT_STRING),
            QgsField("unit", FT_STRING),
            QgsField("run_id", FT_STRING),
            QgsField("pix_in", FT_INT),
            QgsField("pix_val", FT_INT),
            QgsField("cov_pct", FT_DOUBLE),
            QgsField("val_mean", FT_DOUBLE),
            QgsField("val_std", FT_DOUBLE),
            QgsField("val_min", FT_DOUBLE),
            QgsField("val_max", FT_DOUBLE),
            QgsField("px_area", FT_DOUBLE),
            QgsField("area_unit", FT_STRING),
            QgsField("zone_area", FT_DOUBLE),
            QgsField("zarea_unit", FT_STRING),
            QgsField("burn_rule", FT_STRING),
            QgsField("fill_pct", FT_DOUBLE),
        ]

        n_classes = max(0, int(len(breaks) - 1))
        width = min(3, max(2, len(str(max(1, n_classes)))))
        for cid in range(1, n_classes + 1):
            s = str(cid).zfill(width)
            extra_fields.append(QgsField(f"c{s}_n", FT_INT))
            extra_fields.append(QgsField(f"c{s}_pct", FT_DOUBLE))
            extra_fields.append(QgsField(f"c{s}_area", FT_DOUBLE))

        try:
            pr.addAttributes(orig_fields + extra_fields)
        except Exception:
            try:
                for f in orig_fields + extra_fields:
                    pr.addAttributes([f])
            except Exception:
                return None
        out_layer.updateFields()

        # Geometric area of the zone polygon itself: ellipsoidal m2 when an
        # ellipsoid is available (same setup as _decorate_polygons), otherwise
        # planar in the raster CRS units, labelled in zarea_unit either way.
        zone_dist = None
        zone_area_unit = px_area_unit
        try:
            from qgis.core import QgsDistanceArea

            zone_dist = QgsDistanceArea()
            zone_dist.setSourceCrs(crs, QgsProject.instance().transformContext())
            ell = (QgsProject.instance().ellipsoid() or "").strip()
            if not ell or ell.upper() == "NONE":
                ell = "WGS84"
            zone_dist.setEllipsoid(ell)
            if zone_dist.willUseEllipsoid():
                zone_area_unit = "m2"
            else:
                zone_dist = None
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._make_zonal_stats_layer (zone area)", _exc)
            zone_dist = None
        n_burn_fallback = 0

        # Transform zones to raster CRS for rasterization
        ct = None
        try:
            if crs and raster_crs and crs != raster_crs:
                ct = QgsCoordinateTransform(crs, raster_crs, QgsProject.instance())
        except Exception:
            ct = None

        # Iterate zones
        feats = None
        try:
            if zone_selected_only and zone_layer.selectedFeatureCount() > 0:
                feats = zone_layer.selectedFeatures()
            else:
                if zone_selected_only:
                    push_message(
                        self.iface,
                        "경고",
                        f"구역 레이어 '{zone_layer.name()}'에 선택된 피처가 없어 전체 피처로 구역 통계를 계산합니다.",
                        level=1,
                        duration=7,
                    )
                    log_message("GeoChem: zone selected-only requested but no selection; using all features", level=Qgis.MessageLevel.Warning)
                feats = zone_layer.getFeatures()
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._make_zonal_stats_layer", _exc)
            feats = zone_layer.getFeatures()

        added = 0
        for zft in feats:
            try:
                geom = zft.geometry()
            except Exception:
                geom = None
            if geom is None or geom.isEmpty():
                continue

            # Keep original geometry for output
            out_geom = geom

            # Copy & transform for rasterization
            geom_r = QgsGeometry(geom)
            if ct is not None:
                try:
                    geom_r.transform(ct)
                except Exception as _exc:
                    log_swallowed("geochem_polygonize_dialog._make_zonal_stats_layer", _exc)

            _skip_2421 = False
            try:
                bbox = geom_r.boundingBox()
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._make_zonal_stats_layer", _exc)
                log_swallowed("tools/geochem_polygonize_dialog.py:2423 (_make_zonal_stats_layer)", _exc)
                _skip_2421 = True
            if _skip_2421:
                continue
            if bbox.isEmpty():
                continue

            # Compute pixel window from bbox (fast crop)
            _skip_2430 = False
            try:
                corners = [
                    (bbox.xMinimum(), bbox.yMinimum()),
                    (bbox.xMinimum(), bbox.yMaximum()),
                    (bbox.xMaximum(), bbox.yMinimum()),
                    (bbox.xMaximum(), bbox.yMaximum()),
                ]
                cols = []
                rows = []
                for x, y in corners:
                    c, r = gdal.ApplyGeoTransform(inv_gt, float(x), float(y))
                    cols.append(float(c))
                    rows.append(float(r))
                min_col = int(math.floor(min(cols)))
                max_col = int(math.ceil(max(cols)))
                min_row = int(math.floor(min(rows)))
                max_row = int(math.ceil(max(rows)))
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._make_zonal_stats_layer", _exc)
                log_swallowed("tools/geochem_polygonize_dialog.py:2447 (_make_zonal_stats_layer)", _exc)
                _skip_2430 = True
            if _skip_2430:
                continue

            xoff = max(0, min(full_xsize - 1, min_col))
            yoff = max(0, min(full_ysize - 1, min_row))
            xend = max(0, min(full_xsize - 1, max_col))
            yend = max(0, min(full_ysize - 1, max_row))
            xsize = int(xend - xoff + 1)
            ysize = int(yend - yoff + 1)
            if xsize <= 0 or ysize <= 0:
                continue

            sub_gt = _window_geotransform(geotransform, xoff, yoff)
            # Pixel-centre rule (all_touched=False), as QGIS zonal statistics:
            # ALL_TOUCHED dilated every zone by up to a pixel on each side.
            burn_rule = "cell_centre"
            try:
                mask = _gdal_rasterize_wkt_mask(
                    geom_wkt=str(geom_r.asWkt()),
                    xsize=int(xsize),
                    ysize=int(ysize),
                    geotransform=sub_gt,
                    projection_wkt=str(projection_wkt or ""),
                    all_touched=False,
                )
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._make_zonal_stats_layer (rasterize)", _exc)
                mask = None
            if mask is None:
                continue
            if not np.any(mask):
                # Zone smaller than a pixel (no pixel centre inside): use the
                # touched pixels rather than drop the zone, and say so.
                try:
                    mask_touch = _gdal_rasterize_wkt_mask(
                        geom_wkt=str(geom_r.asWkt()),
                        xsize=int(xsize),
                        ysize=int(ysize),
                        geotransform=sub_gt,
                        projection_wkt=str(projection_wkt or ""),
                        all_touched=True,
                    )
                except Exception as _exc:
                    log_swallowed("geochem_polygonize_dialog._make_zonal_stats_layer (rasterize fallback)", _exc)
                    mask_touch = None
                if mask_touch is not None and np.any(mask_touch):
                    mask = mask_touch
                    burn_rule = "all_touched"
                    n_burn_fallback += 1

            v_sub = values[yoff:yoff + ysize, xoff:xoff + xsize]
            c_sub = classes[yoff:yoff + ysize, xoff:xoff + xsize]

            inside = mask.astype(bool, copy=False)
            try:
                pix_in = int(np.count_nonzero(inside))
            except Exception:
                pix_in = 0
            if pix_in <= 0:
                continue

            v_inside = v_sub[inside].astype(np.float32, copy=False)
            valid = np.isfinite(v_inside)
            try:
                valid &= v_inside != np.float32(float(nodata_value))
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._make_zonal_stats_layer", _exc)
            pix_val = int(np.count_nonzero(valid)) if pix_in > 0 else 0
            cov_pct = float(pix_val) * 100.0 / float(pix_in) if pix_in > 0 else 0.0

            zone_area = None
            try:
                if zone_dist is not None:
                    zone_area = float(zone_dist.measureArea(out_geom))
                else:
                    zone_area = float(geom_r.area())
                if not math.isfinite(zone_area):
                    zone_area = None
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._make_zonal_stats_layer (zone area)", _exc)
                zone_area = None

            # Share of the zone's valid pixels that were inpainted (invented).
            # NULL when inpainting was on but the mask is unavailable.
            fill_pct = None if inpaint_on else 0.0
            if fill_mask is not None:
                try:
                    f_inside = fill_mask[yoff:yoff + ysize, xoff:xoff + xsize][inside]
                    n_fill = int(np.count_nonzero(f_inside & valid)) if f_inside.shape == valid.shape else 0
                    fill_pct = float(n_fill) * 100.0 / float(pix_val) if pix_val > 0 else 0.0
                except Exception as _exc:
                    log_swallowed("geochem_polygonize_dialog._make_zonal_stats_layer (fill_pct)", _exc)
                    fill_pct = None

            v_mean = None
            v_std = None
            v_min = None
            v_max = None
            if pix_val > 0:
                try:
                    vv = v_inside[valid].astype(np.float64, copy=False)
                    v_mean = float(np.mean(vv))
                    v_std = float(np.std(vv))
                    v_min = float(np.min(vv))
                    v_max = float(np.max(vv))
                except Exception:
                    v_mean = None
                    v_std = None
                    v_min = None
                    v_max = None

            # Class counts (within valid pixels only)
            cls_counts = None
            try:
                cls_inside = c_sub[inside].astype(np.int64, copy=False)
                if cls_inside.shape == valid.shape:
                    cls_inside = cls_inside[valid]
                cls_counts = np.bincount(cls_inside, minlength=max(1, n_classes + 1))
            except Exception:
                cls_counts = None

            out_ft = QgsFeature(out_layer.fields())
            try:
                out_ft.setGeometry(out_geom)
            except Exception as _exc:
                log_swallowed("tools/geochem_polygonize_dialog.py:2524 (_make_zonal_stats_layer)", _exc)

            try:
                attrs = list(zft.attributes())
            except Exception:
                attrs = []
            try:
                out_ft.setAttributes(attrs + [None] * len(extra_fields))
            except Exception as _exc:
                log_swallowed("tools/geochem_polygonize_dialog.py:2533 (_make_zonal_stats_layer)", _exc)

            try:
                out_ft["element"] = preset.label
                out_ft["unit"] = unit
                out_ft["run_id"] = run_id
                out_ft["pix_in"] = int(pix_in)
                out_ft["pix_val"] = int(pix_val)
                out_ft["cov_pct"] = float(cov_pct)
                out_ft["val_mean"] = float(v_mean) if v_mean is not None else None
                out_ft["val_std"] = float(v_std) if v_std is not None else None
                out_ft["val_min"] = float(v_min) if v_min is not None else None
                out_ft["val_max"] = float(v_max) if v_max is not None else None
                out_ft["px_area"] = float(px_area) if px_area > 0 else None
                out_ft["area_unit"] = px_area_unit
                out_ft["zone_area"] = float(zone_area) if zone_area is not None else None
                out_ft["zarea_unit"] = zone_area_unit
                out_ft["burn_rule"] = burn_rule
                out_ft["fill_pct"] = float(fill_pct) if fill_pct is not None else None

                if cls_counts is not None:
                    for cid in range(1, n_classes + 1):
                        s = str(cid).zfill(width)
                        n = int(cls_counts[cid]) if cid < len(cls_counts) else 0
                        out_ft[f"c{s}_n"] = int(n)
                        out_ft[f"c{s}_pct"] = float(n) * 100.0 / float(pix_in) if pix_in > 0 else 0.0
                        out_ft[f"c{s}_area"] = float(n) * float(px_area) if px_area > 0 else None
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._make_zonal_stats_layer", _exc)

            _skip_2559 = False
            try:
                pr.addFeatures([out_ft])
                added += 1
            except Exception as _exc:
                log_swallowed("tools/geochem_polygonize_dialog.py:2562 (_make_zonal_stats_layer)", _exc)
                _skip_2559 = True
            if _skip_2559:
                continue

        out_layer.updateExtents()
        self._last_geochem_zonal_meta = {
            "zone_burn_rule": "cell_centre",
            "zone_burn_fallback_n": int(n_burn_fallback),
            "zone_area_unit": str(zone_area_unit),
        }
        if n_burn_fallback > 0:
            log_message(
                f"GeoChem zonal: {n_burn_fallback}개 구역이 픽셀보다 작아 닿은 픽셀 기준(all_touched)으로 집계했습니다"
                " (burn_rule 필드 참조; zone_area와 c*_area 합을 비교하세요)",
                level=Qgis.MessageLevel.Warning,
            )
        try:
            log_message(f"GeoChem: zonal stats features={added}", level=Qgis.MessageLevel.Info)
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:2568 (_make_zonal_stats_layer)", _exc)
        return out_layer

    def _style_value_raster(self, *, layer: QgsRasterLayer, preset: GeoChemPreset, unit: str):
        """Apply legend-based pseudo-color styling to a value raster layer."""
        try:
            from qgis.core import QgsColorRampShader, QgsRasterShader, QgsSingleBandPseudoColorRenderer

            shader = QgsRasterShader()
            ramp = QgsColorRampShader()
            ramp.setColorRampType(SHADER_INTERPOLATED)
            items = []
            for p in preset.points:
                _skip_2582 = False
                try:
                    val = float(p.value)
                    col = QColor(int(p.rgb[0]), int(p.rgb[1]), int(p.rgb[2]))
                    items.append(QgsColorRampShader.ColorRampItem(val, col, f"{val:g}{unit}"))
                except Exception as _exc:
                    log_swallowed("geochem_polygonize_dialog._style_value_raster", _exc)
                    log_swallowed("tools/geochem_polygonize_dialog.py:2586 (_style_value_raster)", _exc)
                    _skip_2582 = True
                if _skip_2582:
                    continue
            if not items:
                return
            ramp.setColorRampItemList(items)
            try:
                ramp.setMinimumValue(float(items[0].value))
                ramp.setMaximumValue(float(items[-1].value))
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._style_value_raster", _exc)
            shader.setRasterShaderFunction(ramp)
            renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
            try:
                renderer.setClassificationMin(float(items[0].value))
                renderer.setClassificationMax(float(items[-1].value))
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._style_value_raster", _exc)
            layer.setRenderer(renderer)
            layer.triggerRepaint()
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._style_value_raster", _exc)

    def _style_class_raster(self, *, layer: QgsRasterLayer, preset: GeoChemPreset, unit: str):
        """Apply legend-based palette styling to a class raster layer."""
        try:
            from qgis.core import QgsPalettedRasterRenderer

            breaks = _points_to_breaks(preset.points)
            classes = []
            try:
                nd = preset.points[0].rgb if preset.points else (204, 204, 204)
                classes.append(QgsPalettedRasterRenderer.Class(0, QColor(int(nd[0]), int(nd[1]), int(nd[2])), "NoData"))
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._style_class_raster", _exc)
            for i in range(1, len(breaks)):
                v0 = float(breaks[i - 1])
                v1 = float(breaks[i])
                mid = (v0 + v1) / 2.0
                col = _rgb_for_value(points=preset.points, value=mid)
                classes.append(
                    QgsPalettedRasterRenderer.Class(int(i), QColor(int(col[0]), int(col[1]), int(col[2])), _interval_label(v0, v1, unit))
                )
            if not classes:
                return
            renderer = QgsPalettedRasterRenderer(layer.dataProvider(), 1, classes)
            layer.setRenderer(renderer)
            layer.triggerRepaint()
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._style_class_raster", _exc)

    def _decorate_polygons(self, *, layer: QgsVectorLayer, preset: GeoChemPreset, unit: str):
        breaks = _points_to_breaks(preset.points)
        intervals = [(breaks[i], breaks[i + 1]) for i in range(len(breaks) - 1)]

        pr = layer.dataProvider()
        pr.addAttributes(
            [
                QgsField("element", FT_STRING),
                QgsField("unit", FT_STRING),
                QgsField("v_min", FT_DOUBLE),
                QgsField("v_max", FT_DOUBLE),
                QgsField("v_mid", FT_DOUBLE),
                QgsField("val_mean", FT_DOUBLE),
                QgsField("val_std", FT_DOUBLE),
                QgsField("label", FT_STRING),
                QgsField("pix_n", FT_INT),
                QgsField("pix_pct", FT_DOUBLE),
                QgsField("area_m2", FT_DOUBLE),
                QgsField("area_ha", FT_DOUBLE),
                QgsField("area_pct", FT_DOUBLE),
            ]
        )
        layer.updateFields()

        # Field aliases (Korean)
        try:
            def _alias(name: str, alias: str):
                idx = layer.fields().indexFromName(name)
                if idx >= 0:
                    layer.setFieldAlias(idx, alias)

            _alias("class_id", "구간ID")
            _alias("element", "원소/지표")
            _alias("unit", "단위")
            _alias("v_min", "구간 최소값")
            _alias("v_max", "구간 최대값")
            _alias("v_mid", "구간 대표값(중앙)")
            _alias("val_mean", "구간 평균값")
            _alias("label", "구간 라벨")
            _alias("pix_n", "픽셀 수")
            _alias("pix_pct", "픽셀 비율(%)")
            _alias("area_m2", "면적(m²)")
            _alias("area_ha", "면적(ha)")
            _alias("area_pct", "면적 비율(%)")
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._decorate_polygons", _exc)

        try:
            idx = layer.fields().indexFromName("val_std")
            if idx >= 0:
                layer.setFieldAlias(idx, "구간 표준편차")
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._decorate_polygons", _exc)

        # Apply attributes and style
        cats = []
        try:
            nd_col = preset.points[0].rgb if preset.points else (204, 204, 204)
            nd_qcol = QColor(int(nd_col[0]), int(nd_col[1]), int(nd_col[2]), 120)
            from qgis.core import QgsFillSymbol

            nd_sym = QgsFillSymbol.createSimple(
                {
                    "color": f"{nd_qcol.red()},{nd_qcol.green()},{nd_qcol.blue()},{nd_qcol.alpha()}",
                    "outline_color": "0,0,0,30",
                    "outline_width": "0.1",
                }
            )
            cats.append(QgsRendererCategory(int(0), nd_sym, "NoData"))
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._decorate_polygons", _exc)
        for i, (v0, v1) in enumerate(intervals, start=1):
            mid = (float(v0) + float(v1)) / 2.0
            col = _rgb_for_value(points=preset.points, value=mid)
            qcol = QColor(int(col[0]), int(col[1]), int(col[2]), 140)
            try:
                from qgis.core import QgsFillSymbol

                fs = QgsFillSymbol.createSimple(
                    {
                        "color": f"{qcol.red()},{qcol.green()},{qcol.blue()},{qcol.alpha()}",
                        "outline_color": "0,0,0,40",
                        "outline_width": "0.1",
                    }
                )
            except Exception:
                from qgis.core import QgsFillSymbol

                fs = QgsFillSymbol.createSimple({"color": "200,200,200,120", "outline_color": "0,0,0,40"})
            cats.append(QgsRendererCategory(int(i), fs, _interval_label(v0, v1, unit)))

        try:
            layer.setRenderer(QgsCategorizedSymbolRenderer("class_id", cats))
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:2730 (_decorate_polygons)", _exc)

        # Compute per-feature geometry area (m²) for statistics fields.
        # When dissolve is enabled, there is typically 1 feature per class_id.
        area_by_fid = {}
        features_per_class = {}
        has_class0 = False
        try:
            from qgis.core import QgsDistanceArea, QgsProject

            dist = QgsDistanceArea()
            dist.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
            try:
                ell = (QgsProject.instance().ellipsoid() or "").strip()
                if not ell or ell.upper() == "NONE":
                    ell = "WGS84"
                dist.setEllipsoid(ell)
                dist.setEllipsoidalMode(True)
            except Exception as _exc:
                log_swallowed("tools/geochem_polygonize_dialog.py:2749 (_decorate_polygons)", _exc)

            for ft in layer.getFeatures():
                _skip_2753 = False
                try:
                    try:
                        cid = int(ft["class_id"]) if ft["class_id"] is not None else 0
                        if cid == 0:
                            has_class0 = True
                            features_per_class[0] = int(features_per_class.get(0, 0)) + 1
                        elif cid > 0:
                            features_per_class[cid] = int(features_per_class.get(cid, 0)) + 1
                    except Exception as _exc:
                        log_swallowed("geochem_polygonize_dialog._decorate_polygons", _exc)
                    geom = ft.geometry()
                    if geom is None or geom.isEmpty():
                        continue
                    area_m2 = float(dist.measureArea(geom))
                    if math.isfinite(area_m2) and area_m2 > 0:
                        area_by_fid[int(ft.id())] = area_m2
                except Exception as _exc:
                    log_swallowed("geochem_polygonize_dialog._decorate_polygons", _exc)
                    log_swallowed("tools/geochem_polygonize_dialog.py:2769 (_decorate_polygons)", _exc)
                    _skip_2753 = True
                if _skip_2753:
                    continue
        except Exception:
            area_by_fid = {}
            features_per_class = {}
            has_class0 = False

        total_area_m2 = float(sum(area_by_fid.values())) if area_by_fid else 0.0
        if not math.isfinite(total_area_m2) or total_area_m2 <= 0:
            total_area_m2 = 0.0

        # Pixel-count stats (if provided by run()).
        pix_n_by_cid = {}
        try:
            pix_n_by_cid = getattr(self, "_last_geochem_pix_counts", {}) or {}
        except Exception:
            pix_n_by_cid = {}
        mean_by_cid = {}
        try:
            mean_by_cid = getattr(self, "_last_geochem_class_mean", {}) or {}
        except Exception:
            mean_by_cid = {}
        std_by_cid = {}
        try:
            std_by_cid = getattr(self, "_last_geochem_class_std", {}) or {}
        except Exception:
            std_by_cid = {}
        is_one_feature_per_class = True
        try:
            is_one_feature_per_class = all(int(n) <= 1 for n in features_per_class.values())
        except Exception:
            is_one_feature_per_class = True
        if not is_one_feature_per_class:
            try:
                log_message(
                    "GeoChem: dissolve가 꺼져 있어 class_id별 픽셀 통계를 폴리곤 피처에 직접 기록하지 않습니다.",
                    level=Qgis.MessageLevel.Warning,
                )
            except Exception as _exc:
                log_swallowed("tools/geochem_polygonize_dialog.py:2808 (_decorate_polygons)", _exc)
        total_pix = 0
        try:
            for cid, n in pix_n_by_cid.items():
                if has_class0 and int(cid) >= 0:
                    total_pix += int(n)
                elif int(cid) > 0:
                    total_pix += int(n)
        except Exception:
            total_pix = 0

        # Write per-feature attributes
        layer.startEditing()
        try:
            for ft in layer.getFeatures():
                cid = int(ft["class_id"]) if ft["class_id"] is not None else 0
                ft["element"] = preset.label
                ft["unit"] = unit
                if cid == 0:
                    ft["v_min"] = None
                    ft["v_max"] = None
                    ft["v_mid"] = None
                    ft["val_mean"] = None
                    ft["val_std"] = None
                    ft["label"] = "NoData"
                    if is_one_feature_per_class:
                        try:
                            pix_n = int(pix_n_by_cid.get(0, 0) or 0)
                        except Exception:
                            pix_n = 0
                        ft["pix_n"] = int(pix_n)
                        if total_pix > 0:
                            ft["pix_pct"] = float(pix_n) * 100.0 / float(total_pix)
                        else:
                            ft["pix_pct"] = 0.0
                    else:
                        ft["pix_n"] = None
                        ft["pix_pct"] = None
                else:
                    if cid < 1 or cid > len(intervals):
                        continue
                    v0, v1 = intervals[cid - 1]
                    ft["v_min"] = float(v0)
                    ft["v_max"] = float(v1)
                    v_mid = (float(v0) + float(v1)) / 2.0
                    ft["label"] = _interval_label(v0, v1, unit)
                    if is_one_feature_per_class:
                        ft["v_mid"] = v_mid
                        try:
                            ft["val_mean"] = float(mean_by_cid.get(cid, v_mid))
                        except Exception:
                            ft["val_mean"] = v_mid
                        try:
                            ft["val_std"] = float(std_by_cid.get(cid, 0.0))
                        except Exception:
                            ft["val_std"] = 0.0
                        try:
                            pix_n = int(pix_n_by_cid.get(cid, 0) or 0)
                        except Exception:
                            pix_n = 0
                        ft["pix_n"] = int(pix_n)
                        if total_pix > 0:
                            ft["pix_pct"] = float(pix_n) * 100.0 / float(total_pix)
                        else:
                            ft["pix_pct"] = 0.0
                    else:
                        # Avoid misleading duplicated values when there are multiple features per class.
                        ft["v_mid"] = None
                        ft["val_mean"] = None
                        ft["val_std"] = None
                        ft["pix_n"] = None
                        ft["pix_pct"] = None

                area_m2 = float(area_by_fid.get(int(ft.id()), 0.0) or 0.0)
                if not math.isfinite(area_m2) or area_m2 < 0:
                    area_m2 = 0.0
                ft["area_m2"] = area_m2
                ft["area_ha"] = area_m2 / 10000.0 if area_m2 > 0 else 0.0
                if total_area_m2 > 0:
                    ft["area_pct"] = area_m2 * 100.0 / total_area_m2
                else:
                    ft["area_pct"] = 0.0
                layer.updateFeature(ft)
        finally:
            layer.commitChanges()
        layer.triggerRepaint()

    def _add_to_project(
        self,
        *,
        layer: Optional[QgsVectorLayer],
        center_layer: Optional[QgsVectorLayer] = None,
        zone_stats_layer: Optional[QgsVectorLayer] = None,
        preset: GeoChemPreset,
        unit: str,
        run_id: str,
        extent: QgsRectangle,
        value_raster_path: Optional[str] = None,
        class_raster_path: Optional[str] = None,
    ):
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        parent = root.findGroup(PARENT_GROUP_NAME)
        if parent is None:
            parent = root.insertGroup(0, PARENT_GROUP_NAME)

        if layer is not None:
            try:
                name = f"{preset.key}_구간폴리곤_{run_id}"
                layer.setName(name)
            except Exception as _exc:
                log_swallowed("tools/geochem_polygonize_dialog.py:2919 (_add_to_project)", _exc)
        if center_layer is not None:
            try:
                center_layer.setName(f"{preset.key}_중심점_{run_id}")
            except Exception as _exc:
                log_swallowed("tools/geochem_polygonize_dialog.py:2924 (_add_to_project)", _exc)
        if zone_stats_layer is not None:
            try:
                zone_stats_layer.setName(f"{preset.key}_구역통계_{run_id}")
            except Exception as _exc:
                log_swallowed("tools/geochem_polygonize_dialog.py:2929 (_add_to_project)", _exc)

        layers_to_add = []
        val_layer = None
        cls_layer = None
        if class_raster_path:
            try:
                cls_layer = QgsRasterLayer(class_raster_path, f"{preset.key}_class_{run_id}")
                if cls_layer.isValid():
                    self._style_class_raster(layer=cls_layer, preset=preset, unit=unit)
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._add_to_project", _exc)
        if value_raster_path:
            try:
                val_layer = QgsRasterLayer(value_raster_path, f"{preset.key}_value_{run_id}")
                if val_layer.isValid():
                    self._style_value_raster(layer=val_layer, preset=preset, unit=unit)
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._add_to_project", _exc)

        if val_layer is not None and val_layer.isValid():
            layers_to_add.append(val_layer)
        if cls_layer is not None and cls_layer.isValid():
            layers_to_add.append(cls_layer)
        if layer is not None and layer.isValid():
            layers_to_add.append(layer)
        if center_layer is not None and center_layer.isValid():
            layers_to_add.append(center_layer)
        if zone_stats_layer is not None and zone_stats_layer.isValid():
            layers_to_add.append(zone_stats_layer)

        for lyr in layers_to_add:
            try:
                kind = "layer"
                units0 = str(unit or "").strip()
                if lyr is val_layer:
                    kind = "value_raster"
                elif lyr is cls_layer:
                    kind = "class_raster"
                    units0 = "class"
                elif lyr is layer:
                    kind = "polygonize"
                elif lyr is center_layer:
                    kind = "weighted_center"
                    units0 = "m"
                elif lyr is zone_stats_layer:
                    kind = "zonal_stats"

                params = {
                    "preset_key": str(getattr(preset, "key", "") or ""),
                    "preset_label": str(getattr(preset, "label", "") or ""),
                    "unit": str(unit or ""),
                }
                # Resolution and corrections travel with the rasters; the
                # zonal layer records its pixel-counting rule.
                if kind in ("value_raster", "class_raster"):
                    params.update(dict(getattr(self, "_last_geochem_run_params", None) or {}))
                elif kind == "zonal_stats":
                    params.update(dict(getattr(self, "_last_geochem_zonal_meta", None) or {}))
                set_archtoolkit_layer_metadata(
                    lyr,
                    tool_id="geochem",
                    run_id=str(run_id),
                    kind=kind,
                    units=units0,
                    params=params,
                )
            except Exception as _exc:
                log_swallowed("geochem_polygonize_dialog._add_to_project", _exc)
            project.addMapLayer(lyr, False)
            parent.insertLayer(0, lyr)

        try:
            parent.setExpanded(True)
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:2997 (_add_to_project)", _exc)

        try:
            # Keep group near top
            if parent.parent() == root:
                idx = root.children().index(parent)
                if idx != 0:
                    root.removeChildNode(parent)
                    root.insertChildNode(0, parent)
        except Exception as _exc:
            log_swallowed("geochem_polygonize_dialog._add_to_project", _exc)

        try:
            self.iface.mapCanvas().setExtent(extent)
            self.iface.mapCanvas().refresh()
        except Exception as _exc:
            log_swallowed("tools/geochem_polygonize_dialog.py:3013 (_add_to_project)", _exc)
