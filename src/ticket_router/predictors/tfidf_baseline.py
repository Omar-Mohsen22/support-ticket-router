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

Run from the repo root:
    .venv\\Scripts\\python.exe src\\ticket_router\\predictors\\tfidf_baseline.py   (Windows)
    .venv/bin/python src/ticket_router/predictors/tfidf_baseline.py                 (POSIX)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier

REPO_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RESULTS_DIR = REPO_ROOT / "results"

TRAIN_SPLIT = "train"
PREDICT_SPLIT = "test"
TARGET_FIELDS = ["queue", "priority", "type"]
SEED = 42
OUTPUT_PATH = RESULTS_DIR / "tfidf-baseline.predictions.jsonl"

# A single sensible configuration -- not tuned, not swept, not cross-validated.
TFIDF_CONFIG = dict(max_features=20_000, ngram_range=(1, 2), stop_words="english", sublinear_tf=True)
LOGREG_CONFIG = dict(max_iter=1000, random_state=SEED)  # max_iter raised only so lbfgs converges


def main() -> None:
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

    print("Fitting TF-IDF vectorizer on train text only ...")
    vectorizer = TfidfVectorizer(**TFIDF_CONFIG)
    X_train = vectorizer.fit_transform(train["text"])
    X_test = vectorizer.transform(test["text"])
    print(f"  vocabulary size: {len(vectorizer.vocabulary_)}")

    predictions = {}
    total_predict_s = 0.0
    for field in TARGET_FIELDS:
        print(f"\nTraining one-vs-rest logistic regression for `{field}` "
              f"({train[field].nunique()} classes) ...")
        clf = OneVsRestClassifier(LogisticRegression(**LOGREG_CONFIG))

        t0 = time.perf_counter()
        clf.fit(X_train, train[field])
        fit_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        preds = clf.predict(X_test)
        predict_s = time.perf_counter() - t0
        total_predict_s += predict_s

        predictions[field] = preds
        train_acc = clf.score(X_train, train[field])
        print(f"  fit: {fit_s:.2f}s  |  predict: {predict_s:.3f}s  |  train accuracy: {train_acc:.4f}")

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


if __name__ == "__main__":
    main()
