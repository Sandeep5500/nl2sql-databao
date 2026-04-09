# Bug 4 — result_mismatch Deep Dive
## Spider 2.0 Local SQLite Benchmark · Run 4 (Qwen3-32B-AWQ · 124 questions)

**Total result_mismatch: 54 / 124 questions (43.5%)**

Failures are classified into 9 overlapping buckets. Each question can belong to more than one bucket (the first-listed bucket is the primary cause).

---

## Bucket Summary

| ID | Name | Count | Fixable without model change? |
|----|------|-------|-------------------------------|
| B1 | Incomplete transformation (stops before final step) | 5 | ✅ Prompt rule |
| B2 | Wrong output format / grain | 4 | ✅ Prompt + PIVOT hint |
| B3 | Missing zero/absent entities (LEFT JOIN omitted) | 3 | ✅ Prompt rule |
| B4 | Window / running aggregate logic wrong | 9 | ⚠️ Partial (prompt helps, model cap for hard cases) |
| B5 | Wrong literal / enum in filter → empty result | 9 | ✅ DCE enrichment (sample values) |
| B6 | DuckDB dialect / extension error | 5 | ✅ DUCKDB_HINTS update |
| B7 | Trivially wrong SQL (ignores core requirement) | 7 | ⚠️ Prompt rule (model cap for complex) |
| B8 | Multi-step aggregation collapsed to partial answer | 23 | ⚠️ Partial (model capability) |
| B9 | Result too large (unfiltered, hits 1000-row cap) | 4 | ✅ Prompt rule |

*Total across buckets = 69 (instances can appear in multiple buckets)*

---

## B1 — Incomplete Transformation
**Definition:** Agent writes SQL that correctly retrieves intermediate data, but omits the final transformation the question requires (percentage, ratio, which-month, combined ranking).

**Fix:** Add to system prompt:
> *"After writing SQL, re-read every clause of the question. Verify: if the question asks for a percentage/ratio, ensure you divide; if it asks 'which X', ensure you return a single identified value, not the full table."*

| Instance | DB | Result | Error | Expected |
|----------|----|--------|-------|----------|
| local041 | modern_data | 1 row | `SELECT COUNT(*) WHERE boroname='Bronx' AND health='Good'` — counts, no division | `100.0 * COUNT(*) FILTER (WHERE health='Good') / COUNT(*)` |
| local064 | bank_sales_trading | 1 row | Monthly balance CTE correct; final SELECT collapses to "which month" answer, not the balance table | Need `SELECT month, COUNT(*) ... HAVING balance > 0` then find MAX month |
| local078 | bank_sales_trading | 20 rows | Returns top-20 by rank (all same direction); gold wants top-10 highest AND bottom-10 lowest combined | Need dual ROW_NUMBER (DESC for top-10, ASC for bottom-10) then UNION |
| local157 | bank_sales_trading | 1000 rows | Volume cleaning CTE correct; date filter applied in CTE only, not propagated to final SELECT | Move `WHERE market_date BETWEEN '2021-08-01' AND '2021-08-10'` to final SELECT |
| local299 | bank_sales_trading | 4 rows | Running balance window function correct; returns all days per customer instead of MAX per customer | Add outer `SELECT customer_id, MAX(running_balance) AS max_balance GROUP BY customer_id` |

---

## B2 — Wrong Output Format / Grain
**Definition:** SQL executes cleanly and retrieves correct underlying data, but returns it in the wrong shape (long vs. wide pivot, wrong grouping level, too many rows per entity).

**Fix:** Add to DUCKDB_HINTS:
```sql
-- Pivot long→wide: use DuckDB native PIVOT
PIVOT (SELECT year, month, count FROM t)
ON year IN (2016, 2017, 2018)
USING SUM(count)
GROUP BY month
```
> *"If the question says 'each column represents X' or asks for a side-by-side comparison, use PIVOT to produce wide format."*

| Instance | DB | Result | Error | Expected |
|----------|----|--------|-------|----------|
| local028 | Brazilian_E_Commerce | 25 rows | Returns `(month_year, count)` long format | Wide pivot: `(month, 2016, 2017, 2018)` — 12 rows |
| local141 | AdventureWorks | 163 rows | `ON s.businessentityid = s.businessentityid` — self-join; returns raw rows | Needs `GROUP BY salesperson, year` with `SUM(sales) - quota` |
| local258 | IPL | 312 rows | Returns one row per bowler with all stats; no ranking/filtering applied | Gold wants top-N or a specific ranked output |
| local309 | f1 | 68 rows | Returns one row per year×driver and year×constructor separately | Gold wants exactly 1 row per year with `driver_name, constructor_name` as two columns |

---

## B3 — Missing Zero/Absent Entities
**Definition:** Agent uses INNER JOIN where LEFT JOIN (or CROSS JOIN + LEFT JOIN) is needed, causing entities with zero counts to be silently dropped. The question explicitly says "including those with zero" or "all X".

**Fix:** Add to system prompt:
> *"If the question says 'including zero', 'all X', or asks for the minimum/fewest, start with all entities using LEFT JOIN or a base set, then count matches. Never use INNER JOIN for this pattern."*

| Instance | DB | Result | Error | Expected |
|----------|----|--------|-------|----------|
| local219 | EU_soccer | 16 rows (wrong values) | `INNER JOIN Team ON match.home_team_api_id = t.team_api_id OR away...` — teams with 0 wins excluded | Generate all teams from Team table → LEFT JOIN win counts → include zero-win teams |
| local283 | EU_soccer | 1000 rows | Computes points only for home_team_api_id; away team contributions missing | UNION ALL home + away perspectives; correct champion needs both |
| local133 | EntertainmentAgency | 20 rows | Weighted score only for styles present in Musical_Preferences; zero-preference styles absent | Start from Musical_Styles, LEFT JOIN preferences, COALESCE score to 0 |

---

## B4 — Window / Running Aggregate Logic Wrong
**Definition:** The question requires cumulative sums, LAG comparisons, date-windowed aggregation, or running balances. The agent uses the correct window function syntax but gets the framing, partition, or final aggregation wrong.

**Fix:** Add to DUCKDB_HINTS:
```sql
-- Running balance (cumulative sum over ordered rows):
SUM(amount) OVER (PARTITION BY customer_id ORDER BY txn_date
                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)

-- Previous month comparison (LAG):
LAG(balance, 1) OVER (PARTITION BY customer_id ORDER BY month_start)

-- Month-end balance (all transactions up to last day of month):
DATE_TRUNC('month', txn_date) + INTERVAL '1 month' - INTERVAL '1 day' AS month_end
```

| Instance | DB | Result | Error | Expected |
|----------|----|--------|-------|----------|
| local064 | bank_sales_trading | 1 row | `SUM(deposit) - SUM(withdrawal) GROUP BY customer, month` collapses all months; strftime on DATE may return NULL | `DATE_TRUNC('month', txn_date::DATE)` for grouping; then COUNT customers with positive balance per month |
| local068 | city_legislation | 4 rows | Cumulative running total per month across years — CASE WHEN month name is computed before EXTRACT(YEAR) causing wrong partitioning | Need `SUM(count) OVER (PARTITION BY month_name ORDER BY year)` for cumulative |
| local072 | city_legislation | 1 row | Consecutive-days streak with LAG: identifies the streak correctly but % calculation uses wrong base (total rows not total days) | `percentage = streak_length / 31.0 * 100` for January |
| local298 | bank_sales_trading | 3 rows | Previous month total balance: `GREATEST(cumulative_balance, 0)` applied per-customer not aggregate; grouping creates wrong month windows | `SUM(GREATEST(running_balance, 0))` across all customers per month, not per customer |
| local299 | bank_sales_trading | 4 rows | Running balance WINDOW correct; returns all days instead of max per customer per day | Outer `SELECT customer_id, txn_date, MAX(running_balance) GROUP BY customer_id, txn_date` |
| local302 | bank_sales_trading | 1 rows | `reference_date - 7` used as start of "after" window — should be `reference_date + INTERVAL '1 day'` to `reference_date + 12*7` | Fix: before = `[ref - 12*7, ref - 1]`; after = `[ref + 1, ref + 12*7]` |
| local020 | IPL | 1 row | JOIN across ball_by_ball + batsman_scored + extra_runs simultaneously — Cartesian explosion doubles/triples run counts | Compute runs from ball_by_ball only; wickets from wicket_taken; exclude `kind_out IN ('run out', 'retired hurt')` |
| local023 | IPL | 5 rows (wrong) | `AVG(bs.runs_scored + er.extra_runs)` — extra_runs joined at ball level inflates per-player averages | Sum runs per player per match first, then AVG across matches; extra_runs are team-level not player-level |
| local062 | complex_oracle | 10 rows (wrong) | NTILE(10) applied before profit GROUP BY; profit formula references `cost` column that may not exist | `(quantity_sold * (list_price - cost))` — check column name is `prod_list_price` and `prod_cost` in this schema |

---

## B5 — Wrong Literal / Enum in Filter → Empty Result
**Definition:** SQL structure is logically correct but uses wrong string/value for a WHERE filter. The actual data uses different codes, case, or date formats. This almost always produces empty result because nothing matches.

**Root cause:** DCE enrichment doesn't include sample values for categorical/code columns, so the model guesses.

**Fix:** Re-run the DCE critique pass (`experiment_critique_enrich.py`) on these specific tables/columns to add sample values and enum meanings to column descriptions.

| Instance | DB | Error | Actual format needed |
|----------|----|-------|---------------------|
| local015 | California_Traffic_Collision | `party_safety_equipment_1 = 'helmet used'` | Actual values are single-char codes (e.g. `'E'` = helmet) — needs sample values in DCE |
| local019 | WWE | `m.title_change = 0` and `p.name = 'NXT'` | Promotions table may not have an `NXT` row; title_change encoding unknown |
| local039 | Pagila | `'%-%%'` in LIKE — escaping wrong in DuckDB (use `'%-%'` not `'%-%%'`) | DuckDB LIKE doesn't need `%%` to escape %; use `'%-%'` for hyphen-containing cities |
| local114 | education_business | `web_orders`, `web_accounts`, `web_sales_reps` tables don't exist | Table names in education_business DB don't match; DCE has no web_ tables described |
| local130 | school_scheduling | `ClassStatus = 2` for "completed" | Actual completion value unknown; DCE description says nothing about ClassStatus enum |
| local167 | city_legislation | `lt.term_end = 'December, 31'` — wrong date format | term_end is stored as ISO date (`YYYY-MM-DD`); filter should be `EXTRACT(MONTH FROM term_end::DATE) = 12 AND EXTRACT(DAY FROM term_end::DATE) = 31` |
| local212 | delivery_center | `delivery_status = 'DELIVERED'` and `order_status = 'DELIVERED'` | Actual status values unknown; DCE doesn't include sample values for status columns |
| local354 | f1 | `f1.main.drives` does not exist | Table is `f1.main.driver_standings` or similar; model guessed table name |
| local358 | log | `AGE(CURRENT_DATE, birth_date)` — uses today (2026-04-08) as reference | All users born in 1970s–1990s would appear as 36–56 year olds; reference date should be fixed to match gold |

---

## B6 — DuckDB Dialect / Extension Error
**Definition:** The model uses SQLite functions, spatial extensions, or incorrect DuckDB syntax. Often produces empty result or runtime error.

**Fix:** Extend DUCKDB_HINTS with:
```python
DUCKDB_HINTS += """
- The spatial extension is NOT available. Implement haversine as pure arithmetic:
    2 * ASIN(SQRT(POWER(SIN(RADIANS(lat2-lat1)/2),2) +
             COS(RADIANS(lat1)) * COS(RADIANS(lat2)) * POWER(SIN(RADIANS(lon2-lon1)/2),2))) * 6371
- Median: use PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY col), not AVG
- LIKE escaping: use '%-%' to find hyphen in string (no need to escape %)
- UNNEST of string: STRING_SPLIT(col, ',') returns list; UNNEST wraps it — verify topping_id type matches join
- Do NOT use: LOAD spatial, JULIAN(), DATE(), INTERVAL MINUTE TO SECOND cast
"""
```

| Instance | DB | Wrong function/syntax | Correct DuckDB alternative |
|----------|----|----------------------|---------------------------|
| local010 | Airlines | `LOAD spatial;` — extension not installed, returns empty | Pure arithmetic haversine: `2 * ASIN(SQRT(...)) * 6371` |
| local019 | WWE | `TRY_CAST(REGEXP_MATCHES(...) AS INTERVAL MINUTE TO SECOND)` — invalid | `INTERVAL (minutes * 60 + seconds) SECONDS` or parse with `SPLIT_PART` |
| local039 | Pagila | `'%-%%'` — `%%` is not LIKE escape in DuckDB | Use `'%-%'` — single `%` is wildcard, no escaping needed |
| local066 | modern_data | `TRIM(t.topping_id)` after STRING_SPLIT returns strings; JOIN to toppings.topping_id (INTEGER) fails silently | `CAST(TRIM(t.topping_id) AS INTEGER)` before join |
| local218 | EU_soccer | `AVG(max_goals)` used instead of `MEDIAN` | `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY max_goals)` |

---

## B7 — Trivially Wrong SQL (Ignores Core Requirement)
**Definition:** The agent submits SQL that is syntactically correct and runs without error, but fundamentally ignores the main requirement of the question. Often an exploratory query or stub.

**This is the clearest signal of model capability ceiling** — the model couldn't formulate the core algorithm and retreated to a simpler query.

**Fix:** Prompt rule: *"If you cannot write the exact SQL immediately, use search_context to explore the schema first. Never submit a query that only returns counts or raw rows when the question asks for calculations."*

| Instance | DB | Result | What the model submitted | What was needed |
|----------|----|--------|--------------------------|-----------------|
| local035 | Brazilian_E_Commerce | 1 row | `SELECT COUNT(*) FROM olist_geolocation WHERE lat IS NOT NULL` | Self-join on sorted rows with LAG to find two consecutive cities with max lat/lng distance |
| local081 | northwind | 10 rows | `SELECT orderid, orderdate FROM orders WHERE year=1998 LIMIT 10` | `SUM(unit_price * quantity * (1-discount)) GROUP BY customer_id` then rank |
| local141 | AdventureWorks | 163 rows | `JOIN sp ON s.id = s.id` (self-join bug) returns all raw rows | `GROUP BY salesperson, year` computing `SUM(sales) - quota` |
| local168 | city_legislation | 1 row | `SELECT job_title_short, COUNT(*) WHERE job_title_short='Data Analyst'` | Filter to remote Data Analyst jobs → get top-3 skill sets → avg salary for those skill sets |
| local201 | modern_data | 996 rows | `SELECT words WHERE length BETWEEN 4 AND 5 AND words LIKE 'r%'` | Self-join: `WHERE ARRAY_SORT(SPLIT(w1,'')) = ARRAY_SORT(SPLIT(w2,''))` for anagram detection |
| local301 | bank_sales_trading | 5 rows | `SELECT DISTINCT week_number FROM weekly_sales WHERE month=6` | Average weekly sales 4 weeks before mid-June vs 4 weeks after, % change per region/platform/etc. |
| local336 | f1 | 1000 rows | `SELECT race_id, driver_id, lap, position, LAG(position)...` — raw lap positions | Count position changes by category (retirement/pit/start/track-pass) across first 5 laps |

---

## B8 — Multi-Step Aggregation Collapsed to Partial Answer
**Definition:** The question requires 2–4 sequential aggregation steps (e.g., find top-N per group, then aggregate those results). The model builds one or two CTEs correctly but the final SELECT applies the wrong level of aggregation or misses a step.

**This is the dominant failure mode (23/54 = 43%).** It is primarily a model capability issue — larger or more capable models handle multi-step reasoning better. Prompt improvements can recover some easy cases.

**Fix (partial):** Add to system prompt:
> *"For questions requiring multiple aggregation steps, write one CTE per step. Before submitting, trace through each CTE manually: CTE1 → CTE2 → ... → final SELECT. Verify the final SELECT operates on the output of the last CTE, not the raw tables."*

| Instance | DB | Result | Missing step | 
|----------|----|--------|-------------|
| local021 | IPL | 1 row | Finds strikers with >50 runs in ANY match; then AVGs per-ball runs not per-match totals |
| local024 | IPL | 5 rows | Computes per-player avg correctly; then averages across players, not within country-level grouping |
| local029 | Brazilian_E_Commerce | 3 rows | Top-3 by customer_unique_id correct; avg payment join creates duplicates due to multiple orders |
| local031 | Brazilian_E_Commerce | 3 rows | Finds lowest-annual-volume year; but inner query for highest monthly uses wrong year boundary |
| local034 | Brazilian_E_Commerce | 74 rows | Gets most-preferred payment type per category; then count of that type is wrong (includes other types) |
| local037 | Brazilian_E_Commerce | 3 rows | Gets most-used payment type per category; ranking of categories by that type's count is inverted |
| local055 | chinook | 2 rows | Max/min artist found correctly; ratio (max_sales / min_sales) computed but value wrong |
| local059 | education_business | 3 rows | Top-3 products per division correct; then AVG is taken across divisions not within |
| local063 | complex_oracle | 1 row | Q4 sales increase filter correct; final product ranking drops the city filter |
| local065 | modern_data | 1 row | Base pizza price correct; extras comma-string parsing misses some extra toppings |
| local066 | modern_data | 12 rows | STRING_SPLIT for recipe ingredients correct; CAST to INTEGER for join fails silently → wrong totals |
| local072 | city_legislation | 1 row | Consecutive-day streak identified; % of January days calculated with wrong denominator |
| local132 | EntertainmentAgency | 12 rows | First style match correct; second style match join condition too loose (OR instead of AND) |
| local163 | education_business | 8 rows | Salary diff from rank average computed; returns ALL faculty sorted by diff, not just "closest" (MIN per rank) |
| local202 | city_legislation | 5 rows | Top-10 states by alien population correct; age > 200 filter references non-existent column |
| local209 | delivery_center | 1 row | Top store by order count correct; deliveries ratio join wrong → ratio off |
| local218 | EU_soccer | 1 row | Max season goals per team correct; then uses AVG not MEDIAN |
| local244 | music | 3 rows | Duration classification correct; revenue join uses UnitPrice from Track not InvoiceLine.UnitPrice |
| local258 | IPL | 312 rows | Wickets + economy per bowler computed; no ranking applied; returns all 312 bowlers |
| local310 | f1 | 3 rows | Max driver points from `results` correct; max constructor points queried from `constructor_standings` not `results` |
| local335 | f1 | 5 rows | Constructor points per season correct; ranking finds bottom-most seasons but direction inverted |
| local020 | IPL | 1 row | Bowling avg: JOIN to batsman_scored inflates runs; also missing `NOT IN ('run out', 'retired hurt')` |
| local023 | IPL | 5 rows | Extra_runs joined at ball level inflates player averages |

---

## B9 — Result Too Large (Unfiltered / Hits 1000-Row Cap)
**Definition:** LighthouseExecutor caps query results at 1000 rows. The agent generates SQL that returns the full table instead of the aggregated/filtered result the question requires.

**Fix:** Add to system prompt:
> *"Your query result is capped at 1000 rows. If your expected result is a ranked or aggregated list (top-N, grouped stats), ensure GROUP BY + LIMIT is in the final SELECT. Never submit a raw table scan as the answer."*

| Instance | DB | Rows | What was returned | What was needed |
|----------|----|------|-------------------|-----------------|
| local157 | bank_sales_trading | 1000 | All tickers × all dates with % change | Only Aug 1–10 2021 (10 days × N tickers ≈ ~40 rows) |
| local201 | modern_data | 996 | Raw word list filtered by length+letter | 10 anagram pairs with count |
| local283 | EU_soccer | 1000 | All matches with home team points (no GROUP BY champion) | 1 champion team per season per league |
| local336 | f1 | 1000 | Raw lap_positions with LAG | 4 overtake category counts (retirements / pit / start / track) |

---

## Cross-Bucket Impact Matrix

Questions in **both B4 and B8** (running aggregates + multi-step collapse) are the hardest — they need the model to chain multiple window function stages correctly:

- **local020** (IPL bowling avg): B4 + B8 — wrong JOIN inflates numerator AND wrong exclusion
- **local064** (bank month-end): B1 + B4 — balance CTE correct, final SELECT wrong level
- **local072** (city consecutive days): B4 + B8 — streak correct, % denominator wrong
- **local299** (bank daily running): B1 + B4 — window correct, outer aggregation missing

---

## Actionable Fix Priority

| Priority | Action | Questions Recoverable | Effort |
|----------|--------|-----------------------|--------|
| 1 | **DCE critique pass** on California, school_scheduling, Pagila, delivery_center, city_legislation tables with categorical columns | B5: ~5–7 questions | Low — run `experiment_critique_enrich.py` per DB |
| 2 | **DUCKDB_HINTS** additions: haversine formula, PERCENTILE_CONT, PIVOT syntax, LIKE escaping, STRING_SPLIT CAST | B6: 4–5 questions | Low — edit `spider2_benchmark.py` |
| 3 | **System prompt rules**: re-read question, LEFT JOIN for zero-entities, cap check | B1: 3–4, B3: 2–3, B9: 2–3 questions | Low — edit `spider2_benchmark.py` |
| 4 | **Model upgrade** to Qwen2.5-Coder-32B or Claude Sonnet | B7: 4–5, B8: 8–12 questions | Medium — infra change |
| 5 | **f1/bank_sales_trading DCE enrichment** — add domain hints for financial/racing query patterns | B4 subset: 3–4 questions | Medium |

**Estimated recovery from priorities 1–3 alone (no model change): +14–20 questions**
**Estimated recovery from priority 4 (model upgrade): additional +15–25 questions**
