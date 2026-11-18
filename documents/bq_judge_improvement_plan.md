# Improving the judge on BigQuery: plan and ablations (Nov 18 2026)

Written on Nov 18 before any ablation call was made. The evidence is the BigQuery error analysis,
[judge_results.md](judge_results.md) §11. Production stays the 35B with `diff_cmp` until the user
decides otherwise.

## What the analysis says

- The deployed judge (Qwen3.6-35B-A3B, thinking, `diff_cmp`) loses 16.7 of the 65 mixed pools of
  all 204 BigQuery questions. None of it is noise, presentation order or voting.
- About half of it (7.0 picks) is label problems that no judge should be expected to fix.
- The rest is reasoning with the answer in view:
  - accepting a filter the question does not ask for (bq278: a typed list of 50 states drops 37
    rows);
  - holding hard-coded values against a right result (ga013, bq268, ga032);
  - misreading the asked quantity (bq393, bq018, bq424, bq079).
- The result comparison misaligns on BigQuery outputs in 12 of the 39 comparisons: keys written in
  different styles, renamed or rescaled columns, long vs wide layouts, six significant digits.
- Half the loss is in pools where all four lanes differ and one is right.

## Levers, in the order they are tested

1. **Prompt variants of `diff_cmp`, on the 35B** (queued Nov 18; `judge_prompts.py`). Each adds one
   change, so their difference from `diff_cmp` isolates it.
   - `dc_scope`: adds a rule. Filters must come from the question or the documentation. A typed-in
     list, a code the query's author picked, or dropping unusual-looking rows is a flaw when it
     changes the result. Rows belong if the data files them under what the question asks about. A
     filter the question implies is required.
   - `dc_lit`: adds a final step. Before answering, the judge drops any reason about how the query
     is written (hard-coded values, typed-in lists, literal dates or IDs, generality, style) that
     changes no value or row.
   - `dc_v2`: both.
2. **Comparison tool v3, with the `diff_cmp` prompt unchanged.**
   - Fixes:
     - match row keys across naming styles;
     - pair columns by their values, including ×100 / ×1000 scale and sign;
     - print enough digits to show a difference;
     - flag long vs wide layouts;
     - make no "equal" claims about empty columns.
   - It sits behind a version switch, so `select_answer.py` is unchanged until adoption.
   - Only pairs whose comparison text changes are judged again; the others keep their calls.
3. **Selection rule A, no GPU:** re-sample the pairs whose two presentation orders disagree.
   - Computed offline from the stored samples, on the full BigQuery set (new).
   - It was already measured on the Spider2 halves and the earlier BigQuery set: close calls +1.9 /
     +2.2 / +1.1 at about 1.5× the calls (§6).
4. **Later, each needing the user's go-ahead:**
   - the 27B with a larger token budget on the 32% of its calls that truncate;
   - more preview rows (needs a pool rebuild);
   - a judge that sees all three or four distinct results at once, for pools where they all differ.

## Data

- **Development (DEV): the full BigQuery set (`results/bq17/`).**
  - 65 mixed pools, 506 ordered pairs.
  - Its misses were read on Nov 18, so gains there are exploratory. They show whether a change fixes
    what it targets.
- **Test (TEST-BQ): the earlier BigQuery set.**
  - Mixed pools of Rohini's 4 retries of the 107 questions greedy got wrong: 37 pools, 280 ordered
    pairs. Never read.
  - Primary: the 25 pools whose question was not read in the full set (176 ordered pairs). All 37
    are also reported.
  - The deployed prompt is judged again in the same session, with the fixed comparisons. The
    Nov 12–15 calls used the faulty comparisons on 52 of the 280 pairs.
- **No-harm check: Spider2.** The 217 mixed pools of both halves (814 + 652 ordered pairs), against
  the stored deployed calls, which use the same comparisons.

## Measures

- exp1, 4 samples per ordered pair, paired question bootstrap at 95%. Missing verdicts count 0.5.
- On DEV, also per comparison:
  - mean P(right) on the 39 read comparisons (the targets);
  - mean P(right) on the 116 other right-vs-wrong comparisons (no harm).

## Gates, fixed now

1. **DEV.** A variant becomes a candidate if two conditions hold:
   - its mixed-pool gain over the deployed prompt is at least +1.0;
   - its mean P(right) on the 116 non-target comparisons is at most 0.02 lower.
2. **TEST-BQ.** On the 25 unread pools, gain at least 0. This is a point estimate: the set is too
   small for an interval bar.
3. **Spider2 no harm.** Mixed pools at least −1.5, with close calls and easy pools reported.
4. **Proposal.** A variant that passes 1–3 is proposed to the user for adoption.

The TEST-BQ arms run alongside DEV to save time, but only the numbers of variants that pass DEV count
toward a proposal. Spider2 arms run only for DEV candidates.

## Cost and jobs

- The 35B runs on 2 GPUs per session at about 29 calls a minute, on the preempt partition (lilab is
  busy):
  - DEV: 6,072 calls (about 3.5 h);
  - TEST-BQ: 4,480 (about 2.6 h);
  - Spider2: 5,864 per variant (about 3.4 h).
- Jobs as run (the first three, 11197280–82, waited on a CPU prep job and were replaced before any
  call; the prep moved into the GPU sessions, `prep_improve.sh`):
  - DEV session 11197357 (`bq17_impr`): `cmp3` → `~/judge-tmp/bq17/cmp3/`, the variants →
    `~/judge-tmp/bq17/improve/`, then a same-prompt rerun of `diff_cmp` → `~/judge-tmp/bq17/rerun_dc/`;
  - TEST session 11197358 (`sel_impr`) → `~/judge-tmp/sel_improve/bq105/`;
  - Spider2 session 11198103 (`s2_impr`), `dc_lit` → `~/judge-tmp/sel_improve/spider2/`, started on a
    one-sample interim and cancelled when no variant passed gate 1.

## Results (Nov 18)

Details: [judge_results.md](judge_results.md) §12; running log `results/bq17/improve/RESULTS.md`.

- **Lever 1, prompt variants: no variant passes gate 1.** DEV mixed pools against the stored deployed
  calls: `dc_scope` −0.4 [−3.2, +2.5], `dc_lit` −1.4 [−4.5, +1.4], `dc_v2` −0.2 [−2.6, +2.5]. TEST-BQ
  (25 unread pools) was positive, +1.8, +1.4 and +2.7, but counts only for variants that pass gate 1.
  - The scope rule fixes the filters it names (bq278, bq389) and turns the judge against exclusions the
    question implies (bq199 returns, ga004 users with no pageviews). The literal step changes none of
    its targets.
- **Lever 2, comparison tool v3: +0.1 [−0.4, +0.5].** Fails gate 1.
- **Lever 3, rule A: +0.1 [−1.0, +1.1] at 1.21× the calls** for the deployed judge.
- **Measurement notes.**
  - A same-prompt rerun of `diff_cmp` on DEV scores +1.6 [−0.9, +4.1] over the stored calls, so the
    stored baseline was a slightly low draw; against the rerun the variants are −3.0 to −1.8.
  - The per-comparison measure of gate 1 (the 39 read vs the 116 others) is biased by selection: both
    groups were chosen by the stored calls' own P(right). The same prompt moves them 0.204 → 0.266 and
    0.930 → 0.910. A future gate of this kind needs a same-prompt rerun as its reference.
- **Production stays on the 35B with `diff_cmp`.** Lever 4 needs a decision; both BigQuery sets are
  now used, so a further prompt change has no unused BigQuery set to be tested on.

## Round 2: how the judge works, and what it sees (Nov 18, afternoon; written before any round-2 call)

Asked again whether prompt changes alone, or more information in the prompt, can improve the judge on
BigQuery. Round 1 added rules or a final check. Round 2 changes how the judge works through a pair
(35B), how long it reasons (27B), and how much of the agent's information it sees.

**What else the judge could be given** (checked offline, no GPU):
- The agent's output-shape rubric (rows and columns, drafted from the question; in 123 of 204 BigQuery
  traces): on the 21 right-vs-wrong comparisons a top judge misses that have one, its row count
  separates the right answer from the wrong one once (bq268, which the 27B already gets right); in the
  others both answers have the shape it asks for. Not tested further.
- The doc: the judge sees its first 8,000 characters. 11 of 204 BigQuery docs are longer. The GA360 doc
  (35,736 characters; bq001–bq010) defines the nested fields only after that, e.g. `productRevenue`
  "multiplied by 10^6" at character 28,057, and the GA360 schema dump shows only top-level fields. No
  SQLite doc reaches 8,000 characters.
- The schema: the judge sees the first 40,000 characters of the agent's schema dump. 61 of 204 dumps are
  longer (up to 56,963), in 20 of the 65 mixed pools. Both judges score lower on those pools (35B 0.68
  vs 0.79, 27B 0.72 vs 0.83), but their weak pools are mostly §11's label problems (bq045, bq151, bq308)
  and bq055.
- How many lanes gave each result: not given. The judge would lean to the majority, and on BigQuery
  rescuing a wrong majority is worth more (3.8 picks) than overruling a right one costs (1.9).
- Facts from the answer key (which columns the scorer checks, whether row order counts): not given.
- SQLite: the judge already sees what the agent saw before exploring (the names-only overview and the
  doc). Table details ("DB context") were tried in October and helped only easy pairs.

**Sets.**
- TEST (primary): the 68 mixed pools whose question was not read on Nov 18: 43 of bq17's 65 and 25 of
  the earlier set's 37. Round 1 scored them; nothing in them was read. Round 2's variants come from the
  reading of the other 34 and of the Spider2 design half (judge_results.md §9).
- READ: the other 34 (bq17 22, earlier set 12), reported with a no-harm bar.
- The 27B's misses in unread questions are read only after round 2 is scored.

**Baselines** (fixed comparisons): the deployed 35B with `diff_cmp`, bq17 8 samples per ordered pair (Nov
17 calls and the Nov 18 rerun), earlier set 4 samples (Nov 18 session); the 27B, its Nov 17 calls on bq17.

**Variants** (`judge_prompts.py`):
- `dc_spec` (35B): a specification written from the question and documentation alone, then `diff_cmp`'s
  steps decided against it. For misreading which quantity, period or rows the question asks for (15 of
  the 39 read comparisons; the 27B gets 7 of them right).
- `dc_rf` (35B): both results and the comparison before the SQL; the judge first says where the results
  disagree and uses the SQL only to explain each disagreement. For holding how the SQL looks against a
  right result.
- `dc_full` (35B): `diff_cmp` with the doc and schema uncut (up to 40,000 and 60,000 characters; every
  BigQuery question fits), so the judge sees what the agent saw. Its Spider2 prompts are `diff_cmp`'s.
- `dc_brief` (27B): `diff_cmp` plus an instruction to keep the reasoning short. For its missing verdicts:
  32% of its bq17 calls reach 8,192 tokens; of its 36 right-vs-wrong comparisons with a wrong majority
  or no verdict, 24 are among the 39 read, and 6 of the other 12 lack a verdict in at least 6 of 8 calls.

**Measures.** exp1 with 4 samples per ordered pair, paired question bootstrap; three 35B variants, so
98.3% intervals.

**Gates, fixed now.**
- A 35B variant is proposed for production only if TEST mixed (68) is at least +2.0 with its 98.3%
  interval above 0, READ (34) is at least −1.0, and then (`dc_spec`, `dc_rf`) Spider2 mixed is at least
  −1.5 in a separate run.
- `dc_brief` pilot: 1 sample on bq17 (506 calls). It continues to 4 samples only if calls without a
  verdict fall by at least 10 points (from 32%) and its right-vs-wrong accuracy on answered calls stays
  at 80% or more (now 82.7%). Final: bq17 mixed (65) and unread (43) against the stored 27B calls, 95%
  intervals. It changes the 27B, not production.

**Cost.** 35B: 3 variants × 4 samples × (506 + 280) = 9,432 calls in two sessions (bq17 6,072, earlier
set 3,360), about 4 h. 27B pilot: 506 calls. All on preempt, next to the judging of q36e/q36x.
