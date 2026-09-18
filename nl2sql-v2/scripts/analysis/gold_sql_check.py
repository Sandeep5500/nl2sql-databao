#!/usr/bin/env python3
"""Execute Spider2's official answer-key SQL and score it with our own scorer,
through both the agent's DuckDB path and raw SQLite. Backs Section 2 of
documents/retrieval_vs_generation_findings.md.

A gold SQL that fails in DuckDB but passes in SQLite is a dialect artifact:
its linkage is still valid. One that fails in both answers a different
question than the graded CSV, and must not be used as an oracle source.

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/gold_sql_check.py
    uv run python scripts/analysis/gold_sql_check.py --diagnose
"""

import argparse
import sqlite3

import pandas as pd

from _common import (GOLD_SQL_DIR, SQLITE_DIR, Database, gold_files,
                     load_eval_standards, local_questions, score_against_gold)
from nl2sql.db import _decode_bytes


def run_sqlite(path, sql):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    try:
        return _decode_bytes(pd.read_sql_query(sql, con)).head(5000)
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=0,
                    help="re-execute each gold SQL this many times via DuckDB and "
                         "flag any whose score flips between executions")
    ap.add_argument("--diagnose", action="store_true",
                    help="for gold SQL failing both paths, compare its output to the gold CSV")
    args = ap.parse_args()

    std = load_eval_standards()
    qdb = {k: v["db"] for k, v in local_questions().items()}
    rows = []
    for f in sorted(GOLD_SQL_DIR.glob("local*.sql")):
        iid = f.stem
        if iid not in qdb:
            continue
        sql = f.read_text().strip().rstrip(";")
        path = SQLITE_DIR / f"{qdb[iid]}.sqlite"
        duck = lite = False
        note = ""
        try:
            db = Database(path)
            df, _ = db.query_preview(sql, preview_rows=1, max_rows=5000)
            duck = score_against_gold(df, iid, std)[0] == 1
            db.close()
        except Exception as e:
            note = f"DuckDB: {type(e).__name__}: {str(e).splitlines()[0][:60]}"
        try:
            lite = score_against_gold(run_sqlite(path, sql), iid, std)[0] == 1
        except Exception as e:
            note = note or f"SQLite: {type(e).__name__}"
        rows.append((iid, qdb[iid], duck, lite, note))

    r = pd.DataFrame(rows, columns=["iid", "db", "duckdb", "sqlite", "note"])
    print(f"official gold SQL, local split : {len(r)}")
    print(f"  scores correct via DuckDB    : {r.duckdb.sum()}")
    print(f"  scores correct via SQLite    : {r.sqlite.sum()}")
    print(f"  fails both (wrong question)  : {(~r.duckdb & ~r.sqlite).sum()}")
    print(f"  SQLite only (dialect)        : {(r.sqlite & ~r.duckdb).sum()}")
    print("\ntrustworthy (valid in SQLite):", " ".join(r[r.sqlite].iid))
    print("\n" + r[~(r.duckdb & r.sqlite)].to_string(index=False))

    if args.repeats:
        from collections import Counter
        print(f"\nnondeterminism check, {args.repeats} DuckDB executions each:")
        flips = 0
        for iid in r.iid:
            sql = (GOLD_SQL_DIR / f"{iid}.sql").read_text().strip().rstrip(";")
            seen = Counter()
            for _ in range(args.repeats):
                try:
                    db = Database(SQLITE_DIR / f"{qdb[iid]}.sqlite")
                    df, _ = db.query_preview(sql, preview_rows=1, max_rows=5000)
                    db.close()
                    seen[score_against_gold(df, iid, std)[0]] += 1
                except Exception:
                    seen["error"] += 1
            if len(seen) > 1:
                flips += 1
                print(f"   {iid}: {dict(seen)}")
        print(f"   {flips} of {len(r)} flip between executions")

    if args.diagnose:
        for iid in r[~r.duckdb & ~r.sqlite].iid:
            try:
                got = run_sqlite(SQLITE_DIR / f"{qdb[iid]}.sqlite",
                                 (GOLD_SQL_DIR / f"{iid}.sql").read_text().strip().rstrip(";"))
            except Exception as e:
                print(f"\n{iid}: gold SQL does not execute ({type(e).__name__})")
                continue
            gold = [pd.read_csv(g) for g in gold_files(iid)]
            print(f"\n{iid}: gold SQL returns {got.shape}, gold CSV variants "
                  f"{[g.shape for g in gold]}")
            print(f"   SQL cols {list(got.columns)[:6]}")
            print(f"   CSV cols {list(gold[0].columns)[:6]}")


if __name__ == "__main__":
    main()
