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

## step-03: evaluation harness (no model calls)

**What was built:** a typed label schema, a metrics library, a scoring CLI, a cross-run comparison
report, a random-baseline predictor, and pytest tests — all new files; no step-01/02 file was
touched (per CLAUDE.md).

1. **`src/ticket_router/schema.py`**: `TicketLabels` (pydantic `BaseModel`) with `queue`, `priority`,
   `type` as `Literal[...]` built dynamically from `data/processed/label_map.json` at import time
   (`Literal[tuple(values)]` — subscripting with a tuple is exactly the same as
   `Literal[v1, v2, ...]`). If the label contract ever changes, the schema updates with it — no
   hand-maintained enum to drift out of sync.
2. **`src/ticket_router/metrics.py`**: pure, I/O-free functions — `field_metrics` (per-class
   precision/recall/F1/support + accuracy + macro-F1), `exact_match_rate`, `percentile` (linear
   interpolation, matches `numpy.percentile`'s default), `md_table`. `INVALID` is a sentinel that can
   never equal a real label, so a missing/malformed prediction always scores as a miss rather than
   being dropped from the denominator.
3. **`src/ticket_router/evaluate.py`** (CLI: `--predictions`, `--split`, `--run-name`): reads a
   predictions JSONL, validates each row's labels via `TicketLabels`, tracks
   latency/tokens/cost independently of label validity (an API call can burn both even if its JSON
   comes back malformed), computes every metric asked for, prints a markdown summary row plus a
   per-class breakdown (honoring `data/README.md`'s "per-class support next to every metric" promise
   from step-02), and read-modify-writes `results/results.json` keyed by run name.
4. **`src/ticket_router/report.py`**: reads `results/results.json`, regenerates
   `results/comparison.md` (one row per run) and prints it.
5. **`src/ticket_router/predict_random_baseline.py`**: no model calls — samples queue/priority/type
   independently from each field's marginal distribution in `train.parquet` (seed 42), writes
   `results/random-baseline.predictions.jsonl` with `latency_ms/input_tokens/output_tokens/cost_usd`
   all structurally `0` (never measured, since nothing was ever called).
6. **`tests/test_metrics.py`** + **`pytest.ini`** (`pythonpath = src`): hand-computed 8-row/3-class
   fixture for `field_metrics` (accuracy, per-class precision/recall/F1, macro-F1 all worked out by
   hand in comments — e.g. macro-F1 = 11/18), a fixture proving the `INVALID` sentinel always counts
   as a miss, a 5-row `exact_match_rate` fixture, and known-value checks for `percentile`/`md_table`.
   **11/11 passed.**

**Proof run (random baseline on `test`, 1,633 rows):**
```
exact_match=2.20%  invalid_rate=0.00%
queue:    acc=17.82%  macro_f1=0.1110
priority: acc=36.56%  macro_f1=0.3427
type:     acc=30.80%  macro_f1=0.2577
latency p50/p95 = 0.00/0.00 ms   total_cost=$0.0000   cost/1000=$0.0000
```
0% invalid rate is expected (the baseline only ever samples from the allowed set — this exercises
the harness's "everything valid" path; the invalid/missing-prediction path is what
`test_field_metrics_invalid_sentinel_counts_as_miss` covers directly). `results/comparison.md`
regenerated by `report.py` contains exactly this one row.

**Bug found and fixed during the proof run:** `evaluate.py --predictions results/foo.jsonl` (a
relative path) crashed in `save_result` — `Path.relative_to()` was being called against the relative
path as given, not resolved to absolute first, so it never matched `REPO_ROOT`. Fixed by resolving
`--predictions` to an absolute path in `argparse` itself (`type=lambda p: Path(p).resolve()`).

**Also fixed:** `evaluate.py`/`report.py` initially failed with `ModuleNotFoundError: No module named
'ticket_router'` when run directly (`python src/ticket_router/evaluate.py`) — running a file inside a
package puts only that file's own directory on `sys.path`, not `src/`. Fixed by inserting `src/` onto
`sys.path` at the top of both files before the `ticket_router.*` imports, so both run standalone from
the repo root exactly as documented, with no `PYTHONPATH` env var or `-m` flag required.

**Dependencies added:**
- `pydantic==2.13.5` — runtime validation of a prediction's queue/priority/type against the exact
  label set in `label_map.json` (`schema.py`'s `TicketLabels`); this is what makes "value outside the
  allowed set" a well-defined, enforced check in `evaluate.py` rather than an ad-hoc string comparison.
- `pytest==9.1.1` — test runner for `tests/test_metrics.py`, requested by this step.
No `scikit-learn`: macro-F1/accuracy are simple enough to implement directly over `label_map.json`'s
class lists (see `metrics.py`), consistent with step-02's earlier choice to hand-roll the stratified
split instead of adding `sklearn`.

**Files added:** `src/ticket_router/schema.py`, `src/ticket_router/metrics.py`,
`src/ticket_router/evaluate.py`, `src/ticket_router/report.py`,
`src/ticket_router/predict_random_baseline.py`, `tests/test_metrics.py`, `pytest.ini`,
`results/results.json`, `results/comparison.md`, `results/random-baseline.predictions.jsonl`
(`results/` was already git-tracked — only `data/` is gitignored — so no `.gitignore` change was
needed). **Files changed:** `requirements.txt` (added `pydantic`, `pytest`).

**Verify with:**
```
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest -v
.venv\Scripts\python.exe src\ticket_router\predict_random_baseline.py
.venv\Scripts\python.exe src\ticket_router\evaluate.py --predictions results\random-baseline.predictions.jsonl --split test --run-name random-baseline
.venv\Scripts\python.exe src\ticket_router\report.py
```

## step-04: zero-shot API baseline (OpenAI, gpt-4o-mini)

**What was built:** `src/ticket_router/predictors/api_predictor.py` — calls the OpenAI API directly
via the official `openai` SDK (provider-agnostic: `OPENAI_API_KEY`/`OPENAI_BASE_URL`/`OPENAI_MODEL`
all read from `.env`, `OPENAI_MODEL` never hardcoded). Structured outputs
(`response_format: json_schema, strict=True`) with a fallback to plain-JSON + `TicketLabels`
validation if a model/request rejects that parameter. Up to 2 content-validation retries (3
attempts total) with corrective feedback in the retry prompt; rate-limit/transient-error backoff is
the SDK's own built-in `max_retries`. Every individual API call is cached to disk
(`.cache/api_predictor/`, gitignored) keyed by a hash of (model, exact messages, ticket id), so
re-running the same rows costs nothing. Concurrency capped at 5 threads. A `--smoke-test` mode sends
one raw, uncached, unretried call and lets any SDK exception propagate uncaught (no fallback model),
for a clean go/no-go check before spending anything.

**Provider pivot mid-step:** originally built against OpenRouter; switched to calling OpenAI
directly on request, before any API call was made. `.env.example` and the script were updated
together so there was never a mix of the two.

**`cost_usd` is `null` in every predictions row, on purpose**: OpenAI's chat completions API does
not return a live `$` figure (unlike some aggregators). No pricing table is hardcoded in the
pipeline -- prices drift and a stale guess baked into the codebase is worse than being explicit that
it's unknown there. `input_tokens`/`output_tokens` are exact and authoritative; $ costs below are
computed separately (not by the script) from those tokens using gpt-4o-mini's published per-token
price ($0.15/1M input, $0.60/1M output) -- flagged as an external, verify-before-trusting figure,
not a harness-tracked one.

**Verification sequence, in order:**
1. **Smoke test** (`--smoke-test`): first attempt failed with `401 AuthenticationError` -- traced to
   a stale Windows `OPENAI_API_KEY` environment variable shadowing `.env` (the original loader used
   `os.environ.setdefault()`, which never overwrites an existing variable). Fixed by switching to
   `python-dotenv`'s `load_dotenv(dotenv_path=ENV_PATH, override=True)`, so `.env` always wins
   regardless of ambient environment state, on any machine. Re-ran: passed, structured output
   confirmed working, masked key (`...jqkA`) printed and confirmed correct before the call.
2. **50-row proof run** (`--split test --limit 50`): 50/50 valid, 0 failures. Re-ran the identical
   command a second time: `cached=50, fresh=0` -- proves the cache works (zero API calls on rerun,
   not an estimate).
3. **Sampling-trap bug found and fixed at the source**: the 50-row run's gold gave `queue` support
   of 50 for a single class ("Billing and Payments") -- `make_dataset.py`'s `stratified_split()`
   concatenates one queue class's rows after another, so a split's row order was grouped by class;
   `df.head(n)` on a split was a slice of one class, not a sample. **Fixed in `make_dataset.py`**:
   after the stratified assignment, each split's row order is shuffled (`.sample(frac=1,
   random_state=np.random.default_rng(SPLIT_SEED))`, fresh per split) -- membership is untouched,
   only order changes. Documented as new item 8 in `data/README.md`'s "Preprocessing decisions"
   (items 8-9 renumbered to 9-10).
4. **Re-ran `make_dataset.py`, verified three things:**
   - `label_map.json`: `git diff` empty -- unchanged, as expected (shuffling doesn't touch labels).
   - `data/README.md`: `git diff` **not** empty, but the *only* diff is the new item documenting
     this shuffle step (row counts and label distributions are byte-identical) -- a deliberate
     content addition per the data card's own "every preprocessing decision" promise, not drift.
   - **Id-to-split membership**: compared the full id set per split before vs. after, for all three
     splits: `added=0, removed=0` on every split -- membership is exactly identical; only file row
     order changed (confirmed differing "first 5 ids" before/after). This also means the 50 tickets
     already cached from step 3 remained valid (same ids, just relocated within the file).
5. **`evaluate.py` gap found and fixed**: it always scored against the *full* gold split, so
   scoring 50 predictions against 1,633 gold rows would have shown a bogus ~97% invalid rate (1,583
   "no prediction found" rows). Added an optional `--limit` (default `None` = unchanged behavior for
   every existing/future full-split call), mirroring the predictor's own `--limit`, so gold and
   predictions cover identically the same rows.
6. **Full 1,633-row test-split run** (no `--limit`): 1,633/1,633 valid, 0 failures. 50 of the 1,633
   calls were free cache hits (the same tickets from step 2/3's proof runs, still valid after the
   shuffle since membership didn't change).

**Full-split results** (`api-gpt4o-mini-full-test`, gpt-4o-mini, n=1,633):

| field | accuracy | macro-F1 |
|---|---|---|
| queue | 33.37% | 0.2554 |
| priority | 43.54% | 0.3214 |
| type | 64.18% | 0.5209 |

- exact-match rate (all 3 fields): 10.90%
- invalid-output rate: 0.00%
- latency: p50 = 698.54 ms, p95 = 1092.26 ms
- tokens: 606,199 input + 23,541 output = 629,740 total (371.2 in / 14.4 out per ticket, average)
- estimated cost (external calc, gpt-4o-mini published pricing): **$0.1051 total**, **$0.0643 per
  1,000 tickets** -- consistent with the 50-row run's $0.1057 extrapolation, i.e. the projection
  held even though that 50-row sample was itself label-skewed (a token-count/cost projection isn't
  sensitive to label distribution the way an accuracy projection would have been).
- `queue` per-class F1 (full breakdown in `results/comparison.md` and `results/results.json`):
  strongest on Billing and Payments (0.6967) and Technical Support (0.4724); weakest on General
  Inquiry (0.0000, 0/24 correct) and Returns and Exchanges (0.0706, 1/82 recall).
- Beats `random-baseline` on macro-F1 for all three fields (queue 0.2554 vs 0.1110, priority 0.3214
  vs 0.3427 -- roughly tied, type 0.5209 vs 0.2577), for essentially zero cost.

**Dependencies added:**
- `openai==3.11.0` -- official SDK for the OpenAI API: auth, structured-output requests, built-in
  rate-limit backoff (`max_retries=`), instead of hand-rolling HTTP + retry logic.
- `python-dotenv==1.2.3` -- `load_dotenv(override=True)`, so `.env` always wins over any ambient/
  stale OS environment variable of the same name, on this machine, CI, or anyone else's.

**Files added:** `src/ticket_router/predictors/__init__.py`, `src/ticket_router/predictors/api_predictor.py`,
`results/api-gpt4o-mini-50.predictions.jsonl`, `results/api-gpt4o-mini-full-test.predictions.jsonl`.
**Files changed:** `.env.example` (`OPENAI_API_KEY`/`OPENAI_BASE_URL`/`OPENAI_MODEL` placeholders),
`.gitignore` (added `.cache/`), `requirements.txt` (`openai`, `python-dotenv`),
`src/ticket_router/make_dataset.py` (shuffle fix), `data/README.md` (regenerated, documents the
shuffle), `src/ticket_router/evaluate.py` (`--limit`), `results/results.json`,
`results/comparison.md` (both regenerated with the new runs).

**Verify with:**
```
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe src\ticket_router\predictors\api_predictor.py --smoke-test
.venv\Scripts\python.exe src\ticket_router\predictors\api_predictor.py --split test --run-name api-gpt4o-mini-full-test
.venv\Scripts\python.exe src\ticket_router\evaluate.py --predictions results\api-gpt4o-mini-full-test.predictions.jsonl --split test --run-name api-gpt4o-mini-full-test
.venv\Scripts\python.exe src\ticket_router\report.py
```
Requires `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env` (never committed; see `.env.example`). A
rerun over the same rows replays from `.cache/api_predictor/` and costs nothing.

## step-04b: classical ML baseline (TF-IDF + one-vs-rest logistic regression)

**What was built:** `src/ticket_router/predictors/tfidf_baseline.py` -- a single, deliberately
un-tuned TF-IDF (`max_features=20000, ngram_range=(1,2), stop_words="english", sublinear_tf=True`)
+ `OneVsRestClassifier(LogisticRegression(max_iter=1000, random_state=42))` model, one classifier
per target field, sharing one TF-IDF vectorizer fit on `train.parquet`'s `text` column only (never
sees test text during fitting). Predicts all three fields on the full `test.parquet` (1,633 rows).
Runs in ~3 seconds end to end (fit: 1.81s/0.67s/0.82s for queue/priority/type; predict: <10ms
total). `cost_usd` is a real `0.0` (not `null` like `api_predictor.py`'s -- there is no ambiguity
here, no API was called). `latency_ms` is the total batch-predict time divided evenly across rows
(sklearn predicts the whole test set at once, not row-by-row like an API call) -- documented in the
script as batch-averaged, not a per-request measurement.

**Why this exists:** to answer one question before step 05 spends any effort: is a target field's
low zero-shot macro-F1 because the signal genuinely isn't recoverable from the ticket text, or
because the prompt is failing to extract signal that's actually there? A model trained directly on
13,070 labelled examples is the cleanest way to tell those two apart, and it costs nothing to ask.

**Results** (`tfidf-baseline`, test split, n=1,633) **alongside every other run so far:**

| run | queue F1 | priority F1 | type F1 | exact-match | cost/1000 |
|---|---|---|---|---|---|
| random-baseline | 0.1110 | 0.3427 | 0.2577 | 2.20% | $0.0000 |
| api-gpt4o-mini-full-test (zero-shot) | 0.2554 | 0.3214 | 0.5209 | 10.90% | ~$0.0643 (external calc) |
| **tfidf-baseline** | **0.3683** | **0.5445** | **0.8412** | **29.33%** | $0.0000 |

**The diagnostic question this was built to answer, answered:** zero-shot gpt-4o-mini scored
macro-F1 0.3214 on `priority` -- indistinguishable from random-from-distribution's 0.3427. TF-IDF,
trained on the same 13,070 examples, scores **0.5445** -- clearly and substantially higher than
both (+59% relative over random, +69% relative over the zero-shot LLM). **The numbers support the
second conclusion: the signal is there, and the LLM prompt is what is failing, not that `priority`
is unpredictable from ticket text in this dataset.** This holds even more strongly for `queue`
(0.3683 vs. 0.2554) and `type` (0.8412 vs. 0.5209) -- TF-IDF beats the zero-shot LLM on **all three
fields**, not just `priority`. Per-field weak spots worth step-05's attention: `queue` classes
General Inquiry and Human Resources still score 0.0 F1 even for TF-IDF (support 24 and 35 -- may
be a genuinely hard minority-class problem, not just a prompting one); `priority=low` has high
precision but poor recall (0.24) for TF-IDF, suggesting the model defaults to high/medium when
unsure.

**Not tuned, as instructed:** no hyperparameter search, no cross-validation, no feature selection
beyond the fixed `max_features=20000` cap -- a single sensible configuration, because the question
was "is there signal at all", not "what's the best classical score achievable".

**Dependency added:** `scikit-learn==1.9.0` -- `TfidfVectorizer` + `OneVsRestClassifier` +
`LogisticRegression` for the model itself. This is a different concern from `metrics.py` (step-03),
which deliberately stayed hand-rolled/sklearn-free for macro-F1 etc.; there's no reasonable
hand-rolled substitute for TF-IDF + logistic regression, so unlike the metrics decision, adding
scikit-learn here is the straightforward choice.

**Files added:** `src/ticket_router/predictors/tfidf_baseline.py`,
`results/tfidf-baseline.predictions.jsonl`. **Files changed:** `requirements.txt` (`scikit-learn`),
`results/results.json`, `results/comparison.md` (both regenerated with the new run).

**Verify with:**
```
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe src\ticket_router\predictors\tfidf_baseline.py
.venv\Scripts\python.exe src\ticket_router\evaluate.py --predictions results\tfidf-baseline.predictions.jsonl --split test --run-name tfidf-baseline
.venv\Scripts\python.exe src\ticket_router\report.py
```
Deterministic given `random_state=42` and the fixed train/test parquet files -- no `.env`, no
network call, no cost.

## step-04c: TF-IDF near-duplicate leakage check

**What was built:** `src/ticket_router/leakage_check.py`, writing `reports/leakage_check.md`.
Reuses `tfidf_baseline.py`'s exact `TFIDF_CONFIG` (imported, not re-typed, so the two can't drift
apart) to fit TF-IDF on train text and compute, for every one of the 1,633 test rows, its maximum
cosine similarity against all 13,070 train rows. Recomputes macro-F1 from the already-saved
`results/tfidf-baseline.predictions.jsonl` (no retraining) restricted to the subset below a 0.90
similarity threshold, reusing `metrics.field_metrics` (step-03) rather than duplicating scoring
logic.

**Why:** step-02 already ruled out *exact*-duplicate rows across splits (dedup on `text` before
splitting), but synthetic, template-generated tickets can be near-identical paraphrases without
being byte-identical -- exact-dedup can't catch that, and it would let a model "cheat" by
memorizing a near-twin instead of generalizing. A strong result on synthetic data (step-04b's TF-IDF
beating a zero-shot LLM on all three fields) deserved this check before being used to draw
conclusions.

**Results:**
- Max-similarity distribution (each test row vs. its closest train row): min 0.1650, median 0.6539,
  p90 0.8721, p95 0.9016, max 1.0000.
- Rows exceeding threshold: **88/1,633 (5.39%)** above 0.90, **18 (1.10%)** above 0.95, **5 (0.31%)**
  above 0.99.
- The 5 similarity=1.0000 pairs are **real, confirmed near-duplicate leakage** -- read in full in
  the report -- paraphrases from what looks like the same generation template, e.g. test
  `tkt_004641` / train `tkt_001231`: *"...best practices for securing medical data **within**
  healthcare environments..."* vs *"...best practices for securing medical data **in** healthcare
  environments..."*, otherwise word-for-word identical. This is genuine evidence the leakage
  mechanism the check was built to catch is real in this dataset, not just hypothetical.
- **The number that decides everything**: macro-F1 recomputed on only the 1,545/1,633 (94.61%) test
  rows below the 0.90 threshold:

| field | macro-F1 (all 1,633) | macro-F1 (1,545 low-similarity only) | random-baseline (reference) |
|---|---|---|---|
| queue | 0.3683 | 0.3558 | 0.1110 |
| priority | 0.5445 | 0.5316 | 0.3427 |
| type | 0.8412 | 0.8325 | 0.2577 |

**Verdict: the result is real, not leakage.** All three fields drop only slightly (1-3.4%
relative) when the 88 highest-similarity rows are excluded, and stay far above the random-baseline
reference throughout. The near-duplicate leakage that exists in this dataset is real but small
(5.39% of test rows) and does not drive step-04b's headline numbers -- TF-IDF beating the zero-shot
LLM on all three fields is genuine signal, and that comparison stands.

**Files added:** `src/ticket_router/leakage_check.py`, `reports/leakage_check.md`. No other files
changed -- read-only analysis over already-saved predictions and parquet files, no retraining, no
new dependency (reuses `scikit-learn` from step-04b).

**Verify with:**
```
.venv\Scripts\python.exe src\ticket_router\leakage_check.py
```
Deterministic (same fixed TF-IDF config, same fixed parquet files); requires
`results/tfidf-baseline.predictions.jsonl` to already exist (from step-04b).

## step-05: few-shot baseline (two variants, then stop)

**What was built:** extended `src/ticket_router/predictors/api_predictor.py` (same predictor,
same test split, per the instruction) with a `--variant {zero-shot,coverage,coverage-priority}`
flag:
- `select_few_shot_examples(train)`: 10 examples, one per queue class, each that class's
  **shortest** training `text` (ties broken by lowest `id`) -- deterministic, documented in code,
  saved to `results/few_shot_examples.json` on every run for traceability.
- `derive_priority_definitions(train)`: for each `priority` value, a Laplace-smoothed
  relative-word-frequency ratio against training tickets of the other two values (keyness/log-odds
  style), words restricted to those appearing in >=20 training tickets of that value -- **derived
  from data, not written from imagination**, saved with the full ranked word lists to
  `results/priority_definitions.json`.
- `build_initial_messages()` extended to optionally prepend few-shot example turns and/or a
  priority-definitions paragraph to the system prompt; the existing per-call cache key (hash of
  model + exact messages + ticket id) needed no changes -- it already differs correctly across
  variants since the messages differ.

Ran both variants on the full 1,633-row test split, scored through the unchanged harness
(`evaluate.py`), regenerated `results/comparison.md`. **Extended `report.py`** to also sync the
comparison table into the root `README.md`'s "## Results" section (between fixed HTML-comment
markers, replaced in place on every run) -- the table there is never hand-typed, always regenerated
from `results/results.json`.

**Results** (full comparison in `reports/prompting_notes.md`; reference rows from earlier steps):

| run | queue F1 | priority F1 | type F1 | exact-match | invalid-rate |
|---|---|---|---|---|---|
| zero-shot (step-04) | 0.2554 | 0.3214 | 0.5209 | 10.90% | 0.00% |
| **A: coverage** (10 few-shot) | 0.2442 | 0.3135 | 0.4319 | 6.86% | 0.37% |
| **B: coverage-priority** (A + priority defs) | 0.2241 | 0.3224 | 0.4710 | 6.92% | 2.02% |
| tfidf-baseline (reference) | 0.3683 | 0.5445 | 0.8412 | 29.33% | 0.00% |

**Verdict, stated plainly: few-shot prompting did NOT close the gap to TF-IDF on any field --
`queue` and `type` got measurably worse in both variants, and `priority` barely moved (+0.0010 in
Variant B, not a real change) despite Variant B handing the model empirically-derived priority
vocabulary directly in the prompt.** Full reasoning and the derived word lists are in
`reports/prompting_notes.md`.

**The standout persisted error**: `priority = low` scores **0/345 recall in all three LLM
variants** -- zero-shot, coverage, and coverage-priority alike. The model never predicts `low`,
regardless of prompting, even when told the words most associated with it in training data. A
structural bias, not a missing-information problem.

**Secondary, operational finding**: invalid-output rate rose with prompt size (0.00% -> 0.37% ->
2.02%), but every one of those failures (6 + 33) was confirmed (by inspecting each failed row's
error field) to be a `RateLimitError` -- zero JSON-parse or schema-validation failures in either
variant. Longer few-shot prompts consume more tokens/request, pushing closer to the account's
per-minute token budget under `CONCURRENCY_LIMIT=5`. Reported as an infrastructure side-effect, not
folded into the macro-F1 story as if it reflected content quality.

**No new dependency**: `CountVectorizer` (sklearn, already installed since step-04b) and `numpy`
(already installed since step-02) cover everything needed.

**Files added:** `reports/prompting_notes.md`, `results/few_shot_examples.json`,
`results/priority_definitions.json`, `results/api-gpt4o-mini-fewshot-coverage.predictions.jsonl`,
`results/api-gpt4o-mini-fewshot-coverage-priority.predictions.jsonl`. **Files changed:**
`src/ticket_router/predictors/api_predictor.py` (`--variant` support), `src/ticket_router/report.py`
(README sync), `README.md` (results table added), `results/results.json`, `results/comparison.md`
(both regenerated with the 2 new runs).

**Verify with:**
```
.venv\Scripts\python.exe src\ticket_router\predictors\api_predictor.py --split test --variant coverage --run-name api-gpt4o-mini-fewshot-coverage
.venv\Scripts\python.exe src\ticket_router\predictors\api_predictor.py --split test --variant coverage-priority --run-name api-gpt4o-mini-fewshot-coverage-priority
.venv\Scripts\python.exe src\ticket_router\evaluate.py --predictions results\api-gpt4o-mini-fewshot-coverage.predictions.jsonl --split test --run-name api-gpt4o-mini-fewshot-coverage
.venv\Scripts\python.exe src\ticket_router\evaluate.py --predictions results\api-gpt4o-mini-fewshot-coverage-priority.predictions.jsonl --split test --run-name api-gpt4o-mini-fewshot-coverage-priority
.venv\Scripts\python.exe src\ticket_router\report.py
```
Requires `OPENAI_API_KEY`/`OPENAI_MODEL` in `.env`. Reruns replay from `.cache/api_predictor/` and
cost nothing (the few-shot/priority-definition selection is deterministic, so cache keys are stable
across reruns).

**Stopped after two variants, as instructed** -- no further prompt iteration.

## step-05 (continued): methodology fix + Variant C, then stop

Two things, in the order requested.

### 1. Closed the methodology gap

**Exactly how the 429-failed rows were scored, stated plainly**: not dropped. `evaluate.py` keeps
every gold row in the denominator (n=1,633 always) and scores an id with no valid prediction as
wrong on every field via a sentinel that can never match a real label -- so failed rows were always
counted as incorrect, not excluded. But which specific tickets got a genuine prediction differed
per run (6 failed in A, 33 in B) -- same row count, different row identities. Confirmed by
inspecting every failed row's `error` field: **100% `RateLimitError`, 0% content/validation
failures** in both variants.

**Made it deterministic, in `api_predictor.py`:**
- `CONCURRENCY_LIMIT`: 5 -> **3**. Token-budget math in the code comment: Variant B averaged ~963
  tokens/request at ~1.37s/request; concurrency 5 -> ~211,000 tokens/min against a 200,000 TPM
  limit (over budget, matches the observed 429s); concurrency 3 -> ~127,000 tokens/min (comfortable
  margin).
- **Rate-limit retries separated from content-validation retries**: `call_with_cache()` now retries
  `RateLimitError` in its own loop (up to 10 attempts, exponential backoff capped at 60s) that never
  consumes one of a ticket's 3 content-validation attempts -- previously a 429 could burn through
  that budget and permanently fail a ticket.
- **`purge_error_cache_entries()`** (new, runs automatically at the start of every real invocation):
  deletes every cached response that recorded an error before processing starts, since an error was
  never a valid answer and replaying it as if it were final defeats the retry mechanism silently.

**Re-ran only the affected rows** (per instructions: "the cache covers the rest") -- same
`--run-name`s, so the ~1,600+ already-successful rows per run replayed free from cache; only the
previously-failed 6 (A) and 33 (B) rows made fresh calls. Both reached **0 failures, invalid_rate
0.00%** this time.

**Corrected numbers** (before -> after; macro-F1):

| run | queue | priority | type | exact-match | invalid-rate |
|---|---|---|---|---|---|
| A: coverage | 0.2442 -> 0.2445 | 0.3135 -> 0.3136 | 0.4319 -> 0.4327 | 6.86% -> 6.86% | 0.37% -> **0.00%** |
| B: coverage-priority | 0.2241 -> 0.2287 | 0.3224 -> 0.3246 | 0.4710 -> 0.4738 | 6.92% -> 7.04% | 2.02% -> **0.00%** |

Movement is small (failed rows were <2% either way) -- the qualitative story didn't flip -- but every
run is now scored on the identical 1,633-row set with a genuine prediction for all of them, not an
approximation.

### 2. Variant C (`coverage-median`) -- removing the selection confound

Identical to Variant A except `select_few_shot_examples()` now takes a `rule` parameter: `"shortest"`
(Variant A, unchanged) or `"median"` (Variant C -- index `len(subset)//2` after ascending sort by
`text` length, same lowest-id tie-break). Same deterministic, documented, one-example-per-queue-class
structure; only the length-selection rule differs. Saved to rule-named files
(`results/few_shot_examples_shortest.json`, `results/few_shot_examples_median.json` -- the old
undifferentiated `results/few_shot_examples.json` was removed, identical content confirmed via diff
before deletion).

Ran on the full 1,633-row test split (fresh -- no prior cache): **0 failures**, thanks to the same
concurrency/backoff fix.

**Result: the confound was real.** Full comparison and reasoning in `reports/prompting_notes.md`;
headline numbers:

| run | queue F1 | priority F1 | type F1 | exact-match |
|---|---|---|---|---|
| zero-shot | 0.2554 | 0.3214 | 0.5209 | 10.90% |
| A: coverage (shortest) | 0.2445 | 0.3136 | 0.4327 | 6.86% |
| B: coverage-priority | 0.2287 | 0.3246 | 0.4738 | 7.04% |
| **C: coverage-median** | **0.2399** | **0.3330** | **0.6687** | **9.06%** |
| tfidf-baseline (reference) | 0.3683 | 0.5445 | 0.8412 | 29.33% |

Variant C beats A and B on every field, and beats zero-shot on `priority` (small, real gain) and
substantially on `type` (0.5209 -> 0.6687, closing **~46% of the gap to TF-IDF** on that field).
`queue` is still slightly worse than zero-shot regardless of which few-shot rule is used.
`priority = low` recall moves off a literal 0.0000 (A and B both scored exactly 0 there) to 0.0058
in Variant C -- still a near-total miss, but example *typicality* moved it where Variant B's
*explicit stated definitions* did not.

**Final verdict (plainly, per field, with the confound removed and every run on identical rows):**
few-shot **hurts** `queue` (-6.1% relative), **helps modestly** `priority` (+3.6% relative, gap
mostly still open), **helps substantially** `type` (+28.4% relative, ~46% of the TF-IDF gap closed).
**No variant closes the gap to TF-IDF on any field** -- TF-IDF stays ahead everywhere, by a wide
margin on `queue`/`priority` and a still-substantial one on `type`.

**Files added:** `results/few_shot_examples_median.json`,
`results/api-gpt4o-mini-fewshot-coverage-median.predictions.jsonl`. **Files removed:**
`results/few_shot_examples.json` (superseded by rule-named files). **Files changed:**
`src/ticket_router/predictors/api_predictor.py` (concurrency, rate-limit retry separation, cache
purge, `coverage-median` variant), `reports/prompting_notes.md` (rewritten with the correction and
Variant C), `results/api-gpt4o-mini-fewshot-coverage.predictions.jsonl` and
`-coverage-priority.predictions.jsonl` (6 and 33 rows corrected), `results/results.json`,
`results/comparison.md`, `README.md` (all three regenerated/resynced).

**No new dependency**: `random` (stdlib) for backoff jitter; everything else already installed.

**Verify with:**
```
.venv\Scripts\python.exe src\ticket_router\predictors\api_predictor.py --split test --variant coverage --run-name api-gpt4o-mini-fewshot-coverage
.venv\Scripts\python.exe src\ticket_router\predictors\api_predictor.py --split test --variant coverage-priority --run-name api-gpt4o-mini-fewshot-coverage-priority
.venv\Scripts\python.exe src\ticket_router\predictors\api_predictor.py --split test --variant coverage-median --run-name api-gpt4o-mini-fewshot-coverage-median
.venv\Scripts\python.exe src\ticket_router\evaluate.py --predictions results\api-gpt4o-mini-fewshot-coverage-median.predictions.jsonl --split test --run-name api-gpt4o-mini-fewshot-coverage-median
.venv\Scripts\python.exe src\ticket_router\report.py
```

**Stopped after Variant C, as instructed -- this was the last prompting attempt.**

## step-06: convert processed splits to instruction-tuning (SFT) format

**What was built:** `src/ticket_router/make_sft_dataset.py`, reading `data/processed/{train,val,test}.parquet`
+ `label_map.json` and writing `data/processed/sft/{train,val,test}.jsonl` in OpenAI's fine-tuning
JSONL format (`{"messages": [...]}` per line, directly usable as
`client.fine_tuning.jobs.create(training_file=...)` input, no further conversion needed).

**Each example:**
- **system** (identical across all examples): states the task and lists every allowed value per
  field, sourced from `label_map.json` -- same single source of truth used by `schema.py` and
  `api_predictor.py` throughout the project.
- **user**: the ticket's `text` column, verbatim.
- **assistant**: **minified** JSON (`json.dumps(..., separators=(",", ":"))`, no whitespace) with
  keys in the **fixed order `queue, priority, type`** -- the same order used everywhere else in the
  codebase (`schema.py`'s `TicketLabels`, `metrics.py`'s `TARGET_FIELDS`).

Validated all 3 output files line-by-line after writing: every line is valid JSON, exactly 3 messages
with the right roles in order, and the assistant JSON has exactly the 3 expected keys in the exact
expected order -- 13,070 + 1,635 + 1,633 = 16,338 lines, zero exceptions.

**Tokenizer / model, read from config (flagged assumption):** `.env`'s `OPENAI_MODEL` (`gpt-4o-mini`)
-- the only model config this project has; no separate fine-tuning-specific config exists yet, so
this was the natural, lowest-risk choice, but it's an assumption worth surfacing explicitly in case
a different model is the actual fine-tuning target. Token counts use `tiktoken.encoding_for_model()`
(-> `o200k_base` for this model) with OpenAI's published per-message chat-overhead formula
(`num_tokens_from_messages()`, from the openai-cookbook token-counting notebook), not a raw
`encode()` of the concatenated text -- the chat wrapper itself costs a few tokens per message, and
that's what actually counts against a real max_seq_len during fine-tuning.

**Train token-length distribution** (13,070 examples, full system+user+assistant per example):
min=165, p50=232, **p95=274**, p99=287, max=373. Histogram (20 buckets) printed by the script; heavy
mass in the 165-275 range, a short right tail out to 373.

**Recommended `max_seq_len`: 288** (p95=274, rounded up to the nearest 32).

**Truncation counts at max_seq_len=288:**

| split | truncated | total | pct |
|---|---|---|---|
| train | 107 | 13,070 | 0.82% |
| val | 11 | 1,635 | 0.67% |
| test | 13 | 1,633 | 0.80% |

**Files added:** `src/ticket_router/make_sft_dataset.py`, `reports/sft_samples.md` (5 full worked
examples: system message once, then per-example user/assistant turns, gold-label crosscheck, and
the raw JSONL line, plus the token-length summary). `data/processed/sft/*.jsonl` are gitignored
(regenerable from the parquet files + label_map.json, same convention as the parquet splits
themselves -- sizeable: train.jsonl is 16MB). **Files changed:** `requirements.txt` (`tiktoken`).

**Dependency added:** `tiktoken==0.14.0` -- OpenAI's official tokenizer, needed to get exact token
counts matching how OpenAI will actually tokenize the fine-tuning model (no reasonable hand-rolled
substitute for a BPE tokenizer's exact vocabulary/merges).

**Verify with:**
```
.venv\Scripts\python.exe src\ticket_router\make_sft_dataset.py
```
Deterministic given the fixed parquet files, `label_map.json`, and `.env`'s `OPENAI_MODEL`. No
network call, no cost.

**Did not start training, as instructed.**

## Correction (post step-06): fine-tuning target was wrong

Step-06 originally used `.env`'s `OPENAI_MODEL` (`gpt-4o-mini`) and `tiktoken` for the token-length
analysis, on the assumption that the fine-tuning target was an OpenAI-hosted model. **Wrong**: the
actual target is an **open-weights 1-3B instruct model, QLoRA fine-tuned on Colab, self-hosted and
served in Docker in later steps** -- fine-tuning `gpt-4o-mini` through the API would make those
later steps meaningless and would kill the self-hosted-vs-API cost comparison this project is built
around. Corrected in four parts, in the order given.

### 1. Fine-tuning target as its own config

Added `FT_BASE_MODEL` to `.env`/`.env.example` -- a **separate** setting from `OPENAI_MODEL` (which
stays as-is, used only by `api_predictor.py`'s hosted zero-shot/few-shot baselines). Defaults to
**`Qwen/Qwen2.5-1.5B-Instruct`** in code if left blank in `.env` (unlike `OPENAI_MODEL`, which has
no default and must be set). **Confirmed publicly downloadable, not gated**, before picking it:
queried the HF API (`GET /api/models/Qwen/Qwen2.5-1.5B-Instruct`) -- `"gated": false, "private":
false`, license `apache-2.0`.

### 2. Token-length analysis redone with the target model's own tokenizer

`tiktoken` (OpenAI) does not describe how `Qwen/Qwen2.5-1.5B-Instruct` tokenizes anything --
different vocabulary, different chat template. Switched the primary analysis to `transformers`'
`AutoTokenizer.from_pretrained(FT_BASE_MODEL)` + `apply_chat_template(tokenize=True)` (the target
model's real chat template, applied the same way training will). **Real bug caught during manual
testing before it shipped**: `apply_chat_template(tokenize=True)` returns a `BatchEncoding` dict by
default, and `len()` on that returns the number of *keys* (`input_ids`, `attention_mask` -> 2), not
the token count -- silently wrong by two orders of magnitude. Fixed with `return_dict=False`, which
returns the plain token-id list `len()` actually needs to describe.

No torch install needed -- tokenizer/chat-template loading only, no model weights (this step still
does not start training).

**Side-by-side comparison, train split, full system+user+assistant per example** (both computed on
identical prompt content -- only the tokenizer differs):

| model | p50 | p95 | p99 | max |
|---|---|---|---|---|
| **Qwen/Qwen2.5-1.5B-Instruct (target, used below)** | 236 | **277** | 290 | 377 |
| gpt-4o-mini via tiktoken (comparison only, step-06's original error) | 232 | 274 | 287 | 373 |

Qwen's tokenizer runs consistently a little longer than OpenAI's `o200k_base` on this content (a few
tokens at every percentile) -- close, but a real, visible difference, not identical tokenizers
coincidentally agreeing.

**New recommendation: `max_seq_len = 288`** (Qwen p95=277, rounded up to the nearest 32 -- this
happens to round to the same number as the old, wrong analysis's 274; the underlying p95 values are
genuinely different, the post-rounding number is a coincidence, not evidence the fix didn't matter).

**New truncation counts at max_seq_len=288 (target-model tokenizer):**

| split | truncated | total | pct |
|---|---|---|---|
| train | 144 | 13,070 | 1.10% |
| val | 15 | 1,635 | 0.92% |
| test | 17 | 1,633 | 1.04% |

(Previously reported, wrong-tokenizer counts: 107/13,070, 11/1,635, 13/1,633 -- all slightly lower,
consistent with Qwen's slightly longer token counts.)

### 3. Chat-format JSONL: already message-list, not pre-rendered -- confirmed, not changed

Checked directly: every line is `{"messages": [{"role": ..., "content": ...}, ...]}` -- a structured
list of role/content dicts, never a pre-rendered/pre-templated string. This was already correct and
tokenizer-agnostic; nothing needed to change structurally. What *did* need to change was the
docstring/framing, which previously described the file as "OpenAI's fine-tuning JSONL format ...
directly usable as `client.fine_tuning.jobs.create(...)` input" -- misleading now. Reframed as a
provider-agnostic chat-messages format meant for `tokenizer.apply_chat_template()` at training time,
using whichever model actually gets fine-tuned.

### 4. Docs updated to state the target model explicitly

- `reports/sft_samples.md`: states `Qwen/Qwen2.5-1.5B-Instruct` as the fine-tuning target up top;
  every sample's token count is now from Qwen's tokenizer (labelled as such); added, for the first
  sample only, what Qwen's chat template actually renders the message list to at training time
  (`<|im_start|>system\n...<|im_end|>\n...`) -- clearly marked as reference-only, not what's stored
  in the JSONL; token-length summary section now shows target-model numbers as primary and the
  OpenAI/tiktoken numbers as an explicitly-labelled comparison underneath.
- `README.md`: added a **"Next steps"** section (outside `report.py`'s auto-generated markers, so
  regeneration doesn't wipe it) stating plainly that fine-tuning a hosted API model was considered
  and deliberately not done, and why.
- This file: step-06's original entry left as-is above (not rewritten), this correction section
  added after it -- same pattern as the step-02 and step-04/05 corrections earlier in this file.

**Dependencies added:** `transformers==5.17.0` (`AutoTokenizer` for the target model's real
tokenizer + chat template -- no torch needed, tokenizer/config loading only) and `jinja2==3.1.6`
(required by `transformers.apply_chat_template()` to render the target model's Jinja2 chat
template). `tiktoken` is kept, now justified only as the comparison-only tokenizer, not the
recommendation source.

**Files changed:** `src/ticket_router/make_sft_dataset.py` (rewritten: `FT_BASE_MODEL` config,
target-model tokenizer as the primary/only source for the recommendation, tiktoken kept for
comparison only, samples report shows the target model explicitly), `.env.example`
(`FT_BASE_MODEL`), `requirements.txt` (`transformers`, `jinja2`), `reports/sft_samples.md`
(regenerated), `README.md` (added "Next steps"), `data/processed/sft/*.jsonl` (regenerated with
corrected content -- still gitignored, same as before).

**Verify with:**
```
.venv\Scripts\python.exe src\ticket_router\make_sft_dataset.py
```
Requires network access to download `Qwen/Qwen2.5-1.5B-Instruct`'s tokenizer files from Hugging
Face on first run (cached locally afterward, standard HF cache location). `OPENAI_MODEL` in `.env`
is optional now for this script -- used only for the side-by-side comparison if present, skipped
gracefully (not a STOP) if absent.

**Still did not start training.**

## Correction (post step-06): max_seq_len must cover the true max, not the 95th percentile

The p95-based `max_seq_len=288` truncated 144 train examples (1.10%). That matters more than the
percentage suggests: the assistant's JSON label sits at the **end** of every SFT sequence, so
truncating at 288 cuts the **label**, not just ticket text -- those 144 examples would have taught
the model to emit incomplete JSON. That's poisoning the training set, not merely losing 1.10% of it.
The longest example in the whole training set is 377 tokens -- there's no reason to truncate
anything at that scale. Corrected in four parts, in the order given.

### 1. max_seq_len = 384, confirmed zero truncation on all three splits

`src/ticket_router/make_sft_dataset.py`'s sizing rule changed from "p95 rounded up to the nearest
32" to **"true train max rounded up to the nearest 32"** -- 377 -> **384**. Also checked val (max
330) and test (max 363) before relying on this: both comfortably under 384, so the same cap is safe
for all three splits, not just train.

**Truncation counts at max_seq_len=384 (target-model tokenizer) -- exactly zero everywhere:**

| split | truncated | total |
|---|---|---|
| train | **0** | 13,070 |
| val | **0** | 1,635 |
| test | **0** | 1,633 |

(Previous, wrong p95-based counts: train 144/13,070, val 15/1,635, test 17/1,633.)

### 2. Hard assertion added, fails loudly

After building and tokenizing all three splits, the script now asserts that no example in any
split exceeds `max_seq_len`; on violation it `raise`s an `AssertionError` naming the split, the
count over the limit, and the worst offender's length -- it does not print a warning and continue.
**Verified the assertion actually fires** by hand-testing the same logic against a deliberately
too-low fake cap (200 tokens) on a 50-row sample: correctly raised, naming 36 offending examples,
before this shipped with the real 384 value.

### 3. Padding: per-batch to the batch's longest sequence, not to max_seq_len for every example

`max_seq_len` is a **truncation cap** given to the tokenizer, not a fixed padding target. The
standard QLoRA/SFT stack this project will use (`transformers`/`trl`'s `SFTTrainer`, or a plain
`Trainer` with a causal-LM data collator) pads **dynamically per batch**, to that batch's own
longest sequence (`padding=True` by default) -- not every example out to `max_seq_len`. That only
happens with an explicit `padding="max_length"` collator config, which is not the default and not
planned here. **So raising max_seq_len from 288 to 384 costs almost nothing in compute** -- it only
changes the (rare) batch that happens to contain one of the longer examples; it does not make every
batch bigger. No training code exists yet (this step still does not start training), so this
describes the standard/default behavior of the intended tools, not a setting already locked in code
-- flagged so that whichever collator step-07 actually configures preserves dynamic per-batch
padding rather than switching to fixed-length padding, to keep this true. Recorded in
`reports/sft_samples.md` under "Does raising max_seq_len cost more compute?".

### 4. Docs updated

`reports/sft_samples.md`: the token-length summary now states `max_seq_len=384` with the
true-max-based reasoning (not p95), and a new section answers the padding question. This file
(above): corrected numbers recorded here as this correction section.

**Files changed:** `src/ticket_router/make_sft_dataset.py` (max-based sizing, hard assertion,
padding-cost explanation added to the samples report), `reports/sft_samples.md` (regenerated),
`data/processed/sft/*.jsonl` (regenerated with `max_seq_len=384`'s reasoning reflected in the
report -- file *content* is unchanged, since the JSONL always stores full untruncated text
regardless of `max_seq_len`; only the recommended/asserted cap changed). No dependency change.

**Verify with:**
```
.venv\Scripts\python.exe src\ticket_router\make_sft_dataset.py
```
Should print "Assertion passed: zero examples exceed max_seq_len in any split" and exit 0. Would
raise `AssertionError` and exit non-zero if that were ever violated.

**Still did not start training.**

## step-07: QLoRA fine-tuning notebook + config (no training run yet)

**What was built:** `notebooks/train_qlora.ipynb` (34 cells, Colab-only, free-T4-targeted) and
`train/config.yaml` (every hyperparameter the notebook uses -- nothing hardcoded in the notebook
itself). Base model: `Qwen/Qwen2.5-1.5B-Instruct` (the same `FT_BASE_MODEL` set in step-06, not a
hosted API model -- the whole point of steps 07-12 is a model that can be self-hosted, quantized,
and served in Docker).

**A scope-honest note on local verification, upfront**: this environment has no GPU, and
attempting a CPU-only `torch`+`trl` install to test the training-loop code hit a hard local
disk-space wall (`OSError: [WinError 206]` on a deep temp path, then `[Errno 28] No space left on
device` after moving to a short path and retrying -- the machine's C: drive is at 100% from
something unrelated to this session, 19MB-779MB free depending on the moment). Full end-to-end
QLoRA training (bitsandbytes 4-bit loading, `SFTTrainer`, the actual GPU step) could **not** be
executed or tested here. What COULD be, and was, verified for real before writing a line of the
notebook: the two mechanisms explicitly flagged as correctness-critical in the instructions
(completion-only masking, and padding behavior) -- see below. The rest of the notebook (model
loading, `SFTConfig`/`SFTTrainer` wiring, generation) is written to the current standard
`transformers`/`trl`/`peft` API to the best of available knowledge, but wasn't executable here --
flagged at the top of the notebook itself so this isn't a surprise mid-run.

### Completion-only loss: `trl.DataCollatorForCompletionOnlyLM`, verified by hand

**Mechanism, stated explicitly (as asked): `trl.DataCollatorForCompletionOnlyLM`**, keyed on
`response_template: "<|im_start|>assistant\n"` (Qwen2.5's chat-template assistant marker, in
`train/config.yaml`). This collator finds that token sequence in each example and masks
(`label = -100`, PyTorch's cross-entropy `ignore_index`) everything up to and including it --
system + user tokens are ignored by the loss; only the assistant's JSON response (and its
`<|im_end|>`) contributes.

**Verified for real** (no trl install available -- reproduced the collator's exact token-matching
logic by hand, using only `transformers`' `AutoTokenizer`, already installed from step-06):
1. Checked whether `response_template` tokenizes identically standalone vs. embedded in a full
   formatted sequence (the classic failure mode with this collator on some tokenizers/templates).
   For Qwen2.5: **`<|im_start|>` and `<|im_end|>` are protected special tokens**, so it tokenizes
   identically both ways -- no silent mismatch.
2. Built one real example (system + user + assistant turns, Qwen's chat template applied),
   located the response_template's 3 tokens in the full 64-token sequence at position 44, and
   masked everything through position 46 (inclusive).

**Printed proof (one full example, exactly what the notebook's cell 6 reproduces live)**:

```
total tokens: 64  masked (-100): 47  unmasked (real loss targets): 17

 idx token_id     label  token_text
   0   151644      -100  [MASKED] '<|im_start|>'
   1     8948      -100  [MASKED] 'system'
   ...                                          (system + user turns, all -100)
  44   151644      -100  [MASKED] '<|im_start|>'
  45    77091      -100  [MASKED] 'assistant'
  46      198      -100  [MASKED] 'Ċ'
  47     4913      4913  [LOSS  ] '{"'
  48     4584      4584  [LOSS  ] 'queue'
  ...                                          (assistant JSON content, real token ids)
  62   151645    151645  [LOSS  ] '<|im_end|>'
  63      198       198  [LOSS  ] 'Ċ'
```

47 masked, 17 contributing to loss -- and decoding just the 17 unmasked tokens gives exactly
`'{"queue":"IT Support","priority":"high","type":"Incident"}<|im_end|>\n'`, byte-for-byte the
assistant's turn and nothing else. Full un-truncated listing is in the notebook's own output once
run; this is the same logic `DataCollatorForCompletionOnlyLM` is documented to perform.

### Padding: confirmed dynamic per-batch, not fixed to max_seq_len

**Answer to the question asked directly: dynamic per-batch padding** (`padding=True`, the
collator's default) -- each batch is padded to *that batch's own longest example*, not to
`max_seq_len` for every example. `max_seq_len` (384, from step-06) is a **truncation cap** passed
to the tokenizer, not a padding target. **So raising it costs almost nothing in compute** -- it
only changes the rare batch containing one of the longer examples; it does not make every batch
bigger.

**Verified for real** (`tokenizer.pad()`, no trl/torch needed for this specific check): padded two
synthetic batches of very different native lengths --

```
short batch (native lens 10,15) -> padded lens: [15, 15]
long  batch (native lens 50,60,70) -> padded lens: [70, 70, 70]
```

If padding were fixed to a constant length, both batches would show the same padded length
regardless of their native lengths. They don't -- each batch is padded independently to its own
longest row. Reproduced against the actual `DataCollatorForCompletionOnlyLM` (not just raw
`tokenizer.pad()`) in the notebook's cell 7, with two batches of the real tokenized training data.

### Config highlights (`train/config.yaml` -- full file has every value, with reasoning in comments)

- **QLoRA**: 4-bit NF4, double quantization, bfloat16 compute dtype.
- **LoRA**: r=16, alpha=32, dropout=0.05, on **both** attention (`q/k/v/o_proj`) **and** MLP
  (`gate/up/down_proj`) -- attention-only would leave most of a Qwen2 layer's parameters
  untouched.
- **Training**: 3 epochs, effective batch size 16 (per-device 4 Γ— grad-accum 4), cosine LR
  schedule, `paged_adamw_8bit`, gradient checkpointing on.
- **Best-checkpoint selection**: `eval_strategy=steps, eval_steps=50, load_best_model_at_end=true,
  metric_for_best_model=eval_loss, greater_is_better=false` -- the **best** checkpoint by
  validation loss is kept, not simply the last step.
- **No class weighting** (explicit known-limitation comment in the config): real queue-class
  imbalance exists (e.g. General Inquiry/Human Resources have far fewer rows than Technical
  Support), but this is the first fine-tuning run for the project and the goal is an
  interpretable baseline with the fewest moving parts -- adding weighting now would make it
  unclear whether any result change comes from fine-tuning itself or the weighting scheme.
  Revisit if per-class evaluation later shows minority classes are being ignored.
- **`hub_model_id` deliberately left blank** -- no placeholder HF username was guessed; the
  notebook raises a clear `ValueError` at the push step if it's still empty when reached.

### Notebook structure (14 numbered sections, cell order stated at the top of the notebook itself)

Check GPU -> install deps -> get the repo (flags that `data/processed/` is gitignored, so a plain
`git clone` will NOT include the actual training data -- upload/sync it separately) -> load
config.yaml -> load tokenizer + SFT datasets -> **verify completion-only masking** (live,
real-token proof) -> **verify dynamic padding** (live, real-token proof) -> load base model in
4-bit + attach LoRA -> build a config-driven trainer factory -> **smoke test** (~100 steps: loss
curve + 5 generated outputs, validated against `schema.TicketLabels` -- reused from step-03, not
reimplemented) -> **explicit STOP-AND-CONFIRM markdown cell** before the full run -> **full
training run** (loss curve + confirms `trainer.model` is the best checkpoint, not the last) ->
save adapter + push to HF Hub (under the user's own account/repo id) -> **post-train preview**:
generate + print alongside gold labels on 20 val examples.

Expected runtime (approximate, free T4): smoke test ~5-10 min, full run ~45-90 min. Expected VRAM:
~6-10 GB (comfortable on the T4's 16 GB) -- both stated at the top of the notebook, along with the
exact cell order to run.

**Dependencies**: none added to this project's `requirements.txt` -- the training stack
(`transformers`, `trl`, `peft`, `accelerate`, `bitsandbytes`, `datasets`) is installed by the
notebook's own first `!pip install` cell, inside the Colab runtime only, deliberately kept
separate from the local pipeline's environment (which never needs a GPU training stack).

**Files added:** `notebooks/train_qlora.ipynb`, `train/config.yaml`. **Files changed:**
`.gitignore` (added `outputs/`, defensive -- Colab checkpoint/adapter paths referenced in
`train/config.yaml`, never expected to materialize in this repo since the adapter is pushed to
the Hub instead).

**Did not run any training, locally or otherwise -- as instructed.** Waiting on the user to run
`notebooks/train_qlora.ipynb` on Colab and report back the result.

**Next step:** step-08 — not started yet (to be defined once the Colab run's result is known).

## Correction (post step-07): three pre-flight fixes to train/config.yaml + the notebook

Requested before running on Colab, no training started. Three independent fixes, all applied.

### 1. bf16/fp16 compute dtype decided at runtime, not hardcoded

`train/config.yaml`'s `quantization.bnb_4bit_compute_dtype: bfloat16` was wrong for the
free Colab tier's usual T4 GPU: T4 is Turing (CUDA compute capability 7.5), and bf16 needs
Ampere or newer (compute capability major >= 8). Fixed in the notebook's GPU-check cell
(now cell 1): after confirming a GPU is present, it reads
`torch.cuda.get_device_capability()`, sets `USE_BF16 = (major >= 8)` and
`COMPUTE_DTYPE = torch.bfloat16 if USE_BF16 else torch.float16`, and prints the detected
GPU name/compute capability and the chosen dtype before anything else runs. `COMPUTE_DTYPE`
now feeds `BitsAndBytesConfig.bnb_4bit_compute_dtype` (cell 9) and `USE_BF16` feeds the
trainer's `bf16`/`fp16` flags (cell 10's `build_trainer`, previously hardcoded
`bf16=True` regardless of GPU -- that was a second, related bug fixed at the same time).
`train/config.yaml` no longer sets `bnb_4bit_compute_dtype` at all -- replaced with a
comment explaining it's runtime-decided and why.

### 2. eval_steps/save_steps raised to 250 + mid-training eval on a seeded subsample

At `eval_steps: 50`, 13,070 train examples / effective batch 16 -> ~817 steps/epoch ->
~2,450 steps over 3 epochs -> 49 full evaluations over the 1,635-example validation set --
too much GPU time spent measuring instead of learning on a time-limited Colab session.
Fixed:
- `eval_steps`/`save_steps`: 50 -> **250** (~10 evaluations over the full run).
- New `eval_subsample_size: 400` / `eval_subsample_seed: 42` in `train/config.yaml`. The
  notebook (cell 6) now builds `eval_subsample = raw_datasets["val"].shuffle(seed=...).select(...)`
  once, and both the smoke test and the full run evaluate against it during training --
  speed only.
- The **full** 1,635-example validation set is kept untouched and used exactly once: a new
  notebook step (**14, "Select the best checkpoint using the FULL validation set"**,
  between the full run and the save/push step) re-evaluates each of the up to
  `save_total_limit`=3 checkpoints saved during training on the full val set, picks the
  lowest `eval_loss`, and loads that checkpoint into `trainer.model` -- the checkpoint
  that actually gets saved/pushed/previewed is the FULL-val winner, not whichever the
  subsample-monitored last step happened to be.
- `load_best_model_at_end` changed `true` -> **false**: with the subsample as the
  training-time `eval_dataset`, Trainer's own `load_best_model_at_end` would have picked
  the "best" checkpoint by the subsample metric, not the full one -- final selection is
  done manually instead (the new step 14).
- `train/config.yaml`'s "Evaluation & checkpointing" section now states explicitly, in
  comments, which of the two validation numbers is which, so the loss curve plotted during
  training (subsample) is never mistaken for a full-val metric -- the notebook's loss-curve
  cells (steps 11 and 13) also label the eval-loss line with the subsample size directly on
  the plot legend, and step 13's cell prints an explicit note pointing at step 14.

### 3. hub_model_id set + a pre-flight HF token check

`hub_model_id` in `train/config.yaml`: `""` -> **`Omar-Mohsen22/ticket-router-qwen2.5-1.5b-qlora`**.

New notebook step (**5, "Check Hugging Face token (write access)"**), placed right after
config load and before the smoke test, tokenizer/dataset loading, or any GPU-model work: it
resolves a token via `huggingface_hub.get_token()` (env var / Colab `HF_TOKEN` secret /
prior `login()`), raises a clear `RuntimeError` if none is found, and then confirms WRITE
access with a real probe (`HfApi.create_repo(hub_model_id, exist_ok=True)`, not just parsing
`whoami()`'s scope fields, since token-permission shapes vary by token type) -- raising a
second clear error naming the missing permission if that probe fails. This runs before the
smoke test, so a missing/insufficient token fails in seconds instead of after a ~45-90
minute full run, at the push step. The push step (now step 15) was also updated to reuse
this already-validated token (`token=token` passed to `push_to_hub`) instead of calling
`huggingface_hub.login()` a second time, which would otherwise prompt interactively again.

### Notebook renumbering + a rebuild after an editing-tool failure

Applying the above meant inserting 2 new steps (5 and 14) into the notebook's existing
14-step structure, renumbering everything from step 5 onward to 16 steps total. The
in-place cell-by-cell edit tool was used first but produced duplicated/misordered cells
after the first insert shifted every subsequent cell's position (each edit after that
targeted a stale position, since this notebook's cells have no stable `id` field for most
cells and the edit tool's `cell_id` addressing is position-derived) -- caught immediately by
re-reading the file's raw JSON (`json.load` + inspecting `cell_type`/`source` per cell,
not just the rendering tool's view) before it was committed. **Fixed by discarding that
attempt and rebuilding the entire notebook from a single Python script** (`json.dump` of an
explicit cell list, each cell given a real UUID-derived `id`) with the exact intended final
content for all 38 cells (16 numbered steps + sub-cells), rather than patching the
corrupted file further. Verified after rebuilding: valid JSON, `nbformat`/`nbformat_minor`
and Colab metadata preserved from the original file, all 18 code cells `ast.parse()`-clean,
`train/config.yaml` re-parses with `yaml.safe_load` and shows the exact expected values
(`eval_steps`/`save_steps`=250, `eval_subsample_size`=400, `load_best_model_at_end`=False,
`hub_model_id` set, no `bnb_4bit_compute_dtype` key).

**Files changed:** `train/config.yaml`, `notebooks/train_qlora.ipynb` (both -- no other file
touched). **No dependency added.**

**Verify with:**
```
.venv\Scripts\python.exe -c "import yaml; import json; c = yaml.safe_load(open('train/config.yaml')); print(c['eval_steps'], c['hub_model_id'])"
.venv\Scripts\python.exe -c "import json, ast; nb = json.load(open('notebooks/train_qlora.ipynb', encoding='utf-8')); [ast.parse(''.join(l for l in ''.join(c['source']).splitlines(keepends=True) if not l.strip().startswith('!'))) for c in nb['cells'] if c['cell_type']=='code']; print('ok', len(nb['cells']), 'cells')"
```
Still did not run any training, locally or otherwise -- as instructed. Same open item as
before: waiting on the user to run `notebooks/train_qlora.ipynb` on Colab and report back.

**Next step still step-08 — not started, unchanged by this correction.**

## Correction (post step-07, continued): checkpoint-eviction race between `load_best_model_at_end=false` and `save_total_limit`

Flagged before the previous correction's fixes were exercised on Colab: turning
`load_best_model_at_end` off (so the FULL-val checkpoint selection in step 14 does the real
picking) also turns off Trainer's own protection of the best checkpoint from its rotation --
`save_total_limit` was still `3`. At ~2,450 full-run steps / `save_steps`=250, ~10 checkpoints
get written; a limit of 3 keeps only the *last* 3 on a plain FIFO basis, with no awareness of
which one is actually best. On 13,070 examples over 3 epochs, overfitting typically starts
before the run ends, so the true best checkpoint could have been deleted long before step 14
ever got to look at it -- silently, no error, no warning.

**Fix: `save_total_limit: 3` -> `null`** in `train/config.yaml` (parses to Python `None`,
which `transformers.TrainingArguments` treats as "keep every checkpoint, never rotate").
These are LoRA adapters, not full model weights -- a few tens of MB each -- so keeping all
~10 of them is cheap in principle. `train/config.yaml`'s "Evaluation & checkpointing" section
now explains this interaction directly in a comment (why a finite limit is unsafe once
`load_best_model_at_end` is false), and the "two different validation numbers" comment block
was updated to say "every checkpoint saved above -- `save_total_limit` is null" instead of
the now-stale "up to `save_total_limit` checkpoints."

**Not just asserted cheap -- measured, before the full run runs:** the notebook's smoke-test
cell (step 11) now also computes the real on-disk size of one saved checkpoint
(`sum(f.stat().st_size for f in Path(ckpt_dir).rglob("*") if f.is_file())`), projects the
full run's checkpoint count from the same step-math as `train/config.yaml`'s comment
(`ceil(13070 / 16) = 817` steps/epoch x 3 epochs = 2,450 steps, `ceil(2450 / 250)` = ~10
checkpoints), multiplies to a projected total GB, and compares it against
`shutil.disk_usage(REPO_ROOT).free` -- `REPO_ROOT` because that's wherever the checkpoints
will actually land, whether Colab-local (`git clone` option) or a mounted Google Drive
(the default option). If the projection exceeds free space, it prints an explicit `WARNING`
and says to stop and decide together, rather than silently shrinking `save_total_limit`
itself -- per the instruction, the notebook does not make that call unilaterally. The new
"STOP AND CONFIRM" cell (step 12) now lists checking for that `WARNING` as a third condition
alongside the loss-curve and generated-JSON checks already there.

**Edited via `NotebookEdit` "replace" only this time (no insert/delete)** -- the previous
correction's cell-position corruption came from *inserting* cells into a notebook where most
cells had no persisted `id`, which forced the read tool to fabricate position-based labels
that went stale after the first insert. The full rebuild from that correction gave every cell
a real, stable UUID-derived `id`, so this round's 4 targeted `replace` edits (the overview
cell's runtime/disk estimates, the smoke-test cell's new disk-size code, and two markdown
cells' wording) landed on the correct cells with no repositioning risk -- verified anyway,
the same way as last time: raw JSON re-parsed, all 38 cells still present with unique ids,
all 18 code cells still `ast.parse()`-clean, `train/config.yaml` re-parses with
`yaml.safe_load` to `save_total_limit: None` exactly.

**Files changed:** `train/config.yaml`, `notebooks/train_qlora.ipynb` (both -- no other file
touched). **No dependency added** (`pathlib`, `shutil`, `math`, `glob` are all stdlib).

**Verify with:**
```
.venv\Scripts\python.exe -c "import yaml; c = yaml.safe_load(open('train/config.yaml')); print(repr(c['save_total_limit']))"
.venv\Scripts\python.exe -c "import json, ast; nb = json.load(open('notebooks/train_qlora.ipynb', encoding='utf-8')); [ast.parse(''.join(l for l in ''.join(c['source']).splitlines(keepends=True) if not l.strip().startswith('!'))) for c in nb['cells'] if c['cell_type']=='code']; print('ok', len(nb['cells']), 'cells')"
```
Still did not run any training, locally or otherwise -- as instructed.

**Next step still step-08 — not started, unchanged by this correction.**

## Correction (post step-07, continued): trl 1.13.0 removed the collator this notebook depended on -- switched to prompt-completion format + `completion_only_loss`

Reported directly from the real Colab environment, not assumed: `trl==1.13.0`,
`transformers==5.17.0`, `peft==0.20.0`, `torch==2.11.0+cu128`.
**`trl.DataCollatorForCompletionOnlyLM` no longer exists in trl 1.13.0 -- trl exports no
collator classes at all in this version.** The masking mechanism the step-07 notebook was
built around (verified by hand against an *older* trl API, before any of this could be
tested against a real Colab session -- see the original step-07 entry's own disclaimer about
that) simply isn't importable any more.

**The obvious replacement was tried and is a trap, not a fix.** `SFTConfig` in this trl
version exposes `completion_only_loss` and `assistant_only_loss` instead of a collator
class. `assistant_only_loss` relies on the chat template's own `{% generation %}` markers
via `apply_chat_template(return_assistant_tokens_mask=True)` -- and Qwen2.5's chat template
has **no** `{% generation %}` markers, so the returned `assistant_masks` array comes back
**all zeros**. It does not raise. Used as-is, it would have silently masked every token and
trained on nothing, with a loss curve that might even look plausible. Confirmed by direct
probing, not assumed either.

### 1. Dataset format: `make_sft_dataset.py` now emits prompt/completion, not one message list

`src/ticket_router/make_sft_dataset.py`: `build_example()` now returns
`{"prompt": [system, user], "completion": [assistant]}` -- TRL's conversational
prompt-completion format -- instead of `{"messages": [system, user, assistant]}`. This is
what lets `completion_only_loss=True` find the loss boundary from the **data's own explicit
split** (by tokenized length) rather than from a `response_template` string match against a
rendered sequence, or from chat-template generation-mask support that Qwen2.5 doesn't have.

Everything downstream of `build_example()` that read `ex["messages"]` was updated to read
`ex["prompt"]`/`ex["completion"]` instead (`write_samples_report`'s user/assistant text
extraction, the rendered-chat-template reference sample, and both token-length functions --
`num_tokens_target`/`num_tokens_openai` -- via a new `full_messages(ex)` helper that just
concatenates `prompt + completion` back into one list purely for measurement, since the
**total rendered sequence** -- and therefore whether the assistant's JSON at the end gets
truncated -- is unaffected by which JSON field the messages are split across).

**Regenerated all three splits** (`.venv\Scripts\python.exe src\ticket_router\make_sft_dataset.py`):
same numbers as before the format change -- 13,070/1,635/1,633 examples, train token
lengths min=167/p50=236/p95=277/p99=290/**max=377**, `max_seq_len`=**384** (unchanged, true-max
based, not a percentile -- see the step-06 correction), **zero truncation on all three
splits** (0/13070, 0/1635, 0/1633) -- confirms the prompt/completion split doesn't change
what gets tokenized, only how it's stored. `reports/sft_samples.md` regenerated to match
(diff is format-only: `{"messages": [...]}` -> `{"prompt": [...], "completion": [...]}` in
each shown raw JSONL line; token counts and every other section are byte-identical).
`data/processed/sft/*.jsonl` regenerated (gitignored, same convention as before).

### 2 + 3. Notebook: collator cell replaced with a masking-verification cell that checks CONTENT

`notebooks/train_qlora.ipynb` step 7 ("Verify completion-only masking"): the old cell that
built `collator = DataCollatorForCompletionOnlyLM(...)` is gone -- no trace of that class or
of `response_template` remains anywhere as executable code (grepped the raw notebook JSON to
confirm; the two remaining textual mentions are in markdown/comments explaining what changed
and why, not code). Masking is now applied purely via
`SFTConfig(completion_only_loss=config["completion_only_loss"])` in the trainer factory
(step 10) -- no `data_collator=` argument is passed to `SFTTrainer` at all, in either the
main trainer factory or the step-14 checkpoint-evaluation helper (both previously passed
`data_collator=collator`).

**The new verification cell reproduces, by hand, the exact boundary trl 1.13.0 uses for
`completion_only_loss`**: tokenize the prompt alone with `add_generation_prompt=True`
(renders through the assistant-start marker -- the exact prefix the full sequence has before
the assistant's own content begins), tokenize prompt+completion together, and assert the
prompt-alone ids are an exact prefix of the full sequence. Then -- the part the instruction
specifically called out as insufficient last time -- it **decodes the unmasked (completion)
tokens and asserts they equal the gold assistant JSON exactly**
(`json.loads(decoded) == json.loads(gold)`), not merely that `n_loss > 0`. A check that only
confirms some tokens are unmasked would NOT have caught the `assistant_only_loss` trap above
(that mechanism also "returns a mask" -- it's just all zeros); decoding and comparing real
content is the check that can't be fooled that way. Printed output format matches the
original step-07 cell's style (per-token idx/token_id/label/token_text table) so the two are
directly comparable.

**Knock-on fix, not explicitly requested but necessary to keep the notebook working**: step
8's padding-verification cell also depended on the deleted `collator` object and the old
`example["messages"]` field name. Rewritten to pad via `tokenizer.pad()` directly (removes
the trl-collator dependency entirely -- padding behavior is a property of the tokenizer's
own `.pad()` call, unrelated to which masking mechanism is used) and to tokenize the new
prompt+completion format. Also updated: `generate_one()` (used by both the smoke-test
generation cell and the post-train preview cell) took a full `messages` list and sliced
`messages[:2]` to get the prompt -- now takes `prompt_messages` directly (the dataset's
`"prompt"` field already excludes the completion, no slicing needed), and both call sites
read `example["prompt"]`/`example["completion"][0]["content"]` instead of
`example["messages"][:2]`/`example["messages"][2]["content"]`.

### 4. Exact version pins in the install cell -- and an honest gap where versions weren't verified

`notebooks/train_qlora.ipynb`'s install cell now pins the three versions actually read from
the Colab session: `transformers==5.17.0`, `trl==1.13.0`, `peft==0.20.0`. `torch` stays
unpinned on purpose (ships with Colab's image; pinning it risks fighting Colab's own
CUDA-matched build) -- commented explicitly.

**`accelerate`, `bitsandbytes`, `datasets`, `pyyaml`, and `huggingface_hub` were NOT pinned
to an exact version.** Their currently-installed versions in the target Colab environment
were never given or probed -- only trl/transformers/peft/torch were. Inventing exact-looking
pins for the other five would repeat the precise mistake this correction exists to fix
(an unverified assumption baked into the notebook, discovered only when it broke). Instead, a
new cell right after install prints every package's actually-resolved version
(`importlib.metadata.version(...)`), labeled clearly as pinned-and-confirmed
(transformers/trl/peft), unpinned-from-Colab's-image (torch), or unpinned-and-unverified
(the other five) -- so those five can be pinned for real in a follow-up once their versions
are reported back, rather than guessed now.

### 5. `train/config.yaml`: `response_template` removed, replacement mechanism documented

The "Completion-only loss" section's comment block was rewritten in full: explains that the
mechanism changed (dataset-format-based `completion_only_loss`, not a `response_template`
string matched against a `DataCollatorForCompletionOnlyLM`), why the collator approach broke
(trl 1.13.0 exports none), why `assistant_only_loss` was rejected (Qwen2.5's chat template
has no `{% generation %}` markers -> silent all-zeros mask), and what verifies it now (the
notebook's content-checked masking cell, not merely a token-boundary check).
`response_template: "<|im_start|>assistant\n"` was deleted -- nothing in the notebook reads
that key any more.

**Files changed:** `src/ticket_router/make_sft_dataset.py`, `train/config.yaml`,
`notebooks/train_qlora.ipynb`, `reports/sft_samples.md` (regenerated), plus
`data/processed/sft/*.jsonl` (regenerated, gitignored). **No dependency added** to the local
pipeline (`pandas`/`transformers`/etc. already installed); the notebook's own pinned
versions are Colab-runtime-only, as before.

**Verify with:**
```
.venv\Scripts\python.exe src\ticket_router\make_sft_dataset.py
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -c "import json; ex = json.loads(open('data/processed/sft/train.jsonl', encoding='utf-8').readline()); print(list(ex.keys()))"
.venv\Scripts\python.exe -c "import yaml; c = yaml.safe_load(open('train/config.yaml')); print('response_template' in c, c['completion_only_loss'])"
.venv\Scripts\python.exe -c "import json, ast; nb = json.load(open('notebooks/train_qlora.ipynb', encoding='utf-8')); [ast.parse(''.join(l for l in ''.join(c['source']).splitlines(keepends=True) if not l.strip().startswith('!'))) for c in nb['cells'] if c['cell_type']=='code']; print('ok', len(nb['cells']), 'cells')"
```
Still did not run any training, locally or otherwise -- as instructed. The notebook's actual
end-to-end training loop (bitsandbytes 4-bit loading, `SFTTrainer.train()`, the real GPU
step) still could not be executed or tested locally -- same constraint as the original
step-07 entry. This correction fixes exactly what was reported broken from a real Colab run;
whether `completion_only_loss` on the new prompt/completion format behaves as documented
under trl 1.13.0's actual internals is still unverified until the notebook is run again.

**Next step still step-08 — not started, unchanged by this correction.**

## Correction (post step-07, continued): pin the remaining 5 libraries + fix REPO_ROOT drift

Two independent fixes, requested together.

### 1. The remaining 5 libraries pinned with their real Colab-read versions

The previous correction left `accelerate`, `bitsandbytes`, `datasets`, `pyyaml`, and
`huggingface_hub` unpinned in the install cell, on purpose -- their exact versions in the
target Colab environment hadn't been read yet, and guessing would have repeated the mistake
that correction existed to fix. Given the real versions this time
(`accelerate==1.14.0`, `bitsandbytes==0.50.2`, `datasets==4.8.5`, `pyyaml==6.0.3`,
`huggingface_hub==1.29.0`), the install cell now pins all 8 libraries it installs exactly;
only `torch` stays unpinned (ships with Colab's own image -- unchanged reasoning from
before). The version-print cell right after was simplified to match: every one of the 8 is
now printed under "Pinned (confirmed exact versions)" -- there's no more "unpinned, report
these back" section, since nothing is unpinned any more except torch.

### 2. REPO_ROOT drift -- same failure mode as the earlier data/README.md drift, different file

Reported: the "Get the repo" cell still defaulted to Google Drive
(`/content/drive/MyDrive/ticket-router`) and hard-`assert`ed that path existed, which fails
on a fresh Colab session that isn't using Drive. The user had been hand-patching this cell
directly in Colab every session, which is silently lost on every re-upload of the notebook --
the exact same class of problem already hit once with `data/README.md`'s generator drifting
out of sync with hand-edits (see the step-02 corrections). Fixed at the source this time, in
the notebook itself, not by patching a running session:

- `REPO_ROOT` now defaults to **`/content/ticket-router`** (Colab-local disk), not Drive.
  Reasoning added directly in the cell: local disk is faster I/O for training, and it's the
  exact path the step-11 checkpoint disk-size check measures free space at (so that check and
  the actual training run always agree on which filesystem matters).
- The cell now runs `os.makedirs(f"{REPO_ROOT}/train", exist_ok=True)` and
  `os.makedirs(f"{REPO_ROOT}/data/processed/sft", exist_ok=True)` -- creates the folders this
  notebook needs so an upload into them (rather than a `git clone`, which would create the
  structure automatically) doesn't need the directories to exist by hand first.
- The old hard `assert` on Drive paths is gone. Instead, the cell checks 4 required paths
  (`train/config.yaml`, `data/processed/sft/train.jsonl`, `data/processed/sft/val.jsonl`, and
  `src/` -- the last one added beyond what was originally asserted, since step 6/11/16 all
  need `ticket_router.schema.TicketLabels` importable from it) and **prints** which are still
  missing, rather than raising -- a fresh `REPO_ROOT` legitimately has nothing in it the
  first time this cell runs on a new session, so asserting on that would be asserting on an
  expected, not exceptional, state.
- Google Drive is kept as a **commented-out alternative** in the same cell (3 lines: mount,
  set `REPO_ROOT`), with a one-line reason for when it's actually the better choice: it
  persists checkpoints across a disconnected/reconnected Colab session, which local disk does
  not -- relevant specifically for the ~45-90 minute full run (step 13), not the smoke test.

**Files changed:** `notebooks/train_qlora.ipynb` only (`cdef0d15` install cell, `020aec62`
version-print cell, `fb693489`/`51f4fa52` -- the "Get the repo" markdown + code). No other
file touched. **No dependency added.**

**Verify with:**
```
.venv\Scripts\python.exe -c "import json, ast; nb = json.load(open('notebooks/train_qlora.ipynb', encoding='utf-8')); [ast.parse(''.join(l for l in ''.join(c['source']).splitlines(keepends=True) if not l.strip().startswith('!'))) for c in nb['cells'] if c['cell_type']=='code']; print('ok', len(nb['cells']), 'cells')"
```
Still did not run any training, locally or otherwise -- as instructed.

**Next step still step-08 — not started, unchanged by this correction.**

## step-08: Colab-tested fixes to train_qlora.ipynb -- Drive-default resumable training, real masking-check bug fixed, TRL's own labels verified

**What was built:** three edits to `notebooks/train_qlora.ipynb` only (no other file
touched, per instruction) -- the first real fixes driven by feedback from an actual Colab
run of the notebook, not just local reasoning about its API surface.

**1. Google Drive as the default `REPO_ROOT`, and the full run made resumable.**
The Colab runtime disconnects frequently when left idle; the previous default
(`/content/ticket-router`, Colab-local) meant a disconnect wiped both the uploaded data and
every saved checkpoint, restarting the ~45-90 minute full run from zero. Cell 7 now defaults
to `/content/drive/MyDrive/ticket-router` (mounted via `drive.mount`), with local disk kept
as a commented-out alternative -- reasoning recorded directly in the cell's comments: Drive
survives a disconnect; the I/O cost is small because `load_dataset()` reads the JSONL files
once and `datasets` memory-maps them locally afterward, and checkpoints are LoRA adapters
only (tens of MB, ~10 of them across the run); the base model's own weights still download
to Colab's local HF cache every session on purpose (cheaper than reading ~3GB back over
Drive's FUSE mount); uploading into `MyDrive/ticket-router` is a one-time setup. The
`os.makedirs` calls and the `required_files`/`missing` reporting block were left completely
unchanged. The adjacent "Get the repo" markdown cell was also updated so its prose doesn't
contradict the code beneath it (the same drift class already hit once with
`data/README.md` -- see the step-02 corrections).

Cell 30 (the full training run) now checks `full_output_dir` for existing
`checkpoint-*` directories before calling `trainer.train()`: if any exist, it resumes from
the latest one (`trainer.train(resume_from_checkpoint=<latest>)`) and prints which checkpoint
it resumed from; if none exist, it starts fresh and prints that instead.
`resume_from_checkpoint=True` is never passed unconditionally (it raises on an empty
directory -- e.g. the very first run).

Cell 23 (the smoke-test disk-size projection) still calls `shutil.disk_usage(REPO_ROOT)`
unchanged, but now prints the raw `total`/`used`/`free` GB it returns (not just `free`), plus
an explicit note: it is **unverified** whether `shutil.disk_usage()` reports Google Drive's
real account quota on a FUSE-mounted path, or something else entirely -- not assumed either
way, flagged for the user to verify by hand against `drive.google.com`'s own storage
indicator if the numbers look implausible, before trusting the disk projection.

**2. The real masking-verification bug, from an actual Colab run against
`Qwen/Qwen2.5-1.5B-Instruct`:**
```
AssertionError: Prompt tokens are not an exact prefix of the full sequence
```
Cause: the previous version of cell 15 (step 7) called
`apply_chat_template(..., tokenize=True)` separately for the prompt and for
prompt+completion, and asserted the resulting token-id lists lined up as a prefix -- they
didn't, for this tokenizer. Fixed by rendering to **text** first (`tokenize=False`),
asserting the **text**-prefix relation (guaranteed by the chat template's own construction),
and only then tokenizing each rendered string independently with `add_special_tokens=False`.
Everything else in the cell (the full per-token MASKED/LOSS table, the `n_loss > 0`
assertion, the decode-and-compare-against-gold-JSON content check) was left unchanged. The
cell's comment claiming this was "exactly the boundary trl 1.13.0's SFTTrainer uses" was
corrected to claim only what's actually true: it verifies the boundary is well-defined at the
tokenizer level, not that it matches TRL's real internals -- that's what item 3 verifies.

**Independently verified locally, not just trusted from the instruction** -- the target
model's tokenizer was already cached locally from step-06, so this needed no GPU/trl/torch.
Ran both the OLD and NEW tokenization approaches against 30 real training examples from
`data/processed/sft/train.jsonl`:
- **OLD approach (token-prefix check): failed on 30/30 examples** -- reproduces the exact
  Colab `AssertionError` locally, confirming the reported bug is real and not
  environment-specific.
- **NEW approach (text-prefix, then tokenize separately): passed on 30/30 examples** --
  `full_text.startswith(prompt_text)` held every time, and every decoded completion matched
  its gold JSON exactly.

**3. New cell verifying TRL's actual labels, not our own reconstruction** -- inserted
immediately after the trainer factory (step 10). Builds a throwaway `SFTTrainer` via
`build_trainer()` into a `tempfile.mkdtemp()` directory, pulls one real batch from
`trainer.get_train_dataloader()`, and for every row: decodes the tokens where
`labels != -100` and asserts they parse as JSON with exactly the keys `queue`, `priority`,
`type` (`STOP: do not train until this is fixed` on failure), asserts no row has zero
unmasked positions, and prints row 0's masked/unmasked counts and decoded text so the result
is visible, not a silently-passing assertion. This is deliberately the check that
`assistant_only_loss` could NOT have passed even by accident (that mechanism also "returned a
mask" -- it was just silently all zeros) -- it inspects TRL's real tensors, not a
boundary computed independently of them.

**Could not be verified locally** -- `get_train_dataloader()` needs a real `SFTTrainer`
wrapping an actual (4-bit-quantized) model, which needs `trl`/`bitsandbytes`/a GPU, none of
which are available in this environment (same constraint noted throughout the step-07
entries). Flagged directly in the new cell's own markdown. This is the one piece of this
step-08 correction that is still unconfirmed until run on Colab.

**Files changed:** `notebooks/train_qlora.ipynb` only -- cell 7 (REPO_ROOT + markdown above
it), cell 15 (masking-verification tokenization + comment), cell 23 (disk-usage raw
print + uncertainty note), cell 30 (resumable full run), and two new cells inserted after
cell 21 (TRL label-check markdown + code). No other file touched, and no dependency added.

**Verify with:**
```
.venv\Scripts\python.exe -c "import json, ast; nb = json.load(open('notebooks/train_qlora.ipynb', encoding='utf-8')); [ast.parse(''.join(l for l in ''.join(c['source']).splitlines(keepends=True) if not l.strip().startswith('!'))) for c in nb['cells'] if c['cell_type']=='code']; print('ok', len(nb['cells']), 'cells')"
```
The 30/30-vs-30/30 masking comparison above is reproducible locally (Qwen tokenizer only, no
GPU) but was a one-off diagnostic script, not committed as a script of its own -- reproducing
it means re-running the same `apply_chat_template`/`tokenizer()` calls shown in cell 15
against rows from `data/processed/sft/train.jsonl` by hand.

Still did not run any training, locally or otherwise. The GPU-dependent parts of this
notebook (the actual QLoRA training loop, and now also item 3's TRL-label check) remain
unverified until run on Colab.

**Next step still step-08's own Colab run — waiting on the user to run the corrected
notebook and report back what happens (the smoke test, the disk projection, and now also
whether the new TRL-label-check cell passes).**

## step-09: fix step 8's padding-check crash -- same `apply_chat_template(tokenize=True)` bug, third time

**What was built:** one fix to `notebooks/train_qlora.ipynb`'s cell 17 (the padding-check
cell, "## 8. Confirm padding: dynamic per-batch, not fixed to `max_seq_len`"), plus a full
notebook-wide search for the same bug pattern -- reported below, not yet fixed elsewhere.

**The bug, reported from a real Colab run:**
```
ValueError: type of {'attention_mask': [...], 'input_ids': [...]} unknown: <class 'dict'>
```
Cause: `tokenize_full()` called `tokenizer.apply_chat_template(..., tokenize=True, ...)`,
which returns a dict-like (`input_ids` + `attention_mask`), not a plain list of ints. The
function then wrapped that dict inside `{"input_ids": ids}`, so `tokenizer.pad()` received a
list of dicts instead of a list of int-lists, and raised. **Exactly the same failure mode as
the step-08 masking-cell bug**: `apply_chat_template(tokenize=True)` does not return what the
variable name (`ids`) implies.

**Fixed the same way that cell was fixed** (per instruction): render to text first
(`tokenize=False`), then tokenize the text with the plain tokenizer call:
```python
def tokenize_full(ex):
    text = tokenizer.apply_chat_template(
        ex["prompt"] + ex["completion"], tokenize=False, add_generation_prompt=False,
    )
    ids = tokenizer(
        text, truncation=True, max_length=config["max_seq_len"],
        add_special_tokens=False,
    )["input_ids"]
    return {"input_ids": ids}
```
The rest of the cell (the batch-building, `tokenizer.pad()` calls, and the print statements
demonstrating dynamic per-batch padding) is unchanged.

**Verified locally, not just trusted** -- same approach as the last two rounds: ran the fixed
`tokenize_full()` against 12 real training examples using the locally-cached Qwen2.5-1.5B-Instruct
tokenizer (no GPU/trl needed for this specific check). Confirmed `tokenize_full()` now returns
a plain `list` of ints (previously would have been a dict), and that `tokenizer.pad()` succeeds
and still demonstrates the thing this cell exists to prove: batch A (4 examples, native lengths
268/231/230/194) padded to 268 for every row; batch B (8 examples, native lengths up to 292)
padded to 292 for every row -- two *different* padded lengths, confirming padding is still
dynamic per-batch, not fixed to `max_seq_len`=384, after the fix.

**Notebook-wide search for the same pattern, as requested -- not fixed, only reported:**
grepped every cell's source for `apply_chat_template` and for `tokenize=True`. Three
occurrences of `apply_chat_template` besides the one just fixed:
- **Cell 14** (markdown, step 7's intro): a **prose mention** of
  `apply_chat_template(return_assistant_tokens_mask=True)` describing the rejected
  `assistant_only_loss` mechanism -- not executable code.
- **Cell 15** (code, step 7's masking-verification cell): two real calls, both already
  `tokenize=False` (fixed in the step-08 masking-cell correction). A comment in this same
  cell mentions `tokenize=True` in prose, describing the *old, already-fixed* bug -- also not
  executable code.
- **Cell 29** (code, `generate_one()` -- defined in step 11's "5 generated outputs" sub-cell,
  and reused as-is by step 16's post-train preview, cell 77bb77ef): **one real call with
  `tokenize=True`**, combined with `add_generation_prompt=True` and `return_tensors="pt"`:
  ```python
  prompt_ids = tokenizer.apply_chat_template(
      prompt_messages, tokenize=True, add_generation_prompt=True, return_tensors="pt",
  ).to(model.device)
  ```
  This is the **one remaining live occurrence of the exact pattern that has now broken this
  notebook three times.** Not changed in this step, per instruction ("do not change them
  yet, just list them"). Whether `return_tensors="pt"` changes `apply_chat_template`'s return
  type enough to make this particular call safe is **not verified** -- it needs `torch`,
  which is not installed locally, so it could not be checked the way the other two bugs were
  before being reported. Flagged here as the most likely fourth instance of this bug class,
  for the user to decide whether to fix preemptively or wait and see if it breaks on Colab
  like the previous two did.

**Files changed:** `notebooks/train_qlora.ipynb` only (cell `bf028e69` / step 8). No other
file touched, no dependency added.

**Verify with:**
```
.venv\Scripts\python.exe -c "import json, ast; nb = json.load(open('notebooks/train_qlora.ipynb', encoding='utf-8')); [ast.parse(''.join(l for l in ''.join(c['source']).splitlines(keepends=True) if not l.strip().startswith('!'))) for c in nb['cells'] if c['cell_type']=='code']; print('ok', len(nb['cells']), 'cells')"
```
The local before/after comparison (dict-wrapped-in-dict vs. plain list, and the two different
padded batch lengths) is reproducible with the Qwen tokenizer alone, no GPU -- same as the
30/30-vs-30/30 comparison in step-08, not committed as a script of its own.

Still did not run any training, locally or otherwise. `generate_one()`'s `tokenize=True` call
(cell 29) remains an open, unverified risk -- flagged, not fixed.

**Next step: still step-08's own Colab run, now also covering this cell-17 fix and the
open question about cell 29's `generate_one()`.**

## step-10: fix build_trainer() crash -- trl 1.13.0's SFTConfig dropped max_seq_length and warmup_ratio

**What was built:** two fixes to `notebooks/train_qlora.ipynb`, both driven by a real probe
of the installed `SFTConfig` class on Colab (trl 1.13.0, transformers 5.17.0), not guessed --
the probe found 133 total fields, of which exactly 2 of the 28 kwargs this notebook passes
are rejected.

**The crash, from a real Colab run:**
```
TypeError: SFTConfig.__init__() got an unexpected keyword argument 'warmup_ratio'
```

**1. `max_seq_length` -> `max_length` (straight rename).** The probe found no field
containing "seq" anywhere in `SFTConfig`'s 133 fields; the only length-related fields are
`max_grad_norm` (gradient clipping), `max_steps` (training length), `length_column_name` (a
grouping column name), and `max_length` -- by elimination, `max_length` is the sequence-length
limit. Same value (`config["max_seq_len"]`), just the kwarg name changed. Fixed in both
places `SFTConfig` is constructed (see item 3).

**2. `warmup_ratio` -> computed `warmup_steps` (not a plain rename -- no field contains
"ratio" at all).** `warmup_steps` exists (default 0), so the ratio has to be converted to an
absolute step count. Done inside `build_trainer()` (cell 21), computed fresh **per call**
because the smoke test (`max_steps=100`) and the full run (~2,450 steps) are very different
lengths -- a single fixed `warmup_steps` would be wrong for one of them:
- `max_steps` given (smoke test): `total_steps = max_steps`.
- otherwise (full run): `effective_batch = per_device_train_batch_size *
  gradient_accumulation_steps`; `steps_per_epoch = ceil(len(train) / effective_batch)`;
  `total_steps = steps_per_epoch * resolved_num_train_epochs` (the override if one was
  passed to this call, else `config["num_train_epochs"]`).
- `warmup_steps = max(1, round(warmup_ratio * total_steps))` when `warmup_ratio > 0`, else 0.

`train/config.yaml` keeps `warmup_ratio` unchanged -- it stays the human-meaningful knob; the
conversion is entirely inside `build_trainer()`, with a comment explaining trl 1.13.0 dropped
`warmup_ratio` and why the conversion exists. `build_trainer()` now **prints the resolved
values before constructing `SFTConfig`** (e.g. `warmup: ratio 0.03 x 2450 total steps ->
warmup_steps=74`) -- a silently-computed number is exactly how a wrong one would survive an
entire run unnoticed, per the instruction.

**3. Notebook-wide search for every other `SFTConfig`/`TrainingArguments` construction, as
requested.** Grepped every cell's source for `SFTConfig(` and `TrainingArguments(`. Exactly
three hits:
- **Cell 14** (markdown, step 7's intro) -- two **prose mentions**
  (`SFTConfig(assistant_only_loss=True)`, `SFTConfig(completion_only_loss=True)`), not
  executable code.
- **Cell 21** (`build_trainer()`, step 10) -- the main constructor, fixed as described above.
- **Cell 36** (`evaluate_checkpoint_on_full_val()`, step 14's checkpoint-selection cell,
  flagged by name in the instruction as a known second instance) -- its `eval_only_config`
  had `max_seq_length` (renamed to `max_length`) but never passed `warmup_ratio` in the first
  place (it's eval-only, no training happens there), so only the rename was needed.

No other `SFTConfig`/`TrainingArguments` constructions exist anywhere else in the notebook.

**Could not be run or tested** -- needs a GPU, none available locally, per the instruction.
Verified only that the notebook is still valid JSON and every code cell (including both
edited ones) parses as valid Python via `ast.parse`.

**Files changed:** `notebooks/train_qlora.ipynb` only -- cell `bd4e2eff` (step 10 markdown,
documents the rename + conversion), cell `10d625b9` (`build_trainer()`), cell `4dfb2574`
(`evaluate_checkpoint_on_full_val()`). No other file touched, no dependency added.

**Verify with:**
```
.venv\Scripts\python.exe -c "import json, ast; nb = json.load(open('notebooks/train_qlora.ipynb', encoding='utf-8')); [ast.parse(''.join(l for l in ''.join(c['source']).splitlines(keepends=True) if not l.strip().startswith('!'))) for c in nb['cells'] if c['cell_type']=='code']; print('ok', len(nb['cells']), 'cells')"
```

Still did not run any training, locally or otherwise -- this fix is unverified until run on
Colab, same as every GPU-dependent part of this notebook. The open item from step-09 (cell
29's `generate_one()`, the one remaining live `apply_chat_template(tokenize=True)` call) is
still open -- not touched in this step.

**Next step: still the same Colab run this notebook has been waiting on since step-08 --
now covering the step-09 padding fix and this step-10 SFTConfig fix together, plus the still-open
`generate_one()` question from step-09.**

## step-11: fix smoke-test crash -- LoRA params loaded as bfloat16, fp16 GradScaler can't unscale them

**Edited directly on disk by the user, not by this session** -- reviewed and committed, not
re-edited. `git diff` confirmed the change is exactly three `dtype=COMPUTE_DTYPE` additions
(one in the model-loading cell, two in the best-checkpoint-selection cell's two
`AutoModelForCausalLM.from_pretrained` calls) plus their explanatory comments -- nothing
else. (A naive grep for the addition first looked like 4 hits, not 3 -- that was the
model-loading cell's **pre-existing, unrelated** `bnb_4bit_compute_dtype=COMPUTE_DTYPE` line
matching the same substring; confirmed by reading the full cell that only one genuinely new
`dtype=COMPUTE_DTYPE` kwarg was added there.) Notebook re-verified valid JSON, all code cells
parse via `ast.parse`.

**The crash, from a real T4 Colab run -- this time the smoke test itself, not a setup cell:**
```
NotImplementedError: "_amp_foreach_non_finite_check_and_unscale_cuda" not implemented for 'BFloat16'
```
Diagnosed by probing the loaded model directly: all 392 trainable LoRA parameters were
`torch.bfloat16`, because `AutoModelForCausalLM.from_pretrained` was given no `dtype`, so the
model's dtype fell back to Qwen2.5's own `config.json` (which declares `bfloat16`). On a T4,
`USE_BF16` is `False` (T4 is Turing, no bf16 support -- see step-07), so the trainer runs fp16
mixed precision instead, and fp16's `GradScaler` cannot unscale bfloat16 gradients --
unrelated to `bnb_4bit_compute_dtype`, which only controls the dtype the 4-bit base weights
are dequantized to inside matmuls, not the dtype of the trainable LoRA parameters that
actually carry gradients. Fixed by passing `dtype=COMPUTE_DTYPE` (the same runtime-detected
dtype from cell 1's GPU check -- bfloat16 on Ampere+, float16 on Turing) to all three
`AutoModelForCausalLM.from_pretrained` calls, so the LoRA parameters' dtype always matches
what the trainer's mixed-precision mode can actually handle. `dtype` (not `torch_dtype`,
deprecated in transformers 5.x) is the correct kwarg name in transformers 5.17.0.

**Confirmed on GPU: the new TRL-label-check cell (added in step-08, never executed before
this run) passed for real.** Batch of 4 rows: row 0 had 246 masked / 16 unmasked positions,
and all 4 rows' unmasked labels decoded to valid JSON with exactly the keys `queue`,
`priority`, `type`. This closes the one piece of step-08 that was flagged as
"not executable/testable locally" -- `SFTTrainer`'s actual labels, not our own
reconstruction, are now confirmed correct on the real target GPU. (The smoke test's crash
happened in the training step itself, which only triggers `GradScaler` during the backward
pass -- the label-check cell only pulls a batch and inspects it, so it ran and passed before
the crash.)

**Files changed:** `notebooks/train_qlora.ipynb` only (edited by the user directly, reviewed
and committed here). No other file touched, no dependency added.

**Verify with:**
```
.venv\Scripts\python.exe -c "import json, ast; nb = json.load(open('notebooks/train_qlora.ipynb', encoding='utf-8')); [ast.parse(''.join(l for l in ''.join(c['source']).splitlines(keepends=True) if not l.strip().startswith('!'))) for c in nb['cells'] if c['cell_type']=='code']; print('ok', len(nb['cells']), 'cells')"
```

Still did not run any training end-to-end -- the smoke test crashed on the bug this step
fixes; whether it now runs to completion is unverified until the next Colab attempt. The
still-open item from step-09 (`generate_one()`'s `apply_chat_template(tokenize=True)` call,
cell 29 -- used by both the smoke test's generated-outputs cell and the post-train preview)
remains untouched and unconfirmed either way.

**Next step: re-run the smoke test on Colab with this fix in place. If it completes, that
also newly exercises `generate_one()` for the first time (step 11's "5 generated outputs"
cell) -- worth watching specifically for the step-09 open item.**

## step-12: self-verifying dtype fix for the smoke-test crash, plus the real root cause found by reading trl's installed source

**Step-11's fix did not work.** The identical crash recurred on a real T4 Colab run:
```
NotImplementedError: "_amp_foreach_non_finite_check_and_unscale_cuda" not implemented for 'BFloat16'
```
raised from `torch/amp/grad_scaler.py`, `_unscale_grads_`, during `smoke_trainer.train()`.

**Measured, not assumed -- the dtype census taken from the live loaded model before any of
this step's fix:**
```
trainable (LoRA) params : {'torch.bfloat16': 392}     <-- all 392 of them
all params              : {'torch.float32': 58, 'torch.uint8': 196,
                           'torch.float16': 84, 'torch.bfloat16': 392}
model.config.dtype      : torch.bfloat16   (Qwen2.5's own config.json value)
model.dtype              : torch.float32
```
Environment this was measured on: `torch 2.11.0+cu128, transformers 5.17.0, trl 1.13.0,
peft 0.20.0, bitsandbytes 0.50.2`, GPU Tesla T4 (compute capability 7.5) -- so `USE_BF16` is
correctly `False`, `COMPUTE_DTYPE` is correctly `torch.float16`, and `SFTConfig` correctly
receives `bf16=False, fp16=True`.

**Two fixes already tried, both recorded here so a future session does not retry them:**
1. Adding `dtype=COMPUTE_DTYPE` to `AutoModelForCausalLM.from_pretrained` (step-11, already
   committed) -- **did not fix it**. The identical error still occurred.
2. Casting every bfloat16 parameter to float16 in place after loading, then rebuilding the
   trainer -- **inconclusive, not proof of failure**: not fully certain this was executed in
   the right cell order, so it doesn't rule the approach out on its own merits, only as
   attempted.

### The real root cause -- found by reading the actual installed source, not guessed

peft 0.20.0 and trl 1.13.0 are not installed in this local environment (no GPU here, so
they'd never previously been needed locally). Installed both, read-only, into this session's
scratchpad directory (`pip install --target <scratchpad>/pkg_inspect --no-deps peft==0.20.0
trl==1.13.0` -- exact versions matching the Colab probe; **not** added to the project's
`requirements.txt` or venv, purely for reading source files) to answer this properly instead
of speculating. Also downloaded the `bitsandbytes==0.50.2` wheel (Windows build, since that's
what resolves locally -- only used to confirm the platform-independent Python-level
`compute_dtype` attribute logic in `bitsandbytes/nn/modules.py`, not to run anything).

**Trace, in order:**
1. `peft/tuners/lora/layer.py`'s `update_layer()` creates LoRA A/B as plain
   `nn.Linear(self.in_features, r, bias=False)` -- no explicit `dtype`, so they start out
   whatever `torch.get_default_dtype()` is at that moment.
2. Immediately after, `_move_adapter_to_device_of_base_layer()` is supposed to cast them to
   match the base layer's dtype. For a bnb-quantized layer specifically,
   `peft/tuners/tuners_utils.py`'s `_get_base_layer_device_and_dtype()` does:
   ```python
   if hasattr(base_layer, "compute_dtype"):  # bnb Linear4bitLt
       dtype = base_layer.compute_dtype
   ```
   -- i.e. for bnb layers, the LoRA adapter's dtype is meant to track
   `bnb_4bit_compute_dtype`, not `dtype=` on `from_pretrained`. Confirmed via
   `transformers/integrations/bitsandbytes.py` (installed locally, matches the pinned
   5.17.0) that `bnb_4bit_compute_dtype` from `BitsAndBytesConfig` **is** threaded through
   correctly to each `bnb.nn.Linear4bit(..., compute_dtype=quantization_config.bnb_4bit_compute_dtype, ...)`
   at model-construction time -- so per this code path alone, LoRA params should end up
   `float16` on this T4 (`bnb_4bit_compute_dtype=COMPUTE_DTYPE=torch.float16`), not
   `bfloat16`. **This does not, by itself, explain the measured census** -- flagged
   explicitly rather than papered over, because the actual explanation is downstream:
2. **`trl/trainer/sft_trainer.py`, `SFTTrainer.__init__`, found verbatim:**
   ```python
   # When using QLoRA, the PEFT adapter weights are converted to bf16 to follow the
   # recommendations from the original paper (see https://huggingface.co/papers/2305.14314,
   # paragraph 3). Normally, this can be done by passing `autocast_adapter_dtype=False` to
   # `get_peft_model`, but this option is not yet supported for quantized models. See:
   # https://github.com/huggingface/peft/issues/2889
   if _is_quantized_model:
       for param in model.parameters():
           if param.requires_grad:
               param.data = param.data.to(torch.bfloat16)
   ```
   This is **unconditional** for any quantized model -- it does not check
   `args.bf16`/`args.fp16`, does not check the GPU's actual bf16 support, and runs whether or
   not the model was already a `PeftModel` passed in with no `peft_config` (this notebook's
   case: LoRA is attached in the model-loading cell, well before `SFTTrainer` is ever
   constructed). **This is the real, confirmed mechanism**: whatever dtype the LoRA
   parameters had right up until `SFTTrainer(...)` is constructed, trl overwrites them all to
   `bfloat16` at that point, by design (a QLoRA-paper recommendation), not a bug in trl. It
   is simply wrong for a T4, which has no bf16 support and therefore trains under fp16 mixed
   precision, whose `GradScaler` cannot unscale bfloat16 gradients -- exactly the crash.

This fully explains why step-11's `dtype=COMPUTE_DTYPE` fix did nothing: that kwarg affects
model construction, which happens *before* `SFTTrainer.__init__` runs its unconditional
cast -- anything set earlier is simply overwritten.

### The fix: self-verifying, applied twice, not a single-cause patch

Per the instruction, built to catch and correct this regardless of exactly where in the
pipeline it recurs, rather than patch only the one mechanism found above:

1. **Model-loading cell (step 9, `notebooks/train_qlora.ipynb`)**: after `get_peft_model(...)`,
   a new `normalize_bfloat16_params(model, target_dtype, label)` helper casts every
   `torch.bfloat16` parameter to `COMPUTE_DTYPE` (touches nothing else -- `float32` params
   are left alone, since `prepare_model_for_kbit_training` deliberately upcasts layer norms
   to fp32 for numerical stability, and `uint8` params are the packed 4-bit base weights),
   prints a `collections.Counter` before/after census, then hard-asserts no `bfloat16`
   parameter remains, **printing the offending parameter NAMES** (not just a count) if any
   do. Failure message: `STOP: do not train until this is fixed`.
2. **`build_trainer()` (step 10)**: after constructing `SFTTrainer(...)` (now assigned to a
   local `sft_trainer` instead of returned immediately), the **same** `normalize_bfloat16_params`
   runs again on `sft_trainer.model` -- the model the trainer actually holds -- right before
   `build_trainer` returns it. Also prints `sft_config.fp16`, `sft_config.bf16`, and
   `sft_trainer.accelerator.mixed_precision`, so an independently-bf16-selecting `accelerate`
   (a different bug the user flagged as a real possibility) would be visible too, distinct
   from this one.

   **Deliberate deviation from a literal reading of the instruction, flagged explicitly**:
   the instruction described step 10's check as a "census + named check" (i.e. assert-only,
   mirroring step 9's assert but without a second cast). Given the confirmed root cause above
   -- `SFTTrainer.__init__` unconditionally re-casts to bfloat16 for *any* quantized model,
   every single time -- an assert-only check at that point would fail on every run with no
   path to actually train. So step 10 calls the exact same cast-census-assert function used
   in step 9, a second time, rather than a bare assertion. This is flagged here rather than
   applied silently.
3. **`train/config.yaml`**: new `disable_mixed_precision` (default `false`), documented as a
   last-resort fallback, not the intended path. When `true`, `build_trainer` passes
   `bf16=False, fp16=False` for both the smoke test and the full run, so no `GradScaler` is
   ever constructed -- training runs in plain fp32 instead. Comment states plainly: slower,
   more memory, may OOM on a T4's 15GB VRAM.

**Files changed:** `notebooks/train_qlora.ipynb` (step 9's model-loading cell, step 9's
markdown, step 10's `build_trainer()`, step 10's markdown), `train/config.yaml`
(`disable_mixed_precision`). No other file touched. **No project dependency added** --
`peft`/`trl`/`bitsandbytes` were installed read-only into this session's scratchpad for
source inspection only, never into the project venv or `requirements.txt`.

**Could not be run or tested** -- needs a GPU and `bitsandbytes`, neither available locally.
Verified only that the notebook is still valid JSON and every code cell (including both
edited ones) parses as valid Python via `ast.parse`; verified `train/config.yaml` still
parses via `yaml.safe_load` with `disable_mixed_precision: false` present.

**Verify with:**
```
.venv\Scripts\python.exe -c "import json, ast; nb = json.load(open('notebooks/train_qlora.ipynb', encoding='utf-8')); [ast.parse(''.join(l for l in ''.join(c['source']).splitlines(keepends=True) if not l.strip().startswith('!'))) for c in nb['cells'] if c['cell_type']=='code']; print('ok', len(nb['cells']), 'cells')"
.venv\Scripts\python.exe -c "import yaml; c = yaml.safe_load(open('train/config.yaml')); print(c['disable_mixed_precision'])"
```

Still did not run any training end-to-end. Whether this fix actually gets the smoke test past
the point step-11 also failed at is unverified until the next Colab attempt. The step-09 open
item (`generate_one()`'s `apply_chat_template(tokenize=True)` call, cell 29) remains untouched.

**Next step: re-run the smoke test on Colab. Watch specifically for: (a) whether training
now proceeds past the point of the previous crash, (b) the printed dtype censuses at both
checkpoints matching expectations (all-float16 after normalization, zero bfloat16 offenders),
and (c) whether `accelerator.mixed_precision` printed in build_trainer ever disagrees with
`sft_config.bf16` -- which would mean the "different bug" the user flagged is real.**

## step-13: fix `evaluate_checkpoint_on_full_val` crash -- trl 1.13.0's SFTTrainer requires `train_dataset` even for eval-only use

**The bug, from a real Colab run of step 14 ("Select the best checkpoint using the FULL
validation set"):**
```
ValueError: `train_dataset` is required
```
raised from `trl` 1.13.0's `SFTTrainer.__init__`. `evaluate_checkpoint_on_full_val` (cell
`4dfb2574`) builds an eval-only `SFTTrainer` with `eval_dataset` but no `train_dataset` --
allowed by older trl, rejected by 1.13.0. **The fifth place in this notebook where code
written against an assumed trl/transformers API surface broke against the actually-installed
version** -- after `DataCollatorForCompletionOnlyLM` (step-08), `warmup_ratio` (step-10),
`max_seq_length` (step-10), the unconditional bfloat16 cast (step-12), and now this.

**Three changes requested, two applied, one already done:**
1. **Applied**: `train_dataset=raw_datasets["train"].select(range(1))` added to the
   `SFTTrainer(...)` construction inside `evaluate_checkpoint_on_full_val`, with a comment
   explaining why one row (not the full 13,070-row split): `.evaluate()` never iterates
   `train_dataset`, so one row satisfies trl's requirement without the cost of processing the
   full train split once per checkpoint (10 times over the run) for nothing.
2. **Already present, not re-added** -- flagged rather than silently duplicated: the
   instruction described this reload as still lacking `dtype=COMPUTE_DTYPE`, but on disk (per
   `git diff` and direct inspection) **both** `AutoModelForCausalLM.from_pretrained` calls in
   this cell (`base = ...` inside the function, and `best_base = ...` after the loop) already
   had `dtype=COMPUTE_DTYPE` -- added in step-11's user edit and unaffected since. Checked
   carefully before editing specifically to avoid adding a duplicate kwarg; nothing needed
   changing here.
3. **Applied**: `normalize_bfloat16_params(eval_trainer.model, COMPUTE_DTYPE, ...)` -- reusing
   the exact function from step-12, not a new one (the instruction named it
   `normalize_trainable_param_dtype`; the function actually defined in the notebook is
   `normalize_bfloat16_params` -- used the real name rather than introduce a call to a
   function that doesn't exist) -- called on `eval_trainer.model` right after constructing
   `SFTTrainer` and before `.evaluate()`, with a comment noting this is the same unconditional
   bfloat16 cast from step-12's trace, and that skipping it here would make eval_loss for this
   checkpoint incomparable to the others (computed at a different dtype).

### Notebook-wide search for other `SFTTrainer`/`SFTConfig` constructions, as requested -- not changed, only reported

Grepped every cell's source for `SFTTrainer(` and `SFTConfig(`. Exactly three hits, same as
every previous search of this kind in this notebook:
- **Cell 14** (markdown, step 7's intro) -- two prose mentions, not executable code.
- **Cell 21** (`build_trainer()`, step 10) -- already correct: always passes
  `train_dataset=raw_datasets["train"]` unconditionally (both the smoke test and the full run
  train for real), so it was never exposed to this specific bug; already has the dtype
  normalization from step-12.
- **Cell 36** (`evaluate_checkpoint_on_full_val`, step 14) -- fixed in this step.

**No other `SFTTrainer`/`SFTConfig` construction exists anywhere else in the notebook.**

### Tooling note: the notebook is now too large for `NotebookEdit`'s prerequisite `Read`

`Read` on `notebooks/train_qlora.ipynb` now fails outright (`File content (26022 tokens)
exceeds maximum allowed tokens (25000)`) regardless of `offset`/`limit` -- the `.ipynb`
renderer appears to ignore those parameters and always attempts to render the whole notebook.
Since `NotebookEdit` requires a successful `Read` of the file first, it is now **blocked** for
this notebook. Worked around by editing the cell directly: a small Python script
(`json.load`, replace the target cell's `"source"` by id, `json.dump` back) run via `Bash`,
bypassing both `Read` and `NotebookEdit` entirely. Diff verified afterward with `git diff` --
confirmed minimal and exactly as intended (only the two new blocks inside cell `4dfb2574`,
plus a trailing-newline normalization). **Future edits to this notebook will need the same
workaround, or the notebook will need to be split, until this is resolved.**

**Files changed:** `notebooks/train_qlora.ipynb` only (cell `4dfb2574`). No other file
touched, no dependency added.

**Could not be run or tested** -- needs a GPU, none available locally, per the instruction.
Verified only that the notebook is still valid JSON and every code cell parses as valid Python
via `ast.parse`.

**Verify with:**
```
.venv\Scripts\python.exe -c "import json, ast; nb = json.load(open('notebooks/train_qlora.ipynb', encoding='utf-8')); [ast.parse(''.join(l for l in ''.join(c['source']).splitlines(keepends=True) if not l.strip().startswith('!'))) for c in nb['cells'] if c['cell_type']=='code']; print('ok', len(nb['cells']), 'cells')"
```

Still did not run any training end-to-end. Whether step 14 now runs to completion -- and
whether the per-checkpoint `eval_loss` values it prints are sane -- is unverified until the
next Colab attempt (this step requires the full training run, step 13, to have already
produced at least one checkpoint, which itself depends on step-12's fix working).

**Next step: re-run on Colab, now covering the full pipeline through step 14. Given the
five-in-a-row pattern of assumed-API-surface breaks, treat any further crash in this notebook
as likely to be the same class of bug (an API this notebook was written against no longer
matching the actually-installed trl/transformers/peft) before assuming anything else.**

## step-14: make checkpoint selection resumable, and add a no-training recovery path after a disconnect

**Not an API break this time -- the same durability bug already fixed once, left exposed a
second place.** Step 14's checkpoint-selection loop evaluated 9 of its 10 checkpoints on the
full validation set (~40 minutes on a T4), Colab disconnected during the 10th, and re-running
started from checkpoint-250 again -- all 9 already-scored checkpoints' `eval_loss` values were
gone, because `full_val_losses` was a plain in-memory `dict`, never written anywhere. This is
exactly the "work not written to durable storage does not survive a disconnect" failure
step-08 already fixed for the training loop itself (`resume_from_checkpoint`) -- just left
open in this second loop.

### 1. Resumable cache, written inside the loop -- not after it

`notebooks/train_qlora.ipynb`'s checkpoint-selection cell (`evaluate_checkpoint_on_full_val`
+ the scoring loop) now caches each checkpoint's full-val loss to
`f"{full_output_dir}/full_val_losses.json"` (on Drive, since `full_output_dir` lives under
`REPO_ROOT` which defaults to Drive as of step-08) via `json.dump(...)` **immediately after
that checkpoint is scored, inside the loop body** -- not collected and written once after the
loop. On entry, the cache is loaded if present and any checkpoint already in it is skipped,
printing the cached value (`SKIPPED -- cached FULL-val eval_loss = ...`) so it's visible which
ones were reused. The final best-checkpoint selection was changed from
`min(full_val_losses, key=full_val_losses.get)` to
`min(checkpoint_dirs, key=lambda cd: full_val_losses[cd])` -- restricts the comparison to
checkpoints that actually exist right now, so a stale cache entry for a checkpoint that no
longer exists (or came from a different `output_dir`) can't silently win.

**Commented explicitly against regression, per the instruction**: the write sits inside the
`for ckpt_dir in checkpoint_dirs:` loop body with a comment stating plainly that a future edit
moving the `json.dump` call to after the loop "to tidy it up" would silently reintroduce this
exact bug -- the loop-body placement is the fix, not an implementation detail to be refactored
away later.

### 2. Staleness warning at cache-load time

When an existing `full_val_losses.json` is loaded, a printed `WARNING` states plainly that the
cached numbers are only valid for the exact version of `evaluate_checkpoint_on_full_val()`
that produced them -- if that function changes (dtype normalization, eval batch size,
`max_length`, anything), the cache file must be deleted first, or a re-run would silently mix
results computed by two different code versions. Framed explicitly as the same class of
mistake as the two prior stale-file incidents in this project: `data/README.md` regenerated
by hand going stale against its own generator (step-02 corrections), and a stale
`train/config.yaml` sitting on Drive (step-08's `REPO_ROOT` default-to-Drive fix exists partly
because of exactly this risk).

### 3. Recovery cell: rebuild `trainer`/`full_output_dir` after a disconnect, without re-training

New markdown + code cell pair, inserted between step 13's loss-curve cell and step 14's
markdown: `full_output_dir = f"{REPO_ROOT}/{config['output_dir']}"` and
`trainer = build_trainer(output_dir=full_output_dir, eval_dataset=eval_subsample)` -- no
`.train()` call. `trainer`/`full_output_dir` only exist in memory if the full-training cell
ran in *this* session; after a disconnect they don't, even though the checkpoints themselves
survived on Drive, and re-running training from scratch to get two variables back would waste
the very checkpoints step-08's resumability exists to protect. Step 14's markdown was updated
to say explicitly: run the recovery cell instead of re-running step 13's training cell, if
`trainer`/`full_output_dir` are missing. The recovery cell's own markdown notes it still
requires step 9 (model loading + LoRA attach) to have run this session -- that step is fast
(a few minutes) and, by design (see step-08's `REPO_ROOT` reasoning), always reloads the base
model fresh from the Hub rather than trying to cache it, so it isn't itself a candidate for
this kind of resumability.

### Tooling note: still working around `NotebookEdit`/`Read` being blocked on this notebook

Same constraint as step-13: `Read` on `notebooks/train_qlora.ipynb` still fails outright
(exceeds the 25,000-token limit, `offset`/`limit` have no effect for `.ipynb` rendering), so
`NotebookEdit` remains unusable. All of this step's edits (two cell insertions, one markdown
rewrite, one code cell rewrite) were made with a Python script
(`json.load` -> locate cells by `id` -> mutate `"source"` / `cells.insert(...)` -> `json.dump`
back) run via `Bash`, the same workaround as step-13. Verified afterward with `git diff` --
confirmed the change is exactly the intended edits, nothing else touched, all cell `id`s
remain unique.

**Files changed:** `notebooks/train_qlora.ipynb` only -- new recovery markdown+code cell pair,
step 14's markdown (`8f4cfd63`), step 14's code cell (`4dfb2574`). No other file touched, no
dependency added.

**Could not be run or tested** -- needs a GPU, none available locally, per the instruction.
Verified only that the notebook is still valid JSON (43 cells now, all unique ids) and every
code cell parses as valid Python via `ast.parse`.

**Verify with:**
```
.venv\Scripts\python.exe -c "import json, ast; nb = json.load(open('notebooks/train_qlora.ipynb', encoding='utf-8')); [ast.parse(''.join(l for l in ''.join(c['source']).splitlines(keepends=True) if not l.strip().startswith('!'))) for c in nb['cells'] if c['cell_type']=='code']; print('ok', len(nb['cells']), 'cells')"
```

Still did not run any training end-to-end. Whether the resumable cache and the recovery cell
actually behave as designed is unverified until the next Colab attempt -- specifically worth
watching: that the cache file appears under `full_output_dir` on Drive after the first
checkpoint is scored (not just at the end), that a deliberate re-run correctly skips cached
checkpoints, and that the recovery cell alone (without re-running step 13) is enough to get
step 14 running again.

**Next step: re-run on Colab. If a disconnect happens again during step 14, this is the first
real test of whether the resumable cache actually saves the already-scored work -- report
back whether `full_val_losses.json` existed on Drive and had the expected partial contents
when the session reconnects.**

## step-15: third predictor -- the fine-tuned QLoRA adapter, scored on the same harness

**What was built:** `src/ticket_router/predictors/adapter_predictor.py`, the third predictor
`evaluate.py` can score, alongside `api_predictor.py` (zero-shot/few-shot GPT-4o-mini) and
`tfidf_baseline.py`. The adapter itself is done and on the Hub:
`Omar-Mohsen22/ticket-router-qwen2.5-1.5b-qlora` (private, base
`Qwen/Qwen2.5-1.5B-Instruct`, LoRA r=16/alpha=32, pushed from checkpoint-1500 by step 15 of the
notebook). This step writes the code to score it, not run it -- see "Could not be run" below.

### Interface found, before writing anything (as instructed)

Read `api_predictor.py`, `tfidf_baseline.py`, and `evaluate.py` first. The shared interface is
the predictions JSONL row `evaluate.py`'s `load_predictions()` actually consumes:
```
{"id": <str>, "queue"/"priority"/"type": <str|null>,
 "latency_ms": <float>, "input_tokens": <int>, "output_tokens": <int>, "cost_usd": <float|null>}
```
`id` must match a gold-split id (missing/non-string ids are dropped, counted separately, and
never scored). `queue`/`priority`/`type` are re-validated by `evaluate.py` itself via
`TicketLabels(**row)` -- a `ValidationError` (missing, `null`, or a value outside the allowed
set) is how "invalid" is signaled; there is no separate flag field. The four numeric fields
are recorded independent of label validity. An optional `"error"` field
(`api_predictor.py`'s convention) is written for diagnostics but never read by `evaluate.py`.
Scoring is always a separate step -- neither existing predictor calls `evaluate.py` itself.
`api_predictor.py`'s caching pattern: one file per ticket under `.cache/<predictor>/`, keyed
by a hash of the request-determining inputs + ticket id, output JSONL opened once and
written+flushed as each row/batch completes. `tfidf_baseline.py`'s convention for
non-per-request work: when generation happens in a batch, `latency_ms` is the batch's total
time divided evenly across its rows, documented as batch-averaged, not individually measured.
**Nothing in this interface was changed; `evaluate.py` was not touched.**

### The six requirements, and how each was met

1. **4-bit loading + adapter attachment, config-driven, not hardcoded.** `base_model` and
   `hub_model_id` (already `Omar-Mohsen22/ticket-router-qwen2.5-1.5b-qlora`) and the
   `quantization` block (`load_in_4bit`, `bnb_4bit_quant_type`, `bnb_4bit_use_double_quant`)
   are all **reused directly from `train/config.yaml`** -- the same file
   `notebooks/train_qlora.ipynb` reads -- rather than duplicated into a second config, so
   there is exactly one place any of it can go stale. `bnb_4bit_compute_dtype` is
   deliberately still NOT in config, matching `train/config.yaml`'s existing reasoning
   exactly: `pick_compute_dtype()` reproduces the notebook's own cell-1 GPU-capability check
   (bfloat16 on compute capability major>=8, float16 otherwise) at runtime, since which GPU
   this predictor runs on isn't decided any more than the notebook's was.
2. **Prompt rendered exactly like training.** `render_prompt()` builds
   `[{"role": "system", "content": system_message}, {"role": "user", "content": ticket_text}]`
   using `build_system_message()` **imported directly from `make_sft_dataset.py`** (not
   re-typed a third time -- `api_predictor.py` and `make_sft_dataset.py` each already have
   their own copy of a similar builder; importing here stops that from becoming a third,
   independently-driftable copy for the one predictor where prompt-exactness is the entire
   point). Rendered via `apply_chat_template(tokenize=False, add_generation_prompt=True)`,
   then tokenized separately with `add_special_tokens=False` -- the exact pattern
   `notebooks/train_qlora.ipynb` settled on after two real, reproducible bugs from
   `apply_chat_template(tokenize=True)` (PROGRESS.md's step-09 and step-13 entries), used
   here for the identical reason, not as a style choice.
3. **Deterministic decoding.** `do_sample=False` in the one `model.generate()` call.
4. **Batched generation, left padding, config-driven batch size.**
   `tokenizer.padding_side = "left"` set once after loading (inference-only script, never
   trains, so no conflict with training's right-padding). `batch_size` and `max_new_tokens`
   are new `train/config.yaml` keys under `inference:` -- not CLI flags, per the instruction
   ("a config value") -- so the batch size is tunable without touching code once the actual
   GPU is known.
5. **Streamed, resumable output.** Per-ticket disk cache under `.cache/adapter_predictor/`,
   keyed by a hash of `(adapter_repo_id, exact rendered prompt text, ticket_id)` -- mirrors
   `api_predictor.py`'s `call_with_cache` pattern exactly, per the instruction. The output
   JSONL is opened once and every batch's rows are written and flushed immediately after that
   batch completes (not buffered to the end), so a crash loses at most the batch in flight,
   and a re-run replays every already-cached ticket for free rather than re-generating.
6. **Invalid outputs recorded, never retried or repaired.** `parse_and_validate()` gets
   exactly one `json.loads()` + one `TicketLabels(**parsed)` attempt per ticket -- unlike
   `api_predictor.py`'s `MAX_CONTENT_RETRIES`, there is no retry loop here at all, per the
   instruction (the invalid-output rate is a reported harness metric; repairing it here would
   falsify what a real deployment's rate would actually be). Catches `(TypeError,
   ValidationError)`, not just `ValidationError` -- `TypeError` covers valid-JSON-but-not-an-
   object output (e.g. the model emitting a bare string or a list), the same edge case
   `api_predictor.py`'s own `except` clause already guards against; missed on the first pass
   here and added after re-reading `api_predictor.py`'s exact exception tuple a second time.

### Two other things fixed on review, before committing

- The same `TypeError` gap above.
- An unused `TARGET_FIELDS` module constant (declared to match the other two predictors'
  style, never actually referenced) -- wired into both the per-ticket `result` dict
  construction and the output-row construction instead of leaving it as dead code.

### New dependencies -- named and justified, per the project's rule

`requirements.txt`: `pyyaml==6.0.3` (already present transitively via
`huggingface_hub`/`transformers`, now a direct, declared dependency since this script reads
`train/config.yaml` itself), `peft==0.20.0` and `bitsandbytes==0.50.2` (pinned to the exact
versions the adapter was trained with on Colab, to avoid a version-mismatch loading
difference), `torch` (deliberately unpinned -- identical reasoning to
`notebooks/train_qlora.ipynb`'s install cell: the correct build is tied to whatever GPU/CUDA
this actually ends up running on, not this repo's business to guess). `.env.example`: new
`HF_TOKEN` entry -- the adapter repo is private, so a token is required; the script `STOP`s
with a clear message if it's unset, same pattern as `api_predictor.py`'s
`OPENAI_API_KEY`/`OPENAI_MODEL` check.

**Files changed:** `src/ticket_router/predictors/adapter_predictor.py` (new),
`train/config.yaml` (new `inference:` section: `batch_size`, `max_new_tokens`),
`requirements.txt` (4 new lines, see above), `.env.example` (`HF_TOKEN`). `evaluate.py` was
**not** touched, per the instruction.

**Could not be run or tested** -- needs a CUDA GPU with bitsandbytes 4-bit support, neither
available locally (confirmed: `torch`/`peft`/`bitsandbytes` are not installed in this local
venv). Verified what could actually be checked without one: `ast.parse` and `py_compile` both
pass; every import that doesn't require the GPU stack was independently confirmed to resolve
correctly in this venv (`build_system_message` importable and callable, `TicketLabels`
importable, `yaml`/`dotenv`/`pandas` all present) by importing the module directly and
confirming it fails at exactly `import torch` and nowhere earlier -- not a general assumption
that the rest is fine, an actual check of where the import chain breaks. `train/config.yaml`
re-parses with the new `inference:` section present and correctly typed.

**Verify with:**
```
.venv\Scripts\python.exe -c "import ast; ast.parse(open('src/ticket_router/predictors/adapter_predictor.py', encoding='utf-8').read()); print('syntax OK')"
.venv\Scripts\python.exe -m py_compile src\ticket_router\predictors\adapter_predictor.py
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'src'); import ticket_router.predictors.adapter_predictor" # expected: ModuleNotFoundError: No module named 'torch', nothing earlier
.venv\Scripts\python.exe -c "import yaml; c = yaml.safe_load(open('train/config.yaml')); print(c['inference'])"
```

Not run end to end. Once a GPU is available: `pip install -r requirements.txt` (now pulls
torch/peft/bitsandbytes too), set `HF_TOKEN` in `.env`, then
`python src/ticket_router/predictors/adapter_predictor.py --split test --run-name adapter-qlora`
followed by the same `evaluate.py --predictions results/adapter-qlora.predictions.jsonl
--split test --run-name adapter-qlora` used for the other two runs, to get it into
`results/comparison.md` alongside them.

**Next step: run `adapter_predictor.py` on a real GPU, then `evaluate.py` on its output, and
compare against `api-gpt4o-mini-full-test` and `tfidf-baseline` in `results/comparison.md` --
the comparison this whole fine-tuning effort (steps 06-15) was building toward.**

## step-16: settle how cost and latency are reported, BEFORE the fine-tuned predictor produces any numbers

**Why now, specifically:** requested and done before `adapter_predictor.py` (step-15) has ever
been run, on purpose. The predictions schema's `cost_usd`/`latency_ms` would let the adapter's
results table row read `cost_usd=0.0`, exactly like TF-IDF's row -- which is false. TF-IDF
trains in seconds on a CPU and serves on a CPU; the adapter took 3h21m (3.35 hours) of T4 GPU
time to train and needs a GPU to serve. Deciding the categories and wording for this *before*
seeing whether the adapter wins or loses on accuracy is the whole point -- deciding after would
let the framing get quietly shaped by the result.

### The design: run-level metadata, not a schema change

Per the instruction, `evaluate.py`'s per-row predictions schema (`id`, `queue`, `priority`,
`type`, `latency_ms`, `input_tokens`, `output_tokens`, `cost_usd`) is **untouched** -- nothing
about it changed. Instead, new **run-level** metadata:

- `cost_basis`: one of `api-per-token`, `cpu-local`, `gpu-local` (the three names the
  instruction proposed -- judged clear enough to keep as-is, no reason to invent new ones).
- `hardware`: the actual device a run happened on -- `torch.cuda.get_device_name(0)` for the
  adapter (read at runtime, never hardcoded), `"CPU"` for TF-IDF/random-baseline, `"OpenAI
  API"` for the API predictor.
- `training_cost`: `{"gpu_hours": <float>, "note": <str>}` -- `3.35` for the adapter (with a
  note stating plainly the $0 training cost is because Colab's free tier absorbed it, not
  because training was free), `0.0` with an explanatory note for everything else (TF-IDF's
  note states its fit is seconds of CPU time, not GPU-hours -- explicitly not comparable).

New shared module `src/ticket_router/run_meta.py`: `write_run_meta(run_name, cost_basis,
hardware, training_cost)` writes `results/<run_name>.run_meta.json`; `COST_BASIS_DESCRIPTIONS`
is the one place the three categories' meanings are written in English, read back by
`report.py` so the table's footnote text can never drift from what the code actually enforces.
Each predictor calls it once, right after producing its predictions, using whatever it
actually knows about its own run:
- `predict_random_baseline.py`, `predictors/tfidf_baseline.py`: `cost_basis="cpu-local"`,
  `hardware="CPU"`. TF-IDF's `training_cost.note` reports the REAL measured fit time
  (`total_fit_s` across the 3 classifiers, now tracked and printed) rather than a vague "a few
  seconds" claim.
- `predictors/api_predictor.py`: `cost_basis="api-per-token"`, `hardware="OpenAI API"`, for
  whatever `--run-name` that invocation used (covers all variants: zero-shot, coverage,
  coverage-priority, coverage-median).
- `predictors/adapter_predictor.py`: `cost_basis="gpu-local"`, `hardware` read live via
  `torch.cuda.get_device_name(0)` (the *inference*-time GPU, which need not be the same GPU
  the adapter was trained on), `training_cost` from two new module constants
  (`TRAINING_GPU_HOURS = 3.35`, `TRAINING_HARDWARE = "Tesla T4 (Google Colab, free tier)"`) --
  a fixed historical fact about this specific adapter, not an inference knob, so it lives as a
  commented constant in the predictor rather than in `train/config.yaml`'s `inference:`
  section.

`evaluate.py`'s `save_result()` (the only thing that writes `results/results.json`) gained one
new step: `load_run_meta(run_name)` looks for that sidecar file and merges its contents in
under a new `"run_meta"` key -- falling back to an explicit `{"cost_basis": "unknown", ...}`
with a printed `WARNING` (not a silent omission) if a predictor didn't write one. `evaluate.py`
does not import `torch` or gain any GPU dependency -- hardware detection stays exactly where
the real execution context is known (inside each predictor), not duplicated into the harness.

### report.py: footnotes generated from results.json, nothing hand-typed

`build_comparison()` now tags every `total_cost_usd`/`cost_per_1000_usd` cell that is 0 with
`[cost_basis]` inline (`format_cost_cell`), and every `lat_p50_ms`/`lat_p95_ms` cell with
`[hardware]` inline (`format_latency_cell`) -- directly in the cell, not only in a separate
legend that could be read apart from the number. A `## Notes` section is appended below the
table: a glossary of exactly the `cost_basis` values actually used in this run of the report
(descriptions imported from `run_meta.COST_BASIS_DESCRIPTIONS`, not retyped), and a
`training_cost` breakdown listing every run with `gpu_hours > 0` by name. All of this is
generated from `results.json` on every run of `report.py`, exactly as before -- no markdown
was hand-written into `comparison.md` or `README.md`.

### A real, unrelated bug found and NOT silently fixed or hidden

Verifying the mechanism end-to-end (by actually re-running `predict_random_baseline.py` and
`predictors/tfidf_baseline.py`, then re-scoring both plus backfilling `run_meta` for the 5
already-existing API runs) surfaced something that has nothing to do with this step's actual
task: re-scoring **`random-baseline`** and **`api-gpt4o-mini-50`** against the *current* local
`data/processed/test.parquet` produced **substantially different metrics** than what's
currently committed in `results.json` (random-baseline's queue macro-F1 shifted from 0.1110 to
0.0913; `api-gpt4o-mini-50`'s `invalid_rate` jumped from 0% to 96%, `n_valid` from 50 to 2).
The other 5 runs (`api-gpt4o-mini-full-test` and the 3 fewshot variants, all full-split,
scored by id) came back byte-identical; only the two order/position-sensitive ones drifted --
`predict_random_baseline.py` assigns its RNG draws to rows by **position**
(`sampled[field][i]` to `target["id"][i]`), and `api-gpt4o-mini-50`'s original run used
`--limit 50`, i.e. `gold.head(50)`, also position-based. This is consistent with the local
`data/processed/test.parquet` (gitignored, not tracked -- so this checkout's copy is not
provably the same file that produced the committed numbers) having a **different row order**
than whatever produced the currently-committed values, while its **row-to-id membership**
stays intact (id-keyed, full-split runs were unaffected). **Not investigated further and not
fixed here** -- out of scope for this step, and CLAUDE.md's "stop and report a wrong
assumption rather than invent a workaround" applies directly: this is a real, separate,
pre-existing data-reproducibility question (is `make_dataset.py`'s shuffle actually
deterministic across regenerations? has `test.parquet` simply never been regenerated to match
some later fix?) that deserves its own investigation, not a fix folded into an unrelated task.

**Recovered safely, not left broken:** `git checkout -- results/random-baseline.predictions.jsonl
results/tfidf-baseline.predictions.jsonl results/results.json` reverted every numeric value
back to the committed baseline, then `run_meta` was merged into all 7 entries via a pure
JSON-key-insertion script (not `evaluate.py`'s recompute path) -- verified programmatically
afterward that every field except the new `"run_meta"` key is byte-identical, per run, to what
was already committed. No historical metric was overwritten by this step.

**Files changed:** `src/ticket_router/run_meta.py` (new), `src/ticket_router/evaluate.py`
(`load_run_meta` + `save_result` wiring), `src/ticket_router/report.py` (footnote rendering),
`src/ticket_router/predict_random_baseline.py`, `src/ticket_router/predictors/tfidf_baseline.py`,
`src/ticket_router/predictors/api_predictor.py`, `src/ticket_router/predictors/adapter_predictor.py`
(each now calls `write_run_meta`), `results/results.json` (7 `run_meta` keys added, nothing
else changed), `results/comparison.md` + `README.md` (regenerated via `report.py`), 7 new
`results/<run-name>.run_meta.json` sidecar files. No dependency added.

**Verified for real, not just syntax-checked:** `predict_random_baseline.py` and
`predictors/tfidf_baseline.py` were actually run, followed by `evaluate.py` and `report.py` --
confirming `write_run_meta` -> `evaluate.py`'s pickup -> `report.py`'s footnote rendering work
end to end (the rendered table and `## Notes` section shown above are real output, not a mockup).
`pytest -q`: 11/11 still passing. `adapter_predictor.py`'s own `write_run_meta` call is
untested (same GPU constraint as step-15 -- not run).

**Verify with:**
```
.venv\Scripts\python.exe src\ticket_router\predict_random_baseline.py
.venv\Scripts\python.exe src\ticket_router\evaluate.py --predictions results\random-baseline.predictions.jsonl --split test --run-name random-baseline
.venv\Scripts\python.exe src\ticket_router\report.py
.venv\Scripts\python.exe -m pytest -q
```

**Next step: still run `adapter_predictor.py` on a real GPU (step-15), then `evaluate.py` --
its `run_meta` will be picked up automatically and the table will render `[gpu-local]`/
`[<real GPU name>]` and a training-cost line for it, with no further code changes needed.
Separately, worth investigating on its own: why `data/processed/test.parquet`'s local copy
doesn't reproduce the row order that produced the currently-committed
`random-baseline`/`api-gpt4o-mini-50` numbers.**

## step-17: close the step-16 investigation -- test both hypotheses, test drift directly, add a hash check that fails loudly

**Hypothesis A (api-gpt4o-mini-50), tested, precisely confirmed with a caveat.**
`results/api-gpt4o-mini-50.predictions.jsonl` has exactly 50 rows (`wc -l`). Re-scoring it
against the FULL 1,633-row test split (no `--limit`, using `evaluate.py`'s own `load_predictions`/
`evaluate()` directly so nothing was written to `results.json`) gives `n_valid=50,
invalid_rate=0.9693815064298836` -- matching `1 - 50/1633 = 0.9693815064298836` to full float
precision. **But** that is not literally what produced last turn's reported ~96%: that run
correctly passed `--limit 50`. Checked precisely instead: all 50 of the file's ids are still
present *somewhere* in the current full `test.parquet` (`len(pred_ids & set(gold["id"])) == 50`
-- membership intact), but only **2 of them** fall within the CURRENT first-50 rows by position
(`len(pred_ids & current_first_50_ids) == 2`). Same underlying mechanism the hypothesis points
at (a position-based comparison against a since-reordered split), just via `--limit`'s
`gold.head(n)` rather than a missing `--limit`.

**Hypothesis B (random-baseline), tested.** `src/ticket_router/predict_random_baseline.py` IS
seeded (`SEED = 42`, `rng = np.random.default_rng(SEED)`) -- the draw sequence itself is fully
deterministic given the same `train.parquet` content. But the assignment is **positional**:
`sampled[field][i]` -> `target["id"][i]`, i.e. the i-th random draw is handed to whatever id
sits at position i of `test.parquet` *at the moment the script runs*. Seeded is not sufficient
for reproducibility here -- the row order of `test.parquet` also has to match, and nothing
checked that it did.

**The drift question, tested directly, as a fact:** `make_dataset.py`'s `main()` was run fresh
just now with every output path monkeypatched to a scratch directory (`OUTPUT_DIR`,
`LABEL_MAP_PATH`, `DATA_README_PATH` -- all three, since `LABEL_MAP_PATH` is bound from
`OUTPUT_DIR` at import time and does not follow a later override, and `DATA_README_PATH` is
the real, git-tracked `data/README.md` that would otherwise have been silently overwritten).
Real `data/raw/`'s CSV was read (unchanged, read-only). Compared the regenerated `test.parquet`
against the currently-committed one on disk:
```
committed test.parquet:   1633 rows
regenerated test.parquet: 1633 rows
same COUNT: True
same SET (membership, order-independent): True
same ORDERED SEQUENCE (id-for-id, position-for-position): True
```
**Fact: `make_dataset.py` is fully reproducible on this machine, right now.** There is no
ongoing/current drift in `test.parquet` -- regenerating it from the checked-in raw CSV
reproduces the exact current file, order included.

**So what actually explains the two mismatches?** Not instability in the current pipeline --
`random-baseline.predictions.jsonl` and `api-gpt4o-mini-50.predictions.jsonl` are simply
**stale artifacts that predate step-04's shuffle fix** to `test.parquet`'s row order (see
PROGRESS.md's step-04 entry: the shuffle was added specifically because a `--limit 50` run,
before the fix, drew 50 rows that were "100% one queue class" -- which matches
`api-gpt4o-mini-50`'s committed `results.json` entry exactly: its `queue.per_class` lists only
`"Billing and Payments"`, support 50). Both files' content is genuine and their OWN committed
metrics remain internally valid for the file as it exists -- they were simply never
regenerated against the corrected, later row order, and nothing before this step could have
told anyone that.

### The fix: evaluate.py now hashes and checks the gold split, and fails loudly on a mismatch

`src/ticket_router/evaluate.py`:
- `compute_gold_hash(ids)`: sha256 of the gold split's **ordered** id sequence (`"\n".join`,
  not a sorted set) -- order has to be part of the hash, since that is exactly what broke
  `random-baseline` and the `--limit 50` run above; a hash of just the id *set* would have
  missed both.
- Every `results.json` entry now carries a `"gold_split"` key:
  `{"split", "limit", "n", "id_sequence_sha256"}`.
- `check_gold_hash_consistency(all_results, split, limit, gold_hash, run_name)`: before saving,
  compares this run's hash against every *other* run already recorded for the identical
  `(split, limit)` pair. On a mismatch: prints both hashes and a clear explanation, then
  `raise SystemExit(1)` -- **no `results.json` write happens**. Deliberately scoped to
  `(split, limit)`, not just `split`, so a legitimate `--limit 50` smoke test is never flagged
  against a full-split run (they were never claimed to be comparable). Re-running the *same*
  `run_name` (overwriting its own prior entry) is always allowed regardless of its own earlier
  hash -- only *other* run names sharing the same split/limit are compared against.
- `main()` computes the hash and runs the check **before** calling `evaluate()` -- fails fast,
  before spending any time computing metrics that would just get thrown away.

**Verified without touching the real `results.json`, on purpose** (after last step's lesson):
wrote an isolated test script exercising `compute_gold_hash`/`check_gold_hash_consistency`
directly against fabricated `all_results` dicts -- confirmed: (1) matching hash under the same
split/limit passes silently, (2) a real mismatch under the same split/limit raises
`SystemExit` with a clear message naming both hashes, (3) a mismatch under a *different* limit
does **not** raise (correctly not comparable groups), (4) re-scoring the same `run_name` never
raises regardless of its own prior hash, (5) the bootstrap case (no prior entries at all) never
raises. `pytest -q`: still 11/11. `git status` after all of this shows only
`src/ticket_router/evaluate.py` changed -- `results.json` and every predictions file are
untouched, per the instruction ("report all of this before changing anything beyond the hash
check").

### Recommendation on committing the split files instead of gitignoring them (not acted on)

**Recommend: commit `data/processed/test.parquet` and `data/processed/val.parquet`. Leave
`train.parquet` gitignored.** Reasoning:

- This is the *same* argument that already applied to `label_map.json` (step-02 correction):
  "the label contract... schema.py, the evaluation harness, and the CI tests all depend on its
  exact contents, and CI does not rebuild the dataset." `test.parquet` is that argument's
  natural extension -- it is not just something code depends on, it is the literal denominator
  of every number in `results/comparison.md` and `README.md`. If it drifts, every published
  comparison becomes silently unverifiable by anyone who cannot reproduce the exact historical
  file -- which, per the previous section, is provably possible today but is not a standing
  guarantee (see below).
- Small: `test.parquet` is 617 KB; `val.parquet` (1,635 rows, almost the same size) is
  comparable. Trivial by git's standards, nowhere near the SFT JSONL files (`train.jsonl`,
  called out as "sizeable" at 16MB in step-06 and kept gitignored partly for that reason).
- The hash check above only protects against drift being detected *after the fact*, by
  comparing against sibling entries already in `results.json` -- it cannot protect a single
  fresh clone with an empty `results.json` from silently producing a self-consistent but
  historically-incomparable set of numbers from scratch. Committing `test.parquet` removes the
  ambiguity at the root instead of only detecting its symptom.
- Today's reproducibility is real (just proven) but is contingent on: `requirements.txt`'s
  exact pins (`pandas==3.0.5`, `numpy==2.5.3`) never being bumped without re-verifying this;
  and, more fundamentally, on `data/raw/`'s source CSV -- ALSO gitignored, re-downloaded fresh
  from the Hugging Face Hub by `inspect_data.py` -- never changing upstream. Neither is
  guaranteed to stay true indefinitely, and nothing in this project would notice if either one
  quietly did, on a machine with no prior `results.json` to hash-check against.
- `train.parquet` is a closer call and I'm **not** recommending it: at ~4.9 MB (8x `test`'s
  size) it is meaningfully bigger, and its exact reproducibility is not load-bearing for
  *comparing already-published results* the way test/val are -- it only matters for
  reproducing *training itself* (TF-IDF's fit, the adapter's fine-tuning), a real but
  lower-stakes and differently-scoped concern than "can last month's published table still be
  verified."

This is a recommendation only -- `.gitignore` was not touched, and neither `test.parquet` nor
`val.parquet` was `git add`ed.

**Files changed:** `src/ticket_router/evaluate.py` only. No other file touched (confirmed via
`git status`), no dependency added (`hashlib` is stdlib).

**Verify with:**
```
.venv\Scripts\python.exe -c "import ast; ast.parse(open('src/ticket_router/evaluate.py', encoding='utf-8').read()); print('syntax OK')"
.venv\Scripts\python.exe -m pytest -q
```
The isolated hash-check test above was a one-off scratch script, not committed (mirrors the
project's existing convention of not committing ad hoc diagnostic scripts -- e.g. step-08's
30/30-vs-30/30 comparison).

Deliberately did NOT re-run `evaluate.py` against the real `results.json` in this step (that
would add `"gold_split"` to the 7 existing entries, bootstrapping them against today's data --
plausible and safe given the drift finding above, but the instruction was explicit: report
first, change nothing beyond the hash check itself).

**Next step: decide on the `test.parquet`/`val.parquet` gitignore recommendation above. Once
settled, `evaluate.py` can be re-run for the 7 existing entries to backfill their `gold_split`
hashes (a pure bootstrap -- there is nothing to compare the first backfilled entry against),
and then `adapter_predictor.py` still needs a real GPU run (step-15).**

## step-18: three decisions from the step-17 report -- commit the split files, mark the known-bad run superseded, make the random baseline order-independent

**Checked for conflicts before touching anything, per the instruction.** Found one real,
necessary knock-on fix (below); everything else was clear. `val.parquet` was verified to
regenerate identically too (same check as step-17's `test.parquet`, using the scratch output
already on disk from that step) before committing it.

### 1. Committed `data/processed/test.parquet` and `data/processed/val.parquet`; `train.parquet` stays gitignored

`.gitignore`: added `!data/processed/test.parquet` and `!data/processed/val.parquet` next to
the existing `!data/processed/label_map.json` exception, with the sharper reasoning recorded
in the comment there: `make_dataset.py` is now PROVEN deterministic (step-17), so anyone WITH
the raw CSVs could regenerate all three splits identically -- but the raw CSVs are 53MB and
ALSO gitignored, so a person cloning this repo cannot verify a single published number without
first obtaining the source dataset. `test.parquet` is the literal denominator of every number
in `results/comparison.md`/`README.md`; `val.parquet` is what the step-14 checkpoint decision
was made on. `train.parquet` only affects reproducing the ~3-hour GPU training run, which
nobody re-runs to check a claim -- stays gitignored. 1.19 MB total (`test.parquet` 618 KB,
`val.parquet` 604 KB -- `ls -la` confirmed) buys full verifiability of every number in the
README, the same principle that already un-gitignored `label_map.json` (step-02 correction).
`git add`ed both files.

### 2. `api-gpt4o-mini-50` marked superseded in `results.json`, excluded from the main table, listed separately

Per the instruction: not deleted -- it's part of this project's own methodology story (the
step-04 sampling-trap bug, preserved on disk exactly as it happened). Added a `"superseded"`
key to its `results.json` entry (pure metadata addition -- every other field in the entry
verified byte-identical to before, programmatically, same check used in step-16):
```json
"superseded": {
  "reason": "... all 50 tickets in this run share a single queue value, \"Billing and
             Payments\" -- the step-04 sampling-trap bug ...",
  "superseded_by": "api-gpt4o-mini-full-test"
}
```
`report.py`'s `build_comparison()` now partitions `all_results` into `comparable` (rendered in
the main table, as before) and `superseded` (any entry with a `"superseded"` key) -- excluded
from the main table entirely, then listed under a new `## Superseded runs (excluded from the
comparison above)` heading with its reason and what to look at instead
(`superseded_by`). Regenerated `results/comparison.md`/`README.md`: confirmed
`api-gpt4o-mini-50` no longer appears in the main table and appears, with its explanation,
under the new heading.

### 3. `predict_random_baseline.py` made order-independent -- id-keyed, not position-keyed

**Real root cause, precisely, per the instruction's own framing: seeding alone is not
reproducibility.** `SEED=42` made the RNG's *draw sequence* deterministic, but the old code
assigned draw `i` to whatever id sat at position `i` of `test.parquet` when the script ran
(`sampled[field][i]` -> `target["id"][i]`) -- the *consumption order* was never pinned to
anything about the data itself, only to file position. Fixed: new `sample_for_row(ticket_id,
field, values, probs, seed)` seeds a fresh `np.random.default_rng` from
`sha256(f"{seed}:{ticket_id}:{field}")` for every single (ticket, field) pair, independent of
every other row and of the order `target["id"]` is iterated in. The single shared `rng =
np.random.default_rng(SEED)` and its one `rng.choice(..., size=n)` call per field are gone
entirely (not left as dead code -- removed, not just unused).

**Order-independence verified directly, not just argued:** ran `sample_for_row` against
`test.parquet` in its real order AND against a randomly-shuffled copy (`.sample(frac=1,
random_state=999)`, a different seed than anything else in this project, specifically to rule
out an accidental match) -- confirmed every ticket id maps to the exact same
`{queue, priority, type}` prediction in both orders. This is the property being claimed, checked
for real, not inferred from reading the code.

**Re-run for real, re-scored, results.json updated -- numbers changed, method did not
improve:**
```
                queue_f1   priority_f1   type_f1
old (position)  0.1110     0.3427        0.2577
new (id-keyed)  0.0996     0.3163        0.2444
```
Both are legitimate draws from the identical marginal distributions (`train.parquet`'s
per-field class frequencies, unchanged) -- the shift is sampling noise from which specific
draw each ticket happens to get under the new (correct) assignment, not a change in what the
baseline is modeling or any kind of improvement/regression to read into. `evaluate.py`'s new
step-17 hash check passed cleanly (no prior entry had a `gold_split` yet for `test`/`limit=None`
-- the bootstrap case) and `random-baseline`'s entry now carries both `gold_split` and
(unchanged) `run_meta`.

**Knock-on fix, found while checking for conflicts, not left stale:** `src/ticket_router/leakage_check.py`
hardcoded the OLD random-baseline macro-F1 values (`{"queue": 0.1110, "priority": 0.3427, "type":
0.2577}`) as a fixed comparison reference in `decide_verdict()`. Left as-is, it would have
silently gone stale the moment `random-baseline` above was re-scored -- exactly the class of
bug this whole investigation (step-17/step-18) has been about. Fixed at the root instead of
re-typing new numbers: new `load_random_baseline_f1()` reads the reference LIVE from
`results/results.json` (`STOP`s with a clear message if the entry is missing, rather than
guessing), so it can never drift from whatever `random-baseline` actually says again.
Re-ran `leakage_check.py`: `reports/leakage_check.md` now shows the new reference numbers
(0.0996/0.3163/0.2444); the verdict text's conclusion ("holds well above random -- consistent
with real signal") is unchanged -- the fix changed the reference numbers, not the finding.

**Other places the old numbers appear, deliberately NOT touched:** `PROGRESS.md`'s own earlier
entries (step-03/step-04/step-04c) and `reports/prompting_notes.md` (step-05) are historical
snapshots of what was true when written -- this project's established convention (e.g. the
step-02 corrections) is to append a new entry describing a change, never rewrite an old one to
match it. `README.md`/`results/comparison.md` needed no manual fix -- both are regenerated by
`report.py`, which now reads the corrected `results.json` automatically.

**Files changed:** `.gitignore`, `data/processed/test.parquet` (new, committed),
`data/processed/val.parquet` (new, committed), `results/results.json` (`api-gpt4o-mini-50`
superseded metadata; `random-baseline`'s metrics/`gold_split` updated),
`src/ticket_router/report.py` (superseded-run partitioning), `src/ticket_router/predict_random_baseline.py`
(id-keyed sampling), `src/ticket_router/leakage_check.py` (live reference instead of hardcoded),
`reports/leakage_check.md` (regenerated), `results/comparison.md` + `README.md` (regenerated),
`results/random-baseline.predictions.jsonl` (regenerated with the new, order-independent
predictions). No dependency added (`hashlib` is stdlib, already used by `evaluate.py` since
step-17).

**Verify with:**
```
.venv\Scripts\python.exe src\ticket_router\predict_random_baseline.py
.venv\Scripts\python.exe src\ticket_router\evaluate.py --predictions results\random-baseline.predictions.jsonl --split test --run-name random-baseline
.venv\Scripts\python.exe src\ticket_router\leakage_check.py
.venv\Scripts\python.exe src\ticket_router\report.py
.venv\Scripts\python.exe -m pytest -q
```
`pytest -q`: 11/11 still passing throughout.

**Next step: still run `adapter_predictor.py` on a real GPU (step-15) -- unaffected by this
step. When it's scored, `evaluate.py`'s step-17 hash check will run against `random-baseline`'s
(and every other run's) now-recorded `gold_split` hash automatically -- the 6 remaining
comparable entries (all full-split, `limit=None`) still lack a recorded `gold_split` and will
bootstrap theirs the first time each is next re-scored, same as `random-baseline` did here.**

## step-19: error analysis -- do qlora-adapter-ckpt1500 and tfidf-baseline fail on the same tickets, in the same direction?

`qlora-adapter-ckpt1500` was scored on the full test split (via `adapter_predictor.py` on a
real GPU + `evaluate.py`) since step-18: queue macro-F1 0.3999, priority 0.4944, type 0.8559,
exact-match 26.03%, invalid rate 0.06%. This step runs entirely on local files (no GPU, no
model) and answers one question, diagnosis only -- no fix, retraining, hyperparameter, or
label-merge proposal is made here: **do the fine-tuned adapter and the architecturally
unrelated TF-IDF baseline (bag-of-words + logistic regression vs. a fine-tuned transformer,
sharing no inductive bias) confuse the same class pairs, in the same direction?** If they do,
that is evidence the ceiling is a property of the LABELS, not of either model's capacity.

### New script: `src/ticket_router/error_analysis.py`

Reads both runs' `predictions_file` paths from `results/results.json` (never hand-typed),
`data/processed/test.parquet` as gold, and reuses `evaluate.load_predictions` (so an invalid
or missing prediction is classified exactly the way the harness itself classifies it -- the
`INVALID` sentinel from `metrics.py`, not silently dropped or re-implemented differently here).
Before scoring anything, re-verifies each run's recorded `gold_split` hash (step-17's mechanism)
against the `test.parquet` actually on disk, and STOPs if they disagree -- the same guarantee
`evaluate.py` gives a fresh scoring run applies to this analysis reading an old one back.

Produces, per field (`queue`/`priority`/`type`), entirely generated from the data:
1. A raw-count confusion matrix for each run (rows=gold, columns=predicted, `__INVALID__` as
   an explicit column only where it actually occurs).
2. Each run's top 10 confused (gold, predicted) pairs, side by side.
3. Agreement statistics: both right, only-A-right, only-B-right, and both wrong -- split
   further into "same predicted label" (the two runs actually agree with each other on the
   wrong answer -- literally a same-direction failure) vs. "different predicted labels."
4. (`queue` only) The IT Support hypothesis, stated and tested rather than assumed: the full
   destination distribution of all 194 gold IT Support tickets, for both runs, with an explicit
   plain statement of whether the top destination actually is Technical Support (it is).
5. 10 misclassified samples per field with real ticket text, gold label, and both runs'
   predictions -- selected round-robin across the ranked worst-confused pairs (one ticket per
   pair per pass) so the sample spans multiple failure patterns instead of exhausting the
   single worst pair first, which technically matches "ranked by count" but would not let a
   human see more than one failure mode.

Writes `reports/error_analysis.md`. Verify/regenerate with:
```
.venv\Scripts\python.exe src\ticket_router\error_analysis.py
```
No dependency added -- `collections.Counter` is stdlib; everything else (`pandas`,
`evaluate.load_predictions`, `metrics.md_table`) was already a project dependency.

### What the report found

**Central question -- answered, not left to interpretation.** Across the 1633-row test split:

| field | both right | only adapter right | only tfidf right | both wrong, SAME label | both wrong, different label |
| --- | --- | --- | --- | --- | --- |
| queue | 647 (39.6%) | 150 (9.2%) | 183 (11.2%) | 471 (28.8%) | 182 (11.1%) |
| priority | 652 (39.9%) | 215 (13.2%) | 322 (19.7%) | 341 (20.9%) | 103 (6.3%) |
| type | 1310 (80.2%) | 89 (5.5%) | 77 (4.7%) | 157 (9.6%) | 0 (0.0%) |

Of every row where at least one run was wrong, the two runs were wrong TOGETHER 66.2% of the
time on `queue`, 45.3% on `priority`, and 48.6% on `type` -- and within "wrong together," the
two runs landed on the exact SAME predicted (wrong) label far more often than not (queue:
471/653 = 72%; priority: 341/444 = 77%; type: 157/157 = 100%, no exceptions at all). "Wrong
together" dominates the error population on all three fields, and it is overwhelmingly
same-direction wrongness, not two models tripping on different things. Two architecturally
unrelated models converging this strongly on which specific wrong label to pick is the
signature the instruction described as the taxonomy answer: the confusion is a property of
what the labels ask two different models to distinguish (e.g. "Product Support" vs.
"Technical Support," "Problem" vs. "Incident," "high" vs. "medium" priority), not a gap in
either model's capacity that further tuning would be expected to close on its own.

**Top confused pairs overlap almost one-to-one between the two runs**, confirming this is not
an artifact of the aggregate statistic alone: for `queue`, both runs' #1/#2/#3 pairs are
identical in identity and order (`Product Support -> Technical Support`, `IT Support ->
Technical Support`, `Customer Service -> Technical Support`); for `type`, both runs' entire
error mass is the same two pairs (`Problem <-> Incident`) with everything else in single
digits; for `priority`, both runs' top pairs are the same three (`medium<->high`, `low<->
medium`) in slightly different order.

**IT Support hypothesis: confirmed, not just plausible -- reported plainly since it could have
gone the other way.** Of the 194 gold IT Support tickets, `qlora-adapter-ckpt1500` predicted
Technical Support for 139 of them (71.6%) -- the single largest destination by a wide margin
(next largest: IT Support itself, 16 tickets, 8.2%). `tfidf-baseline` shows the same direction
at a smaller magnitude: 112/194 (57.7%) also predicted Technical Support, with IT Support
itself catching more (43/194, 22.2%) than the adapter kept. Both runs' single biggest error on
this class, by far, is the same absorption in the same direction -- consistent with (2)/(3)
above rather than a fine-tuning-specific defect.

**Reading the sampled tickets themselves (queue's `Product Support -> Technical Support` pair,
`priority`'s `high -> medium` pair, `type`'s `Problem -> Incident` pair -- see
`reports/error_analysis.md` for the full text) supports the same reading**: several of the
sampled tickets read as genuinely ambiguous between the confused pair even to a human skim (a
report of a system crash/outage phrased as a request for help reads plausibly as either
Incident or Problem; a routine "please improve X" ask with no explicit urgency language reads
plausibly as medium or high priority depending on how much weight the reader puts on the
underlying business impact) -- consistent with the labels themselves carrying real ambiguity
that both architectures run into the same way, rather than one model missing something
extractable from the text that the other one gets.

**Nothing found that contradicts the stated hypothesis in point 4** -- flagging this
explicitly per the instruction to report plainly if the story did not hold, since it did.

**Files added:** `src/ticket_router/error_analysis.py`, `reports/error_analysis.md`. No other
file changed -- this step reads `results/results.json` and `data/processed/test.parquet`, it
does not write to either.

**Verify with:**
```
.venv\Scripts\python.exe src\ticket_router\error_analysis.py
.venv\Scripts\python.exe -m pytest -q
```
`pytest -q`: 11/11 still passing (this step added no new test file -- the script's own
gold-hash re-check at startup is its correctness guard, matching `evaluate.py`'s step-17
mechanism rather than duplicating it).

**Next step: not yet specified by Omar. This report is diagnosis only, per explicit
instruction -- no fix, retraining, hyperparameter, or label-merge decision has been made or
proposed here; that decision comes after Omar has read `reports/error_analysis.md`.**

## step-20: pre-push safety audit (read-only)

The repo has never been pushed (no `origin` remote), and a push uploads the FULL history, so
every check covered all commits (`git rev-list --all`, 32 commits at the time), not just the
current tree. Read-only: nothing modified, staged, committed, or deleted.

| check | result | evidence |
| --- | --- | --- |
| 1. Secrets in history (`sk-[A-Za-z0-9_-]{20,}`, `hf_[A-Za-z0-9]{20,}`, notebooks included) | PASS | `git grep` against every commit: 0 matches, not even placeholders |
| 2. `.env` tracking | PASS | not tracked; `git log --all --full-history -- .env` empty; covered by `.gitignore`'s `.env` line |
| 3. File sizes | PASS | largest blob across all history is `data/processed/test.parquet` at 618 KB, far under GitHub's 50 MB / 100 MB limits; `eval-bundle.zip`, any `checkpoint-*`, any `*.safetensors`, and `data/processed/train.parquet` were never committed |
| 4. Authorship | PASS | all 32 commits `Omar-Mohsen22 <omar1mohsen23@gmail.com>`; 0 hits for "Co-Authored-By" / "Claude" / "Anthropic" / "Generated with" in any commit message |
| 5. Dataset licence | FAIL | no `LICENSE` at repo root; `data/README.md` credits the source and CC-BY-NC-4.0 correctly, but the root `README.md` did not mention the dataset, its licence, or link to `data/README.md` -- while `test.parquet`/`val.parquet`, derived from that dataset, are committed |

Verdict at the time: NOT SAFE to push until check 5 was fixed (step-21).

**Files changed:** none.

**Verify with** (all read-only):
```
git rev-list --all | while read h; do git grep -nE 'sk-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{20,}' "$h"; done
git log --all --full-history --oneline -- .env
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | awk '$1=="blob"' | sort -k3 -rn | head -15
git log --all --format='%an <%ae>' | sort | uniq -c
```

**Next step: step-21 -- fix check 5.**

## step-21: MIT licence for the code, dataset attribution in the root README

Fixes the only FAIL from the step-20 pre-push audit (check 5). The other four checks (secrets
across all history, `.env`, file sizes, authorship) already passed and needed nothing.

- **`LICENSE`** (new): the standard MIT licence text, `Copyright (c) 2026 Omar Mohsen`. It
  covers the source code only.
- **`README.md`**: appended a `## Data and licensing` section (nothing else in the README was
  touched). It credits [Tobi-Bueck/customer-support-tickets](https://huggingface.co/datasets/Tobi-Bueck/customer-support-tickets)
  under [CC-BY-NC-4.0](https://creativecommons.org/licenses/by-nc/4.0/). It also states that
  `data/processed/test.parquet` and `val.parquet` are processed subsets redistributed under the
  same licence, for non-commercial use only, and that `train.parquet` is not committed and is
  regenerated by the pipeline. It says explicitly that the MIT licence does NOT apply to the
  dataset or any file derived from it, and links to `data/README.md` for the full data card. It
  makes no claim about the licence of the fine-tuned adapter or the base model; that was out of
  scope for this step.
- The section sits AFTER the `<!-- RESULTS_TABLE_END -->` marker, so `report.py`'s README sync
  (which only replaces the content between the markers) never overwrites it.
- **`.gitignore`**: added `eval-bundle.zip`, a temporary Colab transfer bundle that was sitting
  untracked in the working tree. Step-20 confirmed it was never committed; ignoring it keeps it
  from being committed by accident later.

Originally committed as `833f6a3` with a free-form message and without this entry. Amended
(step-22) to follow this project's `step-NN:` message convention and to include this entry, the
step-20 entry above, and the `.gitignore` line. This was safe only because nothing had been
pushed: `git remote -v` was confirmed empty before amending.

**Files changed:** `LICENSE` (new), `README.md`, `.gitignore`, `PROGRESS.md`.

**Verify with:**
```
git show --stat HEAD
git status
```
`git status` should report a clean working tree, with `eval-bundle.zip` no longer listed as
untracked.

**Next step: re-run the step-20 audit checks if anything else is committed, then push when
Omar decides to (adding the remote and pushing are his call, not part of this step).**

## step-23: private GitHub repo created, full history pushed

**Pre-checks (all passed before anything was created):** `gh` 2.101.0 installed; `gh auth
status` logged in as `Omar-Mohsen22`; `git remote -v` empty; `git status` clean; branch
`master`; `gh repo view Omar-Mohsen22/support-ticket-router` returned "Could not resolve to a
Repository", so the repo did not exist yet. (A first attempt at this step stopped at the
pre-checks because `gh` was not installed. Omar installed it and logged in himself, then the
step was re-run from the top.)

**Created and pushed in one command**, deliberately without `--description`, `--add-readme`,
`--license`, or `--gitignore`. Any of those would make GitHub create its own initial commit,
which would compete with this repo's existing history:
```
gh repo create Omar-Mohsen22/support-ticket-router --private --source=. --remote=origin --push
```

**Verified:**
- `origin` -> `https://github.com/Omar-Mohsen22/support-ticket-router.git`
- `master` tracks `origin/master`, nothing ahead or behind
- `git rev-parse HEAD` and `git ls-remote origin HEAD` are identical:
  `1d4f8d5da6bef9fb585c58706d8e2a185128ed62`, which proves GitHub holds exactly the local
  history
- visibility `PRIVATE`, default branch `master`
- 33 commits pushed (`git rev-list --count HEAD`, before this entry's own commit)

**The repo stays private until the README results write-up is done.**

**Files changed:** `PROGRESS.md` (this entry). The push itself changed no files.

**Verify with:**
```
git remote -v
git status -sb
git rev-parse HEAD
git ls-remote origin HEAD
gh repo view Omar-Mohsen22/support-ticket-router --json visibility,defaultBranchRef
```

**Next step: the README results write-up, then decide on making the repo public.**

## step-24: README results write-up; headline table generated by report.py

The README went from a `TODO` line plus a generated table to a full results write-up. It covers
a summary, headline results, what the results say, an error-analysis summary, training details,
reproduce commands and limitations. The existing "Data and licensing" section is unchanged,
byte for byte. Every number is read from a file in the repo; each one was listed with its source
file and field for review before commit. Voice is first-person singular, with no hype words.

### report.py now generates both README tables

- **New headline block.** A second marker pair (`HEADLINE_TABLE_START` / `HEADLINE_TABLE_END`)
  is filled by the new `build_headline()`. It holds exactly `random-baseline`, `tfidf-baseline`,
  `api-gpt4o-mini-full-test` and `qlora-adapter-ckpt1500`, in that order. It uses the same
  `format_latency_cell` / `format_cost_cell` formatters and `[tags]` as the full table. A
  review draft briefly held a hand-copied table here; this replaced it, so the headline
  numbers cannot go stale.
- **Missing inputs are reported, not hidden.** A headline run missing from `results.json` is
  omitted with a printed WARNING, not silently. If the headline markers themselves are missing,
  the block is not synced and a note is printed. Where the table sits in the prose is an
  editorial choice the script does not guess.
- **Only one H1 in the README.** The full comparison block's headings are demoted one level in
  the README copy (`demote_headings`), so `# Run comparison` becomes `## Run comparison` and the
  README has a single H1. `results/comparison.md` keeps its own `# Run comparison`.
- **The generated block moved.** It now sits after the headline section instead of directly
  under the title. `update_readme` locates blocks by marker, not by position, so the move is
  safe.
- **Verified idempotent.** Two consecutive runs of `report.py` produce byte-identical
  `README.md` and `results/comparison.md`.
- **Tests.** There are no tests for `report.py` (only `tests/test_metrics.py`), so none were
  extended. `pytest -q` still gives 11/11.

### Checkpoint selection: new source file

`results/full_val_losses.json` (967 bytes) was added. It is copied unchanged from Google Drive,
where the notebook's checkpoint-selection cell wrote it. It is the only record of the
full-validation eval loss per checkpoint. Before this step the repo said checkpoint-1500 was
selected, but not by how much. From this file:

- checkpoint-1500 has the lowest loss, 0.15380242466926575, out of 10 checkpoints.
- The final checkpoint-2451 has 0.16494038701057434, which is 7.24% worse.

The keys are Colab paths from the training run
(`/content/drive/MyDrive/ticket-router/outputs/qlora-run/checkpoint-N`), and the README says
so. Omar also cross-checked the training numbers against the run's own `trainer_state.json` on
Google Drive: `train_batch_size` 4, `max_steps` 2451, `num_train_epochs` 3, `best_global_step`
1500. These are consistent with `train/config.yaml` and with the file above.

### A wrong claim corrected before it was published

The instruction for this step originally framed `priority = low` as "every prompted attempt
scored zero recall; the fine-tune is the first to get non-zero recall." That was wrong on both
counts, per `results.json` (`fields.priority.per_class.low.recall`):

- The third few-shot variant (`coverage-median`) scored 0.0058 (2 of 345).
- `tfidf-baseline` (0.2406) and `random-baseline` (0.1855) were already non-zero.

The README now states that the adapter's 0.2783 is the highest of any run, and nowhere says
"first". A grep of the repo found no existing file making the "first" claim.
`PROGRESS.md:588-590` (step-05) says `low` was "0/345 ... regardless of prompting". That was true
for the three variants that existed then, and was superseded by Variant C in the same file at
line 694. It was left as a historical entry, per this project's append-only convention.

### Other decisions recorded in the README

- **Adapter batch size is not recorded per run.** It appears in no field of `results.json`'s
  run_meta, no local `run_meta.json` exists for this run, and the predictions file has no such
  field. The README therefore says the batch size comes from `inference.batch_size` in
  `train/config.yaml` (8) and is not recorded per run. Indirect evidence, not cited as a
  record: consecutive rows in the predictions file share identical `latency_ms` in 204 groups
  of 8 plus 1 group of 1, which totals 1,633.
- **The `type` overlap figure carries a caveat.** The 100% "same wrong label" figure on `type`
  is flagged as close to forced. 231 of the adapter's 234 `type` errors and 237 of TF-IDF's 246
  are Problem <-> Incident, counted from the predictions files.
- **The label-contradiction examples are a judgment call.** They are `tkt_011979`,
  `tkt_023949` and `tkt_024807`, picked from `reports/error_analysis.md`'s samples.
- **One limitation beyond the requested list:** one training run, one seed, no confidence
  intervals.

**Files changed:** `README.md`, `src/ticket_router/report.py`, `results/comparison.md`
(regenerated: adapter row, `gpu-local` note, training cost), `results/full_val_losses.json`
(new), `PROGRESS.md`. No dependency added.

**Verify with:**
```
.venv\Scripts\python.exe src\ticket_router\report.py
git diff --exit-code README.md results/comparison.md
.venv\Scripts\python.exe -m pytest -q
```
`git diff --exit-code` should report no changes right after a fresh `report.py` run, which
confirms the committed tables are exactly what the script generates.

**Next step: decide whether to make the GitHub repo (and the Hugging Face adapter repo)
public.**

## step-25: model card for the adapter; stray scaler.pt removed from the HF repo

Repo: `Omar-Mohsen22/ticket-router-qwen2.5-1.5b-qlora`. It stays PRIVATE.

### Pre-checks

The first attempt stopped here because `.env` had no `HF_TOKEN` key at all. Omar added a
fine-grained token, and the step was re-run from the top.

- **Account and access.** `whoami()` returns `Omar-Mohsen22`. The token is fine-grained with
  `repo.write` (plus `repo.content.read`, `repo.access.read`, `discussion.write`). Its scope
  entity is `user Omar-Mohsen22`, not this single repo, so in practice it has write access to
  every repo of that user. Reported to Omar, not changed here.
- **Repo files before changes:** `.gitattributes` 1,570, `README.md` 5,218,
  `adapter_config.json` 1,159, `adapter_model.safetensors` 73,911,112, `chat_template.jinja`
  2,507, `scaler.pt` 1,383, `tokenizer.json` 11,421,892, `tokenizer_config.json` 694. Two
  differences from the expected list were reported before anything was touched:
  - `.gitattributes`: the standard file every HF repo gets on creation.
  - `README.md`: the empty auto-generated PEFT template, with "[More Information Needed]" in
    every section, uploaded with the adapter in commit `91861f97`. Nothing custom was in it.
- **Base model licence**, from `model_info("Qwen/Qwen2.5-1.5B-Instruct").card_data`:
  `license: apache-2.0`, with a `license_link` to the model's `LICENSE` file.
- **Published `adapter_config.json` matches `train/config.yaml`:** base model, r=16, alpha=32,
  dropout 0.05, and the same 7 target modules. This was asserted in the generator.

### The model card

`model_card/README.md` is the source of truth. The same file was uploaded as `README.md` in HF
commit `1bbbcb0d` ("Add model card"). The Hub copy was re-downloaded and verified
byte-identical (7,353 bytes, same sha256).

- **Metadata:** the YAML front matter was set exactly as specified (`license: cc-by-nc-4.0`,
  `base_model`, `library_name: peft`, dataset, `en`, `text-generation`, the four tags).
- **Generated from repo files.** The body was built by a one-off generator script in the
  session scratchpad (not committed). It reads every number from `results/results.json`,
  `results/full_val_losses.json`, `train/config.yaml`, the Hub's `adapter_config.json`,
  `data/processed/label_map.json` and the split parquet files (train 13,070, val 1,635). The
  base model licence was read live from the Hub. The card is a static snapshot, so re-run a
  generator if the numbers change.
- **Usage snippet.** It mirrors `adapter_predictor.py`: tokenizer from the base model, pad =
  eos if unset, left padding, the same 4-bit config, and the runtime bf16/fp16 choice. It uses
  `apply_chat_template(tokenize=False, add_generation_prompt=True)`, then tokenizes separately
  with `add_special_tokens=False`, `max_length` 384, `do_sample=False` and `max_new_tokens` 64.
  The system prompt is embedded verbatim from `build_system_message(label_map)`, not retyped.
  The snippet was checked with `ast.parse`, but NOT run: there is no GPU here. The example
  ticket in it is illustrative input, not data.
- **Licence section.** The adapter is CC-BY-NC-4.0 because its training data is, so it is for
  non-commercial use only. The base model keeps its own licence, `apache-2.0` per its Hub
  metadata. No other legal claims are made.
- **One wording fix before upload.** "mostly fail on the same tickets" became "often fail on
  the same tickets and usually pick the same wrong label". Both-wrong is 66.2% of errors on
  queue but 45.3% on priority and 48.6% on type, so "mostly" overstated it.

### scaler.pt removed

It was deleted in its own HF commit, `466a328d` ("Remove stray scaler.pt (GradScaler state, not
needed for inference)").

### Verified after the changes

- Files: `.gitattributes` 1,570, `README.md` 7,353, `adapter_config.json` 1,159,
  `adapter_model.safetensors` 73,911,112 (unchanged), `chat_template.jinja` 2,507,
  `tokenizer.json` 11,421,892, `tokenizer_config.json` 694. `scaler.pt` is gone.
- `card_data.license` is `cc-by-nc-4.0`, and `card_data.base_model` is
  `Qwen/Qwen2.5-1.5B-Instruct`.
- `private: True`.

No dependency added. `huggingface_hub` (already present transitively in the venv) was used only
by scratch scripts outside the repo.

**Files changed:** `model_card/README.md` (new), `PROGRESS.md`.

**Verify with** (needs `HF_TOKEN` in `.env`):
```
.venv\Scripts\python.exe -c "import os; from dotenv import load_dotenv; from huggingface_hub import HfApi; load_dotenv('.env', override=True); i = HfApi(token=os.environ['HF_TOKEN']).model_info('Omar-Mohsen22/ticket-router-qwen2.5-1.5b-qlora', files_metadata=True); print(i.private, i.card_data.license, [(s.rfilename, s.size) for s in i.siblings])"
```

**Next step: decide whether to make the GitHub repo and the HF adapter repo public. If the HF
repo goes public, consider narrowing the token's scope to this one repo first.**

### Correction (same step, after the first push)

The "byte-identical, 7,353 bytes" check above compared the Hub file against the Windows working
copy, which has CRLF line endings. Git (`core.autocrlf=true`) stores `model_card/README.md` with
LF, as a 7,190-byte blob. The 163-byte difference is one CR per line, 163 lines. So the first
upload was NOT byte-identical to the GitHub source.

Fixed by re-uploading the exact committed blob (`git show HEAD:model_card/README.md`, 0 CR
characters) in HF commit `1cf69a4c` ("Normalize model card line endings to LF (match the GitHub
source)"). A re-download confirms the Hub `README.md` is now 7,190 bytes and identical to the
Git blob. After this commit, the repo is still private, `license` is still `cc-by-nc-4.0`,
`base_model` is still correct, and `adapter_model.safetensors` is still 73,911,112 bytes.
Content is unchanged; only line endings differ from the first upload.

Lesson for future uploads: upload from the Git blob, not the Windows working copy.

## step-26: FastAPI serving, phase 1 -- TF-IDF only

### 0. HF token check (verify only)

The token is now scoped to `model Omar-Mohsen22/ticket-router-qwen2.5-1.5b-qlora` with
`repo.content.read`, plus `user Omar-Mohsen22` with `repo.access.read`; global scope is empty.
**No write permission remains.** `model_info(...)` on the adapter repo still succeeds (private).

### 1. Investigation, reported before any code was written

- **Not persisted.** `tfidf_baseline.py` fitted and predicted in one run, and never saved a
  model.
- **Labels.** Label sets come from `data/processed/label_map.json`, via `schema.TicketLabels`.
  The API reuses them and defines no labels of its own.
- **A wrong assumption in the instruction.** It assumed the batch predictor calls a function to
  build its input from subject + body. No such function existed:
  - `text` was built inline in `make_dataset.py` with `np.where` over the whole DataFrame.
  - Every consumer reads the prebuilt `text` column: `tfidf_baseline.py`, `make_sft_dataset.py`
    line 150 (`"content": row["text"]`) and `adapter_predictor.py` line 332
    (`render_prompt(row["text"], ...)`). None of them builds the text separately, so all of
    them match `build_ticket_text` by construction.
- **No empty subjects in the data.** In the processed data, subjects are either null or
  non-empty (test: 259 null, 0 empty, 0 whitespace-only). A `subject: str` request field would
  therefore have produced `"\n" + body` for an empty subject, an input never seen in training.

Omar chose to extract a shared function (option a), and to make `subject` optional.

### 2. Shared input function, proven to change nothing

`src/ticket_router/ticket_text.py` defines `has_subject()` and `build_ticket_text(subject,
body)`. It returns `subject + "\n" + body` when there is a subject, otherwise `body` alone.
None, NaN, `""` and whitespace-only all mean no subject. `make_dataset.py` now builds
`has_subject` and `text` with these functions. The splits were regenerated in place, and all
required checks passed before going further:

- **`git status`:** `test.parquet`, `val.parquet`, `label_map.json` and `data/README.md` are all
  unchanged, byte-identical to the committed files.
- **`train.parquet`** (gitignored): the sha256 of its ordered id + `text` + `has_subject` is
  identical before and after (the same holds for val and test), and the file itself is
  byte-identical to a pre-change copy.
- **Gold hash:** `evaluate.compute_gold_hash` on the test ids gives `8841a6d1...`, identical to
  both entries stored in `results.json` (`random-baseline`, `qlora-adapter-ckpt1500`).

### 3. Persisted TF-IDF artifact

`tfidf_baseline.py` now has `fit_models()` and `save_artifact()`. It writes
`models/tfidf/model.joblib` (**3,635,302 bytes**) and `models/tfidf/meta.json` (562 bytes). The
meta records sklearn 1.9.0, joblib 1.6.0, 13,070 train rows, the train id-sequence sha256, both
model configs, the fields and a created-at timestamp. The new `--artifact-only` flag fits and
saves without touching `results/`. A full run would rewrite the predictions file and run_meta
with fresh timings, which is the same class of side effect step-16 had to revert. `models/` is
gitignored for now; the Docker step decides whether the artifact ships in the image.
`leakage_check.py` still imports `TFIDF_CONFIG` from this file, and the import was checked.

### 4. API (`src/ticket_router/api/app.py`)

- **Startup.** A lifespan handler loads the artifact once. If it is missing, startup fails
  with `RuntimeError` naming the build command. This was checked by pointing `MODEL_PATH` at a
  nonexistent file.
- **`GET /health`** returns `{"status": "ok", "model": "tfidf-baseline", "model_loaded": true}`.
- **`POST /predict`:**
  - Request: `{subject: str | None = None, body: str}`. An empty or whitespace-only body gets a
    422 from a pydantic validator.
  - Input: built with `build_ticket_text`.
  - Response: a `TicketLabels` subclass, so every label is validated against `label_map.json`.
    It adds `model` and `latency_ms`, which is measured per request around the transform and
    the 3 predicts.
- **Out of scope for this step:** no auth, no batch endpoint, no adapter code.

### 5. Tests

`pytest -q`: **26 passed**. That is the previous 11, plus 8 in `test_ticket_text.py` and 7 in
`test_api.py`.

- **`test_ticket_text.py`:** the join rule; None, NaN, `""`, `"   "` and `"\n\t"` all mean
  "body alone"; and `build_ticket_text` / `has_subject` reproduce the committed `test` and `val`
  `text` / `has_subject` columns for every row.
- **`test_api.py`:**
  - `/health` returns `model_loaded` true.
  - Labels are valid for every field.
  - 422 for a missing, empty or whitespace-only body.
  - An absent, `""`, `"   "` or `null` subject gives identical predictions.
  - **Parity:** for the first 200 test rows, the API's predictions match
    `results/tfidf-baseline.predictions.jsonl` exactly, with 0 mismatches. 26 of those 200
    rows have no subject, so the body-alone path is covered.
- **Skip behavior:** `test_api.py` skips with a clear reason if `models/tfidf/` is missing,
  which is the case on a fresh clone, because `models/` is gitignored. Here it ran; nothing was
  skipped.

### 6. Real request

Started with `python -m uvicorn ticket_router.api.app:app --app-dir src --port 8000`.

- `GET /health` returned `{"status":"ok","model":"tfidf-baseline","model_loaded":true}`.
- `POST /predict` with test ticket `tkt_009916` (subject "System Failure Caused by Overload"
  plus its body) returned `{"queue":"Technical Support","priority":"high","type":"Incident",
  "model":"tfidf-baseline","latency_ms":19.86...}`, HTTP 200. That is identical to the
  published TF-IDF prediction for this ticket (gold: Customer Service / high / Incident).
- A whitespace-only body returned HTTP 422.
- The server was stopped afterwards.

### Dependencies (named and justified in requirements.txt)

- `fastapi==0.141.1` and `uvicorn==0.53.0` were newly installed.
- `httpx==0.28.1` (needed by `TestClient`) was already installed via `openai`, and is now
  declared.
- `joblib==1.6.0` is **added beyond the three the instruction named.** It was already installed
  as a scikit-learn dependency, but it is now imported directly to save and load the artifact.

**Files changed:** `src/ticket_router/ticket_text.py` (new), `src/ticket_router/make_dataset.py`,
`src/ticket_router/predictors/tfidf_baseline.py`, `src/ticket_router/api/__init__.py` and
`app.py` (new), `tests/test_ticket_text.py` and `tests/test_api.py` (new), `requirements.txt`,
`.gitignore` (`models/`), `README.md` (Serving section; the Limitations bullet no longer says
there is no FastAPI service), `PROGRESS.md`.

**Verify with:**
```
.venv\Scripts\python.exe src\ticket_router\predictors\tfidf_baseline.py --artifact-only
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m uvicorn ticket_router.api.app:app --app-dir src --port 8000
```

**Next step: serve the adapter (phase 2), or Dockerize the TF-IDF service -- Omar's call.**

## step-27: Dockerfile + CI for the TF-IDF API; serve the exact evaluated artifact

### The local CPU probe was cancelled

The first version of step-27 was a local CPU feasibility probe for the adapter. It stopped
before anything was installed or written. The laptop has 11.7 GB RAM with only 1.5 GB free at
the time, and the pagefile was already 8.2 GB into use. That is not enough for an unquantized
1.5B model, which needs about 6.2 GB of weights in fp32 or about 3.1 GB in bf16. Omar then set
the deployment target to a Hugging Face Docker Space (CPU Basic: 2 vCPU, 16 GB RAM), so the
12 GB laptop is not the target. The adapter will be measured there in a later step. Nothing
from the probe was installed or committed.

### Dataset pinned; requirements split

- **Pinned dataset revision.** `inspect_data.py` now downloads from Hub revision
  `ddf1c81a5475992c4fa6752bf1e8b4e31f07bbeb` (the full sha, read from the Hub API), via
  `tree/<sha>` and `resolve/<sha>/<file>`, instead of `main`. All 3 files at that revision were
  checked byte-for-byte against the originally downloaded copies:
  - the two LFS files by sha256;
  - the German file, which is not in LFS, by its git-blob sha1.
- **Recorded in the data card.** `make_dataset.py` writes the revision into `data/README.md`.
  Regenerating everything changed only that one line: splits, `label_map.json` and
  `reports/data_report.md` are all unchanged.
- **Requirements split.** `requirements-serve.txt` holds exactly the 10 packages the data build,
  the TF-IDF artifact, the API and the tests import: pandas, pyarrow, numpy, pydantic,
  scikit-learn, joblib, fastapi, uvicorn, httpx, pytest. `requirements.txt` starts with
  `-r requirements-serve.txt`, so each pin lives in one place. The image installs only the serve
  file. The full file would pull an unpinned torch, which on Linux is a CUDA build with nvidia
  libraries of several GB.

### Windows-vs-Linux refit: the finding, with numbers

The first CI design fitted TF-IDF inside the Docker build. Two runs (`35896503865` and
`35898329488`) failed the parity test the same way: **14 of the first 200 test rows**
differed from the published (Windows-fit) predictions. That was 15 field-level differences:
queue 5, priority 6, type 4. The diagnosis run (`35898329488`, `diagnose_tfidf.py` inside the
build) found:

- **The data is identical.** Train sha256 over text + labels is `c9f82636...c929` on both
  Windows and Linux. Val is `edb25863...d25e` on both. The test split passed the gold-hash
  check.
- **Package versions are the same** for numpy 2.5.3, scipy 1.18.1, scikit-learn 1.9.0 and
  joblib 1.6.0. Only threadpoolctl (3.6.0 local vs 3.7.0) and idna differ.
- **No convergence problem.** 0 ConvergenceWarnings on both sides; n_iter_ was 14-52 against
  `max_iter=1000`.
- **But the optimizer path differed.** n_iter_ differed in 14 of the 17 one-vs-rest estimators.
  For example, type/Problem took 40 iterations on Windows and 52 on Linux. On each machine, the
  refit matched its own artifact.

Reading, not proven: floating-point results differ between the two environments, so lbfgs stops
at different points inside `tol`, and borderline tickets flip.

**The sensitivity job then contradicted the finding.** The dedicated `refit-sensitivity` job in
run `35899571019` refitted on Linux (same image, `ubuntu-24.04`) and measured **0 differing test
rows** out of 1,633. Its macro-F1 and exact match were identical to the published ones. So a
Linux refit is not always different: two runs differed (14 of the first 200 rows) and one did
not (0 of 1,633).

The CPU model of each runner was not logged, so what changed between those runs is unverified.
A likely candidate is the runner hardware, since GitHub-hosted VMs do not all have the same CPU,
and BLAS picks kernels per CPU. What is established: a refit is not guaranteed to reproduce the
published model, while the committed artifact always does.

### Decision: serve the exact evaluated artifact

Serving is decoupled from refitting.

- **Checked first.** The Windows-built `models/tfidf/model.joblib` reproduced
  `results/tfidf-baseline.predictions.jsonl` on **all 1,633 test rows**, with 0 field
  mismatches.
- **Committed.** `.gitignore` un-ignores exactly `models/tfidf/model.joblib` and
  `models/tfidf/meta.json`. The artifact is 3,635,302 bytes, sha256
  `b118960f60410d3c930eba6fc26056c5f01e88b343ce1338332316ea74683447`. That sha256 was added to
  `meta.json`, and `save_artifact()` now records it for future artifacts. A new `.gitattributes`
  marks `*.joblib` as binary, so line-ending conversion can never touch it. The staged blob was
  verified to be the same sha256.
- **Licence.** The README's "Data and licensing" section now states that the artifact is
  derived from the CC-BY-NC-4.0 data and carries the same licence.
- **Dockerfile.** No fit step. It copies the committed artifact, and `check_artifact.py` fails
  the build if its sha256 does not match `meta.json`. The data download (pinned revision),
  `make_dataset.py` and `check_gold_hash.py` stay, because the tests need `test.parquet`.
- **Parity test.** It now covers all 1,633 test rows instead of 200, the assertion is still
  exact, and it lists every mismatch.
- **Kept, but out of the build.** `diagnose_tfidf.py` stays in the repo, but no longer runs
  during the build.
- **Warnings against refits.** `tfidf_baseline.py`'s docstring, the README Reproduce step and
  the API's missing-artifact message all warn that a refit overwrites the committed artifact and
  is not bit-identical.

### CI

`.github/workflows/ci.yml` runs on push to master and on pull requests, uses no secrets, and is
pinned to `ubuntu-24.04`. It has two jobs:

- **`docker`:**
  1. build (sha256 check, pinned download, gold-hash check);
  2. `pip freeze` and image size;
  3. `pytest` inside the image with `-e CI=true`, where a missing artifact fails instead of
     skipping;
  4. start the container, then `curl /health` and one `/predict`, failing on anything but 200.
- **`refit-sensitivity`:** builds the image, runs `refit_sensitivity.py`, writes the table to
  the job summary, and uploads it as a job artifact. The script refits with the unchanged
  `fit_models()` and scores with `evaluate.evaluate()`. It asserts the published predictions
  still score exactly as `results.json` says. It never writes under `results/` or `models/`.

**Run `35899571019`** (commit `8787fbb`): both jobs passed, 72 s end to end.

- **Tests in the image:** 26 passed, 0 skipped. The full-split parity test passed:
  1,633/1,633.
- **Image:** 659 MB (659,170,774 bytes), 32 packages.
- **Container checks:**
  - `GET /health` returned 200: `{"status":"ok","model":"tfidf-baseline","model_loaded":true}`.
  - `POST /predict` returned 200: Technical Support / high / Incident.
- **Sensitivity:** queue 0.3683, priority 0.5445 and type 0.8412 macro-F1, and 29.33% exact
  match, are identical for the published model and the Linux refit, with 0 rows differing per
  field.

**Warnings left for later:** `actions/checkout@v4` and `upload-artifact@v4` are on the
deprecated Node 20. Starlette warns that `httpx` with its TestClient is deprecated in favour of
`httpx2`.

**Files changed (whole step):** `Dockerfile`, `.dockerignore`, `.gitattributes`,
`.github/workflows/ci.yml`, `.gitignore`, `requirements.txt`, `requirements-serve.txt`,
`models/tfidf/model.joblib` + `meta.json` (now committed), `src/ticket_router/inspect_data.py`,
`make_dataset.py`, `check_gold_hash.py`, `check_artifact.py`, `diagnose_tfidf.py`,
`refit_sensitivity.py`, `predictors/tfidf_baseline.py`, `api/app.py`, `tests/test_api.py`,
`data/README.md`, `README.md`, `PROGRESS.md`. No new dependency; the serve file only moves
existing pins.

**Verify with:**
```
.venv\Scripts\python.exe src\ticket_router\check_artifact.py
.venv\Scripts\python.exe src\ticket_router\check_gold_hash.py
.venv\Scripts\python.exe src\ticket_router\refit_sensitivity.py
.venv\Scripts\python.exe -m pytest -q
```
or push and read both CI jobs.

**Next step: Omar's call. Options: log the runner CPU in the sensitivity job to settle the
Windows-vs-Linux question; deploy the image to the HF Docker Space; or serve the adapter.**

### Correction (step-27 close-out): the sensitivity result varies between runs

The "0 differing test rows" above came from a single run, `35899571019`. A later run,
`35899886980`, used the same runner label (`ubuntu-24.04`) and the same image recipe, and found
**81 of 1633** test rows differing. The metric table from that run
(`refit_sensitivity.json`, downloaded from the run's job artifact):

| metric | published (tfidf-baseline) | Linux refit | delta | test rows whose prediction differs |
| --- | --- | --- | --- | --- |
| queue macro-F1 | 0.3683 | 0.3710 | +0.0027 | 35 |
| priority macro-F1 | 0.5445 | 0.5451 | +0.0006 | 33 |
| type macro-F1 | 0.8412 | 0.8399 | -0.0013 | 15 |
| exact match | 29.33% | 29.15% | -0.18 pp | 81 |

The last column counts rows whose prediction for that field differs; for exact match, rows where
any field differs.

Across the two recorded sensitivity runs:
- **Differing rows:** 0 and 81 of 1633.
- **Largest macro-F1 move on any field:** 0.0027.
- **Adapter-vs-TF-IDF ordering:** unchanged on every field and on exact match. For each of those
  metrics, the adapter is above or below the refit exactly when it is above or below the
  published TF-IDF model.

Two runs are not enough to call this an error margin. From this step on, the `refit-sensitivity`
job records the runner's CPU (`lscpu`: model name, core counts and a SIMD-flag summary) in its
log, job summary and job artifact, so each future measurement can be matched to the hardware it
ran on.

Also in this close-out, the README's Limitations section was updated in two places:
- It gained the refit bullet above, generated from the two runs' recorded
  `refit_sensitivity.json` files and `results.json`.
- Its "Serving" bullet was corrected. It still said Docker and CI were planned; both exist now.
  Deploying to a HF Space and serving the adapter remain planned.

## step-28: hosted deployment -- a private Hugging Face Docker Space, deployed by CI

### Hosting decision history

Step-28 was redefined several times before landing here.

1. **HF Docker Space, first attempt: dropped.** Omar found in the Space-creation UI that Docker
   Spaces required a paid plan.
2. **GitHub Container Registry: cancelled.** It was investigated only; nothing was pushed.
   - GitHub's Packages billing docs give GitHub Free 500MB storage / 1GB transfer, but also say:
     "Container image storage and bandwidth for the Container registry is currently free. If you
     use Container registry, you'll be informed at least one month in advance of any change to
     this policy."
   - The account's billing and budget settings could not be read: the API needs the `user`
     scope, which the `gh` token lacks.
3. **Render free web service: measured, then dropped.** The fit check (512 MB RAM, `$PORT`) was
   measured in CI (commit `8b4b804`, run `36108478920`) with `--memory=512m --memory-swap=512m`
   and `PORT=10000`:
   - `/health` on port 10000 returned 200, so the CMD's `${PORT:-7860}` works.
   - Memory at startup was 138.9 MiB (docker stats) and memory.current 146,079,744 bytes. After
     30 s idle it was 138.6 MiB, and after 200 sequential `/predict` calls (all 200 returned 200)
     it was 139 MiB. memory.peak was 155,279,360 bytes (148.1 MiB) throughout.
   - Not OOM-killed; `memory.events` was all zeros.
   - uvicorn runs 1 worker (the default).
   - The app pulls in `pandas`, `pyarrow`, `evaluate` and `run_meta` at startup through its
     import of `tfidf_baseline.py`, none of which serving needs. That was reported, not changed.

   Render then asked for a card at deploy time, so it was not free as advertised.
4. **Chosen: HF PRO ($9/month, fixed price).** It makes Docker Spaces available, and it also
   covers the adapter demo on ZeroGPU later. Omar created the Space by hand:
   `spaces/Omar-Mohsen22/support-ticket-router`, Docker SDK, Blank template, CPU Basic (free
   hardware), private, cc-by-nc-4.0.

### Pre-checks (HF_SPACE_TOKEN from .env, never printed)

- **Token:** fine-grained, `space Omar-Mohsen22/support-ticket-router` with `repo.access.read`,
  `repo.content.read`, `repo.write`. The `user Omar-Mohsen22` entry has an empty permission
  list, and the global scope is empty. The only write permission is on this Space.
- **Space:** exists, `sdk=docker`, `private=True`, requested hardware `cpu-basic`. The stage was
  `NO_APP_FILE` (nothing uploaded yet), so current hardware read `None`.
- **The `HF_SPACE_TOKEN` secret** exists in the GitHub repo. It was checked by name only, with
  `gh secret list`.

### What was built

- **`deploy/space/README.md`** is the Space's README and the source of truth.
  - Field names were taken from the official Spaces config reference: `title`, `sdk`,
    `app_port` (int, default 7860, which matches the Dockerfile's `PORT`) and
    `short_description`.
  - `license` is not on that page. Its name was taken from the README HF itself generated at
    Space creation (`license: cc-by-nc-4.0`), which also held the `emoji`, `colorFrom`, `colorTo`
    and `pinned` values Omar picked in the UI. Those were kept as they were.
  - The body is four first-person lines: what is served, that it is the exact evaluated model,
    the GitHub link (private for now), and the licence note.
- **`deploy/space/deploy_space.py`** has `--dry-run` to list the files only.
  - **File list.** It uploads exactly what the Dockerfile build needs: the `COPY` lines filtered
    by the `.dockerignore` allowlist, tracked files only (`git ls-files`). That is `Dockerfile`,
    `.dockerignore`, `requirements-serve.txt`, `pytest.ini`, the 3 `data/processed` files, the 2
    `models/tfidf` files, and all tracked files under `src/`, `tests/` and `results/`: 58 files,
    plus `deploy/space/README.md` as `README.md`. The script refuses to upload anything matching
    `.env`, key, `__pycache__` or `.venv` patterns.
  - **Upload.** It uses `HfApi().upload_folder(repo_type="space", delete_patterns=["*", "**/*"])`.
    `huggingface_hub` never deletes `.gitattributes`. The commit message contains the GitHub
    commit sha.
  - **Waiting for the build.** The Space runtime API reports no commit sha, so after an upload
    that creates a commit, the script requires a build stage (BUILDING / RUNNING_BUILDING /
    APP_STARTING / RUNNING_APP_STARTING) to be seen before it accepts RUNNING. Otherwise it could
    smoke-test the old build. Timeouts: 5 min to see a build stage, 25 min to reach RUNNING
    (HF's own default startup timeout is 30 min). It fails on BUILD_ERROR, RUNTIME_ERROR,
    CONFIG_ERROR, STOPPED, PAUSED and DELETING. An upload with no changes creates no commit, and
    then no rebuild is waited for.
  - **Smoke test.** It sends an `Authorization: Bearer` header to the `*.hf.space` host. It
    retries `/health` for up to 2 min while the router warms up, and requires `/health` 200 with
    `model_loaded` true. It then requires `/predict` on test ticket `tkt_009916` to return 200
    and match the published tfidf-baseline prediction exactly, and sends 5 more warm `/predict`
    requests. Every request's latency is logged, and the table goes to the job summary.
- **The `deploy` job** in `.github/workflows/ci.yml`: `needs: docker`, runs only on push to
  master, `ubuntu-24.04`, 40-min job timeout. It uses Python 3.12 via `actions/setup-python@v5`.
  It installs `huggingface_hub==1.31.0`, a CI-only deploy tool pinned to the locally verified
  version and not added to any requirements file, plus pandas/pyarrow/numpy at the same pins as
  `requirements-serve.txt` to read the smoke-test ticket. The token comes from
  `secrets.HF_SPACE_TOKEN` and is never echoed.

### First deploy: CI run 36261663632 (commit 325c643)

- **Jobs:** `docker`, `refit-sensitivity` and `deploy` all succeeded.
- **Upload** created Space commit `a26917b636ebfdc0db00676dd8dc47bead077cc0`.
- **Build:** stage BUILDING at 0, 15, 30 and 45 s, then RUNNING at 61 s.
- **Space URL:** https://omar-mohsen22-support-ticket-router.hf.space (private).
- **Smoke test.** Client latency was measured from the GitHub runner, so it includes the
  network round trip:
  - `GET /health` (first) returned 200 in 250 ms: `{'status': 'ok', 'model':
    'tfidf-baseline', 'model_loaded': True}`.
  - `POST /predict` (first, `tkt_009916`) returned 200 in 196 ms: Technical Support / high /
    Incident, server latency_ms 6.82. It **matches** the published prediction exactly.
  - The 5 warm `/predict` calls took 222 / 211 / 196 / 232 / 203 ms (median 211 ms), with server
    latency_ms 3.26-3.65.
- **The token was never exposed:** the full run log contains 0 `hf_...`-like strings, and the
  env line shows `HF_SPACE_TOKEN: ***`.
- **Not measured:** a cold start after the Space goes to sleep.

**README:** the "Serving" section now names the private Space, the deploy flow and the measured
latencies. The Limitations "Serving" bullet now says the service is deployed to a private
Space, instead of "not deployed yet".

**Files changed:** `deploy/space/README.md` (new), `deploy/space/deploy_space.py` (new),
`.github/workflows/ci.yml` (memory measurement step in the `docker` job, `deploy` job),
`README.md`, `PROGRESS.md`.

**Verify with:**
```
python deploy/space/deploy_space.py --dry-run
```
or push to master and read the `deploy` job's summary.

**Next step: Omar's call. Options: make the GitHub repo and/or the Space public; serve the
adapter as a ZeroGPU demo (covered by HF PRO); or trim the unneeded startup imports.**

## step-29: ZeroGPU demo -- TF-IDF vs the fine-tuned adapter, side by side

This entry is being written checkpoint by checkpoint. The final summary (agreement numbers,
README) is appended when the step closes.

### TODO -- blocker before the demo Space is ever made public

`predict_batch` is a hidden endpoint, added only for the step-29 agreement measurement. It sits
in a `gr.Row(visible=False)`, so it is not in the UI, but it is still callable, and it appears on
the Space's "Use via API" page. **It must be removed or disabled before the demo Space goes
public**, so outside visitors cannot use it to drain GPU quota. (Resolved: removed in step 31.)

### Dependency note: pydantic differs between the repo and the demo Space

The repo pins `pydantic==2.13.5` (`requirements-serve.txt`). The demo Space pins
`pydantic==2.12.5` (`deploy/demo/requirements.txt`). HF installs `gradio[oauth,mcp]==6.28.0` for
a Gradio Space with `sdk_version: 6.28.0`, and its `mcp` extra requires
`pydantic<=2.12.5,>=2.11.10`. With the repo's 2.13.5, the Space build failed with
`ResolutionImpossible`.

With 2.12.5, every declared constraint was checked against PyPI metadata before pushing:
- gradio 6.28.0: `pydantic<=3.0,>=2.0`, plus the `mcp` extra's bound above;
- spaces 0.51.3: `pydantic<3,>=1`;
- mcp 1.30.0: `pydantic<3.0.0,>=2.11.0`.

The project code the Space runs (`TicketLabels`, `model_dump`) uses only pydantic 2 APIs that
both versions have.

### GPU ledger (cap: 10 GPU-minutes, all within the free 40-min PRO daily quota; $2 credits untouched)

| call | GPU inside `@spaces.GPU` | server end to end |
| --- | --- | --- |
| CI smoke test, run 36301053541, `tkt_014741` | 1,090 ms | 2,571 ms |
| duration probe: single `tkt_000466` | 881 ms | 5,980 ms |
| duration probe: single `tkt_011979` | 960 ms | 2,913 ms |
| duration probe: batch of 8 (`predict_batch`) | 1,161 ms | 5,270 ms (client wall) |
| **total so far** | **4.1 s** | **16.7 s** (the conservative count used against the cap) |

The deploy attempts that failed (a build error and a module-level runtime error) never reached a
GPU call, so they used no quota.

### Duration sizing (per endpoint)

The ZeroGPU docs say `duration` sets the maximum runtime of the decorated function: "This sets
the maximum function runtime to 120 seconds." The docs connect it to queue priority: "Specifying
shorter durations for quicker functions will improve queue priority for Space visitors." They
also support a dynamic duration: "pass a callable that takes the same inputs as your decorated
function and returns a duration value".

Measured: a single ticket took 0.88-1.09 s inside the GPU call, and a batch of 8 took 1.16 s.
Decoding dominates, so the batch size barely matters. The worst case is an output running to
`max_new_tokens` = 64, about 4x a normal ~15-token answer, so roughly 4 s.

- **Single-ticket UI call:** `duration=10` s, about 2.5x that worst case and about 9x the
  measured time.
- **`predict_batch`:** a dynamic duration of `10 + 0.5 x n_tickets` s, so 14 s for the batch of 8
  used in the measurement and 18 s at the `MAX_BATCH` of 16. The measured marginal cost is about
  0.03 s per ticket.

These bf16-era durations were replaced when the demo switched to 4-bit; see below.

### Finding: the demo's bf16 setup did not reproduce the published adapter; the evaluated 4-bit config did

- **bf16, all 1,633 test tickets** (`reports/adapter_zerogpu_agreement.md`, commit `b57daee`).
  The first demo setup used a bf16 unquantized base, the adapter merged, and batch 16. It agreed
  with the published predictions on only **1,186 / 1,633 = 72.63%** of tickets on all three
  fields (queue 84.94%, priority 83.83%, type 96.39%). Its macro-F1 was lower on every field:
  queue 0.3849 vs 0.3999, priority 0.4696 vs 0.4944, type 0.8391 vs 0.8559. On type, that is
  below TF-IDF's 0.8412.
- **4-bit, first 400 tickets of the same seed=29 order** (`reports/adapter_zerogpu_4bit.md`,
  commit `deea718`). This run used the published config: 4-bit NF4 with double quant, the
  adapter unmerged, float16 compute pinned, batch 8, through the same
  `load_model_and_tokenizer()`. It agreed with the published predictions on **399 / 400** on all
  three fields (queue 100%, priority 99.75%, type 100%). On the same 400 tickets, bf16 agreed on
  291 / 400 (72.75%).
- **Hardware ruled out.** The 4-bit run on ZeroGPU (Blackwell) reproduced the T4 run almost
  exactly, so the hardware is not what caused the bf16 gap.
- **Cause not isolated.** The bf16 gap comes from one or more of: precision (bf16 unquantized vs
  4-bit NF4), merged vs unmerged adapter, and batch 16 vs 8. Which of these matters was not
  isolated further.
- **Where the 4-bit endpoint came from.** It lived only on the local branch
  `probe/4bit-zerogpu` (commit `629c12c`) and was deployed by hand from a separate worktree. The
  Space was then redeployed from master (Space commit `f29f6ad`) and verified: `app.py` and
  `requirements.txt` byte-identical to master, and only the `/classify` and `/predict_batch`
  endpoints.
- **Is bitsandbytes on ZeroGPU officially supported?** There is no official statement. The
  ZeroGPU docs do not mention it, and the one relevant thread is a user report in
  `zero-gpu-explorers` (discussion #71). The `bitsandbytes==0.50.2` wheel ships
  `libbitsandbytes_cuda130.so` with `sm_120` (Blackwell) and `sm_75` (T4) kernels. The probe
  proved that loading works inside `@spaces.GPU`: 5.9 s for the first load, ~1.7 s after that.

### Decision: the demo now serves the evaluated 4-bit config

`deploy/demo/app.py` on master now loads the adapter with `load_model_and_tokenizer()`: 4-bit
NF4 with double quant, adapter unmerged, and `torch.float16` compute pinned. This replaces the
bf16 merged path.
- **The model is loaded inside every GPU call.** This is required: 4-bit quantization needs a
  real GPU, and ZeroGPU gives none at module level.
- **Weights are pre-downloaded.** `snapshot_download` at startup puts the base model and the
  private adapter in the disk cache, so no GPU call pays for a 3 GB download.
- **Batches of 8** inside every call, as in the evaluated run.
- **Requirements:** `bitsandbytes==0.50.2` and `accelerate==1.14.0` were added to the demo's
  requirements, the same versions the Colab environment used.

**Durations** are sized from the probe's measured latencies. Loading took 1.6-1.75 s warm and
5.9 s cold; a batch of 8 took 0.93-1.5 s; an output running to 64 tokens is ~6 s at worst.
- Single-ticket UI call: **20 s**. That is ~1.7x the worst case (cold load plus a runaway
  output, ~12 s) and ~7x a typical call (~2.7 s).
- `predict_batch`: **`20 + 3 x ceil(n / 8)` s**, with `MAX_BATCH` raised to 96 (12 batches of 8,
  at most 56 s per call). Bigger calls spread the per-call load over more tickets.

**UI caveat, stated on the page.** The page sends one ticket at a time, so a UI request has no
batch padding. The 399/400 match was measured in batches of 8, and padding can occasionally
change an output.

### TODOs

- **Blocker before the demo Space is made public:** remove or disable `predict_batch` (see above).
- **Full 1,633-ticket 4-bit agreement run, on a fresh daily quota.** Only 400 tickets were run
  today, to stay inside the 10-GPU-minute cap. For the full run, point
  `deploy/demo/measure_4bit.py` at master's `/predict_batch` (it now serves 4-bit in batches of
  8, up to 96 tickets per call) and set `N_TICKETS` to 1,633. As written, the script targets
  the branch-only `/predict_batch_4bit`.

### GPU ledger for today (conservative: each call's full wall time)

| item | seconds |
| --- | --- |
| up to the batch-of-8 duration verification (table above, plus 2.1 s + 2.7 s) | 21.5 |
| bf16 agreement run, 1,633 tickets, 103 calls | 127.7 |
| smoke test of the branch (4-bit probe) deploy | 2.3 |
| 4-bit calls: probe plus 400 tickets, 6 calls | 75.0 |
| smoke test of the redeploy back to master | 2.9 |
| **total before the 4-bit switch is pushed** | **229.3 (3.82 min)** |

The smoke test of the push that shipped the 4-bit switch (CI run `36327595748`) added 4.8 s
(client wall 4,788 ms), for **234.1 s (3.90 min)** in total.

### Full 1,633-ticket 4-bit agreement run (2026-09-28)

This run closes the earlier TODO (the full run, on the next day's quota).
- **What was run:** `deploy/demo/measure_4bit.py` (commit `0ebf84f`, `--run full`), against
  the deployed **master** demo's `/predict_batch` (commit `85feb19`). It covered all 1,633 test
  tickets in the seed=29 order, in 18 calls (16, then 16 x 96, then 81), in batches of 8.
- **The budget was checked first.** Omar raised the day's cap to 20 conservative minutes, inside
  the free 40-minute daily quota. Before any GPU call, the run was estimated at 4.52 min from the
  6 calls measured the day before (7.45 min pessimistic), for a day total of 8.42 min (11.35
  pessimistic). The gate at 208 tickets projected 8.42 min.
- **Result** (`reports/adapter_zerogpu_4bit_full.md`): the run agreed with the published
  predictions on **1,623 / 1,633 = 99.39%** of tickets on all three fields (queue 99.88%,
  priority 99.63%, type 99.88%). Exactly 10 tickets have a different valid label.
- **Macro-F1, published vs 4-bit ZeroGPU:** queue 0.3999 vs 0.4004, priority 0.4944 vs 0.4918,
  type 0.8559 vs 0.8562. The earlier bf16 run scored 0.3849 / 0.4696 / 0.8391, and TF-IDF
  0.3683 / 0.5445 / 0.8412.
- **Invalid outputs:** 1 / 1,633. It is the same ticket as the published run's single invalid
  output (`tkt_003783`, where the model puts "Incident" in the queue field).
- **Conclusion.** On the full test split, the deployed demo reproduces the evaluated model to
  within 10 tickets, and its macro-F1 is within 0.003 of the published numbers on every field.
  This also confirms the 400-ticket finding: the hardware does not explain the bf16 gap.
- **GPU:** the run's calls took 266.7 s conservative, so the day's total is **500.8 s
  (8.35 min)**. Margin: 699.2 s to the 20-minute cap, 1,899.2 s to the 40-minute free quota.

### TODO -- redesign the demo UI after step-29 closes

The options are to be reviewed visually before anything is implemented.

Part of the redesign: show **gpt-4o-mini (zero-shot)** as a third column.
- It uses the stored evaluation predictions, and only for the example tickets. There are no
  live API calls and no OpenAI key on the Space.
- For free-text input, the column shows "available for examples only".
- The UI carries this note: "gpt-4o-mini predictions are the stored outputs from my evaluation
  run, shown for the examples only. I don't call it live here: a public page would need my API
  key on the server, and every visitor's request would be billed to my account."
- **Checked (2026-09-28):** `results/api-gpt4o-mini-full-test.predictions.jsonl` is committed.
  It has 1,633 rows, `n_gold` is 1,633 and `invalid_rate` is 0.0 in `results.json`, and the run
  is not superseded. It covers all 6 current example ticket ids (`tkt_014741`, `tkt_021899`,
  `tkt_015123`, `tkt_011979`, `tkt_023949`, `tkt_024807`), each with a valid queue, priority and
  type and no error.

### Go-public checklist (all must be done before the demo Space is made public)

- [x] Remove or disable the hidden `predict_batch` endpoint in `deploy/demo/app.py`, so visitors
  cannot use it to drain GPU quota. See the blocker TODO at the top of this entry. Done in step 31
  (removed).
- [ ] The README's "Demo" section links to the demo Space, which is private for now. Recheck the
  link, and the "(private for now)" wording, once the Space is public.
- [ ] Step 30: the demo page links to the GitHub repo in its header (Results, Error analysis,
  Code) and in its notes (error analysis, agreement report). While the repo is private, those
  links 404 for everyone else. Make the repo public too, or change the links, before the Space
  goes public.
- [x] API Space (`Omar-Mohsen22/support-ticket-router`): "/" currently returns
  `{"detail":"Not Found"}`. Make "/" redirect to `/docs`. Done in step 31.
- [ ] After making the demo public, check that it loads in a Chrome incognito window with the
  default third-party-cookie settings.

### Step-29 closing summary

**What was built.** A private Hugging Face ZeroGPU Space,
`Omar-Mohsen22/support-ticket-router-demo`, shows TF-IDF (CPU) and the fine-tuned Qwen2.5-1.5B
adapter (GPU) side by side on a ticket.
- **Examples:** 6 test tickets, with their gold labels shown. Three are agreement cases, and
  three are the label-noise cases from `reports/error_analysis.md`.
- **Error-analysis note:** the page links the error analysis and says the test labels are noisy.
- **Model:** the adapter runs the evaluated inference config, 4-bit NF4 with double quant,
  unmerged, with float16 compute. It is loaded inside every `@spaces.GPU` call, because 4-bit
  quantization needs a real GPU. The weights are pre-downloaded at startup.
- **Reused code:** the demo reuses the project's own modules (`build_ticket_text`,
  `build_system_message`, `load_model_and_tokenizer`, `render_prompt`, `generate_batch`,
  `parse_and_validate`) and the committed TF-IDF artifact. They are copied into the Space at
  deploy time, not rewritten.

**Deploy.**
- The `deploy-demo` CI job runs on pushes to master, after the `docker` job passes. It assembles
  the bundle (17 files plus a generated `examples.json`), uploads it with `delete_patterns`, waits
  for a build stage and then RUNNING, and smoke-tests `/classify` through `gradio_client` with a
  masked token.
- The Space secret `HF_TOKEN` (read-only on the adapter repo) was set once, with
  `deploy_demo.py --set-secret`.

**Results.**
- **Evaluated 4-bit config, full test split:** the demo matched the published adapter predictions
  on **1,623 / 1,633 (99.39%)**, with macro-F1 within 0.003 on every field. Its one invalid output
  is the same ticket as in the published run (`reports/adapter_zerogpu_4bit_full.md`).
- **First bf16 setup:** bf16 base, adapter merged, batch 16. It matched only 72.63% and scored
  lower on every field (`reports/adapter_zerogpu_agreement.md`).
- **Hardware ruled out:** 4-bit on Blackwell matched the T4. The bf16 gap comes from precision,
  merging and/or batch size, and was not isolated further (`reports/adapter_zerogpu_4bit.md`,
  400-ticket run).
- **Headline tables unchanged.** The README's headline tables remain the published evaluation.
  The new "Demo" section reports the agreement numbers separately.

**Durations** (sized from measured 4-bit latencies): single ticket 20 s; `predict_batch`
`20 + 3 x ceil(n / 8)` s, with at most 96 tickets per call.

**GPU:**
- 2026-09-27: 234.1 s conservative, against a 10-minute cap.
- 2026-09-28: 500.8 s conservative through the full run (this counts the previous day's
  234.1 s too, to be safe), against a 20-minute cap.
- The $2 credits were never touched; every call stayed inside the free PRO daily quota.
- The smoke test of the push that closes this step is reported with the push, not in this entry.

**Temporary branch.** The 4-bit probe endpoint lived only on branch `probe/4bit-zerogpu`
(commit `629c12c`, pushed so the report's reference stays reachable). Its worktree was removed
with `git worktree remove`, and the branch was kept.

**Files added or changed in step-29:**
- New: `deploy/demo/` (`app.py`, `requirements.txt`, `README.md`, `deploy_demo.py`,
  `measure_agreement.py`, `measure_4bit.py`) and `requirements-dev.txt`.
- Changed: `.github/workflows/ci.yml` (the `deploy-demo` job) and `deploy/space/deploy_space.py`
  (a `space_id` parameter).
- New reports: `reports/adapter_zerogpu_agreement.*`, `reports/adapter_zerogpu_4bit.*` and
  `reports/adapter_zerogpu_4bit_full.*`.
- Changed: `README.md` (the "Demo" section, and the Limitations "Serving" bullet) and
  `PROGRESS.md`.

**Verify with:**
```
python deploy/demo/deploy_demo.py --dry-run
python deploy/demo/measure_4bit.py --report
python deploy/demo/measure_4bit.py --run probe400 --report
python deploy/demo/measure_agreement.py --report
```
or push to master and read the `deploy-demo` job's summary.

**Next step:** the UI redesign (TODO above; the options are reviewed visually first), or the
go-public checklist. Omar's call.

## step-30: demo UI redesign (approved design: Option A, Eta AI colors)

**What changed.** The UI only. No inference code, config or prediction changed.

**New `deploy/demo/ui.py`** holds the layout, CSS and card rendering. It imports no torch, so the
same UI runs on the Space and locally.
- **Fonts and colors:** IBM Plex Sans and Mono. Orange `#F4521A` for the Classify pill (19px
  bold, white text) and "one ticket" in the H1. Purple `#6D28D9` for the fine-tuned card, its
  badge, the ✓ marks and links. Small orange text is `#c2410c` on `#fff1eb`.
- **Header:** "SUPPORT TICKET ROUTER", "Three models, one ticket", the subtitle, and links to
  Results, Error analysis and Code.
- **Left column:** the input card and "Try a test ticket". The 6 examples are full-width buttons
  showing the ticket id, or a "noisy label" pill for the three label-noise cases. The selected
  example gets a purple border.
- **Right column:**
  - A dark gold-label strip, shown for examples only.
  - Three equal-height cards in one CSS grid, with the label above each value:
    - **TF-IDF:** badge `CPU · <ms>`.
    - **Fine-tuned Qwen2.5-1.5B:** badge `ZeroGPU · 4-bit · <s>`. It shows "Running on
      ZeroGPU…" until the adapter returns; the events are chained with `.success()`.
    - **gpt-4o-mini:** badge `zero-shot · stored result`. For free text it shows "Available
      for examples only.".
  - A ✓ or ✗ against the gold label, for examples only.
- **Notes:** the noisy-label note stays visible. The gpt-4o-mini note and the
  inference-config / 1,623-of-1,633 note sit in a collapsed "About this demo", with the same text
  as before.
- **Layout:** the page is centered (max-width 1240px), and the columns and cards stack on narrow
  screens.
- **Light theme pinned:** the page forces Gradio's light theme with `?__theme=light`.

**gpt-4o-mini.** The stored zero-shot labels come from
`results/api-gpt4o-mini-full-test.predictions.jsonl`. `deploy_demo.py` copies them into
`examples.json` for the 6 example tickets only; the full file is not bundled, no API is called,
and the Space has no OpenAI key.

**API unchanged.**
- The visible UI's events use `api_visibility="private"` and `show_progress="hidden"`, so they
  add no endpoints and Gradio's overlay does not cover the loading card.
- `/classify` (subject, body -> table, timing) and `/predict_batch` (payload) keep the same
  names, inputs and response shapes, on hidden components wired to app.py's unchanged
  `classify()` and `predict_batch()`. This was checked with `view_api` on the local preview.
- `app.py` changed only in its UI section, which now calls `build_demo()`.

**Local preview.**
- `deploy/demo/preview_ui.py` runs the UI with the real TF-IDF and a stub adapter (fixed labels
  after 3 s). It needs `gradio==6.28.0`, which the project venv does not have.
- For step 30 it ran from a venv under `.scratch/step30/`, a new gitignored folder for scratch
  work (`.gitignore`: `.scratch/`). The screenshots were taken there with Playwright over two
  review rounds: an example selected, a noisy-label example, free text, the loading state, and a
  390px mobile width.
- Nothing under `.scratch/` is committed.

**Go-public checklist:** a new item (above). The page's GitHub links 404 for everyone else while
the repo is private.

**Files changed:** `deploy/demo/ui.py` (new), `deploy/demo/preview_ui.py` (new),
`deploy/demo/app.py` (UI section only), `deploy/demo/deploy_demo.py` (bundles `ui.py`; the
examples gain `gold_labels`, `noisy` and `gpt4o_mini`), `.gitignore`, `PROGRESS.md`.

**Verify with:** `python deploy/demo/deploy_demo.py --dry-run` (18 files plus examples.json).
Run `python deploy/demo/preview_ui.py` from an environment that has gradio 6.28.0, or push to
master and read the `deploy-demo` job's summary.

**Next step:** Omar's call. Options: the go-public checklist, or other demo work.

### step-30 follow-up: live styling fix and three custom tickets

**Finding: the Space renders server-side, so our CSS lost there.**
- The live page looked different from the local preview:
  - the ✓/✗ marks, the fine-tuned badge text and the kicker were dark grey;
  - the nav links were blue and underlined;
  - the TF-IDF card had no border.
- The matched CSS rules (Chrome DevTools Protocol, no GPU call) showed the cause:
  - Hugging Face Spaces run Gradio in SSR mode. There, `demo.css` is a plain `<style>` in
    `<head>`, before Gradio's stylesheets, and is not rewritten into the higher-specificity copy
    the client-rendered page adds.
  - Two rules in Gradio's `_app/immutable/assets/0.*.css` then win:
    - `.gradio-container-6-28-0 .prose *` sets `color: var(--body-text-color)`;
    - `.gradio-container-6-28-0 .prose a` sets the link color and underline;
  - and the preflight reset `.gradio-container-6-28-0 *` sets `border-width: 0`.

**Fix.**
- The whole UI sits in `gr.Column(elem_id="tr-root")`, and every rule of ours is scoped
  `#tr-root ...`. The ID outranks those class selectors.
- `!important` is gone inside the UI. It stays only on Gradio's own `.gradio-container`, on the
  footer, and on the mobile `width`/`min-width` that must beat Gradio's inline `min-width`.
- Gradio's orange theme accent variables are mapped to purple inside `#tr-root`.
- **Checked:** computed styles of 111 elements were compared with the approved
  (client-rendered) design, for a test example, a noisy example, a custom ticket and a 390px
  width. There were 0 differing values, in both SSR and non-SSR mode.

**Local preview matches the Space.**
- `python deploy/demo/preview_ui.py --ssr` renders server-side, as the Space does. It serves the
  same hashed Gradio stylesheets.
- It needs Node.js 20+, via `GRADIO_NODE_PATH` (Node v22.12.0 was used, from
  `.scratch/step30/node`, not part of the repo), and `PYTHONIOENCODING=utf-8` on Windows.

**Custom tickets.**
- Three tickets Omar wrote (`custom-1` to `custom-3` in `deploy_demo.py`) follow the 6 test
  tickets.
- Each shows a neutral "custom" pill, with no gold strip and no ✓/✗.
- TF-IDF and the adapter run live. The gpt-4o-mini card says "Stored results exist for
  test-set tickets only." No API is called.
- A line under the list says they are not in the dataset and have no gold label.

**Go-public checklist:** two new items (above): the API Space "/" redirect, and an incognito
check with default third-party-cookie settings.

**Files changed:** `deploy/demo/ui.py`, `deploy/demo/preview_ui.py`, `deploy/demo/deploy_demo.py`,
`PROGRESS.md`.

**Verify with:** `python -m pytest -q` (26 passed); `python deploy/demo/deploy_demo.py --dry-run`
(9 examples); `python deploy/demo/preview_ui.py --ssr` from an environment with gradio 6.28.0 and
Node.js.

**Next step:** Omar's call.

### step-30 follow-up: HF_SPACE_TOKEN rotated (2026-10-20)

**Why.**
- Two scratch scripts used for the live-styling diagnosis (`diag_live.py` and `cdp_live.py`,
  never committed) set the token with Playwright's `extra_http_headers`.
- That attaches the header to every request the page makes. A load of the live page requests
  four hosts: the Space's `*.hf.space` host, `huggingface.co`, `fonts.googleapis.com` and
  `fonts.gstatic.com`.
- So the token reached Google's font servers, over HTTPS.

**Done.**
- Omar created a new `HF_SPACE_TOKEN`, put it in `.env` and in the GitHub secret, and will
  delete the old one on Hugging Face.
- The two scripts were deleted.
- The committed scripts send the token only through `huggingface_hub`, `gradio_client` or
  `deploy_space.request()`, to `huggingface.co` or the Space's own `*.hf.space` host.

**Rule.** Attach HF tokens only to `*.hf.space` and `huggingface.co` requests. In a browser,
use a per-request route that checks the host, never a page-wide header such as
`extra_http_headers`.

## step-31: go-public, stage A (code changes while everything is still private)

**Old token deleted.** On 2026-10-21 Omar deleted the rotated-out `HF_SPACE_TOKEN`
(`ticket-router-space-deploy`) on Hugging Face. The leaked value no longer works. The scripts
that leaked it attached only `HF_SPACE_TOKEN`; `HF_TOKEN` was never sent as a header. This was
checked against every version of the two scripts in the session transcript.

**Changes.**
- **`/predict_batch` removed** from the demo (Omar's decision), with everything only it used:
  - in `app.py`: `predict_batch()`, `adapter_generate_batch()`, `batch_duration()`,
    `BATCH_BASE_S`, `BATCH_PER_8_S` and `MAX_BATCH`;
  - the hidden batch components in `ui.py`;
  - the stub in `preview_ui.py`.

  `/classify` is now the demo's only API endpoint. It stays public (Omar's decision: the UI and
  the CI smoke test use it).
- **Measure scripts marked historical.** `measure_agreement.py` and `measure_4bit.py` say they
  depended on the removed endpoints and that their results are preserved in `reports/`.
  - `--report` still rebuilds every report from the saved outputs, with no Space call.
  - Note: a rebuild is not byte-identical to the committed reports. The full and agreement
    reports differ only in "Run status: report rebuilt from saved outputs". The probe400 report
    also has older wording, with the same numbers. The committed reports were left unchanged.
- **API Space:** `GET /` now redirects (307) to `/docs`. It is left out of the OpenAPI schema
  and covered by a new test, `test_root_redirects_to_docs`.
- **Smoke test message:** "counts toward the step-29 cap" became "counts toward the ZeroGPU
  quota".
- **Demo Space card (`deploy/demo/README.md`):**
  - it credits the dataset (Tobi-Bueck/customer-support-tickets, CC-BY-NC-4.0) as both the
    training data and the source of the example tickets, and says the three custom tickets are
    Omar's;
  - its stale facts were fixed: it now mentions the stored gpt-4o-mini output and says "1,623 of
    1,633" instead of "399 of 400".

**Files changed:** `deploy/demo/app.py`, `deploy/demo/ui.py`, `deploy/demo/preview_ui.py`,
`deploy/demo/measure_agreement.py`, `deploy/demo/measure_4bit.py`, `deploy/demo/deploy_demo.py`,
`deploy/demo/README.md`, `src/ticket_router/api/app.py`, `tests/test_api.py`, `PROGRESS.md`.

**Verify with:**
- `python -m pytest -q` (27 passed);
- CI green on push;
- `gradio_client` `view_api()` on the demo lists only `/classify`;
- `curl -I https://omar-mohsen22-support-ticket-router.hf.space/` with the token returns `307`
  and `location: /docs`.

**Next step:** stage B, read-only: a secret scan of the full history (gitleaks plus grep), a
review of the Actions logs, the list of files the demo Space exposes, and a sensitive-content
review list. No visibility flips.

### step-31: stage B (read-only review) and follow-up decisions

**Secret scan: clean.**
- gitleaks 8.21.2 (a standalone binary under `.scratch/`, checksum verified against the
  release; not a project dependency) found 0 leaks over the full history of:
  - the GitHub repo (61 commits, `--all`);
  - the demo Space repo (11 commits);
  - the API Space repo (3 commits);
  - the adapter model repo.
- A grep of `git log -p --all` for `hf_`, `sk-`, `ghp_` and `github_pat_` found 0 hits.
- The Actions logs of all 18 runs show every secret masked (`***`). They contain no token, email
  or local path.

**Sensitive-content review.** Omar reviewed the list:
- `CLAUDE.md` stays as is;
- the billing lines in this file stay as is;
- history is not edited.

**`HEAD /` on the API.** The route also answers HEAD, so `curl -I /` gets the 307 to `/docs`,
not a 405. `test_root_redirects_to_docs` covers HEAD.

**API Space bundle: kept as is (Omar's decision).**
- The Space runtime needs only `src/`, `models/tfidf/` and `label_map.json`. This was checked by
  serving `/health`, `/predict` and `/` from a copy with only those files.
- The Docker build also needs `results/results.json` (the gold-hash check). The bundled parquet
  files are regenerated by `make_dataset.py` during the build anyway.
- The bundle still keeps `tests/`, `results/` and the parquet files, with one Dockerfile,
  because the image CI tests is the image the Space runs.

**Recorded retroactively on 2026-10-21: the decision to stop training after step 19.**
- Step 19's entry is diagnosis only. It left the next decision to Omar, and no later entry
  recorded it.
- The decision Omar made after reading `reports/error_analysis.md`: stop tuning the model.
- The reason: the fine-tuned adapter and the architecturally unrelated TF-IDF baseline fail on
  the same tickets and usually pick the same wrong label. That points at the labels, not at model
  capacity, so further tuning was not expected to close the gap.
- No training was run after step 19.

**README: new "How I built this" section,** after "Data and licensing". It discloses the AI
assistance once for the whole project, explains why commits are authored by Omar, and lists the
main decisions with their step numbers.

**Files changed:** `src/ticket_router/api/app.py`, `tests/test_api.py`, `README.md`,
`PROGRESS.md`.

**Verify with:**
- `python -m pytest -q` (27 passed);
- CI green on push;
- `curl -I https://omar-mohsen22-support-ticket-router.hf.space/` with the token returns `307`
  and `location: /docs`.

**Next step:** Omar's call. Stage C, the visibility flips in the planned order: the GitHub repo,
the adapter repo, the API Space, then the demo Space.
