"""Tool schemas (OpenAI function-calling format) and dispatch."""

import json
from dataclasses import dataclass, field

import pandas as pd

from .config import AgentConfig
from .db import Database


def build_tool_schemas(cfg: AgentConfig, has_docs: bool, has_search: bool,
                       has_draft: bool = False) -> list[dict]:
    def fn(name, desc, props, required):
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required},
        }}

    tools = [
        fn("run_sql_query",
           "Run one DuckDB SELECT query against the database. Returns a CSV preview "
           f"(default {cfg.preview_rows_default} rows, max {cfg.preview_rows_max}) plus a "
           "query_id you can pass to submit_result. The full result (up to "
           f"{cfg.result_rows_max} rows) is stored for submission.",
           {"sql": {"type": "string", "description": "A single DuckDB SELECT statement."},
            "preview_rows": {"type": "integer",
                             "description": f"Rows to show (1-{cfg.preview_rows_max}). "
                                            f"Default {cfg.preview_rows_default}."}},
           ["sql"]),
        fn("list_tables", "List all table names in the database.", {}, []),
        fn("describe_table",
           "Exact schema of one table: columns with types, nullability, distinct/null "
           "counts, row count, and 5 sample rows. Use this to verify columns before "
           "writing SQL — it is ground truth, unlike search results.",
           {"table": {"type": "string"}}, ["table"]),
        fn("get_column_values",
           "Top distinct values of a column with occurrence counts. Use before writing "
           "a WHERE filter to see how values are actually stored.",
           {"table": {"type": "string"}, "column": {"type": "string"},
            "limit": {"type": "integer", "description": "Max values (default 20)."}},
           ["table", "column"]),
        fn("find_value",
           "Find which table/column contains a given text value (case-insensitive "
           "substring search across text columns). Use when the question mentions a "
           "name/code/label and you don't know where it lives or how it is spelled.",
           {"term": {"type": "string"},
            "table": {"type": "string", "description": "Optional: restrict to one table."},
            "column": {"type": "string", "description": "Optional: restrict to one column."}},
           ["term"]),
        fn("submit_result",
           "Submit the stored result of a previous run_sql_query as the final answer. "
           "Must be your only tool call in the message.",
           {"query_id": {"type": "string"},
            "result_description": {"type": "string",
                                   "description": "One-sentence summary of the answer."}},
           ["query_id", "result_description"]),
    ]
    if has_search:
        tools.append(fn(
            "search_context",
            "Semantic + keyword search over curated schema documentation (table/column "
            "descriptions with sample values). Best first step to locate relevant tables.",
            {"retrieve_text": {"type": "string",
                               "description": "Natural-language description of what you need."}},
            ["retrieve_text"]))
    if has_draft:
        tools.append(fn(
            "draft_sql",
            "Ask a specialist SQL model for a complete draft query. It sees the full "
            "schema and your request, and returns SQL. Call it EARLY with the full "
            "question (or a precise sub-question) to get a strong starting draft — "
            "then verify the draft with run_sql_query and refine it yourself. The "
            "draft is written in SQLite dialect and may need small DuckDB fixes.",
            {"request": {"type": "string",
                         "description": "The question or precise instruction for the "
                                        "specialist, including any needed definitions "
                                        "from the documentation."}},
            ["request"]))
    if has_docs:
        tools.append(fn(
            "read_documentation",
            "Read the external knowledge document provided with this question (formulas, "
            "business definitions). If a document exists, you should read it before "
            "answering.", {}, []))
    return tools


@dataclass
class ToolSession:
    db: Database
    cfg: AgentConfig
    search: object | None = None          # SearchContext
    doc_text: str | None = None
    draft: object | None = None           # DraftSQL (specialist model client)
    query_results: dict = field(default_factory=dict)  # query_id -> (sql, df)
    search_calls: int = 0
    draft_calls: int = 0
    _query_counter: int = 0

    def dispatch(self, name: str, args: dict) -> str:
        try:
            return self._dispatch(name, args)
        except Exception as e:  # tool errors go back to the model, not up the stack
            return f"ERROR: {type(e).__name__}: {e}"

    def _dispatch(self, name: str, args: dict) -> str:
        cfg = self.cfg
        if name == "run_sql_query":
            preview = min(int(args.get("preview_rows") or cfg.preview_rows_default),
                          cfg.preview_rows_max)
            df, csv = self.db.query_preview(args["sql"], preview, cfg.result_rows_max,
                                            cfg.cell_char_limit)
            self._query_counter += 1
            qid = f"q{self._query_counter}"
            self.query_results[qid] = (args["sql"], df)
            return f"query_id='{qid}'\n{csv}"
        if name == "list_tables":
            return "\n".join(self.db.list_tables())
        if name == "describe_table":
            return self.db.describe_table(args["table"])
        if name == "get_column_values":
            return self.db.get_column_values(args["table"], args["column"],
                                             int(args.get("limit") or 20))
        if name == "find_value":
            return self.db.find_value(args["term"], args.get("table"),
                                      args.get("column"),
                                      max_columns=cfg.find_value_max_columns)
        if name == "search_context":
            if self.search is None:
                return "ERROR: search_context is not available in this run."
            self.search_calls += 1
            return self.search.search(args["retrieve_text"], limit=cfg.search_limit,
                                      expansion_queries=cfg.expansion_queries)
        if name == "read_documentation":
            return self.doc_text or "No documentation is attached to this question."
        if name == "draft_sql":
            if self.draft is None:
                return "ERROR: draft_sql is not available in this run."
            self.draft_calls += 1
            return self.draft.draft(args["request"])
        raise ValueError(f"unknown tool {name!r}")

    def get_submission(self, query_id: str) -> tuple[str, pd.DataFrame] | None:
        return self.query_results.get(query_id)


def parse_tool_args(raw: str) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {"__parse_error__": raw}
