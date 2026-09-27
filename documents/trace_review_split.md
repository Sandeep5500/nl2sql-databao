# Trace review split — Qwen3.6-35B run k4 (63 ✓ / 72 ✗)

Traces: `logs/traces/q36_pass4_k4/<instance>.json` · viewer task `q36_pass4_k4` (`uv run inspect view --log-dir ../logs/inspect --port 7591`)

Suggested failure tags while reading: wrong-logic / wrong-output-shape / wrong-filter-value / doc-misread / gave-up(step-cap) / dialect-or-tool-issue. For successes, note anything fragile (lucky guesses, unverified filters) — those inform judge/critic design.


## Person 1 — 45 questions (21 failures, 24 successes)

| instance | db | outcome | detail | steps | status |
|---|---|---|---|---|---|
| local141 | AdventureWorks | FAILURE | result_mismatch | 30 | fallback |
| local009 | Airlines | FAILURE | result_mismatch | 30 | fallback |
| local010 | Airlines | FAILURE | result_mismatch | 30 | fallback |
| local015 | California_Traffic_Collision | FAILURE | result_mismatch | 30 | fallback |
| local017 | California_Traffic_Collision | FAILURE | result_mismatch | 30 | fallback |
| local018 | California_Traffic_Collision | FAILURE | result_mismatch | 21 | submitted |
| local220 | EU_soccer | FAILURE | result_mismatch | 14 | submitted |
| local064 | bank_sales_trading | FAILURE | result_mismatch | 16 | submitted |
| local157 | bank_sales_trading | FAILURE | result_mismatch | 23 | submitted |
| local285 | bank_sales_trading | FAILURE | result_mismatch | 18 | submitted |
| local297 | bank_sales_trading | FAILURE | result_mismatch | 9 | submitted |
| local298 | bank_sales_trading | FAILURE | result_mismatch | 30 | fallback |
| local299 | bank_sales_trading | FAILURE | result_mismatch | 30 | fallback |
| local302 | bank_sales_trading | FAILURE | result_mismatch | 19 | submitted |
| local060 | complex_oracle | FAILURE | result_mismatch | 30 | fallback |
| local062 | complex_oracle | FAILURE | result_mismatch | 19 | submitted |
| local063 | complex_oracle | FAILURE | result_mismatch | 13 | submitted |
| local272 | oracle_sql | FAILURE | result_mismatch | 15 | submitted |
| local273 | oracle_sql | FAILURE | result_mismatch | 30 | fallback |
| local277 | oracle_sql | FAILURE | result_mismatch | 21 | submitted |
| local279 | oracle_sql | FAILURE | result_mismatch | 30 | fallback |
| local218 | EU_soccer | SUCCESS | matches local218_a.csv | 7 | submitted |
| local219 | EU_soccer | SUCCESS | matches local219_a.csv | 11 | submitted |
| local221 | EU_soccer | SUCCESS | matches local221_a.csv | 7 | submitted |
| local283 | EU_soccer | SUCCESS | matches local283_a.csv | 18 | submitted |
| local074 | bank_sales_trading | SUCCESS | matches local074_a.csv | 11 | submitted |
| local075 | bank_sales_trading | SUCCESS | matches local075_a.csv | 19 | submitted |
| local077 | bank_sales_trading | SUCCESS | matches local077_a.csv | 22 | submitted |
| local078 | bank_sales_trading | SUCCESS | matches local078_a.csv | 17 | submitted |
| local156 | bank_sales_trading | SUCCESS | matches local156_a.csv | 16 | submitted |
| local284 | bank_sales_trading | SUCCESS | matches local284_a.csv | 5 | submitted |
| local300 | bank_sales_trading | SUCCESS | matches local300_a.csv | 21 | submitted |
| local301 | bank_sales_trading | SUCCESS | matches local301_b.csv | 20 | submitted |
| local050 | complex_oracle | SUCCESS | matches local050_a.csv | 28 | submitted |
| local061 | complex_oracle | SUCCESS | matches local061_a.csv | 28 | submitted |
| local067 | complex_oracle | SUCCESS | matches local067_a.csv | 15 | submitted |
| local209 | delivery_center | SUCCESS | matches local209_a.csv | 9 | submitted |
| local210 | delivery_center | SUCCESS | matches local210_a.csv | 10 | submitted |
| local212 | delivery_center | SUCCESS | matches local212_c.csv | 14 | submitted |
| local152 | imdb_movies | SUCCESS | matches local152_a.csv | 12 | submitted |
| local230 | imdb_movies | SUCCESS | matches local230_a.csv | 12 | submitted |
| local269 | oracle_sql | SUCCESS | matches local269_a.csv | 21 | submitted |
| local270 | oracle_sql | SUCCESS | matches local270_a.csv | 16 | submitted |
| local274 | oracle_sql | SUCCESS | matches local274_a.csv | 8 | submitted |
| local275 | oracle_sql | SUCCESS | matches local275_a.csv | 17 | submitted |

## Person 2 — 45 questions (28 failures, 17 successes)

| instance | db | outcome | detail | steps | status |
|---|---|---|---|---|---|
| local007 | Baseball | FAILURE | result_mismatch | 12 | submitted |
| local008 | Baseball | FAILURE | result_mismatch | 30 | fallback |
| local028 | Brazilian_E_Commerce | FAILURE | result_mismatch | 10 | submitted |
| local029 | Brazilian_E_Commerce | FAILURE | result_mismatch | 4 | submitted |
| local031 | Brazilian_E_Commerce | FAILURE | result_mismatch | 9 | submitted |
| local032 | Brazilian_E_Commerce | FAILURE | result_mismatch | 11 | submitted |
| local034 | Brazilian_E_Commerce | FAILURE | result_mismatch | 6 | submitted |
| local037 | Brazilian_E_Commerce | FAILURE | result_mismatch | 6 | submitted |
| local131 | EntertainmentAgency | FAILURE | result_mismatch | 3 | submitted |
| local132 | EntertainmentAgency | FAILURE | result_mismatch | 20 | submitted |
| local021 | IPL | FAILURE | result_mismatch | 14 | submitted |
| local022 | IPL | FAILURE | result_mismatch | 11 | submitted |
| local023 | IPL | FAILURE | result_mismatch | 18 | submitted |
| local024 | IPL | FAILURE | result_mismatch | 27 | submitted |
| local026 | IPL | FAILURE | result_mismatch | 20 | submitted |
| local228 | IPL | FAILURE | result_mismatch | 30 | fallback |
| local229 | IPL | FAILURE | result_mismatch | 30 | fallback |
| local258 | IPL | FAILURE | result_mismatch | 30 | fallback |
| local259 | IPL | FAILURE | result_mismatch | 30 | fallback |
| local163 | education_business | FAILURE | result_mismatch | 7 | submitted |
| local253 | education_business | FAILURE | result_mismatch | 19 | submitted |
| local330 | log | FAILURE | result_mismatch | 9 | submitted |
| local331 | log | FAILURE | result_mismatch | 30 | fallback |
| local358 | log | FAILURE | result_mismatch | 13 | submitted |
| local360 | log | FAILURE | result_mismatch | 20 | submitted |
| local066 | modern_data | FAILURE | result_mismatch | 14 | submitted |
| local073 | modern_data | FAILURE | result_mismatch | 30 | fallback |
| local201 | modern_data | FAILURE | result_mismatch | 5 | submitted |
| local128 | BowlingLeague | SUCCESS | matches local128_a.csv | 11 | submitted |
| local030 | Brazilian_E_Commerce | SUCCESS | matches local030_a.csv | 12 | submitted |
| local035 | Brazilian_E_Commerce | SUCCESS | matches local035_a.csv | 10 | submitted |
| local133 | EntertainmentAgency | SUCCESS | matches local133_a.csv | 6 | submitted |
| local020 | IPL | SUCCESS | matches local020_b.csv | 23 | submitted |
| local025 | IPL | SUCCESS | matches local025_e.csv | 22 | submitted |
| local058 | education_business | SUCCESS | matches local058_a.csv | 9 | submitted |
| local059 | education_business | SUCCESS | matches local059_a.csv | 13 | submitted |
| local114 | education_business | SUCCESS | matches local114_d.csv | 8 | submitted |
| local329 | log | SUCCESS | matches local329_a.csv | 12 | submitted |
| local040 | modern_data | SUCCESS | matches local040_a.csv | 22 | submitted |
| local041 | modern_data | SUCCESS | matches local041_a.csv | 4 | submitted |
| local049 | modern_data | SUCCESS | matches local049_a.csv | 14 | submitted |
| local065 | modern_data | SUCCESS | matches local065_b.csv | 7 | submitted |
| local244 | music | SUCCESS | matches local244_a.csv | 11 | submitted |
| local081 | northwind | SUCCESS | matches local081_a.csv | 6 | submitted |
| local085 | northwind | SUCCESS | matches local085_a.csv | 5 | submitted |

## Person 3 — 45 questions (23 failures, 22 successes)

| instance | db | outcome | detail | steps | status |
|---|---|---|---|---|---|
| local096 | Db-IMDB | FAILURE | result_mismatch | 26 | submitted |
| local097 | Db-IMDB | FAILURE | result_mismatch | 16 | submitted |
| local098 | Db-IMDB | FAILURE | result_mismatch | 30 | fallback |
| local099 | Db-IMDB | FAILURE | result_mismatch | 28 | submitted |
| local003 | E_commerce | FAILURE | result_mismatch | 30 | fallback |
| local004 | E_commerce | FAILURE | result_mismatch | 10 | submitted |
| local039 | Pagila | FAILURE | result_mismatch | 26 | submitted |
| local167 | city_legislation | FAILURE | result_mismatch | 16 | submitted |
| local169 | city_legislation | FAILURE | result_mismatch | 30 | fallback |
| local171 | city_legislation | FAILURE | result_mismatch | 20 | submitted |
| local286 | electronic_sales | FAILURE | result_mismatch | 14 | submitted |
| local309 | f1 | FAILURE | result_mismatch | 17 | submitted |
| local335 | f1 | FAILURE | result_mismatch | 15 | submitted |
| local336 | f1 | FAILURE | result_mismatch | 30 | fallback |
| local344 | f1 | FAILURE | result_mismatch | 30 | fallback |
| local354 | f1 | FAILURE | result_mismatch | 30 | fallback |
| local355 | f1 | FAILURE | result_mismatch | 19 | submitted |
| local356 | f1 | FAILURE | result_mismatch | 30 | fallback |
| local056 | sqlite-sakila | FAILURE | result_mismatch | 10 | submitted |
| local194 | sqlite-sakila | FAILURE | result_mismatch | 13 | submitted |
| local196 | sqlite-sakila | FAILURE | result_mismatch | 17 | submitted |
| local263 | stacking | FAILURE | result_mismatch | 13 | submitted |
| local264 | stacking | FAILURE | result_mismatch | 8 | submitted |
| local100 | Db-IMDB | SUCCESS | matches local100_a.csv | 29 | submitted |
| local002 | E_commerce | SUCCESS | matches local002_c.csv | 21 | submitted |
| local038 | Pagila | SUCCESS | matches local038_b.csv | 7 | submitted |
| local019 | WWE | SUCCESS | matches local019_a.csv | 13 | submitted |
| local054 | chinook | SUCCESS | matches local054_a.csv | 14 | submitted |
| local055 | chinook | SUCCESS | matches local055_b.csv | 19 | submitted |
| local198 | chinook | SUCCESS | matches local198_a.csv | 6 | submitted |
| local068 | city_legislation | SUCCESS | matches local068_a.csv | 7 | submitted |
| local070 | city_legislation | SUCCESS | matches local070_b.csv | 17 | submitted |
| local071 | city_legislation | SUCCESS | matches local071_a.csv | 11 | submitted |
| local072 | city_legislation | SUCCESS | matches local072_d.csv | 10 | submitted |
| local168 | city_legislation | SUCCESS | matches local168_d.csv | 14 | submitted |
| local170 | city_legislation | SUCCESS | matches local170_a.csv | 24 | submitted |
| local202 | city_legislation | SUCCESS | matches local202_a.csv | 10 | submitted |
| local310 | f1 | SUCCESS | matches local310_a.csv | 5 | submitted |
| local311 | f1 | SUCCESS | matches local311_a.csv | 13 | submitted |
| local130 | school_scheduling | SUCCESS | matches local130_a.csv | 23 | submitted |
| local193 | sqlite-sakila | SUCCESS | matches local193_a.csv | 7 | submitted |
| local195 | sqlite-sakila | SUCCESS | matches local195_a.csv | 14 | submitted |
| local197 | sqlite-sakila | SUCCESS | matches local197_a.csv | 6 | submitted |
| local199 | sqlite-sakila | SUCCESS | matches local199_a.csv | 6 | submitted |
| local262 | stacking | SUCCESS | matches local262_a.csv | 13 | submitted |