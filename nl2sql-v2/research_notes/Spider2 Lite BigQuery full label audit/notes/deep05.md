# deep05 audit notes (Nov 19 2026)

Batch: bq021, bq038, bq053, bq054, bq098, bq185, bq202, bq203, bq041, bq123, bq302, bq304. Lane n = trace folder
lane_k(n+1). Pre-rewrite golds were read from the Spider2 submodule history (parent of commit 5fa8a517).

Verdicts: gold_right 7 (bq021, bq038, bq098, bq041, bq123, bq302, bq304), two_readings 3 (bq053, bq054, bq185),
scoring_defect 1 (bq202), gold_wrong 1 (bq203), unclear 0. Labels change in bq053, bq054, bq185 (lenient only) and
bq202 (strict and lenient).

## bq021

The question says "The coordinates are rounded to three decimals", so bike routes and taxi trips are matched on
coordinates rounded to three places. The gold SQL and lanes 0-2 do exactly that and all answer 12 Ave & W 40 St: on
its route to West St & Chambers St the bike averages 1,483.9 s and matching taxis 1,634 s, and no other route that
beats the taxis has a longer bike time. The file and the pre-rewrite gold agree. Lane 3 instead compares raw taxi coordinates
with the rounded station point using ABS(diff) < 0.001, a window twice as wide as a rounding cell. That pulls in many
more taxi trips, the taxi average on the 12 Ave route drops to 869.8 s, only four Pershing Square North routes stay
faster than taxis, and lane 3 answers Pershing Square North. Lanes 0-2 keep round trips in the top 20 while the gold
SQL removes them; the answer does not change. Gold right, labels unchanged.

Labels: official [0, 1, 2] -> strict [0, 1, 2], lenient [0, 1, 2].

## bq038

There is no gold SQL. The three files agree with each other (3182 Yankee Ferry Terminal 3,760 of 8,674 = 0.4335,
3181 0.4289, 3254 0.3542, 2006 40,094 of 170,829, ...) and use the same denominators (all trips ending at the station)
as the lanes. The question defines group rides as trips where "multiple riders departed/arrived within the same
2-minute time window". All four lanes use only start times of round trips: lane 0 marks a trip if the previous or
next round trip at the station started within 120 s, lane 2 uses fixed 2-minute buckets, lane 3 uses pairs within
120 s but skips pairs with identical start times, and lane 1 uses lane 0's rule but inner-joins citibike_stations,
which silently drops stations missing from the current station table (3181, 3182, 3257, 3180). Every gold numerator
is larger than every lane count we have for the same station (2006: 40,094 against 27,573-33,837; 3423: 154 against
78-103), which fits a rule that also counts riders who arrived together. I cannot reproduce the gold's exact rule
without the data, but none of the lanes implements the "arrived" half under any reading (AND or OR), and their
proportions miss by 0.04 or more (3182: 0.32-0.40 against 0.4335). Gold right at medium confidence; labels
unchanged. The pre-rewrite gold (a different station list) answered an older wording of the question.

Labels: official [] -> strict [], lenient [].

## bq053

The question contradicts itself on the sign. It asks for "the change in the number of living trees ... from 1995 to
2015", which suggests 2015 minus 1995, but defines the computation as "the difference between the number of trees not
marked as dead in 1995 and the number of trees alive in 2015", which read literally is 1995 minus 2015. Both files
(and the gold SQL and pre-rewrite gold) use 2015 minus 1995: Yellow +229,431, Maroon +53,509, ..., Red +1,000. Lane 1's
eight values are exactly these numbers negated, and lane 3's thirteen values are exactly file b negated, including
its five zero colours; lane 3's trace says outright "So it's: (1995 not dead) - (2015 alive)". Both are a fair literal
reading, so I mark two readings and add lanes 1 and 3 to the lenient list. Lane 0 inner-joins on 1995 counts and drops
species that did not exist in 1995 (no Cream row, Yellow -69,049), and lane 2 counts COUNT(*) over LEFT JOINs, adding
1 for every unmatched species (Cream -19,337, Yellow -229,423); both are wrong under either reading.

Labels: official [] -> strict [], lenient [1, 3].

## bq054

There is no gold SQL, and the files go beyond the question in two ways. First, they include 2005 census counts, and
condition_cols [2-10] require them, although the question only speaks of growth "from 1995 to 2015" and "these
years"; the pre-rewrite gold had no 2005 columns. Second, the two files map the 1995 status values differently, and
neither counts every record. Using QUERCUS PALUSTRIS, whose 1995 statuses appear in lane 3's trace (Good 25,247,
Excellent 8,563, Poor 1,879, Fair 24, Unknown 510, Dead 298, Stump 32): file a drops stumps and counts Unknown as
alive (total 36,521, alive 36,223, dead 298); file b counts stumps as dead and drops Unknown (alive 35,713, dead 330,
total 36,043). Lanes 0 and 1 count all 36,553 records, with alive = the health ratings (35,713) and dead = 'Dead'
(298); their PYRUS CALLERYANA total of 31,295 equals the pre-rewrite gold's count_1995. The ten species and all 2015
counts agree. Reporting only the two compared years and counting every record is at least as fair a reading as the
gold's, so lanes 0 and 1 go on the lenient list. Lane 3 leaves 'Poor' trees out of alive (33,834 for QUERCUS
PALUSTRIS), which is wrong, and lane 2 fell back to a list of species names.

Scoring note: the growth columns the question asks for are never checked, while the unrequested 2005 columns are.

Labels: official [] -> strict [], lenient [0, 1].

## bq098

The question requires that "both the pickup and dropoff occurred between January 1 and 7, 2016, inclusive". Lanes 0
and 3 filter both dates (whole days, January 7 included) and reproduce file a to every digit and file b's counts
(Bronx 2,617 trips, 2,098 without a tip, 80.168%). Lanes 1 and 2 filter only pickup_datetime < 2016-01-08, so trips
that end on January 8 come in (Bronx 2,618, Brooklyn 42,541 instead of 42,448), and Brooklyn's share moves to 46.376%
from 46.398%, outside the 0.01 tolerance; the other boroughs happen to stay within it. Current file a equals the
pre-rewrite file b; the deleted file a probably came from the gold SQL's BETWEEN '2016-01-07', which stops at
midnight. Gold right, labels unchanged.

Labels: official [0, 3] -> strict [0, 3], lenient [0, 3].

## bq185

All three answers rest on the same 19 trips; they differ only in how each trip's duration is turned into minutes.
File b is the exact average: 101.0026 min, i.e. 115,143 s over 19 trips. File a carries a Snowflake header,
AVG(DATEDIFF(MINUTE, ...)), which counts minute boundaries crossed: 1,920 whole minutes, 101.0526. Lanes 0, 1 and 3
average BigQuery's TIMESTAMP_DIFF(..., MINUTE), which truncates each trip: 1,912 whole minutes, 100.6316 (lane 1
reports cnt = 19). As a check, the 17 trips visible in lane 1's trace sum to 108,797 s exactly, 1,807 truncated
minutes and 1,814 boundary minutes, leaving 6,346 s, 105 and 106 for the remaining two trips, which is consistent.
The most precise answer is 101.00, but the gold already accepts one whole-minute convention (Snowflake's), and
BigQuery's whole-minute convention is the same kind of choice, so I mark two readings, as the Nov 18 audit did for the
one-second TIMESTAMP_DIFF convention in bq308. Strict stays official because truncation biases every trip downward
(by half a minute on average), while boundary counting does not. Lane 2 has no date filter (all of February, 50.41)
and is wrong under any reading.

Labels: official [] -> strict [], lenient [0, 1, 3].

## bq202

All lanes find the right station, Pershing Square North (519, 55,990 trips started there in 2018). The current files
take the busiest single (day, hour) slot: day 4, hour 18, 1,943 trips (file b 1,944). Lane 0 finds exactly that slot,
5, 18, 1,943 trips, but numbers the day with BigQuery's EXTRACT(DAYOFWEEK), where 1 is Sunday (lane 1 checked that
Monday 2018-01-01 returns 2), so 5 is Thursday; the files' 4 is Thursday under 0 = Sunday or ISO 1 = Monday numbering.
"Which numeric day of the week" fixes no numbering, so the scorer rejects an equivalent encoding: a scoring defect,
and lane 0 goes on the strict list. Lanes 1-3 instead report the busiest day (Tuesday = 3, 11,218 trips) and the
busiest hour (17, 8,841 trips) separately. "Which numeric day of the week and which hour of the day had the greatest
number of trips" allows that reading, and all three pre-rewrite files were exactly (3, 17), so lanes 1-3 go on the
lenient list.

Labels: official [] -> strict [0], lenient [0, 1, 2, 3].

## bq203

The four accepted files cannot all be right: Manhattan has 40 stations with an accessible entry in file c (26.49%),
13 in file a (8.61%), 7 in file b (4.64%) and 0 in file d, and Brooklyn ranges from 20 down to 1. The cause is the
link between the two tables, which share no station ID. Joining on station_name, as the gold SQL does, matches only 25
of Manhattan's 99 distinct station names (lane 1, q2 and q8; the gold SQL's own output in the pre-rewrite file also
has 25), although the entrance table holds 1,866 entrances, so stations whose names are written differently in the
two tables can never be counted as accessible. Files a, b and d are therefore capped by the name match, and at least
three of the four files are wrong; whether file c's linkage is exactly right cannot be checked without the data. All
four lanes also join on station_name (lane 1 adds division): lane 2 reproduces file a's counts exactly (19/169, 13/151,
4/70, 2/82, 0/21) and lane 3 its numerators over station rows (153, 83) rather than distinct station IDs, so they
inherit the same undercount. I mark gold_wrong at medium confidence with no label change. If file a were accepted as
valid, lane 2 would fail only through rounding to one decimal (11.2 against 11.24).

Labels: official [] -> strict [], lenient [].

## bq041

Lanes 0-2 count users who asked a question between signup and signup + 30 days, then users who answered after their
first question and within 30 days of it. They reproduce file b to the digit (January 10.40 / 12.19 through December
8.61 / 8.54) and files c and d within rounding (0.005). Lane 3 takes each user's first question ever and tests
TIMESTAMP_DIFF(first question, signup, DAY) <= 30. That accepts negative gaps, which its own trace found (first
questions years before the account was created), and gaps up to 30.99 days, and it applies the same 31-day test to
answers. It gets 10.42 / 12.25 for January against 10.3953 / 12.1946, outside the tolerance. Gold right, labels
unchanged.

Labels: official [0, 1, 2] -> strict [0, 1, 2], lenient [0, 1, 2].

## bq123

"The percentage of questions on Stack Overflow that receive an answer within an hour" has all questions as its
denominator, and the gold SQL left-joins first answers to every question. Lane 1 does the same and gets Friday
49.787, within 0.01 of all three files (49.7835-49.7839). Lanes 0, 2 and 3 inner-join posts_answers, so questions
with no answer drop out of the denominator; that changes the ranking (Thursday third) and the value (58.20%, given by
lane 0 as the fraction 0.582). The pre-rewrite 49.96 probably comes from the gold SQL's MINUTE <= 60 test, which admits
answers up to 60.99 minutes. Gold right, labels unchanged.

Labels: official [1] -> strict [1], lenient [1].

## bq302

"Questions tagged with 'python'" names one tag. The gold SQL splits the tag string on '|' and keeps tag = 'python';
lanes 2 and 3 use an exact-tag regex and reproduce file a and the pre-rewrite gold to every digit (January 22,518 of
143,345 = 0.15709). Lanes 0 and 1 use tags LIKE '%python%', which also counts questions whose only python-like tag is
another tag such as python-3.x; they get 24,259 January questions (0.1692), about 0.012 too high in every month. Gold
right, labels unchanged.

Labels: official [2, 3] -> strict [2, 3], lenient [2, 3].

## bq304

Files a and c contain the same 500 (tag, question) rows, and these equal the pre-rewrite gold, which is the gold SQL's
output with substring tests on title and body. File b differs in 112 rows; it is stricter on "how" and looser on the
excluded terms, consistent with whole-word matching (only 2 of the 112 rows unique to a and c have "how" as a word in
the title, against 68 of the rows unique to b). Both are fair readings of "contain the word 'how'", and both list a
question under every requested tag it carries (14483393 appears under android-layout and android-actionbar). Every
lane breaks this: lanes 2 and 3 assign each question to one tag through a CASE, so 14483393 and 15560904 are missing
from their android-actionbar lists; lane 0 matches tags with LIKE '%android-actionbar%' and admits 31297246, which the
files list only under android-activity and android-fragments; lane 1 checks only titles and admits 8024706 (535,959
views), which no file contains. Gold right, labels unchanged.

Labels: official [] -> strict [], lenient [].
