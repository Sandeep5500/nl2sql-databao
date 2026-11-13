# Judge and answer selection: results, Oct 23 – Nov 13 2026

What was built and measured for the pairwise judge that picks one of the agent's 4 candidate answers.
All numbers are measured unless marked *(estimate)*. Short version:
[judge_findings.md](judge_findings.md). The prompt-variant protocol is
[judge_prompt_eval.md](judge_prompt_eval.md); the trace-verification pre-registration is
[head_probe_prereg.md](head_probe_prereg.md).

## 1. Setup

- **Candidates.** Each question has 4 lanes of the agent (Qwen3.6-35B-A3B):
  - Spider2: 4 saved run sets (q36rg, q36s, q36, v2) × 135 questions = **540 pools**.
  - BigQuery: Rohini's 4 retries of the 107 questions greedy got wrong = **105 pools**.
- **Judge.** The agent's own model (QuantTrio/Qwen3.6-35B-A3B-AWQ), thinking on, temperature 0.6, up
  to 8,192 tokens. It sees the question, the doc, a schema overview, both SQLs and 8-row result
  previews.
- **Round-robin.** Every pair of distinct results is judged in both orders; the most wins is
  submitted.
- **Scores.** Correct picks out of 540 (Spider2) and 105 (BigQuery).
- **Noise.** Two identical judge runs differ on about 23 of 540, so single-run gaps under about 10
  are noise.
- **exp1** (from Nov 12): each ordered pair is judged 4 times, and exp1 is the exact expected
  accuracy of the deployed single-sample round-robin, which cuts that noise.

## 2. Baseline judge

| selection | Spider2 (of 540) | BigQuery (of 105) |
|---|---|---|
| plain majority vote | 261 | 22 |
| judge, thinking off | 281 | 24 |
| **judge, thinking on (deployed)** | **296** (rerun 293) | **26** |
| pass@1 (average lane) / pass@4 (any lane right) | 234.8 / 346 | — / 42 |

- **Other judges.**
  - JEV-27B scored 83 on q36rg (vs 82) and 29 on BigQuery. Its edge comes from its base model.
  - Combining 35B and JEV gave 85 on q36rg (+5 to +7 over 540), not significant, and needs a second
    model.
- **Did not help:**
  - a test-query "probe" judge;
  - database context in the prompt;
  - trace-note summaries (+8 / −7 over 405);
  - extra rule layers (296 → 282);
  - voting over 3–11 samples (296 vs 293);
  - two samples per pair (299, +6 / −3, not significant).
- **Where it misses.** 346 of 540 pools have a correct lane.
  - Right picks by the number of correct lanes: 1 → 47/81, 2 → 45/58, 3 → 75/78, 4 → 129/129.
  - In the 40 pools missed in both thinking runs (29 of them lone-correct), the right answer still
    wins 45% of its pairwise judgments: "can't tell", not confidently wrong.
  - Biases: right 85% of the time when shown first vs 71% second; right 88% when the right answer has
    fewer columns vs 75% when it has more.
- **Headroom.** About 10–15 of 540 for any judge reading these inputs *(estimate)*. A blind Claude
  reader of the same inputs gained about +5 of 69 design-half close calls.

## 3. Judge training data (practice pairs, never Spider2)

- **What a pair is.** A practice pair is a question on a non-Spider2 database plus one right and
  one wrong answer from our agent.
- **What is excluded:**
  - databases that copy Spider2's (BIRD movie_3, works_cycles, soccer_2016, sales, …);
  - Spider2-derived sets (deny-list in `judge_data_deny.json`, check `check_db_overlap.py`).
- **Held out:** the 15 val-split databases throughout. From v2a on, also 10 of the 48 training
  databases (`holdout.json`, seed 0): 25 of 63 in all.
- **Exact losses, data rows, settings and commands:** [judge_training_methods.md](judge_training_methods.md).

| source | how it was made | size | yield and label quality |
|---|---|---|---|
| BIRD-Platinum | Re-checked BIRD questions (ReViSQL, 2,064 train / 398 val); our agent, 4 lanes, on 1,739 train-split questions | about 2,000 questions | Only about 1 question in 5 gives a pair. SQL is much simpler than Spider2's (median 228 vs 1,266 chars). |
| Claude-written | Trap questions on BIRD databases (look-alike columns, grain, fan-out) plus plain ones. Sonnet wrote; Opus solved blind and reviewed; checks on altered database copies. | about 1,000 accepted (wave 1: 115; Nov 7: 330; hard h1: 113; hard h2: 224) | Many too easy: 27% gave pairs in the Nov 7 batch. Hard batches: 35% vs 25%, and 32% vs 28% (p = 0.42), on the same databases. 7–14% "another fair reading". |
| Qwen-written complex | Qwen wrote a 3–6 CTE query, then the question, then checked it | 400 of 1,632 attempts | Spider2-length SQL. The same model wrote the key and the answers, so shared mistakes went unseen; about half of the never-right pairs had an ambiguous key. Stopped Nov 7. |
| BEAVER | A real data warehouse plus 2 OpenStack databases, copied to SQLite. Gold re-run on MySQL 9.3: 7,978/7,978 ok; 1,975 kept after dropping VARIANCE/STDDEV golds. | 600-question pilot | 16% split. 27% "another fair reading" (questions written from SQL leave choices unstated). Stopped after the pilot. |

- **Label check** (`check_pair_labels.py`): a model must quote the question words that the "wrong"
  answer contradicts, or the pair is dropped. On a hand-checked sample it caught about half of the
  doubtful labels.
- **Final build** (`judge_train_v4/data_v6`): 2,644 letter rows over 1,814 ordered pairs.
- **Stored judgments:** 10,715 usable thinking judgments with full reasoning, 4 per ordered pair over
  2,684 ordered pairs. Only 22% of ordered pairs have samples that disagree (419 after the label
  check).

## 4. Fine-tuning (Nov 1–11)

- **Setup.** Every run is LoRA r16 on attention, linear attention and the shared experts, merged
  into the AWQ checkpoint (`merge_judge_adapter.py`) and evaluated as served by vLLM.
- **Gates.** "Gate" = held-out practice pairs judged against fresh untuned samples.

| run | recipe | held-out practice pairs | Spider2 (of 540) | BigQuery (of 105) |
|---|---|---|---|---|
| untuned | — | — | think 296 / 293; no-think 281 | think 26; no-think 24 |
| v1 | SFT on 2,750 self-sampled right judgments, then DPO on 423 pairs (lr 5e-6) | no change, even on its own training pairs (57.3% → 57.8%) | 290 | — |
| v2a | DPO only, 848 rows, lr 5e-5, 2 epochs | mixed 62.0% → 71.8% (p = 0.08); always-right 92.2% → 84.4% | 287 | — |
| v2b | as v2a, lr 1.5e-4 | diverged (output only "!") | — | — |
| v3c | v2a + 400 Qwen complex questions (1,476 rows) | complex held-out mixed only +3.0 (n = 58, p = 0.55) | 290 | — |
| **v4** | letter only: 2-way cross-entropy on A/B, thinking off, 2,006 rows | complex held-out 57.2% → 70.2% | **287** (vs no-think 281). Per pair 72.9% → 78.6% (65/34, p = 0.002) | **30** (vs 24) |
| v4, 1 epoch | as v4, half the training | worse (complex held-out mixed 51.7% vs 65.5%) | 287 | 28 |
| v5c | v4 + 128 Claude pairs | a wash | 287 | 27 |
| v6 | v5c + 342 pairs (Claude h1/h2, BEAVER) | failed the pre-set bar | 288 | 27 |

- **v4 as a tie-breaker** for the thinking judge (exploratory, chosen after seeing results):
  - Spider2 296 → 304 and 293 → 298; BigQuery 26 → 30.
  - Controls: the untuned no-think judge 300 / 293; JEV 302 / 300.
- **Lessons.**
  - Compare against fresh untuned samples: stored samples that chose the pairs regress.
  - Selecting hard pairs by the runs that measure them faked +17.
  - v1, v2a and v3c were evaluated at temperature 0.2 (bug fixed Nov 7, not re-run).
- **Open caveat (Nov 13):** see §7. The training path may have run on a broken forward pass.

## 5. Without training: prompt variants and selection rules (Nov 12)

Pre-registered (judge_prompt_eval.md):
- Spider2 split by database into a design half and a test half.
- 4 fresh samples per ordered pair.
- At most 2 variants admitted from the design half.
- Test-half bar: 95% interval above 0 (97.5% with two variants), easy pools −1.5 at most, BigQuery
  −1.5 at most.

| close-call pools (1–2 of 4 lanes right) | design (69), change | test (70), change [97.5%] | easy pools, both halves | BigQuery mixed (37) |
|---|---|---|---|---|
| **diff_cmp**: list the SQL differences, check each against a computed comparison of the two full results | +4.5 | **+7.2 [+1.9, +13.0]** (25 up / 8 down) | +0.4 | +2.9 |
| diff_nocmp: the same without the comparison | +4.9 | +5.1 [+1.6, +9.1] | **−2.4 (fails)** | +3.3 |
| rules (cleared the design bar, not taken) / spec (failed) | +4.0 / +2.6 | — | — | — |

- **Adopted:** `diff_cmp`.
  - Whole-benchmark exp1: Spider2 293.4 → 305.6 (about +3 questions per run set), 310.4 with rule U
    on top; BigQuery 24.8 → 27.7.
  - Position bias drops: with the right answer shown second, right 74% → 84%.
  - Cost: about +23% judge tokens; about 1% of calls truncate.
- **Rules (no GPU), re-checked on the fresh baseline:**
  - U (switch to an answer with the same rows plus extra columns): +3.7 [0.0, +11.0] on the test
    half, 5 up / 0 down. It has never lowered a pool, but misses the bar by the letter.
  - T (wider-first tie-break): fails.
  - Neither is adopted.
- **Production:** `select_answer.py --mode pairwise --thinking` now defaults to
  `--judge-prompt diff_cmp` and computes the comparison at judge time.
  - Offline, it reproduces the evaluation's comparison text in 391 of 412 pairs. The rest are
    row-order ties, or one question whose SQL is nondeterministic.
  - A live 3-question smoke test passed with 12 calls and 0 failures; the third question was still
    running.

## 6. Trace verification (Nov 12–13, in progress)

**Question.** Can a trained readout, or one read from hidden states, tell which of the judge's
sampled reasoning traces for the same comparison reached the right verdict?
- The verdict's own probability is always within 0.01 of 0 or 1 (read from the top-5 log-probs),
  so it can't.
- This is the useful form of "train with reasoning but read a CLS / vector head". The A/B-letter loss
  is already a linear head on the last hidden state.

Close-call exp1 on top of `diff_cmp` (no fitting on Spider2):

| | design | test | BigQuery |
|---|---|---|---|
| deployed (1 sample per ordered pair) | 50.7 | 50.9 | 15.2 |
| average of 4 samples | 52.0 | 54.0 | 16.0 |
| rule A: re-sample only the pairs whose two orders disagree (about 1.4–1.6× calls) | 52.6 | 53.1 | 16.3 |
| rule F: v4 settles those pairs (second model) | 53.3 | 52.4 | 18.3 |
| oracle: flip wrong traces in mixed ordered pairs | 60.1 | 63.0 | 22.8 |

- **Cheap signals.** Reasoning length and hedge words predict which pairs are hard (pooled AUROC
  about 0.65–0.7), but not which trace inside a pair is wrong: within-pair AUROC about 0.50–0.55 on
  Spider2 and 0.57 on practice data.
- **Old DPO judges as trace verifiers** (implicit reward log π_dpo − log π_base, 2,843 held-out
  practice traces, scored in vLLM): within-pair AUROC v2a 0.648, v3c 0.646, against 0.584 for
  shorter-reply-first. That is +0.06 [−0.01, +0.14], within noise.
- **Stage A frozen probe:** pre-registered (gate: within-pair AUROC ≥ 0.65 and ≥ baseline + 0.05 on
  held-out practice databases). Its extraction is blocked by §7.

## 7. Open issue: the HF forward pass (Nov 13)

- **The failure.** The hidden-state extraction's identity check failed: its letter readout matched
  the stored verdict on 57/100 and 53/100.
- **The inputs are correct.** The served judge (vLLM, AWQ), given the same token ids, gets 24/24.
- **The model is intermittent.**
  - A first diagnostic of the bf16 model in HF transformers 5.5.3 was correct: 24/24, " Paris",
    0.18 nats per token on its own reasoning.
  - A second one, same code and same node an hour later, was broken: logit gaps of exactly 0.0 or
    NaN, final-norm states of 0.
  - All runs were on 2× L40S.
- **Prime suspect.** Transformers 5.5.3 defaults the MoE experts to torch's fused `grouped_mm`. A
  diagnostic testing `eager` / `batched_mm` experts, layer by layer and with repeats, is queued.
- **Why it matters.** Every LoRA training above used this HF path, and the letter-only runs logged
  first-step losses of 1.1–1.16. Until it is resolved, the training results in §4 may understate what
  training can do.
- **Guards added:**
  - an identity check before training;
  - an `--experts` switch;
  - a merge-parity check planned before any evaluation.

## 8. Next experiments (after the fix)

| arm | pick loss | reasoning loss | question |
|---|---|---|---|
| C0 | letter, thinking off (v4) | — | Was v4 held back by the forward-pass issue? |
| C1 | letter, thinking off | next-token on own right reasoning, weight 0.25 | Does a second loss on reasoning help the pick? |
| C2 | letter read after own reasoning, for both the right and the wrong sample | next-token on the right sample's reasoning, weight 0.25 | Can a trained decision verify reasoning? |
| A | frozen probe on hidden states (no training) | — | Is the signal already there? |

- **Ablations,** only if a core arm beats C0: reasoning-loss weight 0; a bounded order-consistency
  term; a noise-robust pick loss.
- **Re-run of v2a** if the issue reached the DPO path.
- **Sanity checks on every run:** identity check, determinism check, step-0 loss check, NaN stop, and
  merge parity before evaluation.

## 9. Where things are

- **Data pipeline.** `build_bird_dataset.py`, `build_beaver_dataset.py`, `beaver_to_sqlite.py`,
  `beaver_gold_mysql.py`, `check_db_overlap.py`, `profile_traps.py`, `sql_mutations.py`,
  `generate_trap_items.py`, `validate_trap_items.py`, `stress_test_items.py`, `review_packets.py`,
  `question_waves.py`, `question_briefs/`, `sample_judge_verdicts.py`, `check_pair_labels.py`.
- **Training.** `make_judge_sft_dpo.py`, `train_judge_lora.py` (stages sft, dpo, choice, choice_mt,
  choice_reason), `merge_judge_adapter.py`, `judge_gate.py`.
- **Judging and evaluation.** `judge_pools.py`, `bq_judge_pools.py`, `judge_pairs.py`,
  `rejudge_pools.py`, `selection_eval.py` (exp1; rules @U / @T; soft votes @S), `judge_prompts.py`,
  `result_compare.py`, `build_compare_cache.py`, `analyze_pools.py`, `compare_judges.py`.
- **Trace verification.** `extract_judge_states.py`, `probe_fit.py`, `vstar_scores.py`,
  `vstar_eval.py`, `diag_hf_forward*.py`.
- **Cluster jobs.** `nl2sql-v2/slurm/`.
- **Results on Babel.** `/data/user_data/dpalagan/{judge-data,nl2sql-sel}/results/`.
