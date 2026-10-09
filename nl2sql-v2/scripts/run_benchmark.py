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
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openai import OpenAI

from nl2sql.agent import run_episode
from nl2sql.config import (CONTEXT_DIR, AgentConfig, CriticConfig, DATA_SOURCES,
                           DCE_PROJECT_DIR, SPIDER2_LITE,
                           LLMConfig, VLLM_ENDPOINT_FILE)
from nl2sql.context import CatalogSearchContext, SearchContext
from nl2sql.db import Database
from nl2sql.eval import load_eval_standards, score_against_gold
from nl2sql.rubric import load_rubric, render_rubric
from nl2sql.tools import ToolSession


def load_questions(sources, instances=None, skip=None, limit=None):
    """Load questions from one or more DATA_SOURCES entries.

    Each returned question dict carries '_db_dir'/'_docs_dir' (that source's
    paths) so callers don't need to re-derive them per instance, plus the
    source's dialect and eval paths.

    Sources whose jsonl names fields differently (spider2-snow uses
    'instruction'/'db_id') declare a field_map, applied here so everything
    downstream only ever sees q["question"] / q["db"].
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
                if src.id_prefixes and not iid.startswith(src.id_prefixes):
                    continue
                if any(iid.startswith(x) for x in src.id_exclude_prefixes):
                    continue
                if instances and iid not in instances:
                    continue
                if skip and iid in skip:
                    continue
                for canon, src_key in src.field_map.items():
                    if canon not in q and src_key in q:
                        q[canon] = q[src_key]
                q["_db_dir"] = src.db_dir
                q["_docs_dir"] = src.docs_dir
                q["_source"] = src.name
                q["_dialect"] = src.dialect
                q["_gold_exec_dir"] = src.gold_exec_dir
                q["_eval_jsonl"] = src.eval_jsonl
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


INFRA_ERROR_MARKERS = ("Connection error", "timed out", "Timeout", "502", "503",
                       "504", "Service Unavailable", "Bad Gateway")


def is_infra_error(err: str | None) -> bool:
    return bool(err) and err.startswith("llm_call") and \
        any(m in err for m in INFRA_ERROR_MARKERS)


def wait_for_services(base_url: str, ollama_host: str | None,
                      max_wait_s: int = 4 * 3600, poll_s: int = 30) -> None:
    """Block until vLLM (and Ollama, when search is on) answer health checks.

    A preempted/requeued or crashed server otherwise turns every remaining
    question into an instant 'Connection error' row that looks like a real
    model failure."""
    import urllib.error
    import urllib.request
    checks = [("vLLM", base_url.rstrip("/") + "/models")]
    if ollama_host:
        checks.append(("Ollama", f"http://{ollama_host}:11434/api/tags"))
    # a server started with --api-key answers /v1/models with 401 unless the key is
    # sent, which would make a perfectly healthy endpoint look down for the whole
    # max_wait_s. Send the key, and count 401/403 as alive anyway: the question here
    # is whether the server is answering, not whether we are authorised.
    api_key = os.environ.get("VLLM_API_KEY", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    waited = 0
    while True:
        down = []
        for name, url in checks:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read(20000)
                    if r.status != 200:
                        down.append(name)
                    elif name == "vLLM" and b'"id"' not in body:
                        # 200 with no model listed means the HTTP app is serving but
                        # the weights are not loaded yet. Proceeding here is what made
                        # a whole run die on a malformed first completion.
                        down.append(name)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    # we sent the key, so this is a wrong key, not a warm-up state --
                    # waiting cannot fix it
                    raise SystemExit(
                        f"{name} rejected our API key ({e.code}) at {url}. Check the "
                        f"VLLM_API_KEY in the nl2sql-vllm secret matches the one the "
                        f"serve app was deployed with.")
                down.append(name)
            except Exception:
                down.append(name)
        if not down:
            if waited:
                print(f"[services back after {waited // 60} min] ", end="", flush=True)
            return
        if waited == 0:
            print(f"\n[waiting for {', '.join(down)} to come back] ", end="", flush=True)
        if waited >= max_wait_s:
            raise SystemExit(f"{', '.join(down)} down for {max_wait_s // 3600}h; giving up")
        time.sleep(poll_s)
        waited += poll_s


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


def warehouse_index_dir(dialect: str) -> Path:
    """Where build_bq_context.py writes <db>.npz (and the companion YAML)."""
    return CONTEXT_DIR / ("bigquery" if dialect == "bigquery" else "snowflake")


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


def schema_overview(db, char_cap: int = 8_000, datasource: str | None = None,
                    facts_cap: int = 5_000, report_truncation: bool = False) -> str:
    """Databao-style compressed schema in the system prompt: table -> column names,
    plus SQL-verified structure (grain, joins, coarser keys) from profile_dce.py."""
    prof = _load_profile(datasource)
    grains = {k.lower(): v for k, v in (prof.get("natural_grains") or {}).items() if v}
    for k, v in (prof.get("grains") or {}).items():
        if v:
            grains.setdefault(k.lower(), v)
    lines = []
    for t in db.list_tables():
        try:
            cols = [c for c, _, _ in db._columns(t)]
        except ValueError:
            continue
        g = grains.get(t.lower())
        grain = f" [one row per {', '.join(g)}]" if g else ""
        lines.append(f"{t}{grain}: {', '.join(cols)}")
    text = "\n".join(lines)
    if len(text) > char_cap:
        if report_truncation:
            # On a 300-table warehouse database the cap bites hard, and how
            # much schema the model never saw is a confound on any retrieval
            # claim. Cut at a table boundary and say what was dropped, so the
            # trace records it. (Local SQLite keeps the original wording so the
            # baseline prompt stays byte-identical.)
            kept, used = [], 0
            for ln in lines:
                if used + len(ln) + 1 > char_cap:
                    break
                kept.append(ln)
                used += len(ln) + 1
            text = ("\n".join(kept)
                    + f"\n[overview truncated at the {char_cap}-char cap: showing "
                      f"{len(kept)} of {len(lines)} tables — use list_tables/"
                      f"describe_table for the rest]")
        else:
            text = text[:char_cap] + "\n[overview truncated — use list_tables/describe_table]"
    out = ("\nSchema overview (columns per table; [one row per ...] is the table's verified "
           "grain; use describe_table for types/samples):\n" + text)
    facts = []
    for j in prof.get("joins") or []:
        if len(j["cols"]) > 1:
            facts.append(f"- {j['child']} -> {j['parent']}: join on ALL of "
                         f"({', '.join(j['cols'])}) [{j['card']}]")
        else:
            facts.append(f"- {j['child']}.{j['cols'][0]} -> {j['parent']}.{j['keys'][0]} [{j['card']}]")
    for t, es in (prof.get("entity_keys") or {}).items():
        for e in es:
            facts.append(f"- {t}.{e['coarse']} groups {e['fine']} (~{e['ratio']:g} per value): "
                         f"count/group by {e['coarse']} for the thing it identifies, not {e['fine']}")
    if facts:
        ft = "\n".join(facts)
        if len(ft) > facts_cap:
            ft = ft[:facts_cap] + "\n[truncated]"
        out += ("\n\nVerified joins and keys (checked against the data; declared FKs are "
                "not repeated):\n" + ft)
    return out


def _load_profile(datasource: str | None) -> dict:
    """spider2-dce/profiles/<db>.json written by scripts/profile_dce.py ({} if absent)."""
    if not datasource:
        return {}
    p = DCE_PROJECT_DIR / "profiles" / f"{Path(datasource).stem}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


SHARD_SUFFIX = re.compile(r"^(?P<stem>.+?)_(?P<date>\d{6}(?:\d{2})?)$")


def collapse_shards(tables: list[str]) -> tuple[list[str], dict]:
    """Group `<stem>_YYYYMMDD` / `<stem>_YYYYMM` families into one representative.

    Returns (tables, families) where families maps the representative name to
    (stem, n_shards, first, last). A family of two is left alone -- collapsing it
    would hide a name to save nothing.
    """
    fams = {}
    for t in tables:
        m = SHARD_SUFFIX.match(t)
        if m:
            fams.setdefault(m.group("stem"), []).append(m.group("date"))
    families, drop = {}, set()
    for stem, dates in fams.items():
        if len(dates) < 3:
            continue
        rep = f"{stem}_*"
        families[rep] = (stem, len(dates), min(dates), max(dates))
        drop |= {f"{stem}_{d}" for d in dates}
    out = [t for t in tables if t not in drop]
    # keep the representative where the first shard used to sort
    for rep, (stem, *_rest) in families.items():
        out.append(rep)
    return sorted(out), families


def _family_note(rep: str, fam: tuple) -> str:
    stem, n, lo, hi = fam
    return (f"table: {rep}  ({n} date-sharded tables, {lo} to {hi})\n"
            f"  Query the whole family with the wildcard and filter the suffix:\n"
            f"    FROM `{rep}` WHERE _TABLE_SUFFIX BETWEEN '{lo}' AND '{hi}'\n"
            f"  All shards share one schema; describe_table('{stem}_{hi}') shows it.")


def full_schema_dump(db, char_cap: int = 58_000) -> str:
    """The whole catalog, budgeted so the table list itself is never truncated.

    See the module history: cutting the joined text mid-table made 73% of the bq_v2
    episodes blind to part of their own database.
    """
    tables, families = collapse_shards(db.list_tables())
    detail_for = {rep: f"{fam[0]}_{fam[3]}" for rep, fam in families.items()}

    names, columns, blocks = {}, {}, {}
    for t in tables:
        names[t] = f"- {t}"
        probe = detail_for.get(t, t)
        try:
            cols = [c for c, _, _ in db._columns(probe)]
            columns[t] = f"{t}: {', '.join(cols)}"
        except Exception:
            pass
        if t in families:
            blocks[t] = _family_note(t, families[t])
            continue
        try:
            blocks[t] = db.describe_table(t)
        except Exception as e:
            blocks[t] = f"table: {t} (describe failed: {e})"

    # tier 1 is mandatory: the only tier that guarantees the agent can name every
    # table and ask about it. Family notes ride along in the floor, because a
    # collapsed `x_*` name is useless without the _TABLE_SUFFIX syntax beside it.
    floor = "\n".join(names[t] for t in tables)
    fam_notes = "\n\n".join(blocks[t] for t in tables if t in families)
    budget = char_cap - len(floor) - len(fam_notes)

    def fit(src: dict, remaining: int) -> list[str]:
        kept, used = [], 0
        for t in tables:
            body = src.get(t)
            if body is None:
                continue
            if used + len(body) + 2 > remaining:
                break
            kept.append(t)
            used += len(body) + 2
        return kept

    full = fit(blocks, budget)
    if len(full) == len(tables):
        body = "\n\n".join(blocks[t] for t in tables)
        note = ""
    else:
        # no room for every full block: give columns to as many as possible, and
        # fall back to the bare list for the remainder
        with_cols = fit(columns, budget)
        if len(with_cols) >= len(full):
            shown = with_cols
            body = "\n".join(columns[t] for t in shown if t not in families)
            kind = "columns"
        else:
            shown = full
            body = "\n\n".join(blocks[t] for t in shown if t not in families)
            kind = "full detail"
        if fam_notes:
            body = fam_notes + "\n\n" + body
        shown = set(shown) | set(families)
        rest = [t for t in tables if t not in shown]
        note = (f"\n\n[{len(shown)} of {len(tables)} tables shown with {kind}; "
                f"the remaining {len(rest)} are listed by name below and "
                f"describe_table works on every one of them]\n"
                + "\n".join(names[t] for t in rest))

    head = "\nFull database schema"
    if families:
        head += (f" ({len(families)} date-sharded table "
                 f"{'family' if len(families) == 1 else 'families'} collapsed to a "
                 f"wildcard)")
    return f"{head}:\n{body}{note}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", help="vLLM base URL (default: logs/vllm_endpoint.txt)")
    ap.add_argument("--model", default=None, help="model name (default: first served model)")
    ap.add_argument("--instances", help="comma-separated instance ids")
    ap.add_argument("--skip-instances", help="comma-separated ids to skip")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--output", default="../results/v2_run.csv")
    ap.add_argument("--trace-dir")
    ap.add_argument("--run-tag", default="",
                    help="tags Snowflake QUERY_TAG so credits are "
                         "attributable per run; defaults to the output stem")
    ap.add_argument("--max-bytes-per-query", type=float, default=0,
                    help="BigQuery: GiB a single query may scan (dry-run "
                         "enforced; default 50)")
    ap.add_argument("--max-bytes-per-episode", type=float, default=0,
                    help="BigQuery: GiB one question may scan in total "
                         "(default 200)")
    ap.add_argument("--describe-cache", metavar="DIR",
                    help="cache describe_table output per table (the Snowflake "
                         "databases are static, so this is a once-ever cost; "
                         "share the dir across shards and lanes)")
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
    ap.add_argument("--thinking", action="store_true",
                    help="let the model reason before each step (Qwen "
                         "enable_thinking); slower, reasoning is kept in the trace")
    ap.add_argument("--rubric-dir",
                    help="directory of per-question output-shape rubrics from "
                         "scripts/run_rubric.py; appended to the system prompt")
    ap.add_argument("--retrieval", action="store_true",
                    help="warehouse lanes: offer search_context from the index built "
                         "by scripts/build_bq_context.py, IN ADDITION to whatever "
                         "--context-mode already puts in the prompt. The dump now "
                         "keeps every table name but drops descriptions for about "
                         "half the episodes, and the table cards carry those.")
    ap.add_argument("--rubric-confident-only", action="store_true",
                    help="use a question's rubric only when it states an exact row "
                         "count with high confidence; otherwise add nothing")
    ap.add_argument("--source", default="spider2",
                    help="comma-separated source(s) to load questions from: "
                         f"{', '.join(sorted(DATA_SOURCES))}, or 'all' (every "
                         "local-SQLite source; snow/dbt must be named explicitly)")
    args = ap.parse_args()

    if args.source == "all":
        # 'all' keeps its original meaning -- the local-SQLite sources. The snow
        # and dbt sources need a different backend and runner, so sweeping them in
        # here would just emit db_not_found rows.
        sources = [d for d in DATA_SOURCES.values() if d.dialect == "duckdb_sqlite"]
    else:
        names = args.source.split(",")
        unknown = [n for n in names if n not in DATA_SOURCES]
        if unknown:
            raise SystemExit(f"unknown --source value(s): {unknown}; "
                             f"choose from {sorted(DATA_SOURCES)} or 'all'")
        sources = [DATA_SOURCES[n] for n in names]

    dialects = {d.dialect for d in sources}
    if "duckdb" in dialects:
        raise SystemExit(
            "spider2_dbt is a repo-level dbt task, not one-shot SQL. "
            "Use scripts/run_dbt_benchmark.py.")
    if len(dialects) > 1:
        raise SystemExit(f"mixing dialects in one run is not supported: "
                         f"{sorted(dialects)} - run them as separate lanes.")
    snow_cfg = bq_cfg = None
    if args.draft_endpoint and dialects - {"duckdb_sqlite"}:
        raise SystemExit("--draft-model builds its schema prompt from a SQLite "
                         "file and emits SQLite SQL; it is not wired for the "
                         f"warehouse lanes {sorted(dialects)}. Drop the flag.")
    if dialects == {"snowflake"}:
        from nl2sql.snowflake_db import SnowflakeConfig
        snow_cfg = SnowflakeConfig.load(
            describe_cache_dir=(Path(args.describe_cache) if args.describe_cache
                                else None))
        print(f"snowflake: {snow_cfg.redacted()}")
    if dialects == {"bigquery"}:
        from nl2sql.bigquery_db import BigQueryConfig
        GiB = 1024 ** 3
        over = {}
        if args.max_bytes_per_query:
            over["max_bytes_per_query"] = int(args.max_bytes_per_query * GiB)
        if args.max_bytes_per_episode:
            over["max_bytes_per_episode"] = int(
                args.max_bytes_per_episode * GiB)
        bq_cfg = BigQueryConfig.load(**over)
        print(f"bigquery: {bq_cfg.redacted()}")
    if (snow_cfg or bq_cfg) and args.context_mode == "search":
        # Retrieval IS available on a warehouse lane now, from the index
        # build_bq_context.py synthesises out of the catalog Spider2 ships. Say
        # which databases have one rather than running episodes with a dead
        # search_context, which is how the 457-silently-failed-call bug stayed
        # invisible for days.
        idx = warehouse_index_dir("bigquery" if bq_cfg else "snowflake")
        have = {p.stem for p in idx.glob("*.yaml")}
        want = {q["db"] for q in load_questions(sources)}
        missing = sorted(want - have)
        print(f"warehouse lane: retrieval index at {idx} covers "
              f"{len(want & have)}/{len(want)} databases")
        if missing:
            print(f"  NO index for {len(missing)}: {', '.join(missing[:10])}"
                  + (" ..." if len(missing) > 10 else ""))
            print("  those episodes fall back to the schema dump; build them with "
                  "scripts/build_bq_context.py --all")

    base_url = read_endpoint(args.endpoint)
    client = OpenAI(base_url=base_url, api_key=os.environ.get("VLLM_API_KEY", "EMPTY"))
    model = args.model or client.models.list().data[0].id
    print(f"endpoint={base_url} model={model} context_mode={args.context_mode}")

    llm = LLMConfig(base_url=base_url, model=model,
                    temperature=args.temperature,
                    chat_template_kwargs={"enable_thinking": args.thinking}
                    if "qwen" in model.lower() else {})
    if args.thinking:
        # reasoning tokens count against the completion budget
        llm.max_tokens, llm.timeout = 12_000, 900.0
    cfg = AgentConfig(max_steps=args.max_steps, context_mode=args.context_mode,
                      expansion_queries=0 if args.no_expansion else 3,
                      text_sql_fallback=args.text_sql_fallback)
    critic = CriticConfig(enabled=bool(args.critic_model),
                          base_url=args.critic_endpoint, model=args.critic_model,
                          chat_template_kwargs={"enable_thinking": False}
                          if args.critic_model and "qwen" in args.critic_model.lower()
                          else {})

    # database -> CatalogSearchContext (or None when it has no index)
    warehouse_search: dict = {}
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
    # one standards file per source: lite and snow ship different eval jsonls
    _standards: dict[str, dict] = {}

    def standards_for(q):
        key = q.get("_source", "spider2")
        if key not in _standards:
            _standards[key] = load_eval_standards(q.get("_eval_jsonl"))
        return _standards[key]
    run_tag = args.run_tag or Path(args.output).stem
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    if trace_dir:
        trace_dir.mkdir(parents=True, exist_ok=True)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # sf_queries/sf_seconds are the Snowflake spend per instance: an all-zero
    # column means nothing actually ran, which is how a dead connection looks.
    fieldnames = ["instance_id", "db", "score", "score_detail", "status", "steps",
                  "critic_rounds", "search_calls", "draft_calls", "wall_seconds",
                  "sf_queries", "sf_seconds", "scan_bytes", "sql"]
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
            db_path = None
            if snow_cfg is None and bq_cfg is None:
                db_path = q["_db_dir"] / f"{db_name}.sqlite"
                if not db_path.exists():
                    writer.writerow({"instance_id": iid, "db": db_name, "score": 0,
                                     "score_detail": "db_not_found"})
                    print("db_not_found")
                    continue
                db = Database(db_path)
            else:
                try:
                    if snow_cfg is not None:
                        from nl2sql.snowflake_db import SnowflakeDatabase
                        db = SnowflakeDatabase(db_name, snow_cfg, instance_id=iid,
                                               run_tag=run_tag)
                    else:
                        from nl2sql.bigquery_db import BigQueryDatabase
                        db = BigQueryDatabase(db_name, bq_cfg, SPIDER2_LITE,
                                              instance_id=iid, run_tag=run_tag)
                except Exception as e:
                    # a missing database grant would otherwise score as a wrong
                    # answer for every instance using it
                    writer.writerow({"instance_id": iid, "db": db_name, "score": 0,
                                     "score_detail": f"connect_failed: {e}"})
                    f.flush()
                    print(f"connect_failed: {e}")
                    continue
            doc = None
            if q.get("external_knowledge") and q["_docs_dir"]:
                p = q["_docs_dir"] / q["external_knowledge"]
                doc = p.read_text() if p.exists() else None
            search = None
            extra = ""
            if (args.retrieval or args.context_mode == "search") and (
                    snow_cfg or bq_cfg):
                # cached per database: the larger indexes are ~150 MiB of float32
                # (fec is 52,357 chunks) and shards are grouped by database, so
                # rebuilding this per episode would re-read the same file for every
                # question on it
                if db_name not in warehouse_search:
                    idx = warehouse_index_dir(q["_dialect"])
                    try:
                        warehouse_search[db_name] = CatalogSearchContext(
                            idx, db_name, expansion_client=client,
                            expansion_model=model)
                    except FileNotFoundError:
                        warehouse_search[db_name] = None
                search = warehouse_search[db_name]
                if search is None and args.context_mode == "search":
                    print(f"[warn: no retrieval index for {db_name}; "
                          f"falling back to the schema dump] ", end="")
                    extra = full_schema_dump(db)
                elif search is None:
                    print(f"[warn: no retrieval index for {db_name}] ", end="")
            if args.retrieval and args.context_mode == "full":
                # additive: the dump as bq_v3 sent it, plus search_context
                extra = full_schema_dump(db)
            elif args.context_mode == "search":
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
                # compact overview (table -> columns) rather than the full dump:
                # with retrieval available, describe_table and search_context carry
                # the detail, and this matches what the SQLite lane sends
                extra += schema_overview(
                    db, datasource=resolve_datasource(db_name),
                    report_truncation=bool(snow_cfg or bq_cfg))

            if args.rubric_dir:
                rubric = load_rubric(args.rubric_dir, iid)
                if rubric and args.rubric_confident_only and not (
                        rubric.get("rows_confidence") == "high"
                        and rubric.get("exact_rows") is not None):
                    rubric = None
                if rubric:
                    extra += "\n" + render_rubric(rubric)

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

            ollama_host = os.environ.get("DCE_OLLAMA_HOST") if search else None
            try:
                for attempt in range(2):
                    wait_for_services(base_url, ollama_host)
                    session = ToolSession(db=db, cfg=cfg, search=search,
                                          doc_text=doc, draft=draft)
                    result = run_episode(q["question"], session, llm, cfg, critic,
                                         extra_context=extra)
                    if not is_infra_error(result.error):
                        break
                    print("[infra error, retrying question] ", end="", flush=True)
                else:
                    # Still failing on infrastructure: record nothing, so the
                    # restart wrapper + --resume retries this question later.
                    raise SystemExit(f"infrastructure error on {iid}: {result.error}")
            finally:
                db.close()

            budget = getattr(db, "budget", None)
            if result.pred_df is not None:
                score, detail = score_against_gold(
                    result.pred_df, iid, standards_for(q), q.get("_gold_exec_dir"))
            else:
                score, detail = 0, result.error or result.status
                if budget and budget.timeouts:
                    # never fold an execution failure into result_mismatch:
                    # a timeout-dominated run measures the warehouse size,
                    # not the model.
                    detail = f"sf_timeout x{budget.timeouts}: {detail}"
            correct += score
            writer.writerow({
                "instance_id": iid, "db": db_name, "score": score,
                "score_detail": detail, "status": result.status,
                "steps": result.steps, "critic_rounds": result.critic_rounds,
                "search_calls": result.search_calls,
                "draft_calls": session.draft_calls,
                "wall_seconds": round(result.wall_seconds, 1),
                "sf_queries": budget.queries if budget else "",
                "sf_seconds": round(budget.seconds, 1) if budget else "",
                "scan_bytes": getattr(db, "bytes_scanned", "") or "",
                "sql": (result.sql or "").replace("\n", "\\n")})
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
