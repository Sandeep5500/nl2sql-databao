#!/usr/bin/env python3
"""Offline layered selection over judge_pools.py outputs.

Layers, in order (each can be switched off for ablations):
  1. drop lanes whose SQL failed; drop empty results when another group has rows
  2. superset merge: a group whose columns sit inside another group's (same rows)
     joins that group (the superset is never scored worse: extra columns are allowed)
  3. one group left -> take it
  4. strong majority: a group with >= --strong lanes -> take it (unless --judge-strong)
  5. judge: each remaining group's score = mean over its matchups of P(win), each
     matchup averaged over both presentation orders; the judge's top group replaces
     the majority group only if its score is higher by more than tau
Majority = most lane votes (step-cap fallback lanes weigh --fallback-weight);
ties -> submitted, then more lanes, then the earlier lane.

tau is tuned on --dev (a pool name) and applied unchanged to the other pools.

Usage: uv run python scripts/analyze_pools.py ../results/pools --dev q36s
       (files named <judge>_<pool>.jsonl)
"""

import argparse
import glob
import json
import math
import os
from collections import defaultdict

TAUS = [0.0, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 2.0]


def select(item, tau, merge=True, strong=3, judge_strong=False, fb_w=1.0,
           strong_premerge=False, tau_strong=None, keep_empty_majority=False,
           weighted=False):
    """Returns (picked group index or None, which layer decided, majority group).

    strong_premerge: count the strong majority on identical results only, so a
    superset merge cannot manufacture one. tau_strong: the judge may override a
    strong majority when its margin exceeds tau_strong (None = never).
    keep_empty_majority: do not drop empty results when most lanes returned one."""
    groups, lanes = item["groups"], item["lanes"]
    if not groups:
        return None, "no answer", None
    live = [i for i, g in enumerate(groups)]
    empty_lanes = sum(1 for l in lanes if l["group"] is not None and groups[l["group"]]["rows"] == 0)
    drop_empty = not (keep_empty_majority and 2 * empty_lanes > len(lanes))
    if drop_empty and any(g["rows"] > 0 for g in groups):
        live = [i for i in live if groups[i]["rows"] > 0]
    owner = {i: i for i in live}
    if merge:
        cont = set(item["contains"])
        for i in sorted(live, key=lambda i: groups[i]["cols"]):  # narrowest first
            for j in sorted(live, key=lambda j: -groups[j]["cols"]):
                if j != i and owner[j] == j and f"{j}>{i}" in cont:
                    owner[i] = j
                    break
        for i in live:  # follow chains to the final superset
            while owner[owner[i]] != owner[i]:
                owner[i] = owner[owner[i]]
    reps = sorted({owner[i] for i in live})
    weight = defaultdict(float)
    submitted = defaultdict(bool)
    for ln in lanes:
        gi = ln["group"]
        if gi is None or gi not in owner:
            continue
        r = owner[gi]
        weight[r] += 1.0 if ln["status"] == "submitted" else fb_w
        submitted[r] |= ln["status"] == "submitted"
    maj = max(reps, key=lambda r: (weight[r], submitted[r],
                                   len([l for l in lanes if l["group"] in owner and owner[l["group"]] == r]),
                                   -r))
    if len(reps) == 1:
        return reps[0], "single", maj
    if strong_premerge:  # lanes that returned exactly the majority's own result
        n_lanes = sum(1 for l in lanes if l["group"] == maj)
    else:
        n_lanes = sum(1 for l in lanes if l["group"] in owner and owner[l["group"]] == maj)
    is_strong = n_lanes >= strong
    if is_strong and not judge_strong and tau_strong is None:
        return maj, "strong majority", maj
    # judge scores among representatives
    p = {(j["first"], j["second"]): j["p_first"] for j in item["judgments"]
         if j["p_first"] is not None}
    def win(a, b):
        vals = []
        if (a, b) in p: vals.append(p[(a, b)])
        if (b, a) in p: vals.append(1 - p[(b, a)])
        return sum(vals) / len(vals) if vals else 0.5
    if weighted:  # every lane is a player: copies of a result tie each other, and each
        # copy counts in its matchups, so a result more lanes produced weighs more
        n_r = {r: sum(1 for l in lanes if l["group"] in owner and owner[l["group"]] == r) for r in reps}
        total = sum(n_r.values())
        score = {r: (sum(n_r[o] * win(r, o) for o in reps if o != r) + 0.5 * (n_r[r] - 1))
                    / max(total - 1, 1) for r in reps}
    else:         # each distinct result counts once
        score = {r: sum(win(r, o) for o in reps if o != r) / (len(reps) - 1) for r in reps}
    top = max(reps, key=lambda r: (score[r], weight[r], -r))
    margin = tau_strong if (is_strong and not judge_strong) else tau
    if top != maj and score[top] - score[maj] > margin:
        return top, "strong majority overridden" if is_strong else "judge override", maj
    return maj, "strong majority" if is_strong else "judge kept majority", maj


def sign_p(up, dn):
    n, k = up + dn, min(up, dn)
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def evaluate(items, **kw):
    picks = [select(it, **kw) for it in items]
    acc = sum(it["groups"][p]["correct"] for it, (p, _, _) in zip(items, picks) if p is not None)
    maj = sum(it["groups"][m]["correct"] for it, (_, _, m) in zip(items, picks) if m is not None)
    up = sum(1 for it, (p, _, m) in zip(items, picks)
             if p is not None and it["groups"][p]["correct"] > it["groups"][m]["correct"])
    dn = sum(1 for it, (p, _, m) in zip(items, picks)
             if p is not None and it["groups"][p]["correct"] < it["groups"][m]["correct"])
    layers = defaultdict(int)
    for _, l, _ in picks:
        layers[l] += 1
    return acc, maj, up, dn, dict(layers)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pools_dir")
    ap.add_argument("--dev", default="q36s")
    args = ap.parse_args()
    data = defaultdict(dict)  # judge -> pool -> items
    for f in sorted(glob.glob(f"{args.pools_dir}/*.jsonl")):
        judge, pool = os.path.basename(f)[:-6].rsplit("_", 1)
        data[judge][pool] = [json.loads(l) for l in open(f)]
    variants = {
        "full design": dict(merge=True, strong=3, judge_strong=False, fb_w=0.5),
        "no superset merge": dict(merge=False, strong=3, judge_strong=False, fb_w=0.5),
        "judge also on strong majority": dict(merge=True, strong=3, judge_strong=True, fb_w=0.5),
        "fallback lanes weigh 1": dict(merge=True, strong=3, judge_strong=False, fb_w=1.0),
    }
    for judge, pools in data.items():
        print(f"\n######## judge: {judge}")
        if args.dev not in pools:
            print(f"(no dev pool {args.dev}; skipping)")
            continue
        for vname, kw in variants.items():
            dev = pools[args.dev]
            best = max(TAUS, key=lambda t: (evaluate(dev, tau=t, **kw)[0], t))
            print(f"--- {vname}: tau tuned on {args.dev} = {best}")
            print(f"    {'pool':8s} {'n':>4s} {'oracle':>6s} {'majority':>8s} {'judge':>6s} {'+':>3s} {'-':>3s} {'p':>6s}  {'tau=0':>6s}  layers")
            for pool, items in sorted(pools.items()):
                acc, maj, up, dn, layers = evaluate(items, tau=best, **kw)
                acc0 = evaluate(items, tau=0.0, **kw)[0]
                orc = sum(any(g["correct"] for g in it["groups"]) for it in items)
                tag = " (dev)" if pool == args.dev else ""
                print(f"    {pool + tag:8s} {len(items):4d} {orc:6d} {maj:8d} {acc:6d} {up:3d} {dn:3d} "
                      f"{sign_p(up, dn):6.3f}  {acc0:6d}  {layers}")


if __name__ == "__main__":
    main()
