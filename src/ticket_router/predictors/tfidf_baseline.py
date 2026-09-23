"""Step 04b -- classical ML baseline: TF-IDF + one-vs-rest logistic regression.

Trained on the TRAIN split only (13,070 rows), predicts all three fields
(queue, priority, type) on the TEST split. Costs nothing, runs in seconds --
built to answer one specific question before step 05: when a target field's
zero-shot macro-F1 is low, is that because the signal genuinely isn't
recoverable from the ticket text, or because the LLM prompt is failing to
extract signal that IS there? A model trained directly on 13,070 labelled
examples is the cleanest way to tell those two apart.

A single sensible TF-IDF + logistic regression configuration is used
throughout. This is deliberately NOT tuned -- a competitive score is not the
point; a same-order-of-magnitude signal check is.

Step-26: every run also saves the fitted vectorizer + classifiers to
models/tfidf/ (joblib) with a meta.json, for the serving API.

Step-27: models/tfidf/ is COMMITTED -- it is the exact model behind
results/tfidf-baseline.predictions.jsonl (all 1,633 test rows reproduce).
Running this script overwrites it. A refit on another platform is NOT
bit-identical: a Linux refit on the same data changed predictions on some test
rows (see PROGRESS.md step-27), so do not commit a refit casually. Use
--artifact-only to fit and save WITHOUT rewriting results/ (a full run
rewrites the predictions file and run_meta with fresh timings).

Run from the repo root:
    .venv\\Scripts\\python.exe src\\ticket_router\\predictors\\tfidf_baseline.py   (Windows)
    .venv/bin/python src/ticket_router/predictors/tfidf_baseline.py                 (POSIX)
    .venv\\Scripts\\python.exe src\\ticket_router\\predictors\\tfidf_baseline.py --artifact-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier

# Make `ticket_router` importable when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ticket_router.evaluate import compute_gold_hash
from ticket_router.run_meta import no_training_cost, write_run_meta

REPO_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RESULTS_DIR = REPO_ROOT / "results"
MODEL_DIR = REPO_ROOT / "models" / "tfidf"
MODEL_PATH = MODEL_DIR / "model.joblib"
MODEL_META_PATH = MODEL_DIR / "meta.json"

TRAIN_SPLIT = "train"
PREDICT_SPLIT = "test"
TARGET_FIELDS = ["queue", "priority", "type"]
SEED = 42
OUTPUT_PATH = RESULTS_DIR / "tfidf-baseline.predictions.jsonl"
RUN_NAME = "tfidf-baseline"  # must match the --run-name evaluate.py is called with

# A single sensible configuration -- not tuned, not swept, not cross-validated.
TFIDF_CONFIG = dict(max_features=20_000, ngram_range=(1, 2), stop_words="english", sublinear_tf=True)
LOGREG_CONFIG = dict(max_iter=1000, random_state=SEED)  # max_iter raised only so lbfgs converges


def fit_models(train: pd.DataFrame) -> tuple[TfidfVectorizer, dict, float]:
    """Fit the vectorizer on train text only, then one classifier per field.
    Returns (vectorizer, classifiers_by_field, total_fit_seconds)."""
    print("Fitting TF-IDF vectorizer on train text only ...")
    vectorizer = TfidfVectorizer(**TFIDF_CONFIG)
    X_train = vectorizer.fit_transform(train["text"])
    print(f"  vocabulary size: {len(vectorizer.vocabulary_)}")

    classifiers = {}
    total_fit_s = 0.0
    for field in TARGET_FIELDS:
        print(f"\nTraining one-vs-rest logistic regression for `{field}` "
              f"({train[field].nunique()} classes) ...")
        clf = OneVsRestClassifier(LogisticRegression(**LOGREG_CONFIG))
        t0 = time.perf_counter()
        clf.fit(X_train, train[field])
        fit_s = time.perf_counter() - t0
        total_fit_s += fit_s
        classifiers[field] = clf
        print(f"  fit: {fit_s:.2f}s  |  train accuracy: {clf.score(X_train, train[field]):.4f}")
    return vectorizer, classifiers, total_fit_s


def save_artifact(vectorizer: TfidfVectorizer, classifiers: dict, train: pd.DataFrame) -> None:
    """Write the fitted models to models/tfidf/ for the serving API. Only load
    this file from a trusted source: joblib files are pickles."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"vectorizer": vectorizer, "classifiers": classifiers}, MODEL_PATH)
    meta = {
        "model": RUN_NAME,
        "model_sha256": hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),
        "sklearn_version": sklearn.__version__,
        "joblib_version": joblib.__version__,
        "train_rows": len(train),
        "train_id_sequence_sha256": compute_gold_hash(train["id"].tolist()),
        "tfidf_config": TFIDF_CONFIG,
        "logreg_config": LOGREG_CONFIG,
        "fields": TARGET_FIELDS,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    MODEL_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nSaved model artifact to {MODEL_PATH} ({MODEL_PATH.stat().st_size:,} bytes) "
          f"and {MODEL_META_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-only", action="store_true",
                        help="Fit and save models/tfidf/ only; do not predict or touch results/.")
    args = parser.parse_args()

    train_path = PROCESSED_DIR / f"{TRAIN_SPLIT}.parquet"
    test_path = PROCESSED_DIR / f"{PREDICT_SPLIT}.parquet"
    for p in (train_path, test_path):
        if not p.exists():
            print(f"STOP: {p} not found. Run src/ticket_router/make_dataset.py first.")
            raise SystemExit(1)

    train = pd.read_parquet(train_path)
    test = pd.read_parquet(test_path)
    print(f"Train: {len(train)} rows  |  Test: {len(test)} rows")
    print(f"TF-IDF config: {TFIDF_CONFIG}")
    print(f"LogisticRegression config: {LOGREG_CONFIG} (wrapped in OneVsRestClassifier)\n")

    vectorizer, classifiers, total_fit_s = fit_models(train)
    save_artifact(vectorizer, classifiers, train)
    if args.artifact_only:
        return

    X_test = vectorizer.transform(test["text"])
    predictions = {}
    total_predict_s = 0.0
    for field in TARGET_FIELDS:
        t0 = time.perf_counter()
        predictions[field] = classifiers[field].predict(X_test)
        total_predict_s += time.perf_counter() - t0

    # sklearn predicts the whole test set in one batch, not one row at a time
    # like an API call -- latency_ms below is the total predict time across
    # all three fields' classifiers, averaged evenly over the rows, not
    # individually measured per row. Reported for schema consistency with the
    # other predictors, not as a claim about single-request latency.
    per_row_latency_ms = (total_predict_s / len(test)) * 1000
    print(f"\nTotal predict time (all 3 fields, whole test set): {total_predict_s * 1000:.1f} ms "
          f"-> {per_row_latency_ms:.4f} ms/row, batch-averaged")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for i, ticket_id in enumerate(test["id"]):
            row = {
                "id": ticket_id,
                "queue": predictions["queue"][i],
                "priority": predictions["priority"][i],
                "type": predictions["type"][i],
                "latency_ms": per_row_latency_ms,
                "input_tokens": 0,
                "output_tokens": 0,
                # Exactly $0 -- no API calls, no ambiguity, unlike api_predictor.py's
                # null (unknown) cost_usd for a provider that doesn't report it.
                "cost_usd": 0.0,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\nWrote {len(test)} predictions to {OUTPUT_PATH}")

    meta_path = write_run_meta(
        RUN_NAME, cost_basis="cpu-local", hardware="CPU",
        training_cost=no_training_cost(
            f"Trains in {total_fit_s:.2f}s total (all 3 classifiers) on a local CPU -- "
            "not comparable to the fine-tuned adapter's GPU training time."
        ),
    )
    print(f"Wrote {meta_path}")


if __name__ == "__main__":
    main()
