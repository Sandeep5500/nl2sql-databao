# Answer selection: the pairwise judge (Nov 2026)

The agent answers every question 4 times (4 lanes, temperature 0.7), and one answer has to be submitted.
The judge picks it. This page says what the judge does, why it is built this way, how the two best
judges compare (Qwen3.6-35B-A3B in production, Qwen3.8-27B as the challenger, both with the `diff_cmp`
prompt), and how to test a change. All numbers are measured unless marked *(estimate)*. The full record
is in [judge_results.md](judge_results.md); a short list of findings is in
[judge_findings.md](judge_findings.md).

## The problem

The 4 lanes often disagree, and at least one is right much more often than a single lane is:

| | one lane (pass@1) | any lane right (pass@4) |
|---|---|---|
| SQLite, 135 local questions (run q36rg) | 51.1% | 69.6% |
| BigQuery, 204 questions (Nov 17 run) | 48.0% | 63.2% |

Selection decides how much of that gap we keep. Majority vote keeps little of it (54.2% and 51.6%),
because the right answer is often the one only one lane found.

## How the judge works

Production is `nl2sql-v2/scripts/select_answer.py --mode pairwise --thinking` (the `diff_cmp` prompt, two
calls per ordered pair and the superset rule are the defaults; the last two since Nov 19):

1. Run each lane's SQL and group lanes whose results are equal (row order ignored, the scorer's
   normalisation). If all lanes agree, submit that result; no judge call is made.
2. Judge every pair of distinct results in both presentation orders, twice per order (`--votes 2`; once
   per order before Nov 19). The judge sees the
   question, the external document (first 8,000 characters), a schema overview, both SQL queries, the
   first 8 rows of each result with its full shape, and a comparison of the two full results computed
   by `result_compare.py` (shapes, which columns pair up, rows and values found on one side only).
3. The `diff_cmp` prompt asks for four steps: list the concrete differences between the two queries;
   use the comparison to say whether each one changes the result; set aside those that change no value;
   decide the rest against the question and the document. A rules block repeats what counts (extra
   columns are fine; missing rows or values are not; how the SQL is written is not a criterion).
4. The judge reasons first (thinking on, temperature 0.6, up to 8,192 tokens) and replies with JSON
   naming the winner.
5. Take the result with the most wins. Ties go to the result more lanes produced.
6. Superset rule: if another result holds every column of that result with the same rows, submit the
   widest such result instead. The scorer accepts extra columns, so the wider result is right whenever
   the winner is, unless the gold answer's row order counts and the wider result orders its rows
   differently. Of the 398 such pairs in our eval sets, none had the winner right and the wider result
   wrong; 36 had the reverse.

```bash
cd nl2sql-v2
uv run python scripts/select_answer.py --mode pairwise --thinking \
    --runs ../results/q36rg_pass4_k1.csv,../results/q36rg_pass4_k2.csv,../results/q36rg_pass4_k3.csv,../results/q36rg_pass4_k4.csv \
    --judge-endpoint http://<node>:8765/v1 --judge-model QuantTrio/Qwen3.6-35B-A3B-AWQ \
    --output ../results/q36rg_selected.csv
```

A question with 4 different results needs 24 judge calls (12 before Nov 19); questions where the lanes
disagree and one is right need about 14 on average on SQLite. The calls of one question are sent at once
(`--workers`, default 16), so asking twice adds judge compute but little waiting. `--votes 1
--no-superset-rule` gives the earlier production.

## Why it is built this way

- **A judge beats majority vote.** Over 540 SQLite pools (4 saved run sets × 135 questions) the old
  thinking judge picked 296 right against 261 for majority vote; on all 204 BigQuery questions the judges
  beat majority vote by 7 to 10 picks on the 65 questions where the lanes disagree and at least one is
  right.
- **Pairs, in both orders.** Comparing two answers at a time keeps each call small. Judges favour the
  answer shown first (the old prompt was right 85% of the time with the right answer first, 71% with it
  second), so every pair is asked both ways and the bias cancels in the totals.
- **Thinking on.** Without reasoning the same model picks 281 of 540 (SQLite) and 24 of 105 (BigQuery)
  instead of 296 and 26.
- **The `diff_cmp` prompt and the computed comparison.** Tested in a pre-registered design (SQLite split
  by database into a design half and a test half, 4 samples per pair; [judge_prompt_eval.md](judge_prompt_eval.md)).
  On the test half's close calls it gained +7.2 picks [+1.9, +13.0] (97.5% interval), without losing
  easy pools. Over the
  540 pools it moves the expected score from 293.4 to 305.6, and with the right answer shown second the
  judge is right 84% of the time instead of 74%. It costs about 23% more judge tokens. On BigQuery it
  gives the 35B no gain (+0.8 [−2.9, +4.3] for the old prompt on the 204 questions), and it stays the
  default because it was allowed to lose up to 1.5 there.
- **Ask twice, then the superset rule (adopted Nov 19).** Averaging two verdicts per ordered pair
  softens one unlucky verdict, and the superset rule only moves to a result the scorer accepts whenever
  it accepts the winner. It was the one change that helped on both BigQuery sets and on SQLite in the
  Nov 18 tests; on the stored samples it adds +1.5 [+0.1, +3.0] picks on BigQuery (204 questions), +0.4 on
  the earlier BigQuery set, and +1.6, +0.5 and +2.7 on the SQLite run sets q36rg, q36e and q36x. It doubles
  the judge calls. A check on fresh samples is in [judge_results.md](judge_results.md) §14.
- **An untuned model.** Six fine-tuning recipes (SFT, DPO, letter-only training; at most 2,644
  examples over 1,814 practice pairs from non-Spider2 databases) never beat the untuned thinking judge
  on Spider2. The practice data
  was simpler than Spider2 and about half of its hard pairs had a defensible "wrong" answer. Details:
  [judge_training_methods.md](judge_training_methods.md).
- **The agent's own model.** The 35B judge is the model that serves the agent, so production needs no
  second model.

## The two judges

Both run with thinking, temperature 0.6, 8,192 tokens and the `diff_cmp` prompt.

| | Qwen3.6-35B-A3B (production) | Qwen3.8-27B |
|---|---|---|
| model | mixture of experts, about 3B parameters active per token; AWQ 4-bit | dense 27B, bf16; about 9× the compute per token |
| reasoning per BigQuery call (median) | 3,053 tokens | 5,146 tokens |
| calls that reach 8,192 tokens without a verdict | 1% | 16–25% SQLite, 31–32% BigQuery (8% with a 16,384 budget) |
| first-shown answer wins both orders (right-vs-wrong pairs) | 7–12% | 0–1% |
| SQLite, 540 pools (expected correct) | 305.6 | **317.4** (+11.8 [+1.7, +22.0] on the 217 pools where lanes disagree) |
| BigQuery, earlier set (105 pools, greedy failures only) | 27.7 | **33.3** (+5.6 [+2.1, +9.5]) |
| BigQuery, all 204 questions (Nov 17) | 112.3 and 113.9 in two runs | **115.5** (+2.3 [−1.6, +6.8] against both 35B runs pooled) |

- The 27B is the better judge on SQLite and ahead on both BigQuery sets, but on the full BigQuery set
  its lead is not resolved.
- Room to finish does not help it pick. With 16,384 tokens instead of 8,192 (BigQuery, Nov 18) the 27B
  leaves 8% of its calls without a verdict instead of 32%, and 72% of its answers on the comparisons it
  used to cut off are right, yet it scores 114.0 of 204 against 115.5 (−1.6 [−4.2, +0.7], 3 samples).
  A missing verdict counts half for each side, which leaves the result more lanes gave ahead; where that
  result is right and the 27B, once it finishes, decides wrong (bq389, bq424), the pick is lost. Its
  errors cluster in the hard questions, so finishing exposes them rather than spreading them thin.
- Under the production rule (asks twice, superset rule; scored from the stored samples) the 27B scores
  117.1 of 204 on BigQuery against the 35B's 114.7 (+2.4 [−1.7, +6.8]) and 34.0 against 28.2 on the earlier
  BigQuery set (+5.9 [+1.2, +10.7]); on the SQLite run sets +0.9 (q36rg), +6.9 [+1.5, +12.8] (q36s), +2.5
  (q36) and −0.2 (v2). The rule helps both judges by about the same amount.
- **Does the 27B fit the small-model goal?** (Nov 19) The goal set in September is a small deployed model
  (9B-class), with larger models used only as a reference or as an offline teacher. Qwen3.8 has no smaller
  model than the 27B. Per judge call the 27B uses about 15× the 35B's compute (9× the active parameters per
  token, 1.7× the reasoning tokens), needs two 48 GB GPUs in bf16 where the AWQ 35B needs one, and is a
  second model next to the agent's own. It gains +1 to +7 picks per set, resolved on 2 of 6 sets.
  Recommendation (pending the team's decision): it does not fit; production stays on the 35B, and the 27B is
  reported as the larger-judge reference.
- Other models of the same sizes did worse than the 35B: GLM-4.7-Flash (296.9 of 540) and
  Magistral-Small-2509 (300.0). JEV-27B's one-step decision mode scored 290 of 540.

## Final scores, latest runs

Judge rows are the expected accuracy of one run (exp1, computed from 4 or more samples of every judge
call; see below). "One call per pair" is production before Nov 19; "production" asks every pair twice and
applies the superset rule, scored here from the stored samples (a check on fresh samples is in
[judge_results.md](judge_results.md) §14).

**SQLite, 135 local questions, run q36rg** (Qwen3.6-35B-A3B agent, 4 lanes, temperature 0.7):

| | correct of 135 | accuracy |
|---|---|---|
| one lane (pass@1, average) | 69.0 | 51.1% |
| majority vote (ties at random) | 73.2 | 54.2% |
| 35B judge, `diff_cmp`, one call per pair | 85.6 | 63.4% |
| **35B judge, production (asks twice, superset rule)** | **87.2** | **64.6%** |
| 27B judge, `diff_cmp`, one call per pair | 86.6 | 64.1% |
| any lane right (pass@4) | 94 | 69.6% |

On this run set alone the 27B's lead over the one-call 35B is +1.0 [−2.5, +4.6].

**SQLite, newer run sets q36e and q36x** (Oct 7–8, explored enrichment; 35B judge only, the 27B was
not run on them):

| correct of 135 | q36e | q36x |
|---|---|---|
| one lane (pass@1, average) | 72.5 (53.7%) | 67.5 (50.0%) |
| majority vote (ties at random) | 78.5 (58.1%) | 75.2 (55.7%) |
| 35B judge, `diff_cmp`, one call per pair | 82.8 (61.3%) | 82.8 (61.3%) |
| **35B judge, production (asks twice, superset rule)** | **83.3 (61.7%)** | **85.5 (63.3%)** |
| any lane right (pass@4) | 92 (68.1%) | 91 (67.4%) |

The one-call judge beats majority vote by +4.3 [−0.9, +9.8] and +7.5 [+1.3, +13.8] picks. q36x's own log says
50.2% and 92; one lane's SQL gives another result when re-run.

**BigQuery, 204 questions, Nov 17 run** (same agent model, bf16, 4 lanes, temperature 0.7):

| | correct of 204 | accuracy |
|---|---|---|
| one lane (pass@1, average) | 98.0 | 48.0% |
| majority vote (ties at random) | 105.2 | 51.6% |
| 35B judge, `diff_cmp`, one call per pair (two runs pooled) | 113.2 | 55.5% |
| **35B judge, production (asks twice, superset rule)** | **114.7** | **56.2%** |
| 27B judge, `diff_cmp`, one call per pair | 115.5 | 56.6% |
| any lane right (pass@4) | 129 | 63.2% |

Under the gold audit's corrected labels (13 audited questions, chosen where the judges lost, so the
correction leans in the judges' favour) the 35B production scores 116.7 (57.2%, strict) and 120.5 (59.1%,
both fair readings accepted); one call per pair gives 114.9 and 118.8.

With one call per pair, the 35B judge keeps half to two thirds of the pass@1 to pass@4 gap on SQLite (q36rg 16.6 of 25 picks,
q36e 10.3 of 19.5, q36x 15.3 of 23.5) and about half on BigQuery (15.2 of 31).

## Where the judge still loses

- **SQLite.** Losses sit in pools where only one lane is right. Reading 29 missed comparisons with the
  gold answer in view: 12 were misreads with the deciding information in the prompt, 7 held a hard-coded
  value or SQL style against the right answer, 4 were questions that allow the other reading, 3 were
  formatting conventions the gold wants, 2 needed data the judge cannot see, 1 held extra detail
  against the right answer. The judge does not apply rules the prompt already states.
- **BigQuery.** Of the 16.7 picks the 35B loses on the 65 mixed questions, about half are label
  problems no judge should fix: gold files that contradict their own SQL, a 1.6 parts-per-million
  difference failing a tolerance, questions with two fair readings. The rest are reasoning errors with
  the answer in view: accepting a filter the question does not state, penalising hard-coded values the
  results confirm, misreading the quantity or month asked for. The 27B fixes the clearest of these.
  Rough ceiling for any judge on this set: about 122 of 204 *(estimate)*.

## What did not help

- Fine-tuning (six recipes), a readout trained on the judge's hidden states, and a two-loss head: no
  gain on Spider2.
- Rule layers and confidence gating on top of the thinking judge (296 → 282 of 540), table details from
  the database in the prompt (helped easy pairs, hurt hard ones), summaries of the agent's trace
  (+8 / −7 over 405). More samples per pair gave the old prompt +3 of 540 (two samples, not
  significant); with `diff_cmp`, two samples plus the superset rule were small but positive on every set
  and became production (above).
- BigQuery prompt rules (Nov 18): a rule that filters must come from the question, and a final step that
  drops objections to how a query is written. The first fixes the filters it names and rejects
  exclusions the question implies; the second changes nothing. A clearer comparison tool and re-asking
  pairs whose two orders disagree gave +0.1 each.
- BigQuery prompt changes to how the judge works (Nov 18, second round, 68 unread questions): writing a
  specification from the question before reading the candidates, showing the results before the SQL,
  and the doc and schema uncut. Against one run of the deployed prompt +1.5, +0.9 and +1.7, short of
  the +2.0 the plan asked for; against two runs pooled +0.6, −0.1 and +0.7. For the 27B: asking for
  short reasoning (fewer missing verdicts, 32% → 22%, but no better picks) and a 16,384-token budget
  (above).
- The agent's output-shape rubric as extra information (checked offline, Nov 18): on the BigQuery
  comparisons the judges miss, both answers almost always have the shape the rubric asks for.
- Round 3 for the 35B on BigQuery (Nov 18): short notes from each dataset's official documentation in the
  prompt (+2.2 [−2.6, +7.2] over the 102 mixed BigQuery pools; they fix the questions whose deciding fact
  is documented and lose about as much elsewhere) and a listwise judge that sees every result of a
  question in one call (+0.8 [−4.5, +6.3]; worse than the round-robin when all four results differ).
  Neither reached the +2.0 the plan asked for.

## How to test a judge change

Score changes with exp1, not with single runs: two single runs of the same judge pick differently on
about 23 of 540 SQLite questions, and even two 4-sample runs differed by 1.6 picks on BigQuery's 65
mixed pools. On 43 of those pools the same two runs differ by −1.3 [−2.9, −0.1]: the question bootstrap
can leave out zero for a prompt that did not change, so a pass bar needs a margin above it (round 2
asked for +2.0).

1. Build the candidate pools: `judge_pools.py --no-judge` (SQLite: re-runs each lane's SQL, groups equal
   results, labels groups with the scorer) or `bq_judge_pools.py --no-judge` (BigQuery: reads results
   from the traces; never re-run SQL on BigQuery, it bills per byte).
2. Build an eval set: `selection_eval.py build`, or `runset_evalset.py` for new SQLite run sets (it
   reuses the design/test split by database).
3. Compute the result comparisons: `build_compare_cache.py`.
4. Judge every ordered pair 4 times: `rejudge_pools.py --variants <names> --samples 4` (cluster jobs:
   `slurm/judge_variants.slurm` for the 35B, `slurm/jev_variants.slurm` for the 27B,
   `slurm/runset_pools.slurm` for steps 1–3 on new SQLite run sets). Prompt variants live in
   `judge_prompts.py`.
5. Score: `selection_eval.py score --evalset ... --judge NAME@U@V2=calls.jsonl --ref <baseline>` prints
   exp1 per set and stratum with paired question bootstraps. `@U@V2` scores a run that asks every pair
   twice and applies the superset rule, as production does; `NAME=` without suffixes gives the one-call
   numbers of the earlier records.

exp1 is the exact expected accuracy of one run: each ordered pair has 4 sampled verdicts, and every
combination of one verdict per pair (with `@V2`, of two verdicts per pair, averaged) is weighed. A missing verdict counts as 0.5. The
evaluation counts each lane in the round-robin, which differs from production's win count by under 1
pick per stratum. Before testing a change, fix the measure and the pass bar in writing, keep part of
the data unread, and compare against a fresh run of the baseline: comparisons picked out by the
baseline's own samples drift back toward the average on any rerun. On preemptible GPUs, calls in flight
when a job is stopped are drawn again, and those are mostly the long ones; `rejudge_pools.py` logs every
request in `calls_<variant>.starts.jsonl`, so redrawn calls can be counted, and a sample that ran without
a preemption is the clean one.

## Open items (Nov 19)

- Running: the check of the production rule on fresh samples, and the same 35B in bf16 instead of AWQ
  4-bit ([judge_results.md](judge_results.md) §14).
- Running: an audit of all 204 BigQuery labels, so that corrected-label scores can move both ways (the
  Nov 18 audit read only the 13 questions where the judges lost).
- Needs the team's confirmation: the 27B does not fit the small-model goal (recommended above, "The two
  judges").
- Not run: the 27B on q36e and q36x (stopped to free GPUs for BigQuery).
- Not read: the 27B's misses in the BigQuery questions nobody has read (2.9 picks over 43 pools).
- Both BigQuery sets have been used for development, so a further BigQuery change needs a new test set,
  e.g. a fresh agent run on the 204 questions.
- About half of the BigQuery loss is label problems (gold files that contradict their SQL in 4 questions,
  a tolerance tripped by 1.6 parts per million); these limit any judge and could be reported upstream.
