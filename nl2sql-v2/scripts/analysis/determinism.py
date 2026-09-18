#!/usr/bin/env python3
"""How many stored queries return different results on repeated execution,
and how many of those flip between scoring correct and incorrect?

Some SQL is nondeterministic -- LIMIT over tied rows, window functions with no
ORDER BY, GROUP BY picking an arbitrary row -- so one execution is not a
verdict. local003's greedy query returns 9, 10 or 11 rows run to run; only the
9-row result matches gold. This counts the problem across whole runs.

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/determinism.py                    # the five Phase-0 runs
    uv run python scripts/analysis/determinism.py --runs 'teacher_p1_*' --repeats 8
"""

import argparse
from collections import defaultdict

from _common import (PHASE0_RUNS, SQLITE_DIR, Database, buckets,
                     load_eval_standards, load_traces, local_questions,
                     score_against_gold)
from vote import canon


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=",".join(PHASE0_RUNS))
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args()

    std = load_eval_standards()
    qdb = {k: v["db"] for k, v in local_questions().items()}
    traces = load_traces(args.runs.split(","))
    by_db = defaultdict(list)
    for spec, by_iid in traces.items():
        for iid, t in by_iid.items():
            by_db[qdb[iid]].append((spec, iid, t["sql"]))

    varies, flips = [], []
    total = 0
    for db_name, items in sorted(by_db.items()):
        path = SQLITE_DIR / f"{db_name}.sqlite"
        if not path.exists():
            continue
        for spec, iid, sql in items:
            total += 1
            results, scores = set(), set()
            for _ in range(args.repeats):
                try:
                    db = Database(path)          # fresh connection each time
                    df, _ = db.query_preview(sql, preview_rows=1, max_rows=5000)
                    db.close()
                    results.add(canon(df))
                    scores.add(score_against_gold(df, iid, std)[0])
                except Exception:
                    results.add("error"); scores.add(0)
            if len(results) > 1:
                varies.append((spec, iid))
            if len(scores) > 1:
                flips.append((spec, iid))

    print(f"stored queries checked            : {total}  ({args.repeats} executions each)")
    print(f"return different results run to run: {len(varies)}")
    print(f"flip between correct and incorrect : {len(flips)}")
    for spec, iid in sorted(flips, key=lambda x: x[1]):
        print(f"   {iid}  ({spec})")
    b = buckets(qdb)
    moved = {iid for spec, iid in flips}
    at_risk = {k: sorted(moved & b[k]) for k in "ABC"}
    print("\nquestions whose bucket could change on another machine:")
    for k in "ABC":
        print(f"   bucket {k}: {at_risk[k] or 'none'}")


if __name__ == "__main__":
    main()
