# Retrieval vs generation: findings

**Date:** 2026-09-18 (updated 05:30 with the overnight runs) · **Model:** Qwen3.5-9B, v2 harness; Qwen3.6-27B as teacher · **Scope:** Spider 2.0-Lite local split, 135 SQLite questions

**Data:** the five published runs in `logs/traces/` (greedy `v2_armAplus` plus the four sampled lanes
`v2_pass4_k1`–`k4`), re-executed and re-scored with the current `nl2sql/eval.py`. Stored scores in the
trace files predate the three Sept 17 scoring fixes and were not used.

---

## Summary

- **Retrieval is a real but narrow bottleneck; generation dominates everywhere.** Two independent
  methods now agree, on the questions the 9B can reach and on the ones it never solves.
- **Questions within the 9B's reach** (62 it both solved and failed across runs): when it fails, it is
  2% never finding a needed table, 25% picking the wrong column, 74% wrong logic with everything right.
- **Never-solved questions** (57, or 58 on one machine, see Section 8): a Qwen3.6-27B teacher produced
  verified gold SQL for 14 of them.
- **Handing the 9B the correct tables and columns on those 14** lifts its mean pass rate from 7.1% (decoy)
  to 17.9% (oracle): +10.7 points, 95% CI [-3.6, +28.6]. Inconclusive on its own at n=14.
- **But the whole gain sits on 3 questions** that an analysis computed *before* the arms ran had flagged as
  genuine retrieval failures: 6/12 runs vs 0/12. On the other 11, where the 9B already found every table,
  correct linkage changed nothing: 4/44 vs 4/44.
- **Those retrieval failures are near-misses**, not lost schema: a sibling table in a 29-table database
  (`constructor_standings`), or the one table that holds the right identity key (`customers` for
  `customer_unique_id`).
- **Even with retrieval handed over, the 9B mostly fails the hard tail:** 9% pass rate on the 11 unflagged
  questions. Of its 46 failed runs, a third ignored the tables or columns it was explicitly given, 13%
  missed a join key (composite keys, semantic links), and 39% ran out of steps without ever producing the
  answer.
- **Telling it to use the given tables does not fix this.** An explicit instruction cut runs that skipped a
  named table from 8 to 0 but added only 2 correct runs of 56 (+3.6 points, CI [-7.1, +14.3]). It used
  the tables without understanding why: `local004` now joins `customers` every time and still groups by
  the per-order ID.
- **Selection is the gap on the reachable questions, and a validator captures much of it:** greedy gets 47
  of 135 while perfect selection over 4 samples would give 72. Agreement voting recovers 3 points, but a
  prompted validator that judges the four candidates gets **55 (9B) or 59 (27B)**, with no training. On
  the 29 questions where only one candidate is right, it finds it 45-59% of the time against 25% by chance.
- **The benchmark's own artifacts need care:** 8 of the 24 shipped gold SQLs answer a different question
  than the graded CSV; the scorer ignores row pairing on all 135; 52 of 675 stored queries return
  different results run to run.

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

Scope limit: this covers the 62 questions the model solves on at least one run. Section 7 extends the
analysis to the questions no run had ever solved, using a larger model to supply correct answers.

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

### 5.1 A validator agent recovers about half the gap

Voting fails because it counts agreement. A validator *judges*: show a model the question, its
documentation, and the four candidates (SQL + result shape + first rows), and have it pick one. Candidate
order is shuffled per question, and which candidate is correct is never shown. One model call per
question, no training, nothing re-executed (`validator_select.py` over `validator_inputs.json`).

| Strategy | Correct |
|---|---|
| Pick one run at random | 41 / 135 |
| Greedy (what we ship) | 47 |
| Execution-consistency vote | 50 |
| **Validator, Qwen3.5-9B** | **55** (45% of the headroom) |
| **Validator, Qwen3.6-27B** | **59** (58% of the headroom) |
| Perfect selection | 72 |

The 9B judging its own four outputs beats its own greedy run, 55 to 47.

| Questions where | Count | 9B | 27B | random |
|---|---|---|---|---|
| only 1 of 4 candidates correct | 29 | 13 | 17 | 7.2 |
| 2 of 4 correct | 9 | 9 | 9 | 4.5 |
| 3 of 4 correct | 19 | 18 | 18 | 14.2 |
| none correct | 63 | 0 | 0 | 0 |

The first row carries the result: where voting cannot help by construction, the judge finds the single
correct answer 45% (9B) and 59% (27B) of the time against 25% by chance.

Not an artifact: it picks the longest SQL 29-30% of the time (25% by chance), candidate order is shuffled
per question so position skew cannot inflate accuracy, and the two judges agree on 83 of 135 questions.
Unparsed replies fall back to the first candidate (1 for the 9B, 3 for the 27B).

Caveat: "correct" is the scorer's verdict, so a candidate that matched by luck counts as correct here too.

### 5.2 Thinking on: neither better candidates nor better selection

Run 2026-09-24. The original environment was rebuilt on Babel first (vector index copied over, Ollama
installed for query-time embeddings, `--context-mode search` with the schema overview, temperature 0.7,
Qwen3.5-9B), because the earlier runs used semantic retrieval in 79-88 of 135 episodes. Then 4 runs with
thinking on, reasoning stored per step and the per-call output budget raised to 8192, plus 1 control with
thinking off to detect stack drift.

| Runs | Accuracy per run (of 135) | pass@4 |
|---|---|---|
| Original lanes (thinking off, earlier stack) | 39, 38, 41, 46 | 72 |
| **Control (thinking off, this stack)** | **37** | - |
| **Thinking on (this stack)** | **44, 37, 32, 40** (mean 38.3) | **67** |

Read this within-stack: thinking averages 38.3 against the control's 37, so **no gain**, with wide spread
(32 to 44). The control also lands 1-4 points below the original lanes, so the 67-versus-72 comparison
mixes the change with stack drift and should not be read as thinking hurting.

Thinking was real and substantial: every step carried reasoning, 9,000-16,000 characters per episode,
about 2,700 reasoning-bearing steps per run. It cost step budget, though: episodes ending at the 30-step
cap rose from 34/135 (control) and 38/135 (original) to **44-48 per run**.

Validator over this thinking-on pool (ceiling 67, random pick 38.3):

| Prompt | Correct | Headroom captured |
|---|---|---|
| Results only | **51** | 44% |
| + reasoning from its final steps | 49 | 37% |
| + full reasoning, 6k chars per candidate | 48 | 34% |

Paired: none to final-step gains 6 and loses 8 (p=0.79); none to full gains 3 and loses 6 (p=0.51). The
judge's pick changed on 53-60 of 135 questions, so the reasoning is being read, it just does not help.

**Conclusion.** Chain-of-thought is not the missing ingredient for selection, the same direction as the
narration result in 5.1. And thinking did not make the student more accurate in this harness. Judging the
*result* remains the thing that works; a trained verifier is still the open lever.

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

## 7. The never-solved questions: teacher run and oracle ablation

The paired method in Section 1 needs a correct run to compare against, so it could not reach bucket C.
The overnight runs on 2026-09-18 supplied one, then tested the question directly on the 9B.

### 7.1 A 27B teacher supplies verified gold SQL

Qwen3.6-27B (the model the plan picks for fine-tuning) ran the same harness on the never-solved
questions, with the output contract in its prompt to maximise yield. It is a data generator here, so its
solve rate is not comparable to the 9B's. A query became gold SQL only if it scored correct on every one
of three repeated executions, had an answer larger than one number, and touched the table the value sweep
found (where one exists).

| Pass | Mode | Attempted | Scored correct | Verified gold SQL |
|---|---|---|---|---|
| 1 | swept tables + output contract | 29 | 13 | **12** |
| 1b | full schema + output contract | 15 | 2 | **2** |
| 1c | single-number answers | 12 | 7 | 0 (not eligible) |

14 verified packages, all in bucket C, in `nl2sql-v2/teacher_context.json`. Re-harvesting the pulled traces
on a second machine gives the identical 14.

### 7.2 Cross-model paired analysis

Same method as Section 1, but the winning query is the 27B's and the failing ones are the 9B's.

| | Pairs | Share |
|---|---|---|
| Never found a table the 27B's query needs | 7 | 16% |
| Right tables, wrong column | 13 | 29% |
| Right tables and columns, wrong logic | 25 | 56% |

45 clean pairs from 13 questions, after removing 30 unfinished (step-cap) episodes: 40% of raw pairs,
against 29% on the reachable questions. Pairs cluster by question, so per question: **3 of 13** had at
least one run that never found a needed table, **10 of 13** had every needed table in every failing run.
One question, `local335`, supplies 4 of the 7 retrieval pairs.

### 7.3 Oracle vs decoy on the 9B

The 9B (vLLM 0.19, 4 runs per arm: greedy plus 3 at temperature 0.7) on the 14 verified questions.

- **Oracle:** the verified query's tables described up front, plus the columns it touches.
- **Decoy:** the same kind of block, never shorter (median 1.14x the oracle's length), naming tables the
  query does not use, and framed neutrally so it does not assert they are correct.

Search is off in both arms and neither gets the output contract, so the only difference is whether the
named tables are right.

| | Oracle | Decoy |
|---|---|---|
| Greedy run solves | 2 / 14 | 0 / 14 |
| Solved in at least one of 4 runs | 7 / 14 | 3 / 14 |
| Mean pass rate per question | 17.9% | 7.1% |
| Episodes that hit the 30-step cap | 19 / 56 | 20 / 56 |

Effect of correct linkage: **+10.7 points, 95% CI [-3.6, +28.6]**. Oracle beats decoy on 6 questions, the
decoy wins on 3, 5 tie.

| Question | Oracle | Decoy | | Question | Oracle | Decoy |
|---|---|---|---|---|---|---|
| local004 | 1/4 | 0/4 | | local133 | 1/4 | 0/4 |
| local062 | 0/4 | 0/4 | | local170 | 1/4 | 2/4 |
| local073 | 0/4 | 0/4 | | local201 | 1/4 | 0/4 |
| local075 | 0/4 | 1/4 | | local286 | 0/4 | 0/4 |
| local096 | 1/4 | 0/4 | | local311 | 1/4 | 0/4 |
| local130 | 0/4 | 1/4 | | **local335** | **4/4** | **0/4** |
| local131 | 0/4 | 0/4 | | local360 | 0/4 | 0/4 |

### 7.4 The two methods agree

Split the ablation by the retrieval flags from 7.2, which were computed before either arm finished:

| Questions | Count | Oracle | Decoy | Gap |
|---|---|---|---|---|
| Flagged: in its own runs the 9B never found a needed table | 3 | 6/12 (50%) | 0/12 (0%) | **+6** |
| Not flagged: the 9B already had every needed table | 11 | 4/44 (9%) | 4/44 (9%) | **0** |

Correct linkage helps exactly where the 9B failed to find a table, and there it helps a lot. Where the 9B
already had the tables, handing them over gains nothing, and the 9B still fails 91% of runs.

The flagged failures are near-misses:

- **`local335`** (f1, 29 tables): missed `constructor_standings` in 4 of 5 runs. Oracle 4/4, decoy 0/4.
- **`local004`** (E_commerce): missed `customers` in 2 of 5 runs, the only table holding
  `customer_unique_id`, which separates a person from an order. The plan already names this confusion.
- **`local311`** (f1): missed `results` in 2 of 5 runs.

### 7.5 Why the 9B still fails with the correct linkage

46 of the 56 oracle runs failed. `oracle_failures.py` diffs each failed query against the teacher's
verified query and assigns the first cause that applies. Examples in every category were read by hand;
two artifacts found that way were fixed (below).

| Cause | Runs | Share |
|---|---|---|
| **1) Ignored what it was given** | **15** | **33%** |
| &nbsp;&nbsp;left out a table the prompt named | 8 | |
| &nbsp;&nbsp;left out a column the prompt listed | 7 | |
| **2) Joins**: used the tables, missed a join key the correct query uses | **6** | **13%** |
| **3) Anything else** | **25** | **54%** |
| &nbsp;&nbsp;ran out of its 30 steps | 18 | |
| &nbsp;&nbsp;right columns, wrong row count (grouping or filtering) | 4 | |
| &nbsp;&nbsp;too few output columns | 2 | |
| &nbsp;&nbsp;right shape, wrong values | 1 | |

**1) Ignoring explicit hints is common.**
- `local004`: in all 3 failed runs the final query skips `customers` and groups by the per-order
  `customer_id`. Two of those runs never mention `customers` in any tool call; the third describes it once
  and moves on. The one successful run uses `customers` in 8 of its 11 tool calls.
- `local133`: skipped `musical_styles`, returned style IDs instead of names, and hardcoded an average (4.05).
- `local130`: identified English classes by `CategoryID`, which was not listed, instead of the listed
  `SubjectCode`.
- `local131`: ignored `PreferenceSeq`, so it never split counts into 1st, 2nd and 3rd choice.

**2) Join failures are semantic, not foreign-key discovery.**
- `local062`: every run joins `costs` exactly once. Three of four join it on 2 of its 4 key columns
  (`prod_id`, `time_id`, without `promo_id`, `channel_id`). `costs` holds one row per product, day,
  promotion and channel, so the two-column key matches up to 7 rows (2.27 on average) and each sale is
  counted several times:

  | Italian customers, Dec 2021 | Rows after join | Total profit |
  |---|---|---|
  | joined on all 4 columns (correct) | 689, one per sale | 11,423.84 |
  | joined on 2 columns (9B) | 1,999 | 36,375.39 (3.2x) |

  `promo_id` and `channel_id` **were in the prompt's column list.** The 9B had them; nothing said they form
  the join key, and per-column distinct counts cannot show that `(prod_id, time_id)` is not unique. So
  this overlaps with category 1 as much as it is a join problem.

  All four runs also bucket with `NTILE(10)` (equal numbers of customers) where the question asks for
  "ten equal intervals" of the profit range. That is why run 2 failed with the correct join, and why
  fixing the join alone would rescue none of the four.
- `local075`: never linked purchase events back to products through `visit_id`.

**3) Running out of steps is non-convergence, not error loops.** The 18 step-cap episodes run 27 queries
each on average; 78% execute fine, there are about 2 exact repeats per episode, and the history never
overflowed. Only 2 of the 18 ever ran a query that scores correct without submitting it (`local201` at SQL
call 12, `local360` at call 24). In the other 16 it never produced the answer at all, so an in-episode
verifier would rescue little here.

**Artifacts fixed during the check.**
- *Extra tables are not counted as a cause.* The given list is what the teacher needed to pass the scorer,
  which can be less than the question asks: `local286`'s gold answer has review-score and packing-time
  columns, but only 5 of its 7 columns are graded, so the teacher skipped `order_reviews` and `orders` and
  the 9B was right to use them. 4 runs used tables beyond the list.
- *Join keys count only real schema columns.* Otherwise a comparison between two computed values
  (`pre_count = min_pre_count` in `local360`) reads as a join.

Caveats: one cause per run, although a run can have several faults (`local062` also buckets by `NTILE`
where the question implies equal-width ranges); and the classification is structural, so treat counts as
approximate.

### 7.6 Telling it to use the tables fixes compliance, not correctness

Category 1 above suggests a cheap fix: tell the model to use the tables. `oracle_forced` is the oracle
block word for word plus "your final query must use each of these tables; check before submitting"
(columns stay hints). Same 14 questions, 4 runs, same stack, run 2026-09-18.

| | Oracle | Forced | Decoy |
|---|---|---|---|
| Runs that left out a table the prompt named | 8 | **0** | - |
| Runs that left out a listed column | 7 | 12 | - |
| Join failures | 6 | 3 | - |
| Ran out of steps | 18 | 19 | - |
| Correct runs (of 56) | 10 | **12** | 4 |
| Mean pass rate | 17.9% | 21.4% | 7.1% |

Forced vs oracle: **+3.6 points, 95% CI [-7.1, +14.3]**. Forced vs decoy: +14.3, CI [+0.0, +32.1].

The instruction removes table non-use entirely, yet adds only 2 correct runs. The per-question view shows
why:

- **Where skipping a table was the only obstacle, forcing it works.** `local133`: 1/4 -> 3/4. Made to use
  `musical_styles`, it returns style names instead of IDs.
- **Where the model does not understand why a table matters, forcing it does nothing.** `local004`: all 4
  forced runs now use `customers` (1 of 4 before) but still group by the per-order `customer_id` instead of
  the person-level `customer_unique_id`. 1/4 -> 0/4. This is where the rise in unused columns comes from.

So most category-1 failures were a symptom of not understanding the question and schema, not of ignoring
instructions. Prompting is not a large lever; the bottleneck remains generation.

### 7.7 Caveats

- **Small n.** 14 questions, 3 flagged, and `local335` supplies 4 of the 6 gained runs. The split in 7.4
  was chosen after noticing `local335`, although the flags themselves predate the arm results. Confirm on
  more questions before relying on it.
- **Selection.** The 14 are the never-solved questions a 27B could solve with the output contract in hand:
  the easier end of the hard tail. 43 bucket-C questions have no verified answer yet.
- **Cross-model reference.** The flags and linkage use the 27B's query as ground truth; another valid query
  might use different tables.
- **The oracle misses lookup tables.** Its table list is parsed from the teacher's *final* query, so a
  table used only to look up a constant drops out. `local062` filters on `country_id = 52770` (Italy),
  found in `countries` during exploration and then hardcoded; `countries` is not in the list. Harmless there
  (all four 9B runs found it themselves) but it can make the oracle look more complete than it is.
- **The oracle conveys which columns, not how they are used.** The column list is flat: join keys, filters
  and outputs are not distinguished (see `local062`).
- **Search was off** in both arms because Ollama and the vector index are not set up on Babel. The enriched
  column descriptions it returns could help the oracle arm, so its effect may be understated.
- **Stack.** Both arms ran on vLLM 0.19, so the oracle/decoy comparison is internal. Absolute rates are not
  directly comparable to Phase-0, which used 0.18.1. Preemptions moved the arms across GPU types
  (A100, L40S and others), and greedy decoding can differ slightly across hardware.

---

## 8. Reproducibility: nondeterminism and running on Babel

**Nondeterminism.** 52 of the 675 stored Phase-0 queries return different results across 5 executions
(`determinism.py`). None flipped its score in 5 executions, but rare flips exist: `local003`'s greedy query
returns 9, 10 or 11 rows and matches gold only on the 9-row result, about 1 run in 15. That is why bucket
counts are 47/30/58 on one machine and 48/30/57 on another, with byte-identical databases (checked by
MD5) and the same DuckDB version. `local219`'s official gold SQL passes about 2 runs in 20.

**Running on Babel — what bit us overnight:**
- The `preempt` partition requeues preempted jobs. With `--resume` and per-question traces, 10 preemptions
  across 5 jobs lost no finished work. Jobs were also preempted *after* finishing, during model-server
  shutdown; the requeued copy found nothing left to do and exited.
- `--resume` crashed when a preemption left a lane's CSV empty and the next restart appended rows with no
  header. Fixed: the header is flushed at once and empty or headerless files are handled.
- Two vLLM servers on one node must use different ports, or the second fails to start.
- Qwen3.6-27B needs vLLM 0.19 **and** transformers 5.5.3. vLLM 0.19 pulls transformers 4.57.6, which does
  not know the `qwen3_5` model type. It lives in its own `.vllm-venv-0.19` so the 9B setup is untouched.
- `sbatch` reads job scripts on the login node, which cannot see `/data/user_data`. Keep job scripts in the
  home directory and point jobs at the repo with `--chdir`.

---

## 9. Mistakes made during this analysis — do not repeat

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

## 10. What was built

| File | Purpose |
|---|---|
| `nl2sql-v2/scripts/build_free_context.py` | Builds both gold-SQL-free context files from the gold CSVs |
| `nl2sql-v2/contract_context.json` | Output contract per question — 135 entries |
| `nl2sql-v2/sweep_context.json` | Value-sweep linkage — 72 entries |
| `nl2sql-v2/scripts/run_benchmark.py` | New `--context-mode contract / sweep / sweep_contract`; new `--shard I/N` |
| `nl2sql-v2/src/nl2sql/agent.py` | Contract keeps retrieval on; linkage arms turn it off |
| `nl2sql-v2/slurm/serve_vllm_qwen35.slurm` | Removed hardcoded user paths; portable across users |
| `nl2sql-v2/scripts/analysis/` | Scripts that reproduce every number in this document (see Section 11) |
| `nl2sql-v2/scripts/run_benchmark.py` (overnight) | `--context-mode full_contract / oracle_decoy`, `--oracle-file`, `--thinking`; `--resume` fix |
| `nl2sql-v2/slurm/teacher_run.slurm` | One self-contained job: serve, smoke-test, lanes, optional repeats, harvest |
| `nl2sql-v2/teacher_context.json` | The 14 verified gold SQL packages from the 27B teacher |
| `logs/traces/teacher_*`, `logs/traces/ablation_*` | Every overnight episode, published |

---

## 11. Reproducing these numbers

Every number above is produced by a script in `nl2sql-v2/scripts/analysis/`. Run from `nl2sql-v2/`:

```
uv run python scripts/analysis/buckets.py            # Section 4  — writes logs/analysis/buckets.json
uv run python scripts/analysis/paired_failures.py    # Section 1  — add --examples 2 for SQL examples
uv run python scripts/analysis/gold_sql_check.py     # Section 2  — add --repeats 20, --diagnose
uv run python scripts/analysis/scorer_audit.py       # Section 3  — needs no stored runs
uv run python scripts/analysis/vote.py               # Section 5
uv run python scripts/analysis/linkage_funnel.py     # Section 6
uv run python scripts/analysis/harvest_teacher.py --runs 'teacher_p1_*'                  # Section 7.1
uv run python scripts/analysis/paired_failures.py --bucket C --by-question \
    --runs 'v2_armAplus,v2_pass4_k1,v2_pass4_k2,v2_pass4_k3,v2_pass4_k4,teacher_p1_*,teacher_p1b_*'  # 7.2
uv run python scripts/analysis/ablation_arms.py                                           # Section 7.3
uv run python scripts/analysis/oracle_failures.py --examples 2                           # Section 7.5
uv run python scripts/analysis/ablation_arms.py --oracle-prefix ablation_forced --decoy-prefix ablation_oracle  # 7.6
uv run python scripts/analysis/oracle_failures.py --prefix ablation_forced               # Section 7.6
uv run python scripts/analysis/determinism.py                                             # Section 8
uv run python scripts/analysis/validator_report.py --tags 9b,27b                          # Section 5.1
```

`teacher_targets.py` picks the questions to send to a teacher; `teacher_run.slurm` runs a teacher pass or
a 9B arm end to end (see its header for the exact `sbatch` lines).

The first run re-executes all 675 stored queries (a few minutes) and caches the scores in
`logs/analysis/rescore_cache.json`. The cache discards itself whenever `eval.py` or `db.py` change.

To analyse the new arms once they finish, pass their trace directories. A glob merges an arm's shards
into one run, and bucket membership always comes from the five Phase-0 runs:

```
uv run python scripts/analysis/paired_failures.py --runs 'v2_armAplus,arm_contract_*'
```

---

## 12. Open questions and next steps

- **Optional: state column roles.** The forced prompt moved failures from tables to columns (7.6), and
  `local062` had its join-key columns without knowing they were keys. A variant that says which columns
  are join or identity keys would show how much of the rest is comprehension. It moves toward handing over
  part of the query, so it tests something different from retrieval.

- **Confirm Section 7.4 on more questions.** Run a second teacher pass with reasoning on
  (`--thinking --temperature 0.7`) over the 43 bucket-C questions still without verified gold SQL, then
  re-run both 9B arms on the larger set. The claim to test: correct linkage helps only where the 9B
  failed to find a table.
- **Re-run the arms with search on** once Ollama and the vector index are set up on Babel, to remove the
  caveat that the oracle arm lacked the enriched column descriptions.
- **Targeted retrieval, not more retrieval.** The retrieval failures are near-misses between sibling tables
  and identity keys. Cheap candidates: surface all tables sharing a name stem when one is described, and
  flag entity/identity tables (`customers` for `customer_unique_id`) in the schema overview.
- **Arm 1 (output contract), 135 questions — still worth running.** Several logic failures are correct
  computations with the wrong final shape, which is what the contract supplies. Read it on bucket C.
- **Arm 2 (value sweep) — low priority.** It supplies tables the model already finds almost every time.
- **A verifier is the highest-return next build, and a prompted one already works** (5.1): +8 questions
  with the 9B, +12 with the 27B, one extra call per question. Next steps: add the greedy run as a fifth
  candidate (ceiling 77), try more samples, and compare a trained ranker against the prompted judge on the
  13 questions the 27B judge still misses.
- **Generation is the lever for training (P1).** Even with retrieval handed over, the 9B passes 9% of runs
  on the unflagged hard questions and a third of its episodes exhaust the step budget.
