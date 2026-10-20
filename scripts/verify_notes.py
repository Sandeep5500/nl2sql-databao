#!/usr/bin/env python3
"""Second pass over scripts/explore_notes.py output: for each note, a model is
shown only the note, the SQL it cites and that query's result, and judges
whether the result actually shows the claim. Notes that are not supported are
marked and left out of describe_table.

Usage (from repo root):
    uv run --project nl2sql-v2 python scripts/verify_notes.py \
        --datasources f1,ipl --endpoint http://<node>:<port>/v1 --model <model>
"""

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nl2sql-v2/src"))
from openai import OpenAI  # noqa: E402

from nl2sql.config import DCE_PROJECT_DIR  # noqa: E402

PROMPT = """A note about a database table cites one SQL query as its evidence. Judge \
only whether that query's result shows what the note claims. Do not use outside \
knowledge about what the data probably means.

Table: {table}
Note{column}: {note}

Cited query:
{sql}

Its result:
{result}

Answer one of:
- "yes": the result directly shows every factual claim in the note.
- "partly": the result shows part of the note, but the note also asserts something the \
result does not show (a meaning, a cause, a count, how SQL will behave).
- "no": the result is about something else, or contradicts the note.

Reply with JSON only: {{"verdict": "yes" | "partly" | "no", "unsupported": "<the part \
of the note the result does not show, or ''>"}}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasources", required=True)
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--notes-dir", default=str(DCE_PROJECT_DIR / "output" / "notes"))
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    client = OpenAI(base_url=args.endpoint, api_key="EMPTY", timeout=300)
    extra = ({"chat_template_kwargs": {"enable_thinking": False}}
             if "qwen" in args.model.lower() else None)

    def judge(job):
        table, col, item, q = job
        if not q:
            item["verdict"] = "no"
            item["unsupported"] = "cites no query"
            return
        try:
            resp = client.chat.completions.create(
                model=args.model, temperature=0.0, max_tokens=300, extra_body=extra,
                messages=[{"role": "user", "content": PROMPT.format(
                    table=table, column=f" on column {col}" if col else "",
                    note=item.get("note", ""), sql=q.get("sql", "")[:2000],
                    result=q.get("result", "")[:1500])}])
            m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.DOTALL)
            ans = json.loads(m.group(0)) if m else {}
            item["verdict"] = str(ans.get("verdict", "no")).lower()
            item["unsupported"] = str(ans.get("unsupported", ""))[:300]
        except Exception as e:
            item["verdict_error"] = str(e)[:150]

    for stem in args.datasources.split(","):
        path = Path(args.notes_dir) / f"{stem}.json"
        doc = json.loads(path.read_text())
        jobs = []
        for t, r in doc["tables"].items():
            qs = r.get("queries") or {}
            for x in r.get("column_notes") or []:
                jobs.append((t, x.get("column"), x, qs.get(x.get("query_id"))))
            for x in r.get("pitfalls") or []:
                jobs.append((t, None, x, qs.get(x.get("query_id"))))
        with ThreadPoolExecutor(args.workers) as ex:
            list(ex.map(judge, jobs))
        path.write_text(json.dumps(doc, indent=1, default=str))
        counts = {}
        for *_, x, _q in jobs:
            counts[x.get("verdict", "error")] = counts.get(x.get("verdict", "error"), 0) + 1
        print(f"{stem}: {len(jobs)} notes -> {counts}", flush=True)


if __name__ == "__main__":
    main()
