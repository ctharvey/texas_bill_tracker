"""Draw public/social-card.png (1200x630).

Run by hand when the card changes: python design/social/make_images.py --fonts C:/Windows/Fonts
Colours are the default palette in src/styles.css (--nav-bg, the warbler yellow, --accent). The mark is the warbler
logo (design/brand/warbler.svg), drawn by resvg through node (run npm install first), as make_icons.mjs draws the icons.
"""
from __future__ import annotations

import argparse
import io
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
NAVY, GOLD, TEAL, WHITE, MUTED = "#14243a", "#f5b517", "#5fc7c2", "#ffffff", "#9fb0c4"  # GOLD: the warbler's cheek.
SCALE = 4  # Draw large and shrink, for smooth edges.


RENDER = """
const {readFileSync} = require('node:fs');
const {initWasm, Resvg} = require('@resvg/resvg-wasm');
initWasm(readFileSync(require.resolve('@resvg/resvg-wasm/index_bg.wasm'))).then(() => {
  const resvg = new Resvg(readFileSync(process.argv[1], 'utf8'), {fitTo: {mode: 'width', value: Number(process.argv[2])}});
  process.stdout.write(Buffer.from(resvg.render().asPng()));
});
"""


def warbler(size: int) -> Image.Image:
    """The warbler logo as a size x size RGBA image."""
    png = subprocess.run(["node", "-e", RENDER, str(ROOT / "design/brand/warbler.svg"), str(size)],
                         cwd=ROOT, check=True, capture_output=True).stdout
    return Image.open(io.BytesIO(png)).convert("RGBA")


def card(fonts: Path) -> Image.Image:
    w, h = 1200, 630
    big = Image.new("RGB", (w * SCALE, h * SCALE), NAVY)
    d = ImageDraw.Draw(big)
    f = lambda name, px: ImageFont.truetype(str(fonts / name), px * SCALE)
    s = lambda v: v * SCALE
    d.rectangle((0, 0, s(14), s(h)), fill=GOLD)
    mark = warbler(112 * SCALE)
    big.paste(mark, (s(84), s(78)), mark)
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


if __name__ == "__main__":
    main()
