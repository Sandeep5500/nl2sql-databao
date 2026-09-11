# Spider2 Plan

**4 people · Sept–Dec 2026 · target: Spider 2.0-Lite leaderboard**

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
