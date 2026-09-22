#!/usr/bin/env python3
"""Build the ZIP that the QGIS plugin repository (plugins.qgis.org) accepts.

    python scripts/build_plugin_zip.py            # -> dist/ArchToolkit-<version>.zip
    python scripts/build_plugin_zip.py --check    # build, then verify the archive

The archive holds one top-level folder, ArchToolkit/, with only what the plugin
needs at run time: metadata.txt, __init__.py, arch_toolkit.py, tools/, icons/,
LICENSE, README.md, REFERENCES.md, CHANGELOG.md, CITATION.cff. Tests, docs,
scripts, CI config, caches and the original artwork stay out. Standard library
only, so it runs anywhere the release checks run.
"""
from __future__ import annotations

import argparse
import configparser
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "ArchToolkit"

INCLUDE_FILES = (
    "metadata.txt", "__init__.py", "arch_toolkit.py", "LICENSE", "README.md", "REFERENCES.md", "CHANGELOG.md", "CITATION.cff",
    # Text guides the in-plugin help points to (docs/AHP_GUIDE.md is cited by the AHP help).
    "docs/AHP_GUIDE.md", "docs/TOOLS.md",
)
INCLUDE_DIRS = ("tools", "icons")
EXCLUDE_DIR_NAMES = {"__pycache__", ".git", ".github", ".agent", "tests", "docs", "scripts", "dist"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".orig", ".rej", ".swp")
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db", "symbology-style.db", ".gitattributes", ".gitignore", ".flake8"}


def _version() -> str:
    cfg = configparser.ConfigParser()
    cfg.read(ROOT / "metadata.txt", encoding="utf-8")
    return cfg["general"]["version"].strip()


def _iter_files():
    for name in INCLUDE_FILES:
        p = ROOT / name
        if p.is_file():
            yield p
    for d in INCLUDE_DIRS:
        base = ROOT / d
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if any(part in EXCLUDE_DIR_NAMES for part in path.relative_to(ROOT).parts):
                continue
            if path.suffix in EXCLUDE_SUFFIXES or path.name in EXCLUDE_NAMES:
                continue
            yield path


def build(out_dir: Path) -> Path:
    version = _version()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{PACKAGE}-{version}.zip"
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in _iter_files():
            arcname = f"{PACKAGE}/{path.relative_to(ROOT).as_posix()}"
            zf.write(path, arcname)
    return out


def check(archive: Path) -> list:
    """Return a list of problems the plugin repository would reject the upload for."""
    errors = []
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        tops = {n.split("/", 1)[0] for n in names}
        if tops != {PACKAGE}:
            errors.append(f"archive must contain exactly one top-level folder {PACKAGE}/, found {sorted(tops)}")
        required = {f"{PACKAGE}/metadata.txt", f"{PACKAGE}/__init__.py"}
        missing = sorted(required - set(names))
        if missing:
            errors.append("missing required files: " + ", ".join(missing))
        bad = [n for n in names if "__pycache__" in n or n.endswith((".pyc", ".pyo")) or "/.git" in n or "__MACOSX" in n]
        if bad:
            errors.append("forbidden entries: " + ", ".join(bad[:5]))
        try:
            meta = zf.read(f"{PACKAGE}/metadata.txt").decode("utf-8")
            cfg = configparser.ConfigParser()
            cfg.read_string(meta)
            g = cfg["general"]
            required = ("name", "description", "about", "version", "qgisMinimumVersion", "author", "email",
                        "repository", "tracker", "homepage", "icon", "tags", "changelog", "license")
            for key in required:
                if not str(g.get(key, "")).strip():
                    errors.append(f"metadata.txt is missing '{key}'")
            if not re.match(r"^\d+\.\d+(\.\d+)?$", str(g.get("version", ""))):
                errors.append(f"metadata.txt version must be numeric (x.y or x.y.z), got {g.get('version')!r}")
            icon = str(g.get("icon", "")).strip()
            if icon and f"{PACKAGE}/{icon}" not in names:
                errors.append(f"icon '{icon}' is not inside the archive")
            for key in ("experimental", "deprecated", "server", "hasProcessingProvider"):
                v = str(g.get(key, "")).strip()
                if v and v not in ("True", "False", "true", "false"):
                    errors.append(f"metadata.txt {key} must be True or False, got {v!r}")
            init = zf.read(f"{PACKAGE}/__init__.py").decode("utf-8")
            if "def classFactory" not in init:
                errors.append("__init__.py must define classFactory(iface)")
        except KeyError:
            pass
        size = archive.stat().st_size
        if size > 25 * 1024 * 1024:
            errors.append(f"archive is {size / 1e6:.1f} MB; keep it well under 25 MB")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--check", action="store_true", help="verify the built archive")
    args = ap.parse_args()
    archive = build(Path(args.out))
    n = len(zipfile.ZipFile(archive).namelist())
    print(f"built {archive} ({archive.stat().st_size / 1024:.0f} KB, {n} entries)")
    if args.check:
        errors = check(archive)
        if errors:
            print("CHECK FAILED")
            for e in errors:
                print("  -", e)
            return 1
        print("CHECK OK: ready for plugins.qgis.org")
    return 0


if __name__ == "__main__":
    sys.exit(main())
