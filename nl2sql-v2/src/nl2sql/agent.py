"""The episode loop: plain OpenAI-SDK tool calling against vLLM."""

import json
import re
import time
from dataclasses import dataclass, field

import pandas as pd
from openai import OpenAI

from . import critic as critic_mod
from .config import AgentConfig, CriticConfig, LLMConfig
from .prompts import (DOC_HINT, MEMORY_PREFIX, SEARCH_HINT_FULL,
                      SEARCH_HINT_SEARCH, SUMMARIZE_PROMPT, SYSTEM_PROMPT,
                      USER_START)
from .tools import ToolSession, build_tool_schemas, parse_tool_args

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


@dataclass
class EpisodeResult:
    pred_df: pd.DataFrame | None
    sql: str | None
    status: str                      # submitted | fallback | no_sql | error
    steps: int = 0
    critic_rounds: int = 0
    search_calls: int = 0
    error: str | None = None
    trace: list = field(default_factory=list)
    wall_seconds: float = 0.0
    system: str = ""


def _strip_think(content: str | None) -> str | None:
    return _THINK_RE.sub("", content) if content else content


def _history_chars(messages: list[dict]) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages)


def _truncate_tool_msgs(messages: list[dict], cfg: AgentConfig, keep_last: int) -> None:
    """Emergency fallback: blunt truncation of tool results, oldest first."""
    tool_msgs = [m for m in messages[2:] if m.get("role") == "tool"]
    for m in tool_msgs[: len(tool_msgs) - keep_last if keep_last else None]:
        if len(str(m.get("content") or "")) > cfg.truncated_tool_msg_chars:
            m["content"] = (str(m["content"])[: cfg.truncated_tool_msg_chars]
                            + "\n[truncated to save context]")
            if _history_chars(messages) <= cfg.history_char_budget:
                return


def _serialize_turns(msgs: list[dict], per_result_cap: int = 1500,
                     total_cap: int = 45_000) -> str:
    parts = []
    for m in msgs:
        role = m.get("role")
        content = str(m.get("content") or "")
        if role == "assistant":
            calls = ", ".join(
                f"{tc['function']['name']}({tc['function']['arguments'][:400]})"
                for tc in m.get("tool_calls", []))
            parts.append(f"ASSISTANT: {content[:600]}" + (f"\nCALLS: {calls}" if calls else ""))
        elif role == "tool":
            parts.append(f"RESULT: {content[:per_result_cap]}")
        else:  # earlier [MEMORY] note — carry its facts into the new summary
            parts.append(content[:4000])
    text = "\n".join(parts)
    return text[-total_cap:]


def _compact_memory(messages: list[dict], cfg: AgentConfig, client, llm: LLMConfig,
                    trace: list) -> None:
    """LLM-summary memory: fold turns older than the last `keep_recent_turns`
    into a [MEMORY] note; recent turns stay verbatim with full tool results.
    System prompt (question, constraints) is never touched. Falls back to
    blunt truncation if summarization fails."""
    if _history_chars(messages) <= cfg.history_char_budget:
        return
    turn_starts = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    if len(turn_starts) > cfg.keep_recent_turns:
        cut = turn_starts[-cfg.keep_recent_turns]
        old = messages[2:cut]
        if old:
            try:
                extra_body = ({"chat_template_kwargs": llm.chat_template_kwargs}
                              if llm.chat_template_kwargs else None)
                resp = client.chat.completions.create(
                    model=llm.model,
                    messages=[{"role": "user",
                               "content": SUMMARIZE_PROMPT + _serialize_turns(old)}],
                    temperature=0.0, max_tokens=cfg.summary_max_tokens,
                    extra_body=extra_body)
                summary = (resp.choices[0].message.content or "").strip()
                summary = _THINK_RE.sub("", summary)
                if summary:
                    messages[2:cut] = [{"role": "user",
                                        "content": MEMORY_PREFIX + summary}]
                    trace.append({"memory_compaction": {
                        "folded_msgs": len(old), "summary_chars": len(summary),
                        "history_chars_after": _history_chars(messages),
                        "summary": summary}})
            except Exception as e:
                trace.append({"memory_compaction": {"error": str(e)[:200]}})
    if _history_chars(messages) > cfg.history_char_budget:
        _truncate_tool_msgs(messages, cfg, keep_last=1)


def run_episode(question: str, session: ToolSession, llm: LLMConfig,
                cfg: AgentConfig, critic_cfg: CriticConfig | None = None,
                extra_context: str = "") -> EpisodeResult:
    t0 = time.time()
    client = OpenAI(base_url=llm.base_url, api_key=llm.api_key, timeout=llm.timeout)
    critic_client = None
    if critic_cfg and critic_cfg.enabled:
        critic_client = OpenAI(base_url=critic_cfg.base_url or llm.base_url,
                               api_key=llm.api_key, timeout=llm.timeout)

    has_search = session.search is not None and cfg.context_mode == "search"
    tools = build_tool_schemas(cfg, has_docs=session.doc_text is not None,
                               has_search=has_search,
                               has_draft=session.draft is not None)
    system = SYSTEM_PROMPT.format(
        search_hint=SEARCH_HINT_SEARCH if has_search else SEARCH_HINT_FULL,
        doc_hint=DOC_HINT if session.doc_text else "",
        max_steps=cfg.max_steps,
        db_name=session.db.sqlite_path.stem,
        question=question,
        extra_context=extra_context,
    )
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": USER_START},
    ]
    result = EpisodeResult(pred_df=None, sql=None, status="no_sql", system=system)
    extra_body = ({"chat_template_kwargs": llm.chat_template_kwargs}
                  if llm.chat_template_kwargs else None)

    ctx_retried_step = -1
    for step in range(cfg.max_steps):
        result.steps = step + 1
        _compact_memory(messages, cfg, client, llm, result.trace)
        try:
            resp = client.chat.completions.create(
                model=llm.model, messages=messages, tools=tools,
                temperature=llm.temperature, max_tokens=llm.max_tokens,
                extra_body=extra_body,
            )
        except Exception as e:
            if "maximum context length" in str(e) and ctx_retried_step != step:
                ctx_retried_step = step
                _truncate_tool_msgs(messages, cfg, keep_last=1)
                continue
            result.status, result.error = "error", f"llm_call: {e}"
            break

        msg = resp.choices[0].message
        assistant: dict = {"role": "assistant",
                           "content": _strip_think(msg.content) or ""}
        tool_calls = msg.tool_calls or []
        if tool_calls:
            assistant["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name,
                              "arguments": tc.function.arguments}}
                for tc in tool_calls]
        messages.append(assistant)
        result.trace.append({"step": step, "assistant": assistant})

        if not tool_calls:
            if cfg.text_sql_fallback:
                # text-protocol shim for models without tool training (e.g.
                # Arctic): execute the last ```sql block in the reply as if it
                # were a run_sql_query call and feed the preview back.
                blocks = re.findall(r"```sql\s*(.*?)```",
                                    assistant["content"], re.DOTALL | re.IGNORECASE)
                if blocks:
                    out = session.dispatch("run_sql_query", {"sql": blocks[-1].strip()})
                    if len(out) > cfg.max_tool_result_chars:
                        out = out[: cfg.max_tool_result_chars] + "\n[result truncated]"
                    result.trace.append({"step": step, "tool": "run_sql_query(text)",
                                         "args": {"sql": blocks[-1].strip()},
                                         "result": out})
                    messages.append({"role": "user", "content":
                                     "Result of your SQL:\n" + out +
                                     "\nIf this correctly answers the question, reply "
                                     "with exactly DONE. Otherwise write an improved "
                                     "SQL query in a ```sql block."})
                    continue
                if re.search(r"\bDONE\b", assistant["content"]) and session.query_results:
                    qid = max(session.query_results, key=lambda q: int(q[1:]))
                    result.sql, result.pred_df = session.query_results[qid]
                    result.status = "submitted"
                    break
            messages.append({"role": "user", "content":
                             "Continue using tools. When done, call submit_result."})
            continue

        submit_call = next((tc for tc in tool_calls
                            if tc.function.name == "submit_result"), None)
        if submit_call and len(tool_calls) > 1:
            for tc in tool_calls:
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": "ERROR: submit_result must be the only "
                                            "tool call in the message."})
            continue

        if submit_call:
            args = parse_tool_args(submit_call.function.arguments)
            sub = session.get_submission(str(args.get("query_id", "")))
            if sub is None:
                messages.append({"role": "tool", "tool_call_id": submit_call.id,
                                 "content": f"ERROR: unknown query_id "
                                            f"{args.get('query_id')!r}. Run the query "
                                            f"first and use its query_id."})
                continue
            sql, df = sub
            if critic_client and result.critic_rounds < critic_cfg.max_rounds:
                verdict = critic_mod.review(
                    critic_client, critic_cfg, question, sql,
                    df.head(12).to_csv(index=False), session.doc_text)
                result.critic_rounds += 1
                result.trace.append({"step": step, "critic": verdict.__dict__})
                if not verdict.approve:
                    messages.append({
                        "role": "tool", "tool_call_id": submit_call.id,
                        "content": "A reviewer flagged issues with this answer:\n"
                                   f"{verdict.feedback}\n"
                                   "Address them (or, if you are confident the review "
                                   "is wrong, submit the same query_id again)."})
                    continue
            result.pred_df, result.sql, result.status = df, sql, "submitted"
            break

        for tc in tool_calls:
            args = parse_tool_args(tc.function.arguments)
            if "__parse_error__" in args:
                out = "ERROR: could not parse tool arguments as JSON."
            else:
                out = session.dispatch(tc.function.name, args)
            if len(out) > cfg.max_tool_result_chars:
                out = (out[: cfg.max_tool_result_chars]
                       + "\n[result truncated; narrow your query]")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
            result.trace.append({"step": step, "tool": tc.function.name,
                                 "args": args, "result": out})

    if result.status == "no_sql" and session.query_results:
        # recursion budget exhausted: fall back to the last executed query
        qid = max(session.query_results, key=lambda q: int(q[1:]))
        result.sql, result.pred_df = session.query_results[qid][0], session.query_results[qid][1]
        result.status = "fallback"

    result.search_calls = session.search_calls
    result.wall_seconds = time.time() - t0
    return result
