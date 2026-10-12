#!/usr/bin/env python3
"""Reject weakly matched or previously delivered stock video; record after verified delivery."""
from __future__ import annotations
import argparse, json, re, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

HISTORY=Path("learning/used_visual_assets.json")
MANIFEST=Path("work/asset_sources.jsonl")
REPORT=Path("work/asset_reuse_report.json")
MIN_LICENSED_CLIPS=4

def canonical_url(value):
    try:
        p=urllib.parse.urlsplit(str(value or ""))
        return (p.scheme.lower(),p.netloc.lower(),p.path.rstrip("/").lower())
    except Exception:
        return ("","","")

def norm(value):
    return re.sub(r"[^a-z0-9]+"," ",str(value or "").lower()).strip()

def identity(item):
    provider=norm(item.get("provider"))
    asset_id=norm(item.get("asset_id") or item.get("resource_id"))
    source=canonical_url(item.get("source_url"))
    title=norm(item.get("asset_title") or item.get("title"))
    creator=norm(item.get("creator"))
    keys=set()
    if provider and asset_id: keys.add("id:"+provider+":"+asset_id)
    if provider and source[0]=="https" and source[1]: keys.add("url:"+provider+":"+"|".join(source))
    if provider and title and creator: keys.add("title:"+provider+":"+title+":"+creator)
    return keys

def load_history():
    if not HISTORY.exists(): return {"version":1,"used":[]}
    data=json.loads(HISTORY.read_text(encoding="utf-8"))
    if not isinstance(data,dict) or not isinstance(data.get("used",[]),list):
        raise SystemExit("Visual-asset history is corrupt; refusing to assume assets are unique.")
    return data

def read_manifest():
    if not MANIFEST.exists(): return []
    out=[]
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: item=json.loads(line)
        except json.JSONDecodeError: raise SystemExit("Asset manifest contains invalid JSON; blocking upload.")
        if isinstance(item,dict): out.append(item)
    return out

def scene_file(scene):
    safe=re.sub(r"[^A-Za-z0-9_-]","_",str(scene or ""))[:80]
    return Path("assets")/f"scene_{safe}.mp4"

def save_report(data):
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(data,ensure_ascii=False))

def validate(content_id):
    history=load_history()
    prior=set()
    for item in history.get("used",[]): prior.update(identity(item))
    seen=set(); raw=read_manifest(); accepted=[]; removed=[]
    for item in raw:
        scene=str(item.get("scene") or "")
        provider=str(item.get("provider") or "")
        url=str(item.get("source_url") or "")
        creator=str(item.get("creator") or "")
        try: relevance=float(item.get("relevance_score") or 0)
        except (TypeError,ValueError): relevance=0.0
        keys=identity(item); reason=""
        if not url.startswith("https://") or not provider or not creator or not keys:
            reason="missing verified source, creator or stable asset identity"
        elif relevance<0.18:
            reason=f"weakly scene-matched asset (relevance {relevance:.3f} < 0.18)"
        elif keys & prior:
            reason="asset was used in a previously delivered video"
        elif keys & seen:
            reason="same asset selected for multiple scenes in this video"
        if reason:
            scene_file(scene).unlink(missing_ok=True)
            removed.append({"scene":scene,"provider":provider,"asset_title":item.get("asset_title") or item.get("title"),"reason":reason})
            continue
        accepted.append(item); seen.update(keys)
    MANIFEST.parent.mkdir(parents=True,exist_ok=True)
    MANIFEST.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in accepted),encoding="utf-8")
    data={"status":"validated" if len(accepted)>=MIN_LICENSED_CLIPS else "blocked",
          "content_id":str(content_id),"candidate_assets":len(raw),"accepted_new_assets":len(accepted),
          "removed_assets":removed,"previous_video_reuse":False,"within_video_duplicates":False,
          "minimum_new_licensed_clips_required":MIN_LICENSED_CLIPS,
          "policy":"A stock visual from an earlier delivered video is excluded; weak matches are replaced by new generated scene art."}
    save_report(data)
    if len(accepted)<MIN_LICENSED_CLIPS:
        raise SystemExit(f"VISUAL NOVELTY GATE BLOCKED: {len(accepted)} new relevant licensed clips remain; {MIN_LICENSED_CLIPS} required.")

def persist(content_id):
    history=load_history(); used=history.setdefault("used",[]); already=set()
    for item in used: already.update(identity(item))
    additions=[]; now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    for item in read_manifest():
        keys=identity(item)
        if not keys or keys & already:
            raise SystemExit("Post-upload asset-history persistence found a duplicate or unidentified asset.")
        record=dict(item); record["content_id"]=str(content_id); record["delivered_at_utc"]=now
        additions.append(record); already.update(keys)
    used.extend(additions); history["version"]=1; history["updated_at_utc"]=now
    HISTORY.parent.mkdir(parents=True,exist_ok=True)
    HISTORY.write_text(json.dumps(history,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    save_report({"status":"persisted_after_verified_upload","content_id":str(content_id),
                 "new_assets_recorded":len(additions),"total_history_assets":len(used),
                 "history_file":str(HISTORY),"duplicate_guard":"passed"})

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=("validate","persist"),required=True)
    p.add_argument("--content-id",required=True)
    a=p.parse_args()
    validate(a.content_id) if a.mode=="validate" else persist(a.content_id)

if __name__=="__main__": main()
