"""Production rule check (Nov 19; documents/judge_results.md §14): the old production (one diff_cmp call per
ordered pair) against the new one (ask twice + superset rule; selection_eval.py NAME@U@V2), both computed from the
same samples, per set. bq17 also under the corrected labels of the Nov 18 gold audit (bq_corrected_labels.py) and
of the Nov 19 full audit (bq_audit_labels.py).

Sources: stored = the samples that chose the rule; fresh = 4 new samples per ordered pair (Nov 19, copied from Babel
~/judge-tmp/prod19/<dir>/ to results/prod_nov19/fetched/<dir>/); all = both pooled. A mixed pool without samples in
a source is left out of that source's totals (reported). Eval sets and judge calls are under results/ (not tracked).

usage (from nl2sql-v2/): python3 scripts/score_production_rule.py [stored|fresh|all ...]
"""
import json
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

from bq_corrected_labels import LENIENT, STRICT, lane_groups
from selection_eval import bootstrap, load_samples, pool_scores

R = Path(__file__).resolve().parents[2] / "results"
H = R / "prod_nov19"
I = R / "bq17/improve"
SEL = R / "selection_nov2026/selection_evalset.json"
RUNSETS = R / "runsets_nov18/runsets_evalset.json"
# name: (eval set, pool filter, questions, stored sources, fresh dir on Babel ~/judge-tmp/prod19/)
SETS = {
    "bq17": (R / "bq17/bq17_evalset.json", lambda e: True, 204,
             [R / "bq17/judges/35B_dc.jsonl", I / "judges/dev/rerun_dc.jsonl"], "bq17"),
    "earlier BQ": (SEL, lambda e: e["bench"] == "bq", 105,
                   [I / "judges/test/diff_cmp.jsonl", I / "fetched/r2/bq105/rerun_diff_cmp.complete.jsonl"], "bq105"),
    "q36rg": (SEL, lambda e: e.get("runset") == "q36rg", 135, [R / "selection_nov2026/judges/35B_dc.jsonl"], "q36rg"),
    "q36e": (RUNSETS, lambda e: e.get("runset") == "q36e", 135, [R / "runsets_nov18/judges/35B_dc.jsonl"], "runsets"),
    "q36x": (RUNSETS, lambda e: e.get("runset") == "q36x", 135, [R / "runsets_nov18/judges/35B_dc.jsonl"], "runsets"),
}
VIEWS = {"official": None, "strict (13)": STRICT, "lenient (13)": LENIENT}
# the Nov 19 audit of all 204 (bq_audit_labels.py)
FULL = (Path(__file__).resolve().parents[1] / "research_notes/Spider2 Lite BigQuery full label audit"
        / "corrected_labels_full.json")
if FULL.exists():
    _full = json.loads(FULL.read_text())
    VIEWS["strict (204)"] = {k: set(v) for k, v in _full["strict"].items()}
    VIEWS["no drift (204)"] = {k: set(v) for k, v in _full["strict_no_drift"].items()}
    VIEWS["lenient (204)"] = {k: set(v) for k, v in _full["lenient"].items()}


# questions mixed only under the corrected labels (results/bq17/audit/newly_mixed.py, not tracked), judged once on
# Nov 19 with the production settings; they are non-mixed officially, so they change only the corrected views
EXTRA = {"bq17": "newmixed"}


def fresh_files(d):
    return sorted((H / "fetched" / d).glob("calls_diff_cmp.jsonl")) + extra_files(d)


def extra_files(d):
    return sorted((H / "fetched" / EXTRA[d]).glob("calls_diff_cmp.jsonl")) if d in EXTRA else []


def relabel(groups, iid, fix, lg):
    groups = [list(g) for g in groups]
    if fix and iid in fix:
        for a in range(len(groups)):
            lanes = [l for l, g in lg.get(iid, {}).items() if g == a]
            if lanes:
                groups[a][1] = int(any(l in fix[iid] for l in lanes))
    return [tuple(g) for g in groups]


def health(d):
    """Fresh calls: count, no verdict, truncated, calls started more than once (redrawn after a preemption)."""
    out = []
    for f in fresh_files(d):
        rows = []
        for line in open(f):
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        rows = [r for r in rows if not r.get("retry")]
        starts = Counter()
        sf = f.with_name(f.stem + ".starts.jsonl")
        if sf.exists():
            for line in open(sf):
                try:
                    s = json.loads(line)
                except ValueError:
                    continue
                starts[(s.get("key"), s.get("first"), s.get("second"), s.get("sample"))] += 1
        redrawn = sum(1 for n in starts.values() if n > 1)
        out.append(f"{f.parent.name}: {len(rows)} calls, no verdict {sum(bool(r.get('error')) for r in rows)}, "
                   f"truncated {sum(bool(r.get('truncated')) for r in rows)}, redrawn {redrawn}")
    return out


def main():
    sources = sys.argv[1:] or ["stored", "fresh", "all"]
    lg = lane_groups()
    for src in sources:
        print(f"\n=== source: {src} ===")
        pooled = defaultdict(lambda: defaultdict(float))  # (view) -> iid -> new - old, mixed pools of all sets
        for name, (evp, keep, nq, stored, fdir) in SETS.items():
            files = {"stored": stored + extra_files(fdir), "fresh": fresh_files(fdir),
                     "all": stored + fresh_files(fdir)}[src]
            if not files:
                print(f"{name:10s} no samples yet")
                continue
            ev = json.loads(Path(evp).read_text())["pools"]
            samples = load_samples([str(p) for p in files])[0]
            for view, fix in VIEWS.items():
                if view != "official" and name != "bq17":
                    continue
                old = new = p4 = p1 = maj = 0.0
                missing, up, down, by_q = 0, 0, 0, defaultdict(float)
                n_pools = 0
                for k, e in ev.items():
                    if not keep(e):
                        continue
                    n_pools += 1
                    groups = relabel(e["groups"], e["iid"], fix, lg)
                    alive = [a for a, g in enumerate(groups) if g[0] > 0]
                    flags = [groups[a][1] for a in alive]
                    p4 += float(any(flags))
                    p1 += sum(groups[a][0] * groups[a][1] for a in alive) / 4
                    top = max(groups[a][0] for a in alive)
                    tied = [a for a in alive if groups[a][0] == top]
                    maj += sum(groups[a][1] for a in tied) / len(tied)
                    if len(alive) == 1 or all(flags) or not any(flags):
                        c = float(all(flags))
                        old += c
                        new += c
                        continue
                    if k not in samples:
                        missing += 1
                        continue
                    seed = zlib.crc32(k.encode())
                    o = pool_scores(groups, samples[k], seed=seed)[0]
                    w = pool_scores(groups, samples[k], seed=seed, rules=("U",), contains=e.get("contains", ()),
                                    votes=2)[0]
                    old += o
                    new += w
                    up += w > o + 1e-9
                    down += w < o - 1e-9
                    by_q[e["iid"]] += w - o
                    pooled[view][e["iid"]] += w - o
                assert n_pools == nq, (name, n_pools)
                lo, hi = bootstrap(by_q)
                print(f"{name:10s} {view:13s} old {old:6.1f} ({old / nq:5.1%})  new {new:6.1f} ({new / nq:5.1%})  "
                      f"diff {new - old:+5.1f} [{lo:+.1f}, {hi:+.1f}]  pools up/down {up}/{down}  | pass@1 {p1:5.1f} "
                      f"majority {maj:5.1f} pass@4 {p4:.0f}"
                      + (f"  ({missing} mixed pools without samples left out)" if missing else ""))
        lo, hi = bootstrap(pooled["official"])
        print(f"all five sets, mixed pools, official labels: new - old {sum(pooled['official'].values()):+.1f} "
              f"[{lo:+.1f}, {hi:+.1f}] (95%, clustered by question)")
    if "stored" not in sources or len(sources) > 1:
        print("\nfresh call health:")
        for d in sorted({v[4] for v in SETS.values()}):
            for line in health(d) or [f"{d}: not fetched"]:
                print("  " + line)


if __name__ == "__main__":
    main()
