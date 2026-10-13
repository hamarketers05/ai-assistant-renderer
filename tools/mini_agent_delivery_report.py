#!/usr/bin/env python3
"""Compile downstream mini-agent evidence after render/upload/schedule/learning gates."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from mini_agents import agent_execution_report

WORK = Path("work")


def read_json(name: str) -> dict:
    path = WORK / name
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write(name: str, value: dict) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / name).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    category = os.getenv("EDITORIAL_CATEGORY", "").strip()
    content_id = os.getenv("CONTENT_ID", "").strip()
    already_uploaded = os.getenv("ALREADY_UPLOADED", "false").strip().lower() == "true"
    existing_video_id = os.getenv("EXISTING_VIDEO_ID", "").strip()

    verified = read_json("youtube_post_upload_review.json")
    upload = read_json("upload_result.json")
    review = read_json("video_review_report.json")
    manifest = read_json("editing_tool_manifest.json")
    learning_path = Path("learning/latest_video_review.json")
    learning_record = {}
    if learning_path.is_file():
        try:
            loaded = json.loads(learning_path.read_text(encoding="utf-8"))
            learning_record = loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            learning_record = {}
    learning_exists = bool(learning_record)
    current_review_persisted = bool(review) and learning_record == review and os.getenv("LEARNING_PERSISTENCE_STEP_OUTCOME", "").strip().lower() == "success"

    video_id = str(verified.get("video_id") or upload.get("id") or existing_video_id)
    url = str(verified.get("url") or ("https://www.youtube.com/watch?v=" + video_id if video_id else ""))
    privacy = str(verified.get("privacy_status") or "")
    publish_at = str(verified.get("publish_at") or "")
    publish_ok = bool(verified.get("verified") is True and video_id and url and privacy == "private" and publish_at)

    if publish_ok:
        publish_status = "completed"
        publish_tools = ["YouTube Data API v3", "Cloudflare Worker upload-result"]
        publish_note = "Read-after-write verification confirmed the uploaded video ID, private status, and scheduled publishAt."
    elif already_uploaded and existing_video_id:
        publish_status = "already_completed"
        publish_tools = ["Existing YouTube/D1 state check"]
        publish_note = "Duplicate upload was deliberately skipped because existing state reported an uploaded video."
    else:
        publish_status = "blocked_or_unverified"
        publish_tools = []
        publish_note = "No complete verified read-after-write record was found; do not claim the video was successfully scheduled."

    publisher = agent_execution_report("publish", [{
        "agent_id": "publisher_agent", "status": publish_status,
        "actual_tools_used": publish_tools,
        "evidence_files": ["work/youtube_post_upload_review.json", "work/upload_result.json", "work/upload_record_response.json"],
        "details": {"content_id": content_id, "video_id": video_id or None, "verified": publish_ok,
                    "privacy_status": privacy or None, "publish_at": publish_at or None, "note": publish_note}
    }], {"content_id": content_id, "editorial_category": category, "policy_version": "1.0.0"})
    write("mini_agent_publish_execution_report.json", publisher)

    if review.get("review_status") == "completed" and review.get("decision") in {"PASS", "IMPROVE"}:
        learning_status = "completed" if current_review_persisted else "review_completed_feedback_persistence_unverified"
        learning_tools = ["Groq video/vision review"]
        if current_review_persisted:
            learning_tools.append("learning/latest_video_review.json")
            learning_note = "The current rendered-video QA feedback exactly matches the persisted learning record."
        else:
            learning_note = "A review exists, but the persisted learning record does not exactly match this run's review."
    else:
        learning_status = "blocked_or_unverified"
        learning_tools = []
        learning_note = "No completed final video-review artifact was available; no learning success is claimed."
    learning_agent = agent_execution_report("learn", [{
        "agent_id": "learning_agent", "status": learning_status,
        "actual_tools_used": learning_tools,
        "evidence_files": ["work/video_review_report.json", "work/video_review_metrics.json", "learning/latest_video_review.json"],
        "details": {"decision": review.get("decision"), "review_status": review.get("review_status"),
                    "feedback_file_exists": learning_exists, "current_feedback_exactly_persisted": current_review_persisted, "note": learning_note}
    }], {"content_id": content_id, "editorial_category": category, "policy_version": "1.0.0"})
    write("mini_agent_learning_execution_report.json", learning_agent)

    render_report = read_json("mini_agent_render_execution_report.json")
    summary = {
        "schema_version": "1.0.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "content_id": content_id,
        "editorial_category": category,
        "render_agent_report_present": bool(render_report),
        "render_manifest_status": manifest.get("status", "missing"),
        "publisher_agent_status": publish_status,
        "learning_agent_status": learning_status,
        "youtube_video_id": video_id or None,
        "youtube_url": url or None,
        "scheduled_publish_at": publish_at or None,
        "safe_claim_policy": "Only reports backed by current workflow artifacts are marked completed. Missing evidence remains unverified.",
    }
    write("mini_agent_delivery_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
