#!/usr/bin/env python3
"""Find candidate training databases that hold the same data as a Spider 2.0-Lite
local database, so judge training data never comes from a test database under
another name (BIRD's movie_3 is Sakila, soccer_2016 is IPL).

Every database is fingerprinted once: its normalised table and column names, a hash
of up to --rows rows per table (cells normalised and sorted, so renamed or reordered
columns still match) and a hash of every text value of 6+ characters in those rows.
Only cells that are mostly letters count (rows need one): dates, codes and number
pairs are shared by unrelated databases.
Each (candidate, Spider2 database) pair is then scored on
  col_jaccard     shared column names / all column names
  table_matches   candidate tables (3+ columns) whose columns match a Spider2 table
                  with Jaccard >= 0.6
  shared_rows     identical rows
  shared_values   identical long text values, and their share of the smaller set
and flagged for review when any is high. Flags are for a person to decide: public
lists (countries, film titles) can match without the databases being the same.

Usage (from nl2sql-v2/, with the Spider2 local DBs present):
    uv run python scripts/check_db_overlap.py --candidates <dir searched for *.sqlite> \\
        --output ../results/judge_data/db_overlap.csv --cache-dir ../results/judge_data/fp
"""

import argparse
import csv
import hashlib
import pickle
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl2sql.config import SQLITE_DIR

NUMBER = re.compile(r"-?\d+(\.\d+)?")


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def norm_name(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def norm_cell(v) -> str:
    """One spelling per value: numbers stored as text match numbers, case and
    surrounding spaces are ignored."""
    if v is None:
        return ""
    if isinstance(v, (bytes, bytearray)):
        v = bytes(v).decode("utf-8", "replace")
    if isinstance(v, str):
        v = v.strip().lower()
        if not NUMBER.fullmatch(v):
            return v
        v = float(v)
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return f"{v:.6g}" if isinstance(v, float) else str(v)


def h64(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")


def wordy(c: str, n: int) -> bool:
    """At least n characters, mostly not digits: names and titles, not dates, codes
    or numbers, which any two databases covering the same years share."""
    return len(c) >= n and sum(ch.isdigit() for ch in c) < len(c) / 2


def fingerprint(path: Path, rows: int, budget_s: float) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    fp = {"tables": {}, "rows": set(), "values": set(), "n_rows_read": 0}
    names = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    for t in names:
        try:
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({q(t)})")]
        except sqlite3.Error:
            continue
        fp["tables"][norm_name(t)] = sorted({norm_name(c) for c in cols})
        deadline = time.time() + budget_s
        con.set_progress_handler(lambda: time.time() > deadline, 10_000)
        try:
            for row in con.execute(f"SELECT * FROM {q(t)} LIMIT {rows}"):
                cells = [norm_cell(v) for v in row]
                fp["n_rows_read"] += 1
                # rows of numbers and dates alone (link tables, calendars) match anywhere
                if sum(1 for c in cells if c) >= 2 and any(wordy(c, 4) for c in cells):
                    fp["rows"].add(h64("\x1f".join(sorted(cells))))
                for c in cells:
                    if wordy(c, 6):
                        fp["values"].add(h64(c))
        except sqlite3.Error:
            pass  # stopped by the time budget (or unreadable): keep what was read
        finally:
            con.set_progress_handler(None, 0)
    con.close()
    return fp


def cached_fingerprint(path: Path, cache_dir: Path | None, rows: int, budget_s: float) -> dict:
    if cache_dir is None:
        return fingerprint(path, rows, budget_s)
    key = f"{path.stem}_{hashlib.md5(str(path.resolve()).encode()).hexdigest()[:8]}_{rows}_v2.pkl"
    cp = cache_dir / key
    if cp.exists():
        return pickle.loads(cp.read_bytes())
    fp = fingerprint(path, rows, budget_s)
    cp.write_bytes(pickle.dumps(fp))
    return fp


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def compare(c: dict, r: dict) -> dict:
    ccols = {col for cols in c["tables"].values() for col in cols}
    rcols = {col for cols in r["tables"].values() for col in cols}
    matches = [ct for ct, cols in c["tables"].items() if len(cols) >= 3 and any(
        jaccard(set(cols), set(rc)) >= 0.6 for rc in r["tables"].values())]
    sv = len(c["values"] & r["values"])
    return {"col_jaccard": round(jaccard(ccols, rcols), 3),
            "table_matches": len(matches), "matched_tables": " ".join(sorted(matches)),
            "shared_rows": len(c["rows"] & r["rows"]),
            "shared_values": sv,
            "value_share": round(sv / max(min(len(c["values"]), len(r["values"])), 1), 3)}


def flagged(m: dict) -> bool:
    return (m["col_jaccard"] >= 0.4 or m["table_matches"] >= 2 or m["shared_rows"] >= 50
            or (m["shared_values"] >= 500 and m["value_share"] >= 0.2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True, help="directory searched recursively for *.sqlite")
    ap.add_argument("--reference", default=str(SQLITE_DIR), help="Spider2 local DBs (default: config)")
    ap.add_argument("--output", required=True)
    ap.add_argument("--cache-dir")
    ap.add_argument("--rows", type=int, default=20_000, help="rows read per table")
    ap.add_argument("--budget-s", type=float, default=60.0, help="time limit per table")
    args = ap.parse_args()
    cache = Path(args.cache_dir) if args.cache_dir else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)

    refs = sorted(p for p in Path(args.reference).glob("*.sqlite") if p.stat().st_size)
    cands = sorted(p for p in Path(args.candidates).rglob("*.sqlite") if p.stat().st_size)
    if not refs or not cands:
        raise SystemExit(f"{len(refs)} reference and {len(cands)} candidate databases found")
    print(f"{len(cands)} candidates x {len(refs)} Spider2 databases", flush=True)
    ref_fp = {}
    for p in refs:
        t0 = time.time()
        ref_fp[p.stem] = cached_fingerprint(p, cache, args.rows, args.budget_s)
        print(f"  ref {p.stem}: {len(ref_fp[p.stem]['tables'])} tables, "
              f"{len(ref_fp[p.stem]['rows'])} rows hashed ({time.time() - t0:.0f}s)", flush=True)

    out_rows, n_flag = [], 0
    for p in cands:
        t0 = time.time()
        fp = cached_fingerprint(p, cache, args.rows, args.budget_s)
        scored = [{"candidate": p.stem, "spider2_db": ref, **compare(fp, rfp)}
                  for ref, rfp in ref_fp.items()]
        for m in scored:
            m["flag"] = int(flagged(m))
        out_rows += scored
        hits = [m for m in scored if m["flag"]]
        n_flag += bool(hits)
        best = max(scored, key=lambda m: (m["flag"], m["shared_rows"], m["col_jaccard"]))
        print(f"{p.stem}: {'FLAG ' + ','.join(m['spider2_db'] for m in hits) if hits else 'ok'}"
              f"  (closest {best['spider2_db']}: cols {best['col_jaccard']}, tables "
              f"{best['table_matches']}, rows {best['shared_rows']}, values {best['shared_values']}"
              f"/{best['value_share']}; {time.time() - t0:.0f}s)", flush=True)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out_rows.sort(key=lambda m: (-m["flag"], -m["shared_rows"], -m["col_jaccard"]))
    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n{n_flag} of {len(cands)} candidates flagged -> {args.output}")


if __name__ == "__main__":
    main()
