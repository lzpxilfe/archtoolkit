# -*- coding: utf-8 -*-
"""CI workflow wiring & test discovery completeness checks (V14)."""

from __future__ import annotations

import ast
import glob
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _flatten_suite(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten_suite(item)
        else:
            yield item


class CiWiringTests(unittest.TestCase):
    def test_ci_workflow_runs_static_identity_flake8_and_unittest_discover(self):
        ci_path = os.path.join(ROOT, ".github", "workflows", "ci.yml")
        self.assertTrue(os.path.isfile(ci_path))
        with open(ci_path, encoding="utf-8") as f:
            ci_text = f.read()
        self.assertIn("tests/check_static.py", ci_text)
        self.assertIn("scripts/check_release_identity.py", ci_text)
        self.assertIn("flake8 --select=E9,F63,F7,F82", ci_text)
        self.assertIn('unittest discover -s tests -p "test_*.py"', ci_text)
        self.assertIn("qgis/qgis:", ci_text)

    def test_release_workflow_validates_identity_and_builds_zip(self):
        rel_path = os.path.join(ROOT, ".github", "workflows", "release.yml")
        self.assertTrue(os.path.isfile(rel_path))
        with open(rel_path, encoding="utf-8") as f:
            rel_text = f.read()
        self.assertIn("scripts/check_release_identity.py", rel_text)
        self.assertIn("scripts/build_plugin_zip.py --check", rel_text)

    def test_every_test_file_is_valid_python_and_discoverable(self):
        tests_dir = os.path.join(ROOT, "tests")
        test_files = sorted(glob.glob(os.path.join(tests_dir, "test_*.py")))
        self.assertGreater(len(test_files), 0)
        for path in test_files:
            with open(path, encoding="utf-8") as f:
                ast.parse(f.read(), filename=path)

        loader = unittest.TestLoader()
        suite = loader.discover(tests_dir, pattern="test_*.py", top_level_dir=tests_dir)
        self.assertEqual(loader.errors, [], f"unittest discovery errors: {loader.errors}")

        discovered_ids = {tc.id() for tc in _flatten_suite(suite)}
        for path in test_files:
            mod_name = os.path.splitext(os.path.basename(path))[0]
            self.assertTrue(
                any(tid.startswith(f"{mod_name}.") or f".{mod_name}." in tid for tid in discovered_ids),
                f"Test module {mod_name} yielded no tests under unittest discover",
            )


if __name__ == "__main__":
    unittest.main()
