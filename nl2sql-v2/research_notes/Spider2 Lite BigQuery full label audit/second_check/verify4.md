# verify4: second-auditor checks (Nov 19 2026)

Batch: bq202 (deep05), bq360 (deep11), bq161 (light3), bq186 (deep11), bq376 (deep09), bq120 (light1),
bq326 (deep06). Result: **7 confirm, 0 adjust, 0 refute.**

Every claim the first auditor relied on was rechecked against the gold files, `spider2lite_eval.jsonl`, the
four lane traces and the Spider2 git history. Every scoring claim was also rerun with a standalone copy of the
comparison logic in `nl2sql-v2/src/nl2sql/eval.py`, applied to the lanes' submitted results and to edited
("counterfactual") versions of them. The helper scripts are in the scratchpad folder `verify4/`.

## bq202: confirm, strict [0]

- Files: a = (4, 18, 1943), b = (4, 18, 1944); condition_cols [0, 1] score day and hour only.
- Lane 0's full slot table (k1 q3): (5, 18) = 1,943 is the unique maximum, and (4, 18) = 1,824. The gold's count
  therefore belongs to lane 0's slot, Thursday 18:00 in BigQuery numbering. A gold made with BigQuery numbering
  would have picked (5, 18), not (4, 18) with 1,943 trips.
- Lane 1's check (k2 q2): Monday 2018-01-01 returns 2, so BigQuery numbers 1 = Sunday and 5 = Thursday. The files'
  4 is Thursday under 0 = Sunday or ISO (Monday = 1) numbering.
- Official comparison: lane 0 fails both files as submitted and passes both once 5 is renumbered to 4. The question
  ("which numeric day of the week") fixes no numbering, so this is a convention, not substance. The reference
  report treats bq002's week start the same way.
- Lenient: the pre-Nov-2025 files were all (3, 17), the busiest day and busiest hour taken separately (git
  `ef559e1c`). Lanes 1-3 return exactly that, so lenient [0, 1, 2, 3] is supported.

## bq360: confirm, strict [0, 1, 2, 3] (medium confidence)

- All four files are the full top-10 table (65, 44, 31, 29, 28, 23, 22, 21, 17, 14; average 29.4) and flag Family
  in four different spellings. condition_cols [] makes every column required.
- Lane 0's full list (k1 q15) matches the files' top 10 exactly, and 11th place has 11, so there is no tie at the
  cut. Lane 1 gets the identical result from the pre-joined `healthcare_provider_taxonomy_N_specialization`
  columns, an independent method. Lanes 0-2 return "Family, 29, 29.4, 0.4".
- Lane 3 counts primary taxonomies only (k4 q21-q22): 64, 39, 29, 28, 23, 22, 20, 16, 13, 12, average 26.6. These
  are the same ten names, and Family (28, difference 1.4) is closest.
- New evidence for the output-shape question: the question text in its current form was introduced on 2025-02-10
  (`07c88177`). Until the 2025-11-02 swap (`5fa8a517`), this wording was scored against the single cell
  `output: Psychiatry`. The old question was "Which of the top 10 ... has a specialist count closest to the
  average". The deliverable is the one specialization; the 10-row tables arrived only with the November files.
- Official comparison: all lanes fail all four files. All four pass a one-cell "Family" label, because extra
  columns are tolerated, so lane 3's 28 does not matter.
- Lane 3 is right on the deliverable under both counting readings. Medium confidence overall: if the project
  decides the top-10 list itself is required output, this becomes two_readings over output shape.

## bq161: confirm, strict [1]

- Files: a = 40, b = 39; condition_cols [] (one value).
- Lane 1's counts (k2): 174 PAAD participants in the mutation table (q7), 184 in the clinical table (q8), 174
  clinical patients matched (q12), both = 90 and neither = 50 over the 184 (q14), KRAS only = 27 and TP53 only = 17
  (q15). So 90 + 27 + 17 + 50 = 184, and neither = 40 within the 174.
- File a = 90 - 50 = the gold SQL's logic, which lane 1 returns (q16).
- Lanes 0, 2 and 3 all submit "the net difference ... is 50". Official comparison: each passes file a only through
  its "neither" column (40), and with that column removed none matches 40. That is a false accept.
- Lenient: against 50 (the 174-patient reading, which the reference report accepted as fair for sibling bq151),
  only lane 2 passes. Lanes 0 and 3 never output a difference. Lenient [1, 2] is supported.
- File b's 39 matches no count in the traces and affects no lane.

## bq186: confirm, strict [0, 1, 2, 3]

- Cell comparison (37 months, 4 scored columns): lanes 0-2 vs file d match 146 of 148. The misses are 201409 first
  (9.466667 vs 9.483333) and 201410 last (5.033333 vs 4.366667). Against files a-c the lanes differ in about 30
  cells each, because those files keep San Francisco stations only.
- Between files: a and c differ at 201409 first, 201410 last and 201510 first; b differs from a and c at 201401
  first. These files share one reading, so these splits are tie picks.
- Max and min match file d in all 37 months, so the lanes and file d share population and month boundaries. A
  different first/last pick can then only mean an equal start time. start_date is minute resolution: k1 q1 and k3 q4
  show three trips at 2013-08-29 09:24:00. The table is static (2013-2016), so data drift is not a factor.
- Official comparison: with the two cells set to file d's picks, lanes 0-2 pass file d.
- Lane 3: its SQL is the same ROW_NUMBER query over the same table, and its 12 visible rows match file d 48 of 48.
  Its deterministic columns must equal the other lanes', so its unseen rows can differ only in tie picks.

## bq376: confirm, strict [0, 1, 2, 3]

- File a: 117 rows. NUM_CRIME_INCIDENTS is 0 in every row, 55 rows have 0 stations, and 62 rows have stations
  (261 stations in total).
- Lanes: every neighborhood that appears in any lane's station queries has file a's station count, and together
  they cover all 62 station neighborhoods (261 stations). The lanes return 62 rows each, with at least 2,168
  incidents per visible row.
- Official comparison: the reconstructed 62-row result fails file a as shipped, passes file a restricted to its
  62 station rows (condition_cols [1] = station counts), and fails file b.
- File b equals the pre-rewrite gold and comes from the gold SQL's `bigquery-public-data.san_francisco.*` tables.
  `resource/databases/bigquery/san_francisco_plus` lists only the `san_francisco_bikeshare`, `_sfpd_incidents`,
  `_neighborhoods` and other `san_francisco_*` datasets, and its git history never contained the old dataset.
  The database's station table has South of Market at 30 stations; file b has 9.
- The lanes' crime counts differ only at Buena Vista (lane 3: 9,574 against 9,576), and crime counts are not
  scored.

## bq120: confirm, strict [0, 1, 3]

- Cook County (17031) has 30 rows on 2017-01-01 (k3 q7; k4 q4, q5, q17). The largest is COOK - NORTHERN at 47,549;
  12 rows are 0 (the first auditor wrote 13, which changes nothing). The rows sum to 480,564, which I re-added from
  q17. The top-20 listing (k2 q9) shows every other county with a single row.
- By county totals (k2 q14), San Diego (135,503, ratio 1.0222) is 11th. File d omits Cook and includes San Diego,
  which is what ranking single rows gives (lane 2's SQL, and the stale gold SQL's join without a sum).
- Official comparison: lanes 0, 1 and 3 match files a, b and c and fail file d; lane 2 matches only file d.
- Side observation, no label change: SNAP FIPS 12025 ("FL EBT DADE CO DFS", 400,341 households) does not join to
  the ACS geo_id 12086 (Miami-Dade), so every file and every lane drops it. Recoding an obsolete FIPS needs outside
  knowledge the question does not ask for, so this does not meet the strict bar.

## bq326: confirm, strict [0, 3]

- Files: a = 64, b = 65. There is no gold SQL, and the pre-rewrite gold was 113.
- Lane 2 q26 counts 76 economies meeting both criteria. Lane 3 lists all 76 (k4 q18-q19), and 12 are aggregates:
  EAR, IBT, LMC, LMY, MIC, PSS, SAS, SSA, SSF, TSA, TSS, WLD.
- Lanes 0 (k1 q19-q20) and 3 (k4 q29-q30) list identical 64-code sets. All are sovereign states, and Kosovo (XKX),
  which lane 0 excludes, is not among the 76.
- Lane 2's 40-code list misses only SSA among the 76's aggregates. Its 65 is 64 + SSA (+2.68% population, +2.10%
  health spending), a region counted as a country. Lane 2 is wrong on these data whatever produced file b.
- Lane 1's 40 (empty special_notes) drops real countries and stays wrong.
