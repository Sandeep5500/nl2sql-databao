# Error Analysis — gpt-5.4-mini, Spider2-lite Full 124 Questions

**Model:** gpt-5.4-mini  
**API:** CMU AI Gateway (`https://ai-gateway.andrew.cmu.edu/v1`)  
**Run 1 CSV:** `results/spider2_results_20260414_203430.csv` (Q1–50)  
**Run 2 CSV:** `results/spider2_results_20260414_230114.csv` (Q51–124)  
**Traces:** `logs/traces/run_20260414_203430/` and `logs/traces/run_20260414_230114/`

---

## Overall Summary

| Metric | Run 1 (Q1–50) | Run 2 (Q51–124) | Total |
|---|---|---|---|
| **Score** | **36/50 (72%)** | **35/74 (47%)** | **71/124 (57%)** |
| correct | 36 | 35 | 71 |
| result_mismatch | 10 | 21 | 31 |
| sql_execution_error | 4 | 16 | 20 |
| empty_result | 0 | 1 | 1 |
| no_sql | 0 | 1 | 1 |
| Input tokens | 2,463,474 | 3,279,409 | 5,742,883 |
| Output tokens | 200,171 | 337,031 | 537,202 |
| Avg per question | 49K in / 4K out | 44K in / 4.6K out | 46K in / 4.3K out |
| **Est. cost** | ~$1.30 | ~$1.85 | **~$3.15** |

The drop from 72% → 47% in Run 2 is driven by several new databases that performed poorly: sqlite-sakila (0/6), Db-IMDB (0/5), AdventureWorks (0/1), and f1 (3/9).

---

## Accuracy by Database (Combined)

| Database | ✓ | Total | % | Notes |
|---|---|---|---|---|
| Brazilian_E_Commerce | 8 | 8 | 100% | |
| Pagila | 2 | 2 | 100% | |
| education_business | 5 | 5 | 100% | |
| city_legislation | 9 | 10 | 90% | |
| northwind | 2 | 2 | 100% | |
| BowlingLeague | 1 | 1 | 100% | |
| delivery_center | 3 | 3 | 100% | |
| music | 1 | 1 | 100% | |
| IPL | 8 | 11 | 73% | |
| Baseball | 2 | 2 | 100% | |
| WWE | 1 | 1 | 100% | |
| EntertainmentAgency | 4 | 4 | 100% (Run 2 added 2/2) | |
| EU_soccer | 3 | 5 | 60% | |
| bank_sales_trading | 8 | 15 | 53% | |
| chinook | 2 | 3 | 67% | |
| California_Traffic_Collision | 2 | 3 | 67% | |
| imdb_movies | 2 | 4 | 50% | |
| modern_data | 4 | 7 | 57% | |
| Airlines | 1 | 2 | 50% | |
| log | 2 | 5 | 40% | InternalException recurring |
| f1 | 3 | 9 | 33% | Mix of SQL errors + result mismatches |
| complex_oracle | 2 | 6 | 33% | Projection/promo logic issues |
| school_scheduling | 0 | 1 | 0% | |
| E_commerce | 0 | 3 | 0% | |
| electronic_sales | 0 | 1 | 0% | |
| AdventureWorks | 0 | 1 | 0% | TypeMismatchException |
| Db-IMDB | 0 | 5 | 0% | BinderException + CatalogException |
| sqlite-sakila | 0 | 7 | 0% | Schema discovery failure |

---

## Run 2 Results Table

| ID | DB | ✓/✗ | Category | Steps | Tools | SQL | Srch | In Tok | Out Tok | Ext Knowledge |
|---|---|---|---|---|---|---|---|---|---|---|
| local074 | bank_sales_trading | ✗ | result_mismatch | 6 | 7 | 4 | 2 | 39K | 8K | — |
| local064 | bank_sales_trading | ✓ | correct | 7 | 7 | 5 | 1 | 47K | 9K | — |
| local297 | bank_sales_trading | ✗ | result_mismatch | 6 | 8 | 6 | 1 | 28K | 6K | — |
| local298 | bank_sales_trading | ✓ | correct | 6 | 6 | 3 | 2 | 38K | 5K | — |
| local299 | bank_sales_trading | ✗ | sql_execution_error | 6 | 6 | 5 | 1 | 51K | 7K | — |
| local300 | bank_sales_trading | ✗ | result_mismatch | 4 | 5 | 3 | 1 | 17K | 3K | — |
| local075 | bank_sales_trading | ✓ | correct | 10 | 13 | 12 | 1 | 64K | 7K | — |
| local077 | bank_sales_trading | ✓ | correct | 3 | 3 | 1 | 1 | 13K | 2K | — |
| local078 | bank_sales_trading | ✓ | correct | 10 | 10 | 8 | 1 | 80K | 6K | — |
| local081 | northwind | ✓ | correct | 3 | 3 | 1 | 1 | 15K | 2K | — |
| local085 | northwind | ✓ | correct | 3 | 3 | 1 | 1 | 17K | 1K | — |
| local096 | Db-IMDB | ✗ | result_mismatch | 8 | 8 | 6 | 1 | 15K | 2K | — |
| local097 | Db-IMDB | ✗ | sql_execution_error | 8 | 8 | 6 | 1 | 15K | 1K | — |
| local098 | Db-IMDB | ✗ | result_mismatch | 5 | 5 | 3 | 1 | 8K | 1K | — |
| local099 | Db-IMDB | ✗ | sql_execution_error | 9 | 9 | 7 | 1 | 17K | 2K | — |
| local100 | Db-IMDB | ✗ | sql_execution_error | 8 | 8 | 6 | 1 | 15K | 2K | — |
| local114 | education_business | ✓ | correct | 8 | 8 | 6 | 1 | 60K | 3K | — |
| local128 | BowlingLeague | ✓ | correct | 10 | 13 | 12 | 1 | 100K | 5K | — |
| local130 | school_scheduling | ✗ | result_mismatch | 5 | 5 | 2 | 2 | 51K | 3K | — |
| local131 | EntertainmentAgency | ✗ | result_mismatch | 3 | 3 | 1 | 1 | 15K | 1K | — |
| local133 | EntertainmentAgency | ✓ | correct | 3 | 3 | 1 | 1 | 12K | 1K | — |
| local132 | EntertainmentAgency | ✓ | correct | 3 | 3 | 1 | 1 | 13K | 2K | — |
| local141 | AdventureWorks | ✗ | sql_execution_error | 13 | 14 | 10 | 4 | 186K | 13K | — |
| local152 | imdb_movies | ✓ | correct | 4 | 5 | 1 | 2 | 24K | 2K | — |
| local230 | imdb_movies | ✗ | result_mismatch | 3 | 3 | 1 | 1 | 11K | 4K | — |
| local156 | bank_sales_trading | ✓ | correct | 4 | 4 | 2 | 1 | 19K | 3K | — |
| local157 | bank_sales_trading | ✗ | sql_execution_error | 12 | 12 | 10 | 1 | 106K | 9K | — |
| local163 | education_business | ✓ | correct | 4 | 4 | 2 | 1 | 17K | 1K | — |
| local168 | city_legislation | ✓ | correct | 3 | 3 | 1 | 1 | 12K | 2K | — |
| local169 | city_legislation | ✓ | correct | 3 | 3 | 1 | 1 | 13K | 5K | — |
| local171 | city_legislation | ✗ | sql_execution_error | 9 | 9 | 7 | 1 | 81K | 16K | — |
| local167 | city_legislation | ✓ | correct | 10 | 10 | 8 | 1 | 92K | 9K | — |
| local170 | city_legislation | ✓ | correct | 3 | 3 | 1 | 1 | 18K | 3K | — |
| local193 | sqlite-sakila | ✗ | result_mismatch | 6 | 6 | 4 | 1 | 11K | 1K | — |
| local194 | sqlite-sakila | ✗ | result_mismatch | 6 | 6 | 4 | 1 | 10K | 1K | — |
| local195 | sqlite-sakila | ✗ | sql_execution_error | 9 | 7 | 5 | 1 | 12K | 1K | — |
| local196 | sqlite-sakila | ✗ | empty_result | 4 | 4 | 2 | 1 | 9K | 1K | — |
| local197 | sqlite-sakila | ✗ | sql_execution_error | 8 | 7 | 5 | 1 | 10K | 1K | — |
| local199 | sqlite-sakila | ✗ | result_mismatch | 8 | 7 | 5 | 1 | 14K | 2K | — |
| local201 | modern_data | ✗ | result_mismatch | 5 | 5 | 3 | 1 | 23K | 2K | — |
| local210 | delivery_center | ✓ | correct | — | — | — | — | — | — | — |
| local212 | delivery_center | ✓ | correct | — | — | — | — | — | — | — |
| local218 | EU_soccer | ✓ | correct | — | — | — | — | — | — | — |
| local219 | EU_soccer | ✓ | correct | — | — | — | — | — | — | — |
| local221 | EU_soccer | ✓ | correct | — | — | — | — | — | — | — |
| local220 | EU_soccer | ✗ | result_mismatch | 3 | 3 | 1 | 1 | — | — | — |
| local244 | music | ✓ | correct | — | — | — | — | — | — | music_length_type.md ✓ |
| local229 | IPL | ✗ | sql_execution_error | — | — | — | — | — | — | — |
| local258 | IPL | ✓ | correct | — | — | — | — | — | — | baseball_game_special_words_definition.md ✓ |
| local259 | IPL | ✗ | result_mismatch | 3 | 3 | 1 | 1 | — | — | baseball_game_special_words_definition.md ⚠️ |
| local253 | education_business | ✗ | sql_execution_error | — | — | — | — | — | — | — |
| local283 | EU_soccer | ✗ | result_mismatch | 3 | 3 | 1 | 1 | — | — | — |
| local285 | bank_sales_trading | ✗ | result_mismatch | — | — | — | — | — | — | — |
| local286 | electronic_sales | ✗ | sql_execution_error | — | — | — | — | — | — | — |
| local302 | bank_sales_trading | ✗ | result_mismatch | 3 | 3 | 1 | 1 | — | — | — |
| local329 | log | ✓ | correct | — | — | — | — | — | — | — |
| local330 | log | ✗ | sql_execution_error | — | — | — | — | — | — | — |
| local331 | log | ✗ | sql_execution_error | — | — | — | — | — | — | — |
| local358 | log | ✓ | correct | — | — | — | — | — | — | — |
| local360 | log | ✗ | result_mismatch | 3 | 3 | 1 | 1 | — | — | — |
| local335 | f1 | ✗ | result_mismatch | — | — | — | — | — | — | — |
| local336 | f1 | ✗ | sql_execution_error | — | — | — | — | — | — | f1_overtake.md ⚠️ |
| local344 | f1 | ✗ | no_sql | — | — | — | — | — | — | f1_overtake.md ⚠️ |
| local309 | f1 | ✗ | sql_execution_error | — | — | — | — | — | — | — |
| local310 | f1 | ✓ | correct | — | — | — | — | — | — | — |
| local311 | f1 | ✓ | correct | — | — | — | — | — | — | — |
| local354 | f1 | ✓ | correct | — | — | — | — | — | — | — |
| local355 | f1 | ✗ | result_mismatch | — | — | — | — | — | — | — |
| local356 | f1 | ✗ | result_mismatch | — | — | — | — | — | — | — |

_Ext Knowledge: ✓ = applied correctly, ⚠️ = ignored or misapplied. Tools = search + sql + submit._

---

## Error Deep Dive — Run 2 New Failures

### sqlite-sakila (0/7) — Schema Discovery Failure

All 7 sqlite-sakila questions failed due to the same root cause seen in Run 1 (local056): the agent attempts SQLite-specific pragmas (`pragma_database_list`) which don't exist in DuckDB, fails to discover tables, and either gives up or produces wrong results.

- **local193, 194, 199**: result_mismatch — agent found some tables but used wrong joins/logic
- **local195, 197**: sql_execution_error — `BinderException` on column references after schema confusion
- **local196**: empty_result — query ran but returned no rows
- Pattern: agent never used `SHOW TABLES` or `DESCRIBE` to discover schema reliably

**Fix:** Add a system prompt hint: "Always use `SHOW TABLES` and `DESCRIBE <table>` to inspect available tables before writing queries. Do not use SQLite pragma functions."

---

### Db-IMDB (0/5) — BinderException + CatalogException

All 5 Db-IMDB questions failed with SQL errors:
- `BinderException` — column references that don't exist (agent hallucinating column names not in schema)
- `CatalogException` — referencing tables/views that don't exist in DuckDB

The agent was finding some schema info via `search_context` but not enough to write correct queries. The IMDB schema likely has many similarly named tables (movies, titles, series) leading to column confusion.

**Fix:** More targeted `search_context` queries for IMDB schema; add `DESCRIBE` calls to verify columns before joining.

---

### AdventureWorks (0/1) — TypeMismatchException

local141: 13 steps, 10 SQL attempts, 186K tokens. Recurring `TypeMismatchException` — SQLite stores numeric columns as strings (same issue as local010 Airlines). Agent tried many approaches but couldn't cast the values correctly.

**Fix:** `sqlite_all_varchar=true` hint to treat all SQLite columns as VARCHAR initially, then cast explicitly.

---

### f1 (3/9, 33%)

Mixed failures:
- **local309**: `InternalException` loop — 10 SQL attempts, DuckDB SQLite read bug
- **local336, local344**: `f1_overtake.md` doc not applied (see External Knowledge section)
- **local335, local355, local356**: result_mismatch — wrong aggregation logic (race position calculations)
- **local310, local311, local354**: correct ✓

F1 queries involve complex window functions (race rankings, lap times, position changes) that stress both DuckDB compatibility and agent reasoning.

---

### log (2/5, 40%)

- **local330, local331**: `InternalException` — DuckDB SQLite read bug on the log database schema
- **local360**: result_mismatch — wrong filter logic

---

### bank_sales_trading (8/15, 53%)

Largest single database in the benchmark. Failures split between:
- **sql_execution_error** (local299, local157): `InternalException` and `BinderException`
- **result_mismatch** (local074, local297, local300, local285, local302): wrong aggregation, wrong join logic, or wrong output columns

---

### External Knowledge — Run 2

| Question | Doc | Score | What happened |
|---|---|---|---|
| local244 | music_length_type.md | ✓ | Applied correctly; got right answer |
| local258 | baseball_game_special_words_definition.md | ✓ | Applied correctly (8 SQL attempts, persisted) |
| local259 | baseball_game_special_words_definition.md | ✗ | Same doc as local258; agent ran only 1 SQL, didn't apply terminology correctly |
| local344 | f1_overtake.md | ✗ | **no_sql** — agent searched 4 times but never wrote SQL; doc may have confused it |
| local336 | f1_overtake.md | ✗ | `CatalogException` — agent tried to use a table that doesn't exist, ignored formula in doc |

---

## External Knowledge — Combined Analysis (Both Runs)

| Question | Doc | Score | Application |
|---|---|---|---|
| local009 | haversine_formula.md | ✓ | Applied formula correctly |
| local035 | spherical_law.md | ✓ | Derived independently (doc internalized) |
| local244 | music_length_type.md | ✓ | Applied correctly |
| local258 | baseball_game_special_words_definition.md | ✓ | Applied correctly |
| local003 | RFM.md | ✗ | Substituted own segment thresholds |
| local010 | haversine_formula.md | ✗ | Ignored doc entirely |
| local061 | projection_calculation.md | ✗ | Used generic growth rate, not proj_factor formula |
| local050 | projection_calculation.md | ✗ | Same as local061 |
| local259 | baseball_game_special_words_definition.md | ✗ | Same doc as local258 (✓); only 1 SQL attempt |
| local344 | f1_overtake.md | ✗ | Never wrote SQL (no_sql) — doc may have caused confusion |
| local336 | f1_overtake.md | ✗ | Hallucinated table, ignored doc formula |

**Accuracy: 4/11 (36%) with external knowledge vs 67/113 (59%) without**

**Critical finding confirmed across both runs:** Correct doc application always yields a correct answer. Every failure involved either ignoring the doc or substituting the agent's own logic. The same doc can lead to success (local258) or failure (local259) depending on whether the agent commits to applying it.

**`f1_overtake.md` is especially problematic** — both questions using it failed, one with `no_sql` (agent got confused and never wrote a query). This suggests the doc may be complex or ambiguous enough to derail the agent entirely.

---

## Root Cause Summary (Combined)

| Root Cause | Instances | Count | Fix |
|---|---|---|---|
| DuckDB InternalException (SQLite type/read bug) | local003, 010, 073, 157, 171, 229, 253, 286, 309, 330, 331 | 11 | `sqlite_all_varchar=true` + explicit CAST guidance |
| result_mismatch (wrong aggregation/logic) | local002, 004, 015, 025, 049, 055, 060, 061, 063, 074, 096, 098, 130, 131, 193, 194, 199, 201, 220, 230, 259, 283, 285, 300, 302, 335, 355, 356, 360 | 29 | Mix of output format + query logic fixes |
| External knowledge doc not applied | local003, 010, 050, 061, 259, 336, 344 | 7 | Prompt: "use exact formulas/definitions from doc" |
| sqlite-sakila schema discovery | local056, 193, 194, 195, 196, 197, 199 | 7 | Hint: use `SHOW TABLES` / `DESCRIBE`, not pragmas |
| Output format wrong (correct logic, wrong shape) | local002, 015, 025, 055 | 4 | Prompt: "return exactly N columns named X" |
| complex_oracle promo/projection logic | local050, 060, 061, 063 | 4 | Schema hint: promo_id=999 = no-promo; projection formula |
| BinderException / CatalogException | local097, 099, 100, 286, 336 | 5 | Better schema discovery before querying |
| AdventureWorks TypeMismatch | local141 | 1 | `sqlite_all_varchar=true` |
| f1_overtake.md confusion (no_sql) | local344 | 1 | Simplify or clarify the doc |

---

## Highest-Value Fixes

| Fix | Est. questions recovered | Impact |
|---|---|---|
| `sqlite_all_varchar=true` + CAST hint | ~5–8 (InternalException cases) | +4–6% |
| System prompt: explicitly apply doc formulas | ~4–5 (EK failures) | +3–4% |
| `SHOW TABLES` / `DESCRIBE` hint for schema discovery | ~4–5 (sqlite-sakila) | +3–4% |
| Output format instruction ("return only N columns") | ~4 | +3% |
| complex_oracle schema hints (promo_id, projection) | ~3–4 | +2–3% |

**Potential score with all fixes applied: ~85–90/124 (69–73%)**
