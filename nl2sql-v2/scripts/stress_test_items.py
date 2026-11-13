#!/usr/bin/env python3
"""Stress-test written items: run each gold and the blind solutions that matched it on
small altered copies of its database, and flag items where they stop agreeing. Two
queries can agree on the real data by coincidence while meaning different things;
equivalent queries agree on any copy (the test-suite idea from text-to-SQL evaluation),
so a split means the gold or the solution encodes a different reading, and the item
goes to review.

Each copy alters one table the queries read; the others are read in place. Alterations
keep the data realistic, because two readings that only differ on impossible data are not
a problem with the question:
  delete     drop a random 15% of the rows of a table no other table points to (deleting
             parents would leave orphans the real data never has)
  nudge      shift measure-like numbers (non-key, not a date part, 20+ distinct values) in
             a random 20% of rows, integers by -2..2 within the column's range, others by up
             to 10%
  nulls      blank a random 10% of a column that already holds NULLs
  more_rows  copy a random 5% of the rows as new entities, with fresh values for a
             single-column integer key (tables keyed by text, or with no key, are skipped)
Tables with more than --max-table-rows rows are only read, never altered.

Usage (NL2SQL_DATASET_DIR set):
    python scripts/stress_test_items.py --items items.jsonl --solutions sol.jsonl \\
        --output stress.jsonl [--copies 6]
"""

import argparse
import json
import re
import sqlite3
import sys
import threading
from collections import defaultdict
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql import db as dbmod
from nl2sql.config import DATASET_DIR, DCE_PROJECT_DIR, SQLITE_DIR
from generate_trap_items import matches

HOWS = ["delete", "nudge", "nulls", "more_rows"]
NUMERIC = re.compile(r"INT|DOUBLE|FLOAT|REAL|DECIMAL|NUMERIC|HUGEINT")


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def tables_in(sql: str) -> set[str]:
    import sqlglot
    from sqlglot import exp
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return set()
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    return {t.name for t in tree.find_all(exp.Table) if t.name and t.name.lower() not in ctes}


class Source:
    """One database's objects, sizes and keys, read lazily."""

    def __init__(self, name: str):
        self.path = SQLITE_DIR / f"{name}.sqlite"
        self.lite = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        rows = self.lite.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') "
                                 "AND name NOT LIKE 'sqlite_%'").fetchall()
        self.objects = [n for n, _ in rows]
        self.tables = {n.lower(): n for n, t in rows if t == "table"}
        kp = DCE_PROJECT_DIR / "output" / "keys" / f"{name}.json"
        keys = json.loads(kp.read_text()) if kp.exists() else {}
        self.unique = {t.lower(): [c[0] for c in (r.get("candidates") or []) if len(c) == 1]
                       for t, r in keys.items()}
        # columns named like any table's single-column key are join keys wherever they appear,
        # and so are declared foreign keys
        self.join_keys = {c.lower() for cs in self.unique.values() for c in cs}
        self.parents = set()  # tables another table points to
        cols = {t: {r[1].lower() for r in self.lite.execute(f"PRAGMA table_info({q(t)})")}
                for t in self.tables.values()}
        for t in self.tables.values():
            for r in self.lite.execute(f"PRAGMA foreign_key_list({q(t)})").fetchall():
                self.join_keys.add(str(r[3]).lower())
                self.parents.add(str(r[2]).lower())
        for t, ks in self.unique.items():  # a key column name that appears in another table
            if any(k.lower() in c for k in ks for o, c in cols.items() if o.lower() != t):
                self.parents.add(t)
        self._rows = {}

    def n_rows(self, table: str) -> int:
        if table not in self._rows:
            self._rows[table] = self.lite.execute(f"SELECT COUNT(*) FROM {q(table)}").fetchone()[0]
        return self._rows[table]


def run(con, sql: str, timeout: float):
    timer = threading.Timer(timeout, con.interrupt)
    timer.start()
    try:
        return dbmod._decode_bytes(dbmod._run(con, sql))
    finally:
        timer.cancel()


def altered(src: Source, table: str, how: str, seed: int):
    """(connection whose `table` is an altered copy, description) or None if not applicable."""
    con = duckdb.connect(":memory:")
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute("SET disabled_optimizers='cte_inlining,common_subplan'")
    con.execute(f"SET memory_limit='{dbmod.MEMORY_LIMIT}'")
    con.execute(f"ATTACH '{src.path}' AS src (TYPE sqlite, READ_ONLY)")
    con.execute("ATTACH ':memory:' AS alt")
    con.execute("USE alt")
    for o in src.objects:
        kind = "TABLE" if o == table else "VIEW"
        con.execute(f"CREATE {kind} {q(o)} AS SELECT * FROM src.{q(o)}")
    con.execute(f"SELECT setseed({(seed % 997) / 997})")
    cols = con.execute("SELECT column_name, data_type FROM information_schema.columns "
                       "WHERE table_catalog = 'alt' AND table_name = ?", [table]).fetchall()
    keys = {k.lower() for k in src.unique.get(table.lower(), [])}
    plain = [(c, t) for c, t in cols if c.lower() not in keys | src.join_keys
             and not re.search(r"(id|number|no|code|key)$", c, re.I)]
    t = q(table)
    if how == "delete":
        if table.lower() in src.parents:
            return None
        con.execute(f"DELETE FROM {t} WHERE random() < 0.15")
        return con, "deleted 15% of rows"
    if how == "nudge":
        nums = [(c, ty) for c, ty in plain if NUMERIC.search(ty.upper())
                and not re.search(r"year|date|month|day|hour|time|week|quarter", c, re.I)
                and con.execute(f"SELECT COUNT(DISTINCT {q(c)}) FROM {t}").fetchone()[0] >= 20]
        if not nums:
            return None
        for c, ty in nums[:3]:
            if "INT" in ty.upper():
                lo, hi = con.execute(f"SELECT min({q(c)}), max({q(c)}) FROM {t}").fetchone()
                expr = (f"least(greatest({q(c)} + CAST(floor(random() * 5) - 2 AS BIGINT), {lo}), "
                        f"{hi})")
            else:
                expr = f"{q(c)} * (0.9 + random() * 0.2)"
            con.execute(f"UPDATE {t} SET {q(c)} = {expr} WHERE random() < 0.2 AND {q(c)} IS NOT NULL")
        return con, f"nudged {', '.join(c for c, _ in nums[:3])} in 20% of rows"
    if how == "nulls":
        with_nulls = [c for c, _ in plain
                      if con.execute(f"SELECT COUNT(*) FROM {t} WHERE {q(c)} IS NULL").fetchone()[0]]
        if not with_nulls:
            return None
        c = with_nulls[seed % len(with_nulls)]
        con.execute(f"UPDATE {t} SET {q(c)} = NULL WHERE random() < 0.1")
        return con, f"blanked 10% of {c}"
    if how == "more_rows":
        if not keys:
            return None  # exact duplicate rows: not a new entity, just bad data
        ints = sorted((c for c, ty in cols if c.lower() in keys and "INT" in ty.upper()),
                      key=lambda c: not re.search(r"id$|number$|no$", c, re.I))
        if not ints:
            return None  # keyed by text: copies would duplicate the key
        k = ints[0]  # other columns that happen to be unique (names) may repeat, as in real data
        top = con.execute(f"SELECT max({q(k)}) FROM {t}").fetchone()[0] or 0
        con.execute(f"INSERT INTO {t} SELECT * REPLACE ({q(k)} + {int(top)} AS {q(k)}) "
                    f"FROM {t} WHERE random() < 0.05")
        return con, f"copied 5% of rows with new {k}"
    raise ValueError(how)


def stress(item: dict, sols: list[str], args) -> dict:
    out = {"id": item["id"], "db": item["db"], "status": "untested", "copies": []}
    src = Source(item["db"])
    base = dbmod.Database(src.path)
    base.con.execute("SET disabled_optimizers='cte_inlining,common_subplan'")
    try:
        gold = base.query_preview(item["gold_sql"], 1, 10_000, timeout_s=args.timeout)[0]
        agreeing = []
        for s in sols:
            try:
                if matches(base.query_preview(s, 1, 10_000, timeout_s=args.timeout)[0], gold):
                    agreeing.append(s)
            except Exception:
                pass
    except Exception as e:
        out["note"] = f"gold failed: {' '.join(str(e).split())[:120]}"
        return out
    finally:
        base.close()
    if not agreeing:
        out["note"] = "no solution matched the gold on the real data"
        return out
    targets = sorted({src.tables[t.lower()] for s in [item["gold_sql"]] + agreeing
                      for t in tables_in(s) if t.lower() in src.tables})
    targets = [t for t in targets if 0 < src.n_rows(t) <= args.max_table_rows]
    if not targets:
        out["note"] = "every table it reads is empty or too large to alter"
        return out
    splits = 0
    combos = [(t, h) for h in HOWS for t in targets]  # every alteration of every table, in turn
    plan = [(*combos[i % len(combos)], i) for i in range(max(args.copies, len(combos)) * 2)]
    for table, how, seed in plan:
        if len(out["copies"]) >= args.copies:
            break
        try:
            made = altered(src, table, how, seed)
        except Exception as e:
            out["copies"].append({"table": table, "how": how, "error": str(e)[:120]})
            continue
        if made is None:
            continue
        con, desc = made
        rec = {"table": table, "how": desc, "seed": seed}
        try:
            g = run(con, item["gold_sql"], args.timeout)
            rec["gold_rows"] = len(g)
            bad = []
            for i, s in enumerate(agreeing):
                try:
                    if not matches(run(con, s, args.timeout), g):
                        bad.append(i)
                except Exception:
                    pass
            rec["split_solutions"] = bad
            splits += bool(bad)
        except Exception as e:
            rec["error"] = " ".join(str(e).split())[:120]
        finally:
            con.close()
        out["copies"].append(rec)
    tested = [c for c in out["copies"] if "gold_rows" in c]
    if tested:
        out["status"] = "split" if splits else "agree"
        out["solutions_compared"] = len(agreeing)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True, help="comma-separated item files")
    ap.add_argument("--solutions", required=True, help="comma-separated blind-solution files")
    ap.add_argument("--output", required=True)
    ap.add_argument("--copies", type=int, default=6)
    ap.add_argument("--max-table-rows", type=int, default=1_000_000)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--only-ids", help="file of item ids (one per line)")
    args = ap.parse_args()
    if not DATASET_DIR:
        raise SystemExit("set NL2SQL_DATASET_DIR to the question set")
    items = [json.loads(l) for f in args.items.split(",") for l in open(f) if l.strip()]
    if args.only_ids:
        keep = set(Path(args.only_ids).read_text().split())
        items = [it for it in items if it["id"] in keep]
    sols = defaultdict(list)
    for f in args.solutions.split(","):
        for r in map(json.loads, (l for l in open(f) if l.strip())):
            if str(r.get("sql") or "").strip():
                sols[r["id"]].append(r["sql"])
    counts = defaultdict(int)
    with open(args.output, "w") as f:
        for it in items:
            if it["id"] not in sols:
                continue
            r = stress(it, sols[it["id"]], args)
            counts[r["status"]] += 1
            f.write(json.dumps(r) + "\n")
            f.flush()
            detail = "; ".join(f"{c['table']}: {c['how']}" + (" SPLIT" if c.get("split_solutions") else "")
                               for c in r["copies"] if "gold_rows" in c)
            print(f"{it['id']}: {r['status']} ({detail or r.get('note', '')})", flush=True)
    print(f"\n{dict(counts)} -> {args.output}")


if __name__ == "__main__":
    main()
