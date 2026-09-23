"""Serving API tests (step-26). Needs the TF-IDF artifact:
    python src/ticket_router/predictors/tfidf_baseline.py --artifact-only

Locally, a missing artifact skips these tests. With CI=true it fails the run
instead (step-27): in CI the artifact is built into the image, so a missing
one means the build is broken, not that the tests don't apply.
"""

import json
import os
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from ticket_router.predictors.tfidf_baseline import MODEL_PATH

REPO_ROOT = Path(__file__).resolve().parents[1]
LABEL_MAP = json.loads((REPO_ROOT / "data" / "processed" / "label_map.json").read_text(encoding="utf-8"))
PARITY_ROWS = 200
MISSING_ARTIFACT = f"TF-IDF artifact missing at {MODEL_PATH} -- run tfidf_baseline.py --artifact-only first"

if not MODEL_PATH.exists() and os.environ.get("CI", "").lower() == "true":
    pytest.fail(f"CI=true: {MISSING_ARTIFACT}", pytrace=False)

pytestmark = pytest.mark.skipif(not MODEL_PATH.exists(), reason=MISSING_ARTIFACT)


@pytest.fixture(scope="module")
def client():
    from ticket_router.api.app import app

    with TestClient(app) as c:  # the context manager runs the lifespan (model load)
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "model": "tfidf-baseline", "model_loaded": True}


def test_predict_returns_valid_labels(client):
    r = client.post("/predict", json={"subject": "Refund request", "body": "I was charged twice."})
    assert r.status_code == 200
    data = r.json()
    for field in ("queue", "priority", "type"):
        assert data[field] in LABEL_MAP[field]
    assert data["model"] == "tfidf-baseline"
    assert data["latency_ms"] >= 0


@pytest.mark.parametrize("payload", [
    {"subject": "No body here"},
    {"subject": "Empty body", "body": ""},
    {"subject": "Blank body", "body": "   "},
])
def test_missing_or_empty_body_is_422(client, payload):
    assert client.post("/predict", json=payload).status_code == 422


def test_absent_empty_and_blank_subject_all_mean_body_alone(client):
    body = "My laptop will not connect to the office VPN since this morning."
    labels = lambda r: {k: r.json()[k] for k in ("queue", "priority", "type")}  # noqa: E731
    responses = [
        client.post("/predict", json={"body": body}),
        client.post("/predict", json={"subject": "", "body": body}),
        client.post("/predict", json={"subject": "   ", "body": body}),
        client.post("/predict", json={"subject": None, "body": body}),
    ]
    assert all(r.status_code == 200 for r in responses)
    assert all(labels(r) == labels(responses[0]) for r in responses)


def test_parity_with_published_predictions(client):
    """The API must reproduce results/tfidf-baseline.predictions.jsonl exactly."""
    test = pd.read_parquet(REPO_ROOT / "data" / "processed" / "test.parquet").head(PARITY_ROWS)
    published = {}
    with open(REPO_ROOT / "results" / "tfidf-baseline.predictions.jsonl", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            published[row["id"]] = {k: row[k] for k in ("queue", "priority", "type")}

    mismatches = []
    for ticket in test.itertuples():
        subject = ticket.subject if isinstance(ticket.subject, str) else None
        r = client.post("/predict", json={"subject": subject, "body": ticket.body})
        assert r.status_code == 200, (ticket.id, r.text)
        got = {k: r.json()[k] for k in ("queue", "priority", "type")}
        if got != published[ticket.id]:
            mismatches.append((ticket.id, got, published[ticket.id]))
    assert not mismatches, f"{len(mismatches)} of {PARITY_ROWS} rows differ: {mismatches[:10]}"
