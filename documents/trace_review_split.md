# Trace review split — Qwen3.6-35B search-fixed lane k1 (64 ✓ / 71 ✗)

Traces: `logs/traces/q36s_pass4_k1/<instance>.json` · Inspect task `q36s_pass4_k1`
(`uv run inspect view --log-dir ../logs/inspect --port 7591`)

Failure tags: wrong-logic / wrong-output-shape / wrong-filter-value / doc-misread / gave-up(step-cap) / dialect-or-tool-issue. For losses, find the divergence step: first SQL committing to wrong logic — what visible info was ignored, which tool would have caught it? Flag fragile successes (unverified filters, lucky guesses).


## Person 1 — 45 questions (22 failures, 23 successes)

| instance | db | outcome | detail | steps | status |
|---|---|---|---|---|---|
| local141 | AdventureWorks | FAILURE | result_mismatch | 30 | fallback |
| local009 | Airlines | FAILURE | result_mismatch | 30 | fallback |
| local010 | Airlines | FAILURE | result_mismatch | 30 | fallback |
| local015 | California_Traffic_Collision | FAILURE | result_mismatch | 30 | fallback |
| local017 | California_Traffic_Collision | FAILURE | result_mismatch | 16 | submitted |
| local018 | California_Traffic_Collision | FAILURE | result_mismatch | 20 | submitted |
| local220 | EU_soccer | FAILURE | result_mismatch | 25 | submitted |
| local064 | bank_sales_trading | FAILURE | result_mismatch | 15 | submitted |
| local074 | bank_sales_trading | FAILURE | result_mismatch | 24 | submitted |
| local157 | bank_sales_trading | FAILURE | result_mismatch | 14 | submitted |
| local285 | bank_sales_trading | FAILURE | result_mismatch | 20 | submitted |
| local297 | bank_sales_trading | FAILURE | result_mismatch | 15 | submitted |
| local298 | bank_sales_trading | FAILURE | result_mismatch | 30 | fallback |
| local299 | bank_sales_trading | FAILURE | result_mismatch | 29 | submitted |
| local302 | bank_sales_trading | FAILURE | result_mismatch | 21 | submitted |
| local061 | complex_oracle | FAILURE | result_mismatch | 22 | submitted |
| local062 | complex_oracle | FAILURE | result_mismatch | 13 | submitted |
| local209 | delivery_center | FAILURE | result_mismatch | 8 | submitted |
| local272 | oracle_sql | FAILURE | result_mismatch | 13 | submitted |
| local273 | oracle_sql | FAILURE | result_mismatch | 30 | fallback |
| local277 | oracle_sql | FAILURE | result_mismatch | 30 | fallback |
| local279 | oracle_sql | FAILURE | result_mismatch | 30 | fallback |
| local218 | EU_soccer | SUCCESS | matches local218_a.csv | 6 | submitted |
| local219 | EU_soccer | SUCCESS | matches local219_a.csv | 9 | submitted |
| local221 | EU_soccer | SUCCESS | matches local221_a.csv | 7 | submitted |
| local283 | EU_soccer | SUCCESS | matches local283_a.csv | 12 | submitted |
| local075 | bank_sales_trading | SUCCESS | matches local075_a.csv | 19 | submitted |
| local077 | bank_sales_trading | SUCCESS | matches local077_a.csv | 10 | submitted |
| local078 | bank_sales_trading | SUCCESS | matches local078_a.csv | 8 | submitted |
| local156 | bank_sales_trading | SUCCESS | matches local156_d.csv | 13 | submitted |
| local284 | bank_sales_trading | SUCCESS | matches local284_a.csv | 7 | submitted |
| local300 | bank_sales_trading | SUCCESS | matches local300_a.csv | 24 | submitted |
| local301 | bank_sales_trading | SUCCESS | matches local301_b.csv | 26 | submitted |
| local050 | complex_oracle | SUCCESS | matches local050_c.csv | 22 | submitted |
| local060 | complex_oracle | SUCCESS | matches local060_a.csv | 30 | fallback |
| local063 | complex_oracle | SUCCESS | matches local063_b.csv | 18 | submitted |
| local067 | complex_oracle | SUCCESS | matches local067_a.csv | 10 | submitted |
| local210 | delivery_center | SUCCESS | matches local210_b.csv | 8 | submitted |
| local212 | delivery_center | SUCCESS | matches local212_c.csv | 10 | submitted |
| local152 | imdb_movies | SUCCESS | matches local152_a.csv | 14 | submitted |
| local230 | imdb_movies | SUCCESS | matches local230_a.csv | 11 | submitted |
| local269 | oracle_sql | SUCCESS | matches local269_a.csv | 11 | submitted |
| local270 | oracle_sql | SUCCESS | matches local270_a.csv | 12 | submitted |
| local274 | oracle_sql | SUCCESS | matches local274_a.csv | 10 | submitted |
| local275 | oracle_sql | SUCCESS | matches local275_a.csv | 13 | submitted |

## Person 2 — 45 questions (26 failures, 19 successes)

| instance | db | outcome | detail | steps | status |
|---|---|---|---|---|---|
| local008 | Baseball | FAILURE | result_mismatch | 30 | fallback |
| local028 | Brazilian_E_Commerce | FAILURE | result_mismatch | 8 | submitted |
| local029 | Brazilian_E_Commerce | FAILURE | result_mismatch | 4 | submitted |
| local031 | Brazilian_E_Commerce | FAILURE | result_mismatch | 6 | submitted |
| local032 | Brazilian_E_Commerce | FAILURE | result_mismatch | 10 | submitted |
| local034 | Brazilian_E_Commerce | FAILURE | result_mismatch | 7 | submitted |
| local037 | Brazilian_E_Commerce | FAILURE | result_mismatch | 9 | submitted |
| local131 | EntertainmentAgency | FAILURE | result_mismatch | 6 | submitted |
| local132 | EntertainmentAgency | FAILURE | result_mismatch | 21 | submitted |
| local133 | EntertainmentAgency | FAILURE | result_mismatch | 5 | submitted |
| local021 | IPL | FAILURE | result_mismatch | 5 | submitted |
| local023 | IPL | FAILURE | result_mismatch | 24 | submitted |
| local024 | IPL | FAILURE | result_mismatch | 14 | submitted |
| local228 | IPL | FAILURE | result_mismatch | 17 | submitted |
| local229 | IPL | FAILURE | result_mismatch | 30 | fallback |
| local258 | IPL | FAILURE | result_mismatch | 30 | fallback |
| local259 | IPL | FAILURE | result_mismatch | 30 | fallback |
| local059 | education_business | FAILURE | result_mismatch | 8 | submitted |
| local163 | education_business | FAILURE | result_mismatch | 5 | submitted |
| local253 | education_business | FAILURE | result_mismatch | 23 | submitted |
| local330 | log | FAILURE | result_mismatch | 10 | submitted |
| local331 | log | FAILURE | result_mismatch | 30 | fallback |
| local360 | log | FAILURE | result_mismatch | 30 | fallback |
| local049 | modern_data | FAILURE | result_mismatch | 9 | submitted |
| local066 | modern_data | FAILURE | result_mismatch | 18 | submitted |
| local201 | modern_data | FAILURE | result_mismatch | 16 | submitted |
| local007 | Baseball | SUCCESS | matches local007_c.csv | 15 | submitted |
| local128 | BowlingLeague | SUCCESS | matches local128_a.csv | 15 | submitted |
| local030 | Brazilian_E_Commerce | SUCCESS | matches local030_a.csv | 9 | submitted |
| local035 | Brazilian_E_Commerce | SUCCESS | matches local035_a.csv | 7 | submitted |
| local020 | IPL | SUCCESS | matches local020_a.csv | 16 | submitted |
| local022 | IPL | SUCCESS | matches local022_a.csv | 14 | submitted |
| local025 | IPL | SUCCESS | matches local025_e.csv | 10 | submitted |
| local026 | IPL | SUCCESS | matches local026_a.csv | 29 | submitted |
| local058 | education_business | SUCCESS | matches local058_a.csv | 7 | submitted |
| local114 | education_business | SUCCESS | matches local114_d.csv | 6 | submitted |
| local329 | log | SUCCESS | matches local329_a.csv | 10 | submitted |
| local358 | log | SUCCESS | matches local358_a.csv | 8 | submitted |
| local040 | modern_data | SUCCESS | matches local040_b.csv | 11 | submitted |
| local041 | modern_data | SUCCESS | matches local041_a.csv | 5 | submitted |
| local065 | modern_data | SUCCESS | matches local065_b.csv | 7 | submitted |
| local073 | modern_data | SUCCESS | matches local073_b.csv | 30 | fallback |
| local244 | music | SUCCESS | matches local244_a.csv | 9 | submitted |
| local081 | northwind | SUCCESS | matches local081_a.csv | 8 | submitted |
| local085 | northwind | SUCCESS | matches local085_a.csv | 6 | submitted |

## Person 3 — 45 questions (23 failures, 22 successes)

| instance | db | outcome | detail | steps | status |
|---|---|---|---|---|---|
| local096 | Db-IMDB | FAILURE | result_mismatch | 19 | submitted |
| local098 | Db-IMDB | FAILURE | result_mismatch | 30 | fallback |
| local002 | E_commerce | FAILURE | result_mismatch | 18 | submitted |
| local003 | E_commerce | FAILURE | result_mismatch | 30 | fallback |
| local004 | E_commerce | FAILURE | result_mismatch | 7 | submitted |
| local039 | Pagila | FAILURE | result_mismatch | 17 | submitted |
| local070 | city_legislation | FAILURE | result_mismatch | 17 | submitted |
| local168 | city_legislation | FAILURE | result_mismatch | 22 | submitted |
| local169 | city_legislation | FAILURE | result_mismatch | 21 | submitted |
| local171 | city_legislation | FAILURE | result_mismatch | 13 | submitted |
| local202 | city_legislation | FAILURE | result_mismatch | 10 | submitted |
| local286 | electronic_sales | FAILURE | result_mismatch | 11 | submitted |
| local309 | f1 | FAILURE | result_mismatch | 25 | submitted |
| local335 | f1 | FAILURE | result_mismatch | 30 | fallback |
| local336 | f1 | FAILURE | result_mismatch | 30 | fallback |
| local344 | f1 | FAILURE | result_mismatch | 30 | fallback |
| local354 | f1 | FAILURE | result_mismatch | 17 | submitted |
| local355 | f1 | FAILURE | result_mismatch | 27 | submitted |
| local356 | f1 | FAILURE | result_mismatch | 30 | fallback |
| local130 | school_scheduling | FAILURE | result_mismatch | 12 | submitted |
| local056 | sqlite-sakila | FAILURE | result_mismatch | 11 | submitted |
| local194 | sqlite-sakila | FAILURE | result_mismatch | 14 | submitted |
| local264 | stacking | FAILURE | result_mismatch | 4 | submitted |
| local097 | Db-IMDB | SUCCESS | matches local097_a.csv | 13 | submitted |
| local099 | Db-IMDB | SUCCESS | matches local099_b.csv | 22 | submitted |
| local100 | Db-IMDB | SUCCESS | matches local100_a.csv | 16 | submitted |
| local038 | Pagila | SUCCESS | matches local038_b.csv | 8 | submitted |
| local019 | WWE | SUCCESS | matches local019_a.csv | 14 | submitted |
| local054 | chinook | SUCCESS | matches local054_a.csv | 10 | submitted |
| local055 | chinook | SUCCESS | matches local055_a.csv | 15 | submitted |
| local198 | chinook | SUCCESS | matches local198_a.csv | 7 | submitted |
| local068 | city_legislation | SUCCESS | matches local068_a.csv | 9 | submitted |
| local071 | city_legislation | SUCCESS | matches local071_a.csv | 8 | submitted |
| local072 | city_legislation | SUCCESS | matches local072_d.csv | 12 | submitted |
| local167 | city_legislation | SUCCESS | matches local167_a.csv | 12 | submitted |
| local170 | city_legislation | SUCCESS | matches local170_a.csv | 23 | submitted |
| local310 | f1 | SUCCESS | matches local310_a.csv | 6 | submitted |
| local311 | f1 | SUCCESS | matches local311_a.csv | 24 | submitted |
| local193 | sqlite-sakila | SUCCESS | matches local193_a.csv | 10 | submitted |
| local195 | sqlite-sakila | SUCCESS | matches local195_c.csv | 7 | submitted |
| local196 | sqlite-sakila | SUCCESS | matches local196_a.csv | 11 | submitted |
| local197 | sqlite-sakila | SUCCESS | matches local197_a.csv | 7 | submitted |
| local199 | sqlite-sakila | SUCCESS | matches local199_a.csv | 7 | submitted |
| local262 | stacking | SUCCESS | matches local262_a.csv | 8 | submitted |
| local263 | stacking | SUCCESS | matches local263_a.csv | 19 | submitted |