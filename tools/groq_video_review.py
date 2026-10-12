#!/usr/bin/env python3
"""Pre-upload review: sample the rendered video, ask Groq vision to inspect frames, and persist actionable QA feedback."""
from __future__ import annotations
import base64, json, os, re, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL", "openai/gpt-oss-20b")
VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"

def read_json(path, fallback):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback

def run(args, capture=False):
    proc = subprocess.run(args, check=True, text=True, capture_output=capture)
    return proc.stdout.strip() if capture else ""

def groq_call(model, messages, max_tokens=800, json_mode=True):
    key=os.getenv("GROQ_API_KEY","").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    payload={"model":model,"temperature":0.1,"max_tokens":max_tokens,"messages":messages}
    if json_mode:
        payload["response_format"]={"type":"json_object"}
    data=json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        req=urllib.request.Request(GROQ_API,data=data,headers={
            "Authorization":"Bearer "+key,"Content-Type":"application/json","Accept":"application/json"})
        try:
            with urllib.request.urlopen(req,timeout=90) as response:
                result=json.loads(response.read().decode("utf-8"))
            choices=result.get("choices") or []
            if not choices:
                raise RuntimeError("Groq returned no choices")
            text=choices[0].get("message",{}).get("content","")
            try:
                answer=json.loads(text)
            except json.JSONDecodeError:
                match=re.search(r"\{.*\}",text,re.S)
                if not match:
                    raise RuntimeError("Groq returned an invalid review response")
                answer=json.loads(match.group(0))
            if not isinstance(answer,dict):
                raise RuntimeError("Groq review response was not an object")
            return answer
        except urllib.error.HTTPError as exc:
            if (exc.code==429 or exc.code>=500) and attempt<2:
                try: pause=min(20,max(2,int(float(exc.headers.get("Retry-After","3")))))
                except ValueError: pause=3*(attempt+1)
                time.sleep(pause)
                continue
            raise RuntimeError(f"Groq review request failed with HTTP {exc.code}") from None
        except (urllib.error.URLError,TimeoutError,json.JSONDecodeError) as exc:
            if attempt<2:
                time.sleep(2+2*attempt)
                continue
            raise RuntimeError(f"Groq review request failed: {type(exc).__name__}") from None
    raise RuntimeError("Groq review did not complete after retries")

def probe(path):
    data=json.loads(run(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(path)],True))
    streams=data.get("streams",[])
    v=next((s for s in streams if s.get("codec_type")=="video"),{})
    a=next((s for s in streams if s.get("codec_type")=="audio"),{})
    return {
        "duration_seconds":round(float(data.get("format",{}).get("duration",0) or 0),2),
        "size_bytes":int(data.get("format",{}).get("size",0) or 0),
        "video_codec":v.get("codec_name"),"audio_codec":a.get("codec_name"),
        "width":int(v.get("width",0) or 0),"height":int(v.get("height",0) or 0),
        "fps":str(v.get("avg_frame_rate","0/1")),"has_video":bool(v),"has_audio":bool(a),
        "audio_sample_rate":a.get("sample_rate"),"audio_channels":a.get("channels"),
        "bit_rate":data.get("format",{}).get("bit_rate"),
    }

def sample_frames(video, duration, directory):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    cap=cv2.VideoCapture(str(video))
    fps=float(cap.get(cv2.CAP_PROP_FPS) or 0)
    count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if fps<=0 or count<=0:
        cap.release()
        raise RuntimeError("Could not decode the rendered video's frame timeline")
    total=count
    width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    sample_n=max(12,min(50,int(duration/5)))
    positions=np.linspace(min(duration-1,4.5),max(4.6,duration-1.0),sample_n)
    grays=[]; blacks=[]; selected=[]
    for i,sec in enumerate(positions):
        cap.set(cv2.CAP_PROP_POS_MSEC,max(0,float(sec))*1000)
        ok,frame=cap.read()
        if not ok or frame is None:
            continue
        small=cv2.resize(frame,(64,36))
        gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
        grays.append(gray)
        mean,std=float(np.mean(gray)),float(np.std(gray))
        blacks.append(mean<4 and std<2)
        # Three evenly separated story moments for multimodal review.
        if i in {max(0,sample_n//6), sample_n//2, min(sample_n-1,(sample_n*5)//6)}:
            target=directory/f"video_frame_{len(selected)+1}.jpg"
            h,w=frame.shape[:2]
            ratio=min(512/max(w,h),1.0)
            resized=cv2.resize(frame,(max(1,int(w*ratio)),max(1,int(h*ratio))))
            cv2.imwrite(str(target),resized,[int(cv2.IMWRITE_JPEG_QUALITY),52])
            selected.append({"path":str(target),"timestamp_seconds":round(float(sec),1)})
    cap.release()
    changes=[float(np.mean(cv2.absdiff(grays[i-1],grays[i]))) for i in range(1,len(grays))]
    return {
        "decoded_samples":len(grays),"sampled_frames":selected,"near_black_frame_ratio":round(sum(blacks)/max(1,len(blacks)),3),
        "active_visual_change_ratio":round(sum(x>=0.8 for x in changes)/max(1,len(changes)),3),
        "mean_frame_change":round(float(np.mean(changes)) if changes else 0,3),
        "source_frame_count":total,"width":width,"height":height,"fps":round(fps,3)
    }

def image_data_url(path):
    raw=Path(path).read_bytes()
    if len(raw)>1_500_000:
        raise RuntimeError("A sampled review frame exceeded the safe image payload limit")
    return "data:image/jpeg;base64,"+base64.b64encode(raw).decode("ascii")

def main():
    video=Path(sys.argv[1] if len(sys.argv)>1 else "output/AI_TECH_LAB_video.mp4")
    thumbnail=Path(sys.argv[2] if len(sys.argv)>2 else "output/thumbnail.jpg")
    script_path=Path(sys.argv[3] if len(sys.argv)>3 else "work/script.txt")
    title_path=Path(sys.argv[4] if len(sys.argv)>4 else "work/title.txt")
    out=Path(sys.argv[5] if len(sys.argv)>5 else "work/video_review_report.json")
    title=title_path.read_text(encoding="utf-8").strip()
    script=script_path.read_text(encoding="utf-8").strip()
    sources=[]
    for line in Path("work/asset_sources.jsonl").read_text(encoding="utf-8").splitlines() if Path("work/asset_sources.jsonl").exists() else []:
        try:
            item=json.loads(line)
            sources.append({k:item.get(k) for k in ("provider","scene","creator","license_label","license_url","source_url","commercial_use_allowed")})
        except json.JSONDecodeError:
            continue
    scene_rows=[]
    for line in Path("work/scenes.tsv").read_text(encoding="utf-8").splitlines() if Path("work/scenes.tsv").exists() else []:
        row=line.split("\t")
        if len(row)>=7:
            scene_rows.append({"id":row[0],"start":row[1],"end":row[2],"visual_query":row[5][:180],"overlay":row[6][:100]})
    previous=read_json("learning/latest_video_review.json",{})
    report={"generated_at_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"title":title,
            "review_status":"started","decision":"BLOCK","top_improvements":[],"repeat_issues_to_avoid":[],
            "blocking_issues":[],"review_scope":"Rendered MP4 and thumbnail sampled before YouTube upload; this is a quality-control review, not a guarantee of factual truth."}
    try:
        if not video.is_file() or not thumbnail.is_file() or not script_path.is_file():
            raise RuntimeError("Rendered video, thumbnail, or script is missing")
        metrics=probe(video)
        if not metrics["has_video"] or not metrics["has_audio"]:
            raise RuntimeError("Final video must contain both audio and video streams")
        if metrics["duration_seconds"]<30 or metrics["width"]<720 or metrics["height"]<720:
            raise RuntimeError("Rendered video's duration or dimensions are below the safety threshold")
        if not Path("work/voice_edited.wav").is_file() or not Path("work/music.wav").is_file():
            raise RuntimeError("Narration master or generated music is missing")
        captions=Path("work/captions.srt").read_text(encoding="utf-8") if Path("work/captions.srt").exists() else ""
        music_probe=probe_audio=run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0","work/music.wav"],True)
        music_seconds=round(float(music_probe or 0),2)
        cue_count=captions.count(" --> ")
        scene_report=read_json("work/scene_director_report.json",{})
        with Image.open(thumbnail) as im:
            thumb_size=list(im.size)
            im.verify()
        frames=sample_frames(video,metrics["duration_seconds"],"work/review_frames")
        local_issues=[]
        if frames["near_black_frame_ratio"]>0.20:
            local_issues.append("More than 20% of sampled timeline frames are almost black")
        if frames["active_visual_change_ratio"]<0.20:
            local_issues.append("Very low visual change across sampled timeline; possible repeated/static shots")
        if cue_count<10:
            local_issues.append("Caption cue count is unexpectedly low")
        if music_seconds<max(5,metrics["duration_seconds"]-20):
            local_issues.append("Generated music bed is shorter than the final video timeline")
        if thumb_size != [1280,720]:
            local_issues.append("Thumbnail is not 1280x720")
        if len(scene_rows)<4:
            local_issues.append("Fewer than four sentence-directed visual scenes were prepared")

        frame_prompt = (
          "Review these three actual sampled frames from one finished AI explainer video in timeline order. "
          "The three attached images are at the timestamps listed in the text. Evaluate whether the footage/graphics feel "
          "topic-specific, cinematic, varied, coherent, and plausibly aligned with the narration context. Detect generic or "
          "repeated visuals, awkward cropping, empty/black frames, illegible overlays, distracting effects, and visual mismatch. "
          "Do not infer facts that are not visible. Return JSON keys: visual_match_score (1-10), visual_quality_score (1-10), "
          "frame_reviews (array with timestamp, what_is_visible, fit_to_story, issue), critical_issues (array), "
          "improvement_actions (array), decision (PASS, IMPROVE, or BLOCK). Use BLOCK only for a severe mismatch or quality failure."
        )
        frame_content=[{"type":"text","text":frame_prompt+"\nTitle: "+title+
                       "\nNarration opening: "+script[:900]+
                       "\nScene-plan excerpts: "+json.dumps(scene_rows[:12],ensure_ascii=False)[:2600]+
                       "\nSample timestamps: "+json.dumps([x["timestamp_seconds"] for x in frames["sampled_frames"]])}]
        for frame in frames["sampled_frames"][:3]:
            frame_content.append({"type":"image_url","image_url":{"url":image_data_url(frame["path"])}})
        visual_review=groq_call(VISION_MODEL,[{"role":"user","content":frame_content}],max_tokens=750)

        thumb_content=[
          {"type":"text","text":"Assess this exact finished YouTube thumbnail for mobile readability, topic match, one clear focal point, strong contrast, tasteful premium AI-tech style, and non-misleading hook. Return JSON keys: topic_match_score (1-10), mobile_readability_score (1-10), focal_point_score (1-10), observed_text, issues (array), improvements (array), decision (PASS, IMPROVE, or BLOCK). Do not judge unseen video content."},
          {"type":"image_url","image_url":{"url":image_data_url(thumbnail)}}]
        thumb_review=groq_call(VISION_MODEL,[{"role":"user","content":thumb_content}],max_tokens=450)
        previous_summary={"title":previous.get("title",""),"decision":previous.get("decision","NONE"),
                          "top_improvements":previous.get("top_improvements",[])[:5] if isinstance(previous.get("top_improvements",[]),list) else []}
        final_review=groq_call(TEXT_MODEL,[{"role":"system","content":
          "You are the final quality router for AI Tech Lab. Judge the actual reported video/frame and thumbnail reviews, technical metrics, scene plan and manual QA output. Preserve facts. Minor improvements do not block upload. Return JSON keys: decision (PASS, IMPROVE, BLOCK), overall_score (1-10), blocking_issues (array), top_improvements (array, max 5), repeat_issues_to_avoid (array, max 5), summary, next_video_rules (array). BLOCK only for a severe factual, narration/audio, visual mismatch, unusable thumbnail, or technical defect; do not block for cosmetic preferences alone."},
          {"role":"user","content":json.dumps({"title":title,"video_metrics":metrics,"sampled_visual_metrics":frames,
            "music_seconds":music_seconds,"caption_cues":cue_count,"scene_director_report":scene_report,
            "script_word_count":len(re.findall(r"\b[\w'-]+\b",script)),"scene_plan_sample":scene_rows[:24],
            "asset_source_count":len(sources),"asset_sources_sample":sources[:20],
            "thumbnail_dimensions":thumb_size,"local_issues":local_issues,
            "visual_review":visual_review,"thumbnail_review":thumb_review,
            "previous_video_review":previous_summary},ensure_ascii=False)}],max_tokens=1000)

        decision=str(final_review.get("decision","IMPROVE")).upper()
        allowed={"PASS","IMPROVE","BLOCK"}
        if decision not in allowed: decision="IMPROVE"
        critical=list(final_review.get("blocking_issues",[])) if isinstance(final_review.get("blocking_issues",[]),list) else []
        if str(visual_review.get("decision","")).upper()=="BLOCK":
            critical.extend(visual_review.get("critical_issues",[]) if isinstance(visual_review.get("critical_issues",[]),list) else ["Vision review flagged a severe visual issue"])
        if str(thumb_review.get("decision","")).upper()=="BLOCK":
            critical.extend(thumb_review.get("issues",[]) if isinstance(thumb_review.get("issues",[]),list) else ["Vision review flagged a severe thumbnail issue"])
        if int(visual_review.get("visual_match_score",10) or 0)<4 or int(thumb_review.get("mobile_readability_score",10) or 0)<4:
            critical.append("A key visual relevance or thumbnail readability score fell below 4/10")
        if local_issues:
            critical.extend(local_issues)
        if critical:
            decision="BLOCK"
        report.update({
          "review_status":"completed","decision":decision,"overall_score":int(final_review.get("overall_score",0) or 0),
          "video_metrics":metrics,"sampled_visual_metrics":frames,"music_seconds":music_seconds,
          "caption_cues":cue_count,"scene_director_report":scene_report,"thumbnail_dimensions":thumb_size,
          "visual_review":visual_review,"thumbnail_review":thumb_review,"local_issues":local_issues,
          "blocking_issues":list(dict.fromkeys(str(x)[:350] for x in critical))[:12],
          "top_improvements":final_review.get("top_improvements",[])[:5] if isinstance(final_review.get("top_improvements",[]),list) else [],
          "repeat_issues_to_avoid":final_review.get("repeat_issues_to_avoid",[])[:5] if isinstance(final_review.get("repeat_issues_to_avoid",[]),list) else [],
          "next_video_rules":final_review.get("next_video_rules",[])[:6] if isinstance(final_review.get("next_video_rules",[]),list) else [],
          "summary":str(final_review.get("summary",""))[:1200],
          "asset_source_count":len(sources),"manual_voice_gate":"approved manual voice required; no synthetic fallback",
          "review_models":{"vision":VISION_MODEL,"router":TEXT_MODEL}})
    except Exception as exc:
        report.update({"review_status":"failed","decision":"BLOCK",
          "blocking_issues":[f"Final AI/vision review did not complete: {type(exc).__name__}: {str(exc)[:220]}"],
          "top_improvements":["Restore the free Groq API quota/key or correct the review error, then rerun final QA."],
          "repeat_issues_to_avoid":["Never upload a render whose required final review did not complete."]})
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    Path("work/video_review_metrics.json").write_text(json.dumps({
        "title":title,"decision":report.get("decision"),"review_status":report.get("review_status"),
        "overall_score":report.get("overall_score"),"top_improvements":report.get("top_improvements",[]),
        "blocking_issues":report.get("blocking_issues",[]),"summary":report.get("summary","")},indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({"review_status":report.get("review_status"),"decision":report.get("decision"),
                      "score":report.get("overall_score"),"blocking_issues":report.get("blocking_issues",[]),
                      "improvements":report.get("top_improvements",[])},ensure_ascii=False))
    # Report is written even when review fails; the workflow blocks upload in a separate step.

if __name__=="__main__":
    main()
