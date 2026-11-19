# deep04 audit notes (Nov 19 2026)

Batch: bq022, bq076, bq362, bq363, bq287, bq288, bq330, bq432, bq427, bq428, bq461, bq462. Lane n = trace folder
lane_k(n+1). Pre-rewrite golds and configs were read from the Spider2 submodule history (parent of commit 5fa8a517).
No BigQuery was run; facts about today's data come from the lanes' own queries in their traces.

Verdicts: scoring_defect 6 (bq022, bq076, bq362, bq363, bq432, bq461), gold_right 4 (bq288, bq427, bq428, bq462),
two_readings 1 (bq330), unclear 1 (bq287), gold_wrong 0.

A note on the Chicago taxi table (bq022, bq362, bq363). The same SQL logic gives different numbers in each gold vintage
and in today's runs: bq363's Nov-2024 gold, its Nov-2025 files and today's lanes all differ, and bq022's May-2025 and
Nov-2025 files share a trip total that today's table no longer has. The City of Chicago's "Taxi Trips (2013-2023)"
source on data.gov shows a last-modified date of 2026-03-19. I treat a lane that runs the gold's own logic on today's table
as right and the frozen numbers as a scoring defect. These three are marked "Live-table drift" in the issue field, so
they can be counted separately if the drift policy is decided differently.

## bq022

The question asks for six equal-count duration groups over trips of 0-60 minutes, with rounded min/max minutes, trip
count and average fare. All four lanes run the gold SQL's own logic (NTILE(6) over trip_seconds BETWEEN 0 AND 3600,
ROUND of min/max minutes, COUNT, AVG(fare)), and their duration bounds (0-4, 4-7, 7-9, 9-13, 13-21, 21-60) equal every
file. Only average fare is scored, and it moved because the table changed: every file and the May-2025 pre-rewrite gold
(the gold SQL's output) count 207,933,411 trips, while every lane counts 208,952,405. Tile 1's fare is 7.75-7.76 in all
files against 6.85-6.86 now, and tile 5's is 15.16-15.17 against 14.79-14.80; the files differ from each other by at most
0.007. That gap is not a lane error, so I add all four lanes. Confidence is medium because the old snapshot cannot be
inspected. Separately, NTILE splits the 8.8M trips tied at 240 s arbitrarily, so even identical reruns differ by up to
0.012 in tile 1, close to the tolerance.

Labels: official [] -> strict [0, 1, 2, 3], lenient [0, 1, 2, 3].

## bq076

"What is the highest number of motor vehicle theft incidents that occurred in any single month during 2016?" asks for
one number. All four lanes return 1106, the count in every file and the value the gold SQL selects (incidents AS
highest_monthly_thefts). The pre-rewrite gold was exactly that one column with condition_cols [], so the lanes would
have passed. The Nov 2025 rewrite added a month column (12, or 2016-12-01 as a timestamp) to all three files and kept
condition_cols [], so the month is now required and a correct one-number answer cannot pass. Scoring defect, high
confidence; scoring only the count column would fix it.

Labels: official [] -> strict [0, 1, 2, 3], lenient [0, 1, 2, 3].

## bq362

"Which three companies had the largest increase in trip numbers between two consecutive months in 2018?" Lanes 0, 2
and 3 follow the gold SQL's logic: monthly trips per company, LAG, each company's best increase, top three distinct
companies. They get Taxi Affiliation Services (+133,275, Oct), Star North Management LLC (+62,340, Mar) and Flash Cab
(+55,724, Mar). File a shows why this differs from the gold: Flash Cab's Feb/Mar counts (206,474 / 262,198) are identical
today, but Taxi Affiliation Services' Sep/Oct counts were 239,207 / 284,472 in the gold and are 701,515 / 834,790 today.
Chicago Carriage also moved slightly (158,965 / 201,480 to 159,621 / 202,330), and Star North's rise now beats the gold's
third place (42,515). So the files hold the answer for an older version of the table. Lane 1 returns Taxi Affiliation
Services three times (three company-months), which does not answer "which three companies" under any reading. Confidence
is medium: no trace shows whether the 2018 rows were re-attributed or duplicated.

Labels: official [] -> strict [0, 2, 3], lenient [0, 2, 3].

## bq363

The question asks for ten groups over the minute values 1-50, "each group ... a similar number of distinct minute
values", so five minutes per group (01m-05m ... 46m-50m), as in every file. The gold SQL filters ROUND(trip_seconds/60)
between 1 and 50 (30-3029 s). Lanes 0 and 1 use SAFE_CAST(trip_seconds/60 AS INT64), which in BigQuery rounds half away
from zero, and NTILE(10) over the 50 distinct minutes, which gives the same groups and filter. Their counts differ from file a by
-3.5% to +4.8% per group (total 195,892,375 vs 191,354,996), and the Nov-2024 gold (191,899,239) and file b (191,338,344)
differ from file a as well. So the same logic has produced three different answers over time, which is drift, not a
lane error. Lane 2 filters raw durations of 60-3000 s, a fair reading of "from 1-50 minutes" (file c also trims the top
group, 1,939,369 vs 2,078,931 trips), so I add it under lenient only. Lane 3 makes equal-count groups over trips (01m-04m,
04m-05m, ..., 27m-50m), which the question's distinct-minute rule excludes.

Labels: official [] -> strict [0, 1], lenient [0, 1, 2].

## bq287

No lane gives an employment rate. The 2017 ACS ZIP table the question needs is not in Spider2's fda database (only
census_utility, fda_food, fdic_banks, geo_census_blockgroups, geo_us_boundaries), and the harness refused
census_bureau_acs as out of scope. So the official "none right" is certain. The gold itself cannot be checked. "The ZIP
code that has the fewest FDIC-insured bank locations" is not unique: lanes 2/3 count 42 Utah ZIPs with exactly one
location, and lane 0 finds 172 of 299 Utah ZIPs with none. The rewrite also changed the answer from 0.6395 to
0.5742049 (= 325/566, a ZIP with 566 residents aged 16+), and there is no gold SQL. Unclear, with no label change either
way.

Labels: official [] -> strict [], lenient [] (unchanged).

## bq288

All lanes identify North Carolina: its 'Bank%' institutions established 1900-2000 hold 2,772,804,950 in total assets,
against New York's 81,896,096. "The total number of all banking institutions in the state" means every NC institution,
453 (lanes 0, 1, 3), which is file a. Lane 2 answers 23 by re-applying the name and date filters, which "all" rules out.
File b (653) and the pre-rewrite gold (184) are reproduced by no trace, but they accept other numbers rather than reject
a right one, so no lane is affected. Gold right.

Labels: official [0, 1, 3] -> strict [0, 1, 3], lenient [0, 1, 3] (unchanged).

## bq330

The document distributes each ZIP's bank locations to block groups by overlap ratio and ends with "grouping by ZIP code
and finding the maximum number of bank locations per block group". That reads two ways: the maximum over block groups
inside each ZIP, or the ZIP with the highest per-block-group figure. Lane 0's trace computed the variants on today's data.
The within-ZIP maximum ranks 80111 first (33.0, essentially its 33 locations), which is what both current files say. The
gold SQL's sum (then a trivial MAX per ZIP) ranks 80501 first among the 12 ZIPs listed (872.1 vs 80525's 841.0), and it
produced the pre-rewrite gold, 80501. Lane 0's per-block-group average also ranks 80501 first (18.56 vs 80111's 17.29),
and an average is a natural reading of "concentration per block group". So I count lane 0 under lenient. Lane 2 divides
locations by the number of overlapping block groups (81427), and lanes 1 and 3 submitted raw overlap-ratio rows; they
are wrong under any reading.

Labels: official [] -> strict [], lenient [0].

## bq432

This is a data-cleansing question with 183 rows, and its scoring cannot accept any native BigQuery answer. The Nov 2025
rewrite set flat condition_cols [2, 4, 6] (previously []). In every file, that list lands on at least one array column:
outcomes in a, outcomes_array and products_brand_array in b, reactions_array in c and d. All of them are stored as
pretty-printed JSON text, while BigQuery arrays reach the scorer as Python-style lists like ['Other Outcome'], so exact
string comparison always fails. Apart from that format, lane 1 matches file a's scored columns: clean outcome elements,
industry codes (02 parses to 2) and " -- " in the two comma industry names. Lane 0 matches files c/d: date_started,
consumer_age, and reactions with the leading spaces those files keep. No brand name in the 183 rows has a digit-comma-digit
pattern, so the lanes' different numeric-pattern rules give identical output; every lane gives brand lengths 3/2 for
the 8 comma brands, as files a and c do. Lanes 2 and 3 drop consumer_gender, consumer_age and consumer_age_unit, which the
document lists among the food-event fields, so they stay wrong. Side flaws: file d never replaces ", " in brand and industry
names, and file b repeats reaction lists per product. Neither is scored, so both would accept wrong cleansing.

Labels: official [] -> strict [0, 1], lenient [0, 1].

## bq427

File a combines per-shot average adjusted coordinates (dunk 90.5004, 301.2168) with per-game average attempts and makes
(dunk 4.609351, 4.082650). File b has the same coordinates with per-team-game counts. Lane 3's own q5 reproduces file a's
coordinates exactly at shot level with the team_basket side filter, and its per-game counts equal file a to nine digits,
so its shot filter is the gold's. But it submitted averages of per-game coordinate means (dunk 90.716, hook 125.420 vs
124.904). That weights each game equally rather than each shot, which is not the usual meaning of "the average x and y
coordinates" for a shot type. Lanes 0-2 report total counts (jump shot 675,099) instead of averages, and skip the
correct-side filter (jump x 211.34 vs 211.25). Gold right, medium confidence, since some analysts would weight by game.

Labels: official [] -> strict [], lenient [] (unchanged).

## bq428

The question asks for game details "as specified in the data model document". The document defines one row per team
per game, with label (win/loss), the team's seed, market, name, alias, school and opponent_* columns. The gold has 95
such rows for the five markets with the most 15-point second-half scorers: Kentucky 32, Duke 26, Gonzaga 23, Florida
State 8, Memphis 6. Two games between these teams appear once from each side (2010 Gonzaga-Florida State, 2015
Duke-Gonzaga). Lanes 0, 2 and 3 find the same five markets but return the 93 games as single rows with win_*/lose_*
columns and no label. That is a different table from the one the document specifies, not a formatting difference, and no
95-value gold column can match it. Lane 1 picks Memphis, South Florida, Missouri, UNLV and Duke. Gold right.

Labels: official [] -> strict [], lenient [] (unchanged).

## bq461

Lanes 0, 1 and 3 return the same 75 scoring plays with the same descriptions and the same 68-66 final. They differ only
in how they order the five and-ones, where a basket and its "free throw 1 of 1" share a clock time: Wildcats at 9:34,
2:22 and 4:08 of the second half, and Fighting Irish at 5:05 and 00:25. Each and-one's order changes one running-score
value. The gold files take both orders: a/b/c/h put the basket first (Wildcats running scores 16, 24, 60), d/e/f the
free throw first (15, 23, 59), and g mixes them (16, 23, 59). Lane 1 breaks ties by event_id, a random UUID, and happened
to match file d. Lane 0 (15, 24, 60) and lane 3 (16, 24, 59) are each one value off file a, and both order only by
elapsed time, so a rerun can flip them. Since the gold itself treats the order as free, passing depends on tie-break
luck, so I count all three; lane 2 is a 25-row page (OFFSET 50) and stays wrong. The alternative standard is strict
basketball chronology (the free throw follows its basket): under it only files a/b/c are fully right, and every lane has
at least one free throw placed before its basket, so no lane would be right. Medium confidence.

Labels: official [1] -> strict [0, 1, 3], lenient [0, 1, 3].

## bq462

The question restricts Biggest Championship Margins to "National Championship games since the 2016 season (season >
2015)". The files give two rows either way: the 2016 and 2017 tournaments in files a-f, or the 2016-17 and 2017-18
seasons in file g. All lanes filter only tournament_type = 'National Championship' and list five finals from 2014-2018,
giving 20 rows instead of 17; lane 3 also reports a margin of -3. Their other three categories carry the gold's values,
including both accepted venue sources (game venues led by AT&T Stadium, or team arenas led by the Carrier Dome). The
exact-string matchup and venue columns would also reject the lanes' mascot-only matchups, but the ignored filter alone
decides it. Gold right.

Labels: official [] -> strict [], lenient [] (unchanged).
