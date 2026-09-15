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
