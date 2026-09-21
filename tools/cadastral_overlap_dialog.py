# -*- coding: utf-8 -*-

"""
지적도 중첩 면적표 (Cadastral Overlap Table)

입력:
- 지적도(필지) 폴리곤 레이어
- 조사지역(면/경계) 폴리곤 레이어

출력:
- 조사지역과 겹치는 지적도 폴리곤(클립) 레이어(메모리)
  - 원본 지적 속성 + 면적 필드 추가
    - parcel_m2: 필지 전체면적(㎡)
    - in_aoi_m2: 조사지역 내 포함면적(㎡)
    - in_aoi_pct: 포함비율(%)

의도:
한국 고고학 조사 실무에서 “조사지역 내 어떤 필지가 얼마나 포함되는지”를 빠르게 표로 만들기 위한 도구.
"""

import math
import os
import uuid
from typing import Iterable, List, Optional, Tuple

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsMapLayerProxyModel,
    QgsProject,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox

from .live_log_dialog import ensure_live_log_dialog
from .utils import log_swallowed, log_message, push_message, restore_ui_focus
from .utils import set_archtoolkit_layer_metadata
from .help_dialog import show_help_dialog
from . import dialog_memory
from .i18n import is_english_ui


def _is_geographic_crs(crs) -> bool:
    """True when `crs` is measured in degrees (planar areas would be square degrees)."""
    try:
        return bool(crs is not None and crs.isValid() and crs.isGeographic())
    except Exception as _exc:
        log_swallowed("cadastral_overlap_dialog._is_geographic_crs", _exc)
        return False


def _will_use_ellipsoid(da: QgsDistanceArea) -> bool:
    """True when `da` is actually configured to measure on an ellipsoid.

    Guarded with hasattr/try because willUseEllipsoid() is not exposed by every
    QGIS build. When we cannot tell, assume the measurement is sound: this check
    exists to reject a bad number, never to zero out a correct one.
    """
    try:
        if not hasattr(da, "willUseEllipsoid"):
            return True
        return bool(da.willUseEllipsoid())
    except Exception as _exc:
        log_swallowed("cadastral_overlap_dialog._will_use_ellipsoid", _exc)
        return True


def _safe_make_valid(geom: QgsGeometry) -> QgsGeometry:
    try:
        if geom is None or geom.isEmpty():
            return geom
        if geom.isGeosValid():
            return geom
    except Exception as _exc:
        log_swallowed("tools/cadastral_overlap_dialog.py:58 (_safe_make_valid)", _exc)
    try:
        mv = geom.makeValid()
        if mv and (not mv.isEmpty()):
            return mv
    except Exception as _exc:
        log_swallowed("tools/cadastral_overlap_dialog.py:64 (_safe_make_valid)", _exc)
    return geom


def _iter_layer_geoms(layer: QgsVectorLayer, *, selected_only: bool) -> List[QgsGeometry]:
    geoms: List[QgsGeometry] = []
    feats: Iterable[QgsFeature]
    if selected_only and layer.selectedFeatureCount() > 0:
        feats = layer.selectedFeatures()
    else:
        feats = layer.getFeatures()
    for f in feats:
        _skip_77 = False
        try:
            g = f.geometry()
            if g and (not g.isEmpty()):
                geoms.append(_safe_make_valid(g))
        except Exception as _exc:
            log_swallowed("cadastral_overlap_dialog._iter_layer_geoms", _exc)
            log_swallowed("tools/cadastral_overlap_dialog.py:81 (_iter_layer_geoms)", _exc)
            _skip_77 = True
        if _skip_77:
            continue
    return geoms


def _unary_union(geoms: List[QgsGeometry]) -> Optional[QgsGeometry]:
    if not geoms:
        return None
    if len(geoms) == 1:
        return geoms[0]
    try:
        return QgsGeometry.unaryUnion(geoms)
    except Exception:
        try:
            # Fallback: iterative combine
            out = geoms[0]
            for g in geoms[1:]:
                out = out.combine(g)
            return out
        except Exception:
            return None


class CadastralOverlapDialog(QtWidgets.QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        # Remember the last-used inputs between sessions (tools/dialog_memory.py).
        dialog_memory.attach(self, "cadastral_overlap")
        self.iface = iface
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("지적도 중첩 면적표 (Cadastral Overlap) - ArchToolkit")
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            icon_path = None
            for icon_name in ("jijuk.png", "jijuk.jpg", "jijuk.jpeg", "icon.png"):
                p = os.path.join(plugin_dir, icon_name)
                if os.path.exists(p):
                    icon_path = p
                    break
            if icon_path and os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception as _exc:
            log_swallowed("cadastral_overlap_dialog._setup_ui", _exc)

        layout = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel(
            "<b>지적도 중첩 면적표</b><br>"
            "조사지역 폴리곤이 지적도(필지) 폴리곤을 어느 면적만큼 포함하는지 계산하여<br>"
            "클립(모자이크) 레이어 + 속성테이블(면적/비율)을 생성합니다."
        )
        header.setWordWrap(True)
        header.setStyleSheet("background:#e8f5e9; padding:10px; border:1px solid #c8e6c9; border-radius:4px;")
        layout.addWidget(header)

        notice = QtWidgets.QLabel(
            "<b>주의</b>: 연속지적도/공간정보 데이터는 <b>참고용</b>입니다.<br>"
            "법적 효력이 필요하거나 경계/면적이 중요한 경우, 관할 <b>시·군·구청(시청/구청)</b>에서 "
            "발급받은 지적도/토지(임야)대장 등 <b>공식 자료</b>를 반드시 확인하세요."
        )
        notice.setWordWrap(True)
        notice.setStyleSheet("background:#fff3e0; padding:10px; border:1px solid #ffe0b2; border-radius:4px; color:#e65100;")
        layout.addWidget(notice)

        grp = QtWidgets.QGroupBox("1. 입력 레이어")
        form = QtWidgets.QFormLayout(grp)

        self.cmbCadastral = QgsMapLayerComboBox(grp)
        # QGIS API compatibility: Filter may be scoped or unscoped depending on build.
        try:
            poly_filter = QgsMapLayerProxyModel.Filter.PolygonLayer
        except Exception:
            poly_filter = QgsMapLayerProxyModel.PolygonLayer
        self.cmbCadastral.setFilters(poly_filter)
        self.cmbSurvey = QgsMapLayerComboBox(grp)
        self.cmbSurvey.setFilters(poly_filter)

        self.chkCadastralSelected = QtWidgets.QCheckBox("지적도: 선택 피처만 사용")
        self.chkSurveySelected = QtWidgets.QCheckBox("조사지역: 선택 피처만 사용")
        self.chkSurveySelected.setChecked(True)
        self.chkSplitBySurveyFeature = QtWidgets.QCheckBox("조사지역 피처별로 결과 레이어 분리")
        self.chkSplitBySurveyFeature.setChecked(False)

        form.addRow("지적도(필지) 레이어", self.cmbCadastral)
        form.addRow("", self.chkCadastralSelected)
        form.addRow("조사지역 레이어", self.cmbSurvey)
        form.addRow("", self.chkSurveySelected)
        form.addRow("", self.chkSplitBySurveyFeature)
        layout.addWidget(grp)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        self.btnRun = QtWidgets.QPushButton("실행")
        self.btnHelp = QtWidgets.QPushButton("도움말")
        self.btnClose = QtWidgets.QPushButton("닫기")
        btn_row.addWidget(self.btnRun)
        btn_row.addWidget(self.btnHelp)
        btn_row.addWidget(self.btnClose)
        layout.addLayout(btn_row)

        self.btnRun.clicked.connect(self.run)
        self.btnClose.clicked.connect(self.reject)
        self.btnHelp.clicked.connect(self._on_help)

        # Tooltips (compact UI, detailed info on hover)
        self.cmbCadastral.setToolTip("조사 범위와 겹치는 지적도(필지) 폴리곤 레이어를 선택하세요.")
        self.cmbSurvey.setToolTip("조사 범위를 나타내는 폴리곤 레이어를 선택하세요. 여러 피처면 합집합으로 처리합니다.")
        self.chkCadastralSelected.setToolTip("체크하면 지적도 레이어에서 선택한 피처만 대상으로 계산합니다.")
        self.chkSurveySelected.setToolTip("체크하면 조사지역 레이어에서 선택한 피처만 합집합(AOI)으로 사용합니다.")
        self.chkSplitBySurveyFeature.setToolTip(
            "조사지역 레이어에 폴리곤 피처가 여러 개라면, 피처(폴리곤)마다 결과 레이어를 따로 생성합니다.\n"
            "해당 폴리곤별로 속성테이블을 분리해서 보고 싶을 때 사용하세요."
        )

    def _on_help(self):
        html = """
<h3>지적도 중첩 면적표(Cadastral Overlap) 도움말</h3>
<p>
조사지역(AOI)과 지적도(필지) 폴리곤의 교차 면적을 계산해,
필지별로 “전체면적 / AOI 포함면적 / 포함비율(%)”을 속성으로 저장한 결과 레이어를 생성합니다.
</p>

<h4>입력</h4>
<ul>
  <li><b>지적도(필지) 레이어</b>: 폴리곤</li>
  <li><b>조사지역 레이어</b>: 폴리곤(AOI)</li>
</ul>

<h4>출력(속성 예시)</h4>
<ul>
  <li><code>parcel_m2</code>: 필지 전체면적(㎡)</li>
  <li><code>in_aoi_m2</code>: AOI 포함면적(㎡)</li>
  <li><code>in_aoi_pct</code>: 포함비율(%)</li>
</ul>

<h4>주의</h4>
<ul>
  <li>연속지적도/공간정보는 <b>참고용</b>입니다. 법적 효력이 필요한 경우 관공서(시청/구청 등)에서 발급받은 <b>공식 지적도</b>로 확인하세요.</li>
  <li>면적 계산은 CRS/단위에 영향받습니다(가능하면 미터 단위 투영좌표계 권장).</li>
</ul>
"""
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            show_help_dialog(parent=self, title="Cadastral Overlap 도움말", html=html, plugin_dir=plugin_dir, tool_id="cadastral_overlap")
        except Exception as _exc:
            log_swallowed("tools/cadastral_overlap_dialog.py:226 (_on_help)", _exc)

    def _validate_layer(self, layer, *, name: str) -> Optional[QgsVectorLayer]:
        if layer is None or (not layer.isValid()):
            push_message(self.iface, "오류", f"{name} 레이어를 선택해주세요.", level=2)
            restore_ui_focus(self)
            return None
        if layer.type() != layer.VectorLayer:
            push_message(self.iface, "오류", f"{name}는 벡터 레이어여야 합니다.", level=2)
            restore_ui_focus(self)
            return None
        if layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            push_message(self.iface, "오류", f"{name}는 폴리곤 레이어여야 합니다.", level=2)
            restore_ui_focus(self)
            return None
        return layer

    def _distance_area(self, crs) -> QgsDistanceArea:
        da = QgsDistanceArea()
        try:
            da.setSourceCrs(crs, QgsProject.instance().transformContext())
        except Exception as _exc:
            log_swallowed("tools/cadastral_overlap_dialog.py:248 (_distance_area)", _exc)
        try:
            raw_ell = QgsProject.instance().ellipsoid()
            ell = str(raw_ell if raw_ell is not None else "").strip()
            # A blank or "NONE" ellipsoid tells QGIS to measure planar areas in
            # the source CRS units. On a geographic CRS that is SQUARE DEGREES,
            # and measureArea() returns them without raising, so the planar
            # fallback in _area_m2 never sees the problem. Substitute a real
            # ellipsoid so an ellipsoidal measurement is genuinely performed;
            # every other case keeps honouring whatever the project is
            # configured with.
            if ((not ell) or ell.upper() == "NONE") and _is_geographic_crs(crs):
                ell = "WGS84"
                log_message(
                    "CadastralOverlap: 프로젝트 타원체가 비어 있거나 'NONE'이고 레이어가 지리좌표계여서 "
                    "면적 계산에 WGS84 타원체를 대신 사용합니다.",
                    level=Qgis.Warning,
                )
            # A blank ellipsoid on a PROJECTED CRS is deliberately left alone:
            # skipping setEllipsoid() keeps QgsDistanceArea on its planar
            # default, which is already the correct square-metre measurement
            # there. Forcing WGS84 in would quietly swap a projected area for a
            # geodesic one, which is outside what the geographic-CRS fix above
            # is meant to change.
            if ell:
                da.setEllipsoid(ell)
        except Exception as _exc:
            log_swallowed("tools/cadastral_overlap_dialog.py:254 (_distance_area)", _exc)
        return da

    def _area_m2(self, da: QgsDistanceArea, geom: QgsGeometry, crs=None) -> float:
        """Ellipsoidal area in square metres.

        The planar fallback is only reached when the ellipsoidal measurement
        fails, and it returns the geometry's area in *layer units*. For a
        projected metre CRS that is the right number; for a geographic one it
        is square degrees, and writing that into a column called `parcel_m2`
        would be a wrong figure presented as a measurement. So the fallback is
        used only when the units are metres, and otherwise the row reports 0
        with a logged warning.

        The willUseEllipsoid() check below covers the case the try/except
        cannot: with no ellipsoid in effect, measureArea() does not fail on a
        geographic CRS, it succeeds and returns square degrees, which
        convertAreaMeasurement() then rescales by a nominal degree-to-metre
        factor (~25% too large at Korean latitudes). That is a wrong figure
        presented as a measurement, so it is routed to the same "report 0 with
        a logged warning" path rather than into the parcel_m2 column.
        """
        if geom is None or geom.isEmpty():
            return 0.0
        degrees_not_ellipsoidal = _is_geographic_crs(crs) and not _will_use_ellipsoid(da)
        if not degrees_not_ellipsoidal:
            try:
                a = float(da.measureArea(geom))
                return float(da.convertAreaMeasurement(a, QgsUnitTypes.AreaSquareMeters))
            except Exception as _exc:
                log_swallowed("cadastral_overlap_dialog._area_m2", _exc)
        try:
            if crs is not None and crs.isValid() and not crs.isGeographic():
                if crs.mapUnits() == QgsUnitTypes.DistanceMeters:
                    return float(geom.area())
            log_message(
                "면적을 타원체 기준으로 계산하지 못했고 레이어 단위가 미터가 아니어서 "
                "0으로 기록합니다(제곱도를 ㎡로 적지 않기 위함).",
                level=Qgis.Warning,
            )
        except Exception as _exc:
            log_swallowed("cadastral_overlap_dialog._area_m2", _exc)
        return 0.0

    def run(self):
        use_en = is_english_ui()
        cad = self._validate_layer(self.cmbCadastral.currentLayer(), name="지적도")
        if cad is None:
            return
        survey = self._validate_layer(self.cmbSurvey.currentLayer(), name="조사지역")
        if survey is None:
            return

        # Live log window
        ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)

        cad_sel = bool(self.chkCadastralSelected.isChecked())
        survey_sel = bool(self.chkSurveySelected.isChecked())
        try:
            split_by_feature = bool(self.chkSplitBySurveyFeature.isChecked())
        except Exception:
            split_by_feature = False

        # "선택 피처만" with an empty selection silently processed the WHOLE
        # layer — a user whose selection was cleared got a full-layer result
        # while believing it was restricted. Say so explicitly.
        try:
            notices = []
            if survey_sel and survey.selectedFeatureCount() == 0:
                notices.append("조사구역")
            if cad_sel and cad.selectedFeatureCount() == 0:
                notices.append("지적")
            if notices:
                push_message(
                    self.iface,
                    "알림",
                    f"{'/'.join(notices)} 레이어에 선택된 피처가 없어 전체 피처로 계산합니다.",
                    level=1,
                    duration=7,
                )
        except Exception as _exc:
            log_swallowed("cadastral_overlap_dialog.run", _exc)

        # A geographic input cannot fail loudly: measureArea() just hands back
        # square degrees. The overlap geometry stays usable, but the area table
        # this tool exists to produce does not, so warn without blocking.
        try:
            geo_names = []
            if _is_geographic_crs(cad.crs()):
                geo_names.append("지적도")
            if _is_geographic_crs(survey.crs()):
                geo_names.append("조사지역")
            if geo_names:
                push_message(
                    self.iface,
                    "주의",
                    f"{'/'.join(geo_names)} 레이어가 지리좌표계(도)입니다. 면적표를 신뢰하려면 "
                    "미터 단위 투영좌표계(예: EPSG:5186)로 재투영한 뒤 실행하세요.",
                    level=1,
                    duration=10,
                )
        except Exception as _exc:
            log_swallowed("cadastral_overlap_dialog.run", _exc)

        cad_crs = cad.crs()
        da = self._distance_area(cad_crs)

        # Transform survey CRS -> cadastral CRS if needed. A failed transform
        # must ABORT: silently keeping the untransformed geometry made every
        # intersection empty and reported "겹침 없음" as a successful result.
        ct = None
        if survey.crs() != cad_crs:
            try:
                ct = QgsCoordinateTransform(survey.crs(), cad_crs, QgsProject.instance())
            except Exception as e:
                log_message(f"CadastralOverlap: failed to build CRS transform (survey -> cad): {e}", level=Qgis.Warning)
                push_message(
                    self.iface,
                    "오류",
                    "조사구역과 지적 레이어의 좌표계 변환을 만들 수 없습니다. 두 레이어의 CRS를 확인하세요.",
                    level=2,
                    duration=8,
                )
                return

        # Output fields: cadastral + computed
        base_fields = list(cad.fields())
        base_fields.append(QgsField("parcel_m2", QVariant.Double))
        base_fields.append(QgsField("in_aoi_m2", QVariant.Double))
        base_fields.append(QgsField("in_aoi_pct", QVariant.Double))

        def create_output_layer(name: str) -> QgsVectorLayer:
            out = QgsVectorLayer(f"Polygon?crs={cad_crs.authid()}", name, "memory")
            pr = out.dataProvider()
            pr.addAttributes(base_fields)
            out.updateFields()
            try:
                def _set_alias(field_name: str, alias: str):
                    idx = int(out.fields().indexFromName(field_name))
                    if idx >= 0:
                        out.setFieldAlias(idx, alias)

                _set_alias("parcel_m2", "필지면적(㎡)")
                _set_alias("in_aoi_m2", "조사지역 포함면적(㎡)")
                _set_alias("in_aoi_pct", "포함비율(%)")
            except Exception as _exc:
                log_swallowed("cadastral_overlap_dialog.create_output_layer", _exc)
            return out

        # Prepare output group (lazy-create run group only when at least one layer is added)
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        parent_name = "ArchToolkit - Cadastral"
        parent_group = root.findGroup(parent_name)
        if parent_group is None:
            parent_group = root.insertGroup(0, parent_name)

        try:
            # Keep group near top
            if parent_group.parent() == root:
                idx = root.children().index(parent_group)
                if idx != 0:
                    root.removeChildNode(parent_group)
                    root.insertChildNode(0, parent_group)
        except Exception as _exc:
            log_swallowed("cadastral_overlap_dialog.run", _exc)

        run_id = uuid.uuid4().hex[:6]
        run_group_name = f"지적중첩_{run_id}"
        run_group = None

        def ensure_run_group():
            nonlocal run_group
            if run_group is None:
                run_group = parent_group.insertGroup(0, run_group_name)
                run_group.setExpanded(False)
            return run_group

        cad_selected_feats = None
        if cad_sel and cad.selectedFeatureCount() > 0:
            try:
                cad_selected_feats = list(cad.selectedFeatures())
            except Exception:
                cad_selected_feats = None

        def iter_survey_features():
            if survey_sel and survey.selectedFeatureCount() > 0:
                return survey.selectedFeatures()
            return survey.getFeatures()

        if split_by_feature:
            # Build AOI geometries per survey feature
            aoi_items: List[Tuple[int, QgsGeometry]] = []
            for sf in iter_survey_features():
                _skip_418 = False
                try:
                    g = sf.geometry()
                except Exception as _exc:
                    log_swallowed("cadastral_overlap_dialog.run", _exc)
                    log_swallowed("tools/cadastral_overlap_dialog.py:420 (run)", _exc)
                    _skip_418 = True
                if _skip_418:
                    continue
                if not g or g.isEmpty():
                    continue
                g = _safe_make_valid(g)
                if ct is not None:
                    _skip_427 = False
                    try:
                        gt = QgsGeometry(g)
                        gt.transform(ct)
                        g = _safe_make_valid(gt)
                    except Exception as _exc:
                        # Skip rather than keep the untransformed geometry —
                        # wrong-CRS coordinates would just yield "no overlap".
                        log_swallowed("cadastral_overlap_dialog.run", _exc)
                        log_swallowed("tools/cadastral_overlap_dialog.py:431 (run)", _exc)
                        _skip_427 = True
                    if _skip_427:
                        continue
                if g and (not g.isEmpty()):
                    try:
                        aoi_items.append((int(sf.id()), g))
                    except Exception:
                        aoi_items.append((0, g))

            if not aoi_items:
                push_message(self.iface, "오류", "조사지역(폴리곤)에서 유효한 지오메트리를 찾지 못했습니다.", level=2)
                restore_ui_focus(self)
                return

            log_message(
                f"CadastralOverlap: start split-by-feature (cad={cad.name()}, survey={survey.name()}, aoi_count={len(aoi_items)})",
                level=Qgis.Info,
            )

            progress = QtWidgets.QProgressDialog(
                "조사지역 피처별 지적도 중첩 면적 계산 중...", "취소", 0, len(aoi_items), self
            )
            progress.setWindowModality(Qt.WindowModal)
            progress.show()
            QtWidgets.QApplication.processEvents()

            created_layers = 0
            empty_aois = 0
            total_in_m2 = 0.0

            for idx, (aoi_fid, aoi_geom) in enumerate(aoi_items):
                if progress.wasCanceled():
                    push_message(self.iface, "취소", "중첩 계산이 취소되었습니다.", level=1, duration=4)
                    restore_ui_focus(self)
                    return

                progress.setValue(idx)
                try:
                    if use_en:
                        progress.setLabelText(f"Processing AOI {idx + 1}/{len(aoi_items)}... (fid={aoi_fid})")
                    else:
                        progress.setLabelText(f"조사지역 {idx + 1}/{len(aoi_items)} 처리 중... (fid={aoi_fid})")
                except Exception as _exc:
                    log_swallowed("tools/cadastral_overlap_dialog.py:475 (run)", _exc)
                QtWidgets.QApplication.processEvents()

                aoi_geom = _safe_make_valid(aoi_geom)
                if aoi_geom is None or aoi_geom.isEmpty():
                    empty_aois += 1
                    continue

                aoi_bbox = aoi_geom.boundingBox()

                # Collect candidate cadastral features (bbox filter)
                feats: List[QgsFeature] = []
                if cad_selected_feats is not None:
                    for cf in cad_selected_feats:
                        _skip_490 = False
                        try:
                            cg = cf.geometry()
                            if cg and (not cg.isEmpty()) and cg.boundingBox().intersects(aoi_bbox):
                                feats.append(cf)
                        except Exception as _exc:
                            log_swallowed("cadastral_overlap_dialog.run", _exc)
                            log_swallowed("tools/cadastral_overlap_dialog.py:494 (run)", _exc)
                            _skip_490 = True
                        if _skip_490:
                            continue
                else:
                    req = QgsFeatureRequest()
                    try:
                        req.setFilterRect(aoi_bbox)
                    except Exception as _exc:
                        log_swallowed("tools/cadastral_overlap_dialog.py:501 (run)", _exc)
                    try:
                        feats = list(cad.getFeatures(req))
                    except Exception:
                        feats = []

                out = create_output_layer(f"{run_group_name}_AOI{aoi_fid}")
                pr = out.dataProvider()
                try:
                    set_archtoolkit_layer_metadata(
                        out,
                        tool_id="cadastral_overlap",
                        run_id=str(run_id),
                        kind="overlap_by_aoi",
                        units="m2/%",
                        params={"split_by_feature": True},
                    )
                except Exception as _exc:
                    log_swallowed("cadastral_overlap_dialog.run", _exc)

                out_feats: List[QgsFeature] = []
                sum_in = 0.0
                kept = 0

                for i, f in enumerate(feats):
                    if progress.wasCanceled():
                        push_message(self.iface, "취소", "중첩 계산이 취소되었습니다.", level=1, duration=4)
                        restore_ui_focus(self)
                        return
                    if i % 200 == 0:
                        QtWidgets.QApplication.processEvents()

                    _skip_534 = False
                    try:
                        g = f.geometry()
                    except Exception as _exc:
                        log_swallowed("cadastral_overlap_dialog.run", _exc)
                        log_swallowed("tools/cadastral_overlap_dialog.py:536 (run)", _exc)
                        _skip_534 = True
                    if _skip_534:
                        continue
                    if not g or g.isEmpty():
                        continue
                    g = _safe_make_valid(g)
                    try:
                        if not g.boundingBox().intersects(aoi_bbox):
                            continue
                    except Exception as _exc:
                        log_swallowed("cadastral_overlap_dialog.run", _exc)

                    try:
                        inter = g.intersection(aoi_geom)
                    except Exception:
                        inter = None
                    if inter is None or inter.isEmpty():
                        continue
                    inter = _safe_make_valid(inter)

                    in_m2 = self._area_m2(da, inter, crs=cad_crs)
                    if not math.isfinite(float(in_m2)) or float(in_m2) <= 0.0:
                        continue

                    parcel_m2 = self._area_m2(da, g, crs=cad_crs)
                    if parcel_m2 > 0.0 and math.isfinite(float(parcel_m2)):
                        pct = float(in_m2) / float(parcel_m2) * 100.0
                    else:
                        pct = 0.0

                    feat_out = QgsFeature(out.fields())
                    try:
                        attrs = list(f.attributes())
                        attrs.append(float(parcel_m2))
                        attrs.append(float(in_m2))
                        attrs.append(float(pct))
                        feat_out.setAttributes(attrs)
                    except Exception as _exc:
                        log_swallowed("cadastral_overlap_dialog.run", _exc)

                    feat_out.setGeometry(inter)
                    out_feats.append(feat_out)
                    sum_in += float(in_m2)
                    kept += 1

                if not out_feats:
                    empty_aois += 1
                    log_message(f"CadastralOverlap: AOI fid={aoi_fid} -> overlaps=0", level=Qgis.Info)
                else:
                    pr.addFeatures(out_feats)
                    out.updateExtents()
                    total_in_m2 += float(sum_in)
                    log_message(
                        f"CadastralOverlap: AOI fid={aoi_fid} done (parcels={kept}, in_m2={sum_in:.2f})",
                        level=Qgis.Info,
                    )

                # Add the output layer even when empty so users can open a per-AOI attribute table.
                project.addMapLayer(out, False)
                ensure_run_group().addLayer(out)
                created_layers += 1

            progress.setValue(len(aoi_items))
            QtWidgets.QApplication.processEvents()

            msg = f"완료: {created_layers}개 레이어 생성, 포함면적 합 {total_in_m2:,.2f} ㎡"
            if empty_aois > 0:
                msg += f"  (겹침 없음 {empty_aois}개)"
            push_message(self.iface, "지적도 중첩 면적표", msg, level=0, duration=7)
            log_message(f"CadastralOverlap: done split-by-feature ({msg})", level=Qgis.Info)
            self.accept()
            return

        # Default: unary union AOI (single output layer)
        survey_geoms = _iter_layer_geoms(survey, selected_only=survey_sel)
        aoi = _unary_union(survey_geoms)
        if aoi is None or aoi.isEmpty():
            push_message(self.iface, "오류", "조사지역(폴리곤)에서 유효한 지오메트리를 찾지 못했습니다.", level=2)
            restore_ui_focus(self)
            return
        aoi = _safe_make_valid(aoi)
        if ct is not None:
            try:
                aoi_t = QgsGeometry(aoi)
                aoi_t.transform(ct)
                aoi = _safe_make_valid(aoi_t)
            except Exception as e:
                log_message(f"CadastralOverlap: failed CRS transform AOI -> cad CRS: {e}", level=Qgis.Warning)
                push_message(
                    self.iface,
                    "오류",
                    "조사지역을 지적 레이어 좌표계로 변환하지 못했습니다. 결과가 왜곡되므로 중단합니다.",
                    level=2,
                    duration=8,
                )
                restore_ui_focus(self)
                return

        aoi = _safe_make_valid(aoi)
        aoi_bbox = aoi.boundingBox()
        aoi_area_m2 = self._area_m2(da, aoi, crs=cad_crs)

        # Collect candidate cadastral features (bbox filter)
        feats: List[QgsFeature] = []
        if cad_selected_feats is not None:
            for cf in cad_selected_feats:
                _skip_642 = False
                try:
                    cg = cf.geometry()
                    if cg and (not cg.isEmpty()) and cg.boundingBox().intersects(aoi_bbox):
                        feats.append(cf)
                except Exception as _exc:
                    log_swallowed("cadastral_overlap_dialog.run", _exc)
                    log_swallowed("tools/cadastral_overlap_dialog.py:646 (run)", _exc)
                    _skip_642 = True
                if _skip_642:
                    continue
        else:
            req = QgsFeatureRequest()
            try:
                req.setFilterRect(aoi_bbox)
            except Exception as _exc:
                log_swallowed("tools/cadastral_overlap_dialog.py:653 (run)", _exc)
            try:
                feats = list(cad.getFeatures(req))
            except Exception:
                feats = []

        total = len(feats)
        log_message(
            f"CadastralOverlap: start (cad={cad.name()}, survey={survey.name()}, total={total}, aoi_m2={aoi_area_m2:.2f})",
            level=Qgis.Info,
        )

        progress = QtWidgets.QProgressDialog("지적도 중첩 면적 계산 중...", "취소", 0, max(1, total), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        QtWidgets.QApplication.processEvents()

        out = create_output_layer(run_group_name)
        pr = out.dataProvider()
        try:
            set_archtoolkit_layer_metadata(
                out,
                tool_id="cadastral_overlap",
                run_id=str(run_id),
                kind="overlap",
                units="m2/%",
                params={"split_by_feature": False},
            )
        except Exception as _exc:
            log_swallowed("cadastral_overlap_dialog.run", _exc)

        out_feats: List[QgsFeature] = []
        sum_in = 0.0
        kept = 0

        for i, f in enumerate(feats):
            if progress.wasCanceled():
                push_message(self.iface, "취소", "중첩 계산이 취소되었습니다.", level=1, duration=4)
                restore_ui_focus(self)
                return
            if i % 50 == 0:
                progress.setValue(min(total, i))
                QtWidgets.QApplication.processEvents()

            _skip_698 = False
            try:
                g = f.geometry()
            except Exception as _exc:
                log_swallowed("cadastral_overlap_dialog.run", _exc)
                log_swallowed("tools/cadastral_overlap_dialog.py:700 (run)", _exc)
                _skip_698 = True
            if _skip_698:
                continue
            if not g or g.isEmpty():
                continue
            g = _safe_make_valid(g)
            try:
                if not g.boundingBox().intersects(aoi_bbox):
                    continue
            except Exception as _exc:
                log_swallowed("cadastral_overlap_dialog.run", _exc)

            try:
                inter = g.intersection(aoi)
            except Exception:
                inter = None
            if inter is None or inter.isEmpty():
                continue
            inter = _safe_make_valid(inter)

            in_m2 = self._area_m2(da, inter, crs=cad_crs)
            if not math.isfinite(float(in_m2)) or float(in_m2) <= 0.0:
                continue

            parcel_m2 = self._area_m2(da, g, crs=cad_crs)
            if parcel_m2 > 0.0 and math.isfinite(float(parcel_m2)):
                pct = float(in_m2) / float(parcel_m2) * 100.0
            else:
                pct = 0.0

            feat_out = QgsFeature(out.fields())
            try:
                attrs = list(f.attributes())
                attrs.append(float(parcel_m2))
                attrs.append(float(in_m2))
                attrs.append(float(pct))
                feat_out.setAttributes(attrs)
            except Exception as _exc:
                log_swallowed("cadastral_overlap_dialog.run", _exc)

            feat_out.setGeometry(inter)
            out_feats.append(feat_out)
            sum_in += float(in_m2)
            kept += 1

        progress.setValue(total)
        QtWidgets.QApplication.processEvents()

        if not out_feats:
            push_message(self.iface, "결과 없음", "조사지역과 겹치는 지적도 피처를 찾지 못했습니다.", level=1, duration=5)
            restore_ui_focus(self)
            return

        pr.addFeatures(out_feats)
        out.updateExtents()

        project.addMapLayer(out, False)
        ensure_run_group().addLayer(out)

        msg = f"완료: {kept}개 필지, 포함면적 합 {sum_in:,.2f} ㎡"
        if aoi_area_m2 > 0.0:
            msg += f"  (AOI {aoi_area_m2:,.2f} ㎡ 대비 {sum_in / aoi_area_m2 * 100.0:.1f}%)"
        push_message(self.iface, "지적도 중첩 면적표", msg, level=0, duration=7)
        log_message(f"CadastralOverlap: done ({msg})", level=Qgis.Info)
        self.accept()
