#!/usr/bin/env python3
"""Split a source's instances into shards, and take stratified slices.

Two rules, both about not wasting warehouse money or drawing biased conclusions:

* Shard BY DATABASE, not round-robin. The describe_table cache is keyed by table and
  Snowflake's result cache by query text, so keeping a database inside one shard turns
  repeated catalog work into cache hits. Round-robin would have every shard pay to
  describe GA4.
* Slice by sampling every database, never by truncating the jsonl. A prefix is biased
  toward whichever databases happen to sort first, which would make a calibration
  slice unrepresentative of the spend it is meant to predict.

    uv run python scripts/shard_plan.py --source spider2_snow_new --shards 8
    uv run python scripts/shard_plan.py --source spider2_snow_new --limit 40
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql.config import DATA_SOURCES          # noqa: E402
from run_benchmark import load_questions        # noqa: E402


def group_by_db(questions):
    by_db = {}
    for q in questions:
        by_db.setdefault(q["db"], []).append(q["instance_id"])
    return {k: sorted(v) for k, v in sorted(by_db.items())}


def stratified_slice(by_db: dict, limit: int) -> dict:
    """Take about `limit` instances spread across every database.

    Round-robin over databases so each contributes before any contributes twice:
    that keeps both the big-schema and small-schema cost regimes in the sample.
    """
    if not limit or sum(len(v) for v in by_db.values()) <= limit:
        return by_db
    out = {db: [] for db in by_db}
    taken, depth = 0, 0
    while taken < limit:
        progressed = False
        for db, ids in by_db.items():
            if depth < len(ids):
                out[db].append(ids[depth])
                taken += 1
                progressed = True
                if taken >= limit:
                    break
        if not progressed:
            break
        depth += 1
    return {db: ids for db, ids in out.items() if ids}


def pack_shards(by_db: dict, shards: int) -> list[list[str]]:
    """Largest database first into the currently emptiest shard: keeps instance
    counts close without ever splitting a database across shards."""
    buckets: list[list[str]] = [[] for _ in range(max(shards, 1))]
    for db, ids in sorted(by_db.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        min(buckets, key=len).extend(ids)
    return [b for b in buckets if b]


def plan(source: str, shards: int = 1, limit: int = 0) -> list[list[str]]:
    questions = load_questions([DATA_SOURCES[source]])
    if not questions:
        raise SystemExit(f"source {source!r} produced no instances "
                         f"(is the Spider2 submodule present?)")
    by_db = stratified_slice(group_by_db(questions), limit)
    return pack_shards(by_db, shards)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="spider2_snow_new")
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0,
                    help="stratified slice size (0 = everything)")
    ap.add_argument("--json", action="store_true", help="emit the shards as JSON")
    args = ap.parse_args()

    buckets = plan(args.source, args.shards, args.limit)
    if args.json:
        print(json.dumps(buckets))
        return 0
    total = sum(len(b) for b in buckets)
    print(f"{total} instances in {len(buckets)} shard(s)")
    for i, b in enumerate(buckets):
        print(f"  shard {i:02d}: {len(b):4d} instances  "
              f"({', '.join(b[:4])}{' ...' if len(b) > 4 else ''})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
