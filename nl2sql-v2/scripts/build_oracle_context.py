#!/usr/bin/env python3
"""Parse gold SQL for the local questions that have it and extract the tables
and columns each answer uses. Output feeds ablation arm C (--context-mode oracle).

Usage (from nl2sql-v2/):
    uv run python scripts/build_oracle_context.py   # writes oracle_context.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sqlglot
from sqlglot import exp

from nl2sql.config import GOLD_SQL_DIR, QUESTIONS_FILE

OUT_PATH = Path(__file__).resolve().parents[1] / "oracle_context.json"


def extract(sql: str) -> dict | None:
    for dialect in ("sqlite", "duckdb", None):
        try:
            statements = sqlglot.parse(sql, read=dialect)
            break
        except Exception:
            statements = None
    if not statements:
        return None
    tables, columns = set(), set()
    ctes = set()
    for st in statements:
        if st is None:
            continue
        for cte in st.find_all(exp.CTE):
            ctes.add(cte.alias_or_name.lower())
        for t in st.find_all(exp.Table):
            if t.name and t.name.lower() not in ctes:
                tables.add(t.name)
        for c in st.find_all(exp.Column):
            if c.name:
                columns.add(c.name)
    return {"tables": sorted(tables), "columns": sorted(columns)}


def main():
    local_ids = set()
    with open(QUESTIONS_FILE) as f:
        for line in f:
            q = json.loads(line)
            if q["instance_id"].startswith("local"):
                local_ids.add(q["instance_id"])

    oracle, failed = {}, []
    for sql_file in sorted(GOLD_SQL_DIR.glob("local*.sql")):
        iid = sql_file.stem
        if iid not in local_ids:
            continue
        info = extract(sql_file.read_text())
        if info is None or not info["tables"]:
            failed.append(iid)
            continue
        oracle[iid] = info

    OUT_PATH.write_text(json.dumps(oracle, indent=2))
    print(f"extracted oracle context for {len(oracle)} instances -> {OUT_PATH}")
    if failed:
        print(f"failed to parse ({len(failed)}): {failed}")
    for iid, info in list(oracle.items())[:3]:
        print(f"  {iid}: tables={info['tables']} columns={info['columns'][:8]}...")


if __name__ == "__main__":
    main()
