"""Step 03 -- regenerates a full markdown comparison table of every run
recorded in results/results.json. No model calls, no scoring -- evaluate.py
does that; this script only reads what's already there and re-renders it.

Run from the repo root:
    .venv\\Scripts\\python.exe src\\ticket_router\\report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `ticket_router` importable when this file is run directly
# (`python src/ticket_router/report.py`), not just via `python -m` with
# src/ already on PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ticket_router.metrics import md_table

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = REPO_ROOT / "results"
RESULTS_JSON_PATH = RESULTS_DIR / "results.json"
COMPARISON_PATH = RESULTS_DIR / "comparison.md"


def build_comparison(all_results: dict) -> str:
    headers = ["run", "split", "n", "exact_match", "invalid_rate",
               "queue_acc", "queue_f1", "priority_acc", "priority_f1",
               "type_acc", "type_f1", "lat_p50_ms", "lat_p95_ms",
               "total_cost_usd", "cost_per_1000_usd"]
    rows = []
    for run_name, r in all_results.items():
        rows.append([
            run_name, r["split"], r["n_gold"],
            f"{r['exact_match_rate']:.2%}", f"{r['invalid_rate']:.2%}",
            f"{r['fields']['queue']['accuracy']:.2%}", f"{r['fields']['queue']['macro_f1']:.4f}",
            f"{r['fields']['priority']['accuracy']:.2%}", f"{r['fields']['priority']['macro_f1']:.4f}",
            f"{r['fields']['type']['accuracy']:.2%}", f"{r['fields']['type']['macro_f1']:.4f}",
            f"{r['latency_ms']['p50']:.2f}", f"{r['latency_ms']['p95']:.2f}",
            f"{r['cost']['total_usd']:.4f}", f"{r['cost']['per_1000_usd']:.4f}",
        ])

    lines = ["# Run comparison\n"]
    if not rows:
        lines.append("_No runs recorded yet in results/results.json._\n")
    else:
        lines.append(md_table(headers, rows))
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    if RESULTS_JSON_PATH.exists():
        all_results = json.loads(RESULTS_JSON_PATH.read_text(encoding="utf-8"))
    else:
        all_results = {}
        print(f"Note: {RESULTS_JSON_PATH} does not exist yet -- writing an empty comparison table.")

    text = build_comparison(all_results)
    print(text)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    COMPARISON_PATH.write_text(text, encoding="utf-8")
    print(f"\nWrote {COMPARISON_PATH}")


if __name__ == "__main__":
    main()
