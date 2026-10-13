#!/usr/bin/env python3
"""Offline regression tests for manifest and scheduled/stage health classification."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline_health_check as health

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def run(path, *, event="schedule", status="completed", conclusion="success", age_minutes=5, run_id=1):
    created = NOW - timedelta(minutes=age_minutes)
    return {
        "id": run_id,
        "path": path,
        "event": event,
        "status": status,
        "conclusion": conclusion,
        "head_branch": "main",
        "created_at": created.isoformat(),
        "html_url": f"https://github.com/hamarketers05/ai-assistant-renderer/actions/runs/{run_id}",
    }


def make_catalog(root: Path):
    (root / ".github/workflows").mkdir(parents=True)
    (root / "tools").mkdir(exist_ok=True)
    for path in ("tools/agent.py", "tools/rescue.py", "tools/tool.py",
                 ".github/workflows/agent.yml", ".github/workflows/watchdog.yml",
                 ".github/workflows/research.yml"):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# fixture\n", encoding="utf-8")
    return {
        "schema_version": "1.0.0",
        "pipeline_id": "test-pipeline",
        "runtime_monitoring": {
            "controller_workflow": ".github/workflows/agent.yml",
            "watchdog_workflow": ".github/workflows/watchdog.yml",
            "expected_schedule_minutes": 15,
            "scheduled_probe_freshness_limit_minutes": 45,
            "health_probe_endpoints": [{
                "id": "worker-test",
                "url": "https://example.workers.dev/health",
            }],
        },
        "stages": [{
            "id": "S00",
            "name": "Test stage",
            "state": "configured_not_verified",
            "tool_paths": ["tools/tool.py"],
            "workflow_paths": [".github/workflows/research.yml"],
            "quality_gates": ["fixture"],
            "step_status_is_not_runtime_proof": True,
        }],
    }


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        catalog = make_catalog(root)
        assert health.validate_catalog(catalog, root) == []
        bad = {**catalog, "stages": [catalog["stages"][0], catalog["stages"][0]]}
        assert any("duplicate stage id" in error for error in health.validate_catalog(bad, root))
        bad_endpoint = make_catalog(root)
        bad_endpoint["runtime_monitoring"]["health_probe_endpoints"][0]["url"] = "http://127.0.0.1:8000/health"
        assert any("HTTPS Cloudflare Workers" in error for error in health.validate_catalog(bad_endpoint, root))

    controller = ".github/workflows/agent.yml"
    fresh = health.audit_schedule(controller, [run(controller)], NOW, 45)
    assert fresh["state"] == "fresh_success" and fresh["healthy"] is True

    stale = health.audit_schedule(controller, [run(controller, age_minutes=90)], NOW, 45)
    assert stale["state"] == "stale" and stale["healthy"] is False

    skipped = health.audit_schedule(controller, [
        run(controller, event="workflow_run", conclusion="skipped", age_minutes=1, run_id=3),
        run(controller, conclusion="skipped", age_minutes=1, run_id=2),
        run(controller, conclusion="success", age_minutes=3, run_id=1),
    ], NOW, 45)
    assert skipped["state"] == "skipped_not_healthy" and skipped["healthy"] is False

    no_schedule = health.audit_schedule(controller, [
        run(controller, event="workflow_run", conclusion="skipped", age_minutes=1),
    ], NOW, 45)
    assert no_schedule["state"] == "not_observed" and no_schedule["healthy"] is False

    active = health.audit_schedule(controller, [
        run(controller, status="in_progress", conclusion=None, age_minutes=8),
    ], NOW, 45)
    assert active["state"] == "in_progress" and active["healthy"] is False

    stuck = health.audit_schedule(controller, [
        run(controller, status="in_progress", conclusion=None, age_minutes=80),
    ], NOW, 45)
    assert stuck["state"] == "stuck_or_overdue" and stuck["healthy"] is False

    stage = {
        "id": "S01", "name": "Research", "state": "configured",
        "workflow_paths": [".github/workflows/research.yml"],
    }
    skipped_stage = health.audit_stage(stage, [
        run(".github/workflows/research.yml", event="workflow_run", conclusion="skipped", run_id=4),
    ], NOW)
    assert skipped_stage["state"] == "not_observed_or_skipped"
    assert skipped_stage["e2e_verified"] is False

    passed_stage = health.audit_stage(stage, [
        run(".github/workflows/research.yml", event="push", conclusion="success", run_id=5),
    ], NOW)
    assert passed_stage["state"] == "workflow_checks_passed_e2e_unverified"
    assert passed_stage["e2e_verified"] is False

    failed_stage = health.audit_stage(stage, [
        run(".github/workflows/research.yml", event="push", conclusion="failure", run_id=6),
    ], NOW)
    assert failed_stage["state"] == "attention_required"

    print("PIPELINE_HEALTH_CHECK_TESTS_PASS: catalog validation; schedule freshness; skipped/stuck runs; fail-closed stage evidence.")


if __name__ == "__main__":
    main()
