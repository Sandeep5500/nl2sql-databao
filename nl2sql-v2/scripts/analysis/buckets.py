#!/usr/bin/env python3
"""Split the local questions into buckets by which Phase-0 run solved them,
and report bucket B's chance-level null. Backs Section 4 of
documents/retrieval_vs_generation_findings.md.

  A  greedy already solves it                  -> useless for an ablation
  B  greedy fails, a sampled lane solved it    -> noisy: solvable by luck
  C  no run has ever solved it                 -> the clean test

Writes logs/analysis/buckets.json so ablation results can be split by bucket.

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/buckets.py
"""

import json
from collections import Counter

from _common import ANALYSIS_DIR, buckets, chance_null, local_questions


def main():
    qdb = {k: v["db"] for k, v in local_questions().items()}
    b = buckets(qdb)
    print(f"local questions: {len(qdb)}\n")
    for k, label in (("A", "greedy already solves"),
                     ("B", "greedy fails, a sampled lane solved"),
                     ("C", "no run has ever solved")):
        print(f"  {k}  {label:36s} {len(b[k]):3d}")

    rates = Counter(round(b["lane_rate"][i], 2) for i in b["B"])
    exp, bar = chance_null(b["lane_rate"], b["B"])
    print(f"\nbucket B per-lane pass rate (fraction of the 4 sampled lanes that win):")
    print("  ", dict(sorted(rates.items())))
    print(f"  a blind redraw with no help wins {exp:.1f} of {len(b['B'])}; "
          f"an intervention must clear {bar:.1f} (2 sigma)")

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    out = ANALYSIS_DIR / "buckets.json"
    out.write_text(json.dumps({k: sorted(b[k]) for k in "ABC"}, indent=1))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
