#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static smoke test for ArchToolkit (no QGIS runtime required).

Catches the class of defects that shipped in 0.1.2 - undefined names
(missing helper module / stray variables) and syntax errors - by:

  1. byte-compiling every plugin .py file (SyntaxError / IndentationError),
  2. running pyflakes to flag undefined names (F821) and other blockers, and
  3. resolving every RELATIVE import to a file on disk (pyflakes/flake8 do
     not resolve modules, so a deleted/renamed tools/*.py used to keep CI
     green while the menu entry crashed at click time).

Run locally:   python tests/check_static.py
Exit code is non-zero if any file fails, so it doubles as a CI gate.
"""

from __future__ import annotations

import ast
import os
import sys
from typing import List, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", "dist", "build", ".venv"}


def _iter_py_files() -> List[str]:
    out: List[str] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".py"):
                out.append(os.path.join(root, name))
    return sorted(out)


def _compile_all(paths: List[str]) -> List[Tuple[str, str]]:
    errors: List[Tuple[str, str]] = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
            compile(source, path, "exec")
        except (SyntaxError, ValueError) as exc:
            errors.append((path, f"compile: {exc}"))
    return errors


def _pyflakes_all(paths: List[str]) -> Tuple[List[str], bool]:
    """Return (messages, ran). Compile-only when pyflakes is unavailable
    (a warning is printed; there is no stdlib undefined-name fallback)."""
    try:
        from pyflakes.api import check
        from pyflakes.reporter import Reporter
        import io

        out, err = io.StringIO(), io.StringIO()
        reporter = Reporter(out, err)
        problems = 0
        for path in paths:
            with open(path, "r", encoding="utf-8") as f:
                problems += check(f.read(), path, reporter)
        messages = [line for line in (out.getvalue() + err.getvalue()).splitlines() if line.strip()]
        # pyflakes returns a count; treat "undefined name" and syntax as fatal.
        fatal = [m for m in messages if "undefined name" in m or "invalid syntax" in m]
        return fatal, True
    except Exception:
        return [], False


def _relative_import_errors(paths: List[str]) -> List[Tuple[str, str]]:
    """Resolve `from .x import y` / `from ..pkg.mod import y` to files on disk.

    Static linters never resolve modules, so a missing tools/*.py is invisible
    to them. This walks each file's AST and demands that every relative import
    target exists as <target>.py or <target>/__init__.py.
    """
    errors: List[Tuple[str, str]] = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
        except Exception:
            continue  # compile errors are reported by _compile_all
        pkg_dir = os.path.dirname(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.level:
                continue
            # level=1 -> current package dir, level=2 -> parent, ...
            base = pkg_dir
            for _ in range(node.level - 1):
                base = os.path.dirname(base)
            parts = (node.module or "").split(".") if node.module else []
            target = os.path.join(base, *parts) if parts else base
            ok = (
                os.path.isfile(target + ".py")
                or os.path.isfile(os.path.join(target, "__init__.py"))
            )
            if not parts:
                # from . import a, b  -> each alias must be a module or defined
                # in the package __init__; require module file OR __init__.py.
                has_init = os.path.isfile(os.path.join(base, "__init__.py"))
                for alias in node.names:
                    mod_ok = (
                        os.path.isfile(os.path.join(base, alias.name + ".py"))
                        or os.path.isdir(os.path.join(base, alias.name))
                        or has_init
                    )
                    if not mod_ok:
                        errors.append((path, f"relative import target missing: .{alias.name} (line {node.lineno})"))
                continue
            if not ok:
                dotted = "." * node.level + (node.module or "")
                errors.append((path, f"relative import target missing: {dotted} (line {node.lineno})"))
    return errors


def main() -> int:
    paths = _iter_py_files()
    print(f"[check_static] scanning {len(paths)} Python files under {REPO_ROOT}")

    compile_errors = _compile_all(paths)
    for path, msg in compile_errors:
        print(f"  COMPILE FAIL {os.path.relpath(path, REPO_ROOT)}: {msg}")

    flake_msgs, ran = _pyflakes_all(paths)
    if ran:
        for msg in flake_msgs:
            print(f"  UNDEFINED/SYNTAX {msg}")
    else:
        print("  [warn] pyflakes not installed; ran compile-only checks "
              "(install pyflakes/flake8 for undefined-name detection)")

    import_errors = _relative_import_errors(paths)
    for path, msg in import_errors:
        print(f"  IMPORT FAIL {os.path.relpath(path, REPO_ROOT)}: {msg}")

    failed = bool(compile_errors) or bool(flake_msgs) or bool(import_errors)
    if failed:
        print("[check_static] FAILED")
        return 1
    print("[check_static] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
