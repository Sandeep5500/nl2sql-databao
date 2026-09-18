#!/usr/bin/env python3
"""Run the Spider 2.0-Lite local benchmark with the v2 harness.

Usage (from nl2sql-v2/):
    uv run python scripts/run_benchmark.py --instances local002,local007
    uv run python scripts/run_benchmark.py --output ../results/v2.csv \
        --trace-dir ../logs/traces/v2_run --context-mode search
"""

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openai import OpenAI

from nl2sql.agent import run_episode
from nl2sql.config import (AgentConfig, CriticConfig, DATA_SOURCES, DCE_PROJECT_DIR,
                           LLMConfig, VLLM_ENDPOINT_FILE)
from nl2sql.context import SearchContext
from nl2sql.db import Database
from nl2sql.eval import load_eval_standards, score_against_gold
from nl2sql.tools import ToolSession


def load_questions(sources, instances=None, skip=None, limit=None):
    """Load questions from one or more DATA_SOURCES entries.

    Each returned question dict carries '_db_dir'/'_docs_dir' (that source's
    paths) so callers don't need to re-derive them per instance.
    """
    out = []
    for src in sources:
        if not src.questions_file.exists():
            raise SystemExit(f"source '{src.name}': questions file not found "
                             f"({src.questions_file})")
        with open(src.questions_file) as f:
            for line in f:
                q = json.loads(line)
                iid = q["instance_id"]
                if src.id_prefix and not iid.startswith(src.id_prefix):
                    continue
                if instances and iid not in instances:
                    continue
                if skip and iid in skip:
                    continue
                q["_db_dir"] = src.db_dir
                q["_docs_dir"] = src.docs_dir
                out.append(q)
    return out[:limit] if limit else out


def read_endpoint(cli_endpoint):
    ep = cli_endpoint
    if not ep:
        if not VLLM_ENDPOINT_FILE.exists():
            raise SystemExit("no vLLM endpoint: pass --endpoint or start serve_vllm.slurm")
        ep = VLLM_ENDPOINT_FILE.read_text().splitlines()[0].strip()  # "host:port"
    if not ep.startswith("http"):
        ep = f"http://{ep}"
    if not ep.rstrip("/").endswith("/v1"):
        ep = ep.rstrip("/") + "/v1"
    return ep


def resolve_datasource(db_name: str) -> str | None:
    """Map a question's db name to a DCE datasource id, or None if unenriched.

    Question db names ('E_commerce', 'Db-IMDB') differ from DCE yaml names
    ('e_commerce', 'db_imdb'): lowercase with non-alnum folded to underscore.
    v1 used db_name.lower() and silently lost search for 4 DBs (23 questions).
    """
    norm = re.sub(r"[^a-z0-9]", "_", db_name.lower())
    for cand in (db_name, db_name.lower(), norm):
        if (DCE_PROJECT_DIR / "output" / "databases" / f"{cand}.yaml").exists():
            return f"databases/{cand}.yaml"
    return None


def oracle_context(db: Database, info: dict) -> str:
    """Arm C: inject gold tables + (schema-verified) gold columns."""
    real_cols = set()
    for t in info["tables"]:
        try:
            real_cols.update(c for c, _, _ in db._columns(t))
        except ValueError:
            pass
    cols = [c for c in info["columns"] if c in real_cols]
    parts = ["\nThe correct answer is known to use these tables: "
             + ", ".join(info["tables"]) + "."]
    if cols:
        parts.append("Relevant columns: " + ", ".join(cols) + ".")
    parts.append("Details of those tables:\n")
    for t in info["tables"]:
        try:
            parts.append(db.describe_table(t))
        except Exception as e:
            parts.append(f"table {t}: describe failed ({e})")
    return "\n".join(parts)


def schema_overview(db: Database, char_cap: int = 8_000) -> str:
    """Databao-style compressed schema in the system prompt: table -> column names."""
    lines = []
    for t in db.list_tables():
        try:
            cols = [c for c, _, _ in db._columns(t)]
        except ValueError:
            continue
        lines.append(f"{t}: {', '.join(cols)}")
    text = "\n".join(lines)
    if len(text) > char_cap:
        text = text[:char_cap] + "\n[overview truncated — use list_tables/describe_table]"
    return ("\nSchema overview (columns per table; use describe_table for "
            "types/samples):\n" + text)


def full_schema_dump(db: Database, char_cap: int = 60_000) -> str:
    parts = []
    for t in db.list_tables():
        try:
            parts.append(db.describe_table(t))
        except Exception as e:
            parts.append(f"table: {t} (describe failed: {e})")
    text = "\n\n".join(parts)
    if len(text) > char_cap:
        text = text[:char_cap] + "\n[schema dump truncated]"
    return "\nFull database schema:\n" + text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", help="vLLM base URL (default: logs/vllm_endpoint.txt)")
    ap.add_argument("--model", default=None, help="model name (default: first served model)")
    ap.add_argument("--instances", help="comma-separated instance ids")
    ap.add_argument("--skip-instances", help="comma-separated ids to skip")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--output", default="../results/v2_run.csv")
    ap.add_argument("--trace-dir")
    ap.add_argument("--context-mode", choices=["search", "full", "oracle"],
                    default="search")
    ap.add_argument("--schema-overview", action="store_true",
                    help="inject compressed table->columns overview into the "
                         "system prompt (databao v1 style)")
    ap.add_argument("--no-expansion", action="store_true",
                    help="disable query expansion in search_context")
    ap.add_argument("--critic-endpoint")
    ap.add_argument("--critic-model")
    ap.add_argument("--draft-endpoint",
                    help="specialist SQL model endpoint for the draft_sql tool")
    ap.add_argument("--draft-model")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--text-sql-fallback", action="store_true",
                    help="execute ```sql blocks from replies of models without "
                         "tool training (e.g. Arctic as actor)")
    ap.add_argument("--resume", action="store_true",
                    help="skip instances already in --output and append to it")
    ap.add_argument("--source", default="spider2",
                    help="comma-separated source(s) to load questions from: "
                         f"{', '.join(sorted(DATA_SOURCES))}, or 'all'")
    args = ap.parse_args()

    if args.source == "all":
        sources = list(DATA_SOURCES.values())
    else:
        names = args.source.split(",")
        unknown = [n for n in names if n not in DATA_SOURCES]
        if unknown:
            raise SystemExit(f"unknown --source value(s): {unknown}; "
                             f"choose from {sorted(DATA_SOURCES)} or 'all'")
        sources = [DATA_SOURCES[n] for n in names]

    base_url = read_endpoint(args.endpoint)
    client = OpenAI(base_url=base_url, api_key="EMPTY")
    model = args.model or client.models.list().data[0].id
    print(f"endpoint={base_url} model={model} context_mode={args.context_mode}")

    llm = LLMConfig(base_url=base_url, model=model,
                    temperature=args.temperature,
                    chat_template_kwargs={"enable_thinking": False}
                    if "qwen" in model.lower() else {})
    cfg = AgentConfig(max_steps=args.max_steps, context_mode=args.context_mode,
                      expansion_queries=0 if args.no_expansion else 3,
                      text_sql_fallback=args.text_sql_fallback)
    critic = CriticConfig(enabled=bool(args.critic_model),
                          base_url=args.critic_endpoint, model=args.critic_model,
                          chat_template_kwargs={"enable_thinking": False}
                          if args.critic_model and "qwen" in args.critic_model.lower()
                          else {})

    questions = load_questions(
        sources,
        set(args.instances.split(",")) if args.instances else None,
        set(args.skip_instances.split(",")) if args.skip_instances else None,
        args.limit)

    oracle = {}
    if args.context_mode == "oracle":
        oracle_path = Path(__file__).resolve().parents[1] / "oracle_context.json"
        if not oracle_path.exists():
            raise SystemExit("run scripts/build_oracle_context.py first")
        oracle = json.loads(oracle_path.read_text())
        questions = [q for q in questions if q["instance_id"] in oracle]
        print(f"oracle mode: restricted to {len(questions)} instances with gold SQL")
    standards = load_eval_standards()
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    if trace_dir:
        trace_dir.mkdir(parents=True, exist_ok=True)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["instance_id", "db", "score", "score_detail", "status", "steps",
                  "critic_rounds", "search_calls", "draft_calls", "wall_seconds",
                  "sql"]
    correct = 0
    if args.resume and out_path.exists():
        prior = list(csv.DictReader(open(out_path)))
        done_ids = {r["instance_id"] for r in prior}
        correct = sum(1 for r in prior if r.get("score") == "1")
        questions = [q for q in questions if q["instance_id"] not in done_ids]
        print(f"resume: {len(done_ids)} already done ({correct} correct), "
              f"{len(questions)} remaining")
        mode, write_header = "a", False
    else:
        mode, write_header = "w", True
    with open(out_path, mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for i, q in enumerate(questions):
            iid, db_name = q["instance_id"], q["db"]
            print(f"[{i + 1}/{len(questions)}] {iid} ({db_name}) ... ",
                  end="", flush=True)
            db_path = q["_db_dir"] / f"{db_name}.sqlite"
            if not db_path.exists():
                writer.writerow({"instance_id": iid, "db": db_name, "score": 0,
                                 "score_detail": "db_not_found"})
                print("db_not_found")
                continue

            db = Database(db_path)
            doc = None
            if q.get("external_knowledge") and q["_docs_dir"]:
                p = q["_docs_dir"] / q["external_knowledge"]
                doc = p.read_text() if p.exists() else None
            search = None
            extra = ""
            if args.context_mode == "search":
                ds = resolve_datasource(db_name)
                if ds:
                    search = SearchContext(DCE_PROJECT_DIR, ds,
                                           expansion_client=client,
                                           expansion_model=model)
                else:
                    print(f"[warn: no DCE enrichment for {db_name}; "
                          f"search_context disabled] ", end="")
            elif args.context_mode == "full":
                extra = full_schema_dump(db)
            elif args.context_mode == "oracle":
                extra = oracle_context(db, oracle[iid])
            if args.schema_overview and args.context_mode == "search":
                extra += schema_overview(db)

            draft = None
            if args.draft_endpoint and args.draft_model:
                from run_single_shot import build_schema
                from nl2sql.draft import DraftSQL
                draft = DraftSQL(args.draft_endpoint, args.draft_model,
                                 build_schema(db_path))
                extra += ("\nA specialist SQL model is available via the draft_sql "
                          "tool. Call it EARLY with the full question to get a "
                          "strong draft, then verify and refine it yourself before "
                          "submitting.")

            session = ToolSession(db=db, cfg=cfg, search=search, doc_text=doc,
                                  draft=draft)
            try:
                result = run_episode(q["question"], session, llm, cfg, critic,
                                     extra_context=extra)
            finally:
                db.close()

            if result.pred_df is not None:
                score, detail = score_against_gold(result.pred_df, iid, standards)
            else:
                score, detail = 0, result.error or result.status
            correct += score
            writer.writerow({
                "instance_id": iid, "db": db_name, "score": score,
                "score_detail": detail, "status": result.status,
                "steps": result.steps, "critic_rounds": result.critic_rounds,
                "search_calls": result.search_calls,
                "draft_calls": session.draft_calls,
                "wall_seconds": round(result.wall_seconds, 1),
                "sql": (result.sql or "").replace("\n", " ")})
            f.flush()
            print(f"{'✓' if score else '✗'} {detail} "
                  f"({result.steps} steps, {result.wall_seconds:.0f}s)")

            if trace_dir:
                with open(trace_dir / f"{iid}.json", "w") as tf:
                    json.dump({"instance_id": iid, "question": q["question"],
                               "status": result.status, "score": score,
                               "detail": detail, "sql": result.sql,
                               "system": result.system,
                               "trace": result.trace}, tf, indent=2, default=str)

    total_rows = len(list(csv.DictReader(open(out_path))))
    print(f"\n{correct}/{total_rows} correct "
          f"({100 * correct // max(total_rows, 1)}%) → {out_path}")

    if trace_dir:
        try:
            from traces_to_inspect import convert
            convert(trace_dir, out_path, model)
        except Exception as e:
            print(f"inspect-log conversion failed (non-fatal): {e}")


if __name__ == "__main__":
    main()
