#!/usr/bin/env python3
"""Record per-video tool usage, deliberate skips, and editing QA evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def count_asset_sources(path: Path) -> dict:
    import json as _json
    counts: dict[str, int] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            provider = str(row.get("provider") or "unknown")
            counts[provider] = counts.get(provider, 0) + 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--content-id", required=True)
    parser.add_argument("--format", choices=("LONG_VIDEO", "SHORT"), required=True)
    parser.add_argument("--stereo-output", default="SBS")
    parser.add_argument("--final-video", required=True)
    parser.add_argument("--thumbnail", default="")
    parser.add_argument("--output", default="work/editing_tool_manifest.json")
    args = parser.parse_args()

    final_video = Path(args.final_video)
    thumb = Path(args.thumbnail) if args.thumbnail else None
    required_paths = [
        Path("work/voice_edit_report.json"),
        Path("work/scene_director_report.json"),
        Path("work/transitions_report.json"),
        Path("work/transition_sfx_report.json"),
        Path("work/music_report.json"),
        Path("work/opencv_visual_qa.json"),
    ]
    missing = [str(p) for p in required_paths if not p.is_file()]
    if not final_video.is_file() or final_video.stat().st_size < 100_000:
        missing.append(str(final_video))
    if thumb is not None and (not thumb.is_file() or thumb.stat().st_size < 1000):
        missing.append(str(thumb))
    if missing:
        raise SystemExit("Editing tool manifest blocked; required production evidence missing: " + ", ".join(missing))

    voice = read_json(Path("work/voice_edit_report.json"))
    scenes = read_json(Path("work/scene_director_report.json"))
    transitions = read_json(Path("work/transitions_report.json"))
    sfx = read_json(Path("work/transition_sfx_report.json"))
    music = read_json(Path("work/music_report.json"))
    visual_qa = read_json(Path("work/opencv_visual_qa.json"))
    reuse = read_json(Path("work/asset_reuse_report.json"))
    evidence = read_json(Path("work/evidence_charts_report.json"))
    stereo = read_json(Path("work/stereo_3d_report.json"))
    kokoro = read_json(Path("work/kokoro_audio_quality.json"))
    thumbnail_brief = read_json(Path("work/thumbnail_brief.json"))
    provider_counts = count_asset_sources(Path("work/asset_sources.jsonl"))

    scene_count = int(scenes.get("planned_visual_scenes", 0))
    transition_count = int(transitions.get("scenes", scene_count)) - 1
    if voice.get("status") != "passed":
        raise SystemExit("Editing manifest blocked: automated voice-editing QA did not pass.")
    if scenes.get("exact_word_timing") is not True or scene_count < 8:
        raise SystemExit("Editing manifest blocked: scene timing/visual generation evidence is missing.")
    if transitions.get("transition") is None or transitions.get("rendered_duration_seconds") is None:
        raise SystemExit("Editing manifest blocked: transition renderer report is incomplete.")
    if sfx.get("status") != "generated" or int(sfx.get("transition_count", -1)) != transition_count:
        raise SystemExit("Editing manifest blocked: procedural transition SFX count does not match rendered cuts.")
    if music.get("status") != "generated" or music.get("uses_external_samples") is not False:
        raise SystemExit("Editing manifest blocked: original music track was not verified.")
    if reuse.get("status") != "validated" or reuse.get("previous_video_reuse") is not False:
        raise SystemExit("Editing manifest blocked: unique-media guard did not pass.")
    if not visual_qa:
        raise SystemExit("Editing manifest blocked: final visual QA report is absent.")

    is_short = args.format == "SHORT"
    sbs_lut_used = bool(stereo.get("color_grade_applied") and stereo.get("pinned_lut_integrity_verified"))
    licensed_clips = sum(provider_counts.values())
    avg_scene_seconds = round(float(scenes.get("scene_duration_seconds", {}).get("mean", 0)), 2)
    tools = [
        {"tool": "FFmpeg", "status": "used", "purpose": "render, animate, transition, assemble, master and encode video/audio"},
        {"tool": "Python/Pillow", "status": "used", "purpose": "original topic-specific graphics, HUD/lower-thirds, glow and premium 3D-pop-out thumbnail"},
        {"tool": "Kokoro-82M", "status": "used" if kokoro.get("quality_gate") == "passed" else "unverified", "purpose": "automatic American-English narration", "quality_gate": kokoro.get("quality_gate", "missing")},
        {"tool": "Faster-Whisper", "status": "used" if int(voice.get("timestamped_words", 0)) > 0 else "unverified", "purpose": "speech validation and word-timestamp alignment"},
        {"tool": "FFmpeg de-esser/compressor/loudness", "status": "used", "purpose": "speech cleanup, light sibilance control, compression and loudness normalization", "settings": "light de-esser; speech target -16 LUFS before final mix; final mix -14 LUFS"},
        {"tool": "FFmpeg slow stereo motion", "status": "used", "purpose": "subtle 0.08 Hz motion on the background-music bed only; speech remains centered", "settings": "15% modulation; music is side-chain ducked under narration"},
        {"tool": "Voice-aligned scene director", "status": "used", "purpose": "clause-aware scene chunks driven by final narration word timestamps", "scene_count": scene_count, "average_scene_seconds": avg_scene_seconds},
        {"tool": "Ken Burns / camera drift", "status": "used", "purpose": "slow pan/zoom and restrained camera motion on footage and generated stills"},
        {"tool": "Cinematic color grade", "status": "used", "purpose": "restrained contrast/saturation, teal-blue shadows, warmer highlights, sharpening and soft vignette"},
        {"tool": "Film grain", "status": "used", "purpose": "very light FFmpeg grain, kept subtle for technology detail"},
        {"tool": "Neon HUD / scene overlay", "status": "used", "purpose": "per-scene transparent topic label, cyan glow and lower-third overlay"},
        {"tool": "Crossfade / push / digital mosaic transitions", "status": "used", "purpose": "short FFmpeg xfade transitions; occasional pixelize/zoom transitions", "transition_report": transitions.get("transition_types", [])},
        {"tool": "Original procedural transition SFX", "status": "used", "purpose": "quiet whoosh + digital tick ahead of each rendered scene transition", "transition_count": int(sfx.get("transition_count", 0))},
        {"tool": "Original topic-aware music", "status": "used", "purpose": "locally synthesized score with voice ducking"},
        {"tool": "2.35:1 letterboxing", "status": "skipped" if is_short else "used", "reason": "native vertical canvas for Shorts" if is_short else "cinematic bars inside the 16:9 YouTube container"},
        {"tool": "Premium thumbnail", "status": "used" if thumb is not None else "unverified", "purpose": "1280x720 Pillow composition with 3D pop-out, glow and short title text", "brief_source": "Groq brief" if thumbnail_brief.get("hook") else "local fallback"},
        {"tool": "MiDaS + FFmpeg stereoscopic render", "status": "used" if (not is_short and stereo.get("status") == "success") else ("not_applicable" if is_short else "unverified"), "purpose": "3D depth and SBS output before upload", "stereo_mode": args.stereo_output},
        {"tool": "Pinned Rec.709 Kodak 2383 D55 LUT", "status": "used" if sbs_lut_used else "not_applicable", "purpose": "integrity-verified LUT transform in the SBS conversion stage", "integrity_verified": sbs_lut_used, "rights_note": "The existing source repository's commercial license was not independently verified; checksum integrity is not proof of usage rights."},
        {"tool": "Evidence-supported charts", "status": "used" if evidence.get("charts_generated", evidence.get("generated_count", 0)) else "skipped", "reason": "only chart claims backed by script/source evidence are graphed; no statistics are invented"},
        {"tool": "Commercial-use stock clips", "status": "used", "source_manifest_entries": licensed_clips, "providers": provider_counts, "note": "Only entries passing the separate license and relevance gates are eligible for delivery."},
        {"tool": "FLUX.1 [schnell]", "status": "skipped", "reason": "Official weights are Apache-2.0, but this standard GitHub-hosted CPU job has no attached GPU; the 12B-parameter model is not reliable for a zero-cost per-video CPU render. Existing original Pillow art and licensed B-roll remain the fallback."},
        {"tool": "ComfyUI + Stable Video Diffusion / AnimateDiff", "status": "skipped", "reason": "GPU-heavy model runtimes and large checkpoints are not a reliable fit for the current free hosted runner. FFmpeg motion is active instead; no paid inference/API is used."},
        {"tool": "Auto-Editor", "status": "skipped", "reason": "The existing word-timestamped voice editor handles pauses and captions together; a second silence-cut pass would desynchronize verified word timings."},
        {"tool": "Demucs", "status": "not_applicable", "reason": "Voice narration and the original synthesized music are separate clean tracks, so no mixed audio needs stem separation."},
        {"tool": "DaVinci Resolve", "status": "not_installed", "reason": "Desktop GUI editor is not usable as a headless GitHub Actions step; its grade is implemented reproducibly with FFmpeg filters."},
        {"tool": "GIMP / Krita", "status": "not_installed", "reason": "Desktop GUI image editors are not required on the headless runner; Pillow produces the automated thumbnail and overlays."},
    ]
    warnings = []
    if is_short:
        warnings.append("Shorts keep their native 9:16 canvas, so 2.35:1 letterboxing and 3D SBS conversion are not applied.")
    if stereo.get("status") == "success" and not sbs_lut_used and args.stereo_output == "SBS":
        warnings.append("SBS report did not confirm both LUT application and pinned-file integrity.")
    if not evidence:
        warnings.append("Evidence chart report is missing; charts must not be inferred from unsupported statistics.")
    if licensed_clips < 4:
        raise SystemExit(f"Editing manifest blocked: only {licensed_clips} source-manifest entries; existing commercial-use gate requires at least four.")
    result = {
        "status": "passed",
        "content_id": args.content_id,
        "format": args.format,
        "final_video": str(final_video),
        "final_video_bytes": final_video.stat().st_size,
        "thumbnail": str(thumb) if thumb else None,
        "scene_count": scene_count,
        "average_scene_seconds": avg_scene_seconds,
        "transition_count": int(transitions.get("scenes", 0)) - 1,
        "transition_sfx_count": int(sfx.get("transition_count", 0)),
        "music": {"status": music.get("status"), "source": music.get("source"), "uses_external_samples": music.get("uses_external_samples")},
        "commercial_use_stock_source_count": licensed_clips,
        "editing_tools": tools,
        "warnings": warnings,
        "policy": "Each relevant feature must report used, not_applicable, skipped, or not_installed with a reason; no tool is forced when it would reduce reliability or invalidate sync/licensing.",
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": result["status"], "content_id": result["content_id"],
                      "scene_count": scene_count, "transition_count": result["transition_count"],
                      "transition_sfx_count": result["transition_sfx_count"], "stock_sources": licensed_clips,
                      "warnings": warnings, "manifest": str(out)}))


if __name__ == "__main__":
    main()
