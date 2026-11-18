#!/usr/bin/env python3
"""The two-loss judges as pickers and as trace verifiers, on the held-out practice traces scored by
c2_scores.py (one scores_<name>.jsonl per arm, plus scores_base.jsonl for the untrained judge):

  keep      share of right traces after which the pick is the correct letter
  overrule  share of wrong traces after which the pick is the correct letter (the base echoes the
            trace, so about 0)
  pair acc  share of ordered pairs whose mean P(correct letter) over their samples is above 1/2
  AUROC     within-pair AUROC (right vs wrong traces of the same ordered pair) of the judge's belief in
            the trace's own verdict, log P(verdict) - log P(other letter), and, for the vector arms,
            of the head score; database-bootstrap 95% intervals

Mixed ordered pairs only for AUROC, other_reading pairs dropped, groups by source batch, as
vstar_eval.py.

    python scripts/c2_eval.py --scores-dir <dir> --practice <practice dir>
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_fit import auc_of, db_bootstrap, practice_info, within_pair  # noqa: E402
from vstar_eval import batch  # noqa: E402


def p_correct(r):
    a, b = r["lp_a"], r["lp_b"]
    m = max(a, b)
    pa = np.exp(a - m) / (np.exp(a - m) + np.exp(b - m))
    return pa if r["correct_letter"] == "A" else 1 - pa


def belief(r):
    """log-odds the judge gives the trace's own verdict over the other letter."""
    d = r["lp_a"] - r["lp_b"]
    return d if r["verdict"] == "A" else -d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores-dir", required=True)
    ap.add_argument("--practice", required=True)
    args = ap.parse_args()
    _, other, _ = practice_info(args.practice)
    files = sorted(Path(args.scores_dir).glob("scores_*.jsonl"))
    names = [f.stem.removeprefix("scores_") for f in files]
    loaded = {n: {r["id"]: r for r in map(json.loads, open(f))} for n, f in zip(names, files)}
    ids = sorted(set.intersection(*[set(s) for s in loaded.values()]))
    ids = [i for i in ids if (loaded[names[0]][i]["instance_id"],
                              frozenset((loaded[names[0]][i]["first"], loaded[names[0]][i]["second"]))) not in other]
    rows = [loaded[names[0]][i] for i in ids]
    print(f"{len(rows)} held-out traces scored by all of {', '.join(names)}")

    out = {}
    for n in names:
        rs = [loaded[n][i] for i in ids]
        pc = np.array([p_correct(r) for r in rs])
        right = np.array([r["right"] for r in rs])
        by_pair = defaultdict(list)
        for r, p in zip(rs, pc):
            by_pair[(r["file"], r["instance_id"], r["pair"])].append(p)
        out[n] = dict(keep=round(float((pc[right] > 0.5).mean()), 3),
                      overrule=round(float((pc[~right] > 0.5).mean()), 3),
                      pair_acc=round(float(np.mean([np.mean(v) > 0.5 for v in by_pair.values()])), 3),
                      pairs=len(by_pair))
        print(f"{n:12s} keep {out[n]['keep']:.3f}  overrule {out[n]['overrule']:.3f}  "
              f"pair acc {out[n]['pair_acc']:.3f} over {len(by_pair)} ordered pairs")

    scores = {}
    for n in names:
        scores[f"{n} belief in the trace's verdict"] = [belief(loaded[n][i]) for i in ids]
        if all("vec" in loaded[n][i] for i in ids):
            scores[f"{n} vector head"] = [loaded[n][i]["vec"] for i in ids]
    scores["shorter reasoning (-tokens)"] = [-r["n_tokens"] for r in rows]
    groups = {b: [b] for b in sorted({batch(r) for r in rows})}
    groups["spider2_like (complex + claude_h1 + claude_h2)"] = ["complex", "claude_h1", "claude_h2"]
    groups["all held-out"] = sorted({batch(r) for r in rows})
    for gname, members in groups.items():
        ii = [j for j, r in enumerate(rows) if batch(r) in members]
        per = {s: within_pair(np.array(v), rows, ii) for s, v in scores.items()}
        keys = list(per)
        boot = db_bootstrap([per[k] for k in keys], reps=2000)
        n_cmp = int(sum(v[1] for v in per[keys[0]].values()))
        out[gname] = {k: dict(auc=round(auc_of(per[k]), 3),
                              ci=[round(float(np.nanpercentile(boot[:, j], 2.5)), 3),
                                  round(float(np.nanpercentile(boot[:, j], 97.5)), 3)])
                      for j, k in enumerate(keys)}
        out[gname]["comparisons"] = n_cmp
        print(f"\n{gname} ({n_cmp} right/wrong comparisons in mixed ordered pairs)")
        for k in keys:
            print(f"  {k:44s} within-pair AUROC {out[gname][k]['auc']:.3f} {out[gname][k]['ci']}")
    Path(args.scores_dir, "c2_eval.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
