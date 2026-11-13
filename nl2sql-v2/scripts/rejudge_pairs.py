#!/usr/bin/env python3
"""Re-judge chosen right-vs-wrong ordered pairs several times with one judge, keeping the
full reasoning, to compare judges pair by pair (a single sample per order cannot tell a
changed judgment from sampling noise).

Two sources of pairs, both judged with the deployed prompt (select_answer.PAIRWISE_PROMPT,
thinking at temperature 0.6, as sample_judge_verdicts.py and judge_pools.py send it):
  --verdicts  a sample_judge_verdicts.py output: its stored prompts, chosen by how often the
              judge that produced it was right (--select never,mixed,always[:N])
  --pairs     a JSON list of {"pool", "instance_id", "first", "second"} for judge_pools.py
              outputs in --pools-dir (<prefix>_<pool>_n12_s*.jsonl); the prompt is rebuilt
              from the stored candidates and the question (Spider2 config)

--rationalize (STaR): the prompt ends with a note naming the correct candidate and asking
the judge to reason to it on its own; a sample whose reasoning or answer leans on the note
(LEAK) is marked leaked and not right. make_judge_sft_dpo.py --rationales trains on the
kept ones with the original prompt, without the note.

Output: one JSON line per call (resumable): pair id, sample index, verdict, right,
answer, full reasoning, completion tokens, truncated.

Usage (from nl2sql-v2/):
    python scripts/rejudge_pairs.py --verdicts verdicts_train_v1.jsonl --select never,mixed,always:150 \\
        --judge-endpoint http://localhost:8766/v1 --judge-model judge-tuned-v1 --samples 4 \\
        --output rejudge_train_tuned.jsonl --resume
"""

import argparse
import glob
import json
import random
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


HINT = ("\n\n[Reviewer's note: Candidate {letter} has been verified as the correct answer. Work out "
        "from the question, schema and results above why it is correct and the other candidate is not, "
        "and answer in the required format. Your reasoning must stand on its own: do not mention or "
        "rely on this note.]")
LEAK = re.compile(r"reviewer|verified|the note|this note|we(?:'re| are) told|i(?:'m| am) told|been told|"
                  r"\bhint|given that candidate|stated (?:to be )?correct", re.I)


def verdict_of(text):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        v = str(json.loads(m.group(0)).get("winner", "")).strip().upper() if m else ""
    except Exception:
        v = ""
    return v if v in ("A", "B") else None


def from_verdicts(path, select, seed=0):
    """(pair id, prompt, correct letter, stored samples' right count) for the chosen pairs."""
    want = {}
    for s in select.split(","):
        name, _, n = s.partition(":")
        want[name] = int(n) if n else None
    found = {"never": [], "mixed": [], "always": []}
    for line in (l for p in path.split(",") for l in open(p)):
        r = json.loads(line)
        for pi, p in enumerate(r["pairs"]):
            usable = [s for s in p["samples"] if not s["error"]]
            if not usable:
                continue
            k = sum(s["right"] for s in usable)
            kind = "never" if k == 0 else "always" if k == len(usable) else "mixed"
            found[kind].append({"id": f"{r['instance_id']}#{pi}", "prompt": p["prompt"],
                                "correct_letter": p["correct_letter"], "kind": kind,
                                "source": r.get("source"), "ref_right": k, "ref_n": len(usable)})
    out = []
    for kind, n in want.items():
        items = found[kind]
        if n is not None and n < len(items):
            items = random.Random(seed).sample(items, n)
        out += items
    return out


def from_pools(pairs_file, pools_dir, prefix):
    from nl2sql.config import QUESTIONS_FILE, SQLITE_DIR
    from nl2sql.db import Database
    from select_answer import PAIRWISE_PROMPT, question_context
    qmeta = {q["instance_id"]: q for q in map(json.loads, open(QUESTIONS_FILE))}
    items = {}
    for f in glob.glob(f"{pools_dir}/{prefix}_*_n12_s*.jsonl"):
        pool = f.split("_n12_")[0].rsplit("_", 1)[1]
        for line in open(f):
            it = json.loads(line)
            items[(pool, it["instance_id"])] = it
    out, dbs, ctx = [], {}, {}
    for p in json.load(open(pairs_file)):
        it = items[(p["pool"], p["instance_id"])]
        q = qmeta[p["instance_id"]]
        if q["instance_id"] not in ctx:
            if q["db"] not in dbs:
                dbs[q["db"]] = Database(SQLITE_DIR / f"{q['db']}.sqlite")
            ctx[q["instance_id"]] = question_context(q, dbs[q["db"]])
        doc, schema = ctx[q["instance_id"]]
        gf, gs = it["groups"][p["first"]], it["groups"][p["second"]]
        if bool(gf["correct"]) == bool(gs["correct"]):
            raise SystemExit(f"{p}: not a right-vs-wrong pair")
        prompt = PAIRWISE_PROMPT.format(question=q["question"], doc_section=doc, schema_section=schema,
                                        sql_a=gf["sql"], res_a=gf["preview"], sql_b=gs["sql"], res_b=gs["preview"])
        out.append({"id": f"{p['pool']}:{p['instance_id']}:{p['first']}>{p['second']}", "prompt": prompt,
                    "correct_letter": "A" if gf["correct"] else "B", "kind": "spider2"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", help="comma-separated")
    ap.add_argument("--select", default="never,mixed,always:150")
    ap.add_argument("--pairs")
    ap.add_argument("--pools-dir")
    ap.add_argument("--pool-prefix", default="think35/qwen36-35b-think")
    ap.add_argument("--judge-endpoint", required=True, help="comma-separated; calls are spread over them")
    ap.add_argument("--judge-model", required=True)
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--workers", type=int, default=96)
    ap.add_argument("--output", required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--rationalize", action="store_true", help="STaR: tell the judge the answer")
    ap.add_argument("--limit", type=int, help="only the first N pairs (smoke test)")
    ap.add_argument("--no-thinking", action="store_true",
                    help="judge with thinking off, as judge_pools.py without --thinking (temperature 0.2): "
                         "p_right is P(correct letter) read at the winner token, and right means p_right > 0.5")
    args = ap.parse_args()

    pairs = (from_verdicts(args.verdicts, args.select) if args.verdicts
             else from_pools(args.pairs, args.pools_dir, args.pool_prefix))
    if args.limit:
        pairs = pairs[:args.limit]
    done = set()
    if args.resume and Path(args.output).exists():
        done = {(r["id"], r["sample"]) for r in map(json.loads, open(args.output)) if not r["error"]}
    tasks = [(p, s) for p in pairs for s in range(args.samples) if (p["id"], s) not in done]
    print(f"{len(pairs)} pairs, {len(tasks)} calls to make", flush=True)

    import openai
    clients = [openai.OpenAI(base_url=e, api_key="EMPTY", timeout=1800) for e in args.judge_endpoint.split(",")]

    def call(i, p, s):
        client = clients[i % len(clients)]
        rec = {"id": p["id"], "sample": s, "kind": p["kind"], "judge_model": args.judge_model,
               **{k: p[k] for k in ("source", "ref_right", "ref_n") if k in p}}
        prompt = p["prompt"] + (HINT.format(letter=p["correct_letter"]) if args.rationalize else "")
        try:
            think = not args.no_thinking
            resp = client.chat.completions.create(
                model=args.judge_model, messages=[{"role": "user", "content": prompt}],
                temperature=0.6 if think else 0.2, max_tokens=args.max_tokens,
                logprobs=None if think else True, top_logprobs=None if think else 5,
                extra_body={"chat_template_kwargs": {"enable_thinking": think}})
            ch = resp.choices[0]
            extra = ch.message.model_dump()
            reasoning = (getattr(ch.message, "reasoning", None) or extra.get("reasoning")
                         or extra.get("reasoning_content") or "")
            text = re.sub(r"<think>.*?</think>", "", ch.message.content or "", flags=re.DOTALL)
            v = verdict_of(text)
            rec.update(verdict=v, right=v == p["correct_letter"], answer=text.strip(), reasoning=reasoning,
                       completion_tokens=resp.usage.completion_tokens if resp.usage else None,
                       truncated=ch.finish_reason == "length", error="")
            if not think:
                from select_answer import winner_prob
                pa = winner_prob(ch.logprobs, ("A", "B"))
                rec["p_right"] = None if pa is None else (pa if p["correct_letter"] == "A" else 1 - pa)
                if rec["p_right"] is not None:
                    rec["right"] = rec["p_right"] > 0.5
            if args.rationalize:
                rec["rationalized"] = True
                rec["leaked"] = bool(LEAK.search(reasoning + "\n" + text))
                rec["right"] = rec["right"] and not rec["leaked"]
        except Exception as e:
            rec.update(verdict=None, right=False, answer="", reasoning="", completion_tokens=None,
                       truncated=False, error=str(e)[:200])
        return rec

    lock = threading.Lock()
    with open(args.output, "a") as out, ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(call, i, p, s) for i, (p, s) in enumerate(tasks)]
        for n, fut in enumerate(as_completed(futs), 1):
            with lock:
                out.write(json.dumps(fut.result()) + "\n")
                out.flush()
            if n % 100 == 0:
                print(f"{n}/{len(tasks)}", flush=True)


if __name__ == "__main__":
    main()
