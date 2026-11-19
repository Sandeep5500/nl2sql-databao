# Verification of strict label changes (Nov 19 2026)

A first auditor, following `results/bq17/audit/PROTOCOL.md`, changed the **strict** labels of the questions in your
batch (which lanes count as right after fixing clear gold errors and scoring defects). Strict changes alter the corrected
scores we report, so each gets a second, independent check. **The burden of proof is on the change**: confirm it only
when you reproduce the decisive evidence yourself from local files and the reasoning holds.

Read `PROTOCOL.md` first (hard rules, inputs, the meaning of strict and lenient). The same hard rules apply: never run
anything against BigQuery or any cloud service, do not open credential or key files, use only local files plus
WebSearch/WebFetch for official dataset documentation, no curl or wget, no personal information in any request. Keep any
helper files in `scratchpad/<your batch>/` (the scratchpad is shared with other agents) and write only your outputs.

## Per question

1. Read the packet `results/bq17/audit/packets/<iid>.md`, the first auditor's entry in
   `results/bq17/audit/verdicts/<their batch>.json` (fields `issue`, `evidence`, `strict_right_lanes`) and their section
   in `results/bq17/audit/notes/<their batch>.md`. Your batch list says which file holds each question.
2. Reproduce the decisive facts yourself: the values in the gold files and in the lanes' results, what condition_cols
   and ignore_order make the scorer require, and what the lane traces show
   (`results/bq17/bigquery_passk_nov2026_17/lane_k{1..4}/traces/<iid>.json`, lane 0 = k1). Use `python3 -I`.
3. Decide:
   - `confirm`: the strict change is right as given.
   - `adjust`: partly right; give the strict lanes the evidence supports.
   - `refute`: the official labels should stand under the strict standard.
   The strict standard: only clear gold errors (the accepted files contradict the question or the documentation) and
   scoring defects (the setup rejects a lane that is right in substance, or accepts one that is wrong). A defensible
   other reading is not strict; it belongs to lenient. Two special classes, accepted only when the evidence is specific:
   live-table drift (the public table changed after the gold was made; the lane's logic must match the gold's, and the
   difference must be explained by the data change) and our harness's 5,000-row result cap (bq067).
4. Say also whether the first auditor's lanes would be right under a fair other reading (`lenient_ok`), so a refuted
   strict change can still count in the lenient view.

## Output (write both; overwrite if they exist)

1. `results/bq17/audit/verify/<your batch>.json`: a JSON list, one object per question:
   ```json
   {"iid": "bq290", "decision": "confirm", "strict_right_lanes": [0, 1, 2, 3], "lenient_ok": true,
    "reason": "2-4 sentences with the evidence you reproduced"}
   ```
   For `refute`, `strict_right_lanes` is the official lanes.
2. `results/bq17/audit/verify/<your batch>.md`: one short section per question with what you checked.

Then reply with at most 6 lines: counts per decision, and each question you adjusted or refuted with one phrase why.
