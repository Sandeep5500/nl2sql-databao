# Spider 2.0-Lite BigQuery gold audit: bq045 and bq356 (NOAA GSOD), bq051 (GHCN-Daily + Citibike), bq035 (SF bike share)

How each finding was checked (tags used below):
- **[file]**: read from a local file in this repo.
- **[git]**: read from the local git history of the `Spider2/` submodule (clone of github.com/xlang-ai/Spider2, checked out at 01a4c67c, 2026-01-30). GitHub links are given for reference; I did not browse GitHub.
- **[trace]**: a BigQuery result recorded in our agent's Nov 17 2026 traces (`results/bq17/bigquery_passk_nov2026_17/lane_k*/traces/<id>.json`). I read these traces. I ran **no** query on BigQuery or Snowflake.
- **[computed]**: local Python on the gold CSVs or on trace previews. This includes re-scoring each lane's submitted-query preview with the `compare_pandas_table` logic copied verbatim from the official `evaluate.py`; the script is `/private/tmp/claude-501/-Users-deepikapalagani-Documents-nl2sql-databao/f54a9a7d-52ac-46be-8abb-0cac5a1864b1/scratchpad/rescore_old_new.py`, in a session scratchpad that may be cleaned.
- **[web]**: official documentation fetched on Nov 18 2026.

Everything under "Inferences" is reasoning, not something checked directly.

## Overview: verdict per instance and which lanes are right under a corrected label

### Takeaway
None of the four is a simple "gold is wrong" case. In bq045 the gold SQL contradicts all four gold files, and the files are the better answer to the current question. In bq356 the current gold (6568) is right; the label used before Nov 2025 (6573) was wrong. bq051 has two fair readings, and the gold picks the better-documented one. bq035 is a scoring artifact. All four gold labels, and their scoring settings, were replaced in a single Spider2 commit on 2025-11-02. Under the earlier labels, different lanes would have passed bq045 and bq356.

| id | verdict | confidence | correct answer | lanes scored right (current gold) | lanes right under a corrected label |
|---|---|---|---|---|---|
| bq045 | (a) gold SQL contradicts gold files; the files are right for the current wording | high on (a); medium-high that the files are right | 3 stations: Quillayute Airport, Stampass Pass FLTWO, Darrington 21 NNE | k1, k2 | k1, k2 (no change) |
| bq356 | (e) the current gold_a (6568) is right; the candidates and judge were wrong. History: the pre-Nov-2025 gold (6573) was wrong. gold_b (6570) is unexplained | high for 6568; low on what 6570 is | 6568 | k4 | k4 |
| bq051 | (c) two fair readings of "valid, unflagged"; the gold uses the quality flag only | high that the gold equals the qflag-only computation; medium that it is the intended reading | 38604.51 non-rainy / 36181.38 rainy (gold reading); 38808.61 / 36181.38 (strict reading) | k2 | k2, plus k1 if both readings are accepted |
| bq035 | (d) scoring artifact: two Earth radii, a 0.01 absolute tolerance, and an average column the question does not ask for | high | per-bike sums of station-to-station great-circle distances (either radius) | k2 | k2, k4 |

### Cited Findings
- [file] Lane scores in the Nov 17 run. bq045: k1=1, k2=1 ("matches bq045_a.csv"), k3=0, k4=0. bq356: k4=1 only ("matches bq356_a.csv"). bq051: k2=1 only. bq035: k2=1 only ("matches bq035_a.csv") — [lane_k1/all.csv](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k1/all.csv), [lane_k2/all.csv](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k2/all.csv), [lane_k3/all.csv](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/all.csv), [lane_k4/all.csv](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/all.csv)
- [computed] Re-scoring each lane's full submitted-query preview with the official comparison logic, against the current gold and the pre-2025-11-02 gold:
  - bq045: k1 and k2 pass the current gold and fail the old one; k3 and k4 fail the current gold and pass the old one.
  - bq356: k4 passes the current gold only; k1 passes the old gold only; k2 and k3 pass neither.
  - bq051: only k2 passes the current gold; no lane passes the old gold.
  - bq035 previews are truncated at 50 of 700 rows, so they were not re-scored. See the bq035 section.
  - Sources: [old gold files at 5fa8a517^](https://github.com/xlang-ai/Spider2/commit/5fa8a5179c411c22ff8fd902c9e01c5bc2bf6c47) and the [current gold files](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/).
- [file] The Spider2-Snow copies (sf_bq045_a–d, sf_bq356_a/b, sf_bq051, sf_bq035_a/b) hold the same values, and [spider2snow_eval.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-snow/evaluation_suite/gold/spider2snow_eval.jsonl) has the same condition_cols. sf_bq035_a/b are byte-identical to the Lite files. No Snow gold SQL exists for these four — [spider2-snow exec_result](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-snow/evaluation_suite/gold/exec_result/)

### Inferences
- If both bq051 readings were accepted and bq035 were scored radius-agnostically without the average column, the run would gain two lane-level passes: k1 on bq051 and k4 on bq035. bq045 and bq356 would not change, since the current files are already right.
- Because the 2025-11-02 update flipped which lanes pass bq045 and bq356, any comparison with results scored before that date (for example, published numbers) is not like-for-like on these tasks.

### Gaps
- None of the four has gold SQL that produces the current files: bq356 and bq051 have no gold SQL at all, and bq045's and bq035's SQL do not produce all of their files. Spider2 documents no process for how the 2025-11-02 alternative files were made.

## Gold history and scoring rules shared by all four

### Takeaway
The gold files were rewritten on 2025-11-02, nearly nine months after the questions reached their current wording (2025-02-10; bq035 on 2025-05-21). The update replaced bq045's two-station answer with three stations, bq356's 6573 with 6568 or 6570, and bq051's integer averages with exact ones. For bq035 it added a second radius and changed which columns are checked. The scorer checks only some gold columns per file, with an absolute tolerance of 0.01.

### Cited Findings
- [file] The scorer accepts a prediction if it matches **any** gold file. Within a file, every selected gold column must equal some predicted column. Extra predicted columns are ignored. Numbers are compared with `math.isclose(float(a), float(b), abs_tol=tol)` where `tolerance = 1e-2`. With ignore_order, both vectors are sorted by `str(x)`. NaN becomes 0. — [evaluate.py lines 67–130](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/evaluate.py). Our port uses the same `abs_tol` 1e-2 and applies condition_cols per gold file — [nl2sql/eval.py lines 28–105](/Users/deepikapalagani/Documents/nl2sql-databao/nl2sql-v2/src/nl2sql/eval.py). Its one known difference: it skips a gold file that raises an error, where the official scorer stops; this matters only for bq389, not for these four — [judge_results.md §11 "Scorer notes"](/Users/deepikapalagani/Documents/nl2sql-databao/documents/judge_results.md)
- [file] Current condition_cols: bq045 `[[1], [2], [0], [1]]` (station-name column only, in each of 4 files); bq356 `[]` (all columns); bq051 `[1]` (avg_daily_trips only); bq035 `[[1], [1, 2]]` (file a: total; file b: avg and total; bike_number in neither). All have ignore_order true — [spider2lite_eval.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl)
- [git] Before 2025-11-02 the config was:
  - bq045: `[]`, one single-column file.
  - bq356: `[]` with `"ignore_order": false`.
  - bq051: `[0]`.
  - bq035: `[0, 2]` (bike_number and total_dist_m).
  - Commit [5fa8a517 "update spider2lite eval" (2025-11-02)](https://github.com/xlang-ai/Spider2/commit/5fa8a5179c411c22ff8fd902c9e01c5bc2bf6c47) deleted bq045.csv, bq356.csv and bq035.csv, and added bq045_a–d, bq356_a/b and bq035_a/b. It also rewrote bq051.csv.
- [git] The original gold files (commit [ef559e1c, 2024-12-12](https://github.com/xlang-ai/Spider2/commit/ef559e1c56c8bb13d12ed3d97a5c5481c05690d7); bq035 from [f8be2c66, 2024-11-10](https://github.com/xlang-ai/Spider2/commit/f8be2c664d6ebefc3da0af4d5e495003ef9c377f)):
  - bq045.csv = `name / STAMPASS PASS FLTWO / QUILLAYUTE AIRPORT`
  - bq356.csv = `output / 6573`
  - bq051.csv = `num_trips,rainy / 38669.0,false / 36181.0,true`
  - bq035.csv = `bike_number,avg_dist_m,total_dist_m` at full precision, e.g. `389,1389.6018489787066,3990936.5102668153`
- [git] How the question wording changed:
  - bq045: 2024-12-12 "…had more than 150 rainy days in 2023 but fewer rainy days than in 2022? Define a 'rainy day' as any day where the precipitation recorded is more than 0 millimeters." Then 2025-01-28 ([8208a4d8](https://github.com/xlang-ai/Spider2/commit/8208a4d8091f764f32303b75a05a3594035d2318)) "…greater than 0 millimeters, **excluding stations with an invalid USAF code**. Only include stations with valid precipitation data." Then 2025-02-10 ([07c88177](https://github.com/xlang-ai/Spider2/commit/07c88177632274f26ac7d4bac925646d54ac60d4)): the current text, which removes the USAF clause and adds "not equal to 99.99". The gold SQL was added on 2025-02-27 ([d72b6a2f](https://github.com/xlang-ai/Spider2/commit/d72b6a2f29079cd3f6abb72dc89eff3216cb5394)) and has not changed since.
  - bq051: 2024-12-12 "…Define a 'rainy day' as any day where the precipitation recorded is more than **0.5 millimeters**." Then 2025-01-28 "…rainy (>0.5mm precipitation)… after verifying station data quality (non-null values, no flags) and converting precipitation values to millimeters by dividing raw measurements by 10". Then 2025-02-10: the current text, "exceeds **5** millimeters (obtained by dividing the raw precipitation value by 10)… that has valid, unflagged measurements".
  - bq356: 2024-12-12 "What is the number of weather stations where the valid temperature record days in 2019 reached 90% or more of the maximum number of recorded days, and have had tracking back to 1/1/2000 or before and through at least 6/30/2019 according to the field 'begin' and 'end'?" Then 2025-02-10: the current text.
  - bq035: 2024-11-10 "What is the total distance traveled by each bike in the San Francisco Bikeshare program? Use data from bikeshare trips and stations to calculate this." Then 2025-05-21 ([84b0c220](https://github.com/xlang-ai/Spider2/commit/84b0c220c465c23910a2a5e20dd4d471c0478a87)) added ", measured in meters".

### Inferences
- The pattern fits labels that were patched over time: the questions were reworded to match what the gold SQL did, and later the gold files were redone to accept outputs the maintainers judged correct. The SQL files were never brought in line.
- In the current bq045 files, the trimmed `DARRINGTON 21 NNE` (file b) and the padded `DARRINGTON 21 NNE            ` (files a, c, d) appear side by side. With exact string matching, this looks like files gathered from several different correct queries, not one reference run.

### Gaps
- The commit messages do not say why the labels changed, and there is no changelog for these instances. The motives above are inferred.

## bq045 — Washington stations with more than 150 rainy days in 2023 but fewer than in 2022 (db noaa_data, GSOD)

### Takeaway
Verdict **(a), gold SQL contradicts gold files**, confidence high. The gold SQL drops every station with USAF 999999, so it cannot output Darrington 21 NNE (USAF 999999, WBAN 04223), yet all four current gold files list it. The SQL also returns only a name column. It matches the pre-Nov-2025 two-station gold and the January 2025 wording ("excluding stations with an invalid USAF code"). The current question has no such clause, Darrington is a real station with plausible counts, and the maintainers themselves added it in Nov 2025. So the current files (3 stations) are the better answer; lanes k1 and k2 are right, and k3 and k4 are wrong.

### Cited Findings
- [file] Question: "Which weather stations in Washington State recorded more than 150 rainy days in 2023 but fewer rainy days compared to 2022? Defining a “rainy day” as one having precipitation greater than zero millimeters and not equal to 99.99. Only include stations with valid precipitation data." — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl)
- [file] Key lines of the gold SQL (2023 CTE; the 2022 CTE is the same with gsod2022):
  - The join and filter: `FROM noaa_gsod.stations AS station INNER JOIN noaa_gsod.gsod2023 AS weather ON station.usaf = weather.stn WHERE station.state = 'WA' AND station.usaf != '999999' GROUP BY station_id`, with `station_id = weather.stn` and `ANY_VALUE(station.name) AS name`.
  - The count: rainy days are a correlated `COUNT(*)` with `washington_stations.station_id = weather.stn AND prcp > 0 AND prcp !=99.99`.
  - The output: `SELECT prcp2023.name FROM prcp2023 JOIN prcp2022 on prcp2023.name = prcp2022.name WHERE prcp2023.rainy_days > 150 AND prcp2023.rainy_days < prcp2022.rainy_days`.
  - Source: [gold/sql/bq045.sql](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/sql/bq045.sql)
- [file] The four current gold files each have 3 rows and the same three stations and counts:
  - a: `STATION_ID,STATION_NAME,RAINY_DAYS_2023,RAINY_DAYS_2022` with `727970,QUILLAYUTE AIRPORT,195,212`, `727815,STAMPASS PASS FLTWO,177,198` and `999999,DARRINGTON 21 NNE            ,167,180`.
  - b: `stn,wban,station_name,rainy_2022,rainy_2023` with `999999,04223,DARRINGTON 21 NNE,180,167`.
  - c: `STATION_NAME,STN,wban`, with no counts.
  - d: composite IDs such as `999999-04223`.
  - Only the name column is scored (condition_cols `[[1],[2],[0],[1]]`).
  - Source: [bq045_a.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq045_a.csv) and [b](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq045_b.csv), [c](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq045_c.csv), [d](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq045_d.csv)
- [git] The gold before 2025-11-02 was one column with two rows: `name / STAMPASS PASS FLTWO / QUILLAYUTE AIRPORT`. Darrington was absent — [ef559e1c](https://github.com/xlang-ai/Spider2/commit/ef559e1c56c8bb13d12ed3d97a5c5481c05690d7)
- [web] NOAA's ISD station history lists `999999 04223 DARRINGTON 21 NNE               US   WA       +48.541 -121.446 +0124.1 20030403 20250828`. Its neighbours are `999999 04222 REDDING 12 WNW` and `999999 04236 CORVALLIS 10 SSW`, so many distinct US stations share USAF 999999 — [isd-history.txt](https://www.ncei.noaa.gov/pub/data/noaa/isd-history.txt)
- [trace] In gsod2019, stn `999999` has 74,972 rows, against 365 for the next-largest stn. It spans many WBANs (94079, 94995, 25381, 03063, …, **04223**, …), each with 365 rows, so Darrington reports daily — [lane_k4 bq356 trace, steps 16 and 19](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/traces/bq356.json)
- [trace] Grouping by USAF alone with 999999 included (lane k3's early queries) produced rows such as `999999,456,467,DEXTER B FLORENCE MEM FLD AP,AR`, `999999,456,467,MUSTANG ISLAND A85A,TX` and `999999,456,467,KRYGYZSTAN US MIL BISHKEK MAN,`. That is a merged pseudo-station with more than 365 "rainy days", joined to every USAF-999999 station worldwide. Lane k3's submitted query returned only `727970,195,212,QUILLAYUTE AIRPORT,WA` and `727815,177,198,STAMPASS PASS FLTWO,WA` — [lane_k3 bq045 trace, steps 6 and 23](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/traces/bq045.json)
- [file/trace] What each lane did:
  - k1 and k2 join on `g.stn = s.usaf AND g.wban = s.wban` with no 999999 filter, and return the 3 stations: Quillayute 195/212, Stampass 177/198, Darrington 167/180.
  - k4 adds `g.stn != '999999'`, `usaf != '999999'` and `g.flag_prcp != 'I'`, and returns 2 stations with identical counts for the shared two.
  - k3 groups by stn alone and returns 2 stations.
  - Sources: [packet bq045.md](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/anatomy/packets/bq045.md), lane all.csv files.
- [web] GSOD PRCP is "in inches and hundredths"; "'0' indicates no measurable precipitation (includes a trace)"; "Missing = 99.99". Flag I = "Station did not report any precipitation data for the day and did not report any occurrences of precipitation in its hourly observations" — [GSOD readme (10/28/2020)](https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt)

### Inferences
- **The gold SQL cannot produce any current file.** Two static reasons: it outputs one column (`name`) where every file has 3–5, and `station.usaf != '999999'` removes Darrington, whose USAF is 999999 according to ISD history and gold files b, c and d.
- **The gold SQL would output the pre-Nov-2025 file.** Its expected output is {QUILLAYUTE AIRPORT, STAMPASS PASS FLTWO}. Two lanes returned exactly these two stations with the same counts: k3 keys by USAF alone like the SQL but has no 999999 exclusion, and k4 keys by USAF+WBAN and excludes 999999. The old file has exactly those two names under the header `name`.
- **Why the SQL excludes 999999.** The SQL joins and groups on USAF only. For USAF 999999 its correlated count would then add up every WBAN-only station in the world (as k3's early output shows), so the exclusion repairs a too-coarse key. It is not a rule about data validity. The USAF clause added to the question on 2025-01-28 described the SQL; when the clause was removed on 2025-02-10 the SQL and the old gold were left behind. They were reconciled only in Nov 2025, and only in the files.
- **Darrington belongs in the answer.** It is a real WBAN station in WA (ISD history), and its counts (167 vs 180) are plausible. The current question does not ask to drop stations by ID. "Only include stations with valid precipitation data" is vague; the gold SQL turns it into nothing beyond the 99.99 exclusion, which the rainy-day definition already states. So the 3-station answer is correct for the current wording, and the gold files are not wrong (not verdict (b)).
- **Corrected answer = current gold.** Lanes k1 and k2 are right. k3 (a USAF-only key that only luckily drops the merged 999999 group) and k4 (an unrequested 999999 exclusion) are wrong now; they would have been right under the old label and under the gold SQL.

### Gaps
- It is unknown whether a flag-based "validity" filter would change Darrington's own counts: k4 excluded 999999 before applying `flag_prcp != 'I'`, so no lane tested it. Also, `flag_prcp != 'I'` drops NULL flags in BigQuery.
- That Darrington 21 NNE is a U.S. Climate Reference Network site is only suggested by its "City NN DIR" name and neighbours. I found no USCRN page to cite.
- The queries that produced files a–d are not published.

### Plain-language explanation
The gold SQL keys stations by USAF number alone, so it has to throw away USAF 999999, which NOAA uses for hundreds of stations that only have a WBAN number. That also throws away Darrington 21 NNE, a real Washington station with 167 rainy days in 2023 and 180 in 2022. The SQL therefore returns two station names, and that is what the gold file said until Nov 2025. The question at one point said "excluding stations with an invalid USAF code", but that clause was removed in Feb 2025, and in Nov 2025 the maintainers swapped in four gold files that all include Darrington. The files are now right for the question as worded, and the SQL is a stale leftover. Our lanes k1 and k2, which identify stations by USAF+WBAN, are correct.

## bq356 — GSOD stations with at least 90% valid temperature days in 2019 (db noaa_data)

### Takeaway
Verdict **(e), the current gold is fine and the candidates and judge were wrong**, with two caveats. First, the label used until 2025-11-02 (6573) was itself wrong: it equals the USAF-only join, which merges all WBAN-only stations into one pseudo-station. Second, the second accepted value (6570) cannot be reproduced and has no gold SQL. Counting stations by USAF+WBAN, as NOAA does, gives 6568, which only lane k4 returned.

### Cited Findings
- [file] Question: "Among all NOAA GSOD weather stations that recorded valid daily temperature data (non-missing temp, max, min) in 2019 and whose period of record began on or before January 1, 2000, and continued through at least June 30, 2019, how many of these stations achieved 90% or more of the maximum possible number of valid temperature-record days in 2019?" — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl)
- [file] There is no gold SQL. The gold files each have 1 row: [bq356_a.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq356_a.csv) = `STATION_COUNT / 6568` and [bq356_b.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq356_b.csv) = `num_stations / 6570`. condition_cols `[]`, so the integer must match within 0.01.
- [git] The gold before 2025-11-02 was `output / 6573` — [ef559e1c](https://github.com/xlang-ai/Spider2/commit/ef559e1c56c8bb13d12ed3d97a5c5481c05690d7)
- [trace] Results our agent got on BigQuery, all from [lane_k4 bq356 trace](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/traces/bq356.json) unless noted:
  - **USAF-only join** (`GROUP BY stn` on valid days, `JOIN stations ON stn = usaf`, `COUNT(*)`, at least 329 valid days): **6573** (step 14). The same query reported 7,630 joined rows and `max_days` = **74,869** (step 15).
  - In stations, 1,338 rows have usaf `999999` (step 18), and `(usaf, wban)` is unique (step 21).
  - In gsod2019 there are 12,144 distinct stn but 12,361 distinct (stn, wban) (steps 22–23).
  - **Keyed by (usaf, wban)**, at least 329 days: **6568**. At least 330 days gives 6560 and at least 328 gives 6575 (steps 24, 27).
- [trace/file] What each lane submitted:
  - k1: USAF-only join, keeping 999999 → 6573.
  - k2: USAF-only, with `stn != '999999'` → 6561.
  - k3: `DISTINCT usaf` with `COUNT(DISTINCT date) >= 329` → 6562.
  - k4: (usaf, wban) → 6568, the only lane scored right.
  - Sources: lane all.csv files and [packet bq356.md](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/anatomy/packets/bq356.md)
- [web] ISD history defines "USAF = Air Force station ID", "WBAN = NCDC WBAN number", "BEGIN = Beginning Period Of Record (YYYYMMDD)" and "END = Ending Period Of Record (YYYYMMDD). There may be reporting gaps within the P.O.R." These are the fields behind the question's "period of record" — [isd-history.txt](https://www.ncei.noaa.gov/pub/data/noaa/isd-history.txt)
- [web] NOAA's ISD problem list names several distinct real stations that share USAF 999999 and differ only by WBAN, for example "The Douglas Army Air Field AZ station (WBAN 23001, USAF ID 999999)", "U.S. station (USAF ID 999999) Dalhart Army Air Field TX" and "San Angelo Goodfellow AAB (USAF ID 999999, WBAN ID 23017)". It also calls WBAN 99999 "a missing code for WBAN ID" — [Brief Review of Problems and Issues with ISD](https://www.ncei.noaa.gov/pub/data/noaa/isd-problems.pdf)

### Inferences
- **6573 is an artifact.** The k1 and k2 queries are identical except for `stn != '999999'`, so the 12-station gap (6573 − 6561) is the merged "999999" group (74,869 valid days, far more than 365) counted once per eligible stations row with USAF 999999. k3's 6562 counts that group once. Under a USAF-only reading, the WBAN-only stations therefore add a meaningless 1 to 12 to the count.
- **6568 is the right count.** The documented identifier is USAF+WBAN: stations has one row per pair, many distinct real stations share USAF 999999, and 99999 is NOAA's "missing code" for WBAN, so by the same pattern 999999 is the "no USAF number" filler. Keying by the pair evaluates each WBAN-only station on its own (each has at most 365 days) and gives 6568. That is the correct answer under the literal question, with maximum possible days = 365 (2019 is not a leap year), 90% → at least 329, and begin ≤ 20000101, end ≥ 20190630.
- **6570 is unexplained.** It is not a threshold variant of the (usaf, wban) count (328/329/330 give 6575/6568/6560). Two guesses, neither verified: (i) a per-station "maximum possible" that shortens the year for stations whose END falls in the second half of 2019, which would let a few more qualify; (ii) a run on a different data copy, since the Snow and Lite labels are shared and file a's upper-case header looks like Snowflake output while b's lower case looks like BigQuery. Accepting 6570 only adds a lenient alternative; it does not hurt correct answers.
- **Lanes under a corrected label:** k4 is right. k1 (6573) was right only under the old wrong label. k2 (6561) and k3 (6562) are wrong under any label I can justify: k2 drops real stations without being asked, and k3 merges distinct stations.

### Gaps
- No gold SQL exists, and no stored query in `results/` returns 6570. I searched every stored bq356 trace. The computation behind 6570 is unknown.
- I did not find an NOAA document that states in so many words that "999999 means no USAF ID". The reading rests on ISD history, the ISD problem list and the trace data.

### Plain-language explanation
GSOD identifies a station by the pair (USAF number, WBAN number). Stations that only have a WBAN number all share the filler USAF value 999999. If you count stations by USAF alone, a couple of hundred different stations collapse into one fake station with about 75,000 "days" in 2019, and joining that back to the stations table counts it once per matching row. That is where the old gold value 6573 came from, and our lane k1 reproduced it. Counting by (USAF, WBAN) gives 6568, which is the current gold and lane k4's answer. The second accepted value, 6570, cannot be reproduced from anything we have, but the gold is right and the other lanes are wrong.

## bq051 — average daily Citibike trips on rainy vs non-rainy days in 2016 (db new_york_ghcn)

### Takeaway
Verdict **(c), the question allows two readings and the gold picks one**. The gold numbers equal, to the last digit, the result of keeping GHCN rows whose **quality** flag (qflag) is blank, at the nearest station with any 2016 data (US1NYKN0025, 3.5 km). Also dropping rows with a **measurement** flag (mflag 'T', trace precipitation) is a literal reading of "unflagged". It changes only the non-rainy average (38808.61 vs 38604.51). GHCN's documentation favours the gold: a blank qflag means the value passed all quality checks, 'T' marks a real trace measurement, and the source flag is never blank on real data, so "no flags at all" is impossible. Lane k2 matches the gold, and lane k1 is right under the strict reading. Lanes k3 and k4 are wrong under every reading.

### Cited Findings
- [file] Question: "Calculate the average daily number of Citibike trips in New York City during 2016, categorizing days as rainy if the total precipitation exceeds 5 millimeters (obtained by dividing the raw precipitation value by 10), and non-rainy otherwise. Use data from the nearest GHCN station located within 50 km of (40.7128, -74.0060) that has valid, unflagged measurements, then compare the resulting average Citibike trips on rainy days versus non-rainy days." — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl)
- [file] There is no gold SQL (neither in Lite nor in Snow, at any commit). The gold file has 2 rows: `rain_status,avg_daily_trips / non-rainy,38604.510067 / rainy,36181.380952`. Only the avg column is scored (condition_cols `[1]`) — [bq051.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq051.csv)
- [git] The gold before 2025-11-02 was `num_trips,rainy / 38669.0,false / 36181.0,true`, scored on column 0 — [ef559e1c](https://github.com/xlang-ai/Spider2/commit/ef559e1c56c8bb13d12ed3d97a5c5481c05690d7)
- [trace] Station search (nearest first): USC00305816 at 733 m, USC00309580 at 745 m, US1NYNY0078 at 2,970 m, **US1NYKN0025 at 3,533 m**, …, USW00094728 (Central Park) at 7,977 m. Among the 12 nearest stations only US1NYKN0025 (431 rows, 255 dates) and USW00094728 (6,302 rows, 366 dates) have any 2016 rows — [lane_k2 bq051 trace, steps 4–8](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k2/traces/bq051.json)
- [trace] US1NYKN0025 PRCP rows in 2016, by (mflag, qflag, sflag): (blank, blank, N) **216**; (T, blank, N) **14**; (blank, L, N) **1**. No row has all three flags blank (0 rows). Central Park PRCP: (blank, blank, W) 342 and (T, blank, W) 24. In BigQuery, blank flags are NULL: `mflag = ''` matched nothing, and `IS NULL` worked — [lane_k3 bq051 trace, steps 13–15](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/traces/bq051.json); [lane_k4 bq051 trace, steps 11, 14–16](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/traces/bq051.json)
- [trace] `new_york.citibike_trips` covers 2016-01-01 to **2016-09-30**: 270 days and 10,262,649 trips in 2016 — [lane_k3 step 57](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/traces/bq051.json); [lane_k2 step 14](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k2/traces/bq051.json)
- [trace] **The gold reproduced exactly.** With `qflag IS NULL`, `value/10.0 > 5` and an inner join to daily trips: non-rainy **149 days, 5,752,072 trips, 38604.5100671141**; rainy **21 days, 759,809 trips, 36181.38095238096**. The weather side alone has 31 rainy days (5.1–49.3 mm) and 199 non-rainy days (0.0–4.6 mm) — [lane_k2 steps 15–20](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k2/traces/bq051.json)
- [trace] Adding `mflag IS NULL` gives non-rainy **38808.61** and rainy **36181.38** (lane k1's submission; lane k3 got the same at step 58). Days with trips: rainy 21 and non-rainy 137, plus 10 rainy and 48 non-rainy days that have no trip data. Lane k4's `SAFE_DIVIDE(SUM(trips), COUNT(*))` over a LEFT JOIN gives 28739.35 / 24509.97. Lane k3's final submission was a step-limit fallback `SELECT COUNT(*) … qflag = ''` — [lane_k1 step 21](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k1/traces/bq051.json); [lane_k4 steps 22–24](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/traces/bq051.json); [lane_k3/all.csv](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/all.csv)
- [web] GHCN-Daily readme v3.35:
  - "PRCP = Precipitation (tenths of mm)".
  - MFLAG "T = trace of precipitation, snowfall, or snow depth"; MFLAG "Blank = no measurement information applicable".
  - QFLAG "Blank = did not fail any quality assurance check"; QFLAG "L = failed check on length of multiday period".
  - SFLAG "Blank = No source (i.e., data value missing)"; "N = Community Collaborative Rain, Hail,and Snow (CoCoRaHS)"; "W = WBAN/ASOS Summary of the Day from NCDC's Integrated Surface Data (ISD)".
  - Source: [GHCN-Daily readme](https://www.ncei.noaa.gov/pub/data/ghcn/daily/readme.txt)

### Inferences
- **Which reading the gold uses.** The gold keeps qflag-blank rows only: row-level filtering at the nearest station with any 2016 data. The 14 trace days stay in, as non-rainy days.
- **What the strict reading changes.** Dropping mflag 'T' removes 12 non-rainy days that have trip data (149 → 137) and no rainy days. That is why only the non-rainy average moves. This confirms the earlier hypothesis that the dropped rows are trace days.
- **Why GHCN favours the gold reading.** A blank qflag is GHCN's definition of a value that passed quality control. 'T' is information about a valid measurement (a trace amount), not a defect. A literal "no flags" rule cannot be applied, because every real value carries a source flag (a blank sflag means the value is missing) and no row at US1NYKN0025 has all three flags blank. A careful reader could still take "unflagged" to cover the measurement flag, so this is (c), not (e). A third reading, choosing the nearest station all of whose measurements are unflagged, would skip US1NYKN0025 because of its one qflag 'L' row and pick Central Park. Its numbers were not computed.
- **The old label.** Its rainy value (36181.0) is the current 36181.38 rounded, so it too used a > 5 mm threshold, even though the question then said "0.5 millimeters" (raw > 5 in tenths of mm). Its non-rainy value (38669.0) fits a computation with **no flag filter**, which keeps the one qflag-'L' day as non-rainy, if that day had about 48,278 trips (38669 × 150 − 5,752,072; roughly 48,203–48,352 if the value was rounded). This is a hypothesis; the date and trips of the 'L' day are not in our traces.
- **Coverage.** All readings average only over January–September, because the trips table stops on 2016-09-30. "During 2016" is therefore effectively nine months. Lane k4 wrongly counts the 58 weather days without trip data as zero-trip days.
- **Corrected answer.** Keep the gold (38604.51 / 36181.38), and accept 38808.61 / 36181.38 as the alternative reading. Under that policy k2 and k1 are right. k3 (no answer) and k4 (wrong denominator) are wrong under every reading.

### Gaps
- No gold SQL, so whether the authors meant qflag-only is undocumented. The match is numeric only, but exact (to about 1e-6, with integer day and trip counts).
- The results of the station-level reading (Central Park) and the old label's computation cannot be checked without running BigQuery.

### Plain-language explanation
GHCN rows carry three flags: a quality flag (blank means the value passed QC), a measurement flag ('T' means a trace of rain was recorded), and a source flag (always filled in for real data). The gold numbers come from filtering only the quality flag at station US1NYKN0025, the nearest station with 2016 data. That gives 38,604.51 trips on non-rainy days and 36,181.38 on rainy days, over the 170 days from January to September that have both weather and trip data. A query that also drops rows with a 'T' measurement flag removes 12 trace days, all non-rainy, and gets 38,808.61. That is a fair literal reading of "unflagged", but NOAA's documentation treats trace values as valid measurements. Our lane k2 matches the gold, and k1 would be right if the strict reading were accepted too.

## bq035 — total distance traveled by each bike (db san_francisco)

### Takeaway
Verdict **(d), scoring artifact**, confidence high. The two accepted files hold the same per-bike great-circle totals computed with Earth radii of 6,371,000 m (file a) and 6,371,010 m (file b: the gold SQL's ST_DISTANCE output). That is a constant 1.57-parts-per-million gap, which exceeds the 0.01 m absolute tolerance for all 700 bikes, so an answer must reproduce one radius exactly. File b also scores an `avg_dist_m` column the question never asks for. Before 2025-11-02 the only gold was the ST_DISTANCE output, scored on bike_number and total. So lane k4 (ST_DISTANCE, as in the gold SQL) would have passed then and fails now, while lane k2 (haversine, 6,371,000 m) fails then and passes now.

### Cited Findings
- [file] Question: "What is the total distance traveled by each bike in the San Francisco Bikeshare program, measured in meters? Use data from bikeshare trips and stations to calculate this." — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl)
- [file] Key lines of the gold SQL: `ST_DISTANCE(ST_GEOGPOINT(start_lon, start_lat), ST_GEOGPOINT(end_lon, end_lat)) AS dist_in_m`, with trips LEFT JOINed to stations on `start_station_id` and on `end_station_id`, then `SELECT bike_number, AVG(dist_in_m) AS avg_dist_m, SUM(dist_in_m) AS total_dist_m … GROUP BY bike_number ORDER BY total_dist_m DESC` — [gold/sql/bq035.sql](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/sql/bq035.sql)
- [file] Gold files, 700 rows each:
  - a: header `bike_number,TOTAL_DISTANCE_METERS`, full precision (e.g. `389,3990930.2460539`).
  - b: header `bike_number,avg_dist_m,total_dist_m`, 4 decimals (e.g. `389,1389.6018,3990936.5103`).
  - condition_cols `[[1],[1,2]]`, so file b requires both the average and the total, and bike_number is checked in neither.
  - Source: [bq035_a.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq035_a.csv), [bq035_b.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result/bq035_b.csv)
- [git/computed] The only gold from 2024-11-10 to 2025-11-02 was the gold SQL's full-precision output (`389,1389.6018489787066,3990936.5102668153`), scored on columns `[0, 2]` (bike_number, total). Current file b equals it rounded to 4 decimals (largest difference 0.00005 in both columns) — [f8be2c66](https://github.com/xlang-ai/Spider2/commit/f8be2c664d6ebefc3da0af4d5e495003ef9c377f), [5fa8a517](https://github.com/xlang-ai/Spider2/commit/5fa8a5179c411c22ff8fd902c9e01c5bc2bf6c47)
- [computed] For all 700 bikes, file b's total ÷ file a's total = 1 + 1.5696e-6 (from 1.5683e-6 to 1.5711e-6 because of b's rounding; exactly 1.5696e-6 at full precision). That ratio is 6,371,010/6,371,000, and it implies a radius of 6,371,010.000 m for b if a used 6,371,000 m. The full-precision gaps run from 0.0111 m to 6.2642 m (median 2.7254 m), and **700 of 700** exceed the 0.01 tolerance. 0.01 m is a relative tolerance of 2.5e-9 at the largest total (3,990,930 m) and 1.4e-6 at the smallest (7,078 m).
- [trace/file] Lanes:
  - k2: haversine in atan2 form with R = 6,371,000 and no LIMIT. Bike 389 gives `3990930.246053194`, which matches file a; scored 1.
  - k4: ST_DISTANCE with `ROUND(SUM(...),2)` and no average column. Bike 389 gives `3990936.51` (gold SQL 3990936.5102668), 503 gives `3934898.8` (3934898.8004458) and 524 gives `3926304.95` (3926304.9492989); scored 0.
  - k1 and k3: haversine with R = 6,371,000 but `LIMIT 20` and `LIMIT 10`, so they return 20 and 10 of 700 rows and fail any label.
  - Sources: [lane_k2 bq035 trace](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k2/traces/bq035.json), [lane_k4 bq035 trace](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/traces/bq035.json), lane all.csv files.
- [file] The trips table has no distance column. Its columns are trip_id, duration_sec, start_date, start_station_name, start_station_id, end_date, end_station_name, end_station_id, bike_number, zip_code and subscriber_type; stations has station_id, name, latitude, longitude, dockcount, landmark and installation_date — [bikeshare_trips.json](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/databases/bigquery/san_francisco/bigquery-public-data.san_francisco/bikeshare_trips.json), [bikeshare_stations.json](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/databases/bigquery/san_francisco/bigquery-public-data.san_francisco/bikeshare_stations.json)
- [web] BigQuery ST_DISTANCE: "Returns the shortest distance in meters between two non-empty GEOGRAPHYs"; "If use_spheroid is FALSE, the function measures distance on the surface of a perfect sphere"; "The default value of use_spheroid is FALSE". The page gives no radius. ST_GEOGPOINT takes longitude first — [BigQuery geography functions](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/geography_functions)
- [web] The R `s2` package states "According to Yoder (1995), the radius of the earth is 6371.01 km" and returns `6371010`. The page itself does not say this is the C++ S2 library's constant — [s2_earth_radius_meters](https://r-spatial.github.io/s2/reference/s2_earth_radius_meters.html)
- [web/computed] Snowflake's HAVERSINE example, `SELECT HAVERSINE(40.7127, -74.0059, 34.0500, -118.2500)` = `3936.385096389` km, is reproduced exactly by a haversine with R = 6371.0 km; R = 6371.01 km gives 3936.391274988 — [Snowflake HAVERSINE](https://docs.snowflake.com/en/sql-reference/functions/haversine)
- [file/computed] The Snowflake ST_DISTANCE page bundled with Spider2 gives 1° along the equator as `111.195101177` km, which implies a sphere radius of 6,371,010.000 m — [resource/documents/functions_st_distance.md](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/documents/functions_st_distance.md)

### Inferences
- **Which file the gold SQL makes.** It produces file b (same column names, same values as the original full-precision file). It cannot produce file a: that file has a different column name, no average, and a 6,371,000 m radius that ST_DISTANCE does not use.
- **ST_DISTANCE uses 6,371,010 m.** The exact ratio between the files (file b being the gold SQL's BigQuery output), the Snowflake ST_DISTANCE example, and the R s2 package's default radius all point to BigQuery's spherical ST_DISTANCE using R = 6,371,010 m. File a fits a hand-written haversine or Snowflake's `HAVERSINE(...)*1000` with R = 6,371 km. Its upper-case header suggests a Snowflake run.
- **Both radii are fair.** Neither is more correct for this question. "Distance traveled" can only be approximated by the station-to-station great-circle distance (round trips count 0), and the two radii change totals by 1.6 ppm, far below the error of that proxy. The 0.01 m absolute tolerance turns an arbitrary constant into pass or fail, and requiring an unrequested average in file b is a second artifact. With bike_number unchecked, only the sorted set of totals is compared, so a wrong bike-to-total mapping would also pass. That does not affect our lanes.
- **Corrected label.** Use a relative tolerance (e.g. 1e-5), do not require the average, and require bike_number. Then k2 and k4 are right, and k1 and k3 stay wrong because of their LIMITs. Under the pre-Nov-2025 label k4 would almost certainly have passed: it uses the same function as the gold SQL, returns 700 rows, and its top rows agree within 0.005. Its full output is not stored.

### Gaps
- Google's BigQuery documentation does not state the sphere radius. The 6,371,010 m figure is inferred from the gold data (exact for all 700 bikes) and Snowflake's example. That the C++ S2 library (`S2Earth`) uses 6,371,010 m I saw only in a search-result snippet of a golang/geo issue, which I did not open.
- That file a came from Snowflake is inferred from its header case and radius, not documented.

### Plain-language explanation
The dataset has no trip length, so both gold files approximate each trip as the straight-line distance between its start and end stations and sum these per bike. One file uses BigQuery's ST_DISTANCE, which works on a sphere of radius 6,371,010 m; the other uses the textbook haversine with 6,371,000 m. Every total therefore differs by 1.6 parts per million, between 1 cm and 6 m per bike. The scorer allows only 1 cm of absolute difference, so an answer must use exactly one of the two radii. The ST_DISTANCE file also demands an average-distance column the question never asks for. Our lane k4 used the same ST_DISTANCE call as the gold SQL and is marked wrong. It would have passed before the Nov 2025 update, and lane k2 would have failed then.

## Dataset facts relied on (official documentation)

### Takeaway
NOAA's own files support each fact used above. GSOD and ISD stations are identified by the USAF and WBAN pair, with fillers for a missing ID. In GHCN-Daily a blank quality flag means "passed QC", 'T' is a measurement flag for trace amounts, and the source flag is always present on real data. BigQuery's ST_DISTANCE uses a sphere whose radius Google does not state.

### Cited Findings
- **GSOD/ISD station identity.**
  - ISD history: "USAF = Air Force station ID. May contain a letter in the first position."; "WBAN = NCDC WBAN number"; BEGIN/END = "Period Of Record". Darrington's line is `999999 04223 DARRINGTON 21 NNE … US WA … 20030403 20250828` — [isd-history.txt](https://www.ncei.noaa.gov/pub/data/noaa/isd-history.txt)
  - Several distinct stations carry "USAF ID 999999" with different WBANs, and WBAN 99999 is called "a missing code for WBAN ID" — [ISD problems (NOAA, 2015)](https://www.ncei.noaa.gov/pub/data/noaa/isd-problems.pdf)
  - The GSOD readme describes "STATION - Station number (WMO/DATSAV3 possibly combined w/WBAN number)" — [GSOD readme](https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt)
- **GSOD precipitation.** PRCP is "in inches and hundredths"; "'0' indicates no measurable precipitation (includes a trace)"; "Missing = 99.99". Flag "H = Station reported '0' as the amount for the day … should be considered as incomplete data for the day". Flag "I = Station did not report any precipitation data for the day…" — [GSOD readme](https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt). The BigQuery column descriptions repeat this, adding "Many stations do not report '0' on days with no precipitation--therefore, '99.99' will often appear on these days" — [gsod2023.json](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/databases/bigquery/noaa_data/bigquery-public-data.noaa_gsod/gsod2023.json)
- **GHCN-Daily flags.** PRCP is in tenths of mm. MFLAG T = trace; QFLAG blank = "did not fail any quality assurance check"; QFLAG L = "failed check on length of multiday period"; SFLAG blank = "No source (i.e., data value missing)" — [GHCN-Daily readme v3.35](https://www.ncei.noaa.gov/pub/data/ghcn/daily/readme.txt)
- **Distance.** ST_DISTANCE defaults to a "perfect sphere", and ST_GEOGPOINT takes (longitude, latitude) — [BigQuery geography functions](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/geography_functions). The R s2 package's default radius is 6,371,010 m (Yoder 1995) — [s2_earth_radius_meters](https://r-spatial.github.io/s2/reference/s2_earth_radius_meters.html). Snowflake's HAVERSINE example implies 6,371.0 km — [Snowflake HAVERSINE](https://docs.snowflake.com/en/sql-reference/functions/haversine)

### Inferences
- An agent with only the schema dump would see `stn`/`wban` and `usaf`/`wban` but no statement of the station key. The BigQuery description of `stn` is just "Cloud - GSOD NOAA". The (usaf, wban) convention in bq045 and bq356 is therefore domain knowledge a judge or agent may lack, which fits the earlier "hidden_data_fact" classification of bq356.
- One agent statement in the lane_k2 bq051 trace calls qflag 'L' "superseded". That is wrong: per the readme, 'L' means "failed check on length of multiday period". The conclusion is unaffected.

### Gaps
- No NOAA page I found defines USAF 999999 in so many words. ISD history and the ISD problem list show its use, and the "missing code" wording appears for WBAN 99999.
- I did not fetch Google's BigQuery dataset listing pages for noaa_gsod, ghcn_d or san_francisco. Schema facts come from the Spider2 schema files and the trace results.
