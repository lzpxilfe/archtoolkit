#!/usr/bin/env python3
"""Draw the two tool icons that had no artwork, in the style of the generated set.

The existing icons are 1024 px pixel-art cards: white margin, black outline,
navy panel, a scene, and a navy caption bar with white block letters. This
script borrows that frame from docs/art/terrain_icon.png, blanks the scene and
the caption, and draws:

* ``vif_icon.png``    - a correlation matrix beside VIF bars with the warning
                        line, captioned CORRELATION & VIF
* ``trench_icon.png`` - a survey area with numbered trench candidates,
                        captioned TRENCH PLAN

Scenes are drawn on an 8 px logical grid so they read as pixel art; captions
are DejaVu Sans Bold rendered without anti-aliasing and scaled up the same
way. Outputs: docs/art/<name>.png (1024 px) and icons/<name>.png (256 px).

    python scripts/make_tool_icons.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "art" / "terrain_icon.png"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
PX = 8                                  # real pixels per logical pixel
CONTENT = (85, 83, 939, 781)            # x0, y0, x1, y1 of the scene window (real px)
CAPTION = (48, 793, 976, 977)           # caption bar, real px
NAVY = (28, 40, 54)
INK = (12, 16, 24)
PAPER = (236, 238, 232)
GRID = (206, 210, 202)
RED = (229, 69, 60)
DARK_RED = (168, 36, 32)
BLUE = (72, 122, 190)
GREEN = (98, 160, 82)
GREEN_DARK = (70, 122, 60)
GREEN_LIGHT = (128, 186, 104)
EARTH = (196, 128, 70)
EARTH_DARK = (132, 80, 40)
YELLOW = (240, 206, 72)
WHITE = (250, 252, 255)


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _scene_canvas():
    w = (CONTENT[2] - CONTENT[0]) // PX
    h = (CONTENT[3] - CONTENT[1]) // PX
    return Image.new("RGB", (w, h), PAPER)


def _paper_grid(d, w, h, step=6):
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=GRID)
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=GRID)


def scene_vif():
    img = _scene_canvas()
    w, h = img.size
    d = ImageDraw.Draw(img)
    _paper_grid(d, w, h)
    # correlation matrix: 6 x 6 cells, diverging colours, dark diagonal
    n, cell, x0, y0 = 6, 7, 6, 10
    values = [
        [1.0, 0.8, -0.3, 0.1, 0.6, -0.7],
        [0.8, 1.0, -0.1, 0.3, 0.5, -0.6],
        [-0.3, -0.1, 1.0, 0.7, -0.2, 0.2],
        [0.1, 0.3, 0.7, 1.0, 0.0, -0.1],
        [0.6, 0.5, -0.2, 0.0, 1.0, -0.4],
        [-0.7, -0.6, 0.2, -0.1, -0.4, 1.0],
    ]
    for r in range(n):
        for c in range(n):
            v = values[r][c]
            colour = DARK_RED if r == c else (_lerp(WHITE, RED, v) if v >= 0 else _lerp(WHITE, BLUE, -v))
            x, y = x0 + c * cell, y0 + r * cell
            d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=colour, outline=INK)
    d.rectangle([x0 - 1, y0 - 1, x0 + n * cell, y0 + n * cell], outline=INK)
    # axis ticks (variable labels) as small dark marks
    for i in range(n):
        d.rectangle([x0 - 4, y0 + i * cell + 2, x0 - 3, y0 + i * cell + 4], fill=INK)
        d.rectangle([x0 + i * cell + 2, y0 + n * cell + 2, x0 + i * cell + 4, y0 + n * cell + 3], fill=INK)
    # VIF bars with the threshold line at "10"
    bx0, base, bw, gap = 58, 60, 6, 4
    heights = [14, 31, 9, 44, 20]           # 44 and 31 exceed the line
    limit_y = base - 28
    d.line([(bx0 - 4, base), (bx0 + len(heights) * (bw + gap), base)], fill=INK, width=1)
    d.line([(bx0 - 4, base), (bx0 - 4, 8)], fill=INK, width=1)
    for i, hgt in enumerate(heights):
        x = bx0 + i * (bw + gap)
        colour = RED if hgt > 28 else GREEN
        d.rectangle([x, base - hgt, x + bw - 1, base - 1], fill=colour, outline=INK)
    for x in range(bx0 - 4, bx0 + len(heights) * (bw + gap), 3):
        d.rectangle([x, limit_y, x + 1, limit_y], fill=DARK_RED)
    # warning marker at the right end of the threshold line
    xe = bx0 + len(heights) * (bw + gap) + 1
    d.polygon([(xe, limit_y + 3), (xe + 6, limit_y + 3), (xe + 3, limit_y - 3)], fill=RED, outline=INK)
    return img


def scene_trench():
    img = _scene_canvas()
    w, h = img.size
    d = ImageDraw.Draw(img)
    # field: two greens in a coarse pattern
    d.rectangle([0, 0, w, h], fill=GREEN)
    for y in range(0, h, 4):
        for x in range((y // 4 % 2) * 4, w, 8):
            d.rectangle([x, y, x + 2, y + 1], fill=GREEN_DARK)
    for (x, y) in ((10, 6), (80, 12), (30, 70), (95, 60), (55, 4), (5, 50)):
        d.rectangle([x, y, x + 3, y + 2], fill=GREEN_LIGHT)
    # a stream in the corner
    for i, (x, y) in enumerate(((0, 62), (8, 66), (16, 68), (24, 72), (32, 78), (40, 86))):
        d.rectangle([x, y, x + 9, y + 2], fill=BLUE)
    # survey area (AOI): dashed yellow polygon
    aoi = [(14, 10), (78, 6), (100, 24), (96, 64), (66, 80), (28, 76), (8, 52)]
    for i in range(len(aoi)):
        (xa, ya), (xb, yb) = aoi[i], aoi[(i + 1) % len(aoi)]
        steps = max(abs(xb - xa), abs(yb - ya))
        for s in range(steps):
            if (s // 3) % 2 == 0:
                x = xa + (xb - xa) * s / steps
                y = ya + (yb - ya) * s / steps
                d.rectangle([x, y, x + 1, y + 1], fill=YELLOW)
    # numbered trench candidates, 2:1 rectangles
    trenches = [((24, 20), "1"), ((60, 30), "2"), ((40, 54), "3"), ((72, 58), "4")]
    tw, th = 22, 9
    font = ImageFont.truetype(FONT, 8)
    for (x, y), label in trenches:
        d.rectangle([x, y, x + tw, y + th], fill=EARTH, outline=INK)
        d.rectangle([x + 2, y + 2, x + tw - 2, y + th - 2], outline=EARTH_DARK)
        d.fontmode = "1"
        d.text((x + tw // 2 - 2, y + 1), label, font=font, fill=WHITE)
    # north arrow
    d.polygon([(w - 10, 6), (w - 14, 14), (w - 6, 14)], fill=WHITE)
    d.rectangle([w - 11, 14, w - 9, 20], fill=WHITE)
    return img


def compose(scene: Image.Image, caption: str, out_name: str, icon_name: str):
    card = Image.open(TEMPLATE).convert("RGBA")
    d = ImageDraw.Draw(card)
    d.rectangle(CONTENT, fill=PAPER + (255,))
    big = scene.resize((scene.width * PX, scene.height * PX), Image.NEAREST)
    card.paste(big, (CONTENT[0], CONTENT[1]))
    # caption bar: blank, then block letters
    d.rectangle(CAPTION, fill=NAVY + (255,))
    small = Image.new("L", (116, 24), 0)
    sd = ImageDraw.Draw(small)
    sd.fontmode = "1"
    font = ImageFont.truetype(FONT, 8)
    sd.text((1, 6), caption, font=font, fill=255)
    sd.text((2, 6), caption, font=font, fill=255)   # one logical pixel thicker, like the set's block letters
    text = small.resize((small.width * PX, small.height * PX), Image.NEAREST)
    white = Image.new("RGBA", text.size, WHITE + (255,))
    card.paste(white, (CAPTION[0] + 56, CAPTION[1] + 8), text)
    card.save(ROOT / "docs" / "art" / out_name)
    card.resize((256, 256), Image.LANCZOS).save(ROOT / "icons" / icon_name)
    print("wrote", out_name, "and", icon_name)


def main():
    compose(scene_vif(), "CORRELATION & VIF", "vif_icon.png", "covariate.png")
    compose(scene_trench(), "TRENCH PLAN", "trench_icon.png", "trench.png")


if __name__ == "__main__":
    main()
