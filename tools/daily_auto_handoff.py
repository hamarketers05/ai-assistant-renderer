#!/usr/bin/env python3
"""Reserve safe D1 daily slots and create renderer dispatch payloads without uploading anything itself."""
from __future__ import annotations
import json, os, sys, urllib.error, urllib.request
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path("work")
NY = ZoneInfo("America/New_York")
WORKER_URL = os.getenv("HANDOFF_URL", "https://ai-tech-lab-daily-handoff.hamarketers05.workers.dev").rstrip("/")
SOURCE_RUN_ID = os.getenv("DAILY_SOURCE_RUN_ID", "").strip()
GITHUB_TOKEN = os.getenv("GH_TOKEN", "").strip()
DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() == "true"

def find_file(name):
    hits = list(Path(".").glob("**/" + name))
    hits = [p for p in hits if p.is_file()]
    if not hits:
        raise SystemExit("Required artifact file missing: " + name)
    return sorted(hits, key=lambda p: len(str(p)))[0]

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

def request_json(url, payload, token):
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json",
        "Accept": "application/json", "User-Agent": "AI-Tech-Lab-Daily-Handoff/1.0"
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:700]
        raise SystemExit("Handoff endpoint rejected request (HTTP " + str(exc.code) + "): " + detail) from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit("Handoff endpoint unavailable: " + type(exc).__name__) from None
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise SystemExit("Handoff endpoint returned an unsuccessful response: " + json.dumps(data)[:700])
    return data

def utc_at(slot_date, hour):
    local = datetime.combine(date.fromisoformat(slot_date), time(hour, 0), tzinfo=NY)
    if local.astimezone(timezone.utc) <= datetime.now(timezone.utc) + timedelta(hours=2):
        raise SystemExit("Schedule time is too close or in the past; publishing is blocked.")
    return local.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def make_request(pkg, sources, fmt, slot_date, category="", require_pair=False):
    return {
        "workflow_run_id": SOURCE_RUN_ID,
        "title": str(pkg.get("title", ""))[:100],
        "script": str(pkg.get("script", "")),
        "description": str(pkg.get("description", ""))[:4900],
        "tags": pkg.get("tags", []),
        "sources": sources[:12],
        "trend_basis": pkg.get("trend_basis", {}),
        "hook_audit": pkg.get("hook_audit", {}),
        "content_format": fmt,
        "slot_date": slot_date,
        "category": category,
        "require_pair": require_pair,
        "dry_run": DRY_RUN,
    }

def dispatch_payload(pkg, content_id, fmt, publish_at):
    tags = pkg.get("tags", [])
    if isinstance(tags, list):
        tags = ",".join(str(x) for x in tags)
    return {
        "ref": "main",
        "inputs": {
            "content_id": str(content_id),
            "content_format": fmt,
            "stereo_output": "2D",
            "title": str(pkg.get("title", ""))[:100],
            "script": str(pkg.get("script", "")),
            "description": str(pkg.get("description", ""))[:4900],
            "tags": str(tags)[:480],
            "editorial_category": str(pkg.get("editorial_category", "")),
            "publish_at": publish_at,
        },
    }

def main():
    if not SOURCE_RUN_ID.isdigit() or not GITHUB_TOKEN:
        raise SystemExit("Source workflow run ID and GitHub Actions token are required.")
    package_path = find_file("daily_content_package.json")
    evidence_path = find_file("research_evidence.json")
    short_path = find_file("short_content_package.json")
    package, evidence, short = read_json(package_path), read_json(evidence_path), read_json(short_path)
    if package.get("brand") != "AI Tech Lab" or package.get("target_audience") != "United States":
        raise SystemExit("Research package brand/audience validation failed.")
    long_words = int(package.get("script_word_count", 0) or 0)
    hook_score = int((package.get("hook_audit") or {}).get("score", 0) or 0)
    sources = evidence.get("sources", [])
    trend_basis = package.get("trend_basis") or {}
    trend_count = int(trend_basis.get("distinct_youtube_videos", 0) or 0)
    trend_gate = str(trend_basis.get("gate") or "")
    trend_fallback = str(trend_basis.get("fallback") or "")
    selected_current_trend = trend_basis.get("selected_current_trend")
    live_trend_ok = trend_gate == "PASS" and trend_count >= 3 and selected_current_trend is True
    evergreen_fallback_ok = (
        trend_gate == "SCHEDULED_ROTATION_FALLBACK"
        and trend_fallback == "scheduled_category_evergreen_explainer"
        and selected_current_trend is False
        and (package.get("trend_verification") or {}).get("gate") == trend_gate
    )
    category = str(package.get("editorial_category", "")).strip()
    if not 850 <= long_words <= 1000 or len(str(package.get("script", ""))) < 4500 or hook_score < 7 or not (live_trend_ok or evergreen_fallback_ok) or not category:
        raise SystemExit("Long-form quality gate failed: require 850-1000 words, 4500+ script characters, hook score >=7, category, and either 3+ real category-related YouTube videos OR the explicit scheduled-category evergreen fallback. Fallback must not be described as a current trend.")
    if short.get("content_format") != "SHORT" or not 100 <= int(short.get("script_word_count", 0) or 0) <= 135 or short.get("qa") != "passed":
        raise SystemExit("Short-form QA failed; no content records or renderer runs were created.")
    next_slot_date = datetime.now(NY).date() + timedelta(days=1)
    rotation_date = str((package.get("category_rotation") or {}).get("date_us_eastern", "")).strip()
    if rotation_date:
        try:
            requested_slot_date = date.fromisoformat(rotation_date)
        except ValueError:
            raise SystemExit("Research target date is invalid; dispatch blocked to prevent a wrong-day category.") from None
        if requested_slot_date < next_slot_date:
            raise SystemExit("Research target date must be at least the next US Eastern calendar day; dispatch blocked.")
        starts = requested_slot_date.isoformat()
    else:
        starts = next_slot_date.isoformat()
    common_sources = sources[:12]
    editorial_category = str(package.get("editorial_category", "")).strip()
    if not editorial_category:
        raise SystemExit("Editorial category missing from research package; no production dispatch is allowed.")
    long_req = make_request(package, common_sources, "LONG_VIDEO", starts, category=editorial_category, require_pair=True)
    long_result = request_json(WORKER_URL + "/content-create", long_req, GITHUB_TOKEN)
    if DRY_RUN:
        short_req = make_request(short, common_sources, "SHORT", starts, category=str(long_result.get("category", "")))
        short_result = request_json(WORKER_URL + "/content-create", short_req, GITHUB_TOKEN)
        result = {
            "status": "DRY_RUN_VALIDATED_NO_D1_WRITES_NO_RENDER_NO_UPLOAD",
            "source_run_id": SOURCE_RUN_ID,
            "editorial_category": editorial_category,
            "category_rotation": package.get("category_rotation", {}),
            "long": long_result,
            "short": short_result,
            "planned_publish_times": {"long_local": "12:00 America/New_York", "short_local": "17:00 America/New_York"},
        }
        Path("work/auto_handoff_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": result["status"], "long_validated": long_result.get("validated"), "short_validated": short_result.get("validated")}))
        return

    effective_date = str(long_result.get("slot_date") or starts)
    category = str(long_result.get("category") or editorial_category)
    short_req = make_request(short, common_sources, "SHORT", effective_date, category=category)
    short_result = request_json(WORKER_URL + "/content-create", short_req, GITHUB_TOKEN)
    if str(short_result.get("slot_date") or effective_date) != effective_date:
        raise SystemExit("Long/Short slot dates diverged; renderer dispatch blocked to avoid mismatched daily pair.")
    results = {"source_run_id": SOURCE_RUN_ID, "slot_date": effective_date, "category": category or editorial_category,
               "editorial_category": editorial_category, "category_rotation": package.get("category_rotation", {}),
               "long": long_result, "short": short_result}
    if long_result.get("already_published_or_scheduled") and short_result.get("already_published_or_scheduled"):
        results["status"] = "ALREADY_SCHEDULED_NO_DUPLICATE_DISPATCH"
        Path("work/auto_handoff_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": results["status"], "long_id": long_result.get("content_id"), "short_id": short_result.get("content_id")}))
        return

    long_status = str(long_result.get("status", "")).upper()
    short_status = str(short_result.get("status", "")).upper()
    if long_result.get("already_published_or_scheduled"):
        results["dispatch_long"] = False
    elif long_status in {"SCRIPTED", "WAITING_FOR_VOICE", "WAITING_FOR_AUDIO"} and long_result.get("content_id"):
        results["dispatch_long"] = True
        results["long_dispatch"] = dispatch_payload(package, long_result["content_id"], "LONG_VIDEO", utc_at(effective_date, 12))
    else:
        results["dispatch_long"] = False
        results["long_block_reason"] = "Existing long-form content has an active/unknown pipeline status; duplicate render blocked."
    if short_result.get("already_published_or_scheduled"):
        results["dispatch_short"] = False
    elif short_status in {"SCRIPTED", "WAITING_FOR_VOICE", "WAITING_FOR_AUDIO"} and short_result.get("content_id"):
        results["dispatch_short"] = True
        results["short_dispatch"] = dispatch_payload(short, short_result["content_id"], "SHORT", utc_at(effective_date, 17))
    else:
        results["dispatch_short"] = False
        results["short_block_reason"] = "Existing Short has an active/unknown pipeline status; duplicate render blocked."
    if not results.get("dispatch_long") and not results.get("dispatch_short"):
        raise SystemExit("Both renderer dispatches were blocked; inspect existing D1/YouTube statuses. No new upload started.")
    Path("work/auto_handoff_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status":"D1_CONTENTS_VERIFIED", "slot_date":effective_date, "category":category,
                      "long_id":long_result.get("content_id"), "short_id":short_result.get("content_id"),
                      "dispatch_long":results.get("dispatch_long"), "dispatch_short":results.get("dispatch_short"),
                      "long_publish_at":(results.get("long_dispatch") or {}).get("inputs",{}).get("publish_at"),
                      "short_publish_at":(results.get("short_dispatch") or {}).get("inputs",{}).get("publish_at")}))

if __name__ == "__main__":
    main()
