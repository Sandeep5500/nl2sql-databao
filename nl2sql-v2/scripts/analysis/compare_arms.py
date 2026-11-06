"""Paired comparison of a control and a treatment arm on the same questions.

Each arm is one or more run dirs (results/<tag>/all.csv + traces/). With k samples
per arm, a question's score is its mean over samples (pass@1 = mean of that).

Reports: accuracy with CI, paired flips, an exact sign test on the questions whose
score differs, a bootstrap CI on the paired difference, and the exposure split --
treatment episodes that never saw a stat (none in the prompt, none in any tool
result) had the control's inputs, so their movement is the run-to-run noise floor.

    python compare_arms.py --c results/cal_C --t results/cal_T [--hist results/bq_v3r_run.csv]
"""
import argparse
import csv
import json
import math
import random
from pathlib import Path

ROOT = Path(r"C:\Users\rohin\Documents\CMU\Capstone\nl2sql-databao")


def load_arm(dirs):
    runs = []
    for d in dirs:
        d = Path(d)
        rows = {r["instance_id"]: r for r in csv.DictReader(
            open(d / "all.csv", newline="", encoding="utf-8"))}
        traces = {}
        for p in (d / "traces").glob("*.json"):
            try:
                traces[p.stem] = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                pass
        runs.append((rows, traces))
    return runs


EXPOSURE = "stats"


def saw_stats(trace):
    if not trace:
        return False
    if EXPOSURE == "row_check":
        return any("row_check" in s for s in trace.get("trace", []))
    if "approx_distinct=" in (trace.get("system") or ""):
        return True
    return any("approx_distinct=" in str(s.get("result", ""))
               for s in trace.get("trace", []))


def sign_test(wins, losses):
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def ci95(p, n):
    return 1.96 * math.sqrt(max(p * (1 - p), 1e-12) / n) if n else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--c", nargs="+", required=True)
    ap.add_argument("--t", nargs="+", required=True)
    ap.add_argument("--hist", help="historical single-run CSV, e.g. results/bq_v3r_run.csv")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--exposure", choices=["stats", "row_check"], default="stats",
                    help="what counts as a treatment episode being exposed")
    args = ap.parse_args()
    global EXPOSURE
    EXPOSURE = args.exposure

    C, T = load_arm(args.c), load_arm(args.t)
    ids = sorted(set.intersection(*[set(r) for r, _ in C + T]))
    score = lambda runs, i: sum(r[i]["score"] == "1" for r, _ in runs) / len(runs)
    sc = {i: score(C, i) for i in ids}
    st = {i: score(T, i) for i in ids}
    n = len(ids)
    pc, pt = sum(sc.values()) / n, sum(st.values()) / n
    print(f"questions in all runs: {n}   samples: control={len(C)} treatment={len(T)}")
    print(f"control   pass@1 {100 * pc:5.1f}%  (+/-{100 * ci95(pc, n):.1f})")
    print(f"treatment pass@1 {100 * pt:5.1f}%  (+/-{100 * ci95(pt, n):.1f})")
    print(f"paired difference: {100 * (pt - pc):+.1f} points")

    wins = [i for i in ids if st[i] > sc[i]]
    losses = [i for i in ids if st[i] < sc[i]]
    print(f"questions better/worse in treatment: +{len(wins)} / -{len(losses)}  "
          f"sign-test p={sign_test(len(wins), len(losses)):.3f}")
    rng = random.Random(0)
    diffs = [st[i] - sc[i] for i in ids]
    boots = sorted(sum(rng.choice(diffs) for _ in ids) / n for _ in range(4000))
    print(f"bootstrap 95% CI on the difference: [{100 * boots[100]:+.1f}, "
          f"{100 * boots[3899]:+.1f}] points")

    # exposure split (treatment sample 1's traces decide exposure per question)
    exposed = {i for i in ids if any(saw_stats(tr.get(i)) for _, tr in T)}
    for name, group in (("saw stats", exposed), ("never saw a stat", set(ids) - exposed)):
        g = sorted(group)
        if not g:
            print(f"  {name}: 0 questions")
            continue
        w = sum(st[i] > sc[i] for i in g)
        l = sum(st[i] < sc[i] for i in g)
        print(f"  {name:17s} n={len(g):3d}  control {100 * sum(sc[i] for i in g) / len(g):5.1f}%"
              f"  treatment {100 * sum(st[i] for i in g) / len(g):5.1f}%  flips +{w}/-{l}")

    def agg(runs, key):
        return sum(float(r[i].get(key) or 0) for r, _ in runs for i in ids) / len(runs)
    print(f"scan per run: control {agg(C, 'scan_bytes') / 1024 ** 3:.1f} GiB, "
          f"treatment {agg(T, 'scan_bytes') / 1024 ** 3:.1f} GiB")
    print(f"mean steps: control {agg(C, 'steps') / n:.1f}, treatment {agg(T, 'steps') / n:.1f};"
          f"  mean wall: control {agg(C, 'wall_seconds') / n:.0f}s, "
          f"treatment {agg(T, 'wall_seconds') / n:.0f}s")
    for name, runs in (("control", C), ("treatment", T)):
        det = {}
        for r, _ in runs:
            for i in ids:
                if r[i]["score"] != "1":
                    k = (r[i]["score_detail"] or r[i]["status"] or "?")[:24]
                    det[k] = det.get(k, 0) + 1
        print(f"  {name} failure details: " +
              ", ".join(f"{k}={v}" for k, v in sorted(det.items(), key=lambda kv: -kv[1])[:6]))

    if args.hist:
        h = {r["instance_id"]: r for r in csv.DictReader(
            open(args.hist, newline="", encoding="utf-8"))}
        hid = [i for i in ids if i in h]
        hs = {i: float(h[i]["score"] == "1") for i in hid}
        print(f"\nvs historical ({Path(args.hist).name}) on {len(hid)} shared questions: "
              f"hist {100 * sum(hs.values()) / len(hid):.1f}%  "
              f"control {100 * sum(sc[i] for i in hid) / len(hid):.1f}%  "
              f"treatment {100 * sum(st[i] for i in hid) / len(hid):.1f}%")
        for name, s in (("control", sc), ("treatment", st)):
            w = sum(s[i] > hs[i] for i in hid)
            l = sum(s[i] < hs[i] for i in hid)
            print(f"  {name} vs hist flips: +{w}/-{l}")

    if args.show:
        print("\ngained:", wins)
        print("lost:  ", losses)


if __name__ == "__main__":
    main()
