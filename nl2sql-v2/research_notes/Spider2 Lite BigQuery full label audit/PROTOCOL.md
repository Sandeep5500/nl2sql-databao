# BigQuery label audit: protocol (Nov 19 2026)

## Why

We score answer-selection judges on 204 Spider 2.0-Lite BigQuery questions. On Nov 18, 13 questions were audited
because the judges lost there, and 12 of their 13 labels turned out flawed (stale gold after Spider2 replaced every
gold file in Nov 2025, scoring-setup defects, questions with two fair readings). Auditing only the judges' losses biases
the corrected scores in the judges' favour. This audit covers every remaining question, so corrections can move scores
**in both directions**: a lane the official scorer counts right may be wrong in substance, and the reverse.

## Your inputs

- Your packets: `results/bq17/audit/packets/<iid>.md` (paths are from the repository root).
  Each has the question, the external document, the scoring setup, the gold SQL, every accepted gold file (shape and
  head), each lane's SQL with the result the agent saw, the official label per lane, automated flags, the schema, and
  Nov 18 readings where they exist.
- Full local files when a packet is not enough:
  - documents: `Spider2/spider2-lite/resource/documents/`
  - gold files: `Spider2/spider2-lite/evaluation_suite/gold/exec_result/<iid>[_a..].csv`
  - scoring config: `Spider2/spider2-lite/evaluation_suite/gold/spider2lite_eval.jsonl`
  - lane traces (the agent's whole session, including its intermediate queries and their results, which show facts
    about the data): `results/bq17/bigquery_passk_nov2026_17/lane_k{1,2,3,4}/traces/<iid>.json` (lane 0 = k1, ...)
- Examples of finished audits: `nl2sql-v2/reports/Spider2 Lite BigQuery gold errors.md` (read its verdict table and
  one or two cases to calibrate; do not re-audit those 13 questions).

## Hard rules

- Never run anything against BigQuery or any cloud service. Do not install or import Google Cloud libraries. Do not
  open credential or key files (anything named like `*credential*`, `*.env`, `*key*.json`).
- Local files only, plus WebSearch/WebFetch for the official documentation of a public dataset (Google Cloud dataset
  pages, the data owner's documentation such as NOAA, Census, CMS, GA4/GA360 export schema docs). No curl or wget. Never
  put names, e-mail addresses or other personal information into any request.
- Python for local checks is fine (`python3 -I`), e.g. comparing a lane's values with a gold file.
- Write only your two output files.

## What to decide, per question

1. **What does the question ask?** Read it literally, with the document: grain (one row per what), filters and time
   range, metric definition, ranking and ties, which values must be reported.
2. **Do the accepted gold files answer it?** Do the files agree with each other in substance (not just in column
   names or formats)? The scorer uses the files, not the SQL, so judge the files; stale gold SQL alone is not an error,
   but SQL that contradicts the files can explain how a file came about.
3. **Is each lane group right in substance?** Compare its values with the gold files on shared rows; when they differ,
   find the SQL difference that causes it and decide it against the question.
4. **Does the scoring setup decide correctly?** condition_cols, ignore_order, the 0.01 numeric tolerance, units,
   rounding and formats can reject a lane that is right in substance, or accept one that is wrong. Check the flags.
5. **Verdict** (one):
   - `gold_right`: the accepted files answer the question and every lane's official label is right. The default when
     you find no concrete problem.
   - `gold_wrong`: the accepted files contradict the question or the documentation (quote the words; show the values
     or logic).
   - `two_readings`: the question allows two or more fair readings with different answers; the gold takes one, and
     some lane takes another. Fair means a careful analyst reading the question and document could choose it, not
     merely that it is plausible.
   - `scoring_defect`: the gold is right in substance, but the scoring setup wrongly rejects or accepts a lane.
   - `unclear`: the evidence does not decide it (for example it needs warehouse data nobody saw). No correction.
6. **Corrected labels**, as lists of lanes 0-3:
   - `strict_right_lanes`: the lanes that are right after fixing `gold_wrong` and `scoring_defect` cases only.
   - `lenient_right_lanes`: strict, plus lanes right under another fair reading (`two_readings`).
   - For `gold_right` and `unclear`: both equal the official lanes. For `two_readings`: strict equals official.
   - A lane the scorer counts right that is wrong in substance (it matched a wrong accepted file, or the tolerance let
     it through) leaves both lists. That direction counts as much as the other.
7. **Confidence**: `high` (decisive evidence), `medium`, `low`. `gold_wrong` and `scoring_defect` need at least medium;
   otherwise use `unclear`.

## Evidence standard

- Quote the words of the question or document that decide. Give the values (gold against lane) and the SQL difference
  that causes them.
- Lanes agreeing with each other is weak evidence: the 4 lanes are one agent with shared habits.
- The gold being official is weak evidence too: errors in it are known.
- Stay with what the files, traces and documentation show. If deciding needs data nobody saw, say so and use `unclear`.
- Formatting alone (column names, column order, extra columns) never makes a lane wrong; the scorer ignores names and
  tolerates extra columns.

## Output (write both; overwrite if they exist)

1. `results/bq17/audit/verdicts/<batch>.json`: a JSON list, one object per question in your batch:
   ```json
   {"iid": "bq060", "official_right_lanes": [0, 1, 2, 3], "verdict": "gold_right", "confidence": "high",
    "strict_right_lanes": [0, 1, 2, 3], "lenient_right_lanes": [0, 1, 2, 3],
    "issue": "one sentence: what is wrong, or none",
    "evidence": "2-5 sentences with quotes and values",
    "scoring_note": "optional, e.g. condition_cols never check the fifth file; harmless here"}
   ```
2. `results/bq17/audit/notes/<batch>.md`: one section per question (heading: the iid) with your reasoning in plain
   words (3-8 sentences) and the key evidence.

Then reply with at most 8 lines: counts per verdict, and each question whose labels change (iid, official lanes ->
strict / lenient lanes, one phrase why).

## Light review (batches named light*)

These are questions where all 4 lanes match an accepted gold file. Apply the same protocol, but the main question is
whether that shared answer is wrong in substance: the gold file the lanes match contradicts the question or document
(then the lanes leave the lists), or the scorer accepted a wrong lane through a lax file or condition_cols. Default
`gold_right`. Spend more time only when the question's wording asks for something the shared answer ignores, or the
flags point to a problem.
