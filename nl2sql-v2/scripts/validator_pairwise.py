#!/usr/bin/env python3
"""Pick one of K candidates by a pairwise tournament instead of one K-way choice.

Two problems with the K-way judge, both measured on the q36rg pool:

  position bias  it picked candidate A on 44-53% of questions although order is
                 shuffled, and "always pick A" scores 69/135 against the judge's
                 72-76. Much of what looked like judging was primacy.
  hard buckets   where exactly one of four candidates is correct it scored 5-6 of
                 17 against 4.2 by chance, i.e. at chance.

A tournament addresses both. Every unordered pair is judged TWICE, once in each
order, and a candidate takes the pair only if it wins both ways; a disagreement
between the two orders is scored as a tie and recorded. Position bias therefore
cannot favour anyone, and it becomes measurable: the share of pairs where the two
orders disagree is a direct read on how much the judge is answering from position.

Ties on the Copeland score fall back to execution consistency -- the largest group
of candidates returning identical tables -- which is the one signal here that needs
no model call.

Usage (from nl2sql-v2/):
    uv run python scripts/validator_pairwise.py --endpoint http://localhost:PORT/v1 \
        --model MODEL --inputs validator_inputs_rg.json --out ../results/pw.csv
"""

import argparse
import csv
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations, permutations
from pathlib import Path

from openai import OpenAI

PAIR_PROMPT = """Two candidate answers to the same question about a SQL database. \
Each was produced independently; each shows its SQL and the first rows of its result.

Question:
{question}
{doc}
[1]
SQL:
{sql1}
Result: {shape1}
{prev1}

[2]
SQL:
{sql2}
Result: {shape2}
{prev2}

The answer is graded by comparing the result TABLE with a reference table. The grader \
never reads the SQL. Extra columns are ignored; a missing column fails. The set of rows \
must match. Column names and row order do not matter.

Decide from the QUESTION what a correct table must look like -- how many rows, which \
columns, what units -- then say which result is closer to it. Longer or more elaborate \
SQL is not evidence; judge the table.

Reply with exactly two lines:
BETTER: 1 or 2
WHY: <one sentence naming the table fact that decided it>"""


def block(c, sql_chars, prev_chars):
    if c["error"]:
        return c["sql"][:sql_chars], "this SQL fails to run", f"({c['error']})"
    return (c["sql"][:sql_chars],
            f"{c['shape'][0]} rows x {c['shape'][1]} columns",
            c["preview"][:prev_chars])


def ask(client, model, item, a, b, args):
    """Which of two candidates is better, as the judge sees them in this order."""
    s1, sh1, p1 = block(a, args.sql_chars, args.preview_chars)
    s2, sh2, p2 = block(b, args.sql_chars, args.preview_chars)
    doc = (f"\nDocumentation provided with the question:\n{item['doc'][:args.doc_chars]}\n"
           if item["doc"] else "")
    prompt = PAIR_PROMPT.format(question=item["question"], doc=doc,
                                sql1=s1, shape1=sh1, prev1=p1,
                                sql2=s2, shape2=sh2, prev2=p2)
    try:
        r = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}],
            temperature=args.temperature, max_tokens=args.max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        text = r.choices[0].message.content or ""
    except Exception as e:
        return None, f"ERROR: {e}"
    m = re.search(r"BETTER:\s*\[?([12])", text) or re.search(r"\b([12])\b", text)
    return (int(m.group(1)) if m else None), text


def result_sig(c):
    """Identical tables group together, so ties can fall back to agreement."""
    return hashlib.sha256((c.get("preview") or "").strip().encode()).hexdigest()[:16]


def judge_question(client, model, iid, item, args):
    cands = item["candidates"]
    n = len(cands)
    wins = [0] * n
    pairs_judged = disagreed = unparsed = 0
    log = []
    for i, j in combinations(range(n), 2):
        verdicts = {}
        for first, second in permutations((i, j)):
            pick, text = ask(client, model, item, cands[first], cands[second], args)
            # the reply says 1 or 2 by position; map it back to the candidate
            verdicts[(first, second)] = (first if pick == 1 else
                                         second if pick == 2 else None)
            if pick is None:
                unparsed += 1
            log.append({"pair": [first, second], "winner": verdicts[(first, second)],
                        "reply": text[:200]})
        pairs_judged += 1
        a, b = verdicts[(i, j)], verdicts[(j, i)]
        if a is not None and a == b:          # same winner in both orders
            wins[a] += 1
        else:
            disagreed += 1                    # order flipped the verdict: a tie
    best = max(wins)
    tied = [k for k in range(n) if wins[k] == best]
    if len(tied) > 1:
        # fall back to execution consistency: the largest identical-result group
        groups = {}
        for k in tied:
            groups.setdefault(result_sig(cands[k]), []).append(k)
        tied = max(groups.values(), key=len)
    chosen = tied[0]
    return {"instance_id": iid, "picked": cands[chosen]["label"],
            "picked_run": cands[chosen]["run"],
            "picked_correct": bool(cands[chosen]["correct"]),
            "wins": wins, "pairs": pairs_judged, "order_disagreements": disagreed,
            "unparsed": unparsed,
            "n_correct_available": sum(bool(c["correct"]) for c in cands),
            "n_candidates": n, "log": log}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", default="validator_inputs_rg.json")
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trace-dir")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=200)
    ap.add_argument("--sql-chars", type=int, default=1500)
    ap.add_argument("--preview-chars", type=int, default=1200)
    ap.add_argument("--doc-chars", type=int, default=3000)
    args = ap.parse_args()

    data = json.loads(Path(args.inputs).read_text())
    client = OpenAI(base_url=args.endpoint, api_key="EMPTY")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(
            lambda kv: judge_question(client, args.model, kv[0], kv[1], args),
            sorted(data.items())))

    n = len(rows)
    sel = sum(r["picked_correct"] for r in rows)
    ceiling = sum(1 for r in rows if r["n_correct_available"])
    rand = sum(r["n_correct_available"] / r["n_candidates"] for r in rows)
    dis = sum(r["order_disagreements"] for r in rows)
    tot = sum(r["pairs"] for r in rows)
    print(f"\npairwise tournament: {args.model}")
    print(f"  questions                      : {n}")
    print(f"  picked a correct answer        : {sel}/{n} ({sel/n:.1%})")
    print(f"  picking at random would give   : {rand:.1f}/{n} ({rand/n:.1%})")
    print(f"  perfect selection would give   : {ceiling}/{n} ({ceiling/n:.1%})")
    print(f"  share of the headroom captured : {(sel-rand)/(ceiling-rand):.0%}")
    print(f"\n  pairs judged (both orders each): {tot}")
    print(f"  order flipped the verdict      : {dis}/{tot} ({dis/tot:.0%})"
          f"   <- direct read on position bias")
    print(f"  unparsed replies               : {sum(r['unparsed'] for r in rows)}")
    dec = [r for r in rows if 0 < r["n_correct_available"] < r["n_candidates"]]
    print(f"\n  on the {len(dec)} decidable questions: "
          f"{sum(r['picked_correct'] for r in dec)}/{len(dec)}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["instance_id", "picked", "picked_run",
                                          "picked_correct", "wins", "pairs",
                                          "order_disagreements", "unparsed",
                                          "n_correct_available", "n_candidates"])
        w.writeheader()
        for r in rows:
            w.writerow({k: v for k, v in r.items() if k != "log"})
    print(f"\nwrote {args.out}")
    if args.trace_dir:
        d = Path(args.trace_dir); d.mkdir(parents=True, exist_ok=True)
        for r in rows:
            (d / f"{r['instance_id']}.json").write_text(json.dumps(r, indent=1))


if __name__ == "__main__":
    main()
