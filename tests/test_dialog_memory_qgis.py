"""QGIS-gated round-trip test for tools.dialog_memory (skipped without PyQGIS)."""
from __future__ import annotations

import os
import unittest

QGIS_AVAILABLE = False
try:
    from qgis.PyQt import QtWidgets
    from qgis.core import QgsApplication
    from qgis.gui import QgsMapLayerComboBox
    from tools import dialog_memory
    QGIS_AVAILABLE = True
except ImportError:  # pragma: no cover - dependency-free CI
    pass


@unittest.skipUnless(QGIS_AVAILABLE, "PyQGIS not available")
class DialogMemoryRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QgsApplication.instance()
        if cls.app is None:
            cls.app = QgsApplication([], False)
            cls.app.initQgis()

    def _build(self):
        d = QtWidgets.QDialog()
        s = QtWidgets.QDoubleSpinBox(d)
        s.setObjectName("spinA")
        s.setRange(0, 100)
        c = QtWidgets.QCheckBox(d)
        c.setObjectName("chkB")
        cb = QtWidgets.QComboBox(d)
        cb.setObjectName("cmbC")
        cb.addItem("one", "k1")
        cb.addItem("two", "k2")
        le = QtWidgets.QLineEdit(d)
        le.setObjectName("txtD")
        anon = QtWidgets.QSpinBox(d)  # no objectName: must be ignored
        anon.setValue(7)
        return d, s, c, cb, le, anon

    def test_values_round_trip_and_unnamed_widgets_are_ignored(self):
        key = "unit_test_dialog_memory"
        dialog_memory.forget(key)
        d, s, c, cb, le, _anon = self._build()
        s.setValue(12.5)
        c.setChecked(True)
        cb.setCurrentIndex(1)
        le.setText("/tmp/out.tif")
        self.assertEqual(dialog_memory.save(d, key), 4)
        d2, s2, c2, cb2, le2, anon2 = self._build()
        self.assertEqual(dialog_memory.restore(d2, key), 4)
        self.assertEqual(s2.value(), 12.5)
        self.assertTrue(c2.isChecked())
        self.assertEqual(cb2.currentData(), "k2")
        self.assertEqual(le2.text(), "/tmp/out.tif")
        self.assertEqual(anon2.value(), 7)  # built with 7, nothing stored for it, nothing restored
        dialog_memory.forget(key)
        d3, s3, *_ = self._build()
        self.assertEqual(dialog_memory.restore(d3, key), 0)
        self.assertEqual(s3.value(), 0.0)

    def test_skip_list_and_missing_layer_are_respected(self):
        key = "unit_test_dialog_memory_skip"
        dialog_memory.forget(key)
        d, s, c, cb, le, _ = self._build()
        ml = QgsMapLayerComboBox(d)
        ml.setObjectName("cmbLayer")
        s.setValue(3.0)
        le.setText("secret")
        n = dialog_memory.save(d, key, skip=("txtD",))
        self.assertEqual(n, 3)  # spin, check, combo; line edit skipped; no layer selected
        d2, s2, c2, cb2, le2, _ = self._build()
        dialog_memory.restore(d2, key)
        self.assertEqual(le2.text(), "")
        self.assertEqual(s2.value(), 3.0)
        dialog_memory.forget(key)


if __name__ == "__main__":
    unittest.main()
