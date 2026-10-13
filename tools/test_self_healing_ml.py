#!/usr/bin/env python3
"""Regression tests for supervised incident classification and conservative output."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import self_healing_ml as ml


def main():
    result = ml.run_self_test()
    assert result["training_count"] >= 40
    assert result["holdout_count"] >= 15
    assert result["holdout_accuracy"] >= 0.80
    assert result["passed"] is True
    print("SELF_HEALING_ML_TESTS_PASS: " + str(result))


if __name__ == "__main__":
    main()
