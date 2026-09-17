# Error Analysis — gpt-4.1-mini, Run `gpt54mini_run_20260415_111943`

**Model:** gpt-4.1-mini  
**Results CSV:** `results/spider2_results_20260415_111944.csv`  
**Traces:** `logs/traces/gpt54mini_run_20260415_111943/`  
**Date:** 2026-04-15  
**Score: 6 / 18 (33%)**

---

## Overall Summary

| Metric | Value |
|---|---|
| Total questions | 18 |
| Correct | 6 (33%) |
| result_mismatch | 12 |
| sql_execution_error | 0 |
| Total input tokens | 1,118,686 |
| Total output tokens | 101,353 |
| Total time | ~3,157s (~53 min) |
| Cost estimate (input $0.40/1M, output $1.60/1M) | ~$0.61 |

---

## Per-Instance Results Table

| ID | DB | ✓/✗ | Category | Ext Knowledge | Ext Used | Steps | SQL Calls | Search Calls | Time (s) | Root Cause | How to Improve |
|---|---|---|---|---|---|---|---|---|---|---|---|
| local002 | E_commerce | ✗ | result_mismatch | — | — | 20 | 10 | 1 | 179 | Agent produced a 4-row per-date table; gold expects a single-row summary (NUM_DAYS, TOTAL_MOVING_AVERAGES, AVG_MOVING_AVERAGE). Submitted the wrong output shape/aggregation level. | Clarify in prompt that the answer should be the summary of the moving averages, not the per-day table. |
| local004 | E_commerce | ✓ | correct | — | — | 14 | 5 | 1 | 64 | — | — |
| local015 | California_Traffic_Collision | ✗ | result_mismatch | — | — | 39 | 20 | 2 | 290 | Motorcycle party fatality rate by helmet. 39 steps signals the agent struggled significantly. Gold expects helmet_worn=16.67%, no_helmet=0.00%. Agent likely got the fatality percentage numerator/denominator wrong (killed victims vs any injury, or incorrect party filtering for motorcycles). | Add a hint about the fatality rate denominator (killed / involved). Consider helmet encoding in safety_equipment columns. |
| local025 | IPL | ✗ | result_mismatch | — | — | 22 | 11 | 1 | 155 | Cricket scoring aggregation: combine batsman runs + extras per over, then find the over with highest runs per match (per innings). Gold includes bowler_id, bowler_name, and a global avg across all matches. Agent likely missed that the over-level max must be matched to a bowler. | Improve DCE schema descriptions for IPL ball-by-ball tables. The bowler join on the max-run over is a multi-step non-obvious join. |
| local049 | modern_data | ✗ | result_mismatch | — | — | 11 | 3 | 1 | 47 | **Wrong output shape.** Agent computed the correct value (57.67, matching gold variant `local049_b.csv`) but submitted 3 rows (year + per-year count + avg repeated as a column) instead of a single scalar row. Evaluator couldn't match a 3-row table against a 1-row gold. | Same fix as local002/local297/local300: pre-submit shape check. Agent should SELECT only the final aggregate, not the intermediate year-by-year breakdown. |
| local050 | complex_oracle | ✓ | correct | projection_calculation.md | Yes | 19 | 9 | 2 | 163 | — | — |
| local060 | complex_oracle | ✗ | result_mismatch | — | — | 15 | 6 | 1 | 105 | US Q4 2019 vs Q4 2020 city sales comparison with no-promo filter, then product ranking within those cities. Complex two-stage filter: (1) find cities where no-promo sales rose from Q4 2019 → Q4 2020, (2) rank products within those cities. Agent likely got the city filter wrong (wrong year comparison or missed the no-promo constraint). No projection logic needed — this is about actual sales, unlike local050/061. | Improve complex_oracle schema descriptions for the sales/promotions join. The two-stage filter (city eligibility first, then product ranking within eligible cities) is a known hard pattern. |
| local061 | complex_oracle | ✓ | correct | projection_calculation.md | Yes | 15 | 6 | 1 | 87 | — | — |
| local063 | complex_oracle | ✓ | correct | — | — | 17 | 7 | 1 | 181 | — | — |
| local074 | bank_sales_trading | ✗ | result_mismatch | — | — | 14 | 5 | 1 | 84 | Monthly closing balance per customer. Gold has 2000 rows (customer × month) with CUMULATIVE_BALANCE. Agent likely computed monthly net change correctly but got the running cumulative sum wrong — possibly missed that months with no transactions should carry forward the previous balance (got confirmed: inactive months are present in gold). | Prompt hint about filling in all months even with zero transactions and carrying balance forward. |
| local096 | Db-IMDB | ✗ | result_mismatch | — | — | 20 | 9 | 0 | 40 | **Schema not loaded.** 0 search calls. Agent found no user tables in DuckDB (`information_schema.tables` returned empty). Submitted an introspection query against `information_schema.columns` as its final answer. | Critical: Db-IMDB is not indexed in DCE / not loading into the DuckDB session. Debug DCE attachment for this DB. |
| local098 | Db-IMDB | ✗ | result_mismatch | — | — | 19 | 8 | 0 | 54 | **Same as local096** — schema not loaded, 0 search calls. Agent gave up and submitted a `duckdb_functions()` introspection query. | Same fix as local096 — Db-IMDB DCE indexing failure. |
| local220 | EU_soccer | ✗ | result_mismatch | — | — | 12 | 4 | 1 | 84 | Agent identified the correct players for most wins (Cristiano Ronaldo, 199) but chose wrong player for most losses (Ricardo, 163 — which is most losses by slots, not distinct matches). Gold expects Gorka Iraizoz Moreno (107 distinct losses). Agent did not deduplicate player-match appearances — counted lineup slots, not distinct match appearances. | Add deduplication hint: count distinct match_ids per player, not total lineup appearances. |
| local297 | bank_sales_trading | ✗ | result_mismatch | — | — | 22 | 8 | 1 | 117 | Monthly net deposit/withdrawal per customer, then derive growth metrics. Agent computed aggregate stats (26.8% of customers with >5% growth in latest month) rather than the per-customer monthly net amounts the gold expects. Submitted the derived statistic instead of the base table. | Agent misread the question's output intent — submit the intermediate table (monthly_net per customer), not the derived statistic. |
| local300 | bank_sales_trading | ✗ | result_mismatch | — | — | 13 | 4 | 1 | 93 | Daily balances with full date spine per customer. Agent computed running balances and then submitted monthly totals (month_start, monthly_total_of_customer_max_balances) — completely wrong aggregation level. Gold expects daily granularity. | Agent collapsed daily → monthly during exploration and submitted the wrong level. Prompt should emphasize "daily" output is required. |
| local344 | f1 | ✗ | result_mismatch | f1_overtake.md | Yes | 71 | 39 | 1 | 1410 | **Agent timeout/doom-loop.** 71 steps, 23 min. Agent eventually gave up and hardcoded values found during exploration: T=13769 (gold: 13402), P=37072 (gold: 37398), R=0 (gold: 5536), S=2452 (gold: 2443). R=0 is a clear signal the agent never correctly identified R-type overtakes. The f1_overtake.md was referenced but the logic for classifying overtake types (P/T/R/S) was not applied correctly. | Most urgent: fix the f1_overtake.md definition of R-type overtakes (agent returned 0). Review doom-loop triggers — agent should fail-fast rather than hardcode guessed values after 60+ steps. |
| local355 | f1 | ✗ | result_mismatch | — | — | 16 | 6 | 1 | 113 | Average first_round and last_round of races missed by F1 drivers across all years. Agent likely computed average round numbers but missed defining "missed races" correctly (drivers absent from a race they otherwise participated in that season vs all races in a year). | Add hint about how to define "missed races" — drivers who participated in a season but skipped specific rounds. |
| local360 | log | ✓ | correct | — | — | 19 | 6 | 1 | 93 | — | — |

---

## Failure Patterns

### 1. Schema Not Loading — Db-IMDB (2 failures: local096, local098)

Both instances returned 0 search_context calls and the agent could not find any user tables. This is a **DCE indexing/attachment bug**, not a model reasoning failure. The agent correctly diagnosed the problem ("no data tables attached") but had no recourse.

**Fix:** Debug why Db-IMDB is absent from the DuckDB session. Check that `spider2-dce/` has a YAML for this DB and that `dce.duckdb` includes it.

---

### 2. Agent Doom-Loop / Near-Timeout — f1 (1 failure: local344)

local344 consumed 71 steps and 23 minutes — by far the most expensive question in this run (379K input tokens, $0.16 alone). The agent surrendered by hardcoding values from earlier SQL runs with incorrect logic. The R-type overtake count was hardcoded as 0 (gold: 5,536), indicating the agent never found the correct classification.

**Fix:** The doom-loop rule in the system prompt should trigger earlier. The f1_overtake.md external knowledge needs to more clearly define all four overtake type classifications with concrete SQL patterns. Consider adding a step cap specifically for f1 questions.

---

### 3. External Knowledge — Correlated with Success on complex_oracle

| Instance | Ext Knowledge | Used | Score |
|---|---|---|---|
| local050 | projection_calculation.md | Yes | ✓ |
| local061 | projection_calculation.md | Yes | ✓ |
| local063 | None | — | ✓ |
| local060 | None | — | ✗ |
| local344 | f1_overtake.md | Yes | ✗ |

On complex_oracle, the two questions that used `projection_calculation.md` passed; the one without it (local060) failed. local060 involves Q4 year-over-year city sales comparison — it is plausibly the same projection logic and should have `projection_calculation.md` referenced in its question metadata.

**Fix:** Check whether local060 should reference `projection_calculation.md`. If so, add it to `spider2-lite.jsonl`.

---

### 4. Wrong Output Shape / Aggregation Level (3 failures: local002, local297, local300)

In all three cases, the agent computed *something* related to the question but submitted at the wrong granularity:
- **local002**: Submitted per-date moving averages; gold wanted a 1-row summary.
- **local297**: Submitted a derived statistic (% of customers with growth); gold wanted the per-customer monthly net table.
- **local300**: Submitted monthly aggregates; gold wanted daily balances.

These are not schema understanding failures — the agent found the right data — but failures to read the output format from the question.

**Fix:** The system prompt's pre-submit checklist should include: *"Does the output shape (rows, columns, granularity) match what the question asked for?"*

---

### 5. Running Balance / Date Spine (2 failures: local074, local300)

Both bank_sales_trading balance questions failed. local074 needed a cumulative running balance that fills in months with zero transactions; local300 needed a full daily date spine. These require `GENERATE_SERIES` or recursive CTEs, which DuckDB supports but the agent did not apply correctly.

**Fix:** Add a DuckDB hint in the system prompt about generating date series: `GENERATE_SERIES(min_date, max_date, INTERVAL '1 day')`.

---

### 6. Subtle Semantic / Definition Errors (4 failures: local015, local025, local220, local355)

| Instance | Issue |
|---|---|
| local015 | Wrong denominator for fatality rate (killed / what?) |
| local025 | Missed bowler join on the max-run over |
| local220 | Counted lineup slots instead of distinct match appearances |
| local355 | Wrong definition of "missed races" |

These require either better schema descriptions (DCE enrichment) or more precise question-specific hints in external knowledge files.

---

## Prioritized Fixes

| Priority | Fix | Expected Impact |
|---|---|---|
| P0 | Debug Db-IMDB schema loading in DCE | Recovers 2 questions from 0-effort failures |
| P1 | Fix f1_overtake.md — define R-type overtakes with SQL pattern | Recovers local344 (currently 0 R-type) |
| P2 | System prompt: pre-submit output-shape check | May fix local002, local297, local300 |
| P2 | System prompt: DuckDB `GENERATE_SERIES` date spine hint | May fix local074, local300 |
| P3 | DCE enrichment for IPL ball-by-ball tables (bowler join) | May fix local025 |
| P3 | System prompt: pre-submit output shape check (covers local049 too) | Already covered above |
| P3 | DCE enrichment for EU_soccer: distinct match count per player | May fix local220 |
