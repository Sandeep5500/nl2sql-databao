# Per-trace analysis — Person 1, first 27 (q36s_pass4_k1)

Analyst: Claude (5 parallel deep-read agents, full traces vs gold). Tags: harness-issue /
wrong-logic / wrong-output-shape / gave-up. Retrieval verdict: **0 of 22 failures are
retrieval**; every episode located the right schema within ~6 steps.

| instance | db | tag | one-line verdict |
|---|---|---|---|
| local141 | AdventureWorks | harness-issue | Sales tables unreadable: DuckDB scanner dies on INTEGER-declared columns storing text; plan matched gold, execution impossible |
| local009 | Airlines | harness-issue | coordinates column unreadable (same scanner bug); doc+airport code all correctly in hand by step 5 |
| local010 | Airlines | harness-issue | Same coordinates bug; secondary: repeated identical query 5x once cornered |
| local015 | California_Traffic_Collision | gave-up | Right cohorts (18 and 1 collisions) at step 14 but fatalities 2 vs gold 3, so its rate would have been 11.1% not 16.67%; then 15 steps auditing the join, never computed a percentage. 0 of 27 queries match gold |
| local017 | California_Traffic_Collision | wrong-output-shape | Reasoned the answer (2021) correctly, submitted the 3-row per-year diagnostic table instead of one row |
| local018 | California_Traffic_Collision | wrong-logic | Narrowed percentage denominator with NULL/''-filters; own unfiltered q2 had the gold number |
| local220 | EU_soccer | wrong-output-shape | Gold answer computed (Ronaldo 199 / Iraizoz); missing category-label column all 9 gold variants require |
| local064 | bank_sales_trading | wrong-logic | Averaged over positive-balance customers instead of all; ignored months absent from data (May=0) |
| local074 | bank_sales_trading | wrong-output-shape | Proved gold-identical 2000-row result (q16), then submitted the LIMIT-15 type-check preview (q18) |
| local157 | bank_sales_trading | wrong-output-shape | Values exact; dates left raw DD-MM-YYYY vs gold ISO, so date column never matches |
| local285 | bank_sales_trading | wrong-logic | Unit-price sums instead of qty-weighted cost; profit omitted loss deduction; cascade across 3 metrics |
| local297 | bank_sales_trading | wrong-logic | Kept no-prior-month customers (gold drops them) and returned 0-1 fraction where question says percentage |
| local298 | bank_sales_trading | gave-up | Produced the gold result on 5 of 26 queries (steps 17, 19, 21, 25, 27) and said 'go with query 24' on the last step, then second-guessed; fallback picked a scratch probe. Genuinely converging |
| local299 | bank_sales_trading | wrong-output-shape | Logic right; split year/month columns vs gold 'YYYY-MM' + 0.1-in-286k precision vs absolute 1e-2 tolerance |
| local302 | bank_sales_trading | wrong-logic | Before/after window asymmetric (11 vs 12 weeks, excluded week 25); right winner, wrong value, 5 rows vs 1 |
| local061 | complex_oracle | wrong-logic | Doc formula implemented right; COALESCE'd single-year products into average (gold excludes) — one-line fix verified |
| local062 | complex_oracle | wrong-logic | costs join missing promo_id+channel_id -> fan-out inflated profits; full-key join reproduces gold exactly |
| local209 | delivery_center | wrong-output-shape | Numerically perfect; omitted store_id column (gold requires it) — checklist's 'no extra id columns' backfired |
| local272 | oracle_sql | wrong-logic | Reasonable FIFO reading of question text; gold encodes book algorithm picking warehouse-2 rows (question says warehouse 1) |
| local273 | oracle_sql | gave-up | Never close: 0 of 22 queries match gold; interpretation thrash plus 4 errored queries; gold itself odd (ids under PRODUCT_NAME, 0.0 averages) |
| local277 | oracle_sql | gave-up | Confused, not converging: 1 of 21 queries (step 24, 417.45) matches gold variant _c, reached by guessing weights = time step; five other answers before and after (408.76, 12034, 494.47, 280.79, per-product). Gold has 3 variants (277.33 / 266.22 / 417.45) |
| local279 | oracle_sql | gave-up | Plan plausible but never built: 24 steps on finding data and type/syntax errors, first model attempt on the last step. 0 of 25 queries match gold |
| local218 | EU_soccer | SUCCESS | search_context found match_view; 6 steps; fragile: submitted 5-col diagnostic (extra-col tolerance saved it) |
| local219 | EU_soccer | SUCCESS | describe_table join grounding + QUALIFY; fragile: tie-break guess happened to match gold |
| local221 | EU_soccer | SUCCESS | First SQL attempt was final answer + sanity check; fragile: scope interpretation unverified |
| local283 | EU_soccer | SUCCESS | Spotted real 77-point tie in preview, added tiebreak; fragile: arbitrary tiebreak matched gold by luck |
| local075 | bank_sales_trading | SUCCESS | search_context genuinely load-bearing (event-code legend); cross-checked attribution rule; solid |

## Pattern rollup (22 failures)

- **wrong-logic 8** — single semantic clause each (window boundary, NULL policy, join fan-out, denominator); local302/061/062 verified one-line-change-to-gold
- **wrong-output-shape 6** — answer computed, projection lost it (LIMIT preview, missing id/label column, raw dates, fraction-vs-percent)
- **gave-up 5** — verified by re-running every query in each trace against gold: only local298 was converging (gold result on 5 queries); local277 hit an accepted answer once by a guess and left it; local015/273/279 never produced a gold-matching result
- **harness-issue 3** — DuckDB sqlite scanner dies on INTEGER-declared columns storing text (Airlines coordinates, AdventureWorks sales) — unanswerable until fixed

## Cheap fixes ranked by expected flips (this 27 alone)
1. Scanner fix for mistyped columns (3 flips: 141/009/010)
2. Smarter fallback: submit best-shaped/most-repeated query, not literal last (277, 298, likely 015/273)
3. Submit-time contracts: never LIMITed previews; ISO dates; include id+label columns; true percentages (074, 157, 209, 220, 017, 297-partial)
4. Variant-verifier on ambiguous clauses: execute 2-3 readings, compare (302, 061, 062, 064)

Benchmark caveats: oracle_sql golds encode book-chapter algorithms that paraphrases contradict (272, 273); absolute 1e-2 tolerance fails correct float pipelines on large sums (299).