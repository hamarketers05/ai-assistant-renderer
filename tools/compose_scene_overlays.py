#!/usr/bin/env python3
"""Prepare transparent source-backed graph overlays and per-scene HUD composites."""
from __future__ import annotations
import json, re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1920, 1080
STOP = set("the and for with from into that this these those then than have has had are was were can could will would should about after before your you our their they them its how what when where why which while latest trend news future technology artificial intelligence explain explained".split())


def terms(text):
    return {x for x in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if x not in STOP and (len(x) > 2 or x in {"ai", "gpu", "cpu", "us"})}


def number_keys(text):
    out = set()
    for raw in re.findall(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?%?(?![A-Za-z])", str(text or "")):
        try:
            out.add(f"{float(raw.replace(',', '').replace('%', '')):g}")
        except ValueError:
            pass
    return out


def chart_matches(scene_text, detail):
    reference = " ".join([str(detail.get("title") or ""), *[str(x) for x in (detail.get("labels") or [])]])
    shared = terms(scene_text) & terms(reference)
    values = " ".join(str(x) for x in (detail.get("values") or []))
    numeric_match = bool(number_keys(scene_text) & number_keys(values))
    return len(shared) >= 2 or (len(shared) >= 1 and numeric_match)


def font(size, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make_graph_overlay(chart_path: Path, chart_detail: dict, target: Path):
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    panel = Image.new("RGBA", (1060, 590), (3, 14, 31, 232))
    glow = Image.new("RGBA", panel.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle((4, 4, 1055, 585), radius=30, outline=(0, 220, 255, 180), width=9)
    panel = Image.alpha_composite(panel, glow.filter(ImageFilter.GaussianBlur(13)))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle((4, 4, 1055, 585), radius=26, outline=(0, 220, 255, 235), width=3)
    title = str(chart_detail.get("title") or "Evidence-backed data").strip()[:95]
    draw.text((28, 20), title, font=font(28, True), fill=(245, 250, 255, 255))
    with Image.open(chart_path) as source:
        graph = source.convert("RGB")
    graph.thumbnail((995, 470), Image.Resampling.LANCZOS)
    panel.alpha_composite(graph.convert("RGBA"), ((panel.width-graph.width)//2, 76))
    source_host = re.sub(r"^https?://(www\.)?", "", str(chart_detail.get("source_url") or "")).split("/")[0]
    draw.text((28, 550), ("SOURCE: " + source_host)[:95], font=font(17, True), fill=(125, 231, 255, 255))
    base.alpha_composite(panel, (W-panel.width-58, 135))
    target.parent.mkdir(parents=True, exist_ok=True)
    base.save(target)


def main():
    scenes_path = Path("work/scenes.tsv")
    charts_path = Path("work/evidence_charts_report.json")
    if not scenes_path.exists():
        raise SystemExit("Missing work/scenes.tsv")
    charts = json.loads(charts_path.read_text(encoding="utf-8")) if charts_path.exists() else {}
    chart_details = {Path(item.get("path", "")).name: item for item in (charts.get("chart_details") or [])
                     if isinstance(item, dict) and item.get("path")}
    chart_files = [Path(p) for p in (charts.get("charts_created") or []) if Path(p).is_file()]
    rows = [line.split("\t") for line in scenes_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    used = set()
    chart_assignments, hud_scene_count = [], 0
    for row in rows:
        if len(row) < 7:
            continue
        scene = re.sub(r"[^A-Za-z0-9_-]", "_", str(row[0]))[:80]
        scene_text = " ".join(row[5:7])
        chart_assignment = None
        for candidate in chart_files:
            if candidate.name in used:
                continue
            detail = chart_details.get(candidate.name, {})
            if chart_matches(scene_text, detail):
                chart_assignment = {"scene": scene, "chart": candidate.name,
                                    "title": str(detail.get("title") or ""),
                                    "source_url": str(detail.get("source_url") or ""),
                                    "overlay_path": f"assets/chart_overlay_scene_{scene}.png"}
                make_graph_overlay(candidate, detail, Path(chart_assignment["overlay_path"]))
                used.add(candidate.name)
                chart_assignments.append(chart_assignment)
                break

        hud_path = Path(f"assets/scene_overlay_{scene}.png")
        composite_path = Path(f"assets/composite_overlay_scene_{scene}.png")
        has_hud = hud_path.is_file()
        has_chart = bool(chart_assignment)
        if has_hud or has_chart:
            composed = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            if has_hud:
                with Image.open(hud_path) as source:
                    composed.alpha_composite(source.convert("RGBA"))
                hud_scene_count += 1
            if has_chart:
                with Image.open(chart_assignment["overlay_path"]) as source:
                    composed.alpha_composite(source.convert("RGBA"))
            composed.save(composite_path, optimize=True)

    report = {
        "status": "passed",
        "scenes_considered": len(rows),
        "evidence_charts_available": len(chart_files),
        "evidence_charts_mapped_to_scenes": len(chart_assignments),
        "hud_overlay_scenes_available": hud_scene_count,
        "chart_assignments": chart_assignments,
        "chart_overlay_rule": "Only source-linked charts whose labels/terms and optional numeric evidence match the narration are overlaid; charts never replace the primary footage/image.",
        "overlay_output_resolution": "1920x1080 transparent RGBA",
    }
    Path("work/chart_overlay_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "chart_assignments"}))


if __name__ == "__main__":
    main()
