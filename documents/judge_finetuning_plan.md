# Fine-tuning the judge agent — plan

Status: proposed, Oct 28 2026. Owner: juliep2.

The judge picks one of K frozen pass@K candidates. Today it is a prompted
Qwen3.6-35B-A3B scoring **76/135**. This plan trains it instead.

Everything in §1 is measured on our own runs, not taken from papers. Sources for
the external anchors are at the end.

---

## 1. Why the judge is stuck (measured)

On the `q36rg` pool (4 lanes, 135 questions):

| selector | of 135 |
|---|---|
| pick a lane at random | 69.2 |
| **majority vote on identical execution result** | **75** |
| judge, best prompt (`shape`) | **76** |
| judge, pairwise Copeland | 74 |
| pass@4 ceiling | 94 |

The judge beats dumb majority voting by **one question**. Three measurements
explain why, and each one maps to a fix in this plan.

**(a) Pairwise binary accuracy is 65.6%.** Replaying the 326 decisive pair
judgements from `validator_pwrg` (pairs where exactly one candidate is correct):

| | |
|---|---|
| decisive single judgements | 326 |
| correct | **65.64%** |
| unordered decisive pairs | 163 |
| judge agrees with itself in both orders | 91 (56%) |
| …of those, correct | 71 (**78%**) |
| order flips — pure noise | **72 (44%)** |

So the judge is *competent when it commits* and a coin-flip otherwise. 44% of
its decisions carry no signal at all.

**(b) Position bias is severe.** "Always pick A" alone scores 69/135, against
the judge's 76. The judge picks A 44–53% of the time depending on prompt.

**(c) Shape cannot discriminate, which is what the current prompt relies on.**
Of the 90 questions in the 16-lane pool with both a right and a wrong result
group, **67% have a wrong group sharing a correct group's exact (rows, cols)**.
The best prompt variant (`shape`, 76) leads with EXPECT_ROWS/EXPECT_COLUMNS —
it is working the one axis that provably collides two-thirds of the time.

**(d) Showing the judge the candidates' reasoning makes it worse.** Five
reasoning modes on the same pool (ceiling 67): none 51, submit summary 51,
summary+thinking 49, last-two-thinking 49, full thinking **48**. The narration
is confidently-wrong prose. Train on evidence, not on self-reports.

**(e) Candidate count is the bigger lever than judge quality.** Pooling all 16
available 35B lanes:

| N | pass@N | majority@N | all-distinct results |
|---|---|---|---|
| 1 | 67.1 | 67.1 | 100% |
| 4 | 94.5 | 69.5 | 66% |
| 8 | 103.9 | 73.2 | 39% |
| 16 | **111.0** | **79.0** | 18% |

Majority voting at N=16 (79) already beats our prompted judge at N=4 (76).
Caveat: those 16 lanes are 4 configs × 4 samples, so some diversity is
config-driven; a single-config 16-sample pool is probably 103–106, not 111.

After collapsing identical execution results the N=16 pool still has a **median
of 12 distinct groups** per question (mean 11.5), i.e. 136 ordered pairs — so
collapsing saves only ~43% of comparisons, and §5.1 shows that breadth is an
asset rather than a cost.

---

## 2. Task definition

Output is **one token**. Input is a question and two candidate **answers**.

```
INPUT
  question                        (natural language)
  schema                          (compact column list -- see arms below)
  ANSWER A: executed result        (first 15 rows, CSV)
  ANSWER B: executed result
OUTPUT
  one token: "A" or "B"
```

The unit being judged is the **executed result, not the query**. That is what
the deployed judge is actually asked to do -- `validator_select.py` says "Pick
the ONE candidate whose RESULT correctly answers the question. Judge the
result, not the style" -- and three of our own measurements say the training
input should match that framing rather than hand the model the SQL and append
an instruction not to look at it:

1. **SQL invites a shortcut that an instruction does not close.** On our 1,313
   pairs, "pick the longer SQL" alone scores **61.3%**, against the judge's
   measured 65.64%. It is not diffuse: it is 99.7% within `missing_column` and
   49.1% on `wrong_values` (see 3.7).
2. **Our SQL is from the wrong distribution.** Training golds are written by
   `gpt-5.4-mini` from a template; real candidates come from Qwen3.6-35B inside
   a tool loop. Style learned on the former does not transfer. A result is a
   result.
3. **It agrees with 1(d).** Showing the judge more of *how* an answer was
   produced made it monotonically worse (51 -> 48 across five reasoning modes).

There is also a structural reason: we collapse identical execution results into
groups (median 12 per question at N=16), and a group holds many SQLs, so "which
SQL do you show" has no principled answer at serving time. Results are the
natural unit.

### 2.1 Two independent ablation axes

Dropping SQL and dropping schema are **separate decisions** and must not be
bundled. Measured on one representative item, the full-evidence prompt is 4,369
characters of content, and of what a results-only prompt removes, the schema
DDL is **56.6%** and the two SQLs are 44.4% together.

| arm | SQL | schema | what it tells us |
|---|---|---|---|
| **A** | out | compact column list | deployment-faithful; the one we expect to serve |
| **B** | in | compact column list | more evidence, but shortcut-exposed |
| **C** | in | out | **the control** |

**Arm C is the diagnostic.** If C lands near B, then B's advantage is SQL style
rather than judgement, and because our SQL distribution differs from real
candidates that advantage is fictional. C is cheap and is the only way to learn
whether B is honest.

Keep a schema in arms A and B: our scorer is asymmetric -- **a missing gold
column fails, extra predicted columns pass** -- so deciding whether an answer
omits a column requires knowing which columns existed to ask for. Stripping the
schema removes the evidence for `missing_column`, which is 312 of our pairs.
Use a compact column list, not full DDL with per-column comments.

### 2.2 Confidence and order symmetry

Confidence is **not** emitted by the model -- it is read off the logits:

```
P(A > B) = softmax([logprob("A"), logprob("B")])[0]
```

vLLM's OpenAI-compatible API already returns `top_logprobs`, so this needs no
serving change. Self-reported confidence is poorly calibrated and costs output
tokens; the logit is free and real.

**Order-symmetric scoring** -- the fix for 1(b):

```
s(A,B) = 1/2 * [ P(A>B | A first) + (1 - P(B>A | B first)) ]
```

Averaging two calibrated probabilities makes an order flip structurally
impossible, rather than hoping training washes it out. It also yields a margin
for breaking Copeland ties, replacing the current fallback to largest
result-group (= majority voting, measured at 75, *below* the judge).

Group sizes stay **out** of the model input -- that is majority voting smuggled
into the prompt, and it is near-worthless on this pool. Judge groups on their
merits and apply any group-size prior outside the model where it can be ablated.

### 2.3 The decidability risk, stated plainly

In arm A some pairs may be genuinely undecidable. A real example: two answers
both 5x3, both led by the same row, totals differing 6%, where the only thing
separating them is that the wrong query counted NULL energy as zero -- a fact
not present anywhere in a results-only prompt.

This cuts both ways and both readings matter:

- If an answer is not decidable from the output, **our judge is being asked to
  do something impossible**, and no amount of training fixes it.
- If we train on undecidable pairs, we fit **label noise** and teach the model
  to guess confidently.

The risk concentrates on the **31% of our questions whose gold is a single
row**, often a single scalar. So measure it before training: have a strong model
attempt arm A on ~100 held-out pairs and report accuracy split by gold row
count. Then either exclude the undecidable slice or keep it and accept a known
noise floor -- rather than meeting it later as a mysteriously capped accuracy.

---

## 3. Data

### 3.1 The leakage rule

Two separate inputs to a training pair, and only one of them may be ours:

| what the pair needs | source | Spider 2.0 involved |
|---|---|---|
| database schema | foreign public DBs (SynSQL donors) | **no** |
| gold SQL + question | **synthesized by us** (§3.2) | no — newly written |
| the K candidate SQLs | our harness running Qwen3.6-35B | no — a model, not data |
| the label | execute candidates against our own gold | no |

"Our own candidates" means our own **model and harness**, never our own
benchmark. What we are matching is the *error distribution* — the specific ways
our 35B goes wrong inside our tool loop — which no public dataset provides.

Off-limits:

1. The 135 local questions — the test set.
2. The 30 local databases, even with newly synthesized questions. Not answer
   leakage, but it trains schema familiarity on the exact test DBs.
3. Spider 2.0's other ~412 instances. Same benchmark, same annotators, same
   authoring style. Also a hard blocker: they are BigQuery/Snowflake, so we
   cannot execute *candidate* SQL to get labels (gold exec CSVs exist for all
   547, but predictions still need a live warehouse).
4. Few-shotting question synthesis from the 135 test questions. Describe the
   style in prose from our own error taxonomy instead.

### 3.2 Primary source: self-synthesis over foreign schemas

Do not reuse anyone's question→SQL pairs. **Write the gold SQL first, execute it
to define the gold result, then phrase a question for it.** This is the SQL→
question direction used by SynSQL's own pipeline and by Six-Gym's SQL-Rewind
(whose recipe produced Bird-Fixer, which beat o3-mini on BIRD-CRITIC).

Three properties follow, and together they answer the contamination question
outright:

- **Zero mapping contamination, by construction.** The (question, SQL) pair has
  never existed, so it cannot be memorized whatever is in Qwen's corpus. A
  public *schema* is harmless — schemas do not contain answers.
- **Gold correctness is free.** We execute the gold SQL, so what it returns *is*
  the gold. No trusting third-party annotations, no porting their scorer
  conventions.
- **We control question style.** This closes a real gap: SynSQL's own questions
  are LLM-generated and single-clause, BIRD's are human but simple, and
  **neither has Spider 2.0's multi-step compositional phrasing** — "first select
  the cities where sales rose 20%, then rank products within them, take the top
  20%, then compute share change" — which drives our largest never-solved
  failure mode. Write that style from a prose spec off our own error taxonomy,
  **never few-shot from the 135 test questions.**

#### What can actually be wrong

Not the gold result — that is defined by execution. The failure mode is the
**question↔SQL correspondence**: an ambiguous or mis-phrased question whose true
answer differs from what the gold SQL returns. That is where the strong model
and the validation gate go.

#### Model roles — do not conflate these

| role | model | why |
|---|---|---|
| write gold SQL (from schema + a failure-mode template) | **strong** (GPT-5.4) | quality and complexity of the query |
| phrase the question from the gold SQL | **strong** (GPT-5.4) | natural, unambiguous wording |
| independent validation | **a different model** (GPT-5.4-mini or another family), **blind to the gold SQL** | agreement must not be self-confirmation |
| generate the K candidates | **our Qwen3.6-35B in our harness** | the whole point is to match *our* error distribution — never use a strong model here |

Using one model to both phrase and validate produces correlated agreement: it
will agree with its own wording. The validator sees only question + schema.

#### Validation gate

The gate exists to reject **ambiguous** questions — ones with two readings, where
the gold result is not the only defensible answer. It is *not* meant to reject
hard ones.

**Do not implement it as "can the validator answer this?"** A weaker validator
(GPT-5.4-mini) against a stronger author (GPT-5.4) conflates "the question is
ambiguous" with "the validator is not good enough" — and since we deliberately
stratify toward difficulty (p ≈ 0.5 for our 35B), that bias rejects exactly the
hard-but-well-posed items we most want.

**Implement it as intent agreement instead.** Have the validator state the
expected output — row grain, exact row count, columns — **blind to the gold
SQL**, and keep the item only if that matches the gold result's actual shape.
Describing intent is far cheaper than solving, so the capability confound mostly
disappears and the gate tests ambiguity directly.

`src/nl2sql/rubric.py` already does exactly this, and its row accuracy measured
**99%** on Spider 2.0 — a trustworthy instrument, and free code reuse. Run it on
a different model from the one that phrased the question.

**Yield is unmeasured.** The plan assumes 60%; an intent-agreement gate should
do better, perhaps 80%. This is the softest number in the document — the §3.5
pilot measures it.

#### Stratify by our measured failure taxonomy

Random synthesis would concentrate pairs where the judge already succeeds.
Instead template the gold SQL into buckets matching where we actually fail
(counts are lane-failures from the 4-lane `q36re` analysis):

| bucket | our failures | what it teaches the judge |
|---|---|---|
| missing filter / wrong grouping | 26 | multi-clause composition |
| set-then-aggregate (gold = 1 row) | 18 | grain vs filter set |
| enumerated multi-column deliverables | 45 (21 questions) | column coverage |
| boundary: ties, NULL group, LIMIT | 13 | off-by-one row counts |
| join fan-out / missing DISTINCT | 10 | exact-multiple row counts |
| right shape, wrong values | 117 | the hard core — metric definition |

This also manufactures the pairs we most need: **67% of mixed questions have a
wrong result group sharing a correct group's exact (rows, cols)**, so wrong
variants that are shape-identical to gold are precisely the discrimination the
judge has to learn. Stratified synthesis produces them on purpose.

#### How many questions — and why not more candidates each

The unit that matters is **distinct questions, not pairs.** Pairs drawn from one
question share its schema, wording and overlapping candidates, so they are
heavily correlated; effective sample size tracks question count.

**Do not model this with a binomial.** A first pass assumed each of K candidates
is independently correct with p = 0.533, predicting 87% of questions mixed at
K=4. Measured on the real 4-lane pool it is **36%**. Lanes are strongly
correlated — question difficulty dominates, so a question tends to come out
all-right or all-wrong. The model overstated pair yield by ~2.5×.

Measured yield, sampling K lanes from the 16-lane pool and collapsing by result
signature:

| K | mixed Q | pairs/Q | **pairs/episode** | Q for 3,800 pairs | episodes |
|---|---|---|---|---|---|
| 2 | 23% | 0.23 | 0.115 | 16,535 | 33,070 |
| 4 | 42% | 1.18 | 0.296 | 3,208 | 12,833 |
| 6 | 51% | 2.70 | 0.450 | 1,407 | 8,443 |
| 8 | 56% | 4.63 | 0.579 | 820 | 6,560 |
| 12 | 63% | 9.63 | 0.802 | 395 | 4,737 |
| 16 | 67% | 15.85 | 0.991 | 240 | 3,836 |

Collapsing itself is cheap: 4 candidates give a mean of **3.47** distinct result
groups, so only 0.53 merge away. The correlation is what costs us.

**Pairs per episode rises monotonically with K**, so higher K is strictly more
*episode*-efficient — low K burns episodes on all-right/all-wrong questions. But
high K buys pairs that are correlated rather than fresh questions. That is the
real trade-off:

Targeting 6,000 raw pairs (≈3,600 after a 60% hard-pair filter):

| K | usable Q | synthesize | API $ | episodes | GPU h ×1 | GPU h ×4 | pairs/Q | vs CHASE-SQL |
|---|---|---|---|---|---|---|---|---|
| 4 | 5,085 | 8,475 | $134 | 20,339 | 56.5 | 14.1 | 1.18 | 2.9× |
| **6** | **2,222** | **3,704** | **$59** | **13,333** | **37.0** | **9.3** | **2.70** | **6.8×** |
| 8 | 1,296 | 2,160 | $34 | 10,367 | 28.8 | 7.2 | 4.63 | 11.6× |
| 12 | 623 | 1,038 | $16 | 7,477 | 20.8 | 5.2 | 9.63 | 24.1× |

**Adopted: ~3,700 synthesized items, K=6.** It halves K=4's GPU time and API
cost while keeping correlation at 6.8× the CHASE-SQL precedent (0.4
pairs/question) rather than K=8's 11.6× or the original plan's 35×.

#### One reason the real numbers should beat this table

The curve above is measured on *Spider 2.0* questions, where difficulty is
bimodal — 49 of 135 solved by all four lanes, 42 by none. That split is exactly
what suppresses the mixed rate. Stratified synthesis calibrated to p ≈ 0.5 with
*narrower* difficulty variance should push the mixed rate above these figures,
because we control difficulty and Spider 2.0 does not.

So treat the table as a **lower bound**, and let the pilot decide K: run 100
synthesized items at K=6, measure the actual mixed rate, and if it comes in
well above 51%, drop to K=4 and buy diversity with the saved episodes.

#### Calibrate difficulty to p ≈ 0.5

Mixed yield is maximised when our generator is at chance on the synthesized
questions:

| generator accuracy | K=4 mixed yield | K=6 |
|---|---|---|
| 0.40 | 0.845 | 0.949 |
| **0.50** | **0.875** | **0.969** |
| 0.60 | 0.845 | 0.949 |
| 0.75 | 0.680 | 0.822 |
| 0.85 | 0.477 | 0.623 |

So difficulty is a tunable knob, not a fixed property: questions too easy *or*
too hard both waste episodes. Run a 100-item pilot, measure our 35B's accuracy
on it, and adjust the stratification templates until it lands near 50% before
committing the full 3,700.

#### Cost and wall clock

~3,700 items × 3 calls ≈ 29M input / 3.0M output tokens. **≈ $59** with GPT-5.4
for gold SQL + question and GPT-5.4-mini for blind validation, with prefix
caching on the shared per-DB schema. Negligible against free Babel GPU.

The three calls are sequential per item (gold SQL → question → blind
validation), but items are independent, so each stage runs as one concurrent
batch:

| concurrency | per stage | all 3 stages |
|---|---|---|
| 10 | ~62 min | ~3.1 h |
| 30 | ~21 min | **~1 h** |

The binding constraint is the rate limit, not latency: 29M input tokens is a
~145 min floor at 200k TPM, ~36 min at 800k TPM. Budget **1.5–3 h**.

Do **not** use the Batch API here. It would halve the cost, but the three stages
are sequential, so it means up to 3 × 24 h to save ~$30.

### 3.3 Where the schemas come from

Use **SynSQL-2.5M's 16,583 databases as schema donors** and discard its
question/SQL pairs. Its schemas average 10.2 tables × 7.3 cols ≈ **74
columns/DB**, which sits on our test median of **13 tables / 77 columns** (min
35 cols, max 49 tables / 352 cols). Apache 2.0, SQLite, so it drops straight
into the harness.

Sample ~150 DBs and run **cheap enrichment only**: `compute_keys.py` and
`compute_profile.py` are data-only, no LLM, so `describe_table` still shows keys
and profile. Skip notes and the vector index (≈4 min LLM time per DB,
infeasible at this scale). This costs `search_context` in foreign episodes,
which is acceptable — retrieval is not what the judge decides.

### 3.4 Control and evaluation sources

**Used only to measure contamination, never as primary training data:**
BIRD train (9,411 questions, high redundancy in the corpus — papers,
leaderboards, derived datasets) and SynSQL's own question/SQL pairs (2.54M rows,
single-exposure, much weaker memorization risk). See §3.6.

**Held out for evaluation, never trained on:**

- **LiveSQLBench** — 270 tasks, 18 SQLite DBs, CC-BY-SA-4.0, contamination-free
  by design (each hidden test set becomes the next release's dev set; business
  rules change between releases). **Gold SQL is locked** (`sol_sql`), by email
  request to the BIRD team. *Start this request first — it is the long-lead item.*
- **BEAVER** — ~200 questions over real private enterprise warehouses (99–321
  tables, 1,544–2,708 columns). Ideal contamination profile; gated behind a
  contact-info agreement on HuggingFace.

Both are too small to train on. They are what makes the generalization claim
clean, with our 135 staying a pure test set.

### 3.5 Pipeline

**The funnel, end to end:**

| stage | count |
|---|---|
| 1. synthesized (gold SQL + question) | **3,700** |
| 2. pass the blind round-trip gate (60%) | 2,220 ← questions we run candidates on |
| 3. candidate episodes (K=6) | 13,320 |
| 4. questions yielding ≥1 pair (51% mixed, measured) | **1,130** |
| 5. raw pairs | 5,994 |
| 6. after the hard-pair filter (60%) | **~3,600** ← the training set |

Per failure bucket (6 buckets): ~190 questions, ~600 pairs.
For comparison, CHASE-SQL trained its selector on **3,800** pairs.

**Treat 1,130 as a midpoint, not a forecast.** It is the product of two
multipliers: 3,700 × 0.60 (the gate, *estimated*) × 0.51 (the mixed rate,
*measured but on Spider 2.0*). Varying both:

| gate ↓ / mixed → | 40% | 51% | 60% | 70% |
|---|---|---|---|---|
| 40% | 592 | 755 | 888 | 1,036 |
| **60%** | 888 | **1,132** | 1,332 | 1,554 |
| 85% | 1,258 | 1,604 | 1,887 | 2,202 |

That is **592 to 2,202 usable questions — a 3.7× spread**, or 3,100 to 11,700
raw pairs. The pilot's job is to collapse this range before we spend 9 GPU-hours
on candidate generation.

1. **Sample ~300 SynSQL databases**; run `compute_keys.py` + `compute_profile.py`.
2. **Pilot: synthesize 100 items**, run K=6 candidates, measure (a) the
   **gate pass rate** — the plan's softest assumption — (b) our 35B's
   accuracy and (c) the **mixed-question rate**. Tune the stratification
   templates until accuracy sits near **p ≈ 0.5**, and use the mixed rate to
   fix K (§3.2: ≫51% → drop to K=4 and buy diversity). Do this before step 3 —
   it is ~1 h and it sets the yield of everything after it.
3. **Synthesize ~3,700 (gold SQL, question) items**, stratified per §3.2, with
   the three-model split; keep the ~2,200 that pass the blind round-trip gate.
4. **Generate 6 candidates per question** with our harness + Qwen3.6-35B at the
   same temperature as the real pass@K lanes. **13,333 episodes** → ~1,130
   mixed questions (51% measured yield at K=6). Shard ×4 across GPUs: ~9 h.
5. **Label with *our* scorer semantics.** Ours tolerates extra predicted
   columns, fails on a missing gold column, and uses absolute 0.01 tolerance.
   **Prerequisite task:** port `eval.py`'s comparison to run against synthesized
   gold result sets. (Simpler than the earlier plan — we own the gold, so there
   are no foreign `condition_cols` / `ignore_order` annotations to reconcile.)
6. **Collapse by result signature**, then form pairs across groups where exactly
   one side is correct. Expect **~6,000 raw pairs**: 2,220 gated questions ×
   2.70 pairs/question measured, of which ~1,130 (51%) actually contribute,
   averaging 5.3 pairs each.
7. **Hard-pair filter.** Judge each pair with the untuned model a few times and
   keep the **middling band (≈0.2–0.6 accuracy)**. Pairs it gets right every
   time are uninformative; pairs it gets wrong *every* time are usually
   mislabeled rather than hard. Target **~3,600** (≈60% survival), spread over
   the ~1,130 contributing questions — roughly **190 questions and 600 pairs
   per failure bucket**.
8. **Shuffle order within every pair.** Non-negotiable given §1(b).

That is just under CHASE-SQL's 3.8K pairs. If the filter proves harsher than
60%, **raise the synthesis count, not K** — K buys pairs cheaply in episodes but
buys them correlated, and correlation is the thing that limits effective sample
size (§3.2).

### 3.6 Contamination, measured not assumed

Self-synthesis makes the training set contamination-free by construction, so
these probes are no longer load-bearing — but they are cheap and the result is
publishable in its own right. Nobody outside Qwen knows what is in Qwen3.6's
pretraining mix, so measure rather than assume.

1. **Memorization probe.** Question + schema, no candidates, ask for SQL, score
   against gold — per source. If BIRD scores high and LiveSQLBench low,
   **that gap is the memorization effect.**
2. **Judge accuracy by source.** Untuned pairwise binary accuracy on BIRD pairs
   vs SynSQL pairs vs our synthesized pairs. Our own pool sits at **65.6%**. A
   source scoring ~90% is useless for training (no gradient); one near 65% is
   informative.

Worth keeping in view: for a *judge*, memorization makes data **uninformative,
not poisonous** — a recalled answer means near-zero loss on that example, so it
wastes compute rather than corrupting the model. The genuine risk is only if
memorized items *dominate*, in which case the model learns "recall gold, then
compare," which transfers to nothing. The §3.5 step-6 filter removes such items
automatically, since a pair solved by recall is a pair the untuned judge already
gets right.

---

### 3.7 What was actually built (2026-11-01)

Generated on Babel (job `11001600`, 1 h 13 m) by `synth_questions.py` piped into
`synth_negatives.py` in `--watch` mode. Committed as `data/synth/main1k.jsonl`
and `data/synth/main1k_negatives.jsonl`.

| | |
|---|---|
| questions generated | 1,000 (300 hard tier, buckets even) |
| passed the ambiguity gate | 861 (86%) |
| questions with >=1 verified wrong answer | **771 (90%)** |
| **preference pairs** | **1,313** (542 questions x2, 229 x1) |
| rejected as not-actually-wrong | 1,823 (58% of attempts) |
| cost | $13.89 questions + $3.69 negatives |

**Negatives are constructed, not sampled.** A pair needs a wrong answer and the
gold already supplies the right one, so there is no need to run episodes hoping
for a mix -- one episode re-processes ~200k tokens of prefill, a constructed
negative is one API call. Each is templated on the measured failure taxonomy,
then executed and graded with the benchmark's own scorer. That 1,823 of 3,136
attempts still graded *correct* is the load-bearing number: without execution
checking, more than half this dataset would be mislabelled.

**Where the 229 unusable questions went:** 139 failed at question time (119
`gated_out` by the blind gate, 20 `sql_failed`), and 90 passed the gate but
could not be broken -- every variant still graded correct. The second group is
explained by output width: **61% have a 1-row gold** against 31% of the usable
set, and a single scalar gives the error templates nowhere to go.

**59% of negatives return exactly gold's (rows, cols)** -- the regime where
shape carries no signal, matching the 67% collision rate measured on real
Spider 2.0 pairs in 1(c):

| error type | pairs | same shape as gold | "pick longer" |
|---|---|---|---|
| `wrong_values` | 641 | 93% | 49.1% |
| `missing_column` | 312 | 2% | **99.7%** |
| `missing_filter` | 116 | 66% | 67.7% |
| `set_vs_grain` | 98 | 6% | 25.5% |
| `fanout` | 78 | 79% | 33.3% |
| `boundary` | 68 | 38% | 73.5% |
| **all** | **1,313** | **59%** | **61.3%** |

The last column is why 4.0.1 drops most of `missing_column`.

**Distribution check against the benchmark.** Spider 2.0's 135 locals: median 3
rows, 33% single-row. Our 771 usable: **31% single-row** -- well matched at the
floor. The mismatch is the tail: our median is 17 rows (p90 69), and questions
run 69 words against the benchmark's 46. If judge accuracy on the 135 lags what
held-out accuracy predicts, this gap is the first place to look.

### 3.8 Reproducibility bug (fixed, but after this dataset)

`str.__hash__` is salted per interpreter (`PYTHONHASHSEED`), and three scripts
seeded RNGs from it, so `--seed` did not determine output and `--resume` did not
reproduce the plan it resumed. Measured: `hash("store_1.sqlite") & 0xFFFF` gave
14513, 33050 and 28089 across three processes.

Affected: `populate_db.py` (the 300 databases), `synth_negatives.py` (error-type
choice), `synth_questions.py` (combination order). All three now use a
crc32-based `stable_hash()`.

**This dataset predates the fix.** `provenance.synth_seed` on these records is
not sufficient to rebuild them, and the 300 populated databases (840 MB, Babel
`~/synsql_filled/`) are not in git and cannot be regenerated. Treat them as
irreplaceable until the set is regenerated under the fix.

---

## 4. Training

**Base model: `Qwen/Qwen3.6-35B-A3B`** (the bf16 base, not the AWQ repo).

### 4.0 Data assembly (`scripts/build_judge_pairs.py`, to write)

The dataset as committed is **not** in trainable form. Two gaps:

- **No result values for negatives.** `main1k.jsonl` carries `gold_preview`,
  but `main1k_negatives.jsonl` stores only `rows`/`cols` per negative. Every
  negative SQL must be **re-executed** to produce its 15-row CSV. This needs
  `~/synsql_filled/` on Babel -- the only copy, since 3.8's hash bug means the
  databases cannot be rebuilt from their recorded seed.
- **No schema.** Derivable from `db_file`; emit a compact column list, and
  resolve table references by parsing rather than substring match (a table
  named `user` must not drag in `users`).

One record per pair, side-agnostic so the loader owns position balance:

```json
{
  "pair_id": "syn0186#0", "item_id": "syn0186",
  "question": "...", "schema": "songs(song_id, name, genre, ...) ...",
  "chosen":   {"rows": 5, "cols": 3, "result_csv": "...", "sql": "..."},
  "rejected": {"rows": 5, "cols": 3, "result_csv": "...", "sql": "...",
               "error_type": "wrong_values"},
  "bucket": "multi_clause", "hard": false, "split": "train"
}
```

`chosen`/`rejected` name the **answer**, not the query. Each record renders to
**two** training examples -- `(chosen, rejected) -> "A"` and
`(rejected, chosen) -> "B"` -- so the model never sees a label attached to a
position. ~1,100 pairs become ~2,200 examples.

**Report real token lengths, not a heuristic.** Tokenize with the actual Qwen
tokenizer and print p50/p90/max per arm. `chars/3.6` is calibrated on English
prose and under-counts a mostly-numeric prompt badly -- `504075` is 2-3 tokens,
not 1.7. Sequence length drives both the memory ceiling and the GPU hours.

### 4.0.1 Training-set composition

Drop most of `missing_column`. It is simultaneously the length shortcut (99.7%
"pick longer") and 98% shape-detectable, so it contributes little but a cheat:

| | pairs | "pick longer" |
|---|---|---|
| all pairs | 1,313 | 61.3% |
| **excluding `missing_column`** | **1,001** | **49.4% (chance)** |

| training set | pairs |
|---|---|
| all non-`missing_column` | 1,001 |
| `missing_column`, length-balanced sample | ~100 |
| **total** | **~1,100** |

Keep a little: `missing_column` is 45 measured lane-failures, so the judge must
not go blind to it. Capping it keeps the length baseline near chance.

**Split by `item_id`, never by pair.** 542 questions contribute two pairs
sharing an identical question and gold; a pair-wise split puts siblings on both
sides and inflates held-out accuracy through memorisation. Reserve ~15% of
*questions*, stratified by bucket and hard/normal. 771 distinct questions is the
number that governs what the judge can learn.

### 4.1 Why 35B and not the 9B

CHASE-SQL's ablation is the cleanest evidence that judge base quality matters:

| tuned selector | binary accuracy |
|---|---|
| Gemma-2-9B | 64.28% |
| Gemini-1.5-Flash | **71.01%** |

A ~6.7 point gap from the base model alone, on the identical task and data.

And the MoE makes it nearly free. At **3B active parameters per token**, the
35B-A3B costs *less* compute per training token than a 9B dense model:

| | active params | FLOPs/token (fwd+bwd) | 36M tokens |
|---|---|---|---|
| Qwen3.6-35B-A3B | 3B | 1.8e10 | 6.5e17 |
| Qwen3.5-9B dense | 9B | 5.4e10 | 1.9e18 |

The binding constraint is **memory, not compute**. So the 35B wins on both
quality and cost. Use the 9B only as a fast pipeline-debug loop.

### 4.2 Configuration

Objective: ordinary SFT with a **single-token target**. Causal-LM loss on that
one token *is* the binary cross-entropy we want. **Do not add a classification
head** — it breaks vLLM serving and buys nothing.

Hardware available: A6000 48GB ×1 or ×2, L40S 48GB ×1.

| option | memory | fits | notes |
|---|---|---|---|
| **QLoRA, NF4 4-bit** | ~17.5GB weights | **1× A6000** | recommended; grad checkpointing, batch 1 + accum |
| bf16 LoRA, FSDP | 70GB weights | 2× A6000 (96GB) | 26GB left for activations — tight |

LoRA on attention projections (q/k/v/o). Target the router or experts only if a
first pass underfits — MoE expert-wise LoRA is fiddly and rarely needed when the
task is discrimination over provided evidence.

Sequence length ~3K (question + schema + 2 SQLs + 2 result previews).

### 4.3 Time

| step | estimate |
|---|---|
| environment setup (peft/trl/bitsandbytes — **none in the repo today**) | 0.5 day |
| port `eval.py` scorer for synthesized gold | 0.5 day |
| cheap enrichment, ~300 SynSQL DBs | ~2 h |
| 100-item pilot: tune to p ≈ 0.5, fix K | ~1 h, ≈$2 API |
| **synthesize ~3,700 items + blind round-trip gate** | ~1.5–3 h wall, **≈$59 API** |
| **candidate generation, 13,333 episodes (K=6)** | **~37 h** on one server at 360 ep/h measured; **~9 h sharded ×4** |
| pair building + hard filter | ~1 h |
| **QLoRA training, 3.6K pairs × 3 epochs ≈ 32M tokens** | **~5–7 h** on 1× A6000 |
| merge LoRA → bf16 → re-quantize to AWQ | ~1–2 h |
| evaluation (135 + LiveSQLBench + BEAVER) | ~2 h |

**Wall clock: ~3 days**, of which ~20 h is GPU. Generation dominates, and shards
cleanly.

### 4.4 Data scaling curve -- the gate on a second round

Do not decide up front whether the data is enough. Train on nested subsets and
read the curve. With ~1,100 pairs and 15% of questions held out, ~935 pairs are
trainable:

| rung | pairs | what it answers |
|---|---|---|
| 1 | 250 | does the single-token format train at all |
| 2 | 500 | first real signal on held-out pair accuracy |
| 3 | ~935 | is the curve still climbing |

**Establish the origin first.** The measured **65.64%** baseline comes from real
Spider 2.0 candidates, not synthetic pairs, and is *not* this curve's zero
point. Run the untuned 35B over the held-out set and report it alongside two
reference baselines: "pick longer" (~50% by construction, see 4.0.1) and
"always A" (50% once position-balanced). If untuned accuracy on held-out pairs
is already ~85%, the pairs are too easy and every later number is hollow.

Report two numbers at each rung:

1. **Held-out pairwise binary accuracy** -- the direct training metric.
2. **End-to-end on the 135** via the Copeland tournament. 5.1's simulation maps
   pair accuracy to questions correct, so this also *validates the simulation*:
   if measured end-to-end tracks the predicted column, the independence
   assumption in 5.2 holds; if it falls short, judge errors are correlated and
   every projection in 5 is optimistic.

**Decision rules:**

| curve shape | reading | action |
|---|---|---|
| flat by 500 pairs | data is not the lever; the discriminating information is probably not in the input | **stop.** Fix the input representation (2.1's arms) before spending more |
| still climbing at ~935 | more data pays | generate a second round: ~1,300 more pairs for ~$18 of the $28.49 left, ~1.25 h on a proven pipeline |

**What this curve cannot resolve.** Our top rung (~935) is the plan's *second*
rung. If accuracy is still climbing there -- the likely outcome -- that says
more data helps but not how much, and cannot separate "a lot" from "a little".
The curve's real value is the opposite result: **flat by 500 is decisive** and
saves the $18.

**Cost:** at ~350-400 tokens per example in arm A rather than the ~3K the
original estimate assumed, 250 + 500 + 935 pairs x 3 arms is a few GPU-hours,
not the 12 projected for the 3.6K ladder.

### 4.5 Serving risk

The AWQ repo is **not trainable**. Train on the bf16 base, then either merge the
adapter and re-quantize to AWQ with `autoawq`, or serve bf16 + LoRA across
2× A6000 (`--enable-lora`). Do not expect a LoRA trained on NF4 to load onto an
AWQ base. Decide this before training so the eval path exists.

---

## 5. Estimated performance

Anchors, all measured or published:

| | |
|---|---|
| our untuned pairwise binary accuracy | **65.64%** |
| CHASE-SQL untuned range | 58.01–63.98% |
| CHASE-SQL tuned (Gemini-1.5-Flash) | **71.01%** |
| CHASE-SQL end-to-end vs self-consistency | 73.01 vs 68.84 (**+4.17 EX**) |
| GradeSQL ORM vs majority voting (BIRD dev) | 66.95 → 68.90 (**+1.95 EX**) |

We start *above* CHASE-SQL's untuned range, so expect tuned binary accuracy of
**72–76%** rather than their 71% — plus the order-symmetric scoring converting
the **44% of flips** from noise into decisions, which is a gain their number
does not include.

### 5.1 Simulated accuracy curve

Rather than borrow a headroom-capture rate, simulate a Copeland tournament over
the **real** candidate sets: a judge with per-pair accuracy `p` decides each
decisive pair correctly with probability `p`, and non-decisive pairs (both right
or both wrong) are coin flips, which is what they are in practice.

| per-pair accuracy | N=4, questions correct | N=16, questions correct |
|---|---|---|
| 0.500 (chance) | 68.7 | 62.2 |
| 0.556 | 71.9 | 72.3 |
| **0.656 (today, measured)** | **76.0** | **89.2** |
| 0.700 | 79.3 | 94.9 |
| 0.750 | 82.0 | 100.2 |
| 0.800 | 84.2 | 104.4 |
| 0.850 | 86.8 | 107.3 |
| 1.000 (ceiling) | 94.0 | 111.0 |

**The model validates itself**: at our measured 65.64%, the N=4 column predicts
**76.0** — exactly our measured 76. That calibration is what makes the rest of
the curve worth reading.

Two things fall out, and they reorder the whole plan.

**More candidates beats a better judge.** Holding the judge fixed at today's
65.6%, going N=4 → N=16 is worth **+13 questions** (76 → 89). Fine-tuning at
N=4 to p≈0.75 is worth **+6** (76 → 82). The tournament amplifies a
modestly-good judge: 12 groups give 66 pairs to aggregate over instead of 6, so
independent errors average out.

**Together they compound.**

| | p=0.656 (today) | p=0.75 (tuned) | p=0.80 (tuned, optimistic) |
|---|---|---|---|
| N=4 | **76** (measured) | 82 | 84 |
| N=16 | 89 | **100** | 104 |

### 5.2 What to discount

- **The independence assumption is untested at N=16.** The simulation treats
  pair decisions as independent given `p`. It reproduces N=4 exactly, so
  independence roughly holds there — but if the judge makes *correlated* errors
  (systematically preferring shape-matching wrong answers, say) the aggregation
  benefit shrinks, and in the fully-correlated limit it vanishes. The
  reassuring evidence: our 44% order flips are genuine noise, not a systematic
  preference, and the judge is 78% accurate whenever it does commit. Noise
  aggregates harmlessly; bias does not. **Step 2 of §6 tests this directly for
  a few GPU-hours and is the single highest-value experiment in this plan.**
- **The N=16 ceiling of 111 is optimistic** — those lanes are 4 configs ×
  4 samples, so part of the diversity is config-driven. A single-config
  16-sample pool is probably 103–106, which pulls the p=0.75 row from 100 to
  roughly **94**.
- BIRD's candidate pools cluster far more tightly than ours (18% all-distinct
  at N=16 here), so voting-adjacent signal that helps published ORMs is weaker
  on this pool.

**Working projection: 94–100 questions (70–74%) from N=16 plus a tuned judge**,
against today's 76. §4.4's scaling curve is the empirical check on this — it
reports measured end-to-end alongside the predicted column, so a shortfall there
means judge errors are correlated and these projections are optimistic. Of that, roughly **+13 comes from candidates and +11 from
training** — which is why the cheap step goes first.

The honest caveat: **our prompt-engineered judge already captures about what a
trained verifier captures on BIRD.** The large win is not a smarter judge at
N=4; it is more candidates, with a trained judge to exploit them.

One methodological advantage: judge experiments run on a **frozen** candidate
pool, so they escape the ±9-question vLLM noise floor that makes generation A/Bs
unresolvable. A 3-question judge difference is measurable.

---

## 6. Order of work

Cheap things that might obviate the expensive thing come first.

| # | step | status | cost | why here |
|---|---|---|---|---|
| 1 | Email BIRD team for LiveSQLBench `sol_sql`; request BEAVER | open | 0 | long lead, blocks clean eval |
| 2 | **Synthesize ~1,000 questions + construct verified negatives** | **DONE 2026-11-01** | $17.57 | 3.7 — 771 questions, 1,313 pairs |
| 3 | **Generate 12–16 single-config lanes; rerun the current judge** | open | GPU hours, no training | predicted **+13 questions (76 → 89)** with no model change, and the decisive test of 5.2's independence assumption |
| 4 | **Run arm B** — judge sees the tool trace | open | ~30 min, coded | tests whether execution evidence breaks the 67% shape-collision wall *before* training |
| 5 | **`build_judge_pairs.py`** — re-execute negatives for previews, compact schema, 3 arms, question-level split | next | ~0.5 day | 4.0; needs Babel `~/synsql_filled/` |
| 6 | **Decidability probe**: strong model on arm A, ~100 held-out pairs, split by gold row count | next | ~$1 | 2.3 — do we have label noise on the 31% single-row slice |
| 7 | **Untuned baseline on the held-out set** (all 3 arms) | next | ~1 h GPU | 4.4 — the curve has no origin without it; 65.64% is from a different distribution |
| 8 | **QLoRA pairwise SFT, scaling curve** (250 / 500 / ~935 pairs × 3 arms) | next | a few GPU-h | 4.4 — decides the second $18 round, and validates 5.1's simulation |
| 9 | Deploy the winning arm into `validator_select.py`, re-score the 135 | | ~2 h | train/serve consistency is non-negotiable |
| 10 | Evaluate: 135 + LiveSQLBench + BEAVER | | ~2 h | |

Steps 3 and 4 may move more than 5–10. Resolve them before committing to the
training run.

**Not recommended: DPO.** Our preference pair is `chosen="A"` vs `rejected="B"` —
one token, near-identical embeddings, which is precisely the regime where
likelihood displacement bites (Razin et al.: the effect is driven by pairs with
similar hidden embeddings, and DPO can satisfy its objective by pushing the
rejected down while mass drifts to a third output). Degradation would surface as
unparseable verdicts, easy to misread as a prompt bug. SFT also gives the
calibrated margin that DPO does not. If DPO is tried at all: after SFT, on
rationale+verdict outputs, never on bare letters.

The genuinely promising non-SFT route is **GRPO/RLVR** — the reward is verifiable
— but it only pays off for an *agentic* judge that runs its own verification
queries. Different and larger project.

---

## 7. Cost

GPU work runs on Babel, so it costs no money — only queue time. The only real
dollars in this plan are the synthesis API calls.

### 7.1 Money

**Budget: $50 cap on question synthesis.** It does not bind — $50 buys the
~3,700 items the plan needs, because the gate runs on Babel rather than the API.

| item | cost |
|---|---|
| **synthesis, 3,678 items × 2 calls on GPT-5.4** (gold SQL + question), with prefix caching | **$50.00** |
| intent-agreement gate — `rubric.py` on Babel | **$0** |
| 100-item pilot | $1.36 |
| all other GPU work on Babel | **$0** |
| **TOTAL** | **≈ $51** |

$/1,000 items by configuration, and what $50 buys:

| configuration | $/1,000 | questions for $50 |
|---|---|---|
| generate on 5.4, gate on 5.4-mini | $15.81 | 3,163 |
| **generate on 5.4, gate on Babel** | **$13.60** | **3,678** |
| everything on 5.4-mini | $6.29 | 7,948 |

Take the middle row. All-mini buys 2.2× the questions, but gold-SQL and question
phrasing quality decides whether the dataset is trainable at all — that is the
one step not to economise on. Moving the gate to Babel is free quality: it was
always meant to be a *different* model, not a better one.

**Do not run the gate on Qwen3.6-35B** — the same model as the candidate
generator. It would pass only questions that model reads correctly, filtering
out the ones it *misreads*, and misreading (set-vs-grain) is one of our measured
failure modes. Use Qwen3.5-9B: different model, still free, and stating an
expected output shape is within its range.

What $50 yields, under both gate assumptions:

| | gate 60% (the guess) | gate 80% (intent-agreement) |
|---|---|---|
| synthesized | 3,678 | 3,678 |
| pass the gate | 2,207 | 2,942 |
| **usable questions** | **1,125** | **1,501** |
| raw pairs | 5,963 | 7,953 |
| **training pairs after filter** | **~3,580** | **~4,770** |
| candidate episodes | 13,240 (9.2 h ×4) | 17,654 (12.3 h ×4) |

Either way we meet or beat CHASE-SQL's 3,800 pairs. The cost that grows is GPU
time, not dollars.

Two items that would cost money if run on the API but are free on Babel:

| if run on API instead | cost |
|---|---|
| step 2: 12 extra generation lanes | $65.76 |
| one N=16 judge evaluation pass (18,360 comparisons, 55M input tokens) | $14.25 on mini / $47.51 on GPT-5.4 |

Worth knowing the second number anyway: it means a full N=16 judge sweep on a
frontier model as a *baseline comparison* is $14, which is cheap enough to be
worth one run for the writeup.

### 7.2 GPU time (Babel)

| step | hours |
|---|---|
| step 2: 12 extra generation lanes | 4.5 |
| cheap enrichment, 300 SynSQL DBs | 2.0 |
| difficulty pilot (100 items × K=6) | 1.0 |
| candidate generation, 13,333 episodes (K=6) | 37.0 |
| QLoRA pairwise SFT on 35B-A3B, as a scaling curve (§4.4) | 12.0 |
| merge LoRA + re-quantize to AWQ | 1.5 |
| judge inference passes (ablations) | 3.0 |
| final eval: 135 + LiveSQLBench + BEAVER | 2.0 |
| **TOTAL** | **73 GPU-hours** (≈31 h wall if generation shards ×4) |

For reference, if this ever had to move off Babel: ~$20 on Vast.ai A6000
($0.28/h), ~$39 on RunPod A6000 ($0.53/h), ~$80 on Lambda ($1.09/h).

### 7.3 The cost that actually binds

Not dollars — **wall clock on Babel.** 73 GPU-hours on one A6000 becomes 4–7
days in practice, because:

- vLLM on A6000 can SIGBUS after ~24h uptime (CLAUDE.md), so servers are
  ~1-day services and the candidate-generation step needs the resume wrapper.
- `preempt`/`preempt_qos` jobs requeue; `lilab`/`lilab_qos` does not but queues.
- Candidate generation (37 h) shards cleanly across GPUs — run it as 4 shards
  and it is ~9 h instead of a day and a half. Training does not shard.

### 7.4 Pre-flight checks before starting

- **Disk.** The bf16 `Qwen/Qwen3.6-35B-A3B` base is ~70 GB, plus an NF4 copy
  (~18 GB), the merged bf16 output (~70 GB) and the re-quantized AWQ (~24 GB):
  **budget ~180 GB** of scratch under `/data/user_data/juliep2`. Check this
  first — it is the most likely thing to stop the run halfway.
- **Training env.** peft / trl / bitsandbytes are **not in the repo today** and
  must not be installed into `.vllm-venv` (the serve scripts pin
  `transformers==5.5.3` with `regex>=2025.10.22`, and a reinstall can silently
  downgrade regex). Use a separate training venv.
- **Decide the serving path before training** (§4.5): the AWQ repo is not
  trainable, and a LoRA trained on NF4 will not load onto an AWQ base.

## Sources

- CHASE-SQL — <https://arxiv.org/abs/2410.01943> (selector: LoRA r=16 on
  Gemini-1.5-Flash, 10 epochs, ~3.8K pairs, candidates clustered by execution
  result, order shuffled; Tables 5–7)
- GradeSQL / Test-Time Verification via Outcome Reward Models —
  <https://arxiv.org/html/2606.30851> (LoRA Yes/No head on OmniSQL-7B, N=32
  candidates, 30,686 balanced samples from BIRD train)
- OmniSQL / SynSQL-2.5M — <https://arxiv.org/pdf/2503.02240>
- LiveSQLBench — <https://huggingface.co/datasets/birdsql/livesqlbench-base-lite-sqlite>
- BEAVER — <https://arxiv.org/abs/2409.02038>
- SWE-SQL / Six-Gym (SQL-Rewind hard-negative synthesis) —
  <https://arxiv.org/pdf/2506.18951>
- Likelihood displacement in DPO (Razin et al.) —
  <https://www.semanticscholar.org/paper/efae534e2a3e4b79fe4050fa3fd40d8c7ba9745b>
- CAPER (process RMs underperform: +0.7 to +1.6 over majority voting) —
  <https://arxiv.org/pdf/2606.03327>

Our own numbers: `results/validator_jrg_*.csv`, `results/validator_pwrg.csv`,
`logs/traces/validator_pwrg/*.json`, `results/validator_think9b_*.csv`,
`logs/traces/q36{rg,re,s}_*`.
