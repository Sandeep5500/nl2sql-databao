"""LOCKED EVALUATION for the RSI loop. Not editable by the proposer.

Computes the fitness report for one run, or an accept/reject decision for an
arm against a baseline. Two standing rules are built in:

  1. ACCURACY IS A FLOOR, NOT A TARGET. Mechanism metrics are the fitness
     signal because accuracy's MDE is hopeless at these sample sizes, but every
     mechanism metric has a degenerate optimum (minimise fallback by submitting
     the first query instantly). So an arm whose accuracy drops beyond the noise
     band is REJECTED however good its mechanism numbers look.

  2. NO SINGLE METRIC DECIDES. The report prints all of them, and the verdict
     names which rule fired.

Usage:
    python rsi_eval.py --run  results/baseline_*.csv --traces logs/traces/baseline_*
    python rsi_eval.py --base results/base_*.csv --base-traces logs/traces/base_* \
                       --arm  results/arm_*.csv  --arm-traces  logs/traces/arm_* \
                       --noise 0.04
"""
import argparse, csv, glob, json, os, re, statistics as st, sys
from collections import Counter, defaultdict
from math import comb

# ---------------------------------------------------------------- loading ---

def load_rows(pattern):
    """every episode row across a run's shard CSVs"""
    out = []
    for f in sorted(glob.glob(pattern)):
        try:
            out.extend(csv.DictReader(open(f)))
        except Exception:
            continue
    return [r for r in out if r.get("instance_id")]


def load_traces(pattern):
    """instance_id -> list of trace dicts"""
    out = defaultdict(list)
    for d in sorted(glob.glob(pattern)):
        if not os.path.isdir(d):
            continue
        for f in sorted(glob.glob(os.path.join(d, "*.json"))):
            try:
                t = json.load(open(f))
            except Exception:
                continue
            if t.get("instance_id"):
                out[t["instance_id"]].append(t)
    return out

# ---------------------------------------------------------------- metrics ---

def _norm_sql(s):
    s = re.sub(r"--[^\n]*", " ", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _is_probe(sql):
    """a diagnostic peek rather than an answer-shaped aggregate"""
    s = _norm_sql(sql)
    if not s or "group by" in s:
        return False
    if re.search(r"\bcount\s*\(", s):
        return True
    if re.search(r"\bselect\s+distinct\b", s) and " limit " in s:
        return True
    if re.search(r"\blimit\s+\d+\b", s) and not re.search(r"\b(sum|avg|min|max)\s*\(", s):
        return True
    return False


def solved(r):
    return (r.get("score") or "0").strip() not in ("", "0")


def metrics(rows, traces, max_steps=30):
    m = {}
    n = len(rows)
    if not n:
        return {"episodes": 0}
    m["episodes"] = n
    m["questions"] = len({r["instance_id"] for r in rows})

    # --- the floor ---
    m["accuracy"] = sum(1 for r in rows if solved(r)) / n
    by_q = defaultdict(list)
    for r in rows:
        by_q[r["instance_id"]].append(solved(r))
    m["pass_any"] = sum(1 for v in by_q.values() if any(v)) / len(by_q)

    # --- mechanism ---
    st_ = [int(r["steps"]) for r in rows if (r.get("steps") or "").isdigit()]
    m["mean_steps"] = st.mean(st_) if st_ else float("nan")
    m["median_steps"] = st.median(st_) if st_ else float("nan")
    m["at_step_cap"] = (sum(1 for s in st_ if s >= max_steps) / len(st_)) if st_ else float("nan")
    stat = Counter((r.get("status") or "").strip() for r in rows)
    m["fallback_rate"] = stat.get("fallback", 0) / n
    m["submitted_rate"] = stat.get("submitted", 0) / n
    m["error_rate"] = sum(v for k, v in stat.items()
                          if k not in ("submitted", "fallback")) / n
    w = [float(r["wall_seconds"]) for r in rows
         if (r.get("wall_seconds") or "").replace(".", "", 1).isdigit()]
    m["mean_wall_s"] = st.mean(w) if w else float("nan")

    # --- from traces: the doubt-spiral signature ---
    last5, dupes, nsql = [], [], []
    for iid, ts in traces.items():
        for t in ts:
            sqls = [e["args"].get("sql", "") for e in t.get("trace", [])
                    if e.get("tool") == "run_sql_query" and isinstance(e.get("args"), dict)]
            if not sqls:
                continue
            nsql.append(len(sqls))
            tail = sqls[-5:]
            last5.append(sum(map(_is_probe, tail)) / len(tail))
            fps = [_norm_sql(s) for s in sqls]
            dupes.append(len(fps) - len(set(fps)))
    m["probe_share_last5"] = st.mean(last5) if last5 else float("nan")
    m["dup_queries"] = st.mean(dupes) if dupes else float("nan")
    m["mean_sql_calls"] = st.mean(nsql) if nsql else float("nan")
    return m

# ------------------------------------------------------------- statistics ---

def fisher(a, b, c, d):
    n = a + b + c + d
    if n == 0:
        return 1.0
    r1, r2, c1 = a + b, c + d, a + c

    def p(x):
        return comb(r1, x) * comb(r2, c1 - x) / comb(n, c1)
    p0 = p(a)
    tot = 0.0
    for x in range(max(0, c1 - r2), min(r1, c1) + 1):
        if p(x) <= p0 + 1e-12:
            tot += p(x)
    return tot


def mcnemar(base_rows, arm_rows):
    """paired on instance_id: b = base right/arm wrong, c = base wrong/arm right"""
    bs = {r["instance_id"]: solved(r) for r in base_rows}
    ar = {r["instance_id"]: solved(r) for r in arm_rows}
    shared = set(bs) & set(ar)
    b = sum(1 for i in shared if bs[i] and not ar[i])
    c = sum(1 for i in shared if ar[i] and not bs[i])
    nn = b + c
    if nn == 0:
        return b, c, 1.0, len(shared)
    p = sum(comb(nn, k) for k in range(0, min(b, c) + 1)) / (2 ** nn) * 2
    return b, c, min(1.0, p), len(shared)

# ----------------------------------------------------------------- report ---

ORDER = [("accuracy", "FLOOR  accuracy (per episode)", "{:.3f}"),
         ("pass_any", "       pass@any lane", "{:.3f}"),
         ("fallback_rate", "MECH   fallback rate", "{:.3f}"),
         ("at_step_cap", "MECH   episodes at the step cap", "{:.3f}"),
         ("probe_share_last5", "DIAG   probe share, last 5 queries *", "{:.3f}"),
         ("dup_queries", "MECH   duplicate queries per episode", "{:.2f}"),
         ("submitted_rate", "       submitted (vs salvaged)", "{:.3f}"),
         ("error_rate", "       errored", "{:.3f}"),
         ("mean_steps", "       mean steps", "{:.1f}"),
         ("mean_sql_calls", "       mean SQL calls", "{:.1f}"),
         ("mean_wall_s", "DIAG   mean wall seconds *", "{:.0f}")]


def show(name, m):
    print(f"\n=== {name} ===")
    print(f"  episodes {m.get('episodes',0)}  questions {m.get('questions',0)}")
    for k, label, fmt in ORDER:
        v = m.get(k)
        if v is None:
            continue
        print(f"  {label:<38}{fmt.format(v)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run"); ap.add_argument("--traces", default="")
    ap.add_argument("--base"); ap.add_argument("--base-traces", default="")
    ap.add_argument("--arm"); ap.add_argument("--arm-traces", default="")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--noise", type=float, default=0.03,
                    help="measured run-to-run accuracy band. 0.03 is the MAX pairwise "
                         "difference between 4 lanes of one identical q36re config "
                         "(mean 0.016, sd 0.012), measured 2026-11-18.")
    a = ap.parse_args()

    if a.run:
        m = metrics(load_rows(a.run), load_traces(a.traces) if a.traces else {}, a.max_steps)
        show(a.run, m)
        return

    if not (a.base and a.arm):
        sys.exit("give --run, or both --base and --arm")

    br, ar_ = load_rows(a.base), load_rows(a.arm)
    if not br or not ar_:
        sys.exit(f"no episodes loaded (base={len(br)}, arm={len(ar_)}). "
                 f"Check the globs -- quote them so the shell does not expand them, "
                 f"and point at the directory that really holds the shard CSVs.")
    bm = metrics(br, load_traces(a.base_traces) if a.base_traces else {}, a.max_steps)
    am = metrics(ar_, load_traces(a.arm_traces) if a.arm_traces else {}, a.max_steps)
    show("BASELINE", bm); show("ARM", am)

    print("\n=== deltas ===")
    print(f"  {'metric':<40}{'base':>9}{'arm':>9}{'delta':>9}")
    for k, label, fmt in ORDER:
        if k in bm and k in am and bm[k] == bm[k] and am[k] == am[k]:
            print(f"  {label:<40}{bm[k]:>9.3f}{am[k]:>9.3f}{am[k]-bm[k]:>+9.3f}")

    b, c, p, shared = mcnemar(br, ar_)

    # An arm must be the SAME questions as its baseline. If it is not, the
    # accuracy comparison is between two question sets, not between two
    # harnesses, and the noise band (measured run-to-run on fixed questions)
    # does not apply. Refuse rather than print a verdict that looks valid.
    bq, aq = {r["instance_id"] for r in br}, {r["instance_id"] for r in ar_}
    if shared == 0:
        sys.exit("REFUSING TO JUDGE: base and arm share no questions. An arm is "
                 "the same questions under a changed harness; comparing different "
                 "question sets measures the sets, not the change.")
    overlap = shared / max(len(bq | aq), 1)
    if overlap < 0.9:
        print(f"\n  !! WARNING: base and arm overlap on only {overlap:.0%} of questions "
              f"({shared} shared, {len(bq-aq)} base-only, {len(aq-bq)} arm-only).")
        print("     The accuracy floor assumes fixed questions. Treat the verdict as void.")

    print(f"\n=== accuracy, paired on {shared} shared questions ===")
    print(f"  base right / arm wrong : {b}")
    print(f"  base wrong / arm right : {c}")
    print(f"  McNemar exact p        : {p:.4f}")

    nb, na = len(br), len(ar_)
    fb_p = fisher(int(bm['fallback_rate']*nb), nb-int(bm['fallback_rate']*nb),
                  int(am['fallback_rate']*na), na-int(am['fallback_rate']*na))
    print(f"  fallback-rate Fisher p : {fb_p:.2e}")

    print("\n=== VERDICT ===")
    acc_drop = bm["accuracy"] - am["accuracy"]
    if acc_drop > a.noise:
        print(f"  REJECT -- accuracy fell {acc_drop:.3f}, beyond the {a.noise:.3f} noise band.")
        print("  Rule 1: a mechanism gain never buys an accuracy regression.")
    elif am["fallback_rate"] < bm["fallback_rate"] and fb_p < 0.01:
        print(f"  ACCEPT -- fallback {bm['fallback_rate']:.3f} -> {am['fallback_rate']:.3f} "
              f"(p={fb_p:.1e}), accuracy within noise.")
    elif c > b and p < 0.05:
        print(f"  ACCEPT -- accuracy improved ({c} gained vs {b} lost, p={p:.3f}).")
    else:
        print("  NO CHANGE -- nothing moved beyond noise. Keep the baseline.")
    print("\n  * DIAG metrics are diagnostic only and never decide a verdict.")
    print("    Measured under a true null on synth (250 identical questions,")
    print("    identical config): probe share moved 0.031 and wall time 2.3x on")
    print("    noise alone, so both are as large as any plausible real effect.")
    print("\n  (Reminder: the loop may not edit this file. If a proposed change")
    print("   only improves a metric defined here, suspect the metric.)")


if __name__ == "__main__":
    main()
