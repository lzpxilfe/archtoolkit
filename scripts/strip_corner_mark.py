#!/usr/bin/env python3
"""Remove the small four-pointed sparkle an image generator stamps in the bottom-right corner.

Gemini-made artwork carries a translucent star (about 44 px wide in a 1024 px
image, centred about 54 px from the right edge and 58 px from the bottom) that
shows on any background because it brightens dark pixels and darkens light
ones. The icon originals in docs/art/ had it, so the 256 px copies in icons/
inherited it.

The star footprint (a disc a little larger than the star) is inpainted from the
surrounding picture:

* ``flat``  - when the footprint sits on one flat colour (the dark panel behind
  the eye glyph in the cost and viewshed icons), every footprint pixel that is
  not part of a bright glyph takes the surrounding median colour.
* ``shift`` - otherwise, OpenCV's exemplar-based shift-map inpainting
  (``cv2.xphoto.inpaint``) copies matching patches from elsewhere in the image,
  which continues grids, frames and checkerboards convincingly. Needs
  ``pip install opencv-contrib-python-headless``.

``--method auto`` (default) picks ``flat`` when at least 85 percent of the
pixels around the footprint share one colour and almost nothing bright lies
inside it. Always look at the result; this is a repair tool for pixel art, not
a guarantee.

    python scripts/strip_corner_mark.py --out /tmp/cleaned docs/art/AHP.png
    python scripts/strip_corner_mark.py --in-place docs/art/*.png docs/art/*.jpg
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# Star geometry relative to the longer image side (measured on 1024 px originals).
CENTER_FROM_RIGHT = 54 / 1024
CENTER_FROM_BOTTOM = 58 / 1024
FOOTPRINT_RADIUS = 31 / 1024
RING_WIDTH = 10 / 1024
FLAT_SHARE = 0.85        # ring pixels that must share one colour for the flat method
FLAT_TOLERANCE = 20      # per-channel distance that still counts as "the same colour"
GLYPH_DISTANCE = 110     # footprint pixels farther than this from the flat colour are glyph, kept
GLYPH_SHARE_MAX = 0.02   # more glyph than this inside the footprint means it is not a flat area


def _disc(h: int, w: int, cx: float, cy: float, r: float) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    return (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r


def _choose(arr: np.ndarray, footprint: np.ndarray, ring: np.ndarray):
    ring_px = arr[ring][:, :3].astype(np.float32)
    median = np.median(ring_px, axis=0)
    share = (np.abs(ring_px - median).max(axis=1) < FLAT_TOLERANCE).mean()
    glyph = (np.abs(arr[footprint][:, :3].astype(np.float32) - median).max(axis=1) >= GLYPH_DISTANCE).mean()
    flat = share >= FLAT_SHARE and glyph <= GLYPH_SHARE_MAX
    return ("flat" if flat else "shift"), median, (share, glyph)


def _flat(arr: np.ndarray, footprint: np.ndarray, median: np.ndarray) -> np.ndarray:
    out = arr.copy()
    rgb = arr[..., :3].astype(np.float32)
    replace = footprint & (np.abs(rgb - median).max(axis=2) < GLYPH_DISTANCE)
    fill = np.rint(median).astype(np.uint8)
    out[replace, :3] = fill
    if arr.shape[2] == 4:
        ring_alpha = np.median(arr[..., 3][~footprint & _grow(footprint, 6)])
        out[replace, 3] = int(ring_alpha)
    return out


def _grow(mask: np.ndarray, n: int) -> np.ndarray:
    g = mask.copy()
    for _ in range(n):
        nxt = g.copy()
        nxt[1:, :] |= g[:-1, :]
        nxt[:-1, :] |= g[1:, :]
        nxt[:, 1:] |= g[:, :-1]
        nxt[:, :-1] |= g[:, 1:]
        g = nxt
    return g


def _shift(arr: np.ndarray, footprint: np.ndarray) -> np.ndarray:
    import cv2  # opencv-contrib-python-headless
    keep = (~footprint).astype(np.uint8) * 255  # cv2.xphoto: non-zero = known pixels
    rgb = np.ascontiguousarray(arr[..., :3])
    out_rgb = np.zeros_like(rgb)
    cv2.xphoto.inpaint(rgb, keep, out_rgb, cv2.xphoto.INPAINT_SHIFTMAP)
    if arr.shape[2] == 4:
        a3 = np.ascontiguousarray(np.repeat(arr[..., 3:4], 3, axis=2))
        out_a = np.zeros_like(a3)
        cv2.xphoto.inpaint(a3, keep, out_a, cv2.xphoto.INPAINT_SHIFTMAP)
        return np.dstack([out_rgb, out_a[..., 0]])
    return out_rgb


def strip(path: Path, out_path: Path, method: str = "auto") -> str:
    im = Image.open(path)
    mode = "RGB" if im.mode == "RGB" else "RGBA"
    arr = np.asarray(im.convert(mode)).copy()
    h, w = arr.shape[:2]
    size = max(h, w)
    cx = w - 1 - CENTER_FROM_RIGHT * size
    cy = h - 1 - CENTER_FROM_BOTTOM * size
    r = FOOTPRINT_RADIUS * size
    footprint = _disc(h, w, cx, cy, r)
    ring = _disc(h, w, cx, cy, r + RING_WIDTH * size) & ~footprint
    chosen, median, share = _choose(arr, footprint, ring)
    if method != "auto":
        chosen = method
    result = _flat(arr, footprint, median) if chosen == "flat" else _shift(arr, footprint)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs = {"quality": 95} if out_path.suffix.lower() in (".jpg", ".jpeg") else {}
    Image.fromarray(result, mode).save(out_path, **kwargs)
    return f"{chosen} (ring share of one colour {share[0]:.0%}, glyph inside footprint {share[1]:.0%})"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, help="directory for the cleaned copies")
    ap.add_argument("--in-place", action="store_true", help="overwrite the inputs")
    ap.add_argument("--method", choices=("auto", "flat", "shift"), default="auto")
    args = ap.parse_args(argv)
    if not args.out and not args.in_place:
        ap.error("give --out DIR or --in-place")
    for p in args.paths:
        dest = p if args.in_place else args.out / p.name
        print(f"{p}: {strip(p, dest, args.method)} -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
