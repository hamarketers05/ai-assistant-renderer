#!/usr/bin/env python3
"""Offline regression tests for pipeline health checks; no network or credentials."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import self_healing_pipeline_health as health


def main():
    findings = health.check_static()
    failed = [x for x in findings if x["status"] == "FAIL"]
    assert not failed, json.dumps(failed, indent=2)
    assert any(x["check"] == "stage-map" and x["status"] == "PASS" for x in findings)
    assert any(x["check"] == "protected-operations" and x["status"] == "PASS" for x in findings)
    assert any(x["check"] == "monitoring-policy" and x["status"] == "PASS" for x in findings)
    # Missing runtime credentials must be UNKNOWN, not falsely green.
    old_repo = health.os.environ.pop("GITHUB_REPOSITORY", None)
    old_token = health.os.environ.pop("GITHUB_TOKEN", None)
    old_gh = health.os.environ.pop("GH_TOKEN", None)
    try:
        result = health.check_runtime()
        assert result[0]["status"] == "UNKNOWN", result
    finally:
        if old_repo is not None: health.os.environ["GITHUB_REPOSITORY"] = old_repo
        if old_token is not None: health.os.environ["GITHUB_TOKEN"] = old_token
        if old_gh is not None: health.os.environ["GH_TOKEN"] = old_gh
    print(f"PASS: {len(findings)} static catalog/path/safety checks; missing runtime evidence fails closed as UNKNOWN")


if __name__ == "__main__":
    main()
