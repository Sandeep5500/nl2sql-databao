#!/usr/bin/env python3
"""Condense each candidate's REASONING so a validator can see all of it.

Keeps why each choice was made -- the observation or reading behind it, and
whether the candidate verified it in the data or assumed it -- rather than a
flat list of decisions. Provenance is the discriminating signal: a candidate
that checked the data before choosing differs from one that guessed, even when
both state the same decision.

Dumping raw reasoning does not fit: four candidates run to ~102k tokens at the
worst question, and truncating to a budget showed the judge only the opening
schema exploration (26% of it at the median). This asks a model to state the
DECISIONS each candidate made, in a few lines.

It must not judge correctness -- that would make it a second validator and the
comparison meaningless. It only reports what the candidate decided to do.

Reads the reasoning tail, where the decisive steps are. Writes a copy of the
inputs file with `reasoning.summary_of_thinking` added per candidate.

Usage (from nl2sql-v2/):
    uv run python scripts/summarize_reasoning.py --endpoint http://localhost:8765/v1 \
        --model Qwen/Qwen3.5-9B --inputs validator_inputs_think.json \
        --out validator_inputs_think_sum.json
"""

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

PROMPT = """An agent wrote a SQL query to answer the question below. Here is its reasoning while working.

Question:
{question}

Its reasoning:
{reasoning}

Summarise WHY it made its choices, not just what it chose. At most 6 bullets, under 150 words:
- for each important choice, what it saw in the data or read in the question that led to it
- mark each as CHECKED if it verified that in the data (sampled rows, counts, a test query),
  or ASSUMED if it did not
- where the question was ambiguous, the reading it settled on and the reason it gave
- anything it tried and abandoned, and why it abandoned it
- anything it remained unsure about

Report its reasoning as it gave it. Do NOT say whether the query or its answer is correct, and do
not add reasoning of your own. Start each bullet with "- "."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", default="validator_inputs_think.json")
    ap.add_argument("--out", default="validator_inputs_think_sum.json")
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-input-chars", type=int, default=30000,
                    help="how much of the reasoning TAIL to summarise")
    ap.add_argument("--max-tokens", type=int, default=320)
    args = ap.parse_args()

    data = json.loads(Path(args.inputs).read_text())
    client = OpenAI(base_url=args.endpoint, api_key="EMPTY", timeout=600)
    extra = ({"chat_template_kwargs": {"enable_thinking": False}}
             if "qwen" in args.model.lower() else None)

    jobs = [(iid, k) for iid, v in data.items() for k, c in enumerate(v["candidates"])
            if (c.get("reasoning") or {}).get("thinking")]

    def one(job):
        iid, k = job
        c = data[iid]["candidates"][k]
        text = c["reasoning"]["thinking"][-args.max_input_chars:]
        try:
            r = client.chat.completions.create(
                model=args.model, max_tokens=args.max_tokens, temperature=0.0,
                messages=[{"role": "user", "content": PROMPT.format(
                    question=data[iid]["question"], reasoning=text)}],
                extra_body=extra)
            out = (r.choices[0].message.content or "").strip()
        except Exception as e:
            out = f"[summary unavailable: {type(e).__name__}]"
        return iid, k, re.sub(r"\n{3,}", "\n", out)

    print(f"summarising {len(jobs)} candidate reasonings with {args.workers} workers ...")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for iid, k, out in pool.map(one, jobs):
            data[iid]["candidates"][k]["reasoning"]["summary_of_thinking"] = out

    Path(args.out).write_text(json.dumps(data, indent=1))
    lens = [len(c["reasoning"].get("summary_of_thinking", ""))
            for v in data.values() for c in v["candidates"]]
    lens.sort()
    print(f"wrote {args.out}")
    print(f"summary length: median {lens[len(lens)//2]} chars, max {lens[-1]}  "
          f"(raw reasoning was 9,000-79,000 per candidate)")


if __name__ == "__main__":
    main()
