# Spider 2.0 NL2SQL Error Analysis — `run_20260416_142322`

Analysis generated from [`token_category_estimate.json`](token_category_estimate.json): gold evaluation uses the same `score_against_gold` logic as [`scripts/spider2_benchmark.py`](../../../scripts/spider2_benchmark.py), with the submitted result table reconstructed from trace `ToolMessage` CSV text.

## Run summary

| Field | Value |
|--------|--------|
| **SQL agent model** | `google_vertexai:gemini-2.5-pro` (Vertex AI) |
| **Framework** | databao-agent (LangGraph, Lighthouse executor) |
| **Trace directory** | `logs/traces/run_20260416_142322` |
| **Run date** | 2026-04-16 (from trace timestamps) |
| **Questions in this run** | 115 |

### Headline metrics

| Metric | Value |
|--------|--------|
| **Correct** | **39 / 115 (33.91%)** |
| **Wrong / incomplete** | 76 / 115 (66.09%) |
| **Total input tokens** (sum over instances) | 2,888,498 |
| **Total output tokens** (sum over instances) | 116,995 |

Token totals are **per-question sums** from trace `_meta` (`total_input_tokens` / `total_output_tokens`), comparable to usage reported by the Vertex/Gemini stack for those turns.

---

## 1. Failure mode breakdown (`classify_error` categories)

Categories follow [`classify_error`](../../../scripts/spider2_benchmark.py): `correct` means `score == 1` on gold; other labels describe *why* the run was not scored as correct (including cases where SQL ran but gold did not match).

| Category | Count | In tokens (sum) | Out tokens (sum) | Notes |
|----------|------:|----------------:|-----------------:|--------|
| **correct** | 39 | 952,463 | 40,097 | Matches official exec_result gold |
| **sql_execution_error** | 29 | 1,321,023 | 53,291 | At least one failed `run_sql_query` in the trace *and* final outcome not correct (see §1.1) |
| **result_mismatch** | 18 | 386,066 | 17,410 | SQL ran and submitted; gold mismatch; no qualifying SQL error trail for this label |
| **recursion_limit** | 22 | 69,637 | **0** | `hit_recursion_limit` in trace; **zero output tokens** — model often returned no tool-calling step |
| **agent_error** | 6 | 154,606 | 6,016 | No submit; had SQL attempts (`score_detail`: `agent_error`) |
| **no_sql** | 1 | 4,703 | 181 | No submit; no SQL attempts |

### 1.1 How to read `sql_execution_error` vs `result_mismatch`

Both imply **incorrect gold** for this run (unless overridden by `score == 1`, which maps to **correct** first).

- **`sql_execution_error`**: The trace records at least one DuckDB/SQL error during the episode (`tool_call_log` / `classify_error` path). These runs are often **high token** (retries, long errors in context).
- **`result_mismatch`**: Submitted answer evaluated as wrong, without hitting the “SQL error history” branch—typically **wrong logic**, filters, joins, or shape versus gold.

---

## 2. Instances by category (for deep dives)

### 2A. Correct (39)

`local007`, `local017`, `local022`, `local023`, `local024`, `local026`, `local028`, `local030`, `local031`, `local035`, `local039`, `local040`, `local041`, `local049`, `local054`, `local058`, `local065`, `local066`, `local067`, `local068`, `local072`, `local075`, `local077`, `local081`, `local085`, `local114`, `local128`, `local132`, `local167`, `local198`, `local202`, `local212`, `local218`, `local219`, `local221`, `local244`, `local300`, `local331`, `local358`

### 2B. Result mismatch (18)

`local019`, `local020`, `local050`, `local059`, `local063`, `local133`, `local156`, `local168`, `local169`, `local171`, `local210`, `local258`, `local297`, `local298`, `local302`, `local329`, `local330`, `local360`

### 2C. SQL execution error (29)

`local009`, `local015`, `local018`, `local021`, `local032`, `local034`, `local037`, `local038`, `local061`, `local062`, `local070`, `local073`, `local074`, `local097`, `local100`, `local131`, `local163`, `local170`, `local194`, `local196`, `local197`, `local209`, `local220`, `local228`, `local230`, `local253`, `local286`, `local299`, `local301`

### 2D. Recursion limit (22)

`local002`, `local003`, `local004`, `local008`, `local010`, `local025`, `local029`, `local055`, `local060`, `local064`, `local071`, `local078`, `local130`, `local141`, `local152`, `local157`, `local201`, `local229`, `local259`, `local283`, `local284`, `local285`

### 2E. Agent error (6)

`local056`, `local096`, `local098`, `local099`, `local193`, `local199`

### 2F. No SQL (1)

`local195`

---

## 3. Per-database performance (this run only)

Databases come from `Spider2/spider2-lite/spider2-lite.jsonl`. Sort order: higher accuracy first, then by name.

| Database | Correct / Total | Accuracy |
|----------|-----------------|----------|
| BowlingLeague | 1/1 | 100% |
| music | 1/1 | 100% |
| northwind | 2/2 | 100% |
| modern_data | 5/7 | 71% |
| chinook | 2/3 | 67% |
| EU_soccer | 3/5 | 60% |
| Baseball | 1/2 | 50% |
| Brazilian_E_Commerce | 4/8 | 50% |
| Pagila | 1/2 | 50% |
| city_legislation | 4/10 | 40% |
| education_business | 2/5 | 40% |
| log | 2/5 | 40% |
| IPL | 4/11 | 36% |
| California_Traffic_Collision | 1/3 | 33% |
| EntertainmentAgency | 1/3 | 33% |
| delivery_center | 1/3 | 33% |
| bank_sales_trading | 3/15 | 20% |
| complex_oracle | 1/6 | 17% |
| AdventureWorks | 0/1 | 0% |
| Airlines | 0/2 | 0% |
| Db-IMDB | 0/5 | 0% |
| E_commerce | 0/3 | 0% |
| WWE | 0/1 | 0% |
| electronic_sales | 0/1 | 0% |
| imdb_movies | 0/2 | 0% |
| school_scheduling | 0/1 | 0% |
| sqlite-sakila | 0/7 | 0% |

**Notable clusters**

- **`bank_sales_trading` (3/15)** — Mix of recursion (5), `sql_execution_error` (3), `result_mismatch` (4); largest schema load in this track.
- **`Db-IMDB` / `sqlite-sakila` (0% in sample)** — Dominated by **`agent_error`** and **`sql_execution_error`** in this run, not by gold-correct submissions.
- **`recursion_limit` (22 cases)** — Concentrated on large-schema / hard episodes (`bank_sales_trading`, `IPL`, `E_commerce`, etc.); **0 output tokens** suggests the model stopped emitting actionable tool calls before the graph exhausted steps.

---

## 4. Root-cause themes (this run)

1. **Recursion / no forward progress (22)** — Empty output token totals align with **no successful tool loop** before the LangGraph cap. Mitigations: stricter “must call `search_context` / `run_sql_query` by step N” in the prompt, lower recursion threshold for strategy switch, or model settings that favor tool calls over long reasoning-only turns.
2. **SQL dialect & schema friction (29 in `sql_execution_error`)** — Wrong table names, catalog prefixes, or DuckDB/SQLite edge cases; often recoverable with retries but burn tokens.
3. **Semantic / logic errors (18 `result_mismatch`)** — Joins, filters, aggregates, or output shape do not match gold despite executing SQL.
4. **`agent_error` without submit (6)** — Timeouts, API errors, or executor failures mid-episode (see trace `error` fields in full JSON if logged elsewhere).

---

## 5. Priority fix list (ranked for *this* run)

| Priority | Direction | Rough impact (from counts) |
|----------|-----------|----------------------------|
| **P0** | Reduce **recursion_limit** episodes (tool-use forcing, shorter reasoning, step budget) | Up to **22** instances |
| **P1** | Cut **sql_execution_error** retries (schema hints, `search_context` quality, DuckDB prefix examples) | Up to **29** instances |
| **P2** | Target **`result_mismatch`** with pre-submit shape checks and domain checks | Up to **18** instances |
| **P3** | Stabilize **Db-IMDB / sqlite-sakila** (agent_error + sql errors) | 5 + 7 instances in DB tables |

---

## 6. Regenerating this report

```bash
uv --project databao-agent run python scripts/trace_token_category_estimate.py \
  --trace-dir logs/traces/run_20260416_142322
```

Outputs `token_category_estimate.json` next to the traces; edit this file or re-run after new traces.
