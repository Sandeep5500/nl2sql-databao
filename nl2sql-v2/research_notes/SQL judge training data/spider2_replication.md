# Replicating Spider 2.0-Lite (local SQLite split): target specification, benchmark-construction methods, recipes for our error types, and contamination policy

Conventions used in these notes:
- **Measured** means computed by this researcher from the local Spider2 submodule at commit `01a4c67c` (2026-01-30), which descends from upstream `5fa8a517` (2025-11-02). The statistics script is `/private/tmp/claude-501/-Users-deepikapalagani-Documents-nl2sql-databao/f54a9a7d-52ac-46be-8abb-0cac5a1864b1/scratchpad/stats.py`, and git-history counts come from `git log` and `git show` on that submodule.
- **Claimed** means a paper's or maintainer's statement that was not re-checked.
- No Spider 2.0 question text or gold SQL is reproduced beyond short fragments.

---

## Q1. What exactly are the Spider 2.0-Lite local tasks? Sources, documents, evaluation conventions, difficulty, and known gold problems

### Takeaway
- **What the tasks are.** The 135 local tasks are tutorial- and forum-derived analytic SQL problems over 30 small-to-medium SQLite databases (median 13 tables and 77 columns). Authors rewrote each one into a long, procedural question.
- **Where the difficulty comes from.** It comes from multi-step logic: CTEs, window functions, string and date parsing, and business definitions. It also comes from strict result matching. Schema size is not the source; the local schemas are far smaller than the cloud ones.
- **How it is scored.** A prediction passes if every essential gold column appears in it. Extra columns pass; extra rows, wrong labels and wrong scale fail. Any one of several gold variants can be matched.
- **Gold reliability.** The golds have been heavily revised:
  - Since the public release, 82 of 135 questions have been substantially rewritten.
  - A November 2025 re-annotation touched 134 of 135 gold results. It raised the number of tasks with more than one acceptable gold from 21 to 91.
  - An independent audit found 62.8% of the publicly checkable Spider 2.0-Snow golds wrong.
  - At least 15 local tasks still have open public complaints about wrong or ambiguous golds.

### Cited Findings

#### How Spider 2.0 was built (paper, ICLR 2025)
- **Databases.** Databases were collected "from cloud data warehouses, including BigQuery public data, Snowflake Marketplace data, and other platforms". The stated criterion is that each "must contain more than 200 columns or have a nested schema structure". The selection was 74 BigQuery, 54 Snowflake, 30 SQLite, 40 DuckDB, 10 PostgreSQL and 5 ClickHouse databases — [Spider 2.0, §2.2 Step 1](https://arxiv.org/html/2411.07763)
- **SQL sources.** "From the corresponding tutorials and forums, we gather 1,021 complex SQL queries." Queries "must originate from real projects or tutorials, not from synthetic examples or corner cases", and must exceed 50 whitespace tokens (BIRD averages 30.9). 547 were kept for Lite/Snow, plus 78 DBT projects out of 157 Fivetran/DBT projects collected — [Spider 2.0](https://arxiv.org/html/2411.07763)
- **Rewrites.** Rewrites happen at two levels. "'Surface' rewrites adjust the parameters and the answer format, while 'Semantic' rewrites expand the question's meaning." 84.2% of examples received surface rewrites and 42% semantic rewrites. The paper says rewriting was done "to avoid contamination and ensure the credibility" of the evaluation — [Spider 2.0](https://arxiv.org/html/2411.07763)
- **Instructions.** "Annotators manually write the instructions, making them natural by avoiding blunt descriptions, removing ambiguity in the expected results." They "verify the semantic equivalence between the SQL queries and instructions, paraphrasing for clarity with the help of LLMs." The paper also states that "text-to-SQL tasks prioritize unambiguity" and that "unambiguity and naturalness are two mutually exclusive concepts" — [Spider 2.0 §2.2 Step 4 and appendix](https://arxiv.org/html/2411.07763)
- **Annotators and validation.** The annotators were eight computer-science authors. At least three annotators reviewed each instruction, gold SQL and evaluation script. "45% of the examples have errors identified by the first validators"; after a second round, "only 5% of the examples contain errors". Evaluation scripts were red-teamed with incorrect but well-formatted results (claimed) — [Spider 2.0 §2.2 Step 6](https://arxiv.org/html/2411.07763)
- **External documents.** "We collect the external reference documents necessary to complete the task." For Lite/Snow these include SQL dialect and function documentation. 82 of Spider 2.0's 632 examples (12.97%) include documentation — [Spider 2.0](https://arxiv.org/html/2411.07763)
- **Paper-level statistics (Table 2).**

  | Dataset | Examples | Databases | Columns per DB | Tokens per SQL | Functions per SQL |
  |---|---|---|---|---|---|
  | Spider 2.0-Lite | 547 | 158 | 803.6 | 144.5 | 6.5 |
  | Spider 2.0-Snow | 547 | — | 812.1 | 161.8 | — |
  | Spider 1.0 dev | — | — | — | 18.5 | — |
  | BIRD dev | — | — | — | 30.9 | — |

  Difficulty is defined by gold-SQL whitespace tokens: Easy is fewer than 80, Medium is 80–159, Hard is 160 or more. Across all 632 Spider 2.0 tasks the split is 25.32%, 44.15% and 30.54%. SQLite accounts for 135 of the 632 (21.36%) — [Spider 2.0 Table 2](https://arxiv.org/html/2411.07763)
- **The paper's error analysis (300 examples).**
  - Erroneous data analysis: 35.5% (query planning 17.7%, dialect functions 10.3%, advanced calculation 7.5%).
  - Wrong schema linking: 27.6% (columns 16.6%, tables 10.1%).
  - JOIN errors: 8.3%.
  - Other categories were not legible in the fetched text.
  
  The fine-tuned baseline (SFT CodeS-15B) scored 0.73% EX on Lite — [Spider 2.0](https://arxiv.org/html/2411.07763)

#### Composition of the local split (measured)
- **Instance counts.** spider2-lite.jsonl has 547 instances: bq 180, sf 207, ga 25, local 135. The local tasks span 30 databases. The largest are bank_sales_trading (15), IPL (11), city_legislation (10), f1 (9), Brazilian_E_Commerce (8) and oracle_sql (8). Eleven databases contribute only 1–2 tasks each — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl)
- **Database size.** The 30 local databases have a mean of 14.4 tables (median 13, range 4–38) and a mean of 100.4 columns (median 77, range 35–352; Baseball is the largest). That is far below the paper's Lite average of 803.6 columns and below its stated >200-column criterion — [resource/databases/sqlite/*/*.json](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/databases/sqlite)
- **Table names hint at tutorial or book origins:**
  - bank_sales_trading: customer_nodes, customer_transactions, interest_metrics, shopping_cart_events, bitcoin_*, veg_*.
  - modern_data: pizza_runner_orders, pizza_recipes, trees, companies_funding.
  - oracle_sql: conway_gen_zero, emp_hire_periods, picking_list, breweries.
  - complex_oracle: channels, costs, promotions, sales, times.
  - city_legislation: legislators, legislators_terms, job_postings_fact, skills_dim.
  - education_business: hardware_fact_gross_price, web_accounts/web_events.
  
  Source: [local DDL folders](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/databases/sqlite). Attribution of these schemas to specific courses is an inference; see Inferences.
- **Question length (current version).** Local questions average 51.1 words (median 46, range 10–142); all Lite questions average 54.0 — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl)
- **Gold SQL availability.** Only 24 of the 135 local gold SQL files are public (256 gold SQL files across Lite). Gold result CSVs exist for all 135 — [gold/sql](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/sql). The maintainer has said: "we do not intend to release all of the gold SQL. We release these SQLs to provide participants with some examples" — [Issue #109](https://github.com/xlang-ai/Spider2/issues/109)

#### External-knowledge documents (measured)
- **Coverage.** Only 13 of the 135 local tasks reference a document, and they use 8 distinct documents:
  - two tasks each: haversine_formula, projection_calculation, baseball_game_special_words_definition, calculation_method, f1_overtake;
  - one task each: RFM, spherical_law, music_length_type.
  
  Across all of Lite, 107 of 547 tasks use 63 distinct documents — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl)
- **Form.** The local documents are short Markdown, 60–918 words. They contain:
  - metric definitions and scoring rules (RFM segments, 918 words);
  - formulas (haversine, spherical law of cosines);
  - stepwise calculation recipes (sales-to-centred-moving-average ratio; sales projection steps);
  - label taxonomies (F1 overtake classes);
  - glossary definitions (baseball terms);
  - bucketing rules (music length types, 60 words).
  
  Source: [resource/documents](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/documents)
- **Known document problems.** In one reported case, the document described a column that does not exist in the database. The maintainer answered "it's a mistake… just delete it" — [Issue #42](https://github.com/xlang-ai/Spider2/issues/42). A 2026 issue reports Snow documents that are inconsistent with the gold answers — [Issue #195](https://github.com/xlang-ai/Spider2/issues/195)

#### Evaluation conventions (measured from evaluate.py and spider2lite_eval.jsonl)
- **Scoring rule.** For each gold variant, every gold column vector must equal *some* predicted column vector. If `condition_cols` is set, only those gold columns are checked. Extra predicted columns are ignored. A task scores 1 if any variant matches — [evaluate.py](https://github.com/xlang-ai/Spider2/blob/main/spider2-lite/evaluation_suite/evaluate.py) (local copy, lines 67–131). The paper describes this as focusing on "the essential components of the answers, ignoring non-essential columns": "if all columns in the reference table appear in the result table, the result is considered correct" — [Spider 2.0 App. A](https://arxiv.org/html/2411.07763)
- **Value comparison.**
  - Numbers match within an absolute tolerance of 0.01 (`math.isclose(..., abs_tol=1e-2)`).
  - NaN/NULL is normalised to 0.
  - Strings must match exactly.
  - With `ignore_order`, each column is sorted *independently*, so row alignment across columns is never checked.
  
  Source: [evaluate.py, local copy](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/evaluate.py). The NULL-to-0 behaviour is reported as a bug for Snow: 161 of 1,544 gold files contain NULLs — [Issue #157](https://github.com/xlang-ai/Spider2/issues/157). The column-independent matching is reported for the DBT comparator, which is the same function — [Issue #226](https://github.com/xlang-ai/Spider2/issues/226), [Issue #200](https://github.com/xlang-ai/Spider2/issues/200)
- **Order and essential columns.**
  - `ignore_order` is currently true for all 547 Lite tasks.
  - `condition_cols` is non-empty for 49 of the 135 local tasks; 12 of these give a nested list with one entry per variant — [spider2lite_eval.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl)
  - Before the Nov-2025 commit, only 94 of 135 locals had `ignore_order: true` and 31 had non-empty `condition_cols` — [commit 5fa8a517 parent](https://github.com/xlang-ai/Spider2/commit/5fa8a5179c411c22ff8fd902c9e01c5bc2bf6c47)
- **Gold variants.** Variants are stored as `<id>_a.csv`, `<id>_b.csv`, and so on. 91 of the 135 locals have more than one. The distribution of variant counts is 1:44, 2:45, 3:22, 4:11, 5:8, 6:1, 8:1, 9:2, 12:1 — [gold/exec_result](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result)
- **Answer shapes (first variant).**
  - 45 of 135 are single-row; 101 of 135 have 10 rows or fewer; 8 have more than 100 rows; the median is 3 rows.
  - 34 are single-column; the mean is 3.0 columns and the maximum 18.
  
  Source: [gold/exec_result](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result)
- **Oracle-tables setting.** Ground-truth tables have been released; users of them "must indicate that you are using `oracle tables`" — [Spider2 README news 2025-04-20](https://github.com/xlang-ai/Spider2). The Snow leaderboard excludes such methods from ranking — [leaderboard](https://spider2-sql.github.io/)

#### Difficulty statistics (measured)
- **Gold token counts.** The `toks` field (gold-SQL token count, available for all 135 locals even where the SQL is hidden) averages 184.2 (median 143, min 52, max 1,066, p75 202, p90 342). The local split has the longest golds by prefix: bq 138.4, sf 137.8, ga 153.7, local 184.2 (Lite overall 150.2) — [spider2lite_eval.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl)
- **Difficulty buckets.** Using the paper's thresholds, the local split has 10 Easy, 67 Medium and 58 Hard tasks. All of Lite has 128, 246 and 173 — [same file](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl)
- **Shape of the 24 public local gold SQLs.** Mean 1,435 characters (median 1,148; 515–3,811), mean 53.8 lines, about 3.2 distinct base tables (median 3, max 8). Construct presence (CTE bodies are counted as parenthesised SELECTs):

  | Construct | Present in (of 24) |
  |---|---|
  | CTE | 21 |
  | CASE | 10 |
  | Window functions | 8 |
  | LIMIT | 8 |
  | UNION | 7 |
  | LEFT JOIN | 6 |
  | Date functions | 6 |
  | DISTINCT | 5 |
  | ROUND | 5 |
  | HAVING | 3 |

  Function-call counts: SUM 32, COUNT 28, SUBSTR 18, INSTR 18, TRIM 17, MAX 12, JULIANDAY 10, ROUND 10, STRFTIME 5, ROW_NUMBER 4, CAST 4, NTILE 3, AVG 3, LAG 1, RANK 1. String parsing and date arithmetic are prominent — [gold/sql local*.sql](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/sql)

#### Known problems with the gold annotations
- **Independent audit (Jin, Choi, Zhu, Kang; arXiv 2601.08778; PVLDB 19).** The audit covered the 121 Spider 2.0-Snow tasks with public gold SQL, using annotations as of 2025-08-20 (before the Oct/Nov-2025 fixes). 76 of 121 (62.8%) had annotation errors; an earlier CIDR-2026 version reported 66.1% — [arXiv 2601.08778v3](https://arxiv.org/html/2601.08778v3), [CIDR 2026](https://vldb.org/cidrdb/2026/text-to-sql-benchmarks-are-broken-an-in-depth-analysis-of-annotation-errors.html)
  - Error taxonomy (an example can carry several labels):

    | Code | Error type | Spider 2.0-Snow | BIRD Mini-Dev |
    |---|---|---|---|
    | E1 | Question–SQL logic mismatch | 48.68% | 29.28% |
    | E2 | Mismatch with data or schema | 57.89% | 57.79% |
    | E3 | Wrong domain knowledge | 11.84% | 10.65% |
    | E4 | Ambiguity in question or output format | 23.68% | 29.66% |

  - Named patterns: row inflation from JOIN/FLATTEN without deduplication (including **sf_local263**, a local-origin task); end-of-day timestamp truncation; a missing filter; a wrong join key; and seven questions requiring an unstated quotation-mark replacement in the output — [same](https://arxiv.org/html/2601.08778v3)
  - Method: SAR-Agent (OpenAI o3, 30 iterations, tools `execute_query` and `terminate`) wrote diagnostic reports. Two authors adjudicated every flag. Precision was 89% on Snow (70 of 79 flags valid). Code and prompts: [github.com/uiuc-kang-lab/text_to_sql_benchmarks](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks) — [same](https://arxiv.org/html/2601.08778v3)
- **Upstream gold churn (measured from git history).**
  - **Question rewrites.** Since the 2024-12-25 snapshot, 82 of 135 local questions have been rewritten. 79 of those changes touched more than 15 words, and the mean length of the changed questions grew from 33.9 to 63.6 words. Added text often fixes a tie-break (e.g. "tie broken by alphabetical order"), names the output columns, defines terms (a status code that means "completed"), or spells out computation steps — [spider2-lite.jsonl history](https://github.com/xlang-ai/Spider2/commits/main/spider2-lite/spider2-lite.jsonl)
  - **Eval-spec changes.** In the same period, the `condition_cols`/`ignore_order` spec changed for 75 of 135 locals — [eval jsonl history](https://github.com/xlang-ai/Spider2/commits/main/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl)
  - **The Nov-2025 re-annotation.** Commit `5fa8a517` (2025-11-02, "update spider2lite eval") added 281, deleted 110 and modified 28 local gold files, touching 134 of 135 local tasks. Tasks with more than one acceptable gold rose from 21 to 91 — [commit 5fa8a517](https://github.com/xlang-ai/Spider2/commit/5fa8a5179c411c22ff8fd902c9e01c5bc2bf6c47). The README says that update "fixed the evaluation-suite issue" and refreshed leaderboard scores — [README news 2025-10-29](https://github.com/xlang-ai/Spider2)
- **Open GitHub issues naming specific local tasks.** At least 15 distinct local tasks are named:
  - Gold SQL does not reproduce gold CSVs for several SQLite tasks, e.g. local003 and local017. The maintainer reply was "you may use Spider2-snow first" — [#154](https://github.com/xlang-ai/Spider2/issues/154)
  - **Fan-out in a gold.** local029's gold joins the payments table and then counts orders, so it counts payment rows — [#216](https://github.com/xlang-ai/Spider2/issues/216), [#122](https://github.com/xlang-ai/Spider2/issues/122). The same task's tie-break is unspecified — [#160](https://github.com/xlang-ai/Spider2/issues/160)
  - **Boundary operator.** local085's question says "on or after" but the gold uses `>` — [#163](https://github.com/xlang-ai/Spider2/issues/163)
  - **Grain ambiguity.** local060: rank products per city, or pooled across qualifying cities? — [#159](https://github.com/xlang-ai/Spider2/issues/159)
  - **Ties from duplicate timestamps.** local331 — [#168](https://github.com/xlang-ai/Spider2/issues/168)
  - **Wrong `condition_cols`.** local130 — [#158](https://github.com/xlang-ai/Spider2/issues/158)
  - **Incorrect or underspecified golds.** local010, local194, local272, local273, local279, local354, local358 — [#161](https://github.com/xlang-ai/Spider2/issues/161), [#162](https://github.com/xlang-ai/Spider2/issues/162), [#164](https://github.com/xlang-ai/Spider2/issues/164), [#165](https://github.com/xlang-ai/Spider2/issues/165), [#166](https://github.com/xlang-ai/Spider2/issues/166), [#167](https://github.com/xlang-ai/Spider2/issues/167), [#169](https://github.com/xlang-ai/Spider2/issues/169); and local066 — [#114](https://github.com/xlang-ai/Spider2/issues/114)
  - **Variant mismatches.** The number of `condition_cols` entries no longer matches the number of variants for some tasks after the update — [#151](https://github.com/xlang-ai/Spider2/issues/151)
- **Maintainer responsiveness varies.** One reply reads: "We carefully checked… your answer is correct. We have fixed the evaluation result" — [#97](https://github.com/xlang-ai/Spider2/issues/97). Most of the Dec-2025 local issues were still open on 2026-10-27 — [issue list](https://github.com/xlang-ai/Spider2/issues)
- **The team's own audit.** It lists 8 gold-sensitive local tasks (local029, local064, local130, local131, local196, local275, local301, local360), tagged gold_revised, variants_added, stale_gold_sql, eval_spec, degenerate_gold or tie_fragile. Examples:
  - local275's current gold has a header and 0 rows.
  - local196's old gold counted payments as rentals.
  - local064 asks about 12 months while the data cover only January–April, which creates an 8-way tie among empty months.
  
  Source: [gold_sensitive_tasks.yaml](/Users/deepikapalagani/Documents/nl2sql-databao/nl2sql-v2/scripts/gold_sensitive_tasks.yaml)
- **Leaderboard on 2026-10-27.**
  - Lite top: "Tianqiong Data Agent + GLM 5.2" at 76.23; "Databao Agent" is 7th at 69.65.
  - Snow top: 96.70 ("Genloop's Sentinel Agent v2 Pro").
  
  Source: [spider2-sql.github.io](https://spider2-sql.github.io/)

### Inferences
- **Target profile for replication.**
  - Databases: small SQLite databases of about 4–38 tables and 35–350 columns, with realistic mess (text dates, codes, denormalised names, duplicate-like rows).
  - Questions: 45–60 words, often procedural ("first compute X per Y, then…"). They name the output columns and fix tie-breaks.
  - Gold SQL: 100–350 whitespace tokens, about 3 base tables, CTE chains, frequent windows, CASE, and string or date parsing.
  - Answers: small (median 3 rows, about 3 columns; a third single-row).
  - Documents: about 10% of tasks carry a short definitional document (metric, formula, label taxonomy).
- **The current local questions are post-hoc disambiguated.** Many ambiguities were fixed by appending explicit rules to the question, or by accepting multiple gold variants. Synthetic data that copies the *original* terse style would be harder and more ambiguous than the current test set. To match the current style, the generator should emit explicit tie-break, rounding and output-column clauses, and keep a minority of genuinely ambiguous items paired with multiple gold variants.
- **Where the hardness comes from.** The local DBs do not meet the paper's stated >200-column criterion (median 77). Local hardness therefore comes from question logic and data quirks, not schema retrieval. This supports building replicas on other mid-size relational DBs rather than giant warehouses.
- **Likely tutorial origins of the schemas.** From table names, bank_sales_trading and modern_data look like assemblies of public SQL case-study datasets (weekly sales, customer nodes and transactions, interest metrics, shopping-cart events, pizza-runner). complex_oracle resembles Oracle's Sales History sample schema. education_business mixes course datasets (an AtliQ-style hardware fact table and web_accounts/web_events). This fits the paper's statement that queries came "from tutorials and forums", but the specific attributions are unverified.
- **Effect of scoring rules on the judge.** Scoring rules alone decide many outcomes:
  - extra columns are harmless;
  - extra or missing rows are fatal;
  - fractions versus percentages fail (absolute tolerance 0.01);
  - unrounded versus 2-decimal values usually pass;
  - NULL versus 0 passes, wrongly;
  - row misalignment can pass under `ignore_order`.
  
  Judge-training labels should therefore be computed with the official comparator plus all variants, so the judge learns the conventions it is actually scored under.
- **Expect noisy synthetic golds.** About 45% of Spider 2.0 examples had errors at first validation, and audits still found high error rates later. Synthetic golds should be expected to be at least as noisy, so independent verification is the main cost to plan for.

### Gaps
- **Leaderboard submission rules.** The submission-guidance Google Doc could not be fetched (redirect then HTTP 400), so its exact rules are not captured.
- **Which local questions came from which tutorials.** The paper's appendix text I retrieved does not list the source per SQLite DB or per local question.
- **Missing error categories.** The remaining categories and percentages of the paper's error analysis (Fig. 23) were not legible.
- **Reproducing the public golds.** The SQLite DBs are not on this laptop (they are on the cluster), so I could not check how many of the 24 public local gold SQLs reproduce the current gold CSVs. Issue #154 and the team's local029 note suggest several do not.
- **How substantive the question rewrites are.** The 82 rewritten questions were not hand-classified; the categories come from keyword counts on added text.

---

## Q2. How were Spider 2.0, BIRD-Interact, LiveSQLBench, BEAVER, Spider2-DBT/ELT-Bench and other 2025–2026 enterprise benchmarks built, and which steps can LLMs automate?

### Takeaway
- **Who did the core work.** Every one of these benchmarks used humans for the core semantic work: writing or rewriting questions, writing gold SQL, and adjudicating.
- **Where LLMs were used.** LLMs appear in narrower roles: paraphrasing (Spider 2.0), instantiating templates mined from real logs (BEAVER v3, with expert review), drafting questions from SQL (BenchPress), user simulation (BIRD-Interact), and auditing golds (SAR-Agent, about 89% flag precision).
- **How LiveSQLBench and BIRD-Interact stay fresh.**
  - They ship new databases each release.
  - They withhold solution SQL, test cases and knowledge from the public files; these are released only on request.
  - One release's hidden test set becomes the next release's dev set.
  - Each database has a DAG-structured knowledge base whose items reference each other.
  
  Their implementation-level ambiguity taxonomy (decimal, join, distinct, sort, NULL, rank, divide-by-zero) maps closely onto our error types.

### Cited Findings

#### Spider 2.0 / Spider2-DBT
- **Spider 2.0.** Construction is covered in Q1: 1,021 tutorial and forum SQL queries collected, 547 kept, then surface and semantic rewrites by 8 expert authors. LLMs were used only for paraphrasing. Every example had at least three reviewers, and errors fell from 45% to 5% across two validation rounds — [Spider 2.0](https://arxiv.org/html/2411.07763)
- **Spider2-DBT.** It replaced the original agentic Spider 2.0 setting on 2025-05-22 with "only 68 tasks" — [Spider2 README](https://github.com/xlang-ai/Spider2). The DBT README says "69 examples of DuckDB data transformation project", which conflicts with that count — [spider2-dbt/README.md](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-dbt/README.md). Its projects come from the 157 Fivetran/DBT projects collected, 78 kept — [Spider 2.0](https://arxiv.org/html/2411.07763)
- **2026 audits of the DBT evaluation.**
  - ignore_order accepts row-scrambled tables — [#200](https://github.com/xlang-ai/Spider2/issues/200)
  - Published scores mix /64 and /68 denominators — [#201](https://github.com/xlang-ai/Spider2/issues/201)
  - The numeric tolerance is defeated by a string-based sort — [#225](https://github.com/xlang-ai/Spider2/issues/225)
  - A reference relation is nondeterministic (f1001) — [#230](https://github.com/xlang-ai/Spider2/issues/230)
  - Gold databases are missing graded tables — [#224](https://github.com/xlang-ai/Spider2/issues/224)

#### ELT-Bench (Jin, Zhu, Kang; arXiv 2504.04808; PVLDB 19)
- **Scale.** 100 pipelines, 835 source tables and 203 data models — [ELT-Bench](https://arxiv.org/html/2504.04808v2)
- **Sources.** 78 of BIRD's 80 open-source DBs (the authors manually checked and corrected BIRD's questions and SQL) and 22 DBs from Fivetran's dbt-package repositories. Data models were derived from BIRD questions, generalised to all entities: about 3 derived columns plus 5 aggregated, categorical or ranked columns each — [ELT-Bench](https://arxiv.org/html/2504.04808v2)
- **Ground truth.** Written by the authors: Airbyte configs, plus BIRD or Fivetran SQL adapted or written from scratch.
- **Verification.** About 10 extra test queries per data model, checked against source tables. This took 3–5 hours of manual work per pipeline, and no LLM annotation is described — [ELT-Bench](https://arxiv.org/html/2504.04808v2)
- **Metrics.** SRDEL checks row counts; SRDT counts a data model correct if it contains all ground-truth columns, with extras allowed.
- **Results.** The best configuration (Spider-Agent + Claude-3.7-Sonnet with extended thinking) reached 57% SRDEL and 3.9% SRDT, at $4.30 and 89.3 steps per task — [ELT-Bench v2](https://arxiv.org/html/2504.04808v2). A catalogue summary cites 11.3% for another version (unverified) — [search summary of the PVLDB listing](https://www.vldb.org/pvldb/volumes/19/paper/ELT-Bench%3A%20An%20End-to-End%20Benchmark%20for%20Evaluating%20AI%20Agents%20on%20ELT%20Pipelines)

#### BEAVER (arXiv 2409.02038; v3 dated 2026-05-13)
- **Warehouses.** Three private warehouses: DW (Oracle, 97 tables and 1,530 columns), NW (MySQL, 366 tables and 2,708 columns) and SP (MySQL, 349 tables and 2,717 columns). Instance-level anonymisation was applied before public release — [BEAVER v3](https://arxiv.org/html/2409.02038v3)
- **Real versus synthetic queries.** Of 9,128 pairs, 254 come from real query logs (one month of logs) and **8,874 are synthesized** by "Structural Template Recomposition". That process uses 594 templates mined from the logs (base, nesting, CTE, domain-knowledge), instantiated and composed by GPT-5.2 with expert review at each step. Nesting and CTE chaining are capped at two levels — [BEAVER v3](https://arxiv.org/html/2409.02038v3)
- **Question writing.** Questions were written by 6 graduate students and 6 professional DBAs, not LLMs. LLM checkers only flagged unclear phrasing. Each question had at least 2 student and 2 DBA reviewers, with about 83% agreement. SQLGlot and sqlparse drafted the table and join-key annotations, which humans verified — [BEAVER v3](https://arxiv.org/html/2409.02038v3)
- **Per-query statistics.** 316.7 tokens, 4.0 tables, 5.7 joins, 8.0 functions, 3.7 CTEs.
- **Results.** The best EX is 11.4% (ReFoRCE + Claude-4.5-Sonnet). The abstract cites 30.1% with oracle subtask hints; the tables show about 26%.
- **Error analysis.** Grouping and ordering 22.8%, advanced functions 14.2%, column selection 12.5%, table selection 11.8%, joins 10.9%, omitted predicates 10.6%, wrong literals 7.4% — [BEAVER v3](https://arxiv.org/html/2409.02038v3)
- **Earlier versions.** These were much smaller; a secondary summary reports about 203 questions — [search summary](https://www.themoonlight.io/review/beaver-an-enterprise-benchmark-for-text-to-sql). The team's Oct-2026 note judged BEAVER unusable (no licence or repository) — [team memory](/Users/deepikapalagani/.claude/projects/-Users-deepikapalagani-Documents-nl2sql-databao/memory/nl2sql-judge-training-data-overlap.md)

#### BenchPress (CIDR 2026)
- **Workflow.** BenchPress is a human-in-the-loop system that turns SQL query logs into benchmarks. An LLM with RAG proposes several candidate natural-language questions per logged SQL, and domain experts select, rank or edit them.
- **Results.** It claims "drastically" reduced effort, but the page gives no numbers — [BenchPress](https://vldb.org/cidrdb/2026/benchpress-a-human-in-the-loop-annotation-system-for-rapid-text-to-sql-benchmark-curation.html)

#### LiveSQLBench (BIRD team)
- **Freshness mechanism.**
  - "Contamination-free, continuously evolving" (also called BIRD-SQL Pro v0.5).
  - The hidden test set of one release becomes the open dev set of the next.
  - "Business rule drift": knowledge-base rules change across releases.
  - Solution SQL, test cases and external knowledge are kept out of the public jsonl to limit crawling, and are emailed on request (bird.bench25@gmail.com).
  
  Source: [LiveSQLBench GitHub](https://github.com/bird-bench/livesqlbench), [HF card](https://huggingface.co/datasets/birdsql/livesqlbench-base-lite)
- **Releases.**

  | Release | Date | Tasks | DBs | Notes |
  |---|---|---|---|---|
  | Base-Lite | 2025-05-30 | 270 | 18 | 180 SELECT + 90 management; a SQLite version came out 2025-07-28 |
  | Base-Full v1 | 2025-09-04 | 600 | 22 | |
  | Large-v1 | 2026-03-02 | 480 | 18 | about 1K columns per DB, about 84K-token prompts |

  The README also says each release adds "50 new" databases, which conflicts with the 18/22/18 counts — [GitHub](https://github.com/bird-bench/livesqlbench)
- **Knowledge base format.** Each HKB-JSON item has `id`, `knowledge`, `description`, `definition`, `type` and `children_knowledge` (a list of dependency ids, or -1) — [HF card](https://huggingface.co/datasets/birdsql/livesqlbench-base-lite)
- **Task format.** Task fields include `preprocess_sql`, `clean_up_sql`, `test_cases`, `conditions`, `high_level` and `difficulty_tier`.
- **Evaluation.** SELECT tasks use "Soft EX"; management tasks use custom test cases. Everything runs in Docker with PostgreSQL. The HF card gives inconsistent licences (CC-BY-4.0 and CC-BY-SA-4.0) — [HF card](https://huggingface.co/datasets/birdsql/livesqlbench-base-lite)
- **Released tooling.** Docker images and dumps, `run_eval.sh` and related scripts, HF datasets, LiveSQLBench-Agent (Google ADK, 30-step budget) and LiveSQLBench-CLI (Harbor) — [GitHub](https://github.com/bird-bench/livesqlbench)
- **Databases.** They are "built from regularly updated CSV datasets and curated by the BIRD team through expert collaboration". No LLM use is described — [GitHub](https://github.com/bird-bench/livesqlbench)

#### BIRD-Interact (arXiv 2510.05318; ICLR 2026)
- **Base.** Built on LiveSQLBench; the knowledge base is a DAG supporting multi-hop chains such as "urgent care" → "AVS" → "IF/CPI" — [BIRD-Interact v3](https://arxiv.org/html/2510.05318v3)
- **Injected ambiguities.**
  - User-query, intent level: lexical, syntactic, semantic, schema linking, query intent, knowledge linking.
  - User-query, implementation level: **Decimal, Join, Distinct, Sort, Null, Rank, Divide-by-zero**, annotated only when the matching construct appears in the solution.
  - Knowledge ambiguities: one-shot masking, and breaking an intermediate node of a chain.
  - Environmental: noisy data and NULLs in critical fields.
  
  Each ambiguity is paired with a ground-truth SQL snippet that serves as the clarification. The quality rule is "unsolvable without clarification, reconstructable with it" — [BIRD-Interact App. H](https://arxiv.org/html/2510.05318v3)
- **Follow-up sub-tasks.** Six categories: constraint change, topic pivot, attribute change, result-based, aggregation, state-dependent — [App. H.5](https://arxiv.org/html/2510.05318v3)
- **People and quality control.**
  - 33 candidates applied; 12 were admitted with a qualification score of at least 90%.
  - Qualification required reproducing tasks, injecting ambiguities, writing follow-ups and validating against test scripts.
  - A final review by 10 experts of 300 samples accepted 97.3% (98.7% on SQL, 95.3% on ambiguity annotation).
  - Inter-annotator agreement is reported as 93.50 (Full) and 93.33 (Lite).
  
  Source: [App. C, Q](https://arxiv.org/html/2510.05318v3)
- **Where LLMs are used.** In the two-stage, function-driven user simulator (AMB/LOC/UNA actions). On UserSim-Guard, unanswerable-request failures fell from 67.4% to 2.7%. Agreement with 100 human-run tasks had Pearson r = 0.84 — [BIRD-Interact](https://arxiv.org/html/2510.05318v3)
- **Size and results.** Full has 600 tasks (410 BI, 190 DM); Lite has 300. GPT-5 reaches 8.67% (c-Interact) and 17.00% (a-Interact) success.
- **Licence.** CC BY-SA 4.0. The paper contrasts this with Spider 2.0's "restricted licensing" — [BIRD-Interact](https://arxiv.org/html/2510.05318v3). By contrast, the Spider2 repository's LICENSE file is MIT — [LICENSE](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/LICENSE)

#### EntSQL (arXiv 2606.03363 v2, June 2026)
- **Scale and data.** 1,066 aligned Chinese–English examples in five business domains. The data come from real enterprise operational data: 15 DB groups, 35 tables, 1,489 columns. Dimension tables were anonymised and the mappings propagated through join keys — [EntSQL](https://arxiv.org/html/2606.03363v2)
- **Authoring.** Questions come from real user Q&A logs. Domain experts wrote, for each item, the gold SQL, concise evidence snippets, and a synthesized domain document of about 3.5–5.3k tokens. The documents cover metric definitions, reporting conventions, fiscal-year rules, org and product mappings, and adjustment policies. Review was multi-round. No LLM role in authoring is stated — [EntSQL](https://arxiv.org/html/2606.03363v2)
- **Results.**

  | Setting | Best system (Claude Code) | Experts, 212-item subset |
  |---|---|---|
  | Base (question only) | 6.8% | 33.5% |
  | With full document | 15.9% | 46.2% |
  | With concise evidence | 21.4% | 84.0% |

  There is no dedicated contamination analysis; private knowledge is the safeguard — [EntSQL](https://arxiv.org/html/2606.03363v2)

#### LLM-automated auditing and error mining
- **SAR-Agent.** It produces per-example diagnostics: ambiguity, SQL correctness, and a proposed fix. Precision was 89% on Snow and 83% on BIRD Mini-Dev, with humans adjudicating every flag — [arXiv 2601.08778v3](https://arxiv.org/html/2601.08778v3)
- **NL2SQL-Bugs.**
  - Built from BIRD dev, with candidates from RESDSQL, CodeS and CHESS.
  - Labels come from execution match against verified golds; annotator agreement κ = 0.78.
  - 2,018 instances (999 incorrect).
  - LLM detection accuracy averages 75.16%.
  - The authors' detection pipeline found gold errors in 1.55% of Spider dev and 6.91% (106) of BIRD dev.
  
  Source: [NL2SQL-Bugs](https://arxiv.org/html/2503.11984), [project page](https://nl2sql-bugs.github.io/)

### Inferences
- **Which construction steps LLMs can take over** (synthesised from the above):

  | Step | Automatable? |
  |---|---|
  | DB profiling and trap discovery | Yes (scripts) |
  | SQL drafting from templates or skeletons | Yes, with execution checks (BEAVER v3, YORO, SING-SQL) |
  | Question drafting from SQL | Partly: LLM drafts, human or second-model selection (BenchPress) |
  | Paraphrasing | Yes (Spider 2.0) |
  | Gold auditing | Partly: an agent flags, a human or second agent adjudicates (SAR-Agent) |
  | Ambiguity enumeration | Yes, generating alternative readings |
  | Multi-variant golds | Yes, if each variant is executed and kept distinct |
  | Deciding the "intended" reading and validating domain rules | Still human-heavy |

- **Why rules sit in documents in LiveSQLBench.** Its design (rules live in a knowledge base, not the question; ambiguity paired with a resolving snippet; test cases) is directly reusable for us. Our "overlapping status categories" and "label convention" errors are naturally expressed as knowledge-base or document rules that the correct SQL must apply. The judge must then check candidates against the document, exactly as the Spider 2.0-Lite external-knowledge tasks require.
- **Mapping BIRD-Interact's implementation-level ambiguity types to our errors:**
  - Distinct/Join → fan-out;
  - Divide-by-zero/Null → denominator;
  - Rank/Sort → ties and answer shape;
  - Decimal → formatting.
  
  These can be used as generator categories.
- **Practical reuse.**
  - LiveSQLBench-Base-Lite-SQLite could serve as a held-out validation set for the judge (it is a different benchmark with its own databases), or it could be used for training. It cannot be both training data and an independent evaluation.
  - LiveSQLBench's knowledge-base JSON schema is a good format for our synthetic "external knowledge" documents.

### Gaps
- **LiveSQLBench internals.** I found no description of how its tasks and knowledge bases are written internally (LLM drafting or not), or what the per-release database refresh mechanism is beyond the README claims.
- **EntSQL's LLM involvement.** Not stated, nor is any per-item execution verification.
- **BEAVER v3 release status.** The data's release status and licence were not verified.
- **Other 2025–26 benchmarks not researched.** DAComp, FDABench and BIRD-Critic/SWE-SQL construction details were not fetched; they are left to the dataset-catalogue researcher.

---

## Q3. Which question and SQL patterns exercise our eight error types, does any benchmark target them, and how do we build Spider2-like questions with verified gold SQL on other databases?

### Takeaway
- **Prior coverage.** No benchmark targets exactly our eight semantics. They are partly covered by:
  - BIRD-Interact's implementation-level ambiguities (Join, Distinct, Rank, Sort, Null, Divide-by-zero, Decimal);
  - NL2SQL-Bugs' taxonomy (join type and condition mismatch, DISTINCT, aggregate and window misuse, implicit-condition missing);
  - the audit's "row inflation" and "output format" classes;
  - BI-tool literature on fan and chasm traps.
- **These errors occur in Spider 2.0-Lite's own golds** (fan-out in local029, a boundary operator in local085, grain in local060, ties in local029 and local331), which confirms they are realistic.
- **Recipe.**
  1. Profile non-Spider2 SQLite DBs for data conditions that make each error change the answer.
  2. Write the gold for a templated analytic question.
  3. Mutate the gold into the typical wrong reading and keep only items where the gold and the mutant differ under the official comparator.
  4. Verify the gold by an independent blind re-solve plus an audit agent.
  5. Use perturbed copies of the DB, test-suite style, to confirm the gold survives and the mutant fails.

### Cited Findings
- **Fan and chasm traps.** A fan trap arises when "two many-to-one joins follow one another in primary-detail form… and the query includes a measure from both the leaf table… and its immediate primary" — [Sisense docs](https://docs.sisense.com/main/SisenseLinux/chasm-and-fan-traps.md). A chasm trap joins two "many" tables through a shared "one" table and double-counts both, e.g. Product with Sales and Returns — [Coginiti glossary](https://coginiti.co/glossary/fan-chasm-traps/)
- **How BI tools fix fan-out.**
  - Looker's symmetric aggregates detect fan-out from one-to-many join declarations and apply distinct-key sums and counts — [Looker community](https://discourse.looker.com/t/outer-join-on-false-or-how-i-learned-to-stop-fanning-out-and-love-the-null/4786)
  - Omni checks primary keys before aggregating — [Omni docs](https://docs.omni.co/analyze-explore/sql/symmetric-aggregates)
  - The manual fix is to pre-aggregate each measure at its own grain before joining — [Coginiti](https://coginiti.co/glossary/fan-chasm-traps/)
  - Snowflake documents double counting as a text-to-SQL failure that its semantic layer prevents — [Snowflake engineering blog](https://www.snowflake.com/en/blog/engineering/snowflake-cortex-analyst-introducting-joins-complex-schemas/)
- **Spider 2.0-Lite golds exhibiting our error types:**
  - Fan-out: local029 joins payments, then counts orders, so it counts payment rows (one customer showed 2 delivered orders against 33 payment-join rows) — [#216](https://github.com/xlang-ai/Spider2/issues/216)
  - Ties: local029's tie-break is unspecified, with several customers tied at 7 orders — [#160](https://github.com/xlang-ai/Spider2/issues/160). local331 has duplicate timestamps, so window ordering is nondeterministic — [#168](https://github.com/xlang-ai/Spider2/issues/168)
  - Boundary operator: "on or after" in the question versus `>` in the gold — [#163](https://github.com/xlang-ai/Spider2/issues/163)
  - Grain: pooled versus per-city ranking — [#159](https://github.com/xlang-ai/Spider2/issues/159)
  - Calendar completeness and shape: "each month of 2020" with data only for January–April leaves empty months that decide the minimum — [gold_sensitive_tasks.yaml](/Users/deepikapalagani/Documents/nl2sql-databao/nl2sql-v2/scripts/gold_sensitive_tasks.yaml)
  - Entity counting: local196's old gold counted payments as rentals — [gold_sensitive_tasks.yaml](/Users/deepikapalagani/Documents/nl2sql-databao/nl2sql-v2/scripts/gold_sensitive_tasks.yaml)
- **Audit classes.** E2 row inflation (JOIN or FLATTEN without dedup, including sf_local263). E4 output-format and ambiguity issues, e.g. an unstated quote replacement. E1 end-of-day timestamp truncation — [arXiv 2601.08778v3](https://arxiv.org/html/2601.08778v3)
- **BIRD-Interact's implementation-level ambiguity types** are Decimal, Join, Distinct, Sort, Null, Rank and Divide-by-zero. Each is paired with a resolving SQL snippet, and the quality rule is that the query is unsolvable without the snippet and reconstructable with it — [BIRD-Interact App. H.4](https://arxiv.org/html/2510.05318v3)
- **NL2SQL-Bugs taxonomy.** Nine classes, 31 subtypes. The relevant subtypes are:
  - Join Type Mismatch and Join Condition Mismatch;
  - Aggregate Functions (missing GROUP BY or misread effect) and Window Functions (wrong partition or frame);
  - Math (ROUND precision) and Comparison Operator (`>` versus `>=`);
  - Implicit Condition Missing (e.g. NULL handling);
  - DISTINCT; ASC/DESC; Clause Missing or Redundant;
  - Attribute Missing or Redundant (output columns).
  
  Type-specific detection accuracy was **0% for every model** on Join Type Mismatch, Window Functions and Partial Query, and no model reached 50% accuracy at identifying error types. The paper has no dedicated ranking, LIMIT, grain or output-format classes — [NL2SQL-Bugs](https://arxiv.org/html/2503.11984)
- **Test-suite accuracy** (Zhong, Yu, Klein, EMNLP 2020) "distills a small test suite of databases that achieves high code coverage for the gold query" from many randomly generated DBs, to approximate semantic accuracy. The authors say the then-current Spider metric "leads to a 2.5% false negative rate on average and 8.1% in the worst case" — [arXiv 2010.02840](https://arxiv.org/abs/2010.02840)
- **Synthesis pipelines worth copying.**
  - YORO: extract SQL skeletons from existing training SQL; have an LLM fill the placeholders for the target DB; execute and drop errors; generate the question by in-context learning. Claude-3-Sonnet at temperature 0.9 for SQL and 0.0 for questions — [YORO, NAACL 2025](https://aclanthology.org/2025.naacl-long.94.pdf)
  - SING-SQL: hierarchical sub-schema partitioning, SQL at several complexity levels, an LLM-as-judge, executability checks, automatic repair and column balancing — [SING-SQL arXiv 2509.25672](https://arxiv.org/abs/2509.25672)
  - BEAVER v3: templates mined from logs and recomposed by an LLM under expert review — [BEAVER v3](https://arxiv.org/html/2409.02038v3)
  - GAZP: keep only cycle-consistent synthesized examples — [GAZP](https://aclanthology.org/2020.emnlp-main.558)
- **Fully automatic LLM annotation is not enough.** A human–LLM collaborative annotation study reports that LLM annotators struggle with diversity and hallucination. Its Adobe formative study found accuracy drops of at least 13.3% for newly added columns and 9.1% for new tables — [arXiv 2502.15980](https://arxiv.org/html/2502.15980v2)
- **Databases to avoid.** These BIRD and Spider *train* databases share schemas with Spider2 local DBs:
  - BIRD: movie_3 = Sakila, retail_world = Northwind, works_cycles = AdventureWorks, soccer_2016 = IPL.
  - Spider: sakila_1, chinook_1, store_1, soccer_1, formula_1, baseball_1.
  
  This mapping came from an automated analysis and has not been hand-verified — [team memory](/Users/deepikapalagani/.claude/projects/-Users-deepikapalagani-Documents-nl2sql-databao/memory/nl2sql-judge-training-data-overlap.md)

### Inferences
The recipes below are proposals synthesized from the findings above. They are not evaluated practice.

#### A. Pipeline for Spider2-like items with verified golds (non-Spider2 SQLite DBs)
1. **Pick databases.**
   - Use mid-size relational SQLite DBs (about 5–40 tables) with business-flavoured, messy data.
   - Exclude every DB whose schema overlaps the 30 local DBs, by table and column-name Jaccard.
   - Keep 20–30% of DBs for judge validation; split by database, not by question.
2. **Profile and find traps.** Use scripts, no LLM. The DCE profile and keys tooling in this repo already computes most of these.
   - Unique-key sets per table; flag tables without declared keys.
   - 1:N fan-out factors per join path, i.e. the share of parents with more than one child.
   - Display names that are not unique across distinct IDs.
   - Status and category columns whose value sets overlap lexically or hierarchically.
   - Ties at plausible top-k cutoffs for numeric measures.
   - NULL and zero rates in candidate denominators.
   - Calendar gaps (months or days with no rows).
   - Text-encoded dates and numbers.
3. **Write the gold SQL.** Pick an analytic pattern at the trap: share of total, rate per population, top-k per group, running balance, cohort or retention, period-over-period growth, RFM-style segmentation, sessionisation, or a lifecycle derived from status. Model A (an LLM) writes the gold in Spider2 style: CTE chain, 100–350 tokens, 2–4 base tables.
4. **Write the question.** Model B writes a 40–70-word question from the SQL, in the current post-revision Spider2 style:
   - name the output columns;
   - state the tie-break and rounding;
   - define terms, or put the definition in a short document of 60–900 words, as in about 10% of local tasks.
   
   For a minority of items, deliberately leave one natural ambiguity, enumerate its readings, and store each reading's result as a gold variant, as Spider2 does with `_a`/`_b`.
5. **Blind re-solve (cross-validation).** Two other solvers, ideally different model families or our agent, solve the question without seeing the gold.
   - Accept when one of them matches the gold under the official comparator.
   - Otherwise send the item to an audit agent in the style of SAR-Agent (verification queries, diagnosis) and then to adjudication by a human or a stronger model.
   - Expect a high first-pass error rate: Spider 2.0 itself had 45%.
6. **Discrimination check.**
   - Apply the error-type mutator(s) to the gold (cards below).
   - Keep the item only if every mutant's result *differs* from the gold, and from all its variants, under the official comparator: `condition_cols`, `ignore_order`, 0.01 tolerance, NULL→0.
   - If they do not differ, the trap is inactive in this data; drop the item or choose another parameter.
7. **Perturbation check (test-suite style).** Make 3–5 perturbed copies of the DB that add exactly one stressor: an extra child row, a tied value at the cutoff, a duplicate display name, an overlapping status value, a NULL in the denominator column. Confirm the gold's answer changes only as the semantics require and that the mutant diverges, which separates robust golds from coincidentally right ones.
8. **Evaluation spec.**
   - Set `condition_cols` to the essential columns (39% of local tasks use them).
   - Set `ignore_order: true` unless order is requested (all current locals are true).
   - Add variants only for genuinely ambiguous readings; Spider2 averages about 2.4 gold CSVs per local task.
9. **Build judge-training candidate sets.**
   - Run our agent 4 times per item to harvest natural candidates.
   - Where the agent's wrong answers do not reproduce the target failure, add mutants. Ideally use two *different* mutants with identical results (e.g. fan-out via two join paths), to imitate "2–3 candidates agree on the same wrong answer".
   - Render exactly what the judge sees: question, document, schema, SQL, and a result preview.
   - Label correctness with the official comparator and all variants, and tag the error type for per-type analysis.

#### B. Error-type cards (question pattern → correct SQL → majority-wrong SQL → data precondition)
1. **Wrong grain or granularity.**
   - Questions: "average daily revenue per store", "average of each customer's monthly spend", "rank products within each qualifying city" versus pooled ranking.
   - Correct: aggregate to the stated grain in a CTE, then aggregate up.
   - Wrong: one GROUP BY at the wrong level, or AVG over raw rows.
   - Precondition: unequal group sizes, so the mean of means differs from the pooled mean. Also check calendar completeness: an "each month" question needs a zero-filled calendar (LEFT JOIN to a generated month list).
2. **Wrong denominator.**
   - Questions: "percentage of late orders among employees with more than 50 orders", "share of customers who…", "rate per active user".
   - Correct: the denominator is the population the question names, computed separately.
   - Wrong patterns:
     - The filter is applied in WHERE, so the denominator shrinks.
     - COUNT(col) skips NULLs where COUNT(*) is needed.
     - SQLite integer division (`a/b` with integers truncates).
     - Dividing by the post-join row count.
   - Precondition: the filtered and unfiltered populations differ; NULLs or zeros exist; integer columns.
3. **Join fan-out inflating aggregates.**
   - Questions: totals of order-level amounts alongside item-level or payment-level facts; counts of orders per customer when payments or items are joined.
   - Correct: pre-aggregate each child at parent grain (`WITH pay AS (SELECT order_id, SUM(value) … GROUP BY order_id)`), or `COUNT(DISTINCT order_id)`.
   - Wrong: SUM or COUNT after a 1:N join (fan trap), or joining two 1:N children at once (chasm trap).
   - Precondition: the fan-out factor is above 1 for some parents in scope; check the mutant changes the top-k membership or the totals.
4. **Overlapping status categories.**
   - Questions: "completed", "active", "cancelled" or "churned" defined by a document or knowledge-base rule over several codes (e.g. delivered + invoiced; canceled + unavailable), or hierarchical statuses (a returned order is also a delivered order).
   - Correct: an explicit IN-list or CASE from the rule, applied at the right event (latest status per entity).
   - Wrong:
     - A single literal.
     - `LIKE '%complete%'`, which also catches "incomplete".
     - Counting every status row instead of the latest.
     - Double-counting entities that sit in two categories.
   - Precondition: entities with several status rows, and lexically overlapping codes. Put the rule in a document, LiveSQLBench-knowledge-base-style, so the judge must consult it.
5. **Keying on a name instead of an ID.**
   - Questions: "top 5 customers or artists or players by …, with their names".
   - Correct: `GROUP BY id` (then join the name).
   - Wrong: `GROUP BY name`, which merges homonyms, or joining on a name across tables.
   - Precondition: verify by query that at least one name is shared by two or more IDs in scope and that merging changes the result (the uniqueness checks in this repo's key computation do this).
6. **Wrong answer shape.**
   - Questions: "which X has the highest …" (one row) versus "list the top 3 …" versus "for each region, the top product" (one row per group), plus explicitly requested companion columns.
   - Majority errors: returning the full ranked list where one row is expected, one row where one per group is expected, or omitting a requested column.
   - Note that extra columns pass the scorer but extra rows fail; 45 of 135 local golds are single-row.
   - Precondition: none; vary the phrasing across these three templates on the same data.
7. **Ties at a cutoff.**
   - Questions: top-k or bottom-k where the k-th and (k+1)-th values tie, or "the month with the lowest …" where several months tie, including empty months.
   - Correct, two options: (a) the question states the tie-break (current Spider2 style, e.g. alphabetical), and the gold uses `ORDER BY measure DESC, name ASC`; or (b) the question says to include ties, and the gold uses `RANK() … <= k`.
   - Wrong: `LIMIT k` with an arbitrary tie order; ROW_NUMBER where RANK is meant; ordering nondeterministic under duplicate timestamps.
   - Precondition: a tie exists exactly at the cutoff. Keep a few items with unstated tie-breaks and all-tied-row variants, mirroring the tie-fragile local tasks.
8. **Output formatting and label conventions.**
   - Questions: "percentage, rounded to 2 decimals", "month as YYYY-MM", "segment labels as defined in the document", "full name as 'First Last'", "difference in millions".
   - Correct: apply the scale, label strings and date format exactly; the scorer compares strings exactly and numbers within an absolute 0.01.
   - Wrong: a fraction instead of a percentage; a missing ×1e-6; a month name instead of a code; label casing or spelling that differs from the document; a concatenation order.
   - Precondition: none, but check the mutant fails under the comparator. Rounding differences of 0.005 or less pass, so they are *not* useful negatives.

#### C. SQLite-specific traps worth adding (local split is SQLite)
- Integer division.
- Text-stored dates, where JULIANDAY or STRFTIME on non-ISO strings returns NULL.
- Bare (non-aggregated) columns in GROUP BY queries, which SQLite allows and which take a value from an arbitrary row.
- NULL sort position.
- Trimming and casing in string keys; the public local golds lean heavily on TRIM, SUBSTR and INSTR.

These are this researcher's domain knowledge, not taken from the sources above.

### Gaps
- **No benchmark covers our eight types directly.** I found none that targets denominators, overlapping status categories, name-versus-ID keying, or ties at a cutoff as first-class categories. Their coverage is inferred from broader taxonomies.
- **No measured mutant hit-rates.** I found no published data on how often LLM-written golds exhibit each of these errors, or how often mutation-based negatives match real agent errors. Measure this on our own harvested candidates first.
- **CodeS details unverified.** CodeS's "bi-directional data augmentation" for new-domain adaptation was confirmed only at abstract level: the abstract mentions financial and academic datasets but gives no mechanism — [arXiv 2402.16347](https://arxiv.org/abs/2402.16347).

---

## Q4. Is generating synthetic training data on Spider 2.0-Lite's own databases (never its questions) accepted, and how should it be reported?

### Takeaway
- **What the maintainers forbid.** They clearly forbid training on Spider 2.0 *data*: "cannot be used for training", "no train set or dev set, only a test set", and they do not recommend fine-tuning on the released gold SQL.
- **What they have not addressed.** They have said nothing about synthesizing new questions on the test *databases*. The leaderboard relies on "academic integrity" and flags only the oracle-tables setting.
- **Precedent exists but must be disclosed.**
  - GAZP (2020) adapts a parser by synthesizing data in the new, inference-time environment with no labels.
  - YORO (NAACL 2025) trains per-database experts on synthetic data for the evaluation DBs. It openly states that the dev sets were used as test sets because the method needs DB access, and it reports gold-versus-synthetic SQL overlap (under 0.5%).
  - SING-SQL frames per-target-DB synthesis as its goal.
  - CHASE-SQL synthesizes test-question-specific examples at inference time.
- **Treat test-DB synthesis as a separate "transductive" condition.** Report it separately from a clean inductive condition, with decontamination statistics.

### Cited Findings
- **Maintainer: no training on Spider 2.0 data.** "Unfortunately, the data from Spider 2.0 is currently used for testing and cannot be used for training" (maintainer lfy79001) — [Issue #49](https://github.com/xlang-ai/Spider2/issues/49)
- **Maintainer: test set only, honour system.** "Spider 2.0 does not have a train set or dev set, only a test set." Leaderboard submissions rely "entirely on academic integrity as we do not have an anti-cheating mechanism in place" — [Issue #8](https://github.com/xlang-ai/Spider2/issues/8)
- **README on gold SQL.** "We do not recommend using the Spider 2.0 Gold SQL we released for fine-tuning" — [Spider2 README](https://github.com/xlang-ai/Spider2). A 2025-01-07 news item, now commented out in the README, gave the reason: "it may affect the fairness of evaluation and hinder better benchmarking of the model's SQL capabilities. The release of Gold SQL is intended to help users design prompts" — [README source, local copy](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/README.md)
- **Partial gold release is deliberate.** "To ensure fairness in the competition, we won't be releasing all of the gold SQL" — [Issue #23](https://github.com/xlang-ai/Spider2/issues/23)
- **Leaderboard flags.** Oracle-table methods must be declared and are excluded from the Snow ranking. Test-time database access and synthetic data are not addressed on the leaderboard page — [spider2-sql.github.io](https://spider2-sql.github.io/). Submissions must include run logs (maintainer reply) — [Issue #97](https://github.com/xlang-ai/Spider2/issues/97)
- **GAZP (EMNLP 2020).** It adapts "an existing semantic parser to new environments (e.g. new database schemas)". It synthesizes utterance–SQL pairs "in the new environment", keeps cycle-consistent ones, and contrasts this with augmentation "in the training environment". It improved logical-form and execution accuracy on the Spider, SParC and CoSQL zero-shot tasks — [ACL Anthology](https://aclanthology.org/2020.emnlp-main.558), [arXiv 2009.07396](https://arxiv.org/abs/2009.07396)
- **YORO (AWS, NAACL 2025).**
  - It trains a text-to-SQL "expert" per target database on LLM-synthesized pairs (Claude-3-Sonnet) mixed with the original training data.
  - "We use the official dev sets as our test set because our method needs to access the target database for knowledge acquisition." It also avoids BIRD oracle knowledge as "not a realistic setting".
  - It reports overlap: the share of test gold SQL that exactly matches any synthetic SQL is 0.48% (Spider dev), 0.37% (KaggleDBQA) and 0.07% (BIRD dev), using parse-based match for Spider and KaggleDBQA and string match for BIRD.
  - Adding 100 synthetic examples per target DB raised accuracy by 20.7–46.8 points over 0.5–19.0% without them. This is in YORO's no-schema-in-prompt setting, so the gains are not comparable to schema-in-prompt systems.
  
  Source: [YORO, NAACL 2025, pp. 1889–1901](https://aclanthology.org/2025.naacl-long.94.pdf)
- **SING-SQL (Sept 2025).** Synthesizes data "for any target database, without relying on SQL logs or manual annotations", motivated by specialising to a single schema. It reports BIRD-subset results (3B model: 82.87% Soft F1, 73.03% EX upper bound with 32 candidates) — [arXiv 2509.25672](https://arxiv.org/abs/2509.25672)
- **CHASE-SQL.** Uses an instance-aware online synthetic-example generator that produces few-shot demonstrations tailored to each test question. This is in-context use of the test DB, not training — [CHASE-SQL arXiv 2410.01943](https://arxiv.org/abs/2410.01943) (summary via search results)
- **Test-time training elsewhere.** ARC Prize 2024 credits test-time training as a key ingredient of the jump in the state of the art from 33% to 55.5%. It defines "transductive" models as those that predict outputs directly from the test input — [ARC Prize 2024 report](https://arxiv.org/abs/2412.04604), [ARC Prize blog](https://arcprize.org/blog/arc-prize-2024-winners-technical-report)
- **How newer benchmarks avoid the question.** They hide solutions and test cases and add new DBs every release (LiveSQLBench), or use private knowledge (EntSQL) — [LiveSQLBench](https://github.com/bird-bench/livesqlbench), [EntSQL](https://arxiv.org/html/2606.03363v2)
- **Spider2.0-SQLite as an eval target.** The 135 local tasks are used as an evaluation set by open-weight text-to-SQL work, e.g. OmniSQL's model card lists Spider2.0-SQLite among its evaluation benchmarks — [OmniSQL-32B card](https://huggingface.co/seeklhy/OmniSQL-32B)
- **Contamination inflates scores.** GPT-3.5 drops markedly on the unseen Termite benchmark compared with Spider, which the authors attribute partly to contamination — [Ranaldi et al., Findings ACL 2024](https://arxiv.org/abs/2402.08100)

### Inferences
- **Status.** Synthesizing training questions on the 30 local databases is not prohibited by any rule I found. It violates the spirit of a test-only benchmark more than training on outside DBs does, because the model learns the test DBs' quirks: codes, value formats, which joins fan out. Published precedent (YORO, GAZP) treats it as legitimate *only when disclosed and evaluated as its own condition*.
- **Leaderboard.** For a Spider2 leaderboard submission it should be declared, like the oracle-tables flag, and a separate listing should be expected.
- **Recommended reporting protocol:**
  1. Main result: judge trained only on non-Spider2 DBs (inductive).
  2. A second condition adding test-DB synthetic data (transductive), labelled as such.
  3. Report per-DB gains to show whether improvements concentrate on DBs with synthetic coverage.
  4. State that no test question, gold SQL or gold result was used in generation prompts, few-shot examples or filtering. The single exception is decontamination against the 135 questions and 24 public golds, which should be stated.
  5. Publish decontamination statistics in YORO style: SQL exact and skeleton match rates against the 24 public golds; question n-gram and embedding-plus-LLM paraphrase hits against the 135 questions; result-fingerprint collisions against the 135 gold CSVs.
  6. Publish the generator models, prompts and the synthetic set.
- **The judge context raises the risk.** A judge trained on test-DB synthetic items may learn which result shapes and values are "typical" for each test DB, and could pick answers by DB-specific priors rather than question semantics. Mitigation: hold out some local DBs from synthesis entirely and compare judge accuracy on held-out versus covered DBs.
- **Overlapping schemas count as partial transduction.** If BIRD or Spider train DBs with the same schemas as Sakila, Northwind, AdventureWorks, IPL, Chinook, F1 or Baseball are used, they should be reported as such, or excluded from the inductive condition.
- **Licensing is a separate question from policy.** The Spider2 repo code is MIT, but the SQLite DBs derive from many sources with their own licences. BIRD-Interact describes Spider 2.0's licensing as restricted. Check licences before redistributing any synthetic set built on these DBs.

### Gaps
- **Submission guidance.** The Google Doc could not be read, so I could not confirm whether it addresses fine-tuning, synthetic data or test-DB access.
- **No maintainer statement on synthesis.** I found no statement, in issues or the README, specifically about synthesizing new questions on the Spider 2.0 databases.
- **No leaderboard entry openly reports test-DB synthetic training.** None was found, and none was found to be flagged for it.
- **GAZP numbers unverified.** The exact GAZP gains and which dev or test DBs it adapted to were not verified from the full text; only the abstract-level description was confirmed.

---

## Q5. Which contamination-detection and deduplication techniques should we apply when building the dataset?

### Takeaway
Use a layered filter against the 135 local questions, the 24 public gold SQLs and the 135 gold result CSVs:
- string n-gram overlap;
- embedding top-k plus an LLM judge for paraphrases;
- normalised-SQL exact and skeleton match;
- execution-result fingerprints on the same DB;
- schema-level overlap for DB selection.

Optionally add a masked-schema reconstruction probe to measure how much the base model already knows about each test DB. n-gram filtering alone misses paraphrases, so the embedding-plus-LLM stage is essential.

### Cited Findings
- **Paraphrases evade string matching.** "Simple variations of test data (e.g., paraphrasing, translation) can easily bypass" n-gram decontamination. The proposed LLM decontaminator takes the top-k most similar training items by embedding and asks a strong LLM whether each is a rephrase; it gave the best F1 in the authors' tests. It found 8–18% HumanEval overlap in RedPajama-Data-1T and StarCoder-Data. Code: [github.com/lm-sys/llm-decontaminator](https://github.com/lm-sys/llm-decontaminator) — [arXiv 2311.04850](https://arxiv.org/abs/2311.04850)
- **n-gram filtering in text-to-SQL synthesis.** SemanticAgent applies an n-gram overlap filter against each benchmark's public evaluation split, removing 764 examples (0.76% of its generated corpus) — [arXiv 2604.21414](https://arxiv.org/pdf/2604.21414) (via search summary; not opened in full)
- **SQL overlap reporting.** YORO reports exact-match overlap between test gold SQL and synthetic SQL, parse-based for Spider and KaggleDBQA and string-based for BIRD: all below 0.5% — [YORO](https://aclanthology.org/2025.naacl-long.94.pdf)
- **Model-side probe.** Termite-style detection masks 25% of columns per table in a schema dump and asks the model to reconstruct them. Higher accuracy on public-benchmark schemas than on unseen ones indicates prior exposure — [Ranaldi et al. 2024](https://arxiv.org/abs/2402.08100)
- **Semantic equivalence via distilled test DBs.** Test-suite accuracy can flag semantically equivalent SQL beyond string matches — [arXiv 2010.02840](https://arxiv.org/abs/2010.02840)
- **Schema overlap is real.** BIRD and Spider train DBs share schemas with several Spider2 local DBs (mapping not hand-verified) — [team memory](/Users/deepikapalagani/.claude/projects/-Users-deepikapalagani-Documents-nl2sql-databao/memory/nl2sql-judge-training-data-overlap.md)
- **Benchmark-side anti-crawl.** LiveSQLBench keeps solutions, test cases and knowledge out of public files so that crawlers cannot ingest them — [LiveSQLBench](https://github.com/bird-bench/livesqlbench)

### Inferences
Concrete filter stack, cheapest first:
1. **Database-level filter.**
   - Compute table-name and column-name Jaccard (after lowercasing and snake-casing) between every candidate DB and the 30 local DBs, and flag anything above about 0.5.
   - Also compare value fingerprints: MinHash over distinct values of key text columns, to catch renamed copies such as Sakila/Pagila or Northwind variants.
   - Exclude flagged DBs or report them separately.
2. **Question n-gram filter.** Remove items sharing a 13-gram, or more than 50% of 8-grams, with any of the 135 questions after normalisation. These thresholds follow common LLM decontamination practice and are not taken from a text-to-SQL paper.
3. **Paraphrase filter.** Embed the questions, take the top-5 nearest test questions per synthetic item, and have an LLM judge "same task?". Drop positives. This matters most for test-DB synthesis, where the generator LLM may regurgitate memorised Spider2 questions.
4. **SQL filter.**
   - Parse and normalise with sqlglot: lowercase, canonical aliases, literals masked into a skeleton.
   - Drop exact normalised matches with the 24 public local golds and report skeleton-match rates. Expect skeleton matches for generic patterns such as top-k; report rather than drop them.
5. **Result-fingerprint filter.** Only applies when synthesizing on test DBs. Hash each synthetic gold's result (sorted rows, rounded to 2 dp) and drop collisions with any of the 135 gold CSVs or their variants on the same DB. Same answer on the same DB is the strongest sign of a semantic duplicate.
6. **Model-exposure probe (reporting, not filtering).** Run the Termite-style masked-column probe for the judge's base model on the 30 local DBs versus our synthetic DBs, and report it so readers can judge prior exposure.
7. **Documentation.** Report counts removed at each stage and the final overlap rates, as YORO did.

### Gaps
- **No consensus thresholds.** I found no text-to-SQL-specific study of n-gram or embedding thresholds, or of SQL-skeleton dedup, and no accepted standard for result-fingerprint decontamination.
- **OmniSQL decontamination unknown.** Whether OmniSQL's SynSQL-2.5M was decontaminated against Spider2.0-SQLite was not found (the OmniSQL pipeline is covered by another researcher).
- **SemanticAgent details unverified.** Its n-gram threshold and its exact eval splits were not verified beyond the search summary.
