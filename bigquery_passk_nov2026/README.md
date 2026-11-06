# BigQuery pass@k results, 6 Nov 2026

Model Qwen3.6-35B-A3B, Spider 2.0-Lite BigQuery split, 204 questions. Full write-up: documents/bigquery_alignment_rerun.md

- `1_greedy_run_R/` - the first run (temperature 0, gated rubric, row-count check): `all.csv` (204 rows) and `traces/`. 97 correct (47.5%).
- `2_retry_1/` ... `2_retry_4/` - four retries at temperature 0.7 of only the 107 questions run R got wrong (same rubric and row-count check): `all.csv` (107 rows) and `traces/`. Correct: 20, 23, 27, 21.
- `combined_per_question.csv` - one row per question: greedy result, each retry result (blank for questions greedy already solved, which were not retried), number of retries correct, and `solved_any`. 139 of 204 (68.1%) solved by any attempt.

`score` is 1 for correct. Because only greedy failures were retried, 68.1% is a "solved by any attempt" figure and not the accuracy of a single answer.
