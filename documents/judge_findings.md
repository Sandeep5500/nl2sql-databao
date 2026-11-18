# Judge and answer selection: findings (Nov 2026)

How the deployed judge works and why: [judge.md](judge.md). Details and numbers:
[judge_results.md](judge_results.md). Spider2 scores are correct picks out of 540
(135 questions × 4 saved run sets). BigQuery scores are out of 105 (the questions greedy got wrong),
except in points 12–15 (all 204 questions).

1. **The judge is close to its ceiling with the inputs it sees.**
   - The untrained thinking judge scores 296 / 540 and 26 / 105, against 261 for majority vote.
   - Its misses are "can't tell" cases: in pools missed by both runs, the right answer still wins 45%
     of its pairwise judgments.
   - Remaining headroom for any judge is about 10–15 of 540 *(estimate)*, less than the 23-pick gap
     between two identical runs.
   - That estimate was too low (point 10): a stronger base model gains +11.8 with the same inputs.

2. **A prompt change gave the first win that passed a pre-registered test.** The `diff_cmp` prompt
   asks the judge to list the SQL differences and check each against a computed comparison of the
   two full results.
   - Held-out test half: +7.2 close-call pools, 97.5% CI [+1.9, +13.0], with no easy-pool loss and
     BigQuery +2.9.
   - Whole-benchmark expected accuracy: 293.4 → 305.6 (about +3 questions per run set).
   - It is now the default in `select_answer.py`.
   - On all 204 BigQuery questions (point 12) it gives the 35B no gain: the old prompt is +0.8
     [−2.9, +4.3].

3. **Fine-tuning has not beaten the untrained thinking judge (v1–v6, Nov 1–11).**
   - Training on reasoning text (SFT / DPO) learned the practice distribution but did not transfer to
     Spider2: 287–290 vs 296.
   - Training only the A/B letter (v4) transferred best: per-pair 73% → 79% on Spider2. But it only
     tied the thinking judge: 287 vs 296, and BigQuery 30 vs 26.
   - Adding 128, then 342 more pairs changed nothing.
   - The forward-pass bug of point 7 shows no sign in these trainings: their logs show steady learning.

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
   - **A frozen probe on the judge's hidden states passed its pre-registered gate (Nov 13), only
     just.** On held-out practice databases it reaches 0.71 within-pair AUROC vs 0.63 for the
     length/hedge baseline (+0.08, interval [+0.004, +0.156]). The gain is smaller on the
     Spider2-like sources (0.70 vs 0.65). The judge's own confidence scores 0.45: the signal is in its
     hidden states, not in the letter it writes.
   - **On `diff_cmp` reasoning it passed again, more clearly (Nov 14).** Refit with the same frozen
     settings: 0.704 vs 0.587 (+0.118, interval [+0.052, +0.176]); 0.734 vs 0.596 on the Spider2-like
     sources.
   - **On Spider2 it did not help selection, so the probe line stops (Nov 14).** As a soft vote in
     the round-robin on the design half, it scored 48.7 close-call pools against 50.7 for the deployed
     judge, and it lost 1.5 easy pools. On Spider2 traces it tells right from wrong reasoning less
     well than on practice traces: 0.60 vs 0.70 within-pair AUROC (exploratory).

7. **A forward-pass bug blocked the probe; every job is now guarded against it.**
   - The bf16 model in HF transformers, split over 2 L40S GPUs, returned zero, NaN or garbage
     activations in 3 of 6 jobs (Nov 13). The same input on the same node was fine in other jobs. The
     served vLLM judge is fine.
   - Ruled out by test: the fused MoE kernel, CPU offload, the input, and the allocator setting.
   - Leading suspect: a particular GPU or GPU pair in some allocations.
   - Every job now tests its GPUs before loading the model, checks its forward pass, and stops on bad
     activations during training. No GPU time goes to a broken allocation.
   - The test caught one such allocation directly (Nov 14, an 8× L40S node): a copy from one GPU to the
     other arrived as all zeros. This supports the suspect: broken GPU-to-GPU copies on some nodes. Jobs
     now exclude that node.
   - A second node passed that test but failed the forward check in two jobs (Nov 14). Each stopped
     within minutes, before training. Jobs exclude both nodes.
   - C1 result (Nov 14): adding the generation loss to the letter-only judge changed Spider2 from 287
     to 290 and left BigQuery at 28, within noise, though held-out BIRD pairs improved (68.5% → 79.6%).
   - C2 results (Nov 14): reading the pick after the judge's own reasoning did not work, with or
     without the reasoning losses.
     - C2-0, C2-gen and C2-both reach only 0.59–0.60 within-pair AUROC on held-out traces. That is no
       better than preferring shorter reasoning, and below the frozen probe's 0.71.
     - Their held-out pair accuracy is near chance (0.43–0.53; untrained: 0.75).
     - The likely reason: the pick can be learned from the question alone, since each question is
       trained with the same target after both right and wrong reasoning.
     - C2-vec's vector head did best: 0.66, and 0.70 on the Spider2-like sources. That is still below
       the frozen probe (0.71), so training the model did not beat a probe on the frozen one. With the
       probe failing on Spider2, the C2 line stops.
   - Launched (Nov 13), every arm keeping the classification loss on the pick:
     - C1: plus a generation (next-token) loss on the judge's own right reasoning.
     - C2: the pick read after the reasoning, with no reasoning loss (C2-0), generation (C2-gen),
       vector (C2-vec) or both (C2-both).
     - A: a frozen probe (done; point 6).
     - v4 serves as C0.

8. **Why fine-tuning has not worked, and where it still could (Nov 14 analysis).**
   - The deployed judge's remaining loss is not noise, presentation order or voting: removing all three
     changes at most 1 pick per half. It comes from 53 Spider2 comparisons (31 questions) where its
     majority answer is wrong, and every judge we ran, tuned or not, mostly gets those wrong too. The
     exception came later: Qwen3.8-27B gets about half of them right (point 10).
   - Training moved Spider2 per-comparison accuracy little: reasoning training 0.78–0.79 vs 0.79–0.80
     untuned; letter-only 0.77–0.78 vs 0.73 untuned no-think. The prompt change gave 0.79 → 0.84.
   - The practice data's hard pairs are about half label noise: "another fair reading" is 41–58% of the
     pairs the judge gets wrong, against 11% of those it gets right.
   - Reading the 29 design-half comparisons: 20 are general reasoning errors with the deciding
     information in the inputs. The judge judges how the SQL looks (it penalizes hard-coded values) and
     does not check extra, missing or absurd rows against the question. 4 more need a fixed rule, and 5
     no judge can fix.
   - So training could help, if its data targeted these habits with clean labels. Ceiling about +9 picks
     per half *(estimate, optimistic)*.

9. **Generation is still the bigger lever.** On q36rg, 41 of 135 questions have no correct answer
   among the 4 lanes, and no judge can fix those.

10. **A stronger base model judges better with the same inputs (Nov 15).** Qwen3.8-27B, unchanged from
    the release, thinking, with `diff_cmp`, against the deployed 35B with `diff_cmp`, 4 samples each:
    - Spider2 305.6 → 317.4: mixed pools +11.8 [+1.7, +22.0], close calls +10.0 [+0.9, +19.7]. On the
      test half alone, close calls +4.3 [−3.1, +11.8]. BigQuery 27.7 → 33.3: mixed pools +5.6
      [+2.1, +9.5]. On all 204 BigQuery questions (point 12) the lead is smaller and not resolved.
    - The gain is in the deployed judge's systematic misses (point 8): its majority is right on 28 of
      the 53 (mean P(right) 0.51–0.60 against 0.18–0.19), and on 10 of BigQuery's 22. Earlier judges
      reached 0.20–0.45 on these.
    - This is with a quarter of its calls cut off at 8192 tokens and counted as missing, most of them
      on hard pairs. Where it answers, it is right as often as the 35B or more.
    - It is a dense 27B: smaller than the 35B-A3B in memory, but about 9× its compute per token, and
      Qwen3.8 has no smaller model. Whether that fits the small-model goal is open.

11. **Other model families of the same size do not judge better (Nov 16–17).** Same pools, inputs and
    `diff_cmp`, thinking on, against the deployed 35B:
    - GLM-4.7-Flash (MoE, 3B active like the 35B; 4 samples): Spider2 296.9, mixed pools −8.6
      [−16.3, −1.3]; BigQuery 27.4, mixed pools −0.3. A quarter of its calls run out of tokens before
      a verdict, mostly on hard pairs, and where it answers it is right less often.
    - Magistral-Small-2509 (24B dense, like the 27B; 1 sample): Spider2 300.0, mixed pools −5.6
      [−17.3, +5.8]; BigQuery 29.0, mixed pools +1.3. It almost always answers.
    - Both favour the answer shown first: it wins both orders in 15–18% of pairs for Magistral and
      9–21% for GLM (35B 7–12%, 27B 0–1%).
    - Every one of their samples scores below every one of the 35B's on Spider2. The 27B (point 10)
      stays the only judge clearly above the 35B, and a dense model of its size is not enough by
      itself.

12. **On all 204 BigQuery questions the judges still beat majority vote; the 27B's lead is smaller
    (Nov 17).** A fresh 4-lane run of the agent; 65 pools with both right and wrong answers; the plan
    was written before any judge call.
    - Out of 204: pass@1 98.0, majority vote 105.2, deployed 35B 112.3, 35B with the old prompt 113.1,
      27B 115.5, pass@4 129. On the mixed pools all three beat majority vote, by 7.0 to 10.3.
    - 27B against the deployed 35B: +3.3 [−0.9, +7.8], not resolved (+5.6 [+2.1, +9.5] on the earlier
      105). How far ahead it is depends on the 32% of its calls that reach 8,192 tokens without a
      verdict: with all of those wrong or all right it would score 99.5 or 119.9.
    - `diff_cmp` gives the 35B no gain here (old prompt +0.8 [−2.9, +4.3]), though it still halves the
      first-position bias. It stays the default: it was adopted on Spider2, with BigQuery allowed to
      lose up to 1.5.
    - So the 27B with `diff_cmp` remains the strongest judge measured: clearly ahead on Spider2, ahead
      but not resolved on BigQuery.

13. **On BigQuery, about half of what the judge still loses is label problems (Nov 18).** The deployed
    judge loses 16.7 of the 65 mixed pools, none of it to noise, presentation order or voting. It comes
    from 39 comparisons where its majority answer is wrong or split; fixing them all would add 14.0.
    - Half the loss is in pools where all four lanes differ and one is right. The judge finds that one
      in 41% of them, against 62% on Spider2.
    - Reading the 39 with the gold in view: 16 (7.0 picks) need no judge fix, because the question
      allows the other reading or the label is an artifact (gold files that contradict their SQL, a
      tolerance tripped by 1.6 parts per million). 21 (5.5 picks) are reasoning errors with the answer
      in view: accepting filters the question does not state, penalizing hard-coded values the results
      confirm, misreading the asked quantity. The 27B gets all 10 of the clearly decidable ones right.
    - The result comparison often fails on BigQuery outputs (keys written in different styles, columns
      not paired, long vs wide layouts; 12 of the 39), which fits `diff_cmp` giving no gain there.
    - Rough ceiling for any judge on this set: about 122 of 204 *(estimate)*, against pass@4 129.

14. **Three cheap fixes for BigQuery did not improve the judge (Nov 18).** Tested on the deployed 35B
    against gates fixed before any call:
    - Two prompt rules and both together: filters must come from the question or the documentation;
      drop objections to how a query is written. On the full BigQuery set, whose misses were read: −1.4
      to −0.2 against the stored calls, −3.0 to −1.8 against a fresh run of the deployed prompt. On the
      25 unread pools of the earlier set: +1.4 to +2.7. None passed the first gate, so production stays
      on `diff_cmp`.
    - The filter rule fixes the typed-in filters it was written for, but it also makes the judge reject
      exclusions the question implies (returns, users with no activity). It moves where the judge draws
      the line more than how well it judges. The second rule changed none of its targets: the judge
      words the same objection to hard-coded values as one that changes the result.
    - A clearer result comparison (keys across naming styles, rescaled columns, more digits): +0.1.
      Asking again on pairs whose two orders disagree: +0.1.
    - Two runs of the same prompt differ by 1.6 on these 65 pools, so gaps of 1–2 are not resolved by 4
      samples.
    - Both BigQuery sets are now used, so a further prompt change has no clean BigQuery test. The 27B
      with a larger token budget was the main lever left (tested the same afternoon, point 15).

15. **A second round of BigQuery prompts, and more room for the 27B, did not help either (Nov 18).**
    Gates fixed before any call; tested on the 68 mixed pools whose questions were not read.
    - Three 35B prompts that change how it works through a pair: a specification written from the
      question first, the results shown before the SQL, the doc and schema uncut. Against one run of
      the deployed prompt: +1.5, +0.9 and +1.7, short of the +2.0 the plan asked for. Against two runs
      pooled on both sets: +0.6, −0.1 and +0.7.
    - The deployed prompt, run again on the earlier set, scores +1.6 [+0.3, +3.2] over its first run on
      the same 25 pools. Twice now an unchanged prompt has had an interval that leaves out zero, so a
      pass bar needs a margin and a baseline of more than one run.
    - The 27B asked for short reasoning still runs out of tokens on 22% of calls and picks no better.
      Given 16,384 tokens it runs out on 8% instead of 32%, and 72% of its answers on the comparisons it
      used to cut off are right, yet it picks 114.0 of 204 against 115.5. A missing verdict counts half
      for each side, which leaves the result more lanes gave ahead; once the 27B finishes, its errors
      on the hard questions show (bq389, bq424).
    - On BigQuery, neither prompt changes nor more reasoning tokens improve selection measurably. What is
      left is mostly label problems and misreads of hard questions.
