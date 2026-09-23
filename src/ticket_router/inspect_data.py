"""Step 01 -- data inspection only.

Downloads every data file from the Hugging Face dataset
``Tobi-Bueck/customer-support-tickets`` into ``data/raw/``, loads each file
separately (they are NOT merged), and writes a read-only inspection report
to ``reports/data_report.md``.

This script does not clean, filter, deduplicate, or transform the data in
any way. It only reports what is actually in the files.

Run from the repo root:

    .venv\\Scripts\\python.exe src\\ticket_router\\inspect_data.py   (Windows)
    .venv/bin/python src/ticket_router/inspect_data.py               (POSIX)

Re-running is safe: files already present in data/raw/ with the expected
size are not re-downloaded, and the report is fully overwritten each run.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pandas as pd

REPO_ID = "Tobi-Bueck/customer-support-tickets"
# Step-27: pinned to the exact Hub commit the committed splits were built from, so a later
# upstream change cannot silently change the data. Full sha read from the Hub API; each file at
# this revision was checked byte-for-byte against the originally downloaded copies.
DATASET_REVISION = "ddf1c81a5475992c4fa6752bf1e8b4e31f07bbeb"
REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
REPORT_PATH = REPO_ROOT / "reports" / "data_report.md"

# Repo files with these suffixes are treated as data and downloaded/loaded.
# Everything else (.gitattributes, README.md, ...) is listed in the report
# but skipped -- confirmed by inspecting the repo's file tree, not assumed.
DATA_FILE_SUFFIXES = (".csv",)

# The column used as "ticket text" for the exact-duplicate-rate check.
# `body` is the one column that is present, populated, and semantically
# the same thing (the customer's message) in all three files -- unlike
# `subject` (frequently empty) or `answer` (missing from one file entirely).
TEXT_COLUMN = "body"

# Categorical columns to report in full, per the step-01 instruction.
# `business type` is included here even though (see below) no such column
# exists in any of the three files -- it is reported as "not present"
# rather than silently dropped or mapped onto a different column.
CATEGORICAL_COLUMNS = ["queue", "priority", "type", "business type"]

TAG_COLUMN_PREFIX = "tag_"

USER_AGENT = "ticket-router-inspect-data/1.0"


def hf_api_get(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_repo_files(repo_id: str) -> list[dict]:
    """Return every file in the dataset repo (path + exact size in bytes)."""
    url = f"https://huggingface.co/api/datasets/{repo_id}/tree/{DATASET_REVISION}"
    return hf_api_get(url)


def download_file(repo_id: str, filename: str, size: int, dest: Path) -> None:
    """Download `filename` into `dest` unless it's already there at the right size."""
    if dest.exists() and dest.stat().st_size == size:
        print(f"  already present ({size:,} bytes), skipping download: {dest.name}")
        return
    url = f"https://huggingface.co/datasets/{repo_id}/resolve/{DATASET_REVISION}/{filename}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    print(f"  downloading {filename} ({size:,} bytes)...")
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        out.write(resp.read())


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


def inspect_file(path: Path) -> str:
    """Build the markdown report section for a single data file."""
    df = pd.read_csv(path, low_memory=False)
    n_rows = len(df)
    out = [f"## {path.name}\n"]
    out.append(f"- Total rows: **{n_rows}**")
    out.append(f"- Total columns: **{len(df.columns)}**\n")

    out.append("### Columns and dtypes\n")
    out.append(md_table(["column", "dtype"], [[c, str(t)] for c, t in df.dtypes.items()]))
    out.append("")

    if "language" in df.columns:
        out.append("### Language distribution\n")
        counts = df["language"].fillna("<empty>").value_counts(dropna=False)
        rows = [[lang, cnt, f"{cnt / n_rows:.2%}"] for lang, cnt in counts.items()]
        out.append(md_table(["language", "count", "pct"], rows))
        out.append("")
    else:
        out.append("### Language distribution\n\n_No `language` column in this file._\n")

    out.append("### Categorical columns\n")
    for col in CATEGORICAL_COLUMNS:
        if col not in df.columns:
            out.append(f"**{col}**: _column not present in this file._\n")
            continue
        counts = df[col].fillna("<empty>").value_counts(dropna=False)
        rows = [[val, cnt, f"{cnt / n_rows:.2%}"] for val, cnt in counts.items()]
        out.append(f"**{col}** ({df[col].nunique(dropna=True)} distinct values):\n")
        out.append(md_table(["value", "count", "pct"], rows))
        out.append("")

    tag_cols = [c for c in df.columns if c.startswith(TAG_COLUMN_PREFIX)]
    if tag_cols:
        pooled = pd.concat([df[c] for c in tag_cols]).dropna()
        counts = pooled.value_counts()
        rows = [[val, cnt, f"{cnt / n_rows:.2%}"] for val, cnt in counts.items()]
        out.append(
            f"**tags** (pooled across {', '.join(tag_cols)}; {pooled.nunique()} distinct values; "
            f"pct = share of this file's rows carrying that tag in *any* slot):\n"
        )
        out.append(md_table(["tag", "count", "pct_of_rows"], rows))
        out.append("")
    else:
        out.append("**tags**: _no `tag_N` columns in this file._\n")

    out.append("### Null / empty rate per column\n")
    na_counts = df.isna().sum()
    rows = [[c, int(na_counts[c]), f"{na_counts[c] / n_rows:.2%}"] for c in df.columns]
    out.append(md_table(["column", "null_count", "null_pct"], rows))
    out.append("")

    out.append("### Exact-duplicate rate on ticket text\n")
    if TEXT_COLUMN in df.columns:
        text = df[TEXT_COLUMN]
        non_null = text.dropna()
        dup_count = int(non_null.duplicated(keep="first").sum())
        dup_rate = dup_count / n_rows if n_rows else 0.0
        out.append(f"- Text column used: `{TEXT_COLUMN}`")
        out.append(f"- Non-null values: {len(non_null)} / {n_rows}")
        out.append(
            f"- Exact-duplicate rows (a repeat of an earlier row's `{TEXT_COLUMN}`; the first "
            f"occurrence of each value is not counted as a duplicate): **{dup_count}** "
            f"({dup_rate:.2%} of all rows)"
        )
    else:
        out.append(f"_No `{TEXT_COLUMN}` column in this file._")
    out.append("")

    out.append("### 3 example rows\n")
    sample = df.sample(n=min(3, n_rows), random_state=42)
    for i, (idx, row) in enumerate(sample.iterrows(), start=1):
        out.append(f"**Row {i} (index {idx}):**\n")
        out.append("```")
        for col in df.columns:
            val = row[col]
            val = "" if pd.isna(val) else str(val)
            out.append(f"{col}: {val}")
        out.append("```")
        out.append("")

    return "\n".join(out)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print(f"Listing files in {REPO_ID} ...")
    tree = list_repo_files(REPO_ID)

    report = [
        f"# Data report: {REPO_ID}\n",
        "Step 01 -- inspection only. Nothing in this report was cleaned, filtered, "
        "deduplicated, or transformed; it describes the raw files exactly as downloaded.\n",
    ]

    report.append("## Files in the repo\n")
    file_rows = []
    data_files = []
    for entry in tree:
        path = entry["path"]
        size = entry["size"]
        is_data = path.endswith(DATA_FILE_SUFFIXES)
        file_rows.append([path, f"{size:,}", "yes" if is_data else "no (repo metadata, skipped)"])
        if is_data:
            data_files.append((path, size))
    report.append(md_table(["file", "size_bytes", "loaded_as_data"], file_rows))
    report.append("")

    report.append("## Assumption check\n")
    report.append(
        "The instruction asked for the full value set of a `business type` column, alongside "
        "`queue`, `priority`, `type`, and `tags`. **No column named `business type` (or anything "
        "resembling it) exists in any of the three files** -- confirmed columns are listed per-file "
        "below. Per CLAUDE.md, this mismatch is reported here rather than guessed at or worked "
        "around; `business type` is listed as \"not present\" in each file's categorical-columns "
        "section instead of being silently mapped onto some other column (e.g. `type`, which is "
        "actually an ITIL ticket type: Incident/Request/Problem/Change; or `version`, which is a "
        "numeric dataset-version tag, not a category).\n"
    )

    print(f"Found {len(data_files)} data file(s): {[f for f, _ in data_files]}")
    for filename, size in data_files:
        dest = RAW_DIR / filename
        download_file(REPO_ID, filename, size, dest)

    for filename, _ in data_files:
        print(f"Inspecting {filename} ...")
        report.append(inspect_file(RAW_DIR / filename))

    REPORT_PATH.write_text("\n".join(report), encoding="utf-8")
    print(f"\nReport written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
