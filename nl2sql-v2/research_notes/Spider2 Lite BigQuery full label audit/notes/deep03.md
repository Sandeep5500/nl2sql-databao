# deep03 audit notes (Nov 19 2026)

Batch: ga005, ga019, ga020, ga021, ga022, ga028, ga030, bq031, bq119, bq181, bq290, bq394. Lane n = trace folder
lane_k(n+1). Pre-rewrite golds and configs were read from the Spider2 submodule at the parent of commit 5fa8a517
(Nov 2 2025); the Snow twins' current files are byte-identical to these Lite files.

Verdicts: gold_right 6 (ga021, ga028, bq031, bq119, bq181, bq394), gold_wrong 3 (ga005, ga022, ga030),
two_readings 1 (ga019), scoring_defect 2 (ga020, bq290), unclear 0. Labels change in ga019, ga020, ga030 and bq290.

## ga005

The question asks for Week 2 retention of weekly new-user cohorts, "with weeks starting on Monday", defined as a
session_start "exactly 2 weeks after their first week". The two files disagree in every cohort (5.75 vs 6.62,
7.78 vs 6.71, ...). Lane 0's intermediate query q14 reproduces file b to six decimals in all 11 cohorts (10/151,
11/164, 11/194, ..., 2/172). That query labels weeks with DATE_SUB(d, INTERVAL EXTRACT(DAYOFWEEK FROM d) - 2 DAY),
which sends Sundays to the following Monday (lane 0 noticed the same flaw in its ga028 run), so file b's cohorts run
Sunday to Saturday, against the question's explicit Monday start; it also counts retention on the single day cohort
Monday + 14. File a uses exactly the pre-rewrite gold's 11 cohort sizes (174, 167, 188, 251, ...) with a single-day-sized
numerator (10/174 where the old file had 36/174); it cannot be reproduced from the traces. The plainest reading (any
session_start in the calendar week two weeks after the cohort week) gives about 17% (lane 2's q10: 27/156, 25/149,
28/161) and is in neither file. No lane is right under any reading: lane 0 ignores the new-user rule (07-09 cohort of
1,226 users), lane 3 has file b's Sunday-start weeks with a different new-user rule, and lanes 1 and 2 check the day
14 days after each user's own first session, which anchors on the first session rather than "their first week".
Verdict gold_wrong (file b), no label change.

Labels: official [] -> strict [], lenient [].

## ga019

With install = each user's first first_open event in Aug-Sep 2018 (2,647 users) and uninstall = first app_remove
through Oct 3, 782 users uninstall within 7 x 24 hours, so 1,865 qualify: 70.45712127%. That is lane 0's q8 value and,
to eight decimals, the pre-rewrite file a; the pre-rewrite file b (70.5705 = 1,868/2,647) is consistent with the gold SQL's
calendar-day test with uninstalls cut at Sep 30. The rewrite replaced both with 74.861368 (header: install time =
USER_FIRST_TOUCH_TIMESTAMP), 74.777266 (= 2,434/3,255), 75.2109 (2,318/3,082) and 71.21. Defining installs by first
touch is defensible, but so is the first_open event the dataset logs for installs, and the gold no longer accepts it.
Lanes 0 and 2 (70.46) take the first_open reading with the 24-hour test; lane 1 (70.34 = 1,862/2,647) uses the gold
SQL's calendar-day test but rightly counts Oct 1-3 uninstalls. Lane 3 (70.00) uses TIMESTAMP_DIFF(..., DAY) > 7, which
truncates and treats 12 users who uninstalled 7-8 days after first open as uninstalling within seven days, a
convention no gold answer used, so I leave it out.

Labels: official [] -> strict [], lenient [0, 1, 2].

## ga020

The question asks only "Which quickplay event type" had the lowest second-week retention. The three files name three
types: level_complete_quickplay (a), level_retry_quickplay with cohort 6 and 0 retained (b), and
level_reset_quickplay with 12.9730 (c); the pre-rewrite gold was level_reset_quickplay. Lane 3 assigns each user to
their first quickplay event type and finds level_reset lowest (23/81 = 0.284; retry 2/6, start 692/1,911, fail
16/36), the type of file c and of the old gold. It fails only because condition_cols [] force file c's rate column,
which the question never asks for, and lane 3's rate comes from a different cohort. I count that as a scoring defect.
Lane 1's similar query also puts level_reset first (23/78) but returns all six types, which does not answer a "which"
question (same treatment as bq328 in deep06). Lane 2 counts users under every type they played and gets level_start
(0.366 vs 0.395 for level_reset); lane 0 submitted a session count. Files a and b cannot be reproduced; lane 3's
6-user retry cohort matches file b's size but has 2 retained users, not 0.

Labels: official [] -> strict [3], lenient [3].

## ga021

Both files agree: users with a session_start in Jul 2-16, grouped by the type of their first quickplay event in that
period (1,594 / 49 / 45 / 30 / 28 / 7), with 603 / 30 / 10 / 14 / 9 / 3 retained; the scorer checks type, cohort size
and retained count. That grouping fits "their initial quickplay event, calculated separately for each quickplay event
type". Lane 3 reproduces all six cohort sizes but counts any event 1-14 days later (932 retained for level_start); its
day-14-only variant gives 214, so the gold's 603 sits between, as the document's "week 2 (8-14 days)" window would.
"Retention two weeks after" is not "returned at any time within two weeks". Lanes 0 and 2 use per-type cohorts and a
single day 14 (lane 0 even requires the same event type again); lane 1 takes first quickplay events over the whole
table (cohorts 1,702 / 63 / 59 ...) and counts any event 14+ days later. Gold right; the pre-rewrite gold had used the
gold SQL's per-type cohorts.

Labels: official [] -> strict [], lenient [].

## ga022

Lanes 0 and 2 take each user's first first_open over the whole table, keep those between Sep 1 00:00 and Sep 7 23:59
Shanghai time (358 users), and count returns on Shanghai calendar days 1-7, 8-14 and 15-21: 103, 37, 26, i.e.
0.2877 / 0.1034 / 0.0726, which is file a (file c in percent). Files b and d (28.18 / 10.00 / 6.97) are 93, 33 and 23
out of 330. 330 is the cohort obtained when only tables from 20180901 are read (lane 3's cohort, and the pre-rewrite
gold's 73/27/20 of 330); it misses first opens stored in table 20180831 that fall on Sep 1 in Shanghai (lane 1,
which reads 20180831, gets 357). So files b and d contradict "(timezone in Shanghai)", but no lane matches them.
Lane 1 reads return events only from tables 20180902-20180928 and loses day-1 returns (98 instead of 103, week 1 =
0.2745, more than 0.01 off); lane 3 combines the 330 cohort with 24-hour periods (0.2545 / 0.1 / 0.0606). Verdict
gold_wrong for files b and d; no label change.

Labels: official [0, 2] -> strict [0, 2], lenient [0, 2].

## ga028

All three files agree (622 users in week 0; 133, 94, 100, 94 retained in Monday-based weeks 1-4). Lanes 0 and 1 build
the cohort from each user's first event of any kind (731 users), not the first session start the question names;
lane 3 uses first_open (205) and user-relative 7-day blocks instead of "Monday-based weeks"; lane 2 returned a bare
count. The 622 cannot be reproduced from the traces. One caveat: the pre-rewrite gold counted 147 truly new users
(session date equal to first-touch date), and 622 probably also includes users whose first session in the data (which
starts Jun 12) falls in that week although they first used the app earlier; lane 1 found such a user (first touch
2016-05-28). The "new users" wording leans to the smaller cohort, but no lane computes either version, so no label
changes.

Labels: official [] -> strict [], lenient [].

## ga030

Lane 3 passes through file a (2018-07-02). Its first-session search starts at table 20180702, so everyone active
that week lands in the 07-02 cohort: 1,266 users against 484-764 for the eight cohorts 07-09 to 08-27, with 502
(39.65%) back in Jul 23-29. Restricted to users whose first session start falls in that week, the cohort is far less
loyal: ga028's accepted gold for the same week has 622 such users, 100 and 94 of them active in the weeks of Jul 23
and Jul 30 (16.1% and 15.1%), and the pre-rewrite ga028 gold (147 truly new users) gives 16.3% and 10.2%. That is
below lane 3's own 07-09 figure for the same window (163/764 = 21.3%). Lane 3's final query also uses 21-day offsets
for the first three cohorts but 7-day offsets for all later ones, so it compares 07-02's fourth-week rate with
week-1 rates (09-03: 30.6%). The other files name 07-23 and 08-20, and the pre-rewrite gold for this wording was
07-09; only file a names 07-02. So I treat file a as wrong (existing users counted as a new cohort), and lane 3 leaves
both lists. Files b and c cannot be checked; lanes 0-2 fell back to intermediate queries.

Labels: official [3] -> strict [], lenient [].

## bq031

The question covers "January 1 to March 31, 2019" and wants each day's moving average compared with "the moving
averages for the previous 1 to 8 days", output "starting from January 9". All five files therefore have full
differences on January 9 (temperature lag 8 = -4.0, against the January 1 average). Lanes 0 and 3 compute the same
daily values and moving averages (2.4 / 0.9 / 6.2 and 1.1 / 0.2 / 4.6 on January 9), but they apply WHERE date >=
'2019-01-09' in the same SELECT as LAG. The lags then see no earlier rows, so the scored lag columns are NULL on the
first days (lag 8 for all of January 9-16): a SQL ordering error, not a reading. Lane 1 stops at LIMIT 20. Lane 2
uses station 998009 (named "ROCHESTER"; its daily values equal the pre-rewrite gold's, which came from the gold SQL's
name match) and returns only the last 10 days. The current files use Greater Rochester International (725290). Files c
and d carry slightly different wind data from a, b and e (7.7 vs 7.9 m/s on January 10), which affects no lane.

Labels: official [] -> strict [], lenient [].

## bq119

Summed point-to-point ST_DISTANCE puts Paulette (11,394 km) and Teddy (7,080 km) ahead of Laura (6,698 km); all three
became hurricanes, so Laura is third in either sense of "hurricane". The four files hold Laura's 79 points with the
same cumulative distances (0.0, 139.17, ..., 6,697.65 km) and winds in different layouts. Lanes 0, 2 and 3 reproduce
them (lane 2 rounds to 0.01 km, within tolerance). Lane 1 pairs each point with the next one via LEAD, so its
cumulative column starts at 139.17 and repeats the total at the last point: it reports the distance to the next
point, not the distance travelled so far. Gold right.

Labels: official [0, 2, 3] -> strict [0, 2, 3], lenient [0, 2, 3].

## bq181

"At least 90% of the days in 2022" means at least 329 of 365 days with valid temperature, maximum and minimum. Both
files count about 9,581-9,582 such stations and differ only in the denominator: file a uses 28,252 (33.9126%), file b
uses 26,188 (36.589278% = 9,582/26,188), the stations-table count with USAF not 999999 (lane 0's q3). Both are
defensible readings of "out of all available stations". All four lanes divide each station's valid records by its
own record count, so a station with 9 valid records out of 9 qualifies; they get 12,075 of 12,103 (99.77%). That does
not measure coverage of the year. Gold right.

Labels: official [] -> strict [], lenient [].

## bq290

All four lanes average daily max, min and mean temperature over each country's stations, drop records with any
9999.9, and subtract UK from US per day. Those are file a's quantities: all 93 lane values equal file a's rounded to
one decimal (largest gap 0.0497; 92 of 93 also equal file d's). The question sets no rounding, and GSOD temperatures
are recorded to 0.1 F, so the lanes are right in substance and fail only on the 0.01 absolute tolerance. Other
batches treat rounding as non-substantive, so this is a scoring defect. Files b and c are another
variant (12.67 vs 13.39 for the Oct 1 max difference); the pre-rewrite gold used the gold SQL's extremes across
stations.

Labels: official [] -> strict [0, 1, 2, 3], lenient [0, 1, 2, 3].

## bq394

Both files sum all six pairwise absolute differences of the monthly means. File b keeps only records where all four
temperatures are present (2013-06, 2013-07, 2012-07; the gold SQL and the pre-rewrite gold); file a averages each
variable over its own non-null records (2010-07, 2010-08, 2010-06). Lanes 0 and 1 reproduce file b and lane 2 file a.
Lane 3 adds only the three differences between neighbours in the listed order (|air-wet| + |wet-dew| + |dew-sst| =
6.90), which depends on the listing order and is not the sum of absolute differences between the four temperatures.
The scorer checks only the sum column, which is harmless here. Gold right.

Labels: official [0, 1, 2] -> strict [0, 1, 2], lenient [0, 1, 2].
