#!/usr/bin/env python3
"""The submit-time row-count check (run_benchmark.py --rubric-row-check), no GPU.

Pins four properties through the real agent loop:
  - off (expected_rows=None) the loop is unchanged: the first submission is final;
  - a mismatched count is bounced exactly once, and a re-run is what gets submitted;
  - resubmitting the same query_id after the bounce keeps it (never rewritten);
  - a matching count is not bounced.

    uv run python scripts/check_row_check.py
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _stub_llm import scripted_llm                     # noqa: E402
from nl2sql.agent import run_episode                   # noqa: E402
from nl2sql.config import AgentConfig, LLMConfig       # noqa: E402
from nl2sql.db import Database                         # noqa: E402
from nl2sql.tools import ToolSession                   # noqa: E402

TOP_ALL = "SELECT label, SUM(v) s FROM t GROUP BY 1 ORDER BY 2 DESC"
TOP_1 = TOP_ALL + " LIMIT 1"
FAILURES = []


def check(label, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        FAILURES.append(f"{label}: got {got!r}, want {want!r}")


def episode(dbp, script, expected_rows):
    db = Database(dbp)
    cfg = AgentConfig(max_steps=10)
    try:
        with scripted_llm(script) as (base_url, _):
            llm = LLMConfig(base_url=base_url, model="stub", api_key="stub")
            r = run_episode("Which label has the largest sum?", ToolSession(db=db, cfg=cfg),
                            llm, cfg, None, extra_context="", expected_rows=expected_rows)
    finally:
        db.close()
    bounces = [s["row_check"] for s in r.trace if "row_check" in s]
    return r, bounces


def main():
    tmp = Path(tempfile.mkdtemp(prefix="nl2sql-rowcheck-"))
    dbp = tmp / "mini.sqlite"
    con = sqlite3.connect(dbp)
    con.execute("CREATE TABLE t(label TEXT, v REAL)")
    con.executemany("INSERT INTO t VALUES (?,?)", [("a", 1.0), ("b", 2.0), ("a", 3.0)])
    con.commit()
    con.close()

    run_all = ("run_sql_query", {"sql": TOP_ALL})
    sub = lambda q: ("submit_result", {"query_id": q, "result_description": "x"})

    r, b = episode(dbp, [run_all, sub("q1")], None)
    check("off: first submission is final", (r.status, len(r.pred_df), r.steps), ("submitted", 2, 2))
    check("off: no bounce recorded", b, [])

    r, b = episode(dbp, [run_all, sub("q1"), ("run_sql_query", {"sql": TOP_1}), sub("q2")], 1)
    check("mismatch: bounced once", b, [{"query_id": "q1", "rows": 2, "expected": 1}])
    check("mismatch: the re-run is submitted", (r.status, len(r.pred_df), r.sql), ("submitted", 1, TOP_1))

    r, b = episode(dbp, [run_all, sub("q1"), sub("q1")], 1)
    check("override: one bounce, then kept", (len(b), r.status, len(r.pred_df)), (1, "submitted", 2))

    r, b = episode(dbp, [run_all, sub("q1")], 2)
    check("match: not bounced", (b, r.status, r.steps), ([], "submitted", 2))

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print("  " + f)
        return 1
    print("row-count check behaves as specified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
