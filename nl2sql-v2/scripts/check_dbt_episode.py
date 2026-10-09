#!/usr/bin/env python3
"""Drive the real agent.run_episode over a dbt project, against a stub LLM.

check_dbt_lane.py exercises the tools directly; this exercises the loop -- the
tool_schemas hook, the dbt system prompt, tool dispatch and the submit path -- so the
dbt lane is verified end to end with no GPU and no credentials. The stub serves a
scripted sequence of tool calls over the OpenAI chat-completions API.

    uv run --extra dbt python scripts/check_dbt_episode.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql.agent import run_episode                      # noqa: E402
from nl2sql.config import AgentConfig, LLMConfig          # noqa: E402
from nl2sql.dbt_submission import DbtSubmission           # noqa: E402
from nl2sql.dbt_tools import DbtToolSession, dbt_executable  # noqa: E402
from nl2sql.dbt_workspace import DbtWorkspace             # noqa: E402
from _stub_llm import scripted_llm                        # noqa: E402
from check_dbt_lane import build_fixture                  # noqa: E402

# what a competent agent would do, in order
SCRIPT = [
    ("list_files", {}),
    ("read_file", {"path": "models/stg_sessions.sql"}),
    ("write_file", {"path": "models/revenue_by_source.sql",
                    "content": "select source, sum(revenue) as total_revenue\n"
                               "from {{ ref('stg_sessions') }}\n"
                               "group by 1\norder by 1\n"}),
    ("run_dbt", {"command": "build"}),
    ("run_sql_query", {"sql": "select source, total_revenue from revenue_by_source "
                              "order by source"}),
    ("submit_result", {"query_id": "q1",
                       "result_description": "revenue per traffic source"}),
]

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


def main():
    if dbt_executable() is None:
        print("dbt is not installed; run with --extra dbt")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="nl2sql-dbtep-"))
    proj, _ = build_fixture(tmp)
    ws = DbtWorkspace.stage("activity001", proj, tmp / "scratch", run_tag="episode")
    cfg = AgentConfig(max_steps=12)
    session = DbtToolSession(ws=ws, cfg=cfg)
    print("== running a real episode against the stub ==")
    with scripted_llm(SCRIPT) as (base_url, cap):
        llm = LLMConfig(base_url=base_url, model="stub", api_key="stub")
        result = run_episode("Show revenue per traffic source.", session, llm, cfg,
                             None, extra_context=ws.project_overview())

    check("the episode submitted", result.status, "submitted")
    check_true("a result frame came back", result.pred_df is not None)
    if result.pred_df is not None:
        check("submitted frame shape", list(result.pred_df.shape), [3, 2])
        check("rows are the aggregated sources",
              sorted(result.pred_df.iloc[:, 0].tolist()),
              ["direct", "google", "unknown"])
    check_true("the submitted SQL is the agent's query",
               "revenue_by_source" in (result.sql or ""), result.sql or "")

    print("\n== the loop used the dbt toolset and prompt ==")
    check_true("run_episode took the dbt toolset via tool_schemas",
               "run_dbt" in cap.tools and "search_context" not in cap.tools,
               str(cap.tools))
    check_true("run_episode took the dbt system prompt",
               "analytics engineer" in cap.system)
    check_true("the project overview reached the prompt",
               "models/stg_sessions.sql" in cap.system)
    check_true("the DuckDB SQL rules reached the prompt",
               "TRY_CAST" in cap.system)
    check("dbt was invoked once", session.dbt_calls, 1)
    check("one model was written", session.write_calls, 1)
    check("the build was recorded as successful", session.dbt_build_ok, True)
    check_true("every scripted tool ran",
               len(result.trace) >= len(SCRIPT) - 1,
               f"{len(result.trace)} trace entries")

    print("\n== submission ==")
    sub = DbtSubmission(tmp / "submission")
    row = sub.record("activity001", result.pred_df, description=result.sql or "",
                     duckdb_path=ws.duckdb_path)
    # every scored spider2-dbt instance is duckdb_match, so the artifact is the
    # project database the agent's dbt run produced, not a CSV of its query
    check("the project database is the artifact", row["answer_type"], "file")
    check("default artifact name", row["answer_or_path"], "result.duckdb")
    check_true("the database was copied into the submission",
               (tmp / "submission/activity001/result.duckdb").exists())

    ws.close_duckdb()
    ws.assert_source_untouched()
    print("ok   pristine project untouched")

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print("  " + f)
        return 1
    print("dbt episode runs end to end through agent.run_episode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
