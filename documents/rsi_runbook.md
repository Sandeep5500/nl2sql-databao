# RSI runbook

State as of 2026-11-19. Goal: be able to run an RSI round.

**The loop can run.** Baselines exist, the evaluator passes its null tests and
now refuses invalid comparisons. Read "What the overnight runs settled" before
proposing the first arm -- one assumption in the original plan was wrong.

## What RSI means here

The solver (Qwen3.6-35B) is frozen. What evolves is the harness. One round is:
run → score → diagnose → propose a harness change → run the arm → accept or
reject against a pre-registered rule → commit or discard.

## The three sets

| set | what | rule |
|---|---|---|
| **evolve** | 250 synthetic questions, split by database | propose against this |
| **held-out** | 250 synthetic questions, disjoint databases | every accept/reject decision |
| **test** | the 135 Spider 2.0 locals | **SEALED.** Never touched during the loop. Reported once. |

Split by *database*, not question: two questions on one schema share its tables,
keys and quirks, so a lesson on one transfers and the held-out stops being held out.

## Data: `synthroot_full`

`/data/user_data/juliep2/synthroot_full` is a Spider 2.0-shaped data root, so the
**unmodified harness** reads it — every path derives from `NL2SQL_DATA_ROOT`, and
`score_against_gold` finds gold by filename alone. Nothing in `nl2sql-v2` changed.

```
Spider2/spider2-lite/
  spider2-lite.jsonl                             instance_id = local_syn0001
  resource/databases/spider2-localdb/*.sqlite    symlinks -> synsql/filled
  evaluation_suite/gold/exec_result/*_a.csv      gold, executed with sqlite3
  evaluation_suite/gold/spider2lite_eval.jsonl   ignore_order: true
  splits/{evolve,heldout,reserve}.txt
```

Built by `prep_synth_root.py` (on Babel at `/home/juliep2/`). Idempotent.

**861 gated → 676 clean.** 185 excluded for mechanically defective gold:
108 duplicate column (two columns holding identical values, e.g. `MAX(row_number())`
alongside `COUNT(*)`), 42 constant-1 column, 19 all-zero numerics, 16 no preview.
That defect rate is ~20% and is uniform across buckets, so it is a generation-pipeline
flaw, not one bad template.

Caveats that are **not** fixed:
- Gold is model-written (`gpt-5.4-mini`). The synthesis gate checked *shape* only
  (a second model stated expected rows/cols blind to the SQL), so semantic errors
  survive. Synth accuracy is directional; it is a floor, not a headline number.
- 18% of gold uses SQLite-only functions (`julianday` in 134 of 861). Gold is
  therefore executed with `sqlite3`, never through the agent's DuckDB path.
- Synth has **no DCE index**, so it cannot run `--context-mode search`. All synth
  runs use `--context-mode full`, and any comparison against locals must run the
  locals with the same flag.


## LiveSQLBench-Base-Lite: the human-verified set

`/data/user_data/juliep2/lsbroot` — **179 questions over 18 databases**,
built by `prep_lsb_root.py --verify`, installed and load-checked on Babel.

Human-verified gold, which is exactly what the synthetic set lacks. Source: the
BIRD team's emailed gold/knowledge/testcase file plus the HuggingFace half
(`birdsql/livesqlbench-base-lite-sqlite`); the two align on all 270 ids.

### How 270 became 179

| step | left | why |
|---|---|---|
| all records | 270 | |
| Query only | 180 | the 90 `Management` golds are CREATE/ALTER/UPDATE/DELETE, unscorable by result comparison |
| gold executes, sane size | **179** | `virtual_7`'s gold returns 1,028,196 rows — a join fan-out for a per-fan question |

### A correction worth reading: do NOT exclude on gold-SQL dialect

An earlier version of this root held only 98 questions, having dropped 55 whose
**gold SQL** would not run in DuckDB. **That was wrong.** The agent never runs the
gold SQL — it writes its own query against the same gold CSV. Gold using
`julianday` is perfectly answerable with DuckDB date arithmetic, so a dialect
error in the gold says nothing about whether the question is solvable.

Loading is also a non-issue: `Database` does `ATTACH '<f>.sqlite' (TYPE sqlite)`
and DuckDB reads SQLite files fine.

`--verify` therefore **classifies and keeps**, writing `engine_notes.jsonl`:

| class | LiveSQLBench | synth (673) | meaning |
|---|---|---|---|
| gold replays in DuckDB | 98 | 500 (74%) | cleanest |
| gold is SQLite-only | 55 | 149 (22%) — 100 `julianday` | **still solvable** |
| values differ | 26 | 24 (4%) | check tolerance/ordering |

Usable: **LiveSQLBench 179**, **synth ~649 of 673** (evolve 243/250, held-out
237/250). My earlier "45% of LiveSQLBench unusable" and the implied synth loss
were both artifacts of the invalid test.

### The scorer fix, now applied and measured

`eval.py` now carries `NUMERIC_REL_TOL = 1e-6`, passed alongside the absolute
bound. **Measured on the 135 locals** by re-executing every stored SQL and
scoring the byte-identical prediction under both tolerances — 2029 distinct
(question, SQL) pairs from 210 results files, 184 seconds, no GPU:

| | |
|---|---|
| pairs scored | 2029 (5 could not re-execute) |
| flips | **7, all wrong → right** |
| **regressions** | **0** — the fix only widens, so this had to be 0 |
| distinct questions recovered | **2: `local285`, `local299`** |

`local299` flipped under **six different** stored SQLs, so that question was
*systematically* unscorable: it aggregates money over many rows, exactly the
large-magnitude sum the absolute bound mishandles. Effect on any single run is
+1 to +2 questions (~+0.7 to +1.5 points).

Backup of the previous scorer is on Babel at `eval.py.pre_reltol`.

### The one genuinely unmatchable case

DuckDB sums floats in a different order than SQLite, giving ~1e-8 *relative*
error. `eval.py:40` is `math.isclose(a, b, abs_tol=1e-2)`, which silently keeps
`isclose`'s default `rel_tol=1e-09`. At magnitude 3.5e6 a 0.08 absolute gap fails
both bounds, and **no query the agent can write will match**. Adding
`rel_tol=1e-6` recovered 4 on LiveSQLBench and lost nothing.

Not applied: `eval.py` scores the sealed Spider2 set, so loosening it is a
baseline change. It is a bug, not a loosening, but it is your call — measure on
the 135 locals first.

### Two scoring decisions, both measured

- **`ignore_order: true` on every question.** 118 of 180 golds carry an
  `ORDER BY`, but those orderings have ties that SQLite and DuckDB break
  differently. Enforcing order failed **25 of 124 correct answers** on an
  arbitrary tie-break. The agent is tested on computing values, not on
  reproducing one engine's tie order.
- **The whole knowledge base, never the oracle subset.** Each question ships
  `external_knowledge: [0, 50]` — pointers to ~2.5 of its database's 49–86
  entries. Handing the agent exactly those would tell it which definitions
  matter. Instead each question points at its database's full KB
  (`resource/documents/<db>_kb.md`, 3.8k–6.7k tokens) and must find the relevant
  definitions itself. The oracle subset is kept in `oracle_knowledge.jsonl` for
  offline diagnosis only.

### Its role

At 179 questions over 18 databases it is large enough to be a real decision set,
not just a trust check.

| set | n | usable | gold | role |
|---|---|---|---|---|
| synth evolve | 250 | 243 | model-written | propose |
| synth held-out | 250 | 237 | model-written | accept/reject |
| **LiveSQLBench** | **179** | **179** | **human-verified** | confirm + report |
| Spider2 locals | 135 | — | official | **SEALED** |

No overlap anywhere: LiveSQLBench's 18 databases are disjoint from both synth's
and Spider2's.


## Branch provenance, and the switch at the end

**The loop runs on `dev-juliep2-ablation` at 516ce01**, with uncommitted local
modifications on top. Decided 2026-11-19, with the alternative (rebasing onto
`judge-selection-nov2026`) considered and rejected on cost.

*Correction, 2026-11-20:* this section and the memory note previously said
`dev-juliep2`. The cluster tree at `/data/user_data/juliep2/nl2sql-databao` is
actually on `dev-juliep2-ablation` (516ce01). The error was never caught because
`/data/user_data` is not mounted on login nodes, so the branch could not be read
from where it was being asserted -- the same class of mistake as every other
defect in `rsi_tried.md`. Rounds 1-2 are unaffected: every arm was gated on the
base-source hash `f1f21341...`, which pins the actual source content regardless
of what the branch is called. The table below is labelled by what the tree
contains, which was verified by diff, not by branch name.

`judge-selection-nov2026` is the branch carrying the deployed judge. Its
`diff_cmp` prompt has been the default in `select_answer.py` since 2026-11-13,
and it is the first judge win to pass a pre-registered test: +7.2 close-call
pools, 97.5% CI [+1.9, +13.0], whole-benchmark expected 293.4 -> 305.6 of 540
(about +3 per run set). That branch is 151 files and ~30.5k insertions ahead.

What it changes that matters to this loop -- not the judge, but the LIVE agent:

| file | the cluster tree (here) | `judge-selection-nov2026` |
|---|---|---|
| `db.py` optimizers | `cte_inlining` | `cte_inlining,common_subplan` |
| mixed-type retry | `Mismatch Type Error` | + `Conversion Error` |
| `config.py` | `NL2SQL_DATA_ROOT` (ours) | adds `NL2SQL_DATASET_DIR` |
| judge prompt | old `PAIRWISE_PROMPT` | `diff_cmp` |

`common_subplan` on DuckDB 1.5.5 **silently returns wrong results** -- it merges
scans of two same-shaped SQLite tables under one filter (duckdb#24781) and
UNION ALL arms sharing a join (#25819); #26427 is open on 1.5.6. The branch
measured 3 wrong exploration results over the stored traces, no score changed.
**This loop runs with that optimizer enabled.** The agent therefore sees wrong
tool output occasionally, in both the baseline and every arm.

Why that is tolerable here, and where it is not:
  - it hits base and arm **equally**, so the paired comparison stays valid;
  - the stale judge costs exactly nothing, because the judge never executes in
    a single-pass configuration;
  - switching would invalidate `synbase_evolve` -- base and arm must differ
    only by the patch -- forcing a full baseline re-run for a change measured
    at zero score impact.

**The obligation this creates.** The final production validation (temp 0.7,
4 lanes, `diff_cmp` judge, sealed 135 locals) MUST run on
`judge-selection-nov2026` with the accepted patches applied. A generator patch
tuned against this `db.py` is not guaranteed to transfer to that one, and the
transfer is a hypothesis to test, not an assumption to state. Any headline claim
has to come from that run, not from the loop's own numbers.


## The round protocol

A **round** is one patch tested end to end. The recursion is across rounds: an
accepted patch is committed and becomes the next round's baseline.

Three nested things, because "loop" is ambiguous:

| level | what | size |
|---|---|---|
| episode | the agent solves one question, <=30 steps | 1 question |
| run | every question in a set, 5 lanes | 250 questions ~= 3h |
| **round** | propose one patch, test it, accept or reject | 1-3 runs |

### Three stages, cheapest first

| stage | set | cost | gate to pass |
|---|---|---|---|
| **1. screen** | evolve 250 | ~3h | did anything move beyond noise? deliberately permissive |
| **2. decide** | held-out 237 | +~3h | the real accept/reject, `rsi_eval.py` verdict |
| **3. confirm** | LiveSQLBench 179 | +~2h | human-verified gold does not regress -- **DEFERRED**, no baseline run yet |

Most rounds die at stage 1 for **~3h**, not ~6h. Only serious candidates reach the
held-out set, and only a patch about to be committed reaches LiveSQLBench.

**Measured, not estimated.** The null replicate `synnull` (job 11209486) ran the
held-out split alone -- 250 questions, 5 lanes -- in 4 min of model load plus
**2h58 of benchmark**. An earlier version of this table said 1h per run, which was
a guess and was wrong by 3x; it set a job walltime that would have died 30 minutes
short of finishing. One round at full depth (screen + decide) is therefore most of
a working day, not an afternoon.

**Stage 3 is deferred.** The LiveSQLBench baseline was cancelled before it ran
(job 11213559, 2026-11-19), so there is no LSB reference to compare an arm against.
Stage 3 cannot execute until that baseline is run. Until then the loop is: synth
evolve decides, synth held-out confirms, and no human-verified-gold check exists.

### Why staged, and not just "run both every round"

**The held-out set erodes every time it is looked at.** Deciding on the same 237
questions across 20 rounds is 20 multiple comparisons, and at p<0.05 roughly one
false accept is expected from luck alone. Screening on evolve keeps the number of
held-out looks down to the few patches that earned one.

The cost of staging: a patch can pass the screen on evolve noise. That is
acceptable -- the screen's job is to kill guaranteed no-ops cheaply, not to
decide. The decision still happens on data the proposer never saw.

### One round, concretely

```bash
# 1. diagnose -- no GPU, reads the baseline run we already have
python scripts/analysis/rsi_diagnose.py \
    --results "results/synbase_evolve_*.csv" \
    --traces  "logs/traces/synbase_evolve_*" \
    --out rounds/r1/bundle.md

# 2. propose -- CMU gateway, Opus 5.5, cost read from /key/info
OPENAI_API_KEY=sk-... python scripts/analysis/rsi_propose.py \
    --bundle rounds/r1/bundle.md --out-dir rounds/r1

# 3. apply, only if validation passed
cd nl2sql-v2 && git apply --check rounds/r1/arm.patch && git apply rounds/r1/arm.patch

# 4. screen on evolve, then score against the baseline
sbatch slurm/rsi_arm.slurm        # TAG=r1 SPLIT=evolve
python scripts/analysis/rsi_eval.py \
    --base "results/synbase_evolve_*.csv" --base-traces "logs/traces/synbase_evolve_*" \
    --arm  "results/r1_evolve_*.csv"      --arm-traces  "logs/traces/r1_evolve_*"

# 5. promote to held-out ONLY if the screen moved something
# 6. confirm on LiveSQLBench ONLY if we are about to commit
```



### Decision: the loop improves the GENERATOR, single-pass

Fixed 2026-11-19. The loop runs **one greedy pass per question, no judge**:
`--temperature 0.0`, one episode per question, `LANES=5` being shards of the
question set rather than samples of it. `pass@any` equals `accuracy` in every
baseline, which is the proof.

This is **not** the configuration that produces the headline number:

| | this loop | the reported setup |
|---|---|---|
| temperature | 0.0 | 0.7 |
| samples per question | 1 | 4 |
| judge | none | `diff_cmp` selects |
| locals | 47.4/135 | 85.6/135 |

Chosen deliberately, because generation is the **measured** bottleneck (the
oracle ablation) while selection is the known gap. Improving the generator under
a fixed decoder is a clean, attributable claim.

**What this scopes out, and must be said when reporting:**
- the judge, selector, critic and rubric never execute, so the loop structurally
  cannot propose against them -- the 8.4-point selection gap is out of scope
- a gain measured at temp 0.0 single-pass is not automatically a gain at temp 0.7
  pass@4, where the judge can already rescue a bad single answer

**Final validation step, required before any headline claim:** take the
accumulated accepted patches and run the production configuration (temp 0.7,
4 lanes, judge) on the sealed 135 locals, once. A generator gain should compound
with selection, but that is a hypothesis to test, not an assumption to make. If
it does not transfer, the honest result is "improved the generator, no effect on
the delivered score".

### Stopping rule — binding

**Three consecutive rounds with no accept: stop the loop and diagnose the setup
instead of proposing again.**

A run of nulls is evidence about the *setup*, not a reason to try harder. When it
fires, the questions to ask, cheapest first:

| suspect | how to check |
|---|---|
| **dataset** | is the remaining headroom real? how many failures are gold-wrong rather than agent-wrong? |
| **dialect / engine** | are correct answers being scored wrong? re-run the gold-vs-agent-path check |
| **detection floor** | MDE is ~4 points on 250. Is the effect size we want simply invisible here? |
| **dormant surface** | the judge, rubric and critic never execute in this configuration. Is the real gap in a component the loop cannot touch? |
| **proposer** | is it producing weak patches, or good patches the harness ignores? compare models on one bundle |

The loop has already measured that four post-hoc fix families give ~zero, so a
null streak is a live hypothesis that the remaining gap is capability, not
harness. Record which suspect the streak pointed to before restarting.

### The ledger

Every round appends one row to `documents/rsi_rounds.md`: round, model, what was
proposed, which stage it died at, the verdict, and the gateway-billed cost. A
rejected patch stays in `rounds/rN/` so the next proposer can be told what has
already failed -- otherwise the loop re-proposes it.

### Accounting

- ~20 rounds, most dying at the screen: **~25-30h of A6000**, over several days.
- API: read from the gateway per round, not estimated. Key was at **$21.51** when
  the loop was built, against a self-imposed $50 ceiling.

## Fitness: `rsi_eval.py` — LOCKED

The proposer may not edit it. Two rules are built in:

1. **Accuracy is a floor, not a target.** Mechanism metrics are the fitness signal
   because accuracy's MDE is hopeless at these sample sizes — but every mechanism
   metric has a degenerate optimum (minimise fallback by submitting the first query
   instantly). An arm whose accuracy falls beyond the noise band is rejected
   regardless of how good its mechanism numbers look.
2. **No single metric decides.** The verdict names which rule fired.

Metrics: accuracy, pass@any, fallback rate, step-cap saturation, probe share in the
last 5 queries, duplicate queries, submitted-vs-salvaged, steps, SQL calls, wall time.

**Noise band, measured on the population the loop actually judges.**
`synnull` vs `synbase`: held-out, 250 identical questions, identical config,
so every delta below is pure noise.

| metric | noise delta | baseline | usable? |
|---|---|---|---|
| accuracy | **0.016** | 0.264 | yes — floor only |
| fallback rate | 0.008 | 0.052 | yes — 6x headroom |
| at step cap | 0.008 | 0.052 | yes |
| duplicate queries | 0.016 | 1.13 | yes |
| probe share, last 5 | **0.031** | 0.122 | **NO — diagnostic only** |
| mean wall seconds | **2.3x** | 83 -> 194 | **NO — diagnostic only** |

Two consequences, both now enforced in the evaluator:

- **`probe_share_last5` and `mean_wall_s` cannot carry a verdict.** Probe share
  moved 0.031 on noise alone, as large as any plausible real effect; wall time
  more than doubled purely from cluster load. Both are labelled `DIAG`.
- **Temperature 0.0 is not deterministic here.** 20 of 250 questions flipped
  outcome between two identical runs (12 one way, 8 the other, McNemar p=0.50) —
  an 8% per-question churn from vLLM batch composition, not from sampling. So
  **the paired McNemar is the real accuracy test, not the rate difference.** With
  ~20 discordant pairs arising from noise, clearing p<0.05 needs roughly a 15-5
  split: an accuracy MDE of about **+10 net solves on 250 questions (~4 points)**.
  Anything smaller is invisible, which is exactly why fitness is mechanism-led.

The earlier 0.03 band (4 lanes of `q36re` on the 135 locals at temp 0.7: mean
pairwise 0.016, max 0.030) is corroborated but was measured on the wrong
population and temperature. `--noise 0.03` is kept as the conservative default,
since the synth null gives one pair at 0.016 and one pair is weak evidence.

Validated by a **null test**: fed two lanes of the same config it returns
"NO CHANGE" (McNemar p = 0.70). An evaluator that cannot pass a null test cannot
be trusted to judge an arm.

## Commands

```bash
# one run's profile
python3 rsi_eval.py --run "results/synbase_evolve_*.csv" \
                    --traces "logs/traces/synbase_evolve_*"

# an arm against the baseline (this is the accept/reject decision)
python3 rsi_eval.py --base "results/synbase_heldout_*.csv" \
                    --base-traces "logs/traces/synbase_heldout_*" \
                    --arm  "results/<arm>_heldout_*.csv" \
                    --arm-traces  "logs/traces/<arm>_heldout_*" \
                    --noise 0.03
```

An arm run reuses `baseline.slurm` with the patch applied and a new output tag.

## Where to search for changes

Every success in this project has been a **mechanism**; every failure has been
**text**. Rank proposals accordingly.

| worked | failed |
|---|---|
| step budget 30→60 (fallback 0.44→0.11, p=2e-7) | facts added to the system prompt (used 1/24) |
| rubric row-count gate (13-for-13 when advised) | declared assumptions shown to the judge (−1) |
| scalar-unwrap filter (80→81) | diff-facts prose, bigger judge, fine-tuned A/B |
| `diff_cmp` tool for the judge (+~12 over majority vote) | 8 mechanical output transforms (0/20) |

So: edit gates, filters, budgets, salvage logic and tool *behaviour*. Do not spend
rounds on prompt wording.

Known open defect worth an early round: the fallback salvage ranks candidates by
largest cluster of identical results, which under a doubt spiral selects the
most-repeated diagnostic `COUNT`. Fix candidates, cheapest first: weight clusters by
distinct normalised SQL rather than repetitions; filter by the rubric's expected row
count; keep a standing answer-shaped candidate and submit it at `max_steps - K`.

## What the overnight runs settled

### The baselines (these are the numbers an arm is judged against)

| split | n | accuracy | fallback | at cap | mean steps |
|---|---|---|---|---|---|
| **evolve** | 250 | 0.296 | 0.056 | 0.064 | 13.0 |
| **held-out** | 250 | 0.264 | 0.052 | 0.052 | 12.7 |
| locals control | 135 | 0.474 | 0.141 | 0.141 | 16.2 |

### Synth is a valid evolve set, but not for the reason the plan assumed

The plan predicted synth might be *too easy*. It is the opposite: accuracy is
**0.252 vs 0.474** on the locals under an identical config. But the mechanism
profile is *quieter* -- fallback 0.082 vs 0.141, 13.4 steps vs 16.2. The agent
fails **fast and confidently**: 89% of synth failures were `submitted`, not
salvaged, against 76% on the locals.

Three causes, measured:

1. **Width compounding.** Synth gold averages 4.9 columns (median 5, 25% have
   >=7); the locals average 3.1 (median 2). The scorer requires *every* gold
   column to match, so a 9-column question is nine ANDed sub-questions.
   Measured on synth: <=3 columns -> 32.8% accuracy, >=7 columns -> 17.7%.
2. **Over-specification.** Synth questions average 425 characters against the
   locals' 312, and 48% use explicit multi-step phrasing ("first compute X,
   then...") against 36%.
3. **Residual gold error.** 61.7% of submitted synth failures contain a
   *majority of the gold values* -- near-misses on one derived column, not
   wrong answers. Spot-checking narrow questions found one gold of a single
   all-blank row (`local_syn0139`) and two order-of-magnitude discrepancies
   with the signature of a join fan-out in the gold query.

### Why that does not invalidate the loop

**For a paired base-vs-arm comparison, wrong gold is noise, not bias.** The arm
runs the same questions against the same gold as the baseline, so a gold error
penalises both sides equally. It widens the band; it does not tilt the verdict.
What synth cannot do is produce a headline accuracy number -- which the loop
never needed.

The real cost is (1): less of the phenomenon worth fixing. Only ~5-6% of synth
episodes hit the cap, against 14% on the locals, so fallback-reduction arms have
roughly 13 episodes of headroom per 250-question split. **Prefer proposals whose
effect is not concentrated in fallback.**

### Two defects found and fixed

- `prep_synth_root.py` gated the *recorded preview*, which cannot see what the
  query really returns. `local_syn0139` passed and produced an all-blank gold
  that scored every correct answer wrong. The gate now also checks the
  **executed** gold for blankness (1.5% of 673 were affected).
- `rsi_eval.py` would compare two *different* question sets and print a
  confident verdict, with "paired on 0 shared questions" the only hint. It now
  **refuses** at zero overlap and warns below 90%. Both behaviours are tested.

## Overnight jobs

| job | outcome |
|---|---|
| 11206638 `synprof` | done -- synth vs locals profile, above |
| 11206641 `prepfull` | done -- 673 of 676 gold (3 timeouts) |
| 11206649 `synbase` | done -- split + both baselines (preempted twice; `--resume` absorbed it) |
| 11209486 `synnull` | done -- null replicate; the band is in the Fitness section |

## Not done

- `diff_cmp` and Deepika's judge prompt are not in any branch reachable from here.
  Production is **85.6/135**, not the 80 used in earlier analysis; the selection gap
  is **8.4**, not 14. Fold this in before trusting any selection-side number.
- The synth band rests on **one** null pair. A second replicate would firm it up,
  but it agrees with the locals' band, so this is not blocking.
- No semantic audit of synthetic gold against independent models. The paired-
  comparison argument above means the loop does not need one; a headline synth
  accuracy number would.
- The ~1.5% blank-gold instances are still present in `synthroot_full`. The gate
  is fixed but the root was built before the fix. Either rebuild, or exclude the
  10 ids -- they cost ~0.4% of accuracy on both sides equally, so this is not
  urgent.
