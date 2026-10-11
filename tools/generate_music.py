#!/usr/bin/env python3
"""Generate an original, royalty-free ambient technology score using NumPy/SciPy.

No sampled audio, external music API, or third-party composition is used.
The output is a low-level WAV bed; FFmpeg side-chain compression ducks it under narration.
"""
import argparse
import json
import math
import re
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

SAMPLE_RATE = 22050
BLOCK_SECONDS = 8
NOTE_NAMES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
              "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def midi_hz(midi):
    return 440.0 * (2.0 ** ((float(midi) - 69.0) / 12.0))


def mood_for(text):
    text = text.lower()
    if any(w in text for w in ("cybersecurity", "privacy", "risk", "safety", "threat", "warning", "ethics")):
        return "serious", 76, "minor"
    if any(w in text for w in ("tool", "productivity", "breakthrough", "launch", "automation", "agent")):
        return "energetic", 98, "major"
    if any(w in text for w in ("research", "science", "quantum", "space", "discovery", "experiment")):
        return "curious", 84, "sus2"
    return "cinematic", 88, "sus2"


def chord_progression(scale):
    if scale == "minor":
        return [(45, 52, 57, 60), (41, 48, 53, 57), (38, 45, 50, 53), (43, 50, 55, 59)]
    if scale == "major":
        return [(48, 55, 60, 64), (53, 60, 65, 69), (45, 52, 57, 60), (55, 62, 67, 71)]
    return [(48, 55, 60, 62), (45, 52, 57, 59), (50, 57, 62, 64), (43, 50, 55, 57)]


def render_music(duration, topic, output):
    if not math.isfinite(duration) or duration < 5 or duration > 3600:
        raise ValueError("Narration duration is outside safe music-generation limits.")

    mood, bpm, scale = mood_for(topic)
    chords = chord_progression(scale)
    beat_seconds = 60.0 / bpm
    bar_seconds = beat_seconds * 4
    total_samples = int(round(duration * SAMPLE_RATE))
    sos = butter(2, 0.12, btype="lowpass", output="sos")
    rng = np.random.default_rng(261011)

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)

        filtered_state = None
        start = 0
        while start < total_samples:
            count = min(BLOCK_SECONDS * SAMPLE_RATE, total_samples - start)
            t = (np.arange(start, start + count, dtype=np.float32) / SAMPLE_RATE)
            local = np.zeros(count, dtype=np.float32)

            bar_ids = np.floor(t / bar_seconds).astype(np.int32)
            for bar in np.unique(bar_ids):
                mask = bar_ids == bar
                bt = (t[mask] - float(bar) * bar_seconds).astype(np.float32)
                notes = chords[int(bar) % len(chords)]
                pad = np.zeros(bt.size, dtype=np.float32)
                for j, midi in enumerate(notes):
                    f = midi_hz(midi + (12 if j == 3 else 0))
                    vibrato = 0.12 * np.sin(2 * np.pi * (0.07 + j * 0.013) * bt)
                    phase = 2 * np.pi * (f * bt + vibrato)
                    pad += (0.38 / (j + 1)) * np.sin(phase)
                    pad += (0.10 / (j + 1)) * np.sin(2 * phase + 0.25)
                # Slow fade at each chord change avoids clicks and creates a soft pad.
                fade_in = np.clip(bt / 0.9, 0, 1)
                fade_out = np.clip((bar_seconds - bt) / 0.7, 0, 1)
                envelope = np.minimum(fade_in, fade_out)
                local[mask] += pad * envelope * 0.09

            # A quiet, filtered synthetic pulse/bass follows the tempo.
            beat_ids = np.floor(t / beat_seconds).astype(np.int64)
            beat_pos = t - beat_ids * beat_seconds
            beat_env = np.exp(-beat_pos * 9.0).astype(np.float32)
            bass_notes = [ch[0] - 12 for ch in chords]
            bass_freqs = np.array([midi_hz(bass_notes[(int(b) // 4) % len(chords)]) for b in beat_ids],
                                  dtype=np.float32)
            local += 0.055 * np.sin(2 * np.pi * bass_freqs * t) * beat_env

            # Original filtered noise at a very low level adds texture, not a sample.
            noise = rng.normal(0.0, 0.012, count).astype(np.float32)
            filtered = sosfilt(sos, noise)
            local += filtered.astype(np.float32)

            # Fade score at the start/end and prevent any hard block edge.
            fade_in = np.clip(t / 1.8, 0.0, 1.0)
            remaining = (duration - t)
            fade_out = np.clip(remaining / 2.8, 0.0, 1.0)
            local *= np.minimum(fade_in, fade_out).astype(np.float32)
            local = np.tanh(local * 1.3) * 0.45
            stereo = np.column_stack((local, np.roll(local, int(SAMPLE_RATE * 0.009))))
            pcm = np.clip(stereo * 32767, -32768, 32767).astype("<i2")
            wav.writeframes(pcm.tobytes())
            start += count

    report = {
        "status": "generated",
        "source": "original_synthesized",
        "uses_external_samples": False,
        "mood": mood,
        "tempo_bpm": bpm,
        "mode": scale,
        "duration_seconds": round(duration, 2),
        "sample_rate_hz": SAMPLE_RATE,
        "licensing": "Original programmatic composition; no third-party audio samples."
    }
    Path("work/music_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--topic", default="")
    parser.add_argument("--output", default="work/music.wav")
    args = parser.parse_args()
    render_music(args.duration, args.topic, args.output)


if __name__ == "__main__":
    main()
