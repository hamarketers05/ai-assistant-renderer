#!/usr/bin/env python3
"""Create original AI Tech Lab intro and subscribe cards for every render."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

CYAN = (61, 226, 255)
GOLD = (255, 209, 92)
WHITE = (246, 250, 255)
NAVY = (3, 9, 25)
RED = (235, 38, 52)


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def background(width: int, height: int) -> Image.Image:
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    glow = np.exp(-((x - 0.73) ** 2 / 0.10 + (y - 0.44) ** 2 / 0.14))
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    arr[:, :, 0] = np.clip(3 + 8 * y + 4 * glow, 0, 255).astype(np.uint8)
    arr[:, :, 1] = np.clip(8 + 18 * y + 30 * glow, 0, 255).astype(np.uint8)
    arr[:, :, 2] = np.clip(24 + 36 * y + 66 * glow, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def create_intro(path: Path, fmt: str) -> None:
    width, height = (1080, 1920) if fmt == "SHORT" else (1920, 1080)
    img = background(width, height).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    margin = int(width * 0.055)
    draw.rounded_rectangle(
        (margin, margin, width - margin, height - margin),
        radius=max(24, int(width * 0.02)), outline=CYAN + (220,),
        width=max(2, int(width * 0.002))
    )

    # Original vector-style technical grid and light trails.
    step = max(48, int(width * 0.07))
    for xx in range(-height, width, step):
        draw.line((xx, 0, xx - int(height * 0.38), height),
                  fill=(27, 107, 148, 55), width=max(1, int(width * 0.001)))
    for radius in (0.18, 0.25, 0.32):
        cx, cy = int(width * 0.83), int(height * 0.30)
        rx, ry = int(width * radius), int(height * radius * 0.56)
        draw.ellipse((cx-rx, cy-ry, cx+rx, cy+ry),
                     outline=(35, 177, 222, 85), width=max(2, int(width * 0.002)))

    if fmt == "SHORT":
        icon_size = 170
        cy = int(height * 0.27)
        draw.ellipse((width//2-icon_size, cy-icon_size, width//2+icon_size, cy+icon_size),
                     outline=CYAN+(245,), width=8)
        draw.text((width//2, cy), "AI", anchor="mm", font=font(122), fill=WHITE)
        title_y = int(height * 0.43)
        title_size = 74
        tagline_size = 33
    else:
        icon_size = 118
        cx, cy = int(width * 0.18), int(height * 0.46)
        draw.ellipse((cx-icon_size, cy-icon_size, cx+icon_size, cy+icon_size),
                     outline=CYAN+(245,), width=7)
        draw.text((cx, cy), "AI", anchor="mm", font=font(86), fill=WHITE)
        title_y = int(height * 0.34)
        title_size = 94
        tagline_size = 34

    if fmt == "SHORT":
        draw.text((width//2, title_y), "AI TECH LAB", anchor="mm",
                  font=font(title_size), fill=WHITE, stroke_width=1, stroke_fill=NAVY)
        draw.rounded_rectangle((int(width*.16), title_y+92, int(width*.84), title_y+103),
                               radius=5, fill=CYAN+(245,))
        draw.text((width//2, title_y+174), "REAL RESEARCH  •  FUTURE FOCUSED",
                  anchor="mm", font=font(tagline_size), fill=CYAN)
        draw.text((width//2, int(height*.66)), "THE NEXT SHIFT STARTS HERE",
                  anchor="mm", font=font(32), fill=GOLD)
    else:
        left = int(width * 0.31)
        draw.text((left, title_y), "AI TECH LAB", font=font(title_size), fill=WHITE)
        draw.rounded_rectangle((left, title_y+126, left+int(width*.38), title_y+139),
                               radius=6, fill=CYAN+(245,))
        draw.text((left, title_y+188), "REAL RESEARCH. FUTURE FOCUSED.",
                  font=font(tagline_size), fill=CYAN)
        draw.text((left, title_y+276), "EXPLORING WHAT COMES NEXT",
                  font=font(25), fill=GOLD)

    # Restrained edge accents keep text readable after video compression.
    draw.text((margin+14, height-margin-48), "ORIGINAL EXPLAINERS  /  AI • SCIENCE • TECHNOLOGY",
              font=font(max(15, int(width*.012)), bold=False), fill=(180, 211, 231, 225))
    img.convert("RGB").save(path, quality=95)
    img.close()


def create_subscribe(path: Path) -> None:
    width, height = 1000, 250
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((22, 22, width-22, height-22), radius=62, fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    img.alpha_composite(shadow)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((18, 14, width-18, height-30), radius=56,
                        fill=(5, 17, 38, 242), outline=CYAN+(230,), width=4)
    d.ellipse((40, 55, 180, 195), fill=(13, 56, 91, 255), outline=CYAN+(255,), width=4)
    d.text((110, 124), "AI", anchor="mm", font=font(62), fill=WHITE)
    d.text((205, 62), "ENJOYING THE VIDEO?", font=font(27), fill=(201, 225, 241, 255))
    d.text((205, 111), "SUBSCRIBE", font=font(44), fill=WHITE)
    d.rounded_rectangle((665, 66, 944, 165), radius=28, fill=RED+(255,))
    d.text((805, 114), "SUBSCRIBE  +", anchor="mm", font=font(28), fill=WHITE)
    d.text((205, 171), "STAY AHEAD OF WHAT'S NEXT", font=font(21), fill=GOLD)
    img.save(path)
    img.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=("LONG_VIDEO", "SHORT"), default="LONG_VIDEO")
    parser.add_argument("--outdir", default="assets")
    args = parser.parse_args()
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    intro = out / "ai_tech_lab_intro.png"
    subscribe = out / "ai_tech_lab_subscribe.png"
    create_intro(intro, args.format)
    create_subscribe(subscribe)
    report = {
        "format": args.format,
        "intro": str(intro),
        "intro_dimensions": list(Image.open(intro).size),
        "subscribe": str(subscribe),
        "subscribe_dimensions": list(Image.open(subscribe).size),
        "assets_are_original_generated_graphics": True,
        "external_media_used": False,
    }
    Path("work").mkdir(exist_ok=True)
    Path("work/brand_assets_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    for p in (intro, subscribe):
        with Image.open(p) as im:
            im.verify()


if __name__ == "__main__":
    main()
