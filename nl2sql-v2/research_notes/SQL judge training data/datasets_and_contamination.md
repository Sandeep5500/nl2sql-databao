# Text-to-SQL datasets for training and validating a SQL judge, and their overlap with Spider 2.0-Lite (checked 2026-10-27)

**Labels used throughout.**
- **"paper"**: the dataset's own authors state it.
- **"audit"**: a third party measured it.
- **"our count"**: counted on 2026-10-27 from the released files, either by this research effort or by its sub-researchers. The file is linked.
- **"claimed"**: asserted without a measurement we could see.
- Rankings, risk ratings and recommendations appear only under **Inferences**.

The Spider 2.0-Lite reference set is the 135 `local*` instances in [spider2-lite.jsonl](https://github.com/xlang-ai/Spider2/blob/main/spider2-lite/spider2-lite.jsonl) (our count: 547 instances in total, 135 local). Scratch scripts and downloads are under `/private/tmp/claude-501/-Users-deepikapalagani-Documents-nl2sql-databao/f54a9a7d-52ac-46be-8abb-0cac5a1864b1/scratchpad/` (clusterA–D, me_dl, me_scripts).

---

## 1. Large general-purpose sets: BIRD (train, dev, Mini-Dev, test), Spider 1.0, SynSQL-2.5M, Gretel synthetic_text_to_sql

### Takeaway
- **BIRD and Spider** are the only large, human-annotated SQLite sets with real data and public gold.
  - Both are widely used to train Qwen-based models.
  - Both have substantial gold-SQL noise. A 2.5k-sample audit found at least 52.1% wrong gold SQL in BIRD train.
  - Both contain Spider 2.0-Lite local databases that must be dropped: BIRD has 4 train DBs, 1 partial, and 2 dev DBs; Spider has 6 train DBs.
- **SynSQL-2.5M** is huge and CTE-heavy, but its databases hold at most 3 rows per table, so execution previews are nearly empty.
- **Gretel** uses one-table contexts in mixed dialects, and about 22% of its SELECTs fail in SQLite.

### Cited Findings

#### BIRD

**Size and splits**
- 12,751 pairs over 95 DBs (33.4 GB, 37 domains): train 9,428 (69 DBs), dev 1,534 (11 DBs), hidden test 1,789 (15 DBs) ([paper](https://arxiv.org/html/2305.03111)).
- Our count of the released files:
  - train.json has 9,428 rows over 69 db_ids ([train.zip](https://bird-bench.oss-cn-beijing.aliyuncs.com/train.zip)).
  - dev_20240627 has 1,534 rows over 11 DBs ([dev.zip](https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip)).
  - Reasoning-SQL says "70 databases" ([arXiv 2503.23157](https://arxiv.org/abs/2503.23157)), which conflicts.

**Versions to pin**
- Dev "1106" (released 2025-11-13) keeps the same 1,534 IDs with revised questions, evidence and SQL ([site](https://bird-bench.github.io/), [HF](https://huggingface.co/datasets/birdsql/bird_sql_dev_20251106)).
- bird23-train-filtered keeps 6,601 of 9,428 ([HF](https://huggingface.co/datasets/birdsql/bird23-train-filtered)). Our check: it only removes rows; nothing is corrected.
- Mini-Dev, original: 500 pairs in SQLite, MySQL and PostgreSQL, released 2024-06-27, of which 498 are unique ([mini_dev README](https://github.com/bird-bench/mini_dev); [Jin et al.](https://arxiv.org/abs/2601.08778)).
- Mini-Dev V2 (2025-07-22): "780 instances", described as 500 plus "270 new". As written, that sums to 770 ([README](https://github.com/bird-bench/mini_dev)).
- "Mini-Dev 1024" on HF (revision 2026-10-25): only 13 of its 500 questions match the 2025-07-04 release verbatim (our count) ([HF](https://huggingface.co/datasets/birdsql/bird_mini_dev)). Its manifest says all 1,500 dialect-specific gold queries run without error and return non-empty results ([manifest](https://huggingface.co/datasets/birdsql/bird_mini_dev/blob/main/data/manifest.json)).

**Dialect and files**
- SQLite throughout. Sizes from HTTP headers (our check): train.zip 8.92 GB, dev.zip 346 MB, minidev.zip 801 MB.
- Mini-Dev also ships MySQL and PostgreSQL dumps ([card](https://huggingface.co/datasets/birdsql/bird_mini_dev)).

**SQL complexity**
- OmniSQL Table 3, over BIRD train+dev: per SQL, 1.98 tables, 0.94 joins, 0.67 functions, 24.75 whitespace tokens. Across the whole set, only 9 queries use a CTE and 10 use a window function ([OmniSQL](https://arxiv.org/html/2503.02240)).
- Spider 2.0 Table 2 gives BIRD 30.9 tokens per SQL and 54.2 columns per DB ([Spider 2.0](https://arxiv.org/html/2411.07763v2)).
- Our count by version:

  | Version | Tokens/SQL | Share with a CTE | Share with a window function |
  |---|---|---|---|
  | train | 25.8 | 0.0% | 0.1% |
  | dev_20240627 | 25.4 | 0.6% | 0.3% |
  | dev 1106 | 37.4 | 6.6% | 4.4% |
  | Mini-Dev 1024 | 56.0 | 30.0% | 5.0% |

  In Mini-Dev 1024, 460 of the 500 questions are labelled "challenging".
- Difficulty mix conflicts. Paper App. B.1 says 30% simple / 60% moderate / 10% challenging. The dev_20240627 file has 925/464/145, i.e. 60/30/10 (our count).

**External knowledge**
- Every pair has an expert "evidence" sentence of one of four kinds: numeric, domain, synonym, value illustration ([paper](https://arxiv.org/html/2305.03111)).
- Evidence is empty in 645/9,428 train and 148/1,534 dev items (our count).
- Mini-Dev 1024 deliberately removed evidence that leaked schema links or answers ([HF](https://huggingface.co/datasets/birdsql/bird_mini_dev)).

**Real or synthetic**
- Databases are real: 32% from Kaggle, 48% from the CTU Prague relational repository, 20% built from open tables.
- 11 native speakers wrote the questions. Crowd DB engineers wrote the SQL double-blind, and experts checked it ([paper](https://arxiv.org/html/2305.03111)).

**License and terms**
- The datasheet says CC BY-NC 4.0. On 2024-04-27 it changed to CC BY-SA 4.0, "for research and healthy application only" ([site](https://bird-bench.github.io/), [README](https://github.com/AlibabaResearch/DAMO-ConvAI/tree/main/bird)).
- Paper A.7 asks anyone who extends or augments the data to contact the authors first ([paper](https://arxiv.org/html/2305.03111)).

**Annotation errors, dev and Mini-Dev**
- Wretblad et al. 2024 (audit; [ACL](https://aclanthology.org/2024.acl-short.34)):
  - Financial DB, all 106 questions: 52 noisy (49%), 22 wrong gold SQL (20.7%).
  - Wrong gold in 20-question samples from other DBs: California Schools 8/20, Thrombosis 6/20, Toxicology 2/20, Superhero 1/20.
- Arcwise (audit, Mini-Dev only): 161 of 498 corrected (32.3%) ([sheet](https://docs.google.com/spreadsheets/d/1IGm9Otruey60ujUnl8AOkepY3qgWHdFJHnX7hQGUeCw/edit?gid=0)).
- Jin, Choi, Zhu, Kang (audit; [arXiv 2601.08778](https://arxiv.org/abs/2601.08778)):
  - Measured: 263 of 498 first-version Mini-Dev examples erroneous (52.8%), counting ambiguity as an error (78 cases). Method: an o3 agent flagged items, two authors checked them, and Arcwise's corrections were merged in.
  - Claimed, from 100 corrected dev examples: agent rankings correlate only ρ=0.32 between the original and corrected subsets.
- MCI-SQL "BIRD-clear": 412 of 1,534 dev items corrected (26.9%) ([arXiv 2603.13390](https://arxiv.org/abs/2603.13390)).
- NL2SQL-Bugs authors found 106 previously undetected dev gold errors (6.91%) ([paper](https://arxiv.org/html/2503.11984)).
- BIRD's own dev 1106 against dev_20240627 (our diff): 570 items changed, and 253 gold results changed (16.5%). The BIRD team published no error counts.
- FLEX: 200 prediction pairs judged by experts. Execution accuracy agrees with the experts at κ=62.0 (21 false positives, 17 false negatives). Its "54.54%" figure is a share of false negatives it detected, not a dataset error rate ([NAACL 2025](https://aclanthology.org/2025.naacl-long.228)).
- Ties: 321 dev queries (20.86%) can return different rows depending on ties ([Pourreza & Rafiei](https://aclanthology.org/2023.emnlp-main.99)).

**Annotation errors, train**
- ReViSQL / BIRD-Platinum audit of 2.5k random train items: wrong gold SQL 52.1%, at least one error 61.1% ([arXiv 2603.20004](https://arxiv.org/abs/2603.20004)).
  - These are floors: the LLM flagger had 24.5% recall.
  - Released as BIRD-Platinum: 2,462 items (2,088 train / 374 val).
- retail_world (our check): the shipped schema is the 8-table W3Schools Northwind, yet 293 of its 373 gold queries reference columns that schema lacks. bird23-train-filtered keeps only 38 of the 373.

**Database lists (our count)**
- Train (69): address, airline, app_store, authors, beer_factory, bike_share_1, book_publishing_company, books, car_retails, cars, chicago_crime, citeseer, codebase_comments, coinmarketcap, college_completion, computer_student, cookbook, craftbeer, cs_semester, disney, donor, european_football_1, food_inspection, food_inspection_2, genes, hockey, human_resources, ice_hockey_draft, image_and_language, language_corpus, law_episode, legislator, mental_health_survey, menu, mondial_geo, movie, movie_3, movie_platform, movielens, movies_4, music_platform_2, music_tracker, olympics, professional_basketball, public_review_platform, regional_sales, restaurant, retail_complains, retail_world, retails, sales, sales_in_weather, shakespeare, shipping, shooting, simpson_episodes, soccer_2016, social_media, software_company, student_loan, superstore, synthea, talkingdata, trains, university, video_games, works_cycles, world, world_development_indicators.
- Dev (11), with question counts: california_schools 89, card_games 191, codebase_community 186, debit_card_specializing 64, european_football_2 129, financial 106, formula_1 174, student_club 158, superhero 129, thrombosis_prediction 163, toxicology 145.
- Train counts for the overlapping DBs, raw → bird23-filtered: movie_3 325→223, works_cycles 474→383, soccer_2016 258→190, retail_world 373→38, legislator 177→128 (our count).

#### Spider 1.0

**Size and splits**
- 10,181 questions, 5,693 unique SQL, 200 DBs, 138 domains ([paper](https://arxiv.org/html/1809.08887)).
- Train 8,659 = train_spider 7,000 (140 DBs) + train_others 1,659 (Restaurants, GeoQuery, Scholar, Academic, IMDB, Yelp). Dev 1,034 (20 DBs). Test 2,147 (40 DBs).
- The test set has been released; the leaderboard closed 2024-02-05 ([site](https://yale-lily.github.io/spider)).

**Dialect:** SQLite. The official zip is 205.8 MB with 166 + 206 DBs (our count).

**SQL complexity**
- 5.1 tables and 27.6 columns per DB; SQL averages about 21 tokens ([paper](https://arxiv.org/html/1809.08887)).
- OmniSQL Table 3: per SQL, 1.52 tables, 0.48 joins, 14.85 whitespace tokens; no CTEs and no window functions ([OmniSQL](https://arxiv.org/html/2503.02240)).
- Spider 2.0 Table 2: test averages 18.5 tokens per SQL ([Spider 2.0](https://arxiv.org/html/2411.07763v2)).
- Our hardness count (easy/medium/hard/extra): dev 248/446/174/166; train_spider 1,694/2,777/1,461/1,068.

**External knowledge:** none. Questions needing outside knowledge were excluded ([paper](https://arxiv.org/html/1809.08887)).

**Real or synthetic** ([paper](https://arxiv.org/html/1809.08887))
- About 70 DBs from courses, tutorials, textbooks and CSV files.
- About 40 DatabaseAnswers schemas filled with generated values.
- About 90 built from WikiSQL tables.
- 11 CS students wrote the questions and SQL without templates.

**License:** CC BY-SA 4.0 ([site](https://yale-lily.github.io/spider)).

**Annotation errors**
- The authors corrected about 4% of dev in June 2020 ([site](https://yale-lily.github.io/spider)).
- Audits of dev:
  - At least 0.7%: 5 unique gold queries ([Zeng et al.](https://arxiv.org/html/2210.10668)).
  - 16 queries, 1.55% ([NL2SQL-Bugs](https://arxiv.org/html/2503.11984)).
  - 4.5% ([R³](https://arxiv.org/html/2402.14851)).
- Pourreza & Rafiei ([EMNLP 2023](https://aclanthology.org/2023.emnlp-main.99)):
  - 33% of gold SQL was wrong among the 102 dev items that two strong models both failed. This is conditional on hard items, not a dataset-wide rate.
  - Tie-prone queries: dev 234 (22.63%), train 1,359 (18.1%).

**Training restrictions:** none.

**Overlap with Spider 2.0-Lite:** six train DBs (questions per DB: sakila_1 82, chinook_1 84, store_1 112, soccer_1 14, formula_1 80, baseball_1 82; our count on [xlangai/spider](https://huggingface.co/datasets/xlangai/spider)). No dev or test DB overlaps. The test-set e_commerce is a DatabaseAnswers schema, not Olist (our check).

#### SynSQL-2.5M (OmniSQL; PVLDB 18(11))

**Size:** 2,544,390 samples (2,412,915 unique SQL) over 16,583 synthetic SQLite DBs, with no splits ([paper](https://arxiv.org/html/2503.02240), [HF](https://huggingface.co/datasets/seeklhy/SynSQL-2.5M)). File sizes (our check): data.json 9.36 GB, databases.zip 54.5 MB.

**How the DBs were made** ([§3.2](https://arxiv.org/html/2503.02240))
- Seeded from 0.1% of TabLib web tables, filtered down to 19,935 tables.
- An LLM wrote a business scenario and about 10 tables with 2 example rows each.
- Result: 10.15 tables and 74.07 columns per DB.
- Our inspection of 30 DBs: no table had more than 3 rows, and 6 DBs had no rows at all.

**SQL complexity** (Table 3 of the [paper](https://arxiv.org/html/2503.02240))
- Per SQL: 4.00 tables, 1.75 joins, 1.49 functions, 57.05 whitespace tokens.
- Feature counts: 1,073,483 CTE queries (42.2%), 33,916 window-function queries, 612,647 subqueries, 363,472 set operations.
- Tier shares (Simple / Moderate / Complex / Highly Complex) are not published.
  - Our estimate from a clustered sample of 14,074 records: Complex 34.9%, Moderate 31.6%, Highly Complex 24.9%, Simple 8.6%.
  - CTEs appear in about 73% of Complex and 68% of Highly Complex queries.

**External knowledge and reasoning** ([§3.4–3.5](https://arxiv.org/html/2503.02240))
- Generated only for "vague" and "metaphorical" questions; non-empty in 22.4% of our sample.
- 9 language styles.
- Chain-of-thought for every sample.

**Fully synthetic:** generated with Llama-3.1, DeepSeek-Coder and the Qwen2.5 / Qwen2.5-Coder families ([§4](https://arxiv.org/html/2503.02240)).

**License**
- Apache-2.0 ([HF](https://huggingface.co/datasets/seeklhy/SynSQL-2.5M)).
- Part of the data comes from Llama 3.1, whose license requires "Llama" in the name of any model trained on its outputs ([license](https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/LICENSE)). The dataset card does not address this.

**Quality (paper-measured human evaluation of 1,000 samples):** 86% fully correct, 89% of SQL appropriate, 97% of questions meaningful ([§4.5.2](https://arxiv.org/html/2503.02240)).

**Overlap:** our scan of all 16,583 schemas found only generic table-name collisions.
- One DB, `formula_one_racing_results_and_analytics`, uses Ergast-like table names but has 0 rows.
- No SynSQL DB is a Spider 2.0-Lite DB.

#### Gretel synthetic_text_to_sql
- **Size:** 105,851 records (100,000 train / 5,851 test) across 100 domains ([HF](https://huggingface.co/datasets/gretelai/synthetic_text_to_sql)). Released 2024-03. Apache-2.0.
- **sql_complexity mix (our count):**

  | Category | Share |
  |---|---|
  | basic | 48.5% |
  | aggregation | 22.0% |
  | single join | 14.9% |
  | subqueries | 6.7% |
  | window functions | 3.6% |
  | multiple joins | 2.9% |
  | set operations | 1.0% |
  | CTEs | 0.3% |

- **Dialect:** not stated.
  - Our marker count: MySQL-style 4.9%, T-SQL 2.4%, PostgreSQL 0.9%.
  - Contexts are CREATE TABLE + INSERT, averaging 1.24 tables and about 3 rows.
- **External knowledge:** none.
- **Quality:**
  - Arctic-Text2SQL-R1 found the unfiltered set hurt their results and kept a filtered 11,811-example subset ([arXiv 2505.20315](https://arxiv.org/abs/2505.20315)).
  - Our SQLite run of 2,000 random SELECT/WITH items: 22.3% failed, and 2.75% of contexts failed to load.
- **Overlap:** none (our check).

#### Spider 2.0 itself (context for the evaluation set; not a candidate)
- 13 of the 135 local questions carry an external-knowledge document (our count of [spider2-lite.jsonl](https://github.com/xlang-ai/Spider2/blob/main/spider2-lite/spider2-lite.jsonl)).
- Errors in the closely related Snow split, measured by Jin et al.: 76 of 121 Spider 2.0-Snow examples with public gold are erroneous (62.8%); 66.1% on the earlier 0713 version ([arXiv 2601.08778](https://arxiv.org/abs/2601.08778), [CIDR 2026](https://www.vldb.org/cidrdb/papers/2026/p5-jin.pdf)).
- 36 of the 120 Snow gold files are sf_local*, the Snowflake versions of the Lite local questions (our count, Spider2 commit 01a4c67).

### Inferences
- **BIRD train fits the judge's input best**: real rows to preview, an evidence document per question, and SQLite.
  - Raw gold is too noisy to label candidates by execution match: at least 52% wrong in the train audit.
  - Use BIRD-Platinum (2,088/374) for clean labels and bird23-train-filtered for volume, after removing the overlapping DBs.
- **BIRD SQL is short.** It runs 25–37 whitespace tokens, against 144.5 tokens for Spider 2.0-Lite in Spider 2.0's own table. Mini-Dev 1024 (56 tokens, 30% CTE) is the most Spider2-like BIRD release.
- **Spider 1.0 adds volume but no analytic depth:** no CTEs, no window functions, about 15 tokens per SQL.
- **SynSQL previews would be empty or near-empty**, so a judge trained on them would learn to judge SQL text rather than results. It is usable only after re-populating the DBs, or for SQL-text pre-training.
- **Gretel is a poor fit** for a judge that reads multi-table schemas and execution previews.
- **The evaluation set's own gold is probably noisy too.** The Snow audit (62.8%) covers the Snowflake twins of 36 local questions. This caps measurable judge accuracy and should be kept in mind when interpreting the 94-of-135 oracle ceiling.

### Gaps
- Names of BIRD's hidden-test DBs: not found.
- SynSQL tier counts: unpublished; only our sample estimate exists.
- No independent audit of BIRD dev 1106 or Mini-Dev 1024 found.
- The underlying generation models for Gretel are not disclosed.
- No audit of Spider 2.0-**Lite** local gold specifically; the Snow numbers only transfer by inference.

---

## 2. Domain and enterprise sets: SEDE, KaggleDBQA, EHRSQL (and the 2024 shared task), MIMICSQL, Archer, BookSQL, BEAVER, FIBEN, ScienceBenchmark

### Takeaway
- **Only two sets offer real volume with public gold:**
  - EHRSQL: 24k pairs; SQLite on Drive; template-based.
  - BEAVER v3: 7,978 public queries; MySQL; long enterprise SQL; 97% synthetic.
- **The earlier verdict "BEAVER is unusable (203 Oracle questions, no license or repo)" is wrong.**
- **Two of these sets touch Spider 2.0-Lite data:**
  - KaggleDBQA's TheHistoryofBaseball is the same Lahman data as local Baseball.
  - Archer's public soccer_1 and formula_1 are the same source data as EU_soccer and f1.

### Cited Findings

#### SEDE (Hazoom et al., NLP4Prog 2021)
- **Size:** 12,023 pairs over one Stack Exchange schema of 29 tables and 211 columns ([paper](https://arxiv.org/pdf/2106.05006v1)).
  - Splits 10,309 / 857 / 857 (our count of the [repo](https://github.com/hirupert/sede/tree/main/data/sede)).
  - Val and test are the 1,714 human-verified pairs. The test set is public.
- **Dialect:** T-SQL. No DB is shipped; a Stack Exchange dump is needed ([issue #4](https://github.com/hirupert/sede/issues/4)). The authors use PCM-F1, not execution accuracy.
- **Complexity**
  - Table 3: 2.14 unique tables per question; average nesting 1.28.
  - Table 2, a 100-pair manual sample: under-specified 87%, window functions 8%, DECLARE/WITH 11%, CASE 10% ([paper](https://arxiv.org/pdf/2106.05006v1)).
  - Our regex count: OVER( in 11.7% of train and 18.6% of test; leading WITH in 7.0% and 9.8%.
- **External knowledge:** none. The question is the user's query title.
- **Real or synthetic:** real user-written queries from a cleaned log of 1.6M rows.
- **License:** Apache-2.0 ([repo](https://github.com/hirupert/sede)).
- **Errors (authors' measurement):** of 2,000 val/test candidates, 1,024 were kept, 690 fixed and about 286 dropped. Train is unverified. No independent audit found.
- **Restrictions:** none.
- **Overlap:** none.
- **Contamination:** in NumbersStation NSText2SQL (10,051 rows, Jul 2023) ([HF stats](https://datasets-server.huggingface.co/statistics?dataset=NumbersStation/NSText2SQL&config=default&split=train)).

#### KaggleDBQA (Lee et al., ACL 2021)
- **Size:** 272 questions over 8 DBs; a few-shot split of 87 and a test split of 185; nothing hidden ([paper](https://aclanthology.org/2021.acl-long.176.pdf); our count on [GitHub](https://github.com/Chia-Hsuan-Lee/KaggleDBQA)).
- **Dialect and access:** SQLite.
  - The DBs are in the README's Google Drive folder.
  - The official Microsoft download host returns NXDOMAIN (our check; [issue #1](https://github.com/Chia-Hsuan-Lee/KaggleDBQA/issues/1)).
- **Complexity**
  - 2.25 tables per DB ([paper](https://aclanthology.org/2021.acl-long.176.pdf)).
  - Spider 2.0 Table 2: 13.8 tokens per SQL ([Spider 2.0](https://arxiv.org/html/2411.07763v2)).
  - Our count: JOIN 16.2%, nested 4.0%, no CTEs.
- **External knowledge:** yes. Column descriptions, DB overviews, value enums and the original documentation ([README](https://github.com/Chia-Hsuan-Lee/KaggleDBQA)).
- **Real or synthetic:** real Kaggle DBs. Non-SQL annotators wrote the questions; SQL experts wrote the SQL.
- **License:** CC BY-SA 4.0, plus per-DB source licenses ([LICENSE](https://github.com/Chia-Hsuan-Lee/KaggleDBQA/blob/main/LICENSE.md), [DATASETS.md](https://github.com/Chia-Hsuan-Lee/KaggleDBQA/blob/main/DATASETS.md)).
- **Errors:** no rate reported. A user listed 5 wrong gold queries and 5 ambiguous questions; the maintainer acknowledged them on 2024-07-11 ([#2](https://github.com/Chia-Hsuan-Lee/KaggleDBQA/issues/2), [#3](https://github.com/Chia-Hsuan-Lee/KaggleDBQA/issues/3)).
- **Restrictions:** none legal. It is intended as a test suite, and the few-shot files may be used for fine-tuning ([README](https://github.com/Chia-Hsuan-Lee/KaggleDBQA)).
- **DBs:** GeoNuclearData, GreaterManchesterCrime, Pesticide, StudentMathScore, TheHistoryofBaseball, USWildFires, WhatCDHipHop, WorldSoccerDataBase ([DATASETS.md](https://github.com/Chia-Hsuan-Lee/KaggleDBQA/blob/main/DATASETS.md)).
  - **TheHistoryofBaseball** is kaggle.com/seanlahman/the-history-of-baseball, the same data as local Baseball.
    - It has 5 tables: hall_of_fame, player_award, player_award_vote and salary are column-identical to Spider 2.0-Lite's, and `player` has 17 of their 24 columns (our check).
    - None of its 39 SQL use batting or the debut/final_game columns that local007 and local008 need (our check).
  - **WorldSoccerDataBase** (betfront, football_data) is **not** the European Soccer Database.
- **Contamination:** in NSText2SQL, 352 rows ([HF stats](https://datasets-server.huggingface.co/statistics?dataset=NumbersStation/NSText2SQL&config=default&split=train)).

#### EHRSQL (NeurIPS 2022 D&B) and EHRSQL 2024 (ClinicalNLP @ NAACL 2024)
- **Size**
  - Paper: 24,411 pairs ([paper](https://arxiv.org/pdf/2301.07695)).
  - Repo v1.5.1 (2026-04-28), our count: 24,405 pairs.
    - MIMIC-III: 9,318 / 1,122 / 1,786.
    - eICU: 9,270 / 1,117 / 1,792.
    - 1,900 unanswerable questions, all in val/test.
  - The test set was released 2024-04-27 ([repo](https://github.com/glee4810/EHRSQL)).
- **Dialect:** SQLite. Preprocessed mimic_iii.sqlite (95 MB) and eicu.sqlite (102 MB) are on Google Drive with patient values shuffled; alternatively, build from credentialed source data ([README](https://github.com/glee4810/EHRSQL)).
- **Complexity**
  - 2.4 tables and 2.7 nesting levels per question; 93.2% involve time ([paper Table 4](https://arxiv.org/pdf/2301.07695)).
  - Annotators were told to avoid JOINs.
  - 230 templates (174 answerable), and every template appears in every split.
- **External knowledge:** none.
- **Real or synthetic**
  - Real de-identified data.
  - Questions come from a poll of 222 hospital staff, turned into templates and paraphrased.
  - v1.5.0 rewrote all questions with GPT-4o-mini ([CHANGELOG](https://github.com/glee4810/EHRSQL/blob/main/dataset/ehrsql/CHANGELOG.md)).
- **License:** CC BY 4.0. The source data falls under the PhysioNet credentialed DUA. PhysioNet's 2025-09-24 guidance bars third-party APIs without zero data retention and recommends local LLMs ([PhysioNet](https://physionet.org/news/post/llm-responsible-use/)).
- **Errors (authors' 2026-03-09 audit):**
  - 1,840 tie-breaking fixes to ORDER BY … LIMIT 1 queries.
  - 148 NULL-guard fixes and 97 COUNT DISTINCT fixes.
  - At most 2,085 of 22,505 SQL changed (9.3%) ([CHANGELOG](https://github.com/glee4810/EHRSQL/blob/main/dataset/ehrsql/CHANGELOG.md)).
- **EHRSQL 2024**
  - Splits: train 5,124 / valid 1,163 / test 1,167, with test labels public ([overview](https://arxiv.org/html/2405.06673)).
  - mimic_iv.sqlite is built from the MIMIC-IV demo (ODbL, no credentials needed) ([repo](https://github.com/glee4810/ehrsql-2024)).
- **Overlap:** none.
- **Contamination:** in NSText2SQL: mimic_iii 10,078 rows, eicu 10,025 rows ([HF stats](https://datasets-server.huggingface.co/statistics?dataset=NumbersStation/NSText2SQL&config=default&split=train)).

#### MIMICSQL (Wang et al., WWW 2020)
- **Size:** 10,000 pairs, split 8,000 / 1,000 / 1,000. SQLite `mimic.db` must be built from credentialed MIMIC-III ([repo](https://github.com/wangpinggl/TREQS)).
- **Complexity:** average SQL length 21.14; no nested queries (our count) ([paper](https://arxiv.org/pdf/1908.01839)).
- **Generation:** template-generated, with paraphrases by Freelancer workers.
- **License:** MIT, plus the MIMIC-III DUA.
- **Errors:** the original split leaks templates. Accuracy falls from up to 92% to 28% on a re-split ([Tarbell et al.](https://arxiv.org/abs/2303.12898)).
- **Overlap:** none.
- **Contamination:** in NSText2SQL, 19,996 rows.

#### Archer (Zheng et al., EACL 2024)
- **Size**
  - 1,042 English and 1,042 Chinese questions; 521 unique SQL; 20 Spider DBs ([paper](https://arxiv.org/html/2402.12554v2)).
  - The leaderboard re-split by DB: train 8 / dev 2 / **blind test 10** ([site](https://sig4kg.github.io/archer-bench/)).
  - Public English: train 414, dev 104 (our count).
- **Dialect:** SQLite; an Oracle port (518 pairs) appeared in May 2026 ([oracle/oracle-archer](https://github.com/oracle/oracle-archer)).
- **Complexity (Table 1):**
  - SQL length 79.71; nesting 1.08; 2.17 tables per SQL.
  - Reasoning types: arithmetic 100%, commonsense 51.4%, hypothetical 44.0% ([paper](https://arxiv.org/html/2402.12554v2)).
- **External knowledge:** a per-question `commonsense_knowledge` text (our inspection).
- **Authorship:** human-written (PhD students, with expert review).
- **License:** CC BY 4.0 ([site](https://sig4kg.github.io/archer-bench/)).
- **Errors:** not found.
- **Overlap:** the public DBs include **soccer_1** (European Soccer, no Match table) and **formula_1** (Ergast, older snapshot) (our check).

#### BookSQL (Kumar et al., NAACL 2024)
- **Size:** 100k pairs over one accounting DB (7 tables, about 1M records). Test gold SQL is withheld for a leaderboard ([paper](https://arxiv.org/html/2406.07860v1), [repo](https://github.com/Exploration-Lab/BookSQL)).
- **Dialect:** SQLite, gated on HF ([HF](https://huggingface.co/datasets/Exploration-Lab/BookSQL)).
- **Difficulty:** Easy 10k / Medium 45k / Hard 45k ([paper](https://arxiv.org/html/2406.07860v1)).
- **Generation:** 183 expert-written questions expanded through templates.
- **License:** CC BY-NC-SA 4.0. The gate requires non-commercial use and forbids sharing or uploading the dataset elsewhere ([HF](https://huggingface.co/datasets/Exploration-Lab/BookSQL)).
- **Overlap:** none.

#### BEAVER (Chen et al., arXiv 2409.02038): verification of the earlier claim

**Versions** ([v1](https://arxiv.org/html/2409.02038v1), [v2](https://arxiv.org/html/2409.02038v2), [v3](https://arxiv.org/html/2409.02038v3))

| Version | Date | Size | Schemas |
|---|---|---|---|
| v1 | 2024-09-03 | 93 pairs | 4 DBs |
| v2 | 2025-01-20 | 203 pairs | DW 103 from an **Oracle** warehouse (99 tables) + NW 100 from **five MySQL** DBs (366 tables) |
| v3 | 2026-05-13 | 9,128 queries | 8 DBs, 812 tables, 19 domains (DW Oracle; NW 5 MySQL; SP 2 MySQL) |

- v3 composition: 254 real queries plus 8,874 synthetic ones. The synthetic queries come from 594 templates mined from real logs, drafted by GPT-5.2 and verified by experts.
- v2's 203 pairs are therefore **not all Oracle**.

**Repository and data**
- `peterbaile/beaver` (created 2024-08-30, MIT) now redirects to [peterbaile/beaver-may-2025](https://github.com/peterbaile/beaver-may-2025). Its releases contained 49, 191 and 209 queries; data is shared as CSV plus a MySQL dump on Drive.

**What is public now**
- 7,978 of the 9,128 queries are public; the rest form a private test set ([site](https://beaverbench.github.io/)).
- HF split sizes: dw 5,787 / nova 1,053 / neutron 1,017 / dw_real 121 ([HF API](https://huggingface.co/api/datasets/beaverbench/beaver-query)).
- Table data: [beaver-table](https://huggingface.co/datasets/beaverbench/beaver-table) (381 tables, plus a 261.6 MB beaver_db.zip). The SP DBs and keystone/glance/cinder are not in the public table release (our check).

**Dialect:** a unified MySQL version. Oracle users must import the DW CSVs themselves. No SQLite.

**Complexity (v3 Table 3)**
- Schemas: 101.5 tables and 869.4 columns per DB.
- Per query: 316.7 tokens, 5.7 joins, 5.6 nesting levels, 3.7 CTEs.
- Best result: GPT-5.2 agentic scores 10.8% ([v3](https://arxiv.org/html/2409.02038v3)).

**External knowledge:** per query, the tables, join keys, column mappings, domain-knowledge facts and sub-SQLs ([HF card](https://huggingface.co/datasets/beaverbench/beaver-query)).

**Other attributes**
- License: MIT tag; HF auto-gating with no extra terms; no "do not train" statement found.
- Errors: no audit found. Inter-annotator agreement is about 83% for questions and 87% for subtask labels ([v3](https://arxiv.org/html/2409.02038v3)).
- Overlap: none. The data comes from an academic data warehouse, OpenStack service DBs and housing management.

#### FIBEN (Sen et al., PVLDB 2020)
- **Size:** 300 NL queries, 237 distinct SQL, one DB of 152 tables, no splits ([repo](https://github.com/IBM/fiben-benchmark), [ATHENA++](https://www.vldb.org/pvldb/vol13/p2747-sen.pdf)).
- **Dialect:** Db2/PostgreSQL DDL plus CSVs. No SQLite.
- **Complexity:** 170 of the 300 queries are nested.
- **Provenance:** SEC filings plus TPoX data; queries written by BI experts.
- **License:** Apache-2.0.
- **Conflict:** BEAVER v1 lists FIBEN as 41 tables per DB ([v1](https://arxiv.org/html/2409.02038v1)).
- **Overlap:** none.

#### ScienceBenchmark (Zhang et al., PVLDB 2024)
- **Size**

  | DB | Seed | Dev | Synthetic |
  |---|---|---|---|
  | CORDIS | 100 | 100 | 1,306 |
  | SDSS | 100 | 100 | 2,061 |
  | OncoMX | 100 | 99 | 1,065 |

  A separate hidden test set of unknown size also exists ([paper](https://arxiv.org/html/2306.04743v2), [repo](https://github.com/ckosten/sciencebenchmark_dataset), [site](https://sciencebenchmark.cloudlab.zhaw.ch/)).
- **Dialect:** PostgreSQL dumps (1 GB, 6.1 GB, 12 GB). No SQLite.
- **Data:** real DBs. Seed and dev items were expert-written. Synthetic items pair template SQL with questions from a fine-tuned GPT-3.
- **Errors (authors' measurement on synthetic data):** in 100-sample checks, question and SQL agree in 83% (CORDIS), 76% (SDSS) and 75% (OncoMX) of cases ([paper](https://arxiv.org/html/2306.04743v2)).
- **License:** not found.
- **Overlap:** none.

#### SCARE (ML4H 2025; found in passing)
- 4,200 (question, candidate SQL, expected output) triples from 7 text-to-SQL models, over MIMIC-III, MIMIC-IV and eICU.
- Built for **post-hoc SQL verification**, which is close to the judge task ([arXiv](https://arxiv.org/abs/2511.17559), [GitHub](https://github.com/glee4810/SCARE)).
- Details beyond the abstract were not checked.

### Inferences
- **BEAVER v3's public 7,978** is the strongest enterprise-style training source with gold: long, CTE-heavy SQL over 100+-table schemas, MIT tag, no overlap, released 2026.
  - It needs a MySQL engine.
  - Its public part covers only three DB groups (dw, nova, neutron), so it adds little database diversity.
  - 97% of it is synthetic recomposition.
- **EHRSQL** is executable in SQLite and has gold. Its template reuse across splits (174 answerable templates) means low diversity, and the 2026 fixes to 1,840 tie-breaking queries show it is sensitive to ties, one of the judge's failure modes.
- **KaggleDBQA** is useful only as a small test set after dropping TheHistoryofBaseball.
- **Archer** has public data only after dropping soccer_1 and formula_1.
- **SEDE** cannot be labelled by execution without rebuilding a Stack Exchange DB in SQL Server. **FIBEN and ScienceBenchmark** need Db2 or PostgreSQL.
- **BookSQL's** non-commercial, no-redistribution terms and single DB make it a poor fit.

### Gaps
- ScienceBenchmark's license and hidden-test size: not found.
- BookSQL's exact split sizes: not verified (gated).
- Names of Archer's blind-test DBs: not found.
- No independent error audits found for BEAVER, Archer, BookSQL or FIBEN.
- SCARE was checked only at abstract level.

---

## 3. Ambiguity, robustness and conversational sets: AmbiQT, AMBROSIA, PRACTIQ, Dr.Spider, Spider-DK, Spider-Syn, Spider-Realistic, SParC, CoSQL (plus MMSQL)

### Takeaway
- **All except AMBROSIA reuse Spider databases.**
  - Their train splits (AmbiQT, Spider-Syn, SParC, CoSQL, MMSQL) contain all six Spider DBs that overlap Spider 2.0-Lite.
  - The dev-only sets (Spider-DK, Spider-Realistic, Dr.Spider, AmbiQT validation, PRACTIQ, MMSQL test) contain none of them.
- **Multiple valid gold answers:** only AMBROSIA keeps several gold SQL per question that give different results. ARCS (§5) also does, with real DBs. AmbiQT's two golds appear to be execution-equivalent by construction.
- **PRACTIQ's data is not released.**

### Cited Findings

#### AmbiQT (EMNLP 2023 main)
- **Size**
  - 3,046 examples with 2 golds each: column 1,240, table 1,417, join 288, precomputed 101 ([paper](https://arxiv.org/html/2310.13659)).
  - These cover only 992 distinct Spider-dev questions (our count).
  - The repo also has train.json (20,249 examples over 140 Spider-train DBs), which the authors "don't use or train on" ([repo](https://github.com/testzer0/AmbiQT)).
- **Dialect:** SQLite (Spider DBs). The ambiguous schemas exist only as strings; evaluation maps them back to the original Spider DB ([evaluate.py](https://github.com/testzer0/AmbiQT/blob/master/benchmark/col-synonyms/evaluate.py)).
- **Construction:** questions are the original human-written Spider questions. Synonyms come from ChatGPT; the J and P categories are rule-based; golds are derived by rule.
- **License:** MIT.
- **Errors:** about 1.8K of 3K test examples return non-empty results (measured by [Saparina & Lapata](https://arxiv.org/html/2502.18448)).
- **Overlap:** validation has none. train.json contains all six overlapping DBs (e.g., store_1 332 examples across categories; our count).
- **Restrictions:** none.

#### AMBROSIA (NeurIPS 2024 D&B)
- **Size**
  - 846 LLM-generated DBs in 16 domains.
  - 1,277 ambiguous questions: scope 501, attachment 362, vague 414.
  - 2,965 interpretations ([paper](https://arxiv.org/html/2406.19073)).
  - Official split, our count: few-shot 423 rows / test 3,819 rows.
  - The authors' later 80/10/10 re-split gives about 1K ambiguous + 2K unambiguous for training and 131 ambiguous for test ([Findings ACL 2025](https://arxiv.org/html/2502.18448)).
- **Dialect:** SQLite files included.
- **Complexity**
  - DBs: about 5 tables per DB and 3–5 rows per table ([paper](https://arxiv.org/html/2406.19073)).
  - Unambiguous golds: 20.7 tokens and 1.25 JOINs on average (our count).
- **Construction**
  - DBs written by OpenChat-7B, then validated by hand.
  - Questions and interpretations written by humans.
  - Golds are templates for scope and attachment, and expert-written for vagueness.
  - Every gold was executed and checked to give non-empty, distinct results.
- **License and terms**
  - CC BY 4.0.
  - The site asks: "We kindly request that you do not upload our dataset to GitHub or Transformers Hub to ensure it is not used for training any LLMs" ([site](https://ambrosia-benchmark.github.io/)). This is a request, not a license term; the datasheet lists no prohibited uses.
- **Training use and leaks**
  - The authors trained on a re-split, and IntentRL (a Qwen3-4B fine-tune) lists AMBROSIA as its training data ([model card](https://huggingface.co/irisaparina/IntentRL-Ambig-Text2SQL-4B)).
  - A full copy is on GitHub ([JustHarsh/Curiosity-by-Design](https://github.com/JustHarsh/Curiosity-by-Design)).
- **Errors:** no rate reported.
- **Overlap:** none.

#### PRACTIQ (NAACL 2025)
- **Size:** 4 ambiguous and 4 unanswerable categories (1,802 items) plus 1,034 answerable Spider-dev questions. That sums to 2,836, but the paper states 2,812 ([paper](https://arxiv.org/html/2410.11076)).
- **Construction:** generated from Spider dev with Claude 3 Sonnet.
- **Availability:** only the generation code is public ([repo](https://github.com/amazon-science/conversational-ambiguous-unanswerable-text2sql)).
- **License:** the repo LICENSE is CC BY-NC 4.0, but the paper says MIT.
- **Quality (authors' sample check):** category correctness 93.75% on average (20 samples per category).
- **Overlap:** none (Spider dev only).

#### Dr.Spider (ICLR 2023)
- **Size:** 17 perturbation sets, 15,269 examples in total (our sum); evaluation only ([paper](https://arxiv.org/html/2301.08881)).
  - The SQL-side perturbations total 1,822: comparison 178, sort-order 192, NonDB-number 131, DB-text 911, DB-number 410.
- **Format:** SQLite; perturbed DBs in a Git LFS tarball ([repo](https://github.com/awslabs/diagnostic-robustness-text-to-sql)).
- **License:** code Apache-2.0; annotations CC BY 4.0.
- **Quality:** 63% of generated paraphrases were judged factual. An open issue reports wrong gold SQL ([#7](https://github.com/awslabs/diagnostic-robustness-text-to-sql/issues/7)).
- **Overlap:** none.

#### Spider-DK, Spider-Syn, Spider-Realistic
- **Spider-DK:** 535 dev-derived pairs (265 modified to need domain knowledge); MIT ([paper](https://arxiv.org/html/2109.05157), [repo](https://github.com/ygan/Spider-DK)). 128 of its queries (23.85%) are tie-sensitive ([Pourreza & Rafiei](https://arxiv.org/html/2310.18538)). No overlap.
- **Spider-Syn:** 7,000 train / 1,034 dev, hand-written synonym rewrites; MIT ([paper](https://arxiv.org/html/2106.01065), [repo](https://github.com/ygan/Spider-Syn)). Its train split covers all 140 Spider-train DBs, including the six overlapping ones. It is **not** evaluation-only.
- **Spider-Realistic:** 508 examples over 19 dev DBs, with explicit column mentions removed ([paper](https://arxiv.org/html/2010.12773), [Zenodo](https://zenodo.org/records/5205322)). The license file says CC BY-SA 4.0 but the Zenodo metadata says CC BY 4.0. No overlap.

#### SParC and CoSQL
- **SParC** ([paper](https://arxiv.org/html/1906.02285), [site](https://yale-lily.github.io/sparc))
  - 4,298 sequences, 12,726 questions, 200 DBs.
  - Train 3,034 / 9,025; dev 422 / 1,203; **test 842 / 2,498, unreleased**.
  - JOIN 35.5%, nested 5.7%.
  - CC BY-SA 4.0.
  - Train interactions on the six overlapping DBs: 30 / 29 / 44 / 10 / 39 / 33 (our count on [aherntech/sparc](https://huggingface.co/datasets/aherntech/sparc)).
- **CoSQL** ([paper](https://arxiv.org/html/1909.05378), [site](https://yale-lily.github.io/cosql))
  - 3,007 dialogues, 31,148 turns, 10k+ SQL.
  - Train 2,164 / dev 292 / **test 551, unreleased**.
  - CC BY-SA 4.0.
  - Ambiguous questions get a clarification turn and then a single gold.
  - Train dialogues on the six overlapping DBs: 24 / 27 / 43 / 7 / 17 / 39 (our count on [avandar2024/cosql](https://huggingface.co/datasets/avandar2024/cosql)).

#### MMSQL (2024/2025)
- **Size:** 6,493 Gemini-generated training dialogues and 149 human-annotated test dialogues; CC BY 4.0 ([paper](https://arxiv.org/html/2412.17867), [card](https://huggingface.co/datasets/GuoZiming/MMSQL)).
- **Overlap:** train includes the six overlapping DBs (108 / 69 / 90 / 24 / 98 / 73 dialogues; our count). Test uses Spider dev DBs, so none.

### Inferences
- **AMBROSIA** is the only released source with several executable golds that give *different* results, so it can teach "both readings are defensible" cases.
  - Its DBs have 3–5 rows per table, so previews are thin.
  - The authors' request not to re-upload it should be honoured.
- **Dr.Spider's SQL-perturbation sets** give minimal-pair negatives: flipped comparisons, sort order, off-by-n numbers, wrong values. They are Spider-easy, but these are the same mistake types that produce "single row vs ranked list" and cutoff errors.
- **AmbiQT** cannot test result-based selection, because its paired golds are built to be equivalent.
- **Spider-family training splits** must be filtered by db_id before use. Their test sets are unreleased (SParC, CoSQL) or easy (Spider-DK, Spider-Realistic).

### Gaps
- PRACTIQ's generated data cannot be inspected.
- No error rate is published for SParC, CoSQL, Spider-Syn or AMBROSIA.
- Whether AmbiQT's paired golds always execute to the same result was inferred from its construction, not measured end to end.

---

## 4. BIRD-family agentic and critic sets, and others: BIRD-Interact, LiveSQLBench, BIRD-Critic / SWE-SQL / Six-Gym, Termite, SQLStorm, TPC-H/TPC-DS, DA-Code, DABStep

### Takeaway
- **Closest analogue to Spider 2.0-Lite:** LiveSQLBench and BIRD-Interact. They have 250–360-token SQL and knowledge-base documents, and no overlap. Gold is withheld but sent by an automatic email reply.
- **Overlap:**
  - BIRD-Critic overlaps through formula_1 and european_football_2.
  - Six-Gym overlaps through chinook, movie_3 (Sakila) and the Postgres Pro airlines DB.
- **Excluded:** DA-Code shares both databases and near-duplicate questions with the local split.
- **Not useful as SQL judge data:**
  - Termite is Italian and tiny.
  - SQLStorm has no natural-language questions.
  - TPC has no maintained natural-language release.
  - DABStep is not SQL, and its hidden answers leak.

### Cited Findings

#### BIRD-Interact (ICLR 2026)

**Size**
- Full: 600 tasks; Lite: 300 tasks; each has 2 sub-tasks ([paper](https://arxiv.org/html/2510.05318v3)).
- Our count of the HF files: Lite 300 rows over 18 DBs ([Lite](https://huggingface.co/datasets/birdsql/bird-interact-lite)); Full 600 rows over 22 DBs ([Full](https://huggingface.co/datasets/birdsql/bird-interact-full)).
- The README also calls Lite "270" ([GitHub](https://github.com/bird-bench/BIRD-Interact)).
- Mini-Interact (SQLite): 300 business-intelligence tasks over 26 DBs (our count) ([card](https://huggingface.co/datasets/birdsql/mini-interact)).

**Dialect:** PostgreSQL 14 in Docker; Mini-Interact ships SQLite.

**Complexity:** 361.52 tokens per SQL (Lite) and 252.21 (Full); 5.16 / 3.89 ambiguities per task ([paper Table 1](https://arxiv.org/html/2510.05318v3)).

**External knowledge:** a hierarchical knowledge base (a DAG of definitions) plus column-meaning files. Ambiguity is injected partly by masking knowledge-base nodes.

**Provenance:** tasks were converted from LiveSQLBench by expert annotators.

**Access, license and restrictions**
- Gold SQL and test cases are withheld "to avoid data leakage by auto-crawling" and sent by automatic email reply ([card](https://huggingface.co/datasets/birdsql/bird-interact-full)).
- Data CC BY-SA 4.0.
- No explicit "do not train" term.

**Errors (claimed):** on 300 samples, 98.7% SQL correctness and 97.3% overall acceptance ([paper App.](https://arxiv.org/html/2510.05318v3)). No independent audit.

**Overlap:** none. DB names include alien, archeology, credit, crypto, cybermarket, households, labor_certification_applications and organ_transplant.

#### LiveSQLBench ("BIRD-SQL Pro v0.5")
- **Releases** ([GitHub](https://github.com/bird-bench/livesqlbench))

  | Release | Date | Tasks | DBs | Notes |
  |---|---|---|---|---|
  | Base-Lite | 2025-05-30 | 270 (180 SELECT / 90 management) | 18 | [card](https://huggingface.co/datasets/birdsql/livesqlbench-base-lite) |
  | Base-Lite-SQLite | 2025-07-28 | 270 | 18 | 20+ queries adapted for SQLite ([card](https://huggingface.co/datasets/birdsql/livesqlbench-base-lite-sqlite)) |
  | Base-Full-v1 | 2025-09-04 | 600 | 22 | [card](https://huggingface.co/datasets/birdsql/livesqlbench-base-full-v1) |
  | Large-v1 | 2026-03-02 | 480 | 18 | about 54 tables, 986 columns and 84K prompt tokens per DB ([card](https://huggingface.co/datasets/birdsql/livesqlbench-large-v1)) |

- **Dialect:** PostgreSQL. SQLite template DBs exist for Base-Lite only (our check).
- **Gold:** withheld in every public file (our check), and sent by email.
- **Hidden test:** promised, but not yet live; the "Keep it Live!" item is unchecked ([card](https://huggingface.co/datasets/birdsql/livesqlbench-base-full-v1)).
- **Complexity:** about 360 average SQL tokens for Base-Lite ([site](https://livesqlbench.ai)). Base-Lite difficulty, our count: 91 Simple, 124 Moderate, 55 Challenging. No paper exists yet.
- **External knowledge:** a per-DB knowledge base (JSONL with dependency links) plus column meanings. Large-v1 adds versioned "business rule drift".
- **Data:** sample rows look Faker-generated (our check of [alien_schema.txt](https://huggingface.co/datasets/birdsql/livesqlbench-base-lite/blob/main/alien/alien_schema.txt)). The README says only that it is built "from extensive and regularly updated CSV datasets".
- **License:** conflicting. HF metadata says cc-by-4.0, but the card bodies and GitHub say CC BY-SA 4.0.
- **Errors:** the 2026-06-13 changelog revised gold or test cases for 17 Full-v1 instances, i.e. at least 2.8% (our arithmetic).
- **Overlap:** none.
- **Claims and restrictions:** describes itself as "contamination-free"; gold is gated against crawling; no do-not-train term.

#### BIRD-Critic / SWE-SQL (NeurIPS 2025), Six-Gym, BIRD-Fixer
- **Size**
  - Paper: PG 530 issues and Multi 570 ([paper](https://arxiv.org/html/2506.18951v4)).
  - Our count of the HF files: PG 530; [Open](https://huggingface.co/datasets/birdsql/bird-critic-1.0-open) 600 (300 PG, 100 each MySQL, Oracle and SQL Server); [Flash](https://huggingface.co/datasets/birdsql/bird-critic-1.0-flash-exp) 200; [SQLite](https://huggingface.co/datasets/birdsql/bird-critic-1.0-sqlite) 500.
- **Complexity:** solution SQL averages 112.64 tokens (PG) ([paper](https://arxiv.org/html/2506.18951v4)).
- **External knowledge:** none as documents. Each task has issue text plus buggy SQL.
- **Provenance:** real StackOverflow issues, re-implemented on BIRD-dev DBs.
- **Access and license:** gold by email; CC BY-SA 4.0.
- **Six-Gym**
  - The paper says about 3,301 synthetic instances. The HF releases hold 5,000 each in [six-gym-sqlite](https://huggingface.co/datasets/birdsql/six-gym-sqlite) and [six-gym-pg-1.5](https://huggingface.co/datasets/birdsql/six-gym-pg-1.5), with `sol_sql` and test cases public (our count).
  - Fully LLM-generated (Gemini-2.0-Flash, "SQL-Rewind"), with no human verification.
  - Average 94.8 tokens per solution.
- **Models trained on these:** BIRD-Fixer is Qwen2.5-Coder-14B fine-tuned on Six-Gym. BIRD-Talon/Zeno models (Qwen2 architecture) are trained on six-gym-sqlite ([BIRD-RL](https://github.com/bird-bench/BIRD-RL)).
- **Overlap (verified)**
  - BIRD-Critic DBs include **formula_1** and **european_football_2**. A sub-researcher found driver rows identical to the local f1 data. Tasks on these two DBs: Flash 54/200, PG 118/530, Open 130/600, SQLite 113/500.
  - Six-Gym's 13 DBs (our check of the [HF tree](https://huggingface.co/datasets/birdsql/six-gym-sqlite/tree/main/database)): address, airline, book_publishing_company, books, car_retails, **chinook**, employees, hockey, lego, **movie_3**, netflix, olympics, public_review_platform.
    - Sub-researcher row checks: chinook track 744 matches the local chinook/music data; movie_3 film 4 matches Sakila; Six-Gym's `airline` is the Postgres Pro demo (identical aircrafts_data rows), i.e. local **Airlines**. BIRD's own `airline` is US flight data and does not match.
    - Tasks on these three DBs: 1,179 of 5,000 (SQLite) and 1,253 of 5,000 (PG).

#### Termite (Ranaldi et al., Findings ACL 2024)
- **Size:** 202 queries over 10 hand-made DBs ([paper](https://arxiv.org/html/2402.08100v1)).
- **Format:** SQLite plus dumps in a password-protected zip ([repo](https://github.com/ART-Group-it/Termite)).
- **Language:** questions and schema names are **Italian** (our check).
- **Complexity:** average 16.5 tokens per SQL.
- **License:** GPL-3.0. The zip password is public. Encryption only keeps the data out of crawls.
- **Overlap:** none. Its `bowling` DB is a hand-made Italian schema, not BowlingLeague.

#### SQLStorm (PVLDB 2025)
- **Size and data:** 18,251 GPT-4o-mini-generated queries over StackOverflow data at 3 scales ([paper](https://db.in.tum.de/~schmidt/papers/sqlstorm.pdf)). **No natural-language questions.**
- **Engines:** queries are kept if they parse on at least 2 of PostgreSQL, Umbra and DuckDB.
- **Errors (authors' measurement)**
  - A manual check of 100 queries found 53% correct, 34% almost correct, 13% incorrect.
  - 5,664 queries give inconsistent results across engines.
- **License:** MIT repo ([GitHub](https://github.com/SQL-Storm/SQLStorm)).

#### TPC-H / TPC-DS
- **Size:** TPC-H has 22 queries over 8 tables ([spec](https://www.tpc.org/TPC_Documents_Current_Versions/pdf/TPC-H_v3.0.1.pdf)); TPC-DS has 99 query templates ([spec](https://www.tpc.org/TPC_Documents_Current_Versions/pdf/TPC-DS_v4.0.0.pdf)). Each query has an official natural-language "Business Question".
- **Complexity:** TPC-DS averages 6.30 joins and 1,370 bytes per query ([SQLStorm Table 6](https://db.in.tum.de/~schmidt/papers/sqlstorm.pdf)).
- **License:** the [TPC EULA](https://tpc.org/TPC_Documents_Current_Versions/txt/eula.txt) restricts redistribution and derivatives.
- **NL versions:** only ad-hoc studies found: 22 rephrased TPC-H questions ([Kim & So, VLDB 2020](https://www.vldb.org/pvldb/vol13/p1737-kim.pdf)) and the 99 TPC-DS descriptions ([Ma, Pu & Zhu 2024](https://arxiv.org/html/2407.19517v1)). No maintained NL-to-gold-SQL release was found.
- **Overlap:** none.

#### DA-Code (EMNLP 2024): a contamination hazard
- **Size:** 500 agentic data-science tasks (Python, SQL, Bash); outputs are files, not SQL ([paper](https://arxiv.org/html/2410.07331)). MIT ([GitHub](https://github.com/yiyihum/da-code)).
- **Same data as local DBs**
  - Task source folders ship the local **Baseball** tables ([dm-csv-015](https://github.com/yiyihum/da-code/tree/main/da_code/source/dm-csv-015)) and the **delivery_center** tables ([plot-pie-008](https://github.com/yiyihum/da-code/tree/main/da_code/source/plot-pie-008)).
  - A wrestling schema with the same core tables as local WWE (wrestlers, belts, cards, events, locations, matches, promotions, but no separate match_types table) appears in the [DA-Code HF data](https://huggingface.co/datasets/Writer/DA-Code-data/blob/109268edc742a6a36ed87cc1366cf8943f872e46/source/data-wrangling-047/schema.yml). This was seen in a search snippet; the full file was not diffed.
- **Near-duplicate questions:** our token-overlap screen of all 500 tasks in [all.jsonl](https://github.com/yiyihum/da-code/blob/main/da_code/configs/task/all.jsonl) against the 135 local questions, confirmed by reading:

  | Local question | DA-Code task | What both ask |
  |---|---|---|
  | local019 (WWE) | di-csv-016 | the shortest NXT title match and its wrestlers |
  | local008 (Baseball) | data-wrangling-084 | the top player for games, runs, hits and home runs |
  | local007 (Baseball) | data-wrangling-089 | career span from debut and final game |
  | local085 (northwind) | di-csv-035 | late orders per employee |
  | local049 (modern_data) | data-wrangling-098 | unicorn companies, 2019–2021, top industries |

  The IPL bowling tasks (data-wrangling-083/097) are similar in theme to local258, local259 and local025.

#### DABStep (Adyen and HF, 2025)
- **Size:** 450 tasks (72 easy / 378 hard) plus a 10-task dev set; Python over CSV/JSON; CC BY 4.0 ([paper](https://arxiv.org/html/2506.23719v1), [HF](https://huggingface.co/datasets/adyen/DABstep)).
- **Hidden answers leak:** they are hidden, but the public task_scores split pairs submitted answers with true/false scores. Every one of the 450 tasks has at least one public correct answer (sub-researcher count).
- **Not SQL.**

### Inferences
- **LiveSQLBench and BIRD-Interact are the strongest non-Spider2 held-out candidates.** They have long SQL, knowledge-base documents, business-style domains, no DB overlap, and gold gated against crawling.
  - SQLite exists only for Base-Lite (270) and Mini-Interact (300).
  - The data looks synthetic, so previews may be less realistic than Spider 2.0-Lite's real data.
- **Six-Gym** is public, judge-friendly training data (buggy versus fixed SQL), after dropping its chinook, movie_3 and airline tasks.
- **BIRD-Critic** is better kept as evaluation, after dropping its formula_1 and european_football_2 tasks.
- **DA-Code must be excluded from both training and evaluation.** Its tasks rest on the same tutorial and Kaggle sources as several local questions.

### Gaps
- Six-Gym has no human-verified error rate.
- LiveSQLBench has no paper and no independent audit.
- DA-Code's full overlap was screened by token similarity plus reading the top matches. A lower-similarity paraphrase could have been missed.
- The original upstream sources for DA-Code's WWE and delivery data were not traced.

---

## 5. Newer 2025–2026 enterprise benchmarks and "judge-shaped" sets (labelled candidates, multiple golds)

### Takeaway
- **Spider 2.0-AIFunc (July 2026) is a rewrite of Spider 2.0 tasks.** It contains 107 rows that rewrite 83 local questions, so it must be excluded.
- **Closest in style to Spider 2.0-Lite:**
  - EntSQL: 388.7-token SQL; 96% of questions need a long document; SQLite. Gold is not released.
  - BEAVER v3: see §2.
- **For judge evaluation specifically:**
  - NL2SQL-Bugs has 2,018 labelled candidates, 440 of them on overlapping DBs.
  - FLEX has 200 expert-judged pairs.
  - ARCS (Oct 2026) has 101 questions with 413 golds and explicit conventions on ties and on names versus IDs.

### Cited Findings

**Spider 2.0-AIFunc** (Snowflake, July 2026)
- Paper: 465 instances, derived from Spider2-Snow ([arXiv](https://arxiv.org/html/2607.06229)).
- Our count of the HF file ([HF](https://huggingface.co/datasets/tianyang/spider2-aifunc)): **393 rows; 107 are `sf_local*` rows rewriting 83 distinct local questions across 28 of the 30 local DBs.**
  - Example: sf_local002 is local002 (E_COMMERCE) rewritten to use AI_SIMILARITY.
- Gold is held out; MIT ([GitHub](https://github.com/Leolty/Spider2-AIFunc)).

**EntSQL** (2026; HKUST-GZ, Alibaba, Qwen Team)
- 1,066 Chinese–English examples over 5 domains, in SQLite.
- Gold SQL averages 388.7 tokens with frequent CTEs; 96.0% of questions need knowledge from documents of about 3.6K tokens; the best system scores 15.9% ([arXiv](https://arxiv.org/html/2606.03363)).
- Gold is **not provided**; the public JSON has only id, long_doc and question. CC BY 4.0 ([HF](https://huggingface.co/datasets/XuWave/Rethinking_Enterprise_Text_to_SQL)).
- Data comes from real enterprise logs, anonymized.

**DAComp** (ICLR 2026)
- 210 tasks ([paper](https://arxiv.org/html/2512.04324)).
- The data-engineering part uses dbt-style pipelines with public gold ([dacomp-de-gold](https://huggingface.co/datasets/DAComp/dacomp-de-gold)).
- The data-analysis part (100 SQLite DBs) is open-ended, scored by rubrics, with **no gold SQL** ([HF](https://huggingface.co/datasets/DAComp/dacomp-da)). MIT.

**ELT-Bench** (PVLDB 19)
- 100 pipelines; ground-truth CSVs are public; CC BY-SA 4.0 ([arXiv](https://arxiv.org/html/2504.04808v2), [GitHub](https://github.com/uiuc-kang-lab/ELT-Bench)).
- Uses 78 BIRD DBs, **including formula_1, european_football_2, movie_3, works_cycles, retail_world and soccer_2016** ([pipeline list](https://github.com/uiuc-kang-lab/ELT-Bench/tree/main/elt-bench/snowflake)).

**Other 2025–2026 benchmarks**
- **KramaBench** (ICLR 2026): 104 Python tasks; 20% held out; no license ([arXiv](https://arxiv.org/html/2506.06541)).
- **SNAILS** (SIGMOD 2025): 503 pairs over 9 real DBs; SQL Server with a SQLite download; Apache-2.0 ([GitHub](https://github.com/KyleLuoma/SNAILS)).
- **CORGI** (2025): 1,200 questions over 10 synthetic SQLite DBs; gold only for part of dev; MIT ([arXiv](https://arxiv.org/html/2510.07309)).
- **TACO** (June 2026): 1,500 real plus 13,000 synthetic smart-city questions; CC BY-NC-ND 4.0 ([arXiv](https://arxiv.org/html/2606.14201)).
- Semantic-layer sets: ACME Insurance (11 questions in the dbt 2026 run, [blog](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)) and Contoso (100 questions, ClickHouse, [arXiv](https://arxiv.org/abs/2604.25149)).
- WarehouseReliabilityBench (400 synthetic, [arXiv](https://arxiv.org/abs/2608.09254)) and ProcArena (3,998 PL/SQL, [arXiv](https://arxiv.org/abs/2609.06527)). Their gold availability and licenses were not checked.
- **BIRD 2.0** is "under development"; `birdsql/bird-pro-0.5` is an empty placeholder ([site](https://bird-bench.github.io/)).

**NL2SQL-Bugs** (KDD 2025)
- 2,018 candidates: 1,019 correct and 999 incorrect, over 1,257 BIRD-dev questions.
- Taxonomy: 9 error types and 31 subtypes.
- Includes BIRD evidence.
- Label quality: correct means an execution match against a cleaned BIRD gold; the type annotation has κ=0.78 ([paper](https://arxiv.org/html/2503.11984), [repo](https://github.com/HKUSTDial/NL2SQL-Bugs-Benchmark)).
- Most frequent subtypes among negatives (our count): Attribute Mismatch 360, Explicit Condition 242, Value Mismatch 238, Table Redundancy 119, Join Condition Mismatch 79.
- Overlap: formula_1 has 270 instances and european_football_2 has 170 (our count).
- No license file.

**FLEX expert set** (NAACL 2025)
- 200 BIRD prediction pairs, each with a human verdict, from california_schools (160) and financial (40). No overlap. Apache-2.0 ([repo](https://github.com/HeegyuKim/FLEX), [paper](https://arxiv.org/html/2409.19014)).

**ARCS** (Oct 2026; Databricks / Megagon)
- 101 questions expanded into 311 test instances; 413 gold SQL (mean 4.09 per question).
- 6 real SQLite DBs: 5 from BIRD (retails, codebase_community, student_club, financial, professional_basketball) and the Spider 2.0 BigQuery DB github_repos, which is not in the local split. CC BY 4.0 ([HF](https://huggingface.co/datasets/megagonlabs/arcs), [paper](https://arxiv.org/html/2610.09396)).
- Conventions given to systems:
  - return names where available, otherwise IDs;
  - return all tied objects for argmax/argmin;
  - extra columns are allowed;
  - percentages are not multiplied by 100;
  - no rounding.
- Authors' process: more than 60% of questions had errors after the first annotation round, and fewer than 2% were flagged in the final pass.

**Unreleased or not judge-ready sets**
- TIDE-Bench (Aug 2026): data not released ([repo](https://github.com/Rcrossmeister/TIDE-Bench)).
- SynCA (Sep 2026): human gold sets deferred ([paper](https://arxiv.org/html/2609.30290)).
- SQL-equivalence sets (Spider+DIN: 385 equivalent / 189 non-equivalent pairs; LLM-SQL-Solver: 70 pairs) compare SQL with SQL and have no question ([SQLEquiQuest](https://arxiv.org/html/2412.05561), [LLM-SQL-Solver](https://arxiv.org/html/2312.10321)).

### Inferences
- **For validating the judge directly** (does it pick the correct candidate?), these are the only off-the-shelf labelled sets:
  - NL2SQL-Bugs after dropping its 440 overlap rows (1,578 remain);
  - FLEX (200);
  - SCARE (§2).
- **ARCS's annotation conventions** map onto three of the judge's failure modes: name vs ID keys, ties at a cutoff, single row vs list. ARCS is small but very recent and has no overlap.
- **EntSQL** would be the closest analogue if its gold is released. Its Qwen-team co-authorship is a reason for caution about exposure.

### Gaps
- EntSQL gold release plans: not found.
- Licenses and gold availability for WarehouseReliabilityBench, ProcArena, Contoso and TACO: not checked.
- SCARE's labels and splits: not inspected.

---

## 6. Which databases overlap with Spider 2.0-Lite's 30 local databases?

### Takeaway
- **43 of the 135 local questions** sit on 10 databases that are the same data as BIRD train/dev or Spider 1.0 train databases.
  - Adding the Airlines DB (via Six-Gym) gives 45.
  - Adding 4 partial legislator matches gives 49.
- **Every earlier unverified overlap claim holds.**
- **Missed overlaps:**
  - BIRD dev formula_1 and european_football_2;
  - BIRD legislator (partial);
  - KaggleDBQA, Archer, NL2SQL-Bugs, BIRD-Critic, Six-Gym, ELT-Bench, DA-Code.
- **Public derivatives of Spider 2.0-Lite itself:** Spider 2.0-AIFunc, the Genies rollout datasets (all 135 questions), nl2sqlproj/spider2-nl2sql, and a multilingual copy.

### Cited Findings

**Local question counts per DB** (our count of [spider2-lite.jsonl](https://github.com/xlang-ai/Spider2/blob/main/spider2-lite/spider2-lite.jsonl)): IPL 11, sqlite-sakila 7, Pagila 2, f1 9, EU_soccer 5, chinook 3, music 1, Baseball 2, northwind 2, AdventureWorks 1, Airlines 2, city_legislation 10. Table lists come from [resource/databases/sqlite](https://github.com/xlang-ai/Spider2/tree/main/spider2-lite/resource/databases/sqlite).

**Overlaps by local DB**

| Local DB (questions) | Same data in | Evidence (who checked) |
|---|---|---|
| IPL (11) | BIRD train **soccer_2016** | Same ball_by_ball, batsman_scored, extra_runs, wicket_taken and player_match columns, and the same match IDs (335987…). BIRD adds lookup tables (sub-researcher, [BIRD train](https://huggingface.co/datasets/xu3kev/BIRD-SQL-data-train)). |
| sqlite-sakila (7), Pagila (2) | BIRD train **movie_3**; Spider train **sakila_1**; Six-Gym **movie_3** | All 16 Sakila tables; film 4 "AFFAIR PREJUDICE" row-identical (sub-researchers). |
| f1 (9) | BIRD dev **formula_1** (174 Qs); Spider train **formula_1** (80 Qs); BIRD-Critic; NL2SQL-Bugs (270 rows); Archer public; ELT-Bench | 13 core Ergast tables; identical `races` columns; an older snapshot with camelCase names. The local DB adds 16 extra tables (sub-researchers; [dev prompts](https://github.com/bird-bench/mini_dev)). |
| EU_soccer (5) | BIRD dev **european_football_2** (129 Qs); Spider train **soccer_1** (14 Qs, no Match table); BIRD-Critic; NL2SQL-Bugs (170 rows); Archer public (soccer_1); ELT-Bench | All 7 tables in BIRD; identical `Player` columns. All 5 local EU_soccer tasks use Match (sub-researchers). |
| chinook (3) | Spider train **store_1** (112 Qs); Six-Gym **chinook** (track 744 row-identical) | Chinook in sqlitetutorial naming (sub-researchers). |
| music (1) | Spider train **chinook_1** (84 Qs) | 11 of 11 CamelCase tables identical (sub-researchers). |
| Baseball (2) | Spider train **baseball_1** (82 Qs); KaggleDBQA **TheHistoryofBaseball**; DA-Code dm-csv-015 | 26 tables identical to baseball_1; KaggleDBQA has a 5-table subset (sub-researchers; [KaggleDBQA](https://github.com/Chia-Hsuan-Lee/KaggleDBQA/blob/main/DATASETS.md)). |
| northwind (2) | BIRD train **retail_world** (373 Qs; 38 after filtering) | 8 of the 15 local tables (W3Schools subset); BIRD's gold SQL uses the full Northwind columns (sub-researchers). |
| AdventureWorks (1) | BIRD train **works_cycles** (474 Qs); ELT-Bench | All 13 local tables present with matching SalesOrderHeader columns (sub-researchers). |
| Airlines (2) | Six-Gym **airline** (Postgres Pro demo) | Identical aircrafts_data rows ([PG dump](https://huggingface.co/datasets/birdsql/six-gym-pg-1.5/tree/main/databases/airline_template)). BIRD's `airline` (US flight data) is **not** this DB. |
| city_legislation (4 of 10: local167, 169, 170, 171) | BIRD train **legislator** (177 Qs), partial | Same upstream congress-legislators IDs (the local `legislators` table has id_bioguide, id_govtrack, …; our inspection). Different schema and snapshot. The other 6 questions use city, job-posting and alien tables. |

**Checked and found not overlapping** (sub-researchers)
- BIRD airline vs local Airlines; BIRD european_football_1 vs EU_soccer.
- BIRD movie / movielens / movies_4 / movie_platform and Spider imdb / movie_1 vs Db-IMDB and imdb_movies.
- Spider wrestler vs WWE; Spider flight_* vs Airlines.
- KaggleDBQA WorldSoccerDataBase vs EU_soccer.
- Termite bowling vs BowlingLeague.
- SynSQL, Gretel and the BIRD-Interact / LiveSQLBench DBs vs everything.
- No public text-to-SQL train set found holds Olist, SWITRS, the Mere Mortals DBs, the Oracle-book DBs, bank_sales_trading, modern_data, log, stacking, delivery_center or education_business. DA-Code does hold some of these (§4).

**Verification of the earlier unverified pass**
- Confirmed: BIRD movie_3 ≈ Sakila, works_cycles ≈ AdventureWorks, soccer_2016 ≈ IPL; Spider sakila_1, chinook_1, store_1, soccer_1, formula_1, baseball_1.
- retail_world ≈ Northwind is **partial**: the DB file is the 8-table W3Schools schema.
- Refinements:
  - chinook_1 corresponds to local **music**, and store_1 to local **chinook**.
  - soccer_1 lacks the Match table.

**Public copies or derivatives of the Spider 2.0-Lite local split itself**
- **Spider 2.0-AIFunc:** 107 rows rewriting 83 local questions over 28 DBs (our count; §5).
- **Genies rollouts** (our check of the parquet files)
  - Datasets: [Genies/text2sql-sft-kumar-v9_sqlite-steps](https://huggingface.co/datasets/Genies/text2sql-sft-kumar-v9_sqlite-steps) (7,813 step rows) and [Genies/text2sql-grpo-d6-e17-deema_sqlite-steps](https://huggingface.co/datasets/Genies/text2sql-grpo-d6-e17-deema_sqlite-steps) (8,129 step rows).
  - Both were created 2026-02-16, are ungated and carry no license.
  - They are agent rollouts on **all 135 local instance IDs across all 30 DBs**, with the local question text verbatim in 122 of 135 IDs. Each step has its SQL, execution output and a `solved` flag (1,192 and 1,193 rows marked solved).
- **nl2sqlproj/spider2-nl2sql** (2025-08-07, MIT): qa.csv plus sqlite_ddl.csv of Spider 2.0. A sub-researcher reports its card labels it "for the purpose of training" ([HF](https://huggingface.co/datasets/nl2sqlproj/spider2-nl2sql)).
- **GitHub mirrors:** the local DB schemas are copied, including in several translations, in [phkhanhtrinh23/Multilingual_Text_to_SQL](https://github.com/phkhanhtrinh23/Multilingual_Text_to_SQL), and Spider 2.0 resources are mirrored in [Snowflake-Labs/ReFoRCE](https://github.com/Snowflake-Labs/ReFoRCE) (our GitHub code search).
- **Question text spread:** local002's exact question text appears in 112 GitHub files (sub-researcher code search).
- **Spider 2.0-Snow and DBT** contain Snowflake versions of the local questions (36 sf_local gold files; §1).

### Inferences
- **For training data,** filter by database identity as well as by name. Drop the DB list above from any source, and use a deny-list of Spider 2.0-derived artifacts: AIFunc, Genies, nl2sqlproj, the multilingual copies, Snow/DBT and DA-Code.
- **Legislator decision:** dropping BIRD legislator costs 177 train items. Keeping it exposes the judge to the same underlying entities as 4 local questions, but not the same schema. Strict hygiene says drop it.
- **Reporting:** whatever is kept, report judge accuracy separately on the 43–49 overlapping local questions and the remaining 86–92. Then any residual leakage shows up as a gap between the two groups.

### Gaps
- Row-level identity checks covered only a sample of rows per DB. For IPL, AdventureWorks and northwind the evidence is schema- and ID-level, not a full data diff.
- Overlap with BIRD's hidden test DBs is unknown, because their names are not public.
- The Genies datasets' authors and training use are not documented on their cards.

---

## 7. Where did the Spider 2.0-Lite local databases come from?

### Takeaway
- **The paper gives no per-database source list.** It says only that 30 SQLite DBs were selected and that the SQL was gathered "from the corresponding tutorials and forums", then rewritten to avoid leakage.
- **From table names and sample rows,** most local DBs trace to Kaggle datasets, classic sample databases, SQL books, and SQL-course or challenge datasets (8 Week SQL Challenge, DataCamp, Codebasics, Udacity, Luke Barousse).
- **Several local DBs are composites** of unrelated tutorial datasets.

### Cited Findings

**What the paper says** ([Spider 2.0](https://arxiv.org/html/2411.07763v2))
- "we select 74 BigQuery, 54 Snowflake, 30 SQLite, 40 DuckDB, 10 PostgreSQL, and 5 ClickHouse databases. From the corresponding tutorials and forums, we gather 1,021 complex SQL queries."
- Queries "must originate from real projects or tutorials".
- "SQL rewrite to prevent data leakage … annotators are required to rewrite each SQL." A sub-researcher reports 84.2% surface-level and 42% semantic-level rewrites ([paper](https://arxiv.org/html/2411.07763)).

**Single-source DBs**

| Local DB (questions) | Source | Sources and evidence |
|---|---|---|
| AdventureWorks (1) | Microsoft AdventureWorks (13-table subset) | [microsoft/sql-server-samples](https://github.com/microsoft/sql-server-samples) |
| Airlines (2) | Postgres Pro "Airlines" demo DB (aircrafts_data, airports_data, boarding_passes, …) | [Postgres Pro demodb](https://postgrespro.com/community/demodb). License conflict: the [current page](https://postgrespro.com/education/demodb) says MIT; the docs say the PostgreSQL license. |
| Baseball (2) | Lahman data via Kaggle "The History of Baseball" | [Kaggle](https://www.kaggle.com/datasets/seanlahman/the-history-of-baseball); same 26 tables as Spider baseball_1 |
| BowlingLeague (1), EntertainmentAgency (3), school_scheduling (1) | *SQL Queries for Mere Mortals* sample DBs (Viescas), with tables such as Bowler_Scores and ztblDays | [Pearson README](https://ptgmedia.pearsoncmg.com/imprint_downloads/informit/bookreg/9780321992475/9780321992475_README.html), [O'Reilly App. B](https://www.oreilly.com/library/view/sql-queries-for/9780133824889/app02.html) |
| Brazilian_E_Commerce (8) | Olist Brazilian E-Commerce (Kaggle) | [Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) |
| E_commerce (3) | Olist e-commerce plus the Olist Marketing Funnel (leads_qualified, leads_closed) | [Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce); funnel described in [Catherinedataa/Olist-Sales-Funnel-Analysis](https://github.com/Catherinedataa/Olist-Sales-Funnel-Analysis) |
| electronic_sales (1) | Olist-structured tables and data (hash IDs, São Paulo customers) | Our inspection of sample rows |
| California_Traffic_Collision (3) | SWITRS dump by Alex Gude (case_ids, collisions, parties, victims) | [Zenodo](https://zenodo.org/records/4284843), [switrs-to-sqlite](https://pypi.org/project/switrs-to-sqlite) |
| EU_soccer (5) | Kaggle European Soccer Database | [Kaggle](https://www.kaggle.com/datasets/hugomathien/soccer) |
| IPL (11) | Kaggle "Indian Premier League SQLite Database" | [Kaggle](https://www.kaggle.com/datasets/harsha547/ipldatabase) |
| f1 (9) | Ergast F1 data (Kaggle), plus extra tables (lap_positions, liveries, tdr_overrides, team_driver_ranks, `*_ext`) of unidentified origin | [Kaggle F1](https://www.kaggle.com/datasets/rohanrao/formula-1-world-championship-1950-2020); our table listing |
| Pagila (2), sqlite-sakila (7) | Sakila / Pagila | [devrimgunduz/pagila](https://github.com/devrimgunduz/pagila) |
| chinook (3) | Chinook, sqlitetutorial.net version | [sqlitetutorial](https://www.sqlitetutorial.net/sqlite-sample-database/) |
| music (1) | Chinook, original CamelCase version | [lerocha/chinook-database](https://github.com/lerocha/chinook-database) |
| northwind (2) | Northwind (with usstates, customergroupthreshold) | [microsoft/sql-server-samples](https://github.com/microsoft/sql-server-samples); source of customergroupthreshold not confirmed |
| oracle_sql (8) | Apress *Practical Oracle SQL* (Kim Berg Hansen) schema | [Apress/practical-oracle-sql](https://github.com/Apress/practical-oracle-sql) (sub-researcher) |
| complex_oracle (6) | Oracle Sales History (SH) sample schema | [oracle-samples/db-sample-schemas](https://github.com/oracle-samples/db-sample-schemas) (sub-researcher) |
| delivery_center (3) | Kaggle sample from Delivery Center (Brazil): channels, deliveries, drivers, hubs, orders, payments, stores | [news coverage of the Kaggle sample](https://gironews.com/varejo-digital/marketplaces-no-delivery-65728/); DA-Code ships the same tables |

**Composite DBs**
- **bank_sales_trading (15)**
  - 8 Week SQL Challenge case studies: Data Bank (customer_nodes, customer_regions, customer_transactions), plus weekly_sales, Clique Bait-style shopping_cart_* tables and interest_* tables ([case study 4](https://8weeksqlchallenge.com/case-study-4/)).
  - Also bitcoin_* tables and vegetable-wholesale veg_* tables of unidentified origin.
- **modern_data (7)**
  - DataCamp "Analyzing Unicorn Companies" (companies_*), whose task matches local049 ([DataCamp](https://www.datacamp.com/projects/1531)).
  - 8 Week SQL Challenge Pizza Runner (pizza_*) ([case study 2](https://8weeksqlchallenge.com/case-study-2/)).
  - NYC street trees plus income by zip (trees, income_trees), COVID statistics by state, and word_list (sources not confirmed).
- **education_business (5)**
  - Codebasics AtliQ Hardware (hardware_dim/fact_*) ([example repo](https://github.com/zrhirok/SQL_Analysis_Codebasics_Challenge)).
  - Parch & Posey from Udacity's SQL course (web_*) ([example](https://github.com/immu0001/Udacity-SQL-for-Data-Analysis)).
  - A university course DB (sample row "IS480 Fundamentals of Database Management"), a Glassdoor-style India salary dataset, and StaffHours (sources not confirmed).
- **city_legislation (10)**
  - US legislators with congress-legislators IDs (id_bioguide, id_govtrack, id_icpsr, …; our inspection).
  - Luke Barousse's SQL-course job-postings star schema (job_postings_fact, skills_dim, skills_job_dim) ([course page](https://lukebarousse.notion.site/Hands-On-Project-SQL-Course-944fd5a160414ed68952a3b1529321a3)).
  - Cities with insert dates, and alien tables (sources not confirmed).

**Sources not identified**
- **log (5):** access_log, action_log, purchase_log, mst_users, form_log, read_log, and others. A GitHub code search finds these names only in Spider 2.0 copies.
- **stacking (3):** ML stacking-experiment tables whose `problem` rows cite Kaggle datasets (our inspection).
- **WWE (1):** a wrestling DB also present in DA-Code ([HF DA-Code schema](https://huggingface.co/datasets/Writer/DA-Code-data/blob/109268edc742a6a36ed87cc1366cf8943f872e46/source/data-wrangling-047/schema.yml)).
- **Db-IMDB (5):** IMDb-derived teaching DB with M_* mapping tables.
- **imdb_movies (2):** IMDb movie case-study DB with an "ERD" sheet as a table.

**Public prevalence of the main sources** (sub-researcher search via the [GitHub REST code-search API](https://docs.github.com/en/rest/search/search), 2026-10-27; approximate counts)

| Search string | Points to | Hits |
|---|---|---|
| "film_actor rental inventory" | Sakila | 11,520 |
| "SalesOrderHeader SalesOrderDetail" | AdventureWorks | 16,032 |
| "olist_order_items" | Olist | 11,952 |
| "constructorStandings driverStandings" | Ergast F1 | 10,416 |
| "InvoiceLine MediaType PlaylistTrack" | Chinook | 6,032 |
| "Player_Attributes Team_Attributes" | European Soccer | 3,800 |
| "batsman_scored ball_by_ball" | IPL | 708 |
| "runner_orders pizza_toppings" | 8 Week SQL Challenge | 785 |
| "Bowler_Scores" | Mere Mortals | 376 |
| "conway_gen_zero" | Practical Oracle SQL | 82 |

Kaggle downloads: Olist 680,036; European Soccer 281,595; F1 171,800; History of Baseball 13,978; IPL SQLite 6,420 (sub-researcher, Kaggle API).

### Inferences
- **Almost every local DB comes from public tutorials, books, courses or Kaggle.** A Qwen model has very likely seen the schemas, and often published SQL solutions for similar questions, regardless of any benchmark data. The Spider 2.0 authors' rewriting reduces but does not remove this exposure.
- **The same tutorial sources feed other datasets.** That explains why DA-Code and Spider 2.0 converge on near-identical questions (§4). Any dataset built from "SQL tutorials and Kaggle notebooks" should be screened question by question, not only by DB name.

### Gaps
- Original sources not confirmed for: log, stacking, WWE, Db-IMDB, imdb_movies; the f1 extra tables; the bitcoin_* and veg_* tables; and the alien, cities, university, StaffHours and salary tables.
- Two GitHub code searches (for the log and stacking table names) returned only Spider 2.0 copies. Further searches were blocked by the GitHub API rate limit.
- Which book or course the legislators cohort tables came from was not confirmed.

---

## 8. Which datasets most resemble Spider 2.0-Lite in difficulty?

### Takeaway
- **Closest on SQL length, multi-step analytic structure and documents:**
  - EntSQL (gold not released);
  - LiveSQLBench / BIRD-Interact (gold by email; PostgreSQL, partly SQLite);
  - BEAVER v3 (public gold; MySQL; no free-text documents).
- **Next tier:**
  - BIRD Mini-Dev 1024 and the SynSQL Highly Complex tier (CTE-heavy but short);
  - Archer (arithmetic and commonsense reasoning, small).
- **Not comparable:** classic Spider-family sets are far simpler.

### Cited Findings

**Reference: Spider 2.0-Lite's own length**
- 144.5 tokens per SQL and 803.6 columns per DB in Spider 2.0's Table 2, against BIRD 30.9, Spider 18.5, KaggleDBQA 13.8 and SEDE 46.9 ([Spider 2.0](https://arxiv.org/html/2411.07763v2)).
- BIRD-Interact and SWE-SQL instead report **412.37 tokens** for Spider 2.0-Lite gold ([BIRD-Interact Table 4](https://arxiv.org/html/2510.05318v3), [SWE-SQL Table 6](https://arxiv.org/html/2506.18951v4)). The two counts presumably use different tokenizers, so compare only within one paper's table.

**Lengths and features of candidate sets** (each set's own tokenization)

| Dataset | Tokens per SQL | Other features | Source |
|---|---|---|---|
| EntSQL | 388.7 | 96% of questions need a long document | [arXiv](https://arxiv.org/html/2606.03363) |
| BIRD-Interact Lite / Full | 361.52 / 252.21 | knowledge base | [paper](https://arxiv.org/html/2510.05318v3) |
| LiveSQLBench Base-Lite | about 360 | knowledge base | [site](https://livesqlbench.ai) |
| BEAVER v3 | 316.7 | 5.7 joins, 3.7 CTEs, 5.6 nesting levels | [v3](https://arxiv.org/html/2409.02038v3) |
| BIRD-Critic PG | 112.64 | — | [paper](https://arxiv.org/html/2506.18951v4) |
| SynSQL | 57.05 | 42.2% use a CTE | [paper](https://arxiv.org/html/2503.02240) |
| BIRD Mini-Dev 1024 | 56.0 | 30% use a CTE | our count |
| BIRD train | 24.75–25.8 | — | OmniSQL / our count |
| Spider | 14.85 | — | [OmniSQL](https://arxiv.org/html/2503.02240) |

- Archer: SQL length 79.71, and every question needs arithmetic ([paper](https://arxiv.org/html/2402.12554v2)).
- TPC-DS: 6.30 joins per query ([SQLStorm](https://db.in.tum.de/~schmidt/papers/sqlstorm.pdf)).

**Headline scores**
- EntSQL best 15.9% ([arXiv](https://arxiv.org/html/2606.03363)); BEAVER v3 GPT-5.2 agentic 10.8% ([v3](https://arxiv.org/html/2409.02038v3)).
- OmniSQL-7B scores 10.4% greedy on the 135-question Spider2.0-SQLite set ([OmniSQL](https://arxiv.org/html/2503.02240)).

### Inferences
Ranked by resemblance to Spider 2.0-Lite local:
1. EntSQL. Unusable for labelling until gold is released.
2. LiveSQLBench Base-Full-v1 / Large-v1 / Base-Lite-SQLite.
3. BIRD-Interact (the same tasks with ambiguity added; prefer the unambiguous LiveSQLBench versions).
4. BEAVER v3.
5. DAComp-DA (similar analytic tasks, but no gold SQL).
6. BIRD Mini-Dev 1024.
7. SynSQL Highly Complex.
8. Archer.
9. TPC-DS (heavy SQL, but only 99 one-line questions, synthetic data, and widely memorized).

DA-Code and Spider 2.0-AIFunc are the closest of all, because they share sources and questions, and are therefore excluded.

### Gaps
- No study puts all of these sets on one tokenizer.
- Spider 2.0-Lite *local-only* SQL statistics are not published; gold SQL is public for only 24 local questions, per the project's CLAUDE.md.

---

## 9. Which datasets are test-only or restrict training, and which have usable train splits?

### Takeaway
- **Explicitly not for training:**
  - Spider 2.0 (no train split; maintainers advise against fine-tuning on its gold).
  - Spider 2.0-derived sets.
  - BIRD's hidden test.
  - Held-out portions of BEAVER, Archer, BookSQL, SParC, CoSQL and KramaBench.
- **Soft request rather than a ban:** AMBROSIA (authors ask that it not be uploaded so it is not used for training).
- **Gated against crawling, with no do-not-train term:** BIRD-Interact, LiveSQLBench, BIRD-Critic.
- **Usable train splits with gold:** BIRD train, Spider train, SynSQL, Gretel, SEDE, EHRSQL, MIMICSQL (credentialed), Archer train/dev, BookSQL train (non-commercial), BEAVER public, ScienceBenchmark synthetic, AmbiQT/Spider-Syn/SParC/CoSQL/MMSQL train, Six-Gym, NL2SQL-Bugs.

### Cited Findings

**Not for training, or held out**

| Dataset | Status | Source |
|---|---|---|
| Spider 2.0 | No train split. README: "we do not recommend using the Spider 2.0 Gold SQL we released for fine-tuning". Maintainers: "cannot be used for training" and "only a test set". | [README](https://github.com/xlang-ai/Spider2/blob/main/README.md) (line 100 of the local copy), [#49](https://github.com/xlang-ai/Spider2/issues/49), [#8](https://github.com/xlang-ai/Spider2/issues/8) |
| BIRD test | Hidden; 15 new DBs curated "to avoid data leakage" | [paper](https://arxiv.org/html/2305.03111) |
| SParC / CoSQL test | Unreleased | [SParC](https://yale-lily.github.io/sparc), [CoSQL](https://yale-lily.github.io/cosql) |
| Archer test | Blind, 10 DBs | [site](https://sig4kg.github.io/archer-bench/) |
| BookSQL test | Gold withheld; whole dataset non-commercial with no redistribution | [repo](https://github.com/Exploration-Lab/BookSQL), [HF](https://huggingface.co/datasets/Exploration-Lab/BookSQL) |
| BEAVER | Private test of about 1,150 queries | [site](https://beaverbench.github.io/) |
| KramaBench | 20% held out | [arXiv](https://arxiv.org/html/2506.06541) |
| EntSQL | Gold not provided | [HF](https://huggingface.co/datasets/XuWave/Rethinking_Enterprise_Text_to_SQL) |
| DABStep | Answers hidden, but recoverable from public scores (§4) | [paper](https://arxiv.org/html/2506.23719v1) |
| AMBROSIA | Request not to upload "to ensure it is not used for training any LLMs"; CC BY 4.0 | [site](https://ambrosia-benchmark.github.io/) |
| BIRD-Interact / LiveSQLBench / BIRD-Critic | Gold withheld against crawling and sent by email; no do-not-train term | [Interact](https://huggingface.co/datasets/birdsql/bird-interact-lite), [LiveSQL](https://huggingface.co/datasets/birdsql/livesqlbench-base-lite), [Critic](https://github.com/bird-bench/BIRD-CRITIC-1) |
| Evaluation-only by design | Spider-DK (MIT), Spider-Realistic (CC BY-SA 4.0), Dr.Spider (CC BY 4.0), KaggleDBQA (few-shot split may be used for fine-tuning); no legal ban on any | §2, §3 |

**Legal or credential constraints**
- MIMIC-derived data (EHRSQL source data, MIMICSQL) falls under the PhysioNet DUA and its LLM-use guidance ([PhysioNet](https://physionet.org/news/post/llm-responsible-use/)).
- BookSQL is CC BY-NC-SA.
- PRACTIQ's repo is CC BY-NC 4.0.
- TACO's paper is CC BY-NC-ND.
- The TPC EULA restricts redistribution and derivatives.
- SynSQL includes Llama 3.1 outputs, which brings a naming clause (§1).
- BIRD is CC BY-SA ("for research and healthy application only").

**Usable training material with gold**

| Set | Size | Source |
|---|---|---|
| BIRD train | 9,428; filtered 6,601; Platinum 2,088 train / 374 val | §1 |
| Spider train | 8,659 | §1 |
| SynSQL | 2.54M | §1 |
| Gretel | 100k | §1 |
| SEDE train | 10,309 (no DB) | §2 |
| EHRSQL | about 18.6k train | §2 |
| EHRSQL-2024 | 5,124 train | §2 |
| BEAVER public | 7,978 | §2 |
| ScienceBenchmark synthetic | 4,432 | §2 |
| Archer | 518 English | §2 |
| AmbiQT train | 20,249 | §3 |
| Spider-Syn train | 7,000 | §3 |
| SParC / CoSQL train | train splits | §3 |
| MMSQL train | 6,493 dialogues | §3 |
| Six-Gym | 5,000 per dialect | §4 |
| NL2SQL-Bugs | 2,018 | §5 |
| DAComp-DE gold, ELT-Bench ground truth | pipeline formats | §5 |

### Inferences
- **Spider 2.0's** "test-only" status and its maintainers' advice cover the Spider 2.0-derived public sets too (AIFunc, Genies, nl2sqlproj), whatever licenses those carry.
- **AMBROSIA** can be used for training under its CC BY 4.0 license, but keep it local and do not redistribute it.
- **LiveSQLBench:** if it is reserved as the held-out set, it should not also be used for training, even though no term forbids it.

### Gaps
- No explicit statement found from BIRD-Interact or LiveSQLBench maintainers about fine-tuning on their gold once it is obtained by email.

---

## 10. How likely is it that pretrained Qwen-family models have seen each dataset?

### Takeaway
- **No published study measures memorization of text-to-SQL benchmarks by any Qwen model.** The ratings below are inferences from:
  - how long and how widely each dataset has been public;
  - its use in Qwen-based training mixtures;
  - measurements on other models;
  - one measurement showing Qwen2.5-Math memorized MATH-500 despite Qwen's stated decontamination.
- **The Spider 2.0-Lite local split itself is exposed:**
  - its schemas are classic public sample DBs;
  - its question text is on GitHub;
  - full agent rollouts on all 135 questions have been on HF since 2026-02-16. Qwen3.5-9B's repo was created 11 days later and Qwen3.6-35B-A3B's two months later.

### Cited Findings

**What Qwen discloses**
- **Qwen2.5-Coder** ([report](https://arxiv.org/html/2409.12186)):
  - Text-to-SQL ability comes from "finely crafted synthetic data during both pre-training and fine-tuning", evaluated on Spider and BIRD.
  - The 10-gram decontamination list names only "HumanEval, MBPP, GSM8K, and MATH".
- **Qwen2.5** decontaminates by LCS ≥ 13 tokens and never mentions SQL ([report](https://arxiv.org/html/2412.15115)).
- **Qwen3** (36T tokens) does not mention SQL, Spider or BIRD, and has no decontamination section ([report](https://arxiv.org/html/2505.09388)).
- **Qwen3-Coder-Next** reports Spider and BIRD scores; its decontamination is described only for pull-request data ([report](https://arxiv.org/html/2603.00729)).
- **Qwen3.5 / Qwen3.6:** no technical report found. The model cards list no SQL benchmarks and give no data cutoff ([Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B), [Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)).
- HF API creation dates (our check): Qwen3.5-9B 2026-02-27, Qwen3.6-35B-A3B 2026-04-15.
- Qwen's training-data summary page says data includes public web data, third-party non-public data and Qwen-generated synthetic data ([qwen.ai](https://qwen.ai/training-data-summary)).

**Qwen-based text-to-SQL models and their training data**

| Model | Training data | Source |
|---|---|---|
| OmniSQL (Qwen2.5-Coder) | SynSQL + Spider train + BIRD train | [paper](https://arxiv.org/html/2503.02240) |
| SQL-R1 | SynSQL subsets | [paper](https://arxiv.org/html/2504.08600) |
| Arctic-Text2SQL-R1 | BIRD 8,017, Spider train 6,972, Spider **dev** 985, Gretel 11,811 | [paper](https://arxiv.org/html/2505.20315) |
| Reasoning-SQL | BIRD train 8,026 | [paper](https://arxiv.org/html/2503.23157) |
| ROUTE | Spider + BIRD train | [paper](https://arxiv.org/html/2412.10138) |
| BIRD-Fixer and BIRD-Talon / Zeno | Six-Gym | §4 |
| ReViSQL (Qwen3-235B) | BIRD-Platinum | [arXiv](https://arxiv.org/abs/2603.20004) |
| XiYan-SQL | Not disclosed | [paper](https://arxiv.org/html/2411.08599) |

- Public mixtures:
  - NSText2SQL includes Spider, SEDE, KaggleDBQA, EHRSQL and MIMICSQL ([card](https://huggingface.co/datasets/NumbersStation/NSText2SQL)).
  - sql-create-context is built from WikiSQL and Spider ([card](https://huggingface.co/datasets/b-mc2/sql-create-context)).
- HF models that tag each dataset, and how many of those are Qwen-related (sub-researcher count): Gretel 171 / 44; xlangai/spider 39 / 25; SynSQL 15 / 10.
- **Claimed, not measured:** the OmniSQL authors conjecture that Qwen2.5-Coder "incorporated the training sets of … Spider and BIRD" ([paper](https://arxiv.org/html/2503.02240)).

**Measured contamination evidence (all on non-Qwen models, except the math study)**
- **Ranaldi et al. 2024, gpt-3.5-turbo** ([paper](https://arxiv.org/abs/2402.08100)):
  - Masked-column reconstruction: 33.42 on Spider dev DBs vs 13.21 on Termite.
  - Test-suite accuracy, Hard: 48.83 vs 28.33.
  - Termite's released data is Italian (our check), which confounds the comparison.
- **Li & Flanigan 2024:** older models generate exact Spider train/dev examples, more so for newer models; the count correlates with Spider-dev accuracy (R=0.88) ([paper](https://arxiv.org/abs/2312.16337)).
- **SPENCE (2026):** accuracy falls as paraphrases drift from the original wording. Kendall τ: Spider −0.89, SParC −0.76, CoSQL −0.71, BIRD −0.35 (confidence intervals mostly span 0). Models: GPT-OSS, Llama, GPT-4o-mini, o3-mini ([paper](https://arxiv.org/abs/2604.17771)).
- **Wu et al. 2025:** given 60% of a MATH-500 problem, Qwen2.5-Math-7B reproduces the rest exactly 54.6% of the time; Llama3.1-8B does so 3.8% of the time ([paper](https://arxiv.org/abs/2507.10532)).

**Release dates of benchmarks in our scope**
- BIRD (May 2023), Spider (2018), Gretel (Mar 2024) and SynSQL (Mar 2025) have all been public on GitHub or HF for a long time.
- LiveSQLBench releases run from 2025-05-30 to 2026-03-02; BIRD-Interact from 2025-06; BEAVER v3 from 2026-05; ARCS from 2026-10-06 (§§4–5).

### Inferences
**Risk ratings** (all inference; "exposure" means the model has likely seen the questions or gold, not that it scores higher because of it)

| Dataset | Risk | Why |
|---|---|---|
| Spider 1.0 (all splits), SParC/CoSQL train+dev, Spider-Syn, AmbiQT, Dr.Spider, Spider-DK, Spider-Realistic | **High** | Spider-derived, public since 2018–2023, in many mixtures, measured contamination on other models |
| BIRD train | **High** | In OmniSQL, Arctic, Reasoning-SQL and ROUTE |
| BIRD dev / Mini-Dev (original) | **High** | Public since 2023, Qwen's own evaluation harness, Arctic trained on Spider dev, though not on BIRD dev |
| BIRD dev 1106 / Mini-Dev 1024 | **Medium** | Revised SQL and questions from 2025-11 and 2026-10 |
| BIRD test | **Low** | Never public |
| SynSQL | **High** | In OmniSQL and SQL-R1; partly generated by Qwen2.5 |
| Gretel | **High** | Arctic plus 44 Qwen-related community fine-tunes |
| SEDE, KaggleDBQA, EHRSQL, MIMICSQL | **High** | In NSText2SQL since 2023 |
| Archer train/dev | **Medium** | Public 2024; its DBs are Spider DBs |
| Archer blind test, BookSQL test | **Low** | Hidden |
| BEAVER v3 public | **Low–Medium** | Released May 2026, after both Qwen models in use |
| BEAVER private test | **Low** | Hidden |
| AMBROSIA | **Low–Medium** | Password-protected, but a full copy is on GitHub and a Qwen3-4B was fine-tuned on it |
| PRACTIQ | **Low** | Not released |
| BIRD-Interact, LiveSQLBench | **Low** | Gold withheld; Large-v1 released 2026-03-02, near the Qwen3.6 date |
| BIRD-Critic | **Medium** | Its StackOverflow sources are public; gold withheld |
| Six-Gym | **Medium** | Public gold since 2025, Qwen2-architecture models trained on it |
| NL2SQL-Bugs | **Medium** | GitHub since March 2025 |
| ARCS | **Low** | October 2026 |
| EntSQL | **Low**, with a caveat | No gold; Qwen-team co-authors |
| DA-Code | **Medium** | Public since October 2024 |
| TPC-H/DS | **High** | Decades old |
| Termite | **Low** | |
| **Spider 2.0-Lite local** (the evaluation set) | **Medium–High** | Classic schemas everywhere, question text on GitHub, Genies rollouts with solved flags since 2026-02-16 |

- **What exposure means for the judge:** it matters less for *training* data than for *evaluation* data. The real hazard is a judge or agent that has seen Spider 2.0-Lite-specific artifacts. A cheap direct check: run Wu et al.'s partial-question completion and Ranaldi's masked-column probe on Qwen3.5-9B and Qwen3.6-35B-A3B, with LiveSQLBench Large-v1 or ARCS as the post-cutoff control.

### Gaps
- No Qwen3.5 or Qwen3.6 technical report, data cutoff or decontamination list was found.
- No membership test for The Stack or Qwen's corpora was possible.
- Whether the Genies rollouts entered any Qwen corpus is unknown. The dates make Qwen3.5 exposure unlikely; that is an inference.

---

## 11. Ranked shortlists

### Takeaway
1. **(a) Judge training.** Build labelled candidate pools mainly from:
   - cleaned BIRD train, minus the overlapping DBs;
   - BEAVER v3 public;
   - Six-Gym, minus chinook, movie_3 and airline;
   - NL2SQL-Bugs, minus formula_1 and european_football_2.

   Add SynSQL Complex or Highly Complex items only if their DBs are re-populated.
2. **(b) Non-Spider2 dev/test.** Tune and validate the judge on:
   - LiveSQLBench (Base-Lite-SQLite, plus Full-v1 / Large-v1 if PostgreSQL is available) and BIRD Mini-Interact;
   - cleaned BIRD dev 1106 minus formula_1 and european_football_2;
   - ARCS, NL2SQL-Bugs and FLEX as targeted checks of judge behaviour.

### Cited Findings
Supporting facts, with sources in the sections cited.
- Counts after removing overlapping DBs (our arithmetic from the counts in §1 and §5):

  | Set | Before | After | What was removed |
  |---|---|---|---|
  | BIRD train | 9,428 | 7,998 | 1,430 rows: movie_3 325, works_cycles 474, soccer_2016 258, retail_world 373 |
  | BIRD train, also without legislator | 9,428 | 7,821 | the above + legislator 177 |
  | bird23-train-filtered | 6,601 | 5,767 | the four DBs (5,639 if legislator is also dropped) |
  | BIRD dev 1106 | 1,534 | 1,231 | formula_1 174, european_football_2 129 |
  | Mini-Dev 1024 | 500 | 414 | formula_1 55, european_football_2 31 |
  | Six-Gym SQLite / PG | 5,000 / 5,000 | 3,821 / 3,747 | chinook, movie_3, airline |
  | NL2SQL-Bugs | 2,018 | 1,578 | formula_1, european_football_2 |
  | BIRD-Critic SQLite / PG / Open / Flash | 500 / 530 / 600 / 200 | 387 / 412 / 470 / 146 | formula_1, european_football_2 |
  | Spider train_spider | 7,000 | 6,546 | 454 questions on the six DBs |

- Label noise to plan around:
  - BIRD train raw gold at least 52.1% wrong in a 2.5k sample.
  - BIRD-Platinum 2,088 / 374 cleaned.
  - bird23-train-filtered only removes rows.
  - Six-Gym has no human verification.
  - NL2SQL-Bugs labels are execution matches against a cleaned gold.
  - LiveSQLBench changelog: at least 2.8% of Full-v1 revised.
  - BIRD dev 1106: 16.5% of gold results changed from the earlier version.
  - SynSQL: 86% fully correct in a 1,000-sample human check; previews at most 3 rows per table.
- Relevance to the judge's failure modes:
  - ARCS conventions on names vs IDs and ties.
  - EHRSQL's 1,840 tie-breaking fixes.
  - Pourreza & Rafiei: 18–23% of Spider and BIRD queries are tie-prone.
  - NL2SQL-Bugs negatives: attribute and value mismatch, table redundancy, join-condition mismatch, DISTINCT (a proxy for fan-out).
  - AMBROSIA's scope and attachment ambiguities.

### Inferences

**(a) For judge training** (ranked; run the agent on these questions, sample 4 answers, label by execution against gold, keep pools with mixed correct and incorrect candidates)
1. **BIRD train, cleaned and de-overlapped.** BIRD-Platinum (2,088) for high-precision labels, plus bird23-train-filtered minus the overlapping DBs (about 5.6–5.8k) for volume.
   - Why: real data gives informative previews; the evidence field mirrors the judge's external-knowledge input; SQLite matches the harness; about 64 DBs.
   - Risks: short SQL; residual gold noise. Re-check each pool's "correct" label with a second signal, e.g. agreement with a stronger model, before training on 1-of-4 cases.
2. **BEAVER v3 public (7,978, MySQL).** The only public, gold-bearing source with Spider2-scale SQL (316.7 tokens, CTE-heavy) over large enterprise schemas.
   - Risks: needs a MySQL harness; 97% synthetic recomposition; only 3 public DB groups.
3. **Six-Gym (3,821 SQLite after filtering).** Buggy versus fixed SQL gives hard near-miss negatives.
   - Risk: LLM-generated with no human check, so audit a sample.
4. **NL2SQL-Bugs (1,578 after filtering).** Already shaped like judge data (labelled correct and incorrect candidates with an error taxonomy).
   - Risks: small; built on BIRD dev, so BIRD dev cannot then serve as a clean evaluation set for the same judge.
5. **SynSQL-2.5M, Complex and Highly Complex tiers.** Volume and CTE or window diversity.
   - Only after populating the DBs, e.g. with LLM-generated rows. Otherwise use only for SQL-text pre-training.
   - Watch the Llama-3.1 naming clause.
6. **EHRSQL v1.5.x and EHRSQL-2024.** Real clinical data, nested temporal SQL, many tie cases.
   - Risks: few templates, domain shift. Run locally per PhysioNet guidance.
7. **AMBROSIA (authors' training re-split).** For "two defensible readings" cases. Tiny DBs; do not redistribute.
8. **Spider train / Spider-Syn / SParC / CoSQL / AmbiQT train, minus the six DBs.** Easy volume only. Low value for this judge.
9. **Archer train/dev minus soccer_1 and formula_1; ScienceBenchmark synthetic (PostgreSQL; 75–83% agreement; license unknown).**

**Do not use:**
- Spider 2.0-derived sets: Lite, Snow, DBT, AIFunc, the Genies rollouts, nl2sqlproj/spider2-nl2sql, the multilingual copies.
- DA-Code.
- ELT-Bench pipelines on the six overlapping BIRD DBs.
- Gretel: one-table contexts; 22% fail in SQLite.
- SEDE (no DB) and MIMICSQL (template leakage; credentialed).
- BookSQL (non-commercial, no redistribution).
- Termite, SQLStorm, DABStep, KramaBench and DAComp-DA (no NL→gold-SQL pairs, or not SQL).

**(b) For a non-Spider2 dev/test set** (ranked; aim for pools where the agent is often right only 1 time in 4)
1. **LiveSQLBench Base-Lite-SQLite (270) plus BIRD Mini-Interact (300, SQLite).** The closest analogue (about 360-token SQL, knowledge-base documents, business domains), no overlap, gold gated, low exposure.
   - Request gold by email.
   - Pin the release.
   - Check whether Mini-Interact reuses Base-Lite's DBs before treating them as independent.
2. **LiveSQLBench Base-Full-v1 (600) and Large-v1 (480)** if the harness can run PostgreSQL. Large-v1, released 2026-03-02, is the most likely to post-date Qwen data.
3. **BIRD dev 1106 minus formula_1 and european_football_2 (1,231).** Large, well understood, cleaned by the BIRD team. Mini-Dev 1024 minus the overlapping DBs (414) is the harder slice.
   - Exposure is high.
   - Do not use it if NL2SQL-Bugs or BIRD-Critic were used in training.
4. **ARCS (101 questions / 413 golds; Oct 2026).** A targeted test of the tie and name-vs-ID conventions with multiple golds. Small.
5. **NL2SQL-Bugs (1,578) and FLEX (200)** as direct pairwise-accuracy checks, if not used for training.
6. **A DB-disjoint slice of BEAVER v3 public** (e.g., nova + neutron, 2,070), if BEAVER's dw split is used for training.
7. **AMBROSIA test (3,819 rows)** as an ambiguity stress test.
8. **KaggleDBQA test (185) minus TheHistoryofBaseball items.**
9. **EntSQL**, if gold is released (the best stylistic match; Qwen-team caveat).

**Reporting:**
- Keep the Spider 2.0-Lite 135 as the final test only.
- Report judge accuracy on the 43–49 overlapping local questions separately from the rest.
- Stratify all results by the number of correct candidates in the pool (1, 2 or 3 of 4), the regime where the judge fails.

### Gaps
- No measured agent success rates for this agent on LiveSQLBench, BEAVER or BIRD, so it is unknown which set yields the most 1-of-4 pools. A small pilot of about 100 questions per set would settle this before committing GPU time.
- Whether LiveSQLBench's gold-by-email terms allow building a tuning set from it was not confirmed with the maintainers.
- The cost of re-populating SynSQL DBs was not estimated.
