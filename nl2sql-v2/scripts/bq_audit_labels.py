"""Corrected labels for all 204 bq17 questions (Nov 19 full audit): the auditors' verdicts (verdicts.json), their
strict changes as checked by a second auditor (second_check.json: confirm, adjust or refute; VERIFY.md), and the
13 questions audited on Nov 18 (bq_corrected_labels.py). Checks every verdict against the official labels and the
protocol, then writes corrected_labels_full.json with three views of the questions whose right lanes change:
  strict           clear gold errors and scoring defects, as verified
  strict_no_drift  strict without live-table drift and our harness's 5,000-row cap (those keep the official labels)
  lenient          strict plus lanes right under another fair reading

Verdicts, second checks, protocols and the output are in nl2sql-v2/research_notes/Spider2 Lite BigQuery full label
audit/; the official labels come from results/bq17/ (not tracked).
usage (from nl2sql-v2/): python3 scripts/bq_audit_labels.py
"""
import glob
import json
from collections import Counter
from pathlib import Path

from bq_corrected_labels import EXPECT_NOW, LENIENT as NOV18_LENIENT, STRICT as NOV18_STRICT

R = Path(__file__).resolve().parents[2] / "results"
NOTES = Path(__file__).resolve().parents[1] / "research_notes/Spider2 Lite BigQuery full label audit"
NOV18 = set(EXPECT_NOW)  # the 13 questions audited on Nov 18; not re-audited

VERDICTS = {"gold_right", "gold_wrong", "two_readings", "scoring_defect", "unclear"}
DRIFT = {"bq022", "bq034", "bq169", "bq362", "bq363"}  # the public table changed after the gold was made
HARNESS = {"bq067"}                                     # our harness keeps at most 5,000 result rows


def official():
    """Per question: the stratum and the lanes the official scorer counts right (as in the audit packets)."""
    ev = json.loads((R / "bq17/bq17_evalset.json").read_text())["pools"]
    meta = {e["iid"]: {"stratum": e["stratum"]} for e in ev.values()}
    for f in glob.glob(str(R / "bq17/pools/groups_n16_s*.jsonl")):
        for line in open(f):
            it = json.loads(line)
            if it["instance_id"] in meta:
                meta[it["instance_id"]]["right"] = sorted(
                    l["lane"] for l in it["lanes"] if l["lane"] in (0, 1, 2, 3) and l["group"] is not None
                    and it["groups"][l["group"]]["correct"])
    return meta


def load(name):
    out, dup = {}, []
    for v in json.loads((NOTES / name).read_text()):
        if v.get("iid") in out:
            dup.append(v.get("iid"))
        out[v.get("iid")] = v
    return out, dup


def main():
    meta = official()
    want = set(meta) - NOV18
    got, dup = load("verdicts.json")
    ver, vdup = load("second_check.json")
    problems = [f"{i}: two verdicts" for i in dup] + [f"{i}: two verifications" for i in vdup]
    for iid, v in got.items():
        off = sorted(meta[iid]["right"]) if iid in meta else None
        s, l = sorted(set(v.get("strict_right_lanes", []))), sorted(set(v.get("lenient_right_lanes", [])))
        if v.get("verdict") not in VERDICTS:
            problems.append(f"{iid}: unknown verdict {v.get('verdict')!r}")
        if sorted(v.get("official_right_lanes", [])) != off:
            problems.append(f"{iid}: official lanes given {v.get('official_right_lanes')} but scorer has {off}")
        if not set(s) <= {0, 1, 2, 3} or not set(l) <= {0, 1, 2, 3}:
            problems.append(f"{iid}: lanes outside 0-3")
        if not set(s) <= set(l):
            problems.append(f"{iid}: strict {s} not inside lenient {l}")
        if v.get("verdict") in ("gold_right", "unclear") and (s != off or l != off):
            problems.append(f"{iid}: {v['verdict']} but labels change ({off} -> {s} / {l})")
        if v.get("verdict") == "two_readings" and s != off:
            problems.append(f"{iid}: two_readings but strict changes ({off} -> {s})")
        if v.get("verdict") in ("gold_wrong", "scoring_defect") and v.get("confidence") == "low":
            problems.append(f"{iid}: {v['verdict']} with low confidence")
    missing = sorted(want - set(got))
    print(f"verdicts: {len(got)} of {len(want)} questions; missing {len(missing)}" + (f": {missing}" if missing else ""))
    strict, lenient, decisions, unverified = dict(NOV18_STRICT), dict(NOV18_LENIENT), Counter(), []
    for iid, v in got.items():
        off = sorted(meta[iid]["right"])
        s, l = sorted(set(v["strict_right_lanes"])), sorted(set(v["lenient_right_lanes"]))
        if s != off:
            w = ver.get(iid)
            if not w:
                unverified.append(iid)
            else:
                d = w.get("decision")
                decisions[d] += 1
                if d == "adjust":
                    s = sorted(set(w["strict_right_lanes"]))
                    l = sorted(set(l) | set(s)) if w.get("lenient_ok") else s
                elif d == "refute":
                    l = l if w.get("lenient_ok") else off
                    s = off
                elif d != "confirm":
                    problems.append(f"{iid}: unknown verification decision {d!r}")
        if s != off:
            strict[iid] = set(s)
        if l != off:
            lenient[iid] = set(l)
    for p in problems:
        print("  CHECK", p)
    if unverified:
        print(f"  strict changes without a verification (applied as given): {sorted(unverified)}")
    for iid in strict:
        lenient.setdefault(iid, strict[iid])
    no_drift = {k: v for k, v in strict.items() if k not in DRIFT | HARNESS}
    out = {"strict": {k: sorted(v) for k, v in sorted(strict.items())},
           "strict_no_drift": {k: sorted(v) for k, v in sorted(no_drift.items())},
           "lenient": {k: sorted(v) for k, v in sorted(lenient.items())}}
    (NOTES / "corrected_labels_full.json").write_text(json.dumps(out, indent=1))
    print("\nverdicts (new audit):", dict(Counter(v["verdict"] for v in got.values())))
    print("confidence:", dict(Counter(v.get("confidence") for v in got.values())))
    print("verification of strict changes:", dict(decisions))
    for view, d in (("strict", strict), ("strict_no_drift", no_drift), ("lenient", lenient)):
        up = down = 0
        for iid, lanes in d.items():
            o = set(meta[iid]["right"])
            up += len(lanes - o)
            down += len(o - lanes)
        print(f"{view}: {len(d)} questions change; lanes gained {up}, lanes lost {down}")
    print("\nchanged questions (official -> strict / lenient):")
    for iid in sorted(set(strict) | set(lenient)):
        off = sorted(meta[iid]["right"])
        src = "Nov 18" if iid in NOV18_STRICT or iid in NOV18_LENIENT else got[iid]["verdict"]
        tag = " drift" if iid in DRIFT else " harness" if iid in HARNESS else ""
        vd = ver.get(iid, {}).get("decision", "")
        print(f"  {iid:6s} {meta[iid]['stratum']:11s} {off} -> {sorted(strict.get(iid, off))} / "
              f"{sorted(lenient.get(iid, off))}  [{src}{tag}{', ' + vd if vd else ''}]")


if __name__ == "__main__":
    main()
