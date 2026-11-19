# deep10 audit notes (Nov 19 2026)

Batch: bq064, bq137, bq085, bq130, bq086, bq391, bq096, bq034, bq393, bq049, bq403, bq457. Lane n = trace folder
lane_k(n+1). Pre-rewrite golds were read from the Spider2 submodule history (parent of commit 5fa8a517).

Verdicts: gold_right 7 (bq137, bq085, bq391, bq096, bq049, bq403, bq457), two_readings 2 (bq130, bq393),
scoring_defect 1 (bq086), gold_wrong 1 (bq034), unclear 1 (bq064).

Two of these questions involve tables that changed after the gold was made. In bq034 the station table only grew, and
the lanes used the gold SQL's own method, so today's right answer is known and the stale list is marked wrong. In bq064
the zip boundaries changed, but the lanes also used a different tract table, so today's right answer is not known and
the case stays unclear.

## bq064

The question allocates 2017 ACS tract population and income to zip codes by overlap area, keeps zips "located within
a 5-mile radius" of (47.685833, -122.191667), and reports population and average income per zip. Only the income
column is scored. Both files hold 17 zips. The pre-rewrite file is identical to file b and carries the gold SQL's own
column names, so the gold SQL produced it in 2024. Lanes 2 and 3 apply exactly the gold SQL's zip filter (distance
from the zip polygon to the point at most 8,046.72 m) and get 16 zips: 98155 (income 39,512.9 in the gold) is no longer
within 5 miles. The zip_codes geometry has therefore changed since the gold was made. Population also moves between
neighbouring zips: 98034 has 38,236.9 in the gold against 44,755.9 for lane 3, and 98011 has 32,882.0 against 26,397.7,
yet the two sums agree (71,118.9 against 71,153.6). Incomes differ on every shared zip by far more than 0.01 (98039
105,015.6 against 105,230.7). The lanes also used census_tracts_washington where the gold SQL used
us_census_tracts_national, and nobody queried the national table, so I cannot say whether lanes 2-3 equal what the gold
method returns today. Lanes 0-1 additionally keep only zips whose internal point lies within 5 miles (8 zips), a second
fair reading of "located within a 5-mile radius". No correction.

Labels: official [] -> strict [], lenient [] (unclear).

## bq137

"Summing only male and female populations with no age constraints" means the male and female rows that carry no age
range: population_by_zip_2010 also stores each gender split into age brackets. All four lanes sum every male and female
row, so every population is exactly doubled: 98033 68,676 against the gold's 34,338, 98126 41,396 against 20,698, 98115
92,412 (2 x 46,206). Files a, b and c list the same 31 zips (total population 646,470). File d drops 98033. File b's
column list scores its GeoJSON polygon column, which no WKT answer can match. Neither quirk affects a lane. Gold right.

Labels: official [] -> strict [], lenient [].

## bq085

All four lanes hit the step limit. Lane 0's last query is a full answer, but it divides by population_by_country.year_2018
(US 244.38 per 100k against 242.66; China 6.20 against 6.12), although the question asks for 2020 populations and
world_bank_wdi.indicators_data with 2020 SP.POP.TOTL was in its schema. Lanes 1-3 end on exploration queries: a
population lookup with empty values, a three-day case listing and a list of country names. The files differ only in
which JHU table supplies the cases (confirmed_cases: US 799,531; summary: US 784,326). File d adds Hong Kong and Macao
to China's population, a defensible reading of "summing all relevant population entries". Gold right.

Labels: official [] -> strict [], lenient [].

## bq130

Every file and lane agrees that Illinois is the fourth state (New York, California, New Jersey, Illinois,
Massachusetts) and that its top five counties are Cook, Lake, DuPage, Kane and Will. The pre-Nov-2025 gold was just
those five names (condition_cols []), and the gold SQL selects only county. The rewrite replaced it with eight files
that also contain the state ranking (10, 26 or 27 rows) and set condition_cols to [2, 3], the frequency and rank
columns. So a counties-only answer can no longer match any file. The question ends with "identify its top five
counties", but also says "Please compile a ranking based on how often each state appears". Reading that as a required
output is fair (the files), and so is reading it as the step that finds the fourth state (the original gold). Lanes 0,
1 and 3 return exactly the five counties, with frequencies that differ from every file's (Cook 87 or 90, against 87, 91
or 92 in the files). Under the counties-only reading the frequencies are extra columns. Lane 2 returns all 16 counties
that ever appeared, which is not a top five under either reading.

Labels: official [] -> strict [], lenient [0, 1, 3].

## bq086

condition_cols are [[4], [4], [4], [3], [3], [3]] for files a-f. Files d and f have four columns, so index 3 is their
percentage. File e has five (country_name, iso_3166_1_alpha_3, cumulative_confirmed, population_2018,
confirmed_pct_of_population), so its index 3 is the population. Lanes 0 and 1 run the same join and filters
(alpha-3 code, 2020-06-30, aggregation_level 0, positive 2018 population) and return 213 rows. That is file e's row set,
which keeps Macau with no cases. The scorer records lane 1 as matching file e, through its population column. Lane 0's
percentages equal file e's (Qatar 3.487213, San Marino 2.116324, USA 0.757068), but it outputs no population, so it
fails only because of the misplaced column index. Lane 2 drops the null row and matches file b (212 rows). Lane 3 maps
alpha-2 to alpha-3 codes by hand and keeps only 205 countries, losing real ones, so it stays wrong. File a (262 rows)
lists World Bank aggregates as countries with 0 cases ("World", "European Union"), which is wrong but matches no lane.

Labels: official [1, 2] -> strict [0, 1, 2], lenient [0, 1, 2].

## bq391

Lanes 0-1 read the question literally. They take living patients (deceased is null; dead patients carry
deceased.dateTime) whose first family name starts with A and who have exactly one distinct condition code. For each such
patient they count distinct active medication codes, then take the maximum per condition. That gives Coronary Heart
Disease 4, acute viral pharyngitis 4, and exactly six conditions at 3 (the ninth is at 2 or less), the same eight as
file a and the pre-rewrite gold. Files b and c (Childhood asthma 2, Hypertension 1, Contact dermatitis 1, then
arbitrary zero ties) evidently count only medications tied to the condition. No lane matches them, so they change
nothing. Lane 2 counts distinct medications across all patients with a condition (104, 103, ...), not "to any single
patient". Lane 3's one-condition test is vacuous (COUNT(DISTINCT condition_code) = 1 inside a grouping by code), and its
living filter (deceased.boolean IS NULL) keeps dead patients. Gold right.

Labels: official [0, 1] -> strict [0, 1], lenient [0, 1].

## bq096

All four lanes hit the step limit. Their fallback results are exploration queries: a count of 0 for a species key, a
kingdom histogram, one day's record count, and a count of records north of 40 degrees. None returns a year. File a
(2023) is the pre-rewrite gold and what the gold SQL's day-of-year ordering returns. File b (1894) fits ranking years by
absolute earliest date. Accepting it harms no lane. Gold right.

Labels: official [] -> strict [], lenient [].

## bq034

The question asks for stations "within a 50 km straight-line distance" of central Chicago. Lanes 1 and 3 compute
great-circle distance with R = 6,371 km, equivalent to the gold SQL's ST_DWithin to well under a metre at 50 km, and get
462 stations. Their 50 nearest stations are file a's first 46 in the same order plus four high-numbered CoCoRaHS
stations: US1ILCK0438 (2.28 km), US1ILCK0421 (8.22 km), US1ILCK0426 (9.57 km) and US1ILCK0455 (12.19 km). The station
table keeps growing. The pre-rewrite gold had two files, both gold SQL output with dist_meters: 445 stations (Nov 2024,
identical to current file a) and 457 stations (May 2025). The 457-station file includes US1ILCK0421 at 8,215.12 m and
US1ILCK0426 at 9,569.85 m, matching the lanes' distances. The rewrite kept only the 445-station list and turned file b
into that list's first 100 IDs, which no complete answer can match. The accepted files therefore omit stations that
exist and lie within 50 km, so I mark the gold wrong and count lanes 1 and 3 right. Lane 0 drops cos(latitude) from its
distance (358 stations) and lane 2 uses 50 miles (944 stations); both stay wrong.

Labels: official [] -> strict [1, 3], lenient [1, 3].

## bq393

Every lane finds the same user: gaborcselle, first active Oct 2006, last active Aug 2024, with empty months including
April-July 2024 (data end 2024-09-09). Only gaborcselle has a 215-month span. The lanes differ only in which month they
report and how they number it:

- **Sept 2024, the first inactive month after the last activity.** It is month 216 counted from 1 (both files, lanes 0
  and 2), or 215 as "the count of months since the user's first activity". 215 is lane 3's value, which it computed as
  the span length.
- **July 2024, the latest empty month inside the span.** It is 214 counted from 1 (lane 1), or 213 counted from 0. 213
  is exactly the pre-Nov-2025 gold (gaborcselle, 213). gaborcselle's July 2024 gap is also the latest empty month inside
  any user's span (lane 1, q8), so that reading picks the same user uniquely.

"Became inactive ... after their last recorded activity month" favours the first reading. "Activity followed by
inactivity" and "expected to be active (within their activity span) but actually had no records" support the second,
and the question's author evidently used it. The two numbering phrases point in opposite directions ("counting from
their first activity month" against "count of months since"). The files accept only 216, so strict keeps lanes 0 and 2,
and lenient adds lanes 1 and 3. File b's user adamsmith cannot be reproduced, but only the month number is scored.

Labels: official [0, 2] -> strict [0, 2], lenient [0, 1, 2, 3].

## bq049

All files, and the pre-rewrite gold (headed "dollars_per_capita"), give zip 52003 with dollar sales divided by its
9,882 residents aged 21+: January 13,113.41 / 9,882 = 1.327, December 1.6447. All four lanes find the same zip and
population but divide liters sold (January about 0.046). "Per capita ... sales", in a table whose sales column is
sale_dollars, means dollars. Lanes 0-2 also keep only STRAIGHT BOURBON WHISKIES, dropping the other two bourbon
categories. The files agree with each other apart from rounding. Gold right.

Labels: official [] -> strict [], lenient [].

## bq403

The file, the pre-rewrite gold and the gold SQL treat each filing-year table (irs_990_2012 ... irs_990_2017) as that
year, use all of its rows, and give 2012 20,639.0, 2013 20,988.0, 2017 26,391.5. In these tables most returns belong to
the previous tax period: in irs_990_2012, 132,771 rows have tax_pd 201112, 56,701 have 201106 and 25,092 have 201206.
Lanes 0 and 2 regroup rows by tax-period year but read only the 2012-2017 tables, so tax years 2016-2017 are partial;
lane 0 also drops non-positive values. Lane 1 averages the rows in a 0.4999-0.5001 percent-rank band instead of taking
a median. Lane 3 keeps only rows whose tax period falls in the table's year (40,768 in the 2012 table) and drops
non-positive values. None computes medians for the filing years, and none is a complete tax-year computation either.
Gold right.

Labels: official [] -> strict [], lenient [].

## bq457

"Repositories that depend on the specified feature toggle libraries" matches libraries.io's repository_dependencies
table, which records the dependencies in each repository's own manifests. The three files list four such repositories
with matching artifact and platform: Informatievlaanderen/datadog-tracing (FeatureToggle, NuGet), incodehq/relatio
(Togglz), ccmdesign-archives/iodc18-osem-archive (feature, Rubygems) and wildsebastian/nixpkgs (flipper). This copy of
the table is a sample: only 85 of its 36,999,999 rows name a listed artifact. The lanes instead join the package-level
dependencies table through projects to the depending package's repository. That returns the libraries' own repositories
(jnunemaker/flipper, launchdarkly/js-client) and package repositories such as edx/edx-proctoring. Lanes 0-1 also ignore
the platform, labelling an npm "unleash" dependency as the Ruby gem, and lane 2's fallback has rows with no repository.
That route is a proxy, not the question's relation, so the gold is right. Medium confidence, because there is no gold
SQL.

Separately, all three files store the update time as integer microseconds and two give size in KB under a "bytes"
header. So even an answer with the right repositories, printing TIMESTAMP values, could match no file under
condition_cols []. No lane is affected.

Labels: official [] -> strict [], lenient [].
