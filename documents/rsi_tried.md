# RSI: what has been tried, and what it measured

One row per intervention, newest last. This file exists so no round re-proposes
a dead end, and so a finding is not confused with the fix that was tried for it.
**A good diagnosis can have a bad solution** — when that happens the finding
stays open here, with the solutions tried against it listed separately.

The proposer is shown a condensed form of this history in its system prompt.

## Status vocabulary

- **ACCEPTED** — moved a metric beyond noise under the pre-registered rule, held
  accuracy, confirmed on held-out.
- **INERT** — the patch did what it claimed mechanically, and bought nothing.
  The mechanism was not the binding constraint.
- **REGRESSED** — accuracy fell beyond the noise band.
- **NOT RUN** — proposed, never measured (usually a dormant component).

---

## Open findings (diagnosed, not yet solved)

### F1. Preview truncation causes identical-SQL re-runs
**Status: CLOSED 2026-11-20, non-costly.** The observation is real; both the
enforcement and the advice variant are refuted as accuracy levers. See the
"Enforcement vs advice, measured head-to-head" block below.
Original statement follows. The finding is solid and independently confirmed in the
aggregate: `run_sql_query` shows 12 rows and appends `[showing 12 of N rows]`;
**56% of episodes re-ran an identical query, 1.26 times per episode.** Seven
episodes were traced step-by-step (`local_syn0678` ran one query 4x,
`local_syn0672` fetched a 34-row table 4x and its `LIMIT 34` attempt was *still*
cut to 12).

Secondary effect claimed but **not confirmed**: duplicates inflate the salvage
path's identical-result clusters, so the fallback submits an over-repeated
diagnostic instead of the real final query. Round 1 moved the duplicate rate
29% and the salvage share did not budge (0.944 -> 0.940), so either the
mechanism is wrong or salvage is dominated by something else.

Solutions tried against F1:
| # | solution | duplicates/ep | accuracy | result |
|---|---|---|---|---|
| R1 | `preview_rows_default` 12 -> 40 (enforce) | 1.26 -> 0.89 | 74 -> 70 | **INERT** |
| R2a4 | truncation footer names the exact call (advise) | 1.26 -> 1.25 | 74 -> 71 | **INERT** |
| R2a2 | salvage ranks by answer-shapedness, dedupes SQL | 1.26 -> 1.27 | 74 -> 68 | **UNMEASURABLE** |

R2a4 is the user's own prompting hypothesis, raised 2026-11-19: "it could be done
in prompting to let the agents know that it is always by default 12 rows." It was
the right thing to test and it is now tested.

R2a2 is the salvage-dedupe idea R1 deliberately withheld. It ran, and its reach
(12-14 fallback episodes) is below the flip noise (32 discordant pairs), so this
design cannot resolve it either way. Recorded as UNMEASURABLE, not as refuted.

**Enforcement vs advice, measured head-to-head.** Same target, same evolve set,
same noise band, confound removed:

| | mechanism | duplicates/ep |
|---|---|---|
| R1 | the harness *made* the rows visible | **-29%** |
| R2a4 | the footer *told* the agent how to see them | **-0.6%** |

Enforcement moved the mechanism 48x further than advice. Third independent
observation of `enforcement-over-advice`, and the first within a single round.

**Why F1 closes anyway.** The causal chain is truncation -> identical re-runs ->
wasted steps. Steps are not scarce (13 of 30 used; 6.4% at the cap), so the last
link carries no cost. Fixing the duplicates by either route cannot convert a
wrong answer into a right one, which is exactly what both arms measured.

---

## Measured interventions

### R1 — `preview_rows_default` 12 -> 40 — INERT
Evolve screen, 250 vs 250 paired. Baseline **74/250 (0.296)**, arm
**70/250 (0.280)**. Paired: 15 broke, 11 fixed, 59 right in both, 165 wrong in
both. McNemar **p=0.557**; a true null on this set flips 20 (12/8), so 26 flips
at 15/11 is indistinguishable from a re-run.

| metric | base | arm | moved? |
|---|---|---|---|
| duplicate queries / episode | 1.26 | 0.89 | yes, -29% (the target) |
| mean steps | 13.0 | 12.4 | yes, consistent |
| fallback rate | 0.056 | 0.060 | no, wrong direction |
| at step cap | 0.064 | 0.064 | no |
| submitted vs salvaged | 0.944 | 0.940 | no |
| accuracy | 0.296 | 0.280 | no (inside noise) |

**Why it bought nothing:** steps were never scarce. Mean steps 13 of a 30 budget,
step-cap saturation 0.064 *before* the patch. Freeing a non-binding resource
cannot convert a wrong answer into a right one. **This is the lesson to carry:
reducing waste is only worth measuring where the wasted resource is exhausted.**

**What it does not refute:** F1 itself. The duplicates are real and the fix
removed them. Only the claim "removing them earns solves" was tested and failed.

---

## Standing pattern across this project

Five fix families have now measured ~zero (four post-hoc families before the
loop, plus R1). Every one of them removed waste or added a guard without adding
capability. 165 of 250 evolve questions are wrong in both arms of R1 — that
population is untouched by any plumbing change so far.

---

## Spider2 135 locals, loop configuration — 2026-11-20

**62/135 = 45.9%.** 119 submitted, 16 fallback. Job 11221102, finished 04:30.

Configuration: temp 0.0, **single pass**, 5 lanes, `--context-mode full`,
max-steps 30, branch as checked out on Babel.

**CORRECTION 2026-11-20: this run was NOT unpatched.** It ran 01:45-04:30 from
the SHARED tree, and round 1's rejected patch was still applied to that tree
until roughly 04:40. Evidence: its traces contain `showing 40 of N` 62 times and
`showing 12 of N` **zero** times, against 458 occurrences of 12 in a known
preview=12 arm. So 62/135 is effectively **the R1 arm on Spider2**, not a
baseline, and must not be cited as one. The genuinely unpatched Spider2 run is
`sp2null` (launched 2026-11-20, isolated copy, base-hash gated).

This is infrastructure defect #5 again -- the same patch, the same shared tree --
reaching a run I had already reported. The isolated-arm script fixed it for arms;
`sp2_base.slurm` was written before that and patches nothing, so it silently
inherited whatever the shared tree held. **Any job that reads the shared tree is
unattributable.** Everything must run from an isolated copy with a base-hash gate,
baselines included.

One thing recovered from it: `sp2base` and `sp2r1` are two independent runs of the
same configuration (both preview=40), so their discordant-pair count gives the
Spider2 true-null noise floor, which had never been measured.

**This is NOT the production number** and must not be reported as one. Production
is temp 0.7, 4 samples, `diff_cmp` judge on `judge-selection-nov2026`, and the
previously reported figure there is 85.6/135. The 45.9% here is the greedy
single-pass generator alone, which is what the RSI loop is trying to move. It
sits close to the 47.4% pass@1 recorded in CLAUDE.md for the 4-lane temp-0.7
configuration, which is the expected neighbourhood.

---

## Infrastructure defects found 2026-11-19/20 (all mine, all the same species)

Every one of these was a check that validated a PROXY instead of the artifact
that actually matters. Recording them because the pattern repeats.

| # | defect | what it would have cost |
|---|---|---|
| 1 | `check_applies()` reimplemented patch validation; accepted diffs GNU `patch` rejects | 3 arms died at launch |
| 2 | An **empty diff** (no +/- lines) passed validation | an arm that runs as a silent no-op and returns "no change" that reads like a finding |
| 3 | Validated patches with **macOS BSD patch**; Babel applies with **GNU patch** | arm1 applied locally, failed at hunk 3 on Babel |
| 4 | Validated against the **local** repo, not Babel's tree | masked defect 5 |
| 5 | **Round 1's rejected patch was left applied** in the shared Babel tree (`preview_rows_default` still 40) | all round-2 arms would have been measured against a different base than `synbase_evolve`, silently invalidating every comparison |
| 6 | `export ARM ROOT` placed **after** the gate heredoc that reads them | 3 arms exited in 2s; a full night of parallel capacity lost |
| 7 | Scoring ran `rsi_eval.py` over `$R/results/*.csv` from a **login node**, where `/data/user_data` is not mounted | a verdict of "no episodes matched" presented as a result |
| 8 | `.gwkey` holds a shell `export` line; `cat`-ing it sent `export OPENAI_API_KEY=...` as the bearer token | proposer calls 401'd |

Fixes now in place:
- validation defers to `patch(1)` itself, run **on Babel**, with `--fuzz=0`
- an empty diff is refused, not repaired
- diffs are **regenerated** with `diff -u` from the applied content, so the
  proposer owns the change and tooling owns the arithmetic (`rsi_fix_hunks.py`
  and the regen step)
- every arm asserts a **base hash** of the pre-patch source before running, so a
  drifted shared tree halts the arm instead of producing an unattributable number
- arms run from **isolated copies** (`rsi_arm_iso.slurm`), each on its own port
- scoring runs **inside a job** (`r2_score.slurm`)

**The deeper lesson:** `rsi_arm.slurm` patched the shared working tree in place.
That is what left round 1's patch applied and what made parallel arms impossible.
Isolation was not an optimisation for parallelism; it was a correctness fix.

---

## Round 2 interventions — 2026-11-20

All three isolated, all 250/250 episodes, all against `synbase_evolve`,
base-hash gate passed.

| arm | change | predicted | measured | status |
|---|---|---|---|---|
| r2a1 | submit-time grain check gate (`agent.py`) | +4 (-3..+9) | -6 solves, 17 broke / 11 fixed | **REGRESSED (within noise)** |
| r2a2 | salvage ranks answer-shapedness, not cluster size | +2 (0..+4) | -6 solves; reach 12 ep < noise 32 | **UNMEASURABLE** |
| r2a4 | truncation footer states the exact call | +1 (-2..+3) | -3 solves; duplicates flat | **INERT** |

**Arm 1 is the one that taught something.** It was the only arm reaching the 165
always-wrong questions, its gate demonstrably fired (steps +1.96, SQL calls
+1.36, step-cap +1.6pt, wall +38s), and it still lost ground. Its author named
this exact outcome in advance as a disconfirmer: "the downside is the gate
talking the model out of correct answers." It did. A verification prompt
delivered at submission time to a 9B model is net-negative: it rescues some wrong
answers and corrupts more right ones.

Note the asymmetry with the rubric row-count gate, which arm 1's own diagnosis
called "the one gate here that worked -- 13 for 13 when it fired." The rubric
gate's count comes from the planner's reading of the question. Arm 1 computes
too, but its main number is a **guess**: `_grain_check` regex-matches the
"for each X" phrase, looks for a table whose name matches it (trying `X`, `Xs`,
`Xes`, `Xies`), and reports that table's `COUNT(*)` as the entity count --
frequently the wrong denominator. So the mechanism is a confidently stated
**wrong** number beside a four-point checklist telling the model to reconcile
against it, which is an efficient way to talk it out of a correct answer. The
lesson is narrower than "submit-time self-checks fail": **a self-check fed a
wrong reference value is worse than none.** Untested variant, if this family is
revisited: the gate emitting only the blank-first-column count (always computed
correctly) and no guessed table count.

## The design limit that now dominates everything

Discordant pairs per arm in round 2: **28, 32, 21.** No candidate change in two
rounds has claimed more than +4 net solves. Temp 0.0 is not deterministic here
(vLLM batch composition flips ~8% of questions between identical runs; a true
null measured 20 flips), so:

**the run-to-run noise is larger than the reach of every intervention proposed
so far.** This is not a reason to run more arms. It is a reason to stop
proposing changes of this size, or to change the measurement.

Options for changing the measurement, none free:
- more lanes per arm -> forbidden, topology must match the baseline exactly
- repeat each arm n times and pool -> n x 3h per arm, and still only halves the
  noise at n=4
- pick targets with reach >> 10 episodes -> the only cheap option, and it rules
  out every fix family tried so far

## Why the loop keeps measuring zero (the structural reason)

**165 of 250 questions are wrong in every arm of every round.** Six interventions
across two rounds have converted none of them. They are not lost to truncation,
step budget, salvage selection or missing verification -- the generator never
emits correct SQL for them at all.

This is the oracle ablation in CLAUDE.md restated: *generation is the measured
bottleneck, selection is the open gap.* The RSI loop has spent both rounds
patching the harness around a single greedy generation pass, which is the one
place with neither headroom nor measurement resolution.

Measured headroom that exists today, for contrast:
- pass@1 on the 135 locals: 47.4%
- **pass@4: 94/135 = 69.6% solved by at least one lane**

That 22-point gap is selection, it is already paid for by sampling, and it is
~30 questions wide -- three times the detection floor. No harness patch proposed
in rounds 1-2 was within an order of magnitude of it.
