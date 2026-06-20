# Demo art generator: stands in for the image-gen model step of sprite-gen.
# Draws a chibi slime character base image and per-state row strips
# (idle = breathing+blink loop, jump = crouch/takeoff/air/land arc)
# on a flat magenta chroma background, matching the prompt contract.

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

MAGENTA = (255, 0, 255)
CELL = 96
MARGIN = 10

BODY = (80, 200, 120)
BODY_DARK = (50, 150, 90)
OUTLINE = (25, 60, 40)
EYE = (30, 30, 40)
CHEEK = (240, 150, 150)


def draw_slime(draw: ImageDraw.ImageDraw, ox: int, squash: float = 1.0,
               lift: int = 0, blink: bool = False, stretch: float = 1.0) -> None:
    """Draw one slime pose inside the cell starting at x offset `ox`.

    squash < 1 widens/flattens, stretch > 1 narrows/elongates.
    lift raises the body off the floor line (for jump frames).
    """
    floor = CELL - MARGIN
    w = int(56 * (2.0 - squash) * (2.0 - stretch) ** 0.0)
    w = int(56 / stretch * (2.0 - squash))
    h = int(48 * squash * stretch)
    cx = ox + CELL // 2
    top = floor - lift - h
    left = cx - w // 2
    right = cx + w // 2
    bottom = floor - lift

    # body with outline
    draw.ellipse((left - 2, top - 2, right + 2, bottom + 2), fill=OUTLINE)
    draw.ellipse((left, top, right, bottom), fill=BODY)
    # belly shade
    draw.ellipse((left + 6, top + h // 2, right - 6, bottom - 2), fill=BODY_DARK)
    # highlight
    draw.ellipse((left + 8, top + 6, left + 20, top + 16), fill=(160, 240, 190))

    eye_y = top + h // 3
    if blink:
        draw.rectangle((cx - 14, eye_y + 3, cx - 6, eye_y + 5), fill=EYE)
        draw.rectangle((cx + 6, eye_y + 3, cx + 14, eye_y + 5), fill=EYE)
    else:
        draw.ellipse((cx - 14, eye_y, cx - 6, eye_y + 9), fill=EYE)
        draw.ellipse((cx + 6, eye_y, cx + 14, eye_y + 9), fill=EYE)
    # cheeks + mouth
    draw.ellipse((cx - 20, eye_y + 10, cx - 12, eye_y + 16), fill=CHEEK)
    draw.ellipse((cx + 12, eye_y + 10, cx + 20, eye_y + 16), fill=CHEEK)
    draw.arc((cx - 6, eye_y + 8, cx + 6, eye_y + 18), 0, 180, fill=EYE, width=2)


def strip(n: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (n * CELL, CELL), MAGENTA)
    return img, ImageDraw.Draw(img)


def main() -> None:
    out = Path(sys.argv[1])
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    # base image: neutral idle pose
    base = Image.new("RGB", (CELL, CELL), MAGENTA)
    draw_slime(ImageDraw.Draw(base), 0)
    base.save(out / "base-slime.png")

    # idle: subtle breathing + one blink (loop)
    img, d = strip(4)
    draw_slime(d, 0 * CELL, squash=1.00)
    draw_slime(d, 1 * CELL, squash=0.94)
    draw_slime(d, 2 * CELL, squash=0.90, blink=True)
    draw_slime(d, 3 * CELL, squash=0.95)
    img.save(raw / "idle.png")

    # jump: crouch, takeoff, airborne, landing (non-loop)
    img, d = strip(4)
    draw_slime(d, 0 * CELL, squash=0.72)                 # crouch
    draw_slime(d, 1 * CELL, stretch=1.25, lift=14)       # takeoff
    draw_slime(d, 2 * CELL, stretch=1.10, lift=26)       # airborne
    draw_slime(d, 3 * CELL, squash=0.80, lift=0)         # landing
    img.save(raw / "jump.png")

    print(f"wrote base + idle/jump rows under {out}")


if __name__ == "__main__":
    main()
