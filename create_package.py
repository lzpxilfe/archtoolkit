from __future__ import annotations

import sys
import zipfile
from pathlib import Path


PLUGIN_DIR_NAME = "ArchToolkit"
EXCLUDED_DIR_NAMES = {
    ".agent",
    ".git",
    ".idea",
    ".pytest_cache",
    ".ruff_cache",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
}
EXCLUDED_FILE_NAMES = {
    ".DS_Store",
    ".gitignore",
    "RELEASE_HARDENING_PLAN.md",
    "Thumbs.db",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def _iter_plugin_files(source_dir: Path, *, output_path: Path):
    output_path = output_path.resolve()
    for path in sorted(source_dir.rglob("*")):
        if path.is_dir():
            continue
        rel_parts = path.relative_to(source_dir).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts):
            continue
        if path.name.startswith("."):
            continue
        if path.name in EXCLUDED_FILE_NAMES:
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        if path.name.endswith("~"):
            continue
        if path.resolve() == output_path:
            continue
        yield path


def _read_plugin_version(source_dir: Path) -> str:
    metadata_path = source_dir / "metadata.txt"
    if not metadata_path.exists():
        return "dev"

    try:
        for line in metadata_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("version="):
                version = line.split("=", 1)[1].strip()
                if version:
                    return version
    except Exception:
        pass

    return "dev"


def create_plugin_zip(output_path: Path) -> int:
    source_dir = Path(__file__).resolve().parent
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    added_count = 0
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for src_path in _iter_plugin_files(source_dir, output_path=output_path):
            rel_path = src_path.relative_to(source_dir).as_posix()
            archive.write(src_path, f"{PLUGIN_DIR_NAME}/{rel_path}")
            added_count += 1
    return added_count


def main(argv: list[str]) -> int:
    source_dir = Path(__file__).resolve().parent
    version = _read_plugin_version(source_dir)

    if len(argv) > 1:
        output_path = Path(argv[1])
    else:
        output_path = source_dir / "dist" / f"{PLUGIN_DIR_NAME}_v{version}.zip"

    count = create_plugin_zip(output_path)
    print(f"Created {output_path} ({count} file(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
