#!/usr/bin/env python3
"""Turn a teacher model's run into gold SQL you can trust, and write it as a
linkage file the oracle arm can read.

A teacher query is accepted only if ALL of these hold, checked in this order:
  1. it scores correct under the current scorer
  2. it scores correct on every one of --repeats fresh executions
     (some queries return different rows per run; see local219)
  3. the gold answer is not a single number (a lucky match is too easy)
  4. it parses to real tables in the schema
  5. it touches the table the value sweep found, where the sweep has one
     (an independent check that it read the right data, not just the scorer)

This is stricter than linkage_funnel.py on purpose: that script reports on SQL
we already had, this one promotes new SQL to ground truth.

Writes nl2sql-v2/teacher_context.json in oracle format, readable with
    run_benchmark.py --context-mode oracle --oracle-file teacher_context.json

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/harvest_teacher.py --runs 'teacher_q36_*'
    uv run python scripts/analysis/harvest_teacher.py --runs 'teacher_q36_*,teacher_q36_t07_*'
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from _common import (SQLITE_DIR, Database, buckets, gold_shape, linkage,
                     load_eval_standards, load_traces, local_questions,
                     passes_reliably, rescore, schema_of)

HERE = Path(__file__).resolve()
SWEEP = HERE.parents[2] / "sweep_context.json"
OUT = HERE.parents[2] / "teacher_context.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True,
                    help="teacher run spec(s), comma-separated; globs merge shards. "
                         "Earlier specs win when several solve the same question.")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    qdb = {k: v["db"] for k, v in local_questions().items()}
    std = load_eval_standards()
    specs = args.runs.split(",")
    traces = load_traces(specs)
    ok = rescore(traces, qdb)
    b = buckets(qdb)
    swept = ({i: {t.lower() for t in v["tables"]}
              for i, v in json.loads(SWEEP.read_text()).items()} if SWEEP.exists() else {})

    attempted = sorted({i for by in traces.values() for i in by})
    accepted, why = {}, {}
    schemas = {}
    for iid in attempted:
        db_path = SQLITE_DIR / f"{qdb[iid]}.sqlite"
        if qdb[iid] not in schemas:
            db = Database(db_path)
            schemas[qdb[iid]] = schema_of(db)
            db.close()
        reason = "not solved by any teacher run"
        for spec in specs:
            t = traces[spec].get(iid)
            if not t or not ok[(spec, iid)]:
                continue
            if not passes_reliably(db_path, t["sql"], iid, std, args.repeats):
                reason = "scores correct only sometimes"
                continue
            if gold_shape(iid) == (1, 1):
                reason = "single-number answer"
                continue
            link = linkage(t["sql"], schemas[qdb[iid]])
            if not link:
                reason = "touches no real table"
                continue
            if iid in swept and not swept[iid] & set(link[0]):
                reason = "misses the table the answer's values live in"
                continue
            accepted[iid] = {"tables": sorted(link[0]), "columns": sorted(link[1]),
                             "source": spec, "sql": t["sql"]}
            break
        if iid not in accepted:
            why[iid] = reason

    Path(args.out).write_text(json.dumps(accepted, indent=2))
    n = len(attempted)
    print(f"questions the teacher attempted : {n}")
    print(f"accepted as gold SQL            : {len(accepted)}  ({100 * len(accepted) / max(n, 1):.0f}%)")
    for reason, k in Counter(why.values()).most_common():
        print(f"   rejected, {reason:44s} {k}")
    print(f"\nby bucket: " + ", ".join(
        f"{k} {len(set(accepted) & b[k])}" for k in "ABC"))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
