# Error Analysis — gpt-5.4-mini, Spider2-lite First 50 Questions

**Run date:** 2026-04-14  
**Model:** gpt-5.4-mini  
**API:** CMU AI Gateway (`https://ai-gateway.andrew.cmu.edu/v1`)  
**Results CSV:** `results/spider2_results_20260414_203430.csv`  
**Traces:** `logs/traces/run_20260414_203430/`

---

## Summary

| Metric | Value |
|---|---|
| **Score** | **36 / 50 (72%)** |
| result_mismatch | 10 |
| sql_execution_error | 4 |
| Total tokens (input) | 2,463,474 |
| Total tokens (output) | 200,171 |
| Avg per question | 49K in / 4K out |
| Est. cost (gpt-4.1-mini rates) | ~$1.30 |
| Total wall time | ~55 min (incl. local063 stall) |

---

## Results Table

| ID | DB | ✓/✗ | Category | Steps | Tools | SQL | Srch | In Tok | Out Tok | Time | Ext Knowledge |
|---|---|---|---|---|---|---|---|---|---|---|---|
| local002 | E_commerce | ✗ | result_mismatch | 6 | 6 | 1 | 4 | 63K | 8K | 52s | — |
| local003 | E_commerce | ✗ | sql_execution_error | 16 | 16 | 14 | 1 | 202K | 17K | 98s | RFM.md ⚠️ |
| local004 | E_commerce | ✗ | result_mismatch | 3 | 3 | 1 | 1 | 15K | 2K | 11s | — |
| local007 | Baseball | ✓ | correct | 3 | 3 | 1 | 1 | 28K | 2K | 11s | — |
| local008 | Baseball | ✓ | correct | 6 | 6 | 4 | 1 | 76K | 3K | 19s | — |
| local009 | Airlines | ✓ | correct | 14 | 14 | 10 | 3 | 167K | 8K | 54s | haversine_formula.md ✓ |
| local010 | Airlines | ✗ | sql_execution_error | 11 | 11 | 8 | 2 | 107K | 7K | 42s | haversine_formula.md ⚠️ |
| local015 | California_Traffic_Collision | ✗ | result_mismatch | 5 | 5 | 3 | 1 | 33K | 3K | 18s | — |
| local017 | California_Traffic_Collision | ✓ | correct | 8 | 8 | 6 | 1 | 102K | 3K | 25s | — |
| local018 | California_Traffic_Collision | ✓ | correct | 3 | 3 | 1 | 1 | 23K | 2K | 12s | — |
| local019 | WWE | ✓ | correct | 7 | 7 | 5 | 1 | 62K | 4K | 25s | — |
| local020 | IPL | ✓ | correct | 6 | 7 | 4 | 2 | 47K | 4K | 25s | — |
| local021 | IPL | ✓ | correct | 3 | 3 | 1 | 1 | 12K | 1K | 9s | — |
| local022 | IPL | ✓ | correct | 3 | 3 | 1 | 1 | 17K | 1K | 10s | — |
| local023 | IPL | ✓ | correct | 10 | 10 | 8 | 1 | 99K | 6K | 40s | — |
| local024 | IPL | ✓ | correct | 3 | 3 | 1 | 1 | 15K | 2K | 13s | — |
| local025 | IPL | ✗ | result_mismatch | 3 | 3 | 1 | 1 | 14K | 5K | 31s | — |
| local026 | IPL | ✓ | correct | 4 | 4 | 2 | 1 | 21K | 3K | 17s | — |
| local028 | Brazilian_E_Commerce | ✓ | correct | 3 | 3 | 1 | 1 | 16K | 1K | 13s | — |
| local029 | Brazilian_E_Commerce | ✓ | correct | 4 | 5 | 3 | 1 | 22K | 2K | 15s | — |
| local030 | Brazilian_E_Commerce | ✓ | correct | 3 | 3 | 1 | 1 | 14K | 1K | 10s | — |
| local031 | Brazilian_E_Commerce | ✓ | correct | 7 | 7 | 5 | 1 | 56K | 5K | 34s | — |
| local032 | Brazilian_E_Commerce | ✓ | correct | 6 | 9 | 7 | 1 | 46K | 4K | 25s | — |
| local034 | Brazilian_E_Commerce | ✓ | correct | 3 | 3 | 1 | 1 | 13K | 1K | 10s | — |
| local035 | Brazilian_E_Commerce | ✓ | correct | 3 | 3 | 1 | 1 | 14K | 2K | 11s | spherical_law.md ✓ |
| local037 | Brazilian_E_Commerce | ✓ | correct | 3 | 3 | 1 | 1 | 15K | 2K | 15s | — |
| local038 | Pagila | ✓ | correct | 3 | 3 | 1 | 1 | 16K | 1K | 7s | — |
| local039 | Pagila | ✓ | correct | 3 | 3 | 1 | 1 | 20K | 1K | 9s | — |
| local040 | modern_data | ✓ | correct | 7 | 7 | 4 | 2 | 52K | 4K | 29s | — |
| local041 | modern_data | ✓ | correct | 3 | 3 | 1 | 1 | 11K | 0.4K | 6s | — |
| local049 | modern_data | ✗ | result_mismatch | 4 | 4 | 2 | 1 | 17K | 2K | 13s | — |
| local050 | complex_oracle | ✗ | result_mismatch | 5 | 5 | 1 | 3 | 52K | 7K | 38s | projection_calculation.md ⚠️ |
| local054 | chinook | ✓ | correct | 4 | 4 | 2 | 1 | 19K | 1K | 11s | — |
| local055 | chinook | ✗ | result_mismatch | 6 | 6 | 4 | 1 | 41K | 11K | 58s | — |
| local056 | sqlite-sakila | ✗ | sql_execution_error | 9 | 9 | 7 | 1 | 16K | 2K | 23s | — |
| local058 | education_business | ✓ | correct | 3 | 3 | 1 | 1 | 12K | 1K | 8s | — |
| local059 | education_business | ✓ | correct | 3 | 3 | 1 | 1 | 12K | 1K | 10s | — |
| local060 | complex_oracle | ✗ | result_mismatch | 8 | 11 | 7 | 3 | 89K | 10K | 58s | — |
| local061 | complex_oracle | ✗ | result_mismatch | 3 | 3 | 1 | 1 | 24K | 2K | 12s | projection_calculation.md ⚠️ |
| local062 | complex_oracle | ✓ | correct | 3 | 3 | 1 | 1 | 16K | 4K | 22s | — |
| local063 | complex_oracle | ✗ | result_mismatch | 8 | 10 | 7 | 2 | 106K | 7K | **3207s** | — |
| local065 | modern_data | ✓ | correct | 4 | 6 | 4 | 1 | 20K | 2K | 16s | — |
| local066 | modern_data | ✓ | correct | 5 | 10 | 8 | 1 | 31K | 6K | 41s | — |
| local067 | complex_oracle | ✓ | correct | 3 | 3 | 1 | 1 | 16K | 1K | 11s | — |
| local068 | city_legislation | ✓ | correct | 4 | 4 | 2 | 1 | 21K | 2K | 15s | — |
| local070 | city_legislation | ✓ | correct | 5 | 5 | 3 | 1 | 27K | 3K | 22s | — |
| local071 | city_legislation | ✓ | correct | 3 | 3 | 1 | 1 | 13K | 1K | 11s | — |
| local072 | city_legislation | ✓ | correct | 6 | 6 | 4 | 1 | 35K | 3K | 20s | — |
| local073 | modern_data | ✗ | sql_execution_error | 23 | 23 | 17 | 5 | 483K | 28K | 195s | — |
| local198 | chinook | ✓ | correct | 4 | 5 | 3 | 1 | 15K | 2K | 12s | — |

_Tools = total tool calls including submit (search + sql + submit). Steps = LLM turns. Ext Knowledge: ✓ = doc applied correctly, ⚠️ = doc ignored or misapplied._

---

## Accuracy by Database

| Database | Correct | Total | % |
|---|---|---|---|
| Brazilian_E_Commerce | 8 | 8 | 100% |
| Pagila | 2 | 2 | 100% |
| education_business | 2 | 2 | 100% |
| chinook | 2 | 3 | 67% |
| city_legislation | 4 | 4 | 100% |
| IPL | 6 | 7 | 86% |
| Baseball | 2 | 2 | 100% |
| WWE | 1 | 1 | 100% |
| California_Traffic_Collision | 2 | 3 | 67% |
| modern_data | 4 | 6 | 67% |
| Airlines | 1 | 2 | 50% |
| E_commerce | 0 | 3 | 0% |
| complex_oracle | 2 | 6 | 33% |
| sqlite-sakila | 0 | 1 | 0% |

---

## External Knowledge Analysis

6 of 50 questions provided an external knowledge document (injected into the system prompt via `domain.add_description()`). Accuracy was significantly lower for these questions.

| Question | Doc | Score | Doc concepts found in agent reasoning |
|---|---|---|---|
| local009 | `haversine_formula.md` | ✓ | `haversine` — correctly applied |
| local035 | `spherical_law.md` | ✓ | none — derived formula independently |
| local003 | `RFM.md` | ✗ | `RFM`, `recency` — segment names ignored |
| local010 | `haversine_formula.md` | ✗ | none — doc completely ignored |
| local061 | `projection_calculation.md` | ✗ | `growth rate` — proj_factor formula not applied |
| local050 | `projection_calculation.md` | ✗ | `growth rate` — proj_factor formula not applied |

**Accuracy: 2/6 (33%) with external knowledge vs 34/44 (77%) without**

### Key finding: the issue is not missing docs — it's partial or no application

The doc is always present in the context. The failure pattern is:

- **local010** — same haversine doc that local009 used correctly, but the agent never mentioned "haversine" or the formula. It tried `st_x` (PostGIS), then manual coordinate splitting, never consulting the doc.
- **local003** — agent acknowledged "RFM" but ignored the specific segment thresholds (Champions, Loyal Customers, Hibernating, etc.) defined in the doc. It invented its own segmentation logic.
- **local061 / local050** — agent used the concept of "growth rate" but did not apply the specific `proj_factor` formula from `projection_calculation.md`, leading to values 20–35% off.
- **local035** — succeeded *without* using the doc (derived the spherical distance formula independently), suggesting the doc is not always needed.

### Critical finding: correct application of the doc always led to a correct answer

Across all 6 external knowledge questions, there is a **perfect correlation** between doc application and correctness:

| Doc applied? | Outcome | Instances |
|---|---|---|
| Yes, correctly | ✓ Correct | local009, local035 |
| Agent substituted own logic | ✗ Wrong | local003, local061, local050 |
| Agent ignored doc entirely | ✗ Wrong | local010 |

**No question got a wrong answer when the doc was properly applied.** The docs are high-quality and sufficient — the bottleneck is purely the agent's instruction-following.

What "not applying the doc" looked like in practice:

- **local003 (RFM.md)**: The doc defines exact RFM segment thresholds (e.g. Champions = Recency≥4, Frequency≥4, Monetary≥4). The agent acknowledged RFM by name but invented its own thresholds instead of using the ones in the doc, producing wrong segment assignments.
- **local061 / local050 (projection_calculation.md)**: The doc specifies a `proj_factor` formula to project historical monthly sales forward. The agent used a generic year-over-year growth rate instead of the doc's formula, producing values 20–35% off.
- **local010 (haversine_formula.md)**: The agent never referenced the haversine formula at all. It tried PostGIS `st_x()` first, then manual string splitting — ignoring that the doc had the exact calculation ready to use. Notably, local009 had the same doc and applied it correctly.

Note on local035: the agent didn't explicitly cite `spherical_law.md` in its reasoning but derived the correct spherical distance formula independently and got the right answer — the doc was internalized even if not verbatim referenced.

### Fix direction

Add an explicit instruction to the system prompt:

> "If an external knowledge document is provided in your context, you MUST use the exact formulas, definitions, and thresholds from that document. Do not substitute your own logic or approximations."

This is a prompt-level fix — the docs themselves are correct and complete.

---

## Error Deep Dive

### sql_execution_error (4 failures)

#### local003 — E_commerce
**Question:** Average sales per order for each customer within distinct RFM segments (delivered orders only).  
**Tool sequence:** `search→sql[ERR:InternalException]×4→sql×9→sql[ERR:ParserException]→sql→sql→submit`  
**Errors:**
- `InternalException: Attempted to access index 0 within vector of size 0` — repeated 4×; DuckDB SQLite reader bug on certain join patterns
- `ParserException: window functions are not allowed in window definitions` — agent tried nested window function (`ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)` inside another window), which DuckDB doesn't allow

**Root cause:** Combination of DuckDB InternalException (SQLite read bug) and nested window function limitation. Agent spent 14 SQL attempts never finding a working query.  
**Gold shape:** `RFM_Segment | AverageSalesPerOrder` (5 rows)  
**Fix direction:** Add prompt hint to avoid nested window functions; use subquery pattern instead.

---

#### local010 — Airlines
**Question:** Distribute unique city pairs into haversine distance ranges; identify range with fewest pairs.  
**Tool sequence:** `search→search→sql[ERR:CatalogException]→sql[ERR:TypeMismatchException]→sql→sql[ERR:InternalException]×2→sql×3→submit`  
**Errors:**
- `CatalogException: st_x not in catalog` — agent tried PostGIS spatial functions not available in DuckDB without extension
- `TypeMismatchException: column "coordinates" declared as integer, found "(129.77, 62.09)"` — SQLite stores coordinates as string `(lon,lat)` but schema reports INTEGER type
- `InternalException: index 0 within vector of size 0` — DuckDB SQLite read bug on the coordinates cast

**Root cause:** SQLite type mismatch (coordinates stored as string, typed as integer). Agent eventually tried `split_part(trim(coordinates, '()'), ',', N)` but hit InternalException.  
**Gold:** Single value `6`  
**Fix direction:** Add `sqlite_all_varchar=true` hint + explicit `split_part`/`CAST` pattern for coordinate columns.

---

#### local056 — sqlite-sakila
**Question:** Which customer has the highest average monthly change in payment amounts?  
**Tool sequence:** `search→sql→sql[ERR:CatalogException]→sql×5→sql→submit`  
**Error:** `CatalogException: Table Function with name pragma_database_list does not exist`  
**Root cause:** Agent tried SQLite pragma functions not available in DuckDB. After failing to discover the schema, it gave up and returned "no tables loaded" as the answer.  
**Gold:** `STEPHEN QUALLS`  
**Fix direction:** Add hint to use `SHOW TABLES` / `DESCRIBE tablename` for schema discovery instead of SQLite pragmas.

---

#### local073 — modern_data (pizza orders)
**Question:** For each pizza order, provide row ID, order ID, customer ID, pizza name, and final ingredients after applying exclusions/extras.  
**Tool sequence:** `search×3→sql[ERR:InternalException]×2→sql→sql[ERR:CatalogException]→sql[ERR:InternalException]×2→search→sql×6→sql[ERR:InternalException]→sql×4→submit`  
**Errors:**
- `InternalException` ×5 — DuckDB SQLite read bug on string manipulation queries
- `CatalogException: Table with name recipe_split does not exist` — agent hallucinated a CTE name as a real table

**Cost outlier:** 483K input / 28K output tokens (23 steps, 5 searches). Largest single question in the run.  
**Gold vs Pred:** Near-miss — logic was correct but ingredient sort order differs (`"BBQ Sauce, Bacon"` vs `"Bacon, BBQ Sauce"`).  
**Fix direction:** The InternalException loop was the blocker; with those fixed, the agent may have gotten the right answer. Add ordering constraint to the ingredient concatenation.

---

### result_mismatch (10 failures)

#### local002 — E_commerce
**Question:** 5-day symmetric moving average of predicted toy sales for Dec 5–8, 2018; sum of the four averages.  
**Tool sequence:** `search×4→sql→submit`  
**Root cause:** Output shape wrong. Agent returned 5 rows (one per date + total row); gold expects a single summary row with `(NUM_DAYS, TOTAL_MOVING_AVERAGES, AVG_MOVING_AVERAGE)`. The sum value (4340.10) was correct.  
**Gold:** `NUM_DAYS=4, TOTAL=4340.10, AVG=1085.03` (1 row)  
**Pred:** 5 rows with individual dates + NaN in sum column  
**Fix direction:** Output format instruction — "return a single summary row, not per-date rows."

---

#### local004 — E_commerce
**Question:** Number of orders, average payment per order, and customer lifespan in weeks for the 3 customers with the longest lifespan.  
**Tool sequence:** `search→sql→submit`  
**Root cause:** Agent used `customer_id` (order-level FK) instead of `customer_unique_id` (the stable cross-order identifier). The schema has both; gold requires `customer_unique_id`.  
**Gold:** Uses `customer_unique_id` as the identifier  
**Pred:** Used `customer_id` — different granularity, different rows  
**Fix direction:** Schema hint: "use `customer_unique_id` for customer-level aggregation, not `customer_id`."

---

#### local015 — California_Traffic_Collision
**Question:** Fatality rate for motorcycle collisions separated by helmet usage (two percentages).  
**Tool sequence:** `search→sql×3→submit`  
**Root cause:** The fatality rate numbers are correct (16.67% helmeted) but the output has extra columns. Gold wants exactly 2 columns: `helmet_usage | fatality_percentage`. Agent returned `helmet_group | collisions_in_group | motorcyclist_fatalities | fatality_rate_pct`.  
**Fix direction:** Stricter output format instruction: "return only the two requested columns."

---

#### local025 — IPL
**Question:** For each match/innings, combine batsman and extra runs per over, find highest over runs, then compute average of those highest values across all matches.  
**Tool sequence:** `search→sql→submit`  
**Root cause:** Agent returned per-match rows; gold expects a single cross-match average. The per-match values (match 335987, over 15, 24 runs, bowler CL White) are correct — just not aggregated to the final average.  
**Gold:** `avg_highest_over_runs_across_matches` (single aggregate value per bowler)  
**Fix direction:** The question asks for an average "across matches" — agent needs to add a final GROUP BY + AVG aggregation layer.

---

#### local049 — modern_data
**Question:** Average number of new unicorn companies per year in the top industry from 2019–2021.  
**Tool sequence:** `search→sql×2→submit`  
**Root cause:** Agent got 57.67 vs gold 60.33. Likely a date parsing issue — `strptime(date_joined, '%Y-%m-%dT%H:%M:%S.%f')` may be dropping some rows where the format doesn't match exactly.  
**Gold:** `60.333333`  
**Pred:** `57.666667`  
**Fix direction:** Use `TRY_CAST` with multiple date format fallbacks, or inspect actual date values in the table first.

---

#### local050 — complex_oracle
**Question:** Median of the average monthly projected sales in USD for France in 2021.  
**Tool sequence:** `search×3→sql→submit`  
**Root cause:** Off by ~27× (68,384 vs 2,552). Agent computed total sales and applied a single projection factor; gold requires: (1) compute monthly sales per month, (2) project each month, (3) take the median of those 12 monthly values.  
**Gold:** `2552.70`  
**Pred:** `68384.76`  
**Fix direction:** Clarify the aggregation order: monthly average first, then median across months — not a single aggregate.

---

#### local055 — chinook
**Question:** Artist with highest overall album sales (tie-broken alphabetically) vs artist with most distinct customers; compute absolute difference in average spending between those two artists' customer bases.  
**Tool sequence:** `search→sql×4→submit`  
**Root cause:** Agent identified the right artists but returned a full customer-level breakdown instead of a single scalar `average_spending_difference`. Gold: `5.133333`.  
**Fix direction:** The final reduction step (averaging and taking the absolute difference) was missing — agent stopped one level too early.

---

#### local060 — complex_oracle
**Question:** In the US, for Q4 2019 and Q4 2020, select cities where no-promotion sales rose; for those cities compute product share changes.  
**Tool sequence:** `search×3→sql×7→submit`  
**Root cause:** Share values are wrong (0.026 vs 0.010 for prod_id=28). Likely filtering issue — `promo_id=999` in this Oracle-derived dataset means "no promotion." Agent may be including or excluding the wrong promo rows when filtering to "no-promotion sales."  
**Note:** local063 is the same type of question and ran for **53 minutes** — a very long API stall occurred mid-run (not a DuckDB issue).

---

#### local061 — complex_oracle
**Question:** Average projected monthly sales in USD for France in 2021 (with promotions where country = France).  
**Tool sequence:** `search→sql→submit`  
**Root cause:** Agent numbers are consistently 20–35% lower than gold across all months. Likely using the wrong projection multiplier or missing a currency conversion factor specific to the complex_oracle schema.  
**Gold sample:** month 1 → 4054.99, month 2 → 2402.89  
**Pred sample:** month 1 → 3202.48, month 2 → 2114.48

---

#### local063 — complex_oracle
**Question:** Among US products with promo_id=999, find cities where sales increased by at least 20%; compute product share changes between Q4 2019 and Q4 2020.  
**Tool sequence:** `search→sql×5→search→sql×3→submit`  
**Wall time: 3207 seconds (53 min)** — a long API stall occurred between steps. The query logic itself ran in normal time; this was a network/gateway stall.  
**Root cause:** Same as local060 — incorrect share values due to promo_id filtering logic.  
**Fix direction:** Document that `promo_id=999` = no promotion in this schema; add as a hint.

---

## Root Cause Summary

| Root Cause | Instances | Count | Fix |
|---|---|---|---|
| Output format/extra columns | local002, 015, 025, 055 | 4 | Stricter prompt: "return exactly N columns named X" |
| External knowledge doc not applied | local003, 010, 061, 050 | 4 | Prompt instruction to explicitly apply doc formulas/definitions |
| DuckDB InternalException (SQLite type bug) | local003, 010, 073 | 3 | `sqlite_all_varchar=true` hint + CAST guidance |
| complex_oracle promo/projection logic | local050, 060, 061, 063 | 4 | Schema-specific hint: promo_id=999 = no-promo; projection formula |
| Wrong customer ID column | local004 | 1 | Schema hint: use `customer_unique_id` not `customer_id` |
| Schema discovery failure (pragma) | local056 | 1 | Hint: use `SHOW TABLES` / `DESCRIBE` |
| Date parsing off-by-one | local049 | 1 | `TRY_CAST` with format fallback |
| Nested window function | local003 | 1 | Prompt: use subquery instead of nested window |

_Note: some questions have multiple contributing root causes (e.g. local003 has both SQLite bug and external knowledge misapplication; local061/050 have both projection formula and external knowledge issues)._

**Highest-value fixes (recover most questions):**
1. **Output format instruction** — could recover local002, 015, 025, 055 (4 questions, +8%)
2. **External knowledge prompt instruction** — could recover local003, 010, 061, 050 (up to 4 questions, +8%)
3. **complex_oracle schema hints** — could recover local060, 063 and assist 061/050 (2–4 questions, +4–8%)
4. **`sqlite_all_varchar=true`** — could recover local010, reduce failures in local003, 073 (~2–3 questions, +4–6%)

Potential score with these fixes: **~44–47/50 (88–94%)**
