# Judge training methods: data, losses, settings, evaluation

How the judge fine-tunings of Nov 1–11 2026 (v1–v6) were built, and how the planned two-loss arms are
defined. Results are in [judge_results.md](judge_results.md) §4. Code: `nl2sql-v2/scripts/`
(`make_judge_sft_dpo.py`, `train_judge_lora.py`, `merge_judge_adapter.py`, `judge_gate.py`,
`judge_pools.py`) and `nl2sql-v2/slurm/`.

## 1. The task being trained

- The judge compares two candidate answers to one question.
- Its prompt (`select_answer.py` PAIRWISE_PROMPT) holds the question, the doc, a schema overview, and
  each candidate's SQL with an 8-row result preview.
- It replies `{"winner": "A" or "B", "reason": "..."}`.
- With thinking on, Qwen writes its reasoning first, inside `<think>...</think>`.
- The round-robin calls it on every ordered pair of distinct results.
- A **practice pair** is a question on a non-Spider2 database plus one right and one wrong answer
  from our agent; both presentation orders are used.

## 2. From sampled judgments to training rows (`make_judge_sft_dpo.py`)

**Input.** `sample_judge_verdicts.py` records, one per question. Each ordered pair holds its prompt,
its correct letter, and 4 judgments sampled from the untuned judge (thinking on, temperature 0.6),
each with its reasoning and reply. `--extra-samples` adds more samples of the same pairs.

For every question in the train split whose database is not held out:
- **Usable sample:** the verdict parsed, and the sample was not truncated and had no error.
- **Right / wrong:** whether the sample's verdict equals the correct letter.
- **Caps and weights:**
  - at most `--max-pairs-per-question` 4 unordered pairs per question, both orders kept together;
  - pools where only 1 lane is correct are repeated `--lone-weight` 2 times;
  - `--source-weight` repeats one source's rows (complex = 2 in v3c).
- **Label check:** `--drop-pairs` removes both orders of a pair that `check_pair_labels.py` labelled
  other_reading (the "wrong" answer is another fair reading).
- **Held out:**
  - the 15 val-split databases are never used;
  - `--holdout-frac 0.2` (v2a) held out 10 of the 48 training databases (seed 0), and later builds
    reuse that list with `--holdout-file`;
  - so 25 of 63 databases in all from v2a on. v1 held out only the val split.

Rows written per ordered pair:

| file | row | rule |
|---|---|---|
| `sft.jsonl` | `{messages: [user prompt, assistant(content = reply JSON, reasoning_content = reasoning)]}` | up to `--sft-per-pair` (2) right samples |
| `dpo.jsonl` | `{prompt, chosen: [right sample], rejected: [wrong sample]}` | up to `--dpo-per-pair` (2; 4 from v2a on) right/wrong pairs on the same prompt |
| `choice.jsonl` | `{prompt, correct_letter}` | every kept ordered pair, never-right ones included |
| `hard_pairs.jsonl` | pairs the judge never got right | not trained on |

All reasoning in these files is the untuned Qwen judge's own; no Claude-written reasoning is used.

## 3. Losses

Notation: x = prompt; y = judgment (reasoning + reply); z_A, z_B = logits of the tokens `A` and `B`
at the position where the letter is written.

| stage | what is trained | loss |
|---|---|---|
| `sft` | imitate the judge's own right judgments | completion-only next-token NLL over y (reasoning and reply), −Σ log π_θ(y_t \| x, y_<t) / \|y\|; the prompt is masked (TRL SFTTrainer, `completion_only_loss=True`) |
| `dpo` | prefer the right judgment over a wrong one on the same prompt | −log σ(β [(log π_θ(y_w\|x) − log π_ref(y_w\|x)) − (log π_θ(y_l\|x) − log π_ref(y_l\|x))]), β = 0.1, over the whole judgment (TRL DPOTrainer). Reference: the SFT model (v1) or the base (v2a, v3c) |
| `choice` | only the pick, thinking off | 2-way cross-entropy on [z_A, z_B] after the thinking-off reply opening `{\n "winner": "`: log(1 + exp(−s · (z_A − z_B))), s = +1 if A is correct, else −1 |
| `choice_mt` *(planned, C1)* | the pick (thinking off) plus the judge's own right reasoning | choice loss on choice rows + λ × completion NLL on sft rows (thinking on), λ = 0.25 |
| `choice_reason` *(planned, C2)* | the pick read after the judge's own reasoning | ½ [CE(z \| x, right reasoning) + CE(z \| x, wrong reasoning)] toward the correct letter, + λ × NLL of the right reasoning, λ = 0.25. Input: thinking-on prompt + `<think>` reasoning `</think>` + `{"winner": "` |

Notes:
- **The letter loss is already a linear head.** z_A − z_B = (W_A − W_B) · h, with h the LoRA-adapted
  last hidden state. So the `choice` loss is logistic regression on the hidden state, with the head
  taken from the output embedding. A separate CLS head would add only a free direction and a bias.
- **What separates the planned arms is the input, not the head.** With A/B verdicts, "is this
  reasoning right?" and "pick the correct letter after reading it" are the same target. C2 differs
  from v4 by reading the reasoning, and C1/C2 add a reasoning loss, as GenRM, CLoud, Critic-RM and
  distilling step-by-step do (judge_results.md §6).

## 4. Common settings (`train_judge_lora.py`, `train_judge.slurm`)

- **Base:** bf16 Qwen/Qwen3.6-35B-A3B (the release the served AWQ build was quantized from), loaded
  with `AutoModelForImageTextToText`.
- **LoRA:**
  - r = 16, α = 32, dropout 0.05;
  - on full attention q/k/v/o, linear attention (`in_proj_*`, `out_proj`) and the shared-expert MLP;
  - the routed experts, router and vision tower are frozen (`router_aux_loss_coef = 0`).
- **Optimization:**
  - batch 1, gradient accumulation 16, cosine schedule, 3% warmup, gradient checkpointing;
  - max length 12,288 tokens (longer rows dropped); checkpoint every 5 steps; preempted jobs resume;
  - learning rate: 1e-4 for sft and choice, 5e-6 for dpo unless set;
  - epochs: 2 for sft and choice, 1 for dpo unless set;
  - training stops on a non-finite or exploding loss.
- **Hardware:** 2× A100-80GB or 4× ≥48GB GPUs on the preempt partition.
- **Serving:** `merge_judge_adapter.py` folds W += (α/r) B A into the AWQ checkpoint's unquantized
  modules (vLLM 0.18.1 cannot serve LoRA on this AWQ MoE build). The merged judge is served by vLLM.

## 5. The runs

| run | data build (`make_judge_sft_dpo.py`) | rows | training |
|---|---|---|---|
| v1 | `--verdicts verdicts_train_v1` (BIRD-Platinum + early Claude batches), defaults, no `--holdout-frac` | SFT 2,750; DPO 423 | `sft` (lr 1e-4, 2 ep), then `dpo` on top (lr 5e-6, 1 ep, ref = SFT); the adapters are joined |
| v2a | `--verdicts v1 --dpo-per-pair 4 --extra-samples train_untuned,train_tuned` (8 more samples per pair) `--holdout-frac 0.2` | DPO 848 | `dpo` from the base, lr 5e-5, 2 epochs |
| v2b | as v2a | DPO 848 | lr 1.5e-4, 3 warmup steps: diverged |
| v3c | `--verdicts v1,complex --dpo-per-pair 4 --extra-samples ...,cplx_untuned --holdout-file v2a --drop-pairs complex labels --source-weight complex=2` | DPO 1,476 (628 complex) | as v2a |
| v4 | the v3c pairs and holdout (`judge_train_v4/data`) | choice 2,006 over 1,344 ordered pairs | `choice`, lr 1e-4, 2 epochs, thinking off |
| v4 e1 | as v4 | as v4 | 1 epoch |
| v5c | v4 + `verdicts_claude_v3` with its other_reading drops | choice 2,164 over 1,472 pairs | as v4 |
| v6 | v5c + `verdicts_claude_h1,h2` + `verdicts_beaver_p1` with their drops (`data_v6`) | choice 2,644 over 1,814 pairs | as v4 |

Commands:
- SFT/DPO: `sbatch --export=ALL,STAGES="dpo merge",DPO_ARGS="--lr 5e-5 --epochs 2",DATA=<dir>,OUT=<dir> ~/slurm/train_judge.slurm`
- Letter-only: `keep_choice_chain.sh` (DATA, V) runs `STAGES="choice merge"`, then `judge_choice_eval.slurm`.

## 6. Evaluation

1. **Gate on practice pairs** (`judge_gate.py`, pairs judged by `rejudge_pairs.py`).
   - The tuned judge is compared with fresh untuned samples (4 per order) on three groups:
     - pairs it trained on;
     - pairs on seen databases it did not train on;
     - held-out pairs (holdout databases + val split).
   - Each group is split by how often the untuned judge was right (never / mixed / always).
   - Pass: trained mixed pairs gain at least 5 points. The held-out rows show transfer.
   - Later gates add complex, Claude and BEAVER pairs (`judge_choice_eval.slurm`).
2. **Spider2 and BigQuery round-robin** (`judge_pools.py`, `bq_judge_pools.py`, served merged judge).
   - The SFT/DPO judges were run with thinking on (at temperature 0.2, by mistake; fixed Nov 7).
   - The letter-only judges were run with thinking off, reading P(A).
   - Score: correct picks out of 540 and 105, against the untuned thinking judge (296 / 26) and the
     no-think judge (281 / 24).
3. **As a tie-breaker** (exploratory): ties at the top of the thinking judge's round-robin are broken
   by the tuned judge's soft score.
4. **Pre-set stop rule (v6):** v6 had to beat v4 by more than about 10 points on held-out Claude
   h1/h2 and complex pairs, and as a tie-breaker. It did not, so judge-data work stopped.

## 7. Caveats

- **Label noise.** 7–27% "another fair reading" per source, and the label check catches about half.
  Practice SQL is simpler than Spider2's (BIRD median 228 vs 1,266 chars).
- **Evaluation temperature.** v1, v2a and v3c were evaluated at temperature 0.2 instead of 0.6.
- **Open forward-pass issue (Nov 13).** The bf16 HF forward used by all trainings is intermittently
  broken (zero / NaN activations). See judge_results.md §7.
  - Until it is resolved, §4 results may understate what training can do.
  - New runs pass an identity check first, and the MoE experts implementation is selectable
    (`--experts`).
