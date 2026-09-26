#!/usr/bin/env python3
"""Does a bigger model use the tools better, or just write better SQL?

Compares two sets of runs episode by episode on the questions BOTH attempted, so
model capability is the only thing that differs: same agent loop, same six tools,
same 30-step cap, same databases.

What "better tool calling" could mean, measured separately:

  finishing         share of episodes that submit an answer instead of burning the
                    30-step cap (a step-cap episode submits its last exploratory
                    query, so this is the clearest agentic failure)
  efficiency        tool calls spent per episode, and steps that ended without any
                    tool call -- one of those is the final answer, the rest are
                    budget spent on nothing
  accuracy of use   share of tool calls that come back an error
  recovery          after an errored call, does the next call succeed
  breadth           distinct tables inspected -- exploring the schema at all

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/tool_use.py
    uv run python scripts/analysis/tool_use.py --a 'v2_pass4_k1' --b 'think_k1_*' --labels 9B,9B-thinking
"""

import argparse
import json
import statistics as st
from collections import Counter

from _common import load_traces, local_questions, rescore

STUDENT = ["v2_armAplus", "v2_pass4_k1", "v2_pass4_k2", "v2_pass4_k3", "v2_pass4_k4"]
TEACHER = ["teacher_p1_*", "teacher_p1b_*"]


def errored(result) -> bool:
    r = str(result or "")
    return r.lstrip().upper().startswith("ERROR")


def episode_stats(t: dict) -> dict:
    calls = [e for e in t["trace"] if "tool" in e]
    # Steps that ended without a tool call. Counting trace ENTRIES with empty
    # assistant text misses these entirely: the turn has text (and, with thinking
    # on, reasoning), it just never gets round to calling a tool. Count step
    # numbers instead, and subtract one for the step that submits the answer.
    steps = {e["step"] for e in t["trace"] if e.get("step") is not None}
    acted = {e["step"] for e in calls}
    idle = max(0, len(steps - acted) - 1)
    errs = [i for i, e in enumerate(calls) if errored(e.get("result"))]
    recovered = sum(1 for i in errs if i + 1 < len(calls) and not errored(calls[i + 1].get("result")))
    tables = set()
    for e in calls:
        if e["tool"] in ("describe_table", "get_column_values"):
            args = e.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            if isinstance(args, dict) and args.get("table"):
                tables.add(str(args["table"]).lower())
    return {"calls": len(calls), "empty": idle, "errors": len(errs),
            "recovered": recovered, "recoverable": len(errs),
            "tables": len(tables), "by_tool": Counter(e["tool"] for e in calls),
            "finished": t.get("status") != "fallback"}


def gather(specs, qdb):
    traces = load_traces(specs)
    ok = rescore(traces, qdb)
    eps = {}
    for spec, by_iid in traces.items():
        for iid, t in by_iid.items():
            eps[(spec, iid)] = dict(episode_stats(t), ok=ok[(spec, iid)], iid=iid)
    return eps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default=",".join(STUDENT))
    ap.add_argument("--b", default=",".join(TEACHER))
    ap.add_argument("--labels", default="Qwen3.5-9B,Qwen3.6-27B")
    args = ap.parse_args()
    la, lb = args.labels.split(",")

    qdb = {k: v["db"] for k, v in local_questions().items()}
    A, B = gather(args.a.split(","), qdb), gather(args.b.split(","), qdb)
    shared = {e["iid"] for e in A.values()} & {e["iid"] for e in B.values()}
    A = {k: v for k, v in A.items() if v["iid"] in shared}
    B = {k: v for k, v in B.items() if v["iid"] in shared}
    print(f"{len(shared)} questions both models attempted; "
          f"{len(A)} episodes for {la}, {len(B)} for {lb}\n")

    def col(eps, key, agg=st.mean):
        return agg([e[key] for e in eps.values()])

    rows = [
        ("scored correct", lambda e: f"{sum(x['ok'] for x in e.values())}/{len(e)}"
                                     f" ({sum(x['ok'] for x in e.values()) / len(e):.0%})"),
        ("finished (did not hit the cap)", lambda e: f"{sum(x['finished'] for x in e.values())}/{len(e)}"
                                                    f" ({sum(x['finished'] for x in e.values()) / len(e):.0%})"),
        ("tool calls per episode (median)", lambda e: f"{col(e, 'calls', st.median):.1f}"),
        ("steps spent without a tool call", lambda e: f"{col(e, 'empty'):.2f}"),
        ("distinct tables inspected (median)", lambda e: f"{col(e, 'tables', st.median):.1f}"),
        ("errored tool calls", lambda e: f"{sum(x['errors'] for x in e.values())}"
                                         f"/{sum(x['calls'] for x in e.values())}"
                                         f" ({sum(x['errors'] for x in e.values()) / max(1, sum(x['calls'] for x in e.values())):.1%})"),
        ("next call succeeds after an error", lambda e: f"{sum(x['recovered'] for x in e.values())}"
                                                       f"/{sum(x['recoverable'] for x in e.values())}"
                                                       f" ({sum(x['recovered'] for x in e.values()) / max(1, sum(x['recoverable'] for x in e.values())):.0%})"),
    ]
    print(f"{'':36s} {la:>16s} {lb:>16s}")
    for name, fn in rows:
        print(f"{name:36s} {fn(A):>16s} {fn(B):>16s}")

    print(f"\ntool mix (share of all calls)\n{'':22s} {la:>16s} {lb:>16s}")
    ta = sum((e["by_tool"] for e in A.values()), Counter())
    tb = sum((e["by_tool"] for e in B.values()), Counter())
    for tool in sorted(set(ta) | set(tb), key=lambda x: -(ta[x] + tb[x])):
        print(f"  {tool:20s} {ta[tool] / max(1, sum(ta.values())):15.1%} "
              f"{tb[tool] / max(1, sum(tb.values())):15.1%}")

    # Per question: does the bigger model finish the episodes the smaller one could not?
    fa = {i: st.mean([e["finished"] for e in A.values() if e["iid"] == i]) for i in shared}
    fb = {i: st.mean([e["finished"] for e in B.values() if e["iid"] == i]) for i in shared}
    stuck = sorted(i for i in shared if fa[i] < 0.5)
    print(f"\n{la} hit the cap on most runs of {len(stuck)} of {len(shared)} questions.")
    if stuck:
        print(f"  on those, {lb} finished {st.mean([fb[i] for i in stuck]):.0%} of its episodes")
        print(f"  elsewhere, {lb} finished {st.mean([fb[i] for i in shared if i not in stuck]):.0%}")


if __name__ == "__main__":
    main()
