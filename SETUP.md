# Setup on Babel (from scratch)

Everything runs from one checkout. Budget ~30 min active + downloads; the only slow
optional step is rebuilding the vector index (skip it by copying a teammate's).

## 1. Clone

```bash
cd /data/user_data/$USER
git clone --recurse-submodules git@github.com:Sandeep5500/nl2sql-databao.git
cd nl2sql-databao
# databao-context-engine must be on the patched branch:
git -C databao-context-engine checkout spider2-patches
```

## 2. Spider2 local databases (802MB, not in git)

Download the [local database zip](https://drive.usercontent.google.com/download?id=1coEVsCZq-Xvj9p2TnhBFoFTsY-UoYGmG&export=download&authuser=0)
(link from `Spider2/spider2-lite/README.md`), then:

```bash
unzip local_databases.zip
mv *.sqlite Spider2/spider2-lite/resource/databases/spider2-localdb/
ls Spider2/spider2-lite/resource/databases/spider2-localdb/*.sqlite | wc -l   # expect 31
```

## 3. Python env for the harness

```bash
cd nl2sql-v2 && uv sync && cd ..
```

(uv installs the pinned deps + databao-context-engine as an editable sibling dep.)

## 4. Ollama (embeddings for search_context)

```bash
# one-time install into ~/.dce (any ollama >= 0.13 works)
curl -fsSL https://ollama.com/install.sh | OLLAMA_HOME=~/.dce/ollama sh   # or module/conda install
~/.dce/ollama/bin/ollama pull nomic-embed-text:v1.5
```

## 5. Vector index `spider2-dce/output/dce.duckdb` (1.2GB, not in git)

**Fast path:** copy from a teammate (`spider2-dce/output/dce.duckdb`, plus their
`spider2-dce/output/databases/*.yaml` if missing). Ask Sandeep — the shared copy lives at
`/data/user_data/sandeep3/personal/nl2sql-databao/spider2-dce/output/` (needs a
`chmod -R g+rX` from him, dirs are private by default).

**Rebuild path (~2h, needs steps 6's vLLM server + local ollama running):**

```bash
cd spider2-dce
for y in src/databases/*.yaml; do
  uv run --project ../nl2sql-v2 python ../scripts/enrich_one_db.py \
    --datasource "databases/$(basename $y)" \
    --vllm-host <vllm_node> --vllm-port 8765 --vllm-model Qwen/Qwen3.5-9B \
    --embed-host localhost --embed-port 11434 --dce-dir .
done
```

## 6. Serve the model

```bash
mkdir -p logs/vllm
sbatch --partition=lilab --qos=lilab_qos --gres=gpu:A6000:1 nl2sql-v2/slurm/serve_vllm_qwen35.slurm
tail -f logs/vllm/vllm_<jobid>.err        # wait for "Application startup complete" (~10 min first time)
```

Notes: the `general` partition rejects our QOS — use `lilab` (or `preempt` + `preempt_qos`).
First run creates `.vllm-venv/` and downloads model weights (~18GB) to the HF cache.
Then start embeds on the same node:

```bash
srun --jobid=<vllm_jobid> --overlap -n1 --cpus-per-task=4 --gres=gpu:A6000:1 bash -c \
  'OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=24h exec ~/.dce/ollama/bin/ollama serve' &
```

## 7. Smoke test

```bash
cd nl2sql-v2
DCE_OLLAMA_HOST=<vllm_node> uv run python scripts/run_benchmark.py \
  --schema-overview --instances local085 \
  --output ../results/smoke.csv --trace-dir ../logs/traces/smoke
```

Expect one scored row (local085 usually ✓) and an Inspect log in `logs/inspect/`.
Full run: drop `--instances`, add `--resume`. Browse traces:
`uv run inspect view --log-dir ../logs/inspect --port 7591` (forward the port in VSCode).

## Working from a different checkout location

All data paths resolve through `NL2SQL_DATA_ROOT` (see `nl2sql-v2/src/nl2sql/config.py`).
Unset, it defaults to the checkout itself — the layout above needs no env var.
