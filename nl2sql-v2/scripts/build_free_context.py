#!/usr/bin/env python3
"""Build the two ablation arms that need no gold SQL and no teacher model.

Both derive their hint from the graded artifact (the gold exec CSV), so they
cover far more than the 24 gold-SQL questions and cannot be contaminated by
anything a model memorised.

  contract_context.json  — the output contract: exactly which columns the answer
                           must return (narrowed by condition_cols when present)
                           and how many rows. Available for all 135.
  sweep_context.json     — schema linkage recovered by sweeping the gold answer's
                           text values back to the column that stores them. The
                           table owning a matched column must be one the correct
                           query touched. Only works where the answer contains
                           literals; purely numeric answers are skipped.

Usage (from nl2sql-v2/):
    uv run python scripts/build_free_context.py            # both files
    uv run python scripts/build_free_context.py --only sweep
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from nl2sql.config import (EVAL_JSONL, GOLD_EXEC_DIR, QUESTIONS_FILE,
                           SQLITE_DIR)
from nl2sql.db import Database

OUT_DIR = Path(__file__).resolve().parents[1]
TEXT_TYPES = ("CHAR", "TEXT", "STRING", "VARCHAR", "CLOB")
# a gold value must be distinctive enough that finding it proves anything
MIN_VALUE_LEN = 2
MAX_PROBE_VALUES = 6        # distinct values probed per gold column
MAX_COLUMNS_PER_DB = 400    # safety cap on the scan


def local_questions() -> dict:
    out = {}
    with open(QUESTIONS_FILE) as f:
        for line in f:
            q = json.loads(line)
            if q["instance_id"].startswith("local"):
                out[q["instance_id"]] = q["db"]
    return out


def gold_files(iid: str) -> list[Path]:
    pat = re.compile(rf"^{re.escape(iid)}(_[a-z])?\.csv$")
    return sorted(GOLD_EXEC_DIR / f for f in os.listdir(GOLD_EXEC_DIR)
                  if pat.match(f))


def load_standards() -> dict:
    return {json.loads(l)["instance_id"]: json.loads(l) for l in open(EVAL_JSONL)}


# ── arm 1: output contract ────────────────────────────────────────────────
def build_contract(ids: dict, standards: dict) -> dict:
    out = {}
    for iid in ids:
        files = gold_files(iid)
        if not files:
            continue
        try:
            df = pd.read_csv(files[0])
        except Exception:
            continue
        cols = list(df.columns)
        cc = standards.get(iid, {}).get("condition_cols")
        # a flat list of indices means only those gold columns are graded
        if isinstance(cc, list) and cc and not isinstance(cc[0], list):
            try:
                cols = [df.columns[i] for i in cc]
            except IndexError:
                pass
        out[iid] = {
            "columns": [str(c) for c in cols],
            "rows": int(df.shape[0]),
            "variants": len(files),
        }
    return out


# ── arm 2: value-sweep linkage ────────────────────────────────────────────
def probe_values(series: pd.Series) -> list[str]:
    """Distinct, distinctive string values worth searching the database for."""
    vals = []
    for v in series.dropna().unique():
        if not isinstance(v, str):
            continue
        s = v.strip()
        # a bare number in a text column proves nothing: it is computed, not stored
        if len(s) < MIN_VALUE_LEN or s.replace(".", "", 1).replace("-", "", 1).isdigit():
            continue
        vals.append(s)
        if len(vals) >= MAX_PROBE_VALUES:
            break
    return vals


def text_columns(db: Database) -> list[tuple[str, str]]:
    cols = []
    for t in db.list_tables():
        try:
            for c, dtype, _ in db._columns(t):
                if any(k in (dtype or "").upper() for k in TEXT_TYPES) or not dtype:
                    cols.append((t, c))
        except ValueError:
            continue
        if len(cols) > MAX_COLUMNS_PER_DB:
            break
    return cols[:MAX_COLUMNS_PER_DB]


def locate(db: Database, cols: list[tuple[str, str]], values: list[str]) -> list[tuple[str, str, int]]:
    """Columns storing these values, best first. One query per column: count how
    many of the probe values appear in it (exact, then case-insensitive)."""
    if not values:
        return []
    placeholders = ", ".join("?" for _ in values)
    lowered = [v.lower() for v in values]
    hits = []
    for t, c in cols:
        q = db._q(t), db._q(c)
        try:
            n = db.con.execute(
                f"SELECT COUNT(DISTINCT CAST({q[1]} AS VARCHAR)) FROM {q[0]} "
                f"WHERE CAST({q[1]} AS VARCHAR) IN ({placeholders})", values
            ).fetchone()[0]
            if not n:
                n = db.con.execute(
                    f"SELECT COUNT(DISTINCT LOWER(CAST({q[1]} AS VARCHAR))) FROM {q[0]} "
                    f"WHERE LOWER(CAST({q[1]} AS VARCHAR)) IN ({placeholders})", lowered
                ).fetchone()[0]
        except Exception:
            continue
        if n:
            hits.append((t, c, int(n)))
    hits.sort(key=lambda h: -h[2])
    return hits


def build_sweep(ids: dict, verbose: bool = True) -> tuple[dict, dict]:
    by_db = defaultdict(list)
    for iid, db_name in ids.items():
        by_db[db_name].append(iid)

    out, skipped = {}, {}
    for db_name in sorted(by_db):
        path = SQLITE_DIR / f"{db_name}.sqlite"
        if not path.exists():
            for iid in by_db[db_name]:
                skipped[iid] = "db_missing"
            continue
        db = Database(path)
        cols = text_columns(db)
        for iid in sorted(by_db[db_name]):
            files = gold_files(iid)
            if not files:
                skipped[iid] = "no_gold_csv"
                continue
            try:
                gdf = pd.read_csv(files[0])
            except Exception:
                skipped[iid] = "gold_unreadable"
                continue
            tables, matched, probed = {}, [], 0
            for gc in gdf.columns:
                vals = probe_values(gdf[gc])
                if not vals:
                    continue
                probed += 1
                for t, c, n in locate(db, cols, vals)[:3]:
                    # require a majority of the probe values to live in the column
                    if n * 2 >= len(vals):
                        tables[t] = tables.get(t, 0) + n
                        matched.append({"gold_column": str(gc), "table": t,
                                        "column": c, "values_found": n,
                                        "values_probed": len(vals)})
            if not tables:
                skipped[iid] = "no_literal_match" if probed else "numeric_only"
                continue
            out[iid] = {
                "tables": sorted(tables, key=lambda t: -tables[t]),
                "columns": sorted({m["column"] for m in matched}),
                "evidence": matched,
            }
            if verbose:
                print(f"  {iid:10s} {db_name:28s} tables={out[iid]['tables']}",
                      flush=True)
        db.close()
    return out, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["contract", "sweep"])
    args = ap.parse_args()

    ids = local_questions()
    standards = load_standards()
    print(f"local questions: {len(ids)}")

    if args.only != "sweep":
        contract = build_contract(ids, standards)
        (OUT_DIR / "contract_context.json").write_text(json.dumps(contract, indent=2))
        print(f"contract_context.json: {len(contract)}/{len(ids)} instances")

    if args.only != "contract":
        print("sweeping gold answer values back to their source columns ...")
        sweep, skipped = build_sweep(ids)
        (OUT_DIR / "sweep_context.json").write_text(json.dumps(sweep, indent=2))
        print(f"\nsweep_context.json: {len(sweep)}/{len(ids)} instances")
        reasons = defaultdict(int)
        for r in skipped.values():
            reasons[r] += 1
        for r, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"  skipped {n:3d}: {r}")


if __name__ == "__main__":
    main()
