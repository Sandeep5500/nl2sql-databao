#!/usr/bin/env python3
"""Summarise agent traces into neutral, fixed-template notes a judge can read:
the answer's interpretation, the evidence the agent actually checked, and its
doubts or changes of mind. Process facts (submitted or step-capped, steps, SQL
errors) are counted in code, not by the model. The summariser is told not to
say whether the answer is correct.

Usage (from nl2sql-v2/):
    uv run python scripts/summarize_traces.py --traces '../logs/traces/q36rg_pass4_k*' \\
        --endpoint http://node:8765/v1 --model QuantTrio/Qwen3.6-35B-A3B-AWQ \\
        --output ../results/notes/q36rg_summaries.jsonl --shard 0/8 --resume
"""

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from judge_pairs import in_shard
from select_answer import ask_text

SUMMARY_PROMPT = """Below is the working log of an agent that answered a database question \
with SQL. Summarise how it arrived at its FINAL answer, in exactly this format:

Interpretation: <how the final answer reads the question: grain (one row per what), \
filters, what is counted or summed, ranking/limit, output columns>
Evidence checked: <facts the agent verified with its own queries that the final answer \
relies on, e.g. which values a column holds, how tables join, row counts>
Doubts or changes: <what it hesitated over, alternatives it considered, and what it \
changed along the way and why; "none" if none>

Rules: at most 120 words in total. State facts from the log only. Do not say or imply \
whether the final answer is correct, and do not praise or criticise it.

Question: {question}

Final SQL:
{final_sql}

Working log:
{log}"""


def condense(trace, max_chars):
    """Agent reasoning, queries (with their first result lines or errors) and other
    tool calls, in order; long logs keep the start and the (more decisive) end."""
    out = []
    for e in trace:
        a = e.get("assistant")
        if isinstance(a, dict):
            if a.get("content"):
                out.append("AGENT: " + " ".join(a["content"].split())[:800])
            for tc in a.get("tool_calls") or []:
                if tc["function"]["name"] == "submit_result":
                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except Exception:
                        args = {}
                    out.append(f"SUBMITTED {args.get('query_id', '')}: "
                               f"{str(args.get('result_description', ''))[:400]}")
        elif e.get("tool") == "run_sql_query":
            args = e.get("args") if isinstance(e.get("args"), dict) else {}
            sql = " ".join(str(args.get("sql", e.get("args", ""))).split())[:400]
            res = str(e.get("result", ""))
            head = " | ".join(res.splitlines()[:4])[:300]
            out.append(f"QUERY: {sql}\n  RESULT: {head}" if res.startswith("query_id=")
                       else f"QUERY: {sql}\n  ERROR: {res[:200]}")
        elif e.get("tool"):
            out.append(f"TOOL {e['tool']}({str(e.get('args', ''))[:80]})")
    text = "\n".join(out)
    if len(text) > max_chars:
        head = max_chars // 5
        text = text[:head] + "\n[... middle of the log omitted ...]\n" + text[-(max_chars - head):]
    return text


def process_facts(t):
    trace = t.get("trace") or []
    steps = max([int(e["step"]) for e in trace if str(e.get("step", "")).isdigit()] or [0])
    queries = [e for e in trace if e.get("tool") == "run_sql_query"]
    errors = sum(1 for e in queries if not str(e.get("result", "")).startswith("query_id="))
    return {"status": t.get("status", ""), "steps": steps, "n_queries": len(queries),
            "n_sql_errors": errors}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", required=True, help="comma-separated globs of run directories")
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--max-chars", type=int, default=24000)
    ap.add_argument("--shard")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    from openai import OpenAI
    client = OpenAI(base_url=args.endpoint, api_key="EMPTY", timeout=600)
    files = sorted(f for pat in args.traces.split(",") for d in sorted(glob.glob(pat))
                   for f in glob.glob(f"{d}/*.json"))
    done = set()
    if args.resume and Path(args.output).exists():
        done = {(r["run"], r["instance_id"]) for r in map(json.loads, open(args.output))}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out = open(args.output, "a")
    for i, f in enumerate(files):
        if not in_shard(i, args.shard):
            continue
        t = json.load(open(f))
        key = (Path(f).parent.name, t["instance_id"])
        if key in done:
            continue
        rec = {"run": key[0], "instance_id": key[1], **process_facts(t), "summary": "", "error": ""}
        try:
            prompt = SUMMARY_PROMPT.format(question=t["question"], final_sql=(t.get("sql") or "")[:3000],
                                           log=condense(t.get("trace") or [], args.max_chars))
            rec["summary"] = ask_text(client, args.model, prompt, 0.2, 400).strip()
        except Exception as e:
            rec["error"] = str(e)[:200]
        out.write(json.dumps(rec) + "\n")
        out.flush()
        print(f"{key[0]} {key[1]}: {len(rec['summary'])} chars {rec['error'][:60]}", flush=True)
    out.close()


if __name__ == "__main__":
    main()
