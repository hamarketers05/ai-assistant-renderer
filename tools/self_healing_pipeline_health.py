#!/usr/bin/env python3
"""Read-only contract and runtime freshness checks for the AI Tech Lab pipeline.

This module never repairs, deploys, publishes, mutates remote state, or prints secrets.
Static contract checks always run. GitHub Actions freshness checks run when repository
and token environment variables are available; unavailable evidence is reported as
unknown, never silently treated as healthy.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "tools" / "pipeline_catalog.json"
REQUIRED_TOP_LEVEL = {
    "schema_version", "pipeline_id", "evidence_boundary", "runtime_monitoring",
    "decision_rules", "stages", "workflows", "tools", "incident_routes",
    "protected_operations", "tool_role_policy",
}
PROTECTED_TERMS = ("credentials", "billing", "YouTube upload", "rendered-video QA gates")


def _api_json(url: str, token: str):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-tech-lab-readonly-healthcheck",
    })
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.load(response)


def check_static() -> list[dict]:
    findings = []
    def add(code, status, detail):
        findings.append({"check": code, "status": status, "detail": detail})
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [{"check": "catalog-json", "status": "FAIL", "detail": type(exc).__name__}]
    missing = sorted(REQUIRED_TOP_LEVEL - set(catalog))
    add("catalog-schema", "FAIL" if missing else "PASS",
        "Missing keys: " + ", ".join(missing) if missing else "Required catalog keys present")
    if missing:
        return findings
    stages = catalog.get("stages", [])
    workflows = catalog.get("workflows", [])
    tools = catalog.get("tools", [])
    routes = catalog.get("incident_routes", [])
    ids = [s.get("id") for s in stages]
    add("stage-map", "PASS" if stages and len(ids) == len(set(ids)) and all(ids) else "FAIL",
        f"{len(stages)} stages; IDs unique and non-empty")
    for label, entries, key in (("workflow-paths", workflows, "path"), ("tool-paths", tools, "path")):
        absent = [e.get(key, "") for e in entries if not e.get(key) or not (ROOT / e[key]).is_file()]
        add(label, "FAIL" if absent else "PASS",
            "Missing tracked paths: " + ", ".join(absent[:12]) if absent else f"{len(entries)} catalog paths exist")
    route_codes = [r.get("code") or r.get("label") for r in routes if isinstance(r, dict)]
    route_recovery = [r.get("safe_recovery") or r.get("permitted_recovery") for r in routes if isinstance(r, dict)]
    add("incident-routes", "PASS" if routes and len(route_codes) == len(set(route_codes)) and all(isinstance(x, str) and x.strip() for x in route_codes) and len(route_recovery) == len(routes) and all(isinstance(x, str) and x.strip() for x in route_recovery) else "FAIL",
        f"{len(routes)} routes; identifiers unique and recovery guidance present")
    protected = " ".join(str(x) for x in catalog.get("protected_operations", []))
    add("protected-operations", "PASS" if all(t.lower() in protected.lower() for t in PROTECTED_TERMS) else "FAIL",
        "Credential, billing, publishing and QA protections must remain catalogued")
    monitor = catalog.get("runtime_monitoring", {})
    schedule = monitor.get("expected_schedule_minutes")
    freshness = monitor.get("scheduled_probe_freshness_limit_minutes")
    add("monitoring-policy", "PASS" if isinstance(schedule, int) and schedule > 0 and isinstance(freshness, int) and freshness >= schedule else "FAIL",
        f"Expected interval={schedule}; stale threshold={freshness} minutes; schedule is best-effort, not 24/7 guarantee")
    return findings


def check_runtime() -> list[dict]:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")
    if not repo or not token:
        return [{"check": "github-runtime-freshness", "status": "UNKNOWN",
                 "detail": "GITHUB_REPOSITORY/token not provided; no live run status inferred"}]
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        limit = int(catalog["runtime_monitoring"].get("run_history_window_limit", 100))
        limit = min(max(limit, 1), 100)
        data = _api_json(f"https://api.github.com/repos/{repo}/actions/runs?per_page={limit}", token)
        runs = data.get("workflow_runs", [])
        now = time.time()
        results = []
        for name in ("AI Tech Lab Autonomous Self-Healing Agent",
                     "AI Tech Lab Autonomous Self-Healing Watchdog"):
            matched = [r for r in runs if r.get("name") == name]
            latest = max(matched, key=lambda r: r.get("run_number", 0), default=None)
            if latest is None:
                results.append({"check": "latest:" + name, "status": "FAIL",
                                "detail": "No run found in bounded recent run history"})
                continue
            status = latest.get("status")
            conclusion = latest.get("conclusion")
            age_minutes = max(0, int((now - __import__("datetime").datetime.fromisoformat(
                latest["created_at"].replace("Z", "+00:00")).timestamp()) / 60))
            if status != "completed":
                verdict = "WARN"
            elif conclusion == "success":
                verdict = "PASS"
            elif conclusion == "skipped":
                verdict = "WARN"
            else:
                verdict = "FAIL"
            results.append({"check": "latest:" + name, "status": verdict,
                            "detail": f"run_id={latest.get('id')} status={status} conclusion={conclusion} age_minutes={age_minutes} branch={latest.get('head_branch')}"})
        monitor = catalog["runtime_monitoring"]
        limit_age = int(monitor.get("scheduled_probe_freshness_limit_minutes", 45))
        recent = [r for r in runs if r.get("name") == "AI Tech Lab Autonomous Self-Healing Agent"
                  and r.get("event") == "schedule" and r.get("status") == "completed"]
        latest_scheduled = max(recent, key=lambda r: r.get("run_number", 0), default=None)
        if latest_scheduled is None:
            results.append({"check": "scheduled-probe-freshness", "status": "FAIL",
                            "detail": "No completed scheduled controller run in bounded history"})
        else:
            age = max(0, int((now - __import__("datetime").datetime.fromisoformat(
                latest_scheduled["created_at"].replace("Z", "+00:00")).timestamp()) / 60))
            results.append({"check": "scheduled-probe-freshness",
                            "status": "PASS" if age <= limit_age and latest_scheduled.get("conclusion") == "success" else "WARN",
                            "detail": f"latest scheduled run_id={latest_scheduled.get('id')} age_minutes={age} conclusion={latest_scheduled.get('conclusion')} freshness_limit_minutes={limit_age}; cron is best-effort"})
        return results
    except (OSError, ValueError, KeyError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return [{"check": "github-runtime-freshness", "status": "UNKNOWN",
                 "detail": f"Read-only GitHub API check unavailable: {type(exc).__name__}; static checks remain valid"}]


def main() -> int:
    report = {"component": "pipeline-health-contract", "mode": "read-only",
              "findings": check_static() + check_runtime()}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if any(x["status"] == "FAIL" for x in report["findings"]) else 0


if __name__ == "__main__":
    sys.exit(main())
