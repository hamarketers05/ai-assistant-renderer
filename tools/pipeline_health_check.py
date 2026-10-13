#!/usr/bin/env python3
"""Validate the pipeline knowledge catalog against the checked-out repository.

This is a read-only static integrity check. It never probes providers, mutates
production state, dispatches jobs, or treats configuration as runtime evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "tools" / "pipeline_catalog.json"
REQUIRED_TOP_LEVEL = {
    "schema_version", "pipeline_id", "evidence_boundary", "runtime_monitoring",
    "decision_rules", "stages", "workflows", "tools", "incident_routes",
    "protected_operations",
}
REQUIRED_PROTECTED_TERMS = (
    "credentials", "billing", "YouTube upload", "QA",
)


def validate_catalog(catalog: Any, root: Path = ROOT) -> list[str]:
    """Return all structural, reference, and safety-contract violations."""
    errors: list[str] = []
    if not isinstance(catalog, dict):
        return ["catalog root must be a JSON object"]

    missing = sorted(REQUIRED_TOP_LEVEL - set(catalog))
    if missing:
        errors.append("missing top-level fields: " + ", ".join(missing))

    for key in ("stages", "workflows", "tools", "incident_routes", "decision_rules", "protected_operations"):
        if not isinstance(catalog.get(key), list) or not catalog.get(key):
            errors.append(f"{key} must be a non-empty list")

    stages = catalog.get("stages", [])
    if isinstance(stages, list):
        stage_ids: list[str] = []
        for index, stage in enumerate(stages):
            if not isinstance(stage, dict):
                errors.append(f"stages[{index}] must be an object")
                continue
            sid = stage.get("id")
            if not isinstance(sid, str) or not sid.strip():
                errors.append(f"stages[{index}] has no valid id")
            else:
                stage_ids.append(sid)
            if not isinstance(stage.get("name"), str) or not stage["name"].strip():
                errors.append(f"stage {sid or index} has no name")
            if not isinstance(stage.get("quality_gates"), list) or not stage["quality_gates"]:
                errors.append(f"stage {sid or index} must declare quality_gates")
            if stage.get("step_status_is_not_runtime_proof") is not True:
                errors.append(f"stage {sid or index} must explicitly separate static configuration from runtime proof")
            for field in ("tool_paths", "workflow_paths"):
                paths = stage.get(field, [])
                if not isinstance(paths, list):
                    errors.append(f"stage {sid or index} {field} must be a list")
                    continue
                for rel in paths:
                    _check_repo_path(rel, f"stage {sid or index} {field}", root, errors)
        if len(stage_ids) != len(set(stage_ids)):
            errors.append("stage ids must be unique")

    for collection_name in ("workflows", "tools"):
        items = catalog.get(collection_name, [])
        if not isinstance(items, list):
            continue
        seen: set[str] = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"{collection_name}[{index}] must be an object")
                continue
            rel = item.get("path")
            if not isinstance(rel, str) or not rel:
                errors.append(f"{collection_name}[{index}] has no path")
                continue
            if rel in seen:
                errors.append(f"duplicate {collection_name} path: {rel}")
            seen.add(rel)
            _check_repo_path(rel, collection_name, root, errors)

    for index, route in enumerate(catalog.get("incident_routes", [])):
        if not isinstance(route, dict):
            errors.append(f"incident_routes[{index}] must be an object")
            continue
        # The catalog intentionally uses human-readable labels and permitted_recovery;
        # accept those canonical fields, while retaining compatibility with older
        # code/safe_recovery records. A route must always name a recovery instruction.
        route_id = route.get("code") or route.get("label")
        recovery = route.get("safe_recovery") or route.get("permitted_recovery")
        if not isinstance(route_id, str) or not route_id.strip() or not isinstance(recovery, str) or not recovery.strip():
            errors.append(f"incident_routes[{index}] must define code/label and safe_recovery/permitted_recovery")

    protected = catalog.get("protected_operations", [])
    if isinstance(protected, list):
        protected_text = " ".join(str(item) for item in protected).lower()
        for term in REQUIRED_PROTECTED_TERMS:
            if term.lower() not in protected_text:
                errors.append(f"protected_operations is missing required safety concept: {term}")

    monitoring = catalog.get("runtime_monitoring")
    if not isinstance(monitoring, dict):
        errors.append("runtime_monitoring must be an object")
    else:
        interval = monitoring.get("expected_schedule_minutes")
        freshness = monitoring.get("scheduled_probe_freshness_limit_minutes")
        if not isinstance(interval, int) or interval <= 0:
            errors.append("runtime_monitoring.expected_schedule_minutes must be a positive integer")
        if not isinstance(freshness, int) or freshness < 2 * interval:
            errors.append("probe freshness limit must be at least two expected schedule intervals")
        caveat = str(monitoring.get("availability_caveat", "")).lower()
        if "not" not in caveat or "24/7" not in caveat:
            errors.append("availability caveat must explicitly reject a 24/7 uptime guarantee")

    boundary = str(catalog.get("evidence_boundary", "")).lower()
    if "does not prove" not in boundary and "not proof" not in boundary:
        errors.append("evidence_boundary must state that static catalog entries do not prove runtime success")

    return errors


def _check_repo_path(value: Any, context: str, root: Path, errors: list[str]) -> None:
    if not isinstance(value, str) or not value or value.startswith("/") or ".." in Path(value).parts:
        errors.append(f"{context} contains an unsafe repository-relative path: {value!r}")
        return
    target = root / value
    if not target.is_file():
        errors.append(f"{context} references missing file: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    try:
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"PIPELINE CATALOG INVALID: {exc}")
        return 1

    errors = validate_catalog(catalog, ROOT)
    if errors:
        print(f"PIPELINE CATALOG INVALID: {len(errors)} issue(s)")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "PIPELINE CATALOG VALID: "
        f"{len(catalog['stages'])} stages, {len(catalog['workflows'])} workflows, "
        f"{len(catalog['tools'])} tools, {len(catalog['incident_routes'])} incident routes. "
        "Static integrity only; live pipeline health remains unverified."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
