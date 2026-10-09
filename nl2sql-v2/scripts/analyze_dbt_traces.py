#!/usr/bin/env python3
"""Error analysis over a dbt run's traces. Every number in the write-up comes from here.

    uv run python scripts/analyze_dbt_traces.py ../logs/traces/dbt_full \
        --run ../results/dbt_full_run.csv --scored ../results/dbt_full_scored.csv

Reports, with the trace files behind each figure:
  * accuracy against all three denominators
  * the tool mix, split into observing vs acting
  * the fallback-vs-submitted call profile ("losers grind")
  * dbt error classes, counted by instance rather than by occurrence
  * the zero-edit and no-op-query pathologies, named
"""

import argparse
import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

OBSERVE = {"run_sql_query", "read_file", "describe_table", "list_files", "list_tables"}
ACT = {"write_file", "run_dbt"}

DBT_ERROR_CLASSES = {
    "missing_ref_or_source": r"depends on a (?:node|source) named",
    "binder_error": r"Binder Error",
    "catalog_error": r"Catalog Error|does not exist",
    "parsing_error": r"Parsing Error",
    "needs_dbt_deps": r'Run "dbt deps" to install package',
}


def load_csv(path):
    if not path or not Path(path).exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["instance_id"]: r for r in csv.DictReader(f)}


def section(t):
    print("\n" + t)
    print("-" * len(t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace_dir", type=Path)
    ap.add_argument("--run", help="run.csv from the benchmark")
    ap.add_argument("--scored", help="scored.csv from score_dbt.py")
    args = ap.parse_args()

    traces = {p.stem: json.loads(p.read_text(encoding="utf-8"))
              for p in sorted(args.trace_dir.glob("*.json"))}
    if not traces:
        raise SystemExit(f"no traces in {args.trace_dir}")
    run, scored = load_csv(args.run), load_csv(args.scored)
    correct = {i for i, r in scored.items() if r.get("score") == "1"}
    defective = {i for i, r in scored.items()
                 if str(r.get("score_detail", "")).startswith("match_error")}
    not_sub = {i for i, r in scored.items()
               if r.get("score_detail") == "not_submitted"}

    print(f"traces analysed : {len(traces)}  (from {args.trace_dir})")

    if scored:
        section("accuracy")
        attempted = len(scored) - len(not_sub)
        sc = attempted - len(defective)
        n = len(correct)
        for label, denom in (("scoreable", sc), ("attempted", attempted),
                             ("full gold set", len(scored))):
            pct = 100.0 * n / max(denom, 1)
            se = (pct * (100 - pct) / max(denom, 1)) ** 0.5
            print(f"  {label:15s} {n}/{denom} = {pct:.1f}%  (+/-{1.96 * se:.1f} at 95%)")
        if defective:
            print(f"  excluded as gold-defective: {sorted(defective)}")
        if not_sub:
            print(f"  no gold shipped (withheld) : {sorted(not_sub)}")

    # ---- tool mix ----
    calls = Counter()
    per_inst = defaultdict(Counter)
    for iid, t in traces.items():
        for ev in t.get("trace", []):
            name = ev.get("tool")
            if name:
                calls[name] += 1
                per_inst[iid][name] += 1
    total = sum(calls.values())
    section(f"tool mix ({total} calls, {total / len(traces):.1f} per episode)")
    for k, v in calls.most_common():
        kind = "observe" if k in OBSERVE else ("act" if k in ACT else "")
        print(f"  {k:16s} {v:5d}  {100 * v / total:5.1f}%  {kind}")
    obs = sum(v for k, v in calls.items() if k in OBSERVE)
    act = sum(v for k, v in calls.items() if k in ACT)
    print(f"  {'OBSERVING':16s} {obs:5d}  {100 * obs / total:5.1f}%")
    print(f"  {'ACTING':16s} {act:5d}  {100 * act / total:5.1f}%")

    # ---- fallback vs submitted ----
    if run:
        section("call profile by outcome (mean calls per episode)")
        for status in ("fallback", "submitted"):
            ids = [i for i in traces if run.get(i, {}).get("status") == status]
            if not ids:
                continue
            agg = Counter()
            for i in ids:
                agg.update(per_inst[i])
            print(f"  {status} (n={len(ids)}): "
                  + "  ".join(f"{k}={agg[k] / len(ids):.1f}"
                              for k, _ in agg.most_common(6)))
        f_ids = [i for i in traces if run.get(i, {}).get("status") == "fallback"]
        s_ids = [i for i in traces if run.get(i, {}).get("status") == "submitted"]
        if f_ids and s_ids:
            fq = statistics.mean(per_inst[i]["run_sql_query"] for i in f_ids)
            sq = statistics.mean(per_inst[i]["run_sql_query"] for i in s_ids)
            print(f"  -> run_sql_query {fq:.1f} (fallback) vs {sq:.1f} (submitted) "
                  f"= {fq / max(sq, 0.01):.1f}x")

        section("steps vs the cap")
        steps = [float(run[i]["steps"]) for i in traces if i in run]
        print(f"  mean {statistics.mean(steps):.1f}  median "
              f"{statistics.median(steps):.1f}  max {max(steps):.0f}")
        at_cap = [i for i in traces
                  if i in run and float(run[i]["steps"]) >= max(steps)]
        print(f"  at the cap: {len(at_cap)}/{len(steps)}")

    # ---- dbt error classes, by instance ----
    hit = defaultdict(set)
    for iid, t in traces.items():
        for ev in t.get("trace", []):
            if ev.get("tool") != "run_dbt":
                continue
            res = str(ev.get("result") or "")
            for label, pat in DBT_ERROR_CLASSES.items():
                if re.search(pat, res):
                    hit[label].add(iid)
    section("dbt error classes (instances affected, not occurrences)")
    for label, ids in sorted(hit.items(), key=lambda kv: -len(kv[1])):
        nc = len(ids & correct)
        print(f"  {label:24s} {len(ids):2d} instances, {nc} correct")
        print(f"    e.g. {sorted(ids)[:5]}")

    # ---- pathologies, named so they can be opened ----
    section("pathologies (open these traces)")
    zero_write = sorted(i for i in traces if per_inst[i]["write_file"] == 0)
    print(f"  zero file edits ({len(zero_write)}): {zero_write}")
    zero_act = sorted(i for i in traces
                      if per_inst[i]["write_file"] == 0 and per_inst[i]["run_dbt"] == 0)
    print(f"  never wrote AND never ran dbt ({len(zero_act)}): {zero_act}")
    spin = sorted(i for i in traces
                  if per_inst[i]["run_dbt"] >= 10 and per_inst[i]["write_file"] == 0)
    print(f"  ran dbt >=10x with zero edits ({len(spin)}): {spin}")

    noop = []
    for iid, t in traces.items():
        q = [str((ev.get("args") or {}).get("sql", "")).strip().lower()
             for ev in t.get("trace", []) if ev.get("tool") == "run_sql_query"]
        trivial = [s for s in q if re.fullmatch(r"select\s+'[^']*'", s)]
        if len(trivial) >= 2:
            noop.append((iid, len(trivial)))
    print(f"  emitted >=2 no-op probe queries ({len(noop)}): "
          f"{sorted(noop, key=lambda kv: -kv[1])}")

    if run and scored:
        won_unbuilt = sorted(i for i in correct
                             if run.get(i, {}).get("dbt_build_ok") == "0")
        print(f"  correct WITHOUT a successful build ({len(won_unbuilt)}): "
              f"{won_unbuilt}")
        section("correctness by behaviour")
        for key, vals in (("dbt_build_ok", ("1", "0")),
                          ("status", ("submitted", "fallback"))):
            for v in vals:
                ids = [i for i in traces if run.get(i, {}).get(key) == v]
                print(f"  {key}={v:10s} {len(ids & correct) if isinstance(ids, set) else len(set(ids) & correct)}/{len(ids)} correct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
