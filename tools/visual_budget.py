#!/usr/bin/env python3
"""Enforce the AI Tech Lab Full-HD visual budget before any upload step."""
from __future__ import annotations
import argparse, json, re, subprocess
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def caption_cues(path: Path) -> int:
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    # Count SRT cue blocks containing a timestamp line, not individual words.
    return sum(1 for block in re.split(r"\n\s*\n", text)
               if re.search(r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[,.]\d{3}", block))


def source_records(path: Path) -> list[dict[str, Any]]:
    items = []
    if not path.is_file():
        return items
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            items.append(item)
    return items


def probe_video(path: Path) -> dict[str, float | int]:
    if not path.is_file():
        raise SystemExit(f"Full-HD visual budget blocked: final video is missing: {path}")
    raw = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-show_entries", "format=duration",
        "-of", "json", str(path)
    ], capture_output=True, text=True, check=True, timeout=30).stdout
    obj = json.loads(raw)
    streams = obj.get("streams") or []
    if not streams:
        raise SystemExit("Full-HD visual budget blocked: final file has no video stream.")
    fmt = obj.get("format") or {}
    return {"width": int(streams[0].get("width") or 0),
            "height": int(streams[0].get("height") or 0),
            "duration_seconds": float(fmt.get("duration") or 0)}


def verified_stock_asset_ids(scene_rows: list[dict[str, Any]],
                            source_rows: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    """Count only source-attributed, commercially usable stock clips actually rendered."""
    def norm_path(value: Any) -> str:
        return str(value or "").replace("\\", "/").lstrip("./")

    scene_by_id = {str(row.get("scene")): row for row in scene_rows if row.get("scene") is not None}
    licensed_ids: set[str] = set()
    vecteezy_ids: set[str] = set()
    for source in source_rows:
        provider = str(source.get("provider") or "").strip().lower()
        rendered = scene_by_id.get(str(source.get("scene") or ""))
        if not rendered or rendered.get("asset_type") != "licensed_stock_broll":
            continue
        if norm_path(rendered.get("primary_asset")) != norm_path(source.get("asset_path")):
            continue
        if source.get("commercial_use_allowed") is not True:
            continue
        creator = str(source.get("creator") or "").strip()
        source_url = str(source.get("source_url") or "")
        asset_id = str(source.get("asset_id") or "").strip()
        license_label = " ".join(str(source.get("license_label") or "").strip().lower().split())
        license_url = str(source.get("license_url") or "")
        if not creator or not source_url.startswith("https://") or not asset_id:
            continue
        if provider == "vecteezy":
            if license_label not in {"free", "free license"} or "vecteezy.com" not in source_url.lower():
                continue
            vecteezy_ids.add(asset_id)
        elif provider == "wikimedia commons":
            # The downloader already inspects per-file license metadata; re-check the
            # recorded label/link here and reject NC/ND or unverified license records.
            if "commons.wikimedia.org/" not in source_url.lower() or not license_url.startswith("https://"):
                continue
            if any(term in license_label for term in ("noncommercial", "non-commercial", "by-nc", "by-nd", "no derivatives", "no-derivatives")):
                continue
            permissive = (
                "public domain" in license_label
                or "cc0" in license_label
                or license_label.startswith("cc by")
                or license_label.startswith("cc-by")
            )
            if not permissive:
                continue
        else:
            continue
        licensed_ids.add(provider + ":" + asset_id)
    return licensed_ids, vecteezy_ids


def evaluate(scene_rows: list[dict[str, Any]], source_rows: list[dict[str, Any]],
             captions: int, video: dict[str, Any], *, min_unique: int = 80,
             min_elements: int = 100) -> dict[str, Any]:
    primary_assets = [str(row.get("primary_asset") or "").strip() for row in scene_rows]
    primary_assets = [x for x in primary_assets if x]
    unique_assets = set(primary_assets)
    scene_count = len(scene_rows)
    hud_count = sum(bool(row.get("hud_overlay_applied")) for row in scene_rows)
    chart_count = sum(bool(row.get("chart_overlay_applied")) for row in scene_rows)
    overlay_count = hud_count + chart_count
    elements = scene_count + overlay_count + captions
    flux_used = sum(1 for row in scene_rows if row.get("flux_image_used"))

    def norm_path(value: Any) -> str:
        return str(value or "").replace("\\", "/").lstrip("./")

    licensed_ids, vecteezy_ids = verified_stock_asset_ids(scene_rows, source_rows)
    licensed_stock = len(licensed_ids)
    vecteezy = len(vecteezy_ids)
    original_visuals = sum(
        1 for row in scene_rows
        if str(row.get("asset_type") or "") in {"python_pillow_scene", "free_commercial_image"}
        and str(row.get("primary_asset") or "").strip()
    )

    native_hd = video.get("width") == 1920 and video.get("height") == 1080
    duration = float(video.get("duration_seconds") or 0)
    checks = {
        "native_full_hd_output": native_hd,
        "duration_in_5_to_6_minute_window": 300 <= duration <= 364,
        "rendered_scene_count_between_80_and_90": 80 <= scene_count <= 90,
        "at_least_80_unique_primary_visual_assets": len(unique_assets) >= min_unique,
        "at_least_100_timeline_visual_elements": elements >= min_elements,
        "six_flux_or_original_visuals_used": flux_used >= 6 or original_visuals >= 6,
        "at_least_4_verified_free_license_stock_clips_rendered": licensed_stock >= 4,
        "at_least_25_hud_overlays_applied": hud_count >= 25,
        "every_rendered_scene_has_primary_asset_record": scene_count > 0 and len(primary_assets) == scene_count,
    }
    return {
        "status": "passed" if all(checks.values()) else "blocked",
        "content_format_target": "6-minute Full HD AI Tech Lab long video",
        "video": video,
        "source_targets": {
            "cloudflare_flux_actual_scene_uses": {"target": 6, "actual": flux_used, "fallback_original_visuals": original_visuals},
            "verified_free_license_stock_clips_actually_rendered": {"target_minimum": 4, "actual": licensed_stock},
            "vecteezy_verified_assets_actually_rendered": {"target_minimum": 0, "actual": vecteezy, "optional_when_free_plan_not_confirmed": True},
            "hud_overlay_placements": {"target_minimum": 25, "actual": hud_count},
        },
        "visual_counts": {
            "rendered_scene_placements": scene_count,
            "unique_primary_visual_assets": len(unique_assets),
            "hud_overlay_placements": hud_count,
            "evidence_chart_overlay_placements": chart_count,
            "subtitle_cue_placements": captions,
            "timeline_visual_elements": elements,
            "target_unique_primary_minimum": min_unique,
            "target_timeline_elements_minimum": min_elements,
        },
        "checks": checks,
        "upload_blocked_if_any_check_fails": True,
        "counting_policy": "Long videos require 80-90 scenes, 80 unique primary assets, 100+ timeline elements, native Full HD, 25+ applied HUD overlays, and 4+ commercially usable, source-attributed Vecteezy-Free or Wikimedia Commons clips actually rendered. Six Flux scenes are preferred, but the bounded local original-visual fallback is accepted when the free image endpoint is rate-limited. Vecteezy assets count only for exact Free License/source/creator/path matches; Wikimedia clips require recorded CC BY/CC BY-SA/CC0/Public Domain metadata with attribution. License, reuse, duration, scene and overlay gates remain mandatory.",
    }


def evaluate_short(scene_rows: list[dict[str, Any]], source_rows: list[dict[str, Any]],
                  captions: int, video: dict[str, Any]) -> dict[str, Any]:
    primary_assets = [str(row.get("primary_asset") or "").strip() for row in scene_rows]
    present_assets = [asset for asset in primary_assets if asset]
    unique_assets = set(present_assets)
    scene_count = len(scene_rows)
    hud_count = sum(bool(row.get("hud_overlay_applied")) for row in scene_rows)
    chart_count = sum(bool(row.get("chart_overlay_applied")) for row in scene_rows)
    flux_used = sum(1 for row in scene_rows if row.get("flux_image_used"))

    def norm_path(value: Any) -> str:
        return str(value or "").replace("\\", "/").lstrip("./")

    licensed_ids, vecteezy_ids = verified_stock_asset_ids(scene_rows, source_rows)
    licensed_stock = len(licensed_ids)
    original_visuals = sum(
        1 for row in scene_rows
        if str(row.get("asset_type") or "") in {"python_pillow_scene", "free_commercial_image"}
        and str(row.get("primary_asset") or "").strip()
    )

    duration = float(video.get("duration_seconds") or 0)
    checks = {
        "native_vertical_output": video.get("width") == 1080 and video.get("height") == 1920,
        "duration_in_20_to_60_second_window": 20 <= duration <= 60,
        "rendered_scene_count_between_8_and_30": 8 <= scene_count <= 30,
        "at_least_8_unique_primary_visual_assets": len(unique_assets) >= 8,
        "at_least_4_hud_overlays_applied": hud_count >= 4,
        "at_least_2_flux_or_original_visuals_used": flux_used >= 2 or original_visuals >= 2,
        "at_least_1_verified_free_license_stock_clip_rendered": licensed_stock >= 1,
        "caption_file_has_at_least_5_cues": captions >= 5,
        "every_rendered_scene_has_primary_asset_record": scene_count > 0 and len(present_assets) == scene_count,
    }
    return {
        "status": "passed" if all(checks.values()) else "blocked",
        "content_format_target": "native 1080x1920 AI Tech Lab Short",
        "video": video,
        "source_targets": {
            "cloudflare_flux_actual_scene_uses": {"target_minimum": 2, "actual": flux_used, "fallback_original_visuals": original_visuals},
            "verified_free_license_stock_clips_actually_rendered": {"target_minimum": 1, "actual": licensed_stock},
            "vecteezy_verified_assets_actually_rendered": {"target_minimum": 0, "actual": len(vecteezy_ids), "optional_when_free_plan_not_confirmed": True},
            "hud_overlay_placements": {"target_minimum": 4, "actual": hud_count},
        },
        "visual_counts": {
            "rendered_scene_placements": scene_count,
            "unique_primary_visual_assets": len(unique_assets),
            "hud_overlay_placements": hud_count,
            "evidence_chart_overlay_placements": chart_count,
            "subtitle_cue_placements": captions,
        },
        "checks": checks,
        "upload_blocked_if_any_check_fails": True,
        "counting_policy": "Shorts require native vertical output, 20-60 seconds, 8-30 scenes, 8 unique primary assets, 4+ applied HUD overlays, 5+ caption cues, and at least 1 fully verified commercially usable Vecteezy-Free or Wikimedia Commons clip actually rendered. Two Flux stills are preferred, with local original-visual fallback when the free endpoint is rate-limited. Vecteezy is never used unless the API plan is positively confirmed Free.",
    }


def self_test() -> None:
    scenes = []
    sources = []
    for i in range(90):
        asset = f"assets/scene_{i}.mp4" if i < 10 else f"assets/generated_scene_{i}.png"
        asset_type = "licensed_stock_broll" if i < 10 else "python_pillow_scene"
        scenes.append({
            "scene": str(i), "primary_asset": asset, "asset_type": asset_type,
            "hud_overlay_applied": i < 30, "chart_overlay_applied": i < 3,
            "flux_image_used": 10 <= i < 16,
        })
        if i < 10:
            sources.append({
                "provider": "Vecteezy", "asset_id": str(i), "scene": str(i),
                "asset_path": asset, "license_label": "Free License",
                "commercial_use_allowed": True, "source_url": f"https://www.vecteezy.com/video/{i}",
                "creator": f"CI creator {i}",
            })
    report = evaluate(scenes, sources, 25, {"width": 1920, "height": 1080, "duration_seconds": 360})
    if report["status"] != "passed":
        raise SystemExit(f"Visual budget self-test failed: {report}")
    boundary = evaluate(scenes[:80], sources, 25,
                        {"width": 1920, "height": 1080, "duration_seconds": 360})
    if boundary["status"] != "passed":
        raise SystemExit(f"Visual budget 80-scene boundary test failed: {boundary}")
    below_target = evaluate(scenes[:79], sources, 25,
                            {"width": 1920, "height": 1080, "duration_seconds": 360})
    if below_target["checks"].get("rendered_scene_count_between_80_and_90") is not False:
        raise SystemExit("Visual budget failed to block a 79-scene long video.")
    unused_scenes = [dict(row, asset_type="python_pillow_scene", primary_asset=f"assets/generated_scene_{i}.png")
                     for i, row in enumerate(scenes)]
    unused = evaluate(unused_scenes, sources, 25, {"width": 1920, "height": 1080, "duration_seconds": 360})
    if unused["checks"]["at_least_4_verified_free_license_stock_clips_rendered"] is not False:
        raise SystemExit("Visual budget incorrectly counted unrendered stock sources.")
    bad = evaluate(scenes[:20], sources[:2], 2, {"width": 1280, "height": 720, "duration_seconds": 80})
    if bad["status"] != "blocked":
        raise SystemExit("Visual budget fail-closed test failed.")
    short_scenes, short_sources = [], []
    for i in range(12):
        stock = i < 4
        asset = f"assets/short_stock_{i}.mp4" if stock else f"assets/short_scene_{i}.png"
        short_scenes.append({"scene":str(i),"primary_asset":asset,
            "asset_type":"licensed_stock_broll" if stock else "python_pillow_scene",
            "hud_overlay_applied":i<5,"chart_overlay_applied":False,"flux_image_used":i in {4,5}})
        if stock:
            short_sources.append({"provider":"Vecteezy","asset_id":f"short-{i}","scene":str(i),
                "asset_path":asset,"license_label":"Free License","commercial_use_allowed":True,
                "source_url":f"https://www.vecteezy.com/video/short-{i}","creator":f"CI Short creator {i}"})
    short = evaluate_short(short_scenes, short_sources, 10, {"width":1080,"height":1920,"duration_seconds":45})
    if short["status"] != "passed":
        raise SystemExit(f"Short visual-budget positive test failed: {short}")
    short_bad = evaluate_short(short_scenes, short_sources[:2], 10, {"width":1920,"height":1080,"duration_seconds":75})
    if short_bad["status"] != "blocked":
        raise SystemExit("Short visual-budget fail-closed test failed.")
    print(json.dumps({"status":"self_test_passed","positive_case":report["visual_counts"],
                      "short_positive_checks":short["checks"],"unused_sources_blocked":True,
                      "negative_case":"Long and Short low-visual/source/non-native outputs are blocked"}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--content-id", default="")
    parser.add_argument("--format", choices=("LONG_VIDEO", "SHORT"), default="LONG_VIDEO")
    parser.add_argument("--video", default="")
    parser.add_argument("--output", default="work/visual_coverage_report.json")
    parser.add_argument("--min-unique", type=int, default=80)
    parser.add_argument("--min-elements", type=int, default=100)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.format == "SHORT":
        scene_report = read_json(Path("work/rendered_scene_assets_report.json"))
        if scene_report.get("status") != "passed":
            raise SystemExit("Short visual budget blocked: rendered scene asset report is missing or incomplete.")
        scene_rows = scene_report.get("scenes") or []
        source_rows = source_records(Path("work/asset_sources.jsonl"))
        captions = caption_cues(Path("work/captions.srt"))
        video_path = Path(args.video)
        probe = probe_video(video_path)
        short_report = evaluate_short(scene_rows, source_rows, captions, probe)
        short_report["content_id"] = str(args.content_id)
        short_report["video_path"] = str(video_path)
        short_report["external_media"] = read_json(Path("work/visual_media_report.json"))
        short_report["chart_overlays"] = read_json(Path("work/chart_overlay_report.json"))
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(short_report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
        print(json.dumps(short_report, ensure_ascii=False))
        if short_report["status"] != "passed":
            failed = [name for name, passed in short_report["checks"].items() if not passed]
            raise SystemExit("SHORT VISUAL/QUALITY UPLOAD GATE BLOCKED: " + ", ".join(failed))
        return
    scene_report = read_json(Path("work/rendered_scene_assets_report.json"))
    if scene_report.get("status") != "passed":
        raise SystemExit("Visual budget blocked: rendered scene asset report is missing or incomplete.")
    scene_rows = scene_report.get("scenes") or []
    source_rows = source_records(Path("work/asset_sources.jsonl"))
    captions = caption_cues(Path("work/captions.srt"))
    video_path = Path(args.video)
    probe = probe_video(video_path)
    report = evaluate(scene_rows, source_rows, captions, probe,
                      min_unique=args.min_unique, min_elements=args.min_elements)
    report["content_id"] = str(args.content_id)
    report["video_path"] = str(video_path)
    report["external_media"] = read_json(Path("work/visual_media_report.json"))
    report["chart_overlays"] = read_json(Path("work/chart_overlay_report.json"))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if report["status"] != "passed":
        failed = [name for name, passed in report["checks"].items() if not passed]
        raise SystemExit("VISUAL/QUALITY UPLOAD GATE BLOCKED: " + ", ".join(failed))


if __name__ == "__main__":
    main()
