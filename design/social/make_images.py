"""Draw public/social-card.png (1200x630), public/icon.png, public/apple-touch-icon.png and public/favicon.ico.

Run by hand when the brand changes: python design/social/make_images.py --fonts C:/Windows/Fonts
Colours are the default palette in src/styles.css (--nav-bg, --mark, --accent); the star is the brand-mark path.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
NAVY, GOLD, TEAL, WHITE, MUTED = "#14243a", "#ba822d", "#5fc7c2", "#ffffff", "#9fb0c4"
# index.html's brand-mark path (viewBox 0 0 24 24).
STAR = [(12, 1.6), (14.9, 8.7), (22.5, 9.2), (16.7, 14.1), (18.6, 21.5), (12, 17.4), (5.4, 21.5), (7.3, 14.1), (1.5, 9.2), (9.1, 8.7)]
SCALE = 4  # Draw large and shrink, for smooth edges.


def star(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, fill: str) -> None:
    draw.polygon([(x + px / 24 * size, y + py / 24 * size) for px, py in STAR], fill=fill)


def tile(size: int, radius: float) -> Image.Image:
    big = Image.new("RGBA", (size * SCALE, size * SCALE), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, size * SCALE - 1, size * SCALE - 1), radius=radius * size * SCALE, fill=GOLD)
    star(d, size * SCALE * .14, size * SCALE * .12, size * SCALE * .72, NAVY)
    return big.resize((size, size), Image.LANCZOS)


def card(fonts: Path) -> Image.Image:
    w, h = 1200, 630
    big = Image.new("RGB", (w * SCALE, h * SCALE), NAVY)
    d = ImageDraw.Draw(big)
    f = lambda name, px: ImageFont.truetype(str(fonts / name), px * SCALE)
    s = lambda v: v * SCALE
    d.rectangle((0, 0, s(14), s(h)), fill=GOLD)
    big.paste(tile(112 * SCALE, .18), (s(84), s(78)), tile(112 * SCALE, .18))
    d.text((s(222), s(88)), "T E X A S", font=f("segoeuib.ttf", 26), fill=GOLD)
    d.text((s(220), s(116)), "BILL ATLAS", font=f("segoeuib.ttf", 62), fill=WHITE)
    lines = ["Every bill in the 90th Texas Legislature,", "tracked to the official source."]
    for i, line in enumerate(lines):
        d.text((s(84), s(268 + i * 70)), line, font=f("segoeuib.ttf", 52), fill=WHITE)
    d.text((s(84), s(430)), "Plain-language summaries, topics, and the agencies each bill affects.",
           font=f("segoeui.ttf", 30), fill=MUTED)
    d.line((s(84), s(512), s(w - 84), s(512)), fill="#2a3d57", width=s(2))
    d.text((s(84), s(538)), "billatlas.org", font=f("segoeuib.ttf", 34), fill=TEAL)
    d.text((s(w - 84), s(546)), "Independent \u00b7 not a state website", font=f("segoeui.ttf", 26), fill=MUTED, anchor="ra")
    return big.resize((w, h), Image.LANCZOS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fonts", type=Path, required=True, help="Folder holding segoeui.ttf and segoeuib.ttf")
    parser.add_argument("--out", type=Path, default=ROOT / "public")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    card(args.fonts).save(args.out / "social-card.png", optimize=True)
    tile(192, .18).save(args.out / "icon.png", optimize=True)
    # iOS rounds the corners itself and shows transparency as black, so the touch icon is full-bleed.
    full = tile(180, 0).convert("RGB")
    full.save(args.out / "apple-touch-icon.png", optimize=True)
    tile(256, .18).save(args.out / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])


if __name__ == "__main__":
    main()
