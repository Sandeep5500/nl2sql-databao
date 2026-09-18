#!/usr/bin/env python3
"""Does sampling convert into score? Compares greedy, an execution-consistency
vote across the runs, and the perfect-selection ceiling. Backs Section 5 of
documents/retrieval_vs_generation_findings.md.

The vote groups runs by identical result set (not identical SQL) and submits
the largest group. It re-executes every query to compare results, so it does
not use the boolean score cache and takes a few minutes.

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/vote.py
"""

import argparse
from collections import Counter, defaultdict

from _common import (GREEDY, PHASE0_RUNS, SQLITE_DIR, Database,
                     load_eval_standards, load_traces, local_questions,
                     score_against_gold)


def canon(df) -> str:
    """Order-insensitive fingerprint of a result, matching how the scorer sees it."""
    return "||".join(sorted("|".join(sorted(str(x) for x in df[c].tolist()))
                            for c in df.columns))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=",".join(PHASE0_RUNS))
    ap.add_argument("--greedy", default=GREEDY)
    args = ap.parse_args()

    std = load_eval_standards()
    qdb = {k: v["db"] for k, v in local_questions().items()}
    specs = args.runs.split(",")
    traces = load_traces(specs)
    by_db = defaultdict(set)
    for by_iid in traces.values():
        for iid in by_iid:
            by_db[qdb[iid]].add(iid)

    greedy = voted = ceiling = 0
    agree = Counter()
    for db_name, ids in sorted(by_db.items()):
        p = SQLITE_DIR / f"{db_name}.sqlite"
        if not p.exists():
            continue
        db = Database(p)
        for iid in ids:
            res, sc = {}, {}
            for spec in specs:
                t = traces[spec].get(iid)
                if not t:
                    continue
                try:
                    df, _ = db.query_preview(t["sql"], preview_rows=1, max_rows=5000)
                    res[spec], sc[spec] = canon(df), score_against_gold(df, iid, std)[0]
                except Exception:
                    res[spec], sc[spec] = None, 0
            greedy += bool(sc.get(args.greedy))
            ceiling += any(sc.values())
            groups = Counter(v for v in res.values() if v is not None)
            if groups:
                top, cnt = groups.most_common(1)[0]
                agree[cnt] += 1
                pick = next(s for s in specs if res.get(s) == top)
                voted += bool(sc.get(pick))
        db.close()

    n = len(qdb)
    print(f"greedy alone                       : {greedy}/{n}")
    print(f"execution-consistency vote         : {voted}/{n}")
    print(f"perfect selection (union ceiling)  : {ceiling}/{n}")
    print(f"\nvote recovers {voted - greedy:+d} of the {ceiling - greedy} points between "
          f"greedy and the ceiling\n\nhow many runs agreed on the winning result:")
    for k in sorted(agree):
        print(f"   {k} of {len(specs)} agreed : {agree[k]:3d} questions")


if __name__ == "__main__":
    main()
