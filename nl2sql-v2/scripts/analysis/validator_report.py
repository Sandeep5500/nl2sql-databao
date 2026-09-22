#!/usr/bin/env python3
"""Score a validator run from its published traces. Backs Section 5.1.

Reads logs/traces/validator_<tag>/ and validator_inputs.json, which carries the
recorded correctness of every candidate, so nothing is re-executed and the
result CSVs (gitignored) are not needed.

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/validator_report.py --tags 9b,27b
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from _common import TRACES_DIR

HERE = Path(__file__).resolve()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", default="9b,27b")
    args = ap.parse_args()
    data = json.loads((HERE.parents[2] / "validator_inputs.json").read_text())
    picks = {}

    for tag in args.tags.split(","):
        d = TRACES_DIR / f"validator_{tag}"
        if not d.is_dir():
            raise SystemExit(f"no traces at {d}")
        rows, pos, longest = [], Counter(), 0
        for f in sorted(d.glob("local*.json")):
            t = json.loads(f.read_text())
            item = data[t["instance_id"]]
            chosen = next(c for c in item["candidates"] if c["label"] == t["picked"])
            rows.append((t["instance_id"], bool(chosen["correct"]),
                         sum(c["correct"] for c in item["candidates"]), len(item["candidates"])))
            pos[t["picked"]] += 1
            if len(chosen["sql"]) == max(len(c["sql"]) for c in item["candidates"]):
                longest += 1
        picks[tag] = {i: p for i, p, _, _ in
                      [(r[0], json.loads((d / f"{r[0]}.json").read_text())["picked"], 0, 0) for r in rows]}
        n = len(rows)
        sel = sum(1 for _, ok, _, _ in rows if ok)
        ceiling = sum(1 for _, _, k, _ in rows if k)
        rand = sum(k / m for _, _, k, m in rows)
        dec = [r for r in rows if 0 < r[2] < r[3]]
        print(f"\n=== validator {tag} ({n} questions) ===")
        print(f"  picked correct {sel}/{n} ({sel/n:.1%})   random {rand:.1f}   ceiling {ceiling}"
              f"   headroom captured {(sel-rand)/(ceiling-rand):.0%}")
        print(f"  decidable ({len(dec)}): {sum(1 for r in dec if r[1])}/{len(dec)}")
        print(f"  {'candidates correct':20s} {'questions':>9s} {'picked':>7s} {'random':>7s}")
        for k in sorted({r[2] for r in rows}):
            g = [r for r in rows if r[2] == k]
            print(f"  {k} of {g[0][3]:<17d} {len(g):9d} {sum(1 for r in g if r[1]):7d} {k/g[0][3]*len(g):7.1f}")
        print(f"  longest SQL picked {longest}/{n} ({longest/n:.0%}, chance ~{100//rows[0][3]}%)"
              f"   positions {dict(sorted(pos.items()))}")

    tags = list(picks)
    if len(tags) == 2:
        a, b = picks[tags[0]], picks[tags[1]]
        same = sum(1 for i in a if a.get(i) == b.get(i))
        print(f"\n{tags[0]} and {tags[1]} picked the same candidate on {same}/{len(a)} questions")


if __name__ == "__main__":
    main()
