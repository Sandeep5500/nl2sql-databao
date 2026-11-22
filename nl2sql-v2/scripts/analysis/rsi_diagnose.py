"""Build the diagnosis bundle the RSI proposer sees. GOLD-FREE BY CONSTRUCTION.

The proposer is an independent model asked to change the harness. What it sees
decides what it can propose, and one thing it must never see is the gold answer:
a proposer that knew gold could write a patch that hardcodes results, and the
patch would "work" while teaching us nothing.

So this strips, per episode:
  - the gold SQL and gold result values (never read from disk at all)
  - `detail`, which can quote gold values on a mismatch
  - the final `sql` is KEPT, because it is the agent's own work

What it keeps is the agent's own behaviour -- its queries, the tool output it
received, how many steps it burned, whether it submitted or was salvaged -- plus
the pass/fail label, which is the whole point of a diagnosis and cannot leak an
answer on its own.

The split guard: proposals are made against `evolve` and judged on `heldout`,
whose databases are disjoint. So even a proposer that overfits to the specific
evolve questions cannot buy a held-out win.

Usage:
    python rsi_diagnose.py --results "results/synbase_evolve_*.csv" \
        --traces "logs/traces/synbase_evolve_*" --out bundle.md [--n-traces 15]
"""
import argparse, csv, glob, json, os, re, sys
from collections import Counter, defaultdict

GOLD_KEYS = ("gold", "gold_sql", "gold_preview", "expected", "answer")


def load_rows(pattern):
    out = []
    for f in sorted(glob.glob(pattern)):
        try:
            out.extend(csv.DictReader(open(f)))
        except Exception:
            continue
    return [r for r in out if r.get("instance_id")]


def solved(r):
    return (r.get("score") or "0").strip() not in ("", "0")


def load_traces(pattern):
    out = {}
    for d in sorted(glob.glob(pattern)):
        if not os.path.isdir(d):
            continue
        for f in sorted(glob.glob(os.path.join(d, "*.json"))):
            try:
                t = json.load(open(f))
            except Exception:
                continue
            if t.get("instance_id"):
                out.setdefault(t["instance_id"], t)
    return out


def scrub(t, cell_limit=700):
    """Keep the agent's own behaviour; drop anything gold-derived."""
    steps = []
    for e in t.get("trace", []) or []:
        tool = e.get("tool")
        args = e.get("args") if isinstance(e.get("args"), dict) else {}
        res = e.get("result")
        res = "" if res is None else str(res)
        if len(res) > cell_limit:
            res = res[:cell_limit] + f"\n[...{len(res)-cell_limit} more chars...]"
        steps.append({"tool": tool,
                      "sql": (args.get("sql") or "")[:1200] if tool == "run_sql_query" else None,
                      "args": {k: v for k, v in args.items() if k != "sql"} or None,
                      "result": res})
    return {"instance_id": t.get("instance_id"),
            "question": t.get("question"),
            "status": t.get("status"),
            "solved": bool(t.get("score")),
            "final_sql": (t.get("sql") or "")[:1500],
            "n_steps": len(steps),
            "steps": steps}


def assert_gold_free(text):
    """Enforcement, not advice: refuse to emit a bundle that mentions gold."""
    bad = []
    for pat in (r"\bgold[_ ]?sql\b", r"\bgold[_ ]?preview\b", r"\bexec_result\b",
                r"\bspider2lite_eval\b"):
        if re.search(pat, text, re.I):
            bad.append(pat)
    if bad:
        sys.exit(f"REFUSING to write the bundle: it references {bad}. "
                 f"The proposer must never see gold.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--traces", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-traces", type=int, default=15)
    ap.add_argument("--max-steps", type=int, default=30)
    a = ap.parse_args()

    rows = load_rows(a.results)
    if not rows:
        sys.exit(f"no episodes matched {a.results!r} -- quote the glob")
    traces = load_traces(a.traces)

    n = len(rows)
    acc = sum(1 for r in rows if solved(r)) / n
    stat = Counter((r.get("status") or "").strip() for r in rows)
    steps = [int(r["steps"]) for r in rows if (r.get("steps") or "").isdigit()]
    at_cap = sum(1 for s in steps if s >= a.max_steps) / max(len(steps), 1)

    fails = [r for r in rows if not solved(r)]
    # Sample across failure modes rather than taking the first N, so the
    # proposer is not shown one mode and asked to generalise from it.
    by_mode = defaultdict(list)
    for r in fails:
        st = (r.get("status") or "").strip()
        sc = (r.get("steps") or "0")
        cap = st == "fallback" or (sc.isdigit() and int(sc) >= a.max_steps)
        by_mode["at_cap_or_fallback" if cap else f"submitted_wrong"].append(r)
    picked, i = [], 0
    while len(picked) < a.n_traces and any(by_mode.values()):
        for k in list(by_mode):
            if by_mode[k] and len(picked) < a.n_traces:
                picked.append(by_mode[k].pop(0))
        i += 1
        if i > a.n_traces * 3:
            break

    # --- per-tool behaviour, aggregated over every trace ---
    tool_calls = Counter(); tool_err = Counter(); tool_empty = Counter()
    model_turns = Counter()
    sql_dupes = []; per_ep_tools = []
    for iid, t in traces.items():
        seen = Counter(); sqls = []
        for e in t.get("trace", []) or []:
            tool = e.get("tool")
            if not tool:
                # a model turn, not a tool call -- counting these as a tool
                # named "?" put a meaningless 13-calls-per-episode row at the
                # top of the table, which is exactly the mean step count
                model_turns[iid] += 1
                continue
            seen[tool] += 1
            tool_calls[tool] += 1
            res = str(e.get("result") or "")
            if res.startswith("ERROR:"):
                tool_err[tool] += 1
            if not res.strip():
                tool_empty[tool] += 1
            if tool == "run_sql_query":
                args = e.get("args") if isinstance(e.get("args"), dict) else {}
                sqls.append(re.sub(r"\s+", " ", re.sub(r"--[^\n]*", " ",
                            (args.get("sql") or "").lower())).strip())
        per_ep_tools.append(seen)
        if sqls:
            sql_dupes.append(len(sqls) - len(set(sqls)))

    L = []
    L.append("# RSI diagnosis bundle\n")
    L.append("Everything below is the agent's own behaviour on the **evolve** set. "
             "Correct answers are deliberately not included: you are diagnosing a "
             "harness, not learning the task.\n")
    L.append("## Aggregate\n")
    L.append(f"- episodes: {n}")
    L.append(f"- accuracy: {acc:.3f}  (this is a FLOOR to hold, not a target to chase)")
    L.append(f"- fallback rate: {stat.get('fallback', 0)/n:.3f}")
    L.append(f"- submitted rate: {stat.get('submitted', 0)/n:.3f}")
    L.append(f"- at the step cap ({a.max_steps}): {at_cap:.3f}")
    L.append(f"- mean steps: {sum(steps)/max(len(steps),1):.1f}\n")

    L.append("## Tool use, across every episode\n")
    L.append("| tool | calls | calls/episode | returned ERROR | returned empty |")
    L.append("|---|---|---|---|---|")
    ne = max(len(traces), 1)
    for tool, c in tool_calls.most_common():
        L.append(f"| `{tool}` | {c} | {c/ne:.1f} | "
                 f"{tool_err.get(tool,0)} ({tool_err.get(tool,0)/max(c,1):.0%}) | "
                 f"{tool_empty.get(tool,0)} ({tool_empty.get(tool,0)/max(c,1):.0%}) |")
    if sql_dupes:
        rep = sum(1 for d in sql_dupes if d > 0)
        L.append(f"\n- duplicate SQL per episode: mean "
                 f"{sum(sql_dupes)/len(sql_dupes):.2f}; "
                 f"{rep}/{len(sql_dupes)} episodes ({rep/len(sql_dupes):.0%}) re-ran "
                 f"an identical query at least once")
    rare = [(t, c) for t, c in tool_calls.items() if c / ne < 0.2]
    if rare:
        L.append("- tools called in under 0.2 episodes on average (candidates for "
                 "a description problem rather than a usefulness problem): "
                 + ", ".join(f"`{t}` ({c} calls total)" for t, c in sorted(rare)))
    never = [t for t in ("run_sql_query", "list_tables", "describe_table",
                         "get_column_values", "find_value", "search_context",
                         "read_documentation", "draft_sql") if t not in tool_calls]
    if never:
        L.append(f"- tools NEVER called in this configuration: "
                 f"{', '.join('`'+t+'`' for t in never)}")
    L.append("")
    L.append(f"## {len(picked)} failing episodes, sampled across failure modes\n")
    for r in picked:
        t = traces.get(r["instance_id"])
        if not t:
            continue
        s = scrub(t)
        L.append(f"### {s['instance_id']}  "
                 f"status={s['status']}  steps={s['n_steps']}")
        L.append(f"**Question.** {s['question']}\n")
        for j, st in enumerate(s["steps"]):
            head = f"- step {j+1} `{st['tool']}`"
            if st["args"]:
                head += f" {json.dumps(st['args'])[:160]}"
            L.append(head)
            if st["sql"]:
                L.append(f"```sql\n{st['sql']}\n```")
            if st["result"]:
                L.append(f"```\n{st['result']}\n```")
        L.append(f"\n**The agent's final SQL.**\n```sql\n{s['final_sql']}\n```\n")

    text = "\n".join(L)
    assert_gold_free(text)
    with open(a.out, "w") as f:
        f.write(text)
    print(f"wrote {a.out}  ({len(text)} chars, ~{len(text)//4} tokens)")
    print(f"  {n} episodes, {len(fails)} failures, {len(picked)} traces included")
    print("  gold-free check: passed")


if __name__ == "__main__":
    main()
