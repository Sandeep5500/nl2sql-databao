#!/usr/bin/env python3
"""Turn a Snowflake run's CSV into the numbers that decide whether the full run fits.

This is the cost gate: after the calibration slice, multiply measured spend per
instance by the full target size and compare to the quota BEFORE launching. Also
separates the three ways a run can score badly, which otherwise all look like
"the model was wrong":

    result_mismatch   the model answered and was wrong        <- a real result
    sf_timeout        the query was cancelled                 <- our warehouse size
    connect_failed    the database was not reachable          <- a grant problem

    uv run python scripts/report_spend.py ../results/snow_cal/all.csv
    uv run python scripts/report_spend.py ../results/snow_cal/all.csv --project-to 412
"""

import argparse
import csv
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def fnum(row, key):
    try:
        return float(row.get(key) or 0)
    except ValueError:
        return 0.0


def section(title):
    print("\n" + title)
    print("-" * len(title))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--project-to", type=int, default=412,
                    help="target set size to extrapolate to (default: the 412)")
    args = ap.parse_args()

    path = Path(args.csv_path)
    if not path.exists():
        raise SystemExit(f"no such results file: {path}")
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    if not rows:
        raise SystemExit(f"{path} has no rows")

    section(f"{path.name}: {len(rows)} instances")
    scored = [r for r in rows if (r.get("score") or "") != ""]
    correct = sum(1 for r in scored if r.get("score") == "1")
    if scored:
        pct = 100.0 * correct / len(scored)
        # binomial standard error, to keep single-run point estimates honest
        se = (pct * (100 - pct) / len(scored)) ** 0.5
        print(f"score: {correct}/{len(scored)} = {pct:.1f}%  (+/-{1.96 * se:.1f} at 95%)")

    section("why the failures failed")
    buckets = Counter()
    for r in rows:
        d = (r.get("score_detail") or "").strip()
        if r.get("score") == "1":
            buckets["correct"] += 1
        elif d.startswith("sf_timeout"):
            buckets["sf_timeout (our timeout/warehouse, NOT the model)"] += 1
        elif d.startswith("connect_failed"):
            buckets["connect_failed (grant/credentials, NOT the model)"] += 1
        elif d.startswith("no_gold"):
            buckets["no_gold_files (unscoreable: exclude from the denominator)"] += 1
        elif d == "result_mismatch":
            buckets["result_mismatch (a real model failure)"] += 1
        elif d:
            buckets[d[:48]] += 1
        else:
            buckets["(blank)"] += 1
    for k, n in buckets.most_common():
        print(f"  {n:4d}  {k}")
    artifact = sum(n for k, n in buckets.items()
                   if "NOT the model" in k)
    if artifact:
        share = 100.0 * artifact / len(rows)
        print(f"\n  {artifact} rows ({share:.0f}%) are infrastructure, not model "
              f"failures.")
        if share > 15:
            print("  WARNING: above ~15% this run measures our plumbing. Fix it "
                  "before publishing the number.")

    # BigQuery bills bytes scanned, so that column is the budget, not query count.
    scanned = [fnum(r, "scan_bytes") for r in rows if fnum(r, "scan_bytes") > 0]
    if scanned:
        section("bigquery scan volume (the billed quantity)")
        TiB = 1024.0 ** 4
        tot = sum(scanned)
        print(f"  instances that scanned: {len(scanned)}/{len(rows)}")
        print(f"  per instance : mean {statistics.mean(scanned)/1024**3:.2f}GiB  "
              f"median {statistics.median(scanned)/1024**3:.2f}GiB  "
              f"max {max(scanned)/1024**3:.2f}GiB")
        print(f"  total        : {tot/TiB:.3f} TiB")
        print(f"  free tier    : {100*tot/TiB:.1f}% of the 1 TiB monthly allowance")
        if len(scanned) < args.project_to:
            proj = statistics.mean(scanned) * args.project_to
            print(f"  projected to {args.project_to}: {proj/TiB:.2f} TiB "
                  f"({100*proj/TiB:.0f}% of free tier)")
        heavy = sorted(((fnum(r, "scan_bytes"), r["instance_id"], r["db"])
                        for r in rows if fnum(r, "scan_bytes") > 0), reverse=True)[:8]
        print("  heaviest instances:")
        for b, iid, db in heavy:
            print(f"    {iid:16s} {db[:26]:26s} {b/1024**3:8.2f}GiB")

    section("snowflake spend")
    q = [fnum(r, "sf_queries") for r in rows if fnum(r, "sf_queries") > 0]
    s = [fnum(r, "sf_seconds") for r in rows if fnum(r, "sf_queries") > 0]
    if not q:
        print("  no sf_queries recorded -- either this is not a Snowflake run, or "
              "nothing actually executed (an all-zero column is how a dead "
              "connection looks).")
        return 0
    print(f"  instances that ran queries: {len(q)}/{len(rows)}")
    print(f"  queries per instance : mean {statistics.mean(q):.1f}  "
          f"median {statistics.median(q):.0f}  max {max(q):.0f}")
    print(f"  warehouse seconds    : mean {statistics.mean(s):.1f}  "
          f"median {statistics.median(s):.1f}  max {max(s):.1f}")
    total_s = sum(s)
    print(f"  total warehouse time : {total_s / 60:.1f} min over {len(q)} instances")

    # an XSMALL warehouse bills 1 credit/hour while running; this is a floor, since
    # Snowflake bills a 60s minimum per resume
    cred = total_s / 3600.0
    print(f"  ~credits (XSMALL, no resume minimums): {cred:.2f}")

    section(f"projection to {args.project_to} instances")
    per = statistics.mean(s)
    proj_s = per * args.project_to
    print(f"  warehouse time : {proj_s / 3600:.1f} h")
    print(f"  ~credits       : {proj_s / 3600:.1f} (XSMALL floor)")
    print(f"  per pass@K lane: multiply by K")
    print("\n  Compare this to the quota before launching. If one pass does not fit,")
    print("  run a stratified subset spanning every db_id -- never a jsonl prefix.")

    section("per database")
    by_db = defaultdict(list)
    for r in rows:
        by_db[r.get("db", "?")].append(r)
    worst = sorted(by_db.items(),
                   key=lambda kv: -sum(fnum(r, "sf_seconds") for r in kv[1]))
    print(f"  {'database':28s} {'n':>4s} {'sec':>8s} {'correct':>8s}")
    for db, rs in worst[:12]:
        sec = sum(fnum(r, "sf_seconds") for r in rs)
        ok = sum(1 for r in rs if r.get("score") == "1")
        print(f"  {db[:28]:28s} {len(rs):4d} {sec:8.0f} {ok:8d}")
    if len(worst) > 12:
        print(f"  ... and {len(worst) - 12} more databases")
    print("\n  QUERY_TAG for the exact bill: "
          "SELECT query_tag, COUNT(*), SUM(credits_used_cloud_services), "
          "SUM(total_elapsed_time)/1000 FROM "
          "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY "
          "WHERE query_tag LIKE 'nl2sql/%' GROUP BY 1;")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
