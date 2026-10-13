#!/usr/bin/env python3
"""Pure local tests for strict self-healing patch parsing."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import self_healing_agent as agent


def main():
    assert agent.is_expected_research_quality_gate_block(
        {"name": "Verify Cloudflare Free-Source Research"},
        "SAFE BLOCK: sources were retrieved, but no cross-checked claim passed; verified_claims=[]"
    ) is True
    assert agent.is_expected_research_quality_gate_block(
        {"name": "AI Tech Lab Daily Research and Script"},
        "SAFE BLOCK: sources were retrieved, but no cross-checked claim passed; verified_claims=[]"
    ) is False
    assert agent.is_retired_diagnostic_workflow({"name": "One-time Main Worker Groq Proxy Probe"}) is True
    assert agent.is_retired_diagnostic_workflow({"name": "Temporary Cloudflare Oct 15 Research Smoke Test"}) is True
    assert agent.is_retired_diagnostic_workflow({"name": "AI Assistant Renderer"}) is False
    assert agent.extract_target_date("TARGET_DATE: 2026-10-15") == "2026-10-15"
    assert agent.extract_target_date("TARGET_DATE: ") == ""
    assert agent.extract_target_date("--target-date 2026-10-15") == "2026-10-15"
    assert agent.extract_target_date("TARGET_DATE: ") == ""

    assert agent.select_repair_target(
        {"name": "AI Assistant Renderer"},
        "VISUAL NOVELTY GATE BLOCKED: candidate_assets=0; minimum_new_licensed_clips_required=4; tools/asset_reuse_guard.py"
    ) == "tools/fetch_free_video.py"
    assert agent.select_repair_target(
        {"name": "AI Tech Lab Daily Research and Script"},
        "Authenticated Cloudflare AI fallback returned HTTP 502; Groq primary was unavailable."
    ) == "tools/ai_text_client.py"
    assert agent.select_repair_target(
        {"name": "AI Tech Lab Automatic Daily Production Handoff"},
        "Short failed quality gates: title=True, script_words=47, description_chars=2263."
    ) == "tools/make_daily_short.py"
    assert agent.select_repair_target(
        {"name": "AI Assistant Renderer"},
        "Unknown failure mentioning tools/fetch_free_video.py and tools/asset_reuse_guard.py"
    ) is None

    # Regression tests for recurring production failures: classify safely, do not
    # fabricate credentials, bypass QA, or try paid providers.
    midas_issue = agent.classify_known_infrastructure_failure(
        {"name": "Validate MiDaS SBS Pipeline"},
        "MiDaS activation report: KeyError: 'Authorization'"
    )
    assert midas_issue and midas_issue["code"] == "PYTORCH_HUB_ANONYMOUS_GITHUB_API_LIMIT"
    assert "Never print the token" in midas_issue["safe_recovery"]

    tier_issue = agent.classify_known_infrastructure_failure(
        {"name": "AI Assistant Renderer"},
        "Vecteezy API plan was not positively identified as Free; Skipping Vecteezy downloads to prevent unexpected charges."
    )
    assert tier_issue and tier_issue["code"] == "VECTEEZY_FREE_TIER_UNVERIFIED"
    assert "paid endpoints" in tier_issue["safe_recovery"]

    flux_issue = agent.classify_known_infrastructure_failure(
        {"name": "AI Assistant Renderer"},
        "FLUX generation stopped safely: Image service HTTP 429; generated_count=0"
    )
    assert flux_issue and flux_issue["code"] == "FREE_IMAGE_ENDPOINT_RATE_LIMIT"
    assert "paid image services" in flux_issue["safe_recovery"]

    # Regression: optional Groq being absent is not a credential failure when its configured
    # Cloudflare fallback returned a transient 502; unrelated "Missing..." text in bundled job
    # logs must not suppress the agent's bounded retry of the failed research run.
    fallback_502_log = (
        "GROQ_API_KEY missing; authenticated Cloudflare Workers AI fallback is enabled. "
        "Authenticated Cloudflare AI fallback returned HTTP 502; Groq primary was unavailable. "
        "Missing existing WORKER_AUTH_TOKEN repository secret."
    )
    assert agent.classify_configuration_failure(fallback_502_log) is None
    assert agent.is_transient(fallback_502_log) is True

    quota_issue = agent.classify_known_infrastructure_failure(
        {"name": "AI Tech Lab Daily Research and Script"},
        "WORKERS_AI_FREE_ALLOCATION_EXHAUSTED: Cloudflare Workers AI daily free neuron allocation is exhausted."
    )
    assert quota_issue and quota_issue["code"] == "WORKERS_AI_FREE_ALLOCATION_EXHAUSTED"
    assert "never enable billing" in quota_issue["safe_recovery"]
    rate_issue = agent.classify_known_infrastructure_failure({"name": "AI Tech Lab Daily Research and Script"}, "GROQ_RATE_LIMITED: Main Worker Groq retry did not recover.")
    assert rate_issue and rate_issue["code"] == "GROQ_RATE_LIMITED"

    tavily_issue = agent.classify_known_infrastructure_failure(
        {"name": "AI Tech Lab Daily Research and Script"},
        "TAVILY_QUOTA_COOLDOWN 86400s: HTTP 432 usage limit exceeded."
    )
    assert tavily_issue and tavily_issue["code"] == "TAVILY_FREE_TIER_QUOTA_EXHAUSTED"
    assert "public RSS fallback" in tavily_issue["safe_recovery"]
    assert "Never upgrade" in tavily_issue["safe_recovery"]

    # Research/handoff workflow repair allowlist is narrow and invariant-driven.
    assert ".github/workflows/daily-content-research.yml" in agent.PATCHABLE
    assert ".github/workflows/daily-auto-production.yml" in agent.PATCHABLE
    assert ".github/workflows/manual.yml" not in agent.PATCHABLE
    good_research_workflow = """name: Research
env:
  WORKER_AUTH_TOKEN: ${{ secrets.WORKER_AUTH_TOKEN }}
  WORKER_URL: https://dark-sunset-a2a1.hamarketers05.workers.dev
run: /editorial/trend-script
path: work/daily_content_package.json
path: work/research_evidence.json
artifact: ai-tech-lab-research-
"""
    assert agent.validate_allowlisted_workflow_text(".github/workflows/daily-content-research.yml", good_research_workflow) is True
    assert agent.validate_allowlisted_workflow_text(".github/workflows/daily-content-research.yml", good_research_workflow + "\nTAVILY_API_KEY: secret") is False
    assert agent.validate_allowlisted_workflow_text(".github/workflows/daily-auto-production.yml",
        "workflow_run: workflow_dispatch: daily_content_package.json research_evidence.json content-create manual.yml/dispatches") is True
    assert agent.validate_allowlisted_workflow_text(".github/workflows/daily-auto-production.yml",
        "workflow_run: workflow_dispatch: daily_content_package.json tavily_evidence.json content-create manual.yml/dispatches") is False

    # Cloudflare editorial category rotation: seven-day US Eastern contract,
    # bounded safe diagnosis, and no automatic production Worker mutation.
    valid_rotation = {
        "date_us_eastern": "2026-10-13", "timezone": "America/New_York",
        "category": "AI News & Breakthroughs", "category_index": 0,
        "next_category": "AI Tools & Practical Workflows",
        "rotation_anchor": "2026-10-13", "cycle_length_days": 7,
        "category_brief": "Evidence-backed news and breakthroughs.",
    }
    assert agent.validate_editorial_rotation_payload(valid_rotation, "2026-10-13") is True
    assert agent.validate_editorial_rotation_payload(valid_rotation, "2026-10-14") is False
    assert agent.validate_editorial_rotation_payload({**valid_rotation, "timezone": "UTC"}) is False
    assert agent.validate_editorial_rotation_payload({**valid_rotation, "category_index": 7}) is False
    valid_rotation_self_test = {
        "ok": True, "category_count": 7,
        "checks": {
            "seven_unique_days_and_wraparound": True,
            "duplicate_video_ids_do_not_count": True,
            "three_video_trend_override": True,
            "invalid_date_rejected": True,
        },
    }
    assert agent.validate_editorial_rotation_self_test(valid_rotation_self_test) is True
    assert agent.validate_editorial_rotation_self_test({**valid_rotation_self_test, "checks": {**valid_rotation_self_test["checks"], "duplicate_video_ids_do_not_count": False}}) is False
    rotation_issue = agent.classify_known_infrastructure_failure(
        {"name": "AI Tech Lab Daily Research and Script"},
        "EDITORIAL_ROTATION_SELF_TEST_FAILED: Cloudflare editorial category rotation returned ok=false",
    )
    assert rotation_issue and rotation_issue["code"] == "CLOUDFLARE_EDITORIAL_ROTATION_REGRESSION"
    assert "Do not deploy a Worker patch automatically" in rotation_issue["safe_recovery"]

    d1_quota = agent.classify_known_infrastructure_failure(
        {"name": "AI Tech Lab Daily Research and Script"},
        "Cloudflare D1 free-tier row read limit exhausted; daily read limit exceeded.",
    )
    assert d1_quota and d1_quota["code"] == "D1_FREE_TIER_DAILY_LIMIT_EXHAUSTED"
    assert "Never enable paid billing" in d1_quota["safe_recovery"]
    trend_gate = agent.classify_known_infrastructure_failure(
        {"name": "Verify Cloudflare Trend Script (No Publishing)"},
        "HTTP 422 youtube_category_trend_gate BLOCKED_INSUFFICIENT_CATEGORY_RELATED_YOUTUBE_VIDEOS distinct_video_count=2",
    )
    assert trend_gate and trend_gate["code"] == "YOUTUBE_CATEGORY_TREND_EVIDENCE_INSUFFICIENT"
    assert "two bounded category-targeted" in trend_gate["safe_recovery"].lower()
    assert "scheduled_rotation_fallback" in trend_gate["safe_recovery"].lower()
    assert "never call it a live trend" in trend_gate["safe_recovery"].lower()
    assert "Tavily and paid search are forbidden" in trend_gate["safe_recovery"]
    obsolete_voice_gate = agent.classify_known_infrastructure_failure(
        {"name": "Renderer Static Validation"},
        "Renderer is missing the explicit Kokoro voice-approval release gate.",
    )
    assert obsolete_voice_gate and obsolete_voice_gate["code"] == "OBSOLETE_HUMAN_VOICE_APPROVAL_VALIDATOR"
    assert "Never add a human voice gate" in obsolete_voice_gate["safe_recovery"]

    stereo_default = agent.classify_known_infrastructure_failure(
        {"name": "Renderer Static Validation"},
        "default: SBS; YouTube upload must use the 3D output.",
    )
    assert stereo_default and stereo_default["code"] == "STANDARD_2D_DEFAULT_RENDERER_CONTRACT_DRIFT"
    assert "2D is default" in stereo_default["safe_recovery"]

    short_script = agent.classify_renderer_input_quality_failure(
        {"name": "AI Assistant Renderer"},
        'CONTENT_FORMAT=LONG_VIDEO\n"planned_visual_scenes": 49'
    )
    assert short_script and short_script["code"] == "LONG_FORM_SCRIPT_UNDERLENGTH"
    assert "Do not modify scene_director.py" in short_script["safe_recovery"]

    short_duration = agent.classify_renderer_input_quality_failure(
        {"name": "AI Assistant Renderer"},
        "DURATION GATE BLOCKED: edited LONG_VIDEO narration is 243.85s"
    )
    assert short_duration and short_duration["code"] == "RENDERER_NARRATION_DURATION_GATE"

    malformed_counts = """--- a/tools/self_healing_canary.py
+++ b/tools/self_healing_canary.py
@@ -9,9 +9,9 @@ def answer():
 def answer():
-    return 41
+    return 42
"""
    fixed = agent.normalize_diff_hunk_counts(malformed_counts)
    assert "@@ -9,2 +9,2 @@ def answer():" in fixed, fixed
    assert "--- a/tools/self_healing_canary.py" in fixed
    assert "+++ b/tools/self_healing_canary.py" in fixed

    omitted_prefix = """--- a/tools/self_healing_canary.py
+++ b/tools/self_healing_canary.py
@@ -9,9 +9,9 @@
 def answer():
-    return 41
    return 42
"""
    repaired = agent.normalize_diff_hunk_counts(
        omitted_prefix, source_lines=["def answer():", "    return 41"]
    )
    assert "+    return 42" in repaired, repaired
    assert "@@ -9,2 +9,2 @@" in repaired, repaired

    unchanged = """--- a/tools/sample.py
+++ b/tools/sample.py
@@ -1,2 +1,2 @@
 first
-second
+third
"""
    assert agent.normalize_diff_hunk_counts(unchanged) == unchanged

    invalid = """--- a/tools/sample.py
+++ b/tools/sample.py
@@ -1,2 +1,2 @@
line without diff prefix
"""
    try:
        agent.normalize_diff_hunk_counts(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("Malformed hunk must be rejected, not guessed.")
    print("SELF_HEALING_PATCH_PARSER_TESTS_PASS: hunk counts normalized; malformed patches rejected")


if __name__ == "__main__":
    main()
