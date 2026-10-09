#!/usr/bin/env python3
"""Self-contained checks for DataSource loading: id filters, field mapping, and
that a lite-shaped source behaves exactly as it did before the snow/dbt work.

Builds its own fixtures in a temp dir, so it needs no Spider2 checkout and no GPU:

    uv run python scripts/check_sources.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="nl2sql-srccheck-"))

# config reads these at import time, so they must be set first
os.environ["NL2SQL_SPIDER2_SNOW"] = str(_TMP / "snow")
os.environ["NL2SQL_SPIDER2_LITE"] = str(_TMP / "lite")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql.config import DATA_SOURCES          # noqa: E402
from run_benchmark import load_questions        # noqa: E402

SNOW_ROWS = [
    {"instance_id": "sf_local003", "instruction": "twin", "db_id": "OLIST"},
    {"instance_id": "sf_bq011", "instruction": "ga4", "db_id": "GA4",
     "external_knowledge": "ga4.md"},
    {"instance_id": "sf_ga001", "instruction": "ga", "db_id": "GA360"},
    {"instance_id": "sf002", "instruction": "native", "db_id": "TPCH"},
]
# spider2-lite.jsonl mixes prefixes; the "local" filter must still isolate ours
LITE_ROWS = [
    {"instance_id": "local003", "question": "q1", "db": "OLIST"},
    {"instance_id": "bq011", "question": "q2", "db": "GA4"},
    {"instance_id": "sf002", "question": "q3", "db": "TPCH"},
]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def main() -> int:
    _write(_TMP / "snow/spider2-snow.jsonl", SNOW_ROWS)
    _write(_TMP / "lite/spider2-lite.jsonl", LITE_ROWS)

    failures = []

    def check(label, got, want):
        ok = got == want
        print(f"{'ok  ' if ok else 'FAIL'} {label}: {got}")
        if not ok:
            failures.append(f"{label}: got {got}, want {want}")

    def ids(source_name):
        return [q["instance_id"] for q in load_questions([DATA_SOURCES[source_name]])]

    check("spider2_snow_new excludes the twins", ids("spider2_snow_new"),
          ["sf_bq011", "sf_ga001", "sf002"])
    check("spider2_snow_bq is bq-origin only", ids("spider2_snow_bq"), ["sf_bq011"])
    check("spider2_snow_native excludes twins and bq", ids("spider2_snow_native"),
          ["sf_ga001", "sf002"])
    check("spider2_snow_control is the twins", ids("spider2_snow_control"),
          ["sf_local003"])
    check("spider2_snow_all takes everything", ids("spider2_snow_all"),
          [r["instance_id"] for r in SNOW_ROWS])
    # the regression that matters: the lite lane is untouched by the new machinery
    check("spider2 still filters to local###", ids("spider2"), ["local003"])

    q = load_questions([DATA_SOURCES["spider2_snow_new"]])[0]
    check("field_map fills question/db", [q["question"], q["db"]], ["ga4", "GA4"])
    check("source fields are preserved", [q["instruction"], q["db_id"]], ["ga4", "GA4"])
    check("dialect is tagged", q["_dialect"], "snowflake")
    check("snow gold dir is per-source", q["_gold_exec_dir"].name, "exec_result")
    check("snow eval jsonl is per-source", q["_eval_jsonl"].name,
          "spider2snow_eval.jsonl")

    lite = load_questions([DATA_SOURCES["spider2"]])[0]
    check("lite keeps module-default eval paths",
          [lite["_gold_exec_dir"], lite["_eval_jsonl"]], [None, None])

    # 'all' must still mean the local-SQLite sources only
    sqlite_only = sorted(n for n, d in DATA_SOURCES.items()
                         if d.dialect == "duckdb_sqlite")
    check("'all' covers only SQLite sources", sqlite_only,
          ["bird_minidev", "kaggledbqa", "spider2", "spider_syn"])

    # ---- shard planning: getting this wrong costs warehouse money ----
    from shard_plan import group_by_db, pack_shards, stratified_slice
    qs = load_questions([DATA_SOURCES["spider2_snow_all"]])
    by_db = group_by_db(qs)
    buckets = pack_shards(by_db, 3)
    check("every instance lands in exactly one shard",
          sorted(i for b in buckets for i in b),
          sorted(q["instance_id"] for q in qs))
    placed = {}
    for ix, b in enumerate(buckets):
        for iid in b:
            placed[iid] = ix
    split = [db for db, ids in by_db.items()
             if len({placed[i] for i in ids}) > 1]
    check("no database is split across shards", split, [])
    thin = stratified_slice(by_db, 2)
    check("a 2-instance slice spans 2 databases, not one prefix",
          sorted(len(v) for v in thin.values()), [1, 1])

    if failures:
        print("\n" + "\n".join(failures))
        return 1
    print("\nall source checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
