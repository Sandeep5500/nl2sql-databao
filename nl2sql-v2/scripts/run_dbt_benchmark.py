#!/usr/bin/env python3
"""Run the Spider 2.0-DBT lane: 69 dbt projects the agent must complete.

Reuses agent.run_episode unchanged -- the loop, memory compaction, the trace format
and the step-cap fallback all transfer, because the episode still ends in
submit_result(query_id). What differs is the toolset (file editing + dbt instead of
warehouse SQL) and the scoring, which is Spider2's own evaluator over a submission
folder rather than our CSV comparison.

    uv run python scripts/run_dbt_benchmark.py --instances activity001 --max-steps 40
    uv run python scripts/run_dbt_benchmark.py --smallest 3 --max-steps 40
    uv run python scripts/run_dbt_benchmark.py --resume \
        --submission ../results/dbt_run --trace-dir ../logs/traces/dbt_run
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import OpenAI

from nl2sql.agent import run_episode
from nl2sql.config import (AgentConfig, DATA_SOURCES, DBT_EVAL_SUITE,
                           DBT_EXAMPLES_DIR, LLMConfig, SCRATCH_DIR)
from nl2sql.dbt_submission import (DbtSubmission, gold_db_name,
                                   load_gold_config, resolve_gold_db)
from nl2sql.dbt_tools import DbtToolSession
from nl2sql.dbt_workspace import DbtWorkspace
# the endpoint resolution, outage waiting and infra-error classification are the
# same problems here as on the SQL lanes, so reuse them rather than re-solving
from run_benchmark import (is_infra_error, load_questions, read_endpoint,
                           wait_for_services)

FIELDNAMES = ["instance_id", "db", "score", "score_detail", "status", "steps",
              "critic_rounds", "search_calls", "draft_calls", "wall_seconds",
              "dbt_calls", "write_calls", "dbt_build_ok", "sql"]


def project_size(instance_id: str) -> int:
    d = DBT_EXAMPLES_DIR / instance_id
    if not d.is_dir():
        return 1 << 60
    return sum(p.stat().st_size for p in d.rglob("*")
               if p.is_file() and "dbt_packages" not in p.parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint")
    ap.add_argument("--model", default="Qwen/Qwen3.5-9B")
    ap.add_argument("--instances", help="comma-separated instance_ids")
    ap.add_argument("--smallest", type=int, metavar="N",
                    help="the N smallest projects -- the gate set: it tests the "
                         "plumbing, not multi-file reasoning")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--max-steps", type=int, default=40,
                    help="file edits and dbt runs burn steps faster than SQL")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--submission", default="../results/dbt_submission",
                    help="submission folder (Spider2 format)")
    ap.add_argument("--output", default="",
                    help="per-instance CSV; defaults to <submission>/run.csv")
    ap.add_argument("--trace-dir")
    ap.add_argument("--run-tag", default="")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--only-scoreable", action="store_true",
                    help="skip instances whose gold database is absent from "
                         "their archive: they cost a full episode and can only "
                         "ever score 0 locally")
    ap.add_argument("--keep-workspace", action="store_true",
                    help="leave the staged project on disk for inspection")
    args = ap.parse_args()

    src = DATA_SOURCES["spider2_dbt"]
    instances = set(args.instances.split(",")) if args.instances else None
    questions = load_questions([src], instances=instances)
    if not questions:
        raise SystemExit(f"no dbt instances found in {src.questions_file} "
                         f"(run: git submodule update --init Spider2)")
    if args.only_scoreable:
        gold = load_gold_config(DBT_EVAL_SUITE / "gold")
        keep, dropped = [], []
        for q in questions:
            iid = q["instance_id"]
            path, _ = resolve_gold_db(DBT_EVAL_SUITE / "gold", iid,
                                      gold_db_name(gold.get(iid)))
            (keep if path is not None else dropped).append(iid)
        if dropped:
            print(f"skipping {len(dropped)} instances with no gold database: "
                  f"{dropped}")
        questions = [q for q in questions if q["instance_id"] in set(keep)]
    if args.smallest:
        questions.sort(key=lambda q: project_size(q["instance_id"]))
        questions = questions[: args.smallest]
    if args.limit:
        questions = questions[: args.limit]

    base_url = read_endpoint(args.endpoint)
    client = OpenAI(base_url=base_url,
                    api_key=os.environ.get("VLLM_API_KEY", "EMPTY"))
    llm = LLMConfig(base_url=base_url, model=args.model,
                    temperature=args.temperature)
    cfg = AgentConfig(max_steps=args.max_steps)

    run_tag = args.run_tag or Path(args.submission).name
    sub = DbtSubmission(Path(args.submission), gold_dir=DBT_EVAL_SUITE / "gold")
    out_path = Path(args.output) if args.output else Path(args.submission) / "run.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    if trace_dir:
        trace_dir.mkdir(parents=True, exist_ok=True)

    if args.resume and out_path.exists():
        done = {r["instance_id"] for r in csv.DictReader(open(out_path))}
        questions = [q for q in questions if q["instance_id"] not in done]
        print(f"resume: {len(done)} already done, {len(questions)} remaining")
        mode, write_header = "a", False
    else:
        mode, write_header = "w", True

    submitted = 0
    with open(out_path, mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()

        for i, q in enumerate(questions):
            iid = q["instance_id"]
            print(f"[{i + 1}/{len(questions)}] {iid} ... ", end="", flush=True)

            try:
                ws = DbtWorkspace.stage(iid, DBT_EXAMPLES_DIR / iid, SCRATCH_DIR,
                                        run_tag=run_tag)
            except Exception as e:
                writer.writerow({"instance_id": iid, "db": iid, "score": 0,
                                 "score_detail": f"stage_failed: {e}",
                                 "status": "error"})
                f.flush()
                print(f"stage_failed: {e}")
                continue

            session = DbtToolSession(ws=ws, cfg=cfg)
            t0 = time.time()
            detail = ""
            try:
                for attempt in range(2):
                    wait_for_services(base_url, None)
                    result = run_episode(q["question"], session, llm, cfg, None,
                                         extra_context=ws.project_overview())
                    if not is_infra_error(result.error):
                        break
                    print("[infra error, retrying instance] ", end="", flush=True)
                else:
                    # record nothing, so --resume retries this instance later
                    raise SystemExit(f"infrastructure error on {iid}: {result.error}")

                row = sub.record(iid, result.pred_df,
                                 description=result.sql or "",
                                 duckdb_path=ws.duckdb_path)
                if result.pred_df is not None:
                    submitted += 1
                detail = f"{row['answer_type']}:{row.get('answer', '')}"[:80]
            finally:
                ws.close_duckdb()
                # the whole point of staging: prove nothing escaped into the
                # pristine tree before moving to the next instance
                ws.assert_source_untouched()
                if not args.keep_workspace:
                    import shutil
                    shutil.rmtree(ws.root, ignore_errors=True)

            writer.writerow({
                "instance_id": iid, "db": iid,
                "score": "", "score_detail": detail,
                "status": result.status, "steps": result.steps,
                "critic_rounds": result.critic_rounds,
                "search_calls": result.search_calls,
                "draft_calls": 0,
                "wall_seconds": round(time.time() - t0, 1),
                "dbt_calls": session.dbt_calls,
                "write_calls": session.write_calls,
                "dbt_build_ok": int(session.dbt_build_ok),
                "sql": (result.sql or "").replace("\n", "\\n")})
            f.flush()
            print(f"{result.status} ({result.steps} steps, "
                  f"{session.dbt_calls} dbt, {session.write_calls} writes, "
                  f"build_ok={int(session.dbt_build_ok)}, {time.time() - t0:.0f}s)")

            if trace_dir:
                with open(trace_dir / f"{iid}.json", "w", encoding="utf-8") as tf:
                    json.dump({"instance_id": iid, "question": q["question"],
                               "status": result.status, "score": None,
                               "detail": detail, "sql": result.sql,
                               "system": result.system, "trace": result.trace},
                              tf, indent=1, default=str)

    print(f"\n{submitted}/{len(questions)} produced a result; "
          f"submission at {args.submission}")
    print(f"score it:  uv run python scripts/score_dbt.py {args.submission}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
