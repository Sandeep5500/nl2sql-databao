# deep11 audit notes (Nov 19 2026)

Batch: bq227, bq200, bq144, bq293, bq105, bq277, bq360, bq114, bq186, bq066, bq278, bq418. Lane n = trace folder
lane_k(n+1). Pre-rewrite golds were read from the Spider2 submodule history (parent of commit 5fa8a517). Lane values
were compared with the gold files by local Python (`python3 -I`), using the results recorded in the traces.

Verdicts: gold_right 7 (bq200, bq144, bq105, bq277, bq114, bq066, bq418), scoring_defect 3 (bq227, bq360, bq186),
two_readings 2 (bq293, bq278), gold_wrong 0, unclear 0. Labels change for bq227, bq360, bq186 (strict and lenient) and
bq278 (lenient only).

## bq227

The question asks for each of the five top-2008 minor categories' share of London's total crimes, for every year, with
one row per year. The single file pivots the five categories into columns for 2008-2016 (the same values as the
pre-Nov-2025 gold), and lane 1 matches it. Lane 0 computes the same shares but returns them as one text string per year
("Other Theft: 13.44, Theft From Motor Vehicle: 10.37, ...", ordered by share). Parsing those strings gives all 45
year-category values with no mismatch, so lane 0 is right in substance and is rejected only for its format. I call it a
scoring defect with medium confidence, because packing five numbers into one text column is more than a name or order
difference. Lane 2 returns the combined share of the five categories per year (2008: 47.83). That is not what "the annual
percentage shares ... of the top 5 minor crime categories ... with each year displayed in one row" describes: the
one-row-per-year instruction only matters if each year has several shares. Lane 3 reports 2008 only.

Labels: official [1] -> strict [0, 1], lenient [0, 1].

## bq200

All three files list the 30 MLB clubs with identical speed vectors and differ only in which pitcher they name for tied
speeds. Only the speed column is scored. Lane 0 confirms team membership through the lineup rows. Its own q5 shows that
those rows miss starting pitchers (Stroman and Tomlin had no lineup match in the sample game), so the Royals fall to
Kelvin Herrera 100 instead of Yordano Ventura 101. Lane 3 uses the homeFielder/homeBatter/awayFielder/awayBatter columns,
which are what "the relevant home or away player lists" names, and gets Ventura 101. But lane 3 keeps a 910 mph pitch by
James Happ (one 2016 postseason record, its q14) as the Blue Jays' maximum, a data error that "the maximum valid pitch
speed" rules out. Both lanes also add the 2016 All-Star squads ("American League", "National League"), giving 32 rows.
Whether those squads count as teams is debatable, but no lane is right under either choice. Lanes 1 and 2 are fallback
lists of team names. The pre-rewrite gold also had Ventura 101.

Labels unchanged: none right.

## bq144

Lane 0 follows the document step by step: win and loss rows from 2014 on plus the 2018 results, LEFT JOINs to
feature_engineering for the team and the opponent, differences taken as opponent minus team. It returns file a's 664
rows. Lanes 1 and 3 end with LIMIT 10, so they return a 10-row preview of a dataset the question asks to "create". Lane 2
has all 664 rows but divides each difference by the team's value (VCU vs Oregon St.: pace_rank_diff 1.146 instead of
165). The document says the differences are derived "by subtracting the team's metric from the opponent's metric". File
b (656 rows) is the inner-join variant without the 8 games that lack metrics. Both are fair.

Labels unchanged: [0].

## bq293

The current file's lags and moving averages for 1 January 2015 need December 2014 data. Lane 0's q6 shows the named
table, tlc_yellow_trips_2015, has no row before 2015-01-01, while the 2014 table has 165 million (q7). The file is
internally consistent with a continuous hourly series running back into December. For zip 10016, ma_14d_excl rises from
795.883 at 00:00 to 798.053 at 01:00, exactly (1730 - 1001)/336, where 1001 is the 00:00 row's trips_336h_ago (18 Dec)
and 1730 the 00:00 count. It then reaches 802.755 = 798.053 + (2011 - 431)/336. The pre-Nov-2025 gold used 1 January
alone and had NULL 24h/168h/336h lags. The question names only the 2015 table ("using the
bigquery-public-data.new_york.tlc_yellow_trips_2015 dataset") but asks for lookbacks of up to 21 days, so I treat both
readings as fair. No lane is right under either reading. Under the 2015-only reading the trailing 14-day means would be
1730, 1873.5 and 1440 for the three rows that have earlier hours. Lane 0 hard-codes 0.0. Lane 1 returns NULL and a
1-hour lag of 0. Lanes 2 and 3 average the 23 other hours of the day, including later hours. The file's trip counts
(2011, 1809, 1752, 1730, 1673) also differ from what all four lanes get today (2017, 1801, 1758, 1730, 1731); trip_count
is not scored.

Labels unchanged: none right (strict [], lenient []).

## bq105

Lanes 1 and 3 count distinct fatal accidents with at least one recorded distraction other than the three excluded
statuses. They reproduce file a's ten states, counts and ranks exactly (2015 New Mexico 124 ... Wyoming 15; 2016 New
Mexico 147 ... Louisiana 143), and only those counts are scored. Their rates differ from file a's by at most 0.022 per
100,000 for one reason: they sum zip-level 2010 census population through utility_us.zipcode_area (New Mexico
2,053,681), while file a uses the official state total (2,059,179). File b uses an even lower zip sum (2,013,122). The
accepted files disagree by 2% on population, so the lanes' figure is a method choice, not an error. Lane 2 counts
distraction rows rather than accidents (New Mexico 2015 rate 6.23, and Idaho ranked above Kansas in 2016) and outputs no
counts. Lane 0 is a fallback list of state names.

Labels unchanged: [1, 3].

## bq277

Lanes 0, 1 and 3 all answer BEAUFORT, but they group by port name. Region 6585 has two different BEAUFORT ports, in
North Carolina (index 8420) and South Carolina (8520). The question asks "Which single port". Lane 3's own per-port counts
with the same max-radius circle (q14, q16) put SOUTHPORT (8480) first with 298, then WRIGHTSVILLE 294, MOREHEAD CITY 293,
CHARLESTON 291 and BEAUFORT NC 291, with BEAUFORT SC at 229. BEAUFORT's 520 is the sum of the two ports. That is the
same pooling-by-name flaw as light2's bq019 (Springfield), so the lanes are wrong whichever storm-area method is used.
The document's azimuth_to_geog_point and ST_MAKEPOLYGON also point to a quadrant-shaped storm area, not a circle. The two
files name different single ports. CHARLESTON is the pre-rewrite gold. PLYMOUTH was added in Nov 2025 and might come from
counting by name (several ports are named PLYMOUTH), but checking either needs warehouse data. The labels are right
whatever the files' status, hence gold_right with medium confidence.

Labels unchanged: none right.

## bq360

Every file is the full top-10 table (65, 44, 31, 29, 28, 23, 22, 21, 17, 14; average 29.4) with Family flagged as
closest. Lanes 0-2 reproduce that top 10 exactly in their traces (lane 0 q14) and return the one row the question
finally asks for: "Family, 29, 29.4, 0.4". The gold SQL returns a single row, and the pre-rewrite gold was a single row
(Psychiatry, from older data). With condition_cols [] the 10-row files require every column, including the average,
the difference and a flag spelled four ways (True/False, Y/N, "*** CLOSEST TO AVERAGE ***", 0/1). So a correct one-row
answer can never pass, which is a scoring defect. Lane 3 counts only each provider's primary taxonomy (top 10: 64, 39,
29, 28, ..., average 26.6), finds the same ten specializations, and also answers Family (28). I count it right on the
answer: the question asks "which" specialization, and the supporting count reflects a fair primary-taxonomy reading. If
the project instead requires the top-10 list in the output, this case becomes two_readings over output shape.

Labels: official [] -> strict [0, 1, 2, 3], lenient [0, 1, 2, 3].

## bq114

Lanes 1-3 return Knoxville, MADISON and HANCOCK with differences 8.81396, 4.873345 and 4.679546. These are identical to
file a and to the pre-rewrite gold (EPA 1990 means minus OpenAQ 2020 values: 14.81396 - 6.0, and so on). Lane 0's EPA
subquery has no year = 1990 filter, so it averages every year and returns Phoenix, Weaverville and Catano. Only the city
column is scored. File b's difference has the opposite sign but the same cities. Nothing changes.

Labels unchanged: [1, 2, 3].

## bq186

The four files cover two readings of "bike share trips in San Francisco". Files a-c keep San Francisco trips only, and
file d keeps all stations (for example, the 201309 maximum is 4198.83 in a-c and 9958.62 in d). Lanes 0-2 use no city
filter and match file d in 146 of the 148 scored values. The two differences are 201409 first (9.466667 vs 9.483333) and
201410 last (5.033333 vs 4.366667). Those are ties: files a and c, identical everywhere else, disagree at exactly these
two cells (8.966667 vs 9.483333; 5.033333 vs 4.366667). File b departs from a and c at 201401 first (7.20 vs 7.25), and
file a departs from b-d at 201510 first (8.833333 vs 8.95). start_date has minute resolution (lane 3's q4 shows three
trips starting at 09:24:00), and the question defines first and last only "by the chronological order of the trip start
date". So each file hard-codes one arbitrary pick among tied trips, and the 0.01 tolerance rejects every other pick.
Lane 3 runs the same ROW_NUMBER logic; its first 12 rows equal lanes 0-2's, and the rest were not shown.

Labels: official [] -> strict [0, 1, 2, 3], lenient [0, 1, 2, 3].

## bq066

The coding is counter-intuitive. Lane 2's q3 shows Maternal_Morbidity_YN = 1 is "None checked" and 0 is "At least one
checked". So the gold SQL's YN = 0 actually counted births with morbidity, and that is why the pre-rewrite gold was
negative (-0.114, -0.100, -0.094). The current file uses "None checked" births over all births. Lanes 0 and 1 reproduce
it to about 1e-12 (0.13090, 0.09065, 0.07750). Lane 2 writes Pearson's formula by hand over LEFT JOINs with COUNT(*),
so counties with no census match enter n and the y sums but not the x sums (0.1179, 0.1116, 0.0883); that is a bug.
Lane 3 drops "Unknown or Not Stated" births from the denominator (0.1152, 0.1003, 0.0941). The question asks for "the
percentage of births without maternal morbidity", whose plain denominator is all births, and lane 3 never argues for
the exclusion. Medium confidence, because excluding unknowns is a common vital-statistics convention; if the project
accepts that reading, lane 3 belongs in the lenient list.

Labels unchanged: [0, 1].

## bq278

The state_name field has 72 values: the 50 states plus DC (102 rows over the two levels) and 21 others, namely 20 Puerto
Rico municipalities (Aguadilla, Arecibo, Bayamón, ..., San Juan) and Baja California (37 rows). All seven files keep
all 139 rows, and lanes 0, 2 and 3 match them. Lane 1 restricts "each state" to the 50 states plus DC and returns 102
rows. Its 50 visible rows equal file b cell for cell (checked locally), and the Nov 18 readings found the same for all
its shared rows. A municipality of Puerto Rico or a Mexican state is not a US state, so leaving them out when asked for
"each state" is a fair literal reading, even though the files follow the dataset's own labels. This is two_readings:
strict stays official, and lenient adds lane 1. File a's condition_cols include REGION_COUNT, which no lane outputs, and
files f and g accept a second way of averaging the coverage percentages; neither matters here.

Labels: official [0, 2, 3] -> strict [0, 2, 3], lenient [0, 1, 2, 3].

## bq418

Both files give RSK activation, CREB phosphorylation and "VEGF binds to VEGFR leading to receptor dimerization", each
with 3 sorafenib targets inside, out of 28 (file a) or 29 (file b) targets. The two files differ only in the size of the
non-target background. All four lanes count Reactome physical-entity IDs rather than targets: 514-617 "targets" and
about 25,000-28,600 "non-targets". This lets pathways crowded with mutant KIT and FLT3 entities win ("Signaling by kinase
domain mutants of KIT": 44 target entities, 0 non-targets). Lane 2's q24, which counts distinct targets per pathway,
gives exactly the files' in-pathway counts (3, 3, 3 for the three gold pathways), but it then went back to entity
counts. The question asks how many "of these targets and non-targets" lie inside and outside each pathway, and the
targets are drug-target proteins, not their many Reactome representations. The pre-rewrite gold also counted at the
target level (RSK activation 3 in, 32 out), with a smaller background.

Labels unchanged: none right.
