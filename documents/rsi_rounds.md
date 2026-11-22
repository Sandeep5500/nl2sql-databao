# RSI round ledger

One row per round. A rejected patch is kept in `rounds/rN/` so the next
proposer can be shown what has already failed, rather than re-proposing it.

| round | model | proposed | died at | verdict | billed |
|---|---|---|---|---|---|
| 1 | opus-5-5 | `preview_rows_default` 12 → 40: the solver re-ran identical SQL to see rows the 12-row preview hid | screening on evolve | *pending* | $0.67 + $0.01 repair |

## Baselines these are judged against

| set | n | accuracy | fallback | at cap | mean steps |
|---|---|---|---|---|---|
| synth evolve | 250 | 0.296 | 0.056 | 0.064 | 13.0 |
| synth held-out | 250 | 0.264 | 0.052 | 0.052 | 12.7 |
| LiveSQLBench | 179 | *pending job 11213559* | | | |
| Spider2 locals (sealed) | 135 | 0.474 | 0.141 | 0.141 | 16.2 |

Noise band measured on synth under a true null: accuracy 0.016, fallback 0.008,
at-cap 0.008. `--noise 0.03` is the conservative default in use.


## Round 1 notes

**Diagnosis (the proposer's own).** 56% of episodes re-ran an identical query.
It traced this to the 12-row preview default: the result prints
`[showing 12 of N rows]`, and the solver re-issues the same SQL to see the rest.
It cited seven episodes, e.g. `local_syn0672` fetching a 34-row table four
times — including one attempt that added `LIMIT 34` and was still cut to 12.

It also connected this to the known salvage defect: those repeats inflate the
identical-result clusters the fallback ranks by, so in three of the six fallback
episodes shown the salvaged answer was the over-repeated diagnostic rather than
the solver's real final query. It deliberately did **not** patch salvage in the
same round, so the effect stays attributable.

**A loop defect this round exposed.** The first patch named `preview_rows`
(the real field is `preview_rows_default`) and used a bare `@@` hunk header, so
it could not apply — and `validate_patch` passed it, because it only checked
which files were touched. Two fixes:
  - `validate_patch` now verifies every removed line exists in the target file
    and that hunk headers carry real line ranges.
  - `rsi_repair.py` feeds the errors and the numbered file back to the proposer,
    which fixed its own patch for $0.01. Hand-editing it would have made the
    human a co-author of the change being measured.

**Cost estimation was wrong.** `chars/4` predicted a 65k-token prompt; the real
count was 137k, because SQL and CSV tokenize far denser (~1.85 chars/token).
Round cost $0.67, not the $0.40 estimated. The gateway's `/key/info` spend also
lags by a minute, so it must be read after a delay.

---

## Round 1 — REJECTED (non-accept 1 of 3)

**Proposed.** Raise `run_sql_query`'s default preview, `preview_rows_default`
12 -> 40 (one field in `config.py`; `preview_rows_max` already 50, so no cap
was raised). Diagnosis: the solver re-issues identical SQL to see rows the
12-row preview hid — 56% of episodes, 1.26 duplicates each — and those
duplicates also corrupt the salvage path, which ranks by the largest cluster of
identical results (3 of 6 fallback episodes submitted the over-repeated
diagnostic instead of the real final query).

Predicted: duplicate rate falls clearly; fallback and step-cap fall secondarily;
salvage errors fall; **accuracy holds** (no gain claimed).

**Results.** Evolve screen, 250 vs 250 paired, job 11214066 (4 attempts, 2
preemptions), scored by job 11220923.

| metric | base | arm | delta | predicted? |
|---|---|---|---|---|
| duplicate queries / episode | 1.26 | 0.89 | **-0.368** | yes, and it moved |
| mean steps | 13.0 | 12.4 | -0.620 | consistent |
| mean SQL calls | 8.9 | 8.5 | -0.436 | consistent |
| fallback rate | 0.056 | 0.060 | +0.004 | **no — went the wrong way** |
| episodes at step cap | 0.064 | 0.064 | 0.000 | **no — unchanged** |
| submitted (vs salvaged) | 0.944 | 0.940 | -0.004 | **no — unchanged** |
| accuracy | 0.296 | 0.280 | -0.016 | held (within noise) |

Paired accuracy: base-right/arm-wrong 15, base-wrong/arm-right 11, McNemar
exact **p=0.557**. That 15/11 split is the measured null pattern almost exactly
(a true null on this set gave 12/8 from vLLM batch composition alone), and
-0.016 equals the measured accuracy noise band. So: no regression established,
no gain either.

**Verdict: REJECTED.** The mechanism moved and bought nothing.

**What this actually teaches.** The duplicates were never the binding
constraint. Mean steps were 13 of a 30 budget and step-cap saturation was 0.064
*before* the fix — the solver was wasting steps it had to spare. Removing waste
from a non-binding resource cannot buy solves. The proposer's second-order
hypothesis (duplicates corrupt salvage clustering) also failed: the salvage
share did not move. This is the fifth fix family to measure ~zero; see
`no-cheap-fixes-left`.

**A defect this exposed in the evaluator, NOT fixed.** `rsi_eval.py`'s accept
branches are only (a) fallback-rate drop at Fisher p<0.01 and (b) accuracy gain
at McNemar p<0.05. `dup_queries` is labelled MECH but is in no accept branch, so
a patch that only improves duplicate rate can never be accepted, and the printed
"nothing moved beyond noise" is false as written — duplicates moved -0.368
against a 0.03 band. The stated accept rule ("mechanism gain, accuracy held at
floor") is therefore broader than the code implements.

**Deliberately not changed now.** Rewriting accept rules after seeing a result
is fitting the rule to the data, which is exactly what locking the evaluator
prevents. If the rule should admit other mechanism metrics, that is decided
before round 2 is scored, applied to both rounds, and reported as a rule change.

---

# Round 2 — three parallel arms, 2026-11-20

Run in isolated copies of the tree (own `src`, own vLLM port), all three against
the same `synbase_evolve` baseline, all three on 250 of 250 episodes. Base-source
hash gate `f1f21341...` passed in every arm, so all three are attributable to
their patch and nothing else.

| | arm 1 grain gate | arm 2 salvage rank | arm 4 truncation footer |
|---|---|---|---|
| accuracy | 0.296 -> 0.272 | 0.296 -> 0.272 | 0.296 -> 0.284 |
| solves /250 | 74 -> 68 | 74 -> 68 | 74 -> 71 |
| broke / fixed | 17 / 11 | 19 / 13 | 12 / 9 |
| McNemar p | 0.345 | 0.377 | 0.664 |
| fallback | 0.056 -> 0.060 | 0.056 -> 0.048 | 0.056 -> 0.048 |
| step cap | 0.064 -> 0.080 | 0.064 -> 0.052 | 0.064 -> 0.048 |
| duplicates/ep | 1.26 -> 1.36 | 1.26 -> 1.27 | 1.26 -> 1.25 |
| mean steps | 13.0 -> 15.0 | 13.0 -> 12.8 | 13.0 -> 12.5 |

**Verdict: all three NO CHANGE / REJECTED.** Non-accept round 2 of 3.

## Each arm against the disconfirming observation it wrote in advance

**Arm 1 (submit-time grain gate).** Predicted: gate fires, steps +1.5,
accuracy +4 (range -3 to +9). Its stated disconfirmer was "revisions under 5% of
fires, **or the revised answers are net-negative** on the questions where the
gate fired."
Observed: the gate fired hard -- steps +1.96, SQL calls +1.36, step-cap +1.6pt,
duplicates +0.10, wall +38s. And accuracy fell, 17 broken against 11 fixed.
**The second disconfirmer is met.** The gate works as machinery and is
net-negative in effect: it talks the model out of more right answers than it
rescues. This is the first arm whose failure mode was predicted by its own
author and then observed.

*Reading corrected 2026-11-20 after re-reading the applied patch.* The gate does
compute values, so this is not "a self-check instead of a number". Its row count
and blank-count are correct, but its **entity count is a guess**: `_grain_check`
regex-matches the "for each X" phrase, looks for a table whose name matches it
(trying `X`, `Xs`, `Xes`, `Xies`), and reports that table's `COUNT(*)`. On a
question whose entity is a *column* of some other table, or whose phrase matches
the wrong table, the model is handed a wrong denominator stated as fact, next to
a four-point checklist telling it to reconcile its result against it. That is the
likely mechanism for 17 broken against 11 fixed, and it is a narrower lesson than
"submit-time self-checks do not work": **a self-check fed a wrong reference value
is worse than none.** The variant worth testing, if this family is revisited, is
the gate emitting only the blank-first-column count and dropping the guessed
table count entirely.

**Arm 2 (rank salvage by answer-shapedness).** Predicted +2 (0 to +4), stated as
below the MDE and wanted anyway. Its disconfirmer was "fallback-episode accuracy
does not rise, which would mean the answers were wrong anyway, i.e. a generation
problem."
Observed: no accuracy rise. But the arm's **reach** is the fallback population,
12-14 episodes of 250, while 32 questions flipped between the arms. The arm
cannot be measured in this design: its maximum possible effect is smaller than
the run-to-run flip noise. The honest verdict is not "it failed" but "this design
cannot see it". Its disconfirmer is satisfied only in the weak sense.

**Arm 4 (truncation footer -- the human's directed hypothesis).** Predicted
duplicates 1.26 -> <=0.6, episodes-with-a-duplicate 56% -> <=35%, accuracy +1.
Observed: duplicates 1.260 -> **1.252**. The mechanism did not fire at all.
Steps and SQL calls did fall (-0.52, -0.56) and wall time -40s, so the footer
changed *something* about how the agent paged -- but it did not stop the agent
re-issuing identical queries.

## The sharpest thing round 2 produced

Round 1 and arm 4 are the same finding approached from opposite sides, and
together they close F1:

| | what it did | duplicates/ep |
|---|---|---|
| R1 | **enforced** it: raised `preview_rows_default` 12 -> 40 | 1.26 -> 0.89 (-29%) |
| R2a4 | **told** the agent: footer states re-runs are identical + the exact call | 1.26 -> 1.25 (-0.6%) |

Same target, same noise band, same evolve set. Enforcement moved it 48x further
than advice. This is `enforcement-over-advice` observed a third time, and it is
now observed *within a single round* with the confound removed. Neither version
bought a solve.

**F1 moves OPEN -> CLOSED, non-costly.** Truncation does cause identical
re-runs; the re-runs cost steps; steps are not scarce; so the re-runs cost
nothing that matters. Both the enforcement and the advice variant are refuted as
accuracy levers. The user's prompting variant was the right thing to test and it
is now tested.

## The methodological blocker, stated plainly

Discordant pairs per arm: 28, 32, 21. Arm reach: ~12 episodes (arm 2) to ~30-50
(arm 1). **The noise is the same size as or larger than every candidate's reach.**
Two rounds and four arms have been spent inside a design that cannot resolve
anything under ~10 net solves, and no proposed change has claimed more than +4.

And 165 of 250 questions are wrong in **every arm of every round**. No
submit-time gate, selector or footer has converted any of them, because the
generator never produces correct SQL for them at all. That is the oracle-ablation
result in CLAUDE.md ("generation is the measured bottleneck") reappearing as the
reason the loop keeps measuring zero.
