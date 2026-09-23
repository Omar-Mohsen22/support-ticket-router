"""Step 27 -- fail loudly if models/tfidf/model.joblib is not the artifact
meta.json describes (sha256 mismatch). The Docker build runs this, so the image
can only ever serve the exact evaluated artifact.

Run from the repo root:
    .venv\\Scripts\\python.exe src\\ticket_router\\check_artifact.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ticket_router.predictors.tfidf_baseline import MODEL_META_PATH, MODEL_PATH


def main() -> None:
    expected = json.loads(MODEL_META_PATH.read_text(encoding="utf-8")).get("model_sha256")
    actual = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
    print(f"meta.json model_sha256: {expected}")
    print(f"model.joblib sha256:    {actual}")
    if expected != actual:
        print("STOP: models/tfidf/model.joblib does not match meta.json.")
        raise SystemExit(1)
    print("OK: artifact matches meta.json.")


if __name__ == "__main__":
    main()
