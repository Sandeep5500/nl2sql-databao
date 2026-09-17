#!/usr/bin/env python3
"""Single-shot lane: schema + question -> ONE completion -> SQL -> score.

No tools, no iteration. The same prompt is used for every model so
generalist (Qwen3.5-9B) and specialist (Arctic-Text2SQL-R1-7B) compare fairly.
Predicted SQL executes directly against SQLite (Arctic's training dialect and
the official Spider2-lite eval dialect) — no DuckDB confound.

Usage (from nl2sql-v2/):
    uv run python scripts/run_single_shot.py --endpoint http://node:8765/v1 \
        --model Qwen/Qwen3.5-9B --output ../results/ss_qwen.csv \
        --trace-dir ../logs/traces/ss_qwen [--thinking]
"""

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from openai import OpenAI

from nl2sql.config import DOCS_DIR, QUESTIONS_FILE, SQLITE_DIR
from nl2sql.eval import load_eval_standards, score_against_gold

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_SQL_BLOCK_RE = re.compile(r"```sql\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_ANY_BLOCK_RE = re.compile(r"```\s*(.*?)```", re.DOTALL)

PROMPT = """You are an expert SQL analyst. Answer the question by writing ONE SQLite \
SELECT query against the database below.

Database schema:
{schema}
{doc_section}
Question: {question}

Instructions:
- Think step by step about which tables, joins, filters and computations are needed.
- Check value formats shown in the sample rows before writing filters.
- Return exactly the columns the question asks for — no extra id/helper columns.
- End your answer with the final SQLite query in a ```sql code block.
"""


def build_schema(db_path: Path, sample_rows: int = 2, char_cap: int = 45_000) -> str:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    cur = con.cursor()
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    parts = []
    for t in tables:
        ddl = cur.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)
        ).fetchone()[0]
        parts.append(ddl.strip() + ";")
        try:
            rows = cur.execute(f'SELECT * FROM "{t}" LIMIT {sample_rows}').fetchall()
            cols = [d[0] for d in cur.description]
            for row in rows:
                vals = ", ".join(str(v)[:60] for v in row)
                parts.append(f"-- sample: ({vals})")
            parts.append(f"-- columns: {', '.join(cols)}")
        except Exception:
            pass
        parts.append("")
    con.close()
    text = "\n".join(parts)
    if len(text) > char_cap:
        text = text[:char_cap] + "\n-- [schema truncated]"
    return text


def extract_sql(text: str) -> str | None:
    text = _THINK_RE.sub("", text)
    blocks = _SQL_BLOCK_RE.findall(text) or _ANY_BLOCK_RE.findall(text)
    if blocks:
        return blocks[-1].strip().rstrip(";") or None
    m = re.search(r"\b(WITH|SELECT)\b", text, re.IGNORECASE)
    return text[m.start():].strip().rstrip(";") if m else None


def run_sql_sqlite(db_path: Path, sql: str, row_cap: int = 5000,
                   timeout_s: float = 60.0) -> pd.DataFrame:
    import threading
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True,
                          check_same_thread=False)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    # runaway-query guard: interrupt after timeout_s (raises OperationalError)
    timer = threading.Timer(timeout_s, con.interrupt)
    timer.start()
    try:
        return pd.read_sql_query(sql, con).head(row_cap)
    finally:
        timer.cancel()
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--trace-dir")
    ap.add_argument("--instances")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--max-tokens", type=int, default=16384)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--thinking", action="store_true",
                    help="enable chat_template_kwargs thinking (Qwen3.5)")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    client = OpenAI(base_url=args.endpoint, api_key="EMPTY", timeout=600.0)
    standards = load_eval_standards()
    want = set(args.instances.split(",")) if args.instances else None

    questions = []
    for line in open(QUESTIONS_FILE):
        q = json.loads(line)
        if q["instance_id"].startswith("local") and (not want or q["instance_id"] in want):
            questions.append(q)
    if args.limit:
        questions = questions[: args.limit]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done, correct = set(), 0
    if args.resume and out_path.exists():
        prior = list(csv.DictReader(open(out_path)))
        done = {r["instance_id"] for r in prior}
        correct = sum(1 for r in prior if r["score"] == "1")
        questions = [q for q in questions if q["instance_id"] not in done]
        print(f"resume: {len(done)} done ({correct} correct), {len(questions)} left")
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    if trace_dir:
        trace_dir.mkdir(parents=True, exist_ok=True)

    fieldnames = ["instance_id", "db", "score", "score_detail", "prompt_chars",
                  "completion_chars", "wall_seconds", "sql"]
    schema_cache = {}
    with open(out_path, "a" if done else "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not done:
            writer.writeheader()
        for i, q in enumerate(questions):
            iid, dbn = q["instance_id"], q["db"]
            db_path = SQLITE_DIR / f"{dbn}.sqlite"
            print(f"[{i + 1}/{len(questions)}] {iid} ({dbn}) ... ", end="", flush=True)
            if dbn not in schema_cache:
                schema_cache[dbn] = build_schema(db_path)
            doc_section = ""
            if q.get("external_knowledge"):
                p = DOCS_DIR / q["external_knowledge"]
                if p.exists():
                    doc_section = ("\nReference documentation (required for this "
                                   "question):\n" + p.read_text()[:20_000] + "\n")
            prompt = PROMPT.format(schema=schema_cache[dbn],
                                   doc_section=doc_section, question=q["question"])
            t0 = time.time()
            sql, detail, score, completion = None, "", 0, ""
            try:
                extra = ({"chat_template_kwargs": {"enable_thinking": True}}
                         if args.thinking else None)
                resp = client.chat.completions.create(
                    model=args.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=args.temperature, max_tokens=args.max_tokens,
                    extra_body=extra)
                msg = resp.choices[0].message
                dump = msg.model_dump()
                reasoning = dump.get("reasoning") or dump.get("reasoning_content") or ""
                content = msg.content or ""
                completion = reasoning + "\n" + content
                # fall back to the reasoning tail if the model ran out of tokens
                # before emitting the final answer block
                sql = extract_sql(content) or extract_sql(reasoning[-4000:])
                if not sql and args.thinking:
                    # runaway thinking: one bounded retry without thinking
                    resp2 = client.chat.completions.create(
                        model=args.model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=args.temperature, max_tokens=3000,
                        extra_body={"chat_template_kwargs":
                                    {"enable_thinking": False}})
                    content2 = resp2.choices[0].message.content or ""
                    completion += "\n[no-thinking retry]\n" + content2
                    sql = extract_sql(content2)
                if not sql:
                    detail = "no_sql_extracted"
                else:
                    pred = run_sql_sqlite(db_path, sql)
                    score, detail = score_against_gold(pred, iid, standards)
            except Exception as e:
                detail = f"error: {str(e)[:120]}"
            wall = time.time() - t0
            correct += score
            writer.writerow({"instance_id": iid, "db": dbn, "score": score,
                             "score_detail": detail, "prompt_chars": len(prompt),
                             "completion_chars": len(completion),
                             "wall_seconds": round(wall, 1),
                             "sql": (sql or "").replace("\n", " ")})
            f.flush()
            print(f"{'✓' if score else '✗'} {detail} ({wall:.0f}s)")
            if trace_dir:
                json.dump({"instance_id": iid, "question": q["question"],
                           "score": score, "detail": detail, "sql": sql,
                           "completion": completion[:40_000]},
                          open(trace_dir / f"{iid}.json", "w"), indent=2)

    total = len(done) + len(questions)
    print(f"\n{correct}/{total} correct ({100 * correct // max(total, 1)}%) → {out_path}")


if __name__ == "__main__":
    main()
