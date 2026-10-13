#!/usr/bin/env python3
"""Isolated non-production self-healing repair canary.

This isolated assertion protects the self-healing repair/validation/restart path.
It has no imports from production rendering code and performs no external actions.
"""
import sys

def answer():
    # This value must equal expected=42 in self_test().
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
