#!/usr/bin/env python3
"""Pure local tests for strict self-healing patch parsing."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import self_healing_agent as agent


def main():
    assert agent.extract_target_date("TARGET_DATE: 2026-10-15") == "2026-10-15"
    assert agent.extract_target_date("TARGET_DATE: ") == ""
    assert agent.extract_target_date("--target-date 2026-10-15") == "2026-10-15"
    assert agent.extract_target_date("TARGET_DATE: ") == ""

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
