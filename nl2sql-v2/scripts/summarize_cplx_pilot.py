#!/usr/bin/env python3
"""Do the complex-question pilot's pairs look like Spider2's? From sample_judge_verdicts.py
outputs (the pilot's, and optionally the BIRD-Platinum one for comparison, split by source):
questions with a right-vs-wrong pair, the shape of those pairs (SQL length, CTEs, joins, how the
two results differ: analyze_judge_gap.features) and the untuned judge's accuracy on them, beside
the same figures for Spider2's pairs (analyze_judge_gap.py --dump rows, side "spider2").

Usage (from nl2sql-v2/):
    python scripts/summarize_cplx_pilot.py --verdicts verdicts_cplx_v1.jsonl \\
        [--compare verdicts_train_v1.jsonl] --spider-features gap_v2a.jsonl
"""

import argparse
import json
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_judge_gap import features

NUM = ("sql_chars_max", "ctes_max", "joins_max", "q_chars")


def rows_of(path):
    """(questions per source: Counter of pool kinds, pair feature rows with the untuned accuracy)."""
    pools, rows = defaultdict(Counter), []
    for line in open(path):
        r = json.loads(line)
        src = r.get("source") or "?"
        right = [bool(g["correct"]) for g in r["groups"]]
        pools[src]["questions"] += 1
        pools[src]["with pair" if r["pairs"] else "all right" if all(right) else
                   "none right" if not any(right) else "right only as duplicates"] += 1
        for p in r["pairs"]:
            s = [x for x in p["samples"] if not x.get("error")]
            if not s:
                continue
            f = features(p["prompt"], p["correct_letter"])
            f.update(source=src, acc=sum(x["right"] for x in s) / len(s), split=r.get("split"))
            rows.append(f)
    return pools, rows


def describe(name, rows):
    if not rows:
        return f"{name:24s} no pairs"
    acc = st.mean(r["acc"] for r in rows)
    kinds = Counter("never" if r["acc"] == 0 else "always" if r["acc"] == 1 else "mixed" for r in rows)
    diff = Counter(r["diff"] for r in rows)
    return (f"{name:24s} pairs {len(rows):4d}  untuned {acc:5.1%}  "
            + "  ".join(f"{k} {st.median(r[k] for r in rows):.0f}" for k in NUM)
            + f"  never/mixed/always {kinds['never']}/{kinds['mixed']}/{kinds['always']}"
            + "  diff: " + ", ".join(f"{k} {v / len(rows):.0%}" for k, v in diff.most_common()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", required=True)
    ap.add_argument("--compare", help="another verdicts file, e.g. the BIRD-Platinum one")
    ap.add_argument("--spider-features", help="analyze_judge_gap.py --dump output")
    args = ap.parse_args()

    pools, rows = rows_of(args.verdicts)
    if args.compare:
        p2, r2 = rows_of(args.compare)
        for k, v in p2.items():
            pools.setdefault(k, v)
        rows += [r for r in r2 if r["source"] not in {x["source"] for x in rows}]
    for src, c in sorted(pools.items()):
        print(f"{src:14s} questions {c['questions']:5d}: with a right-vs-wrong pair {c['with pair']} "
              f"({c['with pair'] / c['questions']:.0%}), all right {c['all right']}, none right {c['none right']}")
    print("\nper ordered pair (medians; untuned = mean of the stored samples):")
    for src in sorted({r["source"] for r in rows}):
        print(describe(src, [r for r in rows if r["source"] == src]))
    if args.spider_features:
        sp = [json.loads(l) for l in open(args.spider_features)]
        sp = [dict(r, acc=r["base"]) for r in sp if r["side"] == "spider2"]
        print(describe("spider2 (2 untuned runs)", sp))


if __name__ == "__main__":
    main()
