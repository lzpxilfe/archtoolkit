# -*- coding: utf-8 -*-
"""One implementation of "the extent of this AOI, in that CRS".

Three tools needed this and each carried its own copy. They had drifted -
one wrapped the union in ``try/except: pass``, the others did not - but the
copies shared a worse problem: none of them checked what ``combine()``
returned.

PyQGIS signals a failed union by returning a null or empty geometry, not by
raising. So a self-intersecting AOI (ordinary in Korean cadastral and survey
polygons) produced an empty geometry, which the emptiness check at the end read
as "no AOI", which returned ``None``, which every caller treated as "the user
did not pick an AOI" and silently fell back to the full raster extent.

The user picked an AOI, got the whole sheet, and was told nothing.

So this returns a result object rather than an optional rectangle: callers can
tell "no AOI was requested" apart from "an AOI was requested and could not be
built", and say so. The union also skips features individually instead of
abandoning the whole AOI for one bad polygon, and reports how many it dropped.
"""

from __future__ import annotations

from qgis.core import (
    QgsCoordinateTransform,
    QgsProject,
    QgsWkbTypes,
)

STATUS_OK = "ok"
STATUS_NO_LAYER = "no_layer"
STATUS_NOT_POLYGON = "not_polygon"
STATUS_NO_FEATURES = "no_features"
STATUS_UNION_FAILED = "union_failed"
STATUS_TRANSFORM_FAILED = "transform_failed"
STATUS_NOTHING_SELECTED = "nothing_selected"

_MESSAGES = {
    STATUS_NOT_POLYGON: "AOI 레이어가 폴리곤이 아닙니다.",
    STATUS_NO_FEATURES: "AOI 레이어에 사용할 수 있는 폴리곤이 없습니다.",
    STATUS_UNION_FAILED: (
        "AOI 폴리곤을 합칠 수 없습니다(자기교차 등 잘못된 지오메트리일 수 있습니다). "
        "벡터 > 지오메트리 도구 > 유효성 검사로 확인하세요."
    ),
    STATUS_TRANSFORM_FAILED: "AOI를 대상 좌표계로 변환할 수 없습니다.",
    STATUS_NOTHING_SELECTED: (
        "'선택 피처만'이 켜져 있지만 AOI 레이어에 선택된 피처가 없습니다. "
        "피처를 선택하거나 옵션을 끄세요."
    ),
}


class AoiExtentResult:
    """Outcome of resolving an AOI to a rectangle."""

    def __init__(self, extent=None, status=STATUS_NO_LAYER, used=0, skipped=0):
        self.extent = extent
        self.status = status
        self.used = int(used)
        self.skipped = int(skipped)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK and self.extent is not None

    @property
    def requested_but_failed(self) -> bool:
        """True when the user chose an AOI and it could not be used.

        This is the case the old code could not express, and the one that
        needs to reach the user: falling back to the full extent silently is
        how a clipped export quietly becomes an unclipped one.
        """
        return self.status not in (STATUS_OK, STATUS_NO_LAYER)

    def message(self) -> str:
        text = _MESSAGES.get(self.status, "")
        if self.ok and self.skipped:
            return f"AOI 폴리곤 {self.skipped}개를 건너뛰었습니다(잘못된 지오메트리)."
        return text

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"AoiExtentResult({self.status}, used={self.used}, skipped={self.skipped})"


def _is_usable(geom) -> bool:
    """A geometry that can take part in a union.

    ``isNull`` and ``isEmpty`` are both needed: a failed ``combine()`` returns
    a null geometry on some builds and an empty one on others.
    """
    if geom is None:
        return False
    try:
        if geom.isNull():
            return False
    except Exception:
        pass
    try:
        return not geom.isEmpty()
    except Exception:
        return False


def resolve_aoi_extent(aoi_layer, *, selected_only: bool, dst_crs) -> AoiExtentResult:
    """Union an AOI layer's polygons and return their extent in ``dst_crs``."""
    if aoi_layer is None:
        return AoiExtentResult(status=STATUS_NO_LAYER)
    try:
        if aoi_layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            return AoiExtentResult(status=STATUS_NOT_POLYGON)
    except Exception:
        return AoiExtentResult(status=STATUS_NOT_POLYGON)

    try:
        if selected_only and aoi_layer.selectedFeatureCount() == 0:
            # The old copies quietly unioned EVERY feature here. That is the
            # same silent substitution this module exists to remove: the user
            # asked for their selection and got the whole layer's extent.
            return AoiExtentResult(status=STATUS_NOTHING_SELECTED)
        features = aoi_layer.selectedFeatures() if selected_only else aoi_layer.getFeatures()
    except Exception:
        try:
            features = aoi_layer.getFeatures()
        except Exception:
            return AoiExtentResult(status=STATUS_NO_FEATURES)

    geom = None
    used = 0
    skipped = 0
    for feature in features:
        try:
            candidate = feature.geometry()
        except Exception:
            skipped += 1
            continue
        if not _is_usable(candidate):
            skipped += 1
            continue
        if geom is None:
            geom = candidate
            used += 1
            continue
        try:
            combined = geom.combine(candidate)
        except Exception:
            combined = None
        if _is_usable(combined):
            geom = combined
            used += 1
        else:
            # Keep the union built so far rather than letting one bad polygon
            # empty it; the count is reported so the caller can say so.
            skipped += 1

    if geom is None or not _is_usable(geom):
        return AoiExtentResult(
            status=STATUS_NO_FEATURES if used == 0 and skipped == 0 else STATUS_UNION_FAILED,
            used=used, skipped=skipped,
        )

    try:
        if aoi_layer.crs() != dst_crs:
            transform = QgsCoordinateTransform(aoi_layer.crs(), dst_crs, QgsProject.instance())
            reprojected = type(geom)(geom)
            reprojected.transform(transform)
            if not _is_usable(reprojected):
                return AoiExtentResult(status=STATUS_TRANSFORM_FAILED, used=used, skipped=skipped)
            geom = reprojected
    except Exception:
        return AoiExtentResult(status=STATUS_TRANSFORM_FAILED, used=used, skipped=skipped)

    try:
        rect = geom.boundingBox()
    except Exception:
        return AoiExtentResult(status=STATUS_TRANSFORM_FAILED, used=used, skipped=skipped)
    if rect is None or rect.isEmpty():
        return AoiExtentResult(status=STATUS_UNION_FAILED, used=used, skipped=skipped)
    return AoiExtentResult(extent=rect, status=STATUS_OK, used=used, skipped=skipped)


__all__ = [
    "AoiExtentResult",
    "STATUS_NO_FEATURES",
    "STATUS_NO_LAYER",
    "STATUS_NOTHING_SELECTED",
    "STATUS_NOT_POLYGON",
    "STATUS_OK",
    "STATUS_TRANSFORM_FAILED",
    "STATUS_UNION_FAILED",
    "resolve_aoi_extent",
]
