"""Pure metric functions for the evaluation harness -- no file I/O here, so
they can be unit-tested directly against a small hand-written fixture (see
tests/test_metrics.py).

`INVALID` is the sentinel used everywhere a gold ticket has no usable
prediction (missing line, unparseable JSON, unmatched id, or a label outside
the allowed set): it is guaranteed to never equal a real label, so it always
counts as a miss in accuracy / macro-F1 / exact-match rather than being
silently excluded from the denominator.
"""

from __future__ import annotations

import math

INVALID = "__INVALID__"


def field_metrics(y_true: list[str], y_pred: list[str]) -> dict:
    """Per-class precision/recall/F1/support, plus accuracy and macro-F1, for
    one target field (e.g. queue). Classes are those observed in y_true;
    macro-F1 averages each class's F1 unweighted (F1 = 0 for a class with no
    predicted-correct examples, per the standard convention when
    precision + recall == 0).
    """
    if len(y_true) != len(y_pred):
        raise ValueError(f"y_true and y_pred must be the same length ({len(y_true)} != {len(y_pred)})")
    n = len(y_true)
    classes = sorted(set(y_true))

    per_class = {}
    f1_values = []
    for c in classes:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == c and p == c)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != c and p == c)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == c and p != c)
        support = tp + fn
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        per_class[c] = {"support": support, "precision": precision, "recall": recall, "f1": f1}
        f1_values.append(f1)

    accuracy = sum(1 for t, p in zip(y_true, y_pred) if t == p) / n if n else 0.0
    macro_f1 = sum(f1_values) / len(f1_values) if f1_values else 0.0

    return {"accuracy": accuracy, "macro_f1": macro_f1, "per_class": per_class, "n": n}


def exact_match_rate(gold_rows: list[dict], pred_rows: list[dict], fields: list[str]) -> float:
    """Fraction of rows where every field in `fields` matches between gold_rows
    and pred_rows (same order, same length -- caller aligns them, e.g. both
    already indexed by the same gold id order)."""
    if len(gold_rows) != len(pred_rows):
        raise ValueError("gold_rows and pred_rows must be the same length")
    n = len(gold_rows)
    if n == 0:
        return 0.0
    matches = sum(
        1 for g, p in zip(gold_rows, pred_rows)
        if all(g[f] == p[f] for f in fields)
    )
    return matches / n


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile (matches numpy.percentile's default
    'linear' method), implemented locally so metrics.py has no dependency."""
    if not values:
        return math.nan
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    rank = (p / 100) * (len(xs) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return xs[int(rank)]
    frac = rank - lo
    return xs[lo] + (xs[hi] - xs[lo]) * frac


def md_table(headers: list[str], rows: list[list]) -> str:
    """Render rows as a GitHub-flavored markdown table."""

    def esc(v: object) -> str:
        s = "" if v is None else str(v)
        return s.replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(esc(v) for v in row) + " |")
    return "\n".join(lines)
