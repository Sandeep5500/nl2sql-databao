#!/usr/bin/env python3
"""judge_pools.py for Rohini's BigQuery pass@k runs (bigquery_passk_nov2026). Each lane's result is
read from its trace (the preview of the submitted query) instead of re-executing the SQL on
BigQuery, which bills per byte. The schema shown to the judge is the one in the agent's system
prompt. Correctness comes from the run's recorded score (analysis only, never shown to the judge).

Previews are complete except for large results ("[showing 50 of N rows]"); those groups are
compared on their first 50 rows plus the total row count, and the judge sees 8 rows plus the true
shape, as in judge_pools.py.

Usage (from nl2sql-v2/):
    python scripts/bq_judge_pools.py --base <dir with 1_greedy_run_R, 2_retry_*> \\
        --questions bq_questions.jsonl --judge pairwise --judge-endpoint http://localhost:8765/v1 \\
        --judge-model QuantTrio/Qwen3.6-35B-A3B-AWQ --thinking --max-tokens 8192 \\
        --save-reasoning --pair-workers 4 --output pools/think35_bq.jsonl --resume
    ... --judge jev_choice --jev-dir <JEV-27B dir> --judge-endpoint http://localhost:8796/v1
    ... --no-judge  (build the groups only)
"""

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from select_answer import canonical, equivalent, pairwise_verdict
from judge_pairs import JevJudge, in_shard, jev_state
from judge_pools import contains
import select_answer

# lane order: the four temperature-0.7 retries first (so a group's representative SQL comes from
# a retry), then the greedy run, which is wrong on every retried question
LANES = ["2_retry_1", "2_retry_2", "2_retry_3", "2_retry_4", "1_greedy_run_R"]
SHOWING = re.compile(r"^\[showing (\d+) of (\d+) rows\]$")
CAPPED = re.compile(r"^\[(showing \d+ rows; result exceeded|result truncated)")


def norm_sql(s):
    return re.sub(r"\s+", " ", (s or "").replace("\\n", "\n")).strip().rstrip(";")


def final_result(trace, sql):
    """Tool output of the submitted query, or (no submit) of the last run of the recorded SQL."""
    sub = None
    for s in trace["trace"]:
        for c in (s.get("assistant") or {}).get("tool_calls") or []:
            if c["function"]["name"] == "submit_result":
                try:
                    sub = json.loads(c["function"]["arguments"]).get("query_id")
                except Exception:
                    pass
    by_id = by_sql = None
    for s in trace["trace"]:
        r = s.get("result")
        if s.get("tool") != "run_sql_query" or not isinstance(r, str):
            continue
        if sub and r.startswith(f"query_id='{sub}'\n"):
            by_id = r
        if norm_sql((s.get("args") or {}).get("sql")) == norm_sql(sql):
            by_sql = r
    return by_id or by_sql


def parse_result(r):
    """(df, total_rows, capped) from a run_sql_query tool output; raises on errors."""
    lines = r.split("\n")
    if not lines[0].startswith("query_id="):
        raise ValueError(r[:160])
    body, total, capped = [], None, False
    for line in lines[1:]:
        m = SHOWING.match(line.strip())
        if m:
            total = int(m.group(2))
        elif CAPPED.match(line.strip()):
            capped = True
        elif not line.startswith("[scanned "):
            body.append(line)
    text = "\n".join(body).strip()
    if not text:
        raise ValueError("empty output")
    df = canonical(pd.read_csv(io.StringIO(text)))
    return df, (total if total is not None else int(df.shape[0])), capped


def names_overview(dump, char_cap=8_000):
    """The agent's BigQuery schema dump reduced to run_benchmark.schema_overview's form (the
    schema the SQLite judges saw): one 'table: col, col, ...' line per table, same header and cap.
    The dump mixes full blocks (table:/columns:/sample rows:), compact 'table: cols' lines and
    '- table' name lists."""
    lines, cur, cols, in_cols = [], None, [], False

    def flush():
        if cur:
            lines.append(f"{cur}: {', '.join(cols)}" if cols else cur)

    for raw in dump.split("\n"):
        line = raw.rstrip("\r")
        if line.startswith("table: "):
            flush()
            cur, cols, in_cols = line[7:].split("  ")[0].strip(), [], False
        elif line == "columns:":
            in_cols = True
        elif line == "sample rows:" or (not line.strip() and in_cols):
            in_cols = False
        elif in_cols and line.startswith("  ") and line.strip():
            cols.append(line.split()[0])
        elif re.match(r"^[\w\-]+\.[\w\-.*]+: \S", line):
            flush(); cur = None
            lines.append(line)
        elif re.match(r"^- [\w\-]+\.[\w\-.*]+\s*$", line):
            flush(); cur = None
            lines.append(line[2:].strip())
    flush()
    text = "\n".join(lines)
    if len(text) > char_cap:
        text = text[:char_cap] + "\n[overview truncated — use list_tables/describe_table]"
    return ("\nSchema overview (columns per table; use describe_table for "
            "types/samples):\n" + text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--questions", required=True, help="jsonl: instance_id, question, doc (text)")
    ap.add_argument("--judge", choices=["jev_choice", "pairwise"])
    ap.add_argument("--judge-endpoint")
    ap.add_argument("--judge-model", default="jev-decision")
    ap.add_argument("--jev-dir")
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--max-schema-chars", type=int, default=40000)
    ap.add_argument("--schema-format", choices=["agent", "names"], default="agent",
                    help="agent: the schema dump from the agent's system prompt; names: reduced to "
                         "the SQLite judges' table -> column names overview (8k chars)")
    ap.add_argument("--output", required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--thinking", action="store_true")
    ap.add_argument("--shard")
    ap.add_argument("--save-reasoning", action="store_true")
    ap.add_argument("--pair-workers", type=int, default=1)
    ap.add_argument("--no-judge", action="store_true")
    args = ap.parse_args()
    select_answer.THINKING = args.thinking
    base = Path(args.base)

    lanes = [{r["instance_id"]: r for r in csv.DictReader(open(base / d / "all.csv"))} for d in LANES]
    qmeta = {json.loads(l)["instance_id"]: json.loads(l) for l in open(args.questions)}
    done = set()
    if args.resume and Path(args.output).exists():
        done = {json.loads(l)["instance_id"] for l in open(args.output)}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out = open(args.output, "a")

    if args.no_judge:
        pass
    elif args.judge == "jev_choice":
        jev = JevJudge(args.judge_endpoint, args.jev_dir, 40000)
    else:
        from openai import OpenAI
        llm = (OpenAI(base_url=args.judge_endpoint, api_key="EMPTY", timeout=1800),
               args.judge_model, args.max_tokens)

    for qi, iid in enumerate(sorted(set.intersection(*(set(l) for l in lanes)))):
        if iid in done or not in_shard(qi, args.shard):
            continue
        q = qmeta[iid]
        lane_info, groups, systems = [], [], {}
        for k, lane in enumerate(lanes):
            r = lane[iid]
            sql = (r.get("sql") or "").replace("\\n", "\n").strip()
            info = {"lane": k, "run": LANES[k], "status": r.get("status", ""),
                    "recorded_score": int(r["score"]), "error": "", "rows": None, "group": None}
            tr = json.load(open(base / LANES[k] / "traces" / f"{iid}.json"))
            systems[k] = tr.get("system", "")
            df = None
            if not sql:
                info["error"] = "no sql"
            else:
                res = final_result(tr, sql)
                if res is None:
                    info["error"] = "no result in trace"
                else:
                    try:
                        df, total, capped = parse_result(res)
                        info["rows"], info["capped"] = total, capped
                    except Exception as e:
                        info["error"] = str(e)[:160]
            if df is not None:
                for gi, g in enumerate(groups):
                    if g["rows"] == info["rows"] and equivalent(df, g["df"], True):
                        g["lanes"].append(k)
                        if info["status"] == "submitted" and g["status"] != "submitted":
                            g["sql"], g["status"] = sql, "submitted"
                        info["group"] = gi
                        break
                else:
                    info["group"] = len(groups)
                    groups.append({"df": df, "sql": sql, "status": info["status"], "lanes": [k],
                                   "rows": info["rows"], "partial": info["rows"] > df.shape[0]})
            lane_info.append(info)

        for gi, g in enumerate(groups):
            members = [li for li in lane_info if li["group"] == gi]
            sub = [li for li in members if li["status"] == "submitted"]
            g["rep_lane"] = (sub or members)[0]["lane"]
            scores = {li["recorded_score"] for li in members}
            g["correct"] = int(max(scores))  # analysis only
            g["score_conflict"] = len(scores) > 1
            g["cols"] = int(g["df"].shape[1])
            g["preview"] = g["df"].head(8).to_csv(index=False) + f"[{g['rows']} rows x {g['cols']} cols total]"
        contains_map = {f"{a}>{b}": True for a in range(len(groups)) for b in range(len(groups))
                        if a != b and groups[b]["rows"] > 0 and not groups[a]["partial"]
                        and not groups[b]["partial"] and contains(groups[a]["df"], groups[b]["df"])}

        judgments = []
        if len(groups) > 1 and not args.no_judge:
            doc = ("\nReference documentation:\n" + q["doc"][:8000] + "\n") if q.get("doc") else ""
            system = systems[groups[0]["rep_lane"]]
            m = re.search(r"Full database schema.*?(?=\n## Expected output shape|\Z)", system, re.S)
            dump = m.group(0) if m else ""
            schema = "\n" + (names_overview(dump) if args.schema_format == "names"
                             else dump[:args.max_schema_chars]) + "\n"

            def judge(a, b):
                ca = (groups[a]["sql"], groups[a]["preview"])
                cb = (groups[b]["sql"], groups[b]["preview"])
                rec = {"first": a, "second": b, "p_first": None, "verdict": "", "error": ""}
                try:
                    if args.judge == "jev_choice":
                        p = jev.decide("choice", jev_state(q, doc, schema, [ca, cb]),
                                       "Which candidate SQL query correctly answers the "
                                       "database question?", ["Candidate A", "Candidate B"])
                        rec["p_first"], rec["verdict"] = p[0], "AB"[p[1] > p[0]]
                    else:
                        rec["verdict"], rec["p_first"] = pairwise_verdict(*llm, q, doc, schema, ca, cb)
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


if __name__ == "__main__":
    main()
