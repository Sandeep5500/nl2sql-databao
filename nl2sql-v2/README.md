# nl2sql-v2

Lean, purpose-built text2sql agent harness for Spider 2.0-Lite (local SQLite split).
Replaces the databao-agent execution path (LangGraph + monkey-patches) with a plain
OpenAI-SDK tool-call loop against vLLM. Keeps **databao-context-engine** as a library
for semantic schema search, and keeps v1's trace format and eval logic.


## Setup

Dependencies live outside this repo (dataset is multi-GB): set one env var and clone two things.

```bash
# 1. this repo + the patched context engine as a sibling
git clone git@github.com:Sandeep5500/nl2sql-v2.git
git clone -b spider2-patches git@github.com:Sandeep5500/databao-context-engine.git
cd nl2sql-v2 && uv sync

# 2. point at the data root (Spider2/ dataset, spider2-dce/ index, logs/)
#    On Babel, just use the shared copy:
export NL2SQL_DATA_ROOT=/data/user_data/sandeep3/personal/nl2sql-databao
#    Elsewhere: clone https://github.com/xlang-ai/Spider2 into $NL2SQL_DATA_ROOT/Spider2
#    and build the DCE index with slurm/enrich_one_db.py (needs a vLLM + Ollama endpoint).

# 3. serve the model (SLURM) and run
sbatch --partition=lilab --qos=lilab_qos --gres=gpu:A6000:1 slurm/serve_vllm_qwen35.slurm
uv run python scripts/run_benchmark.py --schema-overview --instances local002,local007
```

`slurm/` holds the vLLM serve scripts (Qwen3.5-9B and Arctic) and the single-DB
enrichment script. All data paths resolve through `NL2SQL_DATA_ROOT` (see `src/nl2sql/config.py`).

## Design

One episode = one question. The loop (`src/nl2sql/agent.py`):

```
system prompt + question
  └─ LLM (OpenAI SDK, native tool calling)
       ├─ tool call(s) → dispatch → tool result message → loop
       └─ submit_result → critic gate (optional) → approve → done
                                    └─ revise → critique returned as tool msg → loop
```

- No LangGraph, no monkey-patches. `<think>` blocks are stripped before storing history.
- History compaction: old tool results are truncated once the transcript exceeds a char budget.
- One shared DCE project (`spider2-dce/`); per-question scoping via `datasource_ids`
  filter instead of v1's temp-project symlink dance.

## Tools

| Tool | What / why |
|---|---|
| `search_context(retrieve_text)` | Hybrid vector+BM25 search over enriched schema chunks (DCE). With **query expansion**: an LLM rewrites the query into ~3 variants, all are searched, results merged by Reciprocal Rank Fusion. |
| `list_tables()` | Deterministic table list (live catalog, not retrieval). |
| `describe_table(table)` | Columns, types, row count, per-column distinct/null counts, 5 sample rows. Ground truth complement to `search_context`'s LLM-written prose. |
| `get_column_values(table, column)` | Top distinct values + counts — probe filter values before writing WHERE clauses. |
| `find_value(term, table?, column?)` | Reverse lookup: which table/column contains this literal (ILIKE sweep over text columns). Fixes 'CA' vs 'California' filter mismatches. |
| `read_documentation()` | The question's external_knowledge markdown, full text, on demand (v1 prompt-stuffed a 20K-char truncation). |
| `run_sql_query(sql, preview_rows≤50)` | Execute SELECT on DuckDB (SQLite attached). Agent-settable preview size; full result capped at 100 rows, stored under a `query_id`. |
| `submit_result(query_id, result_description)` | Finish. Must be the sole tool call. Triggers the critic gate. |

## Critic gate

Harness-enforced, not agent-optional: when the agent submits, a **different model**
reviews {question, docs, SQL, result preview} and returns approve/revise. On revise,
the critique is returned to the agent as the tool result (max `critic.max_rounds`
rounds, default 2, to prevent loops). Rationale: one bounded call at the moment of
highest leverage; an anytime "second opinion" tool invites doom-loops and outsourced
thinking.

## Run

```bash
# vLLM must be serving (reads logs/vllm_endpoint.txt like v1)
cd nl2sql-v2
uv run python scripts/run_benchmark.py --instances local002,local007
uv run python scripts/run_benchmark.py --output ../results/v2_full135.csv \
    --trace-dir ../logs/traces/v2_$(date +%Y%m%d_%H%M%S)
# critic uses a second endpoint/model:
uv run python scripts/run_benchmark.py --critic-endpoint http://node:8766/v1 --critic-model glm-4.7-flash
```

## Ablation hooks (Phase 0, see documents/spider2_attack_plan.md)

- `--context-mode search|full|oracle` — B arm injects full `describe_table` dump of every
  table and disables `search_context`; C arm injects gold tables/columns (24 locals with gold SQL).
