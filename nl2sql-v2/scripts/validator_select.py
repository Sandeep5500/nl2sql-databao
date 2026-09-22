#!/usr/bin/env python3
"""Validator agent: show a model the question and the pass@4 candidate answers,
and have it pick one. Scores the pick against what we already know.

Reads validator_inputs.json (built by scripts/analysis/build_validator_inputs.py),
so every model sees byte-identical prompts and nothing is re-executed. Candidate
order is already shuffled per question; whether a candidate is correct is stored
there for scoring and is never shown to the model.

Usage (from nl2sql-v2/):
    uv run python scripts/validator_select.py --endpoint http://node:8765/v1 \
        --model Qwen/Qwen3.5-9B --out ../results/validator_9b.csv --workers 8
"""

import argparse
import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

PROMPT = """You are checking which candidate answer correctly answers a question about a SQL database.

Question:
{question}
{doc}
{n} candidates were produced independently. Each shows its SQL and the first rows of its result.

{candidates}
Pick the ONE candidate whose RESULT correctly answers the question. Judge the result, not the style:
- are the columns the ones the question asks for, and no fewer?
- is the grain right (one row per what the question asks about)?
- are filters, units, rounding and ordering as the question states?
- are the values plausible for the question?

Reply with exactly two lines:
CHOICE: <letter>
WHY: <one sentence>"""


def build(item, sql_chars, prev_chars, doc_chars):
    parts = []
    for c in item["candidates"]:
        if c["error"]:
            body = f"Result: this SQL fails to run ({c['error']})"
        else:
            body = (f"Result: {c['shape'][0]} rows x {c['shape'][1]} columns\n"
                    f"{c['preview'][:prev_chars]}")
        parts.append(f"[{c['label']}]\nSQL:\n{c['sql'][:sql_chars]}\n{body}\n")
    doc = f"\nDocumentation provided with the question:\n{item['doc'][:doc_chars]}\n" if item["doc"] else ""
    return PROMPT.format(question=item["question"], doc=doc,
                         n=len(item["candidates"]), candidates="\n".join(parts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", default="validator_inputs.json")
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trace-dir")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=300)
    ap.add_argument("--sql-chars", type=int, default=1500)
    ap.add_argument("--preview-chars", type=int, default=1200)
    ap.add_argument("--doc-chars", type=int, default=3000)
    ap.add_argument("--thinking", action="store_true")
    args = ap.parse_args()

    data = json.loads(Path(args.inputs).read_text())
    client = OpenAI(base_url=args.endpoint, api_key="EMPTY", timeout=300)
    extra = ({} if args.thinking or "qwen" not in args.model.lower()
             else {"chat_template_kwargs": {"enable_thinking": False}})
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    if trace_dir:
        trace_dir.mkdir(parents=True, exist_ok=True)

    def one(iid):
        item = data[iid]
        prompt = build(item, args.sql_chars, args.preview_chars, args.doc_chars)
        try:
            r = client.chat.completions.create(
                model=args.model, messages=[{"role": "user", "content": prompt}],
                temperature=args.temperature, max_tokens=args.max_tokens,
                extra_body=extra or None)
            text = r.choices[0].message.content or ""
        except Exception as e:
            text = f"ERROR {type(e).__name__}: {e}"
        m = re.search(r"CHOICE:\s*\[?([A-H])\b", text) or re.search(r"\b([A-H])\b", text)
        labels = [c["label"] for c in item["candidates"]]
        pick = m.group(1) if m and m.group(1) in labels else labels[0]
        chosen = next(c for c in item["candidates"] if c["label"] == pick)
        if trace_dir:
            (trace_dir / f"{iid}.json").write_text(json.dumps(
                {"instance_id": iid, "prompt": prompt, "reply": text,
                 "picked": pick, "picked_run": chosen["run"]}, indent=1))
        return {"instance_id": iid, "picked": pick, "picked_run": chosen["run"],
                "picked_correct": int(chosen["correct"]),
                "parsed": int(bool(m)),
                "n_candidates": len(item["candidates"]),
                "n_correct_available": sum(c["correct"] for c in item["candidates"]),
                "why": re.sub(r"\s+", " ", text)[:300]}

    ids = sorted(data)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(one, ids))

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

    n = len(rows)
    sel = sum(r["picked_correct"] for r in rows)
    ceiling = sum(1 for r in rows if r["n_correct_available"] > 0)
    avg = sum(r["n_correct_available"] / r["n_candidates"] for r in rows)
    dec = [r for r in rows if 0 < r["n_correct_available"] < r["n_candidates"]]
    dsel = sum(r["picked_correct"] for r in dec)
    davg = sum(r["n_correct_available"] / r["n_candidates"] for r in dec)
    print(f"\nvalidator: {args.model}")
    print(f"  questions                         : {n}   (replies parsed: {sum(r['parsed'] for r in rows)})")
    print(f"  picked a correct answer           : {sel}/{n} ({sel/n:.1%})")
    print(f"  picking at random would give      : {avg:.1f}/{n} ({avg/n:.1%})")
    print(f"  perfect selection would give      : {ceiling}/{n} ({ceiling/n:.1%})")
    print(f"  share of the headroom captured    : {(sel-avg)/(ceiling-avg):.0%}")
    print(f"\n  on the {len(dec)} decidable questions (some right, some wrong):")
    print(f"     picked correct                 : {dsel}/{len(dec)} ({dsel/len(dec):.1%})")
    print(f"     random would give              : {davg:.1f}/{len(dec)} ({davg/len(dec):.1%})")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
