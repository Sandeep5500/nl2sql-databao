#!/usr/bin/env python3
"""How loose is the scorer? Counts the grading relaxations that apply to each
local question, and the answer shapes that make a lucky match likely. Backs
Section 3 of documents/retrieval_vs_generation_findings.md.

Needs no model and no stored runs: reads only the gold CSVs and grading rules.

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/scorer_audit.py
"""

import json

import pandas as pd

from _common import EVAL_JSONL, gold_files, gold_shape, local_questions


def main():
    qdb = local_questions()
    rules = {json.loads(l)["instance_id"]: json.loads(l) for l in open(EVAL_JSONL)}
    n = len(qdb)
    shapes = {i: gold_shape(i) for i in qdb}

    print(f"local questions: {n}\n")
    print("grading relaxations")
    print(f"  row order ignored (columns sorted independently) : "
          f"{sum(1 for i in qdb if rules.get(i, {}).get('ignore_order'))}")
    print(f"  only some gold columns graded (condition_cols)   : "
          f"{sum(1 for i in qdb if rules.get(i, {}).get('condition_cols'))}")
    print(f"  several gold answers accepted                    : "
          f"{sum(1 for i in qdb if len(gold_files(i)) > 1)}")

    print("\nanswer shapes (smallest accepted variant)")
    print(f"  1x1 pure scalar                    : {sum(1 for s in shapes.values() if s == (1, 1))}")
    print(f"  <=2 rows and <=2 columns           : "
          f"{sum(1 for r, c in shapes.values() if r <= 2 and c <= 2)}")
    print(f"  >=5 rows and >=2 columns (robust)  : "
          f"{sum(1 for r, c in shapes.values() if r >= 5 and c >= 2)}")

    literal = 0
    for i in qdb:
        fs = gold_files(i)
        if not fs:
            continue
        d = pd.read_csv(fs[0])
        if any(d[c].dtype == object and d[c].dropna().map(
                lambda v: isinstance(v, str)
                and not v.replace(".", "", 1).replace("-", "", 1).isdigit()).any()
               for c in d.columns):
            literal += 1
    print(f"\nanswers with a text column a value sweep could trace : {literal}")
    print(f"answers that are purely numeric                       : {n - literal}")


if __name__ == "__main__":
    main()
