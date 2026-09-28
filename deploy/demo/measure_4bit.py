"""Step 29 -- the evaluated adapter config (4-bit) on ZeroGPU, compared with the published
predictions, the bf16 demo run and TF-IDF on the same tickets.

Two runs, selected with --run:
- full (default): all 1,633 test tickets through /predict_batch on the deployed MASTER demo,
  which since commit 85feb19 serves the evaluated config.
- probe400: the first 400 tickets, measured on 2026-09-27 through the temporary
  /predict_batch_4bit endpoint (branch probe/4bit-zerogpu, commit 629c12c). That endpoint no
  longer exists, so this run can only rebuild its report (--report).

Both endpoints load the model with adapter_predictor.load_model_and_tokenizer(): 4-bit NF4 with
double quant (train/config.yaml), the adapter unmerged, the compute dtype pinned to float16
(what pick_compute_dtype() chose on the T4), and generation in batches of 8. The model is
loaded inside every GPU call.

Budget (conservative count: client-side wall time per call, plus everything used earlier the
same day):
- full: cap 20 minutes, hard stop at 19.5 minutes, gate at ~10% (164 tickets).
- probe400: cap 10 minutes, hard stop at 9.5 minutes, gate at 40 tickets.
Outputs are appended after every call, and a rerun resumes from them. results.json is never
touched.

Run from the repo root (needs HF_SPACE_TOKEN in .env; the token is never printed):
    python deploy/demo/measure_4bit.py                          (full run: measure or resume, then report)
    python deploy/demo/measure_4bit.py --report                 (rebuild the full-run report)
    python deploy/demo/measure_4bit.py --run probe400 --report  (rebuild the 400-ticket report)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ticket_router.metrics import INVALID, field_metrics, md_table  # noqa: E402

SPACE_ID = "Omar-Mohsen22/support-ticket-router-demo"
SEED = 29
EVAL_BATCH = 8
FIELDS = ["queue", "priority", "type"]
OUT = REPO_ROOT / "reports"
BF16_PATH = OUT / "adapter_zerogpu_agreement.predictions.jsonl"
PUBLISHED_PATH = REPO_ROOT / "results" / "qlora-adapter-ckpt1500.predictions.jsonl"
TFIDF_PATH = REPO_ROOT / "results" / "tfidf-baseline.predictions.jsonl"


@dataclass(frozen=True)
class Run:
    name: str
    api_name: str
    n_tickets: int
    call_plan: tuple[int, ...]      # tickets per call; the last value repeats
    cap_s: float
    hard_stop_s: float
    gate_after: int
    prior_s: float                  # conservative GPU seconds used earlier that day
    prefix: str
    endpoint_note: str


RUNS = {
    "full": Run(
        name="full", api_name="/predict_batch", n_tickets=1633,
        call_plan=(16, 96), cap_s=20 * 60, hard_stop_s=19.5 * 60, gate_after=164,
        # Omar's figure for today (2026-09-27 ledger, PROGRESS.md): 229.3 s plus the 4.8 s smoke
        # test of the push that shipped the 4-bit demo. Counted even if the quota window has
        # rolled over since, which is the conservative choice.
        prior_s=229.3 + 4.788,
        prefix="adapter_zerogpu_4bit_full",
        endpoint_note="the deployed master demo's `/predict_batch` (commit `85feb19`), which serves "
                      "the evaluated config",
    ),
    "probe400": Run(
        name="probe400", api_name="/predict_batch_4bit", n_tickets=400,
        call_plan=(8, 32, 90), cap_s=10 * 60, hard_stop_s=9.5 * 60, gate_after=40,
        prior_s=149.2 + 2.281,
        prefix="adapter_zerogpu_4bit",
        endpoint_note="a temporary `/predict_batch_4bit` endpoint on the local branch "
                      "`probe/4bit-zerogpu` (commit `629c12c`), never on master",
    ),
}


def paths(run: Run) -> tuple[Path, Path, Path]:
    return (OUT / f"{run.prefix}.predictions.jsonl", OUT / f"{run.prefix}.ledger.jsonl",
            OUT / f"{run.prefix}.md")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def target_ids(test: pd.DataFrame, n: int) -> list[str]:
    order = [test["id"].iloc[i] for i in np.random.default_rng(SEED).permutation(len(test))]
    return order[:n]


def n_batches(entry: dict) -> int:
    return len(entry["batch_ms"]) if "batch_ms" in entry else entry["batches"]


def gen_ms(entry: dict) -> float:
    """Generation time inside the call: the per-batch sum where recorded (probe400), otherwise
    the call's GPU time minus the model load (full)."""
    return sum(entry["batch_ms"]) if "batch_ms" in entry else entry["gpu_ms"] - entry["load_ms"]


def spent_s(run: Run, ledger: list[dict]) -> float:
    return run.prior_s + sum(c["client_wall_ms"] for c in ledger) / 1000


def estimate_call_s(ledger: list[dict], n: int) -> float:
    """Client wall time = per-call overhead (model load, allocation, queue, network) plus the
    batches of 8. Both parts are fitted from the calls so far."""
    overhead = sum(c["client_wall_ms"] - gen_ms(c) for c in ledger) / len(ledger)
    per_batch = sum(gen_ms(c) for c in ledger) / sum(n_batches(c) for c in ledger)
    return (overhead + per_batch * math.ceil(n / EVAL_BATCH)) / 1000


def call_size(run: Run, k: int, remaining: int) -> int:
    return min(run.call_plan[k] if k < len(run.call_plan) else run.call_plan[-1], remaining)


def projected_total(run: Run, ledger: list[dict], remaining: int) -> float:
    total, k = spent_s(run, ledger), len(ledger)
    while remaining > 0:
        m = call_size(run, k, remaining)
        total += estimate_call_s(ledger, m)
        remaining, k = remaining - m, k + 1
    return total


def measure(run: Run, test: pd.DataFrame, max_calls: int | None) -> str:
    from dotenv import load_dotenv
    from gradio_client import Client

    pred_path, ledger_path, _ = paths(run)
    load_dotenv(REPO_ROOT / ".env", override=True)
    client = Client(SPACE_ID, token=os.environ["HF_SPACE_TOKEN"], verbose=False)
    by_id = test.set_index("id")
    done = {r["id"] for r in read_jsonl(pred_path)}
    ledger = read_jsonl(ledger_path)
    todo = [i for i in target_ids(test, run.n_tickets) if i not in done]
    gate_checked = len(done) >= run.gate_after
    calls_this_run = 0
    print(f"run={run.name} api={run.api_name} seed={SEED} target={run.n_tickets} done={len(done)} "
          f"todo={len(todo)} spent={spent_s(run, ledger):.1f}s")

    while todo:
        if max_calls is not None and calls_this_run >= max_calls:
            return f"paused after {calls_this_run} call(s) (--max-calls)"
        n = call_size(run, len(ledger), len(todo))
        if ledger:
            est = estimate_call_s(ledger, n)
            if spent_s(run, ledger) + est > run.hard_stop_s:
                return (f"hard stop: the next call ({n} tickets, ~{est:.0f} s) would pass "
                        f"{run.hard_stop_s / 60:.1f} conservative minutes")
        ids, todo = todo[:n], todo[n:]
        payload = [{"id": i, "subject": by_id.at[i, "subject"] if isinstance(by_id.at[i, "subject"], str) else None,
                    "body": by_id.at[i, "body"]} for i in ids]
        t0 = time.perf_counter()
        try:
            out = json.loads(client.predict(json.dumps(payload), api_name=run.api_name))
        except Exception as e:  # report the exact error, never retry into more GPU use
            return f"stopped on an error from the Space: {type(e).__name__}: {str(e)[:500]}"
        wall = (time.perf_counter() - t0) * 1000
        append_jsonl(pred_path, out["results"])
        entry = {"call": len(ledger), "n": n, "batches": math.ceil(n / EVAL_BATCH),
                 "load_ms": out["load_ms"], "gpu_ms": out["gpu_ms"], "client_wall_ms": wall}
        append_jsonl(ledger_path, [entry])
        ledger.append(entry)
        calls_this_run += 1
        print(f"call {entry['call']}: n={n} load={out['load_ms']:.0f}ms "
              f"gen/batch={gen_ms(entry) / entry['batches']:.0f}ms gpu={out['gpu_ms']:.0f}ms "
              f"wall={wall:.0f}ms | spent={spent_s(run, ledger):.1f}s", flush=True)

        processed = len(read_jsonl(pred_path))
        if not gate_checked and processed >= run.gate_after:
            gate_checked = True
            projected = projected_total(run, ledger, len(todo))
            print(f"GATE at {processed} tickets: projected conservative total {projected / 60:.2f} min "
                  f"(cap {run.cap_s / 60:.0f})")
            if projected > run.cap_s:
                return f"gate: projected {projected / 60:.2f} min exceeds the {run.cap_s / 60:.0f}-min cap"
    return "completed"


def write_report(run: Run, test: pd.DataFrame, status: str) -> None:
    pred_path, ledger_path, report_path = paths(run)
    four = {r["id"]: r for r in read_jsonl(pred_path)}
    bf16 = {r["id"]: r for r in read_jsonl(BF16_PATH)}
    pub = {r["id"]: r for r in read_jsonl(PUBLISHED_PATH)}
    tfidf = {r["id"]: r for r in read_jsonl(TFIDF_PATH)}
    gold = test.set_index("id")
    ledger = read_jsonl(ledger_path)
    ids = [i for i in target_ids(test, run.n_tickets) if i in four]
    n = len(ids)

    def demo_label(rows, i, f):
        return rows[i]["labels"][f] if rows[i].get("labels") else INVALID

    def file_label(rows, i, f):
        v = rows[i].get(f)
        return v if v is not None else INVALID

    runs = {
        "4-bit, ZeroGPU (this run)": lambda i, f: demo_label(four, i, f),
        "bf16 merged, ZeroGPU (earlier run)": lambda i, f: demo_label(bf16, i, f),
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
        "4-bit, ZeroGPU (this run)": sum(1 for i in ids if not four[i].get("labels")),
        "bf16 merged, ZeroGPU": sum(1 for i in ids if not bf16[i].get("labels")),
        "published (4-bit, T4)": sum(1 for i in ids if any(pub[i].get(f) is None for f in FIELDS)),
    }
    call_rows = [[c["call"], c["n"], f"{c['load_ms']:.0f}", n_batches(c),
                  f"{gen_ms(c) / n_batches(c):.0f}", f"{c['gpu_ms']:.0f}",
                  f"{c['client_wall_ms']:.0f}"] for c in ledger]
    total = spent_s(run, ledger)
    this_run = sum(c["client_wall_ms"] for c in ledger) / 1000
    margin_lines = [f"Remaining margin to this run's {run.cap_s / 60:.0f}-minute cap: {run.cap_s - total:.1f} s."]
    if run.name == "full":
        margin_lines.append(f"Remaining margin to the 40-minute free PRO daily quota: {40 * 60 - total:.1f} s.")
    lines = [
        f"# The evaluated adapter config on ZeroGPU (4-bit): {n} test tickets\n",
        f"Generated by `deploy/demo/measure_4bit.py --run {run.name}`. Not part of `results/results.json`.\n",
        "**Three runs of the same adapter, compared on the same tickets:**",
        "- **Published** (`results/qlora-adapter-ckpt1500.predictions.jsonl`): 4-bit NF4 with double "
        "quant, adapter unmerged, float16 compute, batch 8, on a **Tesla T4**.",
        "- **4-bit, ZeroGPU (this run):** the same config through the same "
        "`load_model_and_tokenizer()` (float16 compute pinned, adapter unmerged, batch 8), on "
        f"**ZeroGPU (half an RTX Pro 6000 Blackwell)**, via {run.endpoint_note}.",
        "- **bf16 merged, ZeroGPU (earlier run):** the demo's first setup: base unquantized in "
        "bfloat16, adapter merged, batch 16 (`reports/adapter_zerogpu_agreement.md`).",
        "",
        f"**Sample:** the first {n} tickets of the seed={SEED} shuffle of the test split "
        f"({len(test)} tickets), the order all of these runs used. Run status: **{status}**.\n",
        "## Agreement with the published predictions\n",
        md_table(["run", "queue", "priority", "type", "all three"], agree_rows),
        "",
        "## Macro-F1 against gold labels (same tickets)\n",
        md_table(["field", "published (4-bit, T4)", "4-bit, ZeroGPU", "bf16 merged, ZeroGPU", "TF-IDF"], f1_rows),
        "",
        "## Invalid outputs (same tickets)\n",
        *[f"- {k}: {v} of {n}" for k, v in invalid.items()],
        "",
        "## Per-call latency\n",
        "Every call loads and quantizes the 4-bit model inside the GPU call (`load_ms`), because "
        "4-bit quantization needs a real GPU and ZeroGPU gives none at module level.\n",
        md_table(["call", "tickets", "load_ms", "batches of 8", "mean generation ms per batch",
                  "gpu_ms (inside the call)", "client wall ms"], call_rows),
        "",
        "## GPU used (conservative: client-side wall time)\n",
        f"- This run's calls: {this_run:.1f} s.",
        f"- **Total for the day, including earlier calls: {total:.1f} s ({total / 60:.2f} min).** "
        + " ".join(margin_lines),
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", choices=sorted(RUNS), default="full")
    parser.add_argument("--report", action="store_true", help="Only rebuild the report.")
    parser.add_argument("--max-calls", type=int, default=None)
    args = parser.parse_args()
    run = RUNS[args.run]
    if run.name == "probe400" and not args.report:
        raise SystemExit("STOP: the probe400 endpoint no longer exists; use --report to rebuild its report.")
    test = pd.read_parquet(REPO_ROOT / "data" / "processed" / "test.parquet")
    status = "report rebuilt from saved outputs" if args.report else measure(run, test, args.max_calls)
    print(f"STATUS: {status}")
    if read_jsonl(paths(run)[0]):
        write_report(run, test, status)


if __name__ == "__main__":
    main()
