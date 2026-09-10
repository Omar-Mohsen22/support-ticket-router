"""Step 04 -- zero-shot API baseline predictor, calling the OpenAI API directly
via the official `openai` Python SDK. Provider-agnostic by design: api_key,
base_url, and model are all read from .env (OPENAI_API_KEY, OPENAI_BASE_URL,
OPENAI_MODEL) -- OPENAI_MODEL has no default and is never hardcoded anywhere
in this file, so swapping models is a one-line .env edit.

For each ticket, asks the model for strict JSON matching TicketLabels
(queue/priority/type), with the allowed values listed explicitly in the
prompt, using OpenAI's structured-output mode (response_format: json_schema,
strict=True). If a given model/request rejects that parameter, falls back to
plain prompt-based JSON and validates the result with schema.TicketLabels.
Up to 2 retries (3 attempts total) on invalid/unparseable content -- failures
beyond that are logged, not retried forever. Rate-limit/transient-error
backoff is handled by the SDK's own built-in retry logic (`max_retries=`).

Every individual API call is cached to disk, keyed by a hash of
(model, exact messages sent, ticket id), so re-running over the same rows
costs nothing: cached calls are replayed instead of re-sent. Concurrency is
capped at CONCURRENCY_LIMIT threads.

Requires OPENAI_API_KEY and OPENAI_MODEL in a .env file at the repo root (see
.env.example) -- never hardcoded, never passed on the command line.

Run from the repo root:
    # one-call smoke test (no cache, no retries -- raw response or raw error):
    .venv\\Scripts\\python.exe src\\ticket_router\\predictors\\api_predictor.py --smoke-test

    # real run:
    .venv\\Scripts\\python.exe src\\ticket_router\\predictors\\api_predictor.py --split test --limit 50 --run-name api-baseline-50
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Make `ticket_router` importable when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI, APIStatusError, BadRequestError
from pydantic import ValidationError

from ticket_router.schema import TicketLabels

REPO_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RESULTS_DIR = REPO_ROOT / "results"
LABEL_MAP_PATH = PROCESSED_DIR / "label_map.json"
ENV_PATH = REPO_ROOT / ".env"
CACHE_DIR = REPO_ROOT / ".cache" / "api_predictor"

DEFAULT_BASE_URL = "https://api.openai.com/v1"
TARGET_FIELDS = ["queue", "priority", "type"]

CONCURRENCY_LIMIT = 5
MAX_CONTENT_RETRIES = 2   # content-validation retries: up to 3 attempts total per ticket
SDK_MAX_RETRIES = 5       # the openai SDK's own built-in backoff on 429/5xx/connection errors

_print_lock = threading.Lock()
_jsonl_lock = threading.Lock()
_cache_lock = threading.Lock()


def load_env_file(path: Path) -> None:
    """Load .env with override=True: the project's .env always wins over any
    ambient/stale environment variable of the same name (on this machine, on
    CI, on anyone else's machine) -- the code must not depend on a clean
    environment. A prior hand-rolled loader here used setdefault(), which let
    a stale OS-level OPENAI_API_KEY silently shadow .env; load_dotenv's
    override=True is the fix, not a workaround."""
    load_dotenv(dotenv_path=path, override=True)


def load_label_map() -> dict:
    if not LABEL_MAP_PATH.exists():
        raise FileNotFoundError(f"{LABEL_MAP_PATH} not found. Run make_dataset.py first.")
    return json.loads(LABEL_MAP_PATH.read_text(encoding="utf-8"))


def build_ticket_schema_dict() -> dict:
    """TicketLabels' JSON schema, with additionalProperties:false added for
    OpenAI's strict structured-output mode -- added here rather than in
    schema.py, so step-03's file is not touched."""
    schema = TicketLabels.model_json_schema()
    schema["additionalProperties"] = False
    return schema


def build_initial_messages(ticket_text: str, label_map: dict) -> list[dict]:
    system = (
        "You are a support-ticket routing classifier. Given a ticket's text, respond with "
        "ONLY a single JSON object with exactly these three keys: queue, priority, type. "
        "No other text, no explanation, no markdown code fences -- just the raw JSON object.\n\n"
        f"queue must be exactly one of: {json.dumps(label_map['queue'])}\n"
        f"priority must be exactly one of: {json.dumps(label_map['priority'])}\n"
        f"type must be exactly one of: {json.dumps(label_map['type'])}"
    )
    user = f"Ticket:\n{ticket_text}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def cache_key_for(model: str, messages: list[dict], ticket_id: str, use_structured: bool) -> str:
    payload = json.dumps(
        {"model": model, "messages": messages, "ticket_id": ticket_id, "structured": use_structured},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def looks_like_unsupported_response_format(error_text: str) -> bool:
    lowered = error_text.lower()
    return "response_format" in lowered or "json_schema" in lowered


def call_with_cache(client: OpenAI, model: str, messages: list[dict], ticket_id: str,
                     use_structured: bool, schema_dict: dict) -> tuple[dict, float, bool]:
    """Send (or replay from cache) one API call.

    Returns (response_dict, elapsed_ms, was_fresh). response_dict is either
    `response.model_dump()`, or {"error": "..."} on failure -- the error
    itself is still cached, since it's still "a response" for that exact
    request per the caching instruction, and replaying it on a re-run
    correctly reconstructs the same retry path without spending anything.
    was_fresh is False on a cache hit (nothing was sent/spent this run).
    """
    key = cache_key_for(model, messages, ticket_id, use_structured)
    cache_path = CACHE_DIR / f"{key}.json"

    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        return cached["response"], cached["elapsed_ms"], False

    kwargs = {"model": model, "messages": messages, "temperature": 0}
    if use_structured:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "ticket_labels", "strict": True, "schema": schema_dict},
        }

    t0 = time.perf_counter()
    try:
        response = client.chat.completions.create(**kwargs)
        response_dict = response.model_dump()
    except BadRequestError as e:
        response_dict = {"error": f"BadRequestError {e.status_code}: {e.message}"}
    except APIStatusError as e:
        response_dict = {"error": f"{type(e).__name__} {e.status_code}: {e.message}"}
    elapsed_ms = (time.perf_counter() - t0) * 1000

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with _cache_lock:
        cache_path.write_text(
            json.dumps({"response": response_dict, "elapsed_ms": elapsed_ms}), encoding="utf-8"
        )
    return response_dict, elapsed_ms, True


def process_ticket(client: OpenAI, ticket_id: str, ticket_text: str, model: str,
                    schema_dict: dict, label_map: dict, run_state: dict) -> tuple[dict, bool]:
    """Returns (jsonl_row, was_fully_cached)."""
    messages = build_initial_messages(ticket_text, label_map)
    total_latency_ms = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    was_fully_cached = True
    final_labels: TicketLabels | None = None
    last_error: str | None = None

    for attempt in range(MAX_CONTENT_RETRIES + 1):
        use_structured = run_state["structured_output_supported"]
        response_dict, elapsed_ms, was_fresh = call_with_cache(
            client, model, messages, ticket_id, use_structured, schema_dict
        )
        total_latency_ms += elapsed_ms
        if was_fresh:
            was_fully_cached = False

        if "error" in response_dict:
            error_text = response_dict["error"]
            if use_structured and looks_like_unsupported_response_format(error_text):
                with _print_lock:
                    if run_state["structured_output_supported"]:
                        print("  Structured output not supported by this model -- "
                              "falling back to prompt-only JSON for the rest of the run.")
                run_state["structured_output_supported"] = False
                response_dict, elapsed_ms2, was_fresh2 = call_with_cache(
                    client, model, messages, ticket_id, False, schema_dict
                )
                total_latency_ms += elapsed_ms2
                if was_fresh2:
                    was_fully_cached = False

            if "error" in response_dict:
                last_error = response_dict["error"]
                continue  # exhausts one of the MAX_CONTENT_RETRIES attempts

        usage = response_dict.get("usage") or {}
        total_input_tokens += usage.get("prompt_tokens") or 0
        total_output_tokens += usage.get("completion_tokens") or 0

        try:
            content = response_dict["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            final_labels = TicketLabels(**parsed)
            break
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as e:
            last_error = f"{type(e).__name__}: {e}"
            messages = messages + [
                {"role": "assistant", "content": response_dict.get("choices", [{}])[0]
                    .get("message", {}).get("content", "")},
                {"role": "user", "content": (
                    f"That response was invalid ({last_error}). Reply again with ONLY a raw JSON "
                    "object with exactly the three keys queue, priority, type, using one of the "
                    "allowed values listed earlier for each."
                )},
            ]

    row = {
        "id": ticket_id,
        "queue": final_labels.queue if final_labels else None,
        "priority": final_labels.priority if final_labels else None,
        "type": final_labels.type if final_labels else None,
        "latency_ms": total_latency_ms,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        # OpenAI's API does not return a live $ cost in the response (unlike
        # some aggregators). No pricing table is hardcoded here -- pricing
        # drifts and guessing it would be worse than being explicit that it's
        # unknown. input_tokens/output_tokens above are exact and authoritative;
        # multiply by your account's current published per-token price for
        # OPENAI_MODEL to get a real cost.
        "cost_usd": None,
    }
    if final_labels is None and last_error:
        row["error"] = last_error

    return row, was_fully_cached


def build_client() -> tuple[OpenAI, str, str]:
    load_env_file(ENV_PATH)
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL
    model = os.environ.get("OPENAI_MODEL")
    if not api_key or not model:
        print("STOP: OPENAI_API_KEY and/or OPENAI_MODEL not set.")
        print(f"Add both to {ENV_PATH} (copy .env.example) before running this script.")
        raise SystemExit(1)
    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=SDK_MAX_RETRIES)
    print(f"Provider: OpenAI SDK  |  base_url={base_url}  |  model={model}")
    return client, model, api_key


def run_smoke_test(split: str) -> None:
    """ONE raw, uncached, unretried call -- to prove the key/base_url/model/
    structured-output path all work. On failure (e.g. the model is not
    available on this account), the SDK's exception is left to propagate
    uncaught, so the real error is shown as-is -- no fallback model, no
    silent handling."""
    client, model, api_key = build_client()

    split_path = PROCESSED_DIR / f"{split}.parquet"
    if not split_path.exists():
        print(f"STOP: {split_path} not found. Run make_dataset.py first.")
        raise SystemExit(1)
    df = pd.read_parquet(split_path)
    ticket_id = df.iloc[0]["id"]
    ticket_text = df.iloc[0]["text"]

    label_map = load_label_map()
    schema_dict = build_ticket_schema_dict()
    messages = build_initial_messages(ticket_text, label_map)

    print(f"Smoke test: sending ONE request for ticket {ticket_id!r} to model={model!r} "
          f"(structured output, strict json_schema) ...")
    print(f"Key actually being used ends in: ...{api_key[-4:]}\n")

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "ticket_labels", "strict": True, "schema": schema_dict},
        },
    )

    print("=== RAW RESPONSE (response.model_dump_json) ===")
    print(response.model_dump_json(indent=2))

    content = response.choices[0].message.content
    print("\n=== Parsed message content ===")
    print(content)

    labels = TicketLabels(**json.loads(content))
    print("\n=== Validated against TicketLabels ===")
    print(labels)
    print(f"\nGold label for this ticket: queue={df.iloc[0]['queue']!r}, "
          f"priority={df.iloc[0]['priority']!r}, type={df.iloc[0]['type']!r}")
    print("\nSmoke test PASSED: API key, base_url, model, and the structured-output path all work.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-test", action="store_true",
                         help="Send ONE raw, uncached request and print the full response, then exit.")
    parser.add_argument("--split", choices=["train", "val", "test"], default="test")
    parser.add_argument("--limit", type=int, default=None,
                         help="Only predict the first N rows of the split (omit for the full split)")
    parser.add_argument("--run-name", help="Required unless --smoke-test")
    parser.add_argument("--output", type=Path, default=None,
                         help="Defaults to results/<run-name>.predictions.jsonl")
    args = parser.parse_args()

    if args.smoke_test:
        run_smoke_test(args.split)
        return

    if not args.run_name:
        parser.error("--run-name is required unless --smoke-test")

    client, model, _api_key = build_client()

    split_path = PROCESSED_DIR / f"{args.split}.parquet"
    if not split_path.exists():
        print(f"STOP: {split_path} not found. Run make_dataset.py first.")
        raise SystemExit(1)

    df = pd.read_parquet(split_path)
    if args.limit is not None:
        df = df.head(args.limit)

    label_map = load_label_map()
    schema_dict = build_ticket_schema_dict()

    output_path = args.output or (RESULTS_DIR / f"{args.run_name}.predictions.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Split: {args.split}  |  Rows: {len(df)}  |  Concurrency: {CONCURRENCY_LIMIT}")
    print(f"Output: {output_path}")
    print(f"Cache dir: {CACHE_DIR}\n")
    print("NOTE: cost_usd is null for every row -- OpenAI's API does not return a live $ cost. "
          "input_tokens/output_tokens are exact; compute cost externally from those.\n")

    run_state = {"structured_output_supported": True}
    n_cached = 0
    n_fresh = 0
    n_errors = 0

    with open(output_path, "w", encoding="utf-8") as out_f, \
         ThreadPoolExecutor(max_workers=CONCURRENCY_LIMIT) as executor:
        futures = {
            executor.submit(
                process_ticket, client, row.id, row.text, model, schema_dict, label_map, run_state
            ): row.id
            for row in df.itertuples()
        }
        done = 0
        for future in as_completed(futures):
            row, was_cached = future.result()
            with _jsonl_lock:
                out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                out_f.flush()

            done += 1
            if was_cached:
                n_cached += 1
            else:
                n_fresh += 1
            if "error" in row:
                n_errors += 1

            if done % 10 == 0 or done == len(df):
                with _print_lock:
                    print(f"  {done}/{len(df)} done  (cached={n_cached}, fresh={n_fresh}, failed={n_errors})")

    print(f"\nWrote {len(df)} predictions to {output_path}")
    print(f"Cached (free) tickets: {n_cached}  |  Freshly called: {n_fresh}  |  Failed (invalid after retries): {n_errors}")


if __name__ == "__main__":
    main()
