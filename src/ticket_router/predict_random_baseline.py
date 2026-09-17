"""Step 03 -- a random-baseline predictor, to prove the evaluation harness
works end-to-end before any real model touches it. Makes NO model calls: it
samples each of queue/priority/type independently from that field's marginal
distribution in the training split, using a seeded RNG.

latency_ms, input_tokens, output_tokens, and cost_usd are all written as 0 --
not measured or estimated, but structurally zero, because this predictor
never calls a model at all.

Step-18: sampling is keyed off each row's stable `id`, not its position in
`target`. An earlier version drew one shared `rng.choice(..., size=n)` array
and assigned draw `i` to `target["id"][i]` -- SEED=42 made the DRAW SEQUENCE
itself deterministic, but the file's final id->label mapping still depended
on `test.parquet`'s row order at the moment the script ran. That is not
reproducibility: seeding pins the sequence of numbers a generator produces,
not what they get assigned to. Re-running the old version after
`test.parquet`'s row order changed (step-04's shuffle fix, applied AFTER this
predictor's original run) silently produced a different id->label mapping
with an unchanged seed -- see PROGRESS.md's step-17 and step-18 entries. Now
each row's prediction is drawn from an RNG seeded by a stable hash of
(SEED, ticket_id, field) -- the SAME ticket gets the SAME prediction no
matter what order the split's rows happen to be in, for the same reason the
other predictors (id-keyed by construction: TF-IDF predicts from a row's own
text, the API/adapter predictors send one ticket at a time) already were.

Run from the repo root:
    .venv\\Scripts\\python.exe src\\ticket_router\\predict_random_baseline.py   (Windows)
    .venv/bin/python src/ticket_router/predict_random_baseline.py                (POSIX)
"""

from __future__ import annotations

import hashlib
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


def sample_for_row(ticket_id: str, field: str, values: np.ndarray, probs: np.ndarray, seed: int):
    """Deterministic, ORDER-INDEPENDENT sample for one (ticket, field): the RNG
    is seeded from a stable hash of (seed, ticket_id, field), never from the
    row's position in a file. The same ticket id always gets the same
    prediction, regardless of what order the split's rows are written in --
    see the module docstring for why that matters here specifically."""
    digest = hashlib.sha256(f"{seed}:{ticket_id}:{field}".encode("utf-8")).digest()
    row_seed = int.from_bytes(digest[:8], "big")
    row_rng = np.random.default_rng(row_seed)
    return row_rng.choice(values, p=probs)


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
    print(f"Sampling predictions for {len(target)} {PREDICT_SPLIT} rows (seed={SEED}, "
          "id-keyed -- see sample_for_row)")

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
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for ticket_id in target["id"]:
            row = {
                "id": ticket_id,
                **{
                    field: sample_for_row(ticket_id, field, field_values[field], field_probs[field], SEED)
                    for field in TARGET_FIELDS
                },
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
