"""Every image the repository shows or the plugin loads must actually be committed.

Release 0.1.4 shipped with 13 plugin icons and 20 README screenshots present on
the developer's disk but ignored by a blanket ``*.png`` rule in .gitignore, so
GitHub showed broken images and a fresh clone had no icons. These checks run
``git`` when it is available (locally and in CI checkouts) and are skipped
elsewhere, for example inside an unpacked plugin ZIP.
"""
from __future__ import annotations

import os
import re
import subprocess
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IMAGE_DIRS = ("icons", os.path.join("docs", "images"), os.path.join("docs", "art"))
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".xpm")
IMG_REF = re.compile(r'!\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)|<img[^>]+src="([^"]+)"')


def _git(*args):
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out


def _git_available():
    out = _git("rev-parse", "--is-inside-work-tree")
    return bool(out) and out.returncode == 0 and out.stdout.strip() == "true"


def _tracked_files():
    out = _git("ls-files", "-z")
    return set(p for p in out.stdout.split("\0") if p)


def _markdown_image_refs():
    refs = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "dist", "hidden", ".agent")]
        for name in filenames:
            if not name.endswith(".md"):
                continue
            md = os.path.join(dirpath, name)
            with open(md, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for m in IMG_REF.finditer(text):
                ref = m.group(1) or m.group(2)
                if ref.startswith(("http://", "https://", "data:")):
                    continue
                target = os.path.normpath(os.path.join(dirpath, ref.split("#")[0].split("?")[0]))
                refs.append((os.path.relpath(md, ROOT), ref, os.path.relpath(target, ROOT)))
    return refs


def _image_files():
    found = []
    for d in IMAGE_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if name.lower().endswith(IMAGE_SUFFIXES):
                found.append(os.path.join(d, name))
    return found


class RepositoryImageTests(unittest.TestCase):
    def test_markdown_images_exist(self):
        missing = [f"{md}: {ref}" for md, ref, target in _markdown_image_refs()
                   if not os.path.isfile(os.path.join(ROOT, target))]
        self.assertEqual([], missing, "markdown references images that do not exist:\n" + "\n".join(missing))

    def test_plugin_icons_exist(self):
        # Every icon name the sources ask for, and the metadata icon, must be a file in icons/.
        # A call may list fallbacks (icon("trench.png", "archtoolkit.png")); at least one
        # of the literal names must exist, otherwise the tool silently gets the default icon.
        calls = []
        sources = [os.path.join(ROOT, "arch_toolkit.py")] + [
            os.path.join(ROOT, "tools", n) for n in os.listdir(os.path.join(ROOT, "tools")) if n.endswith(".py")]
        for path in sources:
            with open(path, encoding="utf-8") as fh:
                for m in re.finditer(r'\b(?:plugin_icon|icon|icon_path)\(((?:\s*"[^"]+\.(?:png|xpm|svg)"\s*,?)+)\)', fh.read()):
                    names = re.findall(r'"([^"]+)"', m.group(1))
                    calls.append((os.path.relpath(path, ROOT), names))
        with open(os.path.join(ROOT, "metadata.txt"), encoding="utf-8") as fh:
            m = re.search(r"^icon=(.+)$", fh.read(), re.M)
        self.assertIsNotNone(m, "metadata.txt has no icon= entry")
        meta_icon = m.group(1).strip()
        self.assertTrue(os.path.isfile(os.path.join(ROOT, meta_icon)), f"metadata icon missing: {meta_icon}")
        self.assertTrue(calls, "no icon(...) calls found in the sources")
        missing = sorted(f"{path}: {names}" for path, names in calls
                         if not any(os.path.isfile(os.path.join(ROOT, "icons", n)) for n in names))
        self.assertEqual([], missing, "icon calls whose names all miss icons/ (would fall back silently):\n" + "\n".join(missing))

    @unittest.skipUnless(_git_available(), "not a git checkout")
    def test_images_are_tracked_and_not_ignored(self):
        tracked = _tracked_files()
        files = _image_files()
        self.assertTrue(files, "no image files found under the image folders")
        untracked = [f for f in files if f.replace(os.sep, "/") not in tracked]
        self.assertEqual([], untracked, "images on disk but not committed (check .gitignore):\n" + "\n".join(untracked))
        # A tracked file can still match an ignore rule; that would silently drop the next new image.
        out = _git("check-ignore", "--no-index", "--", *files)
        ignored = [ln for ln in (out.stdout.splitlines() if out else []) if ln.strip()]
        self.assertEqual([], ignored, "image files matched by a .gitignore rule:\n" + "\n".join(ignored))
        # And every image markdown points at must be committed, or GitHub shows a broken picture.
        unpublished = [f"{md}: {ref}" for md, ref, target in _markdown_image_refs()
                       if target.replace(os.sep, "/") not in tracked]
        self.assertEqual([], unpublished, "markdown images not committed:\n" + "\n".join(unpublished))


if __name__ == "__main__":
    unittest.main()
