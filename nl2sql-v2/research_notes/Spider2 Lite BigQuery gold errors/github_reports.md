# Spider 2.0-Lite BigQuery gold answers: what the xlang-ai/Spider2 maintainers and users have reported or changed on GitHub (focus: bq045, bq397, bq151, bq308, bq002, bq035, bq051, bq055, bq208, ga010, bq424, bq389, bq356)

Research date: 2026-11-18. Method and coverage, so that "nothing found" means something:
- Downloaded every issue and PR of xlang-ai/Spider2 with the REST API on 2026-11-18: 233 items, #1–#234 (213 issues, 20 PRs). Also downloaded every issue comment, all PR review comments (there are none), and the changed-file list and patch text of all 20 PRs. Then grepped all of it, case-insensitively, for each id in both its Lite form (`bq045`) and its Snow form (`sf_bq045`).
- GitHub Discussions are turned off for this repo (`has_discussions: false` in the repo metadata), so there are no discussions to search.
- Cross-checked with the GitHub search API (three OR queries covering the 13 ids). It returned only #98 and #151, the same two threads the grep found.
- Commit history comes from (a) the local clone at 01a4c67c1e3f6ab9032716b050a927abbb245f65, which has full history (238 commits, not shallow), and (b) the GitHub compare and path-filtered commits APIs for anything after that commit.
- I read gold SQL and CSV files statically. Nothing was run against BigQuery, Snowflake, or any other database.
- No page I tried was inaccessible. The maintainers' "data update log" Google Doc was readable through its public plain-text export.

## Q1. For each instance, is there an issue, PR, discussion or commit about it, what problem was described, and was it fixed?

### Takeaway
Only two GitHub threads mention any of the 13 ids, and neither reports a wrong value. #98 asks why `sf_bq002` has `_a`/`_b` gold files. #151 reports that bq389's `condition_cols` points to columns that do not exist in some of its gold files; it is still open with no maintainer reply. No PR changes the gold of any of the 13. What did change them is two unexplained bulk maintainer commits, on 2025-10-29 (Snow) and 2025-11-02 (Lite). These replaced every gold CSV of all 13 instances, usually with 2–7 accepted variants, and changed the evaluation config of 12 of them. None of the old CSVs survived byte-for-byte. Several gold values changed in substance. The Lite gold SQL files were never updated to match the new CSVs.

### Cited Findings

#### Threads that mention the ids (complete list)
- **#98, "The error of exvaluate"** (zcs159, opened 2025-06-12, still open). The user asks whether a condition in the Snow evaluate.py can be removed, "And why does the exec_result directory contain files like sf_bq002_a.csv and sf_bq002_b.csv with suffixes such as _a or _b?" — [#98](https://github.com/xlang-ai/Spider2/issues/98)
- Maintainer reply on #98 (lfy79001, 2025-06-13): "we have updated to a new evaluate.py script… _a, _b — this is because there are multiple correct answers due to question ambiguity or data version issues." No change to bq002's gold came out of this thread. — [#98 comment](https://github.com/xlang-ai/Spider2/issues/98#issuecomment-2968801552)
- **#151, "Inconsistent number of condition columns's variants"** (pickleerik, opened 2025-11-02, the same day as the Lite bulk update; still open). Quote: "Before the update, the number of condition columns' variants… was always equal to the number of exec_results variants. Now, there are a couple of cases: `sf_bq236` `bq169` and `bq060`, where this is not true. Also there are cases where a condition column has an index not given in the gold dataframe - e.g. 6 where the gold df has 4 columns: e.g. `bq389`." The reporter followed up on 2025-11-23 ("Any news on that one?"). No maintainer has replied. — [#151](https://github.com/xlang-ai/Spider2/issues/151); [follow-up](https://github.com/xlang-ai/Spider2/issues/151#issuecomment-3567903761)
- **Mentions that are not reports.** PR #191's diff shows `sf_bq002` and `sf_ga010` only as unchanged context lines in `spider2snow_eval.jsonl` and `spider2-snow.jsonl`. PR #137's diff shows `sf_bq356` only as a context line. PR #211 uses the string `sf_bq051` as a made-up test fixture (`(self.sql / "sf_bq051.sql").write_text("SELECT 1")`). Closed PR #194 ("Sol01", unmerged) has a third-party method's category metadata that lists 13 of these ids, but it says nothing about gold. — [PR #191](https://github.com/xlang-ai/Spider2/pull/191); [PR #137](https://github.com/xlang-ai/Spider2/pull/137); [PR #211](https://github.com/xlang-ai/Spider2/pull/211); [PR #194](https://github.com/xlang-ai/Spider2/pull/194)
- **No thread at all** mentions bq045, bq397, bq151, bq308, bq035, bq051 (other than the fixture above), bq055, bq208, ga010, bq424 or bq356, in either their Lite or Snow form. This comes from the full grep of issue and PR bodies, comments, and PR patches described in the header, plus the search-API cross-check. — [issues list](https://github.com/xlang-ai/Spider2/issues?q=is%3Aissue); [search API](https://api.github.com/search/issues?q=repo:xlang-ai/Spider2+bq045+OR+bq397+OR+bq151+OR+bq308+OR+bq002)

#### Changes that affected all 13 instances
- Commit 575a7a4f ("update 1029", 2025-10-29, Snow) touched 2,063 files, 93.8% of them in `spider2-snow/evaluation_suite/gold/exec_result/`. Commit 5fa8a517 ("update spider2lite eval", 2025-11-02, Lite) touched 1,946 files, 99.8% in `spider2-lite/evaluation_suite/gold/exec_result/`. Neither commit message explains the per-instance changes. — [commit 575a7a4f](https://github.com/xlang-ai/Spider2/commit/575a7a4fab3515fc81e806481cd2164d05a26292); [commit 5fa8a517](https://github.com/xlang-ai/Spider2/commit/5fa8a5179c411c22ff8fd902c9e01c5bc2bf6c47)
- At the local commit, the Lite gold CSVs of all 13 instances are byte-identical (same md5) to their Snow counterparts, variant by variant. Snow has no gold SQL file for any of the 13. — [Lite exec_result](https://github.com/xlang-ai/Spider2/tree/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result); [Snow exec_result](https://github.com/xlang-ai/Spider2/tree/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-snow/evaluation_suite/gold/exec_result)
- None of the 13 Lite gold SQL files was ever modified after it was added. bq035.sql and ga010.sql were added 2024-11-13 ("release some gold SQLs"); bq045, bq397, bq151, bq308, bq002, bq424 and bq389 .sql were added 2025-02-27 ("add more gold SQL"). bq051, bq055, bq208 and bq356 have no Lite gold SQL. — [commit d9d28782](https://github.com/xlang-ai/Spider2/commit/d9d287824b95a6048d0d93a3c35590748dd0880b); [commit d72b6a2f](https://github.com/xlang-ai/Spider2/commit/d72b6a2f29079cd3f6abb72dc89eff3216cb5394); [API history of bq045.sql](https://api.github.com/repos/xlang-ai/Spider2/commits?path=spider2-lite/evaluation_suite/gold/sql/bq045.sql)
- The maintainers' public data update log says: "Spider2-lite and Spider2-snow are updated simultaneously. If bq341 is updated, sf_bq341 will be updated by default as well." Its latest entry is 2025-08-06. It has **no entry** for the 2025-10-29 / 2025-11-02 gold replacement. — [data update log](https://docs.google.com/document/d/1a69mxO7m1nMndXp8H_-aggvYDbcbiS3rV9GPXEw-DeM/edit?usp=sharing)

#### Per-instance record
"Old" means the gold before 2025-10-29/11-02. "New" means the gold at the local commit 01a4c67, which is unchanged upstream (see Q2). Every CSV and config change below is from commits 575a7a4f (Snow) and 5fa8a517 (Lite) unless another commit is named. CSV values were read from git; links point to the files at 01a4c67.

- **bq045** (noaa_data: Washington stations with more than 150 rainy days in 2023 and fewer than in 2022).
  - No GitHub thread.
  - Old gold (added 2024-12-12): one column `name`, 2 rows (STAMPASS PASS FLTWO; QUILLAYUTE AIRPORT). — [commit ef559e1c](https://github.com/xlang-ai/Spider2/commit/ef559e1c56c8bb13d12ed3d97a5c5481c05690d7)
  - New gold: 4 variants `_a`–`_d`, each with **3 rows** (adds DARRINGTON 21 NNE, USAF 999999 / WBAN 04223) and 3–5 columns (station id or name, rainy days 2023 = 195/177/167, 2022 = 212/198/180).
  - `condition_cols` went from `[]` to `[[1],[2],[0],[1]]`, so only the station-name column is scored. — [bq045_a.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq045_a.csv); [spider2lite_eval.jsonl](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl)
  - Gold SQL (2025-02-27, never changed) ends `SELECT prcp2023.name … WHERE prcp2023.rainy_days > 150 AND prcp2023.rainy_days < prcp2022.rainy_days`. — [bq045.sql](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/sql/bq045.sql)
  - Question history:
    - 2025-01-28: the question gained "excluding stations with an invalid USAF code. Only include stations with valid precipitation data." — [commit 8208a4d8](https://github.com/xlang-ai/Spider2/commit/8208a4d8091f764f32303b75a05a3594035d2318)
    - 2025-02-10: a rainy day became "greater than zero millimeters and not equal to 99.99", and the invalid-USAF clause was dropped. — [commit 07c88177](https://github.com/xlang-ai/Spider2/commit/07c88177632274f26ac7d4bac925646d54ac60d4)
    - The update log lists bq045 under 2025-01-28 and 2025-02-10, with no detail. — [data update log](https://docs.google.com/document/d/1a69mxO7m1nMndXp8H_-aggvYDbcbiS3rV9GPXEw-DeM/edit?usp=sharing)
- **bq397** (ecommerce rev_transactions: for each channel grouping with transactions from more than one country, the top country and its transaction total).
  - No GitHub thread.
  - Old gold (added 2024-11-08): 6 rows, including `Social,Venezuela,447`, `Referral,United States,28933`, `Direct,United States,16541`. — [commit c62529ce](https://github.com/xlang-ai/Spider2/commit/c62529ceb020dbde672e09be5ce28bf0787fc2bd)
  - New gold: 4 variants, each 6 rows, **all United States**, with much smaller totals (Social 164 in `_a`). The variants disagree with each other by 1–12 transactions: Direct 6650/6651/6652, Organic Search 3773/3785, Referral 12278/12280.
  - `condition_cols` went from `[]` to `[2]`, so only the totals column is scored. — [bq397_a.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq397_a.csv)
  - Gold SQL (2025-02-27, unchanged) selects `channelGrouping, Country, TotalTransaction … WHERE rnk = 1`. — [bq397.sql](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/sql/bq397.sql)
  - The question was rewritten on 2025-01-28 and again on 2025-02-10, ending as "After removing any duplicate records from the rev_transactions dataset…". The update log lists bq397 under both dates. — [commit 8208a4d8](https://github.com/xlang-ai/Spider2/commit/8208a4d8091f764f32303b75a05a3594035d2318); [commit 07c88177](https://github.com/xlang-ai/Spider2/commit/07c88177632274f26ac7d4bac925646d54ac60d4)
- **bq151** (TCGA pancreatic cancer: chi-squared statistic for KRAS vs TP53 mutations).
  - No GitHub thread.
  - Old gold: `output` = 46.52221206.
  - New gold: `_a` (9 columns; 174 patients; counts 90/27/17/40; chi-squared 35.9059), `_b` (6 columns; same counts; 35.9059), and `_c` (10 columns; **155** patients; counts 86/27/14/28; chi-squared **24.4700**).
  - `ignore_order` went from false to true. `condition_cols` stays `[]`, which means every gold column must be matched. — [bq151_c.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq151_c.csv)
  - Gold SQL (2025-02-27, unchanged) returns a single column, `chi_square_statistic`. — [bq151.sql](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/sql/bq151.sql)
- **bq308** (Stack Overflow: questions per day of week and the share answered within one hour).
  - No GitHub thread.
  - Old gold, two variants:
    - `bq308.csv` (2024-11-08) was renamed to `bq308_a.csv` on 2025-05-22, when a second variant `bq308_b.csv` was added: [commit d79b85e9](https://github.com/xlang-ai/Spider2/commit/d79b85e97be4bf68f62ba1e87e77531bdb3719c6).
    - `_a` uses numbered days (1 = 157237 questions, 38.56%). `_b` has quite different numbers (150272 questions, 52.7%).
  - New gold: 4 variants keyed by day name. Their counts match old `_a` (Monday 251182), but the answered-within-1h count for Monday differs across variants (94921 / 94919 / 94921 / 94923). Old `_b`'s values were dropped.
  - `condition_cols` went from `[1,2,3]` to `[[1,2,3],[2,3,4],[1,2,3],[2,3,4]]`.
  - The question asks about **2021**, and variant `_c` has a column named `questions_total_2021`. But the gold SQL (2025-02-27, unchanged) filters `EXTRACT(YEAR FROM a.creation_date) = 2020 AND EXTRACT(YEAR FROM q.creation_date) = 2020`. — [bq308.sql](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/sql/bq308.sql); [bq308_c.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq308_c.csv); [spider2-lite.jsonl](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/spider2-lite.jsonl)
- **bq002** (GA360, first half of 2017: top traffic source by product revenue, and its maximum daily, weekly and monthly revenue "in millions").
  - Only thread: #98, which asks about the `_a`/`_b` files, not about the values. — [#98](https://github.com/xlang-ai/Spider2/issues/98)
  - Old gold:
    - `_a`: one column `max_revenue`, 3 rows (99301.44, **35854.64**, 21148.43).
    - `_b`: the same values in a single row.
  - New gold: 3 variants. Their **weekly maximum is 36474.27** (variants `_a` and `_c`, with the top source `(direct)`). Variant `_b` divides by 1e6 (0.021148 / 0.036474 / 0.099301), so two unit conventions are accepted at once.
  - `condition_cols` went from `[]` to `[[1,2,3],[1,2,3],[0]]`. — [bq002_a.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq002_a.csv); [bq002_b.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq002_b.csv)
  - Gold SQL (2025-02-27, unchanged) ends `SELECT max_revenue FROM max_revenues ORDER BY max_revenue DESC`. — [bq002.sql](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/sql/bq002.sql)
  - Question history:
    - 2025-01-24: "hits" was added. — [commit e0ab4def](https://github.com/xlang-ai/Spider2/commit/e0ab4def60f4dc4d68cdd63b86e1236d7906f7e8)
    - 2025-02-10: fully rewritten. — [commit 07c88177](https://github.com/xlang-ai/Spider2/commit/07c88177632274f26ac7d4bac925646d54ac60d4)
    - The update log lists bq002 under 2025-01-23 and 2025-02-10. — [data update log](https://docs.google.com/document/d/1a69mxO7m1nMndXp8H_-aggvYDbcbiS3rV9GPXEw-DeM/edit?usp=sharing)
- **bq035** (San Francisco bikeshare: total distance per bike in meters).
  - No GitHub thread.
  - Old gold: 700 rows × (`bike_number`, `avg_dist_m`, `total_dist_m`), `condition_cols [0,2]`.
  - New gold:
    - `_b`: the old values rounded to 4 decimals (same 700 bikes; totals identical at 4 decimals).
    - `_a`: (`bike_number`, `TOTAL_DISTANCE_METERS`), with totals about **6 m lower per bike** (bike 389: 3,990,930.25 vs 3,990,936.51).
  - `condition_cols` went to `[[1],[1,2]]`, so variant `_b` now also scores `avg_dist_m`. — [bq035_a.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq035_a.csv); [bq035_b.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq035_b.csv)
  - On 2025-05-21 the question changed from "…program?" to "…program, measured in meters?". The update log says, for 2025-05-21, "update question:bq035". — [commit 84b0c220](https://github.com/xlang-ai/Spider2/commit/84b0c220c465c23910a2a5e20dd4d471c0478a87); [data update log](https://docs.google.com/document/d/1a69mxO7m1nMndXp8H_-aggvYDbcbiS3rV9GPXEw-DeM/edit?usp=sharing)
  - Gold SQL (2024-11-13, unchanged) ends `GROUP BY bike_number ORDER BY total_dist_m DESC`. — [bq035.sql](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/sql/bq035.sql)
- **bq051** (NYC Citibike 2016: average daily trips on rainy vs non-rainy days).
  - No GitHub thread, apart from the PR #211 fixture noted above.
  - Old gold: `num_trips,rainy` = 38669.0 (false) and 36181.0 (true), `condition_cols [0]`.
  - New gold: a single file, still with no alternative variants. `rain_status,avg_daily_trips` = non-rainy **38604.510067**, rainy 36181.380952. `condition_cols` went to `[1]`. — [bq051.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq051.csv)
  - The question was rewritten on 2025-01-28 and 2025-02-10. It now says rainy means total precipitation above 5 mm, obtained by dividing the raw value by 10, at the nearest GHCN station within 50 km. The update log lists bq051 under both dates. — [commit 8208a4d8](https://github.com/xlang-ai/Spider2/commit/8208a4d8091f764f32303b75a05a3594035d2318); [commit 07c88177](https://github.com/xlang-ai/Spider2/commit/07c88177632274f26ac7d4bac925646d54ac60d4)
- **bq055** (Google 2021 hiring vs BLS tech sectors: top three races by percentage difference).
  - No GitHub thread.
  - Old gold:
    - Eval config: on 2025-05-21 `condition_cols` changed from `[]` to `[1]`; the log entry reads "update eval config:bq055". — [commit 84b0c220](https://github.com/xlang-ai/Spider2/commit/84b0c220c465c23910a2a5e20dd4d471c0478a87)
    - On 2025-05-22, `_a` (3 rows: white 0.2325, asian 0.20125, black 0.0195) and `_b` (5 rows, adding hispanic_latinx 0.00125 and a blank native_american) were created. — [commit d79b85e9](https://github.com/xlang-ai/Spider2/commit/d79b85e97be4bf68f62ba1e87e77531bdb3719c6)
  - New gold: 6 variants `_a`–`_f`, all 3 rows (White/Asian/Black), in mixed units and signs:
    - `_a`: percentage points rounded to 1 decimal (−23.3 / 20.1 / 1.9).
    - `_b`, `_c`: unsigned fractions.
    - `_d`, `_e`, `_f`: signed and absolute differences.
  - `condition_cols` went to `[[1,2,3],[1],[1,2,3],[1,2],[1,2],[1,2,3,4]]`, and `ignore_order` from false to true. — [bq055_a.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq055_a.csv)
  - The question was rewritten on 2025-02-10. — [commit 07c88177](https://github.com/xlang-ai/Spider2/commit/07c88177632274f26ac7d4bac925646d54ac60d4)
- **bq208** (weather stations within 20 miles of Chappaqua, NY: number of valid temperature observations, 2011–2020).
  - No GitHub thread.
  - Old gold: `Data_Points` = 3652, 3649, 1530.
  - New gold: `_a` (5 columns: station id, name, latitude, longitude, count) and `_b` (usaf, wban, name, count). Both give counts **3653, 3649, 1532**.
  - `condition_cols` went from `[]` to `[[4],[3]]`, and `ignore_order` to true. — [bq208_a.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq208_a.csv)
  - Question and external-document history:
    - 2025-01-10: the update log says a geospatial external doc was added for bq208.
    - 2025-01-28: the question gained "excluding any invalid or missing temperature data". — [commit 8208a4d8](https://github.com/xlang-ai/Spider2/commit/8208a4d8091f764f32303b75a05a3594035d2318)
    - Snow's external-knowledge field was set to null on 2025-04-01 and restored on 2025-05-29. — [commit 9bf09297](https://github.com/xlang-ai/Spider2/commit/9bf0929749622339b553ca0dc477b64fb8a52b34); [commit 17ff2f38](https://github.com/xlang-ai/Spider2/commit/17ff2f38dbdf9e9b247581cd14422a19d5117685)
- **ga010** (GA4, December 2020: the channel with the fourth-highest number of sessions).
  - No GitHub thread (PR #191 shows `sf_ga010` only as an unchanged context line).
  - Old gold (added 2024-11-08): `output` = Referral.
  - New gold:
    - `_a`: Referral, **23082** sessions.
    - `_b`: 4 rows with Referral = **23092**.
    - `_c`: Referral, 23082, 17.307%, rank 4.
    - `_d`: the channel name only (`CHANNEL_GROUP` = Referral).
  - `condition_cols` stays `[]`; `ignore_order` went from false to true. — [ga010_b.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/ga010_b.csv); [ga010_a.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/ga010_a.csv)
  - Gold SQL (2024-11-13, unchanged) ends `ORDER BY COUNT(DISTINCT CONCAT(user_pseudo_id, session_id)) DESC LIMIT 1 OFFSET 3`. — [ga010.sql](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/sql/ga010.sql)
- **bq424** (World Bank: top 10 countries by total long-term external debt, excluding those without a region).
  - No GitHub thread.
  - Old gold (added 2024-11-08): India 24,207,420,537.1 first, through Kazakhstan 6,440,650,957.8.
  - New gold: `_a`, `_b` and `_c` put China first at 1,103,089,536,703.9 (`_b` labels the year 2020). `_d` puts Brazil first at 9,316,572,339,231.4. So the accepted variants differ from each other by about 8x, and from the old gold by about 45x.
  - `condition_cols` went from `[0]` to `[[2],[3],[1],[1]]`, and `ignore_order` to true. — [bq424_a.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq424_a.csv); [bq424_d.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq424_d.csv)
  - Gold SQL (2025-02-27, unchanged) filters `indicator_code = "DT.AMT.DLXF.CD"` and ends `ORDER BY id.value DESC LIMIT 10`. — [bq424.sql](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/sql/bq424.sql)
- **bq389** (EPA, California 2020: monthly averages of PM10, PM2.5 FRM, PM2.5 non-FRM, VOC, SO2 ×10 and lead ×100).
  - Thread: #151, open and unanswered. Its claim checks out locally:
    - The flat `condition_cols [1,2,3,4,5,6]` was **not updated** when the 7 variants arrived. bq389 is the only one of the 13 whose eval line was left unchanged.
    - Variants `_a`, `_d` and `_e` are wide (12 × 7). `_b` is long (72 × 4). `_c`, `_f` and `_g` are long (72 × 3).
    - [bq389_b.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq389_b.csv); [spider2lite_eval.jsonl](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl)
  - Old gold: 12 × 7, with the 5th column headed `co`. Its values equal the new `_a`'s `VOC_AVG` column (e.g. 4.0472 for January), and the gold SQL reads `voc_daily_summary`. So the old header was a mislabel, not a CO measurement. `_a`, `_d` and `_e` hold identical values (max difference 0.0). — [bq389.sql](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/sql/bq389.sql)
  - The Lite evaluator does two things that matter here:
    - It copies a flat `condition_cols` list to every variant (`multi_condition_cols = [multi_condition_cols for _ in range(len(multi_gold))]`).
    - It then indexes `gold.iloc[:, condition_cols]`. The per-variant loop has no try/except, so an exception on any variant falls through to `except Exception … score = 0`.
    - Variants are tried in sorted order (a, b, c, …). — [evaluate.py L67–81](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/evaluate.py#L67-L81); [L113–116](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/evaluate.py#L113-L116); [L309–315](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/evaluate.py#L309-L315); [L209–221](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/evaluate.py#L209-L221)
- **bq356** (NOAA GSOD: number of stations with at least 90% valid temperature days in 2019).
  - No GitHub thread (PR #137 shows `sf_bq356` only as a context line).
  - Old gold: `output` = **6573**.
  - New gold: `_a` STATION_COUNT = **6568** and `_b` num_stations = **6570**. `ignore_order` went from false to true; `condition_cols` stays `[]`. — [bq356_a.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq356_a.csv); [bq356_b.csv](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/gold/exec_result/bq356_b.csv)
  - On 2025-02-10 the question was rewritten to add the period-of-record constraints ("began on or before January 1, 2000, and continued through at least June 30, 2019") and "non-missing temp, max, min". The update log lists bq356 under 2025-02-10. — [commit 07c88177](https://github.com/xlang-ai/Spider2/commit/07c88177632274f26ac7d4bac925646d54ac60d4)

#### The Snow versions (sf_*)
- Snow question texts went back and forth:
  - 2025-04-01: reverted to the old, shorter wording for sf_bq045, sf_bq397, sf_bq002, sf_bq051, sf_bq055, sf_bq208 and sf_bq356. — [commit 9bf09297](https://github.com/xlang-ai/Spider2/commit/9bf0929749622339b553ca0dc477b64fb8a52b34)
  - 2025-07-14: the longer Lite-style wording was restored in `spider2-snow.jsonl`, and the old file was kept as `spider2-snow-0713.jsonl`. — [commit 9a4e374c](https://github.com/xlang-ai/Spider2/commit/9a4e374c702b16660840c8beb9ad21e8cb2bf157)
- Issue #106 (2025-07-07, open, no maintainer reply) notes: "the questions in the lite version seem much more descriptive, and Snowflake version is more ambiguous. But answers are same for both." — [#106](https://github.com/xlang-ai/Spider2/issues/106)

### Inferences
- These 13 instances show no "reported → fixed" trail on GitHub. Their golds changed silently in the Oct/Nov 2025 bulk update, with no per-instance note in the commit messages, the README, or the data update log.
- **The gold SQL no longer matches the gold CSV.** The 9 Lite gold SQL files were frozen at their 2024-11 or 2025-02 versions, but every CSV was replaced in 2025-11. Each SQL's output columns match the old CSV, not the new ones:
  - bq045: `name`.
  - bq151: one chi-square column.
  - bq002: `max_revenue`.
  - bq035: bike / avg / total.
  - bq397: three columns.
  - For **bq151** the mismatch is certain from the evaluator alone, with no need to run anything. `condition_cols []` requires every gold column to appear in the prediction, so a single-column output cannot match the 6-, 9- and 10-column variants.
  - For bq002 (old weekly value 35854.64 vs new 36474.27), bq424 (old values ~45x smaller), bq356 (6573 vs 6568/6570) and bq208 (3652/1530 vs 3653/1532), the old values that the gold SQL presumably produced now fail at the 1e-2 absolute tolerance. This assumes the SQL output equals the old CSV, which I could not verify without running it.
- **bq308.** The question year (2021) and the gold SQL filter (2020) disagree. Which year the gold counts represent cannot be told without running the query. The new variants reuse old `_a`'s counts.
- **bq424.** Background knowledge, not verified here: in World Bank WDI, DT.AMT.DLXF.CD is "principal repayments on long-term external debt", while long-term external debt *stocks* is DT.DOD.DLXF.CD. If so, the gold SQL answers a different quantity from the new golds. The 1.1e12 values look like 2020 debt stocks, and `_d` looks like a sum over years.
- **bq045.** Background knowledge: in GSOD, USAF 999999 usually marks a station with no valid USAF id. The new third station (999999, DARRINGTON 21 NNE) is the kind of row the Jan-2025 "exclude invalid USAF code" clause would have removed. That clause was deleted on 2025-02-10, which plausibly explains why the gold grew from 2 to 3 stations.
- **bq389 (#151) is a confirmed evaluator/config defect** in both Lite and Snow (same logic and same eval line), still present upstream:
  - A prediction that does not match variant `_a` raises IndexError on `_b` (4 columns, indices up to 6), and the whole instance scores 0.
  - So the long-format variants `_b`, `_c`, `_f` and `_g` can never be matched. Effectively only the wide format (`_a` = `_d` = `_e`) is accepted.
  - Worth checking whether our local `nl2sql/eval.py` copies this abort behaviour or catches errors per variant. That decides whether long-format answers to bq389 are counted wrong in our runs.
- **Accepted variants disagree with each other in value, not just in format.** This happens in bq397 (±1–12 transactions), bq308 (answered counts ±4), bq151 (174 vs 155 patients), bq424 (8x apart), ga010 (23082 vs 23092), bq356 (6568 vs 6570), and bq035 (`_a` totals ~6 m below `_b`). This fits the maintainer's explanation that variants cover "question ambiguity or data version issues" ([#98](https://github.com/xlang-ai/Spider2/issues/98#issuecomment-2968801552)). It also means "matching the gold" for these instances depends on matching one specific implementation's choices.
- **bq035.** Variant `_b` now also scores `avg_dist_m`, which the question never asks for. A prediction that outputs only the total distance computed the `_b` way (the old way) fails `_b` (no avg column) and also fails `_a` (~6 m difference, far above 0.01).

### Gaps
- Why each gold value changed in Oct/Nov 2025: no commit message, README item, update-log entry or issue explains any instance-level change.
- Whether the frozen gold SQL reproduces any current variant: this needs execution on BigQuery, which was out of scope. The statements above about SQL vs CSV come from reading columns and values, except bq151, which is certain from the evaluator.
- Which year the bq308 gold represents, and which World Bank indicator the new bq424 golds used.
- Images in issues (e.g. #97) were not read. None of them concern the 13 instances.

## Q2. Have the gold SQL or CSV files of these instances changed upstream after 01a4c67 (2026-01-30), or in the six months before it?

### Takeaway
After 01a4c67 nothing gold-related changed. Upstream `main` is 3 commits ahead (all on 2026-08-12) and they touch only README.md. In the six months before (2025-07-30 to 2026-01-30), every gold CSV and 12 of 13 eval-config lines for these instances were rewritten by two bulk commits: Snow on 2025-10-29 and Lite on 2025-11-02. No gold SQL for these instances changed in that window, or ever after it was added.

### Cited Findings
- **After 01a4c67.** Comparing 01a4c67 with `main` gives status "ahead", ahead_by 3, behind_by 0. The only file changed is README.md (+2 lines). — [compare 01a4c67...main](https://github.com/xlang-ai/Spider2/compare/01a4c67c1e3f6ab9032716b050a927abbb245f65...main)
- The three newer commits, all by Fangyu Lei on 2026-08-12, are "Update README.md", "Highlight ongoing Spider 2.0-Snow access issues" and "Remove HTML span tags from news section". `main` is the only branch, and the repo's `pushed_at` is 2026-08-12. — [commit 4e74f73](https://github.com/xlang-ai/Spider2/commit/4e74f7351e9f2b1c560bb6faed17c85ca7e9628e); [commit deba6e3](https://github.com/xlang-ai/Spider2/commit/deba6e349a3380828f9fefec41be3ccfd48fea57); [commit cafb867](https://github.com/xlang-ai/Spider2/commit/cafb867313aab4e674652054198f383cf4018943)
- The path-filtered commits API with `since=2026-01-30T05:00:00Z` returns 0 commits for each of these paths: `spider2-lite/evaluation_suite/gold`, `spider2-snow/evaluation_suite/gold`, `spider2-lite/evaluation_suite/evaluate.py`, `spider2-snow/evaluation_suite/evaluate.py`. — [API: Lite gold](https://api.github.com/repos/xlang-ai/Spider2/commits?path=spider2-lite/evaluation_suite/gold&since=2026-01-30T05:00:00Z); [API: Snow gold](https://api.github.com/repos/xlang-ai/Spider2/commits?path=spider2-snow/evaluation_suite/gold&since=2026-01-30T05:00:00Z)
- Latest commit for each sample path:
  - `gold/sql/bq045.sql`: d72b6a2f (2025-02-27), the only commit ever.
  - `gold/exec_result/bq045_a.csv`: 5fa8a517 (2025-11-02).
  - `spider2lite_eval.jsonl`: 5fa8a517.
  - `sf_bq045_a.csv`: 575a7a4f (2025-10-29).
  - [API bq045.sql](https://api.github.com/repos/xlang-ai/Spider2/commits?path=spider2-lite/evaluation_suite/gold/sql/bq045.sql); [API bq045_a.csv](https://api.github.com/repos/xlang-ai/Spider2/commits?path=spider2-lite/evaluation_suite/gold/exec_result/bq045_a.csv); [web history](https://github.com/xlang-ai/Spider2/commits/main/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl)
- **Window commit 575a7a4f** ("update 1029", 2025-10-29, Snow):
  - Gold CSVs of 544 Snow instances changed. Snow gold CSV files went from 622 to 1,544. Instances with more than one accepted variant went from 64 to 440.
  - `condition_cols`/`ignore_order` changed for 405 of 547 eval lines. Some Snow gold SQL files changed too (5.8% of touched files), but none of these 13 instances has a Snow gold SQL.
  - The same commit set the Snow evaluator's tolerance from 1e-2 to **1e-1** and added NULL-to-0 normalization (`if pd.isna(value): return 0`). — [commit 575a7a4f](https://github.com/xlang-ai/Spider2/commit/575a7a4fab3515fc81e806481cd2164d05a26292)
- **Window commit 76b85e5d** ("fix eval tolerance 1e-2", 2025-10-30) changed the Snow evaluate.py line from `tolerance = 1e-1` back to `tolerance = 1e-2`. — [commit 76b85e5d](https://github.com/xlang-ai/Spider2/commit/76b85e5d225fdae2c8f335a8f2eac30ee17d617c)
- **Window commit 5fa8a517** ("update spider2lite eval", 2025-11-02, Lite):
  - Gold CSVs of 554 instance ids changed (bq 180, ga 25, sf_bq 188, sf 18, sf_local 8, sf_ga 1, local 134). Lite gold CSV files went from 641 to 1,544. Instance ids present went from 557 to 547 (stale files removed). Instances with more than one variant went from 71 to 440.
  - 405 of 547 eval lines changed.
  - evaluate.py was rewritten (+413 / −305 lines), adding the same NULL-to-0 normalization while keeping the 1e-2 tolerance.
  - For the 13 instances, the before/after values are listed per instance in Q1. — [commit 5fa8a517](https://github.com/xlang-ai/Spider2/commit/5fa8a5179c411c22ff8fd902c9e01c5bc2bf6c47)
- Other gold commits in the window touch none of the 13: 35f6849f (2025-08-03, "fix bq279 eval"), ab0d1810 (2025-08-05, "fix bq182"), b92f19e7 (2025-08-05, "fix bq363"), 84911f37 (2025-08-06, "fix sf_bq294 eval"). — [commit 35f6849f](https://github.com/xlang-ai/Spider2/commit/35f6849fb38a3bd339f6a12be3fe41532a713838); [commit ab0d1810](https://github.com/xlang-ai/Spider2/commit/ab0d1810bf97b7beec58dacf1b26ed7eb6429f81); [commit b92f19e7](https://github.com/xlang-ai/Spider2/commit/b92f19e7b85ba5e4c02aed42b3a484e25ef49fe5); [commit 84911f37](https://github.com/xlang-ai/Spider2/commit/84911f375c87903c73ed5fe93769b593a14efb42)
- **Just before the window**, for context:
  - 9a4e374c (2025-07-14) re-wrote the Snow question texts. — [commit 9a4e374c](https://github.com/xlang-ai/Spider2/commit/9a4e374c702b16660840c8beb9ad21e8cb2bf157)
  - d79b85e9 (2025-05-22) added the second variants for bq055 and bq308. — [commit d79b85e9](https://github.com/xlang-ai/Spider2/commit/d79b85e97be4bf68f62ba1e87e77531bdb3719c6)
  - 84b0c220 (2025-05-21) changed bq035's question and bq055's `condition_cols`. — [commit 84b0c220](https://github.com/xlang-ai/Spider2/commit/84b0c220c465c23910a2a5e20dd4d471c0478a87)
- Lite tolerance history: absolute 1e-2 in every evaluate.py version checked (2024-12-25, 2025-02-12, 2025-06-13, before and after 5fa8a517). Snow was 1e-2 except during 575a7a4f → 76b85e5d (2025-10-29 to 10-30), when it was 1e-1. — [Lite evaluate.py at 01a4c67](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/spider2-lite/evaluation_suite/evaluate.py#L84-L111)

### Inferences
- The local copy at 01a4c67 is up to date for every gold, eval-config and evaluator file. The only upstream difference is a README news line.
- The Oct/Nov 2025 update is effectively a re-release of the Lite/Snow answer key: 98–100% of instances got new gold CSVs, and multi-variant instances rose roughly 6x.
- Any of our results scored against gold files from before 2025-11-02 are not comparable with results scored against the current files. That covers any older vendored copy, the Sept 2026 baseline only if it used an older checkout (not checked here), and published papers that predate the update.

### Gaps
- Commits are timestamped, but the upstream repo has no tags or release notes. Which gold version a given leaderboard entry or paper used cannot be recovered from GitHub.

## Q3. What do the README, changelog, news sections and maintainers say about gold-answer fixes?

### Takeaway
Official statements are general. A 2025-10-29 README note says the evaluation suite was fixed and leaderboard methods were re-scored, but gives no count. The data update log lists question, eval-config and answer edits by instance up to 2025-08-06, then stops. In issue threads, maintainers repeatedly say multiple gold files exist because of ambiguity or data versions, that the gold *result* (not the gold SQL) is authoritative, and that tolerance is absolute 1e-2.

### Cited Findings
- **README News at 01a4c67, 2025-10-29:** "Major update! 1. We fixed the evaluation-suite issue, so scores are now more accurate and stable. We also refreshed the affected methods on the leaderboard." It gives no number of corrected examples and no description of the multiple-gold change. — [README at 01a4c67](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/README.md)
- **README News, other entries:**
  - 2025-07-13: "We update `spider2-snow.jsonl` to resolve ambiguities, with the previous version renamed to `spider2-snow-0713.jsonl`".
  - 2025-01-10: "Please refer to the data update log to track changes in the evaluation examples. The leaderboard results will also change dynamically accordingly."
  - 2024-12-24: "release all examples and gold answers for self-evaluation. However, only a small amount of gold SQL is available."
  - A commented-out 2025-01-07 note says they "do not recommend using the Spider 2.0 Gold SQL we released for SFT".
  - [README at 01a4c67](https://github.com/xlang-ai/Spider2/blob/01a4c67c1e3f6ab9032716b050a927abbb245f65/README.md)
- **Upstream README after 01a4c67:** the only new item is dated 2026-08-12, about the Snowflake evaluation account being suspended. Nothing about gold. — [compare 01a4c67...main](https://github.com/xlang-ai/Spider2/compare/01a4c67c1e3f6ab9032716b050a927abbb245f65...main)
- **Project site:** it dates the same news item "2024-10-29: Major update! We fixed the evaluation-suite issue…", which conflicts with the README's and the commits' 2025-10-29. It also says: "Since we continually check the accuracy of the evaluation metrics (while the questions remain fixed), the scores may change slightly over time." — [spider2-sql.github.io](https://spider2-sql.github.io/)
- **Data update log** (Google Doc linked from the README):
  - Purpose: "a document for recording changes in Spider 2.0 data, including updates to natural language questions, gold SQL, gold answers, and evaluation scripts."
  - Entries run from 2025-01-06 to 2025-08-06.
  - Large id-only lists appear on 2025-01-28 (~200 ids) and 2025-02-10 (~250 ids), with no description of what changed.
  - The 2025-01-06 entry lists specific eval fixes (e.g. "sf_bq085: condition_cols should be [1, 2] rather than [2, 3]", "sf_local193: Add another CSV file").
  - Most recent entry: "2025-08-06: sf_bq294, fix eval".
  - [data update log](https://docs.google.com/document/d/1a69mxO7m1nMndXp8H_-aggvYDbcbiS3rV9GPXEw-DeM/edit?usp=sharing)
- **Tolerance (#25, 2024-11-26).** Maintainer: "We have updated the `1e-3` in the evaluation scripts to `1e-2`. In the paper experiments, we used `1e-2`, but we forgot to update it in the public repo." — [#25](https://github.com/xlang-ai/Spider2/issues/25#issuecomment-2500016922)
- **Data update tracking and multi-CSV config (#44, 2025-01-07/08).** Maintainer: "We have pushed the updated answers and eval config. Additionally, we have decided to maintain a document… to track data updates!" Later, for multi-CSV cases with the same format: "we use "condition_cols": [0, 1, 2]. The evaluation scripts can then be extended accordingly. ( [0,1,2] -> [[0,1,2],[0,1,2]])". — [#44](https://github.com/xlang-ai/Spider2/issues/44#issuecomment-2574294874); [#44 follow-up](https://github.com/xlang-ai/Spider2/issues/44#issuecomment-2576859652)
- **Why there are multiple gold files (#98, 2025-06-13):** "there are multiple correct answers due to question ambiguity or data version issues." — [#98](https://github.com/xlang-ai/Spider2/issues/98#issuecomment-2968801552)
- **Gold result over gold SQL (#94, 2025-05-21):**
  - "For sf_bq083, please use the gold result as the reference and ignore the gold SQL."
  - "For sf012, sf_bq093, sf_bq193, sf_bq260, and local003, we have updated the gold result."
  - "examples with IDs starting with 'sf' use a dynamically updated database… Please focus more on examples starting with 'sf_'."
  - [#94](https://github.com/xlang-ai/Spider2/issues/94#issuecomment-2897676610)
- **Dynamic databases (#47, 2025-01-21):** "Spider 2.0 includes a small number of dynamically changing databases… We have already updated the answers in the gold folder." — [#47](https://github.com/xlang-ai/Spider2/issues/47#issuecomment-2603521461)
- **Accepting a user's answer (#97, 2025-06-12, sf_bq414):** "found that your answer is correct. We have fixed the evaluation result." — [#97](https://github.com/xlang-ai/Spider2/issues/97#issuecomment-2964740126)
- **Adding an alternative gold (#99, 2025-06-15, sf_bq030):** "this might be due to some loss in the answer data, so we have added additional gold results for bq030." — [#99](https://github.com/xlang-ai/Spider2/issues/99#issuecomment-2973541328)
- **SQLite mismatches (#154, 2025-11-13):** "We will review it as soon as possible. In the meantime, you may use Spider2-snow first." No later maintainer comment. — [#154](https://github.com/xlang-ai/Spider2/issues/154#issuecomment-3525250942)
- **Gold SQL policy:**
  - #23 (2024-11-13): "to ensure fairness in the competition, we won't be releasing all of the gold SQL for now." — [#23](https://github.com/xlang-ai/Spider2/issues/23#issuecomment-2472445726)
  - #2 (2024-09-26): "there may be multiple gold SQL queries that can solve a task." — [#2](https://github.com/xlang-ai/Spider2/issues/2#issuecomment-2376933603)
- **Community measurement in PR #220** (2026-09-17, open, from DAQUV):
  - "Snow and Lite ship the same 1,542 gold results under different ids."
  - 981 primary-vs-alternative gold pairs across 547 questions. "502 of the 981 pairs match in row and column count and still differ in the values, and 183 more report different measures."
  - An opt-in `--relax` comparator collapses 32 pairs (3.3%) "with 0 false passes".
  - The PR says `compare_pandas_table` "already exists in four different versions across five files".
  - [PR #220](https://github.com/xlang-ai/Spider2/pull/220)

### Inferences
- The maintainers' position, pieced together from the threads: gold CSVs are authoritative and gold SQL is only a reference. Ambiguity is handled by adding more accepted CSVs, not by fixing questions or loosening the comparator. The comparator is per-column vector matching with an absolute 1e-2 tolerance, and extra predicted columns are tolerated.
- The public changelog (README plus update log) does not document the largest gold change in the repo's history. For the post-August-2025 period, git history is the only record.
- The 1,542 count in PR #220 vs the 1,544 files I counted is a 2-file difference. It could be counting method (e.g. excluding stale files) or a slight version difference. I did not resolve it.

### Gaps
- No official count of "corrected examples" exists for the 2025-10-29 update. The counts above (about 544–554 instances re-golded, multi-variant instances from about 64–71 up to 440) are my own measurements from git, not maintainer statements.
- I did not check whether the leaderboard records which gold version each entry was scored against. The site text only says scores "may change slightly over time".

## Q4. Other BigQuery/GA gold-error reports showing the same patterns

### Takeaway
There are about 30 BigQuery/GA (or sf_bq Snow-equivalent) gold reports. They fall into three patterns: gold SQL that does not reproduce the gold CSV, ambiguous questions, and evaluator/tolerance problems. Up to early August 2025 the maintainers usually responded within days to two weeks, by editing the question, adding a variant or patching the eval config. The last maintainer reply on a BigQuery/Snow gold issue was #130 on 2025-08-06. Since then, BigQuery/Snow gold reports (#133, #135, #136, #139, #151, #155, #157, #170, #186) have had no maintainer reply, and the community correction PRs (#137, #191, #220) remain unmerged.

### Cited Findings
- **Gold SQL does not reproduce the gold CSV, or the gold SQL is wrong:**
  - #94: sf_bq083/093/193/260/294 (2025-05-16). Partly fixed; for sf_bq083, "ignore the gold SQL". — [#94](https://github.com/xlang-ai/Spider2/issues/94)
  - #99: sf_bq030, recovery rate above 100. An extra gold was added. — [#99](https://github.com/xlang-ai/Spider2/issues/99)
  - #88: bq011, "last 2 days" covers 3 days in the gold SQL. Maintainer: "There was an error in our gold SQL, but… does not affect the execution results". — [#88](https://github.com/xlang-ai/Spider2/issues/88#issuecomment-2897748197)
  - #117 / PR #119: sf_bq291, the gold SQL date range ran 2019-07-01 to 2021-07-31. Fixed through merged PR #119 on 2025-08-03. — [#117](https://github.com/xlang-ai/Spider2/issues/117); [PR #119](https://github.com/xlang-ai/Spider2/pull/119)
  - #129: sf_bq182 threshold 5 vs >100, fixed; sf_bq193 was handled by a question edit. — [#129](https://github.com/xlang-ai/Spider2/issues/129#issuecomment-3153089741)
  - #130: sf_bq294 joined on name rather than id; "already fixed". — [#130](https://github.com/xlang-ai/Spider2/issues/130#issuecomment-3157384675)
  - #136: sf_bq294 age computed against 2024; open. — [#136](https://github.com/xlang-ai/Spider2/issues/136)
  - #139: sf_bq003, double `LATERAL FLATTEN` inflates pageviews; open, no reply. — [#139](https://github.com/xlang-ai/Spider2/issues/139)
  - #170: sf_bq033 / sf_bq422 gold queries do not parse; open. — [#170](https://github.com/xlang-ai/Spider2/issues/170)
  - #133: sf_bq233 wrong db_id, sf_bq250 ST_ENVELOPE vs ST_CONVEXHULL; open. — [#133](https://github.com/xlang-ai/Spider2/issues/133)
  - #135 / PR #137: sf_bq236 uses "past 10 years" relative to today, sf_bq320 count; PR open and unmerged. — [#135](https://github.com/xlang-ai/Spider2/issues/135); [PR #137](https://github.com/xlang-ai/Spider2/pull/137)
  - #86: bq420 gold tables, "There are some errors with BQ420, which we will fix in the future." — [#86](https://github.com/xlang-ai/Spider2/issues/86#issuecomment-2848919887)
- **Ambiguous questions:**
  - #62: bq275, mobile vs tablet; question updated. — [#62](https://github.com/xlang-ai/Spider2/issues/62#issuecomment-2681218945)
  - #63: bq383, "peak measurement"; "updated the eval scripts to ignore this column". — [#63](https://github.com/xlang-ai/Spider2/issues/63#issuecomment-2681220480)
  - #64 / PR #65: ga008 date-filter logic; the question was rewritten, and the user's gold-update PR was closed unmerged. — [#64](https://github.com/xlang-ai/Spider2/issues/64#issuecomment-2687023892); [PR #65](https://github.com/xlang-ai/Spider2/pull/65)
  - #68: sf_bq019; question updated. — [#68](https://github.com/xlang-ai/Spider2/issues/68#issuecomment-2713817772)
  - #103: bq363, NTILE groups; "this ambiguity is indeed difficult to avoid", later "We have already modified bq363" (commit b92f19e7, 2025-08-05). — [#103](https://github.com/xlang-ai/Spider2/issues/103#issuecomment-3153115914)
  - #42: bq011, doc lists a column absent from the data; question updated 2025-04-13. — [#42](https://github.com/xlang-ai/Spider2/issues/42#issuecomment-2799943873)
  - #155: sf_bq014, two valid interpretations; open. — [#155](https://github.com/xlang-ai/Spider2/issues/155)
  - #106: Lite vs Snow wording; open. — [#106](https://github.com/xlang-ai/Spider2/issues/106)
- **Evaluator, tolerance and config:**
  - #25: tolerance 1e-3 → 1e-2. — [#25](https://github.com/xlang-ai/Spider2/issues/25)
  - #35: `ignore_order` / `condition_cols` for bq066, sf_bq350, sf_bq085; fixed. — [#35](https://github.com/xlang-ai/Spider2/issues/35)
  - #44: condition_cols index error in sf_bq085, `csv_files` order reversed relative to `condition_cols`, "%" compared as strings; fixed. — [#44](https://github.com/xlang-ai/Spider2/issues/44)
  - #151: condition_cols count mismatch for sf_bq236 / bq169 / bq060, out-of-range index for bq389; open, no reply. — [#151](https://github.com/xlang-ai/Spider2/issues/151)
  - #157 (2025-11-23): "NULL values incorrectly treated as 0", claiming 161 of 1,544 gold files contain NULLs; open. — [#157](https://github.com/xlang-ai/Spider2/issues/157)
  - #149: what the `_a`/`_b` suffixes mean; open, no reply. — [#149](https://github.com/xlang-ai/Spider2/issues/149)
  - #186 (2026-04-07): same-shape results differing by a few units; asks whether gold_result can change; open. — [#186](https://github.com/xlang-ai/Spider2/issues/186)
- **Community correction PRs (none merged):**
  - #191 "[Spider2-E] spider2-snow: gold corrections and evaluation patches" (2026-05-05, open):
    - Removes 23 Snow instances whose gold is "no longer reproducible": 3 revoked shares and 20 drifted, including sf_bq009, sf_bq275, sf_ga014, sf_ga018, sf_ga021.
    - Adds 5 engine-difference variants (sf_bq111, sf_bq276, sf_bq430, sf_bq458, sf_local344).
    - Replaces sf_bq294's calendar-dependent gold SQL.
    - Patches evaluate.py: empty-vs-empty results match, and `condition_cols` is padded with `[]` "instead of crashing with IndexError".
    - It touches none of the 13 instances.
    - [PR #191](https://github.com/xlang-ai/Spider2/pull/191)
  - #220 `--relax` comparator (open). — [PR #220](https://github.com/xlang-ai/Spider2/pull/220)
  - #211, a read-only consistency audit; closed by its author on 2026-09-14 ("I'm no longer maintaining this contribution"). — [PR #211](https://github.com/xlang-ai/Spider2/pull/211)

### Inferences
- The 13 target instances show the same three patterns, but nobody has filed them:
  - SQL/CSV divergence: frozen gold SQL vs replaced CSVs.
  - Ambiguity handled by adding variants: bq055, bq002 units, bq424.
  - Config/evaluator brittleness: bq389, matching the open #151 and PR #191's IndexError padding.
- Given the maintainers' stated rule ("use the gold result as the reference and ignore the gold SQL", #94), a challenge to these instances on GitHub would probably have to show that a gold CSV is wrong, not just that it differs from the gold SQL.
- PR #191's `condition_cols` padding fixes too-few config entries, but it would not fix bq389's case of too many indices for narrow variants.

### Gaps
- The list above is restricted to BigQuery/GA and their sf_bq Snow equivalents. The many SQLite (local*) gold reports (#154, #158–#169, #114, #122, #216) are out of scope and only noted here.
- I did not search the EmergenceAI/Spider2-E fork, where #191 says per-instance evidence lives, for the 13 ids. The upstreamed PR #191 changes none of their files.
