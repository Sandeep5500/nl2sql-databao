#!/usr/bin/env python3
"""Can a solver recover the gold answer from a synthesized question alone?

The ambiguity gate in synth_questions.py checks that an independent *reading* of
the question matches the gold's shape. It deliberately does not check whether the
question is SOLVABLE -- a weak validator would reject hard-but-well-posed items,
which are the valuable ones. That leaves the solvability of our items unmeasured.

This closes that gap cheaply: give a solver the question and schema only, execute
whatever SQL it returns, and score against the gold result using OUR scorer's
semantics (each gold column must match some predicted column; extra predicted
columns are tolerated; absolute 0.01 numeric tolerance).

The resulting solve rate is a local proxy for the plan's "mixed rate": an item no
solver can get is an item that will produce no usable training pair, and an item
every solver gets is too easy to be informative.

Usage (from nl2sql-v2/):
    OPENAI_API_KEY=... uv run python scripts/synth_solvecheck.py \\
        --items ../data/synth/batch30_v3.jsonl \\
        --db /tmp/bikeshare.sqlite \\
        --base-url https://ai-gateway.andrew.cmu.edu/v1 --model gpt-5.4-mini
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parent))
from synth_questions import fence, key_spend, schema_text  # noqa: E402

SOLVE_PROMPT = """Answer this question with one SQLite SELECT query.

Schema:
{schema}

Question:
{question}

Return ONLY the SQL in a ```sql fenced block. No commentary.
"""


def norm(v):
    """Compare the way nl2sql/eval.py does: numbers within 0.01, else strings."""
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return str(v).strip()


def columns_of(rows, ncols):
    return [tuple(norm(r[i]) for r in rows) for i in range(ncols)]


def scores(gold_rows, gold_ncols, pred_rows, pred_ncols) -> bool:
    """Every gold column must appear among the predicted columns; extras are fine.

    Row order is ignored by sorting each column, which matches how our scorer
    treats results without an explicit ordering requirement.
    """
    if len(gold_rows) != len(pred_rows):
        return False
    gcols = [sorted(c, key=lambda x: (x is None, str(x))) for c in columns_of(gold_rows, gold_ncols)]
    pcols = [sorted(c, key=lambda x: (x is None, str(x))) for c in columns_of(pred_rows, pred_ncols)]
    used = set()
    for g in gcols:
        for j, p in enumerate(pcols):
            if j not in used and g == p:
                used.add(j)
                break
        else:
            return False
    return True


CAP = 5000


def run(db, sql, cap=CAP):
    """Returns (rows, ncols, truncated). A truncated comparison is worthless:
    two different results both cut at the cap look identical, which once scored a
    2.3M-row gold as SOLVED against a 5,000-row prediction."""
    cur = db.execute(sql)
    rows = cur.fetchmany(cap + 1)
    return rows[:cap], len(cur.description), len(rows) > cap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--only-passing", action="store_true", default=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    key = os.environ.get("OPENAI_API_KEY", "EMPTY")
    client = OpenAI(base_url=args.base_url, api_key=key)
    db = sqlite3.connect(args.db)
    schema = schema_text(db)
    spend0 = key_spend(args.base_url, key)

    items = [json.loads(l) for l in open(args.items)]
    if args.only_passing:
        items = [r for r in items if r.get("status") == "pass"]
    print(f"{len(items)} items, solver = {args.model}\n")

    out, solved, errored = [], 0, 0
    for r in items:
        try:
            g_rows, g_ncols, g_trunc = run(db, r["gold_sql"])
        except Exception as e:
            print(f"  {r['id']} GOLD FAILED TO RE-EXECUTE: {e}")
            continue
        if g_trunc:
            print(f"  {r['id']} SKIPPED: gold exceeds {CAP} rows, comparison would "
                  f"be truncated on both sides")
            continue
        resp = client.chat.completions.create(
            model=args.model, temperature=args.temperature, max_tokens=1600,
            messages=[{"role": "user", "content": SOLVE_PROMPT.format(
                schema=schema, question=r["question"])}])
        sql = fence(resp.choices[0].message.content or "")
        ok, note = False, ""
        try:
            p_rows, p_ncols, p_trunc = run(db, sql)
            if p_trunc:
                ok, note = False, f"pred exceeds {CAP} rows vs gold {len(g_rows)}"
            else:
                ok = scores(g_rows, g_ncols, p_rows, p_ncols)
                note = f"pred {len(p_rows)}x{p_ncols} vs gold {len(g_rows)}x{g_ncols}"
        except Exception as e:
            errored += 1
            note = f"{type(e).__name__}: {str(e)[:70]}"
        solved += ok
        out.append({"id": r["id"], "bucket": r["bucket"], "solved": ok,
                    "note": note, "solver_sql": sql})
        print(f"  {r['id']} [{r['bucket']:19s}] {'SOLVED' if ok else 'missed':6s}  {note}")

    n = len(out)
    print(f"\nsolve rate: {solved}/{n} = {solved/max(n,1):.0%}   "
          f"({errored} solver queries failed to execute)")
    from collections import Counter
    per = Counter(x["bucket"] for x in out)
    hit = Counter(x["bucket"] for x in out if x["solved"])
    print("per bucket:")
    for b in sorted(per):
        print(f"  {b:20s} {hit[b]}/{per[b]}")
    spend1 = key_spend(args.base_url, key)
    if spend0 is not None and spend1 is not None:
        print(f"\nspend: ${spend1-spend0:.4f} this check (${spend1:.4f} cumulative)")
    if args.out:
        Path(args.out).write_text("".join(json.dumps(x) + "\n" for x in out))
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
