"""Step 03 -- evaluation harness. No model calls happen here; this script only
scores predictions someone else already produced.

Takes a predictions JSONL file (one JSON object per line: id, queue, priority,
type, latency_ms, input_tokens, output_tokens, cost_usd) and a gold split
(train/val/test from data/processed/), and computes macro-F1 + accuracy per
field, exact-match rate, invalid-output rate, latency p50/p95, and cost.
Prints a markdown summary row plus a per-class breakdown, and writes/updates
results/results.json, keyed by run name.

Step-16 (run_meta) recorded WHERE and at what cost a run happened. Step-17
records WHAT DATA it was scored against: data/processed/*.parquet is
gitignored (not version-controlled), so nothing previously stopped a run
from silently being scored against a test split with a different row order
(or content) than the one earlier results in results.json were produced
against -- two committed runs (random-baseline, api-gpt4o-mini-50) turned
out to be exactly that (see PROGRESS.md's step-17 entry for the full
investigation). Every run's gold split is now hashed (compute_gold_hash --
the ORDERED id sequence, since row order matters for position-based
predictors like the random baseline) and recorded under "gold_split" in its
results.json entry. Before saving, check_gold_hash_consistency() compares
this run's hash against every other run already recorded against the same
(split, limit) and STOPS (SystemExit, no results.json write) on a mismatch,
rather than silently adding a row that cannot actually be compared to the
rest of the table.

Run from the repo root:
    .venv\\Scripts\\python.exe src\\ticket_router\\evaluate.py \\
        --predictions results/random-baseline.predictions.jsonl \\
        --split test --run-name random-baseline
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Make `ticket_router` importable when this file is run directly
# (`python src/ticket_router/evaluate.py`), not just via `python -m` with
# src/ already on PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from pydantic import ValidationError

from ticket_router.metrics import INVALID, exact_match_rate, field_metrics, md_table, percentile
from ticket_router.run_meta import run_meta_path
from ticket_router.schema import TicketLabels

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RESULTS_DIR = REPO_ROOT / "results"
RESULTS_JSON_PATH = RESULTS_DIR / "results.json"

TARGET_FIELDS = ["queue", "priority", "type"]
NUMERIC_FIELDS = ["latency_ms", "input_tokens", "output_tokens", "cost_usd"]


def load_predictions(path: Path) -> tuple[dict, dict]:
    """Read a predictions JSONL file.

    Returns (labels_by_id, numeric_by_id):
      - labels_by_id[id] = TicketLabels instance, only for lines that parsed
        as JSON, had a usable id, AND validated (queue/priority/type all in
        the allowed set). A row missing from this dict is treated as
        INVALID by the caller.
      - numeric_by_id[id] = {field: value or None}, for any line that parsed
        as JSON and had a usable id, REGARDLESS of label validity -- an API
        call can burn tokens/time even if its labels come back malformed.

    Also prints a warning with counts of unparseable lines / lines missing an
    id, since those can't be attributed to any specific gold row at all.
    """
    labels_by_id: dict[str, TicketLabels] = {}
    numeric_by_id: dict[str, dict] = {}
    n_lines = 0
    n_unparseable = 0
    n_no_id = 0
    n_invalid_labels = 0

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n_lines += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                n_unparseable += 1
                continue

            row_id = row.get("id")
            if not row_id or not isinstance(row_id, str):
                n_no_id += 1
                continue

            numeric_by_id[row_id] = {}
            for field in NUMERIC_FIELDS:
                value = row.get(field)
                try:
                    numeric_by_id[row_id][field] = float(value) if value is not None else None
                except (TypeError, ValueError):
                    numeric_by_id[row_id][field] = None

            try:
                labels_by_id[row_id] = TicketLabels(
                    queue=row.get("queue"), priority=row.get("priority"), type=row.get("type"),
                )
            except ValidationError:
                n_invalid_labels += 1

    print(f"Read {n_lines} prediction line(s) from {path.name}:")
    print(f"  unparseable JSON: {n_unparseable}")
    print(f"  missing/non-string id: {n_no_id}")
    print(f"  parsed but invalid labels (value outside allowed set): {n_invalid_labels}")
    print(f"  valid labeled predictions: {len(labels_by_id)}")

    return labels_by_id, numeric_by_id


def evaluate(gold: pd.DataFrame, labels_by_id: dict, numeric_by_id: dict) -> dict:
    n_gold = len(gold)
    gold_ids = gold["id"].tolist()

    field_results = {}
    per_field_pred = {}
    for field in TARGET_FIELDS:
        y_true = gold[field].tolist()
        y_pred = [
            labels_by_id[i].__getattribute__(field) if i in labels_by_id else INVALID
            for i in gold_ids
        ]
        per_field_pred[field] = y_pred
        field_results[field] = field_metrics(y_true, y_pred)

    gold_rows = gold[TARGET_FIELDS].to_dict("records")
    pred_rows = [
        {field: per_field_pred[field][i] for field in TARGET_FIELDS}
        for i in range(n_gold)
    ]
    exact_match = exact_match_rate(gold_rows, pred_rows, TARGET_FIELDS)

    n_valid = sum(1 for i in gold_ids if i in labels_by_id)
    invalid_rate = (n_gold - n_valid) / n_gold if n_gold else 0.0

    latencies = [
        numeric_by_id[i]["latency_ms"] for i in gold_ids
        if i in numeric_by_id and numeric_by_id[i]["latency_ms"] is not None
    ]
    costs = [
        numeric_by_id[i]["cost_usd"] for i in gold_ids
        if i in numeric_by_id and numeric_by_id[i]["cost_usd"] is not None
    ]
    total_cost = sum(costs)
    cost_per_1000 = (total_cost / n_gold * 1000) if n_gold else 0.0

    return {
        "n_gold": n_gold,
        "n_valid": n_valid,
        "invalid_rate": invalid_rate,
        "exact_match_rate": exact_match,
        "fields": field_results,
        "latency_ms": {
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "n": len(latencies),
        },
        "cost": {
            "total_usd": total_cost,
            "per_1000_usd": cost_per_1000,
            "n_with_cost": len(costs),
        },
    }


def print_summary(run_name: str, split: str, result: dict) -> None:
    headers = ["run", "split", "n", "exact_match", "invalid_rate",
               "queue_acc", "queue_f1", "priority_acc", "priority_f1",
               "type_acc", "type_f1", "lat_p50_ms", "lat_p95_ms",
               "total_cost_usd", "cost_per_1000_usd"]
    row = [
        run_name, split, result["n_gold"],
        f"{result['exact_match_rate']:.2%}", f"{result['invalid_rate']:.2%}",
        f"{result['fields']['queue']['accuracy']:.2%}", f"{result['fields']['queue']['macro_f1']:.4f}",
        f"{result['fields']['priority']['accuracy']:.2%}", f"{result['fields']['priority']['macro_f1']:.4f}",
        f"{result['fields']['type']['accuracy']:.2%}", f"{result['fields']['type']['macro_f1']:.4f}",
        f"{result['latency_ms']['p50']:.2f}", f"{result['latency_ms']['p95']:.2f}",
        f"{result['cost']['total_usd']:.4f}", f"{result['cost']['per_1000_usd']:.4f}",
    ]
    print("\n=== Summary (markdown row) ===")
    print(md_table(headers, [row]))

    print("\n=== Per-class breakdown (support reported next to every metric) ===")
    for field in TARGET_FIELDS:
        print(f"\n`{field}` (macro_f1={result['fields'][field]['macro_f1']:.4f}, "
              f"accuracy={result['fields'][field]['accuracy']:.2%}):")
        rows = [
            [cls, stats["support"], f"{stats['precision']:.4f}", f"{stats['recall']:.4f}", f"{stats['f1']:.4f}"]
            for cls, stats in sorted(result["fields"][field]["per_class"].items())
        ]
        print(md_table(["class", "support", "precision", "recall", "f1"], rows))


def load_run_meta(run_name: str) -> dict:
    """Picks up results/<run_name>.run_meta.json if the predictor wrote one
    (see ticket_router.run_meta) -- cost_basis, hardware, and training_cost,
    none of which are derivable from the predictions file itself. Falls back
    to an explicit "unknown" rather than silently omitting the key, so a
    missing run_meta is visible in results.json and in report.py's table,
    not just absent without explanation."""
    path = run_meta_path(run_name)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    print(f"WARNING: no {path.name} found -- recording run_meta as 'unknown' for '{run_name}'. "
          "The predictor should call ticket_router.run_meta.write_run_meta() before this runs.")
    return {
        "cost_basis": "unknown",
        "hardware": "unknown",
        "training_cost": {"gpu_hours": 0.0, "note": "run_meta not provided"},
    }


def compute_gold_hash(ids: list) -> str:
    """sha256 of the gold split's ORDERED id sequence (position matters, not
    just membership -- see check_gold_hash_consistency for why: a predictor
    that assigns by position, e.g. predict_random_baseline.py, or a
    --limit-based row slice, produces a different, silently incomparable
    result if the underlying split's row order changes even when its id SET
    is unchanged)."""
    payload = "\n".join(str(i) for i in ids)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_results_json() -> dict:
    if RESULTS_JSON_PATH.exists():
        return json.loads(RESULTS_JSON_PATH.read_text(encoding="utf-8"))
    return {}


def check_gold_hash_consistency(all_results: dict, split: str, limit: int | None,
                                 gold_hash: str, run_name: str) -> None:
    """FAIL LOUDLY (raise SystemExit) if this run's gold split does not match
    the ordered id sequence already recorded by another run against the same
    (split, limit) -- this project's comparison table (report.py) assumes
    every run against the same split/limit is directly comparable. Silently
    scoring against a different id order/set would produce numbers that
    cannot actually be compared to the existing ones, with no way to tell
    from results.json alone that anything was wrong (see PROGRESS.md's
    step-16 and step-17 entries for exactly this happening: two committed
    runs turned out to have been scored against a since-changed row order).

    Only compares against OTHER run names using the identical (split, limit)
    -- a deliberately smaller/--limit'd smoke-test run (e.g.
    api-gpt4o-mini-50) is legitimately a different id sequence from a
    full-split run and must not be flagged against it. Re-running the SAME
    run_name (overwriting itself) is always allowed regardless of its own
    prior hash.
    """
    for other_name, other in all_results.items():
        if other_name == run_name:
            continue
        gs = other.get("gold_split")
        if not gs or gs.get("split") != split or gs.get("limit") != limit:
            continue
        if gs.get("id_sequence_sha256") != gold_hash:
            print("STOP: gold split mismatch.")
            print(f"  '{run_name}' would be scored against a DIFFERENT ordered test-set id "
                  f"sequence than '{other_name}', even though both use split={split!r} "
                  f"limit={limit!r}.")
            print(f"  '{other_name}' recorded hash: {gs.get('id_sequence_sha256')}")
            print(f"  This run's hash:              {gold_hash}")
            print("  The resulting metrics would NOT be comparable to the existing results "
                  "table -- refusing to save. Either regenerate data/processed/ so it matches "
                  "the split the existing results were produced against, or, if the split was "
                  "deliberately changed, that is a new baseline -- re-run every predictor "
                  "against it explicitly rather than letting this one run silently disagree "
                  "with the rest of results.json.")
            raise SystemExit(1)


def save_result(run_name: str, split: str, predictions_path: Path, result: dict,
                 gold_split: dict, all_results: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    all_results[run_name] = {
        "run_name": run_name,
        "split": split,
        "predictions_file": str(predictions_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "run_meta": load_run_meta(run_name),
        "gold_split": gold_split,
        **result,
    }
    RESULTS_JSON_PATH.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote/updated '{run_name}' in {RESULTS_JSON_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", required=True, type=lambda p: Path(p).resolve(),
                         help="Path to a predictions JSONL file")
    parser.add_argument("--split", required=True, choices=["train", "val", "test"], help="Gold split to score against")
    parser.add_argument("--limit", type=int, default=None,
                         help="Score against only the first N rows of the split (must match the "
                              "--limit a predictor used, e.g. predictors/api_predictor.py, so gold "
                              "and predictions cover the same rows -- omit for the full split)")
    parser.add_argument("--run-name", required=True, help="Key this run is stored under in results/results.json")
    args = parser.parse_args()

    gold_path = PROCESSED_DIR / f"{args.split}.parquet"
    if not gold_path.exists():
        print(f"STOP: gold split not found: {gold_path}")
        print("Run src/ticket_router/make_dataset.py first to generate it.")
        raise SystemExit(1)
    if not args.predictions.exists():
        print(f"STOP: predictions file not found: {args.predictions}")
        raise SystemExit(1)

    gold = pd.read_parquet(gold_path)
    if args.limit is not None:
        gold = gold.head(args.limit)
    print(f"Loaded {len(gold)} gold rows from {gold_path.name}"
          + (f" (limited to first {args.limit})" if args.limit is not None else ""))

    gold_ids = gold["id"].tolist()
    gold_hash = compute_gold_hash(gold_ids)
    all_results = load_results_json()
    check_gold_hash_consistency(all_results, args.split, args.limit, gold_hash, args.run_name)

    labels_by_id, numeric_by_id = load_predictions(args.predictions)
    result = evaluate(gold, labels_by_id, numeric_by_id)
    print_summary(args.run_name, args.split, result)
    gold_split = {
        "split": args.split, "limit": args.limit, "n": len(gold_ids),
        "id_sequence_sha256": gold_hash,
    }
    save_result(args.run_name, args.split, args.predictions, result, gold_split, all_results)


if __name__ == "__main__":
    main()
