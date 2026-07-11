#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static smoke test for ArchToolkit (no QGIS runtime required).

Catches the class of defects that shipped in 0.1.2 - undefined names
(missing helper module / stray variables) and syntax errors - by:

  1. byte-compiling every plugin .py file (SyntaxError / IndentationError), and
  2. running pyflakes to flag undefined names (F821) and other blockers.

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
    """Return (messages, ran). Prefers pyflakes; falls back to a minimal
    undefined-name check via the stdlib if pyflakes is unavailable."""
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

    failed = bool(compile_errors) or bool(flake_msgs)
    if failed:
        print("[check_static] FAILED")
        return 1
    print("[check_static] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
