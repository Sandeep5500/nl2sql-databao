# Light review, batch light3 (22 questions)

All 4 lanes match an accepted gold file in every question. 19 are `gold_right`. Three change labels, all in the direction of fewer right lanes:

- bq108 (`gold_wrong`): both files count people by person_number alone, which FARS restarts in every vehicle, so all four lanes leave both lists.
- bq198 (`scoring_defect`): lane 0 ranked team nicknames and passes only through file b's nickname column.
- bq161 (`scoring_defect`): three lanes answer 50 and pass only because their "neither" count equals the gold's net difference of 40. Lane 2's 50 is right under the 174-patient reading, so it stays in the lenient list.

## bq269

The question gives the recipe: classify sessions with non-null pageviews by whether they have a transaction, sum pageviews per visitor, month and class, then average per visitor. The lanes do exactly that. Their four averages equal both files to every printed digit (June 25.735763 / 4.074560, July 27.720954 / 4.191841). The two files differ only in how the month is written, and the month is not scored. Verdict: `gold_right`.

## bq270

The document maps action_type 2 to product detail views, 3 to add-to-cart and 6 to completed purchase. Both files hold hit-level ratios of 3 and 6 to 2, in percent, per month. Lane 2 reproduces file b to six decimals (28.471711 / 5.591965, and so on). Lanes 0, 1 and 3 round to two decimals, which is within 0.003 of the files and is not an error in substance. Verdict: `gold_right`.

## bq228

The question names no time range. Summing all years for Barking and Dagenham gives Theft and Handling 50,999, Violence Against the Person 43,091 and Criminal Damage 18,888, which is the file. The gold SQL also sums all years. Verdict: `gold_right`.

## bq232

The lanes filter Westminster, 'Theft and Handling' and 'Other Theft' and sum per year. All nine totals, from 16,501 (2008) to 12,172 (2016), equal the file. Verdict: `gold_right`.

## bq039

The lanes' ten trips equal file e. The five files show three choices, and k3's trace makes them clear.

- Files a-c rank yellow and green trips together and keep trips that end in zone 265. That zone has no row in taxi_zone_geom, which holds only zones 1-263 (k3 q13-q15), and it is where the top trip ends ($474.36 from JFK, 81 miles).
- File d is yellow only. k3 q9, which queried the yellow table alone, does not contain the $181.60 Manhattanville and $172.80 Brownsville trips, so those two are green cab trips.
- File e, like the lanes and the gold SQL's INNER JOIN, drops trips whose zone cannot be named.

"Taxi trips in New York City" fairly covers green cabs. Because the question asks to display each trip's zones, dropping trips with no mapped zone is a defensible choice, even though it removes the most expensive trip. Every reading is accepted, so the labels stand. Verdict: `gold_right`.

## bq040

Lane 0 reproduces the gold counts exactly in all 28 cells, for example Brooklyn no tip 19,729 of 42,541. Lane 3 uses the same logic, and the 12 rows it printed match. Lanes 1 and 2 handle the 16 trips with total_amount = 0 differently from the gold, which files them under no tip:

- Lane 1 drops them with `total_amount > 0`, although the question says amounts must be "non-negative".
- In lane 2, SAFE_DIVIDE returns NULL for these trips, so its ELSE branch files them under "More than 25%" (Brooklyn 542 instead of 540, Manhattan +10, Queens +4).

Either way, proportions move by at most 0.00005, so I count both lanes as the same answer in substance. Only the proportion column is scored, which is lax but harmless here. Verdict: `gold_right`.

## bq108

Both files count "distinct persons" with COUNT(DISTINCT person_number). FARS does not number persons uniquely within a crash. NHTSA's coding manual says "For each vehicle, persons are numbered consecutively beginning with 001" and "Persons not in motor vehicles are numbered consecutively beginning with 01" (FARS Coding and Validation Manual, DOT HS 811 530, general instructions .32-.33). The schema the lanes saw also says person_number is used with ST_CASE "and sometimes the VEH_NO".

Two consequences follow:

- The "more than one distinct person" filter treats a crash between two single-occupant vehicles, or between one driver and one pedestrian, as a one-person crash. Both people carry number 001.
- File b's distinct count of fatal person numbers merges people who died in different vehicles.

The traces show the merge directly. Crash 42-420702 has two fatal person rows (k3 q1) but only one distinct fatal person_number (k4 q1). Over January-August the two methods give 1,401 and 1,320 multi-fatality crashes.

File a is exactly 1,401 / 8,584 = 16.32% (k1 q2), and file b is 1,320 / 8,584 = 15.38% (k4 q3). The denominator 8,584 is the set of crashes with more than one distinct person number, out of 20,923 crashes from January to August (k1 q3). Under FARS numbering this undercounts multi-person crashes.

Nobody computed the share with persons keyed by (vehicle_number, person_number), so the right value is unknown, but it cannot be either file's. All four lanes use the same key and leave both lists. Verdict: `gold_wrong`, medium confidence. The merge is certain from the manual and the trace. The medium rating is because the corrected number was not measured and because the schema text ("assigned to each person in the case") could mislead an analyst. This is the same reasoning as bq019 in light2.

## bq396

California, Texas and Florida lead in every file and lane, with identical Texas (827) and Florida (750) gaps. The files differ only in California's rainy count, which depends on the weather field used:

- 72 with atmospheric_conditions_name: files a and c, and lanes 0-2.
- 55 with atmospheric_conditions_1_name: file d and lane 3.
- 73 in file b.

Any of these fields is a fair choice. Lanes 0-2 report signed differences and match file c (-907, -827, -750); lane 3 reports absolute differences and matches file d. Weekends are FARS day_of_week 1 and 7 (Sunday and Saturday). Verdict: `gold_right`.

## bq284

The lanes' category totals and percentages equal file a: sport 0.78%, business 2.35%, politics 14.63%, tech 3.49% and entertainment 2.33%. They also search titles, which changes nothing at two decimals. File b is a single JSON cell that no tabular answer can match; this is harmless. Verdict: `gold_right`.

## bq077

The seven yearly maxima of monthly motor vehicle thefts equal the file, from 1,880 (2010) to 1,106 (2016). Verdict: `gold_right`.

## bq413

k1 q5 shows that only grid.507983.0 has city 'Qianjiang', so hard-coding that id is equivalent to the gold SQL's join. The six venues equal file b. File a's values carry literal quote marks under a COALESCE-expression header, so no plain answer can match it; this is harmless. Verdict: `gold_right`.

## bq204

There is no clicks column. Each row of the three photo tables is one photo, so "total clicks" means records per user across photos_v_0_1, v_0_2 and v_0_3, the only photo tables. User 0bbc1d2d9453456898c02b77f2bc33f3 has 3,082 records, in the file and in every lane. Verdict: `gold_right`.

## bq402

There are 20,015 purchasers among 741,721 unique visitors, a conversion rate of 0.026985. They made 24,901 transactions, or 1.244117 per purchaser. Both numbers equal file a, and the counts equal file b. The files follow the question's per-purchaser definition. Verdict: `gold_right`.

## bq285

Every lane names zip 33134. Lane 0 counts 39 distinct institutions there, which matches file a. Lanes 1-3 count 48 branch records or return the zip alone, and match file b, which holds only the zip. The question asks only for the zip. Verdict: `gold_right`.

## bq124

The SNOMED codes 44054006 and 38341003 have exactly the displays 'Diabetes' and 'Hypertension' (k1 q1). The lanes' code filter is therefore the gold SQL's display filter, and they count 11,576, which is file b. File a's 14,144 is not reproduced in any trace; it may come from a broader condition match. Accepting it harms no lane. The "alive" filter (deceased.dateTime is null) keeps 999,949 patients (k2 q6). Verdict: `gold_right`.

## bq383

Precipitation maxima (7.9, 8.1, 37.3, 5.8 mm) and TMAX maxima (10.0, 10.0, 15.0, 12.2 C) for December 17-31 equal the file. The question's "minimum temperature" has two fair readings:

- The file's min_temperature_c column holds the lowest TMIN (-18.8, -15.5, -9.3, -24.9), which the lanes also compute.
- The gold SQL takes the highest TMIN, following "each value represents the peak measurement".

The scorer checks only columns 1 and 3, so the minimum-temperature column, and with it this ambiguity, never affects the score. Verdict: `gold_right`.

## bq198

Lane 0 grouped by `name`, the team nickname, so "Tigers" (9) and "Wildcats" (9) pool several universities. Texas Southern alone has 5 and Kentucky 6 in the gold. Its counts (9, 9, 6, 6, 5) match no file's count column. The shared condition_cols [1] makes the scorer compare file b's column 1, which is b's nickname column (Bruins, Wildcats, Tigers, Quakers, Hilltoppers), and the scorer reports "matches bq198_b.csv". A list of nicknames with merged counts does not answer "top 5 universities", so lane 0 is wrong in substance and passes through a scoring defect.

Lanes 1-3 are right. Lanes 1 and 3 take the season maximum over all rows and match file a. Lane 2 takes it over rows with a name, which gives Penn and Fordham one more season each, and matches file d. Both readings of "excluding entries with missing team names" are fair, and the gold accepts both. Verdict: `scoring_defect`; strict and lenient [1, 2, 3].

## bq392

The three warmest days, 2009-10-30, 10-29 and 10-19 (54.5, 50.8 and 48.8 F), equal the file. Verdict: `gold_right`.

## bq229

40,231 cat URLs (label /m/01yrx at confidence 1) and 9,122,224 URLs with no /m/01yrx label at any confidence. Both equal both files, and the lanes match file b's one-row layout. Verdict: `gold_right`.

## bq161

The traces fix every count:

- 184 PAAD patients in the clinical table, of whom 174 appear in the mutation table.
- 90 have PASS-filtered mutations in both KRAS and TP53, 27 in KRAS only and 17 in TP53 only.
- 40 have neither among the 174, and 50 have neither among the 184 (k2 q8, q12, q14).

File a's 40 is the gold SQL's 90 - 50, which counts the 10 patients without any mutation record as having neither mutation. Lane 1 computes exactly that.

Lanes 0, 2 and 3 use the 174 patients with mutation data, and each submits with "the net difference ... is 50". They pass only because file a is a single value, 40, with empty condition_cols, and each of their tables contains a "neither" column equal to 40. That is a coincidental match on the wrong quantity, so under the gold's reading they are wrong.

The Nov 18 audit of the sibling question bq151 judged the 174-patient population a fair, even sounder, alternative, because a patient never sequenced is missing data rather than unmutated. Lane 2, which outputs net_difference = 50, is right under that reading. Lanes 0 and 3 output only the components and never the difference the question asks for, so they are wrong under either reading. File b's 39 matches no count in the traces; it harms no lane. Verdict: `scoring_defect`; strict [1], lenient [1, 2].

## bq116

The question asks "Which U.S. state reported the highest total annual revenue". Only the state is scored, and every lane names TX, as the file does. The lanes' revenue totals are about 11.5 times the file's: 21,374 billion for lanes 0-2 and 21,333 for lane 3, against 1,856.2. From their SQL, they appear to have summed every four-quarter value of the three tags in every FY2016 submission (9,620 TX rows in k1 q5), without restricting the period, the segment or duplicate filings. I read the question as asking for the state, with "in billions of dollars" describing the ranking measure. On that reading the labels stand. If the amount counted as part of the answer, the lanes would be wrong and condition_cols [0] would be a defect. Verdict: `gold_right`, medium confidence for that reason.

## bq126

The lanes apply the four stated filters, join images, and return one row per image: 32 rows. Fifteen of the 17 objects have two images. These rows equal file b in title, artist and URL. File a keeps one image per object (17 rows), and both granularities are accepted. Lane 3 also excludes 'Unidentified Artist' and blank names, which removes nothing. Verdict: `gold_right`.
