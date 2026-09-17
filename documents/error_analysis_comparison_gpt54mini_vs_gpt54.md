# Error Analysis Comparison — GPT-5.4-mini vs GPT-5.4

**GPT-5.4-mini:** 0 / 18 correct (all failures, some values correct but wrong format/schema)  
**GPT-5.4:** 5 / 18 correct (`local004`, `local050`, `local061`, `local063`, `local360`)  
**GPT-5.4 run:** `logs/traces/gpt54mini_run_20260415_111943` / `results/spider2_results_20260415_111944.csv`

---

## Comparison Table

| ID | DB | Question (short) | mini ✓? | GPT5.4 ✓? | mini Error Category | mini Error Detail | GPT5.4 Error Category | GPT5.4 Error Detail | What Changed |
|---|---|---|---|---|---|---|---|---|---|
| local002 | E_commerce | 5-day symmetric moving average of toy sales Dec 5–8 | ✗ | ✗ | Output too verbose | Correct sum (4340.10 matches gold) but returned 5-row table (4 date rows + Total) instead of 1 summary row: NUM_DAYS \| TOTAL \| AVG | Wrong output shape | Same root cause — correct math, submitted per-date breakdown instead of the single summary row | Same failure mode, different surface: mini adds a "Total" footer row, GPT5.4 omits it but still returns 4 rows not 1 |
| local004 | E_commerce | Orders, avg payment, customer lifespan for top 3 customers | ✗ | ✓ | Wrong join key | Correct values (13664.08, 7274.88, 6929.31) but used `customer_id` (order-level) instead of `customer_unique_id` (person-level) | — | Passed | GPT5.4 correctly used `customer_unique_id`; mini's wrong key happened to produce matching values on this data, but is semantically wrong |
| local015 | California_Traffic_Collision | Fatality rate for motorcycle collisions by helmet usage | ✗ | ✗ | Extra columns | Correct percentages (16.67%, 0.00%) but returned 4 columns; gold expects 2: `helmet_usage \| fatality_percentage` | High step count + wrong formula | 39 steps, 20 SQL calls; likely wrong numerator/denominator for fatality rate | Mini got the right numbers but cluttered the output; GPT5.4 struggled with the formula itself and used far more steps |
| local025 | IPL | Highest-run over per match/innings with bowler and global avg | ✗ | ✗ | Column name + order mismatch | Correct values but column named `highest_over_total` (float 24.0) instead of `highest_over_runs` (int 24); wrong column order | Missing bowler join | Did not join the max-run over back to the bowler; missed `bowler_id` and `bowler_name` in output entirely | Mini was closer — had correct values with naming issues; GPT5.4 missed the bowler dimension entirely |
| local049 | modern_data | Avg new unicorns per year in top industry 2019–2021 | ✗ | ✗ | Wrong date field + format | Used wrong date field; returned per-year breakdown (3 rows) instead of single aggregate; avg was 57.67 (matches gold_b) | Wrong output shape | Correct value 57.67 (matches `local049_b.csv`) but submitted 3-row year breakdown instead of 1-row scalar | Both computed the right answer, both returned the wrong shape; mini additionally used the wrong date column |
| local050 | complex_oracle | Median of avg monthly projected sales, France 2021 | ✗ | ✓ | External knowledge ignored | `projection_calculation.md` defines `proj_factor` formula; agent used generic YoY ratio causing 27× amplification instead | — | Passed; correctly applied `proj_factor` from external doc | GPT5.4 read and applied the external knowledge doc; mini ignored it and hallucinated a formula |
| local060 | complex_oracle | US Q4 cities with ≥20% no-promo growth → top 20% products by share | ✗ | ✗ | Wrong promo filter logic | Used wrong column or value for the no-promo filter, yielding incorrect city set | Wrong city selection scope / denominator | Agent city denominator was ~133K vs gold's ~586K; likely joined fewer qualifying cities, possibly due to country name mismatch or share computed within cities instead of all US | Different root causes: mini had a filter bug; GPT5.4 had a scope/denominator interpretation error |
| local061 | complex_oracle | Avg projected monthly sales France 2021, promotions only | ✗ | ✓ | External knowledge ignored | Same as local050 — used raw monthly aggregation instead of `proj_factor` | — | Passed; correctly used `projection_calculation.md` | Same delta as local050: GPT5.4 used EK, mini did not |
| local063 | complex_oracle | Top products in US with promo_id=999 by sales share change | ✗ | ✓ | Wrong promo filter (inverted) | Selected products WITH promotions instead of WITHOUT (promo_id=999 = no promo) | — | Passed; correctly filtered on promo_id=999 | GPT5.4 correctly identified promo_id=999 = no promotion; mini inverted the filter |
| local074 | bank_sales_trading | Monthly closing balance summary per customer | ✗ | ✗ | Date format + column mismatch | Correct values but wrong column names and date format | Wrong running balance | Cumulative balance computation incorrect; inactive months may not carry forward properly | Mini was closer to correct (right values, wrong format); GPT5.4 had a deeper logic error in the balance formula |
| local096 | Db-IMDB | % films with exclusively female actors per year | ✗ | ✗ | DCE index missing | Agent found no tables in DuckDB; submitted introspection query | DCE index missing | Identical infrastructure failure — 0 search calls, no tables visible | Same failure, same cause; not a model capability issue |
| local098 | Db-IMDB | Actors with no career gap >N years | ✗ | ✗ | DCE index missing | Same as local096 | DCE index missing | Identical | Same |
| local220 | EU_soccer | Player with most wins / most losses | ✗ | ✗ | Extra column + wrong labels | Right values but extra column, wrong category labels, wrong column names | Wrong player (lineup slots vs distinct) | Found most wins correctly (Cristiano Ronaldo, 199) but chose Ricardo (163 slots) over Gorka Iraizoz Moreno (107 distinct matches) for most losses | Mini had formatting issues; GPT5.4 had a deeper deduplication error — counted lineup slots not distinct match appearances |
| local297 | bank_sales_trading | Monthly net deposit/withdrawal per customer | ✗ | ✗ | Wrong growth denominator | Gold 44.87% vs pred 46.88%; likely wrong denominator; also returned extra breakdown columns | Wrong aggregation level | Agent submitted a derived statistic (% customers with >5% growth) instead of the per-customer monthly net table gold expects | Different failure modes: mini computed the right-level table but with wrong denominator; GPT5.4 collapsed the table to a single aggregate entirely |
| local300 | bank_sales_trading | Daily balances with full date spine per customer | ✗ | ✗ | Wrong date spine baseline | Jan 2020 discrepancy due to carry-forward starting at wrong baseline (non-zero) | Wrong granularity | Submitted monthly aggregates instead of daily balances | Mini was closer — operated at daily level but got the initial balance wrong; GPT5.4 collapsed to monthly entirely |
| local344 | f1 | Pit stop overtake counts by type (P/T/R/S) | ✗ | ✗ | EK doc caused paralysis | Agent searched `f1_overtake.md` repeatedly but never successfully wrote SQL | Doom-loop, hardcoded values | 71 steps, 23 min; hardcoded counts from partial exploration (R=0 vs gold 5536); near-correct T and P but wrong R entirely | GPT5.4 made more attempts but got stuck and hardcoded wrong values; mini was paralyzed by the doc; both failed on R-type overtakes |
| local355 | f1 | Avg first/last round of missed races by F1 drivers | ✗ | ✗ | Wrong team-switch definition + extra column | Different driver set selected due to ambiguous "missed races" definition; extra column in output | Wrong "missed races" definition | Different interpretation of which races count as "missed" | Same root ambiguity, different manifestations; neither model got the correct driver/round set |
| local360 | log | Events before first '/detail' page per session | ✗ | ✓ | Wrong question interpretation | Agent computed count of events instead of path/list of events before first conversion | — | Passed; correctly identified events preceding `/detail` page per session | GPT5.4 correctly parsed "number of events before" the boundary; mini misread it as a path/conversion question |

---

## Summary by Outcome

| Outcome | Instances | Notes |
|---|---|---|
| Both correct | 0 | — |
| GPT5.4 ✓, mini ✗ | 5 | local004, local050, local061, local063, local360 |
| Both fail, same root cause | 6 | local002, local049, local096, local098, local344, local355 |
| Both fail, different root cause | 7 | local015, local025, local060, local074, local220, local297, local300 |
| mini ✓, GPT5.4 ✗ | 0 | — |

---

## Key Patterns

### Where GPT-5.4 wins (5 questions)

| Pattern | Questions | Detail |
|---|---|---|
| External knowledge (EK) | local050, local061 | GPT5.4 read and applied `projection_calculation.md`; mini ignored it entirely |
| Promo filter | local063 | GPT5.4 correctly identified promo_id=999 = no promo; mini inverted the filter |
| Join key semantics | local004 | GPT5.4 used `customer_unique_id`; mini used `customer_id` (happened to match numerically but wrong conceptually) |
| Question interpretation | local360 | GPT5.4 correctly parsed the session-log question; mini confused count vs path |

### Where mini is actually closer (3 questions)

| ID | Why mini is closer |
|---|---|
| local015 | Mini computed correct fatality rates (16.67%, 0.00%); GPT5.4 struggled with the formula across 39 steps |
| local025 | Mini had correct values with naming issues; GPT5.4 missed the bowler join entirely |
| local300 | Mini operated at daily granularity (right level); GPT5.4 collapsed to monthly |

### Shared infrastructure failure (2 questions)

`local096` and `local098` fail identically for both — Db-IMDB schema is not loaded in the DuckDB session. This is a DCE indexing issue, not a model issue.

### Shared output-shape failure (2 questions)

`local002` and `local049` — both models compute the right answer but submit an intermediate breakdown table instead of the required scalar summary. GPT5.4 is only marginally better here.

---

## Prioritized Fixes (by potential recovery)

| Priority | Fix | Recovers (mini) | Recovers (GPT5.4) |
|---|---|---|---|
| P0 | Fix Db-IMDB DCE indexing | local096, local098 | local096, local098 |
| P1 | Prompt: force reading EK docs before writing SQL | local050, local061 | — (already works) |
| P1 | Schema hint: `promo_id=999` = no promotion | local060, local063 | — (already works) |
| P2 | Prompt: pre-submit output-shape check ("return only the final aggregate, not the breakdown") | local002, local049 | local002, local049 |
| P2 | f1_overtake.md: explicit SQL pattern for R-type overtakes | local344 | local344 |
| P3 | Schema hint: `customer_unique_id` for person-level aggregation | local004 | — |
| P3 | DCE enrichment: bank_sales_trading date spine hint (`GENERATE_SERIES`) | local074, local297, local300 | local074, local297, local300 |
| P3 | DCE enrichment: IPL bowler join on max-run over | local025 | local025 |
