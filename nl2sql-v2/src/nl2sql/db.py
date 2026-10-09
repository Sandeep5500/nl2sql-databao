"""DuckDB wrapper over a Spider2 local SQLite database, plus deterministic
schema/value inspection used by the dbtools."""

from pathlib import Path

import os

import duckdb
import pandas as pd


def _decode_bytes(df: pd.DataFrame) -> pd.DataFrame:
    """SQLite columns with no declared type come back from DuckDB's scanner as
    bytes/bytearray objects; decode them so the model and the scorer both see
    text (official eval runs on SQLite, which returns plain str)."""
    for c in df.columns:
        if df[c].dtype == object and df[c].map(
                lambda v: isinstance(v, (bytes, bytearray))).any():
            df[c] = df[c].map(
                lambda v: bytes(v).decode("utf-8", "replace")
                if isinstance(v, (bytes, bytearray)) else v)
    return df


def _trim_cell(value, limit: int):
    s = str(value)
    if len(s) <= limit:
        return value
    keep = limit - 15
    front = int(keep * 0.7)
    return s[:front] + "[...trimmed...]" + s[front - keep:]


MEMORY_LIMIT = os.environ.get("NL2SQL_DUCKDB_MEMORY", "3GB")


def _configure(con) -> None:
    """Engine settings applied to every connection.

    - cte_inlining off: with it on, DuckDB's sqlite scanner fails valid queries
      that join over CTEs and end in LIMIT ("INTERNAL Error: Attempted to access
      index 0 within vector of size 0").
    - memory_limit: a runaway query returns an error to the agent instead of
      getting the whole benchmark process killed by the job's memory cgroup.
    """
    con.execute("SET disabled_optimizers='cte_inlining'")
    con.execute(f"SET memory_limit='{MEMORY_LIMIT}'")


def _run(con, sql: str) -> pd.DataFrame:
    rel = con.execute(sql)
    if rel is None or rel.description is None:
        raise ValueError("The SQL contained no statement that returns rows "
                         "(empty or comment-only query).")
    return rel.df()


class Database:
    def __init__(self, sqlite_path: Path):
        self.sqlite_path = sqlite_path
        self.con = duckdb.connect(":memory:")
        self.con.execute("INSTALL sqlite; LOAD sqlite;")
        _configure(self.con)
        self.con.execute(f"ATTACH '{sqlite_path}' AS db (TYPE sqlite, READ_ONLY)")
        self.con.execute("USE db")

    def close(self):
        self.con.close()
        if getattr(self, "_av", None) is not None:
            self._av.close()

    def _all_varchar_con(self):
        """Fallback connection reading every SQLite column as text — survives
        columns declared INTEGER that store text, which crash the normal scan."""
        if getattr(self, "_av", None) is None:
            av = duckdb.connect(":memory:")
            av.execute("INSTALL sqlite; LOAD sqlite;")
            _configure(av)
            av.execute("SET GLOBAL sqlite_all_varchar=true")
            av.execute(f"ATTACH '{self.sqlite_path}' AS db (TYPE sqlite, READ_ONLY)")
            av.execute("USE db")
            self._av = av
        return self._av

    # ── raw query ─────────────────────────────────────────────────────────
    def query(self, sql: str, max_rows: int = 100) -> pd.DataFrame:
        return _decode_bytes(_run(self.con, sql).head(max_rows))

    def query_preview(self, sql: str, preview_rows: int, max_rows: int,
                      cell_char_limit: int = 1024,
                      timeout_s: float = 90.0) -> tuple[pd.DataFrame, str]:
        """Run SQL; return (full df capped at max_rows, csv preview of preview_rows).

        Runaway-query guard: interrupt after timeout_s so a pathological join
        surfaces as a tool error instead of hanging the episode."""
        import threading
        timer = threading.Timer(timeout_s, self.con.interrupt)
        timer.start()
        av_note = ""
        try:
            df = _decode_bytes(_run(self.con, sql))
        except Exception as e:
            timer.cancel()
            if "Mismatch Type Error" not in str(e):
                raise
            # mistyped column (INTEGER-declared storing text): retry with all
            # columns as text; numeric ops need TRY_CAST, which the hint says.
            av = self._all_varchar_con()
            timer = threading.Timer(timeout_s, av.interrupt)
            timer.start()
            try:
                df = _decode_bytes(_run(av, sql))
                av_note = ("\n[note: this table has mixed-typed columns; all values "
                           "were read as TEXT — use TRY_CAST(col AS DOUBLE) for math]")
            except Exception as e2:
                raise RuntimeError(
                    f"{e2} [hint: this table has mixed-typed columns readable only "
                    f"as TEXT — wrap numeric columns in TRY_CAST(col AS DOUBLE)]") from e2
            finally:
                timer.cancel()
        finally:
            timer.cancel()
        total = len(df)
        df = df.head(max_rows)
        preview = df.head(preview_rows).map(lambda v: _trim_cell(v, cell_char_limit))
        csv = preview.to_csv(index=False)
        if total > preview_rows:
            csv += f"\n[showing {len(preview)} of {total} rows]"
        csv += av_note
        return df, csv

    # ── catalog helpers ───────────────────────────────────────────────────
    def list_tables(self) -> list[str]:
        # sqlite_master, not information_schema: the latter prepares every view
        # definition, and some Spider2 DBs (e.g. stacking) contain views DuckDB's
        # sqlite scanner cannot parse.
        rows = self.con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]

    def list_views(self) -> list[str]:
        """Views the agent can query like tables (e.g. complex_oracle's `profits`).

        Names come from SQLite directly: asking DuckDB for the view catalog fails
        for the whole database when any single view has a definition it cannot
        parse (stacking, oracle_sql). Views DuckDB cannot read are left out."""
        import sqlite3
        try:
            src = sqlite3.connect(f"file:{self.sqlite_path}?mode=ro", uri=True)
            names = [r[0] for r in src.execute(
                "SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY name")]
            src.close()
        except Exception:
            return []
        readable = []
        for name in names:
            try:
                self._columns(name)
                readable.append(name)
            except Exception:
                continue
        return readable

    def _columns(self, table: str) -> list[tuple[str, str, str]]:
        """[(name, type, is_nullable)] — raises ValueError on unknown table."""
        try:
            rows = self.con.execute(
                "SELECT name, type, CASE WHEN \"notnull\" THEN 'NO' ELSE 'YES' END "
                "FROM pragma_table_info(?)", [table],
            ).fetchall()
        except Exception:
            rows = []
        if not rows:
            raise ValueError(f"Unknown table: {table!r}. Use list_tables() to see valid names.")
        return rows

    @staticmethod
    def _q(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    def describe_table(self, table: str, sample_rows: int = 5,
                       stats_row_limit: int = 2_000_000, context=None,
                       notes: bool = True) -> str:
        """`context` is an optional nl2sql.context.TableContext; when given, the
        output also carries the context engine's declared keys and descriptions."""
        cols = self._columns(table)
        qt = self._q(table)
        n_rows = self.con.execute(f"SELECT COUNT(*) FROM {qt}").fetchone()[0]

        lines = [f"table: {table}  ({n_rows} rows)", "columns:"]
        stats = {}
        if n_rows and n_rows <= stats_row_limit:
            # CAST to VARCHAR first: SQLite's loose typing lets text like ""
            # live in numeric columns, which the scanner otherwise chokes on.
            aggs = ", ".join(
                f"COUNT(DISTINCT CAST({self._q(c)} AS VARCHAR)), "
                f"SUM(CASE WHEN {self._q(c)} IS NULL THEN 1 ELSE 0 END)"
                for c, _, _ in cols
            )
            try:
                vals = self.con.execute(f"SELECT {aggs} FROM {qt}").fetchone()
                for i, (c, _, _) in enumerate(cols):
                    stats[c] = (vals[2 * i], vals[2 * i + 1])
            except Exception:
                pass  # stats are best-effort
        for name, dtype, nullable in cols:
            extra = ""
            if name in stats:
                nd, nn = stats[name]
                extra = f"  distinct={nd} nulls={nn}"
            prof = context.profile(table, name) if context is not None else ""
            lines.append(f"  {name}  {dtype}  nullable={nullable}{extra}"
                         + (f"  | {prof}" if prof else ""))

        if context is not None:
            keys = context.key_lines(table)
            fks = context.foreign_keys(table)
            if fks:
                keys.append("foreign keys (declared): " + "; ".join(fks))
            lines[1:1] = keys

        if n_rows:
            select = ", ".join(f"CAST({self._q(c)} AS VARCHAR) AS {self._q(c)}"
                               for c, _, _ in cols)
            try:
                sample = self.con.execute(
                    f"SELECT {select} FROM {qt} LIMIT {sample_rows}").df()
                sample = sample.map(lambda v: _trim_cell(v, 200))
                lines.append(f"sample rows:\n{sample.to_csv(index=False)}")
            except Exception as e:
                lines.append(f"sample rows unavailable: {e}")
        if context is not None and notes:
            explored = context.explored_notes(table)
            if explored:
                lines.append("notes (written by an LLM after querying this table; they "
                             "can still be wrong — the facts above take precedence):\n"
                             + explored)
            else:
                old = context.notes(table)
                if old:
                    lines.append("notes (from the context engine's records; they can "
                                 "be wrong — the facts above take precedence):\n" + old)
        return "\n".join(lines)

    def get_column_values(self, table: str, column: str, limit: int = 20) -> str:
        cols = {c for c, _, _ in self._columns(table)}
        if column not in cols:
            raise ValueError(f"Unknown column {column!r} in table {table!r}. "
                             f"Columns: {sorted(cols)}")
        qt, qc = self._q(table), self._q(column)
        df = self.con.execute(
            f"SELECT {qc} AS value, COUNT(*) AS count FROM {qt} "
            f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {int(limit)}"
        ).df()
        df = _decode_bytes(df)
        total = self.con.execute(f"SELECT COUNT(DISTINCT {qc}) FROM {qt}").fetchone()[0]
        out = df.to_csv(index=False)
        if total > limit:
            out += f"[showing {limit} of {total} distinct values]"
        return out

    def find_value(self, term: str, table: str | None = None, column: str | None = None,
                   limit: int = 10, max_columns: int = 200) -> str:
        """Search text columns for cells containing `term` (case-insensitive)."""
        tables = [table] if table else self.list_tables()
        hits, scanned = [], 0
        for t in tables:
            try:
                cols = self._columns(t)
            except ValueError:
                raise
            for c, dtype, _ in cols:
                if column and c != column:
                    continue
                if not any(k in dtype.upper() for k in ("CHAR", "TEXT", "STRING", "VARCHAR")):
                    continue
                scanned += 1
                if scanned > max_columns:
                    hits.append(f"[stopped: scanned {max_columns}-column cap; "
                                f"narrow with table=/column=]")
                    return "\n".join(hits) if hits else "no matches"
                rows = self.con.execute(
                    f"SELECT {self._q(c)}, COUNT(*) FROM {self._q(t)} "
                    f"WHERE {self._q(c)} ILIKE ? GROUP BY 1 LIMIT {int(limit)}",
                    [f"%{term}%"],
                ).fetchall()
                for value, count in rows:
                    if isinstance(value, (bytes, bytearray)):
                        value = bytes(value).decode("utf-8", "replace")
                    hits.append(f"{t}.{c} = {value!r}  ({count} rows)")
                if len(hits) >= limit:
                    return "\n".join(hits[:limit]) + "\n[hit limit; refine the term]"
        return "\n".join(hits) if hits else f"no cell values matching {term!r} found"
