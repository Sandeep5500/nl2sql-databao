# BigQuery pass@4 (full), 17 Nov 2026

Model `Qwen/Qwen3.6-35B-A3B` (bf16, Modal H200), Spider 2.0 Lite comprising **204 questions**.

Four independent temperature 0.7 lanes over **all 204 questions each** a clean pass@4. Config per lane is a gated output-shape rubric reused from `results/full_C/rubrics`, `--rubric-row-check` on, no BigQuery stats, 60 steps,
`context_mode=full`.

Driven by `nl2sql-v2/scripts/analysis/run_arm.py`, 2 waves of 2 concurrent lanes (agent loop local, only model calls to Modal).

## Results

| lane | correct (of 204) |
|---|---:|
| `lane_k1` | 103 |
| `lane_k2` | 94 |
| `lane_k3` | 99 |
| `lane_k4` | 96 |

- **pass@1 (mean of 4 samples) = 98.0 / 204 = 48.0%**
- **pass@4 (solved by any of 4) = 129 / 204 = 63.2%**

- Per-question lane agreement: 75 solved by none, 19 by one, 21 by two, 25 by three, 64 by all four so **65 contested questions** (1–3 of 4 lanes right).

- BigQuery scanned 7.4 TiB (~$46). No infrastructure errors
  (773 submitted, 43 step-limit fallbacks, across 816 episodes).

## Layout

```
lane_k1/ lane_k2/ lane_k3/ lane_k4/   each: all.csv + traces/bqNNN.json (204 each)

combined_per_question.csv      one row per question: per-lane 0/1, n_correct, solved_any
```

- `all.csv` columns: `instance_id, db, score, score_detail, status, steps, critic_rounds,
search_calls, draft_calls, wall_seconds, sf_queries, sf_seconds, scan_bytes, sql`. `score` is 1 for correct. 

- Each `traces/bqNNN.json` is the full tool-call trace; the submitted query's preview is in it (the judge pipeline reads the preview, it does not re-run SQL).
