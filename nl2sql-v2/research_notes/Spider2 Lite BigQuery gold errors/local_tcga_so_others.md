# Spider 2.0-Lite BigQuery gold labels: bq151 (TCGA), bq308 (Stack Overflow), bq424 (World Bank debt), bq055 (Google DEI), bq389 (EPA air quality)

Evidence tags used on every finding:

- **[file]**: read directly from local files (question JSONL, gold SQL, gold CSVs, eval config, schema JSONs, evaluator code) or from the git history of the `Spider2` submodule.
- **[trace]**: BigQuery output recorded in our Nov 17 2026 agent traces (data the agents saw). I ran no SQL against BigQuery or any other cloud service, and opened no credential files.
- **[sim]**: checked by running the official evaluator's own `compare_pandas_table` / `compare_multi_pandas_table` functions (extracted verbatim from `evaluate.py` with `ast`) locally on reconstructed predictions. Scripts are in `/private/tmp/claude-501/-Users-deepikapalagani-Documents-nl2sql-databao/f54a9a7d-52ac-46be-8abb-0cac5a1864b1/scratchpad/sim/`.
- **[doc]**: official web documentation.
- **[inferred]**: my reasoning from the above, not verified directly.

Path shorthands used in citations: `G` = `/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold`; `R` = `/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17`; `S` = `/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/databases/bigquery`. Git commits refer to the `Spider2` submodule at `/Users/deepikapalagani/Documents/nl2sql-databao/Spider2`; any old file can be shown with `git show <commit>^:<path>`.

The scoring rule, verified by reading `evaluate.py` [file]: each gold column (limited to `condition_cols`) must equal some predicted column. Numbers are compared with `math.isclose(abs_tol=0.01)`, and vectors are sorted first when `ignore_order` is true. Extra predicted columns are allowed, and matching any one gold file is enough. A flat `condition_cols` list is copied to every gold file (`evaluate.py` lines 71-74). If comparing any file raises an exception, the multi-file loop stops and scores 0 (lines 362-368) — [evaluate.py](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/evaluate.py).

## Overview: verdicts, confidence, and which lanes are right under a corrected label

### Takeaway
All five labels are flawed, in different ways. For bq151, bq308 and bq424, the gold SQL cannot produce any current gold file, because the CSVs were replaced on 2025-11-02 while the SQL was left as it was. bq424's original label also used the wrong World Bank indicator. bq055 accepts an inconsistent patchwork of formats. bq389's label is internally consistent, but its scoring config makes four of its seven gold files unusable, so our lane 1 (the right numbers in a long layout) is a false negative.

### Cited Findings
- **History of all five labels [file]**:
  - First gold CSVs: commit f8be2c66 on 2024-11-10 (bq308.csv, bq424.csv) and ef559e1c on 2024-12-12 (bq055.csv, bq151.csv, bq389.csv).
  - Gold SQL added for bq151, bq308, bq389 and bq424 by d72b6a2f ("add more gold SQL", 2025-02-27).
  - bq055 and bq308 got a second file in d79b85e9 (2025-05-22).
  - Commit 5fa8a517 ("update spider2lite eval", 2025-11-02) deleted the single files bq151.csv, bq389.csv and bq424.csv. It replaced them with the current multi-file sets, rewrote bq055_a/b and bq308_a/b, added the other files, and changed `condition_cols`. It did not touch `gold/sql/`.
  - Source: [Spider2 git history](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2) (`git log -- spider2-lite/evaluation_suite/gold/...`).
- **Same files in Snow [file]**: the current Lite gold CSVs are byte-identical to the Spider2-Snow copies (`sf_bq*.csv`). Spider2-Snow ships no gold SQL for any of the five tasks — [spider2-snow gold](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-snow/evaluation_suite/gold).
- **Per-lane scores, from all.csv [file]** — [R/lane_k1..4/all.csv](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17):
  - bq151: only k1 passes (file b).
  - bq308: only k3 passes (file d).
  - bq424: k1, k2 and k3 pass (file d).
  - bq055: k1 and k3 pass (file b).
  - bq389: k2 and k4 pass (file a).
- **Summary of verdicts** (detail and evidence in each instance section):

| id | Can gold SQL produce the current files? | Primary verdict | Secondary | Confidence | Pass now | Correct under my corrected label |
|---|---|---|---|---|---|---|
| bq151 | No: 1 column, 184-patient cohort, chi² 46.52 (this was the original gold) vs files with 6-10 columns, 174/155 patients, chi² 35.91/24.47 | (a) | (c) cohort reading; (d) every column required | high on (a), medium on which cohort is right | k1 | 174-patient label: k1. Either-cohort label: k1, k2, k4. Never k3 (formula bug) |
| bq308 | No: year 2020, inner join, 1-dp percent | (a) | (c)/(d) one-second boundary scored by exact counts; (e) for lane 1 | high | k3 | strict: k3; tolerant of ±1 s boundary: k2, k3, k4; never k1 |
| bq424 | No: DT.AMT.DLXF.CD (repayments), no SUM, IDS table (this was the original gold) | (a) and (b) for the original label | (d)/(c): file d accepts a stock summed over 51 years | high | k1, k2, k3 (via d) | latest-year stock: none of the four; with summing also accepted: k1-k3 |
| bq055 | no gold SQL exists | (d) patchwork | (c) signed vs absolute, fraction vs percentage points | high | k1, k3 | all four |
| bq389 | Yes (the SQL produced the original file) | (d) long-format files can never be matched | (c)/(e) VOC parameter reading | high on (d), medium on VOC | k2, k4 | k1, k2, k4 (k3 only if a 43102 reading is added) |

### Inferences
- [inferred] The common cause in bq151, bq308 and bq424 is that the Nov 2025 re-annotation replaced or extended the gold CSVs without updating or removing the gold SQL. Anyone checking labels by re-running the gold SQL would get answers the scorer now rejects.
- [inferred] Under corrected labels, the outcome changes for at least one of our lanes on every instance: bq389 k1 (false negative), bq055 k2 and k4 (false negatives), bq151 k2 and k4 (right under the gold SQL's own reading), bq424 k1-k3 (pass only through a lenient file), and bq308 k2 and k4 (a one-second convention).
- [inferred] For the earlier anatomy hypotheses: the bq151, bq308 and bq424 "SQL cannot produce files" claims are confirmed and extended. The bq389 "scorer difference" claim is technically true but changes no outcome. The real bq389 artifact is that long-format files are unscorable, which the earlier reading noted only for lane 3 and not for lane 1.

### Gaps
- The derivation of bq151_c (155 patients) and the exact boundary rules behind bq308 files a, b and c are not documented and cannot be reproduced without running SQL.
- I found no Spider2 changelog or issue text explaining the Nov 2025 edits. The commit message is only "update spider2lite eval".

## bq151 (pancancer_atlas_2): chi-squared for KRAS and TP53 co-mutation in PAAD

### Takeaway
Verdict (a), high confidence: the gold SQL contradicts the current gold files. The SQL computes chi-squared = 46.52 on a 184-patient clinical cohort and returns one column; this was the benchmark's original answer until 2025-11-02. The current files want a 174-patient mutation-table cohort (35.91) or an unexplained 155-patient cohort (24.47), and they require 6-10 columns. Secondary: (c) the question allows both cohort readings, and (d) a correct statistic-only answer can never pass. The "high-quality" `FILTER = 'PASS'` condition changes no patient's status.

### Cited Findings
- **Question [file]**: "Using TCGA dataset, calculate the chi-squared statistic to evaluate the association between KRAS and TP53 gene mutations in patients diagnosed with pancreatic adenocarcinoma (PAAD). Incorporate clinical follow-up data and high-quality mutation annotations to accurately determine the frequency of patients with co-occurring KRAS and TP53 mutations compared to those with each mutation occurring independently. Ensure that patient records are meticulously matched based on unique identifiers to maintain data integrity. ..." `external_knowledge` is null — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl).
- **Gold SQL, key lines [file]** — [G/sql/bq151.sql](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/sql/bq151.sql):
  - The cohort is `barcodes AS (SELECT bcr_patient_barcode ... FROM isb-cgc-bq.pancancer_atlas.Filtered_clinical_PANCAN_patient_with_followup WHERE acronym = 'PAAD')`.
  - Mutation status comes from `barcodes AS t1 LEFT JOIN (SELECT ParticipantBarcode FROM ...Filtered_MC3_MAF_V5_one_per_tumor_sample WHERE Study = 'PAAD' AND Hugo_Symbol = 'KRAS' AND FILTER = 'PASS' GROUP BY ParticipantBarcode)`, with `IF(t2.ParticipantBarcode IS NULL, 'NO', 'YES')`, and the same for TP53.
  - Pearson chi-squared is computed from expected counts, and the SQL ends with `SELECT ... AS chi_square_statistic`. The output is **1 row × 1 column**.
- **Gold files and scoring [file]** — [G/exec_result/bq151_*.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result) and [spider2lite_eval.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl):
  - `bq151_a.csv`, 1 row × 9 columns: Total 174, both 90, KRAS only 27, TP53 only 17, neither 40, frequencies 0.5172 / 0.1552 / 0.0977, chi² **35.90590051746639**.
  - `bq151_b.csv`, 1 × 6: 90, 27, 17, 40, 174, chi² 35.9059005174664.
  - `bq151_c.csv`, 1 × 10: 86, 27, 14, 28, **155**, expected 72.903226 / 40.096774 / 27.096774 / 14.903226, chi² **24.46996432500303**.
  - `condition_cols: []`, meaning every gold column must be matched; `ignore_order: true`.
- **Original gold [file]**: from 2024-12-12 (ef559e1c) to 2025-11-02, the only gold was `bq151.csv` = `output` / **`46.52221206`**. Commit 5fa8a517 deleted it and added a, b and c. The gold SQL (added 2025-02-27, d72b6a2f) was never changed — [Spider2 git](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2).
- **Patient counts from the traces [trace]**:
  - Clinical table: **184** PAAD patients (184 distinct barcodes, 184 rows) — [R/lane_k4/traces/bq151.json q11](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/traces/bq151.json).
  - Mutation table: **174** PAAD participants with 175 tumor samples, and all 174 are in the clinical table — [R/lane_k1/traces/bq151.json q3, q9](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k1/traces/bq151.json). Lanes k2 (q11) and k3 (q10) confirm 174/174.
  - Without any FILTER condition, KRAS patients number 117 and TP53 patients 107 (lane_k1 q10). On the 174 cohort the table is 90/27/17/40 with chi² 35.90590051746639 (lane_k1 q11, q14). On the 184 cohort it is 90/27/17/**50** (lane_k2 q8), chi² 46.52221206050192.
- **Effect of FILTER = 'PASS' [trace]**, from the sibling question bq161's traces:
  - PAAD KRAS rows are 119 PASS plus 1 `nonpreferredpair`; TP53 rows are 107 PASS plus 1 `nonpreferredpair`.
  - With the PASS filter, KRAS patients still number 117, TP53 patients 107, and both 90.
  - On the clinical cohort with PASS, the cells are both 90, neither 50, KRAS only 27, TP53 only 17 — [R/lane_k2/traces/bq161.json q2, q4, q5, q6, q14, q15](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k2/traces/bq161.json).
  - On the 174 cohort with PASS: 174 patients, 27 / 17 / 90 / 40 — [R/lane_k1/traces/bq161.json q6](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k1/traces/bq161.json).
- **FILTER column meaning [file]**: the table's column description reads: FILTER = "List of failed filters (if any), or "PASS" indicating the variant has passed all filters" — [S/pancancer_atlas_2/.../Filtered_MC3_MAF_V5_one_per_tumor_sample.json](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/databases/bigquery/pancancer_atlas_2/isb-cgc-bq.pancancer_atlas/Filtered_MC3_MAF_V5_one_per_tumor_sample.json).
- **"Filtered" tables [doc]**: ISB-CGC says the `Filtered_*` tables "were filtered using the Pan-Cancer Atlas whitelist (which is the list of TCGA barcodes included in the Pan-Cancer Atlas)" and that "Use of the tables starting with Filtered_* is recommended". The page names the MC3 MAF as an exception to the "unmodified uploads" description — [ISB-CGC Pan-Cancer Atlas BigQuery Data](https://isb-cancer-genomics-cloud.readthedocs.io/en/latest/sections/PanCancer-Atlas-Mirror.html).
- **Sibling question bq161 [file]**: bq161's gold SQL uses the identical template (clinical cohort, LEFT JOIN, `FILTER = 'PASS'`) and returns both minus neither. Its gold `bq161_a.csv` is **40** (= 90 − 50, the 184 cohort); `bq161_b.csv` is 39 — [G/sql/bq161.sql](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/sql/bq161.sql).
- **Our four lanes [file/trace]** — [R/lane_k*/traces/bq151.json](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17):
  - k1 uses the mutation-table cohort (174) with no FILTER and returns 14 columns (a, b, c, d, n, margins, expected counts, chi² 35.906). It matches b.
  - k2 uses the clinical cohort with a LEFT JOIN and returns a, b, c, d, total, chi² = 90, 27, 17, 50, 184, 46.522.
  - k3 uses the 174 cohort, but its expected count is `(SELECT kras_total FROM totals) * (...) / grand_total` for every cell, which gives the wrong expectation for KRAS-negative cells. It returns one column, 54.29378628067427.
  - k4 uses the clinical cohort and returns one column, 46.522212060501914. Its output-shape rubric said "A single row holding the chi-squared statistic".
- **Simulation of the official scorer [sim]**:
  - A one-column answer of 35.906 (the "right" number for files a and b) fails all three files. So do 46.522 and 54.29.
  - k2's six columns fail.
  - k1 passes b only; it fails a because it has no frequency columns.
  - A minimal answer with counts, n and chi² on the 174 cohort passes b.

### Inferences
- **What the gold SQL returns [inferred, near-certain]**: the SQL's cohort is the 184 clinical patients. Its LEFT JOINs make every one of the 10 patients with no mutation-table record a "NO/NO". Given the trace-observed PASS counts, its table is a = 90, b = 27, c = 17, d = 50, n = 184, so χ² = 184·(90·50 − 27·17)² / (117·67·107·77) = **46.5222**. That equals the removed original gold `46.52221206` to 8 decimals. The gold SQL therefore produced the original label.
- **Why it cannot produce the current files [inferred from static reading plus traces; verdict (a), high]**:
  - The cohort differs: 184 patients vs 174 (a, b) or 155 (c).
  - The statistic differs: 46.52 vs 35.91 or 24.47.
  - The shape differs: one column, while `condition_cols: []` requires all 6, 9 or 10 gold columns.
- **Two cohort readings, verdict (c) [inferred]**: "Incorporate clinical follow-up data" invites the clinical-table cohort used by the gold SQL, the original gold and bq161. "Patient records are meticulously matched based on unique identifiers" invites an inner join of clinical and mutation records. That inner join is exactly the 174 cohort, because all 174 mutation-table patients have clinical records.
- **Which cohort is better [inferred]**: the 174 cohort is the better statistics. A patient with no MC3 record at all was most likely not sequenced or not whitelisted for MC3, so counting them as "neither mutated" treats missing data as wild-type. So the current a/b content is the better answer, but it is not what the gold SQL or the sibling bq161 label encode.
- **File c [inferred, untested]**: the 155-patient file cannot come from the PASS filter, since PASS changes nobody's status. Compared with the 174 table, its 19 missing patients are 4 both, 0 KRAS-only, 3 TP53-only and 12 neither. That looks like a restriction on the cohort, for example by a clinical field, rather than a stricter mutation definition. Its SQL is unknown.
- **Shape requirement, verdict (d) [inferred]**: the first instruction is "calculate the chi-squared statistic". A statistic-only answer is a fair response, yet `condition_cols: []` rejects it against every file. File a additionally demands frequency columns, b demands counts and a total, and c demands expected counts.
- **Correct answer (my judgment)**: a 2×2 table on the 174 matched patients, 90 / 27 / 17 / 40, with Pearson χ² ≈ **35.906** (no continuity correction). The counts and frequencies are good to include, but they should not be required.
  - Under a corrected label that accepts this statistic with or without counts, only **k1** is correct.
  - If the label also accepted the gold SQL's 184-patient reading, **k2 and k4** (46.52) would be correct too.
  - **k3** is wrong under every reading because of its expected-count bug.
- [inferred] **Side note, outside my scope**: on bq161, lanes k1, k3 and k4 answered "net difference 50" yet passed `bq161_a.csv` (40). Their submitted tables also contained a "neither = 40" column, and the extra-column tolerance matched it.

### Gaps
- I could not determine what query produced `bq151_c.csv`, the 155-patient file.
- I could not confirm from documentation why 10 clinical PAAD patients are absent from the MC3 table (not sequenced vs excluded by the whitelist). The traces show only that they are absent.

### Plain-language explanation
The gold SQL takes all 184 PAAD patients from the clinical table and LEFT JOINs the mutation calls. As a result, 10 patients with no mutation record at all count as having neither mutation, which gives 90/27/17/50 and a chi-squared of 46.52; that was in fact the benchmark's original answer. In November 2025 the answer files were replaced with versions built only from patients who appear in the mutation table (174 patients, 90/27/17/40, chi-squared 35.91), plus an unexplained 155-patient variant (24.47), and the SQL was left unchanged. The SQL can no longer produce any accepted answer, and its one-column output could not pass anyway, because every accepted file requires all of its columns. The 174-patient version is the sounder statistic, but the question's "incorporate clinical follow-up data" invites the 184-patient reading, and the sibling question bq161, built from the same SQL, still uses 184. Our lane 1 is right under the current files, lanes 2 and 4 follow the gold SQL's own reading, and lane 3 has a formula bug.

## bq308 (stackoverflow): questions per weekday in 2021 and the share answered within one hour

### Takeaway
Verdict (a), high confidence: the gold SQL filters to 2020, turns its LEFT JOIN into an inner join, and rounds percentages to one decimal, so it cannot produce any of the four 2021 gold files. Those files were swapped in on 2025-11-02. The files themselves are right in substance, but they disagree with one another by 0-4 answered questions per weekday, and scoring demands exact counts. So a one-second boundary convention decides lanes 2 and 4 (secondary verdict (c)/(d)). Lane 1's drop of same-instant answers is a real error (e).

### Cited Findings
- **Question [file]**: "Show the number of Stack Overflow questions asked each day of the week in 2021, and find out how many and what percentage of those were answered within one hour." — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl).
- **Gold SQL, key lines [file]** — [G/sql/bq308.sql](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/sql/bq308.sql):
  - `EXTRACT(DAYOFWEEK FROM q.creation_date) AS day_of_week`.
  - `MAX(IF(a.parent_id IS NOT NULL AND (UNIX_SECONDS(a.creation_date)-UNIX_SECONDS(q.creation_date))/(60*60) <= 1, 1, 0))`.
  - `FROM posts_questions q LEFT JOIN posts_answers a ON q.id = a.parent_id WHERE EXTRACT(YEAR FROM a.creation_date) = 2020 AND EXTRACT(YEAR FROM q.creation_date) = 2020`.
  - `ROUND(100 * SUM(answered_in_1h) / COUNT(1),1) AS Percent_Answered_in_1H`.
- **Gold files [file]** — [G/exec_result/bq308_*.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result):
  - Four files of 7 rows each, with identical totals: Mon 251,182; Tue 269,887; Wed 276,742; Thu 273,442; Fri 247,624; Sat 153,466; Sun 157,237. They sum to 1,629,580.
  - Answered within 1 h in **d**: 94,923 / 102,365 / 104,861 / 103,351 / 93,473 / 58,576 / 60,630 (Mon to Sun).
  - **a** and **c** equal d except Monday, which is 94,921.
  - **b** has Monday 94,919, Thursday 103,350 and Saturday 58,575; the rest equal d.
  - Percentages are given to 2 dp (a, b, d) or about 6 dp (c).
  - `condition_cols [[1,2,3],[2,3,4],[1,2,3],[2,3,4]]` cover total, count and percent; the day column is never scored. `ignore_order: true`.
- **History [file]**:
  - The original `bq308.csv` (2024-11-10, f8be2c66) had `Day_of_Week` 1-7 (1 = Sunday), the 2021 totals, counts identical to current d (Monday 94,923) and full-precision percentages.
  - On 2025-05-22 (d79b85e9) it became `bq308_a`, and a new `bq308_b` was added. That file had the gold SQL's exact column names and day numbers 1-7. Its totals were 150,272 / 226,584 / 242,792 / 248,488 / 247,004 / 220,570 / 146,810 (sum 1,482,520), and its percentages 52.4-53.3, rounded to **1 dp**.
  - Both were replaced on 2025-11-02 (5fa8a517). Until then `condition_cols` was `[1,2,3]` — [Spider2 git](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2).
- **Timestamp precision [file]**: `creation_date` carries milliseconds, for example `2014-06-27 10:38:02.797000+00:00` in posts_questions and `2014-01-10 15:53:33.090000+00:00` in posts_answers — [S/stackoverflow/.../posts_questions.json and posts_answers.json](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/resource/databases/bigquery/stackoverflow/bigquery-public-data.stackoverflow).
- **BigQuery semantics [doc]**:
  - TIMESTAMP_DIFF: "Decimals are always truncated rather than rounded". The documentation's example returns 0 "because only the number of whole specified HOUR intervals are included".
  - UNIX_SECONDS "Truncates higher levels of precision by rounding down to the beginning of the second".
  - DAYOFWEEK "Returns values in the range [1,7] with Sunday as the first day of the week".
  - Source: [BigQuery timestamp functions](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/timestamp_functions).
- **Our four lanes [trace]** — [R/lane_k*/traces/bq308.json](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17):
  - k1 takes the first answer with `a.creation_date > q.creation_date` and counts `TIMESTAMP_DIFF(..., SECOND) <= 3600`: 93,903 on Monday, and 59,970 / 101,181 / 103,560 / 102,082 / 92,276 / 57,915 for Sun and Tue to Sat.
  - k2 and k4 take the first answer of any time and count `SECOND <= 3600`: Sun 60,637, Mon 94,931, Tue 102,371, Wed 104,866, Thu 103,363, Fri 93,485, Sat 58,581.
  - k3 takes the first answer of any time and counts `TIMESTAMP_DIFF(..., MINUTE) < 60`. Its counts equal file d exactly.
- **Simulation [sim]**:
  - k3 matches d only; k1, k2 and k4 match no file.
  - A gold-SQL-shaped answer with the right 2021 counts but `ROUND(pct, 1)` fails all four files (for example 38.6 vs 38.56, a gap above 0.01). With full-precision percentages it matches d.
- **Self-answers [doc]**: Stack Overflow's "Answer your own question" option posts the question and the answer together — [Stack Overflow for Teams help: self-answer](https://stackoverflowteams.com/help/self-answer); [Stack Overflow blog, 2012](https://stackoverflow.blog/2012/05/22/encyclopedia-stack-exchange/). These are known from search results; stackoverflow.com itself blocked fetching.

### Inferences
- **Why the gold SQL cannot produce any current file [inferred from static reading plus docs; verdict (a), high]**:
  1. The year is 2020, not 2021.
  2. `WHERE EXTRACT(YEAR FROM a.creation_date) = 2020` is NULL for unanswered questions, so the LEFT JOIN acts as an inner join. The denominator becomes questions with at least one 2020 answer, and answers dated 2021 on late-2020 questions are dropped.
  3. The 1-dp `ROUND` fails the 0.01 tolerance against every current file (checked in the simulation).
  4. Its boundary, `floor(a) − floor(q) ≤ 3600` seconds, includes negative gaps and roughly half of the answers that arrive 3600-3601 s after the question. Every current file has counts at or below d, and d equals "elapsed < 3600 s".
- [inferred, medium-high] The removed May 2025 file `bq308_b` was most likely the gold SQL's literal 2020 output. It has the SQL's column names, DAYOFWEEK numbering and 1-dp rounding, and its ~53% rate is what an answered-only denominator gives (38% overall divided by an answered share of about 70%).
- **File d [inferred]**: with millisecond timestamps, `TIMESTAMP_DIFF(..., MINUTE) < 60` means exactly "elapsed under 3600.000 s". So file d is the exact count for "within one hour". Files a, b and c differ from it by 0-4 per day for reasons I could not reproduce. Possibilities include excluding answers dated before the question (for example after merges) or truncating each timestamp to the second before taking the difference.
- **Lanes 2 and 4 [inferred]**: compared with d they are +7, +8, +6, +5, +12, +12, +5 (Sun to Sat). These are first answers 3600-3601 s after the question, which `TIMESTAMP_DIFF(SECOND) <= 3600` admits because it truncates. Strictly they over-count by up to 0.999 s, but this is a convention-level difference of 55 questions out of 1.63M (under 0.01 percentage points), decided by exact count matching. I classify it as (c)/(d).
- **Lane 1 [inferred]**: compared with d it is short by 660-1,301 per day, and more once its inclusive boundary is netted out. These are questions whose first answer is stamped at or before the question's own time. Most plausibly they are self-answers posted together with the question. They were answered within the hour, so excluding them is a genuine error (e).
- **Correct answer**: file d's counts and percentages, which is lane **k3**. If a corrected label tolerated the one-second boundary convention, **k2 and k4** would also be correct. **k1** is wrong either way.

### Gaps
- The exact rules behind files a, b and c are unknown; reproducing them would require BigQuery.
- That self-answer pairs share an identical `creation_date` is inferred, not documented.

### Plain-language explanation
The gold SQL counts 2020 instead of 2021, and its WHERE clause on the answer's year quietly turns the LEFT JOIN into an inner join, so unanswered questions vanish from the denominator. It also rounds the percentage to one decimal. For all three reasons it cannot produce any of the four 2021 answer files that were put in place in November 2025; an earlier accepted file looked just like this SQL's 2020 output, at about 53% instead of 38%. The current files are sensible (every 2021 question, counted by whether its first answer came within an hour), but they disagree with each other by up to 4 questions per weekday, and the scorer requires exact counts. Our lane 3 (fewer than 60 whole minutes) matches file d exactly. Lanes 2 and 4 (at most 3600 whole seconds, which with millisecond timestamps admits answers up to 3600.999 s) are 5-12 higher per day and fail. Lane 1 also drops answers stamped at the same instant as the question, about 1,000 per day, which is a real mistake.

## bq424 (world_bank): top 10 countries by long-term external debt

### Takeaway
Verdict (a) and (b), high confidence. The gold SQL uses DT.AMT.DLXF.CD, which is principal **repayments** (a yearly flow), not debt. It produced the original label (India first, $24.2B), which was wrong for the question. The 2025-11-02 files switched to the debt **stock** DT.DOD.DLXF.CD from a different dataset, so the SQL produces none of them. Files a, b and c (2020 stock) are correct. File d accepts the stock summed over 1970-2020, which is a lenient patch, and it is the only file our lanes 1-3 match.

### Cited Findings
- **Question [file]**: "List the top 10 countries with respect to the total amount of long-term external debt in descending order, excluding those without a specified region." — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl).
- **Gold SQL, key lines [file]**: `SELECT DISTINCT id.country_name, id.value AS debt FROM (SELECT country_code, region FROM world_bank_intl_debt.country_summary WHERE region != "") cs INNER JOIN (SELECT ... FROM world_bank_intl_debt.international_debt WHERE indicator_code = "DT.AMT.DLXF.CD") id ... ORDER BY id.value DESC LIMIT 10`. It has no year filter and no SUM — [G/sql/bq424.sql](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/sql/bq424.sql).
- **Gold files [file]** — [G/exec_result/bq424_*.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result):
  - **a, b and c** hold the same 10 values. File b has a `year` column = 2020; file a uses long official names and a region column. The values are China 1,103,089,536,703.9; Brazil 476,093,070,117.8; India 454,916,152,665.2; Mexico 413,696,160,516.7; Russian Federation 409,979,522,669.4; Indonesia 370,191,692,229.1; Türkiye 295,908,445,105.3; Argentina 162,279,484,272.8; Kazakhstan 152,445,368,869.1; South Africa 136,012,616,994.3.
  - **d** holds sums: Brazil 9,316,572,339,231.4; China 8,784,940,555,034.5; Russian Federation 7,967,031,710,515.3; Mexico 7,148,236,496,589.4; India 6,563,066,463,345.1; Indonesia 5,404,351,473,897.3; Turkey 5,314,321,743,200.2; Argentina 3,784,264,414,175.8; Venezuela, RB 2,368,411,469,306.8; Thailand 2,082,552,518,935.9.
  - `condition_cols [[2],[3],[1],[1]]` check only the debt column; `ignore_order: true`.
- **Original gold [file]**: from 2024-11-10 (f8be2c66) to 2025-11-02, `bq424.csv` held `country_name,debt` = India 24,207,420,537.1; Mexico 22,071,860,987.6; China 18,853,024,609.1; Russian Federation 18,498,824,669.4; Turkey 16,657,914,590.5; Brazil 15,249,518,424.3; Argentina 14,105,881,581.9; Indonesia 10,510,768,817.4; Colombia 9,252,731,662.1; Kazakhstan 6,440,650,957.8. It was scored with `condition_cols [0]` and `ignore_order: false`, so only the country names, in order, were checked — [Spider2 git](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2).
- **The IDS table's data [trace]**:
  - In `world_bank_intl_debt.international_debt`, DT.DOD.DLXF.CD has **6,615 rows, 0 non-null values, and NULL min/max year** — [R/lane_k4/traces/bq424.json q4](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k4/traces/bq424.json); also lane_k2 q3-q7 and lane_k1 q4.
  - Only 27 DT.* indicators have values. All are AMT, DIS or INT flow series, each with 7,560 non-null rows over 135 countries (lane_k4 q6-q9; lane_k2 q8-q9).
  - Indicator names from series_summary: DT.AMT.DLXF.CD = "Principal repayments on external debt, long-term (AMT, current US$)"; DT.DOD.DLXF.CD = "External debt stocks, long-term (DOD, current US$)" (lane_k4 q10).
- **WDI coverage [trace]**: `world_bank_wdi.indicators_data` does have DT.DOD.DLXF.CD. Brazil has 51 yearly values starting in 1970 — [R/lane_k1/traces/bq424.json q25](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k1/traces/bq424.json).
- **Duplication check [file + trace, computed]**: for all 10 countries, lane k4's sum of DT.AMT.DLXF.CD over every row is exactly **56.0 ×** the original gold value (for example 1,355,615,550,077.6 / 24,207,420,537.1 = 56.0).
- **Indicator definitions [doc]**:
  - DT.DOD.DLXF.CD = "External debt stocks, long-term (DOD, current US$)": "Long-term debt is debt that has an original or extended maturity of more than one year. It has three components: public, publicly guaranteed, and private nonguaranteed debt." — [World Bank API metadata, DT.DOD.DLXF.CD](https://api.worldbank.org/v2/indicator/DT.DOD.DLXF.CD?format=json).
  - DT.AMT.DLXF.CD = "Principal repayments on external debt, long-term (AMT, current US$)", described as the actual principal amounts paid by the borrower during the year specified — [World Bank API metadata, DT.AMT.DLXF.CD](https://api.worldbank.org/v2/indicator/DT.AMT.DLXF.CD?format=json).
  - The data.worldbank.org indicator pages returned 403 to my fetcher.
- **Our four lanes [file/trace]**:
  - k1, k2 and k3 sum WDI DT.DOD.DLXF.CD over all years and match d.
  - k4 sums IDS DT.AMT.DLXF.CD (India 1,355,615,550,077.6 first) and fails.
  - In k1 and k3, the output-shape rubric shown to the agent described the target as "sum of all years' values for long-term external debt indicators" — [R/lane_k1/traces/bq424.json](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k1/traces/bq424.json) and [R/lane_k3/traces/bq424.json](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/traces/bq424.json).
- **Simulation [sim]**:
  - The gold SQL's output (= the original gold) fails all four current files.
  - A latest-year (2020) DOD answer passes a, b and c.
  - Lanes 1-3 pass d only; lane 4 passes none.

### Inferences
- **The SQL produced the original gold [inferred, near-certain]**: the IDS table stores one DT.AMT.DLXF.CD value per country repeated 56 times (7,560 / 135 = 56), with year NULL. The SQL's `DISTINCT country_name, value` collapses the copies to one value per country, and its top 10 is exactly the original gold.
- **Why the SQL cannot produce the current files [verdict (a), high]**: the current files use a different indicator (DOD), a different dataset (WDI) and, for d, a different aggregation (SUM over years).
- **The original label was wrong for the question [verdict (b), high]**: "total amount of long-term external debt" names the debt stock, while DT.AMT.DLXF.CD is the year's principal repayments. [inferred] The likely cause is that DOD is entirely NULL in the table the SQL targets, and "AMT" reads like "amount".
- **Correct answer [inferred]**: the latest available year of DT.DOD.DLXF.CD, which is 2020 in this copy, per file b and Brazil's 51-year series. That is files a, b and c: China, Brazil, India, Mexico, Russian Federation, Indonesia, Türkiye, Argentina, Kazakhstan, South Africa. Summing a stock over 51 years counts the same debt again every year, so file d is a lenient acceptance rather than a second correct answer (verdict (d), or at most (c)).
- **Lanes under a corrected label**: with a latest-year label, **none** of our four lanes is correct. k1-k3 sum over years, and k4 uses the wrong indicator times 56 duplicates. Only if summing were also accepted would k1-k3 pass. [inferred] The rubric's "sum of all years" wording steered k1 and k3 toward file d.

### Gaps
- I did not verify that 2020 is the last DOD year for every top-10 country in WDI; the evidence is file b plus Brazil's series.
- I did not establish why the IDS table lost its year column; this is a BigQuery dataset defect visible only through query results.

### Plain-language explanation
The gold SQL picks indicator DT.AMT.DLXF.CD, which the World Bank defines as principal repayments on long-term external debt (money paid back during a year), not the amount of debt owed. The real debt-stock indicator, DT.DOD.DLXF.CD, is entirely NULL in the table the SQL uses, which probably explains the choice. The original accepted answer (India first, about $24B) came straight from that SQL. In November 2025 it was replaced by debt-stock answers from the World Development Indicators tables, either for 2020 (China first, $1.10T) or summed over 1970-2020 (Brazil first, $9.3T), while the SQL stayed the same, so the SQL now contradicts every accepted file. The 2020 files are the right answer; the summed file accepts adding up a stock year after year, which is not a meaningful total. Our lanes 1-3 pass only through that summed file, lane 4 (summing repayments that the table stores 56 times per country) fails, and under a strict latest-year label none of the four would pass.

## bq055 (google_dei): races with the largest gaps between Google's 2021 hiring and BLS tech-sector averages

### Takeaway
Verdict (d), high confidence: there is no gold SQL, and the six accepted files form an inconsistent patchwork. All of them agree on the substance (White, Asian, Black; gaps of 23.25, 20.125 and 1.95 percentage points). But an absolute difference alone passes only on the 0-1 scale, and a signed difference alone fails on both scales. This failed our lanes 2 and 4, which are fair readings (secondary verdict (c)). Under a corrected label all four lanes are correct.

### Cited Findings
- **Question [file]**: "Can you provide the top three races with the largest percentage differences between Google's 2021 overall hiring data from dar non intersectional hiring and the average percentages in the 2021 BLS data for the technology sectors specifically defined as 'Internet publishing and broadcasting and web search portals,' 'Software publishers,' 'Data processing, hosting, and related services,' or the industry group 'Computer systems design and related services,' along with their respective differences?" — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl).
- **No gold SQL [file]**: there is no bq055 SQL in Lite `gold/sql` (256 files) or in Snow `gold/sql` (120 files) — [G/sql](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/sql).
- **Gold files and their scored columns [file]** — [G/exec_result/bq055_*.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result); `condition_cols [[1,2,3],[1],[1,2,3],[1,2],[1,2],[1,2,3,4]]`, `ignore_order: true`:
  - **a**: Google % 44.5 / 42.8 / 8.8, BLS % 67.8 / 22.7 / 6.9 and signed gap −23.3 / 20.1 / 1.9, all at 1 dp; all three columns scored.
  - **b**: absolute fraction gap 0.2325 / 0.20125 / 0.0195; scored alone.
  - **c**: Google fraction, BLS fraction (0.6775 / 0.2268 / 0.0685) and absolute fraction gap, at 4 dp; all scored.
  - **d**: signed fraction plus absolute fraction; both scored.
  - **e**: signed percentage points (−23.25 / 20.125 / 1.95) plus absolute percentage points; both scored.
  - **f**: Google %, BLS % (67.75 / 22.675 / 6.85), signed and absolute percentage points; all four scored.
- **History [file]**:
  - The original `bq055.csv` (2024-12-12) was `race,diff`: white 0.2325, asian 0.20125, black 0.0195. These are absolute values on the fraction scale.
  - On 2025-05-22 it became `bq055_a`, and `bq055_b` added 5 rows, including hispanic_latinx 0.00125 and an empty native_american.
  - `condition_cols` went from `[]` (through 2025-04-01) to `[1]` with `ignore_order: false` (May 2025), then to the current six-file set (2025-11-02) — [Spider2 git](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2).
- **Our four lanes [trace]**:
  - All four use `google_dei.dar_non_intersectional_hiring` (report_year 2021, workforce 'overall') and `bls.cpsaat18` (year 2021, the three subsectors or the industry group). All four rank White, Asian, Black.
  - k1 returns Google 0.445/0.428/0.088, BLS 0.6775/0.22675/0.0685 and absolute differences; it passes b and c.
  - k3 returns the same numbers with the label "Black"; it passes b and c.
  - k2 returns 4-dp fractions with a **signed** difference (−0.2325, 0.2012, 0.0195); it fails.
  - k4 returns only signed percentage points rounded to 2 dp (−23.25, 20.13, 1.95); it fails.
  - Source: [R/lane_k*/traces/bq055.json](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17).
- **Which presentations pass, by simulation of the official scorer [sim]**:
  - Pass:
    - absolute fraction alone (b);
    - signed plus absolute fraction (b, d);
    - signed plus absolute percentage points (e);
    - Google, BLS, signed and absolute percentage points (e, f).
  - Fail every file:
    - signed fraction alone;
    - signed percentage points alone, unrounded or at 2 dp;
    - **absolute percentage points alone**, unrounded or at 2 dp;
    - Google, BLS and signed percentage points, unrounded;
    - Google, BLS and absolute percentage points, unrounded;
    - Google, BLS and signed percentage points at 1 dp computed with Python rounding, because the signed gap then rounds to −23.2 against gold a's −23.3.

### Inferences
- **Patchwork [verdict (d), high]**: the same content passes or fails depending on scale. An absolute gap suffices on the 0-1 scale (b) but needs a companion signed column on the percentage-point scale (e, f). A signed gap needs a companion absolute column on both scales (d, e), or rounding to exactly match file a. File a's BLS 67.8 is 0.05 away from the exact 67.75, beyond the 0.01 tolerance. [inferred] Its −23.3 matches rounding −23.25 half away from zero, so only one particular rounding path reproduces file a.
- **Two fair readings [verdict (c)]**: "their respective differences" (Google minus BLS) can fairly be reported signed or absolute, as a fraction or in percentage points. "Largest ... differences" is read as magnitudes by every gold file and every lane. [inferred] A signed descending reading would pick Asian, Black, Hispanic instead; no file supports it and no lane chose it.
- **Correct answer**: White −23.25, Asian +20.125, Black +1.95 percentage points (or the magnitudes). Under a corrected label that accepts either sign convention and either scale, all of **k1, k2, k3 and k4** are correct.

### Gaps
- There is no gold SQL, so I cannot say how files a-f were produced.
- I could not fetch Google's methodology page. Search results say Google counts multiracial people in each race they identify with (the "plus system"), so race shares can sum to over 100% — [Google DAR 2022 methodology](https://about.google/belonging/diversity-annual-report/2022/methodology) (redirects to a 404). If true, this makes any Google-vs-BLS comparison approximate, but it affects every reading equally.

### Plain-language explanation
There is no gold SQL. All six accepted files agree on the substance: White, Asian and Black have the largest gaps between Google's 2021 hiring shares and the BLS tech-sector averages (−23.25, +20.125 and +1.95 percentage points). They disagree on presentation, and as a set they accept some presentations while rejecting equivalent ones. An absolute difference alone passes on the 0-1 scale but fails in percentage points, a signed difference (Google minus BLS) alone fails on both scales, and one file even demands one-decimal rounding that only a particular rounding path reproduces. All four of our lanes found the same three races with the same magnitudes: lanes 1 and 3 used absolute fractions and pass, while lane 2 (signed fractions) and lane 4 (signed percentage points) fail. Under a label that accepts either sign and either scale, both fair readings of "their respective differences", all four lanes are correct.

## bq389 (epa_historical_air_quality): monthly California 2020 pollutant averages

### Takeaway
The gold SQL and the gold files agree; the SQL produced the original file. The main verdict is (d), a scoring artifact, with high confidence. A flat `condition_cols [1..6]` is applied to all seven files, so the four long-format files (3-4 columns) raise IndexError and can never be matched. Our lane 1 returned the gold numbers in long format and was scored wrong. Lane 3's VOC filter `parameter_code = 43102` (EPA "Total NMOC") is a defensible but unrequested narrowing (verdict (c)/(e)). The scorer difference in our port changes no outcome here.

### Cited Findings
- **Question [file]**: "Please calculate the monthly average levels of PM10, PM2.5 FRM, PM2.5 non-FRM, volatile organic emissions, SO2 (scaled by a factor of 10), and Lead (scaled by a factor of 100) air pollutants in California for the year 2020." — [spider2-lite.jsonl](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/spider2-lite.jsonl).
- **Gold SQL, key lines [file]** — [G/sql/bq389.sql](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/sql/bq389.sql):
  - Six subqueries of the form `SELECT AVG(arithmetic_mean) AS avg ... FROM epa_historical_air_quality.<pm10|pm25_frm|pm25_nonfrm|lead|voc|so2>_daily_summary WHERE state_name = 'California' AND EXTRACT(YEAR FROM date_local) = 2020 GROUP BY year, month`.
  - Lead is `AVG(arithmetic_mean) * 100`, and SO2 is `* 10`.
  - The VOC subquery is aliased `co`.
  - The subqueries are inner-joined on year and month. There is no parameter_code, sample_duration or pollutant_standard filter. The output is 12 rows × 7 columns.
- **Gold files [file]** — [G/exec_result/bq389_*.csv](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/gold/exec_result):
  - a, d and e are wide (12 × 7; the month is written as 1-12, 2020-01-01 and 2020-01 respectively).
  - b (72 × 4: YEAR, MONTH, POLLUTANT, MONTHLY_AVG), c (72 × 3), f (72 × 3, one row per pollutant and month name) and g (72 × 3, rounded to 2 dp) are long.
  - All carry the same numbers. January is PM10 17.8905, PM2.5 FRM 9.3852, PM2.5 non-FRM 9.7335, VOC 4.0472, SO2×10 4.5814, Lead×100 1.0522; September PM10 is 74.759.
  - `condition_cols [1,2,3,4,5,6]` is a flat list; `ignore_order: true`.
- **History [file]**: the original `bq389.csv` (2024-12-12) has the header `month,pm10,pm25_frm,pm25_nonfrm,co,so2,lead`. These are the gold SQL's aliases, including `co` for VOC, and the values equal current file a to about 1e-13. On 2025-11-02 it was replaced by files a-g. `condition_cols` has been the same flat list since at least 2025-02-13 — [Spider2 git](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2).
- **Evaluator behavior [file]**: the flat list is copied to every file (`evaluate.py` lines 73-74), and `gold.iloc[:, [1..6]]` on a 3-4 column file raises. The loop compares files in sorted order (a, b, c, ...). So anything that fails file a hits file b's IndexError, and the whole instance scores 0. Our port wraps each file in try/except, skips the long files, and also tries d and e — [evaluate.py](/Users/deepikapalagani/Documents/nl2sql-databao/Spider2/spider2-lite/evaluation_suite/evaluate.py); [nl2sql/eval.py](/Users/deepikapalagani/Documents/nl2sql-databao/nl2sql-v2/src/nl2sql/eval.py).
- **Our four lanes [file/trace]** — [R/lane_k*/traces/bq389.json](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17):
  - k1 is long (72 × 3) with no parameter filters, and its values equal the gold at 4 dp (for example Jan Lead 1.0522, PM10 17.8905, VOC 4.0472).
  - k2 and k4 are wide, rounded to 2 dp.
  - k3 is long, and its VOC CTE adds `AND parameter_code = 43102`. Its VOC values for Jan-Aug are 72.81, 65.79, 55.65, 50.91, 55.09, 52.20, 54.83, 74.63, against the gold's 4.05, 3.28, 2.93, 2.51, 2.82, 2.19, 2.18, 2.88. The other five pollutants equal the gold.
- **California 2020 parameters [trace]**:
  - `voc_daily_summary` holds **106** distinct VOC parameters, i.e. compounds. Row counts include Benzene 45201 (3,878), Toluene, Ethylbenzene, o-Xylene, m/p Xylene and Total NMOC 43102 (3,836).
  - `lead_daily_summary` holds three parameters: 12128 Lead (TSP) STP, 14129 Lead (TSP) LC, and 85129 Lead PM10 LC FRM/FEM.
  - Lane 3 picked 43102 after searching parameter names ("Total NMOC ... seems to be the most representative").
  - Source: [R/lane_k3/traces/bq389.json q1, q2, q5, q6](/Users/deepikapalagani/Documents/nl2sql-databao/results/bq17/bigquery_passk_nov2026_17/lane_k3/traces/bq389.json).
- **EPA parameter codes [doc]**:
  - 43102 = "Total NMOC (non-methane organic compound)", in "Parts per billion Carbon".
  - 42401 = "Sulfur dioxide", in "Parts per billion".
  - 12128 = "Lead (TSP) STP"; 14129 = "Lead (TSP) LC"; 85129 = "Lead PM10 LC FRM/FEM".
  - 81102 = "PM10 Total 0-10um STP"; 88101 = "PM2.5 - Local Conditions"; 88502 = "Acceptable PM2.5 AQI & Speciation Mass".
  - Source: [EPA AQS parameter code table](https://aqs.epa.gov/aqsweb/documents/codetables/parameters.html).
- **EPA daily-summary rows [doc]**: daily summary files contain data "for every monitor (sampled parameter) ... for each day". A monitor can have several rows on one day when there are calculated sample durations, multiple standards, or exceptional events. Arithmetic Mean is "The average (arithmetic mean) value for the day" — [EPA AirData file formats](https://aqs.epa.gov/aqsweb/airdata/FileFormats.html).
- **Simulation [sim]**:
  - A k1-like long answer with the gold values scores 0 in both scorers: the official one raises IndexError, and the port finds no hit.
  - With per-file columns ([3] for b; [2] for c, f and g), the same answer matches all four long files.
  - A k2/k4-like wide answer at 2 dp matches a, d and e at once.

### Inferences
- **No contradiction [inferred]**: the gold SQL and the gold files are consistent, so verdict (a) does not apply. The gold reading, "average every row of each table", is literal and simple, and it treats all six pollutants alike. Lead, for instance, mixes three parameter definitions, and nobody filters it.
- **The VOC dispute, (c) leaning (e)**: averaging 106 different compounds is not a physically meaningful single "level". Total NMOC (43102) is a defensible domain reading. But the question names no parameter, and lane 3 filtered only the VOC table, which is internally inconsistent. The gold is acceptable.
- **Main verdict (d), high**: the Nov 2025 authors evidently meant to accept long layouts, since they added four long files. But the unchanged flat `condition_cols` makes those files unmatchable, so any long-format answer fails. Lane **k1** is a false negative.
- **Correct answer**: the gold numbers in either layout. Under a corrected scorer (per-file columns), **k1, k2 and k4** are correct. **k3** would be correct only if a label for the 43102 reading were added.
- **Port difference [inferred]**: the known difference in our port (it tries d and e and skips errors) never changes an outcome on this instance, because d and e carry a's numbers.

### Gaps
- I did not check whether VOC compounds use different units (some may be ppb rather than ppbC), or how sample-duration and standard duplicates weight each table's average.
- The `co` alias suggests the SQL was adapted from a carbon-monoxide query, but that is speculative.

### Plain-language explanation
Here the gold SQL and the files agree. The SQL averages every row of each pollutant's daily-summary table for California in 2020 (with SO2 ×10 and lead ×100), and the original answer file even keeps its column names. The problem is the scorer. When the answers were expanded to seven files in November 2025, the single column list [1..6] was left in place and applied to every file, so the four long-format files (one row per month and pollutant, 3-4 columns) make the evaluator crash or skip them, and a long-format answer can never pass. Our lane 1 returned exactly the gold numbers in long format and was marked wrong, a false negative; lanes 2 and 4 used the wide layout and passed. Lane 3 also used the long layout and additionally restricted VOC to parameter 43102 (EPA's Total NMOC), giving VOC values about 18 times the gold's average over 106 individual compounds. That is a defensible domain choice but not what the question asks, so the gold's plain average stands.
