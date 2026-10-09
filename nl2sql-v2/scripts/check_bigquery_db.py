#!/usr/bin/env python3
"""Credential-free checks for LiteCatalog and BigQueryDatabase.

Builds a fixture in the exact shape spider2-lite ships
(resource/databases/<engine>/<db>/<namespace>/<table>.json) and drives the backend
against a fake BigQuery client, asserting the things that would otherwise be
discovered by spending money:

  * catalog operations issue ZERO queries (the whole point of reading the shipped JSON)
  * every query is dry-run first, and one over the per-query cap is refused with the
    real byte figure in the message
  * the per-episode scan budget stops the episode
  * maximum_bytes_billed is set on real runs, so the server kills a bad estimate
  * find_value is disabled by default, and still gives the free sample-row answer

    uv run python scripts/check_bigquery_db.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl2sql.bigquery_db import (BigQueryConfig, BigQueryDatabase,  # noqa: E402
                                human_bytes)
from nl2sql.dbbase import BudgetExhausted                          # noqa: E402
from nl2sql.lite_catalog import LiteCatalog                        # noqa: E402

GiB = 1024 ** 3

SESSIONS = {
    "table_name": "all_sessions",
    "table_fullname": "data-to-insights.ecommerce.all_sessions",
    "column_names": ["fullVisitorId", "channelGrouping", "totalTransactionRevenue",
                     "hits"],
    "column_types": ["STRING", "STRING", "INT64", "ARRAY<STRUCT<page STRING>>"],
    "nested_column_names": ["fullVisitorId", "channelGrouping",
                            "totalTransactionRevenue", "hits.page"],
    "nested_column_types": ["STRING", "STRING", "INT64", "STRING"],
    "description": [None, None, None, None],
    "sample_rows": [
        {"fullVisitorId": "001", "channelGrouping": "Direct",
         "totalTransactionRevenue": 10, "hits": None},
        {"fullVisitorId": "002", "channelGrouping": "Organic Search",
         "totalTransactionRevenue": None, "hits": None},
    ],
}
PRODUCTS = {
    "table_name": "products",
    "table_fullname": "data-to-insights.ecommerce.products",
    "column_names": ["SKU", "name"],
    "column_types": ["STRING", "STRING"],
    "description": [None, None],
    "sample_rows": [{"SKU": "GGOEA1", "name": "Cap"}],
}
# same bare name in a second dataset: the ambiguity case
PRODUCTS_2 = dict(PRODUCTS,
                  table_fullname="other-project.warehouse.products")

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


def sent_bytes_billed(job_config):
    """What maximumBytesBilled would actually go on the wire.

    Returns "absent" when the field is not set (fine), None when it is explicitly
    null (what the API rejects), or the value.
    """
    props = getattr(job_config, "_properties", None)
    if isinstance(props, dict):               # the real QueryJobConfig
        q = props.get("query") or {}
        return q["maximumBytesBilled"] if "maximumBytesBilled" in q else "absent"
    return getattr(job_config, "maximum_bytes_billed", "absent")


class FakeJob:
    def __init__(self, bytes_processed, rows, job_config, raise_on_result=None):
        self.total_bytes_processed = bytes_processed
        self.job_id = "job1"
        self.location = "US"
        self._rows = rows
        self.job_config = job_config
        self._raise = raise_on_result

    def result(self, timeout=None, max_results=None):
        if self._raise:
            raise self._raise
        return iter(self._rows[:max_results] if max_results else self._rows)


class FakeClient:
    """Records every call so the checks can assert on cost behaviour."""

    def __init__(self, bytes_for=None, rows=None, raise_on_result=None):
        self.dry_runs = []
        self.real_runs = []
        self.configs = []
        self.cancelled = []
        self.bytes_for = bytes_for or {}
        self.rows = rows if rows is not None else [{"n": 1}, {"n": 2}, {"n": 3}]
        self.raise_on_result = raise_on_result

    def _bytes(self, sql):
        for marker, n in self.bytes_for.items():
            if marker in sql:
                return n
        return 1024 * 1024

    def query(self, sql, job_config=None):
        self.configs.append(job_config)
        # mimic the real API's validation. The distinction that matters: the client
        # serialises only properties that were ASSIGNED, so an unset field is omitted
        # and accepted, while an explicit None is sent as "None" and rejected. That is
        # exactly the bug that made every dry run fail.
        if sent_bytes_billed(job_config) is None:
            raise ValueError("400 Invalid value at "
                             "'job.configuration.query.maximum_bytes_billed.value' "
                             "(TYPE_INT64), \"None\"")
        if getattr(job_config, "dry_run", False):
            self.dry_runs.append(sql)
            return FakeJob(self._bytes(sql), [], job_config)
        self.real_runs.append(sql)
        return FakeJob(self._bytes(sql), self.rows, job_config,
                       raise_on_result=self.raise_on_result)

    def cancel_job(self, job_id, location=None):
        self.cancelled.append(job_id)

    def close(self):
        pass


def build_fixture(tmp: Path) -> Path:
    lite = tmp / "spider2-lite"
    base = lite / "resource/databases/bigquery/ecommerce"
    for ns, tables in (("data-to-insights.ecommerce", [SESSIONS, PRODUCTS]),
                       ("other-project.warehouse", [PRODUCTS_2])):
        d = base / ns
        d.mkdir(parents=True, exist_ok=True)
        for t in tables:
            (d / f"{t['table_name']}.json").write_text(json.dumps(t),
                                                       encoding="utf-8")
    # a snowflake-shaped database too, to prove one reader serves both
    sf = lite / "resource/databases/snowflake/TPCH_SF1/PUBLIC"
    sf.mkdir(parents=True, exist_ok=True)
    (sf / "ORDERS.json").write_text(json.dumps({
        "table_name": "ORDERS",
        "table_fullname": "TPCH_SF1.PUBLIC.ORDERS",
        "column_names": ["O_ORDERKEY", "O_TOTALPRICE"],
        "column_types": ["NUMBER", "FLOAT"],
        "description": [None, None],
        "sample_rows": [{"O_ORDERKEY": 1, "O_TOTALPRICE": 1.5}]}), encoding="utf-8")
    return lite


def main():
    tmp = Path(tempfile.mkdtemp(prefix="nl2sql-bqcheck-"))
    lite = build_fixture(tmp)

    print("== catalog ==")
    cat = LiteCatalog("ecommerce", "bigquery", lite)
    check_true("catalog loads the shipped JSON", cat.available)
    check("list_tables returns fully qualified names", cat.list_tables(),
          ["data-to-insights.ecommerce.all_sessions",
           "data-to-insights.ecommerce.products",
           "other-project.warehouse.products"])
    check("namespaces are the project.dataset dirs", cat.namespaces,
          ["data-to-insights.ecommerce", "other-project.warehouse"])
    check("exact fullname resolves",
          cat.resolve("data-to-insights.ecommerce.all_sessions").name, "all_sessions")
    check("case-insensitive fullname resolves",
          cat.resolve("DATA-TO-INSIGHTS.ECOMMERCE.ALL_SESSIONS").name, "all_sessions")
    check("unique bare name resolves", cat.resolve("all_sessions").name,
          "all_sessions")
    try:
        cat.resolve("products")
        FAILURES.append("ambiguous bare name should raise")
        print("FAIL ambiguous bare name raises")
    except ValueError as e:
        check_true("ambiguous bare name lists both datasets",
                   "data-to-insights" in str(e) and "other-project" in str(e),
                   str(e)[:90])
    try:
        cat.resolve("all_session")
        FAILURES.append("typo should raise")
        print("FAIL typo raises")
    except ValueError as e:
        check_true("a typo gets suggestions", "Did you mean" in str(e), str(e)[:80])

    desc = cat.describe("all_sessions")
    check_true("describe lists columns with types", "channelGrouping  STRING" in desc)
    check_true("describe exposes nested STRUCT paths", "hits.page" in desc,
               [l for l in desc.splitlines() if "hits" in l])
    check_true("describe includes the shipped sample rows", "Organic Search" in desc)
    check_true("describe says no warehouse query was run",
               "no warehouse query was run" in desc)
    check("columns() carries (name, type, nullable)", cat.columns("data-to-insights.ecommerce.products")[0],
          ("SKU", "STRING", "UNKNOWN"))
    hint = cat.column_values_hint("all_sessions", "channelGrouping")
    check_true("column value hint uses sample rows",
               "Direct" in hint and "not the full distribution" in hint)

    sfcat = LiteCatalog("TPCH_SF1", "snowflake", lite)
    check("one reader serves the Snowflake layout too", sfcat.list_tables(),
          ["TPCH_SF1.PUBLIC.ORDERS"])

    print("\n== bigquery backend ==")
    cfg = BigQueryConfig(project="p", credentials_path="/dev/null",
                         max_bytes_per_query=10 * GiB,
                         max_bytes_per_episode=25 * GiB)
    client = FakeClient()
    db = BigQueryDatabase("ecommerce", cfg, lite, instance_id="bq001",
                          run_tag="check", client=client)

    check("display_name is the db", db.display_name, "ecommerce")
    check("dialect", db.dialect, "bigquery")
    n_before = len(client.dry_runs) + len(client.real_runs)
    db.list_tables(); db._columns("data-to-insights.ecommerce.products"); db.describe_table("all_sessions")
    check("catalog operations issue ZERO queries",
          len(client.dry_runs) + len(client.real_runs) - n_before, 0)

    df, csv = db.query_preview("SELECT n FROM `t`", preview_rows=2, max_rows=10)
    check("a real query is dry-run first", len(client.dry_runs), 1)
    check("then executed once", len(client.real_runs), 1)
    check("rows come back", list(df["n"]), [1, 2, 3])
    check_true("the preview reports what it scanned", "scanned 1.0MiB" in csv,
               csv.splitlines()[-1])
    check_true("and how much budget is left", "scan budget left" in csv)
    dry_cfg = [c for c in client.configs if getattr(c, "dry_run", False)][0]
    check("dry runs omit maximum_bytes_billed (the API rejects a null)",
          sent_bytes_billed(dry_cfg), "absent")
    real_cfg = [c for c in client.configs if not getattr(c, "dry_run", False)][0]
    check("maximum_bytes_billed caps the real run",
          int(sent_bytes_billed(real_cfg)), 10 * GiB)
    check_true("jobs are labelled for cost attribution",
               real_cfg.labels.get("app") == "nl2sql"
               and real_cfg.labels.get("instance") == "bq001",
               str(real_cfg.labels))

    print("\n== cost guards ==")
    client = FakeClient(bytes_for={"huge": 40 * GiB})
    db = BigQueryDatabase("ecommerce", cfg, lite, client=client)
    try:
        db.query("SELECT * FROM `huge`")
        FAILURES.append("an over-cap query should be refused")
        print("FAIL over-cap query is refused")
    except BudgetExhausted as e:
        check_true("over-cap query is refused with the real figure",
                   "40.0GiB" in str(e) and "partition" in str(e), str(e)[:110])
    check("the refused query never ran", len(client.real_runs), 0)

    client = FakeClient(bytes_for={"mid": 15 * GiB})
    db = BigQueryDatabase("ecommerce", cfg, lite, client=client)
    db.cfg.max_bytes_per_query = 20 * GiB
    db.query("SELECT a FROM `mid`")
    try:
        db.query("SELECT a FROM `mid`")
        FAILURES.append("episode scan budget should stop the second query")
        print("FAIL episode scan budget stops the second query")
    except BudgetExhausted as e:
        check_true("episode scan budget stops the next query",
                   "scan budget is left" in str(e) or "scan budget" in str(e),
                   str(e)[:110])

    client = FakeClient()
    db = BigQueryDatabase("ecommerce", cfg, lite, client=client)
    db.budget.max_queries = 1
    db.query("SELECT 1")
    try:
        db.query("SELECT 2")
        FAILURES.append("query-count budget should stop the episode")
        print("FAIL query count budget enforced")
    except BudgetExhausted as e:
        check_true("query-count budget tells the agent to submit",
                   "submit_result" in str(e), str(e)[:80])

    client = FakeClient(raise_on_result=TimeoutError("deadline"))
    db = BigQueryDatabase("ecommerce", cfg, lite, client=client)
    try:
        db.query("SELECT 1")
        FAILURES.append("a timeout should surface")
        print("FAIL timeout surfaces")
    except TimeoutError as e:
        check_true("a timeout is cancelled and counted",
                   client.cancelled == ["job1"] and db.budget.timeouts == 1,
                   f"cancelled={client.cancelled} timeouts={db.budget.timeouts}")

    print("\n== find_value ==")
    db = BigQueryDatabase("ecommerce", cfg, lite, client=FakeClient())
    out = db.find_value("Direct")
    check_true("find_value is disabled by default", out.startswith("ERROR:"))
    check_true("and explains the billing reason", "bills for every byte" in out
               or "every byte" in out, out[:100])
    out = db.find_value("Organic", table="all_sessions")
    check_true("it still answers from the free sample rows",
               "Organic Search" in out, out[-120:])

    check("human_bytes is readable", human_bytes(1536 * 1024 ** 2), "1.5GiB")

    print("\n== query scope guards (all refuse before a job is submitted) ==")
    gdb = BigQueryDatabase("ecommerce", cfg, lite, instance_id="bq001",
                           run_tag="check", client=FakeClient())
    namespaces = sorted(gdb.catalog.namespaces)
    good = namespaces[0]

    def refused(sql):
        try:
            gdb.query(sql)
        except Exception as e:
            return f"{type(e).__name__}: {e}"
        return ""

    # empty / comment-only SQL must not reach a dry run
    msg = refused("   ")
    check_true("empty SQL is refused without a dry run",
               "no statement" in msg, msg[:70])
    msg = refused("-- just a thought\n/* and another */")
    check_true("comment-only SQL is refused too",
               "no statement" in msg, msg[:70])

    # bare-dataset INFORMATION_SCHEMA: 61 calls across 17 bq_v2 instances, all 404
    msg = refused("SELECT * FROM `ga360.INFORMATION_SCHEMA.TABLES`")
    check_true("bare-dataset INFORMATION_SCHEMA is refused",
               "INFORMATION_SCHEMA" in msg and "billing project" in msg, msg[:90])

    # out-of-scope reference: 11 of the 12 bq_v2 Forbidden instances were this,
    # not a missing grant (bq_preflight reaches every database but one)
    msg = refused("SELECT * FROM `bigquery-public-data.hhs.homeless` LIMIT 1")
    check_true("a dataset outside this database is refused",
               "not part of" in msg, msg[:90])
    check_true("...and the refusal names the datasets that ARE in scope",
               good in msg, msg[:150])

    # and it must not fire on legitimate SQL
    msg = refused(f"SELECT 1 FROM `{good}.all_sessions` LIMIT 1")
    check_true("an in-scope table is not refused",
               "not part of" not in msg, msg[:90] or "(ran)")
    msg = refused(f"SELECT COUNT(*) FROM `{good}.ga_sessions_*` "
                  f"WHERE _TABLE_SUFFIX BETWEEN '20160801' AND '20160831'")
    check_true("a wildcard + _TABLE_SUFFIX query is not refused",
               "not part of" not in msg, msg[:90] or "(ran)")
    msg = refused("WITH t AS (SELECT 1 AS a) SELECT a FROM t")
    check_true("a CTE name is not mistaken for a dataset",
               "not part of" not in msg, msg[:90] or "(ran)")
    msg = refused(f"SELECT a.x FROM `{good}.all_sessions` AS a "
                  f"WHERE a.x > 1")
    check_true("a table alias is not mistaken for a dataset",
               "not part of" not in msg, msg[:90] or "(ran)")
    # the case that produced 193 false positives before the guard was restricted to
    # backticks: a nested field path is textually a three-part qualified name
    msg = refused(f"SELECT h.transaction.transactionId FROM `{good}.all_sessions` f, "
                  f"UNNEST(f.hits) AS h")
    check_true("a nested STRUCT path is not mistaken for project.dataset.table",
               "not part of" not in msg, msg[:120] or "(ran)")
    # forms that work and so must not be refused (4 such queries in bq_v2)
    msg = refused("SELECT schema_name FROM `region-us.INFORMATION_SCHEMA.SCHEMATA`")
    check_true("the region-us INFORMATION_SCHEMA qualifier is allowed",
               "INFORMATION_SCHEMA" not in msg, msg[:100] or "(ran)")
    msg = refused(f"SELECT schema_name FROM `{cfg.project}"
                  f".INFORMATION_SCHEMA.SCHEMATA`")
    check_true("our own billing project's INFORMATION_SCHEMA is allowed",
               "INFORMATION_SCHEMA" not in msg, msg[:100] or "(ran)")
    msg = refused(f"SELECT p.v2ProductName FROM `{good}.ga_sessions_*` f, "
                  f"UNNEST(f.hits) h, UNNEST(h.product) p "
                  f"WHERE h.eCommerceAction.action_type = '6'")
    check_true("UNNEST over two struct levels is not refused",
               "not part of" not in msg, msg[:120] or "(ran)")
    gdb.close()

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print("  " + f)
        return 1
    print("all BigQuery/catalog checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
