#!/usr/bin/env python3
"""Stage A of documents/head_probe_prereg.md: a logistic probe on the judge's hidden states after its
own reasoning (extract_judge_states.py shards) predicting "this trace's verdict is right", chosen
on practice training databases only and scored once on the held-out practice set.

- Data: practice traces, other_reading pairs dropped. Training = split "train" on databases outside
  holdout.json; held-out = split "heldout" (the val split) or a holdout.json database.
- Configurations: every (layer, position) of the shards, each with the verdict letter as a covariate.
  Features are standardized inside each fold. C is chosen per configuration by leave-one-database-out
  cross-validation on log loss with the one-SE rule (the largest penalty within one SE of the best);
  the configuration with the lowest cross-validated log loss is frozen.
- Baseline: the same procedure on [verdict letter, log reasoning length, hedge-word rate].
- Gate A, on the held-out mixed ordered pairs: within-pair AUROC (right vs wrong traces of the same
  ordered pair) >= 0.65 and >= baseline + 0.05 with the database-bootstrap interval of the
  difference above 0 (4,000 reps, seed 0).
Nothing from Spider2 or BigQuery is read. The held-out report is written once; --force reruns it.

    python scripts/probe_fit.py --states <dir> [<dir>] --practice <dir with the verdict and
        pair_labels files and judge_train_v4/data_v6/holdout.json> --out <report prefix>
"""

import argparse
import glob
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

LAYERS = ["L10", "L20", "L30", "final"]  # extract_judge_states.py --layers 9,19,29 (outputs) + final norm
POSITIONS = ["verdict", "think_end", "reason_mean", "reason_25", "reason_50", "reason_75"]
CS = [1e-3, 1e-2, 1e-1, 1.0]
HEDGE = re.compile(r"\b(wait|however|actually|hmm|but|re-?check|double[- ]check|not sure|ambiguous|either|"
                   r"alternatively|on the other hand)\b", re.I)
LABEL_FILES = {"cplx_v1": "judge_cplx/pair_labels_v1.jsonl", "cplx_v2": "judge_cplx/pair_labels_v2.jsonl",
               "claude_v3": "judge_claude/pair_labels_v3.jsonl", "claude_h1": "judge_claude/pair_labels_h1.jsonl",
               "claude_h2": "judge_claude/pair_labels_h2.jsonl", "beaver_p1": "judge_beaver/pair_labels_p1.jsonl"}
VERDICT_FILES = {"train_v1": "judge_train/verdicts_train_v1.jsonl", "cplx_v1": "judge_cplx/verdicts_cplx_v1.jsonl",
                 "cplx_v2": "judge_cplx/verdicts_cplx_v2.jsonl", "claude_v3": "judge_claude/verdicts_claude_v3.jsonl",
                 "claude_h1": "judge_claude/verdicts_claude_h1.jsonl", "claude_h2": "judge_claude/verdicts_claude_h2.jsonl",
                 "beaver_p1": "judge_beaver/verdicts_beaver_p1.jsonl"}


def load_states(dirs):
    feats, zs, meta = [], [], []
    for d in dirs:
        for f in sorted(glob.glob(f"{d}/shard_*.npz")):
            if ".tmp" in f:
                continue
            a = np.load(f)
            m = [json.loads(l) for l in open(f.replace(".npz", ".jsonl"))]
            feats.append(a["feats"]), zs.append(a["z"]), meta.extend(m)
    return np.concatenate(feats), np.concatenate(zs), meta


def practice_info(pdir):
    """other_reading unordered pairs, hedge rates per trace, holdout databases."""
    hold = set(json.load(open(f"{pdir}/judge_train_v4/data_v6/holdout.json"))["databases"])
    other, hedge = set(), {}
    for tag, vf in VERDICT_FILES.items():
        recs = {}
        for line in open(f"{pdir}/{vf}"):
            r = json.loads(line)
            recs[r["instance_id"]] = r
            for pi, p in enumerate(r["pairs"]):
                for si, s in enumerate(p["samples"]):
                    t = s.get("reasoning") or ""
                    hedge[(tag, r["instance_id"], pi, si)] = len(HEDGE.findall(t)) / max(1, len(t.split())) * 1000
        lf = LABEL_FILES.get(tag)
        if lf:
            for row in map(json.loads, open(f"{pdir}/{lf}")):
                iid, pi = row["id"].rsplit("#", 1)
                r = recs.get(iid)
                if r is None or int(pi) >= len(r["pairs"]):
                    continue
                p = r["pairs"][int(pi)]
                if row["label"] == "other_reading":
                    other.add((iid, frozenset((p["first"], p["second"]))))
    return hold, other, hedge


def within_pair(scores, rows, idx):
    """(sum of right-above-wrong comparisons, count) per database, over mixed ordered pairs in idx."""
    by_pair = defaultdict(list)
    for i in idx:
        r = rows[i]
        by_pair[(r["file"], r["instance_id"], r["pair"])].append(i)
    per_db = defaultdict(lambda: [0.0, 0])
    for key, ii in by_pair.items():
        right = [scores[i] for i in ii if rows[i]["right"]]
        wrong = [scores[i] for i in ii if not rows[i]["right"]]
        if not right or not wrong:
            continue
        db = rows[ii[0]]["db"]
        for a in right:
            for b in wrong:
                per_db[db][0] += (a > b) + 0.5 * (a == b)
                per_db[db][1] += 1
    return per_db


def auc_of(per_db):
    s = sum(v[0] for v in per_db.values())
    n = sum(v[1] for v in per_db.values())
    return s / n if n else float("nan")


def db_bootstrap(per_dbs, reps=4000, seed=0):
    """per_dbs: list of per-database dicts; returns the bootstrap distribution of each AUROC."""
    rng = np.random.default_rng(seed)
    dbs = sorted(set().union(*[set(p) for p in per_dbs]))
    out = []
    for _ in range(reps):
        pick = rng.choice(len(dbs), len(dbs), replace=True)
        vals = []
        for p in per_dbs:
            s = sum(p[dbs[j]][0] for j in pick if dbs[j] in p)
            n = sum(p[dbs[j]][1] for j in pick if dbs[j] in p)
            vals.append(s / n if n else float("nan"))
        out.append(vals)
    return np.array(out)


def fit_predict(Xtr, ytr, Xte, C):
    from sklearn.linear_model import LogisticRegression
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-6
    m = LogisticRegression(C=C, max_iter=3000)
    m.fit((Xtr - mu) / sd, ytr)
    return m.predict_proba((Xte - mu) / sd)[:, 1]


def cv_logloss(X, y, groups, C):
    """Leave-one-database-out predictions; (pooled log loss, SE over databases, predictions)."""
    pred = np.zeros(len(y))
    for g in np.unique(groups):
        te = groups == g
        if te.all() or len(np.unique(y[~te])) < 2:
            pred[te] = y[~te].mean()
            continue
        pred[te] = fit_predict(X[~te], y[~te], X[te], C)
    p = np.clip(pred, 1e-6, 1 - 1e-6)
    ll = -(y * np.log(p) + (1 - y) * np.log(1 - p))
    per_db = np.array([ll[groups == g].mean() for g in np.unique(groups)])
    return ll.mean(), per_db.std(ddof=1) / math.sqrt(len(per_db)), pred


def select(X, y, groups):
    """C by the one-SE rule: the smallest C within one SE of the best cross-validated log loss."""
    res = {C: cv_logloss(X, y, groups, C) for C in CS}
    best = min(res, key=lambda C: res[C][0])
    pick = min(C for C in CS if res[C][0] <= res[best][0] + res[best][1])
    return pick, res[pick][0], res[pick][2], {str(C): round(res[C][0], 5) for C in CS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", nargs="+", required=True)
    ap.add_argument("--practice", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    if Path(f"{out}.heldout.json").exists() and not args.force:
        raise SystemExit(f"{out}.heldout.json exists: the held-out set is scored once (--force to rerun)")

    feats, z, rows = load_states(args.states)
    if any(re.match(r"(spider2:|bq:|local\d|bq\d|sf\d)", str(r.get("instance_id", ""))) for r in rows):
        raise SystemExit("Spider2 / BigQuery rows found: this probe is fit on practice data only")
    hold, other, hedge = practice_info(args.practice)
    keep = [i for i, r in enumerate(rows) if not r.get("skipped")
            and (r["instance_id"], frozenset((r["first"], r["second"]))) not in other]
    is_held = np.array([rows[i]["split"] == "heldout" or rows[i]["db"] in hold for i in keep])
    y = np.array([float(rows[i]["right"]) for i in keep])
    va = np.array([float(rows[i]["verdict"] == "A") for i in keep])
    zk = z[keep]
    ident = float(np.mean((zk > 0) == (va == 1)))
    groups = np.array([rows[i]["db"] for i in keep])
    tr, te = ~is_held, is_held
    print(f"{len(rows)} traces; {len(keep)} after other_reading removal; train {tr.sum()} "
          f"({len(np.unique(groups[tr]))} dbs), held-out {te.sum()} ({len(np.unique(groups[te]))} dbs); "
          f"identity (sign of logit A-B = stored verdict) {ident:.4f}", flush=True)
    if ident < 0.99:
        raise SystemExit("identity check below 0.99: the rebuilt sequences do not match the judge's")

    base = np.column_stack([va, np.log1p([rows[i]["reasoning_chars"] for i in keep]),
                            [hedge[(rows[i]["file"], rows[i]["instance_id"], rows[i]["pair"], rows[i]["sample"])]
                             for i in keep]])
    configs = {}
    for li, lname in enumerate(LAYERS[:feats.shape[1]]):
        for pi, pname in enumerate(POSITIONS[:feats.shape[2]]):
            X = np.column_stack([feats[keep, li, pi, :].astype(np.float32), va])
            C, ll, pred, grid = select(X[tr], y[tr], groups[tr])
            cv_auc = auc_of(within_pair(pred, [rows[i] for i in np.array(keep)[tr]], range(int(tr.sum()))))
            configs[f"{lname}/{pname}"] = dict(C=C, cv_logloss=ll, cv_within_auc=cv_auc, grid=grid)
            print(f"{lname}/{pname}: C={C} cv logloss {ll:.4f} cv within-pair AUROC {cv_auc:.3f}", flush=True)
    bC, bll, bpred, bgrid = select(base[tr], y[tr], groups[tr])
    b_cv_auc = auc_of(within_pair(bpred, [rows[i] for i in np.array(keep)[tr]], range(int(tr.sum()))))
    chosen = min(configs, key=lambda k: configs[k]["cv_logloss"])
    sel = dict(n_configs=len(configs), configs=configs, chosen=chosen,
               baseline=dict(C=bC, cv_logloss=bll, cv_within_auc=b_cv_auc, grid=bgrid))
    Path(f"{out}.selection.json").write_text(json.dumps(sel, indent=1))
    print(f"frozen: {chosen} (C={configs[chosen]['C']}); baseline C={bC}; selection written", flush=True)

    # held-out evaluation, once
    lname, pname = chosen.split("/")
    li, pi = LAYERS.index(lname), POSITIONS.index(pname)
    X = np.column_stack([feats[keep, li, pi, :].astype(np.float32), va])
    p_probe = fit_predict(X[tr], y[tr], X[te], configs[chosen]["C"])
    p_base = fit_predict(base[tr], y[tr], base[te], bC)
    te_rows = [rows[i] for i in np.array(keep)[te]]
    wp_probe = within_pair(p_probe, te_rows, range(len(te_rows)))
    wp_base = within_pair(p_base, te_rows, range(len(te_rows)))
    boot = db_bootstrap([wp_probe, wp_base])
    diff = boot[:, 0] - boot[:, 1]
    from sklearn.metrics import roc_auc_score
    yt = y[te]
    rep = dict(
        heldout_traces=int(te.sum()), heldout_dbs=int(len(np.unique(groups[te]))),
        mixed_comparisons=int(sum(v[1] for v in wp_probe.values())),
        probe=dict(config=chosen, within_auc=auc_of(wp_probe), ci=[float(np.nanpercentile(boot[:, 0], 2.5)),
                                                                    float(np.nanpercentile(boot[:, 0], 97.5))],
                   pooled_auc=float(roc_auc_score(yt, p_probe)), brier=float(np.mean((p_probe - yt) ** 2))),
        baseline=dict(within_auc=auc_of(wp_base), ci=[float(np.nanpercentile(boot[:, 1], 2.5)),
                                                      float(np.nanpercentile(boot[:, 1], 97.5))],
                      pooled_auc=float(roc_auc_score(yt, p_base)), brier=float(np.mean((p_base - yt) ** 2))),
        diff=dict(point=auc_of(wp_probe) - auc_of(wp_base), ci=[float(np.nanpercentile(diff, 2.5)),
                                                                float(np.nanpercentile(diff, 97.5))]),
    )
    def batch(r):  # source batches as in documents/head_probe_prereg.md
        if r["file"] == "train_v1":
            return "bird_platinum" if r["source"] == "bird_platinum" else "claude_v1"
        return {"cplx_v1": "complex", "cplx_v2": "complex", "beaver_p1": "beaver"}.get(r["file"], r["file"])
    groups_rep = {b: [b] for b in sorted({batch(r) for r in te_rows})}
    groups_rep["spider2_like (complex + claude_h1 + claude_h2)"] = ["complex", "claude_h1", "claude_h2"]
    per_src = {}
    for src, members in groups_rep.items():
        ii = [j for j, r in enumerate(te_rows) if batch(r) in members]
        per_src[src] = dict(probe=auc_of(within_pair(p_probe, te_rows, ii)),
                            baseline=auc_of(within_pair(p_base, te_rows, ii)),
                            comparisons=int(sum(v[1] for v in within_pair(p_probe, te_rows, ii).values())))
    rep["per_source"] = per_src
    rep["gate_A"] = bool(rep["probe"]["within_auc"] >= 0.65 and rep["diff"]["point"] >= 0.05 and rep["diff"]["ci"][0] > 0)
    Path(f"{out}.heldout.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
