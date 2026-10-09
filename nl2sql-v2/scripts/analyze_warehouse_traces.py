#!/usr/bin/env python3
"""Error analysis for a warehouse lane (BigQuery or Snowflake).

Every figure in a write-up should come from here so it can be re-derived:

    uv run python scripts/analyze_warehouse_traces.py ../logs/traces/bq_v2 \
        --run ../results/bq_v2_run.csv

Reports accuracy, the tool mix, the winners-vs-losers call profile, the SQL error
classes the warehouse returned, scan volume and its skew, and whether failures look
like retrieval (never found the table) or semantics (answered and was wrong).

`analyse()` returns the same content as a list of sections so the trajectory viewer's
Analysis tab can render it without recomputing anything:

    uv run python scripts/analyze_warehouse_traces.py ../logs/traces/bq_v2 \
        --run ../results/bq_v2_run.csv --json ../logs/openhands/bq_v2.analysis.json

Keeping the computation here means the CLI and the tab can never disagree.
"""

import argparse
import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

TiB = 1024.0 ** 4
GiB = 1024.0 ** 3

# what the warehouse itself complained about, by cause.
# These are substring probes over tool results, so an instance can land in several
# classes, and a class counts INSTANCES AFFECTED, never calls. "permission" in
# particular over-counts: "403" matches digits in result data too, so the Forbidden
# row below (keyed on the exception name the tool layer raised) is the honest one.
SQL_ERROR_CLASSES = {
    "unrecognized_name": r"Unrecognized name|Name .* not found|not found inside",
    "table_not_found": r"Not found: Table",
    "dataset_not_found": r"Not found: Dataset",
    "syntax_error": r"Syntax error",
    "type_error": r"No matching signature|Cannot coerce|cannot be cast|argument type",
    "unnest_struct": r"Cannot access field|values referenced in UNNEST",
    "aggregate_misuse": r"must be grouped or aggregated",
    "function_not_found": r"Function not found",
    "over_cap_refused": r"would scan .* over the",
    "budget_exhausted": r"budget exhausted|BudgetExhausted",
    "timeout": r"was cancelled|exceeded .*s and was cancelled|TimeoutError",
    "forbidden": r"Forbidden",
}

# The schema the agent was shown can be cut two different ways, and the markers
# differ: schema_overview() emits the first, full_schema_dump() the second. Looking
# for only the first reported 0/204 truncated on a lane where 149/204 were.
TRUNCATION_MARKERS = ("overview truncated", "[schema dump truncated]")


def _pct(n, d):
    return 100.0 * n / d if d else 0.0


def analyse(trace_dir: Path, run_csv: Path, top: int = 8) -> dict:
    with open(run_csv, newline="", encoding="utf-8") as f:
        run = {r["instance_id"]: r for r in csv.DictReader(f)}
    traces = {p.stem: json.loads(p.read_text(encoding="utf-8"))
              for p in sorted(Path(trace_dir).glob("*.json"))}
    correct = {i for i, r in run.items() if r.get("score") == "1"}
    n = len(run)
    sections = []

    def add(title, columns, rows, note=""):
        sections.append({"title": title, "note": note,
                         "columns": columns, "rows": [list(map(_cell, r)) for r in rows]})

    def _cell(v):
        return v if isinstance(v, (int, float, type(None))) else str(v)

    # ── accuracy ──────────────────────────────────────────────────────────
    pct = _pct(len(correct), n)
    se = (pct * (100 - pct) / n) ** 0.5 if n else 0.0
    rows = [["overall", len(correct), n, f"{pct:.1f}%", f"+/-{1.96 * se:.1f}"]]
    fams = defaultdict(list)
    for i, r in run.items():
        fams[re.match(r"[a-z_]+", i).group(0)].append(r)
    for fam, rs in sorted(fams.items()):
        c = sum(1 for r in rs if r["score"] == "1")
        rows.append([fam, c, len(rs), f"{_pct(c, len(rs)):.1f}%", ""])
    add("accuracy", ["set", "correct", "n", "accuracy", "95% CI"], rows,
        "A single greedy pass. The CI is binomial, so differences inside it are noise.")

    add("episode status", ["status", "episodes", "correct"],
        [[s, c, sum(1 for r in run.values()
                    if r["status"] == s and r["score"] == "1")]
         for s, c in Counter(r["status"] for r in run.values()).most_common()],
        "'fallback' and 'no_sql' mean the loop ended without a clean submission.")

    # ── failure taxonomy ──────────────────────────────────────────────────
    det = Counter()
    for r in run.values():
        d = r["score_detail"]
        if r["score"] == "1":
            det["correct"] += 1
        elif d.startswith("matches"):
            det["scored-but-wrong?"] += 1
        else:
            det[d.split(":")[0][:34] or "(blank)"] += 1
    add("failure taxonomy (episode level)", ["outcome", "episodes"],
        [[k, v] for k, v in det.most_common()])

    # ── tool mix ──────────────────────────────────────────────────────────
    calls = Counter()
    per_inst = defaultdict(Counter)
    errs = Counter()
    err_inst = defaultdict(set)
    cls_hit = defaultdict(set)
    for iid, t in traces.items():
        for ev in t.get("trace", []):
            name = ev.get("tool")
            if not name:
                continue
            calls[name] += 1
            per_inst[iid][name] += 1
            res = str(ev.get("result") or "")
            if res.startswith("ERROR:"):
                key = res.split(":")[1].strip().split()[0][:34] if ":" in res \
                    else res[:34]
                errs[key] += 1
                err_inst[key].add(iid)
            for label, pat in SQL_ERROR_CLASSES.items():
                if re.search(pat, res, re.IGNORECASE):
                    cls_hit[label].add(iid)
    total = sum(calls.values())
    add(f"tool mix ({total} calls, {total / max(len(traces), 1):.1f} per episode)",
        ["tool", "calls", "share"],
        [[k, v, f"{_pct(v, total):.1f}%"] for k, v in calls.most_common()])

    rows = []
    for label, ids in (("correct", sorted(correct)),
                       ("wrong", sorted(set(traces) - correct))):
        if not ids:
            continue
        agg = Counter()
        for i in ids:
            agg.update(per_inst[i])
        rows.append([label, len(ids)] + [f"{agg[k] / len(ids):.1f}"
                                         for k, _ in calls.most_common(5)])
    note = ""
    if correct and set(traces) - correct:
        w = statistics.mean(per_inst[i]["run_sql_query"] for i in correct)
        l = statistics.mean(per_inst[i]["run_sql_query"]
                            for i in set(traces) - correct)
        note = (f"run_sql_query {l:.1f} (wrong) vs {w:.1f} (correct) = "
                f"{l / max(w, 0.01):.1f}x. Thrashing is the clearest signal of a "
                f"lost episode, not a cause of it.")
    add("call profile by outcome (mean per episode)",
        ["outcome", "episodes"] + [k for k, _ in calls.most_common(5)], rows, note)

    add("tool errors returned to the model", ["error", "calls", "instances"],
        [[k, v, len(err_inst[k])] for k, v in errs.most_common(top)],
        "Counted from the tool layer's own exception name, so these do not "
        "double-count the way the substring classes below can.")

    add("warehouse error classes (instances affected)",
        ["class", "instances", "of which correct"],
        [[label, len(ids), len(ids & correct)]
         for label, ids in sorted(cls_hit.items(), key=lambda kv: -len(kv[1]))],
        "Substring probes over tool results; one instance can appear in several "
        "rows, and the count is instances, not calls.")

    # ── retrieval vs semantics ────────────────────────────────────────────
    lost = cls_hit.get("table_not_found", set()) | cls_hit.get("unrecognized_name", set())
    wrong_answer = {i for i, r in run.items() if r["score_detail"] == "result_mismatch"}
    add("retrieval vs semantics", ["question", "episodes"],
        [["answered but wrong (result_mismatch)", len(wrong_answer)],
         ["ever hit a missing name/table", len(lost)],
         ["never produced SQL at all (no_sql)",
          sum(1 for r in run.values() if r["status"] == "no_sql")],
         ["wrong answers that never hit a name error", len(wrong_answer - lost)]],
        "The last row is the semantics-only failure count: the agent found the "
        "tables and still got the answer wrong.")

    # ── the truncation confound ───────────────────────────────────────────
    trunc = [i for i, t in traces.items()
             if any(m in str(t.get("system") or "") for m in TRUNCATION_MARKERS)]
    rest = sorted(set(traces) - set(trunc))
    tc, rc = len(set(trunc) & correct), len(set(rest) & correct)
    add("schema shown to the agent (the retrieval confound)",
        ["cohort", "episodes", "correct", "accuracy"],
        [["schema truncated", len(trunc), tc, f"{_pct(tc, len(trunc)):.1f}%"],
         ["schema complete", len(rest), rc, f"{_pct(rc, len(rest)):.1f}%"]],
        "Truncation correlates with database size, so this is not a clean causal "
        "estimate -- but the cut is naive, so on a large database the agent can "
        "never be shown the table it needs.")

    # ── step cap ──────────────────────────────────────────────────────────
    steps = {i: int(r["steps"]) for i, r in run.items() if (r.get("steps") or "").isdigit()}
    if steps:
        cap = max(steps.values())
        at_cap = [i for i, s in steps.items() if s >= cap]
        add("step budget", ["cohort", "episodes", "correct", "accuracy"],
            [[f"hit the cap ({cap} steps)", len(at_cap),
              len(set(at_cap) & correct),
              f"{_pct(len(set(at_cap) & correct), len(at_cap)):.1f}%"],
             ["finished early", len(steps) - len(at_cap),
              len(correct) - len(set(at_cap) & correct),
              f"{_pct(len(correct) - len(set(at_cap) & correct), len(steps) - len(at_cap)):.1f}%"]],
            "An episode that runs out of steps submits whatever it has, or nothing.")

    # ── scan volume ───────────────────────────────────────────────────────
    sb = {i: float(r["scan_bytes"]) for i, r in run.items()
          if (r.get("scan_bytes") or "").strip()}
    if sb:
        tot = sum(sb.values())
        v = list(sb.values())
        rows = [["total scanned", f"{tot / TiB:.4f} TiB",
                 f"{_pct(tot, TiB):.0f}% of a 1 TiB free tier"],
                ["per instance mean", f"{statistics.mean(v) / GiB:.2f} GiB", ""],
                ["per instance median", f"{statistics.median(v) / GiB:.3f} GiB", ""],
                ["per instance max", f"{max(v) / GiB:.1f} GiB", ""]]
        if correct & set(sb):
            rows.append(["correct answers cost",
                         f"{statistics.mean([sb[i] for i in correct if i in sb]) / GiB:.2f} GiB",
                         "mean"])
        wrong_sb = [b for i, b in sb.items() if i not in correct]
        if wrong_sb:
            rows.append(["wrong answers cost",
                         f"{statistics.mean(wrong_sb) / GiB:.2f} GiB", "mean"])
        add("scan volume (the billed quantity)", ["measure", "value", "note"], rows,
            f"At $6.25/TiB on demand this pass costs about "
            f"${6.25 * tot / TiB:.2f} once the free tier is spent.")

        heavy = sorted(sb.items(), key=lambda kv: -kv[1])[:top]
        share = sum(b for _, b in heavy) / tot
        add(f"heaviest instances ({_pct(share * tot, tot):.0f}% of all bytes)",
            ["instance", "database", "GiB", "outcome"],
            [[i, run[i]["db"][:32], f"{b / GiB:.2f}",
              "correct" if i in correct else "wrong"] for i, b in heavy])

    return {"meta": {"trace_dir": str(trace_dir), "run_csv": str(run_csv),
                     "episodes": n, "traces": len(traces),
                     "correct": len(correct),
                     "accuracy_pct": round(pct, 1)},
            "sections": sections}


def render(report: dict) -> str:
    out = []
    for s in report["sections"]:
        out.append("\n" + s["title"])
        out.append("-" * len(s["title"]))
        widths = [max(len(str(s["columns"][c])),
                      *(len(str(r[c])) for r in s["rows"])) if s["rows"]
                  else len(str(s["columns"][c]))
                  for c in range(len(s["columns"]))]
        out.append("  " + "  ".join(str(h).ljust(w)
                                    for h, w in zip(s["columns"], widths)))
        for r in s["rows"]:
            out.append("  " + "  ".join(str(c).ljust(w)
                                        for c, w in zip(r, widths)))
        if s["note"]:
            out.append(f"  -> {s['note']}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace_dir", type=Path)
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--json", type=Path,
                    help="also write the report as JSON for the viewer's Analysis tab")
    args = ap.parse_args()

    report = analyse(args.trace_dir, args.run, args.top)
    print(render(report))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
