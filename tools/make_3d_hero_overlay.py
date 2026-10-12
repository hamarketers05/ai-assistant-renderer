#!/usr/bin/env python3
"""Create a topic-matched transparent 3D-style security hero for the opening scene."""
from pathlib import Path
import math
import re
import sys
from PIL import Image, ImageDraw, ImageFilter

TITLE_FILE = Path(sys.argv[1] if len(sys.argv) > 1 else "work/title.txt")
OUTPUT = Path(sys.argv[2] if len(sys.argv) > 2 else "assets/ai_security_3d_hero.png")
title = TITLE_FILE.read_text(encoding="utf-8").strip().lower()
if not any(term in title for term in ("agent", "security", "risk", "safety", "privacy")):
    print("Title is not a security/agent topic; no 3D hero overlay required.")
    raise SystemExit(0)

W = H = 900
img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
# Isometric shield silhouette with layered extrusion for a genuine depth cue.
front = [(450, 95), (690, 185), (660, 490), (450, 705), (240, 490), (210, 185)]
back = [(x + 54, y + 32) for x, y in front]
for offset in range(34, -1, -1):
    pts = [(x + offset, y + int(offset * .58)) for x, y in front]
    ImageDraw.Draw(img).polygon(pts, fill=(0, 35 + min(offset, 20), 78 + min(offset * 3, 90), 220))
d = ImageDraw.Draw(img)
d.polygon(back, fill=(3, 28, 63, 180), outline=(30, 205, 255, 170))
d.polygon(front, fill=(5, 22, 55, 238), outline=(60, 225, 255, 255))
d.line(front + [front[0]], fill=(100, 245, 255, 255), width=12, joint="curve")
# Inner beveled shield and subtle circuitry.
inner = [(450, 155), (635, 224), (610, 465), (450, 625), (290, 465), (265, 224)]
d.polygon(inner, fill=(4, 47, 88, 220), outline=(30, 170, 240, 245))
for y in range(260, 520, 54):
    d.line((330, y, 570, y - 20), fill=(30, 145, 220, 100), width=3)
# Large dimensional check mark with extrusion/shadow.
check = [(355, 390), (420, 455), (555, 310)]
for dx in range(18, 0, -1):
    d.line([(x + dx, y + dx) for x, y in check], fill=(0, 90, 145, 230), width=32, joint="curve")
d.line(check, fill=(115, 255, 245, 255), width=24, joint="curve")
d.line(check, fill=(235, 255, 255, 255), width=7, joint="curve")
# Floating orbit arcs and depth particles.
for box, start, end, width in [((125, 125, 775, 760), 205, 330, 5), ((155, 165, 745, 720), 20, 135, 3)]:
    d.arc(box, start=start, end=end, fill=(35, 220, 255, 210), width=width)
for x, y, r in [(180, 340, 8), (700, 300, 6), (640, 600, 7), (255, 570, 5), (510, 160, 5)]:
    d.ellipse((x-r, y-r, x+r, y+r), fill=(145, 250, 255, 245))
glow = img.filter(ImageFilter.GaussianBlur(22))
glow.putalpha(glow.getchannel("A").point(lambda p: int(p * .36)))
img = Image.alpha_composite(glow, img)
# Downsample with antialiasing; transparency preserved for FFmpeg compositing.
img = img.resize((720, 720), Image.Resampling.LANCZOS)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
img.save(OUTPUT)
with Image.open(OUTPUT) as check_img:
    if check_img.size != (720, 720) or check_img.mode != "RGBA":
        raise SystemExit("3D hero overlay failed image validation.")
    check_img.verify()
print("Generated transparent 3D security hero:", OUTPUT)
