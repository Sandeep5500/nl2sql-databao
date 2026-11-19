# Judge and answer selection: results, Oct 23 – Nov 18 2026

What was built and measured for the pairwise judge that picks one of the agent's 4 candidate answers.
All numbers are measured unless marked *(estimate)*. Overview of the deployed judge: [judge.md](judge.md).
Short version: [judge_findings.md](judge_findings.md). The prompt-variant protocol is
[judge_prompt_eval.md](judge_prompt_eval.md); the trace-verification pre-registration is
[head_probe_prereg.md](head_probe_prereg.md).

## 1. Setup

- **Candidates.** Each question has 4 lanes of the agent (Qwen3.6-35B-A3B):
  - Spider2: 4 saved run sets (q36rg, q36s, q36, v2) × 135 questions = **540 pools**.
  - BigQuery: Rohini's 4 retries of the 107 questions greedy got wrong = **105 pools**.
  - BigQuery, all questions (Nov 17, §10): a fresh run of 4 lanes over all 204 = **204 pools**.
- **Judge.** The agent's own model (QuantTrio/Qwen3.6-35B-A3B-AWQ), thinking on, temperature 0.6, up
  to 8,192 tokens. It sees the question, the doc, a schema overview, both SQLs and 8-row result
  previews.
- **Round-robin.** Every pair of distinct results is judged in both orders; the most wins is
  submitted.
- **Scores.** Correct picks out of 540 (Spider2) and 105 (BigQuery; 204 in §10).
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
    on top; BigQuery 24.8 → 27.7. On all 204 BigQuery questions it gives no gain (§10).
  - Realized single runs (the k-th sample of every call, k = 0–3): Spider2 290 / 294 / 297 / 295 →
    305 / 306 / 307 / 304; BigQuery 24 / 26 / 26 / 24 → 28 / 30 / 25 / 27.
  - BigQuery comparisons come from the stored outputs (BigQuery bills per byte, so nothing is re-run).
    In 9 of the 37 mixed pools (52 of 280 comparisons) a stored output shows only some rows of a
    larger result: the agent's tool shows 12 rows unless the call asks for more (up to 50), so the two
    sides can show different numbers of rows. Found Nov 17: those comparisons listed rows not shown as
    missing ("only in B (38)" when A showed 12 of 666 rows; 42 of the 52) and printed long IDs as
    1.4253e+16. Every judge in the Nov 12–17 runs saw the same text; `result_compare.py` is fixed for
    the full BigQuery rerun (§10), and complete results give the same text as before.
  - Position bias drops: with the right answer shown second, right 74% → 84%.
  - Cost: about +23% judge tokens; about 1% of calls truncate.
- **On JEV-27B (Nov 14, `jev_variants.slurm`, same pools and candidates).** JEV's decision mode answers
  in one step, so it cannot follow the procedure; it was given the comparison appended to its usual
  input (one call per ordered pair; the decision is deterministic).
  - Spider2: 290.0 → 292.0 (+2.0 [−6.0, +10.0], 11 pools up / 9 down); contested design 47 → 49, test
    42 → 41. BigQuery: 29.0 → 29.0. The comparison changes 7–9% of its decisions.
  - The plain arm reproduces JEV's earlier runs (290 vs 289 on Spider2, 29 vs 29 on BigQuery).
  - Against the deployed 35B with `diff_cmp`: Spider2 305.6 (+15.6 [+2.2, +29.8] over JEV), BigQuery
    27.7 (−1.3).
  - Reasoning mode (Qwen3.8-27B unchanged, thinking on, 8192 tokens) with `diff_cmp`, 4 samples per
    ordered pair (Nov 15): better than the deployed 35B with `diff_cmp`, although a quarter of its calls
    truncate.
    - Spider2 317.4 vs 305.6: mixed pools +11.8 [+1.7, +22.0] (47 up / 30 down), contested +10.0
      [+0.9, +19.7]. Contested by half: design +5.7 [+0.1, +12.3], test +4.3 [−3.1, +11.8], so on the
      test half alone it misses the bar used for prompts; it was tuned on neither half.
    - BigQuery 33.3 vs 27.7: mixed +5.6 [+2.1, +9.5] (14 up / 6 down), contested +4.1 [+1.0, +7.5].
      On all 204 BigQuery questions (§10) the lead is smaller and not resolved: +3.3 [−0.9, +7.8].
    - Each of the 4 samples alone beats the 35B's 4 (Spider2 314–324, BigQuery 31–34). The samples
      ran on four servers.
    - Of the calls that give a verdict, 92–93% are right on Spider2 whichever answer is shown first
      (35B 80–89%). The first-shown answer wins both orders in 1% of pairs (35B 7–12%).
    - It truncates 25% (design), 16% (test) and 31% (BigQuery) of calls (35B 1.3%), mostly on hard
      pairs: where the 27B truncated, the 35B is right 66% of the time, elsewhere 89%. Truncated calls
      count as missing. With them all right or all wrong, Spider2 would be 327.3 or 295.4. So a larger
      budget could lower it below the 35B only if the 27B, given room to finish, were right on fewer
      than about a quarter of them (interpolated).
    - Old prompt, 4 samples: Spider2 307.7, BigQuery 32.5. On Spider2 `diff_cmp` helps the 27B too:
      mixed pools +9.7 [+3.1, +17.0], close calls +7.2 [+1.2, +13.7]. On BigQuery it adds only +0.9
      [−0.9, +3.0]; there the 27B beats the 35B with either prompt (old prompt vs the 35B with
      `diff_cmp`: +4.8 [+1.6, +8.4]).
    - It is a dense 27B: smaller than the 35B-A3B in memory, but about 9× its compute per token, and
      it writes more tokens. Qwen3.8 has no smaller model (27B, Flash-Next, 2.4T-A95B).
    - A first attempt was redone. It gave up on any request that took over 1800 s and drew it again.
      With about 75 requests per server, a long reasoning took longer than that, so long draws were
      replaced by short ones: 11–59% of the generated tokens went to abandoned requests, and
      truncation looked lower than it is (BigQuery 26–30% then, 31% now). Those calls are set aside
      (`*.timeout1800.jsonl`); `rejudge_pools.py` now waits up to 4 h and records timeouts. The 35B
      arms were not affected: a full 8192-token reply took about 600 s there, and their calls show no
      timeouts.
- **Other model families (Nov 16–17, `family_judge.slurm`; same pools and candidates, `diff_cmp`,
  thinking on, temperature 0.6, 8192 tokens).** One model at the size of each Qwen judge:
  GLM-4.7-Flash (MoE, 31B total / 3B active, next to the 35B-A3B; 4 samples per ordered pair)
  and Magistral-Small-2509 (24B dense, reasoning, next to the 27B; 1 sample). Neither beats the
  deployed 35B. Intervals are question bootstraps over each judge's samples.

  | judge | Spider2, each sample | BigQuery, each sample | Spider2 mixed vs 35B | BigQuery mixed vs 35B |
  |---|---|---|---|---|
  | Qwen3.6-35B-A3B (deployed) | 304–307 | 25–30 | | |
  | Qwen3.8-27B | 314–324 | 31–34 | +11.8 [+1.7, +22.0] | +5.6 [+2.1, +9.5] |
  | GLM-4.7-Flash | 293–300 | 24–31 | −8.6 [−16.3, −1.3] | −0.3 [−3.4, +2.8] |
  | Magistral-Small-2509 | 300 | 29 | −5.6 [−17.3, +5.8] | +1.3 [−3.6, +6.1] |

  - Every GLM and Magistral sample is below every 35B sample on Spider2, though for Magistral the
    question bootstrap does not resolve the gap. On BigQuery, Magistral's 29 is inside the 35B's range
    and GLM's samples (24–31) straddle it.
  - GLM writes long reasoning (median 3,800–5,100 tokens per call; 35B 2,800–3,200), and 22–31% of
    its calls reach 8192 tokens without a verdict, mostly hard ones: where GLM gives no verdict the
    35B is right 77% of the time on Spider2, elsewhere 89–91%. On comparisons both answer, GLM is
    also right less often: 79.0 vs 83.9% (design), 81.2 vs 85.6% (test), 65.7 vs 69.5% (BigQuery).
  - Magistral is short (median 1,600–1,900 tokens) and gives a verdict in 98.6–100% of calls, but on
    comparisons both answer it is right less often than the 35B: 80.6 vs 83.7% (design), 79.0 vs
    85.1% (test), 67.0 vs 69.5% (BigQuery).
  - Both lose when the right answer is shown second. The first-shown answer wins both orders in 15–18%
    of right-vs-wrong pairs for Magistral and 9–21% for GLM (35B 7–12%, 27B 0–1%). With the right
    answer shown first both are right about as often as the 35B (Magistral 87 / 86 / 72%, GLM
    87 / 90 / 77%, 35B 89 / 86 / 72% on design / test / BigQuery); shown second, Magistral is 5–12
    points below the 35B (75 / 72 / 62% vs 80 / 84 / 68%) and GLM 3–8 (77 / 77 / 60%).
  - So at this size the family changes how the judge fails: both favour the first answer, and GLM also
    runs out of tokens. The 27B, right more often with almost no position bias, is still the only judge
    clearly above the 35B, and Magistral shows that a dense model of its size is not enough by itself.
    Magistral got no further samples: one already places it well below the 27B.
  - Serving: Magistral's defaults set top_p, and vLLM's FlashInfer top-p sampler (compiled on first
    use) crashed its first request, so the jobs use vLLM's own sampler (`VLLM_USE_FLASHINFER_SAMPLER=0`,
    same distribution). Replies that name the winner but are not valid JSON (GLM can leave the reason
    unquoted) are read from the last "winner" field and marked `loose_json`: 42 of GLM's 3,492 calls,
    12 of Magistral's 1,746, none for the Qwen judges. Magistral wraps its JSON in ```json fences,
    which parse as usual.
  - Outputs: `results/selection_nov2026/` (`score_glm4_mistral1.txt`, `verdict_quality_glm4_mistral1.txt`,
    `diag_glm4_mistral1.txt`, `score_per_sample.txt`; the `*_glm2_*` files are the same with GLM's
    first two samples, Spider2 295.5).
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

## 6. Trace verification (Nov 12–14)

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
- **Stage A frozen probe (measured Nov 13): it passed its pre-registered gate, only just.**
  - Data: the untuned judge's hidden states at the end of its own stored reasoning, for all 10,715
    practice traces (each rebuilt sequence returned the stored verdict: 100%). After other-reading
    pairs are dropped: 7,249 training traces on 40 databases, 2,449 held-out traces on 26 databases.
  - Choice, on the training databases only: 24 settings (4 layers × 6 positions), by
    leave-one-database-out log loss. Frozen: layer 20 at the verdict position, with the strongest
    penalty in the grid (every setting chose it, so the grid edge may make the probe conservative).
  - Held out, over 466 right/wrong comparisons in mixed ordered pairs:

    | | within-pair AUROC | 95% interval |
    |---|---|---|
    | probe | 0.710 | [0.623, 0.799] |
    | baseline (verdict letter, reasoning length, hedge words) | 0.631 | [0.551, 0.706] |
    | difference | +0.079 | [+0.004, +0.156] |

    Gate: AUROC ≥ 0.65 (yes), difference ≥ 0.05 (yes), interval above 0 (yes, by 0.004).
  - By source (probe vs baseline, comparisons): BIRD-Platinum 0.76 vs 0.62 (128), complex 0.63 vs
    0.56 (124), Claude h2 0.81 vs 0.76 (63), Claude h1 0.73 vs 0.81 (26), BEAVER 0.53 vs 0.47 (30).
    The Spider2-like sources together (complex + h1 + h2, 213): 0.695 vs 0.653, a smaller gain.
  - Pooled AUROC 0.792 (baseline 0.692); Brier 0.151 (0.172).
  - The judge's own confidence in its verdict, read at the same position, scores 0.448 (§8). The
    signal is in the hidden states, not in the probability of the letter the judge writes.
  - Within an ordered pair every right trace picked the same candidate, so this metric rewards any
    score that prefers the right candidate. That is what selection needs.
  - Fixed before the one held-out scoring: the probe lacked the pre-registered presentation-order
    covariate. It is constant within an ordered pair, so it cannot move this metric directly.
- **Stage B (started Nov 13).** Step 1 regenerates the practice judgments with `diff_cmp`
  (`practice_dc.py`: same pairs and candidates; the candidates' SQL is re-run for the result
  comparison). Step 2 refits the frozen probe on them and re-checks the gate. Step 3, only if that
  passes, scores it once on the Spider2 design half (`calls_to_records.py`, then states, then
  `probe_votes.py` and `selection_eval.py` @S) against deployed, rule A and rule F.
- **Stage B step 1 done (Nov 14).** All 7 practice files were re-judged with `diff_cmp`.
  - 10,736 samples, 0 errors. 0.1–1.6% were cut off at the token limit (Claude h2: 6.1%).
  - On the same ordered pairs, `diff_cmp` samples are right 73.7% of the time, against 71.8% for the
    stored samples.
  - Per file (`diff_cmp` vs stored): BIRD-Platinum 77.1 vs 74.9, complex v2 67.5 vs 65.5, Claude v3
    77.9 vs 75.7, h1 76.4 vs 75.0, h2 79.6 vs 75.2, BEAVER 63.4 vs 63.3. Only complex v1 is lower:
    57.3 vs 61.4, on 368 samples.
  - 96 of 2,684 ordered pairs (3.6%) got no comparison, because a candidate's SQL did not reproduce
    its stored result.
- **Stage B step 2: gate A passed again on `diff_cmp` reasoning (Nov 14, scored once).** The frozen
  probe (L20, verdict position, C = 0.001) was refit on the training databases' `diff_cmp` traces.
  - States for all 10,629 traces with a verdict, identity 100%. After other-reading pairs are dropped:
    7,213 training traces (40 databases) and 2,419 held-out traces (26 databases, 450 right/wrong
    comparisons).
  - Held-out within-pair AUROC: probe 0.704 [0.644, 0.768] vs baseline 0.587 [0.538, 0.652].
    Difference +0.118 [+0.052, +0.176]. All three conditions of the gate hold.
  - Spider2-like sources (complex + h1 + h2, 203 comparisons): 0.734 vs 0.596. That gain is larger
    than in Stage A (0.695 vs 0.653).
  - By source (probe vs baseline): BIRD-Platinum 0.60 vs 0.50 (139), complex 0.66 vs 0.54 (122),
    Claude h1 0.81 vs 0.72 (43), h2 0.87 vs 0.63 (38), v3 0.70 vs 0.66 (47), the first Claude batch
    (inside the BIRD file) 0.95 vs 0.80 (40), BEAVER 0.62 vs 0.52 (21).
  - Pooled AUROC 0.804 (baseline 0.719); Brier 0.131 (0.148).
  - Report: `stageB_dc.heldout.json`, probe `stageB_dc.probe.npz` (fixed for step 3).
- **Stage B step 3: the probe failed as a soft vote on the Spider2 design half (Nov 14, one
  evaluation).**
  - Close-call pools: 48.7, against 50.7 for the deployed judge (−2.0, 95% interval [−7.7, +3.9];
    15 pools up, 28 down) and 53.3 for rule F. The bar was 56.3.
  - Easy pools: 36.0 against 37.5. At most 1 could be lost.
  - Checks: states for all 3,211 calls with a verdict, identity 100%. With hard votes in place of
    the probe's, the same pipeline reproduces the deployed judge exactly.
  - As pre-registered, the line stops here. The test half and BigQuery are not run, so the test
    half is still unused for the probe.
  - *Exploratory, after the result.* On Spider2 traces the probe tells right from wrong traces of
    the same ordered pair less well than on practice traces:
    - within-pair AUROC 0.60 [0.51, 0.69] (97 ordered pairs, 30 questions), against 0.70 on
      held-out practice traces;
    - on close-call pools, 0.58 [0.48, 0.68];
    - shorter reasoning scores 0.52.
  - Across pairs its confidence does differ: 0.77 on average for right traces, 0.50 for wrong ones.
  - *Likely reason (not tested).* As a soft vote, the probe also weakens most right votes, from 1 to
    about 0.77, by amounts that vary from pair to pair. On these pools that cost more than the wrong
    votes it turned around gained.

## 7. The HF forward-pass issue (Nov 13)

- **The failure.** The hidden-state extraction's identity check failed: its letter readout matched
  the stored verdict on 57/100 and 53/100. A later diagnostic on the same node type returned
  letter-logit gaps of 0.0, NaN and 755.67, and final-norm states of 0. That is corrupted computation,
  not a modeling error.
- **The inputs are correct.** The served judge (vLLM, AWQ), given the same token ids, gets 24/24.
- **What it is not** (each measured):
  - *The fused MoE kernel.* One full-size MoE block on an L40S gave the same output under `grouped_mm`
    and `eager`, finite and repeatable. The full model was also correct under both (next point).
  - *GPU-to-GPU copies in general.* 0 of 300–600 direct copies differed from copies staged through the
    CPU, on A6000 and on two L40S nodes. That holds with and without expandable segments, and with the
    memory pool growing and shrinking between copies. These checks ran on other GPUs than the broken
    jobs.
  - *CPU offload.* The placement budget (79 GiB) holds the 66 GiB of weights on the two GPUs, and no
    offload warning appears.
  - *`logits_to_keep` or the hooks.* The broken run was broken in every variant.
- **What it goes with: the allocation, not the input or the setting.** All 6 bf16 two-GPU forwards ran
  on 2× L40S, and 3 were broken.
  - The same 1,016-token row was correct in two runs and broken in a third. One node gave a correct run
    and, an hour later, a broken one.
  - With `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`, 3 of 5 runs broke. The one run without it
    was correct, so the setting does not explain the failures.
  - The correct runs were fully correct under both expert kernels: identity 6/6 and 24/24, every layer
    finite, repeats bit-identical, logit gaps of about ±18.
  - One-GPU runs (vLLM, the single MoE block) were never wrong.
- **Leading suspect: a particular GPU or GPU pair in some allocations.** The broken outputs look like a
  hidden state that arrived wrong where it crosses from one GPU to the other. The copy checks passed,
  but they ran on other GPUs.
- **Guards applied.**
  - Every HF job now starts with `gpu_preflight.py`, before the 70GB model loads. It checks each GPU's
    matrix products and each GPU pair's copies against the CPU, and logs the topology.
  - Each job then runs its forward check, so a bad allocation stops within minutes.
  - The job scripts also no longer set expandable segments, which is harmless either way.
- **Since the relaunch (Nov 13 afternoon).**
  - Stage A worker 0 ran on 2× L40S, the setup that failed this morning (53/100 and 57/100). It passed
    the preflight and got identity 200/200 on its first shard.
  - C1 on 4× A6000 passed the preflight and the forward check, and trained 10 healthy steps. It then
    died with `CUDA error: unspecified launch failure` (error 719, a kernel fault). It resumes from its
    step-10 checkpoint on another node.
  - A kernel that reads memory it should not would explain both the silent garbage and this crash. One
    crash does not separate that from a faulty GPU, and the cluster did not drain the node.
- **The preflight caught a broken allocation (Nov 14).** On `babel-q5-32` (8× L40S), a Stage B
  extraction job's copy from GPU 0 to GPU 1 arrived as all zeros: "zero share 1.000". The job stopped
  before the model loaded. This is the failure the suspect predicts: a hidden state crossing from one
  GPU to the other arrives wrong. Later jobs exclude that node. The resubmitted job and the other
  worker passed the preflight on other nodes, with identity 100% on every shard so far.
- **The forward check caught a node the preflight passed (Nov 14).** On `babel-o5-20` (4× L40S), two
  jobs failed it 5 minutes apart: C2-vec, then C2-both.
  - Both had passed the preflight: every product and copy correct.
  - The forward check then found letter mass 0.000 on some rows, and the labelled letter on only 5 of
    8 rows.
  - Each job stopped before training, about 5 minutes in. The same arms passed both checks on other
    nodes.
  - So a node can be faulty without failing the preflight's copy test. The forward check is the guard
    that matters. Jobs now exclude `babel-o5-20` as well.
- **The §4 trainings show no sign of it.**
  - v4, v4-e1 and v5c trained on 4× A6000. v6 trained on 6000 Ada and L40S, then A6000.
  - Their logs show steady learning: v4's loss went from 1.16 to 0.05 over 2 epochs, and its training
    pick accuracy from 0.68 to 0.99. v6 matched v4 at the same epoch.
  - The DPO runs also learned: v2a on 6000 Ada (0.65 → 0.08) and v3c on L40S (0.22 → 0.05). No
    training log has a NaN or a divergence.
  - A broken forward gives a flat log 2 or NaN. The first-step loss of 1.16 at 68% accuracy fits a
    confident judge that is sometimes wrong.
  - Splitting the model over 4 GPUs also leaves far more memory free than the 2-GPU runs that broke.

## 8. Two-loss arms (Nov 13–14)

Classification is the loss on the pick. Generation is next-token loss on the judge's own right
reasoning. Vector is a contrastive head on the hidden state at `</think>`, scoring the right reasoning
above the wrong one. Formulas: [judge_training_methods.md](judge_training_methods.md) §3. All arms use
the v4 data, holdout and recipe on 4 GPUs, without expandable segments.

| arm | pick (classification) | reasoning loss | epochs | question |
|---|---|---|---|---|
| C0 = v4 | letter, thinking off | none | 2 | baseline (already trained; healthy log, §7) |
| C1 | letter, thinking off | generation, weight 0.25 | 1 (vs v4-e1) | Does a generation loss help a classification judge? |
| C2-0 | letter read after the judge's own reasoning (right and wrong sample) | none | 2 | Does reading the reasoning help? |
| C2-gen | as C2-0 | generation, weight 0.25 | 2 | next-token reasoning loss |
| C2-vec | as C2-0 | vector, weight 1 | 2 | vector reasoning loss |
| C2-both | as C2-0 | generation 0.25 + vector 1 | 2 | both |
| A | none (model frozen) | vector only: probe on frozen states | — | Is the signal already there? |

- **Checks on every run:**
  - before training: forward check (states finite and non-zero, letter mass, repeat, the judge's own
    letter back);
  - during training: stop on non-finite or all-zero states, and on a NaN or exploding loss;
  - before evaluation: merge parity.
  - The new stages passed a smoke test on a tiny random model of the same architecture. The vector
    loss started at log 2, and the head was saved and restored on resume (within 0.2%).
- **Ablations,** only if a core arm beats its baseline: a bounded order-consistency term, a
  noise-robust pick loss.
- **Baseline for the C2 arms** (measured Nov 13, `c2_scores.py` + `c2_eval.py`). The untrained judge
  read the letter after its own stored reasoning on the held-out practice traces: 2,449 traces after
  other-reading pairs are dropped, 466 right/wrong comparisons in mixed ordered pairs.
  - Keep 1.000, overrule 0.000. It always echoes the reasoning, which also confirms the forward pass
    on every one of the 2,843 traces.
  - Pair accuracy 0.752 over 614 ordered pairs (mean P(correct) over the samples).
  - Within-pair AUROC of its confidence in the trace's own verdict: 0.448 [0.38, 0.51]. If anything,
    it is more confident in wrong reasoning.
  - Within-pair AUROC of shorter reasoning: 0.586 [0.52, 0.65], the same as the earlier 0.584.
  - So a C2 arm must overrule wrong reasoning to pick better than the base. To clear the bar of the
    pre-registered probe, it needs within-pair AUROC ≥ 0.65 (and ≥ baseline + 0.05).
- **C1 result (Nov 14).** C1 adds the generation loss to the letter-only judge (1 epoch). It is
  compared with v4-e1, the same recipe without the generation loss:
  - Spider2 round-robin: 290 / 540 against 287. The thinking judge gets 296, and two identical runs
    differ by about 23.
  - BigQuery: 28 / 105 against 28. The thinking judge gets 26.
  - Held-out practice pairs where the untuned judge is mixed: BIRD 79.6% against 68.5% (54 pairs);
    complex 51.7% against 51.7% (58 pairs).
  - So the generation loss helped on held-out BIRD-like pairs, but not on Spider2 or BigQuery. This is
    the same gap between practice data and the benchmark as before.
- **C2 results (Nov 14): no arm reads the reasoning usefully.** Scored on the same held-out traces as
  the baseline above (2,449 after other-reading pairs are dropped; 614 ordered pairs; 466 right/wrong
  comparisons, 213 of them from the Spider2-like sources):

  | | keep | overrule | pair accuracy | within-pair AUROC: pick | vector head | Spider2-like (pick) |
  |---|---|---|---|---|---|---|
  | untrained judge | 1.000 | 0.000 | 0.752 | 0.448 [0.38, 0.51] | — | 0.460 |
  | C2-0 | 0.329 | 0.661 | 0.430 | 0.592 [0.517, 0.656] | — | 0.643 |
  | C2-gen | 0.461 | 0.487 | 0.529 | 0.592 [0.509, 0.679] | — | 0.613 |
  | C2-both | 0.382 | 0.566 | 0.505 | 0.597 [0.548, 0.640] | 0.603 [0.545, 0.655] | 0.629 (head 0.606) |
  | C2-vec | 0.362 | 0.576 | 0.482 | 0.632 [0.550, 0.710] | **0.663** [0.608, 0.717] | 0.660 (head 0.704) |
  | shorter reasoning | | | | 0.586 [0.524, 0.648] | | 0.573 |
  | frozen probe (Stage A) | | | | 0.710 [0.623, 0.799] | | 0.695 |

  - C2-0, C2-gen and C2-both sit at the level of preferring shorter reasoning (0.59–0.60).
  - C2-vec's vector head is the best C2 score: 0.663, and 0.704 on the Spider2-like sources.
    - It clears 0.65, but it is only 0.03 above Stage A's length/hedge baseline on the same traces
      (0.631). The bar asks for 0.05.
    - It is below the frozen probe overall (0.710). On the Spider2-like sources the two are about
      equal (0.704 vs 0.695).
    - So training the model with the contrastive loss did not beat a probe on the frozen model.
  - As pickers all four are near chance: pair accuracy 0.43–0.53, against 0.75 for the untrained
    judge. C2-0 mostly picks against the reasoning it reads, right or wrong.
  - The pre-registration gives a trained head a Spider2 test only if Stage B passes (§6). It did not,
    and the probe, the stronger checker, made Spider2 selection worse. So the C2 line stops here.
  - Every adapter's forward pass is healthy: on the same GPUs, the base model reproduced the judge
    exactly.
  - *Likely reason (not tested).* Each training question appears with both its right and its wrong
    reasoning, and both rows have the same target letter. So the pick can be learned from the question
    alone, without reading the reasoning. Training accuracy reached about 0.65, while on held-out
    questions it is about chance.
  - The vector loss does compare right against wrong reasoning for the same question. Over its last
    training steps it got 64–78% of those comparisons right, but on held-out questions its head scores
    only 0.60.
  - Letter mass at the pick: median 0.43 for C2-0, 0.83 for C2-vec, 0.89 for C2-gen, 0.96 for C2-both.
    The generation loss keeps the output near the base. These scores compare A with B, so they are unaffected, but a
    served judge would need its letters read directly.

## 9. Where the judge still loses, and where training could help (Nov 14)

Offline, from the deployed judge's 4 samples per ordered pair (`diff_cmp`, both halves and BigQuery)
and every stored judge's pools. Scripts and outputs: scratchpad `sel/anatomy/` (`judge_anatomy.py`,
`other_judges.py`, `make_packets.py`, `readings_*.json`).

- **Not noise, order or voting.** Expected correct picks on mixed pools, deployed vs counterfactuals:

  | | pools | deployed | presentation order removed | always its majority answer | + comparisons wrong in all 8 samples fixed |
  |---|---|---|---|---|---|
  | design | 108 | 88.2 | 88.4 | 89.0 | 92.0 |
  | test | 109 | 88.4 | 88.4 | 88.0 | 92.0 |
  | BigQuery | 37 | 22.7 | 22.9 | 24.0 | 27.0 |

  - Unweighted instead of lane-weighted votes: within ±0.8 per stratum. BigQuery comparisons cut to 50
    rows: P(right) 0.71 vs 0.69 for full ones.
  - So the loss comes from comparisons where the judge's majority answer is wrong: 29 on the design
    half (16 questions), 24 on the test half (15 questions), 22 on BigQuery (13 questions).
  - Pools with one correct lane hold 64% (design), 77% (test) and 47% (BigQuery) of the loss.
- **These comparisons are hard for every judge we ran.** Mean P(right) on the 53 Spider2 ones: the
  thinking judges (old prompt, rerun, v1, v2a, v3c) 0.20–0.25; untuned no-think 0.31; JEV 0.34; v4 / v5c
  / v6 0.41–0.45.
  - Except Qwen3.8-27B with `diff_cmp` (Nov 15, §5): 0.60 on the design half and 0.51 on the test half,
    majority right on 28 of the 53; BigQuery 0.47, 10 of 22. A third to a half of its calls on these
    truncate. On the other right-vs-wrong comparisons it answers as well as the 35B or better (0.92–0.95
    vs 0.88–0.93), but loses a few to truncation.
- **What training changed on Spider2, per comparison** (mean P(right) over 455 right-vs-wrong pairs):
  reasoning training v1–v3c 0.78–0.79 vs 0.79–0.80 untuned thinking; letter-only v4–v6 0.77–0.78 vs
  0.73 untuned no-think. The `diff_cmp` prompt: 0.79 → 0.84.
- **The hard practice pairs are largely label noise.** In the sources with a label check, "another fair
  reading" is 41% of the pairs the judge leans wrong on (70 of 172) and 58% of those it always gets
  wrong (44 of 76), against 11% of the pairs it gets right. The check catches about half of doubtful
  labels, and BIRD-Platinum, the largest source, was never checked. So "learn from your mistakes" data
  was about half examples where the judge's answer was defensible.
- **Reading the 29 design-half comparisons** (one reader per packet, gold in view; the test half and
  BigQuery stay unread):

  | cause | comparisons | picks if fixed (sum of single-comparison gains) |
  |---|---|---|
  | misread with the deciding information in its inputs | 12 | 4.8 |
  | held a hard-coded value or SQL style against the right answer | 7 | 3.6 |
  | question honestly allows the other reading, or a label artifact | 4 | 2.3 |
  | same values, different form (a column or label format the gold wants) | 3 | 2.1 |
  | needs data the judge cannot see | 2 | 0.5 |
  | held extra detail against the right answer | 1 | 0.6 |

  - By fix: better reasoning 20 (8.9 picks), a fixed rule 4 (3.0), nothing 3 (1.4), more information
    2 (0.5). 23 of 29 need only general skills; 17 are decidable from the inputs, 10 partly.
  - The recurring errors: judging how the SQL looks instead of what it returns (penalizing hard-coded
    values, preferring "careful" or "standard" SQL), and not checking extra, missing or absurd rows
    against the question (7 extra countries, dropped seasons, an all-zero column, two metrics equal in
    every row). The deployed rules already state most of these; the judge does not apply them.
  - Hard-coding is more common on Spider2: the judge's reason cites it in 13% of right and 20% of
    wrong Spider2 verdicts, against 4% and 11% on the practice pairs.
  - Tooling issues found: the comparison's absolute tolerance (0.01) hides differences between small
    fractions; a comparison keyed on a column that itself differs hides the deciding rows; an 8-row
    preview can hide the right answer's content.
  - Caveat: decidability was judged with the gold in view. The Nov 12 blind reading (a much stronger
    model, no gold) recovered only about +5 design contested pools, so the reachable part is smaller.
- **Reading.** The errors left are mostly general reasoning habits that training could fix in principle,
  but the practice data neither held them often nor labeled them cleanly. Ceiling if every
  better-reasoning comparison were fixed: about +9 picks per half *(estimate, optimistic)*.

## 10. All 204 BigQuery questions (Nov 17)

Rohini's `bigquery_passk_nov2026_17` (branch rohini-platforms): the agent with 4 temperature-0.7 lanes
over all 204 BigQuery questions, where the set used so far has only the 107 questions greedy got wrong.
The analysis plan was written before any judge call (`results/bq17/PLAN.md`). Judges, prompts and
settings are those of §5; the thinking judges have 4 samples per ordered pair.

- **Pools.** 64 all correct, 75 none correct, 40 close calls (1–2 of 4 lanes right), 25 easy (3 of 4).
  The 65 mixed pools hold 506 ordered pairs of distinct results, 310 of them right vs wrong. Candidates
  and results come from the traces; nothing is re-run on BigQuery. The comparison fault described in §5
  was fixed before scoring, and the calls already made on the 126 affected pairs were made again.
- **Scores.** All 204 = the 64 all-correct pools + the mixed pools. Intervals are paired question
  bootstraps over the 65 mixed pools.

  | | all 204 | mixed (65) | vs deployed 35B, mixed | vs majority vote, mixed |
  |---|---|---|---|---|
  | pass@1 / majority vote / pass@4 | 98.0 / 105.2 / 129 | 34.0 / 41.2 / 65 | | |
  | Qwen3.6-35B-A3B, `diff_cmp` (deployed) | 112.3 (55.0%) | 48.3 | | +7.0 [+1.1, +13.1] |
  | Qwen3.6-35B-A3B, old prompt | 113.1 (55.4%) | 49.1 | +0.8 [−2.9, +4.3] | +7.8 [+3.0, +12.8] |
  | Qwen3.8-27B, `diff_cmp` | **115.5 (56.6%)** | 51.5 | +3.3 [−0.9, +7.8] | +10.3 [+4.7, +16.1] |
  | JEV-27B decision | 104.0 (51.0%) | 40.0 | −8.3 [−14.5, −2.0] | −1.2 [−9.5, +7.0] |
  | JEV-27B decision + comparison | 108.0 (52.9%) | 44.0 | −4.3 [−9.3, +0.4] | +2.8 [−5.0, +10.5] |

- **The 27B against the deployed 35B (the plan's primary comparison): ahead, not resolved.**
  - Mixed pools +3.3 [−0.9, +7.8], 19 up / 11 down; close calls +1.4 [−2.5, +5.7], easy +1.9
    [+0.3, +4.1]. The plan's bar for "better on this set" was an interval above 0. On the earlier
    BigQuery set (105 pools) it was +5.6 [+2.1, +9.5].
  - Each 27B sample alone scores 114–118 of 204, each 35B sample 111–114.
  - All three thinking judges beat majority vote on the mixed pools, by 7.0 to 10.3.
- **How far ahead the 27B is depends on its missing verdicts.**
  - 641 of its 2,024 calls (32%) give no verdict, all but one because they reach 8,192 tokens (35B: 21,
    1%); 31% on the earlier set. Median 5,146 tokens per call (35B 3,053).
  - On right-vs-wrong comparisons it answers 70% of calls and is right on 82.7% of those (35B: 98.5%
    and 74.7%). On the 269 comparisons both answered at least once: 80.7% vs 77.6%.
  - It misses on hard comparisons: there the 35B is right 65.7% of the time (150 comparisons),
    elsewhere 83.3% (160).
  - With its missing verdicts on right-vs-wrong comparisons all wrong or all right, it would score 99.5
    or 119.9. Simulated, with each such call decided right with probability f (20 draws): 111.6 at
    f = 0.5, 113.8 at 0.6, 115.9 at 0.7. So with room to finish it stays above the 35B if it gets more
    than about 53% of them right; the 35B gets 66% of the same comparisons right *(simulation, calls
    drawn independently)*.
  - Its losses are not where it truncates: the pools it wins have 47% of their calls without a verdict,
    the pools it loses 39%, level pools 20%.
- **Position.** The 27B is right 82% with the right answer shown first and 83% shown second, and the
  first-shown answer wins both orders in 1% of right-vs-wrong pairs (35B: 12% with `diff_cmp`, 23% with
  the old prompt).
- **`diff_cmp` gives the 35B no gain on BigQuery.**
  - The old prompt is +0.8 [−2.9, +4.3] (close calls −0.7, easy +1.5 [+0.2, +3.3]). The earlier +2.9
    (37 pools, comparisons with the fault) does not replicate.
  - It stays the default: it was adopted on the Spider2 test half with BigQuery allowed to lose up to
    1.5, and here it loses 0.8.
  - It still halves the first-position wins (12% vs 23%) and raises the per-call accuracy on
    right-vs-wrong comparisons (74.7% vs 71.9%), but neither changes which answer wins the pools.
- **JEV's decision mode stays below the 35B.** The comparison adds 4.0 here (40.0 → 44.0 on the mixed
  pools; nothing on the earlier set). JEV favours the answer shown second: right 59% when the
  right answer is shown first, 75% when it is shown second.
- **Checks.** Every arm is complete (4 × 506 calls; JEV 1 × 506), with no retries or client timeouts.
  All three judge jobs were requeued by Slurm after a clean exit and cancelled once their calls were
  checked. babel-p5-16 failed the GPU preflight and is excluded from these jobs.
- **Outputs.** `results/bq17/`: `score_final.txt` (scores, intervals, position and call statistics),
  `vs_majority_final.txt`, `extra_final.txt` (per-sample scores, bounds, per-call accuracy),
  `fcurve_final.txt` (simulation, per-pool truncation), and the scripts that make them.

## 11. Where the judge loses on BigQuery (Nov 18)

The method of §9, on the 65 mixed pools of §10: the deployed judge (35B, `diff_cmp`, 4 samples per
ordered pair) and the other judges of §10. Scripts and outputs: `results/bq17/anatomy/`.

- **Not noise, order or voting.** The deployed judge loses 16.7 of the 65 mixed pools:

  | | close calls (40) | easy (25) | mixed (65) |
  |---|---|---|---|
  | deployed | 25.4 | 22.8 | 48.3 |
  | presentation order removed | 25.6 | 22.5 | 48.1 |
  | always its majority answer | 25.0 | 21.0 | 46.0 |
  | + comparisons wrong in all 8 samples fixed | 31.0 | 21.0 | 52.0 |

  - The loss comes from 35 right-vs-wrong comparisons where its majority answer is wrong (21
    questions), plus 4 it splits evenly. All 39 fixed together: +14.0 picks.
  - Every judge finds them hard. Mean P(right) on the 35: deployed 0.17, old prompt 0.31, JEV 0.27 and
    0.33, the 27B 0.43 (majority right on 12; 40% of its calls on them give no verdict). On the other
    right-vs-wrong comparisons: 0.92, 0.84, 0.78, 0.80 and 0.89.
- **Where in the pools.** By how the 4 lanes agree (mixed pools):

  | lanes per distinct result | pools | majority vote | deployed 35B | 27B | deployed's loss |
  |---|---|---|---|---|---|
  | 1-1-1-1, one right | 14 | 3.5 | 5.8 | 8.2 | 8.2 |
  | 1-1-1-1, two right | 9 | 4.5 | 5.7 | 4.6 | 3.3 |
  | 1-1-1-1, three right | 3 | 2.2 | 2.1 | 3.0 | 0.9 |
  | 2-1-1 or 3-1, largest group right | 29 | 29.0 | 27.1 | 28.3 | 1.9 |
  | 2-1-1 or 3-1, largest group wrong | 6 | 0.0 | 3.8 | 3.4 | 2.2 |
  | 2-2, one right | 4 | 2.0 | 3.8 | 4.0 | 0.2 |

  - Half the loss is in the 14 pools where all four lanes differ and one is right: the deployed judge
    finds it in 41% of them, against 62% on Spider2 (29.2 of 47); the 27B 59%.
  - Overruling a right majority costs 1.9 picks and rescuing a wrong one gains 3.8, so skipping the
    judge when lanes agree would lose.
  - Per comparison, the deployed judge is right in 74.7% of BigQuery's right-vs-wrong calls, against
    about 84% on Spider2.
- **Reading the 39 comparisons** (four readers, gold in view, as in §9; 5 readings checked against the
  packets):

  | cause | comparisons | picks if fixed together | 27B majority right |
  |---|---|---|---|
  | question honestly allows the other reading, or a label artifact | 14 | 6.3 | 0 of 14 |
  | misread with the deciding information in its inputs | 15 | 3.9 | 7 of 15 |
  | held a hard-coded value or SQL style against the right answer | 5 | 1.2 | 5 of 5 |
  | same values, different form (a convention the gold wants) | 3 | 1.0 | 1 of 3 |
  | needs data the judge cannot see | 2 | 0.9 | 0 of 2 |

  - By fix: nothing 16 (7.0 picks), better reasoning 14 (3.7), a fixed rule 7 (1.8), more information
    2 (0.9). So about half of what is left on BigQuery is not a judge error; on the Spider2 design half
    it was 3 of 29.
  - The label problems: in 4 questions the gold files contradict the gold SQL (bq045: the SQL drops the
    station all four files keep; bq397, bq151, bq308). In ga010 the right answer passes only through a
    gold file that checks the channel name alone. In bq035 the two answers differ by 1.6 parts per
    million (two Earth radii) against a 0.01 absolute tolerance. In bq051, bq002, bq208 and bq308 the
    gold takes one of two fair readings (which flag to filter, the week's first day, stations with no
    data, the one-hour boundary), and bq055 wants an absolute difference where the wrong answers give
    the signed one.
  - The 10 comparisons a careful reader could decide from the judge's inputs alone are all ones the 27B
    gets right (bq278 ×3, ga013 ×3, bq087, bq393, ga032, bq268).
  - The recurring errors:
    - Accepting a filter the question does not state: bq278's typed list of the 50 states drops 37 of
      139 rows (Puerto Rico municipalities, Baja California) and was praised as "correctly filters to
      only US states as requested"; bq389's unexplained parameter code. The reverse also happens once
      (bq087: a filter the question implies called "unrequested").
    - Penalizing hard-coded values the results confirm (ga013, bq268, ga032). The deployed judge's
      reason cites hard-coding in 13.6% of its wrong verdicts and 2.5% of its right ones; the 27B's in
      none of its wrong ones.
    - Misreading which quantity or month the question asks for (bq393, bq018, bq424, bq079).
  - Comparison and preview problems were noted in 18 of the 39 (6 harmless): row keys written in
    different styles never line up (bq424 country names, bq055 race labels); columns with different
    names or scales are not paired, or are paired wrongly (ga010, bq055, bq079, bq151, bq278); long and
    wide layouts cannot be aligned (bq389); six significant digits hide a small gap between large
    numbers (bq035); for large results only the rows shown are compared, so rows one side drops are not
    listed (bq278); the 8-row preview cuts exactly the deciding rows (ga013). This fits `diff_cmp`
    helping on Spider2 but not on BigQuery (§10).
  - A prompt rule backfired once: a sample quoted "rows left out that belong make a result wrong" to
    pick the wrong answer in bq208, where the old prompt is right 75% of the time.
  - Order: in 10 of the 39, P(right) differs by 0.5 or more between the two presentation orders, 8 of
    them in favour of the answer shown first.
- **Reading.** On BigQuery the remaining loss splits about evenly between label problems that no judge
  should be expected to fix and reasoning errors with the answer in view, and the 27B fixes the clearest
  of the latter. Rough ceiling for any judge on this set: about 112.3 + 7.0 + 2.7 = 122 of 204
  *(estimate: every comparison that is not a label problem fixed, plus every residual error)*, against
  pass@4 129. This set has now been read, so a fix suggested by it needs another set to be tested on.
- **Scorer notes.** Our port of the Spider2 scorer tries each gold file and skips one that raises an
  error; the official evaluator stops at the first error. They differ on 1 of the 547 questions
  (bq389: one column list for gold files of 3 to 7 columns; ours also accepts its files d and e).
  Readers also found gold SQL that cannot produce its own gold files in 6 questions (bq002, bq045,
  bq151, bq308, bq397, bq424); scoring uses the files, so our numbers are unaffected.

## 12. Prompt changes for BigQuery (Nov 18)

The plan, [bq_judge_improvement_plan.md](bq_judge_improvement_plan.md), was written after the reading
of §11 and before any ablation call, gates included. It tests three cheap levers on the deployed 35B.
Outputs and the running log: `results/bq17/improve/` (`RESULTS.md`).

- **Sets and gates.**
  - Development (DEV): the 65 mixed pools of §10, whose misses were read in §11.
  - Test (TEST-BQ): the 37 mixed pools of the earlier BigQuery set. Primary: the 25 whose question was
    not read in §11. The deployed prompt was judged again in the same session, with the comparisons
    fixed.
  - Gates: on DEV, mixed pools at least +1.0, with the 116 right-vs-wrong comparisons that were not
    read at most 0.02 lower in mean P(right); then TEST-BQ unread at least 0; then Spider2 mixed at
    least −1.5.
- **Variants of `diff_cmp`** (`judge_prompts.py`), each adding one change:
  - `dc_scope`, a rule: a filter or list of allowed values must come from the question or the
    documentation. One they neither state nor imply (a typed-in list, a code the query's author picked,
    dropping rows that look unusual) is a flaw when it changes the result. A filter the question implies
    is required.
  - `dc_lit`, a last step: before answering, drop any reason about how a query is written (hard-coded
    values, typed-in lists, literal dates, style) that changes no value or row.
  - `dc_v2`: both.
- **Scores.** 4 samples per ordered pair, every arm complete, no client timeouts; intervals are paired
  question bootstraps.

  | | DEV mixed (65) | vs deployed | TEST-BQ unread (25) | vs deployed | TEST-BQ all (37) | vs deployed |
  |---|---|---|---|---|---|---|
  | deployed `diff_cmp` | 48.3 | | 17.3 | | 21.4 | |
  | `dc_scope` | 47.8 | −0.4 [−3.2, +2.5] | 19.1 | +1.8 [−0.7, +4.8] | 24.5 | +3.1 [−0.1, +6.6] |
  | `dc_lit` | 46.9 | −1.4 [−4.5, +1.4] | 18.7 | +1.4 [+0.0, +3.0] | 23.6 | +2.2 [+0.3, +4.4] |
  | `dc_v2` | 48.0 | −0.2 [−2.6, +2.5] | 20.1 | +2.7 [+0.6, +5.4] | 24.5 | +3.1 [+0.5, +6.2] |

  - No variant passes the DEV gate, whichever deployed run is the baseline, so none is proposed and
    production stays on `diff_cmp`. The Spider2 no-harm arm, started early for `dc_lit`, was cancelled
    (845 of 5,864 calls made).
  - The deployed prompt judged again on DEV, in the variants' session, scores 49.9: +1.6 [−0.9, +4.1]
    over the stored calls. Two runs of one prompt differ by about this much. Against this rerun the
    variants are −2.0, −3.0 and −1.8; against both deployed runs pooled (8 samples per ordered pair),
    −1.4, −2.3 and −1.2.
  - On TEST-BQ the gain is in close calls (unread pools: +1.7, +1.5, +2.3; easy +0.1, −0.1, +0.4).
- **The two BigQuery sets disagree.** DEV shows no gain (−1.4 to −0.2 against the stored calls, −3.0 to
  −1.8 against the rerun); TEST-BQ shows +1.4 to +2.7 on 25 pools. Per call, accuracy on right-vs-wrong comparisons falls on DEV (74.7% → 72.8–73.3%) and
  rises on TEST-BQ (69.9% → 70.6–71.8%). If anything, DEV favours the variants, since they were written
  after reading its misses.
- **What the rules do.**
  - The scope rule fixes the filter cases it was written for: on bq278 ×3, bq389 and bq087, mean
    P(right) is 0.61 (`dc_scope`) and 0.58 (`dc_v2`), against 0.27 and 0.40 in the two deployed runs;
    bq278's pool goes from 0.12 to 0.95. The largest TEST-BQ gains are of the same kind: bq066
    0.00 → 0.94 ("introduces an unsupported filter on morbidity categories that alters the
    denominator"), bq023 0.21 → 0.95.
  - It also turns the judge against exclusions the question implies. In bq199, dropping returns becomes
    "filters out transactions with negative volumes, which alters the computed averages"; in ga004,
    leaving out users with no pageviews becomes a flaw. Its four largest pool losses on DEV (bq199,
    ga004, bq227, bq327) sum to −1.8.
  - It doubles how often the judge's reason objects to a filter (DEV 66 → 130 of about 1,220
    right-vs-wrong calls; TEST-BQ 53 → 82 of about 700).
  - The last step of `dc_lit` fixes none of its targets (ga013, bq268, ga032: 0.12 → 0.10). The judge
    words the same objection as one that changes the result: "hardcodes dates and ignores the database
    … a static, unrelated result", "a hardcoded list that ignores the rules".
- **A selection effect in the per-comparison measure.** The 39 read and the 116 other comparisons were
  chosen by the stored deployed calls' own P(right), so any fresh run, even of the same prompt, scores
  the 39 higher and the 116 lower. The rerun measures it: the 39 go from 0.204 to 0.266 and the 116 from
  0.930 to 0.910 with the same prompt (a beta-binomial fit to the stored calls predicted 0.250 and
  0.915). The interim reading that every variant raises the targets and lowers the others was mostly
  this. Against the rerun, the variants score 0.224–0.262 on the 39 (no gain) and 0.888–0.902 on the
  116 (0.01–0.02 lower). The mixed-pool scores have no such selection.
- **Comparison tool v3** (`result_compare.py`, version 3 behind a switch).
  - It matches row keys across naming styles, pairs columns by their values with ×100 / ×1000 scale and
    sign, prints enough digits to show a difference, and flags long vs wide layouts.
  - 42 of the 506 DEV ordered pairs get different text (11 pools, 7 of the 22 read questions); only
    those were judged again. Mixed pools +0.1 [−0.4, +0.5].
  - The read comparisons whose text changed move by one or two samples of eight, and none crosses over:
    the judge had already seen these differences and decided them against the question.
- **Rule A** (judge a pair again when its two orders disagree or lack a verdict; offline from the stored
  samples): deployed 35B +0.1 [−1.0, +1.1] at 1.21× the calls; old prompt +0.4; the 27B +0.7
  [+0.1, +1.4] at 1.46×, mostly by asking again where it gave no verdict.
- **Reading.** None of the three cheap levers improves the 35B on BigQuery. A prompt rule moves where
  the judge draws the line more than how well it judges: the scope rule wins the typed-in filters it
  names and loses about as much on exclusions the question implies, so its net effect depends on the mix
  of cases in a set. Both BigQuery sets have now been used, for development or test, so a further prompt
  change has no unused BigQuery set to be tested on. The levers left need a decision (plan, lever 4):
  the 27B with a larger token budget, more preview rows, or a judge that sees all distinct results at
  once.

## 13. BigQuery, second round: what else the judge could see, and how it works through a pair (Nov 18)

The plan, with its gates and two amendments, was written before the calls it covers:
[bq_judge_improvement_plan.md](bq_judge_improvement_plan.md), "Round 2". Outputs and scripts:
`results/bq17/anatomy/pool_losses.py`; `results/bq17/improve/` (`fetch_r2.sh`, `score_r2.py`,
`score_16k.py`, `score_rerun.py`, `r2_movers.py`, `r2_16k_calls.py`, `RESULTS.md`).

- **Where both judges lose, question by question** (bq17's 65 mixed pools; the 35B with both runs pooled,
  8 samples per ordered pair; the 27B, 4 samples; causes from the §11 reading):

  | cause (read questions) | pools | 35B loss | 27B loss |
  |---|---|---|---|
  | question allows the other reading, or a label artifact | 8 | 6.4 | 7.6 |
  | misread with the deciding information in its inputs | 9 | 3.8 | 1.0 |
  | held a hard-coded value or SQL style against the right answer | 3 | 1.1 | 0.0 |
  | needs data the judge cannot see; a convention the gold wants | 2 | 1.9 | 2.0 |
  | not read (round 2 tests on these) | 43 | 2.5 | 2.9 |
  | all | 65 | 15.8 | 13.5 |

  - The 27B fixes most of what better reasoning can fix (misreads 3.8 → 1.0, hard-coding 1.1 → 0), and
    loses more on the label problems (7.6): it rejects, with reasons, answers that only the gold accepts.
  - What a judge could still gain is about 7 picks for the 35B and about 4 for the 27B *(estimate: every
    loss outside the label, hidden-data and convention rows)*.
  - The 27B's own misses are mostly calls without a verdict: of its 36 right-vs-wrong comparisons with a
    wrong majority or no verdict, 24 are §11's, and 6 of the other 12 lack a verdict in 6 to 8 of 8 calls.
- **What else the judge could be given** (offline, no GPU):
  - The agent's output-shape rubric: on the 21 missed comparisons that have one, it separates the right
    answer from the wrong one once (bq268, which the 27B already gets right).
  - Whether an answer was submitted or taken at the step limit: every miss is between two submitted
    answers (or two step-limit ones); where the wrong answer is a step-limit one (14 comparisons), both
    judges are right.
  - The doc: the GA360 doc (35,736 characters, bq001–bq010) defines the nested fields only after the
    8,000 characters the judge sees (`productRevenue` "multiplied by 10^6" at character 28,057), and the
    GA360 schema dump lists only top-level fields. No SQLite doc reaches 8,000 characters.
  - The schema: 61 of 204 dumps are longer than the 40,000 characters shown (up to 56,963), in 20 of the
    65 mixed pools. Both judges are weaker there (35B 0.68 vs 0.79 per pool, 27B 0.72 vs 0.83), mostly
    because §11's label problems sit there.
  - Not given: how many lanes gave each result (the judge would lean to the majority, and on BigQuery
    rescuing a wrong majority gains 3.8 picks against 1.9 for overruling a right one), and facts from the
    answer key.
- **Variants** (`judge_prompts.py`):
  - `dc_spec` (35B): first a short specification from the question and the doc alone, then `diff_cmp`'s
    steps decided against it. For misreading which quantity, period or rows the question asks for.
  - `dc_rf` (35B): both results and the comparison come before the SQL; the judge says where the results
    disagree and uses the SQL only to explain each disagreement. For holding how the SQL looks against
    a right result.
  - `dc_full` (35B): `diff_cmp` with the doc and schema uncut (up to 40,000 and 60,000 characters), so
    the judge sees what the agent saw. Its prompt differs from `diff_cmp`'s in 26 of the 68 test pools.
  - `dc_brief` (27B): `diff_cmp` plus an instruction to keep the reasoning short.
  - The 27B with `diff_cmp` and a 16,384-token reply budget instead of 8,192.
- **Sets and gate.** TEST: the 68 mixed pools whose question was not read (bq17 43, earlier set 25).
  READ: the other 34. A 35B variant needed TEST at least +2.0 with its 98.3% interval above 0, and READ
  at least −1.0. Baselines: the deployed 35B with `diff_cmp`, bq17 both runs pooled (8 samples per
  ordered pair), earlier set the Nov 18 morning session (4 samples).
- **35B results.** 4 samples per ordered pair, every arm complete; no verdict in 0.3–2.7% of calls.

  | | TEST (68) | vs deployed [98.3%] | bq17 / earlier set | READ (34) | vs deployed [98.3%] |
  |---|---|---|---|---|---|
  | deployed `diff_cmp` | 57.8 | | | 12.8 | |
  | `dc_spec` | 59.3 | +1.5 [−1.5, +4.7] | −1.1 / +2.6 | 13.7 | +0.9 [−1.5, +3.7] |
  | `dc_rf` | 58.7 | +0.9 [−3.1, +4.9] | −1.5 / +2.4 | 13.3 | +0.5 [−1.9, +3.1] |
  | `dc_full` | 59.5 | +1.7 [−1.2, +5.3] | −0.7 / +2.4 | 13.2 | +0.4 [−1.3, +2.2] |

  - No variant passes, so none is proposed, no Spider2 run follows, and production stays on `diff_cmp`.
  - The two sets disagree again: every variant loses on bq17's 43 test pools and gains on the earlier
    set's 25. On bq17's 43, two runs of `diff_cmp` itself differ by −1.3 [−2.9, −0.1]: a same-prompt
    difference whose interval leaves out zero, so the question bootstrap understates how far two runs
    differ.
  - `dc_full` has its own control: in 42 test pools its prompt is the same as `diff_cmp`'s, and there it
    scores −0.3 (bq17, 28 pools) and +0.8 (earlier set, 14 pools), which is run-to-run spread. In the 26
    where it shows more doc or schema: −0.4 and +1.6 (schema lengths read from bq17's traces for both
    sets).
  - The same pools move under every variant. On the earlier set, against the morning session, bq066
    (0.00 → 0.56, 0.89, 1.00), bq407 (0.30 → 0.72, 0.82, 0.61) and bq123 (0.50 → 1.00, 1.00, 0.75) gain
    under all three, as bq066 and bq023 did under round 1's rules; on bq17, ga004 (leaving out users
    with no pageviews is right) loses under all three (0.55 → 0.00, 0.00, 0.12).
  - GA360, `dc_full`'s own target: with the field definitions in view, bq002 rises (bq17 0.15 → 0.27,
    earlier set 0.38 → 0.50) and bq004 falls (0.92 → 0.75); bq001 and bq010 stay at 1.00.
  - The deployed prompt judged again on the earlier set (amendment 2) scores +1.6 [+0.3, +3.2] over the
    morning session on the 25 unread pools (bq066 0.00 → 0.51, bq123 0.50 → 1.00): the morning baseline
    was a low draw, and for the second time the bootstrap leaves out zero for an unchanged prompt. With
    both runs pooled on each set (8 samples per ordered pair), round 2's variants score +0.6 [−2.2, +3.2],
    −0.1 [−4.0, +3.6] and +0.7 [−1.7, +3.5] on TEST, and round 1's (§12) +0.8, +0.5 and +1.8 on the
    earlier set's 25. A few pools still move beyond both runs of the deployed prompt (bq023 0.12–0.21 vs
    0.69–0.95; bq328 0.25–0.28 vs 0.56–0.75), and losses elsewhere offset them.
- **27B results** (bq17, 506 ordered pairs per sample; against its Nov 17 calls at 8,192 tokens, which
  have no verdict in 31.7% of calls and are right in 82.7% of the answered right-vs-wrong ones):
  - `dc_brief` failed its pilot bar on samples 2 and 3 (samples 0 and 1 were slowed by preemption and
    stopped): no verdict 21.9% (the bar wanted a fall of 10 points to 21.7% or less) and 80.8% right on
    answered right-vs-wrong calls. On those two samples it picks 114.8 of 204 against 115.5 (−0.7
    [−2.8, +1.0] on the 65 mixed pools).
  - `diff_cmp` with 16,384 tokens (samples 0, 2 and 3; sample 0 ran without a preemption; sample 1,
    preempted five times, was cancelled and is left out): calls without a verdict fall from 31.7% to 7.8%, and accuracy
    on answered right-vs-wrong calls stays close (80.2% vs 82.7%). Per right-vs-wrong call, P(right)
    with a missing verdict counted 0.5 rises from 0.729 to 0.781: comparisons the 8,192 budget always
    cut off are now right 0.667 of the time, those it never cut stay at 0.87. In the read questions,
    which hold the hard comparisons, it moves only from 0.526 to 0.551.
  - Picks do not follow: 114.0 of 204 on the three samples against 115.5 (−1.6 [−4.2, +0.7] on the 65
    mixed pools), and 116.0 for sample 0 alone (+0.5 [−3.7, +4.4]). Single samples of the 8,192 run
    score 114 to 118.
  - Why: a missing verdict counts half for each side, so it leaves the larger group's head start in place,
    and truncation deferred to the majority. Where the majority is right and the 27B, once it finishes,
    decides wrong, the pool falls: bq389 0.81 → 0.15, bq424 0.75 → 0.21, bq103 0.77 → 0.33, bq002 0.64 →
    0.26, ga004 0.44 → 0.00. Where the right answer is a single lane, finishing helps: bq055 0.03 → 0.36,
    bq445 0.75 → 1.00, bq066 0.80 → 1.00. The §10 simulation put break-even at 53% of the cut calls right
    because it let each call go right or wrong on its own; the errors cluster by question instead. In
    bq424 the 27B picks the other debt indicator in 6 of its 7 answers (5 of 6 at 8,192), and in bq389
    it accepts the unexplained parameter-code filter in 4 of 9, the 35B's error of §11.
- **Reading.** Six prompt variants over two rounds change the 35B on BigQuery by no more than two runs of
  one prompt differ, once each baseline has 8 samples per ordered pair. The 27B with room to finish
  answers nearly every comparison but picks no better, because its remaining errors sit in the same hard
  questions. Neither prompt changes nor a larger token budget improves BigQuery selection measurably;
  production stays on the 35B with `diff_cmp`. What is left is mostly §11's label problems and misreads
  of hard questions, which no round has moved.
- **Method notes.** Two same-prompt reruns (bq17 43 pools: −1.3 [−2.9, −0.1]; earlier set 25 pools: +1.6
  [+0.3, +3.2]) show that a 4-sample baseline can be off by 1.5 picks on a few dozen pools and that the
  question bootstrap does not cover it; a pass bar needs a margin above the bootstrap and a baseline of
  more than one run. On preemptible GPUs, calls in flight at a preemption are drawn again; the start log
  (`calls_<variant>.starts.jsonl`) counts them (27B 16,384 sample 2: 79 of 506; sample 1, cancelled:
  at least 251 of 384).

## 14. Round 3 and the production rule (Nov 18–19)

**Round 3** (35B only; plan, gate and full results in [bq_judge_improvement_plan.md](bq_judge_improvement_plan.md),
"Round 3"). Dataset notes from each BigQuery dataset's official documentation (`dc_facts`) and a listwise judge
(all results of a question in one call) both fail the gate on the 102 mixed BigQuery pools: +2.2 [−2.6, +7.2] and
+0.8 [−4.5, +6.3] (97.5%). The notes fix the questions whose deciding fact is documented (bq356, bq051) and lose
about as much elsewhere. Asking every pair twice and applying the superset rule is the only change that is
positive on both BigQuery sets and on SQLite.

**Adopted on Nov 19** (the user's decision): `select_answer.py` now judges every ordered pair twice (`--votes 2`)
and then applies the superset rule (a result that holds every column of the pick's result with the same rows
replaces it; the widest such result). `--votes 1 --no-superset-rule` gives the earlier production.
`selection_eval.py score` scores the new production as `NAME@U@V2`, exactly (each ordered pair's vote is the mean
of 2 of its samples, drawn without replacement); it gives the same totals as round 3's Monte Carlo scripts.
The calls of one question now go out at once (`--workers`, default 16). Checks: with a fake judge, the call count
(two per ordered pair), the superset upgrade, `--votes 1 --no-superset-rule` reproducing the old picks, and 12 calls
in 0.4 s instead of 3.7 s with the same pick; with the served 35B (`slurm/prod_smoke.slurm`, 3 SQLite questions),
12, 12 and 4 calls, none failed, all 3 picks right (majority vote got 2). Across
the eval sets, 398 pairs of results stand in the superset relation; the contained result is right and the wider one
wrong in none of them, and the reverse in 36.

From the stored samples (old = one call per ordered pair, new = ask twice + superset rule, same samples; 95%
paired question bootstrap on the mixed pools; `results/prod_nov19/score_prod.py`):

| set | old | new | new − old |
|---|---|---|---|
| BigQuery bq17 (of 204) | 113.2 (55.5%) | 114.7 (56.2%) | +1.5 [+0.1, +3.0] |
| bq17, strict corrected labels | 114.9 (56.3%) | 116.7 (57.2%) | +1.7 [+0.4, +3.1] |
| bq17, lenient corrected labels | 118.8 (58.3%) | 120.5 (59.1%) | +1.6 [+0.3, +3.2] |
| BigQuery earlier set (of 105) | 27.7 (26.4%) | 28.2 (26.8%) | +0.4 [−0.7, +1.5] |
| SQLite q36rg (of 135) | 85.6 (63.4%) | 87.2 (64.6%) | +1.6 [−0.1, +3.8] |
| SQLite q36e | 82.8 (61.4%) | 83.3 (61.7%) | +0.5 [−1.2, +2.6] |
| SQLite q36x | 82.8 (61.3%) | 85.5 (63.3%) | +2.7 [+0.4, +5.7] |

The two BigQuery sets and q36rg (part of the 540 SQLite pools) chose the rule; q36e and q36x did not.

**Check on fresh samples (written before any call, Nov 19).** The rule is measured again on new samples: 4 fresh
`diff_cmp` samples per ordered pair (35B, thinking, 8,192 tokens, the deployed comparison caches) on bq17 (506
ordered pairs), the earlier BigQuery set (280), q36rg (294), q36e (270) and q36x (322): 6,688 calls on preemptible
GPUs (`judge_variants.slurm`, three sessions). Measure: old and new production on the same fresh samples, per set,
with the 95% paired question bootstrap; bq17 also under the audit's strict and lenient labels. Production stays
adopted either way. The check fails if the new rule is below the old one summed over the five sets' mixed pools;
the decision then goes back to the user. Calls redrawn after a preemption are counted from the starts logs.

**bf16 judge test (written before any call, Nov 19).** The same model at full precision instead of AWQ 4-bit:
`Qwen/Qwen3.6-35B-A3B` in bf16, one vLLM engine over two GPUs (`judge_variants.slurm` with `MODEL` and `TP=2`; a GPU
preflight and an obvious-pair smoke test before any call). Everything else as in the fresh AWQ check above: the same
vLLM build and flags, `diff_cmp`, thinking, temperature 0.6, 8,192 tokens, the same comparison caches, 4 samples per
ordered pair on the same five sets. Measure: the production rule (`@U@V2`) on the same pools, bf16 minus the fresh
AWQ samples. Pass: on both BigQuery sets' mixed pools (102) at least +2.0 with the 97.5% paired question bootstrap
above zero, and on the SQLite run sets' mixed pools (146) not below −1.5. One-call numbers and call health (no
verdict, truncation, tokens) are reported alongside. If it passes, a bf16 judge needs two 48 GB GPUs (or one
80 GB GPU) per server instead of one, with the same active parameters per token.

## 15. Where things are

- **Data pipeline.** `build_bird_dataset.py`, `build_beaver_dataset.py`, `beaver_to_sqlite.py`,
  `beaver_gold_mysql.py`, `check_db_overlap.py`, `profile_traps.py`, `sql_mutations.py`,
  `generate_trap_items.py`, `validate_trap_items.py`, `stress_test_items.py`, `review_packets.py`,
  `question_waves.py`, `question_briefs/`, `sample_judge_verdicts.py`, `check_pair_labels.py`.
- **Training.** `make_judge_sft_dpo.py`, `train_judge_lora.py` (stages sft, dpo, choice, choice_mt,
  choice_reason), `merge_judge_adapter.py`, `judge_gate.py`.
- **Judging and evaluation.** `judge_pools.py` and `bq_judge_pools.py` (`--no-judge` builds the groups
  only), `judge_pairs.py`, `rejudge_pools.py`, `selection_eval.py` (exp1; rules @U / @T; soft votes @S; two votes per pair @V2),
  `runset_evalset.py` (eval set for new Spider2 run sets, Nov 18), `judge_prompts.py`,
  `result_compare.py`, `build_compare_cache.py`, `analyze_pools.py`, `compare_judges.py`.
- **Trace verification.** `extract_judge_states.py`, `probe_fit.py` (`--frozen` for Stage B),
  `vstar_scores.py`, `vstar_eval.py`, `practice_dc.py`, `calls_to_records.py`, `probe_votes.py`.
- **Forward-pass checks.** `diag_hf_forward*.py`, `diag_moe_experts.py`, `diag_p2p.py`,
  `smoke_two_loss.py`.
- **Cluster jobs.** `nl2sql-v2/slurm/`.
- **Full BigQuery rerun.** `results/bq17/` (plan, scores, scripts); its error analysis in `anatomy/`,
  the Nov 18 ablations in `improve/` (round 2: `score_r2.py`, `score_16k.py`, `score_rerun.py`,
  `r2_movers.py`, `r2_16k_calls.py`, `fetch_r2.sh`); round 3 in `round3/` (`score_r3.py`, `facts/`).
- **Production rule check (Nov 19).** `results/prod_nov19/` (`score_prod.py`; fresh calls in `fetched/`).
- **Results on Babel.** `/data/user_data/dpalagan/{judge-data,nl2sql-sel}/results/`.
