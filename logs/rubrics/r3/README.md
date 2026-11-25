# r3 submit rubrics (q36f, Nov 24 2026)

The 135 output-shape rubrics the **q36f** run consumed, one per local instance.
Generated once by `scripts/run_rubric.py` at 15:10-15:43 on Nov 24 2026 against
`QuantTrio/Qwen3.6-35B-A3B-AWQ` at temp 0.7.

**These files are committed because they cannot be regenerated.** The planner runs
at non-zero temperature, so a fresh `run_rubric.py` pass produces different rubrics
and a combined run would no longer share q36f's inputs. Any run that wants to pool
with q36f lanes must pass `--rubric-dir logs/rubrics/r3` and use these files verbatim.

Integrity (concatenation of all 135 files, names sorted):

    sha256  c0aabd94b424b49b8d6ff487cb9b1eb3a02203eb4d65a0379c4ba16ad5d7f3d0
    verify: cd logs/rubrics/r3 && ls *.json | sort | xargs cat | shasum -a 256

## What is in a file

`{"rubric": {...}, "turns": N, "trace": [...], "system": "...", "instance_id": ...}`.
The harness reads only the `rubric` object; the rest is kept for inspection. Inside
`rubric`, the fields that drive behaviour:

| field | effect |
|---|---|
| `exact_rows` | the row count the submit gate enforces under `--rubric-enforce` |
| `rows_confidence` | gate only fires on `high` (with `--rubric-confident-only`) |
| `answer_is_single_row` | required bool; supplies 1 when `exact_rows` is absent |
| `include_zero_count_entities` | required bool; shown to the agent, not enforced |

r3 is the first generation carrying the two booleans: all 135 have them,
`single_row` true in 46, `include_zero` true in 15. 86 of 135 yield an enforced
row count; the other 49 abstain.

## Two traps if you reuse these

1. **`local356` has `exact_rows: ""`** (an empty string) next to
   `rows_confidence: "high"`. On the code q36f ran, the gate did `int(exact_rows)`
   and the shard died at that question, which is why every q36f lane has 134
   episodes and not 135. Fixed in `f5e308e` — `effective_exact_rows()` now
   normalises the field — so current code handles this file fine. Do not "repair"
   the file; it is kept as the run saw it.
2. **An enforced count can be wrong.** The planner sometimes infers a count from
   its own grain reasoning rather than reading one off the question. `local163`
   asserts `exact_rows: 3` at high confidence ("one row per faculty rank") but gold
   has 4 rows, because one rank ties — and it fails in all four q36f lanes for that
   reason. 86 rubrics enforce; treat the enforcement as a hypothesis, not a fact.

## Companion artifacts

- `results/q36f_pass4_k{1..4}.csv` — per-episode scores, status, `step_extensions`, SQL
- `logs/traces/q36f_pass4_k{1..4}/` — 134 episode traces per lane, for `inspect view`
- `documents/spider2_attack_plan.md` — the run's results and caveats
