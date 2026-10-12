#!/usr/bin/env python3
"""Render script-ordered scene clips with short FFmpeg crossfades and no scene-loop repetition."""
from __future__ import annotations
import argparse, csv, json, math, re, subprocess
from pathlib import Path

def run(args, capture=False):
    result=subprocess.run(args,check=True,text=True,capture_output=capture)
    return result.stdout.strip() if capture else ""

def probe_duration(path):
    out=run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],True)
    value=float(out)
    if not math.isfinite(value) or value<=0: raise ValueError(f"Bad scene duration for {path}: {value}")
    return value

def safe(value):
    return re.sub(r"[^A-Za-z0-9_-]","_",str(value))[:80]

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--scenes",default="work/scenes.tsv")
    p.add_argument("--target-duration",type=float,required=True)
    p.add_argument("--output",default="work/visual_track.mp4")
    p.add_argument("--transition",type=float,default=0.5)
    args=p.parse_args()
    if not 5<=args.target_duration<=3600: raise SystemExit("Target video duration is outside safe limits.")
    if not 0.2<=args.transition<=0.8: raise SystemExit("Transition duration must be 0.2–0.8 seconds.")
    rows=list(csv.reader(Path(args.scenes).open(encoding="utf-8"),delimiter="\t"))
    clips=[]
    for row in rows:
        if len(row)<7: continue
        path=Path("scenes")/f"scene_{safe(row[0])}.mp4"
        if not path.is_file() or path.stat().st_size<1000:
            raise SystemExit(f"Missing rendered scene clip: {path}")
        duration=probe_duration(path)
        if duration<=args.transition+0.1: raise SystemExit(f"Scene is too short for crossfade: {path} ({duration:.2f}s)")
        clips.append((path,duration))
    if len(clips)<2: raise SystemExit("At least two rendered scene clips are needed for transitions.")
    cmd=["ffmpeg","-hide_banner","-loglevel","error","-y"]
    for path,_ in clips: cmd.extend(["-i",str(path)])
    filters=[]
    for i,(_,_) in enumerate(clips):
        # Pad each scene by the transition length so each transition overlaps a cloned
        # tail frame, preserving the original per-scene timing rather than shortening it.
        filters.append(f"[{i}:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p,settb=AVTB,tpad=stop_mode=clone:stop_duration={args.transition:.3f}[v{i}]")
    current="v0"; cumulative=clips[0][1]
    for i in range(1,len(clips)):
        out=f"x{i}"
        filters.append(f"[{current}][v{i}]xfade=transition=fade:duration={args.transition:.3f}:offset={cumulative:.3f}[{out}]")
        current=out
        cumulative+=clips[i][1]
    # Remove the intentionally added transition padding from final requested duration.
    desired=max(args.target_duration,min(cumulative+args.transition, sum(d for _,d in clips)+args.transition))
    # If the scene plan undershoots narration, freeze only the final shot instead of
    # looping the entire timeline back to the opening.
    filter= ";".join(filters)+f";[{current}]tpad=stop_mode=clone:stop_duration={max(0.0,args.target_duration-cumulative):.3f}[vout]"
    cmd.extend(["-filter_complex",filter,"-map","[vout]","-an","-t",f"{args.target_duration:.3f}",
                "-c:v","libx264","-preset","veryfast","-crf","22","-r","30","-pix_fmt","yuv420p",
                "-movflags","+faststart",args.output])
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    run(cmd)
    duration=probe_duration(args.output)
    if duration+0.15<args.target_duration:
        raise SystemExit(f"Transition render shorter than narration: {duration:.2f}s < {args.target_duration:.2f}s")
    report={"scenes":len(clips),"transition":"crossfade","transition_seconds":args.transition,
            "target_duration_seconds":args.target_duration,"rendered_duration_seconds":round(duration,3),
            "loops_entire_video":False,"clip_duration_total_seconds":round(sum(d for _,d in clips),3)}
    Path("work/transitions_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))
if __name__=="__main__": main()
