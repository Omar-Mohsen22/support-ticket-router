"""Step 15 -- fine-tuned QLoRA adapter predictor. Scores the adapter pushed to
the Hugging Face Hub during steps 07-14 (notebooks/train_qlora.ipynb) on the
same evaluation harness (evaluate.py) that scored the zero-shot API baseline
(api_predictor.py) and the TF-IDF baseline (tfidf_baseline.py), producing a
predictions JSONL in the exact format evaluate.py already reads:
    {"id", "queue", "priority", "type",
     "latency_ms", "input_tokens", "output_tokens", "cost_usd"}
Scoring itself is a separate step (run evaluate.py afterward), same as both
existing predictors -- this script only writes predictions.

Requires a CUDA GPU with bitsandbytes 4-bit support -- see requirements.txt
(torch/peft/bitsandbytes were added for this script specifically; the rest of
this project's local pipeline never needed a GPU stack). NOT executable in
this environment -- see PROGRESS.md's step-15 entry for what could and
couldn't be verified without one.

Base model, the adapter's Hub repo id, and the 4-bit quantization settings all
come from train/config.yaml -- the SAME file notebooks/train_qlora.ipynb reads
-- so there is exactly one place any of that can go stale, not two. Only the
inference-specific knobs (batch_size, max_new_tokens) are new, under
train/config.yaml's "Inference" section.

Prompt rendering matches training EXACTLY, not approximately:
  1. The same system message src/ticket_router/make_sft_dataset.py builds
     (imported directly from there, not re-typed a third time) + the ticket's
     `text` column verbatim as the user turn -- the identical
     system+user construction make_sft_dataset.py's "prompt" half uses.
  2. tokenizer.apply_chat_template(messages, tokenize=False,
     add_generation_prompt=True) to render to TEXT, THEN tokenizer(text,
     add_special_tokens=False) to tokenize that text separately. This is not
     a style choice: notebooks/train_qlora.ipynb hit real, reproducible bugs
     from apply_chat_template(tokenize=True) -- it silently returns something
     other than what the variable name implies, differently in different
     cells (PROGRESS.md's step-09 and step-13 entries: a dict-wrapped-in-dict
     `tokenizer.pad()` crash, and a token-list prefix mismatch that failed on
     a real Colab run). Rendering to text first and tokenizing the text is
     the pattern the notebook settled on after both of those, and this
     script uses the identical pattern for the identical reason: any drift
     between the training prompt and the inference prompt here would
     silently degrade accuracy without ever raising an error.

Generation is batched with LEFT padding (required for batched generation --
every row's real content must end at the same position so the model
continues from a shared boundary across the batch; training used RIGHT
padding, dynamic per batch -- see train/config.yaml's "Padding" comment --
which is irrelevant here since this script never trains). Deterministic
(do_sample=False) so repeated runs -- and comparisons against the other two
predictors -- are not noise.

Invalid outputs (unparseable JSON, or failing TicketLabels validation) are
recorded as invalid and counted -- NEVER retried or repaired. Unlike
api_predictor.py's content-validation retries, this predictor gets exactly
one generation attempt per ticket: the invalid-output rate is one of the
harness's reported metrics, and silently repairing/retrying here would
falsify what that rate is actually measuring for a real deployment of this
model.

Caching follows api_predictor.py's pattern: one cache file per ticket under
.cache/adapter_predictor/, keyed by a hash of (adapter repo id, the exact
rendered prompt text, ticket id) -- a re-run over the same rows replays
cached tickets for free. The output JSONL is written and flushed as each
batch completes, not buffered until the end, so a crash or disconnect loses
at most the batch in flight, not the whole run -- and metrics can be
recomputed later (evaluate.py) without touching the model again.

cost_usd is null for every row, on purpose (same convention as
api_predictor.py's OpenAI rows, for the same reason): self-hosted GPU
inference has a real cost, but this script has no idea what GPU it's running
on or what that GPU costs per hour, so guessing would be worse than being
explicit that it's unknown. input_tokens/output_tokens/latency_ms below are
real and can be used to compute a $ figure externally against whatever GPU
this actually runs on.

Run from the repo root (needs a CUDA GPU + bitsandbytes -- untested here):
    .venv\\Scripts\\python.exe src\\ticket_router\\predictors\\adapter_predictor.py \\
        --split test --run-name adapter-qlora
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

# Make `ticket_router` importable when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import torch
import yaml
from peft import PeftModel
from pydantic import ValidationError
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from ticket_router.hf_auth import load_hf_token  # step 31: moved out so tests can cover it without torch
from ticket_router.make_sft_dataset import build_system_message
from ticket_router.run_meta import write_run_meta
from ticket_router.schema import TicketLabels

REPO_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RESULTS_DIR = REPO_ROOT / "results"
LABEL_MAP_PATH = PROCESSED_DIR / "label_map.json"
CONFIG_PATH = REPO_ROOT / "train" / "config.yaml"
CACHE_DIR = REPO_ROOT / ".cache" / "adapter_predictor"

TARGET_FIELDS = ["queue", "priority", "type"]

# A fixed historical fact about how THIS adapter (train/config.yaml's hub_model_id) was
# trained -- not an inference knob, so it lives here rather than in train/config.yaml's
# "inference" section. Recorded in run_meta (see main()) so report.py can show it: this
# predictor's inference-time cost_usd is null/0 (see the module docstring), and without this
# number sitting next to it, that 0 reads as "free" -- it is not. 3.35 hours = 3h21m,
# measured on the Colab T4 run that produced checkpoint-1500 (see PROGRESS.md's step-07
# through step-15 entries). Update this if the adapter is ever retrained.
TRAINING_GPU_HOURS = 3.35
TRAINING_HARDWARE = "Tesla T4 (Google Colab, free tier)"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"{CONFIG_PATH} not found.")
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def load_label_map() -> dict:
    if not LABEL_MAP_PATH.exists():
        raise FileNotFoundError(f"{LABEL_MAP_PATH} not found. Run make_dataset.py first.")
    return json.loads(LABEL_MAP_PATH.read_text(encoding="utf-8"))


def pick_compute_dtype() -> torch.dtype:
    """Same runtime GPU-capability check as notebooks/train_qlora.ipynb's cell 1
    (GPU check): bfloat16 on Ampere-or-newer (CUDA compute capability major
    >= 8), float16 otherwise. Hardcoding either would be silently wrong on
    whichever GPU this actually runs on -- the notebook already hit exactly
    this class of bug with a T4 (no bf16 support; see PROGRESS.md's step-07
    and step-12 entries)."""
    if not torch.cuda.is_available():
        raise RuntimeError(
            "No CUDA GPU detected -- adapter_predictor.py requires one for 4-bit QLoRA inference."
        )
    major, minor = torch.cuda.get_device_capability(0)
    dtype = torch.bfloat16 if major >= 8 else torch.float16
    print(f"GPU: {torch.cuda.get_device_name(0)} (compute capability {major}.{minor}) "
          f"-> compute dtype {dtype}")
    return dtype


def load_model_and_tokenizer(config: dict, compute_dtype: torch.dtype, hf_token: str | None):
    base_model_id = config["base_model"]
    adapter_repo_id = config["hub_model_id"]

    tokenizer = AutoTokenizer.from_pretrained(base_model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    # Batched generation requires LEFT padding: every row's real content must end at the
    # same position so the model continues generating from one shared boundary across the
    # batch. Training used RIGHT padding (dynamic per-batch -- see train/config.yaml's
    # "Padding" comment); irrelevant here, since this script never trains, only generates.
    tokenizer.padding_side = "left"

    q = config["quantization"]
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=q["load_in_4bit"],
        bnb_4bit_quant_type=q["bnb_4bit_quant_type"],
        bnb_4bit_compute_dtype=compute_dtype,  # decided at runtime -- see pick_compute_dtype()
        bnb_4bit_use_double_quant=q["bnb_4bit_use_double_quant"],
    )
    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_id, quantization_config=bnb_config, device_map="auto",
        dtype=compute_dtype, token=hf_token,
    )
    print(f"Loading adapter from {adapter_repo_id!r} ...")
    model = PeftModel.from_pretrained(base_model, adapter_repo_id, token=hf_token)
    model.eval()
    return model, tokenizer


def render_prompt(ticket_text: str, system_message: str, tokenizer) -> str:
    """The exact system+user construction make_sft_dataset.py's "prompt" half
    uses (build_system_message imported directly from there -- not re-typed),
    rendered to TEXT via apply_chat_template(tokenize=False,
    add_generation_prompt=True). See the module docstring for why text-first,
    not apply_chat_template(tokenize=True)."""
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": ticket_text},
    ]
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def cache_key_for(adapter_repo_id: str, prompt_text: str, ticket_id: str) -> str:
    payload = json.dumps(
        {"adapter": adapter_repo_id, "prompt": prompt_text, "ticket_id": ticket_id}, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_and_validate(generated_text: str) -> tuple[TicketLabels | None, str | None]:
    """Returns (labels_or_None, error_or_None). Exactly one attempt -- never
    retried, never repaired. See the module docstring for why: the
    invalid-output rate is one of the harness's reported metrics."""
    try:
        parsed = json.loads(generated_text)
    except json.JSONDecodeError as e:
        return None, f"JSONDecodeError: {e}"
    try:
        # parsed can be valid JSON that isn't an object (e.g. a bare string or a list) --
        # TypeError from `**parsed` in that case, same as api_predictor.py's process_ticket
        # guards against, not just ValidationError.
        return TicketLabels(**parsed), None
    except (TypeError, ValidationError) as e:
        return None, f"{type(e).__name__}: {e}"


def generate_batch(model, tokenizer, prompts: list[str], max_seq_len: int, max_new_tokens: int):
    """One batched, deterministic (do_sample=False) generate() call.

    Returns (decoded_completions, input_tokens_per_row, output_tokens_per_row,
    batch_elapsed_ms). Token counts are the REAL per-row lengths -- excluding
    left-padding on the prompt side and excluding the pad_token_id filled in
    for rows that finished generating before others in the batch -- not just
    max_seq_len/max_new_tokens repeated for every row.
    """
    encoded = tokenizer(
        prompts, truncation=True, max_length=max_seq_len, add_special_tokens=False,
        padding=True, return_tensors="pt",
    ).to(model.device)

    t0 = time.perf_counter()
    with torch.no_grad():
        out_ids = model.generate(
            **encoded,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
        )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    prompt_len = encoded["input_ids"].shape[1]  # identical for every row -- LEFT padding
    completion_ids = out_ids[:, prompt_len:]

    input_tokens_per_row = encoded["attention_mask"].sum(dim=1).tolist()
    pad_id = tokenizer.pad_token_id
    output_tokens_per_row = []
    decoded = []
    for row_ids in completion_ids:
        row_list = row_ids.tolist()
        real_len = row_list.index(pad_id) if pad_id in row_list else len(row_list)
        output_tokens_per_row.append(real_len)
        decoded.append(tokenizer.decode(row_ids[:real_len], skip_special_tokens=True).strip())

    return decoded, input_tokens_per_row, output_tokens_per_row, elapsed_ms


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["train", "val", "test"], default="test")
    parser.add_argument("--limit", type=int, default=None,
                         help="Only predict the first N rows of the split (omit for the full split)")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--output", type=Path, default=None,
                         help="Defaults to results/<run-name>.predictions.jsonl")
    args = parser.parse_args()

    config = load_config()
    hf_token = load_hf_token()
    label_map = load_label_map()
    system_message = build_system_message(label_map)

    split_path = PROCESSED_DIR / f"{args.split}.parquet"
    if not split_path.exists():
        print(f"STOP: {split_path} not found. Run make_dataset.py first.")
        raise SystemExit(1)
    df = pd.read_parquet(split_path)
    if args.limit is not None:
        df = df.head(args.limit)

    compute_dtype = pick_compute_dtype()
    model, tokenizer = load_model_and_tokenizer(config, compute_dtype, hf_token)

    batch_size = config["inference"]["batch_size"]
    max_new_tokens = config["inference"]["max_new_tokens"]
    max_seq_len = config["max_seq_len"]
    adapter_repo_id = config["hub_model_id"]

    output_path = args.output or (RESULTS_DIR / f"{args.run_name}.predictions.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\nSplit: {args.split}  |  Rows: {len(df)}  |  Batch size: {batch_size}  "
          f"|  Adapter: {adapter_repo_id}")
    print(f"Output: {output_path}")
    print(f"Cache dir: {CACHE_DIR}\n")
    print("NOTE: cost_usd is null for every row -- self-hosted GPU inference has a real cost "
          "this script has no way to know (which GPU, what it costs per hour). "
          "input_tokens/output_tokens/latency_ms are real; compute cost externally from those.\n")

    rows = df.to_dict("records")
    n_cached = 0
    n_fresh = 0
    n_invalid = 0

    with open(output_path, "w", encoding="utf-8") as out_f:
        for batch_start in range(0, len(rows), batch_size):
            batch_rows = rows[batch_start: batch_start + batch_size]

            # Per-ticket disk cache, same pattern as api_predictor.py's call_with_cache:
            # keyed by a hash of (adapter, exact rendered prompt, ticket id), so a re-run
            # over the same rows replays already-generated tickets for free and only spends
            # GPU time on the ones actually missing.
            to_generate = []   # (row, prompt_text, cache_path)
            results_by_id = {}
            for row in batch_rows:
                prompt_text = render_prompt(row["text"], system_message, tokenizer)
                key = cache_key_for(adapter_repo_id, prompt_text, row["id"])
                cache_path = CACHE_DIR / f"{key}.json"
                if cache_path.exists():
                    results_by_id[row["id"]] = json.loads(cache_path.read_text(encoding="utf-8"))
                else:
                    to_generate.append((row, prompt_text, cache_path))

            n_cached += len(batch_rows) - len(to_generate)

            if to_generate:
                prompts = [p for _, p, _ in to_generate]
                decoded, in_toks, out_toks, batch_ms = generate_batch(
                    model, tokenizer, prompts, max_seq_len, max_new_tokens
                )
                per_row_ms = batch_ms / len(to_generate)
                for (row, _prompt, cache_path), text, n_in, n_out in zip(
                    to_generate, decoded, in_toks, out_toks
                ):
                    labels, error = parse_and_validate(text)
                    result = {
                        **{field: (getattr(labels, field) if labels else None) for field in TARGET_FIELDS},
                        "latency_ms": per_row_ms,
                        "input_tokens": n_in,
                        "output_tokens": n_out,
                    }
                    if error:
                        result["error"] = error
                    cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                    results_by_id[row["id"]] = result
                n_fresh += len(to_generate)

            # Write every row in this batch to disk NOW, not buffered until the whole run
            # finishes -- so a crash or disconnect loses at most this one batch, and
            # results/<run-name>.predictions.jsonl is always complete and scoreable for
            # every row processed so far.
            for row in batch_rows:
                result = results_by_id[row["id"]]
                out_row = {"id": row["id"], **{f: result[f] for f in
                    (*TARGET_FIELDS, "latency_ms", "input_tokens", "output_tokens")}}
                out_row["cost_usd"] = None  # self-hosted -- see module docstring
                if "error" in result:
                    out_row["error"] = result["error"]
                    n_invalid += 1
                out_f.write(json.dumps(out_row, ensure_ascii=False) + "\n")
            out_f.flush()

            done = batch_start + len(batch_rows)
            print(f"  {done}/{len(rows)} done  (cached={n_cached}, fresh={n_fresh}, invalid={n_invalid})")

    print(f"\nWrote {len(rows)} predictions to {output_path}")
    print(f"Cached (free) tickets: {n_cached}  |  Freshly generated: {n_fresh}  |  "
          f"Invalid (not retried): {n_invalid}")

    # hardware is the ACTUAL device this inference run happened on, read at runtime -- not
    # necessarily the same GPU the adapter was trained on (TRAINING_GPU_HOURS/TRAINING_HARDWARE
    # above are about training, a separate, already-finished, fixed-cost event).
    meta_path = write_run_meta(
        args.run_name, cost_basis="gpu-local", hardware=torch.cuda.get_device_name(0),
        training_cost={
            "gpu_hours": TRAINING_GPU_HOURS,
            "note": (
                f"{TRAINING_GPU_HOURS} GPU-hour(s) on {TRAINING_HARDWARE} to train this adapter "
                "(hub_model_id in train/config.yaml). The $0 training cost is because the free "
                "tier absorbed it, not because training itself was free -- and this is a "
                "one-time cost, separate from what serving each prediction below costs."
            ),
        },
    )
    print(f"Wrote {meta_path}")


if __name__ == "__main__":
    main()
