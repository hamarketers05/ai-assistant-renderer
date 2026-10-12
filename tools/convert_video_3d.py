#!/usr/bin/env python3
"""Safely create an optional stereoscopic companion; never alters the normal 2D master."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPOSITORY = "https://github.com/JulesMellot/2D3D.git"
PINNED_COMMIT = "a35d0281dea2a043b9490318d12b14dc39df0b5e"
CODE_LICENSE = "MIT"
FORMATS = {"SBS": "sbs", "TB": "tb", "ANAGLYPH": "anaglyph"}


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


def run_command(args: list[str], *, timeout: int, cwd: Path | None = None) -> None:
    print("+", " ".join(str(item) for item in args[:8]), "...")
    subprocess.run(args, cwd=str(cwd) if cwd else None, check=True, timeout=timeout)


def probe_video(path: Path) -> dict:
    raw = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(path),
        ],
        text=True,
        timeout=60,
    )
    data = json.loads(raw)
    streams = data.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not video:
        raise ValueError("Input/output does not contain a readable video stream.")
    return {
        "duration_seconds": float(data.get("format", {}).get("duration") or 0),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": str(video.get("avg_frame_rate") or "0/1"),
        "has_audio": audio is not None,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name") if audio else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=["OFF", "SBS", "TB", "ANAGLYPH"])
    parser.add_argument("--content-format", default="LONG_VIDEO", choices=["LONG_VIDEO", "SHORT"])
    parser.add_argument("--report", default="work/stereo_3d_report.json", type=Path)
    parser.add_argument("--max-duration-seconds", type=float, default=365.0)
    parser.add_argument("--max-conversion-seconds", type=int, default=1800)
    parser.add_argument("--require-success", action="store_true",
                        help="Fail the workflow unless a valid stereoscopic output is produced.")
    args = parser.parse_args()

    report_path = args.report
    started = time.monotonic()
    base = {
        "tool": "JulesMellot/2D3D",
        "repository": REPOSITORY,
        "code_license": CODE_LICENSE,
        "pinned_commit": PINNED_COMMIT,
        "model_profile": "fast",
        "model_license": "Apache-2.0 (Depth Anything V2 Small)",
        "main_video_untouched": True,
        "standard_master_is_publish_source": True,
        "requested_mode": args.mode,
    }

    if args.mode == "OFF":
        write_report(report_path, {
            **base,
            "status": "disabled",
            "reason": "Stereoscopic companion was not requested; normal 2D production is unchanged.",
        })
        return 1 if args.require_success else 0

    if args.content_format == "SHORT":
        write_report(report_path, {
            **base,
            "status": "skipped",
            "reason": "Portrait Shorts remain on the standard 2D path to avoid unsuitable stereo geometry.",
        })
        return 1 if args.require_success else 0

    source = args.input.resolve()
    output = args.output.resolve()
    if source == output:
        write_report(report_path, {
            **base, "status": "failed",
            "reason": "Safety check rejected an output path that would overwrite the standard video.",
        })
        return 0
    if not source.is_file() or source.stat().st_size < 100_000:
        write_report(report_path, {
            **base, "status": "skipped",
            "reason": "Completed master video is not available; the 3D export was not started.",
        })
        return 1 if args.require_success else 0

    source_probe = None
    try:
        source_probe = probe_video(source)
        if not source_probe["has_audio"]:
            raise ValueError("Source master has no audio; refusing to create a companion without narration.")
        if source_probe["width"] <= source_probe["height"]:
            raise ValueError("Stereoscopic export is limited to landscape masters.")
        if not 1 <= source_probe["duration_seconds"] <= args.max_duration_seconds:
            write_report(report_path, {
                **base, "status": "skipped", "source": source_probe,
                "reason": f"Source duration exceeds the safe automated limit ({args.max_duration_seconds:g}s).",
            })
            return 0

        output.parent.mkdir(parents=True, exist_ok=True)
        output.unlink(missing_ok=True)
        env = os.environ.copy()
        # Respect hardware if present, while using a CPU-only PyTorch wheel in standard Actions runners.
        env["TOKENIZERS_PARALLELISM"] = "false"

        with tempfile.TemporaryDirectory(prefix="ai-tech-lab-2d3d-") as temporary:
            root = Path(temporary)
            checkout = root / "2D3D"
            venv = root / ".venv"
            run_command(
                ["git", "clone", "--quiet", "--no-checkout", REPOSITORY, str(checkout)],
                timeout=180,
            )
            run_command(
                ["git", "-C", str(checkout), "fetch", "--quiet", "--depth", "1", "origin", PINNED_COMMIT],
                timeout=180,
            )
            run_command(
                ["git", "-C", str(checkout), "checkout", "--quiet", "--detach", PINNED_COMMIT],
                timeout=60,
            )
            # YouTube needs stereoscopic metadata to recognize side-by-side H.264 as 3D.
            # Patch only the temporary pinned checkout; standard project files stay untouched.
            if args.mode == "SBS":
                pipeline_file = checkout / "pipeline.py"
                upstream = pipeline_file.read_text(encoding="utf-8")
                needle = '"-pix_fmt", "yuv420p", "-c:a", "copy",'
                replacement = '"-pix_fmt", "yuv420p", *(["-x264opts", "frame-packing=3"] if format == "sbs" else []), "-c:a", "copy",'
                if upstream.count(needle) != 1:
                    raise ValueError("Pinned 2D3D source layout changed; refusing an unverified metadata patch.")
                pipeline_file.write_text(upstream.replace(needle, replacement), encoding="utf-8")
                print("Added YouTube H.264 side-by-side stereo metadata in the temporary checkout.")
            run_command([sys.executable, "-m", "venv", str(venv)], timeout=120)
            pip = str(venv / "bin" / "pip")
            python = str(venv / "bin" / "python")
            run_command(
                [pip, "install", "--disable-pip-version-check", "--no-cache-dir",
                 "--index-url", "https://download.pytorch.org/whl/cpu", "torch"],
                timeout=900,
                cwd=checkout,
            )
            run_command(
                [pip, "install", "--disable-pip-version-check", "--no-cache-dir",
                 "-r", "requirements.txt"],
                timeout=900,
                cwd=checkout,
            )
            run_command(
                [python, "test_pipeline.py"],
                timeout=240,
                cwd=checkout,
            )
            run_command(
                [
                    python, "main.py", str(source), "--output", str(output),
                    "--profile", "fast", "--format", FORMATS[args.mode],
                    "--strength", "0.015", "--smoothing", "0.55",
                    "--crf", "18", "--preset", "veryfast",
                ],
                timeout=max(60, args.max_conversion_seconds),
                cwd=checkout,
            )

        if not output.is_file() or output.stat().st_size < 100_000:
            raise ValueError("The 3D tool did not produce a sufficiently large output file.")
        output_probe = probe_video(output)
        expected = {
            "SBS": (source_probe["width"] * 2, source_probe["height"]),
            "TB": (source_probe["width"], source_probe["height"] * 2),
            "ANAGLYPH": (source_probe["width"], source_probe["height"]),
        }[args.mode]
        actual = (output_probe["width"], output_probe["height"])
        if actual != expected:
            raise ValueError(f"Output geometry mismatch: expected {expected}, got {actual}.")
        if not output_probe["has_audio"]:
            raise ValueError("3D output lost the original audio stream.")
        if abs(output_probe["duration_seconds"] - source_probe["duration_seconds"]) > 1.0:
            raise ValueError("3D output duration differs from the standard master by more than one second.")

        write_report(report_path, {
            **base,
            "status": "success",
            "output": str(output),
            "output_format": FORMATS[args.mode],
            "stereo_metadata": "H.264 frame-packing=3 added for YouTube SBS" if args.mode == "SBS" else "No YouTube SBS metadata; use the format with a compatible 3D viewer.",
            "source": source_probe,
            "output_probe": output_probe,
            "strength": 0.015,
            "temporal_smoothing": 0.55,
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
        # The stereo copy is optional. A model/download/CPU-time failure must not block the
        # separately rendered, QA-checked 2D master or alter the scheduled YouTube upload.
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        write_report(report_path, {
            **base,
            "status": "failed_optional_export",
            "source": source_probe,
            "reason": f"{type(exc).__name__}: {str(exc)[:500]}",
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "fallback": "Continue with the original QA-checked 2D master; no 3D file is published.",
        })
        return 1 if args.require_success else 0


if __name__ == "__main__":
    raise SystemExit(main())
