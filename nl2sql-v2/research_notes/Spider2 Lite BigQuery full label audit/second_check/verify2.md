# verify2: second check of strict label changes (Nov 19 2026)

Decisions: 7 confirm (ga004, bq198, bq461, bq108, bq290, bq419, bq162), 2 refute (ga031, bq067), 0 adjust.

How I checked: I re-ran Spider2's comparison function (a local copy of `compare_pandas_table` /
`compare_multi_pandas_table`, no cloud imports) on each lane's submitted result as stored in its trace (the
`submit_result` query id). I read the full lane traces and the gold files, and used the Spider2 git history for
pre-rewrite golds. For bq108/bq067 I read the official NHTSA manual (DOT HS 811 530). Helper scripts are in the scratchpad
folder `verify2/`.

How to read `lenient_ok`: when a change adds lanes, `true` means those lanes are right under a fair other reading. When
a change removes lanes (bq198, bq108, bq419), `true` means the removed lanes are also wrong under every fair reading, so
the lenient list equals the first auditor's list. Each JSON object also has an explicit `lenient_right_lanes` field.

**bq108 and bq067 must be decided together.** Both questions filter on "more than one distinct person", and every lane,
plus every gold file except bq067's file e, counts that with `COUNT(DISTINCT person_number)`. I confirm the bq108
finding that this key is wrong. Applied consistently, the same finding means bq067's lanes 0 and 1 are not right in
substance, so I refute that change. If the person_number key were instead accepted as a fair reading, bq108's official
lanes [0,1,2,3] and bq067's lanes [0,1] (via the row cap) would both count in the lenient view.

## ga004 (deep01): confirm, strict [0,1,2,3]

- The question asks for one number, "the average difference in pageviews between users who bought something and those
  who didn't". condition_cols [] makes each file also require the two group averages.
- Lanes 1 and 2 submit only the difference: 45.37456967714961 and ...962, over 102,340 non-purchasers and 1,975
  purchasers (lane 1, q4).
- **Correction to the first auditor's evidence:** lane 3 submits 45.3653539640364, computed over users with at least
  one page view. Its q4 averages, 49.09316 and 3.72781, round exactly to file b's 49.09 / 3.73 / 45.37. So file b is
  that population rounded to two decimals, and it can be matched: lane 3's three values pass both files when run
  through the scorer.
- Scored on the difference column alone ([2]), lanes 1-3 pass both files. The pre-rewrite gold (Spider2 `5fa8a517^`,
  `ga004.csv`) was the single value 45.37456968100644, and the gold SQL returns only the difference.
- Lane 0 outputs all three values and passes file a. The rejection is a scoring defect: the setup requires columns the
  question never asks for.

## ga031 (deep01): refute, strict [] (official); lenient [0,1,2]

- File a is 1.221640 and file b is 1.200686. An exhaustive search over numerators up to 39 finds 14/1,146 and
  14/1,166, but equally 7/573 and 7/583 (and their multiples).
- What the traces show, identical in every lane (k2 q5, k4 q9): 2,606 sessions with page views, 805 with a 'Home' view,
  14 with 'Checkout Confirmation', all 14 also with Home.
- No trace counts sessions whose landing (first) page was Home, or Home page views on Jan 2. I also searched the other
  Jan 2 GA4 traces (ga007, ga013, ga018).
- The first auditor ruled out the landing-page reading only by assuming the numerator is 14. If 7 of the 14
  converting sessions began on Home, and 573 or 583 sessions began on Home, the files are that reading exactly.
  "Relative to those that landed on the Home page" read as the landing page is a fair reading, so a gold error is not
  established.
- Lanes 0-2 give 14/805 = 1.7391 (lane 2 rounded to 1.74). They are right under the "any Home view" reading, and would
  be strictly right if the denominators are page views. Lane 3 submitted the four counts only.

## bq198 (light3): confirm, strict [1,2,3]

- Lane 0 grouped by `name`, the team nickname; in its own trace (get_column_values) "Tigers" covers 1,545 team-seasons.
  Its result is Tigers 9, Wildcats 9, Bruins 6, Quakers 6, Hilltoppers 5. Its count column matches no file:
  [6,6,5,5,5] in a-c, [6,6,6,5,5] in d-e.
- Comparison file by file: lane 0 passes only file b, through b's column 1, which is the nickname column (Bruins,
  Wildcats, Tigers, Quakers, Hilltoppers). Lanes 1 and 3 pass files a and c; lane 2 passes d and e.
- With per-file columns [[1],[2],[1],[1],[1]], lane 0 fails every file and lanes 1-3 still pass.
- "Top 5 universities" is not answered by pooled nickname counts, so lane 0 leaves both lists.

## bq461 (deep04): confirm, strict [0,1,3]

- Wildcats running scores at the three Wildcats and-ones (9:34 and 2:22 of the first half, 4:08 of the second), as I
  read them from the files:
  - a/b/c/h: (16, 24, 60), the basket first
  - d/e/f: (15, 23, 59), the free throw first
  - g: (16, 23, 59), a mix

  So the gold treats the order of each basket and its free throw as free.
- I rebuilt the lanes' 75-row results from their previews.
  - **Lane 0** (submitted q5): 15 at 9:34 and 24 at 2:22. Its 4:08 rows appear only in a separate run (q7, basket
    first) and were never seen in the stored result. That does not matter: lane 0 fails every file with either 4:08
    order.
  - **Lane 3** (submitted q7): 16 and 24. Its separate run q8 has the 4:08 free throw first. With that pair flipped,
    the rebuilt result passes file a, so its official rejection implies 59 in the stored result.
- Both lanes match files a and d exactly on clock, team and description, and the multiset of Wildcats scores differs
  from file a by one value (lane 0: 15 vs 16; lane 3: 59 vs 60).
- Lane 1 breaks ties by event_id and matched file d. Lane 2 submitted rows 51-75 only, with the score as one string.
- Caveat: under strict basketball chronology (the free throw follows its basket) only files a/b/c are right and every
  lane is wrong. The official [1] fits neither standard. I follow the gold's own acceptance of both orders.

## bq067 (deep09): refute, strict [] (official); lenient []

- **The cap is real.**
  - Every lane's submitted preview ends "result exceeded the 5000-row cap and was truncated", and
    `nl2sql-v2/src/nl2sql/config.py` has `result_rows_max = 5000`.
  - The scored DataFrame is the stored, capped result (`tools.py`), and the gold files have 13,827-25,422 rows, so no
    submission could pass.
- **The first auditor's match evidence reproduces.**
  - Lane 0's q12/q13/q14 counts are 13,848 crashes; labels 11,614 / 2,234; speed levels NULL 8,096 / 3,661 / 1,324 /
    543 / 216 / 8. These equal files a and b.
  - All 12 of lane 0's preview rows are in file a, and a and b have identical value multisets on every column b checks.
  - All 15 of lane 1's preview rows are in file d; two of them (17/66 and 21/14) are absent from a, f and g.
  - Crash 17-170012 has body type 66 in both lane 1 and file d (14 in a/f/g).
- **The lanes' population is wrong.**
  - Every lane, and every 13,848-row file, keeps crashes with `COUNT(DISTINCT person_number) > 1`.
  - FARS numbers persons from 001 within each vehicle, and non-motorists separately (DOT HS 811 530, .32-.33; quoted
    under bq108). So the filter drops crashes with two or more people who share a number.
  - The gold's own file e has 25,422 unique crashes: all 13,848 of file a plus 11,574 more, 234 of them with 2+
    fatalities. Its labels are identical to file a on the shared crashes.
  - Files a and d disagree on 138 labels, all a=1 / d=0: crashes in which several fatal persons share a person_number.
- This is the flaw for which the bq108 change removes all four lanes, so lanes 0 and 1 are not right in substance, and
  the official [] stands under strict. No lane computed file e's population.

## bq108 (light3): confirm, strict []; lenient []

- Files: 16.32 = 1,401 / 8,584 (fatal person rows, k1 q2) and 15.38 = 1,320 / 8,584 (distinct fatal person numbers,
  k4 q3). The 8,584 denominator is the Jan-Aug crashes with more than one distinct person_number, out of 20,923 (k1 q3).
- The official manual, *2010 FARS Coding and Validation Manual*, DOT HS 811 530, general instructions:
  - ".32 For each vehicle, persons are numbered consecutively beginning with '001.' ... The driver does not have to be
    '001.'"
  - ".33 Persons not in motor vehicles are numbered consecutively beginning with '01.'"
- The schema the lanes saw says person_number is used with ST_CASE "(and sometimes the VEH_NO data element)".
- Crash 42-420702 has 2 fatal rows (k3 q1) but 1 distinct fatal number (k4 q1).
- So the denominator drops crashes with two or more people who share a number, and file b also merges fatalities.
- The corrected share was never measured. Estimate (not measured): using bq067's 2016 proportions (the distinct filter
  keeps 13,848 of 25,422 multi-person crashes; 2.0% of the dropped ones have 2+ fatalities), it would be about
  (1,401 + ~145) / ~15,760, or about 10%. That is far from both files.
- All four lanes use this key and leave both lists. Treating person_number as a person identifier is not a fair reading
  here, consistent with how the calibration audit treated USAF-only station keys (bq045, bq356).

## bq290 (deep03): confirm, strict [0,1,2,3]

- All four lanes submit 31 rows. Their 93 values equal file a's values rounded to one decimal (93 of 93, largest gap
  0.0497); 92 of 93 equal file d's.
- Each lane's SQL applies ROUND(..., 1), and the official comparison rejects them on the 0.01 tolerance alone. Against
  files b and c the gaps run up to 1.78.
- The question sets no precision, GSOD temperatures have 0.1 F resolution, and the lanes' logic is file a's: the
  average over stations of daily max, min and mean, records with 9999.9 excluded, US minus UK. The protocol lists
  rounding as a possible scoring defect, so the lanes count as right.

## bq419 (light2): confirm, strict []; lenient []

- All four lanes submit [24,336, 16,762, 14,064, 11,811, 8,941], the only column scored (condition_cols [1]). Lanes 0-2
  label the rows Te/Mi/Ok/Ne/Ka; lane 3 labels them TN/MI/OK/NE/KS.
- `state` is documented as "The full text state name where the event occurred". The k4 trace shows two-letter
  truncations instead: Te has FIPS 47 and 48; Mi 26-29; Ne 31-36; Ma 23-25; Ar 4-5; Al 1-2; Co 8-9; No 37-38; So 45-46
  (q1, q2, q5).
- Single-FIPS counts for the top five are 21,656, 14,064, 8,941, 6,454 and 5,605 (q3). q12 puts 6,454 in FIPS 4 or 5:
  the pooled Ar group is 7,193, and every other pooled group that could hold it is below 4,990.
- The pre-rewrite gold was the same pooled output. The files rank groups of up to six states, which contradicts "which
  5 states", and no lane gives per-state counts.

## bq162 (deep09): confirm, strict [0,1,2]

- All five files agree on the substance: CODEX, H&E and IMC with Level2 only. Lane 3's q37 supports this: 0 Level3 or
  Level4 imaging records derive from WUSTL Level2 files.
- Lanes 0-2 submit exactly the three assays with "Level2", and the comparison rejects them against all five files:
  - a needs a constant "HTAN WUSTL" column
  - b and d need Yes/No or True/False flag columns
  - c needs the JSON text `["Level2"]` (with line breaks)
  - e needs "ImagingLevel2" plus the center column
- Adding a constant center column makes the same answer pass file a. The center is a filter, not a requested output, so
  this is a scoring defect.
- Lane 3 submitted an empty table (q34) and stays wrong.
