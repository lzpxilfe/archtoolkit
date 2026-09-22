"""Names that differ between QGIS 3.x (PyQt5) and QGIS 4 (PyQt6).

The plugin declares ``qgisMaximumVersion=4.99``. QGIS 4 is built on PyQt6,
which removed unscoped enum access (``QVariant.Int``, or an alignment flag
written without its ``AlignmentFlag`` scope), and several QGIS 3 enums moved
into the ``Qgis`` namespace (``QgsWkbTypes.PointGeometry`` became
``Qgis.GeometryType.Point``). Most of those have a spelling that works on
every supported version, and the sources use that spelling directly. The few
that do not are resolved once here, at import time, by probing the running
QGIS rather than by version arithmetic.

Everything in this module is a plain constant so call sites read the same on
both bindings::

    QgsField("elev", FT_DOUBLE)
    provider.bandStatistics(1, RBS_MIN | RBS_MAX)
    ramp.setColorRampType(SHADER_DISCRETE)
"""
from __future__ import annotations

from qgis.PyQt.QtCore import QMetaType
from qgis.core import Qgis, QgsColorRampShader, QgsField, QgsSymbolLayer


def _field_types():
    """Return (Int, UInt, LongLong, ULongLong, Double, String) for QgsField().

    QgsField accepts ``QMetaType.Type`` from QGIS 3.38 and is the only form on
    QGIS 4 (PyQt6 has no ``QVariant.Type``). Older 3.x releases accept only
    ``QVariant.Type``; the probe below tells the two apart on the running build.
    """
    try:
        QgsField("_probe", QMetaType.Type.Int)
        t = QMetaType.Type
        return (t.Int, t.UInt, t.LongLong, t.ULongLong, t.Double, t.QString)
    except TypeError:
        from qgis.PyQt.QtCore import QVariant
        return (
            QVariant.Int, QVariant.UInt, QVariant.LongLong, QVariant.ULongLong,
            QVariant.Double, QVariant.String,
        )


FT_INT, FT_UINT, FT_LONGLONG, FT_ULONGLONG, FT_DOUBLE, FT_STRING = _field_types()

#: Integer-like field types, for ``field.type() in FT_INTEGER_TYPES`` checks.
FT_INTEGER_TYPES = (FT_INT, FT_UINT, FT_LONGLONG, FT_ULONGLONG)
#: Numeric field types (integers plus double).
FT_NUMERIC_TYPES = FT_INTEGER_TYPES + (FT_DOUBLE,)

# Raster band statistics flags: Qgis.RasterBandStatistic from 3.36, and the
# only form on QGIS 4; QgsRasterBandStats.Stats before that.
try:
    RBS_ALL = Qgis.RasterBandStatistic.All
    RBS_MIN = Qgis.RasterBandStatistic.Min
    RBS_MAX = Qgis.RasterBandStatistic.Max
except AttributeError:
    from qgis.core import QgsRasterBandStats as _QgsRasterBandStats
    RBS_ALL = _QgsRasterBandStats.Stats.All
    RBS_MIN = _QgsRasterBandStats.Stats.Min
    RBS_MAX = _QgsRasterBandStats.Stats.Max

# Colour ramp shader interpolation: Qgis.ShaderInterpolationMethod from 3.38
# (QGIS 4 only form); QgsColorRampShader.Type before that.
try:
    SHADER_INTERPOLATED = Qgis.ShaderInterpolationMethod.Linear
    SHADER_DISCRETE = Qgis.ShaderInterpolationMethod.Discrete
except AttributeError:
    SHADER_INTERPOLATED = QgsColorRampShader.Type.Interpolated
    SHADER_DISCRETE = QgsColorRampShader.Type.Discrete

# Data-defined symbol layer properties: QGIS 4 renamed the members
# (Property.PropertyAngle -> Property.Angle).
SYMBOL_PROPERTY_ANGLE = getattr(QgsSymbolLayer.Property, "Angle", None)
if SYMBOL_PROPERTY_ANGLE is None:
    SYMBOL_PROPERTY_ANGLE = QgsSymbolLayer.Property.PropertyAngle
SYMBOL_PROPERTY_STROKE_COLOR = getattr(QgsSymbolLayer.Property, "StrokeColor", None)
if SYMBOL_PROPERTY_STROKE_COLOR is None:
    SYMBOL_PROPERTY_STROKE_COLOR = QgsSymbolLayer.Property.PropertyStrokeColor

# Rubber band marker icon: Qgis.RubberBandIconType on QGIS 4,
# QgsRubberBand.IconType on 3.x. qgis.gui is optional so headless imports of
# this module (tests, server contexts) do not require a GUI build.
try:
    RUBBER_BAND_CIRCLE = Qgis.RubberBandIconType.Circle
except AttributeError:
    try:
        from qgis.gui import QgsRubberBand as _QgsRubberBand
        RUBBER_BAND_CIRCLE = _QgsRubberBand.IconType.ICON_CIRCLE
    except ImportError:  # no qgis.gui available
        RUBBER_BAND_CIRCLE = None

__all__ = [
    "FT_INT", "FT_UINT", "FT_LONGLONG", "FT_ULONGLONG", "FT_DOUBLE", "FT_STRING",
    "FT_INTEGER_TYPES", "FT_NUMERIC_TYPES",
    "RBS_ALL", "RBS_MIN", "RBS_MAX",
    "SHADER_INTERPOLATED", "SHADER_DISCRETE",
    "SYMBOL_PROPERTY_ANGLE", "SYMBOL_PROPERTY_STROKE_COLOR",
    "RUBBER_BAND_CIRCLE",
]
