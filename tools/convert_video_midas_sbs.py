#!/usr/bin/env python3
"""Create a high-quality SBS stereo master using official MiDaS depth + FFmpeg.

The normal rendered master is never overwritten. MiDaS estimates relative depth on
keyframes; depth maps are interpolated between keyframes and reset at detected cuts.
FFmpeg encodes the two views side-by-side, copies the original audio, and writes
H.264 stereoscopic frame-packing metadata for compatible YouTube 3D playback.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
from pathlib import Path

MIDAS_REPO = "isl-org/MiDaS"
MIDAS_COMMIT = "454597711a62eabcbf7d1e89f3fb9f569051ac9b"
MIDAS_MODEL = "MiDaS_small"


def report(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data, indent=2), flush=True)


def probe(path: Path) -> dict:
    raw = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        text=True, timeout=60,
    )
    data = json.loads(raw)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video:
        raise ValueError("Input/output has no readable video stream.")
    fps = video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1"
    if fps in ("0/0", "0/1", "N/A"):
        fps = video.get("r_frame_rate") or "30/1"
    return {
        "duration_seconds": float(data.get("format", {}).get("duration") or 0),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": fps,
        "has_audio": audio is not None,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name") if audio else None,
    }


def load_midas():
    import torch

    # Keep model inference predictable on GitHub's CPU runner.
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 2)))
    # MiDaS_small calls torch.hub.load("rwightman/gen-efficientnet-pytorch", ...)
    # internally. GitHub Actions is non-interactive, so explicitly pre-authorize the
    # exact dependency repository name that the pinned official MiDaS source requests.
    # This avoids an interactive prompt/EOFError while preserving the official call path.
    hub_dir = Path(torch.hub.get_dir())
    trusted_file = hub_dir / "trusted_list"
    trusted_file.parent.mkdir(parents=True, exist_ok=True)
    existing = set(trusted_file.read_text(encoding="utf-8").splitlines()) if trusted_file.exists() else set()
    existing.add("rwightman_gen-efficientnet-pytorch")
    trusted_file.write_text("\n".join(sorted(existing)) + "\n", encoding="utf-8")
    model_ref = f"{MIDAS_REPO}:{MIDAS_COMMIT}"
    model = torch.hub.load(model_ref, MIDAS_MODEL, trust_repo=True, verbose=True)
    model.eval()
    return torch, model


def infer_depth(frame, torch, model):
    """Infer a normalized inverse-depth map for one BGR frame using MiDaS_small."""
    import cv2
    import numpy as np

    height, width = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    # MiDaS_small is trained for 256px input. Keep aspect ratio and use multiples of 32.
    scale = min(256.0 / max(1, width), 256.0 / max(1, height))
    small_w = max(32, int((width * scale) // 32) * 32)
    small_h = max(32, int((height * scale) // 32) * 32)
    resized = cv2.resize(rgb, (small_w, small_h), interpolation=cv2.INTER_CUBIC)
    image = resized.astype(np.float32) / 255.0
    mean = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)
    tensor = torch.from_numpy(((image - mean) / std).transpose(2, 0, 1).copy()).unsqueeze(0)
    with torch.inference_mode():
        prediction = model(tensor)
        if prediction.ndim == 3:
            prediction = prediction.unsqueeze(1)
        prediction = torch.nn.functional.interpolate(
            prediction, size=(height, width), mode="bicubic", align_corners=False
        )
        depth = prediction.squeeze().detach().cpu().numpy().astype(np.float32)

    low, high = np.percentile(depth, (2.0, 98.0))
    if not np.isfinite(low) or not np.isfinite(high) or high - low < 1e-6:
        return np.full((height, width), 0.5, dtype=np.float32)
    depth = np.clip((depth - low) / (high - low), 0.0, 1.0)
    return depth


def looks_like_scene_cut(previous, current) -> bool:
    import cv2
    import numpy as np

    a = cv2.cvtColor(cv2.resize(previous, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(cv2.resize(current, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(np.mean(np.abs(a - b))) >= 28.0


def synthesize_sbs(frame, depth, max_disparity: float):
    """Create left/right views with bounded horizontal parallax and safe edge fill."""
    import cv2
    import numpy as np

    height, width = frame.shape[:2]
    x = np.broadcast_to(np.arange(width, dtype=np.float32), (height, width))
    y = np.broadcast_to(np.arange(height, dtype=np.float32)[:, None], (height, width))
    shift = (depth - 0.5) * max_disparity
    # Nearer objects move in opposite directions in the two eye views.
    left_x = x - shift
    right_x = x + shift
    left = cv2.remap(frame, left_x, y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    right = cv2.remap(frame, right_x, y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return np.concatenate((left, right), axis=1)


def activate_model(report_path: Path) -> int:
    import numpy as np

    started = time.monotonic()
    try:
        torch, model = load_midas()
        dummy = np.zeros((180, 320, 3), dtype=np.uint8)
        depth = infer_depth(dummy, torch, model)
        if depth.shape != (180, 320) or not np.isfinite(depth).all():
            raise ValueError("MiDaS activation inference returned an invalid depth map.")
        report(report_path, {
            "status": "success",
            "engine": "MiDaS AI",
            "model": MIDAS_MODEL,
            "repository": f"https://github.com/{MIDAS_REPO}",
            "pinned_commit": MIDAS_COMMIT,
            "source_license": "MIT",
            "device": "CPU",
            "activation_inference": "passed",
            "ffmpeg_sbs_stage": "next",
            "elapsed_seconds": round(time.monotonic() - started, 2),
        })
        return 0
    except Exception as exc:
        report(report_path, {
            "status": "failed",
            "engine": "MiDaS AI",
            "model": MIDAS_MODEL,
            "reason": f"{type(exc).__name__}: {str(exc)[:500]}",
            "elapsed_seconds": round(time.monotonic() - started, 2),
        })
        return 1


def convert(args) -> int:
    import cv2
    import numpy as np

    started = time.monotonic()
    source = args.input.resolve()
    output = args.output.resolve()
    base = {
        "engine": "MiDaS AI + FFmpeg",
        "model": MIDAS_MODEL,
        "model_repository": f"https://github.com/{MIDAS_REPO}",
        "pinned_commit": MIDAS_COMMIT,
        "stereo_mode": "SBS",
        "standard_master_untouched": True,
        "original_audio_required": True,
        "requested_max_disparity_px_at_1080p": args.max_disparity_px,
    }

    try:
        if source == output:
            raise ValueError("Refusing to overwrite the standard rendered master.")
        if not source.is_file() or source.stat().st_size < 100_000:
            raise ValueError("Final rendered master is missing or unexpectedly small.")
        source_info = probe(source)
        if not source_info["has_audio"]:
            raise ValueError("Source master has no audio; refusing an output without narration.")
        if source_info["width"] <= source_info["height"]:
            raise ValueError("SBS conversion is restricted to landscape long-form videos.")
        if not 1 <= source_info["duration_seconds"] <= args.max_duration_seconds:
            raise ValueError(f"Video duration exceeds safe limit ({args.max_duration_seconds:g}s).")
        if args.mode != "SBS" or args.content_format != "LONG_VIDEO":
            raise ValueError("This MiDaS + FFmpeg stage is only enabled for LONG_VIDEO SBS.")

        output.parent.mkdir(parents=True, exist_ok=True)
        output.unlink(missing_ok=True)

        torch, model = load_midas()
        cap = cv2.VideoCapture(str(source))
        if not cap.isOpened():
            raise ValueError("OpenCV could not decode the source master.")
        fps = source_info["fps"]
        width, height = source_info["width"], source_info["height"]
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        max_disparity = float(args.max_disparity_px) * height / 1080.0

        ffmpeg_log = args.report.parent / "midas_ffmpeg.log"
        ffmpeg_log.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pixel_format", "bgr24",
            "-video_size", f"{width * 2}x{height}", "-framerate", fps,
            "-i", "pipe:0", "-i", str(source),
            "-map", "0:v:0", "-map", "1:a:0", "-map_metadata", "1",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-x264opts", "frame-packing=3",
            "-c:a", "copy", "-shortest", "-movflags", "+faststart",
            str(output),
        ]
        frames_done = 0
        last_progress = 0
        with ffmpeg_log.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
            try:
                while True:
                    batch = []
                    for _ in range(args.depth_stride):
                        ok, frame = cap.read()
                        if not ok:
                            break
                        if frame.shape[1] != width or frame.shape[0] != height:
                            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
                        batch.append(frame)
                    if not batch:
                        break

                    # Split at obvious cuts so interpolation never bridges two unrelated scenes.
                    segments = []
                    segment_start = 0
                    for i in range(1, len(batch)):
                        if looks_like_scene_cut(batch[i - 1], batch[i]):
                            segments.append(batch[segment_start:i])
                            segment_start = i
                    segments.append(batch[segment_start:])

                    for segment in segments:
                        if not segment:
                            continue
                        depth_start = infer_depth(segment[0], torch, model)
                        depth_end = infer_depth(segment[-1], torch, model) if len(segment) > 1 else depth_start
                        denominator = max(1, len(segment) - 1)
                        for index, frame in enumerate(segment):
                            if time.monotonic() - started > args.max_conversion_seconds:
                                raise TimeoutError(f"MiDaS + FFmpeg exceeded {args.max_conversion_seconds}s limit.")
                            alpha = index / denominator
                            depth = (1.0 - alpha) * depth_start + alpha * depth_end
                            stereo = synthesize_sbs(frame, depth, max_disparity)
                            process.stdin.write(stereo.tobytes())
                            frames_done += 1
                            if frames_done - last_progress >= 150:
                                pct = (100.0 * frames_done / total_frames) if total_frames else 0.0
                                print(f"MiDaS/FFmpeg SBS progress: {frames_done}/{total_frames or '?'} frames ({pct:.1f}%)", flush=True)
                                last_progress = frames_done
                process.stdin.close()
                return_code = process.wait(timeout=180)
                if return_code != 0:
                    detail = ffmpeg_log.read_text(encoding="utf-8", errors="replace")[-3000:]
                    raise RuntimeError(f"FFmpeg failed with exit code {return_code}: {detail}")
            except Exception:
                if process.stdin and not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except (BrokenPipeError, OSError):
                        pass
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=30)
                raise
            finally:
                cap.release()

        if frames_done < 1 or not output.is_file() or output.stat().st_size < 100_000:
            raise ValueError("MiDaS/FFmpeg did not create a usable SBS video.")
        output_info = probe(output)
        expected = (width * 2, height)
        actual = (output_info["width"], output_info["height"])
        if actual != expected:
            raise ValueError(f"SBS geometry mismatch: expected {expected}, got {actual}.")
        if not output_info["has_audio"]:
            raise ValueError("SBS output lost the original narration/audio.")
        if abs(output_info["duration_seconds"] - source_info["duration_seconds"]) > 1.0:
            raise ValueError("SBS duration differs from master by more than one second.")
        report(args.report, {
            **base,
            "status": "success",
            "output": str(output),
            "depth_estimation": "MiDaS_small keyframes with interpolation between keyframes and scene-cut resets",
            "ffmpeg_encoding": "libx264; H.264 frame-packing=3; original audio stream-copied",
            "source": source_info,
            "output_probe": output_info,
            "frames_processed": frames_done,
            "quality_checks": {
                "separate_file_not_overwriting_master": True,
                "video_dimensions_correct_for_mode": True,
                "audio_preserved": True,
                "duration_matches_master": True,
            },
            "elapsed_seconds": round(time.monotonic() - started, 1),
        })
        return 0
    except Exception as exc:
        output.unlink(missing_ok=True)
        report(args.report, {
            **base,
            "status": "failed",
            "reason": f"{type(exc).__name__}: {str(exc)[:900]}",
            "standard_master_untouched": True,
            "fallback": "No 2D upload fallback; the workflow must stop for investigation.",
            "elapsed_seconds": round(time.monotonic() - started, 1),
        })
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="Download/load pinned MiDaS and validate a real inference.")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mode", default="SBS", choices=["SBS"])
    parser.add_argument("--content-format", default="LONG_VIDEO", choices=["LONG_VIDEO", "SHORT"])
    parser.add_argument("--report", type=Path, default=Path("work/stereo_3d_report.json"))
    parser.add_argument("--max-duration-seconds", type=float, default=480.0)
    parser.add_argument("--max-conversion-seconds", type=int, default=5400)
    parser.add_argument("--depth-stride", type=int, default=8)
    parser.add_argument("--max-disparity-px", type=float, default=16.0)
    parser.add_argument("--require-success", action="store_true")
    args = parser.parse_args()

    if args.check_only:
        return activate_model(args.report)
    if not args.input or not args.output:
        parser.error("--input and --output are required unless --check-only is set")
    if args.depth_stride < 2 or args.depth_stride > 16:
        parser.error("--depth-stride must be between 2 and 16")
    if not 4.0 <= args.max_disparity_px <= 24.0:
        parser.error("--max-disparity-px must be between 4 and 24")
    return convert(args)


if __name__ == "__main__":
    raise SystemExit(main())
