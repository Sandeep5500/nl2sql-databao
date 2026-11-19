# Published audits of Spider 2.0 gold labels, and public mentions of 13 Spider 2.0-Lite BigQuery instances

Scope: Spider 2.0-Lite and Spider 2.0-Snow gold answers. Instances checked: bq045, bq397, bq151, bq308, bq002, bq035, bq051, bq055, bq208, ga010, bq424, bq389, bq356 (Snow twins: sf_bq045 ... sf_ga010 ...). Research date: 2026-11-18. Read-only web and repository research. No SQL was run against any cloud service. No credential files were opened.

How to read the sources: "Verified in full text" means the paper's PDF or HTML was read. "Search summary only" means the claim comes from a search-result summary and the full text was not read. Facts about the official Spider2 repository were checked two ways. The issue tracker was pulled through the GitHub API on 2026-11-18 (213 issues, 20 PRs, 345 comments). File history was read from the project's local clone of `xlang-ai/Spider2` at commit `01a4c67` (2026-01-30). Upstream `main` may have changed since then.

## Q1. The UIUC study "Pervasive Annotation Errors Break Text-to-SQL Benchmarks and Leaderboards": details, and whether it covers our ids

### Takeaway
The study is real and peer-reviewed. Authors: Tengjun Jin, Yoojin Choi, Yuxuan Zhu and Daniel Kang (UIUC). It appears in PVLDB 19(5): 931–944, 2026 (arXiv 2601.08778, January 2026). An earlier CIDR 2026 version has a different title. On Spider 2.0-Snow it audited only the 121 examples whose gold SQL was public as of the 2025-08-20 snapshot, and found errors in 76 of them (62.8%). It did not re-score the Snow leaderboard. It released no per-instance verdict list for Snow, only named examples. **None of our 13 ids, and none of their sf_ twins, is among the 121 audited examples**, so the study says nothing about them, either for or against.

### Cited Findings
**Bibliographic facts**
- The archival version is: Tengjun Jin, Yoojin Choi, Yuxuan Zhu, Daniel Kang, "Pervasive Annotation Errors Break Text-to-SQL Benchmarks and Leaderboards", *PVLDB* 19(5): 931–944, 2026, doi:10.14778/3796195.3796206. All four authors are at University of Illinois (UIUC). Artifacts: https://github.com/uiuc-kang-lab/text_to_sql_benchmarks — [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf)
- arXiv 2601.08778 (cs.AI, cross-listed cs.DB) has three versions: v1 on 13 Jan 2026, v2 on 14 Jan 2026, v3 on 19 Jan 2026. The comments field reads "18 pages, 14 figures, 9 tables." — [arXiv abstract page](https://arxiv.org/abs/2601.08778)
- The repo README calls the paper "Accepted to VLDB 2026" — [GitHub repo](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks)
- An earlier, shorter version appeared at CIDR 2026 (Jan 18–21, 2026, Chaminade) as "Text-to-SQL Benchmarks are Broken: An In-Depth Analysis of Annotation Errors", by the same authors — [CIDR PDF](https://vldb.org/cidrdb/papers/2026/p5-jin.pdf); [CIDR page](https://vldb.org/cidrdb/2026/text-to-sql-benchmarks-are-broken-an-in-depth-analysis-of-annotation-errors.html)
- The CIDR version reports "error rates of 52.8% and 66.1%" for BIRD Mini-Dev and Spider 2.0-Snow. It re-evaluated five BIRD agents and found changes of "−3% to 31% in relative terms" and rank changes "of up to three positions" — [CIDR PDF](https://vldb.org/cidrdb/papers/2026/p5-jin.pdf)

**Scope and snapshot**
- Quote: "Spider 2.0-Snow contains a total of 547 examples, with gold queries publicly available for 121 of them. Therefore, we evaluated the correctness of these 121 examples." — [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf)
- They chose Snow over Lite "because teams at leading technology companies benchmark their agents on it rather than on Spider 2.0-lite." — [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf)
- Snapshot quote: "The Spider 2.0 gold queries were updated on Oct. 29, 2025. Since our evaluation was conducted before that, we used the annotations as of Aug. 20, 2025". This points to Spider2 commit `84911f375c87903c73ed5fe93769b593a14efb42`. — [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf)
- SAR-Agent was given only the gold tables, because Snow schemas are large (an average of 812.1 columns per database) — [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf)

**How an annotation was judged wrong**
- The paper describes a three-stage audit. Quote: "(1) SAR-Agent producing per-annotation diagnostic reports; (2) human SQL experts adjudicating all agent-flagged cases, verifying the stated error reasons and assigning final correctness labels; and (3) human SQL experts extending manual review to additional examples based on the recurring error patterns." — [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf)
- SAR-Agent ran on OpenAI o3 with up to 30 iterations. During verification, the experts ran their own check queries (subqueries, or queries modified to test each stated error reason) against the database. Disagreements were settled in a discussion among all four authors — [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf); [arXiv HTML v3](https://arxiv.org/html/2601.08778v3)
- Definition used: "We consider an example to be incorrect if it exhibits any of E1 - E4." The four classes are:
  - E1: the question's meaning does not match the logic of the gold SQL.
  - E2: mismatch with the data or schema.
  - E3: wrong domain knowledge.
  - E4: ambiguity.

  So ambiguous questions count as errors even when the gold SQL is one reasonable reading — [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf)
- SAR-Agent precision after human checking was 83% on BIRD Mini-Dev (228 of 274 flagged) and 89% on Spider 2.0-Snow (70 of 79 flagged) — [arXiv HTML v3](https://arxiv.org/html/2601.08778v3); [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf)

**Error rates and categories**
- Snow quote: "For Spider 2.0-Snow, we find annotation errors in 76 of 121 examples, resulting in an error rate of 62.8%." For BIRD Mini-Dev the count is 263 of 498 (52.8%) — [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf)
- The four classes overlap, so the shares sum to more than 100%. Shares are of the erroneous examples. Snow (76 erroneous) — [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf):
  - E1: 37 (48.68%)
  - E2: 44 (57.89%)
  - E3: 9 (11.84%)
  - E4: 18 (23.68%)
- BIRD Mini-Dev (263 erroneous), same table — [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf):
  - E1: 77 (29.28%)
  - E2: 152 (57.79%)
  - E3: 28 (10.65%)
  - E4: 78 (29.66%)
- **Why 66.1% and 62.8% differ.** On July 13, 2025 the Spider 2.0 team rewrote questions "to resolve ambiguity". This touched 71 of the 121 examples and lowered the error rate from 66.1% to 62.8%, but "introduces additional errors in 6 examples". The appendix example is sf_local015: the rewrite added a fatalities-per-collision formula that conflicts with the word "percentage" in the question, and the gold SQL multiplies by 100. The authors conclude that updating questions alone does not fix gold errors — [arXiv HTML v3](https://arxiv.org/html/2601.08778v3); [supplementary material](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks/blob/main/materials/supplementary_material.pdf)
- **Snow instances the paper names.** None is one of ours.
  - sf_bq291 (E1): ST_POINT gets longitude and latitude swapped.
  - sf_bq263, sf_bq271, sf_bq273, sf_bq294 (E1): `TO_TIMESTAMP(end_date)` cuts off the last day of the date range.
  - sf_bq050, sf_bq209, sf_bq455 (E1): a filter the question asks for is missing. For sf_bq209 the gold drops "utility patent".
  - sf_bq099, sf_bq248, sf_bq422, sf_local263 (E2): a join or flatten inflates counts.
  - sf_bq052, sf_bq246 (E3): forward citations are miscounted.
  - sf_bq017, sf_bq068, sf_bq099, sf_bq182, sf_bq193, sf_bq222, sf_bq223 (E4): the gold applies a quote-mark output format the question never asks for.
  - sf_bq128: cited as a correct example.
  - The CIDR version also names sf_bq012 and sf_local355.

  Sources: [arXiv HTML v3](https://arxiv.org/html/2601.08778v3); [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf); [CIDR PDF](https://vldb.org/cidrdb/papers/2026/p5-jin.pdf)

**Leaderboard re-scoring**
- BIRD only. The authors sampled 100 of the 1,534 BIRD Dev examples and corrected 48 of them ("We corrected a total of 48 text-to-SQL examples"). They then re-scored all 16 open-source BIRD leaderboard agents.
  - Relative execution-accuracy changes ranged from −7% to 31%, and ranks moved by −9 to +9.
  - CHESS rose from 62% to 81% (+30.6% relative), from 7th to a tie for 1st with GenaSQL.
  - Contextual-SQL fell from 1st to 7th, and MAC-SQL from 4th to 13th.
  - Spearman correlations: rankings on the original subset correlate strongly with the full Dev set (r_s = 0.85, p = 3.26e-5), "whereas they correlate weakly with those on the corrected subset (r_s = 0.32, p = 0.23)".

  Sources: [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf); [Kang Substack](https://ddkang.substack.com/p/pervasive-annotation-errors-break)
- No Spider 2.0-Snow leaderboard re-scoring is reported — [arXiv HTML v3](https://arxiv.org/html/2601.08778v3)

**What was released**
- The repo (CC-BY-SA-4.0) contains:
  - SAR-Agent code, including `sql_verifier_sf.py` for Snow, with an `--old_sf` flag for the 0713 question set.
  - Copies of the 121 public Snow gold SQLs and their gold schemas under `SAR-Agent/spider2/`.
  - The 16 agents' BIRD outputs.
  - Two corrected BIRD Mini-Dev files, Arcwise-Plat-SQL (`data/arcwise_plat_sql_only_with_diff.json`) and Arcwise-Plat (`data/arcwise_plat_full_with_diff.json`), released 2026-02-21.
  - The original and corrected 100-example BIRD Dev subsets, on Google Drive.

  Sources: [GitHub repo](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks)
- No per-instance Snow verdict file was found. I listed all 1,787 paths in the repo through the GitHub API, and none holds Snow verdicts or corrected Snow answers. The paper gives example ids by category, not a full list — [repo tree](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks); [arXiv HTML v3](https://arxiv.org/html/2601.08778v3)

**Our ids**
- The 121 audited Snow instances are the files in [`SAR-Agent/spider2/sql/`](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks/tree/main/SAR-Agent/spider2/sql): sf001–sf044 (8), sf_bq012 ... sf_bq455 (76), sf_ga001, and sf_local003 ... sf_local360 (36).
- None of sf_bq045, sf_bq397, sf_bq151, sf_bq308, sf_bq002, sf_bq035, sf_bq051, sf_bq055, sf_bq208, sf_ga010, sf_bq424, sf_bq389 or sf_bq356 is in that set. I checked by matching ids against the GitHub API tree.
- None of these ids appears in the PVLDB, CIDR or arXiv texts, the supplementary PDF, or the authors' Substack post.

  Sources: [repo tree](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks); [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf); [Substack](https://ddkang.substack.com/p/pervasive-annotation-errors-break)

### Inferences
- Our 13 ids were out of the study's scope, because their Snow gold SQL was not public on 2025-08-20. Their absence from the error list is therefore not evidence that their gold answers are correct.
- The 62.8% rate is not a random-sample estimate for Spider 2.0. It applies to the public-gold Snow subset and counts ambiguity (E4) as an error. Using it as a prior for Lite BigQuery tasks is reasonable only as a rough guide.
- The official log says Lite and Snow are "updated simultaneously". The UIUC findings on audited sf_bq ids (for example sf_bq291 and sf_bq263) therefore probably carry over to their Lite twins. That does not reach our ids.

### Gaps
- No per-instance verdicts were released for the 45 audited Snow examples judged correct or for every one of the 76 judged wrong. Only examples are named.
- The CIDR 2026 slides ([Kang-16.pdf](https://www.cidrdb.org/cidr2026/slides/Kang-16.pdf)) turned up in search but were not opened.

## Q2. Other papers, preprints and technical reports (2024–2026) that blame some Spider 2.0 failures on wrong gold answers or ambiguous questions

### Takeaway
Only a few sources go beyond the UIUC study, and all of them concern Snow:
- Emergence AI's Spider2-E analysis (May 2026) blames 28 of its 32 failed Snow instances on the benchmark itself, and releases a patched Snow variant.
- Spider 2.0-AIFunc (July 2026, partly written by the Spider 2.0 team) finds annotation issues in 7 of 30 tasks that all strong models fail, without naming ids.
- The original Spider 2.0 paper reports its own 45% → 5% validation error rates.
- No ReFoRCE or Spider-Agent error analysis attributing failures to gold labels was found.

No source audits the Spider 2.0-Lite BigQuery split, and none names any of our 13 ids.

### Cited Findings
**Spider 2.0 paper** (Lei, Chen, Ye, Cao, Shin, Su, Suo, Gao, Hu, Yin, Zhong, Xiong, Sun, Liu, Wang, Yu; arXiv 2411.07763 v2, 17 Mar 2025; ICLR 2025)
- "Eight authors majoring in computer science, all highly proficient in SQL, carry out the data annotation process."
- "each instruction, the gold SQL query, and evaluation script are reviewed by at least three annotators."
- "45% of the examples have errors identified by the first validators." After a second round, "only 5% of the examples contain errors."
- "Multiple potential gold answers are supported."
- The paper's own failure analysis blames the models, not the labels: erroneous data analysis 35.5%, wrong schema linking 27.6%, JOIN errors 8.3%.

Sources: [arXiv HTML v2](https://arxiv.org/html/2411.07763v2); [ICLR proceedings PDF](https://proceedings.iclr.cc/paper_files/paper/2025/file/46c10f6c8ea5aa6f267bcdabcb123f97-Paper-Conference.pdf)

**Spider 2.0-AIFunc** (Tianyang Liu, Canwen Xu, Fangyu Lei, Nikki Lijing Kuang, Jixuan Chen, Tao Yu, Julian McAuley, Zhewei Yao, Yuxiong He; arXiv 2607.06229, submitted 7 Jul 2026)
- The benchmark rewrites Spider2-Snow tasks.
- Section 4.4 is a manual error analysis of 85 randomly sampled instances. Quote: "7 of the 30 S1 instances (23%) show signs of annotation issues (C5)." S1 is the group of tasks that all three strong proprietary models failed.
- C5 covers cases where "the gold query encodes constraints not mentioned in the instruction" or where the task "admits multiple valid SQL queries that produce different but arguably correct results".
- No instance ids are named, and none of ours appears.
- Note: the 7 of 30 count was verified in the arXiv HTML. One third-party summary (Pith) restates it as "1.5% of total", using a different denominator.

Sources: [arXiv HTML](https://arxiv.org/html/2607.06229v1); [Pith summary](https://pith.science/paper/2607.06229)

**Emergence AI, "Spider2 Under the Microscope: Data Drift, Engine Gaps, and the Case for Spider2-E"** (Pralhad Deshpande, Ayan Bhowmick, Jeremy Hartman, Paul Haley; blog dated May 2026; repo created 2026-05-05)
- The authors manually analysed all 32 non-exact matches from their Snow run. Quote: "28 were caused by issues in the benchmark itself rather than query reasoning failures."
- Breakdown:
  - Data drift: 20
  - Engine differences between BigQuery and Snowflake: 5
  - Database unavailable: 3
  - Query logic errors (the system's fault): 4
- On annotation errors, the post cites Jin et al. instead of reporting its own audit.

Sources: [Emergence blog](https://www.emergence.ai/blog/spider2-under-the-microscope-data-drift-engine-gaps-and-the-case-for-spider2-e); [v3 of post](https://www.emergence.ai/blog/published-may-12-edit-share-spider2-under-the-microscope-data-drift-engine-gaps-and-the-case-for-spider2-e)

**Spider2-E** (patched Snow variant)
- Changes from upstream:
  - Instances: 547 → 524. The 23 removed are 20 drift cases and 3 with revoked data shares.
  - Gold SQL files: 120 → 118. sf_bq294 got a deterministic gold SQL in place of one using `CURRENT_DATE`.
  - Gold CSVs: 1,544 → 1,469.
  - 5 gold variants added for legitimate engine differences.
  - The evaluator was patched to reject SQL that hard-codes answer values, and to count an empty result against an empty gold as a match.
- Quote: "For every instance not listed in §1–§3, the upstream gold artifacts are kept verbatim."
- Named ids:
  - Drift: sf006, sf008, sf012, sf037, sf040, sf_bq009, sf_bq024, sf_bq058, sf_bq063, sf_bq102, sf_bq130, sf_bq165, sf_bq190, sf_bq249, sf_bq256, sf_bq275, sf_bq366, sf_ga014, sf_ga018, sf_ga021.
  - Engine differences: sf_bq111, sf_bq276, sf_bq430, sf_bq458, sf_local344.
  - Unavailable: sf009, sf013, sf029.

Sources: [Spider2-E README](https://github.com/EmergenceAI/Spider2-E); [Emergence blog](https://www.emergence.ai/blog/spider2-under-the-microscope-data-drift-engine-gaps-and-the-case-for-spider2-e)

**Not found**
- **ReFoRCE** (arXiv 2502.00675; Snowflake): searches found no error analysis that blames failures on wrong gold answers. The paper describes deferring and resolving ambiguous cases inside the agent. I did not read its full text. — [ReFoRCE arXiv](https://arxiv.org/html/2502.00675v3)
- **Spider-Agent or other leaderboard systems**: no published error analysis naming wrong-gold Spider 2.0 instances was found, beyond the sources above.

**Official maintainers' corrections** (these are not audits)
- The README news lists:
  - 2025-01-10: changes to evaluation examples are tracked in a public data update log.
  - 2025-07-13: `spider2-snow.jsonl` was updated "to resolve ambiguities". The old file was renamed `spider2-snow-0713.jsonl`.
  - 2025-10-29 "Major update!": "We fixed the evaluation-suite issue, so scores are now more accurate and stable."

  Source: [Spider2 README](https://github.com/xlang-ai/Spider2)
- The leaderboard site dates the same fix "2024-10-29", which looks like a typo. The repo commit that carries it is dated 2025-11-02 — [leaderboard](https://spider2-sql.github.io/); [commit 5fa8a517](https://github.com/xlang-ai/Spider2/commit/5fa8a517)
- The data update log says it records "updates to natural language questions, gold SQL, gold answers, and evaluation scripts". Quote: "Spider2-lite and Spider2-snow are updated simultaneously." Its last entry is 2025-08-06, so the Oct–Nov 2025 update is not in the log. Most entries list ids without saying what changed — [Data Update Log](https://docs.google.com/document/d/1a69mxO7m1nMndXp8H_-aggvYDbcbiS3rV9GPXEw-DeM/edit)

### Inferences
- Two published sources independently find that a large share of hard Snow failures come from the benchmark:
  - Emergence: 28 of 32 failures, mostly data drift, a different mechanism from wrong labels.
  - AIFunc: 7 of 30 tasks that every strong model fails.

  A set of BigQuery tasks that strong systems keep failing, like the 13, is therefore a plausible place to find label problems. This is an inference, not a finding about these ids.
- The Spider 2.0 team acknowledges multiple valid answers in two places: through added gold variants and through the AIFunc C5 class. This fits the user's suspicion that some failures on these ids come from under-specified questions.

### Gaps
- No public audit of Spider 2.0-Lite (BigQuery, GA or local) gold answers comparable to UIUC's Snow audit was found.
- GBV-SQL (arXiv [2509.12612](https://arxiv.org/pdf/2509.12612)) and NL2SQL-BUGs (arXiv [2503.11984](https://arxiv.org/pdf/2503.11984)) turned up in searches but were not read. Neither appeared to target Spider 2.0 gold labels.
- No theses or technical reports specific to Spider 2.0 label errors were found.

## Q3. Instance-level mentions of the 13 ids, and any corrected answers

### Takeaway
No published audit, paper, blog post or community repo names any of the 13 ids as having a wrong gold answer, and none offers a corrected answer.

The only public traces are three:
- The official maintainers changed all 13 in the 2025-10-29/11-02 evaluation update. That update mostly added alternative accepted gold CSVs and changed `condition_cols`/`ignore_order`; for bq002, bq051, bq055 and bq308 it also edited existing gold values.
- Eight of the 13 appear in the official data update log, with no stated reason.
- Two GitHub issues touch them. Issue #151 reports a real evaluation-config bug for **bq389**, and issue #98 mentions sf_bq002 only in passing.

### Cited Findings
- **UIUC audit**: none of the 13 (as sf_ twins) is among the 121 audited instances — [repo `SAR-Agent/spider2/sql/`](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks/tree/main/SAR-Agent/spider2/sql)
- **Spider2-E**: all 13 sf_ twins are kept. All 46 of their gold CSVs in Spider2-E are byte-identical to upstream `spider2-snow` gold, which I checked with `cmp` against the local clone at `01a4c67`. Spider2-E did not change any of them — [Spider2-E](https://github.com/EmergenceAI/Spider2-E)
- **Emergence blog and Spider 2.0-AIFunc**: neither mentions any of the 13 — [Emergence blog](https://www.emergence.ai/blog/spider2-under-the-microscope-data-drift-engine-gaps-and-the-case-for-spider2-e); [AIFunc](https://arxiv.org/html/2607.06229v1)
- **Spider2 GitHub issues**: I searched all 213 issues and 345 comments, pulled 2026-11-18. Only two issues match:
  - **#151** (open, 2025-11-02, "Inconsistent number of condition columns's variants"). Quote: "there are cases where a condition column has an index not given in the gold dataframe - e.g. 6 where the gold df has 4 columns: e.g. `bq389`." The only reply, on 2025-11-23, asks "Any news on that one?" No fix or corrected answer is given.
  - **#98** (open, 2025-06-12) asks why `sf_bq002_a.csv`/`sf_bq002_b.csv` exist. The maintainer account lfy79001 replied: "_a, _b — this is because there are multiple correct answers due to question ambiguity or data version issues." This is not an error report.

  Sources: [issue #151](https://github.com/xlang-ai/Spider2/issues/151); [issue #98](https://github.com/xlang-ai/Spider2/issues/98)
- **bq389 consequence** (my reading of the official code at commit `01a4c67`):
  - The eval config keeps a flat `"condition_cols": [1, 2, 3, 4, 5, 6]`.
  - Since Nov 2025 there are 7 gold variants:
    - `bq389_a`, `bq389_d`, `bq389_e`: 7 columns × 12 rows (wide format).
    - `bq389_b`: 4 columns × 72 rows (long format).
    - `bq389_c`, `bq389_f`, `bq389_g`: 3 columns × 72 rows (long format).
  - `compare_multi_pandas_table` in `spider2-lite/evaluation_suite/evaluate.py` copies the flat list to every variant and checks the variants in sorted order. On `bq389_b`, `gold.iloc[:, [1..6]]` raises an out-of-bounds IndexError, and the instance-level `try/except` turns that into a score of 0.
  - Result: under the official scorer only predictions that match variant `a` can score. Variants b–g, including the wide d and e, are never reached.

  Sources: [evaluate.py](https://github.com/xlang-ai/Spider2/blob/main/spider2-lite/evaluation_suite/evaluate.py); [spider2lite_eval.jsonl](https://github.com/xlang-ai/Spider2/blob/main/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl); [issue #151](https://github.com/xlang-ai/Spider2/issues/151)
- **Official data update log**: entries for our ids, with no per-id explanation unless noted:

  | Id | Log entries |
  |---|---|
  | bq002 | 2025-01-23, 2025-02-10 |
  | bq045 | 2025-01-28, 2025-02-10 |
  | bq397 | 2025-01-28, 2025-02-10 |
  | bq051 | 2025-01-28, 2025-02-10 |
  | bq208 | 2025-01-10 (geospatial external document added), 2025-01-28 |
  | bq356 | 2025-02-10 |
  | bq055 | 2025-02-10; 2025-05-21 "update eval config" |
  | bq035 | 2025-05-21 "update question" |
  | bq151, bq308, ga010, bq424, bq389 | none |

  Source: [Data Update Log](https://docs.google.com/document/d/1a69mxO7m1nMndXp8H_-aggvYDbcbiS3rV9GPXEw-DeM/edit)
- **Official evaluation update of 2025-11-02** (commit `5fa8a517`, "update spider2lite eval", 1,946 files; part of the "2025-10-29 Major update"). What changed for each id:

  | Id | Gold CSV change | Eval config change |
  |---|---|---|
  | bq045 | 1 → 4 variants | `condition_cols` [] → [[1],[2],[0],[1]] |
  | bq397 | 1 → 4 | [] → [2] |
  | bq151 | 1 → 3 | `ignore_order` false → true |
  | bq308 | a and b edited; c and d added | [1,2,3] → [[1,2,3],[2,3,4],[1,2,3],[2,3,4]] |
  | bq002 | a and b edited; c added | [] → [[1,2,3],[1,2,3],[0]] |
  | bq035 | 1 → 2 | [0,2] → [[1],[1,2]] |
  | bq051 | single CSV edited (3 lines) | [0] → [1] |
  | bq055 | a and b edited; c–f added | [1] → six per-variant lists; `ignore_order` → true |
  | bq208 | 1 → 2 | [] → [[4],[3]]; `ignore_order` → true |
  | ga010 | 1 → 4 | `ignore_order` → true |
  | bq424 | 1 → 4 | [0] → [[2],[3],[1],[1]]; `ignore_order` → true |
  | bq389 | 1 → 7 | `condition_cols` unchanged |
  | bq356 | 1 → 2 | `ignore_order` → true |

  Separately, commit `d79b85e9` (2025-05-22, "update lite eval bq022 bq034 bq055 bq169 bq278 bq293 bq308 bq396 bq432") touched bq055 and bq308.

  Sources: [commit 5fa8a517](https://github.com/xlang-ai/Spider2/commit/5fa8a517); [commit d79b85e9](https://github.com/xlang-ai/Spider2/commit/d79b85e9)
- **Public gold SQL in Lite.** As of the local clone (`01a4c67`), Lite gold SQL is public for 9 of the 13: bq045, bq397, bq151, bq308, bq002, bq035, ga010, bq424, bq389. It is not public for bq051, bq055, bq208 or bq356.
  - Overall, 256 Lite gold SQL files are public: 134 of the 180 `bq` tasks, 14 of the 25 `ga` tasks, 24 `local` tasks, and 84 `sf*` tasks.
  - Upstream Snow has 120 gold SQL files.

  Source: [Lite gold SQL folder](https://github.com/xlang-ai/Spider2/tree/main/spider2-lite/evaluation_suite/gold/sql)

### Inferences
- **Where a correction exists, it is the maintainers' own.** The Nov 2025 update widened the accepted answers for all 13 ids. Any analysis of these ids should use the post-Nov-2025 gold. Pre-update traces may have been scored against a single, narrower gold.
- **bq389's failure may be partly a scorer artifact.** A long-format or 3–4-column answer cannot score under the official evaluator, even though the maintainers added such variants. The project's own `nl2sql/eval.py` port should be checked for the same behaviour, since it may or may not raise on out-of-range indices.
- **The 9 ids with public Lite gold SQL can be audited the UIUC way.** That means comparing gold SQL to the question with check queries. A finding of "gold wrong" for any of these 13 would be new; no prior public report exists to cite.

### Gaps
- The update log does not say what changed for the batched ids (2025-01-23, 01-28, 02-10), so the reasons for those edits are unknown.
- The Nov 2025 commit carries no per-instance rationale.
- I did not diff the old and new gold values for bq002, bq051, bq055 and bq308. That diff is in commit `5fa8a517` if the content is needed.

## Q4. Blog posts, leaderboard notes, issue-tracker and social-media discussion of wrong gold answers (Lite BigQuery focus)

### Takeaway
Public discussion lives almost entirely in four places: the official GitHub issue tracker (at least 40 issues report wrong or ambiguous gold), the UIUC authors' Substack post, the Emergence AI blog, and a few community repos. Searches found no Reddit, X/Twitter or Hacker News threads. The few Lite BigQuery reports (bq363, bq383, bq275, ga008, bq023, bq011, bq066, bq389) do not include any of our ids except bq389, and only for its evaluation config.

### Cited Findings
- **Daniel Kang's Substack post** (dated July 27, 2026 on the page):
  - Restates 52.8% for BIRD Mini-Dev and 62.8% for Snow (2025-08-20 cutoff), and the BIRD re-ranking: Contextual-SQL from 1st to 7th; CHESS and GenaSQL to a tie for 1st at 81%.
  - Advises "don't blindly trust benchmark scores or leaderboards!"
  - Names no instances and reports no Spider 2.0 team response.

  Source: [Substack](https://ddkang.substack.com/p/pervasive-annotation-errors-break)
- **Leaderboard site**:
  - Says the authors "continually check the accuracy of the evaluation metrics" and that scores "may change slightly over time".
  - Links the data update log.
  - Advises against using the released gold SQL for fine-tuning.
  - Gives no instance-level notes on wrong gold answers.
  - Top Lite entry when read: "Tianqiong Data Agent + GLM 5.2" at 76.23.

  Source: [spider2-sql.github.io](https://spider2-sql.github.io/)
- **Spider2 issue tracker** (213 issues as of 2026-11-18). By my count from titles, at least 40 report a wrong or ambiguous gold answer, gold SQL or eval config.
  - Lite BigQuery and GA reports:
    - [#103](https://github.com/xlang-ai/Spider2/issues/103) "bq363 incorrect/ambiguous" (open)
    - [#63](https://github.com/xlang-ai/Spider2/issues/63) bq383 ambiguity (closed; log 2025-02-25 changes bq383 `condition_cols`)
    - [#62](https://github.com/xlang-ai/Spider2/issues/62) BQ275 (closed; log 2025-02-25 "update question")
    - [#64](https://github.com/xlang-ai/Spider2/issues/64) ga008 date filtering (closed; log 2025-02-27)
    - [#61](https://github.com/xlang-ai/Spider2/issues/61) bq023 avg_donation SQL (closed)
    - [#88](https://github.com/xlang-ai/Spider2/issues/88) BQ011 date range (closed; log 2025-04-13)
    - [#35](https://github.com/xlang-ai/Spider2/issues/35) bq066 `ignore_order` (closed; log 2025-01-06)
    - [#151](https://github.com/xlang-ai/Spider2/issues/151) bq389/bq169/bq060 (open)
  - Snow reports include:
    - [#170](https://github.com/xlang-ai/Spider2/issues/170): gold queries with SQL syntax errors, for sf_bq033, sf_bq422 and sf_local015
    - [#136](https://github.com/xlang-ai/Spider2/issues/136) and [#130](https://github.com/xlang-ai/Spider2/issues/130): sf_bq294
    - [#129](https://github.com/xlang-ai/Spider2/issues/129): sf_bq182 and sf_bq193 (closed)
    - [#117](https://github.com/xlang-ai/Spider2/issues/117): sf_bq291 (closed)
    - [#133](https://github.com/xlang-ai/Spider2/issues/133) and [#135](https://github.com/xlang-ai/Spider2/issues/135): sf_bq233, sf_bq250, sf_bq236, sf_bq320
    - [#195](https://github.com/xlang-ai/Spider2/issues/195): external-knowledge documents that contradict the gold
    - [#157](https://github.com/xlang-ai/Spider2/issues/157): the evaluator treats NULL as 0

  Sources: [Spider2 issues](https://github.com/xlang-ai/Spider2/issues)
- **Lite local (SQLite) reports.** These are outside the 13-id scope but relevant to the project's 135-question split.
  - One reporter filed a batch on 2025-12-04/05 claiming incorrect gold for local010, local085, local273, local279, local354 and local358. The same batch also reported:
    - local060: ambiguous question
    - local130: wrong conditions columns
    - local194: underspecified question
    - local272: incorrect exec result
    - local331: too many valid answers
  - [#154](https://github.com/xlang-ai/Spider2/issues/154) says many SQLite gold SQLs do not match their gold exec results.
  - [#114](https://github.com/xlang-ai/Spider2/issues/114) (local066) and [#122](https://github.com/xlang-ai/Spider2/issues/122)/[#216](https://github.com/xlang-ai/Spider2/issues/216) (local029) report gold-query problems.
  - All of these were open when pulled.

  Sources: [#166](https://github.com/xlang-ai/Spider2/issues/166); [#161](https://github.com/xlang-ai/Spider2/issues/161); [Spider2 issues](https://github.com/xlang-ai/Spider2/issues)
- **Community repo FengMaXu/data_agent, PR #175** (merged 2026-10-15). It narrows a "Spider2 official 135 questions" gold-correct list from 103 to 80. The only reason given for the 23 removed is that their gold "did not hold up under review". The method is not described, the PR is marked as generated with Claude Code, and the id file returned 404 when fetched. This is low reliability, and the list likely covers the 135 local questions, not BigQuery. — [PR #175](https://github.com/FengMaXu/data_agent/pull/175)
### Inferences
- **No outside discussion of our ids.** Practitioners mostly report Lite BigQuery gold problems through GitHub issues. Those issues are often fixed through the update log, but our 13 ids have no such reports beyond bq389's config.
- **The local split is contested publicly.** Several of its questions have open reports of wrong gold, which matters when interpreting scores on the 135-question split.

### Gaps
- Social media: two web searches covering X/Twitter, Reddit, Hacker News and LinkedIn found no threads about wrong Spider 2.0 gold answers. Only papers, blogs and GitHub pages came back; the top hit for the authors was the CIDR slides, not a social post. X/Twitter and LinkedIn content needs a login and is poorly indexed, so this reflects search limits, not a confirmed absence.
- Hugging Face discussions and Discord were not searched directly.

## Q5. Context from BIRD audits: error rates and effect on accuracy and rankings

### Takeaway
Every BIRD audit finds a large share of noisy items:
- 15–49% per domain (Wretblad et al. 2024)
- 32.3% of Mini-Dev (Arcwise, 2024, as reported by UIUC)
- 52.8% of Mini-Dev (UIUC 2026)

Correcting labels changes rankings a lot. Zero-shot GPT-3.5 overtook DIN-SQL and MAC-SQL after Wretblad's correction. CHESS went from 7th to tied 1st and MAC-SQL from 4th to 13th after UIUC's correction, with a rank correlation of only 0.32 against the corrected subset. Verifier- and judge-based re-evaluations (SpotIt, FLEX) also find that wrong gold SQL is common among disagreements.

### Cited Findings
**Wretblad et al. 2024** — Niklas Wretblad, Fredrik Riseby, Rahul Biswas, Amin Ahmadi, Oskar Holmström, "Understanding the Effects of Noise in Text-to-SQL: An Examination of the BIRD-Bench Benchmark", ACL 2024 (Short Papers), pp. 356–369; arXiv 2402.12243 (Feb 2024)
- Noise rates by domain:

  | Domain | Examples with noise | Noisy questions | Wrong gold SQL |
  |---|---|---|---|
  | Financial | 52/106 (49%) | 44/106 (41.5%) | 22/106 (20.7%) |
  | California Schools | 9/20 (45%) | | |
  | Superhero | 3/20 (15%) | | |
  | Toxicology | 7/20 (35%) | | |
  | Thrombosis Prediction | 8/20 (40%) | | |

- Noise categories: spelling or syntax errors, vague or ambiguous questions, incorrect SQL, synonyms, string capitalization, and questions that do not map to the database.
- Effect on rankings: with corrected SQL, zero-shot GPT-3.5 outperformed DIN-SQL and MAC-SQL, a "drastic re-ranking". With both SQL and questions corrected, all models improved and zero-shot GPT-4 was best.
- Data and code: https://github.com/niklaswretblad/the-effects-of-noise-in-text-to-SQL

Sources: [ACL Anthology](https://aclanthology.org/2024.acl-short.34); [arXiv HTML v4](https://arxiv.org/html/2402.12243v4)

**Arcwise (2024)**
- SQL experts flagged 161 error examples in BIRD Mini-Dev, which UIUC reports as 32.3%. UIUC's SAR-Agent caught 138 of the 161 (85.7%) and found 41.6% more error examples.
- The CIDR version gives this prior rate as "36.1%" in one place and "32%" in another, an inconsistency inside the CIDR paper. 161 of 498 is 32.3%.
- Arcwise's corrections are linked from the UIUC repo as a Google Drive file. Arcwise also has a Hugging Face dataset, `arcwise/bird_sql_annotated`.

Sources: [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf); [CIDR PDF](https://vldb.org/cidrdb/papers/2026/p5-jin.pdf); [UIUC repo README](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks); [HF dataset](https://huggingface.co/datasets/arcwise/bird_sql_annotated/commits/main/train_0711.jsonl)

**UIUC 2026 (BIRD part)**
- 263 of 498 Mini-Dev examples are erroneous (52.8%).
- On 100 sampled Dev examples, 48 were corrected and 16 agents re-scored:
  - Relative accuracy change: −7% to +31%. Rank change: −9 to +9.
  - CHESS: 62% → 81%.
  - Spearman: 0.85 between the original subset and the full Dev set, and 0.32 against the corrected subset (p = 0.23).
- Released Arcwise-Plat-SQL and Arcwise-Plat on 2026-02-21.

Sources: [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p931-jin.pdf); [GitHub repo](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks)

**FLEX** (Heegyu Kim et al., "FLEX: Expert-level False-Less EXecution Metric for Reliable Text-to-SQL Benchmark", NAACL 2025; arXiv 2409.19014). Search summary only.
- An LLM judge replaces execution accuracy. The authors re-evaluated 50 public models on Spider and BIRD.
- They attribute EX's underestimation of models mainly to annotation quality, and report "many annotation issues of at least 15% per database".
- Reported agreement with experts (Cohen's kappa) differs by version: 61 → 78.17 in one, 62 → 87.04 in another.

Sources: [arXiv HTML v4](https://arxiv.org/html/2409.19014v4); [ACL Anthology PDF](https://preview.aclanthology.org/moar-dois/2025.naacl-long.228.pdf)

**SpotIt** (arXiv 2510.26840; ICLR 2026 poster). Search summary only.
- Bounded equivalence verification looks for a database on which the predicted and gold SQL disagree.
- BIRD accuracy drops by 11.3%–14.2% in v1, or 9.8%–13.5% in the ICLR listing.
- Quote: "when the predicted SQL disagrees with the ground truth, it is often the gold SQL that is incorrect."

Sources: [arXiv HTML](https://arxiv.org/html/2510.26840v1); [ICLR 2026 listing](https://iclr.cc/virtual/2026/poster/10007969)

**MCI-SQL** (Qin Wang et al., arXiv 2603.13390, 11 Mar 2026)
- The authors "manually identify and correct 412 samples in the BIRD dataset, forming a new version named BIRD-clear", released with their code.
- The abstract gives no error-rate breakdown.

Source: [arXiv abstract](https://arxiv.org/abs/2603.13390)

### Inferences
- **Error counts mislead on their own.** BIRD results show that a benchmark with roughly 30–50% noisy items can rank systems in a nearly unrelated order once corrected (r_s = 0.32). Small gains on a few contested items, like the 13 BigQuery ids, should be read with that in mind.
- **The BIRD lessons probably carry over to Spider 2.0.** UIUC finds the same error classes on Snow with similar E2 shares (about 58% in both benchmarks).

### Gaps
- The CIDR paper attributes a figure of "up to 17.6% underestimation of performance" to Wretblad et al. It was not found in the Wretblad text I read and is unverified.
- MCI-SQL reportedly states that the BIRD team acknowledged the errors and plans a corrected release. This came from a search snippet and was not confirmed in the abstract.
- I did not find an official corrected BIRD release.
- Arcwise's own write-up (method and categories) was not found; only its numbers as cited by UIUC.
