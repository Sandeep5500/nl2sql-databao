# Spider 2.0 NL2SQL Error Analysis — Gemini 3.1 Pro Preview (Vertex AI)

## Run Summary

- **SQL Agent Model**: `gemini-3.1-pro-preview` via Google Vertex AI (`ChatGoogleGenerativeAI`, google-genai SDK)
- **Vertex Project**: `lunar-geography-433410-n6` / `global`
- **Embedding Model**: `nomic-embed-text-v1.5` (Ollama / fast_embed_server)
- **DCE Enrichment Model**: `Qwen/Qwen3-32B-AWQ`
- **Framework**: databao-agent (LangGraph, Lighthouse executor)
- **Recursion Limit**: 50 LangGraph nodes (≈ 25 AI steps)
- **Date**: April 16, 2026 (17:50 → 21:46 local)
- **Logs**: `results/current_run.txt`, traces in `logs/traces/run_20260416_{175014,192401,194812,213943}/`, CSVs `results/spider2_results_20260416_{175014,192401,194812,213943}.csv`

| Metric | Value |
|--------|-------|
| **Total Questions** | 124 (135 local track − 11 excluded) |
| **Correct** | **59 (47.6%)** |
| **Result Mismatch** | 30 (24.2%) |
| **Agent Error** | 35 (28.2%) — 34 `recursion_limit`, 1 Vertex `400 INVALID_ARGUMENT` |
| **No SQL Submitted** | 0 (0.0%) |
| **Total wall-clock** | ~3 h 38 min (13,075 s across 4 segments) |
| **Mean time / question** | 105 s (min 9 s, max 479 s) |
| **Total input tokens** | 12,353,262 (~99.6 K / q) |
| **Total output tokens** | 958,180 (~7.7 K / q) |

---

## 1. Result Mismatch Breakdown (30 questions)

Each row below was produced by reading the predicted SQL, the pred/gold result previews, and the trace, then assigning a single primary root cause.

### 1A. Column-Name / Alias Mismatch — values correct, headers different (9 cases)

The numbers match but the evaluator rejects because column names, order, or types differ from the gold header row.

| Instance | DB | What's off |
|----------|------|-----------|
| local029 | Brazilian_E_Commerce | `num_delivered_orders` → `delivered_orders`; `city` → `customer_city`; `state` → `customer_state` |
| local032 | Brazilian_E_Commerce | Column order `seller_id, value, achievement` — gold has `ACHIEVEMENT, seller_id, VALUE` |
| local074 | bank_sales_trading | `end_date` (timestamp 2020-01-31) → gold `MONTH` as `'2020-01'` string; `closing_balance` → `CUMULATIVE_BALANCE` |
| local077 | bank_sales_trading | `interest_1_month_ago` / `max_index_1_month_ago` → gold `PREV_MONTH_INTEREST_NAME` / `PREV_MONTH_MAX_COMPOSITION`; `rolling_avg` → `ROLLING_AVG_3MONTH` |
| local131 | EntertainmentAgency | Missing `StyleID`; values returned as float (`0.0`) where gold has integer |
| local220 | EU_soccer | Category labels `Most Wins` / `Most Losses` with spaces (gold: `most_wins` / `most_losses`); `count` float vs gold int |
| local229 | IPL | `player_1 / score_1` → `PLAYER1_ID / PLAYER1_SCORE`; also one row has value mismatch (60 vs 57) from extras double-counting |
| local259 | IPL | `total_matches` → `total_matches_played`; `total_dismissals` → `total_times_dismissed`; `total_wi...` → `total_wickets_taken` |
| local286 | electronic_sales | Missing `total_quantity_sold`; `top_product_category` → `top_categories_english`; `avg_*` → gold `average_*` |

**Pattern**: Gemini consistently picks idiomatic `snake_case` aliases instead of the exact column names Spider 2.0 expects. A pre-submit rule that required the agent to restate expected output headers from the question wording would fix most of these.

---

### 1B. Output Formatting — values correct, wrong literal format (2 cases)

| Instance | DB | What's off |
|----------|------|-----------|
| local028 | Brazilian_E_Commerce | Returned `month` as integer `1, 2, 3` — gold uses `'January', 'February', 'March'` strings |
| local299 | bank_sales_trading | Returned `month` as integer `2, 3, 4` — gold uses `'2020-02', '2020-03', '2020-04'`. Values also differ (see 1C) |

---

### 1C. Wrong Aggregation / Business-Metric Formula (9 cases)

| Instance | DB | Bug |
|----------|------|-----|
| local003 | E_commerce (ek: `RFM.md`) | RFM thresholds wrong — `NTILE(5)` ordering reversed + segment case-when doesn't match doc (got `Can't Lose Them` avg 342.55, gold `Champions` 301.07) |
| local008 | Baseball | Picked the player with the max single-season stat (`Maurice Morning`, 165 games) instead of career total (`Peter Edward`, 3562). `MAX(g)` over batting rows instead of `SUM(g) GROUP BY player`. |
| local031 | Brazilian_E_Commerce | `265` vs gold `205` — likely counting all orders in the lowest-volume year rather than only `delivered` ones consistently, or off-by-one year filter |
| local049 | modern_data | `59.67` vs `60.33` — wrong tie-breaking on "top industry" (two industries may be tied; Gemini picked the alphabetically first via `ORDER BY COUNT DESC`), or mis-joined `companies_industries`/`companies_dates` with duplicate matches |
| local059 | education_business | Returned single scalar `794864.89`; gold wants one row per division. SQL does `AVG(total_quantity) FROM RankedProducts WHERE rnk<=3` without `GROUP BY division` |
| local141 | AdventureWorks | Every year's `difference` is ~4000 units off (−97073 vs −93432). Probably summing `subtotal` instead of `TotalDue` or missing an order-status filter |
| local198 | chinook | `median(Total)` from `invoices` table, got 3.96 vs gold 249.53. Should have computed per-customer lifetime value (sum of `UnitPrice × Quantity` from `invoice_items`) then median across customers |
| local253 | education_business | `Average Salary in Country` = 767988 vs 915555. Country average likely excludes some rows that gold includes (e.g., filtering out cities not in the top-4) |
| local283 | EU_soccer | Only returned one team per season globally (used `RANK() OVER(PARTITION BY season)` without `league_id`); gold wants champion per season *per country/league* |

---

### 1D. Wrong Question Interpretation (5 cases)

The agent misread the question's intent, not the aggregation formula.

| Instance | DB | Misread |
|----------|------|---------|
| local004 | E_commerce | Dropped the `customer_unique_id` column; question asks "the 3 customers" with identifying column |
| local064 | bank_sales_trading | Returned a single scalar `difference = 419.994`; gold wants a 7-column summary row (highest_month, highest_positive_count, highest_avg_balance, lowest_*, average_difference) |
| local169 | city_legislation | Returned individual legislator rows; gold is a per-year retention-rate table over 20 years |
| local210 | delivery_center | Returned only `hub_name` list; gold wants `hub_id, hub_name, year, feb_finished_orders, mar_finished_orders, pct_increase` |
| local309 | f1 | Returned recent years only (2024 → 2020, Verstappen/Hamilton); gold starts at 1950 (Farina). The `driver_standings` table likely doesn't have historic rows — agent should have joined through `results` instead |

---

### 1E. Wrong Filter / Boundary / JOIN (3 cases)

| Instance | DB | Bug |
|----------|------|-----|
| local157 | bank_sales_trading | First-day percent-change must be `NaN` (no prior volume); Gemini returned `79.91` because it computed against volume zero. Column also named `pct_change` vs gold `daily_percentage_change` |
| local209 | delivery_center | Missing `store_id, TOTAL_ORDERS, DELIVERED_ORDERS` columns — only kept ratio. Values otherwise correct |
| local330 | log | Counted `/detail/` and `/detail` (with / without trailing slash) as separate pages; gold normalizes to `/detail/` giving count=9 not 8 |

---

### 1F. Infrastructure: tables not attached (1 case)

| Instance | DB | |
|----------|------|---|
| local199 | sqlite-sakila | Predicted SQL = `SELECT * FROM sqlite_master` (returned empty). Tables never loaded — see §2A |

**Note**: `local199` shows up as `result_mismatch` rather than `agent_error` because the agent did submit something (an empty SELECT from a catalog view). All seven other `sqlite-sakila` questions hit `recursion_limit` instead.

---

## 2. Agent Error Breakdown (35 questions)

### 2A. Database Not Attached — agent exhausts catalog probes finding zero tables (9 cases)

Every table-listing approach (`SHOW TABLES`, `information_schema.tables`, `duckdb_tables()`, `sqlite_master`, `pg_tables`, `SELECT * FROM duckdb_databases()`) returns 0 rows. The agent correctly diagnoses "tables not attached" but cannot bootstrap them, then burns its step budget trying increasingly creative probes.

| Instance | DB | Trace signal |
|----------|------|--------------|
| local056 | sqlite-sakila | 16 empty-result queries; ends on `current_setting('search_path')` returning empty |
| local193 | sqlite-sakila | 21 empty results; repeated CatalogExceptions on `sales`, `customers`, `payments` |
| local194 | sqlite-sakila | 13 empty results; `duckdb_tables()` returns 0 rows |
| local195 | sqlite-sakila | 13 empty results; agent even tries `ATTACH 'Pagila.sqlite'` — wrong DB file |
| local196 | sqlite-sakila | 19 empty results; 25 SQL calls, no errors (all empty) |
| local197 | sqlite-sakila | 12 empty results; tries IMDB table names (`orders`, `customers`) in confusion |
| local096 | Db-IMDB | 11 empty results; CatalogException on `Movie`, `movies`, `films` |
| local097 | Db-IMDB | 14 empty results; `glob('*.parquet')` returns empty |
| local100 | Db-IMDB | 15 empty results; `glob('*.csv')` empty |

**Root cause**: DuckDB `ATTACH` step for `sqlite-sakila.sqlite` and (for some runs) `Db-IMDB.sqlite` is not registering tables under the agent's search path. The DCE `search_context` also returns 0 chunks for these DBs — the catalog YAMLs may be missing or misnamed in `dce.duckdb`. This is an infrastructure bug, not an agent reasoning bug.

**Fix**: Investigate the temp-DCE-project creation path for these two databases, and verify `dce.duckdb` contains chunks tagged `sqlite-sakila` and `Db-IMDB`. Re-running these 9 after the fix is a pure win.

---

### 2B. Partial Attach + Doom Loop on Schema Confusion (2 cases)

Tables are reachable under `imdb.<Table>` but the agent spends its budget trying namespace variants.

| Instance | DB | Trace signal |
|----------|------|--------------|
| local098 | Db-IMDB | `imdb.M_Cast LIMIT 10` **worked** (returns PIDs), but agent still hit recursion limit — 8 of 24 SQL calls returned 0 rows from wrong namespaces |
| local099 | Db-IMDB | `information_schema.columns WHERE table_catalog='imdb'` **worked** and returned `Movie, Person`, but agent couldn't recover into productive SQL |

**Fix**: System-prompt hint: "Tables in this DB may be under `<db_name>.<Table>` without a `main` schema; try both `db.main.Table` and `db.Table` forms."

---

### 2C. Real Doom Loops — Complex Logic, Never Submits (23 cases)

Tables load, searches return chunks, SQL executes cleanly. The agent writes plausible answers, inspects the result, self-rejects, and rewrites — but never calls `submit_result`.

| Instance | DB | Loop driver (from last SQL + error history) |
|----------|------|----------------------------------------------|
| local009 | Airlines (ek: `haversine_formula.md`) | `TypeMismatchException` on `coordinates` column (stored as text tuple `"(lat,lon)"`); agent keeps trying to parse. Reached a correct-looking `3484 km` answer but didn't submit |
| local010 | Airlines (ek: `haversine_formula.md`) | Same coordinate-parsing struggle; ends checking for NULL airports |
| local015 | California_Traffic_Collision | Multi-table motorcycle fatality rate; agent kept exploring `parties` / `victims` table relationships |
| local025 | IPL | **Not recursion** — Vertex returned `400 INVALID_ARGUMENT` at step 16. Likely oversized or malformed prompt. |
| local034 | Brazilian_E_Commerce | `CatalogException` on `olist_order_items` — agent couldn't settle on the `brazilian_e_commerce.main.` prefix after switching tables |
| local040 | modern_data | Trees-income join with ZIP filling; agent kept re-validating filtering clauses |
| local050 | complex_oracle (ek: `projection_calculation.md`) | Projection formula — agent rebuilt the currency/sales CTE many times |
| local055 | chinook | `BinderException: Ambiguous reference to column "Name"` — agent kept hitting the same ambiguity without qualifying |
| local060 | complex_oracle | `InternalException: Attempted to access index 0 within vector of size 0` (DuckDB assertion) — broken CASE expression mixing INT and VARCHAR triggered a DuckDB internal crash repeatedly |
| local063 | complex_oracle | `TypeMismatchException` on `prod_src_id` (text in int column); agent kept re-casting |
| local065 | modern_data | Pizza revenue calc; agent kept reprobing `cancellation` values |
| local066 | modern_data | Pizza ingredients tally; `ParserException` on dotted column; `InternalException` later |
| local073 | modern_data | Pizza final-ingredients view; agent kept inspecting `pizza_get_exclusions` helper |
| local168 | city_legislation | Top-3 skills for Data Analyst; agent kept refining the skill-counting subquery |
| local258 | IPL (ek: `baseball_game_special_words_definition.md`) | `BinderException: Ambiguous reference to column "ball_id"` — agent kept reusing the unqualified name |
| local285 | bank_sales_trading | Vegetable wholesale analytics over 4 years; `CatalogException: veg_cat` kept recurring |
| local297 | bank_sales_trading | Monthly net + growth rate calc; ended comparing against zero-prev-balance edge case |
| local331 | log | LEAD/LAG session pattern for "third-page visits"; agent kept re-sequencing |
| local335 | f1 | "Constructors with most seasons of fewest points" — agent never escaped the driver-ranking subquery |
| local336 | f1 (ek: `f1_overtake.md`) | Multiple Catalog + Conversion errors on `lap_positions.lap` type; agent built a 22-call chain of temp tables |
| local344 | f1 (ek: `f1_overtake.md`) | `TypeMismatchException: date "2009-03-29" not float`; agent kept re-casting lap times |
| local355 | f1 | `InternalException: index 0 within vector of size 0` (DuckDB crash on broken JOIN) — appeared twice, agent couldn't diagnose |
| local356 | f1 | `ConversionException: invalid timestamp "17:05:23"` — agent kept trying to cast time column as timestamp |
| local360 | log | Pre-click counting per session; agent kept refining the landing/session boundary |

**Patterns**:
1. **DuckDB `InternalException: vector of size 0`** (local060, local355) — broken CASE/JOIN statements cause DuckDB assertion failures. The agent treats these as retryable errors but no slight rewrite fixes them.
2. **Type-mismatch loops** (local009, 010, 063, 344, 356) — columns stored as text in the SQLite source (coordinates, lap numbers, timestamps) trigger conversion errors. Agent needs to consistently `SET sqlite_all_varchar=true` and wrap with `TRY_CAST`.
3. **Catalog-prefix loops** (local034, 285) — agent forgets to prefix `<db>.main.` and keeps hitting CatalogException on the same table.
4. **True exploration loops** (local015, 040, 050, 065, 066, 073, 168, 297, 331, 335, 360) — SQL valid, agent iterating on semantic variants without ever calling `submit_result`.

**Fix direction**:
- **Commit-budget rule**: After 10 successful (non-error) SQL attempts without `submit_result`, force a submit on the best-so-far query.
- **InternalException handler**: Treat DuckDB `INTERNAL Error` as a "query is structurally broken" signal — require a schema re-read before the next attempt.
- **Type-mismatch auto-fix prompt**: When `TypeMismatchException` fires on a source-SQLite column, tell the agent to always use `TRY_CAST` and fall back to `VARCHAR`.

---

## 3. No SQL Submitted (0 questions)

Gemini 3.1 Pro eliminated this failure mode entirely — it always produces tool calls rather than hanging in a reasoning block.

---

## 4. Per-Database Performance

| Database | Correct / Total | % |
|----------|-----------------|---|
| Pagila | 2/2 | 100% |
| imdb_movies | 2/2 | 100% |
| northwind | 2/2 | 100% |
| BowlingLeague | 1/1 | 100% |
| WWE | 1/1 | 100% |
| music | 1/1 | 100% |
| city_legislation | 8/10 | 80% |
| California_Traffic_Collision | 2/3 | 67% |
| EntertainmentAgency | 2/3 | 67% |
| IPL | 7/11 | 64% |
| education_business | 3/5 | 60% |
| EU_soccer | 3/5 | 60% |
| bank_sales_trading | 8/15 | 53% |
| Baseball | 1/2 | 50% |
| complex_oracle | 3/6 | 50% |
| log | 2/5 | 40% |
| Brazilian_E_Commerce | 3/8 | 38% |
| chinook | 1/3 | 33% |
| delivery_center | 1/3 | 33% |
| E_commerce | 1/3 | 33% |
| f1 | 3/9 | 33% |
| modern_data | 2/7 | 29% |
| Airlines | 0/2 | 0% |
| AdventureWorks | 0/1 | 0% |
| electronic_sales | 0/1 | 0% |
| school_scheduling | 0/1 | 0% |
| **sqlite-sakila** | **0/7** | **0% (all infra)** |
| **Db-IMDB** | **0/5** | **0% (all infra or schema-confusion)** |

The two 0/N rows at the bottom — sqlite-sakila (0/7) and Db-IMDB (0/5) — are **12 questions locked out by the DB-attach bug**, not by agent reasoning.

---

## 5. External-Knowledge Question Summary (11 questions)

External-knowledge docs correlate with failure: **3/11 correct (27%)** vs the run-wide 47.6%.

| Instance | DB | Doc | Outcome |
|----------|------|-----|---------|
| local003 | E_commerce | RFM.md | result_mismatch (wrong thresholds) |
| local009 | Airlines | haversine_formula.md | recursion_limit (coord parse) |
| local010 | Airlines | haversine_formula.md | recursion_limit (coord parse) |
| local035 | Brazilian_E_Commerce | spherical_law.md | ✓ correct |
| local050 | complex_oracle | projection_calculation.md | recursion_limit |
| local061 | complex_oracle | projection_calculation.md | ✓ correct |
| local244 | music | music_length_type.md | ✓ correct |
| local258 | IPL | baseball_game_special_words_definition.md | recursion_limit (ambiguous ball_id) |
| local259 | IPL | baseball_game_special_words_definition.md | result_mismatch (column names) |
| local336 | f1 | f1_overtake.md | recursion_limit (type casts) |
| local344 | f1 | f1_overtake.md | recursion_limit (type casts) |

**Fix**: Inline the document text directly into the system prompt whenever `external_knowledge` is present, rather than letting the agent re-retrieve it.

---

## 6. Priority Fix List

Ordered by expected gain on this run.

| Priority | Fix | Questions Affected | Expected Gain |
|----------|-----|--------------------|---------------|
| **P0** | Fix `sqlite-sakila` + `Db-IMDB` attach so tables are visible | 9 in §2A + 1 in §1F + 2 in §2B | **+6 to +10** |
| **P1** | Commit-budget rule: after 10 clean SQL calls, force `submit_result` | 11 real doom-loops in §2C | +4 to +6 |
| **P2** | Pre-submit "restate expected output columns" rule (match gold header) | 9 in §1A + 3 missing-column cases in §1D/1E | +4 to +7 |
| **P3** | Month / date literal formatting hint (`strftime('%Y-%m')`, `monthname()`) | 2 in §1B + `local074` date | +2 to +3 |
| **P4** | Treat DuckDB `InternalException: vector of size 0` as structural error; force schema re-read | local060, local355 | +1 to +2 |
| **P5** | Inject external-knowledge doc text into system prompt | 8 failures in §5 | +2 to +4 |
| **P6** | SQLite-source type-cast prompt (`SET sqlite_all_varchar=true` + `TRY_CAST`) | local009, 010, 063, 344, 356 | +1 to +3 |
| **P7** | Fix 9 wrong-aggregation cases with per-domain formula hints | §1C | +2 to +4 |

**Conservative estimate**: P0–P3 together push the run from 59/124 (47.6%) to ~75–82/124 (60–66%).

---

## 7. Cost Analysis

### Pricing assumptions

Vertex AI **Gemini 3 Pro Preview**, standard tier, all API calls ≤200K input tokens (verified: max per-question input = 503,589 is the *sum* across ~25 turns, so each individual call stays well under 200K):

| | Price per 1M tokens |
|---|---|
| Input (text) | **$2.00** |
| Output (text + reasoning) | **$12.00** |

*Caveat*: official pricing is published for `gemini-3-pro-preview`. Our runs used the revision `gemini-3.1-pro-preview` and I've assumed identical rates; if the 3.1 revision is priced differently these numbers scale linearly.

### Total cost

| | Tokens | $ |
|---|---:|---:|
| Input | 12,353,262 | **$24.71** |
| Output | 958,180 | **$11.50** |
| **Total** | — | **$36.20** |

- **Mean cost per question**: $0.29
- **Mean cost per correct answer**: **$0.61** (59 correct / $36.20)
- **Wall-clock**: 3h 38m across 4 segments
- **Vertex stability**: only 1 hard API failure in 124 questions (`local025`, `400 INVALID_ARGUMENT`)

### Cost by outcome

Where the money went:

| Outcome | n | Input tokens | Output tokens | Time | Cost | Cost / q |
|---|---:|---:|---:|---:|---:|---:|
| Correct | 59 | 3,477,451 | 338,713 | 4,384 s | **$11.02 (30%)** | $0.187 |
| Mismatch | 30 | 2,126,279 | 251,535 | 3,088 s | **$7.27 (20%)** | $0.242 |
| Agent error | 35 | 6,749,532 | 367,932 | 5,602 s | **$17.91 (49%)** | $0.512 |

**~50% of spend went to agent_error runs that returned no result** — recursion-limit doom loops accumulate 25 AI turns of growing context. The P1 "commit budget" rule (force `submit_result` after 10 clean SQL calls) would eliminate most of this waste. Capping doom loops at, say, 12 turns should shave roughly $8–10 off a full-run bill while likely converting a handful of those into correct answers.

### Cost by database (top spenders)

| Database | Score | Cost | $ / q |
|---|---|---:|---:|
| bank_sales_trading | 8/15 (53%) | $4.91 | 0.328 |
| f1 | 3/9 (33%) | $3.98 | 0.442 |
| IPL | 7/11 (64%) | $3.63 | 0.330 |
| complex_oracle | 3/6 (50%) | $3.02 | 0.503 |
| sqlite-sakila | **0/7 (0%)** | $2.77 | 0.396 |
| modern_data | 2/7 (29%) | $2.51 | 0.358 |
| California_Traffic_Collision | 2/3 (67%) | $2.50 | 0.832 |

`sqlite-sakila` alone burned **$2.77 on zero correct answers** — cheapest fix on the priority list (P0, DB attach).

### Per-question extremes

**Most expensive single questions** (top 5):

| $ | Instance | DB | Outcome | Input | Output | Time |
|---:|---|---|---|---:|---:|---:|
| $1.053 | local015 | California_Traffic_Collision | agent_error | 503,589 | 3,844 | 94 s |
| $0.902 | local336 | f1 | agent_error | 415,801 | 5,880 | 102 s |
| $0.885 | local064 | bank_sales_trading | mismatch | 232,147 | 35,041 | 371 s |
| $0.876 | local050 | complex_oracle | agent_error | 233,269 | 34,129 | 271 s |
| $0.876 | local017 | California_Traffic_Collision | **correct** | 396,697 | 6,888 | 115 s |

**Cheapest single questions** (all under 3 cents): `local221` (EU_soccer, correct, $0.026), `local114` (education_business, correct, $0.032), `local085` (northwind, correct, $0.028).

### Projected scaling

| Scenario | Questions | Cost estimate |
|---|---:|---:|
| This run (partial local track) | 124 | **$36.20** |
| Full local track | 135 | ~$39.40 |
| Full Spider 2.0-lite (547 questions) | 547 | ~$160 |
| 5× repeat runs for variance | 124 × 5 | ~$181 |
| After P1 (commit-budget) fix | 124 | ~$26–28 (−25%) |

Cheap enough to run end-to-end weekly without budget concerns, but worth throttling doom loops if you plan to sweep configurations.

### Latency

- **Mean**: 105 s / q
- **p50**: ~85 s (correct answers cluster around 40–90 s)
- **p99**: 479 s (`local064`, bank_sales_trading — 21 agent steps before submitting the wrong scalar)
- **Min**: 9 s (`local221`, EU_soccer)

---

## 8. Re-run Snippet

```python
import csv, glob
from collections import Counter, defaultdict

RUN_DATE = '20260416'
files = sorted(glob.glob(f'results/spider2_results_{RUN_DATE}_*.csv'))
seen = {}
for f in files:
    with open(f, encoding='utf-8') as fp:
        for r in csv.DictReader(fp):
            seen[r['instance_id']] = r  # later runs win on re-try

rows = list(seen.values())

# Overall
outcomes = Counter()
for r in rows:
    sd = r['score_detail']
    if sd.startswith('matches'): outcomes['correct'] += 1
    elif sd.startswith('result_mismatch'): outcomes['mismatch'] += 1
    elif sd.startswith('agent_error'): outcomes['agent_error'] += 1
    else: outcomes[sd] += 1
print(dict(outcomes))

# Per-db
by_db = defaultdict(lambda: [0, 0])
for r in rows:
    by_db[r['db']][1] += 1
    if r['score'] == '1':
        by_db[r['db']][0] += 1
for db, (c, t) in sorted(by_db.items(), key=lambda x: -x[1][1]):
    print(f'{db}: {c}/{t}')

# Agent-error diagnosis
for r in rows:
    if r['score_detail'].startswith('agent_error'):
        cat = r.get('error_category', '')
        steps = r.get('n_agent_steps', '')
        print(f"{r['instance_id']:10} {r['db']:30} cat={cat:20} steps={steps}")
```
