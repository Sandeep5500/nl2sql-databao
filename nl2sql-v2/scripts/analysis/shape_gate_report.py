"""Did the submit-time shape gate do anything? Mechanism first, score second.

A single lane cannot settle the headline score: the four q36s lanes spanned
55-71 of 135, so one run landing anywhere in that band proves nothing. What one
run CAN settle is whether the mechanism fires and whether the model recovers
when it does, and that is measured per event, not per run.

Reports, from the traces alone:
  how often the gate refused a submission, and on what grounds
  what the episode did next: fixed the shape and submitted, submitted unchanged
      with confirm_shape, or died at the step cap
  whether refused episodes end up scoring better or worse than the control's
      same questions

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/shape_gate_report.py --run shape_k1
    uv run python scripts/analysis/shape_gate_report.py --run shape_k1 --control q36s_pass4_k1
"""

import argparse
import glob
import json
from collections import Counter

from _common import TRACES_DIR


def load(spec):
    out = {}
    for d in sorted(glob.glob(str(TRACES_DIR / spec))):
        for f in sorted(glob.glob(d + "/local*.json")):
            t = json.load(open(f))
            if isinstance(t, dict) and "trace" in t:
                out[t["instance_id"]] = t
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--control")
    ap.add_argument("--examples", type=int, default=3)
    args = ap.parse_args()

    runs = load(args.run)
    if not runs:
        raise SystemExit(f"no traces under {TRACES_DIR / args.run}")
    refused = {i: [e for e in t["trace"] if "shape_refusal" in e]
               for i, t in runs.items()}
    refused = {i: v for i, v in refused.items() if v}

    n = len(runs)
    solved = sum(1 for t in runs.values() if t.get("score") == 1)
    cap = sum(1 for t in runs.values() if t.get("status") == "fallback")
    print(f"{args.run}: {n} episodes, {solved} correct, {cap} hit the step cap\n")
    print(f"gate fired on {len(refused)}/{n} episodes "
          f"({sum(len(v) for v in refused.values())} refusals total)")
    if not refused:
        print("  -> the gate never fired: on this run the change is inert.")
        return

    grounds = Counter()
    for v in refused.values():
        for e in v:
            for line in e["shape_refusal"].splitlines():
                line = line.strip()
                if line.startswith("- "):
                    key = ("row count" if "row(s)" in line else
                           "too few columns" if "column(s)" in line else
                           "proportion vs percentage" if "percentage" in line else "other")
                    grounds[key] += 1
    print("  grounds:", dict(grounds))

    after = Counter()
    for i, v in refused.items():
        t = runs[i]
        last = max(e["step"] for e in v)
        resubmitted = any(e.get("step", -1) > last and "tool" in e
                          and e["tool"] == "run_sql_query" for e in t["trace"])
        if t.get("status") == "fallback":
            after["died at the step cap"] += 1
        elif resubmitted:
            after["ran another query, then submitted"] += 1
        else:
            after["submitted without a new query"] += 1
    print("  what happened next:", dict(after))
    print(f"  of the {len(refused)} refused episodes, {sum(1 for i in refused if runs[i].get('score')==1)} ended correct")

    if args.control:
        ctrl = load(args.control)
        both = [i for i in refused if i in ctrl]
        gain = [i for i in both if runs[i].get("score") == 1 and ctrl[i].get("score") != 1]
        loss = [i for i in both if runs[i].get("score") != 1 and ctrl[i].get("score") == 1]
        print(f"\nagainst {args.control}, on the {len(both)} questions the gate fired on:")
        print(f"  fixed {len(gain)}: {', '.join(sorted(gain)) or '-'}")
        print(f"  broke {len(loss)}: {', '.join(sorted(loss)) or '-'}")
        cs = sum(1 for t in ctrl.values() if t.get("score") == 1)
        print(f"  whole-run score {solved}/{n} vs control {cs}/{len(ctrl)} "
              f"(NB: one lane; the q36s lanes spanned 55-71, so read the per-event "
              f"numbers above, not this line)")

    for i in list(refused)[:args.examples]:
        print(f"\n--- {i} ({'correct' if runs[i].get('score')==1 else 'failed'}, "
              f"{runs[i].get('status')})")
        print("   ", refused[i][0]["shape_refusal"].splitlines()[1].strip())


if __name__ == "__main__":
    main()
