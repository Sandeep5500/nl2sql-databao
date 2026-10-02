# Contrast pairs: questions lane k1 lost that another run won

Run analysed: `q36s_pass4_k1` (Qwen3.6-35B, 64/135). Of its 71 failures, 38 were solved by another run of the
same setup (30 by a search-fixed lane, 8 only by a raw lane); 33 were solved by none of the other seven runs.

Each cause below was confirmed by sub-agents editing the failing SQL and re-scoring it against gold
(`nl2sql-v2/scripts/trace_tools.py exec`), not by reading the model's reasoning. I have not re-run each edit myself.

Counts: model error 16, output shape 10, ambiguous question 6, no commit 3, luck 3.

| instance | db | won in | kind | what k1 did differently | had gold mid-episode |
|---|---|---|---|---|---|
| local002 | E_commerce | s-k2 | model error | Fitted regression on a sale-day counter but predicted at calendar-day offsets | no |
| local018 | California_Traffic_Collision | s-k4 | model error | Dropped blank categories from yearly total AND subtracted in the wrong direction (both needed) | no |
| local023 | IPL | s-k2 | model error | Ranked by batting average; question says rank by runs per match and also report batting average | no |
| local029 | Brazilian_E_Commerce | raw-k1 | model error | Counted payment rows as orders (join fan-out); also a 3-way tie for third place | no |
| local034 | Brazilian_E_Commerce | s-k2 | model error | Counted each payment once per item in the order | no |
| local037 | Brazilian_E_Commerce | s-k3 | model error | Counted each payment once per item in the order | no |
| local059 | education_business | raw-k4 | model error | Filtered on fiscal_year; question says calendar year | no |
| local061 | complex_oracle | s-k2 | model error | Substituted raw sales for product-months with only one year; gold excludes them | no |
| local062 | complex_oracle | s-k4 | model error | Joined costs on 2 of 4 keys (fan-out); winner used the profits view | no |
| local070 | city_legislation | s-k2 | model error | 36 rows despite 'exactly one record per date'; which city is kept per date also decides the score | no |
| local096 | Db-IMDB | s-k3 | model error | Took 'total movies' from the inner-joined cast set, losing 2 movies; saw 3473 vs 3475 and accepted it | no |
| local163 | education_business | s-k2 | model error | ROW_NUMBER dropped one of two exactly tied faculty; winner used RANK | no |
| local228 | IPL | s-k4 | model error | Credited wickets to the dismissed batsman, not the bowler; also dropped rank/name columns | no |
| local253 | education_business | s-k2 | model error | Salary cleaning stripped only two currency symbols; 7 rows became NULL | no |
| local309 | f1 | s-k2 | model error | Inner join dropped 1950-57 (no constructor data); question says 'for each year' | no |
| local354 | f1 | raw-k2 | model error | Counted drive stints as rounds; also split name columns that fit no gold variant | no |
| local017 | California_Traffic_Collision | s-k4 | output shape | Stated '2021' and submitted the 3-row comparison table | no |
| local031 | Brazilian_E_Commerce | raw-k1 | output shape | Submitted all three months for a 'highest month' question | no |
| local039 | Pagila | s-k2 | output shape | Submitted its all-categories check query instead of the one-row answer | step 13 |
| local074 | bank_sales_trading | s-k2 | output shape | Submitted a 15-row preview of the verified 2000-row answer | step 20 |
| local130 | school_scheduling | s-k2 | output shape | Removed the Grade column before submitting (gold requires it; question does not ask for it) | steps 5,7,8 |
| local133 | EntertainmentAgency | s-k2 | output shape | Returned StyleID only, no style name | no |
| local169 | city_legislation | s-k2 | output shape | Relabelled periods 0-19 (gold 1-20) and dropped the count column | step 13 |
| local202 | city_legislation | s-k2 | output shape | Submitted the five qualifying rows for a 'how many' question | no |
| local209 | delivery_center | s-k2 | output shape | Left store_id out of the final SELECT | no |
| local264 | stacking | raw-k2 | output shape | Submitted the full two-row ranking for a 'which is most frequent' question | no |
| local021 | IPL | s-k2 | ambiguous question | Averaged only the over-50 matches; gold averages each qualifying striker's career total | no |
| local028 | Brazilian_E_Commerce | s-k3 | ambiguous question | Bucketed by purchase month; gold uses delivery month | no |
| local049 | modern_data | s-k2 | ambiguous question | 'New unicorns' by year founded; gold uses year joined | no |
| local056 | sqlite-sakila | s-k4 | ambiguous question | Averaged signed monthly change; gold averages the absolute change | no |
| local132 | EntertainmentAgency | raw-k1 | ambiguous question | Read style strength as magnitude; gold reads it as a 1/2/3 ordering. All 4 search-fixed runs lost, 3 of 4 raw runs won | no |
| local171 | city_legislation | s-k2 | ambiguous question | First term in Louisiana vs first term in any state; one legislator decides it | no |
| local098 | Db-IMDB | s-k2 | no commit | Never submitted; repeated one query 4 times, then 8 steps on an off-by-one | no |
| local335 | f1 | raw-k1 | no commit | Neither run submitted; winner's last query at the step cap happened to be the answer | no |
| local360 | log | s-k2 | no commit | Neither run submitted; k1 held gold twice and left it; winner landed on gold on its last step | steps 19,24 |
| local168 | city_legislation | s-k2 | luck | Five skills tie for top 3; gold files are different 3-of-5 subsets; k1's own SQL is non-deterministic | no |
| local220 | EU_soccer | raw-k2 | luck | Same players and counts in both runs; score depends on the exact label string | no |
| local330 | log | s-k4 | luck | Alphabetical tie-break on tied first pages; gold matches the engine's default row order | no |

## pass^k context

Four search-fixed lanes: pass^4 32/135 (23.7%), pass@4 94/135 (69.6%). Wins out of 4 lanes: 4 -> 32 questions,
3 -> 24, 2 -> 18, 1 -> 20, 0 -> 41.

## Caveat

`trace_tools.py queries` re-executes SQL, so on queries with unbroken ties (e.g. local168) a re-run can return a
different result from the one recorded in the trace.