#!/usr/bin/env python3
"""Judge every pair of distinct answers in a K-lane pool, both presentation orders,
and save everything a selection rule needs, so rule layers (superset merge,
unanimity, strong majority, judge margin) can be swept offline (analyze_pools.py).

Per question: execute each lane's submitted SQL, group identical results (row order
ignored, same normalisation as the scorer), record which group's columns contain
another's (same rows), label groups with the scorer (for analysis only, never shown
to the judge), and ask the judge about every ordered pair of groups.

Usage (from nl2sql-v2/):
    uv run python scripts/judge_pools.py --runs a.csv,b.csv,c.csv,d.csv \\
        --judge jev_choice --judge-endpoint http://node:8796/v1 --jev-dir <JEV-27B dir> \\
        --output ../results/pools/jev27b_q36rg.jsonl --resume
    ... --judge pairwise --judge-model QuantTrio/Qwen3.6-35B-A3B-AWQ  (P(A) from logprobs)
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql.config import QUESTIONS_FILE, SQLITE_DIR
from nl2sql.db import Database
from nl2sql.eval import compare_dataframes, load_eval_standards, score_against_gold
from select_answer import (canonical, equivalent, pairwise_verdict, question_context,
                           result_preview)
from judge_pairs import JevJudge, db_context_for, in_shard, jev_state
import select_answer


def contains(big, small):
    """big holds every column of small, same row count (row order ignored)."""
    return (big.shape[0] == small.shape[0] and small.shape[1] <= big.shape[1]
            and compare_dataframes(big, small, ignore_order=True))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="comma-separated results CSVs (one per lane)")
    ap.add_argument("--judge", choices=["jev_choice", "pairwise"], required=True)
    ap.add_argument("--judge-endpoint", required=True)
    ap.add_argument("--judge-model", default="jev-decision")
    ap.add_argument("--jev-dir")
    ap.add_argument("--jev-inputs", default="sql_results",
                    choices=["sql_results", "sql", "results", "sql_results_db", "sql_results_db_nodup"],
                    help="what jev_choice sees of each candidate (see judge_pairs.py)")
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--output", required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--thinking", action="store_true",
                    help="LLM judge reasons before answering (Qwen enable_thinking, temp 0.6)")
    ap.add_argument("--shard", help="k/n: judge only every n-th question starting at k")
    ap.add_argument("--notes", help="summarize_traces.py output; adds each candidate's trace "
                                    "notes to the pairwise prompt")
    ap.add_argument("--notes-runs", help="comma-separated trace run names in lane order "
                                         "(e.g. q36rg_pass4_k1,...,q36rg_pass4_k4)")
    ap.add_argument("--save-reasoning", action="store_true",
                    help="store the judge's reasoning text (thinking mode) per judgment")
    ap.add_argument("--pair-workers", type=int, default=1,
                    help="judge a question's ordered pairs concurrently (pairwise judge only)")
    args = ap.parse_args()
    select_answer.THINKING = args.thinking
    notes = {}
    if args.notes:
        runs = args.notes_runs.split(",")
        import glob as _glob
        for path in sorted(_glob.glob(args.notes)):  # a file or a glob of shard files
            for r in map(json.loads, open(path)):
                notes[(r["run"], r["instance_id"])] = r
        print(f"loaded notes for {len(notes)} traces", flush=True)

    def notes_for(iid, lane_idx):
        r = notes.get((runs[lane_idx], iid))
        if not r:
            return "(no notes available)"
        proc = (f"Process: submitted after {r['steps']} steps, {r['n_queries']} queries, "
                f"{r['n_sql_errors']} SQL errors." if r["status"] == "submitted" else
                f"Process: hit the step limit after {r['steps']} steps without submitting; "
                f"this answer was taken from its queries ({r['n_sql_errors']} SQL errors).")
        return (r["summary"] or "(summary unavailable)") + "\n" + proc

    lanes = [{r["instance_id"]: r for r in csv.DictReader(open(f))} for f in args.runs.split(",")]
    qmeta = {json.loads(l)["instance_id"]: json.loads(l) for l in open(QUESTIONS_FILE)}
    standards = load_eval_standards()
    done = set()
    if args.resume and Path(args.output).exists():
        done = {json.loads(l)["instance_id"] for l in open(args.output)}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out = open(args.output, "a")

    if args.judge == "jev_choice":
        jev = JevJudge(args.judge_endpoint, args.jev_dir, 40000)
    else:
        from openai import OpenAI
        # long: under many concurrent requests a full 8k-token answer can take over 10 min
        llm = (OpenAI(base_url=args.judge_endpoint, api_key="EMPTY", timeout=1800),
               args.judge_model, args.max_tokens)

    db_cache = {}
    for qi, iid in enumerate(sorted(set.intersection(*(set(l) for l in lanes)))):
        if iid in done or not in_shard(qi, args.shard):
            continue
        q = qmeta[iid]
        if q["db"] not in db_cache:
            db_cache[q["db"]] = Database(SQLITE_DIR / f"{q['db']}.sqlite")
        db = db_cache[q["db"]]

        lane_info, groups = [], []
        for k, lane in enumerate(lanes):
            r = lane[iid]
            sql = (r.get("sql") or "").replace("\\n", "\n").strip()
            info = {"lane": k, "status": r.get("status", ""), "recorded_score": int(r["score"]),
                    "error": "", "rows": None, "group": None}
            df = None
            if not sql:
                info["error"] = "no sql"
            else:
                try:
                    df, _ = db.query_preview(sql, 1, 5000, timeout_s=60)
                    df = canonical(df)
                    info["rows"] = int(df.shape[0])
                except Exception as e:
                    info["error"] = str(e)[:160]
            if df is not None:
                for gi, g in enumerate(groups):
                    if equivalent(df, g["df"], True):
                        g["lanes"].append(k)
                        if info["status"] == "submitted" and g["status"] != "submitted":
                            g["sql"], g["status"] = sql, "submitted"  # prefer a submitted SQL
                        info["group"] = gi
                        break
                else:
                    info["group"] = len(groups)
                    groups.append({"df": df, "sql": sql, "status": info["status"], "lanes": [k]})
            lane_info.append(info)

        for gi, g in enumerate(groups):
            members = [li for li in lane_info if li["group"] == gi]
            sub = [li for li in members if li["status"] == "submitted"]
            g["rep_lane"] = (sub or members)[0]["lane"]
        for g in groups:
            g["rows"], g["cols"] = int(g["df"].shape[0]), int(g["df"].shape[1])
            g["correct"] = score_against_gold(g["df"], iid, standards)[0]  # analysis only
            g["preview"] = result_preview(g["df"])
        contains_map = {f"{a}>{b}": True for a in range(len(groups)) for b in range(len(groups))
                        if a != b and groups[b]["rows"] > 0 and contains(groups[a]["df"], groups[b]["df"])}

        judgments = []
        if len(groups) > 1:
            doc, schema = question_context(q, db)

            def judge(a, b):
                ca = (groups[a]["sql"], groups[a]["preview"])
                cb = (groups[b]["sql"], groups[b]["preview"])
                rec = {"first": a, "second": b, "p_first": None, "verdict": "", "error": ""}
                nts = ((notes_for(iid, groups[a]["rep_lane"]), notes_for(iid, groups[b]["rep_lane"]))
                       if args.notes else None)
                try:
                    if args.judge == "jev_choice":
                        ctx = (db_context_for(db, q["db"], [ca[0], cb[0]],
                                              drop_dup_facts=args.jev_inputs.endswith("_nodup"))
                               if "_db" in args.jev_inputs else "")
                        p = jev.decide("choice", jev_state(q, doc, schema, [ca, cb],
                                                           inputs=args.jev_inputs.split("_db")[0],
                                                           db_context=ctx),
                                       "Which candidate SQL query correctly answers the "
                                       "database question?", ["Candidate A", "Candidate B"])
                        rec["p_first"], rec["verdict"] = p[0], "AB"[p[1] > p[0]]
                    else:
                        rec["verdict"], rec["p_first"] = pairwise_verdict(*llm, q, doc, schema, ca, cb,
                                                                          notes=nts)
                        if args.save_reasoning:
                            rec["reasoning"] = (getattr(select_answer._LOCAL, "reasoning", None) or "")[:6000]
                except Exception as e:
                    rec["error"] = str(e)[:160]
                return rec

            pairs = [(a, b) for a in range(len(groups)) for b in range(len(groups)) if a != b]
            if args.pair_workers > 1 and args.judge == "pairwise":
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(args.pair_workers) as ex:
                    judgments = list(ex.map(lambda ab: judge(*ab), pairs))
            else:
                judgments = [judge(a, b) for a, b in pairs]

        for g in groups:
            del g["df"]
        out.write(json.dumps({"instance_id": iid, "lanes": lane_info, "groups": groups,
                              "contains": sorted(contains_map), "judgments": judgments}) + "\n")
        out.flush()
        print(f"{iid}: {len(groups)} groups, {len(judgments)} judgments, "
              f"correct groups {[i for i, g in enumerate(groups) if g['correct']]}", flush=True)
    out.close()
    for d in db_cache.values():
        d.close()


if __name__ == "__main__":
    main()
