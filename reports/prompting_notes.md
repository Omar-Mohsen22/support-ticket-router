# Step 05: few-shot prompting notes

Three variants of `src/ticket_router/predictors/api_predictor.py` (`--variant coverage`,
`coverage-priority`, `coverage-median`), same model (gpt-4o-mini), same full test split (1,633
rows), same harness. This report was revised twice after the initial two-variant run: once to fix a
methodology gap (how rate-limited rows were scored), once to add Variant C and remove a selection
confound from Variant A/B. Three variants total, as instructed for the final round -- this is a
measurement of whether prompting closes a gap, not a search for the best prompt.

## Methodology correction (closed before adding Variant C)

**Exactly how the 429-failed rows were being scored, stated plainly**: they were **not dropped**.
Every gold test row stays in the evaluation denominator regardless of prediction outcome --
`evaluate.py` assigns a sentinel value to any id with no valid prediction, which can never equal a
real label, so a failed row is **counted as incorrect on every field** (and contributes to
`invalid_rate`), never excluded from `n`. So `n=1,633` was identical across every run -- but which
*specific* tickets got a genuine model prediction differed: 6 different tickets auto-scored wrong in
Variant A, 33 different (mostly, not necessarily entirely, overlapping) tickets in Variant B. Same
row *count*, different row *identities* -- that's the gap that needed closing.

**Root cause confirmed**: inspected every failed row's `error` field in both variants -- **100% were
`RateLimitError` (429)**, zero were JSON-parse or schema-validation failures. Longer few-shot
prompts (more tokens/request) pushed the run closer to the account's per-minute token budget under
the original `CONCURRENCY_LIMIT=5`.

**Fix, in `api_predictor.py`:**
1. **`CONCURRENCY_LIMIT` lowered from 5 to 3.** Variant B (the longest prompt) averaged ~963
   tokens/request at ~1.37s/request; at concurrency 5 that's ~211,000 tokens/minute against a
   200,000 TPM account limit -- over budget, which is exactly what produced the 429s. At
   concurrency 3: ~127,000 tokens/minute, comfortably under budget.
2. **Rate-limit retries separated from content-validation retries.** Previously a 429 could consume
   one of a ticket's 3 total content-attempts, so 3 unlucky 429s in a row meant a permanently failed
   ticket. Now `call_with_cache()` retries `RateLimitError` in its own dedicated loop (up to 10
   attempts, exponential backoff capped at 60s) that never touches the content-retry budget.
3. **Stale error cache entries are purged automatically** (`purge_error_cache_entries()`, run at the
   start of every real invocation) -- an error was never a valid answer, so nothing legitimate is
   lost, and a transient failure can no longer be silently replayed forever as if it were final.

**Re-ran Variant A and B** (`--variant coverage` / `coverage-priority`, same run names -- the ~1,600+
already-successful rows per run replayed free from cache; only the previously-failed 6 and 33 rows
made fresh calls). Both reached **0 failures, invalid_rate 0.00%, 1,633/1,633 valid** this time.

One visible side-effect of the fix, worth naming rather than leaving unexplained: Variant C's p95
latency is 27.6 seconds (`results/comparison.md`) -- far above every other run's. This is the
dedicated rate-limit backoff loop actually doing its job on a small number of requests near the
tail of a long, token-heavy run (median examples produce a bigger prompt than shortest examples),
trading latency for the "no row left without a prediction" guarantee. It is not a sign of anything
wrong with those specific predictions -- once a retried call succeeds, it's scored exactly like any
other successful call.

**Corrected numbers for both affected runs** (before -> after; queue/priority/type = macro-F1):

| run | queue | priority | type | exact-match | invalid-rate |
|---|---|---|---|---|---|
| A: coverage -- before | 0.2442 | 0.3135 | 0.4319 | 6.86% | 0.37% |
| A: coverage -- **after** | 0.2445 | 0.3136 | 0.4327 | 6.86% | **0.00%** |
| B: coverage-priority -- before | 0.2241 | 0.3224 | 0.4710 | 6.92% | 2.02% |
| B: coverage-priority -- **after** | 0.2287 | 0.3246 | 0.4738 | 7.04% | **0.00%** |

The movement is small in every case (the failed rows were <2% of the split either way) -- the
original qualitative story for A/B did not change. But it is no longer an estimate with an asterisk:
every run from this point on, including Variant C below, is scored on the exact same 1,633 rows with
a genuine model prediction for all of them.

## What each variant changed

**Variant A (`coverage`)**: 10 few-shot examples added to every prompt, one per queue class.
Selection rule: for each of the 10 queue classes, the training row with the **shortest `text`**
(ties broken by lowest `id`).

**Variant B (`coverage-priority`)**: Variant A's examples, plus a one-sentence description per
`priority` value, derived empirically (Laplace-smoothed relative-word-frequency ratio against the
other two values, words appearing in >=20 training tickets of that value -- a keyness/log-odds-style
analysis, not hand-written). The three sentences (verbatim, unchanged from the original run since
the derivation doesn't depend on rate limits): `high` -> severe, timeouts, major, reverting,
rolling, overloads, outage, reliability, interruption, ceased, interrupted, capacity. `low` -> com,
lack, providers, browser, feature, low, commitments, finds, utmost, value, long, delay. `medium` ->
demonstrate, scope, app, organizations, modifying, knowing, transaction, lately, compatible, month,
predictions, conflicting.

**Variant C (`coverage-median`) -- new this round, to remove a confound**: identical to Variant A in
every respect except the selection rule picks the **MEDIAN-length** training example per queue class
(index `len(subset)//2` after ascending sort by length, same lowest-id tie-break). Reasoning this
was built to test: Variant A's shortest-example rule was chosen to keep the prompt small, but the
shortest tickets are plausibly the least typical and least informative -- so "few-shot made it
worse" (Variant A/B's finding) might have been an artifact of that rule, not a property of few-shot
prompting itself. The two sets of examples are visibly different in kind, not just length -- e.g.
Variant A's `Human Resources` example is the single sentence *"Can you provide details on
integrating data analytics with FL Studio?"* (18-69 chars across all 10 examples); Variant C's is a
full multi-sentence ticket body (384-450 chars across all 10 examples) describing an actual incident.
Full example sets: `results/few_shot_examples_shortest.json`, `results/few_shot_examples_median.json`.

## Effect on macro-F1 per field (all runs on the same 1,633 rows, invalid-rate 0.00% throughout)

| run | queue F1 | priority F1 | type F1 | exact-match |
|---|---|---|---|---|
| zero-shot (step-04) | 0.2554 | 0.3214 | 0.5209 | 10.90% |
| A: coverage (shortest few-shot) | 0.2445 | 0.3136 | 0.4327 | 6.86% |
| B: coverage-priority (A + priority defs) | 0.2287 | 0.3246 | 0.4738 | 7.04% |
| **C: coverage-median (median few-shot)** | **0.2399** | **0.3330** | **0.6687** | **9.06%** |
| tfidf-baseline (reference) | 0.3683 | 0.5445 | 0.8412 | 29.33% |
| random-baseline (reference) | 0.1110 | 0.3427 | 0.2577 | 2.20% |

(Full per-class breakdowns for every run: `results/comparison.md`, `results/results.json`.)

**The confound was real.** Variant C (median examples) beats both A and B on every field, and beats
*zero-shot* on `priority` and, substantially, on `type`:
- **`type`**: 0.5209 (zero-shot) -> 0.6687 (Variant C) -- a genuine, large improvement. This closes
  roughly (0.6687-0.5209)/(0.8412-0.5209) = **46% of the gap to TF-IDF** on this field.
- **`priority`**: 0.3214 -> 0.3330 -- a small but real improvement (unlike A/B, which were flat or
  worse), though still far below TF-IDF's 0.5445.
- **`queue`**: 0.2554 -> 0.2399 -- still slightly worse than zero-shot, the one field where more
  few-shot examples (of any selection rule tried) did not help.

## Which errors persisted

**`priority = low` was 0/345 recall in zero-shot, Variant A, and Variant B alike** -- the model
never once predicted `low` in any of those three. **Variant C breaks this, barely**: recall rises
from 0.0000 to 0.0058 (2/345), precision 0.14 -- still a near-total miss in practical terms, but no
longer *literally* zero. That the example-selection rule moves this at all (where explicitly stating
the empirical `low`-priority vocabulary in Variant B moved it not at all) suggests example
typicality matters more here than explicit definitions do -- though neither comes close to fixing
it. Compare TF-IDF's `low` recall of 0.24 (F1 0.363) -- still far ahead.

## Verdict: with the confound removed and every run on identical rows, does few-shot help, hurt, or nothing -- and does it close the gap to TF-IDF?

**All three, depending on the field -- stated plainly, field by field:**

| field | zero-shot -> best variant | which variant | direction | gap to TF-IDF closed? |
|---|---|---|---|---|
| queue | 0.2554 -> 0.2399 | C | **hurts** (-6.1% relative) | No |
| priority | 0.3214 -> 0.3330 | C | **helps, modestly** (+3.6% relative) | No -- still <20% of the way to 0.5445 |
| type | 0.5209 -> 0.6687 | C | **helps, substantially** (+28.4% relative) | **Partially -- ~46% of the gap closed** |

Few-shot prompting is not uniformly good or bad here -- it depends both on *what* is being predicted
and on *which examples* are shown. The original two-variant finding ("prompting doesn't help, and
sometimes hurts") was partly a real property of `queue` and partly an artifact of the
shortest-example selection rule for `type` and, more weakly, `priority`. With that confound removed:
`type` sees a real, substantial gain that meaningfully narrows the TF-IDF gap; `priority` sees a
small real gain that leaves the gap almost entirely open; `queue` gets worse regardless of which
few-shot rule is tried. **No variant of few-shot prompting tried here closes the gap to TF-IDF on any
field** -- TF-IDF remains ahead on all three, by a wide margin on `queue` and `priority` and a
still-substantial one on `type`, even after the best-performing prompt variant.

Step-04c's leakage check already established that TF-IDF's advantage is genuine signal, not
near-duplicate leakage. This step's conclusion sits alongside that one: for `type`, a better-chosen
few-shot prompt recovers a meaningful share of what TF-IDF is picking up on; for `priority` and
`queue`, whatever TF-IDF is learning from 13,070 labelled examples was not successfully communicated
to the LLM by any of the three prompts tried, including one that stated the relevant vocabulary
outright.

**Stopping after three variants, as instructed** -- this is the last prompting attempt in this
step; no further iteration.
