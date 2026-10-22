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

# Same task, but the judge must commit to the shape the QUESTION implies before it
# looks at which candidate to pick. Nothing here comes from the gold answer -- the
# expectation is the judge's own reading, so this is deployable, unlike a contract
# built from the gold CSV. Targets the largest failure class in the trace analysis:
# the right computation returned at the wrong grain (16 category rows where the
# question asks for one, the 5 qualifying states where it asks how many).
SHAPE_PROMPT = """You are checking which candidate answer correctly answers a question about a SQL database.

Question:
{question}
{doc}
{n} candidates were produced independently. Each shows its SQL and the first rows of its result.

{candidates}
First decide, from the QUESTION ALONE, what shape a correct answer must have:
- how many rows? "which X has the most Y" or "how many" or "what is the total" means ONE
  row; "for each X" or "list all" means many.
- which columns must appear? Include the identifying columns the question names.
- units: does it ask for a percentage (0-100) or a proportion (0-1)?

Then pick the ONE candidate whose RESULT matches that shape and answers the question.
A candidate that returns a whole ranked table when the question asks for the top one, or
that drops a column the question names, is wrong even if its numbers are right.

Reply with exactly four lines:
EXPECT_ROWS: <1 or many>
EXPECT_COLUMNS: <comma-separated>
CHOICE: <letter>
WHY: <one sentence>"""


# Third variant, written against the error analysis rather than from intuition.
# Four things it adds over PROMPT, each tied to something measured:
#   - names the scorer's actual rule. Extra columns are free and a missing one is
#     fatal, so "has more columns" is never a reason to reject a candidate.
#   - lists the discriminators that actually separated right from wrong in the
#     trace analysis: ranked table vs top row, dropped identity column, fraction
#     vs percentage, raw vs ISO dates, off-by-one row counts.
#   - tells it not to reward elaborate SQL. The judge picks the longest SQL
#     29-30% of the time against 25% by chance, and three worked examples showed
#     it preferring the more thorough-sounding candidate over the correct one.
#   - makes it commit to the expected shape from the question BEFORE looking at
#     the candidates, so the shape is not rationalised from whichever table it
#     already likes.
SCORER_PROMPT = """You are picking which candidate answer a grader would accept for a question \
about a SQL database.

Question:
{question}
{doc}
{n} candidates were produced independently by the same model. Each shows its SQL and the \
first rows of its result.

{candidates}
How the grader works, so you judge the same thing it does:
- It compares the result TABLE against a reference table. It never reads the SQL.
- EXTRA columns are ignored. A MISSING column fails. So a candidate having more \
columns than another is never a reason against it; having fewer is.
- The set of rows must match. One extra or one missing row fails.
- Column names and row order do not matter. Numbers must match to within 0.01.

First, from the QUESTION ALONE, write what a correct table must look like:
- how many rows. "which X has the most Y", "how many", "what is the total" mean ONE row. \
"for each X" means one per X.
- which columns, including the id or name that says what each row is about.
- units and format the question states: a percentage is 0-100, a proportion is 0-1; \
dates as the question or documentation asks.

Then pick the candidate whose RESULT matches that. Things that have actually separated \
right from wrong here:
- a whole ranked table where the question asked for the top one;
- the supporting breakdown where the question asked how many;
- a dropped id or name column, so the rows do not say what they are about;
- a fraction where the question said percentage, or the reverse;
- a row count one off, from an inclusive/exclusive boundary.

Do not reward effort. Longer SQL, more CTEs, more joins and a more thorough-looking \
query are not evidence of correctness; several candidates may be near-identical. Judge \
only the table.

Reply with exactly four lines:
EXPECT_ROWS: <1, N, or one per X>
EXPECT_COLUMNS: <comma-separated>
CHOICE: <letter>
WHY: <one sentence naming the table fact that decided it>"""


def reasoning_block(c, mode, chars):
    """Optional: what the agent said while producing this candidate."""
    r = c.get("reasoning") or {}
    if mode == "none" or not r:
        return ""
    if mode == "short":
        bits = []
        if r.get("summary"):
            bits.append(f"Its own summary of the answer: {r['summary']}")
        if r.get("last_messages"):
            bits.append("Its last words before finishing: " + " ".join(r["last_messages"]))
        text = "\n".join(bits)
    elif mode == "full":
        text = "Its narration while working:\n" + (r.get("narration") or "")
    elif mode == "thinking_summary":
        text = ("Why it made its choices, and what it checked versus assumed:\n"
                + (r.get("summary_of_thinking") or ""))
    elif mode == "thinking":
        text = "Its reasoning while working:\n" + (r.get("thinking") or "")
    else:   # thinking_last
        text = "Its reasoning on its final steps:\n" + (r.get("thinking_last") or "")
    return ("\n" + text[:chars] + "\n") if text else ""


def build(item, sql_chars, prev_chars, doc_chars, reasoning="none",
          reasoning_chars=2500, prompt_kind="base"):
    parts = []
    for c in item["candidates"]:
        if c["error"]:
            body = f"Result: this SQL fails to run ({c['error']})"
        else:
            body = (f"Result: {c['shape'][0]} rows x {c['shape'][1]} columns\n"
                    f"{c['preview'][:prev_chars]}")
        parts.append(f"[{c['label']}]\nSQL:\n{c['sql'][:sql_chars]}\n{body}\n"
                     + reasoning_block(c, reasoning, reasoning_chars))
    doc = f"\nDocumentation provided with the question:\n{item['doc'][:doc_chars]}\n" if item["doc"] else ""
    tmpl = {"shape": SHAPE_PROMPT, "scorer": SCORER_PROMPT}.get(prompt_kind, PROMPT)
    return tmpl.format(question=item["question"], doc=doc,
                       n=len(item["candidates"]), candidates="\n".join(parts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", default="validator_inputs.json")
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trace-dir")
    ap.add_argument("--prompt", dest="prompt_kind", default="base",
                    choices=["base", "shape", "scorer"],
                    help="base: judge the result; shape: state the expected shape first; "
                         "scorer: shape first, plus the grader's actual rule and the "
                         "discriminators from the trace analysis")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=300)
    ap.add_argument("--sql-chars", type=int, default=1500)
    ap.add_argument("--preview-chars", type=int, default=1200)
    ap.add_argument("--doc-chars", type=int, default=3000)
    ap.add_argument("--reasoning",
                    choices=["none", "short", "full", "thinking", "thinking_last",
                             "thinking_summary"],
                    default="none",
                    help="also show what each agent said while producing its candidate: "
                         "short = its own summary plus its last words; full = its whole narration. "
                         "Self-reported and sometimes confidently wrong.")
    ap.add_argument("--reasoning-chars", type=int, default=2500)
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
        prompt = build(item, args.sql_chars, args.preview_chars, args.doc_chars,
                       args.reasoning, args.reasoning_chars, prompt_kind=args.prompt_kind)
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
