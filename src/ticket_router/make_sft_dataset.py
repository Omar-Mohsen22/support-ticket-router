"""Step 06 -- convert the processed splits into OpenAI fine-tuning chat format.

Reads data/processed/{train,val,test}.parquet and label_map.json, and writes
data/processed/sft/{train,val,test}.jsonl in OpenAI's fine-tuning JSONL format
-- one {"messages": [...]} object per line (system + user + assistant turns),
directly usable as a `client.fine_tuning.jobs.create(training_file=...)`
input, no further conversion needed.

Each example:
  - system: a short, fixed message stating the task and every allowed value
    per field, read from label_map.json (the same single source of truth
    used everywhere else in this project -- schema.py, api_predictor.py).
  - user: the ticket's `text` column, verbatim.
  - assistant: MINIFIED JSON (json.dumps(..., separators=(",", ":")), no
    whitespace) with keys in the fixed order queue, priority, type -- the
    same order used throughout the codebase (schema.py's TicketLabels,
    metrics.py's TARGET_FIELDS, api_predictor.py's prompts).

Token-length histogram, recommended max_seq_len, and truncation counts use
the tokenizer of the model that will actually be fine-tuned -- read from
.env's OPENAI_MODEL. That's the only model config this project has (no
separate fine-tuning-specific config exists), so it's the natural choice
here; flagged in the printed output in case a different target model is
intended. Token counts follow OpenAI's published per-message chat-overhead
formula (num_tokens_from_messages(), from the openai-cookbook "How to count
tokens with tiktoken" notebook) -- not a raw encode() of the concatenated
text, since the chat wrapper itself costs a few tokens per message.

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
import tiktoken
from dotenv import load_dotenv

from ticket_router.metrics import percentile

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
SFT_DIR = PROCESSED_DIR / "sft"
LABEL_MAP_PATH = PROCESSED_DIR / "label_map.json"
REPORTS_DIR = REPO_ROOT / "reports"
SAMPLES_PATH = REPORTS_DIR / "sft_samples.md"
ENV_PATH = REPO_ROOT / ".env"

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


def num_tokens_from_messages(messages: list[dict], encoding: "tiktoken.Encoding") -> int:
    """OpenAI's published token-counting formula for chat messages (from the
    openai-cookbook "How to count tokens with tiktoken" notebook): each
    message costs a few tokens of chat-wrapper overhead beyond the raw
    content tokens, and the reply is primed with a few more."""
    tokens_per_message = 3
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for value in message.values():
            num_tokens += len(encoding.encode(value))
    num_tokens += 3  # every reply is primed with the assistant turn
    return num_tokens


def get_model_and_encoding() -> tuple[str, "tiktoken.Encoding"]:
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    model = os.environ.get("OPENAI_MODEL")
    if not model:
        print("STOP: OPENAI_MODEL not set in .env -- needed to pick the tokenizer for the model "
              "that will actually be fine-tuned. Add it (see .env.example) and re-run.")
        raise SystemExit(1)
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        print(f"STOP: tiktoken has no known encoding for model {model!r}. This is an assumption "
              "worth stopping on rather than guessing a workaround -- confirm the exact "
              "fine-tuning target model, or the right tiktoken encoding for it, and re-run.")
        raise SystemExit(1)
    return model, encoding


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


def write_samples_report(sample_examples: list[dict], sample_lengths: list[int],
                          sample_rows: list[pd.Series], system_message: str, model: str,
                          recommended_max_seq_len: int, train_lengths: list[int]) -> None:
    lines = ["# SFT format samples\n"]
    lines.append(
        f"{len(sample_examples)} formatted examples from `data/processed/sft/train.jsonl`, "
        f"shown in full so the format can be read directly. Tokenizer: "
        f"`tiktoken.encoding_for_model({model!r})`.\n"
    )

    lines.append("## System message (identical for every example)\n")
    lines.append("```\n" + system_message + "\n```\n")

    for i, (ex, length, row) in enumerate(zip(sample_examples, sample_lengths, sample_rows), start=1):
        user_msg = ex["messages"][1]["content"]
        assistant_msg = ex["messages"][2]["content"]
        lines.append(f"## Example {i} -- ticket `{row['id']}` ({length} tokens)\n")
        lines.append("**User turn (ticket text):**\n")
        lines.append("```\n" + user_msg + "\n```\n")
        lines.append("**Assistant turn (minified JSON, fixed key order):**\n")
        lines.append("```\n" + assistant_msg + "\n```\n")
        lines.append(
            f"Gold labels: queue={row['queue']!r}, priority={row['priority']!r}, type={row['type']!r}\n"
        )
        lines.append("**Raw JSONL line (exact bytes written to the file):**\n")
        lines.append("```json\n" + json.dumps(ex, ensure_ascii=False) + "\n```\n")

    lines.append("## Token-length summary (full train split)\n")
    lines.append(
        f"n={len(train_lengths)}, min={min(train_lengths)}, "
        f"p50={percentile(train_lengths, 50):.0f}, "
        f"p95={percentile(train_lengths, 95):.0f}, "
        f"p99={percentile(train_lengths, 99):.0f}, "
        f"max={max(train_lengths)}. Recommended `max_seq_len` = **{recommended_max_seq_len}** "
        f"(p95 rounded up to the nearest {ROUND_MAX_SEQ_LEN_TO}). Full histogram and per-split "
        "truncation counts are printed by the script and recorded in PROGRESS.md.\n"
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
    model, encoding = get_model_and_encoding()
    print(f"Fine-tuning target model (from .env OPENAI_MODEL): {model!r}")
    print(f"Tokenizer: tiktoken.encoding_for_model({model!r}) -> {encoding.name}\n")

    SFT_DIR.mkdir(parents=True, exist_ok=True)

    split_lengths: dict[str, list[int]] = {}
    train_examples: list[dict] = []
    train_rows: list[pd.Series] = []

    for split in SPLITS:
        df = pd.read_parquet(PROCESSED_DIR / f"{split}.parquet")
        examples = [build_example(row, system_message) for _, row in df.iterrows()]
        lengths = [num_tokens_from_messages(ex["messages"], encoding) for ex in examples]
        split_lengths[split] = lengths

        out_path = SFT_DIR / f"{split}.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
        print(f"Wrote {len(examples)} examples to {out_path}")

        if split == "train":
            train_examples = examples
            train_rows = [row for _, row in df.iterrows()]

    train_lengths = split_lengths["train"]
    print(f"\n=== Train token-length histogram ({len(train_lengths)} examples) ===")
    print_histogram(train_lengths)

    p50 = percentile(train_lengths, 50)
    p95 = percentile(train_lengths, MAX_SEQ_LEN_PERCENTILE)
    p99 = percentile(train_lengths, 99)
    print(f"\nmin={min(train_lengths)}  p50={p50:.0f}  p95={p95:.0f}  p99={p99:.0f}  "
          f"max={max(train_lengths)}")

    recommended = -(-int(p95) // ROUND_MAX_SEQ_LEN_TO) * ROUND_MAX_SEQ_LEN_TO
    print(f"\nRecommended max_seq_len: p{MAX_SEQ_LEN_PERCENTILE}={p95:.0f} rounded up to the "
          f"nearest {ROUND_MAX_SEQ_LEN_TO} -> **{recommended}**")

    print("\nTruncation counts at that max_seq_len, per split:")
    for split in SPLITS:
        lengths = split_lengths[split]
        n_truncated = sum(1 for length in lengths if length > recommended)
        print(f"  {split}: {n_truncated} / {len(lengths)} ({n_truncated / len(lengths):.2%}) "
              f"would be truncated")

    write_samples_report(
        train_examples[:N_SAMPLES_TO_SHOW], train_lengths[:N_SAMPLES_TO_SHOW],
        train_rows[:N_SAMPLES_TO_SHOW], system_message, model, recommended, train_lengths,
    )


if __name__ == "__main__":
    main()
