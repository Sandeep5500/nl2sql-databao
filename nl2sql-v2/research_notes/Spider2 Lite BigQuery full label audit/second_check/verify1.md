# Verification batch verify1 (second auditor, Nov 19 2026)

Result: 7 confirm, 0 adjust, 2 refute (bq363, ga030). All values below come from local files: packets, gold files
and their git history in the Spider2 submodule (Lite and Snow), lane traces, and a local copy of the scorer
(`nl2sql-v2/src/nl2sql/eval.py`) run with `python3 -I`. One web search on the City's taxi dataset page showed
conflicting "last modified" dates (2024-06-21 vs 2026-03-19, perhaps only a catalog-metadata refresh), so I did not use
it as evidence.

A general finding that matters for three questions: the Nov 2025 Lite gold files for the questions checked here are
byte-identical to Spider2-Snow's `sf_` files, which were updated on 2025-10-29. So they were most likely computed on
Snowflake's copy of the data. For the Chicago taxi table, that copy matches the 2024 BigQuery table: bq022's count
and tile fares agree with the 2024 BigQuery gold.

## bq022 — confirm [0, 1, 2, 3]

- Every gold vintage totals 207,933,411 trips at 0-3600 s: Nov 2024, May 2025 (two runs of the gold SQL) and the four
  Nov 2025 files. Every lane's own count with the same filter is 208,952,405 (traces, q1).
- The lanes run the gold SQL's logic: NTILE(6) over trip_seconds, BETWEEN 0 AND 3600, rounded min/max minutes, and
  AVG(fare). Their tile bounds (0-4, 4-7, 7-9, 9-13, 13-21, 21-60) equal every file's.
- In the scorer mirror, the gold SQL's own old outputs pass the current files (one run passes c and d, the other passes
  all four). So the same logic reproduces the files on the old data, and only the data differs.
- The fare gaps (tile 1 at 7.75 vs 6.85-6.86, tile 5 at 15.17 vs 14.79) are too large for an append of 1M trips. The
  bq363 comparison below (same rounded-minute logic, 2024 gold vs today) shows existing durations changed: +2.2M trips
  at 1-5 min, +2.5M at 6-10 min, and fewer trips at every length from 16 min up. That changes which trips fall in each
  tile, so it explains the fare drift.
- Lane 3 averages with SUM(fare)/COUNT(*), which counts NULL fares as zero. On today's data this moves tile 6 by
  -0.007 and the other tiles by at most 0.003. Simulated on the old data, it passes only via file b, in 1 of 2 runs.
  That is borderline, but the lane is right in substance, so I kept it.
- Correction to the first auditor's evidence: the bq363 gold vintages do not disagree because of drift (see bq363).
  That point is not needed here.

## bq076 — confirm [0, 1, 2, 3]

- All four final results are one column, one row: 1106. The lanes' intermediate queries show December 2016 = 1106 as
  the highest month.
- All three files are month + count, and condition_cols [] require both. In the scorer mirror, a one-column 1106 fails
  every file; adding the month passes file a.
- The question asks "What is the highest number…". The pre-rewrite gold was the single column 1106. This is a scoring
  defect, high confidence.

## bq362 — confirm [0, 2, 3]

- The trace counts match the first auditor's. Flash Cab's Feb/Mar 2018 counts today (206,474 / 262,198) equal file a
  exactly, so the lanes' COUNT(*)-per-company-month bucketing is the files'. Taxi Affiliation Services' Sep/Oct counts
  went from 239,207 / 284,472 (file a) to 701,515 / 834,790. Chicago Carriage went from 158,965 / 201,480 to 159,621 /
  202,330. Star North's March rise is now 62,340, above file a's third place (42,515).
- The 2024 gold (file b, unchanged since Nov 2024) came from the gold SQL, which keeps blank companies, and it lists
  the same three companies. So on the old data, the lanes' filter on blank companies changes nothing, and lanes 0/2/3
  would produce file b's set.
- The total trip count rose by only about 1M across all years (bq022), so the Taxi Affiliation Services gain is mostly
  trips re-attributed to that company, not added. Either way, existing 2018 rows changed.
- Lane 1 returns Taxi Affiliation Services three times (three company-months): wrong under any reading.

## bq363 — refute (official [] stands); lenient_ok for lanes 0 and 1

- Lanes 0 and 1 bin minutes by rounding, the same as the gold SQL. Lane 0's trace shows SAFE_CAST(86399/60 AS INT64)
  = 1440. Lane 2 (same cast, raw 60-3000 s filter) has 505,742 fewer trips than lanes 0/1 in group 1, which are the
  trips at 30-59 s. Its groups 2-9 are identical to lanes 0/1.
- The accepted files do not bin by rounding. The 2024 gold (gold SQL, rounded minutes) and file a come from the same
  data: bq022 shows the Snow copy matches the 2024 BigQuery table. Yet file a minus the 2024 gold is +1,506,020 trips
  in group 1, then -569k, -770k, -311k, -125k, -100k, -65k, -48k, -36k, -27k, and -544k in total.
- That is exactly what truncated minutes (60-3059 s) produce compared with rounded minutes (30-3029 s): each group
  shifts 30 s later. Solving the chain with about 614k trips at 30-59 s gives a smooth, falling density of off-minute
  trips: 20k/s, 71k/s, 52k/s, 26k/s, … 3.2k/s, 2.3k/s at 3030-3059 s.
- File c's group-10 trim (2,078,931 - 1,939,369 = 139,562 trips over 3001-3059 s) is 2,365/s, which matches that
  chain. Under rounding, the trim would cover 3001-3029 s, where today's table has only 60,577 trips.
- All ten average fares are 0.04-0.25 higher in file a, largest where fare rises fastest with duration. A 30 s upward
  shift predicts exactly that.
- In the scorer mirror, the gold SQL's own old output fails all three files on both scored columns. So lanes 0/1
  would fail even without drift: the strict change rests on drift alone, and drift does not explain the mismatch.
- Rounded minutes is a fair reading: the gold SQL uses it, and the 2024-25 question text said "rounded trip duration
  in minutes". Lanes 0/1 are exactly right under it on today's table. Lenient only.
- Lane 3 (equal-count trip groups) breaks "similar number of distinct minute values". Lane 2 is not my call (it is not
  in the first auditor's strict list).

## bq009 — confirm [0, 1, 2]

- Lanes 0, 1 and 2 show identical monthly totals for (direct) in 2017 (revenue / 1e6): 96,134.16, 98,118.79,
  94,102.63, 99,197.44, 96,132.33, 97,231.62, 126,887.80 and 8,872.04 (Aug 1 only). Max minus min is 118,015.76
  (32,785.17 over full months).
- No pair of months differs by 4,659.15. The closest are 5,094.81 (Apr - Mar), which is also the Jan-Jun span, and
  4,016.16. The bq002 traces (lanes 1-3) give (direct)'s Jan-Jun product revenue as 94,395.63 to 99,301.44, a span of
  4,905.81.
- The pre-rewrite gold is 118,015.76 in both Lite (Dec 2024) and Snow (Dec 2024), the gold SQL's output.
- Both files (identical to Snow's) say 4,659.15, which does not follow from the documented "Total transaction revenue"
  field. Gold wrong, medium confidence.
- Final results: lanes 0 and 2 return (direct), 118,015.76; lane 1 returns the same plus max/min; lane 3 returns 118.02
  (divided by 1e9), which is neither dollars nor true millions.

## bq275 — confirm [0, 1, 2, 3]

- The pre-rewrite gold (Nov 2024) has 230 distinct visitors.
- The four lanes' final queries each return 230 rows. All visible rows (50, 50, 12, 12) are in that set (checked as
  integers).
- Current files: a 33 rows (17 in the 230), b 23 (22), c 37 (36), d 8 (8). b is a subset of c; d overlaps none of a,
  b, c. 4950411203281265700 is in a, b and c but not in the 230.
- The question states no time window, so these mutually inconsistent fragments contradict it. With condition_cols []
  and ignore_order, a 230-row answer cannot match any file.
- Lane 1's rule (the earliest transaction session is mobile) implies the gold SQL's rule (a mobile transaction session
  on the first transaction date) and gives the same count, so its set equals the 230. Confirmed, high confidence for
  the gold error. That the lane sets equal the old gold rests on logic, row count and visible rows.

## bq374 — confirm [0, 1, 2, 3]

- Final results: 0.30794 (1,691 / 549,137), 0.31 (ROUND of 1,702-1,710 / 549,137), 0.30757 (1,689 / 549,137) and
  0.31 (ROUND of 0.30871).
- The pre-rewrite gold is 0.30848403950198222, the gold SQL's output. Every lane is within 0.0015 of it.
- Lane 0's q5 counts 326 new users with a purchase outside Aug 2016 - Apr 2017. So even if the purchase must fall
  inside the window (against "at any later time"), at least 1,365 users remain, which is at least 0.249%.
- The files' 0.152247% (about 836 users) and 0.04% (about 220) do not follow from the definition and disagree with
  each other. Gold wrong, medium confidence; all four lanes are right.

## ga020 — confirm [3]

- Pre-rewrite gold: level_reset_quickplay.
- Lane 3's single-row answer is level_reset_quickplay, 81, 23, 0.284. Its q6 ranks first-quickplay-type cohorts:
  reset 23/81, retry 2/6, start 692/1,911, end 26/68, complete 14/36, fail 16/36.
- In the scorer mirror, lane 3 matches file c's type column but not its rate, 12.9730. The question asks only "Which
  quickplay event type", so requiring the rate is a scoring defect like bq076.
- Files a (complete) and b (retry, 0 of 6) cannot be reproduced from the traces. Lane 3's six-user retry cohort keeps
  2 users.
- The other lanes: lane 1 (reset 23/78) returns all six rows, which still fails a type-only check (6 rows vs 1).
  Lane 2 counts users under every type they played and gets level_start (0.366 vs reset 0.395). Lane 0 submitted a
  count of 13,042.

## ga030 — refute (official [3] stands); lenient_ok false

- I reproduced the facts. Lane 3 searches first sessions only from 20180702, so its 07-02 cohort is 1,266 users, 502
  (39.65%) back in Jul 23-29. ga028's files (same data) give 622 users whose first session start is in the week of
  Jul 2, with 100 (16.1%) back in the week of Jul 23 and 94 (15.1%) in the week of Jul 30. ga028's lanes, using the
  first event since Jun 12, give 731 users and 120 (16.4%) back.
- So 07-02 wins in lane 3's data because of users who were active before Jul 2, but that does not prove 07-02 is wrong
  under the literal reading.
- The first auditor compares 16.1% with lane 3's 07-09 rate (163/764 = 21.3%). That cohort also contains returning
  users: 764 against about 600-650 new users per week (later cohorts are 584-704), so about 140 of them. If their
  retention is 40-55%, the 07-09 rate without them is about 14-17%, a tie with 07-02.
- 07-16's rate (102/633 = 16.1%) is still slightly inflated by returning users. From 07-23 on, lane 3 used windows one
  week after the cohort week instead of the fourth week, so no correct rates exist for those cohorts.
- The four gold vintages name four weeks (07-09 in 2024-25; 07-02, 08-20, 07-23 now). The answer clearly depends on
  method details, and whether 07-02 is right under the literal reading needs data nobody saw.
- Verdict: unclear, so no correction. Lane 3's own method is flawed (it searches first sessions only from Jul 2, uses
  Sunday-to-Saturday weeks, and uses wrong windows from 07-23 on). But its answer matches an accepted file that has not
  been shown wrong, so it stays in both strict and lenient. Lanes 0-2 fell back to intermediate queries and are wrong.
