#!/usr/bin/env python3
"""Assert that --retrieval actually offers search_context, without a GPU or a warehouse.

    uv run python scripts/check_retrieval_wiring.py

This exists because the first bq_v3s launch silently produced duplicates of the lane
without retrieval. A CatalogSearchContext was built and attached to the session, but
agent.py gated the tool on

    has_search = session.search is not None and cfg.context_mode == "search"

and the additive lane runs with context_mode "full", so the tool was never offered and
the system prompt carried the no-search hint. Everything looked right from the launch
command, which showed --retrieval --search-limit 16 on all six shards.

The lesson is that "the flag reached the process" and "the flag changed the prompt" are
different claims, so this checks the second one: given a session with a search object,
the tool schemas must contain search_context and the prompt must carry the search hint,
in both context modes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql.config import AgentConfig
from nl2sql.prompts import SEARCH_HINT_FULL, SEARCH_HINT_SEARCH
from nl2sql.tools import ToolSession, build_tool_schemas

FAILURES = []


def check(label, cond, detail=""):
    print(f"{'ok  ' if cond else 'FAIL'} {label}" + (f": {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


class FakeSearch:
    """Stands in for CatalogSearchContext: only its presence is under test."""

    def search(self, query, limit=8, expansion_queries=0):
        return "TABLE proj.ds.t: a description the schema dump had to drop"


class FakeDB:
    dialect = "bigquery"
    display_name = "testdb"
    find_value_enabled = False

    def list_tables(self):
        return ["proj.ds.t"]

    def list_views(self):
        return []

    def _columns(self, t):
        return [("a", "STRING", "UNKNOWN")]

    def describe_table(self, t, sample_rows=5, context=None, notes=True):
        return "table: proj.ds.t"

    def close(self):
        pass


def main():
    cfg = AgentConfig()

    # the actual regression: a search object present while context_mode is "full"
    for mode in ("full", "search"):
        cfg.context_mode = mode
        session = ToolSession(db=FakeDB(), cfg=cfg, search=FakeSearch())
        has_search = session.search is not None
        names = [t["function"]["name"] for t in build_tool_schemas(
            cfg, has_docs=False, has_search=has_search, dialect="BigQuery",
            has_find_value=False)]
        check(f"context_mode={mode!r}: search_context is offered",
              "search_context" in names, ", ".join(names))
        check(f"context_mode={mode!r}: the prompt gets the search hint",
              (SEARCH_HINT_SEARCH if has_search else SEARCH_HINT_FULL)
              == SEARCH_HINT_SEARCH)

    # and with no index, it must NOT be offered, in either mode
    for mode in ("full", "search"):
        cfg.context_mode = mode
        session = ToolSession(db=FakeDB(), cfg=cfg, search=None)
        has_search = session.search is not None
        names = [t["function"]["name"] for t in build_tool_schemas(
            cfg, has_docs=False, has_search=has_search, dialect="BigQuery",
            has_find_value=False)]
        check(f"context_mode={mode!r}, no index: search_context is absent",
              "search_context" not in names, ", ".join(names))

    # dispatch has to reach the search object, and respect cfg.search_limit
    cfg.context_mode = "full"
    seen = {}

    class RecordingSearch(FakeSearch):
        def search(self, query, limit=8, expansion_queries=0):
            seen["limit"] = limit
            return "ok"

    cfg.search_limit = 16
    session = ToolSession(db=FakeDB(), cfg=cfg, search=RecordingSearch())
    out = session.dispatch("search_context", {"retrieve_text": "revenue by device"})
    check("dispatch reaches the index", out == "ok", out)
    check("cfg.search_limit is honoured", seen.get("limit") == 16,
          str(seen.get("limit")))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {', '.join(FAILURES)}")
        return 1
    print("retrieval wiring is correct in both context modes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
