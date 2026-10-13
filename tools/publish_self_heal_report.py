#!/usr/bin/env python3
"""Publish the sanitized self-healing report to Cloudflare D1 through the authenticated handoff Worker.

This telemetry step must never turn a successful recovery run into a failed pipeline.
It only sends the machine-readable report; it cannot execute commands or alter production.
"""
from __future__ import annotations
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://ai-tech-lab-daily-handoff.hamarketers05.workers.dev/self-heal/report"
REPORT_PATH = Path("work/self_healing_report.json")


def main() -> int:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    def note(text: str) -> None:
        print(text)
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write("\n" + text + "\n")

    if not REPORT_PATH.is_file():
        note("Self-healing D1 report: skipped because no report JSON was produced.")
        return 0
    if not token or not run_id.isdigit():
        note("Self-healing D1 report: skipped because run authentication metadata is unavailable.")
        return 0
    try:
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        note("Self-healing D1 report: report JSON could not be read (" + type(exc).__name__ + ").")
        return 0
    payload = json.dumps({"workflow_run_id": run_id, "report": report}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        URL,
        data=payload,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "AI-Tech-Lab-Self-Healing-Agent/1.0",
        },
        method="POST",
    )
    last_error = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=18) as response:
                raw = response.read(4000).decode("utf-8", "replace")
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError("HTTP " + str(response.status))
                result = json.loads(raw) if raw else {}
                if not result.get("ok"):
                    raise RuntimeError("D1 Worker did not confirm report storage")
                note("Self-healing D1 report: stored=" + str(bool(result.get("saved"))) +
                     ", duplicate=" + str(bool(result.get("duplicate"))) +
                     ", status=" + str(result.get("status", report.get("overall", "unknown"))) +
                     ", worker_probes=" + str(result.get("health_probes_passed", "?")) +
                     "/" + str(result.get("health_probes_total", "?")) + ".")
                return 0
        except urllib.error.HTTPError as exc:
            last_error = "HTTP " + str(exc.code)
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                request = urllib.request.Request(URL, data=payload, headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "AI-Tech-Lab-Self-Healing-Agent/1.0",
                }, method="POST")
                continue
            break
        except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError) as exc:
            last_error = type(exc).__name__
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                request = urllib.request.Request(URL, data=payload, headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "AI-Tech-Lab-Self-Healing-Agent/1.0",
                }, method="POST")
                continue
            break
    note("Self-healing D1 report: NOT STORED (" + last_error + "); workflow recovery result remains recorded in GitHub Actions artifact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
