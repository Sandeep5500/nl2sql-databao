# Improving the 35B judge on BigQuery: analysis and plan (Nov 18 2026)

Goal: take the 35B judge (Qwen3.6-35B-A3B, `diff_cmp`) from 55.5% on the 204 BigQuery questions to about
58–60%. Every number is measured on stored judge calls unless marked *(estimate)*; nothing here re-ran SQL
on BigQuery. Scripts and outputs: `results/bq17/headroom/`. The gold-label audit behind §4 is
`nl2sql-v2/reports/Spider2 Lite BigQuery gold errors.md`.

## 1. Where the 35B stands

| | correct of 204 | accuracy |
|---|---|---|
| one try alone (pass@1) | 98.0 | 48.0% |
| majority vote | 105.2 | 51.6% |
| 35B judge, `diff_cmp` (two runs pooled) | 113.2 | 55.5% |
| target 58% / 60% | 118.3 / 122.4 | |
| at least one try right (pass@4) | 129 | 63.2% |

- The judge only matters on the 65 questions where the 4 tries disagree and at least one is right (in 64
  every try is right, in 75 none is). 58% means +5.1 picks on those 65; 60% means +9.2.
- It loses 15.8 picks there. Most of that (8.4) is in 14 questions where all four tries differ and one is
  right. In those, the three wrong tries usually share one mistake, so the right answer is the odd one out:
  a "which result agrees most with the others" score picks it in 2 of 14.
- Its errors are mostly consistent, not noisy: on the 35 comparisons that decide most of the loss it is
  right in 17% of calls, so it makes the same wrong call almost every time.

## 2. What a better judge could reach

- Any judge is capped at pass@4: 129 (63.2%).
- 4.5 of the 35B's 15.8 lost picks are on questions where the official label rewards an arbitrary choice
  or one convention (§4: bq035, ga010, bq002, bq424, bq055, bq397, bq208); no judge should be expected to
  win those. A judge that won every other question would score about 124.5 (61.0%) *(estimate)*.
- The other 11.3 picks are real judge errors: 5.1 on audited questions where the gold is right or
  defensible (bq045, bq356, bq051, bq151, bq308, bq389) and 6.2 on the rest. They are consistent errors
  that neither prompt changes nor the 27B (115.5) fix, so the reachable part is much smaller than 124.5.
- References: the 27B judge scores 115.5; choosing per question the better of the 35B and the 27B (with
  the answer key) gives 118.7; choosing per question the best of the eight 35B prompts we ran gives 119.3.
  These oracles show the room exists but is spread across questions no single change targets.

## 3. Cheap changes, measured offline on the stored calls

| change | bq17 (204) | earlier BigQuery set (105) | SQLite (540) |
|---|---|---|---|
| deployed: one call per ordered pair | 113.2 | 27.7 | 305.7 |
| **ask twice, average the votes** | **114.4** (+1.3 [+0.1, +2.6]) | 28.2 (+0.4) | 308.1 (+2.5 [−0.0, +5.1]) |
| ask four times, average | 114.9 (+1.8 [−0.2, +3.8]) | 27.8 (+0.1) | 309.0 (+3.3) |
| superset rule (submit the wider result when it contains the pick with the same rows) | 113.7 (+0.5 [+0.0, +1.4]) | 27.7 (0.0) | |
| **ask twice + superset rule** | **114.6** (+1.5 [+0.2, +3.1]) | | |
| eight different prompts, one call each, averaged | 114.4 (+1.2) | 30.1 (+2.4) | |
| prefer the wider result on ties | 112.8 (−0.4) | 29.3 (+1.5) | |
| confidence-weighted votes | 113.2 (0.0) | 27.8 (0.0) | |
| more or less weight on how many tries agree | 111.5–113.2 | 26.9–28.2 | |
| favour results that partly agree with the others | 113.2–113.4 | | |

- Averaging helps where the judge leans right but is noisy; it cannot fix the consistent errors. Each
  extra call per pair costs one more judge pass (1,194 calls per BigQuery run today; the 35B is the
  agent's own model and judges a run in about an hour on two GPUs).
- The superset rule cannot lose under Spider2's scorer (extra columns are allowed), so it is free.
- The same averaging on the 27B: 116.6 with two calls, about 117–119 with three or four *(estimate)*.

## 4. The labels: part of the gap is the benchmark, not the judge

We audited the 13 BigQuery questions where our judges lose most, using the gold SQL, the gold files, our
agent's traces and Spider2's git history (no BigQuery run). Main findings:

- In Nov 2025 the maintainers replaced every accepted answer file for these questions (one commit, no
  per-question reason) and never updated the Lite gold SQL. So the gold SQL of bq397, bq002, bq151, bq308
  and bq424 cannot produce any current answer file, and some current files look generated on Snowflake
  (bq002's weeks start on Monday, Snowflake's default; BigQuery's start on Sunday).
- Some labels are fine and the judge was simply wrong: bq045 (the three-station files are right),
  bq356 (6,568 is right), bq051 (the gold's reading is the one NOAA's documentation supports).
- Some are scoring defects: bq035 (two accepted files differ by the Earth radius used, so answers at
  either radius fail the 0.01 tolerance), bq389 (a column setting makes four of its seven files unusable;
  open GitHub issue #151), bq055 (a patchwork of accepted formats), ga010 (one file checks only the
  channel name, so an answer with a 13× wrong count passes while correct overviews fail).
- Some allow two fair readings and the gold accepts one (bq397, bq208, bq151, bq308), and in one the
  accepted file is not a meaningful answer (bq424 sums a debt stock over 51 years).
- Nobody has published these as errors or posted corrected answers; the large 2026 audit of Spider 2.0
  (Jin et al., PVLDB) did not cover them, and the maintainers have not replied to gold reports since
  August 2025.

Rescoring all 204 questions with these 13 labels corrected:

| | pass@1 | majority | 35B judge | 27B judge | pass@4 |
|---|---|---|---|---|---|
| official labels | 48.0% | 51.6% | 55.5% | 56.6% | 63.2% |
| strict: fix scoring defects and clear errors only | 48.4% | 52.1% | 56.3% | 57.8% | 62.7% |
| lenient: also accept both fair readings | 49.9% | 53.4% | 58.2% | 59.6% | 63.2% |

- Caveat: only these 13 questions were audited, and they were chosen because the judges lost there, so the
  corrected scores lean in the judges' favour. bq424 shows a correction can also take picks away. A fair
  corrected score needs the same audit on all 204 questions (163 have more than one distinct answer).
- Published leaderboards use the official labels, so the official number stays the headline.

## 5. Plan

| step | what | expected *(estimate)* | cost | status |
|---|---|---|---|---|
| 1 | ask twice per ordered pair and average, plus the superset rule | +1.5 (bq17), +0.4 (earlier set), +2.5 (SQLite) | 2× judge calls | measured offline; needs your decision on cost |
| 2 | serve the 35B judge in bf16 instead of 4-bit AWQ (same model; the agent already runs bf16) | 0 to +2 | one 4-sample run on bq17, the earlier set and SQLite (~9k calls, two GPUs) | not tested; generic, so the used sets are a fair test |
| 3 | a listwise judge for questions with 3–4 different results: all results side by side, with their differences, one decision | 0 to +3 | ~1 day to build; ~1 call per question | not tested; targets where 70% of the loss is |
| 4 | distil the 27B into the 35B on practice pairs from non-Spider2 databases (SFT on the 27B's reasoning where it is right) | 0 to +2 | days; GPU for the 27B to judge ~3k pairs, LoRA training | allowed by the data rules; earlier fine-tuning failed on the data, not the method |
| 5 | audit all 204 questions and report a corrected-label score next to the official one | removes the bias in §4 | agent reading time, no GPU | 13 of 204 done |

- Steps 1+2+3 together: about 115–118 on the official labels (56.5–58%) *(estimate)*; 58% needs steps 2
  or 3 to work at the top of their range. 60% on the official labels would need the judge to fix most of
  its consistent errors, which nothing we have tried, including the 27B, comes close to.
- On lenient corrected labels the 35B is already at 58.2%, and step 1 takes it to 59.0%.
- Each new experiment gets a written plan first. Gates as in round 2: BigQuery mixed pools (both sets)
  at least +2.0 with the interval above zero, and SQLite at least −1.5. Since no BigQuery set is unused,
  only generic changes (steps 1–4), not rules written from reading misses, should be tested on them.
- Not recommended: merging columns from several tries to exploit the scorer's tolerance of extra columns,
  or rules that copy the gold's habits (e.g. "drop entities with no data"); both fit the benchmark, not
  the questions.

## 6. Round 3 results (Nov 18, night)

Steps 1–3 of the plan were run on the 35B against gates written beforehand (bq_judge_improvement_plan.md,
"Round 3"); details in that file's "Round 3 results".

| bq17, correct of 204 | official labels | strict corrections | lenient corrections |
|---|---|---|---|
| deployed `diff_cmp` | 113.2 (55.5%) | 114.9 (56.3%) | 118.8 (58.3%) |
| **ask twice + superset rule** | **114.7 (56.2%)** | **116.7 (57.2%)** | **120.5 (59.1%)** |
| dataset notes (`dc_facts`) | 112.8 (55.3%) | 115.9 (56.8%) | 117.7 (57.7%) |
| dataset notes + ask twice | 114.0 (55.9%) | 117.6 (57.6%) | 118.9 (58.3%) |
| listwise for 3–4 results | 112.4 (55.1%) | 113.9 (55.8%) | 118.4 (58.0%) |

- Dataset notes fix the questions whose deciding fact is in the notes (bq356, bq051) and lose about as much
  elsewhere; on the earlier set they gain 2.6. Listwise judging is worse on bq17. Neither passes the gate.
- Asking twice with the superset rule remains the only change that is positive on both BigQuery sets and on
  SQLite (+1.5 on bq17, +0.4 on the earlier set, +2.5 on SQLite). It is the recommended production change if the
  doubled judge cost is acceptable.
- Not run yet: the bf16 judge (step 2 of the original plan) and distillation from the 27B (step 4).
