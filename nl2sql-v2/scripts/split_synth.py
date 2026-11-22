"""Split the synthetic root into evolve / held-out / reserve BY DATABASE.

Splitting by question would leak: two questions on the same schema share the
same tables, keys and quirks, so a lesson learned on one transfers to the other
and the held-out set stops being held out.
"""
import argparse, json, random
from collections import defaultdict
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--root", default="/data/user_data/juliep2/synthroot_full")
ap.add_argument("--evolve", type=int, default=250)
ap.add_argument("--heldout", type=int, default=250)
ap.add_argument("--seed", type=int, default=13)
a = ap.parse_args()

lite = Path(a.root) / "Spider2/spider2-lite"
qs = [json.loads(l) for l in open(lite / "spider2-lite.jsonl")]
by_db = defaultdict(list)
for q in qs:
    by_db[q["db"]].append(q["instance_id"])
dbs = sorted(by_db)
random.Random(a.seed).shuffle(dbs)
print(f"{len(qs)} questions across {len(dbs)} databases")

evolve, heldout, reserve = [], [], []
for db in dbs:
    ids = by_db[db]
    if len(evolve) < a.evolve:       evolve += ids
    elif len(heldout) < a.heldout:   heldout += ids
    else:                            reserve += ids

out = Path(a.root) / "splits"
out.mkdir(exist_ok=True)
for name, ids in (("evolve", evolve), ("heldout", heldout), ("reserve", reserve)):
    (out / f"{name}.txt").write_text(",".join(ids))
    ndb = len({q["db"] for q in qs if q["instance_id"] in set(ids)})
    print(f"  {name:<9}{len(ids):>5} questions  {ndb:>4} databases")

overlap = set()
for a_, b_ in (("evolve", evolve), ("heldout", heldout)):
    pass
e_db = {q["db"] for q in qs if q["instance_id"] in set(evolve)}
h_db = {q["db"] for q in qs if q["instance_id"] in set(heldout)}
print(f"\n  database overlap evolve/heldout: {len(e_db & h_db)}  (must be 0)")
print(f"  splits written to {out}")
