#!/usr/bin/env python3
"""Small helpers for comparing traces of the same question across runs.

Usage (from nl2sql-v2/):
    uv run python scripts/trace_tools.py final <run_dir_name> <instance_id>
        print the question, final SQL, status, and its score against gold
    uv run python scripts/trace_tools.py queries <run_dir_name> <instance_id>
        re-run every run_sql_query in the trace and mark which ones match gold
    uv run python scripts/trace_tools.py exec <instance_id> <sql_file>
        run arbitrary SQL against the question's database and score it
<run_dir_name> is a directory under logs/traces/, e.g. q36s_pass4_k1.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl2sql.config import QUESTIONS_FILE, REPO_ROOT, SQLITE_DIR
from nl2sql.db import Database
from nl2sql.eval import load_eval_standards, score_against_gold

TRACES = REPO_ROOT / "logs" / "traces"


def _db_for(iid: str) -> Database:
    for line in open(QUESTIONS_FILE):
        q = json.loads(line)
        if q["instance_id"] == iid:
            return Database(SQLITE_DIR / f"{q['db']}.sqlite")
    raise SystemExit(f"unknown instance {iid}")


def _run_and_score(db, iid, sql, std, show=6):
    try:
        df, _ = db.query_preview(sql, 1, 5000, timeout_s=90)
    except Exception as e:
        return f"ERROR: {str(e)[:200]}"
    score, detail = score_against_gold(df, iid, std)
    return (f"score={score} ({detail}) shape={df.shape}\n"
            f"{df.head(show).to_string(index=False)}")


def main():
    cmd = sys.argv[1]
    std = load_eval_standards()
    if cmd == "final":
        run, iid = sys.argv[2], sys.argv[3]
        t = json.load(open(TRACES / run / f"{iid}.json"))
        db = _db_for(iid)
        print(f"QUESTION: {t['question']}\nSTATUS: {t['status']}\nFINAL SQL:\n{t['sql']}\n")
        print(_run_and_score(db, iid, t["sql"] or "SELECT 1", std))
        db.close()
    elif cmd == "queries":
        run, iid = sys.argv[2], sys.argv[3]
        t = json.load(open(TRACES / run / f"{iid}.json"))
        db = _db_for(iid)
        n = 0
        for e in t["trace"]:
            if e.get("tool") == "run_sql_query":
                n += 1
                res = _run_and_score(db, iid, e["args"].get("sql", ""), std, show=0)
                print(f"q{n} step {e['step']}: {res.splitlines()[0]}")
        db.close()
    elif cmd == "exec":
        iid, sql = sys.argv[2], Path(sys.argv[3]).read_text()
        db = _db_for(iid)
        print(_run_and_score(db, iid, sql, std, show=12))
        db.close()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
