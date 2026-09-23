"""Step 27 diagnosis -- why the Linux-built TF-IDF model disagrees with the
Windows-built predictions. Observes only: changes nothing about how the model
is built or served.

Prints, in a fixed format that is easy to diff between machines:
  1. sha256 of train.parquet and val.parquet over `text` + queue/priority/type,
     in row order.
  2. A refit with tfidf_baseline.fit_models() (unchanged), with every
     ConvergenceWarning recorded, then n_iter_ vs max_iter for each one-vs-rest
     LogisticRegression. The artifact in models/tfidf/ is also read, so its
     n_iter_ can be compared with the refit.

Run from the repo root:
    .venv\\Scripts\\python.exe src\\ticket_router\\diagnose_tfidf.py
"""

from __future__ import annotations

import hashlib
import platform
import sys
import warnings
from pathlib import Path

import joblib
import pandas as pd
from sklearn.exceptions import ConvergenceWarning

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ticket_router.predictors.tfidf_baseline import (
    LOGREG_CONFIG, MODEL_PATH, PROCESSED_DIR, TARGET_FIELDS, fit_models,
)

HASH_COLUMNS = ["text", *TARGET_FIELDS]


def split_hash(df: pd.DataFrame) -> str:
    h = hashlib.sha256()
    for row in df[HASH_COLUMNS].itertuples(index=False):
        h.update("\x1f".join(row).encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()


def n_iter_report(classifiers: dict) -> dict:
    return {
        field: {cls: int(est.n_iter_[0]) for cls, est in zip(clf.classes_, clf.estimators_)}
        for field, clf in classifiers.items()
    }


def main() -> None:
    print(f"DIAG platform: {platform.platform()} | python {platform.python_version()}")
    train = pd.read_parquet(PROCESSED_DIR / "train.parquet")
    val = pd.read_parquet(PROCESSED_DIR / "val.parquet")
    print(f"DIAG train rows={len(train)} sha256={split_hash(train)}")
    print(f"DIAG val   rows={len(val)} sha256={split_hash(val)}")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _, classifiers, _ = fit_models(train)
    convergence = [w for w in caught if issubclass(w.category, ConvergenceWarning)]
    print(f"DIAG ConvergenceWarning count during refit: {len(convergence)}")
    for w in convergence:
        print(f"DIAG   warning: {str(w.message).splitlines()[0]}")

    max_iter = LOGREG_CONFIG["max_iter"]
    refit = n_iter_report(classifiers)
    artifact = n_iter_report(joblib.load(MODEL_PATH)["classifiers"]) if MODEL_PATH.exists() else None
    for field in TARGET_FIELDS:
        for cls, n in refit[field].items():
            art = artifact[field][cls] if artifact else "n/a"
            hit = " HIT_MAX_ITER" if n >= max_iter else ""
            print(f"DIAG n_iter {field} | {cls} | refit={n} artifact={art} max_iter={max_iter}{hit}")


if __name__ == "__main__":
    main()
