# deep08 audit notes (Nov 19 2026)

Batch: bq087, bq088, bq089, bq407, bq425, bq430, bq023, bq094, bq075, bq406, bq199, bq218. Lane n = trace folder
lane_k(n+1). Pre-rewrite golds and scoring configs were read from the Spider2 submodule history (parent of commit
5fa8a517). No query was run anywhere; every data fact below comes from the files or from queries recorded in the traces.

Verdicts: gold_right 10 (bq087, bq088, bq089, bq407, bq425, bq430, bq023, bq075, bq406, bq218), two_readings 1
(bq094), scoring_defect 1 (bq199), gold_wrong 0, unclear 0. Only bq199 changes labels: [1, 2] -> strict and lenient
[0, 1, 2, 3].

## bq087

The question pools the weekly Anosmia values of the five New York City counties for 2019 and for 2020 and asks for
the percentage change. Lanes 0, 1 and 3 filter sub_region_1 = 'New York' and the five county names and get 573.4517,
which is file a, the gold SQL's pooled average and the pre-rewrite gold. Lane 2 checked the five counties inside New
York in its exploration, but its final query keeps only the county-name filter, so Richmond County (Georgia, North
Carolina, Virginia) and Kings County (California) enter both years (2019 average 0.0625, 2020 average 0.3585,
473.6%). That is a real error, not a reading. File b (575.19) has no visible derivation, but no lane is near it.

Labels: official [0, 1, 3] unchanged.

## bq088

The question asks for the 2019 and 2020 average anxiety and depression levels and the percentage increase between
them. Files a, b and d agree on 9.6179 / 6.0083 (2019), 9.8773 / 5.7806 (2020) and +2.697% / -3.790%; lane 3 returns
exactly these values and matches file d. Lanes 0 and 2 compute their "2019" columns as AVG over both years (the
column has no year filter), so they report 9.7476 / 5.8944 as the 2019 levels; their percentage columns filter the
year and happen to be right, but a requested value is wrong. Lane 1 makes the same mistake and also uses the two-year
average as the base, giving +1.33% / -1.93%. File c comes from integer-valued weekly scores (its averages are exactly
498/52, 514/52, 311/52 and 301/52, while the warehouse values sum to 500.13, 513.62, 312.43 and 300.59), so it is
another data version; it matches no lane.

Labels: official [3] unchanged.

## bq089

"The number of vaccine sites per 1000 people for counties in California" asks for one rate per county. The gold SQL,
files a and c (58 counties) and the pre-rewrite gold (57 counties) are all per county. All four lanes return one
statewide figure: 6,417 distinct sites / 39,148,760 people x 1000 = 0.1639. Those two totals are exactly the sums of
file a's site counts and populations, so the lanes computed the aggregate of the right answer instead of the answer.
I do not treat a single state figure as a fair reading, because the question names counties as the unit. File b is
wrong but harmless: its counts are file a's times exactly 10 (it counts catchment-boundary rows, 64,170 rows for
6,417 sites per the lanes' q2) and it leaves out the last 8 counties (FIPS 06101-06115).

Labels: official [] unchanged.

## bq407

All four files name Franklin MA (14.75%), Sussex NJ (14.24%) and Middlesex CT (13.35%; 1,438 cases and 192 deaths
for 162,742 people). Lanes 0 and 1 cast both FIPS keys to INT64 and match. Lanes 2 and 3 join
CAST(geo_id AS STRING) to the USAFacts county_fips_code; the census geo_id prints without a leading zero (6037 for
Los Angeles in lane 2's q2) while USAFacts pads it ('08057'), so no county in Connecticut, California, Colorado,
Arizona, Alabama, Alaska or Arkansas can join, and Steuben NY (12.54%) slides into third place. The pre-Nov-2025
gold was exactly that Steuben answer, so the rewrite fixed a real bug and lanes 2 and 3 reproduce the old one.

Labels: official [0, 1] unchanged.

## bq425

The question wants each SanofiAventis molecule's trade name with "the most recent approval date", keeping "only the
latest approval date per molecule"; only products_23.approval_date has several dated approvals per molecule. The
seven files agree on the same 100 molecules and the same dates; they differ only in which of two tied trade names
they print for molregno 453832 and 674569. Lanes 0, 2 and 3 use molecule_dictionary.first_approval, which is one year
per molecule and the earliest approval, not the latest (doxepin HCl, 1051125: 1969 in lane 2 vs 2016-01-20 in the
files). Their 141 or 532 rows of years answer a different question. Lane 1 is a fallback that lists 5 product rows
found by applicant name, which the question explicitly excludes. The pre-rewrite gold was the gold SQL's 43-row
output (it ranks across all companies before filtering on SanofiAventis); the current 100-molecule files apparently
filter first, which reads the question better. Neither version helps any lane.

Labels: official [] unchanged.

## bq430

Lanes 0, 1 and 3 cannot be right: lane 0 cuts its output to 20 rows, and lanes 1 and 3 are fallbacks whose submitted
result is a single count (809 and 568). Lane 2 is the only real attempt. Lane 1's count of 809 equals file b's row
count, reached with per-molecule counts in each assay (fewer than 5 activities, fewer than 2 flagged duplicates) and
one row per unordered pair. Lane 2 does the same but first removes every activity with potential_duplicate = '1', so
"fewer than 2 duplicate activities" becomes "none", and pairs that involve a molecule's single flagged activity
vanish: 729 rows, 80 fewer than file b. It also leaves out the canonical-SMILES UUID the question asks for. Under the
other reading (the gold SQL's assay-level count, which gave the 10-row pre-rewrite gold) lane 2 is wrong as well.

The files have their own problems, none of which touches a lane: files a and b store the UUIDs hex-encoded twice
(64 characters; '3061...' decodes to '0aec1188...'), which BigQuery's to_hex(md5()) never produces, and file a scores
that column; files c-e keep 179 of file b's pairs and call all of them 'no-change' although only 7 have equal values
(file d itself lists 0.018 vs 0.026 as 'no-change'), and file e scores that label. File b scores the A/B columns with
pairs oriented by activity id, so a correct answer oriented by molregno would also fail.

Labels: official [] unchanged.

## bq023

The five files take two defensible approaches. Files a-d apportion donations to tracts with the crosswalk ratios:
tracts that share one ZIP set still get different values (000200 / 001800 / 002000 = 104.29 / 138.74 / 70.32 in
file a). File e, which is the pre-rewrite gold, is an unweighted tract average like the lanes' (90.59 for all three).
Lanes 1-3 join FEC zip_code to the 5-digit crosswalk by exact string; New York donors have 195,916 distinct ZIP
strings (lane 2 q4), mostly 9-digit ZIP+4 codes that can never match, so a large share of donors silently drops out
and their values (tract 000100: 239.01 for lanes 1 and 3, 183.91 for lane 2) match no file. That is a join defect,
not a reading of the question. Lane 0 truncates to 5 digits and gets 254.598 for single-ZIP tracts such as 000100,
the same as files a and b, but it restricts ZIPs by county instead of restricting tracts, and returns 802 tracts, 44
of them outside Kings County (its own q5-q7 show the 44). File e's values fit 5-digit truncation with refunds kept
(just below lane 0's positive-only averages: 250.82 vs 254.60, 90.59 vs 92.10) and cannot come from an exact join,
with or without dropping negative amounts. Medium confidence because files c and d (217.79 for tract 000100) use an
unidentified filter.

Labels: official [] unchanged.

## bq094

The question can be read two ways. Literally, "committees that ... received a total amount of individual
contributions between $0 and $200" filters on each committee's total, and all six current files do that (224-294
committees, totals $1-$198). But "these small-dollar contributions sum to more than $0 overall" and "the total sum of
these small-dollar donations" describe summing each committee's contributions under $200, which is what the
pre-Nov-2025 gold did (1,532 committees; BARBARA LEE FOR CONGRESS 53,433). Both are fair, so two_readings.

No lane is right under either reading, so the lists do not change. Lanes 0 (1,399 rows) and 1 (1,476) take the
per-contribution reading but sum over the join with candidate_committee_2016, which repeats each contribution once
per linked candidate: lane 0's q10 shows 4-candidate committees at 236, 372 and 528, which are the old gold's figures
for SECURE OUR SENATE 2016, DCCC RAPID RESPONSE FUND 2014 and WOMEN MAKE THE MAJORITY 2016, and the current files give
those committees 59, 93 and 132, a quarter each (so the old gold had the same fan-out). Lane 1 also admits $200 gifts
against "less than $200" (HAL ROGERS FOR CONGRESS 4,299 vs 499). Lanes 2 and 3 sum committee_contributions_2016,
which holds committee transfers, not individual contributions, and return 4 rows.

Labels: official [] -> strict [], lenient [].

## bq075

All 11 files and the pre-rewrite gold give the same 4 x 6 table: Google overall hiring and overall representation from
the non-intersectional tables, and the two BLS industry groups, each with the Asian, Black, Hispanic/Latinx and White
shares and the women/men split. Lane 0 has the right Google and internet-publishing rows, but for "Computer systems
design and related services" it takes the whole "Professional and technical services" subsector (Asian 0.131 instead
of 0.237) and adds four race-by-gender rows. Lanes 1-3 read the intersectional tables, which give race shares within
each gender (hiring: women Asian 15.2%, men Asian 27.7%), and never state the overall race shares or Google's
women/men split; lane 3 has no gender column at all. The question asks for the race and gender distributions next to
BLS figures that exist only in non-intersectional form, so the files are right and every lane is wrong.

Labels: official [] unchanged.

## bq406

The question asks for growth rates from 2014 to 2024; the gold SQL defines a growth rate as (end - begin) / begin, and
all four files give the 2024-based rates (Asians +45.08%, Black people +137.5%, White people -29.77%). The warehouse
table the agents queried ends in 2022 (MAX(report_year) = 2022 in lanes 0, 1 and 3), so every lane substituted 2022,
and every lane also subtracted the shares (Asian 0.432 - 0.315 = 11.7 points) instead of dividing. Even with 2022 as
the end year the growth rate would be 37.1% for Asians, so the lanes are wrong whatever end year is used. The gold
is not at fault for the missing year: the pre-rewrite files, back to Dec 2024, already held these 2024-based rates,
so the table had 2024 rows when the gold was made and has lost them since. On today's warehouse no answer can match
any file, so this question is unanswerable as scored and is worth flagging separately.

Labels: official [] unchanged.

## bq199

Lanes 1 and 2 average state_bottle_retail per liter by category name and match file e exactly. Lanes 0 and 3 use
sale_dollars / volume_sold_liters, which drops returns (non-positive volume) and divides the stored order totals.
Their ten categories and their order are identical to file e's, and for the six categories whose name has one code
their 2019-2021 values equal file c's to every printed digit (WHISKEY LIQUEUR 87.97801 / 194.19180 / 174.76841,
TENNESSEE WHISKIES 51.96710 / 81.42801 / 97.68531, ...). So file c uses exactly their metric, but groups by category
code, which splits TEMPORARY & SPECIALTY PACKAGES into two codes and changes the top 10; file e uses their grouping
with the other metric, and the gaps (up to 1.94, WHISKEY LIQUEUR 2020) are far beyond the 0.01 tolerance. The
maintainers accept both metrics and both groupings, just not this combination, so lanes 0 and 3 are rejected for a
gap in the files rather than for anything in substance. Medium confidence, because it treats file c's metric as
genuinely accepted rather than as a lenient patch; I see no reason to doubt it, since per-transaction dollars per
liter is a literal reading of "per-liter retail prices across all sales transactions".

Labels: official [1, 2] -> strict [0, 1, 2, 3], lenient [0, 1, 2, 3].

## bq218

The files accept two meanings of "item". Files a and b key by item_number, which puts 73729 (EVAN WILLIAMS, $7.50 to
$8,290.80, +110,444%) and 43086 (BACARDI, +11,825%) in the top 5; the two files print different descriptions for both
numbers, so each number carries two descriptions in the data. Files c and d key by item_description like the gold
SQL, which merges special-order item numbers and brings in SOOH EL TESORO ANEJO ($360 to $19,800, +5,400%). All four
lanes group by the pair (item_number, item_description): the two renamed numbers break into one-year fragments and
the special-order rows stay apart, so their fifth item is LICOR 43 CHOCOLATE (+4,157%), which is sixth by description
and further down by item number. I count the pair key as an implementation side effect, not a third reading: lane 1
explicitly treated "item_number/item_description" as one identity and never noticed a number with two descriptions.
This is borderline, since the gold already accepts two item keys, hence medium confidence; a lenient labelling that
accepted the pair key would add all four lanes. Whether returns are dropped (lanes 0-1) or kept (lanes 2-3) does not
change the five items.

Labels: official [] unchanged.
