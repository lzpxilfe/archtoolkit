# -*- coding: utf-8 -*-
"""Static & runtime checks for GDAL/OGR enum usage across tools/*.py (V9)."""

from __future__ import annotations

import ast
import glob
import os
import unittest

try:
    from osgeo import gdal, ogr, osr
except ImportError:  # pragma: no cover - dependency-free CI lane
    gdal = ogr = osr = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(ROOT, "tools")

_PREFIXES_GDAL = ("GDT_", "GRA_", "GF_", "GA_", "CE_", "GMF_", "GCI_")
_PREFIXES_OGR = ("OFT", "wkb", "OFST")


def _tool_files():
    return sorted(glob.glob(os.path.join(TOOLS_DIR, "*.py")))


class GdalEnumAuditTests(unittest.TestCase):
    def test_referenced_gdal_and_ogr_constants_are_valid(self):
        gdal_attrs = set()
        ogr_attrs = set()
        for path in _tool_files():
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    owner = node.value.id
                    attr = node.attr
                    if owner == "gdal" and attr.startswith(_PREFIXES_GDAL):
                        gdal_attrs.add((os.path.basename(path), attr))
                    elif owner == "ogr" and attr.startswith(_PREFIXES_OGR):
                        ogr_attrs.add((os.path.basename(path), attr))

        self.assertTrue(gdal_attrs, "Expected GDAL enum constants to be referenced in tools/")
        if gdal is not None:
            for fname, attr in sorted(gdal_attrs):
                self.assertTrue(hasattr(gdal, attr), f"{fname}: gdal.{attr} does not exist")
            self.assertEqual(gdal.GDT_Byte, 1)
            self.assertEqual(gdal.GDT_UInt16, 2)
            self.assertEqual(gdal.GDT_Int16, 3)
            self.assertEqual(gdal.GDT_UInt32, 4)
            self.assertEqual(gdal.GDT_Int32, 5)
            self.assertEqual(gdal.GDT_Float32, 6)
            self.assertEqual(gdal.GDT_Float64, 7)
            self.assertEqual(gdal.GRA_NearestNeighbour, 0)
            self.assertEqual(gdal.GRA_Bilinear, 1)
        if ogr is not None:
            for fname, attr in sorted(ogr_attrs):
                self.assertTrue(hasattr(ogr, attr), f"{fname}: ogr.{attr} does not exist")

    def test_processing_gdal_numeric_enum_literals_in_valid_bounds(self):
        # Verify hardcoded Processing integer enum parameters stay in GDAL's published bounds:
        # - DATA_TYPE: 0..11 (gdal:proximity accepts 0..6, gdal:warpreproject/rasterize 0..11)
        # - RTYPE (gdal:rastercalculator): 0..5 (Byte..Float64)
        # - RESAMPLING: 0..12
        for path in _tool_files():
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                for k, v in zip(node.keys, node.values):
                    if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                        continue
                    if not (isinstance(v, ast.Constant) and isinstance(v.value, int) and not isinstance(v.value, bool)):
                        continue
                    if k.value == "DATA_TYPE":
                        self.assertGreaterEqual(v.value, 0, msg=path)
                        self.assertLessEqual(v.value, 11, msg=path)
                    elif k.value == "RTYPE":
                        self.assertGreaterEqual(v.value, 0, msg=path)
                        self.assertLessEqual(v.value, 5, msg=path)
                    elif k.value == "RESAMPLING":
                        self.assertGreaterEqual(v.value, 0, msg=path)
                        self.assertLessEqual(v.value, 12, msg=path)

            # Algorithm-specific checks for calls like run_alg_blocking("gdal:proximity", {...})
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or len(node.args) < 2:
                    continue
                alg_arg, params_arg = node.args[0], node.args[1]
                if not (isinstance(alg_arg, ast.Constant) and isinstance(alg_arg.value, str)):
                    continue
                if not isinstance(params_arg, ast.Dict):
                    continue
                alg_id = alg_arg.value.lower()
                for k, v in zip(params_arg.keys, params_arg.values):
                    if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                        continue
                    if not (isinstance(v, ast.Constant) and isinstance(v.value, int) and not isinstance(v.value, bool)):
                        continue
                    if alg_id == "gdal:proximity" and k.value == "DATA_TYPE":
                        self.assertLessEqual(v.value, 6, msg=f"{path}: gdal:proximity DATA_TYPE={v.value}")
                    if alg_id == "gdal:rastercalculator" and k.value == "RTYPE":
                        self.assertLessEqual(v.value, 5, msg=f"{path}: gdal:rastercalculator RTYPE={v.value}")


if __name__ == "__main__":
    unittest.main()
