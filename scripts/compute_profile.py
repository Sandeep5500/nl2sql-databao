#!/usr/bin/env python3
"""Precompute a per-column profile of every table, from the data only (no LLM).

For each column: what the values are (integer / decimal / date / text), their
range, the full value list when there are few, and for text the common value
shapes (e.g. '99-99-9999', '999.99A') so odd encodings are visible.
describe_table shows these as facts.

Usage (from repo root):
    uv run --project nl2sql-v2 python scripts/compute_profile.py --out-dir spider2-dce/output/profile
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nl2sql-v2/src"))
from nl2sql.config import DCE_PROJECT_DIR, SQLITE_DIR  # noqa: E402

FEW = 12          # list every value when a column has at most this many
SHAPES = 3        # value shapes shown for text columns


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def clip(v, n=40):
    s = str(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def profile_table(con, table: str, columns: list[tuple[str, str]], row_limit: int) -> dict:
    n = con.execute(f"SELECT COUNT(*) FROM db.{q(table)}").fetchone()[0]
    out = {"n_rows": n, "columns": {}}
    if n == 0 or n > row_limit:
        return out
    sel = ", ".join(f"CAST({q(c)} AS VARCHAR) AS {q(c)}" for c, _ in columns)
    con.execute(f"CREATE OR REPLACE TEMP TABLE _t AS SELECT {sel} FROM db.{q(table)}")
    for c, declared in columns:
        qc = q(c)
        (nn, empty, distinct, n_num, n_int, n_date, n_ts, lo, hi) = con.execute(f"""
            SELECT COUNT({qc}),
                   COUNT(*) FILTER (WHERE {qc} = ''),
                   COUNT(DISTINCT {qc}),
                   COUNT(TRY_CAST({qc} AS DOUBLE)),
                   COUNT(*) FILTER (WHERE TRY_CAST({qc} AS DOUBLE) = ROUND(TRY_CAST({qc} AS DOUBLE))),
                   COUNT(TRY_CAST({qc} AS DATE)),
                   COUNT(TRY_CAST({qc} AS TIMESTAMP)),
                   MIN({qc}), MAX({qc})
            FROM _t""").fetchone()
        p = {"nulls": n - nn, "distinct": distinct}
        if empty:
            p["empty_strings"] = empty
        filled = nn - empty
        if filled == 0:
            p["kind"] = "empty"
        elif n_num == filled:
            p["kind"] = "integer" if n_int == filled else "decimal"
            lo_n, hi_n = con.execute(
                f"SELECT MIN(TRY_CAST({qc} AS DOUBLE)), MAX(TRY_CAST({qc} AS DOUBLE)) FROM _t"
            ).fetchone()
            fmt = (lambda v: int(v)) if p["kind"] == "integer" else (lambda v: round(v, 4))
            p["min"], p["max"] = fmt(lo_n), fmt(hi_n)
        elif n_ts == filled:
            p["kind"] = "date" if n_date == filled and all(
                len(str(v)) <= 10 for v in (lo, hi)) else "datetime"
            lo_d, hi_d = con.execute(
                f"SELECT MIN(TRY_CAST({qc} AS TIMESTAMP)), MAX(TRY_CAST({qc} AS TIMESTAMP)) "
                f"FROM _t WHERE {qc} <> ''").fetchone()
            p["min"], p["max"] = str(lo_d)[:19], str(hi_d)[:19]
            if p["kind"] == "date":
                p["min"], p["max"] = p["min"][:10], p["max"][:10]
            if str(lo) not in (p["min"], p["min"][:10]):
                p["stored_like"] = clip(lo, 30)  # parses as a date but is not ISO text
        else:
            p["kind"] = "text"
            if n_num:  # mostly text, but some values parse as numbers
                p["numeric_values"] = n_num
        if distinct <= FEW:
            p["values"] = [[clip(v), cnt] for v, cnt in con.execute(
                f"SELECT {qc}, COUNT(*) FROM _t WHERE {qc} IS NOT NULL "
                f"GROUP BY 1 ORDER BY 2 DESC, 1").fetchall()]
        elif p["kind"] == "text":
            # value shapes: digits -> 9 (count kept), letter runs -> A
            rows = con.execute(f"""
                SELECT regexp_replace(regexp_replace({qc}, '[0-9]', '9', 'g'),
                                      '[A-Za-z]+', 'A', 'g') AS shape,
                       COUNT(*) AS cnt, MIN({qc}) AS example
                FROM _t WHERE {qc} IS NOT NULL AND {qc} <> ''
                GROUP BY 1 ORDER BY 2 DESC LIMIT {SHAPES + 1}""").fetchall()
            n_shapes = con.execute(f"""
                SELECT COUNT(DISTINCT regexp_replace(regexp_replace({qc}, '[0-9]', '9', 'g'),
                                                     '[A-Za-z]+', 'A', 'g'))
                FROM _t WHERE {qc} IS NOT NULL AND {qc} <> ''""").fetchone()[0]
            top = rows[:SHAPES]
            covered = sum(r[1] for r in top) / filled
            # only worth showing when values are structured, not free text
            if covered >= 0.8 and any(re.search(r"[9\W]", r[0].replace(" ", "")) for r in top):
                p["shapes"] = [[clip(s, 30), round(cnt / filled, 3), clip(ex, 30)]
                               for s, cnt, ex in top]
                p["n_shapes"] = n_shapes
        out["columns"][c] = p
    con.execute("DROP TABLE IF EXISTS _t")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--datasources", help="comma-separated yaml stems (default: all)")
    ap.add_argument("--row-limit", type=int, default=5_000_000)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    want = set(args.datasources.split(",")) if args.datasources else None
    by_norm = {re.sub(r"[^a-z0-9]", "_", p.stem.lower()): p
               for p in SQLITE_DIR.glob("*.sqlite") if p.stat().st_size}
    for src in sorted((DCE_PROJECT_DIR / "output" / "databases").glob("*.yaml")):
        if (want and src.stem not in want) or src.stem not in by_norm:
            continue
        sqlite_path = by_norm[src.stem]
        lite = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
        tables = [r[0] for r in lite.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        schema = {t: [(r[1], r[2]) for r in lite.execute(f"PRAGMA table_info({q(t)})")]
                  for t in tables}
        lite.close()
        con = duckdb.connect(":memory:")
        con.execute("INSTALL sqlite; LOAD sqlite; SET GLOBAL sqlite_all_varchar=true")
        con.execute(f"ATTACH '{sqlite_path}' AS db (TYPE sqlite, READ_ONLY)")
        result, t0 = {}, time.time()
        for t in tables:
            try:
                result[t] = profile_table(con, t, schema[t], args.row_limit)
            except Exception as e:
                result[t] = {"error": str(e)[:200], "columns": {}}
        con.close()
        (out_dir / f"{src.stem}.json").write_text(json.dumps(result, indent=1, default=str))
        print(f"{src.stem}: {len(tables)} tables ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
