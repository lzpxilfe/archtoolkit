from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.atomic_output import (
    MARKER_NAME,
    cleanup_staging_dir,
    create_staging_dir,
    publish_staging_dir,
)


class AtomicOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.export = self.root / "export"
        self.export.mkdir()

    def _stage(self, run_id="run-1") -> Path:
        return Path(create_staging_dir(str(self.export), run_id, purpose="align"))

    def test_cleanup_refuses_unmarked_directory(self):
        unmarked = self.root / "unmarked"
        unmarked.mkdir()

        with self.assertRaises(ValueError):
            cleanup_staging_dir(str(unmarked))

        self.assertTrue(unmarked.exists())

    def test_cleanup_removes_marked_staging_tree_and_sidecars(self):
        staging = self._stage()
        (staging / "partial.tif").write_text("partial", encoding="utf-8")
        (staging / "partial.tif.aux.xml").write_text("sidecar", encoding="utf-8")

        self.assertTrue(cleanup_staging_dir(str(staging)))

        self.assertFalse(staging.exists())

    def test_publish_renames_complete_bundle_and_removes_marker(self):
        staging = self._stage()
        (staging / "layer.tif").write_text("complete", encoding="utf-8")
        (staging / "aligned_stack_manifest.csv").write_text("manifest", encoding="utf-8")

        final_dir = Path(publish_staging_dir(
            str(staging), str(self.export), "aligned_stack_run-1"
        ))

        self.assertFalse(staging.exists())
        self.assertEqual((final_dir / "layer.tif").read_text(encoding="utf-8"), "complete")
        self.assertEqual(
            (final_dir / "aligned_stack_manifest.csv").read_text(encoding="utf-8"),
            "manifest",
        )
        self.assertFalse((final_dir / MARKER_NAME).exists())

    def test_published_bundle_is_not_cleanup_target_when_marker_unlink_fails(self):
        staging = self._stage()
        (staging / "layer.tif").write_text("complete", encoding="utf-8")

        with mock.patch(
            "tools.atomic_output.Path.unlink",
            side_effect=PermissionError("marker is locked"),
        ):
            final_dir = Path(publish_staging_dir(
                str(staging), str(self.export), "aligned_stack_run-1"
            ))

        self.assertTrue((final_dir / MARKER_NAME).exists())
        with self.assertRaises(ValueError):
            cleanup_staging_dir(str(final_dir))
        self.assertTrue(final_dir.exists())
        self.assertEqual(
            (final_dir / "layer.tif").read_text(encoding="utf-8"),
            "complete",
        )

    def test_publish_never_overwrites_existing_bundle(self):
        staging = self._stage()
        (staging / "layer.tif").write_text("new", encoding="utf-8")
        existing = self.export / "aligned_stack_run-1"
        existing.mkdir()
        (existing / "layer.tif").write_text("old", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            publish_staging_dir(str(staging), str(self.export), existing.name)

        self.assertEqual((existing / "layer.tif").read_text(encoding="utf-8"), "old")
        self.assertTrue(staging.exists())
        cleanup_staging_dir(str(staging))

    def test_publish_refuses_unmarked_source(self):
        unmarked = self.root / "unmarked"
        unmarked.mkdir()
        (unmarked / "layer.tif").write_text("data", encoding="utf-8")
        self.addCleanup(lambda: shutil.rmtree(unmarked, ignore_errors=True))

        with self.assertRaises(ValueError):
            publish_staging_dir(str(unmarked), str(self.export), "bundle")


if __name__ == "__main__":
    unittest.main()
