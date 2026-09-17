# TF-IDF near-duplicate leakage check

Every one of the 1633 test rows' TF-IDF vector (same config as `tfidf_baseline.py`) compared by cosine similarity against all 13070 train rows' vectors. Exact duplicates across splits were already ruled out in step-02 (dedup on `text` before splitting); this checks near-duplicates, which dedup on exact text cannot catch but which can leak just as effectively for synthetic, template-generated tickets.

## Max-similarity distribution

Each test row's similarity to its single closest train row:

| statistic | value |
| --- | --- |
| min | 0.1650 |
| median (p50) | 0.6539 |
| p90 | 0.8721 |
| p95 | 0.9016 |
| max | 1.0000 |

## Rows exceeding similarity thresholds

| threshold | count | pct_of_test |
| --- | --- | --- |
| > 0.9 | 88 | 5.39% |
| > 0.95 | 18 | 1.10% |
| > 0.99 | 5 | 0.31% |

## 5 most similar train/test pairs

Full ticket text for each, one after another (not literal side-by-side columns -- markdown tables can't hold full ticket text legibly) so they can be read and compared directly.

### Pair #1 -- similarity = 1.0000

**TEST** `tkt_006245` (queue=`Technical Support`, priority=`high`, type=`Incident`):

```
Several products are impacted.
```

**TRAIN** `tkt_005423` (queue=`Technical Support`, priority=`high`, type=`Incident`):

```
Several products are impacted
```

### Pair #2 -- similarity = 1.0000

**TEST** `tkt_010545` (queue=`Product Support`, priority=`high`, type=`Problem`):

```
Recent unauthorized access to medical data systems is due to outdated security protocols.
```

**TRAIN** `tkt_019087` (queue=`Product Support`, priority=`high`, type=`Problem`):

```
There has been recent unauthorized access to our medical data systems due to outdated security protocols.
```

### Pair #3 -- similarity = 1.0000

**TEST** `tkt_003363` (queue=`IT Support`, priority=`high`, type=`Problem`):

```
Concern with SaaS Platform Performance Today
The platform is slow due to high server load.
```

**TRAIN** `tkt_006146` (queue=`IT Support`, priority=`high`, type=`Problem`):

```
Concern About SaaS Platform Performance Today
The platform is slow because of high server load.
```

### Pair #4 -- similarity = 1.0000

**TEST** `tkt_004641` (queue=`Technical Support`, priority=`high`, type=`Request`):

```
Customer Support, I am reaching out to inquire about best practices for securing medical data within healthcare environments using Cassandra 4.0. Could you please provide guidance on this topic? I would appreciate any information you can share. Thank you for your time and assistance. I look forward to hearing from you soon.
```

**TRAIN** `tkt_001231` (queue=`Technical Support`, priority=`high`, type=`Request`):

```
Customer Support, I am reaching out to inquire about best practices for securing medical data in healthcare environments using Cassandra 4.0. Could you please provide guidance on this topic? I would appreciate any information you can share. Thank you for your time and assistance. I look forward to hearing from you soon.
```

### Pair #5 -- similarity = 1.0000

**TEST** `tkt_009538` (queue=`Technical Support`, priority=`medium`, type=`Incident`):

```
A healthcare provider encountered a possible data breach impacting several devices, potentially due to network misconfiguration involving the Ubiquiti UniFi Dream Machine. Devices have been restarted and firmware updated, but the problem remains unresolved. Assistance is needed to address this issue.
```

**TRAIN** `tkt_009516` (queue=`Technical Support`, priority=`medium`, type=`Incident`):

```
A healthcare provider encountered a possible data breach impacting several devices, potentially due to a network misconfiguration involving the Ubiquiti UniFi Dream Machine. The devices have been restarted and their firmware updated, but the problem remains unresolved. Assistance is needed to address the issue.
```

## macro-F1: all test rows vs. only low-similarity test rows

Recomputed from `results/tfidf-baseline.predictions.jsonl` (not retrained), restricted to the 1545 / 1633 test rows whose nearest-train-neighbour similarity is below 0.9 -- **this is the number that decides whether step-04b's headline result is real signal or leakage.**

| field | macro_f1_all_test | macro_f1_low_sim_only | n_all | n_low_sim |
| --- | --- | --- | --- | --- |
| queue | 0.3683 | 0.3558 | 1633 | 1545 |
| priority | 0.5445 | 0.5316 | 1633 | 1545 |
| type | 0.8412 | 0.8325 | 1633 | 1545 |

## Verdict

- **queue**: all-test=0.3683, low-sim-only=0.3558, random-baseline=0.0996 -> holds well above random -- consistent with real signal.
- **priority**: all-test=0.5445, low-sim-only=0.5316, random-baseline=0.3163 -> holds well above random -- consistent with real signal.
- **type**: all-test=0.8412, low-sim-only=0.8325, random-baseline=0.2444 -> holds well above random -- consistent with real signal.

**All three fields hold up on the low-similarity subset.** The headline step-04b result is real: TF-IDF is learning genuine signal from the ticket text, not memorizing near-duplicate training tickets. The comparison against the zero-shot LLM baseline stands.