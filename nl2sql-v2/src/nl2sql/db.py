"""DuckDB wrapper over a Spider2 local SQLite database, plus deterministic
schema/value inspection used by the dbtools."""

from pathlib import Path

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


class Database:
    def __init__(self, sqlite_path: Path):
        self.sqlite_path = sqlite_path
        self.con = duckdb.connect(":memory:")
        self.con.execute("INSTALL sqlite; LOAD sqlite;")
        self.con.execute(f"ATTACH '{sqlite_path}' AS db (TYPE sqlite, READ_ONLY)")
        self.con.execute("USE db")

    def close(self):
        self.con.close()

    # ── raw query ─────────────────────────────────────────────────────────
    def query(self, sql: str, max_rows: int = 100) -> pd.DataFrame:
        return _decode_bytes(self.con.execute(sql).df().head(max_rows))

    def query_preview(self, sql: str, preview_rows: int, max_rows: int,
                      cell_char_limit: int = 1024,
                      timeout_s: float = 90.0) -> tuple[pd.DataFrame, str]:
        """Run SQL; return (full df capped at max_rows, csv preview of preview_rows).

        Runaway-query guard: interrupt after timeout_s so a pathological join
        surfaces as a tool error instead of hanging the episode."""
        import threading
        timer = threading.Timer(timeout_s, self.con.interrupt)
        timer.start()
        try:
            df = _decode_bytes(self.con.execute(sql).df())
        finally:
            timer.cancel()
        total = len(df)
        df = df.head(max_rows)
        preview = df.head(preview_rows).map(lambda v: _trim_cell(v, cell_char_limit))
        csv = preview.to_csv(index=False)
        if total > preview_rows:
            csv += f"\n[showing {len(preview)} of {total} rows]"
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
                       stats_row_limit: int = 2_000_000) -> str:
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
            lines.append(f"  {name}  {dtype}  nullable={nullable}{extra}")

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
