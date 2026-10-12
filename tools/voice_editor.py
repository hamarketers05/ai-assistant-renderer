#!/usr/bin/env python3
"""Free, local voice-editing stage for AI Tech Lab's automatically generated narration.

Cleans generated narration, inserts punctuation-aware pauses, applies light script-cue
level shaping, and generates captions from the edited timeline. Speech synthesis runs
upstream; this local stage uses no paid speech API.
"""
import json
import re
import subprocess
from pathlib import Path

from faster_whisper import WhisperModel
from pydub import AudioSegment

SOURCE = Path("voice.wav")
SCRIPT_PATH = Path("work/script.txt")
WORK = Path("work")
CLEAN = WORK / "voice_clean.wav"
EDITED = WORK / "voice_edited.wav"
CAPTIONS = WORK / "captions.srt"
REPORT = WORK / "voice_edit_report.json"


def run(command):
    subprocess.run(command, check=True)


def stamp(seconds):
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def classify(text):
    value = text.lower()
    serious = (
        "risk", "danger", "warning", "privacy", "security", "threat",
        "misuse", "harm", "critical", "ethical", "ethics", "job loss",
        "layoff", "consequence", "concern", "vulnerability", "failure",
    )
    energetic = (
        "breakthrough", "incredible", "remarkable", "surprising", "exciting",
        "revolution", "amazing", "unprecedented", "game changer", "finally",
        "powerful", "dramatically", "major leap", "transform", "imagine",
    )
    curious = ("why", "how", "what if", "question", "mystery", "could", "might")
    if any(term in value for term in serious):
        return "serious", 0.55
    if any(term in value for term in energetic) or "!" in value:
        return "energetic", 0.9
    if "?" in value or any(term in value for term in curious):
        return "curious", 0.35
    return "neutral", 0.0


def punctuation(word):
    text = word.strip()
    if not text:
        return ""
    final = text[-1]
    return final if final in ",;:.!?" else ""


def pause_ms(mark):
    # Generated narration already includes natural breath and comma pauses.
    # Add only short sentence-ending pauses; long per-word pauses stretched a
    # five-minute narration to nearly nine minutes and broke the duration QA.
    if mark == "?":
        return 220
    if mark == "!":
        return 180
    if mark == ".":
        return 150
    return 0


def emit_captions(words, shifts):
    entries = []
    batch = []
    index = 1

    def flush():
        nonlocal index, batch
        if not batch:
            return
        text = " ".join(item["text"] for item in batch).strip()
        if text:
            start = max(0.0, batch[0]["start"] + shifts[batch[0]["index"]])
            end = max(start + 0.12, batch[-1]["end"] + shifts[batch[-1]["index"]])
            entries.append(f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}\n")
            index += 1
        batch = []

    for item in words:
        batch.append(item)
        mark = punctuation(item["text"])
        if len(batch) >= 5 or mark:
            flush()
    flush()
    if not entries:
        raise SystemExit("Voice editor could not create any caption entries.")
    CAPTIONS.write_text("\n".join(entries), encoding="utf-8")
    return len(entries)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    if not SOURCE.is_file() or SOURCE.stat().st_size < 10_000:
        raise SystemExit("Generated narration audio is missing or too small; rendering is blocked.")
    if not SCRIPT_PATH.is_file() or not SCRIPT_PATH.read_text(encoding="utf-8").strip():
        raise SystemExit("The English script is missing; narration editing is blocked.")

    script = SCRIPT_PATH.read_text(encoding="utf-8").strip()
    script_sentences = [
        part.strip() for part in re.split(r"(?<=[.!?])\s+", script) if part.strip()
    ]

    # Open-source FFmpeg audio mastering: rumble/high-frequency trim, gentle denoise,
    # light compression and platform-friendly loudness normalization.
    audio_filter = (
        "highpass=f=80,lowpass=f=16000,afftdn=nr=4:nf=-32,"
        "equalizer=f=180:t=q:w=1:g=1.5,"
        "equalizer=f=2800:t=q:w=1:g=1.8,"
        "acompressor=threshold=0.16:ratio=2.4:attack=10:release=160:makeup=3,"
        "loudnorm=I=-16:TP=-1.5:LRA=9"
    )
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(SOURCE), "-af", audio_filter,
        "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(CLEAN),
    ])

    audio = AudioSegment.from_wav(str(CLEAN))
    if len(audio) < 30_000:
        raise SystemExit("Narration audio is under 30 seconds; QA blocks production.")
    if audio.dBFS == float("-inf") or audio.dBFS < -55:
        raise SystemExit("Voice audio is silent or too quiet; production is blocked.")

    # CPU/int8 Whisper is free to run on the GitHub Actions runner; no paid API.
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        str(CLEAN),
        language="en",
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    words = []
    for segment in segments:
        for item in (getattr(segment, "words", None) or []):
            if item.start is None or item.end is None:
                continue
            text = (item.word or "").strip()
            if text:
                words.append({
                    "start": max(0.0, float(item.start)),
                    "end": max(float(item.start) + 0.01, float(item.end)),
                    "text": text,
                    "index": len(words),
                })
    if len(words) < 5:
        raise SystemExit("Voice validation failed: speech could not be reliably transcribed.")

    edited = AudioSegment.empty()
    cursor_ms = 0
    group_start = 0
    cumulative_shift = 0.0
    shifts = [0.0] * len(words)
    script_sentence_index = 0
    cues_used = []
    added_pause_ms = 0
    inserted_pause_count = 0
    last_boundary = -1

    for i, item in enumerate(words):
        mark = punctuation(item["text"])
        target = pause_ms(mark)
        if not target:
            continue

        # Keep a short tail of the spoken word and a short lead-in to the next word;
        # replace existing inter-word gap with at least the punctuation's target pause.
        end_ms = min(len(audio), max(cursor_ms, int(item["end"] * 1000) + 30))
        chunk = audio[cursor_ms:end_ms]
        group_words = words[group_start:i + 1]
        transcript_part = " ".join(word["text"] for word in group_words)
        script_part = (
            script_sentences[script_sentence_index]
            if script_sentence_index < len(script_sentences)
            else transcript_part
        )
        cue_name, gain = classify(script_part + " " + transcript_part)
        if gain and len(chunk) > 0:
            chunk = chunk.apply_gain(gain)
        if chunk:
            edited += chunk
        for word_index in range(group_start, i + 1):
            shifts[word_index] = cumulative_shift
        cues_used.append(cue_name)

        if i + 1 < len(words):
            next_start_ms = max(end_ms, int(words[i + 1]["start"] * 1000) - 30)
            existing_gap = max(0, next_start_ms - end_ms)
            chosen_pause = max(target, existing_gap)
            silence = AudioSegment.silent(duration=chosen_pause, frame_rate=audio.frame_rate)
            silence = silence.set_channels(audio.channels).set_sample_width(audio.sample_width)
            edited += silence
            added_pause_ms += max(0, chosen_pause - existing_gap)
            if chosen_pause > 0:
                inserted_pause_count += 1
            cumulative_shift += (chosen_pause - existing_gap) / 1000.0
            cursor_ms = next_start_ms
            group_start = i + 1
        else:
            # Preserve breath/tail audio after the last recognized word.
            edited += audio[end_ms:]
            cursor_ms = len(audio)
            group_start = i + 1

        if mark in ".!?":
            script_sentence_index += 1
        last_boundary = i

    if group_start < len(words):
        remaining = audio[cursor_ms:]
        transcript_part = " ".join(word["text"] for word in words[group_start:])
        script_part = (
            script_sentences[script_sentence_index]
            if script_sentence_index < len(script_sentences)
            else transcript_part
        )
        cue_name, gain = classify(script_part + " " + transcript_part)
        if gain and len(remaining) > 0:
            remaining = remaining.apply_gain(gain)
        edited += remaining
        for word_index in range(group_start, len(words)):
            shifts[word_index] = cumulative_shift
        cues_used.append(cue_name)
    elif last_boundary < 0:
        # No recognized punctuation: retain the cleaned recording without cuts.
        edited = audio
        shifts = [0.0] * len(words)

    if len(edited) < 30_000 or edited.dBFS == float("-inf"):
        raise SystemExit("Edited voice failed duration or signal validation.")
    edited.export(str(EDITED), format="wav")

    caption_count = emit_captions(words, shifts)
    report = {
        "status": "passed",
        "manual_voice_required": False,
        "input_file": str(SOURCE),
        "output_file": str(EDITED),
        "language": getattr(info, "language", "en"),
        "input_duration_seconds": round(len(audio) / 1000.0, 2),
        "edited_duration_seconds": round(len(edited) / 1000.0, 2),
        "duration_added_seconds": round(max(0, len(edited) - len(audio)) / 1000.0, 2),
        "extra_pause_seconds": round(added_pause_ms / 1000.0, 2),
        "pause_boundaries_processed": inserted_pause_count,
        "caption_entries": caption_count,
        "script_cues": {name: cues_used.count(name) for name in sorted(set(cues_used))},
        "processing": [
            "high-pass/low-pass filtering",
            "gentle FFT denoising",
            "light compression",
            "loudness normalization to -16 LUFS target",
            "script-guided punctuation pauses",
            "subtle cue-based phrase-level gain shaping",
        ],
        "limitations": [
            "Audio processing cannot fully manufacture natural acting/emotion from a flat recording.",
            "Kokoro voice expressiveness has model limits; retain sentence-level pauses and subtle processing rather than aggressive pitch effects.",
        ],
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "passed",
        "edited_duration_seconds": report["edited_duration_seconds"],
        "extra_pause_seconds": report["extra_pause_seconds"],
        "caption_entries": caption_count,
    }))


if __name__ == "__main__":
    main()
