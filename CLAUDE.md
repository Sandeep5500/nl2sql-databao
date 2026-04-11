# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

NL2SQL benchmarking system for [Spider 2.0](https://spider2-sql.github.io/) using the [databao-agent](https://github.com/databao-ai/databao-agent) framework. The system runs LLM agents (currently GLM-4.7-Flash-AWQ via vLLM) against 135 local SQLite questions, using the databao-context-engine for semantic schema retrieval.

**Three git submodules:**
- `databao-agent/` — LangGraph-based SQL agent library
- `databao-context-engine/` — Vector search + schema enrichment engine (DCE)
- `Spider2/` — Spider 2.0 dataset (`spider2-lite/` = 135 local SQLite questions)

**Local project:**
- `spider2-dce/` — DCE project dir (enriched YAMLs + `output/dce.duckdb` vector index)

## First-Time Setup

After cloning, run these once:

```bash
git submodule update --init --recursive
git config submodule.recurse true   # auto-update submodules on branch switch
```

The `dce.duckdb` vector index (1.2GB) is gitignored. Copy it from the shared NFS path or rebuild with `dce build && dce index` inside `spider2-dce/`.

## Running the Benchmark

All benchmark commands run from `databao-agent/` using `uv run`:

```bash
cd databao-agent

# Quick test (5 questions)
uv run python ../scripts/spider2_benchmark.py \
  --instances local002,local007,local009

# Skip already-completed questions
uv run python ../scripts/spider2_benchmark.py \
  --skip-instances "local002,local007,..." \
  --output ../results/spider2_partial.csv \
  --trace-dir ../logs/traces/traces_run_$(date +%Y%m%d_%H%M%S) \
  --full-trace

# SLURM (production run)
cd /data/user_data/sandeep3/personal/nl2sql-databao
sbatch scripts/run_benchmark.slurm
```

The benchmark auto-reads the vLLM endpoint from `logs/vllm_endpoint.txt`. If vLLM isn't running it falls back to Ollama (`OLLAMA_SQL_MODEL` env var).

## Serving vLLM (SLURM)

```bash
# Default: GLM-4.7-Flash-AWQ on A100_80GB
sbatch scripts/serve_vllm.slurm

# Reduced context for L40S (48GB VRAM)
MAX_MODEL_LEN=25000 sbatch --gres=gpu:L40S:1 scripts/serve_vllm.slurm

# Monitor startup (~8 min for weight loading)
tail -f logs/vllm/vllm_<jobid>.out   # weight loading + "Application startup complete"
tail -f logs/vllm/vllm_<jobid>.err   # error output
```

**Critical GLM-4.7-Flash vLLM flags** (do not remove):
- `VLLM_MLA_DISABLE=1` — disables TRITON_MLA attention, forces FLASH_ATTN (bus errors otherwise)
- `--enforce-eager` — disables CUDA graph warmup (avoids OOM)
- `--quantization awq` — required for AWQ quantized weights

**transformers version**: Must be `==5.5.3` with `regex>=2025.10.22`. The `glm4_moe_lite` architecture isn't in transformers 4.x, and transformers 5.x with the old regex causes SIGBUS on first inference. The `serve_vllm.slurm` script pins both.

## Checking Benchmark Results

```bash
python3 -c "
import csv
with open('results/spider2_full135_<timestamp>.csv') as f:
    rows = list(csv.DictReader(f))
correct = sum(1 for r in rows if r.get('score','0') == '1')
print(f'{correct}/{len(rows)} correct ({100*correct//len(rows)}%)')
for r in rows:
    mark = '✓' if r['score']=='1' else '✗'
    print(f'  {mark} {r[\"instance_id\"]}: {r[\"score_detail\"]}')
"
```

Gold CSVs for comparison: `Spider2/spider2-lite/evaluation_suite/gold/exec_result/<instance>_*.csv`

## Architecture: How a Question Runs

1. **Benchmark script** loads question from `spider2-dce/spider2-lite.jsonl`, creates a temp DCE project pointing at the question's database YAML and the shared `dce.duckdb`.
2. **Agent** (LighthouseExecutor, LangGraph) receives the question + system prompt with schema summary.
3. **`search_context` tool** embeds the query via Ollama (`nomic-embed-text-v1.5`) and retrieves matching schema chunks from `dce.duckdb`. The `min_retrievals=1` config forces at least one call.
4. **Agent iterates** (up to 30 steps / 60 LangGraph nodes): calls `run_sql_query` to try SQL, observes results, refines.
5. **Think-stripper** monkey-patches LangGraph message handling to replace GLM's `<think>...</think>` blocks with 2-sentence summaries (max 120 tokens) before storing in history.
6. **`submit_result`** triggers evaluation: output DataFrame compared against gold CSV.
7. Trace written to `logs/traces/<run>/local###.json`.

## Agent Configuration (spider2_benchmark.py)

Key settings applied at runtime in `scripts/spider2_benchmark.py`:

| Setting | Value | Why |
|---|---|---|
| `max_tokens` | 4096 | GLM reasoning was being truncated at 1024 |
| `temperature` | 0.0 | Deterministic output |
| `recursion_limit` | 30 steps / 60 nodes | Old limit of 12 hit 2 steps before correct answers |
| `min_retrievals` | 1 | Forces schema exploration before writing SQL |
| `max_tokens_before_cleaning` | 5000 (default) | Compacts message history when exceeded |
| `wait_for_vllm` timeout | 7200s (2hr) | Allows bench to wait for slow SLURM queue |

## DCE Enrichment (One-Time Setup)

The `spider2-dce/output/dce.duckdb` vector index is pre-built. To rebuild or re-enrich:

```bash
# Enrich schemas (needs vLLM running)
cd spider2-dce
uv run python ../scripts/enrich_dce.py \
  --vllm-host <node> --vllm-port 8766 \
  --vllm-model Qwen/Qwen3-32B-AWQ \
  --dce-dir .

# Rebuild index
dce build && dce index
```

The critique enrichment pass (in `scripts/enrich_dce.py`) runs a second LLM call per table to rewrite ambiguous column descriptions using concrete sample values — critical for tables with similar column names (e.g., `customer_id` vs `customer_unique_id`).

## Log Layout

```
logs/
  vllm/           # vLLM server stdout/stderr per job
  bench/          # benchmark runner stdout per job
  dce/            # DCE enrichment job output
  traces/         # per-run subdirs of per-question JSON traces
  vllm_endpoint.txt   # written by serve_vllm.slurm; read by benchmark
results/          # scored CSVs from each run
```

## Key Files in databao-agent

- `databao/agent/executors/lighthouse/system_prompt.jinja` — agent system prompt (DuckDB hints, pre-submit checklist, doom-loop rules, stuck-loop rule)
- `databao/agent/executors/base.py` — `GraphExecutor`, history cleaning, partial state persistence on failure
- `databao/agent/configs/llm.py` — `LLMConfig` dataclass including `max_tokens_before_cleaning`
- `databao/agent/configs/agent.py` — `AgentConfig` dataclass including `min_retrievals`, `recursion_limit`
- `documents/MODIFICATIONS.md` — changelog of all improvements made for this benchmark

## Common Failure Modes

| Score detail | Cause | Fix direction |
|---|---|---|
| `result_mismatch` | Wrong SQL logic (wrong JOIN, wrong aggregation) | Improve prompt hints |
| `agent_error` / Connection error | vLLM crashed or never started | Check vLLM logs for SIGBUS |
| `no_sql` | Agent hit recursion limit without submitting | Increase `recursion_limit`, check doom-loop |
| SIGBUS (exit 7) on vLLM | Wrong transformers version (needs 5.5.3 + regex>=2025.10.22) | Check `serve_vllm.slurm` install step |
| `glm4_moe_lite` not recognized | transformers < 5.x installed | `uv pip install "transformers==5.5.3"` |
