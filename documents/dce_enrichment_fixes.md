# DCE enrichment: faults, fixes, and what we took from ktx

**Date:** 2026-09-25 · **Branch:** `rohini-dev-v2` · **Scope:** the 30 Spider 2.0-Lite local SQLite databases in `spider2-dce/`

## Summary

- Our semantic layer came from a single LLM pass that only saw 5 rows of each table. That layer is the YAML descriptions that `search_context` embeds.
- As a result it had no value profiles, no joins for 20 of 30 DBs, and no table grain. On `E_commerce` it described the identity keys backwards (`customer_id` vs `customer_unique_id`).
- Julie's analysis found three retrieval-related failures, and each traces straight to one of these gaps:

  | Question | Failure | Gap |
  |---|---|---|
  | `local004` | wrong customer key | identity keys backwards |
  | `local062` | 2-of-4 column join on `costs` | composite key never stated |
  | `local335` | missed `constructor_standings` | similar tables not told apart |

- The fix is a new **deterministic, SQL-verified enrichment pass**, `scripts/profile_dce.py`. It uses no LLM. It profiles each database directly and writes checked facts into the YAML descriptions that DCE already embeds. Most of the ideas come from Kaelio's ktx.
- Re-indexing uses DCE's existing index-only path, so there are no DCE code changes.
- **Results on the 29 profiled DBs:**

  | Metric | Before | After |
  |---|---|---|
  | Truncated descriptions | 76 | 1 |
  | Tables with a stated grain | 0 | 356 |
  | Tables with join information | 84 | 263 |
  | DBs with any join information | 10 | 28 |
  | Inferred joins | 0 | 241 (10 composite) |
  | Columns with a complete value list | 0 | 1,405 |
  | TEXT-date columns with their format | 0 | 245 |

- **Join precision against declared FKs:** 0.92 precision at 0.87 recall, with the declared FKs hidden (0.68 recall before role-named FKs).
- **Retrieval table recall@8** on 35 questions with known gold tables: **0.717 → 0.969** (old search output on the old index vs table-grouped search with one-hop joins on the new index). All gold tables are found on 31 of 35 questions, up from 16. Grouping accounts for most of it; join hops add the rest, and those rely on the inferred joins. See Section 5.

---

## 1. What was wrong

The pipeline is `scripts/enrich_dce.py`, which drives DCE's `context_enricher.py`, followed by `database_chunker.py` and hybrid vector + BM25 search.

| # | Fault | Evidence | Questions it hurts |
|---|---|---|---|
| F1 | **Identity keys described backwards.** The critique pass writes relationship claims without checking them. | `e_commerce.customers`: `customer_id` is called "the primary identifier", `customer_unique_id` "used for external systems". In Olist, `customer_id` is per order (1:1 with `orders`) and `customer_unique_id` is the person. The pre-critique draft was vague, not wrong; the critique made it worse. | `local004` |
| F2 | **Descriptions cut off mid-sentence.** `max_tokens=256` also bounds the critique call, which returns YAML for a whole table's columns. | 76 of 2,965 column descriptions end mid-word, e.g. "…It differs from". | all |
| F3 | **No joins, keys or grain.** DCE records only FKs that SQLite declares. | Only 10 of 29 DBs declare any FKs; `f1`, `E_commerce` and `Brazilian_E_Commerce` declare none. Nothing says `costs` is keyed on 4 columns, or that `constructor_standings` has one row per race × constructor. | `local062`, `local335`, `local311` |
| F4 | **No profiling.** Samples are `SELECT * LIMIT 5` (the first physical rows), and DCE's profiling is off and not implemented for SQLite. | `order_status` is described as "delivered" only, because all 5 sample rows are delivered; there are really 8 statuses. All 5 sample customers are in SP. Date columns stored as TEXT never say so. | wrong-column and wrong-filter failures (25% of reachable failures per Julie's paired analysis) |
| F5 | **Invented or boilerplate text.** | `f1.constructor_standings.position_text` is described with values "1st"/"2nd" while its samples show '1', '2'. Many descriptions only restate the type, nullability and default. | noise in retrieval |
| F6 | **Values not searchable.** Sample values are shown to the agent but never embedded or put in the BM25 text. | A question mentioning "canceled" cannot retrieve `order_status` through search. | value-linking questions |

**Julie's branch does not change enrichment.** `git diff origin/main...origin/dev-juliep2-ablation -- scripts/ spider2-dce/ databao-context-engine` is empty. Her `contract`, `sweep` and `oracle` context arms are built from the gold answer CSVs or teacher SQL. They are upper-bound experiments, not something we can use at inference time.

---

## 2. What ktx does (Kaelio/ktx)

ktx is Kaelio's open-source context layer for data agents. It reportedly topped Spider 2.0-Lite; we have not verified that claim. The parts relevant to us:

| ktx mechanism | ktx source | What it gives |
|---|---|---|
| Profiling SQL per column: count, nulls, `COUNT(DISTINCT)`, top-5 values, uniqueness and null rate. Low-cardinality text columns go into a data dictionary (≤200 values). | `scan/relationship-profiling.ts`, `scan/data-dictionary.ts` | real value distributions and enums |
| Embedding text per column: `table.col (type)`, then table description, then column description, then `FK -> t.c`, then `Values: v1, v2…` | `scan/embedding-text.ts` | values and joins become searchable |
| Join inference in 5 layers: name heuristics (`_id/_key/_code`, singularised table names), profiling, an LLM PK/FK proposal, weighted scoring, then **SQL validation** (child→parent coverage ≥0.9, parent uniqueness ≥0.9, orphan ratio ≤1%). Supports composite keys. Low-confidence results go to a human review band. | `scan/relationship-*.ts` | joins for undeclared-FK databases |
| Every semantic-layer source must declare its **grain**. Join paths are costed (1:N costs 10). The planner detects fan traps and pre-aggregates before joining. | `context/sl/schemas.ts`, `python/ktx-sl/semantic_layer/graph.py` | no double counting through wrong-grain joins |
| Hybrid search: RRF over semantic, lexical and **dictionary** (value) lanes. | `search/hybrid-search-core.ts`, `sl/dictionary-search.ts` | value → column linking |
| Descriptions kept per source (`ai`, `db`, `dbt`, `user`) rather than merged. | `scan/enrichment-types.ts` | LLM guesses never overwrite verified facts |

---

## 3. What we changed

### 3.1 `scripts/profile_dce.py` (new, pure `sqlite3`, about 7 minutes on a laptop CPU for all 30 DBs)

It reads each DB read-only, with a per-query time budget. It writes verified facts into `spider2-dce/output/databases/*.yaml` and a sidecar `spider2-dce/profiles/<db>.json`. Originals are backed up to `spider2-dce/backups/databases_pre_profile_<timestamp>/` (outside `output/`, see 3.3). The script is idempotent: previous `[Profile]` / `[Structure]` suffixes and `inferred_fk_*` entries are stripped before rewriting.

| Step | What it does | ktx influence | Fixes |
|---|---|---|---|
| Column profile | null %, distinct count, uniqueness, min/max. Lists **all values** when there are ≤30, else the top 8 (skipped for high-cardinality ids and free text). Regex-detects the **format of TEXT dates** (`YYYY-MM-DD HH:MM:SS`, …). Appended to each column description as `[Profile] …`. | profiling SQL + data dictionary | F4, F6 |
| Grain | Smallest unique key: declared PK, else a unique id column, else a 2–4 column combination checked with `GROUP BY … HAVING COUNT(*)>1`. For surrogate-keyed tables it also finds the **natural grain** (`constructor_standings`: one row per `(race_id, constructor_id)`; `constructor_standings_id` is a surrogate). | the required `grain` | F3 |
| Join inference | Candidates are exact shared names and `x_id` → table `x`/`xs`. Accepted only if the parent key is unique and **≥90% of the child's distinct values exist in the parent** (a set-based `EXCEPT` query). Labelled `N:1`/`1:1` with coverage. **Composite joins** are found when a multi-column parent grain appears whole in a child: `sales (time_id, prod_id, promo_id, channel_id) → costs`, "join on ALL these columns". A table's own key is never treated as an FK. Joins are written both as text and as structural `foreign_keys` (`inferred_fk_*`, `enforced: false`), so DCE's chunker puts them in the table embedding. | name heuristics + SQL coverage validation; composite candidates | F3 |
| Coarser keys | Detects a never-null id column that groups the table's unique key and has no table of its own. `customers.customer_unique_id` groups `customer_id` (~1.03 per person), so the text says "use `customer_unique_id` when counting the thing it identifies". Combined with the inferred `orders.customer_id → customers` **1:1** join, this states that `customer_id` is per order. | ktx's key scoring, reduced to a data test | F1 |
| Similar tables | Groups tables that share a name stem (`constructor_standings` / `constructor_results` / `driver_standings`) and lists each one's grain and row count side by side. | Julie's "surface sibling tables" next step | `local335` |
| Description cleanup | Truncated descriptions are cut back to their last full sentence. On id columns, hedged speculation ("often", "may", "external systems"…) and sentences comparing id columns are dropped, because the verified facts replace them. | ktx never lets AI text overwrite verified facts | F1, F2, F5 |
| Samples | 5 random rows (`ORDER BY RANDOM()`) instead of the first 5. | | F4 |
| Views | Materialised once into a same-named TEMP table (temp resolves before main), capped at 200k rows. Views too expensive to materialise (`complex_oracle.profits`) or broken (`oracle_sql.emp_hire_periods_with_name`) are left untouched. | | |

Only database contents and schema are read, never questions, gold SQL or gold CSVs. So, unlike the contract/sweep arms, this is usable at inference time.

**Example: `e_commerce.customers.customer_unique_id`**, before:
> customer_unique_id is a TEXT column that contains unique identifiers for customers, often used for external systems or data integration. It differs from customer_id, which is the primary internal identifier…

After:
> [Profile] COARSER KEY than customer_id: one customer_unique_id covers about 1.03 customer_id values; when the question counts or groups the thing customer_unique_id identifies, use customer_unique_id, not customer_id; never null; 96096 distinct.

**Example: `complex_oracle.sales`** (table text, after):
> [Structure] 918843 rows. … Joins: (time_id, prod_id, promo_id, channel_id) -> costs(time_id, prod_id, promo_id, channel_id) join on ALL these columns [N:1, 100%].

**Example: `brazilian_e_commerce.olist_orders.order_status`**, after:
> [Profile] never null; 8 distinct; all values: delivered (96478), shipped (1107), canceled (625), unavailable (609), invoiced (314), processing (301), created (5), approved (2).

### 3.2 `scripts/enrich_dce.py`, `scripts/enrich_one_db.py`

`max_tokens` changes from 256 to 1024, so a future LLM re-enrichment no longer truncates the critique output (F2 at the source).

### 3.3 Re-index

The profiled YAMLs were re-embedded into `spider2-dce/output/dce.duckdb` (a copy of the April index from `nl2sql-databao-old`) with DCE's index-only API, `DatabaoContextDomainManager(domain_dir).index_built_contexts()`. It used nomic-embed-text v1.5 on a local Ollama, took 25.6 minutes on CPU, and involved no re-introspection and no DCE code changes. On Windows, set `PYTHONUTF8=1`.

**Gotcha:** DCE indexes *every* YAML folder under `output/`. The first run also embedded the backup folders, 169 datasources in total. Search filters to `databases/<db>.yaml`, so results are unaffected, but the file grew to about 4GB. Backups and sidecars now go to `spider2-dce/backups/` (gitignored) and `spider2-dce/profiles/`. For a clean, smaller index, rebuild on the cluster or Modal from a fresh copy, passing `datasource_ids` for `databases/*.yaml` only.

---

## 4. Measured: join inference

Method: on the 10 DBs that declare FKs, the declared FKs were hidden, joins were inferred, and the two sets compared. "v1" is name matching only; "v2" adds role-named FKs (item 2 in Section 6).

| DB | Declared | v1 P / R | **v2 P / R** |
|---|---|---|---|
| chinook | 11 | 1.00 / 0.82 | **1.00 / 1.00** |
| music | 11 | 1.00 / 0.82 | **1.00 / 1.00** |
| entertainmentagency | 9 | 1.00 / 1.00 | **1.00 / 1.00** |
| eu_soccer | 31 | 1.00 / 0.19 | **1.00 / 0.97** |
| pagila / sqlite_sakila | 22 | 1.00 / 0.91 | **1.00 / 0.91** |
| oracle_sql | 32 | 0.92 / 0.72 | **0.92 / 0.75** |
| complex_oracle | 10 | 0.80 / 0.80 | **0.73 / 0.80** |
| bowlingleague | 8 | 0.67 / 0.50 | **0.67 / 0.75** |
| school_scheduling | 17 | 0.71 / 0.59 | **0.69 / 0.65** |
| **Overall** (173 declared) | | **0.92 / 0.68** | **0.92 / 0.87** (tp 150, fp 13, fn 23) |

- Some "false positives" are real joins that are simply undeclared. `sales → costs` on 4 columns is the correct `local062` join, but it is not a declared FK.
- **v2 fixes:** `match.away_player_1..11` / `home_player_*` → `player.player_api_id` (eu_soccer recall 0.19 → 0.97), `customers.supportrepid` / `employees.reportsto` → `employees`.
- **Remaining misses:**
  - FKs whose values are all NULL: `film.original_language_id`.
  - Names that share no token with the target: `store.manager_staff_id` targets `staff`, but the token check did not match it because the `staff` table's grain is not id-typed.
  - `school_scheduling`'s staff/faculty ambiguity.

## 5. Measured: retrieval

**Method.**
- 35 questions with known gold tables: Julie's 14 teacher-verified queries plus 21 Spider2 gold SQLs.
- The query is the raw question with no LLM paraphrases, restricted to the question's database, with k=8.
- A table counts as found if any of its chunks, or its card, is returned.
- The eval script is `retrieval_eval.py`. It evaluates three modes of `nl2sql.context.SearchContext`:
  - **chunks:** DCE's top-8 chunks, the old `search_context` output.
  - **tables:** new (item 0). It fetches 32 chunks, fuses them per table, and returns the top 8 tables as compact cards.
  - **+hops:** new (item 0). It also lists the tables one declared or inferred join away.

| Mode | Metric | Old index | New index |
|---|---|---|---|
| chunks (old behaviour) | mean table recall | 0.717 | 0.738 |
| | all gold tables found | 16 / 35 | 17 / 35 |
| | tables shown | 3.7 | 4.1 |
| **tables** | mean table recall | 0.870 | 0.853 |
| | all gold tables found | 26 / 35 | 25 / 35 |
| | tables shown | 7.3 | 7.3 |
| **tables + hops** | mean table recall | 0.924 | **0.969** |
| | all gold tables found | 31 / 35 | 31 / 35 |
| | tables shown | 8.3 | 9.7 |

**Reading it.**
- The biggest lever is **table-level grouping**: 0.72 → 0.86. Raw DCE returns mostly column chunks, so 8 hits cover only about 4 tables.
- **Join hops** add the tables a query needs but doesn't name (`local335`: `constructor_standings` → `races`, `constructors`). They benefit most from the **new** index, because 20 of 29 DBs only have joins through inference (`local335`: 0.33 on the old index, 1.00 on the new). Hops also show about 1.4 more tables, so part of that gain is simply showing more.
- On raw chunks the profiled index is slightly ahead (0.717 → 0.738). Grouped without hops it is slightly behind (0.870 → 0.853, a one-question difference). Mean reciprocal rank (MRR) of the first gold table under grouping dropped (0.833 → 0.757): long `[Profile]` text shifts which chunks rank first.
- **Correction:** an earlier draft of this section reported 0.610 → 0.573. That eval ignored table chunks, because their display format is `{table: {name, …}}`. The table above supersedes it.
- **Caveat:** small n, and one raw query per question. The agent adds paraphrases and several searches per episode.


---

## 6. Next steps: status

0. ~~**Retrieval coverage**: table-level aggregation of search hits, plus one-hop join expansion.~~
   **Done.** `nl2sql-v2/src/nl2sql/context.py` groups search hits by table (compact cards) and lists one-hop joined tables. It is on by default (`SearchContext(group_tables=True, join_hops=True)`). Table recall@8 rose from 0.717 to 0.969; see Section 5.
1. **End-to-end benchmark.** *In progress.*
   - ~~Serve the 9B~~ **Done:** `nl2sql-v2/modal/serve_vllm_qwen35.py` serves it on Modal (L40S, vLLM 0.18.1, same flags as the SLURM script, API key from the Modal secret `nl2sql-vllm`). The runner reads `VLLM_API_KEY`.
   - ~~Smoke test on `local004, local062, local335, local311, local023, local054`~~ **Done:** 1/6 both with and without the facts in the overview; the old greedy run also scored 1/6.
     - `local062` now joins `costs` on all 4 key columns (before, 3 of 4 runs used 2 columns). It still fails on `NTILE` vs equal-width buckets and a reused alias.
     - The agent **skipped `search_context` on 3 of 6 questions**, which is why item 5 was pulled forward.
     - `local004` still groups by `customer_id` even with the coarser-key fact in the prompt: the fact reaches the model, and the 9B does not act on it.
   - Full 135 greedy, compared with 47/135: *next.*
2. ~~**Role-named FKs** (ktx layers 4–5): candidates for FKs whose names do not match the target.~~
   **Done.** `role_named_joins()` in `profile_dce.py`:
   - A column token must name the parent table (`away_player_1` → `player`), or be a person role pointing at a person table (`supportrepid`, `reportsto` → `employees`).
   - The target can be any unique id column (`player_api_id`).
   - Coverage must be ≥95%, and numeric FK values must span ≥20% of the parent key's range, which rejects durations and coordinates.
   - Join inference went from **P 0.92 / R 0.68 to P 0.92 / R 0.87** against the 173 declared FKs. No LLM proposal step was needed.
3. ~~**nomic task prefixes**: `search_document:` / `search_query:`.~~
   **Done (opt-in).** A DCE patch in the Ollama embedding provider, enabled with `DCE_NOMIC_PREFIXES=1`. It must be set both when indexing and when searching. The patch is at `scripts/dce_patches/0001-fk-text-and-nomic-prefixes.patch`; apply it to the `spider2-patches` submodule branch for the cluster. Measured effect: see Section 5.
4. ~~**Fix the chunker FK sentence.**~~
   **Done.** The same patch makes the table text list every FK as `(from_cols) -> table(to_cols)`. Before, for a single FK it said "The column has a foreign key to X".
5. ~~**Agent-side use**: add joins, grain and coarser keys to `--schema-overview`.~~
   **Done.** `run_benchmark.py::schema_overview` reads `spider2-dce/profiles/<db>.json`. It tags each table with `[one row per ...]` and appends "Verified joins and keys" (composite joins say "join on ALL of"). That adds about 4–7k characters to the system prompt.
6. ~~**Deepika's rule-based checks for the validator.**~~
   **Done, and evaluated offline.** `nl2sql-v2/src/nl2sql/checks.py` holds the checks; `scripts/rule_checks_eval.py` evaluates them.
   - On Julie's pass@4 pool, 88% of flagged candidates are wrong, and only 4.3% of correct candidates get flagged.
   - But the flags catch just 52 of about 376 wrong candidates. Filtering random picks moves 41.0 → 41.6.
   - The 9B and 27B validators picked a flagged candidate on only 7 questions, and no unflagged correct alternative existed on any of them.
   - **Conclusion:** a cheap guard (better used inside the episode, before the agent submits), not a selection lever. `more_rows_than_top_2` is noisy (25% wrong) and should be dropped or loosened.

**Still open:**
- Pass@4 on the new enrichment, with Julie's validator on top.
- Nothing is committed yet.

## Reproduce

```bash
cd spider2-dce
python ../scripts/profile_dce.py [--db-dir <dir with *.sqlite>] [--only f1,e_commerce] [--dry-run]
PYTHONUTF8=1 python -c "from pathlib import Path; from databao_context_engine.databao_context_domain_manager import DatabaoContextDomainManager as M; print(M(domain_dir=Path('.')).index_built_contexts())"
```
Needs an Ollama embed server with `nomic-embed-text:v1.5` (`DCE_OLLAMA_HOST` on the cluster). Don't re-index while a search-mode run is reading `dce.duckdb`.
