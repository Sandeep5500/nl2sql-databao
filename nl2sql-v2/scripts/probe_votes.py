#!/usr/bin/env python3
"""Stage B step 3 of documents/head_probe_prereg.md: the frozen probe's soft votes on stored selection-eval
calls. For every call with hidden states (extract_judge_states.py on calls_to_records.py records),
c = the probe's P(this trace's verdict is right) and the vote is v = c for verdict A, else 1 - c. v
replaces the call's p_first, so `selection_eval.py score --judge probe@S=<out>` counts it; calls without
states (no verdict, truncated) are copied unchanged. Only the pools of --records are written, so a
design-half run holds no other half. Labels are not read.

    python scripts/probe_votes.py --probe <prefix>.probe.npz --states <dir> --records verdicts_design.jsonl \\
        --calls calls_diff_cmp.jsonl --out calls_probe.jsonl
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_fit import LAYERS, POSITIONS, load_states  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", required=True, help="probe_fit.py <out>.probe.npz")
    ap.add_argument("--states", nargs="+", required=True)
    ap.add_argument("--records", nargs="+", required=True, help="the calls_to_records.py files the states came from")
    ap.add_argument("--calls", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pr = np.load(args.probe)
    lname, pname = str(pr["config"]).split("/")
    feats, z, rows = load_states(args.states)
    skipped = sum(1 for r in rows if r.get("skipped"))
    if skipped:  # their features are zeros: every call with a verdict must get a real probe vote
        raise SystemExit(f"{skipped} rows were skipped as too long: extract them again with a higher --max-tokens")
    va = np.array([float(r["verdict"] == "A") for r in rows])
    order = np.array([float(r["first"] > r["second"]) for r in rows])
    ident = float(np.mean((z > 0) == (va == 1)))
    X = np.column_stack([feats[:, LAYERS.index(lname), POSITIONS.index(pname), :].astype(np.float32), va, order])
    c = 1 / (1 + np.exp(-(((X - pr["mu"]) / pr["sd"]) @ pr["coef"] + pr["intercept"][0])))
    samples = {}
    for path in args.records:
        for r in map(json.loads, open(path)):
            for p in r["pairs"]:
                samples[r["instance_id"], p["first"], p["second"]] = [s["call_sample"] for s in p["samples"]]
    votes = {}
    for r, ci in zip(rows, c):
        call = samples[r["instance_id"], r["first"], r["second"]][r["sample"]]
        votes[r["instance_id"], r["first"], r["second"], call] = (float(ci), float(ci) if r["verdict"] == "A" else 1 - float(ci))
    n = hit = 0
    with open(args.out, "w") as out:
        for line in open(args.calls):
            call = json.loads(line)
            if (call["key"], call["first"], call["second"]) not in samples:
                continue
            v = votes.get((call["key"], call["first"], call["second"], call["sample"]))
            if v is not None:
                call.update(p_first=v[1], probe_c=v[0], variant="probe")
                hit += 1
            n += 1
            out.write(json.dumps(call) + "\n")
    print(f"{len(rows)} states (identity {ident:.4f}), probe {lname}/{pname} C={float(pr['C'])}; "
          f"{hit} of {n} calls given a probe vote -> {args.out}; mean c {c.mean():.3f}", flush=True)
    if hit != len(rows):
        raise SystemExit("some states matched no call")


if __name__ == "__main__":
    main()
