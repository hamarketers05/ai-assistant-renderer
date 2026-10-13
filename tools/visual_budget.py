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


def evaluate(scene_rows: list[dict[str, Any]], source_rows: list[dict[str, Any]],
             captions: int, video: dict[str, Any], *, min_unique: int = 70,
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
    vecteezy = len({str(row.get("asset_id")) for row in source_rows
                    if str(row.get("provider") or "").lower() == "vecteezy" and row.get("asset_id") is not None})
    native_hd = video.get("width") == 1920 and video.get("height") == 1080
    duration = float(video.get("duration_seconds") or 0)
    checks = {
        "native_full_hd_output": native_hd,
        "duration_in_5_to_7_minute_window": 300 <= duration <= 420,
        "at_least_70_unique_primary_visual_assets": len(unique_assets) >= min_unique,
        "at_least_100_timeline_visual_elements": elements >= min_elements,
        "six_flux_images_actually_used": flux_used >= 6,
        "ten_vecteezy_assets_verified": vecteezy >= 10,
        "every_rendered_scene_has_primary_asset_record": scene_count > 0 and len(primary_assets) == scene_count,
    }
    return {
        "status": "passed" if all(checks.values()) else "blocked",
        "content_format_target": "6-minute Full HD AI Tech Lab long video",
        "video": video,
        "source_targets": {"cloudflare_flux_actual_scene_uses": {"target": 6, "actual": flux_used},
                           "vecteezy_verified_assets": {"target": 10, "actual": vecteezy}},
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
        "counting_policy": "Primary images/video scenes, separately rendered HUD/chart overlays and timed caption cues are reported separately; scene transitions do not inflate the visual-element count.",
    }


def self_test() -> None:
    scenes = [{"primary_asset": f"assets/generated_scene_{i}.png",
               "hud_overlay_applied": i < 20, "chart_overlay_applied": i < 3,
               "flux_image_used": i < 6} for i in range(90)]
    sources = [{"provider": "Vecteezy", "asset_id": str(i)} for i in range(10)]
    report = evaluate(scenes, sources, 25, {"width": 1920, "height": 1080, "duration_seconds": 360})
    if report["status"] != "passed":
        raise SystemExit(f"Visual budget self-test failed: {report}")
    bad = evaluate(scenes[:20], sources[:2], 2, {"width": 1280, "height": 720, "duration_seconds": 80})
    if bad["status"] != "blocked":
        raise SystemExit("Visual budget fail-closed test failed.")
    print(json.dumps({"status": "self_test_passed", "positive_case": report["visual_counts"],
                      "negative_case": "low visual count, source quota and non-HD are blocked"}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--content-id", default="")
    parser.add_argument("--format", choices=("LONG_VIDEO", "SHORT"), default="LONG_VIDEO")
    parser.add_argument("--video", default="")
    parser.add_argument("--output", default="work/visual_coverage_report.json")
    parser.add_argument("--min-unique", type=int, default=70)
    parser.add_argument("--min-elements", type=int, default=100)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.format == "SHORT":
        short_report = {
            "status": "not_applicable_short",
            "content_id": str(args.content_id),
            "content_format_target": "9:16 Short uses its separate 20-60 second QA profile",
            "reason": "The 6-minute landscape visual-budget thresholds apply only to LONG_VIDEO; Shorts retain native vertical output.",
            "long_video_gate": "not_run",
            "upload_blocked_if_any_check_fails": False,
        }
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(short_report, indent=2)+"\\n", encoding="utf-8")
        print(json.dumps(short_report))
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
