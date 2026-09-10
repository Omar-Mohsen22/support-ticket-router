"""Step 06 -- convert the processed splits into a provider-agnostic
instruction-tuning (SFT) chat format for QLoRA fine-tuning of an open-weights
model on Colab (self-hosted afterward -- see data/README.md-style reasoning
in README.md's "Next steps"). This is NOT OpenAI fine-tuning: fine-tuning a
hosted API model would make the self-hosted-vs-API cost comparison this
project is built around meaningless, so it was deliberately not done (see
README.md).

Reads data/processed/{train,val,test}.parquet and label_map.json, and writes
data/processed/sft/{train,val,test}.jsonl -- one {"messages": [...]} object
per line (system + user + assistant turns, as role/content dicts). This is a
MESSAGE LIST, not a pre-rendered string: the target model's own chat template
(Jinja2, shipped with its tokenizer) is applied at training time via
`tokenizer.apply_chat_template(example["messages"], tokenize=True)`, so the
file itself carries no model-specific special tokens or formatting baked in.

Each example:
  - system (identical across all examples): states the task and lists every
    allowed value per field, from label_map.json (the same single source of
    truth used by schema.py and api_predictor.py elsewhere in this project).
  - user: the ticket's `text` column, verbatim.
  - assistant: MINIFIED JSON (json.dumps(..., separators=(",", ":")), no
    whitespace) with keys in the fixed order queue, priority, type -- the
    same order used throughout the codebase (schema.py's TicketLabels,
    metrics.py's TARGET_FIELDS).

Fine-tuning target model: FT_BASE_MODEL, read from .env, defaulting to
Qwen/Qwen2.5-1.5B-Instruct (public, apache-2.0, not gated -- confirmed via
the HF API before picking it: `gated: false`). This is a SEPARATE config
from OPENAI_MODEL (used by api_predictor.py for the zero-shot/few-shot API
baselines) -- the two must never be conflated, which is exactly the mistake
this version of the script corrects (a prior version used OPENAI_MODEL/
tiktoken for the token-length analysis, which does not describe how the
actual fine-tuning target model tokenizes anything).

Token-length histogram, recommended max_seq_len, and truncation counts use
FT_BASE_MODEL's own tokenizer and chat template (transformers' AutoTokenizer
+ apply_chat_template(tokenize=True)) -- the number that actually matters for
training. OPENAI_MODEL's tiktoken-based counts are also computed, ONLY for a
side-by-side comparison showing how much the two tokenizers disagree; they do
not inform the max_seq_len recommendation.

Run from the repo root:
    .venv\\Scripts\\python.exe src\\ticket_router\\make_sft_dataset.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Make `ticket_router` importable when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from dotenv import load_dotenv
from transformers import AutoTokenizer

from ticket_router.metrics import percentile

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
SFT_DIR = PROCESSED_DIR / "sft"
LABEL_MAP_PATH = PROCESSED_DIR / "label_map.json"
REPORTS_DIR = REPO_ROOT / "reports"
SAMPLES_PATH = REPORTS_DIR / "sft_samples.md"
ENV_PATH = REPO_ROOT / ".env"

# The actual fine-tuning target: an open-weights, self-hostable model, QLoRA
# fine-tuned on Colab -- deliberately NOT OpenAI's API (see module docstring
# and README.md "Next steps"). Separate config key from OPENAI_MODEL on
# purpose: conflating "the model used for zero-shot/few-shot baselines" with
# "the model being fine-tuned" was exactly the bug being fixed here.
DEFAULT_FT_BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"

# Fixed key order for the assistant's minified JSON -- matches
# schema.py's TicketLabels field order and metrics.py's TARGET_FIELDS.
TARGET_FIELDS = ["queue", "priority", "type"]
SPLITS = ["train", "val", "test"]
N_SAMPLES_TO_SHOW = 5
MAX_SEQ_LEN_PERCENTILE = 95
ROUND_MAX_SEQ_LEN_TO = 32  # round the recommended max_seq_len up to the nearest multiple of this


def load_label_map() -> dict:
    if not LABEL_MAP_PATH.exists():
        raise FileNotFoundError(f"{LABEL_MAP_PATH} not found. Run make_dataset.py first.")
    return json.loads(LABEL_MAP_PATH.read_text(encoding="utf-8"))


def build_system_message(label_map: dict) -> str:
    return (
        "You are a support-ticket routing classifier. Given a ticket's text, output ONLY a "
        "single, compact JSON object (no extra whitespace) with exactly these three keys, in "
        "this order: queue, priority, type.\n\n"
        f"queue must be exactly one of: {json.dumps(label_map['queue'])}\n"
        f"priority must be exactly one of: {json.dumps(label_map['priority'])}\n"
        f"type must be exactly one of: {json.dumps(label_map['type'])}"
    )


def build_assistant_content(row: pd.Series) -> str:
    obj = {field: row[field] for field in TARGET_FIELDS}
    return json.dumps(obj, separators=(",", ":"))  # minified, fixed key order


def build_example(row: pd.Series, system_message: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": row["text"]},
            {"role": "assistant", "content": build_assistant_content(row)},
        ]
    }


def get_ft_base_model() -> str:
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    return os.environ.get("FT_BASE_MODEL") or DEFAULT_FT_BASE_MODEL


def get_openai_comparison_model() -> str | None:
    """Best-effort only -- OPENAI_MODEL is used purely for the side-by-side
    tokenizer comparison, never for the max_seq_len recommendation. Returns
    None (comparison skipped, not a STOP) if unset or tiktoken doesn't know it."""
    model = os.environ.get("OPENAI_MODEL")
    if not model:
        return None
    try:
        import tiktoken
        tiktoken.encoding_for_model(model)
    except (ImportError, KeyError):
        return None
    return model


def num_tokens_openai(messages: list[dict], model: str) -> int:
    """OpenAI's published token-counting formula for chat messages (from the
    openai-cookbook "How to count tokens with tiktoken" notebook)."""
    import tiktoken
    encoding = tiktoken.encoding_for_model(model)
    tokens_per_message = 3
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for value in message.values():
            num_tokens += len(encoding.encode(value))
    num_tokens += 3
    return num_tokens


def num_tokens_target(messages: list[dict], tokenizer) -> int:
    """Token count using the ACTUAL fine-tuning target's own tokenizer and
    chat template -- this is the number that determines a real max_seq_len.
    return_dict=False is required: with the default (return_dict=True),
    apply_chat_template(tokenize=True) returns a BatchEncoding whose len() is
    the number of keys ('input_ids', 'attention_mask' -> 2), not the token
    count -- caught by hand-testing before this shipped in the script."""
    ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False,
                                         return_dict=False)
    return len(ids)


def print_histogram(lengths: list[int], n_buckets: int = 20) -> None:
    lo, hi = min(lengths), max(lengths)
    width = max(1, -(-(hi - lo + 1) // n_buckets))
    buckets: dict[int, int] = {}
    for length in lengths:
        bucket = lo + ((length - lo) // width) * width
        buckets[bucket] = buckets.get(bucket, 0) + 1
    max_count = max(buckets.values())
    for bucket in sorted(buckets):
        count = buckets[bucket]
        bar = "#" * max(1, round(count / max_count * 50))
        print(f"  {bucket:6d}-{bucket + width - 1:<6d} tokens | {bar} {count}")


def write_samples_report(sample_examples: list[dict], sample_lengths_target: list[int],
                          sample_rows: list[pd.Series], system_message: str, ft_base_model: str,
                          tokenizer, recommended_max_seq_len: int,
                          train_lengths_target: list[int], train_lengths_openai: list[int] | None,
                          openai_model: str | None) -> None:
    lines = ["# SFT format samples\n"]
    lines.append(
        f"**Fine-tuning target model: `{ft_base_model}`** (QLoRA on Colab, self-hosted "
        "afterward -- see README.md \"Next steps\" for why this is not an OpenAI fine-tune). "
        f"{len(sample_examples)} formatted examples from `data/processed/sft/train.jsonl`, shown "
        "in full so the format can be read directly. Token counts below use "
        f"`{ft_base_model}`'s own tokenizer and chat template "
        "(`tokenizer.apply_chat_template(...)`), not an OpenAI tokenizer.\n"
    )

    lines.append("## System message (identical for every example)\n")
    lines.append("```\n" + system_message + "\n```\n")

    for i, (ex, length, row) in enumerate(
            zip(sample_examples, sample_lengths_target, sample_rows), start=1):
        user_msg = ex["messages"][1]["content"]
        assistant_msg = ex["messages"][2]["content"]
        lines.append(f"## Example {i} -- ticket `{row['id']}` ({length} tokens, {ft_base_model})\n")
        lines.append("**User turn (ticket text):**\n")
        lines.append("```\n" + user_msg + "\n```\n")
        lines.append("**Assistant turn (minified JSON, fixed key order):**\n")
        lines.append("```\n" + assistant_msg + "\n```\n")
        lines.append(
            f"Gold labels: queue={row['queue']!r}, priority={row['priority']!r}, type={row['type']!r}\n"
        )
        lines.append(
            f"**Raw JSONL line (exact bytes written to the file -- a message list, not a "
            f"pre-rendered string; the target model's chat template is applied at training "
            f"time, not baked in here):**\n"
        )
        lines.append("```json\n" + json.dumps(ex, ensure_ascii=False) + "\n```\n")
        if i == 1:
            rendered = tokenizer.apply_chat_template(ex["messages"], tokenize=False,
                                                       add_generation_prompt=False)
            lines.append(
                f"**What `{ft_base_model}`'s chat template actually renders this to at training "
                "time (for reference only -- this rendered string is NOT what's stored in the "
                "JSONL file):**\n"
            )
            lines.append("```\n" + rendered + "\n```\n")

    lines.append("## Token-length summary (full train split)\n")
    lines.append(f"**Target model (`{ft_base_model}`) -- this is what the recommendation below is based on:**\n")
    lines.append(
        f"n={len(train_lengths_target)}, min={min(train_lengths_target)}, "
        f"p50={percentile(train_lengths_target, 50):.0f}, "
        f"p95={percentile(train_lengths_target, 95):.0f}, "
        f"p99={percentile(train_lengths_target, 99):.0f}, "
        f"max={max(train_lengths_target)}. Recommended `max_seq_len` = "
        f"**{recommended_max_seq_len}** (p95 rounded up to the nearest {ROUND_MAX_SEQ_LEN_TO}).\n"
    )
    if train_lengths_openai:
        lines.append(
            f"\n**For comparison only -- OpenAI `{openai_model}` via tiktoken (NOT the "
            "fine-tuning target, not used for the recommendation above):**\n"
        )
        lines.append(
            f"n={len(train_lengths_openai)}, min={min(train_lengths_openai)}, "
            f"p50={percentile(train_lengths_openai, 50):.0f}, "
            f"p95={percentile(train_lengths_openai, 95):.0f}, "
            f"p99={percentile(train_lengths_openai, 99):.0f}, "
            f"max={max(train_lengths_openai)}.\n"
        )
    lines.append(
        "\nFull histograms and per-split truncation counts are printed by the script and "
        "recorded in PROGRESS.md.\n"
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLES_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {len(sample_examples)} samples to {SAMPLES_PATH}")


def main() -> None:
    for split in SPLITS:
        p = PROCESSED_DIR / f"{split}.parquet"
        if not p.exists():
            print(f"STOP: {p} not found. Run make_dataset.py first.")
            raise SystemExit(1)

    label_map = load_label_map()
    system_message = build_system_message(label_map)

    ft_base_model = get_ft_base_model()
    print(f"Fine-tuning target model (FT_BASE_MODEL): {ft_base_model!r}")
    print("Loading its tokenizer (tokenizer/config files only -- no model weights, no training) ...")
    tokenizer = AutoTokenizer.from_pretrained(ft_base_model)
    print(f"  {type(tokenizer).__name__} loaded.\n")

    openai_model = get_openai_comparison_model()
    if openai_model:
        print(f"Comparison-only tokenizer: OpenAI {openai_model!r} via tiktoken "
              "(not the fine-tuning target).\n")
    else:
        print("No usable OPENAI_MODEL found for comparison -- skipping the side-by-side tiktoken "
              "numbers (this does not affect the recommendation, which is target-model-only).\n")

    SFT_DIR.mkdir(parents=True, exist_ok=True)

    split_lengths_target: dict[str, list[int]] = {}
    train_examples: list[dict] = []
    train_rows: list[pd.Series] = []
    train_lengths_openai: list[int] | None = [] if openai_model else None

    for split in SPLITS:
        df = pd.read_parquet(PROCESSED_DIR / f"{split}.parquet")
        examples = [build_example(row, system_message) for _, row in df.iterrows()]
        lengths = [num_tokens_target(ex["messages"], tokenizer) for ex in examples]
        split_lengths_target[split] = lengths

        out_path = SFT_DIR / f"{split}.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
        print(f"Wrote {len(examples)} examples to {out_path}")

        if split == "train":
            train_examples = examples
            train_rows = [row for _, row in df.iterrows()]
            if openai_model:
                train_lengths_openai = [num_tokens_openai(ex["messages"], openai_model)
                                         for ex in examples]

    train_lengths_target = split_lengths_target["train"]
    print(f"\n=== Train token-length histogram -- TARGET MODEL ({ft_base_model}, "
          f"{len(train_lengths_target)} examples) ===")
    print_histogram(train_lengths_target)

    if train_lengths_openai:
        print(f"\n=== Train token-length histogram -- COMPARISON ONLY: OpenAI {openai_model} "
              f"via tiktoken ({len(train_lengths_openai)} examples) ===")
        print_histogram(train_lengths_openai)

        print(f"\n=== Side by side (train, p50/p95/p99/max) ===")
        print(f"  {'model':<32s} p50   p95   p99   max")
        t50, t95, t99 = (percentile(train_lengths_target, p) for p in (50, 95, 99))
        o50, o95, o99 = (percentile(train_lengths_openai, p) for p in (50, 95, 99))
        print(f"  {ft_base_model:<32s} {t50:5.0f} {t95:5.0f} {t99:5.0f} {max(train_lengths_target):5d}  <- target, used below")
        print(f"  {openai_model + ' (tiktoken)':<32s} {o50:5.0f} {o95:5.0f} {o99:5.0f} {max(train_lengths_openai):5d}  <- comparison only")

    p50 = percentile(train_lengths_target, 50)
    p95 = percentile(train_lengths_target, MAX_SEQ_LEN_PERCENTILE)
    p99 = percentile(train_lengths_target, 99)
    print(f"\n[{ft_base_model}] min={min(train_lengths_target)}  p50={p50:.0f}  p95={p95:.0f}  "
          f"p99={p99:.0f}  max={max(train_lengths_target)}")

    recommended = -(-int(p95) // ROUND_MAX_SEQ_LEN_TO) * ROUND_MAX_SEQ_LEN_TO
    print(f"\nRecommended max_seq_len (target model {ft_base_model}): "
          f"p{MAX_SEQ_LEN_PERCENTILE}={p95:.0f} rounded up to the nearest "
          f"{ROUND_MAX_SEQ_LEN_TO} -> **{recommended}**")

    print("\nTruncation counts at that max_seq_len, per split (target-model tokenizer):")
    for split in SPLITS:
        lengths = split_lengths_target[split]
        n_truncated = sum(1 for length in lengths if length > recommended)
        print(f"  {split}: {n_truncated} / {len(lengths)} ({n_truncated / len(lengths):.2%}) "
              f"would be truncated")

    write_samples_report(
        train_examples[:N_SAMPLES_TO_SHOW], train_lengths_target[:N_SAMPLES_TO_SHOW],
        train_rows[:N_SAMPLES_TO_SHOW], system_message, ft_base_model, tokenizer, recommended,
        train_lengths_target, train_lengths_openai, openai_model,
    )


if __name__ == "__main__":
    main()
