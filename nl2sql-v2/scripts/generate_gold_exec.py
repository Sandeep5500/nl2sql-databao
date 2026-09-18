#!/usr/bin/env python3
"""Generate gold execution-result CSVs for the dataset-augmentation sources.

Each source's instances.jsonl already carries gold_sql inline; this just runs
that SQL against the instance's own database and writes the result to
dataset-augmentation/<source>/gold/exec_result/<instance_id>.csv.

Uses Python's native sqlite3, NOT the harness's DuckDB-attach path: this gold
SQL was authored for real SQLite semantics (e.g. "string" as a literal when no
column matches), which DuckDB's stricter identifier quoting rejects. The
*agent* still runs on DuckDB per the harness design and has to handle that
dialect gap itself — gold answers should reflect true SQLite execution.

No LLM/GPU needed. Safe to run locally or on Babel.

Usage (from nl2sql-v2/):
    uv run python scripts/generate_gold_exec.py
    uv run python scripts/generate_gold_exec.py --source bird_minidev
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl2sql.config import DATA_SOURCES, DATASET_AUGMENTATION_DIR

AUGMENTED_SOURCES = ("bird_minidev", "kaggledbqa", "spider_syn")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="all",
                    help=f"comma-separated source(s): {', '.join(AUGMENTED_SOURCES)}, "
                         "or 'all'")
    args = ap.parse_args()
    names = list(AUGMENTED_SOURCES) if args.source == "all" else args.source.split(",")

    for name in names:
        src = DATA_SOURCES[name]
        out_dir = DATASET_AUGMENTATION_DIR / name / "gold" / "exec_result"
        out_dir.mkdir(parents=True, exist_ok=True)

        rows = [json.loads(line) for line in open(src.questions_file, encoding="utf-8")]
        ok, failed = 0, []
        for i, q in enumerate(rows):
            iid, db_name, sql = q["instance_id"], q["db"], q.get("gold_sql")
            db_path = src.db_dir / f"{db_name}.sqlite"
            try:
                con = sqlite3.connect(str(db_path))
                # some source DBs (e.g. wta_1) have non-UTF-8 text columns;
                # decode leniently rather than raising, matching nl2sql/db.py
                con.text_factory = lambda b: b.decode("utf-8", "replace")
                try:
                    df = pd.read_sql_query(sql, con)
                finally:
                    con.close()
                df.to_csv(out_dir / f"{iid}.csv", index=False)
                ok += 1
            except Exception as e:
                failed.append((iid, str(e)))
            if (i + 1) % 100 == 0:
                print(f"[{name}] {i + 1}/{len(rows)} ...")

        print(f"{name}: {ok}/{len(rows)} gold CSVs written -> {out_dir}")
        if failed:
            print(f"{name}: {len(failed)} failed:")
            for iid, err in failed[:20]:
                msg = err[:200].encode("ascii", "replace").decode("ascii")
                print(f"  {iid}: {msg}")
            if len(failed) > 20:
                print(f"  ... and {len(failed) - 20} more")


if __name__ == "__main__":
    main()
