#!/usr/bin/env python3
"""Generate an output-shape rubric per question (see nl2sql/rubric.py).

A planning pass that runs before the benchmark: for each question it decides what the
answer should LOOK like -- how many rows, which columns, what ordering -- and writes
that to <out-dir>/<instance_id>.json. run_benchmark.py --rubric-dir <out-dir> then
appends it to the agent's system prompt.

On the SQLite lane (origin/main's version of this script) it has every inspection
tool, because scanning a SQLite table is free:

    uv run python scripts/run_rubric.py --out-dir ../logs/rubrics/r1

On a warehouse lane it is **free of warehouse cost**: list_tables and describe_table
are served from the catalog spider2-lite ships as JSON, and rubric.py drops
get_column_values and find_value for non-SQLite dialects, so no SQL runs at all.
That matters because this is a second pass over all 204 questions -- with
get_column_values left in, it would have roughly doubled the lane's bill for a step
that does not need data.

    uv run python scripts/run_rubric.py --source spider2_lite_bq \
        --out-dir /results/rubric_bq --resume

Verify the claim rather than trusting it: the printed scan total must be 0 B.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import OpenAI

from nl2sql.config import (DATA_SOURCES, AgentConfig, DCE_PROJECT_DIR, LLMConfig,
                           SPIDER2_LITE)
from nl2sql.context import SearchContext
from nl2sql.rubric import run_rubric
from nl2sql.tools import ToolSession
from run_benchmark import (full_schema_dump, load_questions, read_endpoint,
                           resolve_datasource, schema_overview, wait_for_services)


def human_bytes(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint")
    ap.add_argument("--model", default=None)
    ap.add_argument("--source", default="spider2",
                    help=f"one of {sorted(DATA_SOURCES)}")
    ap.add_argument("--instances")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--max-turns", type=int, default=5)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--no-search", action="store_true")
    ap.add_argument("--with-sql", action="store_true",
                    help="also give the rubric agent run_sql_query. On a warehouse "
                         "lane this makes the pass cost real money; off by default.")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    if args.source not in DATA_SOURCES:
        raise SystemExit(f"unknown --source {args.source!r}; "
                         f"choose from {sorted(DATA_SOURCES)}")
    src = DATA_SOURCES[args.source]
    if src.dialect == "duckdb":
        raise SystemExit("spider2_dbt is a repo-level task with no single output "
                         "shape to describe; the rubric does not apply.")

    base_url = read_endpoint(args.endpoint)
    client = OpenAI(base_url=base_url, api_key=os.environ.get("VLLM_API_KEY", "EMPTY"))
    model = args.model or client.models.list().data[0].id
    llm = LLMConfig(base_url=base_url, model=model, temperature=args.temperature,
                    chat_template_kwargs={"enable_thinking": False}
                    if "qwen" in model.lower() else {})
    cfg = AgentConfig()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bq_cfg = snow_cfg = None
    if src.dialect == "bigquery":
        from nl2sql.bigquery_db import BigQueryConfig
        bq_cfg = BigQueryConfig.load()
        print(f"bigquery: {bq_cfg.redacted()}")
    elif src.dialect == "snowflake":
        from nl2sql.snowflake_db import SnowflakeConfig
        snow_cfg = SnowflakeConfig.load()
        print(f"snowflake: {snow_cfg.redacted()}")

    questions = load_questions(
        [src], set(args.instances.split(",")) if args.instances else None)
    ollama_host = None if (args.no_search or bq_cfg or snow_cfg) \
        else os.environ.get("DCE_OLLAMA_HOST")
    print(f"{len(questions)} questions from {args.source} "
          f"({src.dialect}) -> {out_dir}")

    n_ok = scanned = 0
    t_start = time.time()
    for i, q in enumerate(questions):
        iid, db_name = q["instance_id"], q["db"]
        path = out_dir / f"{iid}.json"
        if args.resume and path.exists():
            try:
                if json.loads(path.read_text(encoding="utf-8")).get("rubric"):
                    n_ok += 1
                    continue
            except ValueError:
                pass                     # a half-written file: redo it
        print(f"[{i + 1}/{len(questions)}] {iid} ({db_name}) ... ",
              end="", flush=True)
        try:
            if bq_cfg is not None:
                from nl2sql.bigquery_db import BigQueryDatabase
                db = BigQueryDatabase(db_name, bq_cfg, SPIDER2_LITE,
                                      instance_id=iid, run_tag="rubric")
            elif snow_cfg is not None:
                from nl2sql.snowflake_db import SnowflakeDatabase
                db = SnowflakeDatabase(db_name, snow_cfg, instance_id=iid,
                                       run_tag="rubric")
            else:
                from nl2sql.db import Database
                db_path = q["_db_dir"] / f"{db_name}.sqlite"
                if not db_path.exists():
                    print("db_not_found")
                    continue
                db = Database(db_path)
        except Exception as e:
            print(f"connect_failed: {e}")
            continue

        doc = None
        if q.get("external_knowledge") and q["_docs_dir"]:
            p = q["_docs_dir"] / q["external_knowledge"]
            doc = p.read_text(encoding="utf-8") if p.exists() else None
        search = None
        if ollama_host:
            ds = resolve_datasource(db_name)
            if ds:
                search = SearchContext(DCE_PROJECT_DIR, ds, expansion_client=client,
                                       expansion_model=model)
        try:
            wait_for_services(base_url, ollama_host if search else None)
            # the warehouse lanes have no DCE index, so the rubric agent needs the
            # schema in its prompt the same way the benchmark agent does
            extra = (schema_overview(db) if search
                     else full_schema_dump(db))
            session = ToolSession(db=db, cfg=cfg, search=search, doc_text=doc)
            res = run_rubric(q["question"], session, llm, cfg,
                             extra_context=extra, max_turns=args.max_turns,
                             with_sql=args.with_sql)
        finally:
            scanned += int(getattr(db, "bytes_scanned", 0) or 0)
            db.close()
        res.update(instance_id=iid, question=q["question"], model=model,
                   source=args.source, dialect=src.dialect)
        path.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
        r = res["rubric"]
        if r:
            n_ok += 1
            print(f"rows[{r.get('rows_confidence')}]={r.get('exact_rows')} "
                  f"cols[{r.get('columns_confidence')}]={len(r.get('columns') or [])} "
                  f"({res['turns']} turns, {res['wall_seconds']}s)")
        else:
            print(f"NO RUBRIC: {res['error']}")

    print(f"\n{n_ok}/{len(questions)} rubrics -> {out_dir}")
    print(f"wall {(time.time() - t_start) / 60:.1f} min")
    print(f"warehouse bytes scanned: {human_bytes(scanned)}"
          + ("  <- must be 0 B unless --with-sql" if not args.with_sql else ""))
    if scanned and not args.with_sql:
        print("WARNING: the rubric pass was supposed to be catalog-only but "
              "scanned data. Check rubric.py's tool gating before trusting the "
              "lane's cost model.")
    # how many would survive run_benchmark.py --rubric-confident-only
    gated = 0
    for p in out_dir.glob("*.json"):
        try:
            r = json.loads(p.read_text(encoding="utf-8")).get("rubric") or {}
        except ValueError:
            continue
        if r.get("rows_confidence") == "high" and r.get("exact_rows") is not None:
            gated += 1
    print(f"{gated} would pass --rubric-confident-only "
          f"(the gate that produced the team's 51.3%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
