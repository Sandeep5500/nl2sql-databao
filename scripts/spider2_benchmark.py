#!/usr/bin/env python3
"""
Spider 2.0 (local SQLite track) benchmark runner for databao-agent.

Runs Spider 2.0 local questions through databao-agent and evaluates by comparing
predicted SQL output DataFrames against the official exec_result gold CSVs
(same logic as Spider2's evaluate.py).

Usage:
    # Run all local questions (requires OpenAI API key or compatible endpoint)
    uv --project ../databao-agent run python spider2_benchmark.py

    # Run specific instances
    uv --project ../databao-agent run python spider2_benchmark.py --instances local003,local008

    # Run first N questions
    uv --project ../databao-agent run python spider2_benchmark.py --limit 10

    # Per-instance JSONL checkpoint (default: alongside the CSV as *.status.jsonl)
    uv --project ../databao-agent run python spider2_benchmark.py --output ../results/run.csv

    # Use a specific model
    uv --project ../databao-agent run python spider2_benchmark.py --model gpt-4.1

Environment variables:
    OPENAI_API_KEY    OpenAI API key (required for OpenAI models)
    API_BASE_URL      Base URL for OpenAI-compatible API (optional, for custom endpoints)
    MODEL             Model name (default: gpt-4.1)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from contextlib import nullcontext
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# ── Paths ────────────────────────────────────────────────────────────────────
CAPSTONE_DIR = Path(__file__).parent.parent
SPIDER2_DIR = CAPSTONE_DIR / "Spider2" / "spider2-lite"
SQLITE_DIR = SPIDER2_DIR / "resource/databases/spider2-localdb"
EVAL_SUITE_DIR = SPIDER2_DIR / "evaluation_suite"
GOLD_EXEC_DIR = EVAL_SUITE_DIR / "gold/exec_result"
EVAL_JSONL = EVAL_SUITE_DIR / "gold/spider2lite_eval.jsonl"
DOCS_DIR = SPIDER2_DIR / "resource/documents"
QUESTIONS_FILE = SPIDER2_DIR / "spider2-lite.jsonl"
DCE_PROJECT_DIR = CAPSTONE_DIR / "spider2-dce"
# Enriched vector index built by DCE (`dce index`); used for search_context retrieval.
DCE_VECTOR_INDEX = DCE_PROJECT_DIR / "output" / "dce.duckdb"
RESULTS_DIR = CAPSTONE_DIR / "results"

EXCLUDE_DBS = {"oracle_sql", "stacking"}  # broken views crash DuckDB schema inspection


# ── Data loading ─────────────────────────────────────────────────────────────

def load_questions(instances=None, skip_instances=None, limit=None):
    questions = []
    with open(QUESTIONS_FILE) as f:
        for line in f:
            q = json.loads(line)
            if not q["instance_id"].startswith("local"):
                continue
            if q["db"].lower() in EXCLUDE_DBS:
                continue
            questions.append(q)
    if instances:
        inst_set = set(instances)
        questions = [q for q in questions if q["instance_id"] in inst_set]
    if skip_instances:
        skip_set = set(skip_instances)
        questions = [q for q in questions if q["instance_id"] not in skip_set]
    if limit:
        questions = questions[:limit]
    return questions


def load_eval_standards() -> dict:
    """Load per-question eval config (condition_cols, ignore_order) from spider2lite_eval.jsonl."""
    standards = {}
    with open(EVAL_JSONL) as f:
        for line in f:
            item = json.loads(line)
            standards[item["instance_id"]] = item
    return standards


def get_db_path(db_name: str) -> Path | None:
    for candidate in [SQLITE_DIR / f"{db_name}.sqlite", SQLITE_DIR / f"{db_name.lower()}.sqlite"]:
        if candidate.exists():
            return candidate
    for f in SQLITE_DIR.glob("*.sqlite"):
        if f.stem.lower() == db_name.lower():
            return f
    return None


# ── DuckDB capability hints injected into every agent context ─────────────────
DUCKDB_HINTS = """
DuckDB SQL capabilities you MUST use instead of Python or external tools:
- Linear regression: REGR_SLOPE(y, x), REGR_INTERCEPT(y, x), REGR_R2(y, x) — use these for any prediction/regression task
- Moving averages: AVG(col) OVER (ORDER BY ... ROWS BETWEEN N PRECEDING AND N FOLLOWING)
- Date arithmetic: datediff('day', date1, date2), date_diff('week', d1, d2), epoch_ms(), strptime()
  Do NOT use JULIAN() or DATE() — those are SQLite functions unavailable in DuckDB.
- Calendar decomposition (years/months/days between two dates):
    EXTRACT(YEAR FROM age(d2::DATE, d1::DATE)) AS years,
    EXTRACT(MONTH FROM age(d2::DATE, d1::DATE)) AS months,
    EXTRACT(DAY FROM age(d2::DATE, d1::DATE)) AS days
  age() returns a proper calendar interval; use this whenever the question asks for separate year/month/day components.
- Type casting: TRY_CAST(col AS DATE), col::DATE, col::FLOAT
- String functions: regexp_matches(), string_split(), list_aggregate()
- Percentile/quantile scoring: NTILE(n) OVER (ORDER BY col) — use this for any question involving percentile bins, quintiles, deciles, or "top N%" scoring.
Always express the full answer as a single DuckDB SELECT statement.
Never compute numerical values (coefficients, statistics, aggregates, scores) in your head — always let DuckDB compute them via SQL.
If you are uncertain about which column, table, or join path to use, call search_context to look up the schema before writing SQL rather than guessing.
""".strip()


# ── Agent setup ───────────────────────────────────────────────────────────────

def _patch_dce_src_yaml_sqlite_path(src_yaml_path: Path, sqlite_path: Path) -> None:
    """Rewrite connection.database_path to this machine's SQLite file.

    spider2-dce/src/databases/*.yaml often ship with Linux paths from the machine
    that built the index; DuckDB attach must use the local Spider2 sqlite path.
    """
    import yaml

    data = yaml.safe_load(src_yaml_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return
    conn = data.get("connection")
    if not isinstance(conn, dict):
        return
    if "database_path" not in conn:
        return
    conn["database_path"] = str(sqlite_path.resolve())
    src_yaml_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _normalize_dce_output_context_yaml_header(context_yaml: Path) -> None:
    """Make enriched context YAML readable by DCE's line-based header parser.

    databao-context-engine reads ``datasource_type`` only from lines that start
    with ``datasource_type: `` at column 0. UTF-8 BOM, leading spaces, or
    ``datasource_type:sqlite`` (no space) cause introspection to fail and
    ``is_context_built()`` to be false, which breaks ``search_context``.
    """
    text = context_yaml.read_text(encoding="utf-8-sig")
    lines = text.splitlines(True)
    out: list[str] = []
    fixed_header = False
    for i, line in enumerate(lines):
        if fixed_header or i >= 40:
            out.append(line)
            continue
        stripped = line.lstrip()
        if not stripped.startswith("datasource_type:"):
            out.append(line)
            continue
        rest = stripped[len("datasource_type:") :].lstrip()
        out.append(f"datasource_type: {rest}\n" if rest else "datasource_type: sqlite\n")
        fixed_header = True
    if fixed_header:
        context_yaml.write_text("".join(out), encoding="utf-8")


def _make_temp_dce_project(db_name: str, sqlite_path: Path, vector_index_path: Path) -> Path:
    """Create a minimal per-question DCE project dir.

    Contains only the src YAML for the relevant database and symlinks/copies
    ``vector_index_path`` (your enriched ``dce.duckdb``) into ``output/dce.duckdb``
    so ``search_context`` queries that index. Paths under ``%TEMP%`` are only a
    thin project layout; the DuckDB file is always this shared index.
    """
    tmp = Path(tempfile.mkdtemp(prefix=f"dce_{db_name.lower()}_"))

    # Project config
    shutil.copy(DCE_PROJECT_DIR / "dce.ini", tmp / "dce.ini")

    # Only this database's source YAML
    (tmp / "src" / "databases").mkdir(parents=True)
    src_yaml = DCE_PROJECT_DIR / "src" / "databases" / f"{db_name.lower()}.yaml"
    if src_yaml.exists():
        dest = tmp / "src" / "databases" / src_yaml.name
        shutil.copy(src_yaml, dest)
        _patch_dce_src_yaml_sqlite_path(dest, sqlite_path)

    # output/ gets its own directory; link/copy the single shared vector index here.
    out = tmp / "output"
    out.mkdir()
    (out / "databases").mkdir()

    shared_db = vector_index_path.resolve()
    if shared_db.exists():
        tmp_db = out / "dce.duckdb"
        try:
            tmp_db.symlink_to(shared_db)
        except OSError:
            try:
                # On Windows, hard links usually work without admin privileges and
                # avoid re-copying a potentially large vector index per question.
                os.link(shared_db, tmp_db)
            except OSError:
                # Final fallback when linking is unavailable.
                shutil.copy2(shared_db, tmp_db)

    # Copy the enriched output YAML so the domain has descriptions available
    out_yaml = DCE_PROJECT_DIR / "output" / "databases" / f"{db_name.lower()}.yaml"
    if out_yaml.exists():
        dest_ctx = out / "databases" / out_yaml.name
        shutil.copy(out_yaml, dest_ctx)
        _normalize_dce_output_context_yaml_header(dest_ctx)

    return tmp


def _progress(enabled: bool, message: str) -> None:
    """Emit a timestamped progress log line for long-running steps."""
    if not enabled:
        return
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [progress {ts}] {message}", flush=True)


def setup_agent(
    db_path: Path,
    model_name: str,
    api_base_url: str | None = None,
    external_knowledge_doc: str | None = None,
    vertex_project: str | None = None,
    vertex_location: str | None = None,
    google_application_credentials: str | None = None,
    debug_progress: bool = False,
    dce_vector_index: Path | None = None,
):
    """Create a databao agent with DCE retrieval enabled for a single database."""
    _progress(debug_progress, "Importing databao agent modules")
    import databao.agent as bao
    from databao.agent.configs.agent import AgentConfig
    from databao.agent.configs.llm import LLMConfig
    from databao.agent.integrations.dce import DatabaoContextApi

    if os.name == "nt":
        # Runtime-only Windows fix: DCE datasource IDs can use "\" separators,
        # but databao source names must be plain identifiers like "e_commerce".
        DatabaoContextApi.get_datasource_name = staticmethod(
            lambda datasource_id: str(getattr(datasource_id, "datasource_path", datasource_id))
            .replace("\\", "/")
            .split("/")[-1]
        )
        _progress(debug_progress, "Applied Windows datasource-path normalization")

    # Normalize plain Gemini model IDs to a Vertex provider-qualified model.
    resolved_model_name = model_name
    if ":" not in resolved_model_name and resolved_model_name.lower().startswith("gemini"):
        resolved_model_name = f"google_vertexai:{resolved_model_name}"

    # Vertex AI env wiring (safe no-op for non-Vertex models).
    if vertex_project:
        os.environ["VERTEX_PROJECT"] = vertex_project
    if vertex_location:
        os.environ["VERTEX_LOCATION"] = vertex_location
    if google_application_credentials:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = google_application_credentials

    llm_kwargs = {
        "name": resolved_model_name,
        "temperature": 0.0,
    }
    if api_base_url:
        # Local OpenAI-compatible endpoints (vLLM / gateways) usually need old chat completions.
        llm_kwargs["api_base_url"] = api_base_url
        llm_kwargs["use_responses_api"] = False

    _progress(debug_progress, f"Building LLM config for model '{resolved_model_name}'")
    llm_config = LLMConfig(**llm_kwargs)

    agent_config = AgentConfig()

    # Build a temp DCE project with only this DB's YAML — enables search_context tool
    index = (dce_vector_index or DCE_VECTOR_INDEX).resolve()
    _progress(
        debug_progress,
        f"Creating temp DCE project for db '{db_path.stem}' (sqlite={db_path}, dce.duckdb={index})",
    )
    tmp_dce = _make_temp_dce_project(db_path.stem, db_path, index)

    _progress(debug_progress, "Initializing domain from temp DCE project")
    domain = bao.domain(project_dir=tmp_dce)
    domain.add_description(DUCKDB_HINTS)

    if external_knowledge_doc:
        doc_path = DOCS_DIR / external_knowledge_doc
        if doc_path.exists():
            # Windows default locale (cp1252) breaks UTF-8 markdown (e.g. RFM.md).
            doc_text = doc_path.read_text(encoding="utf-8", errors="replace")
            if len(doc_text) > 20_000:
                doc_text = doc_text[:20_000] + "\n\n[... external knowledge truncated ...]"
                print(f"  WARN: external_knowledge doc truncated to 20K chars")
            domain.add_description(doc_text)
        else:
            print(f"  WARN: external_knowledge doc not found: {doc_path}")

    _progress(debug_progress, "Creating LighthouseExecutor")
    from databao.agent.executors import LighthouseExecutor

    executor = LighthouseExecutor()

    _progress(debug_progress, "Creating agent object")
    agent = bao.agent(domain=domain, llm_config=llm_config, agent_config=agent_config,
                      data_executor=executor, stream_ask=False, auto_output_modality=False)
    _progress(debug_progress, "Agent setup complete")
    return agent, tmp_dce


# ── Evaluation (ported from Spider2's evaluate.py) ────────────────────────────

def _normalize(value):
    if pd.isna(value):
        return 0
    return value


def _vectors_match(v1, v2, tol=1e-2, ignore_order=False):
    v1 = [_normalize(x) for x in v1]
    v2 = [_normalize(x) for x in v2]
    if ignore_order:
        v1 = sorted(v1, key=lambda x: (x is None, str(x), isinstance(x, (int, float))))
        v2 = sorted(v2, key=lambda x: (x is None, str(x), isinstance(x, (int, float))))
    if len(v1) != len(v2):
        return False
    for a, b in zip(v1, v2):
        if pd.isna(a) and pd.isna(b):
            continue
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if not math.isclose(float(a), float(b), abs_tol=tol):
                return False
        elif a != b:
            return False
    return True


def compare_dataframes(pred: pd.DataFrame, gold: pd.DataFrame, condition_cols=None, ignore_order: bool = False) -> bool:
    """Return True if pred matches gold (using Spider2's comparison logic)."""
    if condition_cols:
        if not isinstance(condition_cols, (list, tuple)):
            condition_cols = [condition_cols]
        gold_check = gold.iloc[:, condition_cols]
    else:
        gold_check = gold

    t_gold = gold_check.transpose().values.tolist()
    t_pred = pred.transpose().values.tolist()

    for gold_vector in t_gold:
        if not any(_vectors_match(gold_vector, pv, ignore_order=ignore_order) for pv in t_pred):
            return False
    return True


def score_against_gold(pred_df: pd.DataFrame, instance_id: str, standards: dict) -> tuple[int, str]:
    """Compare pred_df against all gold exec_result CSVs for this instance."""
    pattern = re.compile(rf"^{re.escape(instance_id)}(_[a-z])?\.csv$")
    gold_files = sorted(GOLD_EXEC_DIR / f for f in os.listdir(GOLD_EXEC_DIR) if pattern.match(f))

    if not gold_files:
        return 0, "no_gold_files"

    standard = standards.get(instance_id, {})
    condition_cols = standard.get("condition_cols")
    ignore_order = standard.get("ignore_order", False)

    if isinstance(condition_cols, list) and condition_cols and isinstance(condition_cols[0], list):
        flat_cols = condition_cols
    else:
        flat_cols = [condition_cols] * len(gold_files)

    for gold_file, cols in zip(gold_files, flat_cols):
        try:
            gold_df = pd.read_csv(gold_file)
            if compare_dataframes(pred_df, gold_df, condition_cols=cols, ignore_order=ignore_order):
                return 1, f"matches {gold_file.name}"
        except Exception:
            continue

    return 0, "result_mismatch"


# ── Agent trace logging ───────────────────────────────────────────────────────

def _is_sql_error(content_str: str) -> bool:
    """Heuristic: does a tool result look like a DuckDB/SQL error?"""
    lower = content_str.lower()
    return any(kw in lower for kw in ["error", "exception", "invalid", "syntax", "no such", "does not exist", "traceback"])


def _parse_sql_rows(content_str: str) -> int | None:
    """Parse the number of data rows returned from a run_sql_query ToolMessage."""
    # Format: "query_id='X'\n\ncol1,col2\nrow1\nrow2\n..."
    # Count lines after the blank line separator, minus the header line.
    try:
        if "query_id=" not in content_str:
            return None
        after_id = content_str.split("\n\n", 1)
        if len(after_id) < 2:
            return 0
        data_lines = [l for l in after_id[1].strip().splitlines() if l.strip()]
        return max(0, len(data_lines) - 1)  # subtract header
    except Exception:
        return None


def _parse_search_scores(content_str: str) -> list[float]:
    """Extract relevance scores from a search_context ToolMessage."""
    scores = []
    for match in re.finditer(r"'score':\s*([\d.e+-]+)", content_str):
        try:
            scores.append(float(match.group(1)))
        except ValueError:
            pass
    return scores


def _parse_error_type(content_str: str) -> str:
    """Extract a short error type label from a DuckDB error message."""
    m = re.search(r"Exception Name:\s*(\w+)", content_str)
    if m:
        return m.group(1)
    for label in ["SyntaxError", "BinderError", "CatalogException", "ConversionException",
                  "NotImplementedException", "OutOfMemoryException", "IOException"]:
        if label.lower() in content_str.lower():
            return label
    return "Error"


def extract_trace_stats(messages) -> dict:
    """Derive structured stats from a message list for error analysis."""
    from langchain_core.messages import AIMessage, ToolMessage

    n_agent_steps = 0
    n_sql_attempts = 0
    n_search_calls = 0
    sql_errors: list[str] = []
    all_sqls: list[str] = []
    search_queries: list[str] = []
    all_search_scores: list[float] = []
    hit_recursion_limit = False

    # Per-call log: one entry per tool invocation
    tool_call_log: list[dict] = []
    call_seq = 0

    # Map tool_call_id → {name, args} so ToolMessages can be matched back
    pending: dict[str, dict] = {}

    for msg in messages:
        if isinstance(msg, AIMessage):
            n_agent_steps += 1
            for tc in (msg.tool_calls or []):
                name = tc.get("name", "")
                tc_id = tc.get("id", "")
                args = tc.get("args", {}) or {}
                call_seq += 1
                entry: dict = {
                    "seq": call_seq,
                    "tool": name,
                    "step": n_agent_steps,
                }
                if name == "run_sql_query":
                    n_sql_attempts += 1
                    sql = str(args.get("sql", "")).strip()
                    if sql:
                        all_sqls.append(sql)
                    entry["sql_snippet"] = sql[:200]
                elif name == "search_context":
                    n_search_calls += 1
                    q = str(args.get("retrieve_text", ""))
                    if q:
                        search_queries.append(q)
                    entry["query"] = q
                elif name == "submit_result":
                    entry["query_id"] = args.get("query_id")
                pending[tc_id] = entry

        elif isinstance(msg, ToolMessage):
            tc_id = getattr(msg, "tool_call_id", None) or ""
            content_str = str(msg.content)
            entry = pending.pop(tc_id, None)
            if entry is None:
                continue
            name = entry["tool"]

            if name == "run_sql_query":
                is_err = _is_sql_error(content_str)
                entry["is_error"] = is_err
                if is_err:
                    err_msg = content_str[:300].strip()
                    entry["error_type"] = _parse_error_type(content_str)
                    entry["error_msg"] = err_msg
                    sql_errors.append(err_msg)
                else:
                    rows = _parse_sql_rows(content_str)
                    entry["rows_returned"] = rows
                    entry["result_preview"] = content_str[content_str.find("\n\n")+2:][:200].strip() if "\n\n" in content_str else ""

            elif name == "search_context":
                scores = _parse_search_scores(content_str)
                entry["n_chunks"] = len(scores)
                entry["score_avg"] = round(sum(scores) / len(scores), 4) if scores else None
                entry["score_min"] = round(min(scores), 4) if scores else None
                entry["score_max"] = round(max(scores), 4) if scores else None
                all_search_scores.extend(scores)

            tool_call_log.append(entry)

    # Flush any pending entries that had no ToolMessage response
    tool_call_log.extend(pending.values())
    tool_call_log.sort(key=lambda e: e.get("seq", 0))

    # Detect recursion limit hit
    if messages:
        from langchain_core.messages import AIMessage as _AI
        last_ai = next((m for m in reversed(messages) if isinstance(m, _AI)), None)
        if last_ai is not None:
            text = last_ai.content if isinstance(last_ai.content, str) else ""
            if isinstance(last_ai.content, list):
                text = " ".join(p.get("text", "") for p in last_ai.content if isinstance(p, dict))
            if not last_ai.tool_calls and not text.strip():
                hit_recursion_limit = True

    # Compact sequence string e.g. "search→sql→sql[ERR:BinderError]→sql→submit"
    seq_parts = []
    for e in tool_call_log:
        t = e["tool"]
        if t == "run_sql_query":
            label = "sql[ERR:" + e.get("error_type", "?") + "]" if e.get("is_error") else "sql"
        elif t == "search_context":
            label = "search"
        elif t == "submit_result":
            label = "submit"
        else:
            label = t
        seq_parts.append(label)
    tool_call_sequence = "→".join(seq_parts)

    search_score_avg = round(sum(all_search_scores) / len(all_search_scores), 4) if all_search_scores else None

    # Token usage — sum over all AIMessages (OpenAI fills usage_metadata per response)
    total_input_tokens = 0
    total_output_tokens = 0
    for msg in messages:
        if isinstance(msg, AIMessage):
            um = getattr(msg, "usage_metadata", None) or {}
            total_input_tokens += um.get("input_tokens", 0) or 0
            total_output_tokens += um.get("output_tokens", 0) or 0

    return {
        "n_agent_steps": n_agent_steps,
        "n_sql_attempts": n_sql_attempts,
        "n_search_calls": n_search_calls,
        "sql_errors": sql_errors,
        "all_sqls": all_sqls,
        "search_queries": search_queries,
        "hit_recursion_limit": hit_recursion_limit,
        "tool_call_log": tool_call_log,
        "tool_call_sequence": tool_call_sequence,
        "search_score_avg": search_score_avg,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
    }


def _fsync_text_file(f) -> None:
    """Best-effort flush + fsync so checkpoints survive abrupt process death."""
    try:
        f.flush()
        if getattr(f, "fileno", None):
            os.fsync(f.fileno())
    except (OSError, AttributeError, ValueError):
        pass


def write_status_jsonl(status_f, payload: dict) -> None:
    """Append one JSON object per line; flush + fsync for crash-safe checkpoints."""
    status_f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _fsync_text_file(status_f)


def classify_error(
    score: int,
    exec_result: str,
    error: str,
    trace_stats: dict,
    predicted_sql: str,
) -> str:
    """Return a single standardized error category string."""
    if score == 1:
        return "correct"
    if exec_result == "db_missing":
        return "db_missing"
    if exec_result == "agent_error":
        if "recursion" in error.lower() or trace_stats.get("hit_recursion_limit"):
            return "recursion_limit"
        if "timeout" in error.lower() or "timed out" in error.lower():
            return "timeout"
        return "agent_error"
    if exec_result == "no_sql_generated" or not predicted_sql:
        return "no_sql"
    if exec_result == "empty_result":
        if trace_stats.get("sql_errors"):
            return "sql_execution_error"
        return "empty_result"
    if trace_stats.get("hit_recursion_limit"):
        return "recursion_limit"
    if trace_stats.get("sql_errors"):
        return "sql_execution_error"
    return "result_mismatch"


def get_gold_preview(instance_id: str) -> str:
    """Return a compact preview of the gold result CSV(s)."""
    pattern = re.compile(rf"^{re.escape(instance_id)}(_[a-z])?\.csv$")
    gold_files = sorted(GOLD_EXEC_DIR / f for f in os.listdir(GOLD_EXEC_DIR) if pattern.match(f))
    if not gold_files:
        return ""
    try:
        df = pd.read_csv(gold_files[0])
        return df.head(5).to_string(index=False)
    except Exception:
        return ""


def log_agent_trace(
    thread,
    instance_id: str,
    full: bool = False,
    trace_dir: Path | None = None,
    run_meta: dict | None = None,
) -> dict:
    """Print the full agent conversation trace, write to JSON, and return trace stats."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    try:
        meta = thread.meta()
    except Exception as e:
        print(f"  [trace] thread.meta() failed: {e}")
        return {}

    messages = meta.get("messages", [])
    if not messages:
        print(f"  [trace] no messages in thread state for {instance_id}")
        return {}

    stats = extract_trace_stats(messages)

    if trace_dir is not None:
        trace_dir.mkdir(parents=True, exist_ok=True)
        dump = []

        # Leading metadata block for easy offline analysis
        dump.append({
            "_meta": True,
            "instance_id": instance_id,
            "model": (run_meta or {}).get("model"),
            "api_base_url": (run_meta or {}).get("api_base_url"),
            "timestamp": (run_meta or {}).get("timestamp"),
            "n_agent_steps": stats["n_agent_steps"],
            "n_sql_attempts": stats["n_sql_attempts"],
            "n_search_calls": stats["n_search_calls"],
            "hit_recursion_limit": stats["hit_recursion_limit"],
            "n_sql_errors": len(stats["sql_errors"]),
            "tool_call_sequence": stats["tool_call_sequence"],
            "search_score_avg": stats["search_score_avg"],
            "tool_call_log": stats["tool_call_log"],
            "total_input_tokens": stats.get("total_input_tokens"),
            "total_output_tokens": stats.get("total_output_tokens"),
        })

        step = 0
        for m in messages:
            entry: dict = {
                "type": type(m).__name__,
                "content": m.content if isinstance(m.content, (str, list, dict)) else str(m.content),
            }
            if isinstance(m, AIMessage):
                step += 1
                entry["step"] = step
                entry["tool_calls"] = [
                    {"name": tc.get("name"), "args": tc.get("args", {}), "id": tc.get("id")}
                    for tc in (m.tool_calls or [])
                ]
            if isinstance(m, ToolMessage):
                entry["name"] = getattr(m, "name", None)
                entry["tool_call_id"] = getattr(m, "tool_call_id", None)
                entry["is_error"] = _is_sql_error(str(m.content))
            dump.append(entry)

        out_file = trace_dir / f"{instance_id}.json"
        out_file.write_text(json.dumps(dump, indent=2, default=str))
        print(f"  [trace] {stats['n_agent_steps']} steps | {stats['n_sql_attempts']} SQL attempts | "
              f"{stats['n_search_calls']} searches | {len(stats['sql_errors'])} SQL errors → {out_file}")

    sys_cap = 10_000 if full else 200
    user_cap = 10_000 if full else 300
    ai_cap = 10_000 if full else 400
    sql_cap = 10_000 if full else 500
    tool_cap = 10_000 if full else 400
    args_cap = 10_000 if full else 200

    print(f"\n{'─'*60}")
    print(f"AGENT TRACE  [{instance_id}]  ({len(messages)} messages, {stats['n_agent_steps']} AI steps)")
    print(f"{'─'*60}")

    step = 0
    for i, msg in enumerate(messages):
        try:
            if isinstance(msg, SystemMessage):
                content = str(msg.content)
                print(f"\n[SYS] {content[:sys_cap].strip()}{'...' if len(content) > sys_cap else ''}")

            elif isinstance(msg, HumanMessage):
                print(f"\n[USER] {str(msg.content)[:user_cap]}")

            elif isinstance(msg, AIMessage):
                step += 1
                text = msg.content if isinstance(msg.content, str) else ""
                if isinstance(msg.content, list):
                    text = " ".join(p.get("text", "") for p in msg.content if isinstance(p, dict))
                if text and text.strip():
                    print(f"\n[AI step {step}] {text.strip()[:ai_cap]}")

                for tc in (msg.tool_calls or []):
                    name = tc.get("name", "?")
                    args = tc.get("args", {}) or {}
                    if name == "run_sql_query":
                        print(f"\n  → [{step}] run_sql_query")
                        print(f"    SQL: {str(args.get('sql', ''))[:sql_cap]}")
                    elif name == "search_context":
                        print(f"\n  → [{step}] search_context({args.get('retrieve_text','')!r})")
                    elif name == "submit_result":
                        print(f"\n  → [{step}] submit_result(query_id={args.get('query_id')!r})")
                        print(f"    description: {str(args.get('result_description',''))[:args_cap]}")
                    else:
                        print(f"\n  → [{step}] {name}  args={str(args)[:args_cap]}")

            elif isinstance(msg, ToolMessage):
                name = getattr(msg, "name", None) or "tool"
                content_str = str(msg.content)
                is_err = _is_sql_error(content_str)
                tag = " [ERROR]" if is_err else ""
                preview = content_str[:tool_cap]
                suffix = "" if len(content_str) <= tool_cap else f"  [+{len(content_str)-tool_cap} chars]"
                print(f"\n  ← {name}{tag} ({len(content_str)} chars): {preview}{suffix}")
        except Exception as e:
            print(f"  [trace] error printing message {i} ({type(msg).__name__}): {e}")

    print(f"\n{'─'*60}")
    return stats


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Spider 2.0 local track benchmark for databao-agent")
    parser.add_argument("--instances", type=str, help="Comma-separated instance IDs (e.g. local003,local008)")
    parser.add_argument("--skip-instances", type=str, help="Comma-separated instance IDs to skip")
    parser.add_argument("--limit", type=int, help="Run only first N questions")
    parser.add_argument("--model", type=str, default=os.environ.get("MODEL", "gpt-4.1"),
                        help="Model name (e.g. gpt-4.1, google_vertexai:gemini-2.5-pro, gemini-2.5-pro)")
    parser.add_argument("--api-base-url", type=str, default=os.environ.get("API_BASE_URL"),
                        help="Base URL for OpenAI-compatible API (optional)")
    parser.add_argument(
        "--vertex-project",
        type=str,
        default=os.environ.get("VERTEX_PROJECT", "lunar-geography-433410-n6"),
        help="Vertex AI project id (used for Gemini on Vertex)",
    )
    parser.add_argument(
        "--vertex-location",
        type=str,
        default=os.environ.get("VERTEX_LOCATION", "us-central1"),
        help="Vertex AI location (used for Gemini on Vertex)",
    )
    parser.add_argument(
        "--google-application-credentials",
        type=str,
        default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        help="Path to service-account JSON for Vertex auth",
    )
    parser.add_argument("--output", type=str, help="Output CSV file path")
    parser.add_argument(
        "--status-file",
        type=str,
        default=None,
        metavar="PATH",
        help="JSONL checkpoint: one JSON object per completed instance (score, score_detail, "
        "error_category, …) flushed to disk after each question. "
        "Default: same basename as the CSV with suffix .status.jsonl. "
        "Pass an empty string to disable.",
    )
    parser.add_argument("--full-trace", action="store_true",
                        help="Print agent traces without truncating message bodies / tool results.")
    parser.add_argument("--trace-dir", type=str,
                        help="Directory to write per-question trace JSON (default: logs/traces/<timestamp>).")
    parser.add_argument("--no-trace", action="store_true",
                        help="Disable trace JSON writing entirely.")
    parser.add_argument(
        "--debug-progress",
        action="store_true",
        help="Print timestamped progress logs for setup and execution steps (useful when runs appear frozen).",
    )
    parser.add_argument(
        "--dce-duckdb",
        type=str,
        default=os.environ.get("DCE_DUCKDB", str(DCE_VECTOR_INDEX)),
        help="Path to the DCE vector index file (dce.duckdb) for search_context. "
        f"Default: {DCE_VECTOR_INDEX} or env DCE_DUCKDB.",
    )
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.no_trace:
        trace_dir = None
    elif args.trace_dir:
        trace_dir = Path(args.trace_dir)
    else:
        trace_dir = CAPSTONE_DIR / "logs" / "traces" / f"run_{timestamp}"

    instances = args.instances.split(",") if args.instances else None
    skip_instances = args.skip_instances.split(",") if args.skip_instances else None
    questions = load_questions(instances=instances, skip_instances=skip_instances, limit=args.limit)

    if not questions:
        print("No questions matched the filters.")
        sys.exit(1)

    dce_vector_index = Path(args.dce_duckdb).expanduser().resolve()
    if not dce_vector_index.is_file():
        print(f"ERROR: DCE vector index not found: {dce_vector_index}")
        print("Build or copy the enriched index to this path, or pass --dce-duckdb <path>.")
        sys.exit(1)

    if skip_instances:
        print(f"Skipping {len(skip_instances)} instance(s)")

    standards = load_eval_standards()
    model_name = args.model
    api_base_url = args.api_base_url
    vertex_project = args.vertex_project
    vertex_location = args.vertex_location
    google_application_credentials = args.google_application_credentials

    run_meta = {
        "model": model_name,
        "api_base_url": api_base_url,
        "vertex_project": vertex_project,
        "vertex_location": vertex_location,
        "timestamp": timestamp,
        "dce_vector_index": str(dce_vector_index),
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    output_path = Path(args.output or (RESULTS_DIR / f"spider2_results_{timestamp}.csv")).resolve()
    if args.status_file == "":
        status_path: Path | None = None
    elif args.status_file:
        status_path = Path(args.status_file).resolve()
    else:
        status_path = output_path.with_name(f"{output_path.stem}.status.jsonl")

    print(f"Running {len(questions)} questions | model: {model_name}")
    print(f"Results CSV:  {output_path}")
    if status_path:
        print(f"Status JSONL: {status_path}  (checkpoint after each instance)")
    print(f"DCE vector index: {dce_vector_index}")
    if api_base_url:
        print(f"API base URL: {api_base_url}")
    if "gemini" in model_name.lower() or model_name.startswith("google_vertexai:"):
        print(f"Vertex:       {vertex_project} / {vertex_location}")
        if google_application_credentials:
            print(f"Credentials:  {google_application_credentials}")
        else:
            print("Credentials:  using ambient ADC (no GOOGLE_APPLICATION_CREDENTIALS provided)")
    if trace_dir:
        print(f"Trace dir:    {trace_dir}")

    fieldnames = [
        "instance_id", "db", "question", "external_knowledge",
        "predicted_sql", "execution_result", "score", "score_detail",
        "error_category", "error",
        "n_agent_steps", "n_sql_attempts", "n_search_calls",
        "tool_call_sequence", "search_score_avg",
        "sql_errors", "search_queries",
        "gold_result_preview", "pred_result_preview",
        "model", "time_s",
        "total_input_tokens", "total_output_tokens",
    ]

    correct = 0
    total_scored = 0
    errors = 0
    run_input_tokens = 0
    run_output_tokens = 0

    if status_path:
        status_path.parent.mkdir(parents=True, exist_ok=True)
    status_cm = open(status_path, "w", encoding="utf-8") if status_path else nullcontext()

    with open(output_path, "w", newline="", encoding="utf-8") as csvf, status_cm as statusf:
        writer = csv.DictWriter(csvf, fieldnames=fieldnames)
        writer.writeheader()
        csvf.flush()
        _fsync_text_file(csvf)

        for i, q in enumerate(questions):
            instance_id = q["instance_id"]
            db_name = q["db"]
            question = q["question"]
            ext_doc = q.get("external_knowledge")

            print(f"\n[{i+1}/{len(questions)}] {instance_id} ({db_name})")
            print(f"  Q: {question[:100]}...")
            if ext_doc:
                print(f"  external_knowledge: {ext_doc}")

            db_path = get_db_path(db_name)
            if not db_path:
                print(f"  ERROR: SQLite file not found for '{db_name}'")
                writer.writerow({
                    "instance_id": instance_id, "db": db_name, "question": question,
                    "external_knowledge": ext_doc or "",
                    "predicted_sql": "", "execution_result": "db_missing",
                    "score": 0, "score_detail": "db_missing",
                    "error_category": "db_missing", "error": "db not found",
                    "n_agent_steps": 0, "n_sql_attempts": 0, "n_search_calls": 0,
                    "tool_call_sequence": "", "search_score_avg": "",
                    "sql_errors": "", "search_queries": "",
                    "gold_result_preview": "", "pred_result_preview": "",
                    "model": model_name, "time_s": 0,
                    "total_input_tokens": "",
                    "total_output_tokens": "",
                })
                csvf.flush()
                _fsync_text_file(csvf)
                if statusf is not None:
                    write_status_jsonl(statusf, {
                        "ts": datetime.now().isoformat(timespec="seconds"),
                        "index": i + 1,
                        "total": len(questions),
                        "instance_id": instance_id,
                        "db": db_name,
                        "score": 0,
                        "score_detail": "db_missing",
                        "error_category": "db_missing",
                        "execution_result": "db_missing",
                        "error": "db not found",
                        "time_s": 0,
                    })
                errors += 1
                continue

            t0 = time.time()
            predicted_sql = ""
            exec_result = "not_run"
            score = 0
            score_detail = ""
            error = ""
            pred_df = None
            thread = None
            trace_stats: dict = {}

            tmp_dce = None
            try:
                agent, tmp_dce = setup_agent(
                    db_path=db_path,
                    model_name=model_name,
                    api_base_url=api_base_url,
                    external_knowledge_doc=ext_doc,
                    vertex_project=vertex_project,
                    vertex_location=vertex_location,
                    google_application_credentials=google_application_credentials,
                    debug_progress=args.debug_progress,
                    dce_vector_index=dce_vector_index,
                )
                _progress(args.debug_progress, "Creating thread")
                thread = agent.thread()
                _progress(args.debug_progress, "Starting thread.ask(question)")
                thread.ask(question)
                _progress(args.debug_progress, "thread.ask(question) finished")

                predicted_sql = thread.code() or ""
                if predicted_sql:
                    print(f"  SQL: {predicted_sql[:120]}...")
                else:
                    print("  SQL: (none generated)")

                pred_df = thread.df()

                if pred_df is not None and not pred_df.empty:
                    exec_result = f"{len(pred_df)} rows"
                    score, score_detail = score_against_gold(pred_df, instance_id, standards)
                    if score == 1:
                        correct += 1
                    total_scored += 1
                    print(f"  RESULT: {exec_result} | score: {score} ({score_detail})")
                elif predicted_sql:
                    exec_result = "empty_result"
                    score, score_detail = score_against_gold(pd.DataFrame(), instance_id, standards)
                    total_scored += 1
                    print(f"  RESULT: empty df | score: {score}")
                else:
                    exec_result = "no_sql_generated"
                    score = 0
                    score_detail = "no_sql"
                    total_scored += 1
                    errors += 1
                    print("  RESULT: no SQL generated")

            except Exception as e:
                error = str(e)[:500]
                exec_result = "agent_error"
                score = 0
                score_detail = "agent_error"
                total_scored += 1
                errors += 1
                print(f"  AGENT ERROR: {e}")

            # Always dump the full agent trace for visibility
            if thread is not None:
                try:
                    trace_stats = log_agent_trace(
                        thread, instance_id,
                        full=args.full_trace,
                        trace_dir=trace_dir,
                        run_meta=run_meta,
                    )
                except Exception as trace_err:
                    print(f"  [trace] log_agent_trace raised: {trace_err}")

            if tmp_dce is not None:
                shutil.rmtree(tmp_dce, ignore_errors=True)

            elapsed = round(time.time() - t0, 2)

            error_category = classify_error(score, exec_result, error, trace_stats, predicted_sql)
            gold_preview = get_gold_preview(instance_id) if score == 0 else ""
            pred_preview = ""
            if pred_df is not None and not pred_df.empty and score == 0:
                pred_preview = pred_df.head(5).to_string(index=False)

            in_tok = trace_stats.get("total_input_tokens", 0) or 0
            out_tok = trace_stats.get("total_output_tokens", 0) or 0
            run_input_tokens += in_tok
            run_output_tokens += out_tok
            tok_str = f" | tokens: {in_tok}in/{out_tok}out" if (in_tok or out_tok) else ""
            print(f"  category: {error_category} | steps: {trace_stats.get('n_agent_steps',0)} | "
                  f"sql_attempts: {trace_stats.get('n_sql_attempts',0)} | "
                  f"searches: {trace_stats.get('n_search_calls',0)} | {elapsed}s{tok_str}")

            writer.writerow({
                "instance_id": instance_id,
                "db": db_name,
                "question": question,
                "external_knowledge": ext_doc or "",
                "predicted_sql": predicted_sql,
                "execution_result": exec_result,
                "score": score,
                "score_detail": score_detail,
                "error_category": error_category,
                "error": error,
                "n_agent_steps": trace_stats.get("n_agent_steps", ""),
                "n_sql_attempts": trace_stats.get("n_sql_attempts", ""),
                "n_search_calls": trace_stats.get("n_search_calls", ""),
                "tool_call_sequence": trace_stats.get("tool_call_sequence", ""),
                "search_score_avg": trace_stats.get("search_score_avg", ""),
                "sql_errors": " ||| ".join(trace_stats.get("sql_errors", [])),
                "search_queries": " ||| ".join(trace_stats.get("search_queries", [])),
                "gold_result_preview": gold_preview,
                "pred_result_preview": pred_preview,
                "model": model_name,
                "time_s": elapsed,
                "total_input_tokens": trace_stats.get("total_input_tokens", ""),
                "total_output_tokens": trace_stats.get("total_output_tokens", ""),
            })
            csvf.flush()
            _fsync_text_file(csvf)
            if statusf is not None:
                write_status_jsonl(statusf, {
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "index": i + 1,
                    "total": len(questions),
                    "instance_id": instance_id,
                    "db": db_name,
                    "score": score,
                    "score_detail": score_detail,
                    "error_category": error_category,
                    "execution_result": exec_result,
                    "error": error,
                    "time_s": elapsed,
                    "n_agent_steps": trace_stats.get("n_agent_steps", ""),
                    "n_sql_attempts": trace_stats.get("n_sql_attempts", ""),
                    "n_search_calls": trace_stats.get("n_search_calls", ""),
                })

    # Summary
    print(f"\n{'='*60}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"Total questions:   {len(questions)}")
    print(f"Scored:            {total_scored}")
    print(f"Correct:           {correct} / {total_scored}  ({100*correct//max(total_scored,1)}%)")
    print(f"Errors/no-SQL:     {errors}")
    print(f"\nResults → {output_path}")
    if status_path:
        print(f"Status  → {status_path}")
    if trace_dir:
        print(f"Traces  → {trace_dir}/")
    print(f"\nToken usage (this run):")
    print(f"  Input:  {run_input_tokens:,}  tokens")
    print(f"  Output: {run_output_tokens:,}  tokens")
    print(f"  Total:  {run_input_tokens + run_output_tokens:,}  tokens")
    if total_scored > 0:
        avg_in = run_input_tokens // total_scored
        avg_out = run_output_tokens // total_scored
        print(f"  Avg/question: {avg_in:,} in / {avg_out:,} out")
    print(f"\nNote: Spider2-lite official score = correct / 547 (all tracks)")
    print(f"      Local-track score = {correct} / {total_scored} ({100*correct//max(total_scored,1)}%)")


if __name__ == "__main__":
    main()
