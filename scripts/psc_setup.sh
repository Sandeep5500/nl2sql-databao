#!/bin/bash
# One-time setup script for PSC Bridges-2.
# Run this ONCE from the PSC login node before submitting any SLURM jobs.
#
# Usage:
#   ssh psc
#   bash /path/to/psc_setup.sh
#   # OR copy-paste the sections below directly

set -e

WORK_DIR="/jet/home/dpalagan/nl2sql-databao"
OCEAN_DIR="/ocean/projects/cis260009p/dpalagan"
HF_CACHE="$OCEAN_DIR/huggingface_cache"
VENV_PYTHON="$WORK_DIR/databao-agent/.venv/bin/python"

echo "=== PSC Bridges-2 One-Time Setup ==="
echo "Work dir:  $WORK_DIR"
echo "HF cache:  $HF_CACHE"
echo ""

# ── Step 1: Clone repo ────────────────────────────────────────────────────────
echo "[1/5] Cloning nl2sql-databao repo..."
if [ -d "$WORK_DIR" ]; then
    echo "  Already exists — pulling latest..."
    cd "$WORK_DIR" && git pull
else
    git clone https://github.com/Sandeep5500/nl2sql-databao.git "$WORK_DIR"
fi

cd "$WORK_DIR"

# Switch to dpalagan-dev branch (has enum enrichment + SLURM scripts)
git checkout dpalagan-dev 2>/dev/null || git checkout -b dpalagan-dev origin/dpalagan-dev

echo "  Repo ready at $WORK_DIR (branch: $(git branch --show-current))"

# ── Step 2: Init submodules ───────────────────────────────────────────────────
echo "[2/5] Initialising submodules (databao-agent, databao-context-engine, Spider2)..."
git submodule update --init --recursive

# ── Step 3: Python venv ───────────────────────────────────────────────────────
echo "[3/5] Creating Python venv in databao-agent/..."
cd "$WORK_DIR/databao-agent"

module load python/3.11-anaconda2023.09 2>/dev/null || \
module load python/3.11 2>/dev/null || \
module load anaconda3 2>/dev/null || true

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate

# Install databao-agent in editable mode + dependencies
pip install --quiet -e ".[dev]" 2>/dev/null || pip install --quiet -e "." || true

# Install databao-context-engine (DCE) editable
pip install --quiet -e "../databao-context-engine/" 2>/dev/null || true

# Install remaining benchmark dependencies
pip install --quiet pandas pyyaml requests openai

echo "  venv ready: $VENV_PYTHON"

# ── Step 4: Verify HF cache dir ──────────────────────────────────────────────
echo "[4/5] Verifying HF cache directory..."
mkdir -p "$HF_CACHE"
echo "  HF cache: $HF_CACHE"
echo "  (GLM-4.7-Flash-AWQ ~17 GB will download here on first vLLM run)"

# ── Step 5: Create symlink for Spider2 data ───────────────────────────────────
echo "[5/5] Checking Spider2 database path..."
# Spider2 SQLite files expected at the path hardcoded in spider2_benchmark.py
SPIDER2_DB_PATH="/data/user_data/sandeep3/personal/capstone/Spider2/spider2-lite"
if [ ! -d "$SPIDER2_DB_PATH" ]; then
    echo ""
    echo "  ⚠️  WARNING: Spider2 data not found at $SPIDER2_DB_PATH"
    echo "  The benchmark script hardcodes this path (SPIDER2_DIR in spider2_benchmark.py)."
    echo "  You need to either:"
    echo "    a) Copy/link Spider2 data to $SPIDER2_DB_PATH"
    echo "    b) Edit SPIDER2_DIR in scripts/spider2_benchmark.py to point to"
    echo "       the actual location of spider2-lite/ on PSC"
    echo ""
    echo "  Spider2 data is ~2 GB. If you have it locally:"
    echo "    scp -r path/to/spider2-lite dpalagan@bridges2.psc.edu:$WORK_DIR/Spider2/"
    echo "  Then update SPIDER2_DIR in spider2_benchmark.py to:"
    echo "    SPIDER2_DIR = Path('$WORK_DIR/Spider2/spider2-lite')"
else
    echo "  Spider2 data found at $SPIDER2_DB_PATH ✓"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Fix SPIDER2_DIR in scripts/spider2_benchmark.py if needed (see above)"
echo "  2. Start vLLM GPU job:    sbatch $WORK_DIR/scripts/psc_serve_vllm.slurm"
echo "  3. Submit benchmark:      sbatch $WORK_DIR/scripts/psc_run_benchmark.slurm"
echo "  4. Monitor vLLM:          tail -f $WORK_DIR/logs/vllm_<jobid>.out"
echo "  5. Monitor benchmark:     tail -f $WORK_DIR/logs/bench_<jobid>.log"
echo "  6. Check jobs:            squeue -u dpalagan"
