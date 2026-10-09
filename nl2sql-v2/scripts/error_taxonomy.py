#!/usr/bin/env python3
"""What actually goes wrong, across every lane, in one table.

    uv run python scripts/error_taxonomy.py \
        bq_v2:../logs/traces/bq_v2:../results/bq_v2_run.csv \
        bq_v3:../logs/traces/bq_v3:../results/bq_v3_run.csv

Two things this does that the per-lane analyzer does not.

It counts the LAST failure state of each wrong episode, so every wrong answer lands in
exactly one bucket and the buckets sum to the loss. The per-lane analyzer counts
instances affected per error class, where one episode can appear in six rows -- useful
for "what did the warehouse complain about", useless for "where did the accuracy go".

And it separates failures the harness caused from failures the model made. That
distinction drove every fix that worked: 149 truncated prompts, 63 episodes offered a
dead tool and 12 misread 403s were ours, and fixing them was worth +7.4 points, while
the model's own wrong answers were untouched by any of it.
"""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

# Ordered: the first pattern that matches a wrong episode's evidence wins, most
# specific and most harness-attributable first. HARNESS entries are our bugs or our
# limits; MODEL entries are the model's own reasoning.
BUCKETS = [
    ("harness", "prompt truncated (names lost)",
     r"\[schema dump truncated\]|overview truncated"),
    ("harness", "dead tool offered (find_value)",
     r"find_value is disabled"),
    ("harness", "misread 403 (out-of-database table)",
     r"Forbidden"),
    ("harness", "bare-dataset INFORMATION_SCHEMA",
     r"has no project in front of it|asks for PROJECT-level|Not found: Dataset"),
    ("harness", "scan budget / cap refused the query",
     r"BudgetExhausted|budget exhausted|would scan .* over the"),
    ("harness", "query cancelled for time",
     r"TimeoutError|was cancelled"),
    ("model", "wrong table or column name",
     r"Unrecognized name|Not found: Table|Name .* not found"),
    ("model", "unknown function",
     r"Function not found"),
    ("model", "type mismatch",
     r"No matching signature|Cannot coerce|cannot be cast"),
    ("model", "nested/UNNEST misuse",
     r"Cannot access field|values referenced in UNNEST"),
    ("model", "aggregation or GROUP BY",
     r"must be grouped or aggregated"),
    ("model", "SQL syntax", r"Syntax error"),
]


def lane_rows(run_csv):
    with open(run_csv, newline="", encoding="utf-8") as f:
        return {r["instance_id"]: r for r in csv.DictReader(f)}


def classify(run, traces):
    """wrong episode -> (origin, label). One bucket each, so they sum to the loss."""
    out = {}
    for iid, r in run.items():
        if r.get("score") == "1":
            continue
        t = traces.get(iid)
        status = (r.get("status") or "").strip()
        if t is None:
            out[iid] = ("unknown", "no trace")
            continue
        errs = "\n".join(str(e.get("result") or "")
                         for e in t.get("trace", [])
                         if str(e.get("result") or "").startswith("ERROR"))
        blob = str(t.get("system") or "") + "\n" + errs
        hit = next(((o, l) for o, l, p in BUCKETS
                    if re.search(p, blob, re.IGNORECASE)), None)
        # An episode that submitted an answer and was simply wrong has no error to
        # classify: that is the irreducible bucket, and conflating it with the
        # error-shaped failures is how a harness bug hides.
        if status == "no_sql":
            out[iid] = hit or ("harness", "never produced SQL")
        elif status == "fallback":
            out[iid] = ("harness", "ran out of steps, submitted exploratory SQL")
        elif hit and hit[0] == "harness":
            out[iid] = hit
        else:
            out[iid] = ("model", "answered, wrong result")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lanes", nargs="+", metavar="NAME:TRACES:RUNCSV")
    args = ap.parse_args()

    lanes, classes = [], {}
    for spec in args.lanes:
        name, tdir, rcsv = spec.split(":", 2)
        run = lane_rows(rcsv)
        traces = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                  for p in Path(tdir).glob("*.json")}
        lanes.append((name, run))
        classes[name] = classify(run, traces)

    labels, seen = [], set()
    for _o, l, _p in BUCKETS:
        labels.append(l)
        seen.add(l)
    for extra in ("never produced SQL",
                  "ran out of steps, submitted exploratory SQL",
                  "answered, wrong result", "no trace"):
        if extra not in seen:
            labels.append(extra)
    origin = {l: o for o, l, _p in BUCKETS}
    origin.update({"never produced SQL": "harness",
                   "ran out of steps, submitted exploratory SQL": "harness",
                   "answered, wrong result": "model", "no trace": "unknown"})

    w = max(len(l) for l in labels) + 2
    head = f"  {'':{w}}" + "".join(f"{n:>10s}" for n, _ in lanes)
    print("\nwrong episodes by cause (each episode counted once)")
    print("-" * len(head))
    print(head)
    for grp in ("harness", "model", "unknown"):
        rows = [l for l in labels if origin[l] == grp
                and any(Counter(c.values())[(grp, l)] for c in classes.values())]
        if not rows:
            continue
        print(f"  {grp.upper()}")
        for l in rows:
            cells = "".join(f"{Counter(c.values())[(grp, l)]:>10d}"
                            for _n, c in [(n, classes[n]) for n, _ in lanes])
            print(f"    {l:{w - 2}}" + cells)
        tot = "".join(f"{sum(v for k, v in Counter(classes[n].values()).items() if k[0] == grp):>10d}"
                      for n, _ in lanes)
        print(f"    {'subtotal':{w - 2}}" + tot)
    print(f"  {'TOTAL WRONG':{w}}" + "".join(
        f"{len(classes[n]):>10d}" for n, _ in lanes))
    print(f"  {'correct':{w}}" + "".join(
        f"{sum(1 for r in run.values() if r.get('score') == '1'):>10d}"
        for _n, run in lanes))
    print(f"  {'n':{w}}" + "".join(f"{len(run):>10d}" for _n, run in lanes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
