#!/usr/bin/env python3
"""Create a sentence-timed, voice-duration-aware visual plan for every narration sentence."""
import argparse, csv, json, re
from pathlib import Path

def sentences(text):
    text=re.sub(r"\s+"," ",text).strip()
    parts=re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])",text)
    return [p.strip() for p in parts if p.strip()]

def short_label(text, limit=76):
    words=text.split()
    out=[]
    for word in words:
        candidate=" ".join(out+[word])
        if len(candidate)>limit: break
        out.append(word)
    return " ".join(out) or text[:limit]

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--script",default="work/script.txt")
    p.add_argument("--duration",type=float,required=True)
    p.add_argument("--output",default="work/scenes.tsv")
    p.add_argument("--max-scenes",type=int,default=48)
    a=p.parse_args()
    text=Path(a.script).read_text(encoding="utf-8").strip()
    if not text or a.duration<30: raise SystemExit("Script or approved narration duration is invalid.")
    items=sentences(text)
    if not items: raise SystemExit("Could not split script into sentence-level scenes.")
    # Keep sentence-level cuts; only combine adjacent sentences when the plan would be too large.
    if len(items)>a.max_scenes:
        grouped=[]; chunk=max(2,(len(items)+a.max_scenes-1)//a.max_scenes)
        for i in range(0,len(items),chunk): grouped.append(" ".join(items[i:i+chunk]))
        items=grouped
    usable=max(1.0,a.duration-4.0)
    # Keep each visual long enough for a readable sentence and a valid transition.
    max_scenes_by_duration=max(1,int(usable//3.2))
    if len(items)>max_scenes_by_duration:
        grouped=[]; chunk=max(2,(len(items)+max_scenes_by_duration-1)//max_scenes_by_duration)
        for i in range(0,len(items),chunk): grouped.append(" ".join(items[i:i+chunk]))
        items=grouped
    weights=[max(4,len(re.findall(r"\b[\w'-]+\b",s))) for s in items]
    total=sum(weights)
    minimum=3.0
    extra=max(0.0,usable-minimum*len(items))
    cursor=0.0; rows=[]
    for i,(sentence,weight) in enumerate(zip(items,weights),1):
        dur=minimum+extra*weight/total
        start=cursor; end=cursor+dur; cursor=end
        # Full sentence is retained as the search prompt; scene art and overlays use its meaning.
        query=re.sub(r"\s+"," ",sentence).strip()[:180]
        overlay=short_label(sentence,52)
        rows.append([str(i),f"{start:.3f}",f"{end:.3f}",f"{dur:.3f}","generated",query,overlay])
    # Correct floating-point drift in the final scene.
    if rows:
        rows[-1][2]=f"{usable:.3f}"
        rows[-1][3]=f"{max(3.0,usable-float(rows[-1][1])):.3f}"
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",encoding="utf-8",newline="") as f: csv.writer(f,delimiter="\t",lineterminator="\n").writerows(rows)
    report={"script_sentences":len(sentences(text)),"planned_visual_scenes":len(rows),"duration_seconds":round(usable,2),"alignment":"sentence-weighted estimate; final captions are aligned to actual voice via Whisper","visual_change_policy":"one scene per sentence, or a small adjacent-sentence group when capped"}
    Path("work/scene_director_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))
if __name__=="__main__": main()
