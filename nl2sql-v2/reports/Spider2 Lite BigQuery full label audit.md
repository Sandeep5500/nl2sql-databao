# Spider 2.0-Lite BigQuery: an audit of all 204 labels

November 19, 2026. Follows [Spider2 Lite BigQuery gold errors](Spider2%20Lite%20BigQuery%20gold%20errors.md) (Nov 18),
which audited 13 questions.

## Summary

- **Why.** The Nov 18 audit read only the 13 questions where our answer-selection judges lost, so its corrections could
  only raise the judges' scores. This audit reads the other 191 of the 204 BigQuery questions in our evaluation, so a
  correction can now move a score in either direction.
- **How.** For every question we built an evidence packet from local files: the question, its documentation, the
  scoring setup, the gold SQL, every accepted gold file, and each of the agent's 4 answers with the result the agent
  saw. Auditors followed one written protocol, and a second auditor re-checked every change to the strict labels. No
  query was run on BigQuery.
- **Labels.** Of the 191 questions, 131 labels are right, 16 gold answers are wrong, 22 have scoring defects, 19 allow a
  second fair reading, and 3 are unclear. With the 13 from Nov 18, strict corrections change 34 questions (68 answers
  become right, 22 answers stop counting as right); lenient corrections, which also accept fair second readings, change
  59.
- **Causes.** Most problems come from Spider2's replacement of every gold file in November 2025: columns the question
  does not ask for became mandatory, formats vary between files, and some files contradict the question or each other.
  Others come from answers that merge different things sharing a name, from public tables that changed after the gold
  was made, and from two limits of our own harness.
- **Scores.** With the strict corrections, our production judge scores 125.9 of 204 (61.7%) instead of 114.2
  (56.0%); without the corrections for data drift, 121.9 (59.8%); with fair second readings also accepted, 146.0
  (71.6%). The judge keeps about the same lead over majority vote under every labelling.

## Why a full audit

On Nov 18 we audited the 13 BigQuery questions where our judges lost, and 12 of their 13 labels were flawed. Correcting
those raised the 35B judge's score by 1.7 to 5.6 picks of 204, but that comparison was biased: a question was audited only if the
judge lost there, so every correction favoured the judge. A fair corrected score needs every question checked, including
questions where all 4 answers already count as right (if the gold is wrong, they should not) and questions where none
does (if the gold is wrong, some may be right).

## Method

**Evidence packets** (one per question, from local files only): the question; the external document, if any; the
scoring setup (which gold columns must match, whether row order counts); the gold SQL, noting that Spider2 replaced the
gold files in November 2025 without updating the SQL; every accepted gold file with its shape and first rows; the 4
answers of our agent's November 17 run, each with its SQL and the result the agent saw; and the official score of each
answer. The auditors could also read the agents' full sessions, whose intermediate queries show facts about the data,
and the official documentation of each public dataset.

**Verdicts.** For each question the auditor decided one of:

| verdict | meaning |
|---|---|
| gold right | the accepted files answer the question, and every answer's official score is right |
| gold wrong | the accepted files contradict the question or the documentation |
| scoring defect | the gold is right in substance, but the scoring setup wrongly rejects or accepts an answer |
| two fair readings | the question allows another reading that a careful analyst could choose, and some answer takes it |
| unclear | the evidence does not decide it; no change |

**Two corrected views.** *Strict* fixes only wrong golds and scoring defects. *Lenient* also accepts answers that follow
a fair second reading. Both can remove credit: an answer that matched a wrong accepted file stops counting as right.

**Second check.** Every strict change (34 of them) went to a second auditor, who had to reproduce the decisive evidence
from the files; the burden of proof was on the change. 28 were confirmed and 6 rejected: 4 because the first auditor's
reading was fair but not the only one (they stay in the lenient view), and 2 because the evidence did not hold.

**Data drift is reported separately.** Five strict changes rest on public tables that changed after the gold was made
(the agents' queries follow the gold's own logic on today's data). The table below also shows strict corrections
without them.

## What we found

| verdict (191 newly audited questions) | questions |
|---|---|
| gold right | 131 |
| gold wrong | 16 |
| scoring defect | 22 |
| two fair readings | 19 |
| unclear | 3 |

126 verdicts were made with high confidence and 65 with medium. Some wrong golds change no label, because every answer
is wrong anyway.

**1. Columns the question does not ask for became mandatory (November 2025 files).** When a question's scoring setup
lists no required columns, every column of the gold file must match. The new files often add columns: a month next to a
count (bq076), both group averages next to the asked-for difference (ga004), a rate next to an event type (ga020), a
whole top-10 table with a yes/no flag spelled four ways where the question asks for one specialty (bq360), a constant
site column and yes/no flags (bq162). Answers that give exactly what was asked fail. Where the extra column answers part
of the question (bq112's "did wages keep pace?"), the second check kept the official label.

**2. Formats that no correct answer can match, or only by luck.** An array stored as JSON text (bq432), gene lists
spelled three ways (bq103), the day of the week numbered from Sunday or Monday (bq202), values rounded to 0.1 against a
0.01 tolerance (bq290), the order of plays that happen at the same moment (bq461), ties broken differently in each file
(bq186), and two accepted choices that no single file combines (bq199). In bq086 the required column points at
population instead of the percentage, so an answer with the right percentages fails.

**3. Gold files that contradict the question or each other.** bq009's 4,659.15 is not the difference between any two
monthly totals; the gold SQL, the old gold and three answers give 118,015.76. bq275's four files list 33, 23, 37 and 8
visitors, fragments of the 230 that qualify. bq374's rates imply 836 and 220 users where the stated definition gives
about 1,700. bq376's files list every neighbourhood with zero crimes, or use tables outside the question's database.
bq326 accepts a count that includes a world-region aggregate as a country.

**4. Different things merged under one name.** These corrections remove credit. bq019's accepted file groups hospitals
by city name alone, so "Springfield" pools several states; all 4 answers matched it. bq419's state column holds
two-letter cut-offs that pool states (Te = Tennessee + Texas), and every gold file and answer uses them. bq108 counts
crash victims by a person number that restarts in every vehicle. In bq198 one answer ranked team nicknames that merge
universities, and in bq120 one answer matched a file that ranks single office rows instead of counties.

**5. Public tables that changed after the gold was made (data drift).** The taxi trips table (bq022, bq362), a growing
weather-station list (bq034) and the Mitelman cancer database (bq169) now give different numbers, and answers that apply
the gold's own logic to today's data fail. A sixth claim (bq363) was rejected: its files also bin minutes differently.

**6. Limits of our own harness.** Our BigQuery harness keeps at most 5,000 result rows, while bq067's and bq441's gold
files have 13,827 and 74,270 rows or more, so no answer can pass; in bq067 the answers are also wrong for the reason in
bq108. bq111's queries on the TCGA tables are blocked in our harness. In bq406 the public table now stops in 2022 while
the gold needs 2024. No answer is right in these four questions, so they change no label, but they cannot be passed.

**7. Two fair readings.** 19 questions, each with a second reading some answer takes: the sign of a "change from 1995 to
2015" (bq053), whole-minute durations as BigQuery counts them against Snowflake's count (bq185), a medicine's brand name
against its active ingredient (bq234), each period's label count against the whole collection's (bq366), and others in
the table at the end. These count only in the lenient view.

The November 2025 Lite gold files are byte-identical to Spider2-Snow's, which fits several findings above: they appear
to have been computed on Snowflake's copy of the data, with Snowflake's date and time functions.

## Effect on the BigQuery scores

All 204 questions of the November 17 run (4 answers each). The judge is Qwen3.6-35B-A3B with the `diff_cmp` prompt;
its rows are the expected accuracy of one run, computed from every judge sample we have (12 per comparison, 4 on the
newly judged questions). The 23 questions where only the corrected labels give a mix of right and wrong answers were judged on Nov 19 for this
table, with the production settings.

| correct of 204 | official | strict | strict without drift | lenient |
|---|---|---|---|---|
| one answer (pass@1, average of the 4) | 98.0 (48.0%) | 109.2 (53.5%) | 106.0 (52.0%) | 123.8 (60.7%) |
| majority vote (ties at random) | 105.2 (51.6%) | 117.3 (57.5%) | 114.1 (55.9%) | 133.3 (65.3%) |
| judge, one call per comparison | 112.6 (55.2%) | 126.1 (61.8%) | 122.1 (59.8%) | 145.9 (71.5%) |
| **judge, production** (asks twice, superset rule) | **114.2 (56.0%)** | **125.9 (61.7%)** | **121.9 (59.8%)** | **146.0 (71.6%)** |
| any of the 4 answers right (pass@4) | 129 (63.2%) | 141 (69.1%) | 137 (67.2%) | 157 (77.0%) |

- **The corrections now go both ways**, and their net effect is large and upward: the November 2025 files reject many
  answers that are right in substance. Strict corrections add 12 questions that some answer gets right (pass@4) and
  11.2 to the average answer.
- **The judge's lead over majority vote holds**: +9.0 picks with official labels, +8.6 strict, +7.8 without drift,
  +12.7 lenient.
- **The production rule's gain is a gain under the official labels only.** Asking twice plus the superset rule adds
  +1.6 picks with official labels but −0.1 [−2.5, +1.8] with strict ones and +0.1 with lenient ones. Part of its
  official gain comes from questions whose labels the audit changed: in ga004 the rule picks the wider result that
  the new files wrongly require, and in bq199 the answer that happens to fit one accepted file; with corrected labels
  the other answers are right too. In bq161 the rule picks a wider result that holds the gold value only as a side
  column while its actual answer differs: right for the official scorer, wrong in substance (−0.9 there).
- 183 of the 776 calls on the 23 newly judged questions were drawn again after a preemption (long calls are the ones
  lost). Leaving those calls out changes these questions' totals by at most 0.3.

## Limits

- The auditors and second auditors are Claude agents reading local files; they could not query the warehouse, so a few
  verdicts rest on the rows an agent happened to see (the agents saw at most 50 rows of each result).
- Only strict changes had a second check. Lenient changes and "gold right" verdicts did not.
- 65 of the 191 verdicts were made with medium confidence.
- Whether a question "asks for" a column is sometimes a judgement (the second check reversed 4 such calls).
- The corrected labels are for our November 17 run's answers. They do not cover other runs' answers to the same
  questions.

## All changed questions

Right answers are numbered 0 to 3 (the 4 answers of the November 17 run). N18 = audited on Nov 18.

| question | official | strict | lenient | cause |
|---|---|---|---|---|
| bq002 | 2 | 2, 3 | 2, 3 | files use Monday-start weeks (Snowflake's default) (N18) |
| bq008 | none | none | 0, 2 | fair reading: a repeat /home view is the next page |
| bq009 | none | 0, 1, 2 | 0, 1, 2 | gold wrong: 4,659.15 is no difference of monthly totals |
| bq019 | 0, 1, 2, 3 | none | none | gold wrong: accepted file merges cities named Springfield |
| bq022 | none | 0, 1, 2, 3 | 0, 1, 2, 3 | data drift: taxi table changed, gold's own logic |
| bq034 | none | 1, 3 | 1, 3 | data drift: station list grew since the gold |
| bq035 | 1 | 1, 3 | 1, 3 | two Earth radii against the 0.01 tolerance (N18) |
| bq051 | 1 | 1 | 0, 1 | second fair reading of the quality flags (N18) |
| bq053 | none | none | 1, 3 | fair reading: sign of the change |
| bq054 | none | none | 0, 1 | fair reading: gold adds 2005 counts not asked for |
| bq055 | 0, 2 | 0, 1, 2, 3 | 0, 1, 2, 3 | six files mixing sign, scale and rounding (N18) |
| bq076 | none | 0, 1, 2, 3 | 0, 1, 2, 3 | mandatory month column the question does not ask for |
| bq086 | 1, 2 | 0, 1, 2 | 0, 1, 2 | required column is population, not the percentage |
| bq090 | none | none | 1 | fair reading: intrinsic value as the old gold defines it |
| bq102 | none | none | 2 | fair reading: exomes only |
| bq103 | 0, 3 | 0, 1, 2, 3 | 0, 1, 2, 3 | gene list as an array; files accept three spellings |
| bq108 | 0, 1, 2, 3 | none | none | gold wrong: person numbers restart in every vehicle |
| bq112 | none | none | 2, 3 | fair reading; strict rejected (the yes/no column is asked for) |
| bq120 | 0, 1, 2, 3 | 0, 1, 3 | 0, 1, 3 | gold wrong: accepted file ranks office rows, not counties |
| bq130 | none | none | 0, 1, 3 | fair reading: the five counties only |
| bq151 | 0 | 0 | 0, 1, 3 | two fair patient cohorts (N18) |
| bq161 | 0, 1, 2, 3 | 1 | 1, 2 | three answers matched through an incidental column |
| bq162 | none | 0, 1, 2 | 0, 1, 2 | mandatory constant column and flag formats |
| bq169 | none | 0, 1, 2, 3 | 0, 1, 2, 3 | data drift: newer Mitelman data |
| bq185 | none | none | 0, 1, 3 | fair reading: BigQuery's whole-minute count |
| bq186 | none | 0, 1, 2, 3 | 0, 1, 2, 3 | tied first and last trips; each file picks its own |
| bq198 | 0, 1, 2, 3 | 1, 2, 3 | 1, 2, 3 | one answer ranked nicknames that merge universities |
| bq199 | 1, 2 | 0, 1, 2, 3 | 0, 1, 2, 3 | two accepted choices that no file combines |
| bq202 | none | 0 | 0, 1, 2, 3 | Thursday numbered 5 (BigQuery) against 4; lenient: day and hour apart |
| bq208 | 1, 3 | 1, 3 | 1, 2, 3 | second fair reading (N18) |
| bq220 | 0, 2 | 0, 2 | 0, 2, 3 | fair reading: weights by plot_tree, named in the question |
| bq227 | 1 | 1 | 0, 1 | fair reading; strict rejected (shares packed into one text) |
| bq230 | 0, 1 | 0, 1 | 0, 1, 2, 3 | fair reading: the same totals stacked by commodity |
| bq234 | none | none | 0, 1, 3 | fair reading: drug name against active ingredient |
| bq275 | none | 0, 1, 2, 3 | 0, 1, 2, 3 | gold wrong: four inconsistent fragments of 230 visitors |
| bq278 | 0, 2, 3 | 0, 2, 3 | 0, 1, 2, 3 | fair reading: each state as the 50 states and DC |
| bq290 | none | 0, 1, 2, 3 | 0, 1, 2, 3 | values rounded to 0.1 fail the 0.01 tolerance |
| bq308 | 2 | 2 | 1, 2, 3 | second fair reading (N18) |
| bq326 | 0, 2, 3 | 0, 3 | 0, 3 | gold wrong: accepted count includes a region as a country |
| bq330 | none | none | 0 | fair reading of the per-block-group maximum |
| bq354 | none | none | 0, 3 | fair reading: category codes only, as the gold SQL |
| bq360 | none | 0, 1, 2, 3 | 0, 1, 2, 3 | whole top-10 table with a flag required for a one-item question |
| bq362 | none | 0, 2, 3 | 0, 2, 3 | data drift: taxi table changed |
| bq363 | none | none | 0, 1, 2 | fair reading; strict rejected (files also bin minutes differently) |
| bq366 | none | none | 0, 1, 2, 3 | fair reading: the threshold per period |
| bq374 | none | 0, 1, 2, 3 | 0, 1, 2, 3 | gold wrong: rates imply 836 and 220 users, not about 1,700 |
| bq376 | none | 0, 1, 2, 3 | 0, 1, 2, 3 | gold wrong: zero-crime rows, or tables outside the database |
| bq389 | 1, 3 | 0, 1, 3 | 0, 1, 3 | flat required-column list breaks 4 of 7 files (N18) |
| bq393 | 0, 2 | 0, 2 | 0, 1, 2, 3 | fair reading of which month, and how it is numbered |
| bq397 | 2, 3 | 2, 3 | 1, 2, 3 | hit-level against session-level totals (N18) |
| bq419 | 0, 1, 2, 3 | none | none | gold wrong: state column pools several states |
| bq424 | 0, 1, 2 | none | 0, 1, 2 | accepted file sums a debt stock over 51 years (N18) |
| bq432 | none | 0, 1 | 0, 1 | array stored as JSON text |
| bq461 | 1 | 0, 1, 3 | 0, 1, 3 | order of simultaneous plays |
| ga004 | 0 | 0, 1, 2, 3 | 0, 1, 2, 3 | mandatory group averages the question does not ask for |
| ga010 | 0 | 1, 2 | 0, 1, 2, 3 | name-only gold against a real session count (N18) |
| ga019 | none | none | 0, 1, 2 | fair reading: the first_open install event (old gold) |
| ga020 | none | 3 | 3 | mandatory rate the question does not ask for |
| ga031 | none | none | 0, 1, 2 | fair reading; strict rejected (landing-page reading also fits) |

## Files

- Evidence packets, protocols, verdicts, second checks and the label builder: `results/bq17/audit/` (not tracked;
  copies of the protocols, notes and corrected labels are in
  `nl2sql-v2/research_notes/Spider2 Lite BigQuery full label audit/`).
- Scoring: `results/prod_nov19/score_prod.py` (the official, strict, no-drift and lenient views).
