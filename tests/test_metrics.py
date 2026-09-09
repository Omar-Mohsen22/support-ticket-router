"""Unit tests for src/ticket_router/metrics.py, against a small fixture whose
expected numbers are worked out by hand in the comments below (run
`pytest` from the repo root -- pytest.ini adds src/ to the path).
"""

from ticket_router.metrics import INVALID, exact_match_rate, field_metrics, md_table, percentile

# --- Fixture: 8 rows, 3 classes (A, B, C) -----------------------------------
#
# row:  1    2    3    4    5    6    7    8
# true: A    A    A    B    B    C    C    C
# pred: A    A    B    B    C    C    C    A
# ok?   yes  yes  no   yes  no   yes  yes  no
#
# By hand:
#   correct rows = {1, 2, 4, 6, 7} -> 5 of 8
#   accuracy = 5/8 = 0.625
#
#   Class A: support = |{1,2,3}| = 3 (true==A)
#     TP (true=A,pred=A) = rows {1,2} = 2
#     FP (true!=A,pred=A) = row {8} = 1
#     FN (true=A,pred!=A) = row {3} = 1
#     precision = 2/3, recall = 2/3, F1 = 2/3 (precision==recall => F1==precision)
#
#   Class B: support = |{4,5}| = 2
#     TP (true=B,pred=B) = row {4} = 1
#     FP (true!=B,pred=B) = row {3} = 1
#     FN (true=B,pred!=B) = row {5} = 1
#     precision = 1/2, recall = 1/2, F1 = 1/2
#
#   Class C: support = |{6,7,8}| = 3
#     TP (true=C,pred=C) = rows {6,7} = 2
#     FP (true!=C,pred=C) = row {5} = 1
#     FN (true=C,pred!=C) = row {8} = 1
#     precision = 2/3, recall = 2/3, F1 = 2/3
#
#   macro_f1 = (2/3 + 1/2 + 2/3) / 3 = (4/6 + 3/6 + 4/6) / 3 = (11/6) / 3 = 11/18

Y_TRUE = ["A", "A", "A", "B", "B", "C", "C", "C"]
Y_PRED = ["A", "A", "B", "B", "C", "C", "C", "A"]


def test_field_metrics_accuracy():
    result = field_metrics(Y_TRUE, Y_PRED)
    assert result["n"] == 8
    assert result["accuracy"] == 5 / 8


def test_field_metrics_per_class():
    result = field_metrics(Y_TRUE, Y_PRED)
    a, b, c = result["per_class"]["A"], result["per_class"]["B"], result["per_class"]["C"]

    assert a["support"] == 3
    assert a["precision"] == 2 / 3
    assert a["recall"] == 2 / 3
    assert a["f1"] == 2 / 3

    assert b["support"] == 2
    assert b["precision"] == 0.5
    assert b["recall"] == 0.5
    assert b["f1"] == 0.5

    assert c["support"] == 3
    assert c["precision"] == 2 / 3
    assert c["recall"] == 2 / 3
    assert c["f1"] == 2 / 3


def test_field_metrics_macro_f1():
    result = field_metrics(Y_TRUE, Y_PRED)
    expected = (2 / 3 + 1 / 2 + 2 / 3) / 3
    assert abs(result["macro_f1"] - expected) < 1e-12
    assert abs(result["macro_f1"] - 11 / 18) < 1e-12


def test_field_metrics_length_mismatch_raises():
    try:
        field_metrics(["A", "B"], ["A"])
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- Fixture: the INVALID sentinel always counts as a miss ------------------
#
# true: A     B        C
# pred: A     INVALID  INVALID
#
# By hand:
#   accuracy = 1/3
#   Class A: support=1, TP=1, FP=0, FN=0 -> precision=1, recall=1, F1=1
#   Class B: support=1, TP=0, FP=0, FN=1 -> precision=0 (TP+FP==0), recall=0, F1=0
#   Class C: support=1, TP=0, FP=0, FN=1 -> precision=0, recall=0, F1=0
#   macro_f1 = (1 + 0 + 0) / 3 = 1/3

def test_field_metrics_invalid_sentinel_counts_as_miss():
    result = field_metrics(["A", "B", "C"], ["A", INVALID, INVALID])
    assert result["accuracy"] == 1 / 3
    assert abs(result["macro_f1"] - 1 / 3) < 1e-12
    assert result["per_class"]["A"]["f1"] == 1.0
    assert result["per_class"]["B"]["f1"] == 0.0
    assert result["per_class"]["C"]["f1"] == 0.0


# --- Fixture: exact_match_rate ------------------------------------------------
#
# 5 rows, each with queue/priority/type; row 3 differs on `type`, row 4 differs
# on `priority` -> 3/5 rows match on every field.

GOLD_ROWS = [
    {"queue": "A", "priority": "high", "type": "Incident"},
    {"queue": "A", "priority": "low", "type": "Request"},
    {"queue": "B", "priority": "high", "type": "Problem"},
    {"queue": "C", "priority": "medium", "type": "Incident"},
    {"queue": "B", "priority": "low", "type": "Request"},
]
PRED_ROWS = [
    {"queue": "A", "priority": "high", "type": "Incident"},
    {"queue": "A", "priority": "low", "type": "Request"},
    {"queue": "B", "priority": "high", "type": "Change"},   # type differs
    {"queue": "C", "priority": "low", "type": "Incident"},  # priority differs
    {"queue": "B", "priority": "low", "type": "Request"},
]


def test_exact_match_rate():
    rate = exact_match_rate(GOLD_ROWS, PRED_ROWS, ["queue", "priority", "type"])
    assert rate == 3 / 5


def test_exact_match_rate_length_mismatch_raises():
    try:
        exact_match_rate(GOLD_ROWS, PRED_ROWS[:2], ["queue"])
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- percentile: linear interpolation, matches numpy.percentile's default ----
#
# values = [10, 20, 30, 40] (already sorted, 4 points -> rank = p/100 * 3)
#   p50: rank = 1.5 -> between xs[1]=20 and xs[2]=30, frac=0.5 -> 25.0
#   p95: rank = 2.85 -> between xs[2]=30 and xs[3]=40, frac=0.85 -> 38.5

def test_percentile():
    values = [10, 20, 30, 40]
    assert percentile(values, 50) == 25.0
    assert percentile(values, 95) == 38.5


def test_percentile_single_value():
    assert percentile([42.0], 50) == 42.0
    assert percentile([42.0], 95) == 42.0


def test_percentile_empty_is_nan():
    import math
    assert math.isnan(percentile([], 50))


# --- md_table: basic rendering + pipe escaping --------------------------------

def test_md_table():
    out = md_table(["a", "b"], [[1, 2], ["x|y", None]])
    lines = out.splitlines()
    assert lines[0] == "| a | b |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| 1 | 2 |"
    assert lines[3] == "| x\\|y |  |"
