"""Step 26 -- FastAPI serving, phase 1: the TF-IDF baseline only.

Loads models/tfidf/ (written by predictors/tfidf_baseline.py) ONCE at startup
and refuses to start if it is missing. Input text is built with the same
ticket_text.build_ticket_text() that built every training example, and every
response is validated against the shared label set (schema.TicketLabels,
built from data/processed/label_map.json) -- no labels are defined here.

Run from the repo root:
    .venv\\Scripts\\python.exe -m uvicorn ticket_router.api.app:app --app-dir src --port 8000
"""

from __future__ import annotations

import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import joblib
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, field_validator

# Make `ticket_router` importable when uvicorn is started without --app-dir src.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ticket_router.predictors.tfidf_baseline import MODEL_PATH, RUN_NAME, TARGET_FIELDS
from ticket_router.schema import TicketLabels
from ticket_router.ticket_text import build_ticket_text


class PredictRequest(BaseModel):
    subject: str | None = None
    body: str

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body must not be empty or whitespace-only")
        return value


class PredictResponse(TicketLabels):
    model: str
    latency_ms: float


class HealthResponse(BaseModel):
    status: str
    model: str
    model_loaded: bool


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not MODEL_PATH.exists():
        raise RuntimeError(
            f"TF-IDF model artifact not found at {MODEL_PATH}. It is committed to git "
            "(models/tfidf/) -- restore it from there. Rebuilding it with tfidf_baseline.py "
            "--artifact-only gives a model that is not bit-identical on other platforms."
        )
    artifact = joblib.load(MODEL_PATH)
    app.state.vectorizer = artifact["vectorizer"]
    app.state.classifiers = artifact["classifiers"]
    yield
    app.state.vectorizer = None
    app.state.classifiers = None


app = FastAPI(title="ticket-router", lifespan=lifespan)


# Step 31: a visitor opening the Space's root URL lands on the interactive docs, not a 404.
@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    loaded = getattr(app.state, "vectorizer", None) is not None
    return HealthResponse(status="ok", model=RUN_NAME, model_loaded=loaded)


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest) -> PredictResponse:
    t0 = time.perf_counter()
    X = app.state.vectorizer.transform([build_ticket_text(request.subject, request.body)])
    labels = {field: str(app.state.classifiers[field].predict(X)[0]) for field in TARGET_FIELDS}
    latency_ms = (time.perf_counter() - t0) * 1000
    # Validating through PredictResponse (a TicketLabels subclass) rejects any label
    # outside label_map.json with a 500, rather than returning it.
    return PredictResponse(**labels, model=RUN_NAME, latency_ms=latency_ms)
