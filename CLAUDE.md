# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

NL2SQL benchmarking for [Spider 2.0-Lite](https://spider2-sql.github.io/) (local split: 135 SQLite questions).
The agent is **nl2sql-v2/** — a lean OpenAI-SDK tool-call loop (currently Qwen3.5-9B via vLLM) with
**databao-context-engine** as the semantic schema retrieval library. The old databao-agent (LangGraph)
execution path was removed Sept 2026; its history lives in git and in `documents/spider2_attack_plan.md`.

**Layout:**
- `nl2sql-v2/` — the harness: `src/nl2sql/` (agent loop, tools, memory, eval), `scripts/` (runners), `slurm/` (serve scripts)
- `databao-context-engine/` — submodule, branch `spider2-patches` (DCE_OLLAMA_HOST env override)
- `Spider2/` — submodule; SQLite DBs are downloaded separately (see SETUP.md)
- `spider2-dce/` — DCE project: enriched YAMLs (tracked) + `output/dce.duckdb` vector index (gitignored, 1.2GB)
- `scripts/` — enrichment (`enrich_dce.py` lib, `enrich_one_db.py`), `setup_dce_spider2.py`, GLM serve script
- `.vllm-venv/` — shared vLLM serving venv (gitignored; serve scripts auto-create it if missing)
- `results/`, `logs/` — gitignored; CSVs, traces, server logs stay on the cluster

Fresh-machine setup: **SETUP.md**. Results and experiment log: **documents/spider2_attack_plan.md**.

## Running the Benchmark

```bash
# 1. serve the model (SLURM; general partition rejects our QOS — use lilab or preempt)
sbatch --partition=lilab --qos=lilab_qos --gres=gpu:A6000:1 nl2sql-v2/slurm/serve_vllm_qwen35.slurm
# wait for "Application startup complete" in logs/vllm/vllm_<jobid>.err

# 2. Ollama embeds on the same node (for search_context), as an overlapping step:
srun --jobid=<vllm_jobid> --overlap -n1 --cpus-per-task=4 --gres=gpu:A6000:1 bash -c \
  'OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=24h exec ~/.dce/ollama/bin/ollama serve' &

# 3. run (from nl2sql-v2/); endpoint auto-read from logs/vllm_endpoint.txt
cd nl2sql-v2
DCE_OLLAMA_HOST=<vllm_node> uv run python scripts/run_benchmark.py \
  --schema-overview --instances local002,local007          # smoke
DCE_OLLAMA_HOST=<vllm_node> uv run python scripts/run_benchmark.py \
  --schema-overview --resume --output ../results/run.csv \
  --trace-dir ../logs/traces/run_$(date +%Y%m%d)           # full 135, resumable
```

Key runner flags: `--resume` (skip done, append), `--temperature` (pass@K sampling),
`--context-mode search|full|oracle` (ablations), `--critic-model/-endpoint`,
`--draft-model/-endpoint`, `--text-sql-fallback`, `--max-steps` (default 30).
Single-shot lane: `scripts/run_single_shot.py`. Long runs: wrap with
`../logs/bench/run_lane.sh <tag> <command...>` for auto-restart (up to 15 attempts).

Traces auto-convert to Inspect AI logs (`logs/inspect/`); view with
`uv run inspect view --log-dir ../logs/inspect --port 7591` (forward the port in VSCode).

## Serving notes (hard-won)

- **A6000 needs `--enforce-eager`** (bus errors otherwise) and even then vLLM can SIGBUS
  after ~24h uptime — treat servers as ~1-day services; runners auto-resume through restarts.
- transformers must be `==5.5.3` with `regex>=2025.10.22` (serve scripts pin this;
  a `uv sync`/editable reinstall elsewhere can silently downgrade regex).
- Qwen3.5 serve flags: `--tool-call-parser qwen3_coder --reasoning-parser qwen3`;
  vLLM exposes reasoning as message field `reasoning` (not `reasoning_content`).
- Two servers on one node/port: the second binds IPv6 and curl still hits the first —
  use distinct `VLLM_PORT`s.
- Session/subshell cgroup is ~16GB — heavy multi-lane runs get OOM-killed (exit 137);
  the resume wrappers absorb this.

## Scoring

`nl2sql/eval.py` ports Spider2's comparison: each gold column (value vector) must match
some predicted column; **extra predicted columns are tolerated**; `condition_cols` /
`ignore_order` come from `evaluation_suite/gold/spider2lite_eval.jsonl`. Gold exec CSVs
exist for all 547 instances; gold SQL only for 24 locals (basis of the oracle ablation).

## DCE enrichment

One-time per database. Single DB (~4 min): from `spider2-dce/`,
`uv run --project ../nl2sql-v2 python ../scripts/enrich_one_db.py --datasource databases/<name>.yaml
--vllm-host <node> --vllm-port 8765 --vllm-model Qwen/Qwen3.5-9B --embed-host <node> --embed-port 11434 --dce-dir .`
Datasource names are lowercase with non-alnum → `_` (question db `Db-IMDB` → `db_imdb.yaml`);
`run_benchmark.py::resolve_datasource` handles the mapping. Don't rebuild the index while
a search-mode run is reading `dce.duckdb`.

## Known result baselines (Sept 2026, Qwen3.5-9B)

Greedy agentic 43/135 (31.9%) · single-shot 15.6% · pass@4 51.1% · v1 (GLM) was 20.2%.
Generation is the measured bottleneck (oracle ablation); selection is the open gap (pass@K).
Details and never-solved core: `documents/spider2_attack_plan.md`.
