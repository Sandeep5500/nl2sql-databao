#!/usr/bin/env python3
"""Pick the never-solved questions worth sending to a teacher model, and print
them as a comma-separated list for run_benchmark.py --instances.

Starts from bucket C (no Phase-0 run ever solved it), then:
  --drop-scalars    skip 1x1 answers: the linkage filter discards them anyway
  --require-sweep   keep only questions with value-sweep coverage, so the
                    swept table can verify the teacher's SQL, and so
                    --context-mode sweep_contract runs without Ollama
  --limit N         take N, round-robin across databases so no schema dominates

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/teacher_targets.py --drop-scalars --require-sweep
    uv run python scripts/run_benchmark.py --instances "$(uv run python \\
        scripts/analysis/teacher_targets.py --drop-scalars --require-sweep --quiet)"
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from _common import buckets, gold_shape, local_questions

SWEEP = Path(__file__).resolve().parents[2] / "sweep_context.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop-scalars", action="store_true")
    ap.add_argument("--require-sweep", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--quiet", action="store_true", help="print only the id list")
    args = ap.parse_args()

    qdb = {k: v["db"] for k, v in local_questions().items()}
    ids = set(buckets(qdb)["C"])
    log = [f"bucket C (never solved)        : {len(ids)}"]
    if args.drop_scalars:
        ids = {i for i in ids if gold_shape(i) != (1, 1)}
        log.append(f"after dropping 1x1 scalars     : {len(ids)}")
    if args.require_sweep:
        swept = set(json.loads(SWEEP.read_text())) if SWEEP.exists() else set()
        ids &= swept
        log.append(f"after requiring sweep coverage : {len(ids)}")

    by_db = defaultdict(list)
    for i in sorted(ids):
        by_db[qdb[i]].append(i)
    picked, dbs = [], sorted(by_db, key=lambda d: -len(by_db[d]))
    while any(by_db.values()) and (args.limit is None or len(picked) < args.limit):
        for d in dbs:
            if by_db[d] and (args.limit is None or len(picked) < args.limit):
                picked.append(by_db[d].pop(0))

    if not args.quiet:
        print("\n".join(log), file=sys.stderr)
        spread = defaultdict(int)
        for i in picked:
            spread[qdb[i]] += 1
        print(f"picked                         : {len(picked)} across {len(spread)} databases",
              file=sys.stderr)
    print(",".join(sorted(picked)))


if __name__ == "__main__":
    main()
