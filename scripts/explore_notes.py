#!/usr/bin/env python3
"""Enrichment by exploration: for each table, a short agent episode whose only
tool is SQL writes the notes a SQL author would need. It starts from facts
computed from the data (row count, key, column profiles) and never sees the
benchmark questions. A final call per database writes a short note on how the
database is organised.

Output: spider2-dce/output/notes/<db>.json
Usage (from repo root):
    uv run --project nl2sql-v2 python scripts/explore_notes.py \
        --datasources f1,ipl --endpoint http://<node>:<port>/v1 --model <model>
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nl2sql-v2/src"))
sys.path.insert(0, str(ROOT / "nl2sql-v2/scripts"))

from openai import OpenAI  # noqa: E402

from nl2sql.config import AgentConfig, DCE_PROJECT_DIR, SQLITE_DIR  # noqa: E402
from nl2sql.context import TableContext  # noqa: E402
from nl2sql.db import Database  # noqa: E402
from nl2sql.tools import ToolSession, build_tool_schemas, parse_tool_args  # noqa: E402

SYSTEM = """You are documenting one table of a SQL database for analysts who will \
later write queries against it. They will see the facts below (row count, key, each \
column's type, range and values) exactly as you see them. Your job is to add what those \
facts do not show and what an analyst is likely to get wrong.

You can run SQL (DuckDB syntax) against the whole database. You have {max_turns} turns; \
use them to check things, not to restate the facts.

Worth finding out
- What a code or id means, and which other table holds its meaning. Look it up; do not \
guess from the name.
- Values that need converting before they can be compared or computed with: numbers or \
dates stored as text, units or suffixes inside the value, inconsistent formats.
- What a date or period column actually marks (start or end of the period, which day of \
the week, whether every period is present).
- Placeholder values that are not real data: 'unknown', empty strings, 0, 999, a \
default date.
- Columns that look alike: say how they differ, from the data.
- How this table connects to others: which column matches which key, and whether one \
row here can match several rows there or none.
- Anything about how rows repeat or are split that would make a COUNT or SUM misleading.

Rules
- Write a note only for something you checked with a query, or that follows directly \
from the facts shown. If a query contradicts what you expected, write what the query \
showed.
- No note is better than a guess. Most columns need no note; leave them out.
- Do not repeat the facts (types, ranges, value lists) and do not describe the obvious.
- Each note is one or two plain sentences an analyst can act on.

When done, call submit_notes — it must be your only tool call in that message.

Database: {db_name}
All tables (name: columns):
{overview}

Table to document, with its computed facts:
{facts}"""

LAST_TURN = "This is your last turn. Call submit_notes now with what you have verified."

SUBMIT = {"type": "function", "function": {
    "name": "submit_notes",
    "description": "Submit the notes for this table.",
    "parameters": {"type": "object", "properties": {
        "table_note": {"type": "string",
                       "description": "One or two sentences: what one row records and "
                                      "what the table is for."},
        "column_notes": {"type": "array", "items": {"type": "object", "properties": {
            "column": {"type": "string"},
            "note": {"type": "string"},
            "query_id": {"type": "string",
                         "description": "The query_id that supports this note, or '' "
                                        "if it follows from the facts shown."}},
            "required": ["column", "note", "query_id"]}},
        "pitfalls": {"type": "array", "items": {"type": "object", "properties": {
            "note": {"type": "string",
                     "description": "Something about this table as a whole that would "
                                    "make a query silently wrong."},
            "query_id": {"type": "string"}},
            "required": ["note", "query_id"]}}},
        "required": ["table_note", "column_notes", "pitfalls"]}}}

DB_PROMPT = """Below are the tables of a SQL database with a one-line note on each and \
their keys. Write a short guide (at most 120 words) for an analyst who has never seen \
it: which tables record events or transactions, which are lookups or descriptions of \
things, and how the main tables connect (which column joins to which). Mention a join \
only if both columns appear below. Plain sentences, no headings, no SQL.

Database: {db_name}

{tables}"""


def overview(db: Database) -> str:
    lines = []
    for t in db.list_tables():
        try:
            lines.append(f"{t}: {', '.join(c for c, _, _ in db._columns(t))}")
        except ValueError:
            continue
    return "\n".join(lines)[:8000]


def explore(client, model, db, tc, table, ov, max_turns, cfg) -> dict:
    session = ToolSession(db=db, cfg=cfg)
    tools = [t for t in build_tool_schemas(cfg, has_docs=False, has_search=False)
             if t["function"]["name"] == "run_sql_query"] + [SUBMIT]
    facts = db.describe_table(table, context=tc, notes=False)
    messages = [{"role": "system", "content": SYSTEM.format(
                    max_turns=max_turns, db_name=db.sqlite_path.stem, overview=ov,
                    facts=facts)},
                {"role": "user", "content": "Begin."}]
    out = {"turns": 0, "queries": {}, "error": None}
    extra = ({"chat_template_kwargs": {"enable_thinking": False}}
             if "qwen" in model.lower() else None)
    for turn in range(max_turns):
        out["turns"] = turn + 1
        last = turn == max_turns - 1
        if last:
            messages.append({"role": "user", "content": LAST_TURN})
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=tools, temperature=0.0,
            max_tokens=4096, extra_body=extra,
            tool_choice=({"type": "function", "function": {"name": "submit_notes"}}
                         if last else "auto"))
        msg = resp.choices[0].message
        calls = msg.tool_calls or []
        assistant = {"role": "assistant", "content": msg.content or ""}
        if calls:
            assistant["tool_calls"] = [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in calls]
        messages.append(assistant)
        submit = next((c for c in calls if c.function.name == "submit_notes"), None)
        if submit:
            args = parse_tool_args(submit.function.arguments)
            if "__parse_error__" in args:
                out["error"] = "submit_notes arguments were not valid JSON"
            else:
                out.update(table_note=str(args.get("table_note", "")),
                           column_notes=args.get("column_notes") or [],
                           pitfalls=args.get("pitfalls") or [])
            break
        if not calls:
            messages.append({"role": "user",
                             "content": "Run a query, or call submit_notes."})
            continue
        for c in calls:
            args = parse_tool_args(c.function.arguments)
            if c.function.name != "run_sql_query" or "__parse_error__" in args:
                res = "ERROR: only run_sql_query and submit_notes are available."
            else:
                res = session.dispatch("run_sql_query", args)
                m = re.match(r"query_id='(q\d+)'", res)
                if m:
                    out["queries"][m.group(1)] = {"sql": args.get("sql", ""),
                                                  "result": res[:1500]}
            messages.append({"role": "tool", "tool_call_id": c.id,
                             "content": res[: cfg.max_tool_result_chars]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasources", required=True, help="comma-separated yaml stems")
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out-dir", default=str(DCE_PROJECT_DIR / "output" / "notes"))
    ap.add_argument("--max-turns", type=int, default=8)
    args = ap.parse_args()

    client = OpenAI(base_url=args.endpoint, api_key="EMPTY", timeout=600)
    cfg = AgentConfig()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_norm = {re.sub(r"[^a-z0-9]", "_", p.stem.lower()): p
               for p in SQLITE_DIR.glob("*.sqlite") if p.stat().st_size}

    for stem in args.datasources.split(","):
        db = Database(by_norm[stem])
        tc = TableContext(DCE_PROJECT_DIR, f"databases/{stem}.yaml")
        path = out_dir / f"{stem}.json"
        result = json.loads(path.read_text()) if path.exists() else {"tables": {}}
        ov = overview(db)
        for t in db.list_tables():
            if t in result["tables"] and not result["tables"][t].get("error"):
                continue
            t0 = time.time()
            try:
                r = explore(client, args.model, db, tc, t, ov, args.max_turns, cfg)
            except Exception as e:
                r = {"error": str(e)[:300]}
            r["wall_seconds"] = round(time.time() - t0, 1)
            result["tables"][t] = r
            path.write_text(json.dumps(result, indent=1, default=str))
            print(f"{stem}.{t}: {len(r.get('column_notes') or [])} column notes, "
                  f"{len(r.get('pitfalls') or [])} pitfalls, {r.get('turns')} turns, "
                  f"{len(r.get('queries') or {})} queries ({r['wall_seconds']}s)"
                  + (f" ERROR {r['error']}" if r.get("error") else ""), flush=True)

        # database-level guide, written from the table notes and keys only
        if not result.get("database_note"):
            lines = []
            for t in db.list_tables():
                key = "; ".join(tc.key_lines(t) + (
                    ["joins: " + "; ".join(tc.foreign_keys(t))] if tc.foreign_keys(t) else []))
                note = result["tables"].get(t, {}).get("table_note", "")
                cols = ", ".join(c for c, _, _ in db._columns(t))
                lines.append(f"- {t} ({cols})\n  {note}\n  {key}")
            try:
                resp = client.chat.completions.create(
                    model=args.model, temperature=0.0, max_tokens=600,
                    messages=[{"role": "user", "content": DB_PROMPT.format(
                        db_name=db.sqlite_path.stem, tables="\n".join(lines)[:24000])}],
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}}
                    if "qwen" in args.model.lower() else None)
                result["database_note"] = re.sub(
                    r"<think>.*?</think>", "", resp.choices[0].message.content or "",
                    flags=re.DOTALL).strip()
            except Exception as e:
                result["database_note_error"] = str(e)[:200]
            path.write_text(json.dumps(result, indent=1, default=str))
            print(f"{stem}: database note written", flush=True)
        db.close()


if __name__ == "__main__":
    main()
