#!/usr/bin/env python3
"""
Spider 2.0 (local SQLite track) benchmark runner for databao-agent.

Runs Spider 2.0 local questions through databao-agent and evaluates by comparing
predicted SQL output DataFrames against the official exec_result gold CSVs
(same logic as Spider2's evaluate.py).

Usage:
    # Run all local questions (requires vLLM server running)
    uv --project ../databao-agent run python spider2_benchmark.py

    # Run specific instances
    uv --project ../databao-agent run python spider2_benchmark.py --instances local003,local008

    # Run first N questions
    uv --project ../databao-agent run python spider2_benchmark.py --limit 10

Environment variables:
    VLLM_HOST    hostname of vLLM server (default: read from logs/vllm_endpoint.txt)
    VLLM_PORT    port of vLLM server (default: 8765)
    VLLM_MODEL   model name (default: Qwen/Qwen3-32B-AWQ)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
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
SPIDER2_DIR = Path("/data/user_data/sandeep3/personal/capstone/Spider2/spider2-lite")
SQLITE_DIR = SPIDER2_DIR / "resource/databases/spider2-localdb"
EVAL_SUITE_DIR = SPIDER2_DIR / "evaluation_suite"
GOLD_EXEC_DIR = EVAL_SUITE_DIR / "gold/exec_result"
EVAL_JSONL = EVAL_SUITE_DIR / "gold/spider2lite_eval.jsonl"
DOCS_DIR = SPIDER2_DIR / "resource/documents"
QUESTIONS_FILE = SPIDER2_DIR / "spider2-lite.jsonl"
DCE_PROJECT_DIR = Path("/data/user_data/sandeep3/personal/capstone/spider2-dce")
RESULTS_DIR = CAPSTONE_DIR / "results"
ENDPOINT_FILE = CAPSTONE_DIR / "logs/vllm_endpoint.txt"

EXCLUDE_DBS = {"oracle_sql", "stacking"}  # broken views crash DuckDB schema inspection


# ── Data loading ─────────────────────────────────────────────────────────────

def load_questions(instances=None, limit=None):
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


def get_vllm_endpoint():
    host = os.environ.get("VLLM_HOST")
    port = os.environ.get("VLLM_PORT", "8765")
    model = os.environ.get("VLLM_MODEL", "QuantTrio/GLM-4.7-Flash-AWQ")
    if host:
        return f"http://{host}:{port}", model
    if ENDPOINT_FILE.exists():
        lines = ENDPOINT_FILE.read_text().strip().splitlines()
        node, node_port = lines[0].strip().rsplit(":", 1)
        for line in lines:
            if line.startswith("Model:"):
                model = line.split(":", 1)[1].strip()
        return f"http://{node}:{node_port}", model
    print("WARNING: No vLLM endpoint found. Set VLLM_HOST or run serve_vllm.slurm first.")
    return None, model


# ── DuckDB capability hints injected into every agent context ─────────────────
# Prevents the agent from refusing statistical/regression questions as "ML tasks".
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

def _make_temp_dce_project(db_name: str) -> Path:
    """Create a minimal per-question DCE project dir.

    Contains only the src YAML for the relevant database and symlinks/copies
    the shared dce.duckdb so search_context works without loading all 28 DBs.
    """
    tmp = Path(tempfile.mkdtemp(prefix=f"dce_{db_name.lower()}_"))

    # Project config
    shutil.copy(DCE_PROJECT_DIR / "dce.ini", tmp / "dce.ini")

    # Only this database's source YAML
    (tmp / "src" / "databases").mkdir(parents=True)
    src_yaml = DCE_PROJECT_DIR / "src" / "databases" / f"{db_name.lower()}.yaml"
    if src_yaml.exists():
        shutil.copy(src_yaml, tmp / "src" / "databases" / src_yaml.name)

    # output/ gets its own directory (so init_or_get_dce_project can write there freely),
    # but dce.duckdb is symlinked from the shared index (read-only search, never written).
    out = tmp / "output"
    out.mkdir()
    (out / "databases").mkdir()

    shared_db = DCE_PROJECT_DIR / "output" / "dce.duckdb"
    if shared_db.exists():
        (out / "dce.duckdb").symlink_to(shared_db)

    # Copy the enriched output YAML so the domain has descriptions available
    out_yaml = DCE_PROJECT_DIR / "output" / "databases" / f"{db_name.lower()}.yaml"
    if out_yaml.exists():
        shutil.copy(out_yaml, out / "databases" / out_yaml.name)

    return tmp


# ── <think>-tag stripper ──────────────────────────────────────────────────────
#
# Thinking models (GLM-4.7-Flash, DeepSeek R1, Qwen3 with thinking enabled, etc.)
# emit verbose <think>...</think> monologue before each tool call. The model still
# benefits from this on the *current* turn (chain-of-thought is preserved during
# generation), but if we let the raw assistant message flow back into the chat
# history, every subsequent turn re-reads the full prior monologue. Across a
# 16-step agent loop that's thousands of wasted input tokens.
#
# This monkey-patch wraps databao.agent.executors.llm.chat so the *last* message
# in the returned list (the new AIMessage) has its <think> blocks stripped before
# being stored back into LangGraph state. Per-turn quality is unaffected (the
# model still thinks during generation); only the cumulative history shrinks.
#
# Equivalent server-side option: launch vLLM with --reasoning-parser glm45 (the
# vLLM 0.18.1 GLM-4.5 family parser, which uses the DeepSeek V3 thinking-parser
# implementation). When that's enabled vLLM splits reasoning_content from
# content automatically, and this client-side patch becomes a no-op.

# GLM-4.7-Flash chat template prepends <think> as part of the assistant prefill,
# so the model only emits "reasoning</think>response" in `content` — no opening
# tag in the message string. We split on the LAST </think> to separate reasoning
# from narrative. If there's substantive narrative after </think>, we keep it.
# If there's no narrative (common: GLM often emits only tool_calls after </think>),
# we replace the reasoning with a brief LLM-generated summary so the model has a
# decision anchor when re-reading its history. The summary call is capped at
# max_tokens=120 and hard-truncated to 500 chars so a runaway summary can't
# balloon history anyway.

_SUMMARY_MAX_CHARS = 500
_SUMMARY_MAX_TOKENS = 120
_SUMMARY_MIN_REASONING_CHARS = 80  # below this, don't bother summarizing

_SUMMARY_SYSTEM_PROMPT = (
    "You compress an AI agent's internal reasoning into a terse note the agent "
    "can use as a memory anchor. Output at most 2 short sentences. Focus on: "
    "(1) the decision the agent made, (2) WHY. Do not echo the reasoning; "
    "extract the conclusion. Do not include <think> tags. Be direct."
)

_summary_client = None  # OpenAI client pointed at vLLM, configured via _configure_summarizer
_summary_model_name = None


def _configure_summarizer(vllm_base_url: str | None, model_name: str) -> None:
    """Initialize the summarizer client once we know the vLLM endpoint."""
    global _summary_client, _summary_model_name
    if _summary_client is not None or not vllm_base_url:
        return
    try:
        from openai import OpenAI
    except ImportError:
        return
    _summary_client = OpenAI(base_url=f"{vllm_base_url.rstrip('/')}/v1", api_key="EMPTY", timeout=60)
    _summary_model_name = model_name


def _get_summary_client():
    return _summary_client, _summary_model_name


def _summarize_reasoning(reasoning: str) -> str:
    """Ask the LLM to compress a block of reasoning into ≤2 sentences.

    Falls back to the tail of the reasoning (last ~400 chars, trimmed to sentence
    boundary) if the summary call fails or the endpoint is not configured.
    """
    reasoning = reasoning.strip()
    if len(reasoning) < _SUMMARY_MIN_REASONING_CHARS:
        return reasoning[:_SUMMARY_MAX_CHARS]

    client, model_name = _get_summary_client()
    if client is not None:
        try:
            resp = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Reasoning:\n{reasoning}\n\nCompressed note:"},
                ],
                temperature=0.0,
                max_tokens=_SUMMARY_MAX_TOKENS,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            summary = (resp.choices[0].message.content or "").strip()
            # Strip any stray think tags the summarizer might have produced
            summary = re.sub(r"<think>.*?</think>\s*", "", summary, flags=re.DOTALL)
            summary = re.sub(r"</?think>", "", summary).strip()
            if summary:
                return summary[:_SUMMARY_MAX_CHARS]
        except Exception as e:
            print(f"  [think-stripper] summary call failed: {e}; falling back to tail heuristic")

    # Fallback: last ~400 chars trimmed to a sentence boundary.
    tail = reasoning[-400:]
    # Find first sentence start in the tail so we don't land mid-sentence.
    m = re.search(r"(?<=[.!?])\s+", tail)
    if m:
        tail = tail[m.end():]
    return tail.strip()[:_SUMMARY_MAX_CHARS]


def _strip_think_from_text(text: str) -> str:
    # Unclosed <think> with no closer: truncated generation. Strip everything
    # from the opener onward and summarize what was cut.
    if "<think>" in text and "</think>" not in text:
        pre, _, rest = text.partition("<think>")
        summary = _summarize_reasoning(rest)
        return ((pre.strip() + "\n" + summary).strip() if pre.strip() else summary)

    if "</think>" not in text:
        return text  # no reasoning at all

    # Split on LAST </think> so any intermediate reasoning is fully captured as
    # "reasoning" and whatever the model wrote after its final </think> is
    # treated as narrative output.
    idx = text.rfind("</think>")
    reasoning = text[:idx]
    narrative = text[idx + len("</think>"):]
    # Clean any embedded think tags inside the reasoning block itself.
    reasoning = re.sub(r"</?think>", "", reasoning)

    if narrative.strip():
        # The model emitted real narrative after </think> — keep that verbatim,
        # drop the reasoning entirely. Narrative is already a natural anchor.
        return narrative.lstrip()

    # No post-</think> narrative → summarize the reasoning so the model has
    # SOMETHING to re-read when parsing its own history on the next turn.
    return _summarize_reasoning(reasoning)


def _strip_think_from_message_content(content):
    """Strip <think>...</think> blocks from a langchain message content field.

    langchain messages allow content as either str or list[dict]. We handle both.
    """
    if isinstance(content, str):
        return _strip_think_from_text(content)
    if isinstance(content, list):
        out = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                stripped = _strip_think_from_text(block["text"])
                if stripped:
                    out.append({**block, "text": stripped})
            else:
                out.append(block)
        return out
    return content


_THINK_PATCH_INSTALLED = False


def _install_think_stripper_once() -> None:
    """Monkey-patch databao.agent.executors.llm.chat to strip <think> from responses."""
    global _THINK_PATCH_INSTALLED
    if _THINK_PATCH_INSTALLED:
        return
    from databao.agent.executors import llm as _databao_llm

    _orig_chat = _databao_llm.chat

    def _chat_strip_think(messages, config, model=None):
        result = _orig_chat(messages, config, model)
        if not result:
            return result
        last = result[-1]
        # Only strip if last message has a `content` attribute (AIMessage does).
        if hasattr(last, "content") and last.content:
            new_content = _strip_think_from_message_content(last.content)
            if new_content != last.content:
                # langchain messages are pydantic; use model_copy to update in-place semantics.
                if hasattr(last, "model_copy"):
                    new_last = last.model_copy(update={"content": new_content})
                else:
                    last.content = new_content
                    new_last = last
                result = [*result[:-1], new_last]
        return result

    _databao_llm.chat = _chat_strip_think
    # graph.py imported `chat` directly into its module namespace, so patch that too.
    try:
        from databao.agent.executors.lighthouse import graph as _lh_graph
        if hasattr(_lh_graph, "chat"):
            _lh_graph.chat = _chat_strip_think
    except Exception:
        pass
    _THINK_PATCH_INSTALLED = True
    print("  [think-stripper] installed: <think>...</think> blocks will be stripped from AIMessage content before history reuse")


def setup_agent(db_path: Path, vllm_base_url: str | None, model_name: str, external_knowledge_doc: str | None = None):
    """Create a databao agent with DCE retrieval enabled for a single database."""
    import databao.agent as bao
    from databao.agent.configs.agent import AgentConfig
    from databao.agent.configs.llm import LLMConfig

    _install_think_stripper_once()
    _configure_summarizer(vllm_base_url, model_name)

    is_qwen3 = "Qwen3" in model_name or "qwen3" in model_name.lower()

    if vllm_base_url:
        llm_config = LLMConfig(
            name=model_name,
            api_base_url=f"{vllm_base_url}/v1",
            temperature=0.0,
            # 4096 output tokens: on A100 80GB at max_model_len=60000 we no longer need
            # to starve max_tokens. Lifted from 1024 (the A6000 setting) because GLM's
            # verbose pre-tool-call reasoning was being truncated mid-thought, causing
            # the final assistant turn to land with empty tool_calls and the agent to
            # terminate without emitting SQL (observed on local022, local025).
            max_tokens=4096,
            timeout=180,
            use_responses_api=False,
            # Qwen3 only: disable thinking mode via chat_template_kwargs per-request.
            # GLM-4.7-Flash does not have thinking mode, so this is skipped for GLM.
            **({"model_kwargs": {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}}
               if is_qwen3 else {}),
        )
    else:
        ollama_model = os.environ.get("OLLAMA_SQL_MODEL", "glm4.7-flash:latest")
        llm_config = LLMConfig(
            name=f"ollama:{ollama_model}",
            temperature=0.0,
            max_tokens=8192,
            use_responses_api=False,
        )

    agent_config = AgentConfig(recursion_limit=30, min_retrievals=1)

    # Build a temp DCE project with only this DB's YAML — enables search_context tool
    # without loading all 28 databases into DuckDB simultaneously.
    tmp_dce = _make_temp_dce_project(db_path.stem)

    domain = bao.domain(project_dir=tmp_dce)
    domain.add_description(DUCKDB_HINTS)

    if external_knowledge_doc:
        doc_path = DOCS_DIR / external_knowledge_doc
        if doc_path.exists():
            doc_text = doc_path.read_text()
            # Guard against very large external knowledge docs consuming too much context.
            # At ~4 chars/token, 20K chars ≈ 5K tokens. GLM context is only 28K, so
            # haversine_formula.md and similar long docs must be tightly truncated.
            if len(doc_text) > 20_000:
                doc_text = doc_text[:20_000] + "\n\n[... external knowledge truncated ...]"
                print(f"  WARN: external_knowledge doc truncated to 20K chars")
            domain.add_description(doc_text)
        else:
            print(f"  WARN: external_knowledge doc not found: {doc_path}")

    from databao.agent.executors import LighthouseExecutor

    executor = LighthouseExecutor()
    # Cap schema at ~60K chars (~15K tokens). LighthouseExecutor has a 3-tier fallback:
    #   1. Full schema with columns (if ≤ 60K chars)
    #   2. Table names only, no columns (if > 60K chars) — agent uses search_context for details
    #   3. Schema overview only (if still > 60K chars)
    # Default is 250K chars which doesn't help on a 40K-token context model.
    executor._max_schema_summary_length = 60_000
    # Override _graph_recursion_limit (default 50 in base.py) so LangGraph actually
    # respects our recursion_limit. base.py uses max(self._graph_recursion_limit,
    # agent_config.recursion_limit), so we must set both to cap loop depth.
    # 30 agent steps × 2 LangGraph nodes/step = 60 LangGraph nodes.
    # Bumped from 24/48 after local002 was 2 steps away from a correct answer at step 24.
    # Doom-loop prompt rules (3-consecutive-error cutoff) are the primary guard against
    # runaway loops; the step limit is a hard backstop only.
    executor._graph_recursion_limit = 60

    # auto_output_modality=False: skip the post-submit Vega visualizer agent. Spider 2.0
    # scoring only needs SQL + dataframe; the visualizer fires extra LLM calls after
    # submit_result that can hit the 180s read timeout and bubble up an httpx.ReadTimeout
    # — which the benchmark loop then mis-marks as a full question failure even though
    # submit_result already succeeded (observed on local054 in the 15-winner A100 run).
    agent = bao.agent(domain=domain, llm_config=llm_config, agent_config=agent_config,
                      data_executor=executor, stream_ask=False, auto_output_modality=False)
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
    """
    Compare pred_df against all gold exec_result CSVs for this instance.
    Returns (score 0/1, description).
    """
    # Find gold files: local002_a.csv, local002_b.csv, etc.
    pattern = re.compile(rf"^{re.escape(instance_id)}(_[a-z])?\.csv$")
    gold_files = sorted(GOLD_EXEC_DIR / f for f in os.listdir(GOLD_EXEC_DIR) if pattern.match(f))

    if not gold_files:
        return 0, "no_gold_files"

    standard = standards.get(instance_id, {})
    condition_cols = standard.get("condition_cols")
    ignore_order = standard.get("ignore_order", False)

    # Flatten nested condition_cols if needed (Spider2 stores them as list of lists)
    if isinstance(condition_cols, list) and condition_cols and isinstance(condition_cols[0], list):
        flat_cols = condition_cols  # multiple gold files → list of per-gold condition_cols
    else:
        flat_cols = [condition_cols] * len(gold_files)

    for gold_file, cols in zip(gold_files, flat_cols):
        try:
            gold_df = pd.read_csv(gold_file)
            if compare_dataframes(pred_df, gold_df, condition_cols=cols, ignore_order=ignore_order):
                return 1, f"matches {gold_file.name}"
        except Exception as e:
            continue

    return 0, "result_mismatch"


# ── Agent trace logging ───────────────────────────────────────────────────────

def log_agent_trace(thread, instance_id: str, full: bool = False, trace_dir: Path | None = None) -> None:
    """Print the full agent conversation trace: every tool call and its result.

    If `full` is True, no truncation is applied to message bodies / tool results /
    SQL previews. If `trace_dir` is set, the raw message history is also written
    as a JSON file at `<trace_dir>/<instance_id>.json` for offline inspection.
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    try:
        meta = thread.meta()
    except Exception as e:
        print(f"  [trace] thread.meta() failed: {e}")
        return

    messages = meta.get("messages", [])
    if not messages:
        print(f"  [trace] no messages in thread state for {instance_id}")
        return

    # Optional raw JSON dump (lossless, for offline inspection)
    if trace_dir is not None:
        trace_dir.mkdir(parents=True, exist_ok=True)
        dump = []
        for m in messages:
            entry = {
                "type": type(m).__name__,
                "content": m.content if isinstance(m.content, (str, list, dict)) else str(m.content),
            }
            if isinstance(m, AIMessage):
                entry["tool_calls"] = [
                    {"name": tc.get("name"), "args": tc.get("args", {}), "id": tc.get("id")}
                    for tc in (m.tool_calls or [])
                ]
            if isinstance(m, ToolMessage):
                entry["name"] = getattr(m, "name", None)
                entry["tool_call_id"] = getattr(m, "tool_call_id", None)
            dump.append(entry)
        out_file = trace_dir / f"{instance_id}.json"
        out_file.write_text(json.dumps(dump, indent=2, default=str))
        print(f"  [trace] wrote {len(dump)} messages → {out_file}")

    sys_cap = 10_000 if full else 200
    user_cap = 10_000 if full else 300
    ai_cap = 10_000 if full else 400
    sql_cap = 10_000 if full else 300
    tool_cap = 10_000 if full else 400
    args_cap = 10_000 if full else 200

    print(f"\n{'─'*60}")
    print(f"AGENT TRACE  [{instance_id}]  ({len(messages)} messages)")
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
                        print(f"\n  → TOOL CALL: run_sql_query")
                        print(f"    SQL: {str(args.get('sql', ''))[:sql_cap]}")
                    elif name == "search_context":
                        print(f"\n  → TOOL CALL: search_context(retrieve_text={args.get('retrieve_text','')!r})")
                    elif name == "submit_result":
                        print(f"\n  → TOOL CALL: submit_result(query_id={args.get('query_id')!r})")
                        print(f"    description: {str(args.get('result_description',''))[:args_cap]}")
                    else:
                        print(f"\n  → TOOL CALL: {name}  args={str(args)[:args_cap]}")

            elif isinstance(msg, ToolMessage):
                name = getattr(msg, "name", None) or "tool"
                content_str = str(msg.content)
                preview = content_str[:tool_cap]
                suffix = "" if len(content_str) <= tool_cap else f"  [+{len(content_str)-tool_cap} more chars]"
                print(f"\n  ← TOOL RESULT [{name}] ({len(content_str)} chars): {preview}{suffix}")
        except Exception as e:
            print(f"  [trace] error printing message {i} ({type(msg).__name__}): {e}")

    print(f"\n{'─'*60}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Spider 2.0 local track benchmark for databao-agent")
    parser.add_argument("--instances", type=str, help="Comma-separated instance IDs (e.g. local003,local008)")
    parser.add_argument("--limit", type=int, help="Run only first N questions")
    parser.add_argument("--output", type=str, help="Output CSV file path")
    parser.add_argument("--full-trace", action="store_true",
                        help="Print agent traces without truncating message bodies / tool results.")
    parser.add_argument("--trace-dir", type=str,
                        help="Directory to write per-question raw message JSON for offline inspection.")
    args = parser.parse_args()
    trace_dir = Path(args.trace_dir) if args.trace_dir else None

    instances = args.instances.split(",") if args.instances else None
    questions = load_questions(instances=instances, limit=args.limit)

    if not questions:
        print("No questions matched the filters.")
        sys.exit(1)

    standards = load_eval_standards()
    vllm_base_url, model_name = get_vllm_endpoint()

    print(f"Running {len(questions)} questions | model: {model_name}")
    if vllm_base_url:
        print(f"vLLM endpoint: {vllm_base_url}")

    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = args.output or str(RESULTS_DIR / f"spider2_results_{timestamp}.csv")

    fieldnames = [
        "instance_id", "db", "question", "external_knowledge",
        "predicted_sql", "execution_result", "score", "score_detail", "error", "time_s",
    ]

    correct = 0
    total_scored = 0
    errors = 0

    with open(output_path, "w", newline="") as csvf:
        writer = csv.DictWriter(csvf, fieldnames=fieldnames)
        writer.writeheader()

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
                    "score": 0, "score_detail": "db_missing", "error": "db not found", "time_s": 0,
                })
                csvf.flush()
                errors += 1
                continue

            t0 = time.time()
            predicted_sql = ""
            exec_result = "not_run"
            score = 0
            score_detail = ""
            error = ""
            thread = None

            tmp_dce = None
            try:
                agent, tmp_dce = setup_agent(db_path, vllm_base_url, model_name, ext_doc)
                thread = agent.thread()
                thread.ask(question)

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
                    log_agent_trace(thread, instance_id, full=args.full_trace, trace_dir=trace_dir)
                except Exception as trace_err:
                    # Surface the failure instead of silently dropping the trace
                    print(f"  [trace] log_agent_trace raised: {trace_err}")

            # Clean up per-question temp DCE project dir
            if tmp_dce is not None:
                shutil.rmtree(tmp_dce, ignore_errors=True)

            elapsed = round(time.time() - t0, 2)

            writer.writerow({
                "instance_id": instance_id,
                "db": db_name,
                "question": question,
                "external_knowledge": ext_doc or "",
                "predicted_sql": predicted_sql,
                "execution_result": exec_result,
                "score": score,
                "score_detail": score_detail,
                "error": error,
                "time_s": elapsed,
            })
            csvf.flush()

    # Summary
    print(f"\n{'='*60}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"Total questions:   {len(questions)}")
    print(f"Scored:            {total_scored}")
    print(f"Correct:           {correct} / {total_scored}  ({100*correct//max(total_scored,1)}%)")
    print(f"Errors/no-SQL:     {errors}")
    print(f"\nResults → {output_path}")
    print(f"\nNote: Spider2-lite official score = correct / 547 (all tracks)")
    print(f"      Local-track score = {correct} / {total_scored} ({100*correct//max(total_scored,1)}%)")


if __name__ == "__main__":
    main()
