"""Step 29 -- the published adapter config reproduced on ZeroGPU (4-bit), on the first 400
tickets of the seed=29 order, compared with the bf16 demo run, the published predictions and
TF-IDF on those same tickets.

The 4-bit endpoint (predict_batch_4bit) exists only on the local branch probe/4bit-zerogpu and
was deployed from there by hand; it is never on master. On every call it loads the model with
adapter_predictor.load_model_and_tokenizer(): 4-bit NF4 with double quant (train/config.yaml),
the adapter unmerged, and the compute dtype pinned to float16, as pick_compute_dtype() chose on
the T4. It then generates in batches of 8.

Budget (Omar's step-29 rules): a conservative count (client-side wall time per call, plus
everything used earlier today) must stay under 10 minutes.
- The first call is a probe of 8 tickets. If bitsandbytes fails on ZeroGPU, stop with the
  exact error and do not retry.
- Gate at 40 tickets (10%): re-estimate the total and stop if it projects past the cap.
- Hard stop: never start a call whose estimated cost would pass 9.5 minutes.
- Outputs are appended after every call, and a rerun resumes from them. results.json is never
  touched.

Run from the repo root (needs HF_SPACE_TOKEN in .env; the token is never printed):
    python deploy/demo/measure_4bit.py --max-calls 1   (the probe)
    python deploy/demo/measure_4bit.py                 (continue, or resume, up to 400 tickets)
    python deploy/demo/measure_4bit.py --report        (rebuild the report only)
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
N_TICKETS = 400
CALL_PLAN = [8, 32, 90, 90, 90, 90]   # sums to 400; the first call is the probe
FIELDS = ["queue", "priority", "type"]
CAP_S = 10 * 60
HARD_STOP_S = 9.5 * 60
GATE_AFTER_TICKETS = 40
# Conservative GPU time used earlier today: 149.2 s through the bf16 agreement run (see
# reports/adapter_zerogpu_agreement.md), plus the smoke test of the branch deploy (2,281 ms
# client-side).
PRIOR_CONSERVATIVE_S = 149.2 + 2.281

OUT = REPO_ROOT / "reports"
PRED_PATH = OUT / "adapter_zerogpu_4bit.predictions.jsonl"
LEDGER_PATH = OUT / "adapter_zerogpu_4bit.ledger.jsonl"
REPORT_PATH = OUT / "adapter_zerogpu_4bit.md"
BF16_PATH = OUT / "adapter_zerogpu_agreement.predictions.jsonl"
PUBLISHED_PATH = REPO_ROOT / "results" / "qlora-adapter-ckpt1500.predictions.jsonl"
TFIDF_PATH = REPO_ROOT / "results" / "tfidf-baseline.predictions.jsonl"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def target_ids(test: pd.DataFrame) -> list[str]:
    order = [test["id"].iloc[i] for i in np.random.default_rng(SEED).permutation(len(test))]
    return order[:N_TICKETS]


def spent_s(ledger: list[dict]) -> float:
    return PRIOR_CONSERVATIVE_S + sum(c["client_wall_ms"] for c in ledger) / 1000


def estimate_call_s(ledger: list[dict], n: int) -> float:
    """Client wall time = fixed per-call overhead (model load, allocation, queue, network) plus
    the batches. Both parts are fitted from the calls so far; unknown before the probe."""
    overhead = sum((c["client_wall_ms"] - sum(c["batch_ms"])) for c in ledger) / len(ledger)
    per_batch = sum(sum(c["batch_ms"]) for c in ledger) / sum(len(c["batch_ms"]) for c in ledger)
    return (overhead + per_batch * math.ceil(n / 8)) / 1000


def measure(test: pd.DataFrame, max_calls: int | None) -> str:
    from dotenv import load_dotenv
    from gradio_client import Client

    load_dotenv(REPO_ROOT / ".env", override=True)
    client = Client(SPACE_ID, token=os.environ["HF_SPACE_TOKEN"], verbose=False)
    by_id = test.set_index("id")
    done = {r["id"] for r in read_jsonl(PRED_PATH)}
    ledger = read_jsonl(LEDGER_PATH)
    todo = [i for i in target_ids(test) if i not in done]
    gate_checked = len(done) >= GATE_AFTER_TICKETS
    calls_this_run = 0
    print(f"seed={SEED} target={N_TICKETS} done={len(done)} todo={len(todo)} spent={spent_s(ledger):.1f}s")

    while todo:
        if max_calls is not None and calls_this_run >= max_calls:
            return f"paused after {calls_this_run} call(s) (--max-calls)"
        n = min(CALL_PLAN[len(ledger)] if len(ledger) < len(CALL_PLAN) else CALL_PLAN[-1], len(todo))
        if ledger:
            est = estimate_call_s(ledger, n)
            if spent_s(ledger) + est > HARD_STOP_S:
                return (f"hard stop: the next call ({n} tickets, ~{est:.0f} s) would pass "
                        f"{HARD_STOP_S / 60:.1f} conservative minutes")
        ids, todo = todo[:n], todo[n:]
        payload = [{"id": i, "subject": by_id.at[i, "subject"] if isinstance(by_id.at[i, "subject"], str) else None,
                    "body": by_id.at[i, "body"]} for i in ids]
        t0 = time.perf_counter()
        try:
            out = json.loads(client.predict(json.dumps(payload), api_name="/predict_batch_4bit"))
        except Exception as e:  # the probe rule: report the exact error, never retry
            return f"stopped on an error from the Space: {type(e).__name__}: {str(e)[:500]}"
        wall = (time.perf_counter() - t0) * 1000
        append_jsonl(PRED_PATH, out["results"])
        entry = {"call": len(ledger), "n": n, "load_ms": out["load_ms"], "batch_ms": out["batch_ms"],
                 "gpu_ms": out["gpu_ms"], "client_wall_ms": wall}
        append_jsonl(LEDGER_PATH, [entry])
        ledger.append(entry)
        calls_this_run += 1
        print(f"call {entry['call']}: n={n} load={out['load_ms']:.0f}ms batches={len(out['batch_ms'])} "
              f"batch_mean={sum(out['batch_ms']) / len(out['batch_ms']):.0f}ms gpu={out['gpu_ms']:.0f}ms "
              f"wall={wall:.0f}ms | spent={spent_s(ledger):.1f}s", flush=True)

        processed = len(read_jsonl(PRED_PATH))
        if not gate_checked and processed >= GATE_AFTER_TICKETS:
            gate_checked = True
            remaining, projected, k = len(todo), spent_s(ledger), len(ledger)
            while remaining > 0:
                m = min(CALL_PLAN[k] if k < len(CALL_PLAN) else CALL_PLAN[-1], remaining)
                projected += estimate_call_s(ledger, m)
                remaining, k = remaining - m, k + 1
            print(f"GATE at {processed} tickets: projected conservative total {projected / 60:.2f} min "
                  f"(cap {CAP_S / 60:.0f})")
            if projected > CAP_S:
                return f"gate: projected {projected / 60:.2f} min exceeds the {CAP_S / 60:.0f}-min cap"
    return "completed"


def write_report(test: pd.DataFrame, status: str) -> None:
    four = {r["id"]: r for r in read_jsonl(PRED_PATH)}
    bf16 = {r["id"]: r for r in read_jsonl(BF16_PATH)}
    pub = {r["id"]: r for r in read_jsonl(PUBLISHED_PATH)}
    tfidf = {r["id"]: r for r in read_jsonl(TFIDF_PATH)}
    gold = test.set_index("id")
    ledger = read_jsonl(LEDGER_PATH)
    ids = [i for i in target_ids(test) if i in four]
    n = len(ids)

    def demo_label(rows, i, f):
        return rows[i]["labels"][f] if rows[i].get("labels") else INVALID

    def file_label(rows, i, f):
        v = rows[i].get(f)
        return v if v is not None else INVALID

    runs = {
        "4-bit, ZeroGPU (this run)": lambda i, f: demo_label(four, i, f),
        "bf16 merged, ZeroGPU": lambda i, f: demo_label(bf16, i, f),
    }
    agree_rows = []
    for name, get in runs.items():
        cells = []
        for f in FIELDS:
            k = sum(1 for i in ids if get(i, f) == file_label(pub, i, f))
            cells.append(f"{k} ({k / n:.2%})")
        k = sum(1 for i in ids if all(get(i, f) == file_label(pub, i, f) for f in FIELDS))
        agree_rows.append([name, *cells, f"{k} ({k / n:.2%})"])

    f1_rows = []
    for f in FIELDS:
        y = [gold.at[i, f] for i in ids]
        f1_rows.append([
            f,
            f"{field_metrics(y, [file_label(pub, i, f) for i in ids])['macro_f1']:.4f}",
            f"{field_metrics(y, [demo_label(four, i, f) for i in ids])['macro_f1']:.4f}",
            f"{field_metrics(y, [demo_label(bf16, i, f) for i in ids])['macro_f1']:.4f}",
            f"{field_metrics(y, [file_label(tfidf, i, f) for i in ids])['macro_f1']:.4f}",
        ])

    invalid = {
        "4-bit, ZeroGPU": sum(1 for i in ids if not four[i].get("labels")),
        "bf16 merged, ZeroGPU": sum(1 for i in ids if not bf16[i].get("labels")),
        "published (4-bit, T4)": sum(1 for i in ids if any(pub[i].get(f) is None for f in FIELDS)),
    }
    call_rows = [[c["call"], c["n"], f"{c['load_ms']:.0f}", len(c["batch_ms"]),
                  f"{sum(c['batch_ms']) / len(c['batch_ms']):.0f}", f"{c['gpu_ms']:.0f}",
                  f"{c['client_wall_ms']:.0f}"] for c in ledger]
    total = spent_s(ledger)
    lines = [
        "# The published adapter config on ZeroGPU (4-bit): same 400 tickets\n",
        "Generated by `deploy/demo/measure_4bit.py`. Not part of `results/results.json`.\n",
        "**Three runs of the same adapter, compared on the same tickets:**",
        "- **Published** (`results/qlora-adapter-ckpt1500.predictions.jsonl`): 4-bit NF4 with double "
        "quant, adapter unmerged, float16 compute, batch 8, on a **Tesla T4**.",
        "- **4-bit, ZeroGPU (this run):** the same config through the same "
        "`load_model_and_tokenizer()` (compute dtype pinned to float16, adapter unmerged, batch 8), "
        "on **ZeroGPU (half an RTX Pro 6000 Blackwell)**. It came from a temporary endpoint on "
        "the local branch `probe/4bit-zerogpu`, never on master. The only remaining difference from "
        "the published run is the GPU hardware and its kernels.",
        "- **bf16 merged, ZeroGPU:** the demo's own setup: base unquantized in bfloat16, adapter "
        "merged, batch 16 (`reports/adapter_zerogpu_agreement.md`).",
        "",
        f"**Sample:** the first {n} tickets of the seed={SEED} shuffle of the test split, the same "
        f"order the bf16 run used. Run status: **{status}**.\n",
        "## Agreement with the published predictions\n",
        md_table(["run", "queue", "priority", "type", "all three"], agree_rows),
        "",
        "## Macro-F1 against gold labels (same tickets)\n",
        md_table(["field", "published (4-bit, T4)", "4-bit, ZeroGPU", "bf16 merged, ZeroGPU", "TF-IDF"], f1_rows),
        "",
        "## Invalid outputs (same tickets)\n",
        *[f"- {k}: {v} of {n}" for k, v in invalid.items()],
        "",
        "## Per-call latency of the 4-bit endpoint\n",
        "Every call loads and quantizes the model inside the GPU call (`load_ms`), because 4-bit "
        "quantization needs a real GPU and ZeroGPU gives none at module level. A visitor to a 4-bit "
        "demo would pay that load on every request.\n",
        md_table(["call", "tickets", "load_ms", "batches of 8", "mean batch_ms",
                  "gpu_ms (inside the call)", "client wall ms"], call_rows),
        "",
        "## GPU used today (conservative, client-side wall time)\n",
        f"- 4-bit calls: {sum(c['client_wall_ms'] for c in ledger) / 1000:.1f} s.",
        f"- **Today's total, including earlier step-29 calls: {total:.1f} s ({total / 60:.2f} min).** "
        f"Remaining margin to the 10-minute cap: {(CAP_S - total):.1f} s. This does not yet include the "
        "smoke test of the redeploy back to master.",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--max-calls", type=int, default=None)
    args = parser.parse_args()
    test = pd.read_parquet(REPO_ROOT / "data" / "processed" / "test.parquet")
    status = "report rebuilt from saved outputs" if args.report else measure(test, args.max_calls)
    print(f"STATUS: {status}")
    if read_jsonl(PRED_PATH):
        write_report(test, status)


if __name__ == "__main__":
    main()
