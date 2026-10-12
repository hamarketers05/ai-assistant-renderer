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
    clips=[]; expected=[]
    for row in rows:
        if len(row)<7: continue
        try:
            start,end=float(row[1]),float(row[2]); planned=end-start
        except (ValueError,IndexError):
            raise SystemExit(f"Invalid voice-timed scene row: {row[:4]}")
        path=Path("scenes")/f"scene_{safe(row[0])}.mp4"
        if not path.is_file() or path.stat().st_size<1000:
            raise SystemExit(f"Missing rendered scene clip: {path}")
        source_duration=probe_duration(path)
        if planned<=args.transition+0.1:
            raise SystemExit(f"Planned scene too short for transition: {path} ({planned:.2f}s)")
        if source_duration<planned-0.35:
            raise SystemExit(f"Rendered clip is shorter than its planned voice interval: {path} ({source_duration:.2f}s < {planned:.2f}s)")
        clips.append((path,planned)); expected.append((start,end))
    if len(clips)<2: raise SystemExit("At least two rendered scene clips are required.")
    planned_total=sum(d for _,d in clips)
    if abs(planned_total-args.target_duration)>0.45:
        raise SystemExit(f"Scene timeline ({planned_total:.2f}s) does not match narration ({args.target_duration:.2f}s).")
    for i in range(1,len(expected)):
        if abs(expected[i][0]-expected[i-1][1])>0.025:
            raise SystemExit("Scene timeline contains a gap/overlap; refusing a misaligned render.")
    cmd=["ffmpeg","-hide_banner","-loglevel","error","-y"]
    for path,_ in clips: cmd.extend(["-i",str(path)])
    filters=[]
    for i,(_,planned) in enumerate(clips):
        # Pad incoming scenes by the overlap length, so each xfade starts at the
        # true spoken boundary and does not shift later scene changes earlier.
        tail=args.transition if i<len(clips)-1 else 0.0
        filters.append(
            f"[{i}:v]trim=duration={planned:.3f},setpts=PTS-STARTPTS,fps=30,"
            f"format=yuv420p,tpad=stop_mode=clone:stop_duration={tail:.3f},"
            f"trim=duration={planned+tail:.3f},settb=AVTB[v{i}]"
        )
    current="v0"
    cumulative=clips[0][1]+(args.transition if len(clips)>1 else 0.0)
    transition_types=["fade","smoothleft","wipeleft","slideleft","fadeblack","smoothright"]
    used_transitions=[]
    for i in range(1,len(clips)):
        out=f"x{i}"
        offset=max(0.0,cumulative-args.transition)
        transition=transition_types[(i-1)%len(transition_types)]
        used_transitions.append(transition)
        filters.append(f"[{current}][v{i}]xfade=transition={transition}:duration={args.transition:.3f}:offset={offset:.3f}[{out}]")
        current=out
        cumulative+=clips[i][1]+(args.transition if i<len(clips)-1 else 0.0)-args.transition
    padding=max(0.0,args.target_duration-cumulative)
    if padding>0.20:
        raise SystemExit(f"Visual track would require {padding:.2f}s frozen-tail padding; scene boundaries need correction.")
    filter=";".join(filters)+f";[{current}]tpad=stop_mode=clone:stop_duration={padding:.3f}[vout]"
    cmd.extend(["-filter_complex",filter,"-map","[vout]","-an","-t",f"{args.target_duration:.3f}",
                "-c:v","libx264","-preset","veryfast","-crf","22","-r","30","-pix_fmt","yuv420p",
                "-movflags","+faststart",args.output])
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    run(cmd)
    duration=probe_duration(args.output)
    if abs(duration-args.target_duration)>0.25:
        raise SystemExit(f"Transition render duration mismatch: {duration:.2f}s vs {args.target_duration:.2f}s.")
    report={"scenes":len(clips),"transition":"alternating cinematic xfade","transition_types":sorted(set(used_transitions)),
            "transition_seconds":args.transition,"target_duration_seconds":args.target_duration,
            "rendered_duration_seconds":round(duration,3),"loops_entire_video":False,
            "clip_duration_total_seconds":round(sum(d for _,d in clips),3),
            "untrimmed_crossfade_timeline_seconds":round(cumulative,3),
            "final_frame_padding_seconds":round(padding,3),
            "planned_scene_timeline_seconds":round(planned_total,3),
            "scene_boundary_alignment":"voice-timestamped boundaries; crossfades do not compress scene start times"}
    Path("work/transitions_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))
if __name__=="__main__": main()
