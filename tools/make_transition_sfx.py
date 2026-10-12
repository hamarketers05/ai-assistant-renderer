#!/usr/bin/env python3
"""Generate original, subtle transition whooshes and digital ticks without sampled audio."""
from __future__ import annotations

import argparse
import csv
import json
import math
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

SAMPLE_RATE = 44_100


def read_scenes(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        for row in csv.reader(stream, delimiter="\t"):
            if len(row) < 4:
                continue
            try:
                rows.append({"scene": str(row[0]), "start": float(row[1]),
                             "end": float(row[2]), "duration": float(row[3])})
            except (TypeError, ValueError):
                raise SystemExit(f"Invalid scene timing row: {row[:4]}")
    if not rows:
        raise SystemExit("Transition SFX blocked: scene plan is empty.")
    if any(x["start"] < 0 or x["end"] <= x["start"] for x in rows):
        raise SystemExit("Transition SFX blocked: scene times are invalid.")
    return rows


def synthesize_event(rng: np.random.Generator, duration: float = 0.34) -> np.ndarray:
    n = max(1, int(round(duration * SAMPLE_RATE)))
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    noise = rng.normal(0.0, 1.0, n).astype(np.float32)
    sos = butter(3, [350, 8500], btype="bandpass", fs=SAMPLE_RATE, output="sos")
    filtered = sosfilt(sos, noise).astype(np.float32)
    envelope = np.sin(np.pi * np.clip(t / duration, 0.0, 1.0)) ** 1.35
    sweep_hz = 320.0 + 1700.0 * np.clip(t / duration, 0.0, 1.0)
    phase = 2 * np.pi * np.cumsum(sweep_hz) / SAMPLE_RATE
    whoosh = 0.12 * filtered * envelope + 0.07 * np.sin(phase) * envelope

    # A short, quiet high-frequency tick gives the wipe a digital edge without a
    # third-party sound file. Keep it below the whoosh and away from harsh peaks.
    tick_start = int(0.235 * SAMPLE_RATE)
    tick_n = min(int(0.018 * SAMPLE_RATE), n - tick_start)
    if tick_n > 0:
        tick_t = np.arange(tick_n, dtype=np.float32) / SAMPLE_RATE
        tick_env = np.exp(-tick_t * 185.0)
        whoosh[tick_start:tick_start + tick_n] += (
            0.045 * np.sin(2 * np.pi * 3100.0 * tick_t) * tick_env
        ).astype(np.float32)
    peak = float(np.max(np.abs(whoosh))) if whoosh.size else 0.0
    if peak > 0.40:
        whoosh *= 0.40 / peak
    return whoosh.astype(np.float32)


def render(scenes: list[dict], voice_duration: float, intro_seconds: float,
           lead_seconds: float, content_id: str, output: Path) -> dict:
    if not math.isfinite(voice_duration) or voice_duration < 20 or voice_duration > 3600:
        raise SystemExit("Transition SFX blocked: narration duration is outside limits.")
    if not 0 <= intro_seconds <= 20 or not 0 <= lead_seconds <= 0.5:
        raise SystemExit("Transition SFX configuration is outside safe bounds.")

    total_seconds = voice_duration + intro_seconds
    total_samples = int(math.ceil(total_seconds * SAMPLE_RATE))
    stereo = np.zeros((total_samples, 2), dtype=np.float32)
    seed = int.from_bytes(content_id.encode("utf-8")[:4].ljust(4, b"0"), "little")
    rng = np.random.default_rng(seed)
    event_starts = []

    # First scene has no incoming transition. Every subsequent boundary receives
    # one restrained whoosh/tick, cued just before the image transition starts.
    for boundary_index, scene in enumerate(scenes[1:], start=1):
        start_seconds = max(0.0, intro_seconds + scene["start"] - lead_seconds)
        start = int(round(start_seconds * SAMPLE_RATE))
        event = synthesize_event(rng)
        end = min(total_samples, start + len(event))
        if end <= start:
            continue
        event = event[:end - start]
        # Gentle alternating movement, not extreme 100%-left/right headphone
        # motion; dialog stays centered and the low-level bed is ducked under it.
        left_gain, right_gain = (0.78, 0.38) if boundary_index % 2 else (0.38, 0.78)
        stereo[start:end, 0] += event * left_gain
        stereo[start:end, 1] += event * right_gain
        event_starts.append(round(start_seconds, 3))

    peak = float(np.max(np.abs(stereo))) if stereo.size else 0.0
    if peak > 0.7:
        stereo *= 0.7 / peak
    pcm = np.clip(stereo * 32767.0, -32768, 32767).astype("<i2")
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())

    report = {
        "status": "generated",
        "provider": "Python + NumPy/SciPy procedural synthesis",
        "source_license": "Original synthesized effects; no third-party audio samples.",
        "sample_rate_hz": SAMPLE_RATE,
        "duration_seconds": round(total_seconds, 3),
        "transition_count": len(event_starts),
        "transition_effect": "quiet procedural whoosh plus short digital tick",
        "cue_lead_seconds": lead_seconds,
        "stereo_motion": "subtle alternating left/right on SFX only; narration stays centered",
        "mix_target": "low-level effects bed, side-chain ducked under narration",
        "event_start_seconds": event_starts,
        "output": str(output),
    }
    Path("work/transition_sfx_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "event_start_seconds"}))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenes", default="work/scenes.tsv")
    parser.add_argument("--voice-duration", type=float, required=True)
    parser.add_argument("--intro-seconds", type=float, default=4.0)
    parser.add_argument("--lead-seconds", type=float, default=0.22)
    parser.add_argument("--content-id", required=True)
    parser.add_argument("--output", default="work/transition_sfx.wav")
    args = parser.parse_args()
    render(read_scenes(Path(args.scenes)), args.voice_duration, args.intro_seconds,
           args.lead_seconds, args.content_id, Path(args.output))


if __name__ == "__main__":
    main()
