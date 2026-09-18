#!/usr/bin/env python3
"""Why did the 9B still fail when handed the correct tables and columns?

For every failed oracle-arm run, diff the 9B's final query against the
teacher's verified query for the same question, and assign the FIRST cause
that applies, in this order:

  step cap        ran out of its 30 steps; the "answer" is its last exploratory query
  unused table    left out a table the prompt said the answer uses
                  (tables beyond the list are only recorded: the list is what the
                  teacher needed to pass the scorer, not always all the question asks)
  join            used the tables but misses a join key the correct query uses
  unused column   left out a column the prompt listed (not a join key)
  output shape    returns fewer columns than the answer needs
  row count       right columns, wrong number of rows (grouping or filtering)
  values          right shape, wrong values (aggregation or calculation logic)

Structural and automatic, so spot-check the examples it prints.

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/oracle_failures.py --examples 2
"""

import argparse
import json
import textwrap
from collections import Counter, defaultdict
from pathlib import Path

import sqlglot
from sqlglot import exp

from _common import (SQLITE_DIR, Database, gold_files, linkage, load_traces,
                     local_questions, rescore, schema_of)
from ablation_arms import discover

import pandas as pd

HERE = Path(__file__).resolve()
ORDER = ["step cap", "unused table", "join", "unused column",
         "output shape", "row count", "values"]


def join_keys(sql: str, schema_cols: set) -> set:
    """Column-name pairs equated anywhere (ON, WHERE, USING), keeping only pairs
    where both names are real schema columns. Without that filter, a comparison
    between two computed values (pre_count = min_pre_count) counts as a join."""
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return set()
    keys = set()
    for eq in tree.find_all(exp.EQ):
        l, r = eq.left, eq.right
        if isinstance(l, exp.Column) and isinstance(r, exp.Column):
            pair = frozenset({l.name.lower(), r.name.lower()})
            if pair <= schema_cols:
                keys.add(pair)
    for j in tree.find_all(exp.Join):
        for u in j.args.get("using") or []:
            if u.name.lower() in schema_cols:
                keys.add(frozenset({u.name.lower()}))
    return keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="ablation_oracle")
    ap.add_argument("--examples", type=int, default=0)
    args = ap.parse_args()

    Q = local_questions()
    qdb = {k: v["db"] for k, v in Q.items()}
    teacher = json.loads((HERE.parents[2] / "teacher_context.json").read_text())
    specs = discover(args.prefix)
    traces = load_traces(specs)
    ok = rescore(traces, qdb)

    rows, schemas = [], {}
    for spec in specs:
        for iid, t in traces[spec].items():
            if iid not in teacher or ok[(spec, iid)]:
                continue
            db_name = qdb[iid]
            if db_name not in schemas:
                d = Database(SQLITE_DIR / f"{db_name}.sqlite"); schemas[db_name] = schema_of(d); d.close()
            real = schemas[db_name]
            given_t = {x.lower() for x in teacher[iid]["tables"]}
            given_c = {x.lower() for x in teacher[iid]["columns"]}
            gold_sql = teacher[iid]["sql"]
            schema_cols = set().union(*real.values())
            gold_keys = join_keys(gold_sql, schema_cols)
            key_cols = set().union(*gold_keys) if gold_keys else set()
            sql = t.get("sql") or ""
            link = linkage(sql, real) if sql else None
            used_t = set(link[0]) if link else set()
            used_c = set(link[1]) if link else set()
            detail = ""
            if t.get("status") == "fallback":
                cause = "step cap"
            elif given_t - used_t:
                cause, detail = "unused table", ", ".join(sorted(given_t - used_t))
            elif gold_keys - join_keys(sql, schema_cols):
                miss = gold_keys - join_keys(sql, schema_cols)
                cause, detail = "join", "; ".join("=".join(sorted(k)) for k in miss)
            elif (given_c - key_cols) - used_c:
                cause, detail = "unused column", ", ".join(sorted((given_c - key_cols) - used_c))
            else:
                try:
                    d = Database(SQLITE_DIR / f"{db_name}.sqlite")
                    df, _ = d.query_preview(sql, preview_rows=1, max_rows=5000); d.close()
                    golds = [pd.read_csv(f) for f in gold_files(iid)]
                    need_cols = min(g.shape[1] for g in golds)
                    gold_rows = {g.shape[0] for g in golds}
                    if df.shape[1] < need_cols:
                        cause, detail = "output shape", f"{df.shape[1]} cols, needs {need_cols}"
                    elif len(df) not in gold_rows:
                        cause, detail = "row count", f"{len(df)} rows, gold {sorted(gold_rows)}"
                    else:
                        cause, detail = "values", f"{df.shape[0]}x{df.shape[1]}, same shape as gold"
                except Exception as e:
                    cause, detail = "values", f"did not re-execute ({type(e).__name__})"
            extra = sorted(used_t - given_t) if link else []
            rows.append({"iid": iid, "run": spec, "cause": cause, "detail": detail, "extra": extra,
                         "sql": sql, "gold": gold_sql})

    n = len(rows)
    c = Counter(r["cause"] for r in rows)
    print(f"failed oracle-arm runs: {n}  (of {len(specs) * len(teacher)})\n")
    groups = {"1) ignored what it was given": ["unused table", "unused column"],
              "2) joins": ["join"],
              "3) anything else": ["step cap", "output shape", "row count", "values"]}
    for g, causes in groups.items():
        k = sum(c[x] for x in causes)
        print(f"{g:32s} {k:3d}  ({100 * k / n:4.0f}%)")
        for x in causes:
            if c[x]:
                print(f"     {x:16s} {c[x]:3d}")

    xr = [r for r in rows if r["extra"]]
    print(f"\n(also used tables beyond the given list: {len(xr)} runs -- not counted as a cause,")
    print(f" since the given list is what the teacher needed to pass the scorer, which can be")
    print(f" less than the question asks for; e.g. local286's review and packing columns are ungraded)")
    print("\nper question (failed runs by cause):")
    per = defaultdict(Counter)
    for r in rows:
        per[r["iid"]][r["cause"]] += 1
    for iid in sorted(per):
        print(f"   {iid}: " + ", ".join(f"{k} {per[iid][k]}" for k in ORDER if per[iid][k]))

    for cause in ORDER:
        ex = sorted((r for r in rows if r["cause"] == cause and r["sql"]),
                    key=lambda r: len(r["sql"]) + len(r["gold"]))[: args.examples]
        for r in ex:
            print(f"\n{'=' * 78}\n{cause.upper()} — {r['iid']} ({r['run']})  {r['detail']}\n{'=' * 78}")
            print("Q: " + textwrap.fill(Q[r["iid"]]["question"][:300], 88, subsequent_indent="   "))
            print("\n   CORRECT (27B):\n" + textwrap.indent(r["gold"].strip()[:650], "     "))
            print("\n   9B FAILED:\n" + textwrap.indent(r["sql"].strip()[:650], "     "))


if __name__ == "__main__":
    main()
