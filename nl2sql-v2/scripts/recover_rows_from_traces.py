"""Recover run rows that the shard CSVs lost, from the traces.

bq_v3s wrote 204 trace files but only 175 CSV rows, and bq_v3r 200. Traces are closed
per episode so they land on the volume individually; the shard CSV stays open and is
only visible once the container commits, so a retried or restarted shard loses the
rows it had written while keeping the traces.

The trace carries instance_id, score, status, detail and the submitted SQL, which is
everything the accuracy comparison needs. steps and scan_bytes are not in it, so the
recovered rows are blank there and the cost figures stay based on the rows that do
carry them -- which means reported scan is a floor for these lanes, not a total.
"""
import csv
import json
import sys
from pathlib import Path

FIELDS = ["instance_id", "db", "score", "score_detail", "status", "steps",
          "critic_rounds", "search_calls", "draft_calls", "wall_seconds",
          "sf_queries", "sf_seconds", "scan_bytes", "sql"]

REPO = Path("C:/Users/rohin/Documents/CMU/Capstone/nl2sql-databao")
run_csv = REPO / sys.argv[1]
traces = REPO / sys.argv[2]
ref_csv = REPO / sys.argv[3]          # a lane that has every instance, for db names

rows = {r["instance_id"]: r for r in csv.DictReader(
    open(run_csv, newline="", encoding="utf-8"))}
ref = {r["instance_id"]: r for r in csv.DictReader(
    open(ref_csv, newline="", encoding="utf-8"))}

added = []
for p in sorted(traces.glob("*.json")):
    iid = p.stem
    if iid in rows:
        continue
    t = json.loads(p.read_text(encoding="utf-8"))
    sc = t.get("score")
    rows[iid] = {
        "instance_id": iid,
        "db": ref.get(iid, {}).get("db", ""),
        "score": "1" if sc == 1 else "0",
        "score_detail": t.get("detail") or "",
        "status": t.get("status") or "",
        "steps": "", "critic_rounds": "", "search_calls": "", "draft_calls": "",
        "wall_seconds": "", "sf_queries": "", "sf_seconds": "", "scan_bytes": "",
        "sql": t.get("sql") or "",
    }
    added.append(iid)

out = [rows[i] for i in sorted(rows)]
with open(run_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(out)

c = sum(1 for r in out if r["score"] == "1")
n = len(out)
pct = 100.0 * c / n
se = (pct * (100 - pct) / n) ** 0.5
print(f"recovered {len(added)} row(s) from traces: "
      f"{', '.join(added[:12])}{' ...' if len(added) > 12 else ''}")
print(f"{run_csv.name}: {c}/{n} = {pct:.1f}%  (+/-{1.96 * se:.1f})")
