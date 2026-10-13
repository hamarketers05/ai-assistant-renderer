#!/usr/bin/env python3
"""Generate a capped set of FLUX.1 Schnell visuals through the authenticated production Worker.

The renderer's existing Pillow scene graphics remain the fallback. The caller makes at most
25 image requests for one content item, uses four inference steps, and never needs a paid
third-party inference API. Cloudflare Workers AI may reject requests when free capacity is
exhausted; that condition is recorded and handled by retaining the local scene artwork.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageDraw

MODEL = "@cf/black-forest-labs/flux-1-schnell"
LICENSE_URL = "https://github.com/black-forest-labs/flux/blob/main/model_licenses/LICENSE-FLUX1-schnell"
SIZE = (1920, 1080)
MAX_IMAGES_PER_CONTENT = 25


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def compose_landscape(raw: bytes, target: Path) -> tuple[int, int]:
    """Validate the model output and compose a 16:9 frame suitable for the 1080p master."""
    with Image.open(io.BytesIO(raw)) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
    if source.width < 256 or source.height < 256:
        raise ValueError(f"Generated image is too small ({source.width}x{source.height}).")

    # The model endpoint currently returns square images. A center-focused landscape crop
    # preserves the cinematic subject while keeping the existing FFmpeg/Ken Burns pipeline.
    frame = ImageOps.fit(source, SIZE, method=Image.Resampling.LANCZOS, centering=(0.5, 0.47))
    frame = ImageEnhance.Contrast(frame).enhance(1.03)
    frame = ImageEnhance.Color(frame).enhance(0.98)
    frame.save(target, format="PNG", optimize=True)
    with Image.open(target) as check:
        if check.size != SIZE or check.mode not in ("RGB", "RGBA"):
            raise ValueError("Composed FLUX visual failed 1920x1080 validation.")
    return source.size


def build_prompt(title: str, scene_text: str, scene_id: str) -> str:
    scene = " ".join(scene_text.split())[:650]
    title = " ".join(title.split())[:180]
    prompt = (
        "Create one photorealistic cinematic editorial still for a trustworthy United States "
        "technology-news explainer. Topic: " + title + ". Scene to illustrate: " + scene + ". "
        "Premium real-camera photography, accurate physical materials, rich but restrained HDR-like "
        "tonal range, clean highlights, detailed shadows, volumetric practical lighting, cool teal-blue "
        "shadow tones with subtle warm amber highlights, professional 35mm lens, natural depth of field, "
        "wide horizontal composition with the important subject near the center for a 16:9 crop. "
        "No words, no typography, no captions, no watermarks, no fake charts, no logos, no brand marks. "
        "Illustrate the concept rather than inventing factual numbers. Visual shot reference " + scene_id + "."
    )
    return prompt[:2048]


def call_model(endpoint: str, token: str, content_id: str, image_index: int, prompt: str) -> bytes:
    body = json.dumps({
        "content_id": content_id,
        "image_index": image_index,
        "prompt": prompt,
        "steps": 4,
    }).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AI-Tech-Lab-Renderer/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("ok") is not True:
        raise RuntimeError("Image endpoint returned an unsuccessful response.")
    encoded = str(payload.get("image") or "")
    if encoded.startswith("data:") and "," in encoded:
        encoded = encoded.split(",", 1)[1]
    raw = base64.b64decode(encoded, validate=True)
    # Force a decode before the bytes are accepted into the production assets folder.
    with Image.open(io.BytesIO(raw)) as image:
        image.verify()
    return raw


def pick_scenes(rows: list[list[str]], limit: int) -> list[list[str]]:
    candidates = []
    for row in rows:
        if len(row) < 7:
            continue
        scene_id = "".join(ch for ch in str(row[0]) if ch.isalnum() or ch in "_-")[:80]
        if not scene_id:
            continue
        # Stock clips are already motion footage and are preferred when available. Spend AI
        # inference only on scenes that would otherwise use the local static illustration.
        stock = Path("assets") / f"scene_{scene_id}.mp4"
        licensed_image = Path("assets") / f"free_media_scene_{scene_id}.jpg"
        if stock.is_file() and stock.stat().st_size > 10_000:
            continue
        if licensed_image.is_file() and licensed_image.stat().st_size > 10_000:
            continue
        candidates.append(row)
    if len(candidates) <= limit:
        return candidates
    if limit <= 1:
        return [candidates[len(candidates) // 2]]
    indexes = sorted({round(i * (len(candidates) - 1) / (limit - 1)) for i in range(limit)})
    return [candidates[i] for i in indexes]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--content-id", default=os.getenv("CONTENT_ID", ""))
    parser.add_argument("--max-images", type=int, default=MAX_IMAGES_PER_CONTENT)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", default="work/flux_generation_report.json")
    args = parser.parse_args()

    report_path = Path(args.output)
    if args.self_test:
        Path("work").mkdir(exist_ok=True)
        test_bytes = io.BytesIO()
        Image.new("RGB", (512, 512), (20, 50, 90)).save(test_bytes, format="JPEG", quality=90)
        target = Path("work/flux-image-self-test.png")
        compose_landscape(test_bytes.getvalue(), target)
        write_json(report_path, {
            "status": "self_test_passed",
            "model": MODEL,
            "image_dimensions": list(SIZE),
            "license_url": LICENSE_URL,
        })
        print("FLUX image composition self-test passed; no network request made.")
        return

    Path("assets").mkdir(exist_ok=True)
    Path("work").mkdir(exist_ok=True)
    limit = max(0, min(int(args.max_images), MAX_IMAGES_PER_CONTENT))
    content_id = str(args.content_id).strip()
    base_url = os.getenv("WORKER_URL", "").strip()
    token = os.getenv("WORKER_AUTH_TOKEN", "").strip()

    if not content_id.isdigit():
        reason = "A numeric content_id was not supplied."
        write_json(report_path, {"status": "skipped", "model": MODEL, "generated_count": 0, "reason": reason, "license_url": LICENSE_URL})
        print("FLUX image generation skipped: " + reason)
        return
    if not base_url or not token:
        reason = "Authenticated production Worker URL/token is unavailable; local generated scenes retained."
        write_json(report_path, {"status": "skipped", "model": MODEL, "generated_count": 0, "reason": reason, "license_url": LICENSE_URL})
        print("FLUX image generation skipped: " + reason)
        return
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        reason = "Worker endpoint must use HTTPS; local generated scenes retained."
        write_json(report_path, {"status": "skipped", "model": MODEL, "generated_count": 0, "reason": reason, "license_url": LICENSE_URL})
        print("FLUX image generation skipped: " + reason)
        return

    endpoint = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/generate-image", "", ""))
    title_path = Path("work/title.txt")
    title = title_path.read_text(encoding="utf-8").strip() if title_path.is_file() else "AI and future technology"
    scene_file = Path("work/scenes.tsv")
    if not scene_file.is_file():
        raise SystemExit("FLUX generation cannot start: work/scenes.tsv is missing.")
    import csv
    with scene_file.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream, delimiter="\t"))
    selected = pick_scenes(rows, limit)
    if not selected:
        write_json(report_path, {
            "status": "skipped",
            "model": MODEL,
            "generated_count": 0,
            "reason": "Every planned scene has suitable stock footage or no scenes need image fallback.",
            "license": "Apache-2.0",
            "license_url": LICENSE_URL,
        })
        print("FLUX image generation skipped: suitable stock footage already covers the planned scenes.")
        return

    generated: list[dict[str, Any]] = []
    stop_reason = ""
    for image_index, row in enumerate(selected, start=1):
        scene_id = "".join(ch for ch in str(row[0]) if ch.isalnum() or ch in "_-")[:80]
        scene_text = " ".join(str(x) for x in row[4:7])
        prompt = build_prompt(title, scene_text, scene_id)
        try:
            raw = call_model(endpoint, token, content_id, image_index, prompt)
            source_dimensions = None
            with Image.open(io.BytesIO(raw)) as source:
                source_dimensions = list(source.size)
            flux_path = Path("assets") / f"flux_scene_{scene_id}.png"
            fallback_path = Path("assets") / f"generated_scene_{scene_id}.png"
            compose_landscape(raw, flux_path)
            # Replace only the local illustrated fallback after the AI image was verified.
            compose_landscape(raw, fallback_path)
            generated.append({
                "scene_id": scene_id,
                "image_index": image_index,
                "file": str(flux_path),
                "render_fallback_replaced": str(fallback_path),
                "source_dimensions": source_dimensions,
                "output_dimensions": list(SIZE),
                "prompt_summary": scene_text[:180],
                "model": MODEL,
            })
            print(f"FLUX image generated and validated for scene {scene_id} ({len(generated)}/{len(selected)}).")
        except urllib.error.HTTPError as exc:
            stop_reason = f"Image service HTTP {exc.code}; local fallback visuals retained for remaining scenes."
            print("FLUX generation stopped safely: " + stop_reason)
            break
        except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
            stop_reason = f"Image service/validation issue ({type(exc).__name__}); local fallback visuals retained for remaining scenes."
            print("FLUX generation stopped safely: " + stop_reason)
            break
        except Exception as exc:
            stop_reason = f"Unexpected image generation issue ({type(exc).__name__}); local fallback visuals retained for remaining scenes."
            print("FLUX generation stopped safely: " + stop_reason)
            break
        if image_index < len(selected):
            time.sleep(0.15)

    status = "generated" if len(generated) == len(selected) and generated else ("partial" if generated else "fallback")
    report = {
        "status": status,
        "provider": "Cloudflare Workers AI",
        "model": MODEL,
        "license": "Apache-2.0",
        "license_url": LICENSE_URL,
        "content_id": content_id,
        "steps_per_image": 4,
        "max_images_per_content": MAX_IMAGES_PER_CONTENT,
        "requested_count": len(selected),
        "generated_count": len(generated),
        "generated": generated,
        "fallback_reason": stop_reason or None,
        "note": "This report counts generated images. Actual scene use is verified separately in rendered_scene_assets_report.json.",
    }
    write_json(report_path, report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("generated",)}, indent=2))


if __name__ == "__main__":
    main()
