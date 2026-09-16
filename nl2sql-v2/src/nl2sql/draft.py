"""draft_sql backend: one-call SQL drafting by a specialist model (e.g.
Arctic-Text2SQL-R1). The specialist sees the full schema and the agent's
request; the agent verifies/refines the returned draft."""

import re

from openai import OpenAI

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_SQL_BLOCK_RE = re.compile(r"```sql\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_ANY_BLOCK_RE = re.compile(r"```\s*(.*?)```", re.DOTALL)

_PROMPT = """You are an expert SQL analyst. Write ONE SQLite SELECT query for the \
request below.

Database schema:
{schema}

Request: {request}

Think step by step, then output the final SQLite query in a ```sql code block."""


class DraftSQL:
    def __init__(self, base_url: str, model: str, schema_text: str,
                 max_tokens: int = 8192, timeout: float = 600.0):
        self.client = OpenAI(base_url=base_url, api_key="EMPTY", timeout=timeout)
        self.model = model
        self.schema_text = schema_text
        self.max_tokens = max_tokens

    def draft(self, request: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": _PROMPT.format(
                schema=self.schema_text, request=request)}],
            temperature=0.0, max_tokens=self.max_tokens)
        text = _THINK_RE.sub("", resp.choices[0].message.content or "")
        blocks = _SQL_BLOCK_RE.findall(text) or _ANY_BLOCK_RE.findall(text)
        sql = blocks[-1].strip() if blocks else text.strip()
        if not sql:
            return "The specialist returned no SQL; try rephrasing the request."
        return ("Specialist draft (SQLite dialect — verify with run_sql_query, "
                "adapt to DuckDB if needed):\n```sql\n" + sql + "\n```")
