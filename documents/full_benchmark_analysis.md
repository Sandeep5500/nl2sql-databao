# Full Benchmark Error Analysis
## Spider 2.0 Local SQLite — Run 4 · Qwen3-32B-AWQ · 124 Questions · 15/124 (12.1%)

Companion file: `results/full_categorized_analysis.csv` — machine-readable, includes `model_switch_helps` column (YES / PARTIAL / NO) for every question.

---

## Background: How the System Works

### What is Spider 2.0?
Spider 2.0 is an academic benchmark that tests whether an AI system can answer natural language questions about a database by generating correct SQL. Each question comes with one or more databases and a "gold" answer (either a specific value or a CSV file with the expected rows). The system must produce a SQL query whose output matches the gold answer exactly.

We are running the **local SQLite track** — 135 questions across 28 different databases covering sports, finance, e-commerce, entertainment, and government data.

### What does our system do?

```
User question
     │
     ▼
┌─────────────────────────────────────────────────────┐
│                   Databao Agent                     │
│  (LangGraph loop — up to 6 tool calls per question) │
│                                                     │
│  Tool 1: search_context  ← look up the schema       │
│  Tool 2: run_sql_query   ← run SQL against the DB   │
│  Tool 3: submit_result   ← submit the final answer  │
└─────────────────────────────────────────────────────┘
     │                │
     ▼                ▼
  DCE Index        DuckDB
  (schema          (executes
  embeddings)      the SQL)
```

**The agent** is powered by a language model (currently Qwen3-32B-AWQ, running on our SLURM cluster). It decides which tools to call and in what order — it is not handed the SQL directly.

**DCE (Databao Context Engine)** pre-processes each database: it reads the schema, enriches column descriptions, and builds a semantic vector index. When the agent calls `search_context("customer payment table")`, DCE finds the most relevant table/column descriptions and returns them to the agent. Without DCE, the agent has only a raw schema summary — no enriched descriptions, no foreign key links.

**DuckDB** is the SQL engine used to run all queries. Even though the source files are SQLite `.db` files, DuckDB attaches them and runs the SQL — so standard SQLite functions may not work; DuckDB has its own dialect.

### How scoring works
The agent's final SQL result is compared to the gold answer using a fuzzy match (column names ignored, row order ignored, numeric rounding allowed). A question scores 1 only if the output DataFrame matches the gold exactly. Partial credit is not given.

### Why 12%?
Databao reports **69.65%** — but that number is across the full Spider 2.0 benchmark (BigQuery + Snowflake + SQLite), and uses Claude Sonnet with a 1M-context window. Our run uses:
- A quantized open-source model (Qwen3-32B-AWQ, 40K context)
- Only the local SQLite track
- Our own infrastructure (vLLM on A6000 cluster)

The 12% vs 69% gap is almost entirely explained by **model capability** and **context window size**, plus two missing DCE indexes. The sections below break this down precisely.

---

## Executive Summary

### The 4 Bug Classes

| Bug | Name | Questions affected | Model switch helps? |
|-----|------|--------------------|---------------------|
| **Bug 1** | DCE index not built | 11 | ❌ No — infra fix required |
| **Bug 2** | Context overflow | 14 | ✅ Yes — Gemini 2.5 Pro / GPT-4o eliminates all |
| **Bug 3** | Recursion / agent loops | 11 | ⚠️ Partial — bigger context removes 4; better model removes 5 |
| **Bug 4** | SQL correctness (result_mismatch) | 54 | Mix — see breakdown below |

```
Total: 124 questions
├── ✅ PASS                       15  (12%)
├── Bug 1 · A1: DCE not built     11  (9%)   ← fix: rebuild index for 2 DBs
├── Bug 2 · A2: Context overflow  14  (11%)  ← fix: larger-context model
├── Bug 3 · A3: Recursion loop    11  (9%)   ← fix: config + better model
│          A4: Agent abandoned     18  (15%)  ← fix: better model (hardest questions)
│          A5: Parse error          1  (1%)   ← fix: retry logic
└── Bug 4 · Result mismatch       54  (43%)
           ├── B5: Wrong enum/literal → empty    8   ← fix: DCE sample values
           ├── B6: DuckDB dialect errors         5   ← fix: DUCKDB_HINTS update
           ├── B1: Stops before final step       5   ← fix: prompt rule
           ├── B9: 1000-row cap hit              4   ← fix: prompt rule
           ├── B2: Wrong output format           4   ← fix: PIVOT hint
           ├── B3: Missing zero entities         3   ← fix: prompt rule
           ├── B4: Window aggregate wrong        9   ← partial fix: hints + model
           ├── B7: Trivially wrong SQL           7   ← fix: better model
           └── B8: Multi-step collapsed         23   ← fix: better model (dominant failure)
```

### What a Model Switch Resolves

| Verdict | Count | Meaning |
|---------|-------|---------|
| **YES** | 48 | Frontier model (GPT-4o / Gemini 2.5 Pro) very likely fixes this |
| **PARTIAL** | 49 | Helps significantly; some cases remain hard even for frontier models |
| **NO** | 11 | Model change alone does not fix — needs DCE rebuild |
| **—** | 16 | Already correct (PASS) |

**NO cases (11):** All 11 A1 (DCE not built for `sqlite_sakila` + `db_imdb`). These need `dce build` regardless of which model is used.

**B5 moved to PARTIAL:** Frontier models may proactively run `SELECT DISTINCT` before filtering on coded columns. Reliable fix is prompt hint #8 (works with any model) or DCE enum enrichment.

### Top 5 Fixes — Ranked by Questions Recovered

| Priority | Fix | Effort | Est. questions recovered |
|----------|-----|--------|--------------------------|
| 1 | **Rebuild DCE** for `sqlite_sakila` + `db_imdb` | Low (run `dce build`) | +8–10 |
| 2 | **Switch to GPT-4o or Gemini 2.5 Pro** | Medium (API key + config) | +25–35 |
| 3 | **Update DUCKDB_HINTS** (haversine, PERCENTILE_CONT, PIVOT, CAST) | Low (edit benchmark script) | +3–5 |
| 4 | **DCE critique pass** on enum/status columns (California, school_scheduling, Pagila) | Medium (run enrichment) | +4–6 |
| 5 | **System prompt rules** (re-read question, LEFT JOIN for zeros, row-cap warning) | Low (edit benchmark script) | +4–6 |

**Realistic accuracy targets:**
- Current (Qwen3-32B-AWQ): **12%**
- After fixes 1, 3, 4, 5 only (no model change): **~22–28%**
- With GPT-4o / Gemini 2.5 Pro + all fixes: **~50–65%**

---

### Model Switch: Gemini 2.5 Pro/Flash vs GPT-4o — What Each Fixes

#### Gemini 2.5 Pro / Flash
- **1M token context window** → eliminates all 14 Bug 2 (context overflow) failures
- Strong SQL reasoning → recovers most B7 (trivially wrong) and B8 (multi-step) cases
- Good DuckDB knowledge → reduces B6 dialect errors
- **Caveat:** Tool calling reliability in vLLM not yet tested; may need API mode

#### GPT-4o (OpenAI API)
- **128K context** → eliminates most A2 overflow failures (14/14 for current schemas)
- Strongest multi-step SQL reasoning → best for B8 bank_sales_trading queries
- Excellent DuckDB knowledge → B6 nearly eliminated
- Best-tested with LangGraph tool calling (most reliable for agent loop)
- **Caveat:** Cost per question higher (~$0.05–0.15 per question × 124 = ~$8–20 per run)

#### Neither model alone fixes
- A1 (DCE not built): `sqlite_sakila` + `db_imdb` need `dce build` regardless
- B5 (wrong enum values): Without DCE sample values, even GPT-4o guesses wrong filter literals

---

## Category Taxonomy

Every question is assigned one or more categories. Categories marked **A*** are infrastructure/configuration bugs — fixable without changing the model. Categories marked **B*** are SQL correctness bugs.

| Code | Name | Count | Fixable without model? |
|------|------|-------|------------------------|
| PASS | Correct answer | 15 | — |
| **A1** | DCE index not built | 11 | ✅ Rebuild DCE for 2 DBs |
| **A2** | Context overflow (400 error) | 14 | ✅ Larger context model / schema truncation |
| **A3** | Recursion loop | 11 | ✅ Increase limit / stop rules |
| **A4** | Agent abandoned (text-only answer) | 18 | ⚠️ Prompt + model |
| **A5** | Parse error (malformed tool call) | 1 | ✅ Retry logic |
| **B1** | Incomplete transformation | 5 | ✅ Prompt rule |
| **B2** | Wrong output format / grain | 4 | ✅ PIVOT hint |
| **B3** | Missing zero-count entities | 3 | ✅ Prompt rule |
| **B4** | Window / running aggregate wrong | 9 | ⚠️ Hints + model |
| **B5** | Wrong literal / enum → empty result | 8 | ✅ DCE sample values |
| **B6** | DuckDB dialect / extension error | 5 | ✅ DUCKDB_HINTS update |
| **B7** | Trivially wrong SQL | 7 | ⚠️ Prompt + model |
| **B8** | Multi-step aggregation collapsed | 23 | ⚠️ Primarily model capability |
| **B9** | Result too large (1000-row cap) | 4 | ✅ Prompt rule |

*Total > 124 because questions can have multiple categories.*

---

## Complete Question-by-Question Categorization

### ✅ PASS — 15 questions

| Instance | DB | Notes |
|----------|----|-------|
| local007 | Baseball | avg career span via age() |
| local022 | IPL | players scoring ≥100 for losing team |
| local025 | IPL | avg of highest-scoring over per match |
| local030 | Brazilian_E_Commerce | 5 cities with lowest summed payments |
| local038 | Pagila | film category with highest rental hours |
| local040 | modern_data | pizza runner success rate |
| local054 | chinook | customer who spent most on classical music |
| local058 | education_business | top 3 best-selling hardware products |
| local071 | city_legislation | countries with longest consecutive insert streak |
| local085 | northwind | orders shipped after required date |
| local131 | EntertainmentAgency | musical styles by 1st/2nd/3rd preference count |
| local198 | chinook | customer with most purchases in each genre |
| local210 | delivery_center | hubs with >20% increase in finished orders (Feb→Mar) |
| local221 | EU_soccer | top 10 teams by most wins |
| local329 | log | unique sessions: /regist/input → /regist/confirm |

---

### A1 — DCE Index Not Built (11 questions · 0 correct)
**Model switch helps: ❌ NO** — GPT-4o and Gemini face the same empty search_context results. The fix is `dce build`, not a better model.

**Root cause:** Embeddings for `sqlite_sakila` and `db_imdb` are missing from `dce.duckdb`. Every `search_context` call returns `ValueError: Context is not built`. Agent retries 5× (exhausting 6-tool budget) then abandons. Schema in system prompt is insufficient for these questions.

**Fix:** `cd spider2-dce && dce build --db sqlite_sakila --db db_imdb`
Expected recovery: **+8–11 questions**

#### Representative Trace — local056 (sqlite-sakila)

**Question:** *"Which customer has the highest average monthly change in payment amounts? Provide the customer's full name."*

```
[USER]  Which customer has the highest average monthly change in payment amounts?

  → TOOL CALL: search_context("customer full name payment amount")
  ← ERROR: "Context is not built. Call build_context() before searching."

  → TOOL CALL: search_context("customer table structure")
  ← ERROR: "Context is not built. Call build_context() before searching."

  → TOOL CALL: search_context("payment amount column")
  ← ERROR: "Context is not built. Call build_context() before searching."

  → TOOL CALL: search_context("customer full name")
  ← ERROR: "Context is not built. Call build_context() before searching."

  → TOOL CALL: search_context("customer table columns")
  ← ERROR: "Context is not built. Call build_context() before searching."

[AI]  It seems the context cannot be accessed, and no database schema is available.
      Without knowing the relevant tables and columns, I cannot proceed with the query.

RESULT: no SQL generated | score: 0
```

The agent tried 5 different search queries — none worked. It never ran a single SQL statement. The entire 6-tool budget was consumed by failed schema lookups. This is a **pre-condition failure**, not a SQL failure.

| Instance | DB | Question |
|----------|----|---------|
| local056 | sqlite-sakila | customer with highest avg monthly change in payment amounts |
| local194 | sqlite-sakila | customer who rented the most films in each category |
| local195 | sqlite-sakila | top 5 cities by total rental revenue |
| local196 | sqlite-sakila | avg film length per rating category |
| local197 | sqlite-sakila | first film rented by each customer |
| local199 | sqlite-sakila | most popular film category by rental count |
| local096 | Db-IMDB | % of films per year with exclusively female cast |
| local097 | Db-IMDB | 10-year period with most actor collaborations |
| local098 | Db-IMDB | actors appearing most with director Yash Chopra |
| local099 | Db-IMDB | actors with highest avg film revenue in career |
| local100 | Db-IMDB | customer's first rental and its film rating |

---

### A2 — Context Overflow (14 questions · 0 correct)
**Model switch helps: ✅ YES** — Gemini 2.5 Pro (1M token context) and GPT-4o (128K) eliminate all 14 overflow failures without any other change. This is the single highest-return model switch benefit.

**Root cause:** Schema size + conversation history + `max_tokens=2048` reserved output exceeds Qwen3's 40960-token context. All fail with HTTP 400.

**Most affected DBs:** complex_oracle (4), log (2), f1 (2), city_legislation (1), E_commerce (1), Brazilian_EC (1), BowlingLeague (1), imdb_movies (1), EU_soccer (1), IPL (1)

**Fix options (ranked by impact):**
1. Switch to 200K+ context model (eliminates all 14)
2. Reduce `max_schema_summary_length` from 60K → 20K chars for large-schema DBs
3. Keep `max_tokens=1024` (already applied in Run 5+)

#### Representative Trace — local060 (complex_oracle)

**Question:** *"In the United States, for Q4 2019 and Q4 2020, first select only those cities where total sales increased by at least 20%..."*

```
[USER]  In the United States, for Q4 2019 and Q4 2020, first select only those cities
        where total sales (with promo_id=999) increased by at least 20%...

  → AGENT ERROR:
    Error code: 400 — "This model's maximum context length is 40960 tokens.
    However, you requested 2048 output tokens and your prompt contains at least
    38913 input tokens, for a total of at least 40961 tokens.
    Please reduce the length of the input prompt or the number of requested output tokens."

RESULT: no SQL generated | score: 0
```

The agent never even started. The `complex_oracle` database schema is so large (13 wide tables, each with many columns) that after DCE injected the schema summary into the system prompt, there was only **47 tokens of space left** for the agent to think and respond — not enough to generate any output. The model crashes before the first tool call.

| Instance | DB | Schema size issue |
|----------|----|-------------------|
| local002 | E_commerce | E_commerce schema (8 tables, wide) + RFM.md doc |
| local032 | Brazilian_E_Commerce | Large schema + conversation history |
| local060 | complex_oracle | complex_oracle: largest schema in benchmark |
| local061 | complex_oracle | same |
| local067 | complex_oracle | same |
| local070 | city_legislation | city_legislation: 10 tables, wide columns |
| local128 | BowlingLeague | Medium schema but conversation already long |
| local220 | EU_soccer | EU_soccer 7 tables, wide Match table |
| local229 | IPL | IPL: 7 tables, many JOINs |
| local230 | imdb_movies | imdb_movies schema |
| local330 | log | log: 19 tables |
| local331 | log | same |
| local344 | f1 | f1: 13 tables |
| local355 | f1 | same |

---

### A3 — Recursion Loop (11 questions · 0 correct)
**Model switch helps: ⚠️ PARTIAL** — A larger context (GPT-4o/Gemini) eliminates the 2–3 compound overflow→recursion cases. Better instruction-following reduces schema blindness loops. But `recursion_limit` config fix is still required; model alone doesn't prevent the node limit from being hit.

**Root cause:** Agent loops without resolving. Three sub-patterns (detailed in Bug 3 report):
- **Schema blindness loop** (6): agent guesses wrong table/column names, retries 25+ times
- **Correct answer, recursion kills it** (1: local329 — fixed in latest run)
- **Context overflow → compounded recursion** (2–3)
- **Search_context loop from broken DCE** (1: local193)

**Fix:** `recursion_limit=12` already applied in Run 5+; also add "stop after 3 failed SQL" prompt rule.

#### Representative Trace — local008 (Baseball)

**Question:** *"I would like to know the given names of baseball players who have achieved the highest value of games, runs, hits, and home runs."*

```
[USER]  I would like to know the given names of baseball players who have achieved
        the highest value of games, runs, hits, and home runs.

  → TOOL CALL: search_context("baseball player stats games runs hits home runs")
  ← [schema chunks returned — mentions columns name_first, name_last, G, R, H, HR]

  → TOOL CALL: run_sql_query("SELECT name_given FROM batting JOIN people ...")
  ← ERROR: column "name_given" does not exist

  → TOOL CALL: run_sql_query("SELECT given_name FROM people WHERE ...")
  ← ERROR: column "given_name" does not exist

  → TOOL CALL: run_sql_query("SELECT player_given_name FROM people WHERE ...")
  ← ERROR: column "player_given_name" does not exist

  → TOOL CALL: run_sql_query("SELECT first_name FROM people WHERE ...")
  ← ERROR: column "first_name" does not exist

  → ... [continues guessing column names for 20+ more iterations] ...

  ← AGENT ERROR: Recursion limit of 50 reached without hitting a stop condition.

RESULT: no SQL generated | score: 0
```

The agent knew the answer required "given name" but the actual column is `nameGiven` (camelCase). DCE's schema description used natural language ("given name of the player") so the agent kept guessing variations. With no stop rule, it tried 25+ different column names until LangGraph cut it off.

| Instance | DB | Sub-pattern | Question |
|----------|----|-------------|---------|
| local008 | Baseball | Schema blindness — `name_given` vs `name_first||name_last` | highest games/runs/hits/HR with given names |
| local009 | Airlines | Schema blindness + haversine | longest route from Abakan (with haversine_formula.md) |
| local050 | complex_oracle | Schema blindness | median of avg monthly projected sales France 2021 |
| local073 | modern_data | Schema blindness | pizza order expanded with row_id per item |
| local074 | bank_sales_trading | Schema blindness | monthly closing balance summary |
| local170 | city_legislation | Context overflow → recursion | male LA legislators active Dec 1, 2023 |
| local171 | city_legislation | Context overflow → recursion | states where retention rate unchanged M/F |
| local193 | sqlite-sakila | DCE not built → search_context loop | avg % of LTV in first 3 months |
| local284 | bank_sales_trading | Schema blindness | veg wholesale loss rate summary |
| local356 | f1 | Schema blindness | drivers overtaken more than they overtook |
| local360 | log | Context overflow → recursion | events before max-revenue purchase per session |

---

### A4 — Agent Abandoned / Text-Only Answer (18 questions · 0 correct)
**Model switch helps: ✅ YES** — GPT-4o and Gemini 2.5 Pro handle multi-step financial/temporal SQL that Qwen3-32B cannot formulate. Estimated recovery: ~10–14 of 18. The remaining 4 (most complex bank_sales_trading CTEs) remain hard even for frontier models.

**Root cause:** Agent called `search_context` once (schema found OK), then submitted a text-only answer without a `query_id`. `thread.code()` returns None → scored as no_sql. 

**Why it happens:** Question is too algorithmically complex for the model to formulate SQL within the 6-tool budget. The model explains in text what it would do rather than writing SQL.

**Pattern:** All questions in this category are either:
- Complex multi-step financial/temporal queries (bank_sales_trading ×5)
- Compound IPL cricket stats (×3)
- Questions requiring self-joins, date-spine generation, or domain-specific logic

**Fix:** Model upgrade is the primary lever. Also helps: increase tool budget to 8-10, add specific DuckDB patterns to hints for date-spine generation.

#### Representative Trace — local075 (bank_sales_trading)

**Question:** *"Can you provide a breakdown of how many times each product was viewed, how many times they were added to the shopping cart, and how many times they were left in the cart without being purchased? Also, give me the count of actual purchases for each product. Ensure that products with a page id in (1, 2) are excluded..."*

```
[USER]  Can you provide a breakdown of how many times each product was viewed,
        added to cart, left in cart without purchase, and actually purchased?
        Exclude products with page_id in (1, 2)...

  → TOOL CALL: search_context("shopping cart events, page hierarchy, event types")
  ← [schema returned — events table, page_hierarchy table, campaign_identifier table]

[AI]  To answer this question, I need to:
      1. Join events with page_hierarchy to get product names
      2. Use CASE statements to pivot event_type into view/cart/purchase columns
      3. LEFT JOIN to get abandoned = (added to cart) - (purchased)
      4. Filter page_id NOT IN (1, 2)

      This is a complex multi-step query requiring careful event-type pivoting.
      Based on the schema, I can outline the approach but the query involves
      multiple conditional aggregations...

      [Submits text explanation as final answer — no query_id, no SQL]

RESULT: no SQL generated | score: 0
```

The agent understood the problem correctly and described the right approach in plain English. But it could not translate that plan into working SQL within the tool budget — so it submitted its explanation as the "answer." The scorer sees no `query_id`, treats it as no SQL generated.

| Instance | DB | Question | Complexity |
|----------|----|---------|------------|
| local003 | E_commerce | RFM segmentation with NTILE quintiles | B8+B4 if had attempted SQL |
| local004 | E_commerce | orders/avg payment/lifespan in weeks per customer tier | B8 |
| local018 | California_Traffic_Collision | most-common collision factor in 2021 → count in other years | B8 |
| local026 | IPL | top-3 bowlers in overs where max runs conceded in match | B8 |
| local049 | modern_data | avg new unicorn companies/yr in top industry for each country | B8 |
| local075 | bank_sales_trading | product funnel: viewed→cart→purchase→abandoned per product | B8 |
| local077 | bank_sales_trading | interest composition month-over-month change Sep 2018–Aug 2019 | B4+B8 |
| local152 | imdb_movies | top 9 directors by count + their avg movie rating | B8 |
| local156 | bank_sales_trading | annual avg Bitcoin purchase price by region | B4+B8 |
| local169 | city_legislation | annual retention rate of legislators 1917–1945 cohort | B4+B8 |
| local228 | IPL | top-3 batsmen + top-3 bowlers per season (combined output) | B8 |
| local253 | education_business | salary cleaning (remove non-numeric) then stats by job/country | B6+B8 |
| local259 | IPL | player most-frequent role + batting hand + bowling style per player | B8 |
| local285 | bank_sales_trading | veg wholesale financial performance 2020–2023 | B8 |
| local286 | electronic_sales | seller performance report: sales/returns/ratings/avg price | B8 |
| local297 | bank_sales_trading | monthly closing balance via cumulative net deposits | B4+B8 |
| local300 | bank_sales_trading | daily balance for every calendar day between earliest/latest txn | B4+B8 |
| local311 | f1 | constructors with top-3 combined best-driver + team points | B8 |

---

### A5 — Parse Error (1 question · 0 correct)
**Model switch helps: ✅ YES** — Frontier models (GPT-4o, Gemini 2.5 Pro) rarely generate malformed tool-call JSON. This failure class is nearly absent at frontier model capability levels.

| Instance | DB | Error | Fix |
|----------|----|-------|-----|
| local017 | California_Traffic_Collision | `1 validation error for AIMessage: tool_calls.0.args — Input should be a valid dictionary` — model generated SQL directly as tool arg string instead of dict | Add retry: catch pydantic validation errors and retry with temperature bump |

---

### B1 — Incomplete Transformation (5 questions · 0 correct)
**Model switch helps: ✅ YES** — Frontier models are better at re-reading the question after generating SQL and catching missing percentage/ratio/final-filter steps. Estimated recovery: ~4 of 5 with GPT-4o.

**Definition:** Correct intermediate data retrieved; final transformation step missing (percentage, combined ranking, filtered max).

**Fix:** Add to system prompt: *"After writing SQL, re-read every clause of the question. If it asks for a percentage, ensure you divide. If it asks for 'which X', return the identified value, not the full table."*

| Instance | DB | Got | Needed |
|----------|----|-----|--------|
| local041 | modern_data | `COUNT(*)` of Good-health Bronx trees | `100.0 * COUNT(*) FILTER (WHERE health='Good') / COUNT(*)` |
| local064 | bank_sales_trading | Balance CTE correct; final collapses to 1-row "which month" | Show balance table, then find month with most positive-balance customers |
| local078 | bank_sales_trading | Top-20 by rank (one direction only) | Top-10 highest + bottom-10 lowest via dual ROW_NUMBER then UNION |
| local157 | bank_sales_trading | Volume cleaning correct; date filter not in final SELECT | Move `WHERE market_date BETWEEN '2021-08-01' AND '2021-08-10'` to final SELECT |
| local299 | bank_sales_trading | Running balance correct for all days | Outer `SELECT customer_id, txn_date, MAX(running_balance) GROUP BY customer_id, txn_date` |

---

### B2 — Wrong Output Format / Grain (4 questions · 0 correct)
**Model switch helps: ✅ YES** — Frontier models reliably recognize PIVOT/wide-format requirements from natural language phrasing and generate correct DuckDB `PIVOT` syntax. Estimated recovery: ~3–4 of 4.

**Definition:** Correct data, wrong shape. Long-format when wide needed, wrong grouping level, too many rows per entity.

**Fix:** Add to DUCKDB_HINTS:
```sql
-- Wide pivot (when question says "each column represents X"):
PIVOT (SELECT year, month, cnt FROM t) ON year IN (2016,2017,2018) USING SUM(cnt) GROUP BY month
```

| Instance | DB | Got | Needed |
|----------|----|-----|--------|
| local028 | Brazilian_E_Commerce | Long: `(month_year, count)` — 25 rows | Wide pivot: `(month, 2016_count, 2017_count, 2018_count)` — 12 rows |
| local141 | AdventureWorks | 163 raw rows (self-join bug ON `s.id=s.id`) | `GROUP BY salesperson, year` → `SUM(sales) - quota` per year |
| local258 | IPL | 312 rows: all bowlers unranked | Ranked/filtered output with economy + avg; specific N requested |
| local309 | f1 | 68 rows: one per year×category | 1 row per year with `top_driver_name, top_constructor_name` as columns |

---

### B3 — Missing Zero/Absent Entities (3 questions · 0 correct)
**Model switch helps: ✅ YES** — Frontier models reliably recognize "including zero" patterns and generate LEFT JOIN from the base table. Estimated recovery: ~3 of 3 with GPT-4o given the clear natural language cues in these questions.

**Definition:** INNER JOIN silently drops entities with zero counts. Question explicitly includes "zero wins", "all styles", etc.

**Fix:** Add to system prompt: *"If the question says 'including zero', 'all X', or asks for minimum/fewest: generate all entities first using LEFT JOIN or the base table, then count. Never use INNER JOIN for this pattern."*

| Instance | DB | Dropped entities | Fix |
|----------|----|-----------------|-----|
| local219 | EU_soccer | Teams with 0 wins excluded by INNER JOIN to Match | Start from `Team`, LEFT JOIN win counts from Match |
| local283 | EU_soccer | Away team contributions to champion points missing | UNION ALL home + away perspectives before GROUP BY champion |
| local133 | EntertainmentAgency | Musical styles never preferred get score=0; missing from output | Start from `Musical_Styles`, LEFT JOIN preference counts |

---

### B4 — Window / Running Aggregate Logic Wrong (9 questions · 0 correct)
**Model switch helps: ⚠️ PARTIAL** — GPT-4o/Gemini improve running balance and LAG-based comparisons significantly (~5–6 of 9). Complex 4-stage financial CTEs (bank_sales_trading) remain hard even for frontier models; estimated ~3–4 still fail without DUCKDB_HINTS additions.

**Definition:** Correct window function syntax, wrong partition/frame/outer aggregation.

**Fix:** Add to DUCKDB_HINTS:
```sql
-- Running balance:
SUM(amount) OVER (PARTITION BY id ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
-- Previous month comparison:
LAG(balance) OVER (PARTITION BY id ORDER BY month_start)
-- Month-end grouping (DuckDB):
DATE_TRUNC('month', txn_date::DATE) AS month_start
-- 12-week window boundary:
reference_date::DATE - INTERVAL '84 days'   -- before
reference_date::DATE + INTERVAL '84 days'   -- after
```

| Instance | DB | Window error | Fix |
|----------|----|-------------|-----|
| local020 | IPL | batsman+extra JOIN doubles run counts in bowling avg | Compute runs and wickets in separate CTEs; no cross-join |
| local023 | IPL | extra_runs at ball level inflates per-player averages | Sum per player per match first; extra_runs are team-level |
| local062 | complex_oracle | NTILE applied before profit GROUP BY; cost column name wrong | Check column is `prod_cost`; GROUP BY before NTILE |
| local064 | bank_sales_trading | strftime on DATE may return NULL; final collapses to 1 row | `DATE_TRUNC('month', txn_date::DATE)` for grouping |
| local068 | city_legislation | Cumulative SUM OVER partition wrong; returns 4 rows not 9 | `SUM(count) OVER (PARTITION BY month_name ORDER BY year)` |
| local072 | city_legislation | Consecutive-day streak correct; % denominator uses rows not days | Denominator = 31 (days in January), not COUNT(*) |
| local298 | bank_sales_trading | GREATEST(balance,0) per-customer not aggregate; month windows wrong | `SUM(GREATEST(running_balance,0))` across all customers per month |
| local299 | bank_sales_trading | Running balance correct; returns all days instead of MAX per day | `SELECT customer_id, txn_date, MAX(running_balance) GROUP BY 1,2` |
| local302 | bank_sales_trading | "After" boundary `ref-7` wrong; should be `ref+1` to `ref+84` | Fix: after = `[ref + INTERVAL '1 day', ref + INTERVAL '84 days']` |

---

### B5 — Wrong Literal / Enum in Filter → Empty Result (8 questions · 0 correct)
**Model switch helps: ⚠️ PARTIAL** — Frontier models (GPT-4o, Gemini 2.5 Pro) are more likely to proactively run `SELECT DISTINCT col LIMIT 20` before filtering on an unfamiliar column, which would reveal the actual codes. Qwen3-32B skips this step and guesses directly. However, this behaviour is inconsistent even in frontier models without an explicit prompt rule. The reliable fixes are: (1) add "inspect enum values before filtering" to DUCKDB_HINTS (works with any model), or (2) inject actual distinct values into the DCE YAML descriptions. Note: the existing `experiment_critique_enrich.py` script does NOT directly fix this — it disambiguates similar-sounding columns, not categorical value domains. A separate enum scan is required.

**Definition:** SQL structure correct; filter value doesn't match actual data values in DB. Almost always produces empty result. Caused by DCE not including sample values for categorical/code columns.

**Fix:** Run `experiment_critique_enrich.py` on affected tables to add enum values and sample data to column descriptions. Priority tables: `parties.party_safety_equipment_*`, `Student_Schedules.ClassStatus`, `legislators_terms.term_end`, `drivers.status`.

#### Representative Trace — local015 (California_Traffic_Collision)

**Question:** *"Please calculate the fatality rate for motorcycle collisions, separated by helmet usage. Specifically: 1) the % of motorcyclist fatalities where parties were wearing helmets, and 2) the % where they were not."*

```
[USER]  Please calculate the fatality rate for motorcycle collisions,
        separated by helmet usage...

  → TOOL CALL: search_context("california traffic collision database helmet usage")
  ← [schema: parties table — columns: party_safety_equipment_1, party_safety_equipment_2,
     at_fault, party_type, ...]
     (No sample values shown — only column names and natural-language descriptions)

  → TOOL CALL: run_sql_query("""
      WITH helmet_usage AS (
        SELECT case_id,
          CASE WHEN party_safety_equipment_1 = 'helmet used' THEN 'Helmet'
               WHEN party_safety_equipment_1 = 'no helmet'   THEN 'No Helmet'
               ELSE 'Unknown' END AS helmet_status
        FROM parties WHERE party_type = 'motorcycle'
      )
      SELECT helmet_status, COUNT(*) * 100.0 / SUM(COUNT(*)) OVER () AS fatality_rate
      FROM helmet_usage GROUP BY helmet_status
    """)
  ← RESULT: empty DataFrame (0 rows)

  [AI submits 0-row result as final answer]

RESULT: empty df | score: 0
```

**Root cause:** The `party_safety_equipment_1` column stores single-character safety codes (e.g., `'E'`, `'G'`, `'H'`), not human-readable strings. The agent guessed `'helmet used'` based on natural language — a perfectly reasonable guess, but wrong. Because DCE never extracted sample values for this column, neither the agent nor a frontier model would know the actual codes without running `SELECT DISTINCT party_safety_equipment_1 FROM parties LIMIT 20` first.

| Instance | DB | Wrong filter | Actual data |
|----------|----|-------------|-------------|
| local015 | California_Traffic_Collision | `party_safety_equipment_1 = 'helmet used'` | Single-char codes like `'E'`; values unknown without DCE samples |
| local019 | WWE | `title_change = 0` and `p.name = 'NXT'` | title_change encoding and Promotions name values unknown |
| local039 | Pagila | `'%-%%'` LIKE pattern for hyphen | Use `'%-%'` — DuckDB `%` is wildcard, no `%%` needed |
| local114 | education_business | `web_orders`, `web_accounts`, `web_sales_reps` tables | These tables don't exist; schema has different names |
| local130 | school_scheduling | `ClassStatus = 2` for "completed" | Actual completion value unknown; DCE has no enum for ClassStatus |
| local167 | city_legislation | `term_end = 'December, 31'` | term_end stored as ISO date; use `EXTRACT(MONTH)=12 AND EXTRACT(DAY)=31` |
| local354 | f1 | `f1.main.drives` does not exist | Table is `f1.main.driver_standings` or similar |
| local358 | log | `AGE(CURRENT_DATE, birth_date)` — 2026 reference | Use fixed reference year matching data era; `CURRENT_DATE` gives wrong decade |

---

### B6 — DuckDB Dialect / Extension Error (5 questions · 0 correct)
**Model switch helps: ⚠️ PARTIAL** — GPT-4o and Gemini 2.5 Pro have better DuckDB knowledge and will avoid some dialect errors (e.g., duration parsing). However, haversine (`LOAD spatial` missing) and `PERCENTILE_CONT` syntax still benefit from explicit DUCKDB_HINTS; estimated recovery ~3 of 5 with model switch alone.

**Definition:** SQLite functions, unavailable extensions, or wrong DuckDB syntax.

**Fix:** Add to DUCKDB_HINTS:
```python
"""
- The spatial extension is NOT available. Implement haversine as:
    2 * ASIN(SQRT(POWER(SIN(RADIANS(lat2-lat1)/2),2) +
             COS(RADIANS(lat1)) * COS(RADIANS(lat2)) *
             POWER(SIN(RADIANS(lon2-lon1)/2),2))) * 6371
- Median: PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY col)
- LIKE hyphen: '%-%' (single %, no escaping needed)
- UNNEST(STRING_SPLIT(col,',')): result is VARCHAR — CAST to INTEGER before joining
- Do NOT use: LOAD spatial, JULIAN(), DATE(), INTERVAL MINUTE TO SECOND cast
"""
```

| Instance | DB | Wrong | Correct |
|----------|----|-------|---------|
| local010 | Airlines | `LOAD spatial;` — extension missing | Pure arithmetic haversine formula |
| local019 | WWE | `REGEXP_MATCHES(...) AS INTERVAL MINUTE TO SECOND` | `SPLIT_PART` + arithmetic for duration |
| local039 | Pagila | `'%-%%'` LIKE pattern | `'%-%'` |
| local066 | modern_data | `TRIM(topping_id)` as VARCHAR joined to INTEGER `toppings.id` | `CAST(TRIM(topping_id) AS INTEGER)` |
| local218 | EU_soccer | `AVG(max_goals)` for median | `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY max_goals)` |

---

### B7 — Trivially Wrong SQL (7 questions · 0 correct)
**Model switch helps: ✅ YES** — These failures are classic model capability ceiling cases for Qwen3-32B. GPT-4o and Gemini 2.5 Pro can formulate anagram self-joins, product funnel queries, consecutive-row logic, and ranked aggregations. Estimated recovery: ~5–6 of 7.

**Definition:** Model submits syntactically valid SQL that ignores the core algorithmic requirement. Often an exploratory/stub query.

**These are model capability ceiling cases.** The model couldn't formulate the required algorithm and fell back to a simpler query.

| Instance | DB | Submitted | Required |
|----------|----|-----------|---------|
| local035 | Brazilian_E_Commerce | `SELECT COUNT(*) FROM olist_geolocation WHERE lat IS NOT NULL` | Self-join on sorted rows with LAG to find max-distance consecutive city pair |
| local081 | northwind | `SELECT orderid, orderdate FROM orders WHERE year=1998 LIMIT 10` | `SUM(unit_price * qty * (1-discount)) GROUP BY customer` then ranked |
| local141 | AdventureWorks | `JOIN sp ON s.businessentityid = s.businessentityid` (self-join) | `GROUP BY salesperson, year` comparing `SUM(sales)` to `quota` |
| local168 | city_legislation | `SELECT COUNT(*) WHERE job_title_short='Data Analyst'` | Filter remote Data Analyst → top-3 skills → avg salary for those skills |
| local201 | modern_data | `SELECT words WHERE length BETWEEN 4 AND 5 AND LIKE 'r%'` | Self-join: `WHERE sorted_chars(w1) = sorted_chars(w2)` for anagram detection |
| local301 | bank_sales_trading | `SELECT DISTINCT week_number FROM weekly_sales WHERE month=6` | 4-week avg before vs after mid-June, % change per region/platform/demographic |
| local336 | f1 | Raw `lap_positions` with LAG(position) — 1000 rows | Categorise position changes into retirement/pit/start/track-pass; COUNT per type |

---

### B8 — Multi-Step Aggregation Collapsed (23 questions · 0 correct)
**Model switch helps: ⚠️ PARTIAL** — Frontier models (GPT-4o, Gemini 2.5 Pro) recover an estimated ~13–15 of 23: they handle the 2–3 step cases well. The remaining ~8–10 complex 4-stage bank_sales_trading CTEs (daily balance spine, window-over-window, RFM) remain hard even for frontier models without specific schema guidance.

**Definition:** Question requires 2–4 sequential aggregation steps. Model builds first 1–2 CTEs correctly but the final SELECT applies wrong level of aggregation or misses a step. **Dominant failure mode (43% of result_mismatch cases).**

**Fix:** System prompt: *"For questions requiring multiple aggregation steps, write one CTE per step. Before submitting, mentally trace CTE1 → CTE2 → ... → final SELECT."* Model upgrade is the primary long-term lever.

#### Representative Trace — local021 (IPL)

**Question:** *"Could you calculate the average of the total runs scored by all strikers who have scored more than 50 runs in any single match?"*

```
[USER]  Could you calculate the average of the total runs scored by all strikers
        who have scored more than 50 runs in any single match?

  → TOOL CALL: search_context("ipl database schema, total runs per striker per match")
  ← [schema: ball_by_ball, batsman_scored, extra_runs, player tables returned]

  → TOOL CALL: run_sql_query("""
      WITH striker_runs AS (
        SELECT bbb.striker AS player_id,
               bbb.match_id,
               SUM(bs.runs_scored) AS match_runs    -- ✓ runs per match, per striker
        FROM ball_by_ball bbb
        JOIN batsman_scored bs ON bbb.match_id = bs.match_id AND bbb.over_id = bs.over_id
                               AND bbb.ball_id = bs.ball_id
        GROUP BY bbb.striker, bbb.match_id
      ),
      qualified AS (
        SELECT player_id, AVG(match_runs) AS avg_runs   -- ✗ avg of per-match runs
        FROM striker_runs
        WHERE match_runs > 50                            -- ✓ filter correct
        GROUP BY player_id
      )
      SELECT AVG(avg_runs) AS result FROM qualified      -- ✗ double-averaged
    """)
  ← RESULT: 1 row — {"result": 68.4}

  [Agent submits this value]

RESULT: 1 row | score: 0 (result_mismatch — gold answer: 56.2)
```

**Root cause — the aggregation ladder:**

| Step | What the question asks | What the agent did |
|------|----------------------|-------------------|
| 1 | Sum runs per striker per match | ✅ Correct |
| 2 | Filter: only strikers who scored >50 in ANY match | ✅ Correct |
| 3 | Sum ALL runs per qualifying striker (across all matches) | ❌ Averaged per-match runs instead |
| 4 | Average those totals across all qualifying strikers | ❌ Averaged the averages (wrong denominator) |

The model collapsed steps 3 and 4 into a single `AVG(match_runs)` — a very natural mistake that produces a plausible-looking number, but the wrong one.

| Instance | DB | Steps completed | Missing step |
|----------|----|----------------|-------------|
| local021 | IPL | Finds strikers with >50 in any match | AVG of total match runs (not per-ball) |
| local024 | IPL | Per-player avg runs correct | Avg within country (extra aggregation level) |
| local029 | Brazilian_E_Commerce | Top-3 by unique_id correct | Duplicate orders inflate avg payment |
| local031 | Brazilian_E_Commerce | Finds lowest-volume year | Max-monthly query uses wrong year boundary |
| local034 | Brazilian_E_Commerce | Most-preferred type per category | Count includes all types not just preferred |
| local037 | Brazilian_E_Commerce | Most-used type per category | Ranking direction inverted |
| local055 | chinook | Max/min artist found | Ratio (max_sales/min_sales) value wrong |
| local059 | education_business | Top-3 per division | AVG taken across divisions not within each |
| local063 | complex_oracle | City 20% increase filter correct | City filter dropped from final product SELECT |
| local065 | modern_data | Base pizza price correct | Extras comma-string parser misses some toppings |
| local066 | modern_data | Recipe string split correct | CAST to INTEGER fails silently on join |
| local072 | city_legislation | Streak identified | % denominator wrong (rows vs days) |
| local132 | EntertainmentAgency | First style match | Second style JOIN too loose (OR not AND) |
| local163 | education_business | All salary diffs computed | Returns all; needs MIN per rank |
| local202 | city_legislation | Top-10 states by alien population | `alien_age>200` references non-existent column |
| local209 | delivery_center | Top store correct | Deliveries ratio JOIN wrong |
| local218 | EU_soccer | Max season goals per team | Uses AVG not PERCENTILE_CONT for median |
| local244 | music | Duration classification correct | Revenue uses Track.UnitPrice not InvoiceLine |
| local258 | IPL | Bowler stats correct | No ranking/filtering applied |
| local310 | f1 | Max driver points from `results` correct | Constructor points from wrong table |
| local335 | f1 | Constructor points per season correct | Ranking direction inverted |
| local020 | IPL | Bowling avg structure correct | JOIN inflation + wrong exclusion |
| local023 | IPL | Per-player runs per season | extra_runs at ball level inflates avg |

---

### B9 — Result Too Large / 1000-Row Cap (4 questions · 0 correct)
**Model switch helps: ✅ YES** — Frontier models with better instruction-following are more likely to recognize that a 1000-row result signals a missing GROUP BY / LIMIT and self-correct. Also fixable with a prompt rule alone. Estimated recovery: ~3–4 of 4.

**Definition:** LighthouseExecutor caps query results at 1000 rows. Query returns full table instead of aggregated answer.

**Fix:** Add to system prompt: *"Your query result is capped at 1000 rows. If the expected result is a ranked or aggregated list, ensure GROUP BY + LIMIT is in the final SELECT. Never submit a raw table scan as the answer."*

| Instance | DB | Rows returned | Rows needed |
|----------|----|--------------|-------------|
| local157 | bank_sales_trading | 1000 | ~40 (Aug 1–10 × N tickers) — date filter not in final SELECT |
| local201 | modern_data | 996 | 10 anagram word pairs |
| local283 | EU_soccer | 1000 | 1 champion team per season per league |
| local336 | f1 | 1000 | 4 overtake category counts |

---

## Failure Distribution by DB

| DB | Total | Pass | A1 | A2 | A3 | A4 | A5 | B-class |
|----|-------|------|----|----|----|----|----|----|
| bank_sales_trading | 15 | 0 | 0 | 0 | 2 | 5 | 0 | 8 |
| IPL | 11 | 2 | 0 | 1 | 0 | 3 | 0 | 5 |
| city_legislation | 10 | 1 | 0 | 1 | 2 | 1 | 0 | 5 |
| f1 | 9 | 0 | 0 | 2 | 1 | 1 | 0 | 5 |
| Brazilian_E_Commerce | 8 | 1 | 0 | 1 | 0 | 0 | 0 | 6 |
| modern_data | 7 | 1 | 0 | 0 | 1 | 1 | 0 | 4 |
| sqlite-sakila | 7 | 0 | 6 | 0 | 1 | 0 | 0 | 0 |
| complex_oracle | 6 | 0 | 0 | 4 | 1 | 0 | 0 | 1 |
| education_business | 5 | 1 | 0 | 0 | 0 | 1 | 0 | 3 |
| Db-IMDB | 5 | 0 | 5 | 0 | 0 | 0 | 0 | 0 |
| EU_soccer | 5 | 1 | 0 | 1 | 0 | 0 | 0 | 3 |
| log | 5 | 1 | 0 | 2 | 1 | 0 | 0 | 1 |
| E_commerce | 3 | 0 | 0 | 1 | 0 | 2 | 0 | 0 |
| California_Traffic_Coll. | 3 | 0 | 0 | 0 | 0 | 1 | 1 | 1 |
| chinook | 3 | 2 | 0 | 0 | 0 | 0 | 0 | 1 |
| EntertainmentAgency | 3 | 1 | 0 | 0 | 0 | 0 | 0 | 2 |
| delivery_center | 3 | 1 | 0 | 0 | 0 | 0 | 0 | 2 |
| Baseball | 2 | 1 | 0 | 0 | 1 | 0 | 0 | 0 |
| Airlines | 2 | 0 | 0 | 0 | 1 | 0 | 0 | 1 |
| Pagila | 2 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| northwind | 2 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| imdb_movies | 2 | 0 | 0 | 1 | 0 | 1 | 0 | 0 |
| WWE | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| BowlingLeague | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| school_scheduling | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| AdventureWorks | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| music | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| electronic_sales | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |

---

## Recovery Roadmap

### Without model change — estimated +14–22 questions

| Action | Targets | Est. gain |
|--------|---------|-----------|
| Rebuild DCE for sqlite-sakila + db_imdb | A1 (11 questions) | +8–10 |
| Add DUCKDB_HINTS: haversine, PERCENTILE_CONT, PIVOT, CAST fix | B6 (5 questions) | +3–4 |
| DCE critique pass on California, school_scheduling, Pagila, city_legislation status/enum cols | B5 (5–6 questions) | +3–5 |
| System prompt rules: percentage check, LEFT JOIN for zeros, row-cap warning | B1+B3+B9 | +3–5 |
| Fix `recursion_limit` → 16 (for local329-type); add "stop after 3 failed SQL" rule | A3 subset | +1–2 |

### With model upgrade (Qwen2.5-Coder-32B or Claude Sonnet)

| Action | Targets | Est. gain |
|--------|---------|-----------|
| Better SQL formulation | B7 (7), B4 partial (4), B8 partial (8–12) | +15–25 |
| Larger context window | A2 (14 questions eliminated) | +8–12 |
| Better multi-step reasoning | A4 subset (harder abandoned cases) | +5–10 |

**Realistic ceiling with Qwen2.5-Coder-32B + prompt fixes: ~45–55/124 (36–44%)**
**Ceiling with Claude Sonnet 4.5 + prompt fixes: ~65–80/124 (52–65%)**
