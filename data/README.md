# Data card: ticket-router training data

## Source

- Hugging Face dataset: [`Tobi-Bueck/customer-support-tickets`](https://huggingface.co/datasets/Tobi-Bueck/customer-support-tickets)
- License: **CC-BY-NC-4.0** (Creative Commons Attribution-NonCommercial 4.0) -- **non-commercial use only**.
- The tickets in this dataset are **synthetic** (LLM-generated), not real customer correspondence.

## Which file was used, and why

Only `data/raw/aa_dataset-tickets-multi-lang-5-2-50-version.csv` (28587 rows) is used by `src/ticket_router/make_dataset.py`. The other two files downloaded during step-01 are excluded:

- **dataset-tickets-german_normalized_50_5_2.csv**: German-only, and its `queue` values are a different, incompatible taxonomy (42 topic-style classes, e.g. 'Pets & Animals/Pet Services') from the 10-class queue taxonomy in the chosen file -- combining them would mean training against two different label spaces.
- **dataset-tickets-multi-lang-4-20k.csv**: Same schema as the chosen file, but its overlap with the chosen file has not been verified. Combining unverified-overlap sources risks the same ticket (or a near-duplicate) landing in two different splits (train/val/test), which would leak information across the split boundary.

## Preprocessing decisions (in pipeline order)

1. **Language filter**: kept only rows with `language == "en"` -- 16338 / 28587 rows (57.15%). Reason: the chosen file mixes English and German tickets under the same queue taxonomy; this pipeline builds an English-only model and the German rows are set aside rather than mixed in.

2. **Queue row-count gate**: after the language filter, every one of the 10 queue classes still had at least 100 rows (smallest: General Inquiry with 236), so the pipeline proceeded instead of stopping. See the per-class counts below.

3. **Label values read from the data**, not the dataset card: the card lists `critical` as a possible priority, but it does not occur anywhere in this file -- only `['high', 'low', 'medium']` are used. `type` values: `['Change', 'Incident', 'Problem', 'Request']`. All 10 `queue` values are kept, none merged or dropped.

4. **Row drop (empty body / null target)**: 0 rows dropped (0 for empty/null `body`, 0 for a null `queue`/`priority`/`type`; a row counted in both is not double-counted in the total). In this file, after the English filter, that total was 0 -- body and all three target fields were fully populated.

5. **`text` field**: `subject + "\n" + body`, except when `subject` is null (2607 rows, 15.96% of the cleaned data) where `text` is `body` alone. A boolean `has_subject` column records which case applied for each row, so the substitution is auditable rather than silent.

6. **Exact-duplicate removal on `text`**: 0 rows removed (0.00% of the pre-dedup cleaned data). This is within the expected range (step-01 found 0 duplicates on `body` alone across the whole file).

7. **Stratified split**: 80/10/10 train/val/test, stratified on `queue`, fixed seed `42`. Splitting is done independently within each queue class so every class keeps its ~80/10/10 proportions in every split, rather than risking a class landing disproportionately in one split by chance.

8. **Row order shuffled within each split** (membership unchanged): building a split by concatenating one queue class's rows after another leaves each split grouped by class, so `df.head(n)` on a split is a slice of one class, not a sample of the split. Fixed at the source with `.sample(frac=1, random_state=...)` per split, seeded from `SPLIT_SEED = 42` fresh for each split (independent of dict iteration order). Which split an id belongs to is exactly the same as before this step -- only row order changes.

9. **Stable `id`**: assigned from each row's position in the raw source CSV (`tkt_000000`, `tkt_000001`, ...) before any filtering, so an id always traces back to the same source row across re-runs. Verified programmatically that no id appears in more than one split.

10. **Columns kept in the output**: `id`, `subject`, `body`, `text`, `has_subject`, `language`, `queue`, `priority`, `type`. The source file's `answer`, `version`, and `tag_1..tag_8` columns are dropped -- they are not needed for the queue/priority/type routing targets this dataset is built for.

## Row counts per split

| split | rows | pct_of_total |
| --- | --- | --- |
| train | 13070 | 80.00% |
| val | 1635 | 10.01% |
| test | 1633 | 10.00% |
| TOTAL | 16338 | 100.00% |

## Label distribution per split

### queue

| value | train | val | test |
| --- | --- | --- | --- |
| Billing and Payments | 1276 | 160 | 159 |
| Customer Service | 1928 | 241 | 241 |
| General Inquiry | 189 | 23 | 24 |
| Human Resources | 278 | 35 | 35 |
| IT Support | 1554 | 194 | 194 |
| Product Support | 2458 | 308 | 307 |
| Returns and Exchanges | 656 | 82 | 82 |
| Sales and Pre-Sales | 410 | 52 | 51 |
| Service Outages and Maintenance | 531 | 67 | 66 |
| Technical Support | 3790 | 473 | 474 |

### priority

| value | train | val | test |
| --- | --- | --- | --- |
| high | 5066 | 624 | 656 |
| low | 2675 | 354 | 345 |
| medium | 5329 | 657 | 632 |

### type

| value | train | val | test |
| --- | --- | --- | --- |
| Change | 1360 | 190 | 155 |
| Incident | 5254 | 651 | 666 |
| Problem | 2721 | 340 | 336 |
| Request | 3735 | 454 | 476 |

## Known limitations

The split is stratified on `queue` only, so `priority` and `type` proportions are preserved only approximately, not exactly. For example, `type = Change` has 1,705 rows total and lands 1,360 / 190 / 155 across train/val/test instead of an exact 1,364 / 170 / 170 -- roughly a 10% relative deviation for that class.

This was accepted rather than fixed: re-splitting to satisfy three targets (queue, priority, and type) at once would either break the queue stratification this split is built around, or require multi-label stratification, and the deviation is small enough that it should not change conclusions drawn from evaluation. So that a reader can judge that for themselves, per-class support (row count) will be reported next to every metric in the evaluation output, not just the metric value alone.

## Reproduce

Activate the virtual environment, then run the script with a platform-neutral `python`:

```
# Windows (PowerShell / cmd)
.venv\Scripts\activate
python src/ticket_router/make_dataset.py

# Unix (macOS / Linux)
source .venv/bin/activate
python src/ticket_router/make_dataset.py
```

Requires `data/raw/aa_dataset-tickets-multi-lang-5-2-50-version.csv` to already be present (downloaded by `src/ticket_router/inspect_data.py`). Deterministic given a fixed source file and `SPLIT_SEED = 42`.
