#!/usr/bin/env python3
"""Oracle vs decoy: when the 9B is handed the tables and columns a correct
query uses, does it reach the correct output -- beyond what a same-length,
wrong-tables prompt achieves on its own?

Each arm is several runs over the same questions (greedy plus sampled
repeats). Per question, the pass rate in each arm is the fraction of its runs
that score correct; the effect of correct linkage is the paired difference
oracle minus decoy, with a bootstrap 95% interval over questions.

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/ablation_arms.py            # ablation_oracle_r* vs ablation_decoy_r*
    uv run python scripts/analysis/ablation_arms.py --oracle-runs 'a_*,b_*' --decoy-runs 'c_*,d_*'
"""

import argparse
import glob
import json
import random
from pathlib import Path

from _common import (TRACES_DIR, buckets, load_traces, local_questions,
                     rescore)

HERE = Path(__file__).resolve()


def discover(prefix: str) -> list[str]:
    """ablation_oracle -> ['ablation_oracle_r0_*', 'ablation_oracle_r1_*', ...]"""
    reps = sorted({Path(p).name.rsplit("_", 1)[0]
                   for p in glob.glob(str(TRACES_DIR / f"{prefix}_r*_*"))})
    return [f"{r}_*" for r in reps]


def rates(specs, qdb, ids):
    traces = load_traces(specs)
    ok = rescore(traces, qdb)
    per = {i: [ok.get((s, i), False) for s in specs] for i in ids}
    return per, traces


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oracle-prefix", default="ablation_oracle")
    ap.add_argument("--decoy-prefix", default="ablation_decoy")
    ap.add_argument("--oracle-runs")
    ap.add_argument("--decoy-runs")
    ap.add_argument("--questions", default=str(HERE.parents[2] / "teacher_context.json"),
                    help="JSON whose keys are the question ids both arms ran on, or 'all'")
    args = ap.parse_args()

    qdb = {k: v["db"] for k, v in local_questions().items()}
    o_specs = args.oracle_runs.split(",") if args.oracle_runs else discover(args.oracle_prefix)
    d_specs = args.decoy_runs.split(",") if args.decoy_runs else discover(args.decoy_prefix)
    if not o_specs or not d_specs:
        raise SystemExit(f"no runs found (oracle={o_specs}, decoy={d_specs})")
    ids = sorted(qdb) if args.questions == "all" else sorted(json.load(open(args.questions)))

    o, o_tr = rates(o_specs, qdb, ids)
    d, d_tr = rates(d_specs, qdb, ids)
    n = len(ids)
    greedy_o = sum(o[i][0] for i in ids)
    greedy_d = sum(d[i][0] for i in ids)
    ro = {i: sum(o[i]) / len(o[i]) for i in ids}
    rd = {i: sum(d[i]) / len(d[i]) for i in ids}
    diff = [ro[i] - rd[i] for i in ids]
    mean = sum(diff) / n

    rng = random.Random(0)
    boots = sorted(sum(rng.choice(diff) for _ in range(n)) / n for _ in range(10_000))
    lo, hi = boots[250], boots[9750]

    b = buckets(qdb)
    print(f"questions: {n}   (bucket C: {len(set(ids) & b['C'])}, B: {len(set(ids) & b['B'])}, "
          f"A: {len(set(ids) & b['A'])})")
    print(f"runs per arm: oracle {len(o_specs)}, decoy {len(d_specs)}   (run 0 is greedy)\n")
    print(f"{'':34s} {'oracle':>8s} {'decoy':>8s}")
    print(f"{'greedy run solves':34s} {greedy_o:8d} {greedy_d:8d}")
    print(f"{'solved in at least one run':34s} {sum(any(o[i]) for i in ids):8d} "
          f"{sum(any(d[i]) for i in ids):8d}")
    print(f"{'mean pass rate per question':34s} {sum(ro.values()) / n:8.1%} {sum(rd.values()) / n:8.1%}")
    print(f"\neffect of correct linkage (oracle - decoy): {mean:+.1%}   95% CI [{lo:+.1%}, {hi:+.1%}]")
    print(f"questions where oracle > decoy: {sum(x > 0 for x in diff)}, "
          f"decoy > oracle: {sum(x < 0 for x in diff)}, tied: {sum(x == 0 for x in diff)}")

    # decoy must be at least as big a prompt change as the oracle
    ratios = []
    for i in ids:
        so = next((t[i].get("system", "") for t in o_tr.values() if i in t), "")
        sd = next((t[i].get("system", "") for t in d_tr.values() if i in t), "")
        if so and sd:
            ratios.append(len(sd) / len(so))
    if ratios:
        ratios.sort()
        print(f"\ndecoy/oracle system-prompt length: median {ratios[len(ratios) // 2]:.2f}, "
              f"min {ratios[0]:.2f}; decoy shorter on {sum(r < 1 for r in ratios)} of {len(ratios)}")


if __name__ == "__main__":
    main()
