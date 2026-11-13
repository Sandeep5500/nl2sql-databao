#!/usr/bin/env python3
"""Is the "wrong" side of a judge-training pair really wrong, or a second reading of the question?

On the complex-question pilot, about half of the pairs the untuned judge never got right were
label problems, not judge errors: the agent's answer followed a reading the question allows
(ratio vs percent, all students vs students who teach, one row per officer vs per incident),
and only the gold's reading is scored right. A blind solve that happens to match the gold does
not rule that out.

Per unordered right-vs-wrong pair (from sample_judge_verdicts.py outputs), a model is shown the
question, the reference (scored-right) query and the other one, and must quote the words of the
question that the other query contradicts, or answer that the question allows both. A quote that
is not in the question counts as no quote. Several samples per pair; the pair is "wrong" (label
kept) when most samples quote words that are in the question.

Usage (from nl2sql-v2/):
    python scripts/check_pair_labels.py --verdicts verdicts_cplx_v1.jsonl[,more.jsonl] \\
        --endpoint http://host:8765/v1[,http://host:8766/v1] --model <model> --thinking \\
        --samples 3 --output pair_labels.jsonl [--resume] [--only never]
"""

import argparse
import json
import re
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import select_answer
from analyze_judge_gap import split_prompt
from select_answer import ask_json

PROMPT = """Below are a business question over a database and two SQL queries with their results. \
The reference query is scored as the correct answer. Decide whether the other query is wrong, \
or whether it follows another reasonable reading of the question as written.

The other query is wrong only if it contradicts something the question states: a filter, a \
grouping, a unit, a tie rule, a row count, an output column, an ordering. Differences the \
question does not settle (for example ratio vs percent when the question does not say, or one \
row per officer vs one row per incident when it does not say which) make it another reading.

Question: {question}

Reference query:
{sql_ref}
Reference result:
{res_ref}

Other query:
{sql_other}
Other result:
{res_other}

Reply with JSON only: {{"quote": "<the exact words of the question that the other query \
contradicts, or empty>", "verdict": "wrong" or "other_reading", "reason": "<one sentence>"}}"""


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def pairs_of(paths, only):
    """Unordered pairs; the judge's samples from both presentation orders are pooled."""
    pairs = {}
    for path in paths:
        for line in open(path):
            r = json.loads(line)
            for pi, p in enumerate(r["pairs"]):
                s = [x for x in p["samples"] if not x.get("error")]
                if not s:
                    continue
                q, _, _, a, b = split_prompt(p["prompt"])
                ref, other = (a, b) if p["correct_letter"] == "A" else (b, a)
                rec = pairs.setdefault((r["instance_id"], ref[0], other[0]), {
                    "id": f"{r['instance_id']}#{pi}", "instance_id": r["instance_id"],
                    "source": r.get("source"), "right": 0, "n": 0,
                    "question": q, "ref": ref, "other": other})
                rec["right"] += sum(x["right"] for x in s)
                rec["n"] += len(s)
    out = []
    for rec in pairs.values():
        k, n = rec.pop("right"), rec.pop("n")
        rec.update(kind="never" if k == 0 else "always" if k == n else "mixed", judge_right=k / n)
        if not only or rec["kind"] in only:
            out.append(rec)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", required=True, help="comma-separated sample_judge_verdicts.py outputs")
    ap.add_argument("--endpoint", required=True, help="comma-separated; calls are spread over them")
    ap.add_argument("--model", required=True)
    ap.add_argument("--thinking", action="store_true")
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--only", help="comma-separated pair kinds: never,mixed,always")
    ap.add_argument("--output", required=True)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    select_answer.THINKING = args.thinking

    from openai import OpenAI
    clients = [OpenAI(base_url=e, api_key="EMPTY", timeout=1800) for e in args.endpoint.split(",")]
    pairs = pairs_of(args.verdicts.split(","), set(args.only.split(",")) if args.only else None)
    done = set()
    if args.resume and Path(args.output).exists():
        done = {json.loads(l)["id"] for l in open(args.output)}
    todo = [p for p in pairs if p["id"] not in done]
    print(f"{len(pairs)} pairs, {len(todo)} to check", flush=True)

    def check(i, p):
        prompt = PROMPT.format(question=p["question"], sql_ref=p["ref"][0], res_ref=p["ref"][1],
                               sql_other=p["other"][0], res_other=p["other"][1])
        samples = []
        for j in range(args.samples):
            try:
                d = ask_json(clients[(i + j) % len(clients)], args.model, prompt,
                             args.temperature, args.max_tokens)
                quote = str(d.get("quote") or "").strip()
                verdict = str(d.get("verdict") or "").strip()
                # a "wrong" verdict needs words that are in the question
                quoted = bool(quote) and norm(quote) in norm(p["question"])
                samples.append({"verdict": verdict, "quote": quote, "quoted": quoted,
                                "reason": str(d.get("reason") or "")})
            except Exception as e:
                samples.append({"error": str(e)[:200]})
        ok = [s for s in samples if "error" not in s]
        wrong = sum(s["verdict"] == "wrong" and s["quoted"] for s in ok)
        label = "unknown" if not ok else "wrong" if wrong > len(ok) / 2 else "other_reading"
        return {k: v for k, v in p.items() if k not in ("ref", "other")} | {
            "label": label, "wrong_votes": wrong, "n": len(ok), "samples": samples}

    lock, n, tally = threading.Lock(), 0, Counter()
    with ThreadPoolExecutor(args.workers) as pool, open(args.output, "a") as fh:
        for fut in as_completed([pool.submit(check, i, p) for i, p in enumerate(todo)]):
            rec = fut.result()
            with lock:
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                n += 1
                tally[(rec["source"], rec["kind"], rec["label"])] += 1
                if n % 25 == 0:
                    print(f"{n}/{len(todo)}", flush=True)
    for k, v in sorted(tally.items()):
        print(k, v)


if __name__ == "__main__":
    main()
