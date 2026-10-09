#!/usr/bin/env python3
"""Guard the published baseline: the local SQLite lane through the real agent loop.

check_prompt_parity.py pins the system prompt's text. This pins the rest of what the
SQLite lane shows the model -- the advertised tool list, the rendered database name,
and that an episode still submits a correct frame -- because the snow/dbt work added
`hasattr`-based hooks to run_episode and the whole point is that this lane does not
take them.

    uv run python scripts/check_sqlite_episode.py
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

SCRIPT = [
    ("list_tables", {}),
    ("describe_table", {"table": "t"}),
    ("get_column_values", {"table": "t", "column": "label"}),
    ("run_sql_query", {"sql": "SELECT label, SUM(v) s FROM t GROUP BY 1 ORDER BY 1"}),
    ("submit_result", {"query_id": "q1", "result_description": "sums per label"}),
]

FAILURES = []


def check(label, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        FAILURES.append(f"{label}: got {got!r}, want {want!r}")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="nl2sql-sqlep-"))
    dbp = tmp / "mini.sqlite"
    con = sqlite3.connect(dbp)
    con.execute("CREATE TABLE t(label TEXT, v REAL)")
    con.executemany("INSERT INTO t VALUES (?,?)",
                    [("a", 1.0), ("b", 2.0), ("a", 3.0)])
    con.commit()
    con.close()

    db = Database(dbp)
    cfg = AgentConfig(max_steps=10)
    session = ToolSession(db=db, cfg=cfg)

    with scripted_llm(SCRIPT) as (base_url, cap):
        llm = LLMConfig(base_url=base_url, model="stub", api_key="stub")
        result = run_episode("Sum v per label.", session, llm, cfg, None,
                             extra_context="")

    check("episode submitted", result.status, "submitted")
    check("result shape", list(result.pred_df.shape), [2, 2])
    check("values are correct", result.pred_df.iloc[:, 1].tolist(), [4.0, 2.0])
    check("the SQL toolset is advertised",
          sorted(t for t in cap.tools
                 if t in ("run_sql_query", "describe_table", "find_value",
                          "get_column_values", "list_tables", "submit_result")),
          ["describe_table", "find_value", "get_column_values", "list_tables",
           "run_sql_query", "submit_result"])
    check("no dbt tools leak into this lane",
          [t for t in cap.tools if t in ("run_dbt", "write_file", "read_file",
                                         "list_files")], [])
    check("the SQLite/DuckDB prompt is used",
          "DuckDB syntax, SQLite data attached" in cap.system, True)
    check("the dbt prompt is NOT used", "analytics engineer" in cap.system, False)
    check("db_name still renders from the file stem", "Database: mini" in cap.system,
          True)
    db.close()

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print("  " + f)
        print("the published SQLite baseline is no longer reproducible")
        return 1
    print("SQLite lane is unchanged through the real loop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
