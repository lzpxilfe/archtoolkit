# -*- coding: utf-8 -*-
"""Dependency-free helpers for transactional directory publication.

Long-running tools write into a marked staging directory and rename the whole
directory only after every required output has been validated.  The ownership
marker prevents cleanup code from deleting an arbitrary user directory.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from pathlib import Path


MARKER_NAME = ".archtoolkit-staging.json"
_SHARED_DIRECTORY_BITS = stat.S_IRWXG | stat.S_IRWXO | stat.S_ISGID
_SHARED_FILE_BITS = stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH


def _safe_component(value: str, fallback: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(value or ""))
    return cleaned.strip("_") or fallback


def _ensure_private_owner_access(path: Path) -> None:
    """Best-effort repair of the private mode requested by ``mkdtemp``.

    ``mkdtemp`` requests mode 0700, but an unusual umask may remove owner bits.
    Changing the process umask here would be thread-unsafe, so POSIX callers get
    an explicit chmod instead.  Only an inherited setgid bit is preserved; a
    live staging root must never expose partial files to group/other users.
    Failure is intentionally non-fatal: the usual 0700 mode may already be
    usable, and marker creation below remains the authoritative access check.
    """
    if os.name != "posix":
        return
    try:
        current_mode = stat.S_IMODE(path.stat().st_mode)
        private_mode = stat.S_IRWXU | (current_mode & stat.S_ISGID)
        os.chmod(path, private_mode)
    except (OSError, NotImplementedError):
        pass


def _ensure_marker_owner_access(path: Path) -> None:
    """Keep the private marker readable under even an owner-masking umask."""
    if os.name != "posix":
        return
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except (OSError, NotImplementedError):
        # With an ordinary umask the marker is already owner-readable.  If it
        # is not, a later validation fails closed instead of deleting blindly.
        pass


def _shared_directory_mode(parent_mode: int) -> int:
    return stat.S_IRWXU | (parent_mode & _SHARED_DIRECTORY_BITS)


def _shared_file_mode(parent_mode: int) -> int:
    return stat.S_IRUSR | stat.S_IWUSR | (parent_mode & _SHARED_FILE_BITS)


def _chmod_without_following(path: Path, mode: int, *, directory: bool) -> None:
    """Best-effort chmod of a known file type, never a symbolic link."""
    if os.name != "posix":
        return
    try:
        current_mode = os.lstat(path).st_mode
        expected = (
            stat.S_ISDIR(current_mode)
            if directory
            else stat.S_ISREG(current_mode)
        )
        if stat.S_ISLNK(current_mode) or not expected:
            return

        if os.chmod in os.supports_follow_symlinks:
            os.chmod(path, mode, follow_symlinks=False)
            return

        # Some POSIX builds cannot express no-follow chmod by pathname.  Use a
        # no-follow descriptor there; if O_NOFOLLOW is unavailable, skip the
        # convenience chmod rather than risk modifying an external target.
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None or not hasattr(os, "fchmod"):
            return
        flags = os.O_RDONLY | no_follow | getattr(os, "O_CLOEXEC", 0)
        if directory:
            flags |= getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path, flags)
        try:
            opened_mode = os.fstat(descriptor).st_mode
            opened_expected = (
                stat.S_ISDIR(opened_mode)
                if directory
                else stat.S_ISREG(opened_mode)
            )
            if opened_expected:
                os.fchmod(descriptor, mode)
        finally:
            os.close(descriptor)
    except (OSError, NotImplementedError):
        # Sharing permissions are a convenience.  A chmod failure must not
        # discard a complete bundle or undo its atomic rename.
        pass


def _prepare_children_for_publication(staging: Path, parent_mode: int) -> None:
    """Prepare descendants while the staging root remains private.

    Regular files receive owner rw and only the parent's group/other r/w bits;
    executability is never inferred from a directory.  Nested directories get
    owner rwx, the parent's group/other rwx policy, and its setgid intent.
    os.walk is explicitly non-following, and symlinks are removed from descent
    and skipped by the no-follow chmod helper.
    """
    if os.name != "posix":
        return
    directory_mode = _shared_directory_mode(parent_mode)
    file_mode = _shared_file_mode(parent_mode)
    for root, directory_names, file_names in os.walk(
        staging, topdown=True, followlinks=False
    ):
        root_path = Path(root)
        traversable_names = []
        for name in directory_names:
            child = root_path / name
            try:
                child_mode = os.lstat(child).st_mode
            except OSError:
                continue
            if stat.S_ISLNK(child_mode) or not stat.S_ISDIR(child_mode):
                continue
            traversable_names.append(name)
            _chmod_without_following(child, directory_mode, directory=True)
        directory_names[:] = traversable_names

        for name in file_names:
            if root_path == staging and name == MARKER_NAME:
                continue
            _chmod_without_following(
                root_path / name, file_mode, directory=False
            )


def create_staging_dir(parent_dir: str, run_id: str, *, purpose: str) -> str:
    """Create a marked staging directory on the destination filesystem."""
    parent = Path(parent_dir).expanduser() if parent_dir else Path(tempfile.gettempdir())
    parent.mkdir(parents=True, exist_ok=True)
    safe_purpose = _safe_component(purpose, "output")
    safe_run_id = _safe_component(run_id, "run")
    path = Path(tempfile.mkdtemp(
        prefix=f".archtoolkit_{safe_purpose}_{safe_run_id}_",
        suffix=".staging",
        dir=str(parent),
    ))
    _ensure_private_owner_access(path)
    marker = {
        "owner": "ArchToolkit",
        "purpose": safe_purpose,
        "run_id": safe_run_id,
    }
    marker_path = path / MARKER_NAME
    try:
        marker_path.write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")
        _ensure_marker_owner_access(marker_path)
    except Exception:
        shutil.rmtree(path, ignore_errors=True)
        raise
    return str(path)


def _require_staging_dir(path: str) -> Path:
    staging = Path(path)
    try:
        staging_mode = staging.lstat().st_mode
    except OSError as exc:
        raise ValueError(f"Staging directory does not exist: {staging}") from exc
    if stat.S_ISLNK(staging_mode):
        raise ValueError(f"Refusing to manage a staging symlink: {staging}")
    if not stat.S_ISDIR(staging_mode):
        raise ValueError(f"Staging directory does not exist: {staging}")
    if not staging.name.endswith(".staging"):
        raise ValueError(f"Refusing to manage a non-staging directory: {staging}")
    marker = staging / MARKER_NAME
    try:
        marker_mode = marker.lstat().st_mode
    except OSError as exc:
        raise ValueError(
            f"Refusing to manage an unmarked directory: {staging}"
        ) from exc
    if stat.S_ISLNK(marker_mode):
        raise ValueError(f"Refusing to trust a staging marker symlink: {marker}")
    if not stat.S_ISREG(marker_mode):
        raise ValueError(f"Refusing to manage an unmarked directory: {staging}")
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid staging marker: {marker}") from exc
    if data.get("owner") != "ArchToolkit":
        raise ValueError(f"Staging marker has an unexpected owner: {marker}")
    return staging


def cleanup_staging_dir(path: str) -> bool:
    """Remove a marked staging directory; never remove an unmarked directory."""
    if not path or not os.path.lexists(path):
        return False
    staging = _require_staging_dir(path)
    shutil.rmtree(staging)
    return True


def publish_staging_dir(path: str, parent_dir: str, final_name: str) -> str:
    """Atomically rename a complete staging directory into its final location."""
    staging = _require_staging_dir(path)
    parent = Path(parent_dir).expanduser() if parent_dir else Path(tempfile.gettempdir())
    parent.mkdir(parents=True, exist_ok=True)
    if staging.parent.resolve(strict=True) != parent.resolve(strict=True):
        raise ValueError(
            "Staging and publication directories must have the same parent"
        )
    safe_name = _safe_component(final_name, "archtoolkit_output")
    final_dir = parent / safe_name
    if os.path.lexists(final_dir):
        raise FileExistsError(f"Output bundle already exists: {final_dir}")
    try:
        parent_mode = stat.S_IMODE(parent.stat().st_mode)
    except OSError:
        parent_mode = None
    if parent_mode is not None:
        _prepare_children_for_publication(staging, parent_mode)
    os.replace(staging, final_dir)
    try:
        (final_dir / MARKER_NAME).unlink()
    except Exception:
        # The output bundle is already complete and published.  A stale marker
        # is harmless, while rolling back a successful atomic rename is riskier.
        pass
    # The root stays private through descendant preparation, rename, and marker
    # removal.  Widening it last exposes only a complete published bundle.
    if parent_mode is not None:
        _chmod_without_following(
            final_dir, _shared_directory_mode(parent_mode), directory=True
        )
    return str(final_dir)
