# Spider2 Plan

**4 people · Sept–Dec 2026 · target: Spider 2.0-Lite leaderboard**

---

## Phase 0 — Harness, baseline, and bottleneck analysis (first)

Before any training: find out whether the bottleneck is **retrieval** (getting the right schema context to the model) or **SQL generation** (writing correct SQL once context is known).

**Model for all Phase 0 work: Qwen3.5-9B** (fits L40S/A6000 in BF16, agentic-focused, matches the shakeout role below).

### Harness rewrite (decided)

Replace the databao-agent execution path with a lean, purpose-built tool-call loop (plain Python + OpenAI SDK against vLLM). The current path fights the library: monkey-patched `chat` for think-stripping, private-field overrides, symlinked temp DCE projects, prompt-only `min_retrievals`. We keep **databao-context-engine as a library** (search_context backend), the eval code, the trace format, and the prompt content. A lean harness is also the episode runner P2 needs for agentic RL. Not OpenHands — it's a sandboxed dev-agent runtime, wrong shape for a programmatic RL loop.

### Tool set v2 (ranked, from DivSkill/Spider-Agent/CHESS/SOMA survey)

1. `describe_table(table)` + `list_tables()` — deterministic schema browsing (PRAGMA + sample values). Decided: in.
2. `find_value(term, table?, column?)` — fuzzy cell-value search (CHESS/Tool-SQL pattern, +3–5% measured); fixes filter-literal mismatches ('CA' vs 'California').
3. `get_column_values(table, column)` — distinct values + counts for filter/ambiguity probing (SOMA-style, +9 over majority vote).
4. `read_documentation()` — the question's external_knowledge doc as a tool instead of 20K-char prompt-stuffing (13/135 locals need it).
5. `run_sql_query(sql, limit=N)` — keep, but make the preview row count an agent-settable parameter (capped) instead of fixed 12.
6. Later / after ablation: `run_python` (biggest single-tool ablation in FlexSQL, −11.85% when removed, but needs sandboxing), `validate_sql` dry-run, LLM critic, query-expansion search (deferred — deterministic tools should reduce reliance on vector search).

### Bottleneck ablation (after baseline run)

| Arm | Context given | Questions | Isolates |
|---|---|---|---|
| A — baseline | tools as-is, retrieval via search_context | all 135 | end-to-end |
| B — full schema | complete DDL + column samples in prompt, retrieval disabled | all 135 | is *finding* context the problem? |
| C — oracle linking | gold tables+columns (parsed from gold SQL via sqlglot) injected up front | 24 locals with gold SQL (compare against same-24 baseline slice) | can the model write correct SQL given perfect context? |

Read: C ≫ B ≈ A → generation is fine, retrieval/linking is the bottleneck. C ≈ B ≈ A (all low) → generation is the bottleneck. Gold SQL exists for only 24/135 locals; gold result CSVs exist for all (scoring unaffected). Alongside: categorize every failure in the baseline traces (wrong table / wrong column / wrong filter literal / wrong aggregation / doc-dependent / doom-loop).

### Results (Sept 13, 2026 — Qwen3.5-9B, v2 harness)

| Run | Score | Note |
|---|---|---|
| v1 harness (GLM-4.7-Flash), reference | 20.2% | 17% of questions had silently dead retrieval |
| A+ baseline (retrieval + schema overview + tools) | **43/135 (31.9%)** | zero infra failures; all misses are real SQL errors |
| A+ restricted to the 24 gold-SQL questions | 9/24 | |
| C oracle (gold tables+columns injected, no search) | **8/24** | |

**Verdict: SQL generation is the bottleneck, not retrieval.** Handing the model the exact
tables and columns of the correct answer changed nothing (9/24 → 8/24; overlap analysis:
5 solved in both arms, 3 only-with-oracle vs 4 only-baseline — symmetric noise). 12/24
questions fail in BOTH arms with perfect context — pure generation failures (window
functions, aggregation grain, identifier semantics like customer_id vs customer_unique_id,
doc-defined metrics). This validates the plan's core bet: the Arctic SFT+RL recipe on SQL
generation (P1) is the right lever; further retrieval investment is not.

Supporting evidence — enriching the never-enriched oracle_sql DB and enabling search moved
its 8 questions only 2/8 → 3/8.

**Failure taxonomy** (92 A+ misses, automated by re-executing predicted SQL vs gold):

| Category | Count | Reading |
|---|---|---|
| Wrong values (scorer tolerates extra columns) | 79 | wrong numbers/rows — aggregation grain, filters, window logic, wrong metric |
| True output-contract error (fewer cols than gold) | 10 | question intent misread |
| SQL no longer executes | 3 | nondeterministic edge (env) |

(Earlier draft split by raw column count; corrected after noting the scorer matches gold
columns anywhere in the prediction, so "extra columns" misses are value errors.)

Arm C step-budget check: with gold columns provided the agent's behavior barely changed —
14.9 vs 15.7 avg steps, 266 vs 265 SQL executions on the same 24. It already spends
~75-80% of tool calls iterating SQL in both arms (~11 executions/question) and still
converges on wrong logic: **iteration without a correctness signal**. Execution feedback
alone can't distinguish plausible from correct — the motivation for critic/selection
(P4) and execution-match RL (P1).

Cross-cuts: 22/92 hit the 30-step cap (fallback); 10/92 are doc-dependent questions.
On the gold-SQL subset: 8/15 misses used exactly the right tables and still wrote wrong
SQL; 7/15 missed a gold table (incomplete joins — e.g. local019 missed 4 of its tables).
Every category points at generation quality; none at retrieval.

**Caveat on arm C:** the hint listed all columns the gold SQL *touches* (join keys,
filters), not the output columns — and shape mismatches went UP under C (7→12).
The biggest failure bucket is the **output contract** (which columns the final answer
should return), a question-comprehension failure orthogonal to retrieval.

### Phase 0 follow-up experiments (queued)

1. Gold-SQL-through-DuckDB sanity check (24) — calibrates dialect-artifact ceiling.
2. Retrieval recall@8 measured directly (gold tables in top-8 chunks?) — exonerates
   retrieval without episode confounds.
3. C+ — inject exact output columns (gold CSV headers, available for ALL 135) — does
   the 43-question shape-mismatch bucket collapse?
4. Single-shot mode (schema + question, one call, no tools): Qwen3.5-9B vs
   **Arctic-Text2SQL-R1-7B/14B** (open weights, BIRD SOTA lineage, single-shot
   specialist — do NOT run it as the agent; it has no tool training). Arctic's
   number is the bar P1's fine-tuned model must beat; also Option-2 `draft_sql` backend.
5. Pass@K (K=4, temp 0.7, stratified subset) — if pass@K ≫ pass@1, selection is the gap
   (favors ensemble/critic + guarantees GRPO positive rollouts); if ≈, capability ceiling
   (favors distillation).

### Results: single-shot lane + two-model design (Sept 14, 2026)

| Run | Score | |
|---|---|---|
| Qwen3.5-9B single-shot (schema+question, 1 call, SQLite exec) | 21/135 (15.6%) | |
| Arctic-Text2SQL-R1-7B single-shot (identical prompt) | 22/135 (16.3%) | 18 misses don't even execute |
| Qwen3.5-9B agentic (A+) | 43/135 (31.9%) | |
| Agentic + draft_sql(Arctic) | 46/135 (34.1%) | within noise of A+ |

Findings:
- **Specialist ≈ generalist single-shot** (22 vs 21, only 13 shared wins). The BIRD-SOTA
  fine-tune transfers nothing to Spider2-lite → P1 must train on Spider2-style
  multi-step analytics, not BIRD data.
- **The agentic loop DOUBLES the same model** (21 → 43). Biggest measured lever so far.
- **Two-model design with this specialist: no effect.** Where draft_sql was actually
  called (61/135 episodes) the draft run scored 15 vs A+'s 17; the +3 net is variance
  (17 flips each way). Revisit once P1 produces a specialist whose single-shot beats
  the actor's own SQL.
- **Arctic as the agent actor: non-functional.** Zero tool calls in a 2-question smoke
  (60 steps); it answers in its trained prose+SQL style regardless of protocol.
  Full run skipped. Implication for P1: if we fine-tune hard on single-shot SQL, we
  should expect tool-calling degradation — check for it, or train with agentic traces
  mixed in. (A `--text-sql-fallback` shim exists in the harness if we ever want to
  iterate with a non-tool model.)
- **Selection headroom: union of the 4 runs = 67/135 (50%).** Perfect cross-run
  selection would gain +18 points over the best single run — strong motivation for
  pass@K + critic/selection (P4) and confirmation GRPO will have positive rollouts.
- 68/135 solved by no run yet — the hard core for training to attack.

### Results: pass@4 (Sept 15, 2026 — 4× full-135 agentic runs, temp 0.7)

| K | pass@K |
|---|---|
| 1 (avg) | 29.3% |
| 2 | 39.9% |
| 3 | 46.1% |
| 4 | **51.1% (69/135)** |

Greedy A+ on same set: 31.9%. Pass@4 + greedy union: 73/135 (54.1%). Curve still rising
+5 pts at K=3→4 (K=8 likely >55-60%). **Verdict: selection is the gap** — one extra
sample is worth +10 pts; the model generates correct SQL for half the benchmark within
4 tries. GRPO rollouts will be positive-rich; best-of-K + selector (exec-consistency
vote / critic / DivSkill) is the cheapest accuracy win before any training.
Never-solved core across all 5 runs: 62 questions, concentrated in bank_sales_trading (8),
f1 (8), IPL (5), oracle_sql (4), complex_oracle (4) — mine these for training targets.
Ops note: two runaway-query hangs cost wall-clock this phase; both DuckDB (agentic) and
SQLite (single-shot) executors now have interrupt guards.

**Correction (Sept 17): 100-row result cap invalidated 8 questions.** The harness stored
at most 100 rows of the submitted result while 8/135 gold answers have 236-2000 rows —
those questions were unwinnable in every run (v1 included). Cap raised to 5000; stored
final SQL re-executed uncapped and re-scored:
- **A+ corrected: 46/135 (34.1%)** (local074, local194, local354 had correct SQL, truncated)
- pass@4 corrected: 71/135 (52.6%); pass@4 + greedy union: 76/135 (56.3%)
- 5 of the 8 remain genuinely unsolved (now winnable going forward).

**Correction 2 (Sept 17): CSV round-trip type coercion** (credit: teammate's review).
The official Spider2 scorer writes the *prediction* to CSV and reads it back with
pandas, so both sides get identical type coercion; our scorer compared the in-memory
DuckDB frame directly — string '2018' vs number 2018, timestamps vs date strings,
'' vs NaN all scored as false negatives. Fixed: `eval.py` now round-trips the
prediction through CSV before comparison. Re-scored from stored SQL (flips only —
regressions in re-execution were artifacts of comment-swallowing newline flattening
in the CSVs, itself now fixed by escaping newlines):

| Run | before | corrected |
|---|---|---|
| A+ greedy | 43 | **46/135 (34.1%)** |
| pass@4 lanes | 39/37/38/44 | 40/38/40/46 (avg pass@1 30.4%) |
| pass@4 union | 69 | **72/135 (53.3%)** |
| pass@4 + greedy union | 73 | **77/135 (57.0%)** |
| draft (Arctic) | 46 | 47 (34.8%) |
| single-shot Arctic | 22 | 23 (17.0%) |

Cross-checked cases from both corrections: local156 (SUBSTR year as text),
local074/194/354 (row cap), local017 (type coercion).

**Correction 3 (Sept 17): byte decoding for typeless SQLite columns** (teammate review
again). SQLite columns with no declared type (e.g. WWE Wrestlers.name) come back from
DuckDB's scanner as bytearray objects; str() of those never matches gold text, and the
MODEL saw `bytearray(b'...')` in every preview on affected DBs. Fixed at the Database
layer (previews, stored results, get_column_values, find_value) and in the scorer
round-trip. Recovers local019 (WWE) in A+, k3 and arm C — correct SQL all along.

**Final corrected ledger:** A+ **47/135 (34.8%)** · pass@4 lanes 40/38/41/46
(avg pass@1 30.6%) · pass@4 union **73/135 (54.1%)** · with greedy **78/135 (57.8%)** ·
arm C 9/24 vs A+ 10/24 on the same slice (bottleneck verdict unchanged) · draft 47 ·
single-shot Qwen 21 / Arctic 23.

---

## Plan

The [Arctic-Text2SQL-R1](https://arxiv.org/abs/2505.20315) paper shows that SFT + RL can improve a single model's SQL generation by ~18 points on BIRD (most of it from SFT, the rest from GRPO with a simple execution reward). We try the same on a newer open model — **Qwen3.6-27B is the pick** — to see how far a current-generation model gets with the same training data and recipe.

Once we have that checkpoint, two options:

**Option 1 — single model, continued training.** Further SFT + RL on the same model using training traces from our harness — context engine, SQL documentation, and the other tools in the loop. Work on RL for SQL generation shows specialized rewards tend to work *worse* than a simple tiered one, so we go with `1 / 0.1 / 0` (exec-match / valid SQL / invalid).

**Option 2 — two models.** A separate model runs the agentic harness and calls the SQL model from step 1 through a `draft_sql` tool. This is the fallback in case agentic training degrades the model's SQL capability.

---

## Training data generation

**For SQL training** — straightforward reuse from the Arctic paper: their data sources are public, no new data needed.

**For agentic training** — several methods, used together:

- **Rejection sampling**: run our harness K times per question with varied skill prompts, keep the traces that scored correct.
- **Challenger / SQL-first generation**: generate SQL over messy enterprise schemas, execute it, then back-translate to a natural-language question — execution-verified data with no annotation.
- **Hindsight relabeling**: a failed trace that still executed some SQL is a correct trace for the question that SQL actually answers.
- **Frontier teacher**: distill traces from a frontier model, only for the hard tail our own sampling can't crack.

---

## Role split

| Who | Owns |
|---|---|
| **P1 — SQL training** | Train the SQL model using the Arctic recipe on Qwen3.6-27B. Also owns the baseline eval table. |
| **P2 — Agentic training** | Build the harness + RL infrastructure (episode runner, reward wiring, resume) and run the agentic training on P1's checkpoint. |
| **P3 — Training data for agent training** | Challenger / SQL-first pipeline + hindsight relabeling; multi-dialect. |
| **P4 — DivSkill + Databao** | Set up the skill-diverse ensemble on databao, get a baseline (pass@1 / pass@K / selected accuracy) — and generate the winning traces for agent SFT. |

---

## GPUs

| Job | Allocation |
|---|---|
| Serving / eval / ensemble | 1× A100, L40S for small aux models |
| SFT (LoRA) | 2× A100, ~a day |
| Single-shot RL (P1) | 4× A100, ~a week |
| Agentic RL (later) | 8× A100 for 1–2 weeks (or 4× at double wall-clock) — the one job needing a reservation |

Everything LoRA; shakeout runs happen on Qwen3.5-9B first.

---

## References

- [Arctic-Text2SQL-R1](https://arxiv.org/abs/2505.20315) — recipe & reward design
- [DivSkill-SQL](https://arxiv.org/html/2605.21792v1) — skills, ensemble, selection
- [ktx](https://github.com/Kaelio/ktx) — context-layer design
- [SQL-Zero](https://arxiv.org/html/2609.04697) — challenger/solver self-play


---

## Phase 1 — Training plan (Sept 25, 2026; lit survey + local assets)

**Assets:** 258 exec-verified winning traces / 79 unique questions (57 with multiple wins
→ DPO pairs); median 13 steps; 0/201 winners hit memory compaction (each trace = one
clean conversation).

**Collection:** (1) pass@K harvest at K=8-16 temp 0.7-1.0 over all 135; (2) frontier-teacher
traces through OUR harness on the ~57 never-solved questions (highest-leverage add —
cf. SWE-agent-LM: ~5K teacher traces + SFT only); (3) synthetic SQL-first questions for
volume; (4) hindsight relabeling only if thin. Dedupe near-identical solutions per question.

**Method (evidence-ranked):** rejection-sampled LoRA SFT first (arXiv:2609.17848: SFT beats
GRPO in 15/18 in-distribution settings) → divergence-point DPO from same-question
success/failure pass@4 pairs → multi-turn GRPO only as week-7 go/no-go (~2-5 pts for
~3-4 person-weeks; FIRST verify verl/SkyRL/ms-swift can train Qwen3.5's GDN-hybrid layers).

**Mixture:** ~40% agentic traces / ~30% single-shot NL2SQL (our lane + BIRD-style) /
~30% general tool-use + reasoning — the last slice prevents the Arctic-style tool-calling
regression we measured. Keep error-recovery segments; mask malformed-call turns.
Hold out a question split; gate checkpoints on greedy AND pass@4 (watch diversity collapse).

**Format:** one sample per trajectory (per compaction segment in general), native chat
template, loss on assistant tokens only (reasoning + tool calls), system/user/tool-results
masked. PIN a community-fixed Qwen3.5 chat template (shipped one has tool-call bugs) and
use the identical template for collection, training, serving.

**Stack:** ms-swift (official Qwen3.5 recipe, GRPO support) or Unsloth (9B LoRA ~22GB,
fits one A6000); LoRA all-linear r=8-16 bf16; no QLoRA on the hybrid arch; training venv
separate from serving venv. Timeline: wk1-3 data pipeline + SFT; wk3-5 teacher traces +
mixture ablations; wk5-7 DPO; wk7-8 RL go/no-go.


### Results: Qwen3.6-35B-A3B pass@4 + DivSkill judge selection (Sept 27, 2026)

35B-A3B (AWQ, same harness/config as 9B): pass@1 45.9% / @2 55.9% / @3 60.4% /
**@4 63.0% (85/135)**. Lanes 61-63 correct each. Never-solved core (vs ALL runs, both models): **39/135**; 96 unique questions solved
by at least one run (506 winning traces). 35B solved 17 questions no 9B run ever did;
the 9B family solved 11 the 35B missed — capabilities don't nest (ensemble/teacher
diversity argument).

Selection over the 4 lanes (dedup by exec-result equality, DivSkill pairwise
round-robin judge = same 35B, temp 0.2, both presentation orders):
avg single lane 45.9% -> majority vote 49.6% -> **judge 70/135 (51.9%)** -> oracle 63.0%.
Judge beats majority (+2.3) but harvests only ~35% of the selection gap — self-judging
shares the generator's blind spots. Next levers: cross-family judge, judge-time probes,
trained judge. Best project number to date: **51.9%**.

Teacher takeaway: ~46% pass@1 makes the 35B a productive trace generator — this run
added 248 winning traces; corpus now 506 traces / 96 unique questions.


### Results: search-fixed 35B lanes + selection (Sept 28, 2026)

Bug (caught by teammate review): the raw q36 lanes ran with ollama dead — all 457
search_context calls errored. Fixed (orchestrator gres inheritance) and reran 4 lanes:

| | raw (search dead) | search-fixed |
|---|---|---|
| lanes | 62/62/61/63 | 64/71/55/66 |
| pass@1 avg | 45.9% | 47.4% |
| pass@4 | 63.0% | **69.6% (94/135)** |

Findings: pass@1 +1.5 (noise-level); pass@4 +9 but confounded with extra sampling;
lane variance tripled. Search usage is a checkbox: ~1 call/question, 98% in the opening
steps, never revisited when stuck; 63% full gold-table recall when used. Win rate is
identical with/without search per-episode. **Retrieval is vestigial on the local split**
(overview + describe_table carry grounding); its real test is enterprise-scale schemas.

Tool-usage profile (k1): run_sql_query 67% of calls (7.9/win-ep vs 13.6/loss-ep — losers
grind), describe_table 17% (disciplined, early, the real orientation tool),
read_documentation 13/13 compliance, find_value near-abandoned (10 calls), 43% of
SQL-error episodes still win, zero submit protocol errors.

Selection on search-fixed lanes: majority 52.6% vs judge 51.1% (raw set: 49.6% vs 51.9%).
**Pooled: majority ≈ self-judge ≈ 52%; oracle gap widened to ~17 pts.** Self-judging is
the bottleneck → cross-family judge / probe-augmented judge / trained verifier.

Cumulative: all-8-lane 35B union 102/135 (75.6%); global solved-ever 105/135;
762 winning traces; never-solved core 30.


### Results: presentation-loss arm q36f (Nov 24-25, 2026)

Hypothesis: a measurable slice of our failures are answers the agent computes
correctly and then submits in a shape the scorer rejects. Four changes, all aimed
at that slice, nothing aimed at capability:

1. **Output-format rules** in the system prompt — ISO dates (`YYYY-MM-DD`), no
   rounding unless asked, and include BOTH identifiers when the schema has two for
   one entity (`customer_id` + `customer_unique_id`).
2. **Rubric commitment** — two *required* booleans added to the submit rubric,
   `answer_is_single_row` and `include_zero_count_entities`. The planner reliably
   recognised a single-winner question and then left `exact_rows` null; the boolean
   forces the call. `effective_exact_rows()` honours it.
3. **Step rescue** — `--step-extension 15`: an episode that hits the step cap with
   no SQL submitted gets one budget extension instead of a forced fallback.
4. Join/type hygiene in `describe_table` (committed, **not** in this run's tree).

Setup: Qwen3.6-35B-A3B-AWQ, temp 0.7, 4 lanes, 7 shards, `--context-mode search
--schema-overview --rubric-dir r3 --rubric-confident-only --rubric-enforce`.
Baseline is **q36e** (explored enrichment, old vector index), the best prior config.

| | q36e | q36f |
|---|---|---|
| lanes | 75 / 69 / 74 / 72 | 83 / 74 / 83 / 79 |
| pass@1 | 53.7% (72.5/135) | **59.1% (79.75/135)** |
| pass@4 | 92 (68.7%) | **100 (74.6%)** |
| pass^4 | 45 (33.6%) | **53 (39.6%)** |
| fallback rate | 13.9% | **2.6%** |
| lane sd | 2.65 | 4.27 |

**+7.25 questions (+5.4 pp), SE 2.51, Welch t=2.89 (df 5, p~0.03)** — the first
change in this project to clear the noise band. Caveats that belong with the number:
the effect is 5 points, not 10, and lane sd rose to 4.27, so a *single* lane of this
config reads anywhere from 55% to 62%. Judge it on the 4-lane mean only.

Solve-count distribution hardened at both poles: never-solved 42 -> **34**,
always-solved 45 -> **53**. That pass^4 move is the more useful result than pass@1 —
8 more questions now survive every attempt, which is what a single-lane system needs.

**Reproducible core** (same verdict in all 4 lanes), which is the part not to
attribute to variance:

- gained, 0/4 baseline -> 4/4 now: `local004` `local030` `local067` `local157`
  `local264` `local299`
- lost, 4/4 baseline -> 0/4 now: `local163`
- net **+5** reproducible; the remaining ~+2 is movement in the coin-flip middle.

Every gain is a question one of the above changes was built for: local004 the dual
identifier, local157 ISO dates + rounding, local264 the single-row boolean (now
solves in 3-6 steps vs abstaining before), local030 shape commitment.

Step rescue, pooled over 536 episodes: fired **91** times, 77 went on to submit,
**31 correct**. It all but eliminated forced fallbacks (13.9% -> 2.6%) and is the
mechanism behind the f1 gains (`local355`, `local309`).

**One systematic defect, diagnosed — fix before reusing this config.** `local163`
fails identically in all 4 lanes: the gate enforces `exact_rows: 3` at high
confidence, but the planner *inferred* 3 from its own grain reasoning ("one row per
faculty rank") rather than reading a number off the question, and gold has 4 rows
because rank ASSC has a tie. Enforcement should be restricted to counts the question
itself states; that keeps the local264 win and drops this casualty. `local023`
(enforced 5) lost in 3 of 4 lanes for the same family of reason.

Also fixed mid-run (`f5e308e`, not applied to the running tree so lanes stayed
identical): the gate did `int(exact_rows)` and one rubric of 135 (`local356`) carried
`exact_rows: ""` next to `rows_confidence: high`, which killed that shard at its last
question. Every lane therefore reports **134/135**; local356 is counted wrong in all
figures above. It is 0/12 historically, so the cost is ~0.

Artifacts, now **in the repo** so a combined/pass@8 run can consume them directly:

- `results/q36f_pass4_k{1..4}.csv` — 134 episodes per lane, the 7 shards merged and
  sorted by instance_id; carries `step_extensions` (new column) and the final SQL.
- `logs/rubrics/r3/` — the **exact** 135 rubrics the run read. The planner runs at
  temp 0.7, so regenerating gives different rubrics and breaks comparability; pass
  `--rubric-dir logs/rubrics/r3`. See its README for the two reuse traps
  (`local356`'s empty `exact_rows`, and `local163`'s wrong enforced count).
- `logs/traces/q36f_pass4_k{1..4}/` — 134 episode traces per lane for `inspect view`.

Also mirrored on Babel at `~/q36f_out/` (login-node readable; `/data/user_data` is
not). The run's worktree `/data/user_data/juliep2/q36f_tree` is disposable.

Checked and ruled out: the last-quintile accuracy dip (41%/30% vs 59-60% earlier) is
*difficulty*, not server decay — those questions' q36e-expected rate is 31-33% and
70% of them are the same questions in both lanes (slow episodes finish last).

### Fix: the local163 tie defect (Nov 25, 2026)

q36f's one reproducible regression, diagnosed and fixed. **No new run** — every number
below comes from q36f's own CSVs, traces and rubrics plus local re-execution.

**What actually happened.** The r3 rubric for local163 says `exact_rows: 3`,
`rows_confidence: high`, grain "one row per faculty rank", and in the same breath raises
the open point *"if two faculty members in the same rank are equally close to the
average, should both be included or only one?"*. All four lanes wrote
`ROW_NUMBER() OVER (PARTITION BY FacRank ORDER BY ABS(...)) ... WHERE rn = 1` — three
rows, one per rank. Gold has 4: rank ASSC ties (LEONARD FIBON 70000 and JULIA MILLS
75000 are both 2500 from the 72500 average). Re-executed locally and scored with
`nl2sql/eval.py`: `ROW_NUMBER()` → 0, `RANK()` → 1, `DENSE_RANK()` → 1.

**The enforcement gate was not the cause.** No `shape_refusal` fired on local163 in any
lane — the agent produced the rubric's 3 rows unprompted, so the gate had nothing to
object to. The harm came from the rendered rubric text, not from `--rubric-enforce`.

**Measured on q36f before changing anything:**

| | |
|---|---|
| enforced counts (86 rubrics) | 37 of 40 with count > 1 match a gold row count |
| wrong enforced counts | 4: local163 (3 vs 4), local220 (1 vs 2), local279 (10 vs 2), local302 (5 vs 1) |
| refusal events | 32, across 31 episodes / 18 questions |
| gate refused a gold-shaped result | 0 times |
| refused vs unrefused episodes, same questions | 19/31 (61.3%) vs 24/41 (58.5%) |

So the gate is neutral at this n, and the count is a good signal. Two fixes that looked
obvious were rejected on this evidence: suppressing counts the question does not state
(all 40 counts > 1 sit on per-entity grains, so the rule has no discrimination), and
turning the equality check into a lower bound (it would cancel 11 refusals, and in all
11 the gold count equalled the enforced count — the gate was correctly pushing the agent
*down*).

**What changed instead** — the count stays the target; the way it may be reached does not:
1. `row_count_in_doubt()` flags a rubric whose own open points unsettle the row count
   (ties, "how many rows", "only one"). It catches 3 of the 4 wrong counts and fires on
   22 of the 86 enforcing r3 rubrics.
2. `render_rubric()` then adds: N assumes no ties, keep every tied member
   (RANK/DENSE_RANK, never ROW_NUMBER), invent no tie-breaker, and if the tie is real
   submit the longer result with `confirm_shape=true`.
3. The refusal message gains the same escape clause when the submitted result has *more*
   rows than N — the equality check itself is untouched.
4. `RUBRIC_SYSTEM` now says an unresolved tie means the count is not fixed by the
   question, so `rows_confidence` is at most medium. This affects r4+ only; r3 is frozen.

**Risk check.** 10 of the 22 affected questions have correct q36f episodes whose SQL uses
`ROW_NUMBER()`. Swapping it for `RANK()` in each and re-scoring: 13 of 13 executable
cases still score 1, 0 break (the rest hold comments or multiple statements that would
not re-execute standalone). No currently-correct answer in that set depends on arbitrary
tie-breaking.

**Not verified:** that the agent obeys the new text. The mechanism is proven (RANK scores
1) and the instruction is proven harmless, but whether local163 flips needs a lane.
