# ticket-router: TF-IDF serving image (step-27). Python minor version matches the dev venv (3.12).
# The data and the model artifact are rebuilt from the pinned dataset revision at build time, and
# the build fails if the regenerated test split is not the one the published results used.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=7860

# Hugging Face Docker Spaces run the container as uid 1000.
RUN useradd --create-home --uid 1000 user
WORKDIR /app

COPY requirements-serve.txt .
RUN pip install -r requirements-serve.txt

COPY pytest.ini .
COPY src/ src/
COPY tests/ tests/
COPY data/ data/
COPY results/ results/

# Download the pinned dataset revision, rebuild the splits, check them against results.json,
# fit the TF-IDF artifact, then drop the ~53 MB of raw CSVs.
RUN python src/ticket_router/inspect_data.py \
 && python src/ticket_router/make_dataset.py \
 && python src/ticket_router/check_gold_hash.py \
 && python src/ticket_router/predictors/tfidf_baseline.py --artifact-only \
 && rm -f data/raw/*.csv \
 && chown -R user:user /app

USER user
EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn ticket_router.api.app:app --app-dir src --host 0.0.0.0 --port ${PORT:-7860}"]
