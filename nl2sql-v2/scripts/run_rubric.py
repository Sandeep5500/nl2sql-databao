#!/usr/bin/env python3
"""Generate an output-shape rubric per question (see nl2sql/rubric.py).

Usage (from nl2sql-v2/):
    DCE_OLLAMA_HOST=<node> uv run python scripts/run_rubric.py \
        --out-dir ../logs/rubrics/r1 [--instances local002,local007] [--max-turns 5]
Feed the result to the main agent with run_benchmark.py --rubric-dir <out-dir>.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import OpenAI

from nl2sql.config import AgentConfig, DCE_PROJECT_DIR, DOCS_DIR, LLMConfig, SQLITE_DIR
from nl2sql.context import SearchContext
from nl2sql.db import Database
from nl2sql.rubric import run_rubric
from nl2sql.tools import ToolSession
from run_benchmark import (load_questions, read_endpoint, resolve_datasource,
                           schema_overview, wait_for_services)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint")
    ap.add_argument("--model", default=None)
    ap.add_argument("--instances")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--max-turns", type=int, default=5)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--no-search", action="store_true")
    ap.add_argument("--with-sql", action="store_true",
                    help="also give the rubric agent run_sql_query")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    base_url = read_endpoint(args.endpoint)
    client = OpenAI(base_url=base_url, api_key="EMPTY")
    model = args.model or client.models.list().data[0].id
    llm = LLMConfig(base_url=base_url, model=model, temperature=args.temperature,
                    chat_template_kwargs={"enable_thinking": False}
                    if "qwen" in model.lower() else {})
    cfg = AgentConfig()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    questions = load_questions(set(args.instances.split(",")) if args.instances else None)
    ollama_host = None if args.no_search else os.environ.get("DCE_OLLAMA_HOST")

    n_ok = 0
    for i, q in enumerate(questions):
        iid, db_name = q["instance_id"], q["db"]
        path = out_dir / f"{iid}.json"
        if args.resume and path.exists() and json.loads(path.read_text()).get("rubric"):
            n_ok += 1
            continue
        print(f"[{i + 1}/{len(questions)}] {iid} ({db_name}) ... ", end="", flush=True)
        db = Database(SQLITE_DIR / f"{db_name}.sqlite")
        doc = None
        if q.get("external_knowledge"):
            p = DOCS_DIR / q["external_knowledge"]
            doc = p.read_text() if p.exists() else None
        search = None
        if ollama_host:
            ds = resolve_datasource(db_name)
            if ds:
                search = SearchContext(DCE_PROJECT_DIR, ds, expansion_client=client,
                                       expansion_model=model)
        try:
            wait_for_services(base_url, ollama_host if search else None)
            session = ToolSession(db=db, cfg=cfg, search=search, doc_text=doc)
            res = run_rubric(q["question"], session, llm, cfg,
                             extra_context=schema_overview(db),
                             max_turns=args.max_turns,
                             with_sql=args.with_sql)
        finally:
            db.close()
        res.update(instance_id=iid, question=q["question"], model=model)
        path.write_text(json.dumps(res, indent=2, default=str))
        r = res["rubric"]
        if r:
            n_ok += 1
            print(f"rows[{r.get('rows_confidence')}]={r.get('exact_rows')} "
                  f"cols[{r.get('columns_confidence')}]={len(r.get('columns') or [])} "
                  f"({res['turns']} turns, {res['wall_seconds']}s)")
        else:
            print(f"NO RUBRIC: {res['error']}")
    print(f"\n{n_ok}/{len(questions)} rubrics → {out_dir}")


if __name__ == "__main__":
    main()
