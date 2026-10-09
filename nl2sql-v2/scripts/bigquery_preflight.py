#!/usr/bin/env python3
"""Check BigQuery access per database BEFORE spending GPU time on the lane.

The question this answers: Spider2's BigQuery databases live in several Google Cloud
projects, and a plain account only reaches the open ones (`bigquery-public-data` and
friends). Anything in a project we have not been granted scores 0 for a reason that
has nothing to do with the model, so the unreachable set has to come out of the
denominator up front rather than be discovered mid-run.

Every probe is a DRY RUN, so this costs nothing: BigQuery bills bytes processed, and
a dry run processes none. A dry run still resolves the table and checks permissions,
which is exactly what we want to know.

    uv run python scripts/bigquery_preflight.py
    uv run python scripts/bigquery_preflight.py --write-unreachable ../results/bq_unreachable.txt
"""

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql.bigquery_db import BigQueryConfig, human_bytes   # noqa: E402
from nl2sql.config import DATA_SOURCES, SPIDER2_LITE         # noqa: E402
from nl2sql.lite_catalog import LiteCatalog                  # noqa: E402
from run_benchmark import load_questions                     # noqa: E402


def _why(exc) -> str:
    """Collapse a BigQuery exception into an actionable reason."""
    msg = " ".join(str(exc).split())
    if "bigquery.jobs.create" in msg:
        return "IAM: service account cannot run jobs (grant roles/bigquery.jobUser)"
    if "has not enabled BigQuery" in msg or "API has not been used" in msg:
        return "IAM: BigQuery API not enabled on the project"
    if "Access Denied" in msg and "Dataset" in msg:
        return "grant: no access to this dataset"
    if "Not found" in msg or "404" in msg:
        return "missing: table/dataset does not exist"
    short = msg[:110]
    return f"{type(exc).__name__}: {short}"


def section(t):
    print("\n" + t)
    print("-" * len(t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="spider2_lite_bq")
    ap.add_argument("--write-unreachable", metavar="PATH")
    ap.add_argument("--limit-dbs", type=int, default=0,
                    help="probe only the first N databases (smoke)")
    args = ap.parse_args()

    problems = []

    section("credentials")
    cfg = BigQueryConfig.load()
    print(cfg.redacted())

    section("target set")
    src = DATA_SOURCES[args.source]
    questions = load_questions([src])
    by_db = defaultdict(list)
    for q in questions:
        by_db[q["db"]].append(q["instance_id"])
    print(f"{len(questions)} instances across {len(by_db)} databases")

    # the catalog tells us the real project.dataset.table to probe, for free
    section("catalog coverage")
    probes, no_catalog = {}, []
    for db in sorted(by_db):
        cat = LiteCatalog(db, "bigquery", SPIDER2_LITE)
        if not cat.available:
            no_catalog.append(db)
            continue
        # one table per distinct project.dataset. The catalog indexes lazily,
        # so this touches directory entries only -- no JSON is read.
        per_ns = {}
        for t in cat.tables.values():
            per_ns.setdefault(t.namespace, t)
        probes[db] = per_ns
    print(f"databases with a shipped catalog: {len(probes)}/{len(by_db)}")
    if no_catalog:
        print(f"  NO catalog ({len(no_catalog)}): {no_catalog[:8]}")
        problems.append(f"{len(no_catalog)} databases have no shipped catalog")

    section("access probe (dry runs - free)")
    from google.api_core import exceptions as gexc
    from google.cloud import bigquery
    from google.oauth2 import service_account
    creds = (service_account.Credentials.from_service_account_info(cfg.credentials_info)
             if cfg.credentials_info
             else service_account.Credentials.from_service_account_file(
                 cfg.credentials_path))
    client = bigquery.Client(project=cfg.project, credentials=creds)
    job_cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)

    # One trivial query first: if we cannot run ANY job, every dataset below
    # would read as 403 and the real cause (our own IAM) would be buried.
    try:
        client.query("SELECT 1", job_config=job_cfg)
        print("  can run query jobs: yes")
    except Exception as e:
        print(f"  CANNOT RUN ANY QUERY: {_why(e)}")
        print("     " + " ".join(str(e).split())[:220])
        print()
        print("  -> fix this first; every dataset probe would just repeat it.")
        print("     console: https://console.cloud.google.com/iam-admin/iam"
              f"?project={cfg.project}")
        return 1

    reachable, unreachable = {}, {}
    projects = Counter()
    items = sorted(probes.items())
    if args.limit_dbs:
        items = items[: args.limit_dbs]
    for db, per_ns in items:
        bad = []
        for ns, t in per_ns.items():
            projects[ns.split(".")[0]] += 1
            try:
                client.query(f"SELECT * FROM `{t.fullname}` LIMIT 0",
                             job_config=job_cfg)
            except Exception as e:
                # keep the real message: "no bigquery.jobs.create permission" (an IAM
                # problem on our own project) and "access denied to dataset X" (a
                # genuine grant problem) are both 403 but need opposite fixes.
                bad.append((ns, _why(e)))
        if bad:
            unreachable[db] = bad
        else:
            reachable[db] = sorted(per_ns)
        print(("  ok   " if not bad else "  FAIL ") + db
              + ("" if not bad else f"  {bad[:2]}"))

    section("verdict")
    n_ok = sum(len(by_db[d]) for d in reachable)
    n_bad = sum(len(by_db[d]) for d in unreachable)
    print(f"reachable  : {len(reachable)} databases, {n_ok} instances")
    print(f"unreachable: {len(unreachable)} databases, {n_bad} instances")
    print("\nGCP projects referenced:")
    for proj, n in projects.most_common():
        print(f"  {proj:34s} {n} dataset(s)")
    if unreachable:
        print("\nunreachable databases and why:")
        for db, bad in sorted(unreachable.items()):
            print(f"  {db:28s} {bad[0][1]:16s} {bad[0][0]}")
        if args.write_unreachable:
            ids = sorted(i for d in unreachable for i in by_db[d])
            Path(args.write_unreachable).write_text("\n".join(ids) + "\n",
                                                    encoding="utf-8")
            print(f"\n{len(ids)} instance ids written to {args.write_unreachable}")
        print("\n-> exclude those instances from the denominator, or request access "
              "to the projects above")
    if problems:
        for p in problems:
            print("BLOCKER: " + p)
    return 0 if reachable else 1


if __name__ == "__main__":
    raise SystemExit(main())
