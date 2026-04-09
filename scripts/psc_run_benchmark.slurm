#!/bin/bash
#SBATCH --job-name=spider2_bench
#SBATCH --partition=RM-shared
#SBATCH --account=cis260009p
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=/ocean/projects/cis260009p/dpalagan/nl2sql-databao/logs/bench_%j.log
#SBATCH --error=/ocean/projects/cis260009p/dpalagan/nl2sql-databao/logs/bench_%j.err

# Run full Spider 2.0 local SQLite benchmark on PSC Bridges-2 (CPU-only job).
#
# This job connects to the vLLM endpoint started by psc_serve_vllm.slurm.
# The LLM inference is remote (GPU node); this job only runs Python + DuckDB.
#
# Memory: 32 GB is sufficient for DuckDB attaching SQLite files.
# Partition: RM-shared (CPU only) — no GPU needed, lower queue wait.
#
# IMPORTANT: Submit psc_serve_vllm.slurm first. This script waits up to
#   10 minutes for the vLLM server to become ready before starting.
#
# Usage:
#   # Step 1 — start vLLM on GPU node:
#   sbatch scripts/psc_serve_vllm.slurm
#
#   # Step 2 — submit benchmark (waits for vLLM automatically):
#   sbatch scripts/psc_run_benchmark.slurm
#
#   # Monitor:
#   tail -f logs/bench_<jobid>.log
#   grep -E "^\[|score=|AGENT ERROR|PASS" logs/bench_<jobid>.log
#
#   # Quick result summary (run after benchmark finishes):
#   python3 scripts/psc_check_results.py

set -e

WORK_DIR="/ocean/projects/cis260009p/dpalagan/nl2sql-databao"
VENV_PYTHON="$WORK_DIR/databao-agent/.venv/bin/python"
TS=$(date +%Y%m%d_%H%M%S)

mkdir -p "$WORK_DIR/logs" "$WORK_DIR/results"
cd "$WORK_DIR"

echo "========================================"
echo "Spider 2.0 Benchmark — PSC Bridges-2"
echo "Node:   $(hostname)"
echo "Time:   $(date)"
echo "Output: results/spider2_full135_${TS}.csv"
echo "Traces: logs/traces_full135_${TS}/"
echo "========================================"

# Verify vLLM endpoint exists
ENDPOINT_FILE="$WORK_DIR/logs/vllm_endpoint.txt"
if [ ! -f "$ENDPOINT_FILE" ]; then
    echo "ERROR: $ENDPOINT_FILE not found."
    echo "Submit psc_serve_vllm.slurm first, then re-submit this job."
    exit 1
fi

ENDPOINT=$(head -1 "$ENDPOINT_FILE")
MODEL_NAME=$(grep "^Model:" "$ENDPOINT_FILE" | cut -d' ' -f2-)
echo "vLLM endpoint: $ENDPOINT"
echo "Model:         $MODEL_NAME"

# Wait for vLLM to be ready (up to 10 min — first run downloads model)
echo "Waiting for vLLM server..."
for i in $(seq 1 60); do
    if curl -sf --max-time 5 "http://${ENDPOINT}/v1/models" > /dev/null 2>&1; then
        echo "vLLM ready (polled ${i}× 10s)"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "ERROR: vLLM not ready after 10 minutes."
        echo "Check: cat logs/vllm_*.err"
        exit 1
    fi
    echo "  poll $i/60..."
    sleep 10
done

echo ""
echo "Starting benchmark at $(date)..."
echo "Baseline: 15/124 (12.1%) — Run 4, Qwen3-32B-AWQ, no fixes"
echo "Target:   beat 12.1% with all fixes applied"
echo ""

# Tell the benchmark where Spider2 data and DCE project live on PSC
export SPIDER2_DIR="$WORK_DIR/Spider2/spider2-lite"
export DCE_PROJECT_DIR="$WORK_DIR/spider2-dce"

"$VENV_PYTHON" scripts/spider2_benchmark.py \
    --output "results/spider2_full135_${TS}.csv" \
    --trace-dir "logs/traces_full135_${TS}" \
    --full-trace

echo ""
echo "========================================"
echo "Benchmark complete at $(date)"
echo "========================================"

# Print results summary
"$VENV_PYTHON" - <<'PYEOF'
import pandas as pd, glob, os, sys

files = glob.glob("results/spider2_full135_*.csv")
if not files:
    print("No result files found.")
    sys.exit(0)

f = max(files, key=os.path.getmtime)
df = pd.read_csv(f)
total = len(df)
correct = int(df["score"].sum())
pct = 100 * df["score"].mean()

print(f"\n{'='*50}")
print(f"RESULTS: {correct}/{total} ({pct:.1f}%)")
print(f"Baseline: 15/124 (12.1%)")
delta = correct - 15
print(f"Delta:    {'+' if delta >= 0 else ''}{delta} questions")
print(f"File:     {f}")
print(f"{'='*50}")

print(f"\nPassing questions ({correct}):")
passes = df[df["score"] == 1][["instance_id", "db_id"]]
print(passes.to_string(index=False))

if "score_detail" in df.columns:
    print(f"\nFailure breakdown:")
    print(df[df["score"] == 0]["score_detail"].value_counts().to_string())
PYEOF
