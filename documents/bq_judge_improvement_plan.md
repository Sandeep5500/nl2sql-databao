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

**Amendment (Nov 18, 11:55; before any round-2 call).** The user asked to move the free GPUs from the 27B on
SQLite to BigQuery: the 27B's q36e/q36x jobs were cancelled (the 35B's run continues).
- The bq17 35B arm stays in one session (it had started before it could be split).
- `dc_brief`'s samples 1–3 run next to the pilot (sample 0). They are used only if the pilot passes its bar.
- Added: **the 27B with a 16,384-token reply budget** (`diff_cmp`, otherwise as the Nov 17 run), 4 samples on
  bq17 (2,024 calls; the server's 49,152-token context holds the longest prompt plus 16,384). Reported on
  bq17 mixed (65) and unread (43) against the 27B at 8,192 tokens and the 35B pooled, with its share of
  calls without a verdict and its right-vs-wrong accuracy on answered calls. It measures how far the 27B
  gets when it can finish (the §10 simulation put break-even with the 35B at about 53% of its truncated
  calls right). It changes no production setting by itself.

**Amendment 2 (Nov 18, 16:20; after the 35B variants were scored, before the two runs below were).**
- No round-2 35B variant passes the gate (results below), so no Spider2 run follows.
- Added: **the deployed `diff_cmp` judged again on the earlier set** (4 samples, 1,120 calls, the same
  comparisons and settings as the morning session). On the earlier set every variant of both rounds
  gains (+1.4 to +2.7 on its 25 unread pools) while on bq17 the round-2 variants lose (−1.5 to −0.7 on
  43), and on those 43 pools two runs of `diff_cmp` already differ by −1.3 [−2.9, −0.1]. Reported: the
  rerun minus the morning session on the 25 unread and all 37 mixed pools, and every variant against
  both sessions pooled (8 samples per ordered pair). It changes no decision.
- The 27B's 16,384-token jobs were preempted and requeued (samples 1–3: 5, 2 and 1 times). Calls in
  flight at a preemption are drawn again, and the calls in flight are mostly the long ones, so the
  redraws favour replies that finish with a verdict. Sample 0 ran without a preemption. Reported:
  sample 0 alone as the clean estimate, then all four samples with the number of calls drawn again
  (from the start logs, which cover every restart after the first).

## Round 2 results (Nov 18, evening)

Details: [judge_results.md](judge_results.md) §13; running log `results/bq17/improve/RESULTS.md`.

- **35B variants: none passes the gate.** TEST (68), against the baselines fixed in the plan (98.3%):
  `dc_spec` +1.5 [−1.5, +4.7], `dc_rf` +0.9 [−3.1, +4.9], `dc_full` +1.7 [−1.2, +5.3]; READ (34) +0.9,
  +0.5, +0.4. All three lose on bq17's 43 (−1.1, −1.5, −0.7) and gain on the earlier set's 25 (+2.6,
  +2.4, +2.4). No Spider2 run; production stays on `diff_cmp`.
- **Same-prompt rerun on the earlier set (amendment 2):** +1.6 [+0.3, +3.2] over the morning session on
  the 25 unread pools; the morning baseline was a low draw. With both runs pooled on each set, TEST is
  +0.6 [−2.2, +3.2], −0.1 [−4.0, +3.6] and +0.7 [−1.7, +3.5].
- **27B `dc_brief`: fails its bar** (no verdict 21.9% against a bar of 21.7%; 80.8% right on answered
  right-vs-wrong calls); exploratory, 2 samples: −0.7 [−2.8, +1.0] on bq17's mixed pools.
- **27B with 16,384 tokens** (samples 0, 2, 3; sample 1 cancelled after 5 preemptions): no verdict 31.7%
  → 7.8%, answered right-vs-wrong 82.7% → 80.2%, all 204 114.0 against 115.5 (−1.6 [−4.2, +0.7] on the
  mixed 65); sample 0 alone, which ran without a preemption, 116.0 (+0.5 [−3.7, +4.4]).
- **Reading.** Neither prompt changes nor a larger budget improves the judge on BigQuery measurably. Both
  BigQuery sets are now used for development.

## Round 3: acting on the error analysis, 35B only (Nov 18, evening; written before any round-3 call)

The user asked to try the actionable findings (judge_35b_improvement.md, judge_results.md §11 and §13, the gold audit
in `nl2sql-v2/reports/Spider2 Lite BigQuery gold errors.md`) on the 35B, and to report the official numbers and the
numbers under the audit's corrected labels.

**Arms.**
- **A. Ask twice + superset rule** (no new calls): two calls per ordered pair, votes averaged, then the superset
  rule. Scored from the stored samples (k = 2 drawn from 8), as in `results/bq17/headroom/`.
- **B. `dc_facts`**: `diff_cmp` plus a short "dataset notes" section for BigQuery questions: facts from each
  dataset's official documentation (what one row is, which columns identify an entity, special codes and flags,
  units and scales, time zones and precision, nested fields whose values repeat on child rows). Built before any
  call, for every dataset that appears in a mixed pool of either set (44 datasets), by one fixed procedure: the
  writers see the schema the judge sees, Spider2's reference docs and the web, never the gold files, the
  questions' answers, our judge calls or the error readings; facts only, no advice (advice hurt the agent in
  October). SQLite prompts are unchanged.
- **C. Listwise**: for questions with three or four distinct results, one call shows every result (numbered,
  with SQL, result preview and the computed comparison of each pair) and asks which one answers the question,
  with `diff_cmp`'s steps and rules adapted to several candidates. Four samples per question, the candidate
  order rotated each sample. Two-result questions keep the deployed round-robin. A sample without a valid pick
  falls back to the deployed round-robin for that question.

**Sets and baselines.** bq17 (204 questions, 65 mixed) and the earlier BigQuery set (105, 37 mixed); baseline the
deployed `diff_cmp` with both runs pooled on each set (8 samples per ordered pair). 4 samples per ordered pair (B)
or per question (C).

**Measures.** exp1 on all questions of each set; the gate uses both sets' mixed pools together (102), paired
question bootstrap, 97.5% intervals (two new-call arms). Reported for every arm, without affecting the gate:
bq17 under the audit's strict and lenient corrected labels (`nl2sql-v2/scripts/bq_corrected_labels.py`); both sets
without the seven questions whose official label rewards an arbitrary choice (bq035, ga010, bq002, bq424, bq055,
bq397, bq208); for B, also without the four questions that motivated it (bq045, bq356, bq051, bq389); and the
combinations with A (k = 2 averaging and the superset rule on B's calls; majority of two listwise samples on C).

**Gates, fixed now.** B or C is proposed for production only if the 102 mixed pools gain at least +2.0 with the
97.5% interval above 0, against the pooled baselines. C changes SQLite pools too, so it would then need a SQLite
run with mixed pools at least −1.5 before production; B leaves SQLite prompts unchanged. A's decision is about
cost (2x judge calls), from the numbers already measured.

**Cost.** B: 4 × (506 + 280) = 3,144 calls; C: about 4 × 85 = 340 calls; one 35B session on preempt (lilab has a
queue), about 3 h.

## Round 3 results (Nov 18, night)

Scores: `results/bq17/round3/score_r3_final.txt` (`score_r3.py`); notes `results/bq17/round3/facts/` (44 datasets,
compiled to `facts.json`). All arms complete with 4 samples; the `dc_facts` sessions ran without a preemption, the bq17
listwise session was preempted once (64 of its 220 calls drawn again).

| | gate: both sets' mixed pools (102), 97.5% | bq17 mixed (65) | earlier set mixed (37) |
|---|---|---|---|
| A ask twice + superset rule (no new calls) | +1.9 [−0.1, +4.1] | +1.5 [+0.2, +3.0] | +0.4 [−0.8, +1.5] |
| B `dc_facts` | +2.2 [−2.6, +7.2] | −0.4 [−4.5, +3.8] | +2.6 [+0.8, +4.5] |
| C listwise | +0.8 [−4.5, +6.3] | −0.8 [−3.9, +2.1] | +1.7 [−1.9, +5.4] |
| B + A (combination, not gated) | +4.4 [−1.0, +10.1] | +0.8 [−3.5, +5.5] | +3.6 [+1.5, +6.0] |
| C + A (combination, not gated) | +0.4 [−3.3, +3.8] | +0.4 [−2.4, +2.7] | +0.0 [−2.1, +2.0] |

- **Neither B nor C passes the gate**: B reaches +2.2 but its interval includes zero, and on bq17 it loses 0.4. No SQLite
  run follows; production stays on `diff_cmp`.
- **B helps where the deciding fact is in the notes and costs elsewhere.** On bq17 it fixes bq356 (0.02 → 1.00, the
  station key) and bq051 (0.00 → 0.73, the GHCN flags), and loses bq407 (−1.00), bq199 (−0.62), ga004 (−0.55),
  ga032 (−0.38) and bq424 (−0.37); bq045 falls from 0.17 to 0.06. Without the four questions that motivated it, B is
  +0.3 [−3.0, +3.5] on both sets. On the earlier set its gains are in Stack Overflow, sdoh and covid19_usa questions.
- **C does worse where it was meant to help**: on bq17's 14 questions where all four tries differ and one is right
  it scores 4.8 against 5.6.
- **bq17 totals (of 204), official / strict / lenient corrected labels:** deployed 113.2 / 114.9 / 118.8 (55.5% /
  56.3% / 58.3%); A 114.7 / 116.7 / 120.5 (56.2% / 57.2% / 59.1%); B 112.8 / 115.9 / 117.7; B + A 114.0 / 117.6 /
  118.9; C 112.4 / 113.9 / 118.4; C + A 113.6 / 115.6 / 119.8. Earlier set (of 105): deployed 27.7, A 28.1, B 30.3,
  B + A 31.4, C 29.4, C + A 27.8.
- **Reading.** Once more the two BigQuery sets disagree (bq17 flat, the earlier set positive). The only change that
  is positive on both BigQuery sets and on SQLite is A, asking twice with the superset rule; its decision is about
  cost.
