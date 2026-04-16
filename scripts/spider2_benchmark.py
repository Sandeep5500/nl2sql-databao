from __future__ import annotations
# Force UTF-8 mode on Windows
import os
import sys
if os.name == 'nt' and os.environ.get('PYTHONUTF8') != '1':
    os.environ['PYTHONUTF8'] = '1'
    import subprocess
    try:
        sys.exit(subprocess.run([sys.executable] + sys.argv).returncode)
    except KeyboardInterrupt:
        sys.exit(130)

from pathlib import Path

# Ensure databao-agent is in the path for all imports in this file
CAPSTONE_DIR = Path(__file__).parent.parent.resolve()
agent_path = str(CAPSTONE_DIR / "databao-agent")
if agent_path not in sys.path:
    sys.path.insert(0, agent_path)

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

import argparse
import csv
import json
import math
import re
import shutil
import tempfile
import time
import sqlite3
import pandas as pd
import requests
import urllib.error
from datetime import datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
CAPSTONE_DIR = Path(__file__).parent.parent.resolve()
SPIDER2_DIR = (CAPSTONE_DIR / "Spider2" / "spider2-lite").resolve()
GOLD_EXEC_DIR = (SPIDER2_DIR / "evaluation_suite" / "gold" / "exec_result").resolve()
GOLD_SQL_DIR = (SPIDER2_DIR / "evaluation_suite" / "gold" / "sql").resolve()
SQLITE_DIR = (SPIDER2_DIR / "resource" / "databases" / "spider2-localdb").resolve()
EVAL_SUITE_DIR = (SPIDER2_DIR / "evaluation_suite").resolve()
EVAL_JSONL = (EVAL_SUITE_DIR / "gold" / "spider2lite_eval.jsonl").resolve()
DOCS_DIR = (SPIDER2_DIR / "resource" / "documents").resolve()
QUESTIONS_FILE = (SPIDER2_DIR / "spider2-lite.jsonl").resolve()
DCE_PROJECT_DIR = (CAPSTONE_DIR / "spider2-dce").resolve()
RESULTS_DIR = (CAPSTONE_DIR / "results").resolve()
ENDPOINT_FILE = (CAPSTONE_DIR / "logs" / "vllm_endpoint.txt").resolve()

# Vertex AI Configuration
os.environ["VERTEX_PROJECT"] = os.environ.get("VERTEX_PROJECT", "lunar-geography-433410-n6")
os.environ["VERTEX_LOCATION"] = os.environ.get("VERTEX_LOCATION", "us-central1")

print(f"DEBUG: CAPSTONE_DIR = {CAPSTONE_DIR}")
print(f"DEBUG: DCE_PROJECT_DIR = {DCE_PROJECT_DIR}")
print(f"DEBUG: SQLITE_DIR = {SQLITE_DIR}")

EXCLUDE_DBS = {"oracle_sql", "stacking"}  # broken views crash DuckDB schema inspection

# ── Data loading ─────────────────────────────────────────────────────────────

def load_questions(instances=None, limit=None):
    questions = []
    with open(QUESTIONS_FILE, encoding="utf-8") as f:
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
    with open(EVAL_JSONL, encoding="utf-8") as f:
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
    model = os.environ.get("VLLM_MODEL", "gemini-2.5-pro")
    
    if "gemini" in model.lower() or "google" in model.lower():
        return None, model

    if host:
        return f"http://{host}:{port}", model
    if ENDPOINT_FILE.exists():
        lines = ENDPOINT_FILE.read_text(encoding="utf-8").strip().splitlines()
        node, node_port = lines[0].strip().rsplit(":", 1)
        for line in lines:
            if line.startswith("Model:"):
                model = line.split(":", 1)[1].strip()
        return f"http://{node}:{node_port}", model
    print("WARNING: No vLLM endpoint found. Set VLLM_HOST or run serve_vllm.slurm first.")
    return None, model

def wait_for_vllm(timeout_seconds: int = 7200, check_interval: int = 10) -> str | None:
    """Wait for vLLM to be ready, re-reading the endpoint file on each poll."""
    start_time = time.time()
    last_url = None
    while time.time() - start_time < timeout_seconds:
        url, _ = get_vllm_endpoint()
        if url and url != last_url:
            print(f"  Endpoint updated: {url}")
            last_url = url
        if url:
            try:
                req = urllib.request.Request(f"{url}/v1/models", method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        elapsed = round(time.time() - start_time, 1)
                        print(f"✓ vLLM server is ready at {url} ({elapsed}s)")
                        return url
            except (urllib.error.URLError, OSError, TimeoutError):
                pass
        elapsed = round(time.time() - start_time, 1)
        print(f"  Waiting for vLLM... ({elapsed}s elapsed)")
        time.sleep(check_interval)
    print(f"✗ vLLM server not ready after {timeout_seconds}s — aborting.")
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

def _make_temp_dce_project(db_name: str) -> Path:
    """Create a minimal per-question DCE project dir."""
    tmp = Path(tempfile.mkdtemp(prefix=f"dce_{db_name.lower()}_"))
    shutil.copy(DCE_PROJECT_DIR / "dce.ini", tmp / "dce.ini")
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    src_yaml = DCE_PROJECT_DIR / "src" / "databases" / f"{db_name.lower()}.yaml"
    if src_yaml.exists():
        shutil.copy(src_yaml, tmp / "src" / src_yaml.name)
    with open(tmp / "dce_project.yaml", "w", encoding="utf-8") as f:
        f.write("name: spider2-context-engine\n")
        f.write("sources:\n")
        f.write(f"  - {db_name.lower()}.yaml\n")
    out = tmp / "output"
    out.mkdir(exist_ok=True)
    shared_db = DCE_PROJECT_DIR / "output" / "dce.duckdb"
    if shared_db.exists():
        try:
            (out / "dce.duckdb").symlink_to(shared_db)
        except OSError:
            try:
                os.link(shared_db, out / "dce.duckdb")
            except OSError:
                print(f"  WARN: Could not symlink/link dce.duckdb to {out}. Context search may fail.")
    out_yaml = DCE_PROJECT_DIR / "output" / "databases" / f"{db_name.lower()}.yaml"
    if out_yaml.exists():
        shutil.copy(out_yaml, out / out_yaml.name)
    return tmp

def _strip_think_from_text(text: str) -> str:
    """Relatively simple stripping of <think> blocks."""
    if not isinstance(text, str):
        return text
    # Remove complete think blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Remove dangling tags if any
    text = re.sub(r"</?think>", "", text)
    return text.strip()

# (Previously here were complex think-stripping functions using another LLM. Now simplified to regex.)

def _strip_think_from_message_content(content):
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
    """Installs patches for the LLM execution."""
    global _THINK_PATCH_INSTALLED
    if _THINK_PATCH_INSTALLED:
        return
    
    from databao.agent.configs import llm as _databao_llm_config
    from databao.agent.executors import llm as _databao_llm
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    import litellm

    class GeminiModel(BaseChatModel):
        name: str
        max_tokens: int
        
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            litellm_messages = []
            for m in messages:
                role = "user"
                if isinstance(m, HumanMessage): role = "user"
                elif isinstance(m, SystemMessage): role = "system"
                elif isinstance(m, AIMessage): role = "assistant"
                elif isinstance(m, ToolMessage): role = "tool"
                msg_dict = {"role": role, "content": m.content}
                if role == "assistant" and getattr(m, "tool_calls", None):
                    msg_dict["tool_calls"] = [
                        {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
                        for tc in m.tool_calls
                    ]
                if role == "tool":
                    msg_dict["tool_call_id"] = getattr(m, "tool_call_id", None)
                litellm_messages.append(msg_dict)
            
            tools = None
            if "tools" in kwargs:
                from langchain_core.utils.function_calling import convert_to_openai_tool
                tools = [convert_to_openai_tool(t) for t in kwargs["tools"]]

            target_model = f"vertex_ai/{self.name}"
            if "vertex_ai/" in self.name: target_model = self.name
            
            response = litellm.completion(
                model=target_model,
                messages=litellm_messages,
                tools=tools,
                tool_choice="auto" if tools else None,
                temperature=0.0,
                max_tokens=self.max_tokens,
                vertex_project=os.environ.get("VERTEX_PROJECT"),
                vertex_location=os.environ.get("VERTEX_LOCATION"),
            )
            
            choice = response.choices[0].message
            content = choice.content or ""
            tool_calls = []
            if hasattr(choice, "tool_calls") and choice.tool_calls:
                for tc in choice.tool_calls:
                    tool_calls.append({"name": tc.function.name, "args": json.loads(tc.function.arguments), "id": tc.id})
            
            ai_msg = AIMessage(content=content, tool_calls=tool_calls)
            from langchain_core.outputs import ChatGeneration, ChatResult
            return ChatResult(generations=[ChatGeneration(message=ai_msg)])

        def bind_tools(self, tools, **kwargs):
            return self.bind(tools=tools, **kwargs)

        @property
        def _llm_type(self) -> str: return "gemini-litellm"

    _orig_new_chat_model = _databao_llm_config.LLMConfig.new_chat_model
    def _new_chat_model_patch(self):
        if "gemini" in self.name.lower() or "google" in self.name.lower():
            return GeminiModel(name=self.name, max_tokens=self.max_tokens)
        return _orig_new_chat_model(self)
    
    _databao_llm_config.LLMConfig.new_chat_model = _new_chat_model_patch
    
    _orig_chat = _databao_llm.chat
    def _chat_patched_for_think(messages, config, model=None):
        out_messages = _orig_chat(messages, config, model)
        last = out_messages[-1]
        if isinstance(last, AIMessage):
            last.content = _strip_think_from_message_content(last.content)
        return out_messages
    
    _databao_llm.chat = _chat_patched_for_think
    _THINK_PATCH_INSTALLED = True
    print("  [think-stripper] installed: thinking blocks will be stripped for history reuse")

def log_agent_trace(thread, instance_id, full=False, trace_dir=None):
    """Dump the full conversation history for debugging."""
    if trace_dir is not None:
        trace_dir.mkdir(parents=True, exist_ok=True)
        dump = []
        for m in thread.meta().get("messages", []):
            entry = {"role": m.type, "content": m.content}
            if hasattr(m, "tool_calls") and m.tool_calls:
                entry["tool_calls"] = m.tool_calls
            if m.type == "tool":
                entry["tool_call_id"] = getattr(m, "tool_call_id", None)
            dump.append(entry)
        out_file = trace_dir / f"{instance_id}.json"
        out_file.write_text(json.dumps(dump, indent=2, default=str), encoding="utf-8")
        print(f"  [trace] wrote {len(dump)} messages -> {out_file}")

    sys_cap = 10_000 if full else 200
    tool_cap = 10_000 if full else 400
    print(f"\n{'-'*60}\nAGENT TRACE  [{instance_id}]  ({len(thread.meta().get('messages', []))} messages)\n{'-'*60}")
    for m in thread.meta().get("messages", []):
        icon = "[USER]" if m.type == "human" else "[SYS ]" if m.type == "system" else "[AI  ]" if m.type == "ai" else "[TOOL]"
        text = str(m.content)
        cap = sys_cap if m.type in ("human", "system", "ai") else tool_cap
        if len(text) > cap:
            text = text[:cap] + "... (truncated)"
        print(f"\n{icon} {text}")
        if hasattr(m, "tool_calls") and m.tool_calls:
            for tc in m.tool_calls:
                print(f"       * Tool Call: {tc['name']}({tc['args']})")
    print(f"\n{'-'*60}\n")

# ── Evaluation ────────────────────────────────────────────────────────────────

def get_gold_path(instance_id: str) -> Path:
    return GOLD_EXEC_DIR / f"{instance_id}.csv"

def get_gold_sql_path(instance_id: str) -> Path:
    return GOLD_SQL_DIR / f"{instance_id}.sql"

def execute_gold_sql(instance_id: str, db_name: str) -> pd.DataFrame:
    sql_path = get_gold_sql_path(instance_id)
    if not sql_path.exists():
        return None
    
    sql = sql_path.read_text(encoding="utf-8")
    db_path = get_db_path(db_name)
    if not db_path:
        return None
        
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        df = pd.read_sql_query(sql, conn)
        conn.close()
        return df
    except Exception as e:
        print(f"  [eval] error executing gold SQL for {instance_id}: {e}")
        return None

def compare_results(pred: pd.DataFrame, gold: pd.DataFrame, eval_config: dict) -> tuple[int, str]:
    """Official Spider2 lenient comparison logic."""
    if pred is None:
        return 0, "no_prediction"
    if pred.empty and gold.empty:
        return 1, "both_empty"
    if pred.empty or gold.empty:
        return 0, "mismatch_empty"

    condition_cols = eval_config.get("condition_cols", [])
    ignore_order = eval_config.get("ignore_order", False)
    tolerance = 1e-2

    def normalize(value):
        if pd.isna(value):
            return 0
        return value

    def vectors_match(v1, v2, tol=tolerance, ignore_order_=False):
        v1 = [normalize(x) for x in v1]
        v2 = [normalize(x) for x in v2]
        if ignore_order_:
            # Sort for comparison
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

    # Filter gold columns if specified
    if condition_cols:
        try:
            # Spider2 stores condition_cols as indices or list of indices
            if isinstance(condition_cols, (list, tuple)) and condition_cols and isinstance(condition_cols[0], list):
                # If multiple gold files, we are called per-gold, but condition_cols might be nested
                # For simplicity in this benchmark loop, we assume single gold per call or flat indices
                gold_cols = gold.iloc[:, condition_cols[0]] 
            else:
                gold_cols = gold.iloc[:, condition_cols]
        except Exception:
            gold_cols = gold
    else:
        gold_cols = gold

    # Transpose to get columns as lists
    t_gold_list = gold_cols.transpose().values.tolist()
    t_pred_list = pred.transpose().values.tolist()

    for gold_vector in t_gold_list:
        if not any(vectors_match(gold_vector, pred_vector, ignore_order_=ignore_order) for pred_vector in t_pred_list):
            return 0, "column_mismatch"

    return 1, "match"

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instances", type=str, help="Comma-separated instance IDs (e.g. local001,local002)")
    parser.add_argument("--limit", type=int, help="Limit number of questions")
    parser.add_argument("--vllm-wait", action="store_true", help="Wait for vLLM server to be ready")
    parser.add_argument("--full-trace", action="store_true", help="Print full non-truncated traces")
    args = parser.parse_args()

    instances = args.instances.split(",") if args.instances else None
    questions = load_questions(instances=instances, limit=args.limit)
    eval_standards = load_eval_standards()

    vllm_host = None
    vllm_model_name = "QuantTrio/GLM-4.7-Flash-AWQ"
    if args.vllm_wait:
        vllm_host = wait_for_vllm()
    else:
        vllm_host, vllm_model_name = get_vllm_endpoint()

    print(f"Running {len(questions)} questions | model: {vllm_model_name}")
    if "gemini" in vllm_model_name.lower() or "google" in vllm_model_name.lower():
        print("Using Gemini API for LLM generation.")

    output_path = RESULTS_DIR / f"spider2_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    trace_dir = RESULTS_DIR / "traces"

    correct = 0
    total_scored = 0
    errors = 0

    from databao.agent import domain as db_agent_domain
    from databao.agent.configs.agent import DEFAULT_AGENT_CONFIG
    from databao.agent.configs.llm import LLMConfig
    from databao.agent.executors.lighthouse.executor import LighthouseExecutor
    from databao.agent.databases import SQLiteConnectionConfig
    from databao.agent.core.agent import Agent
    from databao.agent.caches.in_mem_cache import InMemCache
    from databao.agent.visualizers.dumb import DumbVisualizer

    with open(output_path, "w", newline="", encoding="utf-8") as csvf:
        fieldnames = ["instance_id", "db", "question", "external_knowledge", "predicted_sql", "execution_result", "score", "score_detail", "error", "time_s"]
        writer = csv.DictWriter(csvf, fieldnames=fieldnames)
        writer.writeheader()

        for idx, q in enumerate(questions, 1):
            instance_id = q["instance_id"]
            db_name = q["db"]
            question = q["question"]
            ext_doc = q.get("external_knowledge")

            print(f"\n[{idx}/{len(questions)}] {instance_id} ({db_name})")
            print(f"  Q: {question[:100]}...")

            t0 = time.time()
            predicted_sql = ""
            exec_result = ""
            score = 0
            score_detail = ""
            error = ""
            thread = None
            tmp_dce = None

            try:
                _install_think_stripper_once()

                # 1. Prepare minimal DCE project and domain
                tmp_dce = _make_temp_dce_project(db_name)
                domain = db_agent_domain(tmp_dce)
                
                # 2. Inject hints and external knowledge into domain description
                ctx = DUCKDB_HINTS
                if ext_doc:
                    doc_path = DOCS_DIR / ext_doc
                    if doc_path.exists():
                        ctx += f"\n\n## External Knowledge for Question\n\n{doc_path.read_text(encoding='utf-8')}"
                domain.add_description(ctx)

                # 4. Initialize Agent
                llm_cfg = LLMConfig(name=vllm_model_name, max_tokens=8192)
                agent = Agent(
                    domain=domain,
                    llm=llm_cfg,
                    agent_config=DEFAULT_AGENT_CONFIG,
                    data_executor=LighthouseExecutor(),
                    visualizer=DumbVisualizer(),
                    cache=InMemCache(),
                    rows_limit=2000,
                    stream_ask=False
                )

                # 5. Execute
                thread = agent.thread()
                thread.ask(question)
                
                predicted_sql = thread.code()
                if predicted_sql:
                    # 6. Evaluation
                    df = thread.df()
                    gold_df = None
                    execution_source = "csv"
                    
                    gold_path = get_gold_path(instance_id)
                    if gold_path.exists():
                        gold_df = pd.read_csv(gold_path)
                    else:
                        # Fallback to executing gold SQL
                        gold_df = execute_gold_sql(instance_id, db_name)
                        execution_source = "sql_exec"
                    
                    if gold_df is None:
                        exec_result = "error: gold_not_found"
                        score = 0
                        score_detail = f"Gold file missing (CSV/SQL) for {instance_id}"
                    else:
                        score, score_detail = compare_results(df, gold_df, eval_standards.get(instance_id, {}))
                        exec_result = "success" if score == 1 else "mismatch"
                        if score == 1:
                            correct += 1
                        total_scored += 1
                        if execution_source == "sql_exec":
                            print(f"  [eval] used gold SQL fallback for {instance_id}")
                else:
                    exec_result = "no_sql"
                    score = 0
                    score_detail = "agent_returned_empty_code"
                    total_scored += 1
                    errors += 1
                    print("  RESULT: no SQL generated")

            except Exception as e:
                import traceback
                traceback.print_exc()
                error = str(e)[:500]
                exec_result = "agent_error"
                score = 0
                score_detail = "agent_error"
                total_scored += 1
                errors += 1
                print(f"  AGENT ERROR: {e}")

            if thread is not None:
                try:
                    log_agent_trace(thread, instance_id, full=args.full_trace, trace_dir=trace_dir)
                except Exception as trace_err:
                    print(f"  [trace] log_agent_trace raised: {trace_err}")

            if tmp_dce is not None:
                shutil.rmtree(tmp_dce, ignore_errors=True)

            elapsed = round(time.time() - t0, 2)
            writer.writerow({
                "instance_id": instance_id, "db": db_name, "question": question,
                "external_knowledge": ext_doc or "", "predicted_sql": predicted_sql,
                "execution_result": exec_result, "score": score, "score_detail": score_detail,
                "error": error, "time_s": elapsed
            })
            csvf.flush()

    print(f"\n{'='*60}\nRESULTS SUMMARY\n{'='*60}")
    print(f"Total questions:   {len(questions)}")
    print(f"Scored:            {total_scored}")
    print(f"Correct:           {correct} / {total_scored}  ({100*correct//max(total_scored,1)}%)")
    print(f"Errors/no-SQL:     {errors}")
    print(f"\nResults -> {output_path}")

if __name__ == "__main__":
    main()
