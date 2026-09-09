# Progress

## step-00: scaffold project structure, working rules, and venv

**What was built:** Initial repo skeleton — folder structure (`src/ticket_router/`, `data/raw/`,
`data/processed/`, `reports/`, `results/`, `notebooks/`, `tests/`, `demo/`), housekeeping files, the
`CLAUDE.md` working rules, and a local venv with no packages installed.

**Files added:**
- `.gitignore`
- `requirements.txt` (empty, header comment only)
- `.env.example`
- `README.md`
- `CLAUDE.md`
- `PROGRESS.md`
- `src/ticket_router/__init__.py` (empty)
- `data/raw/.gitkeep`, `data/processed/.gitkeep`, `reports/.gitkeep`, `results/.gitkeep`,
  `notebooks/.gitkeep`, `tests/.gitkeep`, `demo/.gitkeep`

**Verify with:**
```
git -C . ls-files
git -C . log --format="%an <%ae>%n%b" -1
.\.venv\Scripts\python.exe --version
```

**Next step:** step-01 — not started yet (to be defined).

## step-01: inspect the raw Hugging Face dataset (no cleaning/transforming)

**What was built:** `src/ticket_router/inspect_data.py`, a standalone, re-runnable script that:
1. Lists every file in the `Tobi-Bueck/customer-support-tickets` HF dataset repo (via the HF
   tree API) with its exact size in bytes.
2. Downloads the 3 CSV data files into `data/raw/` (skips re-download if a file of the right
   size is already there; `.gitattributes`/`README.md` are listed but not downloaded).
3. Loads each of the 3 files **separately** (no merging) and, for each, computes: columns +
   dtypes, row count, language distribution, full distinct-value counts for `queue`, `priority`,
   `type`, `business type`, and pooled `tag_1..tag_8`, null/empty rate per column, exact-duplicate
   rate on the `body` column, and 3 example rows (`sample(random_state=42)` for reproducibility).
4. Writes everything as markdown tables to `reports/data_report.md`.

**Assumption mismatch found (per CLAUDE.md, reported not worked around):** no `business type`
column exists in any of the 3 files. Confirmed real columns per file:
- `aa_dataset-tickets-multi-lang-5-2-50-version.csv` (28,587 rows): subject, body, answer, type,
  queue, priority, language, version, tag_1..tag_8
- `dataset-tickets-german_normalized_50_5_2.csv` (13,178 rows, German-only): subject, body, queue,
  priority, language
- `dataset-tickets-multi-lang-4-20k.csv` (20,000 rows): subject, body, answer, type, queue,
  priority, language, tag_1..tag_8

This is flagged in `reports/data_report.md` under "Assumption check"; `business type` is reported
as "not present" per file rather than mapped onto `type` (which is actually an ITIL ticket type:
Incident/Request/Problem/Change) or `version` (a numeric dataset-version tag, not a category).

**Dependency added:** `pandas==3.0.5` (and its transitive deps: numpy, python-dateutil, tzdata,
six) — needed for CSV loading, dtype inference, `value_counts`, null-rate and duplicate-rate
computation. No other package was added; downloading uses only the Python stdlib
(`urllib.request`).

**Files added/changed:**
- `src/ticket_router/inspect_data.py` (new)
- `reports/data_report.md` (new, generated — not hand-written)
- `requirements.txt` (added `pandas==3.0.5`)
- `data/raw/aa_dataset-tickets-multi-lang-5-2-50-version.csv` (downloaded, gitignored)
- `data/raw/dataset-tickets-german_normalized_50_5_2.csv` (downloaded, gitignored)
- `data/raw/dataset-tickets-multi-lang-4-20k.csv` (downloaded, gitignored)

**Verify with:**
```
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe src\ticket_router\inspect_data.py
```
Re-running regenerates `reports/data_report.md` from scratch; the 3 CSVs in `data/raw/` are
skipped on re-download since their size already matches the repo.

**Next step:** step-02 — not started yet (to be defined once the report has been read).

## step-02: build the modeling dataset (English filter, clean, split)

**What was built:** `src/ticket_router/make_dataset.py`, a standalone, config-driven, re-runnable
pipeline that reads ONLY `data/raw/aa_dataset-tickets-multi-lang-5-2-50-version.csv` (28,587 rows)
and produces `data/processed/{train,val,test}.parquet` + `data/processed/label_map.json` +
`data/README.md` (a generated data card).

**Why only one of the 3 raw files is used:** recorded in `data/README.md` under "Which file was
used, and why" — `dataset-tickets-german_normalized_50_5_2.csv` is German-only with an
incompatible 42-class topic-style `queue` taxonomy; `dataset-tickets-multi-lang-4-20k.csv` has the
same schema but unverified overlap with the chosen file, risking duplicate/near-duplicate leakage
across splits if combined.

**Pipeline (in order), with the actual numbers this run produced:**
1. Load raw CSV (28,587 rows), assign a stable `id` (`tkt_NNNNNN`, from each row's position in the
   raw file, before any filtering).
2. English-only filter (`language == "en"`): **16,338 / 28,587 rows** (57.15%) — matches the
   "roughly 16,338" expectation from the step-01 report exactly.
3. Queue row-count gate, checked right after the English filter, before anything else: all 10
   classes ≥ 100 rows (smallest: General Inquiry, 236) → proceeded (no STOP).
4. Label sets read from the data, not the dataset card: `priority` = `[high, low, medium]` (the
   card's `critical` does not occur in this file — confirms the step-01 report's finding);
   `type` = `[Change, Incident, Problem, Request]`; all 10 `queue` values kept, none merged/dropped.
5. Drop rows with empty/null `body` or a null target: **0 rows** (body and all 3 targets were
   fully populated in the English subset).
6. Build `text` = `subject + "\n" + body`, or `body` alone when `subject` is null (**2,607 rows**,
   15.96% of the cleaned data) — recorded per-row in a new boolean `has_subject` column.
7. Drop exact duplicates on `text`: **0 rows removed** (0.00%) — consistent with step-01's finding
   of 0 duplicates on `body` alone across the whole file; not flagged (well under the 1% sanity
   threshold).
8. Stratified 80/10/10 split on `queue`, seed 42, done independently per queue class (manual
   `numpy.random.default_rng` shuffle-and-cut — no `sklearn` needed/added). Result: train 13,070,
   val 1,635, test 1,633 (16,338 total).
9. Asserted programmatically that no `id` appears in more than one split, and that the union of
   split ids equals the full cleaned row count — both passed.
10. Saved `id, subject, body, text, has_subject, language, queue, priority, type` to parquet per
    split (source's `answer`, `version`, `tag_1..tag_8` columns dropped — not needed for the
    queue/priority/type routing targets).

**Full per-split label distributions, row counts, license (CC-BY-NC-4.0, non-commercial), and the
synthetic-data note are all in `data/README.md`** (generated by the script itself, so it can never
drift from the actual output).

**Dependencies added:**
- `pyarrow==25.0.1` — parquet read/write engine for pandas; there is no pure-stdlib way to write
  parquet. (Downloaded the wheel directly via `curl` and installed with `pip install --no-index
  <local wheel>` because `pip`'s own downloader kept hitting `ReadTimeoutError` against
  `files.pythonhosted.org` on this network — same root cause as the earlier pandas install retry
  in step-01, just larger/slower for a 28 MB wheel.)
- `numpy==2.5.3` — was already an installed transitive dependency of pandas (step-01), now also
  imported directly for the seeded stratified-split shuffle and vectorized text concatenation, so
  it's listed explicitly in `requirements.txt` for clarity.

**Files added/changed:**
- `src/ticket_router/make_dataset.py` (new)
- `data/README.md` (new, generated — tracked in git; added a `!data/README.md` exception to
  `.gitignore` since `data/*` would otherwise have excluded it)
- `requirements.txt` (added `pyarrow==25.0.1`, `numpy==2.5.3`)
- `.gitignore` (added `!data/README.md` exception)
- `data/processed/train.parquet`, `val.parquet`, `test.parquet`, `label_map.json` (generated,
  gitignored — same convention as the raw CSVs: regenerable from the script, not tracked)

**Verify with:**
```
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe src\ticket_router\make_dataset.py
```
Re-running is deterministic (fixed seed 42, fixed source file) and regenerates all outputs from
scratch.

### Correction (post step-02): track `label_map.json` in git

`data/processed/label_map.json` was originally left gitignored alongside the parquet splits, on
the assumption that everything under `data/processed/` is regenerable and therefore not worth
tracking. That assumption was wrong: `label_map.json` is the **label contract** — `schema.py`, the
evaluation harness, and the step-13 CI tests all depend on its exact contents, and CI does not
rebuild the dataset (so it can't regenerate the file to get it). The parquet splits genuinely are
just regenerable data and stay gitignored.

**Fix:** added `!data/processed/label_map.json` to `.gitignore` (alongside the existing
`!data/processed/.gitkeep` exception), then staged and committed the file.

**Verified tracked:**
```
$ git ls-files data/processed/
data/processed/.gitkeep
data/processed/label_map.json
```
(`train.parquet`, `val.parquet`, `test.parquet` correctly do **not** appear — still gitignored.)

**Files changed:** `.gitignore` (added the exception), `data/processed/label_map.json` (now
tracked).

### Correction (post step-02): fix `data/README.md` wording (docs-only, no re-split)

Two hand-edits to `data/README.md`, without re-running `make_dataset.py` (no data touched, no
split regenerated):

1. Added a **"Known limitations"** section: the split is stratified on `queue` only, so `priority`
   and `type` proportions are preserved only approximately. Concrete example given: `type = Change`
   has 1,705 rows and lands 1,360/190/155 across train/val/test instead of an exact 1,364/170/170
   (~10% relative deviation for that class). States this was accepted, not fixed — satisfying all
   three targets at once would either break the queue stratification or need multi-label
   stratification, and the deviation is too small to change conclusions — and that per-class
   support will be reported next to every metric so a reader can judge for themselves.
2. **Reproduce** section was Windows-only (`.venv\Scripts\python.exe ...`). Replaced with a
   platform-neutral `python src/ticket_router/make_dataset.py` plus venv-activation lines for both
   Windows and Unix, since the repo is public and will be reviewed on Linux/macOS too.

**Known drift this leaves behind (flagged, not fixed here):** `data/README.md` is normally
*generated* by `build_data_readme()` inside `src/ticket_router/make_dataset.py`, which was
deliberately **not** touched this round (docs-only scope, no re-split). That generator still
produces the old Windows-only Reproduce text and has no Known-limitations section, so the next
time `make_dataset.py` actually runs, it will silently overwrite `data/README.md` and undo both
of these corrections. Worth fixing the generator itself next time the script is touched.

**Files changed:** `data/README.md` only.

### Correction (post step-02): close the drift — generator now produces both sections

The drift flagged above is fixed. `build_data_readme()` in `src/ticket_router/make_dataset.py` now
generates both corrections itself, so a real re-run can no longer erase them:

- **`find_least_balanced_class(splits, fields, ratios)`** (new helper): for each value of each
  field in `fields` — called with `["priority", "type"]`, deliberately excluding `queue`, the field
  the split is actually stratified on — compares actual per-split counts to an exactly-proportional
  split and returns the single `(field, value)` with the largest relative deviation on any split.
  This replaces the previously hand-typed `type = Change` / `1360/190/155` prose: the "Known
  limitations" section now names whichever class is actually least balanced and prints its real
  numbers, so the text can't silently go stale if the data or split logic ever changes.
- **`round_to_nearest_10_pct(fraction)`** (new helper): turns the computed deviation into the same
  coarse "roughly N%" phrasing the section already used, instead of false precision.
- **Reproduce section**: generator now emits the cross-platform block (Windows `.venv\Scripts\activate`
  + Unix `source .venv/bin/activate`, both followed by `python src/ticket_router/make_dataset.py`)
  instead of the old Windows-only one-liner.

**Re-ran** `.venv\Scripts\python.exe src\ticket_router\make_dataset.py` (fixed seed 42, same source
file — fully deterministic). Same numbers as the original step-02 run: 16,338 English rows, 0 rows
dropped, 0 duplicate `text` rows, splits 13,070/1,635/1,633.

**Proof the generator now matches what's committed:**
```
$ git status --short
 M src/ticket_router/make_dataset.py

$ git diff data/README.md
(empty)

$ git diff data/processed/label_map.json
(empty)
```
`data/README.md` came back byte-identical to the committed version on the first try — the computed
"least-balanced class" naturally resolved to `type = Change` (1,705 rows; 1,360/190/155 actual vs.
1,364/170/170 ideal, ~11.4% max relative deviation on val, which `round_to_nearest_10_pct` renders
as "roughly a 10%"), matching the previously hand-written numbers because the underlying split
itself didn't change — only how the text describing it is produced. `label_map.json` is untouched,
confirming the re-run is fully deterministic.

**Files changed:** `src/ticket_router/make_dataset.py` only (`data/README.md` and
`data/processed/label_map.json` regenerated identical to what was already committed/tracked, so
neither shows a diff).

**Next step:** step-03 — not started yet (to be defined).
