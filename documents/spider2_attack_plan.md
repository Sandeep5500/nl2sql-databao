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
