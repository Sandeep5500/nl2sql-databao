#!/usr/bin/env python3
"""One-time per-database stats enrichment for the BigQuery lane.

SQLite's describe_table runs COUNT(*) and per-column COUNT(DISTINCT)/null counts
live, on every call, because it is free (db.py:187). BigQuery's equivalent
(lite_catalog.LiteCatalog.describe) cannot: the same pattern on these tables can be
tens of GiB per call, repeated every time the agent asks. So this runs it ONCE per
table, caches DIR/<db>.stats.json, and run_benchmark.py --bq-stats DIR folds it into
describe_table for free.

Distinct counts use APPROX_COUNT_DISTINCT (HyperLogLog++, ~1% error) and columns are
read in chunks so a 3,000-column census table stays within query limits. Row counts
are plain COUNT(*), which BigQuery answers from metadata (0 bytes) on native tables.

    --estimate                 dry runs only -- free -- prices both column policies
    --limit-dbs N / --db X     calibration slice
    --policy id|all            id: STRING/INT64/NUMERIC/DATE/TIME*/BOOL/BYTES (default)
                               all: also FLOAT64 (75% of all columns, mostly measures)

This is REAL SPEND without --estimate. Check scripts/bq_spend.py after a slice.
"""

import argparse
import json
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl2sql.bigquery_db import BigQueryConfig, build_credentials, human_bytes  # noqa: E402
from nl2sql.config import CONTEXT_DIR, DATA_SOURCES, SPIDER2_LITE  # noqa: E402
from nl2sql.lite_catalog import LiteCatalog  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_benchmark import load_questions  # noqa: E402

ID_TYPES = {"STRING", "INT64", "INTEGER", "NUMERIC", "BIGNUMERIC", "DATE",
            "DATETIME", "TIMESTAMP", "TIME", "BOOL", "BOOLEAN", "BYTES"}
ALL_TYPES = ID_TYPES | {"FLOAT64", "FLOAT"}
CHUNK = 150


def base_type(t: str) -> str:
    return re.split(r"[<(]", t or "")[0].strip().upper()


def eligible(columns, policy: str) -> list[str]:
    allowed = ALL_TYPES if policy == "all" else ID_TYPES
    return [c for c, ty in columns if base_type(ty) in allowed]


def chunks(xs, n):
    return [xs[i:i + n] for i in range(0, len(xs), n)]


class BQ:
    def __init__(self, cfg):
        from google.cloud import bigquery
        self.bq = bigquery
        self.client = bigquery.Client(project=cfg.project,
                                      credentials=build_credentials(cfg))
        self.labels = {"app": "nl2sql", "run": "enrich_bq_stats",
                       "cost_center": cfg.cost_center}

    def dry(self, sql: str) -> int:
        job = self.client.query(sql, job_config=self.bq.QueryJobConfig(
            dry_run=True, use_query_cache=False, labels=self.labels))
        return int(job.total_bytes_processed or 0)

    def run(self, sql: str, est_bytes: int):
        # Billing rounds up (to whole MiB, 10 MiB minimum per table), so a cap equal
        # to the dry-run estimate is refused; headroom still stops a runaway query.
        cap = int(est_bytes * 1.1) + 20 * 1024 ** 2
        job = self.client.query(sql, job_config=self.bq.QueryJobConfig(
            use_query_cache=True, labels=self.labels, maximum_bytes_billed=cap))
        rows = list(job.result())
        return rows[0], int(job.total_bytes_billed or 0)


def stats_sql(fullname, cols):
    aggs = ", ".join(f"APPROX_COUNT_DISTINCT(`{c}`) AS d{i}, "
                     f"COUNTIF(`{c}` IS NULL) AS n{i}" for i, c in enumerate(cols))
    return f"SELECT {aggs} FROM `{fullname}`"


def valid_chunks(bq, fullname, cols):
    """Dry-run each chunk; split a failing chunk until the bad column is isolated.
    Free (dry runs). Returns [(cols, est_bytes)] and the columns BigQuery refused."""
    out, refused = [], []
    stack = chunks(cols, CHUNK)
    while stack:
        part = stack.pop()
        try:
            out.append((part, bq.dry(stats_sql(fullname, part))))
        except Exception:
            if len(part) == 1:
                refused.append(part[0])
            else:
                mid = len(part) // 2
                stack += [part[:mid], part[mid:]]
    return out, refused


def target_tables(source, only_dbs, limit_dbs):
    questions = load_questions([DATA_SOURCES[source]])
    dbs = sorted({q["db"] for q in questions})
    if only_dbs:
        dbs = [d for d in dbs if d in only_dbs]
    if limit_dbs:
        dbs = dbs[:limit_dbs]
    return dbs


def estimate(bq, dbs, threads, report_path):
    """Free: bytes each policy would scan, per database and per table."""
    def one(args):
        db, fullname, cols_id, cols_all = args
        res = {"db": db, "table": fullname}
        for name, cols in (("id", cols_id), ("all", cols_all)):
            if not cols:
                res[name] = 0
                continue
            sql = "SELECT " + ", ".join(f"`{c}`" for c in cols) + f" FROM `{fullname}`"
            try:
                res[name] = bq.dry(sql)
            except Exception as e:
                res[name] = None
                res[f"{name}_err"] = " ".join(str(e).split())[:160]
        return res

    work = []
    for db in dbs:
        cat = LiteCatalog(db, "bigquery", SPIDER2_LITE)
        for fullname in sorted(cat.tables):
            t = cat.table(fullname)
            work.append((db, t.fullname, eligible(t.columns, "id"),
                         eligible(t.columns, "all")))
    print(f"dry-running {len(work)} tables x 2 policies with {threads} threads ...",
          flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(threads) as ex:
        results = list(ex.map(one, work))
    print(f"done in {time.time() - t0:.0f}s")
    Path(report_path).write_text(json.dumps(results, indent=1), encoding="utf-8")

    GiB = 1024 ** 3
    for policy in ("id", "all"):
        per_db = defaultdict(int)
        errs = sum(1 for r in results if r.get(policy) is None)
        for r in results:
            per_db[r["db"]] += r.get(policy) or 0
        tot = sum(per_db.values())
        print(f"\npolicy={policy}: {human_bytes(tot)} total  "
              f"(~${tot / 1024 ** 4 * 6.25:.2f} on-demand), {errs} dry-run errors")
        for cap in (1, 2, 5, 10, 50):
            under = [r.get(policy) or 0 for r in results
                     if (r.get(policy) or 0) <= cap * GiB]
            n_over = len(results) - len(under)
            print(f"  per-table cap {cap:>2} GiB: {human_bytes(sum(under))} "
                  f"(~${sum(under) / 1024 ** 4 * 6.25:.2f}), {n_over} tables skipped")
        top = sorted(per_db.items(), key=lambda kv: -kv[1])[:8]
        print("  heaviest dbs: " + ", ".join(f"{d}={human_bytes(b)}" for d, b in top))
    print(f"\nper-table report: {report_path}")


def enrich(bq, dbs, args):
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = int(args.max_gib_per_table * 1024 ** 3)
    budget = int(args.budget_gib * 1024 ** 3)
    state = {"spent": 0, "reserved": 0, "stop": False}
    counts = defaultdict(int)
    lock = threading.Lock()

    for db in dbs:
        if state["stop"]:
            break
        cat = LiteCatalog(db, "bigquery", SPIDER2_LITE)
        out_path = out_dir / f"{db}.stats.json"
        stats = {}
        if out_path.exists():
            try:
                stats = json.loads(out_path.read_text(encoding="utf-8"))
            except ValueError:
                stats = {}
        todo = [n for n in sorted(cat.tables) if cat.table(n).fullname not in stats]
        print(f"\n[{db}] {len(cat.tables)} tables, {len(todo)} to do", flush=True)

        def one(name):
            t = cat.table(name)
            fullname = t.fullname
            cols = eligible(t.columns, args.policy)
            try:
                rc_bytes = bq.dry(f"SELECT COUNT(*) AS n FROM `{fullname}`")
            except Exception as e:
                with lock:
                    counts["count_failed"] += 1
                print(f"  {fullname}: count dry-run failed: {str(e)[:100]}")
                return
            parts, refused = valid_chunks(bq, fullname, cols) if cols else ([], [])
            col_est = sum(b for _, b in parts)
            skip_cols = col_est > cap
            est = rc_bytes + (0 if skip_cols else col_est)
            # reserve before sending anything, so concurrent tables cannot jointly
            # overshoot the run budget
            with lock:
                if state["stop"] or state["spent"] + state["reserved"] + est > budget:
                    state["stop"] = True
                    return
                state["reserved"] += est
            billed_total = 0
            try:
                row, billed = bq.run(f"SELECT COUNT(*) AS n FROM `{fullname}`",
                                     rc_bytes)
                billed_total += billed
                entry = {"row_count": int(row["n"]), "columns": {}}
                if skip_cols:
                    entry["stats_skipped"] = (f"column stats would scan "
                                              f"{human_bytes(col_est)}")
                else:
                    for part_cols, b in parts:
                        r, billed = bq.run(stats_sql(fullname, part_cols), b)
                        billed_total += billed
                        for i, c in enumerate(part_cols):
                            entry["columns"][c] = {
                                "approx_distinct": int(r[f"d{i}"]),
                                "nulls": int(r[f"n{i}"])}
                if refused:
                    entry["refused_columns"] = refused
            except Exception as e:
                # not written to stats, so the next invocation retries it
                with lock:
                    state["reserved"] -= est
                    state["spent"] += billed_total
                    counts["query_failed"] += 1
                print(f"  {fullname}: query failed, will retry next run "
                      f"({' '.join(str(e).split())[:140]})")
                return
            with lock:
                state["reserved"] -= est
                state["spent"] += billed_total
                counts["row_count_only" if skip_cols else "enriched"] += 1
                counts["refused_columns"] += len(refused)
                stats[fullname] = entry
                if len(stats) % 25 == 0:
                    out_path.write_text(json.dumps(stats, indent=1),
                                        encoding="utf-8")

        with ThreadPoolExecutor(args.threads) as ex:
            list(ex.map(one, todo))
        out_path.write_text(json.dumps(stats, indent=1), encoding="utf-8")
        print(f"[{db}] wrote {out_path.name}; billed so far "
              f"{human_bytes(state['spent'])}", flush=True)
    if state["stop"]:
        print(f"\nBUDGET: stopped under the {args.budget_gib} GiB run budget "
              f"({human_bytes(state['spent'])} billed). Re-run to continue; "
              f"finished tables are kept.")
    return summary(counts, state["spent"])


def summary(counts, spent):
    print("\n" + "-" * 50)
    print(f"billed this run: {human_bytes(spent)} (~${spent / 1024 ** 4 * 6.25:.2f})")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    print("cross-check with BigQuery's own accounting: scripts/bq_spend.py --hours 2")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="spider2_lite_bq")
    ap.add_argument("--db", action="append", help="only this database (repeatable)")
    ap.add_argument("--limit-dbs", type=int, default=0)
    ap.add_argument("--estimate", action="store_true",
                    help="dry runs only (free): price both policies, write a report")
    ap.add_argument("--report", default="enrich_estimate.json")
    ap.add_argument("--policy", choices=["id", "all"], default="id")
    ap.add_argument("--max-gib-per-table", type=float, default=2.0,
                    help="above this a table gets its row count only")
    ap.add_argument("--budget-gib", type=float, default=50.0,
                    help="stop once this run has been billed this many GiB")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--out-dir", default=str(CONTEXT_DIR / "bigquery_stats"))
    args = ap.parse_args()

    cfg = BigQueryConfig.load()
    print(cfg.redacted())
    bq = BQ(cfg)
    dbs = target_tables(args.source, set(args.db or []), args.limit_dbs)
    print(f"{len(dbs)} databases")
    if args.estimate:
        return estimate(bq, dbs, args.threads, args.report)
    return enrich(bq, dbs, args)


if __name__ == "__main__":
    raise SystemExit(main())
