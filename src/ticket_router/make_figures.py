"""Step 32 -- figures for the README, built only from committed result files, so they can be
rebuilt at any time and never carry a hand-typed number.

Inputs:
  - results/results.json: macro-F1 per field for the three headline runs (TF-IDF baseline,
    zero-shot gpt-4o-mini, the QLoRA adapter), the same numbers as README's headline table;
  - reports/adapter_zerogpu_4bit_full.md: the demo's agreement with the published adapter
    predictions on all three fields, for the evaluated 4-bit config and the earlier bf16
    merged setup. That report is not in results.json, so its table is parsed here, and the
    script stops if the table is not found.

Not drawn: latency and cost. results.json has a cost only for TF-IDF (cpu-local, measured);
the gpt-4o-mini and adapter costs are 0 meaning UNMEASURED, and the three latencies come from
different hardware and methods (README, Notes), so a chart would compare unlike things.

Every figure is written twice, for light and dark backgrounds (GitHub's #ffffff and #0d1117),
as PNG at 2x scale. Each model keeps one color: TF-IDF #0891B2 and gpt-4o-mini #C2850C in both
modes; the fine-tuned model is the demo's purple #6D28D9 on light and #8B5CF6 (same hue family)
on dark, where #6D28D9's contrast is only 2.66:1. Both palettes pass the dataviz palette checks
on their background (lightness, chroma, colorblind and normal-vision separation, contrast), and
every bar also carries its value as a text label.

Run from the repo root:
    .venv\\Scripts\\python.exe src\\ticket_router\\make_figures.py [--out docs/images]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_JSON_PATH = REPO_ROOT / "results" / "results.json"
AGREEMENT_REPORT_PATH = REPO_ROOT / "reports" / "adapter_zerogpu_4bit_full.md"
DEFAULT_OUT = REPO_ROOT / "docs" / "images"

FIELDS = ["queue", "priority", "type"]
# Fixed order per model, in every figure; colors are per theme (THEMES[mode]["models"]).
MODELS = [
    ("tfidf-baseline", "TF-IDF + logistic regression"),
    ("api-gpt4o-mini-full-test", "gpt-4o-mini, zero-shot"),
    ("qlora-adapter-ckpt1500", "Qwen2.5-1.5B + QLoRA (fine-tuned)"),
]
# Drawn top to bottom.
AGREEMENT_ROWS = [
    ("bf16 merged, ZeroGPU (earlier run)", "First demo setup\nbf16, adapter merged, batch 16"),
    ("4-bit, ZeroGPU (this run)", "Evaluated config\n4-bit NF4, unmerged, batch 8"),
]
THEMES = {
    "light": {"surface": "#ffffff", "ink": "#1f2328", "muted": "#59636e", "grid": "#e6e8eb",
              "earlier": "#8c959f", "models": ["#0891B2", "#C2850C", "#6D28D9"]},
    "dark": {"surface": "#0d1117", "ink": "#e6edf3", "muted": "#9198a1", "grid": "#262c36",
             "earlier": "#6e7681", "models": ["#0891B2", "#C2850C", "#8B5CF6"]},
}
DPI = 200  # figures are laid out at 100 dpi, so 200 dpi is 2x


def load_f1() -> dict[str, dict[str, float]]:
    results = json.loads(RESULTS_JSON_PATH.read_text(encoding="utf-8"))
    out = {}
    for run, _ in MODELS:
        if run not in results:
            raise SystemExit(f"STOP: {run} not in {RESULTS_JSON_PATH}.")
        out[run] = {f: results[run]["fields"][f]["macro_f1"] for f in FIELDS}
    return out


def load_agreement() -> tuple[int, dict[str, int]]:
    text = AGREEMENT_REPORT_PATH.read_text(encoding="utf-8")
    m = re.search(r"\): (\d+) test tickets", text)
    if not m:
        raise SystemExit(f"STOP: ticket count not found in {AGREEMENT_REPORT_PATH}.")
    n = int(m.group(1))
    counts = {}
    for row, _ in AGREEMENT_ROWS:
        m = re.search(rf"^\| {re.escape(row)} \|.*\| (\d+) \([\d.]+%\) \|$", text, re.MULTILINE)
        if not m:
            raise SystemExit(f"STOP: row {row!r} not found in {AGREEMENT_REPORT_PATH}.")
        counts[row] = int(m.group(1))
    return n, counts


def style_axes(ax, t: dict) -> None:
    ax.set_facecolor(t["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["grid"])
    ax.tick_params(colors=t["muted"], length=0, labelsize=9)
    ax.grid(axis="y", color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def header(fig, t: dict, title: str, subtitle: str) -> None:
    fig.text(0.02, 0.965, title, ha="left", va="top", fontsize=13, fontweight="bold", color=t["ink"])
    fig.text(0.02, 0.895, subtitle, ha="left", va="top", fontsize=9.5, color=t["muted"])


def legend(fig, t: dict, y: float) -> None:
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in t["models"]]
    leg = fig.legend(handles, [label for _, label in MODELS], loc="upper left",
                     bbox_to_anchor=(0.015, y), ncol=3, frameon=False, fontsize=9,
                     handlelength=1.0, handleheight=1.0, columnspacing=1.6)
    for text in leg.get_texts():
        text.set_color(t["ink"])


def source(fig, t: dict, text: str) -> None:
    fig.text(0.02, 0.02, text, ha="left", va="bottom", fontsize=8, color=t["muted"])


def label_bars(ax, bars, values, t: dict, fmt: str = "{:.3f}") -> None:
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.015, fmt.format(v),
                ha="center", va="bottom", fontsize=8.5, color=t["ink"])


def f1_panels(f1: dict, t: dict):
    """One small panel per field, three bars each, one shared y-axis."""
    fig, axes = plt.subplots(1, 3, figsize=(9, 4.2), sharey=True, facecolor=t["surface"])
    fig.subplots_adjust(left=0.06, right=0.98, top=0.70, bottom=0.12, wspace=0.08)
    for ax, field in zip(axes, FIELDS):
        style_axes(ax, t)
        values = [f1[run][field] for run, _ in MODELS]
        bars = ax.bar(range(3), values, width=0.72, color=t["models"],
                      edgecolor=t["surface"], linewidth=1.5)
        label_bars(ax, bars, values, t)
        ax.set_xticks([])
        ax.set_title(field, fontsize=10.5, color=t["ink"], pad=6)
        ax.set_ylim(0, 1)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    axes[0].set_ylabel("macro-F1", fontsize=9, color=t["muted"])
    header(fig, t, "Macro-F1 per field on the frozen test split",
           "1,633 tickets. Higher is better. Same split, same metric code for all three models.")
    legend(fig, t, 0.85)
    source(fig, t, "Source: results/results.json")
    return fig


def agreement(n: int, counts: dict, t: dict):
    """The demo's agreement with the published adapter predictions, on all three fields."""
    fig, ax = plt.subplots(figsize=(9, 3.0), facecolor=t["surface"])
    # The x-axis stops at 100%; the right margin holds the value labels, drawn unclipped.
    fig.subplots_adjust(left=0.27, right=0.76, top=0.76, bottom=0.18)
    style_axes(ax, t)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=t["grid"], linewidth=0.8)
    colors = [t["earlier"], t["models"][2]]
    ys = range(len(AGREEMENT_ROWS))
    shares = [counts[row] / n for row, _ in AGREEMENT_ROWS]
    ax.barh(ys, shares, height=0.55, color=colors, edgecolor=t["surface"], linewidth=1.5)
    for y, (row, _), share in zip(ys, AGREEMENT_ROWS, shares):
        ax.text(share + 0.015, y, f"{counts[row]:,} / {n:,} ({share:.1%})", va="center",
                ha="left", fontsize=9, color=t["ink"], clip_on=False)
    ax.set_yticks(list(ys))
    ax.set_yticklabels([label for _, label in AGREEMENT_ROWS], fontsize=9, color=t["ink"])
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    header(fig, t, "The demo reproduces the evaluated model",
           f"Share of {n:,} test tickets where the deployed demo matches the published adapter "
           "predictions on all three fields.")
    source(fig, t, "Source: reports/adapter_zerogpu_4bit_full.md")
    return fig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    f1 = load_f1()
    n, counts = load_agreement()
    plt.rcParams["font.family"] = "DejaVu Sans"
    for mode, t in THEMES.items():
        for name, fig in [("f1_by_field", f1_panels(f1, t)), ("demo_agreement", agreement(n, counts, t))]:
            path = args.out / f"{name}_{mode}.png"
            fig.savefig(path, dpi=DPI, facecolor=t["surface"])
            plt.close(fig)
            print(f"wrote {path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}")


if __name__ == "__main__":
    main()
