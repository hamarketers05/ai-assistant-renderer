#!/usr/bin/env python3
"""Pure local tests for strict self-healing patch parsing."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import self_healing_agent as agent


def main():
    assert agent.is_retired_diagnostic_workflow({"name": "One-time Main Worker Groq Proxy Probe"}) is True
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
