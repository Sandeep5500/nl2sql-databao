"""Scores on the 204 BigQuery questions (Nov 17 run) when the 13 audited labels are corrected (Nov 18 gold audit,
nl2sql-v2/reports/Spider2 Lite BigQuery gold errors.md). Lanes k1..k4 = lanes 0..3.

  strict:  fix scoring defects and clear errors only (bq035 radius/tolerance, bq002 week start, bq055 format
           patchwork, bq389 unusable long-format files, ga010 must report a real session count, bq424 must use
           the latest-year debt stock, not a 51-year sum)
  lenient: strict, plus accept both fair readings where the question allows two (bq397, bq208, bq151, bq308,
           bq051; ga010 channel name alone or with a real count; bq424 keeps the summed file)
Only these 13 questions were audited, and they were chosen because the judges lost there, so the corrected
scores lean in the judges' favour; a full audit could move other questions either way. The full audit of all
204 questions (Nov 19, bq_audit_labels.py) starts from these labels.

Reads results/bq17/ (not tracked). usage (from nl2sql-v2/): python3 scripts/bq_corrected_labels.py
"""
import glob
import json
from pathlib import Path

from selection_eval import load_samples, pool_scores

R = Path(__file__).resolve().parents[2] / "results"
I = R / "bq17/improve"
CURRENT_NOTE = {}  # filled from the pools for a check
STRICT = {"bq035": {1, 3}, "ga010": {1, 2}, "bq002": {2, 3}, "bq424": set(), "bq055": {0, 1, 2, 3},
          "bq389": {0, 1, 3}}
LENIENT = dict(STRICT, bq397={1, 2, 3}, bq208={1, 2, 3}, bq151={0, 1, 3}, bq308={1, 2, 3}, bq051={0, 1},
               ga010={0, 1, 2, 3}, bq424={0, 1, 2})
EXPECT_NOW = {"bq045": {0, 1}, "bq356": {3}, "bq051": {1}, "bq035": {1}, "bq397": {2, 3}, "ga010": {0},
              "bq002": {2}, "bq208": {1, 3}, "bq151": {0}, "bq308": {2}, "bq424": {0, 1, 2}, "bq055": {0, 2},
              "bq389": {1, 3}}


def lane_groups():
    out = {}
    for f in glob.glob(str(R / "bq17/pools/groups_n16_s*.jsonl")):
        for line in open(f):
            r = json.loads(line)
            out[r["instance_id"]] = {l["lane"]: l["group"] for l in r["lanes"] if l["lane"] in (0, 1, 2, 3)}
    return out


def metrics(ev, fix, judges):
    lg = lane_groups()
    tot = {"pass@1": 0.0, "majority": 0.0, "pass@4": 0.0, **{j: 0.0 for j in judges}}
    for k, e in ev["pools"].items():
        iid = e["iid"]
        groups = [list(g) for g in e["groups"]]
        if iid in fix:
            right_lanes = fix[iid]
            for a in range(len(groups)):
                lanes = [l for l, g in lg[iid].items() if g == a]
                if lanes:
                    groups[a][1] = int(any(l in right_lanes for l in lanes))
        alive = [a for a, g in enumerate(groups) if g[0] > 0]
        n4 = sum(groups[a][0] for a in alive)
        tot["pass@1"] += sum(groups[a][0] * groups[a][1] for a in alive) / n4
        tot["pass@4"] += float(any(groups[a][1] for a in alive))
        top = max(groups[a][0] for a in alive)
        tied = [a for a in alive if groups[a][0] == top]
        tot["majority"] += sum(groups[a][1] for a in tied) / len(tied)
        for j, s in judges.items():
            if len(alive) == 1 or all(groups[a][1] for a in alive) or not any(groups[a][1] for a in alive):
                tot[j] += float(groups[alive[0]][1]) if len(alive) == 1 else float(all(groups[a][1] for a in alive))
            else:
                tot[j] += pool_scores([tuple(g) for g in groups], s.get(k, {}))[0]
    return tot


def main():
    ev = json.loads((R / "bq17/bq17_evalset.json").read_text())
    lg = lane_groups()
    for iid, want in EXPECT_NOW.items():  # check that the lanes passing now match the audit's reading
        k = f"bq:{iid}"
        g = ev["pools"][k]["groups"]
        now = {l for l, a in lg[iid].items() if g[a][1]}
        if now != want:
            print(f"note: {iid} lanes passing now {sorted(now)} vs audit {sorted(want)}")
    judges = {}
    for name, paths in (("35B judge", [R / "bq17/judges/35B_dc.jsonl", I / "judges/dev/rerun_dc.jsonl"]),
                        ("27B judge", [R / "bq17/judges/27b_dc.jsonl"])):
        judges[name] = load_samples([str(p) for p in paths])[0]
    rows = {"official labels": metrics(ev, {}, judges), "strict corrections": metrics(ev, STRICT, judges),
            "lenient corrections": metrics(ev, LENIENT, judges)}
    cols = ["pass@1", "majority", "35B judge", "27B judge", "pass@4"]
    print(f"{'':22s}" + "".join(f"{c:>16s}" for c in cols))
    for name, t in rows.items():
        print(f"{name:22s}" + "".join(f"{t[c]:7.1f} ({t[c] / 204:5.1%})" for c in cols))


if __name__ == "__main__":
    main()
