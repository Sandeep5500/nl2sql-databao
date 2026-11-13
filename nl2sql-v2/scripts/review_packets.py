#!/usr/bin/env python3
"""Packets for reviewing written items whose checks disagree: the blind solutions did not
reach the gold result (validate_trap_items.py), or one that did split from the gold on an
altered copy of the database (stress_test_items.py). A packet holds the question, the gold
and each disputed solution with the first rows of their results, so a reviewer with access
to the database can rule gold_right, gold_wrong or ambiguous (validate_trap_items.py
--reviews reads the verdicts).

Usage (NL2SQL_DATASET_DIR set):
    python scripts/review_packets.py --items a.jsonl --solutions s.jsonl \\
        --reports a.report.json --stress st.jsonl --output packets.jsonl
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql.config import SQLITE_DIR
from nl2sql.db import Database
from select_answer import result_preview


def rows_of(files: str):
    for f in (files or "").split(","):
        if f:
            yield from (json.loads(l) for l in open(f) if l.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--solutions", required=True)
    ap.add_argument("--reports", help="validate_trap_items.py reports (json lists)")
    ap.add_argument("--stress", help="stress_test_items.py outputs")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    items = {it["id"]: it for it in rows_of(args.items)}
    sols = defaultdict(list)
    for r in rows_of(args.solutions):
        sols[r["id"]].append(r["sql"])
    failed = set()
    for f in (args.reports or "").split(","):
        if f:
            failed |= {r["id"] for r in json.load(open(f))
                       if r["reason"] in ("blind_solve_failed", "no_solution")}
    split = {r["id"]: r for r in rows_of(args.stress) if r["status"] == "split"}
    n = 0
    with open(args.output, "w") as out:
        for iid in sorted(failed | set(split)):
            it = items.get(iid)
            if not it:
                continue
            db = Database(SQLITE_DIR / f"{it['db']}.sqlite")
            db.con.execute("SET disabled_optimizers='cte_inlining,common_subplan'")

            def preview(sql):
                try:
                    return result_preview(db.query_preview(sql, 1, 200, timeout_s=60)[0], rows=15)
                except Exception as e:
                    return f"(error: {' '.join(str(e).split())[:200]})"

            why = ("the blind solutions did not reach the gold result" if iid in failed else
                   "a blind solution matched the gold on the real data but returned a different "
                   "result on a copy of the database where "
                   + "; ".join(f"{c['table']}: {c['how']}" for c in split[iid]["copies"]
                               if c.get("split_solutions")))
            packet = {"id": iid, "db": it["db"], "kind": it["kind"], "question": it["question"],
                      "why_disputed": why, "gold_sql": it["gold_sql"],
                      "gold_result": preview(it["gold_sql"]),
                      "solutions": [{"sql": s, "result": preview(s)} for s in sols.get(iid, [])]}
            db.close()
            out.write(json.dumps(packet) + "\n")
            n += 1
    print(f"{n} packets -> {args.output}")


if __name__ == "__main__":
    main()
