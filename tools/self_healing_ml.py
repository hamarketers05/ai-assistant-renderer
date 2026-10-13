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
MODEL_VERSION = "incident-nb-v2"
MIN_CONFIDENCE = 0.10
MIN_MARGIN = 0.005
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
    "CODE_SYNTAX_OR_IMPORT_FAILURE": "Inspect the exact traceback; make the smallest allowlisted code patch, run compile and focused tests, and revert if validation fails. Never expose secrets or bypass QA.",
    "TEST_REGRESSION_FAILURE": "Identify the first failing assertion, preserve the regression test, patch narrowly, then rerun focused and CI validation. Never weaken a release gate just to make tests green.",
    "WORKFLOW_CONFIG_INVALID": "Validate workflow YAML and actionlint output; change only the known workflow contract, review permissions and triggers, then require CI before merge.",
    "DEPENDENCY_INSTALL_FAILURE": "Check the pinned dependency, Python version and transient package-index errors; retry transient failures once, do not upgrade pins blindly, and verify license and compatibility.",
    "RENDER_TIMEOUT": "Stop at the bounded timeout, preserve checkpoints and logs, inspect slow stages, and retry only once when safe. Never treat a partial MP4 as complete.",
    "VIDEO_INTEGRITY_FAILURE": "Keep upload blocked; validate size, ffprobe metadata, frame decode, duration, resolution, frame rate and playback before considering a rerender.",
    "CAPTION_SYNC_FAILURE": "Regenerate captions from verified narration timestamps, validate monotonic cues and audio duration, and keep release blocked until sync checks pass.",
    "ASSET_LICENSE_FAILURE": "Quarantine the asset and replace it only with media whose exact license and attribution are verified; never lower the licensing gate.",
    "DISK_SPACE_EXHAUSTED": "Inspect disk usage and remove only known disposable temporary files after confirming source artifacts and checkpoints are safe; do not delete production state.",
    "SUPABASE_STORAGE_FAILURE": "Use bounded retry only for transient errors; preserve the local artifact and verify remote object key, size and checksum before marking storage complete.",
    "YOUTUBE_QUOTA_EXHAUSTED": "Stop YouTube API calls until quota reset; never retry-loop, publish without readback, or enable billing without explicit approval.",
    "YOUTUBE_UPLOAD_FAILURE": "Check resumable session and remote video readback before retry; reuse the same upload identity where supported and never create a second video when status is uncertain.",
    "DUPLICATE_UPLOAD_RISK": "Block new upload until the existing content hash, idempotency key, upload job and remote video ID have been checked. Do not assume an earlier timeout means no upload.",
    "SCHEDULE_READBACK_FAILURE": "Keep video private; verify video ID, privacyStatus and publishAt from YouTube readback. Do not claim scheduling succeeded when any field is missing or mismatched.",
    "CONTENT_DEDUP_STATE_FAILURE": "Stop handoff until persisted job state, content hash and recent-title checks are verified; do not process or upload a duplicate item while storage state is uncertain.",
    "SOURCE_CLAIM_MISMATCH": "Remove or rewrite the unsupported claim against retained credible source evidence; retain citations and keep factual QA blocking until each claim is supported.",
    "JSON_SCHEMA_PARSE_FAILURE": "Capture a sanitized parse/schema error, issue at most one bounded structured repair, validate again, and reject malformed or incomplete output without weakening the schema.",
    "QUEUE_JOB_FAILURE": "Inspect attempt count, idempotency and dead-letter evidence; use bounded retry for transient faults and preserve the message when its state is uncertain.",
    "WORKER_DEPLOYMENT_FAILURE": "Do not shift traffic; read back the active version and bindings, keep the known-good rollback target, compare configuration and restore only through a verified reversible deployment.",
    "MODEL_OUTPUT_INVALID": "Reject empty, truncated or malformed output; allow at most one bounded schema-constrained retry using existing evidence, then fail closed and preserve diagnostics."
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
    known_feature_count: int
    known_feature_ratio: float
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
        features = _tokens(text)
        vocabulary = set(self.vocabulary)
        known = [token for token in features if token in vocabulary]
        known_feature_count = len(set(known))
        known_feature_ratio = len(known) / max(len(features), 1)
        scored = self.decision_scores(text)
        best_label, best_score = scored[0]
        second_label, second_score = scored[1]
        max_score = best_score
        exp_scores = [math.exp(max(-700.0, value - max_score)) for _, value in scored]
        total = sum(exp_scores) or 1.0
        posterior = exp_scores[0] / total
        second_posterior = exp_scores[1] / total
        margin = posterior - second_posterior
        # Softmax posterior shrinks as taxonomy size grows; require actual lexical
        # evidence plus a nontrivial best-vs-runner-up margin instead of using a
        # fixed 0.55 threshold designed for only ten classes. A one-token match
        # such as "unknown" is insufficient to classify an out-of-domain message.
        if (known_feature_count < 2 or known_feature_ratio < 0.08
                or posterior < MIN_CONFIDENCE or margin < MIN_MARGIN):
            shown_label = "LOW_CONFIDENCE_UNCLASSIFIED"
        else:
            shown_label = best_label
        return Prediction(
            label=shown_label, confidence=round(posterior, 6),
            margin=round(margin, 6), second_label=second_label,
            known_feature_count=known_feature_count,
            known_feature_ratio=round(known_feature_ratio, 6),
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


def validate_splits(training: list[dict[str, str]], holdout: list[dict[str, str]]) -> dict:
    """Fail training if classes are uncovered or exact/normalized rows cross the split."""
    train_counts = Counter(row["label"] for row in training)
    eval_counts = Counter(row["label"] for row in holdout)
    train_labels, eval_labels = set(train_counts), set(eval_counts)
    known_labels = set(SAFE_ADVISORIES)
    if train_labels != known_labels:
        raise ValueError(
            f"Training labels must exactly match safe advisory taxonomy; "
            f"missing={sorted(known_labels - train_labels)}, extra={sorted(train_labels - known_labels)}"
        )
    if eval_labels != train_labels:
        raise ValueError(
            f"Holdout must cover every train class; missing={sorted(train_labels - eval_labels)}, "
            f"extra={sorted(eval_labels - train_labels)}"
        )
    undertrained = {label: count for label, count in train_counts.items() if count < 5}
    under_evaluated = {label: count for label, count in eval_counts.items() if count < 2}
    if undertrained or under_evaluated:
        raise ValueError(f"Insufficient class coverage: training={undertrained}, holdout={under_evaluated}")
    def normalise(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    train_texts = {normalise(row["text"]) for row in training}
    overlaps = [row["text"] for row in holdout if normalise(row["text"]) in train_texts]
    if overlaps:
        raise ValueError(f"Training/holdout data leakage: {len(overlaps)} duplicated examples")
    return {"training_class_counts": dict(sorted(train_counts.items())),
            "holdout_class_counts": dict(sorted(eval_counts.items())),
            "class_count": len(train_labels), "exact_normalised_overlap_count": 0}


def evaluate(model: IncidentNaiveBayes, rows: list[dict[str, str]]) -> dict:
    results = []
    correct = 0
    expected_labels = sorted({row["label"] for row in rows})
    per_class_counts: Counter[str] = Counter()
    per_class_correct: Counter[str] = Counter()
    unclassified_count = 0
    for row in rows:
        prediction = model.predict(row["text"])
        hit = prediction.label == row["label"]
        correct += int(hit)
        per_class_counts[row["label"]] += 1
        per_class_correct[row["label"]] += int(hit)
        unclassified_count += int(prediction.label == "LOW_CONFIDENCE_UNCLASSIFIED")
        results.append({
            "expected": row["label"], "predicted": prediction.label,
            "correct": hit, "confidence": prediction.confidence,
            "margin": prediction.margin, "second_label": prediction.second_label,
            "known_feature_count": prediction.known_feature_count,
            "known_feature_ratio": prediction.known_feature_ratio,
            "was_classified": prediction.label != "LOW_CONFIDENCE_UNCLASSIFIED",
        })
    per_class = {
        label: {
            "support": per_class_counts[label],
            "correct_count": per_class_correct[label],
            "accuracy": round(per_class_correct[label] / per_class_counts[label], 4)
        }
        for label in expected_labels
    }
    accuracy = correct / len(rows) if rows else 0.0
    macro_accuracy = (
        sum(per_class[label]["accuracy"] for label in expected_labels) / len(expected_labels)
        if expected_labels else 0.0
    )
    classified_results = [row for row in results if row["was_classified"]]
    classified_count = len(classified_results)
    selective_correct_count = sum(int(row["correct"]) for row in classified_results)
    classification_coverage = classified_count / len(rows) if rows else 0.0
    selective_accuracy = (
        selective_correct_count / classified_count if classified_count else 0.0
    )
    return {
        "model_version": MODEL_VERSION,
        "evaluation_count": len(rows),
        "correct_count": correct,
        "accuracy": round(accuracy, 4),
        "macro_accuracy": round(macro_accuracy, 4),
        "unclassified_count": unclassified_count,
        "classified_count": classified_count,
        "classification_coverage": round(classification_coverage, 4),
        "selective_accuracy": round(selective_accuracy, 4),
        "class_count": len(expected_labels),
        "per_class": per_class,
        "threshold_accuracy_target": 0.80,
        "threshold_macro_accuracy_target": 0.75,
        "threshold_classification_coverage_target": 0.80,
        "passed": bool(rows) and accuracy >= 0.80 and macro_accuracy >= 0.75 and classification_coverage >= 0.80,
        "results": results,
    }
def train_and_save(train_path: Path = DEFAULT_TRAIN, eval_path: Path = DEFAULT_EVAL,
                   model_path: Path = DEFAULT_MODEL, evaluation_path: Path = DEFAULT_EVAL_REPORT):
    training = read_jsonl(train_path)
    holdout = read_jsonl(eval_path)
    split_diagnostics = validate_splits(training, holdout)
    model = IncidentNaiveBayes().fit(training)
    metrics = evaluate(model, holdout)
    metrics["split_diagnostics"] = split_diagnostics
    model_path.parent.mkdir(parents=True, exist_ok=True)
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.to_dict()
    payload["training_data_file"] = train_path.as_posix()
    payload["holdout_data_file"] = eval_path.as_posix()
    payload["holdout_accuracy"] = metrics["accuracy"]
    payload["holdout_count"] = metrics["evaluation_count"]
    payload["holdout_passed"] = metrics["passed"]
    payload["holdout_macro_accuracy"] = metrics["macro_accuracy"]
    payload["training_class_count"] = len(model.labels)
    payload["evaluation_split_has_leakage"] = False
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
        "CODE_SYNTAX_OR_IMPORT_FAILURE": "Python SyntaxError unexpected indent py_compile traceback",
        "TEST_REGRESSION_FAILURE": "pytest regression assertion failed expected actual CI smoke test",
        "WORKFLOW_CONFIG_INVALID": "GitHub Actions actionlint workflow YAML invalid expression",
        "DEPENDENCY_INSTALL_FAILURE": "pip installation failed incompatible pinned wheel ModuleNotFoundError",
        "RENDER_TIMEOUT": "FFmpeg renderer exceeded timeout encoding deadline",
        "VIDEO_INTEGRITY_FAILURE": "ffprobe moov atom not found zero frames corrupt MP4",
        "CAPTION_SYNC_FAILURE": "SRT subtitle timestamps do not align narration waveform",
        "ASSET_LICENSE_FAILURE": "stock asset commercial license unverified attribution missing",
        "DISK_SPACE_EXHAUSTED": "ENOSPC no space left on device runner disk full",
        "SUPABASE_STORAGE_FAILURE": "Supabase upload checksum mismatch object readback timeout",
        "YOUTUBE_QUOTA_EXHAUSTED": "YouTube Data API quotaExceeded daily project allocation",
        "YOUTUBE_UPLOAD_FAILURE": "YouTube videos.insert resumable upload failed no video id",
        "DUPLICATE_UPLOAD_RISK": "duplicate YouTube upload same content hash idempotency key",
        "SCHEDULE_READBACK_FAILURE": "YouTube publishAt privacyStatus schedule readback mismatch",
        "CONTENT_DEDUP_STATE_FAILURE": "D1 content hash dedup persisted job state missing duplicate",
        "SOURCE_CLAIM_MISMATCH": "source citation contradicts exact factual claim unsupported",
        "JSON_SCHEMA_PARSE_FAILURE": "JSONDecodeError malformed response missing required schema field",
        "QUEUE_JOB_FAILURE": "Cloudflare Queue dead letter message retries exhausted",
        "WORKER_DEPLOYMENT_FAILURE": "Cloudflare Worker active version bindings deployment verification failed",
        "MODEL_OUTPUT_INVALID": "LLM empty truncated malformed structured JSON output",
    }.items():
        predicted = model.predict(cue)
        assert predicted.label == label, {"expected": label, "prediction": predicted.__dict__}
    return {
        "training_count": model.training_count, "labels": model.labels,
        "holdout_accuracy": metrics["accuracy"],
        "holdout_count": metrics["evaluation_count"], "passed": metrics["passed"],
        "macro_accuracy": metrics["macro_accuracy"], "class_count": len(model.labels),
        "classification_coverage": metrics["classification_coverage"],
        "selective_accuracy": metrics["selective_accuracy"],
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
