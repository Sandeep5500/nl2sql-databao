# Spider 2.0 NL2SQL Error Analysis — GLM-4.7-Flash-AWQ (vLLM 0.18.1)

## Run Summary

- **SQL Agent Model**: QuantTrio/GLM-4.7-Flash-AWQ (MoE 30B-A3B, INT4 AWQ)
- **Inference Server**: vLLM 0.18.1, L40S (25K context) + A100_80GB (60K context)
- **Embedding Model**: nomic-embed-text-v1.5 (via Ollama/fast_embed_server)
- **DCE Enrichment Model**: Qwen/Qwen3-32B-AWQ (critique pass for column descriptions)
- **Framework**: databao-agent (LangGraph, Lighthouse executor)
- **Date**: April 10-11, 2026

| Metric | Value |
|--------|-------|
| **Total Questions** | 124 (135 local track − 11 excluded) |
| **Correct** | 25 (20.2%) |
| **Result Mismatch** | 53 (42.7%) |
| **Agent Error** | 31 (25.0%) |
| **No SQL Submitted** | 15 (12.1%) |

---

## 1. Result Mismatch Breakdown (53 questions)

These are cases where the agent produced SQL, executed it, but the output didn't match the gold answer.

### 1A. Wrong Aggregation (16 cases)

Agent computes the wrong aggregate — SUM vs AVG, wrong denominator, double-counting due to bad JOINs, or applying aggregation at the wrong granularity.

| Instance | DB | Pattern |
|----------|-----|---------|
| local015, local018 | California_Traffic_Collision | Aggregating over wrong grouping level |
| local021, local023, local024, local025, local026, local258, local259 | IPL | Cricket stats — complex multi-table aggregation (runs, wickets, averages) |
| local029, local034 | Brazilian_E_Commerce | Order/payment aggregation with wrong JOIN multiplying rows |
| local062, local067 | complex_oracle | NTILE bucket profit calculation — wrong profit formula (used `amount_sold - total_cost` instead of `quantity_sold × (unit_price - unit_cost)`) |
| local202 | city_legislation | Aggregating counts incorrectly |
| local302 | bank_sales_trading | Wrong grouping producing 19 rows instead of 1 |

**Root cause**: The agent often has the right structure but uses incorrect column expressions for business metrics. Profit, revenue, and rate calculations are especially fragile — the column names don't self-document the formula.

**Fix direction**: Inject domain-specific formula hints when external knowledge documents are available. Add a prompt rule: "before computing a metric like profit/revenue/rate, search for the exact column formula."

---

### 1B. Date/Time Logic Errors (13 cases)

Incorrect date parsing, wrong time window filtering, broken consecutive-day detection (gap-and-islands), or wrong date arithmetic.

| Instance | DB | Pattern |
|----------|-----|---------|
| local004 | E_commerce | Customer lifespan calculation — wrong date diff |
| local028 | Brazilian_E_Commerce | Date filtering off-by-one |
| local059, local253 | education_business | Academic year/semester boundary logic |
| local061 | complex_oracle | Projected sales date window |
| local064, local074, local297, local299 | bank_sales_trading | Monthly/quarterly date grouping |
| local068, local071, local072 | city_legislation | **Gap-and-islands consecutive streak** — agent uses LAG/age() instead of `date - ROW_NUMBER()` grouping |
| local130 | school_scheduling | Schedule date calculation |

**Root cause**: Two main sub-patterns:
1. **Consecutive-day detection** (gap-and-islands): The agent consistently fails this. It uses `LAG()` comparisons or `age()` which break on gaps. The correct DuckDB approach is `date_trunc('day', d) - INTERVAL (ROW_NUMBER() OVER (ORDER BY d)) DAY` as a grouping key.
2. **Date boundary logic**: Off-by-one errors on month/year boundaries, wrong timezone handling, incorrect BETWEEN ranges.

**Fix direction**: Add gap-and-islands SQL pattern to DuckDB hints. Add examples for `date_trunc` + `ROW_NUMBER` grouping technique.

---

### 1C. Wrong Output Shape (10 cases)

The query returns a fundamentally different number of rows or columns than expected.

| Instance | DB | Got → Gold |
|----------|-----|-----------|
| local008 | Baseball | 20 → 4 rows (wanted 4 metrics, got per-player) |
| local022 | IPL | 444 → 7 rows (wanted per-season, got per-match) |
| local026 | IPL | 10 → 3 rows (wanted top 3, returned top 10) |
| local163 | education_business | 8 → 4 rows |
| local202 | city_legislation | 10 → 1 row |
| local258 | IPL | 10 → 330 rows (wanted per-match, got per-player) |
| local302 | bank_sales_trading | 19 → 1 row |
| local330 | log | 9 → 5 rows |
| local331 | log | wrong shape |
| local356 | f1 | wrong shape |

**Root cause**: The agent doesn't always re-read the question before submitting. "Top 3" becomes "top 10", "one row per season" becomes "one row per match", etc. The pre-submit checklist catches some of these but not all.

**Fix direction**: Strengthen pre-submit checklist rule #1 (output shape) and #4 (row count sanity). Consider adding a forced verification step: "BEFORE submit_result, run SELECT COUNT(*) on your query and compare against what the question asks for."

---

### 1D. Window Function Errors (6 cases)

Incorrect NTILE bucketing, ROW_NUMBER partitioning, or running total logic.

| Instance | DB | Pattern |
|----------|-----|---------|
| local037 | Brazilian_E_Commerce | Wrong NTILE partition |
| local059, local163 | education_business | Running total / rank |
| local130 | school_scheduling | Wrong ranking window |
| local299 | bank_sales_trading | Quarterly rolling window |
| local331 | log | Cumulative / running total |

**Root cause**: Window function semantics (PARTITION BY vs ORDER BY, frame specification) are error-prone. The agent often gets the PARTITION BY clause wrong, causing aggregation at the wrong level.

**Fix direction**: Add window function examples to DuckDB hints, especially NTILE with correct PARTITION BY.

---

### 1E. Missing/Misapplied External Knowledge (4 cases)

The question provides an external document (RFM definition, projection formula, cricket terminology) but the agent ignores or misinterprets it.

| Instance | DB | Document |
|----------|-----|---------|
| local003 | E_commerce | RFM.md (customer segmentation rules) |
| local061 | complex_oracle | projection_calculation.md |
| local258, local259 | IPL | baseball_game_special_words_definition.md |

**Root cause**: The agent reads the document but doesn't faithfully apply the specific thresholds, formulas, or definitions. It substitutes general domain knowledge instead.

**Fix direction**: Pre-submit checklist #6 (external knowledge compliance) exists but isn't enforced strongly enough. Consider injecting the document content directly into the system prompt rather than relying on the agent to reference it.

---

### 1F. Wrong Filter / WHERE Clause (3 cases)

| Instance | DB | Pattern |
|----------|-----|---------|
| local097 | Db-IMDB | Missing or wrong filter condition |
| local196 | sqlite-sakila | Filter on wrong table |
| local253 | education_business | Wrong predicate |

---

### 1G. Wrong JOIN Logic (2 cases)

| Instance | DB | Pattern |
|----------|-----|---------|
| local032 | Brazilian_E_Commerce | Wrong join key |
| local210 | delivery_center | Missing or extra join |

---

### 1H. Other / Uncategorized (5 cases)

| Instance | DB |
|----------|-----|
| local099, local100 | Db-IMDB |
| local193, local199 | sqlite-sakila |
| local354 | f1 |

---

## 2. Agent Error Breakdown (31 questions)

These are cases where the agent threw an exception and never submitted a result.

### 2A. Recursion Limit Hit (11 cases)

Agent looped for 30 steps (60 LangGraph nodes) without submitting. Typically stuck in a doom-loop of similar SQL errors.

| Instance | DB |
|----------|-----|
| local017 | California_Traffic_Collision |
| local039 | Pagila |
| local055 | chinook |
| local060 | complex_oracle |
| local096, local098 | Db-IMDB |
| local131 | EntertainmentAgency |
| local194, local197 | sqlite-sakila |
| local244 | music |
| local284 | bank_sales_trading |

**Root cause**: The doom-loop prevention rule (switch strategy after 3 consecutive same-type errors) isn't aggressive enough. Agent retries slight variations of the same broken approach.

**Fix direction**: Lower the doom-loop threshold from 3 to 2. Add a rule: "after 15 steps without a successful query, submit your best-effort answer rather than continuing."

---

### 2B. Context Length Exceeded (10 cases)

Agent's message history exceeded vLLM's max context (25K tokens on L40S). Returns HTTP 400.

| Instance | DB |
|----------|-----|
| local010 | Airlines |
| local078 | bank_sales_trading |
| local170 | city_legislation |
| local219, local220, local283 | EU_soccer |
| local229 | IPL |
| local310, local355 | f1 |
| local360 | log |

**Root cause**: Large schemas (EU_soccer, f1, IPL) produce massive search_context results that fill context quickly. Combined with long SQL queries and error messages from failed attempts, the history exceeds 25K tokens within ~10 steps.

**Fix direction**:
1. Use A100_80GB (60K context) instead of L40S (25K) to eliminate this category entirely.
2. Reduce `max_tokens_before_cleaning` from 5000 to 3000 to compact history earlier.
3. Truncate search_context results to top-5 chunks.

---

### 2C. Connection Error (8 cases)

vLLM crashed or was unreachable mid-question.

| Instance | DB |
|----------|-----|
| local050, local062, local063, local067 | complex_oracle |
| local068, local070, local071, local072 | city_legislation |
| local073 | modern_data |

**Root cause**: vLLM bus errors from transformers 5.5.3 + broken regex. **Now fixed** — transformers 5.5.3 + regex >= 2025.10.22.

---

### 2D. Request Timeout (2 cases)

| Instance | DB |
|----------|-----|
| local056 | sqlite-sakila |
| local063 | complex_oracle |

**Root cause**: Single inference call exceeded 180s timeout. Likely a very long prompt hitting slow generation on L40S.

---

## 3. No SQL Submitted (15 questions)

Agent explored the schema but never attempted or submitted SQL.

### 3A. Agent Gave Up After Schema Exploration (10 cases)

7 messages, 0 SQL attempts, 2-3 search_context calls. Agent explored schema then terminated without trying any SQL.

| Instance | DB |
|----------|-----|
| local298, local077, local285 | bank_sales_trading |
| local167, local169 | city_legislation |
| local344, local336, local311 | f1 |
| local132 | EntertainmentAgency |
| local141 | AdventureWorks |

**Root cause**: After seeing a complex schema, the agent's final response gets truncated by `max_tokens=4096` before it can emit a `run_sql_query` tool call. The agent "thinks" extensively but runs out of output tokens before acting. With 7 messages and 0 SQL attempts, the agent likely wrote a long reasoning block and got cut off.

**Fix direction**: Increase `max_tokens` to 8192 on vLLM configurations that support it. Add prompt rule: "be concise in reasoning, prioritize tool calls over explanation."

---

### 3B. Agent Tried SQL But Never Submitted (3 cases)

Multiple SQL attempts but no `submit_result` call.

| Instance | DB | SQL Attempts |
|----------|-----|-------------|
| local066 | modern_data | 24 attempts |
| local195 | sqlite-sakila | 10 attempts |
| local201 | modern_data | 3 attempts |

**Root cause**: Agent kept iterating on SQL queries but never called `submit_result`. Likely hit the recursion limit (which shows as no_sql rather than agent_error when the exception is caught differently) or produced SQL that never returned satisfactory results.

---

### 3C. Agent Explored But Didn't Know What To Do (2 cases)

| Instance | DB |
|----------|-----|
| local020 | IPL (11 msgs, 4 search_context, 0 SQL) |
| local228 | IPL (9 msgs, 3 search_context, 0 SQL) |

**Root cause**: IPL schema is large and complex. Agent searched context multiple times but couldn't figure out which tables/columns to use.

---

## 4. Per-Database Performance

| Database | Score | Notes |
|----------|-------|-------|
| chinook | 2/3 (67%) | Best performer. Simple schema. |
| modern_data | 4/7 (57%) | Pizza shop — straightforward. |
| Baseball | 1/2 (50%) | |
| BowlingLeague | 1/1 (100%) | |
| WWE | 1/1 (100%) | |
| northwind | 1/2 (50%) | |
| imdb_movies | 1/2 (50%) | |
| Airlines | 1/2 (50%) | |
| log | 2/5 (40%) | |
| Brazilian_E_Commerce | 3/8 (38%) | |
| E_commerce | 1/3 (33%) | RFM external knowledge hurts |
| EntertainmentAgency | 1/3 (33%) | |
| delivery_center | 1/3 (33%) | |
| education_business | 1/5 (20%) | |
| EU_soccer | 1/5 (20%) | Context overflow due to schema size |
| bank_sales_trading | 2/15 (13%) | Largest DB, most failures |
| city_legislation | 1/10 (10%) | Consecutive-date logic failures |
| **IPL** | **0/11 (0%)** | Large schema + complex cricket stats |
| **f1** | **0/9 (0%)** | Large schema + context overflow |
| **sqlite-sakila** | **0/7 (0%)** | Recursion limits + timeouts |
| **complex_oracle** | **0/6 (0%)** | Connection errors + external knowledge |
| **Db-IMDB** | **0/5 (0%)** | Filter logic + recursion limits |
| **California_Traffic_Collision** | **0/3 (0%)** | Aggregation errors |
| Pagila | 0/2 (0%) | |
| school_scheduling | 0/1 (0%) | |
| AdventureWorks | 0/1 (0%) | |
| music | 0/1 (0%) | |
| electronic_sales | 0/1 (0%) | |

---

## 5. Priority Fix List

Ranked by expected accuracy improvement:

| Priority | Fix | Questions Affected | Expected Gain |
|----------|-----|--------------------|---------------|
| **P0** | Run on A100_80GB (60K context) | 10 context overflow | +5-7 questions |
| **P1** | Add gap-and-islands SQL hint | 5 consecutive-date failures | +3-4 questions |
| **P2** | Fix output shape verification (force COUNT check) | 10 wrong shape | +3-5 questions |
| **P3** | Increase max_tokens to 8192 | 10 no-sql (truncated output) | +3-5 questions |
| **P4** | Add NTILE/window function examples | 6 window errors | +2-3 questions |
| **P5** | Inject external knowledge into system prompt | 4 external knowledge | +1-2 questions |
| **P6** | Lower doom-loop threshold to 2 | 11 recursion limit | +2-3 questions |
| **P7** | Fix aggregation formula hints for business metrics | 16 wrong aggregation | +3-5 questions |

**Conservative estimate**: Implementing P0-P3 could yield ~15-20 additional correct answers, bringing the score from 25/124 (20%) to ~40-45/124 (32-36%).

---

## Error Analysis Template

To re-run this analysis on a new benchmark result:

```python
import csv, json, glob, os

# 1. Load results
with open('results/spider2_<timestamp>.csv') as f:
    rows = list(csv.DictReader(f))

# 2. Overall breakdown
from collections import Counter
details = Counter(r.get('score_detail','').split()[0] for r in rows)
print(details)

# 3. Per-database
for db in sorted(set(r['db'] for r in rows)):
    db_rows = [r for r in rows if r['db'] == db]
    correct = sum(1 for r in db_rows if r['score'] == '1')
    print(f'{db}: {correct}/{len(db_rows)}')

# 4. Agent errors
for r in rows:
    if r['score_detail'] == 'agent_error':
        print(f"{r['instance_id']}: {r['error'][:80]}")

# 5. Compare SQL vs gold for mismatches
gold_dir = 'Spider2/spider2-lite/evaluation_suite/gold/exec_result'
for r in rows:
    if r['score_detail'] == 'result_mismatch':
        golds = glob.glob(f'{gold_dir}/{r["instance_id"]}_*.csv')
        if golds:
            gold = open(golds[0]).read()[:200]
            print(f'{r["instance_id"]}: our={r["execution_result"][:80]} gold={gold[:80]}')
```
