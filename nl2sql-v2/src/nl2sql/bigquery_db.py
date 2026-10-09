"""BigQuery backend satisfying dbbase.DatabaseLike, for spider2-lite's bq###/ga### lane.

Schema comes from the shipped catalog (lite_catalog), so list_tables, _columns and
describe_table cost nothing at all. Only run_sql_query reaches BigQuery.

BigQuery bills per byte scanned, which makes the guard here stronger than anything
available on Snowflake: every query is **dry-run first** to learn exactly how many
bytes it would read, refused above a cap with that number in the error so the agent
can add a partition filter, and then run with `maximum_bytes_billed` so the server
kills it if the estimate was wrong. A per-episode byte budget sits on top.

Costing note: the datasets in this lane are public (ga360, ebi_chembl, fec,
census_bureau_*, ...), so storage is free but *queries are billed to our project*.
"""

import difflib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .dbbase import BudgetExhausted, QueryBudget
from .lite_catalog import LiteCatalog

_TiB = 1024 ** 4


@dataclass
class BigQueryConfig:
    project: str = ""                       # the billing project
    credentials_path: str = ""              # service-account JSON on disk
    credentials_info: dict | None = None    # ... or the key itself, from a secret
    location: str | None = None             # e.g. "US"; most public data is US

    statement_timeout_s: int = 120
    max_queries_per_episode: int = 60
    max_seconds_per_episode: float = 900.0
    # refuse a query the dry run says would scan more than this
    max_bytes_per_query: int = 50 * 1024 ** 3        # 50 GiB
    # and stop the episode once it has scanned this much in total
    max_bytes_per_episode: int = 200 * 1024 ** 3     # 200 GiB
    find_value_enabled: bool = False        # a cross-table LIKE sweep is ruinous here
    use_query_cache: bool = True            # repeated identical SQL is then free

    source: str = "(unset)"

    @classmethod
    def load(cls, path: Path | None = None, **overrides) -> "BigQueryConfig":
        """Credentials from, in order: an explicit path, GOOGLE_APPLICATION_CREDENTIALS
        / BIGQUERY_CREDENTIAL, then ~/.nl2sql/bigquery_credential.json.

        The JSON schema is a normal GCP service-account key, which is also what
        Spider2's own evaluation_suite expects, so the same file serves both.
        """
        # On Modal the key arrives as a secret env var holding the JSON, so
        # nothing is ever written to the container filesystem.
        inline = os.environ.get("GCP_SA_KEY") or os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS_JSON")
        if inline and not path:
            info = json.loads(inline)
            project = (overrides.pop("project", "")
                       or os.environ.get("BIGQUERY_PROJECT", "")
                       or info.get("project_id", ""))
            if not project:
                raise SystemExit("GCP key has no project_id; set BIGQUERY_PROJECT")
            return cls(project=project, credentials_info=info,
                       source=f"env (service account "
                              f"{info.get('client_email', '?')})", **overrides)

        tried, chosen = [], None
        candidates = []
        if path:
            candidates.append(Path(path))
        for var in ("GOOGLE_APPLICATION_CREDENTIALS", "BIGQUERY_CREDENTIAL"):
            if os.environ.get(var):
                candidates.append(Path(os.environ[var]))
        candidates.append(Path.home() / ".nl2sql/bigquery_credential.json")

        for cand in candidates:
            if cand.exists():
                chosen = cand
                break
            tried.append(str(cand))

        if chosen is None:
            raise SystemExit(
                "no BigQuery credentials found. Looked in:\n  "
                + "\n  ".join(tried or ["(nothing configured)"])
                + "\nOn Modal: modal secret create nl2sql-bigquery "
                  "GOOGLE_APPLICATION_CREDENTIALS=/secrets/bq.json  (and mount the "
                  "key), or set BIGQUERY_CREDENTIAL to the key path.\nLocally: put "
                  "the service-account key at ~/.nl2sql/bigquery_credential.json "
                  "(chmod 600).")

        project = overrides.pop("project", "")
        if not project:
            try:
                project = json.loads(chosen.read_text(encoding="utf-8")).get(
                    "project_id", "")
            except ValueError:
                project = ""
        project = project or os.environ.get("BIGQUERY_PROJECT", "")
        if not project:
            raise SystemExit(f"could not determine a billing project from {chosen}; "
                             f"set BIGQUERY_PROJECT")
        return cls(project=project, credentials_path=str(chosen),
                   source=str(chosen), **overrides)

    def redacted(self) -> str:
        who = (self.credentials_info or {}).get("client_email",
                                               self.credentials_path or "<none>")
        return (f"project={self.project} credentials={who} "
                f"location={self.location} "
                f"max_bytes/query={self.max_bytes_per_query / 1024 ** 3:.0f}GiB "
                f"max_bytes/episode={self.max_bytes_per_episode / 1024 ** 3:.0f}GiB")


def human_bytes(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.1f}{unit}"
        n /= 1024


def _trim_cell(value, limit: int):
    s = str(value)
    if len(s) <= limit:
        return value
    keep = limit - 15
    front = int(keep * 0.7)
    return s[:front] + "[...trimmed...]" + s[front - keep:]


class BigQueryDatabase:
    """One spider2-lite BigQuery database (the question's `db`)."""

    dialect = "bigquery"

    def __init__(self, db_name: str, cfg: BigQueryConfig, lite_root: Path,
                 instance_id: str = "", run_tag: str = "", client=None):
        self.db_name = db_name
        self.cfg = cfg
        self.instance_id = instance_id
        self.run_tag = run_tag
        self.budget = QueryBudget(max_queries=cfg.max_queries_per_episode,
                                  max_seconds=cfg.max_seconds_per_episode)
        self.bytes_scanned = 0
        self.catalog = LiteCatalog(db_name, "bigquery", lite_root)
        if not self.catalog.available:
            raise ValueError(
                f"no shipped catalog for BigQuery database {db_name!r} under "
                f"{self.catalog.root}; cannot describe tables without querying")
        self._client = client            # injectable for tests

    # ── identity ──────────────────────────────────────────────────────────
    @property
    def display_name(self) -> str:
        return self.db_name

    @property
    def prompt_facts(self) -> dict:
        return {"query_budget": self.cfg.max_queries_per_episode,
                "query_timeout_s": self.cfg.statement_timeout_s,
                "max_scan": human_bytes(self.cfg.max_bytes_per_query)}

    @property
    def client(self):
        if self._client is None:
            from google.cloud import bigquery
            from google.oauth2 import service_account
            if self.cfg.credentials_info:
                creds = service_account.Credentials.from_service_account_info(
                    self.cfg.credentials_info)
            else:
                creds = service_account.Credentials.from_service_account_file(
                    self.cfg.credentials_path)
            self._client = bigquery.Client(project=self.cfg.project,
                                           credentials=creds,
                                           location=self.cfg.location)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass

    # ── catalog (free) ────────────────────────────────────────────────────
    def list_tables(self) -> list[str]:
        return self.catalog.list_tables()

    def _columns(self, table: str) -> list:
        return self.catalog.columns(table)

    def describe_table(self, table: str, sample_rows: int = 5,
                       context=None, notes: bool = True) -> str:
        # context/notes are the DCE enrichment material, which only exists for the
        # SQLite databases; the shipped BigQuery catalog carries the publishers' own
        # column descriptions instead. Accepted and ignored so tools.py never has to
        # branch on dialect.
        return self.catalog.describe(table, sample_rows=sample_rows)

    def list_views(self) -> list[str]:
        """The shipped catalog JSON does not mark views, and one
        INFORMATION_SCHEMA.VIEWS query per dataset is not worth the round trips --
        a view is queryable exactly like a table here anyway."""
        return []

    @property
    def find_value_enabled(self) -> bool:
        return self.cfg.find_value_enabled

    # ── query execution ───────────────────────────────────────────────────
    def _job_config(self, dry_run: bool):
        try:
            from google.cloud import bigquery
            make = bigquery.QueryJobConfig
        except ImportError:
            # the SDK is only needed to talk to BigQuery; with an injected
            # client (the checks) a plain object carries the same fields, so
            # the cost guards stay testable without the dependency
            from types import SimpleNamespace as make
        kwargs = dict(
            dry_run=dry_run,
            use_query_cache=self.cfg.use_query_cache,
            labels={"app": "nl2sql", "run": (self.run_tag or "adhoc")[:63].lower(),
                    "instance": (self.instance_id or "none")[:63].lower()},
        )
        if not dry_run:
            # server-side kill switch. Only on real runs: the API rejects the field
            # outright on a dry run (the client serialises None rather than omitting
            # it), which fails every estimate and so every query.
            kwargs["maximum_bytes_billed"] = self.cfg.max_bytes_per_query
        return make(**kwargs)

    def _estimate(self, sql: str) -> int:
        """Dry run: what would this scan? Free, and does not count as a query."""
        job = self.client.query(sql, job_config=self._job_config(dry_run=True))
        return int(getattr(job, "total_bytes_processed", 0) or 0)

    def _check_budget(self) -> None:
        self.budget.check()
        if self.bytes_scanned >= self.cfg.max_bytes_per_episode:
            raise BudgetExhausted(
                f"scan budget exhausted ({human_bytes(self.bytes_scanned)} read for "
                f"this question). Submit your best existing query_id with "
                f"submit_result.")

    # `dataset.INFORMATION_SCHEMA.VIEW` with no project in front of it. BigQuery
    # happily resolves that against the billing project and 404s.
    # Whatever qualifies an INFORMATION_SCHEMA reference, however many parts: the
    # shape of the prefix decides what is wrong with it. Capture it all rather than
    # excluding bad cases with a lookbehind -- the first attempt excluded a leading
    # backtick and so missed every real occurrence, because the prompt tells the
    # model to backtick its table references.
    _INFO_SCHEMA = re.compile(
        r"(?P<prefix>[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)*)"
        r"\.INFORMATION_SCHEMA\.(?P<view>\w+)", re.IGNORECASE)

    _CATALOG_HINT = ("the complete catalog for this database is already in your "
                     "prompt, and list_tables()/describe_table() read it at no "
                     "cost, so INFORMATION_SCHEMA should not be necessary.")

    # BACKTICKED three-part references only. An unbackticked a.b.c is far more
    # often a nested field path (UNNEST alias . STRUCT . field) than a table name,
    # and those are the bulk of the GA-style datasets: matching them refused 193
    # queries in bq_v2 that had actually succeeded. Backticks are required anyway
    # whenever the project id is hyphenated, as bigquery-public-data is.
    _QUALIFIED_REF = re.compile(
        r"`(?P<bt>[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_$*\-]+)`")

    def _known_namespaces(self) -> set:
        return {ns.lower() for ns in self.catalog.namespaces}

    def _reject_out_of_scope(self, sql: str) -> None:
        """Refuse a reference to a dataset outside this question's database.

        Returned as a tool error, so the agent simply tries again -- the point is
        that it is told "not in this database" instead of "Access Denied", and that
        it costs nothing to find out.
        """
        known = self._known_namespaces()
        if not known:
            return                      # no catalog: nothing to check against
        seen = {}
        for m in self._QUALIFIED_REF.finditer(sql):
            ref = m.group("bt")
            project, dataset, _table = ref.split(".", 2)
            ns = f"{project}.{dataset}"
            if ns.lower() not in known and dataset.upper() != "INFORMATION_SCHEMA":
                seen.setdefault(ns, ref)
        if not seen:
            return
        datasets = sorted(self.catalog.namespaces)
        shown = ", ".join(datasets[:8])
        more = f" (and {len(datasets) - 8} more)" if len(datasets) > 8 else ""
        raise ValueError(
            f"{', '.join(sorted(seen))} is not part of the "
            f"{self.display_name!r} database, so this query cannot be answered from "
            f"it -- BigQuery would reply 'Access Denied' rather than 'no such "
            f"table', which is misleading. Everything this question needs is in: "
            f"{shown}{more}. Use list_tables() to see the tables, and build the "
            f"answer from those.")

    def _reject_bare_information_schema(self, sql: str) -> None:
        for m in self._INFO_SCHEMA.finditer(sql):
            prefix, view = m.group("prefix"), m.group("view")
            parts = prefix.split(".")
            if len(parts) >= 2:
                continue                 # project.dataset.INFORMATION_SCHEMA: fine
            name = parts[0]
            # `region-us.INFORMATION_SCHEMA.*` is the valid regional qualifier, and
            # our own billing project really does expose its metadata. Neither is
            # useful here, but both succeed, so neither is ours to refuse.
            if name.lower().startswith("region-") or name == self.cfg.project:
                continue
            if "-" in name:
                # a project id, not a dataset: project-level INFORMATION_SCHEMA
                # needs a role nobody holds on a public project, and BigQuery says
                # "Access Denied" rather than "no such table"
                raise ValueError(
                    f"`{name}.INFORMATION_SCHEMA.{view}` asks for PROJECT-level "
                    f"metadata of {name}, which needs a role no one has on a public "
                    f"project, so BigQuery refuses it as Access Denied rather than "
                    f"as a missing table. Instead, {self._CATALOG_HINT}")
            project = self.catalog.project_for(name) or "<project>"
            raise ValueError(
                f"`{name}.INFORMATION_SCHEMA.{view}` has no project in front of it, "
                f"so it resolves against the billing project instead of the "
                f"dataset's own and cannot be found. Write "
                f"`{project}.{name}.INFORMATION_SCHEMA.{view}` if you really need "
                f"it -- but {self._CATALOG_HINT}")

    def _run(self, sql: str, max_rows: int, timeout_s: float | None = None):
        if not re.sub(r"--[^\n]*|/\*.*?\*/", "", sql, flags=re.S).strip():
            raise ValueError("The SQL contained no statement that returns rows "
                             "(empty or comment-only query).")
        self._reject_bare_information_schema(sql)
        self._reject_out_of_scope(sql)
        self._check_budget()

        est = self._estimate(sql)
        if est > self.cfg.max_bytes_per_query:
            # the most useful possible error: the real number, and what to do
            raise BudgetExhausted(
                f"this query would scan {human_bytes(est)}, over the "
                f"{human_bytes(self.cfg.max_bytes_per_query)} per-query limit. "
                f"Add a filter on the partition/date column, select fewer columns "
                f"(BigQuery bills per column read), or aggregate in SQL instead of "
                f"returning rows.")
        remaining = self.cfg.max_bytes_per_episode - self.bytes_scanned
        if est > remaining:
            raise BudgetExhausted(
                f"this query would scan {human_bytes(est)} but only "
                f"{human_bytes(remaining)} of this question's scan budget is left. "
                f"Narrow it, or submit your best existing query_id.")

        started = time.time()
        job = self.client.query(sql, job_config=self._job_config(dry_run=False))
        try:
            it = job.result(timeout=timeout_s or self.cfg.statement_timeout_s,
                            max_results=max_rows + 1)
        except Exception:
            try:
                self.client.cancel_job(job.job_id, location=job.location)
            except Exception:
                pass
            self.budget.record(getattr(job, "job_id", None), time.time() - started)
            self.budget.timeouts += 1
            raise TimeoutError(
                f"query exceeded {timeout_s or self.cfg.statement_timeout_s:.0f}s "
                f"and was cancelled (job={getattr(job, 'job_id', '?')}). Add filters "
                f"or aggregate more in SQL.")
        self.budget.record(getattr(job, "job_id", None), time.time() - started)
        self.bytes_scanned += int(getattr(job, "total_bytes_processed", 0) or est)
        return it, job

    @staticmethod
    def _to_frame(it, max_rows: int) -> tuple[pd.DataFrame, bool]:
        rows = []
        truncated = False
        for i, row in enumerate(it):
            if i >= max_rows:
                truncated = True
                break
            rows.append(dict(row))
        return pd.DataFrame(rows), truncated

    def query(self, sql: str, max_rows: int = 100) -> pd.DataFrame:
        it, _ = self._run(sql, max_rows)
        df, _ = self._to_frame(it, max_rows)
        return df

    def query_preview(self, sql: str, preview_rows: int, max_rows: int,
                      cell_char_limit: int = 1024,
                      timeout_s: float = 90.0) -> tuple[pd.DataFrame, str]:
        it, job = self._run(sql, max_rows, timeout_s)
        df, truncated = self._to_frame(it, max_rows)
        preview = df.head(preview_rows).map(lambda v: _trim_cell(v, cell_char_limit))
        csv = preview.to_csv(index=False)
        if truncated:
            csv += (f"\n[showing {len(preview)} rows; result exceeded the "
                    f"{max_rows}-row cap and was truncated - narrow the query]")
        elif len(df) > preview_rows:
            csv += f"\n[showing {len(preview)} of {len(df)} rows]"
        scanned = int(getattr(job, "total_bytes_processed", 0) or 0)
        csv += (f"\n[scanned {human_bytes(scanned)}; "
                f"{human_bytes(self.cfg.max_bytes_per_episode - self.bytes_scanned)} "
                f"of this question's scan budget left]")
        return df, csv

    # ── value inspection ──────────────────────────────────────────────────
    def get_column_values(self, table: str, column: str, limit: int = 20) -> str:
        """Real distinct values when affordable, the catalog's sample otherwise.

        A GROUP BY reads the whole column, which on these datasets can be tens of
        GiB for one tool call, so the dry-run estimate decides.
        """
        t = self.catalog.table(table)
        names = {c for c, _ in t.columns}
        if column not in names:
            ci = [c for c in names if c.lower() == column.lower()]
            if len(ci) != 1:
                raise ValueError(f"Unknown column {column!r} in {t.fullname!r}. "
                                 f"Columns: {sorted(names)}")
            column = ci[0]
        sql = (f"SELECT `{column}` AS value, COUNT(*) AS count "
               f"FROM `{t.fullname}` GROUP BY 1 ORDER BY 2 DESC LIMIT {int(limit)}")
        try:
            est = self._estimate(sql)
        except Exception as e:
            return (f"[could not estimate the cost of reading that column: {e}]\n"
                    + self.catalog.column_values_hint(t.fullname, column, limit))
        if est > self.cfg.max_bytes_per_query:
            return (f"[reading {t.fullname}.{column} would scan {human_bytes(est)}, "
                    f"over the per-query limit, so here is the catalog sample "
                    f"instead]\n"
                    + self.catalog.column_values_hint(t.fullname, column, limit))
        df = self.query(sql, max_rows=limit)
        return df.to_csv(index=False)

    def find_value(self, term: str, table: str | None = None,
                   column: str | None = None, limit: int = 10,
                   max_columns: int = 200) -> str:
        """Disabled by default: a LIKE sweep across text columns reads every byte of
        every one of them, which on this lane is the single most expensive thing the
        agent could do. The catalog's sample rows cover the common case."""
        if not self.cfg.find_value_enabled:
            hint = ""
            if table:
                try:
                    t = self.catalog.table(table)
                    hits = []
                    for c, _ in t.columns:
                        for row in t.sample_rows:
                            v = row.get(c)
                            if v is not None and term.lower() in str(v).lower():
                                hits.append(f"{t.fullname}.{c} = {v!r}")
                                break
                    if hits:
                        hint = ("\nFound in the catalog's sample rows:\n"
                                + "\n".join(hits[:limit]))
                except ValueError:
                    pass
            return ("ERROR: find_value is disabled on BigQuery: scanning every text "
                    "column bills for every byte in them. Use describe_table (its "
                    "sample rows are free) and then SELECT DISTINCT on the one "
                    "column you care about." + hint)

        if not table:
            return ("ERROR: find_value on BigQuery requires table='<project.dataset."
                    "table>' so the scan is bounded.")
        t = self.catalog.table(table)
        text_cols = [c for c, ty in t.columns
                     if "STRING" in str(ty).upper()
                     and (column is None or c == column)][:max_columns]
        if not text_cols:
            return f"no text columns in {t.fullname}"
        branches = " UNION ALL ".join(
            f"SELECT '{c}' AS col, CAST(`{c}` AS STRING) AS value, COUNT(*) AS n "
            f"FROM `{t.fullname}` WHERE LOWER(CAST(`{c}` AS STRING)) "
            f"LIKE '%{term.lower()}%' GROUP BY 2 LIMIT {int(limit)}"
            for c in text_cols)
        df = self.query(branches, max_rows=limit)
        if df.empty:
            return f"no values matching {term!r} found in {t.fullname}"
        return df.to_csv(index=False)
