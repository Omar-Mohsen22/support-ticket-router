"""build_ticket_text must reproduce the committed splits' `text` column exactly."""

from pathlib import Path

import pandas as pd
import pytest

from ticket_router.ticket_text import build_ticket_text, has_subject

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"


def test_subject_and_body_joined_by_newline():
    assert build_ticket_text("Login fails", "Cannot sign in.") == "Login fails\nCannot sign in."


@pytest.mark.parametrize("subject", [None, float("nan"), "", "   ", "\n\t"])
def test_missing_or_blank_subject_means_body_alone(subject):
    assert not has_subject(subject)
    assert build_ticket_text(subject, "Cannot sign in.") == "Cannot sign in."


@pytest.mark.parametrize("split", ["test", "val"])
def test_matches_committed_text_column(split):
    df = pd.read_parquet(PROCESSED_DIR / f"{split}.parquet")
    rebuilt = [build_ticket_text(s, b) for s, b in zip(df["subject"], df["body"])]
    assert rebuilt == df["text"].tolist()
    assert df["subject"].map(has_subject).tolist() == df["has_subject"].tolist()
