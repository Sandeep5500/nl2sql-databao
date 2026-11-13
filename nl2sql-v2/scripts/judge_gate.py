#!/usr/bin/env python3
"""Did a judge retrain change the judge where it was trained, and on databases it never saw?

Compares rejudge_pairs.py --verdicts outputs of the untuned judge (fresh samples, the
baseline) and a tuned one on the same judge-training pairs, split three ways:
  trained   the pair is in the DPO file (dpo.jsonl pair_id)
  seen db   its database was trained on, the pair was not
  held out  its database is in holdout.json, or its question is in the val split (never trained on)
and by how often the untuned judge was right when the pairs were chosen (never/mixed/always).

PASS when the trained mixed pairs gain at least --min-gain (the training moved the judge at
all); the held-out rows say whether that carries to new databases.

Usage: python scripts/judge_gate.py --baseline train_untuned.jsonl --tuned gate_v2.jsonl \\
           --data <make_judge_sft_dpo out dir> --verdicts verdicts_train_v1.jsonl
"""

import argparse
import json
import math
import statistics as st
from collections import defaultdict


def load(path):
    out = defaultdict(list)
    for line in open(path):
        r = json.loads(line)
        if not r["error"]:
            out[r["id"]].append(r)
    return out


def sign_p(up, dn):
    k, n = min(up, dn), up + dn
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--tuned", required=True)
    ap.add_argument("--data", required=True, help="dir with dpo.jsonl and holdout.json")
    ap.add_argument("--verdicts", required=True,
                    help="the sample_judge_verdicts.py files the pairs come from (comma-separated)")
    ap.add_argument("--min-gain", type=float, default=0.05)
    ap.add_argument("--trained-file", default="dpo.jsonl",
                    help="the file in --data whose pair_ids count as trained (choice.jsonl for the verdict-only stage)")
    args = ap.parse_args()

    base, tuned = load(args.baseline), load(args.tuned)
    trained = {json.loads(l)["pair_id"] for l in open(f"{args.data}/{args.trained_file}")}
    held = set(json.load(open(f"{args.data}/holdout.json"))["databases"])
    recs = [json.loads(l) for path in args.verdicts.split(",") for l in open(path)]
    db = {r["instance_id"]: r["db"] for r in recs}
    val = {r["instance_id"] for r in recs if r.get("split", "train") != "train"}  # never trained on

    def where(pid):
        if db[pid.split("#")[0]] in held or pid.split("#")[0] in val:
            return "held out"
        return "trained" if pid in trained else "seen db"

    rate = lambda rs: sum(r["right"] for r in rs) / len(rs)
    cells = defaultdict(list)
    for pid in set(base) & set(tuned):
        cells[(where(pid), base[pid][0]["kind"])].append(pid)
    print(f"{'':10s}{'chosen as':>10s}{'pairs':>7s}{'untuned':>9s}{'tuned':>8s}{'gain':>8s}   pairs up/down, sign p")
    result = {}
    for w in ("trained", "seen db", "held out"):
        for k in ("mixed", "never", "always"):
            ids = cells.get((w, k))
            if not ids:
                continue
            a = [rate(base[i]) for i in ids]
            b = [rate(tuned[i]) for i in ids]
            up = sum(y > x for x, y in zip(a, b))
            dn = sum(y < x for x, y in zip(a, b))
            gain = st.mean(b) - st.mean(a)
            result[(w, k)] = gain
            print(f"{w:10s}{k:>10s}{len(ids):7d}{st.mean(a):9.1%}{st.mean(b):8.1%}{gain:+8.1%}   {up}/{dn}, p={sign_p(up, dn):.3f}")
    for name, s in (("untuned", base), ("tuned", tuned)):
        rs = [r for v in s.values() for r in v]
        ct = sorted(r["completion_tokens"] for r in rs if r["completion_tokens"])
        print(f"{name:8s} {len(rs)} samples: median {ct[len(ct) // 2]} completion tokens, "
              f"truncated {sum(r['truncated'] for r in rs)}, no verdict {sum(r['verdict'] is None for r in rs)}")
    g = result.get(("trained", "mixed"))
    ok = g is not None and g >= args.min_gain
    print(f"GATE {'PASS' if ok else 'FAIL'}: trained mixed pairs {'+' if g and g >= 0 else ''}{(g or 0):.1%} "
          f"(needs +{args.min_gain:.0%})")


if __name__ == "__main__":
    main()
