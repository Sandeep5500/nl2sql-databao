# Spider 2.0-Lite BigQuery, second round: aligning the harness with SQLite and re-measuring

**What this is.** In October we scored all 204 BigQuery questions of Spider 2.0-Lite for the first time, using four configurations of the same agent and the model `Qwen/Qwen3.6-35B-A3B`; the best configuration answered 47.5% correctly ([bigquery_lane_analysis.md](bigquery_lane_analysis.md)). 

The work produced four results and two corrections to our own earlier conclusions.

1. **Adding table statistics to the schema tools did not change accuracy.** The run with statistics and the run without it both answered 86 of 204 questions correctly (Section 7.2).
2. **October's "gated rubric" lane never showed the rubric to the model.** All 200 of its prompts are identical, character for character, to the prompts of the lane it was compared against, so the reported gain of 8.1 points was run-to-run variation between two identical setups (Section 7.3).
3. **A small new check on the number of rows in a submitted answer raised accuracy from 43.1% to 47.5%.** The check fired on 18 questions and produced a net nine additional right answers. The evidence comes from one replicate and a split by whether the check could act, so we treat it as suggestive and describe the steps that would confirm it (Sections 7.4 and 10).
4. **Allowing four further attempts at temperature 0.7 on the 107 questions the best run got wrong brought the number of questions answered correctly at least once to 139 of 204 (68.1%).** For the same model on SQLite the team measured 69.6% for the equivalent "any of four samples" figure, so the two lanes now look similar on that measure (Sections 7.5 and 8).

The corrections concern October's analysis. The rubric result in item 2 is one. The other is the table of wrong-answer shapes, which counted rows in a truncated display preview and therefore concluded that most failures had the wrong number of rows. Counting the real rows shows that most failures have the right shape and different values (Section 7.8).

Everything below is reproducible from the files named beside each result, and Appendix A lists the outcome of every question in every run.

---

## 1. Background for a reader new to the project

### 1.1 The benchmark and the two lanes

Spider 2.0 is a benchmark of realistic text-to-SQL problems: a person asks a business or science question in English, and the system has to produce the SQL, run it against a real database, and return a table that matches a hidden reference table. Spider 2.0-Lite is the version of the benchmark with 547 questions spread over three database engines. This project works with two parts of it, which we call lanes.

- **The SQLite lane** has 135 questions over small local databases.
- **The BigQuery lane** has 205 questions over Google's public datasets in the BigQuery cloud warehouse. One question points at a dataset our credentials cannot read, so 204 are scored. The warehouse bills by the amount of data each query reads, so every query costs real money, and the harness caps how much a question may read.

A question is scored as correct when every column of the reference table can be matched, value for value, to some column of our answer. Extra columns in our answer are allowed and the order of rows only matters for some questions. The scoring code is `nl2sql/eval.py` and follows the official Spider 2.0 comparison.

### 1.2 The agent

The system under test is a language model driven by a loop. At each step the model may call a tool and read the result; it ends by calling `submit_result` with the identifier of a query it ran. The tools are: `list_tables`, `describe_table` (columns, descriptions and a few sample rows), `get_column_values` (the distinct values of a column), `run_sql_query`, `read_documentation` (for the 42 BigQuery questions that come with a reference document), and `submit_result`. Before the first step the model receives a prompt containing the question and a dump of the database's table list and schema, limited to 58,000 characters. The model is `Qwen/Qwen3.6-35B-A3B` served in bf16 precision on one H200 GPU through vLLM, hosted on Modal.

### 1.3 Terms used in this report

| term | meaning |
|---|---|
| **greedy decoding** | The model always picks its most likely next token (temperature 0). Two greedy runs of the same setup should be identical, but in practice they differ on about one question in five, for reasons we did not investigate; Section 7.2 measures this. |
| **temperature 0.7 / sampling** | The model picks tokens at random in proportion to their probability, so every attempt is different. |
| **pass@1** | The probability that one attempt is correct. SQLite's team figure averages four sampled attempts per question. |
| **pass@k, "solved by any attempt"** | A question counts as solved if at least one of k attempts is correct. |
| **rubric** | A short planning pass before the main run. A separate model call reads the question and the catalog (not the warehouse) and writes down the expected shape of the answer: how many rows, which columns, what ordering. It also states how confident it is about the row count. |
| **gate** | The rule that the rubric is added to the prompt only when it states an exact row count with high confidence. For these data the gate is open on 123 of 204 questions. |
| **arm** | One complete run over all 204 questions with one configuration. |
| **flip** | A question whose result differs between two runs. "+27 / −18" means 27 questions were wrong in the first run and right in the second, and 18 the other way around. |
| **sign test** | A test on the flips alone, asking whether 27 against 18 is more lopsided than a fair coin would produce. |

---

## 2. Where the project stood before this round

Four BigQuery configurations were scored in October, all greedy, all on the same model.

| lane | what it adds | correct | n | accuracy |
|---|---|---:|---:|---:|
| `bq_v2` | baseline: 40 steps, schema dump cut at 60,000 characters, a tool the warehouse refuses | 69 | 204 | 33.8% |
| `bq_v3` | five harness fixes and 60 steps | 84 | 204 | 41.2% |
| `bq_v3r` | plus the gated rubric | 95 | 200 | 47.5% |
| `bq_v3s` | plus catalog retrieval (a `search_context` tool) | 87 | 204 | 42.6% |

Three conclusions from that round matter here. First, most of the improvement from 33.8% to 41.2% came from fixing handicaps in our own harness, chiefly a schema dump that was cut off in the middle of a table list so that later tables were invisible to the model. Second, the report credited the rubric with a gain of 8.1 points over a measured noise floor. Third, retrieval added nothing once the full table list was in the prompt.

The SQLite lane had been measured differently. Its headline figures, from commit `49cca7d` on the team's main branch, use the same Qwen3.6-35B model at temperature 0.7 and report the **average over four sampled attempts per question**:

| SQLite lane (135 questions) | pass@1 (mean of 4) | solved by any of 4 attempts |
|---|---:|---:|
| baseline | 47.4% | 94 (69.6%) |
| richer `describe_table` | 51.1% | 94 (69.6%) |
| plus gated rubric | 51.3% | 94 (69.6%) |

Every BigQuery number in the table above is a single greedy run, so comparing 47.5% with SQLite's 51.1% compares two different quantities. That is one of the five differences below.

---

## 3. Why a second round: 's five differences

 compared the two harnesses and found the following. Reading the code confirmed each one.

| # | Difference | What the code showed | What we did |
|---|---|---|---|
| 1 | **`describe_table` is thin on BigQuery.** On SQLite it runs live queries for the row count and, per column, the number of distinct values and of nulls. On BigQuery it only lists columns, descriptions and five sample rows copied from a catalog file. | Confirmed. | Built a one-time statistics pass and made the tool print its results (Section 4.3). |
| 2 | **The `get_column_values` fallback is misleading.** When an exact distinct-value query would read too much data, the BigQuery tool returns a handful of catalog sample values instead. | Confirmed. The fallback was already labelled as a sample, but the label was easy to overlook. | Rewrote the warning so that it cannot be mistaken for the real value list (Section 4.4). |
| 3 | **The rubric planner is blind on warehouses.** On SQLite the planner can look at column values; on BigQuery those tools are removed to avoid doubling the bill. | Confirmed. | Gave the planner the same cached statistics through `describe_table`, at no query cost, and kept the value tools removed (Section 4.3). |
| 4 | **Time and cost limits.** BigQuery runs have a 120-second statement timeout, 60 queries and 900 seconds per question, 50 GiB per query and 200 GiB per question. SQLite has none. | Confirmed. Several October episodes already scanned more than 100 GiB. | **Not changed.** Raising limits needs a measured proposal that the project administrators see first (Section 10). |
| 5 | **Decoding and weights.** BigQuery runs are greedy in bf16. SQLite uses temperature 0.7, according to 's comparison with quantized (AWQ) weights, and reports the mean of four samples. | Confirmed for decoding and for the metric. | Ran sampled retries at temperature 0.7 on the questions that failed (Section 7.5). We did **not** switch to quantized weights, and did not sample every question. |

---

## 4. What had to change before the first run

### 4.1 Access and billing

The old Google Cloud project could no longer be used. The new project, `llm-systems-projects`, is shared and comes with four rules from its administrators: label every resource `cost_center=rohini`, keep usage within a $150 guideline, stop or delete resources when finished, and ask before starting expensive GPU or TPU jobs on Google Cloud. Access is through a service account that our own account impersonates, with no key file.

Code changes in [bigquery_db.py](../nl2sql-v2/src/nl2sql/bigquery_db.py):

- `build_credentials()` creates impersonated credentials. A first version wrapped credentials that the local login had already wrapped, which the permission system rejected; it now detects that case.
- Every query job carries the label `cost_center=rohini`.
- `scripts/bq_spend.py` and `scripts/bigquery_preflight.py` use the same credentials, and `bq_spend.py` reads BigQuery's own job accounting, which gives spend per run label.
- Two optional dependency groups were added to `pyproject.toml` (`bigquery` and `embed`).

The model runs on Modal and no GPU was used on Google Cloud, so the rule about GPU jobs was not triggered; we still report the GPU time used (Section 9).

### 4.2 Where the code runs

Credentials for the shared project stay on one machine. The agent loop, the tools and the BigQuery calls therefore run on Rohini's laptop in five parallel processes per run, and only the model calls go to the Modal H200. The `run_arm.py` script drives a full arm: first the rubric pass, then the five processes. The vLLM key was regenerated for this and stored in a Modal secret.

### 4.3 Statistics for `describe_table` ('s items 1 and 3)

[enrich_bq_stats.py](../nl2sql-v2/scripts/enrich_bq_stats.py) visits each of the 69 reachable databases once and records, for every table, the exact row count and, for every column of an identifier-like type, an approximate distinct count (HyperLogLog) and the number of nulls. Floating-point columns are skipped because their distinct counts are not informative. Before spending anything the script estimates its cost with BigQuery dry runs, which are free, and it sets a byte cap on every query.

The pass produced 70 files, one per database (the file for the one unreachable dataset is empty), covering 5,401 tables and 89,718 column statistics. BigQuery billed 582.5 GiB for it, about $3.60. Here is what `describe_table` now shows the model for one table; the header and the `approx_distinct` and `nulls` fields are new:

```
table: bigquery-public-data.census_bureau_international.birth_death_growth_rates  (15019 rows)
columns:
  country_code  STRING  approx_distinct=228 nulls=0  -- Federal Information Processing Standard (FIPS) country/area code
  year          INT64   approx_distinct=101 nulls=0  -- Year
  net_migration FLOAT64  -- Net migration rate (net number of migrants per 1,000 population)
```

The feature is opt-in, through `--bq-stats DIR`, so that the control arm is untouched. The rubric planner receives the same statistics when it is started with that flag.

### 4.4 A clearer warning on the value fallback (item 2)

When an exact distinct-value query would exceed the byte cap, `get_column_values` now says that the real distinct values could not be read and that the values that follow are only what happened to appear in a few catalog sample rows. The earlier text described the output as a "sample". The test in `check_bigquery_db.py` was updated to match.

### 4.5 A confound found in the pilot and its fix

We first ran a pilot of 40 questions, chosen to cover every database family, once without statistics and once with them. In the treatment arm, the block for each table became longer, and for the `stackoverflow` database the whole dump no longer fit in the 58,000-character budget. The prompt builder then switched to a shorter format that lists only column names, dropping the descriptions and sample rows, so the treatment arm had changed in two ways at once: statistics were added and descriptions were removed. The builder now drops the statistics from the dump first and keeps every description, while `describe_table` still returns the statistics when the model asks for a table. The script `dump_mode_check.py` builds the dump for each of the 70 databases with and without statistics and reports the format chosen; after the fix, all 70 are unchanged. The partial pilot run made with the faulty builder was deleted and repeated.

### 4.6 The pilot's result

On the 40 pilot questions the control, the treatment and October's `bq_v3r` all scored 15 of 40. The treatment read 131 GiB against the control's 208 GiB, a 37% reduction, and took fewer steps (20.2 against 23.0). The pilot was too small to say more; 36 of the 40 treatment episodes displayed at least one statistic, so the feature was reaching the model. The reduction in data read did not reappear at full scale (Section 7.2).

---

## 5. Design of the runs

All runs use the same model server, greedy decoding, a limit of 60 steps, and the October limits on data read. The first four arms use all 204 questions.

| arm | statistics | rubric text in prompt | row-count check | purpose |
|---|---|---|---|---|
| `C` | no | yes (123 questions) | no | control |
| `T` | yes | yes (128 questions, from its own planner run with statistics) | no | the change  asked for |
| `C2` | no | yes (the same files as `C`) | no | a second control, run at the same time as `R` |
| `R` | no | yes (the same files as `C`) | **yes** | the row-count check |
| tries 1–4 | no | yes (as `R`) | yes | temperature 0.7 retries of the 107 questions `R` got wrong |

Running a control at the same time as each treatment, on the same server, means that any change in the server, the warehouse or the day affects both. This matters because comparing a new run with an October run would mix the effect of our change with four weeks of other differences, including the Google Cloud project, the code and the server. `R` differs from `C2` in exactly one setting, `--rubric-row-check`.

Three kinds of statistics are used, none of them corrected for the number of comparisons made. The two-sided sign test on flips asks whether a gain is lopsided. A bootstrap interval resamples questions. Where a split by "gate open versus gate closed" is used, it divides the questions into those on which a change can act and those on which it cannot, and the second group works as an internal control.

---

## 6. How the runs went

Work proceeded in four phases.

**Phase 1: control against statistics (`C` and `T`).** Both arms ran at the same time. Each first generated 204 rubrics (about 12 minutes, zero bytes read from the warehouse), then answered all questions in about 1 hour 47 minutes. Neither arm recorded an infrastructure error, and both scored 86.

**Phase 2: finding out what the rubric was doing.** The 5-point shortfall against October's 47.5% prompted a comparison of the fresh control with October's traces. The fresh control's prompts contain a section titled "Expected output shape" in 123 of 204 episodes. October's contain it in none of 200. The same holds for October's `bq_v3`, and the two October prompts are equal for all 200 shared questions. We could not recover the exact October launch command, so we cannot say why the rubric directory was invisible. We did reproduce the mechanism on a smoke test: the rubric loader returns nothing, without any message, when the directory does not exist from the process's point of view, and the run then silently proceeds without a rubric. `run_benchmark.py` now refuses to start when `--rubric-dir` contains no files.

**Phase 3: the row-count check (`C2` and `R`).** The wrong answers in every run included a recurring pattern: the model had written a test query that returned a long list, the rubric in its prompt said one row (or three, or five), and the model submitted the test query anyway. Section 7.4 gives the evidence. We added a check that, when the rubric states an exact row count with high confidence, bounces the first submission whose row count differs and tells the model both numbers. It can re-run or resubmit the same query unchanged, and the harness never rewrites an answer. A no-GPU test (`check_row_check.py`) covers four cases: check off, mismatch, override and match. A three-question smoke test then exposed the silent rubric problem a second time, because the relative path to the rubric folder was resolved from the wrong directory; the guard described above was written in response, and the smoke output was deleted and repeated. `C2` and `R` then ran side by side.

**Phase 4: retries of the failures.** At Rohini's request, the 107 questions `R` answered wrongly were attempted four more times at temperature 0.7, two attempts at a time.

| run | wall time | correct | data billed by BigQuery |
|---|---:|---:|---:|
| `C` | 1 h 59 min | 86 / 204 | 1.4 TiB |
| `T` | 2 h 02 min | 86 / 204 | 1.5 TiB |
| `C2` | 1 h 41 min | 88 / 204 | 1.1 TiB |
| `R` | 1 h 46 min | 97 / 204 | 1.3 TiB |
| try 1 | 1 h 18 min | 20 / 107 | 717 GiB |
| try 2 | 1 h 09 min | 23 / 107 | 886 GiB |
| try 3 | 1 h 17 min | 27 / 107 | 722 GiB |
| try 4 | 1 h 23 min | 21 / 107 | 751 GiB |

No run had an infrastructure error. The harness's own counter of data scanned reads higher than BigQuery's bill (for example 1.65 TiB against 1.3 TiB for `R`); the bill is used throughout. One question (ga021) took noticeably longer than the rest in try 4, and the overall run waited for it.

---

## 7. Results, question by question

### 7.1 Headline

| run | what it tests | correct | accuracy |
|---|---|---:|---:|
| October `bq_v3` | five harness fixes, no rubric text | 84 | 41.2% |
| October `bq_v3r` | the same prompts as `bq_v3` (Section 7.3) | 95 (of 200) | 47.5% |
| `C` | control, rubric text present | 86 | 42.2% |
| `T` | plus statistics | 86 | 42.2% |
| `C2` | second control | 88 | 43.1% |
| **`R`** | **plus row-count check** | **97** | **47.5%** |
| `R` plus four tries | solved by any of five attempts | 139 | 68.1% |

Each single run has a 95% interval of about ±6.8 points, and two identical greedy runs differ on 44 of the 204 questions (Section 7.2), so any pair of single runs has to be read through its flips and not through its totals.

### 7.2 Do the statistics help? (`C` against `T`)

Totals are equal, 86 and 86. The flips are +26 and −26, which is as symmetric as a result can be (sign test p = 1.0).

To know how large a difference to expect from chance alone, compare `C` with `C2`. These two arms are the same setup, run one after the other, and they differ on 44 of 204 questions (+23 and −21). The statistics arm differs from `C` on 52 questions and from `C2` on 42, which is the same range as the 44 that separate the two controls from each other. If the statistics had changed the model's behaviour in a consistent way, the treatment would be expected to sit clearly further from both controls than they sit from each other.

The 204 questions fall into patterns across the three runs (right in `C`, `C2`, `T`):

| pattern | questions |
|---|---:|
| right in all three | 51 |
| wrong in all three | 84 |
| the three runs disagree | 69 |

On the 69 disagreements, when the two controls agree with each other and the statistics arm differs, it is right on 11 questions the controls got wrong (`bq002`, `bq004`, `bq006`, `bq053`, `bq308`, `bq326`, `bq327`, `bq397`, `bq445`, `ga009`, `ga011`) and wrong on 14 that both controls got right (`bq001`, `bq021`, `bq040`, `bq108`, `bq114`, `bq161`, `bq203`, `bq230`, `bq288`, `bq356`, `bq391`, `bq419`, `ga002`, `ga025`). The net effect is −3 questions, the opposite sign from what an improvement would give and well inside the noise.

Of the 204 treatment episodes, 186 displayed at least one statistic in the prompt or in a tool result and 18 never displayed any. The 18 are almost the same as the control in what they saw (the only remaining difference is the rubric text, generated in the treatment arm with statistics), and still moved by +5 and −1 questions, which shows how far a group of this size can drift when the inputs differ very little.

The pilot's reduction in data read did not reappear. The treatment arm read 1.5 TiB against 1.4 TiB for the control by BigQuery's bill, and took 19.2 steps per question against 18.6.

**Conclusion.** The statistics were visible in 91% of treatment episodes, and accuracy ended exactly where the control was, with the changes at the question level no larger than the changes between the two controls. On this model and this benchmark, row counts, approximate distinct counts and null counts therefore move the score by at most a few questions. The SQLite improvement from 47.4% to 51.1% came from a `describe_table` that also reports declared keys and generated table notes from the context engine, and we did not build those for BigQuery, so the BigQuery experiment tests only part of what the SQLite change contained.

### 7.3 October's rubric result, re-examined

The October report compared `bq_v3` with `bq_v3r` and found +11 questions (+25 and −14) on the 200 shared questions. It then split the questions by whether the rubric had passed the gate, and read the closed-gate group as a noise floor. That reasoning is sound when the open-gate prompts really differ, but we find that they do not differ: comparing the stored system prompt of every shared question, `bq_v3` and `bq_v3r` are identical for all 200.

The consequence is that the October comparison was a measurement of how far two identical runs can disagree. They differed by 11 questions on a net basis, 5.5 points, and the sign test on those flips gives p = 0.11. Run-to-run variation of that size is the context in which every single-run difference in this report has to be read.

With the rubric genuinely present, this round's controls give an indication of its effect, although other small changes were made in the meantime (the warning text and the project) and no run isolates the rubric alone:

| questions | `bq_v3` (no rubric) | `C` | `C2` |
|---|---:|---:|---:|
| 123 where the gate is open | 49 | 53 | 56 |
| 81 where the gate is closed | 35 | 33 | 32 |

The open-gate group gained 4 to 7 questions and the closed-gate group lost 2 to 3. The paired flips from `bq_v3` to `C2` on the open-gate group are +15 and −8 (p = 0.21), so the data lean in the direction October reported while remaining compatible with no effect at all. The October commit message for `bq_v3r` records that the same rubric added only 0.2 points on the team's SQLite runs, and our estimate of a few questions out of 123 is on the same small scale.

### 7.4 The row-count check (`R` against `C2`)

#### What goes wrong without it

For every run, the wrong answers were classified by the real number of rows submitted compared with the reference table (the tool prints `[showing 12 of 61 rows]` when it truncates a preview, and the real count is taken from that line):

| wrong answers | `bq_v3` | `bq_v3r` | `C` | `T` | `C2` | `R` |
|---|---:|---:|---:|---:|---:|---:|
| right number of rows | 61 | 60 | 59 | 58 | 61 | 62 |
| too many rows | 27 | 24 | 29 | 28 | 27 | **11** |
| too few rows | 17 | 13 | 14 | 16 | 16 | 19 |
| ran out of steps | 15 | 7 | 15 | 16 | 10 | 14 |
| no submission | 0 | 1 | 1 | 0 | 2 | 1 |
| of "too many rows", the rubric's count was right | 19 | 14 | 18 | 16 | 14 | **0** |

For `bq_v3` and `bq_v3r` the rubric was not in the prompt, and in every column the last row counts what the rubric of `C` would have said. The last row is the one that motivated the check. In `C` and `C2`, where the correct row count was written in the prompt, 18 and 14 answers still had too many rows. Reading them, the model had typically run an exploratory query with `LIMIT 10` or a ranking over every group, seen a plausible table, and submitted it although the rubric said one row. The rubric states the correct count on 118 of the 123 questions where the gate is open (the five exceptions are listed below).

#### How it works

When the rubric's count is stated with high confidence and the model submits a query whose result has a different number of rows, the harness replies once, in place of accepting the submission:

> Row-count check: q1 returned 10 row(s), but the expected output shape (confidence: high) is exactly 3 row(s). Re-read the question. If it asks for exactly 3, run a query that returns exactly that and submit its query_id. If you are confident the count should be 10, submit q1 again.

It never rewrites SQL, never fires a second time on the same question, and uses no information from the answer key; the rubric is written from the question and the catalog alone. Earlier in the project the SQLite lane had a feature that silently removed `LIMIT` clauses from submissions; it was reverted (commit `cd1d20f`) because it turned correct top-N answers into wrong ones. The check described here therefore only asks the model a question and leaves the decision with the model.

#### Result

| | `C2` | `R` | flips | sign test |
|---|---:|---:|---|---:|
| all 204 questions | 88 (43.1%) | 97 (47.5%) | +27 / −18 | p = 0.23 |
| 123 where the check can fire | 56 (45.5%) | 67 (54.5%) | +19 / −8 | p = 0.05 |
| 81 where it cannot fire | 32 | 30 | +8 / −10 | p = 0.81 |

Against the mean of both controls (`C` and `C2`, 42.6%), `R` is 4.9 points higher, with a bootstrap 95% interval of −0.5 to +10.5 points. The same split against `C` alone is +21 and −7 (p = 0.01). The 81 questions on which the check cannot fire have identical prompts and an identical loop, so their movement of −2 questions measures the noise in this comparison directly; the open-gate group moved by +11. We chose the split by gate after seeing the totals, so the p-values describe the data and carry no formal guarantee.

Wrong answers with too many rows fell from 27 to 11, and the number of answers that were wrong because the rubric's count was right and ignored fell from 14 to 0. Wrong answers with too few rows rose from 16 to 19. Part of that rise is a side effect of the check, as the question-level table below shows for `bq076`, where shrinking a list into a single value also dropped a column.

#### The 18 questions on which the check fired, one by one

The check fired on 18 of the 123 open-gate questions in `R`. Seventeen of the 18 first submissions would have been wrong against the answer key (we scored the preview of each bounced query to find out), and one, `bq339`, would have been right.

| question | database | first submission | rubric | what happened after the bounce | final |
|---|---|---|---|---|:-:|
| `bq002` | ga360 | 181 rows (daily revenue for a traffic source) | 1 row | Kept working on a multi-part question, used all 60 steps and fell back to a partial answer. | wrong |
| `bq006` | austin | 2 rows (`LIMIT 2` on the z-scores) | 1 row | Changed the ending to `LIMIT 1 OFFSET 1`, which returns the second-highest date the question asks for. | **right** |
| `bq060` | census_bureau_international | 10 rows (`LIMIT 10`) | 3 rows | Changed `LIMIT 10` to `LIMIT 3`. | **right** |
| `bq061` | census_bureau_acs_1 | 10 rows, 4 columns | 1 row | Re-ran selecting only the tract identifier, ordered by the increase, with `LIMIT 1`. | **right** |
| `bq076` | chicago | 12 monthly rows | 1 row | Wrapped the query in `MAX`, which gave one row, but the answer key also expects the month, so a column was lost. | wrong |
| `bq130` | covid19_nyt | 10 rows | 5 rows | The rubric's count is wrong (the answer key has 10 rows). The model complied with 5 rows. Its original answer was also wrong. | wrong |
| `bq172` | cms_data | 10 rows (`LIMIT 10`) | 5 rows | Changed to `LIMIT 5`. | **right** |
| `bq202` | new_york_plus | 7 rows (counts per weekday) | 1 row | Wrote a single combined query, but the values do not match. | wrong |
| `bq229` | open_images | 2 rows | 1 row | Rewrote the query; the new values do not match. The answer key accepts one row or two. | wrong |
| `bq281` | austin | 5 rows | 1 row | Replaced the list with a single `MAX`. | **right** |
| `bq282` | austin | 6 rows | 1 row | Kept only the top council district. | **right** |
| `bq339` | san_francisco_plus | 1 row, **correct** | 12 rows | The rubric expected one row per month, while the question asks for a single month and the answer key has one row. The model complied with 12 rows and lost a correct answer. | wrong |
| `bq362` | chicago | 20 rows | 3 rows | Kept the three largest increases. | **right** |
| `bq395` | sdoh | 1 row (only the count of states and the national average) | 5 rows | The model had stopped halfway; after the bounce it went on to name the five states closest to the average (`LIMIT 5`). | **right** |
| `bq403` | irs_990 | 6 rows | 3 rows | Reduced to 3 rows, but the values do not match the answer key. | wrong |
| `bq462` | ncaa_basketball | 17 rows | 20 rows | The rubric's count is wrong (the answer key has 17). The final answer again has 17 rows, and its values do not match the key. | wrong |
| `ga011` | ga4 | 10 rows (ranking of pages) | 1 row | Kept only the second-ranked page. | **right** |
| `ga030` | firebase | 14 cohorts | 1 row | Kept only the cohort with the highest retention. | **right** |

Ten of the 18 ended right. Had the check not fired, only 1 of the 18 first submissions would have scored, and in the two controls `C2` and `C` three and two of these same 18 questions happened to come out right. The gain on these 18 questions is therefore between 7 and 9 questions, depending on which baseline is used, and 7 of the net 9 between `C2` and `R` arise here. The remaining questions, on which the check did not fire, differ between the two arms by a net 2.

Four kinds of outcome appear in the table, and each suggests a different follow-up.

- **The rubric was wrong (`bq130`, `bq339`, `bq462`).** The planner's row count disagrees with the answer key on 5 of the 123 open-gate questions: `bq089`, `bq130`, `bq339`, `bq360` and `bq462`. The check fired on three of them, and in one (`bq339`) it replaced a right answer with a wrong one. This is the main risk of the check, and in this sample it cost 1 question out of 18.
- **The row count was fixed and a column was lost (`bq076`).** The question asks for the highest monthly count and the answer key also lists the month, so the answer needs two columns. The model satisfied the row count with a single `MAX` value.
- **The row count was fixed or already right, and the values were still wrong (`bq202`, `bq229`, `bq403`).** A row count cannot influence which value a query computes, so the check had no way of helping.
- **The model could not finish (`bq002`).** The question asks for several outputs and exhausted the step budget.

### 7.5 Retries of the failures: what the other 107 questions did

For each of the 107 questions `R` answered wrongly, four further attempts were run at temperature 0.7, with the rubric and the row-count check still active.

| | answered right in this try | newly solved (not solved by an earlier attempt) | solved by any attempt, of 204 |
|---|---:|---:|---:|
| `R`, greedy | — | — | 97 (47.5%) |
| + try 1 | 20 | 20 | 117 (57.4%) |
| + try 2 | 23 | 11 | 128 (62.7%) |
| + try 3 | 27 | 7 | 135 (66.2%) |
| + try 4 | 21 | 4 | **139 (68.1%)** |

Each try rescues roughly one failure in five, 19% to 25% of the 107, but the new questions per try fall from 20 to 4 as the easy-to-rescue ones are used up. We did not retry the 97 questions `R` answered correctly, so the final figure tells us how often a right answer lies within reach of the system, which is a separate quantity from the accuracy of a single submitted answer. Retrying only the failures gives the exact count of questions solved by any attempt, because a question that is already solved cannot change that count. It cannot give pass@1, because the answer key decided which questions were retried and some of the failures would turn right by chance alone.

**The 42 rescued questions.** How many of the four tries produced a right answer:

| tries right | questions |
|---:|---|
| 4 of 4 (5) | `bq001`, `bq011`, `bq235`, `bq461`, `ga008` |
| 3 of 4 (9) | `bq010`, `bq079`, `bq126`, `bq305`, `bq326`, `bq389`, `bq396`, `bq407`, `ga007` |
| 2 of 4 (16) | `bq018`, `bq023`, `bq035`, `bq051`, `bq066`, `bq105`, `bq151`, `bq185`, `bq203`, `bq229`, `bq302`, `bq304`, `bq424`, `bq445`, `ga025`, `ga032` |
| 1 of 4 (12) | `bq002`, `bq053`, `bq055`, `bq123`, `bq208`, `bq227`, `bq308`, `bq327`, `bq328`, `bq339`, `bq366`, `ga002` |

Fourteen questions were right in at least three of four tries, which suggests that the model can produce the right answer on these and that the greedy run happened to take a wrong path. For example, `bq001` (a Google Analytics question) is right in all four tries and in October's `bq_v3r`, `C` and `C2`, and wrong in `T` and `R`; in `R` the greedy answer had 20 rows against an answer key of 666. A selection method that prefers the answer most attempts agree on would recover most of these 14, and arguably some of the 16 that were right twice. The 12 questions right only once are harder to pick out; a majority among five answers would have missed them.

Of the 42 rescued questions, the greedy `R` answer had the right number of rows on 28, too few rows on 7, too many on 4, and was unfinished on 3. The attempts that succeeded therefore mostly kept the overall shape of the greedy answer and differed from it in the definition or filter they used, and Section 7.6 shows what such differences look like.

### 7.6 What remains unsolved

Sixty-five questions were wrong in `R` and in all four tries. They are listed in full in Appendix B. By database family, 55 are `bq###` (of 179) and 10 are `ga###` (of 25).

| database | never solved | in benchmark |
|---|---:|---:|
| ga360 | 5 | 12 |
| firebase | 5 | 9 |
| ga4 | 5 | 17 |
| chicago | 3 | 5 |
| noaa_data | 3 | 11 |
| mitelman | 3 | 3 |
| ncaa_basketball | 3 | 5 |
| new_york, nhtsa_traffic_fatalities, google_dei, CYMBAL_INVESTMENTS | 2 each | 4, 4, 3, 2 |

October's list of 76 questions that no lane solved had 18 of the 25 `ga###` questions in it. Now 15 of those 25 have been solved at least once, so these questions are less closed than they looked. The three Google Analytics and Firebase databases (ga360, firebase and ga4) still account for 15 of the 65 unsolved questions.

The greedy `R` answers to these 65 fall into the following kinds.

| kind of miss | questions | what it looks like |
|---|---:|---|
| right number of rows, wrong content | 34 | The model computed a table of the right size with different values or different columns. |
| too few rows | 12 | For example `bq031` (50 rows against 82) and `bq428` (40 against 95). |
| too many rows | 7 | For example `bq034` (462 rows against 100 or 445), `bq425` (605 against 100) and `bq457` (42 against 4). |
| ran out of the 60 steps | 11 | Long multi-stage analyses, listed below. |
| no submission | 1 | `bq096`, a date search over bird sightings. |

**Right shape, different values (34).** A few examples show how the answers diverge from the key while looking plausible:

- `bq009` asks for the revenue gap between a traffic source's best and worst months. The model returned the right source, `(direct)`, and a gap of 118,015.76 where the key has 4,659.15, about 25 times smaller, so the model's monthly totals or their difference were computed differently from the key's.
- `bq022` asks for six equal-sized duration groups of Chicago taxi trips. The model's groups each hold 34,891,917 trips and the key's hold 34,655,568 and 34,655,569, a 0.7% difference that suggests the two sets of trips were filtered differently.
- `bq024` expects numeric evaluation-group codes such as 562012 in its first column, and the model returned the descriptive text for that column.
- `bq008` asks which page visitors most often reach next. The model answered `/home` with a maximum time of 2 seconds, where the key names a specific apparel page and 2,848 seconds.

These examples suggest that many of the differences come from definitions the question leaves open, such as which trips count, how a month is totalled, or which code a column holds; we have not read all 34 individually. This is the largest category of residual failure, and the row-count check has no influence on it.

**Questions with an attached document (24 of the 65).** Forty-two BigQuery questions come with a reference document that is meant to supply required definitions, such as a formula or a list of fields. The model always read it: in `R`, `read_documentation` was called on all 42. Even so, these questions are much harder.

| | with a document (42) | without (162) |
|---|---:|---:|
| `C` | 12 (29%) | 74 (46%) |
| `T` | 11 (26%) | 75 (46%) |
| `C2` | 9 (21%) | 79 (49%) |
| `R` | 11 (26%) | 86 (53%) |
| solved by any of the five attempts | 18 (43%) | 121 (75%) |

Questions with a document make up 21% of the benchmark and 37% (24 of 65) of the never-solved set. Examples are `bq441` and `bq442`, whose question text says only "as listed in the info document" or "refer to the document for all the information I want". Bringing these questions to the rate of the others would be worth up to 11 questions in a greedy run, so how the model applies the document is a promising place to look.

**Ran out of steps (11).** `bq003` (ga360), `bq085` (covid19_jhu), `bq102` (gnomAD), `bq111` (mitelman), `bq200` (mlb), `bq277` (noaa_ports), `bq287` (fda), `bq354` (cms_data), `ga005`, `ga020` and `ga028` (firebase). These are long analyses, such as retention by weekly cohort, a correlation computed for each chromosome, or a spatial join. Only two of the eleven (`bq003` and `bq200`) were ever solved by another run. In the error taxonomy of Section 7.7, 22 of `R`'s 107 failures were stopped by a harness limit: 14 ran out of steps, 6 had a query cancelled for exceeding the time limit and 2 were refused for exceeding a scan cap. Those 22 are the most that 's fourth item, raising the limits, could address.

**Seven questions were solved by another run, either in October or earlier this round, and by none of the five attempts of `R`.** They are `bq003`, `bq075`, `bq090`, `bq200`, `bq290`, `ga009` and `ga022`. Together with the 14 questions that most of the tries solved, they show that the set of questions the system can solve is larger than any single configuration reaches.

### 7.7 Where each run lost its points

The failure taxonomy (`scripts/error_taxonomy.py`) assigns each wrong episode to one cause, harness first, so that the buckets sum to the loss.

| wrong episodes | `bq_v3` | `bq_v3r` | `C` | `T` | `C2` | `R` |
|---|---:|---:|---:|---:|---:|---:|
| harness: schema from the wrong scope (bare-dataset INFORMATION_SCHEMA) | 0 | 0 | 2 | 2 | 0 | 1 |
| harness: scan cap refused the query | 0 | 1 | 1 | 0 | 1 | 2 |
| harness: query cancelled for time | 7 | 3 | 6 | 8 | 3 | 6 |
| harness: never produced SQL | 0 | 0 | 0 | 0 | 1 | 0 |
| harness: ran out of steps | 15 | 7 | 15 | 16 | 10 | 14 |
| **harness subtotal** | **22** | **11** | **24** | **26** | **15** | **23** |
| model: answered, wrong result | 98 | 94 | 94 | 92 | 101 | 84 |
| **total wrong** | 120 | 105 | 118 | 118 | 116 | 107 |
| correct | 84 | 95 | 86 | 86 | 88 | 97 |

Harness limits account for 10% to 22% of wrong answers in every run. Between `C2` and `R` the number of wrong answers from the model fell by 17 (101 to 84), while the number stopped by a harness limit rose by 8 (15 to 23): 14 episodes ran out of steps against 10, and 6 had a query cancelled for time against 3. A check that asks the model to re-run a query can plausibly lengthen some episodes, but a difference of this size also occurs between identical runs (`C` had 24 harness-limited failures and `C2` had 15).

### 7.8 Corrections to the October analysis

**The rubric.** Section 7.3: the October report attributed 8.1 points to a rubric that was not in the prompts. The report's section 4 and the commit message of `461ffcf` should be read with that correction.

**The wrong-answer shape table.** The October report (section 3) stated that on the best lane, 51% of wrong answers had too many rows, 15% too few, 33% the wrong number of columns, and 1% the right shape with wrong values, and concluded that the model finds the right tables but gets the grain wrong. The script that produced the table, `wrong_answer_shapes.py`, counts the lines of the preview text stored in the trace. That text is limited to the first 12 rows by default, it ends with footer lines such as `[showing 12 of 61 rows]` and `[scanned …]`, and the script counts the footer lines as data rows. Counting the real rows (taken from the footer) and the real columns gives a different picture for the same lane, `bq_v3r`, for its 97 wrong submitted answers:

| wrong submitted answers on `bq_v3r` (97) | October table | recounted |
|---|---:|---:|
| too many rows | 49 (51%) | 24 (25%) |
| too few rows | 15 (15%) | 13 (13%) |
| right number of rows, but fewer columns than the answer key | 32 (33%, "wrong column count") | 7 (7%) |
| right number of rows and enough columns, with different values | 1 (1%) | **53 (55%)** |

In the October table the "wrong column count" group also included answers with more columns than the key, which the scorer allows, so it counted answers that were not shape errors at all. The recount for the other runs is similar. In `C2` there are 56 answers with the right rows and enough columns, 27 with too many rows, 15 with too few and 5 with a column missing (one answer could not be classified). In `R` the same counts are 57, 11, 19 and 5.

The majority of wrong answers therefore have the right shape and disagree with the answer key about values. The October recommendation to extend the rubric to state the expected grain still applies to the quarter of wrong answers that have too many rows and the further eighth that have too few, and it cannot reach the 55% that already have the right shape.

---

## 8. How this compares with SQLite

| quantity | SQLite (135 questions) | BigQuery (204 questions) |
|---|---|---|
| single greedy run | 34.8% in September, with a different model (Qwen3.5-9B) | 42.2% to 47.5%, depending on the run |
| pass@1, mean of 4 samples at temperature 0.7 | 47.4% baseline, 51.1% with richer `describe_table` (Qwen3.6-35B) | **not measured** |
| solved by any of 4 samples at temperature 0.7 | 94 of 135 (69.6%) (Qwen3.6-35B) | 139 of 204 (68.1%) from one greedy run and four samples, taken only on the greedy failures |

Two points of caution apply. The SQLite figures at temperature 0.7 come from commit `49cca7d` and use the same Qwen3.6-35B model, whereas the 54.1% and 57.8% quoted in `CLAUDE.md` for September belong to a smaller model (Qwen3.5-9B) and should not be set beside the BigQuery figures. In addition, the BigQuery "any attempt" figure uses five attempts on the questions `R` got wrong and one on the rest, and SQLite's uses four attempts on every question, so the two figures are close to each other but built differently.

The comparison  asked for, pass@1 averaged over four samples on every question, has not been run on BigQuery. From this round's data, four samples of one configuration over all 204 questions would read about 5 TiB (roughly $31) and keep the GPU busy for about three and a half hours, and a matched control would double both. It needs the team's agreement under our plan.

---

## 9. Cost and compliance with the project's rules

| item | BigQuery billed | at $6.25/TiB |
|---|---:|---:|
| statistics pass | 582.5 GiB | $3.6 |
| 40-question pilot, both arms | 267 GiB | $1.6 |
| `C`, `T`, `C2`, `R` | 1.4 + 1.5 + 1.1 + 1.3 TiB | $8.8 + $9.4 + $6.9 + $8.1 |
| four retries | 3.0 TiB | $18.8 |
| **total, all work today** | **9.2 TiB** | **about $57** |

After the 1 TiB monthly free allowance the charge is about $51. The $150 guideline has not been reached. Every job carried `cost_center=rohini`, and `bq_spend.py` reads the figures from BigQuery's own job history. The model ran on Modal for roughly eight hours in total with the server warm; we did not read Modal's bill. No Google Cloud resource apart from query jobs was created, so nothing on Google Cloud needs to be stopped. No Google Cloud GPU was used, and Modal's server shuts itself down after 20 minutes without traffic. We left the Modal deployment itself in place because stopping it would require redeploying for any follow-up.

---

## 10. Limitations

1. **One replicate of the main comparison.** `R` and `C2` were each run once. Identical greedy runs differ by a net of a few questions (one point between `C` and `C2`, and five and a half points between October's two runs with identical prompts), so part of the 9-question difference between `R` and `C2` could be chance. The split by gate (+19/−8 where the check can act, −2 where it cannot) and the question-by-question trace of the 18 firings both point to the check as the cause. A second `R` run beside two further controls would settle the matter for about $24 of BigQuery reads.
2. **The check was designed on the questions it is scored on.** We read failing answers from this benchmark, including `bq060`, `bq172` and `bq396`, before writing the check. A fair test of its value needs questions that played no part in its design, for example the SQLite lane.
3. **The retry stage used the answer key to choose its questions.** The figure of 139 counts the questions solved by any attempt, and the accuracy of a single answer remains 47.5%.
4. **The rubric is imperfect.** It was wrong about the row count on 5 of 123 questions, and the check cost one right answer to a wrong rubric.
5. **Shared inputs.** `C2` and `R` reuse the rubric files written for `C`; `T` used its own. The row-shape tallies in Section 7.4 use the rubric files from `C` for every column.
6. **Other changes since October.** Between October and this round the Google Cloud project and the warning text of `get_column_values` changed, and so did whether the rubric reached the prompt. The comparison with October's runs is therefore indicative, and only the side-by-side arms are controlled.
7. **The 205th question.** One BigQuery question (`open_targets_genetics_1`) cannot be read with our credentials and is excluded from every November run, so the denominator is 204. October's `bq_v3r` had 200 scored questions.
8. **Counting rows.** An early version of our own row-shape tally for this round read the length of the display preview, as the October script does, and gave a misleading picture; the tables above use the real row counts. The October script `wrong_answer_shapes.py` has not been changed.
9. **Cause of run-to-run variation.** We measured it and did not investigate it. Non-deterministic batching on the GPU is a plausible source.

---

## 11. Recommended next steps

1. **Replicate before relying on the check.** Run `R` again beside two more controls (about $24 of BigQuery reads and three hours of GPU time), and apply the check to the SQLite lane, where it costs nothing in warehouse spend and was not tuned on those questions.
2. **Improve the check's message.** Include the rubric's list of columns in the bounce so that the model does not satisfy the row count by dropping a column, as it did in `bq076`. The three questions on which the rubric's count was wrong (`bq130`, `bq339`, `bq462`) suggest a second refinement: let the check fire only when the rubric's row count also agrees with what the question's wording asks for, for example a question that says "which month" asks for one month.
3. **Measure pass@1 as the SQLite team does.** Four samples at temperature 0.7 on all 204 questions would read about 5 TiB (roughly $31) per configuration and take about three and a half GPU hours; the plan calls for the team's agreement, and a note to the project administrators, before this starts.
4. **Build a selector over the attempts.** In the data we have, 14 of the 42 rescued questions were right in at least three of four tries, and 30 in at least two. A majority vote over the attempts' result tables, or a judge that compares them, could recover many of these. To score it fairly it must also be run on the questions greedy got right, which we did not sample.
5. **Look at questions with documents.** Their solve rate is half that of the others even though the model always reads the document.
6. **Raise the harness limits only for the 22 failures that the limits cause.** Section 7.6 gives the count; trying them alone is much cheaper than raising limits for the whole benchmark.
7. **Add an erratum to `bigquery_lane_analysis.md`** for the rubric result and the shape table (Section 7.8).

---

## Appendix A. Outcome of every question in every run

`1` correct, `.` wrong, `-` not scored. "Oct `bq_v3r`" is October's run; the other columns are this round. The four "try" columns exist only for questions `R` answered wrongly. The last column states how each question was finally solved: "greedy" if `R` was right, "tries n/4" if only temperature-0.7 attempts were right, and "never" otherwise.

| question | database | Oct `bq_v3r` | `C` | `T` | `C2` | `R` | try 1 | try 2 | try 3 | try 4 | outcome |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|---|
| `bq001` | ga360 | 1 | 1 | . | 1 | . | 1 | 1 | 1 | 1 | tries 4/4 |
| `bq002` | ga360 | 1 | . | 1 | . | . | . | 1 | . | . | tries 1/4 |
| `bq003` | ga360 | . | . | 1 | 1 | . | . | . | . | . | never |
| `bq004` | ga360 | 1 | . | 1 | . | 1 |   |   |   |   | greedy |
| `bq006` | austin | . | . | 1 | . | 1 |   |   |   |   | greedy |
| `bq008` | ga360 | . | . | . | . | . | . | . | . | . | never |
| `bq009` | ga360 | . | . | . | . | . | . | . | . | . | never |
| `bq010` | ga360 | . | 1 | 1 | 1 | . | 1 | 1 | . | 1 | tries 3/4 |
| `bq011` | ga4 | 1 | 1 | 1 | . | . | 1 | 1 | 1 | 1 | tries 4/4 |
| `bq018` | covid19_open_data | 1 | . | . | . | . | 1 | 1 | . | . | tries 2/4 |
| `bq019` | cms_data | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq021` | new_york | . | 1 | . | 1 | 1 |   |   |   |   | greedy |
| `bq022` | chicago | . | . | . | . | . | . | . | . | . | never |
| `bq023` | fec | . | 1 | . | . | . | . | . | 1 | 1 | tries 2/4 |
| `bq024` | usfs_fia | . | . | . | . | . | . | . | . | . | never |
| `bq025` | census_bureau_internationa | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq030` | covid19_open_data | 1 | . | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq031` | noaa_data | . | . | . | . | . | . | . | . | . | never |
| `bq032` | noaa_data | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq034` | ghcn_d | . | . | . | . | . | . | . | . | . | never |
| `bq035` | san_francisco | . | . | . | . | . | . | 1 | 1 | . | tries 2/4 |
| `bq038` | new_york | . | . | . | . | . | . | . | . | . | never |
| `bq039` | new_york_plus | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq040` | new_york_plus | 1 | 1 | . | 1 | 1 |   |   |   |   | greedy |
| `bq041` | stackoverflow | . | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq042` | noaa_data | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq045` | noaa_data | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq046` | TCGA_bioclin_v0 | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq047` | new_york_noaa | 1 | . | . | . | 1 |   |   |   |   | greedy |
| `bq048` | new_york_noaa | . | . | . | . | 1 |   |   |   |   | greedy |
| `bq049` | iowa_liquor_sales_plus | . | . | . | . | . | . | . | . | . | never |
| `bq051` | new_york_ghcn | 1 | 1 | . | . | . | 1 | . | 1 | . | tries 2/4 |
| `bq053` | new_york | . | . | 1 | . | . | . | 1 | . | . | tries 1/4 |
| `bq054` | new_york | . | . | . | . | . | . | . | . | . | never |
| `bq055` | google_dei | 1 | . | . | . | . | . | 1 | . | . | tries 1/4 |
| `bq059` | san_francisco_plus | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq060` | census_bureau_internationa | 1 | . | . | . | 1 |   |   |   |   | greedy |
| `bq061` | census_bureau_acs_1 | 1 | 1 | . | . | 1 |   |   |   |   | greedy |
| `bq064` | census_bureau_acs_1 | . | . | . | . | . | . | . | . | . | never |
| `bq066` | sdoh | 1 | . | 1 | 1 | . | 1 | 1 | . | . | tries 2/4 |
| `bq067` | nhtsa_traffic_fatalities | . | . | . | . | . | . | . | . | . | never |
| `bq074` | sdoh | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq075` | google_dei | 1 | . | . | . | . | . | . | . | . | never |
| `bq076` | chicago | . | . | . | . | . | . | . | . | . | never |
| `bq077` | chicago | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq079` | usfs_fia | . | . | . | . | . | 1 | 1 | . | 1 | tries 3/4 |
| `bq081` | san_francisco_plus | . | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq085` | covid19_jhu_world_bank | . | . | . | . | . | . | . | . | . | never |
| `bq086` | covid19_open_world_bank | 1 | . | . | 1 | 1 |   |   |   |   | greedy |
| `bq087` | covid19_symptom_search | 1 | . | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq088` | covid19_symptom_search | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq089` | covid19_usa | . | . | . | . | . | . | . | . | . | never |
| `bq090` | CYMBAL_INVESTMENTS | . | . | . | 1 | . | . | . | . | . | never |
| `bq094` | fec | . | . | . | . | . | . | . | . | . | never |
| `bq096` | gbif | . | . | . | . | . | . | . | . | . | never |
| `bq097` | sdoh | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq098` | new_york_plus | 1 | 1 | 1 | . | 1 |   |   |   |   | greedy |
| `bq102` | gnomAD | . | . | . | . | . | . | . | . | . | never |
| `bq103` | gnomAD | . | . | . | . | 1 |   |   |   |   | greedy |
| `bq105` | nhtsa_traffic_fatalities_p | . | . | . | 1 | . | . | . | 1 | 1 | tries 2/4 |
| `bq108` | nhtsa_traffic_fatalities | 1 | 1 | . | 1 | 1 |   |   |   |   | greedy |
| `bq110` | sdoh | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq111` | mitelman | . | . | . | . | . | . | . | . | . | never |
| `bq112` | bls | . | . | . | . | . | . | . | . | . | never |
| `bq113` | bls | . | . | . | 1 | 1 |   |   |   |   | greedy |
| `bq114` | openaq | 1 | 1 | . | 1 | 1 |   |   |   |   | greedy |
| `bq115` | census_bureau_internationa | . | . | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq116` | sec_quarterly_financials | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq119` | noaa_data | 1 | 1 | . | . | 1 |   |   |   |   | greedy |
| `bq120` | sdoh | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq123` | stackoverflow | . | . | . | . | . | . | . | . | 1 | tries 1/4 |
| `bq124` | fhir_synthea | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq126` | the_met | 1 | 1 | 1 | . | . | 1 | 1 | 1 | . | tries 3/4 |
| `bq130` | covid19_nyt | . | . | . | . | . | . | . | . | . | never |
| `bq137` | census_bureau_usa | . | . | . | . | . | . | . | . | . | never |
| `bq143` | CPTAC_PDC | . | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq144` | ncaa_insights | 1 | 1 | 1 | . | 1 |   |   |   |   | greedy |
| `bq151` | pancancer_atlas_2 | . | 1 | . | . | . | 1 | . | 1 | . | tries 2/4 |
| `bq161` | pancancer_atlas_2 | 1 | 1 | . | 1 | 1 |   |   |   |   | greedy |
| `bq162` | HTAN_1 | . | . | . | . | . | . | . | . | . | never |
| `bq165` | mitelman | . | . | . | . | . | . | . | . | . | never |
| `bq169` | mitelman | . | . | . | . | . | . | . | . | . | never |
| `bq172` | cms_data | 1 | . | . | 1 | 1 |   |   |   |   | greedy |
| `bq177` | cms_data | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq181` | noaa_data | . | . | . | . | . | . | . | . | . | never |
| `bq185` | new_york_plus | 1 | . | . | . | . | 1 | . | 1 | . | tries 2/4 |
| `bq186` | san_francisco | . | . | . | . | . | . | . | . | . | never |
| `bq198` | ncaa_basketball | 1 | . | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq199` | iowa_liquor_sales | . | . | . | . | 1 |   |   |   |   | greedy |
| `bq200` | mlb | 1 | . | . | . | . | . | . | . | . | never |
| `bq202` | new_york_plus | . | . | . | . | . | . | . | . | . | never |
| `bq203` | new_york_plus | . | 1 | . | 1 | . | . | 1 | 1 | . | tries 2/4 |
| `bq204` | eclipse_megamovie | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq208` | new_york_noaa | 1 | . | . | . | . | . | . | . | 1 | tries 1/4 |
| `bq218` | iowa_liquor_sales | . | . | . | . | . | . | . | . | . | never |
| `bq220` | usfs_fia | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq227` | london | . | 1 | . | . | . | 1 | . | . | . | tries 1/4 |
| `bq228` | london | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq229` | open_images | 1 | . | 1 | 1 | . | 1 | 1 | . | . | tries 2/4 |
| `bq230` | usda_nass_agriculture | 1 | 1 | . | 1 | 1 |   |   |   |   | greedy |
| `bq232` | london | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq234` | cms_data | . | . | . | . | . | . | . | . | . | never |
| `bq235` | cms_data | 1 | 1 | 1 | 1 | . | 1 | 1 | 1 | 1 | tries 4/4 |
| `bq268` | ga360 | 1 | 1 | . | . | 1 |   |   |   |   | greedy |
| `bq269` | ga360 | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq270` | ga360 | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq275` | ga360 | . | . | . | . | . | . | . | . | . | never |
| `bq277` | noaa_ports | . | . | . | . | . | . | . | . | . | never |
| `bq278` | sunroof_solar | 1 | 1 | 1 | . | 1 |   |   |   |   | greedy |
| `bq279` | austin | . | . | . | . | 1 |   |   |   |   | greedy |
| `bq280` | stackoverflow | 1 | . | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq281` | austin | . | . | . | . | 1 |   |   |   |   | greedy |
| `bq282` | austin | . | . | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq284` | bbc | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq285` | fda | . | . | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq286` | usa_names | . | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq287` | fda | . | . | . | . | . | . | . | . | . | never |
| `bq288` | fda | 1 | 1 | . | 1 | 1 |   |   |   |   | greedy |
| `bq290` | noaa_data | 1 | . | . | . | . | . | . | . | . | never |
| `bq293` | new_york_geo | . | . | . | . | . | . | . | . | . | never |
| `bq300` | stackoverflow | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq301` | stackoverflow | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq302` | stackoverflow | 1 | . | 1 | 1 | . | . | . | 1 | 1 | tries 2/4 |
| `bq303` | stackoverflow | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq304` | stackoverflow | . | 1 | 1 | . | . | 1 | . | 1 | . | tries 2/4 |
| `bq305` | stackoverflow | . | . | . | 1 | . | 1 | 1 | 1 | . | tries 3/4 |
| `bq306` | stackoverflow | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq308` | stackoverflow | . | . | 1 | . | . | . | . | 1 | . | tries 1/4 |
| `bq309` | stackoverflow | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq310` | stackoverflow | 1 | . | . | 1 | 1 |   |   |   |   | greedy |
| `bq326` | world_bank | . | . | 1 | . | . | . | 1 | 1 | 1 | tries 3/4 |
| `bq327` | world_bank | 1 | . | 1 | . | . | . | . | . | 1 | tries 1/4 |
| `bq328` | world_bank | . | . | . | . | . | . | . | 1 | . | tries 1/4 |
| `bq330` | fda | . | 1 | . | . | 1 |   |   |   |   | greedy |
| `bq338` | census_bureau_acs_1 | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq339` | san_francisco_plus | . | . | . | . | . | . | 1 | . | . | tries 1/4 |
| `bq352` | sdoh | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq354` | cms_data | . | . | . | . | . | . | . | . | . | never |
| `bq355` | cms_data | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq356` | noaa_data | 1 | 1 | . | 1 | 1 |   |   |   |   | greedy |
| `bq357` | noaa_data | . | 1 | . | . | 1 |   |   |   |   | greedy |
| `bq360` | nppes | . | . | . | . | . | . | . | . | . | never |
| `bq362` | chicago | 1 | 1 | 1 | . | 1 |   |   |   |   | greedy |
| `bq363` | chicago | . | . | . | . | . | . | . | . | . | never |
| `bq366` | the_met | 1 | . | . | . | . | . | . | . | 1 | tries 1/4 |
| `bq374` | ga360 | . | . | . | . | . | . | . | . | . | never |
| `bq376` | san_francisco_plus | . | . | . | . | . | . | . | . | . | never |
| `bq383` | ghcn_d | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq389` | epa_historical_air_quality | . | . | 1 | 1 | . | . | 1 | 1 | 1 | tries 3/4 |
| `bq391` | fhir_synthea | . | 1 | . | 1 | 1 |   |   |   |   | greedy |
| `bq392` | noaa_gsod | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq393` | hacker_news | . | . | . | . | 1 |   |   |   |   | greedy |
| `bq394` | noaa_data | 1 | 1 | 1 | . | 1 |   |   |   |   | greedy |
| `bq395` | sdoh | . | . | . | . | 1 |   |   |   |   | greedy |
| `bq396` | nhtsa_traffic_fatalities | 1 | . | . | . | . | . | 1 | 1 | 1 | tries 3/4 |
| `bq397` | ecommerce | . | . | 1 | . | 1 |   |   |   |   | greedy |
| `bq398` | world_bank | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq399` | world_bank | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq400` | san_francisco_plus | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq402` | ecommerce | . | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq403` | irs_990 | . | . | . | . | . | . | . | . | . | never |
| `bq406` | google_dei | . | . | . | . | . | . | . | . | . | never |
| `bq407` | covid19_usa | 1 | 1 | 1 | 1 | . | . | 1 | 1 | 1 | tries 3/4 |
| `bq413` | dimensions_ai_covid19 | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `bq414` | the_met | . | 1 | 1 | . | 1 |   |   |   |   | greedy |
| `bq418` | targetome_reactome | . | . | . | . | . | . | . | . | . | never |
| `bq419` | noaa_data | . | 1 | . | 1 | 1 |   |   |   |   | greedy |
| `bq424` | world_bank | 1 | 1 | 1 | 1 | . | 1 | . | . | 1 | tries 2/4 |
| `bq425` | ebi_chembl | . | . | . | . | . | . | . | . | . | never |
| `bq427` | ncaa_basketball | . | . | . | . | . | . | . | . | . | never |
| `bq428` | ncaa_basketball | . | . | . | . | . | . | . | . | . | never |
| `bq430` | ebi_chembl | . | . | . | . | . | . | . | . | . | never |
| `bq432` | fda | . | . | . | . | . | . | . | . | . | never |
| `bq441` | nhtsa_traffic_fatalities | . | . | . | . | . | . | . | . | . | never |
| `bq442` | CYMBAL_INVESTMENTS | . | . | . | . | . | . | . | . | . | never |
| `bq445` | gnomAD | 1 | . | 1 | . | . | 1 | . | 1 | . | tries 2/4 |
| `bq457` | libraries_io | . | . | . | . | . | . | . | . | . | never |
| `bq461` | ncaa_basketball | . | . | . | . | . | 1 | 1 | 1 | 1 | tries 4/4 |
| `bq462` | ncaa_basketball | . | . | . | . | . | . | . | . | . | never |
| `ga001` | ga4 | . | . | 1 | 1 | 1 |   |   |   |   | greedy |
| `ga002` | ga4 | 1 | 1 | . | 1 | . | . | . | 1 | . | tries 1/4 |
| `ga003` | firebase | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `ga004` | ga4 | . | 1 | . | . | 1 |   |   |   |   | greedy |
| `ga005` | firebase | . | . | . | . | . | . | . | . | . | never |
| `ga006` | ga4 | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `ga007` | ga4 | 1 | . | . | . | . | 1 | . | 1 | 1 | tries 3/4 |
| `ga008` | ga4 | 1 | . | 1 | 1 | . | 1 | 1 | 1 | 1 | tries 4/4 |
| `ga009` | ga4 | 1 | . | 1 | . | . | . | . | . | . | never |
| `ga010` | ga4 | . | . | . | . | . | . | . | . | . | never |
| `ga011` | ga4 | . | . | 1 | . | 1 |   |   |   |   | greedy |
| `ga012` | ga4 | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `ga013` | ga4 | . | . | . | 1 | 1 |   |   |   |   | greedy |
| `ga014` | ga4 | . | . | . | . | . | . | . | . | . | never |
| `ga017` | ga4 | 1 | 1 | 1 | 1 | 1 |   |   |   |   | greedy |
| `ga018` | ga4 | . | . | . | . | . | . | . | . | . | never |
| `ga019` | firebase | 1 | 1 | . | . | 1 |   |   |   |   | greedy |
| `ga020` | firebase | - | . | . | . | . | . | . | . | . | never |
| `ga021` | firebase | - | . | . | . | . | . | . | . | . | never |
| `ga022` | firebase | - | . | 1 | 1 | . | . | . | . | . | never |
| `ga025` | firebase | - | 1 | . | 1 | . | . | . | 1 | 1 | tries 2/4 |
| `ga028` | firebase | . | . | . | . | . | . | . | . | . | never |
| `ga030` | firebase | . | . | . | . | 1 |   |   |   |   | greedy |
| `ga031` | ga4 | . | . | . | . | . | . | . | . | . | never |
| `ga032` | ga4 | 1 | 1 | . | . | . | . | 1 | 1 | . | tries 2/4 |

## Appendix B. The rescued and the never-solved questions in detail

"Submitted rows" is the real row count of the greedy `R` answer. "Gold rows" lists the row counts of the accepted reference tables (a question may have several accepted layouts). "Rubric said" is the planner's high-confidence row count where it gave one. A dash in "submitted rows" means the run ran out of steps without a submission.

#### Recovered only by a temperature-0.7 try (42)

| question | database | greedy `R` submitted rows | gold rows | rubric said | steps | tries right | kind of miss |
|---|---|--:|--:|--:|--:|--|---|
| `bq001` | ga360 | 20 | 666 | - | 10 | 4/4 | too few rows |
| `bq002` | ga360 | 181 | 1/3 | 1 | 60 | 1/4 | ran out of steps |
| `bq010` | ga360 | 1 | 1 | 1 | 24 | 3/4 | right row count |
| `bq011` | ga4 | 1 | 1 | 1 | 7 | 4/4 | right row count |
| `bq018` | covid19_open_data | 1 | 1 | 1 | 13 | 2/4 | right row count |
| `bq023` | fec | 758 | 758/761 | - | 13 | 2/4 | right row count |
| `bq035` | san_francisco | 700 | 700 | - | 13 | 2/4 | right row count |
| `bq051` | new_york_ghcn | 2 | 2 | 2 | 34 | 2/4 | right row count |
| `bq053` | new_york | 13 | 8/13 | - | 24 | 1/4 | right row count |
| `bq055` | google_dei | 5 | 3 | - | 20 | 1/4 | too many rows |
| `bq066` | sdoh | 3 | 3 | 3 | 24 | 2/4 | right row count |
| `bq079` | usfs_fia | 2 | 2 | 2 | 21 | 3/4 | right row count |
| `bq105` | nhtsa_traffic_fatalities | 85 | 10/101 | - | 46 | 2/4 | too few rows |
| `bq123` | stackoverflow | 1 | 1 | 1 | 7 | 1/4 | right row count |
| `bq126` | the_met | 20 | 17/32 | - | 8 | 3/4 | too few rows |
| `bq151` | pancancer_atlas_2 | 1 | 1 | 1 | 17 | 2/4 | right row count |
| `bq185` | new_york_plus | 1 | 1 | 1 | 6 | 2/4 | right row count |
| `bq203` | new_york_plus | 5 | 5 | - | 38 | 2/4 | right row count |
| `bq208` | new_york_noaa | 3 | 3 | - | 22 | 1/4 | right row count |
| `bq227` | london | 5 | 9 | - | 8 | 1/4 | too few rows |
| `bq229` | open_images | 1 | 1/2 | 1 | 18 | 2/4 | right row count |
| `bq235` | cms_data | 10 | 1 | - | 11 | 4/4 | too many rows |
| `bq302` | stackoverflow | 9 | 9 | - | 7 | 2/4 | right row count |
| `bq304` | stackoverflow | 176 | 500 | - | 9 | 2/4 | too few rows |
| `bq305` | stackoverflow | 10 | 10 | 10 | 17 | 3/4 | right row count |
| `bq308` | stackoverflow | 7 | 7 | 7 | 7 | 1/4 | right row count |
| `bq326` | world_bank | 1 | 1 | 1 | 14 | 3/4 | right row count |
| `bq327` | world_bank | 1 | 1 | 1 | 6 | 1/4 | right row count |
| `bq328` | world_bank | 7 | 1 | - | 12 | 1/4 | too many rows |
| `bq339` | san_francisco_plus | 12 | 1 | 12 | 9 | 1/4 | too many rows |
| `bq366` | the_met | 17 | 901/4390/4426 | - | 14 | 1/4 | too few rows |
| `bq389` | epa_historical_air_quali | 72 | 12/72 | - | 19 | 3/4 | right row count |
| `bq396` | nhtsa_traffic_fatalities | 3 | 3 | 3 | 9 | 3/4 | right row count |
| `bq407` | covid19_usa | 3 | 3 | - | 14 | 3/4 | right row count |
| `bq424` | world_bank | 10 | 10 | 10 | 31 | 2/4 | right row count |
| `bq445` | gnomAD | 1 | 1 | 1 | 37 | 2/4 | right row count |
| `bq461` | ncaa_basketball | 1 | 75 | - | 16 | 4/4 | too few rows |
| `ga002` | ga4 | 3 | 3 | - | 13 | 1/4 | right row count |
| `ga007` | ga4 | - | 1 | 1 | 60 | 3/4 | ran out of steps |
| `ga008` | ga4 | 30 | 30 | - | 7 | 4/4 | right row count |
| `ga025` | firebase | - | 1 | 1 | 60 | 2/4 | ran out of steps |
| `ga032` | ga4 | 1 | 1 | 1 | 28 | 2/4 | right row count |

#### Never solved by greedy `R` or any try (65)

| question | database | greedy `R` submitted rows | gold rows | rubric said | steps | solved by another full run | kind of miss |
|---|---|--:|--:|--:|--:|--|---|
| `bq003` | ga360 | - | 4/8 | - | 60 | T,C2 | ran out of steps |
| `bq008` | ga360 | 1 | 1 | 1 | 26 | - | right row count |
| `bq009` | ga360 | 1 | 1 | 1 | 10 | - | right row count |
| `bq022` | chicago | 6 | 6 | 6 | 5 | - | right row count |
| `bq024` | usfs_fia | 10 | 10 | 10 | 24 | - | right row count |
| `bq031` | noaa_data | 50 | 82 | - | 21 | - | too few rows |
| `bq034` | ghcn_d | 462 | 100/445 | - | 6 | - | too many rows |
| `bq038` | new_york | 10 | 10 | 10 | 21 | - | right row count |
| `bq049` | iowa_liquor_sales_plus | 12 | 12 | 12 | 19 | - | right row count |
| `bq054` | new_york | 10 | 10 | 10 | 19 | - | right row count |
| `bq064` | census_bureau_acs_1 | 16 | 17 | - | 30 | - | too few rows |
| `bq067` | nhtsa_traffic_fatalities | 20 | 13827/13848/25422 | - | 38 | - | too few rows |
| `bq075` | google_dei | 6 | 4 | - | 21 | - | too many rows |
| `bq076` | chicago | 1 | 1 | 1 | 6 | - | right row count |
| `bq085` | covid19_jhu_world_bank | - | 7 | 7 | 31 | - | ran out of steps |
| `bq089` | covid19_usa | 1 | 50/58 | 1 | 14 | - | too few rows |
| `bq090` | CYMBAL_INVESTMENTS | 1 | 1 | 1 | 15 | C2 | right row count |
| `bq094` | fec | 4 | 224/226/238/279/286/294 | - | 21 | - | too few rows |
| `bq096` | gbif | - | 1 | 1 | 60 | - | no submission |
| `bq102` | gnomAD | - | 166/184 | - | 60 | - | ran out of steps |
| `bq111` | mitelman | - | 21/42 | - | 60 | - | ran out of steps |
| `bq112` | bls | 1 | 1 | 1 | 28 | - | right row count |
| `bq130` | covid19_nyt | 5 | 10/26/27 | 5 | 13 | - | too few rows |
| `bq137` | census_bureau_usa | 31 | 30/31 | - | 11 | - | right row count |
| `bq162` | HTAN_1 | 3 | 3 | - | 23 | - | right row count |
| `bq165` | mitelman | 320 | 320 | - | 33 | - | right row count |
| `bq169` | mitelman | 124 | 119/139 | - | 16 | - | too few rows |
| `bq181` | noaa_data | 1 | 1 | 1 | 22 | - | right row count |
| `bq186` | san_francisco | 37 | 37 | - | 5 | - | right row count |
| `bq200` | mlb | - | 30 | - | 29 | - | ran out of steps |
| `bq202` | new_york_plus | 1 | 1 | 1 | 8 | - | right row count |
| `bq218` | iowa_liquor_sales | 5 | 5 | 5 | 10 | - | right row count |
| `bq234` | cms_data | 61 | 51/61 | - | 6 | - | right row count |
| `bq275` | ga360 | 230 | 8/23/33/37 | - | 9 | - | too many rows |
| `bq277` | noaa_ports | - | 1 | 1 | 60 | - | ran out of steps |
| `bq287` | fda | - | 1 | 1 | 60 | - | ran out of steps |
| `bq290` | noaa_data | 31 | 31 | 31 | 10 | - | right row count |
| `bq293` | new_york_geo | 5 | 5 | - | 29 | - | right row count |
| `bq354` | cms_data | - | 4 | 4 | 60 | - | ran out of steps |
| `bq360` | nppes | 1 | 10 | 1 | 11 | - | too few rows |
| `bq363` | chicago | 10 | 10 | 10 | 12 | - | right row count |
| `bq374` | ga360 | 1 | 1 | 1 | 13 | - | right row count |
| `bq376` | san_francisco_plus | 62 | 11/117 | - | 15 | - | too few rows |
| `bq403` | irs_990 | 3 | 3 | 3 | 14 | - | right row count |
| `bq406` | google_dei | 9 | 1/9 | 9 | 17 | - | right row count |
| `bq418` | targetome_reactome | 3 | 3 | 3 | 40 | - | right row count |
| `bq425` | ebi_chembl | 605 | 100 | - | 38 | - | too many rows |
| `bq427` | ncaa_basketball | 5 | 5 | - | 11 | - | right row count |
| `bq428` | ncaa_basketball | 40 | 95 | - | 17 | - | too few rows |
| `bq430` | ebi_chembl | 809 | 179/777/809 | - | 29 | - | right row count |
| `bq432` | fda | 183 | 183 | - | 47 | - | right row count |
| `bq441` | nhtsa_traffic_fatalities | 1 | 74270/81620 | - | 36 | - | too few rows |
| `bq442` | CYMBAL_INVESTMENTS | 6 | 6 | 6 | 6 | - | right row count |
| `bq457` | libraries_io | 42 | 4 | - | 14 | - | too many rows |
| `bq462` | ncaa_basketball | 17 | 17 | 20 | 41 | - | right row count |
| `ga005` | firebase | - | 11 | - | 60 | - | ran out of steps |
| `ga009` | ga4 | 1 | 1 | 1 | 37 | T | right row count |
| `ga010` | ga4 | 5 | 1/4 | - | 14 | - | too many rows |
| `ga014` | ga4 | 8 | 5 | - | 39 | - | too many rows |
| `ga018` | ga4 | 1 | 1 | 1 | 41 | - | right row count |
| `ga020` | firebase | - | 1 | - | 60 | - | ran out of steps |
| `ga021` | firebase | 3 | 6 | - | 23 | - | too few rows |
| `ga022` | firebase | 1 | 1 | 1 | 16 | T,C2 | right row count |
| `ga028` | firebase | - | 1/5 | 5 | 60 | - | ran out of steps |
| `ga031` | ga4 | 1 | 1 | 1 | 14 | - | right row count |

## Appendix C. Files and commands

**New or changed files (not committed):**

| file | change |
|---|---|
| `nl2sql-v2/src/nl2sql/bigquery_db.py` | impersonated credentials, `cost_center` label, optional statistics, louder fallback warning |
| `nl2sql-v2/src/nl2sql/lite_catalog.py` | reads the statistics and prints them in `describe_table` |
| `nl2sql-v2/src/nl2sql/agent.py` | `expected_rows` parameter and the row-count check |
| `nl2sql-v2/src/nl2sql/rubric.py` | comment only |
| `nl2sql-v2/scripts/run_benchmark.py` | `--bq-stats`, `--rubric-row-check`, guard against an empty rubric directory, statistics yield to descriptions in the schema dump |
| `nl2sql-v2/scripts/run_rubric.py` | `--bq-stats` |
| `nl2sql-v2/scripts/enrich_bq_stats.py` | the one-time statistics pass |
| `nl2sql-v2/scripts/check_row_check.py` | no-GPU test of the check |
| `nl2sql-v2/scripts/bq_spend.py`, `bigquery_preflight.py`, `check_bigquery_db.py` | new credentials, new wording |
| `nl2sql-v2/scripts/analysis/` | `run_arm.py` (drives one arm), `compare_arms.py` (paired comparison), `shapes_true.py` (true row shapes), `passk.py` (retry tally), and `instances/` (the question lists) |
| `spider2-dce/output/bigquery_stats/` | the statistics, one file per database |

**Reproducing the runs** (from the repository root; the endpoint is the Modal server):

```bash
# a control, a treatment, and a row-check arm over all 204 questions
A=nl2sql-v2/scripts/analysis        # the instance lists are comma-separated question ids
python $A/run_arm.py --tag full_C  --instances-file $A/instances/all204.txt --shards 5 --endpoint $EP
python $A/run_arm.py --tag full_T  --instances-file $A/instances/all204.txt --shards 5 --endpoint $EP --bq-stats spider2-dce/output/bigquery_stats
python $A/run_arm.py --tag full_R  --instances-file $A/instances/all204.txt --shards 5 --endpoint $EP --rubric-dir results/full_C/rubrics --row-check
# four retries of the failures at temperature 0.7 (repeat with failR_s2, failR_s3, failR_s4)
python $A/run_arm.py --tag failR_s1 --instances-file $A/instances/fail_R.txt --shards 5 --endpoint $EP --temperature 0.7 --rubric-dir results/full_C/rubrics --row-check

# analysis
uv run --project nl2sql-v2 python $A/compare_arms.py --c results/full_C2 --t results/full_R --exposure row_check --show
uv run --project nl2sql-v2 python $A/shapes_true.py
python $A/passk.py
uv run --project nl2sql-v2 python nl2sql-v2/scripts/error_taxonomy.py bq_v3:logs/traces/bq_v3:results/bq_v3_run.csv full_R:results/full_R/traces:results/full_R/all.csv
uv run --project nl2sql-v2 python nl2sql-v2/scripts/bq_spend.py --hours 72   # needs BIGQUERY_PROJECT and BIGQUERY_IMPERSONATE_SERVICE_ACCOUNT set
```
