#!/usr/bin/env python3
"""How many questions have a complete, trustworthy package — question,
verified SQL, and the tables/columns parsed from it — and how many of those
are usable for an ablation. Backs Section 6 of
documents/retrieval_vs_generation_findings.md.

Official gold SQL counts only if it passes on every repeated execution, since
some are nondeterministic. A package is kept only if its SQL scores correct, parses to real tables, has
an answer larger than a single number, and touches the table the value sweep
independently found (where the sweep has one). Official gold SQL is preferred
when it is valid.

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/linkage_funnel.py
"""

import json
from pathlib import Path

from collections import Counter

from _common import (GOLD_SQL_DIR, PHASE0_RUNS, SQLITE_DIR, Database, buckets,
                     chance_null, gold_shape, linkage, load_eval_standards,
                     load_traces, local_questions, passes_reliably, rescore,
                     schema_of)

SWEEP = Path(__file__).resolve().parents[2] / "sweep_context.json"


def main():
    qdb = {k: v["db"] for k, v in local_questions().items()}
    std = load_eval_standards()
    traces = load_traces(PHASE0_RUNS)
    ok = rescore(traces, qdb)
    b = buckets(qdb)
    sweep = json.loads(SWEEP.read_text()) if SWEEP.exists() else {}

    packages = {}
    schemas = {}
    for iid, db_name in qdb.items():
        p = SQLITE_DIR / f"{db_name}.sqlite"
        if not p.exists():
            continue
        if db_name not in schemas:
            db = Database(p)
            schemas[db_name] = schema_of(db)
            db.close()
        real = schemas[db_name]
        cands = []
        gold = GOLD_SQL_DIR / f"{iid}.sql"
        if gold.exists():
            sql = gold.read_text().strip().rstrip(";")
            if passes_reliably(p, sql, iid, std):
                cands.append(("official", sql))
        cands += [(spec, traces[spec][iid]["sql"]) for spec in PHASE0_RUNS
                  if iid in traces[spec] and ok[(spec, iid)]]
        for src, sql in cands:
            link = linkage(sql, real)
            if link:
                packages[iid] = (src, link)
                break

    swept = {i: {t.lower() for t in v["tables"]} for i, v in sweep.items()}
    no_scalar = {i for i in packages if gold_shape(i) != (1, 1)}
    strict = {i for i in no_scalar
              if i not in swept or swept[i] & set(packages[i][1][0])}
    usable = strict & (b["B"] | b["C"])

    print(f"verified, parseable SQL held             : {len(packages)}")
    print(f"   from the official answer key          : "
          f"{sum(1 for s, _ in packages.values() if s == 'official')}")
    print(f"   from our own runs                     : "
          f"{sum(1 for s, _ in packages.values() if s != 'official')}")
    print(f"after dropping 1x1 scalar answers        : {len(no_scalar)}")
    print(f"after requiring the swept table          : {len(strict)}")
    print(f"   in bucket A (useless for ablation)    : {len(strict & b['A'])}")
    print(f"   in bucket B                           : {len(strict & b['B'])}")
    print(f"   in bucket C                           : {len(strict & b['C'])}")
    print(f"usable for the ablation (B + C)          : {len(usable)}")

    ub = strict & b["B"]
    rates = Counter(round(b["lane_rate"][i], 2) for i in ub)
    print(f"\nusable bucket-B per-lane pass rates: {dict(sorted(rates.items()))}")
    exp, bar = chance_null(b["lane_rate"], ub)
    print(f"\nusable bucket-B packages: a blind redraw wins {exp:.1f} of {len(ub)}; "
          f"an oracle arm must clear {bar:.1f}")


if __name__ == "__main__":
    main()
