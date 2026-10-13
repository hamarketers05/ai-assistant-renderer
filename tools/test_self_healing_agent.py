#!/usr/bin/env python3
"""Pure local tests for strict self-healing patch parsing."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import self_healing_agent as agent


def main():
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
