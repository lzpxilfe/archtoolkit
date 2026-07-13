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
import tempfile
from pathlib import Path


MARKER_NAME = ".archtoolkit-staging.json"


def _safe_component(value: str, fallback: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(value or ""))
    return cleaned.strip("_") or fallback


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
    marker = {
        "owner": "ArchToolkit",
        "purpose": safe_purpose,
        "run_id": safe_run_id,
    }
    try:
        (path / MARKER_NAME).write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")
    except Exception:
        shutil.rmtree(path, ignore_errors=True)
        raise
    return str(path)


def _require_staging_dir(path: str) -> Path:
    staging = Path(path)
    if not staging.is_dir():
        raise ValueError(f"Staging directory does not exist: {staging}")
    if not staging.name.endswith(".staging"):
        raise ValueError(f"Refusing to manage a non-staging directory: {staging}")
    marker = staging / MARKER_NAME
    if not marker.is_file():
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
    if not path or not os.path.exists(path):
        return False
    staging = _require_staging_dir(path)
    shutil.rmtree(staging)
    return True


def publish_staging_dir(path: str, parent_dir: str, final_name: str) -> str:
    """Atomically rename a complete staging directory into its final location."""
    staging = _require_staging_dir(path)
    parent = Path(parent_dir).expanduser() if parent_dir else Path(tempfile.gettempdir())
    parent.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_component(final_name, "archtoolkit_output")
    final_dir = parent / safe_name
    if final_dir.exists():
        raise FileExistsError(f"Output bundle already exists: {final_dir}")
    os.replace(staging, final_dir)
    try:
        (final_dir / MARKER_NAME).unlink()
    except Exception:
        # The output bundle is already complete and published.  A stale marker
        # is harmless, while rolling back a successful atomic rename is riskier.
        pass
    return str(final_dir)
