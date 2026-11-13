# Training data and recipes for pairwise judges / verifiers in verifiable domains (code, math), and what transfers to pairwise SQL candidate selection

*Conventions.* "Measured" = a number the paper reports from its own experiment; "claim" = an authors' summary statement not directly re-derived here. "Our setup" = Qwen3.6-35B-A3B agent, 4 samples per question, 135 local Spider 2.0-Lite questions, round-robin pairwise judge over distinct answers in both orders, 82–83 judge-correct vs 94 with ≥1 correct candidate (gap of 11–12 questions, mostly "1 correct vs 2–3 agreeing wrong"). All sources below are non-SQL (math, code, general preference) except LEVER, which is mentioned only for its general recipe. Numbers were taken from the arXiv full text (HTML/PDF) unless the citation says abstract.

## Q1. How do judge/verifier papers build positive and negative pairs without human labels?

### Takeaway
Almost every verifiable-domain recipe uses the same steps. Sample several candidates per problem, usually from one model. Label each one by checking the final answer or running tests. Keep only problems with mixed correctness, then pair a correct candidate with an incorrect one, or have a teacher judge the pair and keep only verdicts that agree with the label. Recipes differ in two places. The first is where negatives come from: same-model samples, a weaker model, a response to a perturbed instruction, or perturbed, truncated or adversarial outputs. The second is how label noise is filtered: agreement filters, a second labeler, or rejection sampling of teacher verdicts.

### Cited Findings
**Answer-checked sampling (math, the dominant label source)**
- Cobbe et al. (GSM8K): "Sample 100 completions from the generator for each training problem and label each solution as correct or incorrect" by final answer. Verification gave "approximately the same performance boost as a 30x model size increase". They note false positives from solutions that "reach the correct final answer using flawed reasoning". — [Cobbe et al., arXiv 2110.14168](https://arxiv.org/abs/2110.14168)
- J1 (Meta, 2025): the final training set is 22K synthetic pairs, 17K from WildChat and 5K from MATH. "For MATH, rejected responses are sampled from generations by an LLM that do not lead to the gold answer". For WildChat, the rejected response is the LLM's response to an LLM-generated "noisy" variant of the instruction. — [J1, arXiv 2505.10320](https://arxiv.org/abs/2505.10320)
- EvalPlanner (Meta): a Mixtral 8x22B Instruct model generates multiple candidate solutions per MATH problem, labeled correct or incorrect by answer. WildChat pairs use the noisy-instruction method. Totals: 17,588 WildChat and 4,141 MATH triples. Measured: "Wildchat instructions help the Chat-hard category more, MATH prompts are more effective for the Reasoning category". — [EvalPlanner, arXiv 2501.18099](https://arxiv.org/abs/2501.18099)
- Self-Taught Evaluator (Meta): from unlabeled instructions, an LLM writes a "noisy" instruction x′, and its best-attempt answer to x′ becomes the losing response for x. An LLM classifies instructions to select "a challenging, balanced distribution". The current judge annotates the pairs, and rejection sampling removes judgments whose verdict disagrees with the synthetic label. The loop repeats. Measured: Llama3-70B-Instruct went from 75.4 to 88.3 on RewardBench (88.7 with majority vote), with no human preference labels. — [Self-Taught Evaluator, arXiv 2408.02666](https://arxiv.org/abs/2408.02666)
- PairJudge RM: on NuminaMath, Llama-3.1-8B-Instruct generates 24 candidates per problem (temperature 1.0, top-p 0.5). gemini-1.5-flash then runs knockout tournaments, only on problems whose candidates are "not all correct or all incorrect": 343K tournaments and 2.2M comparisons. The 1.3M comparisons that "correctly evaluated both candidate solutions" were kept, leaving 432K after format filtering. Qwen2.5-7B-Instruct was trained on them by SFT. — [PairJudge RM, arXiv 2501.13007](https://arxiv.org/abs/2501.13007)
- Reward Reasoning Model (RRM, Microsoft): about 420K pairs, made up of 80K from Skywork-Reward, 80K from Tülu 3, 80K synthesized from Tülu 3 prompts and 180K from other sources. For verifiable sources: "If at least one response is correct and another is incorrect, we add the correct-incorrect pair". — [RRM, arXiv 2505.14674](https://arxiv.org/abs/2505.14674)
- GenSelect training data (NVIDIA, AIMO-2): for each problem, 2–16 candidate solution summaries are sampled, with "at least one correct and one incorrect solution" in every group. QwQ-32B makes the selection. The resulting 1M selections were cut to 565K "by eliminating any instances where incorrect solutions were chosen". Summaries were rewritten by Qwen2.5-32B-Instruct, and any summary whose answer differed from its solution's answer was dropped. — [AIMO-2 / OpenMathReasoning, arXiv 2504.16891](https://arxiv.org/abs/2504.16891)
- JudgeBench uses the same construction as a benchmark. It samples k responses from one strong model (e.g., GPT-4o), grades them, and keeps questions with ≥1 correct and ≥1 incorrect response. Using a single model "ensures consistency in response style… and mitigat[es] self-enhancement bias". — [JudgeBench, arXiv 2410.12784](https://arxiv.org/abs/2410.12784)
- GenRM (DeepMind) frames verification as next-token prediction of Yes/No. Gemini 1.0 Pro synthesizes CoT rationales with reference-guided grading. The answer checker produces false negatives, and some solutions reach the right answer by wrong reasoning, so the authors "only keep the rationales from solutions where more than 50% of verification rationales agree with the correctness returned by the answer checker". — [GenRM, arXiv 2408.15240](https://arxiv.org/abs/2408.15240)
- V-STaR trains a DPO verifier on correct vs incorrect self-generated solutions collected over several self-improvement iterations. Claim: 4% to 17% test accuracy gains over self-improvement and verification baselines (LLaMA2, code and math). — [V-STaR, arXiv 2402.06457 (abstract)](https://arxiv.org/abs/2402.06457)

**Execution/test-based labels (code)**
- AceCoder: an LLM synthesizes test cases, Qwen2.5-Coder-32B-Instruct filters them as a proxy, and questions with fewer than 5 remaining tests are dropped, giving AceCode-87K. Programs are sampled from existing models (e.g., Llama-3.1) and scored by pass rate s. A pair is kept only if 𝟙[s_i > s_j + 0.4, s_i > 0.8, s_j > 0], and a Bradley-Terry reward model is trained on these pairs. Measured with best-of-32: +10 points average for Llama-3.1-8B-Ins and +5 for Qwen2.5-Coder-7B-Ins. — [AceCoder, arXiv 2502.01718](https://arxiv.org/abs/2502.01718)
- CodeT: the same LM generates tests, and solutions are chosen by "dual execution agreement". HumanEval pass@1 reached 65.8%, +18.8 over code-davinci-002. — [CodeT, arXiv 2207.10397 (abstract)](https://arxiv.org/abs/2207.10397)
- MBR-exec: each program is run on a few test inputs, and selection marginalizes over programs with identical outputs. It consistently beats execution-unaware selection. — [MBR-exec, arXiv 2204.11454 (abstract)](https://arxiv.org/abs/2204.11454)
- LEVER trains a verifier on the NL input, the program and its execution result. Reranking combines the verifier score with LM probability and marginalizes over programs with equal results: +4.6 to +10.9 points with code-davinci-002 on table QA, math QA and Python. The SQL-specific results belong to the other researcher's scope. — [LEVER, arXiv 2302.08468 (abstract)](https://arxiv.org/abs/2302.08468)
- CodeRM-8B: scaling the number of LLM-generated unit tests improves reward-signal quality, with larger benefits on harder problems. Measured on HumanEval Plus: +18.43% for Llama3-8B and +3.42% for GPT-4o-mini. — [CodeRM-8B, arXiv 2501.01054 (abstract)](https://arxiv.org/abs/2501.01054)
- CURE co-evolves a coder and a unit tester with RL, "without any ground-truth code", so the tester learns "directly from the coder's mistakes". Claim: Best-of-N accuracy +9.0%. — [CURE, arXiv 2506.03136 (abstract)](https://arxiv.org/abs/2506.03136)

**Process (step) labels**
- Math-Shepherd labels steps automatically. The Qwen paper below classes it as Monte-Carlo-estimation data of about 445K examples. Measured: step-by-step PPO took Mistral-7B from 77.9% to 84.1% on GSM8K and from 28.6% to 33.0% on MATH, and adding verification raised these to 89.1% and 43.5%. — [Math-Shepherd, arXiv 2312.08935 (abstract)](https://arxiv.org/abs/2312.08935)
- Qwen, "Lessons" paper: MC-estimation labels give "inferior performance and generalization compared to LLM-as-a-judge and human annotation". Consensus filtering keeps an instance only when MC estimation and a Qwen2.5-72B-Instruct judge agree on the error step. "Only approximately 40% of the data are preserved", yet performance and data efficiency both improve. BoN evaluation is biased because policies produce "responses with correct answers but flawed processes". — [Qwen PRM Lessons, arXiv 2501.07301](https://arxiv.org/abs/2501.07301)
- ThinkPRM uses QwQ-32B-Preview to write verification CoTs and keeps them only when they agree with PRM800K step labels. Training used 1K synthetic examples, or 8K step labels, about 1% of PRM800K. "Fine-grained filtering of synthetic data based on step supervision is crucial". — [ThinkPRM, arXiv 2504.16828](https://arxiv.org/abs/2504.16828)
- For contrast, PRM800K relied on 800K human step labels. Process supervision beat outcome supervision, reaching 78% on a MATH subset. — [Let's Verify Step by Step, arXiv 2305.20050 (abstract)](https://arxiv.org/abs/2305.20050)

**Teacher distillation with label-based rejection**
- RM-R1 draws on a cleaned subset of Skywork Reward Preference 80K, 8K Code-Preference-Pairs and the full Math-DPO-10K. An "oracle" model (o3 or Claude-3.7-sonnet) writes reasoning traces for 8.7K examples used for distillation, followed by RLVR on 64K examples (Instruct models). — [RM-R1, arXiv 2505.02387](https://arxiv.org/abs/2505.02387)
- DeepSeek-GRM uses rejective fine-tuning: critiques are sampled and rejected when their predicted rewards disagree with ground truth. "Hinted" sampling, where the correct answer is appended to the prompt, produces trajectories that "sometimes take shortcuts… especially for reasoning tasks". Measured: removing non-hinted sampling hurt more (67.4) than removing hinted sampling (68.0), against a 68.8 full RFT model. — [DeepSeek-GRM, arXiv 2504.02495](https://arxiv.org/abs/2504.02495)
- JudgeLM: 100K training samples with GPT-4 judgments of LLM-generated answers. — [JudgeLM (ICLR 2025), arXiv 2310.17631](https://arxiv.org/abs/2310.17631)

**Perturbed / constructed negatives**
- The noisy-instruction negatives of Self-Taught Evaluator, J1 and EvalPlanner (above) are, in effect, best attempts at a slightly different question: "a 'noisy' version x′ of the original instruction x, and then a best-attempt yl at responding to x′". — [STE](https://arxiv.org/abs/2408.02666); [J1](https://arxiv.org/abs/2505.10320); [EvalPlanner](https://arxiv.org/abs/2501.18099)
- CriticGPT (OpenAI): "Contractors modify ChatGPT responses to insert subtle bugs" ("tampering"). Inserted bugs "are both harder for humans to catch and more severe on average but are not from the natural distribution of model errors". On naturally occurring LLM errors, model critiques were preferred over human critiques 63% of the time. The insertions were made by humans, but the construction could be automated. — [CriticGPT, arXiv 2407.00215](https://arxiv.org/abs/2407.00215)
- Master-RM: "master keys" such as ":" or "Thought process:" elicit false-positive rates "as high as 80%" from LLM judges. Adding negatives made by "truncating model-generated solutions to their first segment" gives "near-zero FPRs". — [One Token to Fool LLM-as-a-Judge, arXiv 2507.08794](https://arxiv.org/abs/2507.08794)
- Adv-RM trains an RL policy to find responses that score high but are low quality and out of distribution. Adding them to RM training improves robustness (claim). — [Adv-RM, arXiv 2504.06141 (abstract)](https://arxiv.org/abs/2504.06141)
- RM-Bench is a benchmark of subtle content changes. Even state-of-the-art RMs average 46.6%, below random (50%), under style-bias interference. — [RM-Bench, arXiv 2410.16184 (abstract)](https://arxiv.org/abs/2410.16184)

**Combining weak verifiers as the label source**
- Weaver combines LM judges and RMs with weak supervision, which estimates each verifier's accuracy with little labeled data. It normalizes output formats and filters out low-quality verifiers. With 50K labeled query-response pairs, learned weights beat naive averaging by up to 11.2 points. Weak verifiers "suffer from high false positive rates". — [Weaver, arXiv 2506.18203](https://arxiv.org/abs/2506.18203)

### Inferences
- **The template carries over to SQL almost unchanged.** Run our own agent K times per question on non-Spider2 SQLite questions and label each candidate by execution match. Keep questions with mixed correctness and build (correct, incorrect) pairs over distinct result sets, in both orders. This is exactly the J1 / PairJudge / RRM / GenSelect / JudgeBench construction. JudgeBench's "single strong model, mixed correctness" pairs are structurally our 4-candidate pools.
- **Labels must use our scorer's semantics.** That means extra columns tolerated, `ignore_order` and `condition_cols`. A stricter or looser checker produces label noise of the kind GenRM filters out (checker false negatives).
- **"Correct by coincidence" is the SQL version of Qwen's "correct answer, flawed process".** A fan-out join that inflates nothing on this database instance, or a name key that happens to be unique here, will match gold. Plain execution labels would teach the judge to accept these. Two mitigations follow from the sources: consensus labels (Qwen; execution match AND a strong LLM judge agree) and execution on extra database variants that discriminate between candidates (CodeT, MBR-exec, S*). Running on database variants is the analog of extra test inputs.
- **The noisy-instruction method fits our error list well.** Rewrite a training question at a different grain, denominator, status definition, key (name vs ID) or answer shape (single row vs ranked list), then run the agent on it. Results that differ from the original question's gold-matching result are natural-looking near-miss negatives. CriticGPT-style tampering of correct SQL can be automated too: add a fan-out join, switch an ID key to a name, change tie handling at a LIMIT, or collapse a ranked list to its top row. Per CriticGPT, inserted errors are not natural errors, so mix them with mined on-policy errors.
- **Filter distillation traces from our current judges by label.** Run the Qwen3.6-35B thinking judge and JEV-27B on the training pairs. Keep traces whose verdict matches the execution label in both orders (Self-Taught Evaluator and PairJudge rejection sampling). Do not generate traces with the answer in the prompt, because hinted traces take shortcuts (DeepSeek-GRM).
- **Formatting and label-convention errors are partly specific to each dataset.** Training on another corpus's conventions could teach conventions that differ from Spider2's. Normalize formatting before labeling, or keep formatting-only differences out of the training labels.
- **Check database overlap.** Project memory notes that BIRD and Spider training sets share Spider2 database schemas, so check the on-policy question pool for database overlap before use.

### Gaps
- No non-SQL paper I found compares negative sources directly on a fixed generator's BoN selection: same-model samples vs perturbed instruction vs perturbed output. The evidence is indirect (SFR-Judge Table 11 and Principia; see Q3 and Q7).
- I did not extract the per-iteration dataset sizes of Self-Taught Evaluator.

## Q2. How are judges trained (SFT/distillation, DPO, RL with verifiable rewards)? Data needs, trade-offs, label-noise tolerance

### Takeaway
For pairwise judges with verifiable labels, the best controlled comparison favors online RL (GRPO) with a verdict-correctness reward over DPO on the same synthetic data (J1 vs EvalPlanner, same base and data). DPO in turn beats SFT on chosen traces only (EvalPlanner, SFR-Judge). A short distillation warm start helps in some reports (RM-R1) but is unnecessary in others (TIR-Judge-Zero, RRM). Label noise is handled almost entirely by filtering. I found no head-to-head test of SFT vs DPO vs GRPO judges under controlled label noise.

### Cited Findings
- **J1 (GRPO) vs EvalPlanner (2× DPO) on the same data and base:** the authors say this "validates the effectiveness of J1's training methodology and use of online RL, compared to EvalPlanner, which is trained on the same data but with two iterations of DPO". Measured PPE-Correctness with the same Llama-3.1-8B base: EvalPlanner-8B 52.8 → J1-Llama-8B 59.2. On the five-benchmark average, J1-Llama-8B scores 61.9 vs EvalPlanner-Llama-8B 56.2 and base 48.3. On position-consistent JudgeBench it scores 42.0 vs 30.2. At 70B, J1 scores 75.0 vs 73.2. — [J1, arXiv 2505.10320](https://arxiv.org/abs/2505.10320)
- **J1 recipe details (measured, 8B):**
  - Reward: verdict correctness plus a consistency reward (below).
  - The KL penalty matters: overall 63.9 with it vs 61.1 without. "More exploration generally leads to some degradation".
  - Outputting a verdict beat outputting scores or scores plus verdict: 63.9 vs 63.4 vs 61.7.
  - J1 beat a scalar RM trained on the same data on 4 of 5 benchmarks.
  - J1-Qwen-32B-MultiTask reaches 80.8 overall vs o3 77.4 and DeepSeek-R1 78.4, trained "only… on synthetic data".
  - [J1, arXiv 2505.10320](https://arxiv.org/abs/2505.10320)
- **EvalPlanner ablation** (RewardBench, Llama-3.1-70B seed, 2.5K MATH instructions): seed model 84.0; trained without thoughts 86.2; SFT with thoughts 86.8; SFT + DPO with thoughts 90.5. The full recipe is SFT on chosen thoughts, then 2 DPO iterations, reaching 93.9 on RewardBench. — [EvalPlanner, arXiv 2501.18099](https://arxiv.org/abs/2501.18099)
- **JudgeLRM:** RL with "judge-wise, outcome-driven rewards". These combine a structural (format) reward with content rewards for relation (the correct preference), absolute score and confidence. Claims: +8.14% F1 on average over SFT counterparts; "SFT gains drop as the proportion of reasoning-intensive items rises"; JudgeLRM-3B/4B exceed GPT-4, and 7B/8B/14B beat DeepSeek-R1 by >2% F1. — [JudgeLRM, arXiv 2504.00050](https://arxiv.org/abs/2504.00050)
- **SFR-Judge (Salesforce):** DPO on 680K samples using three pair types (CoT critique, standard judgement, response deduction). SFT is called "suboptimal, as it only trains LLMs to mimic correct examples without exposing the model to incorrect examples; we observe similar trends". — [Direct Judgement Preference Optimization, arXiv 2409.14664](https://arxiv.org/abs/2409.14664)
- **RM-R1:** distillation (8.7K) followed by RLVR (64K). "Cold Start RL… fails to close the gap to fully optimized models". Claim: beats INF-ORM-Llama3.1-70B and GPT-4o by up to 4.9% on average. — [RM-R1, arXiv 2505.02387](https://arxiv.org/abs/2505.02387)
- **DeepSeek-GRM (SPCT):** rejective fine-tuning followed by rule-based online RL; RFT-only scores 68.8 vs 69.9 with RL (greedy, overall). Online RL is motivated by shortcut critiques in hinted trajectories. — [DeepSeek-GRM, arXiv 2504.02495](https://arxiv.org/abs/2504.02495)
- **TIR-Judge:** "TIR-Judge-Zero – trained entirely without distilled judge trajectories, matches the performance of distilled variants". It is +1.2% over its distilled counterpart at 4B. The 8B model beats reasoning judges by up to 6.4% pointwise and 7.7% pairwise. — [TIR-Judge, arXiv 2510.23038](https://arxiv.org/abs/2510.23038)
- **RRM:** RL with rule-based rewards, "without requiring explicit reasoning traces as training data". — [RRM, arXiv 2505.14674](https://arxiv.org/abs/2505.14674)
- **Con-J:** DPO on self-generated positive and negative judgments with rationales. It performs comparably to a scalar RM on the same data, and the authors claim more robustness to dataset bias. — [Con-J, arXiv 2410.03742 (abstract)](https://arxiv.org/abs/2410.03742)
- **GenRM (SynthLabs):** zero-shot LLM judges trail Bradley-Terry RMs in-distribution by 9–36%. An iteratively self-trained GenRM matches BT in-distribution and beats it out-of-distribution by 10–45%. — [Generative Reward Models, arXiv 2410.12832 (abstract)](https://arxiv.org/abs/2410.12832)
- **Label noise is handled by filtering:**
  - GenRM keeps rationales only with >50% agreement with the checker.
  - Qwen consensus filtering keeps about 40% of the data and still improves results.
  - PairJudge keeps 1.3M of 2.2M teacher comparisons.
  - GenSelect keeps 565K of 1M selections.
  - Self-Taught Evaluator rejection-samples the judge's verdicts.
  - Sources: [GenRM](https://arxiv.org/abs/2408.15240); [Qwen Lessons](https://arxiv.org/abs/2501.07301); [PairJudge](https://arxiv.org/abs/2501.13007); [AIMO-2](https://arxiv.org/abs/2504.16891); [STE](https://arxiv.org/abs/2408.02666)
- **Noise tolerance of RL (policy, not judge):** flipping 40% of reward outputs on math still took Qwen-2.5-7B from 5% to 72%, vs 75% with noiseless rewards. — [Noisy Rewards in Learning to Reason, arXiv 2505.22653 (abstract)](https://arxiv.org/abs/2505.22653)
- **Judges distilled without reasoning get hacked:** smaller judges were trained on annotations from a "gold-standard" judge (gpt-oss-120b). When those judges were used to train policies with RL, "non-reasoning judges lead to reward hacking easily". Reasoning judges led to strong policies, partly because the policies learned "highly effective adversarial outputs" that also fool other LLM judges. — [Examining Reasoning LLMs-as-Judges, arXiv 2603.12246 (abstract)](https://arxiv.org/abs/2603.12246)

### Inferences
- **The recipe with the most evidence for our 9B pairwise judge:**
  1. Optional SFT warm start on label-filtered traces from the 35B thinking judge.
  2. GRPO with J1's verdict-correctness reward plus the both-order consistency reward, with a KL penalty, on about 10–25K on-policy SQL pairs.
  3. Model selection on held-out on-policy pairs from non-Spider2 databases.
- **DPO is the cheaper fallback.** In EvalPlanner it added +3.7 over SFT on the ablation set, but J1's online RL beat DPO on the same data.
- **Our labels are execution matches, which are mostly clean.** "Different result" is close to noiseless. The noise sits in coincidental matches and formatting-convention mismatches, and the literature's answer to both is filtering, not a choice of algorithm.
- **RL-trained and DPO-trained judges learn shortcuts.** Examples are hinted shortcuts and master keys. Plausible shortcuts for SQL previews include "non-empty result wins", "more columns wins" and "the longer, more careful-looking SQL wins". Build matched adversarial negatives against them, such as a plausible preview at the wrong grain or SQL that looks careful but fans out (Master-RM / Adv-RM idea).

### Gaps
- No controlled study found of SFT vs DPO vs GRPO judges under injected label-noise rates.
- No judge-training study found whose inputs include tabular execution previews (the closest is LEVER's execution-aware verifier).

## Q3. On-policy pairs (from the generator being selected for) vs off-policy pairs: measured effect

### Takeaway
There are few direct measurements, and they all point the same way. Meta's Principia study (2026) found that a judge trained on the target generator's own samples improved downstream results more than identical judges trained on a weaker or a stronger model's samples, even though offline judging accuracy rose for all three. The downstream metric there is RL, not BoN. Indirect evidence agrees. An off-distribution 72B RM fell below majority voting in GenSelect. Errors from weaker generators are easier to catch. PairJudge's gain is largest on the generator that produced its training data. Off-policy data is not useless: J1 and RRM trained on other models' samples still improve BoN on PPE candidates.

### Cited Findings
- **Principia, Table 11 (measured):**
  - Setup: three J1-trained Qwen3-32B reward models with the same recipe, differing only in training data. The on-policy RM uses 18,774 balanced Qwen3-1.7B responses labeled by GPT-OSS-120B. The off-policy RMs use responses from Llama-3.1-8B-Instruct or from Qwen3-8B.
  - Downstream average over 6 math benchmarks after RL post-training of Qwen3-1.7B: base 35.20; prompted Qwen3-32B RM 41.88; off-policy (Llama data) 41.08; off-policy (Qwen3-8B data) 40.41; on-policy 43.41.
  - J1 training improved in-distribution judgment accuracy for all three RMs, "the off-policy trained LMs-as-RMs do not transfer to downstream policy improvements". "Responses from the weaker Llama model are easiest to judge".
  - Separately, J1 training on Qwen3-1.7B, which judges its own outputs, brought no gain, while the same training on Qwen3-32B gave +10% absolute. The authors' reading is that the generator-verifier capability gap matters.
  - [Principia, arXiv 2603.18886](https://arxiv.org/abs/2603.18886)
- **GenSelect (Comp-Math-24-25, QwQ-32B solutions):** majority@64 scores 68.4 and Qwen2.5-Math-RM-72B 66.8. The authors attribute the RM's shortfall to "distribution mismatch, as the model was trained on a different data distribution". QwQ judging its own samples gets 69.1 pointwise and 72.1 with GenSelect@1. — [GenSelect, arXiv 2507.17797](https://arxiv.org/abs/2507.17797)
- **PairJudge**, trained on Llama-3.1-8B-Instruct samples. Measured MATH-500 gain over majority voting at @16/@32/@64, by generator (my arithmetic from their Table 2):
  - Llama-3.1-8B: +4.0 / +5.8 / +6.8
  - Qwen-2.5-7B: +2.8 / +2.2 / +2.4
  - Llama-3.1-70B: +2.0 / +2.8 / +3.8
  - [PairJudge RM, arXiv 2501.13007](https://arxiv.org/abs/2501.13007)
- **Variation in Verification:** "Weak generators produce errors that are easier to detect than strong generators". Verification ability tracks the verifier's own problem-solving ability. With strong generators, a strong verifier (GPT-4o) can offer "no additional benefit" over a weak one (Qwen2.5-7B). The study covers 14 open models from 2B to 72B plus GPT-4o, on 12 benchmarks. — [Variation in Verification, arXiv 2509.17995](https://arxiv.org/abs/2509.17995)
- **SFR-Judge, Table 11 (measured, 8B judges):** with negatives from the same strong teacher (Llama-3.1-70B) vs from a weaker teacher (Llama-3.1-8B), pairwise accuracy was 78.83 vs 77.56 and pairwise consistency 85.94 vs 80.70. — [SFR-Judge, arXiv 2409.14664](https://arxiv.org/abs/2409.14664)
- **Off-policy training still helps on other models' candidates:**
  - J1-Llama-8B, trained on Llama-generated pairs, went from 54.7 to 59.2 on PPE-Correctness, where candidates come from other models. — [J1](https://arxiv.org/abs/2505.10320)
  - RRM-7B picking from "the same 32 response candidates provided by PPE" scored 66.8 vs 55.8 for Skywork-Reward-Gemma-2-27B and 56.0 for GPT-4o. — [RRM](https://arxiv.org/abs/2505.14674)
- **Aggregator generalization claims:** AggLM "generalizes effectively to solutions from differing models, including stronger ones than contained in the training data" ([AggLM, arXiv 2509.06870](https://arxiv.org/abs/2509.06870)). SSA generalizes "across sample set sizes, base model families and scales, and tasks" ([SSA, arXiv 2506.09014 (abstract)](https://arxiv.org/abs/2506.09014)).

### Inferences
- **Our failure mode is the case where off-policy data should help least.** The errors come from a strong generator, and several samples agree on them. Negatives from weaker models are "easiest to judge" (Principia, Variation) and train less consistent judges (SFR-Judge). The best-supported data source is on-policy sampling from our own agent, same model and same tool loop, on non-Spider2 databases, plus synthetic near-misses.
- **The PairJudge pattern is consistent with an on-policy advantage but confounded.** The training generator had the lowest baseline, so it also had the most headroom. Treat it as suggestive only.
- **On-policy data goes stale.** If the generator or agent scaffold changes, for example a new model or new describe_table enrichment, regenerate the pairs. Principia's mechanism is a change in the response distribution.
- **Generator-verifier gap.** A roughly 9B dense judge selecting among Qwen3.6-35B-A3B agent outputs may land in the "no gain" regime Principia saw for self-judging at 1.7B. Before investing in training, measure the 9B model's own solve rate on held-out non-Spider2 questions; per Variation, verification tracks solving ability.
- **Off-policy public data has a role.** Pairs like J1's or RRM's could warm-start general judging skill, but the 11–12-question gap probably needs on-policy hard pairs.

### Gaps
- I found no study that holds a candidate pool fixed and measures BoN selection accuracy for on-policy vs off-policy judge training data. Principia measured downstream RL instead.
- It is unknown how "on-policy" the data must be: same weights, same family, or same agent scaffold.

## Q4. Position bias: training-time remedies and their measured effect

### Takeaway
Three training-time remedies come with numbers: (a) both presentation orders in the data (swap augmentation); (b) a reward for a correct verdict in both orders (J1); (c) pointwise or multitask judges whose verdict cannot depend on order. Each reduces order dependence but none removes it. The best 8B J1 variant still flips its verdict on about 29% of PPE-Correctness pairs. Order bias is strongest when candidates are close in quality, which describes our hard SQL pairs, so judging in both orders at inference (as we already do) remains necessary.

### Cited Findings
- **J1, Table 8 (Pairwise-J1 8B), measured.** PPE-Correctness values are acc(a,b) / acc(b,a) / position-consistent acc / verdict-flip %:

  | Variant | PPE-Correctness | JudgeBench (flip/ties %) |
  |---|---|---|
  | Base Llama-3.1-8B-Instruct | 54.7 / 54.1 / 30.2 / 44.1 | 67.4 / 42.3 / 32.3 / 37.4 |
  | Random single-order data | 58.3 / 57.6 / 38.3 / 36.7 | 48.3 / 59.4 / 36.6 / 32.9 |
  | Both-order data | 59.2 / 58.4 / 39.1 / 36.8 | 63.1 / 51.4 / 42.0 / 27.7 |
  | + verdict-consistency reward | 58.4 / 58.2 / 43.9 / 28.7 | 52.3 / 64.6 / 45.4 / 26.0 |

  The consistency reward is "+1 only if the model produces the correct verdict for both input orderings", and both orderings sit in the same batch. — [J1, arXiv 2505.10320](https://arxiv.org/abs/2505.10320)
- **J1, Table 3 (pairwise vs pointwise, PPE-Correctness).** Values are position-consistent accuracy / flips (pairwise) or ties (pointwise):

  | Model | Pairwise | Pointwise |
  |---|---|---|
  | J1-Llama-70B | 61.2 / 21.9 | 65.0 / 13.7 |
  | J1-Qwen-32B | 65.2 / 14.5 | 69.3 / 13.0 |
  | J1-Qwen-32B-MultiTask | 67.0 / 17.0 | 70.6 / 10.5 |

  Pointwise judges "lack the context of reference candidates… and hence are more prone to ties". Sampling more verdicts raises position-consistent accuracy and lowers the tie rate. — [J1](https://arxiv.org/abs/2505.10320)
- **JudgeLM swap augmentation, 7B with 3.5K data (measured):** agreement 75.87 → 76.51; consistency 73.45 → 78.89; bias toward the first position 19.83 → 15.34; toward the second 6.72 → 5.77; delta bias 13.11 → 9.57. Data scaling at 7B from 3.5K to 100K raised consistency from 73.45 to 82.62. — [JudgeLM, arXiv 2310.17631](https://arxiv.org/abs/2310.17631)
- **Other recipes that build in both orders:**
  - EvalPlanner generates plan executions in both orders and builds chosen/rejected pairs for both, "ensuring that the model becomes position-consistent". — [EvalPlanner](https://arxiv.org/abs/2501.18099)
  - Self-Taught Evaluator randomizes the winner's position, which is "important to deal with position bias". — [STE](https://arxiv.org/abs/2408.02666)
  - DeepSeek-GRM shuffles responses before sampling. — [DeepSeek-GRM](https://arxiv.org/abs/2504.02495)
- **SFR-Judge:** more consistent than GPT-4o-mini, Skywork-Critic-8B and Llama-3-OffsetBias by at least 5.37, 3.21 and 7.40 points. Hard same-model negatives added +5.24 consistency (Q7). — [SFR-Judge](https://arxiv.org/abs/2409.14664)
- **JudgeBench scoring:** inconsistent verdicts across the two orders are scored as incorrect. "JudgeLM-7B and JudgeLM-13B were inconsistent on 59.71% and 54.57% of pairs". — [JudgeBench](https://arxiv.org/abs/2410.12784)
- **Judging the Judges:** 15 judges and more than 150K instances. Position bias "is weakly influenced by the length of prompt components, [but] strongly affected by the quality gap between solutions". — [arXiv 2406.07791](https://arxiv.org/abs/2406.07791)
- **Size of the effect:** with ChatGPT as evaluator, reordering alone let Vicuna-13B beat ChatGPT on 66 of 80 queries. Balanced Position Calibration, which aggregates over both orders, is the inference-time fix. — [LLMs are not Fair Evaluators, arXiv 2305.17926 (abstract)](https://arxiv.org/abs/2305.17926)
- **Thinking helps consistency:** in a study of small Qwen3 judges (0.6–4B), thinking models were about 6% more consistent under positional, bandwagon, identity and other bias conditions. — [Explicit Reasoning Makes Better Judges, arXiv 2509.13332 (abstract)](https://arxiv.org/abs/2509.13332)
- **Pairwise protocols are more sensitive to distractor features:** pairwise preferences flipped in about 35% of cases vs 9% for absolute scores. — [Pairwise or Pointwise?, arXiv 2504.14716 (abstract)](https://arxiv.org/abs/2504.14716)

### Inferences
- **Our hard pairs are the high-bias regime.** Two plausible SQL queries from the same model, with similar style and a small "quality gap", are where position bias is largest. Train with both orders in the same batch plus J1's consistency reward. A multitask pointwise+pairwise judge (J1-MultiTask) is worth trying because it had the best position-consistent accuracy.
- **Treat order-inconsistent results as ties, not half-wins.** Keep both-order inference, but break ties with another signal: pointwise score, sampled-verdict average or an execution probe. With 1 correct of 4, a single flipped match can change the winner.
- **Track position-consistent accuracy.** Use it (JudgeBench's metric) on held-out on-policy pairs as the primary judge metric during training, not single-order accuracy.

### Gaps
- No measurement of these remedies on pairs whose inputs include tabular execution previews.
- No study found that compares the consistency reward against swap augmentation at the 9B scale with pairs from a code/SQL-like domain beyond J1's PPE/JudgeBench.

## Q5. How much data? Can 7–9B judges improve best-of-N? Diminishing returns? Distilling a thinking judge into a fast non-thinking one?

### Takeaway
Strong generative judges are usually trained on 10–25K verifiable or synthetic pairs: J1 22K, EvalPlanner 22K, Principia 18.8K, and RM-R1 8.7K distillation plus 64K RL. Returns flatten quickly within one training round (EvalPlanner: 5K → 22K added +0.2), while a second self-training round added more. Long-CoT verifiers are very data-efficient (ThinkPRM: 1K CoTs). SFT judges keep improving to 100K (JudgeLM). Judges of 7–9B do improve BoN in math and code. However, verification ability tracks the verifier's own solving ability, and a judge trained to judge its own weak outputs gained nothing. I found no study that distills a thinking pairwise judge into a non-thinking one and reports BoN. Nearby evidence: non-thinking judges lose about 10 points in small Qwen3 models, and verdict-only training recovers only part of what CoT plus preference optimization gives. Distilling a verifier ensemble into a 400M classifier kept about 98% of its accuracy.

### Cited Findings
- **Data sizes reported:**
  - J1: 22K pairs. — [J1](https://arxiv.org/abs/2505.10320)
  - EvalPlanner: about 22K; DPO iteration 1 with 5K pairs scored 92.3, with 22K pairs 92.5, and 2 iterations (5K + 17K) 93.9 on RewardBench. — [EvalPlanner](https://arxiv.org/abs/2501.18099)
  - RM-R1: 8.7K distillation and 64K RLVR, "compared to the 800K examples used in training DeepSeek-Distilled". — [RM-R1](https://arxiv.org/abs/2505.02387)
  - Principia: 18,774 examples. — [Principia](https://arxiv.org/abs/2603.18886)
  - PairJudge: 432K. — [PairJudge](https://arxiv.org/abs/2501.13007)
  - RRM: about 420K. — [RRM](https://arxiv.org/abs/2505.14674)
  - SFR-Judge: 680K. — [SFR-Judge](https://arxiv.org/abs/2409.14664)
  - JudgeLM: 100K. — [JudgeLM](https://arxiv.org/abs/2310.17631)
  - GenPRM: 23K. — [GenPRM, arXiv 2504.00891 (abstract)](https://arxiv.org/abs/2504.00891)
  - ThinkPRM: 1K CoTs / 8K step labels. — [ThinkPRM](https://arxiv.org/abs/2504.16828)
  - DeepSeek-GRM: "1270K judge data" for fine-tuning plus RL on 237K samples, as reported by J1, whose 22K-pair J1 beat it on PPE-Correctness (59.8 → 76.8 at 27B vs 32B). — [J1](https://arxiv.org/abs/2505.10320)
  - Skywork-Reward-V2: 26M curated pairs out of 40M. "Effectiveness stems not only from data scale but also from high-quality curation". — [Skywork-Reward-V2, arXiv 2507.01352 (abstract)](https://arxiv.org/abs/2507.01352)
- **JudgeLM data scaling (measured).** Agreement / consistency at 3.5K, 10K, 30K and 100K training samples:

  | Model | 3.5K | 10K | 30K | 100K |
  |---|---|---|---|---|
  | 7B | 75.87 / 73.45 | 78.89 / 78.25 | 81.43 / 80.89 | 83.71 / 82.62 |
  | 33B agreement | 85.38 | – | – | 90.06 |

  — [JudgeLM](https://arxiv.org/abs/2310.17631)
- **Cobbe:** verifiers "scale significantly better with increased data than a finetuning baseline", but "once we use a sufficiently large dataset, we see a strong boost from verifiers". With small training sets, verification is not better. — [Cobbe et al.](https://arxiv.org/abs/2110.14168)
- **Data efficiency of long-CoT verifiers:** "ThinkPRM-14B, trained on 8K process labels or 1K synthetic examples, outperforms discriminative PRMs trained on about 100x more data". Out of domain it beat discriminative verifiers trained on all of PRM800K by 8% on a GPQA-Diamond subset and 4.5% on a LiveCodeBench subset. — [ThinkPRM](https://arxiv.org/abs/2504.16828)
- **Small (≤9B) judges improving BoN (measured):**
  - PairJudge, Qwen2.5-7B: MATH-500 average 73.0 vs majority 69.4. — [PairJudge](https://arxiv.org/abs/2501.13007)
  - RRM-7B: BoN over 32 PPE candidates 66.8 (MATH 82.0) vs Skywork-Reward-Gemma-2-27B 55.8 and GPT-4o 56.0; 68.2 with voting@5. — [RRM](https://arxiv.org/abs/2505.14674)
  - J1-Llama-8B: PPE-Correctness 59.2. — [J1](https://arxiv.org/abs/2505.10320)
  - GenRM, Gemma2-9B: GSM8K BoN raised problems solved from 73% to 93.4% on Gemini 1.0 Pro solutions. — [GenRM](https://arxiv.org/abs/2408.15240)
  - AceCode-RM-7B: +10 / +5 points with best-of-32. — [AceCoder](https://arxiv.org/abs/2502.01718)
  - GenRM-FT, Llama-3.1-8B: up to 30% relative over self-consistency on the hardest MATH problems. — [When To Solve, When To Verify, arXiv 2504.01005](https://arxiv.org/abs/2504.01005)
  - SSA-3B beats reranking with a 72B PRM. — [SSA](https://arxiv.org/abs/2506.09014)
  - AggLM-1.7B (Q6). — [AggLM](https://arxiv.org/abs/2509.06870)
  - TIR-Judge-8B. — [TIR-Judge](https://arxiv.org/abs/2510.23038)
- **Limits for small judges:**
  - Verification ability is "correlated with the verifier's own problem-solving capability", and on hard problems the relationship is "threshold-limited". — [Variation in Verification](https://arxiv.org/abs/2509.17995)
  - J1 training on Qwen3-1.7B, judging its own outputs, gave no improvement, against +10% absolute on Qwen3-32B. — [Principia](https://arxiv.org/abs/2603.18886)
- **Thinking vs non-thinking judges (measured):**
  - Small Qwen3 judges (0.6–4B) on RewardBench: thinking gives "approximately 10% points higher accuracy with little overhead (under 2x)". Augmenting non-thinking models, e.g. few-shot, gives "modest gains at a higher cost (>8x)". — [Explicit Reasoning Makes Better Judges, arXiv 2509.13332 (abstract)](https://arxiv.org/abs/2509.13332)
  - EvalPlanner with the same data: trained without thoughts 86.2; SFT with thoughts 86.8; SFT + DPO with thoughts 90.5 (seed 84.0). — [EvalPlanner](https://arxiv.org/abs/2501.18099)
  - GenRM: CoT verifiers "can outperform discriminative and direct verifiers". — [GenRM](https://arxiv.org/abs/2408.15240)
- **Distilling slow verifiers into fast ones (measured):**
  - Weaver distilled a weighted ensemble of verifiers up to 70B into a 400M cross-encoder that "retains 98.7% of Weaver's full accuracy while reducing verification compute by up to 99.97%". Elsewhere the paper says 98.2% of the accuracy gains. — [Weaver](https://arxiv.org/abs/2506.18203)
  - Self-Calibration distills confidence derived from self-consistency into a single forward pass. Confidence-based early stopping for BoN raised MathQA from 81.0 to 83.6 at a 16-sample budget. — [Self-Calibration, arXiv 2503.00031 (abstract)](https://arxiv.org/abs/2503.00031)
- **Risk of non-thinking distilled judges:** judges trained from a gold judge's labels without reasoning were easily reward-hacked when used for RL. — [arXiv 2603.12246 (abstract)](https://arxiv.org/abs/2603.12246)

### Inferences
- **Plan for about 10–25K on-policy pairs in the first round.** That is where J1 and EvalPlanner saturate. Spend the budget on label quality (consensus filtering, both orders) and on a second on-policy round (EvalPlanner: +1.4 from iteration 2) rather than raw volume. Pairs come from distinct-answer pools of 4 samples per question across many non-Spider2 questions.
- **Small judges can work, but the capability gap is the risk.** Our hard cases require the judge to know the right grain or denominator, which means solving the question. Before training, measure the 9B base model as a solver and as a zero-shot judge on held-out non-Spider2 pools. If its solve rate is far below the 35B agent's, Variation and Principia predict limited gains.
- **Two paths from thinking to fast.**
  - (a) Keep a short-CoT 9B judge trained with GRPO, which has the most evidence.
  - (b) Distill the 35B thinking judge's soft labels into a pointwise or pairwise classifier, averaging the labels over both orders and several samples (Weaver-style). This is cheap, but non-thinking judges lose accuracy (about 10 points at small scale) and are easier to hack. Expect (b) to lose most on the near-miss pairs we care about, and validate on the "1 correct vs 2–3 wrong" slice specifically.

### Gaps
- No direct BoN measurement of a distilled non-thinking pairwise judge against its thinking teacher.
- No data-scaling curve found for GRPO-trained pairwise judges beyond the 5K vs 22K points from EvalPlanner (DPO) and J1's single 22K setting.

## Q6. When do trained verifiers beat self-consistency, especially when the correct answer is a minority? Known failures (false positives growing with N, reward hacking, overconfidence)

### Takeaway
Learned selection beats majority voting by single-digit points at moderate N in math and code:
- PairJudge: +3.6 on MATH-500
- GenSelect: +3.7 on competition math
- AggLM: +5 on AIME25
- Weaver: +13.5 averaged over its tasks

Gains concentrate on hard problems and diverse candidate sets. Self-consistency is more compute-efficient at small budgets: a generative verifier needs up to 8× the compute to match it. Recovering minority-correct answers requires training on groups where the majority is wrong (AggLM). The failure modes are well documented:
- Verifier BoN peaks and then declines as N grows, because false positives accumulate.
- Generative judges can be fooled by superficial tokens.
- Off-distribution RMs can fall below majority voting.
- Errors are increasingly correlated across capable models, and judges favor similar models.
- Judges are overconfident.

The usual calibration fix is to sample several verdicts and average them.

### Cited Findings
**Gains over majority / self-consistency (measured)**
- **PairJudge + knockout vs majority voting:** MATH-500 average 73.0 vs 69.4; OlympiadBench average 33.9 vs 32.8. It is not uniformly better: with Llama-3.1-70B at @16 on Olympiad, PairJudge scored 33.9 vs majority 35.6. — [PairJudge](https://arxiv.org/abs/2501.13007)
- **GenSelect (Comp-Math-24-25, 256 problems, QwQ-32B solutions):**

  | Method | Accuracy |
  |---|---|
  | pass@64 (oracle) | 85.2 |
  | majority@64 | 68.4 |
  | Qwen2.5-Math-RM-72B | 66.8 |
  | QwQ GenRM (pointwise) | 69.1 |
  | QwQ GenSelect@1 | 72.1 |
  | QwQ GenSelect@8 | 73.4 |

  Compute-matched, comparing N generations + N GenSelect calls against 2N generations + majority:
  - QwQ-32B, N=4: 69.5 vs 66.4; N=16: 71.9 vs 68.0.
  - DeepSeek-R1-0528, N=4: 82.4 vs 82.8 (no gain); N=16: 87.1 vs 84.4.

  — [GenSelect, arXiv 2507.17797](https://arxiv.org/abs/2507.17797). GenSelect "becomes unstable when using more than 32 generations" in one prompt. — [AIMO-2](https://arxiv.org/abs/2504.16891)
- **AggLM:** on AIME25 with Qwen3-1.7B solutions, single-sample accuracy is 35%, majority 45% and the AggLM-1.7B aggregator 50%. It beats 72B reward-model selection baselines. "Gains over majority voting are particularly substantial when the majority answer set is small". "Majority-based aggregation… fails when correct solutions exist but are confined to minority modes". — [AggLM, arXiv 2509.06870](https://arxiv.org/abs/2509.06870)
- **SSA:** +8% pass@5 over naive majority voting on MATH; the 3B SSA beats a 72B PRM reranker. — [SSA (abstract)](https://arxiv.org/abs/2506.09014)
- **Weaver:** +13.5% over majority voting and +17.1% over unweighted verifier averaging. "Many standard verification baselines (e.g. majority voting) quickly plateau". — [Weaver](https://arxiv.org/abs/2506.18203)
- **SC vs GenRM under fixed compute:** "SC outperforms GenRM at lower budgets, using up to 8× less compute, while GenRM excels at higher budgets". On the hardest MATH problems, GenRM-FT gives up to 30% relative improvement over SC. Claim: compute-optimal inference scales solutions faster than verifications. — [When To Solve, When To Verify](https://arxiv.org/abs/2504.01005)
- **GenRM-CoT:** beats self-consistency on its algorithmic and math tasks. The two are complementary via weighted self-consistency, and summing only each answer's top-K verifier scores "slightly improves performance". — [GenRM](https://arxiv.org/abs/2408.15240)
- **Heimdall:** RL raised verification accuracy on competition math from 62.5% to 94.5%, and to 97.5% with repeated sampling. "Pessimistic Verification" raised AIME2025 from 54.2% to 70.0% with 16× compute and to 83.3% with more. — [Heimdall, arXiv 2504.10337 (abstract)](https://arxiv.org/abs/2504.10337)
- **Comparing candidates helps:** "Comparing across responses provides helpful signals about the locations of errors". Separately, frontier models "demonstrate remarkably weak out-of-box verification". — [Sample, Scrutinize and Scale, arXiv 2502.01839 (abstract)](https://arxiv.org/abs/2502.01839)
- **Universal Self-Consistency:** an LLM picking the "most consistent" candidate matches self-consistency on math and execution-based voting on code. — [USC, arXiv 2311.17311 (abstract)](https://arxiv.org/abs/2311.17311)
- **Execution-grounded pairwise selection beats LLM judging alone.** Pass@1 on LiveCodeBench v4 (N=8, average across four models):

  | Selection method | Avg pass@1 |
  |---|---|
  | Public tests only | 53.8 |
  | Generated tests | 53.1 |
  | LLM judge (pairwise) | 55.6 |
  | Adaptive distinguishing-input synthesis | 57.5 |

  "LLM-based judging alone often struggles to predict program behavior accurately". — [S*, arXiv 2502.14382](https://arxiv.org/abs/2502.14382)

**Failure modes (measured unless marked)**
- **BoN with a verifier peaks, then declines.** At 6B, "performance improves as we increase the number of completions up to 400… the benefits of search are eventually outweighed by the risk of finding adversarial solutions that fool the verifier". — [Cobbe et al.](https://arxiv.org/abs/2110.14168)
- **Imperfect verifiers cap accuracy.** A verifier with a non-zero false-positive rate imposes "an upper bound to the accuracy of resampling-based inference scaling". The false-positive rate correlates strongly with the model's single-sample accuracy (HumanEval/MBPP), and "optimal sampling attempts are often fewer than 10". — [The Limits of Inference Scaling Through Resampling, arXiv 2411.17501 (abstract)](https://arxiv.org/abs/2411.17501)
- **Selection plateaus with N:** majority voting and reward models "plateau beyond several hundred samples". — [Large Language Monkeys, arXiv 2407.21787 (abstract)](https://arxiv.org/abs/2407.21787)
- **Inference-time reward hacking.** The rise-then-fall of true reward is "an inevitable property of a broad class of inference-time mechanisms, including BoN". The authors propose hedging (HedgeTune). — [Inference-Time Reward Hacking, arXiv 2506.19248 (abstract)](https://arxiv.org/abs/2506.19248)
- **Superficial "master key" inputs** give false-positive rates "as high as 80%", including on GPT-o1 and Claude-4. — [One Token to Fool LLM-as-a-Judge](https://arxiv.org/abs/2507.08794)
- **Model-based verifiers are hackable during RL,** "particularly after fine-tuning". — [Rule- and Model-based Verifiers, arXiv 2505.22203 (abstract)](https://arxiv.org/abs/2505.22203)
- **Off-distribution RMs** can fall below majority voting (Qwen2.5-Math-RM-72B 66.8 vs majority 68.4, above). — [GenSelect](https://arxiv.org/abs/2507.17797)
- **Correlated errors.** "LLM-as-a-judge scores favor models similar to the judge", and "model mistakes are becoming more similar with increasing capabilities". — [Great Models Think Alike, arXiv 2502.04313 (abstract)](https://arxiv.org/abs/2502.04313)
- **Hard same-model pairs are close to random for strong judges:** GPT-4o performs "just slightly better than random guessing". — [JudgeBench](https://arxiv.org/abs/2410.12784)
- **Correct answers with flawed processes** inflate BoN scores for PRMs. — [Qwen Lessons](https://arxiv.org/abs/2501.07301)

**Overconfidence and calibration**
- **Judges are overconfident:** an "Overconfidence Phenomenon… where predicted confidence significantly overstates actual correctness". The proposed ensemble ("LLM-as-a-Fuser") improves calibration (claim). — [Overconfidence in LLM-as-a-Judge, arXiv 2508.06225 (abstract)](https://arxiv.org/abs/2508.06225)
- **LLMs in general:** "LLMs are known to be overconfident". — [Self-Calibration](https://arxiv.org/abs/2503.00031)
- **Counterpoint:** reasoning models express verbalized confidence that is better calibrated than non-reasoning models in 33 of 36 settings. That concerns verbalized confidence on QA, not verdict-token probabilities. — [Reasoning Models Better Express Their Confidence, arXiv 2505.14489 (abstract)](https://arxiv.org/abs/2505.14489)
- **Fixes that produce graded scores:**
  - GenRM-CoT averages P(Yes) across several sampled rationales. — [GenRM](https://arxiv.org/abs/2408.15240)
  - DeepSeek-GRM: greedy 69.9 → voting@8 70.6 → voting@32 71.0 → meta-RM-guided voting@32 72.8. — [DeepSeek-GRM](https://arxiv.org/abs/2504.02495)
  - Heimdall's repeated sampling raised accuracy from 94.5 to 97.5. — [Heimdall](https://arxiv.org/abs/2504.10337)
  - "Simulated Annotators" improve judge calibration. Cascaded selective evaluation that escalates when confidence is low guarantees >80% human agreement at about 80% coverage using models such as Mistral-7B. — [Trust or Escalate, arXiv 2407.18370 (abstract)](https://arxiv.org/abs/2407.18370)
  - JudgeLRM includes a confidence term in its reward. — [JudgeLRM](https://arxiv.org/abs/2504.00050)
- **J1's verdicts are nearly deterministic:** greedy decoding and temperature 0.6 over 8 seeds give the same accuracy within ±0.1 (72.9 vs 72.8±0.1; 76.8 vs 77.0±0.1). — [J1](https://arxiv.org/abs/2505.10320)

### Inferences
- **We are in the small-N regime.** With N=4 and 94/135 coverage, self-consistency is strong and the remaining gap (11–12 questions) is mostly minority-correct cases. This is exactly AggLM's "hard" group, and AggLM shows it is learnable only if training oversamples majority-wrong groups. Build the training set around on-policy pools where the agent's majority answer is wrong and a minority answer is right.
- **The wrong-majority failures are probably correlated errors, not vote-following.** The judge sees distinct answers, so it cannot count votes unless vote counts are in its prompt. The more likely mechanism is that the judge, from the same model family, shares the generator's misreading of grain or denominator (Great Models Think Alike). Two levers follow: (a) on-policy training on exactly those misreadings; (b) judge diversity, such as JEV-27B on a different base, combined with learned weights rather than an unweighted vote (Weaver).
- **Do not raise N to compensate.** With imperfect judges, false positives accumulate as N grows (Cobbe; Limits of Resampling). Improve the judge before increasing N.
- **Our near-0/1 verdict probabilities are expected.** After a long CoT, the verdict token is effectively decided (J1's ±0.1 sampling variance). Graded confidence should come from several sampled verdicts across both orders (GenRM, DeepSeek-GRM), or from a pointwise head. Use it to abstain or escalate to a fallback such as the majority answer or a second judge when confidence is low (Trust or Escalate).
- **Execution-grounded discrimination is the strongest non-SQL lever** (S* adaptive inputs; CodeT; MBR-exec). For SQL this means letting the judge run discriminating probe queries, for example "is the result unique at the stated grain?", "does this join duplicate rows?" or "how many rows tie at the cutoff?". TIR-Judge shows judges can be RL-trained to call an executor.

### Gaps
- No non-SQL study isolates the regime of N=4 with one correct candidate against two or three agreeing wrong ones. I did not extract AggLM's numeric breakdown by majority-set size.
- No study found of how well verdict-token probabilities from thinking pairwise judges are calibrated.

## Q7. Hard-negative curricula: mining and constructing the hardest negatives; does training on near-misses help?

### Takeaway
In this literature the hardest negatives are mostly mined: same strong model, mixed-correctness prompts, majority-wrong groups, programs that pass some tests. Few are constructed. The one direct ablation (SFR-Judge) shows that negatives from the same strong model beat weaker-model negatives, by 1.3 points of accuracy and 5.2 points of order consistency. AggLM shows that hard-only training is worse than hard examples plus 5–50% easy ones. Constructed negatives (noisy instructions, truncations, adversarial policy outputs, human-inserted bugs) fix specific failure modes, such as cutting master-key false positives to near zero, but are not drawn from natural errors. I found no ablation of easy-to-hard ordering (a true curriculum) for judges.

### Cited Findings
- **SFR-Judge, Table 11 (8B judges, DPO).** "Hard" pairs take both responses from Llama-3.1-70B; "easy" pairs take the negative from Llama-3.1-8B:

  | Metric | Hard pairs | Easy pairs |
  |---|---|---|
  | Pairwise accuracy | 78.83 | 77.56 (−1.27) |
  | Pairwise consistency | 85.94 | 80.70 (−5.24) |
  | Pearson | 0.68 | 0.67 |
  | Classification accuracy | 85.48 | 84.54 |

  "Across all metrics, training with harder preference samples results in better performance". — [SFR-Judge, arXiv 2409.14664](https://arxiv.org/abs/2409.14664)
- **AggLM:** an example is "hard if the majority answer… is wrong". The authors keep all hard examples and vary the share of easy ones from 0% (hard-only) to 270% (all easy kept). "Incorporating a moderate proportion of easy sets (5–50%) consistently enhances accuracy, and results are stable within this range". Training only on hard groups "makes rewards sparse". — [AggLM](https://arxiv.org/abs/2509.06870)
- **AceCoder** requires the rejected program to pass some tests (s_j > 0) and the chosen one to pass more than 80% with a gap above 0.4. This keeps partially passing near-miss negatives and drops trivially broken ones. — [AceCoder](https://arxiv.org/abs/2502.01718)
- **Mixed-correctness filters** (keep only prompts with ≥1 correct and ≥1 incorrect candidate) are used by PairJudge, GenSelect, RRM and JudgeBench. — [PairJudge](https://arxiv.org/abs/2501.13007); [AIMO-2](https://arxiv.org/abs/2504.16891); [RRM](https://arxiv.org/abs/2505.14674); [JudgeBench](https://arxiv.org/abs/2410.12784)
- **Hardness tracks the generator.** Principia: "Responses from the weaker Llama model are easiest to judge, followed by Qwen3-1.7B, and Qwen3-8B" ([Principia](https://arxiv.org/abs/2603.18886)). Variation in Verification: errors from strong generators are harder to detect ([Variation](https://arxiv.org/abs/2509.17995)).
- **Constructed negatives:**
  - Truncated outputs make Master-RM robust (near-zero false positives vs up to 80%). — [Master-RM](https://arxiv.org/abs/2507.08794)
  - An RL-trained adversarial policy produces high-scoring bad outputs for retraining. — [Adv-RM](https://arxiv.org/abs/2504.06141)
  - Human-inserted bugs are "harder… and more severe… but… not from the natural distribution of model errors". — [CriticGPT](https://arxiv.org/abs/2407.00215)
  - Noisy-instruction negatives are used for Self-Taught Evaluator, J1 and EvalPlanner. — [STE](https://arxiv.org/abs/2408.02666); [J1](https://arxiv.org/abs/2505.10320); [EvalPlanner](https://arxiv.org/abs/2501.18099)
- **Near-equal quality maximizes position bias**, so hard negatives also stress order robustness. — [Judging the Judges](https://arxiv.org/abs/2406.07791)
- **Subtle-change pairs are where reward models fail:** RM-Bench state-of-the-art average is 46.6%. — [RM-Bench](https://arxiv.org/abs/2410.16184)
- **Label noise grows with hardness**, because subtle negatives are the most often mislabeled by automatic labelers. Consensus filtering keeps about 40% and helps. — [Qwen Lessons](https://arxiv.org/abs/2501.07301)

### Inferences
- **Mine three kinds of hard negatives from our own agent on non-Spider2 databases:**
  1. Questions with mixed correctness.
  2. Oversampled majority-wrong groups, keeping 5–50% easy groups (AggLM's ratio).
  3. "Partially correct" SQL that matches some gold columns or rows but fails one condition. This is the analog of AceCoder's s_j > 0 and maps onto wrong denominator, ties at the cutoff and overlapping status categories.
- **Construct negatives for each listed error type.** The types are grain, denominator, join fan-out, overlapping statuses, name-vs-ID key, answer shape, ties and formatting. Two routes: question perturbation (noisy-instruction method) and automated SQL tampering. Verify each by execution that its result differs from gold. Keep constructed negatives a minority relative to mined ones, because inserted errors are not natural (CriticGPT).
- **Iterate on the judge's own mistakes.** After round 1, collect the trained judge's errors on fresh on-policy pools and add them (the Self-Taught Evaluator / EvalPlanner iteration, Adv-RM idea). This is the closest supported approach to a curriculum.
- **Balance against shortcuts.** If most hard negatives return more rows, for example from fan-out, the judge may learn "fewer rows wins". Include hard negatives in both directions, such as an over-filtered SQL that returns too few rows.

### Gaps
- No ablation found of curriculum ordering (easy → hard) for judges, or of mined vs constructed negatives on BoN selection.
- SFR-Judge's hard-vs-easy experiment ran at "an earlier stage" of development, at 8B, with DPO only. No GRPO replication found.
