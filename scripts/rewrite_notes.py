#!/usr/bin/env python3
"""Third pass over the explored notes: reduce each surviving note to the facts
its cited query shows, with no advice. A note saying "6,838 rows are exact
copies; deduplicate by tree_id" becomes "6,838 rows are exact copies of another
row" — what to do about it is the query author's decision, and depends on the
question. Table notes and the database guide are stripped of advice the same way.

Writes a `fact` field next to each note (empty = nothing factual left) and
`table_fact` / `database_fact`; describe_table and the prompt use those.

Usage (from repo root):
    uv run --project nl2sql-v2 python scripts/rewrite_notes.py \
        --endpoint http://<node>:<port>/v1 --model <model> [--datasources a,b]
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

NOTE_PROMPT = """Below is a note about a database table, the SQL query cited as its \
evidence, and that query's result. Rewrite the note so that it states only facts the \
result shows.

Remove:
- advice and instructions of any kind — what to use, avoid, filter, cast, deduplicate, \
join on, or be careful about;
- claims about what will go wrong in a query;
- interpretation the result does not show (what a value probably means, why it is there).

Keep the concrete facts: counts, values, formats, which table holds a code's meaning, \
which values have no match. Do not add anything new. One or two plain sentences. If \
nothing factual remains, return an empty string.

Table: {table}{column}
Note: {note}

Cited query:
{sql}

Its result:
{result}

Reply with JSON only: {{"fact": "<the rewritten note, or ''>"}}"""

TEXT_PROMPT = """Rewrite the text below, which describes {what}, so that it only \
describes: what the tables record and how they connect. Remove every sentence or clause \
that gives advice or an instruction (what to use, avoid, deduplicate, filter, or be \
careful about) or that predicts what will go wrong. Keep the facts, including counts. \
Do not add anything.

Text:
{text}

Reply with JSON only: {{"text": "<the rewritten text>"}}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasources")
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--notes-dir", default=str(DCE_PROJECT_DIR / "output" / "notes"))
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()
    client = OpenAI(base_url=args.endpoint, api_key="EMPTY", timeout=300)
    extra = ({"chat_template_kwargs": {"enable_thinking": False}}
             if "qwen" in args.model.lower() else None)

    def ask(prompt, key):
        resp = client.chat.completions.create(
            model=args.model, temperature=0.0, max_tokens=500, extra_body=extra,
            messages=[{"role": "user", "content": prompt}])
        m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.DOTALL)
        return str(json.loads(m.group(0)).get(key, "")).strip() if m else None

    def do(job):
        kind, target, field, prompt, key = job
        try:
            out = ask(prompt, key)
            if out is not None:
                target[field] = out
        except Exception as e:
            target[field + "_error"] = str(e)[:150]

    stems = (args.datasources.split(",") if args.datasources
             else sorted(p.stem for p in Path(args.notes_dir).glob("*.json")))
    for stem in stems:
        path = Path(args.notes_dir) / f"{stem}.json"
        doc = json.loads(path.read_text())
        jobs = []
        for t, r in doc["tables"].items():
            qs = r.get("queries") or {}
            for x in (r.get("column_notes") or []) + (r.get("pitfalls") or []):
                q = qs.get(x.get("query_id"))
                if x.get("verdict") == "no" or not q or not x.get("note"):
                    continue
                jobs.append(("note", x, "fact", NOTE_PROMPT.format(
                    table=t, column=f", column {x['column']}" if x.get("column") else "",
                    note=x["note"], sql=q.get("sql", "")[:2000],
                    result=q.get("result", "")[:1500]), "fact"))
            if r.get("table_note"):
                jobs.append(("table", r, "table_fact", TEXT_PROMPT.format(
                    what=f"the table {t}", text=r["table_note"]), "text"))
        if doc.get("database_note"):
            jobs.append(("db", doc, "database_fact", TEXT_PROMPT.format(
                what="a database", text=doc["database_note"]), "text"))
        with ThreadPoolExecutor(args.workers) as ex:
            list(ex.map(do, jobs))
        path.write_text(json.dumps(doc, indent=1, default=str))
        notes = [j[1] for j in jobs if j[0] == "note"]
        print(f"{stem}: {len(notes)} notes -> {sum(1 for n in notes if n.get('fact'))} "
              f"facts, {sum(1 for n in notes if n.get('fact') == '')} emptied", flush=True)


if __name__ == "__main__":
    main()
