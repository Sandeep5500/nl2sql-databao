# Judge prompt variants: evaluation protocol

Fixed on 2026-11-12, before any variant was judged. Tests whether changing the pairwise judge's
prompt, with no training, picks the right answer more often. Covers Spider2 (SQLite) and BigQuery.

## What is being changed

Only the instruction text of the thinking judge's pairwise prompt (untuned
`QuantTrio/Qwen3.6-35B-A3B-AWQ`, thinking on, temperature 0.6, up to 8192 tokens). The candidates,
previews, schema, document, reply format and round-robin rule stay as deployed. Variants live in
`nl2sql-v2/scripts/judge_prompts.py`; `base` is the deployed prompt.

## Eval set

`nl2sql-v2/scripts/selection_eval.py build` (copy on Babel:
`nl2sql-sel/results/variants/selection_evalset.json`). A pool is one question's 4 lanes in one run
set (Spider2: q36rg, q36s, q36, v2) or Rohini's 4 BigQuery retries. Only pools with both a correct
and a wrong answer can change with the judge:

- **contested**: 1–2 of 4 lanes correct. The primary metric.
- **easy**: 3 of 4 lanes correct. The regression check.

The Spider2 questions are split by database into two halves balanced on contested pools, easy
pools and baseline misses (seed 20261112). Misses are read and prompts are designed on the design
half only. The test half is used once, to confirm. BigQuery is never used for design.

| set | contested pools | easy pools | ordered pairs | questions | stored thinking runs, contested right (run 1 / rerun) |
|---|---|---|---|---|---|
| Spider2 design | 69 | 39 | 814 | 67 | 49 / 42 |
| Spider2 test | 70 | 39 | 652 | 68 | 43 / 44 |
| BigQuery | 28 | 9 | 280 | 105 | 13 / 13 |

Design databases: Baseball, California_Traffic_Collision, EU_soccer, bank_sales_trading,
city_legislation, complex_oracle, delivery_center, f1, imdb_movies, log, modern_data.
Test databases: the other 19.

## Metric

Every arm, the baseline included, judges every ordered pair of the pools 4 times. The baseline gets
fresh samples, not the stored runs. From those samples, `selection_eval.py score` computes per pool:

- **exp1**: the exact expected accuracy of the deployed round-robin. It uses one verdict per
  ordered pair, drawn from that pair's 4 samples; a missing verdict counts 0.5, as before.
- **avg4**: the accuracy of the round-robin on the 4-sample average.

Differences are paired by pool. The 95% interval resamples questions with replacement.

Noise floor, measured on the two stored single-sample runs: on the design half's contested pools
they differ by 6 pools (interval −12 to 0), on the test half by 2. Four samples per pair should
roughly halve that.

## Protocol

1. **Design stage**, Spider2 design half (108 pools, 814 ordered pairs): the baseline and up to 4
   variants, 4 samples each. At most 2 variants go on to the test stage. They are the ones with the
   largest contested exp1 gain over the fresh baseline, and only if that gain is at least +2 pools.
2. **Test stage**, Spider2 test half and BigQuery (146 pools, 932 ordered pairs): the baseline and
   the chosen variants, 4 samples each.

## Pass bar

A variant is adopted only if all three hold:

1. Spider2 test-half contested: the exp1 gain over the fresh baseline has a 95% question-bootstrap
   interval above 0. If two variants are tested, each needs the 97.5% interval above 0.
2. Easy pools, both halves (78): the exp1 loss is at most 1.5 pools.
3. BigQuery mixed pools (37): the exp1 change is at least −1.5 pools. BigQuery is too small to show
   a gain, so it only guards against harm.

avg4 and the whole-benchmark totals (out of 540 and 105) are reported alongside, but do not decide.
If nothing passes, this judge's prompt is at its ceiling with these inputs.

## Amendment 1: selection rules and a stricter design bar

Fixed on 2026-11-12, after the design-half miss reading (summarized below) and before any
test-half or BigQuery result for these rules was looked at, and before any variant was judged.

Two selection rules sit on top of the judge. Neither needs a GPU, because both apply to the
stored verdicts. In `selection_eval.py`, a judge name gets the suffix `@U` and/or `@T`.

- **U, superset upgrade.** Judge exactly as deployed. Then, if another group's result has every
  column of the picked group's result with the same rows, submit the widest such group. The
  pools' `contains` map, computed on full results, gives this.
  - Why it should be safe: under Spider2's scorer that group is right whenever the pick is,
    except for questions where row order matters and values at the 0.01 tolerance edge.
  - It follows from the scorer's documented rule that extra columns are tolerated.
- **T, wider-first tie-break.** When groups tie for the top score, prefer more columns, then
  more lanes. Deployed: more lanes first.
  - Exploratory: it was chosen after reading the design-half misses.

On the design half, with the two stored thinking runs pooled (exp1, contested out of 69):

| rule | contested | easy (of 39) |
|---|---|---|
| deployed | 44.7 | 36.8 |
| U | 47.2 | 37.8 |
| T | 46.7 | 37.0 |
| U+T | 48.7 | 38.0 |

U+T gained 7 pools and lost 1 on contested pools; on easy pools, 3 up and 0 down.

**Rule test (preliminary).** Run on the stored runs, without a GPU:
- Spider2 test half: thinking run 1 and rerun, pooled (K=2).
- BigQuery: `think35` and `think35n` pooled. `think35n` is the names-only schema run, measured
  as making no difference.

U and T are each adopted only if all three hold:
1. The test-half contested exp1 gain over the deployed rule has a 97.5% question-bootstrap
   interval above 0. The level is 97.5% because two rules are tested.
2. Easy pools, both halves: the loss is at most 1.5 pools.
3. BigQuery mixed pools: the change is at least −1.5 pools.

U+T is adopted if both pass. The fresh 4-sample baseline's test half re-checks the decision with
the same bar once it is in; a reversal there is reported and the rule is dropped.

**Changes to the prompt-variant protocol:**
- **Admission bar.** A variant goes from the design stage to the test stage only with a gain of
  at least +3 contested pools, or +2 with at least twice as many pools up as down. A +2 gain is
  inside the noise of a 4-sample arm.
- **Comparison.** Variants are compared on top of the adopted rules. Otherwise column-rule gains
  that U already captures would count twice. Results without rules are reported alongside.
- **Not used for the decision:** design-stage exp1 without the 5 pools no judge can win
  (q36rg:local067, q36:local220, q36rg:local220, v2:local297, q36s:local358); per-arm
  diagnostics (accuracy with the right answer shown first vs second, the share of right-vs-wrong
  pairs where the first-shown candidate won both orders, accuracy by column relation); and
  failure and truncation rates.

## Design-half miss reading (summary)

32 design-half pools were missed in run 1 or the rerun (24 questions). Each was classified with
the gold in view and re-checked by a skeptic. A much stronger model also picked blind from the
judge's inputs only.

| final cause | pools | decidable from the judge's inputs (yes / partly / no) |
|---|---|---|
| visible misread | 17 | 15 / 2 / 0 |
| label questionable | 6 | 0 / 3 / 3 |
| hidden data fact | 4 | 0 / 4 / 0 |
| narrow-answer preference | 2 | 2 / 0 / 0 |
| info in doc or schema | 1 | 1 / 0 / 0 |
| ambiguous | 1 | 0 / 0 / 1 |
| other | 1 | 0 / 1 / 0 |

**Blind skyline.** The stronger model was right on 22/32 misses without database access and
26/32 with it, but only 32/41 on the contested pools our judge got right in both runs. Over all 69
design contested pools that is 72%, against the judge's 65% (exp1). So a much stronger reader of
the same inputs gains only about +5 pools. A prompt change is expected to recover +1 to +3 per
half (estimated), and the bar needs about +4.

**Recurring judge errors:**
- position decided a deciding pair (19 pools): right 85% when shown first, 71% second;
- objections to SQL differences that change no value (9);
- extra columns held against the right answer (8);
- "typical value" priors (6);
- false dialect objections (5);
- accepting the wrong number of rows (4).

## Runs

- Babel session `judge_variants.slurm` (2 GPUs, one vLLM server each, `judge_gpu_session` flags).
  Arms are queued as `nl2sql-sel/results/variants/queue/*.args`; calls are written to
  `nl2sql-sel/results/variants/calls/calls_<variant>.jsonl` by `rejudge_pools.py`.
- `02_design`: base, rules, diff_cmp, diff_nocmp and spec, interleaved, 4 samples per ordered pair
  on the design half (16,280 calls). It replaced the baseline-only design arm before anything ran.
- `09_base_testbq`: the fresh baseline on the test half and BigQuery (3,728 calls).
- `10_variants_testbq`: the two admitted variants, `diff_nocmp` and `diff_cmp`, interleaved, on the
  test half and BigQuery (7,456 calls). Queued 2026-11-12 13:08, after the design-stage decision
  below and before any test-half or BigQuery call of any arm was scored.
- **Variants** (`judge_prompts.py`). All four replace the deployed "Weigh: ... shape ..." sentence
  and share one rules block covering columns, rows, differences that change no value, dialect,
  typical-value priors and SQL comments.
  - `rules`: the rules alone.
  - `diff_cmp`: list the differences, check each against the results, decide. It adds a computed
    comparison of the two full results (`build_compare_cache.py`, `result_compare.py`). The
    comparison is unavailable for 80 of 814 design pairs and 82 of 652 test pairs, whose SQL is
    nondeterministic. It is available for all 280 BigQuery pairs, which come from traces of at most
    50 rows.
  - `diff_nocmp`: the same procedure without the comparison.
  - `spec`: write the answer's specification first, then check each candidate against it.

## Results

### Rule test, stored runs (preliminary; 2026-11-12)

Thinking judge, run 1 and rerun pooled (K=2); BigQuery `think35` and `think35n` pooled. Each cell
is the exp1 change against the deployed rule, with its 97.5% question-bootstrap interval.

| rule | Spider2 test contested (67 scored) | pools up / down | easy, both halves | BigQuery mixed (37) |
|---|---|---|---|---|
| U | +3.5 [0.0, +11.0] | 4 / 0 | +1.0 | 0.0 (0 / 0) |
| T | +1.7 [−2.5, +6.6] | 7 / 3 | +0.2 | +1.4 [−0.2, +4.4] |
| U+T | +3.2 [−2.5, +10.8] | 8 / 3 | +1.2 | +1.4 |

- **T fails the bar.**
- **U does not pass by the letter of the bar:** its interval reaches 0 instead of lying above it.
  This partly follows from what U is. It cannot lower a pool under this scorer, so its interval
  cannot fall below 0, and the lower bound is 0 whenever a resample may draw none of the 4 improved
  test questions. Over all 540 Spider2 pools and 105 BigQuery pools, U raised 10 pools and lowered
  none.
- Whole Spider2 benchmark, exp1 out of 540: deployed 291.5, U 298.6, U+T 299.9. These figures
  include the design half, where the rules were made.
- The fresh 4-sample baseline (`09_base_testbq`) re-checks U and T against the same bar.

### Design stage (2026-11-12; 4 fresh samples per ordered pair, every arm)

Spider2 design half: 3,256 calls per arm. Contested pools: 69. Easy pools: 39. Changes are against
the fresh baseline, with 95% question-bootstrap intervals.

| arm | contested exp1 | change [95%] | pools up / down | change on top of U | easy change | contested avg4 |
|---|---|---|---|---|---|---|
| base | 46.2 | | | | | 51 |
| rules | 50.2 | +4.0 [+0.6, +7.7] | 21 / 8 | +4.3 | +0.8 | 51 |
| diff_cmp | 50.7 | +4.5 [+0.5, +8.7] | 25 / 9 | +4.4 | +0.4 | 52 |
| diff_nocmp | 51.2 | +4.9 [+1.3, +9.1] | 23 / 7 | +5.6 | −0.3 | 52 |
| spec | 48.9 | +2.6 [−1.0, +6.5] | 18 / 13 | +3.0 | −1.4 | 50 |

"On top of U" compares variant@U with base@U. U alone adds +2.1 to the baseline (5 up / 0 down).

**Admission.** No rule was adopted, because U and T both failed the preliminary bar. So the
decision uses the comparison without rules.
- `diff_nocmp` (+4.9) and `diff_cmp` (+4.5) go to the test stage. They have the largest gains and
  both clear +3.
- `rules` (+4.0) also clears the bar, but only two may go.
- `spec` fails: +2.6, with 18 up and 13 down.
- The same two lead on top of U, and without the 5 unwinnable pools. On those 64 contested pools,
  the gains are diff_cmp +3.4, diff_nocmp +3.1, rules +2.5 and spec +1.8.
- The three leading gains (+4.0 to +4.9) are within noise of each other. Which two go is decided by
  the rule, not by the data.
- With two variants on the test half, each needs its 97.5% interval above 0.
- The prompts were written from design-half misses, so the gains are expected to shrink on the test
  half.

**Observations (measured; they do not decide):**
- **Averaging 4 baseline samples gives about the same gain.** With the samples averaged before the
  round-robin (avg4), the baseline already reaches 51 contested; the variants reach 50–52.
  - Reading: the variants mostly make one verdict as reliable as an average of four.
  - The deployed judge draws one sample per ordered pair, so exp1 decides.
  - The gain may not add to multi-sampling.
- **Less position bias.**
  - With the right answer shown second, the baseline is right 71% of the time; rules is right 78%,
    the two diff variants 80% and spec 76%.
  - With the right answer shown first: 85% for the baseline, 86–89% for the variants.
  - The first-shown candidate won both orders in 18% of right-vs-wrong pairs for the baseline,
    and 11–12% for the variants.
- **Better in both column cases.** When the right answer has more columns, the baseline is right 80%
  of the time and the variants 80–86%. When it has fewer, the baseline is right 91% and the variants
  94–96%. So the gain is not only about extra columns.
- **Calls that failed**, all truncations at 8,192 tokens, out of 3,256 per arm: base 2, rules 52,
  diff_cmp 45, diff_nocmp 61, spec 29. Each failed call counts 0.5.
- **Completion tokens, p50 / p90:** base 2,266 / 3,923; rules 2,540 / 4,980; diff_cmp 2,789 / 5,019;
  diff_nocmp 3,038 / 5,437; spec 2,911 / 4,934.

### Rule re-check on the fresh baseline (2026-11-12; 4 samples per ordered pair)

This is `09_base_testbq` (test half and BigQuery) plus the design half's fresh baseline from
`02_design`. Each cell is the exp1 change against the deployed rule, with its 97.5%
question-bootstrap interval.

| rule | Spider2 test contested (70) | pools up / down | easy, design / test | BigQuery mixed (37) |
|---|---|---|---|---|
| U | +3.7 [0.0, +11.0] | 5 / 0 | +0.5 / +0.2 | 0.0 (0 / 0) |
| T | +1.2 [−1.2, +5.0] | 6 / 3 | +0.1 / −0.4 | +1.8 [0.0, +5.0] (3 / 0) |
| U+T | +3.5 [−1.1, +11.5] | 7 / 3 | +0.6 / −0.2 | +1.8 |

- **No reversal.** T fails again.
- **U misses the bar by the letter again.** Its interval touches 0, for the reason given above.
  - It raised 5 test-half contested pools and lowered none.
  - On the design half it raised 5 and lowered none.
  - It has lowered no pool in any measurement so far.
- **Neither rule is adopted under the protocol.** So the test-stage variants are compared without
  rules, with @U reported alongside.
- **Fresh baseline, exp1 with the deployed rule:**
  - test contested 43.8 of 70 (avg4 45), test easy 37.4 of 39;
  - BigQuery mixed 19.8 of 37 (avg4 20).
- **Failed calls** (truncations): design 2, test 1, BigQuery 2.

### Test stage (2026-11-12; `10_variants_testbq`, 4 fresh samples per ordered pair)

Changes are against the fresh baseline (`09_base_testbq`), with no rule on top, because no rule was
adopted. Intervals are 97.5% question bootstraps, since two variants were tested.

| variant | test contested (70) | pools up / down | easy, design + test (78) | BigQuery mixed (37) | pass bar |
|---|---|---|---|---|---|
| diff_cmp | +7.2 [+1.9, +13.0] | 25 / 8 | +0.4 (74.5 → 74.9) | +2.9 [−0.6, +6.6] | **passes all three** |
| diff_nocmp | +5.1 [+1.6, +9.1] | 23 / 9 | **−2.4** (74.5 → 72.1) | +3.3 [−0.2, +7.4] | fails criterion 2 |

**Decision under the protocol: `diff_cmp` is adopted.**
- `diff_nocmp` fails because it lost easy pools: −0.3 on the design half and −2.0 on the test half
  (3 up / 6 down), against a limit of 1.5.

Reported alongside; these do not decide:
- **Whole benchmark, exp1.**
  - Spider2 (of 540): base 293.4, diff_cmp 305.6, diff_nocmp 301.1.
  - With U on top: base 299.9, diff_cmp 310.4.
  - BigQuery (of 105): base 24.8, diff_cmp 27.7, diff_nocmp 28.1.
- **avg4 totals.** Spider2: base 299, diff_cmp 309. BigQuery: 25 → 28.
- **Test contested with U on top.** diff_cmp@U +9.5 [+2.4, +18.3] (28 / 7), diff_nocmp@U +8.6.
- **Position, test half.** With the right answer shown second, base is right 74% of the time and
  diff_cmp 84%. The first-shown candidate won both orders in 13% of right-vs-wrong pairs for base, 7%
  for diff_cmp.
  - BigQuery: right shown second 54% for base vs 68% for diff_cmp.
- **Columns, test half.** When the right answer has more columns: base 66%, diff_cmp 79%.
- **Calls that failed** (all truncations at 8,192 tokens):
  - diff_cmp: 25 of 2,608 (test), 21 of 1,120 (BigQuery);
  - base: 1 and 2.
- **Completion tokens, p50.** diff_cmp 2,801 (test) and 3,168 (BigQuery), vs base 2,268 and 2,530.
- **The comparison needs full results.** `diff_cmp` relies on the computed comparison of the two full
  results (`result_compare.py`). The production judge path (`select_answer.py`) does not compute it
  yet. Deploying it there is a harness change.
