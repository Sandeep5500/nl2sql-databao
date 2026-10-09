#!/usr/bin/env python3
"""Credential-free checks for SnowflakeDatabase against a fake connector.

Exercises the parts that are easy to get wrong and expensive to discover live:
catalog prefetch, schema qualification, name resolution and its error text, the
describe_table stats thresholds, budget enforcement, result truncation and the
find_value gate. It asserts on the SQL we send, so a regression that would quietly
cost credits (a COUNT(*), an exact COUNT(DISTINCT), one query per column) fails here.

    uv run python scripts/check_snowflake_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl2sql.snowflake_db import (BudgetExhausted, SnowflakeConfig,  # noqa: E402
                                 SnowflakeDatabase)

# (schema, table, kind, row_count, bytes)
TABLES = [
    ("ga4", "events", "BASE TABLE", 900_000_000, 40_000_000_000),   # huge: skip stats
    ("ga4", "users", "BASE TABLE", 1_000, 50_000),                  # small: do stats
    ("staging", "events", "BASE TABLE", 2_000, 90_000),             # name clash
    ("staging", "v_orders", "VIEW", None, None),                    # NULL row_count
]
COLUMNS = [
    ("ga4", "events", "event_name", "TEXT", "YES"),
    ("ga4", "events", "user_pseudo_id", "TEXT", "YES"),
    ("ga4", "users", "userId", "TEXT", "NO"),
    ("ga4", "users", "signup_ts", "TIMESTAMP_NTZ", "YES"),
    ("staging", "events", "label", "TEXT", "YES"),
    ("staging", "v_orders", "order_id", "NUMBER", "NO"),
]


class FakeCursor:
    def __init__(self, con):
        self.con = con
        self.description = []
        self._rows = []
        self.sfqid = None

    # -- catalog path (plain execute) --
    def execute(self, sql):
        self.con.sql_log.append(sql)
        self._rows, self.description = self.con.answer(sql)
        return self

    # -- episode path (async) --
    def execute_async(self, sql):
        self.con.sql_log.append(sql)
        self.con.n_async += 1
        self.sfqid = f"qid{self.con.n_async}"
        self._pending = sql
        return self

    def get_results_from_sfqid(self, qid):
        self._rows, self.description = self.con.answer(self._pending)

    def cancel(self):
        self.con.cancelled.append(self.sfqid)

    def fetchall(self):
        return list(self._rows)

    def fetchmany(self, n):
        return list(self._rows[:n])

    def close(self):
        pass


class FakeConnection:
    """Answers INFORMATION_SCHEMA from the fixtures and anything else from `canned`."""

    def __init__(self, canned=None):
        self.sql_log = []
        self.cancelled = []
        self.n_async = 0
        self.canned = canned or {}
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def answer(self, sql):
        s = " ".join(sql.split())
        if "INFORMATION_SCHEMA.TABLES" in s:
            return ([(t[0], t[1], t[2], t[3], t[4]) for t in TABLES],
                    [("TABLE_SCHEMA",), ("TABLE_NAME",), ("TABLE_TYPE",),
                     ("ROW_COUNT",), ("BYTES",)])
        if "INFORMATION_SCHEMA.COLUMNS" in s:
            return (list(COLUMNS),
                    [("TABLE_SCHEMA",), ("TABLE_NAME",), ("COLUMN_NAME",),
                     ("DATA_TYPE",), ("IS_NULLABLE",)])
        for marker, (rows, desc) in self.canned.items():
            if marker in s:
                return rows, desc
        return [], [("RESULT",)]

    # async status plumbing: always already finished
    def get_query_status(self, qid):
        return "SUCCESS"

    def get_query_status_throw_if_error(self, qid):
        return None

    def is_still_running(self, status):
        return False

    def close(self):
        self.closed = True


def build(canned=None, **cfg_overrides):
    con = FakeConnection(canned)
    cfg = SnowflakeConfig(account="a", user="u", password="pw", **cfg_overrides)
    db = SnowflakeDatabase("GA4", cfg, instance_id="sf_bq011", run_tag="test",
                           connect=lambda **kw: con)
    return db, con


FAILURES = []


def check(label, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        FAILURES.append(f"{label}: got {got!r}, want {want!r}")


def check_true(label, cond, detail=""):
    print(f"{'ok  ' if cond else 'FAIL'} {label}" + (f": {detail}" if detail else ""))
    if not cond:
        FAILURES.append(f"{label}: {detail}")


def main():
    # ---- catalog prefetch is two queries, and nothing else -------------------
    db, con = build()
    check("prefetch issues exactly 2 catalog queries", len(con.sql_log), 2)
    check_true("prefetch reads INFORMATION_SCHEMA.TABLES",
               "INFORMATION_SCHEMA.TABLES" in con.sql_log[0])
    check_true("prefetch reads INFORMATION_SCHEMA.COLUMNS",
               "INFORMATION_SCHEMA.COLUMNS" in con.sql_log[1])

    # ---- list_tables / _columns cost nothing --------------------------------
    before = len(con.sql_log)
    tables = db.list_tables()
    cols = db._columns("ga4.users")
    check("list_tables and _columns issue 0 queries", len(con.sql_log) - before, 0)
    check("multi-schema db qualifies names", tables,
          ["ga4.events", "ga4.users", "staging.events", "staging.v_orders"])
    check("_columns returns (name, type, nullable)", cols[0],
          ("userId", "TEXT", "NO"))

    # ---- name resolution ----------------------------------------------------
    check("exact qualified name resolves", db._resolve("ga4.users").table, "users")
    check("case-insensitive qualified resolves", db._resolve("GA4.USERS").table,
          "users")
    check("unique bare name resolves", db._resolve("users").table, "users")

    try:
        db._resolve("events")
        FAILURES.append("ambiguous bare name should raise")
        print("FAIL ambiguous bare name raises")
    except ValueError as e:
        check_true("ambiguous bare name names both schemas",
                   "ga4" in str(e) and "staging" in str(e), str(e)[:90])

    try:
        db._resolve("evnts")
        FAILURES.append("unknown table should raise")
        print("FAIL unknown table raises")
    except ValueError as e:
        check_true("unknown table suggests candidates",
                   "Did you mean" in str(e), str(e)[:90])

    # ---- describe_table on a huge table: no COUNT(*), no stats --------------
    db, con = build()
    before = len(con.sql_log)
    text = db.describe_table("ga4.events")
    issued = " ".join(con.sql_log[before:])
    check_true("huge table: stats are skipped",
               "stats skipped" in text, text.splitlines()[0])
    check_true("huge table: no COUNT(*) anywhere", "COUNT(*)" not in issued)
    check_true("huge table: no APPROX_COUNT_DISTINCT either",
               "APPROX_COUNT_DISTINCT" not in issued)
    check_true("huge table: row count came from the catalog",
               "900000000 rows" in text, text.splitlines()[0])
    check("huge table: only the sample query runs",
          len(con.sql_log) - before, 1)

    # ---- describe_table on a small table: approximate stats, still no COUNT(*)
    db, con = build()
    before = len(con.sql_log)
    db.describe_table("ga4.users")
    issued = " ".join(con.sql_log[before:])
    check_true("small table: uses APPROX_COUNT_DISTINCT",
               "APPROX_COUNT_DISTINCT" in issued)
    check_true("small table: never COUNT(DISTINCT",
               "COUNT(DISTINCT" not in issued.upper())
    check_true("small table: no bare COUNT(*) scan for row count",
               "COUNT(*) - COUNT(" in issued and "SELECT COUNT(*) FROM" not in issued)
    check_true("identifiers are double-quoted with stored case",
               '"userId"' in issued, issued[:80])
    check_true("fully qualified three-part name",
               '"GA4"."ga4"."users"' in issued)

    # ---- NULL row_count (view): stats skipped, no COUNT(*) fallback ---------
    db, con = build()
    before = len(con.sql_log)
    text = db.describe_table("staging.v_orders")
    issued = " ".join(con.sql_log[before:])
    check_true("view: row count reported unknown", "row count unknown" in text)
    check_true("view: no COUNT(*) fallback", "COUNT(*)" not in issued)

    # ---- result truncation is bounded and labelled -------------------------
    rows = [(i,) for i in range(50)]
    db, con = build(canned={"FROM big": (rows, [("N",)])})
    df, csv = db.query_preview("SELECT n FROM big", preview_rows=3, max_rows=10)
    check("truncates to max_rows", len(df), 10)
    check_true("truncation is stated, not silent", "truncated" in csv, csv.splitlines()[-1])

    # ---- budget enforcement ------------------------------------------------
    db, con = build(max_queries_per_episode=2)
    db.query("SELECT 1")
    db.query("SELECT 2")
    try:
        db.query("SELECT 3")
        FAILURES.append("budget should have been exhausted")
        print("FAIL budget exhaustion raises")
    except BudgetExhausted as e:
        check_true("budget exhaustion tells the agent to submit",
                   "submit_result" in str(e), str(e)[:80])
    check("budget counted the queries", db.budget.queries, 2)
    check("budget recorded query ids", db.budget.query_ids, ["qid1", "qid2"])

    # ---- find_value gating -------------------------------------------------
    db, _ = build()
    out = db.find_value("california")
    check_true("find_value refuses an all-table sweep on a huge db",
               out.startswith("ERROR:") and "table=" in out, out[:90])

    db, _ = build(find_value_enabled=False)
    check_true("find_value can be disabled outright",
               db.find_value("x", table="ga4.users").startswith("ERROR:"))

    db, con = build(canned={"ILIKE": ([("label", "California", 3)],
                                      [("COL",), ("VALUE",), ("N",)])})
    before = len(con.sql_log)
    out = db.find_value("california", table="staging.events")
    check("find_value uses ONE query per table, not per column",
          len(con.sql_log) - before, 1)
    check_true("find_value samples rather than full-scans",
               "SAMPLE ROW" in con.sql_log[-1])
    check_true("find_value reports the hit", "California" in out, out[:80])
    check_true("find_value says the search was sampled", "sampled" in out)

    # ---- prompt facts feed the dialect rules --------------------------------
    db, _ = build(max_queries_per_episode=42, statement_timeout_s=77)
    check("prompt_facts expose the budget", db.prompt_facts,
          {"query_budget": 42, "query_timeout_s": 77})
    check("display_name is the db_id", db.display_name, "GA4")

    # ---- the whole prompt renders with no leftover placeholders ------------
    from nl2sql.prompts import DIALECTS
    rules = DIALECTS["snowflake"].sql_rules.format_map(dict(db.prompt_facts))
    check_true("snowflake rules render with no stray braces",
               "{" not in rules and "}" not in rules)
    check_true("snowflake rules state the budget", "42 queries" in rules)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print("  " + f)
        return 1
    print("all SnowflakeDatabase checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
