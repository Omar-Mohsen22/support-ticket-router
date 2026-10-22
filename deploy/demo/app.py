"""Step 29 -- ZeroGPU demo: TF-IDF vs the fine-tuned Qwen2.5-1.5B adapter, side by side.

Reuses the project's own code, copied into this Space at deploy time by
deploy/demo/deploy_demo.py:
  - build_ticket_text (ticket_text.py): subject + body -> model input, as in training;
  - build_system_message (make_sft_dataset.py), and load_model_and_tokenizer, render_prompt,
    generate_batch and parse_and_validate (predictors/adapter_predictor.py): the same model
    loading, system prompt, chat template, left padding, greedy decoding and output
    validation as the evaluated batch predictor;
  - the committed TF-IDF artifact (models/tfidf/), the exact evaluated model.

The adapter runs in the evaluated inference config: 4-bit NF4 with double quant
(train/config.yaml), the adapter unmerged, and the compute dtype pinned to float16, which
pick_compute_dtype() chose on the T4 that produced the published predictions. On 400 sampled
test tickets, run in batches of 8, this config matched the published predictions on 399
(reports/adapter_zerogpu_4bit.md). 4-bit quantization needs a real GPU, so the model is
loaded inside each GPU call (ZeroGPU gives none at module level). The weights are downloaded to
disk at startup, so a GPU call only loads them from disk.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import spaces  # imported before torch, as ZeroGPU expects

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import gradio as gr
import joblib
import torch
from huggingface_hub import snapshot_download

from ticket_router.make_sft_dataset import build_system_message
from ticket_router.predictors.adapter_predictor import (
    generate_batch, load_config, load_hf_token, load_label_map, load_model_and_tokenizer,
    parse_and_validate, render_prompt,
)
from ticket_router.predictors.tfidf_baseline import MODEL_PATH, TARGET_FIELDS
from ticket_router.ticket_text import build_ticket_text
from ui import build_demo, launch_kwargs

# GPU durations, sized from the 4-bit probe on this Space (reports/adapter_zerogpu_4bit.md).
# Loading the 4-bit model inside a call took 1.6-1.75 s warm and 5.9 s on the first call.
# One batch of 8 took 0.93-1.5 s to generate. An output that runs to max_new_tokens (64, about
# 4x a normal ~15-token answer) could take ~6 s. So a single ticket's worst case is ~12 s
# (cold load plus a runaway output), and a typical one is ~2.7 s.
SINGLE_DURATION_S = 20          # ~1.7x that worst case, ~7x the typical call
EVAL_BATCH = 8                  # the evaluated run's batch size
COMPUTE_DTYPE = torch.float16   # what pick_compute_dtype() chose on the T4

CONFIG = load_config()
SYSTEM_MESSAGE = build_system_message(load_label_map())
MAX_SEQ_LEN = CONFIG["max_seq_len"]
MAX_NEW_TOKENS = CONFIG["inference"]["max_new_tokens"]
HF_TOKEN = load_hf_token()

tfidf = joblib.load(MODEL_PATH)

# Download the base model and the adapter to the disk cache now, without a GPU, so a GPU
# call never spends its time on a 3 GB download.
snapshot_download(CONFIG["base_model"])
snapshot_download(CONFIG["hub_model_id"], token=HF_TOKEN)

EXAMPLES = json.loads((ROOT / "examples.json").read_text(encoding="utf-8"))


def _generate_4bit(texts: list[str]) -> tuple[list[str], float, float]:
    """Load the evaluated 4-bit config and generate in batches of 8, as the evaluated run did.
    Returns (decoded, load_ms, total_ms_inside_the_call)."""
    t_call = time.perf_counter()
    model, tokenizer = load_model_and_tokenizer(CONFIG, COMPUTE_DTYPE, HF_TOKEN)
    load_ms = (time.perf_counter() - t_call) * 1000
    decoded_all = []
    for i in range(0, len(texts), EVAL_BATCH):
        prompts = [render_prompt(t, SYSTEM_MESSAGE, tokenizer) for t in texts[i:i + EVAL_BATCH]]
        decoded, _, _, _ = generate_batch(model, tokenizer, prompts, MAX_SEQ_LEN, MAX_NEW_TOKENS)
        decoded_all += decoded
    del model
    torch.cuda.empty_cache()
    return decoded_all, load_ms, (time.perf_counter() - t_call) * 1000


@spaces.GPU(duration=SINGLE_DURATION_S)
def adapter_generate_one(text: str) -> tuple[list[str], float, float]:
    return _generate_4bit([text])


def tfidf_predict(texts: list[str]) -> list[dict]:
    X = tfidf["vectorizer"].transform(texts)
    preds = {f: tfidf["classifiers"][f].predict(X) for f in TARGET_FIELDS}
    return [{f: str(preds[f][i]) for f in TARGET_FIELDS} for i in range(len(texts))]


def classify(subject: str, body: str):
    if not body or not body.strip():
        raise gr.Error("The ticket body is required.")
    text = build_ticket_text(subject, body)

    t0 = time.perf_counter()
    tfidf_labels = tfidf_predict([text])[0]
    tfidf_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    decoded, load_ms, gpu_ms = adapter_generate_one(text)
    adapter_ms = (time.perf_counter() - t0) * 1000
    labels, error = parse_and_validate(decoded[0])

    rows = [
        [f, tfidf_labels[f], getattr(labels, f) if labels else "invalid output"]
        for f in TARGET_FIELDS
    ]
    timing = (
        f"TF-IDF (CPU): {tfidf_ms:.1f} ms. Fine-tuned model: {adapter_ms:.0f} ms end to end, "
        f"GPU time inside the call: {gpu_ms:.0f} ms (of which loading the 4-bit model: {load_ms:.0f} ms)."
    )
    if error:
        timing += f"\n\nThe fine-tuned model's output did not validate: `{decoded[0][:200]}` ({error[:200]})"
    return rows, timing


# Step 31: the hidden /predict_batch endpoint (step-29 agreement measurement) was removed before
# the Space went public, so visitors cannot use it to drain GPU quota.


# --- UI (step 30): layout, CSS and card rendering live in ui.py; inference above is unchanged.
def ui_tfidf(text: str) -> tuple[dict, float]:
    t0 = time.perf_counter()
    labels = tfidf_predict([text])[0]
    return labels, (time.perf_counter() - t0) * 1000


def ui_adapter(text: str) -> tuple[dict | None, str, str | None, float]:
    t0 = time.perf_counter()
    decoded, _load_ms, _gpu_ms = adapter_generate_one(text)
    labels, error = parse_and_validate(decoded[0])
    return (labels.model_dump() if labels else None), decoded[0], error, (time.perf_counter() - t0) * 1000


demo = build_demo(examples=EXAMPLES, tfidf_fn=ui_tfidf, adapter_fn=ui_adapter,
                  classify_fn=classify)
demo.queue().launch(**launch_kwargs(EXAMPLES))
