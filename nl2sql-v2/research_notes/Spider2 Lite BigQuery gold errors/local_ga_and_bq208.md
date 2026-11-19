# Spider 2.0-Lite gold answers for bq397, ga010, bq002 and bq208: wrong, inconsistent, or ambiguous?

Evidence labels used below:
- **[file]**: verified by reading a local file (question, gold SQL, gold CSV, scorer, doc).
- **[trace]**: a BigQuery result recorded in our agent's Nov 17 2026 traces. The agent ran these queries during the benchmark run; I only read the trace files. I ran no SQL against any cloud service.
- **[doc]**: official documentation fetched on 2026-11-18.
- **[calc]**: my own local arithmetic on cited values (Python, no data access).
- **Inference**: my reasoning. These items appear only under "Inferences".

Repo root: `/Users/deepikapalagani/Documents/nl2sql-databao`. Lanes k1–k4 are the four candidates per question in `results/bq17/bigquery_passk_nov2026_17/lane_k*/`.

Scorer behaviour that matters for all four questions [file: `evaluate.py` lines 67–131]: each gold file is checked on its own and matching any one file passes. Within a file, every gold column chosen by `condition_cols` must equal some predicted column. The values form vectors, which are sorted when `ignore_order` is set. Vector lengths must be equal, so the row count must match. Numbers are compared with `math.isclose(..., abs_tol=1e-2)`. When `condition_cols` is empty, all gold columns are checked. Extra predicted columns are ignored. — [evaluate.py](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/evaluate.py)

---

## 1. bq397 (db ecommerce, table rev_transactions): question, gold SQL, gold files, verdict

### Takeaway
The gold SQL contradicts its own gold files. The SQL removes only exact duplicate rows and then sums a session-level total that repeats on every hit row. That method returns Direct 16,541 and makes Venezuela the top country for Social. All four gold files count each session once instead (Direct 6,650–6,652, Social top = United States). Verdict **(a)**, high confidence. The root cause is **(c)**: the question supports both a literal and a session-level reading. There is also a **(d)** patchwork, since the four accepted files are different session-key variants.

### Cited Findings

**Question and scoring**
- Question, verbatim: "After removing any duplicate records from the rev_transactions dataset, identify each channel grouping that has transactions from more than one country. For each such channel grouping, find the country with the highest total number of transactions and report both the country name and the sum of transactions for that channel grouping." The task has no external-knowledge doc (`external_knowledge: null`). [file] — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl)
- Scoring config: `"condition_cols": [2], "ignore_order": true`. Only the third column (the transaction sum) is checked, and the same `[2]` applies to each of the four files. [file] — [spider2lite_eval.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl); [evaluate.py](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/evaluate.py) lines 73–74

**Gold SQL (key lines)** [file] — [bq397.sql](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/sql/bq397.sql)
```sql
WITH tmp AS (
  SELECT DISTINCT *
  FROM `data-to-insights.ecommerce.rev_transactions`
  -- Removing duplicated values
),
tmp1 AS (SELECT tmp.channelGrouping, tmp.geoNetwork_country,
                SUM(tmp.totals_transactions) AS tt FROM tmp GROUP BY 1, 2),
... COUNT(DISTINCT geoNetwork_country) OVER (PARTITION BY channelGrouping) AS CountryCount
... RANK() OVER (PARTITION BY channelGrouping ORDER BY TotalTransaction DESC) AS rnk
    ... WHERE CountryCount > 1
SELECT channelGrouping, Country, TotalTransaction FROM tmp3 WHERE rnk = 1;
```

**Gold files** (6 rows each; every country is "United States") [file] — [bq397_a.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq397_a.csv), [_b](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq397_b.csv), [_c](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq397_c.csv), [_d](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq397_d.csv)

| channelGrouping | gold_a | gold_b | gold_c | gold_d |
|---|---:|---:|---:|---:|
| Direct | 6651 | 6651 | 6652 | 6650 |
| Display | 203 | 203 | 203 | 203 |
| Organic Search | 3785 | 3773 | 3785 | 3785 |
| Paid Search | 580 | 580 | 580 | 580 |
| Referral | 12280 | 12280 | 12280 | 12278 |
| Social | 164 | 164 | 164 | 164 |

- Headers: a `channelGrouping,country,total_transactions`; b `channelGrouping,country,sum_transactions`; c `channelGrouping,COUNTRY_NAME,SUM_OF_TRANSACTIONS`; d `channelGrouping,geoNetwork_country,total_transactions`. None of them carries the gold SQL's output aliases (`Country`, `TotalTransaction`). [file] — same files
- The four files are byte-identical to Spider2-snow's `sf_bq397_a..d.csv`. Spider2-snow has the same question and the same `condition_cols`, and no gold SQL for this task. [file] — [sf_bq397_a.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-snow/evaluation_suite/gold/exec_result/sf_bq397_a.csv); [spider2snow_eval.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-snow/evaluation_suite/gold/spider2snow_eval.jsonl)

**What the table is, and what each method returns** [trace]
- rev_transactions columns include `hits_time, hits_type, hits_product_productSKU, hits_product_v2ProductName, hits_transaction_transactionId, totals_transactions, ...`. Its sample rows show one session spread over at least 4 rows, one per product. The session is fullVisitorId 7851878234225373633, visitId 1470617094, transaction ORD20160807983, and every one of its rows carries `totals_transactions = 1`. — [lane_k2 trace, step 0](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k2/traces/bq397.json)
- Size: 56,535 rows; 23,916 distinct fullVisitorId–visitId pairs; 23,919 distinct transaction IDs. Exact duplicate rows do exist: a GROUP BY over all columns with HAVING COUNT(*) > 1 returns rows with dup_count 2, 3 and 10. — [lane_k2 trace, steps 2 and 6](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k2/traces/bq397.json)
- **No deduplication** (lane k1 computed ROW_NUMBER but never filtered `rn = 1`): Direct 16561, Display 804, Organic Search 12407, Paid Search 1779, Referral 29062, Social → **Venezuela** 447. — [lane_k1 trace, step 8 (q6)](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k1/traces/bq397.json)
- **Exact-duplicate removal, the gold SQL's method** (lane k2: `SELECT DISTINCT *`, SUM(totals_transactions), more than one country, top-1 by ROW_NUMBER): Direct 16541, Display 803, Organic Search 12394, Paid Search 1774, Referral 28933, Social → **Venezuela** 447. The Social breakdown is Venezuela 447, United States 340, Indonesia 232. — [lane_k2 trace, steps 8 and 10](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k2/traces/bq397.json)
- **One row per (fullVisitorId, visitId, date)** (lane k3, first row by hits_time): 6652 / 203 / 3785 / 580 / 12280 / 164, all United States. Scored "matches bq397_c.csv". — [lane_k3 trace](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/traces/bq397.json); [lane_k3 all.csv](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/all.csv)
- **One row per (fullVisitorId, visitId)** (lane k4, first row by hits_time): 6651 / 203 / 3773 / 580 / 12280 / 164, all United States. Scored "matches bq397_b.csv". — [lane_k4 trace, step 17](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/traces/bq397.json); [lane_k4 all.csv](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/all.csv)

**Dataset documentation**
- GA360 export: "Each row within a table corresponds to a session in Analytics 360." `totals` "contains aggregate values across the session"; `totals.transactions` is the "Total number of ecommerce transactions within the session"; `hits` "row and nested fields are populated for any and all types of hits." `visitId` "is only unique to the user. For a completely unique ID, you should use a combination of fullVisitorId and visitId." [file, Spider2's copy of the official schema] — [google_analytics_sample.ga_sessions.md](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/documents/google_analytics_sample.ga_sessions.md). The original page is "[UA] BigQuery Export schema [Legacy]" — [Google Analytics Help](https://support.google.com/analytics/answer/3437719). That URL now serves the GA4 schema page when fetched, so the quotes come from the Spider2 copy.

### Inferences
**Can the gold SQL produce the files? No.**
- The gold SQL's logic matches lane k2's query: `SELECT DISTINCT *`, a sum by channel and country, more than one country, top 1 per channel. The differences are RANK vs ROW_NUMBER and a windowed rather than grouped country count. These only change the output when there is a tie for first place, and the observed top values are far apart (Social: 447 vs 340; Direct: 16541 vs 1172). The gold SQL should therefore return k2's six rows: 16541, 803, 12394, 1774, 28933, and Venezuela 447. Those are 2.4–4.0x the file values [calc: 16541/6651 = 2.49, 803/203 = 3.96, 12394/3773 = 3.28, 1774/580 = 3.06, 28933/12280 = 2.36], with a different country for Social. No gold file contains them.
- `SELECT DISTINCT *` cannot collapse a session to one row, because the product rows of a session differ in their `hits_product_*` columns. Even a later change to the table's data would not let the SQL as written yield session-level counts. I have not verified whether the table changed after the gold was made (see Gaps).
- The gold files' headers do not match the SQL's aliases. gold_c's uppercase headers resemble Snowflake output, and the files are shared with Spider2-snow. That suggests the files came from other queries, which were never reconciled with the BigQuery SQL. This is a weaker, circumstantial point.

**Verdict: (a) gold SQL contradicts gold files. High confidence.**
- Underlying ambiguity **(c)**: "removing any duplicate records" literally means exact-duplicate rows, which the gold SQL removes and which really exist in this table. The question then asks for "the sum of transactions". On a hit-level table, summing the session total `totals_transactions` after exact-duplicate removal counts each session's transactions once per product row. That is not a count of transactions in any meaningful sense. The gold files apply the sounder session-level deduplication, which the question's wording does not state.
- **(d)**: the four files are near-identical session-level variants (Direct 6650/6651/6652; Organic Search 3773/3785; Referral 12278/12280). gold_b equals a (fullVisitorId, visitId) key and gold_c equals a (fullVisitorId, visitId, date) key, as lanes k4 and k3 show. gold_a mixes the two (6651 with 3785). I could not tie gold_d to a specific key. With the 0.01 tolerance, a session-level answer passes only if it lands exactly on one of these variants.
- The 3773 vs 3785 gap probably comes from sessions that span midnight and appear under two dates. Keying on (fullVisitorId, visitId) keeps one half, while keying with the date keeps both halves and their separate totals. This is inferred, not checked.

**Correct answer and lanes**
- Session-level reading (sounder; it is what the files hold): United States tops all six channels. Direct ≈ 6,650–6,652, Display 203, Organic Search 3,773–3,785, Paid Search 580, Referral 12,278–12,280, Social 164. (Channels "(Other)" and "Affiliates" have one country each and drop out.) The most defensible key is (fullVisitorId, visitId, date), i.e. gold_c, because each date-split part has its own totals.
- Literal reading (the gold SQL's): Direct 16,541, Display 803, Organic Search 12,394, Paid Search 1,774, Referral 28,933, Social → Venezuela 447.
- Lanes: **k3** and **k4** are correct under the session reading and pass now. **k2** is correct under the literal reading, which is exactly the gold SQL, but it fails now. **k1** is wrong under both, because it never actually removed duplicates. A corrected label that accepts both readings would pass k2, k3 and k4.

**Plain-language explanation**
rev_transactions stores one row per product line inside each page hit, so a session's "transactions" total is copied onto every one of its rows. The gold SQL drops only rows that are exact copies, then adds up that copied total. That gives Direct 16,541 and makes Venezuela the top country for Social, and our lane k2 ran exactly this logic. All four gold result files instead keep one row per session (Direct about 6,651, Social's top country the United States), which the gold SQL cannot produce. The per-session numbers are the meaningful count of transactions, but the question's "remove duplicate records" describes the gold SQL's literal step. So the benchmark's label disagrees with its own SQL and rewards only one of two defensible readings.

### Gaps
- I did not execute the gold SQL (forbidden by the constraints). Its output is inferred from lane k2's equivalent query in the trace.
- I could not determine which query produced gold_a (a mix of keys) or gold_d (Direct 6650, Referral 12278), or whether `data-to-insights.ecommerce.rev_transactions` changed after the gold was created.
- I did not find the origin of the gold SQL or the course material behind the `data-to-insights` table.

---

## 2. ga010 (db ga4, GA4 obfuscated sample): question, gold SQL, gold files, verdict

### Takeaway
The asked-for channel, **Referral** in fourth place by sessions, is right under every method used by us and by all four gold files. The label set is a patchwork, though. gold_d checks only the channel name, so any one-row answer naming Referral passes, even one that reports an event count (lane k1's 295,924). Meanwhile, a full channel ranking (a fair reading of "overview") fails every file. gold_b, the only multi-row file, folds Paid Search into Organic Search, contrary to the reference doc. Verdict **(d)** scoring artifact plus **(c)** two readings of the output shape. High confidence on the channel; medium on the exact session count.

### Cited Findings

**Question, doc and scoring**
- Question, verbatim: "Can you give me an overview of our website traffic for December 2020? I'm particularly interested in the channel with the fourth highest number of sessions." External knowledge: `ga4_dimensions_and_metrics.md`. [file] — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl)
- Doc rules (excerpt). **Direct**: "Source exactly matches "(direct)" AND Medium is one of ("(not set)", "(none)")". **Paid Search**: "Source matches a list of search sites (baidu,bing,duckduckgo,ecosia,google,yahoo,yandex) AND Medium matches regex `^(.*cp.*|ppc|paid.*)$`". **Organic Search**: "Source matches a list of search sites … OR Medium exactly matches organic". **Referral**: "Medium exactly matches Referral". **Unassigned**: "Others". [file] — [ga4_dimensions_and_metrics.md](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/documents/ga4_dimensions_and_metrics.md)
- Scoring: `"condition_cols": [], "ignore_order": true`. Every column of a gold file must be matched. [file] — [spider2lite_eval.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl); [evaluate.py](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/evaluate.py) lines 71–72, 113–118

**Gold SQL (key lines)** [file] — [ga010.sql](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/sql/ga010.sql)
```sql
(SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS session_id,
ARRAY_AGG((SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'source') IGNORE NULLS
          ORDER BY event_timestamp)[SAFE_OFFSET(0)] AS source,      -- same for medium, campaign
... WHERE _TABLE_SUFFIX BETWEEN '20201201' AND '20201231'
GROUP BY user_pseudo_id, session_id
...
WHEN REGEXP_CONTAINS(source,'baidu|bing|duckduckgo|ecosia|google|yahoo|yandex')
     AND REGEXP_CONTAINS(medium,'^(.*cp.*|ppc|paid.*)$') THEN 'Paid Search'
...
GROUP BY channel_grouping_session
ORDER BY COUNT(DISTINCT CONCAT(user_pseudo_id, session_id)) DESC
LIMIT 1 OFFSET 3
```
The output is one column (the channel name) and one row, with no session count.

**Gold files** [file] — [ga010_a.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/ga010_a.csv), [_b](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/ga010_b.csv), [_c](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/ga010_c.csv), [_d](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/ga010_d.csv)
- gold_a (1 row): `CHANNEL,SESSIONS` / `Referral,23082`
- gold_b (4 rows): `CHANNEL,SESSIONS,SESSIONS_RANK,IS_FOURTH_HIGHEST`: Organic Search 51193 1 False; Direct 30516 2 False; Unassigned 27035 3 False; Referral 23092 4 True
- gold_c (1 row): `channel,sessions,sessions_pct,sessions_rank` / `Referral,23082,17.307,4`
- gold_d (1 row): `CHANNEL_GROUP` / `Referral`
- All four files are byte-identical to Spider2-snow's `sf_ga010_*.csv`. [file] — [sf_ga010_b.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-snow/evaluation_suite/gold/exec_result/sf_ga010_b.csv)

**Our four candidates** [trace]
- **k1**: COUNT(*) over all events, channel taken from `traffic_source.*`, `LIMIT 1 OFFSET 3`, giving `Referral, 295924`. Scored "matches ga010_d.csv". — [lane_k1 trace, step 20](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k1/traces/ga010.json); [lane_k1 all.csv](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k1/all.csv)
- **k2**: `event_name = 'session_start'`, `platform = 'WEB'`, channel from `traffic_source.*`, full ranking: Organic Search 45298, Direct 30516, Unassigned 27035, Referral 23092, Paid Search 5895 (5 rows). Fails every file. — [lane_k2 trace, step 16](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k2/traces/ga010.json)
- **k3**: the same method and the same 5 rows and counts as k2. Fails. — [lane_k3 trace, step 8](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/traces/ga010.json)
- **k4**: page_view events only, `COUNT(DISTINCT ga_session_id)` without user_pseudo_id, a cut-down CASE. Result: Organic Search 43020, Direct 28588, Unassigned 24711, Referral 20953, Paid Search 5787, with a rank column (5 rows). Fails. — [lane_k4 trace, step 12](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/traces/ga010.json)

**GA4 documentation**
- `traffic_source.source`: "Name of the network that first acquired the user"; `traffic_source.medium`: "Name of the medium … that first acquired the user"; "The traffic_source values do not change if the user interacts with subsequent campaigns after installation." The schema also has a `session_traffic_source_last_click` record with "last-click attributed session traffic source data". [doc] — [GA4 BigQuery Export schema](https://support.google.com/analytics/answer/7029846)
- "Session default channel group" is session-scoped (the channel that brought users in when they started new sessions). "First user default channel group" is user-scoped (the channel through which each user first arrived). Paid Search requires medium matching `^(.*cp.*|ppc|retargeting|paid.*)$`. Unassigned "is the value Analytics uses when there are no other channel rules that match the event data." [doc] — [Default channel group, Analytics Help](https://support.google.com/analytics/answer/9756891)
- Session counting: "The `ga_session_id` event parameter identifies individual unique sessions for each user." "The combination of `user_pseudo_id` and `ga_session_id` will be unique across your dataset for unique sessions." "This is the standard method of counting sessions for Google Analytics 4 properties." Google's example SQL passes the INT64 session id straight into `CONCAT(user_pseudo_id, (...).int_value)` on this exact dataset. [doc] — [Unique count approximation in Google Analytics (Minhaz Kazi, Oct 2022)](https://developers.google.com/analytics/blog/2022/hll)
- Sample dataset: "ga4_obfuscated_sample_ecommerce" covers "2020-11-01 to 2021-01-31". "Certain fields will contain placeholder values including `<Other>`, `NULL`, and `''`", and "internal consistency of the dataset might be somewhat limited." [doc] — [GA4 web ecommerce demo dataset](https://developers.google.com/analytics/bigquery/web-ecommerce-demo-dataset)

### Inferences
**Can the gold SQL produce the files?**
- It produces exactly gold_d's content: one row and one column holding the fourth channel, which every method puts at Referral. It cannot produce gold_a, gold_b or gold_c, because it outputs no counts. I cannot check statically whether its hidden session count is 23,082 (see Gaps). The SQL is valid BigQuery as far as I can tell: Google's own example uses the same INT64-in-CONCAT pattern.
- gold_b is inconsistent with the gold SQL and with the doc. Its Organic Search 51,193 equals k2's Organic Search 45,298 plus Paid Search 5,895 exactly [calc]. The gold SQL has a Paid Search branch, and the doc defines google + cpc as Paid Search. gold_b's Direct 30,516, Unassigned 27,035 and Referral 23,092 equal k2's and k3's counts exactly. Those counts come from session_start events grouped by the user-scoped `traffic_source.*`. So gold_b was most likely built from the first-user source with Paid Search merged, not from the session-scoped source the gold SQL uses (strong inference: three exact matches).
- gold_c's share of 17.307% implies about 23,082 / 0.17307 ≈ 133,368 total sessions (±4) [calc]. The session_start total from k2 is 131,836 [calc]. So gold_c used another session definition. Plausibly it counted distinct user_pseudo_id + ga_session_id pairs, which include sessions without a session_start event; this is unverified.

**Scoring mechanics (why this is (d))**
- gold_d has a single column, so any single-row prediction containing "Referral" in some column passes, whatever count it reports. That is how k1's event count passes. A one-row answer of Referral with 23,092 (k2/k3's count) would fail gold_a and gold_c (|23092 − 23082| = 10 > 0.01) but still pass gold_d.
- A multi-row overview passes only by reproducing gold_b exactly. That means four rows and no more, Organic Search at 51,193 with Paid Search merged in, a rank column, and a boolean `IS_FOURTH_HIGHEST` column. A doc-compliant ranking that keeps Paid Search separate can never match it. gold_c additionally demands a percent column ≈ 17.307 and a rank column = 4.

**Verdict: (d) scoring artifact + (c) two readings of the output shape.**
- (c): "an overview of our website traffic" invites a channel table, while "particularly interested in the channel with the fourth highest number of sessions" points to one channel. Three of the four files take the single-channel reading.
- Not (b): Referral is fourth under every method (4 lanes and 4 files, with first-user or session-scoped source, session_start or ga_session_id counting). Not (a): the gold SQL's own output equals gold_d.
- Confidence: high that the answer channel is Referral, and high that k1 passes only through gold_d. Medium on the "right" session count. 23,082 (gold_a/c) and 23,092 (gold_b, k2/k3) are both defensible. The GA4-standard method (session-scoped source, distinct user_pseudo_id + ga_session_id) is what the gold SQL encodes.
- Minor alternative: if "Unassigned" (third, 27,035) were not treated as a real channel, the fourth would be Paid Search. The doc lists Unassigned as a channel ("Unassigned | Others"), so the gold's choice follows the doc. The obfuscation placeholders (`<Other>`, NULL, '') plausibly inflate Unassigned.

**Correct answer and lanes**
- Correct answer: **Referral**, fourth after Organic Search, Direct and Unassigned, with about 23,082–23,092 sessions depending on the session and source definition. Paid Search (about 5,900) is fifth when split out per the doc.
- Under a corrected label that accepts either a single channel or an overview, and requires a session count in the defensible band: **k2** and **k3** are correct (Referral 23,092, fourth in a ranked list). **k1** names the right channel but reports 295,924 events as sessions (12.8x k2's 23,092 [calc]), so it is correct only if the label checks the channel alone, as gold_d does. **k4** names Referral fourth, but its 20,953 undercounts (page_view only, a non-unique session key, a cut-down mapping), so it too is correct only on a channel-only label.
- Today only k1 passes, which is the opposite of what a count-aware label would do.

**Plain-language explanation**
Every method we tried, and every gold file, agrees that the channel with the fourth-most sessions in December 2020 is Referral. The four gold files disagree on everything else. Two say 23,082 sessions; one says 23,092 inside a top-4 table that merges Paid Search into Organic Search; one contains only the word "Referral". Because that last file checks just the channel name, a one-row answer passes even with a badly wrong number: our lane k1 reported 295,924 events as "sessions" and was scored correct. A full channel ranking, a fair answer to "give me an overview", fails every file unless it copies the top-4 table's exact layout. So the gold channel is right, but the scoring rewards output shape rather than correct counts.

### Gaps
- I did not run the gold SQL, so its Referral session count (perhaps 23,082) is unconfirmed.
- I did not confirm which query produced gold_a/gold_c (23,082) or gold_b's merged mapping.
- I did not check whether the obfuscated sample's `event_params` source/medium values give the same ranking as `traffic_source.*`. All observed methods agree on Referral, but none of our lanes used the session-scoped event_params source.

---

## 3. bq002 (db ga360, google_analytics_sample.ga_sessions): question, gold SQL, gold files, verdict

### Takeaway
The gold SQL contradicts its gold files on the **weekly** maximum. The SQL buckets weeks with BigQuery's `EXTRACT(WEEK ...)`, which starts weeks on Sunday and gives 35,854.64. All three gold files hold 36,474.27, the Monday-start (ISO-style) week. The files match Snowflake's default Monday-start week semantics and are shared byte-for-byte with Spider2-snow. Verdict **(a)**, high confidence. There is also **(c)**: the question fixes neither the week start nor what "in millions" means for micro-unit revenue. And **(d)**: gold_b checks the total but not the monthly figure, under a loose ±0.01 tolerance on million-scale values. Lane k4 computed exactly what the BigQuery gold SQL specifies and was marked wrong.

### Cited Findings

**Question, doc and scoring**
- Question, verbatim: "During the first half of 2017,  focusing on hits product revenue, which traffic source generated the highest total product revenue, and what were the maximum daily, weekly, and monthly product revenues (in millions) for that top-performing source over this period?" External knowledge: `google_analytics_sample.ga_sessions.md`. [file] — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl)
- Doc: `hits.product.productRevenue` — "The revenue of the product, expressed as the value passed to Analytics multiplied by 10^6 (e.g., 2.40 would be given as 2400000)." [file] — [google_analytics_sample.ga_sessions.md](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/documents/google_analytics_sample.ga_sessions.md) (line 220)
- Scoring: `"condition_cols": [[1, 2, 3], [1, 2, 3], [0]], "ignore_order": true`. [file] — [spider2lite_eval.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl)

**Gold SQL (key lines)** [file] — [bq002.sql](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/sql/bq002.sql)
```sql
DECLARE start_date STRING DEFAULT '20170101';  DECLARE end_date STRING DEFAULT '20170630';
... SUM(productRevenue) / 1000000 AS revenue
FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`, UNNEST (hits) AS hits, UNNEST (hits.product) AS product
... CONCAT(EXTRACT(YEAR FROM (PARSE_DATE('%Y%m%d', date))), 'W',
          EXTRACT(WEEK FROM (PARSE_DATE('%Y%m%d', date)))) AS week
... CONCAT(EXTRACT(YEAR FROM (PARSE_DATE('%Y%m%d', date))),'0', EXTRACT(MONTH FROM (PARSE_DATE('%Y%m%d', date)))) AS month
... SELECT max_revenue FROM max_revenues ORDER BY max_revenue DESC;
```
The output is one column, `max_revenue`, with three rows (the daily, weekly and monthly maxima for the top source), in micros/10^6, i.e. currency units.

**Gold files** [file] — [bq002_a.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq002_a.csv), [_b](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq002_b.csv), [_c](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq002_c.csv)
- gold_a (1 row): `TOP_TRAFFIC_SOURCE,MAX_DAILY_REVENUE_MILLIONS,MAX_WEEKLY_REVENUE_MILLIONS,MAX_MONTHLY_REVENUE_MILLIONS` / `(direct),21148.43,36474.27,99301.44`. Columns 1–3 (daily, weekly, monthly) are checked.
- gold_b (1 row): `TRAFFIC_SOURCE,TOTAL_PRODUCT_REVENUE_MILLIONS,MAX_DAILY_…,MAX_WEEKLY_…,MAX_MONTHLY_…` / `(direct),0.581583,0.021148,0.036474,0.099301`. Columns 1–3 are checked, which are **total, daily, weekly**. Monthly (column 4) is not checked.
- gold_c (3 rows): `MAX_REVENUE` / `21148.429980`, `36474.269938`, `99301.439750`. Column 0 is checked.
- All three files are byte-identical to Spider2-snow's `sf_bq002_a..c.csv`. Spider2-snow has the same question and `condition_cols`, and ships no gold SQL for this task. [file] — [sf_bq002_c.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-snow/evaluation_suite/gold/exec_result/sf_bq002_c.csv); [spider2snow_eval.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-snow/evaluation_suite/gold/spider2snow_eval.jsonl)

**Values observed in our traces** [trace]
- Daily maximum for (direct): 2017-02-14, 21,148.42998 (micros/10^6). Lanes k2 (as raw micros 21148429980), k3 and k4 all get this. — [lane_k3 trace, step 9](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/traces/bq002.json); [lane_k4 trace, step 10](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/traces/bq002.json)
- **Sunday-start weeks** (`DATE_TRUNC(…, WEEK)`): top week starts 2017-02-12 at **35,854.639935** (k4; k2 gets 35854639935 in micros). — [lane_k4 trace, step 11](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/traces/bq002.json); [lane_k2 trace, step 10](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k2/traces/bq002.json)
- **Monday-start weeks** (`DATE_TRUNC(…, WEEK(MONDAY))`): top week starts 2017-02-13 at **36,474.269938**. — [lane_k3 trace, step 39](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/traces/bq002.json)
- Monthly maximum: 99,301.43975 (k4) / 99301.43974999996 (k3). Total product revenue by source: (direct) 581,583.078285, google 134,507.219422, dfa 119,125.429951. — [lane_k4 trace, steps 14 and 16](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/traces/bq002.json); [lane_k3 trace, step 42](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/traces/bq002.json)
- Final answers: **k1** `(direct), 7625.543807, 18745.023775, 49725.415429`. It sums only `h.product[OFFSET(0)]`, the first product of each hit. **k2** `(direct), 21.14842998, 35.854639935, 99.30143975`. It divides by 10^9 and uses Sunday weeks. **k3** `(direct), 21148.42998, 36474.269938, 99301.43975`, scored "matches bq002_a.csv". **k4** `(direct), 21148.43, 35854.64, 99301.44` (Sunday weeks, rounded), scored as a mismatch. — lane traces and [all.csv files](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k1/all.csv)

**Function semantics**
- BigQuery `EXTRACT` WEEK: "Returns the week number of the date in the range [0, 53]." "Weeks begin with Sunday, and dates prior to the first Sunday of the year are in week 0." ISOWEEK: "`ISOWEEK`s begin on Monday." `DATE_TRUNC` WEEK: "Weeks begin on Sundays." "`WEEK` is equivalent to `WEEK(SUNDAY)`." [doc] — [BigQuery date functions](https://cloud.google.com/bigquery/docs/reference/standard-sql/date_functions)
- Snowflake: "The default value for both parameters [WEEK_START, WEEK_OF_YEAR_POLICY] is `0`, which preserves the legacy Snowflake behavior (ISO-like semantics)." Policy 0 means "a week belongs to a given year if at least 4 days of that week are in that year". `WEEK_START` 0 or 1 gives "ISO week semantics, with the week starting on Monday". The page's example table shows 2017-01-01 (Sun) in week 52 and 2017-01-02 (Mon) starting week 1. [doc] — [Snowflake date & time functions](https://docs.snowflake.com/en/sql-reference/functions-date-time)

### Inferences
**Can the gold SQL produce the files? Not the weekly value.**
- 2017-01-01 is a Sunday [calc], so BigQuery's `EXTRACT(WEEK)` week 1 starts on Jan 1. Each week number then covers exactly one Sunday-to-Saturday block, the same buckets as `DATE_TRUNC(…, WEEK)`. The peak day, Tue 2017-02-14, falls in EXTRACT(WEEK) = 7, covering Feb 12–18 [calc]. The gold SQL's weekly maximum is therefore the Sunday-week figure **35,854.64**, the value lanes k2 and k4 got. This is inferred from identical bucketing; I did not run the gold SQL.
- All three files hold **36,474.27** (or 0.036474 in millions), the Mon Feb 13 – Sun Feb 19 week. The gap of 619.63 equals revenue on Sun Feb 19 minus revenue on Sun Feb 12 [calc]. gold_c's 36474.269938 matches lane k3's Monday-week figure to six decimals.
- Likely origin: the files were produced by a Snowflake port of this SQL, where `EXTRACT(WEEK)` follows the default ISO-like, Monday-start semantics. Three pieces of evidence support this. (1) The files are byte-identical with Spider2-snow's. (2) gold_c's header is uppercase `MAX_REVENUE`, while the BigQuery SQL aliases it `max_revenue`. (3) gold_c's fixed-scale decimals (21148.429980, 99301.439750) differ from BigQuery's float output in our traces (21148.42998, 99301.43974999996). This is a strong inference but not proven. The Snowflake doc ties week behaviour to the `WEEK` date part; that `EXTRACT(week)` uses the same rule is itself an inference from the doc.

**Verdict: (a) gold SQL contradicts gold files (weekly value). High confidence.**
- **(c)**: the question does not say when a week starts; Sunday (BigQuery default, US) and Monday (ISO, Snowflake default) are both common. "In millions" is also unclear. productRevenue is in micros (×10^6), so dividing by 10^6 gives dollars and millions needs 10^12. gold_a labels dollar values "_MILLIONS"; gold_c and the gold SQL are in dollars; only gold_b is in true millions.
- **(d)**: gold_b's `condition_cols` [1,2,3] select total, daily and weekly. They skip the monthly figure, which was asked for, and require a total-revenue column, which was not explicitly asked for. That looks like an off-by-one (perhaps [2,3,4] was intended), but this is an inference. With an absolute tolerance of 0.01 on values of 0.02–0.58, gold_b accepts a ±$10,000 band. The Sunday-week figure in millions (0.035855) is within 0.00062 of gold_b's 0.036474 [calc]. So a true-millions answer with Sunday weeks and a total column passes gold_b, while the same answer in dollars fails gold_a and gold_c by 619.63. Which week start "counts" depends on the unit chosen.

**Correct answer and lanes**
- Correct answer: top source **(direct)** (total $581,583.08 = 0.5816 M). Max daily **$21,148.43** (2017-02-14; 0.0211 M). Max weekly **$35,854.64** for Sunday–Saturday weeks, which is what the BigQuery gold SQL specifies, or **$36,474.27** for Monday–Sunday/ISO weeks. Max monthly **$99,301.44** (0.0993 M). Lane k3's text says April 2017, but I did not see the month in a result row. A fair label should accept both week starts, and both dollar and true-million scales, since the gold already accepts both scales.
- Lanes: **k3** (Monday weeks, dollars) is correct and passes now. **k4** (Sunday weeks, dollars) is correct under a label that follows the gold SQL's own week definition, but fails now. **k1** is wrong under every reading: it counts only the first product per hit, giving 7,625.54 / 18,745.02 / 49,725.42. **k2** is wrong under every reading: dividing by 10^9 gives thousands of dollars (21.148 / 35.855 / 99.301), which fits no unit reading.

**Plain-language explanation**
Every candidate and every gold file agrees that "(direct)" is the top source, the best day was Feb 14 2017 ($21,148.43), and the best month was $99,301.44. The only dispute is the best week. The gold SQL groups days with BigQuery's `EXTRACT(WEEK)`, which starts weeks on Sunday and gives $35,854.64. But all three gold files contain $36,474.27, the total for the Monday-to-Sunday week. That is what Snowflake's default week numbering would produce, and the files are shared with the Snowflake version of the task. Our lane k4 computed exactly what the BigQuery gold SQL computes and was marked wrong. Separately, "in millions" is honoured by only one gold file; the others report plain dollars, so both scales pass.

### Gaps
- I did not execute the gold SQL. The 35,854.64 output is inferred from the BigQuery docs plus lanes k2/k4, which used the same Sunday buckets.
- I could not find the Snowflake SQL that produced the files; Spider2-snow's gold SQL folder has 120 files, none for bq002.
- I did not verify the month of the monthly maximum.

---

## 4. bq208 (db new_york_noaa, NOAA GSOD): question, gold, verdict

### Takeaway
The gold is internally consistent and its counts are right. The question allows two readings, and the gold picks one. Six stations in NOAA's station table lie within 20 miles of Chappaqua, but only three have temperature data in 2011–2020. The gold lists only those three, so an answer that also lists the three silent stations with count 0 fails on row count. Verdict **(c)**, medium-high confidence. No gold SQL exists locally to check. One lane (k1) is wrong for an unrelated reason: a `state = 'NY'` filter drops in-radius stations.

### Cited Findings

**Question, doc and scoring**
- Question, verbatim: "Can you provide weather stations within a 20-mile radius of Chappaqua, New York (Latitude: 41.197, Longitude: -73.764), and tell me the number of valid temperature observations they have recorded from 2011 to 2020, excluding any invalid or missing temperature data?" External knowledge: `functions_st_dwithin.md`. [file] — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl)
- Doc: "Returns TRUE if the minimum geodesic distance between two points (two GEOGRAPHY objects) is within the specified distance." "ST_DWITHIN( <geography_expression_1> , <geography_expression_2> , <distance_in_meters> )". The same doc mentions the "Search Optimization Service" and gives an `ST_MAKEPOINT` example. [file] — [functions_st_dwithin.md](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/documents/functions_st_dwithin.md)
- Scoring: `"condition_cols": [[4], [3]], "ignore_order": true`. Only the count column of each file is checked. [file] — [spider2lite_eval.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl)
- There is no `bq208.sql` in Spider2-lite's gold SQL folder (it holds bq002/bq397/ga010 but not bq208), and none in Spider2-snow's. [file] — [gold/sql folder](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/sql)

**Gold files** [file] — [bq208_a.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq208_a.csv), [bq208_b.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq208_b.csv)
- gold_a (3 rows): `STATION_ID,STATION_NAME,LATITUDE,LONGITUDE,NUM_VALID_TEMP_OBS`: 725037-94745 WESTCHESTER COUNTY AIRPORT 41.062,-73.705 **3653**; 725086-54734 DANBURY MUNICIPAL AIRPORT 41.371,-73.483 **3649**; 997186-99999 WESTERN LONG ISLAND SOUND 40.96,-73.58 **1532**.
- gold_b (3 rows): `usaf,wban,name,VALID_TEMP_OBS_2011_2020`, with the same three stations and counts. Both files are byte-identical to Spider2-snow's `sf_bq208_a/b.csv`.

**Our four candidates** [trace]
- **k3** (LEFT JOIN, every station with `ST_DWITHIN(..., 20 * 1609.344)`) returns 6 rows: the three gold stations plus WHITE PLAINS WESTCHESTER CO A (999999-94745; 41.067,-73.708) 0, DANBURY MUNI ARPT (725086-99999; 41.372,-73.482) 0, and BEAR MOUNTAIN WB (999999-14797; 41.317,-74.0) 0. Fails. — [lane_k3 trace, step 17](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/traces/bq208.json)
- **k2** and **k4** (inner joins, `temp != 9999.9`) return the three gold stations with 3653/3649/1532. Both are scored "matches bq208_a.csv". — [lane_k2 trace](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k2/traces/bq208.json); [lane_k4 trace](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/traces/bq208.json)
- **k1** (`WHERE state = 'NY'` + LEFT JOIN) returns Westchester 3653, Bear Mountain 0 and White Plains 0. It drops Danbury Municipal (CT) and Western Long Island Sound, although both are inside the radius and have data. Fails. — [lane_k1 trace, step 23](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k1/traces/bq208.json)
- k4 also computed `SUM(count_temp)`: 87,538 / 87,398 / 34,741 for the three stations. — [lane_k4 trace, step 20](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/traces/bq208.json)

**Function and data documentation**
- BigQuery `ST_DWITHIN(geography_1, geography_2, distance[, use_spheroid])`: "The given `distance` is in meters on the surface of the Earth." "If `use_spheroid` is `FALSE`, the function measures distance on the surface of a perfect sphere" (the default). `ST_GEOGPOINT(longitude, latitude)`: "Some systems present latitude first; take care with argument order." [doc] — [BigQuery geography functions](https://cloud.google.com/bigquery/docs/reference/standard-sql/geography_functions)
- NOAA GSOD: "TEMP - Mean temperature for the day in degrees Fahrenheit to tenths. Missing = 9999.9". The count attribute is the "Number of observations used in calculating mean temperature." [doc] — [GSOD readme](https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt)

### Inferences
- Distances from Chappaqua (haversine, sphere R = 6,371,008.8 m) [calc]: Westchester County Airport 9.82 mi; Danbury Municipal 18.90 mi; Western Long Island Sound 18.97 mi; White Plains (alternate ID) 9.44 mi; Danbury Muni (alternate ID) 18.99 mi; Bear Mountain WB 14.80 mi. All are inside 20 mi = 32,186.88 m, so neither the radius conversion nor the sphere model changes the station set.
- 3653 is exactly the number of days from 2011-01-01 to 2020-12-31 [calc], so Westchester has a valid daily mean every day. The counts are daily records with `temp != 9999.9`.
- Two of the three zero-count rows look like older or alternate IDs for the same airports. White Plains has the same WBAN 94745 as Westchester County Airport and coordinates within 0.005°; Danbury Muni Arpt has the same USAF 725086 as Danbury Municipal and coordinates within 0.001°. Bear Mountain WB looks like a historic Weather Bureau station. In practice this favours the gold's reading. I did not check station begin/end dates.
- **Verdict: (c) the question allows two readings and the gold picks one.** Reading 1 (gold): stations that recorded valid observations in 2011–2020, with their counts. Reading 2 (literal): every station in the radius, with 0 where nothing was recorded. "the number of valid temperature observations they have recorded" fits reading 1 slightly better, and the zero rows are stale duplicates. Still, listing all stations in the radius is a defensible literal answer. Not (a): there is no gold SQL to compare, and the two files agree. Not (b): the counts are right.
- Secondary ambiguity, also (c): "number of valid temperature observations" could mean valid daily records (the gold's 3653/3649/1532) or the hourly observations behind each daily mean, `SUM(count_temp)` (87,538 / 87,398 / 34,741). GSOD's own field text calls those "observations". The gold picks daily records, which I consider the more natural reading, but the other is not unreasonable.
- **Correct answer and lanes:** the three stations with 3,653 / 3,649 / 1,532 valid daily readings. Under reading 2, the same three plus three stations with 0. A corrected label accepting both readings would pass **k2**, **k3** and **k4**. **k1** is wrong under both, because its state filter excludes two in-radius stations with data.

**Plain-language explanation**
Six stations in NOAA's station list sit within 20 miles of Chappaqua, but only three of them have any temperature data for 2011–2020. The other three are old or duplicate records; two are earlier IDs for the same Westchester and Danbury airports. The gold lists only the three stations with data. An answer that also lists the three silent stations with a count of 0 fails, because the scorer compares the whole count column and the column lengths differ. Both readings fit the question's wording; the gold's is arguably more useful, and its counts (3,653 / 3,649 / 1,532 valid daily readings) are correct. So this is a two-readings case, not a wrong gold.

### Gaps
- No gold SQL exists locally for bq208, in Spider2-lite or Spider2-snow, so I cannot check SQL against files.
- I did not check the stations' begin/end dates, which would confirm that the three zero-count IDs were inactive before 2011.

---

## 5. Dataset and function facts relied on (official sources)

### Takeaway
The key facts are documented by Google, Snowflake and NOAA. GA360 rows are sessions with session-level totals; productRevenue is in micros. GA4 `traffic_source` is first-user acquisition, and sessions are counted as user_pseudo_id + ga_session_id. BigQuery WEEK starts on Sunday while Snowflake's default week is ISO-like and starts on Monday. ST_DWITHIN works in meters on a sphere, and GSOD marks missing temperature as 9999.9. One caveat: the live Universal Analytics schema URL now serves the GA4 page, so the GA360 field texts are quoted from Spider2's copy.

### Cited Findings
- GA360 (Universal Analytics) export: rows are sessions. `totals.transactions` is the "Total number of ecommerce transactions within the session". `hits.product.productRevenue` is "expressed as the value passed to Analytics multiplied by 10^6". `visitId` is only unique per user; combine it with fullVisitorId. — [Spider2 copy of the schema](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/documents/google_analytics_sample.ga_sessions.md); original page "[UA] BigQuery Export schema [Legacy]" — [support.google.com/analytics/answer/3437719](https://support.google.com/analytics/answer/3437719)
- GA360 sample dataset: "The sample dataset provides an obfuscated Google Analytics 360 dataset that can be accessed via BigQuery". The data comes from the Google Merchandise Store, covering "1-Aug-2016 to 1-Aug-2017". — [[UA] Google Analytics sample dataset for BigQuery [Legacy]](https://support.google.com/analytics/answer/7586738)
- GA4 export: `traffic_source.*` describes the network, medium and campaign "that first acquired the user", and "The traffic_source values do not change if the user interacts with subsequent campaigns after installation". The schema also has `session_traffic_source_last_click` and `collected_traffic_source` records. — [GA4 BigQuery Export schema](https://support.google.com/analytics/answer/7029846)
- GA4 sessions: "The combination of `user_pseudo_id` and `ga_session_id` will be unique across your dataset for unique sessions … This is the standard method of counting sessions." — [Google Analytics developer blog, Oct 2022](https://developers.google.com/analytics/blog/2022/hll)
- GA4 channel groups: session-scoped vs first-user-scoped dimensions; the Paid Search, Organic Search, Referral and Unassigned rules. — [Default channel group](https://support.google.com/analytics/answer/9756891)
- GA4 demo dataset: covers 2020-11-01 to 2021-01-31; obfuscated, with placeholders `<Other>`, NULL, ''. — [Demo dataset page](https://developers.google.com/analytics/bigquery/web-ecommerce-demo-dataset)
- BigQuery: EXTRACT WEEK is Sunday-start (week 0 before the first Sunday); ISOWEEK is Monday-start; DATE_TRUNC `WEEK` = `WEEK(SUNDAY)`. — [BigQuery date functions](https://cloud.google.com/bigquery/docs/reference/standard-sql/date_functions)
- Snowflake: the default WEEK_START = 0 and WEEK_OF_YEAR_POLICY = 0 give "ISO-like semantics", with weeks starting Monday; 2017-01-01 falls in week 52. — [Snowflake date & time functions](https://docs.snowflake.com/en/sql-reference/functions-date-time)
- BigQuery ST_DWITHIN: distance in meters on the Earth's surface, perfect sphere by default; ST_GEOGPOINT takes (longitude, latitude). — [BigQuery geography functions](https://cloud.google.com/bigquery/docs/reference/standard-sql/geography_functions)
- NOAA GSOD: TEMP missing = 9999.9; the count field is the number of observations used for the daily mean. — [GSOD readme](https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt)

### Inferences
- Spider2's `functions_st_dwithin.md` appears to be Snowflake's ST_DWITHIN page, given its ST_MAKEPOINT example and the Search Optimization Service note. The meter semantics agree with BigQuery's, so this does not affect bq208.
- Because Spider2-lite and Spider2-snow share byte-identical gold files for all four tasks, BigQuery and Snowflake semantics must give the same answers for the shared label to be fair. bq002's week numbering is a case where they don't.

### Gaps
- I could not fetch the live text of the Universal Analytics schema page; it now serves GA4 content, and the archive was not reachable. The GA360 quotes rely on Spider2's copy.

---

## 6. Summary: verdicts, confidence, and which lanes are right under corrected labels

### Takeaway
Two of the four questions (bq397, bq002) have gold SQL that cannot produce the gold files. ga010's label set rewards output shape over correctness. bq208 is a fair two-readings case. Under the scorer, 6 of 16 lane answers pass today. Under labels that accept both defensible readings and require a real session count for ga010, about 10 of 16 would pass, and ga010's only current pass (k1, an event count) would be lost.

### Cited Findings
| id | verdict | confidence | gold SQL vs files | correct answer (short) | lanes passing now | lanes correct under corrected label |
|---|---|---|---|---|---|---|
| bq397 | (a); root cause (c); plus (d) | high | contradicts (SQL gives Direct 16,541, Social→Venezuela; files 6,650–6,652, Social→US) | session level: US tops all, Direct ≈ 6,651 … Social 164; literal: the SQL's output | k3, k4 | k2 (literal), k3, k4 (session); k1 wrong under both |
| ga010 | (d) + (c) | high on channel, medium on count | SQL output = gold_d (channel only); gold_b uses a merged mapping that disagrees with the SQL and the doc | Referral, about 23,082–23,092 sessions | k1 (via gold_d only) | k2, k3; k1 and k4 only on a channel-only label |
| bq002 | (a) + (c) + (d) | high | contradicts on weekly (SQL Sunday weeks 35,854.64; files Monday weeks 36,474.27) | (direct); 21,148.43 / 35,854.64 or 36,474.27 / 99,301.44 USD | k3 | k3, k4; k1 and k2 wrong |
| bq208 | (c) | medium-high | no gold SQL; the two files agree | 3 stations (3,653 / 3,649 / 1,532), or those plus 3 zero rows | k2, k4 | k2, k3, k4; k1 wrong |

Sources: sections 1–4 above; lane scores from [lane_k1](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k1/all.csv), [lane_k2](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k2/all.csv), [lane_k3](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/all.csv), [lane_k4](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/all.csv) all.csv files.

### Inferences
- Status of the earlier hypotheses (from `results/bq17/anatomy/readings_*.json` and `documents/judge_results.md` §11):
  - bq397, hit-level SQL vs session-level CSVs: **confirmed**, now with trace evidence of the SQL method's output.
  - ga010, k1 passes only via gold_d with an event count about 13x sessions: **confirmed** (295,924 / 23,092 = 12.8x). I also found that gold_b folds Paid Search into Organic Search and uses first-user counts.
  - bq002, EXTRACT(WEEK) Sunday-start vs Monday-start CSVs: **confirmed**. The likely mechanism is Snowflake's default ISO-like week (shared files, uppercase header, fixed-scale decimals) rather than ISOWEEK in BigQuery. "In millions" is ambiguous: **confirmed**, and the gold accepts both scales. New finding: gold_b checks total/daily/weekly but not monthly.
  - bq208, hinges on zero-data stations: **confirmed**. Also, k1 fails for an unrelated real error (state filter), and "observations" has a second reading (SUM(count_temp)).
- Counting rule for the new tally: lanes correct under a corrected label = bq397 3, ga010 2, bq002 2, bq208 3, for 10 of 16, versus 6 of 16 now. The ga010 figure depends on whether the corrected label checks the session count.

### Gaps
- None of these conclusions rests on running SQL. The gold-SQL outputs for bq397 and bq002 are inferred from equivalent queries recorded in our traces and from documented function semantics.
- I found no public Spider2 issue or erratum for these four instances. One general web search (2026-11-18) turned up nothing relevant, and I did not search the xlang-ai/Spider2 GitHub issue tracker directly.
