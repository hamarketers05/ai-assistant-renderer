#!/usr/bin/env python3
"""Record per-video tool usage, deliberate skips, and editing QA evidence."""
from __future__ import annotations

import argparse
import hashlib
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


def count_rendered_stock_sources(source_path: Path, scene_assets: dict) -> dict[str, int]:
    """Count source records that match real rendered stock-scene primary asset paths."""
    def norm(value) -> str:
        return str(value or "").replace("\\", "/").lstrip("./")

    rendered = {
        (str(row.get("scene") or ""), norm(row.get("primary_asset")))
        for row in (scene_assets.get("scenes") or [])
        if isinstance(row, dict) and row.get("asset_type") == "licensed_stock_broll"
    }
    counts: dict[str, int] = {}
    if not source_path.is_file():
        return counts
    for line in source_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "").strip()
        scene_id = str(row.get("scene") or "")
        if not provider or (scene_id, norm(row.get("asset_path"))) not in rendered:
            continue
        source_url = str(row.get("source_url") or "")
        creator = str(row.get("creator") or "").strip()
        if not source_url.startswith("https://") or not creator or row.get("commercial_use_allowed") is not True:
            continue
        label = str(row.get("license_label") or "").lower()
        license_url = str(row.get("license_url") or "").lower()
        if provider.lower() == "vecteezy":
            if label.strip() not in {"free", "free license"} or "vecteezy.com" not in source_url.lower():
                continue
        elif provider == "Wikimedia Commons":
            if any(term in (label + " " + license_url) for term in ("by-nc", "by-nd", "noncommercial", "non-commercial", "no derivatives")):
                continue
            if not any(term in (label + " " + license_url) for term in ("cc0", "public domain", "creativecommons.org/licenses/by/", "creativecommons.org/licenses/by-sa/", "creativecommons.org/publicdomain")):
                continue
        elif provider == "NASA Image and Video Library":
            if "images.nasa.gov/details/" not in source_url or "nasa.gov/nasa-brand-center/images-and-media" not in license_url:
                continue
        else:
            continue
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
        Path("work/rubberband_report.json"),
        Path("work/video_review_report.json"),
        Path("work/scene_director_report.json"),
        Path("work/transitions_report.json"),
        Path("work/transition_sfx_report.json"),
        Path("work/music_report.json"),
        Path("work/opencv_visual_qa.json"),
        Path("work/rendered_scene_assets_report.json"),
        Path("work/flux_generation_report.json"),
        Path("work/visual_coverage_report.json"),
        Path("work/thumbnail_imagemagick_report.json"),
    ]
    missing = [str(p) for p in required_paths if not p.is_file()]
    if not final_video.is_file() or final_video.stat().st_size < 100_000:
        missing.append(str(final_video))
    if thumb is not None and (not thumb.is_file() or thumb.stat().st_size < 1000):
        missing.append(str(thumb))
    if missing:
        raise SystemExit("Editing tool manifest blocked; required production evidence missing: " + ", ".join(missing))
    if thumb is None:
        raise SystemExit("Editing tool manifest blocked: final thumbnail is required to verify ImageMagick processing.")
    thumb_hash = hashlib.sha256(thumb.read_bytes()).hexdigest()
    if (imagemagick_report.get("status") != "used"
            or imagemagick_report.get("output_changed") is not True
            or imagemagick_report.get("dimensions") != [1280, 720]
            or imagemagick_report.get("output_sha256") != thumb_hash):
        raise SystemExit("Editing tool manifest blocked: ImageMagick processing report does not match the final thumbnail bytes.")

    voice = read_json(Path("work/voice_edit_report.json"))
    rubberband = read_json(Path("work/rubberband_report.json"))
    video_review = read_json(Path("work/video_review_report.json"))
    scenes = read_json(Path("work/scene_director_report.json"))
    transitions = read_json(Path("work/transitions_report.json"))
    sfx = read_json(Path("work/transition_sfx_report.json"))
    music = read_json(Path("work/music_report.json"))
    visual_qa = read_json(Path("work/opencv_visual_qa.json"))
    scene_assets = read_json(Path("work/rendered_scene_assets_report.json"))
    flux_report = read_json(Path("work/flux_generation_report.json"))
    visual_coverage = read_json(Path("work/visual_coverage_report.json"))
    external_media = read_json(Path("work/visual_media_report.json"))
    chart_overlay_report = read_json(Path("work/chart_overlay_report.json"))
    reuse = read_json(Path("work/asset_reuse_report.json"))
    evidence = read_json(Path("work/evidence_charts_report.json"))
    stereo = read_json(Path("work/stereo_3d_report.json"))
    kokoro = read_json(Path("work/kokoro_audio_quality.json"))
    thumbnail_brief = read_json(Path("work/thumbnail_brief.json"))
    imagemagick_report = read_json(Path("work/thumbnail_imagemagick_report.json"))
    provider_counts = count_asset_sources(Path("work/asset_sources.jsonl"))
    stock_provider_counts = count_rendered_stock_sources(Path("work/asset_sources.jsonl"), scene_assets)

    scene_count = int(scenes.get("planned_visual_scenes", 0))
    transition_count = int(transitions.get("scenes", scene_count)) - 1
    generated_scene_images = len(list(Path("assets").glob("generated_scene_*.png")))
    generated_hud_overlays = len(list(Path("assets").glob("scene_overlay_*.png")))
    evidence_charts_generated = list(evidence.get("charts_created") or [])
    evidence_charts_used = int(scene_assets.get("evidence_charts_used", 0))
    hud_overlays_applied = int(scene_assets.get("transparent_hud_overlay_applied_count", 0))
    stock_scene_count = int(scene_assets.get("licensed_stock_broll_scene_count", 0))
    flux_generated_count = max(0, int(flux_report.get("generated_count", 0)))
    flux_used_scene_count = max(0, int(scene_assets.get("cloudflare_flux_image_scene_count", 0)))
    is_short = args.format == "SHORT"
    if voice.get("status") != "passed":
        raise SystemExit("Editing manifest blocked: automated voice-editing QA did not pass.")
    if rubberband.get("status") not in {"used", "skipped"}:
        raise SystemExit("Editing manifest blocked: Rubber Band attempt/report is missing or invalid.")
    coverage_checks = visual_coverage.get("checks", {})
    if visual_coverage.get("status") != "passed" or not coverage_checks or any(value is not True for value in coverage_checks.values()):
        raise SystemExit("Editing manifest blocked: visual-budget checks are missing, incomplete, or failed.")
    stereo_quality = stereo.get("quality_checks", {}) if isinstance(stereo.get("quality_checks"), dict) else {}
    if not is_short:
        if stereo.get("status") != "success":
            raise SystemExit("Editing manifest blocked: final 3D stereoscopic conversion did not report success.")
        for key in ("audio_preserved", "duration_matches_master", "video_dimensions_correct_for_mode"):
            if stereo_quality.get(key) is not True:
                raise SystemExit(f"Editing manifest blocked: stereoscopic output did not verify {key}.")
        if args.stereo_output == "SBS" and not (stereo_quality.get("color_grade_applied") is True and stereo_quality.get("pinned_lut_integrity_verified") is True):
            raise SystemExit("Editing manifest blocked: SBS output did not verify pinned Kodak LUT application and integrity.")
    if video_review.get("review_status") != "completed" or video_review.get("decision") not in {"PASS", "IMPROVE"}:
        raise SystemExit("Editing manifest blocked: mandatory Groq video/vision review did not pass.")
    if is_short:
        if hud_overlays_applied < 4:
            raise SystemExit("Editing manifest blocked: Short needs at least four actually applied HUD overlays.")
    elif visual_coverage.get("status") != "passed":
        raise SystemExit("Editing manifest blocked: Long-video visual coverage gate did not pass.")
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
    if visual_qa.get("status") != "passed":
        raise SystemExit("Editing manifest blocked: OpenCV sampled-frame visual QA must explicitly pass.")
    if scene_assets.get("status") != "passed" or int(scene_assets.get("rendered_scene_count", -1)) != scene_count:
        raise SystemExit("Editing manifest blocked: actual rendered scene/source manifest is missing or incomplete.")
    rendered_rows = [row for row in (scene_assets.get("scenes") or []) if isinstance(row, dict)]
    if len(rendered_rows) != scene_count:
        raise SystemExit("Editing manifest blocked: scene-by-scene render evidence does not match the planned scene count.")
    missing_primary_assets = [str(row.get("scene") or "?") for row in rendered_rows if not str(row.get("primary_asset") or "").strip()]
    if missing_primary_assets:
        raise SystemExit("Editing manifest blocked: rendered scenes lack primary asset evidence: " + ", ".join(missing_primary_assets[:12]))
    graded_scene_count = sum(1 for row in rendered_rows if str(row.get("color_grade") or "").strip())
    motion_scene_count = sum(1 for row in rendered_rows if str(row.get("motion") or "").strip())
    if graded_scene_count != scene_count or motion_scene_count != scene_count:
        raise SystemExit(
            "Editing manifest blocked: cinematic color grade and camera-motion evidence must exist for every rendered scene "
            f"(grade={graded_scene_count}/{scene_count}, motion={motion_scene_count}/{scene_count})."
        )
    if evidence_charts_used < 0 or evidence_charts_used > len(evidence_charts_generated):
        raise SystemExit("Editing manifest blocked: chart use count exceeds the evidence chart assets generated.")

    sbs_lut_used = bool(stereo_quality.get("color_grade_applied") and stereo_quality.get("pinned_lut_integrity_verified"))
    licensed_clips = sum(stock_provider_counts.values())
    avg_scene_seconds = round(float(scenes.get("scene_duration_seconds", {}).get("mean", 0)), 2)
    tools = [
        {"tool": "FFmpeg", "status": "used", "purpose": "render, animate, transition, assemble, master and encode video/audio"},
        {"tool": "Python/Pillow", "status": "used", "purpose": "original topic-specific graphics, HUD/lower-thirds, glow and premium 3D-pop-out thumbnail"},
        {"tool": "NumPy + SciPy", "status": "used" if music.get("status") == "generated" else "unverified", "purpose": "signal synthesis for original background music"},
        {"tool": "Matplotlib", "status": "used" if evidence_charts_generated else "skipped", "purpose": "source-backed charts only", "charts_generated": len(evidence_charts_generated), "skip_reason": None if evidence_charts_generated else "No suitable source-linked numeric data was available; no statistics were invented."},
        {"tool": "Pydub", "status": "used" if voice.get("status") == "passed" else "unverified", "purpose": "punctuation-aware narration pause editing and audio segment handling"},
        {"tool": "Librosa", "status": "used" if voice.get("librosa_voice_enhancement") else "unverified", "purpose": "subtle voice-presence enhancement", "report": voice.get("librosa_voice_enhancement")},
        {"tool": "OpenCV", "status": "used" if visual_qa.get("status") == "passed" else "failed", "purpose": "sample-frame visual QA, movement/black-frame checks", "sample_frames": visual_qa.get("sample_frames"), "mean_frame_difference": visual_qa.get("mean_frame_difference"), "active_sample_transition_ratio": visual_qa.get("active_sample_transition_ratio")},
        {"tool": "ImageMagick", "status": imagemagick_report.get("status", "failed"), "purpose": "final premium-thumbnail sharpening/finish", "thumbnail": str(thumb), "output_changed": imagemagick_report.get("output_changed"), "dimensions": imagemagick_report.get("dimensions"), "sha256_verified_against_final_thumbnail": imagemagick_report.get("output_sha256") == thumb_hash},
        {"tool": "Kokoro-82M", "status": "used" if kokoro.get("quality_gate") == "passed" else "unverified", "purpose": "automatic American-English narration", "quality_gate": kokoro.get("quality_gate", "missing")},
        {"tool": "Faster-Whisper", "status": "used" if int(voice.get("timestamped_words", 0)) > 0 else "unverified", "purpose": "speech validation and word-timestamp alignment"},
        {"tool": "Rubber Band pitch shaping", "status": rubberband.get("status"), "purpose": "attempted subtle, duration-preserving pitch shaping on every video", "pitch_semitones": rubberband.get("pitch_semitones"), "reason": rubberband.get("reason"), "duration_preserved": rubberband.get("duration_preserved")},
        {"tool": "Groq video/vision final QA", "status": "used", "review_status": video_review.get("review_status"), "decision": video_review.get("decision"), "score": video_review.get("overall_score"), "blocking_issues": video_review.get("blocking_issues", [])},
        {"tool": "FFmpeg de-esser/compressor/loudness", "status": "used", "purpose": "speech cleanup, light sibilance control, compression and loudness normalization", "settings": "light de-esser; speech target -16 LUFS before final mix; final mix -14 LUFS"},
        {"tool": "FFmpeg slow stereo motion", "status": "used", "purpose": "subtle 0.08 Hz motion on the background-music bed only; speech remains centered", "settings": "75% modulation, 75% pulse-width (width=1.5 of max 2), 0.08 Hz; music is side-chain ducked under narration"},
        {"tool": "Voice-aligned scene director", "status": "used", "purpose": "clause-aware scene chunks driven by final narration word timestamps", "scene_count": scene_count, "average_scene_seconds": avg_scene_seconds},
        {"tool": "Visual novelty/reuse guard", "status": reuse.get("status", "unverified"), "purpose": "prevent repeated assets within a video or across verified recent deliveries", "previous_video_reuse": reuse.get("previous_video_reuse"), "within_video_duplicates": reuse.get("within_video_duplicates")},
        {"tool": "Ken Burns / camera drift", "status": "used" if motion_scene_count == scene_count else "failed", "purpose": "slow pan/zoom and restrained camera motion on footage and generated stills", "applied_to_scenes": motion_scene_count, "all_scenes_verified": motion_scene_count == scene_count, "settings": "generated stills zoom to 1.08; stock framing varies about 1.06-1.105 with slow x/y drift and subtle roll"},
        {"tool": "Cinematic color grade", "status": "used" if graded_scene_count == scene_count else "failed", "purpose": "restrained contrast/saturation, cool teal-blue shadows, warmer highlights, sharpening, soft vignette and subtle temporal grain", "applied_to_scenes": graded_scene_count, "all_scenes_verified": graded_scene_count == scene_count, "settings": "contrast=1.10; saturation=1.10; gamma=1.015; cool shadows / warm highlights via colorbalance; unsharp=0.45; vignette=PI/5; noise=1.2 temporal"},
        {"tool": "Film grain", "status": "used", "purpose": "very light FFmpeg grain, kept subtle for technology detail"},
        {"tool": "Neon HUD / scene overlay", "status": "used" if hud_overlays_applied > 0 else "skipped", "purpose": "transparent topic label, cyan glow and lower-third composited over scheduled primary visuals of any supported type", "generated_overlay_files": generated_hud_overlays, "applied_to_scenes": hud_overlays_applied, "primary_stock_scenes_available": stock_scene_count, "skip_reason": None if hud_overlays_applied > 0 else "No eligible transparent composite was successfully applied in this run."},
        {"tool": "Crossfade / push / digital mosaic transitions", "status": "used", "purpose": "short FFmpeg xfade transitions; occasional pixelize/zoom transitions", "transition_report": transitions.get("transition_types", [])},
        {"tool": "Original procedural transition SFX", "status": "used", "purpose": "quiet whoosh + digital tick ahead of each rendered scene transition", "transition_count": int(sfx.get("transition_count", 0)), "cue_lead_seconds": sfx.get("cue_lead_seconds", 0.22), "source_license": sfx.get("source_license")},
        {"tool": "Original topic-aware music", "status": "used", "purpose": "locally synthesized score with voice ducking"},
        {"tool": "2.35:1 letterboxing", "status": "skipped" if is_short else "used", "reason": "native vertical canvas for Shorts" if is_short else "cinematic bars inside the 16:9 YouTube container"},
        {"tool": "Premium thumbnail", "status": "used" if thumb is not None else "unverified", "purpose": "1280x720 Pillow composition with 3D pop-out, glow and short title text", "brief_source": "Groq brief" if thumbnail_brief.get("hook") else "local fallback"},
        {"tool": "MiDaS + FFmpeg stereoscopic render", "status": "used" if (not is_short and stereo.get("status") == "success") else ("not_applicable" if is_short else "unverified"), "purpose": "3D depth and SBS output before upload", "stereo_mode": args.stereo_output},
        {"tool": "Pinned Rec.709 Kodak 2383 D55 LUT", "status": "used" if sbs_lut_used else "not_applicable", "purpose": "integrity-verified LUT transform in the SBS conversion stage", "integrity_verified": sbs_lut_used, "rights_note": "The existing source repository's commercial license was not independently verified; checksum integrity is not proof of usage rights."},
        {"tool": "Evidence-supported charts", "status": "used" if evidence_charts_used > 0 else "skipped", "chart_count": evidence_charts_used, "generated_chart_count": len(evidence_charts_generated), "unused_chart_count": max(0, len(evidence_charts_generated) - evidence_charts_used), "display_mode": "transparent overlay only; never replaces the scene primary image/video", "reason": "only source-backed charts with a topic/number match to the scene are included; no statistics are invented"},
        {"tool": "Full-HD visual-budget gate", "status": "not_applicable" if is_short else "used", "gate_status": visual_coverage.get("status", "missing"), "visual_counts": visual_coverage.get("visual_counts", {}), "checks": visual_coverage.get("checks", {}), "blocked_upload_if_failed": not is_short},
        {"tool": "Free commercial-use image/video acquisition", "status": "used" if int(external_media.get("assets_downloaded", 0)) > 0 else "skipped", "providers": external_media.get("providers", {}), "assets_downloaded": external_media.get("assets_downloaded", 0), "report": "work/visual_media_report.json", "note": "Native Full HD sources required for downloaded stills; CC0/Public Domain/CC BY or explicitly permitted provider-specific items only."},
        {"tool": "Voice-aligned transparent graph overlays", "status": "used" if int(chart_overlay_report.get("evidence_charts_mapped_to_scenes", 0)) > 0 else "skipped", "charts_overlaid": chart_overlay_report.get("evidence_charts_mapped_to_scenes", 0), "scenes_considered": chart_overlay_report.get("scenes_considered", 0), "report": "work/chart_overlay_report.json"},
        {"tool": "Commercial-use stock clips", "status": "used" if licensed_clips >= 4 else "failed", "rendered_primary_clip_count": licensed_clips, "providers": stock_provider_counts, "note": "Counts only licensed source records whose exact asset path and scene match a rendered stock-b-roll primary visual."},
        {"tool": "Cloudflare Workers AI FLUX.1 [schnell]", "status": "used" if flux_used_scene_count > 0 else "skipped", "purpose": "generate topic-matched 1920x1080 stills through the authenticated Cloudflare AI binding; actual use is counted from rendered scenes", "model": flux_report.get("model", "@cf/black-forest-labs/flux-1-schnell"), "images_generated": flux_generated_count, "scenes_actually_using_flux": flux_used_scene_count, "max_images_per_render": 6, "free_quota_note": "Cloudflare Workers AI includes 10,000 Neurons/day on Free; requests fall back on quota/capacity errors. Usage above the included allocation may be billed on a Paid plan.", "license": flux_report.get("license", "Apache-2.0"), "license_url": flux_report.get("license_url", "https://github.com/black-forest-labs/flux/blob/main/model_licenses/LICENSE-FLUX1-schnell"), "skip_reason": None if flux_used_scene_count > 0 else (flux_report.get("fallback_reason") or flux_report.get("reason") or "No generated FLUX still was needed/accepted for a final scene; original Pillow art/licensed B-roll remained active.")},
        {"tool": "ComfyUI + Stable Video Diffusion / AnimateDiff", "status": "skipped", "reason": "GPU-heavy model runtimes and large checkpoints are not a reliable fit for the current free hosted runner. FFmpeg motion is active instead; no paid inference/API is used."},
        {"tool": "Auto-Editor", "status": "skipped", "reason": "The existing word-timestamped voice editor handles pauses and captions together; a second silence-cut pass would desynchronize verified word timings."},
        {"tool": "Demucs", "status": "not_applicable", "reason": "Voice narration and the original synthesized music are separate clean tracks, so no mixed audio needs stem separation."},
        {"tool": "DaVinci Resolve", "status": "not_installed", "reason": "Desktop GUI editor is not usable as a headless GitHub Actions step; its grade is implemented reproducibly with FFmpeg filters."},
        {"tool": "GIMP / Krita", "status": "not_installed", "reason": "Desktop GUI image editors are not required on the headless runner; Pillow produces the automated thumbnail and overlays."},
    ]
    warnings = []
    if is_short:
        warnings.append("Shorts keep their native 9:16 canvas, so 2.35:1 letterboxing and 3D SBS conversion are not applied.")
    if stereo.get("status") == "success" and args.stereo_output == "SBS":
        if not sbs_lut_used:
            warnings.append("SBS report did not confirm both LUT application and pinned-file integrity.")
        else:
            warnings.append("The pinned external Kodak 2383 D55 LUT checksum is verified, but its upstream commercial-use license remains unverified.")
    if not evidence:
        warnings.append("Evidence chart report is missing; charts must not be inferred from unsupported statistics.")
    elif not evidence_charts_generated:
        warnings.append("No evidence chart was generated; the script did not contain enough source-linked numeric data to justify a chart.")
    elif evidence_charts_used == 0:
        warnings.append("Evidence charts were generated but none matched a narrated scene well enough to insert safely; no unrelated chart was forced into the final video.")
    if hud_overlays_applied == 0:
        warnings.append("No separate transparent HUD overlay was applied in this run; primary visuals retain their normal content without a separate transparent HUD layer.")
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
        "visual_assets": {
            "planned_voice_aligned_scenes": scene_count,
            "generated_topic_matched_images": generated_scene_images,
            "cloudflare_flux_images_generated": flux_generated_count,
            "cloudflare_flux_images_used_in_final_scenes": flux_used_scene_count,
            "transparent_hud_overlays_generated": generated_hud_overlays,
            "transparent_hud_overlays_applied": hud_overlays_applied,
            "evidence_charts_generated": len(evidence_charts_generated),
            "evidence_charts_used": evidence_charts_used,
            "licensed_stock_source_records": licensed_clips,
            "licensed_stock_broll_scenes_used": stock_scene_count,
            "provider_source_counts": provider_counts,
            "scene_asset_report": "work/rendered_scene_assets_report.json",
            "transition_sfx_events": int(sfx.get("transition_count", 0)),
        },
        "average_scene_seconds": avg_scene_seconds,
        "transition_count": int(transitions.get("scenes", 0)) - 1,
        "transition_sfx_count": int(sfx.get("transition_count", 0)),
        "music": {"status": music.get("status"), "source": music.get("source"), "uses_external_samples": music.get("uses_external_samples")},
        "commercial_use_stock_source_count": licensed_clips,
        "editing_tools": tools,
        "warnings": warnings,
        "policy": "Each relevant feature must report used, not_applicable, skipped, or not_installed with a reason; no tool is forced when it would reduce reliability or invalidate sync/licensing. Asset counts represent generated/downloaded artifacts actually present for this run; they are not promises of viewer retention or performance.",
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
