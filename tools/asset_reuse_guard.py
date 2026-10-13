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

def read_manifest(path=MANIFEST):
    path=Path(path)
    if not path.exists(): return []
    out=[]
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: item=json.loads(line)
        except json.JSONDecodeError: raise SystemExit("Asset manifest contains invalid JSON; blocking upload.")
        if isinstance(item,dict): out.append(item)
    return out

def scene_file(scene):
    safe=re.sub(r"[^A-Za-z0-9_-]","_",str(scene or ""))[:80]
    return Path("assets")/f"scene_{safe}.mp4"

def asset_file(item):
    """Return only the asset path explicitly logged for this source, constrained to assets/."""
    requested = str(item.get("asset_path") or "").strip()
    if requested:
        path = Path(requested)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "assets":
            raise SystemExit(f"Unsafe asset_path in source manifest: {requested!r}")
        return path
    # Backward-compatible path for historical licensed-video source rows.
    return scene_file(item.get("scene"))

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
            asset_file(item).unlink(missing_ok=True)
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

def seed(content_id, manifest_path):
    history=load_history()
    if history.get("used"):
        print(json.dumps({"status":"history_already_seeded","assets":len(history["used"])}))
        return
    source=Path(manifest_path)
    if not source.is_file():
        raise SystemExit(f"Cannot seed repeat protection: prior asset manifest is missing: {source}")
    prior_records=read_manifest(source)
    if not prior_records:
        raise SystemExit("Cannot seed repeat protection: prior successful video manifest is empty.")
    used=[]; seen=set()
    for item in prior_records:
        keys=identity(item)
        # Existing video manifests may lack new relevance scores, but the assets
        # still count as used. Record every stable identity so future reuse is blocked.
        if not keys:
            continue
        if keys & seen:
            continue
        record=dict(item)
        record["content_id"]=str(content_id)
        record["history_source"]="seeded_from_previous_verified_renderer_artifact"
        used.append(record)
        seen.update(keys)
    if not used:
        raise SystemExit("Cannot seed repeat protection: prior manifest has no stable asset identities.")
    history["version"]=1
    history["used"]=used
    history["updated_at_utc"]=datetime.now(timezone.utc).isoformat(timespec="seconds")
    HISTORY.parent.mkdir(parents=True,exist_ok=True)
    HISTORY.write_text(json.dumps(history,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    save_report({"status":"seeded_from_previous_verified_upload","content_id":str(content_id),
                 "seeded_assets":len(used),"history_file":str(HISTORY),
                 "source_manifest":str(source),"duplicate_guard":"enabled_before_next_upload"})

def merge_history(candidate_path):
    history=load_history()
    used=history.setdefault("used",[])
    current_keys=set()
    for item in used:
        current_keys.update(identity(item))
    source=Path(candidate_path)
    if not source.is_file():
        raise SystemExit(f"Cannot recover concurrent asset-history update: missing candidate {source}")
    candidate=json.loads(source.read_text(encoding="utf-8"))
    candidate_items=candidate.get("used") if isinstance(candidate,dict) else None
    if not isinstance(candidate_items,list):
        raise SystemExit("Cannot recover concurrent asset-history update: candidate history format is invalid.")
    added=0
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    for item in candidate_items:
        keys=identity(item)
        if not keys:
            continue
        if keys & current_keys:
            continue
        record=dict(item)
        record["merged_after_concurrent_delivery"]=True
        record["history_merged_at_utc"]=now
        used.append(record)
        current_keys.update(keys)
        added+=1
    history["version"]=1
    history["updated_at_utc"]=now
    HISTORY.parent.mkdir(parents=True,exist_ok=True)
    HISTORY.write_text(json.dumps(history,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    save_report({"status":"merged_concurrent_asset_history","new_records":added,
                 "total_history_assets":len(used),"candidate":str(source),
                 "deduplication":"passed"})

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
    p.add_argument("--mode",choices=("seed","validate","persist","merge-history"),required=True)
    p.add_argument("--content-id",required=True)
    p.add_argument("--manifest",default="work/previous_assets.jsonl")
    p.add_argument("--candidate",default="work/asset_history_candidate.json")
    a=p.parse_args()
    if a.mode=="validate":
        validate(a.content_id)
    elif a.mode=="persist":
        persist(a.content_id)
    elif a.mode=="merge-history":
        merge_history(a.candidate)
    else:
        seed(a.content_id,a.manifest)

if __name__=="__main__": main()
