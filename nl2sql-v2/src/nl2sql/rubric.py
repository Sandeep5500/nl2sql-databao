"""Rubric agent: a short planning pass that describes the SHAPE of the final
result table (row grain, row count, columns, types, formats) before the main
agent writes any SQL. By default it has schema-inspection tools only (no SQL,
so it cannot compute the answer); with_sql=True also gives it run_sql_query."""

import json
import time

from openai import OpenAI

from .config import AgentConfig, LLMConfig
from .tools import ToolSession, build_tool_schemas, parse_tool_args

# Tools the rubric agent may use: enough to learn what entities exist and how
# values are stored. run_sql_query is added only with with_sql=True.
RUBRIC_TOOLS = {"list_tables", "describe_table", "get_column_values",
                "search_context", "read_documentation"}

RUBRIC_SYSTEM = """You are the planning half of a two-person team answering a question \
against a SQL database. A second analyst will write and run the SQL. Your job is \
narrower: before any query is written, work out what the FINAL RESULT TABLE should look \
like — its rows, columns and data types — so the analyst can check their answer against \
it. You do not compute the answer{sql_clause}.

Why this matters: the answer is graded by comparing the submitted table with a reference \
table. An analyst who finds the right numbers still fails when the table has the wrong \
set of rows or lacks a column — for example returning a supporting breakdown when one \
value was asked for, leaving out entities that have no matching data when the question \
asked about each of them, or omitting one of several quantities the question requested. \
Extra columns do no harm; a missing column or a wrong set of rows does.

What to work out
1. Row grain — what one row of the final result stands for ("one row per customer", \
"a single row holding the answer").
2. Row count — only what the question itself fixes: exactly 1, exactly N (when the \
question states N), or one per <entity>. For "one per entity", say whether entities with \
no matching data still need a row. You may use the tools to see how many such entities \
exist; report that as context, not as a target, because the analyst's filters may \
legitimately change it.
3. Columns — every quantity or attribute the question asks to see gets its own column, \
plus whatever identifies each row. List only those: leave out intermediate or \
supporting quantities (counts, totals, components of a ratio) that the question does \
not ask to see. For each column give what it holds, its type (integer / decimal / \
text / date / boolean), and any format that the question or the documentation states \
(rounding, percentage versus fraction, date format, units).
4. Ordering — only if the question's own words ask for one. Needing to sort in order \
to find a top-N or a maximum is the analyst's method, not a requested ordering; in \
that case write "not specified".
5. Open points — at most three, one sentence each, and only about the shape of the \
result: how many rows, which columns, what format. Questions about which table, \
column, filter or definition to use are not open points; leave them to the analyst.

Stay out of
- values, expected numbers, or any guess at the answer;
- SQL, joins, which tables or columns to use, or how to compute anything;
- how to interpret filters, definitions or business terms — the analyst owns that;
- constraints the question does not state: do not add an ordering, a row limit, a \
rounding, or "only these columns" of your own.

Confidence
Give a confidence for the rows and, separately, for the columns:
- high: the question's wording fixes it.
- medium: the most natural reading, but another reading is possible.
- low: you cannot tell from the question and the schema. Say what would settle it; the \
analyst will explore and decide. If the row count is not fixed by the question, the \
row confidence cannot be high.
The analyst treats "high" as a requirement, so a wrong "high" costs more than an honest \
"low". When you are unsure, say so and describe the alternatives instead of picking one.

You have at most {max_turns} turns. Use tools only for things that affect the shape: \
what identifies an entity, how a date or category is stored, how many distinct \
categories exist, what the documentation says about the output. Then call submit_rubric \
— it must be your only tool call in that message.
{doc_hint}
Database: {db_name}

Question: {question}
{extra_context}"""

SQL_CLAUSE_OFF = ", and you cannot run SQL"
SQL_CLAUSE_ON = (". You can run SQL, but only to learn things that affect the shape "
                 "(how many entities exist, whether a key is unique, how a value is "
                 "stored) — never to work towards the answer itself")

RUBRIC_DOC_HINT = ("\nThis question comes with a documentation file. Read it with "
                   "read_documentation: it may define the output or its format.\n")

RUBRIC_USER_START = "Begin. Inspect what you need, then call submit_rubric."

RUBRIC_LAST_TURN = ("This is your last turn. Call submit_rubric now with what you "
                    "have; mark anything you could not settle as low confidence.")

_CONF = {"type": "string", "enum": ["high", "medium", "low"]}

SUBMIT_RUBRIC = {"type": "function", "function": {
    "name": "submit_rubric",
    "description": "Submit the expected shape of the final result table.",
    "parameters": {"type": "object", "properties": {
        "row_grain": {"type": "string",
                      "description": "What one row of the final result stands for."},
        "row_count": {"type": "string",
                      "description": "What the question fixes about the number of rows, "
                                     "e.g. 'exactly 1', 'exactly 5', 'one per product "
                                     "category, including categories with no sales', "
                                     "'not fixed by the question'."},
        "exact_rows": {"type": ["integer", "null"],
                       "description": "The row count as a number ONLY when the question "
                                      "itself fixes it (a single answer, a stated top-N). "
                                      "Otherwise null."},
        "rows_confidence": _CONF,
        "columns": {"type": "array", "items": {"type": "object", "properties": {
            "holds": {"type": "string", "description": "What the column contains."},
            "type": {"type": "string",
                     "enum": ["integer", "decimal", "text", "date", "boolean"]},
            "format": {"type": "string",
                       "description": "Stated format, or '' when none is stated."}},
            "required": ["holds", "type"]}},
        "columns_confidence": _CONF,
        "ordering": {"type": "string",
                     "description": "Requested ordering, or 'not specified'."},
        "open_points": {"type": "array", "items": {"type": "string"},
                        "description": "Shape questions left open, each with the "
                                       "alternatives and what would settle it."}},
        "required": ["row_grain", "row_count", "exact_rows", "rows_confidence",
                     "columns", "columns_confidence", "ordering", "open_points"]}}}


def run_rubric(question: str, session: ToolSession, llm: LLMConfig, cfg: AgentConfig,
               extra_context: str = "", max_turns: int = 5,
               with_sql: bool = False) -> dict:
    """Returns {"rubric": dict | None, "turns": int, "trace": [...], "error": str | None}."""
    t0 = time.time()
    client = OpenAI(base_url=llm.base_url, api_key=llm.api_key, timeout=llm.timeout)
    allowed = RUBRIC_TOOLS | ({"run_sql_query"} if with_sql else set())
    tools = [t for t in build_tool_schemas(cfg, has_docs=session.doc_text is not None,
                                           has_search=session.search is not None)
             if t["function"]["name"] in allowed] + [SUBMIT_RUBRIC]
    system = RUBRIC_SYSTEM.format(
        max_turns=max_turns, sql_clause=SQL_CLAUSE_ON if with_sql else SQL_CLAUSE_OFF,
        db_name=session.db.sqlite_path.stem, question=question,
        doc_hint=RUBRIC_DOC_HINT if session.doc_text else "",
        extra_context=extra_context)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": RUBRIC_USER_START}]
    out = {"rubric": None, "turns": 0, "trace": [], "error": None, "system": system}
    extra_body = ({"chat_template_kwargs": llm.chat_template_kwargs}
                  if llm.chat_template_kwargs else None)

    for turn in range(max_turns):
        out["turns"] = turn + 1
        last = turn == max_turns - 1
        if last:
            messages.append({"role": "user", "content": RUBRIC_LAST_TURN})
        try:
            resp = client.chat.completions.create(
                model=llm.model, messages=messages, tools=tools,
                tool_choice=({"type": "function", "function": {"name": "submit_rubric"}}
                             if last else "auto"),
                temperature=llm.temperature, max_tokens=llm.max_tokens,
                extra_body=extra_body)
        except Exception as e:
            out["error"] = f"llm_call: {e}"
            break
        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []
        assistant = {"role": "assistant", "content": msg.content or ""}
        if tool_calls:
            assistant["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name,
                              "arguments": tc.function.arguments}} for tc in tool_calls]
        messages.append(assistant)
        out["trace"].append({"turn": turn, "assistant": assistant})

        submit = next((tc for tc in tool_calls
                       if tc.function.name == "submit_rubric"), None)
        if submit:
            args = parse_tool_args(submit.function.arguments)
            if "__parse_error__" in args:
                out["error"] = "submit_rubric arguments were not valid JSON"
            else:
                out["rubric"] = args
            break
        if not tool_calls:
            messages.append({"role": "user",
                             "content": "Use the tools, or call submit_rubric."})
            continue
        for tc in tool_calls:
            args = parse_tool_args(tc.function.arguments)
            if tc.function.name not in allowed:
                res = f"ERROR: tool {tc.function.name!r} is not available to you."
            elif "__parse_error__" in args:
                res = "ERROR: could not parse tool arguments as JSON."
            else:
                res = session.dispatch(tc.function.name, args)
            if len(res) > cfg.max_tool_result_chars:
                res = res[: cfg.max_tool_result_chars] + "\n[result truncated]"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": res})
            out["trace"].append({"turn": turn, "tool": tc.function.name,
                                 "args": args, "result": res})
    out["wall_seconds"] = round(time.time() - t0, 1)
    return out


def render_rubric(rubric: dict) -> str:
    """Section appended to the main agent's system prompt."""
    lines = [
        "",
        "## Expected output shape",
        "A separate planner drafted this from the question and schema. It ran no SQL "
        "and describes only the shape of the result, not values or method.",
        f"Rows (confidence: {rubric.get('rows_confidence', 'low')}): "
        f"{rubric.get('row_grain', '')} — {rubric.get('row_count', '')}",
        f"Columns (confidence: {rubric.get('columns_confidence', 'low')}), at minimum:",
    ]
    for i, c in enumerate(rubric.get("columns") or [], 1):
        fmt = (c.get("format") or "").strip()
        lines.append(f"  {i}. {c.get('holds', '')} ({c.get('type', '')}"
                     + (f"; {fmt}" if fmt else "") + ")")
    lines.append(f"Ordering: {rubric.get('ordering') or 'not specified'}")
    opens = [o for o in (rubric.get("open_points") or []) if str(o).strip()]
    if opens:
        lines.append("Open points for you to settle by exploring:")
        lines += [f"  - {o}" for o in opens]
    lines.append(
        "How to use it: before submitting, compare your result with this. Where the "
        "confidence is high and your result differs, re-read the question and resolve "
        "the difference. Where it is medium or low, decide from what you find in the "
        "data. Columns beyond these are fine.")
    return "\n".join(lines)


def load_rubric(rubric_dir, instance_id: str) -> dict | None:
    from pathlib import Path
    p = Path(rubric_dir) / f"{instance_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text()).get("rubric")
