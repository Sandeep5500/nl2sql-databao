#!/usr/bin/env python3
"""Retrieval vs generation, measured within question. The headline analysis;
backs Section 1 of documents/retrieval_vs_generation_findings.md.

For every question the SAME model both solved and failed across the runs,
compare each failing query to the winning one. Same model, same question, same
prompt, different sample: no prompt confound, no question-selection bias.

  never found a needed table     true retrieval failure
  found it, but left it out      generation (checked against the whole trace,
                                  not just the final SQL)
  right table, wrong column      column linking
  right tables and columns       generation

Three artifacts are removed, each of which moved a headline number:
  - fallback episodes (hit the step cap, submitted an exploratory query)
  - SQL aliases that sqlglot reports as columns (`cnt`, `total_income`)
  - tables found during the episode but omitted from the final SQL

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/paired_failures.py
    uv run python scripts/analysis/paired_failures.py --examples 2
    uv run python scripts/analysis/paired_failures.py --runs 'v2_armAplus,arm_contract_*'
"""

import argparse
import json
import re
import textwrap
from collections import defaultdict

from _common import (PHASE0_RUNS, SQLITE_DIR, Database, linkage,
                     load_traces, local_questions, rescore, schema_of)

KINDS = [("retrieval", "never found a table the answer needs"),
         ("linking", "right tables, wrong column"),
         ("generation", "right tables and columns, wrong logic")]


def touched(trace: dict, table: str) -> bool:
    """Did this table appear in any tool call or tool result in the episode?"""
    pat = re.compile(rf"\b{re.escape(table)}\b", re.I)
    for e in trace.get("trace", []):
        if "tool" in e and (pat.search(json.dumps(e.get("args", "")))
                            or pat.search(str(e.get("result", "")))):
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=",".join(PHASE0_RUNS),
                    help="comma-separated run specs (dir names or globs under logs/traces)")
    ap.add_argument("--examples", type=int, default=0,
                    help="print this many examples per failure kind")
    args = ap.parse_args()

    Q = local_questions()
    qdb = {k: v["db"] for k, v in Q.items()}
    traces = load_traces(args.runs.split(","))
    ok = rescore(traces, qdb)

    # per (question, run): outcome, linkage, trace
    rec = defaultdict(dict)
    by_db = defaultdict(set)
    for spec, by_iid in traces.items():
        for iid in by_iid:
            by_db[qdb[iid]].add(iid)
    real_schema = {}
    for db_name in by_db:
        p = SQLITE_DIR / f"{db_name}.sqlite"
        if p.exists():
            db = Database(p)
            real_schema[db_name] = schema_of(db)
            db.close()

    for spec, by_iid in traces.items():
        for iid, t in by_iid.items():
            real = real_schema.get(qdb[iid])
            if real is None:
                continue
            rec[iid][spec] = {"ok": ok[(spec, iid)], "status": t.get("status"),
                              "link": linkage(t["sql"], real), "trace": t, "sql": t["sql"]}

    raw_pairs = fallback = unparsed = 0
    both_q = set()
    pairs = []
    for iid, runs in rec.items():
        winners = {s: r for s, r in runs.items() if r["ok"]}
        losers = {s: r for s, r in runs.items() if not r["ok"]}
        if not winners or not losers:
            continue
        both_q.add(iid)
        raw_pairs += len(losers)
        wl = [r["link"] for r in winners.values() if r["link"]]
        if not wl:
            unparsed += len(losers)
            continue
        wt = set.intersection(*[set(t) for t, _ in wl]) or set(wl[0][0])
        wc = set.intersection(*[set(c) for _, c in wl])
        win_sql = min((r["sql"] for r in winners.values()), key=len)
        for spec, r in losers.items():
            if r["status"] == "fallback":
                fallback += 1
                continue
            if not r["link"]:
                unparsed += 1
                continue
            lt, lc = r["link"]
            missing = wt - lt
            if missing and not all(touched(r["trace"], m) for m in missing):
                kind = "retrieval"
            elif missing or not (wc - lc):
                kind = "generation"      # found-but-omitted counts here
            else:
                kind = "linking"
            pairs.append({"iid": iid, "kind": kind, "found_unused": bool(missing),
                          "wt": wt, "lt": lt, "wc": wc, "lc": lc,
                          "win": win_sql, "lose": r["sql"]})

    n = len(pairs)
    print(f"questions with both a winning and a failing run : {len(both_q)}")
    print(f"raw (question, failing run) pairs               : {raw_pairs}")
    print(f"  removed, fallback (unfinished episode)        : {fallback}")
    print(f"  removed, query touches no real table          : {unparsed}")
    print(f"clean pairs                                     : {n}\n")
    for key, label in KINDS:
        k = sum(1 for p in pairs if p["kind"] == key)
        print(f"  {label:42s} {k:4d}  ({100 * k / n:3.0f}%)")
    fu = sum(1 for p in pairs if p["found_unused"] and p["kind"] == "generation")
    print(f"\n  of the generation pairs, {fu} had a table the final SQL omitted but the "
          f"episode had already found")

    for key, label in KINDS:
        ex = sorted((p for p in pairs if p["kind"] == key),
                    key=lambda p: len(p["win"]) + len(p["lose"]))[: args.examples]
        for p in ex:
            print(f"\n{'=' * 78}\n{label.upper()} — {p['iid']} ({qdb[p['iid']]})\n{'=' * 78}")
            print("Q: " + textwrap.fill(Q[p["iid"]]["question"][:380], 88, subsequent_indent="   "))
            print(f"   winner tables {sorted(p['wt'])}   loser tables {sorted(p['lt'])}")
            if p["wc"] - p["lc"]:
                print(f"   columns the loser missed: {sorted(p['wc'] - p['lc'])}")
            print("\n   CORRECT:\n" + textwrap.indent(p["win"].strip()[:700], "     "))
            print("\n   FAILED:\n" + textwrap.indent(p["lose"].strip()[:700], "     "))


if __name__ == "__main__":
    main()
