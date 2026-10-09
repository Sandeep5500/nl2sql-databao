"""Split bq_v3r by whether the rubric actually reached the prompt.

The rubric is gated: it is appended only when rows_confidence == "high" and
exact_rows is not None. Questions that fail the gate get a prompt byte-identical to
bq_v3's, so their flips are pure sampling variance at temperature 0 -- a noise floor
measured on the same run, which is what makes the gated group's movement readable.

Without this split a +5.5 point net is just a number with a confidence interval
wrapped around it.
"""
import csv
import glob
import json
import sys
from pathlib import Path

REPO = Path("C:/Users/rohin/Documents/CMU/Capstone/nl2sql-databao")
RUB = REPO / "dlrub" / "rubric_bq"


def load(p):
    return {r["instance_id"]: r for r in csv.DictReader(
        open(p, newline="", encoding="utf-8"))}


A = load(REPO / "results/bq_v3_run.csv")
B = load(REPO / "results/bq_v3r_run.csv")
shared = sorted(set(A) & set(B))

gated = set()
seen = 0
for f in glob.glob(str(RUB / "*.json")):
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
    except ValueError:
        continue
    seen += 1
    r = d.get("rubric") or {}
    if r.get("rows_confidence") == "high" and r.get("exact_rows") is not None:
        gated.add(d.get("instance_id") or Path(f).stem)

print(f"rubric files read: {seen}; passed the confidence gate: {len(gated)}")

for label, ids in (("rubric IN the prompt", [i for i in shared if i in gated]),
                   ("prompt byte-identical to bq_v3",
                    [i for i in shared if i not in gated])):
    if not ids:
        continue
    ca = {i for i in ids if A[i]["score"] == "1"}
    cb = {i for i in ids if B[i]["score"] == "1"}
    n = len(ids)
    won, lost = cb - ca, ca - cb
    pa, pb = 100.0 * len(ca) / n, 100.0 * len(cb) / n
    print(f"\n{label}  (n={n})")
    print(f"  bq_v3  {len(ca):3d}/{n} = {pa:5.1f}%")
    print(f"  bq_v3r {len(cb):3d}/{n} = {pb:5.1f}%     delta {pb - pa:+5.1f} points")
    print(f"  flips: +{len(won)} / -{len(lost)}  (churn {len(won) + len(lost)} "
          f"= {100.0 * (len(won) + len(lost)) / n:.0f}% of the group)")

print("\nRead the second group as the noise floor: its prompt did not change, so "
      "whatever it moved is sampling variance, and the first group has to beat that "
      "to count as the rubric doing something.")
