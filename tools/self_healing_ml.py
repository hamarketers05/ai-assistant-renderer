#!/usr/bin/env python3
"""Small supervised incident classifier; advisory only, never authorizes repairs.

The controller trains a Multinomial Naive Bayes model from a version-controlled,
reviewed incident corpus on each run. Predictions are diagnostics only: all retries,
patching, credential handling and release gates remain controlled by deterministic
allowlists and existing QA rules. The corpus is intentionally explicit and is not
self-labelled from the model's own predictions.
"""
from __future__ import annotations
import argparse
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEFAULT_TRAIN = BASE / "self_healing_incidents_train.jsonl"
DEFAULT_EVAL = BASE / "self_healing_incidents_eval.jsonl"
DEFAULT_MODEL = Path("work/self_healing_ml_model.json")
DEFAULT_EVAL_REPORT = Path("work/self_healing_ml_evaluation.json")
MODEL_VERSION = "incident-nb-v1"
MIN_CONFIDENCE = 0.55
MIN_MARGIN = 0.08
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "by", "did",
    "do", "does", "for", "from", "had", "has", "have", "in", "into",
    "is", "it", "its", "of", "on", "or", "our", "out", "over", "please",
    "the", "their", "then", "there", "this", "to", "too", "up", "was",
    "we", "were", "when", "with", "without", "yet",
}

SAFE_ADVISORIES = {
    "GROQ_RATE_LIMITED": "Honor the provider reset hint; at most one timeout-aware retry, then retain pending. Do not infer missing credentials or loop the fallback.",
    "WORKERS_AI_QUOTA_EXHAUSTED": "Wait for the free quota reset. Do not enable billing or repeatedly call the exhausted fallback.",
    "D1_QUOTA_EXHAUSTED": "Stop D1 probes until the quota reset; do not claim state persistence or dedup was verified.",
    "SCRIPT_LENGTH_GATE": "Keep the word-count gate closed; request the single bounded source-locked rewrite, then recheck length.",
    "SCRIPT_AUDIT_BLOCK": "Inspect the audit artifact; do not normalize explicit rejection, weak scores, malformed audit or unsupported claims.",
    "TREND_EVIDENCE_INSUFFICIENT": "Run only bounded, deduplicated free-source discovery; if evidence remains sparse, clearly label the scheduled evergreen fallback.",
    "TAVILY_QUOTA_EXHAUSTED": "Respect the free-tier cooldown and use approved public-source fallbacks; never upgrade or retry-loop.",
    "TRANSIENT_NETWORK_FAILURE": "Use bounded retry/backoff only for allowlisted jobs; preserve job state and prevent duplicate work.",
    "AUDIO_QA_FAILURE": "Keep render/upload blocked until real audio exists, decodes, has valid duration, and passes objective quality/sync checks.",
    "CREDENTIAL_CONFIG_MISSING": "Stop and report the missing configuration; retries cannot create secrets. Never expose tokens or switch to paid providers.",
}


def _tokens(text: str) -> list[str]:
    raw = re.findall(r"[a-z0-9_]+", str(text or "").lower())
    words = [w for w in raw if w not in STOPWORDS and len(w) > 1]
    unigrams = words[:]
    bigrams = [f"{a}__{b}" for a, b in zip(words, words[1:])]
    return unigrams + bigrams


def read_jsonl(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSONL {path}:{number}: {exc}") from None
        label, text = row.get("label"), row.get("text")
        if not isinstance(label, str) or not label.strip() or not isinstance(text, str) or not text.strip():
            raise ValueError(f"Invalid labeled incident at {path}:{number}")
        rows.append({"label": label.strip(), "text": text.strip()})
    if not rows:
        raise ValueError(f"No training/evaluation rows in {path}")
    return rows


@dataclass
class Prediction:
    label: str
    confidence: float
    margin: float
    second_label: str
    scores: list[dict[str, float | str]]

    @property
    def accepted(self) -> bool:
        return self.label != "LOW_CONFIDENCE_UNCLASSIFIED" and self.confidence >= MIN_CONFIDENCE and self.margin >= MIN_MARGIN


class IncidentNaiveBayes:
    """Multinomial Naive Bayes trained on token and adjacent-token features."""
    def __init__(self, alpha: float = 1.0):
        if alpha <= 0:
            raise ValueError("alpha must be positive")
        self.alpha = float(alpha)
        self.labels: list[str] = []
        self.vocabulary: list[str] = []
        self.log_priors: dict[str, float] = {}
        self.log_likelihoods: dict[str, dict[str, float]] = {}
        self.training_count = 0
        self.class_counts: dict[str, int] = {}

    def fit(self, rows: list[dict[str, str]]) -> "IncidentNaiveBayes":
        if not rows:
            raise ValueError("training set cannot be empty")
        self.labels = sorted({row["label"] for row in rows})
        if len(self.labels) < 2:
            raise ValueError("at least two incident classes are required")
        doc_counts: Counter[str] = Counter()
        term_counts: dict[str, Counter[str]] = defaultdict(Counter)
        total_terms: Counter[str] = Counter()
        vocabulary: set[str] = set()
        for row in rows:
            label = row["label"]
            features = Counter(_tokens(row["text"]))
            doc_counts[label] += 1
            term_counts[label].update(features)
            total_terms[label] += sum(features.values())
            vocabulary.update(features)
        self.vocabulary = sorted(vocabulary)
        vsize = len(self.vocabulary)
        self.training_count = len(rows)
        self.class_counts = dict(doc_counts)
        self.log_priors = {label: math.log(doc_counts[label] / len(rows)) for label in self.labels}
        self.log_likelihoods = {}
        for label in self.labels:
            denom = total_terms[label] + self.alpha * vsize
            self.log_likelihoods[label] = {
                token: math.log((term_counts[label][token] + self.alpha) / denom)
                for token in self.vocabulary
            }
        return self

    def decision_scores(self, text: str) -> list[tuple[str, float]]:
        if not self.labels or not self.vocabulary:
            raise RuntimeError("model is not trained")
        known = Counter(token for token in _tokens(text) if token in self.log_likelihoods[self.labels[0]])
        scores = []
        for label in self.labels:
            score = self.log_priors[label] + sum(
                count * self.log_likelihoods[label][token] for token, count in known.items()
            )
            scores.append((label, score))
        return sorted(scores, key=lambda item: item[1], reverse=True)

    def predict(self, text: str) -> Prediction:
        scored = self.decision_scores(text)
        best_label, best_score = scored[0]
        second_label, second_score = scored[1]
        max_score = best_score
        exp_scores = [math.exp(max(-700.0, value - max_score)) for _, value in scored]
        total = sum(exp_scores) or 1.0
        posterior = exp_scores[0] / total
        second_posterior = exp_scores[1] / total
        margin = posterior - second_posterior
        if not _tokens(text) or posterior < MIN_CONFIDENCE or margin < MIN_MARGIN:
            shown_label = "LOW_CONFIDENCE_UNCLASSIFIED"
        else:
            shown_label = best_label
        return Prediction(
            label=shown_label, confidence=round(posterior, 6),
            margin=round(margin, 6), second_label=second_label,
            scores=[{"label": label, "relative_posterior": round(exp_scores[i] / total, 6)}
                    for i, (label, _) in enumerate(scored[:3])],
        )

    def to_dict(self) -> dict:
        return {
            "model_version": MODEL_VERSION,
            "algorithm": "multinomial_naive_bayes_word_and_bigram_features",
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "alpha": self.alpha,
            "training_count": self.training_count,
            "class_counts": self.class_counts,
            "labels": self.labels,
            "vocabulary": self.vocabulary,
            "log_priors": self.log_priors,
            "log_likelihoods": self.log_likelihoods,
            "prediction_confidence_is_calibrated": False,
            "safety_policy": "advisory_only_no_model_authorized_retry_patch_upload_or_release",
        }


def evaluate(model: IncidentNaiveBayes, rows: list[dict[str, str]]) -> dict:
    results = []
    correct = 0
    for row in rows:
        prediction = model.predict(row["text"])
        hit = prediction.label == row["label"]
        correct += int(hit)
        results.append({
            "expected": row["label"], "predicted": prediction.label,
            "correct": hit, "confidence": prediction.confidence,
            "second_label": prediction.second_label,
        })
    return {
        "model_version": MODEL_VERSION,
        "evaluation_count": len(rows),
        "correct_count": correct,
        "accuracy": round(correct / len(rows), 4) if rows else 0.0,
        "threshold_accuracy_target": 0.80,
        "passed": bool(rows) and correct / len(rows) >= 0.80,
        "results": results,
    }


def train_and_save(train_path: Path = DEFAULT_TRAIN, eval_path: Path = DEFAULT_EVAL,
                   model_path: Path = DEFAULT_MODEL, evaluation_path: Path = DEFAULT_EVAL_REPORT):
    training = read_jsonl(train_path)
    holdout = read_jsonl(eval_path)
    model = IncidentNaiveBayes().fit(training)
    metrics = evaluate(model, holdout)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.to_dict()
    payload["training_data_file"] = train_path.as_posix()
    payload["holdout_data_file"] = eval_path.as_posix()
    payload["holdout_accuracy"] = metrics["accuracy"]
    payload["holdout_count"] = metrics["evaluation_count"]
    payload["holdout_passed"] = metrics["passed"]
    model_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    evaluation_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return model, metrics


def run_self_test() -> dict:
    model, metrics = train_and_save()
    assert len(model.labels) == len(SAFE_ADVISORIES), (len(model.labels), len(SAFE_ADVISORIES))
    assert model.training_count >= 40, model.training_count
    assert metrics["evaluation_count"] >= 15, metrics
    assert metrics["passed"], metrics
    unknown = model.predict("lorem ipsum unknown random observation")
    assert unknown.label == "LOW_CONFIDENCE_UNCLASSIFIED", unknown
    for label, cue in {
        "GROQ_RATE_LIMITED": "Groq HTTP 429 too many requests Retry-After",
        "WORKERS_AI_QUOTA_EXHAUSTED": "Workers AI error 4006 daily free neuron allocation exhausted",
        "D1_QUOTA_EXHAUSTED": "D1 daily free-tier row read quota exhausted",
        "SCRIPT_LENGTH_GATE": "LONG_VIDEO 1048 spoken words required 850-1000",
        "SCRIPT_AUDIT_BLOCK": "natural_script_audit rejected unsupported_current_claims",
        "TREND_EVIDENCE_INSUFFICIENT": "youtube category trend gate distinct_video_count 2",
        "TAVILY_QUOTA_EXHAUSTED": "Tavily HTTP 432 quota exhausted 24 hour cooldown",
        "TRANSIENT_NETWORK_FAILURE": "HTTP 503 service unavailable connection reset",
        "AUDIO_QA_FAILURE": "Kokoro WAV missing narration audio QA failure duration",
        "CREDENTIAL_CONFIG_MISSING": "GROQ_API_KEY missing unauthorized 401 secret",
    }.items():
        predicted = model.predict(cue)
        assert predicted.label == label, {"expected": label, "prediction": predicted.__dict__}
    return {
        "training_count": model.training_count, "labels": model.labels,
        "holdout_accuracy": metrics["accuracy"],
        "holdout_count": metrics["evaluation_count"], "passed": metrics["passed"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", action="store_true", help="train and serialize the model")
    parser.add_argument("--self-test", action="store_true", help="train, evaluate, and run regression fixtures")
    parser.add_argument("--output", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--evaluation-output", type=Path, default=DEFAULT_EVAL_REPORT)
    args = parser.parse_args()
    model, metrics = train_and_save(model_path=args.output, evaluation_path=args.evaluation_output)
    summary = {
        "training_count": model.training_count, "labels": model.labels,
        "holdout_accuracy": metrics["accuracy"], "holdout_count": metrics["evaluation_count"],
        "evaluation_passed": metrics["passed"], "model_file": str(args.output),
    }
    if args.self_test:
        summary["self_test"] = run_self_test()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if metrics["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
