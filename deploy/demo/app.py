"""Step 29 -- ZeroGPU demo: TF-IDF vs the fine-tuned Qwen2.5-1.5B adapter, side by side.

Reuses the project's own code, copied into this Space at deploy time by
deploy/demo/deploy_demo.py:
  - build_ticket_text (ticket_text.py): subject + body -> model input, as in training;
  - build_system_message (make_sft_dataset.py), render_prompt, generate_batch and
    parse_and_validate (predictors/adapter_predictor.py): the same system prompt, chat
    template, left padding, greedy decoding and output validation as the batch predictor;
  - the committed TF-IDF artifact (models/tfidf/), the exact evaluated model.

One difference from the published run: the base model is loaded unquantized in bfloat16 and
the adapter is merged (merge_and_unload). The published metrics used a 4-bit NF4 base on a
T4.
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
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from ticket_router.make_sft_dataset import build_system_message
from ticket_router.predictors.adapter_predictor import (
    generate_batch, load_config, load_hf_token, load_label_map, parse_and_validate, render_prompt,
)
from ticket_router.predictors.tfidf_baseline import MODEL_PATH, TARGET_FIELDS
from ticket_router.ticket_text import build_ticket_text

# Seconds of GPU time one call may hold. Start at the ZeroGPU default of 60 and lower it after
# measuring real per-call time (step 29).
GPU_DURATION_S = 60
MAX_BATCH = 16  # upper bound for the hidden measurement endpoint
ERROR_ANALYSIS_URL = "https://github.com/Omar-Mohsen22/support-ticket-router/blob/master/reports/error_analysis.md"

CONFIG = load_config()
SYSTEM_MESSAGE = build_system_message(load_label_map())
MAX_SEQ_LEN = CONFIG["max_seq_len"]
MAX_NEW_TOKENS = CONFIG["inference"]["max_new_tokens"]

tfidf = joblib.load(MODEL_PATH)

tokenizer = AutoTokenizer.from_pretrained(CONFIG["base_model"])
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "left"
base = AutoModelForCausalLM.from_pretrained(CONFIG["base_model"], dtype=torch.bfloat16)
model = PeftModel.from_pretrained(base, CONFIG["hub_model_id"], token=load_hf_token()).merge_and_unload()
model.to("cuda")  # at module level, as the ZeroGPU docs require
model.eval()

EXAMPLES = json.loads((ROOT / "examples.json").read_text(encoding="utf-8"))


@spaces.GPU(duration=GPU_DURATION_S)
def adapter_generate(texts: list[str]) -> tuple[list[str], float]:
    """Returns the decoded completions and the milliseconds spent inside this GPU call."""
    t0 = time.perf_counter()
    prompts = [render_prompt(t, SYSTEM_MESSAGE, tokenizer) for t in texts]
    decoded, _, _, _ = generate_batch(model, tokenizer, prompts, MAX_SEQ_LEN, MAX_NEW_TOKENS)
    return decoded, (time.perf_counter() - t0) * 1000


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
    decoded, gpu_ms = adapter_generate([text])
    adapter_ms = (time.perf_counter() - t0) * 1000
    labels, error = parse_and_validate(decoded[0])

    rows = [
        [f, tfidf_labels[f], getattr(labels, f) if labels else "invalid output"]
        for f in TARGET_FIELDS
    ]
    timing = (
        f"TF-IDF (CPU): {tfidf_ms:.1f} ms. Fine-tuned model: {adapter_ms:.0f} ms end to end, "
        f"GPU time inside the call: {gpu_ms:.0f} ms."
    )
    if error:
        timing += f"\n\nThe fine-tuned model's output did not validate: `{decoded[0][:200]}` ({error[:200]})"
    return rows, timing


def predict_batch(payload: str) -> str:
    """Hidden endpoint for the step-29 agreement measurement. It is not shown in the UI.
    TODO (blocker for making this Space public): remove or disable it first, so visitors
    cannot use it to drain GPU quota."""
    tickets = json.loads(payload)
    if not 1 <= len(tickets) <= MAX_BATCH:
        raise gr.Error(f"Send between 1 and {MAX_BATCH} tickets.")
    texts = [build_ticket_text(t.get("subject"), t["body"]) for t in tickets]
    decoded, gpu_ms = adapter_generate(texts)
    results = []
    for t, raw in zip(tickets, decoded):
        labels, error = parse_and_validate(raw)
        results.append({"id": t["id"], "raw": raw,
                        "labels": labels.model_dump() if labels else None, "error": error})
    return json.dumps({"gpu_ms": gpu_ms, "results": results})


INTRO = """# Support ticket router: TF-IDF vs fine-tuned Qwen2.5-1.5B

I trained two models to route a customer-support ticket to a **queue**, a **priority** and a
**type**. Enter a ticket, and both answer side by side:
- **TF-IDF + logistic regression** runs on the CPU.
- **Qwen2.5-1.5B-Instruct with my LoRA adapter** runs on a shared GPU.

The adapter runs on an unquantized bf16 base here. The published numbers used a 4-bit base on a
T4, so a few predictions can differ from the published ones.
"""

NOTE = f"""**About the test labels.** They are noisy. In my [error analysis]({ERROR_ANALYSIS_URL})
(the repository is private for now), the two models, which are unrelated, often make the same
"mistake", and several sampled tickets have text that contradicts their gold label. Some of the
examples below are such cases. Compare the gold labels with the ticket text yourself.
"""


def examples_table() -> str:
    lines = ["| ticket | gold queue / priority / type | why it is here |", "| --- | --- | --- |"]
    for e in EXAMPLES:
        lines.append(f"| `{e['id']}` | {e['gold']} | {e['why']} |")
    return "\n".join(lines)


with gr.Blocks() as demo:
    gr.Markdown(INTRO)
    with gr.Row():
        with gr.Column():
            subject = gr.Textbox(label="Subject (optional)")
            body = gr.Textbox(label="Body", lines=8)
            gold = gr.Textbox(label="Gold labels from the test set (filled in by the examples)",
                              interactive=False)
            run = gr.Button("Classify", variant="primary")
        with gr.Column():
            table = gr.Dataframe(headers=["field", "TF-IDF", "fine-tuned Qwen2.5-1.5B"],
                                 interactive=False)
            timing = gr.Markdown()
    gr.Examples(examples=[[e["subject"] or "", e["body"], e["gold"]] for e in EXAMPLES],
                inputs=[subject, body, gold])
    gr.Markdown(NOTE)
    gr.Markdown(examples_table())
    run.click(classify, inputs=[subject, body], outputs=[table, timing], api_name="classify")

    with gr.Row(visible=False):
        batch_in = gr.Textbox()
        batch_out = gr.Textbox()
        batch_run = gr.Button()
    batch_run.click(predict_batch, inputs=batch_in, outputs=batch_out, api_name="predict_batch")

demo.queue().launch()
