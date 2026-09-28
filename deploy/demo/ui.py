"""Step 30 -- the demo's UI (layout, CSS and card rendering), kept apart from inference.

This module holds no model code and imports no torch, so the same UI runs on the Space
(deploy/demo/app.py passes the real TF-IDF and adapter functions) and locally with a stubbed
adapter (deploy/demo/preview_ui.py).

The visible UI's events use api_visibility="private": they add no API endpoints. The /classify
endpoint that the CI smoke test calls keeps its name, inputs and response shape, and is wired to
the unchanged classify() in app.py through hidden components. /predict_batch is left as it was
(hidden; removing it is on the go-public checklist in PROGRESS.md).
"""

from __future__ import annotations

import html
import time
from typing import Callable

import gradio as gr

from ticket_router.ticket_text import build_ticket_text

FIELDS = ["queue", "priority", "type"]
FIELD_NAMES = {"queue": "Queue", "priority": "Priority", "type": "Type"}
REPO_URL = "https://github.com/Omar-Mohsen22/support-ticket-router"
RESULTS_URL = f"{REPO_URL}#headline-results"
ERROR_ANALYSIS_URL = f"{REPO_URL}/blob/master/reports/error_analysis.md"
AGREEMENT_REPORT_URL = f"{REPO_URL}/blob/master/reports/adapter_zerogpu_4bit_full.md"

HEAD = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600'
    '&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">'
)
# The design is light-only: pin Gradio's light theme even when the visitor's OS prefers dark.
JS = """() => {
  const url = new URL(window.location.href);
  if (url.searchParams.get("__theme") !== "light") {
    url.searchParams.set("__theme", "light");
    window.location.replace(url.href);
  }
}"""

BASE_CSS = """
:root, .gradio-container {
  --ink: #1c1b19; --muted: #57534e; --line: #e7e5e4;
  --orange: #F4521A; --orange-text: #c2410c; --orange-tint: #fff1eb;
  --purple: #6D28D9; --purple-tint: #faf8ff; --purple-line: #e7e0f7;
}
.gradio-container { background: #ffffff !important; color: var(--ink);
  font-family: "IBM Plex Sans", system-ui, sans-serif !important; max-width: 1240px !important;
  margin-left: auto !important; margin-right: auto !important; }
.nw { white-space: nowrap; }
.gradio-container * { font-family: inherit; }
.mono, .mono * { font-family: "IBM Plex Mono", ui-monospace, monospace !important; }
footer { display: none !important; }

/* header */
.hdr { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px;
  flex-wrap: wrap; padding: 8px 0 4px; }
.hdr .kicker { font-family: "IBM Plex Mono", monospace; font-size: 12px; font-weight: 600;
  letter-spacing: .12em; color: var(--purple); }
.hdr h1 { font-size: 34px; line-height: 1.15; margin: 6px 0 6px; color: var(--ink); font-weight: 700; }
.hdr h1 .hl { color: var(--orange); }
.hdr .sub { color: var(--muted); font-size: 16px; margin: 0; }
.hdr nav a { color: var(--purple); font-weight: 600; text-decoration: none; margin-left: 18px; font-size: 15px; }
.hdr nav a:hover { text-decoration: underline; }

/* left column */
.input-card { background: var(--purple-tint) !important; border: 1px solid var(--purple-line) !important;
  border-radius: 16px !important; padding: 16px !important; }
.input-card textarea, .input-card input { background: #ffffff !important; color: var(--ink) !important; }
#classify-btn { background: var(--orange) !important; color: #ffffff !important; border: none !important;
  border-radius: 999px !important; font-size: 19px !important; font-weight: 700 !important;
  padding: 12px 20px !important; }
#classify-btn:hover { filter: brightness(0.95); }
.left-col { gap: 10px !important; }
.try-wrap { padding: 0 !important; margin: 0 !important; min-height: 0 !important; }
.try-title { font-weight: 600; color: var(--ink); margin: 6px 0 0; font-size: 15px; }
.ex-btn { display: flex !important; justify-content: space-between !important; align-items: center !important;
  gap: 12px; width: 100% !important; text-align: left !important; background: #ffffff !important;
  color: var(--ink) !important; border: 1px solid var(--line) !important; border-radius: 12px !important;
  padding: 10px 14px !important; font-weight: 500 !important; font-size: 14px !important;
  box-shadow: none !important; min-height: 0 !important; }
.ex-btn:hover { border-color: var(--purple-line) !important; background: var(--purple-tint) !important; }
.ex-btn::after { font-family: "IBM Plex Mono", monospace; font-size: 12px; color: var(--muted);
  white-space: nowrap; flex-shrink: 0; }
.ex-btn.ex-noisy::after { content: "noisy label"; color: var(--orange-text); background: var(--orange-tint);
  border-radius: 999px; padding: 2px 8px; font-weight: 600; }
.ex-btn.ex-selected { border: 2px solid var(--purple) !important; padding: 9px 13px !important; }
.examples-col { gap: 6px !important; }

/* right column */
.gold { background: #1c1b19; color: #ffffff; border-radius: 12px; padding: 12px 16px; display: flex;
  flex-wrap: wrap; align-items: center; gap: 8px 16px; font-size: 15px; }
.gold, .gold * { color: #ffffff !important; }
.gold .gold-label { font-family: "IBM Plex Mono", monospace; color: #fdba9c; font-weight: 600;
  letter-spacing: .1em; font-size: 12px; color: #fdba9c !important; }
.gold .gold-id { font-family: "IBM Plex Mono", monospace; color: #d6d3d1 !important; font-size: 12px; margin-left: auto; }
.gold b { font-weight: 600; }
.cards-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px;
  align-items: stretch; }
.card { border: 1px solid var(--line); border-radius: 16px; padding: 16px; background: #ffffff;
  height: 100%; box-sizing: border-box; }
.card.card-ft { border: 2px solid var(--purple); background: var(--purple-tint); }
.card.card-gpt { border: 1.5px dashed #a8a29e; }
.card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; flex-wrap: wrap; }
.card-title { font-weight: 700; font-size: 15.5px; color: var(--ink); }
.badge { font-family: "IBM Plex Mono", monospace; font-size: 11.5px; font-weight: 600; border-radius: 999px;
  padding: 3px 9px; white-space: nowrap; }
.badge-cpu { background: #f5f5f4; color: var(--muted); }
.badge-ft { background: var(--purple); color: #ffffff; }
.badge-gpt { background: #f5f5f4; color: var(--muted); }
.card-sub { color: var(--muted); font-size: 13px; margin: 4px 0 12px; }
.field { display: block; padding: 8px 0; border-top: 1px solid var(--line); }
.card.card-ft .field { border-top-color: var(--purple-line); }
.field .k { display: block; font-family: "IBM Plex Mono", monospace; font-size: 11.5px; color: var(--muted);
  margin-bottom: 2px; }
.field .v { display: block; font-weight: 600; text-align: left; font-size: 14.5px; color: var(--ink); }
.mark-ok { color: var(--purple); font-weight: 700; margin-left: 6px; }
.mark-bad { color: var(--orange-text); font-weight: 700; margin-left: 6px; }
.card-empty { color: var(--muted); font-size: 14px; padding-top: 14px; border-top: 1px solid var(--line); }
.card-loading { color: var(--purple); font-weight: 600; font-size: 14.5px; padding-top: 16px;
  border-top: 1px solid var(--purple-line); display: flex; align-items: center; gap: 10px; }
.spinner { width: 16px; height: 16px; border: 2.5px solid var(--purple-line); border-top-color: var(--purple);
  border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.invalid { color: var(--orange-text); font-size: 13px; margin-top: 8px; }
.notes { color: var(--muted); font-size: 13px; line-height: 1.5; margin-top: 4px; }
.notes p { margin: 0 0 8px; }
.notes details { margin-top: 2px; }
.notes summary { cursor: pointer; color: var(--ink); font-weight: 600; margin-bottom: 6px; }
.notes a { color: var(--purple) !important; margin: 0 !important; padding: 0 !important; display: inline !important; }

/* narrow screens: the two columns stack */
@media (max-width: 900px) {
  .main-row { flex-direction: column !important; }
  .main-row > .left-col, .main-row > .right-col { width: 100% !important; min-width: 0 !important; }
  .hdr nav a { margin: 0 16px 0 0; }
  .hdr h1 { font-size: 28px; }
  .cards-grid { grid-template-columns: 1fr; }
}
"""


def example_css(examples: list[dict]) -> str:
    """Per-example ::after content: the ticket id in mono, or the "noisy label" pill (set by the
    .ex-noisy class above)."""
    return "\n".join(
        f'#ex-{e["id"]}::after {{ content: "{e["id"]}"; }}' for e in examples if not e.get("noisy")
    )


def _esc(v) -> str:
    return html.escape(str(v))


def header_html() -> str:
    return f"""<div class="hdr">
  <div>
    <div class="kicker">SUPPORT TICKET ROUTER</div>
    <h1>Three models, <span class="hl">one ticket</span></h1>
    <p class="sub">Queue, priority and type from TF-IDF, my fine-tuned <span class="nw">Qwen2.5-1.5B</span>, and <span class="nw">gpt-4o-mini</span>.</p>
  </div>
  <nav><a href="{RESULTS_URL}" target="_blank">Results</a><a href="{ERROR_ANALYSIS_URL}" target="_blank">Error analysis</a><a href="{REPO_URL}" target="_blank">Code</a></nav>
</div>"""


def gold_html(example: dict | None) -> str:
    if not example:
        return ""
    g = example["gold_labels"]
    return (f'<div class="gold"><span class="gold-label">GOLD LABEL</span>'
            f'<span><b>{_esc(g["queue"])}</b></span><span>{_esc(g["priority"])}</span>'
            f'<span>{_esc(g["type"])}</span><span class="gold-id">{_esc(example["id"])}</span></div>')


def card_html(kind: str, title: str, sub: str, badge: str, *, labels: dict | None = None,
              gold: dict | None = None, state: str = "result", note: str = "") -> str:
    """kind: tfidf | ft | gpt. state: empty | loading | na | result. title is trusted HTML (constants)."""
    cls = {"tfidf": "card", "ft": "card card-ft", "gpt": "card card-gpt"}[kind]
    badge_cls = {"tfidf": "badge badge-cpu", "ft": "badge badge-ft", "gpt": "badge badge-gpt"}[kind]
    head = (f'<div class="{cls}"><div class="card-head"><div class="card-title">{title}</div>'
            f'<span class="{badge_cls}">{_esc(badge)}</span></div><div class="card-sub">{_esc(sub)}</div>')
    if state == "loading":
        body = '<div class="card-loading"><span class="spinner"></span>Running on ZeroGPU…</div>'
    elif state == "na":
        body = '<div class="card-empty">Available for examples only.</div>'
    elif state == "empty" or labels is None:
        body = '<div class="card-empty">Classify a ticket to see its prediction.</div>'
    else:
        rows = []
        for f in FIELDS:
            v = labels.get(f)
            mark = ""
            if gold is not None and v is not None:
                mark = ('<span class="mark-ok" title="matches the gold label">✓</span>' if v == gold[f]
                        else '<span class="mark-bad" title="differs from the gold label">✗</span>')
            rows.append(f'<div class="field"><span class="k">{FIELD_NAMES[f]}</span>'
                        f'<span class="v">{_esc(v) if v is not None else "—"}{mark}</span></div>')
        body = "".join(rows)
    extra = f'<div class="invalid">{_esc(note)}</div>' if note else ""
    return head + body + extra + "</div>"


TFIDF_TITLE, TFIDF_SUB = "TF-IDF", "TF-IDF + logistic regression"
FT_TITLE, FT_SUB = 'Fine-tuned<br><span class="nw">Qwen2.5-1.5B</span>', "QLoRA adapter, 4-bit NF4 base"
GPT_TITLE, GPT_SUB = '<span class="nw">gpt-4o-mini</span>', "OpenAI API, zero-shot prompt"


def cards_html(tf: str, ft: str, gpt: str) -> str:
    return f'<div class="cards-grid">{tf}{ft}{gpt}</div>'


def notes_html() -> str:
    return f"""<div class="notes">
<p>The test labels are noisy. Tickets marked "noisy label" have text that contradicts their gold label; compare them yourself (<a href="{ERROR_ANALYSIS_URL}" target="_blank">error analysis</a>).</p>
<details><summary>About this demo</summary>
<p>gpt-4o-mini shows the stored output from my evaluation run, for the examples only. I don't call it live: a public page would need my API key on the server, and every visitor's request would be billed to my account.</p>
<p>The fine-tuned card runs the evaluated inference config: 4-bit NF4 base, adapter not merged, float16 compute, greedy decoding. Through this Space, in batches of 8, it matched the published predictions on 1,623 of 1,633 test tickets (<a href="{AGREEMENT_REPORT_URL}" target="_blank">report</a>). This page sends one ticket at a time, so there is no batch padding, and an answer can occasionally differ from the batched results. The model loads on every request, so an answer takes a few seconds.</p>
</details>
</div>"""


def _button_label(e: dict) -> str:
    text = e["subject"] or e["body"]
    return text if len(text) <= 64 else text[:61].rstrip() + "…"


def build_demo(*, examples: list[dict],
               tfidf_fn: Callable[[str], tuple[dict, float]],
               adapter_fn: Callable[[str], tuple[dict | None, str, str | None, float]],
               classify_fn: Callable, predict_batch_fn: Callable) -> gr.Blocks:
    """tfidf_fn(text) -> (labels, ms). adapter_fn(text) -> (labels or None, raw, error, ms).
    classify_fn and predict_batch_fn are app.py's unchanged API functions."""

    def normalize(s) -> str:
        return (s or "").strip()

    def matched_example(subject, body, idx):
        if idx is None:
            return None
        e = examples[idx]
        if normalize(subject) == normalize(e["subject"]) and normalize(body) == normalize(e["body"]):
            return e
        return None

    def button_updates(selected_idx):
        return [gr.Button(elem_classes=["ex-btn"] + (["ex-noisy"] if e.get("noisy") else [])
                          + (["ex-selected"] if i == selected_idx else []))
                for i, e in enumerate(examples)]

    def select(i):
        e = examples[i]
        return [e["subject"] or "", e["body"], i, *button_updates(i)]

    def run_fast(subject, body, idx):
        if not body or not body.strip():
            raise gr.Error("The ticket body is required.")
        e = matched_example(subject, body, idx)
        text = build_ticket_text(subject, body)
        tf_labels, tf_ms = tfidf_fn(text)
        gold = e["gold_labels"] if e else None
        tf = card_html("tfidf", TFIDF_TITLE, TFIDF_SUB, f"CPU · {tf_ms:.0f} ms", labels=tf_labels, gold=gold)
        ft = card_html("ft", FT_TITLE, FT_SUB, "ZeroGPU · 4-bit", state="loading")
        if e:
            gpt = card_html("gpt", GPT_TITLE, GPT_SUB, "zero-shot · stored result",
                            labels=e["gpt4o_mini"], gold=gold)
        else:
            gpt = card_html("gpt", GPT_TITLE, GPT_SUB, "zero-shot · stored result", state="na")
        sel = examples.index(e) if e else None
        return [gr.HTML(gold_html(e), visible=e is not None), cards_html(tf, ft, gpt), tf, gpt, sel,
                *button_updates(sel)]

    def run_slow(subject, body, idx, tf, gpt):
        e = matched_example(subject, body, idx)
        text = build_ticket_text(subject, body)
        labels, raw, error, ms = adapter_fn(text)
        note = f"The output did not validate: {raw[:120]}" if error else ""
        ft = card_html("ft", FT_TITLE, FT_SUB, f"ZeroGPU · 4-bit · {ms / 1000:.1f} s", labels=labels,
                       gold=e["gold_labels"] if e else None, note=note)
        return cards_html(tf, ft, gpt)

    with gr.Blocks(title="Support ticket router") as demo:
        selected = gr.State(None)
        tf_state = gr.State("")
        gpt_state = gr.State("")
        gr.HTML(header_html())
        with gr.Row(elem_classes=["main-row"], equal_height=False):
            with gr.Column(scale=0, min_width=440, elem_classes=["left-col"]):
                with gr.Column(elem_classes=["input-card"]):
                    subject = gr.Textbox(label="Subject (optional)", lines=1)
                    body = gr.Textbox(label="Body", lines=7)
                    run = gr.Button("Classify", elem_id="classify-btn")
                gr.HTML('<div class="try-title">Try a test ticket</div>', elem_classes=["try-wrap"], min_height=0)
                with gr.Column(elem_classes=["examples-col"]):
                    buttons = [gr.Button(_button_label(e), elem_id=f"ex-{e['id']}",
                                         elem_classes=["ex-btn"] + (["ex-noisy"] if e.get("noisy") else []))
                               for e in examples]
            with gr.Column(scale=1, min_width=320, elem_classes=["right-col"]):
                gold = gr.HTML("", visible=False)
                cards = gr.HTML(cards_html(
                    card_html("tfidf", TFIDF_TITLE, TFIDF_SUB, "CPU", state="empty"),
                    card_html("ft", FT_TITLE, FT_SUB, "ZeroGPU · 4-bit", state="empty"),
                    card_html("gpt", GPT_TITLE, GPT_SUB, "zero-shot · stored result", state="empty"),
                ), min_height=0)
                gr.HTML(notes_html())

        fast_outputs = [gold, cards, tf_state, gpt_state, selected, *buttons]
        slow_inputs = [subject, body, selected, tf_state, gpt_state]
        run.click(run_fast, [subject, body, selected], fast_outputs, api_visibility="private", show_progress="hidden") \
           .success(run_slow, slow_inputs, cards, api_visibility="private", show_progress="hidden")
        for i, b in enumerate(buttons):
            b.click(lambda i=i: select(i), None, [subject, body, selected, *buttons], api_visibility="private", show_progress="hidden") \
             .success(run_fast, [subject, body, selected], fast_outputs, api_visibility="private", show_progress="hidden") \
             .success(run_slow, slow_inputs, cards, api_visibility="private", show_progress="hidden")

        # Unchanged API endpoints, on hidden components: /classify (CI smoke test) and /predict_batch.
        with gr.Row(visible=False):
            api_table = gr.Dataframe(headers=["field", "TF-IDF", "fine-tuned Qwen2.5-1.5B"], interactive=False)
            api_timing = gr.Markdown()
            api_run = gr.Button()
            batch_in = gr.Textbox()
            batch_out = gr.Textbox()
            batch_run = gr.Button()
        api_run.click(classify_fn, inputs=[subject, body], outputs=[api_table, api_timing], api_name="classify")
        batch_run.click(predict_batch_fn, inputs=batch_in, outputs=batch_out, api_name="predict_batch")
    return demo


def launch_kwargs(examples: list[dict]) -> dict:
    return {"css": BASE_CSS + "\n" + example_css(examples), "head": HEAD, "js": JS}


def timed(fn):
    """Helper for callers: run fn and return (result, elapsed_ms)."""
    t0 = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - t0) * 1000
