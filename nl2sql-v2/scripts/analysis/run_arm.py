"""Run one arm of the BigQuery comparison locally: rubric pass, then the benchmark.

Mirrors modal/run_bench.py's bq_rubric + bq_shard flags exactly (the bq_v3r config),
but the agent loop runs here so BigQuery credentials stay on this machine (ADC
impersonation); only the model calls go to the Modal vLLM endpoint.

    python run_arm.py --tag cal_C --instances-file cal40.txt --shards 4
    python run_arm.py --tag cal_T --instances-file cal40.txt --shards 4 --bq-stats DIR
"""
import argparse
import csv
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(r"C:\Users\rohin\Documents\CMU\Capstone\nl2sql-databao\nl2sql-v2")
ROOT = REPO.parent
MODEL = "Qwen/Qwen3.6-35B-A3B"
RUN_FIELDS = ["instance_id", "db", "score", "score_detail", "status", "steps",
              "critic_rounds", "search_calls", "draft_calls", "wall_seconds",
              "sf_queries", "sf_seconds", "scan_bytes", "sql"]


def child_env():
    env = dict(os.environ)
    env["PYTHONWARNINGS"] = "ignore"
    env["PYTHONUTF8"] = "1"
    env["BIGQUERY_PROJECT"] = "llm-systems-projects"
    env["BIGQUERY_IMPERSONATE_SERVICE_ACCOUNT"] = (
        "rohini-capstone@llm-systems-projects.iam.gserviceaccount.com")
    for line in (Path.home() / ".nl2sql" / "vllm.env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def split(ids, n):
    return [ids[i::n] for i in range(n) if ids[i::n]]


def run_parallel(cmds, logs, env):
    procs = []
    for cmd, log in zip(cmds, logs):
        f = open(log, "w", encoding="utf-8")
        procs.append((subprocess.Popen(cmd, cwd=REPO, env=env, stdout=f,
                                       stderr=subprocess.STDOUT), f))
    codes = []
    for p, f in procs:
        codes.append(p.wait())
        f.close()
    return codes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--instances-file", required=True)
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--shards", type=int, default=4)
    ap.add_argument("--bq-stats", default="")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-steps", type=int, default=60)
    ap.add_argument("--skip-rubric", action="store_true")
    ap.add_argument("--rubric-dir", default="",
                    help="reuse an existing rubric dir instead of generating one")
    ap.add_argument("--row-check", action="store_true",
                    help="pass --rubric-row-check to run_benchmark")
    args = ap.parse_args()

    ids =[i for i in Path(args.instances_file).read_text().strip().split(",") if i]
    out = ROOT / "results" / args.tag
    out.mkdir(parents=True, exist_ok=True)
    logdir = out / "logs"
    logdir.mkdir(exist_ok=True)
    env = child_env()
    shards = split(ids, args.shards)
    stats = ["--bq-stats", args.bq_stats] if args.bq_stats else []
    py = [sys.executable] if False else ["uv", "run", "python"]

    # absolute: the shards run with cwd=nl2sql-v2, so a relative path silently
    # pointed at a directory that does not exist (smoke_R, and likely bq_v3r)
    rubric_dir = str(Path(args.rubric_dir).resolve()) if args.rubric_dir else str(out / "rubrics")
    t0 = time.time()
    if not args.skip_rubric and not args.rubric_dir:
        cmds = [py + ["scripts/run_rubric.py", "--source", "spider2_lite_bq",
                      "--out-dir", rubric_dir, "--model", MODEL, "--resume",
                      "--endpoint", args.endpoint, "--instances", ",".join(s)] + stats
                for s in shards]
        codes = run_parallel(cmds, [logdir / f"rubric{i}.log" for i in range(len(cmds))],
                             env)
        print(f"[{args.tag}] rubric done in {time.time() - t0:.0f}s, exit codes {codes}",
              flush=True)

    t1 = time.time()
    cmds = [py + ["scripts/run_benchmark.py", "--source", "spider2_lite_bq",
                  "--schema-overview", "--context-mode", "full",
                  "--instances", ",".join(s),
                  "--output", str(out / f"shard{i:02d}.csv"),
                  "--trace-dir", str(out / "traces"),
                  "--run-tag", args.tag, "--model", MODEL,
                  "--max-steps", str(args.max_steps),
                  "--temperature", str(args.temperature), "--resume",
                  "--endpoint", args.endpoint,
                  "--rubric-dir", rubric_dir, "--rubric-confident-only"] + stats
            + (["--rubric-row-check"] if args.row_check else [])
            for i, s in enumerate(shards)]
    codes = run_parallel(cmds, [logdir / f"bench{i}.log" for i in range(len(cmds))], env)
    print(f"[{args.tag}] benchmark done in {time.time() - t1:.0f}s, exit codes {codes}",
          flush=True)

    rows = {}
    for sp in sorted(out.glob("shard*.csv")):
        with open(sp, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f, fieldnames=RUN_FIELDS):
                if r["instance_id"] in ("instance_id", "", None):
                    continue
                rows[r["instance_id"]] = r
    with open(out / "all.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RUN_FIELDS)
        w.writeheader()
        w.writerows(rows[i] for i in sorted(rows))
    n = len(rows)
    c = sum(1 for r in rows.values() if r["score"] == "1")
    gib = sum(float(r["scan_bytes"] or 0) for r in rows.values()) / 1024 ** 3
    print(f"[{args.tag}] {c}/{n} correct ({100 * c / max(n, 1):.1f}%), "
          f"scanned {gib:.1f} GiB, total {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
