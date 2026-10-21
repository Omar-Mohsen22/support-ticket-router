"""Step 29 -- agreement between the adapter on the ZeroGPU demo (bf16 base, merged) and the
published adapter predictions (4-bit NF4 base on a T4), on the test split.

HISTORICAL. The measurement depended on the demo's hidden /predict_batch endpoint, which step 31
removed before the Space went public (and the bf16 demo config it measured was replaced in
step 29). Measuring again no longer works. The results are preserved in reports/:
adapter_zerogpu_agreement.md, .predictions.jsonl and .ledger.jsonl. `--report` still rebuilds
the report from those saved outputs, with no Space call.

Budget rules (Omar's step-29 decisions):
- Hard cap of 10 GPU-minutes for the whole step, inside the free PRO daily quota. The cap is
  checked against the CONSERVATIVE count: the client-side wall time of every call, which
  includes queueing and network. That count also includes the GPU used earlier in the step
  (PRIOR_* below).
- Batches of 16 through the hidden predict_batch endpoint.
- Gate 1: after the first batch, re-estimate the total. Stop if it exceeds 8 minutes.
- Gate 2: after ~10% of tickets, re-estimate from the batches measured so far. Stop if the
  projected total exceeds the 10-minute cap.
- Hard stop: never start a batch that would take the conservative total past 9.5 minutes.

The order is a seeded shuffle of the test split, so an early stop still leaves a random sample.
Predictions and a per-batch GPU ledger are appended to disk after every batch, and a rerun
resumes from them. This script never writes results.json.

Run from the repo root (needs HF_SPACE_TOKEN in .env; the token is never printed):
    python deploy/demo/measure_agreement.py            (measure or resume, then write the report)
    python deploy/demo/measure_agreement.py --report   (only rebuild the report from saved outputs)
    python deploy/demo/measure_agreement.py --max-batches 1   (one batch, e.g. to see gate 1)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ticket_router.metrics import INVALID, field_metrics, md_table  # noqa: E402

SPACE_ID = "Omar-Mohsen22/support-ticket-router-demo"
SEED = 29
BATCH_SIZE = 16
FIELDS = ["queue", "priority", "type"]

CAP_S = 10 * 60
HARD_STOP_S = 9.5 * 60
GATE1_LIMIT_S = 8 * 60
GATE2_AFTER_TICKETS = 160
# GPU used earlier in step 29 (PROGRESS.md ledger): 4 calls before this script, plus the
# post-redeploy smoke test (995 / 2,078 ms) and the batch-of-8 verification (1,056 / 2,735 ms).
PRIOR_CONSERVATIVE_S = 21.5
PRIOR_IN_FUNCTION_S = 6.2

OUT_DIR = REPO_ROOT / "reports"
PRED_PATH = OUT_DIR / "adapter_zerogpu_agreement.predictions.jsonl"
LEDGER_PATH = OUT_DIR / "adapter_zerogpu_agreement.ledger.jsonl"
REPORT_PATH = OUT_DIR / "adapter_zerogpu_agreement.md"
PUBLISHED_PATH = REPO_ROOT / "results" / "qlora-adapter-ckpt1500.predictions.jsonl"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def seeded_order(test: pd.DataFrame) -> list[str]:
    return [test["id"].iloc[i] for i in np.random.default_rng(SEED).permutation(len(test))]


def spent(ledger: list[dict]) -> tuple[float, float]:
    conservative = PRIOR_CONSERVATIVE_S + sum(b["client_wall_ms"] for b in ledger) / 1000
    in_function = PRIOR_IN_FUNCTION_S + sum(b["gpu_ms"] for b in ledger) / 1000
    return conservative, in_function


def projected_total(ledger: list[dict], n_remaining: int) -> float:
    avg_wall_s = sum(b["client_wall_ms"] for b in ledger) / len(ledger) / 1000
    return spent(ledger)[0] + avg_wall_s * math.ceil(n_remaining / BATCH_SIZE)


def measure(test: pd.DataFrame, max_batches: int | None) -> str:
    from dotenv import load_dotenv
    from gradio_client import Client

    load_dotenv(REPO_ROOT / ".env", override=True)
    client = Client(SPACE_ID, token=os.environ["HF_SPACE_TOKEN"], verbose=False)

    by_id = test.set_index("id")
    order = seeded_order(test)
    done = {r["id"] for r in read_jsonl(PRED_PATH)}
    ledger = read_jsonl(LEDGER_PATH)
    todo = [t for t in order if t not in done]
    gate1_checked = len(ledger) > 0
    gate2_checked = len(done) >= GATE2_AFTER_TICKETS
    print(f"seed={SEED} batch={BATCH_SIZE} done={len(done)} todo={len(todo)} "
          f"spent_conservative={spent(ledger)[0]:.1f}s")

    batches_this_run = 0
    while todo:
        if max_batches is not None and batches_this_run >= max_batches:
            return f"paused after {batches_this_run} batch(es) (--max-batches)"
        if ledger:
            avg_wall_s = sum(b["client_wall_ms"] for b in ledger) / len(ledger) / 1000
            if spent(ledger)[0] + avg_wall_s > HARD_STOP_S:
                return f"hard stop: the next batch would pass {HARD_STOP_S / 60:.1f} conservative minutes"
        ids, todo = todo[:BATCH_SIZE], todo[BATCH_SIZE:]
        payload = [{"id": i, "subject": by_id.at[i, "subject"] if isinstance(by_id.at[i, "subject"], str) else None,
                    "body": by_id.at[i, "body"]} for i in ids]
        t0 = time.perf_counter()
        try:
            out = json.loads(client.predict(json.dumps(payload), api_name="/predict_batch"))
        except Exception as e:  # stop rather than retry into more GPU use
            return f"stopped on an error from the Space: {type(e).__name__}: {str(e)[:200]}"
        wall_ms = (time.perf_counter() - t0) * 1000
        append_jsonl(PRED_PATH, out["results"])
        entry = {"batch": len(ledger), "n": len(ids), "gpu_ms": out["gpu_ms"], "client_wall_ms": wall_ms}
        append_jsonl(LEDGER_PATH, [entry])
        ledger.append(entry)
        batches_this_run += 1
        cons, inf = spent(ledger)
        print(f"batch {entry['batch']:3d}: n={len(ids)} gpu={out['gpu_ms']:.0f}ms wall={wall_ms:.0f}ms "
              f"| total conservative={cons:.1f}s in-function={inf:.1f}s", flush=True)

        if not gate1_checked:
            gate1_checked = True
            estimate = projected_total(ledger, len(todo))
            print(f"GATE 1: projected conservative total {estimate / 60:.2f} min (limit {GATE1_LIMIT_S / 60:.0f})")
            if estimate > GATE1_LIMIT_S:
                return f"gate 1: projected {estimate / 60:.2f} min exceeds {GATE1_LIMIT_S / 60:.0f} min"
        processed = len(read_jsonl(PRED_PATH))
        if not gate2_checked and processed >= GATE2_AFTER_TICKETS:
            gate2_checked = True
            estimate = projected_total(ledger, len(todo))
            print(f"GATE 2 at {processed} tickets: projected conservative total {estimate / 60:.2f} min "
                  f"(cap {CAP_S / 60:.0f})")
            if estimate > CAP_S:
                return f"gate 2: projected {estimate / 60:.2f} min exceeds the {CAP_S / 60:.0f}-min cap"
    return "completed"


def write_report(test: pd.DataFrame, status: str) -> None:
    preds = {r["id"]: r for r in read_jsonl(PRED_PATH)}
    ledger = read_jsonl(LEDGER_PATH)
    published = {r["id"]: r for r in read_jsonl(PUBLISHED_PATH)}
    gold = test.set_index("id")
    ids = [i for i in seeded_order(test) if i in preds]  # seeded order, measured tickets only
    n = len(ids)

    def label(pred_row, field):
        return pred_row["labels"][field] if pred_row.get("labels") else INVALID

    def published_label(i, field):
        v = published[i].get(field)
        return v if v is not None else INVALID

    invalid_bf16 = sum(1 for i in ids if not preds[i].get("labels"))
    invalid_pub = sum(1 for i in ids if any(published[i].get(f) is None for f in FIELDS))

    agree_rows = []
    for f in FIELDS:
        k = sum(1 for i in ids if label(preds[i], f) == published_label(i, f))
        agree_rows.append([f, f"{k} / {n}", f"{k / n:.2%}"])
    k_all = sum(1 for i in ids if all(label(preds[i], f) == published_label(i, f) for f in FIELDS))
    agree_rows.append(["all three fields", f"{k_all} / {n}", f"{k_all / n:.2%}"])

    f1_rows = []
    for f in FIELDS:
        y = [gold.at[i, f] for i in ids]
        bf16 = field_metrics(y, [label(preds[i], f) for i in ids])["macro_f1"]
        pub = field_metrics(y, [published_label(i, f) for i in ids])["macro_f1"]
        f1_rows.append([f, f"{pub:.4f}", f"{bf16:.4f}", f"{bf16 - pub:+.4f}"])

    cons, inf = spent(ledger)
    this_cons = sum(b["client_wall_ms"] for b in ledger) / 1000
    this_inf = sum(b["gpu_ms"] for b in ledger) / 1000

    lines = [
        "# Adapter on ZeroGPU (bf16) vs the published adapter predictions (4-bit, T4)\n",
        "Generated by `deploy/demo/measure_agreement.py`. Not part of `results/results.json`.\n",
        "**The two runs are not the same setup:**",
        "- **Published metrics** (`results/qlora-adapter-ckpt1500.predictions.jsonl`): the base model "
        "was loaded in **4-bit NF4 on a Tesla T4**, with the LoRA adapter attached (not merged), "
        "batch size 8. `inference.batch_size` in `train/config.yaml` is 8. The batch size is not "
        "recorded per run, but the predictions file shows identical per-row latency in 204 groups "
        "of 8 plus 1 of 1.",
        "- **This measurement:** the demo Space loads the base model **unquantized in bfloat16 on "
        "ZeroGPU** (half an RTX Pro 6000 Blackwell), with the adapter merged (`merge_and_unload`), "
        f"batch size **{BATCH_SIZE}**.",
        "- Both use the same system prompt, chat template, left padding, greedy decoding "
        "(`do_sample=False`, `max_new_tokens=64`) and output validation, from "
        "`predictors/adapter_predictor.py`.",
        "",
        "Batch size and left padding can themselves change a few outputs: the same ticket sees "
        "different padding, so numerics differ slightly. Any disagreement below is therefore "
        "**not attributable to precision alone**.\n",
        f"**Sample:** {n} of {len(test)} test tickets, taken in a seeded shuffle order "
        f"(`numpy.random.default_rng({SEED}).permutation`), so a partial run is a random sample. "
        f"Run status: **{status}**.\n",
        "## Agreement with the published predictions (same tickets)\n",
        md_table(["field", "agree", "%"], agree_rows),
        "",
        "## Macro-F1 against gold labels (same tickets)\n",
        md_table(["field", "published adapter (4-bit, T4)", "demo adapter (bf16, ZeroGPU)", "delta"], f1_rows),
        "",
        "## Invalid outputs\n",
        f"- Demo (bf16): **{invalid_bf16}** of {n} (not parseable, or a label outside the allowed set).",
        f"- Published (4-bit), same tickets: {invalid_pub} of {n}.",
        "",
        "## GPU time\n",
        f"- **This measurement:** {len(ledger)} batches, {this_inf:.1f} s inside `@spaces.GPU` and "
        f"{this_cons:.1f} s conservative (client-side wall time per call).",
        f"- **All of step 29,** including the smoke tests and duration probes before this "
        f"measurement: {inf:.1f} s inside `@spaces.GPU` and **{cons:.1f} s ({cons / 60:.2f} min) "
        f"conservative**, against the 10-minute cap.",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="Only rebuild the report.")
    parser.add_argument("--max-batches", type=int, default=None, help="Stop after this many batches (resume later).")
    args = parser.parse_args()
    test = pd.read_parquet(REPO_ROOT / "data" / "processed" / "test.parquet")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    status = "report rebuilt from saved outputs" if args.report else measure(test, args.max_batches)
    print(f"STATUS: {status}")
    write_report(test, status)


if __name__ == "__main__":
    main()
