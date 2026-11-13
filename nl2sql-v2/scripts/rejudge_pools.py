#!/usr/bin/env python3
"""Re-judge the stored groups of selection-eval pools (selection_eval.py) with prompt variants,
K samples per ordered pair, for `selection_eval.py score`. No SQL is executed: every group's SQL
and 8-row preview come from the reference pools, so all variants judge identical candidates.

Prompts are built as the reference runs built them: Spider2 as judge_pools.py (question_context:
external doc <= 8000 chars + schema overview), BigQuery as bq_judge_pools.py (doc from
bq_questions.jsonl, the agent's schema dump from a trace's system prompt, <= 40000 chars).
Requests are sent as select_answer.ask_text sends them with THINKING on (temperature 0.6,
enable_thinking, top-5 logprobs so P(A) is read at the "winner" token); the full reasoning,
completion tokens and truncation are kept. Calls are interleaved sample-major across variants
(sample 0 of every variant and pair, then sample 1, ...), so a run cut short still leaves every
variant with the same number of samples.

Output: <out-dir>/calls_<variant>.jsonl, one JSON line per call (resumable): key, first, second,
sample, variant, verdict, p_first, reason, reasoning, completion_tokens, truncated, error, retry.
A reply without a valid verdict (no JSON, truncated reasoning, bad request) is final and counts as
a missing verdict, as in the reference runs; only server failures (retry=true) are made again.

Usage (on Babel, from nl2sql-v2/):
    python scripts/rejudge_pools.py --evalset selection_evalset.json --variants base,colrule \\
        --select half=design --samples 4 --pools $W/results/pools --bq-pools $B/pools \\
        --bq-base $B/bigquery_passk_nov2026 --bq-questions $B/bq_questions.jsonl \\
        --judge-endpoint http://localhost:8765/v1,http://localhost:8766/v1 \\
        --judge-model QuantTrio/Qwen3.6-35B-A3B-AWQ --out-dir results/variants --resume
"""

import argparse
import glob
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

from select_answer import PAIRWISE_PROMPT, winner_prob
from judge_prompts import VARIANTS

BQ_LANES = ["2_retry_1", "2_retry_2", "2_retry_3", "2_retry_4", "1_greedy_run_R"]


def load_reference(pools_dir, prefix, bq_dir, bq_prefix):
    """{pool key: reference pool record} (the same records selection_eval.py build read)."""
    from selection_eval import pool_key
    ref = {}
    for f in glob.glob(f"{pools_dir}/{prefix}_*_n12_s*.jsonl") + glob.glob(f"{bq_dir}/{bq_prefix}_n16_s*.jsonl"):
        for line in open(f):
            it = json.loads(line)
            ref[pool_key(f, it["instance_id"])] = it
    return ref


class Contexts:
    """(question text, doc_section, schema_section) per pool, built as the reference runs built them."""

    def __init__(self, args):
        self.args, self.cache, self.dbs = args, {}, {}
        self.qmeta = self.bqmeta = None

    def get(self, key, it):
        iid = it["instance_id"]
        if iid in self.cache:
            return self.cache[iid]
        if key.startswith("bq:"):
            if self.bqmeta is None:
                self.bqmeta = {q["instance_id"]: q for q in map(json.loads, open(self.args.bq_questions))}
            q = self.bqmeta[iid]
            doc = ("\nReference documentation:\n" + q["doc"][:8000] + "\n") if q.get("doc") else ""
            rep = it["groups"][0]["rep_lane"]  # bq_judge_pools.py: the schema of group 0's representative lane
            tr = json.load(open(Path(self.args.bq_base) / BQ_LANES[rep] / "traces" / f"{iid}.json"))
            m = re.search(r"Full database schema.*?(?=\n## Expected output shape|\Z)", tr.get("system", ""), re.S)
            schema = "\n" + (m.group(0) if m else "")[:40000] + "\n"
        else:
            from nl2sql.config import QUESTIONS_FILE, SQLITE_DIR
            from nl2sql.db import Database
            from select_answer import question_context
            if self.qmeta is None:
                self.qmeta = {q["instance_id"]: q for q in map(json.loads, open(QUESTIONS_FILE))}
            q = self.qmeta[iid]
            if q["db"] not in self.dbs:
                self.dbs[q["db"]] = Database(SQLITE_DIR / f"{q['db']}.sqlite")
            doc, schema = question_context(q, self.dbs[q["db"]])
        self.cache[iid] = (q["question"], doc, schema)
        return self.cache[iid]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evalset", required=True)
    ap.add_argument("--variants", required=True, help="comma-separated names from judge_prompts.VARIANTS")
    ap.add_argument("--select", default="", help="filters, e.g. half=design or half=test|bq;stratum=contested")
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--pools", required=True, help="Spider2 results/pools dir (reference pools)")
    ap.add_argument("--ref-prefix", default="think35/qwen36-35b-think")
    ap.add_argument("--bq-pools", help="bq_passk/pools dir")
    ap.add_argument("--bq-ref-prefix", default="think35_bq")
    ap.add_argument("--bq-base", help="bigquery_passk_nov2026 dir (trace system prompts for the schema)")
    ap.add_argument("--bq-questions")
    ap.add_argument("--comparisons", help="build_compare_cache.py output, for variants with {comparison}")
    ap.add_argument("--judge-endpoint", required=True, help="comma-separated; calls are spread over them")
    ap.add_argument("--judge-model", required=True)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--workers", type=int, default=96)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--limit", type=int, help="only the first N pools (smoke test)")
    ap.add_argument("--dry-run", action="store_true", help="print one prompt per variant and exit")
    ap.add_argument("--count-only", action="store_true", help="print the number of calls left and exit")
    args = ap.parse_args()

    variants = args.variants.split(",")
    for v in variants:
        if v not in VARIANTS:
            raise SystemExit(f"unknown variant {v}; known: {', '.join(VARIANTS)}")
    ev = json.loads(Path(args.evalset).read_text())["pools"]
    filt = [f.split("=") for f in args.select.split(";") if f]
    keys = sorted(k for k, e in ev.items() if e["stratum"] in ("contested", "easy")
                  and all(str(e[name]) in want.split("|") for name, want in filt))
    if args.limit:
        keys = keys[:args.limit]
    ref = load_reference(args.pools, args.ref_prefix, args.bq_pools or "", args.bq_ref_prefix)
    from selection_eval import signature
    for k in keys:
        if json.dumps(signature(ref[k])) != json.dumps(ev[k]["sig"]):
            raise SystemExit(f"{k}: reference pool differs from the eval set")
    ctx = Contexts(args)
    comps = {}
    if any("{comparison}" in VARIANTS[v]["template"] for v in variants):
        if not args.comparisons:
            raise SystemExit("a variant needs --comparisons")
        for r in map(json.loads, open(args.comparisons)):
            comps[(r["key"], r["first"], r["second"])] = r["text"]

    def prompt_for(variant, key, a, b):
        it = ref[key]
        question, doc, schema = ctx.get(key, it)
        ga, gb = it["groups"][a], it["groups"][b]
        spec = VARIANTS[variant]
        fields = dict(question=question, doc_section=doc, schema_section=schema,
                      sql_a=ga["sql"], res_a=ga["preview"], sql_b=gb["sql"], res_b=gb["preview"])
        if "{comparison}" in spec["template"]:
            fields["comparison"] = comps.get((key, a, b), "Comparison unavailable.")
        return spec["template"].format(**fields)

    pairs = []
    for k in keys:
        alive = [a for a, g in enumerate(ev[k]["groups"]) if g[0] > 0]
        pairs += [(k, a, b) for a in alive for b in alive if a != b]
    if args.dry_run:
        shown = set()
        for k, a, b in pairs:  # one Spider2 and one BigQuery prompt per variant
            if k.split(":")[0] in shown:
                continue
            shown.add(k.split(":")[0])
            for v in variants:
                print(f"===== {v} ({k} {a}>{b})\n{prompt_for(v, k, a, b)}\n")
        return

    os.makedirs(args.out_dir, exist_ok=True)
    done = set()
    for v in variants:
        p = Path(args.out_dir) / f"calls_{v}.jsonl"
        if args.resume and p.exists():
            for line in open(p):
                try:
                    r = json.loads(line)
                except ValueError:  # a line cut off when a session was killed
                    continue
                if not r.get("retry"):
                    done.add((v, r["key"], r["first"], r["second"], r["sample"]))
    tasks = [(v, k, a, b, s) for s in range(args.samples) for v in variants for (k, a, b) in pairs
             if (v, k, a, b, s) not in done]
    if args.count_only:
        print(len(tasks))
        return
    print(f"{len(keys)} pools, {len(pairs)} ordered pairs, {len(variants)} variants x {args.samples} samples: "
          f"{len(tasks)} calls to make", flush=True)
    # build every question's context up front (DB schema reads are not thread-safe)
    for k in {t[1] for t in tasks}:
        ctx.get(k, ref[k])

    import openai
    clients = []
    for e in args.judge_endpoint.split(","):  # a port taken by someone else's server must not take calls
        c = openai.OpenAI(base_url=e, api_key="EMPTY", timeout=1800, max_retries=0)
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

    def request(i, prompt):
        """The completion; moves to the next server on connection errors or 5xx, waits up to 2h when all are down."""
        deadline = time.time() + 7200
        while True:
            for j in range(len(clients)):
                client = clients[(i + j) % len(clients)]
                try:
                    return client.chat.completions.create(
                        model=args.judge_model, messages=[{"role": "user", "content": prompt}],
                        temperature=0.6, max_tokens=args.max_tokens, logprobs=True, top_logprobs=5,
                        extra_body={"chat_template_kwargs": {"enable_thinking": True}})
                except (openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError):
                    continue
            if time.time() > deadline:
                raise RuntimeError("all judge servers down for 2h")
            time.sleep(60)

    def call(i, v, k, a, b, s):
        rec = {"key": k, "first": a, "second": b, "sample": s, "variant": v, "verdict": None, "p_first": None,
               "reason": "", "reasoning": "", "completion_tokens": None, "truncated": False, "error": "",
               "retry": False}
        try:
            resp = request(i, prompt_for(v, k, a, b))
            ch = resp.choices[0]
            extra = ch.message.model_dump()
            rec["reasoning"] = (getattr(ch.message, "reasoning", None) or extra.get("reasoning")
                                or extra.get("reasoning_content") or "")
            rec["completion_tokens"] = resp.usage.completion_tokens if resp.usage else None
            rec["truncated"] = ch.finish_reason == "length"
            text = re.sub(r"<think>.*?</think>", "", ch.message.content or "", flags=re.DOTALL)
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if not m:
                raise ValueError(f"no JSON in reply: {text[-120:]!r}")
            data = json.loads(m.group(0))
            verdict = str(data.get("winner", "")).strip().upper()
            if verdict not in ("A", "B"):
                raise ValueError(f"invalid verdict {verdict!r}")
            rec.update(verdict=verdict, p_first=winner_prob(ch.logprobs, ("A", "B")),
                       reason=str(data.get("reason", ""))[:500])
        except Exception as e:
            rec["error"] = str(e)[:200]
            rec["retry"] = isinstance(e, RuntimeError)  # all servers down: make the call again later
        return rec

    outs = {v: open(Path(args.out_dir) / f"calls_{v}.jsonl", "a") for v in variants}
    lock = threading.Lock()
    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(call, i, *t) for i, t in enumerate(tasks)]
        for n, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            with lock:
                outs[r["variant"]].write(json.dumps(r) + "\n")
                outs[r["variant"]].flush()
            if n % 200 == 0:
                print(f"{n}/{len(tasks)} calls, {(time.time() - t0) / 60:.0f} min", flush=True)
    for f in outs.values():
        f.close()


if __name__ == "__main__":
    main()
