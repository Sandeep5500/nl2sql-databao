#!/usr/bin/env python3
"""Selection-eval set for Spider2 run sets added after the Nov 12 eval set (Nov 18: Sandeep's q36e and
q36x). Pools are built as `selection_eval.py build` builds them, from group-only reference pools
(judge_pools.py --no-judge), and each is put in the design or test half of an existing eval set by its
database, so the halves mean what they meant in the Nov 12 split. Spider2 only; rejudge_pools.py and
`selection_eval.py score` read the output like any eval set.

It also checks the labels: per question, the lanes in correct groups against the lanes the run recorded
as correct (lanes whose SQL fails when re-run fall in no group and count as wrong).

Usage (from nl2sql-v2/):
    python scripts/runset_evalset.py --pools $W/results/pools --ref-prefix groups/sp --runsets q36e,q36x \\
        --split-from selection_evalset.json --out runsets_evalset.json
"""

import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql.config import QUESTIONS_FILE
from selection_eval import pool_groups, pool_key, signature, stratum


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pools", required=True, help="dir holding <ref-prefix>_<runset>_n12_s<k>.jsonl")
    ap.add_argument("--ref-prefix", default="groups/sp")
    ap.add_argument("--runsets", required=True, help="comma-separated, e.g. q36e,q36x")
    ap.add_argument("--split-from", required=True, help="eval set whose design/test databases to reuse")
    ap.add_argument("--questions", default=str(QUESTIONS_FILE))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    split = json.loads(Path(args.split_from).read_text())["split"]
    half = {**{d: "design" for d in split["design_dbs"]}, **{d: "test" for d in split["test_dbs"]}}
    qdb = {q["instance_id"]: q["db"] for q in map(json.loads, open(args.questions))}
    pools, label_diff = {}, []
    for rs in args.runsets.split(","):
        files = sorted(glob.glob(f"{args.pools}/{args.ref_prefix}_{rs}_n12_s*.jsonl"))
        if len(files) != 12:
            raise SystemExit(f"{rs}: expected 12 shards, found {len(files)}")
        for f in files:
            for line in open(f):
                it = json.loads(line)
                k = pool_key(f, it["instance_id"])
                if k.split(":")[1] != rs:
                    raise SystemExit(f"{f}: pool key {k} does not name run set {rs}")
                groups = pool_groups(it, False)
                s, ncorr = stratum(groups)
                db = qdb[it["instance_id"]]
                pools[k] = {"bench": "spider2", "iid": it["instance_id"], "runset": rs, "db": db,
                            "half": half[db], "stratum": s, "ncorr": ncorr, "groups": groups,
                            "sig": signature(it), "contains": it.get("contains", [])}
                recorded = sum(l["recorded_score"] for l in it["lanes"])
                if recorded != ncorr:
                    label_diff.append((k, recorded, ncorr, [l["error"][:60] for l in it["lanes"] if l["error"]]))
    for rs in args.runsets.split(","):
        n = sum(e["runset"] == rs for e in pools.values())
        if n != 135:
            raise SystemExit(f"{rs}: {n} pools, expected 135")
    Path(args.out).write_text(json.dumps({"pools": pools, "split": split}, indent=1))
    print(f"wrote {args.out}: {len(pools)} pools")
    for rs in args.runsets.split(","):
        for h in ("design", "test"):
            cnt = Counter(e["stratum"] for e in pools.values() if e["runset"] == rs and e["half"] == h)
            print(f"  {rs:6s} {h:6s} " + " ".join(f"{s} {cnt[s]}" for s in ("contested", "easy", "all_correct", "no_correct")))
        es = [e for e in pools.values() if e["runset"] == rs]
        pairs = sum(len([g for g in e["groups"] if g[0] > 0]) * (len([g for g in e["groups"] if g[0] > 0]) - 1)
                    for e in es if e["stratum"] in ("contested", "easy"))
        print(f"  {rs:6s} pass@1 {sum(sum(g[0] * g[1] for g in e['groups']) for e in es) / 4:.2f}, pass@4 "
              f"{sum(e['ncorr'] > 0 for e in es)}, ordered pairs in mixed pools {pairs}")
    print(f"label check: {len(label_diff)} pools where correct lanes in groups differ from the recorded scores")
    for k, rec, got, errs in label_diff:
        print(f"  {k}: recorded {rec}, grouped {got}" + (f", errors {errs}" if errs else ""))


if __name__ == "__main__":
    main()
