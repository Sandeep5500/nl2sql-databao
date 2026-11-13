# Reasoning-reading judge head: pre-registration

Fixed on 2026-11-13, before any hidden state was extracted or any probe was fit. Numbers are
measured unless marked (estimate).

## Question

Can a readout of the judge's hidden states, taken after its own reasoning, tell which of the sampled
reasoning traces for the same ordered pair reached the right verdict ("trace verification")? If it
can, does using that readout as a soft vote improve selection, compared with the adopted prompt
`diff_cmp` and with free label-free rules?

This is the testable form of "train with reasoning, but read the decision from a vector".
- The A/B-letter loss (v4) is already a linear head on the last hidden state.
- A head can add something only by telling right traces from wrong ones within a comparison.

## Why trace verification (step 1, 2026-11-12/13)

Spider2 / BigQuery contested exp1 for the adopted `diff_cmp` (single-sample round-robin, as deployed):

| | design (69) | test (70) | BigQuery (28) |
|---|---|---|---|
| deployed | 50.7 | 50.9 | 15.2 |
| average of 4 samples | 52.0 | 54.0 | 16.0 |
| rule A: re-sample only order-disagreeing pairs (1.4–1.6× calls) | 52.6 | 53.1 | 16.3 |
| rule F: v4 settles order-disagreeing pairs (second model) | 53.3 | 52.4 | 18.3 |
| oracle: flip wrong traces in mixed ordered pairs | 60.1 | 63.0 | 22.8 |

Reasoning length and hedge words give no within-pair signal:
- `diff_cmp` within-pair AUROC, design / test: length 0.52 / 0.51, hedge 0.55 / 0.51.
- Base-prompt practice data, all six sources: length 0.57 [0.53, 0.61], hedge 0.56. Their pooled AUROC
  is about 0.65, but that measures how hard a pair is.

Practice training signal (base prompt, other_reading pairs dropped):
- 2,112 ordered pairs, of which 419 are mixed (the 4 samples disagree).
- By split: train databases 291 mixed, val split 52, holdout databases 76.

Source files:
- `scratchpad/headjudge/step1/{practice,spider2}_ceilings.json`.
- Recomputed independently: `verify_practice.py`, `check_review.py`.

## Data

- **Fitting and selection.** These practice verdict files (cluster
  `judge-data/results/`, md5 as copied on 2026-11-12):

  | file | md5 |
  |---|---|
  | judge_train/verdicts_train_v1.jsonl | 3f48e75e1562573b0343ffc5ee279004 |
  | judge_cplx/verdicts_cplx_v1.jsonl | fc28ee6ed7a0fdefa4cbe748513ec58a |
  | judge_cplx/verdicts_cplx_v2.jsonl | 834d0adc09640319e004c7c30a37eb5c |
  | judge_claude/verdicts_claude_v3.jsonl | cc1ec4c507baf9c3d4ce742b87a6d037 |
  | judge_claude/verdicts_claude_h1.jsonl | 80aa5ca96ab2ecb8f2d4b7a25e6eed79 |
  | judge_claude/verdicts_claude_h2.jsonl | 65a8192859a88da2b2e58ef55499fa6b |
  | judge_beaver/verdicts_beaver_p1.jsonl | 285a9823e8355d10166d786e6cbdc680 |

  Only questions on train-split databases that are not in `judge_train_v4/data_v6/holdout.json` are
  used. Pairs marked other_reading by the `pair_labels_*.jsonl` files are dropped, and truncated
  samples are dropped from fitting.
- **Held-out practice test set, scored once.** Questions on the holdout.json databases plus the val
  split. Earlier trainings excluded both.
- **Spider2 and BigQuery: evaluation only.** Nothing is fit, scaled, thresholded or selected on them.
  The fitting code refuses keys that start with `spider2:` or `bq:`.

## Stage A: screen on the stored base-prompt reasoning (Spider2 not touched)

- **Sequence.** Chat template with thinking on + the stored prompt, then
  `<think>\n` + reasoning.strip() + `\n</think>\n\n` + the reply opening.
  - The reply opening is taken from the stored answers, tabulated before extraction.
- **Model.** The bf16 Qwen/Qwen3.6-35B-A3B in HF transformers 5.5.3, with forward hooks. Every feature
  comes from this one backend.
- **Features (the exploratory set; one configuration is chosen by cross-validation).**
  - Positions: the verdict-letter position; the end of reasoning; the mean over reasoning tokens; the
    reasoning at 25%, 50% and 75%.
  - Layers: the last, plus three middle layers.
- **Probe.** L2 logistic regression for "this trace's verdict is right".
  - Covariates: the verdict letter and the presentation order.
  - Features are standardized within folds.
- **Baseline.** A logistic regression on [verdict, reasoning length, hedge rate], fit the same way.
- **Selection.** Nested leave-one-database-out cross-validation within the training databases, on
  log loss, with the one-SE rule.
  - One configuration is frozen before the held-out set is scored.
  - The number of configurations tried is reported.
- **Primary metric.** Within-ordered-pair AUROC on the mixed ordered pairs of the held-out set: right
  vs wrong traces of the same ordered pair. The interval is a database-cluster bootstrap (4,000 reps,
  seed 0).
- **Gate A (go to Stage B).** Both must hold:
  - the probe's within-pair AUROC is at least 0.65;
  - it is at least 0.05 above the baseline's, with the bootstrap interval of the difference above 0.
- **Also reported.** Pooled AUROC, Brier score, and results per source, with complex and Claude
  h1/h2 (the Spider2-like sources) shown separately.
- **Power (estimate).** About 128 held-out mixed ordered pairs, so the SE of the AUROC is about
  0.03–0.04.
- **Stop rule.** If Gate A fails for every configuration in the exploratory set (mean-pooled and
  middle layers included), the line stops. The conclusion is "no transferable trace-level signal in
  these features", not "none in the model".

## Stage B: decision, on `diff_cmp` reasoning (only if Gate A passes)

1. **Regenerate the practice judgments with `diff_cmp`.** This needs result comparisons for the
   practice pairs. Same pairs, 4 samples per ordered pair, about 11–15 GPU-h (estimate).
2. **Refit the frozen Stage-A configuration** on the training databases and re-check Gate A on the
   held-out practice set.
3. **Spider2 design half, one evaluation of the frozen probe.**
   - Soft vote: v = c if the trace's verdict is A, else 1 − c, where c = P(trace right). It is scored
     with `selection_eval.py` (`@S`).
   - Comparators on the same calls: deployed `diff_cmp`, rule A, rule F; avg4 is reported alongside.
   - Bar: a contested exp1 gain over the best comparator at no more than 1.6× its compute, of +3, or
     +2 with at least twice as many pools up as down. The easy-pool loss must be at most 1.
4. **Test half and BigQuery, one evaluation.** The prompt protocol's pass bar applies:
   - test contested gain over deployed `diff_cmp` with a 95% interval above 0;
   - easy loss at most 1.5 over both halves;
   - BigQuery mixed change at least −1.5.
   - This is a further use of the stored test-half calls, declared here.
5. **A LoRA head (training the letter after the reasoning) gets its own pre-registration,** and only
   if Stage B passes.

## Engineering checks, before any probe result is looked at

- The A-minus-B letter logit at the verdict position has the sign of the stored verdict on at least
  99% of traces.
- Rebuilt Spider2 prompts (Stage B) have a non-empty schema section in 100% of cases, and a doc section
  wherever the question has one.
- Extraction is sharded and resumable, and input md5s are logged.

## Expected outcome (estimate)

- About a 70% chance that Gate A fails. Probes add little on objective-correctness judging, and the
  surface features show no within-pair signal.
- If it passes: +1–3 contested pools per half beyond the free rules.
- Rules A and F are label-free alternatives that need no training. They were found after looking at
  the design half, so they would need their own pre-registered test.
