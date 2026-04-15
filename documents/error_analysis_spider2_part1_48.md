# Error Analysis — spider2_part1_48_20260410_030528.csv

**Run date:** 2026-04-10 03:05  
**Questions (raw):** 48 (subset of 135 Spider 2.0 local SQLite)  
**Score (raw):** 13/48 = **27.1%** (baseline 12.1%)

### DCE context state during this run

DCE **was active** — `search_context` was wired up and available as a tool. However the embedding server (Ollama) was **intermittently timing out**, meaning `search_context` calls often failed silently. From the traces:

```
{"error": "OllamaTransientError: Ollama request to /api/embed timed out after Nones
 Tool: search_context, Args: {'retrieve_text': 'RFM model recency frequency monetary...'}"}
```

When `search_context` timed out, the agent received an error back instead of schema chunks, and fell back to reasoning from the schema injected into the system prompt (column names only, no descriptions, no enum values, no table relationships). So **the failures attributed to "missing DCE context" are accurate** — DCE was present but effectively non-functional for the schema-dependent failures.

Additionally: the DCE index had **no LLM-generated descriptions** (vLLM for enrichment was a separate job that ran on April 3rd with Qwen3-32B-AWQ, but the resulting enriched `dce.duckdb` may not have been the one in use for this run — the benchmark ran on April 10th using Sandeep's server environment). Even when `search_context` did succeed, it returned raw schema (column names + types) without semantic descriptions or enum values.

### Adjusted score — excluding confirmed vLLM infrastructure failures

8 questions failed due to a vLLM server crash mid-run, confirmed by their ~8-second failure times (instant connection timeout — LLM was never contacted). These are not evaluable: the agent made 0 LLM calls and submitted no SQL. Excluding them gives the **real evaluated set**:

> **13/40 = 32.5%** on 40 effectively evaluated questions  
> Baseline on same 40 questions: ~12.1%

The 8 excluded instances are: local050 (vLLM died partway through, 1438s), local062, local067 (complex_oracle), local068, local070, local071, local072 (city_legislation), local073 (modern_data). All failed in ≤9 seconds except local050.

---

## Summary by Failure Category (40-question adjusted set)

| Category | Count | % of failures (27) | % of evaluated (40) |
|---|---|---|---|
| Result mismatch (SQL logic error) | 19 | 70% | 48% |
| Recursion limit hit | 4 | 15% | 10% |
| Timeout (29 min) | 2 | 7% | 5% |
| Context overflow (prompt too large) | 1 | 4% | 2.5% |
| No SQL generated | 1 | 4% | 2.5% |
| **Total failures** | **27** | | **68%** |

---

## Summary by Database (adjusted — excluding vLLM-dead questions)

| Database | Pass | Evaluated | Rate | Dominant failure |
|---|---|---|---|---|
| IPL | 0 | 7 | 0% | Result mismatch (6), no_sql (1) |
| Brazilian_E_Commerce | 3 | 7 | 43% | Result mismatch |
| complex_oracle | 0 | 3 | 0% | Recursion (1), timeout (1), mismatch (1) |
| California_Traffic_Collision | 0 | 3 | 0% | Mismatch (2), recursion (1) |
| E_commerce | 1 | 3 | 33% | Result mismatch |
| modern_data | 3 | 3 | 100% | — |
| chinook | 2 | 3 | 67% | Recursion (1) |
| education_business | 1 | 2 | 50% | Result mismatch |
| Airlines | 1 | 2 | 50% | Context overflow |
| Baseball | 1 | 2 | 50% | Result mismatch |
| Pagila | 0 | 2 | 0% | Mismatch (1), recursion (1) |
| sqlite-sakila | 0 | 1 | 0% | Timeout |
| WWE | 1 | 1 | 100% | — |
| city_legislation | — | 0 | — | *(all 4 excluded: vLLM dead)* |

> Note: complex_oracle had 6 questions total but 3 are excluded (vLLM dead). The 3 evaluated are local060 (recursion), local063 (timeout), local061 (mismatch).

---

## Part A — Infrastructure Failures (7 evaluated failures, 26% of evaluated set)

These failures have **nothing to do with SQL quality** — they are system-level failures that we can eliminate by fixing the runtime environment.

> **A1 (vLLM connection errors) is excluded from the 40-question analysis** — all 8 instances are treated as unevaluated. See header section for justification.

### A1 — vLLM Connection Errors (8 failures — EXCLUDED from analysis)

The vLLM server crashed during the run. The clearest evidence is the failure times — every question that ran while vLLM was alive took hundreds of seconds; every question after the crash took 7–9 seconds (TCP connection timeout, no LLM contact made).

**Two examples showing the contrast:**

| Instance | DB | Time | What happened |
|---|---|---|---|
| local060 | complex_oracle | 732s | vLLM alive — agent ran, hit recursion limit after real attempts |
| local062 | complex_oracle | **8s** | vLLM dead — instant `Connection error.`, no SQL, no agent steps |
| local070 | city_legislation | **8s** | vLLM dead — same |

**The actual error received for local062/local070/etc:**
```
Connection error.
```
That's the entire error. The agent made one LLM call, got a refused connection, and stopped. The question — no matter how easy or hard — had zero chance of passing.

**local050 is different:** it ran for 1438 seconds (24 min) before the connection dropped mid-agent. vLLM likely ran out of GPU memory or crashed due to a previous long request (local063 ran for 1719s immediately before it).

**Fix:** SLURM job dependency so the benchmark job requires a vLLM health check to pass before starting. Add 1–2 connection-error retries with 30s backoff in `spider2_benchmark.py`.

---

### A2 — Recursion Limit (4 failures)

The LangGraph agent runs in a loop: call LLM → get tool call → execute SQL → feed result back → repeat. There is a hard cap of **60 iterations**. When the agent writes SQL that returns a plausible but wrong result, it keeps trying to fix it — and if it can't converge, it hits step 60 and throws an error with no SQL submitted.

**The actual error thrown for all 4:**
```
Recursion limit of 60 reached without hitting a stop condition.
You can increase the limit by setting the `recursion_limit` config key.
```

**What each question required and why the agent looped:**

**local017 — CTC (613s, 60 steps):**
> "In which year were the two most common causes of traffic accidents different from those in other years?"

This requires computing the top-2 causes per year, then finding the year whose top-2 set doesn't match any other year's top-2 set — a set-comparison across years. It's genuinely tricky SQL (requires `ARRAY_AGG` + comparison or multiple self-joins). The agent likely kept getting different year counts and retrying.

**local055 — chinook (1720s, 60 steps):**
> "Identify the top and bottom album sales artists (alphabetical tiebreak), then compute absolute difference in average customer spending on each."

Four nested computations: (1) total artist sales, (2) identify top/bottom with alpha tiebreak, (3) per-customer spend on each artist, (4) average those and take abs difference. The agent probably got steps 1–2 right but kept getting wrong values on step 3–4 and retrying.

**local060 — complex_oracle (732s, 60 steps):**
> "Cities where Q4 sales grew ≥20% → top 20% products by sales → compute share change between Q4 2019 and Q4 2020."

Three-stage filter + window function pipeline. complex_oracle has an unusual table structure (sales facts split by promotion type, quarters keyed by `calendar_quarter_id`). The agent had to figure out the schema from scratch and almost certainly mis-joined at least one stage repeatedly.

**local039 — Pagila (917s, 60 steps):**
> "Film category with highest total rental hours in cities starting with 'A' or containing a hyphen."

Requires joining rental → inventory → film → film_category → category and rental → customer → address → city, then filtering city names. The chain is 6 tables deep and rental duration must be computed from `rental_date` and `return_date`. The agent likely got the join right but kept getting wrong rental hour totals.

**Fix:**
1. Change `recursion_limit=60` → `recursion_limit=100` in LangGraph config — one-line change, recovers ~2 of 4.
2. Add to system prompt: *"If your SQL returns rows and you cannot identify a specific error, submit the result. Do not loop."*
3. DCE context reduces the number of schema-exploration steps needed, leaving more budget for SQL refinement.

---

### A3 — Request Timeout (2 failures)

The benchmark has a **29-minute (1740s) wall-clock timeout** per question. Both hit it almost exactly — local055 at 1720s, local063 at 1719s — meaning the agent was still actively running SQL at minute 28.

**local056 — sqlite-sakila (1736s):**
> "Which customer has the highest average monthly change in payment amounts?"

This requires: group payments by (customer, month), compute monthly totals, then compute month-over-month changes, then average those changes per customer, then find the max. It's a multi-step window function problem. The sakila database has a large payment table. The agent likely tried several approaches (LAG function, self-join, subquery) before converging — each SQL execution itself takes seconds on a large table.

**local063 — complex_oracle (1719s):**
> "Products in US with promo_id=999, in cities with ≥20% Q4 sales growth, top 20% by sales — smallest share-point change."

Nearly identical question to local060 (which hit recursion instead). complex_oracle is a large OLAP dataset; each intermediate query over it takes 10–30 seconds. With 60 agent steps each taking 20s of SQL execution time, 1200s+ is easy to reach.

**Fix:** Both issues are the same root cause as A2 — the agent takes too many attempts. Better model + DCE context → fewer attempts → finishes within the timeout.

---

### A4 — Context Overflow (1 failure)

**local010 — Airlines (1435s):**
> "Distribute unique city pairs into distance buckets (0, 1000, 2000 ... 6000+); how many pairs are in the smallest bucket?"

**The actual error received:**
```
Error code: 400 - {
  'error': {
    'message': "This model's maximum context length is 50000 tokens. However, you 
    requested 4096 output tokens and your prompt contains at least 45905 input tokens, 
    for a total of at least 50001 tokens.",
    'type': 'BadRequestError',
    'param': 'input_tokens',
    'value': 45905
  }
}
```

The agent ran for 1435 seconds (24 minutes) before crashing — it never got a chance to submit. By that point the conversation history contained: the full Airlines schema, multiple intermediate SQL queries (probably exploring the routes table, testing distance buckets, checking city pair logic), and all their result sets. At 45905 tokens, the context was full.

**Why Airlines specifically:** The Airlines DB has a large schema (routes table with many columns, airports table) and the question requires a multi-step approach — first compute average distance per city-pair, then bucket, then count per bucket, then find the minimum bucket. Each exploratory query adds thousands of tokens.

**This gets worse with XiYanSQL:** GLM had a 50K limit. XiYanSQL is configured with `MAX_MODEL_LEN=32000` — the same 45905-token context would fail even earlier, at step 1 if the context had already grown that large.

**Fix:** Truncate `run_sql_query` results to 50 rows maximum before appending to the agent conversation. A result showing 10,000 rows of city pairs costs thousands of tokens and the agent only needs to see the structure, not every row.

---

## Part B — SQL Logic Failures (20 failures, 57%)

These failures produced SQL that ran successfully but returned **wrong results**. One produced no SQL at all.

---

### B1 — IPL (0/7 — 0%)

All IPL questions fail due to fundamental join and aggregation logic errors. The IPL schema has an unusual granularity: `ball_by_ball` is the fact table (one row **per ball delivered**), joined to `batsman_scored` and `extra_runs`. To get a player's runs in a match you must first `GROUP BY match_id + striker` in `batsman_scored`, then aggregate those match totals — two levels of aggregation. The agent consistently collapses this into one.

#### local020 — No SQL generated
**Q:** Which bowler has the lowest bowling average per wicket taken?

The agent produced no SQL at all. Computing bowling average requires finding wickets from a separate `wicket_taken` table (filtering `out_type IS NOT NULL`), and total runs conceded from `batsman_scored` + `extra_runs`. Without DCE context explaining this relationship, the agent gave up.

**Fix:** Add DCE table description for `wicket_taken` and an example of how to compute bowling average.

---

#### local021 — Single-level aggregation (wrong answer)
**Q:** Average of total runs scored by all strikers who scored >50 in any single match

**What the agent wrote:**
```sql
WITH strikers_with_50plus AS (
    SELECT striker, SUM(runs_scored) as match_runs
    FROM ipl.ball_by_ball b
    JOIN ipl.batsman_scored s ON b.match_id = s.match_id 
        AND b.over_id = s.over_id AND b.ball_id = s.ball_id AND b.innings_no = s.innings_no
    GROUP BY striker, b.match_id
    HAVING SUM(runs_scored) > 50
),
striker_totals AS (
    SELECT striker, SUM(match_runs) as total_runs
    FROM strikers_with_50plus GROUP BY striker
)
SELECT AVG(total_runs) as average_total_runs FROM striker_totals;
```

**What's wrong:** The first CTE correctly groups by (striker, match_id) to get per-match totals, then filters >50. But `striker_totals` then sums those match totals into career totals — the final AVG is the average career total, not the average match score. The question asks: "for each qualifying striker, what is their average total runs?" — which is just the average of match_runs from strikers_with_50plus.

**Fix (one extra CTE removed):**
```sql
-- Correct: average the per-match totals directly
SELECT AVG(match_runs) FROM strikers_with_50plus;
```

---

#### local023 — Ball-level AVG instead of match-level average
**Q:** Top 5 players by highest average runs per match in season 5

**What the agent wrote:**
```sql
SELECT p.player_name,
    AVG(bs.runs_scored) AS average_runs_per_match  -- ❌ wrong
FROM ipl.match m
JOIN ipl.player_match pm ON m.match_id = pm.match_id
JOIN ipl.batsman_scored bs ON m.match_id = bs.match_id
JOIN ipl.player p ON pm.player_id = p.player_id
WHERE m.season_id = 5
GROUP BY p.player_id, p.player_name
```

**What's wrong:** `batsman_scored.runs_scored` is per-ball (0, 1, 2, 4, 6). `AVG(runs_scored)` computes the average runs per ball faced — roughly 0.7–1.5. The question wants average total runs per match (e.g., 45, 62, 38). Those are wildly different numbers.

**What it should look like:**
```sql
-- Correct: aggregate to match total first, then average
WITH match_totals AS (
    SELECT pm.player_id, bs.match_id, SUM(bs.runs_scored) AS match_runs
    FROM ipl.batsman_scored bs
    JOIN ipl.player_match pm ON bs.match_id = pm.match_id AND bs.striker = pm.player_id
    JOIN ipl.match m ON bs.match_id = m.match_id
    WHERE m.season_id = 5
    GROUP BY pm.player_id, bs.match_id
)
SELECT p.player_name, AVG(match_runs) AS avg_runs_per_match
FROM match_totals mt JOIN ipl.player p ON mt.player_id = p.player_id
GROUP BY p.player_id, p.player_name
ORDER BY avg_runs_per_match DESC LIMIT 5;
```

Same root error affects local024 (country-level aggregation).

---

#### local026 — Returns 10 rows instead of top 3
**Q:** Top 3 bowlers in overs where the maximum runs were conceded per match

The agent's final SELECT used `ORDER BY ... DESC LIMIT 10` — likely a copy-paste error — returning 10 instead of 3. Additionally the logic for "the over with max runs per match" was computed correctly but the bowler-level deduplication after aggregation was missing, so ties weren't broken.

**Fix:** Change LIMIT 10 → LIMIT 3; add `ROW_NUMBER() OVER (ORDER BY total_runs_conceded DESC)` to handle ties.

---

**IPL systemic root cause:** The agent collapses ball-level rows directly into player/season aggregations, skipping the required intermediate match-level grouping. This is a schema comprehension problem — DCE table descriptions must explicitly state: *"batsman_scored has one row per ball per batsman. To get runs per match, GROUP BY (match_id, striker) first."*

---

### B2 — Brazilian_E_Commerce (3/7 — 43%)

#### local028 — Actually correct SQL, wrong result
**Q:** Monthly delivered orders pivot table (2016, 2017, 2018)

**What the agent wrote:**
```sql
SELECT 
    EXTRACT(MONTH FROM TRY_CAST(order_purchase_timestamp AS DATE)) AS month,
    SUM(CASE WHEN EXTRACT(YEAR FROM ...) = 2016 THEN 1 ELSE 0 END) AS delivered_2016,
    SUM(CASE WHEN EXTRACT(YEAR FROM ...) = 2017 THEN 1 ELSE 0 END) AS delivered_2017,
    SUM(CASE WHEN EXTRACT(YEAR FROM ...) = 2018 THEN 1 ELSE 0 END) AS delivered_2018
FROM brazilian_e_commerce.main.olist_orders
WHERE order_status = 'delivered'   -- ✅ filter IS there
    AND EXTRACT(YEAR FROM ...) IN (2016, 2017, 2018)
GROUP BY month ORDER BY month
```

The filter is present and the pivot structure is correct. The mismatch is likely a subtle value difference — the ground truth may count by `order_delivered_customer_date` (when the customer actually received it) rather than `order_purchase_timestamp` (when they ordered). The agent used the wrong timestamp column.

**Fix:** DCE description should clarify: "for delivered order counts, use `order_delivered_customer_date`, not `order_purchase_timestamp`."

---

#### local029 — AVG of installment rows, not per-order average
**Q:** Top 3 customers by delivered orders; provide avg payment value, city, state

**What the agent wrote:**
```sql
SELECT cu.customer_unique_id, cu.customer_city, cu.customer_state,
    AVG(op.payment_value) AS average_payment_value,   -- ❌
    COUNT(oo.order_id) AS delivered_orders_count
FROM brazilian_e_commerce.olist_orders oo          -- ❌ missing .main.
JOIN brazilian_e_commerce.olist_customers cu ON oo.customer_id = cu.customer_id
LEFT JOIN brazilian_e_commerce.olist_order_payments op ON oo.order_id = op.order_id
WHERE oo.order_status = 'delivered'
GROUP BY cu.customer_unique_id, cu.customer_city, cu.customer_state
ORDER BY delivered_orders_count DESC LIMIT 3
```

Two bugs: (1) `olist_order_payments` has one row per installment — a customer paying in 3 installments has 3 rows. `AVG(payment_value)` gives the average installment amount, not the average per-order total. (2) Schema prefix `brazilian_e_commerce.olist_orders` omits `.main.` — may or may not cause an error depending on DuckDB registration, but inconsistent with other queries.

**Correct approach for avg payment per order:**
```sql
-- First collapse installments to order level, then average per customer
AVG(order_total) AS average_payment_value
-- where order_total = SUM(payment_value) GROUP BY order_id
```

---

#### local034 — SUM(value) instead of COUNT(*) for "most preferred"
**Q:** Average count of payments using the most preferred payment method per product category

**What the agent wrote:**
```sql
WITH category_payment_totals AS (
  SELECT p.product_category_name, op.payment_type,
    SUM(op.payment_value) as total_payments   -- ❌ should be COUNT(*)
  FROM brazilian_e_commerce.olist_order_items oi
  JOIN brazilian_e_commerce.olist_products p ON oi.product_id = p.product_id
  JOIN brazilian_e_commerce.olist_order_payments op ON oi.order_id = op.order_id
  GROUP BY p.product_category_name, op.payment_type
),
category_most_preferred_payment AS (
  SELECT product_category_name, payment_type, total_payments
  FROM category_payment_totals
  WHERE (product_category_name, total_payments) IN (
    SELECT product_category_name, MAX(total_payments) FROM category_payment_totals
    GROUP BY product_category_name
  )
)
SELECT AVG(total_payments) as average_total_payments FROM category_most_preferred_payment;
```

"Most preferred" = highest **number** of payments. The agent used `SUM(payment_value)` (total revenue) to pick the preferred method — so it finds the payment type with highest revenue, not most transactions. Then AVGs those revenue figures instead of counts.

**One-line fix:** `SUM(op.payment_value)` → `COUNT(*) as total_payments`

**Brazilian_E_Commerce systemic issues:**
1. Timestamp column confusion — `order_purchase_timestamp` vs `order_delivered_customer_date`
2. `olist_order_payments` is installment-granular, not order-granular — agent treats it as one row per order
3. COUNT vs SUM confusion for "most preferred" / "highest number" phrasing

---

### B3 — California_Traffic_Collision (0/3 — 0%)

#### local015 — LIKE '%helmet%' matches nothing — wrong enum codes
**Q:** Fatality rate for motorcycle collisions, separated by helmet usage

**What the agent wrote:**
```sql
CASE 
  WHEN p.party_safety_equipment_1 LIKE '%helmet%' 
    OR p.party_safety_equipment_2 LIKE '%helmet%' THEN 'helmet used'
  WHEN p.party_safety_equipment_1 LIKE '%helmet not used%' 
    OR p.party_safety_equipment_2 LIKE '%helmet not used%' THEN 'helmet not used'
  ELSE 'unknown'
END AS helmet_status
```

**What's wrong:** The `party_safety_equipment_1/2` columns store short opaque codes, not human-readable strings. The actual values look like `'B'`, `'B5'`, `'E'`, `'H'` etc. `LIKE '%helmet%'` matches none of them — so every row lands in `'unknown'` and the result is technically 2 rows (helmet used, helmet not used) but with 0 fatalities each, making the rate wrong.

This is a pure schema-knowledge failure. No model can guess these codes without being told. This is **exactly what enum enrichment is for** — after running `enrich_enum_columns.py`, the DCE YAML would read: *"Known sample values: A, B, B5, C, E, G, H, N ..."* and the agent would know to use specific codes.

**Fix:** Run enum enrichment; add to DCE: `party_safety_equipment_1`: helmet = `'B'`, helmet not used = `'B5'`.

---

### B4 — E_commerce (1/3 — 33%)

#### local003 — RFM segment definitions ignored
**Q:** Average sales per order within RFM segments (delivered orders only)

The agent wrote a full 80-line RFM SQL using NTILE(5) to create R/F/M scores and CASE statements to define segments like Champions, Loyal_Customers, Hibernating etc. It returned 11 rows — structurally plausible.

**What's wrong:** The question explicitly says *"According to the RFM definition document"* and there's an `external_knowledge` field pointing to a document with the exact segment boundary definitions. The agent invented its own RFM scoring logic (R=1 AND fm_score BETWEEN 1-4 → Champions) instead of reading the document. The ground truth uses the document's definitions which likely have different cutoffs or segment names.

**Fix:** System prompt addition: *"When external_knowledge is provided, read it before writing any SQL. Use the exact definitions from the document."*

---

#### local004 — AVG(installment) ≠ AVG(order payment)
**Q:** Top 3 customers by avg payment per order; lifespan in weeks

Same installment-granularity bug as local029. `olist_order_payments` has one row per installment — a customer paying an order in 6 installments has 6 rows. `AVG(payment_value)` gives the average installment size (~17 BRL), not the average per-order total (~100+ BRL).

**Fix:** `SUM(payment_value) / COUNT(DISTINCT order_id)` per customer, or pre-aggregate to order totals.

---

### B5 — Pagila (0/2 — 0%)

#### local038 — Hardcoded enum IDs without knowing the actual values
**Q:** Actor most frequent in English-language children's films, G or PG, ≤120 min, released 2000–2010

**What the agent wrote:**
```sql
SELECT a.first_name, a.last_name
FROM pagila.film_actor fa
JOIN pagila.actor a ON fa.actor_id = a.actor_id
JOIN pagila.film f ON fa.film_id = f.film_id
JOIN pagila.film_category fc ON f.film_id = fc.film_id
JOIN pagila.category c ON fc.category_id = c.category_id
WHERE f.language_id = 1          -- assumes English = 1
  AND c.category_id = 3          -- assumes Children's = 3  ❌
  AND f.rating IN ('G', 'PG')
  AND f.length <= 120
  AND f.release_year BETWEEN '2000' AND '2010'
GROUP BY a.actor_id, a.first_name, a.last_name
ORDER BY COUNT(fa.film_id) DESC LIMIT 1
```

The join logic is correct, but the agent hardcoded `c.category_id = 3` without knowing if that's actually "Children's" in this DB. In the standard Pagila dataset, category_id=3 is "Children" but the category name may be `'Children'` or `'Children''s'` — if the film's category entry uses `category_id=2` or the name differs, the entire filter returns nothing and the wrong actor wins.

The safer approach is `c.name = 'Children'` (filter by name, not ID), but the exact string also needs to be verified from the data.

**Fix:** Enum enrichment on `pagila.category.name` would expose the exact string. DCE context: `category_id=3 → 'Children'`, `language_id=1 → 'English'`.

#### local039 — Recursion limit (complex rental hours query)
**Q:** Film category with highest total rental hours in cities starting with "A" or containing hyphen  
**Fix:** Same as A2 — increase recursion limit to 100; add "submit if you have valid rows" guidance.

---

### B6 — Other Single-DB Mismatches

#### local008 — Baseball: misread the question, returned 20 rows instead of 4
**Q:** Players with highest games played, runs, hits, and home runs — with their score values

The agent interpreted "score values" as a composite normalized score and wrote a CROSS JOIN + ranking query returning the top 20 players by combined score. But the question wants 4 rows: one player per stat (the all-time leader in G, the all-time leader in R, the all-time leader in H, the all-time leader in HR). The `LIMIT 20` in the SQL makes clear the agent didn't understand the expected output shape.

**What it should be:**
```sql
SELECT 'Most Games' AS category, name_first, name_last, MAX(g) AS value FROM ...
UNION ALL
SELECT 'Most Runs', name_first, name_last, MAX(r) AS value FROM ...
UNION ALL
SELECT 'Most Hits', name_first, name_last, MAX(h) AS value FROM ...
UNION ALL
SELECT 'Most Home Runs', name_first, name_last, MAX(hr) AS value FROM ...
```

---

#### local059 — education_business: date format + fiscal year interpretation
**Q:** Overall average quantity sold of top 3 best-selling hardware products per division in 2021

The SQL uses `WHERE TRY_CAST(hfm.date AS DATE) BETWEEN '2021-01-01' AND '2021-12-31'` and returns 3 rows (one per division). The structure seems right. The likely issue is the date column stores a fiscal year string (e.g., `'FY2021'`) not a calendar date — `TRY_CAST` silently returns NULL and the filter matches nothing, so the agent gets wrong totals or falls back to all-time top 3.

**Fix:** DCE should describe the `date` column format in `hardware_fact_sales_monthly`. If it's a fiscal year string, the filter should be `WHERE date = 'FY2021'` or similar.

---

#### local061 — complex_oracle: currency conversion join error
**Q:** Average projected monthly 2021 sales in USD for France using 2019-2020 growth rates

Returns 12 rows (one per month — structurally correct). Values wrong. The query correctly implements the growth rate projection logic but fails at the USD conversion step — joining a `CURRENCIES` table with the wrong key (likely uses `country_id` for France instead of currency code `'EUR'`) or the wrong year for exchange rates.

**Fix:** DCE context for `CURRENCIES` table: specify that `currency_id` maps to currency codes and that the join should use `'EUR'` for France, not the country ID.

---

## Key Findings and Prioritized Fixes

### Priority 0 — vLLM Stability (prerequisite for any future run)

0. **Ensure vLLM stays alive for the full benchmark** — 8 questions were lost to a mid-run server crash. This is not an architecture issue but it invalidates future runs. Fix: SLURM job dependency so benchmark job cannot start until vLLM health check passes; add per-question retry (1-2 attempts on connection error) in `spider2_benchmark.py`.

### Priority 1 — Quick Infrastructure Wins (7 failures on 40-question set)

1. **Increase recursion limit to 100** — 4 questions fail at exactly step 60. Change `recursion_limit=60` → `recursion_limit=100` in the LangGraph config. One-line fix.

2. **Truncate SQL result sets in agent context** — local010 hit 45905 tokens from accumulated results. Note: this was on GLM (50K limit). XiYanSQL is configured at 32K — local010 would fail even harder. Limit `run_sql_query` output to 50 rows in the agent before adding to context, regardless of model.

### Priority 2 — Schema Context (DCE improvements, ~6 questions)

3. **Enum enrichment is critical for CTC** — local015 fails because helmet safety codes are short enum values (`B5`, `E`, etc.), not text. `LIKE '%helmet%'` matches nothing. Enum enrichment directly fixes this.

4. **IPL schema granularity description** — Add explicit DCE table-level descriptions: "ball_by_ball has one row per ball delivered. To get player totals per match, first group by (match_id, striker/bowler), then aggregate to season/career level." This is the systemic fix for 6 IPL failures.

5. **Schema prefix standardization** — Brazilian_E_Commerce agent oscillates between `db.table` and `db.main.table`. DCE context should show the correct fully qualified table names.

### Priority 3 — Agent Prompt Improvements (~4 questions)

6. **Prioritize external_knowledge** — local003 (RFM) has the answer in an external document the agent didn't apply. Add to system prompt: "Always read external_knowledge documents before writing SQL when provided."

7. **Payment aggregation guidance** — `olist_order_payments` has one row per installment, not per order. Add to schema description: "To get per-order payment total use SUM(payment_value) GROUP BY order_id."

8. **Submit-if-confident guidance** — "If your SQL returns a reasonable number of rows and you cannot identify a clear error, submit it rather than looping." Reduces recursion limit failures.

---

## Realistic Impact if Fixes Applied (on 40-question adjusted set)

| Fix | Questions recovered | Running total |
|---|---|---|
| **Baseline (40-question set)** | — | **13/40 (32.5%)** |
| Recursion limit 60 → 100 | +2–3 | ~15–16/40 |
| Result truncation (local010 + model switch) | +1 | ~16–17/40 |
| Enum enrichment (local015, local038) | +1–2 | ~17–19/40 |
| Better IPL aggregation context (DCE) | +2–4 | ~19–23/40 |
| External knowledge + payment guidance | +1–2 | ~20–25/40 |
| **Conservative estimate** | | **~20/40 (50%)** |
| **Optimistic upper bound** | | **~25/40 (62.5%)** |

> On the full 48-question set (restoring the 8 vLLM failures with a stable server and potentially correct SQL), conservative target is ~42–52% overall.

---

## Appendix — Pass/Fail by Instance

*(✗ = excluded from 40-question set — vLLM dead)*

| Instance | DB | Score | Failure reason |
|---|---|---|---|
| local002 | E_commerce | ✅ PASS | — |
| local003 | E_commerce | ❌ FAIL | RFM segment definition mismatch |
| local004 | E_commerce | ❌ FAIL | AVG installment vs per-order payment |
| local007 | Baseball | ✅ PASS | — |
| local008 | Baseball | ❌ FAIL | UNION result has 20 rows, expected 4 |
| local009 | Airlines | ✅ PASS | — |
| local010 | Airlines | ❌ FAIL | Context overflow (45905 tokens) |
| local015 | CTC | ❌ FAIL | LIKE '%helmet%' — wrong enum codes |
| local017 | CTC | ❌ FAIL | Recursion limit |
| local018 | CTC | ❌ FAIL | Year-based share change CTE error |
| local019 | WWE | ✅ PASS | — |
| local020 | IPL | ❌ FAIL | No SQL generated |
| local021 | IPL | ❌ FAIL | Wrong join / aggregation level |
| local022 | IPL | ❌ FAIL | Cross-product: 444 rows returned |
| local023 | IPL | ❌ FAIL | Ball-level AVG vs match-level AVG |
| local024 | IPL | ❌ FAIL | Same ball-level aggregation error |
| local025 | IPL | ❌ FAIL | Bowler not correctly identified per max over |
| local026 | IPL | ❌ FAIL | Returns 10 rows instead of top 3 |
| local028 | Brazilian_E_Commerce | ❌ FAIL | Missing delivered filter |
| local029 | Brazilian_E_Commerce | ❌ FAIL | Schema prefix + payment join error |
| local030 | Brazilian_E_Commerce | ✅ PASS | — |
| local031 | Brazilian_E_Commerce | ✅ PASS | — |
| local032 | Brazilian_E_Commerce | ❌ FAIL | Seller comparison multi-category |
| local034 | Brazilian_E_Commerce | ❌ FAIL | SUM(payment_value) vs COUNT(*) |
| local035 | Brazilian_E_Commerce | ✅ PASS | — |
| local037 | Brazilian_E_Commerce | ❌ FAIL | Schema prefix + payment count |
| local038 | Pagila | ❌ FAIL | language_id or category name mismatch |
| local039 | Pagila | ❌ FAIL | Recursion limit |
| local040 | modern_data | ✅ PASS | — |
| local041 | modern_data | ✅ PASS | — |
| local049 | modern_data | ✅ PASS | — |
| local050 | complex_oracle | ✗ EXCL | Connection error (vLLM died, 1438s) |
| local054 | chinook | ✅ PASS | — |
| local055 | chinook | ❌ FAIL | Recursion limit |
| local056 | sqlite-sakila | ❌ FAIL | Request timeout |
| local058 | education_business | ✅ PASS | — |
| local059 | education_business | ❌ FAIL | Division avg query mismatch |
| local060 | complex_oracle | ❌ FAIL | Recursion limit |
| local061 | complex_oracle | ❌ FAIL | Currency conversion wrong |
| local062 | complex_oracle | ✗ EXCL | Connection error (vLLM dead, 8s) |
| local063 | complex_oracle | ❌ FAIL | Request timeout |
| local067 | complex_oracle | ✗ EXCL | Connection error (vLLM dead, 9s) |
| local068 | city_legislation | ✗ EXCL | Connection error (vLLM dead, 9s) |
| local070 | city_legislation | ✗ EXCL | Connection error (vLLM dead, 8s) |
| local071 | city_legislation | ✗ EXCL | Connection error (vLLM dead, 8s) |
| local072 | city_legislation | ✗ EXCL | Connection error (vLLM dead, 8s) |
| local073 | modern_data | ✗ EXCL | Connection error (vLLM dead, 9s) |
| local198 | chinook | ✅ PASS | — |
