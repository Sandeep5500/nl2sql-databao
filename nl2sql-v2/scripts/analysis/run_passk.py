"""Drive a pass@k run: K independent lanes of run_arm.py, launched in waves.

Replaces the ad-hoc pass@4 wave driver (which was never committed). Each lane is an
independent temperature-0.7 re-run (lane independence is RNG -- there is no seed flag);
lanes share one rubric dir. Waves keep the concurrent request count under the single-H200
Modal endpoint's cap and the ~16 GB local cgroup. Lanes are --resume-able, so re-running
this driver recovers a dead lane.

    python nl2sql-v2/scripts/analysis/run_passk.py \
        --endpoint https://rohinida--nl2sql-vllm-qwen36-35b-serve.us-east.modal.run/v1 \
        --base-tag pass8 --lanes 8 --wave-size 2 --temperature 0.7 --shards 5 \
        --rubric-dir results/full_C/rubrics --row-check
"""
import argparse
import csv
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]   # .../nl2sql-databao/nl2sql-v2
ROOT = REPO.parent                            # .../nl2sql-databao (holds results/)
ARM = REPO / "scripts" / "analysis" / "run_arm.py"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--base-tag", default="pass8")
    ap.add_argument("--lanes", type=int, default=8)
    ap.add_argument("--wave-size", type=int, default=2)
    ap.add_argument("--instances-file",
                    default=str(REPO / "scripts/analysis/instances/all204.txt"))
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--shards", type=int, default=5)
    ap.add_argument("--rubric-dir", default="results/full_C/rubrics")
    ap.add_argument("--row-check", action="store_true")
    ap.add_argument("--distinct-key-guard", action="store_true",
                    help="pass --distinct-key-guard through to each lane")
    ap.add_argument("--gen-rules-guard", action="store_true",
                    help="pass --gen-rules-guard through to each lane")
    ap.add_argument("--domain-notes", action="store_true",
                    help="pass --domain-notes through to each lane")
    args = ap.parse_args()

    tags = [f"{args.base_tag}_k{i}" for i in range(1, args.lanes + 1)]
    driver_log = open(ROOT / "results" / f"{args.base_tag}_driver.log", "a",
                      encoding="utf-8")

    def log(msg):
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
        print(line, flush=True)
        driver_log.write(line + "\n")
        driver_log.flush()

    def lane_cmd(tag):
        cmd = [sys.executable, str(ARM), "--tag", tag,
               "--instances-file", args.instances_file,
               "--endpoint", args.endpoint,
               "--shards", str(args.shards),
               "--temperature", str(args.temperature),
               "--rubric-dir", args.rubric_dir]
        if args.row_check:
            cmd.append("--row-check")
        if args.distinct_key_guard:
            cmd.append("--distinct-key-guard")
        if args.gen_rules_guard:
            cmd.append("--gen-rules-guard")
        if args.domain_notes:
            cmd.append("--domain-notes")
        return cmd

    log(f"pass@{args.lanes} start: tags={','.join(tags)} wave_size={args.wave_size}")
    for w in range(0, len(tags), args.wave_size):
        wave = tags[w:w + args.wave_size]
        log(f"wave: {' + '.join(wave)}")
        procs = []
        for tag in wave:
            f = open(ROOT / "results" / f"{tag}_arm.log", "w", encoding="utf-8")
            procs.append((tag, subprocess.Popen(lane_cmd(tag), cwd=ROOT, stdout=f,
                                                 stderr=subprocess.STDOUT), f))
        for tag, p, f in procs:
            code = p.wait()
            f.close()
            log(f"lane {tag} finished exit={code}")
    log(f"pass@{args.lanes} all lanes done")

    # per-lane totals + the any-of-k union
    solved_any, n_total = set(), 0
    for tag in tags:
        all_csv = ROOT / "results" / tag / "all.csv"
        if not all_csv.exists():
            log(f"{tag}: no all.csv (lane did not finish)")
            continue
        rows = list(csv.DictReader(open(all_csv, encoding="utf-8")))
        n_total = max(n_total, len(rows))
        correct = {r["instance_id"] for r in rows if r["score"] == "1"}
        solved_any |= correct
        log(f"{tag}: {len(correct)}/{len(rows)} correct")
    if n_total:
        log(f"pass@{args.lanes} union (solved by ANY lane): "
            f"{len(solved_any)}/{n_total} = {100 * len(solved_any) / n_total:.1f}%")
    driver_log.close()


if __name__ == "__main__":
    main()
