#!/usr/bin/env python3
"""Round 3 listwise judge (Nov 18; documents/bq_judge_improvement_plan.md, "Round 3"): for every mixed pool with
three or four distinct results, one call shows all of them (numbered: SQL, result preview, and the computed
comparison of each pair) and asks which one answers the question (judge_prompts.LISTWISE). Sample s shows the
groups starting from the s-th one (a rotation), so each group comes first about equally often. Pools with two
results keep the round-robin; rejudge_pools.py judges those.

Output: <out-dir>/calls_listwise.jsonl, one JSON line per call (resumable): key, sample, order (group indices in
the order shown), pick (group index, or null without a valid pick), reason, reasoning, completion_tokens,
truncated, error, retry, timeouts. calls_listwise.starts.jsonl gets a line when each request is sent, as in
rejudge_pools.py. Scoring: results/bq17/round3/score_r3.py.

Usage (on Babel, from nl2sql-v2/; the data arguments are rejudge_pools.py's):
    python scripts/listwise_pools.py --evalset bq17_evalset.json --select half=bq --samples 4 \\
        --pools $W/results/pools --bq-pools $BQP --bq-ref-prefix groups --bq-base $BQB --bq-questions $BQQ \\
        --comparisons compare_cache.jsonl --judge-endpoint http://localhost:8765/v1,http://localhost:8766/v1 \\
        --judge-model QuantTrio/Qwen3.6-35B-A3B-AWQ --out-dir results/listwise --resume
"""

import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from judge_prompts import LISTWISE
from rejudge_pools import Contexts, load_reference


def build_prompt(question, doc, schema, it, order, comps):
    """The listwise prompt for pool record `it`, showing groups in `order` as candidates 1..n."""
    blocks = []
    for i, g in enumerate(order, 1):
        grp = it["groups"][g]
        blocks.append(f"--- Candidate {i} ---\nSQL:\n{grp['sql']}\nExecution result:\n{grp['preview']}\n")
    pairs = []
    for i in range(len(order)):
        for j in range(i + 1, len(order)):
            text = comps.get((order[i], order[j]), "Comparison unavailable.")
            pairs.append(f"[Candidate {i + 1} vs Candidate {j + 1}: A = Candidate {i + 1}, B = Candidate {j + 1}]\n{text}")
    return LISTWISE.format(n=len(order), question=question, doc_section=doc, schema_section=schema,
                           candidates="\n".join(blocks), comparisons="\n\n".join(pairs))


def parse_pick(text, n):
    """Candidate number (1..n) named in the reply's JSON, or raise."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON in reply: {text[-120:]!r}")
    try:
        data = json.loads(m.group(0))
        raw, reason = data.get("winner"), str(data.get("reason", ""))
    except ValueError:
        w = re.findall(r'"winner"\s*:\s*"?(?:Candidate\s*)?(\d+)', m.group(0))
        if not w:
            raise
        raw, reason = w[-1], m.group(0)
    d = re.findall(r"\d+", str(raw))
    if not d or not 1 <= int(d[0]) <= n:
        raise ValueError(f"invalid winner {raw!r}")
    return int(d[0]), reason[:500]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evalset", required=True)
    ap.add_argument("--select", default="", help="filters, e.g. half=bq")
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--min-groups", type=int, default=3, help="judge pools with at least this many results")
    ap.add_argument("--pools", required=True)
    ap.add_argument("--ref-prefix", default="think35/qwen36-35b-think")
    ap.add_argument("--bq-pools")
    ap.add_argument("--bq-ref-prefix", default="think35_bq")
    ap.add_argument("--bq-base")
    ap.add_argument("--bq-questions")
    ap.add_argument("--facts", help="unused by the listwise prompt; accepted so arm files can share arguments")
    ap.add_argument("--comparisons", required=True)
    ap.add_argument("--judge-endpoint", required=True)
    ap.add_argument("--judge-model", required=True)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--timeout", type=float, default=14400)
    ap.add_argument("--chat-template-kwargs", default='{"enable_thinking": true}')
    ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true", help="print one prompt and exit")
    ap.add_argument("--count-only", action="store_true")
    args = ap.parse_args()

    ev = json.loads(Path(args.evalset).read_text())["pools"]
    filt = [f.split("=") for f in args.select.split(";") if f]
    keys = sorted(k for k, e in ev.items() if e["stratum"] in ("contested", "easy")
                  and sum(1 for g in e["groups"] if g[0] > 0) >= args.min_groups
                  and all(str(e[name]) in want.split("|") for name, want in filt))
    if args.limit:
        keys = keys[:args.limit]
    ref = load_reference(args.pools, args.ref_prefix, args.bq_pools or "", args.bq_ref_prefix)
    from selection_eval import signature
    for k in keys:
        if json.dumps(signature(ref[k])) != json.dumps(ev[k]["sig"]):
            raise SystemExit(f"{k}: reference pool differs from the eval set")
    comps = {}
    for r in map(json.loads, open(args.comparisons)):
        comps.setdefault(r["key"], {})[(r["first"], r["second"])] = r["text"]
    ctx = Contexts(args)

    def order_of(k, s):
        alive = [a for a, g in enumerate(ev[k]["groups"]) if g[0] > 0]
        r = s % len(alive)
        return alive[r:] + alive[:r]

    def prompt_for(k, s):
        question, doc, schema = ctx.get(k, ref[k])
        return build_prompt(question, doc, schema, ref[k], order_of(k, s), comps.get(k, {}))

    if args.dry_run:
        print(prompt_for(keys[0], 0))
        return
    os.makedirs(args.out_dir, exist_ok=True)
    out_path = Path(args.out_dir) / "calls_listwise.jsonl"
    done = set()
    if args.resume and out_path.exists():
        for line in open(out_path):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not r.get("retry"):
                done.add((r["key"], r["sample"]))
    tasks = [(k, s) for s in range(args.samples) for k in keys if (k, s) not in done]
    if args.count_only:
        print(len(tasks))
        return
    print(f"{len(keys)} pools with >= {args.min_groups} results x {args.samples} samples: {len(tasks)} calls", flush=True)
    for k in {t[0] for t in tasks}:  # contexts up front (schema reads are not thread-safe)
        ctx.get(k, ref[k])

    import openai
    clients = []
    for e in args.judge_endpoint.split(","):
        c = openai.OpenAI(base_url=e, api_key="EMPTY", timeout=args.timeout, max_retries=0)
        try:
            served = [m.id for m in c.models.list().data]
        except Exception as ex:
            print(f"{e}: not answering ({str(ex)[:80]})", flush=True)
            continue
        if args.judge_model in served:
            clients.append(c)
        else:
            print(f"{e}: serves {served}, not {args.judge_model}; skipped", flush=True)
    if not clients:
        raise SystemExit("no endpoint serves the judge model")
    ctk = json.loads(args.chat_template_kwargs)

    def request(i, prompt, rec):
        deadline = time.time() + 7200
        while True:
            for j in range(len(clients)):
                try:
                    return clients[(i + j) % len(clients)].chat.completions.create(
                        model=args.judge_model, messages=[{"role": "user", "content": prompt}],
                        temperature=0.6, max_tokens=args.max_tokens,
                        extra_body={"chat_template_kwargs": ctk} if ctk else None)
                except openai.APITimeoutError:
                    rec["timeouts"] += 1
                except (openai.APIConnectionError, openai.InternalServerError):
                    continue
            if time.time() > deadline:
                raise RuntimeError("all judge servers down for 2h")
            time.sleep(60)

    def call(i, k, s):
        order = order_of(k, s)
        rec = {"key": k, "sample": s, "order": order, "pick": None, "reason": "", "reasoning": "",
               "completion_tokens": None, "truncated": False, "error": "", "retry": False, "timeouts": 0}
        with lock:
            starts.write(json.dumps({"key": k, "sample": s, "t": round(time.time()),
                                     "job": os.environ.get("SLURM_JOB_ID", ""),
                                     "restart": os.environ.get("SLURM_RESTART_COUNT", "0")}) + "\n")
            starts.flush()
        try:
            resp = request(i, prompt_for(k, s), rec)
            ch = resp.choices[0]
            extra = ch.message.model_dump()
            rec["reasoning"] = (getattr(ch.message, "reasoning", None) or extra.get("reasoning")
                                or extra.get("reasoning_content") or "")
            rec["completion_tokens"] = resp.usage.completion_tokens if resp.usage else None
            rec["truncated"] = ch.finish_reason == "length"
            label, rec["reason"] = parse_pick(ch.message.content, len(order))
            rec["pick"] = order[label - 1]
        except Exception as e:
            rec["error"] = str(e)[:200]
            rec["retry"] = isinstance(e, RuntimeError)
        return rec

    lock = threading.Lock()
    starts = open(Path(args.out_dir) / "calls_listwise.starts.jsonl", "a")
    t0 = time.time()
    with open(out_path, "a") as out, ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(call, i, k, s) for i, (k, s) in enumerate(tasks)]
        for n, f in enumerate(as_completed(futs), 1):
            r = f.result()
            with lock:
                out.write(json.dumps(r) + "\n")
                out.flush()
            if n % 50 == 0:
                print(f"{n}/{len(tasks)} calls, {(time.time() - t0) / 60:.0f} min", flush=True)
    starts.close()


if __name__ == "__main__":
    main()
