# Synthetic text-to-SQL training data: generation pipelines and label quality, and what transfers to a pairwise SQL judge

Scope: automated pipelines that synthesize databases, questions, gold SQL and external knowledge, and how their labels are verified. Dataset catalogues and selector/judge training are covered by other researchers. "Measured" means a number the paper reports from an experiment or audit. "Claimed" means the authors' characterization. Spider 2.0-SQLite / Spider 2.0-lite sqlite results below are on the same 135 local questions we use, so 1 question ≈ 0.74 points.

---

## Q1. How OmniSQL / SynSQL-2.5M builds databases, tiered SQL, styled questions and CoT, and how its top tier compares with Spider 2.0 SQL

### Takeaway
SynSQL-2.5M is a four-stage, SQL-first pipeline (web table → synthetic DB → complexity-tiered SQL → back-translated question in one of 9 styles → CoT re-derivation by 8-sample execution-majority vote). It was built only with open-weight LLMs and released under Apache-2.0. Two points matter for judge data. A human audit found 86% of samples fully correct. And each synthetic table holds only the two LLM-written sample rows, so execution checks and result previews on these DBs say little. The "highly complex" tier is CTE-heavy but short next to Spider 2.0: 57 tokens per SQL on average across all tiers, versus a Spider 2.0 average of 144 and a minimum of 50. Window functions appear in only about 1.3% of queries.

### Cited Findings
**Pipeline and databases**
- Four sequential steps: (1) web table-driven database synthesis, (2) complexity-aware SQL generation, (3) stylized question synthesis, (4) CoT solution synthesis. The README says you can start at any step, for example "if you already have databases, you can skip Step 1." — [OmniSQL data_synthesis README](https://github.com/RUCKBReasoning/OmniSQL/blob/main/data_synthesis/README.md)
- Seed tables: a 0.1% sample of TabLib, about 1,319,561 web tables. Filters: non-English removed; fewer than 5 columns or 5 rows removed; dedup by header; semantic screening by Qwen2.5-72B-Instruct. This leaves 19,935 tables, which become 16,583 databases after parse and creation failures. — [OmniSQL paper, arXiv 2503.02240](https://arxiv.org/html/2503.02240)
- Table count per DB is sampled from N(10, 4²). Before enhancement: 9.15 tables/DB and 4.86 columns/table. After a schema-enhancement pass: 10.15 tables/DB, 7.3 columns/table, 74.07 columns/DB. For comparison, Spider has 5.11 tables / 26.82 columns per DB and BIRD has 7.64 / 54.56. — [OmniSQL paper](https://arxiv.org/html/2503.02240)
- The schema prompt asks the LLM to name the table's domain, propose "a complex, enterprise-level, real-world business scenario", and emit a JSON schema. The schema includes table and column descriptions, PKs and FKs, "ultra-wide tables ... featuring 15-50 columns", deliberately abbreviated or non-descriptive column names "reflecting potential annotation inconsistencies", and **"two sample rows of data"** per table. — [schema_prompt.txt](https://github.com/RUCKBReasoning/OmniSQL/blob/main/data_synthesis/database_synthesis/prompt_templates/schema_prompt.txt)
- The SQLite builder creates the tables and inserts the `sample_rows` (row count = `len(sample_rows)`). A second "senior data analyst" prompt only adds columns. — [sqlite_schema_parser.py](https://github.com/RUCKBReasoning/OmniSQL/blob/main/data_synthesis/database_synthesis/sqlite_schema_parser.py); [enhance_prompt.txt](https://github.com/RUCKBReasoning/OmniSQL/blob/main/data_synthesis/database_synthesis/prompt_templates/enhance_prompt.txt)

**SQL generation and complexity control**
- Each SQL prompt contains:
  - the CREATE TABLE schema;
  - randomly sampled SQLite functions with descriptions;
  - INSERT statements built from `SELECT * ... LIMIT 2` per table, "to help generate predicates";
  - a complexity level drawn uniformly from {Simple, Moderate, Complex, Highly Complex};
  - "(Very important) Ensure the final SQL query selects {column_count} columns".

  It also asks for queries that "Address real-world data analysis needs. Avoid trivial or nonsensical queries." The script runs 300 prompts per DB. — [generate_sql_synthesis_prompts.py](https://github.com/RUCKBReasoning/OmniSQL/blob/main/data_synthesis/sql_synthesis/generate_sql_synthesis_prompts.py); [sql_synthesis_prompt.txt](https://github.com/RUCKBReasoning/OmniSQL/blob/main/data_synthesis/sql_synthesis/prompt_templates/sql_synthesis_prompt.txt)
- The column count follows a geometric distribution (p = 0.6), which biases queries toward few output columns. — [OmniSQL paper](https://arxiv.org/html/2503.02240)
- Tier criteria (verbatim excerpts) — [generate_sql_synthesis_prompts.py](https://github.com/RUCKBReasoning/OmniSQL/blob/main/data_synthesis/sql_synthesis/generate_sql_synthesis_prompts.py):
  - Simple: "select data from a single table only ... No joins".
  - Moderate: joins, subqueries in SELECT/WHERE, GROUP BY aggregates, IN/BETWEEN/LIKE, HAVING.
  - Complex: "complex nested subqueries", "multiple types of joins, including self-joins", "window functions, such as ROW_NUMBER, RANK", "CTEs", "multiple aggregate functions".
  - Highly Complex: "multiple CTEs", "recursive CTEs", "Extensively uses advanced window functions", "UNION or UNION ALL", "advanced analytical functions". The example is a recursive employee-hierarchy CTE, plus two more CTEs, plus `SUM(...) OVER (PARTITION BY ... ORDER BY ...)`, about 30 lines.
- Post-processing: drop non-SELECT queries; execute to remove syntax errors and timeouts; keep one query per template (values masked). About 5M were generated and about 2.5M kept. — [OmniSQL paper](https://arxiv.org/html/2503.02240)
- Corpus statistics (Table 3), all tiers pooled:
  - joins per SQL: 1.75 (BIRD 0.94, Spider 0.48);
  - whitespace tokens per SQL: 57.05 (BIRD 24.75, Spider 14.85);
  - queries using window functions: 33,916; CTEs: 1,073,483 (about 40%); subqueries: 612,647; set operators: 363,472;
  - unique skeletons: 2,190,988; distinct functions: 83.
  - No per-tier statistics are reported.

  — [OmniSQL paper PDF](https://arxiv.org/pdf/2503.02240)

**Questions, styles and external knowledge**
- The 9 styles are Formal, Colloquial, Imperative, Interrogative, Descriptive, Concise, Vague ("ambiguous vocabulary requiring inference"), Metaphorical, and Multi-turn Dialogue. Each comes with a one-line definition and an example. — [generate_question_synthesis_prompts.py](https://github.com/RUCKBReasoning/OmniSQL/blob/main/data_synthesis/question_synthesis/generate_question_synthesis_prompts.py)
- The question prompt works in two steps: "Explain the SQL Query", then generate the question. It must capture "predicates, ORDER BY, and LIMIT clauses". Only Vague and Metaphorical styles add an external-knowledge (EK) step: "multiple entries separated by semicolons ... formulas, common sense, domain-specific knowledge, or extended context ... Each entry should be concise". Example: "'older students' refers to age >= 18". — [same file](https://github.com/RUCKBReasoning/OmniSQL/blob/main/data_synthesis/question_synthesis/generate_question_synthesis_prompts.py)
- Several candidate questions are generated per SQL. The candidate closest to the semantic centroid is kept (highest mean cosine similarity under all-mpnet-base-v2). — [OmniSQL paper](https://arxiv.org/html/2503.02240)

**CoT synthesis, which also re-labels the gold**
- The CoT prompt passes the synthetic SQL as "a reference solution from a colleague, which may or may not be correct". It warns that the reference may contain "Unnecessary table and column selections", "Incorrect or excessive joins", or "Misalignment with the question". — [cot_synthesis_prompt_template.txt](https://github.com/RUCKBReasoning/OmniSQL/blob/main/data_synthesis/cot_synthesis/prompt_templates/cot_synthesis_prompt_template.txt)
- The pipeline samples 8 responses at temperature 0.8, groups them by execution result, and keeps one from the largest group. GPT-4o preferred the post-CoT SQL over the original in 4,699 of 5,000 cases (93.98%). — [OmniSQL paper](https://arxiv.org/html/2503.02240)

**Teachers, quality, scale and license**
- Teachers: a pool of Llama 3.1, DeepSeek Coder, Qwen2.5 and Qwen2.5-Coder models; "Larger models are assigned a greater share of the synthesis workload". No per-step model is named. — [OmniSQL paper](https://arxiv.org/html/2503.02240). The README says the data was "generated entirely using open-source LLMs and released under Apache 2.0". — [OmniSQL README](https://github.com/RUCKBReasoning/OmniSQL)
- Human audit (measured): three senior graduate students rated 1,000 samples pass/fail. Results: 96% of DBs realistic, 97% of questions meaningful, 89% of SQL appropriate, **86% of samples fully correct**. The authors call this "silver-standard". A GPT-4o judge preferred SynSQL over BIRD on "nearly all criteria" (1,000 samples each; per-criterion numbers appear only in a figure). — [OmniSQL paper](https://arxiv.org/html/2503.02240)
- Size: 2,544,390 samples, 2,412,915 unique SQL, 16,583 DBs, 9.72 GB, Apache-2.0, English and SQLite only. — [SynSQL-2.5M card](https://huggingface.co/datasets/seeklhy/SynSQL-2.5M); [OmniSQL paper](https://arxiv.org/html/2503.02240)
- Cost: no synthesis cost or GPU-hours are reported. Fine-tuning took about 6 / 12 / 20 days for 7B / 14B / 32B on 8×A800-80GB. — [OmniSQL paper](https://arxiv.org/html/2503.02240)

**Spider 2.0 reference points**
- Spider 2.0 SQL averages 144 tokens, and annotation required queries of more than 50 tokens. DBs needed more than 200 columns or nested schemas, averaging 812 columns. Token-length difficulty bands: Easy <80 tokens (25.32%), Medium 80–160 (44.15%), Hard ≥160 (30.54%). 85.98% of queries use advanced dialect functions, and 82 tasks (12.97%) come with documentation. — [Spider 2.0 paper, arXiv 2411.07763](https://arxiv.org/abs/2411.07763)
- The OmniSQL paper gives no Spider 2.0 SQL or DB statistics in its comparison tables. — [OmniSQL paper](https://arxiv.org/html/2503.02240)

### Inferences
- **The top tier is roughly Spider 2.0's "easy" band.** The pooled SynSQL average (57 whitespace tokens) sits near Spider 2.0's 50-token floor and well under its 144-token mean. Tokenizers differ, so this is approximate. The highly-complex tier is longer than the pool average, but per-tier numbers are not published.
- **Ranking, ties and windowing are under-represented.** Window functions appear in 33,916 / 2.54M ≈ 1.3% of queries, even though the Complex and Highly Complex criteria list them. CTEs and subqueries dominate the "complex" part. Ties-at-cutoff and ranked-list-vs-single-row errors (two of our target error types) will be rare.
- **Two-row tables make execution nearly uninformative for our error types.** Wrong grain, join fan-out, keying on a non-unique name, overlapping categories and ties all need multiple rows per entity to change the result. With two rows per table, a wrong query often returns the same rows as the gold or an empty set. Three consequences:
  - The 8-sample majority vote can't separate many semantically different SQL.
  - A judge trained on SynSQL result previews would see little signal.
  - SynSQL DBs would need re-populating before use for judge pairs. Arctic-Text2SQL-R1 did this for Gretel's DBs with GPT-4o-generated INSERTs; see Q2.
- **Majority-vote labels share the failure mode the judge must overcome.** Our misses are cases where 2–3 candidates agree on a wrong answer. Majority-vote gold is biased toward exactly those popular answers, so judge labels should not come from majority vote without an independent check (Q3).
- **Expected label noise.** About 14% of samples have some error by the human audit. Using SynSQL gold unfiltered as the "correct" side of a pair would mislabel on the order of 1 in 7 pairs.
- **Reusable as-is:** steps 2–4 run on our own (non-Spider-2.0) databases; the tier criteria; the "explain then ask" back-translation prompt; style-conditioned EK generation; centroid question selection.

### Gaps
- Per-tier statistics (tokens, CTE/window rates, joins) and the tier mix in the released data are not reported in the paper.
- The model used at each step and the workload proportions are not reported.
- I found no audit of the vague/metaphorical EK specifically.
- No contamination analysis against Spider 2.0 DBs was found. Domain overlap between TabLib-derived schemas and our 30 DBs is unmeasured.
- Per-sample field names could not be confirmed from the HF card (viewer unavailable). The prompt code implies EK is stored for vague/metaphorical samples.

---

## Q2. What the other pipelines contribute and which ideas are reusable

### Takeaway
Four ideas recur across these pipelines:
- SQL-first back-translation (SQL-Factory, SQLForge, ScienceBenchmark, RingSQL, Text2SQL-Flow, CodeS's SQL→Q direction, GAZP).
- Strong/weak model splits, where a strong model explores and a weak model expands or supplies errors (SENSE, SQL-Factory).
- Correctness by construction (RingSQL compiles SQL from templates).
- Execution-grounded filtering (all of them, at different strengths).

Recent RL work (Arctic-Text2SQL-R1, ReViSQL, SkyRL-SQL, SQL-R1) adds two findings: filtering and label verification of training data matter more than raw volume, and small difficulty-filtered sets suffice for RL. The BIRD team's SWE-SQL adds the most directly reusable negative generator: SQL-Rewind, which injects plausible errors into verified SQL and keeps a pair only if test cases tell them apart.

### Cited Findings
**SENSE (ACL 2024; Yang et al.)**
- Strong data: GPT-4 generates domain, schema, question and SQL together (question-first / joint) at an Easy/Medium/Hard level. The prompt tells it to avoid over-represented domains ("Education/Universities, Healthcare/Medical, Travel/Airlines, or Entertainment/Media") and gives two Spider-train few-shot examples. — [SENSE, arXiv 2408.03256](https://arxiv.org/abs/2408.03256)
- Synthetic set: 8,216 examples over 503 DBs, averaging 60.3 tokens and 1.13 JOINs. Compare Spider train (7,000 / 140 DBs / 0.54 JOIN) and BIRD train (9,428 / 69 DBs / 1.02 JOIN). — [SENSE](https://arxiv.org/abs/2408.03256)
- Weak data: a weak model (DeepSeek-Coder-1.3B, fine-tuned on the strong data) generates SQL. If its execution result equals the gold's it is a positive, otherwise a negative. Pairs train DPO (β = 0.2, lr 2e-6). — [SENSE](https://arxiv.org/abs/2408.03256)
- Results (measured):
  - SENSE-7B: Spider dev EX 83.2, Spider test 83.5, BIRD dev 51.8, BIRD test 59.3.
  - SENSE-13B: 84.1 / 86.6 / 55.5 / 63.4.
  - The weak-data DPO stage adds +1.9 (7B: 49.9→51.8), +2.6 (13B: 52.9→55.5) and +2.0 (Qwen variant: 50.5→52.5) BIRD dev.
  - On top of Spider+BIRD SFT, the GPT-4 synthetic data adds +1.3 BIRD dev (51.6→52.9) and +3.5 Spider dev TS (79.4→82.9) for CodeLLaMA-13B (Fig. 6).

  — [SENSE](https://arxiv.org/abs/2408.03256). The paper says data and models are released ([GitHub Yangjiaxi/Sense](https://github.com/Yangjiaxi/Sense)); I did not verify the license.

**SQL-Factory (PVLDB; arXiv 2504.14837)**
- Three agent teams:
  - Generation (exploration): GPT-4o at temperature 0.8.
  - Expansion (exploitation): Qwen2.5-Coder-14B at 0.8.
  - Management/Critic: Qwen2.5-Coder-14B at 0.3.

  Real schemas: TPC-DS, IMDB (1 DB, 21 tables), Spider and BIRD. The paper's extracted DB counts (69 Spider, 146 BIRD) don't match the public splits and should be checked. Generation is SQL-first: questions plus an "external knowledge explanation" are written afterwards by Qwen2.5-Coder-14B, using 5 retrieved BIRD/Spider exemplars. — [SQL-Factory](https://arxiv.org/html/2504.14837v5)
- Diversity control:
  - table complexity score = attributes + 2·referential degree + depth of the referential tree;
  - hybrid similarity = 0.6·token + 0.3·AST + 0.1·embedding, plus Vendi score;
  - the manager switches back to exploration when redundancy rises or executability falls.

  — [SQL-Factory](https://arxiv.org/html/2504.14837v5)
- Scale and cost (Table 1): TPC-DS 50k ($51.78), IMDB 40k ($18.47), Spider 130k ($42.16), BIRD 160k ($67.50). That totals about $180 for 380k queries, although the abstract says "over 300,000". The authors estimate all-GPT-4o would "approach $1000". — [SQL-Factory](https://arxiv.org/html/2504.14837v5)
- Downstream (measured, small models): Qwen2.5-Coder-1.5B goes Spider 69.2→76.5 and BIRD 28.6→40.9; LLaMA3.2-1B BIRD 11.3→31.4; DeepSeek-Coder-1.3B BIRD 20.3→38.3. The authors claim gains beat the official training data, which holds for most but not all rows. — [SQL-Factory](https://arxiv.org/html/2504.14837v5). Code and data are at [github.com/LJHzju/SQL-Factory](https://github.com/LJHzju/SQL-Factory); license not verified.

**SQLForge (ACL 2025 Findings; arXiv 2505.13725)**
- Reversed pipeline:
  1. A SQL Parser turns seed SQL into AST templates ("replaces non-keyword nodes with placeholders").
  2. Template enrichment does crossover of same-keyword subtrees.
  3. SQL Foundry generates new domains under a "conditional entropy constraint".
  4. A Schema Architect builds the schema to fit the SQL.
  5. A Question Reverse-Translator writes the question.

  The teacher is GPT-4. Seeds are about 18K Spider+BIRD train samples. Output is about 25K examples across more than 1,000 domains. — [SQLForge](https://arxiv.org/html/2505.13725v1)
- Results (CodeLlama-13B, LoRA): Spider dev 85.7, BIRD dev 59.8.
- Ablation (CodeLlama-7B, Spider dev / BIRD dev): Spider+BIRD alone 79.8 / 50.5 → with augmentation 84.4 / 56.9. SENSE-style direct augmentation gives 82.9 / 52.5.
- No human evaluation is reported. A motivating figure: direct GPT-4 generation at about 50 SQL tokens has an execution-failure rate of "about 14%". Release and license are not stated. — [SQLForge](https://arxiv.org/html/2505.13725v1)

**Gretel synthetic_text_to_sql (2024)**
- 105,851 records (100,000 train / 5,851 test) across 100 domains, about 23M tokens (about 12M of them SQL). Generated with Gretel Navigator; the underlying models are not disclosed.
- Labels: complexity labels (8 values, including subqueries, single/multiple joins, aggregation, window functions, set operations) and four task types (definition, retrieval, manipulation, analytics & reporting).
- Fields include `sql_context` (DDL plus data), `sql` and `sql_explanation`.
- Validation: sqlglot/sqlvalidator parsing, and GPT-4-as-judge on 1,000 samples against b-mc2/sql-create-context (+54.6% standards compliance, +34.5% SQL correctness, +8.5% instruction adherence). No human audit. Apache-2.0.

  — [Gretel card README](https://huggingface.co/datasets/gretelai/synthetic_text_to_sql/raw/main/README.md); [dataset page](https://huggingface.co/datasets/gretelai/synthetic_text_to_sql)
- Arctic-Text2SQL-R1 populated Gretel DBs with GPT-4o-generated INSERT statements. Adding the unfiltered pool hurt (BIRD dev 64.9→64.6, 14B). Keeping only items where at least 1 of 10 model samples was correct ("Gretel-Synth-Filtered", 11,811) gave 66.5. — [Arctic-Text2SQL-R1](https://arxiv.org/html/2505.20315)

**ScienceBenchmark (PVLDB 17, 2023–24)**
- Three real scientific DBs: CORDIS (19 tables / 82 columns), SDSS (6 / 61) and OncoMX (25 / 106).
- Four phases:
  1. Seeding: AST templates from 100 expert NL/SQL pairs per domain.
  2. SQL generation: templates filled by sampling DB content.
  3. SQL-to-NL: GPT-3 fine-tuned on 468 Spider samples produces 8 candidate questions per SQL.
  4. Discriminative: keep the 1–2 candidates with the highest embedding similarity.
- Synthetic sizes: CORDIS 1,306, SDSS 2,061, OncoMX 1,065.

  — [ScienceBenchmark, arXiv 2306.04743](https://arxiv.org/abs/2306.04743)
- Manual audit of 100 synthetic pairs per DB (measured): meaningful SQL 97% / 97% / 91%; NL–SQL semantic equivalence 83% / 76% / 75% (CORDIS / SDSS / OncoMX). The authors call it "silver standard". — [ScienceBenchmark PDF](https://arxiv.org/pdf/2306.04743)

**CodeS bi-directional augmentation (SIGMOD 2024)**
- Q→SQL: GPT-3.5 writes new questions from a few real user questions, shuffled and sampled at high temperature, then writes SQL for each.
- SQL→Q: 75 Spider SQL templates paired with question templates are filled from the new schema, then GPT-3.5 rephrases them.
- From 30 annotated seeds this produced 4,901 (Bank-Financials) and 5,427 (Aminer-Simplified) training samples. No quantitative quality check is reported.
- CodeS-7B SFT EX (measured): 71.4 vs 61.5 (3-shot) on Bank-Financials; 51.5 vs 43.3 on Aminer-Simplified.

  — [CodeS, arXiv 2402.16347](https://arxiv.org/html/2402.16347v1)

**GAZP (EMNLP 2020; foundational)**
- A forward parser and a backward utterance generator synthesize (utterance, SQL) pairs in the new database environment. Only cycle-consistent pairs are kept: the parser's re-parse of the generated utterance must match by execution.
- It improved Spider, SParC and CoSQL zero-shot accuracy and beat in-environment augmentation. The authors identify cycle consistency as central to the gains.

  — [GAZP, ACL Anthology](https://aclanthology.org/2020.emnlp-main.558); [arXiv 2009.07396](https://arxiv.org/abs/2009.07396)

**2025–2026 RL / agentic pipelines**
- **Arctic-Text2SQL-R1 (Snowflake, arXiv 2505.20315).**
  - Data: filtered BIRD train (8,017), filtered Spider train (6,972) plus Spider dev (985), and Gretel-Synth-Filtered (11,811). Filtering removed gold SQL with empty results and queries slower than 5 s (about 1,400 BIRD and 1,700 Spider items).
  - SynSQL-2.5M with model filtering was "inconclusive", and LLM-augmented questions "largely failed to improve model generalization".
  - Reward: 1 for execution match, 0.1 for executable SQL, 0 otherwise. GRPO from OmniSQL checkpoints.
  - Results: 32B BIRD test 71.83%; 32B BIRD dev 70.5 and **Spider2.0-SQLite 16.3**.
  - Lessons listed by the authors: data filtering matters; online RL beats batch RL; strong SFT initialization matters; fine-grained rewards caused "lazy" behavior; BIRD-dev-only evaluation hides generalization gaps.

  — [Arctic-Text2SQL-R1](https://arxiv.org/html/2505.20315)
- **SQL-R1 (arXiv 2504.08600).** SFT cold start on SynSQL-200K (50k per tier); RL on SynSQL-Complex-5K, sampled at random from the Complex tier.
  - SFT on SynSQL-200K did not help the 7B model on BIRD dev (57.0 vs 58.2 base).
  - Starting RL from OmniSQL-7B gave 66.6 BIRD dev, versus 59.2 from the SynSQL-200K SFT start.
  - The paper is internally inconsistent: Table 1 reports 66.6 and Section 3.2 reports 63.1 for the 7B.

  — [SQL-R1](https://arxiv.org/html/2504.08600)
- **SkyRL-SQL (NovaSky, NeurIPS 2025).**
  - Setup: multi-turn agentic RL on Qwen2.5-Coder-7B-Instruct with VeRL and a SearchR1-style loop over SQLite, using "only about 600 training examples".
  - Results: the authors report up to +9.2% execution accuracy across 5 Spider benchmarks. They claim it beats GPT-4o, o4-mini and OmniSQL-7B, and that multi-turn RL generalizes better than single-turn.

  — [NeurIPS 2025 abstract](https://neurips.cc/virtual/2025/128018). The released set has 653 train rows, each tagged `synsql` or `spider`. — [SkyRL-SQL-653-data](https://huggingface.co/datasets/NovaSky-AI/SkyRL-SQL-653-data)
- **RingSQL (arXiv 2601.05451, Jan 2026).**
  - Method: 32 hand-designed, schema-independent templates in a "Structured Question Representation" over automatically built "Rings" (entities and attributes from DDL, joins inferred from FKs). SQL is deterministically compiled (Satyrn engine), so gold is correct by construction, then checked for a non-null result. GPT-4o-mini only rephrases the template question.
  - Data: 5,000 pairs over Spider train and dev DBs.
  - Results under RLVR (3B–8B models): average 69.80% across benchmarks, 2.1 points above the next synthetic set (SQLFlow), versus human Spider 68.45% and BIRD 68.51%.
  - The authors report that SFT on the same data was inconsistent.

  — [RingSQL](https://arxiv.org/html/2601.05451)
- **ReViSQL (UIUC Kang lab, arXiv 2603.20004, 2026).**
  - Argument: "rigorous curation is more important than massive creation". The authors build BIRD-Verified, 2,462 expert-corrected BIRD-train instances, and RL Qwen3-235B-A22B and 30B-A3B models with CISPO.
  - Results: Spider 2-SQLite (135 questions) 46.67% with the 235B model and 129 candidates; Spider 2-Snow 55.58%.
  - The paper has no controlled synthetic-vs-verified experiment.

  — [ReViSQL](https://arxiv.org/html/2603.20004v2)
- **Text2SQL-Flow / SQLFlow (PKU, arXiv 2511.10192).** Mutates seed SQL from Spider, BIRD and EHRSQL train sets along six dimensions:
  - Data Value Transformations
  - Query Structure Modifications
  - Business Logic Changes
  - Complexity Enhancements
  - Advanced SQL Features
  - Performance and Optimization

  GPT-4o at temperature 0 is the teacher. Output: 75,386 examples in v4 (89,544 in v2). The HF mirror lists cc-by-nc-sa-4.0; I did not verify the official license. — [Text2SQL-Flow v4](https://arxiv.org/html/2511.10192v4); [HF mirror](https://huggingface.co/datasets/debugger123/SQLFlow/blob/ac07b85fd656e2efcd7fd28d259fc484e9ecb113/README.md)
- **Other 2026 agentic RL items, from search snippets only:**
  - ReToolSQL: SFT then RFT over tool-use trajectories; claims 73.66% BIRD dev at 31B. — [arXiv 2608.27796](https://arxiv.org/abs/2608.27796)
  - Agent World Model: synthetic, code-driven, database-backed environments for agentic RL, scaled to 1,000 environments; not SQL-specific. — [arXiv 2602.10090](https://arxiv.org/abs/2602.10090)

**BIRD-team pipelines**
- **SWE-SQL / BIRD-CRITIC / Six-Gym (arXiv 2506.18951).** SQL-Rewind "operates by taking verified, correct SQL queries and systematically introducing plausible errors".
  - Solution SQL comes from Stack Overflow, adapted to 12 BIRD-train DBs.
  - Gemini-2.0-Flash does adaptation, issue synthesis, evaluation-script writing and user-query writing.
  - A triplet is kept only if test cases pass the solution and fail the issue SQL, with up to 3 coherence refinements.
  - Output: about 3,301 instances.
  - f-Plan Boosting (backward plan, then forward re-solve validated by tests) raised successful teacher trajectories from 1,254 to 2,178 (+73.7%).
  - Bird-Fixer (Qwen-2.5-Coder-14B, LoRA) scores 38.11% on BIRD-CRITIC-PG vs o3-mini 38.87%.

  — [SWE-SQL](https://arxiv.org/html/2506.18951)
- **LiveSQLBench and BIRD-Interact (ICLR 2026).** LiveSQLBench pairs each DB with a Hierarchical Knowledge Base (HKB): a DAG of knowledge nodes for multi-hop external knowledge. BIRD-Interact turns its single-turn tasks into interactive ones with ambiguous and follow-up sub-tasks and a function-driven user simulator. It has 600 full / 300 lite tasks. GPT-5 completes 8.67% (c-Interact) and 17.00% (a-Interact). — [BIRD-Interact, arXiv 2510.05318](https://arxiv.org/abs/2510.05318); [mini-interact card](https://huggingface.co/datasets/birdsql/mini-interact/blob/main/README.md)

### Inferences
Reusable ideas for judge data, ranked by fit to our error types:
1. **SQL-Rewind-style negatives with a test-case gate** (SWE-SQL), adapted from "issue → fix" to "plausible wrong answer vs gold".
2. **Correct-by-construction gold** (RingSQL compile) or **cycle consistency** (GAZP) to keep the positive side clean.
3. **Weak/on-policy model errors as negatives** (SENSE; ExCoT in Q5). These match the deployed agent's error distribution better than synthetic perturbations.
4. **Execution-filtering lessons from Arctic.** Drop empty-result gold. Keep items where at least 1 of N samples is correct, which yields exactly the mixed pools a pairwise judge trains on.

Real-schema pipelines (SQL-Factory, Text2SQL-Flow, RingSQL, ScienceBenchmark, CodeS) give data with realistic row counts. Pure-LLM DBs (SENSE, SQLForge, OmniSQL, Gretel) need re-population before execution-based labels mean much.

I found no training-data pipeline associated with ReFoRCE, which is an inference-time agent. Snowflake's training-data work is ExCoT and Arctic-Text2SQL-R1.

### Gaps
- Not examined: DB-Explore, SING-SQL (in-domain synthesis for a specific enterprise DB), MARS-SQL, MTIR-SQL, SQL-Trail, SERL-SQL. Their data recipes are unknown here.
- SkyRL-SQL's selection criterion for the 653 items is unverified; the Notion blog did not render.
- SENSE's DB content for executing weak-model SQL on synthetic schemas is unclear from the extracted text.
- Licenses unverified: SENSE, SQL-Factory, RingSQL, ReViSQL and SQLFlow (official).
- ReToolSQL and Agent World Model details come from search snippets only.

---

## Q3. Which verification strategies reduce wrong gold SQL, and how much label noise remains

### Takeaway
Measured residual noise in synthetic sets is about 5–25%. Human-labeled complex benchmarks are much worse:
- 61.1% of a 2,500-item BIRD-train sample needed at least one correction, 52.1% to the SQL itself.
- BIRD Mini-Dev and Spider 2.0-Snow have 52.8% and 62.8% annotation error rates.

The strongest gold-side controls reported are correctness by construction (compiled SQL), test cases that must separate gold from a perturbed variant, and double-blind expert correction. LLM critics have high precision but low recall: an o3 reviewer had 90.6% precision and 24.5% recall on BIRD errors. They are useful for flagging, not for certifying. Single-database execution matching and majority vote are weak on their own.

### Cited Findings
**Synthetic sets: measured residual error**
- SynSQL-2.5M: 86% of samples fully correct; 89% of SQL appropriate (human, 1,000 samples). — [OmniSQL](https://arxiv.org/html/2503.02240)
- SQL-Factory:
  - Gates: compile check, redundancy filter, CoT LLM verifier for NL–SQL consistency.
  - Audit: five PhD-level annotators cross-checked 1,000 pairs and judged **4.6% semantically inconsistent**.
  - 15.34% of queries return empty results.

  — [SQL-Factory](https://arxiv.org/html/2504.14837v5)
- ScienceBenchmark: NL–SQL semantic equivalence 75–83% (17–25% mismatch); meaningful SQL 91–97%. — [ScienceBenchmark PDF](https://arxiv.org/pdf/2306.04743)
- RingSQL: SQL correct by construction, with a non-null execution check. Question fidelity measured by UniEval consistency/relevance is 75.07 / 74.07, versus 54.45 / 52.30 for zero-shot LLM generation. No human audit. — [RingSQL](https://arxiv.org/html/2601.05451)
- Unaudited sets:
  - Text2SQL-Flow: executability via `EXPLAIN` only (no execution); a binary LLM NL–SQL check; CoT kept only if its SQL's result matches the reference. No human audit. — [Text2SQL-Flow](https://arxiv.org/html/2511.10192v4)
  - Gretel: parser validity plus relative GPT-4-judge scores. — [Gretel README](https://huggingface.co/datasets/gretelai/synthetic_text_to_sql/raw/main/README.md)
  - SQLForge: reports none. — [SQLForge](https://arxiv.org/html/2505.13725v1)

**Human-labeled data: measured noise and how it was found**
- ReViSQL audited 2,500 BIRD-train items:
  - At least one error in 61.1%: SQL corrected in 52.1%, question in 26.2%, EK in 18.2%; 1.5% unanswerable.
  - The o3 AI reviewer had 90.6% precision but 24.5% recall.
  - Method: a second expert re-corrected each item blind, with a three-expert vote on disagreement. First-round corrections failed verification 16.2% of the time, and some items took up to 4 rounds. Non-empty gold answers were required.

  — [ReViSQL](https://arxiv.org/html/2603.20004v2)
- Noisy labels hurt RL in ReViSQL's measurements. Training on original BIRD train raised training reward while held-out accuracy degraded. BIRD-Verified improved greedy accuracy by +8.2 (Arcwise-Plat-Full), +9.0 (Arcwise-Plat-SQL) and +13.9 (Spider 2-Snow). Noisy validation data picked step 30 instead of step 290 (77.3% vs 85.9%). — [ReViSQL](https://arxiv.org/html/2603.20004v2)
- Jin et al. (PVLDB):
  - BIRD Mini-Dev: 263/498 = 52.8% annotation errors. Spider 2.0-Snow: 76/121 = 62.8% (the CIDR'26 version reports 66.1%).
  - Error classes: E1 question vs SQL-logic mismatch; E2 question vs data; E3 domain-knowledge mismatch; E4 ambiguity.
  - Their SAR-Agent reviewer reached 83% precision on BIRD Mini-Dev.
  - On corrected data, BIRD agent scores shift by −7% to +31% (relative) and ranks move by up to 9 places.

  — [Jin et al., arXiv 2601.08778](https://arxiv.org/abs/2601.08778); [CIDR 2026 version](https://vldb.org/cidrdb/2026/text-to-sql-benchmarks-are-broken-an-in-depth-analysis-of-annotation-errors.html)
- NL2SQL-BUGs flagged 106 BIRD annotation errors (6.91% of the items it examined). — [NL2SQL-BUGs, arXiv 2503.11984](https://arxiv.org/abs/2503.11984)

**Execution-based checks: what they can and cannot certify**
- Distilled test suites start from neighbor queries made by changing one aspect of the gold (e.g., dropping a WHERE clause, ">" → "≥", changing a constant). They then keep the subset of 1,000 random DBs that distinguishes over 99% of the neighbors. Exact-set-match had a 2.5% average and 8.1% worst-case false-negative rate. Manual checks on 100 examples found the method always correct. — [Zhong, Yu & Klein, arXiv 2010.02840](https://arxiv.org/abs/2010.02840)
- GAZP's cycle consistency (keep a pair only if a parser maps the generated utterance back to an execution-equivalent query) was the key ingredient in its gains. — [GAZP](https://aclanthology.org/2020.emnlp-main.558)
- SWE-SQL keeps an issue/solution pair only if generated test cases pass the solution and fail the issue SQL. — [SWE-SQL](https://arxiv.org/html/2506.18951)
- Arctic-Text2SQL-R1 removes gold with empty results and queries slower than 5 s. For synthetic data it keeps only items where at least 1 of 10 model samples matches the gold. — [Arctic-Text2SQL-R1](https://arxiv.org/html/2505.20315)
- Spider 2.0's human annotators had to rewrite each SQL and confirm it "executes successfully, completes in an acceptable time, and returns non-empty results". 84.2% of examples got surface-level rewrites and 42% semantic-level. — [Spider 2.0](https://arxiv.org/abs/2411.07763)

### Inferences
Suggested strategy ranking for complex, multi-step gold:
1. **Construct, don't infer.** Compile SQL from a plan or template, as RingSQL does. This removes SQL-level errors but caps complexity at what templates express, and moves the risk into question wording (UniEval about 75).
2. **Make execution discriminative.** Run on populated or fuzzed DBs (test-suite method) that are designed to separate the gold from its plausible neighbors. Without this, "execution match" passes many wrong queries, especially on SynSQL's 2-row tables.
3. **Re-derive independently.** Cycle consistency, or agreement between independent solvers with different prompts or models, plus a test-case gate. Do not use plain majority vote: it reproduces shared errors, which is exactly what our judge must learn to reject.
4. **LLM critic as a flagger.** High precision, low recall (o3: 90.6% / 24.5%; SAR-Agent: 83% precision). It cannot certify a clean set.
5. **Human double-blind audit on a sample.** This is the only reported route to near-clean complex labels, and even expert first-round fixes failed 16.2% of the time.

Noise grows with complexity. SQL-Factory's 4.6% is on Spider/BIRD/TPC-DS/IMDB schemas with modest SQL. SynSQL's 14% includes CTE-heavy tiers. Human Spider 2.0-Snow is at 62.8%. Spider 2.0-level synthetic gold should be expected to be noisier than any figure above unless it is constructed or verified by tests.

For a pairwise judge, the label is "A beats B". The most robust pair is one where B is a known perturbation of a certified gold A *and* the two produce different results on the populated DB. That pair stays correctly ordered even when the question wording is slightly off.

### Gaps
- No paper reports a human audit of Spider 2.0-difficulty synthetic SQL: CTE chains over 100 tokens on wide schemas.
- No measured comparison was found of multi-model agreement versus single-model execution filtering for gold correctness.
- ScienceBenchmark's discriminator and SynSQL's centroid selection were not ablated against human labels.

---

## Q4. How pipelines make questions harder, longer, more realistic or deliberately ambiguous, and how they generate external-knowledge documents

### Takeaway
Difficulty is mostly controlled by prompting a complexity tier (OmniSQL, SENSE) or by mutating or crossing over seed SQL (SQLForge, Text2SQL-Flow). Realism comes from real schemas, or from LLM "enterprise scenario" schemas with wide tables and abbreviated column names. Ambiguity is injected in two ways:
- **Lexically:** synonyms, or alternative tables and joins (AmbiQT).
- **Structurally:** DBs built so that several readings stay valid (AMBROSIA), or knowledge-linked ambiguity (BIRD-Interact).

External knowledge is short definition strings in every training pipeline. The only multi-node, document-like knowledge source found is LiveSQLBench's HKB, which is a benchmark, not training data. Spider 2.0-Lite deliberately chose unambiguous, column-explicit wording over naturalness.

### Cited Findings
**Controlling difficulty, length and realism**
- OmniSQL uses tier criteria in the prompt, "ultra-wide tables ... 15-50 columns", abbreviated column names, a target column count, and 9 styles including Vague, Metaphorical and multi-turn dialogue. — [OmniSQL prompts](https://github.com/RUCKBReasoning/OmniSQL/tree/main/data_synthesis)
- SENSE prompts Easy/Medium/Hard definitions ("Hard: ... answers that use multiple advanced features") and excludes over-represented domains. — [SENSE](https://arxiv.org/abs/2408.03256)
- SQL-Factory alternates a strong explorer (GPT-4o) with a cheap expander (Qwen2.5-Coder-14B). It scores tables by referential complexity and stops when similarity trends upward. — [SQL-Factory](https://arxiv.org/html/2504.14837v5)
- SQLForge crosses over same-keyword AST subtrees and explores new domains under an entropy constraint. — [SQLForge](https://arxiv.org/html/2505.13725v1)
- Text2SQL-Flow's six mutation dimensions include "Business Logic Changes", "Complexity Enhancements" and "Advanced SQL Features". — [Text2SQL-Flow](https://arxiv.org/html/2511.10192v4)
- Spider 2.0's human annotators applied two kinds of rewrite. — [Spider 2.0](https://arxiv.org/abs/2411.07763)
  - Surface rewrites: answer format (e.g., "replace the one channel with the channel ranking by sessions"), condition parameters.
  - Semantic rewrites: advanced calculation, advanced requirements (e.g., "page view order → page conversion rate"), merging related SQLs.
- Spider 2.0 found that "unambiguity and naturalness are two mutually exclusive concepts". Spider 2.0-Lite emphasizes unambiguity, with instructions that spell out the expected output columns (e.g., "including the trip ID, duration in seconds, start date, start station name ..."). The evaluation ignores non-essential extra columns. — [Spider 2.0](https://arxiv.org/abs/2411.07763)

**Injecting ambiguity**
- AmbiQT: over 3,000 Spider-derived examples, each with two valid SQL readings, across four ambiguity types: column, table, join (vertically partitioned tables) and precomputed aggregates. Built from ChatGPT-generated synonyms plus schema perturbation. — [AmbiQT, arXiv 2310.13659](https://arxiv.org/abs/2310.13659)
- AMBROSIA (NeurIPS 2024 D&B): scope, attachment and vagueness ambiguity. DBs are generated from scratch so the ambiguity survives when the DB is shown; for example, scope ambiguity needs a many-to-many relation such as gyms ↔ classes. It covers 16 domains chosen for suitability for LLM generation. — [AMBROSIA, arXiv 2406.19073](https://arxiv.org/abs/2406.19073)
- BIRD-Interact injects knowledge-based ambiguity on top of LiveSQLBench tasks, with a user simulator that maps questions to constrained symbolic actions to avoid leaking the gold. — [BIRD-Interact](https://arxiv.org/abs/2510.05318). The ABISS paper argues it still omits failure modes such as missing or conflicting user knowledge. — [ABISS, arXiv 2607.23340](https://arxiv.org/pdf/2607.23340)

**Generating external knowledge and documentation**
- OmniSQL writes EK only for Vague and Metaphorical styles, as short semicolon-separated entries. — [OmniSQL question prompts](https://github.com/RUCKBReasoning/OmniSQL/blob/main/data_synthesis/question_synthesis/generate_question_synthesis_prompts.py)
- SQL-Factory writes an "external knowledge explanation" alongside each question (Qwen2.5-Coder-14B, 5 retrieved BIRD/Spider exemplars). — [SQL-Factory](https://arxiv.org/html/2504.14837v5)
- SEED generates BIRD-style evidence automatically from schema, description files and sampled values. It reports better accuracy than the no-evidence setting, sometimes beating human BIRD evidence. The authors argue most BIRD "evidence" (domain knowledge, synonyms, value illustrations) can be derived from the DB itself. — [SEED, arXiv 2506.07423](https://arxiv.org/abs/2506.07423)
- LiveSQLBench organizes knowledge as a DAG (HKB) whose nodes depend on other nodes, so questions require multi-hop definition chains. — [BIRD-Interact paper](https://arxiv.org/abs/2510.05318)
- Spider 2.0's documents were collected by humans: official SQL-dialect and function docs, and task-specific external-knowledge docs such as a Google Analytics channel-grouping definition. 82 tasks (12.97%) require documentation. — [Spider 2.0](https://arxiv.org/abs/2411.07763)

### Inferences
- **Our target is "long, explicit, definition-dependent", not "vague".** Spider 2.0-Lite questions are unambiguous and often list output columns, while business rules live in a markdown document. SynSQL's vague and metaphorical styles target a different difficulty. For judge training, a better style mix is explicit instructions plus a separate definitions document whose clauses the SQL must honor.
- **Doc-driven negatives.** No training pipeline generates multi-paragraph metric definitions such as "conversion rate = ... over sessions with ..." at scale. A practical adaptation of LiveSQLBench's HKB: generate definition nodes first, then SQL that composes them, then negatives that ignore or misapply one node. Misapplying a definition gives the wrong-denominator and overlapping-category errors directly.
- **Ambiguity generators as hard-negative sources.** AmbiQT's alternate tables and joins and AMBROSIA's scope readings are "plausible alternative SQL". Once the question is disambiguated (Spider 2.0-Lite style), the alternate reading becomes a near-miss negative. This maps onto our keying-on-name-vs-ID and overlapping-category errors.
- **Answer-shape and formatting negatives have a human template.** Spider 2.0's surface rewrites (single top item vs a ranking; formatted labels) define the shape and format errors we see. No automatic pipeline found targets them explicitly.

### Gaps
- No published pipeline was found that synthesizes Spider 2.0-Lite-style external-knowledge markdown documents with verified SQL dependence.
- AMBROSIA's exact sizes and its generation-model choices were not extracted.
- SEED's numeric gains were not extracted.

---

## Q5. Which methods produce plausible-but-wrong SQL next to the gold (near-miss negatives)

### Takeaway
Four families produce negatives:
1. **Model-sampled errors labeled by execution** (SENSE weak model; ExCoT off- and on-policy candidates; Arctic's "≥1 of 10 correct" pools).
2. **Rule-based neighbor mutations of the gold** (test-suite neighbor queries).
3. **LLM-injected plausible bugs gated by test cases** (SWE-SQL's SQL-Rewind).
4. **Expert-annotated real model errors with a taxonomy** (NL2SQL-BUGs: 9 categories, 31 subcategories).

None targets our specific failure mode, a *popular* wrong answer shared by 2–3 strong samples. On-policy pools from our own agent come closest. Mutation operators for ties, answer shape and denominators have to be written by us.

### Cited Findings
- **SENSE.** Weak-model (1.3B) samples are labeled by executor comparison with the gold, giving DPO pairs, worth +1.9 to +2.6 BIRD dev. — [SENSE](https://arxiv.org/abs/2408.03256)
- **ExCoT (Snowflake, arXiv 2503.19988).**
  - Method: GPT-4o candidate SQL is executed on SQLite and compared with the gold. Positives go to SFT and to off-policy DPO pairs; later rounds use on-policy samples from the tuned model.
  - Results: LLaMA-3.1-70B BIRD dev 57.37→68.51 and Spider test 78.81→86.59; best BIRD test 68.53.
  - The authors report that plain CoT and plain DPO alone gave negligible or marginal gains.
  - Arctic-ExCoT models are CC-BY-NC-4.0.

  — [ExCoT](https://arxiv.org/html/2503.19988v1); [Arctic-ExCoT-32B card](https://huggingface.co/Snowflake/Qwen-2.5-coder-Arctic-ExCoT-32B)
- **Arctic-Text2SQL-R1.** Model-based filtering keeps items where at least 1 of 10 samples is correct. That produces sample pools mixing correct and incorrect SQL. — [Arctic-Text2SQL-R1](https://arxiv.org/html/2505.20315)
- **OmniSQL CoT.** Each item gets 8 samples grouped by execution result, and only the majority group is kept. Minority groups are by-products and are not released. — [OmniSQL](https://arxiv.org/html/2503.02240)
- **Test-suite neighbor queries.** These are generated "by modifying one aspect of the gold query": drop a span such as a WHERE clause, replace a comparison operator (">" vs "≥") or a constant. Neighbors that fail to execute are removed. The number of neighbors scales with query length. Random DBs are then distilled to distinguish over 99% of neighbors. — [arXiv 2010.02840](https://arxiv.org/abs/2010.02840)
- **SQL-Rewind (SWE-SQL).** Gemini-2.0-Flash "systematically introduc[es] plausible errors" into verified SQL. A pair is kept only when test cases pass the correct SQL and fail the buggy one. Output: about 3,301 instances over 12 BIRD-train DBs. — [SWE-SQL](https://arxiv.org/html/2506.18951)
- **NL2SQL-BUGs taxonomy.** — [NL2SQL-BUGs PDF](https://arxiv.org/pdf/2503.11984); [arXiv abs](https://arxiv.org/abs/2503.11984)
  - Size and accuracy: 2,018 expert-annotated instances (1,019 correct, 999 with semantic errors) drawn from real model outputs. Detection accuracy across models averages 75.16%.
  - Main categories: Attribute (mismatch / redundancy / missing); Table (mismatch / redundancy / missing); Join (condition mismatch, type mismatch); Value (value mismatch, data-format mismatch); Operator; Condition (explicit missing / mismatch / redundant, implicit condition missing such as `IS NOT NULL`); Function (aggregate, window, date/time, conversion, math, string, conditional); Clause (missing / redundant, e.g., GROUP BY); Subquery (missing / mismatch); Other.
- **AmbiQT.** Each question carries two valid SQL readings (alternate column, table, join or precomputed aggregate). — [AmbiQT](https://arxiv.org/abs/2310.13659)

### Inferences
Each of our error types maps to a perturbation operator. Each operator only yields a *near-miss* (result differs from gold) if the DB contains the triggering data, so data requirements are listed too:

| Error type | Operator | Data needed to expose it |
|---|---|---|
| Wrong grain | Change or drop a GROUP BY key; aggregate at the child instead of the parent level (Clause / Attribute) | Several child rows per parent |
| Wrong denominator | `COUNT(*)` ↔ `COUNT(DISTINCT)`; filter before vs after aggregation; ratio of sums vs average of ratios (Aggregate-function) | Multiple rows per group with differing values |
| Join fan-out | Join to a one-to-many table before aggregating (Join condition/type) | Multiple matching child rows |
| Overlapping status categories | Swap `IN (...)` sets; drop an implicit exclusion (Explicit/Implicit condition) | Categories that overlap or nest |
| Name vs ID | GROUP BY or JOIN on the name instead of the key (Attribute mismatch) | Duplicate names with distinct IDs |
| Answer shape | `LIMIT 1` vs full ranking; top-k vs all | n/a. No NL2SQL-BUGs category; Spider 2.0's "answer format" rewrite is the template |
| Ties at cutoff | `ORDER BY ... LIMIT k` ↔ `RANK() ≤ k` / `DENSE_RANK` | Tied values at the k-th position |
| Format / labels | Rounding, date format, label strings (Data-format mismatch) | n/a |

- **The test-suite procedure is the reusable gate.** Generate the perturbation, then populate or fuzz the DB until gold and perturbation differ, which proves the pair is a genuine near-miss. Without it, many "negatives" are semantically equivalent on the data and become label noise.
- **On-policy negatives match our failure mode best.** Run our own agent at temperature on non-Spider-2.0 DBs (BIRD-Verified, re-populated SynSQL, real schemas) and keep questions where the samples split. This reproduces the "2–3 agree on a wrong answer" distribution that zero-shot judges miss, in the spirit of SENSE and ExCoT. It requires certified gold (Q3).
- **Weak-model negatives are probably too easy for this judge.** SENSE's 1.3B errors are likely obvious (schema hallucination). Our misses involve wrong answers that a strong model finds attractive. This is inference; no paper measures negative "difficulty" for judge training.

### Gaps
- No paper was found that measures how training a *pairwise judge or selector* on synthetic perturbation negatives compares with on-policy negatives. Other researchers cover selector training.
- The SQL-Rewind error-type distribution is not reported.
- No pipeline explicitly generates tie-at-cutoff or answer-shape negatives.

---

## Q6. How strong the teacher needs to be, and which open-weight teachers have worked

### Takeaway
For SQLite-level SQL on synthetic or academic schemas, open-weight teachers of 14B–72B paired with execution filters produced usable data:
- OmniSQL's open-model pool: 86% fully correct.
- SQL-Factory's GPT-4o explorer with a Qwen2.5-Coder-14B expander and verifier: 95.4% consistent.

Weak models (1.3B–1.8B) are adequate, even preferred, as negative generators. No evidence was found that any teacher, open or closed, produces reliable Spider 2.0-difficulty gold unaided: human-annotated Spider 2.0-Snow itself is 62.8% erroneous, and o3 as a critic caught only 24.5% of BIRD errors. Hard gold should come from construction or tests, not from teacher strength.

### Cited Findings
- **OmniSQL.** Teachers: Llama 3.1, DeepSeek Coder, Qwen2.5, Qwen2.5-Coder, with larger models doing more of the work; Qwen2.5-72B-Instruct screened tables. Result: 86% fully correct, and SFT gains on BIRD and Spider 2.0-SQLite (Q7). — [OmniSQL](https://arxiv.org/html/2503.02240)
- **SQL-Factory.** GPT-4o for exploration only. Qwen2.5-Coder-14B for expansion, management, criticism, table/seed selection and question writing. 4.6% inconsistent; about $180 for 380k queries. — [SQL-Factory](https://arxiv.org/html/2504.14837v5)
- **SENSE.** GPT-4 as the strong teacher. DeepSeek-Coder-1.3B, and Qwen-1.8B in the Qwen variant, as weak negative generators. — [SENSE](https://arxiv.org/abs/2408.03256)
- **Closed teachers:** GPT-4 (SQLForge, [SQLForge](https://arxiv.org/html/2505.13725v1)); GPT-4o at temperature 0 (Text2SQL-Flow, [Text2SQL-Flow](https://arxiv.org/html/2511.10192v4)); GPT-4o-mini for rephrasing only (RingSQL, [RingSQL](https://arxiv.org/html/2601.05451)); Gemini-2.0-Flash (SWE-SQL, [SWE-SQL](https://arxiv.org/html/2506.18951)); GPT-4o for candidate generation (ExCoT, [ExCoT](https://arxiv.org/html/2503.19988v1)); fine-tuned GPT-3 (ScienceBenchmark, 75–83% NL–SQL equivalence, [ScienceBenchmark](https://arxiv.org/pdf/2306.04743)).
- **Text2SQL-Flow robustness study** across teachers: GPT-3.5-Turbo, Claude-3.7-Sonnet, Gemini-2.5-Flash, DeepSeek-V3, GLM-4.6 and Qwen-3-235B (Table V). — [Text2SQL-Flow](https://arxiv.org/html/2511.10192v4)
- **LLM critics as verifiers:** o3 had 90.6% precision and 24.5% recall on BIRD-train errors ([ReViSQL](https://arxiv.org/html/2603.20004v2)); SAR-Agent had 83% precision on BIRD Mini-Dev ([Jin et al.](https://arxiv.org/abs/2601.08778)).
- **Teacher-free gold:** RingSQL's compiler matched or beat human Spider/BIRD data under RLVR for 3B–8B students. — [RingSQL](https://arxiv.org/html/2601.05451)

### Inferences
- **Our agent is not a reliable gold source on hard questions, but it can supply candidates and question wording.** Our own agent is Qwen3.6-35B-A3B, at about 50% pass@1 and 94/135 pass@4 on the local split (project CLAUDE.md). Used as a *gold generator* for hard synthetic questions, it would be wrong roughly as often as on Spider 2.0. Better uses:
  - candidate and negative generator (on-policy);
  - question writer in a SQL-first pipeline, where the gold SQL comes from construction or a test-gated derivation.
- **Teacher role matters more than teacher size.** A strong explorer, a cheap expander and a weak error source works at low cost (SQL-Factory: about $180 for 380k). Verification is where strength matters most, and even o3 needs humans behind it.

### Gaps
- Text2SQL-Flow's per-teacher numbers (Table V) were not extracted, so the open-vs-closed teacher gap at fixed pipeline is unquantified here.
- No study was found that varies teacher size and measures gold correctness on Spider 2.0-difficulty SQL.

---

## Q7. Measured downstream effects on BIRD and Spider 2.0 (including the 135-question SQLite split)

### Takeaway
Synthetic SFT data clearly helps BIRD and Spider-1 for 1B–32B models. On Spider 2.0-SQLite, the best reported synthetic-data-trained small models reach 10–16%, about 14–22 of 135 questions. Differences between synthetic datasets amount to a handful of questions, which RingSQL's authors themselves call too low to compare. The largest measured Spider 2.0 gain attributable to *data* in these papers comes from label verification, not volume: BIRD-Verified gave +13.9 greedy points on Spider 2-Snow (ReViSQL).

### Cited Findings
- **OmniSQL main results** (greedy / majority, %) — [OmniSQL](https://arxiv.org/html/2503.02240)

  | Model | Spider test | BIRD dev | Spider2.0-SQLite |
  |---|---|---|---|
  | OmniSQL-7B | 87.9 / 88.9 | 63.9 / 66.1 | 10.4 / 10.4 |
  | OmniSQL-14B | 88.3 / 88.3 | 64.2 / 65.9 | 10.4 / 13.3 |
  | OmniSQL-32B | 87.6 / 89.8 | 64.5 / 67.0 | 11.9 / 13.3 |

- **OmniSQL 7B ablation** (greedy; Spider test / BIRD dev / Spider2.0-SQLite) — [OmniSQL](https://arxiv.org/html/2503.02240)
  - Base Qwen2.5-Coder-7B-Instruct: 82.2 / 50.9 / 1.5
  - Original Spider+BIRD: 80.7 / 55.1 / 3.0
  - CoT-enhanced Spider+BIRD: 86.6 / 59.6 / 5.9
  - SynSQL only: 83.5 / 59.9 / 9.6
  - Full (SynSQL + CoT Spider+BIRD): 87.9 / 63.9 / 10.4
- **Arctic-Text2SQL-R1-32B** (OmniSQL init, GRPO, filtered BIRD/Spider/Gretel): BIRD test 71.83, BIRD dev 70.5, **Spider2.0-SQLite 16.3**, Spider test 88.7, Spider-DK 80.6, EHRSQL 40.1, ScienceBenchmark 60.9. — [Arctic-Text2SQL-R1](https://arxiv.org/html/2505.20315)
- **RingSQL Appendix H** ("Spider 2.0-lite sqlite"; steps of 0.74 points imply n = 135). — [RingSQL](https://arxiv.org/html/2601.05451)
  - Qwen2.5-Coder-7B under RL: none 8.15; SynSQL-Uniform 9.63; **SynSQL-Complex 11.11**; SENSE 6.67; SQLFlow 9.63; RingSQL 8.15; Spider 7.41; BIRD 8.89.
  - All 3B models stay at or below 5.19.
  - The authors say the numbers are too low to show which data helps.
- **Text2SQL-Flow** (Qwen2.5-Coder-7B, SFT): SQLFlow gives BIRD dev 56.8 and Spider test 85.1, versus 53.2 / 81.6 for an equal-size 75k SynSQL sample. Full SynSQL-2.5M (OmniSQL-7B) still leads at 63.9 / 87.9. The SynSQL-2.5M rows are identical in both model blocks, so treat them with caution. — [Text2SQL-Flow](https://arxiv.org/html/2511.10192v4)
- **SQL-R1:** SynSQL-200K SFT did not improve 7B BIRD dev (57.0 vs 58.2 base). OmniSQL-7B init gave 66.6, though the paper also reports 63.1 for this setup. — [SQL-R1](https://arxiv.org/html/2504.08600)
- **ReViSQL:** Spider 2-SQLite 46.67% with Qwen3-235B-A22B, RL on 2.5k verified BIRD items and 129 candidates, versus GenaSQL 34.81%. Verified versus original BIRD-train data: +13.9 greedy on Spider 2-Snow. — [ReViSQL](https://arxiv.org/html/2603.20004v2)
- **SENSE, SQLForge, SQL-Factory, CodeS:** BIRD and Spider-1 gains as listed in Q2. None evaluates Spider 2.0. — [SENSE](https://arxiv.org/abs/2408.03256); [SQLForge](https://arxiv.org/html/2505.13725v1); [SQL-Factory](https://arxiv.org/html/2504.14837v5); [CodeS](https://arxiv.org/html/2402.16347v1)

### Inferences
- **Spider 2.0 transfer is modest and mostly within noise.** On 135 questions, SynSQL-only versus Spider+BIRD for OmniSQL-7B is 13 vs 4 questions. SynSQL-Complex versus none under RL is 15 vs 11. Each is a single run, so the gaps are suggestive at best. Our own project notes that about 3-point effects are unresolved even with 4 lanes.
- **Clean generator gold matters more than volume for the judge.** The judge's job is discrimination, not generation, so these SFT numbers say little about judge accuracy directly. What carries over is the evidence that label noise in training data damages held-out performance (ReViSQL) and that filtering beats volume (Arctic). Both argue for a smaller, certified pair set over a large SynSQL-derived one.

### Gaps
- No paper was found that trains a judge, selector or reward model on synthetic pairs and evaluates selection on Spider 2.0-Lite. Selector training is covered by other researchers.
- OmniSQL's Spider2.0-SQLite count and version were not stated in the extracted text; RingSQL's 0.74-point steps and ReViSQL's "135 SQLite questions" indicate the same 135-question split.

---

## Q8. Overlap with the 30 Spider 2.0-Lite local databases (contamination flags) and release terms

### Takeaway
Nearly every pipeline built on real schemas uses Spider-train or BIRD-train databases, which include the schemas you listed:
- Spider-1: sakila_1, chinook_1, store_1, soccer_1, formula_1, baseball_1.
- BIRD: movie_3≈Sakila, retail_world≈Northwind, works_cycles≈AdventureWorks, soccer_2016≈IPL.

Models such as OmniSQL, Arctic-Text2SQL-R1 and SQL-R1's OmniSQL variant inherit this schema-level exposure. SynSQL-2.5M and Gretel use synthetic schemas, with no overlap check reported. SQL-Factory's IMDB schema needs checking against Db-IMDB and imdb_movies.

### Cited Findings
- OmniSQL fine-tuning mixes SynSQL-2.5M with CoT-enhanced Spider and BIRD training sets. — [OmniSQL README](https://github.com/RUCKBReasoning/OmniSQL); [OmniSQL paper](https://arxiv.org/html/2503.02240). Arctic-Text2SQL-R1 starts from OmniSQL and trains on filtered BIRD train, Spider train and Spider dev. — [Arctic-Text2SQL-R1](https://arxiv.org/html/2505.20315)
- SENSE's SFT mix includes Spider train (7,000) and BIRD train (9,428). — [SENSE](https://arxiv.org/abs/2408.03256)
- SQLForge seeds come from about 18K Spider+BIRD train items, which are also in its final training mix. — [SQLForge](https://arxiv.org/html/2505.13725v1)
- Text2SQL-Flow augments Spider train (30,502), BIRD train (33,163) and EHRSQL. — [Text2SQL-Flow](https://arxiv.org/html/2511.10192v4)
- SQL-Factory generates 130k queries on Spider schemas, 160k on BIRD schemas and 40k on an IMDB schema with 21 tables. — [SQL-Factory](https://arxiv.org/html/2504.14837v5)
- RingSQL builds Rings over the Spider train and dev DBs. — [RingSQL](https://arxiv.org/html/2601.05451)
- SkyRL-SQL-653 includes rows tagged `spider`. — [SkyRL-SQL-653-data](https://huggingface.co/datasets/NovaSky-AI/SkyRL-SQL-653-data)
- BIRD-Verified samples BIRD train. — [ReViSQL](https://arxiv.org/html/2603.20004v2)
- SWE-SQL's Six-Gym uses 12 BIRD-train DBs; which 12 is not checked. — [SWE-SQL](https://arxiv.org/html/2506.18951)
- CodeS's SQL→Q direction uses 75 Spider SQL templates (structure only). — [CodeS](https://arxiv.org/html/2402.16347v1)
- Synthetic-schema sets: SynSQL-2.5M (TabLib-derived, Apache-2.0, [card](https://huggingface.co/datasets/seeklhy/SynSQL-2.5M)); Gretel (100 LLM domains, Apache-2.0, [README](https://huggingface.co/datasets/gretelai/synthetic_text_to_sql/raw/main/README.md)). Neither reports an overlap analysis.
- Releases and licenses seen:
  - SynSQL-2.5M and Gretel: Apache-2.0.
  - Arctic-ExCoT models: CC-BY-NC-4.0 ([card](https://huggingface.co/Snowflake/Qwen-2.5-coder-Arctic-ExCoT-32B)).
  - SQLFlow HF mirror: cc-by-nc-sa-4.0 ([mirror](https://huggingface.co/datasets/debugger123/SQLFlow/blob/ac07b85fd656e2efcd7fd28d259fc484e9ecb113/README.md)).
  - SkyRL-SQL-653: no card or license.
  - Arctic-Text2SQL-R1 models are released ([paper](https://arxiv.org/html/2505.20315)), license not stated in the paper text.

### Inferences
- **Filter judge data by DB, not only by question.** Any judge data drawn from Spider/BIRD-derived sets should drop the overlapping DBs. Otherwise the judge sees our evaluation schemas (Sakila, Northwind, AdventureWorks, IPL, Chinook, F1, etc.) with different questions. That is schema-level, not question-level, contamination, but it inflates "transfer" to our 135.
- **Starting checkpoints carry the exposure too.** Initializing the judge from OmniSQL or Arctic checkpoints inherits the same schema exposure. A general instruct base avoids it.
- **Synthesizing on our own 30 DBs is a separate decision.** It is not forbidden by the stated constraint (no Spider 2.0 questions or gold), but it is a schema-level contamination choice that should be reported if made. In-domain synthesis is SING-SQL's premise; not examined here.

### Gaps
- I did not verify which 12 BIRD DBs Six-Gym uses, or whether SQL-Factory's 21-table IMDB is the JOB/IMDB schema or related to Db-IMDB / imdb_movies.
- No overlap audit between TabLib-derived SynSQL schemas and the 30 local DBs was found. It could be run locally by matching table and column names.
- Licenses for the SENSE data, SQL-Factory, RingSQL and ReViSQL artifacts, and OmniSQL model weights, were not verified.
