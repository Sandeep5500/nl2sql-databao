# Judge and answer selection: findings (Nov 2026)

Details and numbers: [judge_results.md](judge_results.md). Spider2 scores are correct picks out of 540
(135 questions × 4 saved run sets). BigQuery scores are out of 105.

1. **The judge is close to its ceiling with the inputs it sees.**
   - The untrained thinking judge scores 296 / 540 and 26 / 105, against 261 for majority vote.
   - Its misses are "can't tell" cases: in pools missed by both runs, the right answer still wins 45%
     of its pairwise judgments.
   - Remaining headroom for any judge is about 10–15 of 540 *(estimate)*, less than the 23-pick gap
     between two identical runs.

2. **A prompt change gave the first win that passed a pre-registered test.** The `diff_cmp` prompt
   asks the judge to list the SQL differences and check each against a computed comparison of the
   two full results.
   - Held-out test half: +7.2 close-call pools, 97.5% CI [+1.9, +13.0], with no easy-pool loss and
     BigQuery +2.9.
   - Whole-benchmark expected accuracy: 293.4 → 305.6 (about +3 questions per run set).
   - It is now the default in `select_answer.py`.

3. **Fine-tuning has not beaten the untrained thinking judge (v1–v6, Nov 1–11).**
   - Training on reasoning text (SFT / DPO) learned the practice distribution but did not transfer to
     Spider2: 287–290 vs 296.
   - Training only the A/B letter (v4) transferred best: per-pair 73% → 79% on Spider2. But it only
     tied the thinking judge: 287 vs 296, and BigQuery 30 vs 26.
   - Adding 128, then 342 more pairs changed nothing.
   - **Caveat:** the training forward pass is under investigation (point 7).

4. **The practice data is the main limit for training.**
   - The questions are simpler than Spider2's or come from other databases.
   - Only 16–35% of questions give a right/wrong pair.
   - 7–27% of "wrong" labels are another fair reading.
   - Only 419 practice comparisons have reasoning samples that disagree.
   - What didn't work as data sources:
     - Self-written questions (Qwen) gave unreliable keys.
     - BEAVER questions are ambiguous.
     - Claude-written questions are cleaner but often too easy.

5. **Cheap gains remain at selection time.** These are exploratory, found on the design half, and
   need their own pre-registered test.
   - Re-sampling only the pairs whose two presentation orders disagree: +1.8 to +2.2 close-call pools
     per half, at about 1.5× the judge calls.
   - Letting v4 settle those pairs: +1.5 to +3.0.
   - The extra-columns rule (U) has never lowered a pool, but missed its bar by the letter.

6. **Where the remaining room is: telling which reasoning sample got it right.**
   - A perfect checker of the judge's own reasoning samples would add +9 to +12 close-call pools per
     half.
   - Nothing cheap captures it: reasoning length and hedging score about 0.5 AUROC within a pair.
   - The old DPO judges reach 0.65 vs 0.58 for the baseline, which is within noise.
   - A pre-registered frozen probe (Stage A) is next.

7. **An infrastructure bug must be fixed before more training.**
   - The bf16 model in HF transformers sometimes returns zero or NaN activations (Nov 13). The
     served vLLM judge is fine.
   - The suspect is the default fused MoE kernel (`grouped_mm`) on L40S GPUs.
   - Every training run now starts with an identity check, so no GPU time goes to a broken forward
     pass.
   - The planned arms are C0 (letter only), C1 (letter + reasoning next-token loss), C2 (letter read
     after own reasoning) and A (probe). They launch once the fix is confirmed.

8. **Generation is still the bigger lever.** On q36rg, 41 of 135 questions have no correct answer
   among the 4 lanes, and no judge can fix those.
