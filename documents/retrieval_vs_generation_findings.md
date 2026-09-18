# Retrieval vs generation: findings

**Date:** 2026-09-18 · **Model:** Qwen3.5-9B, v2 harness · **Scope:** Spider 2.0-Lite local split, 135 SQLite questions

**Data:** the five published runs in `logs/traces/` (greedy `v2_armAplus` plus the four sampled lanes
`v2_pass4_k1`–`k4`), re-executed and re-scored with the current `nl2sql/eval.py`. Stored scores in the
trace files predate the three Sept 17 scoring fixes and were not used.

---

## Headline

**Retrieval is not the bottleneck.** When the model fails a question it can solve on another attempt, it
already had the right tables 98% of the time. Three quarters of failures are pure logic errors with every
table and column correct.

| Failure type | Pairs | Share |
|---|---|---|
| Never found a table the answer needs (true retrieval) | 2 | 2% |
| Right table, wrong column (column linking) | 30 | 25% |
| Right tables and columns, wrong logic (generation) | 90 | 74% |

Scope limit: this covers the 62 questions the model solves on at least one run. It says nothing about the
58 questions no run has ever solved. See "Open questions".

---

## 1. Paired analysis — the primary evidence

### Method

For every question where the **same model** both succeeded and failed across the five runs, compare the
winning query against each losing query. Same model, same question, same prompt, different sample — so
there is no prompt-perturbation confound and no selection bias about which questions are compared.

- 62 questions qualify: 30 from bucket B (greedy lost, a lane won) and 32 from bucket A (greedy won, a
  lane lost). Bucket C has no winning run to compare against.
- Each question contributes one pair per failing run: **174 raw pairs**, about 2.8 per question.
- **51 removed** as unfinished episodes (status `fallback`: hit the 30-step cap and submitted whatever
  exploratory query ran last), and **1 removed** because its query touches no real table.
  **122 clean pairs remain.**
- The winner's tables and columns are taken as ground truth for what a correct answer needs.

### Examples

**Right table, wrong column — `local031` (Brazilian_E_Commerce)**

> What is the highest monthly delivered orders volume in the year with the lowest annual delivered
> orders volume among 2016, 2017, and 2018?

Both queries use only `olist_orders`. The winner buckets by **delivery** date; the failure buckets by
**purchase** date. Both columns sit side by side in the same table. (The failure also drops `LIMIT 1`.)

```sql
-- CORRECT
SELECT CAST(SUBSTR(order_delivered_customer_date, 1, 4) AS INTEGER) AS year,
       CAST(SUBSTR(order_delivered_customer_date, 6, 2) AS INTEGER) AS month,
       COUNT(*) AS monthly_count
FROM olist_orders
WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL
  AND CAST(SUBSTR(order_delivered_customer_date, 1, 4) AS INTEGER) = 2016
GROUP BY year, month ORDER BY monthly_count DESC LIMIT 1

-- FAILED
SELECT SUBSTRING(order_purchase_timestamp, 1, 4) AS year,
       SUBSTRING(order_purchase_timestamp, 6, 2) AS month,
       SUM(CASE WHEN order_status = 'delivered' THEN 1 ELSE 0 END) AS monthly_delivered_orders
FROM olist_orders
WHERE SUBSTRING(order_purchase_timestamp, 1, 4) = '2016'
GROUP BY year, month ORDER BY monthly_delivered_orders DESC
```

**Right tables and columns, wrong logic — `local264` (stacking)**

> Which model category (L1_model) appears the most frequently … and what is the total count?

The failure computes exactly the right counts, then stops. It returns every category instead of the top one.

```sql
-- CORRECT
SELECT L1_model, COUNT(*) AS count FROM model GROUP BY L1_model ORDER BY count DESC LIMIT 1

-- FAILED
SELECT L1_model, COUNT(*) AS cnt FROM model GROUP BY L1_model
```

**Same pattern — `local329` (log)**

> How many unique sessions visited /regist/input and then /regist/confirm, in that order?

The failure has the right join and the right ordering condition, and returns the list of sessions instead
of counting them.

```sql
-- CORRECT (abridged)
... SELECT COUNT(DISTINCT i.session) AS unique_sessions
    FROM input_times i JOIN confirm_times c ON i.session = c.session
    WHERE c.confirm_time > i.input_time

-- FAILED
SELECT DISTINCT f1.session
FROM form_log f1 JOIN form_log f2 ON f1.session = f2.session
WHERE f1.path = '/regist/input' AND f2.path = '/regist/confirm' AND f2.stamp > f1.stamp
```

`local264` and `local329` share a shape worth naming: **correct computation, wrong final answer shape.**
This is exactly what the output-contract arm targets.

**Looks like retrieval, is not — `local019` (WWE)**

> For the NXT title that had the shortest match (excluding title changes), what were the names of the two
> wrestlers involved?

The winner joins `matches`, `belts` and `wrestlers`. The failure's final query uses only `wrestlers`:

```sql
SELECT name FROM Wrestlers WHERE id IN (41653, 44396)
```

Those hardcoded IDs could only have come from querying `matches` earlier in the episode. The model found
the tables, picked the wrong match, and submitted a shortcut. This is a logic failure that the final SQL
alone disguises as retrieval.

**True retrieval failures — only two exist**

Checking every tool call and result in each episode, not just the final SQL:

| "Missed a table" pairs | Count |
|---|---|
| Model touched the missing table during the episode, then left it out | 18 |
| Model never encountered the table anywhere | 2 |

The two: `local023` never found `wicket_taken`; `local054` never found `invoices`.

---

## 2. The official gold SQL is not trustworthy

Spider2 ships answer-key SQL for only 24 of the 135 local questions. Executing each and scoring it with
our own scorer:

| Gold SQL executed through | Scores correct |
|---|---|
| Our agent's DuckDB path | 9 of 24 |
| Raw SQLite | 16 of 24 |
| Fails both paths | 8 of 24 |
| Works in SQLite, fails in DuckDB | 7 of 24 |

- **7 are dialect-only failures.** Mainly `julianday` (absent in DuckDB), plus a rounding syntax error,
  VARCHAR/INTEGER mixing, a circular CTE reference, and stricter GROUP BY. The linkage in these is fine.
- **8 answer a different question than the graded CSV.** Column counts, row counts, or values disagree.
  `local029`: gold SQL averages **7.08** where the gold CSV has **58.62** (one aggregates per customer,
  the other does not). `local210`: gold SQL returns **1** column, the CSV has **6**.
- The gold **CSV** is the graded artifact and is the one to trust. On `local210` our agent matched the
  CSV while the benchmark's own gold SQL does not.
- **One gold SQL is nondeterministic.** `local219` scores correct on only about 2 in 20 identical
  executions. A query can return different rows on different runs (LIMIT over tied rows, window
  functions without an ORDER BY), so a single execution is not a reliable verdict. Only official SQL
  that passes on every repeat is used as an oracle source.

**Consequence:** `build_oracle_context.py` parses these files to build the original arm C. For about a
third of its 24 questions, arm C injected linkage for the wrong query. The original "generation is the
bottleneck" verdict rested partly on a corrupted arm. Section 1 now supports that verdict on far better
evidence.

---

## 3. The scorer is looser than it looks

`eval.py` ports the official Spider2 comparison. It compares **values, never SQL**. Correct for the
leaderboard; dangerous when "scored correct" is used as a training label or an oracle source.

| Property | Questions affected |
|---|---|
| Row order ignored — each column sorted **independently**, so row pairing is never checked | 135 of 135 |
| Several gold answers accepted (`local003_a.csv` … `_d.csv`) | 91 of 135 |
| Only some gold columns graded (`condition_cols`) | 49 of 135 |
| Gold answer is a single number (1×1) | 33 of 135 |

Also: extra predicted columns are free; numeric tolerance is **absolute** 0.01; missing values compare
as 0.

**Example — `local003`:** grading rule `{"condition_cols": [0], "ignore_order": true}`. Only the segment
name column is graded. The average sales figure the question actually asks for is never checked.

**Example of independent sorting:** if the answer pairs A→1 and B→2, returning A→2 and B→1 still passes,
because each column sorts to the same list on its own.

---

## 4. Question buckets

Every question falls into one bucket based on which of the five runs solved it.

| Bucket | Definition | Questions |
|---|---|---|
| A | Greedy already solves it | 47 |
| B | Greedy fails; at least one sampled lane solved it | 30 |
| C | All five runs failed | 58 |

An experiment that adds help can only show an effect on questions the model currently fails.

- **A is useless** for any ablation: solved with or without help.
- **B is noisy.** Per-lane pass rates on the 21 usable B packages: 11 at 1/4, 3 at 2/4, 7 at 3/4. A blind
  redraw with no help wins **9.5 of 21**. An oracle arm must clear about **14 of 21** (2σ) to mean anything.
- **C is the clean test.** Null is essentially zero. **Read every ablation on bucket C.**

---

## 5. Sampling raises the ceiling, not the score

| Strategy | Score |
|---|---|
| Greedy (what we ship) | 47 / 135 |
| Execution-consistency vote across the 5 runs | 50 / 135 |
| Perfect selection (union ceiling) | 77 / 135 |

Voting recovers **3 of the 30** available points. On **61 of 135** questions all five runs returned
different results; only 5 had all five agree. (These agreement counts can shift by one between
executions, because some predicted queries are themselves nondeterministic.) The model is not confidently wrong, it is unstable, so
there is no majority to vote for.

Implications:
- High-K sampling is an excellent **offline** data generator (the gold CSV verifies each sample for free).
- It is not an **online** strategy: on a new question nothing points at the correct sample.
- Closing the gap needs a **verifier** that judges correctness, not a vote that counts recurrence.
- The wide pass@K spread confirms GRPO will have positive rollouts to learn from.

---

## 6. Linkage coverage

| Stage | Questions |
|---|---|
| Verified, parseable SQL held (9 official + 69 from our runs) | 78 |
| After dropping 1×1 scalar answers | 57 |
| After requiring the SQL to touch the value-swept table | 53 |
| Usable for the ablation (buckets B + C) | **22** (21 B, 1 C) |

Official SQL is preferred when it passes on every repeated execution. Otherwise, when several runs
solved a question, the greedy run's SQL is the representative. 31 of the 53 are in bucket A and so
cannot show an ablation effect.

**Value sweep** (`scripts/build_free_context.py`): traces gold answer values back to the column storing
them. Covers **72** of 135 (52 answers are pure numbers, 11 matched nothing). Averages 1.7 tables per
question with **41% table recall** against trustworthy gold SQL. It finds the output table, never the
join or filter tables. Only **10 of 30** databases declare foreign keys (178 across 418 tables), so FK
closure alone cannot recover joins.

Given Section 1, the sweep's weakness matters less than it appeared: the model already finds the tables.

---

## 7. Mistakes made during this analysis — do not repeat

1. **Counting unfinished episodes as retrieval failures.** `fallback` episodes submit the last exploratory
   query, which usually touches one table. Exclude them.
2. **Counting SQL aliases as columns.** sqlglot reports `count`, `cnt`, `total_income` as columns. Filter
   extracted names against the real schema. This inflated "wrong column" from 30 to 93.
3. **Judging retrieval from the final SQL alone.** A table can be found and deliberately omitted. Check
   every tool call and result in the trace. This took "retrieval" from 24% to 2%.
4. **Trusting stored scores.** Re-score from stored SQL with the current scorer.
5. **Pooling buckets.** Pooled numbers dilute any real effect toward zero. Report A, B, C separately.
6. **Assuming one execution is a verdict.** Some queries return different rows on different runs.
   `local219`'s gold SQL passes about 2 times in 20. Repeat before trusting a single pass.

---

## 8. What was built

| File | Purpose |
|---|---|
| `nl2sql-v2/scripts/build_free_context.py` | Builds both gold-SQL-free context files from the gold CSVs |
| `nl2sql-v2/contract_context.json` | Output contract per question — 135 entries |
| `nl2sql-v2/sweep_context.json` | Value-sweep linkage — 72 entries |
| `nl2sql-v2/scripts/run_benchmark.py` | New `--context-mode contract / sweep / sweep_contract`; new `--shard I/N` |
| `nl2sql-v2/src/nl2sql/agent.py` | Contract keeps retrieval on; linkage arms turn it off |
| `nl2sql-v2/slurm/serve_vllm_qwen35.slurm` | Removed hardcoded user paths; portable across users |
| `nl2sql-v2/scripts/analysis/` | The six scripts that reproduce every number in this document |

---

## 9. Reproducing these numbers

Every number above is produced by a script in `nl2sql-v2/scripts/analysis/`. Run from `nl2sql-v2/`:

```
uv run python scripts/analysis/buckets.py            # Section 4  — writes logs/analysis/buckets.json
uv run python scripts/analysis/paired_failures.py    # Section 1  — add --examples 2 for SQL examples
uv run python scripts/analysis/gold_sql_check.py     # Section 2  — add --repeats 20, --diagnose
uv run python scripts/analysis/scorer_audit.py       # Section 3  — needs no stored runs
uv run python scripts/analysis/vote.py               # Section 5
uv run python scripts/analysis/linkage_funnel.py     # Section 6
```

The first run re-executes all 675 stored queries (a few minutes) and caches the scores in
`logs/analysis/rescore_cache.json`. The cache discards itself whenever `eval.py` or `db.py` change.

To analyse the new arms once they finish, pass their trace directories. A glob merges an arm's shards
into one run, and bucket membership always comes from the five Phase-0 runs:

```
uv run python scripts/analysis/paired_failures.py --runs 'v2_armAplus,arm_contract_*'
```

---

## 10. Open questions and next steps

- **Arm 1 (output contract), 135 questions — still worth running.** Two of the three logic-failure
  examples were correct computations with the wrong final shape, which is what the contract supplies.
  Baseline to beat: 47. Read it on bucket C.
- **Arm 2 (value sweep), 72 questions — now close to a foregone conclusion.** It supplies tables the model
  already finds 98% of the time. Optional; run only as independent confirmation.
- **Placebo arm on bucket C.** Inject an uninformative block of similar length to measure how much a
  changed prompt flips outcomes on its own. About 1,050 calls, ~2 h at 4 lanes.
- **The 58 never-solved questions are the unresolved part.** The paired method cannot reach them. They
  may fail for different reasons than the questions within reach.
- **A verifier is the highest-return next build.** Labels are free (execution against gold CSV), it is a
  ranking problem, and it targets the 30-point gap sampling already exposes.
