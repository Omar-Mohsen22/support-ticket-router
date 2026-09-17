"""Step 03 -- a random-baseline predictor, to prove the evaluation harness
works end-to-end before any real model touches it. Makes NO model calls: it
samples each of queue/priority/type independently from that field's marginal
distribution in the training split, using a seeded RNG.

latency_ms, input_tokens, output_tokens, and cost_usd are all written as 0 --
not measured or estimated, but structurally zero, because this predictor
never calls a model at all.

Run from the repo root:
    .venv\\Scripts\\python.exe src\\ticket_router\\predict_random_baseline.py   (Windows)
    .venv/bin/python src/ticket_router/predict_random_baseline.py                (POSIX)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Make `ticket_router` importable when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ticket_router.run_meta import no_training_cost, write_run_meta

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RESULTS_DIR = REPO_ROOT / "results"
RUN_NAME = "random-baseline"  # must match the --run-name evaluate.py is called with

TRAIN_SPLIT = "train"
PREDICT_SPLIT = "test"
TARGET_FIELDS = ["queue", "priority", "type"]
SEED = 42
OUTPUT_PATH = RESULTS_DIR / "random-baseline.predictions.jsonl"


def main() -> None:
    train_path = PROCESSED_DIR / f"{TRAIN_SPLIT}.parquet"
    predict_path = PROCESSED_DIR / f"{PREDICT_SPLIT}.parquet"
    for p in (train_path, predict_path):
        if not p.exists():
            print(f"STOP: {p} not found. Run src/ticket_router/make_dataset.py first.")
            raise SystemExit(1)

    train = pd.read_parquet(train_path)
    target = pd.read_parquet(predict_path)
    print(f"Fitting marginal label distributions on {len(train)} {TRAIN_SPLIT} rows")
    print(f"Sampling predictions for {len(target)} {PREDICT_SPLIT} rows (seed={SEED})")

    rng = np.random.default_rng(SEED)

    # Independent marginal distribution per field (not a joint distribution --
    # this baseline deliberately ignores any correlation between fields).
    field_values = {}
    field_probs = {}
    for field in TARGET_FIELDS:
        counts = train[field].value_counts()
        field_values[field] = counts.index.to_numpy()
        field_probs[field] = (counts / counts.sum()).to_numpy()
        print(f"  {field}: {len(field_values[field])} classes, "
              f"most common = {counts.index[0]!r} ({field_probs[field][0]:.1%})")

    n = len(target)
    sampled = {
        field: rng.choice(field_values[field], size=n, p=field_probs[field])
        for field in TARGET_FIELDS
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for i, ticket_id in enumerate(target["id"]):
            row = {
                "id": ticket_id,
                "queue": sampled["queue"][i],
                "priority": sampled["priority"][i],
                "type": sampled["type"][i],
                "latency_ms": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\nWrote {n} predictions to {OUTPUT_PATH}")

    meta_path = write_run_meta(
        RUN_NAME, cost_basis="cpu-local", hardware="CPU",
        training_cost=no_training_cost(
            "No training step -- samples from each field's marginal distribution in the "
            "train split; no model is fit or served."
        ),
    )
    print(f"Wrote {meta_path}")


if __name__ == "__main__":
    main()
