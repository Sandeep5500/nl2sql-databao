#!/usr/bin/env python3
"""Offline evaluation of nl2sql.checks on the pass@4 validator pool (no model calls).

Reads validator_inputs.json (Julie's branch: question + 4 candidates with shape, preview,
error and the scorer's verdict) and optionally the 9B/27B validator traces, and reports:
  - how well the flags separate correct from wrong candidates
  - random-pick accuracy over all candidates vs over unflagged ones
  - how many of the validator's picks were flagged, and how often that pick was wrong

    python scripts/rule_checks_eval.py --inputs validator_inputs.json \
        [--picks 9b=../logs/traces/validator_9b 27b=../logs/traces/validator_27b]
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nl2sql.checks import check_candidate, parse_preview, prefilter


def truthy(v):
    return str(v).lower() in ("true", "1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--picks", nargs="*", default=[], help="tag=trace_dir with <iid>.json {picked}")
    args = ap.parse_args()
    data = json.loads(Path(args.inputs).read_text(encoding="utf-8"))

    tp = fp = fn = tn = 0          # "flagged" vs "wrong"
    by_flag = Counter()
    by_flag_wrong = Counter()
    rand_all = rand_kept = ceiling = 0.0
    for iid, item in data.items():
        q = item["question"]
        for c in item["candidates"]:
            err = c.get("error")
            err = None if err in (None, "None", "") else err
            cols, rows = parse_preview(c.get("preview") or "")
            shape = json.loads(c["shape"]) if isinstance(c.get("shape"), str) and c["shape"].startswith("[") else c.get("shape")
            n = shape[0] if shape else None
            c["flags"] = check_candidate(q, cols, rows, n, err)
            wrong = not truthy(c["correct"])
            flagged = bool(c["flags"])
            tp += flagged and wrong; fp += flagged and not wrong
            fn += (not flagged) and wrong; tn += (not flagged) and not wrong
            for f in c["flags"]:
                key = f.split(":")[0]
                by_flag[key] += 1
                by_flag_wrong[key] += wrong
        cands = item["candidates"]
        kept = prefilter(cands, q)
        rand_all += sum(truthy(c["correct"]) for c in cands) / len(cands)
        rand_kept += sum(truthy(c["correct"]) for c in kept) / len(kept)
        ceiling += any(truthy(c["correct"]) for c in cands)

    n = len(data)
    print(f"candidates: {tp + fp + fn + tn}   flagged: {tp + fp}   "
          f"of flagged, wrong: {tp}/{tp + fp} ({tp / max(tp + fp, 1):.0%})   "
          f"correct answers wrongly flagged: {fp}/{fp + tn} ({fp / max(fp + tn, 1):.1%})")
    print("per flag (count, share wrong):")
    for f, k in by_flag.most_common():
        print(f"   {f:28s} {k:4d}  {by_flag_wrong[f] / k:.0%} wrong")
    print(f"\nrandom pick, all candidates      : {rand_all:.1f}/{n}")
    print(f"random pick, unflagged candidates: {rand_kept:.1f}/{n}")
    print(f"perfect selection                : {ceiling:.0f}/{n}")

    for spec in args.picks:
        tag, d = spec.split("=", 1)
        picked_flagged = picked_flagged_wrong = rescuable = 0
        correct = 0
        for iid, item in data.items():
            p = Path(d) / f"{iid}.json"
            if not p.exists():
                continue
            lab = json.loads(p.read_text(encoding="utf-8"))["picked"]
            c = next(x for x in item["candidates"] if x["label"] == lab)
            correct += truthy(c["correct"])
            if c["flags"]:
                picked_flagged += 1
                if not truthy(c["correct"]):
                    picked_flagged_wrong += 1
                    rescuable += any(truthy(x["correct"]) and not x["flags"] for x in item["candidates"])
        print(f"\nvalidator {tag}: {correct}/{n} correct; its pick was flagged on {picked_flagged} "
              f"questions, wrong on {picked_flagged_wrong} of those; an unflagged correct "
              f"alternative existed on {rescuable}")


if __name__ == "__main__":
    main()
