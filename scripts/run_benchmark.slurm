#!/bin/bash
#SBATCH --job-name=spider2_bench
#SBATCH --partition=general
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:L40S:1
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=/data/user_data/sandeep3/personal/nl2sql-databao/logs/bench/bench_%j.log

export DCE_OLLAMA_BIN=/home/sandeep3/.dce/ollama/bin/ollama
export PYTHONUNBUFFERED=1

SCRIPT=/data/user_data/sandeep3/personal/nl2sql-databao/scripts/spider2_benchmark.py
TS=$(date +%Y%m%d_%H%M%S)
cd /data/user_data/sandeep3/personal/nl2sql-databao/databao-agent

/home/sandeep3/.local/bin/uv run python ../scripts/spider2_benchmark.py \
  --output ../results/spider2_full135_${TS}.csv \
  --trace-dir ../logs/traces/traces_full135_${TS} \
  --skip-instances "local002,local003,local004,local007,local008,local009,local010,local015,local017,local018,local019,local020,local021,local022,local023,local024,local025,local026,local028,local029,local030,local031,local032,local034,local035,local037,local038,local039,local040,local041,local049,local054,local055,local056,local058,local059,local060,local061,local063,local198" \
  --full-trace
