"""pass@k on BigQuery: greedy full_R plus k temp-0.7 samples run only on full_R's failures.

Valid for pass@k (solved by ANY attempt): a question greedy already solved cannot change
that metric, so skipping it is exact. NOT valid as pass@1 / accuracy -- the scorer chose
what got retried. Comparable to SQLite's "pass@4 with greedy" (57.8%), not its 51.1%.
"""
import csv
from pathlib import Path
ROOT = Path(r"C:\Users\rohin\Documents\CMU\Capstone\nl2sql-databao")
load = lambda t: {r["instance_id"]: r["score"] == "1" for r in
                  csv.DictReader(open(ROOT / f"results/{t}/all.csv", encoding="utf-8"))}
G = load("full_R")
fails = [i for i, ok in G.items() if not ok]
S = []
for k in (1, 2, 3, 4):
    p = ROOT / f"results/failR_s{k}/all.csv"
    if p.exists():
        S.append(load(f"failR_s{k}"))
n = len(G)
print(f"greedy full_R: {sum(G.values())}/{n} = {100 * sum(G.values()) / n:.1f}%   failures retried: {len(fails)}")
for k, s in enumerate(S, 1):
    missing = [i for i in fails if i not in s]
    rec = sum(s.get(i, False) for i in fails)
    print(f"  sample {k}: {len(fails) - len(missing)} scored, recovers {rec} "
          f"({100 * rec / len(fails):.1f}% of failures){'  MISSING ' + str(len(missing)) if missing else ''}")
solved = {i for i, ok in G.items() if ok}
print(f"\ncumulative (greedy + k samples):  k=0 {len(solved)} ({100 * len(solved) / n:.1f}%)")
for k, s in enumerate(S, 1):
    solved |= {i for i in fails if s.get(i)}
    print(f"                                  k={k} {len(solved)} ({100 * len(solved) / n:.1f}%)")
never = sorted(set(fails) - solved)
print(f"\nnever solved by any attempt: {len(never)}")
