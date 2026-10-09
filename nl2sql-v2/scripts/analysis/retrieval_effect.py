"""Did retrieval get used, and did it matter anywhere?

bq_v3s came out dead level with bq_v3: 19 won, 19 lost, +0.0 points. A null result
means two very different things depending on whether the model actually called
search_context, so that is measured first. Then the lane is split the way the index's
own coverage report says it should be: where a database ships no column descriptions,
the cards carry only names and there was never much to add.
"""
import csv
import json
from collections import Counter
from pathlib import Path

REPO = Path("C:/Users/rohin/Documents/CMU/Capstone/nl2sql-databao")
TS = REPO / "logs/traces/bq_v3s"


def load(p):
    return {r["instance_id"]: r for r in csv.DictReader(
        open(p, newline="", encoding="utf-8"))}


A = load(REPO / "results/bq_v3_run.csv")
B = load(REPO / "results/bq_v3s_run.csv")
shared = sorted(set(A) & set(B))
cov = {x["db"]: x for x in json.loads(
    (REPO / "rptdl/build_report.json").read_text(encoding="utf-8"))
    if not x.get("error")}

used, calls, errored = set(), 0, set()
for iid in shared:
    p = TS / f"{iid}.json"
    if not p.exists():
        continue
    t = json.loads(p.read_text(encoding="utf-8"))
    sc = [e for e in t.get("trace", []) if e.get("tool") == "search_context"]
    if sc:
        used.add(iid)
        calls += len(sc)
        if any(str(e.get("result", "")).startswith("ERROR") for e in sc):
            errored.add(iid)

print(f"episodes compared        : {len(shared)}")
print(f"  called search_context  : {len(used)} "
      f"({100 * len(used) / len(shared):.0f}%), {calls} calls")
print(f"  any call errored       : {len(errored)}   <- must be 0")


def rate(ids, R):
    c = sum(1 for i in ids if R[i]["score"] == "1")
    return c, len(ids), 100.0 * c / len(ids) if ids else 0.0


for label, ids in (
        ("episodes that USED retrieval", sorted(used)),
        ("episodes that did NOT use it", [i for i in shared if i not in used])):
    if not ids:
        continue
    ca, n, pa = rate(ids, A)
    cb, _, pb = rate(ids, B)
    won = sum(1 for i in ids if A[i]["score"] != "1" and B[i]["score"] == "1")
    lost = sum(1 for i in ids if A[i]["score"] == "1" and B[i]["score"] != "1")
    print(f"\n{label}  (n={n})")
    print(f"  bq_v3  {ca:3d}/{n} = {pa:5.1f}%")
    print(f"  bq_v3s {cb:3d}/{n} = {pb:5.1f}%     delta {pb - pa:+5.1f}   "
          f"flips +{won}/-{lost}")

# the split the build report argues for
described = [i for i in shared
             if cov.get(A[i]["db"], {}).get("columns_described", 0) > 0]
bare = [i for i in shared if i not in described]
for label, ids in (("databases WITH descriptions", described),
                   ("databases with NONE", bare)):
    if not ids:
        continue
    ca, n, pa = rate(ids, A)
    cb, _, pb = rate(ids, B)
    print(f"\n{label}  (n={n})")
    print(f"  bq_v3  {pa:5.1f}%   bq_v3s {pb:5.1f}%   delta {pb - pa:+5.1f}")

print("\nThe dump already names every table, so retrieval could only add the "
      "descriptions the dump drops. These numbers say what that was worth.")
