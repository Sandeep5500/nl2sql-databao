#!/usr/bin/env python3
"""Fill a schema-only SQLite database with realistic data.

SynSQL's 16,583 databases are schema skeletons: a median of 18 rows across all
tables. The synthesis pipeline executes its gold SQL to define the answer, so
18 rows makes that guarantee vacuous -- aggregates run over one or two rows,
GROUP BYs return a single group, ratios come out 0 or 1, and nothing a solver
could get wrong is left to get wrong.

This populates a schema to volumes where aggregates mean something, and
deliberately preserves the two properties our failure taxonomy needs:

  * ENTITIES WITH ZERO MATCHING ROWS. Measured the hard way: uniform FK
    assignment saturated 7 of 8 relationships in our hand-built test database,
    so LEFT JOIN and INNER JOIN agreed and 18 of 21 `boundary` generation
    attempts failed with "naive gives an identical result". Here a fraction of
    each parent's rows is held out of every child's FK pool.
  * NULLs in nullable columns, so COUNT(*) and COUNT(col) differ and an
    average over an empty subset reads NULL rather than 0.

Existing rows are kept and used as style templates: a schema that ships three
sample rows tells us what its TEXT columns actually look like, which is better
than inventing formats.

Usage (from nl2sql-v2/):
    uv run python scripts/populate_db.py --db path/to/x.sqlite --seed 7
    uv run python scripts/populate_db.py --dir synsql_dbs/ --seed 7 --out-dir filled/
"""

import argparse
import random
import re
import shutil
import sqlite3
import string
import zlib
from pathlib import Path

# Fact tables get volume, dimension tables stay small. Which is which comes from
# the FK graph: a table nothing references is a leaf, i.e. a fact table.
FACT_ROWS = (2000, 20000)
DIM_ROWS = (12, 80)
NULL_RATE = 0.08          # of nullable, non-FK columns
ORPHAN_RATE = 0.12        # of each parent's rows held out of a child's FK pool



def stable_hash(s: str) -> int:
    """A process-independent digest.

    str.__hash__ is salted per interpreter (PYTHONHASHSEED), so seeding an RNG
    from hash() silently made --seed non-reproducible: the same seed produced
    different data on every run. Measured: hash("store_1.sqlite") & 0xFFFF gave
    14513, 33050 and 28089 across three processes.
    """
    return zlib.crc32(s.encode())

DATEISH = re.compile(r"(date|time|_at$|_on$|birth|created|updated|expir)", re.I)
MONEYISH = re.compile(r"(price|cost|amount|fee|salary|revenue|total|balance|budget)", re.I)
COUNTISH = re.compile(r"(count|qty|quantity|number|num_|_num|stock|views|likes)", re.I)
RATEISH = re.compile(r"(rate|ratio|percent|pct|score|rating|avg|average)", re.I)
NAMEISH = re.compile(r"(name|title|label|subject)", re.I)
EMAILISH = re.compile(r"(email|mail)", re.I)
BOOLISH = re.compile(r"(is_|has_|_flag|active|enabled|deleted|verified)", re.I)

WORDS = ("north south east west central upper lower inner outer prime core "
         "delta sigma orion vertex summit harbor ridge grove haven "
         "alpha beta gamma nova lumen atlas pioneer frontier").split()


def schema(db):
    """{table: {"cols": [(name, type, notnull, pk)], "fks": [(col, ptable, pcol)]}}"""
    out = {}
    for (t,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"):
        cols = [(r[1], (r[2] or "").upper(), r[3], r[5])
                for r in db.execute(f'PRAGMA table_info("{t}")')]
        fks = [(r[3], r[2], r[4]) for r in db.execute(f'PRAGMA foreign_key_list("{t}")')]
        out[t] = {"cols": cols, "fks": fks}
    return out


def order_tables(sch):
    """Parents before children, so a child's FK pool is already populated."""
    done, out = set(), []
    pending = dict(sch)
    while pending:
        ready = [t for t, v in pending.items()
                 if all(p in done or p == t or p not in sch for _, p, _ in v["fks"])]
        if not ready:                       # a cycle: break it arbitrarily
            ready = [next(iter(pending))]
        for t in sorted(ready):
            out.append(t)
            done.add(t)
            pending.pop(t)
    return out


def affinity(decl):
    d = (decl or "").upper()
    if any(k in d for k in ("INT",)):
        return "int"
    if any(k in d for k in ("REAL", "FLOA", "DOUB", "NUM", "DEC")):
        return "real"
    return "text"


def make_value(col, decl, rng, samples):
    """A plausible value. Reuses a sample value for TEXT when one exists, so the
    schema's own formats are preserved rather than invented."""
    aff = affinity(decl)
    if BOOLISH.search(col) and aff == "int":
        return rng.randint(0, 1)
    if DATEISH.search(col):
        y, m, d = rng.randint(2019, 2026), rng.randint(1, 12), rng.randint(1, 28)
        if aff == "int":
            return y * 10000 + m * 100 + d
        if "time" in col.lower() or col.lower().endswith("_at"):
            return f"{y:04d}-{m:02d}-{d:02d} {rng.randint(0,23):02d}:{rng.randint(0,59):02d}:00"
        return f"{y:04d}-{m:02d}-{d:02d}"
    if aff == "int":
        if COUNTISH.search(col):
            return int(rng.gammavariate(2.0, 14))
        if MONEYISH.search(col):
            return int(rng.gammavariate(2.0, 3000))
        return rng.randint(1, 10000)
    if aff == "real":
        if RATEISH.search(col):
            return round(rng.uniform(0, 5) if "rating" in col.lower()
                         else rng.uniform(0, 100), 2)
        if MONEYISH.search(col):
            return round(rng.gammavariate(2.0, 120), 2)
        return round(rng.uniform(0, 1000), 3)
    # text
    if samples and rng.random() < 0.45:
        s = str(rng.choice(samples))
        if NAMEISH.search(col) and len(s) > 3:         # perturb so it is not a dup
            return f"{s.rsplit(' ', 1)[0]} {rng.choice(WORDS).title()}"
        return s
    if EMAILISH.search(col):
        return f"{rng.choice(WORDS)}{rng.randint(1,999)}@example.org"
    if NAMEISH.search(col):
        return f"{rng.choice(WORDS).title()} {rng.choice(WORDS).title()}"
    return "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(5, 12)))


def populate(path: Path, seed: int, fact_rows=FACT_ROWS, dim_rows=DIM_ROWS) -> dict:
    rng = random.Random(seed ^ (stable_hash(path.name) & 0xFFFF))
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=OFF")
    sch = schema(db)
    if not sch:
        db.close()
        return {"tables": 0}

    referenced = {p for v in sch.values() for _, p, _ in v["fks"] if p in sch}
    order = order_tables(sch)
    # FK pools, minus a held-out slice so some parent rows stay unreferenced
    pools, added = {}, {}

    for t in order:
        v = sch[t]
        pk_int = [c for c, d, nn, pk in v["cols"] if pk and affinity(d) == "int"]
        fkmap = {c: (p, pc) for c, p, pc in v["fks"] if p in sch}
        samples = {}
        for c, d, nn, pk in v["cols"]:
            if affinity(d) == "text":
                samples[c] = [r[0] for r in db.execute(
                    f'SELECT DISTINCT "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL LIMIT 8')]
        have = db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        target = rng.randint(*(dim_rows if t in referenced else fact_rows))
        need = max(0, target - have)

        cols = [c for c, d, nn, pk in v["cols"]]
        rows = []
        next_pk = {}
        for c in pk_int:
            mx = db.execute(f'SELECT COALESCE(MAX("{c}"), 0) FROM "{t}"').fetchone()[0]
            next_pk[c] = mx + 1
        for _ in range(need):
            row = []
            for c, d, nn, pk in v["cols"]:
                if c in next_pk:
                    row.append(next_pk[c]); next_pk[c] += 1
                elif c in fkmap:
                    p, pc = fkmap[c]
                    pool = pools.get((p, pc)) or [None]
                    val = rng.choice(pool)
                    if val is not None and not nn and rng.random() < 0.05:
                        val = None                      # orphan child row
                    row.append(val)
                elif not nn and rng.random() < NULL_RATE:
                    row.append(None)
                else:
                    row.append(make_value(c, d, rng, samples.get(c) or []))
            rows.append(tuple(row))
        if rows:
            ph = ",".join("?" * len(cols))
            qc = ",".join(f'"{c}"' for c in cols)
            db.executemany(f'INSERT OR IGNORE INTO "{t}" ({qc}) VALUES ({ph})', rows)
        added[t] = need

        # publish this table's key pools for children, holding ORPHAN_RATE back
        for c, d, nn, pk in v["cols"]:
            if not (pk or c in next_pk):
                continue
            vals = [r[0] for r in db.execute(
                f'SELECT "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL')]
            if not vals:
                continue
            rng.shuffle(vals)
            keep = max(1, int(len(vals) * (1 - ORPHAN_RATE)))
            pools[(t, c)] = vals[:keep]
            pools[(t, None)] = vals[:keep]      # FK with no explicit parent column

    db.commit()
    total = sum(db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in sch)
    db.close()
    return {"tables": len(sch), "rows": total, "added": sum(added.values())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="one database to fill in place")
    ap.add_argument("--dir", help="directory of .sqlite files")
    ap.add_argument("--out-dir", help="copy to here first, leaving inputs untouched")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--limit", type=int, help="only the first N of --dir")
    args = ap.parse_args()

    if args.db:
        targets = [Path(args.db)]
    elif args.dir:
        targets = sorted(Path(args.dir).glob("*.sqlite"))[:args.limit]
    else:
        raise SystemExit("pass --db or --dir")

    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        copies = []
        for p in targets:
            q = out / p.name
            if not q.exists():
                shutil.copy2(p, q)
            copies.append(q)
        targets = copies

    ok = 0
    for p in targets:
        try:
            st = populate(p, args.seed)
            ok += 1
            print(f"  {p.name[:52]:52s} {st['tables']:3d} tables  "
                  f"+{st.get('added',0):6,d} rows -> {st.get('rows',0):7,d}")
        except Exception as e:
            print(f"  {p.name[:52]:52s} FAILED {type(e).__name__}: {str(e)[:60]}")
    print(f"\npopulated {ok}/{len(targets)}")


if __name__ == "__main__":
    main()
