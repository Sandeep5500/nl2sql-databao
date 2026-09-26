#!/usr/bin/env python3
"""The questions where retrieval really was the bottleneck, and where to read them.

Two analyses in documents/retrieval_vs_generation_findings.md flag retrieval, over
disjoint question sets, so this reports both:

  within-model (Section 1)  questions the 9B both solved and failed: a failing run
                            never encountered a table the winning run needed
  cross-model (Section 7.2) questions the 9B never solved: a failing run never
                            encountered a table the 27B teacher's verified query needed

"Never encountered" means the table name appears in no tool call and no tool result
anywhere in the episode, not merely that it is absent from the final SQL -- a table
can be found and then deliberately dropped, which is a generation failure wearing a
retrieval costume (see local019 in Section 1).

For each case this prints the missing table, the runs that missed it, the runs that
did not, and the path of every trace to read.

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/retrieval_cases.py
    uv run python scripts/analysis/retrieval_cases.py --sql      # also print the queries
"""

import argparse
import glob
import textwrap
from collections import defaultdict

from _common import (PHASE0_RUNS, SQLITE_DIR, TRACES_DIR, Database, buckets,
                     linkage, load_traces, local_questions, rescore, schema_of)
from ablation_arms import discover
from paired_failures import touched

TEACHER_RUNS = ["teacher_p1_*", "teacher_p1b_*"]


def trace_path(spec: str, iid: str) -> str:
    """The real file for a run spec, which may be a glob over shard directories."""
    hits = glob.glob(str(TRACES_DIR / spec / f"{iid}.json"))
    return hits[0] if hits else str(TRACES_DIR / spec / f"{iid}.json")


def collect(run_specs, qdb):
    """{iid: {run_spec: record}} for every episode in these runs."""
    traces = load_traces(run_specs)
    ok = rescore(traces, qdb)
    dbs = {qdb[iid] for by_iid in traces.values() for iid in by_iid}
    real_schema = {}
    for name in dbs:
        p = SQLITE_DIR / f"{name}.sqlite"
        if p.exists():
            db = Database(p)
            real_schema[name] = schema_of(db)
            db.close()
    rec = defaultdict(dict)
    for spec, by_iid in traces.items():
        for iid, t in by_iid.items():
            real = real_schema.get(qdb[iid])
            if real is None:
                continue
            rec[iid][spec] = {"ok": ok[(spec, iid)], "status": t.get("status"),
                              "link": linkage(t["sql"], real), "trace": t, "sql": t["sql"]}
    return rec


def find_cases(rec, keep=None, teacher=()):
    """Questions with at least one failing run that never encountered a needed table.

    `teacher` names run specs belonging to the larger model, so they can supply the
    correct query without landing in the 9B's own hit rate.
    """
    cases = []
    for iid, runs in sorted(rec.items()):
        if keep is not None and iid not in keep:
            continue
        winners = {s: r for s, r in runs.items() if r["ok"]}
        losers = {s: r for s, r in runs.items() if not r["ok"]}
        if not winners or not losers:
            continue
        wl = [r["link"] for r in winners.values() if r["link"]]
        if not wl:
            continue
        needed = set.intersection(*[set(t) for t, _ in wl]) or set(wl[0][0])
        missed, had, skipped = defaultdict(list), [], []
        for spec, r in sorted(losers.items()):
            if r["status"] == "fallback" or not r["link"]:
                skipped.append(spec)      # never finished; not evidence either way
                continue
            gone = [m for m in needed - set(r["link"][0]) if not touched(r["trace"], m)]
            if gone:
                for m in gone:
                    missed[m].append(spec)
            else:
                had.append(spec)
        if missed:
            # Per-run view over EVERY run, unfinished ones included: a run that hit the
            # step cap is excluded from the pair count but still shows whether the table
            # was ever encountered, which is what "missed it in N of 5 runs" reports.
            tables = sorted(missed)
            per_run = []
            for spec in sorted(runs):
                r = runs[spec]
                per_run.append({"spec": spec, "ok": r["ok"], "status": r["status"],
                                "student": spec not in teacher,
                                "saw": {t: touched(r["trace"], t) for t in tables}})
            cases.append({"iid": iid, "needed": sorted(needed), "tables": tables,
                          "missed": dict(missed), "had": had, "skipped": skipped,
                          "per_run": per_run,
                          "winners": sorted(winners), "losers": sorted(losers)})
    return cases


def report(title, note, cases, Q, show_sql, rec):
    print(f"\n{'=' * 78}\n{title}\n{note}\n{'=' * 78}")
    if not cases:
        print("  none")
        return
    for c in cases:
        iid = c["iid"]
        tables = c["tables"]
        print(f"\n--- {iid}  ({Q[iid]['db']})")
        print(textwrap.fill(Q[iid]["question"], 96, initial_indent="    ",
                            subsequent_indent="    "))
        student = [r for r in c["per_run"] if r["student"]]
        never = [r for r in student if not all(r["saw"].values())]
        print(f"    NEEDED BUT MISSED: {', '.join('`' + t + '`' for t in tables)}"
              f"  -- never encountered in {len(never)} of the 9B's {len(student)} runs"
              f" ({len([r for r in never if r['status'] != 'fallback'])} of those finished)")
        head = "      {:26s} {:10s} {:9s} ".format("run", "outcome", "finished")
        print(head + "  ".join(f"saw {t}" for t in tables))
        for r in c["per_run"]:
            saw = "  ".join(f"{'yes' if r['saw'][t] else 'NO ':>{len(t) + 4}s}" for t in tables)
            print(f"      {r['spec']:26s} {'CORRECT' if r['ok'] else 'wrong':10s}"
                  f" {'no (cap)' if r['status'] == 'fallback' else 'yes':9s} {saw}"
                  f"   {trace_path(r['spec'], iid)}")
        if show_sql:
            for s in c["winners"]:
                print(f"\n      winning SQL ({s}):")
                print(textwrap.indent(rec[iid][s]["sql"].strip(), "        "))
            for table, specs in sorted(c["missed"].items()):
                print(f"\n      failing SQL ({specs[0]}), no `{table}`:")
                print(textwrap.indent(rec[iid][specs[0]]["sql"].strip(), "        "))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sql", action="store_true", help="also print winning and failing queries")
    args = ap.parse_args()

    Q = local_questions()
    qdb = {k: v["db"] for k, v in Q.items()}

    within = collect(list(PHASE0_RUNS), qdb)
    report("WITHIN-MODEL (Section 1) -- questions the 9B both solved and failed",
           "the winning query is the 9B's own, from another sample of the same prompt",
           find_cases(within), Q, args.sql, within)

    bucket_c = buckets(qdb)["C"]
    cross = collect(list(PHASE0_RUNS) + TEACHER_RUNS, qdb)
    cases = find_cases(cross, keep=bucket_c, teacher=set(TEACHER_RUNS))
    report("CROSS-MODEL (Section 7.2) -- questions no 9B run ever solved",
           "the winning query is the 27B teacher's verified one; the 9B's failures are judged against it",
           cases, Q, args.sql, cross)

    # What happened when these questions were re-run with the linkage handed over.
    # One repeat per r<N> group, each sharded across _<M> dirs, so keep the groups apart:
    # collapsing them into one spec would report 4 runs as 1.
    flagged = [c["iid"] for c in cases]
    if flagged:
        o_specs, d_specs = discover("ablation_oracle"), discover("ablation_decoy")
        arms = collect(o_specs + d_specs, qdb)
        print(f"\n{'=' * 78}\nORACLE vs DECOY on the cross-model flagged questions (Section 7.4)"
              f"\nhanding over the correct tables is what these arms test\n{'=' * 78}")
        for iid in flagged:
            runs = arms.get(iid, {})
            if not runs:
                print(f"  {iid}: not in the arms")
                continue
            o = [s for s in o_specs if s in runs]
            d = [s for s in d_specs if s in runs]
            print(f"  {iid}: oracle {sum(runs[s]['ok'] for s in o)}/{len(o)}"
                  f"   decoy {sum(runs[s]['ok'] for s in d)}/{len(d)}")
            for s in o + d:
                mark = "CORRECT" if runs[s]["ok"] else (runs[s]["status"] or "wrong")
                print(f"      {mark:9s} {s:26s} {trace_path(s, iid)}")


if __name__ == "__main__":
    main()
