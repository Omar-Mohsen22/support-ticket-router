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
Up to 2 retries (3 attempts total) on invalid/unparseable CONTENT -- failures
beyond that are logged, not retried forever.

Rate limits (429) are a SEPARATE concern from content retries (see
call_with_cache): they get their own dedicated backoff loop
(RATE_LIMIT_MAX_RETRIES, on top of the SDK's own internal backoff) and never
consume one of a ticket's 3 content-validation attempts. CONCURRENCY_LIMIT is
set low enough (see its definition) that, combined with that backoff, no row
should ever be left without a prediction because of a rate limit -- and every
prior error response cached to disk gets purged at the start of each real run
(purge_error_cache_entries()) so a stale failure is retried, never silently
replayed as if it were final.

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

import random

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI, APIStatusError, BadRequestError, RateLimitError
from pydantic import ValidationError
from sklearn.feature_extraction.text import CountVectorizer

from ticket_router.schema import TicketLabels

REPO_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RESULTS_DIR = REPO_ROOT / "results"
LABEL_MAP_PATH = PROCESSED_DIR / "label_map.json"
ENV_PATH = REPO_ROOT / ".env"
CACHE_DIR = REPO_ROOT / ".cache" / "api_predictor"
PRIORITY_DEFINITIONS_PATH = RESULTS_DIR / "priority_definitions.json"

DEFAULT_BASE_URL = "https://api.openai.com/v1"
TARGET_FIELDS = ["queue", "priority", "type"]

# Lowered from 5 (step-04/05's original value) to eliminate 429s, not just
# reduce them -- see the "Rate limits, made deterministic" note below.
# Variant B (the longest prompt) averaged ~963 total tokens/request at
# ~1.37s/request; at concurrency=5 that's ~5/1.37*963*60 =~ 211,000
# tokens/minute against a 200,000 TPM account limit -- over budget, which is
# exactly what produced the observed 429s. At concurrency=3 the same math
# gives ~127,000 tokens/minute, comfortably under budget with margin for
# variance. Applied to every variant uniformly for one simple, verifiable
# number rather than a per-variant tuned value.
CONCURRENCY_LIMIT = 3
MAX_CONTENT_RETRIES = 2   # content-validation retries: up to 3 attempts total per ticket
SDK_MAX_RETRIES = 5       # the openai SDK's own built-in backoff on 429/5xx/connection errors

# Rate-limit (429) retries are handled SEPARATELY from MAX_CONTENT_RETRIES
# (see call_with_cache): a transient rate limit is not a content problem, and
# must never consume one of a ticket's 3 content-validation attempts. This is
# the outer bound on top of the SDK's own internal backoff -- generous
# (RATE_LIMIT_MAX_RETRIES attempts, exponential backoff capped at
# RATE_LIMIT_MAX_DELAY_S) specifically so that, combined with the lowered
# concurrency above, no row is ever left without a prediction because of a
# rate limit.
RATE_LIMIT_MAX_RETRIES = 10
RATE_LIMIT_BASE_DELAY_S = 2.0
RATE_LIMIT_MAX_DELAY_S = 60.0

# --- Step-05 few-shot config ---------------------------------------------------
# Variant A ("coverage"): one few-shot example per queue class, selected
# deterministically as that class's SHORTEST training text (ties broken by
# lowest id) -- keeps the prompt small while giving the model one concrete
# example of every queue label it's allowed to use.
#
# Variant B ("coverage-priority"): variant A's examples, plus a one-sentence,
# per-priority-value description derived empirically from the training data:
# for each priority value, the words most disproportionately frequent in that
# value's training tickets vs. the other two values (Laplace-smoothed relative
# frequency ratio, restricted to words appearing in at least
# PRIORITY_DEF_MIN_DF training tickets of that value, to avoid noise from rare
# words). This is a keyness/log-odds-style analysis, not a hand-written guess.
#
# Variant C ("coverage-median"): identical to Variant A except the selection
# rule is the MEDIAN-length training text per queue class, not the shortest.
# Isolates whether Variant A's result was a property of few-shot prompting or
# an artifact of "shortest" skewing toward atypical, less-informative
# examples -- same deterministic tie-break (lowest id on length ties), same
# 10-classes-of-1 structure, only the length-selection rule differs.
PRIORITY_DEF_TOP_N = 12
PRIORITY_DEF_MIN_DF = 20

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


def select_few_shot_examples(train: pd.DataFrame, rule: str = "shortest") -> list[dict]:
    """10 few-shot examples: one per queue class, chosen by `rule`, ties on
    text length always broken by lowest `id`. Fully deterministic given the
    fixed train.parquet.

    rule="shortest" (Variant A): the shortest training `text` in each class
      -- keeps the prompt small, but may select atypical, less-informative
      examples.
    rule="median" (Variant C): the training `text` at the middle position by
      length within each class (index len(subset)//2 after ascending sort --
      the upper median for even-sized classes), to remove the "shortest
      skews atypical" confound while keeping the same one-example-per-class
      structure.
    """
    if rule not in ("shortest", "median"):
        raise ValueError(f"unknown rule: {rule!r}")

    examples = []
    for queue_value in sorted(train["queue"].unique()):
        subset = train[train["queue"] == queue_value].copy()
        subset["_text_len"] = subset["text"].str.len()
        subset = subset.sort_values(["_text_len", "id"]).reset_index(drop=True)
        idx = 0 if rule == "shortest" else len(subset) // 2
        row = subset.iloc[idx]
        examples.append({
            "id": row["id"], "text": row["text"],
            "queue": row["queue"], "priority": row["priority"], "type": row["type"],
        })
    return examples


def derive_priority_definitions(train: pd.DataFrame) -> tuple[dict, dict]:
    """Variant B's per-priority-value descriptions, derived empirically from
    train.parquet (never hand-written): for each priority value, find the
    words most disproportionately frequent in that value's tickets vs. the
    other two values, using a Laplace-smoothed relative-frequency ratio
    (a simple keyness/log-odds analysis), restricted to words occurring in at
    least PRIORITY_DEF_MIN_DF tickets of that value.

    Returns (definitions, top_words): `definitions[value]` is the one-sentence
    prompt string; `top_words[value]` is the raw ranked word list, kept for
    the prompting_notes.md report so the derivation is checkable, not just
    asserted.
    """
    vectorizer = CountVectorizer(stop_words="english", min_df=PRIORITY_DEF_MIN_DF)
    X = vectorizer.fit_transform(train["text"])
    vocab = vectorizer.get_feature_names_out()
    total_counts = np.asarray(X.sum(axis=0)).ravel()

    definitions = {}
    top_words = {}
    for value in sorted(train["priority"].unique()):
        in_mask = (train["priority"] == value).to_numpy()
        in_counts = np.asarray(X[in_mask].sum(axis=0)).ravel()
        out_counts = total_counts - in_counts
        in_total, out_total = in_counts.sum(), out_counts.sum()
        rate_in = (in_counts + 1) / (in_total + len(vocab))
        rate_out = (out_counts + 1) / (out_total + len(vocab))
        score = rate_in / rate_out

        in_doc_freq = np.asarray((X[in_mask] > 0).sum(axis=0)).ravel()
        eligible = in_doc_freq >= PRIORITY_DEF_MIN_DF
        ranked = np.argsort(-np.where(eligible, score, -np.inf))[:PRIORITY_DEF_TOP_N]
        words = [vocab[i] for i in ranked if eligible[i]]

        top_words[value] = words
        definitions[value] = (
            f"Training tickets labeled `{value}` priority are, by relative word frequency "
            f"against the other two priority values (words appearing in at least "
            f"{PRIORITY_DEF_MIN_DF} `{value}`-priority tickets), most distinguished by: "
            f"{', '.join(words)}."
        )
    return definitions, top_words


def build_initial_messages(ticket_text: str, label_map: dict,
                            few_shot_examples: list[dict] | None = None,
                            priority_definitions: dict | None = None) -> list[dict]:
    system_parts = [
        "You are a support-ticket routing classifier. Given a ticket's text, respond with "
        "ONLY a single JSON object with exactly these three keys: queue, priority, type. "
        "No other text, no explanation, no markdown code fences -- just the raw JSON object.\n\n"
        f"queue must be exactly one of: {json.dumps(label_map['queue'])}\n"
        f"priority must be exactly one of: {json.dumps(label_map['priority'])}\n"
        f"type must be exactly one of: {json.dumps(label_map['type'])}"
    ]
    if priority_definitions:
        defs = "\n".join(f"- {priority_definitions[v]}" for v in sorted(priority_definitions))
        system_parts.append(
            "Empirical guidance on `priority`, derived from the training data (see the sign-off "
            f"note in the codebase for the exact method):\n{defs}"
        )
    messages = [{"role": "system", "content": "\n\n".join(system_parts)}]

    if few_shot_examples:
        for ex in few_shot_examples:
            messages.append({"role": "user", "content": f"Ticket:\n{ex['text']}"})
            messages.append({"role": "assistant", "content": json.dumps(
                {"queue": ex["queue"], "priority": ex["priority"], "type": ex["type"]}
            )})

    messages.append({"role": "user", "content": f"Ticket:\n{ticket_text}"})
    return messages


def cache_key_for(model: str, messages: list[dict], ticket_id: str, use_structured: bool) -> str:
    payload = json.dumps(
        {"model": model, "messages": messages, "ticket_id": ticket_id, "structured": use_structured},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def looks_like_unsupported_response_format(error_text: str) -> bool:
    lowered = error_text.lower()
    return "response_format" in lowered or "json_schema" in lowered


def purge_error_cache_entries() -> int:
    """Delete every cached response that recorded an "error" -- an error was
    never a valid answer to begin with, so nothing legitimate is lost, and it
    stops a stale rate-limit failure from being silently replayed forever as
    if it were the real result. Cheap (directory scan); run once per real
    invocation before any ticket is processed. Returns the count purged."""
    if not CACHE_DIR.exists():
        return 0
    n_purged = 0
    for cache_path in CACHE_DIR.glob("*.json"):
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(cached.get("response"), dict) and "error" in cached["response"]:
            cache_path.unlink()
            n_purged += 1
    return n_purged


def call_with_cache(client: OpenAI, model: str, messages: list[dict], ticket_id: str,
                     use_structured: bool, schema_dict: dict) -> tuple[dict, float, bool]:
    """Send (or replay from cache) one API call.

    Returns (response_dict, elapsed_ms, was_fresh). response_dict is either
    `response.model_dump()`, or {"error": "..."} on failure -- the error
    itself is still cached (see purge_error_cache_entries() for why that's
    safe), and replaying it on a re-run correctly reconstructs the same retry
    path without spending anything. was_fresh is False on a cache hit
    (nothing was sent/spent this run).

    A RateLimitError (429) is retried in its OWN loop here, separate from
    process_ticket's MAX_CONTENT_RETRIES -- a rate limit is not a content
    problem, and must never consume one of a ticket's 3 content-validation
    attempts. Only after RATE_LIMIT_MAX_RETRIES exhausted attempts (on top of
    the SDK's own internal backoff on every individual call) does this give
    up and return an error, at which point it's a genuine, reportable
    failure rather than an artifact of the retry budget being spent on the
    wrong kind of problem.
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
    response_dict = None
    for rl_attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(**kwargs)
            response_dict = response.model_dump()
            break
        except RateLimitError as e:
            if rl_attempt < RATE_LIMIT_MAX_RETRIES:
                delay = min(RATE_LIMIT_MAX_DELAY_S, RATE_LIMIT_BASE_DELAY_S * (2 ** rl_attempt))
                delay += random.uniform(0, 0.5)
                time.sleep(delay)
                continue
            response_dict = {"error": f"RateLimitError {e.status_code}: {e.message} "
                                       f"(gave up after {RATE_LIMIT_MAX_RETRIES} dedicated retries)"}
        except BadRequestError as e:
            response_dict = {"error": f"BadRequestError {e.status_code}: {e.message}"}
            break
        except APIStatusError as e:
            response_dict = {"error": f"{type(e).__name__} {e.status_code}: {e.message}"}
            break
    elapsed_ms = (time.perf_counter() - t0) * 1000

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with _cache_lock:
        cache_path.write_text(
            json.dumps({"response": response_dict, "elapsed_ms": elapsed_ms}), encoding="utf-8"
        )
    return response_dict, elapsed_ms, True


def process_ticket(client: OpenAI, ticket_id: str, ticket_text: str, model: str,
                    schema_dict: dict, label_map: dict, run_state: dict,
                    few_shot_examples: list[dict] | None = None,
                    priority_definitions: dict | None = None) -> tuple[dict, bool]:
    """Returns (jsonl_row, was_fully_cached)."""
    messages = build_initial_messages(ticket_text, label_map, few_shot_examples, priority_definitions)
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
    parser.add_argument("--variant",
                         choices=["zero-shot", "coverage", "coverage-priority", "coverage-median"],
                         default="zero-shot",
                         help="zero-shot (default, step-04 behavior, unchanged); coverage "
                              "(step-05 Variant A: 10 few-shot examples, shortest-per-class); "
                              "coverage-priority (step-05 Variant B: coverage + data-derived "
                              "per-priority-value descriptions); coverage-median (step-05 Variant "
                              "C: identical to coverage, but median-length-per-class examples)")
    args = parser.parse_args()

    if args.smoke_test:
        run_smoke_test(args.split)
        return

    if not args.run_name:
        parser.error("--run-name is required unless --smoke-test")

    client, model, _api_key = build_client()

    n_purged = purge_error_cache_entries()
    if n_purged:
        print(f"Purged {n_purged} stale error cache entr{'y' if n_purged == 1 else 'ies'} -- "
              f"those tickets will be freshly retried, not replayed as failures.")

    split_path = PROCESSED_DIR / f"{args.split}.parquet"
    if not split_path.exists():
        print(f"STOP: {split_path} not found. Run make_dataset.py first.")
        raise SystemExit(1)

    df = pd.read_parquet(split_path)
    if args.limit is not None:
        df = df.head(args.limit)

    label_map = load_label_map()
    schema_dict = build_ticket_schema_dict()

    few_shot_examples = None
    priority_definitions = None
    if args.variant in ("coverage", "coverage-priority", "coverage-median"):
        train_path = PROCESSED_DIR / "train.parquet"
        if not train_path.exists():
            print(f"STOP: {train_path} not found. Run make_dataset.py first.")
            raise SystemExit(1)
        train = pd.read_parquet(train_path)

        selection_rule = "median" if args.variant == "coverage-median" else "shortest"
        few_shot_examples = select_few_shot_examples(train, rule=selection_rule)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        few_shot_examples_path = RESULTS_DIR / f"few_shot_examples_{selection_rule}.json"
        few_shot_examples_path.write_text(
            json.dumps(few_shot_examples, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Variant '{args.variant}': {len(few_shot_examples)} few-shot examples "
              f"(one per queue class, {selection_rule}-text rule) -- wrote {few_shot_examples_path}")

        if args.variant == "coverage-priority":
            priority_definitions, top_words = derive_priority_definitions(train)
            PRIORITY_DEFINITIONS_PATH.write_text(
                json.dumps({"definitions": priority_definitions, "top_words": top_words},
                           indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"Derived priority definitions -- wrote {PRIORITY_DEFINITIONS_PATH}")
            for value, sentence in sorted(priority_definitions.items()):
                print(f"  {value}: {sentence}")

    output_path = args.output or (RESULTS_DIR / f"{args.run_name}.predictions.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\nSplit: {args.split}  |  Rows: {len(df)}  |  Concurrency: {CONCURRENCY_LIMIT}  "
          f"|  Variant: {args.variant}")
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
                process_ticket, client, row.id, row.text, model, schema_dict, label_map, run_state,
                few_shot_examples, priority_definitions
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
