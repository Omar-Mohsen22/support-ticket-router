"""Step 19 -- comparative error analysis between the fine-tuned QLoRA adapter
(qlora-adapter-ckpt1500) and the TF-IDF baseline (tfidf-baseline). No model
calls, no GPU: reads each run's predictions_file path from results/results.json,
data/processed/test.parquet as gold, and results/results.json's own scoring
logic (reused from evaluate.py, not re-implemented) to build everything else.

THE CENTRAL QUESTION this analysis is built around: do the two models fail on
the SAME tickets, in the SAME direction? They share no inductive bias
(bag-of-words + logistic regression vs. a fine-tuned transformer) -- if they
nonetheless confuse the same class pairs, that is evidence the ceiling is a
property of the LABELS, not of either model's capacity. If they fail
differently, the ceiling is modelling capacity and there is headroom.

Produces, per field (queue/priority/type), entirely from the data:
  1. A raw-count confusion matrix for each run (rows=gold, columns=predicted).
  2. Each run's top confused (gold, predicted) pairs, side by side.
  3. Agreement statistics: both right, both wrong (further split into
     agreeing vs. disagreeing on the wrong label -- "same direction" is
     exactly "both wrong AND agree with each other"), and exactly one right.
  4. (queue only) Where IT Support's gold tickets actually went, for both
     runs -- tests the hypothesis that IT Support is being absorbed into
     Technical Support, stated as a hypothesis, not assumed.
  5. 10 misclassified-ticket samples per field with real ticket text, chosen
     to cover the worst-confused pairs (by combined count across both runs),
     not at random.

DIAGNOSIS ONLY -- this script and the report it writes propose no fix, no
retraining, no hyperparameter, and no label merge. That decision comes after
a human reads this.

Writes reports/error_analysis.md. Run from the repo root:
    .venv\\Scripts\\python.exe src\\ticket_router\\error_analysis.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

# Make `ticket_router` importable when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from ticket_router.evaluate import load_predictions
from ticket_router.metrics import INVALID, md_table

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RESULTS_DIR = REPO_ROOT / "results"
RESULTS_JSON_PATH = RESULTS_DIR / "results.json"
LABEL_MAP_PATH = PROCESSED_DIR / "label_map.json"
REPORTS_DIR = REPO_ROOT / "reports"
REPORT_PATH = REPORTS_DIR / "error_analysis.md"

RUN_A = "qlora-adapter-ckpt1500"  # the fine-tuned model under diagnosis
RUN_B = "tfidf-baseline"          # architecturally unrelated comparison point
SPLIT = "test"
TARGET_FIELDS = ["queue", "priority", "type"]
IT_SUPPORT_FIELD = "queue"
IT_SUPPORT_LABEL = "IT Support"
N_TOP_PAIRS = 10
N_SAMPLES_PER_FIELD = 10


def load_run_predictions(run_name: str, all_results: dict) -> dict:
    """Reads a run's predictions_file path from results/results.json (never
    hand-typed) and loads it with evaluate.load_predictions, so a missing
    prediction or an invalid label is classified exactly the way the harness
    itself classifies it (INVALID sentinel, not silently dropped)."""
    if run_name not in all_results:
        print(f"STOP: '{run_name}' not found in {RESULTS_JSON_PATH}.")
        raise SystemExit(1)
    predictions_path = REPO_ROOT / all_results[run_name]["predictions_file"]
    if not predictions_path.exists():
        print(f"STOP: {predictions_path} not found (referenced by '{run_name}' in results.json).")
        raise SystemExit(1)
    labels_by_id, _ = load_predictions(predictions_path)
    return labels_by_id


def predicted_field(labels_by_id: dict, ticket_id: str, field: str) -> str:
    if ticket_id not in labels_by_id:
        return INVALID
    return getattr(labels_by_id[ticket_id], field)


def build_confusion(gold_ids: list, gold_by_id: dict, labels_by_id: dict, field: str,
                     classes: list) -> dict:
    """dict[gold_class][pred_class] = count. Columns include every class in
    `classes` plus INVALID (only if it actually occurs for this run/field --
    an all-zero INVALID column would just be noise in the table)."""
    matrix = {g: Counter() for g in classes}
    for ticket_id in gold_ids:
        gold_label = gold_by_id[ticket_id][field]
        pred_label = predicted_field(labels_by_id, ticket_id, field)
        matrix[gold_label][pred_label] += 1
    return matrix


def confusion_columns(matrix: dict, classes: list) -> list:
    has_invalid = any(row.get(INVALID, 0) > 0 for row in matrix.values())
    return classes + ([INVALID] if has_invalid else [])


def confusion_to_md(matrix: dict, row_classes: list, columns: list) -> str:
    header = ["gold \\ predicted"] + columns
    rows = []
    for g in row_classes:
        row = [g] + [matrix[g].get(c, 0) for c in columns]
        rows.append(row)
    return md_table(header, rows)


def top_confused_pairs(matrix: dict, n: int) -> list:
    """Off-diagonal (gold, predicted, count) triples, ranked by count desc.
    Excludes gold == predicted (that is correct, not confusion)."""
    pairs = []
    for gold_label, row in matrix.items():
        for pred_label, count in row.items():
            if pred_label != gold_label and count > 0:
                pairs.append((gold_label, pred_label, count))
    pairs.sort(key=lambda t: -t[2])
    return pairs[:n]


def pairs_to_md(pairs: list) -> str:
    if not pairs:
        return "_(no confusion pairs -- every prediction on this field was correct or invalid)_"
    rows = [[g, p, c] for g, p, c in pairs]
    return md_table(["gold", "predicted", "count"], rows)


def agreement_stats(gold_ids: list, gold_by_id: dict, labels_a: dict, labels_b: dict,
                     field: str) -> dict:
    both_right = both_wrong_same = both_wrong_diff = only_a = only_b = 0
    for ticket_id in gold_ids:
        gold_label = gold_by_id[ticket_id][field]
        pred_a = predicted_field(labels_a, ticket_id, field)
        pred_b = predicted_field(labels_b, ticket_id, field)
        right_a = pred_a == gold_label
        right_b = pred_b == gold_label
        if right_a and right_b:
            both_right += 1
        elif right_a and not right_b:
            only_a += 1
        elif right_b and not right_a:
            only_b += 1
        else:  # both wrong
            if pred_a == pred_b:
                both_wrong_same += 1
            else:
                both_wrong_diff += 1
    n = len(gold_ids)
    return {
        "n": n,
        "both_right": both_right,
        "only_a_right": only_a,
        "only_b_right": only_b,
        "both_wrong_same_pred": both_wrong_same,
        "both_wrong_different_pred": both_wrong_diff,
        "both_wrong_total": both_wrong_same + both_wrong_diff,
    }


def agreement_to_md(stats: dict) -> str:
    n = stats["n"]

    def pct(x):
        return f"{x} ({x / n:.1%})" if n else f"{x} (0.0%)"

    rows = [
        ["both right", pct(stats["both_right"])],
        [f"only {RUN_A} right", pct(stats["only_a_right"])],
        [f"only {RUN_B} right", pct(stats["only_b_right"])],
        ["both wrong -- SAME predicted label (agree with each other)", pct(stats["both_wrong_same_pred"])],
        ["both wrong -- DIFFERENT predicted labels (disagree)", pct(stats["both_wrong_different_pred"])],
        ["both wrong -- total", pct(stats["both_wrong_total"])],
    ]
    return md_table(["category", "count (% of test)"], rows)


def it_support_fate(gold_ids: list, gold_by_id: dict, labels_a: dict, labels_b: dict) -> dict:
    """Where did every gold IT Support (queue) ticket actually get predicted,
    for each run? Reports the full distribution, not just the top guess --
    the hypothesis is stated, not assumed, and this must be able to say
    plainly if the ticket count did NOT predominantly go to Technical
    Support."""
    it_ids = [i for i in gold_ids if gold_by_id[i][IT_SUPPORT_FIELD] == IT_SUPPORT_LABEL]
    dist_a = Counter(predicted_field(labels_a, i, IT_SUPPORT_FIELD) for i in it_ids)
    dist_b = Counter(predicted_field(labels_b, i, IT_SUPPORT_FIELD) for i in it_ids)
    return {"n": len(it_ids), "ids": it_ids, "dist_a": dist_a, "dist_b": dist_b}


def fate_to_md(fate: dict) -> str:
    n = fate["n"]
    all_labels = sorted(set(fate["dist_a"]) | set(fate["dist_b"]))
    rows = []
    for label in all_labels:
        ca = fate["dist_a"].get(label, 0)
        cb = fate["dist_b"].get(label, 0)
        rows.append([
            label,
            f"{ca} ({ca / n:.1%})" if n else "0 (0.0%)",
            f"{cb} ({cb / n:.1%})" if n else "0 (0.0%)",
        ])
    rows.sort(key=lambda r: -int(r[1].split(" ")[0]))
    return md_table(["predicted queue", f"{RUN_A} (n={n})", f"{RUN_B} (n={n})"], rows)


def select_samples(field: str, gold_ids: list, gold_by_id: dict, labels_a: dict, labels_b: dict,
                    matrix_a: dict, matrix_b: dict, n: int) -> list:
    """Picks misclassified tickets to COVER the worst-confused pairs (by
    combined count across both runs), not at random. A "worst pair" here is a
    (gold, predicted) combination, counted once per run it occurs in and
    summed -- so a pair both models stumble into the same way ranks above one
    only a single run hits. Walks pairs in that order, pulling tickets whose
    error matches the pair from either run, until `n` distinct tickets are
    collected."""
    combined = Counter()
    for gold_label, row in matrix_a.items():
        for pred_label, count in row.items():
            if pred_label != gold_label and count > 0:
                combined[(gold_label, pred_label)] += count
    for gold_label, row in matrix_b.items():
        for pred_label, count in row.items():
            if pred_label != gold_label and count > 0:
                combined[(gold_label, pred_label)] += count

    ranked_pairs = [pair for pair, _ in combined.most_common()]

    selected = []
    selected_ids = set()
    # Round-robin across pairs, ONE ticket per pair per pass, so the sample
    # spreads across multiple worst-confused pairs instead of exhausting the
    # single top pair first (which would technically be "ranked by count" but
    # would not actually let a human see more than one failure pattern).
    # Repeats passes over the same pairs if fewer than `n` distinct pairs
    # exist or a pair runs out of matching tickets before its turn returns.
    progressed = True
    while len(selected) < n and ranked_pairs and progressed:
        progressed = False
        for gold_label, pred_label in ranked_pairs:
            if len(selected) >= n:
                break
            for ticket_id in gold_ids:
                if ticket_id in selected_ids:
                    continue
                if gold_by_id[ticket_id][field] != gold_label:
                    continue
                pred_a = predicted_field(labels_a, ticket_id, field)
                pred_b = predicted_field(labels_b, ticket_id, field)
                if pred_a != pred_label and pred_b != pred_label:
                    continue
                if pred_a == gold_label and pred_b == gold_label:
                    continue  # not actually misclassified by either run
                selected.append({
                    "id": ticket_id,
                    "gold": gold_label,
                    "matched_pair": f"{gold_label} -> {pred_label}",
                    "pred_a": pred_a,
                    "pred_b": pred_b,
                })
                selected_ids.add(ticket_id)
                progressed = True
                break  # at most one new ticket per pair per pass
    return selected


def build_report(gold: pd.DataFrame, all_results: dict, labels_a: dict, labels_b: dict,
                  label_map: dict) -> list:
    gold_ids = gold["id"].tolist()
    gold_by_id = gold.set_index("id")[TARGET_FIELDS].to_dict("index")
    text_by_id = gold.set_index("id")["text"].to_dict()

    lines = ["# Error analysis: qlora-adapter-ckpt1500 vs. tfidf-baseline\n"]
    lines.append(
        f"Generated by `src/ticket_router/error_analysis.py` from `results/results.json` "
        f"(`{RUN_A}` and `{RUN_B}`, both scored on the full `{SPLIT}` split, n={len(gold_ids)}) "
        "and `data/processed/test.parquet` as gold. No hand-typed numbers -- re-run the script "
        "after any future scoring run to regenerate this file.\n"
    )
    lines.append(
        "**Central question:** do the two models fail on the SAME tickets, in the SAME "
        "direction? They share no inductive bias -- bag-of-words + logistic regression "
        f"(`{RUN_B}`) versus a fine-tuned transformer (`{RUN_A}`). If they nonetheless confuse "
        "the same class pairs, that is evidence the ceiling is a property of the LABELS, not of "
        "either model. If they fail differently, the ceiling is modelling capacity and there is "
        "headroom. **This report is diagnosis only -- it proposes no fix, retraining, "
        "hyperparameter, or label merge.**\n"
    )

    all_agreement = {}
    all_matrices = {}
    for field in TARGET_FIELDS:
        classes = label_map[field]
        matrix_a = build_confusion(gold_ids, gold_by_id, labels_a, field, classes)
        matrix_b = build_confusion(gold_ids, gold_by_id, labels_b, field, classes)
        all_matrices[field] = (matrix_a, matrix_b)
        columns_a = confusion_columns(matrix_a, classes)
        columns_b = confusion_columns(matrix_b, classes)

        lines.append(f"## `{field}`\n")

        lines.append(f"### Confusion matrix -- `{RUN_A}` (rows=gold, columns=predicted, raw counts)\n")
        lines.append(confusion_to_md(matrix_a, classes, columns_a))
        lines.append("")

        lines.append(f"### Confusion matrix -- `{RUN_B}` (rows=gold, columns=predicted, raw counts)\n")
        lines.append(confusion_to_md(matrix_b, classes, columns_b))
        lines.append("")

        pairs_a = top_confused_pairs(matrix_a, N_TOP_PAIRS)
        pairs_b = top_confused_pairs(matrix_b, N_TOP_PAIRS)
        lines.append(f"### Top confused pairs -- {RUN_A} vs. {RUN_B} (side by side, ranked by count)\n")
        max_len = max(len(pairs_a), len(pairs_b))
        rows = []
        for i in range(max_len):
            a = f"{pairs_a[i][0]} -> {pairs_a[i][1]} ({pairs_a[i][2]})" if i < len(pairs_a) else ""
            b = f"{pairs_b[i][0]} -> {pairs_b[i][1]} ({pairs_b[i][2]})" if i < len(pairs_b) else ""
            rows.append([i + 1, a, b])
        lines.append(md_table(["rank", RUN_A, RUN_B], rows))
        lines.append("")

        stats = agreement_stats(gold_ids, gold_by_id, labels_a, labels_b, field)
        all_agreement[field] = stats
        lines.append("### Agreement statistics\n")
        lines.append(agreement_to_md(stats))
        wrong_together_share = (
            stats["both_wrong_total"] / (stats["n"] - stats["both_right"])
            if (stats["n"] - stats["both_right"]) > 0 else 0.0
        )
        lines.append(
            f"\nOf all rows where at least one run was wrong, {stats['both_wrong_total']} "
            f"({wrong_together_share:.1%}) were wrong on BOTH runs; of those, "
            f"{stats['both_wrong_same_pred']} landed on the exact same wrong predicted label "
            "(same-direction failure) and "
            f"{stats['both_wrong_different_pred']} landed on different wrong labels.\n"
        )

        if field == IT_SUPPORT_FIELD:
            fate = it_support_fate(gold_ids, gold_by_id, labels_a, labels_b)
            lines.append(f"### Hypothesis test: where did `{IT_SUPPORT_LABEL}`'s {fate['n']} gold tickets actually go?\n")
            lines.append(
                f"Stated hypothesis (from `{RUN_A}`'s per-class numbers in results.json: "
                "precision 0.7273, recall 0.0825 for IT Support; precision 0.4569, recall 0.8270 "
                "for Technical Support): IT Support is being absorbed into Technical Support.\n"
            )
            lines.append(fate_to_md(fate))
            top_a_label, top_a_count = fate["dist_a"].most_common(1)[0]
            top_a_share = top_a_count / fate["n"] if fate["n"] else 0.0
            verdict = (
                f"**Hypothesis holds for `{RUN_A}`**: {top_a_count}/{fate['n']} ({top_a_share:.1%}) "
                f"of gold IT Support tickets were predicted as `{top_a_label}`."
                if top_a_label == "Technical Support" and top_a_share > 0.5
                else
                f"**Hypothesis does NOT hold as stated for `{RUN_A}`**: the single largest "
                f"destination for gold IT Support tickets is `{top_a_label}` "
                f"({top_a_count}/{fate['n']}, {top_a_share:.1%}), not predominantly Technical "
                "Support -- reporting this plainly rather than fitting the data to the hypothesis."
            )
            lines.append(f"\n{verdict}\n")

        samples = select_samples(field, gold_ids, gold_by_id, labels_a, labels_b,
                                  matrix_a, matrix_b, N_SAMPLES_PER_FIELD)
        lines.append(
            f"### {len(samples)} misclassified sample ticket(s) for `{field}` "
            "(chosen to cover the worst-confused pairs, not at random)\n"
        )
        for i, s in enumerate(samples, start=1):
            lines.append(
                f"**#{i}** `{s['id']}` -- gold `{field}` = `{s['gold']}` "
                f"(targets confusion pair `{s['matched_pair']}`)\n"
            )
            lines.append(f"- `{RUN_A}` predicted: `{s['pred_a']}`")
            lines.append(f"- `{RUN_B}` predicted: `{s['pred_b']}`\n")
            lines.append("```\n" + text_by_id[s["id"]] + "\n```\n")

    return lines, all_agreement, all_matrices


def main() -> None:
    for p in (PROCESSED_DIR / f"{SPLIT}.parquet", RESULTS_JSON_PATH, LABEL_MAP_PATH):
        if not p.exists():
            print(f"STOP: {p} not found.")
            raise SystemExit(1)

    gold = pd.read_parquet(PROCESSED_DIR / f"{SPLIT}.parquet")
    all_results = json.loads(RESULTS_JSON_PATH.read_text(encoding="utf-8"))
    label_map = json.loads(LABEL_MAP_PATH.read_text(encoding="utf-8"))

    for run_name in (RUN_A, RUN_B):
        gold_split = all_results.get(run_name, {}).get("gold_split")
        if gold_split and gold_split.get("split") == SPLIT and gold_split.get("limit") is None:
            expected_hash = gold_split["id_sequence_sha256"]
            from ticket_router.evaluate import compute_gold_hash
            actual_hash = compute_gold_hash(gold["id"].tolist())
            if expected_hash != actual_hash:
                print(f"STOP: '{run_name}' was scored against a different {SPLIT}.parquet than "
                      "the one on disk right now (gold_split hash mismatch). Re-score before "
                      "running this analysis -- see evaluate.py's gold-hash check.")
                raise SystemExit(1)

    print(f"Loading predictions for '{RUN_A}' and '{RUN_B}' ...")
    labels_a = load_run_predictions(RUN_A, all_results)
    labels_b = load_run_predictions(RUN_B, all_results)

    print(f"Gold: {len(gold)} rows from {SPLIT}.parquet")
    lines, all_agreement, _ = build_report(gold, all_results, labels_a, labels_b, label_map)

    for field in TARGET_FIELDS:
        s = all_agreement[field]
        print(f"{field}: both_right={s['both_right']} both_wrong_same={s['both_wrong_same_pred']} "
              f"both_wrong_diff={s['both_wrong_different_pred']} only_{RUN_A}={s['only_a_right']} "
              f"only_{RUN_B}={s['only_b_right']}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
