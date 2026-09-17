from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PICTOGRAPH_RE = re.compile("[\u2600-\u27BF\uFE0F\U0001F000-\U0001FAFF]")


class UiAssetTests(unittest.TestCase):
    def test_tool_sources_do_not_embed_emoji_pictographs(self):
        findings = []
        paths = [ROOT / "README.md"]
        for pattern in ("*.py", "*.ui"):
            paths.extend(sorted((ROOT / "tools").glob(pattern)))
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                match = PICTOGRAPH_RE.search(line)
                if match:
                    findings.append(f"{path.name}:{line_number}: {match.group(0)}")
        self.assertEqual(findings, [], "emoji pictographs found: " + ", ".join(findings))

    def test_align_export_icon_is_a_small_limited_palette_xpm(self):
        path = ROOT / "align_export_icon.xpm"
        text = path.read_text(encoding="ascii")
        quoted = re.findall(r'^"(.*)"[,]?$', text, re.MULTILINE)
        self.assertGreaterEqual(len(quoted), 1)
        width, height, colors, chars_per_pixel = map(int, quoted[0].split())
        self.assertEqual((width, height, chars_per_pixel), (32, 32, 1))
        self.assertLessEqual(colors, 8)
        pixels = quoted[1 + colors:1 + colors + height]
        self.assertEqual(len(pixels), height)
        self.assertTrue(all(len(row) == width for row in pixels))

    def test_move_group_to_top_preserves_children(self):
        try:
            from qgis.core import QgsLayerTreeGroup
        except ImportError as exc:
            self.skipTest(str(exc))
        from tools.utils import move_group_to_top

        root = QgsLayerTreeGroup()
        other = root.addGroup("other")
        original = root.addGroup("results")
        previous_run = original.addGroup("previous_run")
        previous_run.setCustomProperty("run_id", "existing")
        original.setExpanded(False)

        moved = move_group_to_top(root, original)

        self.assertEqual(root.children(), [moved, other])
        self.assertEqual(moved.name(), "results")
        self.assertFalse(moved.isExpanded())
        self.assertEqual(len(moved.children()), 1)
        self.assertEqual(moved.children()[0].name(), "previous_run")
        self.assertEqual(moved.children()[0].customProperty("run_id"), "existing")
        new_run = moved.addGroup("new_run")
        self.assertEqual(new_run.parent(), moved)
        self.assertIs(move_group_to_top(root, moved), moved)
        self.assertEqual(len(moved.children()), 2)

    def test_align_export_action_uses_its_dedicated_icon(self):
        source = (ROOT / "arch_toolkit.py").read_text(encoding="utf-8")
        self.assertIn("align_export_icon.xpm", source)
        self.assertIn("QIcon(align_export_icon)", source)


if __name__ == "__main__":
    unittest.main()
