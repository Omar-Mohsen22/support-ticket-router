"""Step 30 -- run the demo UI locally without a GPU, to check the layout.

TF-IDF is real: the committed artifact runs through the same build_ticket_text and the same
predict calls as app.py. The adapter is a STUB: after a short delay it returns fixed
placeholder labels. The stored gpt-4o-mini labels come from the same examples.json content that
deploy_demo.py builds.

This needs gradio==6.28.0, which the project venv does not have (only the Space does). Run it
from a separate environment with gradio plus the requirements-serve.txt pins. From the repo root:
    python deploy/demo/preview_ui.py            (serves on http://127.0.0.1:7861)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "deploy" / "demo"))
sys.path.insert(0, str(REPO_ROOT / "deploy" / "space"))

import joblib  # noqa: E402

from deploy_demo import build_examples  # noqa: E402
from ticket_router.predictors.tfidf_baseline import MODEL_PATH, TARGET_FIELDS  # noqa: E402
from ui import build_demo, launch_kwargs  # noqa: E402

STUB_DELAY_S = 3.0
STUB_LABELS = {"queue": "Technical Support", "priority": "medium", "type": "Incident"}

tfidf = joblib.load(MODEL_PATH)
examples = build_examples()


def tfidf_fn(text: str) -> tuple[dict, float]:
    t0 = time.perf_counter()
    X = tfidf["vectorizer"].transform([text])
    labels = {f: str(tfidf["classifiers"][f].predict(X)[0]) for f in TARGET_FIELDS}
    return labels, (time.perf_counter() - t0) * 1000


def adapter_stub(text: str):
    t0 = time.perf_counter()
    time.sleep(STUB_DELAY_S)
    return dict(STUB_LABELS), '{"stub": true}', None, (time.perf_counter() - t0) * 1000


def classify_stub(subject: str, body: str):
    return [[f, "-", STUB_LABELS[f]] for f in TARGET_FIELDS], "stub"


def predict_batch_stub(payload: str) -> str:
    return "{}"


if __name__ == "__main__":
    demo = build_demo(examples=examples, tfidf_fn=tfidf_fn, adapter_fn=adapter_stub,
                      classify_fn=classify_stub, predict_batch_fn=predict_batch_stub)
    demo.queue().launch(server_name="127.0.0.1", server_port=7861, **launch_kwargs(examples))
