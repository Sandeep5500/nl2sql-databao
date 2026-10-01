# Correcting benchmark questions

Some Spider2 questions are ambiguous, and a few state something their own gold answer
does not do. This is how we record that without corrupting the benchmark.

## Why not just edit the questions

`Spider2/` is a **git submodule** pointing at `xlang-ai/Spider2`. Editing
`spider2-lite/spider2-lite.jsonl` in place fails three ways: this repo tracks only the
submodule's commit SHA so the edit is never captured, the next submodule update discards
it, and — worst — our numbers silently stop being comparable with the leaderboard and
with our own earlier runs.

So corrections live in **`nl2sql-v2/question_overrides.json`** in this repo and are
applied at load time, **off by default**.

## The two kinds, which must not be conflated

| kind | meaning | default action |
|---|---|---|
| `clarify` | The question is ambiguous or underspecified, and the gold answer is consistent with one reading. | `replace` |
| `contradicts-gold` | The question states something the gold answer does not do. | `exclude` |

The distinction is the whole point. A `clarify` fix is a fair test: the model gains
because the task got clearer, and it would gain the same way on a real user's better
question. Rewriting a `contradicts-gold` question to match its gold is **teaching to the
test** — the score rises and the model is no better — so the default is to drop the
question and report the smaller denominator instead.

## Worked example: `local272` (oracle_sql)

The question asks to pick stock "without exceeding the available inventory in
**warehouse 1**". Joining the gold answer's four rows back through
`inventory` → `locations`:

| product | aisle | position | warehouse |
|---|---|---|---|
| 4280 | B | 3 | **2** |
| 4280 | C | 20 | **2** |
| 6520 | D | 9 | **2** |
| 6520 | A | 16 | 1 |

Three of four rows are warehouse 2. And warehouse 1 holds 112 units of 4280 and 243 of
6520 on its own, so the stated constraint is satisfiable — the gold simply ignores it.
No model that reads the question correctly can produce this answer. Tagged
`contradicts-gold`, action `exclude`.

## Using it

```
# default: untouched upstream questions
uv run python scripts/run_benchmark.py ...

# only disambiguation
uv run python scripts/run_benchmark.py --question-overrides clarify ...

# also act on questions that contradict their gold
uv run python scripts/run_benchmark.py --question-overrides all ...
```

An overlay run announces itself at startup and lists every change, and each affected
trace carries a `question_override` block, so an analysis can never mistake one for a
plain benchmark result. **Always report overlay numbers separately, with the
denominator.**

## Adding an entry

```json
"localNNN": {
  "kind": "clarify" | "contradicts-gold",
  "action": "replace" | "exclude",
  "question": "the reworded question (only for action=replace)",
  "reason": "one line",
  "evidence": "what you ran that proves it, and when",
  "upstream_question": "the exact current upstream text",
  "added": "YYYY-MM-DD"
}
```

`upstream_question` is a drift guard: if Spider2 changes that question, the loader
**refuses to run** rather than applying a correction written against different text.
Re-verify against the gold and update the entry.

Two rules for entries. Evidence must be something you actually executed, not a reading
of the question — the gold CSV is the graded artifact, so a correction is only justified
when it is checked against the gold. And a `clarify` entry must not narrow the question
until only the gold's reading survives; if that is the only way to make it match, the
entry is really `contradicts-gold`.

## Known candidates, not yet entered

From `trace_analysis_p1_first27.md` and the findings doc — each still needs the
gold-level check above before it becomes an entry:

- `local273` (oracle_sql) — gold reported as degenerate (ids under `PRODUCT_NAME`, 0.0 averages).
- `local299`, `local002` — correct float pipelines rejected by the scorer's absolute
  0.01 tolerance. These are **scorer** problems, not question problems; an override is
  the wrong tool.
- The 8 of 24 questions whose shipped gold SQL answers a different question than the
  graded CSV (findings §2). The CSV is what is graded, so these only matter if someone
  uses the gold SQL as an oracle.
