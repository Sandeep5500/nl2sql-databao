Contents

1. [Summary](#summary)
2. [1Terms](#terms)
3. [2Starting point](#start)
4. [3What was wrong](#faults)
5. [4Lessons from ktx](#ktx)
6. [5What we built](#built)
7. [6Results](#results)
8. [7Smoke test](#e2e)
9. [8Operational notes](#ops)
10. [9Next steps](#next)

NL2SQL capstone · Spider 2.0-Lite

# Rebuilding schema enrichment for the NL2SQL agent

Progress report · 25 September 2026 · branch `rohini-dev-v2` · model Qwen3.5-9B

Our agent answers database questions by writing SQL. To do that it looks up documentation about each database's tables and columns. That documentation was written by Qwen3-32B-AWQ from five sample rows per table, and it was often vague or wrong. The worst gaps were how tables connect to each other and what one row of a table represents.

We replaced the guesses with facts computed directly from the data and checked with SQL, following the approach of the open-source tool ktx. The documentation now records how tables join for 28 of 29 databases (previously 10). Search surfaces 98% of the tables a question needs (previously 72%). A six-question end-to-end test shows the new facts reaching the model and changing its SQL, but not yet changing its score.

**Table 1.** Headline results. All numbers are from 25 September unless noted.

| Measure | Before | After |
| --- | --- | --- |
| Databases whose documentation records how tables join | 10 / 29 | 28 / 29 |
| Real foreign keys found by join detection (recall) | none | 0.87 |
| Share of needed tables that search returns (table recall@8) | 0.717 | 0.979 |
| Questions where search returns every needed table | 16 / 35 | 32 / 35 |
| Column descriptions cut off mid-sentence | 76 | 1 |
| End-to-end accuracy, 135 questions | 47 / 135 | pending |

## 1Terms used in this report

The report uses a handful of database and retrieval terms. Each is defined here once, with an example from our data.

The task

NL2SQL agent

A language model that receives a question in English plus access to a database, and answers by writing and running SQL. Ours can take up to 30 steps: search the documentation, inspect tables, run trial queries, then submit.

Spider 2.0-Lite (local)

The benchmark: 135 questions over 30 SQLite databases. An answer counts as correct when the result of its SQL matches the reference result.

Greedy run

One attempt per question with sampling turned off, so the model always picks its most likely next token. Our greedy baseline is **47/135**.

pass@4

Four sampled attempts per question; a question counts if *any* of the four is correct. It measures what a perfect chooser could reach: **72/135**.

Validator

A second model call that looks at the four attempts and picks one. Julie's validator reaches 55 (9B) or 59 (27B).

Step cap

The 30-step limit. An episode that reaches it submits whatever query it ran last, which is usually wrong.

Gold tables

The tables used by a SQL query known to be correct for a question. We use them to check whether search found what was needed.

Schema documentation

Enrichment

Writing documentation for every table and column (what it holds, how it relates to others) so the agent can find and use the right ones.

DCE

databao-context-engine, the library that stores this documentation (one YAML file per database), turns it into a search index, and answers the agent's `search_context` calls.

Profiling

Computing facts from the data itself: row counts, how many distinct values a column has, how often it is empty, its full list of values when that list is short. Example: `order_status` has exactly 8 values, and "delivered" is 96,478 of 99,441 rows.

Schema overview

A compact list of every table and its columns, placed in the agent's instructions before it starts. Unlike search results, the agent always sees it.

Keys and joins

Join

Combining rows from two tables that share a value. Example: each order row is matched to its customer row where `orders.customer_id = customers.customer_id`.

Foreign key (FK)

A column whose values point at the key of another table, which tells you how to join them. A database may *declare* its foreign keys; 19 of our 29 databases declare none.

Join detection

Finding those links automatically when they are not declared. We propose a candidate from column names (a column `race_id` probably points at the table `races`), then run SQL to confirm that at least 90% of its values actually exist in the target table. Candidates that fail the check are dropped.

Composite key

A key made of several columns together. A join on such a key must use *all* of them. Example: `costs` has one row per product, day, promotion and channel. Joining on only product and day matches up to 7 rows per sale and inflates totals about 3×.

Role-named FK

A foreign key whose name does not match its target. Example: `away_player_1` through `away_player_11` all point at `player`; `reportsto` points at `employees`.

Grain

What one row of a table represents, stated as the smallest set of columns that is unique per row. Example: `constructor_standings` has one row per (race, constructor), a running total after each race.

Surrogate id

An artificial row number such as `constructor_standings_id`. It is unique, but it says nothing about what a row means, so we also report the natural grain behind it.

Coarser key

An identifier that groups several rows of the table's own key. Example: in the Olist data every order creates a new `customer_id`; the same person keeps one `customer_unique_id`. Counting customers must use the coarser key.

Search and measurement

Chunk

One searchable piece of documentation. DCE makes one chunk per table and one per column.

Embedding, hybrid search

Each chunk is converted into a vector (an embedding, here by the model nomic-embed-text) so that text with similar meaning can be found. Hybrid search combines that with ordinary keyword matching.

Task prefixes

Short labels (`search_query:`, `search_document:`) that nomic-embed-text was trained to expect in front of queries and documents. DCE was not adding them.

Table cards

Our new search output: results are grouped per table, and each table is shown once with its matched columns, instead of as a list of loose column chunks.

One-hop joins

Tables that are one verified join away from a search result, listed after the cards so the agent sees the tables it will need to join to.

Precision, recall

For join detection, *precision* is the share of the joins we proposed that are real, and *recall* is the share of the real joins that we found. We measure both on the 10 databases that declare their foreign keys, after hiding those declarations.

Table recall@8

For one question, the share of its gold tables that appear in the top 8 search results, averaged over questions. 1.0 means search returned every table the correct SQL uses.

Smoke test

A small run on a few chosen questions to confirm the whole pipeline works before spending hours on the full benchmark.

## 2Starting point

When the 9B fails a question that it solves on another attempt, it almost always had the right tables already. Most failures are in the logic of the query, and a quarter are the wrong column (Figure 1).

Right tables and columns, wrong logic

*74%*

Right table, wrong column

*25%*

Never found a needed table

*2%*

0%25%50%75%100%

**Figure 1.** Why the 9B fails on questions it can sometimes solve. Each of 122 pairs compares a correct and a failed attempt at the same question (62 questions). Source: Julie, `retrieval_vs_generation_findings.md`.

Two further results pointed at the documentation:

- **Missed tables are near-misses, and fixing them matters.** On questions the 9B had never solved, telling it the correct tables solved 6 of 12 runs where it had previously missed one, against 0 of 12 when it was given a decoy list of wrong tables. The misses were a sibling table (`constructor_standings`), or the one table holding the right identity key (`customers.customer_unique_id`).
- **Wrong-column errors** (25%) are the kind that good column documentation should prevent.

Separately, a validator choosing among four attempts raised accuracy from 47 to 55 or 59 of 135. Showing the validator the agent's reasoning made it slightly worse (51, 49, 48), and turning on the model's thinking mode did not improve accuracy.

## 3What was wrong with the documentation

Our enrichment came from one language-model pass that saw only the first five rows of each table and nothing about other tables. We found six problems (Table 2).

**Table 2.** Faults in the original documentation, with evidence from our YAML files.

| Fault | Evidence | Affects |
| --- | --- | --- |
| **Identity keys described backwards** | `customer_id` is called the primary identifier and `customer_unique_id` an external one. The truth is the reverse. | local004 |
| **Truncated text** | 76 of 2,965 column descriptions stop mid-sentence, because a 256-token output limit also applied to a rewrite step. | all |
| **No joins, keys or grain** | Only 10 of 29 databases declare foreign keys; f1 and both e-commerce databases have none. Nothing states that `costs` needs a four-column join. | local062, 311, 335 |
| **No profiling** | The five sample rows are the first rows on disk. `order_status` is documented as "delivered" only; it has 8 values. Dates stored as text are never labelled as such. | wrong column |
| **Invented detail** | `position_text` is described with example "1st", while the data holds "1". Many descriptions only restate the column type. | noise |
| **Values not searchable** | Sample values are shown to the agent but never indexed, so a question mentioning "canceled" cannot find `order_status`. | value lookups |

**Figure 2.** The same column documented before and after.

#### Before: `customer_unique_id`

A TEXT column that contains unique identifiers for customers, often used for external systems or data integration. It differs from customer_id, which is the primary internal identifier …

#### After

\[Profile\] COARSER KEY than customer_id: one customer_unique_id covers about 1.03 customer_id values; when the question counts or groups the thing customer_unique_id identifies, use customer_unique_id, not customer_id; never null; 96,096 distinct.

## 4Lessons from ktx

ktx is an open-source context layer for data agents from Kaelio, reported to have topped the Spider 2.0-Lite leaderboard (we have not verified this). Its central idea is to treat written descriptions as claims and to establish structure, such as keys and joins, with SQL. Table 3 lists what we adopted.

**Table 3.** ktx mechanisms and our counterparts.

| In ktx | In our pipeline |
| --- | --- |
| Profiling queries per column, and a dictionary of short value lists | Null rate, distinct count, range, the full value list when a column has 30 values or fewer, and the format of dates stored as text |
| Foreign keys and values written into each column's searchable text | Facts appended to the descriptions that DCE already indexes, so values and joins become searchable |
| Join detection in five layers, ending in a SQL check | Candidates from names and name tokens, then the same SQL check (at least 90% of values present). Handles composite and role-named keys; no language model needed. |
| Every table must declare its grain | The smallest unique column set per table, plus the natural grain behind surrogate ids |
| Search that also follows joins | Results grouped into table cards, followed by tables one verified join away |
| Verified facts are never overwritten by generated text | Speculative sentences about id columns removed; checked facts appended |

## 5What we built

1. **A profiling pass**, `scripts/profile_dce.py`. It reads each database read-only and writes checked facts into the documentation: a `[Profile]` note on every column and a `[Structure]` note on every table (grain, joins, coarser keys, similar tables). It also adds detected joins as foreign keys. It runs in about seven minutes for all 30 databases on a laptop, uses no GPU and no language model, and can be rerun safely.
2. **Join detection**, inside the same pass. A candidate is kept only if the SQL check passes. It finds composite joins (`sales` to `costs` on all four key columns) and role-named ones (`away_player_1` to `player`).
3. **Table-level search**, in `nl2sql-v2/src/nl2sql/context.py`. It fetches 32 chunks, groups them by table, and returns 8 table cards plus the tables one join away.
4. **Facts in the schema overview.** Each table is tagged with its grain, and verified joins and keys are listed, so the agent sees them even when it never searches.
5. **Two fixes inside DCE**, saved as a patch: foreign-key text now names the columns on both sides, and the embedding prefixes are added (optional). The output limit for any future language-model enrichment was raised from 256 to 1,024 tokens.

## 6Results

### 6.1 Coverage of the documentation

BeforeAfter

Databases with join information

*10 of 29*

*28*

Tables with a stated grain

*0*

*356 of 430*

Tables with join information

*84*

*267 of 430*

Columns with a complete value list

*0*

*1,405 of 2,965*

0%25%50%75%100%

**Figure 3.** Share of databases, tables or columns carrying each kind of fact, across the 29 profiled databases. Also added: 241 verified joins (10 composite), 23 coarser-key notes, date formats on 245 columns, and 52 natural grains behind surrogate ids. Truncated descriptions fell from 76 to 1.

### 6.2 Join detection

To score join detection we used the 10 databases that do declare their foreign keys (173 in total). We hid the declarations, ran detection, and compared its output with them (Table 4).

**Table 4.** Join detection against 173 declared foreign keys.

| Version | Precision | Recall | Notes |
| --- | --- | --- | --- |
| Name matching and SQL check | 0.92 | 0.68 | Misses role-named keys; recall on eu_soccer only 0.19 |
| **Adding role-named keys** | **0.92** | **0.87** | eu_soccer 0.97; chinook and music 1.00. 150 found, 13 extra, 23 missed. |

Some of the "extra" joins are real but undeclared. The four-column join from `sales` to `costs`, which question local062 needs, is one of them.

### 6.3 Does search return the tables a question needs?

We took 35 questions whose correct SQL is known, sent each question once to search, and checked whether its tables came back in the top 8 (Figure 4, Table 5).

Old indexNew indexNew index with task prefixes

Original search output

*0.717*

*0.738*

*0.777*

Table cards

*0.870*

*0.853*

*0.859*

Table cards and one-hop joins

*0.924*

*0.969*

*0.979*

00.250.50.751.0

**Figure 4.** Mean table recall@8 on 35 questions, one search per question, no query rewriting.

**Table 5.** Questions for which search returned every needed table (of 35), and tables shown per search.

| Search output | Old index | New index | New, prefixes | Tables shown |
| --- | --- | --- | --- | --- |
| Original | 16 | 17 | 19 | about 4 |
| Table cards | 26 | 25 | 26 | 7.3 |
| Table cards and one-hop joins | 31 | 31 | **32** | 8.3 to 9.8 |

- **Grouping by table is the largest gain.** The original output is mostly column chunks, so eight results covered only about four tables.
- **One-hop joins depend on detected joins.** For question local335, recall rises from 0.33 on the old index to 1.00 on the new one, because the join from `constructor_standings` to `races` and `constructors` now exists. Part of this gain comes from showing about 1.5 more tables per search.
- **Task prefixes help slightly in every mode**, so the full run uses the index built with them.

**Correction.** An earlier version of this measurement reported recall falling from 0.610 to 0.573 after the change. The script had ignored table chunks, which use a different file layout from column chunks. All numbers here come from the corrected script.

## 7End-to-end smoke test

We served the 9B with the same settings as the cluster and ran the six questions most tied to retrieval. The first run used the new search; the second also put the verified facts into the schema overview (Table 6).

**Table 6.** Six-question smoke test. "Earlier runs" counts correct attempts among the five runs analysed by Julie.

| Question | Earlier runs | New search | Plus facts in overview | Searches made |
| --- | --- | --- | --- | --- |
| local004 | 0 of 5 | wrong | wrong | 0 |
| local062 | 0 of 5 | wrong | wrong | 1 |
| local335 | 0 of 5 | wrong | wrong | 0 |
| local311 | 0 of 5 | step cap | step cap | 1 |
| local023 | 1 of 5 | step cap | step cap | 1 |
| local054 | 4 of 5 | correct | correct | 0 |

- **The join fact changed the SQL.** On local062 the agent now joins `costs` on all four key columns, where three of four earlier attempts used two and counted profit about three times over. It still fails for other reasons: it splits customers into ten equal-sized groups where the question asks for ten equal ranges of profit, and it reuses one table alias for two tables.
- **The agent skipped search on three of six questions**, so it never saw the new documentation. This is why the facts were added to the schema overview.
- **A stated fact is not always acted on.** On local004 the overview says to count people by `customer_unique_id`, and the 9B still used `customer_id`. Julie saw the same pattern: naming the right tables improves compliance more than correctness.
- Six questions cannot establish an effect either way; the full benchmark run is the real test.

## 8Operational notes

- DCE indexes every folder of YAML files under `spider2-dce/output/`. Backups placed there were indexed too (169 datasources, 4 GB). Backups and profiling output now live in `spider2-dce/backups/` and `spider2-dce/profiles/`.
- The search index is tied to the exact YAML files. Copy `dce.duckdb` together with them, or search will re-index on first use. The task prefixes must be on (`DCE_NOMIC_PREFIXES=1`) both when building the index and when searching it.
- The model server (`nl2sql-v2/modal/serve_vllm_qwen35.py`) requires an API key and shuts down after 20 idle minutes. The benchmark runner reads the key from `VLLM_API_KEY`.
- Heuristics added after inspecting the output: `grid` is not an identifier; leftover pandas `index` columns are not a grain; and small numbers such as durations or pitch positions fall inside any id range, so a foreign key's values must span at least 20% of the target key's range.

## 9Next steps

1. **Full benchmark, 135 questions, greedy**, on the new index, compared with 47/135. Everything is prepared; it takes about 90 minutes once approved. Results should be read separately for the questions no run has ever solved.
2. **Four samples per question on the new documentation, then Julie's validator**, to combine better retrieval with better selection.