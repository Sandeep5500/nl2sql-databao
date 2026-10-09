#!/usr/bin/env python3
"""Per-question outcomes across every lane, as a markdown report.

    uv run python scripts/per_question_report.py \
        --lane bq_v2:../results/bq_v2_run.csv:../logs/traces/bq_v2 \
        --lane bq_v3:../results/bq_v3_run.csv:../logs/traces/bq_v3 \
        --out ../documents/bigquery_lane_comparison.md

A lane's accuracy says what changed in aggregate; this says which QUESTIONS changed,
and groups them by pattern across the lanes:

    never solved        wrong in every lane -- the real difficulty, and the ceiling
    always solved       right in every lane -- carries no information about changes
    recovered           wrong at baseline, right in the best lane
    regressed           right at baseline, wrong in the best lane
    unstable            flips more than once across lanes, i.e. sampling noise

The last group matters most for reading any single comparison: a question that flips
between two lanes with identical prompts is telling you about temperature-0 variance,
not about the change under test.
"""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

GiB = 1024.0 ** 3


def load(p):
    with open(p, newline="", encoding="utf-8") as f:
        return {r["instance_id"]: r for r in csv.DictReader(f)}


def tool_counts(tdir, iid):
    p = Path(tdir) / f"{iid}.json"
    if not p.exists():
        return {}
    t = json.loads(p.read_text(encoding="utf-8"))
    return Counter(e["tool"] for e in t.get("trace", []) if e.get("tool"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", action="append", required=True,
                    metavar="NAME:RUNCSV[:TRACEDIR]")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--title", default="BigQuery lane comparison")
    args = ap.parse_args()

    lanes = []
    for spec in args.lane:
        parts = spec.split(":")
        name, rcsv = parts[0], parts[1]
        tdir = parts[2] if len(parts) > 2 else None
        lanes.append((name, load(rcsv), tdir))
    names = [n for n, _r, _t in lanes]
    # recovered/regressed are measured first-lane to last-lane, so pass the
    # lanes in the order you want compared, best last.
    base, best = names[0], names[-1]

    every = sorted(set().union(*[set(r) for _n, r, _t in lanes]))

    def sc(lane_run, iid):
        r = lane_run.get(iid)
        if r is None or (r.get("score") or "") == "":
            return None
        return r["score"] == "1"

    pattern = {i: tuple(sc(r, i) for _n, r, _t in lanes) for i in every}

    groups = defaultdict(list)
    for i, pat in pattern.items():
        known = [p for p in pat if p is not None]
        if not known:
            groups["unscored"].append(i)
            continue
        flips = sum(1 for a, b in zip(known, known[1:]) if a != b)
        if all(known):
            groups["always solved"].append(i)
        elif not any(known):
            groups["never solved"].append(i)
        elif flips > 1:
            groups["unstable"].append(i)
        elif known[0] is False and known[-1] is True:
            groups["recovered"].append(i)
        elif known[0] is True and known[-1] is False:
            groups["regressed"].append(i)
        else:
            groups["unstable"].append(i)

    L = []
    L.append(f"# {args.title}")
    L.append("")
    L.append("Spider 2.0-Lite BigQuery split: 204 instances (`bq###` 179, `ga###` 25) "
             "across 69 databases, `Qwen/Qwen3.6-35B-A3B` on one H200, greedy "
             "(temperature 0), `--max-steps 60` except the baseline's 40.")
    L.append("")

    # ── headline ──────────────────────────────────────────────────────────
    L.append("## Lanes")
    L.append("")
    L.append("| lane | configuration | correct | n | accuracy | 95% CI |")
    L.append("|---|---|---:|---:|---:|---:|")
    cfgs = {
        "bq_v2": "baseline (40 steps, truncating schema dump, dead `find_value`)",
        "bq_v3": "+ 5 harness fixes, 60 steps",
        "bq_v3r": "+ gated output-shape rubric",
        "bq_v3s": "+ catalog retrieval (`search_context`, k=16, additive)",
    }
    for n, run, _t in lanes:
        c = sum(1 for r in run.values() if r.get("score") == "1")
        k = len([r for r in run.values() if (r.get("score") or "") != ""])
        pct = 100.0 * c / k
        ci = 1.96 * (pct * (100 - pct) / k) ** 0.5
        L.append(f"| `{n}` | {cfgs.get(n, '')} | {c} | {k} | **{pct:.1f}%** "
                 f"| ±{ci:.1f} |")
    L.append("")
    L.append("Differences of fewer than about 14 questions sit inside these "
             "intervals. Read the flip counts, not the net.")
    L.append("")

    # ── pattern groups ────────────────────────────────────────────────────
    L.append("## Questions by pattern across the lanes")
    L.append("")
    L.append("| group | n | share | meaning |")
    L.append("|---|---:|---:|---|")
    meaning = {
        "always solved": "right in every lane; carries no signal about any change",
        "never solved": "wrong in every lane; the residual difficulty and the ceiling",
        "recovered": f"wrong in `{base}`, right in `{best}` — what the work bought",
        "regressed": f"right in `{base}`, wrong in `{best}` — the cost of the work",
        "unstable": "flips more than once; temperature-0 sampling variance",
        "unscored": "no score in any lane",
    }
    tot = len(every)
    for g in ("always solved", "never solved", "recovered", "regressed",
              "unstable", "unscored"):
        if not groups[g]:
            continue
        L.append(f"| **{g}** | {len(groups[g])} | {100 * len(groups[g]) / tot:.0f}% "
                 f"| {meaning[g]} |")
    L.append("")
    stable = len(groups["always solved"]) + len(groups["never solved"])
    L.append(f"{stable} of {tot} questions ({100 * stable / tot:.0f}%) have the same "
             f"outcome in all four lanes. Every claim in this report rests on the "
             f"{tot - stable} that move.")
    L.append("")

    # ── never solved, by database ─────────────────────────────────────────
    L.append(f"### Never solved in any lane ({len(groups['never solved'])})")
    L.append("")
    L.append("Grouped by database, worst first. A database that never yields a "
             "correct answer across four configurations is a candidate for a "
             "schema-specific problem rather than a question-specific one.")
    L.append("")
    byd = Counter(lanes[0][1].get(i, {}).get("db", "?")
                  for i in groups["never solved"])
    L.append("| database | never solved | total in lane |")
    L.append("|---|---:|---:|")
    totd = Counter(r.get("db", "?") for r in lanes[0][1].values())
    for db, k in byd.most_common(15):
        L.append(f"| `{db}` | {k} | {totd[db]} |")
    L.append("")

    # ── per-question table ────────────────────────────────────────────────
    L.append("## Per-question outcomes")
    L.append("")
    L.append("`1` correct · `.` wrong · `-` not scored. "
             "`steps`/`GiB` are from the best lane that recorded them.")
    L.append("")
    L.append("| instance | database | " + " | ".join(f"`{n}`" for n in names)
             + " | pattern | steps | GiB | detail (best lane) |")
    L.append("|---|---|" + "|".join([":-:"] * len(names))
             + "|---|---:|---:|---|")
    gof = {i: g for g, ids in groups.items() for i in ids}
    for i in every:
        cells = []
        for _n, run, _t in lanes:
            v = sc(run, i)
            cells.append("1" if v else ("." if v is False else "-"))
        r_best = next((run[i] for _n, run, _t in reversed(lanes)
                       if i in run and (run[i].get("score") or "") != ""), {})
        db = r_best.get("db") or lanes[0][1].get(i, {}).get("db", "?")
        steps = r_best.get("steps") or ""
        try:
            gib = f"{float(r_best.get('scan_bytes') or 0) / GiB:.1f}"
        except ValueError:
            gib = ""
        det = (r_best.get("score_detail") or "")[:34]
        L.append(f"| `{i}` | {db[:26]} | " + " | ".join(cells)
                 + f" | {gof.get(i, '')} | {steps} | {gib} | {det} |")
    L.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {args.out} ({len(L)} lines)")
    for g in ("always solved", "never solved", "recovered", "regressed",
              "unstable", "unscored"):
        if groups[g]:
            print(f"  {g:16s} {len(groups[g]):4d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
