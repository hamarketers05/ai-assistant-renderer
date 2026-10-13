#!/usr/bin/env python3
"""Isolated non-production self-healing repair canary.

This tiny arithmetic defect is deliberately injected for one end-to-end test.
It has no imports from production rendering code and performs no external actions.
"""
import sys

def answer():
    # Deliberately wrong for the isolated repair test; expected result is 42.
    return 42

def self_test():
    actual = answer()
    expected = 42
    if actual != expected:
        raise AssertionError(
            f"{__file__}: canary expected {expected}, got {actual}; repair answer() only"
        )
    print("SELF_HEALING_E2E_CANARY_PASS: deterministic defect repaired and assertion passed")

if __name__ == "__main__":
    if "--self-test" not in sys.argv:
        raise SystemExit("Run with --self-test.")
    self_test()
