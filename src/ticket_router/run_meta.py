"""Step 16 -- shared RUN-LEVEL metadata for results/results.json, recorded
alongside (never instead of) evaluate.py's per-row-derived metrics.

Why this exists: the predictions schema (id, queue, priority, type,
latency_ms, input_tokens, output_tokens, cost_usd) is per-row and stays
untouched -- evaluate.py depends on it. But a 0 in cost_usd means three
completely different things depending on which predictor produced it:
  - api_predictor.py: the OpenAI API doesn't return a live $ figure, so 0
    here means "unmeasured -- compute externally from token counts", not
    "free".
  - tfidf_baseline.py / predict_random_baseline.py: runs entirely on a local
    CPU. 0 is real and measured -- genuinely free to run.
  - adapter_predictor.py: a self-hosted model that needs a GPU to serve. 0
    here is NOT "free" -- this harness tracks no $/GPU-hour rate, and the
    model took real GPU-hours to train in the first place.
Without something recording WHICH of these a given run's zero is,
results/comparison.md would report the fine-tuned adapter as "free" in the
exact same sense as TF-IDF, which is false: TF-IDF trains in seconds on a
CPU and serves on a CPU; the adapter took 3h21m of T4 GPU time to train and
needs a GPU to serve.

Decided and built BEFORE the fine-tuned adapter was ever scored (see
PROGRESS.md's step-16 entry) -- specifically so the categories and wording
below could not be picked to flatter, or punish, a result nobody had seen
yet.

Each predictor script calls write_run_meta() once, using whatever it
actually knows about its own hardware at the moment it ran (read at
runtime, e.g. torch.cuda.get_device_name(0) -- never hardcoded). evaluate.py's
save_result() picks the file up automatically by run-name convention and
folds it into that run's results.json entry under "run_meta". report.py
reads it back out to render footnotes.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = REPO_ROOT / "results"

# The three cost bases this project's predictors actually use. Kept to exactly these three,
# named plainly enough that a reader doesn't need this file open to understand a table
# footnote using them.
COST_BASES = ("api-per-token", "cpu-local", "gpu-local")

COST_BASIS_DESCRIPTIONS = {
    "api-per-token": (
        "a hosted API call. The provider doesn't return a live $ figure per request, so a "
        "cost_usd of 0 here means UNMEASURED -- compute a real figure externally from the "
        "recorded input/output token counts -- not that the call was free."
    ),
    "cpu-local": (
        "runs entirely on a local CPU. A cost_usd of 0 here is real and measured -- "
        "genuinely free to run, no ambiguity."
    ),
    "gpu-local": (
        "a self-hosted model that requires a GPU to serve. A cost_usd of 0 here is NOT "
        "\"free\" -- this harness tracks no $/GPU-hour serving rate. See that run's "
        "training_cost for what training it actually cost."
    ),
}


def run_meta_path(run_name: str) -> Path:
    return RESULTS_DIR / f"{run_name}.run_meta.json"


def no_training_cost(note: str = "No training step for this run.") -> dict:
    """The training_cost value for a run with no training step of its own
    (a hosted pre-trained API model, or a predictor that never fits
    anything)."""
    return {"gpu_hours": 0.0, "note": note}


def write_run_meta(run_name: str, cost_basis: str, hardware: str, training_cost: dict) -> Path:
    """Write results/<run_name>.run_meta.json -- picked up automatically by
    evaluate.py's save_result() the next time that run is scored."""
    if cost_basis not in COST_BASES:
        raise ValueError(f"cost_basis must be one of {COST_BASES}, got {cost_basis!r}")
    if "gpu_hours" not in training_cost or "note" not in training_cost:
        raise ValueError(f"training_cost must have 'gpu_hours' and 'note', got {training_cost!r}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = run_meta_path(run_name)
    payload = {"cost_basis": cost_basis, "hardware": hardware, "training_cost": training_cost}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
