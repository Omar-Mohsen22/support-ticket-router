"""Step 04c -- TF-IDF near-duplicate leakage check.

Exact-duplicate rows were already ruled out across splits in step-02 (dedup
on `text` before splitting). This checks the weaker, still-dangerous case:
synthetic tickets generated from the same template can be near-identical
without being byte-identical, which would let a model "cheat" by memorizing
a near-twin rather than generalizing.

For every test row, computes cosine similarity against every train row using
the SAME TF-IDF vectorizer config as tfidf_baseline.py (imported from there,
not re-typed, so the two can't drift apart), takes each test row's maximum
similarity against the full training set, and:
  - reports the distribution of that max-similarity (min/median/p90/p95/max)
  - counts how many test rows exceed 0.90 / 0.95 / 0.99
  - prints the 5 most similar train/test pairs in full, for manual reading
  - recomputes tfidf-baseline's macro-F1 (from its already-saved predictions,
    not retrained) restricted to only the test rows whose nearest-train
    similarity is below 0.90 -- the number that decides whether step-04b's
    result is real signal or leakage.

Writes reports/leakage_check.md. Run from the repo root:
    .venv\\Scripts\\python.exe src\\ticket_router\\leakage_check.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `ticket_router` importable when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ticket_router.metrics import field_metrics, md_table, percentile
from ticket_router.predictors.tfidf_baseline import TFIDF_CONFIG

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RESULTS_DIR = REPO_ROOT / "results"
REPORTS_DIR = REPO_ROOT / "reports"
REPORT_PATH = REPORTS_DIR / "leakage_check.md"
TFIDF_PREDICTIONS_PATH = RESULTS_DIR / "tfidf-baseline.predictions.jsonl"
RESULTS_JSON_PATH = RESULTS_DIR / "results.json"

TARGET_FIELDS = ["queue", "priority", "type"]
FLAG_THRESHOLDS = [0.90, 0.95, 0.99]
RECHECK_THRESHOLD = 0.90  # the number that decides everything
N_PAIRS_TO_SHOW = 5


def main() -> None:
    for p in (PROCESSED_DIR / "train.parquet", PROCESSED_DIR / "test.parquet", TFIDF_PREDICTIONS_PATH):
        if not p.exists():
            print(f"STOP: {p} not found.")
            if p == TFIDF_PREDICTIONS_PATH:
                print("Run src/ticket_router/predictors/tfidf_baseline.py first.")
            else:
                print("Run src/ticket_router/make_dataset.py first.")
            raise SystemExit(1)

    train = pd.read_parquet(PROCESSED_DIR / "train.parquet")
    test = pd.read_parquet(PROCESSED_DIR / "test.parquet")
    print(f"Train: {len(train)} rows  |  Test: {len(test)} rows")
    print(f"Reusing tfidf_baseline.py's TFIDF_CONFIG: {TFIDF_CONFIG}\n")

    print("Fitting TF-IDF on train text only, transforming train + test ...")
    vectorizer = TfidfVectorizer(**TFIDF_CONFIG)
    X_train = vectorizer.fit_transform(train["text"])
    X_test = vectorizer.transform(test["text"])

    print("Computing cosine similarity of every test row against every train row "
          f"({len(test)} x {len(train)}) ...")
    sim = cosine_similarity(X_test, X_train)  # (n_test, n_train), dense
    max_sim = sim.max(axis=1)
    nearest_train_idx = sim.argmax(axis=1)
    print("Done.\n")

    # --- Distribution of max-similarity ------------------------------------------
    stats = {
        "min": float(np.min(max_sim)),
        "median (p50)": percentile(max_sim.tolist(), 50),
        "p90": percentile(max_sim.tolist(), 90),
        "p95": percentile(max_sim.tolist(), 95),
        "max": float(np.max(max_sim)),
    }
    print("Max-similarity distribution (each test row's single closest train row):")
    for k, v in stats.items():
        print(f"  {k}: {v:.4f}")

    # --- Threshold counts ----------------------------------------------------------
    threshold_counts = {t: int((max_sim > t).sum()) for t in FLAG_THRESHOLDS}
    print("\nTest rows exceeding similarity thresholds:")
    for t, c in threshold_counts.items():
        print(f"  > {t}: {c} / {len(test)} ({c / len(test):.2%})")

    # --- Top N most similar pairs ----------------------------------------------------
    order = np.argsort(-max_sim)[:N_PAIRS_TO_SHOW]
    top_pairs = []
    for rank, test_row_idx in enumerate(order, start=1):
        train_row_idx = nearest_train_idx[test_row_idx]
        test_row = test.iloc[test_row_idx]
        train_row = train.iloc[train_row_idx]
        pair = {
            "rank": rank,
            "similarity": float(max_sim[test_row_idx]),
            "test_id": test_row["id"], "test_text": test_row["text"],
            "test_queue": test_row["queue"], "test_priority": test_row["priority"], "test_type": test_row["type"],
            "train_id": train_row["id"], "train_text": train_row["text"],
            "train_queue": train_row["queue"], "train_priority": train_row["priority"], "train_type": train_row["type"],
        }
        top_pairs.append(pair)
        print(f"\nPair #{rank}: similarity={pair['similarity']:.4f}  "
              f"test={pair['test_id']}  train={pair['train_id']}")

    # --- Recompute macro-F1 on only the low-similarity subset ------------------------
    print(f"\nLoading tfidf-baseline predictions from {TFIDF_PREDICTIONS_PATH.name} ...")
    preds_by_id = {}
    with open(TFIDF_PREDICTIONS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            preds_by_id[row["id"]] = row

    test_with_sim = test[["id"] + TARGET_FIELDS].copy()
    test_with_sim["max_sim"] = max_sim
    for field in TARGET_FIELDS:
        test_with_sim[f"pred_{field}"] = test_with_sim["id"].map(
            lambda i: preds_by_id.get(i, {}).get(field)
        )

    low_sim = test_with_sim[test_with_sim["max_sim"] < RECHECK_THRESHOLD]
    n_low_sim = len(low_sim)
    print(f"\nTest rows with nearest-train similarity < {RECHECK_THRESHOLD}: "
          f"{n_low_sim} / {len(test)} ({n_low_sim / len(test):.2%})")

    all_results = {}
    low_sim_results = {}
    for field in TARGET_FIELDS:
        all_results[field] = field_metrics(
            test_with_sim[field].tolist(), test_with_sim[f"pred_{field}"].tolist()
        )
        low_sim_results[field] = field_metrics(
            low_sim[field].tolist(), low_sim[f"pred_{field}"].tolist()
        )

    print("\nmacro-F1, all test rows vs. only rows with max_sim < 0.90:")
    for field in TARGET_FIELDS:
        print(f"  {field}: all={all_results[field]['macro_f1']:.4f}  "
              f"low_sim_only={low_sim_results[field]['macro_f1']:.4f}")

    # --- Write report ------------------------------------------------------------------
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = build_report(
        n_train=len(train), n_test=len(test), stats=stats, threshold_counts=threshold_counts,
        top_pairs=top_pairs, n_low_sim=n_low_sim, all_results=all_results, low_sim_results=low_sim_results,
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {REPORT_PATH}")


def build_report(*, n_train, n_test, stats, threshold_counts, top_pairs, n_low_sim,
                  all_results, low_sim_results) -> list[str]:
    lines = ["# TF-IDF near-duplicate leakage check\n"]
    lines.append(
        f"Every one of the {n_test} test rows' TF-IDF vector (same config as "
        f"`tfidf_baseline.py`) compared by cosine similarity against all {n_train} train rows' "
        "vectors. Exact duplicates across splits were already ruled out in step-02 (dedup on "
        "`text` before splitting); this checks near-duplicates, which dedup on exact text cannot "
        "catch but which can leak just as effectively for synthetic, template-generated tickets.\n"
    )

    lines.append("## Max-similarity distribution\n")
    lines.append("Each test row's similarity to its single closest train row:\n")
    rows = [[k, f"{v:.4f}"] for k, v in stats.items()]
    lines.append(md_table(["statistic", "value"], rows))
    lines.append("")

    lines.append("## Rows exceeding similarity thresholds\n")
    rows = [[f"> {t}", c, f"{c / n_test:.2%}"] for t, c in threshold_counts.items()]
    lines.append(md_table(["threshold", "count", "pct_of_test"], rows))
    lines.append("")

    lines.append(f"## {len(top_pairs)} most similar train/test pairs\n")
    lines.append(
        "Full ticket text for each, one after another (not literal side-by-side columns -- "
        "markdown tables can't hold full ticket text legibly) so they can be read and compared "
        "directly.\n"
    )
    for pair in top_pairs:
        lines.append(f"### Pair #{pair['rank']} -- similarity = {pair['similarity']:.4f}\n")
        lines.append(
            f"**TEST** `{pair['test_id']}` (queue=`{pair['test_queue']}`, "
            f"priority=`{pair['test_priority']}`, type=`{pair['test_type']}`):\n"
        )
        lines.append("```\n" + pair["test_text"] + "\n```\n")
        lines.append(
            f"**TRAIN** `{pair['train_id']}` (queue=`{pair['train_queue']}`, "
            f"priority=`{pair['train_priority']}`, type=`{pair['train_type']}`):\n"
        )
        lines.append("```\n" + pair["train_text"] + "\n```\n")

    lines.append("## macro-F1: all test rows vs. only low-similarity test rows\n")
    lines.append(
        f"Recomputed from `results/tfidf-baseline.predictions.jsonl` (not retrained), restricted "
        f"to the {n_low_sim} / {n_test} test rows whose nearest-train-neighbour similarity is below "
        f"{RECHECK_THRESHOLD} -- **this is the number that decides whether step-04b's headline "
        "result is real signal or leakage.**\n"
    )
    rows = [
        [field, f"{all_results[field]['macro_f1']:.4f}", f"{low_sim_results[field]['macro_f1']:.4f}",
         all_results[field]["n"], low_sim_results[field]["n"]]
        for field in TARGET_FIELDS
    ]
    lines.append(md_table(["field", "macro_f1_all_test", "macro_f1_low_sim_only", "n_all", "n_low_sim"], rows))
    lines.append("")

    verdict = decide_verdict(all_results, low_sim_results)
    lines.append("## Verdict\n")
    lines.append(verdict)

    return lines


def load_random_baseline_f1() -> dict:
    """Read the random-baseline reference LIVE from results/results.json, not a hand-typed
    snapshot. A hardcoded copy sat here before (step-04c) and went stale exactly once
    already: predict_random_baseline.py's sampling method changed (step-18, id-keyed
    instead of position-keyed -- see its module docstring) and the macro-F1 numbers
    changed with it, but a hardcoded copy in THIS file would not have, silently. This
    doesn't depend on the TF-IDF run at all, but reading it live costs nothing and removes
    the staleness risk entirely instead of just fixing today's snapshot."""
    if not RESULTS_JSON_PATH.exists():
        print(f"STOP: {RESULTS_JSON_PATH} not found.")
        print("Run predict_random_baseline.py, then evaluate.py --run-name random-baseline, first.")
        raise SystemExit(1)
    all_results = json.loads(RESULTS_JSON_PATH.read_text(encoding="utf-8"))
    if "random-baseline" not in all_results:
        print(f"STOP: 'random-baseline' not found in {RESULTS_JSON_PATH}.")
        print("Run predict_random_baseline.py, then evaluate.py --run-name random-baseline, first.")
        raise SystemExit(1)
    fields = all_results["random-baseline"]["fields"]
    return {field: fields[field]["macro_f1"] for field in TARGET_FIELDS}


def decide_verdict(all_results: dict, low_sim_results: dict) -> str:
    random_baseline_f1 = load_random_baseline_f1()
    lines = []
    collapsed_fields = []
    held_fields = []
    for field in TARGET_FIELDS:
        all_f1 = all_results[field]["macro_f1"]
        low_f1 = low_sim_results[field]["macro_f1"]
        rand_f1 = random_baseline_f1[field]
        # "Collapsed toward random" = low-similarity-only score is within a small
        # absolute margin of the random baseline, or dropped most of the way from
        # the full-test score back down to it.
        span = all_f1 - rand_f1
        drop_from_all = all_f1 - low_f1
        collapsed = (low_f1 <= rand_f1 + 0.03) or (span > 0.01 and drop_from_all / span > 0.7)
        (collapsed_fields if collapsed else held_fields).append(field)
        lines.append(
            f"- **{field}**: all-test={all_f1:.4f}, low-sim-only={low_f1:.4f}, "
            f"random-baseline={rand_f1:.4f} -> "
            + ("collapses toward random -- consistent with leakage inflating the full-test score."
               if collapsed else "holds well above random -- consistent with real signal.")
        )
    lines.append("")
    if not collapsed_fields:
        lines.append(
            "**All three fields hold up on the low-similarity subset.** The headline step-04b "
            "result is real: TF-IDF is learning genuine signal from the ticket text, not "
            "memorizing near-duplicate training tickets. The comparison against the zero-shot "
            "LLM baseline stands."
        )
    elif len(collapsed_fields) == len(TARGET_FIELDS):
        lines.append(
            f"**All three fields ({', '.join(collapsed_fields)}) collapse toward the random "
            "baseline on the low-similarity subset.** The step-04b headline result looks like "
            "near-duplicate leakage, not genuine signal -- it should not be used to draw "
            "conclusions about the zero-shot LLM's prompt quality."
        )
    else:
        lines.append(
            f"**Mixed result**: {', '.join(collapsed_fields)} collapse(s) toward random on the "
            f"low-similarity subset (leakage-consistent), while {', '.join(held_fields)} "
            "hold(s) up (signal-consistent). Treat the collapsed field(s)' step-04b score as "
            "unreliable; the held field(s)' comparison against the zero-shot LLM still stands."
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
