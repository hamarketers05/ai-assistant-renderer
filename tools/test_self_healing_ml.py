#!/usr/bin/env python3
"""Regression tests for supervised incident classification and conservative output."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import self_healing_ml as ml


def main():
    result = ml.run_self_test()
    assert result["training_count"] >= 240
    assert result["holdout_count"] >= 80
    assert result["holdout_accuracy"] >= 0.80
    assert result["macro_accuracy"] >= 0.75
    assert result["class_count"] >= 30
    assert result["passed"] is True
    assert 0.0 <= result["macro_precision"] <= 1.0
    assert 0.0 <= result["macro_recall"] <= 1.0
    assert 0.0 <= result["macro_f1"] <= 1.0
    assert len(result["confusion_matrix"]) == result["class_count"]
    knowledge = result["pipeline_knowledge"]
    assert knowledge["catalog_status"] == "PRESENT", knowledge
    assert knowledge["stage_count"] >= 14 and knowledge["tool_count"] >= 40, knowledge
    assert knowledge["runtime_health_proven"] is False
    audio_route = ml.ground_incident_knowledge("AUDIO_QA_FAILURE")
    assert audio_route["route_found"] is True, audio_route
    assert audio_route["must_fail_closed"] is True, audio_route
    assert "S05" in audio_route["stage_ids"], audio_route
    assert audio_route["tools"] and audio_route["workflows"], audio_route
    unknown_route = ml.ground_incident_knowledge("UNKNOWN_INCIDENT")
    assert unknown_route["route_found"] is False, unknown_route
    assert unknown_route["runtime_health_proven"] is False
    print("SELF_HEALING_ML_TESTS_PASS: training, holdout metrics, catalog grounding and fail-closed unknown route verified; " + str({k: result[k] for k in ("training_count", "holdout_count", "holdout_accuracy", "macro_f1", "class_count", "pipeline_knowledge")}))


if __name__ == "__main__":
    main()
