# verify3: second audit of strict label changes

Batch: bq112, bq019, bq086, bq432, bq034, bq103, bq199, bq227, bq169. Result: 7 confirmed, 2 refuted (bq112, bq227), none adjusted.
Method: I read the packets, the first auditor's entries, the gold files, the old gold versions in the Spider2 git
history, and the lane traces. Each check reran the scorer's comparison in `python3 -I`. Helper scripts are in the
scratchpad folder `verify3/`.

## bq112: refute (strict stays none; lenient_ok)

- I confirmed that `condition_cols` is `[]`, so a lane must reproduce every column of a file, including the yes/no:
  file a is (True, 76.3, 57.07) and file b is (76.30, 57.07, Yes). The Dec 2024 gold (git f8be2c66) held only the two
  rates (76.3, 57.07).
- Lanes 2 and 3 return (76.3, 57.07). Their submit text says the wages "kept pace", but the submit text is not scored.
  Lane 0 used geoid 42079, a code it picked from an unnamed list (lane 2 found that Allegheny is 42003). Lane 1 used
  the U.S. city-average, seasonally adjusted, December CPI.
- Why I refute: the question explicitly asks "did ... keep pace", so the files answer the question, and the scorer is
  right to require that column. An answer that leaves out a requested part is not clearly right in substance. The
  yes/no does follow from 76.30 > 57.07, and the old gold accepted the two rates alone, so lanes 2 and 3 are right in
  the lenient view.

## bq019: confirm (strict and lenient empty)

- All four lanes group by `provider_city` only. Their q2 lists NEW YORK 6346, BOSTON 3957, SPRINGFIELD 3540 and
  BALTIMORE 3176, and every lane's official match is file d (scored column [2]).
- Files a and c, and file b (which is the Dec 2024 original, git ef559e1c), group by city and state. They rank
  BALTIMORE MD third at 3176, and their NY and Boston payment values equal the lanes' to 15 digits.
- So no single Springfield has more than 3176 discharges. File d's 3540 (weighted payment 15,290.64) must pool
  Springfields from at least two states. That is not a city. A careful analyst would not group by name alone, so
  lanes 0-3 are wrong in the lenient view as well.

## bq086: confirm [0, 1, 2], with a correction

- I confirmed that file e's condition column [3] is `population_2018`; the percentage is column 4. I rebuilt the
  lanes from the gold values, with Canada set to 0, and reran the scorer. It reproduces every official outcome: lane 1
  matches file e on population only, lane 2 matches file b, and lane 0 matches nothing.
- **Correction to the first audit:** with the condition column fixed to [4], lane 0 would still fail file e. Files e
  and f give Canada 55,458 cases (0.149648%). Today's table gives 0: lane 3's q15 shows Canada with 0 cumulative
  cases, files a-d also have 0, and lane 2 can only match file b if Canada is 0. That one value leaves two sorted
  positions 0.0129 apart.
- Lane 0 is still right in substance:
  - Its 212 non-null rows are lane 2's rows, which match file b.
  - Its one extra row is Macau with a NULL percentage. File e and the Dec 2024 gold SQL output also contain that row.
  - No file combines the Macau row with today's Canada value, so a correct answer has nothing to match.
- Lane 3 builds its own alpha-2 to alpha-3 mapping, keeps 205 rows and loses real countries, so it stays wrong.

## bq432: confirm [0, 1]

- The flat `condition_cols` [2, 4, 6] include a JSON-text array in every file:
  - a: `outcomes`
  - b: `outcomes_array` and `products_brand_array`
  - c and d: `reactions_array`

  Lanes return arrays as `['Other Outcome']`. The May 2025 gold stored the same arrays as numpy text
  (`['ABDOMINAL DISCOMFORT' ' DIARRHOEA' ...]`), which shows the format comes from the export, not from the answer.
- With the arrays parsed:
  - Lane 1's 12 visible rows equal file a on outcomes, industry code (02 reads as 2) and industry name. File a's 28
    multi-outcome rows have no leading spaces, which is what `SPLIT(', ')` produces, and its two comma industry names
    use " -- ".
  - Lane 0's 47 visible rows equal file c on date_started, consumer_age and reactions. Files c and d keep the leading
    spaces that `SPLIT(',')` leaves, and c equals d on all three scored columns.
- No brand name in a, c or d has a digit-comma-digit pattern. So lane 0, which ignores the pattern rule, still gives
  the same output.
- Lanes 2 and 3 fail even with parsed arrays. Their outcomes keep leading spaces, which file a does not, and they
  have no consumer_age column for files c and d.

## bq034: confirm [1, 3]

- Current file a has exactly the 445 IDs, in the same order, of the Nov 2024 gold (git f8be2c66), which was the gold
  SQL's output with dist_meters.
- The May 2025 file had 457 stations: all 445 plus 12 newer CoCoRaHS stations. The Nov 2025 rewrite deleted it, and
  file b is now the first 100 sorted IDs of file a.
- Lanes 1 and 3 compute great-circle distance with R = 6371 km. On the 48 visible stations they share with the May
  2025 file, the distances are within 0.021 m of the gold's `ST_Distance`.
- Their nearest 50 stations are file a's first 46, in the same order, plus four newer stations: 0438, 0421, 0426 and
  0455. Station 0421 (8,215.12 m) and station 0426 (9,569.85 m) are already in the May 2025 file. The gap between 462
  and 445 stations is therefore new stations, which meets the specific evidence the live-table drift class requires.
- Lane 0 (no cos(latitude), 358 stations) and lane 2 (50 miles, 944) stay wrong.

## bq103: confirm [0, 1, 2, 3]

- All four lanes give 5604 variants, allele count 7,917,038, allele number 790,936,430 and density 4.533369
  (25405/5604). File b's 4.533547 is 25406/5604 and file a's 4.5335 is rounded; both are within 0.01.
- Lanes 1 and 2 fail only on the gene column, which they return as an array. Joining the array with "," makes lane 1
  match file a and lane 2 match file b; joining with ", " makes lane 2 match file c.
- The three files already accept three spellings of the same two-gene set, so the array container is only format.

## bq199: confirm [0, 1, 2, 3]

- Lanes 1 and 2 match file e.
- Lane 0 divides sale_dollars by volume_sold_liters, keeps only positive volumes and groups by name. Lane 3 is the same
  rounded to 2 decimal places. For the six names with a single code, their 2019-2021 values equal file c's: lane 0
  within 6e-14, lane 3 within 0.005.
- Lanes 0 and 3 also return file e's ten names in file e's order, but their values differ from file e's by up to 1.94.
- Pooling codes by name moves both metrics the same way. For AMERICAN CORDIALS & LIQUEURS 2021, going from file a to
  file e changes the value by -0.617, and going from file c to the lanes changes it by -0.619.
- So the lanes combine the metric of accepted file c with the grouping of accepted file e, and no single file holds
  that combination. This is the coverage gap the Nov 18 audit counted as a scoring defect for bq055.

## bq227: refute (strict stays [1]; lenient_ok)

- Parsing lane 0's strings gives all 45 shares of the file. Lane 1 matches the file directly.
- Why I refute: lane 0 puts each year's five shares into one text column, with the category order changing by year.
  The question asks for "percentage shares, rounded to two decimal places", and the file has five numeric columns.
  Putting numbers inside a string changes the structure of the answer, not just column names or order, so the
  rejection is not a clear scoring defect. Each year's row does hold every share, labelled, so lane 0 counts in the
  lenient view.
- Lane 2 returns one combined share per year, and lane 3 returns 2008 only. Both stay wrong.

## bq169: confirm [0, 1, 2, 3] (medium)

- **The gold is an old snapshot.**
  - All four files hold the same 119 clones, with a highest RefNo of 17942.
  - File d lists all 139 segment combinations. They are the same combinations as in the Dec 2024 original.
  - File c always takes the lowest start on each chromosome.
  - The May 2025 file, deleted in Nov 2025, had file d's rows plus three rows from newer references (18540/2/1
    twice, 18577/182/1).
  - The lanes' region queries show many rows with RefNo up to 18748.
- **The lanes' logic matches the gold's.**
  - Of the 76 clones visible in any lane's triple-match query, 74 are gold clones. The other two, 18577/182/1/2 and
    18748/319/1/1, come from newer references.
  - All 50 visible rows of lanes 0 and 2 are rows of file d, with identical karyotypes.
  - Lane 1's 12 visible rows are rows of file d. Eleven are also rows of file c; the twelfth differs only in a tied
    chr11 segment that c's scored columns do not check.
  - Inclusive overlap (lane 2's q4) and strict overlap (lane 0's q17) both give 124 clones.
- **Why medium:** three of the five extra clones never appear in a trace, though 18540/2/1 from the May 2025 file
  probably accounts for one or two of them.
- Without the new clones, lanes 0 and 2 match file d, lane 1 matches files b and c, and lane 3 matches file b.
  File b scores only RefNo, CaseNo and karyotype, so lane 3's packed segment strings do not matter.
