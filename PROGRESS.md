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

**Next step:** step-05 — not started yet (to be defined).
