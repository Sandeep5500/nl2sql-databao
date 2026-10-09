"""Snowflake backend satisfying dbbase.DatabaseLike, for the Spider 2.0-Snow lanes.

Mirrors db.py method for method so tools.py dispatches against it unchanged, but the
cost model is the opposite of SQLite's: there, scanning a table is free, so
describe_table issues COUNT(*) plus a COUNT(DISTINCT ...) per column and find_value
sweeps every text column of every table. Against GA4- or PATENTS-scale tables that
would be a very expensive way to learn nothing, so this backend:

  * prefetches the whole catalog once (two INFORMATION_SCHEMA queries) and then answers
    list_tables/_columns with zero queries, and takes row counts from the catalog
    instead of ever issuing COUNT(*);
  * uses APPROX_COUNT_DISTINCT, and skips per-column stats entirely above a size
    threshold, saying so in the output;
  * caps find_value to one sampled query per table and requires a table on big
    databases;
  * enforces a per-episode query budget, surfaced to the model in its prompt;
  * cancels queries from both sides (client deadline + STATEMENT_TIMEOUT_IN_SECONDS).

SnowflakeConfig lives here rather than in config.py so config.py stays free of
credential handling, which every other module would otherwise import.
"""

import difflib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .dbbase import BudgetExhausted, QueryBudget  # noqa: F401 (re-exported)

# identifiers are quoted with their exact stored case everywhere: Snowflake folds
# unquoted names to UPPER, but the BigQuery-derived objects are stored lower/mixed.
_BINARY_TYPES = ("BINARY", "VARBINARY")


@dataclass
class SnowflakeConfig:
    account: str
    user: str
    password: str
    warehouse: str = "COMPUTE_WH"
    role: str | None = None

    statement_timeout_s: int = 90
    max_queries_per_episode: int = 60
    max_seconds_per_episode: float = 900.0
    # above either threshold, describe_table reports columns but no distinct/null stats
    stats_row_limit: int = 10_000_000
    stats_bytes_limit: int = 5_000_000_000
    find_value_enabled: bool = True
    find_value_require_table_above_rows: int = 5_000_000
    find_value_scan_rows: int = 200_000
    find_value_max_columns_per_query: int = 30
    use_cached_result: bool = True
    query_tag_prefix: str = "nl2sql"
    describe_cache_dir: Path | None = None

    # where load() looked, for the preflight to print on failure
    source: str = "(unset)"

    _ENV = {"account": "SNOWFLAKE_ACCOUNT", "user": "SNOWFLAKE_USER",
            "password": "SNOWFLAKE_PASSWORD", "warehouse": "SNOWFLAKE_WAREHOUSE",
            "role": "SNOWFLAKE_ROLE"}

    @classmethod
    def load(cls, path: Path | None = None, **overrides) -> "SnowflakeConfig":
        """Resolve credentials from, in order: explicit path, the environment,
        $NL2SQL_SNOWFLAKE_CREDENTIAL, ~/.nl2sql/snowflake_credential.json.

        The JSON schema is Spider2's own snowflake_credential.json, so the file they
        send with your account drops in unchanged.
        """
        tried = []
        creds, source = {}, None

        candidates = []
        if path:
            candidates.append(Path(path))
        env_path = os.environ.get("NL2SQL_SNOWFLAKE_CREDENTIAL")
        if env_path:
            candidates.append(Path(env_path))
        candidates.append(Path.home() / ".nl2sql/snowflake_credential.json")

        env_creds = {k: os.environ[v] for k, v in cls._ENV.items() if os.environ.get(v)}
        if {"account", "user", "password"} <= set(env_creds):
            creds, source = env_creds, "environment"
        else:
            tried.append("environment (SNOWFLAKE_ACCOUNT/USER/PASSWORD)")
            for cand in candidates:
                if cand.exists():
                    creds = json.loads(cand.read_text(encoding="utf-8"))
                    source = str(cand)
                    break
                tried.append(str(cand))

        if not creds:
            raise SystemExit(
                "no Snowflake credentials found. Looked in:\n  "
                + "\n  ".join(tried)
                + "\nOn Modal: modal secret create nl2sql-snowflake "
                  "SNOWFLAKE_ACCOUNT=... SNOWFLAKE_USER=... SNOWFLAKE_PASSWORD=... "
                  "SNOWFLAKE_WAREHOUSE=...\nLocally: put Spider2's "
                  "snowflake_credential.json at ~/.nl2sql/ (chmod 600).")

        known = {f for f in cls.__dataclass_fields__ if not f.startswith("_")}
        kwargs = {k: v for k, v in creds.items() if k in known and v is not None}
        kwargs.update(overrides)
        missing = {"account", "user", "password"} - set(kwargs)
        if missing:
            raise SystemExit(f"Snowflake credentials from {source} are missing "
                             f"{sorted(missing)}")
        kwargs["source"] = source
        return cls(**kwargs)

    def redacted(self) -> str:
        pw = f"<set, {len(self.password)} chars>" if self.password else "<EMPTY>"
        return (f"account={self.account} user={self.user} warehouse={self.warehouse} "
                f"role={self.role} password={pw} (from {self.source})")


@dataclass
class _TableMeta:
    schema: str
    table: str
    kind: str                 # BASE TABLE | VIEW | ...
    row_count: int | None     # NULL for views and some shared/external tables
    n_bytes: int | None

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.table}"


def _trim_cell(value, limit: int):
    s = str(value)
    if len(s) <= limit:
        return value
    keep = limit - 15
    front = int(keep * 0.7)
    return s[:front] + "[...trimmed...]" + s[front - keep:]


class SnowflakeDatabase:
    """One instance = one Spider2-Snow database (the question's db_id)."""

    dialect = "snowflake"

    def __init__(self, db_id: str, cfg: SnowflakeConfig, instance_id: str = "",
                 run_tag: str = "", connect=None):
        self.db_id = db_id
        self.cfg = cfg
        self.instance_id = instance_id
        self.budget = QueryBudget(max_queries=cfg.max_queries_per_episode,
                                  max_seconds=cfg.max_seconds_per_episode)
        # deferred so importing this module never requires the connector, and the
        # local SQLite lane's environment stays untouched
        if connect is None:
            import snowflake.connector as sc
            connect = sc.connect
        self.con = connect(
            account=cfg.account, user=cfg.user, password=cfg.password,
            warehouse=cfg.warehouse, role=cfg.role, database=db_id,
            client_session_keep_alive=True,
            session_parameters={
                "STATEMENT_TIMEOUT_IN_SECONDS": cfg.statement_timeout_s,
                # if this process dies, the query dies with it
                "ABORT_DETACHED_QUERY": True,
                "QUERY_TAG": f"{cfg.query_tag_prefix}/{run_tag or 'adhoc'}/"
                             f"{instance_id or db_id}",
                # exact-text repeats within 24h cost zero compute; agents re-issue a
                # lot of identical exploration SQL across pass@K and resumes
                "USE_CACHED_RESULT": cfg.use_cached_result,
            })
        self._tables: dict[str, _TableMeta] = {}
        self._cols: dict[str, list[tuple[str, str, str]]] = {}
        self._schemas: list[str] = []
        self._prefetch_catalog()

    # ── identity ──────────────────────────────────────────────────────────
    @property
    def display_name(self) -> str:
        return self.db_id

    @property
    def prompt_facts(self) -> dict:
        return {"query_budget": self.cfg.max_queries_per_episode,
                "query_timeout_s": self.cfg.statement_timeout_s}

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:
            pass

    # ── catalog prefetch ──────────────────────────────────────────────────
    def _prefetch_catalog(self) -> None:
        """Two catalog queries, then zero for the rest of the episode.

        INFORMATION_SCHEMA reads are metadata-only (no warehouse scan), so these are
        effectively free -- unlike COUNT(*), which they replace.
        """
        q = self._q
        tables = self._raw(
            f"SELECT table_schema, table_name, table_type, row_count, bytes "
            f"FROM {q(self.db_id)}.INFORMATION_SCHEMA.TABLES "
            f"WHERE table_schema <> 'INFORMATION_SCHEMA'")
        for schema, table, kind, rows, nbytes in tables:
            meta = _TableMeta(schema, table, kind,
                              int(rows) if rows is not None else None,
                              int(nbytes) if nbytes is not None else None)
            self._tables[meta.qualified] = meta

        cols = self._raw(
            f"SELECT table_schema, table_name, column_name, data_type, is_nullable "
            f"FROM {q(self.db_id)}.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE table_schema <> 'INFORMATION_SCHEMA' "
            f"ORDER BY table_schema, table_name, ordinal_position")
        for schema, table, col, dtype, nullable in cols:
            self._cols.setdefault(f"{schema}.{table}", []).append(
                (col, dtype, "YES" if str(nullable).upper().startswith("Y") else "NO"))

        self._schemas = sorted({m.schema for m in self._tables.values()})

    def _raw(self, sql: str) -> list[tuple]:
        """Catalog query: not counted against the episode budget, not cancellable."""
        cur = self.con.cursor()
        try:
            cur.execute(sql)
            return cur.fetchall()
        finally:
            cur.close()

    # ── quoting / name resolution ─────────────────────────────────────────
    @staticmethod
    def _q(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    def _qname(self, *parts: str) -> str:
        return ".".join(SnowflakeDatabase._q(p) for p in parts)

    def _fq(self, meta: _TableMeta) -> str:
        """Fully qualified, so the session's CURRENT_SCHEMA never matters."""
        return self._qname(self.db_id, meta.schema, meta.table)

    def _resolve(self, name: str) -> _TableMeta:
        """exact -> case-insensitive -> unique bare table name -> ValueError.

        The error text goes straight back to the model as a tool result, so it names
        the candidates instead of just refusing.
        """
        if name in self._tables:
            return self._tables[name]

        lowered = name.lower()
        exact_ci = [m for k, m in self._tables.items() if k.lower() == lowered]
        if len(exact_ci) == 1:
            return exact_ci[0]

        bare = [m for m in self._tables.values() if m.table.lower() == lowered]
        if len(bare) == 1:
            return bare[0]
        if len(bare) > 1:
            opts = ", ".join(self._qname(m.schema, m.table) for m in bare[:8])
            raise ValueError(
                f"Table name {name!r} is ambiguous across schemas. Use one of: {opts}")

        # substring first (partial names), then fuzzy (typos): this message is
        # what the model gets back, so it should be enough to recover from.
        near = [k for k in self._tables if lowered in k.lower()]
        pool = list(self._tables) + sorted(
            {m.table for m in self._tables.values()})
        for cand in difflib.get_close_matches(name, pool, n=5, cutoff=0.5):
            if cand not in near:
                near.append(cand)
        hint = ("Did you mean: " + ", ".join(near[:8]) + ". ") if near else ""
        raise ValueError(
            f"Unknown table {name!r} in database {self.db_id}. {hint}"
            f"Use list_tables() for the full list; names are case-sensitive and must "
            f"be double-quoted exactly as shown.")

    # ── DatabaseLike: catalog ─────────────────────────────────────────────
    def list_tables(self) -> list[str]:
        """Bare names in a single-schema database (reads like the SQLite lane),
        SCHEMA.TABLE otherwise -- multi-schema is the common case for the
        BigQuery-derived databases. Zero queries: served from the prefetch."""
        if len(self._schemas) <= 1:
            return sorted(m.table for m in self._tables.values())
        return sorted(self._tables)

    def _columns(self, table: str) -> list[tuple[str, str, str]]:
        meta = self._resolve(table)
        cols = self._cols.get(meta.qualified, [])
        if not cols:
            raise ValueError(f"No columns found for {meta.qualified!r}.")
        return cols

    # ── DatabaseLike: query execution ─────────────────────────────────────
    def _execute_bounded(self, sql: str, timeout_s: float):
        """execute_async + deadline + cancel().

        Async rather than a timer thread because it yields the query id *before* the
        query finishes, so a runaway query is cancellable by id and still lands in the
        trace when it times out.
        """
        self.budget.check()
        cur = self.con.cursor()
        started = time.time()
        qid = None
        try:
            cur.execute_async(sql)
            qid = cur.sfqid
            deadline = started + timeout_s
            while self.con.is_still_running(self.con.get_query_status(qid)):
                if time.time() > deadline:
                    cur.cancel()
                    self.budget.timeouts += 1
                    raise TimeoutError(
                        f"query cancelled after {timeout_s:.0f}s (query_id={qid}). "
                        f"Add filters or a LIMIT, or query a smaller table.")
                time.sleep(0.25)
            self.con.get_query_status_throw_if_error(qid)
            cur.get_results_from_sfqid(qid)
            return cur
        finally:
            self.budget.record(qid, time.time() - started)

    def _fetch_capped(self, cur, max_rows: int) -> tuple[pd.DataFrame, bool]:
        """Fetch at most max_rows+1 rows, so a huge result is bounded and we still
        know it was truncated. fetch_pandas_all() would pull the whole thing."""
        rows = cur.fetchmany(max_rows + 1)
        names = [d[0] for d in cur.description]
        truncated = len(rows) > max_rows
        df = pd.DataFrame(rows[:max_rows], columns=names)
        return self._render_binary(df), truncated

    def _render_binary(self, df: pd.DataFrame) -> pd.DataFrame:
        """Hex-encode real BINARY values. db.py's _decode_bytes exists only for
        SQLite's untyped columns; Snowflake is typed, so bytes here are genuinely
        binary and UTF-8-replace would corrupt them."""
        for c in df.columns:
            if df[c].dtype == object and df[c].map(
                    lambda v: isinstance(v, (bytes, bytearray))).any():
                df[c] = df[c].map(
                    lambda v: bytes(v).hex() if isinstance(v, (bytes, bytearray)) else v)
        return df

    def query(self, sql: str, max_rows: int = 100) -> pd.DataFrame:
        cur = self._execute_bounded(sql, self.cfg.statement_timeout_s)
        try:
            df, _ = self._fetch_capped(cur, max_rows)
            return df
        finally:
            cur.close()

    def query_preview(self, sql: str, preview_rows: int, max_rows: int,
                      cell_char_limit: int = 1024,
                      timeout_s: float = 90.0) -> tuple[pd.DataFrame, str]:
        timeout_s = min(timeout_s, self.cfg.statement_timeout_s)
        cur = self._execute_bounded(sql, timeout_s)
        try:
            df, truncated = self._fetch_capped(cur, max_rows)
        finally:
            cur.close()
        preview = df.head(preview_rows).map(lambda v: _trim_cell(v, cell_char_limit))
        csv = preview.to_csv(index=False)
        if truncated:
            csv += (f"\n[showing {len(preview)} rows; result exceeded the "
                    f"{max_rows}-row cap and was truncated - narrow the query]")
        elif len(df) > preview_rows:
            csv += f"\n[showing {len(preview)} of {len(df)} rows]"
        return df, csv

    # ── DatabaseLike: inspection ──────────────────────────────────────────
    def _cache_path(self, meta: _TableMeta) -> Path | None:
        if not self.cfg.describe_cache_dir:
            return None
        d = Path(self.cfg.describe_cache_dir) / self.db_id
        return d / f"{meta.schema}.{meta.table}.json"

    def list_views(self) -> list[str]:
        """INFORMATION_SCHEMA.TABLES was already prefetched with table_type, so the
        views are known; they are listed by list_tables() alongside the tables
        because a view is queryable identically."""
        return []

    @property
    def find_value_enabled(self) -> bool:
        return getattr(self.cfg, "find_value_enabled", True)

    def describe_table(self, table: str, sample_rows: int = 5,
                       context=None, notes: bool = True) -> str:
        meta = self._resolve(table)
        cache = self._cache_path(meta)
        if cache and cache.exists():
            try:
                return json.loads(cache.read_text(encoding="utf-8"))["text"]
            except Exception:
                pass                            # corrupt cache entry: just recompute

        text = self._describe_uncached(meta, sample_rows)
        if cache:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps({"text": text}), encoding="utf-8")
            except Exception:
                pass                            # caching is best-effort
        return text

    def _describe_uncached(self, meta: _TableMeta, sample_rows: int) -> str:
        cols = self._columns(meta.qualified)
        fq = self._fq(meta)
        rc = meta.row_count
        head = (f"table: {self._qname(meta.schema, meta.table)}  "
                f"({'row count unknown' if rc is None else f'{rc} rows'}"
                f"{'' if meta.kind == 'BASE TABLE' else ', ' + meta.kind.lower()})")
        lines = [head, "columns:"]

        stats = {}
        too_big = (rc is None
                   or rc > self.cfg.stats_row_limit
                   or (meta.n_bytes or 0) > self.cfg.stats_bytes_limit)
        if rc and not too_big:
            # APPROX_COUNT_DISTINCT (HLL), not COUNT(DISTINCT CAST(c AS VARCHAR)):
            # the exact form is a full re-encode of every value in every column.
            aggs = ", ".join(
                f"APPROX_COUNT_DISTINCT({self._q(c)}), "
                f"COUNT(*) - COUNT({self._q(c)})" for c, _, _ in cols)
            try:
                row = self.query(f"SELECT {aggs} FROM {fq}", max_rows=1)
                if len(row):
                    vals = row.iloc[0].tolist()
                    for i, (c, _, _) in enumerate(cols):
                        stats[c] = (vals[2 * i], vals[2 * i + 1])
            except Exception:
                pass                            # stats are best-effort, as in db.py

        for name, dtype, nullable in cols:
            extra = ""
            if name in stats:
                nd, nn = stats[name]
                extra = f"  ~distinct={nd} nulls={nn}"
            lines.append(f"  {name}  {dtype}  nullable={nullable}{extra}")

        if too_big:
            lines.append("[distinct/null stats skipped: table too large to profile "
                         "cheaply - use get_column_values on a specific column]")

        if rc != 0:
            try:
                sample = self.query(f"SELECT * FROM {fq} LIMIT {int(sample_rows)}",
                                    max_rows=sample_rows)
                sample = sample.map(lambda v: _trim_cell(v, 200))
                lines.append(f"sample rows:\n{sample.to_csv(index=False)}")
            except Exception as e:
                lines.append(f"sample rows unavailable: {e}")
        return "\n".join(lines)

    def get_column_values(self, table: str, column: str, limit: int = 20) -> str:
        meta = self._resolve(table)
        cols = {c for c, _, _ in self._columns(meta.qualified)}
        if column not in cols:
            ci = [c for c in cols if c.lower() == column.lower()]
            if len(ci) == 1:
                column = ci[0]
            else:
                raise ValueError(f"Unknown column {column!r} in {meta.qualified!r}. "
                                 f"Columns: {sorted(cols)}")
        fq, qc = self._fq(meta), self._q(column)
        # one query for both the top values and the approximate cardinality
        df = self.query(
            f"SELECT {qc} AS value, COUNT(*) AS count FROM {fq} "
            f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {int(limit)}", max_rows=limit)
        out = df.to_csv(index=False)
        try:
            total = self.query(f"SELECT APPROX_COUNT_DISTINCT({qc}) FROM {fq}",
                               max_rows=1).iloc[0, 0]
            if total is not None and int(total) > limit:
                out += f"[showing {limit} of ~{int(total)} distinct values]"
        except Exception:
            pass
        return out

    def find_value(self, term: str, table: str | None = None,
                   column: str | None = None, limit: int = 10,
                   max_columns: int = 200) -> str:
        """One sampled UNION ALL query per table, not one query per column.

        db.py's version issues up to 200 separate ILIKE queries; here that would be
        200 warehouse scans. On a large database a table must be named.
        """
        if not self.cfg.find_value_enabled:
            return ("ERROR: find_value is disabled for this run (too expensive on "
                    "warehouse-scale tables). Use get_column_values on a column you "
                    "picked from describe_table instead.")

        if table:
            metas = [self._resolve(table)]
        else:
            biggest = max((m.row_count or 0) for m in self._tables.values()) \
                if self._tables else 0
            if biggest > self.cfg.find_value_require_table_above_rows:
                return (f"ERROR: this database has tables up to {biggest} rows, so an "
                        f"all-table value search is too expensive. Call find_value "
                        f"with table='<name>' (see list_tables/describe_table first).")
            metas = sorted(self._tables.values(), key=lambda m: m.row_count or 0)

        hits, scanned = [], 0
        for meta in metas:
            text_cols = [c for c, dtype, _ in self._columns(meta.qualified)
                         if any(k in dtype.upper()
                                for k in ("CHAR", "TEXT", "STRING", "VARIANT"))
                         and (column is None or c == column)]
            if not text_cols:
                continue
            for chunk_start in range(0, len(text_cols),
                                     self.cfg.find_value_max_columns_per_query):
                chunk = text_cols[chunk_start:chunk_start
                                  + self.cfg.find_value_max_columns_per_query]
                scanned += len(chunk)
                if scanned > max_columns:
                    hits.append(f"[stopped: {max_columns}-column cap reached; "
                                f"narrow with table=/column=]")
                    return "\n".join(hits)
                # TABLESAMPLE bounds the scan; a miss here means "not in the sample",
                # which the footer states rather than implying absence.
                src = (f"{self._fq(meta)} SAMPLE ROW "
                       f"({int(self.cfg.find_value_scan_rows)} ROWS)")
                branches = " UNION ALL ".join(
                    f"SELECT '{c}' AS col, CAST({self._q(c)} AS VARCHAR) AS value, "
                    f"COUNT(*) AS n FROM {src} "
                    f"WHERE CAST({self._q(c)} AS VARCHAR) ILIKE '%{term}%' "
                    f"GROUP BY 2 LIMIT {int(limit)}" for c in chunk)
                try:
                    df = self.query(branches, max_rows=limit)
                except Exception as e:
                    hits.append(f"[{meta.qualified}: search failed: {e}]")
                    continue
                for _, r in df.iterrows():
                    hits.append(f"{meta.qualified}.{r['COL']} = {r['VALUE']!r}  "
                                f"({r['N']} sampled rows)")
                if len(hits) >= limit:
                    return ("\n".join(hits[:limit])
                            + "\n[hit limit; refine the term]")

        if not hits:
            return (f"no sampled cell values matching {term!r} found "
                    f"(searched a {self.cfg.find_value_scan_rows}-row sample per "
                    f"table, so rare values can be missed)")
        return "\n".join(hits)
