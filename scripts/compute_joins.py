#!/usr/bin/env python3
"""Precompute join hazards between same-named columns in different tables.

Data only, no LLM. For every column name that appears in more than one table,
record the two declared types and how many of this column's distinct values
actually occur in the other one. Two things are worth the agent's attention and
cost it steps today:

  TYPE MISMATCH  f1.retirements.lap is VARCHAR while f1.lap_positions.lap is
                 INT. The join needs a cast, and an uncast join in DuckDB either
                 errors or silently matches nothing. One lane spent 25 queries
                 on that f1 question and submitted a diagnostic probe.
  NO OVERLAP     the names line up but the values do not, so the join returns
                 zero rows and the agent reads that as "the answer is empty".

Only facts measured from the data are written -- no guess about whether a pair
is "really" a foreign key.

Usage (from repo root):
    uv run --project nl2sql-v2 python scripts/compute_joins.py \
        --out-dir spider2-dce/output/joins
    uv run --project nl2sql-v2 python scripts/compute_joins.py \
        --out-dir spider2-dce/output/joins --datasources f1,bank_sales_trading
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nl2sql-v2/src"))
from nl2sql.config import DCE_PROJECT_DIR, SQLITE_DIR  # noqa: E402


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _numeric(t: str) -> bool:
    t = (t or "").upper()
    return any(k in t for k in ("INT", "REAL", "FLOA", "DOUB", "NUM", "DEC"))


def _texty(t: str) -> bool:
    t = (t or "").upper()
    return any(k in t for k in ("CHAR", "TEXT", "CLOB", "STRING"))


# A QUALIFIED foreign-key-ish name: customer_id, product_no, store_code. A bare
# "id" or "name" is each table's own surrogate key -- inventory.id and
# breweries.id share a name and nothing else, and flagging those 172 pairs in
# oracle_sql buried the real hazards.
_KEYISH = re.compile(r"^\w+_(id|ids|key|code|no|num|number)$", re.I)


def _looks_like_key(col: str) -> bool:
    """A column someone would plausibly join on, so an empty overlap is worth
    flagging. Measure columns and bare surrogate keys are not."""
    return bool(_KEYISH.match(col))


def types_clash(a: str, b: str) -> bool:
    """A join that needs a cast, in DuckDB's view of the SQLite file.

    BLOB is the one that bites hardest and is invisible in the SQLite schema: a
    column SQLite declares with an EMPTY type (which it allows) arrives in
    DuckDB as BLOB, and joining BLOB to BIGINT does not silently mismatch --
    it raises "Unimplemented type for cast (BIGINT -> BLOB)". That is exactly
    f1.retirements.lap against f1.lap_positions.lap.
    """
    a, b = (a or "").upper(), (b or "").upper()
    if ("BLOB" in a) != ("BLOB" in b):
        return True
    return (_numeric(a) and _texty(b)) or (_texty(a) and _numeric(b))


def distinct_values(con, table, col, cap):
    """Distinct non-null values as text, or None when too many to compare."""
    n = con.execute(
        f"SELECT COUNT(DISTINCT CAST({q(col)} AS VARCHAR)) FROM db.{q(table)}"
    ).fetchone()[0]
    if n == 0 or n > cap:
        return None, n
    rows = con.execute(
        f"SELECT DISTINCT CAST({q(col)} AS VARCHAR) FROM db.{q(table)} "
        f"WHERE {q(col)} IS NOT NULL"
    ).fetchall()
    # trailing-space and case differences are real join hazards; keep them, but
    # compare on the raw text exactly as DuckDB would.
    return {r[0] for r in rows}, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--datasources", help="comma-separated yaml stems (default: all)")
    ap.add_argument("--distinct-cap", type=int, default=200_000,
                    help="skip overlap when a column has more distinct values")
    ap.add_argument("--budget-s", type=float, default=180.0, help="per database")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    want = set(args.datasources.split(",")) if args.datasources else None
    by_norm = {re.sub(r"[^a-z0-9]", "_", p.stem.lower()): p
               for p in SQLITE_DIR.glob("*.sqlite") if p.stat().st_size}

    for src in sorted((DCE_PROJECT_DIR / "output" / "databases").glob("*.yaml")):
        if want and src.stem not in want:
            continue
        if src.stem not in by_norm:
            print(f"no sqlite file for {src.stem}; skipped")
            continue
        sqlite_path = by_norm[src.stem]
        t0 = time.time()

        con = duckdb.connect()
        con.execute(f"ATTACH '{sqlite_path}' AS db (TYPE sqlite, READ_ONLY)")
        # Types as DUCKDB sees them -- that is what the agent's queries hit, and
        # it differs from the SQLite schema exactly where it matters (a typeless
        # SQLite column shows up as BLOB).
        coltypes: dict[str, dict[str, str]] = {}
        for t, c, ty in con.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_catalog = 'db' ORDER BY table_name, ordinal_position").fetchall():
            coltypes.setdefault(t, {})[c] = ty or ""

        # column name -> [(table, declared type)], only names in >1 table
        shared: dict[str, list[tuple[str, str]]] = {}
        for t, cols in coltypes.items():
            for c, ty in cols.items():
                shared.setdefault(c.lower(), []).append((t, ty))
        shared = {c: v for c, v in shared.items() if len(v) > 1}

        cache: dict[tuple[str, str], tuple] = {}
        out: dict[str, list[dict]] = {}
        npairs = 0

        for col, holders in sorted(shared.items()):
            if time.time() - t0 > args.budget_s:
                print(f"  {src.stem}: budget reached, stopping early")
                break
            for i in range(len(holders)):
                for j in range(i + 1, len(holders)):
                    (ta, tya), (tb, tyb) = holders[i], holders[j]
                    clash = types_clash(tya, tyb)
                    key_a, key_b = (ta, col), (tb, col)
                    try:
                        if key_a not in cache:
                            cache[key_a] = distinct_values(con, ta, col, args.distinct_cap)
                        if key_b not in cache:
                            cache[key_b] = distinct_values(con, tb, col, args.distinct_cap)
                        va, na = cache[key_a]
                        vb, nb = cache[key_b]
                    except Exception:
                        continue
                    shared_n = None if (va is None or vb is None) else len(va & vb)
                    # Only report what would cost the agent steps. A type clash
                    # always would -- DuckDB raises on it. "No values in common"
                    # is only worth saying for a column someone would actually
                    # join on; two unrelated measure columns that happen to
                    # share a name (results.milliseconds vs pit_stops.
                    # milliseconds) are noise, not a hazard.
                    if not clash:
                        if shared_n is None or shared_n > 0:
                            continue
                        if not _looks_like_key(col):
                            continue
                    if shared_n == 0 and (na == 0 or nb == 0):
                        continue          # an empty column is not a join hazard
                    rec = {"column": col, "other_table": tb,
                           "this_type": tya, "other_type": tyb,
                           "type_mismatch": clash,
                           "distinct_here": na, "distinct_there": nb,
                           "values_in_common": shared_n}
                    out.setdefault(ta, []).append(rec)
                    out.setdefault(tb, []).append(
                        {**rec, "other_table": ta, "this_type": tyb,
                         "other_type": tya, "distinct_here": nb,
                         "distinct_there": na})
                    npairs += 1
        con.close()
        (out_dir / f"{src.stem}.json").write_text(json.dumps(out, indent=1, sort_keys=True))
        print(f"{src.stem}: {len(shared)} shared column names, "
              f"{npairs} hazard pair(s), {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
