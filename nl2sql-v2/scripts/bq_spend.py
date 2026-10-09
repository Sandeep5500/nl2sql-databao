#!/usr/bin/env python3
"""What has BigQuery actually billed us? Poll this during a run.

Reads INFORMATION_SCHEMA.JOBS_BY_PROJECT, which is Google's own accounting rather
than our estimate of it, so it catches anything our dry-run guard mis-predicted.
The query itself is metadata-only and free.

The number that matters is bytes BILLED (not processed): BigQuery bills a 10 MB
minimum per table and rounds up, and the free tier is 1 TiB of billed bytes a month.

    uv run python scripts/bq_spend.py                  # last 24h, by label
    uv run python scripts/bq_spend.py --hours 2 --by-instance
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl2sql.bigquery_db import BigQueryConfig, human_bytes

FREE_TIER_BYTES = 1024 ** 4          # 1 TiB of query processing per month
# on-demand pricing after the free tier, US multi-region
USD_PER_TIB = 6.25


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--region", default="region-us")
    ap.add_argument("--by-instance", action="store_true",
                    help="break down by the per-instance job label")
    ap.add_argument("--budget-tib", type=float, default=1.0,
                    help="warn past this many TiB billed in the window")
    args = ap.parse_args()

    cfg = BigQueryConfig.load()
    from google.cloud import bigquery
    from google.oauth2 import service_account
    creds = (service_account.Credentials.from_service_account_info(cfg.credentials_info)
             if cfg.credentials_info
             else service_account.Credentials.from_service_account_file(
                 cfg.credentials_path))
    client = bigquery.Client(project=cfg.project, credentials=creds)

    group = ("(SELECT value FROM UNNEST(labels) WHERE key = 'instance')"
             if args.by_instance else
             "(SELECT value FROM UNNEST(labels) WHERE key = 'run')")
    # JOBS_BY_USER covers the jobs this service account ran, which is all of ours,
    # and needs no permission beyond running queries. JOBS_BY_PROJECT would show the
    # whole project but requires bigquery.jobs.listAll, an extra IAM grant.
    def spend_sql(view: str) -> str:
        return f"""
    SELECT
      {group} AS bucket,
      COUNT(*)                                   AS jobs,
      COUNTIF(error_result IS NOT NULL)          AS failed,
      SUM(total_bytes_billed)                    AS billed,
      SUM(total_bytes_processed)                 AS processed,
      ROUND(SUM(total_slot_ms) / 1000.0, 1)      AS slot_seconds
    FROM `{cfg.project}.{args.region}.INFORMATION_SCHEMA.{view}`
    WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(),
                                        INTERVAL {int(args.hours * 60)} MINUTE)
      AND job_type = 'QUERY'
    GROUP BY bucket
    ORDER BY billed DESC NULLS LAST
    """

    rows, view_used = None, None
    for view in ("JOBS_BY_USER", "JOBS_BY_PROJECT"):
        try:
            rows = list(client.query(spend_sql(view)).result())
            view_used = view
            break
        except Exception as e:
            print(f"({view} unavailable: {' '.join(str(e).split())[:90]})")
    if rows is None:
        print()
        print("Could not read BigQuery's own accounting. Fall back to our "
              "per-instance numbers: sum the scan_bytes column of the run CSV.")
        return 1
    print(f"source: INFORMATION_SCHEMA.{view_used}")

    print(f"project {cfg.project}  |  last {args.hours:g}h  |  "
          f"{'per instance' if args.by_instance else 'per run tag'}")
    print(f"{'bucket':34s} {'jobs':>6s} {'failed':>7s} {'billed':>11s} "
          f"{'processed':>11s}")
    total_billed = 0
    for r in rows:
        billed = int(r["billed"] or 0)
        total_billed += billed
        print(f"{str(r['bucket'] or '(unlabelled)')[:34]:34s} {r['jobs']:6d} "
              f"{r['failed']:7d} {human_bytes(billed):>11s} "
              f"{human_bytes(r['processed'] or 0):>11s}")

    print(f"\ntotal billed in window : {human_bytes(total_billed)}")
    pct = 100.0 * total_billed / FREE_TIER_BYTES
    print(f"share of the 1 TiB free tier: {pct:.2f}%")
    overage = max(0, total_billed - FREE_TIER_BYTES)
    if overage:
        print(f"past the free tier by {human_bytes(overage)} "
              f"~= ${overage / 1024 ** 4 * USD_PER_TIB:.2f} on demand")
    if total_billed > args.budget_tib * 1024 ** 4:
        print(f"\nOVER BUDGET: more than {args.budget_tib} TiB billed. Stop the run "
              f"(modal app stop) or lower --max-bytes-per-query.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
