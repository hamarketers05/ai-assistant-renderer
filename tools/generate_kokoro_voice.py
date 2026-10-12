#!/usr/bin/env python3
"""Automatic free American-English TTS using Kokoro-82M (Apache-2.0 model)."""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--script",default="work/script.txt")
    p.add_argument("--output",default="work/kokoro_voice.wav")
    p.add_argument("--voice",default="af_heart")
    p.add_argument("--speed",type=float,default=1.0)
    args=p.parse_args()
    script=Path(args.script).read_text(encoding="utf-8").strip()
    script=re.sub(r"[ \t]+"," ",script)
    script=re.sub(r"\n{3,}","\n\n",script).strip()
    # Kokoro splits on newlines; sentence-level chunks prevent oversized model inputs.
    script=re.sub(r"(?<=[.!?])\s+(?=[A-Z0-9\"“])","\n",script)
    if len(script)<100: raise SystemExit("Kokoro fallback requires the actual long-form narration script.")
    if len(script)>30000: raise SystemExit("Narration is longer than the safe local TTS limit.")
    if not 0.75<=args.speed<=1.2: raise SystemExit("TTS speed must be between 0.75 and 1.2.")
    try:
        import numpy as np
        import soundfile as sf
        from kokoro import KPipeline
    except Exception as exc:
        raise SystemExit("Kokoro dependencies are not available: "+str(exc)[:240])
    pipeline=KPipeline(lang_code="a")
    pieces=[]
    total_samples=0
    for _, sentence, audio in pipeline(script, voice=args.voice, speed=args.speed, split_pattern=r"\n+"):
        if audio is None: continue
        arr=np.asarray(audio,dtype=np.float32).reshape(-1)
        if arr.size:
            if not np.isfinite(arr).all(): raise SystemExit("Kokoro generated invalid audio samples.")
            pieces.append(arr)
            total_samples+=arr.size
            # Small natural breaths between synthesized segments; no long artificial word gaps.
            pause=0.22 if str(sentence).rstrip().endswith((".", "!", "?")) else 0.12
            pieces.append(np.zeros(int(pause*24000),dtype=np.float32))
    if not pieces or total_samples<24000*10: raise SystemExit("Kokoro produced less than 10 seconds of voice.")
    audio=np.concatenate(pieces).astype(np.float32)
    peak=float(np.max(np.abs(audio)))
    if peak>1.0: audio=audio/peak*0.96
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    sf.write(str(out),audio,24000,subtype="PCM_16")
    with sf.SoundFile(str(out)) as wav:
        duration=len(wav)/wav.samplerate
        if wav.samplerate!=24000 or duration<10: raise SystemExit("Kokoro output failed its sample-rate/duration check.")
    report={"engine":"Kokoro-82M","license":"Apache-2.0 model; MIT inference library; espeak-ng dependency GPL-3.0",
            "voice":args.voice,"language":"American English","sample_rate":24000,
            "duration_seconds":round(duration,2),"script_characters":len(script),"peak_before_normalization":peak,
            "manual_voice_required":False}
    Path("work/kokoro_tts_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))
if __name__=="__main__": main()
