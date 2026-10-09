#!/usr/bin/env python3
"""Of the answers the model submitted and got wrong, what KIND of wrong were they?

    uv run python scripts/wrong_answer_shapes.py ../logs/traces/bq_v3r \
        --run ../results/bq_v3r_run.csv

Once the harness defects were fixed, nearly every remaining failure is "submitted an
answer, the answer was wrong" -- which is one bucket holding most of the headroom and
tells you nothing about where to look next. This splits it by comparing the submitted
result against the gold CSV:

    no rows            the query ran and returned nothing
    too few / too many rows   the right idea at the wrong grain, or a missing filter
    wrong column count        shape error: missing or extra output columns
    same shape, different values   the logic is wrong, not the shape

Shape errors are what an output-shape rubric targets, so this is also the measurement
that says whether there is more to get from that direction.

Reads the gold CSVs from the Spider2 checkout and the submitted preview from the
trace, so it runs offline and costs nothing.
"""

import argparse
import csv
import io
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl2sql.config import GOLD_EXEC_DIR


def gold_files(iid):
    pat = re.compile(rf"^{re.escape(iid)}(_[a-z])?\.csv$")
    if not GOLD_EXEC_DIR.is_dir():
        return []
    return sorted(GOLD_EXEC_DIR / f for f in os.listdir(GOLD_EXEC_DIR)
                  if pat.match(f))


def shape(text):
    """(rows, cols) of a CSV blob, tolerating ragged output."""
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        return None
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return (0, 0)
    return (len(rows) - 1, max(len(r) for r in rows))


def submitted_csv(trace):
    """The preview the graded query printed, recovered from the trace."""
    sql = (trace.get("sql") or "").strip()
    if not sql:
        return None
    for e in trace.get("trace", []):
        if e.get("tool") != "run_sql_query":
            continue
        if str((e.get("args") or {}).get("sql", "")).strip() != sql:
            continue
        body = str(e.get("result") or "")
        return body.split("\n", 1)[1] if body.startswith("query_id=") else body
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace_dir", type=Path)
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--show", type=int, default=6)
    args = ap.parse_args()

    with open(args.run, newline="", encoding="utf-8") as f:
        run = {r["instance_id"]: r for r in csv.DictReader(f)}

    kinds = Counter()
    examples = {}
    n_wrong = n_classified = 0
    for iid, r in run.items():
        if r.get("score") == "1" or (r.get("status") or "") != "submitted":
            continue
        n_wrong += 1
        p = args.trace_dir / f"{iid}.json"
        if not p.exists():
            kinds["(no trace)"] += 1
            continue
        t = json.loads(p.read_text(encoding="utf-8"))
        pred = submitted_csv(t)
        golds = gold_files(iid)
        if pred is None or not golds:
            kinds["(no gold or no stored result)"] += 1
            continue
        ps = shape(pred)
        gss = [shape(g.read_text(encoding="utf-8", errors="replace"))
               for g in golds]
        gss = [g for g in gss if g]
        if ps is None or not gss:
            kinds["(unparseable)"] += 1
            continue
        n_classified += 1
        # compare against the gold variant closest in shape: several are accepted
        gs = min(gss, key=lambda g: (abs(g[1] - ps[1]), abs(g[0] - ps[0])))
        if ps[0] == 0:
            k = "returned no rows"
        elif ps[1] != gs[1]:
            k = f"wrong column count (got {ps[1]}, gold {gs[1]})" \
                if abs(ps[1] - gs[1]) <= 2 else "wrong column count (far off)"
        elif ps[0] < gs[0]:
            k = "too few rows"
        elif ps[0] > gs[0]:
            k = "too many rows"
        else:
            k = "same shape, different values"
        kinds[k] += 1
        examples.setdefault(k, []).append(f"{iid} ({r['db'][:18]})")

    print(f"\nwrong submitted answers: {n_wrong}  "
          f"(shape-comparable: {n_classified})")
    print("-" * 64)
    for k, v in kinds.most_common():
        pct = f"{100.0 * v / max(n_classified, 1):5.1f}%" \
            if not k.startswith("(") else "      "
        print(f"  {v:4d} {pct}  {k}")
        for e in examples.get(k, [])[: args.show]:
            print(f"            {e}")

    shapey = sum(v for k, v in kinds.items()
                 if k.startswith("wrong column count") or k == "returned no rows")
    rowy = sum(v for k, v in kinds.items()
               if k in ("too few rows", "too many rows"))
    logic = kinds.get("same shape, different values", 0)
    if n_classified:
        print(f"\n  shape/empty : {shapey:4d} = {100 * shapey / n_classified:.0f}%"
              f"   <- what an output-shape rubric targets")
        print(f"  wrong grain : {rowy:4d} = {100 * rowy / n_classified:.0f}%"
              f"   <- right columns, wrong row set")
        print(f"  wrong values: {logic:4d} = {100 * logic / n_classified:.0f}%"
              f"   <- right shape, wrong logic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
