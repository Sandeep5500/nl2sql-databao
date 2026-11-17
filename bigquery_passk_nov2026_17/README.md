# BigQuery pass@4 (full), 17 Nov 2026

Model `Qwen/Qwen3.6-35B-A3B` (bf16, Modal H200), Spider 2.0-Lite BigQuery split, **204 questions**.
Four independent temperature-0.7 lanes over **all 204 questions each** — a clean pass@4, unlike the
earlier `bigquery_passk_nov2026/` package.

Config per lane (the "R" config from `documents/bigquery_alignment_rerun.md`): gated output-shape
rubric reused from `results/full_C/rubrics`, `--rubric-row-check` on, no BigQuery stats, 60 steps,
`context_mode=full`. Driven by `nl2sql-v2/scripts/analysis/run_arm.py`, 2 waves of 2 concurrent
lanes (agent loop local, only model calls to Modal).

## Results

| lane | correct (of 204) |
|---|---:|
| `lane_k1` | 103 |
| `lane_k2` | 94 |
| `lane_k3` | 99 |
| `lane_k4` | 96 |

- **pass@1 (mean of 4 samples) = 98.0 / 204 = 48.0%**
- **pass@4 (solved by any of 4) = 129 / 204 = 63.2%**
- Per-question lane agreement: 75 solved by none, 19 by one, 21 by two, 25 by three, 64 by all four
  — so **65 contested questions** (1–3 of 4 lanes right).
- BigQuery scanned 7.4 TiB (~$46, `cost_center=rohini`). No infrastructure errors
  (773 submitted, 43 step-limit fallbacks, across 816 episodes).

### How this differs from `bigquery_passk_nov2026/`

That package was **greedy run R + 4 retries of only the 107 questions greedy got wrong** (5 attempts,
retries chosen with the answer key), giving a "solved by any attempt" figure of 68.1%. That is a
different quantity from pass@4 and is not comparable to SQLite. **This package is the honest 4-sample
pass@4** and is the figure to set beside SQLite's `Qwen3.6-35B` temp-0.7 numbers (pass@1 47.4% base /
51.1% rich describe; pass@4 69.6% of 135).

## Layout

```
lane_k1/ lane_k2/ lane_k3/ lane_k4/   each: all.csv + traces/bqNNN.json (204 each)
combined_per_question.csv             one row per question: per-lane 0/1, n_correct, solved_any
```

`all.csv` columns: `instance_id, db, score, score_detail, status, steps, critic_rounds,
search_calls, draft_calls, wall_seconds, sf_queries, sf_seconds, scan_bytes, sql`. `score` is 1 for
correct. Each `traces/bqNNN.json` is the full tool-call trace; the submitted query's preview is in it
(the judge pipeline reads the preview, it does not re-run SQL).

## Feeding the judge pipeline (`nl2sql-v2/scripts/bq_judge_pools.py`)

That script hardcodes the retry+greedy layout:

```python
LANES = ["2_retry_1", "2_retry_2", "2_retry_3", "2_retry_4", "1_greedy_run_R"]
```

For this package (4 symmetric full lanes, no greedy baseline) change that one line to:

```python
LANES = ["lane_k1", "lane_k2", "lane_k3", "lane_k4"]
```

then run with `--base bigquery_passk_nov2026_17`. Everything else (`--questions bq_questions.jsonl`
with `instance_id, question, doc`; the pairwise / `jev_choice` judge flags) is unchanged. With 4 full
lanes every question forms a 4-candidate pool, so the ~65 contested questions here are a much larger
design/test set than the 28 contested pools the retry-only layout gave.
