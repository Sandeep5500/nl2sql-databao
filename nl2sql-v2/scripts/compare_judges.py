#!/usr/bin/env python3
"""Compare judges by the questions they get right under the production selection rule
(pure round-robin over the 4 lanes, win counts) on judge_pools.py outputs.

Each judge is a glob prefix; shard files <prefix>_<pool>_n12_s*.jsonl are joined.
Reports, per run set: plain majority, each judge, the ceiling (some lane right), and for
each judge after the first, questions won and lost against the first (sign test).

Usage: python scripts/compare_judges.py --pools-dir <results/pools> \\
    --judge base=think35/qwen36-35b-think --judge tuned=judge-tuned-v1/judge-tuned-v1
"""

import argparse
import glob
import json
import math

POOLS = ["q36rg", "q36s", "q36", "v2"]


def load(pools_dir, prefix, pool):
    items = {}
    for path in sorted(glob.glob(f"{pools_dir}/{prefix}_{pool}_n12_s*.jsonl")):
        for line in open(path):
            it = json.loads(line)
            items[it["instance_id"]] = it
    return items


def pure_round_robin(it):
    """Every result plays every other, both orders; most wins is submitted. Identical
    results tie each other (half a win each way); a failed SQL scores nothing."""
    g, lanes = it["groups"], it["lanes"]
    if not g:
        return None
    n = {i: sum(1 for l in lanes if l["group"] == i) for i in range(len(g))}
    p = {(j["first"], j["second"]): j["p_first"] for j in it["judgments"] if j["p_first"] is not None}

    def beats(a, b):  # wins of a over b across the two orders (0..2)
        w = 0.0
        for x, y, flip in ((a, b, False), (b, a, True)):
            if (x, y) in p:
                pa = 1 - p[(x, y)] if flip else p[(x, y)]
                w += float(pa > 0.5)
            else:
                w += 0.5
        return w

    score = {a: sum(n[b] * beats(a, b) for b in n if b != a) + (n[a] - 1) * 1.0 for a in n if n[a] > 0}
    return max(score, key=lambda a: (score[a], n[a], -a))


def plain_majority(it):
    g, lanes = it["groups"], it["lanes"]
    if not g:
        return None
    n = {i: sum(1 for l in lanes if l["group"] == i) for i in range(len(g))}
    first = {i: min(l["lane"] for l in lanes if l["group"] == i) for i in n if n[i]}
    return max(first, key=lambda a: (n[a], -first[a]))


def right(it, pick):
    return pick is not None and bool(it["groups"][pick]["correct"])


def sign_p(up, dn):
    """Two-sided exact sign test."""
    k, n = min(up, dn), up + dn
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pools-dir", required=True)
    ap.add_argument("--judge", action="append", required=True, help="name=glob prefix (first is the reference)")
    ap.add_argument("--show", action="store_true", help="list the questions that changed")
    args = ap.parse_args()
    judges = [j.split("=", 1) for j in args.judge]
    ref = judges[0][0]

    data = {name: {p: load(args.pools_dir, pre, p) for p in POOLS} for name, pre in judges}
    rows, diffs = {}, {}
    for p in POOLS:
        common = set.intersection(*(set(data[name][p]) for name, _ in judges))
        items = {name: data[name][p] for name, _ in judges}
        any_items = items[ref]
        rows.setdefault("questions judged by all", {})[p] = len(common)
        rows.setdefault("plain majority", {})[p] = sum(right(any_items[q], plain_majority(any_items[q])) for q in common)
        for name, _ in judges:
            rows.setdefault(name, {})[p] = sum(right(items[name][q], pure_round_robin(items[name][q])) for q in common)
        rows.setdefault("ceiling (some lane right)", {})[p] = sum(
            any(g["correct"] for g in any_items[q]["groups"]) for q in common)
        for name, _ in judges[1:]:
            up = [q for q in sorted(common) if right(items[name][q], pure_round_robin(items[name][q]))
                  and not right(items[ref][q], pure_round_robin(items[ref][q]))]
            dn = [q for q in sorted(common) if right(items[ref][q], pure_round_robin(items[ref][q]))
                  and not right(items[name][q], pure_round_robin(items[name][q]))]
            diffs.setdefault(name, {})[p] = (up, dn)

    print(f"{'':30s}" + "".join(f"{p:>8s}" for p in POOLS) + f"{'all':>8s}")
    for label, vals in rows.items():
        print(f"{label:30s}" + "".join(f"{vals[p]:8d}" for p in POOLS) + f"{sum(vals.values()):8d}")
    for name, per in diffs.items():
        up = sum(len(per[p][0]) for p in POOLS)
        dn = sum(len(per[p][1]) for p in POOLS)
        print(f"\n{name} vs {ref}: +{up} / -{dn} questions, sign test p = {sign_p(up, dn):.3f}")
        for p in POOLS:
            print(f"  {p:6s} +{len(per[p][0])} -{len(per[p][1])}"
                  + (f"   + {' '.join(per[p][0])}   - {' '.join(per[p][1])}" if args.show else ""))


if __name__ == "__main__":
    main()
