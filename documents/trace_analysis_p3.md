# Per-trace analysis — Person 3, all 45 (q36s_pass4_k1..k4)

Counted across all four search-fixed lanes, not one. 32 of the 45 failed at least once;
13 passed on every lane. Two extra runs are used as evidence of winnability: `shape_gate`
and `shape_ctrl`, the A/B of the submit-time shape gate (both greedy, 2026-10-01).

## Error classes by bucket

The top two buckets are counted **by question** (the lanes fail the same way). The bottom
two are counted **by failing run** (the lanes fail differently).

| Bucket | Error class | Count | Where |
|---|---|---|---|
| **4 of 4 failed** (11 questions) | Expensive lap-level computation, never finished | 3 | local336, local344, local356 — all 4 lanes hit the step cap |
| | Wrong grain: extra rows the question does not ask for | 3 | local003 (11 vs 9), local286 (236 vs 233), local194 (600 vs 411) |
| | Dropped the identifying column | 2 | local004 (`customer_unique_id`), local194 (`actor_id`) — local194 is both |
| | Right shape, wrong values | 2 | local335, local355 |
| | Returned the ranked table, not the top row | 1 | local264 — **fixed** by the shape gate |
| | Lost rows / wrong cohort | 1 | local354 (11 vs 104) — **fixed** in the new run |
| **3 of 4 failed** (7 questions) | Dropped a column it had already computed | 1 | local130 — correct result in the trace in **all three** failing lanes; **fixed** |
| | Right shape, wrong values | 3 | local098, local263, local097 (2 of its 3 lanes) |
| | Wrong grain: extra rows | 1 | local070 (36 vs 15) — **fixed** |
| | Ranking definition wrong | 1 | local056 |
| | Lost rows across a join | 1 | local309 (66–75 vs 74) |
| **2 of 4 failed** (10 failing runs) | Right shape, wrong values | 5 | local096 (2 rows of 78 off by one), local099 ×2, local171, local097 |
| | Returned the ranked table, not the top row | 2 | local167 — **fixed** by the shape gate |
| | Off-by-one on a range boundary | 1 | local171 (every bucket one legislator short) |
| | Never committed | 1 | local311 — correct result in the trace, capped; **fixed** |
| | Other | 1 | local311 (other lane: 6 columns, wrong values) |
| **1 of 4 failed** (9 failing runs) | Returned the ranked table, not the top row | 4 | local019, local039, local071, local202 — **all fixed** |
| | Right computation, wrong thing submitted | 2 | local039, local100 — correct result in the trace; **both fixed** |
| | Underdetermined question | 1 | local168 — 5-way tie at frequency 3; the benchmark accepts 4 of the 10 valid tie-breaks |
| | Dropped a column + 0-based index | 1 | local169 — correct rate column, missing `retained_count`, indexed 0–19 vs 1–20 |
| | Numeric tolerance | 1 | local002 — 0.017% relative error against an absolute 0.01 tolerance; **fixed** in the new run |

Lost answers: in **10 of the 84 failing runs** the correct result was already in the trace and
something else was submitted — local130 (×3), local039, local097, local098, local100,
local169, local311, local354.

## What this says

- **This slice has no unreachable questions.** Unlike Person 1's 45, every question here was
  solved by *some* run. Eight were never solved by any of our ten runs — local003, local004,
  local194, local286, local336, local344, local355, local356 — but that is "not yet", not
  "cannot be". local168 looked unreachable and is not: three lanes landed on an accepted
  tie-break. local002 looked like a scorer artifact and was solved outright in the new run.
- **The bottom two buckets are nearly solved already.** Of the 14 questions failing in 1 or 2
  lanes, 11 now pass. The shape gate accounts for local167 and local264 directly; the rest
  came from the scanner fix, the best-cluster fallback and the prompt contract.
- **f1 is five of the eleven always-fail questions**, and three of those (local336, local344,
  local356) are one shared sub-problem: inferring overtakes from consecutive-lap positions over
  613k rows, then classifying each as retirement / pit / start / track. All twelve lanes hit the
  step cap, and **no query any of them ran would have scored** — they never found the answer, so
  better fallback selection cannot help here.
- **local356 is missing its documentation.** It asks for the same on-track-overtake definition as
  local336 and local344, which both receive `f1_overtake.md`. It does not.
- **Output shape is finished as a theme here.** Every "returned the ranked table" case now passes.
  What is left in the always-fail bucket is wrong grain on large results and wrong values.

## Fixes, by what fails consistently

**Fails in all four runs**

1. **Attach `f1_overtake.md` to local356.** A documentation gap, not score inflation — the two
   sibling questions get the same definitions handed to them. Cheapest item on this list.
2. **Test whether the f1 cluster is budget or capability.** Raise `--max-steps` to 50 on
   local336/344/356 alone. They ran 20–25 queries and never reached the answer, so if more steps
   do not finish them the problem is capability and effort should move elsewhere.
3. **Finish the supporting-column rule.** local004 (`customer_unique_id`) and local194
   (`actor_id`) still drop the identity column the gold requires. The scorer accepts extra
   columns and rejects missing ones, so this is a one-way bet; the prompt line already converted
   local130 and local169 is the same shape of fix.

**Fails in one or two runs (what pass@k needs)**

4. **Keep the row-count half of the shape gate; drop or narrow the proportion half.** In the A/B
   the row-count check produced all 5 of the gate's fixes and broke nothing. The proportion check
   fired 3 times, fixed nothing on its own, and broke local301 — "percentage change" of 0.45% is
   not a proportion-versus-percentage error.
5. **A reviewer or agreement rule for the lost answers.** 10 of 84 failing runs had the correct
   result in the trace. The best-cluster fallback already catches some; the rest submitted a
   different query while holding the right one.

## Caveat on run-to-run comparison

`shape_gate` and `shape_ctrl` are identical code at temperature 0 and still produced **different
final SQL on 120 of the 125 questions the gate never touched**. vLLM's batching makes greedy
decoding non-reproducible, so "failed in all four lanes" is a weaker signal of a systematic blind
spot than it looks, and single-run before/after comparisons are not reliable. Only the paired
comparison restricted to questions where an intervention actually fired is trustworthy.
