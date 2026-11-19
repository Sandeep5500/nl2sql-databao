# deep09 audit notes (Nov 19 2026)

Batch: bq047, bq048, bq067, bq441, bq339, bq376, bq366, bq414, bq143, bq162, bq046, bq282. Lane n = trace folder
lane_k(n+1). Pre-rewrite golds were read from the Spider2 submodule history (parent of commit 5fa8a517). Lane values
were checked against the gold files with the official comparison code (`nl2sql-v2/src/nl2sql/eval.py`) where a
lane's full result was visible.

Verdicts: gold_right 8 (bq047, bq048, bq441, bq339, bq414, bq143, bq046, bq282), gold_wrong 1 (bq376),
two_readings 1 (bq366), scoring_defect 2 (bq067, bq162), unclear 0.

Harness finding that affects bq067 and bq441: the run stores a submitted result only up to 5,000 rows
(`result_rows_max: int = 5000  # full stored result cap (max gold is 2000 rows)` in `nl2sql-v2/src/nl2sql/config.py`
on origin/rohini-platforms, the branch of the Nov 17 run; the agent's submitted DataFrame comes from that store). The
comment is wrong for BigQuery: bq067's gold files have 13,827-25,422 rows and bq441's 74,270-81,620, so no
submission to either question could ever match. This is our harness, not Spider2.

## bq047

The five files use three ways of handling days without complaints. Files a, b and d use only the days each type
was reported (per-type day counts up to 2,921); file e fills in zeros over the 2,922 days the 311 table covers;
file c fills in zeros over all 3,653 valid-temperature days from 2008 to 2017. Lane 0 reproduces file a exactly
(19 rows) and lane 2 reproduces file c exactly (14 rows). The 311 table starts in 2010 (lane 0 q3, lane 3 q1), so
c's count correlations include 731 days of 2008-2009 counted as zero complaints, which weakens them (Maintenance or
Facility 0.5503 in c against 0.6815 in e). But the question itself fixes the window, "for the 10 years starting in
2008", and asks for "the total number of days with valid temperature records", which is c's 3,653, so c follows the
question's words and I keep lane 2. Lane 3 used 2010-2019, which contradicts the stated window. Lane 1 defined the
percentage as count divided by the type's ten-year total, so its percentage correlation equals its count
correlation (0.5503 and 0.5503); all five files use the type's share of that day's complaints, and asking for two
identical correlations would be pointless. Labels unchanged: [0, 2].

## bq048

The question wants the type with the strongest positive and the type with the strongest negative correlation
between daily proportion and JFK wind speed. File a uses only the days a type was reported: HEAT/HOT WATER 0.3942
and Outdoor Dining -0.3987. Lane 3 gets 0.394 and -0.3977, and lanes 0 and 1 found the same values in their
traces. File b fills in zero proportions on days without complaints: Street Sign - Dangling 0.3574 and Sanitation
Condition -0.3243, matched exactly by lane 2. Both treatments are fair and both are accepted. Lane 0 submitted all
163 types and lane 1 the top 20 positive ones, so neither answers the question. Lane 3 takes the two largest |r|,
which here have opposite signs, and skips the 999.9 wind code, which is harmless (no missing days in the year
checked; three lanes agree to four decimals). Labels unchanged: [2, 3].

## bq067

No lane could pass because of the harness cap described above: every submission was cut to 5,000 rows, and every
gold file has at least 13,827. On substance, lane 0 matches files a and b. Its query returns 13,848 accidents
(q12), the label split is 11,614 / 2,234, the speed levels are NULL 8,096 / 3,661 / 1,324 / 543 / 216 / 8, and the
12 preview rows have file a's body type and average speed difference. All of these equal file a's. File b checks
only drunk drivers, weekday, hour, work zone and average speed difference, and those value sets are identical in a
and b, so lane 0's full result would match b. Lane 1 (13,848 accidents, same label split, body type of the first
vehicle) has all 15 preview rows in file d, including two rows that a, f and g do not have, and d checks only body
type, drunk drivers, weekday, hour and work zone. Lane 1 gives level 0 to accidents with no valid speed; file e
does the same for all 8,096 such accidents, and the question does not say how to handle them, so I count it as
right. Lane 2 drops the accidents without a valid speed (about 5,752 rows remain), and lane 3 submitted a schema
query. Confidence is medium because the full lane results were never seen. Labels: official [] -> strict [0, 1],
lenient [0, 1].

## bq441

The info document mixes crash, vehicle and person fields (age, person type, seating position, restraint,
survived), so the answer has one row per person: 74,270 persons in vehicles or all 81,620 persons, and the files
accept both. No lane built that table. Lanes 0 and 3 submitted LIMIT 5 samples of raw columns, lane 1 submitted 35
summary counts, and lane 2 submitted one row per accident with MAX(age) and ANY_VALUE person fields. The harness
cap would have rejected even a correct answer, but no lane was correct. The document's "survived = 1 if injury
severity is 4" is backwards (FARS code 4 is a fatal injury), and the files follow the document; this affects no
lane. Labels unchanged: none right.

## bq339

The gold (month 9) comes from running totals: customer and subscriber minutes are added up month by month, and
September is where the two totals are furthest apart. Using lane 3's own monthly totals, the running totals in
September are 2,744.0 and 2,062.2 thousand minutes (gap 681.8), the largest of the year. All four lanes compared
per-month totals instead; that comparison peaks in July (338.9, just ahead of December's 335.8), which is what
lane 1 returned, while lanes 0, 2 and 3 returned all 12 months. The lanes did consider running totals but
rejected them because "a running total would make the last month always the largest". That is false for the gap
between two running totals: here it shrinks to 106.1 by December. "Cumulative" means a running total, the gold SQL
uses a running window sum, and the only argument against it is wrong, so I do not treat the per-month reading as
fair. Medium confidence because "cumulative" is sometimes used loosely for "total". Labels unchanged: none right.

## bq376

File a contradicts the question. It lists all 117 neighborhoods, 55 of them with no station, and every row says 0
crime incidents, although the question keeps only neighborhoods "where at least one bike share station and at
least one crime incident are located". Its 62 non-zero station counts (261 stations) are exactly the lanes' 62
rows, so the file's author used the same station table as the lanes but the crime join failed and the filter was
skipped. File b, the pre-rewrite gold and the gold SQL's output, uses `bigquery-public-data.san_francisco.*` (the
2013-2016 station list). That dataset is not part of the question's database: `san_francisco_plus` contains
`san_francisco_bikeshare.bikeshare_station_info` and `san_francisco_sfpd_incidents.sfpd_incidents` (Spider2
resource listing; the lanes' schema shows 19 of 19 tables). In that table South of Market has 30 stations, not 9.
Lane 2's full 62 rows (every neighborhood has at least 2,168 incidents) pass the official comparison against file
a once it is restricted to its 62 rows with a station. Only station counts are scored, and all four lanes share
them. Labels: official [] -> strict [0, 1, 2, 3], lenient [0, 1, 2, 3].

## bq366

"Only considering labels linked to 500 or more artworks" has two fair meanings. It can mean labels with 500 or
more artworks in the whole collection, which the current files use: the top three of those labels for every one of
1,494 periods, with counts down to 1. Or it can mean label-period pairs with 500 or more artworks, which is what
the gold SQL (`c >= 500` on the per-period count) and the pre-rewrite gold (17 rows) do. All four lanes return
those 17 rows, and they are exactly the rows of files a-d with a count of 500 or more, with the same counts; the
official comparison passes against those rows. The lanes count distinct artworks (Qing pattern 865), as the
current files do; the old gold counted label rows (870). File e has 901 rows and stops at "Heian period", so it
looks truncated. Labels: official [] -> strict [], lenient [0, 1, 2, 3].

## bq414

The file has 5 titles, including "The Whole Art of Marbling as Applied to Paper, Book Edges, etc.", so it matches
"book" in any letter case. Lanes 0, 2 and 3 use LOWER(title) and reproduce it exactly. Lane 1 uses the gold SQL's
case-sensitive LIKE '%book%' and misses that title. A title with "Book" in it contains the word "book", so I treat
the case-sensitive match as a SQL default, not a second fair reading. Before Nov 2025 the gold accepted both the
4-row and the 5-row answer; the rewrite kept only the 5-row one. Medium confidence for that reason. Labels
unchanged: [0, 2, 3].

## bq143

The file (Primary Tumor 0.2608, Solid Tissue Normal 0.1729) is the gold SQL's result and also the pre-rewrite
gold: it keeps the genes whose correlation has |r| <= 0.5 ("filter out correlations with an absolute value greater
than 0.5") and averages them per sample type. Lanes 0, 1 and 2 apply the same filter and get 0.2605 and 0.1730.
The 0.0003 difference comes from join details, not from a different method, so the pass is real. Lane 3 hit the
step limit and its fallback returned a single empty value. Labels unchanged: [0, 1, 2].

## bq162

All five files agree on the substance: CODEX, H&E and IMC at WUSTL, each with Level2 data only. Lane 3's trace
confirms it (q37: no Level3/Level4 imaging record derives from a WUSTL Level2 file). Lanes 0-2 return exactly
those three assays with "Level2". The scorer requires every column of a file (condition_cols []), and each file
adds something the question does not ask for or formats it differently: a constant "HTAN WUSTL" column (a, e),
Yes/No or True/False flags (b, d), or the JSON text `["Level2"]` (c). Running the official comparison, the lanes'
answer fails all five files, and the same answer plus a constant center column passes file a. Lane 3 submitted an
empty table, reading the question as requiring Level3/4 data. That reading leaves nothing for "provide the
available data levels", so lane 3 stays wrong. Labels: official [] -> strict [0, 1, 2], lenient [0, 1, 2].

## bq046

Both files name the same 12 patients. File b's 274 rows are a strict subset of file a's 323 (49 file URLs fewer),
and file a equals the pre-rewrite gold. Lanes 0, 1 and 3 follow the stated steps (annotation and clinical sets,
FULL JOIN, both annotation fields NULL, then the three rel14 tables) and return file a's 323 rows. Lane 2 cut its
output with LIMIT 50. Labels unchanged: [0, 1, 3].

## bq282

Both files, and the pre-rewrite gold, say district 9, and only the district is scored. Lanes 0 and 3 count trips
between active stations in the same district with different start and end stations, and get 9. Lane 2 also gets
9, but it left out "but not at the same station", so its extra count column (1,123,325) includes round trips
(file b's count is 940,592). The district asked for is still right, so I keep lane 2. Lane 1's fallback looked
only at 2014 and returned five districts. Labels unchanged: [0, 2, 3].
