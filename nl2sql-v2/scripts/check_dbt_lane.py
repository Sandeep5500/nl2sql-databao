#!/usr/bin/env python3
"""End-to-end check of the dbt lane against a real dbt project, no LLM needed.

Builds a Spider2-shaped fixture (including the hazard where profiles.yml points at a
database OUTSIDE the project), stages it, then drives the exact tool sequence an
agent would: list_files, read_file, write_file, run_dbt('build'), run_sql_query,
submit. Asserts the things that are expensive to discover later:

  * staging never writes to the pristine tree, and the fingerprint proves it
  * profiles.yml is rewritten to a database inside the workspace
  * dbt actually builds a model the agent wrote
  * the DuckDB single-writer lock does not break `dbt build` after an inspection
  * write_file enforces its allow-list, read/write cannot escape the project
  * the submission folder is Spider2-shaped

Needs dbt-core + dbt-duckdb (the `dbt` extra); skips the dbt steps if absent.

    uv run --extra dbt python scripts/check_dbt_lane.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl2sql.config import AgentConfig
from nl2sql.dbt_submission import DbtSubmission
from nl2sql.dbt_tools import DbtToolSession
from nl2sql.dbt_workspace import DbtWorkspace

FAILURES = []


def check(label, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        FAILURES.append(f"{label}: got {got!r}, want {want!r}")


def check_true(label, cond, detail=""):
    print(f"{'ok  ' if cond else 'FAIL'} {label}" + (f": {detail}" if detail else ""))
    if not cond:
        FAILURES.append(f"{label}: {detail}")


def build_fixture(tmp: Path) -> tuple[Path, Path]:
    """A dbt project whose source database lives outside the project dir -- the
    arrangement that would otherwise let dbt write into the pristine tree."""
    import duckdb

    shared = tmp / "shared_dbs"
    shared.mkdir(parents=True)
    src_db = shared / "activity.duckdb"
    con = duckdb.connect(str(src_db))
    con.execute("CREATE SCHEMA IF NOT EXISTS main")
    con.execute("CREATE TABLE main.raw_sessions("
                "session_id INTEGER, source VARCHAR, revenue DOUBLE)")
    con.execute("INSERT INTO main.raw_sessions VALUES "
                "(1,'google',10.0),(2,'google',5.0),(3,'direct',2.0),(4,NULL,1.0)")
    con.close()

    proj = tmp / "examples" / "activity001"
    (proj / "models").mkdir(parents=True)
    (proj / "dbt_packages" / "dbt_utils").mkdir(parents=True)
    # a realistic vendored package: dbt refuses to run when dbt_packages/ and
    # packages.yml disagree, which is plan risk #8 in miniature
    (proj / "dbt_packages" / "dbt_utils" / "dbt_project.yml").write_text(
        "name: dbt_utils\nversion: '1.3.0'\nconfig-version: 2\n",
        encoding="utf-8")
    (proj / "packages.yml").write_text(
        "packages:\n  - package: dbt-labs/dbt_utils\n    version: 1.3.0\n",
        encoding="utf-8")
    (proj / "dbt_project.yml").write_text(
        "name: activity\nversion: '1.0'\nprofile: activity\n"
        "model-paths: ['models']\n", encoding="utf-8")
    # absolute path to a db outside the project: the hazard
    (proj / "profiles.yml").write_text(
        "activity:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n"
        f"      path: {src_db.as_posix()}\n      schema: main\n", encoding="utf-8")
    (proj / "models" / "stg_sessions.sql").write_text(
        "select session_id, coalesce(source, 'unknown') as source, revenue\n"
        "from main.raw_sessions\n", encoding="utf-8")
    return proj, src_db


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="nl2sql-dbtcheck-"))
    proj, src_db = build_fixture(tmp)
    scratch = tmp / "scratch"
    pristine_before = sorted(p.relative_to(proj).as_posix()
                             for p in proj.rglob("*") if p.is_file())

    print("== staging ==")
    ws = DbtWorkspace.stage("activity001", proj, scratch, run_tag="check")
    check_true("workspace is outside the pristine tree",
               proj.resolve() not in ws.root.resolve().parents
               and ws.root.resolve() != proj.resolve(), str(ws.root))
    check("profile name parsed", ws.profile_name, "activity")
    check("target parsed", ws.target, "dev")
    check_true("the database was copied INTO the workspace",
               ws.duckdb_path.exists()
               and ws.root.resolve() in ws.duckdb_path.resolve().parents,
               str(ws.duckdb_path))
    prof_text = (ws.root / "profiles.yml").read_text(encoding="utf-8")
    check_true("profiles.yml no longer points outside the workspace",
               src_db.as_posix() not in prof_text.replace("\\", "/"))
    check_true("profiles.yml points at the workspace database",
               ws.duckdb_path.name in prof_text, prof_text.strip().replace("\n", " | "))

    print("\n== tools ==")
    cfg = AgentConfig(max_steps=40)
    s = DbtToolSession(ws=ws, cfg=cfg)
    check("session exposes a dbt toolset",
          [t["function"]["name"] for t in s.tool_schemas()][:3],
          ["list_files", "read_file", "write_file"])
    check_true("system prompt is the dbt one",
               "analytics engineer" in s.system_prompt("do it", cfg, "[ctx]"))
    check("db handle reports the dbt dialect", s.db.dialect, "duckdb")

    listing = s.dispatch("list_files", {})
    check_true("list_files shows the model", "models/stg_sessions.sql" in listing)
    check_true("list_files hides vendored packages", "dbt_packages" not in listing,
               listing.replace("\n", " | "))

    body = s.dispatch("read_file", {"path": "models/stg_sessions.sql"})
    check_true("read_file returns the model body", "raw_sessions" in body)
    check_true("read_file suggests on a typo",
               "Did you mean" in s.dispatch(
                   "read_file", {"path": "models/stg_session.sql"}),
               s.dispatch("read_file", {"path": "models/stg_session.sql"})[:70])
    check_true("read_file cannot escape the project",
               "escapes the project" in s.dispatch(
                   "read_file", {"path": "../../../etc/passwd"}))
    check_true("write_file refuses profiles.yml",
               "not writable" in s.dispatch(
                   "write_file", {"path": "profiles.yml", "content": "x"}))
    check_true("write_file refuses an escape",
               "ERROR" in s.dispatch(
                   "write_file", {"path": "../evil.sql", "content": "x"}))

    out = s.dispatch("write_file", {
        "path": "models/revenue_by_source.sql",
        "content": ("select source, sum(revenue) as total_revenue\n"
                    "from {{ ref('stg_sessions') }}\n"
                    "group by 1\norder by 1\n")})
    check_true("write_file returns a diff", "+++ b/models/revenue_by_source.sql" in out,
               out.splitlines()[0])
    check("write_file counted", s.write_calls, 1)

    from nl2sql.dbt_tools import dbt_executable
    if dbt_executable() is None:
        print("\n[dbt not on PATH - skipping the build/query/submit checks]")
    else:
        print("\n== dbt ==")
        # open an inspection connection FIRST: this is what used to deadlock the
        # build with a DuckDB lock error that looks like a broken model
        try:
            s.dispatch("list_tables", {})
        except Exception:
            pass
        res = s.dispatch("run_dbt", {"command": "build"})
        check_true("dbt build succeeds with a reader previously open",
                   "exit_code=0" in res, res.splitlines()[0])
        if "exit_code=0" not in res:
            print("---- dbt output ----")
            print(res)
            print("--------------------")
        check_true("dbt build is condensed, not 100 lines",
                   len(res.splitlines()) < 40, f"{len(res.splitlines())} lines")
        check("build success recorded", s.dbt_build_ok, True)
        check_true("an unknown dbt command is refused",
                   "not allowed" in s.dispatch("run_dbt", {"command": "destroy"}))

        print("\n== query + submit ==")
        tables = s.dispatch("list_tables", {})
        check_true("the agent's model is materialised",
                   "revenue_by_source" in tables, tables.replace("\n", ", "))
        desc = s.dispatch("describe_table", {"table": "revenue_by_source"})
        check_true("describe_table works on the built model",
                   "total_revenue" in desc)
        q = s.dispatch("run_sql_query",
                       {"sql": "select source, total_revenue from revenue_by_source "
                               "order by source"})
        check_true("run_sql_query returns a query_id", "query_id='q1'" in q,
                   q.replace("\n", " | ")[:90])
        check_true("NULL source was coalesced by the existing model",
                   "unknown" in q, q.replace("\n", " | "))

        sub_dir = tmp / "submission"
        # a gold config shaped exactly like spider2-dbt/evaluation_suite/gold:
        # one spider2_eval.jsonl, entries {instance_id, evaluation:{func,parameters}}
        gold_dir = tmp / "gold"
        (gold_dir / "activity001").mkdir(parents=True)
        (gold_dir / "spider2_eval.jsonl").write_text(json.dumps({
            "instance_id": "activity001",
            "evaluation": {"func": "duckdb_match", "parameters": {
                "gold": "activity.duckdb",
                "condition_tabs": ["revenue_by_source"],
                "condition_cols": [[0, 1]], "ignore_orders": [True]}}}) + "\n",
            encoding="utf-8")
        sub = DbtSubmission(sub_dir, gold_dir=gold_dir)
        check("gold is read from spider2_eval.jsonl", len(sub.gold), 1)

        sql, df = s.get_submission("q1")
        row = sub.record("activity001", df, description=sql,
                         duckdb_path=ws.duckdb_path)
        # duckdb_match means the deliverable is the project DATABASE, not a CSV
        check("duckdb_match submits a database", row["answer_type"], "file")
        check("the artifact is named after the gold db", row["answer_or_path"],
              "activity.duckdb")
        check_true("the metadata field is answer_or_path", "answer" not in row)
        check_true("answer_or_path is a bare filename (they join the instance id)",
                   "/" not in row["answer_or_path"])
        check_true("the database landed in the instance dir",
                   (sub_dir / "activity001/activity.duckdb").exists())
        meta = [json.loads(l) for l in
                (sub_dir / "results_metadata.jsonl").read_text(
                    encoding="utf-8").splitlines() if l.strip()]
        check("metadata has one line per instance", len(meta), 1)

        # the handed-over database must contain the table the gold actually checks
        import duckdb as _duckdb
        con = _duckdb.connect(str(sub_dir / "activity001/activity.duckdb"),
                              read_only=True)
        tabs = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        check_true("it contains the gold's condition_tabs table",
                   "revenue_by_source" in tabs, str(tabs))

        # an instance where dbt never built still yields a well-formed line
        row2 = sub.record("never_built001", None, duckdb_path=None)
        check("a failed instance still yields a metadata line",
              row2["answer_type"], "answer")

    print("\n== isolation ==")
    ws.close_duckdb()
    pristine_after = sorted(p.relative_to(proj).as_posix()
                            for p in proj.rglob("*") if p.is_file())
    check("pristine file list unchanged", pristine_after, pristine_before)
    try:
        ws.assert_source_untouched()
        print("ok   fingerprint assertion passes")
    except RuntimeError as e:
        FAILURES.append(f"fingerprint changed: {e}")
        print(f"FAIL fingerprint changed: {e}")

    # and prove the assertion actually fires when the tree is touched
    (proj / "models" / "sneaky.sql").write_text("select 1\n", encoding="utf-8")
    try:
        ws.assert_source_untouched()
        FAILURES.append("fingerprint assertion did NOT fire on a real change")
        print("FAIL fingerprint assertion fires on tampering")
    except RuntimeError:
        print("ok   fingerprint assertion fires on tampering")

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print("  " + f)
        return 1
    print("all dbt lane checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
