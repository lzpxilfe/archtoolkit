from __future__ import annotations

import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import atomic_output
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

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks required")
    def test_cleanup_rejects_staging_directory_symlink(self):
        staging = self._stage()
        alias = self.export / ".archtoolkit_alias.staging"
        alias.symlink_to(staging, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "staging symlink"):
            cleanup_staging_dir(str(alias))

        self.assertTrue(staging.exists())
        alias.unlink()
        self.assertTrue(cleanup_staging_dir(str(staging)))

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks required")
    def test_cleanup_rejects_marker_symlink(self):
        staging = self._stage()
        marker = staging / MARKER_NAME
        marker_text = marker.read_text(encoding="utf-8")
        marker.unlink()
        external_marker = self.root / "external-marker.json"
        external_marker.write_text(marker_text, encoding="utf-8")
        marker.symlink_to(external_marker)

        with self.assertRaisesRegex(ValueError, "marker symlink"):
            cleanup_staging_dir(str(staging))

        self.assertEqual(external_marker.read_text(encoding="utf-8"), marker_text)
        marker.unlink()
        marker.write_text(marker_text, encoding="utf-8")
        self.assertTrue(cleanup_staging_dir(str(staging)))

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits required")
    def test_live_staging_root_stays_private_despite_shared_parent(self):
        os.chmod(self.export, 0o2775)
        old_umask = os.umask(0o077)
        try:
            staging = self._stage()
        finally:
            os.umask(old_umask)

        mode = stat.S_IMODE(staging.stat().st_mode)
        self.assertEqual(mode & stat.S_IRWXU, stat.S_IRWXU)
        self.assertEqual(mode & (stat.S_IRWXG | stat.S_IRWXO), 0)
        self.assertEqual(mode & ~(stat.S_IRWXU | stat.S_ISGID), 0)

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits required")
    def test_owner_access_is_restored_when_umask_masks_owner_bits(self):
        os.chmod(self.export, 0o750)
        old_umask = os.umask(0o777)
        try:
            staging = self._stage()
        finally:
            os.umask(old_umask)

        self.assertEqual(stat.S_IMODE(staging.stat().st_mode), 0o700)
        # Marker repair makes the private directory manageable after restoring
        # the process-wide umask; production code never changes the umask.
        self.assertTrue(cleanup_staging_dir(str(staging)))

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits required")
    def test_restrictive_umask_children_get_shared_modes_at_publish(self):
        os.chmod(self.export, 0o2775)
        old_umask = os.umask(0o077)
        try:
            staging = self._stage()
            direct_file = staging / "layer.tif"
            direct_file.write_text("direct", encoding="utf-8")
            nested_dir = staging / "nested"
            nested_dir.mkdir()
            deep_dir = nested_dir / "deep"
            deep_dir.mkdir()
            nested_file = deep_dir / "layer.tif.aux.xml"
            nested_file.write_text("nested", encoding="utf-8")
        finally:
            os.umask(old_umask)

        self.assertEqual(
            stat.S_IMODE(staging.stat().st_mode)
            & (stat.S_IRWXG | stat.S_IRWXO),
            0,
        )
        final_dir = Path(publish_staging_dir(
            str(staging), str(self.export), "aligned_stack_run-1"
        ))

        self.assertEqual(stat.S_IMODE(final_dir.stat().st_mode), 0o2775)
        self.assertEqual(
            stat.S_IMODE((final_dir / direct_file.name).stat().st_mode),
            0o664,
        )
        self.assertEqual(
            stat.S_IMODE((final_dir / "nested").stat().st_mode),
            0o2775,
        )
        self.assertEqual(
            stat.S_IMODE((final_dir / "nested" / "deep").stat().st_mode),
            0o2775,
        )
        self.assertEqual(
            stat.S_IMODE(
                (final_dir / "nested" / "deep" / nested_file.name).stat().st_mode
            ),
            0o664,
        )

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks required")
    def test_publish_skips_symlink_and_does_not_chmod_external_target(self):
        os.chmod(self.export, 0o2775)
        external = self.root / "external.tif"
        external.write_text("external", encoding="utf-8")
        os.chmod(external, 0o600)
        staging = self._stage()
        (staging / "external-link.tif").symlink_to(external)

        final_dir = Path(publish_staging_dir(
            str(staging), str(self.export), "aligned_stack_run-1"
        ))

        self.assertTrue((final_dir / "external-link.tif").is_symlink())
        self.assertEqual(stat.S_IMODE(external.stat().st_mode), 0o600)

    def test_publish_requires_same_resolved_parent(self):
        staging_parent = self.root / "other-parent"
        staging_parent.mkdir()
        staging = Path(create_staging_dir(
            str(staging_parent), "run-1", purpose="align"
        ))
        (staging / "layer.tif").write_text("complete", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "same parent"):
            publish_staging_dir(
                str(staging), str(self.export), "aligned_stack_run-1"
            )

        self.assertTrue(staging.exists())
        self.assertFalse((self.export / "aligned_stack_run-1").exists())
        self.assertTrue(cleanup_staging_dir(str(staging)))

    @unittest.skipUnless(os.name == "posix", "POSIX setgid required")
    def test_setgid_parent_group_is_inherited_by_staging(self):
        os.chmod(self.export, 0o2770)
        if not stat.S_IMODE(self.export.stat().st_mode) & stat.S_ISGID:
            self.skipTest("filesystem does not retain setgid on directories")

        staging = self._stage()

        self.assertEqual(staging.stat().st_gid, self.export.stat().st_gid)

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits required")
    def test_final_root_is_widened_only_after_marker_removal(self):
        os.chmod(self.export, 0o2775)
        staging = self._stage()
        layer = staging / "layer.tif"
        layer.write_text("complete", encoding="utf-8")
        private_mode = stat.S_IMODE(staging.stat().st_mode)
        observed_modes = []
        real_unlink = Path.unlink

        def observe_unlink(path, *args, **kwargs):
            if path.name == MARKER_NAME:
                observed_modes.append((
                    stat.S_IMODE(path.parent.stat().st_mode),
                    stat.S_IMODE((path.parent / layer.name).stat().st_mode),
                ))
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", new=observe_unlink):
            final_dir = Path(publish_staging_dir(
                str(staging), str(self.export), "aligned_stack_run-1"
            ))

        self.assertEqual(observed_modes, [(private_mode, 0o664)])
        self.assertEqual(stat.S_IMODE(final_dir.stat().st_mode), 0o2775)

    def test_chmod_failure_does_not_abort_staging_creation(self):
        with mock.patch(
            "tools.atomic_output.os.chmod",
            side_effect=PermissionError("chmod denied"),
        ):
            staging = self._stage()

        self.assertTrue((staging / MARKER_NAME).is_file())
        self.assertTrue(cleanup_staging_dir(str(staging)))

    def test_chmod_failure_after_rename_does_not_undo_publication(self):
        staging = self._stage()
        (staging / "layer.tif").write_text("complete", encoding="utf-8")

        with (
            mock.patch(
                "tools.atomic_output.os.chmod",
                side_effect=PermissionError("chmod denied"),
            ),
            mock.patch(
                "tools.atomic_output.os.fchmod",
                side_effect=PermissionError("fchmod denied"),
            ),
        ):
            final_dir = Path(publish_staging_dir(
                str(staging), str(self.export), "aligned_stack_run-1"
            ))

        self.assertFalse(staging.exists())
        self.assertEqual(
            (final_dir / "layer.tif").read_text(encoding="utf-8"),
            "complete",
        )

    def test_windows_policy_skips_posix_chmod(self):
        staging = self._stage()
        with (
            mock.patch("tools.atomic_output.os.name", "nt"),
            mock.patch("tools.atomic_output.os.chmod") as chmod,
            mock.patch("tools.atomic_output.os.fchmod") as fchmod,
        ):
            atomic_output._ensure_private_owner_access(staging)
            atomic_output._prepare_children_for_publication(staging, 0o2775)
            atomic_output._chmod_without_following(
                staging, 0o2775, directory=True
            )

        chmod.assert_not_called()
        fchmod.assert_not_called()
        self.assertTrue(cleanup_staging_dir(str(staging)))


class AtomicFilePublishTests(unittest.TestCase):
    """Single-file / file-pair atomic publication used by long-running tools."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "out"
        self.out.mkdir()

    def _reserve(self, final, run_id="run-1"):
        return atomic_output.reserve_staging_path(str(final), run_id)

    def test_reserve_is_hidden_sibling_that_keeps_extension(self):
        final = self.out / "dem.tif"
        staged = Path(self._reserve(final))

        self.assertEqual(staged.parent, self.out)
        self.assertEqual(staged.suffix, ".tif")
        self.assertTrue(staged.name.startswith(".dem"))
        self.assertIn(atomic_output._STAGING_FILE_INFIX, staged.name)
        # Path is only computed, never created, so writers that refuse to
        # overwrite an existing destination still work.
        self.assertFalse(staged.exists())

    def test_reserve_creates_missing_parent_directory(self):
        final = self.out / "nested" / "sub" / "dem.tif"
        staged = Path(self._reserve(final))

        self.assertTrue(staged.parent.is_dir())
        self.assertEqual(staged.parent, final.parent)

    def test_reserve_avoids_a_leftover_staging_file(self):
        final = self.out / "dem.tif"
        first = Path(self._reserve(final))
        first.write_text("leftover", encoding="utf-8")

        second = Path(self._reserve(final))

        self.assertNotEqual(second, first)
        self.assertFalse(second.exists())

    def test_publish_file_replaces_destination_atomically(self):
        final = self.out / "dem.tif"
        final.write_text("old", encoding="utf-8")
        staged = Path(self._reserve(final))
        staged.write_text("new", encoding="utf-8")

        published = atomic_output.atomic_publish_file(str(staged), str(final))

        self.assertEqual(published, str(final))
        self.assertFalse(staged.exists())
        self.assertEqual(final.read_text(encoding="utf-8"), "new")

    def test_publish_file_rejects_empty_staged_output(self):
        final = self.out / "dem.tif"
        final.write_text("old", encoding="utf-8")
        staged = Path(self._reserve(final))
        staged.write_text("", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "empty"):
            atomic_output.atomic_publish_file(str(staged), str(final))

        # A rejected publish leaves the previous output untouched.
        self.assertEqual(final.read_text(encoding="utf-8"), "old")

    def test_publish_file_rejects_missing_staged_output(self):
        final = self.out / "dem.tif"
        staged = self._reserve(final)

        with self.assertRaisesRegex(ValueError, "missing"):
            atomic_output.atomic_publish_file(str(staged), str(final))

    def test_publish_file_requires_same_parent(self):
        final = self.out / "dem.tif"
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        staged = elsewhere / ("x" + atomic_output._STAGING_FILE_INFIX + "r.tif")
        staged.write_text("new", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "same parent|share a parent"):
            atomic_output.atomic_publish_file(str(staged), str(final))

        self.assertFalse(final.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks required")
    def test_publish_file_refuses_symlink_source_and_spares_target(self):
        final = self.out / "dem.tif"
        external = self.root / "external.tif"
        external.write_text("external", encoding="utf-8")
        staged = self.out / ("x" + atomic_output._STAGING_FILE_INFIX + "r.tif")
        staged.symlink_to(external)

        with self.assertRaisesRegex(ValueError, "symlink"):
            atomic_output.atomic_publish_file(str(staged), str(final))

        self.assertTrue(staged.is_symlink())
        self.assertEqual(external.read_text(encoding="utf-8"), "external")
        self.assertFalse(final.exists())

    def test_publish_files_publishes_a_pair_together(self):
        pred_final = self.out / "dem.tif"
        var_final = self.out / "dem_variance.tif"
        pred = Path(self._reserve(pred_final))
        var = Path(self._reserve(var_final))
        pred.write_text("pred", encoding="utf-8")
        var.write_text("var", encoding="utf-8")

        published = atomic_output.atomic_publish_files([
            (str(pred), str(pred_final)),
            (str(var), str(var_final)),
        ])

        self.assertEqual(published, [str(pred_final), str(var_final)])
        self.assertEqual(pred_final.read_text(encoding="utf-8"), "pred")
        self.assertEqual(var_final.read_text(encoding="utf-8"), "var")

    def test_publish_files_validates_all_before_renaming_any(self):
        pred_final = self.out / "dem.tif"
        var_final = self.out / "dem_variance.tif"
        pred_final.write_text("old-pred", encoding="utf-8")
        pred = Path(self._reserve(pred_final))
        var = Path(self._reserve(var_final))
        pred.write_text("pred", encoding="utf-8")
        var.write_text("", encoding="utf-8")  # variance failed to write

        with self.assertRaisesRegex(ValueError, "empty"):
            atomic_output.atomic_publish_files([
                (str(pred), str(pred_final)),
                (str(var), str(var_final)),
            ])

        # Neither final is touched: the good prediction stays staged, the old
        # prediction output is preserved, and no half-variance appears.
        self.assertEqual(pred_final.read_text(encoding="utf-8"), "old-pred")
        self.assertTrue(pred.exists())
        self.assertFalse(var_final.exists())

    def test_cleanup_removes_reserved_staging_file(self):
        final = self.out / "dem.tif"
        staged = Path(self._reserve(final))
        staged.write_text("partial", encoding="utf-8")

        self.assertTrue(atomic_output.cleanup_staging_path(str(staged)))
        self.assertFalse(staged.exists())

    def test_cleanup_refuses_a_non_staging_path(self):
        final = self.out / "dem.tif"
        final.write_text("real output", encoding="utf-8")

        self.assertFalse(atomic_output.cleanup_staging_path(str(final)))
        self.assertEqual(final.read_text(encoding="utf-8"), "real output")

    def test_cleanup_is_silent_on_missing_file(self):
        missing = self.out / (".gone" + atomic_output._STAGING_FILE_INFIX + "r.tif")
        self.assertFalse(atomic_output.cleanup_staging_path(str(missing)))
        self.assertFalse(atomic_output.cleanup_staging_path(""))

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks required")
    def test_cleanup_refuses_a_staging_symlink(self):
        external = self.root / "external.tif"
        external.write_text("external", encoding="utf-8")
        link = self.out / ("x" + atomic_output._STAGING_FILE_INFIX + "r.tif")
        link.symlink_to(external)

        self.assertFalse(atomic_output.cleanup_staging_path(str(link)))
        self.assertTrue(link.is_symlink())
        self.assertEqual(external.read_text(encoding="utf-8"), "external")


if __name__ == "__main__":
    unittest.main()
