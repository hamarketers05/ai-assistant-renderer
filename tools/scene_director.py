#!/usr/bin/env python3
"""Align scene boundaries to word timestamps from the final edited narration."""
from __future__ import annotations
import argparse, csv, difflib, json, math, re
from pathlib import Path

TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)*")

def norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(word).lower().replace("’", "'"))

def sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    return [p.strip() for p in re.split(r'(?<=[.!?])["”’)]*\s+(?=[A-Z0-9"“\'])', text) if p.strip()]

def short_label(text: str, limit: int = 76) -> str:
    out = []
    for word in text.split():
        candidate = " ".join(out + [word])
        if len(candidate) > limit: break
        out.append(word)
    return " ".join(out) or text[:limit]

def align_words(script_words, asr, duration):
    asr_words = [norm(x.get("text", "")) for x in asr]
    matcher = difflib.SequenceMatcher(a=script_words, b=asr_words, autojunk=False)
    points = {}
    exact = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        a_len, b_len = i2-i1, j2-j1
        if tag == "equal":
            exact += a_len
            for k in range(a_len): points[i1+k] = j1+k
        elif tag == "replace" and a_len and b_len:
            for k in range(a_len):
                points[i1+k] = j1 + min(b_len-1, int((k+0.5)*b_len/a_len))
    sequence_ratio = matcher.ratio()
    mapped_ratio = len(points)/max(1,len(script_words))
    exact_ratio = exact/max(1,len(script_words))
    if sequence_ratio < 0.55 or mapped_ratio < 0.70:
        raise SystemExit("VOICE/SCENE ALIGNMENT BLOCKED: narration differs from script "
                         f"(sequence={sequence_ratio:.3f}, mapped={mapped_ratio:.3f}).")
    timings = [None] * len(script_words)
    for i,j in points.items():
        start=max(0.0,float(asr[j].get("start",0.0)))
        end=min(duration,max(start+0.015,float(asr[j].get("end",start+0.02))))
        timings[i]=(start,end)

    # Interpolate only unmatched script tokens between anchored spoken words.
    i=0
    while i<len(timings):
        if timings[i] is not None:
            i+=1
            continue
        j=i
        while j<len(timings) and timings[j] is None: j+=1
        count=j-i
        left=timings[i-1] if i>0 else None
        right=timings[j] if j<len(timings) else None
        if left and right:
            low,high=left[1],right[0]
            if high<=low: low,high=left[0],right[1]
            span=max(0.02,high-low)
            for k in range(count):
                start=low+span*k/count; end=low+span*(k+1)/count
                timings[i+k]=(max(0.0,start),min(duration,max(start+0.015,end)))
        elif right:
            high=right[0]; span=min(high,0.25*count)
            for k in range(count):
                start=max(0.0,high-span+span*k/count)
                end=min(high,max(start+0.015,high-span+span*(k+1)/count))
                timings[i+k]=(start,end)
        elif left:
            low=left[1]; span=max(0.02,duration-low)
            for k in range(count):
                start=min(duration-0.02,low+span*k/count)
                end=min(duration,max(start+0.015,low+span*(k+1)/count))
                timings[i+k]=(start,end)
        else:
            raise SystemExit("Voice alignment produced no timestamp anchors.")
        i=j
    normalized=[]; previous=0.0
    for item in timings:
        start,end=item or (previous,min(duration,previous+0.02))
        start=min(duration-0.02,max(previous,start))
        end=min(duration,max(start+0.015,end))
        normalized.append((start,end)); previous=start
    return normalized,exact_ratio,sequence_ratio,mapped_ratio

def make_groups(sentence_data,duration,max_scenes,word_times,display_words,punctuation_marks):
    """Split long sentences into voice-timed visual phrases near four seconds."""
    target=max(3.6,float(duration)/max(1,int(max_scenes)))
    groups=[]
    weak_endings={"a","an","the","and","or","to","for","of","in","with","by","on","at","as","from"}
    for sentence in sentence_data:
        start_idx=int(sentence["token_start"])
        limit=int(sentence["token_end"])
        while start_idx<limit:
            remaining=float(word_times[limit-1][1])-float(word_times[start_idx][0])
            if remaining<=target+0.25:
                end_idx=limit
            else:
                candidates=[]
                min_duration=max(2.2,target-0.9)
                max_duration=target+1.25
                for stop in range(start_idx+1,limit+1):
                    elapsed=float(word_times[stop-1][1])-float(word_times[start_idx][0])
                    if elapsed<min_duration:
                        continue
                    if elapsed>max_duration:
                        break
                    punctuation=punctuation_marks[stop-1]
                    score=abs(elapsed-target)
                    if punctuation in (",",";",":"):
                        score-=0.45
                    elif punctuation in (".","!","?"):
                        score-=0.65
                    if re.sub(r"[^a-z]+","",display_words[stop-1].lower()) in weak_endings:
                        score+=0.35
                    candidates.append((score,stop))
                if candidates:
                    end_idx=min(candidates)[1]
                else:
                    end_idx=start_idx+1
                    while end_idx<limit and float(word_times[end_idx-1][1])-float(word_times[start_idx][0])<target:
                        end_idx+=1
            if end_idx<=start_idx:
                end_idx=start_idx+1
            groups.append([{
                "text":" ".join(display_words[start_idx:end_idx]),
                "token_start":start_idx,
                "token_end":end_idx,
                "start":float(word_times[start_idx][0]),
                "end":float(word_times[end_idx-1][1]),
            }])
            start_idx=end_idx

    # Merge tiny phrase fragments instead of flashing to a new visual for a
    # one-second sentence. Keep all boundaries on recognized word timestamps.
    min_scene=2.4
    while len(groups)>1:
        short=next((i for i,g in enumerate(groups)
                    if float(g[-1]["end"])-float(g[0]["start"])<min_scene),None)
        if short is None:
            break
        if short==0:
            groups[0].extend(groups[1]); del groups[1]
        else:
            groups[short-1].extend(groups[short]); del groups[short]

    # Hard cap for long scripts to keep CPU depth conversion bounded.
    while len(groups)>max(1,int(max_scenes)):
        merge_at=min(range(len(groups)-1),key=lambda i:
            abs((float(groups[i][-1]["end"])-float(groups[i][0]["start"]))+
                (float(groups[i+1][-1]["end"])-float(groups[i+1][0]["start"]))-target))
        groups[merge_at].extend(groups[merge_at+1])
        del groups[merge_at+1]
    return groups

def intervals(groups,duration):
    starts=[max(0.0,g[0]["start"]) for g in groups]
    ends=[min(duration,g[-1]["end"]) for g in groups]
    boundaries=[0.0]
    for i in range(1,len(groups)):
        boundaries.append(min(duration,max(boundaries[-1],starts[i],ends[i-1])))
    boundaries.append(duration)
    return [(boundaries[i],boundaries[i+1]) for i in range(len(groups))]

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--script",default="work/script.txt")
    p.add_argument("--duration",type=float,required=True)
    p.add_argument("--output",default="work/scenes.tsv")
    p.add_argument("--max-scenes",type=int,default=90)
    p.add_argument("--timestamps",default="work/voice_word_timestamps.json")
    a=p.parse_args()
    script=Path(a.script).read_text(encoding="utf-8").strip()
    duration=float(a.duration)
    if not script or duration<20: raise SystemExit("Script or edited narration duration is invalid.")
    timestamp_path=Path(a.timestamps)
    if not timestamp_path.is_file(): raise SystemExit("Exact scene timing blocked: final word timestamps are missing.")
    ts=json.loads(timestamp_path.read_text(encoding="utf-8"))
    asr=ts.get("words") or []
    if len(asr)<5: raise SystemExit("Exact scene timing blocked: too few spoken word timestamps.")
    ts_duration=float(ts.get("duration_seconds") or 0)
    if abs(ts_duration-duration)>0.55:
        raise SystemExit(f"Timestamp duration mismatch: {ts_duration:.3f}s vs narration {duration:.3f}s.")
    sentence_data=[]; script_words=[]
    for sentence in sentences(script):
        words=[norm(m.group(0)) for m in TOKEN_RE.finditer(sentence)]
        words=[w for w in words if w]
        if words:
            sentence_data.append({"text":sentence,"token_start":len(script_words),"token_end":len(script_words)+len(words)})
            script_words.extend(words)
    if not script_words: raise SystemExit("Script contains no alignable words.")
    word_times,exact_ratio,sequence_ratio,mapped_ratio=align_words(script_words,asr,duration)
    for item in sentence_data:
        item["start"]=word_times[item["token_start"]][0]
        item["end"]=word_times[item["token_end"]-1][1]
    token_matches=list(TOKEN_RE.finditer(script))
    display_words=[]; punctuation_marks=[]
    for match in token_matches:
        rest=script[match.end():]
        punctuation_match=re.match(r"([,;:.!?]+)",rest)
        punctuation=punctuation_match.group(1) if punctuation_match else ""
        display_words.append(match.group(0)+punctuation)
        punctuation_marks.append(punctuation[-1:] if punctuation else "")
    if len(display_words)!=len(script_words):
        raise SystemExit("Scene phrase planner tokenization differs from script alignment.")
    groups=make_groups(sentence_data,duration,max(1,a.max_scenes),word_times,display_words,punctuation_marks)
    while len(groups)>1:
        spans=intervals(groups,duration)
        short=next((i for i,(lo,hi) in enumerate(spans) if hi-lo<0.80),None)
        if short is None: break
        if short<len(groups)-1:
            groups[short]=groups[short]+groups[short+1]; del groups[short+1]
        else:
            groups[-2]=groups[-2]+groups[-1]; groups.pop()
    spans=intervals(groups,duration)
    rows=[]
    for idx,(group,(start,end)) in enumerate(zip(groups,spans),1):
        scene_text=" ".join(x["text"] for x in group)
        if end-start<0.65: raise SystemExit(f"Scene {idx} is too short ({end-start:.3f}s).")
        label=" ".join(scene_text.split()[:12])[:52]
        query=re.sub(r"\s+"," ",scene_text).strip()[:220]
        rows.append([str(idx),f"{start:.3f}",f"{end:.3f}",f"{end-start:.3f}","generated",query,label])
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",encoding="utf-8",newline="") as stream:
        csv.writer(stream,delimiter="\t",lineterminator="\n").writerows(rows)
    lengths=[end-start for start,end in spans]
    report={"script_sentences":len(sentence_data),"planned_visual_scenes":len(rows),
      "voice_duration_seconds":round(duration,3),"duration_seconds":round(duration,3),
      "timing_source":"Faster-Whisper word timestamps from final edited narration",
      "alignment":"script tokens aligned to recognized words; visual boundaries follow sentence onsets",
      "exact_word_timing":True,"sequence_similarity":round(sequence_ratio,4),
      "exact_token_match_ratio":round(exact_ratio,4),"mapped_script_token_ratio":round(mapped_ratio,4),
      "timestamp_word_count":len(asr),
      "scene_duration_seconds":{"min":round(min(lengths),3),"max":round(max(lengths),3),"mean":round(sum(lengths)/len(lengths),3)},
      "visual_change_policy":"word-timestamped clause-aware scene phrases targeting about 3.6-4.0 seconds; short phrases merge to avoid flicker; capped at 90 scenes"}
    Path("work/scene_director_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))
if __name__=="__main__": main()
