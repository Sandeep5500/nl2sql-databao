#!/usr/bin/env python3
"""Selection eval for judge prompt variants (Nov 2026): the pools a judge can change, a
design/test split of the Spider2 questions, and expected round-robin accuracy from several
judge samples per ordered pair.

Two runs of the thinking judge differ on ~23 of 540 Spider2 pools, so one run cannot show a
change worth 5-10 questions. Each ordered pair is judged K times instead, and a pool scores
  exp1  the exact expected accuracy of the deployed round-robin (one verdict per ordered pair,
        drawn from that pair's K samples; a missing verdict counts 0.5 as in anatomy.py)
  avgK  the accuracy of the round-robin on the K-sample average (twosample.py's rule)

Pools: the 4 lanes of one question in one run set (Spider2 q36rg, q36s, q36, v2), or Rohini's
4 BigQuery retries (lanes 0-3; the greedy lane is left out, as in bq_anatomy.py).
  mixed      a correct and a wrong group among the lanes: only these can change with the judge
  contested  mixed, 1-2 correct lanes (of 4): the primary metric
  easy       mixed, 3 correct lanes: the regression check
Spider2 questions are split by database into a design half (misses are read and prompts tuned
there) and a test half (confirmation only); BigQuery is never used for design. Group indices
follow the reference pools given to build (think35 run 1 / think35_bq); another judge's pool
whose groups differ (nondeterministic agent SQL) is left out of its comparisons.

Usage:
    python scripts/selection_eval.py build --pools <results/pools> --bq-pools <bq_passk/pools> \\
        --out selection_evalset.json
    python scripts/selection_eval.py score --evalset selection_evalset.json \\
        --judge think=<pools>/think35/qwen36-35b-think_*_n12_s*.jsonl,<bq>/think35_bq_n16_s*.jsonl \\
        --judge rerun=<pools>/think35_rerun/qwen36-35b-think-rerun_*_n12_s*.jsonl --ref think
    ... --judge colrule=calls_colrule.jsonl   (rejudge_pools.py output, one line per call)
A judge given several sources (think+rerun) pools their samples: think+rerun is K=2.
Selection rules on top of the judge, named by suffixes (NAME@U@T=...):
  U  superset upgrade: after the round-robin pick, submit the widest group whose result contains
     every column of the picked group's result with the same rows (the pools' "contains" map,
     computed on full results); under Spider2's scorer that group is right whenever the pick is
  T  wider-first tie-break: groups tied for the top score are ordered by more columns, then more
     lanes, then the lower index (deployed: more lanes, then the lower index)
  S  soft votes: each judgment counts its p_first (a probe's or scorer's probability) instead of
     p_first rounded to 0/1, so a calibrated score gets credit for its confidence
"""

import argparse
import glob
import itertools
import json
import os
import random
import sys
import zlib
from collections import defaultdict
from pathlib import Path

SPIDER2_RUNSETS = ("q36rg", "q36s", "q36", "v2")
BQ_LANES = {0, 1, 2, 3}


def pool_key(path, iid):
    if not iid.startswith("local"):
        return f"bq:{iid}"
    name = os.path.basename(path).removesuffix(".jsonl").split("_n12_")[0]
    return f"spider2:{name.rsplit('_', 1)[1]}:{iid}"


def signature(it):
    return [(g["sql"], tuple(sorted(g["lanes"])), int(bool(g["correct"]))) for g in it["groups"]]


def value(p_first, verdict, old_rule=False, soft=False):
    """1.0 = the first-shown candidate won, 0.0 = the second won, None = no verdict.
    old_rule: as anatomy.py, a judgment without p_first is missing even when its verdict is set.
    soft: p_first itself (the @S rule) instead of p_first rounded to 0/1."""
    if p_first is not None:
        return float(p_first) if soft else (1.0 if p_first > 0.5 else 0.0)
    if not old_rule and verdict in ("A", "B"):
        return 1.0 if verdict == "A" else 0.0
    return None


def load_samples(globs, old_rule=False, soft=False):
    """{pool key: {(first, second): [values]}} and {pool key: signature} (pool-format sources).
    Sources are judge_pools.py / bq_judge_pools.py outputs (one pool per line) or
    rejudge_pools.py outputs (one call per line)."""
    samples, sigs, calls = defaultdict(lambda: defaultdict(list)), {}, {}
    files = sorted({f for g in globs for f in glob.glob(g)})
    if not files:
        raise SystemExit(f"no files match {globs}")
    for f in files:
        for line in open(f):
            try:
                r = json.loads(line)
            except ValueError:  # a line cut off when a session was killed
                continue
            if "judgments" in r:
                k = pool_key(f, r["instance_id"])
                sigs[k] = signature(r)
                for j in r["judgments"]:
                    samples[k][(j["first"], j["second"])].append(
                        value(j["p_first"], j.get("verdict"), old_rule, soft))
            elif not r.get("retry"):  # retry records (server down) were made again later
                calls[(f, r["key"], r["first"], r["second"], r["sample"])] = r
    for (_, k, a, b, _), r in calls.items():
        v = None if r.get("error") else value(r.get("p_first"), r.get("verdict"), old_rule, soft)
        samples[k][(a, b)].append(v)
    return samples, sigs


def pool_groups(it, bq):
    """[(n lanes, correct, columns)] per group; BigQuery counts only the 4 retries."""
    used = [l for l in it["lanes"] if l["group"] is not None and (not bq or l["lane"] in BQ_LANES)]
    return [(sum(1 for l in used if l["group"] == a), int(bool(g["correct"])), int(g["cols"]))
            for a, g in enumerate(it["groups"])]


def stratum(groups):
    alive = [(g[0], g[1]) for g in groups if g[0] > 0]
    ncorr = sum(n for n, c in alive if c)
    if not any(c for _, c in alive):
        return "no_correct", ncorr
    if all(c for _, c in alive):
        return "all_correct", ncorr
    return ("contested" if ncorr <= 2 else "easy"), ncorr


def outcomes(vals):
    """Distribution over a verdict value (1, 0, 0.5 = missing) from the samples of one ordered pair."""
    if not vals:
        return {0.5: 1.0}
    d = defaultdict(float)
    for v in vals:
        d[0.5 if v is None else v] += 1 / len(vals)
    return dict(d)


def pick(groups, st, rules=(), contains=()):
    alive = [a for a, g in enumerate(groups) if g[0] > 0]
    # scores within 0.001 tie, so a soft vote's float noise (p_first 0.99990 vs 1) does not override the
    # tie-break; hard votes are multiples of 0.5 and are unaffected
    sc = {a: round(st[a], 3) for a in alive}
    if "T" in rules:
        top = max(alive, key=lambda a: (sc[a], groups[a][2], groups[a][0], -a))
    else:
        top = max(alive, key=lambda a: (sc[a], groups[a][0], -a))
    if "U" in rules:
        sup = [b for b in alive if f"{b}>{top}" in contains]
        if sup:
            top = max(sup, key=lambda b: (groups[b][2], groups[b][0], -b))
    return top


def pool_scores(groups, pair_samples, mc_draws=20000, seed=0, rules=(), contains=()):
    """(exp1, avgK) for one pool: groups [(n, correct, cols)], pair_samples {(x, y): [values]},
    rules: selection rules on top of the round-robin ("U", "T"), contains: the pool's "a>b" list."""
    contains = set(contains)
    alive = [a for a, g in enumerate(groups) if g[0] > 0]
    n = {a: groups[a][0] for a in alive}
    if len(alive) == 1:
        c = float(groups[alive[0]][1])
        return c, c
    pairs = [(x, y) for x in alive for y in alive if x != y]
    dist = {p: outcomes(pair_samples.get(p, [])) for p in pairs}
    # average rule: each ordered pair contributes its mean value
    st = {a: n[a] - 1.0 for a in alive}
    for (x, y), d in dist.items():
        v = sum(val * pr for val, pr in d.items())
        st[x] += n[y] * v
        st[y] += n[x] * (1 - v)
    avg = float(groups[pick(groups, st, rules, contains)][1])
    # one draw per ordered pair: fixed pairs first, then enumerate (or sample) the rest
    st0 = {a: n[a] - 1.0 for a in alive}
    var = []
    for (x, y), d in dist.items():
        if len(d) == 1:
            v = next(iter(d))
            st0[x] += n[y] * v
            st0[y] += n[x] * (1 - v)
        else:
            var.append(((x, y), list(d.items())))
    if not var:
        return float(groups[pick(groups, st0, rules, contains)][1]), avg
    size = 1
    for _, opts in var:
        size *= len(opts)
    if size <= 200000:
        combos = ((1.0, c) for c in itertools.product(*(opts for _, opts in var)))
        exp = 0.0
        for _, combo in combos:
            st, pr = dict(st0), 1.0
            for ((x, y), _), (v, p) in zip(var, combo):
                st[x] += n[y] * v
                st[y] += n[x] * (1 - v)
                pr *= p
            exp += pr * groups[pick(groups, st, rules, contains)][1]
        return exp, avg
    rng = random.Random(seed)
    hits = 0
    for _ in range(mc_draws):
        st = dict(st0)
        for (x, y), opts in var:
            v = rng.choices([o[0] for o in opts], [o[1] for o in opts])[0]
            st[x] += n[y] * v
            st[y] += n[x] * (1 - v)
        hits += groups[pick(groups, st, rules, contains)][1]
    return hits / mc_draws, avg


def score_judge(evalset, samples, sigs, rules=()):
    """{pool key: (exp1, avgK)} for pools this judge can be scored on; skipped keys with reasons."""
    out, skipped = {}, defaultdict(list)
    for k, e in evalset["pools"].items():
        groups = [tuple(g) for g in e["groups"]]
        if e["stratum"] in ("contested", "easy"):
            if k in sigs and json.dumps(sigs[k]) != json.dumps(e["sig"]):
                skipped["groups differ"].append(k)
                continue
            if k not in samples:
                skipped["not judged"].append(k)
                continue
            out[k] = pool_scores(groups, samples[k], seed=zlib.crc32(k.encode()), rules=rules,
                                 contains=e.get("contains", ()))
        else:
            c = float(e["stratum"] == "all_correct")
            out[k] = (c, c)
    return out, skipped


def build(args):
    sp = sorted(glob.glob(f"{args.pools}/{args.ref_prefix}_*_n12_s*.jsonl"))
    bq = sorted(glob.glob(f"{args.bq_pools}/{args.bq_ref_prefix}_n16_s*.jsonl"))
    if len(sp) != 48 or not bq:
        raise SystemExit(f"expected 48 Spider2 reference shards and BigQuery shards, got {len(sp)}/{len(bq)}")
    qdb = {q["instance_id"]: q["db"] for q in map(json.loads, open(args.questions))}
    pools = {}
    for f in sp + bq:
        for line in open(f):
            it = json.loads(line)
            k = pool_key(f, it["instance_id"])
            is_bq = k.startswith("bq:")
            groups = pool_groups(it, is_bq)
            s, ncorr = stratum(groups)
            pools[k] = {"bench": "bq" if is_bq else "spider2", "iid": it["instance_id"],
                        "runset": None if is_bq else k.split(":")[1],
                        "db": None if is_bq else qdb[it["instance_id"]], "half": "bq" if is_bq else None,
                        "stratum": s, "ncorr": ncorr, "groups": groups, "sig": signature(it),
                        "contains": it.get("contains", [])}
    evalset = {"pools": pools}
    # baseline outcomes (thinking judge, run 1 and rerun) to balance the halves
    runs = {}
    for name, g in (("think", [f"{args.pools}/{args.ref_prefix}_*_n12_s*.jsonl"]),
                    ("rerun", [f"{args.pools}/{args.rerun_prefix}_*_n12_s*.jsonl"])):
        s, sg = load_samples(g, old_rule=True)
        runs[name], _ = score_judge(evalset, s, sg)
    stats = defaultdict(lambda: defaultdict(float))
    for k, e in pools.items():
        if e["bench"] != "spider2":
            continue
        st = stats[e["db"]]
        st["pools"] += 1
        st[e["stratum"]] += 1
        if e["stratum"] in ("contested", "easy"):
            m1 = k in runs["think"] and runs["think"][k][0] < 0.5
            m2 = k in runs["rerun"] and runs["rerun"][k][0] < 0.5
            st["miss_any"] += m1 or m2
            st["miss_both"] += m1 and m2
    dbs = sorted(stats)
    keys = ("contested", "miss_both", "miss_any", "easy", "pools")
    wts = (1.0, 1.0, 0.5, 0.5, 0.05)
    tot = {x: sum(stats[d][x] for d in dbs) for x in keys}

    def cost(design):
        return sum(w * abs(2 * sum(stats[d][x] for d in design) - tot[x]) for x, w in zip(keys, wts))

    rng = random.Random(args.seed)
    best, best_cost = None, float("inf")
    for _ in range(args.restarts):
        design = {d for d in dbs if rng.random() < 0.5}
        c = cost(design)
        improved = True
        while improved:  # local search: move one database across while it helps
            improved = False
            for d in dbs:
                trial = design ^ {d}
                tc = cost(trial)
                if tc < c - 1e-9:
                    design, c, improved = trial, tc, True
        if c < best_cost:
            best, best_cost = design, c
    for k, e in pools.items():
        if e["bench"] == "spider2":
            e["half"] = "design" if e["db"] in best else "test"
    evalset["split"] = {"seed": args.seed, "restarts": args.restarts, "cost": best_cost,
                        "design_dbs": sorted(best), "test_dbs": sorted(set(dbs) - best),
                        "per_db": {d: dict(stats[d]) for d in dbs}}
    evalset["baseline_misses"] = {
        k: {"think": runs["think"][k][0] < 0.5 if k in runs["think"] else None,
            "rerun": runs["rerun"][k][0] < 0.5 if k in runs["rerun"] else None}
        for k, e in pools.items() if e["bench"] == "spider2" and e["stratum"] in ("contested", "easy")}
    Path(args.out).write_text(json.dumps(evalset, indent=1))
    print(f"wrote {args.out}: {len(pools)} pools")
    for half in ("design", "test", "bq"):
        es = [e for e in pools.values() if e["half"] == half]
        cnt = defaultdict(int)
        for e in es:
            cnt[e["stratum"]] += 1
        qs = {e["iid"] for e in es}
        line = f"  {half:6s} {len(es):3d} pools, {len(qs):3d} questions | " + \
               " ".join(f"{s} {cnt[s]}" for s in ("contested", "easy", "all_correct", "no_correct"))
        if half != "bq":
            bm = [m for k, m in evalset["baseline_misses"].items() if pools[k]["half"] == half]
            line += (f" | misses think {sum(bool(m['think']) for m in bm)}"
                     f" rerun {sum(bool(m['rerun']) for m in bm)}"
                     f" both {sum(bool(m['think'] and m['rerun']) for m in bm)}"
                     f" (rerun groups differ on {sum(m['rerun'] is None for m in bm)})")
        print(line)
    print(f"  design dbs: {', '.join(sorted(best))}")
    print(f"  test dbs:   {', '.join(sorted(set(dbs) - best))}")


def bootstrap(diffs_by_cluster, reps=4000, seed=0, level=0.95):
    """Two-sided interval of the summed difference, resampling questions (clusters) with replacement."""
    cl = list(diffs_by_cluster.values())
    if not cl:
        return 0.0, 0.0
    rng = random.Random(seed)
    sums = sorted(sum(rng.choice(cl) for _ in cl) for _ in range(reps))
    a = (1 - level) / 2
    return sums[int(a * reps)], sums[min(reps - 1, int((1 - a) * reps))]


def diagnostics(pools, samples, keys):
    """Per-judgment accuracy on right-vs-wrong pairs in `keys`: right shown first / second; the share of
    (right, wrong) pairs whose same-index samples went to the first-shown candidate in both orders;
    by how the right group's column count compares with the wrong one's."""
    c = defaultdict(lambda: [0, 0])
    for k in keys:
        if k not in samples:
            continue
        g = pools[k]["groups"]
        alive = [a for a, x in enumerate(g) if x[0] > 0]
        for x in alive:
            for y in alive:
                if x == y or g[x][1] == g[y][1]:
                    continue
                right = x if g[x][1] else y
                wrong = y if right == x else x
                rel = "fewer" if g[right][2] < g[wrong][2] else "more" if g[right][2] > g[wrong][2] else "same"
                for v in samples[k].get((x, y), []):
                    if v is None:
                        continue
                    won = (v > 0.5) == (x == right)
                    c["right shown first" if x == right else "right shown second"][0] += won
                    c["right shown first" if x == right else "right shown second"][1] += 1
                    c[f"right has {rel} cols"][0] += won
                    c[f"right has {rel} cols"][1] += 1
                if x == right:  # pair sample s of (right, wrong) with sample s of (wrong, right)
                    for v1, v2 in zip(samples[k].get((x, y), []), samples[k].get((y, x), [])):
                        if v1 is not None and v2 is not None:
                            c["first-shown won both orders"][0] += (v1 > 0.5) and (v2 > 0.5)
                            c["first-shown won both orders"][1] += 1
    return c


def score(args):
    evalset = json.loads(Path(args.evalset).read_text())
    pools = evalset["pools"]
    if args.exclude:
        for k in args.exclude.split(","):
            pools.pop(k, None)
    judges, diag = {}, {}
    for spec in args.judge:
        name, _, globs = spec.partition("=")
        rules = tuple(name.split("@")[1:])
        if set(rules) - {"U", "T", "S"}:
            raise SystemExit(f"unknown rule in {name}; known: @U @T @S")
        s, sg = load_samples(globs.split(","), old_rule=args.old_rule, soft="S" in rules)
        rules = tuple(r for r in rules if r != "S")
        if args.diag:
            diag[name] = {h: diagnostics(pools, s, [k for k, e in pools.items() if e["half"] == h
                                                    and e["stratum"] in ("contested", "easy")
                                                    and json.dumps(sg.get(k, e["sig"])) == json.dumps(e["sig"])])
                          for h in ("design", "test", "bq")}
        judges[name], skipped = score_judge(evalset, s, sg, rules)
        for why, ks in skipped.items():
            print(f"[{name}] {len(ks)} mixed pools left out: {why}", file=sys.stderr)
    sets = [("spider2 design", lambda e: e["half"] == "design"), ("spider2 test", lambda e: e["half"] == "test"),
            ("spider2 all", lambda e: e["bench"] == "spider2"), ("bigquery", lambda e: e["bench"] == "bq")]
    strata = [("contested", ("contested",)), ("easy", ("easy",)), ("mixed", ("contested", "easy"))]
    rows = []
    for sname, sf in sets:
        for tname, ts in strata:
            ks = [k for k, e in pools.items() if sf(e) and e["stratum"] in ts]
            for j, res in judges.items():
                cov = [k for k in ks if k in res]
                rows.append(dict(set=sname, stratum=tname, judge=j, pools=len(ks), scored=len(cov),
                                 exp1=sum(res[k][0] for k in cov), avgK=sum(res[k][1] for k in cov)))
        # whole-benchmark total over the pools this judge is scored on (non-mixed pools count as they are)
        for j, res in judges.items():
            ks = [k for k, e in pools.items() if sf(e)]
            cov = [k for k in ks if k in res]
            rows.append(dict(set=sname, stratum="all pools", judge=j, pools=len(ks), scored=len(cov),
                             exp1=sum(res[k][0] for k in cov), avgK=sum(res[k][1] for k in cov)))
    print(f"{'set':15s} {'stratum':10s} {'judge':14s} {'pools':>5s} {'scored':>6s} {'exp1':>7s} {'avgK':>6s}")
    for r in rows:
        print(f"{r['set']:15s} {r['stratum']:10s} {r['judge']:14s} {r['pools']:5d} {r['scored']:6d} "
              f"{r['exp1']:7.1f} {r['avgK']:6.0f}")
    if args.ref:
        ref = judges[args.ref]
        print(f"\npaired vs {args.ref} on pools both judges cover (exp1 difference, {args.ci:.1%} question bootstrap):")
        for sname, sf in sets:
            for tname, ts in strata:
                for j, res in judges.items():
                    if j == args.ref:
                        continue
                    ks = [k for k, e in pools.items() if sf(e) and e["stratum"] in ts and k in res and k in ref]
                    by_q = defaultdict(float)
                    for k in ks:
                        by_q[pools[k]["iid"]] += res[k][0] - ref[k][0]
                    d = sum(by_q.values())
                    lo, hi = bootstrap(by_q, level=args.ci)
                    up = sum(res[k][0] > ref[k][0] + 1e-9 for k in ks)
                    dn = sum(res[k][0] < ref[k][0] - 1e-9 for k in ks)
                    print(f"  {sname:15s} {tname:10s} {j:14s} n={len(ks):3d} diff {d:+6.1f} "
                          f"[{lo:+.1f}, {hi:+.1f}]  pools up/down {up}/{dn}")
    if args.diag:
        print("\ndiagnostics (per judgment, right-vs-wrong pairs of mixed pools): right / judgments")
        for name, by_half in diag.items():
            for h, c in by_half.items():
                if any(v[1] for v in c.values()):
                    print(f"  {name:14s} {h:6s} " + " | ".join(
                        f"{lab} {c[lab][0]}/{c[lab][1]} = {c[lab][0] / c[lab][1]:.0%}" for lab in
                        ("right shown first", "right shown second", "first-shown won both orders",
                         "right has fewer cols", "right has more cols", "right has same cols") if c[lab][1]))
    if args.stats:
        print("\ncall stats (rejudge_pools.py sources): calls, failed (no verdict), truncated, completion tokens p50/p90")
        for spec in args.judge:
            name, _, globs = spec.partition("=")
            rows = defaultdict(list)
            for f in sorted({f for g in globs.split(",") for f in glob.glob(g)}):
                for line in open(f):
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if "judgments" in r or r.get("retry"):
                        continue
                    e = pools.get(r["key"])
                    rows[e["half"] if e else "?"].append(r)
            for half, rs in sorted(rows.items()):
                toks = sorted(r["completion_tokens"] for r in rs if r.get("completion_tokens"))
                q = (lambda x: toks[min(len(toks) - 1, int(x * len(toks)))] if toks else 0)
                print(f"  {name:14s} {half:6s} {len(rs):6d} calls, failed {sum(bool(r['error']) for r in rs):4d}, "
                      f"truncated {sum(bool(r.get('truncated')) for r in rs):4d}, tokens {q(0.5)}/{q(0.9)}")
    if args.dump:
        Path(args.dump).write_text(json.dumps({j: {k: list(v) for k, v in res.items()} for j, res in judges.items()}))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--pools", required=True, help="Spider2 results/pools dir")
    b.add_argument("--bq-pools", required=True, help="bq_passk/pools dir")
    b.add_argument("--ref-prefix", default="think35/qwen36-35b-think")
    b.add_argument("--rerun-prefix", default="think35_rerun/qwen36-35b-think-rerun")
    b.add_argument("--bq-ref-prefix", default="think35_bq")
    b.add_argument("--questions", default=str(Path(__file__).resolve().parents[2] / "Spider2/spider2-lite/spider2-lite.jsonl"))
    b.add_argument("--seed", type=int, default=20261112)
    b.add_argument("--restarts", type=int, default=2000)
    b.add_argument("--out", required=True)
    s = sub.add_parser("score")
    s.add_argument("--evalset", required=True)
    s.add_argument("--judge", action="append", required=True, help="NAME=GLOB[,GLOB...]")
    s.add_argument("--ref")
    s.add_argument("--ci", type=float, default=0.95, help="bootstrap interval level")
    s.add_argument("--old-rule", action="store_true", help="a judgment without p_first is missing (anatomy.py)")
    s.add_argument("--dump", help="write per-pool (exp1, avgK) per judge to this JSON file")
    s.add_argument("--stats", action="store_true", help="failure/truncation/token stats of rejudge_pools.py calls")
    s.add_argument("--diag", action="store_true", help="position and column-relation diagnostics")
    s.add_argument("--exclude", help="comma-separated pool keys to leave out of every table")
    args = ap.parse_args()
    build(args) if args.cmd == "build" else score(args)


if __name__ == "__main__":
    main()
