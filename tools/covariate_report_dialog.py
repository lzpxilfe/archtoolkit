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
변수 상관/다중공선성 리포트 (Covariate Correlation & VIF Report).

Before feeding a covariate stack to a predictive model (e.g. MaxEnt), redundant
variables (multicollinearity) distort variable importance and inflate variance.
This tool samples the selected rasters on a shared deterministic grid of points
(inside the AOI polygon when one is chosen; at most one point per cell of the
first raster) and reports:
- a Pearson correlation matrix (flagging |r| >= 0.7), and
- Variance Inflation Factors (VIF = 1 / (1 - R^2_i); 5 and 10 are shown as
  reference lines, not removal rules - O'Brien 2007).

It is an *analysis of your variables*, not a variable generator.

Design: NumPy + QGIS raster sampling only (both ship with QGIS), per
DEVELOPMENT.md. Sampling handles differing grids/CRS via each provider's own
sample() with coordinate transforms.
"""

from __future__ import annotations

import csv
import math
import os
from typing import Optional

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt
from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPoint,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
)

from .help_dialog import show_help_dialog
from . import dialog_memory
from .icons import icon as plugin_icon
from .aoi_extent import resolve_aoi_extent
from .utils import (
    log_swallowed,
    get_archtoolkit_layer_metadata,
    is_categorical_raster_meta,
    log_exception,
    log_message,
    push_message,
    restore_ui_focus,
)

# Deterministic sampling grid params (Date/random are unavailable/undesired here;
# a fixed low-discrepancy-ish scan keeps results reproducible run to run).
_HIGH_CORR = 0.7
_VIF_WARN = 5.0
_VIF_BAD = 10.0


def _common_extent(layers, dst_crs) -> Optional[QgsRectangle]:
    rect = None
    for lyr in layers:
        _skip_79 = False
        try:
            e = lyr.extent()
            if lyr.crs() != dst_crs:
                ct = QgsCoordinateTransform(lyr.crs(), dst_crs, QgsProject.instance())
                e = ct.transformBoundingBox(e)
        except Exception as _exc:
            log_swallowed("tools/covariate_report_dialog.py:84 (_common_extent)", _exc)
            _skip_79 = True
        if _skip_79:
            continue
        if rect is None:
            rect = QgsRectangle(e)
        else:
            rect = rect.intersect(e)
    if rect is None or rect.isEmpty():
        return None
    return rect


def _unique_names(names):
    """Layer names as report/CSV headers: a repeated name gets ' (2)', ' (3)', ...
    so two columns can never read as the same variable."""
    seen = {}
    out = []
    for name in names:
        count = seen.get(name, 0) + 1
        seen[name] = count
        out.append(name if count == 1 else f"{name} ({count})")
    return out


def _aoi_union_geometry(aoi_layer, *, selected_only: bool, dst_crs) -> Optional[QgsGeometry]:
    """Union of the AOI layer's (selected) polygons in ``dst_crs``; None when it cannot be built.

    resolve_aoi_extent() validates the AOI and yields its rectangle, which only
    bounds the scan. Sampling needs the polygon itself: the bounding box of a
    valley-shaped survey area would report correlations from the hillsides the
    user excluded.
    """
    try:
        feats = aoi_layer.selectedFeatures() if selected_only else aoi_layer.getFeatures()
    except Exception as _exc:
        log_swallowed("tools/covariate_report_dialog.py (_aoi_union_geometry features)", _exc)
        return None
    geoms = []
    for ft in feats:
        try:
            g = ft.geometry()
        except Exception as _exc:
            log_swallowed("tools/covariate_report_dialog.py (_aoi_union_geometry geometry)", _exc)
            g = None
        if g is not None and not g.isNull() and not g.isEmpty():
            geoms.append(QgsGeometry(g))
    if not geoms:
        return None
    try:
        geom = QgsGeometry.unaryUnion(geoms)
    except Exception as _exc:
        log_swallowed("tools/covariate_report_dialog.py (_aoi_union_geometry unaryUnion)", _exc)
        geom = None
    if geom is None or geom.isNull() or geom.isEmpty():
        # GEOS rejects the whole union when one polygon is invalid; join them one
        # by one and keep what joins, as resolve_aoi_extent() does for the extent.
        geom = None
        for g in geoms:
            if geom is None:
                geom = g
                continue
            try:
                combined = geom.combine(g)
            except Exception as _exc:
                log_swallowed("tools/covariate_report_dialog.py (_aoi_union_geometry combine)", _exc)
                combined = None
            if combined is not None and not combined.isNull() and not combined.isEmpty():
                geom = combined
    try:
        if geom is None or geom.isNull() or geom.isEmpty():
            return None
        if aoi_layer.crs() != dst_crs:
            geom.transform(QgsCoordinateTransform(aoi_layer.crs(), dst_crs, QgsProject.instance()))
            if geom.isNull() or geom.isEmpty():
                return None
        return geom
    except Exception as _exc:
        log_swallowed("tools/covariate_report_dialog.py (_aoi_union_geometry union)", _exc)
        return None


def _point_inside(engine, aoi_geom, x, y) -> bool:
    """Point-in-AOI test; the prepared engine is the fast path, QgsGeometry.contains the fallback."""
    if engine is not None:
        try:
            return bool(engine.contains(QgsPoint(x, y)))
        except Exception as _exc:
            log_swallowed("tools/covariate_report_dialog.py (_point_inside engine)", _exc)
    try:
        return bool(aoi_geom.contains(QgsPointXY(x, y)))
    except Exception as _exc:
        log_swallowed("tools/covariate_report_dialog.py (_point_inside)", _exc)
        return False


def _reference_cell_centres(layer, extent):
    """(xs, ys) centres of the reference raster's cells inside ``extent`` (its own CRS), or None when unknown.

    More sample points than cells only re-read the same cells, so the grid is
    capped at these centres and the report says so instead of printing a
    sample size the raster cannot support.
    """
    try:
        px = float(layer.rasterUnitsPerPixelX())
        py = float(layer.rasterUnitsPerPixelY())
        full = layer.extent()
        x0 = float(full.xMinimum())
        y1 = float(full.yMaximum())
    except Exception as _exc:
        log_swallowed("tools/covariate_report_dialog.py (_reference_cell_centres)", _exc)
        return None
    if not (px > 0 and py > 0):
        return None
    eps = 1e-9
    i_lo = math.ceil((extent.xMinimum() - x0) / px - 0.5 - eps)
    i_hi = math.floor((extent.xMaximum() - x0) / px - 0.5 + eps)
    j_lo = math.ceil((y1 - extent.yMaximum()) / py - 0.5 - eps)
    j_hi = math.floor((y1 - extent.yMinimum()) / py - 0.5 + eps)
    if i_hi < i_lo or j_hi < j_lo:
        return None
    xs = [x0 + (i + 0.5) * px for i in range(i_lo, i_hi + 1)]
    ys = [y1 - (j + 0.5) * py for j in range(j_hi, j_lo - 1, -1)]  # south to north, like the scan grid
    return xs, ys


def _scope_lines(scope) -> list:
    """Plain-text scope of one run (extent, AOI, grid, categorical inputs) for the report and the CSV."""
    if not scope:
        return []
    lines = []
    ext = scope.get("extent")
    if ext is not None:
        try:
            crs = str(scope.get("crs") or "")
            lines.append(
                f"범위: X {ext.xMinimum():.2f} - {ext.xMaximum():.2f}, Y {ext.yMinimum():.2f} - {ext.yMaximum():.2f}"
                + (f" ({crs})" if crs else "")
            )
        except Exception as _exc:
            log_swallowed("tools/covariate_report_dialog.py (_scope_lines extent)", _exc)
    if scope.get("aoi_name"):
        lines.append(f"AOI: {scope['aoi_name']}" + (" (선택 피처만)" if scope.get("aoi_selected") else "") + " — 폴리곤 내부 표본")
    else:
        lines.append("AOI 없음 — 공통 범위 전체")
    nx, ny = scope.get("grid") or (0, 0)
    scanned = int(scope.get("scanned") or 0)
    n = int(scope.get("n") or 0)
    where = "AOI 폴리곤 내부 격자 점" if scope.get("polygon") else "격자 점"
    lines.append(f"격자 {nx} × {ny}: {where} {scanned:,}점 중 모든 변수가 유효한 표본 {n:,}점")
    if scope.get("capped"):
        cells = int(scope.get("cells") or 0)
        lines.append(f"요청 {int(scope.get('target') or 0):,}점 > 셀 {cells:,}개, 전수 {cells:,}점")
    if scope.get("categorical"):
        lines.append("범주형 래스터 포함, 클래스 코드로 계산됨: " + ", ".join(str(s) for s in scope["categorical"]))
    return lines


def _compute_vif(matrix):
    """VIF per column: 1/(1-R^2) from OLS of each column on the others (+intercept)."""
    n, k = matrix.shape
    vifs = []
    ones = np.ones((n, 1))
    for i in range(k):
        y = matrix[:, i]
        # A (near-)constant column has no variance to explain: VIF is
        # undefined, not "1.0 = fine". NaN renders as "계산불가" downstream.
        if float(np.std(y)) < 1e-12:
            vifs.append(float("nan"))
            continue
        cols = [ones] + [matrix[:, j:j + 1] for j in range(k) if j != i]
        others = np.hstack(cols)
        try:
            beta, *_ = np.linalg.lstsq(others, y, rcond=None)
            pred = others @ beta
            ss_res = float(np.sum((y - pred) ** 2))
            ss_tot = float(np.sum((y - np.mean(y)) ** 2))
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
            vifs.append(1.0 / (1.0 - r2) if r2 < 0.999999 else float("inf"))
        except Exception:
            vifs.append(float("nan"))
    return vifs


class CovariateReportDialog(QtWidgets.QDialog):
    """Correlation + VIF report for a selected raster stack."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        # Remember the last-used inputs between sessions (tools/dialog_memory.py).
        dialog_memory.attach(self, "covariate_report")
        self.iface = iface
        self._setup_ui()
        self._populate_layers()

    def _setup_ui(self):
        self.setWindowTitle("변수 상관/다중공선성 리포트 (Correlation & VIF)")
        try:
            self.setWindowIcon(plugin_icon("covariate.png", "terrain.png"))
        except Exception as _exc:
            log_swallowed("covariate_report_dialog._setup_ui", _exc)

        layout = QtWidgets.QVBoxLayout(self)
        header = QtWidgets.QLabel(
            "<b>변수 상관/다중공선성 리포트</b><br>"
            "예측모델에 넣기 전, 선택한 변수(래스터)들의 <b>상관행렬</b>과 <b>VIF</b>(분산팽창계수)를 계산해 "
            "중복/다중공선성을 점검합니다.<br>"
            "<span style='color:#455a64;'>|r| ≥ 0.7, VIF 5·10은 참고선입니다 — 임계값만으로 변수를 빼지 말고 "
            "표본 크기·효과 크기와 함께 판단하세요(O'Brien 2007).</span>"
        )
        header.setWordWrap(True)
        header.setStyleSheet("background:#f1f8e9; padding:10px; border:1px solid #dcedc8; border-radius:4px;")
        layout.addWidget(header)

        grp = QtWidgets.QGroupBox("1. 변수(래스터) 선택")
        vl = QtWidgets.QVBoxLayout(grp)
        self.listLayers = QtWidgets.QListWidget()
        self.listLayers.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        vl.addWidget(self.listLayers, 1)
        row = QtWidgets.QHBoxLayout()
        b1 = QtWidgets.QPushButton("모두 선택")
        b2 = QtWidgets.QPushButton("모두 해제")
        b3 = QtWidgets.QPushButton("ArchToolkit 결과만")
        b1.clicked.connect(lambda: self._check_all(True))
        b2.clicked.connect(lambda: self._check_all(False))
        b3.clicked.connect(self._check_arch_only)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addWidget(b3)
        row.addStretch(1)
        vl.addLayout(row)
        layout.addWidget(grp, 1)

        grp2 = QtWidgets.QGroupBox("2. 표본 설정")
        form = QtWidgets.QFormLayout(grp2)
        self.spinSamples = QtWidgets.QSpinBox()
        self.spinSamples.setRange(100, 200000)
        self.spinSamples.setValue(3000)
        form.addRow("표본 점 수:", self.spinSamples)
        from qgis.gui import QgsMapLayerComboBox
        self.cmbAoi = QgsMapLayerComboBox(grp2)
        try:
            self.cmbAoi.setFilters(Qgis.LayerFilter.PolygonLayer)
            self.cmbAoi.setAllowEmptyLayer(True)
        except Exception as _exc:
            log_swallowed("covariate_report_dialog._setup_ui", _exc)
        form.addRow("AOI 제한(선택):", self.cmbAoi)
        self.chkAoiSelected = QtWidgets.QCheckBox("AOI 선택 피처만 사용")
        form.addRow("", self.chkAoiSelected)
        layout.addWidget(grp2)

        btn_row = QtWidgets.QHBoxLayout()
        self.btnRun = QtWidgets.QPushButton("리포트 생성")
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
        self.resize(620, 620)

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
            # Pearson/VIF on nominal class codes is statistically meaningless —
            # don't auto-check categorical rasters (geology, slope-position,
            # geochem class), and say why in the label.
            is_categorical = is_categorical_raster_meta(meta)
            label = lyr.name() + (f"   [{meta.get('tool_id')}/{meta.get('kind')}]" if is_arch else "")
            if is_categorical:
                label += "  (범주형 — 상관/VIF 부적합)"
            item = QtWidgets.QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if (is_arch and not is_categorical) else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, lyr.id())
            item.setData(Qt.ItemDataRole.UserRole + 1, bool(is_arch and not is_categorical))
            self.listLayers.addItem(item)
        if self.listLayers.count() == 0:
            item = QtWidgets.QListWidgetItem("(프로젝트에 래스터 레이어가 없습니다)")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.listLayers.addItem(item)

    def _check_all(self, state):
        for i in range(self.listLayers.count()):
            it = self.listLayers.item(i)
            if it.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                it.setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)

    def _check_arch_only(self):
        for i in range(self.listLayers.count()):
            it = self.listLayers.item(i)
            if it.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                it.setCheckState(Qt.CheckState.Checked if bool(it.data(Qt.ItemDataRole.UserRole + 1)) else Qt.CheckState.Unchecked)

    def _selected_layers(self):
        out = []
        project = QgsProject.instance()
        for i in range(self.listLayers.count()):
            it = self.listLayers.item(i)
            if not (it.flags() & Qt.ItemFlag.ItemIsUserCheckable) or it.checkState() != Qt.CheckState.Checked:
                continue
            lyr = project.mapLayer(str(it.data(Qt.ItemDataRole.UserRole) or ""))
            if isinstance(lyr, QgsRasterLayer) and lyr.isValid():
                out.append(lyr)
        return out

    def _on_run(self):
        if np is None:
            push_message(self.iface, "오류", "이 리포트에는 NumPy가 필요합니다(QGIS 기본 포함).", level=2, duration=7)
            return
        layers = self._selected_layers()
        if len(layers) < 2:
            push_message(self.iface, "오류", "변수(래스터)를 2개 이상 선택하세요.", level=2, duration=6)
            return

        dst_crs = layers[0].crs()
        extent = _common_extent(layers, dst_crs)
        if extent is None:
            push_message(self.iface, "오류", "선택한 래스터들의 공통 범위가 없습니다(겹치지 않음).", level=2, duration=8)
            return
        aoi = self.cmbAoi.currentLayer()
        aoi_geom = None
        aoi_name = ""
        if isinstance(aoi, QgsVectorLayer):
            aoi_result = resolve_aoi_extent(
                aoi, selected_only=self.chkAoiSelected.isChecked(), dst_crs=dst_crs)
            if aoi_result.ok:
                # The rectangle only bounds the scan; points are kept only inside
                # the polygon itself (see _sample_matrix).
                aoi_geom = _aoi_union_geometry(aoi, selected_only=self.chkAoiSelected.isChecked(), dst_crs=dst_crs)
                if aoi_geom is None:
                    push_message(self.iface, "오류",
                                 "AOI 폴리곤을 만들 수 없어 표본을 AOI 내부로 제한할 수 없습니다(잘못된 지오메트리일 수 있습니다).",
                                 level=2, duration=10)
                    return
                aoi_name = aoi.name()
                extent = extent.intersect(aoi_result.extent)
                if extent.isEmpty():
                    push_message(self.iface, "오류", "AOI가 공통 범위와 겹치지 않습니다.", level=2, duration=7)
                    return
                if aoi_result.skipped:
                    push_message(self.iface, "주의", aoi_result.message(), level=1, duration=8)
            elif aoi_result.requested_but_failed:
                # Sampling the full common extent instead would silently report
                # correlations for an area the user did not ask about.
                push_message(self.iface, "오류",
                             f"AOI를 사용할 수 없습니다: {aoi_result.message()}",
                             level=2, duration=10)
                return

        target = int(self.spinSamples.value())
        names = _unique_names([lyr.name() for lyr in layers])
        info = {}
        matrix = self._sample_matrix(layers, dst_crs, extent, target, aoi_geom=aoi_geom, info=info)
        if info.get("cancelled"):
            # A cancelled scan covers only the rows reached so far (a strip of the
            # extent); reporting it would present a biased sample as the whole.
            push_message(self.iface, "취소됨", "표본 추출이 취소되어 리포트를 만들지 않았습니다(부분 표본은 사용하지 않음).",
                         level=1, duration=6)
            return
        if matrix is None or matrix.shape[0] < 10:
            n_ok = 0 if matrix is None else int(matrix.shape[0])
            push_message(self.iface, "오류",
                         f"유효 표본이 부족합니다(검사한 점 {int(info.get('scanned') or 0):,}개 중 모든 변수가 유효한 점 {n_ok:,}개).",
                         level=2, duration=8)
            return

        categorical = []
        for name, lyr in zip(names, layers):
            try:
                if is_categorical_raster_meta(get_archtoolkit_layer_metadata(lyr) or {}):
                    categorical.append(name)
            except Exception as _exc:
                log_swallowed("tools/covariate_report_dialog.py (_on_run categorical)", _exc)
        try:
            crs_label = dst_crs.authid()
        except Exception as _exc:
            log_swallowed("tools/covariate_report_dialog.py (_on_run authid)", _exc)
            crs_label = ""
        scope = {
            "extent": QgsRectangle(extent), "crs": crs_label,
            "aoi_name": aoi_name, "aoi_selected": bool(aoi_name) and self.chkAoiSelected.isChecked(),
            "polygon": aoi_geom is not None, "grid": info.get("grid"), "scanned": info.get("scanned"),
            "n": int(matrix.shape[0]), "target": target, "cells": info.get("cells"), "capped": info.get("capped"),
            "categorical": categorical,
        }
        self._last_scope = scope

        corr = np.corrcoef(matrix, rowvar=False)
        vifs = _compute_vif(matrix)
        html = self._build_report_html(names, corr, vifs, matrix.shape[0], scope=scope)
        log_message(f"Covariate report: {len(names)} vars, {matrix.shape[0]} samples", level=0)
        self._show_report(html, names, corr, vifs, matrix.shape[0])
        restore_ui_focus(self)

    def _sample_matrix(self, layers, dst_crs, extent, target, aoi_geom=None, info=None):
        """Deterministic grid scan over the common extent; keep points inside
        ``aoi_geom`` (when given) where ALL layers return a valid value.
        Returns (n_points x n_layers) array, or None.

        The grid never has more points than the first raster has cells in the
        extent: past that it scans the cell centres. ``info`` (a dict) receives
        the grid size, points scanned, the cell cap and whether the scan was
        cancelled; a cancelled scan returns None, never a partial matrix."""
        if info is None:
            info = {}
        info.update({"cancelled": False, "scanned": 0, "capped": False, "cells": None, "grid": (0, 0)})
        try:
            centres = _reference_cell_centres(layers[0], extent)
            cells = len(centres[0]) * len(centres[1]) if centres is not None else None
            info["cells"] = cells
            if cells is not None and target >= cells:
                xs, ys = centres
                info["capped"] = target > cells
            else:
                # grid resolution so that grid cells ~ target (before validity filtering)
                aspect = extent.width() / extent.height() if extent.height() > 0 else 1.0
                ny = max(2, int(round(math.sqrt(max(1, target) / max(aspect, 1e-9)))))
                nx = max(2, int(round(target / ny)))
                if centres is not None:
                    nx = min(nx, len(centres[0]))
                    ny = min(ny, len(centres[1]))
                xs = [extent.xMinimum() + (i + 0.5) * extent.width() / nx for i in range(nx)]
                ys = [extent.yMinimum() + (j + 0.5) * extent.height() / ny for j in range(ny)]
            info["grid"] = (len(xs), len(ys))

            engine = None
            if aoi_geom is not None:
                try:
                    engine = QgsGeometry.createGeometryEngine(aoi_geom.constGet())
                    engine.prepareGeometry()
                except Exception as _exc:
                    log_swallowed("tools/covariate_report_dialog.py (_sample_matrix engine)", _exc)
                    engine = None

            providers = [lyr.dataProvider() for lyr in layers]
            transforms = []
            for lyr in layers:
                if lyr.crs() != dst_crs:
                    transforms.append(QgsCoordinateTransform(dst_crs, lyr.crs(), QgsProject.instance()))
                else:
                    transforms.append(None)

            rows = []
            progress = QtWidgets.QProgressDialog("표본 추출 중…", "취소", 0, len(ys), self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            for jy, y in enumerate(ys):
                if progress.wasCanceled():
                    info["cancelled"] = True
                    break
                progress.setValue(jy)
                QtWidgets.QApplication.processEvents()
                for x in xs:
                    if aoi_geom is not None and not _point_inside(engine, aoi_geom, x, y):
                        continue
                    info["scanned"] += 1
                    vals = []
                    ok = True
                    for pi, prov in enumerate(providers):
                        pt = QgsPointXY(x, y)
                        ct = transforms[pi]
                        if ct is not None:
                            try:
                                pt = ct.transform(pt)
                            except Exception:
                                ok = False
                                break
                        try:
                            val, res = prov.sample(pt, 1)
                        except Exception:
                            ok = False
                            break
                        if not res or val is None or not np.isfinite(val):
                            ok = False
                            break
                        vals.append(float(val))
                    if ok:
                        rows.append(vals)
            if progress.wasCanceled():
                info["cancelled"] = True
            progress.close()
            if info["cancelled"] or not rows:
                return None
            return np.asarray(rows, dtype="float64")
        except Exception as e:
            log_exception("Covariate sampling error", e)
            return None

    def _build_report_html(self, names, corr, vifs, n_samples, scope=None):
        def esc(s):
            return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    .replace("'", "&#39;").replace('"', "&quot;"))

        def short(s, width=24):
            s = str(s)
            return s if len(s) <= width else s[:width - 1] + "…"
        k = len(names)
        parts = [
            "<html><head><meta charset='utf-8'></head><body style='font-family:Sans-Serif;'>",
            f"<h3>변수 상관/다중공선성 리포트</h3><p>변수 {k}개 · 유효 표본 {n_samples:,}점</p>",
        ]
        for line in _scope_lines(scope):
            color = "#b2182b" if line.startswith("범주형") else "#455a64"
            parts.append(f"<p style='color:{color};margin:2px 0;'>{esc(line)}</p>")
        parts += [
            "<h4>VIF (분산팽창계수)</h4>",
            "<table border='1' cellspacing='0' cellpadding='4'><tr><th>변수</th><th>VIF</th><th>판정</th></tr>",
        ]
        for name, v in zip(names, vifs):
            if v != v:  # nan
                flag, color = "계산불가", "#999"
            elif v >= _VIF_BAD:
                flag, color = "높음(≥10) — 참고선. O'Brien 2007: 표본 크기·효과 크기와 함께 판단", "#b2182b"
            elif v >= _VIF_WARN:
                flag, color = "주의(≥5) — 참고선", "#ef8a62"
            else:
                flag, color = "양호", "#1a9850"
            vtxt = "∞" if v == float("inf") else (f"{v:.2f}" if v == v else "-")
            parts.append(f"<tr><td>{esc(name)}</td><td align='right'>{vtxt}</td>"
                         f"<td style='color:{color}'>{flag}</td></tr>")
        parts.append("</table>")

        parts.append("<h4>상관행렬 (Pearson r)</h4>")
        parts.append("<table border='1' cellspacing='0' cellpadding='3'><tr><th></th>"
                     + "".join(f"<th title='{esc(n)}'>{esc(short(n))}</th>" for n in names) + "</tr>")
        for i in range(k):
            parts.append(f"<tr><th align='left'>{esc(names[i])}</th>")
            for j in range(k):
                r = float(corr[i, j])
                if i == j:
                    cell = "<td align='center'>1</td>"
                elif r != r:  # NaN (a constant/degenerate variable) — mirror the VIF path
                    cell = "<td align='center' style='color:#999'>계산불가</td>"
                else:
                    hot = abs(r) >= _HIGH_CORR
                    style = "background:#fddbc7;font-weight:bold;" if hot else ""
                    cell = f"<td align='right' style='{style}'>{r:+.2f}</td>"
                parts.append(cell)
            parts.append("</tr>")
        parts.append("</table>")
        parts.append(
            "<p style='color:#455a64'>|r| ≥ 0.7(음영), VIF 5·10은 참고선입니다(O'Brien 2007). "
            "임계값만으로 변수를 빼지 말고 표본 크기·효과 크기·해석 가능성과 함께 판단하세요. "
            "중복이 확인되면 쌍 중 해석 가능한 쪽을 남기거나 결합하는 것을 검토합니다.</p>"
        )
        parts.append("</body></html>")
        return "".join(parts)

    def _show_report(self, html, names, corr, vifs, n_samples):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("상관/VIF 리포트")
        dlg.resize(720, 620)
        v = QtWidgets.QVBoxLayout(dlg)
        browser = QtWidgets.QTextBrowser(dlg)
        browser.setHtml(html)
        v.addWidget(browser, 1)
        rr = QtWidgets.QHBoxLayout()
        btn_csv = QtWidgets.QPushButton("CSV 저장", dlg)
        btn_close = QtWidgets.QPushButton("닫기", dlg)
        rr.addStretch(1)
        rr.addWidget(btn_csv)
        rr.addWidget(btn_close)
        v.addLayout(rr)
        btn_close.clicked.connect(dlg.accept)
        scope = getattr(self, "_last_scope", None)
        btn_csv.clicked.connect(lambda: self._save_csv(names, corr, vifs, scope))
        dlg.exec()

    def _save_csv(self, names, corr, vifs, scope=None):
        if scope is None:
            scope = getattr(self, "_last_scope", None)
        path, _flt = QtWidgets.QFileDialog.getSaveFileName(
            self, "리포트 CSV 저장", "covariate_report.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                lines = _scope_lines(scope)
                if lines:
                    w.writerow(["# scope"])
                    for line in lines:
                        w.writerow([f"# {line}"])
                    w.writerow([])
                w.writerow(["# VIF"])
                w.writerow(["variable", "vif"])
                for name, v in zip(names, vifs):
                    w.writerow([name, ("inf" if v == float("inf") else (f"{v:.4f}" if v == v else ""))])
                w.writerow([])
                w.writerow(["# correlation matrix"])
                w.writerow([""] + list(names))
                for i, name in enumerate(names):
                    w.writerow([name] + [f"{float(corr[i, j]):.4f}" for j in range(len(names))])
            push_message(self.iface, "완료", f"저장했습니다: {path}", level=0, duration=6)
        except Exception as e:
            push_message(self.iface, "오류", f"CSV 저장 실패: {e}", level=2, duration=7)

    def _on_help(self):
        html = (
            "<h3>변수 상관/다중공선성 리포트</h3>"
            "<p>예측모델(MaxEnt 등)에 변수를 넣기 전, 변수들끼리 얼마나 겹치는지(다중공선성) 점검합니다. "
            "겹치는 변수가 많으면 변수기여도 해석이 왜곡되고 과적합 위험이 커집니다.</p>"
            "<h4>지표</h4>"
            "<ul>"
            "<li><b>상관행렬(r)</b>: |r| ≥ 0.7이면 두 변수가 강하게 겹칩니다.</li>"
            "<li><b>VIF</b> = 1/(1−R²): 한 변수를 나머지로 회귀했을 때의 설명력 기반. "
            "5와 10은 참고선입니다. O'Brien(2007)은 임계값을 기계적으로 적용해 변수를 버리지 말고 "
            "표본 크기·효과 크기와 함께 판단하라고 권합니다.</li>"
            "</ul>"
            "<h4>방법</h4>"
            "<p>공통 범위에서 격자 표본점을 뽑아 모든 변수가 유효한 점만 사용합니다. "
            "격자/CRS가 달라도 각 래스터를 좌표변환해 샘플링합니다.</p>"
            "<p>AOI를 고르면 AOI 폴리곤 내부의 점만 사용합니다(사각 범위가 아님). "
            "표본 점 수가 첫 래스터의 셀 수보다 많으면 셀 중심을 한 번씩만 읽습니다(전수). "
            "표본 추출을 취소하면 리포트를 만들지 않습니다.</p>"
            "<p style='color:#455a64'>NumPy만 사용(QGIS 기본 포함).</p>"
        )
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            show_help_dialog(parent=self, title="상관/VIF 리포트 도움말", html=html, plugin_dir=plugin_dir, tool_id="covariate_report")
        except Exception as _exc:
            log_swallowed("tools/covariate_report_dialog.py:477 (_on_help)", _exc)
