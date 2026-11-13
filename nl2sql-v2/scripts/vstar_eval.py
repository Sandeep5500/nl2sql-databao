#!/usr/bin/env python3
"""Step 2 of documents/head_probe_prereg.md: score the DPO-trained judges as trace verifiers.
For each held-out practice trace (vstar_scores.py output), the implicit reward of a DPO judge is
log pi_dpo(y|x) - log pi_base(y|x). Reported: within-pair AUROC (right vs wrong traces of the same
ordered pair, mixed pairs, other_reading pairs dropped) with a database-bootstrap interval, per
source batch and pooled, next to two label-free baselines: shorter reply first (-tokens) and the
base model's mean token log-probability of its own reply.

    python scripts/vstar_eval.py --scores-dir <dir with scores_*.jsonl> --practice <practice dir>
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_fit import auc_of, db_bootstrap, practice_info, within_pair  # noqa: E402


def batch(r):
    if r["file"] == "train_v1":
        return "bird_platinum" if r["source"] == "bird_platinum" else "claude_v1"
    return {"cplx_v1": "complex", "cplx_v2": "complex", "beaver_p1": "beaver"}.get(r["file"], r["file"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores-dir", required=True)
    ap.add_argument("--practice", required=True)
    ap.add_argument("--base", default="qwen36-base")
    ap.add_argument("--models", default="judge-v2a,judge-v3c")
    args = ap.parse_args()
    _, other, _ = practice_info(args.practice)
    load = lambda m: {r["id"]: r for r in map(json.loads, open(Path(args.scores_dir) / f"scores_{m}.jsonl"))}
    base = load(args.base)
    models = {m: load(m) for m in args.models.split(",") if (Path(args.scores_dir) / f"scores_{m}.jsonl").exists()}
    ids = [i for i in base if all(i in s for s in models.values())
           and (base[i]["instance_id"], frozenset((base[i]["first"], base[i]["second"]))) not in other]
    rows = [base[i] for i in ids]
    scores = {"shorter reply (-tokens)": [-r["n_tokens"] for r in rows],
              "base mean token logprob": [r["logp"] / max(1, r["n_tokens"]) for r in rows]}
    for m, s in models.items():
        scores[f"{m} implicit reward"] = [s[i]["logp"] - base[i]["logp"] for i in ids]
    groups = {b: [b] for b in sorted({batch(r) for r in rows})}
    groups["spider2_like (complex + claude_h1 + claude_h2)"] = ["complex", "claude_h1", "claude_h2"]
    groups["all held-out"] = sorted({batch(r) for r in rows})
    print(f"{len(rows)} held-out traces scored by {args.base} and {', '.join(models) or 'no DPO model yet'}")
    out = {}
    for gname, members in groups.items():
        ii = [j for j, r in enumerate(rows) if batch(r) in members]
        per = {name: within_pair(np.array(v), rows, ii) for name, v in scores.items()}
        names = list(per)
        boot = db_bootstrap([per[n] for n in names], reps=2000)
        n_cmp = int(sum(v[1] for v in per[names[0]].values()))
        out[gname] = {n: dict(auc=round(auc_of(per[n]), 3),
                              ci=[round(float(np.nanpercentile(boot[:, k], 2.5)), 3),
                                  round(float(np.nanpercentile(boot[:, k], 97.5)), 3)])
                      for k, n in enumerate(names)}
        out[gname]["comparisons"] = n_cmp
        print(f"\n{gname} ({n_cmp} right/wrong comparisons in mixed ordered pairs)")
        for n in names:
            print(f"  {n:34s} within-pair AUROC {out[gname][n]['auc']:.3f} {out[gname][n]['ci']}")
    Path(args.scores_dir, "vstar_eval.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
