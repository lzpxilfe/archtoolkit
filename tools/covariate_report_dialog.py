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
This tool samples the selected rasters at shared random points and reports:
- a Pearson correlation matrix (flagging |r| >= 0.7), and
- Variance Inflation Factors (VIF = 1 / (1 - R^2_i); flagging VIF >= 5 / >= 10).

It is an *analysis of your variables*, not a variable generator.

Design: NumPy + QGIS raster sampling only (both ship with QGIS), per
DEVELOPMENT.md. Sampling handles differing grids/CRS via each provider's own
sample() with coordinate transforms.
"""

from __future__ import annotations

import csv
import os
from typing import Optional

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .help_dialog import show_help_dialog
from .utils import (
    get_archtoolkit_layer_metadata,
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
        try:
            e = lyr.extent()
            if lyr.crs() != dst_crs:
                ct = QgsCoordinateTransform(lyr.crs(), dst_crs, QgsProject.instance())
                e = ct.transformBoundingBox(e)
        except Exception:
            continue
        if rect is None:
            rect = QgsRectangle(e)
        else:
            rect = rect.intersect(e)
    if rect is None or rect.isEmpty():
        return None
    return rect


def _aoi_extent_in_crs(aoi_layer, *, selected_only, dst_crs) -> Optional[QgsRectangle]:
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
        self.iface = iface
        self._setup_ui()
        self._populate_layers()

    def _setup_ui(self):
        self.setWindowTitle("변수 상관/다중공선성 리포트 (Correlation & VIF)")
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
            "<b>변수 상관/다중공선성 리포트</b><br>"
            "예측모델에 넣기 전, 선택한 변수(래스터)들의 <b>상관행렬</b>과 <b>VIF</b>(분산팽창계수)를 계산해 "
            "중복/다중공선성을 점검합니다.<br>"
            "<span style='color:#455a64;'>|r| ≥ 0.7 또는 VIF ≥ 5는 변수 중복 신호 — 하나를 빼는 것을 고려하세요.</span>"
        )
        header.setWordWrap(True)
        header.setStyleSheet("background:#f1f8e9; padding:10px; border:1px solid #dcedc8; border-radius:4px;")
        layout.addWidget(header)

        grp = QtWidgets.QGroupBox("1. 변수(래스터) 선택")
        vl = QtWidgets.QVBoxLayout(grp)
        self.listLayers = QtWidgets.QListWidget()
        self.listLayers.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
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
            from qgis.core import QgsMapLayerProxyModel
            try:
                self.cmbAoi.setFilters(QgsMapLayerProxyModel.Filter.PolygonLayer)
            except Exception:
                self.cmbAoi.setFilters(QgsMapLayerProxyModel.PolygonLayer)
            self.cmbAoi.setAllowEmptyLayer(True)
        except Exception:
            pass
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
            kind0 = str(meta.get("kind") or "").lower()
            units0 = str(meta.get("units") or "").lower()
            tool0 = str(meta.get("tool_id") or "").lower()
            is_categorical = (
                units0 in ("class", "classes", "category")
                or "class" in kind0
                or "slope_position" in kind0
                or "geology" in tool0
            )
            label = lyr.name() + (f"   [{meta.get('tool_id')}/{meta.get('kind')}]" if is_arch else "")
            if is_categorical:
                label += "  (범주형 — 상관/VIF 부적합)"
            item = QtWidgets.QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if (is_arch and not is_categorical) else Qt.Unchecked)
            item.setData(Qt.UserRole, lyr.id())
            item.setData(Qt.UserRole + 1, bool(is_arch and not is_categorical))
            self.listLayers.addItem(item)
        if self.listLayers.count() == 0:
            item = QtWidgets.QListWidgetItem("(프로젝트에 래스터 레이어가 없습니다)")
            item.setFlags(Qt.NoItemFlags)
            self.listLayers.addItem(item)

    def _check_all(self, state):
        for i in range(self.listLayers.count()):
            it = self.listLayers.item(i)
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(Qt.Checked if state else Qt.Unchecked)

    def _check_arch_only(self):
        for i in range(self.listLayers.count()):
            it = self.listLayers.item(i)
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(Qt.Checked if bool(it.data(Qt.UserRole + 1)) else Qt.Unchecked)

    def _selected_layers(self):
        out = []
        project = QgsProject.instance()
        for i in range(self.listLayers.count()):
            it = self.listLayers.item(i)
            if not (it.flags() & Qt.ItemIsUserCheckable) or it.checkState() != Qt.Checked:
                continue
            lyr = project.mapLayer(str(it.data(Qt.UserRole) or ""))
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
        if isinstance(aoi, QgsVectorLayer):
            aoi_ext = _aoi_extent_in_crs(aoi, selected_only=self.chkAoiSelected.isChecked(), dst_crs=dst_crs)
            if aoi_ext is not None and not aoi_ext.isEmpty():
                extent = extent.intersect(aoi_ext)
                if extent.isEmpty():
                    push_message(self.iface, "오류", "AOI가 공통 범위와 겹치지 않습니다.", level=2, duration=7)
                    return

        target = int(self.spinSamples.value())
        names = [lyr.name() for lyr in layers]
        matrix = self._sample_matrix(layers, dst_crs, extent, target)
        if matrix is None or matrix.shape[0] < 10:
            push_message(self.iface, "오류", "유효 표본이 부족합니다(모든 변수가 유효한 점이 적음).", level=2, duration=8)
            return

        corr = np.corrcoef(matrix, rowvar=False)
        vifs = _compute_vif(matrix)
        html = self._build_report_html(names, corr, vifs, matrix.shape[0])
        log_message(f"Covariate report: {len(names)} vars, {matrix.shape[0]} samples", level=0)
        self._show_report(html, names, corr, vifs, matrix.shape[0])
        restore_ui_focus(self)

    def _sample_matrix(self, layers, dst_crs, extent, target):
        """Deterministic grid scan over the common extent; keep points where ALL
        layers return a valid value. Returns (n_points x n_layers) array."""
        try:
            import math
            # grid resolution so that grid cells ~ target (before validity filtering)
            aspect = extent.width() / extent.height() if extent.height() > 0 else 1.0
            ny = max(2, int(round(math.sqrt(max(1, target) / max(aspect, 1e-9)))))
            nx = max(2, int(round(target / ny)))
            xs = [extent.xMinimum() + (i + 0.5) * extent.width() / nx for i in range(nx)]
            ys = [extent.yMinimum() + (j + 0.5) * extent.height() / ny for j in range(ny)]

            providers = [lyr.dataProvider() for lyr in layers]
            transforms = []
            for lyr in layers:
                if lyr.crs() != dst_crs:
                    transforms.append(QgsCoordinateTransform(dst_crs, lyr.crs(), QgsProject.instance()))
                else:
                    transforms.append(None)

            rows = []
            progress = QtWidgets.QProgressDialog("표본 추출 중…", "취소", 0, len(ys), self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            for jy, y in enumerate(ys):
                if progress.wasCanceled():
                    break
                progress.setValue(jy)
                QtWidgets.QApplication.processEvents()
                for x in xs:
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
            progress.close()
            if not rows:
                return None
            return np.asarray(rows, dtype="float64")
        except Exception as e:
            log_exception("Covariate sampling error", e)
            return None

    def _build_report_html(self, names, corr, vifs, n_samples):
        def esc(s):
            return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        k = len(names)
        parts = [
            "<html><head><meta charset='utf-8'></head><body style='font-family:Sans-Serif;'>",
            f"<h3>변수 상관/다중공선성 리포트</h3><p>변수 {k}개 · 유효 표본 {n_samples:,}점</p>",
            "<h4>VIF (분산팽창계수)</h4>",
            "<table border='1' cellspacing='0' cellpadding='4'><tr><th>변수</th><th>VIF</th><th>판정</th></tr>",
        ]
        for name, v in zip(names, vifs):
            if v != v:  # nan
                flag, color = "계산불가", "#999"
            elif v >= _VIF_BAD:
                flag, color = "높음(≥10) — 제거 권장", "#b2182b"
            elif v >= _VIF_WARN:
                flag, color = "주의(≥5)", "#ef8a62"
            else:
                flag, color = "양호", "#1a9850"
            vtxt = "∞" if v == float("inf") else (f"{v:.2f}" if v == v else "-")
            parts.append(f"<tr><td>{esc(name)}</td><td align='right'>{vtxt}</td>"
                         f"<td style='color:{color}'>{flag}</td></tr>")
        parts.append("</table>")

        parts.append("<h4>상관행렬 (Pearson r)</h4>")
        parts.append("<table border='1' cellspacing='0' cellpadding='3'><tr><th></th>"
                     + "".join(f"<th>{esc(n[:10])}</th>" for n in names) + "</tr>")
        for i in range(k):
            parts.append(f"<tr><th>{esc(names[i][:14])}</th>")
            for j in range(k):
                r = float(corr[i, j])
                if i == j:
                    cell = "<td align='center'>1</td>"
                else:
                    hot = abs(r) >= _HIGH_CORR
                    style = "background:#fddbc7;font-weight:bold;" if hot else ""
                    cell = f"<td align='right' style='{style}'>{r:+.2f}</td>"
                parts.append(cell)
            parts.append("</tr>")
        parts.append("</table>")
        parts.append(
            "<p style='color:#455a64'>|r| ≥ 0.7(음영) 또는 VIF ≥ 5는 변수 중복 신호입니다. "
            "쌍 중 하나를 빼거나 결합해 다중공선성을 줄이면 모델 변수기여도 해석이 안정됩니다.</p>"
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
        btn_csv.clicked.connect(lambda: self._save_csv(names, corr, vifs))
        dlg.exec_()

    def _save_csv(self, names, corr, vifs):
        path, _flt = QtWidgets.QFileDialog.getSaveFileName(
            self, "리포트 CSV 저장", "covariate_report.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
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
            "VIF ≥ 5 주의, ≥ 10 제거 권장.</li>"
            "</ul>"
            "<h4>방법</h4>"
            "<p>공통 범위에서 격자 표본점을 뽑아 모든 변수가 유효한 점만 사용합니다. "
            "격자/CRS가 달라도 각 래스터를 좌표변환해 샘플링합니다.</p>"
            "<p style='color:#455a64'>NumPy만 사용(QGIS 기본 포함).</p>"
        )
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            show_help_dialog(parent=self, title="상관/VIF 리포트 도움말", html=html, plugin_dir=plugin_dir)
        except Exception:
            pass
