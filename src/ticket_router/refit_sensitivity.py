"""Step 27 -- how sensitive are the TF-IDF results to refitting on another
platform? Refits the TF-IDF baseline with the unchanged fit_models() and scores
it on the full test split with evaluate.evaluate() (the same metric code that
produced results.json), next to the published tfidf-baseline predictions.

Writes NOTHING under results/ or models/. It only prints a markdown table, and
optionally writes that table plus a JSON copy to --out-dir (CI uploads them as
a job artifact and appends the table to the job summary).

Run from the repo root:
    .venv\\Scripts\\python.exe src\\ticket_router\\refit_sensitivity.py
    .venv\\Scripts\\python.exe src\\ticket_router\\refit_sensitivity.py --out-dir some/dir
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import platform
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ticket_router.evaluate import evaluate, load_predictions
from ticket_router.metrics import md_table
from ticket_router.predictors.tfidf_baseline import (
    PROCESSED_DIR, RESULTS_DIR, RUN_NAME, TARGET_FIELDS, fit_models,
)
from ticket_router.schema import TicketLabels

PUBLISHED_PATH = RESULTS_DIR / f"{RUN_NAME}.predictions.jsonl"
RESULTS_JSON_PATH = RESULTS_DIR / "results.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    train = pd.read_parquet(PROCESSED_DIR / "train.parquet")
    test = pd.read_parquet(PROCESSED_DIR / "test.parquet")

    with contextlib.redirect_stdout(io.StringIO()):
        vectorizer, classifiers, _ = fit_models(train)
        published_labels, published_numeric = load_predictions(PUBLISHED_PATH)
    X_test = vectorizer.transform(test["text"])
    refit_preds = {f: classifiers[f].predict(X_test) for f in TARGET_FIELDS}
    refit_labels = {
        ticket_id: TicketLabels(**{f: str(refit_preds[f][i]) for f in TARGET_FIELDS})
        for i, ticket_id in enumerate(test["id"])
    }

    published = evaluate(test, published_labels, published_numeric)
    refit = evaluate(test, refit_labels, {})

    # The published predictions must score exactly as results.json says, or this comparison
    # is not against the published numbers at all.
    recorded = json.loads(RESULTS_JSON_PATH.read_text(encoding="utf-8"))[RUN_NAME]
    for f in TARGET_FIELDS:
        assert published["fields"][f]["macro_f1"] == recorded["fields"][f]["macro_f1"], f
    assert published["exact_match_rate"] == recorded["exact_match_rate"]

    differing = {
        f: sum(1 for t in test["id"] if getattr(refit_labels[t], f) != getattr(published_labels[t], f))
        for f in TARGET_FIELDS
    }
    differing_any = sum(
        1 for t in test["id"]
        if any(getattr(refit_labels[t], f) != getattr(published_labels[t], f) for f in TARGET_FIELDS)
    )

    rows = []
    for f in TARGET_FIELDS:
        p, r = published["fields"][f]["macro_f1"], refit["fields"][f]["macro_f1"]
        rows.append([f"{f} macro-F1", f"{p:.4f}", f"{r:.4f}", f"{r - p:+.4f}", differing[f]])
    p, r = published["exact_match_rate"], refit["exact_match_rate"]
    rows.append(["exact match", f"{p:.2%}", f"{r:.2%}", f"{(r - p) * 100:+.2f} pp", differing_any])

    env = f"{platform.platform()}, Python {platform.python_version()}"
    table = md_table(["metric", f"published ({RUN_NAME})", "refit on this machine", "delta",
                      "test rows whose prediction differs"], rows)
    report = (
        f"## TF-IDF refit sensitivity\n\nRefit on: {env}. Test split: {len(test)} rows. The published "
        f"predictions were produced on Windows; results.json and the served artifact are not "
        f"touched.\n\n{table}\n\nThe last column counts rows whose prediction for that field "
        f"differs; for exact match, rows where any field differs.\n"
    )
    print(report)

    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "refit_sensitivity.md").write_text(report, encoding="utf-8")
        (args.out_dir / "refit_sensitivity.json").write_text(json.dumps({
            "environment": env, "n_test": len(test),
            "published": {**{f: published["fields"][f]["macro_f1"] for f in TARGET_FIELDS},
                          "exact_match_rate": published["exact_match_rate"]},
            "refit": {**{f: refit["fields"][f]["macro_f1"] for f in TARGET_FIELDS},
                      "exact_match_rate": refit["exact_match_rate"]},
            "rows_differing": {**differing, "any_field": differing_any},
        }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
