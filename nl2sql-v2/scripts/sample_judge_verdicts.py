#!/usr/bin/env python3
"""Training targets for the judge: sample the deployed judge several times on every
right-vs-wrong pair in the agent's pools on a judge-training question set, keeping its
full reasoning (make_judge_sft_dpo.py turns these into SFT and DPO data).

Pools as in judge_pools.py: execute each lane's submitted SQL, group identical results
(row order ignored, the scorer's normalisation), label groups with the scorer. Every
(correct, wrong) pair of groups is judged in both presentation orders, --samples times
each, with the deployed judge's exact prompt (select_answer.PAIRWISE_PROMPT, the same
candidate rendering as judge_pools.py). Pairs whose results hold the same distinct
rows are skipped: they differ only in duplicates, which the scorer separates but the
question rarely decides.

Output: one JSON line per question: lanes, groups (label, size, SQL) and per ordered
pair the prompt and samples (reasoning, answer, verdict, right, truncated).

--judge-endpoint takes several servers of the same model, comma-separated: requests are
spread over them, a request whose server fails (connection or 5xx) moves to the next, and
when all are down it waits for one to come back (up to 2h) rather than record an error.

Usage (NL2SQL_DATASET_DIR set; from nl2sql-v2/):
    uv run python scripts/sample_judge_verdicts.py --runs a.csv,b.csv,c.csv,d.csv \\
        --judge-endpoint http://node:port/v1 --judge-model QuantTrio/Qwen3.6-35B-A3B-AWQ \\
        --samples 4 --output ../results/judge_train/verdicts_pilot.jsonl --resume
"""

import argparse
import csv
import itertools
import json
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql.config import QUESTIONS_FILE, SQLITE_DIR
from nl2sql.db import Database
from nl2sql.eval import load_eval_standards, score_against_gold
from select_answer import PAIRWISE_PROMPT, canonical, equivalent, question_context, result_preview


def judge_once(client, model, prompt, max_tokens, thinking=True):
    """One judge reply, as select_answer.ask_text sends it (Qwen thinking at temp
    0.6), returning the reasoning too: (answer text, reasoning, truncated)."""
    qwen_like = any(k in model.lower() for k in ("qwen", "jev"))
    think = thinking and qwen_like
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        temperature=0.6 if think else 0.2, max_tokens=max_tokens,
        extra_body={"chat_template_kwargs": {"enable_thinking": think}} if qwen_like else None)
    choice = resp.choices[0]
    msg = choice.message
    extra = msg.model_dump() if hasattr(msg, "model_dump") else {}
    reasoning = (getattr(msg, "reasoning", None) or getattr(msg, "reasoning_content", None)
                 or extra.get("reasoning") or extra.get("reasoning_content") or "")
    text = re.sub(r"<think>.*?</think>", "", msg.content or "", flags=re.DOTALL)
    return text, reasoning, choice.finish_reason == "length"


def verdict_of(text: str):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        v = str(json.loads(m.group(0)).get("winner", "")).strip().upper() if m else ""
    except Exception:
        v = ""
    return v if v in ("A", "B") else None


def build_pool(q, lane_rows, db, standards):
    """Groups of identical results over the lanes, labelled by the scorer."""
    iid = q["instance_id"]
    lanes, groups = [], []
    for k, r in enumerate(lane_rows):
        sql = (r.get("sql") or "").replace("\\n", "\n").strip()
        info = {"lane": k, "status": r.get("status", ""), "group": None, "error": ""}
        df = None
        if not sql:
            info["error"] = "no sql"
        else:
            try:
                df, _ = db.query_preview(sql, 1, 5000, timeout_s=60)
                df = canonical(df)
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
        lanes.append(info)
    for g in groups:
        g["rows"], g["cols"] = int(g["df"].shape[0]), int(g["df"].shape[1])
        g["correct"] = score_against_gold(g["df"], iid, standards)[0]
        g["preview"] = result_preview(g["df"])
    return lanes, groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="comma-separated results CSVs, one per lane")
    ap.add_argument("--judge-endpoint", required=True, help="one or more, comma-separated")
    ap.add_argument("--judge-model", required=True)
    ap.add_argument("--samples", type=int, default=4, help="judge samples per ordered pair")
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--no-thinking", action="store_true")
    ap.add_argument("--output", required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--workers", type=int, default=32, help="judge requests in flight")
    args = ap.parse_args()
    import openai
    # long: at 48 requests per server a full 8k-token answer takes over 15 min
    clients = [openai.OpenAI(base_url=e, api_key="EMPTY", timeout=1800)
               for e in args.judge_endpoint.split(",")]
    turn = itertools.count()

    lanes = [{r["instance_id"]: r for r in csv.DictReader(open(f))} for f in args.runs.split(",")]
    qmeta = {q["instance_id"]: q for q in map(json.loads, open(QUESTIONS_FILE))}
    standards = load_eval_standards()
    done = set()
    if args.resume and Path(args.output).exists():
        done = {json.loads(l)["instance_id"] for l in open(args.output)}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    records, tasks, db_cache = {}, [], {}
    for iid in sorted(set.intersection(*(set(l) for l in lanes)) - done):
        q = qmeta[iid]
        if q["db"] not in db_cache:
            db_cache[q["db"]] = Database(SQLITE_DIR / f"{q['db']}.sqlite")
        db = db_cache[q["db"]]
        pool_lanes, groups = build_pool(q, [l[iid] for l in lanes], db, standards)
        doc, schema = question_context(q, db)
        pairs = []
        for a, ga in enumerate(groups):
            for b, gb in enumerate(groups):
                if not ga["correct"] or gb["correct"]:
                    continue
                if equivalent(ga["df"].drop_duplicates(), gb["df"].drop_duplicates(), True):
                    continue  # duplicates only
                for first, second in ((a, b), (b, a)):
                    gf, gs = groups[first], groups[second]
                    prompt = PAIRWISE_PROMPT.format(
                        question=q["question"], doc_section=doc, schema_section=schema,
                        sql_a=gf["sql"], res_a=gf["preview"], sql_b=gs["sql"], res_b=gs["preview"])
                    pairs.append({"first": first, "second": second,
                                  "correct_letter": "A" if gf["correct"] else "B",
                                  "prompt": prompt, "samples": []})
        for g in groups:
            del g["df"]
        records[iid] = {"instance_id": iid, "db": q["db"], "split": q.get("split"),
                        "source": q.get("source"), "judge_model": args.judge_model,
                        "lanes": pool_lanes, "groups": groups, "pairs": pairs}
        tasks += [(iid, pi) for pi in range(len(pairs)) for _ in range(args.samples)]
    for d in db_cache.values():
        d.close()
    mixed = sum(1 for r in records.values() if r["pairs"])
    print(f"{len(records)} questions, {mixed} with a right-vs-wrong pair; "
          f"{len(tasks)} judge calls", flush=True)

    remaining = defaultdict(int)
    for iid, _ in tasks:
        remaining[iid] += 1
    lock = threading.Lock()
    out = open(args.output, "a")
    for iid, r in records.items():  # questions with nothing to judge are written now
        if not remaining[iid]:
            out.write(json.dumps(r) + "\n")
    out.flush()

    def judge(prompt):
        start = next(turn)
        for attempt in itertools.count():
            client = clients[(start + attempt) % len(clients)]
            try:
                return judge_once(client, args.judge_model, prompt, args.max_tokens,
                                  not args.no_thinking)
            except openai.APITimeoutError:  # the server answered too slowly: not a failover
                raise
            except (openai.APIConnectionError, openai.InternalServerError):
                if attempt + 1 >= 120 * len(clients):
                    raise
                if (attempt + 1) % len(clients) == 0:  # every server failed this round
                    time.sleep(60)

    def call(iid, pi):
        p = records[iid]["pairs"][pi]
        try:
            text, reasoning, truncated = judge(p["prompt"])
            v = verdict_of(text)
            return {"verdict": v, "right": v == p["correct_letter"], "answer": text.strip(),
                    "reasoning": reasoning, "truncated": truncated, "error": ""}
        except Exception as e:
            return {"verdict": None, "right": False, "answer": "", "reasoning": "",
                    "truncated": False, "error": str(e)[:200]}

    n_done = 0
    with ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(call, iid, pi): (iid, pi) for iid, pi in tasks}
        for fut in as_completed(futures):
            iid, pi = futures[fut]
            with lock:
                records[iid]["pairs"][pi]["samples"].append(fut.result())
                remaining[iid] -= 1
                n_done += 1
                if remaining[iid] == 0:
                    out.write(json.dumps(records[iid]) + "\n")
                    out.flush()
                    pr = records[iid]["pairs"]
                    right = sum(s["right"] for p in pr for s in p["samples"])
                    print(f"[{n_done}/{len(tasks)}] {iid}: {len(pr)} ordered pairs, "
                          f"{right}/{sum(len(p['samples']) for p in pr)} samples right", flush=True)
    out.close()


if __name__ == "__main__":
    main()
