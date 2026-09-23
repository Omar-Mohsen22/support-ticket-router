"""Step 27 -- fail loudly if data/processed/test.parquet is not the split every
published result was scored against.

Computes the ordered-id gold hash (evaluate.compute_gold_hash) of the test
split on disk and compares it with every results.json entry recorded against
the full test split (split=test, limit=null). Exits 1 on any mismatch, or if
no such entry exists (nothing to check against is also a failure). The Docker
build runs this right after make_dataset.py regenerates the splits.

Run from the repo root:
    .venv\\Scripts\\python.exe src\\ticket_router\\check_gold_hash.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ticket_router.evaluate import compute_gold_hash

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_PATH = REPO_ROOT / "data" / "processed" / "test.parquet"
RESULTS_JSON_PATH = REPO_ROOT / "results" / "results.json"


def main() -> None:
    actual = compute_gold_hash(pd.read_parquet(TEST_PATH)["id"].tolist())
    all_results = json.loads(RESULTS_JSON_PATH.read_text(encoding="utf-8"))
    expected = {
        name: r["gold_split"]["id_sequence_sha256"]
        for name, r in all_results.items()
        if (r.get("gold_split") or {}).get("split") == "test" and r["gold_split"].get("limit") is None
    }
    print(f"test.parquet ordered-id sha256: {actual}")
    if not expected:
        print("STOP: no results.json entry records a gold_split for split=test, limit=null.")
        raise SystemExit(1)
    mismatched = {name: h for name, h in expected.items() if h != actual}
    for name, h in expected.items():
        print(f"  {name}: {h} {'MISMATCH' if name in mismatched else 'ok'}")
    if mismatched:
        print("STOP: the test split on disk is not the one the published results were scored against.")
        raise SystemExit(1)
    print(f"OK: matches all {len(expected)} recorded test-split hashes.")


if __name__ == "__main__":
    main()
