#!/usr/bin/env python3
"""Read-only, evidence-bounded auditor for the AI Tech Lab pipeline.

This tool reports workflow observability and stage evidence. It does not retry jobs,
edit code, deploy Workers, access secrets other than the GitHub Actions token, or publish.
A green workflow is never represented as end-to-end content-pipeline verification.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

API = "https://api.github.com"
CATALOG_PATH = Path("tools/pipeline_catalog.json")
MAX_RUNS = 100
MAX_HEALTH_BODY = 8192


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _safe_repo_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in ("", ".", "..") for part in path.parts)


def validate_catalog(catalog: Any, repo_root: Path) -> list[str]:
    """Return deterministic manifest/schema errors; never probe or mutate production."""
    errors: list[str] = []
    if not isinstance(catalog, dict):
        return ["catalog root must be a JSON object"]
    if catalog.get("schema_version") != "1.0.0":
        errors.append("schema_version must be 1.0.0")
    monitoring = catalog.get("runtime_monitoring")
    if not isinstance(monitoring, dict):
        return errors + ["runtime_monitoring must be an object"]

    for key in ("controller_workflow", "watchdog_workflow"):
        path = monitoring.get(key)
        if not _safe_repo_path(path):
            errors.append(f"runtime_monitoring.{key} is not a safe repository-relative path")
        elif not (repo_root / path).is_file():
            errors.append(f"runtime_monitoring.{key} does not exist: {path}")

    expected = monitoring.get("expected_schedule_minutes")
    freshness = monitoring.get("scheduled_probe_freshness_limit_minutes")
    if not isinstance(expected, int) or expected < 1:
        errors.append("expected_schedule_minutes must be a positive integer")
    if not isinstance(freshness, int) or freshness < 1:
        errors.append("scheduled_probe_freshness_limit_minutes must be a positive integer")
    elif isinstance(expected, int) and freshness < expected:
        errors.append("scheduled freshness limit must be >= expected schedule interval")

    stages = catalog.get("stages")
    if not isinstance(stages, list) or not stages:
        return errors + ["stages must be a non-empty array"]
    seen: set[str] = set()
    required_fields = ("id", "name", "state", "tool_paths", "workflow_paths", "quality_gates")
    for index, stage in enumerate(stages):
        prefix = f"stages[{index}]"
        if not isinstance(stage, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in required_fields:
            if field not in stage:
                errors.append(f"{prefix} missing {field}")
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not stage_id.strip():
            errors.append(f"{prefix}.id must be a non-empty string")
        elif stage_id in seen:
            errors.append(f"duplicate stage id: {stage_id}")
        else:
            seen.add(stage_id)
        if stage.get("step_status_is_not_runtime_proof") is not True:
            errors.append(f"{prefix} must mark workflow/configuration as not being runtime proof")
        for field in ("tool_paths", "workflow_paths"):
            paths = stage.get(field)
            if not isinstance(paths, list) or not paths:
                errors.append(f"{prefix}.{field} must be a non-empty array")
                continue
            for path in paths:
                if not _safe_repo_path(path):
                    errors.append(f"{prefix}.{field} contains unsafe path: {path!r}")
                    continue
                if not (repo_root / path).is_file():
                    errors.append(f"{prefix}.{field} references missing file: {path}")

    endpoints = monitoring.get("health_probe_endpoints")
    if not isinstance(endpoints, list):
        errors.append("runtime_monitoring.health_probe_endpoints must be an array")
    else:
        endpoint_ids: set[str] = set()
        for index, endpoint in enumerate(endpoints):
            prefix = f"runtime_monitoring.health_probe_endpoints[{index}]"
            if not isinstance(endpoint, dict):
                errors.append(f"{prefix} must be an object")
                continue
            endpoint_id, url = endpoint.get("id"), endpoint.get("url")
            if not isinstance(endpoint_id, str) or not endpoint_id.strip() or endpoint_id in endpoint_ids:
                errors.append(f"{prefix}.id must be non-empty and unique")
            else:
                endpoint_ids.add(endpoint_id)
            try:
                parsed = urllib.parse.urlsplit(str(url))
                if (parsed.scheme != "https" or not parsed.hostname or
                    not parsed.hostname.endswith(".workers.dev") or parsed.path != "/health" or
                    parsed.query or parsed.fragment or parsed.username or parsed.password):
                    raise ValueError
            except ValueError:
                errors.append(f"{prefix}.url must be an HTTPS Cloudflare Workers /health URL")
    if not isinstance(catalog.get("pipeline_id"), str) or not catalog.get("pipeline_id"):
        errors.append("pipeline_id must be a non-empty string")
    return errors


def _path_runs(runs: list[dict[str, Any]], path: str) -> list[dict[str, Any]]:
    matches = [
        run for run in runs
        if isinstance(run, dict)
        and run.get("path") == path
        and run.get("head_branch", "main") == "main"
    ]
    return sorted(matches, key=lambda run: parse_time(run.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)


def summarize_run(run: dict[str, Any], now: datetime, stuck_minutes: int = 45) -> dict[str, Any]:
    created = parse_time(run.get("created_at"))
    age_minutes = None if created is None else max(0, int((now - created).total_seconds() // 60))
    status = str(run.get("status") or "unknown")
    conclusion = run.get("conclusion")
    result: dict[str, Any] = {
        "run_id": run.get("id"),
        "event": run.get("event") or "unknown",
        "status": status,
        "conclusion": conclusion,
        "created_at": created.isoformat() if created else None,
        "age_minutes": age_minutes,
        "url": run.get("html_url"),
    }
    if status in ("queued", "requested", "waiting", "pending", "in_progress"):
        if age_minutes is not None and age_minutes > stuck_minutes:
            result["state"] = "stuck_or_overdue"
        else:
            result["state"] = "in_progress" if status == "in_progress" else "queued"
    elif conclusion == "success":
        result["state"] = "workflow_success_only"
    elif conclusion == "skipped":
        result["state"] = "not_executed"
    elif conclusion in ("failure", "timed_out", "cancelled", "action_required", "startup_failure"):
        result["state"] = "failed_or_cancelled"
    else:
        result["state"] = "unknown"
    return result


def audit_schedule(workflow_path: str, runs: list[dict[str, Any]], now: datetime,
                   freshness_minutes: int) -> dict[str, Any]:
    candidates = [
        run for run in _path_runs(runs, workflow_path)
        if run.get("event") == "schedule"
    ]
    if not candidates:
        return {
            "workflow_path": workflow_path,
            "state": "not_observed",
            "healthy": False,
            "reason": f"No scheduled-event run for this workflow exists in the latest {MAX_RUNS}-run API window.",
            "note": "workflow_run events with conclusion=skipped do not count as scheduled monitor execution.",
        }
    latest = candidates[0]
    summary = summarize_run(latest, now, freshness_minutes)
    age = summary.get("age_minutes")
    if summary["state"] == "stuck_or_overdue":
        state = "stuck_or_overdue"
        reason = "The newest scheduled run is still queued/in progress beyond the configured freshness limit."
    elif latest.get("conclusion") == "skipped":
        state = "skipped_not_healthy"
        reason = "The newest scheduled event was skipped; it is not evidence that monitoring executed."
    elif latest.get("conclusion") in ("failure", "timed_out", "cancelled", "action_required", "startup_failure"):
        state = "scheduled_run_failed"
        reason = "The newest scheduled monitor run did not complete successfully."
    elif age is None:
        state = "unknown_timestamp"
        reason = "The newest scheduled run has a missing/invalid created_at timestamp."
    elif age > freshness_minutes:
        state = "stale"
        reason = f"The newest scheduled monitor event is {age} minutes old; freshness limit is {freshness_minutes} minutes."
    elif latest.get("status") in ("queued", "requested", "waiting", "pending", "in_progress"):
        state = "in_progress"
        reason = "A recent scheduled monitor event exists but has not completed."
    elif latest.get("conclusion") == "success":
        state = "fresh_success"
        reason = "The scheduled monitor workflow completed successfully within the freshness window; this is monitoring evidence only."
    else:
        state = "unknown_conclusion"
        reason = "The newest scheduled event has an unrecognized state/conclusion."
    summary.update({
        "workflow_path": workflow_path,
        "state": state,
        "healthy": state == "fresh_success",
        "reason": reason,
    })
    return summary


def audit_stage(stage: dict[str, Any], runs: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    observed = []
    for path in stage.get("workflow_paths", []):
        matching = _path_runs(runs, path)
        if not matching:
            observed.append({"workflow_path": path, "state": "not_observed_in_recent_history"})
        else:
            observed.append({"workflow_path": path, **summarize_run(matching[0], now)})
    states = [item["state"] for item in observed]
    if any(state == "failed_or_cancelled" for state in states):
        stage_state = "attention_required"
    elif any(state == "stuck_or_overdue" for state in states):
        stage_state = "possibly_stuck"
    elif any(state == "in_progress" or state == "queued" for state in states):
        stage_state = "in_progress"
    elif states and all(state == "workflow_success_only" for state in states):
        stage_state = "workflow_checks_passed_e2e_unverified"
    elif any(state == "workflow_success_only" for state in states):
        stage_state = "partial_evidence_or_not_executed"
    else:
        stage_state = "not_observed_or_skipped"
    return {
        "id": stage.get("id"),
        "name": stage.get("name"),
        "catalog_state": stage.get("state"),
        "state": stage_state,
        "workflow_evidence": observed,
        "e2e_verified": False,
        "note": "GitHub workflow result is not proof of provider success, valid audio/media, an audited MP4, or a verified YouTube schedule.",
    }


def probe_health_endpoint(endpoint: dict[str, Any], timeout_seconds: float = 8.0) -> dict[str, Any]:
    """Read only bounded response metadata; never log response bodies or credentials."""
    url = str(endpoint.get("url") or "")
    result = {"id": endpoint.get("id"), "url": url, "state": "unknown", "transport_ok": False}
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "AI-Tech-Lab-Pipeline-Health/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(MAX_HEALTH_BODY)
            result["http_status"] = int(response.status)
            result["transport_ok"] = 200 <= response.status < 300
            if not result["transport_ok"]:
                result["state"] = "http_error"
            else:
                result["state"] = "reachable_http_only"
                try:
                    payload = json.loads(body.decode("utf-8")) if body.strip() else None
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = None
                if isinstance(payload, dict):
                    if payload.get("ok") is False or payload.get("healthy") is False:
                        result["state"] = "application_unhealthy"
                    elif str(payload.get("status", "")).lower() in ("error", "unhealthy", "failed"):
                        result["state"] = "application_unhealthy"
                    elif payload.get("ok") is True or payload.get("healthy") is True or str(payload.get("status", "")).lower() in ("ok", "healthy"):
                        result["state"] = "health_payload_ok"
                result["response_bytes_sampled"] = len(body)
    except urllib.error.HTTPError as exc:
        # Do not read/log an HTTP error body; it may include provider details.
        result.update({"state": "http_error", "http_status": int(exc.code), "error_type": "HTTPError"})
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        result.update({"state": "unreachable", "error_type": type(exc).__name__})
    return result


def fetch_run_history(repo: str, token: str, timeout_seconds: float = 15.0) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
        raise ValueError("GITHUB_REPOSITORY must be owner/name")
    if not token:
        raise ValueError("GITHUB_TOKEN is required for read-only workflow audit")
    url = f"{API}/repos/{repo}/actions/runs?per_page={MAX_RUNS}&branch=main"
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "AI-Tech-Lab-Pipeline-Health/1.0",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub Actions history request returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GitHub Actions history unavailable ({type(exc).__name__})") from None
    runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        raise RuntimeError("GitHub Actions history response has no workflow_runs array")
    return [run for run in runs if isinstance(run, dict)]


def build_report(catalog: dict[str, Any], runs: list[dict[str, Any]], now: datetime,
                 endpoint_results: list[dict[str, Any]], repo: str) -> dict[str, Any]:
    monitoring = catalog["runtime_monitoring"]
    freshness = int(monitoring["scheduled_probe_freshness_limit_minutes"])
    schedule_checks = [
        audit_schedule(monitoring["controller_workflow"], runs, now, freshness),
        audit_schedule(monitoring["watchdog_workflow"], runs, now, freshness),
    ]
    stages = [audit_stage(stage, runs, now) for stage in catalog["stages"]]
    stage_failures = [
        {"stage": stage["id"], "name": stage["name"], "workflow": item["workflow_path"], "url": item.get("url")}
        for stage in stages for item in stage["workflow_evidence"]
        if item["state"] in ("failed_or_cancelled", "stuck_or_overdue")
    ]
    bad_probes = [
        {"id": probe.get("id"), "state": probe.get("state"), "http_status": probe.get("http_status")}
        for probe in endpoint_results
        if probe.get("state") in ("http_error", "application_unhealthy", "unreachable", "unknown")
    ]
    schedule_not_fresh = [item for item in schedule_checks if not item.get("healthy")]
    overall = "attention_required" if (schedule_not_fresh or stage_failures or bad_probes) else "monitor_checks_passed_e2e_unverified"
    return {
        "schema_version": "1.0.0",
        "agent": "AI Tech Lab Pipeline Health Auditor",
        "checked_at": now.astimezone(timezone.utc).isoformat(),
        "repository": repo,
        "monitoring_status": overall,
        "release_readiness": "not_verified",
        "product_pipeline_e2e_verified": False,
        "catalog": {"schema_version": catalog.get("schema_version"), "stage_count": len(stages), "validation": "passed"},
        "scheduled_monitor_checks": schedule_checks,
        "worker_transport_probes": endpoint_results,
        "stages": stages,
        "summary": {
            "stage_failures_or_overdue": len(stage_failures),
            "unobserved_or_skipped_stages": sum(stage["state"] == "not_observed_or_skipped" for stage in stages),
            "scheduled_monitors_not_fresh_success": len(schedule_not_fresh),
            "worker_probes_with_errors": len(bad_probes),
        },
        "evidence_boundary": "This is a bounded read-only diagnostic snapshot. Workflow success and HTTP reachability do not prove that scripts, narration, actual MP4, storage checksum, private upload, future publishAt or YouTube Analytics passed their own gates.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="work/pipeline_health_report.json")
    parser.add_argument("--skip-network", action="store_true", help="Validate only the local catalog; intended for offline checks.")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    catalog_path = root / CATALOG_PATH
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"PIPELINE_CATALOG_INVALID: {type(exc).__name__}", file=sys.stderr)
        return 2
    errors = validate_catalog(catalog, root)
    if errors:
        print("PIPELINE_CATALOG_INVALID: " + "; ".join(errors), file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    repo = os.getenv("GITHUB_REPOSITORY", "unknown/unknown")
    if args.skip_network:
        print(f"PIPELINE_CATALOG_VALID: {len(catalog['stages'])} stages; network checks skipped.")
        return 0

    warnings: list[str] = []
    try:
        runs = fetch_run_history(repo, os.getenv("GITHUB_TOKEN", ""))
    except (ValueError, RuntimeError) as exc:
        runs = []
        warnings.append(str(exc))
    endpoint_results = [probe_health_endpoint(endpoint) for endpoint in catalog["runtime_monitoring"]["health_probe_endpoints"]]
    report = build_report(catalog, runs, now, endpoint_results, repo)
    if warnings:
        report["monitoring_status"] = "attention_required"
        report["api_warnings"] = warnings
    report["catalog"]["validation"] = "passed"
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "PIPELINE_HEALTH_AUDIT: "
        f"status={report['monitoring_status']} stages={report['catalog']['stage_count']} "
        f"schedule_not_fresh={report['summary']['scheduled_monitors_not_fresh_success']} "
        f"stage_failures_or_overdue={report['summary']['stage_failures_or_overdue']} "
        f"probe_errors={report['summary']['worker_probes_with_errors']} report={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
