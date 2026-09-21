"""The scholarly-basis notes shown in every tool's help must stay consistent with REFERENCES.md."""
from __future__ import annotations

import os
import re
import unittest

from tools import scholar_notes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Every dialog that shows help must have a note; the ids are the ones the
# dialogs pass to scholar_notes.html_for.
EXPECTED_TOOLS = {
    "terrain_analysis", "slope_aspect_drafting", "viewshed", "cost_surface", "cost_network",
    "spatial_network", "dem_generator", "contour_extractor", "geology_zip", "geochem",
    "cadastral_overlap", "align_export", "ahp", "trench_suggestion", "distance_raster",
    "covariate_report", "terrain_profile", "map_styling", "ai_report",
}


class ScholarNotesTests(unittest.TestCase):
    def test_every_tool_has_a_note(self):
        self.assertEqual(set(scholar_notes.available_tools()), EXPECTED_TOOLS)

    def test_every_reference_key_resolves(self):
        for tool, note in scholar_notes.NOTES.items():
            for m in note["methods"]:
                for k in m["refs"]:
                    self.assertIn(k, scholar_notes._R, msg=f"{tool}: unknown ref key {k}")
                self.assertIn(m["label"], ("A", "B", "C"), msg=tool)
                self.assertTrue(m["origin"].strip() and m["intent"].strip(), msg=f"{tool}: empty text")

    def test_every_cited_author_appears_in_references_md(self):
        # The notes may not cite anything REFERENCES.md does not carry.
        refs_md = open(os.path.join(ROOT, "REFERENCES.md"), encoding="utf-8").read()
        for key, line in scholar_notes._R.items():
            surname = re.split(r"[,(]", line, maxsplit=1)[0].strip()
            surname = surname.split()[0] if surname else ""
            if not surname or not surname.isascii():
                continue
            self.assertIn(surname, refs_md, msg=f"{key}: {surname} not in REFERENCES.md")

    def test_html_is_well_formed_and_escaped(self):
        for tool in scholar_notes.available_tools():
            html = scholar_notes.html_for(tool)
            self.assertTrue(html.startswith("<h3>"), tool)
            self.assertEqual(html.count("<h4>"), html.count("</h4>"), tool)
            self.assertEqual(html.count("<ul>") + html.count("<ol>"), html.count("</ul>") + html.count("</ol>"), tool)
            self.assertIn("권장 절차", html, tool)
            has_refs = any(m["refs"] for m in scholar_notes.NOTES[tool]["methods"])
            self.assertEqual("원문" in html, has_refs, tool)
        self.assertEqual(scholar_notes.html_for("no_such_tool"), "")

    def test_no_tilde_ranges_in_user_text(self):
        # Ranges are written with a hyphen in this project's UI text.
        for tool, note in scholar_notes.NOTES.items():
            for m in note["methods"]:
                self.assertNotIn("~", m["origin"] + m["intent"], msg=tool)


if __name__ == "__main__":
    unittest.main()
