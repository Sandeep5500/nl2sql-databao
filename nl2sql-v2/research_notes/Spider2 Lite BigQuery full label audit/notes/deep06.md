# deep06 audit notes (Nov 19 2026)

Batch: bq326, bq327, bq328, bq399, bq234, bq235, bq354, bq102, bq103, bq445. Lane n = trace folder lane_k(n+1).
Pre-rewrite golds were read from the Spider2 submodule history (parent of commit 5fa8a517).

Verdicts: gold_right 5 (bq327, bq328, bq399, bq235, bq445), gold_wrong 1 (bq326), two_readings 3 (bq234, bq354,
bq102), scoring_defect 1 (bq103), unclear 0.

## bq326

The question asks how many countries grew more than 1% from 2017 to 2018 in both total population
(population_by_country) and current health expenditure per capita, PPP (SH.XPD.CHEX.PP.CD). Joining the two gives
76 economies (lane 2, q26), of which 12 are aggregates: EAR, IBT, LMC, LMY, MIC, WLD, SSA, SAS, TSA, TSS, PSS, SSF.
That leaves 64 countries. Lane 0 gets 64 with an explicit aggregate list, lane 3 gets the same 64 with an independent
filter (income_group IS NOT NULL), and both list all 64 codes, every one a sovereign state. File a (64) is right.
File b (65) has no SQL behind it (the pre-rewrite gold was 113). The only way the traces reach 65 is lane 2's: its
40-code exclusion list misses SSA, "Sub-Saharan Africa (excluding high income)" (population +2.68%, health +2.10%),
so 65 = 64 + one region. I mark file b wrong and remove lane 2 from both lists. Lane 1 (40) keeps only rows with an
empty special_notes field, a notes field that real countries also fill in (its visible rows skip KHM, KEN, CAN, PAK),
so it stays wrong. Confidence is medium because a different population source could in theory move one borderline
country, though nothing points to that.

Labels: official [0, 2, 3] -> strict [0, 3], lenient [0, 3].

## bq327

"How many debt indicators for Russia have a value of 0" asks for a count of indicators. File, gold SQL (DISTINCT over
indicator_name) and pre-rewrite gold all say 12, and lane 1's COUNT(DISTINCT indicator_code) = 12 lists the 12 codes.
Lanes 0, 2 and 3 count rows (672); lane 2's own breakdown shows the same 12 indicators with 56 zero rows each,
12 x 56 = 672. Counting indicator-year rows does not answer "how many indicators". Gold right, labels unchanged.

## bq328

All three files say North America (file a, region only, is also the pre-rewrite gold). Files b and c add medians that
come from different years: c's 1,607,402,450,990.09 equals lane 1's 2020 median exactly. Every lane puts North America
first, but every lane returns all 7 regions with their medians. The question asks "Which region has the highest
median GDP", which is one region; with condition_cols [] the 7-row vectors cannot equal the 1-row files. I treat a
full ranking as not answering a "which one" question (extra rows are a different answer, not formatting), so the
official "none right" stands. File a would pass any one-row answer containing "North America" whatever number sits
beside it, but no lane is affected.

## bq399

Lanes 0, 1 and 3 use world_bank_wdi and reproduce both files and the pre-rewrite gold exactly (Brunei 30.5327,
Greenland 20.66, Panama 28.6437, Oman 45.9702, United States 15.83, Seychelles 25.78). Lane 2 uses
world_bank_health_population and gets Cyprus 20.07, Bermuda 15.07 and Seychelles 23.58 for three regions. The question
names no dataset, so HNP could have been a fair source, but lane 2's North America answer cannot be right: the WDI
table in the same database puts the US 1980s average at 15.83, above Bermuda's 15.07, so the US is almost certainly
missing from the HNP series rather than revised. Lane 2 never checked. Gold right, medium confidence, because the HNP
data were never seen. condition_cols check only the rate column, not the country, which is harmless here.

## bq234

The gold groups by generic_name (active ingredient). Both files agree on shared rows (a: 50 states + DC; b: all 61
state codes), and the pre-rewrite gold also used generic names. Lanes 0, 1 and 3 group by drug_name instead. CMS
defines drug_name as "The name of the drug filled. This includes both brand names ... and generic names" and
generic_name as "the chemical ingredient of a drug", and says its state summary table is "organized by provider state,
drug name, and generic name". So ranking by drug name is a reading a careful analyst could choose, though merging the
brands of one ingredient is the stronger reading of "medication". The two readings differ: under drug_name, 15 states
change their top drug, all of them levothyroxine in the gold, because Synthroid-type brands split levothyroxine's
claims (CA: LEVOTHYROXINE SODIUM 3,844,722 by generic, HYDROCODONE-ACETAMINOPHEN 3,726,576 by drug name). The other 46
codes have the same drug under a different spelling and with lower counts. These figures combine group 0's visible
50 rows with the last 11 rows of lane 2's identical query. Lane 2 submitted a pagination query (state >= 'TX',
11 rows) and is wrong under either reading.

Labels: official [] -> strict [], lenient [0, 1, 3].

## bq235

Every file and the pre-rewrite gold name UNITY MEDICAL AND SURGICAL HOSPITAL (150177). Files a and b give 141,636.0,
exactly the lanes' 463.5 average outpatient payment plus 141,172.5 average inpatient payment. File c gives 105,305.19
from a discharge-weighted method, and Unity tops both; lane 1's trace shows it also tops when charges are used
instead of payments. Lane 1 returned the top 5 providers (5 rows) for "which healthcare provider", so its row count
matches no file, the same issue as bq328. condition_cols are lax (file a checks only the cost, files b and c only the
name) but harmless here. Gold right, labels unchanged.

## bq354

Three readings are in play. The pre-rewrite gold was 1.1599 / 2.6032 / 1.7188 / 1.3485 (acne, atopic dermatitis,
psoriasis, vitiligo), i.e. 26,990 / 60,573 / 39,994 / 31,378 of 2,326,856 persons. That is what the gold SQL computes
("Maps to" from the four ICD10CM category codes, then all concept_ancestor descendants) and exactly what lanes 0 and 3
return (2.6, 1.72, 1.16, 1.35). The current files (2.7794 and 5.8625 for atopic dermatitis and psoriasis; acne and
vitiligo unchanged) also map the subcategory codes L20.x and L40.x. Lane 1's trace shows these map to concepts outside
the category's SNOMED tree, e.g. L20.83 to Infantile seborrheic dermatitis. "Including their subcategories" supports
the files. But "include all related concepts mapped to the standard ICD-10-CM codes (L70 ..., L80) ... including
descendant concepts ... considering only the standard concepts and their related descendants" describes the gold SQL's
method, which is also the usual OMOP way to define a condition. So both are fair readings, and the rewrite dropped the
one the benchmark's own SQL takes, as in bq397 and bq151. Lane 1 maps subcategories but takes no descendants of the
standard concepts (59,381 / 133,637). Lane 2 divides by persons with any condition record rather than all
participants. Both are wrong under either reading. Scoring note: the name column is required, file a spells
"Atopic Dermatitis" and file b demands count columns, so a names-plus-percentages answer using concept names fails
both files even with the right numbers.

Labels: official [] -> strict [], lenient [0, 3].

## bq102

The gold SQL queries v2_1_1_genomes__chr17, and the pre-rewrite gold was its 48 positions. File a (184) contains all
48, plus exome positions absent from the genome answer, e.g. 41201180, which lanes 1 and 2 find in the exomes table,
so file a pools exomes and genomes. File b (166) is a subset of a, with 18 positions removed by an undocumented filter
(perhaps PASS-only). Lane 2 (exomes, SYMBOL = 'BRCA1', consequence containing "missense") returns 178 positions. In the
range it saw (50 rows, up to 41243030), file a equals lane 2's rows plus 41215925 and 41226347, both genome-answer
positions that an exome query cannot return; 184 - 178 = 6 fits genome-only additions. "Using data from the gnomAD
v2.1.1 version" does not say exomes, genomes or both, and the benchmark's own SQL used a single callset. So exomes-only
is a fair reading and lane 2 goes in lenient. Lane 1 matches Consequence = 'missense_variant' exactly and so drops
combined annotations like 41231350 (in lane 2 and both files). Lanes 0 and 3 use GRCh38 coordinates on GRCh37 data with
no missense filter. All three are wrong under any reading. Limit: full lane results were not stored, so the agreement is
shown on 28% of file a plus the row count.

Labels: official [] -> strict [], lenient [2].

## bq103

All four lanes have identical statistics: 5,604 variants, AC 7,917,038, AN 790,936,430, density 25,405 / 5,604 =
4.533369. These match every file (file b's 4.533547 is 25,406 / 5,604, inside 0.01). They differ only in the gene
column. The files themselves accept three spellings of the same set: "USP24,PCSK9", "PCSK9,USP24" and "PCSK9, USP24".
Lanes 0 and 3 return the string "PCSK9, USP24" and match file c. Lanes 1 and 2 return ARRAY_AGG(DISTINCT SYMBOL), the
same two symbols as an array, which the exact string comparison rejects. "Distinct gene symbols" is answered equally
by an array, so this is a scoring defect, and all four lanes are right.

Labels: official [0, 3] -> strict [0, 1, 2, 3], lenient [0, 1, 2, 3].

## bq445

The gold (3) is the smallest protein position of any missense annotation in the BRCA1 region, sorted numerically.
Lane 3 unnests all VEP annotations and gets 3 (then 3, 4, 5, 5, ...). Its narrower filter (BRCA1 only, exact
consequence) cannot raise a minimum that the files already put at 3. Lanes 0 and 1 read only vep[OFFSET(0)], the
first annotation per allele, and get 13; the question covers all "nested VEP annotations". Lane 2 fell back to an
INFORMATION_SCHEMA listing. The pre-rewrite gold was 10, consistent with sorting the string field as text ('10' < '3').
That would be a second reading, but no lane took it. File b holds the quoted string "\"3\"" and can never match, which
is harmless since file a accepts 3. Gold right, labels unchanged.
