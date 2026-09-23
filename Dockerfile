# ticket-router: TF-IDF serving image (step-27). Python minor version matches the dev venv (3.12).
# Serves the COMMITTED TF-IDF artifact -- the exact model behind the published tfidf-baseline
# numbers -- after verifying its sha256. It is never refitted here: a Linux refit on the same data
# is not bit-identical to it (see PROGRESS.md step-27). The data is still rebuilt from the pinned
# dataset revision, because the tests need test.parquet, and the build fails if the rebuilt test
# split is not the one the published results used.
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
COPY models/tfidf/ models/tfidf/

RUN python src/ticket_router/check_artifact.py \
 && python src/ticket_router/inspect_data.py \
 && python src/ticket_router/make_dataset.py \
 && python src/ticket_router/check_gold_hash.py \
 && rm -f data/raw/*.csv \
 && chown -R user:user /app

USER user
EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn ticket_router.api.app:app --app-dir src --host 0.0.0.0 --port ${PORT:-7860}"]
