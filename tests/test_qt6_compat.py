"""Guard the spellings that let one code base run on QGIS 3.34 through QGIS 4 (PyQt6).

Three layers, each active where its binding is available:

* Always: text checks for the QGIS 3-only spellings that were migrated
  (``QVariant.Int``, ``QgsWkbTypes.PointGeometry``, ``.exec_(``, ...).
* Under PyQt5 (the QGIS 3 Python): every ``QClass.Member`` token whose value is
  an enum member must already be written in its scoped form, so the resolver in
  ``scripts/qt6_migrate.py`` finds nothing left to rewrite.
* Under PyQt6 (the CI static job installs it): every Qt name the sources spell
  must resolve, which catches both a surviving unscoped enum and a mistyped
  scoped one.

``tools/qtcompat.py`` is the one module allowed to spell a PyQt5-only name
(inside its fallback branch) and is excluded from all three.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SOURCES = [os.path.join(ROOT, "arch_toolkit.py")] + sorted(
    os.path.join(ROOT, "tools", name)
    for name in os.listdir(os.path.join(ROOT, "tools"))
    if name.endswith(".py") and name != "qtcompat.py"
)

# (pattern, what to write instead)
FORBIDDEN = [
    (r"\bQVariant\.[A-Z]\w*", "FT_* from tools.qtcompat (QVariant.Type is absent in PyQt6)"),
    (r"\.exec_\(", ".exec( (exec_ is absent in PyQt6)"),
    (r"from qgis\.PyQt\.QtWidgets import[^\n]*\bQAction\b", "QAction from qgis.PyQt.QtGui"),
    (r"\bQgsWkbTypes\.\w+Geometry\b", "Qgis.GeometryType.*"),
    (r"\bQgsMapLayerProxyModel\.(Filter\.)?[A-Z]", "Qgis.LayerFilter.*"),
    (r"\bQgsRasterBandStats\.(Stats\.)?[A-Z]", "RBS_* from tools.qtcompat"),
    (r"\bQgsUnitTypes\.(Distance|Area|Render|Angle|Volume|Temporal|Layout)[A-Z]", "Qgis.DistanceUnit / AreaUnit / RenderUnit"),
    (r"\bQgsRaster\.Identify", "Qgis.RasterIdentifyFormat.*"),
    (r"\bQgis\.(Info|Warning|Critical|Success|NoLevel)\b", "Qgis.MessageLevel.*"),
    (r"\bQgsPalLayerSettings\.(AroundPoint|OverPoint|Line|Curved|Horizontal|Free|PerimeterCurved|OutsidePolygons)\b",
     "Qgis.LabelPlacement.*"),
    (r"\bQgsRubberBand\.ICON_", "RUBBER_BAND_CIRCLE from tools.qtcompat"),
    (r"\bQgsColorRampShader\.(Type\.)?(Interpolated|Discrete|Exact)\b", "SHADER_* from tools.qtcompat"),
    (r"\bQgsTask\.(CanCancel|CancelWithoutPrompt|Hidden|AllFlags)\b", "QgsTask.Flag.*"),
    (r"\bQgsRasterDataProvider\.Transform(?!Type\b)[A-Z]", "QgsRasterDataProvider.TransformType.*"),
    (r"\bQgsSymbolLayer\.Property[A-Z]", "SYMBOL_PROPERTY_* from tools.qtcompat"),
    (r"\bevent\.[xy]\(\)", "event.pos().x() / .y() (QMouseEvent.x() is absent in PyQt6)"),
    (r"(?<!LayerFilter)\.(Vector|Raster|Plugin|Mesh)Layer\b(?!\()", "Qgis.LayerType.*"),
    (r"\bQTextDocument\.FindFlags\b", "QTextDocument.FindFlag(0)"),
    (r"\bQFileDialog\.Options\(", "QFileDialog.Option(0)"),
    (r"\bQRegExp\b|\bQTextCodec\b|\bQDesktopWidget\b|\.toTime_t\(|setTabStopWidth|HighQualityAntialiasing|\.setMargin\(",
     "a Qt 6 API (these were removed)"),
    (r"fontMetrics\(\)\.width\(|QFontMetrics\([^)]*\)\.width\(", "horizontalAdvance()"),
    # PyQt6 rejects a raw int where an enum is expected (progress.setWindowModality(2) raised TypeError).
    (r"\.set(WindowModality|EchoMode|TextAlignment|Alignment|FrameShape|FrameShadow|FrameStyle|CheckState|SelectionMode|"
     r"SelectionBehavior|EditTriggers|LineWrapMode|PopupMode|WindowFlags|ContextMenuPolicy|FocusPolicy|Orientation|"
     r"TextInteractionFlags|SizeAdjustPolicy|InsertPolicy|ToolButtonStyle)\(\s*-?[0-9]", "a scoped Qt enum member, never a raw int"),
]


def _load_migrate_module():
    path = os.path.join(ROOT, "scripts", "qt6_migrate.py")
    spec = importlib.util.spec_from_file_location("qt6_migrate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _binding_available(name):
    try:
        importlib.import_module(f"{name}.QtCore")
        importlib.import_module(f"{name}.QtWidgets")
        return True
    except Exception:
        return False


class Qt6SpellingTests(unittest.TestCase):
    def test_no_qgis3_only_spellings(self):
        offenders = []
        for path in SOURCES:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for pattern, instead in FORBIDDEN:
                for m in re.finditer(pattern, text):
                    line = text.count("\n", 0, m.start()) + 1
                    offenders.append(f"{os.path.relpath(path, ROOT)}:{line}: {m.group(0)!r} -> use {instead}")
        self.assertEqual([], offenders, "\n" + "\n".join(offenders))

    def test_compat_module_exports(self):
        # Pure text check so it runs without QGIS: every exported name is defined.
        with open(os.path.join(ROOT, "tools", "qtcompat.py"), encoding="utf-8") as fh:
            text = fh.read()
        exported = re.findall(r'"(\w+)"', text.split("__all__")[1])
        self.assertTrue(exported)
        for name in exported:
            self.assertRegex(text, rf"(?<![\w.]){name}\s*(=|,)", f"{name} listed in __all__ but never assigned")

    @unittest.skipUnless(_binding_available("PyQt5"), "PyQt5 not importable")
    def test_no_unscoped_qt_enums_under_pyqt5(self):
        mod = _load_migrate_module()
        mapping = mod.resolve()["mapping"]
        self.assertEqual({}, mapping, "unscoped Qt enum members remain (run scripts/qt6_migrate.py):\n"
                         + "\n".join(f"  {k} -> {v}" for k, v in sorted(mapping.items())))

    @unittest.skipUnless(_binding_available("PyQt6"), "PyQt6 not importable")
    def test_every_qt_name_resolves_under_pyqt6(self):
        mod = _load_migrate_module()
        missing = mod.verify_pyqt6_attributes()
        self.assertEqual({}, missing, "Qt names that do not exist in PyQt6:\n"
                         + "\n".join(f"  {k} in {', '.join(v)}" for k, v in missing.items()))


if __name__ == "__main__":
    sys.exit(unittest.main())
