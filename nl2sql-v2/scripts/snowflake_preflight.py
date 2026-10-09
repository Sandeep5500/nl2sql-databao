#!/usr/bin/env python3
"""Check Snowflake access and the cost guards BEFORE a GPU is allocated.

This exists because of two incidents on the local lane: a dead Ollama made all 457
search_context calls fail for days without anyone noticing, and a vLLM restart turned
96 of 135 rows into "Connection error" answers. A new external dependency has to fail
loudly and specifically, or it quietly invalidates a run -- and at 412 instances across
shards, a quiet failure is much more expensive.

Checks, each with its own distinguishable failure:
  1. connect (bad account vs bad password are different messages)
  2. who/where am I: CURRENT_ACCOUNT / USER / ROLE / WAREHOUSE
  3. every db_id the target set needs is actually visible (partial grants would
     silently zero whole subsets of the benchmark)
  4. warehouse size / auto-suspend, and whether we may change them
  5. STATEMENT_TIMEOUT_IN_SECONDS really took effect
  6. one timed describe_table on the biggest table in the set, reporting elapsed
     seconds, the query id, and whether stats were skipped

    uv run python scripts/snowflake_preflight.py --source spider2_snow_new
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql.config import DATA_SOURCES                        # noqa: E402
from nl2sql.snowflake_db import SnowflakeConfig, SnowflakeDatabase  # noqa: E402
from run_benchmark import load_questions                      # noqa: E402


def section(title):
    print("\n" + title)
    print("-" * len(title))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="spider2_snow_new",
                    help="which snow source's db_ids must be reachable")
    ap.add_argument("--credential", help="path to a snowflake_credential.json")
    ap.add_argument("--set-warehouse", action="store_true",
                    help="actually apply XSMALL / AUTO_SUSPEND=60 (default: only report)")
    ap.add_argument("--skip-describe", action="store_true",
                    help="skip check 6, which runs one real (small) query")
    args = ap.parse_args()

    problems = []

    section("credentials")
    cfg = SnowflakeConfig.load(Path(args.credential) if args.credential else None)
    print(cfg.redacted())

    section("target databases")
    src = DATA_SOURCES.get(args.source)
    if src is None:
        raise SystemExit(f"unknown --source {args.source!r}; "
                         f"choose from {sorted(DATA_SOURCES)}")
    if src.dialect != "snowflake":
        raise SystemExit(f"--source {args.source!r} is not a Snowflake source")
    questions = load_questions([src])
    need = Counter(q["db"] for q in questions)
    print(f"{len(questions)} instances across {len(need)} databases")
    for db_id, n in need.most_common(8):
        print(f"  {db_id:28s} {n:4d} instances")
    if len(need) > 8:
        print(f"  ... and {len(need) - 8} more")

    section("connect")
    import snowflake.connector as sc
    try:
        con = sc.connect(account=cfg.account, user=cfg.user, password=cfg.password,
                         warehouse=cfg.warehouse, role=cfg.role,
                         session_parameters={
                             "STATEMENT_TIMEOUT_IN_SECONDS": cfg.statement_timeout_s})
    except Exception as e:
        msg = str(e)
        if "Incorrect username or password" in msg:
            hint = "the user/password pair is wrong"
        elif "does not exist" in msg or "Verify the account name" in msg:
            hint = f"the account identifier {cfg.account!r} is wrong or not reachable"
        elif "Role" in msg and "does not exist" in msg:
            hint = f"the role {cfg.role!r} is not granted to this user"
        else:
            hint = "see the driver error above"
        raise SystemExit(f"connect failed: {msg}\n  -> {hint}")
    print("connected")

    def scalar(sql):
        cur = con.cursor()
        try:
            cur.execute(sql)
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            cur.close()

    def rows(sql):
        cur = con.cursor()
        try:
            cur.execute(sql)
            return cur.fetchall(), [d[0] for d in cur.description]
        finally:
            cur.close()

    section("session identity")
    for label, expr in (("account", "CURRENT_ACCOUNT()"), ("user", "CURRENT_USER()"),
                        ("role", "CURRENT_ROLE()"), ("warehouse", "CURRENT_WAREHOUSE()"),
                        ("region", "CURRENT_REGION()")):
        print(f"  {label:10s} {scalar('SELECT ' + expr)}")
    if not scalar("SELECT CURRENT_WAREHOUSE()"):
        problems.append("no current warehouse: queries will fail with "
                        "'No active warehouse selected'")

    section("database visibility")
    db_rows, db_cols = rows("SHOW DATABASES")
    name_at = db_cols.index("name") if "name" in db_cols else 1
    visible = {r[name_at] for r in db_rows}
    print(f"{len(visible)} databases visible to this role")
    missing = sorted(d for d in need if d not in visible)
    if missing:
        n_lost = sum(need[d] for d in missing)
        print(f"  MISSING {len(missing)} of {len(need)} required databases, "
              f"covering {n_lost} instances:")
        for d in missing[:12]:
            print(f"    {d}  ({need[d]} instances)")
        # case mismatch is the most likely cause and is easy to miss
        ci = {v.upper(): v for v in visible}
        near = [(d, ci[d.upper()]) for d in missing if d.upper() in ci]
        if near:
            print("  (case differs only: " + ", ".join(f"{a} -> {b}" for a, b in near[:6])
                  + ")")
        problems.append(f"{len(missing)} required databases not visible "
                        f"({n_lost} instances would score 0 for the wrong reason)")
    else:
        print("  all required databases are visible")

    section("warehouse")
    wh_rows, wh_cols = rows("SHOW WAREHOUSES")
    idx = {c: i for i, c in enumerate(wh_cols)}
    for r in wh_rows:
        if r[idx["name"]].upper() == (cfg.warehouse or "").upper():
            for key in ("size", "auto_suspend", "auto_resume", "state"):
                if key in idx:
                    print(f"  {key:14s} {r[idx[key]]}")
    alter = (f'ALTER WAREHOUSE {SnowflakeDatabase._q(cfg.warehouse)} SET '
             f"WAREHOUSE_SIZE = XSMALL, AUTO_SUSPEND = 60, AUTO_RESUME = TRUE")
    if args.set_warehouse:
        try:
            scalar(alter)
            print("  applied XSMALL / AUTO_SUSPEND=60 / AUTO_RESUME=TRUE")
        except Exception as e:
            print(f"  CANNOT change the warehouse: {e}")
            print("  -> the cost model is whatever the account owner set; "
                  "budget accordingly")
    else:
        print(f"  not applied (pass --set-warehouse to run: {alter})")

    section("statement timeout")
    params, pcols = rows("SHOW PARAMETERS LIKE 'STATEMENT_TIMEOUT_IN_SECONDS'")
    if params:
        value = params[0][pcols.index("value")] if "value" in pcols else params[0][1]
        print(f"  STATEMENT_TIMEOUT_IN_SECONDS = {value} "
              f"(requested {cfg.statement_timeout_s})")
        if str(value) != str(cfg.statement_timeout_s):
            problems.append(f"statement timeout did not take ({value} != "
                            f"{cfg.statement_timeout_s}); runaway queries would "
                            f"rely on the client deadline alone")
    else:
        problems.append("could not read STATEMENT_TIMEOUT_IN_SECONDS")
    con.close()

    if not args.skip_describe and not missing:
        section("timed describe_table on the biggest table")
        db_id = need.most_common(1)[0][0]
        db = SnowflakeDatabase(db_id, cfg, instance_id="preflight",
                               run_tag="preflight")
        try:
            if not db._tables:
                problems.append(f"{db_id} has no visible tables")
            else:
                biggest = max(db._tables.values(), key=lambda m: m.row_count or 0)
                print(f"  {db_id}: {len(db._tables)} tables, {len(db._schemas)} schemas")
                print(f"  biggest: {biggest.qualified} "
                      f"({biggest.row_count} rows, {biggest.n_bytes} bytes)")
                t0 = time.time()
                text = db.describe_table(biggest.qualified)
                print(f"  describe_table took {time.time() - t0:.1f}s in "
                      f"{db.budget.queries} queries "
                      f"(ids: {db.budget.query_ids})")
                print(f"  stats skipped: {'stats skipped' in text}")
                if time.time() - t0 > 60:
                    problems.append("describe_table took over 60s on the biggest "
                                    "table; lower stats_row_limit or size up the "
                                    "warehouse before a full run")
        finally:
            db.close()

    section("verdict")
    if problems:
        for p in problems:
            print("BLOCKER: " + p)
        return 1
    print("preflight clean - safe to smoke-test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
