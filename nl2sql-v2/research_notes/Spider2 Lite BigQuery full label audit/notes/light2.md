# Light review, batch light2 (21 questions)

All 4 lanes match an accepted gold file in every question. 19 are `gold_right`. In 2 questions (bq019, bq419) the shared answer is wrong in substance, because the file the lanes match counts several distinct places as one. In both cases all four lanes leave the right lists.

## bq019

The question asks for the DRG with the most 2014 discharges (DRG 470) and, for "the top three cities" by discharges for that DRG, their discharge-weighted average total payments. Files a, b and c, and the original pre-Nov-2025 gold, group providers by city and state: New York NY 6,346, Boston MA 3,957, Baltimore MD 3,176, with Baltimore's weighted payment at 23,055.97. File d groups by city name alone, so its third row is SPRINGFIELD with 3,540 discharges and 15,290.64. Because Baltimore MD is third in files a-c at 3,176, no single Springfield reaches 3,176, so file d's 3,540 must add up Springfields in at least two states (the CMS data has Springfields in MA, IL, MO, OH and elsewhere). All four lanes ran `GROUP BY provider_city` (k1 q2 shows NEW YORK 6346, BOSTON 3957, SPRINGFIELD 3540, BALTIMORE 3176), and their output matches file d only. A pool of same-named cities in different states is not a city, and the schema gives provider_city and provider_state as separate fields. This is the same error as merging stations that share a placeholder ID, which the Nov 18 audit treated as wrong (bq045, bq356). Verdict: `gold_wrong` (file d is too lax); strict and lenient: none. I rate confidence medium, not high, because it rests on judging the name-only grouping unfair, and the maintainers added file d on purpose. The merge itself is certain.

## bq172

All lanes find AMLODIPINE BESYLATE as NY's top drug by claims (2,606,392, ahead of simvastatin at 2,483,824) and list CA, FL, NY, TX, PA with claim counts and costs equal to file a. File b has the same states with slightly more claims (0.04-0.13%) and noticeably higher costs (0.8-2.4%). That pattern fits matching by generic name, which adds the brand product, but this is an inference. Either variant is fair, and the lanes match the plain drug_name reading. Verdict: `gold_right`.

## bq177

The question gives the exact formulas. The lanes identify provider 330101 (NEW YORK-PRESBYTERIAN HOSPITAL, 1.92 billion over 2011-2015, k1 q1) and compute per-row averages per year for inpatient and outpatient costs. All ten numbers equal both files to the printed digits. Verdict: `gold_right`.

## bq355

Quinapril users number 229,876 of 2,326,856 persons, so 90.1207% do not use it. The lanes found the users through drug_strength's ingredient column instead of the gold SQL's concept_ancestor, and the count is the same. Three lanes rounded to 90.12, which is 0.0007 from the gold and within tolerance; rounding is not an error in substance. Verdict: `gold_right`.

## bq032

Track lengths from consecutive-point ST_DISTANCE: Paulette 11,394 km, Teddy 7,080 km, Laura 6,698 km (k1 q9). Both Paulette and Teddy became hurricanes, so reading "hurricane" strictly changes nothing. Teddy's last point (2020-09-24 06:00 UTC, extratropical) is at 52.8 N, the gold value. The gold SQL's `name != 'NOT NAMED'` filter matches nothing, because the data spells it NOT_NAMED, but this is irrelevant here. Verdict: `gold_right`.

## bq042

The lanes' ten yearly rows for station 725030 on June 12 equal both files exactly. The gold SQL replaces the 9999.9 and 99.99 missing-value codes and the lanes did not; since the values agree, no such code occurs on those days. Verdict: `gold_right`.

## bq357

The lanes average wind speed per location and day over icoads_core 2005-2015, excluding missing speeds, and return the same five rows as files b and c. Only latitude and longitude are scored. File a's speed column is ten times smaller than the others' (5.25 against 52.5), but that column is not scored. Verdict: `gold_right`.

## bq419

The storms tables' `state` column, documented as "The full text state name where the event occurred", actually holds two-letter truncations. The k4 trace lists the (state, FIPS) pairs: Te covers FIPS 47 and 48 (Tennessee and Texas), Mi covers 26-29 (Michigan, Minnesota, Mississippi, Missouri), Ne covers 31-36 (Nebraska, Nevada, New Hampshire, New Jersey, New Mexico, New York), and Ma, No, So, Ar, Co and Al also cover two or three states each. Every gold file scores the pooled totals [24,336, 16,762, 14,064, 11,811, 8,941]. File a labels the Tennessee+Texas total "TX" and file b uses "TE" and "KA", which are not state abbreviations. Counting by state_fips_code (k4 q3, a GROUP BY state_fips_code query) gives the five largest single states as 21,656 (one of FIPS 47/48, almost certainly Texas), 14,064 (Oklahoma), 8,941 (Kansas), 6,454 (FIPS 4 or 5, most likely Arkansas) and 5,605 (Louisiana). Lanes k1-k3 output the raw truncated values. k4 found the FIPS codes but then mapped 47/48 to TN, 26-29 to MI and 31-36 to NE, which reproduces the pooling. The question asks which "states" had the most events, so a count that pools up to six states does not answer it, and no careful analyst would accept "Te" as one state. Verdict: `gold_wrong`, high confidence; strict and lenient: none. The corrected answer would score [21,656, 14,064, 8,941, 6,454, 5,605]. The "top 1000 states each year" clause is a no-op.

## bq006

Daily counts peak at 19 (Jan 1), 16 (Mar 13) and 15 (Feb 7), so second place is unique. A z-score preserves the order of the counts, so how the mean and standard deviation are defined (with or without zero-count days) cannot change the answer, 2016-03-13. Verdict: `gold_right`.

## bq279

Station status exists only as a current snapshot, so the only workable reading is the one the gold SQL and lanes share: stations that started trips that year, split by their status. That gives 2013: 10 active / 1 closed (11 stations) and 2014: 38 / 9 (47 stations), equal to file a. File b is the same data in long form. Verdict: `gold_right`.

## bq281

The lanes get 201 rides (2023-10-13) by grouping on DATE(start_time) with the stated filters. That is file b, the original pre-Nov-2025 gold, and what the gold SQL computes. File a's 210 is not reproduced anywhere; it may come from a different time zone or a later data snapshot. Accepting it harms no lane. Verdict: `gold_right`, medium confidence, because whether start_time holds local or UTC time is not documented.

## bq025

The ten countries, under-20 counts and midyear totals equal the file exactly (Niger first at 12,498,275 of 21,151,442). The lanes' unrounded percentages are within 0.005 of the file's two-decimal values. Verdict: `gold_right`.

## bq060

Syria 61.46, Luxembourg 15.52, Qatar 14.61, in the lanes and files a-d. The net_migration column is itself a rate per 1,000, so ranking by it and reporting it as the migration rate fits the wording. The config has only 4 condition_cols entries for 5 files, so file e (rates as percentages) is never checked, which does no harm here. Verdict: `gold_right`.

## bq115

Uganda has the highest under-25 share in 2017 (69.146%) in both lane groups and both files. Only the name is scored. Verdict: `gold_right`.

## bq059

The lanes accept trips with either end in Berkeley; the gold SQL requires both ends. Both give 8.2 m/s, so the fastest qualifying trip lies within Berkeley and the readings agree. Verdict: `gold_right`.

## bq081

The latest 2014-2017 trip per region, with region taken from the start station, is identical in the lanes and the file for all five regions. Verdict: `gold_right`.

## bq400

The lanes and the gold (unchanged since before Nov 2025) give Geary + 33rd Avenue 00:00:00 / 23:41:06 and Presidio Avenue 07:35:00 / 20:31:06. One caveat: the Geary departures at 00:00, 00:20, 00:40 and 01:00 (k2 q6) are probably after-midnight runs. The table documents departs_next_day and arrives_next_day flags, and no lane checked them. Under a service-day reading those runs would be the last departures, not the first, and the latest arrival would fall after midnight. The question asks for clock times, and the literal minimum and maximum are a fair answer; no lane took the other reading, so the labels do not change. Verdict: `gold_right`, medium confidence.

## bq061

Tract 06081609601 (San Mateo County; +96,643 in median income, 2015 to 2018) is the answer in every lane and both files. The lanes give the full GEOID (file b) rather than the 6-digit tract code 609601 (file a). That is a format difference for the same tract. Verdict: `gold_right`.

## bq338

The same three Brooklyn tracts (36047055500, 36047051500, 36047003300) appear in all lanes and the file, with matching population and income ranks. The RANK and ROW_NUMBER variants agree. Verdict: `gold_right`.

## ga003

The average quick-play completion scores by board on 2018-09-15 (L 34.169, M 28.182, S 20.471) equal both files. Verdict: `gold_right`.

## ga025

The lanes' 2.45% is 8 crash users out of 327 September first-openers who uninstalled within 0-7 calendar days. It matches file b (2.446483) and the original gold (2.44648318). k4 converted timestamps to dates as the question instructs and got the same 327 and 8, so the event_date shortcut the other lanes took makes no difference. The other files correspond to 10/356, 8/324 and 10/351 (derived from their values) and come from definitions no trace reproduces. Accepting them harms no lane. Verdict: `gold_right`, medium confidence.
