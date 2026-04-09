# NL2SQL Error Analysis & Fix Plan
## Spider 2.0 Local SQLite · Qwen3-32B-AWQ · 124 Questions · 15/124 (12%)

---

## Full Error Breakdown

Of the 109 questions that failed, every failure falls into one of these buckets:

| Error | Questions | Root cause | Fixed by |
|-------|----------:|-----------|---------|
| DCE index not built | 11 | `sqlite_sakila` + `db_imdb` embeddings missing — agent is completely blind | Infra fix (rebuild index) |
| Context overflow | 14 | Schema exceeds model's 40K token limit — crashes before first tool call | Model switch (primary) · partial via config |
| Recursion loop | 11 | Agent guesses wrong column names repeatedly until LangGraph cuts it off | Config fix + model switch |
| Agent abandoned | 18 | Question too complex — agent describes the answer in text instead of writing SQL | Model switch |
| Parse error | 1 | Model outputs SQL as a raw string instead of a JSON tool call | Model switch |
| Wrong enum/literal | 8 | SQL correct but filter value doesn't match actual data — result is empty | Prompt rule (SELECT DISTINCT first) · DCE enrichment · frontier model may self-explore |
| DuckDB dialect error | 5 | Uses unavailable functions (`LOAD spatial`, `INTERVAL` cast, `AVG` for median) | Prompt fix (DUCKDB_HINTS) |
| Missing final step | 5 | Gets the data but forgets to divide/filter/rank at the end | Prompt rule |
| Wrong output format | 4 | Returns long rows when question wants wide/pivoted output | Prompt fix (PIVOT hint) |
| Missing zero entities | 3 | INNER JOIN drops entities with zero counts | Prompt rule |
| Wrong window logic | 9 | Correct window function syntax, wrong frame or partition | Prompt fix + model switch |
| Trivially wrong SQL | 7 | Model couldn't formulate the algorithm, submitted a stub query | Model switch |
| Multi-step collapsed | 23 | 2–4 aggregation steps required; model collapses them into one | Model switch (primary) · prompt rule helps |
| Result too large | 4 | Returns 1000-row raw scan instead of aggregated answer | Prompt rule |

```
Total failures: 109
├── Infra-only fixes (no model needed):    19  →  DCE not built (11) + wrong enum (8)
├── Prompt/config fixes (any model):       26  →  dialect (5) + format (4) + zeros (3)
│                                                  + row cap (4) + missing step (5) + partial window (5)
└── Model switch needed:                   64  →  overflow (14) + abandoned (18) + parse (1)
                                                  + trivially wrong (7) + multi-step (23) + partial window (4)
```

### What a model switch (GPT-4o / Gemini 2.5 Pro) recovers

| Verdict | Questions | What it means |
|---------|----------:|--------------|
| ✅ YES — model fixes it | 48 | Frontier model very likely solves these |
| ⚠️ PARTIAL — helps but not complete | 41 | Recovers majority; some hard cases remain |
| ❌ NO — model change alone doesn't help | 19 | Needs infra fix regardless of model |

**Realistic accuracy targets:**
- Current (Qwen3-32B-AWQ, no fixes): **12%**
- After infra + prompt fixes only (no model change): **~30–39%**
- With GPT-4o / Gemini 2.5 Pro + all fixes: **~50–65%**

---

## What We Can Fix Without Switching the Model

**Estimated score after all 5 fixes below: ~37–48/124 (~30–39%)**

---

## Fix 1 — Rebuild DCE index for 2 missing databases
**Impact: +8–11 questions · Effort: 1 command**

Two databases — `sqlite_sakila` and `db_imdb` — were never indexed. Every schema lookup returns:
```
ValueError: Context is not built. Call build_context() before searching.
```
The agent retries 5 times, exhausts its tool budget, and gives up without writing a single SQL statement. This affects **11 questions** (6 on sqlite_sakila, 5 on db_imdb) — all score 0, none generate any SQL.

**Fix:**
```bash
cd spider2-dce
dce build --db sqlite_sakila --db db_imdb
```

---

## Fix 2 — Add sample values for categorical columns in DCE YAML
**Impact: +4–6 questions · Effort: enum scan script → edit YAML → re-run dce build**

The agent writes structurally correct SQL but filters on guessed string literals. The result is always an empty DataFrame. This happens because DCE describes columns in natural language but never records actual stored values.

Example from `california_traffic_collision.yaml`:
```
# Current (useless for filtering):
description: "primary safety equipment used by the party, such as seat belts or airbags"

# Needed:
description: "primary safety equipment code. Distinct values: 'E' (helmet),
              'A' (air bag), 'G' (lap/shoulder belt), 'H' (no restraint), 'X' (not applicable)"
```

**Important: the existing critique script (`experiment_critique_enrich.py`) does NOT directly fix this.** It is designed to disambiguate similarly-named sibling columns — sample values only get cited as a side effect of comparing two similar columns. For a column with no obvious sibling (e.g. `ClassStatus`, `term_end`), the critique pass leaves it untouched.

**What's needed instead — a targeted enum scan:**
```sql
-- Step 1: detect low-cardinality (categorical) columns
SELECT column_name, COUNT(DISTINCT column_name) AS n_distinct
FROM information_schema.columns  -- per table
-- Step 2: for columns with n_distinct < 30, document all values
SELECT DISTINCT col, COUNT(*) AS freq FROM table GROUP BY col ORDER BY freq DESC
```
Then inject those values directly into the YAML description, and re-run `dce build`.

**Note:** This is also partially addressed by prompt hint #8 in Fix 3 — telling the agent to always run `SELECT DISTINCT` before filtering on coded columns. That prompt rule works with the current model and requires no YAML changes. The DCE enrichment approach is more reliable but higher effort.

**Priority columns:**

| Database | Column | Agent guesses | Actual values |
|----------|--------|--------------|---------------|
| California_Traffic_Collision | `parties.party_safety_equipment_1` | `'helmet used'` | Single-char codes: `'E'`, `'A'`, `'G'`... |
| school_scheduling | `Student_Schedules.ClassStatus` | `ClassStatus = 2` | Unknown without scan |
| city_legislation | `legislators_terms.term_end` | `'December, 31'` | ISO date string |
| f1 | table name | `f1.main.drives` | `f1.main.driver_standings` |
| log | date reference | `CURRENT_DATE` (2026) | Fixed year matching data era |

---

## Fix 3 — Add missing DuckDB dialect hints
**Impact: +3–5 questions · Effort: edit DUCKDB_HINTS in benchmark script**

Several questions fail because the agent uses SQL functions that don't exist in DuckDB, or misuses ones that do. These are deterministic failures — the SQL runs but returns wrong results or errors every time.

**Add these to `DUCKDB_HINTS` in [scripts/spider2_benchmark.py](scripts/spider2_benchmark.py):**

```python
# Haversine distance (spatial extension is NOT installed — never use LOAD spatial):
2 * ASIN(SQRT(
  POWER(SIN(RADIANS(lat2 - lat1) / 2), 2) +
  COS(RADIANS(lat1)) * COS(RADIANS(lat2)) *
  POWER(SIN(RADIANS(lon2 - lon1) / 2), 2)
)) * 6371  -- km

# Median (never use AVG as substitute):
PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY col)

# LIKE with hyphen — single % only, no escaping needed:
'%-%'   -- correct;   '%-%%'  -- WRONG

# STRING_SPLIT returns VARCHAR — always CAST before joining to integer:
CAST(TRIM(UNNEST(STRING_SPLIT(col, ','))) AS INTEGER)

# Duration from HH:MM:SS string — no INTERVAL cast in DuckDB:
CAST(SPLIT_PART(col,':',1) AS INT)*3600 + CAST(SPLIT_PART(col,':',2) AS INT)*60
  + CAST(SPLIT_PART(col,':',3) AS INT)

# Wide pivot output:
PIVOT (SELECT year, month, cnt FROM t) ON year IN (2016,2017,2018)
USING SUM(cnt) GROUP BY month
```

---

## Fix 4 — Add agent behavior rules to system prompt
**Impact: +5–7 questions · Effort: edit system prompt in benchmark script**

Several failures are not SQL dialect issues — they are the agent misreading the question or not checking its own output. A few prompt rules catch these reliably.

**Add to system prompt:**

```
1. After writing SQL, re-read the question word by word. If it asks for a percentage,
   ensure you divide. If it asks for a ratio or "per X", ensure the denominator is correct.

2. If the question says "including zero", "all X", or asks for fewest/minimum:
   start from the full entity table and LEFT JOIN counts onto it.
   NEVER use INNER JOIN for this pattern — it silently drops zero-count rows.

3. Your result is capped at 1000 rows. If the expected answer is a ranked list,
   a count, or a single value — ensure GROUP BY + LIMIT is in the final SELECT.
   Never submit a raw table scan as the answer.

4. Before filtering on a status, category, or code column, run:
   SELECT DISTINCT col FROM table LIMIT 20
   to confirm the actual stored values. Never guess string literals.
```

---

## Fix 5 — Reduce schema truncation for large databases
**Impact: +2–4 questions (partial) · Effort: config change**

14 questions fail with HTTP 400 (context overflow) — the schema alone fills the model's 40K token window. While fully solving this requires a larger-context model, we can reduce overflow frequency by tightening schema truncation for large-schema databases.

**Change in [scripts/spider2_benchmark.py](scripts/spider2_benchmark.py):**
```python
# Current:
executor._max_schema_summary_length = 60_000

# Change to:
executor._max_schema_summary_length = 20_000  # cuts overflow cases for complex_oracle, log, f1
```

This won't eliminate all 14 overflow cases but gives the model room to generate output for the medium-sized schemas (BowlingLeague, EU_soccer, IPL) that currently overflow.

---

## Summary

| Fix | What it does | Questions recovered | Effort |
|-----|-------------|--------------------:|--------|
| 1 · Rebuild DCE index | Agent can see 2 missing databases | +8–11 | Low — 1 command |
| 2 · Enrich enum columns | Agent uses correct filter values | +4–6 | Medium — inspect + edit 5 YAMLs |
| 3 · DuckDB dialect hints | Eliminates deterministic SQL errors | +3–5 | Low — edit 1 string in benchmark script |
| 4 · Agent behavior rules | Catches wrong aggregation, missing LEFT JOIN, row cap | +5–7 | Low — edit system prompt |
| 5 · Schema truncation | Reduces some overflow crashes | +2–4 | Low — change 1 config value |
| | **Total estimated** | **+22–33** | |

**Score after all 5 fixes (no model change): ~37–48/124 (~30–39%)**
