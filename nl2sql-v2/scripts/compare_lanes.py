#!/usr/bin/env python3
"""Compare two runs of the same question set under different configurations.

    uv run python scripts/compare_lanes.py \
        --a ../results/bq_v2_run.csv --a-traces ../logs/traces/bq_v2 \
        --b ../results/bq_v3_run.csv --b-traces ../logs/traces/bq_v3

Distinct from scripts/analysis/paired_failures.py, which compares samples of the
SAME configuration to separate retrieval from generation. This compares two
configurations over the same questions, which is what a fixes-vs-baseline or
retrieval-vs-no-retrieval claim rests on.

The headline a single accuracy difference hides is the churn underneath it: a lane
can gain 10 and lose 8 for a net +2, and those 8 are the regression to explain. So
the flips are reported in both directions, with the error classes and tool mix that
changed, and the per-instance lists are printed so any claim can be traced to
episodes.

A net difference inside the binomial CI of either lane is not evidence of
improvement, and this prints the CI so that is visible rather than implied.
"""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

TiB = 1024.0 ** 4
GiB = 1024.0 ** 3

# the tool-layer exception names and query-refusal classes worth contrasting
ERROR_PROBES = {
    "information_schema_404": r"Not found: Dataset|INFORMATION_SCHEMA",
    "out_of_scope_refused": r"is not part of the",
    "forbidden": r"Forbidden",
    "not_found": r"NotFound|Not found: Table",
    "bad_request": r"BadRequest",
    "timeout": r"TimeoutError|was cancelled",
    "budget": r"BudgetExhausted|budget exhausted",
    "find_value_dead": r"find_value is disabled",
    "schema_truncated": r"\[schema dump truncated\]|overview truncated",
}


def load(run_csv: Path) -> dict:
    with open(run_csv, newline="", encoding="utf-8") as f:
        return {r["instance_id"]: r for r in csv.DictReader(f)}


def load_traces(d: Path | None) -> dict:
    if not d or not d.is_dir():
        return {}
    return {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(d.glob("*.json"))}


def fnum(row, key):
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def ci(correct: int, n: int) -> float:
    if not n:
        return 0.0
    p = 100.0 * correct / n
    return 1.96 * (p * (100 - p) / n) ** 0.5


def probe_counts(traces: dict) -> dict:
    """instances affected per probe -- instances, not calls, so one thrashing
    episode cannot look like a widespread problem."""
    hit = defaultdict(set)
    for iid, t in traces.items():
        blob = str(t.get("system") or "")
        for ev in t.get("trace", []):
            blob += "\n" + str(ev.get("result") or "")
        for label, pat in ERROR_PROBES.items():
            if re.search(pat, blob, re.IGNORECASE):
                hit[label].add(iid)
    return hit


def tool_mix(traces: dict) -> Counter:
    c = Counter()
    for t in traces.values():
        for ev in t.get("trace", []):
            if ev.get("tool"):
                c[ev["tool"]] += 1
    return c


def section(t):
    print("\n" + t)
    print("-" * len(t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, type=Path, help="baseline run CSV")
    ap.add_argument("--b", required=True, type=Path, help="new run CSV")
    ap.add_argument("--a-traces", type=Path)
    ap.add_argument("--b-traces", type=Path)
    ap.add_argument("--a-name", default=None)
    ap.add_argument("--b-name", default=None)
    ap.add_argument("--show", type=int, default=25,
                    help="how many instance ids to print per flip list")
    args = ap.parse_args()

    A, B = load(args.a), load(args.b)
    an = args.a_name or args.a.stem
    bn = args.b_name or args.b.stem
    shared = sorted(set(A) & set(B))
    section(f"{an} vs {bn}")
    print(f"  {an:14s} {len(A)} instances")
    print(f"  {bn:14s} {len(B)} instances")
    print(f"  compared on the {len(shared)} present in both")
    only_a, only_b = sorted(set(A) - set(B)), sorted(set(B) - set(A))
    if only_a:
        print(f"  only in {an}: {len(only_a)}  {', '.join(only_a[:12])}")
    if only_b:
        print(f"  only in {bn}: {len(only_b)}  {', '.join(only_b[:12])}")
    if not shared:
        raise SystemExit("no overlap between the two runs")

    ca = {i for i in shared if A[i].get("score") == "1"}
    cb = {i for i in shared if B[i].get("score") == "1"}
    n = len(shared)
    section("accuracy")
    print(f"  {an:14s} {len(ca):3d}/{n} = {100 * len(ca) / n:5.1f}%  "
          f"+/-{ci(len(ca), n):.1f}")
    print(f"  {bn:14s} {len(cb):3d}/{n} = {100 * len(cb) / n:5.1f}%  "
          f"+/-{ci(len(cb), n):.1f}")
    delta = 100.0 * (len(cb) - len(ca)) / n
    print(f"  delta          {len(cb) - len(ca):+3d}     = {delta:+5.1f} points")
    if abs(delta) < max(ci(len(ca), n), ci(len(cb), n)):
        print("  -> inside both lanes' confidence intervals: not yet evidence of a "
              "real difference. The flip counts below say more than the net does.")

    won, lost = sorted(cb - ca), sorted(ca - cb)
    section("flips (the churn the net difference hides)")
    print(f"  {bn} won  : {len(won)}")
    print(f"  {bn} lost : {len(lost)}")
    print(f"  net          : {len(won) - len(lost):+d}")
    print(f"  both correct : {len(ca & cb)}")
    print(f"  both wrong   : {n - len(ca | cb)}")
    if won:
        print(f"\n  gained ({len(won)}): " + ", ".join(won[: args.show])
              + (" ..." if len(won) > args.show else ""))
    if lost:
        print(f"\n  LOST ({len(lost)}): " + ", ".join(lost[: args.show])
              + (" ..." if len(lost) > args.show else ""))
        print("  ^ these are the regressions; read them before claiming the change "
              "is an improvement")

    section("status mix")
    sa = Counter(A[i].get("status") for i in shared)
    sb = Counter(B[i].get("status") for i in shared)
    print(f"  {'status':12s} {an:>12s} {bn:>12s}  delta")
    for k in sorted(set(sa) | set(sb), key=lambda k: -(sb[k] + sa[k])):
        print(f"  {str(k):12s} {sa[k]:12d} {sb[k]:12d}  {sb[k] - sa[k]:+d}")

    section("steps and scan")
    for label, R, ids in ((an, A, shared), (bn, B, shared)):
        st = [int(R[i]["steps"]) for i in ids if (R[i].get("steps") or "").isdigit()]
        sb_ = [fnum(R[i], "scan_bytes") for i in ids if fnum(R[i], "scan_bytes") > 0]
        cap = max(st) if st else 0
        print(f"  {label:14s} steps mean {sum(st) / max(len(st), 1):5.1f}  "
              f"at-cap({cap}) {sum(1 for x in st if x >= cap):3d}  "
              f"scanned {sum(sb_) / TiB:.4f} TiB  "
              f"(${6.25 * sum(sb_) / TiB:.2f} on demand)")

    ta, tb = load_traces(args.a_traces), load_traces(args.b_traces)
    if ta and tb:
        section("error classes (instances affected, shared instances only)")
        pa, pb = probe_counts(ta), probe_counts(tb)
        print(f"  {'class':24s} {an:>12s} {bn:>12s}  delta")
        for label in ERROR_PROBES:
            x = len(pa.get(label, set()) & set(shared))
            y = len(pb.get(label, set()) & set(shared))
            if x or y:
                print(f"  {label:24s} {x:12d} {y:12d}  {y - x:+d}")

        section("tool mix (calls)")
        ma, mb = tool_mix({k: v for k, v in ta.items() if k in shared}), \
            tool_mix({k: v for k, v in tb.items() if k in shared})
        print(f"  {'tool':20s} {an:>12s} {bn:>12s}  delta")
        for k in sorted(set(ma) | set(mb), key=lambda k: -(ma[k] + mb[k])):
            print(f"  {k:20s} {ma[k]:12d} {mb[k]:12d}  {mb[k] - ma[k]:+d}")
    else:
        print("\n(pass --a-traces/--b-traces for the error-class and tool-mix diff)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
