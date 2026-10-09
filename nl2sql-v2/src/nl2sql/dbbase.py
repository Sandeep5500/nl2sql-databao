"""The database contract the dbtools dispatch against.

`tools.py` is already structurally typed — every branch of `ToolSession._dispatch`
is `self.db.<method>(...)`, and nothing inspects the concrete class. So a Protocol
is enough to let a Snowflake (or plain-DuckDB) backend drop in, and unlike an ABC
it changes no runtime behaviour in the SQLite lane, which is the published baseline.

`_columns` keeps its underscore: it is de-facto public (run_benchmark.py's
oracle_context and schema_overview both call it), and renaming it buys nothing.
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class DatabaseLike(Protocol):
    # `display_name` replaces reaching into `.sqlite_path.stem`; `dialect` keys
    # into prompts.DIALECTS so the system prompt describes the right SQL.
    display_name: str
    dialect: str

    def query(self, sql: str, max_rows: int = 100) -> pd.DataFrame: ...

    def query_preview(self, sql: str, preview_rows: int, max_rows: int,
                      cell_char_limit: int = 1024,
                      timeout_s: float = 90.0) -> tuple[pd.DataFrame, str]: ...

    def list_tables(self) -> list[str]: ...

    def _columns(self, table: str) -> list[tuple[str, str, str]]:
        """[(name, type, is_nullable)] — raises ValueError on unknown table."""
        ...

    def describe_table(self, table: str, sample_rows: int = 5,
                       context=None, notes: bool = True) -> str:
        """`context` is an optional nl2sql.context.TableContext (declared keys and
        descriptions from the context engine). Backends with no such material
        accept it and ignore it, so tools.py never has to branch on dialect."""
        ...

    def list_views(self) -> list[str]:
        """Views the agent may query like tables. [] when the backend has none or
        cannot tell them apart from tables."""
        ...

    def get_column_values(self, table: str, column: str, limit: int = 20) -> str: ...

    def find_value(self, term: str, table: str | None = None,
                   column: str | None = None, limit: int = 10,
                   max_columns: int = 200) -> str: ...

    def close(self) -> None: ...


class BudgetExhausted(RuntimeError):
    """Raised instead of running another query. ToolSession.dispatch turns this into
    a tool error, so the agent can still submit a stored query_id."""


@dataclass
class QueryBudget:
    """Per-episode spend cap. Counted in the trace and in the results CSV so a run
    that burned credits without answering anything is visible at a glance."""

    max_queries: int = 60
    max_seconds: float = 900.0
    queries: int = 0
    seconds: float = 0.0
    timeouts: int = 0        # cancelled queries: an execution failure, not a
                             # wrong answer, so it is reported separately
    query_ids: list[str] = field(default_factory=list)

    def check(self) -> None:
        if self.queries >= self.max_queries:
            raise BudgetExhausted(
                f"query budget exhausted ({self.queries} queries used for this "
                f"question). Submit your best existing query_id with submit_result.")
        if self.seconds >= self.max_seconds:
            raise BudgetExhausted(
                f"time budget exhausted ({self.seconds:.0f}s of warehouse time used). "
                f"Submit your best existing query_id with submit_result.")

    def record(self, query_id: str | None, elapsed: float) -> None:
        self.queries += 1
        self.seconds += elapsed
        if query_id:
            self.query_ids.append(query_id)
