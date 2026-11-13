#!/usr/bin/env python3
"""Run every BEAVER gold query on MySQL (the dialect it was written for) and keep the results:
results.jsonl (one line per question: status, row and column counts, error, seconds) and
exec_result/<id>.csv (up to --max-rows rows). Resumes: questions already in results.jsonl are
skipped. The server is the one slurm/beaver_mysql.slurm starts (lower_case_table_names=1, as on
the macOS servers the dumps came from). Queries that lose the server (it crashed: MySQL 9.1.0
segfaults on some nested-CTE dw golds) are not recorded, and the run exits 3 so the caller can
restart the server and resume; a query that loses it again is recorded as server_gone.

Usage: python scripts/beaver_gold_mysql.py --questions <beaver-query/data> --out <dir> --socket <mysqld.sock>
"""

import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pymysql


GONE = (2003, 2006, 2013)  # can't connect, server has gone away, lost connection during query


def cell(v):
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    return v


def run_one(q, args, out):
    t0 = time.time()
    rec = {"id": q["id"], "db": q["db"]}
    try:
        con = pymysql.connect(unix_socket=args.socket, user="root", database=q["db"], charset="utf8mb4",
                              read_timeout=args.timeout + 60)
        try:
            with con.cursor() as cur:
                cur.execute(f"SET SESSION max_execution_time = {args.timeout * 1000}")
                cur.execute(q["sql"])
                cols = [d[0] for d in cur.description] if cur.description else []
                rows = cur.fetchmany(args.max_rows + 1)
        finally:
            con.close()
        rec.update(status="ok", columns=cols, rows=min(len(rows), args.max_rows),
                   truncated=len(rows) > args.max_rows)
        with open(out / "exec_result" / f"{q['id']}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows([cell(v) for v in r] for r in rows[:args.max_rows])
    except pymysql.MySQLError as e:
        code = e.args[0] if e.args else None
        status = "timeout" if code == 3024 else "server_gone" if code in GONE else "error"
        rec.update(status=status, error=str(e)[:500])
    rec["seconds"] = round(time.time() - t0, 2)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True, help="dir with BEAVER's beaver-query parquet files")
    ap.add_argument("--out", required=True)
    ap.add_argument("--socket", required=True)
    ap.add_argument("--timeout", type=int, default=120, help="seconds per query")
    ap.add_argument("--max-rows", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--record-gone", action="store_true", help="record server_gone results (a retry)")
    args = ap.parse_args()

    out = Path(args.out)
    (out / "exec_result").mkdir(parents=True, exist_ok=True)
    qs = pd.concat([pd.read_parquet(Path(args.questions) / f) for f in sorted(os.listdir(args.questions))
                    if f.endswith(".parquet")])[["id", "db", "sql"]].to_dict("records")
    res = out / "results.jsonl"
    done = {json.loads(line)["id"] for line in open(res)} if res.exists() else set()
    gone = 0
    todo = [q for q in qs if q["id"] not in done]
    print(f"{len(qs)} questions, {len(done)} done, {len(todo)} to run", flush=True)
    with open(res, "a") as f, ThreadPoolExecutor(args.workers) as ex:
        for i, rec in enumerate(ex.map(lambda q: run_one(q, args, out), todo), 1):
            if rec["status"] == "server_gone" and not args.record_gone:
                gone += 1
                continue
            f.write(json.dumps(rec) + "\n")
            f.flush()
            if i % 250 == 0:
                print(f"{i}/{len(todo)}", flush=True)
    recs = [json.loads(line) for line in open(res)]
    print({s: sum(r["status"] == s for r in recs) for s in ("ok", "error", "timeout", "server_gone")})
    if gone:
        print(f"{gone} queries lost the server; not recorded", flush=True)
        sys.exit(3)


if __name__ == "__main__":
    main()
