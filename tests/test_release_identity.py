from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.check_release_identity import validate


class ReleaseIdentityTests(unittest.TestCase):
    def _repo(
        self,
        *,
        version="0.2.0",
        badge_version="0.2.0",
        badge_url_version="0.2.0",
        status="stable",
        status_url="stable",
        experimental="false",
        deprecated="false",
        bib_version="0.2.0",
        bib_url="https://github.com/lzpxilfe/archtoolkit",
        repository="https://github.com/lzpxilfe/archtoolkit",
        tracker="https://example.org/archtoolkit/issues",
        homepage="https://example.org/archtoolkit",
        category=None,
        changelog_version=None,
        cff_version="0.2.0",
        cff_repository="https://github.com/lzpxilfe/archtoolkit",
        cff_url="https://example.org/archtoolkit",
        cff_license="GPL-3.0-or-later",
        cff_release_date=None,
        extra_readme="",
        extra_cff="",
    ) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        category_line = f"category={category}\n" if category is not None else ""
        metadata = (
            "[general]\n"
            "name=ArchToolkit\n"
            f"version={version}\n"
            f"experimental={experimental}\n"
            f"deprecated={deprecated}\n"
            f"repository={repository}\n"
            f"tracker={tracker}\n"
            f"homepage={homepage}\n"
            f"{category_line}"
            "license=GPL-3.0-or-later\n"
            f"changelog={changelog_version or version} - Test release.\n"
        )
        readme = (
            f'<img alt="Version {badge_version}" '
            f'src="https://img.shields.io/badge/version-{badge_url_version}-blue">\n'
            f'<img alt="Status {status}" '
            f'src="https://img.shields.io/badge/status-{status_url}-orange">\n'
            '<img alt="License GPL-3.0-or-later" '
            'src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue">\n'
            "```bibtex\n"
            "@software{ArchToolkit,\n"
            f"  url = {{{bib_url}}},\n"
            f"  version = {{{bib_version}}}\n"
            "}\n"
            "```\n"
            f"{extra_readme}"
        )
        citation_lines = [
            "cff-version: 1.2.0",
            "type: software",
            "title: ArchToolkit",
            f'version: "{cff_version}"' if cff_version is not None else "",
            f"repository-code: {cff_repository}",
            f"url: {cff_url}",
            f"license: {cff_license}" if cff_license is not None else "",
        ]
        if cff_release_date is not None:
            citation_lines.append(f"date-released: {cff_release_date}")
        if extra_cff:
            citation_lines.append(extra_cff)
        (root / "metadata.txt").write_text(metadata, encoding="utf-8")
        (root / "README.md").write_text(readme, encoding="utf-8")
        (root / "CITATION.cff").write_text("\n".join(citation_lines) + "\n", encoding="utf-8")
        return root

    def test_consistent_stable_identity_passes(self):
        self.assertEqual(validate(self._repo()), [])

    def test_badge_alt_and_url_are_checked_independently(self):
        errors = validate(self._repo(badge_version="0.1.2", badge_url_version="0.1.1"))
        self.assertTrue(any("Version badge is" in error for error in errors))
        self.assertTrue(any("Version badge URL" in error for error in errors))

    def test_bibtex_version_and_repository_are_checked(self):
        errors = validate(self._repo(bib_version="0.1.2", bib_url="https://github.com/lzpxilfe/ar"))
        self.assertTrue(any("BibTeX version" in error for error in errors))
        self.assertTrue(any("BibTeX URL" in error for error in errors))

    def test_metadata_flags_determine_status(self):
        errors = validate(self._repo(experimental="true", status="beta", status_url="beta"))
        self.assertTrue(any("expected 'experimental'" in error for error in errors))

    def test_invalid_boolean_is_not_accepted(self):
        errors = validate(self._repo(experimental="yes"))
        self.assertTrue(any("must be exactly true or false" in error for error in errors))

    def test_missing_cff_fields_are_reported(self):
        errors = validate(self._repo(cff_version=None, cff_license=None))
        self.assertTrue(any("top-level version is missing" in error for error in errors))
        self.assertTrue(any("CITATION.cff license" in error for error in errors))

    def test_release_tag_requires_matching_version_and_date(self):
        errors = validate(self._repo(), release_tag="v0.1.2")
        self.assertTrue(any("release tag" in error for error in errors))
        self.assertTrue(any("date-released is required" in error for error in errors))
        self.assertTrue(any("--release-date is required" in error for error in errors))

        self.assertEqual(
            validate(
                self._repo(cff_release_date="2026-07-13"),
                release_tag="v0.2.0",
                release_date="2026-07-13",
            ),
            [],
        )

    def test_invalid_release_date_is_reported(self):
        errors = validate(self._repo(cff_release_date="2026-02-30"))
        self.assertTrue(any("valid calendar date" in error for error in errors))

    def test_release_date_requires_exact_syntax_and_tag_date(self):
        for invalid in ("20260713", "2026-W29-1"):
            with self.subTest(invalid=invalid):
                errors = validate(self._repo(cff_release_date=invalid))
                self.assertTrue(any("YYYY-MM-DD" in error for error in errors))

        errors = validate(
            self._repo(cff_release_date="2026-07-12"),
            release_tag="v0.2.0",
            release_date="2026-07-13",
        )
        self.assertTrue(any("expected release tag date" in error for error in errors))

    def test_future_release_date_is_rejected(self):
        errors = validate(self._repo(cff_release_date="2999-01-01"))
        self.assertTrue(any("too far in the future" in error for error in errors))

    def test_next_calendar_day_is_allowed_for_timezone_boundaries(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self.assertEqual(validate(self._repo(cff_release_date=tomorrow)), [])

    def test_homepage_and_tracker_may_be_independent_urls(self):
        self.assertEqual(validate(self._repo()), [])
        errors = validate(self._repo(tracker="not a URL"))
        self.assertTrue(any("tracker must be an absolute" in error for error in errors))

    def test_cff_url_tracks_homepage(self):
        errors = validate(self._repo(cff_url="https://example.org/other"))
        self.assertTrue(any("CITATION.cff url" in error for error in errors))

    def test_invalid_qgis_category_is_rejected(self):
        errors = validate(self._repo(category="Analysis"))
        self.assertTrue(any("allowed values" in error for error in errors))
        self.assertEqual(validate(self._repo(category="Raster")), [])

    def test_duplicate_cff_root_key_is_rejected(self):
        errors = validate(self._repo(extra_cff='version: "0.2.0" # duplicate'))
        self.assertTrue(any("duplicate top-level key 'version'" in error for error in errors))

    def test_inline_cff_comments_are_supported(self):
        root = self._repo()
        cff_path = root / "CITATION.cff"
        cff = cff_path.read_text(encoding="utf-8")
        cff_path.write_text(
            cff.replace('version: "0.2.0"', 'version: "0.2.0" # current'),
            encoding="utf-8",
        )
        self.assertEqual(validate(root), [])

    def test_duplicate_archtoolkit_bibtex_entry_is_rejected(self):
        extra = (
            "```bibtex\n"
            "@software{ArchToolkit2026,\n"
            "  url = {https://github.com/lzpxilfe/archtoolkit},\n"
            "  version = {0.2.0}\n"
            "}\n"
            "```\n"
        )
        errors = validate(self._repo(extra_readme=extra))
        self.assertTrue(any("exactly one ArchToolkit" in error for error in errors))

    def test_duplicate_archtoolkit_entries_in_one_block_are_rejected(self):
        root = self._repo()
        readme_path = root / "README.md"
        readme = readme_path.read_text(encoding="utf-8")
        duplicate = (
            "@software{ArchToolkitDuplicate,\n"
            "  url = {https://github.com/lzpxilfe/archtoolkit},\n"
            "  version = {0.2.0}\n"
            "}\n"
        )
        readme_path.write_text(
            readme.replace("}\n```", "}\n" + duplicate + "```"),
            encoding="utf-8",
        )
        errors = validate(root)
        self.assertTrue(any("exactly one ArchToolkit" in error for error in errors))

    def test_archtoolkit_bibtex_entry_requires_balanced_braces(self):
        root = self._repo()
        readme_path = root / "README.md"
        readme = readme_path.read_text(encoding="utf-8")
        readme_path.write_text(
            readme.replace("}\n```", "```"),
            encoding="utf-8",
        )
        errors = validate(root)
        self.assertTrue(any("unbalanced braces" in error for error in errors))

    def test_changelog_version_requires_a_boundary(self):
        errors = validate(self._repo(changelog_version="0.2.01"))
        self.assertTrue(any("changelog must start" in error for error in errors))

    def test_duplicate_version_badges_are_rejected(self):
        root = self._repo()
        readme = (root / "README.md").read_text(encoding="utf-8")
        (root / "README.md").write_text(
            readme + '<img alt="Version 0.2.0" src="https://img.shields.io/badge/version-0.2.0-blue">\n',
            encoding="utf-8",
        )
        errors = validate(root)
        self.assertTrue(any("exactly one Version badge" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
