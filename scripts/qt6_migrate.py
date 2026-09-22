#!/usr/bin/env python3
"""Rewrite unscoped Qt enum members to their scoped form, and verify against PyQt6.

PyQt6 (QGIS 4 builds) removed unscoped enum access: Qt.AlignCenter must be
Qt.AlignmentFlag.AlignCenter. PyQt5 5.15 accepts both spellings, so the scoped
form is the one that runs on QGIS 3.40 through 4.x.

Steps (each interpreter has one of the two bindings here):
  resolve : under PyQt5, find every `QClass.Member` token in the sources whose
            value is an enum member and record `QClass.EnumName.Member`.
  verify  : under PyQt6, check that every recorded scoped name exists.
  verify6 : under PyQt6, check that every Qt name the sources spell resolves.
  apply   : rewrite the sources using the verified mapping.

    /usr/bin/python3.12 scripts/qt6_migrate.py resolve  > /tmp/qt6_map.json
    python3            scripts/qt6_migrate.py verify   /tmp/qt6_map.json
    python3            scripts/qt6_migrate.py apply    /tmp/qt6_map.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# tools/qtcompat.py is the one place that may spell a PyQt5-only name (inside
# its fallback branch), so it is excluded from the scan.
SOURCES = [ROOT / "arch_toolkit.py"] + sorted(
    p for p in (ROOT / "tools").glob("*.py") if p.name != "qtcompat.py"
)
TOKEN_RE = re.compile(r"\b(Qt|Q[A-Z][A-Za-z0-9]+)\.([A-Za-z][A-Za-z0-9_]+)\b")  # members may be lower-case (Qt.black)
# Only members whose class we can import from the binding's core modules.
MODULES = ("QtCore", "QtGui", "QtWidgets", "QtSvg", "QtPrintSupport", "QtNetwork", "QtXml")


def _binding(name: str):
    import importlib
    mods = {}
    for m in MODULES:
        try:
            mods[m] = importlib.import_module(f"{name}.{m}")
        except Exception:
            pass
    return mods


def _lookup(mods, cls_name):
    for m in mods.values():
        c = getattr(m, cls_name, None)
        if c is not None:
            return c
    return None


def _scan():
    found = {}
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        # skip already-scoped tokens: the char before must not be a dot-path continuation
        for m in TOKEN_RE.finditer(text):
            cls, member = m.group(1), m.group(2)
            found.setdefault(f"{cls}.{member}", set()).add(path.name)
    return found


def resolve():
    """Return {"mapping": {unscoped: scoped}, "skipped": {token: reason}} under PyQt5."""
    mods = _binding("PyQt5")
    mapping, skipped = {}, {}
    for token in sorted(_scan()):
        cls_name, member = token.split(".", 1)
        cls = _lookup(mods, cls_name)
        if cls is None:
            continue  # QGIS class or not a Qt class
        try:
            value = getattr(cls, member)
        except AttributeError:
            skipped[token] = "no such attribute in PyQt5"
            continue
        vt = type(value)
        enum_name = getattr(vt, "__name__", "")
        # Enum members of nested enum classes: type is e.g. Qt.AlignmentFlag
        if enum_name and enum_name != member and hasattr(cls, enum_name) and getattr(cls, enum_name) is vt:
            mapping[token] = f"{cls_name}.{enum_name}.{member}"
        elif isinstance(value, type):
            skipped[token] = "nested class (kept)"
        else:
            skipped[token] = f"not an enum member ({enum_name})"
    return {"mapping": mapping, "skipped": skipped}


def verify_pyqt6_attributes():
    """Under PyQt6, return every `QClass.attr[.attr]` token in the sources that does not resolve.

    Catches both an unscoped enum that survived (Qt.AlignCenter) and a scoped
    name spelled wrongly (Qt.AlignmentFlag.Centre).
    """
    mods = _binding("PyQt6")
    chain_re = re.compile(r"\b(Qt|Q[A-Z][A-Za-z0-9]+)((?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
    bad = {}
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        for m in chain_re.finditer(text):
            parts = [m.group(1)] + m.group(2).lstrip(".").split(".")
            # skip a module alias prefix (QtWidgets.QDialog.exec): start at the first Qt class
            start = next((i for i, part in enumerate(parts[:-1]) if _lookup(mods, part) is not None), None)
            if start is None:
                continue
            obj = _lookup(mods, parts[start])
            walked = parts[start]
            for attr in parts[start + 1:]:
                if not hasattr(obj, attr):
                    bad.setdefault(f"{walked}.{attr}", set()).add(path.name)
                    break
                obj = getattr(obj, attr)
                walked = f"{walked}.{attr}"
                if not isinstance(obj, type):
                    break  # a method or value: nothing further to resolve statically
    return {k: sorted(v) for k, v in sorted(bad.items())}


def verify(map_path):
    data = json.load(open(map_path, encoding="utf-8"))
    mods = _binding("PyQt6")
    bad = []
    for token, scoped in sorted(data["mapping"].items()):
        cls_name, enum_name, member = scoped.split(".")
        cls = _lookup(mods, cls_name)
        enum = getattr(cls, enum_name, None) if cls is not None else None
        if enum is None or not hasattr(enum, member):
            bad.append((token, scoped))
    print(f"{len(data['mapping'])} scoped names, {len(bad)} missing in PyQt6")
    for t, s in bad:
        print("  MISSING", t, "->", s)
    return 1 if bad else 0


def apply(map_path):
    data = json.load(open(map_path, encoding="utf-8"))
    mapping = data["mapping"]
    total = 0
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        new = text
        for token, scoped in mapping.items():
            cls_name, member = token.split(".", 1)
            # replace Cls.Member (also behind a module prefix such as QtWidgets.) when not already scoped
            pattern = re.compile(r"(?<!\w)" + re.escape(cls_name) + r"\." + re.escape(member) + r"\b(?!\.[A-Z])")
            new, n = pattern.subn(scoped, new)
            total += n
        if new != text:
            path.write_text(new, encoding="utf-8")
            print("rewrote", path.name)
    print("replacements:", total)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "resolve":
        json.dump(resolve(), sys.stdout, indent=1, sort_keys=True)
    elif cmd == "verify6":
        missing = verify_pyqt6_attributes()
        for k, files in missing.items():
            print("  MISSING in PyQt6:", k, "in", ", ".join(files))
        print(f"{len(missing)} unresolved Qt names under PyQt6")
        sys.exit(1 if missing else 0)
    elif cmd == "verify":
        sys.exit(verify(sys.argv[2]))
    elif cmd == "apply":
        apply(sys.argv[2])
