"""Moving a result group to the top of the layer tree must never delete it.

QgsLayerTreeGroup.removeChildNode() deletes the removed node. Five tools moved
their output group with ``root.removeChildNode(g); root.insertChildNode(0, g)``:
the first call deleted the group and every earlier result in it, the second
raised on the dead wrapper (swallowed), and the run still reported success.
tools/utils.move_group_to_top clones first and returns the node to keep using.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SOURCES = [os.path.join(ROOT, "arch_toolkit.py")] + sorted(
    os.path.join(ROOT, "tools", n) for n in os.listdir(os.path.join(ROOT, "tools")) if n.endswith(".py")
)

try:
    from qgis.core import QgsApplication, QgsProject, QgsVectorLayer
    HAVE_QGIS = True
except Exception:  # pragma: no cover - QGIS-free environments
    HAVE_QGIS = False


class NoRemoveThenReinsertTests(unittest.TestCase):
    def test_no_group_is_removed_and_reinserted(self):
        pattern = re.compile(
            r"removeChildNode\(\s*(\w+)\s*\)\s*\n\s*[\w.]*insertChildNode\(\s*\d+\s*,\s*\1\s*\)")
        offenders = []
        for path in SOURCES:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{os.path.relpath(path, ROOT)}:{line}: use utils.move_group_to_top")
        self.assertEqual([], offenders, "\n" + "\n".join(offenders))


@unittest.skipUnless(HAVE_QGIS, "QGIS Python not available")
class MoveGroupToTopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QgsApplication.instance()
        if cls._app is None:
            cls._app = QgsApplication([], False)
            cls._app.initQgis()
        sys.path.insert(0, os.path.dirname(ROOT))
        from importlib import import_module
        cls.utils = import_module(os.path.basename(ROOT) + ".tools.utils")

    def test_group_keeps_its_layers_when_moved(self):
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        group = root.insertGroup(0, "ArchToolkit - test results")
        layer = QgsVectorLayer("Point?crs=EPSG:5186", "earlier result", "memory")
        project.addMapLayer(layer, False)
        group.addLayer(layer)
        other = QgsVectorLayer("Point?crs=EPSG:5186", "loaded later", "memory")
        project.addMapLayer(other, False)
        root.insertLayer(0, other)
        try:
            moved = self.utils.move_group_to_top(root, group)
            self.assertIs(root.children()[0], moved)
            self.assertEqual(["earlier result"], [n.name() for n in moved.children()])
            self.assertIsNotNone(project.mapLayer(layer.id()))
            moved.insertGroup(0, "new run")  # the returned node must be usable
        finally:
            project.removeAllMapLayers()
            root.removeAllChildren()


if __name__ == "__main__":
    unittest.main()
